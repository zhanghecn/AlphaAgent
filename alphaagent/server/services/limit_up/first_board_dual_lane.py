"""Point-in-time first-board continuation and rotation shadow research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.domain import is_eligible_main_board

SHANGHAI = ZoneInfo("Asia/Shanghai")
ROTATION_FORWARD_START = date(2026, 7, 13)
ROTATION_TRIGGER_DISTANCE_PCT = 1.0
ROTATION_EXECUTION_EFFECT = "none_research_only"
ACTIVE_SESSION_STAGES = frozenset(
    {"auction_watch", "auction", "morning", "afternoon", "tail", "close_auction"}
)
STATE_PRIORITY = {
    "unavailable": 0,
    "rejected": 1,
    "watch": 2,
    "missed": 3,
    "trigger": 4,
}
REASON_LABELS = {
    "snapshot_not_live": "不是实时盘中快照",
    "snapshot_stale": "快照已陈旧",
    "snapshot_time_invalid": "快照时间无效",
    "snapshot_date_mismatch": "快照日期与交易日不一致",
    "not_trade_weekday": "不是交易工作日",
    "session_not_active": "不在可观察交易时段",
    "not_main_board_first_board": "不是主板首板",
    "concept_group_unavailable": "点时概念组缺失",
    "concept_trend_unavailable": "概念趋势缺失",
    "concept_rotation_not_confirmed": "概念未处于轮动状态",
    "concept_flow_date_unavailable": "概念资金日期缺失",
    "concept_flow_date_mismatch": "概念资金不是当日数据",
    "concept_flow_unavailable": "概念资金数据缺失",
    "concept_flow_not_positive": "概念主力资金未净流入",
    "dynamic_leader_unavailable": "动态龙头排名缺失",
    "not_dynamic_top2": "不是概念动态龙一龙二",
    "concept_diffusion_unavailable": "概念扩散数据缺失",
    "concept_diffusion_insufficient": "同概念触板不足两只",
    "first_seen_after_seal": "首次发现时已经封板，错过不追",
    "preseal_observation_unconfirmed": "尚未确认封板前已观察到",
    "distance_to_limit_unavailable": "距板数据缺失",
    "waiting_near_limit_trigger": "已预热，等待进入距板1%触发区",
    "waiting_reseal_trigger": "已触板，等待可观察回封触发",
    "board_already_sealed": "已经封住，不按影子买点追板",
    "rotation_trigger_ready": "概念轮动、扩散和动态龙头同时确认",
}


def evaluate_rotation_shadow(
    snapshot: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Classify one candidate using only fields visible in its saved snapshot."""

    envelope_reasons = _snapshot_rejection_reasons(snapshot)
    if envelope_reasons:
        return _classification("unavailable", envelope_reasons, snapshot, candidate)

    evidence_reasons = _candidate_evidence_rejections(snapshot, candidate)
    if evidence_reasons:
        state = "unavailable" if _has_unavailable_reason(evidence_reasons) else "rejected"
        return _classification(state, evidence_reasons, snapshot, candidate)

    if candidate.get("missed_preseal_entry") is True or (
        str(candidate.get("state") or "") in {"sealed", "resealed"}
        and candidate.get("seen_before_seal") is not True
    ):
        return _classification("missed", ["first_seen_after_seal"], snapshot, candidate)
    if candidate.get("seen_before_seal") is not True:
        return _classification(
            "unavailable",
            ["preseal_observation_unconfirmed"],
            snapshot,
            candidate,
        )

    state = str(candidate.get("state") or "")
    if state == "near_limit":
        distance = _number(candidate.get("distance_to_limit_pct"))
        if distance is None:
            return _classification(
                "unavailable",
                ["distance_to_limit_unavailable"],
                snapshot,
                candidate,
            )
        if distance <= ROTATION_TRIGGER_DISTANCE_PCT:
            return _classification(
                "trigger",
                ["rotation_trigger_ready"],
                snapshot,
                candidate,
                passed=True,
            )
        return _classification(
            "watch",
            ["waiting_near_limit_trigger"],
            snapshot,
            candidate,
        )
    if state == "failed":
        return _classification(
            "watch",
            ["waiting_reseal_trigger"],
            snapshot,
            candidate,
        )
    return _classification(
        "watch",
        ["board_already_sealed"],
        snapshot,
        candidate,
    )


