"""Continuous intraday first-board clock shared by replay and live views."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v2"
MAX_POSITIONS = 2
TARGET_POSITION_PCT = 50.0
MAX_SNAPSHOT_AGE_SECONDS = 20
EXIT_TIME = "14:30:00"
ENTRY_WINDOWS = (("10:00:00", "11:30:00"), ("13:00:00", "14:30:00"))
RESEARCH_SAMPLE_START = date(2026, 1, 16)
VALIDATION_START = date(2026, 4, 14)
RULE_FREEZE_DATE = date(2026, 7, 14)


def is_entry_time(value: object) -> bool:
    """Return whether a visible signal arrived during continuous evaluation."""

    time_text = _time_text(value)
    return any(start <= time_text < end for start, end in ENTRY_WINDOWS)


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
) -> list[dict[str, object]]:
    """Extract chronological eligible events without consulting final Top-N selection."""

    candidates: list[dict[str, object]] = []
    for day in history_rows:
        portfolio = day.get("lane_portfolio")
        portfolio = portfolio if isinstance(portfolio, Mapping) else {}
        pools = portfolio.get("candidate_pool")
        pools = pools if isinstance(pools, Mapping) else {}
        first_board = pools.get("first_board")
        first_board = first_board if isinstance(first_board, Sequence) else []
        for raw_candidate in first_board:
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate = dict(raw_candidate)
            buy_time = _time_text(
                candidate.get("buy_time") or candidate.get("signal_time")
            )
            if (
                candidate.get("decision") != "eligible"
                or candidate.get("lane") != "first_board"
                or not is_entry_time(buy_time)
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
                    "candidate_source": "complete_first_board_candidate_pool",
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
        -_number(candidate.get("rank_score")),
        _integer(candidate.get("pool_rank"), 1_000_000),
        str(candidate.get("vt_symbol") or ""),
    )


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
