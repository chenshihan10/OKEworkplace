"""v2.2 Event Bus — 后端事件总线

职责：
  1. 数据采集层与分析层解耦
  2. 支持异步事件发布/订阅
  3. 为后续 WebSocket 推送提供统一接口

事件类型：
  - signal:updated   — 新信号分析完成
  - price:updated    — 价格更新
  - network:change   — 网络状态变化
  - alert:new        — 新告警产生
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class EventBus:
    """轻量级进程内事件总线（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event: str, callback: Callable) -> None:
        """订阅事件"""
        with self._lock:
            if event not in self._subscribers:
                self._subscribers[event] = []
            self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        """取消订阅"""
        with self._lock:
            if event in self._subscribers:
                self._subscribers[event] = [
                    cb for cb in self._subscribers[event] if cb is not callback
                ]

    def publish(self, event: str, data: Any = None) -> None:
        """发布事件（同步调用所有订阅者）"""
        with self._lock:
            callbacks = list(self._subscribers.get(event, []))

        for callback in callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.warning(f"EventBus: 事件 {event} 回调异常: {e}")

    def clear(self) -> None:
        """清空所有订阅"""
        with self._lock:
            self._subscribers.clear()


# 全局单例
event_bus = EventBus()
