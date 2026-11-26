"""历史 K 线重放回测：复用现有评分/方向函数，验证是否有正向 edge。

只读复用冻结区的 signal_engine / market_score，不修改其逻辑：
- 每个 bar 只把「截至该 bar 收盘」的最近 100 根 K 线交给 evaluate（与线上 fetch_candles 默认 100 根一致）；
- 信号在收盘价成交，按固定持仓时长在收盘价离场，并扣双边成本；
- OI 用 0（线上 OI 变化是秒级、不可历史复现），资金费率用 0（历史仅约 3 个月）。
"""

import argparse
import bisect
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import build_settings  # noqa: E402
from app.services.oke_client import OKEClient, normalize_bar  # noqa: E402
from app.services.signal_engine import signal_engine  # noqa: E402

CANDLE_WINDOW = 100  # 与线上 fetch_candles 默认条数一致
TF_MINUTES = {"15m": 15, "1H": 60, "4H": 240}
TF_DAYS = {"15m": 365, "1H": 730, "4H": 1460}
BUCKETS = [(0, 40), (40, 55), (55, 70), (70, 85), (85, 101)]


def fetch_history(client, inst_id, bar, start_ms, sleep=0.15):
    rows = {}
    cursor = int(time.time() * 1000)
    while True:
        payload = client._request(
            "/api/v5/market/history-candles",
            {"instId": inst_id, "bar": bar, "after": str(cursor), "limit": "300"},
        )
        batch = payload.get("data", [])
        if not batch:
            break
        for r in batch:
            ts = int(r[0])
            if ts >= start_ms:
                rows[ts] = r
        cursor = min(int(r[0]) for r in batch)
        if cursor <= start_ms:
            break
        time.sleep(sleep)
    candles = [
        {
            "ts": ts, "open": float(r[1]), "high": float(r[2]),
            "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]),
        }
        for ts, r in sorted(rows.items())
    ]
    return candles


def max_drawdown(trades):
    """按时间顺序、不重叠持仓复利，返回最大回撤（正数）。"""
    equity, peak, worst = 1.0, 1.0, 0.0
    last_exit = None
    for tr in sorted(trades, key=lambda t: t["entry_ts"]):
        if last_exit is not None and tr["entry_ts"] < last_exit:
            continue
        equity *= 1 + tr["net"]
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
        last_exit = tr["exit_ts"]
    return worst


def summarize(trades):
    if not trades:
        return {"n": 0}
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "n": len(trades),
        "win_rate": round(len(wins) / len(trades), 4),
        "mean_net": round(sum(t["net"] for t in trades) / len(trades), 6),
        "median_net": round(sorted(t["net"] for t in trades)[len(trades) // 2], 6),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else None,
        "avg_win": round(gross_win / len(wins), 6) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 6) if losses else None,
        "max_dd": round(max_drawdown(trades), 4),
    }


def fetch_oi_series(client, inst_id, period, start_ms, end_ms, step_ms=86400000):
    """按 begin/end 分片拉取 OI 历史（该接口单次最多 100 条）。

    分片取 1 天：15m 粒度一天 96 条，不会因单页上限 100 产生缺口。
    """
    series = {}
    cursor = end_ms
    empties = 0
    while cursor > start_ms:
        begin = max(cursor - step_ms, start_ms)
        payload = client._request(
            "/api/v5/rubik/stat/contracts/open-interest-history",
            {"instId": inst_id, "period": period,
             "begin": str(begin), "end": str(cursor), "limit": "100"},
        )
        rows = payload.get("data", [])
        empties = empties + 1 if not rows else 0
        for r in rows:
            series[int(r[0])] = float(r[1])
        cursor = begin
        if empties >= 2:
            break
        time.sleep(0.15)
    return sorted(series.items())


def oi_change_at(series, ts, lookback_ms):
    if not series:
        return 0.0
    keys = [k for k, _ in series]
    i_cur = bisect.bisect_right(keys, ts) - 1
    i_prev = bisect.bisect_right(keys, ts - lookback_ms) - 1
    if i_cur < 0 or i_prev < 0 or i_prev == i_cur:
        return 0.0
    cur, prev = series[i_cur][1], series[i_prev][1]
    if prev <= 0:
        return 0.0
    return round((cur - prev) / prev * 100, 4)


