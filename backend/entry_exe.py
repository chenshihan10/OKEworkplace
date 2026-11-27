"""PyInstaller EXE entry point - starts server and opens GUI window with tray icon"""
import sys
import os
import io
import threading
import time
import urllib.request
import urllib.parse
import json
import logging
import logging.handlers
import signal
import secrets
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

from app.core.config import APP_VERSION

APP_TITLE = f"OKEworkplace v{APP_VERSION} - 交易分析终端"
# 开发模式给页面带 dev=1 参数，前端据此启用文件变更自动刷新；打包版不带，零开销
# 开发模式给页面带 dev=1 参数，前端据此启用文件变更自动刷新；打包版不带
_DEV_QUERY = "" if getattr(sys, "frozen", False) else "dev=1"

# 本地接口加固：桌面模式标记 + 每次启动生成一次性 token
# 必须在 app.main 导入（服务器线程）之前写入环境变量
LOCAL_TOKEN = os.environ.get("OKE_LOCAL_TOKEN") or secrets.token_urlsafe(18)
os.environ["OKE_LOCAL_TOKEN"] = LOCAL_TOKEN
os.environ.setdefault("OKE_DESKTOP", "1")


def _page_query() -> str:
    """页面查询串：开发模式标记 + 本地 API token"""
    parts = [p for p in (_DEV_QUERY, "token=" + urllib.parse.quote(LOCAL_TOKEN)) if p]
    return "?" + "&".join(parts)

# 错误日志文件（用于诊断无法启动的问题）
_LOG_DIR = _backend_dir if not getattr(sys, 'frozen', False) else Path.cwd()
_STARTUP_LOG = _LOG_DIR / "startup_error.log"

HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"

# 应用日志：固定放在程序目录/logs 下，按天轮转
_APP_LOG_DIR = _LOG_DIR / "logs"
_APP_LOG_FILE = _APP_LOG_DIR / "app.log"
_MUTEX_HANDLE = None


def _setup_logging() -> None:
    """应用日志按天轮转（保留 14 天），并接管未捕获异常。"""
    try:
        _APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            _APP_LOG_FILE, when="midnight", backupCount=14, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        if not any(isinstance(h, logging.handlers.TimedRotatingFileHandler)
                   for h in root.handlers):
            root.addHandler(handler)
        # 调度器每次任务都打 INFO，噪声过大；只保留告警
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

        def _hook(exc_type, exc, tb):
            root.error("未捕获异常", exc_info=(exc_type, exc, tb))
            sys.__excepthook__(exc_type, exc, tb)

        sys.excepthook = _hook
        threading.excepthook = lambda args: root.error(
            "线程未捕获异常",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    except Exception:
        pass


def _notify(title: str, text: str) -> None:
    """打包环境没有控制台，关键提示用系统弹窗；OKE_SILENT=1 时只写日志。"""
    logging.getLogger(__name__).warning("%s: %s", title, text.replace("\n", " "))
    if os.getenv("OKE_SILENT") == "1" or not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x00000040)
    except Exception:
        pass


def _acquire_single_instance() -> bool:
    """命名互斥体：同一登录会话只允许一个实例，避免两个进程写同一个数据库。"""
    global _MUTEX_HANDLE
    if not sys.platform.startswith("win"):
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        _MUTEX_HANDLE = kernel32.CreateMutexW(
            None, False, "Local\\OKEworkplace_SingleInstance"
        )
        if not _MUTEX_HANDLE:
            return True
        # ERROR_ALREADY_EXISTS
        return kernel32.GetLastError() != 183
    except Exception:
        return True


def _focus_existing_window() -> bool:
    """把已运行的窗口恢复到前台；成功返回 True。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) == 0


def _wait_for_server(port, timeout=30):
    """等待后端服务器就绪"""
    # 本机自检必须绕过代理：.env 里的 HTTP_PROXY 会让 urllib 把 127.0.0.1 也发给代理
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    start = time.time()
    while time.time() - start < timeout:
        try:
            url = f"http://{HOST}:{port}/health"
            resp = opener.open(url, timeout=2)
            if json.loads(resp.read()).get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _write_startup_log(port):
    """记录本次启动的关键信息（打包后没有控制台，用户可据此确认网络出口）"""
    if not getattr(sys, "frozen", False):
        return
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://{HOST}:{port}/network/status", timeout=3) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        source = info.get("proxy_source") or "未知"
        proxy = info.get("proxy") or ""
        exit_text = f"{source} {proxy}".strip() if proxy else f"{source}（未检测到代理）"
        with open(_LOG_DIR / "startup.log", "w", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] OKEworkplace v{APP_VERSION} 启动\n")
            f.write(f"  监听端口: {port}\n")
            f.write(f"  网络出口: {exit_text}\n")
    except Exception:
        pass


def _append_startup_log(*lines):
    """向 startup.log 追加一行说明（打包版没有控制台，供用户/排查使用）"""
    if not getattr(sys, "frozen", False):
        return
    try:
        with open(_LOG_DIR / "startup.log", "a", encoding="utf-8") as f:
            for line in lines:
                f.write(f"  {line}\n")
    except Exception:
        pass


def _reset_startup_error_log():
    """每次启动清空上一次的报错记录，避免用户看到已经解决的历史错误"""
    if not getattr(sys, "frozen", False):
        return
    try:
        if _STARTUP_LOG.exists():
            _STARTUP_LOG.unlink()
    except Exception:
        pass


def _clear_zone_identifier():
    """清掉打包文件上的「来自 Internet」标记（Mark-of-the-Web）。

    从浏览器下载 zip 再解压时，Windows 会给每个文件写入 Zone.Identifier
    备用数据流；.NET Framework 默认拒绝加载这类程序集
    （loadFromRemoteSources），导致 pythonnet / pywebview 初始化失败，
    只剩浏览器回退。这里在创建窗口前把标记清掉。
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        base = Path(sys.executable).resolve().parent
        for path in base.rglob("*"):
            if path.suffix.lower() not in (".dll", ".exe", ".pyd"):
                continue
            stream = str(path) + ":Zone.Identifier"
            try:
                if os.path.exists(stream):
                    os.remove(stream)
            except OSError:
                pass
    except Exception:
        pass


