import atexit

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.services.market_service import market_service


scheduler = BackgroundScheduler()


def stop_scheduler() -> None:
    """安全停止调度器，避免关闭时出现 'cannot schedule new futures after shutdown'"""
    if scheduler.running:
        scheduler.shutdown(wait=False)


# 注册 atexit 在解释器清理前先停止调度器
atexit.register(stop_scheduler)


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        market_service.refresh_all,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="refresh_all_markets",
        replace_existing=True,
        max_instances=2,
        misfire_grace_time=10,
    )
    scheduler.start()
