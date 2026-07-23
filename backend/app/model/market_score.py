"""
市场评分算法模块
基于趋势、资金、订单流、风险四个维度对市场进行评分（0-100）
"""
from typing import Dict, List, Tuple
from dataclasses import dataclass, field


@dataclass
class PriceAction:
    """价格行动"""
    current_price: float
    previous_price: float = None
    change_pct: float = 0.0
    
    def __post_init__(self):
        if self.previous_price:
            self.change_pct = (self.current_price - self.previous_price) / self.previous_price * 100


@dataclass
class MarketAnalysis:
    """市场分析结果"""
    symbol: str
    price: float
    market_score: int  # 0-100
    market_state: str  # 强势、震荡、弱势
    confidence: int  # 可信度 0-100
    
    # 评分组成
    trend_score: int = 0  # 趋势评分
    capital_score: int = 0  # 资金评分
    orderflow_score: int = 0  # 订单流评分
    risk_score: int = 0  # 风险评分
    
    # 详细信息
    oi_change: str = ""
    funding_rate: str = ""
    cvd: float = 0.0
    capital_behavior: Dict = field(default_factory=dict)
    
    # 建议
    recommendation: Dict = field(default_factory=lambda: {"signal": "WAIT", "reason": []})
    
    # 数据源
    data_source: str = "OKX_REAL"


class TrendAnalyzer:
    """趋势分析器"""
    
    @staticmethod
    def analyze(
        candles: List[Dict],
        macd: Dict = None,
        ema_data: Dict = None
    ) -> int:
        """
        分析趋势评分
        
        Args:
            candles: K线数据 [{"close": 1000, "high": 1100, ...}]
            macd: MACD 数据 {"diff": 0.5, "dea": 0.3}
            ema_data: EMA 数据 {"ema20": 1000, "ema60": 980, "ema120": 950}
        
        Returns:
            趋势评分 0-25
        """
        score = 0
        
        if not candles or len(candles) < 2:
            return 0
        
        # K线趋势分析（0-10）
        recent_candles = candles[-5:]  # 最近5条
        bullish_count = sum(1 for c in recent_candles if c.get("close", 0) > c.get("open", 0))
        score += (bullish_count / len(recent_candles)) * 10
        
        # MACD分析（0-8）
        if macd:
            diff = macd.get("diff", 0)
            dea = macd.get("dea", 0)
            
            if diff > dea > 0:  # 强势上升
                score += 8
            elif diff > dea:  # 温和上升
                score += 5
            elif diff < dea < 0:  # 强势下降
                score += 0
            elif diff < dea:  # 温和下降
                score += 2
        
        # EMA分析（0-7）
        if ema_data:
            close = candles[-1].get("close", 0)
            ema20 = ema_data.get("ema20", 0)
            ema60 = ema_data.get("ema60", 0)
            ema120 = ema_data.get("ema120", 0)
            
            if close > ema20 > ema60 > ema120:  # 多头排列
                score += 7
            elif close > ema20 > ema60:  # 部分多头
                score += 5
            elif close > ema20:  # 略微多头
                score += 3
        
        return min(int(score), 25)


class CapitalAnalyzer:
    """资金分析器"""
    
    @staticmethod
    def analyze(
        oi_change_pct: float,
        funding_rate: float,
        price_change_pct: float
    ) -> int:
        """
        分析资金评分
        
        Args:
            oi_change_pct: OI变化百分比
            funding_rate: 资金费率
            price_change_pct: 价格变化百分比
        
        Returns:
            资金评分 0-25
        """
        score = 0
        
        # 价格上涨 + OI上升 = 新增资金进入
        if price_change_pct > 0 and oi_change_pct > 0:
            score += 20
        elif price_change_pct > 0 and oi_change_pct == 0:
            # 价格上升但OI不变 = 空头回补
            score += 15
        elif price_change_pct > 0 and oi_change_pct < 0:
            # 价格上升但OI下降 = 资金不足，风险
            score += 10
        
        # 价格下跌 + OI下降 = 资金撤离
        if price_change_pct < 0 and oi_change_pct < 0:
            score += 0
        
        # 资金费率分析
        if funding_rate > 0.01:  # 超过0.01 = 多头拥挤
            score -= 3
        elif funding_rate < -0.01:  # 负数 = 空头拥挤
            score += 2
        
        return max(0, min(int(score), 25))


