import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.market_service import market_service


def test_refresh_and_snapshot() -> None:
    market_service.refresh_all()
    snapshot = market_service.snapshot()
    assert "watch_items" in snapshot
    assert "prices" in snapshot
    assert "signals" in snapshot
    assert "alerts" in snapshot
