"""v2.1 市场分析 API 路由"""
import json
from fastapi import APIRouter, HTTPException, status
from datetime import datetime, timezone

from app.core.config import settings
from app.services.market_service import market_service
from app.services.db_store import SignalDB
from app.services.decision_engine import build_decision_trace, compute_confidence, detect_trend_phase
from app.services.market_regime import classify_from_signal

router = APIRouter()


def _estimate_pending_status(symbol: str) -> dict:
    prices = market_service._latest_prices
    signals = market_service._latest_signals_cache

    estimated_bytes = 0
    missing_items = []

    if symbol not in prices:
        estimated_bytes += 1024 * 5
        missing_items.append("TickerData")

    if symbol not in signals:
        estimated_bytes += 4 * 1024 * 1024
        missing_items.append("SignalData")

    estimated_mb = round(max(estimated_bytes / (1024 * 1024), 0.45), 2)
    estimated_seconds = 5 if "SignalData" in missing_items else 2

    return {
        "status": "DATA_SYNCING",
        "symbol": symbol,
        "estimated_data_size": f"{estimated_mb} MB",
        "estimated_wait_time": f"{estimated_seconds}s",
        "missing_components": missing_items,
        "msg": "量化核心指标暂未同步完毕，系统拒绝输出存在误判风险的数据"
    }


def _generate_recommendation(analysis, capital_behavior: dict) -> dict:
    """v2.1：基于 v2.1 AnalysisResult 生成交易建议"""
    score = analysis.score
    direction = analysis.direction
    level = analysis.level
    risk = analysis.risk
    components = analysis.components
    reasons = list(analysis.reasons)  # 复制一份
    behavior = capital_behavior.get("type", "")

    signal = "WAIT"
    direction_label = "中性"

    # 根据评分 + 方向综合判断
    if direction == "LONG" and score >= 70:
        if score >= 85:
            signal = "BUY"
            direction_label = "强烈做多"
        elif score >= 70:
            signal = "BUY"
            direction_label = "做多"
        else:
            signal = "MONITOR"
            direction_label = "关注做多"
    elif direction == "SHORT" and score >= 70:
        if score >= 85:
            signal = "SELL"
            direction_label = "强烈做空"
        elif score >= 70:
            signal = "SELL"
            direction_label = "做空"
        else:
            signal = "MONITOR_SHORT"
            direction_label = "关注做空"
    elif score >= 55:
        if direction == "LONG":
            signal = "MONITOR"
            direction_label = "偏多观察"
        elif direction == "SHORT":
            signal = "MONITOR_SHORT"
            direction_label = "偏空观察"
        else:
            signal = "WAIT"
            direction_label = "中性观望"
    else:
        signal = "WAIT"
        direction_label = "观望"

    # 风险调整
    if risk == "HIGH" and signal in ("BUY", "SELL", "MONITOR", "MONITOR_SHORT"):
        reasons.append("风险等级高，建议减仓或观望")

    # 资金费率极端
    funding_rate = analysis.indicators.get("funding_rate", 0) or 0
    if funding_rate > 0.05:
        reasons.append("资金费率过高，多头拥挤")
        if signal == "BUY":
            signal = "WAIT"
            direction_label = "观望（多头拥挤）"
    elif funding_rate < -0.05:
        reasons.append("资金费率极低，空头拥挤可能轧空")
        if signal == "SELL":
            signal = "WAIT"
            direction_label = "观望（空头拥挤）"

    # 资金行为补充
    if "新增资金推动" in behavior and direction == "LONG":
        reasons.append("资金行为验证：新增多头资金推动")
    elif "新增资金推空" in behavior and direction == "SHORT":
        reasons.append("资金行为验证：新增空头资金推动")
    elif "背离" in behavior:
        reasons.append(f"资金行为与方向不一致：{behavior}")

    return {
        "signal": signal,
        "direction": direction_label,
        "reason": reasons,
        "score": score,
        "level": level,
        "risk": risk,
    }


