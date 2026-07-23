"""Causal labels and settlement helpers for the shared pre-board contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from hashlib import sha256
import json
from math import isfinite
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import (
    cash_backtest,
    preboard_decision_repository,
    radar_observation_repository,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_daily_bars_for_symbols,
)
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    load_reliable_trade_dates,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TOUCH_HORIZON_SECONDS = 3 * 60
TRADING_SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0)))


def build_touch_labels(
    feature_rows: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
    *,
    scope_complete: bool,
) -> dict[tuple[int, str], dict[str, object]]:
    """Join frozen decisions to later formal first-board touch events.

    A missing event is a negative label only after the complete radar scope for the
    day has been frozen. Events at or before the decision timestamp are excluded.
    """

    labels: dict[tuple[int, str], dict[str, object]] = {}
    if not scope_complete:
        for row in feature_rows:
            identity = _feature_identity(row)
            labels[identity] = _unknown_label()
        return labels

    events_by_symbol = _formal_touch_events(observations)
    for row in feature_rows:
        identity = _feature_identity(row)
        decision_at = _required_datetime(
            row.get("decision_at") or row.get("captured_at"),
            "decision_at",
        )
        decision_date = _local_datetime(decision_at).date()
        future_events = [
            event_at
            for event_at in events_by_symbol.get(identity[1], ())
            if _local_datetime(event_at).date() == decision_date
            and _strictly_after(event_at, decision_at)
        ]
        within_3m = any(
            _trading_seconds_between(decision_at, event_at)
            <= TOUCH_HORIZON_SECONDS
            for event_at in future_events
        )
        labels[identity] = {
            "label_status": "known",
            "formal_touch_within_3m": within_3m,
            "eventual_formal_touch": bool(future_events),
        }
    return labels


def settle_decision_actions(
    *,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Advance saved shadow/formal actions using later immutable evidence."""

    current_at = _local_datetime(as_of or datetime.now(SHANGHAI))
    actions = preboard_decision_repository.load_decision_actions()
    pending = [row for row in actions if _has_pending_stage(row)]
    if not pending:
        return {"action_count": len(actions), "stages_closed": 0}

    scopes = {
        parsed: dict(row)
        for row in preboard_decision_repository.load_decision_day_scopes()
        if (parsed := _optional_date(row.get("trade_date"))) is not None
    }
    action_dates = sorted(
        {
            parsed
            for row in pending
            if (parsed := _optional_date(row.get("trade_date"))) is not None
        }
    )
    observations_by_date = {
        value: radar_observation_repository.load_observations(value, value)
        for value in action_dates
    }
    symbols = sorted(
        {
            str(row.get("vt_symbol") or "").strip()
            for row in pending
            if str(row.get("vt_symbol") or "").strip()
        }
    )
    daily_bars = (
        load_daily_bars_for_symbols(symbols, min(action_dates), current_at.date())
        if symbols and action_dates
        else []
    )
    bars_by_pair = {
        (str(row.get("vt_symbol") or ""), parsed): dict(row)
        for row in daily_bars
        if (parsed := _optional_date(row.get("trade_date"))) is not None
    }
    reliable_dates = (
        load_reliable_trade_dates(min(action_dates), current_at.date())
        if action_dates
        else []
    )

    closed = 0
    for action in pending:
        action_date = _optional_date(action.get("trade_date"))
        symbol = str(action.get("vt_symbol") or "").strip()
        if action_date is None or not symbol:
            continue
        day_closed = action_date < current_at.date() or (
            action_date == current_at.date()
            and current_at.time().replace(tzinfo=None) >= time(15, 0)
        )
        scope = scopes.get(action_date, {})
        scope_complete = bool(
            scope.get("is_complete") is True and scope.get("status") == "complete"
        )
        intraday = (
            build_action_intraday_outcomes(
                action,
                observations_by_date.get(action_date, ()),
                daily_bar=bars_by_pair.get((symbol, action_date)),
                scope_complete=scope_complete,
            )
            if day_closed
            else {}
        )
        for stage in ("fill", "formal_touch", "physical_touch"):
            values = intraday.get(stage)
            if not isinstance(values, Mapping) or not _stage_pending(action, stage):
                continue
            preboard_decision_repository.close_decision_action_stage(
                action,
                stage=stage,
                values=values,
            )
            action.update(values)
            closed += 1

        if _stage_pending(action, "d1"):
            expected_d1 = next(
                (value for value in reliable_dates if value > action_date),
                None,
            )
            d1 = build_d1_outcome(
                action,
                daily_bar=(
                    bars_by_pair.get((symbol, expected_d1))
                    if expected_d1 is not None
                    else None
                ),
                expected_d1_trade_date=expected_d1,
            )
            if d1 is not None:
                preboard_decision_repository.close_decision_action_stage(
                    action,
                    stage="d1",
                    values=d1,
                )
                closed += 1
    return {"action_count": len(actions), "stages_closed": closed}


