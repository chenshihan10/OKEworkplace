"""网络状态：以行情数据新鲜度为准，不做实时主动探测。

历史问题：早先每次 /network/status 都会实时请求 OKX，代理长尾（单次 >2s）
会让状态在 REAL/FALLBACK 之间来回跳，前端每次恢复后重新触发提示条。
现在改为读取“最近一次成功取数时间”：
- 数据年龄 <= data_grace_seconds：仍视为可用（单次失败/抖动完全静默）
- 超过 grace：判定为不可用
状态只由真实数据是否在更新决定，不受单次探测结果影响。
"""
from datetime import datetime, timezone

from app.core.config import requests_proxies, settings


def proxy_url() -> str:
    proxies = requests_proxies()
    return proxies.get("https") or proxies.get("http") or ""


def network_status() -> dict:
    from app.services.market_service import market_service

    proxy = proxy_url()
    last = market_service.last_success_at()
    now = datetime.now(timezone.utc)
    age = None if last is None else max(0, int((now - last).total_seconds()))
    fresh = age is not None and age <= settings.data_grace_seconds

    return {
        "proxy_enabled": bool(proxy),
        "proxy": proxy,
        "okx_reachable": fresh,
        "data_source": "REAL" if fresh else "FALLBACK",
        "last_success_at": last.isoformat() if last else None,
        "data_age_seconds": age,
        "grace_seconds": settings.data_grace_seconds,
        "stale_seconds": settings.data_stale_seconds,
        "boot_check_seconds": settings.data_boot_check_seconds,
    }
