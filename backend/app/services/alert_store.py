from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone


class AlertStore:
    def __init__(self, cooldown_minutes: int) -> None:
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._last_sent = {}
        self._alerts: deque[dict] = deque(maxlen=200)

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
