from fastapi import APIRouter

from app.services.market_service import market_service

router = APIRouter()


@router.get("/snapshot")
def snapshot() -> dict:
    return market_service.snapshot()


@router.get("/signals")
def signals():
    return market_service.latest_signals()


@router.get("/alerts")
def alerts():
    return market_service.snapshot()["alerts"]
