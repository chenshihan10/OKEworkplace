"""V2.6 实盘只读：OKX 私有 REST 客户端（只签名 GET）。

边界：
- 只允许 `SIGNED_GET_WHITELIST` 中的路径；不提供通用 request，也不实现写操作；
- 签名口径与 OKX v5 文档一致：`timestamp + METHOD + requestPath(含 query) + body`；
  时间戳为 UTC 毫秒（偏差超过 30 秒服务端返回 50102）；
- 代理复用公共客户端的尝试链（环境变量 → 注册表 → .env → 直连），
  TLS 固定使用 certifi，不提供 `verify=False` 开关；
- 使用独立线程内 Session，避免私有请求的签名头污染公共行情请求；
- 日志只记录 path、错误码与耗时，不记录 Secret、Passphrase、签名与完整 header。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from app.services.oke_client import CA_BUNDLE, build_proxy_attempts

logger = logging.getLogger(__name__)

# 私有只读允许的路径白名单；新增接口必须显式加入这里
SIGNED_GET_WHITELIST = frozenset({
    "/api/v5/account/balance",
    "/api/v5/account/positions",
    "/api/v5/account/config",
    "/api/v5/trade/fills-history",
})

AUTH_ERROR_CODES = frozenset({"50111", "50113", "50114"})
CLOCK_ERROR_CODES = frozenset({"50102"})
RATE_LIMIT_ERROR_CODES = frozenset({"50011"})
UNAVAILABLE_ERROR_CODES = frozenset({"50001", "50004"})


def utc_timestamp_ms() -> str:
    """OKX 要求的 ISO8601 UTC 毫秒时间戳，例如 2026-11-25T02:03:04.567Z。"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _classify_code(code: str) -> str:
    if code in AUTH_ERROR_CODES:
        return "auth"
    if code in CLOCK_ERROR_CODES:
        return "clock"
    if code in RATE_LIMIT_ERROR_CODES:
        return "rate_limit"
    if code in UNAVAILABLE_ERROR_CODES:
        return "unavailable"
    return "business"


class OKXPrivateError(RuntimeError):
    """私有接口错误：携带业务码与分类，便于服务层决定退避策略。

    异常文本只拼业务码与服务端 msg，不包含 Key/Secret/Passphrase/签名。
    """

    def __init__(self, message: str, code: str = "", category: str = "business",
                 http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.http_status = http_status

    @property
    def is_auth_error(self) -> bool:
        return self.category == "auth"

    @property
    def needs_clock_check(self) -> bool:
        return self.category == "clock"

    @property
    def retryable(self) -> bool:
        return self.category in ("rate_limit", "unavailable", "network")


class OKXPrivateClient:
    def __init__(self, base_url: str, api_key: str, secret_key: str, passphrase: str,
                 timeout_seconds: int = 10) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._secret_key = secret_key or ""
        self._passphrase = passphrase or ""
        self.timeout_seconds = timeout_seconds
        self._local = threading.local()

    # ─── 配置与签名 ────────────────────────────────────
    def is_configured(self) -> bool:
        return bool(self.base_url and self._api_key and self._secret_key and self._passphrase)

    @property
    def key_suffix(self) -> str:
        """只回显 Key 后四位，前端展示用。"""
        return self._api_key[-4:] if len(self._api_key) >= 4 else ""

    def build_signature(self, path: str, params: Optional[dict] = None,
                        timestamp: Optional[str] = None) -> dict:
        """生成签名材料；timestamp 可注入固定值，便于单测与联调比对。"""
        url = self.base_url + path
        request_path = requests.Request("GET", url, params=params or None).prepare().path_url
        ts = timestamp or utc_timestamp_ms()
        prehash = f"{ts}GET{request_path}"
        digest = hmac.new(self._secret_key.encode(), prehash.encode(), hashlib.sha256).digest()
        return {
            "timestamp": ts,
            "request_path": request_path,
            "prehash": prehash,
            "sign": base64.b64encode(digest).decode(),
        }

    def _headers(self, signature: dict) -> dict:
        return {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature["sign"],
            "OK-ACCESS-TIMESTAMP": signature["timestamp"],
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }

    @property
    def _session(self) -> requests.Session:
        """私有客户端自己的线程内 Session，与公共行情客户端互不影响。"""
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.trust_env = False  # 代理由 build_proxy_attempts 显式提供
            self._local.session = session
        return session

    # ─── 请求 ──────────────────────────────────────────
    def get(self, path: str, params: Optional[dict] = None) -> dict:
        """签名 GET；仅接受白名单路径，返回已校验 code == "0" 的 payload。"""
        if path not in SIGNED_GET_WHITELIST:
            raise ValueError(f"私有 GET 路径不在白名单内：{path}")
        if not self.is_configured():
            raise OKXPrivateError("未配置只读 API Key", category="not_configured")

        signature = self.build_signature(path, params)
        headers = self._headers(signature)
        last_error: Optional[Exception] = None

        for index, proxies in enumerate(build_proxy_attempts()):
            started = time.monotonic()
            try:
                response = self._session.get(
                    self.base_url + path,
                    params=params or None,
                    headers=headers,
                    timeout=self.timeout_seconds,
                    proxies=proxies or None,
                    verify=CA_BUNDLE,
                )
            except requests.RequestException as exc:
                last_error = OKXPrivateError(
                    f"请求失败（{type(exc).__name__}）", category="network"
                )
                logger.warning("private GET %s attempt=%d network error: %s",
                               path, index + 1, type(exc).__name__)
                continue

            elapsed_ms = int((time.monotonic() - started) * 1000)

            if response.status_code == 401 or response.status_code == 403:
                raise OKXPrivateError(
                    f"鉴权失败（HTTP {response.status_code}）",
                    category="auth", http_status=response.status_code,
                )
            if response.status_code == 429:
                raise OKXPrivateError(
                    "请求过于频繁（HTTP 429）", category="rate_limit",
                    http_status=response.status_code,
                )
            if response.status_code >= 500:
                last_error = OKXPrivateError(
                    f"服务端错误（HTTP {response.status_code}）",
                    category="unavailable", http_status=response.status_code,
                )
                logger.warning("private GET %s attempt=%d http=%d in %dms",
                               path, index + 1, response.status_code, elapsed_ms)
                continue
            if response.status_code >= 400:
                raise OKXPrivateError(
                    f"请求被拒绝（HTTP {response.status_code}）",
                    category="business", http_status=response.status_code,
                )

            try:
                payload = response.json()
            except ValueError:
                raise OKXPrivateError("响应不是合法 JSON", category="business",
                                      http_status=response.status_code)

            if not isinstance(payload, dict):
                raise OKXPrivateError("响应结构异常", category="business",
                                      http_status=response.status_code)

            code = str(payload.get("code", ""))
            if code and code != "0":
                category = _classify_code(code)
                message = str(payload.get("msg") or "unknown")
                logger.warning("private GET %s code=%s category=%s in %dms",
                               path, code, category, elapsed_ms)
                raise OKXPrivateError(
                    f"OKX 业务错误 {code}: {message}",
                    code=code, category=category, http_status=response.status_code,
                )

            logger.info("private GET %s ok in %dms", path, elapsed_ms)
            return payload

        raise last_error or OKXPrivateError("所有代理尝试均失败", category="network")
