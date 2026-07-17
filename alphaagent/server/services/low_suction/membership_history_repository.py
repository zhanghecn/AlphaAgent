"""Atomic persistence for strict low-suction concept memberships."""

from __future__ import annotations

from sqlalchemy import delete, insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

from .historical_inputs import (
    HistoricalMembershipBatch,
    HistoricalMembershipRecord,
    HistoricalMembershipScope,
)


def replace_membership_history(batch: HistoricalMembershipBatch) -> int:
    """Replace one provider's complete history and scopes in one transaction."""

    _validate_batch(batch)
    schema.ensure_schema_once(get_engine())
    history = schema.low_suction_concept_membership_history
    scopes = schema.low_suction_concept_membership_scopes
    history_values = [_record_values(record) for record in batch.records]
    scope_values = [_scope_values(scope) for scope in batch.scopes]
    with session_scope() as session:
        session.execute(delete(history).where(history.c.source == batch.source))
        session.execute(delete(scopes).where(scopes.c.source == batch.source))
        session.execute(insert(history), history_values)
        session.execute(insert(scopes), scope_values)
    return len(history_values)


def _validate_batch(batch: HistoricalMembershipBatch) -> None:
    if not batch.required_pairs:
        raise ValueError("membership replacement scope cannot be empty")
    if not batch.records or not batch.scopes:
        raise ValueError("membership history and scopes cannot be empty")
    if not batch.source.strip():
        raise ValueError("membership source cannot be empty")

    required_pairs = set(batch.required_pairs)
    scope_pairs = {(scope.trade_date, scope.sector_id) for scope in batch.scopes}
    if len(scope_pairs) != len(batch.scopes) or scope_pairs != required_pairs:
        raise ValueError("membership scopes must exactly match required pairs")
    sector_scope = {sector_id for _, sector_id in required_pairs}
    outside_scope = sorted(
        {record.sector_id for record in batch.records if record.sector_id not in sector_scope}
    )
    if outside_scope:
        raise ValueError(
            "membership record is outside declared sector scope: "
            + ", ".join(outside_scope)
        )

    _validate_record_identity(batch)
    _validate_scope_identity(batch)


def _validate_record_identity(batch: HistoricalMembershipBatch) -> None:
    if any(record.source != batch.source for record in batch.records):
        raise ValueError("membership record source does not match batch")
    if any(
        record.evidence_level != batch.evidence_level for record in batch.records
    ):
        raise ValueError("membership record evidence level does not match batch")
    source_ids = [record.source_record_id for record in batch.records]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("membership source_record_id must be unique")


def _validate_scope_identity(batch: HistoricalMembershipBatch) -> None:
    if any(scope.source != batch.source for scope in batch.scopes):
        raise ValueError("membership scope source does not match batch")
    if any(scope.evidence_level != batch.evidence_level for scope in batch.scopes):
        raise ValueError("membership scope evidence level does not match batch")
    request_ids = [scope.source_request_id for scope in batch.scopes]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("membership source_request_id must be unique")


def _record_values(record: HistoricalMembershipRecord) -> dict[str, object]:
    return {
        "sector_id": record.sector_id,
        "sector_name": record.sector_name,
        "vt_symbol": record.vt_symbol,
        "in_date": record.in_date,
        "out_date": record.out_date,
        "known_at": record.known_at,
        "evidence_level": record.evidence_level,
        "source": record.source,
        "source_record_id": record.source_record_id,
        "raw": {},
    }


def _scope_values(scope: HistoricalMembershipScope) -> dict[str, object]:
    return {
        "trade_date": scope.trade_date,
        "source_trade_date": scope.source_trade_date,
        "sector_id": scope.sector_id,
        "expected_member_count": scope.expected_member_count,
        "returned_member_count": scope.returned_member_count,
        "pagination_complete": scope.pagination_complete,
        "known_at": scope.known_at,
        "evidence_level": scope.evidence_level,
        "source": scope.source,
        "source_request_id": scope.source_request_id,
        "raw": {},
    }
