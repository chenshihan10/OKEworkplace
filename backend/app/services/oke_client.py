from dataclasses import dataclass
from datetime import datetime, timezone
import os
import threading
from typing import Optional

import requests

try:
    import certifi
    # 显式指定 CA 证书来源，避免被系统里失效的 CURL_CA_BUNDLE / REQUESTS_CA_BUNDLE 污染
    CA_BUNDLE = certifi.where()
except Exception:
    CA_BUNDLE = True

from app.core.config import requests_proxies

# OKX K 线周期是大小写敏感的（15m / 1H / 4H / 1D），
# 用户配置或旧数据里常见的 1h/4h/1d 需要先规范化，否则接口直接报错。
_BAR_ALIASES = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W", "1mon": "1M",
}


def normalize_bar(timeframe: str) -> str:
    """把 1h/4h/1d 之类的写法映射成 OKX 接受的 bar 值。"""
    raw = (timeframe or "").strip()
    return _BAR_ALIASES.get(raw.lower(), raw)

# 每个工作线程复用一个 Session，复用 TCP/TLS 连接，避免每次请求重新握手
_thread_local = threading.local()


def _read_windows_proxy_settings():
    """读取 Windows 系统代理设置（注册表），主流应用的标准做法"""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enable:
                proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                if proxy_server:
                    # 处理带协议前缀的情况
                    if "://" not in proxy_server:
                        proxy_server = f"http://{proxy_server}"
                    return {
                        "http": proxy_server if "://" in proxy_server else f"http://{proxy_server}",
                        "https": proxy_server if "://" in proxy_server else f"http://{proxy_server}",
                    }
    except Exception:
        pass
    return None


def _build_proxy_attempts():
    """
    主流策略：系统代理（环境变量）→ Windows 注册表代理 → 用户配置代理 → 直连
    这是国内主流客户端（微信、飞书、各浏览器）的通用做法
    """
    attempts = []
    seen = set()

    # 1. 系统代理（环境变量）- 最优先，用户在系统设置中配置
    env_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    env_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if env_http:
        proxy_cfg = frozenset({"http": env_http, "https": env_https or env_http}.items())
        if proxy_cfg not in seen:
            seen.add(proxy_cfg)
            attempts.append({"http": env_http, "https": env_https or env_http})

    # 2. 注册表读取系统代理（Windows 专属）
    registry_proxy = _read_windows_proxy_settings()
    if registry_proxy:
        proxy_cfg = frozenset(registry_proxy.items())
        if proxy_cfg not in seen:
            seen.add(proxy_cfg)
            attempts.append(registry_proxy)

    # 3. 用户手动配置的代理（.env 文件中的应用内设置）
    configured = requests_proxies()
    if configured:
        proxy_cfg = frozenset(configured.items())
        if proxy_cfg not in seen:
            seen.add(proxy_cfg)
            attempts.append(configured)

    # 4. 直连（最终兜底）
    attempts.append({})

    return attempts


