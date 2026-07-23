"""市场分析 API 路由"""
import json
from fastapi import APIRouter, HTTPException, status
from datetime import datetime, timezone

from app.core.config import settings
from app.services.market_service import market_service
from app.model import calculate_market_score, analyze_capital_behavior

router = APIRouter()


def _price_change_pct(inputs: dict) -> float:
    price = inputs.get("price", 0) or 0
    previous = inputs.get("previous_price", price) or price
    if not previous:
        return 0.0
    return (price - previous) / previous * 100


def _estimate_pending_status(symbol: str) -> dict:
    """
    动态评估当前缺失的数据大小及预计剩余计算时间
    """
    prices = market_service._latest_prices
    signals = market_service._latest_signals_cache
    
    # 基础估算参数
    candle_count = 150  # 默认回溯 K 线数
    trade_count = 2000  # 默认聚合的主动买卖单数
    
    # 估算未就绪数据的字节大小 (K 线每条约 0.5KB, 逐笔成交每条约 0.2KB)
    estimated_bytes = 0
    missing_items = []
    
    if symbol not in prices:
        estimated_bytes += 1024 * 5  # Ticker/Orderbook 基础数据约 5KB
        missing_items.append("TickerData")
        
    if symbol not in signals:
        # K 线、CVD、持仓量、资金费率多流对齐，约 2.5MB - 4.5MB
        estimated_bytes += (candle_count * 512 * 4) + (trade_count * 204) 
        missing_items.append("MultiPeriodSignals")
        missing_items.append("OrderFlowCVD")

    # 转化为更易读的 MB 格式
    estimated_mb = round(max(estimated_bytes / (1024 * 1024), 0.45), 2)
    
    # 根据数据量和 API 调度排队情况预估耗时
    estimated_seconds = 5 if "MultiPeriodSignals" in missing_items else 2
    
    return {
        "status": "DATA_SYNCING",
        "symbol": symbol,
        "estimated_data_size": f"{estimated_mb} MB",
        "estimated_wait_time": f"{estimated_seconds}s",
        "missing_components": missing_items,
        "msg": "量化核心指标暂未同步完毕，系统拒绝输出存在误判风险的数据"
    }


def _prepare_analysis_inputs(symbol: str) -> dict:
    """
    为分析准备输入数据
    严格校验：如果最新价格或核心信号缓存未就绪，直接返回 None，绝不提供伪造/过时数据
    """
    prices = market_service._latest_prices
    signals = market_service._latest_signals_cache
    
    # 只要任何一个核心量化数据源缺席，就判定为未就绪
    if symbol not in prices or symbol not in signals:
        return None
    
    ticker = prices[symbol]
    signal = signals[symbol]
    
    return {
        "symbol": symbol,
        "price": ticker.get("price", 0),
        "previous_price": ticker.get("previous_price", ticker.get("price", 0)),
        "candles": signal.get("candles", []),
        "macd": signal.get("macd", {}),
        "ema_data": {
            "ema20": signal.get("ema20", 0),
            "ema60": signal.get("ema60", 0),
            "ema120": signal.get("ema120", 0),
        },
        "oi_change_pct": signal.get("oi_change_pct", 0),
        "funding_rate": signal.get("funding_rate", {}).get("funding_rate", 0),
        "cvd": signal.get("cvd", 0),
        "cvd_change": signal.get("cvd_change", 0),
        "buy_volume": sum(t.get("size", 0) for t in signal.get("trades", []) if t.get("side") == "buy"),
        "sell_volume": sum(t.get("size", 0) for t in signal.get("trades", []) if t.get("side") == "sell"),
        "volatility": signal.get("volatility", 1.5),
        "data_source": "OKX_REAL" if str(ticker.get("source", "")).lower() == "okx" else "FALLBACK",
    }


