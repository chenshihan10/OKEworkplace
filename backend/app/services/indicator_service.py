"""技术指标计算服务 - v2.1
提供 SMA / EMA / EMA序列 / MACD / RSI / ATR / 金叉死叉检测
"""
from __future__ import annotations

from collections import deque
from typing import List, Optional


# ══════════════════════════════════════════════════
# 基础指标
# ══════════════════════════════════════════════════

def sma(values: list, period: int) -> Optional[float]:
    """简单移动平均"""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: list, period: int) -> Optional[float]:
    """指数移动平均（返回最新值）。
    种子值使用前 period 个值的 SMA，而非第一个值（修复 v2.0 bug）。
    """
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    # 种子 = 前 period 个值的 SMA
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return round(result, 4)


def ema_series(values: list, period: int) -> List[float]:
    """返回完整 EMA 序列（用于金叉死叉检测）。
    序列长度 = len(values) - period + 1（与 seedsma 对齐）。
    """
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    seed = sum(values[:period]) / period
    series = [seed]
    for value in values[period:]:
        series.append((value - series[-1]) * multiplier + series[-1])
    return series


def macd(closes: list) -> dict:
    """MACD(12, 26, 9)。
    返回: {"diff": DIF, "dea": DEA, "histogram": DIF-DEA}
    """
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    if ema12 is None or ema26 is None:
        return {"diff": None, "dea": None, "histogram": None}

    diff = ema12 - ema26

    # 从序列计算 DEA：需要 DIF 序列
    ema12_series = ema_series(closes, 12)
    ema26_series = ema_series(closes, 26)
    if ema12_series and ema26_series:
        # 对齐长度
        min_len = min(len(ema12_series), len(ema26_series))
        diff_series = [ema12_series[i] - ema26_series[i] for i in range(min_len)]
        dea = ema(diff_series, 9)
    else:
        dea = diff  # 兜底

    histogram = round(diff - (dea or 0), 4)
    return {"diff": round(diff, 4), "dea": round(dea or diff, 4), "histogram": histogram}


def macd_series(closes: list) -> dict:
    """返回 MACD 完整序列（用于金叉死叉检测）。
    返回: {"diff_series": [...], "dea_series": [...], "histogram_series": [...]}
    """
    ema12_s = ema_series(closes, 12)
    ema26_s = ema_series(closes, 26)
    if not ema12_s or not ema26_s:
        return {"diff_series": [], "dea_series": [], "histogram_series": []}

    min_len = min(len(ema12_s), len(ema26_s))
    diff_series = [round(ema12_s[i] - ema26_s[i], 4) for i in range(min_len)]
    dea_series = ema_series(diff_series, 9)
    if dea_series:
        # 对齐：diff_series 和 dea_series 尾部对齐
        offset = len(diff_series) - len(dea_series)
        histogram_series = [
            round(diff_series[offset + i] - dea_series[i], 4)
            for i in range(len(dea_series))
        ]
    else:
        histogram_series = []

    return {
        "diff_series": diff_series,
        "dea_series": dea_series,
        "histogram_series": histogram_series,
    }


def rsi(closes: list, period: int = 14) -> Optional[float]:
    """RSI 相对强弱指标 (Wilder's smoothing)。
    返回最新值 0-100。
    """
    if len(closes) < period + 1:
        return None

    # 首期 avg_gain / avg_loss（简单平均）
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder 平滑
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def atr(candles: list, period: int = 14) -> Optional[float]:
    """ATR 平均真实波幅 (Wilder's smoothing)。
    candles: [{"high":, "low":, "close":}, ...]，需包含 close 用于计算跳空。
    返回最新 ATR 值。
    """
    if len(candles) < period + 1:
        return None

    # 计算 TR 序列
    tr_list = []
    for i in range(1, len(candles)):
        high = candles[i].get("high", 0)
        low = candles[i].get("low", 0)
        prev_close = candles[i - 1].get("close", 0)
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    if len(tr_list) < period:
        return None

    # 首期 ATR（简单平均）
    atr_val = sum(tr_list[:period]) / period

    # Wilder 平滑
    for i in range(period, len(tr_list)):
        atr_val = (atr_val * (period - 1) + tr_list[i]) / period

    return round(atr_val, 4)


def average_volume(candles: list, period: int = 20) -> Optional[float]:
    """平均成交量"""
    if len(candles) < period:
        return None
    return round(sum(c["volume"] for c in candles[-period:]) / period, 2)


# ══════════════════════════════════════════════════
# 交叉检测
# ══════════════════════════════════════════════════

def detect_ema_cross(ema20_series: list, ema60_series: list, lookback: int = 6) -> dict:
    """检测 EMA20/EMA60 金叉死叉。

    Args:
        ema20_series: EMA20 序列
        ema60_series: EMA60 序列
        lookback: 回看范围（K线根数）

    Returns:
        {"cross_type": "golden"|"dead"|None, "bars_ago": int|None, "is_recent": bool}
    """
    if len(ema20_series) < 2 or len(ema60_series) < 2:
        return {"cross_type": None, "bars_ago": None, "is_recent": False}

    # 对齐到较短序列
    min_len = min(len(ema20_series), len(ema60_series))
    ema20 = ema20_series[-min_len:]
    ema60 = ema60_series[-min_len:]

    # 在 lookback 范围内从后往前找交叉点
    search_range = min(lookback, min_len - 1)
    for offset in range(search_range):
        idx = -(offset + 2)  # 比较 idx 和 idx+1
        if idx < -len(ema20):
            break
        prev_20, prev_60 = ema20[idx], ema60[idx]
        curr_20, curr_60 = ema20[idx + 1], ema60[idx + 1]

        if prev_20 <= prev_60 and curr_20 > curr_60:
            return {"cross_type": "golden", "bars_ago": offset, "is_recent": True}
        if prev_20 >= prev_60 and curr_20 < curr_60:
            return {"cross_type": "dead", "bars_ago": offset, "is_recent": True}

    return {"cross_type": None, "bars_ago": None, "is_recent": False}


def detect_macd_cross(diff_series: list, dea_series: list, lookback: int = 6) -> dict:
    """检测 MACD DIF/DEA 金叉死叉。

    Args:
        diff_series: DIF 序列
        dea_series: DEA 序列
        lookback: 回看范围

    Returns:
        {"cross_type": "golden"|"dead"|None, "bars_ago": int|None, "is_recent": bool}
    """
    if len(diff_series) < 2 or len(dea_series) < 2:
        return {"cross_type": None, "bars_ago": None, "is_recent": False}

    # 对齐到较短序列
    min_len = min(len(diff_series), len(dea_series))
    diff = diff_series[-min_len:]
    dea = dea_series[-min_len:]

    search_range = min(lookback, min_len - 1)
    for offset in range(search_range):
        idx = -(offset + 2)
        if idx < -len(diff):
            break
        prev_diff, prev_dea = diff[idx], dea[idx]
        curr_diff, curr_dea = diff[idx + 1], dea[idx + 1]

        if prev_diff <= prev_dea and curr_diff > curr_dea:
            return {"cross_type": "golden", "bars_ago": offset, "is_recent": True}
        if prev_diff >= prev_dea and curr_diff < curr_dea:
            return {"cross_type": "dead", "bars_ago": offset, "is_recent": True}

    return {"cross_type": None, "bars_ago": None, "is_recent": False}