def build_action_intraday_outcomes(
    action: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
    *,
    daily_bar: Mapping[str, object] | None,
    scope_complete: bool,
) -> dict[str, dict[str, object]]:
    """Resolve action-day stages only when the complete quote scope is known."""

    if not scope_complete:
        return {}
    action_at = _required_datetime(
        action.get("captured_at") or action.get("decision_at"),
        "captured_at",
    )
    symbol = str(action.get("vt_symbol") or "").strip()
    limit_price = _positive_number(action.get("limit_price"))
    if not symbol or limit_price is None:
        raise ValueError("action symbol and limit_price are required")
    visible = []
    for raw in observations:
        if str(raw.get("vt_symbol") or "").strip() != symbol:
            continue
        captured_at = _optional_datetime(raw.get("captured_at"))
        quote_at = _optional_datetime(raw.get("quote_observed_at")) or captured_at
        if (
            captured_at is None
            or quote_at is None
            or not _strictly_after(captured_at, action_at)
            or not _strictly_after(quote_at, action_at)
        ):
            continue
        visible.append({**dict(raw), "captured_at": captured_at, "quote_at": quote_at})
    visible.sort(
        key=lambda row: (
            _datetime_sort_key(row["captured_at"]),
            int(row.get("frame_id") or 0),
        )
    )
    evidence = {
        "decision_version": action.get("contract_version"),
        "captured_at": action_at.isoformat(),
        "vt_symbol": symbol,
        "observations": [
            {
                "frame_id": row.get("frame_id"),
                "captured_at": _local_datetime(row["captured_at"]).isoformat(),
                "quote_observed_at": _local_datetime(row["quote_at"]).isoformat(),
                "last_price": _number(row.get("last_price")),
                "capture_state": str(row.get("capture_state") or ""),
                "formal_action": str(row.get("formal_action") or ""),
            }
            for row in visible
        ],
    }
    fill_row = next(
        (
            row
            for row in visible
            if (price := _number(row.get("last_price"))) is not None
            and price < limit_price - 0.001
        ),
        None,
    )
    formal_row = next(
        (
            row
            for row in visible
            if str(row.get("formal_action") or "") == "buy_now"
            and str(row.get("board_lane") or "first_board") == "first_board"
        ),
        None,
    )
    touch_row = next(
        (row for row in visible if _physical_touch(row, limit_price)),
        None,
    )
    daily_high = _number((daily_bar or {}).get("high_price"))
    daily_close = _number((daily_bar or {}).get("close_price"))
    physical_touched = bool(
        touch_row is not None
        or (daily_high is not None and daily_high >= limit_price - 0.001)
    )
    outcomes: dict[str, dict[str, object]] = {
        "fill": {
            "fill_status": "filled" if fill_row is not None else "not_filled",
            "fill_at": fill_row.get("captured_at") if fill_row else None,
            "fill_price": _number(fill_row.get("last_price")) if fill_row else None,
            "fill_quote_observed_at": fill_row.get("quote_at") if fill_row else None,
            "settlement_evidence": evidence,
            "settlement_evidence_fingerprint": _fingerprint(evidence),
        },
        "formal_touch": {
            "formal_identity_status": "matched" if formal_row else "not_matched",
            "formal_event_at": formal_row.get("captured_at") if formal_row else None,
            "formal_identity_vt_symbol": symbol if formal_row else None,
            "formal_identity_matched": bool(formal_row),
            "original_two_slot_matched": None,
        },
    }
    if daily_bar is not None:
        outcomes["physical_touch"] = {
            "physical_touch_status": "touched" if physical_touched else "not_touched",
            "physical_touch_at": touch_row.get("captured_at") if touch_row else None,
            "final_sealed": bool(
                daily_close is not None and daily_close >= limit_price - 0.001
            ),
        }
    return outcomes