@router.get("/analysis/{symbol}")
def get_market_analysis(symbol: str):
    """
    获取市场分析结果
    """
    try:
        inputs = _prepare_analysis_inputs(symbol)
        
        # 🟢 严格防线：若核心数据未对齐，抛出 503 并携带明确的数据量与等待时间评估
        if not inputs or inputs["price"] == 0:
            pending_info = _estimate_pending_status(symbol)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=json.dumps(pending_info)  # 序列化为 JSON 字符串，方便前端解析
            )
        
        # 数据 100% 真实、完整时，才向下执行量化模型计算
        market_analysis = calculate_market_score(inputs)
        
        capital_behavior = analyze_capital_behavior(
            price_change_pct=_price_change_pct(inputs),
            oi_change_pct=inputs.get("oi_change_pct", 0),
            cvd_change=inputs.get("cvd_change", 0),
            current_cvd=inputs.get("cvd", 0),
            buy_volume=inputs.get("buy_volume", 0),
            sell_volume=inputs.get("sell_volume", 0),
            funding_rate=inputs.get("funding_rate", 0),
        )
        
        recommendation = _generate_recommendation(market_analysis, capital_behavior, inputs)
        
        return {
            "symbol": symbol,
            "price": market_analysis.price,
            "market_score": market_analysis.market_score,
            "market_state": market_analysis.market_state,
            "confidence": market_analysis.confidence,
            "components": {
                "trend_score": market_analysis.trend_score,
                "capital_score": market_analysis.capital_score,
                "orderflow_score": market_analysis.orderflow_score,
                "risk_score": market_analysis.risk_score,
            },
            "oi_change": market_analysis.oi_change,
            "funding_rate": market_analysis.funding_rate,
            "cvd": market_analysis.cvd,
            "capital_behavior": capital_behavior,
            "recommendation": recommendation,
            "data_source": market_analysis.data_source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _generate_recommendation(market_analysis, capital_behavior: dict, inputs: dict) -> dict:
    """生成双向交易建议（做多/做空）"""
    score = market_analysis.market_score
    confidence = market_analysis.confidence
    behavior = capital_behavior.get("type", "")

    reasons = []
    signal = "WAIT"
    direction = "中性"

    # ─── 综合评分判断方向 ───
    if score >= 75:
        signal = "BUY"
        direction = "做多"
        reasons.append(f"市场评分较高 ({score}/100)，偏多头")
    elif score >= 60:
        signal = "MONITOR"
        direction = "偏多"
        reasons.append(f"市场评分中等偏多 ({score}/100)")
    elif score <= 25:
        signal = "SELL"
        direction = "做空"
        reasons.append(f"市场评分偏低 ({score}/100)，偏空头")
    elif score <= 40:
        signal = "MONITOR_SHORT"
        direction = "偏空"
        reasons.append(f"市场评分中等偏空 ({score}/100)")
    else:
        signal = "WAIT"
        direction = "中性"
        reasons.append(f"市场评分中性 ({score}/100)")

    if confidence < 50:
        if signal in ("BUY", "SELL"):
            signal = "WAIT"
            direction = "中性"
            reasons.append("信号可信度不足，转为观望")

    # ─── 资金行为方向判断 ───
    if "新增资金推动" in behavior:
        reasons.append("有新增资金推动，支持多头")
        if signal in ("WAIT", "MONITOR"):
            signal = "BUY"
            direction = "做多"
    elif "新增资金推空" in behavior:
        reasons.append("有新增资金推空，支持空头")
        if signal in ("WAIT", "MONITOR"):
            signal = "SELL"
            direction = "做空"
    elif "空头回补" in behavior:
        reasons.append("空头回补中，短期偏多")
        if signal == "WAIT":
            signal = "MONITOR"
            direction = "偏多"
    elif "多头获利" in behavior:
        reasons.append("多头获利了结，短期偏空")
        if signal == "WAIT":
            signal = "MONITOR_SHORT"
            direction = "偏空"

    # ─── 风险评估 ───
    if market_analysis.risk_score < -10:
        if signal in ("BUY", "MONITOR"):
            signal = "WAIT"
            direction = "中性"
            reasons.append("风险等级较高，暂避多头")
        elif signal == "SELL":
            pass  # 风险高时做空逻辑不变
        else:
            signal = "AVOID"
            direction = "回避"
            reasons.append("风险等级较高，建议回避")

    if inputs.get("funding_rate", 0) > 0.05:
        signal = "AVOID"
        direction = "回避"
        reasons.append("资金费率过高，多头拥挤")
    elif inputs.get("funding_rate", 0) < -0.05:
        if signal in ("WAIT", "MONITOR"):
            signal = "MONITOR_SHORT"
            direction = "关注做空"
            reasons.append("资金费率过低，空头拥挤，可能轧空")

    return {
        "signal": signal,
        "direction": direction,
        "reason": reasons,
        "confidence": confidence,
    }