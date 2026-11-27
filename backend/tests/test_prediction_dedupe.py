"""预测落库的 K 线去重（回归测试）。

背景：LONG/SHORT 在噪声中来回抖动时，旧逻辑「方向变化立即记录」会在一根 15m K 线里
写入上百条重复预测（2026-11-24 NVDA 15 分钟 252 条）。这里只验证去重闸门，不涉及评分。
"""
from datetime import datetime, timedelta, timezone
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.prediction_logger import PredictionLogger  # noqa: E402

CLOSED_TS_MS = 1764312300000  # 已收盘 K 线的开盘时刻（15m 边界，毫秒）
CANDLE_CLOSE_S = CLOSED_TS_MS // 1000 + 15 * 60
INTERVAL_MS = 15 * 60 * 1000


class FakeDB:
    def __init__(self, last=None):
        self.last = last
        self.saved = []

    def get_last_prediction(self, symbol):
        return self.last

    def save_prediction(self, **kwargs):
        self.saved.append(kwargs)
        return len(self.saved)


def make_signal(direction, closed_ts_ms, timeframe="15m"):
    analysis = SimpleNamespace(direction=direction, score=50, level="观察", reasons=["t"])
    candles = [
        {"ts": str(closed_ts_ms - INTERVAL_MS), "close": 100.0, "high": 101.0, "low": 99.0},
        {"ts": str(closed_ts_ms), "close": 100.0, "high": 101.0, "low": 99.0},
        {"ts": str(closed_ts_ms + INTERVAL_MS), "close": 100.5, "high": 101.0, "low": 99.0},
    ]
    return {"analysis": analysis, "timeframe": timeframe, "candles": candles, "price": 100.0}


def make_logger(last):
    logger = PredictionLogger.__new__(PredictionLogger)
    logger._db = FakeDB(last)
    return logger


def iso_after(epoch_s, seconds):
    dt = datetime.fromtimestamp(epoch_s, tz=timezone.utc) + timedelta(seconds=seconds)
    return dt.isoformat()


def test_same_candle_direction_flip_is_blocked():
    # 同一根 K 线内，方向从 SHORT 翻到 LONG，不应再写一条
    last = {"direction": "SHORT", "timeframe": "15m", "created_at": iso_after(CANDLE_CLOSE_S, 3)}
    logger = make_logger(last)
    assert logger.maybe_log("NVDA-USDT", make_signal("LONG", CLOSED_TS_MS), 100.0) is None
    assert logger._db.saved == []


def test_repeated_flips_in_one_candle_write_only_once():
    logger = make_logger(None)
    assert logger.maybe_log("NVDA-USDT", make_signal("SHORT", CLOSED_TS_MS), 100.0) == 1
    # 第一条入库后，同一根 K 线内的方向抖动都应被挡住
    logger._db.last = {"direction": "SHORT", "timeframe": "15m",
                       "created_at": iso_after(CANDLE_CLOSE_S, 3)}
    for i in range(9):
        direction = "LONG" if i % 2 else "SHORT"
        assert logger.maybe_log("NVDA-USDT", make_signal(direction, CLOSED_TS_MS), 100.0) is None
    assert len(logger._db.saved) == 1


def test_next_candle_direction_flip_is_logged():
    # 上一根 K 线记过 SHORT，本根翻成 LONG：允许记录
    last = {"direction": "SHORT", "timeframe": "15m",
            "created_at": iso_after(CANDLE_CLOSE_S - 15 * 60, 3)}
    logger = make_logger(last)
    assert logger.maybe_log("BTC-USDT", make_signal("LONG", CLOSED_TS_MS), 100.0) == 1
    assert logger._db.saved[0]["direction"] == "LONG"


def test_unknown_timeframe_falls_back_to_interval_rule():
    # 周期不可识别时不做 K 线去重，仅保留原有方向/间隔节流：方向翻转仍会记录
    last = {"direction": "SHORT", "timeframe": "7m",
            "created_at": iso_after(CANDLE_CLOSE_S, 3)}
    logger = make_logger(last)
    signal = make_signal("LONG", CLOSED_TS_MS, timeframe="7m")
    assert logger.maybe_log("BTC-USDT", signal, 100.0) == 1

