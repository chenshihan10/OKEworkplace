"""V3.0 自动备份：SQLite 在线备份（signals.db / user_trades.db）+ 保留份数管理。

触发策略（面向「一天开三五次、每次几十分钟」的使用方式）：
- 每次启动，运行满 5 分钟后尝试一次；
- 之后每 5 分钟检查一次，只有本次进程累计运行满 backup_runtime_hours 才允许再次备份；
- 与上次成功备份相比数据没有新增（表最大 id / 页数未变）时跳过，避免整库重复拷贝；
- 只保留最近 backup_keep 份（默认 3）。
上次备份的数据签名落盘保存，重启后也能判断“没有实质变化”。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Optional

from app.core.config import settings
from app.services.db_store import SignalDB

FIRST_RUN_MINUTES = 5

# 用于判断“数据有没有实质变化”的表（按最大 id 与页数比较，代价很小）
_SIGNAL_TABLES = ("signals", "signal_snapshots", "analysis_snapshots", "predictions",
                  "prediction_results", "order_flow_snapshots")
_TRADE_TABLES = ("orders", "closed_orders", "risk_events")
_ACCOUNT_TABLES = ("account_snapshots", "position_snapshots", "account_fills",
                   "account_config_cache", "account_sync_state")


class BackupService:
    def __init__(self) -> None:
        data_dir = os.path.dirname(SignalDB().db_path)
        self.data_dir = data_dir
        self.backup_dir = settings.backup_dir or os.path.join(data_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        # 异地镜像：默认放到用户目录，避免与程序/备份同盘同目录（可用 OKE_BACKUP_MIRROR_DIR 覆盖）
        self.mirror_dir = settings.backup_mirror_dir or os.path.join(
            os.path.expanduser("~"), "OKEworkplace_backups"
        )
        try:
            os.makedirs(self.mirror_dir, exist_ok=True)
        except OSError as exc:
            logging.getLogger(__name__).warning("backup mirror dir unavailable: %s", exc)
            self.mirror_dir = ""
        self.last_backup: Dict = {"at": None, "files": [], "removed": 0, "error": None}
        self.last_check: Dict = {"at": None, "action": "idle", "reason": None, "uptime_hours": 0}
        self._started_at = datetime.now(timezone.utc)
        self._last_backup_uptime: Optional[float] = None
        self._state_path = os.path.join(self.backup_dir, "backup_state.json")
        self._state = self._read_state()

    # ─── 运行时长与状态 ────────────────────────────────
    def uptime_hours(self) -> float:
        return (datetime.now(timezone.utc) - self._started_at).total_seconds() / 3600

    def _read_state(self) -> Dict:
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _write_state(self) -> None:
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False)
            os.replace(tmp, self._state_path)
        except Exception as exc:
            logging.getLogger(__name__).warning("backup state write failed: %s", exc)

    def _data_signature(self) -> Dict:
        """轻量数据签名：三张库的页数 + 各表最大 id/时间戳，用于判断备份是否有必要。"""
        signature: Dict = {}
        for name, tables in (("signals.db", _SIGNAL_TABLES),
                             ("user_trades.db", _TRADE_TABLES),
                             ("live_account.db", _ACCOUNT_TABLES)):
            path = os.path.join(self.data_dir, name)
            if not os.path.exists(path):
                signature[name] = None
                continue
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
                try:
                    pages = conn.execute("PRAGMA page_count").fetchone()[0]
                    marks = [self._table_mark(conn, table) for table in tables]
                finally:
                    conn.close()
                signature[name] = [pages, *marks]
            except sqlite3.Error:
                signature[name] = "unreadable"
        return signature

    @staticmethod
    def _table_mark(conn: sqlite3.Connection, table: str) -> int:
        """取表的最大 id；无 id 的表用 ts；两者都没有则退回行数。"""
        for column in ("id", "ts"):
            try:
                return conn.execute(
                    f"SELECT COALESCE(MAX({column}), 0) FROM {table}"
                ).fetchone()[0]
            except sqlite3.Error:
                continue
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            return -1

    # ─── 触发判断 ──────────────────────────────────────
    def maybe_backup(self) -> Dict:
        """按运行时长与数据变化决定是否备份；返回本次检查结果。"""
        now = datetime.now(timezone.utc)
        uptime = self.uptime_hours()
        base = {"at": now.isoformat(), "uptime_hours": round(uptime, 2)}

        if uptime * 60 < FIRST_RUN_MINUTES:
            return self._record({**base, "action": "skip", "reason": "waiting_first_run"})

        if (self._last_backup_uptime is not None
                and uptime - self._last_backup_uptime < settings.backup_runtime_hours):
            return self._record({**base, "action": "skip", "reason": "interval"})

        signature = self._data_signature()
        previous = self._state.get("signature")
        if previous is not None and signature == previous:
            return self._record({**base, "action": "skip", "reason": "unchanged"})

        result = self.create_backup()
        if result.get("error") is None:
            self._last_backup_uptime = uptime
            self._state = {
                "signature": signature,
                "at": result["at"],
                "files": result["files"],
            }
            self._write_state()
            return self._record({**base, "action": "backup", "reason": "due",
                                 "files": len(result["files"])})
        return self._record({**base, "action": "failed", "reason": result["error"]})

    def _record(self, check: Dict) -> Dict:
        self.last_check = check
        return check

    # ─── 备份与清理 ────────────────────────────────────
    def _backup_one(self, name: str, stamp: str) -> str:
        src_path = os.path.join(self.data_dir, name)
        if not os.path.exists(src_path):
            return ""
        target = os.path.join(self.backup_dir, f"{os.path.splitext(name)[0]}_{stamp}.db")
        tmp = target + ".tmp"
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        except Exception:
            dst.close()
            src.close()
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        else:
            dst.close()
            src.close()
        os.replace(tmp, target)
        return target

    def _prune(self) -> int:
        return self._prune_dir(self.backup_dir)

    def _prune_dir(self, directory: str) -> int:
        removed = 0
        keep = max(1, settings.backup_keep)
        if not directory or not os.path.isdir(directory):
            return 0
        for prefix in ("signals_", "user_trades_", "live_account_"):
            files = sorted(
                (f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".db")),
                reverse=True,
            )
            for old in files[keep:]:
                try:
                    os.remove(os.path.join(directory, old))
                    removed += 1
                except OSError:
                    continue
        return removed

    def _mirror(self, files: list) -> Dict:
        """把刚生成的备份复制到异地镜像目录，并同样按份数清理。失败只记录，不影响本地备份结果。"""
        result: Dict = {"dir": self.mirror_dir, "files": [], "error": None}
        if not self.mirror_dir:
            result["error"] = "mirror dir unavailable"
            return result
        try:
            for src in files:
                dst = os.path.join(self.mirror_dir, os.path.basename(src))
                shutil.copy2(src, dst)
                result["files"].append(dst)
            self._prune_dir(self.mirror_dir)
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
            logging.getLogger(__name__).warning("mirror backup failed: %s", exc)
        return result

    def create_backup(self) -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        try:
            files = [p for p in (self._backup_one("signals.db", stamp),
                                 self._backup_one("user_trades.db", stamp),
                                 self._backup_one("live_account.db", stamp)) if p]
            removed = self._prune()
            self.last_backup = {
                "at": datetime.now(timezone.utc).isoformat(),
                "files": files,
                "removed": removed,
                "mirror": self._mirror(files),
                "error": None,
            }
        except Exception as exc:
            logging.getLogger(__name__).warning("backup failed: %s", exc)
            self.last_backup = {
                "at": datetime.now(timezone.utc).isoformat(),
                "files": [],
                "removed": 0,
                "error": str(exc),
            }
        return self.last_backup

    def status(self) -> dict:
        files = sorted(
            f for f in os.listdir(self.backup_dir)
            if os.path.isfile(os.path.join(self.backup_dir, f)) and f.endswith(".db")
        ) if os.path.isdir(self.backup_dir) else []
        return {
            "backup_dir": self.backup_dir,
            "mirror_dir": self.mirror_dir,
            "keep": settings.backup_keep,
            "runtime_hours": settings.backup_runtime_hours,
            "first_run_minutes": FIRST_RUN_MINUTES,
            "uptime_hours": round(self.uptime_hours(), 2),
            "last_check": self.last_check,
            "last_backup": self.last_backup,
            "files": files[-20:],
        }


backup_service = BackupService()
