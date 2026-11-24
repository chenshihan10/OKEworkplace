"""V3.0 自动备份：SQLite 在线备份（signals.db / user_trades.db）+ 保留份数管理。"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict

from app.core.config import settings
from app.services.db_store import SignalDB


class BackupService:
    def __init__(self) -> None:
        data_dir = os.path.dirname(SignalDB().db_path)
        self.data_dir = data_dir
        self.backup_dir = settings.backup_dir or os.path.join(data_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.last_backup: Dict = {"at": None, "files": [], "removed": 0, "error": None}

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
        removed = 0
        keep = max(1, settings.backup_keep)
        for prefix in ("signals_", "user_trades_"):
            files = sorted(
                (f for f in os.listdir(self.backup_dir) if f.startswith(prefix) and f.endswith(".db")),
                reverse=True,
            )
            for old in files[keep:]:
                try:
                    os.remove(os.path.join(self.backup_dir, old))
                    removed += 1
                except OSError:
                    continue
        return removed

    def create_backup(self) -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        try:
            files = [p for p in (self._backup_one("signals.db", stamp),
                                 self._backup_one("user_trades.db", stamp)) if p]
            removed = self._prune()
            self.last_backup = {
                "at": datetime.now(timezone.utc).isoformat(),
                "files": files,
                "removed": removed,
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
        files = sorted(os.listdir(self.backup_dir)) if os.path.isdir(self.backup_dir) else []
        return {
            "backup_dir": self.backup_dir,
            "keep": settings.backup_keep,
            "interval_hours": settings.backup_interval_hours,
            "last_backup": self.last_backup,
            "files": files[-20:],
        }


backup_service = BackupService()
