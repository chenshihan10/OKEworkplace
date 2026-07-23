from pydantic import BaseModel, Field


class WatchItem(BaseModel):
    symbol: str
    alias: str = None
    timeframe: str = "15m"
    enabled: bool = True


class PricePoint(BaseModel):
    symbol: str
    price: float
    change_24h: float = None
    timestamp: str


class Signal(BaseModel):
    symbol: str
    action: str = Field(description="buy, sell, close_long, close_short, wait")
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: str
