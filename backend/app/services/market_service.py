from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.alert_store import AlertStore
from app.models import WatchItem
from app.services.oke_client import OKEClient
from app.services.signal_engine import signal_engine

# 持久化文件路径
if getattr(sys, 'frozen', False):
    # EXE 模式：保存在 EXE 同目录下，避免随更新丢失
    _exe_dir = Path(sys.executable).resolve().parent
    WATCHLIST_FILE = _exe_dir / "watchlist.json"
else:
    # 开发模式：保存在 backend 目录下
    WATCHLIST_FILE = Path(__file__).resolve().parent.parent.parent / "watchlist.json"


def _load_watchlist() -> list[WatchItem]:
    """从 JSON 文件加载已保存的监控币种，自动从旧路径迁移"""
    try:
        # 1. 检查当前路径
        if WATCHLIST_FILE.exists() and WATCHLIST_FILE.stat().st_size > 4:
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
            if data:
                return [WatchItem(**item) for item in data]

        # 2. 检查旧路径 (\app\data\watchlist.json) 并迁移
        _old_path = Path(__file__).resolve().parent.parent / "data" / "watchlist.json"
        if _old_path.exists() and _old_path.stat().st_size > 4:
            with open(_old_path, "r") as f:
                data = json.load(f)
            if data:
                items = [WatchItem(**item) for item in data]
                _save_watchlist(items)  # 迁移到新路径
                return items
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load watchlist: %s", e)
    return []


def _save_watchlist(items: list[WatchItem]) -> None:
    """将监控币种保存到 JSON 文件"""
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump([item.dict() for item in items], f, indent=2)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to save watchlist: %s", e)


class MarketService:
    def __init__(self) -> None:
        saved = _load_watchlist()
        self._watch_items = saved if saved else [
            WatchItem(symbol="BTC-USDT", alias="Bitcoin", timeframe=settings.default_timeframes[1]),
            WatchItem(symbol="ETH-USDT", alias="Ethereum", timeframe=settings.default_timeframes[1]),
        ]
        self._latest_prices = {}
        self._latest_signals_cache = {}
        self._prev_cvd = {}
        self._alerts = AlertStore(settings.signal_cooldown_minutes)
        self._client = OKEClient(settings.oke_base_url, settings.oke_api_key, settings.oke_secret_key)
        self._executor = ThreadPoolExecutor(max_workers=10)

    @staticmethod
    def _calc_cvd(trades: list) -> float:
        total = 0.0
        for trade in trades:
            size = float(trade.get("size", 0) or 0)
            if trade.get("side") == "buy":
                total += size
            elif trade.get("side") == "sell":
                total -= size
        return total

    @staticmethod
    def _calc_volatility(candles: list) -> float:
        closes = [float(c.get("close", 0) or 0) for c in candles if c.get("close")]
        if len(closes) < 2:
            return 1.5
        returns = []
        for idx in range(1, len(closes)):
            prev = closes[idx - 1]
            if prev:
                returns.append(abs((closes[idx] - prev) / prev * 100))
        if not returns:
            return 1.5
        return round(sum(returns) / len(returns), 2)

    def list_watch_items(self):
        return self._watch_items

    def list_available_coins(self):
        """返回 OKX 所有可交易的 USDT 永续合约"""
        return self._client.fetch_all_tickers()

    def add_watch_item(self, item: WatchItem) -> WatchItem:
        self._watch_items = [x for x in self._watch_items if x.symbol != item.symbol]
        self._watch_items.append(item)
        _save_watchlist(self._watch_items)
        return item

    def remove_watch_item(self, symbol: str) -> None:
        self._watch_items = [x for x in self._watch_items if x.symbol != symbol]
        self._latest_prices.pop(symbol, None)
        self._latest_signals_cache.pop(symbol, None)
        _save_watchlist(self._watch_items)

    def _refresh_one(self, item: WatchItem) -> None:
        """刷新单个币种的数据（内部方法，可并发调用）"""
        ticker = self._client.fetch_ticker(item.symbol)
        candles = self._client.fetch_candles(item.symbol, item.timeframe)
        open_interest = self._client.fetch_open_interest(item.symbol)
        funding_rate = self._client.fetch_funding_rate(item.symbol)
        trades = self._client.fetch_trades(item.symbol)
        books = self._client.fetch_books(item.symbol)
        signal = signal_engine.evaluate(
            item.symbol, candles, ticker["price"], item.timeframe,
            open_interest, funding_rate
        )

        previous_price = self._latest_prices.get(item.symbol, {}).get("price", ticker["price"])
        ticker["previous_price"] = previous_price

        cvd = self._calc_cvd(trades)
        prev_cvd = self._prev_cvd.get(item.symbol, cvd)
        oi_change_pct = (open_interest or {}).get("change_pct", 0) or 0

        signal["candles"] = candles
        signal["ema20"] = signal.get("ma20") or 0
        signal["ema60"] = signal.get("ma60") or 0
        signal["ema120"] = signal.get("ma120") or 0
        signal["oi_change_pct"] = oi_change_pct
        signal["cvd"] = cvd
        signal["cvd_change"] = cvd - prev_cvd
        signal["volatility"] = self._calc_volatility(candles)
        signal["trades"] = trades[:20]
        signal["books"] = books

        self._latest_prices[item.symbol] = ticker
        self._latest_signals_cache[item.symbol] = signal
        self._prev_cvd[item.symbol] = cvd
        self._maybe_emit_alert(item.symbol, signal, ticker)

    def refresh_all(self) -> None:
        """并发刷新所有币种数据"""
        futures = {
            self._executor.submit(self._refresh_one, item): item
            for item in self._watch_items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                future.result()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    "Refresh failed for %s: %s", item.symbol, e
                )

    def snapshot(self) -> dict:
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "watch_items": [item.dict() for item in self._watch_items],
            "prices": self._latest_prices,
            "signals": self._latest_signals_cache,
            "alerts": self._alerts.list(20),
        }

    def latest_signals(self):
        return list(self._latest_signals_cache.values())

    def _maybe_emit_alert(self, symbol: str, signal: dict, ticker: dict) -> None:
        price = ticker["price"]
        action = signal.get("action", "NEUTRAL")
        key = f"{symbol}:{action}:{signal.get('signal_strength')}:{round(price, 2)}"
        if action in ("NEUTRAL",) or not self._alerts.should_emit(key):
            return
        alert = {
            "symbol": symbol,
            "title": f"{symbol} {signal.get('direction_label', '')} {action}",
            "price": price,
            "trend": signal.get("trend", "Neutral"),
            "reason": signal.get("reason", ""),
            "timeframe": signal.get("timeframe"),
            "score": signal.get("score", 0),
            "direction_label": signal.get("direction_label", "中性观望"),
            "timestamp": signal.get("timestamp"),
        }
        self._alerts.add(alert)


market_service = MarketService()
