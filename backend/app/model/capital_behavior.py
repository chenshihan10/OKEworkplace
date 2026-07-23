"""
资金行为分析模块
根据价格、OI、CVD 的组合判断资金行为类型
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List


class CapitalBehaviorType(Enum):
    """资金行为类型"""
    
    # 多头行为
    NEW_CAPITAL_BULLISH = "新增资金推动"  # 价格↑ OI↑ CVD↑
    SHORT_COVER_RALLY = "空头回补上涨"  # 价格↑ OI↓
    BULLISH_INSUFFICIENT = "上涨但资金不足"  # 价格↑ CVD↓
    SELLING_PRESSURE_ABSORBED = "卖压吸收"  # 价格→ 卖出增加 价格不跌
    
    # 空头行为
    NEW_CAPITAL_BEARISH = "新增资金推空"  # 价格↓ OI↑ CVD↓
    LONGS_TAKING_PROFIT = "多头获利平仓"  # 价格↓ OI↓
    BEARISH_INSUFFICIENT = "下跌但资金不足"  # 价格↓ CVD↑
    BUYING_PRESSURE_OVERWHELMED = "买压被淹没"  # 价格→ 买出增加 价格不涨
    
    # 中性行为
    ACCUMULATION = "积累阶段"  # 价格→ OI不变 CVD→
    DISTRIBUTION = "分布阶段"  # 价格→ OI↑ CVD→
    CONSOLIDATION = "盘整"  # 价格→ OI↓ CVD→


@dataclass
class CapitalBehavior:
    """资金行为结果"""
    behavior_type: str  # 行为类型名称
    description: str  # 中文描述
    confidence: int  # 可信度 0-100
    signals: List[str]  # 构成此行为的信号
    implications: str  # 隐含的市场含义
    suggestion: str  # 对交易的建议


class CapitalBehaviorAnalyzer:
    """资金行为分析器"""
    
    @staticmethod
    def _get_price_direction(price_change_pct: float, threshold: float = 0.5) -> str:
        """获取价格方向"""
        if price_change_pct > threshold:
            return "up"
        elif price_change_pct < -threshold:
            return "down"
        else:
            return "neutral"
    
    @staticmethod
    def _get_oi_direction(oi_change_pct: float, threshold: float = 0.5) -> str:
        """获取OI方向"""
        if oi_change_pct > threshold:
            return "up"
        elif oi_change_pct < -threshold:
            return "down"
        else:
            return "neutral"
    
    @staticmethod
    def _get_cvd_direction(cvd_change: float, threshold: float = 0.0) -> str:
        """获取CVD方向"""
        if cvd_change > threshold:
            return "up"
        elif cvd_change < -threshold:
            return "down"
        else:
            return "neutral"
    
    @staticmethod
    def analyze(
        price_change_pct: float,
        oi_change_pct: float,
        cvd_change: float,
        current_cvd: float,
        buy_volume: float,
        sell_volume: float,
        funding_rate: float
    ) -> CapitalBehavior:
        """
        分析资金行为
        
        Args:
            price_change_pct: 价格变化百分比
            oi_change_pct: OI变化百分比
            cvd_change: CVD变化
            current_cvd: 当前CVD值
            buy_volume: 主动买成交量
            sell_volume: 主动卖成交量
            funding_rate: 资金费率
        
        Returns:
            CapitalBehavior 对象
        """
        price_dir = CapitalBehaviorAnalyzer._get_price_direction(price_change_pct)
        oi_dir = CapitalBehaviorAnalyzer._get_oi_direction(oi_change_pct)
        cvd_dir = CapitalBehaviorAnalyzer._get_cvd_direction(cvd_change)
        
        signals = []
        confidence = 50
        
        # 多头行为
        if price_dir == "up" and oi_dir == "up" and cvd_dir == "up":
            behavior = CapitalBehaviorType.NEW_CAPITAL_BULLISH
            signals = ["价格上涨", "持仓增加", "主动买增加"]
            confidence = 85
            implications = "主动资金进入市场，新增多头头寸"
            suggestion = "可考虑跟随多头，但需留意高风险"
        
        elif price_dir == "up" and oi_dir == "down":
            behavior = CapitalBehaviorType.SHORT_COVER_RALLY
            signals = ["价格上涨", "持仓减少"]
            confidence = 75
            implications = "空头平仓驱动上涨，非新增资金推动"
            suggestion = "上涨强度可能受限，需警惕反转"
        
        elif price_dir == "up" and cvd_dir == "down":
            behavior = CapitalBehaviorType.BULLISH_INSUFFICIENT
            signals = ["价格上涨", "主动卖增加"]
            confidence = 70
            implications = "价格被动上涨，资金供给不足"
            suggestion = "上涨可能缺乏后续力度，谨慎看多"
        
        # 空头行为
        elif price_dir == "down" and oi_dir == "up" and cvd_dir == "down":
            behavior = CapitalBehaviorType.NEW_CAPITAL_BEARISH
            signals = ["价格下跌", "持仓增加", "主动卖增加"]
            confidence = 85
            implications = "主动资金建立空头头寸"
            suggestion = "警惕进一步下跌，空头力度强"
        
        elif price_dir == "down" and oi_dir == "down":
            behavior = CapitalBehaviorType.LONGS_TAKING_PROFIT
            signals = ["价格下跌", "持仓减少"]
            confidence = 75
            implications = "多头平仓驱动下跌"
            suggestion = "下跌可能是回调，不是趋势反转"
        
        elif price_dir == "down" and cvd_dir == "up":
            behavior = CapitalBehaviorType.BEARISH_INSUFFICIENT
            signals = ["价格下跌", "主动买增加"]
            confidence = 70
            implications = "下跌缺乏主动卖出支持"
            suggestion = "下跌可能遇到支撑，留意反弹"
        
        # 中性行为
        elif price_dir == "neutral" and oi_dir == "neutral" and cvd_dir == "neutral":
            behavior = CapitalBehaviorType.CONSOLIDATION
            signals = ["价格横盘", "持仓不变", "成交均衡"]
            confidence = 60
            implications = "市场处于盘整，买卖力量均衡"
            suggestion = "等待突破确认，不宜贸然入场"
        
        elif price_dir == "neutral" and oi_dir == "up":
            behavior = CapitalBehaviorType.DISTRIBUTION
            signals = ["价格横盘", "持仓增加"]
            confidence = 65
            implications = "资金进入但还未推动价格"
            suggestion = "可能是突破前的积累，留意方向"
        
        elif price_dir == "neutral" and oi_dir == "down":
            behavior = CapitalBehaviorType.ACCUMULATION
            signals = ["价格横盘", "持仓减少"]
            confidence = 60
            implications = "资金撤离，可能是调整"
            suggestion = "谨慎操作，等待清晰信号"
        
        # 特殊情况：卖压吸收
        elif price_dir == "neutral" and sell_volume > buy_volume * 1.5:
            behavior = CapitalBehaviorType.SELLING_PRESSURE_ABSORBED
            signals = ["价格企稳", "卖出增加", "价格不跌"]
            confidence = 70
            implications = "市场在吸收卖压，可能积蓄多头力量"
            suggestion = "可能是看多的机会，等待反向突破"
        
        # 特殊情况：买压被淹没
        elif price_dir == "neutral" and buy_volume > sell_volume * 1.5:
            behavior = CapitalBehaviorType.BUYING_PRESSURE_OVERWHELMED
            signals = ["价格企稳", "买出增加", "价格不涨"]
            confidence = 70
            implications = "买压被市场吸收，可能积蓄空头力量"
            suggestion = "可能是看空的机会，等待反向突破"
        
        else:
            # 其他不明确的情况
            behavior = CapitalBehaviorType.CONSOLIDATION
            signals = ["数据模糊"]
            confidence = 40
            implications = "市场信号不明确"
            suggestion = "等待更明确的信号"
        
        # 根据资金费率调整可信度
        if funding_rate > 0.05:
            confidence -= 10  # 费率过高，警惕风险
        
        return CapitalBehavior(
            behavior_type=behavior.value,
            description=f"{behavior.value}",
            confidence=min(100, max(0, confidence)),
            signals=signals,
            implications=implications,
            suggestion=suggestion
        )


def analyze_capital_behavior(
    price_change_pct: float,
    oi_change_pct: float,
    cvd_change: float,
    current_cvd: float,
    buy_volume: float,
    sell_volume: float,
    funding_rate: float
) -> Dict:
    """
    便捷函数 - 分析资金行为
    
    Returns:
        可序列化为 JSON 的字典
    """
    behavior = CapitalBehaviorAnalyzer.analyze(
        price_change_pct,
        oi_change_pct,
        cvd_change,
        current_cvd,
        buy_volume,
        sell_volume,
        funding_rate
    )
    
    return {
        "type": behavior.behavior_type,
        "description": behavior.description,
        "confidence": behavior.confidence,
        "signals": behavior.signals,
        "implications": behavior.implications,
        "suggestion": behavior.suggestion
    }
