"""影子评分：仅记录，不参与正式判断。"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.shadow_score import shadow_oi_score, shadow_snapshot  # noqa: E402


def test_zero_oi_scores_zero():
    assert shadow_oi_score("LONG", 0, 0) == 0
    assert shadow_oi_score("NEUTRAL", 0, 0) == 0


def test_no_change_keeps_official_baseline():
    # OI 变化不可用（窗口不足）时不再制造虚假差距，与正式分项持平
    assert shadow_oi_score("LONG", 0, 7) == 7
    assert shadow_oi_score("SHORT", 0, 7) == 7


def test_strength_adjusts_around_official_baseline():
    assert shadow_oi_score("LONG", 5, 7) == 15      # +8 上限
    assert shadow_oi_score("SHORT", 9, 7) == 15
    assert shadow_oi_score("LONG", 2.5, 7) == 11    # +4
    assert shadow_oi_score("LONG", -5, 7) == 3      # -4
    assert shadow_oi_score("LONG", 5, 20) == 20     # 不超过 20
    assert shadow_oi_score("NEUTRAL", 2.5, 7) == 7  # 中性不加成


def test_snapshot_does_not_mutate_official():
    analysis = SimpleNamespace(
        score=43, direction="LONG",
        components={"trend": 30, "momentum": 6, "volume": 4, "oi": 2, "funding": 1},
    )
    snap = shadow_snapshot(analysis, 2.5)
    assert analysis.score == 43
    assert snap["official_score"] == 43
    assert snap["official_oi_score"] == 2
    assert snap["shadow_oi_score"] == 6
    assert snap["shadow_score"] == 47


def test_shadow_persist_throttled():
    import tempfile
    from app.services.db_store import SignalDB

    with tempfile.TemporaryDirectory() as tmp:
        db = SignalDB(tmp)
        snap = {"official_score": 43, "shadow_score": 42, "official_oi_score": 2,
                "shadow_oi_score": 1, "direction": "LONG"}
        first = db.save_shadow_score("BTC-USDT", "15m", snap, 0.3)
        second = db.save_shadow_score("BTC-USDT", "15m", snap, 0.3)
        assert first is not None
        assert second is None  # 5 分钟节流


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
