"""Persistence for dated low-suction live recommendation snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


def save_live_snapshot(payload: Mapping[str, object]) -> None:
    """Upsert one trade-date snapshot without overwriting prior trading days."""

    now = datetime.now(timezone.utc)
    trade_date = _payload_trade_date(payload)
    values = {
        # Existing installations used id=1 for the only snapshot. A stable
        # date-derived id avoids a primary-key migration while allowing one row
        # per signal day.
        "id": trade_date.toordinal(),
        "trade_date": trade_date,
        "captured_at": _payload_captured_at(payload),
        "score_version": str(payload["score_version"]),
        "payload": _storage_payload(payload),
        "updated_at": now,
    }
    statement = pg_insert(schema.low_suction_live_snapshots).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[schema.low_suction_live_snapshots.c.trade_date],
        set_={
            "captured_at": statement.excluded.captured_at,
            "score_version": statement.excluded.score_version,
            "payload": statement.excluded.payload,
            "updated_at": now,
        },
    )
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(statement)


def load_live_snapshot(
    score_version: str,
    *,
    trade_date: date | None = None,
) -> dict[str, object] | None:
    """Return a current-version snapshot for a date or the newest saved day."""

    schema.ensure_schema_once(get_engine())
    statement = select(
        schema.low_suction_live_snapshots.c.score_version,
        schema.low_suction_live_snapshots.c.payload,
    ).where(schema.low_suction_live_snapshots.c.score_version == score_version)
    if trade_date is not None:
        statement = statement.where(
            schema.low_suction_live_snapshots.c.trade_date == trade_date
        )
    else:
        statement = statement.order_by(
            desc(schema.low_suction_live_snapshots.c.trade_date),
            desc(schema.low_suction_live_snapshots.c.captured_at),
        )
    statement = statement.limit(1)
    with session_scope() as session:
        row = session.execute(statement).mappings().one_or_none()
    if row is None or str(row["score_version"]) != score_version:
        return None
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        return None
    result = dict(payload)
    return result if str(result.get("score_version") or "") == score_version else None


def list_live_snapshot_dates(score_version: str) -> list[str]:
    """List saved current-version signal days for the recommendation selector."""

    schema.ensure_schema_once(get_engine())
    statement = (
        select(schema.low_suction_live_snapshots.c.trade_date)
        .where(schema.low_suction_live_snapshots.c.score_version == score_version)
        .order_by(desc(schema.low_suction_live_snapshots.c.trade_date))
    )
    with session_scope() as session:
        values = session.execute(statement).scalars().all()
    return [value.isoformat() for value in values if isinstance(value, date)]


def _storage_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Keep diagnostic traces and scanner-only fields out of the live snapshot."""

    return {
        str(key): value
        for key, value in payload.items()
        if not str(key).startswith("_") and key != "scan_trace"
    }


def _payload_trade_date(payload: Mapping[str, object]) -> date:
    value = payload.get("trade_date")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError("live snapshot trade_date must be an ISO date")


def _payload_captured_at(payload: Mapping[str, object]) -> datetime:
    value = payload.get("asof")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("live snapshot asof must be an ISO datetime")
