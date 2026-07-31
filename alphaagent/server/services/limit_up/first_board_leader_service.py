"""First-board leader strength tracker (read-only view over the live snapshot).

盘中实时跟踪首板强度——哪只首板涨得最猛、最接近封板、封单最实、概念龙排名
最靠前，就排前面。这是「跟踪强度」，不是「预测龙头」（首板当天分不出龙头）。

只读现有 10 秒实时快照（``get_latest_live_snapshot``），过滤 first_board + 按
实时强度排序，绝不新建扫描、不改 snapshot 构建。
"""

from __future__ import annotations

from collections.abc import Mapping

from alphaagent.server.services.limit_up.live_service import get_latest_live_snapshot

LEADER_LIMIT = 20


def build_first_board_leader_snapshot() -> dict[str, object]:
    """读取最新实时快照并返回首板龙头强度榜。"""

    return select_first_board_leaders(get_latest_live_snapshot())


def select_first_board_leaders(
    snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    """从实时快照过滤 first_board + 按实时强度排序，返回 top ``LEADER_LIMIT``。"""

    if not snapshot:
        return _empty_leader_snapshot()
    recommendations = snapshot.get("recommendations") or {}
    lanes = (recommendations.get("lanes") or {}) if isinstance(recommendations, Mapping) else {}
    now_signals = lanes.get("now") or []
    first_boards = [
        signal
        for signal in now_signals
        if str(signal.get("board_lane") or "") == "first_board"
    ]
    first_boards.sort(key=_leader_strength_key, reverse=True)
    return {
        "trade_date": snapshot.get("trade_date"),
        "captured_at": snapshot.get("captured_at"),
        "session_stage": snapshot.get("session_stage"),
        "mode": snapshot.get("mode"),
        "data_quality": snapshot.get("data_quality") or {},
        "leaders": first_boards[:LEADER_LIMIT],
    }


def _empty_leader_snapshot() -> dict[str, object]:
    return {
        "trade_date": None,
        "captured_at": None,
        "session_stage": None,
        "mode": None,
        "data_quality": {},
        "leaders": [],
    }


def _leader_strength_key(signal: Mapping[str, object]) -> tuple[float, float, float, float]:
    """强度排序：涨幅高 > 距板近 > 概念龙前 > 封单大。"""

    change = _num(signal.get("change_pct")) or 0.0
    distance = _num(signal.get("distance_to_limit_pct"))
    seal = _num(signal.get("seal_amount")) or 0.0
    concept_rank = _num(signal.get("concept_leader_rank"))
    return (
        change,
        -(distance if distance is not None else 999.0),
        -(concept_rank if concept_rank is not None else 9999.0),
        seal,
    )


def _num(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
