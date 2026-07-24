"""v2.2 决策依据记录（Decision Trace）与趋势可信度（Confidence）"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class DecisionTraceItem:
    """单个指标对决策的贡献记录"""
    indicator: str         # 指标名称: "ema", "rsi", "macd", "oi", "volume", "funding"
    direction: str         # 该指标指向的方向: "LONG"/"SHORT"/"NEUTRAL"
    contribution: float    # 贡献分数 (0~该维度的最大值)
    weight: float          # 该指标的权重占比 (0~1)
    description: str       # 简要说明


@dataclass
class DecisionTrace:
    """v2.2 决策依据记录"""
    symbol: str
    timestamp: str
    direction: str             # 最终方向
    score: int                 # 最终评分
    items: List[DecisionTraceItem] = field(default_factory=list)
    summary: str = ""          # 决策摘要
    trend_phase: dict = field(default_factory=dict)  # v2.2：趋势阶段


def build_decision_trace(symbol: str, analysis: 'AnalysisResult', inputs: dict) -> DecisionTrace:
    """
    根据 AnalysisResult 和原始信号构建 DecisionTrace。

    Args:
        analysis: AnalysisResult 对象（包含 components, direction, score, indicators）
        inputs: 原始信号 dict（包含 ema20, ema60, rsi14, oi_change_pct, funding_rate, candles 等）

    Returns:
        DecisionTrace 对象
    """
    components = analysis.components
    indicators = analysis.indicators
    direction = analysis.direction
    score = analysis.score
    timestamp = analysis.timestamp

    items: List[DecisionTraceItem] = []

    # ── 1. EMA ──
    ema20 = inputs.get("ema20") or indicators.get("ema20")
    ema60 = inputs.get("ema60") or indicators.get("ema60")
    if ema20 is not None and ema60 is not None:
        ema_dir = "LONG" if ema20 > ema60 else "SHORT"
        items.append(DecisionTraceItem(
            indicator="ema",
            direction=ema_dir,
            contribution=float(components.get("trend", 0)),
            weight=0.30,
            description=f"EMA20({ema20:.0f}) {'>' if ema20 > ema60 else '<'} EMA60({ema60:.0f})，{'偏多' if ema_dir == 'LONG' else '偏空'}",
        ))

    # ── 2. RSI ──
    rsi_val = inputs.get("rsi14") or indicators.get("rsi14")
    if rsi_val is not None:
        if rsi_val > 70:
            rsi_dir = "SHORT"
            rsi_desc = f"RSI {rsi_val:.2f}，超买区，偏空"
        elif rsi_val < 30:
            rsi_dir = "LONG"
            rsi_desc = f"RSI {rsi_val:.2f}，超卖区，偏多"
        else:
            rsi_dir = "NEUTRAL"
            rsi_desc = f"RSI {rsi_val:.2f}，中性区间"
        items.append(DecisionTraceItem(
            indicator="rsi",
            direction=rsi_dir,
            contribution=float(components.get("trend", 0)),
            weight=0.15,
            description=rsi_desc,
        ))

    # ── 3. MACD ──
    macd_data = indicators.get("macd", {}) or {}
    macd_diff = macd_data.get("diff")
    macd_dea = macd_data.get("dea")
    if macd_diff is not None and macd_dea is not None:
        macd_dir = "LONG" if macd_diff > macd_dea else "SHORT"
        cross_word = "金叉偏多" if macd_dir == "LONG" else "死叉偏空"
        items.append(DecisionTraceItem(
            indicator="macd",
            direction=macd_dir,
            contribution=float(components.get("momentum", 0)),
            weight=0.20,
            description=f"MACD DIF({macd_diff:.0f}) {'>' if macd_diff > macd_dea else '<'} DEA({macd_dea:.0f})，{cross_word}",
        ))

    # ── 4. OI ──
    oi_change = inputs.get("oi_change_pct") or indicators.get("oi_change_pct", 0) or 0
    if oi_change > 0:
        oi_dir = "LONG"
        oi_word = "增仓偏多"
    elif oi_change < 0:
        oi_dir = "SHORT"
        oi_word = "减仓偏空"
    else:
        oi_dir = "NEUTRAL"
        oi_word = "OI无变化"
    items.append(DecisionTraceItem(
        indicator="oi",
        direction=oi_dir,
        contribution=float(components.get("oi", 0)),
        weight=0.10,
        description=f"OI {oi_change:+.3f}%，{oi_word}",
    ))

    # ── 5. Volume ──
    candles = inputs.get("candles", [])
    vol_ratio = 1.0
    if candles and len(candles) > 0:
        try:
            current_vol = float(candles[-1].get("volume", 0) or 0)
            recent_vols = [float(c.get("volume", 0) or 0) for c in candles[-20:]]
            avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        except (ValueError, ZeroDivisionError):
            vol_ratio = 1.0

    vol_dir = direction if vol_ratio > 1.0 else direction  # direction itself indicates the signal
    vol_word = "高于" if vol_ratio > 1.0 else "低于"
    items.append(DecisionTraceItem(
        indicator="volume",
        direction=vol_dir if vol_ratio > 1.0 else "NEUTRAL",
        contribution=float(components.get("volume", 0)),
        weight=0.15,
        description=f"成交量{vol_word}均值 {vol_ratio:.1f}x，{'确认趋势' if vol_ratio > 1.0 else '趋势减弱'}",
    ))

    # ── 6. Funding Rate ──
    funding_rate = inputs.get("funding_rate") or indicators.get("funding_rate", 0) or 0
    if funding_rate > 0.01:
        fr_dir = "SHORT"
        fr_desc = f"费率 {funding_rate:.3f}%，多头过热偏空"
    elif funding_rate < -0.01:
        fr_dir = "LONG"
        fr_desc = f"费率 {funding_rate:.3f}%，空头过热偏多"
    else:
        fr_dir = "NEUTRAL"
        fr_desc = f"费率 {funding_rate:.3f}%，正常"
    items.append(DecisionTraceItem(
        indicator="funding",
        direction=fr_dir,
        contribution=float(components.get("funding", 0)),
        weight=0.10,
        description=fr_desc,
    ))

    # ── 摘要 ──
    descs = [item.description for item in items]
    summary = f"{symbol} {direction} {score}分，依据：" + "；".join(descs) if descs else ""

    # v2.2：趋势阶段检测
    ema20_val = inputs.get("ema20") or indicators.get("ema20")
    ema60_val = inputs.get("ema60") or indicators.get("ema60")
    trend_phase = detect_trend_phase(
        ema20=ema20_val or 0,
        ema60=ema60_val or 0,
        current_score=score,
        direction=direction,
        price=inputs.get("price", 0) or analysis.price or 0,
    )

    return DecisionTrace(
        symbol=symbol,
        timestamp=timestamp,
        direction=direction,
        score=score,
        items=items,
        summary=summary,
        trend_phase=trend_phase,
    )


def compute_confidence(analysis: 'AnalysisResult', decision_trace: DecisionTrace) -> int:
    """
    计算趋势可信度 (0-100%)。

    三因素加权：
    1. 一致性 (40%)：components 中支持最终方向的维度占比
    2. 评分强度 (35%)：score/100 归一化
    3. 波动率调整 (25%)：ATR/价格比例，波动越小可信度越高

    如果 direction 是 NEUTRAL，返回 0。

    Returns:
        int: 0-100 的可信度百分比
    """
    if analysis.direction == "NEUTRAL":
        return 0

    components = analysis.components

    # 1. 一致性 (40%)：非零评分维度占比
    total_dims = 5
    supporting_count = sum(1 for v in components.values() if v > 0)
    consistency = (supporting_count / total_dims) * 40

    # 2. 评分强度 (35%)
    score_strength = (analysis.score / 100) * 35

    # 3. 波动率调整 (25%)
    indicators = analysis.indicators
    atr14 = indicators.get("atr14") if indicators else None
    price = analysis.price or 1

    if atr14 and price > 0:
        volatility_pct = atr14 / price
    else:
        volatility_pct = 0.02  # 默认值

    if volatility_pct < 0.01:
        volatility_score = 25
    elif volatility_pct > 0.05:
        volatility_score = 5
    else:
        volatility_score = 25 - (volatility_pct - 0.01) / 0.04 * 20

    total = int(round(consistency + score_strength + volatility_score))
    return max(0, min(100, total))


# ══════════════════════════════════════════════════
# v2.2 Trend Phase 趋势阶段检测
# ══════════════════════════════════════════════════

PHASES: dict = {
    "forming": "趋势形成中",
    "confirmed": "趋势确认",
    "strengthening": "趋势强化",
    "weakening": "趋势衰减",
    "ending": "趋势结束",
    "neutral": "无趋势",
}


def detect_trend_phase(
    ema20: float = 0,
    ema60: float = 0,
    prev_ema20: float = None,
    prev_ema60: float = None,
    current_score: int = 0,
    prev_score: int = 0,
    direction: str = "NEUTRAL",
    atr: float = 0,
    price: float = 0,
) -> dict:
    """
    检测趋势阶段。

    基于 EMA 排列 + 斜率 + 评分趋势判断：
    - 趋势形成中: EMA20 刚从下向上穿过 EMA60（金叉）或从上向下穿过（死叉）
    - 趋势确认: EMA20 > EMA60 且价差扩大 + 评分上升
    - 趋势强化: EMA20/EMA60 斜率持续上升 + 评分 >= 70
    - 趋势衰减: EMA20/MA60 斜率下降 + 评分下降 >= 10
    - 趋势结束: EMA20 重新回到 EMA60 另一侧
    - 无趋势: EMA20/EMA60 反复交叉

    Returns:
        dict: {
            "phase": str,        # 阶段标识
            "phase_label": str,  # 中文名称
            "description": str,  # 简要描述
            "confidence_adjust": int,  # 置信度调整值 (-10 ~ +10)
        }
    """
    if direction == "NEUTRAL" or not ema20 or not ema60:
        return {
            "phase": "neutral",
            "phase_label": PHASES["neutral"],
            "description": "方向不明确或无有效数据",
            "confidence_adjust": 0,
        }

    gap = ema20 - ema60
    gap_pct = abs(gap) / ema60 * 100 if ema60 > 0 else 0
    bull = gap > 0  # EMA20 在 EMA60 上方

    # 检测交叉
    golden_cross = False
    dead_cross = False
    if prev_ema20 is not None and prev_ema60 is not None:
        was_bull = prev_ema20 > prev_ema60
        golden_cross = bull and not was_bull       # 金叉：刚从下向上穿过
        dead_cross = not bull and was_bull          # 死叉：刚从上向下穿过

    # EMA20 斜率（正 = 上升，负 = 下降）
    if prev_ema20 is not None:
        ema20_slope = ema20 - prev_ema20
        slope_rising = ema20_slope > 0
    else:
        ema20_slope = 0
        slope_rising = None

    score_diff = current_score - prev_score

    # ── 阶段判定 ──
    if golden_cross or dead_cross:
        # 形成中：刚交叉，价差不大或评分尚可
        if score_diff < -5:
            # 交叉但评分下降 → 可能是趋势结束
            phase = "ending"
            desc = f"EMA 反向交叉，评分下降 {abs(score_diff)} 分，趋势可能结束"
        elif gap_pct < 0.5:
            phase = "forming"
            cross_word = "金叉" if golden_cross else "死叉"
            desc = f"EMA 出现{cross_word}，趋势酝酿中"
        else:
            phase = "forming"
            cross_word = "金叉" if golden_cross else "死叉"
            desc = f"EMA {cross_word}后价差扩大至 {gap_pct:.1f}%，趋势形成中"
    elif gap_pct <= 0.3:
        phase = "forming"
        desc = f"EMA 粘合（价差 {gap_pct:.1f}%），趋势形成中"
    elif score_diff <= -10:
        phase = "weakening"
        desc = f"评分下降 {abs(score_diff)} 分，趋势动能衰减"
    elif current_score >= 70 and (slope_rising is not False):
        phase = "strengthening"
        desc = f"EMA 斜率{'向上' if slope_rising else '平稳'}，评分 {current_score} 分，趋势强化"
    elif current_score >= 60 and score_diff >= 0:
        phase = "confirmed"
        desc = f"评分 {current_score} 分{'(上升)' if score_diff > 0 else ''}，趋势确认"
    else:
        phase = "neutral"
        desc = "无显著趋势特征"

    # 置信度调整
    confidence_adjust_map = {
        "forming": -5,
        "confirmed": 5,
        "strengthening": 10,
        "weakening": -10,
        "ending": -10,
        "neutral": 0,
    }
    confidence_adjust = confidence_adjust_map.get(phase, 0)

    return {
        "phase": phase,
        "phase_label": PHASES.get(phase, ""),
        "description": desc,
        "confidence_adjust": confidence_adjust,
    }
