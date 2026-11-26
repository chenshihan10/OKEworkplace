"""V2.6 实盘只读接口：只读服务层缓存与本地库，不触发任何外部请求。

与公共 GET 的差异（C1）：这些接口会暴露账户余额与持仓，即使是 GET 也要求本机 token。
token 来自桌面壳注入的 `?token=`（前端转成 `x-oke-token` 头）；直接 uvicorn 调试且未配置
`OKE_LOCAL_TOKEN` 时跳过，与 main.py 的中间件口径一致。
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.services.account_service import get_account_service


def require_local_token(request: Request) -> None:
    expected = os.getenv("OKE_LOCAL_TOKEN", "")
    if not expected:
        return
    token = request.headers.get("x-oke-token") or request.query_params.get("token")
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid local token")


router = APIRouter(
    prefix="/api/v3/account",
    tags=["account"],
    dependencies=[Depends(require_local_token)],
)


@router.get("/status")
def account_status() -> dict:
    return get_account_service().status()


@router.get("/summary")
def account_summary() -> dict:
    return get_account_service().summary_view()


@router.get("/positions")
def account_positions() -> dict:
    return get_account_service().positions_view()


@router.get("/margin")
def account_margin() -> dict:
    return get_account_service().margin_view()


@router.get("/fills")
def account_fills(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    inst_id: str = Query("", max_length=40),
) -> dict:
    return get_account_service().fills_view(
        limit=limit, offset=offset, inst_id=inst_id or None
    )


@router.get("/config")
def account_config() -> dict:
    return get_account_service().config_view()


@router.get("/risk")
def account_risk() -> dict:
    """账户级真实风险（敞口/集中度/强平距离），只展示不处置。"""
    return get_account_service().risk_view()


@router.get("/reconciliation")
def account_reconciliation() -> dict:
    """本地手工订单与实盘持仓对账，只读并列展示。"""
    return get_account_service().reconciliation_view()
