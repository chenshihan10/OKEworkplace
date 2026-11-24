import os
import signal
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import APP_VERSION
from app.core.scheduler import start_scheduler, stop_scheduler
from app.routes import (
    coins, monitor, network, analysis, orders, predictions, risk, mtf, orderflow,
)
from app.shutdown import shutdown_event

# 兼容 PyInstaller 打包模式：打包后 frontend 在 _internal/frontend
_this_file = Path(__file__).resolve()
if getattr(sys, 'frozen', False):
    # 打包后 _internal/app/main.py → parents[1] = _internal
    FRONTEND_DIR = _this_file.parents[1] / "frontend"
else:
    # 开发模式 backend/app/main.py → parents[2] = project_root
    FRONTEND_DIR = _this_file.parents[2] / "frontend"

# 正式部署（Web）时通过环境变量关闭进程自杀接口，避免服务被任意访问者关停
IS_DESKTOP = os.getenv("OKE_DESKTOP", "0") == "1"
ENABLE_SHUTDOWN = os.getenv(
    "OKE_ENABLE_SHUTDOWN", "true" if IS_DESKTOP else "false"
).lower() == "true"
LOCAL_TOKEN = os.getenv("OKE_LOCAL_TOKEN", "")
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}

app = FastAPI(title="OKEworkplace API", version=APP_VERSION)

# 只允许本机来源：防止任意网站跨域读取/操纵本地接口
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def local_api_guard(request: Request, call_next):
    """本地接口最小加固：Host/Origin 白名单 + 写操作 token。"""
    host = request.headers.get("host", "")
    hostname = host.rsplit(":", 1)[0].strip("[]") if host else ""
    if hostname and hostname not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "forbidden host"}, status_code=403)

    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.hostname not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "forbidden origin"}, status_code=403)

    # token 由桌面壳生成并通过页面 URL 注入；未配置时（例如直接 uvicorn 调试）跳过
    if LOCAL_TOKEN and request.method not in ("GET", "HEAD", "OPTIONS"):
        token = request.headers.get("x-oke-token") or request.query_params.get("token")
        if token != LOCAL_TOKEN:
            return JSONResponse({"detail": "invalid local token"}, status_code=403)

    return await call_next(request)


app.include_router(coins.router, prefix="/api/coins", tags=["coins"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["monitor"])
app.include_router(network.router, prefix="/network", tags=["network"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(orders.router, prefix="", tags=["orders"])
app.include_router(risk.router, prefix="", tags=["risk"])
app.include_router(mtf.router, prefix="", tags=["mtf"])
app.include_router(orderflow.router, prefix="", tags=["orderflow"])
app.include_router(predictions.router, prefix="/api", tags=["predictions"])


@app.on_event("startup")
def on_startup() -> None:
    start_scheduler()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/")
def root():
    return RedirectResponse("/index.html")


# 开发模式专用：前端热刷新版本号（打包后不注册该路由，正式版零开销）
if not getattr(sys, "frozen", False):
    @app.get("/dev/frontend-version")
    def dev_frontend_version() -> dict:
        """返回 frontend/ 下所有文件的最新修改时间，前端定时比对后自动 reload。"""
        latest = 0.0
        for item in FRONTEND_DIR.rglob("*"):
            try:
                if item.is_file():
                    latest = max(latest, item.stat().st_mtime)
            except OSError:
                continue
        return {"dev": True, "version": latest}


@app.post("/api/shutdown")
def shutdown():
    """前端关闭窗口时调用，通知后端停止"""
    if not ENABLE_SHUTDOWN:
        raise HTTPException(status_code=403, detail="shutdown endpoint disabled")
    shutdown_event.set()
    stop_scheduler()
    # 延迟 0.5 秒后通过 SIGINT 触发 uvicorn 优雅关闭
    # 确保当前 HTTP 响应先成功返回给客户端
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    return {"status": "shutting_down"}


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False, log_config=None, access_log=False)
