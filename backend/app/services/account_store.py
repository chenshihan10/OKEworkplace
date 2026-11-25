"""V2.6 实盘只读本地存储：live_account.db（WAL）。

设计取舍：
- 独立成库，不复用 signals.db / user_trades.db：账户敏感数据可独立删除、备份与限权；
- 只做 `CREATE TABLE/INDEX IF NOT EXISTS`，P1 不需要 ALTER 迁移；
- 成交以 (inst_id, trade_id) 为主键，重复拉取靠主键去重；
- 时间统一写 ISO8601 UTC 字符串，成交原始毫秒时间戳保留在 ts 字段。
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.services.order_manager import _db_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountStore:
    def __init__(self, db_dir: Optional[str] = None) -> None:
        self.db_dir = db_dir or _db_dir()
        os.makedirs(self.db_dir, exist_ok=True)
        self.db_path = os.path.join(self.db_dir, "live_account.db")
        self._init_db()

    def _connect(self, timeout: float = 10) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _conn(self):
        """短事务：成功即提交，异常回滚，退出必关闭（Windows 下不关闭会锁库文件）。"""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute('''CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                total_eq REAL, avail_eq REAL, upl REAL,
                imr REAL, mmr REAL, mgn_ratio REAL, ord_frozen REAL,
                details_json TEXT
            )''')
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_account_snapshots_time "
                "ON account_snapshots(created_at)"
            )
            conn.execute('''CREATE TABLE IF NOT EXISTS position_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                inst_id TEXT NOT NULL,
                pos_side TEXT,
                pos_raw REAL,
                pos_unit TEXT NOT NULL DEFAULT 'contract',
                avg_px REAL, mark_px REAL,
                upl REAL, upl_ratio REAL,
                lever REAL, liq_px REAL, mgn_ratio REAL, mgn_mode TEXT,
                raw_json TEXT
            )''')
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_position_snapshots_inst "
                "ON position_snapshots(inst_id, created_at)"
            )
            conn.execute('''CREATE TABLE IF NOT EXISTS account_fills (
                inst_id TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                ord_id TEXT,
                side TEXT, pos_side TEXT,
                px REAL, sz REAL,
                fee REAL, fee_ccy TEXT,
                ts INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                raw_json TEXT,
                PRIMARY KEY (inst_id, trade_id)
            )''')
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_account_fills_ts ON account_fills(ts)"
            )
            conn.execute('''CREATE TABLE IF NOT EXISTS account_config_cache (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                acct_lv TEXT, pos_mode TEXT, mgn_mode TEXT,
                fee_taker REAL, fee_maker REAL,
                updated_at TEXT NOT NULL,
                raw_json TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS account_sync_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )''')

    # ─── 账户摘要快照 ──────────────────────────────────
    def save_account_snapshot(self, data: Dict) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO account_snapshots
                   (created_at, total_eq, avail_eq, upl, imr, mmr, mgn_ratio,
                    ord_frozen, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("created_at") or _now_iso(),
                    data.get("total_eq"), data.get("avail_eq"), data.get("upl"),
                    data.get("imr"), data.get("mmr"), data.get("mgn_ratio"),
                    data.get("ord_frozen"),
                    json.dumps(data.get("details") or [], ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid or 0)

    # ─── 持仓快照 ──────────────────────────────────────
    def save_position_snapshots(self, rows: List[Dict]) -> int:
        if not rows:
            return 0

        created_at = _now_iso()
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO position_snapshots
                   (created_at, inst_id, pos_side, pos_raw, pos_unit, avg_px, mark_px,
                    upl, upl_ratio, lever, liq_px, mgn_ratio, mgn_mode, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        created_at, row.get("inst_id"), row.get("pos_side"),
                        row.get("pos_raw"), row.get("pos_unit") or "contract",
                        row.get("avg_px"), row.get("mark_px"),
                        row.get("upl"), row.get("upl_ratio"),
                        row.get("lever"), row.get("liq_px"), row.get("mgn_ratio"),
                        row.get("mgn_mode"),
                        json.dumps(row.get("raw") or {}, ensure_ascii=False),
                    )
                    for row in rows
                ],
            )
            return len(rows)

    # ─── 成交（去重） ──────────────────────────────────
    def upsert_fills(self, rows: List[Dict]) -> int:
        if not rows:
            return 0

        inserted = 0
        created_at = _now_iso()
        with self._conn() as conn:
            for row in rows:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO account_fills
                       (inst_id, trade_id, ord_id, side, pos_side, px, sz, fee,
                        fee_ccy, ts, created_at, raw_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row.get("inst_id"), str(row.get("trade_id")),
                        row.get("ord_id"), row.get("side"), row.get("pos_side"),
                        row.get("px"), row.get("sz"), row.get("fee"),
                        row.get("fee_ccy"), int(row.get("ts") or 0),
                        created_at,
                        json.dumps(row.get("raw") or {}, ensure_ascii=False),
                    ),
                )
                if cursor.rowcount:
                    inserted += cursor.rowcount
        return inserted

    def get_fills(self, limit: int = 50, offset: int = 0,
                  inst_id: Optional[str] = None) -> Dict:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        where = ""
        args: List = []
        if inst_id:
            where = " WHERE inst_id = ?"
            args.append(inst_id)

        with self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM account_fills{where}", args
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT inst_id, trade_id, ord_id, side, pos_side, px, sz,
                           fee, fee_ccy, ts
                    FROM account_fills{where}
                    ORDER BY ts DESC LIMIT ? OFFSET ?""",
                [*args, limit, offset],
            ).fetchall()

        items = []
        for row in rows:
            ts = int(row[9] or 0)
            items.append({
                "inst_id": row[0], "trade_id": row[1], "ord_id": row[2],
                "side": row[3], "pos_side": row[4], "px": row[5], "sz": row[6],
                "fee": row[7], "fee_ccy": row[8], "ts": ts,
                "ts_iso": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
                if ts else None,
            })
        return {"total": int(total), "items": items}

    def last_fill_ts(self) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(ts) FROM account_fills").fetchone()
        return int(row[0]) if row and row[0] else None

    # ─── 账户配置缓存 ──────────────────────────────────
    def save_config(self, data: Dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO account_config_cache
                   (id, acct_lv, pos_mode, mgn_mode, fee_taker, fee_maker,
                    updated_at, raw_json)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     acct_lv=excluded.acct_lv,
                     pos_mode=excluded.pos_mode,
                     mgn_mode=excluded.mgn_mode,
                     fee_taker=excluded.fee_taker,
                     fee_maker=excluded.fee_maker,
                     updated_at=excluded.updated_at,
                     raw_json=excluded.raw_json""",
                (
                    data.get("acct_lv"), data.get("pos_mode"), data.get("mgn_mode"),
                    data.get("fee_taker"), data.get("fee_maker"),
                    data.get("updated_at") or _now_iso(),
                    json.dumps(data.get("raw") or {}, ensure_ascii=False),
                ),
            )

    def get_config(self) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT acct_lv, pos_mode, mgn_mode, fee_taker, fee_maker,
                          updated_at FROM account_config_cache WHERE id = 1"""
            ).fetchone()
        if not row:
            return None
        return {
            "acct_lv": row[0], "pos_mode": row[1], "mgn_mode": row[2],
            "fee_taker": row[3], "fee_maker": row[4], "updated_at": row[5],
        }

    # ─── 同步游标 ──────────────────────────────────────
    def get_state(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM account_sync_state WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO account_sync_state (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value, updated_at=excluded.updated_at""",
                (key, str(value), _now_iso()),
            )

    # ─── 保留策略 ──────────────────────────────────────
    def prune(self, retention_days: int, fills_retention_days: int) -> Dict:
        now = datetime.now(timezone.utc)
        snapshot_cutoff = (now - timedelta(days=max(1, int(retention_days)))).isoformat()
        fills_cutoff_ms = int(
            (now - timedelta(days=max(1, int(fills_retention_days)))).timestamp() * 1000
        )
        with self._conn() as conn:
            deleted_snapshots = conn.execute(
                "DELETE FROM account_snapshots WHERE created_at < ?", (snapshot_cutoff,)
            ).rowcount
            deleted_positions = conn.execute(
                "DELETE FROM position_snapshots WHERE created_at < ?", (snapshot_cutoff,)
            ).rowcount
            deleted_fills = conn.execute(
                "DELETE FROM account_fills WHERE ts < ?", (fills_cutoff_ms,)
            ).rowcount
        return {
            "snapshots": max(0, deleted_snapshots),
            "positions": max(0, deleted_positions),
            "fills": max(0, deleted_fills),
            "snapshot_cutoff": snapshot_cutoff,
        }

    def stats(self) -> Dict:
        with self._conn() as conn:
            counts = {}
            for table in ("account_snapshots", "position_snapshots",
                          "account_fills", "account_config_cache"):
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
        return {
            "db_path": self.db_path,
            "size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0,
            "counts": counts,
            "last_fill_ts": self.last_fill_ts(),
        }