@router.get("/analysis/{symbol}")
def get_market_analysis(symbol: str):
    """v2.1 市场分析接口"""
    try:
        prices = market_service._latest_prices
        signals = market_service._latest_signals_cache

        if symbol not in prices or symbol not in signals:
            pending_info = _estimate_pending_status(symbol)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=json.dumps(pending_info)
            )

        ticker = prices[symbol]
        signal = signals[symbol]
        analysis = signal.get("analysis")

        if not analysis or ticker.get("price", 0) == 0:
            pending_info = _estimate_pending_status(symbol)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=json.dumps(pending_info)
            )

        # 资金行为：需要真实买卖量（逐笔成交）才有意义。
        # 此前固定传 buy_volume=0 / sell_volume=0，分析器恒定输出“数据模糊”，属于误导性结论。
        # 在接入真实 trades 数据源之前，明确返回不可用，不再执行该计算。
        capital_behavior = {
            "type": "unavailable",
            "available": False,
            "reason": "缺少真实买卖量数据，资金行为暂不可用",
        }

        recommendation = _generate_recommendation(analysis, capital_behavior)

        # v2.2：Decision Trace + Confidence
        inputs_for_trace = signal  # signal dict 自带 ema20, ema60, rsi14, candles, etc.
        decision_trace = build_decision_trace(symbol, analysis, inputs_for_trace)
        confidence = compute_confidence(analysis, decision_trace)

        # v3.0 前置：市场状态分类（纯规则，不参与现有评分）
        market_regime = classify_from_signal(signal, analysis.price)

        return {
            "symbol": symbol,
            "price": analysis.price,
            "score": analysis.score,
            "level": analysis.level,
            "direction": analysis.direction,
            "raw_direction": signal.get("raw_direction"),        # v2.2：原始方向（过滤前）
            "direction_changed": signal.get("direction_changed", False),  # v2.2：是否发生了方向变更
            "mark_price": signal.get("mark_price", 0),
            "index_price": signal.get("index_price", 0),
            "mark_index_spread": signal.get("mark_index_spread", 0),
            "mark_index_spread_pct": signal.get("mark_index_spread_pct", 0),
            "risk": analysis.risk,
            "risk_factors": analysis.risk_factors,
            "components": analysis.components,
            "reasons": analysis.reasons,
            "indicators": analysis.indicators,
            "capital_behavior": capital_behavior,
            "recommendation": recommendation,
            "decision_trace": {
                "items": [vars(item) for item in decision_trace.items],
                "summary": decision_trace.summary,
            },
            "confidence": confidence,
            "trend_phase": decision_trace.trend_phase,  # v2.2：趋势阶段
            "market_regime": market_regime,  # v3.0：市场状态分类
            "data_source": analysis.data_source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-regime/{symbol}")
def get_market_regime(symbol: str):
    """v3.0：单独查询市场状态（牛/熊/震荡/高波动/数据不足）

    该接口是只读的降级查询：数据未就绪、币种不在监控列表或判定异常时，
    统一返回 200 + regime=UNKNOWN，把原因放在 reasons/pending_info 里，
    不再抛 5xx（避免调用方把“暂未同步”当成接口故障）。
    """
    prices = market_service._latest_prices
    signals = market_service._latest_signals_cache

    if symbol not in prices or symbol not in signals:
        pending_info = _estimate_pending_status(symbol)
        return {
            "regime": "UNKNOWN",
            "label": "数据不足",
            "atr_pct": None,
            "ema_spread_pct": None,
            "reasons": [pending_info["msg"]],
            "thresholds": None,
            "symbol": symbol,
            "pending": True,
            "pending_info": pending_info,
        }

    ticker = prices[symbol]
    try:
        result = classify_from_signal(signals[symbol], ticker.get("price"))
    except Exception as e:  # 指标异常不应让整个查询报错
        return {
            "regime": "UNKNOWN",
            "label": "数据不足",
            "atr_pct": None,
            "ema_spread_pct": None,
            "reasons": [f"市场状态判定失败：{e}"],
            "thresholds": None,
            "symbol": symbol,
            "price": ticker.get("price"),
            "source": ticker.get("source"),
            "pending": False,
        }

    result["symbol"] = symbol
    result["price"] = ticker.get("price")
    result["source"] = ticker.get("source")
    return result


@router.get("/signals/history/{symbol}")
def get_signal_history(symbol: str, limit: int = 50):
    """v2.2 获取信号历史"""
    try:
        db = SignalDB()
        signals = db.get_recent_signals(symbol, limit=limit)
        stats = db.get_signal_stats(symbol)
        return {
            "symbol": symbol,
            "total": len(signals),
            "signals": signals,
            "stats": stats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
