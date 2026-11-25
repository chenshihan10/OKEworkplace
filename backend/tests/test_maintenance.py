"""订单流采样保留策略（N5）：分批删除超期行，保留期内数据不受影响。"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.db_store import SignalDB  # noqa: E402


def _seed(db: SignalDB, ages_days):
    """按给定“距今多少天”写入采样，返回行 id 列表。"""
    ids = []
    for age in ages_days:
        snapshot_id = db.save_order_flow_snapshot("BTC-USDT", 5, {"buy_volume": 1.0, "sell_volume": 2.0})
        created_at = (datetime.now(timezone.utc) - timedelta(days=age)).isoformat()
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE order_flow_snapshots SET created_at = ? WHERE id = ?",
                         (created_at, snapshot_id))
            conn.commit()
        ids.append(snapshot_id)
    return ids


def _count(db: SignalDB) -> int:
    with sqlite3.connect(db.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM order_flow_snapshots").fetchone()[0]


def test_prune_order_flow_keeps_recent_rows():
    tmp = tempfile.mkdtemp(prefix="oke_maint_")
    try:
        db = SignalDB(tmp)
        _seed(db, [10, 8, 2, 0])
        assert _count(db) == 4

        result = db.prune_order_flow(days=7, batch_size=2)
        assert result["deleted_orderflow"] == 2
        assert result["batches"] == 1
        assert _count(db) == 2

        # 再清一次没有可删的行，批次不复位为负数
        again = db.prune_order_flow(days=7, batch_size=2)
        assert again["deleted_orderflow"] == 0
        assert again["batches"] == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_prune_order_flow_is_batched():
    tmp = tempfile.mkdtemp(prefix="oke_maint_")
    try:
        db = SignalDB(tmp)
        _seed(db, [9] * 5)
        result = db.prune_order_flow(days=7, batch_size=2)
        assert result["deleted_orderflow"] == 5
        assert result["batches"] == 3
        assert _count(db) == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("FAIL", name, "->", exc)
    raise SystemExit(1 if failures else 0)
