import atexit
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.services.backup_service import backup_service
from app.services.future_validator import future_validator
from app.services.maintenance_service import maintenance_service
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
        max_instances=3,
        misfire_grace_time=20,
    )
    # signals 保留策略：分批删除超期数据，避免一次性长事务锁库
    scheduler.add_job(
        maintenance_service.prune_signals,
        "interval",
        minutes=settings.signal_cleanup_interval_minutes,
        id="prune_signals",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    # Future Validator：每 60 秒扫描到期预测；首跑提前到启动后 30 秒（等价启动补算）
    scheduler.add_job(
        future_validator.verify_due,
        "interval",
        seconds=settings.verify_interval_seconds,
        id="verify_predictions",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    # 自动备份：每 5 分钟检查一次；运行满 5 分钟首跑，之后按累计运行时长触发，数据无变化则跳过
    scheduler.add_job(
        backup_service.maybe_backup,
        "interval",
        minutes=5,
        id="auto_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