def build_d1_outcome(
    action: Mapping[str, object],
    *,
    daily_bar: Mapping[str, object] | None,
    expected_d1_trade_date: date | None,
) -> dict[str, object] | None:
    """Close the frozen D+1 official-close outcome after formal costs."""

    fill_status = str(action.get("fill_status") or "")
    if fill_status == "pending":
        return None
    if fill_status != "filled":
        return {
            "d1_status": "not_filled",
            "d1_trade_date": None,
            "d1_close_price": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "double_cost_net_return_pct": None,
        }
    if expected_d1_trade_date is None or daily_bar is None:
        return None
    bar_date = _optional_date(daily_bar.get("trade_date"))
    fill_price = _positive_number(action.get("fill_price"))
    close_price = _positive_number(daily_bar.get("close_price"))
    limit_price = _positive_number(action.get("limit_price"))
    if (
        bar_date != expected_d1_trade_date
        or fill_price is None
        or close_price is None
    ):
        return None
    normal = cash_backtest.calculate_round_trip_outcome(
        fill_price,
        close_price,
        limit_price=limit_price,
        cost_multiplier=1.0,
    )
    stress = cash_backtest.calculate_round_trip_outcome(
        fill_price,
        close_price,
        limit_price=limit_price,
        cost_multiplier=2.0,
    )
    if normal is None or stress is None:
        return None
    return {
        "d1_status": "closed",
        "d1_trade_date": bar_date,
        "d1_close_price": close_price,
        "gross_return_pct": round((close_price / fill_price - 1.0) * 100.0, 4),
        "net_return_pct": round(normal["net_return_pct"], 4),
        "double_cost_net_return_pct": round(stress["net_return_pct"], 4),
    }


def _formal_touch_events(
    observations: Sequence[Mapping[str, object]],
) -> dict[str, tuple[datetime, ...]]:
    events: dict[str, set[datetime]] = {}
    for row in observations:
        if str(row.get("formal_action") or "") != "buy_now":
            continue
        lane = str(row.get("board_lane") or "first_board")
        if lane != "first_board":
            continue
        symbol = str(row.get("vt_symbol") or "").strip()
        event_at = _optional_datetime(row.get("captured_at"))
        if (
            not symbol
            or event_at is None
            or not scheduled_execution.is_entry_time(_local_datetime(event_at))
        ):
            continue
        events.setdefault(symbol, set()).add(event_at)
    return {
        symbol: tuple(sorted(values, key=_datetime_sort_key))
        for symbol, values in events.items()
    }


def _feature_identity(row: Mapping[str, object]) -> tuple[int, str]:
    try:
        frame_id = int(row.get("frame_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("frame_id is required") from exc
    symbol = str(row.get("vt_symbol") or "").strip()
    if frame_id <= 0 or not symbol:
        raise ValueError("feature identity is incomplete")
    return frame_id, symbol


def _unknown_label() -> dict[str, object]:
    return {
        "label_status": "incomplete_scope",
        "formal_touch_within_3m": None,
        "eventual_formal_touch": None,
    }


def _trading_seconds_between(start: datetime, end: datetime) -> float:
    local_start = _local_datetime(start)
    local_end = _local_datetime(end)
    if local_end <= local_start or local_end.date() != local_start.date():
        return float("inf")
    total = 0.0
    for session_start, session_end in TRADING_SESSIONS:
        lower = max(
            local_start,
            datetime.combine(local_start.date(), session_start, tzinfo=SHANGHAI),
        )
        upper = min(
            local_end,
            datetime.combine(local_start.date(), session_end, tzinfo=SHANGHAI),
        )
        if upper > lower:
            total += (upper - lower).total_seconds()
    return total


def _strictly_after(value: datetime, cutoff: datetime) -> bool:
    return _local_datetime(value) > _local_datetime(cutoff)


def _datetime_sort_key(value: datetime) -> str:
    return _local_datetime(value).isoformat()


def _required_datetime(value: object, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _has_pending_stage(action: Mapping[str, object]) -> bool:
    return any(
        str(action.get(field) or "pending") == "pending"
        for field in (
            "fill_status",
            "formal_identity_status",
            "physical_touch_status",
            "d1_status",
        )
    )


def _stage_pending(action: Mapping[str, object], stage: str) -> bool:
    status_field = {
        "fill": "fill_status",
        "formal_touch": "formal_identity_status",
        "physical_touch": "physical_touch_status",
        "d1": "d1_status",
    }[stage]
    return str(action.get(status_field) or "pending") == "pending"


def _optional_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return _local_datetime(value).date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive_number(value: object) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _physical_touch(row: Mapping[str, object], limit_price: float) -> bool:
    state = str(row.get("capture_state") or "")
    price = _number(row.get("last_price"))
    return bool(
        state in {"sealed", "resealed", "failed", "limit_touch", "touched"}
        or (price is not None and price >= limit_price - 0.001)
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return "sha256:" + sha256(encoded).hexdigest()
