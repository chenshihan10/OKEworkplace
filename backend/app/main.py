import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.scheduler import start_scheduler
from app.routes import coins, monitor, network, analysis
from app.shutdown import shutdown_event

# 兼容 PyInstaller 打包模式：打包后 frontend 在 _internal/frontend
_this_file = Path(__file__).resolve()
if getattr(sys, 'frozen', False):
    # 打包后 _internal/app/main.py → parents[1] = _internal
    FRONTEND_DIR = _this_file.parents[1] / "frontend"
else:
    # 开发模式 backend/app/main.py → parents[2] = project_root
    FRONTEND_DIR = _this_file.parents[2] / "frontend"

app = FastAPI(title="OKEworkplace API", version="0.2.0")

# ⚡ 彻底推开跨域大门：显式允许所有源、所有方法、所有头部
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(coins.router, prefix="/api/coins", tags=["coins"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["monitor"])
app.include_router(network.router, prefix="/network", tags=["network"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])


@app.on_event("startup")
def on_startup() -> None:
    start_scheduler()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "0.2.0"}


@app.get("/")
def root():
    return RedirectResponse("/index_v2.html")


@app.post("/api/shutdown")
def shutdown():
    """前端关闭窗口时调用，通知后端停止"""
    shutdown_event.set()
    return {"status": "shutting_down"}


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
