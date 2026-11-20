"""V2.3 订单管理 + 价格触及检测 API"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.order_manager import OrderManager

router = APIRouter(prefix="/api/v2.3", tags=["v2.3"])
order_mgr = OrderManager()


# ─── 请求模型 ─────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    symbol: str = Field(..., description="币种，如 BTC-USDT")
    direction: str = Field(..., pattern="^(LONG|SHORT)$")
    entry_price: float = Field(..., gt=0)
    quantity: float = Field(0, ge=0)
    note: str = Field("", max_length=200)


class CloseOrderRequest(BaseModel):
    close_price: float = Field(..., gt=0)
    quantity: Optional[float] = Field(None, ge=0)


class PriceLevelCheckRequest(BaseModel):
    symbol: Optional[str] = Field(None)
    current_price: Optional[float] = Field(None, gt=0)


# ─── 订单 CRUD ─────────────────────────────────────────────


@router.post("/orders", summary="开单")
def create_order(body: CreateOrderRequest):
    try:
        return order_mgr.create_order(
            symbol=body.symbol,
            direction=body.direction,
            entry_price=body.entry_price,
            quantity=body.quantity,
            note=body.note,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/orders", summary="当前持仓列表")
def list_open_orders(symbol: Optional[str] = None):
    orders = order_mgr.get_open_orders(symbol)
    return {"total": len(orders), "orders": orders}


@router.post("/orders/{order_id}/close", summary="平仓")
def close_order(order_id: int, body: CloseOrderRequest):
    try:
        return order_mgr.close_order(order_id, body.close_price, body.quantity)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/orders/history", summary="历史订单")
def order_history(limit: int = 50, offset: int = 0):
    return {"total": len(order_mgr.get_closed_orders(limit=limit, offset=offset)),
            "orders": order_mgr.get_closed_orders(limit=limit, offset=offset)}


@router.get("/orders/summary", summary="订单统计")
def order_summary():
    return order_mgr.get_summary()


# ─── 价格触及检测 ─────────────────────────────────────────


@router.get("/price-levels/check", summary="价格触及检测")
def check_price_levels(symbol: Optional[str] = None, current_price: Optional[float] = None):
    """检测当前价格是否接近某个开单价。

    如果未提供 current_price，尝试从全局缓存获取最新价格。
    进入 ±0.5% 区间时结合系统方向给出建议，并由服务层做 30 分钟冷却。
    """
    from app.services.market_service import market_service

    orders = order_mgr.get_open_orders(symbol)
    if not orders:
        return {"levels": [], "message": "没有正在持仓的订单"}

    # 获取当前行情价格
    snapshot = market_service.snapshot()
    levels = []

    for order in orders:
        price = current_price
        if price is None:
            ticker = snapshot.get("prices", {}).get(order["symbol"], {})
            price = ticker.get("price", ticker.get("last"))

        if price is None:
            continue

        distance_pct = round((price - order["entry_price"]) / order["entry_price"] * 100, 2)
        threshold_pct = 0.5  # ±0.5%
        triggered = abs(distance_pct) <= threshold_pct

        # 构建基础结果
        result = {
            "order_id": order["id"],
            "symbol": order["symbol"],
            "entry_price": order["entry_price"],
            "direction": order["direction"],
            "current_price": price,
            "distance_pct": distance_pct,
            "threshold_pct": threshold_pct,
            "triggered": triggered,
            "suggestion": "observe",
            "reason": "价格尚未回到开仓价附近",
            "alert": False,
            "cooldown_remaining": 0,
        }

        # 在触及范围内时给出不同建议
        if triggered:
            # 尝试获取当前系统评分
            signal = snapshot.get("signals", {}).get(order["symbol"], {})
            sys_dir = signal.get("analysis", {}).get("direction")
            sys_score = signal.get("analysis", {}).get("score")

            if sys_dir and sys_score is not None:
                result["system_direction"] = sys_dir
                result["system_score"] = sys_score
                result["system_confidence"] = signal.get("analysis", {}).get("confidence")

                if sys_dir == order["direction"]:
                    result["suggestion"] = "hold"
                    result["reason"] = f"系统方向 {sys_dir}(评分 {sys_score}) 与你持仓方向一致"
                else:
                    result["suggestion"] = "consider_close"
                    result["reason"] = f"系统方向 {sys_dir}(评分 {sys_score}) 与你持仓方向 {order['direction']} 相反"
            else:
                result["signals_ready"] = False
                result["reason"] = "价格已触及开仓价附近，系统信号尚未就绪"

            # 服务层冷却：同一订单 + 同一建议 30 分钟内只提示一次
            result.update(order_mgr.level_alert_state(order["id"], result["suggestion"]))

        levels.append(result)

    return {"levels": levels}
