"""账户只读路由的离线自证：路由级 token 与未配置占位。

不启动真实服务、不访问 OKX：直接用假的账户服务替换单例，验证路由只读转发。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException  # noqa: E402

from app.routes import account as account_routes  # noqa: E402

STATUS = {
    "available": False, "enabled": False, "configured": False,
    "key_suffix": "", "reason": "未启用实盘只读",
    "resources": {}, "updated_at": None,
}


class FakeService:
    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append(("status",))
        return STATUS

    def summary_view(self):
        self.calls.append(("summary",))
        return {"available": False, "reason": "未启用实盘只读", "data": None}

    def positions_view(self):
        self.calls.append(("positions",))
        return {"available": False, "reason": "未启用实盘只读", "data": None}

    def margin_view(self):
        self.calls.append(("margin",))
        return {"available": False, "data": None, "display_only": True}

    def fills_view(self, limit=50, offset=0, inst_id=None):
        self.calls.append(("fills", limit, offset, inst_id))
        return {"available": False, "total": 0, "items": []}

    def config_view(self):
        self.calls.append(("config",))
        return {"available": False, "data": None}


def _request(headers=None, params=None):
    return SimpleNamespace(headers=headers or {}, query_params=params or {})


def _with_service(func):
    fake = FakeService()
    original = account_routes.get_account_service
    account_routes.get_account_service = lambda: fake
    try:
        return func(fake)
    finally:
        account_routes.get_account_service = original


def _with_token(token):
    previous = os.environ.get("OKE_LOCAL_TOKEN")
    os.environ["OKE_LOCAL_TOKEN"] = token
    return previous


def _restore_token(previous):
    if previous is None:
        os.environ.pop("OKE_LOCAL_TOKEN", None)
    else:
        os.environ["OKE_LOCAL_TOKEN"] = previous


def test_router_prefix_and_paths():
    assert account_routes.router.prefix == "/api/v3/account"
    paths = {route.path for route in account_routes.router.routes}
    assert paths == {
        "/api/v3/account/status",
        "/api/v3/account/summary",
        "/api/v3/account/positions",
        "/api/v3/account/margin",
        "/api/v3/account/fills",
        "/api/v3/account/config",
    }
    # 路由级依赖必须挂在每个接口上
    assert all(route.dependencies for route in account_routes.router.routes)


def test_require_local_token_skips_when_unset():
    previous = os.environ.pop("OKE_LOCAL_TOKEN", None)
    try:
        account_routes.require_local_token(_request())
    finally:
        _restore_token(previous)


def test_require_local_token_enforces_header_and_query():
    previous = _with_token("tok-123")
    try:
        try:
            account_routes.require_local_token(_request())
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("缺少 token 必须 403")

        try:
            account_routes.require_local_token(_request({"x-oke-token": "wrong"}))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("错误 token 必须 403")

        account_routes.require_local_token(_request({"x-oke-token": "tok-123"}))
        account_routes.require_local_token(_request(params={"token": "tok-123"}))
    finally:
        _restore_token(previous)


def test_endpoints_return_placeholders_without_key():
    def run(fake):
        assert account_routes.account_status()["enabled"] is False
        assert account_routes.account_summary()["data"] is None
        assert account_routes.account_positions()["data"] is None
        assert account_routes.account_margin()["display_only"] is True
        assert account_routes.account_config()["available"] is False
        fills = account_routes.account_fills(limit=20, offset=40, inst_id="BTC-USDT-SWAP")
        assert fills["items"] == []
        assert ("fills", 20, 40, "BTC-USDT-SWAP") in fake.calls

    _with_service(run)


def test_http_layer_enforces_token():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(account_routes.router)

    def run(_fake):
        previous = _with_token("tok-http")
        try:
            with TestClient(app) as client:
                assert client.get("/api/v3/account/status").status_code == 403
                assert client.get(
                    "/api/v3/account/status", headers={"x-oke-token": "bad"}
                ).status_code == 403
                ok = client.get(
                    "/api/v3/account/status", headers={"x-oke-token": "tok-http"}
                )
                assert ok.status_code == 200
                assert ok.json()["enabled"] is False
                via_query = client.get("/api/v3/account/status?token=tok-http")
                assert via_query.status_code == 200
        finally:
            _restore_token(previous)

    _with_service(run)


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
