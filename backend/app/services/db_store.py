"""v2.2 SQLite 信号持久化存储"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
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
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
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
            self._create_indexes(conn)

    @staticmethod
    def _create_indexes(conn):
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_analysis_symbol ON analysis_snapshots(symbol)''')

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

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                '''INSERT INTO signals (symbol, direction, raw_direction, score, confidence, level, risk,
                   mark_price, index_price, price, data_source, raw_signal, decision_trace)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (symbol, direction, raw_direction, score, 0, level, risk,
                 mark_price, index_price, price, data_source,
                 raw_signal_json, decision_trace_json)
            )
            return cursor.lastrowid

    def save_analysis_snapshot(self, symbol: str, components: dict, trend_phase: str = "") -> int:
        """保存分析快照"""
        with sqlite3.connect(self.db_path) as conn:
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

    def get_recent_signals(self, symbol: str, limit: int = 50) -> List[Dict]:
        """获取最近的信号历史"""
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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

    def cleanup_old(self, days: int = 30):
        """清理旧数据（保留最近 N 天）"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''DELETE FROM signals WHERE created_at < ?''', (cutoff,))
            conn.execute('''DELETE FROM analysis_snapshots WHERE created_at < ?''', (cutoff,))
