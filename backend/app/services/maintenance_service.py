"""V3.0 数据维护：signals / 订单流采样保留策略（分批删除，记录最近一次执行结果）"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.services.db_store import SignalDB


class MaintenanceService:
    def __init__(self) -> None:
        self._db = SignalDB()
        self.last_cleanup = {
            "at": None,
            "deleted": 0,
            "deleted_snapshots": 0,
            "deleted_orderflow": 0,
            "batches": 0,
            "cutoff": None,
            "error": None,
        }

    def prune_signals(self) -> dict:
        try:
            result = self._db.prune_signals(
                days=settings.signal_retention_days,
                batch_size=settings.signal_cleanup_batch_size,
            )
            # N5 遗留项：订单流采样随同一维护任务清理，避免长期运行膨胀
            orderflow = self._db.prune_order_flow(
                days=settings.orderflow_retention_days,
                batch_size=settings.signal_cleanup_batch_size,
            )
            self.last_cleanup = {
                **result,
                "deleted_orderflow": orderflow["deleted_orderflow"],
                "orderflow_cutoff": orderflow["cutoff"],
                "batches": result["batches"] + orderflow["batches"],
                "at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
        except Exception as exc:  # 清理失败不能影响行情主循环
            logging.getLogger(__name__).warning("prune_signals failed: %s", exc)
            self.last_cleanup = {
                "at": datetime.now(timezone.utc).isoformat(),
                "deleted": 0,
                "deleted_snapshots": 0,
                "deleted_orderflow": 0,
                "batches": 0,
                "cutoff": None,
                "error": str(exc),
            }
        return self.last_cleanup

    def stats(self) -> dict:
        return {
            "retention_days": settings.signal_retention_days,
            "orderflow_retention_days": settings.orderflow_retention_days,
            "batch_size": settings.signal_cleanup_batch_size,
            "interval_minutes": settings.signal_cleanup_interval_minutes,
            "last_cleanup": self.last_cleanup,
            **self._db.signal_stats(),
        }


maintenance_service = MaintenanceService()
