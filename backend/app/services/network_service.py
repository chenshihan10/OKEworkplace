import requests

from app.core.config import requests_proxies, settings


def proxy_url() -> str:
    proxies = requests_proxies()
    return proxies.get("https") or proxies.get("http") or ""


def okx_reachable() -> bool:
    configured = requests_proxies()
    attempts = [configured] if configured else [{}]
    if configured:
        attempts.append({})

    for proxies in attempts:
        try:
            response = requests.get(
                settings.oke_base_url.rstrip("/") + "/api/v5/market/ticker",
                params={"instId": "ETH-USDT-SWAP"},
                timeout=8,
                proxies=proxies or None,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") == "0" and bool(payload.get("data")):
                return True
        except Exception:
            continue
    return False


def network_status() -> dict:
    proxy = proxy_url()
    reachable = okx_reachable()
    return {
        "proxy_enabled": bool(proxy),
        "proxy": proxy,
        "okx_reachable": reachable,
        "data_source": "REAL" if reachable else "FALLBACK",
    }
