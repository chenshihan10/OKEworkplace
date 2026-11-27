from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import locale
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

import requests

try:
    import certifi
    # 显式指定 CA 证书来源，避免被系统里失效的 CURL_CA_BUNDLE / REQUESTS_CA_BUNDLE 污染
    CA_BUNDLE = certifi.where()
except Exception:
    CA_BUNDLE = True

from app.core.config import BASE_DIR, requests_proxies

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


def _parse_proxy_server(raw: str) -> dict:
    """解析注册表 ProxyServer，兼容 host:port、http://host:port、http=...;https=... 三种写法。"""
    raw = (raw or "").strip()
    if not raw:
        return {}

    def normalize(addr: str) -> str:
        addr = addr.strip()
        return addr if "://" in addr else f"http://{addr}"

    if "=" in raw:
        mapping = {}
        for part in raw.split(";"):
            if "=" not in part:
                continue
            kind, addr = part.split("=", 1)
            if addr.strip():
                mapping[kind.strip().lower()] = normalize(addr)
        http = mapping.get("http") or mapping.get("https")
        https = mapping.get("https") or mapping.get("http")
        result = {}
        if http:
            result["http"] = http
        if https:
            result["https"] = https
        return result

    proxy = normalize(raw)
    return {"http": proxy, "https": proxy}


def _read_windows_proxy_settings():
    """读取 Windows 系统代理设置（注册表），主流应用的标准做法"""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enable:
                proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                parsed = _parse_proxy_server(proxy_server)
                if parsed:
                    return parsed
    except Exception:
        pass
    return None


# 常见本地代理端口：优先验证这几个，再扫描其它本机监听端口
_PROXY_PROBE_PORTS = (12334, 7890, 10809, 2080)
_proxy_probe_cache = {"ts": 0.0, "proxies": ()}
_proxy_probe_lock = threading.Lock()
_manual_proxy_cache = {"ts": 0.0, "proxy": None}
_manual_proxy_lock = threading.Lock()

# 最近一次真正成功的出口（source 为空表示还没有成功记录）
_proxy_exit = {"source": "", "proxy": "", "ts": 0.0}
_proxy_exit_lock = threading.Lock()


def _listening_ports() -> set:
    """本机处于 LISTENING 状态的 loopback 端口，用于发现非默认端口的本地代理。"""
    ports = set()
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            timeout=5,
            startupinfo=si,
            creationflags=0x08000000,  # CREATE_NO_WINDOW：打包后不要闪黑框
        )
        # netstat 输出是系统本地编码（中文 Windows 为 GBK），按本地编码解码
        raw = proc.stdout or b""
        try:
            output = raw.decode(locale.getpreferredencoding(False) or "utf-8", "ignore")
        except Exception:
            output = raw.decode("ascii", "ignore")
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
                continue
            host, _, port = parts[1].rpartition(":")
            if host not in ("127.0.0.1", "0.0.0.0", "[::1]", "[::]"):
                continue
            try:
                value = int(port)
            except ValueError:
                continue
            if 1024 <= value <= 65535:
                ports.add(value)
    except Exception:
        pass
    return ports


def _verify_http_proxy(port: int, timeout: float = 0.8) -> bool:
    """用 CONNECT 握手指令验证端口确实是可用的 HTTP 代理。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"CONNECT www.okx.com:443 HTTP/1.1\r\nHost: www.okx.com:443\r\n\r\n")
            head = sock.recv(64)
            return head.startswith(b"HTTP/1.1 200") or head.startswith(b"HTTP/1.0 200")
    except Exception:
        return False


def _probe_local_proxy():
    """扫描本机监听端口，找出真正可用的 HTTP 代理。

    先验证常见端口，再并行验证其它监听端口（排除程序自身端口）。
    结果缓存：命中时 120 秒，未命中时 30 秒，便于用户中途启动代理。
    """
    now = time.monotonic()
    with _proxy_probe_lock:
        if now - _proxy_probe_cache["ts"] < (120 if _proxy_probe_cache["proxies"] else 30):
            return _proxy_probe_cache["proxies"]

        own_ports = set(range(8000, 8020))
        candidates = [p for p in _PROXY_PROBE_PORTS if p not in own_ports]
        candidates += sorted(_listening_ports() - set(candidates) - own_ports)

        found = []
        if candidates:
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(_verify_http_proxy, candidates))
            found = [
                {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
                for port, ok in zip(candidates, results)
                if ok
            ]

        _proxy_probe_cache["ts"] = now
        _proxy_probe_cache["proxies"] = tuple(found)
        return _proxy_probe_cache["proxies"]


def _manual_proxy_path() -> Path:
    """手动代理配置文件：打包版放在 exe 同级，开发模式放在 backend 目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "proxy.txt"
    return BASE_DIR / "proxy.txt"


