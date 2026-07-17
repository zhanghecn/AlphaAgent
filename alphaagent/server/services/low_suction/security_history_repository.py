"""Atomic persistence for low-suction historical security status."""

from __future__ import annotations

from sqlalchemy import delete, insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

from .historical_inputs import HistoricalSecurityBatch, HistoricalSecurityRecord


def replace_security_history(batch: HistoricalSecurityBatch) -> int:
    """Replace one provider's complete symbol scope in one transaction."""

    symbols = _validate_batch(batch)
    schema.ensure_schema_once(get_engine())
    table = schema.low_suction_security_history
    scope_table = schema.low_suction_security_history_scopes
    values = [_record_values(record) for record in batch.records]
    scope_values = [
        {
            "trade_date": trade_date,
            "vt_symbol": vt_symbol,
            "evidence_level": batch.evidence_level,
            "source": batch.source,
        }
        for trade_date, vt_symbol in batch.required_pairs
    ]
    with session_scope() as session:
        session.execute(
            delete(table).where(
                table.c.source == batch.source,
                table.c.vt_symbol.in_(symbols),
            )
        )
        session.execute(
            delete(scope_table).where(
                scope_table.c.source == batch.source,
                scope_table.c.vt_symbol.in_(symbols),
            )
        )
        session.execute(insert(table), values)
        session.execute(insert(scope_table), scope_values)
    return len(values)


def _validate_batch(batch: HistoricalSecurityBatch) -> tuple[str, ...]:
    if not batch.required_pairs:
        raise ValueError("security replacement scope cannot be empty")
    if not batch.records:
        raise ValueError("security replacement records cannot be empty")
    if not batch.source.strip():
        raise ValueError("security replacement source cannot be empty")

    symbols = tuple(sorted({vt_symbol for _, vt_symbol in batch.required_pairs}))
    symbol_scope = set(symbols)
    outside_scope = sorted(
        {
            record.vt_symbol
            for record in batch.records
            if record.vt_symbol not in symbol_scope
        }
    )
    if outside_scope:
        raise ValueError(
            "security history record is outside declared symbol scope: "
            + ", ".join(outside_scope)
        )
    if any(record.source != batch.source for record in batch.records):
        raise ValueError("security history record source does not match batch")
    if any(
        record.evidence_level != batch.evidence_level for record in batch.records
    ):
        raise ValueError("security history evidence level does not match batch")
    source_ids = [record.source_record_id for record in batch.records]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("security history source_record_id must be unique")
    return symbols


def _record_values(record: HistoricalSecurityRecord) -> dict[str, object]:
    return {
        "vt_symbol": record.vt_symbol,
        "symbol": record.symbol,
        "exchange": record.exchange,
        "name": record.name,
        "status": record.status,
        "board": record.board,
        "listed_on": record.listed_on,
        "delisted_on": record.delisted_on,
        "valid_from": record.valid_from,
        "valid_to": record.valid_to,
        "suspended": record.suspended,
        "risk_warning": record.risk_warning,
        "known_at": record.known_at,
        "evidence_level": record.evidence_level,
        "source": record.source,
        "source_record_id": record.source_record_id,
    }
