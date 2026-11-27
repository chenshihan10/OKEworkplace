"""运行期健康监控：方向翻转频率与写入异常（只观测，不影响任何判断）。

为什么不从库里算翻转：
  预测表已经按 K 线去重，翻转过程不会落库；而 `shadow_scores` 有 5 分钟节流。
  因此翻转频率只能在刷新热路径里轻量记录（内存环形队列，重启即清零）。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

WINDOW_SECONDS = 3600          # 保留最近 1 小时事件
MAX_EVENTS_PER_SYMBOL = 1500   # 单币种上限，防止异常时内存膨胀


class DirectionMonitor:
    def __init__(self) -> None:
        # symbol -> deque[(ts, raw_direction, stable_direction)]
        self._events: Dict[str, Deque[tuple]] = defaultdict(
            lambda: deque(maxlen=MAX_EVENTS_PER_SYMBOL)
        )

    def record(self, symbol: str, raw_direction: str, stable_direction: str,
               now: float | None = None) -> None:
        ts = time.time() if now is None else now
        dq = self._events[symbol]
        dq.append((ts, raw_direction or "", stable_direction or ""))
        while dq and ts - dq[0][0] > WINDOW_SECONDS:
            dq.popleft()

    def snapshot(self, now: float | None = None) -> list:
        ts_now = time.time() if now is None else now
        items = []
        for symbol, dq in self._events.items():
            while dq and ts_now - dq[0][0] > WINDOW_SECONDS:
                dq.popleft()
            if not dq:
                continue
            raw_flips = stable_flips = 0
            flips_15m = 0
            prev_raw, prev_stable = dq[0][1], dq[0][2]
            last_change_ts = None
            for ts, raw, stable in dq:
                if raw != prev_raw:
                    raw_flips += 1
                    last_change_ts = ts
                if stable != prev_stable:
                    stable_flips += 1
                if ts_now - ts <= 900 and (raw != prev_raw or stable != prev_stable):
                    flips_15m += 1
                prev_raw, prev_stable = raw, stable
            last_ts, last_raw, last_stable = dq[-1]
            items.append({
                "symbol": symbol,
                "samples_1h": len(dq),
                "raw_flips_1h": raw_flips,
                "stable_flips_1h": stable_flips,
                "flips_15m": flips_15m,
                "last_raw_direction": last_raw,
                "last_stable_direction": last_stable,
                "last_event_age_seconds": max(0, int(ts_now - last_ts)),
                "last_flip_age_seconds": (
                    None if last_change_ts is None else max(0, int(ts_now - last_change_ts))
                ),
            })
        return sorted(items, key=lambda x: x["raw_flips_1h"], reverse=True)


direction_monitor = DirectionMonitor()


def should_alert_stale(data_age, threshold, last_alert_ts, now, cooldown_seconds: int = 600) -> bool:
    """数据停更告警判定（纯函数）：超过阈值且距上次告警达到冷却时间。"""
    if data_age is None or threshold is None or threshold <= 0 or data_age < threshold:
        return False
    return last_alert_ts is None or (now - last_alert_ts) >= cooldown_seconds