def run(symbols, timeframes, threshold, cost, out_path, use_oi=False, days=None):
    settings = build_settings()
    base_url = settings.oke_base_url
    if "example.com" in base_url:
        base_url = "https://www.okx.com"
    client = OKEClient(base_url, "")
    now_ms = int(time.time() * 1000)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "cost_round_trip": cost, "threshold": threshold, "oi_mode": use_oi,
              "results": {}}
    for tf in timeframes:
        tf_min = TF_MINUTES[tf]
        horizons = [4 * 60, 12 * 60]
        pooled = {h: [] for h in horizons}
        buckets = {h: {b: [] for b in BUCKETS} for h in horizons}
        baselines = {h: [] for h in horizons}
        per_symbol = {}
        for symbol in symbols:
            inst = f"{symbol}-SWAP"
            window_days = days or TF_DAYS[tf]
            start_ms = now_ms - window_days * 86400000
            candles = fetch_history(client, inst, normalize_bar(tf), start_ms)
            closes = [c["close"] for c in candles]
            n = len(closes)
            oi_series = []
            if use_oi:
                oi_period = "15m" if tf == "15m" else "1H"
                oi_series = fetch_oi_series(
                    client, inst, oi_period,
                    start_ms - 2 * 86400000, now_ms,
                )
            lookback_ms = 900000 if tf == "15m" else 3600000
            filled = {"bars": n, "first": candles[0]["ts"] if n else None,
                      "oi_points": len(oi_series)}
            sym_trades = {h: [] for h in horizons}
            if n < CANDLE_WINDOW + max(horizons) // tf_min + 1:
                per_symbol[symbol] = {"error": "数据不足", **filled}
                continue
            for i in range(CANDLE_WINDOW - 1, n - 1):
                window = candles[i - CANDLE_WINDOW + 1: i + 1]
                oi_pct = oi_change_at(oi_series, candles[i]["ts"], lookback_ms) if use_oi else 0
                sig = signal_engine.evaluate(
                    symbol, window, closes[i], tf,
                    {"change_pct": oi_pct}, {"rate": 0},
                )
                analysis = sig["analysis"]
                score = int(analysis.score)
                direction = analysis.direction
                for h_min in horizons:
                    bars = h_min // tf_min
                    j = i + bars
                    if j >= n:
                        continue
                    raw = closes[j] / closes[i] - 1
                    baselines[h_min].append(raw - cost)
                    if direction not in ("LONG", "SHORT"):
                        continue
                    sign = 1 if direction == "LONG" else -1
                    net = sign * raw - cost
                    item = {"entry_ts": candles[i]["ts"], "exit_ts": candles[j]["ts"],
                            "net": net, "score": score, "symbol": symbol}
                    buckets[h_min][next((b for b in BUCKETS if b[0] <= score < b[1]), BUCKETS[-1])].append(net)
                    if score >= threshold:
                        sym_trades[h_min].append(item)
            for h_min in horizons:
                pooled[h_min].extend(sym_trades[h_min])
            per_symbol[symbol] = {
                **filled,
                "signals": {str(h): summarize(sym_trades[h])["n"] for h in horizons},
                "by_horizon": {str(h): summarize(sym_trades[h]) for h in horizons},
            }
        tf_result = {
            "per_symbol": per_symbol,
            "pooled": {str(h): summarize(pooled[h]) for h in horizons},
            "baseline_always_long": {
                str(h): {
                    "n": len(baselines[h]),
                    "mean_net": round(sum(baselines[h]) / len(baselines[h]), 6) if baselines[h] else None,
                } for h in horizons
            },
            "score_buckets": {
                str(h): {
                    f"{b[0]}-{b[1] - 1}": {
                        "n": len(v),
                        "mean_net": round(sum(v) / len(v), 6) if v else None,
                        "win_rate": round(sum(1 for x in v if x > 0) / len(v), 4) if v else None,
                    } for b, v in buckets[h].items()
                } for h in horizons
            },
        }
        report["results"][tf] = tf_result
        print(f"[{tf}] done bars={n} signals={len(pooled[horizons[0]])}")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT,ZEC-USDT")
    parser.add_argument("--timeframes", default="15m,1H,4H")
    parser.add_argument("--threshold", type=int, default=70)
    parser.add_argument("--oi", action="store_true", help="使用真实 OI 历史（约 30 天可用）")
    parser.add_argument("--days", type=int, default=None, help="统一覆盖各周期的回看天数")
    parser.add_argument("--out", default=r"d:\OKEworkplace\backend\data\backtest_results.json")
    args = parser.parse_args()
    settings = build_settings()
    cost = 2 * (settings.verify_fee_rate + settings.verify_slippage_rate)
    run(args.symbols.split(","), args.timeframes.split(","), args.threshold, cost,
        args.out, use_oi=args.oi, days=args.days)
