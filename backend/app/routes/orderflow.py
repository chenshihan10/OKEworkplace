"""V3.0 订单流（REST 采样）查询接口"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from app.services.order_flow_service import order_flow_service

router = APIRouter(prefix="/api/v3/orderflow", tags=["orderflow"])


@router.get("", summary="全部关注币种的订单流快照")
def list_orderflow():
    return order_flow_service.snapshot()


@router.get("/{symbol}/large-trades", summary="最近大单")
def large_trades(symbol: str, limit: int = 20):
    return order_flow_service.large_trades(symbol, limit=limit)


@router.get("/{symbol}/history", summary="订单流采样历史")
def orderflow_history(symbol: str, start: Optional[str] = None,
                      end: Optional[str] = None, limit: int = 200):
    return order_flow_service.history(symbol=symbol, start=start, end=end, limit=limit)


@router.get("/{symbol}", summary="当前窗口订单流指标")
def get_orderflow(symbol: str):
    """只读缓存；未预热时返回 200 + available=false。"""
    return order_flow_service.get(symbol)
