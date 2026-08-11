"""Persistence for the latest low-suction live recommendation snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


_SNAPSHOT_ID = 1


def save_live_snapshot(payload: Mapping[str, object]) -> None:
    """Atomically replace the one readable live snapshot."""

    now = datetime.now(timezone.utc)
    values = {
        "id": _SNAPSHOT_ID,
        "trade_date": _payload_trade_date(payload),
        "captured_at": _payload_captured_at(payload),
        "score_version": str(payload["score_version"]),
        "payload": _storage_payload(payload),
        "updated_at": now,
    }
    statement = pg_insert(schema.low_suction_live_snapshots).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[schema.low_suction_live_snapshots.c.id],
        set_={
            "trade_date": statement.excluded.trade_date,
            "captured_at": statement.excluded.captured_at,
            "score_version": statement.excluded.score_version,
            "payload": statement.excluded.payload,
            "updated_at": now,
        },
    )
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(statement)


def load_live_snapshot(score_version: str) -> dict[str, object] | None:
    """Return the current-version snapshot, rejecting stale factor output."""

    schema.ensure_schema_once(get_engine())
    statement = select(
        schema.low_suction_live_snapshots.c.score_version,
        schema.low_suction_live_snapshots.c.payload,
    ).where(schema.low_suction_live_snapshots.c.id == _SNAPSHOT_ID)
    with session_scope() as session:
        row = session.execute(statement).mappings().one_or_none()
    if row is None or str(row["score_version"]) != score_version:
        return None
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        return None
    result = dict(payload)
    return result if str(result.get("score_version") or "") == score_version else None


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