def _gui_ready():
    """检查 pythonnet（.NET）能否初始化；不能则直接走浏览器回退。"""
    try:
        import clr  # noqa: F401
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


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
    关闭确认对话框 - v2.2 三选项
    [是] 直接退出 | [否] 最小化到托盘 | [取消] 继续使用
    返回值：0=退出, 1=最小化到托盘, -1=取消
    """
    import ctypes
    result = ctypes.windll.user32.MessageBoxW(
        0,
        "确定要退出 OKEworkplace 吗？\n\n"
        "[是] 直接退出程序\n"
        "[否] 最小化到系统托盘\n"
        "[取消] 继续使用",
        "退出确认",
        0x00000003 | 0x00000040,  # MB_YESNOCANCEL | MB_ICONINFORMATION
    )
    # IDYES=6, IDNO=7, IDCANCEL=2
    if result == 6:
        return 0   # 退出
    elif result == 7:
        return 1   # 最小化到托盘
    return -1       # 取消


def _start_tray_icon(window_ref):
    """
    v2.2 pystray 系统托盘 - 独立线程运行
    window_ref: pywebview window 对象的弱引用容器 [window]
    """
    try:
        import pystray
        from PIL import Image, ImageDraw

        # 创建 64x64 图标
        icon_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon_img)
        draw.ellipse([4, 4, 60, 60], fill="#3b82f6")
        draw.text((16, 14), "OK", fill="white")

        def on_show(icon, item):
            w = window_ref[0]
            if w:
                w.show()
                # 使用 webview 的 native API 恢复窗口
                try:
                    import webview
                    if hasattr(w, 'restore'):
                        w.restore()
                except Exception:
                    pass

        def on_exit(icon, item):
            icon.stop()
            from app.shutdown import shutdown_event
            shutdown_event.set()

        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", on_exit),
        )

        icon = pystray.Icon("OKEworkplace", icon_img, APP_TITLE, menu)

        def _stale_loop():
            """数据停更巡检：60 秒一次，超阈值弹托盘通知（10 分钟内不重复）。"""
            from app.services.health_monitor import should_alert_stale

            threshold = int(os.getenv("OKE_STALE_ALERT_SECONDS", "300"))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            last_alert = None
            while True:
                time.sleep(60)
                try:
                    with opener.open(f"http://{HOST}:{PORT}/network/status", timeout=3) as resp:
                        info = json.loads(resp.read().decode("utf-8"))
                    age = info.get("data_age_seconds")
                    now = time.time()
                    if should_alert_stale(age, threshold, last_alert, now):
                        last_alert = now
                        message = f"行情数据已 {age} 秒未更新，请检查代理或网络。"
                        logging.getLogger(__name__).warning("数据停更告警: %s", message)
                        try:
                            icon.notify(message, "OKEworkplace 数据停更")
                        except Exception:
                            pass
                except Exception:
                    continue

        threading.Thread(target=_stale_loop, daemon=True).start()
        logging.getLogger(__name__).info(
            "数据停更巡检已启动（阈值 %ss，冷却 600s）",
            os.getenv("OKE_STALE_ALERT_SECONDS", "300"),
        )
        icon.run()
    except ImportError:
        pass  # 无 pystray 时静默跳过


def _open_gui_window(port):
    """用 pywebview 创建独立窗口（支持最小化到系统托盘）"""
    try:
        import webview

        # 避免循环导入：用 list wrapper 存储 window 引用
        window_ref = [None]

        def on_closing():
            """窗口关闭前回调 - 显示三选项对话框"""
            choice = _confirm_exit()
            if choice == 0:         # 退出
                return True
            elif choice == 1:       # 最小化到托盘
                w = window_ref[0]
                if w:
                    w.hide()
                return False        # 阻止关闭
            return False            # 取消 - 阻止关闭

        window = webview.create_window(
            title=APP_TITLE,
            url=f"http://{HOST}:{port}/index.html{_page_query()}",
            width=1280,
            height=800,
            min_size=(960, 600),
            resizable=True,
            text_select=True,
            confirm_close=False,  # v2.2：使用自定义关闭对话框
        )
        window_ref[0] = window

        # v2.2：启动系统托盘（后台线程）
        tray_thread = threading.Thread(
            target=_start_tray_icon, args=(window_ref,), daemon=True
        )
        tray_thread.start()

        def on_window_closed():
            """窗口关闭后的回调"""
            from app.shutdown import shutdown_event
            shutdown_event.set()

        # 拦截 closing 事件
        window.events.closing += on_closing
        window.events.closed += on_window_closed

        webview.start()
        # 窗口关闭 → 触发关闭信号
        from app.shutdown import shutdown_event
        shutdown_event.set()
        return True
    except Exception as e:
        # 打包后无控制台，必须落盘，否则 GUI 启动失败完全不可见
        with open(_STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] GUI 窗口启动失败:\n")
            f.write(traceback.format_exc())
            f.write("\n")
        print(f"  GUI 窗口启动失败: {e}")
        print(f"  回退到浏览器打开...")
        return False


def _open_browser(port):
    """打开系统默认浏览器（回退方案）"""
    import webbrowser
    url = f"http://{HOST}:{port}/index.html{_page_query()}"
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

    _setup_logging()

    # 单实例：已有进程在跑时聚焦原窗口并退出，避免两个进程写同一个数据库
    if not _acquire_single_instance():
        focused = _focus_existing_window()
        logging.getLogger(__name__).warning("检测到已有实例，本次启动退出（聚焦窗口=%s）", focused)
        if not focused:
            _notify("OKEworkplace 已在运行",
                    f"程序已在运行（端口 {PORT}）。\n请从任务栏或系统托盘打开原窗口。")
        sys.exit(0)

    print("╔══════════════════════════════════════╗")
    print("║     OKEworkplace - 交易分析终端      ║")
    print("╠══════════════════════════════════════╣")
    print("║  正在启动后端服务...                  ║")
    print("╚══════════════════════════════════════╝")
    print()

    # 清理上一次的报错记录与下载文件的「来自 Internet」标记（否则 .NET 拒绝加载）
    _reset_startup_error_log()
    _clear_zone_identifier()

    # 固定端口：被占用时明确提示，不再自动漂移（避免文档/快捷方式对不上）
    if _port_in_use(PORT):
        _notify("端口被占用",
                f"端口 {PORT} 已被其他程序占用。\n"
                "请关闭占用该端口的程序后重新启动（程序不会自动改用其他端口）。")
        logging.getLogger(__name__).error("端口 %s 被占用，启动中止", PORT)
        sys.exit(1)

    # 启动前数据库自检：异常时明确提示从备份恢复（不静默继续写）
    try:
        from app.services.db_integrity import check_data_dir
        integrity = check_data_dir()
        bad = [f for f in integrity["files"]
               if not f["ok"] and f.get("detail") != "missing"]
        if bad:
            detail = "；".join(
                f"{os.path.basename(f['path'])}: {f['detail']}" for f in bad
            )
            logging.getLogger(__name__).error("数据库自检异常: %s", detail)
            _notify("数据库自检异常",
                    "检测到数据库文件异常：\n" + detail[:400] +
                    "\n\n建议先备份故障文件，再从最近备份恢复后重新启动。")
        else:
            logging.getLogger(__name__).info("数据库自检通过")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("数据库自检未执行: %s", exc)

    port = PORT

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

    # 启动日志：记录端口与最终网络出口，便于排查「双击没数据」的问题
    _write_startup_log(port)
    print("  📌 关闭窗口即可自动停止服务")
    print()

    from app.shutdown import shutdown_event

    # 3. 打开窗口：优先独立窗口；.NET 不可用时直接走系统浏览器，不写报错日志
    gui_ok, gui_reason = _gui_ready()
    if gui_ok:
        _append_startup_log("窗口后端: 独立窗口（WebView2）")
        if not _open_gui_window(port):
            _append_startup_log("提示: 独立窗口启动失败，已改用系统浏览器（功能一致）")
            _open_browser(port)
            shutdown_event.wait()
    else:
        _append_startup_log(
            f"窗口后端: 系统浏览器（回退，原因: {gui_reason}）",
            "提示: 安装 .NET Framework 4.8 后可恢复独立窗口，功能不受影响",
        )
        # 浏览器模式同样启动托盘，保证用户能正常退出程序
        threading.Thread(target=_start_tray_icon, args=([None],), daemon=True).start()
        _open_browser(port)
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
