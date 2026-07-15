"""Continuous intraday first-board clock shared by replay and live views."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.lane_features import first_reseal_time

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v4"
MAX_POSITIONS = 2
TARGET_POSITION_PCT = 50.0
MAX_SNAPSHOT_AGE_SECONDS = 20
EXIT_TIME = "14:30:00"
ENTRY_WINDOWS = (("10:00:00", "11:30:00"), ("13:00:00", "14:30:00"))
RELAY_LANES = frozenset({"two_to_three", "high_board"})
RESEARCH_EXECUTION_LANES = ("first_board", "two_to_three", "high_board")
PRODUCT_EXECUTION_LANES = ("first_board", "two_to_three")
RESEARCH_SAMPLE_START = date(2026, 1, 16)
VALIDATION_START = date(2026, 4, 14)
RULE_FREEZE_DATE = date(2026, 7, 15)


def is_entry_time(value: object) -> bool:
    """Return whether a visible signal arrived during continuous evaluation."""

    time_text = _time_text(value)
    return any(start <= time_text < end for start, end in ENTRY_WINDOWS)


def resolve_relay_entry_trigger(
    first_limit_time: object,
    return_path: Sequence[object],
) -> dict[str, object]:
    """Resolve a relay entry without falling back to the auction open."""

    if first_limit_time in (None, ""):
        return _relay_trigger(
            "missing_first_touch",
            reason="first_touch_time_missing",
        )
    first_time = _time_text(first_limit_time)
    if is_entry_time(first_time):
        return _relay_trigger(
            "ready",
            signal_time=first_time,
            signal_kind="first_touch",
        )
    if first_time < "10:00:00":
        if not return_path:
            return _relay_trigger(
                "missing_reseal_path",
                reason="pre_ten_touch_without_reseal_path",
            )
        reseal_time = first_reseal_time(return_path, not_before="10:00:00")
        if reseal_time and is_entry_time(reseal_time):
            return _relay_trigger(
                "ready",
                signal_time=reseal_time,
                signal_kind="reseal",
            )
        return _relay_trigger(
            "no_window_reseal",
            reason="pre_ten_touch_without_window_reseal",
        )
    return _relay_trigger(
        "outside_entry_window",
        reason="first_touch_outside_entry_window",
    )


def _relay_trigger(
    status: str,
    *,
    signal_time: str | None = None,
    signal_kind: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "signal_time": signal_time,
        "signal_kind": signal_kind,
        "reason": reason,
    }


def execution_clock(captured_at: datetime) -> dict[str, object]:
    """Describe the current deterministic action window in Shanghai time."""

    local_at = _local_datetime(captured_at)
    clock = local_at.time().replace(microsecond=0)
    state: str
    message: str
    entry_allowed = False
    target: time | None = None

    if clock < time(9, 55):
        state, message, target = "waiting", "10:00开始连续盘中评估", time(10, 0)
    elif clock < time(10, 0):
        state, message, target = "entry_reminder", "买入窗口将在 10:00 开始", time(10, 0)
    elif clock < time(11, 30):
        state, message, entry_allowed, target = (
            "entry_window",
            "连续评估 10:00-11:30",
            True,
            time(11, 30),
        )
    elif clock < time(13, 0):
        state, message, target = "lunch_pause", "午间休市，13:00恢复连续评估", time(13, 0)
    elif clock < time(14, 25):
        state, message, entry_allowed, target = (
            "entry_window",
            "连续评估 13:00-14:30",
            True,
            time(14, 30),
        )
    elif clock < time(14, 30):
        state, message, entry_allowed, target = (
            "entry_exit_reminder",
            "继续评估至14:30，同时准备卖出D+1持仓",
            True,
            time(14, 30),
        )
    elif clock < time(15, 0):
        state, message = "exit_time", "卖出时间已到：执行 D+1 卖出清单"
    else:
        state, message = "closed", "今日执行已结束，下个交易日 09:55 提醒"

    target_at = (
        datetime.combine(local_at.date(), target, tzinfo=SHANGHAI).isoformat()
        if target is not None
        else None
    )
    return {
        "strategy_version": SCHEDULED_EXECUTION_VERSION,
        "state": state,
        "message": message,
        "entry_allowed": entry_allowed,
        "target_at": target_at,
        "entry_windows": [f"{start[:5]}-{end[:5]}" for start, end in ENTRY_WINDOWS],
        "exit_time": EXIT_TIME[:5],
        "max_positions": MAX_POSITIONS,
        "target_position_pct": TARGET_POSITION_PCT,
        "max_snapshot_age_seconds": MAX_SNAPSHOT_AGE_SECONDS,
    }


def next_session_execution_clock() -> dict[str, object]:
    """Describe the fixed plan when the market is closed or not yet scanning."""

    return {
        "strategy_version": SCHEDULED_EXECUTION_VERSION,
        "state": "next_session_wait",
        "message": "下一交易日09:55提醒，10:00开始连续盘中评估",
        "entry_allowed": False,
        "target_at": None,
        "entry_windows": [f"{start[:5]}-{end[:5]}" for start, end in ENTRY_WINDOWS],
        "exit_time": EXIT_TIME[:5],
        "max_positions": MAX_POSITIONS,
        "target_position_pct": TARGET_POSITION_PCT,
        "max_snapshot_age_seconds": MAX_SNAPSHOT_AGE_SECONDS,
    }


def extract_scheduled_orders(
    history_rows: Sequence[Mapping[str, object]],
    *,
    included_lanes: Sequence[str] = PRODUCT_EXECUTION_LANES,
) -> list[dict[str, object]]:
    """Extract chronological eligible events without consulting final Top-N selection."""

    normalized_lanes = tuple(
        lane
        for lane in dict.fromkeys(str(value) for value in included_lanes)
        if lane in RESEARCH_EXECUTION_LANES
    )
    candidates: list[dict[str, object]] = []
    for day in history_rows:
        portfolio = day.get("lane_portfolio")
        portfolio = portfolio if isinstance(portfolio, Mapping) else {}
        pools = portfolio.get("candidate_pool")
        pools = pools if isinstance(pools, Mapping) else {}
        for lane in normalized_lanes:
            lane_rows = pools.get(lane)
            lane_rows = lane_rows if isinstance(lane_rows, Sequence) else []
            for raw_candidate in lane_rows:
                if not isinstance(raw_candidate, Mapping):
                    continue
                candidate = dict(raw_candidate)
                buy_time = _time_text(
                    candidate.get("buy_time") or candidate.get("signal_time")
                )
                if (
                    candidate.get("decision") != "eligible"
                    or candidate.get("lane") != lane
                    or not is_entry_time(buy_time)
                    or (
                        lane in RELAY_LANES
                        and candidate.get("relay_trigger_status") != "ready"
                    )
                ):
                    continue
                entry_date = str(
                    candidate.get("entry_date")
                    or candidate.get("signal_date")
                    or day.get("trade_date")
                    or ""
                )[:10]
                if not entry_date:
                    continue
                candidates.append(
                    {
                        **candidate,
                        "entry_date": entry_date,
                        "signal_date": entry_date,
                        "buy_time": buy_time,
                        "signal_time": buy_time,
                        "validation_phase": candidate.get("validation_phase")
                        or day.get("validation_phase")
                        or "unknown",
                        "candidate_source": f"complete_{lane}_candidate_pool",
                        "scheduled_execution_version": SCHEDULED_EXECUTION_VERSION,
                    }
                )

    candidates.sort(key=_scheduled_order_sort_key)
    seen: set[tuple[str, str]] = set()
    orders: list[dict[str, object]] = []
    for candidate in candidates:
        identity = (
            str(candidate.get("entry_date") or ""),
            str(candidate.get("vt_symbol") or ""),
        )
        if not all(identity) or identity in seen:
            continue
        seen.add(identity)
        orders.append(candidate)
    return orders


def _scheduled_order_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    return (
        str(candidate.get("entry_date") or ""),
        _time_text(candidate.get("buy_time") or candidate.get("signal_time")),
        execution_lane_priority(candidate.get("lane")),
        -_number(candidate.get("rank_score")),
        _integer(candidate.get("pool_rank"), 1_000_000),
        str(candidate.get("vt_symbol") or ""),
    )


def execution_lane_priority(lane: object) -> int:
    """Prefer an available relay only when its timestamp matches a first board."""

    return 0 if str(lane or "") in RELAY_LANES else 1


def relay_trigger_coverage(
    history_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    by_lane: dict[str, Counter[str]] = {
        lane: Counter() for lane in sorted(RELAY_LANES)
    }
    for day in history_rows:
        portfolio = day.get("lane_portfolio")
        portfolio = portfolio if isinstance(portfolio, Mapping) else {}
        pools = portfolio.get("candidate_pool")
        pools = pools if isinstance(pools, Mapping) else {}
        for lane in RELAY_LANES:
            rows = pools.get(lane)
            rows = rows if isinstance(rows, Sequence) else []
            for candidate in rows:
                if not isinstance(candidate, Mapping):
                    continue
                if candidate.get("decision") != "eligible":
                    continue
                counts = by_lane[lane]
                counts["eligible"] += 1
                status = str(
                    candidate.get("relay_trigger_status")
                    or "missing_first_touch"
                )
                counts[status] += 1
                if status == "ready":
                    kind = str(candidate.get("signal_kind") or "unknown")
                    counts[kind] += 1
    total: Counter[str] = Counter()
    for counts in by_lane.values():
        total.update(counts)
    return {
        "by_lane": {lane: dict(counts) for lane, counts in by_lane.items()},
        "total": dict(total),
    }


def _time_text(value: object) -> str:
    text = str(value or "").strip()
    if "T" in text:
        text = text.rsplit("T", 1)[-1]
    elif " " in text:
        text = text.rsplit(" ", 1)[-1]
    text = text.split("+", 1)[0].split("Z", 1)[0]
    parts = text.split(":")
    if len(parts) < 2:
        return "00:00:00"
    hour, minute = parts[:2]
    second = parts[2].split(".", 1)[0] if len(parts) >= 3 else "00"
    try:
        return f"{int(hour):02d}:{int(minute):02d}:{int(second):02d}"
    except ValueError:
        return "00:00:00"


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
