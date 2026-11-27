"""V3.0 Prediction Logger：把“有方向”的判断落库，供后续 Future Validator 回验。

节流规则（避免 5 秒轮询刷表）：
  1. 只记录 direction 为 LONG / SHORT 的判断，NEUTRAL 不入库；
  2. 同一币种 + 同一周期，同一根 K 线只记一条（按已收盘 K 线的收盘时刻去重）；
  3. 跨 K 线后：方向变化立即记录；方向未变时，距上一条记录超过
     OKE_PREDICTION_MIN_INTERVAL_MINUTES（默认 30 分钟）才再记一条。
说明：第 2 条是硬去重。LONG/SHORT 在噪声里来回抖时会逐次触发“方向变化立即记录”，
曾出现一根 15m K 线写入 252 条的情况，因此每条记录必须先通过 K 线去重。
回验字段（verify_status/verified_at/outcome/price_after/pnl_pct）本轮留空。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.config import APP_VERSION, settings
from app.services.db_store import SignalDB
from app.services.market_regime import classify_from_signal

PRICE_TYPE = "candle_close"

# 周期 → 秒数。用于把「已收盘 K 线」换算成该 K 线的收盘时刻。
TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1H": 3600, "2H": 7200, "4H": 14400, "1D": 86400, "1W": 604800,
}


class PredictionLogger:
    def __init__(self) -> None:
        self._db = SignalDB()

    @staticmethod
    def _field(analysis, name: str, default=None):
        if analysis is None:
            return default
        if isinstance(analysis, dict):
            return analysis.get(name, default)
        return getattr(analysis, name, default)

    def maybe_log(self, symbol: str, signal: dict, price: Optional[float]) -> Optional[int]:
        """满足节流条件时写入一条预测，返回记录 ID；否则返回 None。"""
        analysis = (signal or {}).get("analysis")
        direction = self._field(analysis, "direction")
        if direction not in ("LONG", "SHORT"):
            return None

        # 价格口径统一为「K 线收盘」：取最后一根已收盘 K 线的 close，
        # 与 Future Validator 的 exit_price 口径保持一致，避免 last/close 混用。
        candles = (signal or {}).get("candles") or []
        entry_price = None
        if len(candles) >= 2:
            entry_price = float(candles[-2].get("close") or 0) or None
        elif candles:
            entry_price = float(candles[-1].get("close") or 0) or None
        if entry_price is None:
            return None

        timeframe = (signal or {}).get("timeframe") or "15m"
        close_ts = self._candle_close_ts(candles, timeframe)

        last = self._db.get_last_prediction(symbol)
        # 硬去重：同一币种 + 同一周期，同一根 K 线只允许一条。
        # created_at 是写入时刻，写入发生在 K 线收盘后几秒内，
        # 因此「上一条写入时刻 >= 本根 K 线收盘时刻」即可判定该 K 线已记过。
        if last and close_ts is not None and last.get("timeframe") == timeframe:
            last_ts = self._to_epoch(last.get("created_at"))
            if last_ts is not None and last_ts >= close_ts - 2:
                return None

        if last and last.get("direction") == direction:
            elapsed = self._elapsed_minutes(last.get("created_at"))
            if elapsed is not None and elapsed < settings.prediction_min_interval_minutes:
                return None

        regime = classify_from_signal(signal or {}, entry_price)
        score = self._field(analysis, "score", 0) or 0
        level = self._field(analysis, "level", "") or ""
        reasons = self._field(analysis, "reasons", []) or []

        return self._db.save_prediction(
            symbol=symbol,
            direction=direction,
            score=score,
            level=level,
            regime=regime.get("regime", "UNKNOWN"),
            price=entry_price,
            reasons=list(reasons)[:5],
            timeframe=timeframe,
            price_type=PRICE_TYPE,
            strategy_version=APP_VERSION,
        )

    @staticmethod
    def _candle_close_ts(candles, timeframe: str) -> Optional[float]:
        """已收盘 K 线（candles[-2]）的收盘时刻（epoch 秒）。

        candles 为升序，最后一条是正在形成的 K 线；入库价格也取 candles[-2].close，
        两者口径一致。周期未知或缺少时间戳时返回 None（退化为只按方向/间隔节流）。
        """
        secs = TIMEFRAME_SECONDS.get(timeframe)
        if not secs or len(candles) < 2:
            return None
        raw = candles[-2].get("ts")
        if raw is None:
            return None
        try:
            ts = int(float(raw))
        except (TypeError, ValueError):
            return None
        if ts > 10 ** 11:  # 毫秒时间戳
            ts //= 1000
        return ts - ts % secs + secs

    @staticmethod
    def _to_epoch(created_at: Optional[str]) -> Optional[float]:
        if not created_at:
            return None
        try:
            ts = datetime.fromisoformat(created_at)
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()

    @staticmethod
    def _elapsed_minutes(created_at: Optional[str]) -> Optional[float]:
        if not created_at:
            return None
        try:
            ts = datetime.fromisoformat(created_at)
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60


prediction_logger = PredictionLogger()
