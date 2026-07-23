"""PyInstaller EXE entry point - starts server and opens GUI window"""
import sys
import threading
import time
import urllib.request
import json
from pathlib import Path

# Add backend dir to path for imports
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"


def _wait_for_server(timeout=30):
    """等待后端服务器就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"{BASE_URL}/health", timeout=2)
            if json.loads(resp.read()).get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _start_server():
    """在后台线程中启动 uvicorn"""
    import uvicorn
    from app.main import app
    uvicorn.run(app, host=HOST, port=PORT, reload=False, log_level="warning")


def _open_gui_window():
    """用 pywebview 创建独立窗口，失败则回退到浏览器"""
    try:
        import webview
        webview.create_window(
            title="OKEworkplace - 交易分析终端",
            url=f"{BASE_URL}/index_v2.html",
            width=1280,
            height=800,
            min_size=(960, 600),
            resizable=True,
            text_select=True,
            confirm_close=True,
        )
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


def _open_browser():
    """打开系统默认浏览器（回退方案）"""
    import webbrowser
    try:
        webbrowser.open(f"{BASE_URL}/index_v2.html")
    except Exception as e:
        print(f"  浏览器打开失败: {e}")
        print(f"  请手动访问: {BASE_URL}/index_v2.html")


if __name__ == "__main__":
    print("╔══════════════════════════════════════╗")
    print("║     OKEworkplace - 交易分析终端      ║")
    print("╠══════════════════════════════════════╣")
    print("║  正在启动后端服务...                  ║")
    print("╚══════════════════════════════════════╝")
    print()

    # 1. 后台启动服务器
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # 2. 等待服务器就绪
    if not _wait_for_server():
        print("=" * 46)
        print("  ❌ 服务启动失败，请检查端口 8000 是否被占用")
        print("  可运行 stop.bat 释放端口后重试")
        print("=" * 46)
        input("\n按 Enter 退出...")
        sys.exit(1)

    print("=" * 46)
    print("  ✅ 服务已就绪！")
    print("  正在打开窗口...")
    print("=" * 46)
    print()
    print("  📌 关闭窗口即可自动停止服务")
    print()

    # 3. 尝试打开独立窗口，失败则回退浏览器
    if not _open_gui_window():
        _open_browser()
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