class OrderFlowAnalyzer:
    """订单流分析器"""
    
    @staticmethod
    def analyze(
        cvd: float,
        buy_volume: float,
        sell_volume: float,
        cvd_trend: str = "neutral"
    ) -> int:
        """
        分析订单流评分
        
        Args:
            cvd: CVD值（累积成交量差）
            buy_volume: 主动买成交量
            sell_volume: 主动卖成交量
            cvd_trend: CVD趋势 "up", "down", "neutral"
        
        Returns:
            订单流评分 0-25
        """
        score = 0
        
        # CVD分析
        if cvd > 0:
            score += 10
        elif cvd < 0:
            score += 0
        else:
            score += 5
        
        # 主动买卖比
        total_volume = buy_volume + sell_volume
        if total_volume > 0:
            buy_ratio = buy_volume / total_volume
            if buy_ratio > 0.6:  # 买方占优
                score += 10
            elif buy_ratio > 0.55:  # 略微买方
                score += 7
            elif buy_ratio < 0.4:  # 卖方占优
                score += 0
            else:  # 均衡
                score += 5
        
        # CVD趋势
        if cvd_trend == "up":
            score += 5
        elif cvd_trend == "down":
            score += 0
        
        return min(int(score), 25)


class RiskAnalyzer:
    """风险分析器"""
    
    @staticmethod
    def analyze(
        funding_rate: float,
        volatility: float,
        breakout_failures: int = 0,
        price_distance_to_resistance: float = 0
    ) -> int:
        """
        分析风险评分
        
        Args:
            funding_rate: 资金费率
            volatility: 波动率
            breakout_failures: 突破失败次数
            price_distance_to_resistance: 价格距离阻力位的距离（百分比）
        
        Returns:
            风险评分 0-25（负数表示高风险）
        """
        score = 0
        
        # 资金费率风险
        if funding_rate > 0.05:  # 过高 = 多头拥挤
            score -= 10
        elif funding_rate > 0.02:
            score -= 5
        
        # 波动率风险
        if volatility > 3:  # 波动率很大
            score -= 5
        elif volatility > 2:
            score -= 2
        
        # 突破失败风险
        score -= breakout_failures * 2
        
        # 接近阻力位风险
        if price_distance_to_resistance < 1:  # 距离很近
            score -= 5
        elif price_distance_to_resistance < 3:
            score -= 2
        
        return max(-25, min(int(score), 0))


class MarketScorer:
    """市场评分器 - 综合所有分析"""
    
    @staticmethod
    def score(
        candles: List[Dict],
        macd: Dict,
        ema_data: Dict,
        oi_change_pct: float,
        funding_rate: float,
        price_action: PriceAction,
        cvd: float,
        buy_volume: float,
        sell_volume: float,
        volatility: float = 1.5,
        data_source: str = "OKX_REAL"
    ) -> MarketAnalysis:
        """
        综合评分
        
        Returns:
            完整的市场分析结果
        """
        # 获取各维度评分
        trend_score = TrendAnalyzer.analyze(candles, macd, ema_data)
        capital_score = CapitalAnalyzer.analyze(
            oi_change_pct, 
            funding_rate, 
            price_action.change_pct
        )
        orderflow_score = OrderFlowAnalyzer.analyze(cvd, buy_volume, sell_volume)
        risk_score = RiskAnalyzer.analyze(
            funding_rate, 
            volatility, 
            breakout_failures=0
        )
        
        # 综合评分
        total_score = trend_score + capital_score + orderflow_score + risk_score
        market_score = max(0, min(100, int(total_score)))
        
        # 确定市场状态
        if market_score >= 70:
            market_state = "强势"
        elif market_score >= 50:
            market_state = "震荡偏多"
        elif market_score >= 30:
            market_state = "震荡"
        else:
            market_state = "弱势"
        
        # 确定可信度
        confidence = min(100, trend_score * 2 + abs(risk_score))
        
        return MarketAnalysis(
            symbol="",  # 由调用者设置
            price=price_action.current_price,
            market_score=market_score,
            market_state=market_state,
            confidence=confidence,
            trend_score=trend_score,
            capital_score=capital_score,
            orderflow_score=orderflow_score,
            risk_score=risk_score,
            oi_change=f"{oi_change_pct:+.1f}%",
            funding_rate=f"{funding_rate:.4%}",
            cvd=cvd,
            data_source=data_source
        )


def calculate_market_score(analysis_inputs: Dict) -> MarketAnalysis:
    """
    便捷函数 - 直接从输入计算市场评分
    
    Args:
        analysis_inputs: 包含所有必需字段的字典
    
    Returns:
        MarketAnalysis 对象
    """
    price_action = PriceAction(
        current_price=analysis_inputs.get("price", 0),
        previous_price=analysis_inputs.get("previous_price")
    )
    
    result = MarketScorer.score(
        candles=analysis_inputs.get("candles", []),
        macd=analysis_inputs.get("macd", {}),
        ema_data=analysis_inputs.get("ema_data", {}),
        oi_change_pct=analysis_inputs.get("oi_change_pct", 0),
        funding_rate=analysis_inputs.get("funding_rate", 0),
        price_action=price_action,
        cvd=analysis_inputs.get("cvd", 0),
        buy_volume=analysis_inputs.get("buy_volume", 0),
        sell_volume=analysis_inputs.get("sell_volume", 0),
        volatility=analysis_inputs.get("volatility", 1.5),
        data_source=analysis_inputs.get("data_source", "OKX_REAL")
    )
    
    result.symbol = analysis_inputs.get("symbol", "")
    return result
