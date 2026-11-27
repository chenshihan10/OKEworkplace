"""网络状态：以行情数据新鲜度为准，不做实时主动探测。

历史问题：早先每次 /network/status 都会实时请求 OKX，代理长尾（单次 >2s）
会让状态在 REAL/FALLBACK 之间来回跳，前端每次恢复后重新触发提示条。
现在改为读取“最近一次成功取数时间”：
- 数据年龄 <= data_grace_seconds：仍视为可用（单次失败/抖动完全静默）
- 超过 grace：判定为不可用
状态只由真实数据是否在更新决定，不受单次探测结果影响。
"""
from datetime import datetime, timezone
import time

from app.core.config import settings

# 后端进程启动基准：模块在应用导入期加载，与进程启动基本同一时刻
_STARTED_AT = time.time()


def proxy_exit() -> tuple:
    """当前实际使用的出口：(说明, 代理地址)。

    优先用最近一次成功请求真正走过的出口；还没有成功记录时，
    退回到静态探测（环境变量 → 系统代理 → 本地端口探测），
    这样代理没开时界面也能明确提示「未检测到代理」。
    """
    from app.services.oke_client import detect_proxy_exit, last_proxy_exit

    last = last_proxy_exit()
    if last.get("source"):
        return last["source"], last.get("proxy", "")
    return detect_proxy_exit()


def network_status() -> dict:
    from app.services.market_service import market_service

    proxy_source, proxy = proxy_exit()
    last = market_service.last_success_at()
    now = datetime.now(timezone.utc)
    age = None if last is None else max(0, int((now - last).total_seconds()))
    fresh = age is not None and age <= settings.data_grace_seconds

    return {
        "proxy_enabled": bool(proxy),
        "proxy": proxy,
        "proxy_source": proxy_source,
        "okx_reachable": fresh,
        "data_source": "REAL" if fresh else "FALLBACK",
        "last_success_at": last.isoformat() if last else None,
        "data_age_seconds": age,
        "grace_seconds": settings.data_grace_seconds,
        "stale_seconds": settings.data_stale_seconds,
        "boot_check_seconds": settings.data_boot_check_seconds,
        "started_at": datetime.fromtimestamp(_STARTED_AT, tz=timezone.utc).isoformat(),
        "uptime_seconds": max(0, int(time.time() - _STARTED_AT)),
    }