def _read_manual_proxy():
    """读取 proxy.txt：每行一个代理，支持 host:port / http://host:port / 纯端口号。"""
    now = time.monotonic()
    with _manual_proxy_lock:
        if now - _manual_proxy_cache["ts"] < 30:
            return _manual_proxy_cache["proxy"]
        result = None
        try:
            path = _manual_proxy_path()
            if path.is_file():
                raw = path.read_bytes()
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    # 记事本另存为 ANSI(GBK) 时也能读
                    text = raw.decode("gbk", "ignore")
                for line in text.splitlines():
                    line = line.replace("\ufeff", "").strip()
                    if not line or line.startswith("#"):
                        continue
                    if "://" not in line:
                        line = line if ":" in line else f"127.0.0.1:{line}"
                        line = f"http://{line}"
                    result = {"http": line, "https": line}
                    break
        except Exception:
            result = None
        _manual_proxy_cache["ts"] = now
        _manual_proxy_cache["proxy"] = result
        return result


def record_proxy_exit(source: str, proxies: dict) -> None:
    """记录最近一次成功请求实际走的出口，供界面与启动日志展示。"""
    url = (proxies or {}).get("https") or (proxies or {}).get("http") or ""
    with _proxy_exit_lock:
        _proxy_exit.update(source=source, proxy=url, ts=time.time())


def last_proxy_exit() -> dict:
    with _proxy_exit_lock:
        return dict(_proxy_exit)


def detect_proxy_exit() -> tuple:
    """不做真实请求的静态判定：返回 (出口说明, 代理地址)；都没有则 ("直连", "")。"""
    for source, proxies in build_proxy_attempts_labeled():
        if proxies:
            return source, proxies.get("https") or proxies.get("http") or ""
    return "直连", ""


def build_proxy_attempts_labeled():
    """按优先级返回 [(出口说明, proxies), ...]。

    顺序：环境变量 → 程序目录 proxy.txt → Windows 系统代理 → 应用配置
    → 本地端口探测 → 直连。
    proxy.txt 是用户显式指定，必须排在自动探测之前，否则自动探测命中
    错误/残留代理时用户无法纠正。
    """
    attempts = []
    seen = set()

    def add(source: str, proxies: dict) -> None:
        key = frozenset(proxies.items())
        if key in seen:
            return
        seen.add(key)
        attempts.append((source, proxies))

    env_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    env_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if env_http:
        add("环境变量", {"http": env_http, "https": env_https or env_http})

    manual = _read_manual_proxy()
    if manual:
        add("手动配置", manual)

    registry_proxy = _read_windows_proxy_settings()
    if registry_proxy:
        add("系统代理", registry_proxy)

    configured = requests_proxies()
    if configured:
        add("应用配置", configured)

    for probed in _probe_local_proxy():
        add("本地端口探测", probed)

    attempts.append(("直连", {}))
    return attempts


def build_proxy_attempts():
    """兼容旧调用方：只返回 proxies 列表。"""
    return [proxies for _, proxies in build_proxy_attempts_labeled()]


@dataclass
class OKEClient:
    base_url: str
    api_key: str
    secret_key: str = ""
    timeout_seconds: int = 8

    def _request(self, path: str, params: dict) -> dict:
        url = self.base_url.rstrip("/") + path

        last_error = None
        for source, proxies in build_proxy_attempts_labeled():
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
                record_proxy_exit(source, proxies)
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
            session.trust_env = False  # 代理已由 build_proxy_attempts 显式提供
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
        for proxies in build_proxy_attempts():
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
        for proxies in build_proxy_attempts():
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
