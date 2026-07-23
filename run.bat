@echo off
CHCP 65001 >nul
cls

echo ========================================
echo   OKEworkplace
echo ========================================
echo.

set "ROOT_DIR=%~dp0"
set "VENV_PYTHON=%ROOT_DIR%.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] 未找到虚拟环境 Python: %VENV_PYTHON%
    echo 请确保 .venv 环境存在
    pause
    exit /b 1
)

echo [INFO] 启动后端服务器...
echo [INFO] 关闭此窗口将自动停止后端
echo.

:: 切换到 backend 目录（确保 uvicorn 能找到 app/ 模块）
cd /d "%ROOT_DIR%backend"

:: 直接在前台运行 uvicorn（不后台运行），关闭窗口即自动停止
"%VENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

:: 如果 uvicorn 异常退出（如端口被占用），暂停以显示错误
echo.
echo [INFO] 后端已停止
pause
