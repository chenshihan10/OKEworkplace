"""多周期（MTF）旁路服务：15m / 1H / 4H 独立评分与共振结论。

约束：
  - 只调用未修改的 signal_engine / calculate_market_score，评分与方向均为各周期原始值；
  - 不使用 DirectionTracker（它按币种单状态，无法同时承载三个周期）；
  - 结果只做展示与预测上下文，不修改主周期 /predictions 的评分与方向。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.market_regime import classify_from_signal
from app.services.market_service import market_service
from app.services.oke_client import OKEClient, normalize_bar
from app.services.signal_engine import signal_engine

CANDLE_LIMIT = 300


def _ema_stack(ema20: Optional[float], ema60: Optional[float], ema120: Optional[float]) -> str:
    if ema20 is None or ema60 is None:
        return "unknown"
    if ema120 is None:
        return "bull" if ema20 > ema60 else ("bear" if ema20 < ema60 else "mixed")
    if ema20 > ema60 > ema120:
        return "bull"
    if ema20 < ema60 < ema120:
        return "bear"
    return "mixed"


def _resonance(primary_tf: str, rows: List[dict]) -> dict:
    """共振结论：纯展示规则，不参与评分。"""
    directions = {row["timeframe"]: row["direction"] for row in rows}
    primary = directions.get(primary_tf, "NEUTRAL")
    higher = [row["direction"] for row in rows if row["timeframe"] != primary_tf]
    non_neutral = [d for d in directions.values() if d in ("LONG", "SHORT")]

    counter_trend = bool(
        primary in ("LONG", "SHORT")
        and any(d in ("LONG", "SHORT") and d != primary for d in higher)
    )
    alignment = sum(1 for d in directions.values() if d == primary and primary in ("LONG", "SHORT"))
    ratio = round(alignment / len(rows), 2) if rows else 0.0

    if primary in ("LONG", "SHORT") and len(non_neutral) == len(rows) and all(d == primary for d in non_neutral):
        label = f"STRONG_{primary}"
    elif counter_trend:
        label = "MIXED"
    elif primary in ("LONG", "SHORT") and alignment >= 2:
        label = primary
    elif not non_neutral:
        label = "NEUTRAL"
    else:
        label = "MIXED"

    reasons = []
    if counter_trend:
        opposite = [row["timeframe"] for row in rows
                    if row["timeframe"] != primary_tf
                    and row["direction"] in ("LONG", "SHORT")
                    and row["direction"] != primary]
        reasons.append(
            f"{primary_tf} {primary} 与 {'、'.join(opposite)} 方向相反，存在逆大周期风险"
        )
    elif label.startswith("STRONG_"):
        reasons.append(f"{'、'.join(directions)} 三周期同向 {primary}")
    elif label in ("LONG", "SHORT"):
        reasons.append(f"{primary_tf} 与 {alignment} 个周期同向 {primary}")
    elif label == "NEUTRAL":
        reasons.append("三个周期均无明确方向")
    else:
        reasons.append("周期方向不一致，暂不构成共振")

    return {
        "resonance": label,
        "alignment": alignment,
        "alignment_ratio": ratio,
        "counter_trend": counter_trend,
        "reasons": reasons,
    }


class MultiTimeframeService:
    def __init__(self) -> None:
        self._client = OKEClient(
            settings.oke_base_url, settings.oke_api_key, settings.oke_secret_key
        )
        self._cache: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mtf")

    # ─── 计算 ─────────────────────────────────────────────

    def _shared_context(self, symbol: str) -> dict:
        """OI / 资金费率 / 成交 / 盘口是币种级数据，三个周期共用（响应里标注 shared_inputs）。"""
        signal = market_service._latest_signals_cache.get(symbol) or {}
        price = (market_service._latest_prices.get(symbol) or {}).get("price")
        funding = (signal.get("funding_rate_dict") or {}).get("funding_rate") or 0
        return {
            "price": price,
            "open_interest": {"change_pct": signal.get("oi_change_pct", 0) or 0},
            "funding_rate": {"rate": funding},
            "trades": signal.get("trades") or [],
            "books": signal.get("books") or {},
        }

    def _compute_timeframe(self, symbol: str, timeframe: str) -> dict:
        ctx = self._shared_context(symbol)
        candles = self._client.fetch_candles(symbol, timeframe, limit=CANDLE_LIMIT)
        last_close = float(candles[-1]["close"]) if candles else 0.0
        price = ctx["price"] or last_close
        signal = signal_engine.evaluate(
            symbol, candles, price, timeframe,
            ctx["open_interest"], ctx["funding_rate"], ctx["trades"], ctx["books"],
        )
        analysis = signal["analysis"]
        regime = classify_from_signal(signal, price)
        atr = signal.get("atr14")
        return {
            "timeframe": timeframe,
            "bar": normalize_bar(timeframe),
            "direction": analysis.direction,
            "score": analysis.score,
            "level": analysis.level,
            "regime": regime.get("regime"),
            "regime_label": regime.get("label"),
            "ema_stack": _ema_stack(signal.get("ema20"), signal.get("ema60"), signal.get("ema120")),
            "rsi14": round(signal["rsi14"], 2) if signal.get("rsi14") is not None else None,
            "macd_histogram": (
                round(analysis.indicators.get("macd", {}).get("histogram") or 0, 4)
                if analysis.indicators else None
            ),
            "atr_pct": round(atr / price * 100, 3) if atr and price else None,
            "stale": False,
        }

    def _stale_row(self, timeframe: str, reason: str) -> dict:
        return {
            "timeframe": timeframe,
            "bar": normalize_bar(timeframe),
            "direction": "NEUTRAL",
            "score": None,
            "level": "数据不足",
            "regime": "UNKNOWN",
            "regime_label": "数据不足",
            "ema_stack": "unknown",
            "rsi14": None,
            "macd_histogram": None,
            "atr_pct": None,
            "stale": True,
            "reason": reason,
        }

    def _refresh_one(self, item) -> dict:
        rows: List[dict] = []
        errors: List[str] = []
        for timeframe in settings.mtf_timeframes:
            try:
                rows.append(self._compute_timeframe(item.symbol, timeframe))
            except Exception as exc:
                errors.append(f"{timeframe}: {exc}")
                rows.append(self._stale_row(timeframe, str(exc)))

        primary = next(
            (tf for tf in settings.mtf_timeframes
             if normalize_bar(tf) == normalize_bar(item.timeframe)),
            settings.mtf_timeframes[0],
        )
        valid = [row for row in rows if not row["stale"]]
        summary = _resonance(primary, rows)
        weights = [row["score"] for row in valid if row["score"] is not None]

        result = {
            "symbol": item.symbol,
            "primary_timeframe": primary,
            "timeframes": rows,
            "resonance": summary["resonance"],
            "alignment": summary["alignment"],
            "alignment_ratio": summary["alignment_ratio"],
            "counter_trend": summary["counter_trend"],
            "weighted_score": round(sum(weights) / len(weights), 1) if weights else None,
            "shared_inputs": True,
            "reasons": summary["reasons"] + (["部分周期取数失败，已标记 stale"] if errors else []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pending": False,
            "stale": not valid,
        }
        with self._lock:
            self._cache[item.symbol] = result
        return result

    # ─── 调度与读取 ───────────────────────────────────────

    def refresh_all(self) -> None:
        futures = [self._executor.submit(self._refresh_one, item)
                   for item in market_service.list_watch_items()]
        for future in futures:
            try:
                future.result()
            except Exception:
                # 单个币种失败不影响其它币种；下一轮继续重试
                continue

    def get(self, symbol: str) -> dict:
        symbol = symbol.replace("-SWAP", "")
        with self._lock:
            cached = self._cache.get(symbol)
        if cached:
            return cached
        primary = settings.mtf_timeframes[0]
        return {
            "symbol": symbol,
            "primary_timeframe": primary,
            "timeframes": [],
            "resonance": "NEUTRAL",
            "alignment": 0,
            "alignment_ratio": 0.0,
            "counter_trend": False,
            "weighted_score": None,
            "shared_inputs": True,
            "reasons": ["多周期数据尚未就绪，等待首轮刷新（约 60 秒）"],
            "updated_at": None,
            "pending": True,
            "stale": False,
        }

    def snapshot(self) -> dict:
        items = []
        for item in market_service.list_watch_items():
            items.append(self.get(item.symbol))
        return {
            "items": items,
            "timeframes": settings.mtf_timeframes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


multi_timeframe_service = MultiTimeframeService()
