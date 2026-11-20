"""市场状态（Market Regime）分类

V3.0 预测闭环的前置模块：先回答"现在是什么市场"，后续的 Prediction Logger /
Future Validator 才有语境（同样的信号在震荡市命中率天然更低）。

纯规则实现，不引入新依赖。四分类：
  - HIGH_VOLATILITY 高波动：ATR14 / 价格 >= atr_high_pct
  - BULL            牛市：EMA20 > EMA60 > EMA120，且 EMA20 与 EMA120 分离度 >= 阈值
  - BEAR            熊市：EMA20 < EMA60 < EMA120，且分离度 >= 阈值
  - RANGE           震荡：其余情况（均线纠缠或排列不一致）

阈值可用环境变量覆盖，便于回测调参：
  OKE_REGIME_ATR_HIGH_PCT        ATR 占价格百分比阈值，默认 2.5
  OKE_REGIME_EMA_SEPARATION_PCT  EMA20/EMA120 分离度阈值(%)，默认 0.3
"""
from __future__ import annotations

import os
from typing import Dict, Optional

REGIME_LABELS = {
    "BULL": "牛市",
    "BEAR": "熊市",
    "RANGE": "震荡",
    "HIGH_VOLATILITY": "高波动",
    "UNKNOWN": "数据不足",
}


def thresholds() -> Dict[str, float]:
    """当前生效阈值（每次读取，便于运行期调参）"""
    return {
        "atr_high_pct": float(os.getenv("OKE_REGIME_ATR_HIGH_PCT", "2.5")),
        "ema_separation_pct": float(os.getenv("OKE_REGIME_EMA_SEPARATION_PCT", "0.3")),
    }


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return round(value, digits) if value is not None else None


def classify(
    price: Optional[float],
    ema20: Optional[float],
    ema60: Optional[float],
    ema120: Optional[float],
    atr14: Optional[float],
) -> Dict:
    """根据现有指标判定市场状态。

    返回结构：
      regime    BULL / BEAR / RANGE / HIGH_VOLATILITY / UNKNOWN
      label     中文标签
      atr_pct   ATR 占价格百分比
      ema_spread_pct  EMA20 相对 EMA120 的偏离百分比（正=多头排列）
      reasons   判定依据（可直接展示）
      thresholds 本次判定使用的阈值
    """
    t = thresholds()
    result = {
        "regime": "UNKNOWN",
        "label": REGIME_LABELS["UNKNOWN"],
        "atr_pct": None,
        "ema_spread_pct": None,
        "reasons": [],
        "thresholds": t,
    }

    if not price or price <= 0:
        result["reasons"].append("缺少有效价格，无法判定")
        return result

    atr_pct = (atr14 / price * 100) if atr14 else None
    result["atr_pct"] = _round(atr_pct)

    if ema20 and ema120:
        result["ema_spread_pct"] = _round((ema20 - ema120) / ema120 * 100)
    elif ema20 and ema60:
        # EMA120 数据不足时以 EMA60 为基准
        result["ema_spread_pct"] = _round((ema20 - ema60) / ema60 * 100)

    # 1. 高波动优先：波动率过高时，趋势判断本身不稳定
    if atr_pct is not None and atr_pct >= t["atr_high_pct"]:
        result["regime"] = "HIGH_VOLATILITY"
        result["label"] = REGIME_LABELS["HIGH_VOLATILITY"]
        result["reasons"].append(
            f"ATR 占价格 {atr_pct:.2f}%，达到高波动阈值 {t['atr_high_pct']}%"
        )
        return result

    # 2. 均线数据不完整时降级：优先三均线，其次双均线
    has_three = bool(ema20 and ema60 and ema120)
    has_two = bool(ema20 and ema60)

    if not has_two:
        result["regime"] = "RANGE"
        result["label"] = REGIME_LABELS["RANGE"]
        result["reasons"].append("EMA 数据不足（至少需要 EMA20/EMA60），按震荡处理")
        return result

    if has_three:
        bullish = ema20 > ema60 > ema120
        bearish = ema20 < ema60 < ema120
        spread_pct = abs((ema20 - ema120) / ema120 * 100)
        spread_note = f"EMA20 与 EMA120 分离 {spread_pct:.2f}%"
    else:
        # 120 根 K 线不足时用双均线近似，分离度以 EMA60 为基准
        bullish = ema20 > ema60
        bearish = ema20 < ema60
        spread_pct = abs((ema20 - ema60) / ema60 * 100)
        spread_note = f"EMA20 与 EMA60 分离 {spread_pct:.2f}%（EMA120 数据不足，按双均线判定）"

    if bullish and spread_pct >= t["ema_separation_pct"]:
        result["regime"] = "BULL"
        result["label"] = REGIME_LABELS["BULL"]
        result["reasons"].append(f"均线多头排列，{spread_note}")
        return result

    if bearish and spread_pct >= t["ema_separation_pct"]:
        result["regime"] = "BEAR"
        result["label"] = REGIME_LABELS["BEAR"]
        result["reasons"].append(f"均线空头排列，{spread_note}")
        return result

    result["regime"] = "RANGE"
    result["label"] = REGIME_LABELS["RANGE"]
    if bullish or bearish:
        result["reasons"].append(
            f"均线方向一致但 {spread_note}，低于阈值 {t['ema_separation_pct']}%，按震荡处理"
        )
    else:
        result["reasons"].append("EMA 排列不一致（均线纠缠）")
    return result


def classify_from_signal(signal: Dict, price: Optional[float]) -> Dict:
    """从信号字典（signal_engine 输出）直接判定"""
    signal = signal or {}
    return classify(
        price=price if price is not None else signal.get("price"),
        ema20=signal.get("ema20"),
        ema60=signal.get("ema60"),
        ema120=signal.get("ema120"),
        atr14=signal.get("atr14"),
    )
