"""v2.1 市场评分引擎 — 五维对称评分

评分流程：
  1. 方向判定（LONG / SHORT / NEUTRAL）
  2. 在判定方向上质量评分（0-100）
  3. 风险评估（LOW / MEDIUM / HIGH）
  4. 规则解释生成

核心设计：多空评分完全对称，同一套逻辑、方向参数切换。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════

@dataclass
class AnalysisResult:
    """v2.1 统一分析输出"""
    symbol: str
    price: float
    timestamp: str

    # 核心
    score: int = 0          # 0-100
    level: str = "放弃"      # 强烈关注 / 重点关注 / 观察 / 中性 / 放弃
    direction: str = "NEUTRAL"  # LONG / SHORT / NEUTRAL

    # 风险
    risk: str = "LOW"       # LOW / MEDIUM / HIGH
    risk_factors: List[str] = field(default_factory=list)

    # 评分构成
    components: Dict[str, int] = field(default_factory=lambda: {
        "trend": 0, "momentum": 0, "volume": 0, "oi": 0, "funding": 0,
    })

    # 解释
    reasons: List[str] = field(default_factory=list)

    # 指标快照
    indicators: Dict = field(default_factory=dict)

    # 数据源
    data_source: str = "okx"


# ══════════════════════════════════════════════════
# 方向判定
# ══════════════════════════════════════════════════

def _determine_direction(
    ema20: Optional[float],
    ema60: Optional[float],
    rsi_val: Optional[float],
    macd_diff: Optional[float],
    macd_dea: Optional[float],
    oi_change_pct: float,
) -> str:
    """
    判定方向：LONG / SHORT / NEUTRAL。
    四条件中满足 ≥3 个则判定该方向，否则 NEUTRAL。
    """
    if None in (ema20, ema60, rsi_val, macd_diff, macd_dea):
        return "NEUTRAL"

    long_checks = 0
    short_checks = 0

    # EMA 排列
    if ema20 > ema60:
        long_checks += 1
    elif ema20 < ema60:
        short_checks += 1

    # RSI 区间
    if 45 <= rsi_val <= 70:
        long_checks += 1
    if 30 <= rsi_val <= 55:
        short_checks += 1

    # MACD 排列
    if macd_diff > macd_dea:
        long_checks += 1
    elif macd_diff < macd_dea:
        short_checks += 1

    # OI 验证（OI 增加说明资金在参与）
    if oi_change_pct >= 0:
        long_checks += 1
        short_checks += 1

    if long_checks >= 3:
        return "LONG"
    elif short_checks >= 3:
        return "SHORT"
    return "NEUTRAL"


# ══════════════════════════════════════════════════
# 评分维度（对称实现）
# ══════════════════════════════════════════════════

def _score_trend(
    direction: str,
    ema20: float,
    ema60: float,
    rsi_val: float,
    macd_diff: float,
    macd_dea: float,
    macd_histogram: float,
    oi_change_pct: float,
    prev_macd_histogram: Optional[float] = None,
) -> int:
    """趋势评分 (0-30)。direction 为 LONG 或 SHORT；NEUTRAL 时返回一半。"""
    if direction == "NEUTRAL":
        return 10  # 中性基础分

    score = 0

    # EMA 排列强度
    gap_pct = abs(ema20 - ema60) / ema60 * 100
    if gap_pct > 2.0:
        score += 12
    elif gap_pct > 0.5:
        score += 8
    else:
        score += 4

    # RSI 区间
    if direction == "LONG":
        if 50 <= rsi_val <= 62:
            score += 8
        elif 62 < rsi_val <= 68:
            score += 5
        elif rsi_val > 72:
            score += 2
        else:
            score += 3  # 45~50，偏弱但有方向
    else:  # SHORT
        if 38 <= rsi_val <= 50:
            score += 8
        elif 32 <= rsi_val < 38:
            score += 5
        elif rsi_val < 28:
            score += 2
        else:
            score += 3

    # MACD 状态
    if direction == "LONG":
        if macd_diff > macd_dea and macd_histogram > 0:
            # 柱线扩大还是缩小
            if prev_macd_histogram is not None and macd_histogram > prev_macd_histogram:
                score += 6  # 柱线扩大
            else:
                score += 4  # 柱线在缩小
        elif macd_diff > macd_dea:
            score += 3
        else:
            score += 1
    else:  # SHORT — 镜像
        if macd_diff < macd_dea and macd_histogram < 0:
            if prev_macd_histogram is not None and macd_histogram < prev_macd_histogram:
                score += 6  # 负柱线扩大
            else:
                score += 4
        elif macd_diff < macd_dea:
            score += 3
        else:
            score += 1

    # OI 验证
    if oi_change_pct > 0:
        score += 4
    elif oi_change_pct >= -1:
        score += 2
    # else: 0，不扣分

    return min(score, 30)


def _score_momentum(
    direction: str,
    candles: list,
    ema20: float,
    price: float,
    ema_cross_type: Optional[str],
    ema_cross_bars: Optional[int],
) -> int:
    """动量评分 (0-20)。"""
    if direction == "NEUTRAL":
        return 5

    score = 0

    # K 线动量：最近 4 根 K 线中顺势比例
    recent = candles[-4:] if len(candles) >= 4 else candles
    if direction == "LONG":
        bullish = sum(1 for c in recent if c.get("close", 0) > c.get("open", 0))
    else:
        bullish = sum(1 for c in recent if c.get("close", 0) < c.get("open", 0))

    if bullish >= 3:
        score += 8
    elif bullish == 2:
        score += 4

    # 价格位置：在 EMA20 的顺势侧
    if direction == "LONG" and price > ema20:
        score += 6
    elif direction == "SHORT" and price < ema20:
        score += 6

    # 金叉/死叉信号
    if ema_cross_type:
        on_correct_side = (
            (direction == "LONG" and ema_cross_type == "golden") or
            (direction == "SHORT" and ema_cross_type == "dead")
        )
        if on_correct_side:
            if ema_cross_bars is not None and ema_cross_bars <= 3:
                score += 6
            elif ema_cross_bars is not None and ema_cross_bars <= 6:
                score += 3

    return min(score, 20)


def _score_volume(
    direction: str,
    current_vol: float,
    avg_vol: float,
    candles: list,
    price: float,
    ema20: float,
) -> int:
    """成交量评分 (0-20)。方向中性维度。"""
    score = 0

    if avg_vol <= 0 or current_vol is None:
        return 0

    ratio = current_vol / avg_vol

    # 量能强度
    if ratio >= 2.0:
        score += 10
    elif ratio >= 1.5:
        score += 7
    elif ratio >= 1.2:
        score += 4
    elif ratio < 0.5:
        score += 0
    else:
        score += 2

    # 量价配合
    if direction in ("LONG", "SHORT"):
        # 价格是否顺势
        prev_price = candles[-2].get("close", price) if len(candles) >= 2 else price
        price_up = price > prev_price
        correct_move = (direction == "LONG" and price_up) or (direction == "SHORT" and not price_up)

        if correct_move and ratio >= 1.0:
            score += 6  # 价顺势 + 放量
        elif correct_move and ratio < 1.0:
            score += 2  # 价顺势但缩量
        elif not correct_move and ratio >= 1.5:
            score += 0  # 价逆势 + 放量（背离警告）
        else:
            score += 1

    # 突破 EMA20 且放量
    if direction == "LONG" and price > ema20 and ratio >= 1.3:
        score += 4
    elif direction == "SHORT" and price < ema20 and ratio >= 1.3:
        score += 4

    return min(score, 20)


def _score_oi(direction: str, oi_change_pct: float) -> int:
    """OI 评分 (0-20)。"""
    score = 0

    abs_oi = abs(oi_change_pct)

    # OI 变化幅度
    if abs_oi > 5:
        score += 8
    elif abs_oi > 2:
        score += 6
    elif abs_oi > 0:
        score += 3
    # else: 0

    # 价-OI 配合（需要 direction 和 oi 方向）
    if direction == "LONG":
        if oi_change_pct > 0:
            score += 8  # 价涨 OI 增 → 资金推动
        elif oi_change_pct < 0:
            score += 4  # 价涨 OI 减 → 空头回补
        else:
            score += 2
    elif direction == "SHORT":
        if oi_change_pct > 0:
            score += 8  # 价跌 OI 增 → 空头建仓
        elif oi_change_pct < 0:
            score += 4  # 价跌 OI 减 → 多头止盈
        else:
            score += 2
    else:
        score += 3  # NEUTRAL

    # OI 趋势（如果 OI 变化显著）
    if abs_oi > 3:
        score += 4

    return min(score, 20)


def _score_funding(direction: str, funding_rate: float) -> int:
    """资金费率评分 (0-10)。反向指标：对手盘拥挤 = 有利。"""
    if direction == "NEUTRAL":
        if abs(funding_rate) < 0.01:
            return 5
        return 3

    score = 0

    if direction == "LONG":
        if funding_rate < -0.03:
            score = 10  # 空头拥挤 → 可能轧空
        elif -0.01 <= funding_rate <= 0.02:
            score = 7  # 健康区间
        elif 0.02 < funding_rate <= 0.05:
            score = 4  # 偏拥挤
        elif funding_rate > 0.05:
            score = 1  # 极度拥挤
        else:
            score = 5
    else:  # SHORT — 镜像
        if funding_rate > 0.03:
            score = 10  # 多头拥挤 → 可能回调
        elif -0.02 <= funding_rate <= 0.01:
            score = 7
        elif -0.05 < funding_rate < -0.02:
            score = 4
        elif funding_rate < -0.05:
            score = 1
        else:
            score = 5

    return score


# ══════════════════════════════════════════════════
# 风险评级
# ══════════════════════════════════════════════════

def _assess_risk(
    direction: str,
    atr_val: Optional[float],
    price: float,
    funding_rate: float,
    nearest_resistance: Optional[float],
    nearest_support: Optional[float],
) -> tuple:
    """风险评估 → (risk_level, risk_factors)"""
    factors = []
    risk_score = 0  # 累积风险分，越高越危险

    # ATR 波动率
    if atr_val and price > 0:
        atr_pct = atr_val / price * 100
        if atr_pct > 4:
            risk_score += 3
            factors.append(f"ATR 偏高 ({atr_pct:.1f}%)")
        elif atr_pct > 2.5:
            risk_score += 1
            factors.append(f"ATR 中等 ({atr_pct:.1f}%)")

    # 资金费率极端
    if abs(funding_rate) > 0.05:
        risk_score += 3
        side = "多头" if funding_rate > 0 else "空头"
        factors.append(f"资金费率极端（{side}拥挤 {funding_rate:.3%}）")
    elif abs(funding_rate) > 0.03:
        risk_score += 1

    # 距离关键价位
    if direction == "LONG" and nearest_resistance and price > 0:
        distance = (nearest_resistance - price) / price * 100
        if distance < 1:
            risk_score += 2
            factors.append(f"距阻力位极近 ({distance:.1f}%)")
        elif distance < 3:
            risk_score += 1
            factors.append(f"距阻力位较近 ({distance:.1f}%)")
    elif direction == "SHORT" and nearest_support and price > 0:
        distance = (price - nearest_support) / price * 100
        if distance < 1:
            risk_score += 2
            factors.append(f"距支撑位极近 ({distance:.1f}%)")
        elif distance < 3:
            risk_score += 1
            factors.append(f"距支撑位较近 ({distance:.1f}%)")

    # 判定等级
    if risk_score >= 4:
        return "HIGH", factors
    elif risk_score >= 2:
        return "MEDIUM", factors
    return "LOW", factors


# ══════════════════════════════════════════════════
# 规则解释引擎
# ══════════════════════════════════════════════════

def _generate_reasons(
    direction: str,
    ema20: float,
    ema60: float,
    rsi_val: float,
    macd_cross_type: Optional[str],
    macd_histogram: float,
    vol_ratio: float,
    oi_change_pct: float,
    funding_rate: float,
    ema_cross_type: Optional[str],
    ema_cross_bars: Optional[int],
    price: float,
    nearest_resistance: Optional[float],
    nearest_support: Optional[float],
) -> List[str]:
    """生成规则解释数组，按重要性排序。"""
    reasons = []

    # EMA 排列
    gap = abs(ema20 - ema60) / ema60 * 100
    if ema20 > ema60 and gap > 0.5:
        reasons.append("EMA 多头排列明显" if gap > 1.5 else "EMA20 在 EMA60 上方")
    elif ema20 < ema60 and gap > 0.5:
        reasons.append("EMA 空头排列明显" if gap > 1.5 else "EMA20 在 EMA60 下方")

    # RSI
    if rsi_val > 72:
        reasons.append(f"RSI 超买 ({rsi_val})，注意回调风险")
    elif rsi_val < 28:
        reasons.append(f"RSI 超卖 ({rsi_val})，注意反弹风险")
    elif direction == "LONG" and 50 <= rsi_val <= 62:
        reasons.append(f"RSI 处于健康多头区 ({rsi_val})")
    elif direction == "SHORT" and 38 <= rsi_val <= 50:
        reasons.append(f"RSI 处于弱势区 ({rsi_val})")

    # EMA 金叉/死叉
    if ema_cross_type == "golden" and ema_cross_bars is not None and ema_cross_bars <= 6:
        reasons.append("近期出现 EMA 金叉")
    elif ema_cross_type == "dead" and ema_cross_bars is not None and ema_cross_bars <= 6:
        reasons.append("近期出现 EMA 死叉")

    # MACD
    if macd_cross_type == "golden":
        reasons.append("MACD 金叉，多头动能增强")
    elif macd_cross_type == "dead":
        reasons.append("MACD 死叉，空头动能增强")
    elif macd_histogram > 0:
        reasons.append("MACD 柱线转正，动能改善")
    elif macd_histogram < 0:
        reasons.append("MACD 柱线转负，动能减弱")

    # 成交量
    if vol_ratio >= 2.0:
        reasons.append(f"成交量激增至均量 {vol_ratio:.1f} 倍")
    elif vol_ratio >= 1.5:
        reasons.append(f"成交量放大至均量 {vol_ratio:.1f} 倍")

    # OI
    if abs(oi_change_pct) > 5:
        direction_word = "流入" if oi_change_pct > 0 else "流出"
        reasons.append(f"OI 大幅{direction_word} ({oi_change_pct:+.1f}%)")
    elif abs(oi_change_pct) > 2:
        direction_word = "增加" if oi_change_pct > 0 else "减少"
        reasons.append(f"OI {direction_word} ({oi_change_pct:+.1f}%)")

    # 资金费率
    if funding_rate < -0.03:
        reasons.append(f"资金费率极负 ({funding_rate:.3%})，空头拥挤可能轧空")
    elif funding_rate > 0.03:
        reasons.append(f"资金费率极高 ({funding_rate:.3%})，多头拥挤注意风险")

    # 关键价位
    if nearest_resistance and price > 0:
        dist = (nearest_resistance - price) / price * 100
        if dist < 2:
            reasons.append(f"价格接近阻力位 {nearest_resistance} ({dist:.1f}%)")
    if nearest_support and price > 0:
        dist = (price - nearest_support) / price * 100
        if dist < 2:
            reasons.append(f"价格接近支撑位 {nearest_support} ({dist:.1f}%)")

    return reasons


# ══════════════════════════════════════════════════
# 评分等级映射
# ══════════════════════════════════════════════════

def _score_to_level(score: int) -> str:
    if score >= 85:
        return "强烈关注"
    elif score >= 70:
        return "重点关注"
    elif score >= 55:
        return "观察"
    elif score >= 40:
        return "中性"
    return "放弃"


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

def calculate_market_score(inputs: Dict) -> AnalysisResult:
    """
    v2.1 统一分析入口。

    必需字段：
        symbol, price, timestamp, candles,
        ema20, ema60, rsi14,
        macd_diff, macd_dea, macd_histogram,
        oi_change_pct, funding_rate,
        current_vol, avg_vol,
        atr14 (可选),
        key_levels (可选), data_source (可选)

    返回：AnalysisResult（可直接序列化为 JSON）
    """
    symbol = inputs.get("symbol", "")
    price = inputs.get("price", 0.0)
    timestamp = inputs.get("timestamp", "")
    candles = inputs.get("candles", [])
    data_source = inputs.get("data_source", "okx")

    # 指标
    ema20 = inputs.get("ema20")
    ema60 = inputs.get("ema60")
    rsi_val = inputs.get("rsi14")
    macd_diff = inputs.get("macd_diff")
    macd_dea = inputs.get("macd_dea")
    macd_histogram = inputs.get("macd_histogram", 0.0) or 0.0
    oi_change_pct = inputs.get("oi_change_pct", 0.0) or 0.0
    funding_rate = inputs.get("funding_rate", 0.0) or 0.0
    current_vol = inputs.get("current_vol") or 0.0
    avg_vol = inputs.get("avg_vol") or 0.0
    atr_val = inputs.get("atr14")
    key_levels = inputs.get("key_levels", [])
    prev_macd_histogram = inputs.get("prev_macd_histogram")

    # 交叉检测结果
    ema_cross = inputs.get("ema_cross", {}) or {}
    macd_cross = inputs.get("macd_cross", {}) or {}

    # ═══ 步骤 1：方向判定 ═══
    direction = _determine_direction(
        ema20, ema60, rsi_val,
        macd_diff, macd_dea,
        oi_change_pct,
    )

    # ═══ 步骤 2：质量评分 ═══
    trend = _score_trend(
        direction, ema20 or 0, ema60 or 0, rsi_val or 50,
        macd_diff or 0, macd_dea or 0, macd_histogram,
        oi_change_pct, prev_macd_histogram,
    )
    momentum = _score_momentum(
        direction, candles, ema20 or price, price,
        ema_cross.get("cross_type"), ema_cross.get("bars_ago"),
    )
    volume = _score_volume(
        direction, current_vol, avg_vol, candles, price, ema20 or price,
    )
    oi = _score_oi(direction, oi_change_pct)
    funding = _score_funding(direction, funding_rate)

    total_score = trend + momentum + volume + oi + funding
    total_score = max(0, min(100, total_score))
    level = _score_to_level(total_score)

    # ═══ 步骤 3：风险评估 ═══
    nearest_resistance = min([l for l in key_levels if l > price], default=None)
    nearest_support = max([l for l in key_levels if l < price], default=None)

    risk, risk_factors = _assess_risk(
        direction, atr_val, price, funding_rate,
        nearest_resistance, nearest_support,
    )

    # ═══ 步骤 4：规则解释 ═══
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    reasons = _generate_reasons(
        direction,
        ema20 or price, ema60 or price,
        rsi_val or 50,
        macd_cross.get("cross_type"),
        macd_histogram,
        vol_ratio,
        oi_change_pct,
        funding_rate,
        ema_cross.get("cross_type"), ema_cross.get("bars_ago"),
        price, nearest_resistance, nearest_support,
    )

    return AnalysisResult(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        score=total_score,
        level=level,
        direction=direction,
        risk=risk,
        risk_factors=risk_factors,
        components={
            "trend": trend,
            "momentum": momentum,
            "volume": volume,
            "oi": oi,
            "funding": funding,
        },
        reasons=reasons,
        indicators={
            "ema20": ema20,
            "ema60": ema60,
            "rsi14": rsi_val,
            "macd": {"diff": macd_diff, "dea": macd_dea, "histogram": macd_histogram},
            "atr14": atr_val,
            "oi_change_pct": oi_change_pct,
            "funding_rate": funding_rate,
        },
        data_source=data_source,
    )
