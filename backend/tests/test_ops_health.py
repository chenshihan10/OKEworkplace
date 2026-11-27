"""运维加固回归：数据停更告警判定、数据库自检、/health 富字段。"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["OKE_DISABLE_SCHEDULER"] = "1"

from app.services.db_integrity import quick_check  # noqa: E402
from app.services.health_monitor import should_alert_stale  # noqa: E402


def test_should_alert_stale_threshold_and_cooldown():
    assert should_alert_stale(None, 300, None, 1000) is False
    assert should_alert_stale(100, 300, None, 1000) is False
    assert should_alert_stale(301, 300, None, 1000) is True
    # 冷却期内不重复提醒
    assert should_alert_stale(301, 300, 950, 1000) is False
    assert should_alert_stale(301, 300, 300, 1000) is True
    # 阈值为 0 视为关闭告警
    assert should_alert_stale(999, 0, None, 1000) is False


def test_quick_check_ok_missing_and_corrupt():
    tmpdir = tempfile.mkdtemp(prefix="oke_dbc_")
    ok_path = os.path.join(tmpdir, "ok.db")
    conn = sqlite3.connect(ok_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t DEFAULT VALUES")
    conn.commit()
    conn.close()
    assert quick_check(ok_path, force=True)["ok"] is True

    missing = os.path.join(tmpdir, "missing.db")
    result = quick_check(missing, force=True)
    assert result["ok"] is True and result["detail"] == "missing"

    bad_path = os.path.join(tmpdir, "bad.db")
    with open(bad_path, "wb") as f:
        f.write(b"not a sqlite database" * 64)
    assert quick_check(bad_path, force=True)["ok"] is False


def test_health_payload_has_freshness_and_db_fields():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "version" in body and "degraded" in body
    assert "data_age_seconds" in body and "uptime_seconds" in body
    assert isinstance(body.get("db"), dict) and "ok" in body["db"]
