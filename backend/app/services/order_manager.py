"""V2.3 用户订单管理服务"""
from __future__ import annotations

import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
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


def _finite(value, name: str) -> Optional[float]:
    """把外部传入的价格/数量规范成有限浮点数；None 保持 None。"""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是数字")
    if not math.isfinite(num):
        raise ValueError(f"{name} 必须是有限数值")
    return num


def validate_levels(direction: str, entry_price: float,
                    stop_loss: Optional[float],
                    take_profit: Optional[float]) -> tuple:
    """校验止损/止盈与开仓价的方向一致性。

    LONG: SL < entry < TP；SHORT: SL > entry > TP；只填一侧时也必须在正确方向。
    返回规范化后的 (stop_loss, take_profit)。
    """
    direction = (direction or "").upper()
    entry_price = _finite(entry_price, "开仓价")
    stop_loss = _finite(stop_loss, "止损价")
    take_profit = _finite(take_profit, "止盈价")

    if entry_price is None or entry_price <= 0:
        raise ValueError("开仓价必须大于 0")

    if direction == "LONG":
        if stop_loss is not None and stop_loss >= entry_price:
            raise ValueError("多头止损价必须低于开仓价")
        if take_profit is not None and take_profit <= entry_price:
            raise ValueError("多头止盈价必须高于开仓价")
    elif direction == "SHORT":
        if stop_loss is not None and stop_loss <= entry_price:
            raise ValueError("空头止损价必须高于开仓价")
        if take_profit is not None and take_profit >= entry_price:
            raise ValueError("空头止盈价必须低于开仓价")
    else:
        raise ValueError("方向必须是 LONG 或 SHORT")

    return stop_loss, take_profit


def planned_risk(entry_price: float, stop_loss: Optional[float], quantity: float) -> Optional[float]:
    """计划风险金额：|开仓价 - 止损价| × 数量；无止损或数量为 0 时返回 None。"""
    if stop_loss is None or not quantity:
        return None
    return round(abs(entry_price - stop_loss) * quantity, 4)


def risk_reward(entry_price: float, stop_loss: Optional[float],
                take_profit: Optional[float]) -> Optional[float]:
    """盈亏比 R = |止盈 - 开仓| / |开仓 - 止损|；缺一侧或分母为 0 时返回 None。"""
    if stop_loss is None or take_profit is None:
        return None
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return None
    return round(abs(take_profit - entry_price) / risk, 3)


