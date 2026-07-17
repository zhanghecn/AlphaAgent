"""Pure normalization for lagged Tushare DC daily memberships."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from alphaagent.server.services.data_providers.tushare_dc_membership import (
    DC_MEMBER_SOURCE,
)

from .historical_inputs import HistoricalMembershipRecord

SHANGHAI = ZoneInfo("Asia/Shanghai")
MEMBERSHIP_KNOWN_TIME = time(23, 59)
EXCHANGE_SUFFIXES = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
EVIDENCE_LEVELS = {"strict", "reconstructed", "invalid"}


@dataclass(frozen=True)
class NormalizedDcMember:
    source_trade_date: date
    effective_trade_date: date
    sector_id: str
    sector_name: str
    vt_symbol: str
    stock_name: str
    known_at: datetime
    fetched_at: datetime
    source: str
    evidence_level: str


def normalize_dc_snapshot(
    *,
    source_trade_date: date,
    effective_trade_date: date,
    sector_id: str,
    sector_name: str,
    members: Sequence[Mapping[str, Any]],
    fetched_at: datetime | None = None,
    source: str = DC_MEMBER_SOURCE,
    evidence_level: str = "strict",
) -> tuple[NormalizedDcMember, ...]:
    if source_trade_date >= effective_trade_date:
        raise ValueError("source trade date must precede effective trade date")
    if evidence_level not in EVIDENCE_LEVELS:
        raise ValueError("unsupported membership evidence level")
    observed_at = fetched_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    normalized_sector_id = str(sector_id).strip().upper()
    normalized_sector_name = str(sector_name).strip()
    if not normalized_sector_id or not normalized_sector_name:
        raise ValueError("sector ID and name are required")

    known_at = datetime.combine(
        source_trade_date,
        MEMBERSHIP_KNOWN_TIME,
        tzinfo=SHANGHAI,
    )
    rows: list[NormalizedDcMember] = []
    seen_symbols: set[str] = set()
    for member in members:
        vt_symbol = normalize_tushare_stock_code(member.get("con_code"))
        if vt_symbol in seen_symbols:
            raise ValueError(f"duplicate constituent: {vt_symbol}")
        seen_symbols.add(vt_symbol)
        rows.append(
            NormalizedDcMember(
                source_trade_date=source_trade_date,
                effective_trade_date=effective_trade_date,
                sector_id=normalized_sector_id,
                sector_name=normalized_sector_name,
                vt_symbol=vt_symbol,
                stock_name=str(member.get("name") or vt_symbol).strip(),
                known_at=known_at,
                fetched_at=observed_at,
                source=source,
                evidence_level=evidence_level,
            )
        )
    return tuple(rows)


def normalize_tushare_stock_code(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    symbol, separator, suffix = normalized.partition(".")
    exchange = EXCHANGE_SUFFIXES.get(suffix)
    if not separator or not symbol.isdigit() or exchange is None:
        raise ValueError(f"unsupported Tushare constituent code: {normalized or '-'}")
    return f"{symbol}.{exchange}"


def compress_daily_memberships(
    rows: Sequence[NormalizedDcMember],
    *,
    effective_dates: Sequence[date],
    terminal_out_date: date,
) -> tuple[HistoricalMembershipRecord, ...]:
    calendar = tuple(sorted(set(effective_dates)))
    if not calendar:
        raise ValueError("effective trading calendar cannot be empty")
    if terminal_out_date <= calendar[-1]:
        raise ValueError("terminal out date must follow the final effective date")
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    grouped: dict[tuple[str, str], list[NormalizedDcMember]] = defaultdict(list)
    seen: set[tuple[date, str, str]] = set()
    for row in rows:
        if row.effective_trade_date not in positions:
            raise ValueError("membership row is outside the declared calendar")
        unique_key = (row.effective_trade_date, row.sector_id, row.vt_symbol)
        if unique_key in seen:
            raise ValueError("duplicate daily membership row")
        seen.add(unique_key)
        grouped[(row.sector_id, row.vt_symbol)].append(row)

    intervals: list[HistoricalMembershipRecord] = []
    for group_rows in grouped.values():
        ordered = sorted(group_rows, key=lambda row: row.effective_trade_date)
        _validate_group_identity(ordered)
        run_start = 0
        for index in range(1, len(ordered) + 1):
            is_end = index == len(ordered)
            if not is_end:
                previous = positions[ordered[index - 1].effective_trade_date]
                current = positions[ordered[index].effective_trade_date]
                if current == previous + 1:
                    continue
            intervals.append(
                _interval_record(
                    ordered[run_start:index],
                    calendar=calendar,
                    positions=positions,
                    terminal_out_date=terminal_out_date,
                )
            )
            run_start = index
    return tuple(
        sorted(
            intervals,
            key=lambda row: (row.sector_id, row.vt_symbol, row.in_date),
        )
    )


def _validate_group_identity(rows: Sequence[NormalizedDcMember]) -> None:
    identities = {
        (row.sector_id, row.sector_name, row.vt_symbol, row.source, row.evidence_level)
        for row in rows
    }
    if len(identities) != 1:
        raise ValueError("membership identity changed inside one interval group")


def _interval_record(
    rows: Sequence[NormalizedDcMember],
    *,
    calendar: Sequence[date],
    positions: Mapping[date, int],
    terminal_out_date: date,
) -> HistoricalMembershipRecord:
    first = rows[0]
    last_position = positions[rows[-1].effective_trade_date]
    out_date = (
        calendar[last_position + 1]
        if last_position + 1 < len(calendar)
        else terminal_out_date
    )
    source_record_id = _source_record_id(
        first.source,
        first.sector_id,
        first.vt_symbol,
        first.effective_trade_date,
        out_date,
    )
    return HistoricalMembershipRecord(
        sector_id=first.sector_id,
        sector_name=first.sector_name,
        vt_symbol=first.vt_symbol,
        in_date=first.effective_trade_date,
        out_date=out_date,
        known_at=first.known_at,
        evidence_level=first.evidence_level,
        source=first.source,
        source_record_id=source_record_id,
    )


def _source_record_id(
    source: str,
    sector_id: str,
    vt_symbol: str,
    in_date: date,
    out_date: date,
) -> str:
    material = f"{source}|{sector_id}|{vt_symbol}|{in_date}|{out_date}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"dc-member:{digest}"
