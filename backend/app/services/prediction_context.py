"""预测上下文：把预测时刻可见的 MTF / 订单流 / 行情摘要挂到 prediction_id 上。

只写旁路表，不改 predictions / prediction_results / 回验状态机。
"""
from __future__ import annotations

from typing import Optional

from app.services.db_store import SignalDB


class PredictionContextService:
    def __init__(self) -> None:
        self._db = SignalDB()

    def record(self, prediction_id: int, symbol: str, timeframe: Optional[str],
               signal: Optional[dict] = None, price: Optional[float] = None) -> None:
        """在预测落库后调用；MTF / 订单流未预热时对应字段写 null。"""
        # 延迟导入，避免 market_service → prediction_context → mtf/orderflow → market_service 的循环
        from app.services.multi_timeframe_service import multi_timeframe_service
        from app.services.order_flow_service import order_flow_service

        mtf = multi_timeframe_service.get(symbol)
        flow = order_flow_service.get(symbol)

        mtf_resonance = None if mtf.get("pending") else mtf.get("resonance")
        mtf_alignment = None if mtf.get("pending") else mtf.get("alignment")
        mtf_payload = None
        if not mtf.get("pending"):
            mtf_payload = {
                "primary_timeframe": mtf.get("primary_timeframe"),
                "resonance": mtf.get("resonance"),
                "alignment": mtf.get("alignment"),
                "counter_trend": mtf.get("counter_trend"),
                "weighted_score": mtf.get("weighted_score"),
                "timeframes": [
                    {"timeframe": row.get("timeframe"), "direction": row.get("direction"),
                     "score": row.get("score"), "regime": row.get("regime")}
                    for row in mtf.get("timeframes") or []
                ],
            }

        orderflow_bias = flow.get("flow_bias") if flow.get("available") else None
        orderflow_payload = None
        if flow.get("available"):
            orderflow_payload = {
                "window": flow.get("window"),
                "delta_ratio": flow.get("delta_ratio"),
                "book_imbalance": (flow.get("book") or {}).get("imbalance"),
                "flow_bias": flow.get("flow_bias"),
                "quality": flow.get("quality"),
            }

        analysis = (signal or {}).get("analysis")
        market_payload = None
        if signal:
            market_payload = {
                "price": price,
                "direction": getattr(analysis, "direction", None),
                "score": getattr(analysis, "score", None),
                "level": getattr(analysis, "level", None),
                "regime": signal.get("regime"),
                "atr": signal.get("atr14"),
            }

        self._db.save_prediction_context(
            prediction_id=prediction_id,
            symbol=symbol,
            timeframe=timeframe,
            mtf_resonance=mtf_resonance,
            mtf_alignment=mtf_alignment,
            mtf=mtf_payload,
            orderflow_bias=orderflow_bias,
            orderflow=orderflow_payload,
            market=market_payload,
        )

    def summary(self, symbol: Optional[str] = None, start: Optional[str] = None,
                end: Optional[str] = None, min_sample: int = 30) -> dict:
        return self._db.context_summary(symbol=symbol, start=start, end=end, min_sample=min_sample)


prediction_context_service = PredictionContextService()
