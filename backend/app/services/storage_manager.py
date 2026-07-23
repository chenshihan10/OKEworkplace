"""
Data Storage Manager - 支持多种存储策略以平衡实时性和存储压力
"""
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Any


class DataStorageManager:
    """
    管理不同的数据存储策略:
    - memory: 仅保留最新数据（低存储，快速）
    - aggregated: 保留聚合的历史数据（中等存储，平衡）
    - persistent: 持久化存储所有数据（高存储，完整历史）
    """

    def __init__(self, strategy: str = "memory", max_records: int = 100):
        self.strategy = strategy
        self.max_records = max_records
        self.current = {}  # 实时数据
        self.history = {}  # 历史数据（取决于策略）

    def store_ticker(self, symbol: str, ticker: dict) -> None:
        """存储行情数据"""
        self.current[f"{symbol}:ticker"] = {
            "data": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self.strategy in ["aggregated", "persistent"]:
            if symbol not in self.history:
                self.history[symbol] = {"tickers": deque(maxlen=self.max_records)}
            self.history[symbol]["tickers"].append(ticker)

    def store_signal(self, symbol: str, signal: dict) -> None:
        """存储信号数据"""
        self.current[f"{symbol}:signal"] = {
            "data": signal,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self.strategy in ["aggregated", "persistent"]:
            if symbol not in self.history:
                self.history[symbol] = {"signals": deque(maxlen=self.max_records)}
            if "signals" not in self.history[symbol]:
                self.history[symbol]["signals"] = deque(maxlen=self.max_records)
            self.history[symbol]["signals"].append(signal)

    def store_candles(self, symbol: str, timeframe: str, candles: list) -> None:
        """存储 K 线数据 - 仅保留最新的 K 线而不是完整历史"""
        key = f"{symbol}:{timeframe}:candles"
        self.current[key] = {
            "data": candles,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 只有在 persistent 模式下才保存 K 线历史
        if self.strategy == "persistent":
            if symbol not in self.history:
                self.history[symbol] = {}
            if "candles" not in self.history[symbol]:
                self.history[symbol]["candles"] = {}
            self.history[symbol]["candles"][timeframe] = deque(
                maxlen=self.max_records
            )
            self.history[symbol]["candles"][timeframe].extend(candles)

    def get_current(self, symbol: str) -> Dict[str, Any]:
        """获取最新的实时数据"""
        return {
            k: v["data"]
            for k, v in self.current.items()
            if k.startswith(symbol)
        }

    def get_history(self, symbol: str, data_type: str = "all") -> Dict[str, Any]:
        """获取历史数据
        
        Args:
            symbol: 币种符号
            data_type: 数据类型 ('tickers', 'signals', 'candles', 'all')
        """
        if self.strategy == "memory":
            return {}  # Memory 模式不保留历史

        if symbol not in self.history:
            return {}

        result = {}
        history = self.history[symbol]

        if data_type in ["tickers", "all"] and "tickers" in history:
            result["tickers"] = list(history["tickers"])

        if data_type in ["signals", "all"] and "signals" in history:
            result["signals"] = list(history["signals"])

        if data_type in ["candles", "all"] and "candles" in history:
            result["candles"] = {
                tf: list(candles)
                for tf, candles in history["candles"].items()
            }

        return result

    def get_stats(self) -> dict:
        """获取存储统计信息"""
        stats = {
            "strategy": self.strategy,
            "current_count": len(self.current),
            "history_symbols": list(self.history.keys()),
        }

        if self.strategy in ["aggregated", "persistent"]:
            for symbol, data in self.history.items():
                if symbol not in stats:
                    stats[symbol] = {}
                for key, value in data.items():
                    if isinstance(value, deque):
                        stats[symbol][key] = len(value)
                    elif isinstance(value, dict):
                        stats[symbol][key] = {
                            k: len(v) for k, v in value.items()
                        }

        return stats


class DataSampler:
    """数据采样器 - 用于控制采样频率以减少存储压力"""

    def __init__(self, base_interval: int = 5, sample_rates: dict = None):
        """
        Args:
            base_interval: 基础轮询间隔（秒）
            sample_rates: 采样率配置，例如 {
                'ticker': 1,     # 每次都采样
                'candles': 1,    # 每次都采样
                'trades': 5,     # 每 5 次采样 1 次
                'books': 10,     # 每 10 次采样 1 次
            }
        """
        self.base_interval = base_interval
        self.sample_rates = sample_rates or {
            "ticker": 1,
            "candles": 1,
            "trades": 5,
            "books": 10,
            "oi": 1,
            "funding": 1,
        }
        self.counters = {}

    def should_sample(self, symbol: str, data_type: str) -> bool:
        """判断是否应该采样此类型的数据"""
        key = f"{symbol}:{data_type}"
        rate = self.sample_rates.get(data_type, 1)

        if rate <= 0:
            return False  # 不采样

        if rate == 1:
            return True  # 总是采样

        self.counters[key] = self.counters.get(key, 0) + 1
        should = self.counters[key] % rate == 0
        return should

    def reset_counter(self, symbol: str, data_type: str) -> None:
        """重置计数器"""
        key = f"{symbol}:{data_type}"
        self.counters.pop(key, None)
