"""Pure sector-warmup research rules for low first boards."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha1
from math import log1p

MIN_SHARED_STOCKS = 5
MIN_JACCARD = 0.35
MIN_SMALLER_SET_COVERAGE = 0.70
WARMUP_EXECUTION_EFFECT = "none_research_only"

STYLE_SECTOR_KEYWORDS = (
    "昨日",
    "近期",
    "涨停",
    "连板",
    "高换手",
    "融资融券",
    "沪股通",
    "深股通",
    "机构重仓",
    "基金重仓",
    "成份股",
    "成分股",
    "HS300",
    "标准普尔",
)


def group_concepts(
    memberships: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Group highly overlapping concepts with deterministic connected components."""

    members_by_sector: dict[str, set[str]] = defaultdict(set)
    names_by_sector: dict[str, str] = {}
    for row in memberships:
        sector_type = str(row.get("sector_type") or "").lower()
        sector_id = str(row.get("sector_id") or "").strip()
        sector_name = str(row.get("sector_name") or sector_id).strip()
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        if (
            sector_type not in {"concept", "theme"}
            or not sector_id
            or not symbol
            or _is_style_sector(sector_name)
        ):
            continue
        members_by_sector[sector_id].add(symbol)
        names_by_sector[sector_id] = sector_name

    sector_ids = sorted(members_by_sector)
    parents = {sector_id: sector_id for sector_id in sector_ids}
    for index, left_id in enumerate(sector_ids):
        for right_id in sector_ids[index + 1 :]:
            if _concepts_overlap(
                members_by_sector[left_id],
                members_by_sector[right_id],
            ):
                _union(parents, left_id, right_id)

    components: dict[str, list[str]] = defaultdict(list)
    for sector_id in sector_ids:
        components[_find(parents, sector_id)].append(sector_id)

    groups: list[dict[str, object]] = []
    for component in components.values():
        ids = sorted(component)
        symbols = sorted(
            set().union(*(members_by_sector[sector_id] for sector_id in ids))
        )
        names = [names_by_sector[sector_id] for sector_id in ids]
        groups.append(
            {
                "group_id": _group_id(ids),
                "group_name": " / ".join(names[:3]),
                "sector_ids": ids,
                "sector_names": names,
                "member_symbols": symbols,
                "member_count": len(symbols),
                "source": "point_in_time_membership_overlap_v1",
            }
        )
    return sorted(groups, key=lambda group: str(group["group_id"]))


