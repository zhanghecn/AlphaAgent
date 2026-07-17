"""Atomic persistence for low-suction forward membership scopes."""

from __future__ import annotations

from sqlalchemy import delete, insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

from .forward_membership import (
    CATALOG_SCOPE_TYPE,
    TRADABLE_SCOPE_TYPE,
    ForwardMembershipCapture,
    ForwardMembershipRecord,
    ForwardMembershipScope,
)


def save_forward_membership_capture(capture: ForwardMembershipCapture) -> int:
    """Persist a complete capture, or only its non-strict catalog observation."""

    _validate_capture(capture)
    schema.ensure_schema_once(get_engine())
    records = schema.low_suction_forward_membership_snapshots
    scopes = schema.low_suction_forward_membership_snapshot_scopes
    source_date = capture.catalog_scope.source_trade_date
    source = capture.catalog_scope.source

    if capture.tradable_scope.complete:
        with session_scope() as session:
            session.execute(
                delete(records).where(
                    records.c.source_trade_date == source_date,
                    records.c.source == source,
                )
            )
            session.execute(
                delete(scopes).where(
                    scopes.c.source_trade_date == source_date,
                    scopes.c.source == source,
                )
            )
            session.execute(
                insert(records),
                [_record_values(record) for record in capture.records],
            )
            session.execute(
                insert(scopes),
                [_scope_values(scope) for scope in capture.scopes],
            )
        return len(capture.records)

    with session_scope() as session:
        session.execute(
            delete(scopes).where(
                scopes.c.source_trade_date == source_date,
                scopes.c.scope_type == CATALOG_SCOPE_TYPE,
                scopes.c.source == source,
            )
        )
        session.execute(
            insert(scopes),
            [_scope_values(capture.catalog_scope)],
        )
    return 0


def _validate_capture(capture: ForwardMembershipCapture) -> None:
    catalog = capture.catalog_scope
    tradable = capture.tradable_scope
    if catalog.scope_type != CATALOG_SCOPE_TYPE:
        raise ValueError("capture requires one concept_catalog scope")
    if tradable.scope_type != TRADABLE_SCOPE_TYPE:
        raise ValueError("capture requires one concept_tradable scope")
    if (
        catalog.source_trade_date != tradable.source_trade_date
        or catalog.observed_at != tradable.observed_at
        or catalog.source != tradable.source
        or catalog.manifest_version != tradable.manifest_version
    ):
        raise ValueError("forward membership scopes must share one capture identity")

    if not tradable.complete:
        if capture.records:
            raise ValueError("partial tradable capture cannot contain strict records")
        if tradable.evidence_level == "strict":
            raise ValueError("partial tradable capture cannot claim strict evidence")
        return

    if tradable.evidence_level != "strict":
        raise ValueError("complete tradable capture requires strict evidence")
    if not capture.records:
        raise ValueError("complete tradable capture records cannot be empty")
    if tradable.expected_sector_count != tradable.returned_sector_count:
        raise ValueError("complete tradable capture sector count does not close")
    if tradable.row_count != len(capture.records):
        raise ValueError("complete tradable capture row count does not match records")

    record_sectors = {record.sector_id for record in capture.records}
    record_symbols = {record.vt_symbol for record in capture.records}
    if len(record_sectors) != tradable.expected_sector_count:
        raise ValueError("complete tradable capture sector count does not match records")
    if len(record_symbols) != tradable.symbol_count:
        raise ValueError("complete tradable capture symbol count does not match records")
    for record in capture.records:
        _validate_record_identity(record, tradable)


def _validate_record_identity(
    record: ForwardMembershipRecord,
    scope: ForwardMembershipScope,
) -> None:
    if (
        record.source_trade_date != scope.source_trade_date
        or record.observed_at != scope.observed_at
        or record.source != scope.source
        or record.evidence_level != "strict"
    ):
        raise ValueError("forward membership record does not match strict scope")
    if record.raw.get("manifest_version") != scope.manifest_version:
        raise ValueError("forward membership record manifest version does not match scope")


def _record_values(record: ForwardMembershipRecord) -> dict[str, object]:
    return {
        "source_trade_date": record.source_trade_date,
        "sector_id": record.sector_id,
        "vt_symbol": record.vt_symbol,
        "source": record.source,
        "observed_at": record.observed_at,
        "sector_name": record.sector_name,
        "sector_type": record.sector_type,
        "manifest_class": record.manifest_class,
        "evidence_level": record.evidence_level,
        "raw": record.raw,
    }


def _scope_values(scope: ForwardMembershipScope) -> dict[str, object]:
    return {
        "source_trade_date": scope.source_trade_date,
        "scope_type": scope.scope_type,
        "source": scope.source,
        "observed_at": scope.observed_at,
        "expected_sector_count": scope.expected_sector_count,
        "returned_sector_count": scope.returned_sector_count,
        "row_count": scope.row_count,
        "symbol_count": scope.symbol_count,
        "complete": scope.complete,
        "evidence_level": scope.evidence_level,
        "manifest_version": scope.manifest_version,
        "raw": scope.raw,
    }
