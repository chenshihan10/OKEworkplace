"""V2.6 实盘只读服务：拉取账户摘要 / 持仓 / 配置 / 成交，缓存并提供给路由层。

降级原则（与实施方案第 8.2 节一致）：
- 未启用或未配置 Key：不发起任何请求，`available=false` 且带原因；
- 网络/代理失败：保留上一轮内存与库数据，标 `stale=true`，绝不解释为 0 余额或空仓；
- 鉴权/时钟错误：退避 5 分钟，避免高频重试触发风控；
- 单资源失败不影响其他资源；所有外部请求都收敛在后台调度里，GET 接口只读缓存。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.account_store import AccountStore
from app.services.okx_private_client import OKXPrivateClient, OKXPrivateError

logger = logging.getLogger(__name__)

FILLS_OVERLAP_MS = 60 * 1000      # 增量拉取向前重叠 1 分钟，主键去重
FILLS_MAX_PAGES = 20              # 单轮最多 2000 条，防止首次回看拖住调度
AUTH_BACKOFF_SECONDS = 300
FAILURE_BACKOFF_THRESHOLD = 3


def _to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccountService:
    RESOURCES = ("summary", "positions", "config", "fills")

    def __init__(self, store: Optional[AccountStore] = None,
                 client: Optional[OKXPrivateClient] = None) -> None:
        self._store = store
        self._client = client or OKXPrivateClient(
            settings.private_read_base_url or settings.oke_base_url,
            settings.private_read_api_key,
            settings.private_read_secret_key.get_secret_value(),
            settings.private_read_passphrase.get_secret_value(),
        )
        self._resources: Dict[str, Dict] = {
            name: self._blank_resource() for name in self.RESOURCES
        }
        self._cache: Dict[str, object] = {
            "summary": None,
            "positions": None,   # None=尚未刷新；[]=确实空仓
            "config": None,
        }
        self._cursor: Optional[int] = None
        self._snapshot_at: Dict[str, Optional[datetime]] = {
            "summary": None, "positions": None,
        }
        self._last_prune: Optional[Dict] = None
        self._last_refresh_at: Optional[datetime] = None
        if store is not None:
            self._load_persisted()

    @property
    def store(self) -> AccountStore:
        """延迟建库：未启用/未配置时首页轮询也不会落下空的 live_account.db。"""
        if self._store is None:
            self._store = AccountStore()
            self._load_persisted()
        return self._store

    def _load_persisted(self) -> None:
        self._cursor = self._load_cursor()
        self._cache["config"] = self.store.get_config()

    # ─── 状态工具 ──────────────────────────────────────
    @staticmethod
    def _blank_resource() -> Dict:
        return {
            "available": False, "stale": False,
            "updated_at": None, "error": None, "error_code": None,
            "failures": 0, "next_attempt_at": None,
        }

    def _load_cursor(self) -> Optional[int]:
        raw = self.store.get_state("fills_cursor")
        try:
            return int(raw) if raw else None
        except (TypeError, ValueError):
            return None

    @property
    def enabled(self) -> bool:
        return bool(settings.private_read_enabled)

    @property
    def configured(self) -> bool:
        return self._client.is_configured()

    def _gate_reason(self) -> Optional[str]:
        if not self.enabled:
            return "未启用实盘只读"
        if not self.configured:
            return "未配置只读 API Key"
        return None

    def _blocked(self, resource: str) -> bool:
        next_attempt = self._resources[resource]["next_attempt_at"]
        if not next_attempt:
            return False
        try:
            return datetime.fromisoformat(next_attempt) > _now()
        except ValueError:
            return False

    def _mark_ok(self, resource: str) -> None:
        info = self._resources[resource]
        info.update({
            "available": True, "stale": False, "updated_at": _now().isoformat(),
            "error": None, "error_code": None, "failures": 0, "next_attempt_at": None,
        })

    def _mark_failure(self, resource: str, exc: Exception, has_data: bool) -> None:
        info = self._resources[resource]
        info["failures"] += 1
        info["error"] = str(exc)
        info["error_code"] = getattr(exc, "code", "") or None
        info["stale"] = bool(has_data)
        info["available"] = bool(has_data)

        delay = 0
        if getattr(exc, "is_auth_error", False) or getattr(exc, "needs_clock_check", False):
            delay = AUTH_BACKOFF_SECONDS
        elif info["failures"] >= FAILURE_BACKOFF_THRESHOLD:
            delay = min(300, 30 * 2 ** (info["failures"] - FAILURE_BACKOFF_THRESHOLD))
        info["next_attempt_at"] = (
            (_now() + timedelta(seconds=delay)).isoformat() if delay else None
        )
        logger.warning("account %s failed (attempt %d): %s",
                       resource, info["failures"], exc)

    # ─── 摘要 ──────────────────────────────────────────
    def refresh_summary(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["summary"]["error"] = reason
            return self._resources["summary"]
        if self._blocked("summary"):
            return self._resources["summary"]

        try:
            payload = self._client.get("/api/v5/account/balance")
            row = (payload.get("data") or [{}])[0]
            data = {
                "total_eq": _to_float(row.get("totalEq")),
                "avail_eq": _to_float(row.get("availEq")),
                "upl": _to_float(row.get("upl")),
                "imr": _to_float(row.get("imr")),
                "mmr": _to_float(row.get("mmr")),
                "mgn_ratio": _to_float(row.get("mgnRatio")),
                "ord_frozen": _to_float(row.get("ordFrozen")),
                "details": [
                    {
                        "ccy": item.get("ccy"),
                        "eq": _to_float(item.get("eq")),
                        "avail_bal": _to_float(item.get("availBal")),
                        "frozen_bal": _to_float(item.get("frozenBal")),
                        "upl": _to_float(item.get("upl")),
                        "eq_usd": _to_float(item.get("eqUsd")),
                    }
                    for item in (row.get("details") or [])
                ],
            }
            self._cache["summary"] = data
            self._mark_ok("summary")
            self._maybe_snapshot("summary", data)
        except OKXPrivateError as exc:
            self._mark_failure("summary", exc, self._cache["summary"] is not None)
        except Exception as exc:  # 解析异常也不能打断其他资源
            self._mark_failure("summary", exc, self._cache["summary"] is not None)
        return self._resources["summary"]

    # ─── 持仓 ──────────────────────────────────────────
    def refresh_positions(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["positions"]["error"] = reason
            return self._resources["positions"]
        if self._blocked("positions"):
            return self._resources["positions"]

        try:
            payload = self._client.get("/api/v5/account/positions", {"instType": "SWAP"})
            rows: List[Dict] = []
            for item in payload.get("data") or []:
                pos_raw = _to_float(item.get("pos"))
                if pos_raw is None or pos_raw == 0:
                    continue
                rows.append({
                    "inst_id": item.get("instId"),
                    "pos_side": item.get("posSide"),
                    "pos_raw": pos_raw,
                    "pos_unit": "contract",
                    "avg_px": _to_float(item.get("avgPx")),
                    "mark_px": _to_float(item.get("markPx")),
                    "upl": _to_float(item.get("upl")),
                    "upl_ratio": _to_float(item.get("uplRatio")),
                    "lever": _to_float(item.get("lever")),
                    "liq_px": _to_float(item.get("liqPx")),
                    "mgn_ratio": _to_float(item.get("mgnRatio")),
                    "mgn_mode": item.get("mgnMode"),
                    "raw": item,
                })
            self._cache["positions"] = rows
            self._mark_ok("positions")
            self._maybe_snapshot("positions", rows)
        except OKXPrivateError as exc:
            self._mark_failure("positions", exc, self._cache["positions"] is not None)
        except Exception as exc:
            self._mark_failure("positions", exc, self._cache["positions"] is not None)
        return self._resources["positions"]

    # ─── 账户配置 ──────────────────────────────────────
    def refresh_config(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["config"]["error"] = reason
            return self._resources["config"]
        if self._blocked("config"):
            return self._resources["config"]

        try:
            payload = self._client.get("/api/v5/account/config")
            row = (payload.get("data") or [{}])[0]
            data = {
                "acct_lv": row.get("acctLv"),
                "pos_mode": row.get("posMode"),
                # account/config 不返回 mgnMode，实际字段为 mgnIsoMode
                "mgn_mode": row.get("mgnMode") or row.get("mgnIsoMode"),
                "fee_taker": _to_float(row.get("feeTaker")),
                "fee_maker": _to_float(row.get("feeMaker")),
                "updated_at": _now().isoformat(),
                "raw": row,
            }
            self._cache["config"] = {k: v for k, v in data.items() if k != "raw"}
            self.store.save_config(data)
            self._mark_ok("config")
        except OKXPrivateError as exc:
            self._mark_failure("config", exc, self._cache["config"] is not None)
        except Exception as exc:
            self._mark_failure("config", exc, self._cache["config"] is not None)
        return self._resources["config"]

    # ─── 成交增量 ──────────────────────────────────────
    def sync_fills(self) -> Dict:
        reason = self._gate_reason()
        if reason:
            self._resources["fills"]["error"] = reason
            return self._resources["fills"]
        if self._blocked("fills"):
            return self._resources["fills"]

        now_ms = int(time.time() * 1000)
        begin = (self._cursor - FILLS_OVERLAP_MS) if self._cursor else (
            now_ms - settings.account_fills_initial_days * 86400 * 1000
        )
        collected: Dict[tuple, Dict] = {}
        after: Optional[int] = None

        try:
            for _ in range(FILLS_MAX_PAGES):
                params = {
                    "instType": "SWAP",
                    "begin": str(begin),
                    "end": str(now_ms),
                    "limit": "100",
                }
                if after:
                    params["after"] = str(after)
                payload = self._client.get("/api/v5/trade/fills-history", params)
                rows = payload.get("data") or []
                if not rows:
                    break

                page_ts: List[int] = []
                for item in rows:
                    ts = int(item.get("ts") or 0)
                    inst_id = item.get("instId")
                    trade_id = item.get("tradeId")
                    if not ts or not inst_id or trade_id is None:
                        continue
                    page_ts.append(ts)
                    collected[(inst_id, str(trade_id))] = {
                        "inst_id": inst_id,
                        "trade_id": str(trade_id),
                        "ord_id": item.get("ordId"),
                        "side": item.get("side"),
                        "pos_side": item.get("posSide"),
                        # fills-history 实际字段为 fillPx / fillSz；px/sz 仅作旧数据兼容
                        "px": _to_float(item.get("fillPx", item.get("px"))),
                        "sz": _to_float(item.get("fillSz", item.get("sz"))),
                        "fee": _to_float(item.get("fee")),
                        "fee_ccy": item.get("feeCcy"),
                        "ts": ts,
                        "raw": item,
                    }
                if len(rows) < 100 or not page_ts:
                    break
                oldest = min(page_ts)
                if oldest <= begin or oldest == after:
                    break
                after = oldest

            inserted = self.store.upsert_fills(list(collected.values()))
            latest = max((row["ts"] for row in collected.values()), default=0)
            if latest > (self._cursor or 0):
                self._cursor = latest
                self.store.set_state("fills_cursor", str(latest))
            self._mark_ok("fills")
            self._resources["fills"]["inserted"] = inserted
        except OKXPrivateError as exc:
            self._mark_failure("fills", exc, self._cursor is not None)
        except Exception as exc:
            self._mark_failure("fills", exc, self._cursor is not None)
        return self._resources["fills"]

    # ─── 组合刷新 ──────────────────────────────────────
    def refresh_all(self) -> Dict:
        """摘要 + 持仓（30 秒一轮）；配置与成交由各自的低频任务刷新。"""
        self.refresh_summary()
        self.refresh_positions()
        self._last_refresh_at = _now()
        return self.status()

    def prune(self) -> Dict:
        result = self.store.prune(
            settings.account_retention_days, settings.account_fills_retention_days
        )
        self._last_prune = {**result, "at": _now().isoformat()}
        return self._last_prune

    def _maybe_snapshot(self, kind: str, data) -> None:
        now = _now()
        last = self._snapshot_at.get(kind)
        if last and (now - last).total_seconds() < settings.account_snapshot_minutes * 60:
            return
        if kind == "summary":
            self.store.save_account_snapshot({**data, "created_at": now.isoformat()})
        else:
            self.store.save_position_snapshots(data)
        self._snapshot_at[kind] = now

    # ─── 只读视图 ──────────────────────────────────────
    def status(self) -> Dict:
        gate = self._gate_reason()
        resources = {
            name: {
                "available": info["available"],
                "stale": info["stale"],
                "updated_at": info["updated_at"],
                "error": info["error"],
                "error_code": info["error_code"],
            }
            for name, info in self._resources.items()
        }
        resources["fills"]["last_sync_ts"] = self._cursor
        if gate:
            for item in resources.values():
                item["error"] = item["error"] or gate
        available = bool(
            not gate and any(info["available"] for info in self._resources.values())
        )
        return {
            "available": available,
            "enabled": self.enabled,
            "configured": self.configured,
            "key_suffix": self._client.key_suffix,
            "reason": gate,
            "resources": resources,
            "updated_at": _now().isoformat() if available else None,
            "last_refresh_at": self._last_refresh_at.isoformat() if self._last_refresh_at else None,
        }

    def _view(self, resource: str, data) -> Dict:
        info = self._resources[resource]
        reason = info["error"] or self._gate_reason()
        return {
            "available": bool(info["available"] and data is not None),
            "stale": info["stale"],
            "reason": reason,
            "updated_at": info["updated_at"],
            "data": data,
        }

    def summary_view(self) -> Dict:
        return self._view("summary", self._cache["summary"])

    def positions_view(self) -> Dict:
        return self._view("positions", self._cache["positions"])

    def config_view(self) -> Dict:
        return self._view("config", self._cache["config"])

    def fills_view(self, limit: int = 50, offset: int = 0,
                   inst_id: Optional[str] = None) -> Dict:
        info = self._resources["fills"]
        result = self.store.get_fills(limit=limit, offset=offset, inst_id=inst_id)
        reason = info["error"] or self._gate_reason()
        return {
            "available": bool(not self._gate_reason()),
            "pending": self._cursor is None,
            "stale": info["stale"],
            "reason": reason,
            "updated_at": info["updated_at"],
            "total": result["total"],
            "items": result["items"],
        }

    def margin_view(self) -> Dict:
        """派生聚合，仅用于展示；不与订单页的手工记账数字合并。"""
        summary = self._cache["summary"]
        positions = self._cache["positions"] or []
        reason = self._resources["summary"]["error"] or self._gate_reason()
        if summary is None:
            return {
                "available": False, "stale": False, "reason": reason,
                "data": None,
                "sources": ["/api/v5/account/balance", "/api/v5/account/positions"],
                "display_only": True,
            }
        return {
            "available": True,
            "stale": bool(
                self._resources["summary"]["stale"] or self._resources["positions"]["stale"]
            ),
            "reason": reason,
            "updated_at": self._resources["summary"]["updated_at"],
            "data": {
                "account": {
                    "total_eq": summary.get("total_eq"),
                    "imr": summary.get("imr"),
                    "mmr": summary.get("mmr"),
                    "mgn_ratio": summary.get("mgn_ratio"),
                },
                "positions": [
                    {
                        "inst_id": row.get("inst_id"),
                        "mgn_ratio": row.get("mgn_ratio"),
                        "liq_px": row.get("liq_px"),
                    }
                    for row in positions
                ],
            },
            "sources": ["/api/v5/account/balance", "/api/v5/account/positions"],
            "display_only": True,
        }

    def stats(self) -> Dict:
        return {
            "store": self.store.stats(),
            "last_prune": self._last_prune,
            "cursor": self._cursor,
        }


_instance: Optional[AccountService] = None


def get_account_service() -> AccountService:
    """延迟初始化：功能关闭时连 live_account.db 都不创建。"""
    global _instance
    if _instance is None:
        _instance = AccountService()
    return _instance
