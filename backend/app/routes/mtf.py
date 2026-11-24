"""V3.0 多周期（MTF）查询接口"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.multi_timeframe_service import multi_timeframe_service

router = APIRouter(prefix="/api/v3/mtf", tags=["mtf"])


@router.get("", summary="全部关注币种的多周期快照")
def list_mtf():
    return multi_timeframe_service.snapshot()


@router.get("/{symbol}", summary="单个币种的多周期与共振结论")
def get_mtf(symbol: str):
    """只读缓存；未预热时返回 200 + pending=true。"""
    return multi_timeframe_service.get(symbol)