def attach_rotation_shadow(
    candidates: Sequence[Mapping[str, object]],
    snapshot: Mapping[str, object],
) -> list[dict[str, object]]:
    """Return copies with additive rotation fields on first-board candidates only."""

    result: list[dict[str, object]] = []
    for raw in candidates:
        candidate = dict(raw)
        if str(candidate.get("board_lane") or "") == "first_board":
            candidate.update(evaluate_rotation_shadow(snapshot, candidate))
        result.append(candidate)
    return result


def collect_rotation_forward_evidence(
    snapshots: Sequence[Mapping[str, object]],
    *,
    forward_start: date | str = ROTATION_FORWARD_START,
) -> dict[str, object]:
    """Extract each symbol's first real trigger; historical proxies are ignored."""

    start = _date_or_none(forward_start) or ROTATION_FORWARD_START
    trigger_by_key: dict[tuple[str, str], dict[str, object]] = {}
    observation_by_key: dict[tuple[str, str], dict[str, object]] = {}
    valid_snapshot_times: set[str] = set()
    snapshot_dates: set[str] = set()
    evaluated_count = 0

    for snapshot in sorted(snapshots, key=_snapshot_sort_key):
        trade_date = _date_or_none(snapshot.get("trade_date"))
        if trade_date is None or trade_date < start:
            continue
        if _snapshot_rejection_reasons(snapshot):
            continue
        valid_snapshot_times.add(str(snapshot.get("captured_at") or ""))
        snapshot_dates.add(trade_date.isoformat())
        candidates = snapshot.get("candidates")
        candidates = candidates if isinstance(candidates, Sequence) else []
        for raw in candidates:
            if not isinstance(raw, Mapping):
                continue
            candidate = dict(raw)
            if str(candidate.get("board_lane") or "") != "first_board":
                continue
            evaluated_count += 1
            classified = evaluate_rotation_shadow(snapshot, candidate)
            key = (trade_date.isoformat(), str(candidate.get("vt_symbol") or ""))
            observation = _observation_row(snapshot, candidate, classified)
            previous = observation_by_key.get(key)
            if previous is None or _state_priority(observation) > _state_priority(previous):
                observation_by_key[key] = observation
            if classified["rotation_shadow_passed"] is True and key not in trigger_by_key:
                trigger_by_key[key] = _trigger_signal(snapshot, candidate, classified)

    observations = sorted(
        observation_by_key.values(),
        key=lambda row: (
            str(row.get("trade_date") or ""),
            str(row.get("signal_time") or ""),
            str(row.get("vt_symbol") or ""),
        ),
    )
    trigger_signals = sorted(
        trigger_by_key.values(),
        key=lambda row: (
            str(row.get("entry_date") or ""),
            str(row.get("signal_time") or ""),
            str(row.get("vt_symbol") or ""),
        ),
    )
    return {
        "status": "collecting" if trigger_signals else "waiting_for_real_trigger",
        "forward_start_date": start.isoformat(),
        "historical_substitution": False,
        "snapshot_count": len(valid_snapshot_times),
        "snapshot_day_count": len(snapshot_dates),
        "evaluated_candidate_count": evaluated_count,
        "watch_count": sum(row.get("state") == "watch" for row in observations),
        "missed_count": sum(row.get("state") == "missed" for row in observations),
        "trigger_count": len(trigger_signals),
        "trigger_signals": trigger_signals,
        "recent_observations": observations[-20:],
    }


def _candidate_evidence_rejections(
    snapshot: Mapping[str, object],
    candidate: Mapping[str, object],
) -> list[str]:
    symbol = str(candidate.get("vt_symbol") or "")
    name = str(candidate.get("name") or "")
    if (
        str(candidate.get("board_lane") or "") != "first_board"
        or _integer(candidate.get("board_level")) != 1
        or not is_eligible_main_board(symbol, name)
    ):
        return ["not_main_board_first_board"]

    reasons: list[str] = []
    if not str(candidate.get("warmup_group") or "").strip():
        reasons.append("concept_group_unavailable")
    trend_state = str(candidate.get("warmup_trend_state") or "").upper()
    if not trend_state:
        reasons.append("concept_trend_unavailable")
    elif trend_state != "ROTATION":
        reasons.append("concept_rotation_not_confirmed")

    trade_date = _date_or_none(snapshot.get("trade_date"))
    flow_date = _date_or_none(candidate.get("warmup_flow_trade_date"))
    if flow_date is None:
        reasons.append("concept_flow_date_unavailable")
    elif flow_date != trade_date:
        reasons.append("concept_flow_date_mismatch")
    inflow = _number(candidate.get("warmup_main_net_inflow"))
    inflow_ratio = _number(candidate.get("warmup_main_net_inflow_ratio"))
    if inflow is None or inflow_ratio is None:
        reasons.append("concept_flow_unavailable")
    elif inflow <= 0 or inflow_ratio <= 0:
        reasons.append("concept_flow_not_positive")

    leader_rank = _integer(candidate.get("warmup_leader_rank"))
    if leader_rank is None:
        reasons.append("dynamic_leader_unavailable")
    elif leader_rank > 2:
        reasons.append("not_dynamic_top2")
    touch_count = _integer(candidate.get("warmup_touch_count"))
    if touch_count is None:
        reasons.append("concept_diffusion_unavailable")
    elif touch_count < 2:
        reasons.append("concept_diffusion_insufficient")
    return reasons


