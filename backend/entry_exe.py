"""PyInstaller EXE entry point - starts server and opens GUI window"""
import sys
import os
import io
import threading
import time
import urllib.request
import json
import signal
import socket
import ctypes
import traceback
from pathlib import Path

# ══════════════════════════════════════════════════════
# PyInstaller --windowed 模式下 sys.stdout/stderr 为 None，
# 导致 uvicorn 在 log config 中调用 .isatty() 时报错。
# 需要在导入 uvicorn 之前替换为有效的流，使用 UTF-8 编码
# 避免 Windows GBK 环境下 emoji 等字符导致 UnicodeEncodeError
# ══════════════════════════════════════════════════════
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
elif hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')
elif hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add backend dir to path for imports
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# 错误日志文件（用于诊断无法启动的问题）
_LOG_DIR = _backend_dir if not getattr(sys, 'frozen', False) else Path.cwd()
_STARTUP_LOG = _LOG_DIR / "startup_error.log"

HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"


def find_available_port(start_port=8000, max_attempts=20):
    """
    自动端口递增策略 - 主流应用的标准做法
    参考：VS Code、JetBrains 系列、各种 IDE 都使用此策略
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    raise RuntimeError(f"无法找到可用端口（{start_port}~{start_port + max_attempts - 1} 均被占用）")


def _wait_for_server(port, timeout=30):
    """等待后端服务器就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            url = f"http://{HOST}:{port}/health"
            resp = urllib.request.urlopen(url, timeout=2)
            if json.loads(resp.read()).get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _start_server(port):
    """在后台线程中启动 uvicorn（静默模式）"""
    try:
        import uvicorn
        from app.main import app
        uvicorn.run(
            app,
            host=HOST,
            port=port,
            reload=False,
            log_config=None,  # 禁用默认 log config（避免 isatty 错误）
            log_level="warning",
            access_log=False,
        )
    except Exception:
        with open(_STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 服务器启动失败:\n")
            f.write(traceback.format_exc())
            f.write("\n")


def _confirm_exit():
    """
    关闭确认对话框 - 主流应用的标准交互
    参考：VS Code、微信、各种专业软件都有此功能
    返回值：True = 退出, False = 取消
    """
    result = ctypes.windll.user32.MessageBoxW(
        0,
        "确定要退出 OKEworkplace 吗？\n\n[是] 直接退出程序\n[否] 取消",
        "退出确认",
        0x00000004 | 0x00000040,  # MB_YESNO | MB_ICONINFORMATION
    )
    return result == 6  # IDYES = 6


def _open_gui_window(port):
    """用 pywebview 创建独立窗口，失败则回退到浏览器"""
    try:
        import webview

        window = webview.create_window(
            title="OKEworkplace - 交易分析终端",
            url=f"http://{HOST}:{port}/index.html",
            width=1280,
            height=800,
            min_size=(960, 600),
            resizable=True,
            text_select=True,
            confirm_close=True,  # pywebview 原生关闭确认对话框
        )

        def on_window_closed():
            """窗口关闭后的回调 - 触发优雅关闭"""
            from app.shutdown import shutdown_event
            shutdown_event.set()

        window.events.closed += on_window_closed

        # webview.start() 启动 GUI 事件循环并显示窗口，阻塞直到窗口被关闭
        webview.start()
        # 窗口关闭 → 触发关闭信号
        from app.shutdown import shutdown_event
        shutdown_event.set()
        return True
    except Exception as e:
        print(f"  GUI 窗口启动失败: {e}")
        print(f"  回退到浏览器打开...")
        return False


def _open_browser(port):
    """打开系统默认浏览器（回退方案）"""
    import webbrowser
    url = f"http://{HOST}:{port}/index.html"
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"  浏览器打开失败: {e}")
        print(f"  请手动访问: {url}")


if __name__ == "__main__":
    # 信号处理
    def signal_handler(signum, frame):
        from app.shutdown import shutdown_event
        shutdown_event.set()
        sys.exit(0)

    if sys.platform.startswith("win"):
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    print("╔══════════════════════════════════════╗")
    print("║     OKEworkplace - 交易分析终端      ║")
    print("╠══════════════════════════════════════╣")
    print("║  正在启动后端服务...                  ║")
    print("╚══════════════════════════════════════╝")
    print()

    # 0. 自动选择可用端口
    port = find_available_port(8000)
    if port != 8000:
        print(f"  ⚠ 端口 8000 被占用，自动使用端口 {port}")

    # 1. 后台启动服务器
    server_thread = threading.Thread(target=_start_server, args=(port,), daemon=True)
    server_thread.start()

    # 2. 等待服务器就绪
    if not _wait_for_server(port):
        print("=" * 46)
        print(f"  ❌ 服务启动失败，请检查端口 {port} 是否被占用")
        print("  请查看 startup_error.log 了解详情")
        print("=" * 46)
        time.sleep(5)
        sys.exit(1)

    print("=" * 46)
    print(f"  ✅ 服务已就绪！端口: {port}")
    print("  正在打开窗口...")
    print("=" * 46)
    print()
    print("  📌 关闭窗口即可自动停止服务")
    print()

    # 3. 尝试打开独立窗口，失败则回退浏览器
    if not _open_gui_window(port):
        _open_browser(port)
        # 浏览器模式下等待关闭信号
        from app.shutdown import shutdown_event
        shutdown_event.wait()

    # 4. 关闭后处理
    print()
    print("=" * 46)
    print("  ✅ 前端已关闭")
    print("  ✅ 后端已关闭")
    print("  窗口即将自动关闭...")
    print("=" * 46)
    print()
    time.sleep(2)
    # 进程退出 → 控制台窗口自动关闭
