"""v2.2 告警去重优化

v2.1 问题：
  去重键使用 f"{symbol}:{direction}:{level}:{price}"，
  价格每 5 秒微幅变化即产生新键，导致告警堆积。

v2.2 方案：
  1. 去重键改为 f"{symbol}:{direction}:{score//5*5}"  # 按 5 分档
  2. 同一 symbol+direction 的告警，冷却期 2 分钟内不重复推送
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional


# v2.2：告警冷却时间改为 2 分钟（原为 30 分钟）
ALERT_COOLDOWN_MINUTES = 2


class AlertStore:
    def __init__(self, cooldown_minutes: int = ALERT_COOLDOWN_MINUTES) -> None:
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._last_sent: dict[str, datetime] = {}
        self._alerts: deque[dict] = deque(maxlen=200)

    @staticmethod
    def make_key(symbol: str, direction: str, score: int) -> str:
        """
        v2.2 去重键：按 5 分档，避免评分微幅波动产生新告警。
        例如 score=68 → 65, score=72 → 70
        """
        score_bin = (score // 5) * 5
        return f"{symbol}:{direction}:{score_bin}"

    def should_emit(self, key: str) -> bool:
        now = datetime.now(timezone.utc)
        last = self._last_sent.get(key)
        if last and now - last < self.cooldown:
            return False
        self._last_sent[key] = now
        return True

    def add(self, alert: dict) -> None:
        self._alerts.appendleft(alert)

    def list(self, limit: int = 20):
        return list(self._alerts)[:limit]