def _snapshot_rejection_reasons(snapshot: Mapping[str, object]) -> list[str]:
    reasons: list[str] = []
    if str(snapshot.get("mode") or "") != "live_snapshot":
        reasons.append("snapshot_not_live")
    quality = snapshot.get("data_quality")
    if not isinstance(quality, Mapping) or quality.get("is_stale") is not False:
        reasons.append("snapshot_stale")
    captured_at = _datetime_or_none(snapshot.get("captured_at"))
    trade_date = _date_or_none(snapshot.get("trade_date"))
    if captured_at is None or trade_date is None:
        reasons.append("snapshot_time_invalid")
    else:
        if captured_at.astimezone(SHANGHAI).date() != trade_date:
            reasons.append("snapshot_date_mismatch")
        if trade_date.weekday() >= 5:
            reasons.append("not_trade_weekday")
    if str(snapshot.get("session_stage") or "") not in ACTIVE_SESSION_STAGES:
        reasons.append("session_not_active")
    return reasons


def _classification(
    state: str,
    reasons: Sequence[str],
    snapshot: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    passed: bool = False,
) -> dict[str, object]:
    reason_labels = [REASON_LABELS.get(reason, reason) for reason in reasons]
    captured_at = _datetime_or_none(snapshot.get("captured_at"))
    return {
        "rotation_shadow_state": state,
        "rotation_shadow_passed": passed,
        "rotation_shadow_reason_codes": list(reasons),
        "rotation_shadow_reason": "；".join(reason_labels),
        "rotation_shadow_signal_time": (
            captured_at.astimezone(SHANGHAI).time().replace(microsecond=0).isoformat()
            if captured_at is not None
            else None
        ),
        "rotation_shadow_entry_price": (
            _number(candidate.get("limit_price")) if passed else None
        ),
        "rotation_shadow_execution_effect": ROTATION_EXECUTION_EFFECT,
    }


def _trigger_signal(
    snapshot: Mapping[str, object],
    candidate: Mapping[str, object],
    classified: Mapping[str, object],
) -> dict[str, object]:
    trade_date = str(snapshot.get("trade_date") or "")[:10]
    signal_time = str(classified.get("rotation_shadow_signal_time") or "")
    return {
        **dict(candidate),
        **dict(classified),
        "lane": "first_board",
        "entry_date": trade_date,
        "signal_date": trade_date,
        "signal_time": signal_time,
        "buy_time": signal_time,
        "signal_kind": "intraday_rotation_shadow",
        "entry_price": classified.get("rotation_shadow_entry_price"),
        "result_date": None,
        "source_mode": "real_intraday_snapshot",
    }


def _observation_row(
    snapshot: Mapping[str, object],
    candidate: Mapping[str, object],
    classified: Mapping[str, object],
) -> dict[str, object]:
    return {
        "trade_date": str(snapshot.get("trade_date") or "")[:10],
        "signal_time": classified.get("rotation_shadow_signal_time"),
        "vt_symbol": candidate.get("vt_symbol"),
        "name": candidate.get("name"),
        "concept_name": candidate.get("warmup_group_name"),
        "state": classified.get("rotation_shadow_state"),
        "reason": classified.get("rotation_shadow_reason"),
    }


def _state_priority(row: Mapping[str, object]) -> int:
    return STATE_PRIORITY.get(str(row.get("state") or ""), -1)


def _has_unavailable_reason(reasons: Sequence[str]) -> bool:
    return any(
        reason.endswith("_unavailable")
        or reason in {"snapshot_time_invalid", "preseal_observation_unconfirmed"}
        for reason in reasons
    )


def _snapshot_sort_key(snapshot: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(snapshot.get("trade_date") or ""),
        str(snapshot.get("captured_at") or ""),
    )


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)


def _date_or_none(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
