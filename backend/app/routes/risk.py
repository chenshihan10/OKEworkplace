"""V3.0 风险设置与触达事件接口"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.risk_service import risk_service

router = APIRouter(prefix="/api/v3/risk", tags=["risk"])


class RiskSettingsRequest(BaseModel):
    equity: Optional[float] = Field(None, description="账户权益（USDT），null 表示未配置")
    risk_per_trade_pct: float = Field(1.0, gt=0, le=100)
    max_portfolio_risk_pct: float = Field(6.0, gt=0, le=100)
    max_symbol_concentration_pct: float = Field(50.0, gt=0, le=100)


@router.get("/settings", summary="风险偏好设置")
def get_settings():
    return risk_service.settings()


@router.put("/settings", summary="更新风险偏好设置")
def update_settings(body: RiskSettingsRequest):
    try:
        return risk_service.update_settings(
            equity=body.equity,
            risk_per_trade_pct=body.risk_per_trade_pct,
            max_portfolio_risk_pct=body.max_portfolio_risk_pct,
            max_symbol_concentration_pct=body.max_symbol_concentration_pct,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/events", summary="最近止损/止盈触达事件")
def list_events(symbol: Optional[str] = None, limit: int = 50):
    limit = max(1, min(limit, 200))
    return {"events": risk_service.events(symbol=symbol, limit=limit)}
