"""Atomic persistence for complete free forward security snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

from .baostock_security_source import (
    FORWARD_EVIDENCE_LEVEL,
    FORWARD_SECURITY_SOURCE,
    ForwardSecurityRecord,
    ForwardSecuritySnapshotResult,
)

MIN_FORWARD_MAIN_BOARD_SYMBOLS = 3_000


def replace_forward_security_snapshot(
    snapshot: ForwardSecuritySnapshotResult,
) -> int:
    """Replace one complete source-date snapshot and its scope atomically."""

    _validate_snapshot(snapshot)
    schema.ensure_schema_once(get_engine())
    records_table = schema.low_suction_security_snapshots
    scopes_table = schema.low_suction_security_snapshot_scopes
    record_values = [_record_values(record) for record in snapshot.records]
    scope_values = _scope_values(snapshot)

    with session_scope() as session:
        session.execute(
            delete(records_table).where(
                records_table.c.source_trade_date == snapshot.source_trade_date,
                records_table.c.source == snapshot.source,
            )
        )
        session.execute(
            delete(scopes_table).where(
                scopes_table.c.source_trade_date == snapshot.source_trade_date,
                scopes_table.c.source == snapshot.source,
            )
        )
        session.execute(insert(records_table), record_values)
        session.execute(insert(scopes_table), scope_values)
    return len(record_values)


def _validate_snapshot(snapshot: ForwardSecuritySnapshotResult) -> None:
    records = snapshot.records
    if not records:
        raise ValueError("forward security snapshot cannot be empty")
    _require_aware(snapshot.observed_at)
    if snapshot.missing_symbols:
        raise ValueError("forward security snapshot contains missing symbols")
    if (
        snapshot.expected_symbol_count != snapshot.returned_symbol_count
        or snapshot.returned_symbol_count != len(records)
    ):
        raise ValueError("forward security snapshot count mismatch")

    symbols = [record.vt_symbol for record in records]
    source_record_ids = [record.source_record_id for record in records]
    if len(symbols) != len(set(symbols)):
        raise ValueError("forward security snapshot symbols must be unique")
    if len(source_record_ids) != len(set(source_record_ids)):
        raise ValueError("forward security source record IDs must be unique")
    if snapshot.source != FORWARD_SECURITY_SOURCE:
        raise ValueError("forward security snapshot source is invalid")
    if snapshot.evidence_level != FORWARD_EVIDENCE_LEVEL:
        raise ValueError("forward security snapshot evidence level is invalid")

    for record in records:
        _validate_record(record, snapshot=snapshot)
    if snapshot.suspended_count != sum(record.suspended for record in records):
        raise ValueError("forward security suspended count mismatch")
    if snapshot.risk_warning_count != sum(
        record.risk_warning for record in records
    ):
        raise ValueError("forward security risk-warning count mismatch")
    if snapshot.total_master_rows < snapshot.expected_symbol_count:
        raise ValueError("forward security master total is smaller than expected scope")
    if snapshot.total_daily_rows < snapshot.returned_symbol_count:
        raise ValueError("forward security daily total is smaller than returned scope")
    if snapshot.expected_symbol_count < MIN_FORWARD_MAIN_BOARD_SYMBOLS:
        raise ValueError(
            "forward security snapshot is below the minimum main-board universe: "
            f"expected={snapshot.expected_symbol_count} "
            f"minimum={MIN_FORWARD_MAIN_BOARD_SYMBOLS}"
        )


def _validate_record(
    record: ForwardSecurityRecord,
    *,
    snapshot: ForwardSecuritySnapshotResult,
) -> None:
    _require_aware(record.observed_at)
    if record.source_trade_date != snapshot.source_trade_date:
        raise ValueError("forward security record source date does not match snapshot")
    if record.observed_at != snapshot.observed_at:
        raise ValueError("forward security record observation time does not match snapshot")
    if record.source != snapshot.source:
        raise ValueError("forward security record source does not match snapshot")
    if record.evidence_level != snapshot.evidence_level:
        raise ValueError("forward security record evidence level does not match snapshot")
    if record.board != "main":
        raise ValueError("forward security record must belong to the main board")
    if record.vt_symbol != f"{record.symbol}.{record.exchange}":
        raise ValueError("forward security record vt_symbol is inconsistent")
    if record.listed_on > snapshot.source_trade_date:
        raise ValueError("forward security record was not listed on the source date")
    if (
        record.delisted_on is not None
        and record.delisted_on <= snapshot.source_trade_date
    ):
        raise ValueError(
            "forward security record was delisted on or before the source date"
        )


def _record_values(record: ForwardSecurityRecord) -> dict[str, object]:
    return {
        "source_trade_date": record.source_trade_date,
        "vt_symbol": record.vt_symbol,
        "source": record.source,
        "observed_at": record.observed_at.astimezone(timezone.utc),
        "symbol": record.symbol,
        "exchange": record.exchange,
        "name": record.name,
        "status": record.status,
        "board": record.board,
        "listed_on": record.listed_on,
        "delisted_on": record.delisted_on,
        "suspended": record.suspended,
        "risk_warning": record.risk_warning,
        "evidence_level": record.evidence_level,
        "source_record_id": record.source_record_id,
        "raw": {
            "provider_code": record.source_code,
            "trade_status": record.trade_status,
        },
    }


def _scope_values(snapshot: ForwardSecuritySnapshotResult) -> dict[str, object]:
    return {
        "source_trade_date": snapshot.source_trade_date,
        "source": snapshot.source,
        "observed_at": snapshot.observed_at.astimezone(timezone.utc),
        "expected_symbol_count": snapshot.expected_symbol_count,
        "returned_symbol_count": snapshot.returned_symbol_count,
        "total_master_rows": snapshot.total_master_rows,
        "total_daily_rows": snapshot.total_daily_rows,
        "suspended_count": snapshot.suspended_count,
        "risk_warning_count": snapshot.risk_warning_count,
        "complete": True,
        "evidence_level": snapshot.evidence_level,
        "raw": {"missing_symbols": list(snapshot.missing_symbols)},
    }


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("forward security observation time must include a timezone")