def historical_warmup_proxy(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Classify the existing D-1 industry proxy without changing eligibility."""

    change_pct = _candidate_number(candidate, "prior_industry_change_pct")
    advancing_rate = _candidate_number(candidate, "prior_industry_advancing_rate")
    turnover_ratio = _candidate_number(candidate, "prior_industry_turnover_ratio_5d")
    components = {
        "change_pct": change_pct,
        "advancing_rate": advancing_rate,
        "turnover_ratio_5d": turnover_ratio,
    }
    if None in components.values():
        return {
            "available": False,
            "confirmed": False,
            "state": "unavailable",
            "score": None,
            "execution_effect": WARMUP_EXECUTION_EFFECT,
            "components": components,
        }

    score = round(
        _scaled(change_pct, 0.0, 3.0) * 35
        + _scaled(advancing_rate, 0.30, 0.80) * 35
        + _scaled(turnover_ratio, 0.70, 1.50) * 30,
        4,
    )
    confirmed = bool(
        change_pct > 0 and advancing_rate >= 0.50 and turnover_ratio >= 1.0
    )
    if change_pct < 0:
        state = "ebb"
    elif confirmed and score >= 70:
        state = "launch"
    elif confirmed:
        state = "warming"
    elif score >= 40:
        state = "observe"
    else:
        state = "cold"
    return {
        "available": True,
        "confirmed": confirmed,
        "state": state,
        "score": score,
        "execution_effect": WARMUP_EXECUTION_EFFECT,
        "components": components,
    }


def live_warmup_observation(
    contexts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Choose the strongest observable concept context as a live shadow tag."""

    observations = [
        observation
        for context in contexts
        if (observation := _live_context_observation(context)) is not None
    ]
    if not observations:
        return {
            "available": False,
            "group_id": None,
            "group_name": None,
            "state": "unavailable",
            "score": None,
            "confidence": "insufficient_point_in_time_data",
            "execution_effect": WARMUP_EXECUTION_EFFECT,
        }
    return max(
        observations,
        key=lambda item: (
            _number(item.get("score")) or -1.0,
            _number(item.get("main_net_inflow")) or float("-inf"),
            str(item.get("group_id") or ""),
        ),
    )


def attach_dynamic_group_leader_ranks(
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach additive first-board shadow ranks without mutating lane decisions."""

    result = [dict(candidate) for candidate in candidates]
    grouped: dict[str, list[tuple[int, dict[str, object]]]] = defaultdict(list)
    for index, candidate in enumerate(result):
        if str(candidate.get("board_lane") or "") != "first_board":
            continue
        group_id = str(candidate.get("warmup_group") or "").strip()
        if group_id:
            grouped[group_id].append((index, candidate))

    for rows in grouped.values():
        ordered = sorted(
            rows,
            key=lambda item: (
                -_dynamic_leader_score(item[1]),
                str(item[1].get("vt_symbol") or ""),
            ),
        )
        for rank, (index, _) in enumerate(ordered, start=1):
            result[index]["warmup_leader_rank"] = rank
            result[index]["warmup_execution_effect"] = WARMUP_EXECUTION_EFFECT
    return result


def _concepts_overlap(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    shared = len(left & right)
    if shared < MIN_SHARED_STOCKS:
        return False
    union_size = len(left | right)
    smaller_size = min(len(left), len(right))
    return (
        shared / union_size >= MIN_JACCARD
        and shared / smaller_size >= MIN_SMALLER_SET_COVERAGE
    )


def _live_context_observation(
    context: Mapping[str, object],
) -> dict[str, object] | None:
    heat_score = _number(context.get("heat_score"))
    flow_ratio = _number(context.get("main_net_inflow_ratio"))
    main_net_inflow = _number(context.get("main_net_inflow"))
    if heat_score is None and flow_ratio is None and main_net_inflow is None:
        return None
    heat_score = heat_score if heat_score is not None else 0.0
    flow_adjustment = max(min((flow_ratio or 0.0) * 2.0, 10.0), -15.0)
    score = round(max(min(heat_score + flow_adjustment, 100.0), 0.0), 4)
    trend_state = str(context.get("trend_state") or "").lower()
    if trend_state in {"broken", "ebb", "retreat", "decline"} or (
        (flow_ratio or 0.0) < 0 and heat_score >= 55
    ):
        state = "ebb"
    elif score >= 85:
        state = "crowded"
    elif score >= 70 and (flow_ratio is None or flow_ratio >= 0):
        state = "launch"
    elif score >= 55 and (flow_ratio is None or flow_ratio >= 0):
        state = "warming"
    elif score >= 40:
        state = "observe"
    else:
        state = "cold"
    sector_id = str(context.get("sector_id") or "")
    sector_name = str(context.get("sector_name") or sector_id)
    return {
        "available": True,
        "group_id": str(context.get("group_id") or sector_id),
        "group_name": str(context.get("group_name") or sector_name),
        "state": state,
        "score": score,
        "confidence": "point_in_time_proxy",
        "execution_effect": WARMUP_EXECUTION_EFFECT,
        "heat_score": round(heat_score, 4),
        "main_net_inflow": main_net_inflow,
        "main_net_inflow_ratio": flow_ratio,
        "trend_state": context.get("trend_state"),
        "sector_id": sector_id,
        "sector_name": sector_name,
    }


def _dynamic_leader_score(candidate: Mapping[str, object]) -> float:
    state_score = {
        "resealed": 24.0,
        "near_limit": 20.0,
        "sealed": 16.0,
        "failed": 0.0,
    }.get(str(candidate.get("state") or ""), 4.0)
    change_pct = max(min(_number(candidate.get("change_pct")) or 0.0, 10.0), -10.0)
    stock_flow_ratio = max(
        min(_number(candidate.get("stock_main_net_inflow_ratio")) or 0.0, 20.0),
        -20.0,
    )
    touch_gene = min(
        max(_number(candidate.get("prior_touch_count_126")) or 0.0, 0.0), 20.0
    )
    seal_amount = max(_number(candidate.get("seal_amount")) or 0.0, 0.0)
    return (
        state_score
        + change_pct * 2.0
        + stock_flow_ratio * 1.5
        + touch_gene
        + min(log1p(seal_amount) / 3.0, 8.0)
    )


def _candidate_number(candidate: Mapping[str, object], key: str) -> float | None:
    value = _number(candidate.get(key))
    if value is not None:
        return value
    known = candidate.get("known_at_signal")
    return _number(known.get(key)) if isinstance(known, Mapping) else None


def _is_style_sector(name: str) -> bool:
    normalized = name.upper()
    return any(keyword.upper() in normalized for keyword in STYLE_SECTOR_KEYWORDS)


def _group_id(sector_ids: Sequence[str]) -> str:
    digest = sha1(",".join(sector_ids).encode("ascii")).hexdigest()[:12]
    return f"CWG-{digest}"


def _find(parents: dict[str, str], value: str) -> str:
    while parents[value] != value:
        parents[value] = parents[parents[value]]
        value = parents[value]
    return value


def _union(parents: dict[str, str], left: str, right: str) -> None:
    left_root = _find(parents, left)
    right_root = _find(parents, right)
    if left_root == right_root:
        return
    parents[max(left_root, right_root)] = min(left_root, right_root)


def _scaled(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return max(min((value - lower) / (upper - lower), 1.0), 0.0)


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
