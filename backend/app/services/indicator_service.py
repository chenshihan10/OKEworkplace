from __future__ import annotations

from collections import deque


def sma(values: list, period: int):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: list, period: int):
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = (value - result) * multiplier + result
    return result


def macd(values: list) -> dict:
    fast = ema(values, 12)
    slow = ema(values, 26)
    if fast is None or slow is None:
        return {"macd": None, "diff": None, "dea": None}
    diff = fast - slow
    dea = ema([diff] * min(len(values), 9), 9) if values else None
    return {"macd": diff - (dea or 0), "diff": diff, "dea": dea or diff}


def average_volume(candles: list, period: int = 20):
    if len(candles) < period:
        return None
    return sum(c["volume"] for c in candles[-period:]) / period
