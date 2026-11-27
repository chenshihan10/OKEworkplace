"""绩效质量视图：毛/净分离、分视界、置信区间、成本门槛、品种分类、影子评分与运行监控。

只读统计，不参与任何评分/判断。供前端「研究」页使用（/api/v3/performance/quality）。
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.db_store import SignalDB

BOOTSTRAP_ROUNDS = 300
BOOTSTRAP_SEED = 20261127
PERCENTILES = (2.5, 97.5)


def _pct(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None else round(value * 100, digits)


def _percentile(sorted_values: List[float], p: float) -> Optional[float]:
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _metrics(rows: List[dict]) -> Dict:
    verified = [r for r in rows if r.get("outcome") in ("WIN", "LOSS", "FLAT")]
    wins = sum(1 for r in verified if r["outcome"] == "WIN")
    losses = sum(1 for r in verified if r["outcome"] == "LOSS")
    flats = sum(1 for r in verified if r["outcome"] == "FLAT")
    nets = [float(r["net_return"]) for r in verified if r.get("net_return") is not None]
    grosses = [float(r["gross_return"]) for r in verified if r.get("gross_return") is not None]
    return {
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": (wins / len(verified) * 100) if verified else None,
        "directional_accuracy": (wins / (wins + losses) * 100) if (wins + losses) else None,
        "avg_net_pct": (sum(nets) / len(nets) * 100) if nets else None,
        "median_gross_pct": (sorted(grosses)[len(grosses) // 2] * 100) if grosses else None,
    }


def _bootstrap(rows: List[dict]) -> Dict:
    """对结果行做有放回重采样，给胜率/方向准确率/平均净收益的 95% 区间。"""
    if len(rows) < 10:
        return {"method": "sample_too_small", "n": len(rows)}
    rng = random.Random(BOOTSTRAP_SEED)
    samples = {"win_rate": [], "directional_accuracy": [], "avg_net_pct": []}
    n = len(rows)
    for _ in range(BOOTSTRAP_ROUNDS):
        picked = [rows[rng.randrange(n)] for _ in range(n)]
        m = _metrics(picked)
        for key in samples:
            if m.get(key) is not None:
                samples[key].append(m[key])
    out = {"method": "percentile", "rounds": BOOTSTRAP_ROUNDS, "n": n, "ci": {}}
    for key, values in samples.items():
        values.sort()
        out["ci"][key] = [
            None if not values else round(_percentile(values, PERCENTILES[0]), 2),
            None if not values else round(_percentile(values, PERCENTILES[1]), 2),
        ]
    return out


def _symbol_class(symbol: str) -> str:
    base = (symbol or "").split("-")[0].upper()
    return "tokenized_stock" if base in {s.upper() for s in settings.tokenized_stock_symbols} else "crypto"


class PerformanceQuality:
    def __init__(self) -> None:
        self._db = SignalDB()

    def overview(self) -> Dict:
        cost_pct = 2 * (settings.verify_fee_rate + settings.verify_slippage_rate) * 100
        with self._db._connect() as conn:  # noqa: SLF001  只读查询
            conn.row_factory = None
            rows = [dict(zip(
                ("prediction_id", "symbol", "direction", "horizon", "verify_status",
                 "outcome", "gross_return", "net_return"), r))
                for r in conn.execute(
                    "SELECT p.id, p.symbol, p.direction, r.horizon, r.verify_status, "
                    "r.outcome, r.gross_return, r.net_return "
                    "FROM predictions p JOIN prediction_results r ON r.prediction_id = p.id"
                )]

        def build(group_rows: List[dict]) -> Dict:
            preds = len({r["prediction_id"] for r in group_rows})
            base = {
                "predictions": preds,
                "results": len(group_rows),
                "verified": sum(1 for r in group_rows if r["outcome"] in ("WIN", "LOSS", "FLAT")),
            }
            base.update(_metrics(group_rows))
            base["ci"] = _bootstrap(group_rows)
            verified = [r for r in group_rows if r["outcome"] in ("WIN", "LOSS", "FLAT")]
            cover = [r for r in verified if (r.get("gross_return") or 0) * 100 > cost_pct]
            base["cost_pct"] = round(cost_pct, 3)
            base["gross_cover_rate_pct"] = round(len(cover) / len(verified) * 100, 2) if verified else None
            base["cost_verdict"] = (
                "毛收益不足以覆盖成本" if base["median_gross_pct"] is not None
                and base["median_gross_pct"] <= cost_pct else "毛收益高于成本门槛"
            )
            return base

        horizons = sorted({r["horizon"] for r in rows if r["horizon"]})
        by_horizon = []
        for h in horizons:
            item = build([r for r in rows if r["horizon"] == h])
            item["horizon"] = h
            by_horizon.append(item)

        symbols = sorted({r["symbol"] for r in rows})
        by_symbol = []
        for s in symbols:
            item = build([r for r in rows if r["symbol"] == s])
            item["symbol"] = s
            item["class"] = _symbol_class(s)
            by_symbol.append(item)

        classes = {}
        for cls in ("crypto", "tokenized_stock"):
            group = [r for r in rows if _symbol_class(r["symbol"]) == cls]
            classes[cls] = build(group)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall": build(rows),
            "by_horizon": by_horizon,
            "by_symbol": by_symbol,
            "by_class": classes,
            "shadow": self._shadow_stats(),
            "monitor": self._monitor_stats(),
            "definition": {
                "win_rate": "WIN / 已回验（含 FLAT 分母）",
                "directional_accuracy": "WIN / (WIN+LOSS)",
                "avg_net_pct": "已验证结果的平均净收益（含 FLAT），已扣双边手续费与滑点",
                "median_gross_pct": "已验证结果毛收益中位数，未扣成本",
                "gross_cover_rate_pct": "毛收益 > 单次成本的占比，衡量成本门槛",
                "ci": "对结果行做 300 次有放回重采样的 2.5%~97.5% 分位区间",
                "class": "代币化股票按 OKE_TOKENIZED_STOCK_SYMBOLS 划分",
            },
        }

    def _shadow_stats(self) -> Dict:
        with self._db._connect() as conn:  # noqa: SLF001
            conn.row_factory = None
            raw = list(conn.execute(
                "SELECT symbol, official_score, shadow_score, official_oi, shadow_oi, "
                "oi_change_pct, created_at FROM shadow_scores"
            ))
        if not raw:
            return {"rows": 0}
        cols = ("symbol", "official_score", "shadow_score", "official_oi", "shadow_oi",
                "oi_change_pct", "created_at")
        data = [dict(zip(cols, r)) for r in raw]
        gaps = [(d["shadow_score"] or 0) - (d["official_score"] or 0) for d in data]
        oi_gaps = [(d["shadow_oi"] or 0) - (d["official_oi"] or 0) for d in data]
        mean_gap = sum(gaps) / len(gaps)
        mean_oi_gap = sum(oi_gaps) / len(oi_gaps)
        zero_change = sum(1 for d in data if not d["oi_change_pct"])
        by_symbol = {}
        for d in data:
            by_symbol.setdefault(d["symbol"], []).append(
                (d["shadow_score"] or 0) - (d["official_score"] or 0))
        return {
            "rows": len(data),
            "avg_official_score": round(sum(d["official_score"] or 0 for d in data) / len(data), 2),
            "avg_shadow_score": round(sum(d["shadow_score"] or 0 for d in data) / len(data), 2),
            "avg_gap": round(mean_gap, 2),
            "avg_oi_gap": round(mean_oi_gap, 2),
            "gap_std": round((sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)) ** 0.5, 2),
            "gap_range": [min(gaps), max(gaps)],
            "zero_oi_change_share_pct": round(zero_change / len(data) * 100, 2),
            "by_symbol": {
                s: round(sum(v) / len(v), 2) for s, v in sorted(by_symbol.items())
            },
            "note": "修复后 OI 变化不可用时影子与正式持平；仅在 OI 有变化时产生方向性差异",
        }

    def _monitor_stats(self) -> Dict:
        now = datetime.now(timezone.utc)
        bucket = (now - timedelta(minutes=now.minute % 15,
                                  seconds=now.second, microseconds=now.microsecond))
        bucket_str = bucket.strftime("%Y-%m-%dT%H:%M")
        with self._db._connect() as conn:  # noqa: SLF001
            conn.row_factory = None
            recent = list(conn.execute(
                "SELECT symbol, created_at FROM predictions "
                "WHERE substr(created_at,1,10) >= date('now','-1 day')"
            ))
            dup_buckets = list(conn.execute(
                "SELECT symbol, substr(created_at,1,13) || ':' || "
                "printf('%02d', (CAST(substr(created_at,15,2) AS INT)/15)*15) AS bucket, "
                "COUNT(*) AS c FROM predictions "
                "WHERE substr(created_at,1,10) >= date('now','-1 day') "
                "GROUP BY symbol, bucket HAVING c > 1 ORDER BY c DESC LIMIT 10"
            ))
            over_results = list(conn.execute(
                "SELECT COUNT(*) FROM (SELECT prediction_id FROM prediction_results "
                "GROUP BY prediction_id HAVING COUNT(*) > 3)"
            ))
            null_tf = list(conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE timeframe IS NULL OR timeframe = ''"
            ))
        per_candle = {}
        for symbol, created_at in recent:
            if created_at.startswith(bucket_str):
                per_candle[symbol] = per_candle.get(symbol, 0) + 1
        return {
            "current_candle": bucket_str + "Z",
            "current_candle_writes": per_candle,
            "duplicate_buckets_24h": [
                {"symbol": s, "bucket": b, "count": c} for s, b, c in dup_buckets
            ],
            "results_over_3_per_prediction": over_results[0][0] if over_results else 0,
            "predictions_without_timeframe": null_tf[0][0] if null_tf else 0,
            "direction_flips": _direction_snapshot(),
        }


def _direction_snapshot() -> list:
    try:
        from app.services.health_monitor import direction_monitor
        return direction_monitor.snapshot()
    except Exception:  # noqa: BLE001
        return []


performance_quality = PerformanceQuality()


def performance_quality_overview() -> Dict:
    return performance_quality.overview()
