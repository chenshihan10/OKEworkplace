from fastapi import APIRouter

from app.models import WatchItem
from app.services.market_service import market_service

router = APIRouter()


@router.get("/available")
def list_available_coins():
    """返回 OKX 所有可交易的 USDT 永续合约"""
    return market_service.list_available_coins()


@router.get("")
def list_watch_items():
    return market_service.list_watch_items()


@router.post("")
def add_watch_item(item: WatchItem) -> WatchItem:
    return market_service.add_watch_item(item)


@router.delete("/{symbol}")
def remove_watch_item(symbol: str) -> dict:
    market_service.remove_watch_item(symbol)
    return {"status": "removed", "symbol": symbol}
