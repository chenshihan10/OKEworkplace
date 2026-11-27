"""SQLite 完整性自检（只读、带缓存）。

两个使用点：
- 启动自检（entry_exe）：任何库 quick_check 异常时写日志并提示从最近备份恢复；
- /health：暴露数据库健康状态，便于外部脚本与托盘判断。

quick_check 对 10MB 级库是毫秒级；结果缓存 5 分钟，避免频繁磁盘 IO。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

CACHE_SECONDS = 300
_cache = {}  # path -> (checked_ts, ok, detail)


def data_dir() -> str:
    """与 db_store 保持一致的目录解析（不实例化 SignalDB，避免自检时建表）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def data_files() -> list:
    base = data_dir()
    return [os.path.join(base, name)
            for name in ("signals.db", "user_trades.db", "live_account.db")]


def quick_check(path: str, force: bool = False) -> dict:
    now = time.time()
    if not force and path in _cache:
        ts, ok, detail = _cache[path]
        if now - ts < CACHE_SECONDS:
            return {"path": path, "ok": ok, "detail": detail, "cached": True}

    if not os.path.exists(path):
        result = {"path": path, "ok": True, "detail": "missing"}
    else:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
            try:
                rows = conn.execute("PRAGMA quick_check").fetchall()
            finally:
                conn.close()
            ok = bool(rows) and all(str(r[0]).lower() == "ok" for r in rows)
            detail = "ok" if ok else "; ".join(str(r[0]) for r in rows[:3])
            result = {"path": path, "ok": ok, "detail": detail}
        except sqlite3.Error as exc:
            result = {"path": path, "ok": False, "detail": f"error: {exc}"}

    _cache[path] = (now, result["ok"], result["detail"])
    result["cached"] = False
    return result


def check_data_dir() -> dict:
    items = [quick_check(p) for p in data_files()]
    return {
        "ok": all(i["ok"] for i in items),
        "files": items,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
