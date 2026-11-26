"""应用启动隔离：测试环境启动 FastAPI 时不注册调度器，因而不发起任何外部请求。

必须在导入 app.main 之前设置 OKE_DISABLE_SCHEDULER=1。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["OKE_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.core import scheduler as scheduler_module  # noqa: E402
from app.main import app  # noqa: E402


def test_startup_skips_scheduler_when_disabled():
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert scheduler_module.scheduler.running is False
        assert scheduler_module.scheduler.get_jobs() == []

        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # 账户只读任务也未注册：不存在私有只读刷新
        job_ids = {job.id for job in scheduler_module.scheduler.get_jobs()}
        assert not any("account" in job_id for job_id in job_ids)


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
