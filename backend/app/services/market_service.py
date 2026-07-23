from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.alert_store import AlertStore
from app.models import WatchItem
from app.services.oke_client import OKEClient
from app.services.signal_engine import signal_engine

# 持久化文件路径
if getattr(sys, 'frozen', False):
    _exe_dir = Path(sys.executable).resolve().parent
    WATCHLIST_FILE = _exe_dir / "watchlist.json"
else:
    WATCHLIST_FILE = Path(__file__).resolve().parent.parent.parent / "watchlist.json"


def _load_watchlist() -> list[WatchItem]:
    try:
        if WATCHLIST_FILE.exists() and WATCHLIST_FILE.stat().st_size > 4:
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
            if data:
                return [WatchItem(**item) for item in data]
        _old_path = Path(__file__).resolve().parent.parent / "data" / "watchlist.json"
        if _old_path.exists() and _old_path.stat().st_size > 4:
            with open(_old_path, "r") as f:
                data = json.load(f)
            if data:
                items = [WatchItem(**item) for item in data]
                _save_watchlist(items)
                return items
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to load watchlist: %s", e)
    return []


def _save_watchlist(items: list[WatchItem]) -> None:
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump([item.dict() for item in items], f, indent=2)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to save watchlist: %s", e)


def _analysis_to_dict(analysis) -> dict:
    """将 AnalysisResult dataclass 转为可 JSON 序列化的 dict"""
    d = asdict(analysis)
    d["indicators"] = analysis.indicators
    d["components"] = analysis.components
    return d


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
        self._prev_oi = {}  # v2.1：记录上次 OI 值用于计算变化百分比
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

    def list_watch_items(self):
        return self._watch_items

    def list_available_coins(self):
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
        """v2.1：刷新单个币种数据"""
        ticker = self._client.fetch_ticker(item.symbol)
        candles = self._client.fetch_candles(item.symbol, item.timeframe)
        open_interest = self._client.fetch_open_interest(item.symbol)
        funding_rate = self._client.fetch_funding_rate(item.symbol)
        trades = self._client.fetch_trades(item.symbol)
        books = self._client.fetch_books(item.symbol)

        # v2.1：自行计算 OI 变化百分比（OKX API 不直接提供）
        current_oi = open_interest.get("open_interest", 0) or 0
        prev_oi = self._prev_oi.get(item.symbol)
        if prev_oi and prev_oi > 0:
            oi_change_pct = round((current_oi - prev_oi) / prev_oi * 100, 4)
        else:
            oi_change_pct = 0.0
        open_interest["change_pct"] = oi_change_pct
        self._prev_oi[item.symbol] = current_oi

        # v2.1 使用新信号引擎
        signal = signal_engine.evaluate(
            item.symbol, candles, ticker["price"], item.timeframe,
            open_interest, funding_rate, trades, books,
        )

        previous_price = self._latest_prices.get(item.symbol, {}).get("price", ticker["price"])
        ticker["previous_price"] = previous_price

        # 计算 CVD
        cvd = self._calc_cvd(trades)
        prev_cvd = self._prev_cvd.get(item.symbol, cvd)
        signal["cvd"] = cvd
        signal["cvd_change"] = cvd - prev_cvd

        # 向后兼容：old signal 格式的 flat 字段
        analysis = signal["analysis"]
        signal["macd"] = analysis.indicators.get("macd", {})
        signal["volatility"] = analysis.indicators.get("atr14") or 0

        # 向后兼容：funding_rate dict 格式（analysis.py 旧代码依赖）
        signal["funding_rate_dict"] = funding_rate or {}

        self._latest_prices[item.symbol] = ticker
        self._latest_signals_cache[item.symbol] = signal
        self._prev_cvd[item.symbol] = cvd

        self._maybe_emit_alert(item.symbol, signal, ticker)

    def refresh_all(self) -> None:
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
        """v2.1 快照：signals 中包含 AnalysisResult 序列化数据"""
        signals_for_frontend = {}
        for symbol, signal in self._latest_signals_cache.items():
            s = dict(signal)
            analysis = signal.get("analysis")
            if analysis:
                s["analysis"] = _analysis_to_dict(analysis)
            signals_for_frontend[symbol] = s

        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "watch_items": [item.dict() for item in self._watch_items],
            "prices": self._latest_prices,
            "signals": signals_for_frontend,
            "alerts": self._alerts.list(20),
        }

    def latest_signals(self):
        result = []
        for symbol, signal in self._latest_signals_cache.items():
            s = dict(signal)
            analysis = signal.get("analysis")
            if analysis:
                s["analysis"] = _analysis_to_dict(analysis)
            result.append(s)
        return result

    def _maybe_emit_alert(self, symbol: str, signal: dict, ticker: dict) -> None:
        """v2.1 告警：基于 direction + score 触发"""
        price = ticker["price"]
        analysis = signal.get("analysis")
        if not analysis:
            return

        direction = analysis.direction
        score = analysis.score
        level = analysis.level

        if direction == "NEUTRAL" or score < 60:
            return

        # 告警去重键
        key = f"{symbol}:{direction}:{level}:{round(price, 2)}"
        if not self._alerts.should_emit(key):
            return

        direction_label = "做多" if direction == "LONG" else "做空"
        alert = {
            "symbol": symbol,
            "title": f"{symbol} {direction_label}信号 ({score}分/{level})",
            "price": price,
            "trend": level,
            "reason": " ; ".join(analysis.reasons) if analysis.reasons else "",
            "timeframe": signal.get("timeframe"),
            "score": score,
            "direction_label": direction_label,
            "timestamp": analysis.timestamp,
        }
        self._alerts.add(alert)


market_service = MarketService()
