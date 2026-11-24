"""V3.0 Prediction Logger：把“有方向”的判断落库，供后续 Future Validator 回验。

节流规则（避免 5 秒轮询刷表）：
  1. 只记录 direction 为 LONG / SHORT 的判断，NEUTRAL 不入库；
  2. 同一币种，方向变化时立即记录；
  3. 方向未变时，距上一条记录超过
     OKE_PREDICTION_MIN_INTERVAL_MINUTES（默认 30 分钟）才再记一条。
回验字段（verify_status/verified_at/outcome/price_after/pnl_pct）本轮留空。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.config import APP_VERSION, settings
from app.services.db_store import SignalDB
from app.services.market_regime import classify_from_signal

PRICE_TYPE = "candle_close"


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

        last = self._db.get_last_prediction(symbol)
        if last:
            if last.get("direction") == direction:
                elapsed = self._elapsed_minutes(last.get("created_at"))
                if elapsed is not None and elapsed < settings.prediction_min_interval_minutes:
                    return None

        regime = classify_from_signal(signal or {}, entry_price)
        score = self._field(analysis, "score", 0) or 0
        level = self._field(analysis, "level", "") or ""
        reasons = self._field(analysis, "reasons", []) or []
        timeframe = (signal or {}).get("timeframe") or "15m"

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
