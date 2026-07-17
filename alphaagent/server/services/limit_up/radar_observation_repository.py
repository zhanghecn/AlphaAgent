"""Compact point-in-time persistence for the 3% limit-up radar."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from threading import Lock

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.radar_contract import (
    RADAR_CONTRACT_VERSION,
)
from alphaagent.server.services.limit_up import scheduled_execution


RADAR_RETAIN_TRADE_DAYS = 90
_prune_lock = Lock()
_last_pruned_trade_date: date | None = None


def retention_cutoff(
    trade_dates: Sequence[date],
    *,
    retain_trade_days: int = RADAR_RETAIN_TRADE_DAYS,
) -> date | None:
    keep_count = max(int(retain_trade_days), 1)
    ordered = sorted(set(trade_dates), reverse=True)
    return ordered[keep_count - 1] if len(ordered) >= keep_count else None


def project_observation(
    candidate: Mapping[str, object],
    *,
    formal_signal: Mapping[str, object] | None,
    early_signal: Mapping[str, object] | None,
) -> dict[str, object]:
    """Project one evaluated candidate into the bounded research contract."""

    formal = formal_signal if isinstance(formal_signal, Mapping) else {}
    early = early_signal if isinstance(early_signal, Mapping) else {}
    evidence = early.get("historical_evidence") or formal.get(
        "historical_evidence"
    ) or candidate.get("historical_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    blocker_codes = _blocker_codes(candidate, early)
    return {
        "vt_symbol": _required_text(candidate.get("vt_symbol"), "vt_symbol"),
        "name": _required_text(candidate.get("name"), "name"),
        "change_pct": _required_number(candidate.get("change_pct"), "change_pct"),
        "last_price": _required_positive(candidate.get("last_price"), "last_price"),
        "previous_close": _required_positive(
            candidate.get("previous_close"),
            "previous_close",
        ),
        "limit_price": _required_positive(candidate.get("limit_price"), "limit_price"),
        "capture_state": str(
            candidate.get("capture_state")
            or candidate.get("state")
            or "unknown"
        ),
        "board_lane": str(candidate.get("board_lane") or "first_board"),
        "support_score": _optional_number(candidate.get("lane_support_score")),
        "entry_quality_score": _optional_number(
            candidate.get("lane_entry_quality_score")
        ),
        "concept_id": _optional_text(candidate.get("concept_id")),
        "concept_state": _optional_text(candidate.get("concept_state")),
        "concept_strength_score": _optional_number(
            candidate.get("concept_strength_score")
        ),
        "concept_leader_rank": _optional_integer(
            candidate.get("concept_leader_rank")
        ),
        "concept_strong_5_count": _optional_integer(
            candidate.get("concept_strong_5_count")
        ),
        "sector_id": _optional_text(candidate.get("sector_id")),
        "sector_heat": _optional_number(candidate.get("sector_heat")),
        "sector_touch_count": _optional_integer(
            candidate.get("sector_touch_count")
        ),
        "history_sample_count": _optional_integer(
            candidate.get("d1_money_effect_sample_count")
            if candidate.get("d1_money_effect_sample_count") is not None
            else evidence.get("d1_money_effect_sample_count")
        ),
        "historical_combined_rate": _optional_number(
            candidate.get("historical_win_rate")
            if candidate.get("historical_win_rate") is not None
            else evidence.get("historical_win_rate")
        ),
        "formal_action": str(formal.get("action") or "pass"),
        "early_action": str(early.get("action") or "pass"),
        "early_entry_kind": str(early.get("entry_kind") or "none"),
        "blocking_scope": str(
            early.get("blocking_scope")
            or formal.get("blocking_scope")
            or "none"
        ),
        "decision_reason": _optional_text(
            early.get("reason") or formal.get("reason"),
            max_length=500,
        ),
        "blocker_codes": blocker_codes,
    }


def load_recent_signal_observations(
    captured_at: datetime,
    *,
    max_age_seconds: int = 75,
) -> list[dict[str, object]]:
    """Load the earliest recent buy decision per symbol for fill follow-up."""

    current_at = _required_datetime(captured_at)
    frame = schema.limit_up_radar_frames
    observation = schema.limit_up_radar_observations
    statement = (
        select(frame.c.captured_at.label("captured_at"), observation)
        .select_from(observation.join(frame, observation.c.frame_id == frame.c.id))
        .where(
            frame.c.trade_date == current_at.date(),
            frame.c.captured_at >= current_at - timedelta(seconds=max_age_seconds),
            frame.c.captured_at < current_at,
            or_(
                observation.c.formal_action == "buy_now",
                observation.c.early_action == "buy_now",
            ),
        )
        .order_by(frame.c.captured_at, observation.c.vt_symbol)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    earliest: dict[str, dict[str, object]] = {}
    for raw in rows:
        row = dict(raw)
        symbol = str(row.get("vt_symbol") or "")
        if symbol:
            earliest.setdefault(symbol, row)
    return list(earliest.values())


def build_fill_followup_observations(
    recent_signals: Sequence[Mapping[str, object]],
    full_quotes: Sequence[Mapping[str, object]],
    *,
    quote_observed_at: datetime,
    current_observation_symbols: set[str],
) -> list[dict[str, object]]:
    """Build quote-only rows for signaled stocks that left the 3% universe."""

    observed_at = _local_datetime(quote_observed_at)
    quote_by_symbol = {
        str(row.get("vt_symbol") or ""): row
        for row in full_quotes
        if isinstance(row, Mapping) and row.get("vt_symbol")
    }
    observation_fields = {
        column.name
        for column in schema.limit_up_radar_observations.columns
        if column.name != "frame_id"
    }
    rows: list[dict[str, object]] = []
    for raw in recent_signals:
        context = dict(raw)
        symbol = str(context.get("vt_symbol") or "")
        if not symbol or symbol in current_observation_symbols:
            continue
        signal_at = _local_datetime(context.get("captured_at"))
        elapsed = (observed_at - signal_at).total_seconds()
        if elapsed < 20 or elapsed > 60:
            continue
        if not (
            scheduled_execution.is_entry_time(signal_at)
            and scheduled_execution.is_entry_time(observed_at)
        ):
            continue
        quote = quote_by_symbol.get(symbol)
        price = _optional_number((quote or {}).get("last_price"))
        if price is None or price <= 0:
            continue
        previous_close = _optional_number(context.get("previous_close"))
        change_pct = _optional_number((quote or {}).get("change_pct"))
        if change_pct is None and previous_close and previous_close > 0:
            change_pct = (price / previous_close - 1) * 100
        if change_pct is None:
            continue
        row = {
            field: context.get(field)
            for field in observation_fields
        }
        row.update(
            {
                "vt_symbol": symbol,
                "name": str((quote or {}).get("name") or context.get("name") or symbol),
                "change_pct": float(change_pct),
                "last_price": price,
                "capture_state": "fill_followup",
                "formal_action": "pass",
                "early_action": "pass",
                "early_entry_kind": "none",
                "blocking_scope": "none",
                "decision_reason": "delayed_fill_quote_followup",
                "blocker_codes": [],
            }
        )
        rows.append(row)
    return rows


def save_frame(
    snapshot: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Atomically save one compact frame and all of its symbol observations."""

    captured_at = _required_datetime(snapshot.get("captured_at"))
    quality = snapshot.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    timing = quality.get("scan_timing_ms")
    timing = timing if isinstance(timing, Mapping) else {}
    values = {
        "trade_date": captured_at.date(),
        "captured_at": captured_at,
        "strategy_version": str(snapshot.get("strategy_version") or "unknown"),
        "contract_version": RADAR_CONTRACT_VERSION,
        "source": str(snapshot.get("source") or "unknown"),
        "source_updated_at": _optional_datetime(snapshot.get("source_updated_at")),
        "source_trade_date": _optional_date(snapshot.get("trade_date")),
        "quality_status": str(quality.get("status") or "unknown"),
        "is_stale": quality.get("is_stale") is not False,
        "capture_count": len(observations),
        "scan_duration_ms": _optional_integer(timing.get("total")),
        "quote_coverage_ratio": _optional_number(
            quality.get("concept_quote_coverage_ratio")
            if quality.get("concept_quote_coverage_ratio") is not None
            else quality.get("quote_coverage_ratio")
        ),
    }
    frame_table = schema.limit_up_radar_frames
    observation_table = schema.limit_up_radar_observations
    frame_insert = pg_insert(frame_table).values(**values)
    frame_insert = frame_insert.on_conflict_do_update(
        constraint="uq_limit_up_radar_frame_time_version",
        set_={
            key: getattr(frame_insert.excluded, key)
            for key in values
            if key not in {"captured_at", "strategy_version"}
        },
    ).returning(frame_table.c.id)
    with session_scope() as session:
        frame_id = int(session.execute(frame_insert).scalar_one())
        projected = [
            {"frame_id": frame_id, **dict(observation)}
            for observation in observations
        ]
        if projected:
            observation_insert = pg_insert(observation_table).values(projected)
            update_fields = {
                column.name: getattr(observation_insert.excluded, column.name)
                for column in observation_table.columns
                if column.name not in {"frame_id", "vt_symbol"}
            }
            session.execute(
                observation_insert.on_conflict_do_update(
                    index_elements=(
                        observation_table.c.frame_id,
                        observation_table.c.vt_symbol,
                    ),
                    set_=update_fields,
                )
            )
    _prune_once_for_trade_date(captured_at.date())
    return {"frame_id": frame_id, **values}


