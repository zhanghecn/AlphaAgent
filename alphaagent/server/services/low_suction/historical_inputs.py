"""Strict point-in-time input contracts for low-suction research."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
RESEARCH_OPEN_CUTOFF = time(9, 25)
EVIDENCE_LEVELS = ("strict", "reconstructed", "invalid")


class HistoricalInputValidationError(ValueError):
    """Raised when a provider response cannot qualify for persistence."""


@dataclass(frozen=True)
class HistoricalMembershipRecord:
    sector_id: str
    sector_name: str
    vt_symbol: str
    in_date: date
    out_date: date
    known_at: datetime
    evidence_level: str
    source: str
    source_record_id: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> HistoricalMembershipRecord:
        in_date = _required_date(row, "in_date")
        out_date = _required_date(row, "out_date")
        _validate_interval(in_date, out_date, label="membership")
        evidence_level = _required_evidence_level(row)
        return cls(
            sector_id=_required_text(row, "sector_id"),
            sector_name=_required_text(row, "sector_name"),
            vt_symbol=_required_text(row, "vt_symbol").upper(),
            in_date=in_date,
            out_date=out_date,
            known_at=_required_aware_datetime(row, "known_at"),
            evidence_level=evidence_level,
            source=_required_text(row, "source"),
            source_record_id=_required_text(row, "source_record_id"),
        )


@dataclass(frozen=True)
class HistoricalMembershipScope:
    trade_date: date
    source_trade_date: date
    sector_id: str
    expected_member_count: int
    returned_member_count: int
    pagination_complete: bool
    known_at: datetime
    evidence_level: str
    source: str
    source_request_id: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> HistoricalMembershipScope:
        trade_date = _required_date(row, "trade_date")
        source_trade_date = _required_date(row, "source_trade_date")
        if source_trade_date >= trade_date:
            raise HistoricalInputValidationError(
                "membership source_trade_date must precede trade_date"
            )
        return cls(
            trade_date=trade_date,
            source_trade_date=source_trade_date,
            sector_id=_required_text(row, "sector_id"),
            expected_member_count=_required_non_negative_int(
                row,
                "expected_member_count",
            ),
            returned_member_count=_required_non_negative_int(
                row,
                "returned_member_count",
            ),
            pagination_complete=_required_bool(row, "pagination_complete"),
            known_at=_required_aware_datetime(row, "known_at"),
            evidence_level=_required_evidence_level(row),
            source=_required_text(row, "source"),
            source_request_id=_required_text(row, "source_request_id"),
        )


@dataclass(frozen=True)
class HistoricalSecurityRecord:
    vt_symbol: str
    symbol: str
    exchange: str
    name: str
    status: str
    board: str
    listed_on: date
    delisted_on: date | None
    valid_from: date
    valid_to: date
    suspended: bool
    risk_warning: bool
    known_at: datetime
    evidence_level: str
    source: str
    source_record_id: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> HistoricalSecurityRecord:
        listed_on = _required_date(row, "listed_on")
        delisted_on = _optional_date(row.get("delisted_on"), field="delisted_on")
        valid_from = _required_date(row, "valid_from")
        valid_to = _required_date(row, "valid_to")
        _validate_interval(valid_from, valid_to, label="security status")
        if delisted_on is not None and delisted_on < listed_on:
            raise HistoricalInputValidationError(
                "delisted_on cannot precede listed_on"
            )

        vt_symbol = _required_text(row, "vt_symbol").upper()
        symbol = _required_text(row, "symbol")
        exchange = _required_text(row, "exchange").upper()
        if vt_symbol != f"{symbol}.{exchange}":
            raise HistoricalInputValidationError(
                "vt_symbol must match symbol and exchange"
            )
        evidence_level = _required_evidence_level(row)

        record = cls(
            vt_symbol=vt_symbol,
            symbol=symbol,
            exchange=exchange,
            name=_required_text(row, "name"),
            status=_required_text(row, "status").upper(),
            board=_required_text(row, "board").lower(),
            listed_on=listed_on,
            delisted_on=delisted_on,
            valid_from=valid_from,
            valid_to=valid_to,
            suspended=_required_bool(row, "suspended"),
            risk_warning=_required_bool(row, "risk_warning"),
            known_at=_required_aware_datetime(row, "known_at"),
            evidence_level=evidence_level,
            source=_required_text(row, "source"),
            source_record_id=_required_text(row, "source_record_id"),
        )
        if record.status == "DELISTED" and record.delisted_on is None:
            raise HistoricalInputValidationError(
                "delisted security record requires delisted_on"
            )
        return record


@dataclass(frozen=True)
class HistoricalMembershipBatch:
    records: tuple[HistoricalMembershipRecord, ...]
    scopes: tuple[HistoricalMembershipScope, ...]
    required_pairs: tuple[tuple[date, str], ...]
    source: str
    evidence_level: str


@dataclass(frozen=True)
class HistoricalSecurityBatch:
    records: tuple[HistoricalSecurityRecord, ...]
    required_pairs: tuple[tuple[date, str], ...]
    source: str
    evidence_level: str


@dataclass(frozen=True)
class HistoricalMembershipImportReport:
    status: str
    dry_run: bool
    written: bool
    evidence_level: str
    membership_rows: int
    scope_rows: int
    required_pairs: int
    scope_coverage_pct: float
    missing_scope_pairs: tuple[str, ...]
    incomplete_scope_pairs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "written": self.written,
            "evidence_level": self.evidence_level,
            "membership_rows": self.membership_rows,
            "scope_rows": self.scope_rows,
            "required_pairs": self.required_pairs,
            "scope_coverage_pct": self.scope_coverage_pct,
            "missing_scope_pairs": list(self.missing_scope_pairs),
            "incomplete_scope_pairs": list(self.incomplete_scope_pairs),
        }


@dataclass(frozen=True)
class HistoricalSecurityImportReport:
    status: str
    dry_run: bool
    written: bool
    evidence_level: str
    security_rows: int
    risk_warning_rows: int
    delisted_rows: int
    required_pairs: int
    scope_coverage_pct: float
    strict_scope_coverage_pct: float
    missing_security_pairs: tuple[str, ...]
    ambiguous_security_pairs: tuple[str, ...]
    non_strict_security_pairs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "written": self.written,
            "evidence_level": self.evidence_level,
            "security_rows": self.security_rows,
            "risk_warning_rows": self.risk_warning_rows,
            "delisted_rows": self.delisted_rows,
            "required_pairs": self.required_pairs,
            "scope_coverage_pct": self.scope_coverage_pct,
            "strict_scope_coverage_pct": self.strict_scope_coverage_pct,
            "missing_security_pairs": list(self.missing_security_pairs),
            "ambiguous_security_pairs": list(self.ambiguous_security_pairs),
            "non_strict_security_pairs": list(self.non_strict_security_pairs),
        }


MembershipHistoryWriter = Callable[[HistoricalMembershipBatch], None]
SecurityHistoryWriter = Callable[[HistoricalSecurityBatch], None]


def membership_is_valid_at_open(
    record: HistoricalMembershipRecord,
    trade_date: date,
) -> bool:
    cutoff = _market_open_cutoff(trade_date)
    return (
        record.evidence_level == "strict"
        and
        record.in_date <= trade_date < record.out_date
        and record.known_at.astimezone(SHANGHAI) <= cutoff
    )


def membership_scope_is_valid_at_open(
    scope: HistoricalMembershipScope,
) -> bool:
    return (
        scope.evidence_level == "strict"
        and scope.source_trade_date < scope.trade_date
        and scope.known_at.astimezone(SHANGHAI)
        <= _market_open_cutoff(scope.trade_date)
    )


def security_is_valid_at_open(
    record: HistoricalSecurityRecord,
    trade_date: date,
) -> bool:
    return (
        record.evidence_level == "strict"
        and _security_record_covers(record, trade_date)
        and record.known_at.astimezone(SHANGHAI)
        <= _market_open_cutoff(trade_date)
    )


def import_historical_memberships(
    *,
    membership_rows: Sequence[Mapping[str, Any]],
    membership_scope_rows: Sequence[Mapping[str, Any]],
    required_pairs: Sequence[tuple[date, str]],
    membership_interval_semantics_available: bool = True,
    writer: MembershipHistoryWriter | None = None,
    dry_run: bool = True,
) -> HistoricalMembershipImportReport:
    """Validate complete date/sector responses before one writer call."""

    if not membership_interval_semantics_available:
        raise HistoricalInputValidationError(
            "provider membership interval semantics are unavailable"
        )

    pairs = _required_pairs(required_pairs, entity_label="sector ID")
    records = tuple(
        HistoricalMembershipRecord.from_mapping(row) for row in membership_rows
    )
    scopes = tuple(
        HistoricalMembershipScope.from_mapping(row)
        for row in membership_scope_rows
    )
    _reject_duplicate_values(
        (record.source_record_id for record in records),
        label="membership source_record_id",
    )
    _reject_duplicate_values(
        (scope.source_request_id for scope in scopes),
        label="membership source_request_id",
    )
    source = _single_source((*records, *scopes), label="membership")
    evidence_level = _single_evidence_level((*records, *scopes), label="membership")

    missing: list[str] = []
    incomplete: list[str] = []
    for trade_date, sector_id in pairs:
        pair_key = _pair_key(trade_date, sector_id)
        pair_scopes = [
            scope
            for scope in scopes
            if scope.trade_date == trade_date and scope.sector_id == sector_id
        ]
        if not pair_scopes:
            missing.append(pair_key)
            continue
        if len(pair_scopes) != 1:
            incomplete.append(pair_key)
            continue

        scope = pair_scopes[0]
        active = [
            record
            for record in records
            if record.sector_id == sector_id
            and membership_is_valid_at_open(record, trade_date)
        ]
        distinct_symbols = {record.vt_symbol for record in active}
        complete = (
            membership_scope_is_valid_at_open(scope)
            and scope.pagination_complete
            and scope.expected_member_count == scope.returned_member_count
            and scope.returned_member_count == len(active)
            and len(active) == len(distinct_symbols)
        )
        if not complete:
            incomplete.append(pair_key)

    complete_pairs = len(pairs) - len(missing) - len(incomplete)
    complete = bool(source) and complete_pairs == len(pairs)
    status = "ready_for_atomic_replace" if complete else "rejected_partial_response"
    written = False
    if complete and not dry_run:
        if writer is None:
            raise HistoricalInputValidationError(
                "an atomic membership writer is required when dry_run is false"
            )
        writer(
            HistoricalMembershipBatch(
                records=records,
                scopes=scopes,
                required_pairs=pairs,
                source=source,
                evidence_level=evidence_level,
            )
        )
        status = "replaced"
        written = True

    return HistoricalMembershipImportReport(
        status=status,
        dry_run=dry_run,
        written=written,
        evidence_level=evidence_level,
        membership_rows=len(records),
        scope_rows=len(scopes),
        required_pairs=len(pairs),
        scope_coverage_pct=_scope_coverage(
            total=len(pairs),
            covered=complete_pairs,
        ),
        missing_scope_pairs=tuple(missing),
        incomplete_scope_pairs=tuple(incomplete),
    )


def import_historical_securities(
    *,
    security_rows: Sequence[Mapping[str, Any]],
    required_pairs: Sequence[tuple[date, str]],
    writer: SecurityHistoryWriter | None = None,
    dry_run: bool = True,
) -> HistoricalSecurityImportReport:
    """Validate an explicit security scope before one atomic writer call."""

    pairs = _required_pairs(required_pairs, entity_label="symbol", uppercase=True)
    records = tuple(
        HistoricalSecurityRecord.from_mapping(row) for row in security_rows
    )
    _reject_duplicate_values(
        (record.source_record_id for record in records),
        label="security source_record_id",
    )
    source = _single_source(records, label="security")
    evidence_level = _single_evidence_level(records)

    missing: list[str] = []
    ambiguous: list[str] = []
    non_strict: list[str] = []
    covered_count = 0
    strict_count = 0
    for trade_date, vt_symbol in pairs:
        pair_key = _pair_key(trade_date, vt_symbol)
        active = [
            record
            for record in records
            if record.vt_symbol == vt_symbol
            and _security_record_covers(record, trade_date)
        ]
        if not active:
            missing.append(pair_key)
            non_strict.append(pair_key)
            continue
        if len(active) != 1:
            ambiguous.append(pair_key)
            non_strict.append(pair_key)
            continue

        covered_count += 1
        if security_is_valid_at_open(active[0], trade_date):
            strict_count += 1
        else:
            non_strict.append(pair_key)

    complete = (
        bool(source)
        and evidence_level != "invalid"
        and not missing
        and not ambiguous
    )
    strict_batch_invalid = evidence_level == "strict" and bool(non_strict)
    if not complete:
        status = "rejected_partial_response"
    elif strict_batch_invalid:
        status = "rejected_non_point_in_time"
    else:
        status = "ready_for_atomic_replace"

    written = False
    if status == "ready_for_atomic_replace" and not dry_run:
        if writer is None:
            raise HistoricalInputValidationError(
                "an atomic security writer is required when dry_run is false"
            )
        writer(
            HistoricalSecurityBatch(
                records=records,
                required_pairs=pairs,
                source=source,
                evidence_level=evidence_level,
            )
        )
        status = "replaced"
        written = True

    return HistoricalSecurityImportReport(
        status=status,
        dry_run=dry_run,
        written=written,
        evidence_level=evidence_level,
        security_rows=len(records),
        risk_warning_rows=sum(_is_risk_warning(row) for row in records),
        delisted_rows=sum(_is_delisted(row) for row in records),
        required_pairs=len(pairs),
        scope_coverage_pct=_scope_coverage(
            total=len(pairs),
            covered=covered_count,
        ),
        strict_scope_coverage_pct=_scope_coverage(
            total=len(pairs),
            covered=strict_count,
        ),
        missing_security_pairs=tuple(missing),
        ambiguous_security_pairs=tuple(ambiguous),
        non_strict_security_pairs=tuple(non_strict),
    )


def _security_record_covers(
    record: HistoricalSecurityRecord,
    trade_date: date,
) -> bool:
    return (
        record.listed_on <= trade_date
        and record.valid_from <= trade_date < record.valid_to
    )


def _market_open_cutoff(trade_date: date) -> datetime:
    return datetime.combine(trade_date, RESEARCH_OPEN_CUTOFF, tzinfo=SHANGHAI)


def _scope_coverage(*, total: int, covered: int) -> float:
    if total <= 0:
        return 0.0
    return round(covered / total * 100.0, 4)


def _is_risk_warning(record: HistoricalSecurityRecord) -> bool:
    name = record.name.strip().upper()
    return (
        record.risk_warning
        or record.status in {"ST", "*ST", "RISK_WARNING"}
        or name.startswith(("ST", "*ST"))
    )


def _is_delisted(record: HistoricalSecurityRecord) -> bool:
    return record.delisted_on is not None or record.status == "DELISTED"


def _required_pairs(
    values: Sequence[tuple[date, str]],
    *,
    entity_label: str,
    uppercase: bool = False,
) -> tuple[tuple[date, str], ...]:
    normalized: set[tuple[date, str]] = set()
    for value in values:
        if not isinstance(value, tuple) or len(value) != 2:
            raise HistoricalInputValidationError(
                f"required {entity_label} pairs must contain (date, text) tuples"
            )
        trade_date, entity = value
        if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
            raise HistoricalInputValidationError(
                f"required {entity_label} pair dates must be date values"
            )
        text = str(entity).strip()
        if not text:
            raise HistoricalInputValidationError(
                f"required {entity_label} pair values cannot be empty"
            )
        normalized.add((trade_date, text.upper() if uppercase else text))
    if not normalized:
        raise HistoricalInputValidationError(
            f"required {entity_label} pairs cannot be empty"
        )
    return tuple(sorted(normalized))


def _single_source(
    records: Sequence[
        HistoricalMembershipRecord
        | HistoricalMembershipScope
        | HistoricalSecurityRecord
    ],
    *,
    label: str,
) -> str:
    sources = {record.source for record in records}
    if len(sources) > 1:
        raise HistoricalInputValidationError(
            f"mixed {label} sources cannot share one atomic batch"
        )
    return next(iter(sources), "")


def _single_evidence_level(
    records: Sequence[
        HistoricalMembershipRecord
        | HistoricalMembershipScope
        | HistoricalSecurityRecord
    ],
    *,
    label: str = "security",
) -> str:
    levels = {record.evidence_level for record in records}
    if len(levels) > 1:
        raise HistoricalInputValidationError(
            f"mixed {label} evidence levels cannot share one atomic batch"
        )
    return next(iter(levels), "invalid")


def _required_evidence_level(row: Mapping[str, Any]) -> str:
    evidence_level = _required_text(row, "evidence_level").lower()
    if evidence_level not in EVIDENCE_LEVELS:
        raise HistoricalInputValidationError(
            f"evidence_level must be one of {EVIDENCE_LEVELS}"
        )
    return evidence_level


def _reject_duplicate_values(values: Iterable[str], *, label: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise HistoricalInputValidationError(
            f"duplicate {label} in provider response"
        )


def _pair_key(trade_date: date, entity: str) -> str:
    return f"{trade_date.isoformat()}:{entity}"


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise HistoricalInputValidationError(f"{field} is required")
    return value


def _required_date(row: Mapping[str, Any], field: str) -> date:
    value = _optional_date(row.get(field), field=field)
    if value is None:
        raise HistoricalInputValidationError(f"{field} is required")
    return value


def _optional_date(value: Any, *, field: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        raise HistoricalInputValidationError(f"{field} must be a date, not datetime")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise HistoricalInputValidationError(
            f"{field} must be an ISO date"
        ) from exc


def _required_aware_datetime(row: Mapping[str, Any], field: str) -> datetime:
    value = row.get(field)
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").strip())
        except ValueError as exc:
            raise HistoricalInputValidationError(
                f"{field} must be an ISO datetime"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoricalInputValidationError(f"{field} must include a timezone")
    return parsed


def _required_bool(row: Mapping[str, Any], field: str) -> bool:
    value = row.get(field)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise HistoricalInputValidationError(f"{field} must be boolean")


def _required_non_negative_int(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool):
        raise HistoricalInputValidationError(
            f"{field} must be a non-negative integer"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HistoricalInputValidationError(
            f"{field} must be a non-negative integer"
        ) from exc
    if parsed < 0 or str(value).strip() != str(parsed):
        raise HistoricalInputValidationError(
            f"{field} must be a non-negative integer"
        )
    return parsed


def _validate_interval(start: date, end: date, *, label: str) -> None:
    if start >= end:
        raise HistoricalInputValidationError(
            f"{label} interval must satisfy start < end"
        )
