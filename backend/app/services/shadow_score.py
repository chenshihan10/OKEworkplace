"""影子评分：仅用于记录对比，不参与正式 score/direction/level/risk 的任何判断。

差异点只有 OI 维度：正式 `_score_oi` 对「非零 OI + 方向」几乎无条件给出 8 分，
这里改为按 |OI 变化| 分档给分，变化越大得分越高，最大仍为 20 分。
冻结区文件不做任何修改，本模块独立计算影子总分。
"""
from typing import Dict


def shadow_oi_score(direction: str, oi_change_pct: float) -> int:
    """强度感知的 OI 分（0-20）。

    strength = min(|OI| / 5%, 1)
    - 幅度分：12 * strength
    - 配合分：OI 增加 8*strength；OI 减少 4*strength；OI=0 为 0
    - 中性方向：3 * strength
    """
    oi = float(oi_change_pct or 0)
    strength = min(abs(oi) / 5.0, 1.0)
    if strength <= 0:
        return 0
    if direction == "LONG" or direction == "SHORT":
        align = 8.0 if oi > 0 else 4.0 if oi < 0 else 0.0
    else:
        align = 3.0
    return min(int(round(12.0 * strength + align * strength)), 20)


def shadow_snapshot(analysis, oi_change_pct: float) -> Dict:
    """返回影子评分快照；正式评分字段原样带回，便于同表对照。"""
    components = dict(getattr(analysis, "components", {}) or {})
    official_oi = int(components.get("oi", 0) or 0)
    shadow_oi = shadow_oi_score(analysis.direction, oi_change_pct)
    shadow_total = int(analysis.score or 0) - official_oi + shadow_oi
    return {
        "official_score": int(analysis.score or 0),
        "shadow_score": max(0, min(100, shadow_total)),
        "official_oi_score": official_oi,
        "shadow_oi_score": shadow_oi,
        "direction": analysis.direction,
    }
