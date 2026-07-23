@echo off
CHCP 65001 >nul
cls
echo ========================================
echo   OKEworkplace - 停止后端
echo ========================================
echo.

echo [INFO] 查找占用端口 8000 的进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] 正在终止进程 PID=%%a ...
    taskkill /F /PID %%a >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] PID %%a 已终止
    ) else (
        echo [FAIL] 无法终止 PID %%a（可能权限不足）
    )
)

echo.
echo [INFO] 检查端口 8000 是否已释放...
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul
if %errorlevel% equ 0 (
    echo [WARN] 端口 8000 仍被占用，请手动关闭相关程序
) else (
    echo [OK] 端口 8000 已释放
)

echo.
pause
