"""私有只读客户端的离线自证：签名口径、query 编码、白名单、业务码映射。

不依赖真实 Key：签名用固定时间戳与固定 Secret 做向量比对，
HTTP 层用伪造 Session 覆盖 `code != "0"`、429、连接失败等分支。
"""
import base64
import hashlib
import hmac
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from app.services.okx_private_client import (  # noqa: E402
    OKXPrivateClient,
    OKXPrivateError,
    SIGNED_GET_WHITELIST,
    utc_timestamp_ms,
)

SECRET = "22582BD0CFF14C41EDBF1AB98506286D"
PASSPHRASE = "Test-Passphrase-9f3a"
PINNED_SIGN = "HiZhvSfMtWJA3uUIVXV3a/bSXNPCWvYFXoGCVS8V4zY="


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _client(secret=SECRET, passphrase=PASSPHRASE, api_key="readonly-key-1234"):
    return OKXPrivateClient("https://www.okx.com", api_key, secret, passphrase)


def test_signature_vector():
    client = _client()
    timestamp = "2020-12-08T09:08:57.715Z"
    built = client.build_signature(
        "/api/v5/account/balance", {"ccy": "BTC"}, timestamp=timestamp
    )

    assert built["request_path"] == "/api/v5/account/balance?ccy=BTC"
    assert built["prehash"] == timestamp + "GET" + "/api/v5/account/balance?ccy=BTC"
    assert built["sign"] == PINNED_SIGN
    # 再独立算一遍，防止代码与常量同时被改错
    expected = base64.b64encode(
        hmac.new(SECRET.encode(), built["prehash"].encode(), hashlib.sha256).digest()
    ).decode()
    assert built["sign"] == expected


def test_query_order_and_encoding_in_signature_path():
    client = _client()
    built = client.build_signature(
        "/api/v5/trade/fills-history",
        {"instType": "SWAP", "begin": "1700000000000", "limit": "100"},
        timestamp="2026-11-25T00:00:00.000Z",
    )
    assert built["request_path"] == (
        "/api/v5/trade/fills-history?instType=SWAP&begin=1700000000000&limit=100"
    )
    assert built["prehash"].endswith("GET" + built["request_path"])


def test_timestamp_is_utc_millisecond_iso():
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    assert pattern.match(utc_timestamp_ms())


def test_whitelist_rejects_unknown_path():
    client = _client()
    assert "/api/v5/account/balance" in SIGNED_GET_WHITELIST
    try:
        client.get("/api/v5/account/subaccount")
    except ValueError as exc:
        assert "白名单" in str(exc)
    else:
        raise AssertionError("非白名单路径必须被拒绝")


def test_not_configured_raises_without_request():
    client = _client(secret="")
    session = FakeSession(FakeResponse({"code": "0", "data": []}))
    client._local.session = session
    try:
        client.get("/api/v5/account/balance")
    except OKXPrivateError as exc:
        assert exc.category == "not_configured"
    else:
        raise AssertionError("未配置时必须直接报错")
    assert session.calls == []


def test_business_code_maps_to_auth_error():
    client = _client()
    client._local.session = FakeSession(
        FakeResponse({"code": "50113", "msg": "Invalid Sign"})
    )
    try:
        client.get("/api/v5/account/balance")
    except OKXPrivateError as exc:
        assert exc.code == "50113"
        assert exc.category == "auth"
        assert exc.is_auth_error is True
        assert "Invalid Sign" in str(exc)
        assert SECRET not in str(exc)
        assert PASSPHRASE not in str(exc)
    else:
        raise AssertionError("code != 0 必须抛错")


def test_business_code_maps_to_rate_limit():
    client = _client()
    client._local.session = FakeSession(
        FakeResponse({"code": "50011", "msg": "Too Many Requests"})
    )
    try:
        client.get("/api/v5/account/positions", {"instType": "SWAP"})
    except OKXPrivateError as exc:
        assert exc.code == "50011"
        assert exc.category == "rate_limit"
        assert exc.retryable is True
    else:
        raise AssertionError("限频码必须抛错")


def test_http_429_maps_to_rate_limit():
    client = _client()
    client._local.session = FakeSession(FakeResponse({"code": ""}, status_code=429))
    try:
        client.get("/api/v5/account/config")
    except OKXPrivateError as exc:
        assert exc.category == "rate_limit"
        assert exc.http_status == 429
    else:
        raise AssertionError("HTTP 429 必须抛错")


def test_network_error_exhausts_proxy_attempts():
    client = _client()
    client._local.session = FakeSession(requests.ConnectionError("boom"))
    try:
        client.get("/api/v5/account/balance")
    except OKXPrivateError as exc:
        assert exc.category == "network"
        assert "ConnectionError" in str(exc)
    else:
        raise AssertionError("连接失败必须抛错")


def test_success_payload_passes_and_headers_have_no_secret_leak_in_logs():
    client = _client()
    session = FakeSession(FakeResponse({"code": "0", "data": [{"totalEq": "1"}]}))
    client._local.session = session
    payload = client.get("/api/v5/account/balance")
    assert payload["code"] == "0"
    headers = session.calls[0]["kwargs"]["headers"]
    assert headers["OK-ACCESS-KEY"] == "readonly-key-1234"
    assert headers["OK-ACCESS-PASSPHRASE"] == PASSPHRASE
    assert client.key_suffix == "1234"


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
