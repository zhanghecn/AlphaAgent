"""Fail-closed Tushare DC membership probe and atomic import service."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import func, select

from alphaagent.server.core.config import get_settings
from alphaagent.server.db import schema
from alphaagent.server.db.session import (
    get_engine,
    is_database_configured,
    session_scope,
)
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
from alphaagent.server.services.data_providers.tushare_dc_membership import (
    DC_MEMBER_SOURCE,
    TushareDcMembershipClient,
    TushareDcQueryResult,
    dc_membership_source_status,
    local_sector_id,
    tushare_sector_code,
)

from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
from .contracts import CONCEPT_SECTOR_TYPES
from .dc_membership_normalization import (
    MEMBERSHIP_KNOWN_TIME,
    SHANGHAI,
    NormalizedDcMember,
    compress_daily_memberships,
    normalize_dc_snapshot,
)
from .historical_inputs import (
    HistoricalMembershipImportReport,
    HistoricalMembershipRecord,
    HistoricalMembershipScope,
    import_historical_memberships,
)
from .membership_history_repository import replace_membership_history

MIN_EXACT_SECTOR_MAPPING_PCT = 99.0
MIN_RELIABLE_STOCK_SYMBOLS = 3_000
MAX_IMPORT_DATES = 800


class DcMembershipImportError(RuntimeError):
    """Raised when an exact, complete DC membership payload cannot be built."""


class DcMembershipClient(Protocol):
    def query_index(self, trade_date: date) -> TushareDcQueryResult: ...

    def query_members(
        self,
        *,
        sector_code: str,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TushareDcQueryResult: ...


@dataclass(frozen=True)
class LocalConcept:
    sector_id: str
    name: str
    first_bar_date: date
    last_bar_date: date


@dataclass(frozen=True)
class DcMembershipPayload:
    records: tuple[HistoricalMembershipRecord, ...]
    scopes: tuple[HistoricalMembershipScope, ...]
    required_pairs: tuple[tuple[date, str], ...]
    source_dates: tuple[date, ...]
    mapping_pct: float
    expected_sector_pairs: int
    mapped_sector_pairs: int
    unmapped_pairs: tuple[str, ...]
    name_conflicts: tuple[str, ...]


def membership_source_status() -> dict[str, object]:
    settings = get_settings()
    return {
        **dc_membership_source_status(token=settings.tushare_token),
        "source": DC_MEMBER_SOURCE,
        "history_url": "https://tushare.pro/document/2?doc_id=363",
        "index_url": "https://tushare.pro/document/2?doc_id=362",
    }


def build_dc_membership_payload(
    *,
    client: DcMembershipClient,
    research_source_dates: Mapping[date, date],
    concepts: Sequence[LocalConcept],
    fetched_at: datetime | None = None,
) -> DcMembershipPayload:
    date_pairs = _validated_date_pairs(research_source_dates)
    concept_by_id = _concept_map(concepts)
    observed_at = fetched_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")

    source_index = _load_source_index(client, {source for _, source in date_pairs})
    mapped_pairs: list[tuple[date, date, LocalConcept]] = []
    required_pairs: set[tuple[date, str]] = set()
    unmapped: list[str] = []
    name_conflicts: list[str] = []
    expected_count = 0
    for research_date, source_date in date_pairs:
        active = [
            concept
            for concept in concept_by_id.values()
            if concept.first_bar_date <= research_date <= concept.last_bar_date
        ]
        if not active:
            raise DcMembershipImportError(
                f"no active local concepts for {research_date.isoformat()}"
            )
        expected_count += len(active)
        source_rows = source_index[source_date]
        for concept in active:
            required_pairs.add((research_date, concept.sector_id))
            source_name = source_rows.get(concept.sector_id)
            if source_name is None:
                unmapped.append(f"{research_date.isoformat()}:{concept.sector_id}")
                continue
            mapped_pairs.append((research_date, source_date, concept))
            if source_name != concept.name:
                name_conflicts.append(
                    f"{research_date.isoformat()}:{concept.sector_id}:"
                    f"{concept.name}!={source_name}"
                )

    mapping_pct = round(len(mapped_pairs) / expected_count * 100.0, 4)
    if mapping_pct < MIN_EXACT_SECTOR_MAPPING_PCT:
        raise DcMembershipImportError(
            f"exact mapping coverage {mapping_pct:.4f}% is below "
            f"{MIN_EXACT_SECTOR_MAPPING_PCT:.1f}%"
        )

    members = _load_member_rows(client, mapped_pairs)
    normalized: list[NormalizedDcMember] = []
    scopes: list[HistoricalMembershipScope] = []
    for research_date, source_date, concept in mapped_pairs:
        rows = members.get((source_date, concept.sector_id), ())
        if not rows:
            raise DcMembershipImportError(
                f"empty member response for {source_date}:{concept.sector_id}"
            )
        daily = normalize_dc_snapshot(
            source_trade_date=source_date,
            effective_trade_date=research_date,
            sector_id=concept.sector_id,
            sector_name=concept.name,
            members=rows,
            fetched_at=observed_at,
        )
        normalized.extend(daily)
        scopes.append(
            _membership_scope(
                research_date=research_date,
                source_date=source_date,
                sector_id=concept.sector_id,
                member_count=len(daily),
            )
        )

    effective_dates = tuple(research_date for research_date, _ in date_pairs)
    records = compress_daily_memberships(
        normalized,
        effective_dates=effective_dates,
        terminal_out_date=effective_dates[-1] + timedelta(days=1),
    )
    return DcMembershipPayload(
        records=records,
        scopes=tuple(sorted(scopes, key=lambda row: (row.trade_date, row.sector_id))),
        required_pairs=tuple(sorted(required_pairs)),
        source_dates=tuple(source for _, source in date_pairs),
        mapping_pct=mapping_pct,
        expected_sector_pairs=expected_count,
        mapped_sector_pairs=len(mapped_pairs),
        unmapped_pairs=tuple(sorted(unmapped)),
        name_conflicts=tuple(sorted(name_conflicts)),
    )


def validate_dc_membership_payload(
    payload: DcMembershipPayload,
    *,
    dry_run: bool,
) -> HistoricalMembershipImportReport:
    return import_historical_memberships(
        membership_rows=[_record_mapping(record) for record in payload.records],
        membership_scope_rows=[_scope_mapping(scope) for scope in payload.scopes],
        required_pairs=payload.required_pairs,
        writer=replace_membership_history,
        dry_run=dry_run,
    )


def run_dc_membership_import(
    *,
    start_date: date,
    end_date: date,
    max_dates: int,
    dry_run: bool,
) -> dict[str, Any]:
    status = membership_source_status()
    if not bool(status["configured"]):
        return {
            **status,
            "dataset": "historical_concept_membership",
            "dry_run": dry_run,
            "rows_written": 0,
        }
    if not is_database_configured():
        return {
            **status,
            "status": "unavailable",
            "reason": "DATABASE_URL not configured",
            "dataset": "historical_concept_membership",
            "dry_run": dry_run,
            "rows_written": 0,
        }
    try:
        settings = get_settings()
        client = TushareDcMembershipClient(
            token=settings.tushare_token,
            api_url=settings.tushare_api_url,
            timeout=settings.tushare_timeout_seconds,
        )
        research_source_dates = _load_research_source_dates(
            start_date=start_date,
            end_date=end_date,
            max_dates=max_dates,
        )
        concepts = _load_local_concepts()
        payload = build_dc_membership_payload(
            client=client,
            research_source_dates=research_source_dates,
            concepts=concepts,
        )
        validation = validate_dc_membership_payload(payload, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - CLI returns a safe provider boundary
        reason = str(exc)[:500] if isinstance(exc, DcMembershipImportError) else exc.__class__.__name__
        return {
            **status,
            "status": "rejected",
            "strict_ready": False,
            "dataset": "historical_concept_membership",
            "dry_run": dry_run,
            "rows_written": 0,
            "reason": reason,
        }
    return {
        **status,
        **validation.as_dict(),
        "status": validation.status,
        "strict_ready": validation.status in {"ready_for_atomic_replace", "replaced"},
        "dataset": "historical_concept_membership",
        "requested_start": start_date.isoformat(),
        "requested_end": end_date.isoformat(),
        "research_dates": len(research_source_dates),
        "source_start": min(payload.source_dates).isoformat(),
        "source_end": max(payload.source_dates).isoformat(),
        "mapping_pct": payload.mapping_pct,
        "expected_sector_pairs": payload.expected_sector_pairs,
        "mapped_sector_pairs": payload.mapped_sector_pairs,
        "unmapped_pairs": list(payload.unmapped_pairs),
        "name_conflicts": list(payload.name_conflicts),
        "rows_written": validation.membership_rows if validation.written else 0,
    }


def _validated_date_pairs(
    values: Mapping[date, date],
) -> tuple[tuple[date, date], ...]:
    pairs = tuple(sorted(values.items()))
    if not pairs:
        raise DcMembershipImportError("research/source date pairs cannot be empty")
    if len(pairs) > MAX_IMPORT_DATES:
        raise DcMembershipImportError(
            f"membership import cannot exceed {MAX_IMPORT_DATES} research dates"
        )
    for research_date, source_date in pairs:
        if source_date >= research_date:
            raise DcMembershipImportError(
                "each source date must precede its research date"
            )
    return pairs


def _concept_map(concepts: Sequence[LocalConcept]) -> dict[str, LocalConcept]:
    result: dict[str, LocalConcept] = {}
    for concept in concepts:
        if concept.sector_id in result:
            raise DcMembershipImportError(
                f"duplicate local concept ID: {concept.sector_id}"
            )
        result[concept.sector_id] = concept
    if not result:
        raise DcMembershipImportError("local concept inventory cannot be empty")
    return result


def _load_source_index(
    client: DcMembershipClient,
    source_dates: set[date],
) -> dict[date, dict[str, str]]:
    result: dict[date, dict[str, str]] = {}
    for source_date in sorted(source_dates):
        response = client.query_index(source_date)
        if response.limit_reached:
            raise DcMembershipImportError(
                f"dc_index reached provider row limit on {source_date}"
            )
        daily: dict[str, str] = {}
        for row in response.rows:
            if str(row.get("idx_type") or "").strip() != "概念板块":
                continue
            row_date = _source_date(row.get("trade_date"))
            if row_date != source_date:
                raise DcMembershipImportError("dc_index returned a mismatched trade date")
            sector_id = local_sector_id(str(row.get("ts_code") or ""))
            if sector_id in daily:
                raise DcMembershipImportError(
                    f"dc_index returned duplicate sector {sector_id}"
                )
            daily[sector_id] = str(row.get("name") or "").strip()
        result[source_date] = daily
    return result


def _load_member_rows(
    client: DcMembershipClient,
    mapped_pairs: Sequence[tuple[date, date, LocalConcept]],
) -> dict[tuple[date, str], tuple[dict[str, Any], ...]]:
    source_dates_by_sector: dict[str, set[date]] = defaultdict(set)
    for _, source_date, concept in mapped_pairs:
        source_dates_by_sector[concept.sector_id].add(source_date)
    result: dict[tuple[date, str], tuple[dict[str, Any], ...]] = {}
    for sector_id, source_dates in sorted(source_dates_by_sector.items()):
        rows = _query_member_windows(
            client,
            sector_code=tushare_sector_code(sector_id),
            source_dates=tuple(sorted(source_dates)),
        )
        grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            row_date = _source_date(row.get("trade_date"))
            if row_date not in source_dates:
                continue
            if local_sector_id(str(row.get("ts_code") or "")) != sector_id:
                raise DcMembershipImportError("dc_member returned a mismatched sector code")
            grouped[row_date].append(dict(row))
        for source_date in source_dates:
            result[(source_date, sector_id)] = tuple(grouped.get(source_date, ()))
    return result


def _query_member_windows(
    client: DcMembershipClient,
    *,
    sector_code: str,
    source_dates: Sequence[date],
) -> tuple[dict[str, Any], ...]:
    dates = tuple(sorted(set(source_dates)))
    if not dates:
        return ()
    if len(dates) == 1:
        response = client.query_members(
            sector_code=sector_code,
            trade_date=dates[0],
        )
    else:
        response = client.query_members(
            sector_code=sector_code,
            start_date=dates[0],
            end_date=dates[-1],
        )
    if not response.limit_reached:
        return response.rows
    if len(dates) == 1:
        raise DcMembershipImportError(
            f"dc_member reached provider row limit for {sector_code} on {dates[0]}"
        )
    midpoint = len(dates) // 2
    return (
        *_query_member_windows(
            client,
            sector_code=sector_code,
            source_dates=dates[:midpoint],
        ),
        *_query_member_windows(
            client,
            sector_code=sector_code,
            source_dates=dates[midpoint:],
        ),
    )


def _membership_scope(
    *,
    research_date: date,
    source_date: date,
    sector_id: str,
    member_count: int,
) -> HistoricalMembershipScope:
    known_at = datetime.combine(
        source_date,
        MEMBERSHIP_KNOWN_TIME,
        tzinfo=SHANGHAI,
    )
    request_material = f"{DC_MEMBER_SOURCE}|{research_date}|{source_date}|{sector_id}"
    request_id = hashlib.sha256(request_material.encode("utf-8")).hexdigest()[:24]
    return HistoricalMembershipScope(
        trade_date=research_date,
        source_trade_date=source_date,
        sector_id=sector_id,
        expected_member_count=member_count,
        returned_member_count=member_count,
        pagination_complete=True,
        known_at=known_at,
        evidence_level="strict",
        source=DC_MEMBER_SOURCE,
        source_request_id=f"dc-scope:{request_id}",
    )


def _record_mapping(record: HistoricalMembershipRecord) -> dict[str, Any]:
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
    }


def _scope_mapping(scope: HistoricalMembershipScope) -> dict[str, Any]:
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
    }


def _source_date(value: Any) -> date:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DcMembershipImportError("provider returned an invalid trade date") from exc


def _load_research_source_dates(
    *,
    start_date: date,
    end_date: date,
    max_dates: int,
) -> dict[date, date]:
    if start_date > end_date:
        raise DcMembershipImportError("start_date must not be after end_date")
    cap = min(max(int(max_dates), 1), MAX_IMPORT_DATES)
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .where(
                schema.stock_daily_bars.c.trade_date <= end_date,
                schema.stock_daily_bars.c.trade_date <= completed_daily_bar_cutoff(),
            )
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(
                func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
                >= MIN_RELIABLE_STOCK_SYMBOLS
            )
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).scalars().all()
    calendar = tuple(value for value in rows if isinstance(value, date))
    selected = [value for value in calendar if start_date <= value <= end_date][:cap]
    result: dict[date, date] = {}
    positions = {value: index for index, value in enumerate(calendar)}
    for research_date in selected:
        position = positions[research_date]
        if position > 0:
            result[research_date] = calendar[position - 1]
    if not result:
        raise DcMembershipImportError("no laggable reliable research dates in range")
    return result


def _load_local_concepts() -> tuple[LocalConcept, ...]:
    bars = schema.sector_daily_bars
    sectors = schema.sectors
    with session_scope() as session:
        rows = session.execute(
            select(
                bars.c.sector_id,
                sectors.c.name,
                func.min(bars.c.trade_date),
                func.max(bars.c.trade_date),
            )
            .select_from(bars.join(sectors, bars.c.sector_id == sectors.c.id))
            .where(
                sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
                bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            )
            .group_by(bars.c.sector_id, sectors.c.name)
            .order_by(bars.c.sector_id)
        ).all()
    return tuple(
        LocalConcept(
            sector_id=str(row[0]),
            name=str(row[1]),
            first_bar_date=row[2],
            last_bar_date=row[3],
        )
        for row in rows
        if isinstance(row[2], date) and isinstance(row[3], date)
    )
