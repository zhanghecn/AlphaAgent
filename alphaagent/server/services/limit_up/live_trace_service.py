"""Read-side state timelines for append-only intraday limit-up traces."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from threading import Lock

from alphaagent.server.services.limit_up import live_trace_repository


EVENT_PRIORITY = {
    "trigger_ready": 0,
    "approaching_trigger": 1,
    "concept_warming": 2,
    "recommended": 3,
    "missed": 4,
    "sealed": 5,
    "resealed": 5,
    "failed": 6,
    "rejected": 7,
    "invalidated": 8,
    "radar_entered": 9,
    "dropped_from_top5": 10,
    "source_missing": 11,
}
SIGNAL_STATE_PRIORITY = {
    "trigger_ready": 0,
    "approaching_trigger": 1,
    "concept_warming": 2,
    "pending_auction": 3,
    "observing": 4,
    "missed": 5,
    "rejected": 6,
    "invalidated": 7,
}
_day_trace_cache: dict[date, _DayTraceAccumulator] = {}
_day_trace_cache_lock = Lock()


def get_live_trace_dates() -> dict[str, object]:
    dates = live_trace_repository.load_live_trace_dates()
    values = [value.isoformat() for value in dates]
    return {
        "status": "ready" if values else "empty",
        "dates": values,
        "latest": values[0] if values else None,
    }


def get_live_trace_day(trade_date: date) -> dict[str, object]:
    with _day_trace_cache_lock:
        accumulator = _refresh_day_trace_cache(trade_date)
        if accumulator is None:
            return {
                "status": "not_found",
                "trade_date": trade_date.isoformat(),
                "items": [],
            }
        return accumulator.day_result(trade_date.isoformat())


def get_live_trace_symbol(trade_date: date, vt_symbol: str) -> dict[str, object]:
    normalized_symbol = vt_symbol.upper()
    with _day_trace_cache_lock:
        accumulator = _refresh_day_trace_cache(trade_date)
        events = (
            accumulator.symbol_events(normalized_symbol)
            if accumulator is not None
            else []
        )
    if not events:
        return {
            "status": "not_found",
            "trade_date": trade_date.isoformat(),
            "vt_symbol": normalized_symbol,
            "events": [],
        }
    return {
        "status": "ready",
        "trade_date": trade_date.isoformat(),
        "vt_symbol": normalized_symbol,
        "events": events,
    }


def build_day_trace(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    accumulator = _DayTraceAccumulator()
    accumulator.extend(rows)
    return accumulator.day_result(_trace_trade_date(rows))


def build_symbol_trace(
    rows: Sequence[Mapping[str, object]],
    vt_symbol: str,
) -> list[dict[str, object]]:
    symbol = vt_symbol.upper()
    previous: dict[str, object] | None = None
    ever_triggered = False
    triggered_at: str | None = None
    events: list[dict[str, object]] = []
    for row in _ordered_live_rows(rows):
        current = _symbol_state(row, symbol, ever_triggered=ever_triggered)
        if current is not None and current.get("signal_state") == "trigger_ready":
            ever_triggered = True
            triggered_at = triggered_at or str(current["captured_at"])
            current["ever_triggered"] = True
        for event_name in transition_events(previous, current):
            events.append(
                _event_payload(
                    event_name,
                    current or previous,
                    row,
                    triggered_at=triggered_at,
                )
            )
        previous = current
    return events


class _DayTraceAccumulator:
    def __init__(self) -> None:
        self.previous_states: dict[str, dict[str, object]] = {}
        self.ever_triggered: dict[str, bool] = defaultdict(bool)
        self.triggered_at: dict[str, str] = {}
        self.events_by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
        self.first_seen_at: dict[str, str] = {}
        self.last_seen_at: dict[str, str] = {}
        self.snapshot_count = 0
        self.scan_error_count = 0
        self.last_id = 0

    def extend(self, rows: Sequence[Mapping[str, object]]) -> None:
        ordered = sorted(
            rows,
            key=lambda row: (
                _iso_datetime(row.get("captured_at")),
                int(row.get("id") or 0),
            ),
        )
        for row in ordered:
            self.snapshot_count += 1
            self.last_id = max(self.last_id, int(row.get("id") or 0))
            if str(row.get("mode") or "live_trace") == "scan_error":
                self.scan_error_count += 1
                continue
            self._append_live_row(row)

    def _append_live_row(self, row: Mapping[str, object]) -> None:
        current_states = _row_symbol_states(row, self.ever_triggered)
        next_previous_states: dict[str, dict[str, object]] = {}
        for symbol in sorted(self.previous_states.keys() | current_states.keys()):
            previous = self.previous_states.get(symbol)
            current = current_states.get(symbol)
            if current is not None:
                captured_at = str(current["captured_at"])
                self.first_seen_at.setdefault(symbol, captured_at)
                self.last_seen_at[symbol] = captured_at
                if current.get("signal_state") == "trigger_ready":
                    self.ever_triggered[symbol] = True
                    self.triggered_at.setdefault(symbol, captured_at)
                    current["ever_triggered"] = True
                next_previous_states[symbol] = current
            for event_name in transition_events(previous, current):
                self.events_by_symbol[symbol].append(
                    _event_payload(
                        event_name,
                        current or previous,
                        row,
                        triggered_at=self.triggered_at.get(symbol),
                    )
                )
        self.previous_states = next_previous_states

    def day_result(self, trade_date: str | None) -> dict[str, object]:
        items = [
            summary
            for symbol, events in self.events_by_symbol.items()
            if (
                summary := _summary_from_events(
                    symbol,
                    events,
                    (self.first_seen_at[symbol], self.last_seen_at[symbol]),
                )
            ) is not None
        ]
        items.sort(key=_summary_sort_key)
        return {
            "status": "ready",
            "trade_date": trade_date,
            "snapshot_count": self.snapshot_count,
            "scan_error_count": self.scan_error_count,
            "lane_funnels": _lane_funnels(self.events_by_symbol),
            "items": items,
        }

    def symbol_events(self, vt_symbol: str) -> list[dict[str, object]]:
        return [dict(event) for event in self.events_by_symbol.get(vt_symbol, [])]


def _refresh_day_trace_cache(trade_date: date) -> _DayTraceAccumulator | None:
    accumulator = _day_trace_cache.get(trade_date)
    rows = live_trace_repository.load_live_trace_rows(
        trade_date,
        after_id=accumulator.last_id if accumulator is not None else None,
    )
    if accumulator is None:
        if not rows:
            return None
        accumulator = _DayTraceAccumulator()
        _day_trace_cache[trade_date] = accumulator
    accumulator.extend(rows)
    for expired_date in sorted(_day_trace_cache)[:-2]:
        _day_trace_cache.pop(expired_date, None)
    return accumulator


def clear_live_trace_read_cache() -> None:
    with _day_trace_cache_lock:
        _day_trace_cache.clear()


def _row_symbol_states(
    row: Mapping[str, object],
    ever_triggered: Mapping[str, bool],
) -> dict[str, dict[str, object]]:
    ranked_by_symbol = {
        str(candidate.get("vt_symbol") or "").upper(): candidate
        for candidate in _mapping_rows(row.get("ranked_candidates"))
        if candidate.get("vt_symbol")
    }
    signals_by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    recommendations = _mapping(row.get("recommendations"))
    lanes = _mapping(recommendations.get("lanes"))
    for channel in ("now", "tail", "next_auction"):
        for signal in _mapping_rows(lanes.get(channel)):
            symbol = str(signal.get("vt_symbol") or "").upper()
            if symbol:
                signals_by_symbol[symbol].append(signal)
    market_gate = _mapping(recommendations.get("market_gate"))
    captured_at = _iso_datetime(row.get("captured_at"))
    data_quality_status = _mapping(row.get("data_quality")).get("status")
    states: dict[str, dict[str, object]] = {}
    for candidate in _mapping_rows(row.get("radar_candidates")):
        symbol = str(candidate.get("vt_symbol") or "").upper()
        if not symbol or symbol in states:
            continue
        signals = signals_by_symbol.get(symbol, [])
        signal = min(signals, key=_signal_sort_key) if signals else {}
        market_rank = _integer_or_none(
            signal.get("market_dragon_rank")
            or ranked_by_symbol.get(symbol, {}).get("market_dragon_rank")
            or candidate.get("market_dragon_rank")
        )
        states[symbol] = {
            **candidate,
            **dict(ranked_by_symbol.get(symbol, {})),
            **_signal_state_payload(signal),
            "vt_symbol": symbol,
            "captured_at": captured_at,
            "in_top5": market_rank is not None and market_rank <= 5,
            "ever_triggered": ever_triggered.get(symbol, False),
            "market_gate_passed": market_gate.get("passed") is True,
            "market_gate_reasons": list(market_gate.get("reasons") or []),
            "market_repair_state": market_gate.get("repair_state"),
            "market_repair_confirmed_at": market_gate.get("repair_confirmed_at"),
            "data_quality_status": data_quality_status,
        }
    return states


def transition_events(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object] | None,
) -> list[str]:
    if previous is None and current is None:
        return []
    if current is None:
        return ["source_missing"]

    events: list[str] = []
    if previous is None:
        events.append("radar_entered")
    previous_ranked = bool(previous and previous.get("in_top5"))
    current_ranked = bool(current.get("in_top5"))
    if current_ranked and not previous_ranked:
        events.append("recommended")
    if previous_ranked and not current_ranked:
        events.append("dropped_from_top5")
    events.extend(_signal_transition_events(previous, current))
    events.extend(_board_transition_events(previous, current))
    return events


def _signal_transition_events(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> list[str]:
    signal_state = str(current.get("signal_state") or "")
    previous_state = str(previous.get("signal_state") or "") if previous else ""
    if signal_state == previous_state:
        return []
    if signal_state in {
        "concept_warming",
        "approaching_trigger",
        "trigger_ready",
        "rejected",
        "invalidated",
    }:
        return [signal_state]
    return []


def _board_transition_events(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> list[str]:
    state = str(current.get("state") or "")
    previous_state = str(previous.get("state") or "") if previous else ""
    if state == previous_state:
        return []
    if state in {"sealed", "resealed"}:
        prefix = (
            ["missed"]
            if not current.get("ever_triggered")
            and current.get("signal_state") == "missed"
            else []
        )
        return [*prefix, state]
    if state == "failed":
        return ["failed"]
    return []


def _symbol_state(
    row: Mapping[str, object],
    vt_symbol: str,
    *,
    ever_triggered: bool,
) -> dict[str, object] | None:
    candidate = _candidate_for_symbol(row, vt_symbol)
    if candidate is None:
        return None
    signal = _signal_for_symbol(row, vt_symbol)
    recommendations = _mapping(row.get("recommendations"))
    market_gate = _mapping(recommendations.get("market_gate"))
    market_rank = _integer_or_none(
        signal.get("market_dragon_rank") or candidate.get("market_dragon_rank")
    )
    return {
        **candidate,
        **_signal_state_payload(signal),
        "vt_symbol": vt_symbol,
        "captured_at": _iso_datetime(row.get("captured_at")),
        "in_top5": market_rank is not None and market_rank <= 5,
        "ever_triggered": ever_triggered,
        "market_gate_passed": market_gate.get("passed") is True,
        "market_gate_reasons": list(market_gate.get("reasons") or []),
        "market_repair_state": market_gate.get("repair_state"),
        "market_repair_confirmed_at": market_gate.get("repair_confirmed_at"),
        "data_quality_status": _mapping(row.get("data_quality")).get("status"),
    }


def _signal_state_payload(signal: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "market_dragon_rank",
        "signal_state",
        "action",
        "research_action",
        "entry_kind",
        "reason",
        "lane_blocker_reasons",
        "lane_support_score",
        "lane_entry_quality_score",
        "blocking_scope",
        "pending_reasons",
        "trigger_checks",
        "concept_id",
        "concept_name",
        "concept_state",
        "concept_strength_score",
        "concept_strength_rank",
        "concept_strength_percentile",
        "concept_leader_rank",
        "concept_coverage_ratio",
        "concept_strong_5_count",
        "concept_near_limit_count",
        "concept_sealed_count",
        "concept_failed_count",
        "concept_change_acceleration_3m",
        "concept_turnover_acceleration_3m",
        "concept_snapshot_age_seconds",
    )
    return {key: signal[key] for key in keys if key in signal}


def _candidate_for_symbol(
    row: Mapping[str, object],
    vt_symbol: str,
) -> dict[str, object] | None:
    radar = _mapping_rows(row.get("radar_candidates"))
    ranked = _mapping_rows(row.get("ranked_candidates"))
    candidate = next(
        (item for item in radar if str(item.get("vt_symbol") or "").upper() == vt_symbol),
        None,
    )
    if candidate is None:
        return None
    ranked_candidate = next(
        (item for item in ranked if str(item.get("vt_symbol") or "").upper() == vt_symbol),
        {},
    )
    return {**candidate, **ranked_candidate}


def _signal_for_symbol(
    row: Mapping[str, object],
    vt_symbol: str,
) -> dict[str, object]:
    recommendations = _mapping(row.get("recommendations"))
    lanes = _mapping(recommendations.get("lanes"))
    signals = [
        signal
        for channel in ("now", "tail", "next_auction")
        for signal in _mapping_rows(lanes.get(channel))
        if str(signal.get("vt_symbol") or "").upper() == vt_symbol
    ]
    return min(signals, key=_signal_sort_key) if signals else {}


def _signal_sort_key(signal: Mapping[str, object]) -> tuple[int, int]:
    signal_state = str(signal.get("signal_state") or "")
    action = str(signal.get("research_action") or signal.get("action") or "pass")
    action_priority = {"buy_now": 0, "next_auction": 1, "observe": 2, "wait_tail": 3, "pass": 4}
    return (
        SIGNAL_STATE_PRIORITY.get(signal_state, 99),
        action_priority.get(action, 99),
    )


def _event_payload(
    event_name: str,
    state: Mapping[str, object] | None,
    row: Mapping[str, object],
    *,
    triggered_at: str | None,
) -> dict[str, object]:
    current = dict(state or {})
    reason = _event_reason(event_name, current)
    return {
        "event": event_name,
        "captured_at": _iso_datetime(row.get("captured_at")),
        "triggered_at": triggered_at,
        "vt_symbol": current.get("vt_symbol"),
        "name": current.get("name"),
        "board_lane": current.get("board_lane"),
        "board_level": current.get("board_level"),
        "state": current.get("state"),
        "signal_state": current.get("signal_state"),
        "action": current.get("action"),
        "research_action": current.get("research_action"),
        "last_price": current.get("last_price"),
        "change_pct": current.get("change_pct"),
        "distance_to_limit_pct": current.get("distance_to_limit_pct"),
        "sector_heat": current.get("sector_heat"),
        "sector_touch_count": current.get("sector_touch_count"),
        "concept_id": current.get("concept_id"),
        "concept_name": current.get("concept_name"),
        "concept_state": current.get("concept_state"),
        "concept_strength_score": current.get("concept_strength_score"),
        "concept_strength_rank": current.get("concept_strength_rank"),
        "concept_strength_percentile": current.get("concept_strength_percentile"),
        "concept_leader_rank": current.get("concept_leader_rank"),
        "concept_coverage_ratio": current.get("concept_coverage_ratio"),
        "concept_strong_5_count": current.get("concept_strong_5_count"),
        "concept_near_limit_count": current.get("concept_near_limit_count"),
        "concept_sealed_count": current.get("concept_sealed_count"),
        "concept_failed_count": current.get("concept_failed_count"),
        "concept_change_acceleration_3m": current.get(
            "concept_change_acceleration_3m"
        ),
        "concept_turnover_acceleration_3m": current.get(
            "concept_turnover_acceleration_3m"
        ),
        "concept_snapshot_age_seconds": current.get("concept_snapshot_age_seconds"),
        "sector_main_net_inflow": current.get("sector_main_net_inflow"),
        "stock_main_net_inflow": current.get("stock_main_net_inflow"),
        "turnover_rate": current.get("turnover_rate"),
        "seal_amount": current.get("seal_amount"),
        "seal_amount_retention_ratio": current.get("seal_amount_retention_ratio"),
        "seal_amount_change_pct": current.get("seal_amount_change_pct"),
        "portfolio_selected": current.get("portfolio_selected") is True,
        "in_top5": current.get("in_top5") is True,
        "market_gate_passed": current.get("market_gate_passed") is True,
        "market_gate_reasons": list(current.get("market_gate_reasons") or []),
        "market_repair_state": current.get("market_repair_state"),
        "market_repair_confirmed_at": current.get("market_repair_confirmed_at"),
        "blocking_scope": current.get("blocking_scope"),
        "pending_reasons": list(current.get("pending_reasons") or []),
        "trigger_checks": list(current.get("trigger_checks") or []),
        "blockers": list(
            current.get("lane_blocker_reasons")
            or current.get("lane_blockers")
            or []
        ),
        "reason": reason,
        "data_quality_status": current.get("data_quality_status"),
    }


def _event_reason(event_name: str, state: Mapping[str, object]) -> str:
    explicit = str(state.get("reason") or "").strip()
    defaults = {
        "radar_entered": "进入5%预热雷达",
        "concept_warming": "所属概念开始扩散，进入板块预热",
        "recommended": "进入当前动态Top5",
        "dropped_from_top5": "仍在雷达池，但已跌出当前动态Top5",
        "source_missing": "当前扫描未返回该股票，旧价格不再用于买点",
        "missed": "未出现可成交买点便已封板",
        "sealed": "当前封板",
        "resealed": "当前回封",
        "failed": "当前炸板",
        "rejected": "结构硬门未通过",
    }
    return explicit or defaults.get(event_name, "状态发生变化")


def _summary_from_events(
    vt_symbol: str,
    events: Sequence[Mapping[str, object]],
    seen_bounds: tuple[str, str],
) -> dict[str, object] | None:
    if not events:
        return None
    first_seen_at, last_seen_at = seen_bounds
    highest = min(events, key=lambda event: EVENT_PRIORITY.get(str(event["event"]), 99))
    latest = events[-1]
    triggered = next((event for event in events if event["event"] == "trigger_ready"), None)
    return {
        "vt_symbol": vt_symbol,
        "name": latest.get("name") or highest.get("name"),
        "board_lane": latest.get("board_lane") or highest.get("board_lane"),
        "board_level": latest.get("board_level") or highest.get("board_level"),
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "highest_state": highest["event"],
        "final_state": latest["event"],
        "ever_recommended": any(event["event"] == "recommended" for event in events),
        "ever_triggered": triggered is not None,
        "triggered_at": triggered.get("captured_at") if triggered else None,
        "last_price": latest.get("last_price"),
        "change_pct": latest.get("change_pct"),
        "distance_to_limit_pct": latest.get("distance_to_limit_pct"),
        "concept_name": latest.get("concept_name") or highest.get("concept_name"),
        "concept_state": latest.get("concept_state") or highest.get("concept_state"),
        "concept_strength_rank": latest.get("concept_strength_rank"),
        "concept_leader_rank": latest.get("concept_leader_rank"),
        "reason": latest.get("reason"),
        "event_count": len(events),
    }


def _summary_sort_key(item: Mapping[str, object]) -> tuple[object, ...]:
    return (
        EVENT_PRIORITY.get(str(item.get("highest_state") or ""), 99),
        str(item.get("first_seen_at") or ""),
        str(item.get("vt_symbol") or ""),
    )


def _lane_funnels(
    events_by_symbol: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, dict[str, object]]:
    lanes = ("first_board", "two_to_three", "high_board")
    return {
        lane: _lane_funnel(
            [
                events
                for events in events_by_symbol.values()
                if _event_lane(events) == lane
            ]
        )
        for lane in lanes
    }


def _lane_funnel(
    symbol_events: Sequence[Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    blocker_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    for events in symbol_events:
        if any(event.get("event") == "trigger_ready" for event in events):
            continue
        closest = _closest_blocked_event(events)
        if closest is None:
            continue
        seen_codes: set[str] = set()
        for check in closest.get("trigger_checks") or []:
            if (
                not isinstance(check, Mapping)
                or check.get("status") not in {"pending", "failed"}
            ):
                continue
            code = str(check.get("code") or "unknown")
            if code in seen_codes:
                continue
            seen_codes.add(code)
            blocker_counts[(code, str(check.get("label") or code))] += 1

    primary_blockers = [
        {"code": code, "label": label, "count": count}
        for (code, label), count in sorted(
            blocker_counts.items(),
            key=lambda item: (-item[1], item[0][0]),
        )
    ]
    return {
        "radar_count": len(symbol_events),
        "warming_count": _event_group_count(
            symbol_events,
            signal_state="concept_warming",
        ),
        "recommended_count": _event_group_count(symbol_events, event_name="recommended"),
        "approaching_count": _event_group_count(
            symbol_events,
            signal_state="approaching_trigger",
        ),
        "triggered_count": _event_group_count(symbol_events, event_name="trigger_ready"),
        "sealed_without_trigger_count": sum(
            any(event.get("event") == "missed" for event in events)
            and not any(event.get("event") == "trigger_ready" for event in events)
            for events in symbol_events
        ),
        "structural_rejected_count": _scope_group_count(symbol_events, "structural"),
        "market_blocked_count": _scope_group_count(symbol_events, "market"),
        "dynamic_blocked_count": _scope_group_count(symbol_events, "dynamic"),
        "primary_blockers": primary_blockers,
    }


def _event_lane(events: Sequence[Mapping[str, object]]) -> str:
    return next(
        (str(event.get("board_lane")) for event in reversed(events) if event.get("board_lane")),
        "",
    )


def _event_group_count(
    symbol_events: Sequence[Sequence[Mapping[str, object]]],
    *,
    event_name: str | None = None,
    signal_state: str | None = None,
) -> int:
    return sum(
        any(
            (event_name is None or event.get("event") == event_name)
            and (signal_state is None or event.get("signal_state") == signal_state)
            for event in events
        )
        for events in symbol_events
    )


def _scope_group_count(
    symbol_events: Sequence[Sequence[Mapping[str, object]]],
    scope: str,
) -> int:
    return sum(
        any(event.get("blocking_scope") == scope for event in events)
        for events in symbol_events
    )


def _closest_blocked_event(
    events: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    candidates = [
        event
        for event in events
        if event.get("signal_state") == "approaching_trigger"
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda event: (
            sum(
                isinstance(check, Mapping)
                and check.get("status") in {"pending", "failed"}
                for check in event.get("trigger_checks") or []
            ),
            (
                float(event["distance_to_limit_pct"])
                if event.get("distance_to_limit_pct") is not None
                else 99.0
            ),
            str(event.get("captured_at") or ""),
        ),
    )


def _ordered_live_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    return sorted(
        (row for row in rows if str(row.get("mode") or "live_trace") != "scan_error"),
        key=lambda row: _iso_datetime(row.get("captured_at")),
    )


def _trace_trade_date(rows: Sequence[Mapping[str, object]]) -> str | None:
    for row in rows:
        value = row.get("trade_date")
        if isinstance(value, date):
            return value.isoformat()
        if value:
            return str(value)[:10]
    return None


def _iso_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return datetime.fromisoformat(str(value)).isoformat()


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _integer_or_none(value: object) -> int | None:
    try:
        return int(float(value)) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
