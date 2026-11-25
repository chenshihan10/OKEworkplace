"""live_account.db 的离线自证：迁移幂等、成交去重、游标、配置缓存、保留清理。"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.account_store import AccountStore  # noqa: E402


def _fill(index, inst_id="BTC-USDT-SWAP"):
    return {
        "inst_id": inst_id,
        "trade_id": str(index),
        "ord_id": "ord-%d" % index,
        "side": "buy",
        "pos_side": "long",
        "px": 60000.0 + index,
        "sz": 1.0,
        "fee": -0.5,
        "fee_ccy": "USDT",
        "ts": index * 1000,
        "raw": {"tradeId": str(index)},
    }


def test_migration_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        AccountStore(tmp)
        store = AccountStore(tmp)
        with store._conn() as conn:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
        assert {"account_snapshots", "position_snapshots", "account_fills",
                "account_config_cache", "account_sync_state"} <= tables
        assert mode == "wal"
        assert os.path.exists(store.db_path)


def test_fills_dedupe_and_pagination():
    with tempfile.TemporaryDirectory() as tmp:
        store = AccountStore(tmp)
        rows = [_fill(1), _fill(2), _fill(3, "ETH-USDT-SWAP")]
        assert store.upsert_fills(rows) == 3
        # 同一批重复写入必须全部忽略
        assert store.upsert_fills(rows) == 0
        assert store.last_fill_ts() == 3000

        page = store.get_fills(limit=10)
        assert page["total"] == 3
        assert page["items"][0]["ts"] == 3000
        assert page["items"][0]["ts_iso"].startswith("1970-01-01T00:00:03")

        filtered = store.get_fills(limit=10, inst_id="ETH-USDT-SWAP")
        assert filtered["total"] == 1
        assert filtered["items"][0]["inst_id"] == "ETH-USDT-SWAP"

        offset_page = store.get_fills(limit=1, offset=1)
        assert len(offset_page["items"]) == 1
        assert offset_page["total"] == 3


def test_sync_state_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        store = AccountStore(tmp)
        assert store.get_state("fills_cursor") is None
        store.set_state("fills_cursor", "1700000000000")
        assert store.get_state("fills_cursor") == "1700000000000"
        store.set_state("fills_cursor", "1700000001000")
        assert store.get_state("fills_cursor") == "1700000001000"


def test_config_cache_single_row():
    with tempfile.TemporaryDirectory() as tmp:
        store = AccountStore(tmp)
        assert store.get_config() is None
        store.save_config({"acct_lv": "2", "pos_mode": "long_short_mode",
                           "updated_at": "2026-01-01T00:00:00+00:00"})
        store.save_config({"acct_lv": "3", "pos_mode": "net_mode",
                           "updated_at": "2026-01-02T00:00:00+00:00"})
        config = store.get_config()
        assert config["acct_lv"] == "3"
        assert config["pos_mode"] == "net_mode"


def test_prune_keeps_recent_rows():
    with tempfile.TemporaryDirectory() as tmp:
        store = AccountStore(tmp)
        now = datetime.now(timezone.utc)
        store.save_account_snapshot({"total_eq": 1.0,
                                     "created_at": (now - timedelta(days=40)).isoformat()})
        store.save_account_snapshot({"total_eq": 2.0, "created_at": now.isoformat()})
        store.save_position_snapshots([{
            "inst_id": "BTC-USDT-SWAP", "pos_raw": 1.0, "pos_unit": "contract",
        }])
        with store._conn() as conn:
            conn.execute(
                "UPDATE position_snapshots SET created_at = ?",
                ((now - timedelta(days=40)).isoformat(),),
            )
        store.upsert_fills([_fill(1)])          # 1970 年，必然过期
        store.upsert_fills([{**_fill(9), "ts": int(now.timestamp() * 1000)}])

        result = store.prune(retention_days=30, fills_retention_days=365)
        assert result["snapshots"] == 1
        assert result["positions"] == 1
        assert result["fills"] == 1
        assert store.get_fills(limit=10)["total"] == 1
        assert store.stats()["counts"]["account_snapshots"] == 1


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
