"""
v2.0 策略规则模块 — 已降级为 v2.1

v2.1 中评分逻辑已迁移至 app.model.market_score（五维对称评分）。
本模块保留仅供向后兼容，新代码应使用 signal_engine.evaluate() 获取 AnalysisResult。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.services.indicator_service import average_volume, sma


def _ema_series(values, period):
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    series = [sum(values[:period]) / period]
    for value in values[period:]:
        series.append((value - series[-1]) * alpha + series[-1])
    return series


def _macd(values):
    fast = _ema_series(values, 12)
    slow = _ema_series(values, 26)
    if not fast or not slow:
        return {"macd": None, "diff": None, "dea": None}

    diff = fast[-1] - slow[-1]
    diff_series = []
    for idx in range(min(len(fast), len(slow))):
        diff_series.append(fast[idx] - slow[idx])
    dea_series = _ema_series(diff_series, 9)
    dea = dea_series[-1] if dea_series else diff

    return {"macd": diff - dea, "diff": diff, "dea": dea}


# 信号方向标签
DIRECTION_LABELS = {
    "STRONG_BUY": "强烈做多",
    "BUY": "做多",
    "MONITOR_LONG": "关注做多",
    "NEUTRAL": "中性观望",
    "MONITOR_SHORT": "关注做空",
    "SELL": "做空",
    "STRONG_SELL": "强烈做空",
}


class TradingRules:
    def evaluate(self, symbol, candles, latest_price, timeframe,
                 open_interest=None, funding_rate=None):
        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]

        ma20 = sma(closes, 20)
        ma60 = sma(closes, 60)
        ma120 = sma(closes, 120)
        macd_data = _macd(closes)
        avg_vol = average_volume(candles, 20)
        current_vol = volumes[-1] if volumes else None
        oi_change_pct = open_interest.get("change_pct") if open_interest else None
        funding_value = funding_rate.get("funding_rate") if funding_rate else None

        # ─── 趋势判断 ───
        trend = "Neutral"
        if ma20 is not None and ma60 is not None and ma120 is not None:
            if ma20 > ma60 > ma120:
                trend = "Bullish"
            elif ma20 < ma60 < ma120:
                trend = "Bearish"

        # ─── 关键价位 ───
        key_levels = (
            settings.btc_levels if symbol.startswith("BTC")
            else settings.eth_levels if symbol.startswith("ETH")
            else []
        )
        nearest_resistance = min([lvl for lvl in key_levels if lvl >= latest_price], default=None)
        nearest_support = max([lvl for lvl in key_levels if lvl <= latest_price], default=None)

        # ─── 评分系统（正分=多头，负分=空头） ───
        score = 0
        reasons = []

        # 1. 趋势评分 (权重 ±20)
        if trend == "Bullish":
            score += 20
            reasons.append("trend_bullish")
        elif trend == "Bearish":
            score -= 20
            reasons.append("trend_bearish")

        # 2. MACD 评分 (权重 ±15)
        macd_golden = bool(macd_data["diff"] is not None and macd_data["dea"] is not None
                          and macd_data["diff"] > macd_data["dea"])
        macd_dead = bool(macd_data["diff"] is not None and macd_data["dea"] is not None
                        and macd_data["diff"] < macd_data["dea"])
        if macd_golden:
            score += 15
            reasons.append("macd_golden_cross")
        if macd_dead:
            score -= 15
            reasons.append("macd_dead_cross")

        # 3. MACD 柱强度 (权重 ±5)
        macd_hist = macd_data.get("macd")
        if macd_hist is not None:
            if macd_hist > 0:
                score += min(5, abs(macd_hist) * 2)
            elif macd_hist < 0:
                score -= min(5, abs(macd_hist) * 2)

        # 4. 成交量评分 (权重 ±10)
        vol_spike = bool(current_vol is not None and avg_vol is not None
                        and current_vol > 1.5 * avg_vol)
        vol_extreme = bool(current_vol is not None and avg_vol is not None
                          and current_vol > 2.5 * avg_vol)
        if vol_extreme:
            score += 15 if macd_golden else -15
            reasons.append("volume_extreme")
        elif vol_spike:
            score += 10 if macd_golden else -10
            reasons.append("volume_spike")

        # 5. 持仓量评分 (权重 ±10)
        oi_rising = bool(oi_change_pct is not None and oi_change_pct > 3)
        oi_strong_rising = bool(oi_change_pct is not None and oi_change_pct > 8)
        oi_falling = bool(oi_change_pct is not None and oi_change_pct < -3)
        if oi_strong_rising:
            score += 15 if trend == "Bullish" else -15
            reasons.append("oi_strong_rising")
        elif oi_rising:
            score += 10 if trend == "Bullish" else -10
            reasons.append("oi_rising")
        elif oi_falling:
            score += 5 if trend == "Bullish" else -5
            reasons.append("oi_falling")

        # 6. 资金费率评分 (权重 ±5)
        if funding_value is not None:
            if funding_value > 0.03:
                # 多头拥挤 → 潜在回调风险
                score -= 5
                reasons.append("funding_high_long")
            elif funding_value < -0.03:
                # 空头拥挤 → 潜在轧空
                score += 5
                reasons.append("funding_high_short")
            elif funding_value > 0.01:
                score -= 2
            elif funding_value < -0.01:
                score += 2

        # 7. 突破/回调评分 (权重 ±5)
        if nearest_resistance is not None and latest_price >= nearest_resistance * 0.995:
            if latest_price > nearest_resistance:
                score += 8
                reasons.append("break_above_resistance")
            else:
                score += 3
                reasons.append("near_resistance")
        if nearest_support is not None and latest_price <= nearest_support * 1.005:
            if latest_price < nearest_support:
                score -= 8
                reasons.append("break_below_support")
            else:
                score -= 3
                reasons.append("near_support")

        # ─── 映射评分到动作 ───
        action, signal_strength = self._score_to_action(score, len(reasons))

        confidence = min(0.95, 0.3 + 0.08 * len(reasons))
        confidence += abs(score) * 0.005
        confidence = min(0.98, round(confidence, 2))

        return {
            "symbol": symbol,
            "action": action,
            "direction_label": DIRECTION_LABELS.get(action, "中性观望"),
            "signal_strength": signal_strength,
            "score": score,
            "reasons": reasons,
            "confidence": confidence,
            "trend": trend,
            "ma20": ma20,
            "ma60": ma60,
            "ma120": ma120,
            "macd": macd_data,
            "volume": {"current": current_vol, "average": avg_vol, "spike": vol_spike},
            "open_interest": open_interest or {},
            "funding_rate": funding_rate or {},
            "price": latest_price,
            "timeframe": timeframe,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _score_to_action(score: int, reason_count: int) -> tuple:
        """将综合评分映射为交易动作和信号强度"""
        if score >= 40:
            return "STRONG_BUY", "⭐⭐⭐⭐"
        elif score >= 25:
            return "BUY", "⭐⭐⭐"
        elif score >= 12:
            return "MONITOR_LONG", "⭐⭐"
        elif score <= -40:
            return "STRONG_SELL", "⭐⭐⭐⭐"
        elif score <= -25:
            return "SELL", "⭐⭐⭐"
        elif score <= -12:
            return "MONITOR_SHORT", "⭐⭐"
        else:
            return "NEUTRAL", "⭐"


trading_rules = TradingRules()

