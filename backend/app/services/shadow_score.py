"""影子评分：仅用于记录对比，不参与正式 score/direction/level/risk 的任何判断。

本轮修正的是「OI 输入口径」，不是正式评分：
  旧实现只拿到 |OI 变化率|，窗口不足时变化率为 0，影子 OI 直接被记 0 分，
  而正式 `_score_oi` 只要 OI 非零就给基础分（约 7），导致影子总分长期恒定低 5~6 分，
  这种差异来自「输入缺失」而不是「方法不同」，对照实验没有信息量。

  现在影子以正式 OI 分项为基准，再按 OI 变化强度做加减：
    - OI 上升：最多 +8（站上同一量纲，变化越强分越高）
    - OI 下降：最多 -4
    - 变化不可用（窗口不足 / 缺失）：与正式分项持平，不再制造虚假差距
  仍限制在 0~20，冻结区文件不做任何修改。
"""
from typing import Dict


def shadow_oi_score(direction: str, oi_change_pct: float, official_oi: int = 0) -> int:
    """以正式 OI 分项为基准、按变化强度加减的影子 OI 分（0-20）。

    strength = min(|OI| / 5%, 1)
    """
    official_oi = int(official_oi or 0)
    if official_oi <= 0:
        return 0
    oi = float(oi_change_pct or 0)
    strength = min(abs(oi) / 5.0, 1.0)
    if direction == "LONG" or direction == "SHORT":
        delta = (8.0 if oi > 0 else -4.0 if oi < 0 else 0.0) * strength
    else:
        delta = 0.0
    return int(max(0, min(20, round(official_oi + delta))))


def shadow_snapshot(analysis, oi_change_pct: float) -> Dict:
    """返回影子评分快照；正式评分字段原样带回，便于同表对照。"""
    components = dict(getattr(analysis, "components", {}) or {})
    official_oi = int(components.get("oi", 0) or 0)
    shadow_oi = shadow_oi_score(analysis.direction, oi_change_pct, official_oi)
    shadow_total = int(analysis.score or 0) - official_oi + shadow_oi
    return {
        "official_score": int(analysis.score or 0),
        "shadow_score": max(0, min(100, shadow_total)),
        "official_oi_score": official_oi,
        "shadow_oi_score": shadow_oi,
        "direction": analysis.direction,
    }