@dataclass
class OKEClient:
    base_url: str
    api_key: str
    secret_key: str = ""
    timeout_seconds: int = 8

    def _request(self, path: str, params: dict) -> dict:
        url = self.base_url.rstrip("/") + path
        attempts = _build_proxy_attempts()

        last_error = None
        for proxies in attempts:
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    proxies=proxies or None,
                    verify=CA_BUNDLE,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("code") not in (None, "0"):
                    raise RuntimeError("OKE API error: %s" % payload.get("msg", "unknown"))
                return payload
            except Exception as exc:
                last_error = exc
        raise last_error

    @property
    def _session(self) -> requests.Session:
        """线程内复用的 Session：保留连接，减少代理场景下的 TLS 握手开销。"""
        session = getattr(_thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.trust_env = False  # 代理已由 _build_proxy_attempts 显式提供
            _thread_local.session = session
        return session

    def fetch_all_tickers(self):
        """获取 OKX 所有可交易的 USDT 永续合约"""
        try:
            payload = self._request("/api/v5/market/tickers", {"instType": "SWAP"})
            coins = []
            for row in payload.get("data", []):
                inst_id = row.get("instId", "")
                if inst_id.endswith("-USDT-SWAP"):
                    symbol = inst_id.replace("-SWAP", "")
                    coins.append({
                        "symbol": symbol,
                        "instId": inst_id,
                        "last": float(row.get("last", 0) or 0),
                        "vol24h": float(row.get("vol24h", 0) or 0),
                    })
            # 按成交量降序排列
            coins.sort(key=lambda x: x["vol24h"], reverse=True)
            return coins
        except Exception:
            # 返回常用币种列表作为 fallback
            return [
                {"symbol": "BTC-USDT", "instId": "BTC-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "ETH-USDT", "instId": "ETH-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "SOL-USDT", "instId": "SOL-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "DOGE-USDT", "instId": "DOGE-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "XRP-USDT", "instId": "XRP-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "ADA-USDT", "instId": "ADA-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "AVAX-USDT", "instId": "AVAX-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "LINK-USDT", "instId": "LINK-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "MATIC-USDT", "instId": "MATIC-USDT-SWAP", "last": 0, "vol24h": 0},
                {"symbol": "DOT-USDT", "instId": "DOT-USDT-SWAP", "last": 0, "vol24h": 0},
            ]

    def fetch_ticker(self, symbol: str) -> dict:
        inst_id = self._symbol_to_inst_id(symbol)
        payload = self._request("/api/v5/market/ticker", {"instId": inst_id})
        row = payload["data"][0]
        return {
            "symbol": symbol,
            "instId": inst_id,
            "price": float(row["last"]),
            "bid_px": float(row.get("bidPx", 0) or 0),
            "ask_px": float(row.get("askPx", 0) or 0),
            "volume_24h": float(row.get("vol24h", 0) or 0),
            "change_24h": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "okx",
        }

    def fetch_candles(self, symbol: str, timeframe: str, limit: Optional[int] = None):
        inst_id = self._symbol_to_inst_id(symbol)
        params = {"instId": inst_id, "bar": normalize_bar(timeframe)}
        if limit:
            params["limit"] = str(max(1, min(int(limit), 300)))
        payload = self._request("/api/v5/market/candles", params)
        candles = []
        for row in payload.get("data", []):
            candles.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ts": row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "okx",
                }
            )
        return list(reversed(candles))

    def fetch_candles_range(self, symbol: str, timeframe: str, start_ms: int, end_ms: int,
                            max_pages: int = 12):
        """按时间窗回补历史 K 线（用于停机期间到期的回验），返回升序列表。

        `/market/candles` 只返回最近 100 根，停机超过该窗口就取不到到期区间；
        这里用 `/market/history-candles` 以 after 向前翻页，最多 max_pages 页。
        """
        inst_id = self._symbol_to_inst_id(symbol)
        collected = {}
        upper = int(end_ms) + 1
        for _ in range(max_pages):
            payload = self._request(
                "/api/v5/market/history-candles",
                {"instId": inst_id, "bar": timeframe, "after": str(upper), "limit": "100"},
            )
            data = payload.get("data") or []
            if not data:
                break
            page_oldest = None
            for row in data:
                try:
                    ts = int(row[0])
                except (TypeError, ValueError):
                    continue
                if ts > end_ms:
                    continue
                collected[ts] = row
                page_oldest = ts if page_oldest is None else min(page_oldest, ts)
            if page_oldest is None or page_oldest <= start_ms or len(data) < 100:
                break
            upper = page_oldest

        candles = []
        for ts in sorted(collected):
            row = collected[ts]
            candles.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "ts": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "okx",
            })
        return candles

    def fetch_open_interest(self, symbol: str) -> dict:
        inst_id = self._symbol_to_inst_id(symbol)
        payload = self._request("/api/v5/public/open-interest", {"instId": inst_id})
        row = payload["data"][0]
        oi = float(row.get("oi", 0) or 0)
        return {
            "symbol": symbol,
            "instId": inst_id,
            "open_interest": oi,
            "change_pct": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "okx",
        }

    def fetch_funding_rate(self, symbol: str) -> dict:
        inst_id = self._symbol_to_inst_id(symbol)
        payload = self._request("/api/v5/public/funding-rate", {"instId": inst_id})
        row = payload["data"][0]
        rate = float(row.get("fundingRate", 0) or 0)
        return {
            "symbol": symbol,
            "instId": inst_id,
            "funding_rate": rate,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "okx",
        }

    def fetch_trades(self, symbol: str, limit: Optional[int] = None):
        inst_id = self._symbol_to_inst_id(symbol)
        try:
            params = {"instId": inst_id}
            if limit:
                params["limit"] = str(max(1, min(int(limit), 500)))
            payload = self._request("/api/v5/market/trades", params)
            trades = []
            for row in payload.get("data", []):
                trades.append(
                    {
                        "symbol": symbol,
                        "instId": inst_id,
                        "tradeId": row.get("tradeId"),
                        "price": float(row.get("px", 0) or 0),
                        "size": float(row.get("sz", 0) or 0),
                        "side": row.get("side"),
                        "timestamp": row.get("ts") or datetime.now(timezone.utc).isoformat(),
                        "source": "okx",
                    }
                )
            return trades
        except Exception:
            return []

    def fetch_books(self, symbol: str, sz: int = 20):
        inst_id = self._symbol_to_inst_id(symbol)
        try:
            payload = self._request("/api/v5/market/books", {"instId": inst_id, "sz": sz})
            row = payload["data"][0]
            return {
                "symbol": symbol,
                "instId": inst_id,
                "asks": row.get("asks", []),
                "bids": row.get("bids", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "okx",
            }
        except Exception:
            return {"symbol": symbol, "instId": inst_id, "asks": [], "bids": [], "timestamp": datetime.now(timezone.utc).isoformat(), "source": "unavailable"}

    def fetch_mark_price(self, symbol: str) -> dict:
        """获取标记价格 (mark price)"""
        inst_id = self._symbol_to_inst_id(symbol)
        url = self.base_url.rstrip("/") + "/api/v5/public/mark-price"
        for proxies in _build_proxy_attempts():
            try:
                resp = self._session.get(
                    url,
                    params={"instId": inst_id},
                    proxies=proxies or None,
                    timeout=5,
                    verify=CA_BUNDLE,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "0" and data.get("data"):
                        item = data["data"][0]
                        mark_px = float(item.get("markPx", 0) or 0)
                        ts = item.get("ts", "")
                        return {"mark_price": mark_px, "timestamp": ts}
            except Exception:
                continue
        return {"mark_price": 0, "timestamp": ""}

    def fetch_index_price(self, symbol: str) -> dict:
        """获取指数价格 (index price)"""
        # 指数接口使用现货指数 instId（如 BTC-USDT），不带 -SWAP
        inst_id = symbol.replace("-SWAP", "")
        url = self.base_url.rstrip("/") + "/api/v5/market/index-tickers"
        for proxies in _build_proxy_attempts():
            try:
                resp = self._session.get(
                    url,
                    params={"instId": inst_id},
                    proxies=proxies or None,
                    timeout=5,
                    verify=CA_BUNDLE,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "0" and data.get("data"):
                        item = data["data"][0]
                        idx_px = float(item.get("idxPx", 0) or 0)
                        ts = item.get("ts", "")
                        return {"index_price": idx_px, "timestamp": ts}
            except Exception:
                continue
        return {"index_price": 0, "timestamp": ""}

    def _symbol_to_inst_id(self, symbol: str) -> str:
        return symbol.replace("-", "-") + "-SWAP" if not symbol.endswith("-SWAP") else symbol
