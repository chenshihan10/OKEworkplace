from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.alert_store import AlertStore
from app.services.direction_tracker import DirectionTracker
from app.services.event_bus import event_bus
from app.services.db_store import SignalDB
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
        self._trackers: dict[str, DirectionTracker] = {}  # v2.2：每个币种一个方向跟踪器
        self._alerts = AlertStore(settings.signal_cooldown_minutes)
        self._db = SignalDB()  # v2.2：SQLite 持久化
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
        mark_price = self._client.fetch_mark_price(item.symbol)
        index_price = self._client.fetch_index_price(item.symbol)
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

        # v2.2：方向抖动控制 — 三层过滤
        if item.symbol not in self._trackers:
            self._trackers[item.symbol] = DirectionTracker(item.symbol)
        tracker = self._trackers[item.symbol]
        raw_dir = analysis.direction
        raw_score = analysis.score if analysis.score is not None else 0
        stabilized = tracker.feed(raw_dir, raw_score)
        # 更新分析结果为稳定方向
        signal["raw_direction"] = raw_dir  # 保留原始方向供诊断
        analysis.direction = stabilized["direction"]
        # 评分也使用稳定后的分数（实际未改变，保持与原始评分一致）
        # 但标记是否发生过方向变更
        signal["direction_changed"] = stabilized["should_notify"]

        # v2.2：标记价格 / 指数价格
        mark_px = mark_price.get("mark_price", 0) or 0
        idx_px = index_price.get("index_price", 0) or 0
        signal["mark_price"] = mark_px
        signal["index_price"] = idx_px
        signal["mark_index_spread"] = round(mark_px - idx_px, 2) if idx_px else 0
        signal["mark_index_spread_pct"] = round((mark_px - idx_px) / idx_px * 100, 4) if idx_px else 0

        self._latest_prices[item.symbol] = ticker
        self._latest_signals_cache[item.symbol] = signal
        self._prev_cvd[item.symbol] = cvd

        # v2.2：保存信号到 SQLite
        try:
            self._db.save_signal(item.symbol, signal)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save signal to DB: %s", e)

        # v2.2：Event Bus 发布事件
        try:
            event_bus.publish("signal:updated", {"symbol": item.symbol, "signal": signal})
            event_bus.publish("price:updated", {"symbol": item.symbol, "price": ticker})
        except Exception:
            pass

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
        """v2.2 告警：使用 5 分档去重键 + 2 分钟冷却期"""
        price = ticker["price"]
        analysis = signal.get("analysis")
        if not analysis:
            return

        direction = analysis.direction
        score = analysis.score
        level = analysis.level

        if direction == "NEUTRAL" or score < 60:
            return

        # v2.2：使用 5 分档去重键（替代 v2.1 的价格级去重）
        key = AlertStore.make_key(symbol, direction, score)
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

        # v2.2：保存分析快照到 SQLite
        try:
            components = analysis.components or {}
            self._db.save_analysis_snapshot(symbol, components)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save analysis snapshot: %s", e)


market_service = MarketService()
