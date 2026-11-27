"""V3.0 Prediction Logger 查询接口"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from app.core.config import settings
from app.services.backup_service import backup_service
from app.services.db_store import SignalDB
from app.services.future_validator import future_validator
from app.services.maintenance_service import maintenance_service
from app.services.prediction_context import prediction_context_service

router = APIRouter()


@router.get("/predictions", summary="方向预测记录")
def list_predictions(symbol: Optional[str] = None,
                     start: Optional[str] = None,
                     end: Optional[str] = None,
                     limit: int = 50,
                     offset: int = 0):
    """按币种 / 时间范围查询预测记录（ISO 时间字符串，如 2026-11-20T05:00:00）"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    db = SignalDB()
    items, total = db.query_predictions(symbol=symbol, start=start, end=end,
                                        limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/v3/predictions/results", summary="预测回验结果")
def list_prediction_results(symbol: Optional[str] = None,
                            horizon: Optional[str] = None,
                            status: Optional[str] = None,
                            start: Optional[str] = None,
                            end: Optional[str] = None,
                            limit: int = 50,
                            offset: int = 0):
    """查询 Future Validator 的回验结果（status: verified/insufficient_data/invalid/failed）"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    items, total = SignalDB().query_prediction_results(
        symbol=symbol, horizon=horizon, status=status,
        start=start, end=end, limit=limit, offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/v3/verify/status", summary="回验任务最近一次执行情况")
def verify_status():
    return {
        "last_run": future_validator.last_run,
        "horizons": ["30m", "1h", "4h"],
        "interval_seconds": settings.verify_interval_seconds,
    }


@router.get("/v3/maintenance/signals", summary="signals 保留策略与最近清理结果")
def signals_maintenance():
    return maintenance_service.stats()


@router.get("/v3/maintenance/backup", summary="自动备份状态与最近备份结果")
def backup_status():
    return backup_service.status()


@router.get("/v3/performance/summary", summary="预测绩效汇总")
def performance_summary(symbol: Optional[str] = None,
                        start: Optional[str] = None,
                        end: Optional[str] = None):
    return SignalDB().performance_summary(symbol=symbol, start=start, end=end)


@router.get("/v3/performance/detail", summary="预测绩效明细")
def performance_detail(symbol: Optional[str] = None,
                       horizon: Optional[str] = None,
                       status: Optional[str] = None,
                       start: Optional[str] = None,
                       end: Optional[str] = None,
                       limit: int = 50,
                       offset: int = 0):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    items, total = SignalDB().performance_detail(
        symbol=symbol, horizon=horizon, status=status,
        start=start, end=end, limit=limit, offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/v3/performance/quality", summary="绩效质量：置信区间/成本门槛/品种分类/影子与监控")
def performance_quality_view():
    from app.services.performance_quality import performance_quality_overview
    return performance_quality_overview()


@router.get("/v3/performance/context-summary", summary="按多周期/订单流上下文分桶的绩效")
def performance_context_summary(symbol: Optional[str] = None,
                                start: Optional[str] = None,
                                end: Optional[str] = None,
                                min_sample: int = 30):
    """只读聚合；样本不足的桶返回 insufficient_sample=true 且不给胜率结论。"""
    min_sample = max(1, min(min_sample, 1000))
    return prediction_context_service.summary(
        symbol=symbol, start=start, end=end, min_sample=min_sample
    )
