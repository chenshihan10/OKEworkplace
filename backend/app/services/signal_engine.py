"""v2.1 信号引擎 — 统一聚合入口

职责：
  1. 从原始数据计算所有技术指标（EMA / RSI / ATR / MACD / 交叉检测）
  2. 打包为 inputs dict
  3. 调用 market_score.calculate_market_score() 进行评分
  4. 返回 AnalysisResult + 附加数据（candles / CVD 等市场服务需要的字段）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services import indicator_service as ind
from app.model.market_score import calculate_market_score, AnalysisResult


class SignalEngine:
    """v2.1 信号引擎"""

    # 需要缓存的 K 线数量（足够计算 60 周期 EMA + 26 周期 MACD 慢线）
    MIN_CANDLES_FOR_INDICATORS = 100

    def evaluate(
        self,
        symbol: str,
        candles: List[Dict],
        latest_price: float,
        timeframe: str,
        open_interest: Optional[Dict] = None,
        funding_rate: Optional[Dict] = None,
        trades: Optional[List[Dict]] = None,
        books: Optional[Dict] = None,
        prev_signal: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        评估单个币种，返回完整分析结果。

        Returns:
            dict 包含：
              - analysis: AnalysisResult (dataclass)
              - candles: 原始K线（传递回 market_service）
              - cvd: CVD 值
              - trades / books: 原始数据
              - ema20 / ema60 ...: 计算出的指标（向后兼容）
        """
        closes = [float(c.get("close", 0) or 0) for c in candles if c.get("close")]

        if len(closes) < self.MIN_CANDLES_FOR_INDICATORS:
            # 数据不足，返回兜底
            return self._fallback(symbol, latest_price, timeframe, candles)

        # ═══ 计算指标 ═══
        ema20_val = ind.ema(closes, 20)
        ema60_val = ind.ema(closes, 60)
        rsi_val = ind.rsi(closes, 14)
        atr_val = ind.atr(candles, 14)

        macd_data = ind.macd(closes)
        macd_diff = macd_data.get("diff")
        macd_dea = macd_data.get("dea")
        macd_histogram = macd_data.get("histogram")

        # 交叉检测
        ema20_series = ind.ema_series(closes, 20)
        ema60_series = ind.ema_series(closes, 60)
        ema_cross = ind.detect_ema_cross(ema20_series, ema60_series, lookback=6)

        macd_series_data = ind.macd_series(closes)
        macd_cross = ind.detect_macd_cross(
            macd_series_data.get("diff_series", []),
            macd_series_data.get("dea_series", []),
            lookback=6,
        )

        # 前一根 MACD 柱线（用于判断柱线扩大/缩小）
        hist_series = macd_series_data.get("histogram_series", [])
        prev_hist = hist_series[-2] if len(hist_series) >= 2 else None

        # OI 变化
        oi_change_pct = (open_interest or {}).get("change_pct", 0) or 0
        fr_val = (funding_rate or {}).get("rate", 0) or 0

        # 成交量
        current_vol = float(candles[-1].get("volume", 0) or 0) if candles else 0
        avg_vol = ind.average_volume(candles, 20) or current_vol

        # 关键价位（基于书籍数据或 K 线高低点）
        key_levels = self._extract_key_levels(candles, books)

        # ═══ 组装输入 ═══
        inputs = {
            "symbol": symbol,
            "price": latest_price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candles": candles,
            "data_source": "okx",
            # 指标
            "ema20": ema20_val,
            "ema60": ema60_val,
            "rsi14": rsi_val,
            "atr14": atr_val,
            "macd_diff": macd_diff,
            "macd_dea": macd_dea,
            "macd_histogram": macd_histogram,
            "prev_macd_histogram": prev_hist,
            "oi_change_pct": oi_change_pct,
            "funding_rate": fr_val,
            "current_vol": current_vol,
            "avg_vol": avg_vol,
            "key_levels": key_levels,
            # 交叉检测
            "ema_cross": ema_cross,
            "macd_cross": macd_cross,
        }

        # ═══ 评分 ═══
        analysis = calculate_market_score(inputs)

        # ═══ 返回（含市场服务需要的附加字段） ═══
        return {
            "analysis": analysis,
            "candles": candles,
            "trades": trades or [],
            "books": books or {},
            # 向后兼容字段
            "ema20": ema20_val,
            "ema60": ema60_val,
            "ema120": ind.ema(closes, 120),
            "rsi14": rsi_val,
            "atr14": atr_val,
            "oi_change_pct": oi_change_pct,
            "funding_rate": fr_val,
            "timeframe": timeframe,
            "timestamp": inputs["timestamp"],
        }

    def _fallback(
        self, symbol: str, latest_price: float, timeframe: str, candles: List[Dict]
    ) -> Dict[str, Any]:
        """数据不足时的兜底输出"""
        return {
            "analysis": AnalysisResult(
                symbol=symbol,
                price=latest_price,
                timestamp=datetime.now(timezone.utc).isoformat(),
                direction="NEUTRAL",
            ),
            "candles": candles,
            "trades": [],
            "books": {},
            "ema20": None,
            "ema60": None,
            "ema120": None,
            "rsi14": None,
            "atr14": None,
            "oi_change_pct": 0,
            "funding_rate": 0,
            "timeframe": timeframe,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _extract_key_levels(
        candles: List[Dict], books: Optional[Dict]
    ) -> List[float]:
        """从订单簿或 K 线中提取关键价位"""
        levels = []

        # 从订单簿提取
        if books:
            try:
                asks = books.get("asks", []) or []
                bids = books.get("bids", []) or []

                # 聚合大单挂单位置
                from collections import defaultdict
                level_map = defaultdict(float)

                for ask in asks[:20]:
                    price = float(ask[0])
                    size = float(ask[1])
                    rounded = round(price, -1)  # 按 10 档聚合
                    level_map[rounded] += size

                for bid in bids[:20]:
                    price = float(bid[0])
                    size = float(bid[1])
                    rounded = round(price, -1)
                    level_map[rounded] += size

                # 取 TOP 大单
                sorted_levels = sorted(level_map.items(), key=lambda x: x[1], reverse=True)
                levels = [l[0] for l in sorted_levels[:5] if l[1] > 1000]
            except Exception:
                pass

        # 从 K 线补：取最近 100 根的高低点
        if not levels and candles:
            recent = candles[-100:]
            highs = [float(c.get("high", 0) or 0) for c in recent if c.get("high")]
            lows = [float(c.get("low", 0) or 0) for c in recent if c.get("low")]
            if highs:
                levels.append(max(highs))
            if lows:
                levels.append(min(lows))

        return sorted(set(levels))


signal_engine = SignalEngine()
