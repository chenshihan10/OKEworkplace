"""OI 变化口径：15m/1H 窗口变化率（单位测试，不依赖网络）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.market_service import calc_oi_change_pct  # noqa: E402


def test_empty_samples():
    assert calc_oi_change_pct([], 1000.0, 900) == 0.0


def test_window_not_covered():
    # 只有 100 秒历史，不足 15 分钟窗口的 90%
    samples = [(900.0, 100.0), (1000.0, 110.0)]
    assert calc_oi_change_pct(samples, 1000.0, 900) == 0.0


def test_15m_change():
    samples = [(0.0, 100.0), (300.0, 110.0), (900.0, 120.0)]
    assert calc_oi_change_pct(samples, 900.0, 900) == 20.0


def test_picks_latest_sample_at_or_before_target():
    samples = [(0.0, 100.0), (400.0, 105.0), (901.0, 120.0)]
    # now=1300, lookback=900 → target=400，应取 105 而不是 100
    assert calc_oi_change_pct(samples, 1300.0, 900) == round((120 - 105) / 105 * 100, 4)


def test_zero_current_oi():
    samples = [(0.0, 100.0), (900.0, 0.0)]
    assert calc_oi_change_pct(samples, 900.0, 900) == 0.0


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
