"""Continuous intraday limit-up clock shared by replay and live views."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.lane_features import first_reseal_time
from alphaagent.server.services.limit_up.versions import CORE_ABC_STRATEGY_VERSION

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULED_EXECUTION_VERSION = CORE_ABC_STRATEGY_VERSION
FIRST_BOARD_PROFITABILITY_FILTER_VERSION = "first-board-profitability-gate-v1"
FIRST_BOARD_MIN_D1_SAMPLES = 5
FIRST_BOARD_MIN_COMBINED_RATE = 30.0
MAX_POSITIONS = 2
TARGET_POSITION_PCT = 50.0
MAX_SNAPSHOT_AGE_SECONDS = 20
EXIT_MODE = "next_close"
EXIT_TIME = "15:00:00"
ENTRY_WINDOWS = (("10:00:00", "11:30:00"), ("13:00:00", "14:30:00"))
ENTRY_WINDOW_LABELS = tuple(
    f"{start[:5]}-{end[:5]}" for start, end in ENTRY_WINDOWS
)
ENTRY_CUTOFF_TIME = time.fromisoformat(ENTRY_WINDOWS[-1][1])
ENTRY_CUTOFF_LABEL = ENTRY_CUTOFF_TIME.strftime("%H:%M")
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
    elif clock < time(14, 30):
        state, message, entry_allowed, target = (
            "entry_window",
            "连续评估 13:00-14:30",
            True,
            time(14, 30),
        )
    elif clock < time(14, 55):
        state, message, target = (
            "waiting_close",
            "买入窗口已结束，15:00执行D+1收盘卖出",
            time(14, 55),
        )
    elif clock < time(15, 0):
        state, message, target = (
            "exit_reminder",
            "准备按官方收盘价卖出D+1持仓",
            time(15, 0),
        )
    else:
        state, message = "exit_time", "D+1收盘卖出已结束"

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
        "entry_windows": list(ENTRY_WINDOW_LABELS),
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
        "entry_windows": list(ENTRY_WINDOW_LABELS),
        "exit_time": EXIT_TIME[:5],
        "max_positions": MAX_POSITIONS,
        "target_position_pct": TARGET_POSITION_PCT,
        "max_snapshot_age_seconds": MAX_SNAPSHOT_AGE_SECONDS,
    }


def first_board_profitability_filter_metadata() -> dict[str, object]:
    """Return the single public contract for the frozen first-board gate."""

    return {
        "version": FIRST_BOARD_PROFITABILITY_FILTER_VERSION,
        "minimum_d1_samples": FIRST_BOARD_MIN_D1_SAMPLES,
        "minimum_combined_rate": FIRST_BOARD_MIN_COMBINED_RATE,
        "applies_to": "first_board",
        "two_to_three": "unchanged",
    }


def first_board_profitability_gate(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate the frozen same-stock profitability gate for one signal."""

    applies = _is_first_board(candidate)
    evidence = candidate.get("historical_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    sample_value = candidate.get("stock_d1_sample_count")
    if sample_value is None:
        sample_value = evidence.get("d1_money_effect_sample_count")
    combined_value = candidate.get("stock_gene_combined_win_rate")
    if combined_value is None:
        combined_value = evidence.get("historical_win_rate")
    sample_count = max(_integer(sample_value), 0) if applies else None
    combined_rate = _optional_number(combined_value) if applies else None
    if combined_rate is not None and not 0 <= combined_rate <= 100:
        combined_rate = None

    passed = True
    reason = "not_first_board"
    if applies and sample_count < FIRST_BOARD_MIN_D1_SAMPLES:
        passed = False
        reason = f"same_stock_d1_samples_below_{FIRST_BOARD_MIN_D1_SAMPLES}"
    elif applies and combined_rate is None:
        passed = False
        reason = "same_stock_joint_rate_unavailable"
    elif applies and combined_rate < FIRST_BOARD_MIN_COMBINED_RATE:
        passed = False
        reason = (
            "same_stock_joint_rate_below_"
            f"{FIRST_BOARD_MIN_COMBINED_RATE:g}"
        )
    elif applies:
        reason = "qualified"
    return {
        "profitability_gate_version": FIRST_BOARD_PROFITABILITY_FILTER_VERSION,
        "profitability_gate_applies": applies,
        "profitability_gate_passed": passed,
        "profitability_gate_reason": reason,
        "profitability_gate_minimum_d1_samples": FIRST_BOARD_MIN_D1_SAMPLES,
        "profitability_gate_minimum_combined_rate": (
            FIRST_BOARD_MIN_COMBINED_RATE
        ),
        "profitability_gate_sample_count": sample_count,
        "profitability_gate_combined_rate": combined_rate,
    }


def filter_profitability_qualified_orders(
    orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Keep chronological orders admitted by the frozen profitability gate."""

    selected: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    first_board_count = 0
    first_board_selected_count = 0
    for raw_order in orders:
        order = dict(raw_order)
        decision = first_board_profitability_gate(order)
        order.update(decision)
        reason_counts[str(decision["profitability_gate_reason"])] += 1
        if decision["profitability_gate_applies"] is True:
            first_board_count += 1
        if decision["profitability_gate_passed"] is not True:
            continue
        if decision["profitability_gate_applies"] is True:
            first_board_selected_count += 1
        selected.append(order)
    return selected, {
        **first_board_profitability_filter_metadata(),
        "input_count": len(orders),
        "selected_count": len(selected),
        "excluded_count": len(orders) - len(selected),
        "first_board_input_count": first_board_count,
        "first_board_selected_count": first_board_selected_count,
        "first_board_excluded_count": (
            first_board_count - first_board_selected_count
        ),
        "reason_counts": dict(sorted(reason_counts.items())),
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


def _optional_number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _is_first_board(candidate: Mapping[str, object]) -> bool:
    lane = str(candidate.get("lane") or candidate.get("board_lane") or "")
    if lane:
        return lane == "first_board"
    board_level = _optional_number(candidate.get("board_level"))
    return board_level is not None and board_level <= 1


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
