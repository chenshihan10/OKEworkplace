"""账户服务离线自证：未配置不发请求、部分失败保留旧值、鉴权退避、成交增量去重。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.services.account_service import AccountService  # noqa: E402
from app.services.account_store import AccountStore  # noqa: E402
from app.services.okx_private_client import OKXPrivateError  # noqa: E402

SUMMARY = {"code": "0", "data": [{
    "totalEq": "1234.56", "availEq": "900", "upl": "12.3",
    "imr": "300", "mmr": "60", "mgnRatio": "4.2", "ordFrozen": "0",
    "details": [{"ccy": "USDT", "eq": "1200", "availBal": "900",
                 "frozenBal": "0", "upl": "12.3", "eqUsd": "1200"}],
}]}

POSITIONS = {"code": "0", "data": [{
    "instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "2",
    "avgPx": "60000", "markPx": "60100", "upl": "20", "uplRatio": "0.0167",
    "lever": "3", "liqPx": "40000", "mgnRatio": "12.5", "mgnMode": "cross",
}]}

CONFIG = {"code": "0", "data": [{
    "acctLv": "2", "posMode": "long_short_mode", "mgnIsoMode": "auto_transfers_ccy",
}]}

FILLS = {"code": "0", "data": [
    {"instId": "BTC-USDT-SWAP", "tradeId": "11", "ordId": "a1", "side": "buy",
     "posSide": "long", "fillPx": "60000", "fillSz": "1", "fee": "-0.5",
     "feeCcy": "USDT", "ts": "1700000000000"},
    {"instId": "BTC-USDT-SWAP", "tradeId": "12", "ordId": "a2", "side": "sell",
     "posSide": "long", "fillPx": "60100", "fillSz": "1", "fee": "-0.5",
     "feeCcy": "USDT", "ts": "1700000060000"},
]}


class FakeClient:
    def __init__(self, responses=None, configured=True):
        self.responses = dict(responses or {})
        self.configured = configured
        self.calls = []

    def is_configured(self):
        return self.configured

    @property
    def key_suffix(self):
        return "1234"

    def get(self, path, params=None):
        self.calls.append((path, params))
        result = self.responses[path]
        if isinstance(result, Exception):
            raise result
        return result


def _service(client=None, tmp=None):
    store = AccountStore(tmp)
    return AccountService(store=store, client=client or FakeClient()), store


def _enable(enabled=True):
    previous = settings.private_read_enabled
    settings.private_read_enabled = enabled
    return previous


def test_disabled_makes_no_request():
    previous = _enable(False)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            service, _ = _service(FakeClient({}), tmp)
            status = service.refresh_all()
            assert service._client.calls == []
            assert status["enabled"] is False
            assert status["available"] is False
            assert "未启用" in service.summary_view()["reason"]
        finally:
            _enable(previous)


def test_unconfigured_makes_no_request():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            service, _ = _service(FakeClient({}, configured=False), tmp)
            service.refresh_all()
            assert service._client.calls == []
            view = service.summary_view()
            assert view["available"] is False
            assert "未配置" in view["reason"]
        finally:
            _enable(previous)


def test_refresh_parses_all_resources_and_snapshots_once():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({
                "/api/v5/account/balance": SUMMARY,
                "/api/v5/account/positions": POSITIONS,
                "/api/v5/account/config": CONFIG,
            })
            service, store = _service(client, tmp)
            service.refresh_all()
            service.refresh_config()

            summary = service.summary_view()
            assert summary["available"] is True and summary["stale"] is False
            assert summary["data"]["total_eq"] == 1234.56
            assert summary["data"]["details"][0]["ccy"] == "USDT"

            positions = service.positions_view()
            assert positions["data"][0]["pos_unit"] == "contract"
            assert positions["data"][0]["pos_raw"] == 2.0

            config = service.config_view()
            assert config["data"]["acct_lv"] == "2"
            assert config["data"]["mgn_mode"] == "auto_transfers_ccy"

            # 第二次刷新不重复落快照
            service.refresh_all()
            assert store.stats()["counts"]["account_snapshots"] == 1
            assert store.stats()["counts"]["position_snapshots"] == 1
            # 成交任务未被 refresh_all 触发
            called = {path for path, _ in client.calls}
            assert "/api/v5/trade/fills-history" not in called
        finally:
            _enable(previous)


def test_failure_keeps_old_data_and_marks_stale():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({
                "/api/v5/account/balance": SUMMARY,
                "/api/v5/account/positions": POSITIONS,
            })
            service, _ = _service(client, tmp)
            service.refresh_all()
            original = service.summary_view()["data"]

            client.responses["/api/v5/account/balance"] = OKXPrivateError(
                "OKX 业务错误 50011: Too Many Requests",
                code="50011", category="rate_limit",
            )
            service.refresh_summary()
            view = service.summary_view()
            assert view["available"] is True
            assert view["stale"] is True
            assert view["data"] == original
            assert "50011" in view["reason"]
        finally:
            _enable(previous)


def test_auth_error_backs_off_without_retry():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({
                "/api/v5/account/balance": OKXPrivateError(
                    "OKX 业务错误 50111: Invalid Key", code="50111", category="auth"
                ),
                "/api/v5/account/positions": POSITIONS,
            })
            service, _ = _service(client, tmp)
            service.refresh_all()
            assert service._resources["summary"]["available"] is False
            assert service._resources["summary"]["next_attempt_at"] is not None
            calls = len(client.calls)

            service.refresh_summary()
            assert len(client.calls) == calls  # 退避期内不再请求
            assert service.positions_view()["available"] is True  # 其他资源不受影响
        finally:
            _enable(previous)


def test_fills_incremental_dedupe_and_cursor():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({"/api/v5/trade/fills-history": FILLS})
            service, store = _service(client, tmp)
            service.sync_fills()
            assert store.get_fills(limit=10)["total"] == 2
            latest = store.get_fills(limit=1)["items"][0]
            # fills-history 实际返回 fillPx / fillSz，必须落库成 px / sz
            assert latest["px"] == 60100.0
            assert latest["sz"] == 1.0
            assert service._cursor == 1700000060000
            assert store.get_state("fills_cursor") == "1700000060000"

            service.sync_fills()
            assert store.get_fills(limit=10)["total"] == 2  # 主键去重
            assert service.fills_view()["pending"] is False
        finally:
            _enable(previous)


def test_margin_view_is_derived_and_display_only():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({
                "/api/v5/account/balance": SUMMARY,
                "/api/v5/account/positions": POSITIONS,
            })
            service, _ = _service(client, tmp)
            service.refresh_all()
            margin = service.margin_view()
            assert margin["available"] is True
            assert margin["display_only"] is True
            assert margin["data"]["account"]["mgn_ratio"] == 4.2
            assert margin["data"]["positions"][0]["liq_px"] == 40000.0
            assert margin["sources"] == [
                "/api/v5/account/balance", "/api/v5/account/positions",
            ]
        finally:
            _enable(previous)


POSITIONS_P2 = {"code": "0", "data": [
    {"instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "2",
     "avgPx": "60000", "markPx": "60100", "upl": "20", "lever": "3",
     "liqPx": "40000", "mgnRatio": "12.5", "mgnMode": "cross", "notionalUsd": "12000"},
    {"instId": "SOL-USDT-SWAP", "posSide": "short", "pos": "10",
     "avgPx": "100", "markPx": "99", "upl": "5", "lever": "5",
     "liqPx": "150", "mgnRatio": "8", "mgnMode": "cross", "notionalUsd": "2000"},
]}


class FakeOrders:
    def __init__(self, orders=None, concentration=50.0):
        self.orders = orders or []
        self.concentration = concentration

    def get_open_orders(self):
        return list(self.orders)

    def get_risk_settings(self):
        return {"max_symbol_concentration_pct": self.concentration}


def _service_p2(client, orders, tmp):
    store = AccountStore(tmp)
    return AccountService(store=store, client=client, orders_provider=lambda: orders), store


def test_risk_view_exposure_and_concentration():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({
                "/api/v5/account/balance": SUMMARY,
                "/api/v5/account/positions": POSITIONS_P2,
            })
            service, _ = _service_p2(client, FakeOrders(concentration=50.0), tmp)
            service.refresh_all()
            risk = service.risk_view()
            assert risk["available"] is True
            assert risk["display_only"] is True
            data = risk["data"]
            assert data["exposure"]["long_notional"] == 12000.0
            assert data["exposure"]["short_notional"] == 2000.0
            assert data["exposure"]["net_notional"] == 10000.0
            assert data["exposure"]["total_notional"] == 14000.0
            assert data["concentration"]["inst_id"] == "BTC-USDT-SWAP"
            assert abs(data["concentration"]["pct"] - 12000 / 14000) < 1e-9
            assert data["concentration"]["exceeded"] is True
            assert any(w["type"] == "concentration" for w in data["warnings"])
            btc = [r for r in data["positions"] if r["inst_id"] == "BTC-USDT-SWAP"][0]
            assert abs(btc["liq_distance_pct"] - (60100 - 40000) / 60100) < 1e-9
            # 强平距离最小的是 BTC（33%），不触发 10% 告警
            assert all(w["type"] != "liquidation" for w in data["warnings"])
        finally:
            _enable(previous)


def test_reconciliation_flags_local_only_live_only_and_mismatch():
    previous = _enable(True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = FakeClient({
                "/api/v5/account/balance": SUMMARY,
                "/api/v5/account/positions": POSITIONS_P2,
            })
            orders = FakeOrders([
                {"symbol": "BTC-USDT", "direction": "LONG", "quantity": 0.2,
                 "entry_price": 60000},                       # 与实盘 12000 USD 一致
                {"symbol": "ETH-USDT", "direction": "LONG", "quantity": 1,
                 "entry_price": 2000},                        # 本地有、实盘无
                {"symbol": "SOL-USDT", "direction": "SHORT", "quantity": 5,
                 "entry_price": 99},                          # 实盘 2000 USD，本地 495 USD → 数量不一致
            ])
            service, _ = _service_p2(client, orders, tmp)
            service.refresh_all()
            view = service.reconciliation_view()
            assert view["available"] is True
            assert view["display_only"] is True
            rows = {row["symbol"]: row for row in view["data"]["rows"]}
            assert rows["BTC-USDT"]["status"] == "matched"
            assert rows["ETH-USDT"]["status"] == "local_only"
            assert rows["ETH-USDT"]["live"] is None
            assert rows["SOL-USDT"]["status"] == "qty_mismatch"
            counts = view["data"]["counts"]
            assert counts["matched"] == 1
            assert counts["local_only"] == 1
            assert counts["qty_mismatch"] == 1
            # 只读：绝不写回本地 orders 表
            assert len(orders.orders) == 3
        finally:
            _enable(previous)


if __name__ == "__main__":
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("FAIL", name, "->", exc)
    raise SystemExit(1 if failures else 0)
