"""v2.2 DirectionTracker — 方向三层过滤

职责：
  第1层 趋势缓冲区 (Trend Buffer)：
    滚动记录最近 N 次原始方向判定，时间衰减加权投票输出。
  第2层 迟滞带 (Hysteresis Band)：
    方向翻转需要连续多次表决方向一致才执行。
  第3层 方向变更冷却 (Direction Cooldown)：
    方向变更后冷却期内不推送新方向。

用法：
    tracker = DirectionTracker("BTC-USDT")
    result = tracker.feed(raw_direction="SHORT", raw_score=68)
    # result => {"should_notify": false, "direction": "SHORT", "score": 68}
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional

from app.core.config import settings


class DirectionTrackerConfig:
    """方向跟踪器配置 — 从 settings 加载"""
    BUFFER_SIZE: int = settings.signal_buffer_size
    MAJORITY_RATIO: float = 0.5
    WEIGHT_DECAY_FACTOR: float = 0.85
    HYSTERESIS_LOW: int = settings.signal_hysteresis_low
    HYSTERESIS_HIGH: int = settings.signal_hysteresis_high
    NEUTRAL_CONFIRM: int = settings.signal_confirm_count
    DIRECTION_CONFIRM: int = settings.signal_confirm_count
    FLIP_CONFIRM: int = settings.signal_flip_count
    COOLDOWN_MINUTES: int = settings.signal_cooldown_minutes_v2


# 全局配置实例（允许外部覆盖）
config = DirectionTrackerConfig()


@dataclass
class DirectionTracker:
    """方向跟踪器（每个币种一个实例）"""

    symbol: str
    buffer: deque = field(default_factory=lambda: deque(maxlen=config.BUFFER_SIZE))
    published_direction: str = "NEUTRAL"
    published_score: int = 0
    direction_streak: int = 0           # 当前表决方向的连续次数
    streak_target: str = "NEUTRAL"      # 正在累计的方向
    cooldown_until: float = 0.0         # 冷却结束时间戳
    pending_direction: Optional[str] = None  # 冷却期间待推送的方向

    def feed(self, raw_direction: str, raw_score: int) -> Dict:
        """
        输入原始判定 → 返回 stabilized 结果

        Returns:
            dict: {
                "should_notify": bool,  # 是否可推送方向变更提醒
                "direction": str,        # 当前已发布的稳定方向
                "score": int,            # 当前已发布的稳定评分
            }
        """
        # ─── 第1层：趋势缓冲区（时间衰减加权投票） ───
        self.buffer.append(raw_direction)
        majority_dir = self._majority_vote()
        if majority_dir is None:
            majority_dir = raw_direction  # 平局时取最新

        # ─── 第2层：迟滞带 ───
        current = self.published_direction

        if majority_dir == current:
            # 表决方向不变 → 重置累计
            self.direction_streak = 0
            self.streak_target = "NEUTRAL"
            return self._result(False, current, raw_score)

        # 表决方向已变 → 累计连续次数
        if self.streak_target != majority_dir:
            self.streak_target = majority_dir
            self.direction_streak = 1
        else:
            self.direction_streak += 1

        # 判断所需连续次数
        if current == "NEUTRAL":
            # NEUTRAL → SHORT 或 LONG
            required = config.DIRECTION_CONFIRM
        elif majority_dir == "NEUTRAL":
            # SHORT/LONG → NEUTRAL
            required = config.NEUTRAL_CONFIRM
        else:
            # SHORT ↔ LONG 翻转
            required = config.FLIP_CONFIRM

        if self.direction_streak < required:
            return self._result(False, current, raw_score)

        # ─── 第3层：冷却期 ───
        now = time.time()
        if now < self.cooldown_until:
            self.pending_direction = majority_dir
            return self._result(False, current, raw_score)

        # ✅ 执行方向变更
        self.published_direction = majority_dir
        self.published_score = raw_score
        self.direction_streak = 0
        self.streak_target = "NEUTRAL"
        self.cooldown_until = now + config.COOLDOWN_MINUTES * 60
        self.pending_direction = None
        return self._result(True, majority_dir, raw_score)

    def _majority_vote(self) -> Optional[str]:
        """缓冲区时间衰减加权投票（越新的信号权重越大）"""
        if not self.buffer:
            return None
        weights: Dict[str, float] = {}
        buf_size = len(self.buffer)
        for i, direction in enumerate(self.buffer):
            weight = config.WEIGHT_DECAY_FACTOR ** (buf_size - 1 - i)
            weights[direction] = weights.get(direction, 0.0) + weight
        total_weight = sum(weights.values())
        best_dir = max(weights, key=weights.get)
        best_weight = weights[best_dir]
        if best_weight / total_weight <= config.MAJORITY_RATIO:
            return None
        return best_dir

    def _result(self, should_notify: bool, direction: str, score: int) -> Dict:
        return {
            "should_notify": should_notify,
            "direction": direction,
            "score": score,
        }

    def reset(self) -> None:
        """重置跟踪器（用于切换配置等）"""
        self.buffer.clear()
        self.published_direction = "NEUTRAL"
        self.published_score = 0
        self.direction_streak = 0
        self.streak_target = "NEUTRAL"
        self.cooldown_until = 0.0
        self.pending_direction = None
