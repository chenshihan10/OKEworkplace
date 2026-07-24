from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
import random

import requests

from app.core.config import requests_proxies


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
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    proxies=proxies or None,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("code") not in (None, "0"):
                    raise RuntimeError("OKE API error: %s" % payload.get("msg", "unknown"))
                return payload
            except Exception as exc:
                last_error = exc
        raise last_error

    def _fallback_seed(self, symbol: str, timeframe: str = "") -> int:
        return abs(hash((symbol, timeframe))) % (2**32)

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
        try:
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
        except Exception:
            rng = random.Random(self._fallback_seed(symbol))
            if symbol.startswith("BTC"):
                price = 60000 + math.sin(rng.random() * 10) * 1200 + rng.uniform(-250, 250)
                change = rng.uniform(-2.8, 2.8)
            elif symbol.startswith("ETH"):
                price = 1780 + math.sin(rng.random() * 10) * 80 + rng.uniform(-25, 25)
                change = rng.uniform(-4.0, 4.0)
            else:
                price = rng.uniform(1, 100)
                change = rng.uniform(-3, 3)
            return {
                "symbol": symbol,
                "instId": inst_id,
                "price": round(max(price, 0.01), 2),
                "bid_px": None,
                "ask_px": None,
                "volume_24h": None,
                "change_24h": round(change, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "fallback",
            }

    def fetch_candles(self, symbol: str, timeframe: str):
        inst_id = self._symbol_to_inst_id(symbol)
        try:
            payload = self._request("/api/v5/market/candles", {"instId": inst_id, "bar": timeframe})
            candles = []
            rows = payload.get("data", [])
            for row in rows:
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
        except Exception:
            now = datetime.now(timezone.utc).isoformat()
            rng = random.Random(self._fallback_seed(symbol, timeframe))
            base = 60000 if symbol.startswith("BTC") else 1780 if symbol.startswith("ETH") else 100
            candles = []
            close = base
            for idx in range(60):
                drift = rng.uniform(-1, 1) * (20 if symbol.startswith("BTC") else 2)
                open_ = close
                close = max(0.01, open_ + drift)
                high = max(open_, close) + abs(rng.uniform(0, 1)) * (12 if symbol.startswith("BTC") else 1.5)
                low = min(open_, close) - abs(rng.uniform(0, 1)) * (12 if symbol.startswith("BTC") else 1.5)
                volume = abs(rng.gauss(60000 if symbol.startswith("ETH") else 100000, 25000))
                candles.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "open": round(open_, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": round(volume, 2),
                        "timestamp": now,
                        "index": idx,
                        "source": "fallback",
                    }
                )
            return candles

    def fetch_open_interest(self, symbol: str) -> dict:
        inst_id = self._symbol_to_inst_id(symbol)
        try:
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
        except Exception:
            rng = random.Random(self._fallback_seed(symbol, "oi"))
            return {
                "symbol": symbol,
                "instId": inst_id,
                "open_interest": round(abs(rng.gauss(120000, 30000)), 2),
                "change_pct": round(rng.uniform(-8, 8), 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "fallback",
            }

    def fetch_funding_rate(self, symbol: str) -> dict:
        inst_id = self._symbol_to_inst_id(symbol)
        try:
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
        except Exception:
            rng = random.Random(self._fallback_seed(symbol, "funding"))
            return {
                "symbol": symbol,
                "instId": inst_id,
                "funding_rate": round(rng.uniform(-0.12, 0.12), 4),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "fallback",
            }

    def fetch_trades(self, symbol: str):
        inst_id = self._symbol_to_inst_id(symbol)
        try:
            payload = self._request("/api/v5/market/trades", {"instId": inst_id})
            trades = []
            for row in payload.get("data", []):
                trades.append(
                    {
                        "symbol": symbol,
                        "instId": inst_id,
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

    def fetch_books(self, symbol: str):
        inst_id = self._symbol_to_inst_id(symbol)
        try:
            payload = self._request("/api/v5/market/books", {"instId": inst_id, "sz": 20})
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
            return {"symbol": symbol, "instId": inst_id, "asks": [], "bids": [], "timestamp": datetime.now(timezone.utc).isoformat(), "source": "fallback"}

    def fetch_mark_price(self, symbol: str) -> dict:
        """获取标记价格 (mark price)"""
        url = f"{self.base_url}/api/v5/public/mark-price?instId={symbol}"
        for proxies in _build_proxy_attempts():
            try:
                resp = requests.get(url, proxies=proxies, timeout=5)
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
        url = f"{self.base_url}/api/v5/public/index-price?instId={symbol}"
        for proxies in _build_proxy_attempts():
            try:
                resp = requests.get(url, proxies=proxies, timeout=5)
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
