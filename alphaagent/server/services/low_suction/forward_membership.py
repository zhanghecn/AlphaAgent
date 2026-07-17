"""Build auditable low-suction scopes from one forward membership capture."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from alphaagent.market.symbols import normalize_exchange, vt_symbol

from .contracts import CONCEPT_SECTOR_TYPES
from .theme_reference_cohorts import (
    MANIFEST_VERSION,
    REFERENCE_MANIFEST,
    ThemeManifestRecord,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
POST_CLOSE_START = time(15, 0)
CATALOG_SCOPE_TYPE = "concept_catalog"
TRADABLE_SCOPE_TYPE = "concept_tradable"
FORWARD_MEMBERSHIP_SOURCE = "eastmoney.push2.board.forward"
RAW_PROVIDER_SOURCE = "eastmoney.push2.board"
EXCLUDED_MANIFEST_CLASSES = frozenset(
    {"mechanical_event", "style_universe", "report_event", "ambiguous"}
)


class ForwardMembershipCaptureError(ValueError):
    """Raised when a capture cannot prove its declared point-in-time scope."""


@dataclass(frozen=True)
class ForwardMembershipRecord:
    source_trade_date: date
    observed_at: datetime
    sector_id: str
    sector_name: str
    sector_type: str
    vt_symbol: str
    manifest_class: str
    evidence_level: str
    source: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardMembershipScope:
    scope_type: str
    source_trade_date: date
    observed_at: datetime
    expected_sector_count: int
    returned_sector_count: int
    row_count: int
    symbol_count: int
    complete: bool
    evidence_level: str
    source: str
    manifest_version: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardMembershipCapture:
    records: tuple[ForwardMembershipRecord, ...]
    catalog_scope: ForwardMembershipScope
    tradable_scope: ForwardMembershipScope

    @property
    def scopes(self) -> tuple[ForwardMembershipScope, ForwardMembershipScope]:
        return (self.catalog_scope, self.tradable_scope)


def build_forward_membership_capture(
    *,
    sectors: Sequence[Mapping[str, Any]],
    members_by_sector: Mapping[str, Sequence[Mapping[str, Any]]],
    failed_sector_ids: Sequence[str],
    source_trade_date: date,
    observed_at: datetime,
    manifest: Mapping[str, ThemeManifestRecord] = REFERENCE_MANIFEST,
    manifest_version: str = MANIFEST_VERSION,
) -> ForwardMembershipCapture:
    """Build catalog and tradable scopes without using board names as rules."""

    observed = _validated_observation(source_trade_date, observed_at)
    version = str(manifest_version or "").strip()
    if not version:
        raise ForwardMembershipCaptureError("manifest version is required")

    catalog = _concept_catalog(sectors)
    normalized_members = _normalized_members_by_sector(members_by_sector)
    failed = {_sector_id(value) for value in failed_sector_ids if str(value).strip()}
    captured = {
        sector_id
        for sector_id, members in normalized_members.items()
        if sector_id in catalog and sector_id not in failed and members
    }
    missing_catalog = sorted(set(catalog) - captured)
    exclusions = _manifest_exclusions(catalog, manifest)
    excluded_ids = {row["sector_id"] for row in exclusions}
    expected_tradable = set(catalog) - excluded_ids
    returned_tradable = expected_tradable & captured
    missing_tradable = sorted(expected_tradable - returned_tradable)
    tradable_complete = bool(expected_tradable) and not missing_tradable

    records = (
        _build_records(
            sector_ids=sorted(expected_tradable),
            catalog=catalog,
            members_by_sector=normalized_members,
            manifest=manifest,
            source_trade_date=source_trade_date,
            observed_at=observed,
            manifest_version=version,
        )
        if tradable_complete
        else ()
    )
    catalog_row_count, catalog_symbol_count = _catalog_counts(
        captured,
        normalized_members,
    )
    common_raw: dict[str, object] = {
        "manifest_version": version,
        "catalog_sector_count": len(catalog),
        "failed_sector_ids": sorted(failed & set(catalog)),
        "excluded_sectors": exclusions,
    }
    catalog_scope = ForwardMembershipScope(
        scope_type=CATALOG_SCOPE_TYPE,
        source_trade_date=source_trade_date,
        observed_at=observed,
        expected_sector_count=len(catalog),
        returned_sector_count=len(captured),
        row_count=catalog_row_count,
        symbol_count=catalog_symbol_count,
        complete=not missing_catalog,
        evidence_level="catalog_observation",
        source=FORWARD_MEMBERSHIP_SOURCE,
        manifest_version=version,
        raw={**common_raw, "missing_sector_ids": missing_catalog},
    )
    tradable_scope = ForwardMembershipScope(
        scope_type=TRADABLE_SCOPE_TYPE,
        source_trade_date=source_trade_date,
        observed_at=observed,
        expected_sector_count=len(expected_tradable),
        returned_sector_count=len(returned_tradable),
        row_count=len(records),
        symbol_count=len({record.vt_symbol for record in records}),
        complete=tradable_complete,
        evidence_level=("strict" if tradable_complete else "rejected_partial_response"),
        source=FORWARD_MEMBERSHIP_SOURCE,
        manifest_version=version,
        raw={**common_raw, "missing_sector_ids": missing_tradable},
    )
    return ForwardMembershipCapture(
        records=records,
        catalog_scope=catalog_scope,
        tradable_scope=tradable_scope,
    )


def _validated_observation(source_trade_date: date, observed_at: datetime) -> datetime:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ForwardMembershipCaptureError("observed_at must be timezone-aware")
    observed = observed_at.astimezone(SHANGHAI)
    if observed.date() != source_trade_date or observed.time() < POST_CLOSE_START:
        raise ForwardMembershipCaptureError(
            "membership capture must be observed post-close on source_trade_date"
        )
    return observed_at


def _concept_catalog(
    sectors: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for sector in sectors:
        sector_type = str(sector.get("type") or sector.get("sector_type") or "").strip().lower()
        if sector_type not in CONCEPT_SECTOR_TYPES:
            continue
        sector_id = _sector_id(sector.get("id") or sector.get("sector_id"))
        if not sector_id:
            raise ForwardMembershipCaptureError("concept sector ID is required")
        if sector_id in catalog:
            raise ForwardMembershipCaptureError(
                f"duplicate sector ID in concept catalog: {sector_id}"
            )
        catalog[sector_id] = {
            "name": str(sector.get("name") or sector.get("sector_name") or sector_id),
            "type": sector_type,
        }
    if not catalog:
        raise ForwardMembershipCaptureError("concept catalog is empty")
    return catalog


def _normalized_members_by_sector(
    members_by_sector: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    normalized: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for raw_sector_id, members in members_by_sector.items():
        sector_id = _sector_id(raw_sector_id)
        if not sector_id:
            raise ForwardMembershipCaptureError("captured sector ID is required")
        if sector_id in normalized:
            raise ForwardMembershipCaptureError(
                f"duplicate captured sector ID: {sector_id}"
            )
        normalized[sector_id] = tuple(members)
    return normalized


def _manifest_exclusions(
    catalog: Mapping[str, Mapping[str, str]],
    manifest: Mapping[str, ThemeManifestRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for sector_id in sorted(catalog):
        record = manifest.get(sector_id)
        if record is None or record.board_class not in EXCLUDED_MANIFEST_CLASSES:
            continue
        rows.append(
            {
                "sector_id": sector_id,
                "observed_name": catalog[sector_id]["name"],
                "manifest_class": record.board_class,
                "evidence_reason": record.evidence_reason,
                "first_verified_date": record.first_verified_date.isoformat(),
            }
        )
    return rows


def _build_records(
    *,
    sector_ids: Sequence[str],
    catalog: Mapping[str, Mapping[str, str]],
    members_by_sector: Mapping[str, Sequence[Mapping[str, Any]]],
    manifest: Mapping[str, ThemeManifestRecord],
    source_trade_date: date,
    observed_at: datetime,
    manifest_version: str,
) -> tuple[ForwardMembershipRecord, ...]:
    records: list[ForwardMembershipRecord] = []
    for sector_id in sector_ids:
        seen_symbols: set[str] = set()
        members = members_by_sector.get(sector_id, ())
        if not members:
            raise ForwardMembershipCaptureError(
                f"tradable sector members are empty: {sector_id}"
            )
        manifest_record = manifest.get(sector_id)
        manifest_class = manifest_record.board_class if manifest_record else "unlabeled"
        for member in members:
            member_source = str(member.get("source") or "").strip()
            if member_source != RAW_PROVIDER_SOURCE:
                raise ForwardMembershipCaptureError(
                    f"unexpected member source for {sector_id}: {member_source or '-'}"
                )
            member_symbol = _member_vt_symbol(member)
            if member_symbol in seen_symbols:
                raise ForwardMembershipCaptureError(
                    f"duplicate member in {sector_id}: {member_symbol}"
                )
            seen_symbols.add(member_symbol)
            records.append(
                ForwardMembershipRecord(
                    source_trade_date=source_trade_date,
                    observed_at=observed_at,
                    sector_id=sector_id,
                    sector_name=catalog[sector_id]["name"],
                    sector_type=catalog[sector_id]["type"],
                    vt_symbol=member_symbol,
                    manifest_class=manifest_class,
                    evidence_level="strict",
                    source=FORWARD_MEMBERSHIP_SOURCE,
                    raw={
                        "provider_source": member_source,
                        "manifest_version": manifest_version,
                    },
                )
            )
    return tuple(records)


def _catalog_counts(
    captured_sector_ids: set[str],
    members_by_sector: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[int, int]:
    rows = [
        member
        for sector_id in captured_sector_ids
        for member in members_by_sector.get(sector_id, ())
    ]
    symbols = {
        symbol
        for member in rows
        if (symbol := _optional_member_vt_symbol(member)) is not None
    }
    return len(rows), len(symbols)


def _member_vt_symbol(member: Mapping[str, Any]) -> str:
    value = _optional_member_vt_symbol(member)
    if value is None:
        raise ForwardMembershipCaptureError("member vt_symbol is required")
    return value


def _optional_member_vt_symbol(member: Mapping[str, Any]) -> str | None:
    current = str(member.get("vt_symbol") or "").strip().upper()
    if current:
        return current
    symbol = str(member.get("symbol") or "").strip()
    if not symbol:
        return None
    exchange = str(member.get("exchange") or normalize_exchange(symbol)).strip()
    return vt_symbol(symbol, exchange).upper()


def _sector_id(value: object) -> str:
    return str(value or "").strip().upper()
