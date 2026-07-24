"""V2.3 用户订单管理服务"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _db_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')


def _calc_pnl(direction: str, entry_price: float, close_price: float, quantity: float) -> dict:
    """计算盈亏"""
    if direction == "LONG":
        pnl_pct = (close_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - close_price) / entry_price * 100
    pnl_abs = pnl_pct / 100 * entry_price * quantity

    if pnl_pct > 0.1:
        result = "win"
    elif pnl_pct < -0.1:
        result = "loss"
    else:
        result = "breakeven"

    return {
        "pnl_pct": round(pnl_pct, 2),
        "pnl_abs": round(pnl_abs, 2),
        "result": result,
    }


class OrderManager:
    """用户订单管理服务"""

    DB_NAME = "user_trades.db"

    def __init__(self, db_dir: str = None):
        if db_dir is None:
            db_dir = _db_dir()
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, self.DB_NAME)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL DEFAULT 0,
                note TEXT DEFAULT '',
                status TEXT DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS closed_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_order_id INTEGER,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                close_price REAL NOT NULL,
                quantity REAL DEFAULT 0,
                pnl_pct REAL,
                pnl_abs REAL,
                result TEXT,
                note TEXT DEFAULT '',
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_symbol ON closed_orders(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_result ON closed_orders(result)")

    def create_order(self, symbol: str, direction: str, entry_price: float,
                     quantity: float = 0, note: str = "") -> dict:
        """开单"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO orders (symbol, direction, entry_price, quantity, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, direction.upper(), entry_price, quantity, note, now, now),
            )
            order_id = cur.lastrowid
        return {
            "id": order_id,
            "symbol": symbol,
            "direction": direction.upper(),
            "entry_price": entry_price,
            "quantity": quantity,
            "note": note,
            "status": "open",
            "created_at": now,
        }

    def get_open_orders(self, symbol: Optional[str] = None) -> List[dict]:
        """当前持仓列表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE status='open' AND symbol=? ORDER BY created_at DESC", (symbol,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE status='open' ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def close_order(self, order_id: int, close_price: float, quantity: Optional[float] = None) -> dict:
        """平仓：移至 closed_orders"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM orders WHERE id=? AND status='open'", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"订单 {order_id} 不存在或已平仓")

            order = dict(row)
            qty = quantity or order["quantity"]
            pnl = _calc_pnl(order["direction"], order["entry_price"], close_price, qty)

            # 写入 closed_orders
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute(
                """INSERT INTO closed_orders
                   (original_order_id, symbol, direction, entry_price, close_price,
                    quantity, pnl_pct, pnl_abs, result, note, opened_at, closed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, order["symbol"], order["direction"], order["entry_price"],
                 close_price, qty, pnl["pnl_pct"], pnl["pnl_abs"], pnl["result"],
                 order["note"], order["created_at"], now),
            )
            # 删除原订单
            conn.execute("DELETE FROM orders WHERE id=?", (order_id,))

        return {
            "id": order_id,
            "symbol": order["symbol"],
            "direction": order["direction"],
            "entry_price": order["entry_price"],
            "close_price": close_price,
            "quantity": qty,
            **pnl,
            "closed_at": now,
        }

    def get_closed_orders(self, limit: int = 50, offset: int = 0) -> List[dict]:
        """已平仓历史"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM closed_orders ORDER BY closed_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_summary(self) -> dict:
        """统计概览"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # 持仓数
            open_count = conn.execute("SELECT COUNT(*) as c FROM orders WHERE status='open'").fetchone()["c"]
            # 历史
            closed = conn.execute("SELECT COUNT(*) as c, SUM(pnl_abs) as total FROM closed_orders").fetchone()
            closed_count = closed["c"] or 0
            total_pnl = round(closed["total"] or 0, 2)
            # 胜率
            wins = conn.execute("SELECT COUNT(*) as c FROM closed_orders WHERE result='win'").fetchone()["c"]
            win_rate = round(wins / closed_count * 100, 1) if closed_count > 0 else 0

            # 今日平仓
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_closed = conn.execute(
                "SELECT COUNT(*) as c FROM closed_orders WHERE closed_at LIKE ?", (f"{today}%",)
            ).fetchone()["c"]

        return {
            "open_orders": open_count,
            "today_closed": today_closed,
            "total_pnl": total_pnl,
            "total_closed": closed_count,
            "win_rate": win_rate,
        }
