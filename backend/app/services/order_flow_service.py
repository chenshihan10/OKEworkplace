"""订单流（Order Flow）REST 采样服务。

v1 只做 REST：逐笔成交按 tradeId 去重后并入滚动窗口，叠加盘口深度失衡与大单识别。
采样必然漏单，因此响应里显式给出 sampled / trade_count / window_coverage_pct /
gap_suspected，不把采样值包装成完整逐笔；也不覆盖现有 signal["cvd"] 字段。
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.db_store import SignalDB
from app.services.market_service import market_service
from app.services.oke_client import OKEClient

BOOK_BAND_PCT = 0.5
TOP_LEVELS = 20


def _now_ms() -> int:
    return int(time.time() * 1000)


def _trade_id(trade: dict) -> str:
    return str(trade.get("tradeId") or "")


class OrderFlowService:
    def __init__(self) -> None:
        self._client = OKEClient(
            settings.oke_base_url, settings.oke_api_key, settings.oke_secret_key
        )
        self._db = SignalDB()
        self._state: Dict[str, dict] = {}
        self._cache: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="orderflow")

    # ─── 采集与计算 ───────────────────────────────────────

    @staticmethod
    def _band_depth(rows: List[list], mid: float, band_pct: float) -> float:
        if not mid:
            return 0.0
        low, high = mid * (1 - band_pct / 100), mid * (1 + band_pct / 100)
        total = 0.0
        for row in rows or []:
            try:
                price, size = float(row[0]), float(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            if low <= price <= high:
                total += size
        return total

    @staticmethod
    def _p95(values: List[float]) -> Optional[float]:
        if len(values) < 20:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
        return ordered[index]

    def _refresh_one(self, item) -> dict:
        symbol = item.symbol
        now = _now_ms()
        window_minutes = settings.orderflow_window_minutes
        window_ms = window_minutes * 60 * 1000

        raw_trades = self._client.fetch_trades(symbol, limit=500)
        books = self._client.fetch_books(symbol, sz=settings.orderflow_books_sz)
        if not raw_trades:
            return self._stale_or_empty(symbol, window_minutes, "逐笔成交取数失败或暂无成交")

        with self._lock:
            state = self._state.setdefault(symbol, {"trades": [], "session_cvd": 0.0})
            seen = {_trade_id(t) for t in state["trades"] if t.get("tradeId")}
            added = []
            for trade in raw_trades:
                trade_id = _trade_id(trade)
                ts = int(trade.get("timestamp") or 0) or now
                if trade_id and trade_id in seen:
                    continue
                if ts < now - window_ms:
                    continue
                if trade_id:
                    seen.add(trade_id)
                price = float(trade.get("price") or 0)
                size = float(trade.get("size") or 0)
                side = (trade.get("side") or "").lower()
                added.append({
                    "tradeId": trade_id or f"{ts}-{price}-{size}",
                    "ts": ts,
                    "price": price,
                    "size": size,
                    "side": side,
                    "notional": price * size,
                })
                if side == "buy":
                    state["session_cvd"] += size
                elif side == "sell":
                    state["session_cvd"] -= size

            trades = state["trades"] + added
            trades.sort(key=lambda t: t["ts"])
            trades = [t for t in trades if t["ts"] >= now - window_ms]
            state["trades"] = trades
            session_cvd = state["session_cvd"]

        buy_volume = sum(t["size"] for t in trades if t["side"] == "buy")
        sell_volume = sum(t["size"] for t in trades if t["side"] == "sell")
        delta = buy_volume - sell_volume
        total_volume = buy_volume + sell_volume
        delta_ratio = delta / total_volume if total_volume else 0.0

        # 大单：名义价值 >= max(固定阈值, 窗口 p95)
        notionals = [t["notional"] for t in trades]
        p95 = self._p95(notionals)
        threshold = max(settings.orderflow_large_trade_notional, p95 or 0)
        large = [t for t in trades if t["notional"] >= threshold]
        large_buy = sum(t["notional"] for t in large if t["side"] == "buy")
        large_sell = sum(t["notional"] for t in large if t["side"] == "sell")
        large_skew = (
            (large_buy - large_sell) / (large_buy + large_sell)
            if (large_buy + large_sell) else 0.0
        )

        # 盘口：±0.5% 价格带 + top20
        bids = books.get("bids") or []
        asks = books.get("asks") or []
        book_ok = books.get("source") != "unavailable" and bool(bids or asks)
        mid = 0.0
        if bids and asks:
            try:
                mid = (float(bids[0][0]) + float(asks[0][0])) / 2
            except (TypeError, ValueError, IndexError):
                mid = 0.0
        bid_depth = self._band_depth(bids, mid, BOOK_BAND_PCT)
        ask_depth = self._band_depth(asks, mid, BOOK_BAND_PCT)
        band_imbalance = (
            (bid_depth - ask_depth) / (bid_depth + ask_depth)
            if (bid_depth + ask_depth) else 0.0
        )
        top_bid = sum(float(r[1]) for r in bids[:TOP_LEVELS] if len(r) > 1)
        top_ask = sum(float(r[1]) for r in asks[:TOP_LEVELS] if len(r) > 1)
        top_imbalance = (
            (top_bid - top_ask) / (top_bid + top_ask) if (top_bid + top_ask) else 0.0
        )

        flow_bias = round(
            100 * (0.5 * delta_ratio + 0.3 * band_imbalance + 0.2 * large_skew), 1
        )
        flow_bias = max(-100.0, min(100.0, flow_bias))

        # 采样质量：有成交的秒数 / 窗口秒数；单轮返回 500 条视为可能漏单
        covered_seconds = len({t["ts"] // 1000 for t in trades})
        window_seconds = window_minutes * 60
        coverage = round(min(covered_seconds / window_seconds, 1.0), 3) if window_seconds else 0.0
        gap_suspected = len(raw_trades) >= 500 or not book_ok

        result = {
            "symbol": symbol,
            "window": f"{window_minutes}m",
            "window_minutes": window_minutes,
            "available": True,
            "buy_volume": round(buy_volume, 4),
            "sell_volume": round(sell_volume, 4),
            "delta": round(delta, 4),
            "delta_ratio": round(delta_ratio, 4),
            "window_cvd": round(delta, 4),
            "session_cvd": round(session_cvd, 4),
            "large_trades": [
                {
                    "ts": datetime.fromtimestamp(t["ts"] / 1000, timezone.utc).isoformat(),
                    "side": t["side"],
                    "price": t["price"],
                    "size": t["size"],
                    "notional": round(t["notional"], 2),
                }
                for t in sorted(large, key=lambda x: x["ts"], reverse=True)[:20]
            ],
            "large_buy": round(large_buy, 2),
            "large_sell": round(large_sell, 2),
            "large_threshold": round(threshold, 2),
            "book": {
                "band_pct": BOOK_BAND_PCT,
                "bid_depth": round(bid_depth, 4),
                "ask_depth": round(ask_depth, 4),
                "imbalance": round(band_imbalance, 4),
                "top20_imbalance": round(top_imbalance, 4),
                "available": book_ok,
            },
            "flow_bias": flow_bias,
            "quality": {
                "sampled": True,
                "trade_count": len(trades),
                "window_coverage_pct": coverage,
                "gap_suspected": gap_suspected,
                "stale": False,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._cache[symbol] = result
        return result

    def _stale_or_empty(self, symbol: str, window_minutes: int, reason: str) -> dict:
        with self._lock:
            previous = self._cache.get(symbol)
        if previous:
            stale = dict(previous)
            stale["quality"] = {**previous.get("quality", {}), "stale": True}
            stale["reason"] = reason
            # 回写缓存，保证后续 GET 也能看到 stale 标记
            with self._lock:
                self._cache[symbol] = stale
            return stale
        return {
            "symbol": symbol,
            "window": f"{window_minutes}m",
            "window_minutes": window_minutes,
            "available": False,
            "reason": reason,
            "quality": {"sampled": True, "stale": True},
            "updated_at": None,
        }

    # ─── 调度 ─────────────────────────────────────────────

    def refresh_all(self) -> None:
        futures = [self._executor.submit(self._refresh_one, item)
                   for item in market_service.list_watch_items()]
        for future in futures:
            try:
                future.result()
            except Exception:
                continue

    def persist_snapshots(self) -> int:
        """按配置间隔把当前缓存写入 order_flow_snapshots（默认 5 分钟一条）。"""
        written = 0
        with self._lock:
            symbols = list(self._cache.keys())
        for symbol in symbols:
            data = self.get(symbol)
            if not data.get("available"):
                continue
            self._db.save_order_flow_snapshot(
                symbol, data.get("window_minutes") or settings.orderflow_window_minutes,
                data, payload={"large_trades": data.get("large_trades", [])[:20],
                               "book": data.get("book")},
            )
            written += 1
        return written

    # ─── 读取 ─────────────────────────────────────────────

    def get(self, symbol: str) -> dict:
        symbol = symbol.replace("-SWAP", "")
        with self._lock:
            cached = self._cache.get(symbol)
        if cached:
            return cached
        return {
            "symbol": symbol,
            "window": f"{settings.orderflow_window_minutes}m",
            "window_minutes": settings.orderflow_window_minutes,
            "available": False,
            "reason": "订单流数据尚未就绪，等待首轮采样",
            "large_trades": [],
            "quality": {"sampled": True, "stale": False},
            "updated_at": None,
        }

    def large_trades(self, symbol: str, limit: int = 20) -> dict:
        data = self.get(symbol)
        items = (data.get("large_trades") or [])[:max(1, min(int(limit or 20), 100))]
        return {"symbol": symbol.replace("-SWAP", ""), "total": len(items),
                "items": items, "available": data.get("available")}

    def history(self, symbol: Optional[str] = None,
                start: Optional[str] = None, end: Optional[str] = None,
                limit: int = 200) -> dict:
        items = self._db.query_order_flow_snapshots(
            symbol=symbol.replace("-SWAP", "") if symbol else None,
            start=start, end=end, limit=limit,
        )
        return {"total": len(items), "items": items}

    def snapshot(self) -> dict:
        return {
            "items": [self.get(item.symbol) for item in market_service.list_watch_items()],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


order_flow_service = OrderFlowService()
