"""v2.2 SQLite 信号持久化存储"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import zlib
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional


class SignalDB:
    """SQLite 信号持久化存储"""

    def __init__(self, db_dir: str = None):
        if db_dir is None:
            if getattr(sys, 'frozen', False):
                db_dir = os.path.dirname(sys.executable)
            else:
                db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, 'signals.db')
        # 每个币种最近一次“已落库”的判断指纹与快照时间（进程内，重启后首条会重写）
        self._signal_state: Dict[str, dict] = {}
        self._init_db()

    def _connect(self, timeout: float = 10) -> sqlite3.Connection:
        """统一连接入口：WAL + busy_timeout，降低并发写入时的锁冲突"""
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute('''CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                raw_direction TEXT,
                score INTEGER,
                confidence INTEGER,
                level TEXT,
                risk TEXT,
                mark_price REAL,
                index_price REAL,
                price REAL,
                data_source TEXT DEFAULT 'okx',
                raw_signal TEXT,
                decision_trace TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS analysis_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trend_score INTEGER DEFAULT 0,
                momentum_score INTEGER DEFAULT 0,
                volume_score INTEGER DEFAULT 0,
                oi_score INTEGER DEFAULT 0,
                funding_score INTEGER DEFAULT 0,
                trend_phase TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )''')
            # V3.0 Prediction Logger：有方向的判断留档，供后续 Future Validator 回验。
            # 回验字段先留空，表结构用 IF NOT EXISTS，已有库无需重建。
            conn.execute('''CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                score INTEGER,
                level TEXT,
                regime TEXT,
                price REAL,
                reasons TEXT,
                created_at TEXT NOT NULL,
                verify_status TEXT DEFAULT 'pending',
                verified_at TEXT,
                outcome TEXT,
                price_after REAL,
                pnl_pct REAL
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS signal_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER,
                symbol TEXT NOT NULL,
                timeframe TEXT,
                created_at TEXT NOT NULL,
                encoding TEXT DEFAULT 'zlib+json',
                payload_bytes INTEGER NOT NULL,
                payload_z_bytes INTEGER NOT NULL,
                payload_z BLOB NOT NULL
            )''')
            # V3.0 订单流采样：不是每 5 秒写，按配置间隔（默认 5 分钟）一条
            conn.execute('''CREATE TABLE IF NOT EXISTS order_flow_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                created_at TEXT NOT NULL,
                window_minutes INTEGER NOT NULL,
                buy_volume REAL,
                sell_volume REAL,
                delta REAL,
                delta_ratio REAL,
                session_cvd REAL,
                large_buy REAL,
                large_sell REAL,
                book_imbalance REAL,
                flow_bias REAL,
                quality TEXT,
                payload_z BLOB
            )''')
            # V3.0：回验字段（增量迁移，兼容旧库）
            self._migrate_predictions(conn)
            # V3.0 预测上下文：预测时刻可见的新指标，一对一挂在 prediction_id 上
            conn.execute('''CREATE TABLE IF NOT EXISTS prediction_context (
                prediction_id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                created_at TEXT NOT NULL,
                timeframe TEXT,
                mtf_resonance TEXT,
                mtf_alignment INTEGER,
                mtf_json TEXT,
                orderflow_bias REAL,
                orderflow_json TEXT,
                market_json TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS prediction_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                horizon TEXT NOT NULL,
                price_type TEXT NOT NULL DEFAULT 'candle_close',
                entry_price REAL,
                exit_price REAL,
                gross_return REAL,
                estimated_cost REAL,
                net_return REAL,
                mfe REAL,
                mae REAL,
                outcome TEXT,
                verify_status TEXT NOT NULL,
                data_quality TEXT,
                verified_at TEXT,
                note TEXT,
                UNIQUE(prediction_id, horizon)
            )''')
            self._create_indexes(conn)

    @staticmethod
    def _migrate_predictions(conn):
        """给 predictions 增量补列；旧记录因缺少 timeframe/price_type 标为不可回验。"""
        cols = {row[1] for row in conn.execute("PRAGMA table_info(predictions)")}
        additions = {
            "timeframe": "TEXT",
            "price_type": "TEXT",
            "strategy_version": "TEXT",
            "verifiable": "INTEGER DEFAULT 1",
            "verify_note": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE predictions ADD COLUMN {name} {ddl}")
        # 迁移前写入的历史记录没有 timeframe/price_type，不回填猜测值，直接标记不可回验
        conn.execute(
            "UPDATE predictions SET verifiable = 0, "
            "verify_note = COALESCE(verify_note, '历史记录缺少 timeframe/price_type/strategy_version，未回填，标记为不可回验') "
            "WHERE timeframe IS NULL"
        )

    @staticmethod
    def _create_indexes(conn):
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_analysis_symbol ON analysis_snapshots(symbol)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_predictions_symbol_created ON predictions(symbol, created_at)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_pred_results_symbol_time ON prediction_results(symbol, verified_at)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_pred_results_status ON prediction_results(verify_status)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_pred_results_horizon ON prediction_results(horizon)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_signal_snapshots_symbol_time ON signal_snapshots(symbol, created_at)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_orderflow_symbol_time ON order_flow_snapshots(symbol, created_at)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_pred_ctx_symbol_time ON prediction_context(symbol, created_at)''')

    def save_signal(self, symbol: str, signal_data: dict) -> int:
        """保存信号到数据库，返回 ID"""
        analysis = signal_data.get('analysis')
        if analysis is None:
            return 0

        # 如果 analysis 是 dataclass 对象，转 dict
        if hasattr(analysis, '__dataclass_fields__'):
            analysis_dict = asdict(analysis)
        elif isinstance(analysis, dict):
            analysis_dict = analysis
        else:
            analysis_dict = {}

        direction = analysis_dict.get('direction', 'NEUTRAL')
        raw_direction = signal_data.get('raw_direction') or analysis_dict.get('direction')
        score = analysis_dict.get('score', 0)
        level = analysis_dict.get('level', '')
        risk = analysis_dict.get('risk', 'LOW')
        mark_price = signal_data.get('mark_price', 0) or 0
        index_price = signal_data.get('index_price', 0) or 0
        price = analysis_dict.get('price', 0) or 0
        data_source = analysis_dict.get('data_source', 'okx')

        # raw_signal: JSON 序列化（排除 analysis 本身，避免重复）
        raw_signal_dict = {k: v for k, v in signal_data.items() if k != 'analysis'}
        raw_signal_json = json.dumps(raw_signal_dict, default=str, ensure_ascii=False)

        # decision_trace: 如果有 decision_trace 字段
        decision_trace = signal_data.get('decision_trace')
        decision_trace_json = json.dumps(decision_trace, default=str, ensure_ascii=False) if decision_trace else ''

        with self._connect() as conn:
            cursor = conn.execute(
                '''INSERT INTO signals (symbol, direction, raw_direction, score, confidence, level, risk,
                   mark_price, index_price, price, data_source, raw_signal, decision_trace)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (symbol, direction, raw_direction, score, 0, level, risk,
                 mark_price, index_price, price, data_source,
                 raw_signal_json, decision_trace_json)
            )
            return cursor.lastrowid

    def save_signal_sampled(self, symbol: str, signal_data: dict,
                            score_delta: int = 5, heartbeat_minutes: int = 5,
                            snapshot_minutes: int = 5) -> int:
        """按“判断变化”落库，并把原始快照压缩后降采样存到 signal_snapshots。

        规则：
        - signals 行：方向/过滤后方向/等级/风险变化，或评分变化 >= score_delta，
          或距上次写入超过 heartbeat_minutes 才写一条；行内不再保存 raw_signal。
        - signal_snapshots：判断写行时同步存一份；否则每 snapshot_minutes 存一份压缩快照。
        返回 signals 行 ID；未写行时为 0。
        """
        analysis = signal_data.get('analysis')
        if analysis is None:
            return 0
        if hasattr(analysis, '__dataclass_fields__'):
            analysis_dict = asdict(analysis)
        elif isinstance(analysis, dict):
            analysis_dict = analysis
        else:
            return 0

        direction = analysis_dict.get('direction', 'NEUTRAL')
        raw_direction = signal_data.get('raw_direction') or analysis_dict.get('direction')
        score = analysis_dict.get('score', 0) or 0
        level = analysis_dict.get('level', '') or ''
        risk = analysis_dict.get('risk', 'LOW') or 'LOW'
        mark_price = signal_data.get('mark_price', 0) or 0
        index_price = signal_data.get('index_price', 0) or 0
        price = analysis_dict.get('price', 0) or 0
        data_source = analysis_dict.get('data_source', 'okx')
        decision_trace = signal_data.get('decision_trace')
        decision_trace_json = json.dumps(decision_trace, default=str, ensure_ascii=False) if decision_trace else ''

        now = datetime.now(timezone.utc)
        state = self._signal_state.get(symbol)
        write_row = state is None
        if state is not None:
            elapsed = (now - state['written_at']).total_seconds() / 60
            changed = (
                direction != state['direction']
                or raw_direction != state['raw_direction']
                or level != state['level']
                or risk != state['risk']
                or abs(score - state['score']) >= score_delta
            )
            write_row = changed or elapsed >= heartbeat_minutes

        # 原始快照：过滤后的方向变化时留一份，否则按 snapshot_minutes 降采样
        # （raw_direction 会逐跳抖动，不能作为快照触发条件）
        direction_changed = state is None or direction != state['direction']
        snapshot_due = direction_changed
        if not snapshot_due and state is not None:
            snapshot_due = (now - state['snapshot_at']).total_seconds() / 60 >= snapshot_minutes

        signal_id = 0
        payload_z = b''
        payload_bytes = 0
        if snapshot_due:
            payload = json.dumps({k: v for k, v in signal_data.items() if k != 'analysis'},
                                 default=str, ensure_ascii=False).encode('utf-8')
            payload_bytes = len(payload)
            payload_z = zlib.compress(payload, 6)

        with self._connect() as conn:
            if write_row:
                cursor = conn.execute(
                    '''INSERT INTO signals (symbol, direction, raw_direction, score, confidence, level, risk,
                       mark_price, index_price, price, data_source, raw_signal, decision_trace)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (symbol, direction, raw_direction, score, 0, level, risk,
                     mark_price, index_price, price, data_source, '', decision_trace_json)
                )
                signal_id = cursor.lastrowid
            if snapshot_due and payload_z:
                conn.execute(
                    '''INSERT INTO signal_snapshots
                       (signal_id, symbol, timeframe, created_at, encoding, payload_bytes, payload_z_bytes, payload_z)
                       VALUES (?, ?, ?, ?, 'zlib+json', ?, ?, ?)''',
                    (signal_id or None, symbol, signal_data.get('timeframe') or '15m',
                     now.strftime('%Y-%m-%d %H:%M:%S'), payload_bytes, len(payload_z), payload_z)
                )

        self._signal_state[symbol] = {
            'direction': direction,
            'raw_direction': raw_direction,
            'score': score,
            'level': level,
            'risk': risk,
            'written_at': now if write_row else (state['written_at'] if state else now),
            'snapshot_at': now if snapshot_due else (state['snapshot_at'] if state else now),
        }
        return signal_id

    def save_analysis_snapshot(self, symbol: str, components: dict, trend_phase: str = "") -> int:
        """保存分析快照"""
        with self._connect() as conn:
            cursor = conn.execute(
                '''INSERT INTO analysis_snapshots (symbol, trend_score, momentum_score, volume_score,
                   oi_score, funding_score, trend_phase)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (symbol,
                 components.get('trend', 0),
                 components.get('momentum', 0),
                 components.get('volume', 0),
                 components.get('oi', 0),
                 components.get('funding', 0),
                 trend_phase)
            )
            return cursor.lastrowid

    # ─── 订单流采样 ───────────────────────────────────────

    def save_order_flow_snapshot(self, symbol: str, window_minutes: int, data: dict,
                                 payload: Optional[dict] = None) -> int:
        """写入一条订单流采样（默认 5 分钟一条，不是实时逐笔）。"""
        now = datetime.now(timezone.utc).isoformat()
        payload_z = None
        if payload is not None:
            payload_z = zlib.compress(
                json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'), 6
            )
        with self._connect() as conn:
            cursor = conn.execute(
                '''INSERT INTO order_flow_snapshots
                   (symbol, created_at, window_minutes, buy_volume, sell_volume, delta,
                    delta_ratio, session_cvd, large_buy, large_sell, book_imbalance,
                    flow_bias, quality, payload_z)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (symbol, now, window_minutes,
                 data.get('buy_volume'), data.get('sell_volume'), data.get('delta'),
                 data.get('delta_ratio'), data.get('session_cvd'),
                 data.get('large_buy'), data.get('large_sell'), data.get('book_imbalance'),
                 data.get('flow_bias'), json.dumps(data.get('quality') or {}, ensure_ascii=False),
                 payload_z),
            )
            return cursor.lastrowid

    def query_order_flow_snapshots(self, symbol: Optional[str] = None,
                                   start: Optional[str] = None, end: Optional[str] = None,
                                   limit: int = 200) -> List[Dict]:
        where = []
        params: List = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol)
        if start:
            where.append("created_at >= ?")
            params.append(start)
        if end:
            where.append("created_at <= ?")
            params.append(end)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM order_flow_snapshots{where_sql} ORDER BY id DESC LIMIT ?",
                params + [max(1, min(int(limit or 200), 1000))],
            ).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            d.pop('payload_z', None)
            try:
                d['quality'] = json.loads(d['quality']) if d.get('quality') else {}
            except (json.JSONDecodeError, TypeError):
                d['quality'] = {}
            items.append(d)
        return items

    # ─── 预测上下文 ───────────────────────────────────────

    def save_prediction_context(self, prediction_id: int, symbol: str, timeframe: Optional[str],
                                mtf_resonance: Optional[str], mtf_alignment: Optional[int],
                                mtf: Optional[dict], orderflow_bias: Optional[float],
                                orderflow: Optional[dict], market: Optional[dict]) -> None:
        """每条预测最多一行上下文；允许字段为空，不阻塞预测落库。"""
        def dump(value):
            return json.dumps(value, ensure_ascii=False, default=str) if value is not None else None

        with self._connect() as conn:
            conn.execute(
                '''INSERT OR IGNORE INTO prediction_context
                   (prediction_id, symbol, created_at, timeframe, mtf_resonance, mtf_alignment,
                    mtf_json, orderflow_bias, orderflow_json, market_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (prediction_id, symbol, datetime.now(timezone.utc).isoformat(), timeframe,
                 mtf_resonance, mtf_alignment, dump(mtf), orderflow_bias, dump(orderflow), dump(market)),
            )

    def query_prediction_context(self, prediction_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM prediction_context WHERE prediction_id = ?", (prediction_id,)
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("mtf_json", "orderflow_json", "market_json"):
            try:
                data[key] = json.loads(data[key]) if data.get(key) else None
            except (json.JSONDecodeError, TypeError):
                data[key] = None
        return data

    def _context_group(self, bucket_sql: str, where_sql: str, params: List,
                       min_sample: int) -> List[Dict]:
        base = (
            "FROM predictions p "
            "JOIN prediction_context c ON c.prediction_id = p.id "
            "LEFT JOIN prediction_results r ON r.prediction_id = p.id" + where_sql
        )
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT {bucket_sql} AS bucket, {self.PERF_AGG} {base} "
                "GROUP BY bucket ORDER BY bucket",
                params,
            ).fetchall()
        groups = []
        for row in rows:
            data = self._finalize_perf(dict(row))
            data["insufficient_sample"] = (data.get("verified") or 0) < min_sample
            if data["insufficient_sample"]:
                # 样本不足只展示计数，不给胜率结论
                data["win_rate"] = None
                data["directional_accuracy"] = None
                data["avg_net_return"] = None
                data["avg_gross_return"] = None
            groups.append(data)
        return groups

    def context_summary(self, symbol: Optional[str] = None, start: Optional[str] = None,
                        end: Optional[str] = None, min_sample: int = 30) -> Dict:
        """按多周期共振、订单流偏向分桶统计胜率；样本不足只返回计数。"""
        where_sql, params = self._perf_where(symbol, start, end)
        mtf_groups = self._context_group(
            "COALESCE(c.mtf_resonance, 'unavailable')", where_sql, params, min_sample
        )
        flow_groups = self._context_group(
            """CASE
                 WHEN c.orderflow_bias IS NULL THEN 'unavailable'
                 WHEN c.orderflow_bias < -30 THEN 'bearish'
                 WHEN c.orderflow_bias > 30 THEN 'bullish'
                 ELSE 'neutral'
               END""",
            where_sql, params, min_sample,
        )
        return {
            "mtf_resonance": mtf_groups,
            "orderflow_bias": flow_groups,
            "min_sample": min_sample,
            "definition": "胜率=WIN/已回验；样本不足时只展示计数，不给胜率结论",
        }

    def get_recent_signals(self, symbol: str, limit: int = 50) -> List[Dict]:
        """获取最近的信号历史"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                '''SELECT * FROM signals WHERE symbol = ? ORDER BY created_at DESC LIMIT ?''',
                (symbol, limit)
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # 反序列化 JSON 字段
                if d.get('raw_signal'):
                    try:
                        d['raw_signal'] = json.loads(d['raw_signal'])
                    except (json.JSONDecodeError, TypeError):
                        pass
                if d.get('decision_trace'):
                    try:
                        d['decision_trace'] = json.loads(d['decision_trace'])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results

    def get_signal_stats(self, symbol: str) -> Dict:
        """获取信号统计（各方向数量、平均评分等）"""
        with self._connect() as conn:
            direction_counts = dict(conn.execute(
                '''SELECT direction, COUNT(*) as cnt FROM signals WHERE symbol = ? GROUP BY direction''',
                (symbol,)
            ).fetchall())

            row = conn.execute(
                '''SELECT AVG(score) as avg_score, MAX(score) as max_score, MIN(score) as min_score,
                   COUNT(*) as total FROM signals WHERE symbol = ?''',
                (symbol,)
            ).fetchone()

            last_row = conn.execute(
                '''SELECT created_at FROM signals WHERE symbol = ? ORDER BY created_at DESC LIMIT 1''',
                (symbol,)
            ).fetchone()

            return {
                'symbol': symbol,
                'total_signals': row[3] if row else 0,
                'avg_score': round(row[0], 1) if row and row[0] else 0,
                'max_score': row[1] if row else 0,
                'min_score': row[2] if row else 0,
                'direction_counts': direction_counts,
                'last_signal_at': last_row[0] if last_row else None,
            }

    # ─── V3.0 Prediction Logger ─────────────────────────────

    def save_prediction(self, symbol: str, direction: str, score: int, level: str,
                        regime: str, price: float, reasons: List[str],
                        timeframe: str = "15m", price_type: str = "candle_close",
                        strategy_version: str = "") -> int:
        """写入一条方向预测（回验字段保持空，后续由 Future Validator 填充）"""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                '''INSERT INTO predictions
                   (symbol, direction, score, level, regime, price, reasons, created_at,
                    timeframe, price_type, strategy_version, verifiable)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
                (symbol, direction, score, level, regime, price,
                 json.dumps(reasons or [], ensure_ascii=False), now,
                 timeframe, price_type, strategy_version)
            )
            return cursor.lastrowid

    def get_last_prediction(self, symbol: str) -> Optional[Dict]:
        """某币种最近一条预测（用于节流判断）"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                '''SELECT * FROM predictions WHERE symbol = ? ORDER BY created_at DESC, id DESC LIMIT 1''',
                (symbol,),
            ).fetchone()
            return dict(row) if row else None

    def query_predictions(self, symbol: Optional[str] = None,
                          start: Optional[str] = None, end: Optional[str] = None,
                          limit: int = 50, offset: int = 0) -> tuple:
        """按币种/时间范围查询预测记录，返回 (items, total)"""
        where = []
        params: List = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol)
        if start:
            where.append("created_at >= ?")
            params.append(start)
        if end:
            where.append("created_at <= ?")
            params.append(end)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM predictions{where_sql}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM predictions{where_sql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        items = []
        for row in rows:
            d = dict(row)
            if d.get("reasons"):
                try:
                    d["reasons"] = json.loads(d["reasons"])
                except (json.JSONDecodeError, TypeError):
                    pass
            items.append(d)
        return items, total

    # ─── V3.0 数据维护：signals 保留策略 ─────────────────

    def signal_stats(self) -> Dict:
        """signals / signal_snapshots 当前体积与时间范围（用于维护接口/验证）"""
        stats = {"rows": 0, "oldest": None, "newest": None, "file_bytes": 0,
                 "snapshot_rows": 0, "snapshot_raw_bytes": 0, "snapshot_z_bytes": 0}
        with self._connect() as conn:
            stats["rows"] = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            oldest, newest = conn.execute("SELECT MIN(created_at), MAX(created_at) FROM signals").fetchone()
            stats["oldest"], stats["newest"] = oldest, newest
            snap = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(payload_bytes),0), COALESCE(SUM(payload_z_bytes),0) "
                "FROM signal_snapshots").fetchone()
            stats["snapshot_rows"], stats["snapshot_raw_bytes"], stats["snapshot_z_bytes"] = snap
        if os.path.exists(self.db_path):
            stats["file_bytes"] = os.path.getsize(self.db_path)
        return stats

    def prune_signals(self, days: int = 7, batch_size: int = 500) -> Dict:
        """分批删除超过保留期的 signals，避免一次性长事务锁库。

        注：SQLite 删除后文件不会自动缩小；如需回收磁盘，由维护人员手工执行 VACUUM。
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        deleted = 0
        deleted_snapshots = 0
        batches = 0
        with self._connect(timeout=30) as conn:
            while True:
                cursor = conn.execute(
                    "DELETE FROM signals WHERE id IN "
                    "(SELECT id FROM signals WHERE created_at < ? LIMIT ?)",
                    (cutoff, batch_size),
                )
                conn.commit()
                count = cursor.rowcount
                if count <= 0:
                    break
                deleted += count
                batches += 1
                time.sleep(0.05)  # 让出写锁，避免长时间阻塞行情写入
            while True:
                cursor = conn.execute(
                    "DELETE FROM signal_snapshots WHERE id IN "
                    "(SELECT id FROM signal_snapshots WHERE created_at < ? LIMIT ?)",
                    (cutoff, batch_size),
                )
                conn.commit()
                count = cursor.rowcount
                if count <= 0:
                    break
                deleted_snapshots += count
                batches += 1
                time.sleep(0.05)
        return {"deleted": deleted, "deleted_snapshots": deleted_snapshots,
                "batches": batches, "cutoff": cutoff, "retention_days": days}

    def prune_order_flow(self, days: int = 7, batch_size: int = 500) -> Dict:
        """分批删除超期的订单流采样（N5 遗留项）。

        与写入使用同一 ISO 时间口径（含时区），保证字符串比较与时间顺序一致。
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
        deleted = 0
        batches = 0
        with self._connect(timeout=30) as conn:
            while True:
                cursor = conn.execute(
                    "DELETE FROM order_flow_snapshots WHERE id IN "
                    "(SELECT id FROM order_flow_snapshots WHERE created_at < ? LIMIT ?)",
                    (cutoff, batch_size),
                )
                conn.commit()
                count = cursor.rowcount
                if count <= 0:
                    break
                deleted += count
                batches += 1
                time.sleep(0.05)
        return {"deleted_orderflow": deleted, "batches": batches,
                "cutoff": cutoff, "retention_days": days}

    # ─── V3.0 Future Validator：prediction_results ────────

    def get_verifiable_predictions(self, older_than_iso: str, limit: int = 200,
                                   horizons: tuple = ("30m", "1h", "4h")) -> List[Dict]:
        """取仍有 horizon 未回验的预测（已全部完成的不再扫描，避免饥饿）"""
        missing_sql = " OR ".join(
            ["NOT EXISTS (SELECT 1 FROM prediction_results r "
             "WHERE r.prediction_id = p.id AND r.horizon = ?)" for _ in horizons]
        )
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""SELECT p.* FROM predictions p
                    WHERE p.verifiable = 1 AND p.created_at <= ?
                      AND ({missing_sql})
                    ORDER BY p.id ASC LIMIT ?""",
                (older_than_iso, *horizons, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def purge_stale_failed_results(self, older_than_iso: str) -> int:
        """删除超过重试间隔的 failed 结果，让其重新进入回验队列"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM prediction_results WHERE verify_status = 'failed' AND verified_at < ?",
                (older_than_iso,),
            )
            return cursor.rowcount

    def get_result_keys(self, prediction_ids: List[int]) -> Dict[tuple, str]:
        """批量取已存在的回验状态，避免重复请求行情"""
        if not prediction_ids:
            return {}
        marks = ",".join("?" for _ in prediction_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT prediction_id, horizon, verify_status FROM prediction_results "
                f"WHERE prediction_id IN ({marks})",
                prediction_ids,
            ).fetchall()
        return {(r[0], r[1]): r[2] for r in rows}

    def add_prediction_result(self, data: Dict) -> bool:
        """幂等写入回验结果；同一 (prediction_id, horizon) 只保留一条"""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO prediction_results
                   (prediction_id, symbol, horizon, price_type, entry_price, exit_price,
                    gross_return, estimated_cost, net_return, mfe, mae, outcome,
                    verify_status, data_quality, verified_at, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["prediction_id"], data["symbol"], data["horizon"],
                    data.get("price_type", "candle_close"),
                    data.get("entry_price"), data.get("exit_price"),
                    data.get("gross_return"), data.get("estimated_cost"), data.get("net_return"),
                    data.get("mfe"), data.get("mae"), data.get("outcome"),
                    data["verify_status"], data.get("data_quality"), data.get("verified_at"),
                    data.get("note"),
                ),
            )
            return cursor.rowcount > 0

    def query_prediction_results(self, symbol: Optional[str] = None, horizon: Optional[str] = None,
                                 status: Optional[str] = None, start: Optional[str] = None,
                                 end: Optional[str] = None, limit: int = 50,
                                 offset: int = 0) -> tuple:
        """回验结果查询（Dashboard 与人工核验共用）"""
        where = []
        params: List = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol)
        if horizon:
            where.append("horizon = ?")
            params.append(horizon)
        if status:
            where.append("verify_status = ?")
            params.append(status)
        if start:
            where.append("verified_at >= ?")
            params.append(start)
        if end:
            where.append("verified_at <= ?")
            params.append(end)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM prediction_results{where_sql}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM prediction_results{where_sql} "
                f"ORDER BY verified_at DESC, id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def _perf_where(self, symbol=None, start=None, end=None):
        where = ["p.verifiable = 1"]
        params: List = []
        if symbol:
            where.append("p.symbol = ?")
            params.append(symbol)
        if start:
            where.append("p.created_at >= ?")
            params.append(start)
        if end:
            where.append("p.created_at <= ?")
            params.append(end)
        return " WHERE " + " AND ".join(where), params

    PERF_AGG = """
        COUNT(DISTINCT p.id) AS predictions,
        COUNT(r.id) AS results,
        COALESCE(SUM(CASE WHEN r.verify_status = 'verified' THEN 1 ELSE 0 END), 0) AS verified,
        COALESCE(SUM(CASE WHEN r.outcome = 'WIN' THEN 1 ELSE 0 END), 0) AS wins,
        COALESCE(SUM(CASE WHEN r.outcome = 'LOSS' THEN 1 ELSE 0 END), 0) AS losses,
        COALESCE(SUM(CASE WHEN r.outcome = 'FLAT' THEN 1 ELSE 0 END), 0) AS flats,
        COALESCE(SUM(CASE WHEN r.verify_status = 'insufficient_data' THEN 1 ELSE 0 END), 0) AS insufficient_data,
        COALESCE(SUM(CASE WHEN r.verify_status = 'invalid' THEN 1 ELSE 0 END), 0) AS invalid,
        COALESCE(SUM(CASE WHEN r.verify_status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
        COUNT(DISTINCT CASE WHEN r.id IS NULL THEN p.id END) AS pending_predictions,
        AVG(CASE WHEN r.verify_status = 'verified' THEN r.net_return END) AS avg_net_return,
        AVG(CASE WHEN r.verify_status = 'verified' THEN r.gross_return END) AS avg_gross_return,
        SUM(CASE WHEN r.verify_status = 'verified' THEN r.net_return END) AS sum_net_return
    """

    @staticmethod
    def _finalize_perf(row: dict) -> dict:
        verified = row.get("verified") or 0
        wins = row.get("wins") or 0
        losses = row.get("losses") or 0
        row["win_rate"] = round(wins / verified * 100, 2) if verified else None
        row["directional_accuracy"] = round(wins / (wins + losses) * 100, 2) if (wins + losses) else None
        for key in ("avg_net_return", "avg_gross_return", "sum_net_return"):
            if row.get(key) is not None:
                row[key] = round(row[key] * 100, 3)  # 转为百分比
        return row

    def performance_summary(self, symbol: Optional[str] = None,
                            start: Optional[str] = None, end: Optional[str] = None) -> Dict:
        """预测绩效汇总：整体 + 按币种 + 按 horizon（只统计 verifiable 预测）"""
        where_sql, params = self._perf_where(symbol, start, end)
        base = ("FROM predictions p LEFT JOIN prediction_results r "
                "ON r.prediction_id = p.id" + where_sql)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            overall = dict(conn.execute(f"SELECT {self.PERF_AGG} {base}", params).fetchone())
            by_symbol = [dict(r) for r in conn.execute(
                f"SELECT p.symbol, {self.PERF_AGG} {base} GROUP BY p.symbol ORDER BY p.symbol", params)]
            by_horizon = [dict(r) for r in conn.execute(
                f"SELECT r.horizon, {self.PERF_AGG} {base} "
                f"AND r.id IS NOT NULL GROUP BY r.horizon ORDER BY r.horizon", params)]
        return {
            "overall": self._finalize_perf(overall),
            "by_symbol": [self._finalize_perf(r) for r in by_symbol],
            "by_horizon": [self._finalize_perf(r) for r in by_horizon],
            "definition": "胜率=WIN/已回验；方向准确率=WIN/(WIN+LOSS)；净收益已扣双边手续费与滑点",
        }

    def performance_detail(self, symbol: Optional[str] = None, horizon: Optional[str] = None,
                           status: Optional[str] = None, start: Optional[str] = None,
                           end: Optional[str] = None, limit: int = 50,
                           offset: int = 0) -> tuple:
        """预测 + 回验明细（同一条 prediction 的不同 horizon 各一行）"""
        where_sql, params = self._perf_where(symbol, start, end)
        extra = []
        if horizon:
            extra.append("r.horizon = ?")
            params.append(horizon)
        if status:
            extra.append("r.verify_status = ?")
            params.append(status)
        if extra:
            where_sql += " AND " + " AND ".join(extra)
        base = ("FROM predictions p LEFT JOIN prediction_results r "
                "ON r.prediction_id = p.id" + where_sql)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(f"SELECT COUNT(*) AS c {base}", params).fetchone()["c"]
            rows = conn.execute(
                f"""SELECT p.id AS prediction_id, p.created_at, p.symbol, p.direction, p.score,
                           p.level, p.regime, p.timeframe, p.price_type, p.price AS entry_price,
                           r.horizon, r.verify_status, r.outcome, r.exit_price, r.gross_return,
                           r.net_return, r.mfe, r.mae, r.data_quality, r.verified_at, r.note
                    {base}
                    ORDER BY p.created_at DESC, p.id DESC, r.horizon
                    LIMIT ? OFFSET ?""",
                params + [limit, offset],
            ).fetchall()
        items = []
        for row in rows:
            d = dict(row)
            for key in ("gross_return", "net_return", "mfe", "mae"):
                if d.get(key) is not None:
                    d[key] = round(d[key] * 100, 3)
            items.append(d)
        return items, total

    def cleanup_old(self, days: int = 30):
        """清理旧数据（保留最近 N 天）"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            conn.execute('''DELETE FROM signals WHERE created_at < ?''', (cutoff,))
            conn.execute('''DELETE FROM analysis_snapshots WHERE created_at < ?''', (cutoff,))