class OrderManager:
    """用户订单管理服务"""

    DB_NAME = "user_trades.db"
    # 同一订单 + 同一建议的提示冷却时间（秒）
    LEVEL_ALERT_COOLDOWN_SECONDS = 30 * 60

    def __init__(self, db_dir: str = None):
        if db_dir is None:
            db_dir = _db_dir()
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, self.DB_NAME)
        # 价格触及提示的最近触发时间：{(order_id, suggestion): timestamp}
        self._level_alert_times: Dict[tuple, float] = {}
        self._init_db()

    def _connect(self, timeout: float = 10) -> sqlite3.Connection:
        """统一连接入口：WAL + busy_timeout，降低与风险事件写入的锁冲突。"""
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def level_alert_state(self, order_id: int, suggestion: str) -> dict:
        """价格触及提示冷却。

        同一订单、同一建议在 30 分钟内只提示一次，避免 5 秒轮询反复打扰。
        返回 alert（本次是否应提示）与 cooldown_remaining（剩余秒数）。
        """
        key = (order_id, suggestion)
        now = time.time()
        last = self._level_alert_times.get(key)

        if last is not None:
            remaining = int(self.LEVEL_ALERT_COOLDOWN_SECONDS - (now - last))
            if remaining > 0:
                return {"alert": False, "cooldown_remaining": remaining}

        self._level_alert_times[key] = now
        return {"alert": True, "cooldown_remaining": 0}

    def clear_level_alerts(self, order_id: int) -> None:
        """订单平仓后清理其冷却记录"""
        for key in [k for k in self._level_alert_times if k[0] == order_id]:
            self._level_alert_times.pop(key, None)

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _migrate_risk_columns(self, conn: sqlite3.Connection) -> None:
        for column in ("stop_loss", "take_profit"):
            self._ensure_column(conn, "orders", column, "REAL")
        for column, ddl in (
            ("stop_loss", "REAL"),
            ("take_profit", "REAL"),
            ("exit_reason", "TEXT"),
            ("planned_risk", "REAL"),
            ("rr", "REAL"),
        ):
            self._ensure_column(conn, "closed_orders", column, ddl)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
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
            conn.execute("""CREATE TABLE IF NOT EXISTS risk_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                equity REAL,
                risk_per_trade_pct REAL DEFAULT 1.0,
                max_portfolio_risk_pct REAL DEFAULT 6.0,
                max_symbol_concentration_pct REAL DEFAULT 50.0,
                updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                event_type TEXT NOT NULL,
                price REAL,
                level REAL,
                created_at TEXT NOT NULL
            )""")
            self._migrate_risk_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_symbol ON closed_orders(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_result ON closed_orders(result)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_risk_events_order ON risk_events(order_id, created_at)")

    # ─── 风险偏好 ─────────────────────────────────────────

    DEFAULTS = {
        "equity": None,
        "risk_per_trade_pct": 1.0,
        "max_portfolio_risk_pct": 6.0,
        "max_symbol_concentration_pct": 50.0,
    }

    def get_risk_settings(self) -> dict:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM risk_settings WHERE id = 1").fetchone()
        if not row:
            return {**self.DEFAULTS, "updated_at": None}
        data = dict(row)
        data.pop("id", None)
        return data

    def save_risk_settings(self, equity: Optional[float],
                           risk_per_trade_pct: float,
                           max_portfolio_risk_pct: float,
                           max_symbol_concentration_pct: float) -> dict:
        equity = _finite(equity, "账户权益")
        risk_per_trade_pct = _finite(risk_per_trade_pct, "单笔风险比例")
        max_portfolio_risk_pct = _finite(max_portfolio_risk_pct, "组合风险比例")
        max_symbol_concentration_pct = _finite(max_symbol_concentration_pct, "单币集中度")

        if equity is not None and equity <= 0:
            raise ValueError("账户权益必须大于 0（留空表示未配置）")
        for value, name in (
            (risk_per_trade_pct, "单笔风险比例"),
            (max_portfolio_risk_pct, "组合风险比例"),
            (max_symbol_concentration_pct, "单币集中度"),
        ):
            if value is None or value <= 0 or value > 100:
                raise ValueError(f"{name}必须在 0~100 之间")

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO risk_settings
                   (id, equity, risk_per_trade_pct, max_portfolio_risk_pct,
                    max_symbol_concentration_pct, updated_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     equity=excluded.equity,
                     risk_per_trade_pct=excluded.risk_per_trade_pct,
                     max_portfolio_risk_pct=excluded.max_portfolio_risk_pct,
                     max_symbol_concentration_pct=excluded.max_symbol_concentration_pct,
                     updated_at=excluded.updated_at""",
                (equity, risk_per_trade_pct, max_portfolio_risk_pct,
                 max_symbol_concentration_pct, now),
            )
        return self.get_risk_settings()

    # ─── 订单 ─────────────────────────────────────────────

    def create_order(self, symbol: str, direction: str, entry_price: float,
                     quantity: float = 0, note: str = "",
                     stop_loss: Optional[float] = None,
                     take_profit: Optional[float] = None) -> dict:
        """开单（可选止损/止盈）"""
        direction = direction.upper()
        entry_price = _finite(entry_price, "开仓价")
        quantity = _finite(quantity, "数量") or 0
        if entry_price is None or entry_price <= 0:
            raise ValueError("开仓价必须大于 0")
        if quantity < 0:
            raise ValueError("数量不能为负数")
        stop_loss, take_profit = validate_levels(direction, entry_price, stop_loss, take_profit)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO orders
                   (symbol, direction, entry_price, quantity, note, status,
                    stop_loss, take_profit, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                (symbol, direction, entry_price, quantity, note,
                 stop_loss, take_profit, now, now),
            )
            order_id = cur.lastrowid
        return {
            "id": order_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "quantity": quantity,
            "note": note,
            "status": "open",
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "planned_risk": planned_risk(entry_price, stop_loss, quantity),
            "rr": risk_reward(entry_price, stop_loss, take_profit),
            "created_at": now,
        }

    def update_order_risk(self, order_id: int, stop_loss: Optional[float],
                          take_profit: Optional[float]) -> dict:
        """设置/清除止损止盈；传 None 表示清除该侧。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM orders WHERE id=? AND status='open'", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"订单 {order_id} 不存在或已平仓")
            order = dict(row)
            stop_loss, take_profit = validate_levels(
                order["direction"], order["entry_price"], stop_loss, take_profit
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute(
                "UPDATE orders SET stop_loss=?, take_profit=?, updated_at=? WHERE id=?",
                (stop_loss, take_profit, now, order_id),
            )
        order.update({"stop_loss": stop_loss, "take_profit": take_profit, "updated_at": now})
        order["planned_risk"] = planned_risk(order["entry_price"], stop_loss, order.get("quantity") or 0)
        order["rr"] = risk_reward(order["entry_price"], stop_loss, take_profit)
        return order

    def get_open_orders(self, symbol: Optional[str] = None) -> List[dict]:
        """当前持仓列表"""
        with self._connect() as conn:
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

    def close_order(self, order_id: int, close_price: float, quantity: Optional[float] = None,
                    exit_reason: str = "manual") -> dict:
        """平仓：移至 closed_orders，并快照止损/止盈/计划风险/R/退出原因"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM orders WHERE id=? AND status='open'", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"订单 {order_id} 不存在或已平仓")

            order = dict(row)
            qty = quantity or order["quantity"]
            pnl = _calc_pnl(order["direction"], order["entry_price"], close_price, qty)
            stop_loss = order.get("stop_loss")
            take_profit = order.get("take_profit")
            risk_amount = planned_risk(order["entry_price"], stop_loss, qty)
            rr = risk_reward(order["entry_price"], stop_loss, take_profit)

            # 写入 closed_orders
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute(
                """INSERT INTO closed_orders
                   (original_order_id, symbol, direction, entry_price, close_price,
                    quantity, pnl_pct, pnl_abs, result, note, opened_at, closed_at,
                    stop_loss, take_profit, exit_reason, planned_risk, rr)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, order["symbol"], order["direction"], order["entry_price"],
                 close_price, qty, pnl["pnl_pct"], pnl["pnl_abs"], pnl["result"],
                 order["note"], order["created_at"], now,
                 stop_loss, take_profit, exit_reason, risk_amount, rr),
            )
            # 删除原订单
            conn.execute("DELETE FROM orders WHERE id=?", (order_id,))

        # 平仓后清理该订单的价格触及冷却记录
        self.clear_level_alerts(order_id)

        return {
            "id": order_id,
            "symbol": order["symbol"],
            "direction": order["direction"],
            "entry_price": order["entry_price"],
            "close_price": close_price,
            "quantity": qty,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "exit_reason": exit_reason,
            "planned_risk": risk_amount,
            "rr": rr,
            **pnl,
            "closed_at": now,
        }

    def get_closed_orders(self, limit: int = 50, offset: int = 0) -> List[dict]:
        """已平仓历史"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM closed_orders ORDER BY closed_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_summary(self) -> dict:
        """统计概览"""
        with self._connect() as conn:
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

    # ─── 风险触达事件 ─────────────────────────────────────

    def record_risk_event(self, order_id: int, symbol: str, event_type: str,
                          price: Optional[float], level: Optional[float],
                          cooldown_seconds: int = LEVEL_ALERT_COOLDOWN_SECONDS) -> Optional[dict]:
        """同一订单 + 同一事件在冷却期内只写一条；返回新事件或 None（冷却中）。"""
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=cooldown_seconds)).isoformat()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            recent = conn.execute(
                "SELECT id FROM risk_events WHERE order_id=? AND event_type=? AND created_at >= ? "
                "ORDER BY id DESC LIMIT 1",
                (order_id, event_type, cutoff),
            ).fetchone()
            if recent:
                return None
            created_at = now.isoformat()
            cur = conn.execute(
                "INSERT INTO risk_events (order_id, symbol, event_type, price, level, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, symbol, event_type, price, level, created_at),
            )
            event_id = cur.lastrowid
        return {
            "id": event_id,
            "order_id": order_id,
            "symbol": symbol,
            "event_type": event_type,
            "price": price,
            "level": level,
            "created_at": created_at,
        }

    def list_risk_events(self, symbol: Optional[str] = None, limit: int = 50) -> List[dict]:
        limit = max(1, min(int(limit or 50), 200))
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM risk_events WHERE symbol=? ORDER BY id DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM risk_events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
