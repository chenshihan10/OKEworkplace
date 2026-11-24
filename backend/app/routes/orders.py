"""V2.3 订单管理 + 价格触及检测 API"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.order_manager import OrderManager
from app.services.risk_service import risk_service

router = APIRouter(prefix="/api/v2.3", tags=["v2.3"])
order_mgr = OrderManager()


# ─── 请求模型 ─────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    symbol: str = Field(..., description="币种，如 BTC-USDT")
    direction: str = Field(..., pattern="^(LONG|SHORT)$")
    entry_price: float = Field(..., gt=0)
    quantity: float = Field(0, ge=0)
    note: str = Field("", max_length=200)
    stop_loss: Optional[float] = Field(None, description="止损价（可选）")
    take_profit: Optional[float] = Field(None, description="止盈价（可选）")


class CloseOrderRequest(BaseModel):
    close_price: float = Field(..., gt=0)
    quantity: Optional[float] = Field(None, ge=0)
    exit_reason: str = Field("manual", description="manual / sl_hit / tp_hit")


class UpdateRiskRequest(BaseModel):
    stop_loss: Optional[float] = Field(None, description="止损价，null 表示清除")
    take_profit: Optional[float] = Field(None, description="止盈价，null 表示清除")


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
            stop_loss=body.stop_loss,
            take_profit=body.take_profit,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/orders", summary="当前持仓列表")
def list_open_orders(symbol: Optional[str] = None):
    orders = order_mgr.get_open_orders(symbol)
    return {"total": len(orders), "orders": orders}


@router.post("/orders/{order_id}/close", summary="平仓")
def close_order(order_id: int, body: CloseOrderRequest):
    try:
        return order_mgr.close_order(
            order_id, body.close_price, body.quantity, exit_reason=body.exit_reason
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@router.patch("/orders/{order_id}/risk", summary="设置/清除止损止盈")
def update_order_risk(order_id: int, body: UpdateRiskRequest):
    try:
        return order_mgr.update_order_risk(order_id, body.stop_loss, body.take_profit)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/orders/history", summary="历史订单")
def order_history(limit: int = 50, offset: int = 0):
    return {"total": len(order_mgr.get_closed_orders(limit=limit, offset=offset)),
            "orders": order_mgr.get_closed_orders(limit=limit, offset=offset)}


@router.get("/orders/summary", summary="订单统计")
def order_summary():
    return order_mgr.get_summary()


@router.get("/risk/portfolio", summary="组合风险汇总")
def risk_portfolio():
    return risk_service.portfolio()


# ─── 价格触及检测 ─────────────────────────────────────────


@router.get("/price-levels/check", summary="价格触及检测（含止损/止盈）")
def check_price_levels(symbol: Optional[str] = None, current_price: Optional[float] = None):
    """检测价格是否接近开仓价，以及是否触及止损/止盈。

    如果未提供 current_price，从全局缓存获取最新价格（不额外请求 OKX）。
    开仓价 ±0.5% 区间结合系统方向给出建议；止损/止盈触达写入 risk_events，
    同一订单同一事件 30 分钟冷却，仅提示，不自动平仓。
    """
    result = risk_service.check_price_levels(symbol=symbol, current_price=current_price)
    if not result["levels"]:
        return {**result, "message": "没有正在持仓的订单"}
    return result
