"""V3.0 Future Validator：到期方向预测的自动回验。

口径（全项目统一）：
- 时间：一律 ISO 8601 UTC 字符串（带 +00:00），与 predictions.created_at 一致；
- 价格：predictions.price / 回验 exit_price 均为 **K 线收盘价**（price_type=candle_close），
  入场取预测时最后一根已收盘 K 线的 close，回验取 horizon 到期所在 K 线的 close；
- 回验只做方向评估，不代表真实成交或账户收益。

状态机：
- verified：数据完整并完成计算；
- insufficient_data：K 线窗口覆盖不足（含停机过久）或数据缺口，**不计为亏损**；
- invalid：价格跳变（如合约重定价）或数据异常，隔离且不计入统计；
- failed：取数/计算异常，保留记录，10 分钟后自动重试；
- pending：未到期，不写入结果表。

触发方式：随 APScheduler 每 60 秒扫描一次（首跑提前到启动后约 30 秒，等价于启动补算）。
单实例：以数据目录下的 validator.lock 互斥；锁超过 10 分钟视为残留并接管。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.core.config import settings
from app.services.db_store import SignalDB
from app.services.oke_client import OKEClient

HORIZONS = {"30m": 30, "1h": 60, "4h": 240}
PRICE_TYPE = "candle_close"
LOCK_STALE_SECONDS = 10 * 60
FAILED_RETRY_SECONDS = 10 * 60


class FutureValidator:
    def __init__(self) -> None:
        self._db = SignalDB()
        self._client = OKEClient(settings.oke_base_url, settings.oke_api_key, settings.oke_secret_key)
        self._lock_path = os.path.join(os.path.dirname(self._db.db_path), "validator.lock")
        self.last_run: Dict = {
            "at": None,
            "due": 0,
            "verified": 0,
            "insufficient_data": 0,
            "invalid": 0,
            "failed": 0,
            "skipped_locked": False,
        }

    # ─── 锁 ────────────────────────────────────────────
    def _acquire_lock(self) -> bool:
        try:
            if os.path.exists(self._lock_path):
                if time.time() - os.path.getmtime(self._lock_path) < LOCK_STALE_SECONDS:
                    return False
                os.remove(self._lock_path)
            fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            logging.getLogger(__name__).warning("validator lock failed: %s", exc)
            return False

    def _release_lock(self) -> None:
        try:
            os.remove(self._lock_path)
        except OSError:
            pass

    # ─── 主流程 ────────────────────────────────────────
    def verify_due(self) -> Dict:
        if not self._acquire_lock():
            self.last_run = {**self.last_run, "at": datetime.now(timezone.utc).isoformat(),
                             "skipped_locked": True}
            return self.last_run

        stats = {"at": datetime.now(timezone.utc).isoformat(), "due": 0, "verified": 0,
                 "insufficient_data": 0, "invalid": 0, "failed": 0, "skipped_locked": False}
        try:
            now = datetime.now(timezone.utc)
            # failed 结果超过重试间隔后清除，重新进入队列
            self._db.purge_stale_failed_results(
                (now - timedelta(seconds=FAILED_RETRY_SECONDS)).isoformat()
            )
            cutoff = (now - timedelta(minutes=min(HORIZONS.values()))).isoformat()
            predictions = self._db.get_verifiable_predictions(cutoff, limit=200)
            existing = self._db.get_result_keys([p["id"] for p in predictions]) if predictions else {}

            for pred in predictions:
                for horizon, minutes in HORIZONS.items():
                    if (pred["id"], horizon) in existing:
                        continue
                    created = self._parse(pred.get("created_at"))
                    if created is None:
                        continue
                    due = created + timedelta(minutes=minutes)
                    if due > now:
                        continue
                    stats["due"] += 1
                    status = self._verify_one(pred, horizon, created, due)
                    if status in stats:
                        stats[status] += 1
        except Exception as exc:
            logging.getLogger(__name__).warning("validator run failed: %s", exc)
            stats["error"] = str(exc)
        finally:
            self._release_lock()

        self.last_run = stats
        return stats

    def _verify_one(self, pred: Dict, horizon: str, created: datetime, due: datetime) -> str:
        symbol = pred["symbol"]
        timeframe = pred.get("timeframe") or "15m"
        entry_price = pred.get("price")
        if not entry_price or entry_price <= 0:
            return self._save(pred, horizon, "invalid", note="预测价格缺失或非法",
                              data_quality="invalid")

        try:
            candles = self._client.fetch_candles(symbol, timeframe)
        except Exception as exc:
            return self._save(pred, horizon, "failed", note=f"行情获取失败：{exc}")

        if not candles:
            return self._save(pred, horizon, "failed", note="行情接口返回空数据")

        parsed = []
        for c in candles:
            ts = self._parse_ts(c.get("ts"))
            if ts is not None:
                parsed.append((ts, c))
        parsed.sort(key=lambda x: x[0])
        if not parsed:
            return self._save(pred, horizon, "insufficient_data", note="K 线时间戳不可用",
                              data_quality="incomplete")

        tf_minutes = self._timeframe_minutes(timeframe)
        if parsed[0][0] > created:
            # 停机超过最近 100 根 K 线时，向前翻页回补到期区间，而不是直接判数据不足
            try:
                backfill = self._client.fetch_candles_range(
                    symbol, timeframe,
                    int((created - timedelta(minutes=tf_minutes)).timestamp() * 1000),
                    int(due.timestamp() * 1000),
                )
            except Exception as exc:
                return self._save(pred, horizon, "failed", note=f"历史行情获取失败：{exc}")
            if backfill:
                merged = {ts: c for ts, c in parsed}
                for candle in backfill:
                    ts = self._parse_ts(candle.get("ts"))
                    if ts is not None:
                        merged[ts] = candle
                parsed = sorted(merged.items(), key=lambda item: item[0])
            if parsed[0][0] > created:
                return self._save(pred, horizon, "insufficient_data",
                                  note="K 线窗口未覆盖预测时间，历史 K 线仍不可得",
                                  data_quality="incomplete")

        window = [(ts, c) for ts, c in parsed if ts > created - timedelta(minutes=tf_minutes) and ts <= due]
        if not window or window[-1][0] + timedelta(minutes=tf_minutes) < due:
            return self._save(pred, horizon, "insufficient_data", note="到期时点无可用 K 线",
                              data_quality="incomplete")

        expected = max(1, int((due - created).total_seconds() // (tf_minutes * 60)))
        if len(window) < expected - 1:
            return self._save(pred, horizon, "insufficient_data",
                              note=f"K 线缺口（{len(window)}/{expected}）",
                              data_quality="gap")

        exit_price = float(window[-1][1]["close"])
        if exit_price <= 0:
            return self._save(pred, horizon, "invalid", note="到期价格非法", data_quality="invalid")

        # 价格跳变守卫：合约重定价会让收益计算失真，直接隔离
        ratio = exit_price / float(entry_price)
        if ratio > 2 or ratio < 0.5:
            return self._save(pred, horizon, "invalid",
                              note=f"价格跳变（{entry_price}→{exit_price}），疑似合约调整",
                              entry_price=float(entry_price), exit_price=exit_price,
                              data_quality="invalid")

        highs = [float(c["high"]) for _, c in window]
        lows = [float(c["low"]) for _, c in window]
        direction = pred["direction"]
        if direction == "LONG":
            gross = exit_price / entry_price - 1
            mfe = (max(highs) - entry_price) / entry_price
            mae = (entry_price - min(lows)) / entry_price
        else:
            gross = entry_price / exit_price - 1
            mfe = (entry_price - min(lows)) / entry_price
            mae = (max(highs) - entry_price) / entry_price

        cost = 2 * (settings.verify_fee_rate + settings.verify_slippage_rate)
        net = gross - cost
        flat = settings.verify_flat_threshold_pct / 100
        if net > flat:
            outcome = "WIN"
        elif net < -flat:
            outcome = "LOSS"
        else:
            outcome = "FLAT"

        return self._save(
            pred, horizon, "verified", outcome=outcome,
            entry_price=float(entry_price), exit_price=exit_price,
            gross_return=round(gross, 6), estimated_cost=round(cost, 6),
            net_return=round(net, 6), mfe=round(mfe, 6), mae=round(mae, 6),
            data_quality="ok",
            note=f"{timeframe} K线收盘口径；成本=双边手续费+滑点 {cost:.4%}",
        )

    def _save(self, pred: Dict, horizon: str, status: str, **kwargs) -> str:
        self._db.add_prediction_result({
            "prediction_id": pred["id"],
            "symbol": pred["symbol"],
            "horizon": horizon,
            "price_type": pred.get("price_type") or PRICE_TYPE,
            "verify_status": status,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        })
        return status

    # ─── 工具 ──────────────────────────────────────────
    @staticmethod
    def _parse(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            ts = datetime.fromisoformat(value)
        except ValueError:
            return None
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    @staticmethod
    def _parse_ts(value) -> Optional[datetime]:
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _timeframe_minutes(timeframe: str) -> int:
        mapping = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
                   "1H": 60, "1h": 60, "2H": 120, "4H": 240, "4h": 240,
                   "1D": 1440, "1d": 1440}
        return mapping.get(timeframe, 15)


future_validator = FutureValidator()