def load_observations(start: date, end: date) -> list[dict[str, object]]:
    """Load compact observations in point-in-time order."""

    frame = schema.limit_up_radar_frames
    observation = schema.limit_up_radar_observations
    statement = (
        select(
            frame.c.trade_date,
            frame.c.captured_at,
            frame.c.strategy_version,
            frame.c.contract_version,
            frame.c.source_updated_at,
            frame.c.source_trade_date,
            frame.c.quality_status,
            frame.c.is_stale,
            frame.c.scan_duration_ms,
            frame.c.quote_coverage_ratio,
            observation,
        )
        .select_from(observation.join(frame, observation.c.frame_id == frame.c.id))
        .where(frame.c.trade_date.between(start, end))
        .order_by(frame.c.captured_at, observation.c.vt_symbol)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def load_frame_coverage(
    start: date | None = None,
    end: date | None = None,
) -> dict[str, object]:
    """Return bounded coverage fields used by the validation gate."""

    frame = schema.limit_up_radar_frames
    statement = select(
        func.min(frame.c.trade_date),
        func.max(frame.c.trade_date),
        func.count(),
        func.count(func.distinct(frame.c.trade_date)),
        func.sum(frame.c.capture_count),
        func.count().filter(frame.c.is_stale.is_(False)),
        func.avg(frame.c.scan_duration_ms),
    )
    if start is not None:
        statement = statement.where(frame.c.trade_date >= start)
    if end is not None:
        statement = statement.where(frame.c.trade_date <= end)
    with session_scope() as session:
        row = session.execute(statement).one()
    frame_count = int(row[2] or 0)
    valid_count = int(row[5] or 0)
    return {
        "date_start": row[0].isoformat() if row[0] else None,
        "date_end": row[1].isoformat() if row[1] else None,
        "frame_count": frame_count,
        "trade_day_count": int(row[3] or 0),
        "observation_count": int(row[4] or 0),
        "valid_frame_count": valid_count,
        "valid_frame_ratio_pct": (
            round(valid_count / frame_count * 100, 4) if frame_count else None
        ),
        "average_scan_duration_ms": (
            round(float(row[6]), 3) if row[6] is not None else None
        ),
    }


def load_frame_dates(limit: int = RADAR_RETAIN_TRADE_DAYS) -> list[date]:
    statement = (
        select(schema.limit_up_radar_frames.c.trade_date)
        .distinct()
        .order_by(desc(schema.limit_up_radar_frames.c.trade_date))
        .limit(max(int(limit), 1))
    )
    with session_scope() as session:
        return list(session.execute(statement).scalars().all())


def prune_frames(retain_trade_days: int = RADAR_RETAIN_TRADE_DAYS) -> int:
    keep_count = max(int(retain_trade_days), 1)
    trade_dates = load_frame_dates(limit=keep_count + 1)
    cutoff = retention_cutoff(trade_dates, retain_trade_days=keep_count)
    if cutoff is None:
        return 0
    with session_scope() as session:
        result = session.execute(
            delete(schema.limit_up_radar_frames).where(
                schema.limit_up_radar_frames.c.trade_date < cutoff
            )
        )
    return max(int(result.rowcount or 0), 0)


def _prune_once_for_trade_date(trade_date: date) -> None:
    global _last_pruned_trade_date
    if _last_pruned_trade_date == trade_date:
        return
    with _prune_lock:
        if _last_pruned_trade_date == trade_date:
            return
        prune_frames()
        _last_pruned_trade_date = trade_date


def _blocker_codes(
    candidate: Mapping[str, object],
    signal: Mapping[str, object],
) -> list[str]:
    values: list[str] = []
    for key in ("lane_blockers", "pending_reasons"):
        source = candidate.get(key) if key == "lane_blockers" else signal.get(key)
        for value in source or []:
            text = str(value).strip()
            if text:
                values.append(text[:160])
    for raw in signal.get("trigger_checks") or []:
        if not isinstance(raw, Mapping) or raw.get("status") == "passed":
            continue
        code = str(raw.get("code") or "").strip()
        if code:
            values.append(code[:160])
    return list(dict.fromkeys(values))


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _optional_text(value: object, *, max_length: int | None = None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    return text[:max_length] if max_length is not None else text


def _required_number(value: object, field: str) -> float:
    number = _optional_number(value)
    if number is None:
        raise ValueError(f"{field} is required")
    return number


def _required_positive(value: object, field: str) -> float:
    number = _required_number(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number


def _optional_number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_integer(value: object) -> int | None:
    number = _optional_number(value)
    return int(number) if number is not None else None


def _required_datetime(value: object) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError("captured_at is required")
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _local_datetime(value: object) -> datetime:
    parsed = _required_datetime(value)
    return parsed.astimezone(scheduled_execution.SHANGHAI)


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if len(text) >= 10 and "-" in text[:10]:
        return date.fromisoformat(text[:10])
    digits = "".join(character for character in text if character.isdigit())
    return date.fromisoformat(
        f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    ) if len(digits) >= 8 else None
