"""Read-only PostgreSQL coverage audit for low-suction research."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date as SqlDate
from sqlalchemy import and_, case, cast, exists, func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

from .concept_index_coverage import (
    CANONICAL_CONCEPT_INDEX_SOURCE,
    MIN_ACTIVE_CONCEPTS,
    MIN_COVERAGE_PCT,
    build_dynamic_concept_coverage,
)
from .contracts import (
    CONCEPT_SECTOR_TYPES,
    STRICT_MIN_CALENDAR_DAYS,
    STRICT_MIN_TRADE_DAYS,
    CoverageSnapshot,
    DatasetCoverage,
    PairCoverage,
)
from .data_quality import evaluate_data_quality
from .forward_membership import TRADABLE_SCOPE_TYPE
from .theme_reference_cohorts import MANIFEST_VERSION

RESEARCH_VERSION = "low-suction-data-quality-v3"
MIN_RELIABLE_STOCK_SYMBOLS = 3_000
SHANGHAI = ZoneInfo("Asia/Shanghai")
PREOPEN_CUTOFF = time(9, 25)
POST_CLOSE_START = time(15, 0)
MIN_FORWARD_CONCEPT_SECTORS = 300
MIN_FORWARD_MAIN_BOARD_SYMBOLS = 3_000


def load_coverage_snapshot() -> CoverageSnapshot:
    """Load the current database inventory without creating or changing tables."""

    snapshot, _ = _load_coverage()
    return snapshot


def load_data_quality_report() -> dict[str, Any]:
    """Return the coverage inventory and its fail-closed decision."""

    snapshot, inventory = _load_coverage()
    decision = evaluate_data_quality(snapshot)
    return {
        "research_version": RESEARCH_VERSION,
        "as_of_date": snapshot.as_of_date.isoformat(),
        **decision.as_dict(),
        "coverage": snapshot.as_dict(),
        "inventory": inventory,
        "source_limitations": {
            "tushare_dc_member": {
                "status": "candidate_historical_membership_unconfigured",
                "reason": "官方 dc_member 支持按 BKxxxx.DC 和交易日查询历史成分；本地未配置 TUSHARE_TOKEN，且尚未实测三年起点、完整性与 D-1 滞后口径，不能解除门禁",
                "url": "https://tushare.pro/document/2?doc_id=363",
            },
            "tushare_ths_member": {
                "status": "not_strict_historical_membership",
                "reason": "官方文档明确不能查询历史成分，且 in_date/out_date 标记为“暂无”",
                "url": "https://tushare.pro/document/2?doc_id=261",
            },
            "current_eastmoney_members": {
                "status": "membership_proxy",
                "reason": "当前成员关系不能回填到历史交易日",
            },
            "eastmoney_forward_membership": {
                "status": "strict_forward_accumulating",
                "reason": "完整盘后成员快照仅从实际捕获日S映射到下一可靠交易日D；累计达到720个交易日和1095个自然日前不解除门禁",
            },
            "baostock_security_history": {
                "status": "reconstructed_only",
                "reason": "可重建上市、退市、ST和停牌状态，但尚无官方字段发布时间承诺证明历史记录在D日09:25前已知",
            },
            "baostock_forward_security": {
                "status": "strict_forward_accumulating",
                "reason": "当日盘后完整证券状态仅对下一可靠交易日生效；不与BaoStock事后重建记录合并",
            },
        },
    }


def effective_membership_date(
    *,
    snapshot_date: date,
    captured_at: datetime,
    trading_dates: Sequence[date],
) -> date | None:
    """Return the first session allowed to consume a captured membership snapshot."""

    sessions = tuple(sorted(set(trading_dates)))
    captured_local = _as_shanghai(captured_at)
    cutoff = datetime.combine(snapshot_date, PREOPEN_CUTOFF, tzinfo=SHANGHAI)
    if captured_local <= cutoff and snapshot_date in sessions:
        return snapshot_date
    return next((trade_date for trade_date in sessions if trade_date > snapshot_date), None)


def effective_forward_trade_date(
    *,
    source_trade_date: date,
    observed_at: datetime,
    trading_dates: Sequence[date],
) -> date | None:
    """Map an actually observed source session S to its next reliable session D."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return None
    sessions = tuple(sorted(set(trading_dates)))
    if source_trade_date not in sessions:
        return None
    try:
        source_position = sessions.index(source_trade_date)
        effective_date = sessions[source_position + 1]
    except (ValueError, IndexError):
        return None

    observed_local = observed_at.astimezone(SHANGHAI)
    post_close = datetime.combine(
        source_trade_date,
        POST_CLOSE_START,
        tzinfo=SHANGHAI,
    )
    preopen_cutoff = datetime.combine(
        effective_date,
        PREOPEN_CUTOFF,
        tzinfo=SHANGHAI,
    )
    if not post_close <= observed_local <= preopen_cutoff:
        return None
    return effective_date


def _build_forward_membership_provider_inventory(
    rows: Sequence[Mapping[str, Any]],
    *,
    reliable_stock_dates: Sequence[date],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("evidence_level") or "invalid").lower(),
            str(row.get("source") or "").strip(),
        )
        grouped.setdefault(key, []).append(row)

    providers: list[dict[str, Any]] = []
    for (evidence_level, source), source_rows in grouped.items():
        eligible: list[tuple[Mapping[str, Any], date]] = []
        for row in source_rows:
            source_date = _date_value(row.get("source_trade_date"))
            observed_at = row.get("observed_at")
            if source_date is None or not isinstance(observed_at, datetime):
                continue
            effective_date = effective_forward_trade_date(
                source_trade_date=source_date,
                observed_at=observed_at,
                trading_dates=reliable_stock_dates,
            )
            if effective_date is None:
                continue
            if not _complete_forward_membership_capture(
                row,
                evidence_level=evidence_level,
                source=source,
            ):
                continue
            eligible.append((row, effective_date))

        effective_dates = sorted({effective for _, effective in eligible})
        provider = {
            "source": source,
            "evidence_level": evidence_level,
            "trade_days": len(effective_dates),
            "source_trade_days": len(
                {
                    _date_value(row.get("source_trade_date"))
                    for row, _ in eligible
                }
            ),
            "start": effective_dates[0] if effective_dates else None,
            "end": effective_dates[-1] if effective_dates else None,
            "required_pairs": sum(
                int(row.get("expected_sector_count") or 0) for row, _ in eligible
            ),
            "complete_pairs": sum(
                int(row.get("returned_sector_count") or 0) for row, _ in eligible
            ),
            "membership_rows": sum(
                int(row.get("actual_row_count") or 0) for row, _ in eligible
            ),
            "entities": max(
                (int(row.get("actual_symbol_count") or 0) for row, _ in eligible),
                default=0,
            ),
            "sectors": max(
                (int(row.get("actual_sector_count") or 0) for row, _ in eligible),
                default=0,
            ),
            "minimum_daily_coverage_pct": 100.0 if eligible else 0.0,
            "rejected_captures": len(source_rows) - len(eligible),
        }
        provider["status"] = _forward_provider_status(provider)
        providers.append(provider)
    return sorted(
        providers,
        key=lambda item: (str(item["evidence_level"]), str(item["source"])),
    )


def _complete_forward_membership_capture(
    row: Mapping[str, Any],
    *,
    evidence_level: str,
    source: str,
) -> bool:
    expected = int(row.get("expected_sector_count") or 0)
    returned = int(row.get("returned_sector_count") or 0)
    declared_rows = int(row.get("declared_row_count") or 0)
    actual_rows = int(row.get("actual_row_count") or 0)
    declared_symbols = int(row.get("declared_symbol_count") or 0)
    actual_symbols = int(row.get("actual_symbol_count") or 0)
    actual_sectors = int(row.get("actual_sector_count") or 0)
    observed_at = row.get("observed_at")
    return (
        evidence_level == "strict"
        and bool(source)
        and row.get("manifest_version") == MANIFEST_VERSION
        and bool(row.get("complete"))
        and expected >= MIN_FORWARD_CONCEPT_SECTORS
        and expected == returned == actual_sectors
        and declared_rows == actual_rows > 0
        and declared_symbols == actual_symbols > 0
        and row.get("minimum_observed_at") == observed_at
        and row.get("maximum_observed_at") == observed_at
    )


def _build_forward_security_provider_inventory(
    rows: Sequence[Mapping[str, Any]],
    *,
    reliable_stock_dates: Sequence[date],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("evidence_level") or "invalid").lower(),
            str(row.get("source") or "").strip(),
        )
        grouped.setdefault(key, []).append(row)

    providers: list[dict[str, Any]] = []
    for (evidence_level, source), source_rows in grouped.items():
        eligible: list[tuple[Mapping[str, Any], date]] = []
        for row in source_rows:
            source_date = _date_value(row.get("source_trade_date"))
            observed_at = row.get("observed_at")
            if source_date is None or not isinstance(observed_at, datetime):
                continue
            effective_date = effective_forward_trade_date(
                source_trade_date=source_date,
                observed_at=observed_at,
                trading_dates=reliable_stock_dates,
            )
            if effective_date is None:
                continue
            if not _complete_forward_security_capture(
                row,
                evidence_level=evidence_level,
                source=source,
            ):
                continue
            eligible.append((row, effective_date))

        effective_dates = sorted({effective for _, effective in eligible})
        provider = {
            "evidence_level": evidence_level,
            "source": source,
            "status": "invalid_capture",
            "required_pairs": sum(
                int(row.get("expected_symbol_count") or 0) for row, _ in eligible
            ),
            "covered_pairs": sum(
                int(row.get("actual_row_count") or 0) for row, _ in eligible
            ),
            "entities": max(
                (int(row.get("actual_symbol_count") or 0) for row, _ in eligible),
                default=0,
            ),
            "trade_days": len(effective_dates),
            "source_trade_days": len(
                {
                    _date_value(row.get("source_trade_date"))
                    for row, _ in eligible
                }
            ),
            "start": effective_dates[0] if effective_dates else None,
            "end": effective_dates[-1] if effective_dates else None,
            "status_rows": sum(
                int(row.get("actual_row_count") or 0) for row, _ in eligible
            ),
            "risk_warning_rows": sum(
                int(row.get("actual_risk_warning_count") or 0)
                for row, _ in eligible
            ),
            "suspended_rows": sum(
                int(row.get("actual_suspended_count") or 0)
                for row, _ in eligible
            ),
            "delisted_symbols": max(
                (int(row.get("delisted_symbols") or 0) for row, _ in eligible),
                default=0,
            ),
            "rejected_captures": len(source_rows) - len(eligible),
        }
        provider["status"] = _forward_provider_status(provider)
        providers.append(provider)
    return sorted(
        providers,
        key=lambda item: (str(item["evidence_level"]), str(item["source"])),
    )


def _complete_forward_security_capture(
    row: Mapping[str, Any],
    *,
    evidence_level: str,
    source: str,
) -> bool:
    expected = int(row.get("expected_symbol_count") or 0)
    returned = int(row.get("returned_symbol_count") or 0)
    actual_rows = int(row.get("actual_row_count") or 0)
    actual_symbols = int(row.get("actual_symbol_count") or 0)
    observed_at = row.get("observed_at")
    return (
        evidence_level == "strict"
        and bool(source)
        and bool(row.get("complete"))
        and expected >= MIN_FORWARD_MAIN_BOARD_SYMBOLS
        and expected == returned == actual_rows == actual_symbols
        and row.get("risk_warning_count")
        == row.get("actual_risk_warning_count")
        and row.get("suspended_count") == row.get("actual_suspended_count")
        and row.get("minimum_observed_at") == observed_at
        and row.get("maximum_observed_at") == observed_at
    )


def _forward_provider_status(provider: Mapping[str, Any]) -> str:
    if int(provider.get("trade_days") or 0) <= 0:
        return "invalid_capture"
    return "ready" if _provider_has_required_history(provider) else "accumulating"


def _provider_has_required_history(provider: Mapping[str, Any]) -> bool:
    start = _date_value(provider.get("start"))
    end = _date_value(provider.get("end"))
    return (
        int(provider.get("trade_days") or 0) >= STRICT_MIN_TRADE_DAYS
        and start is not None
        and end is not None
        and start <= end
        and (end - start).days >= STRICT_MIN_CALENDAR_DAYS
    )


def _load_coverage() -> tuple[CoverageSnapshot, dict[str, Any]]:
    with session_scope() as session:
        completed_cutoff = completed_daily_bar_cutoff()
        stock_daily, reliable_dates, stock_inventory = _stock_daily_coverage(
            session,
            completed_cutoff=completed_cutoff,
        )
        as_of_date = reliable_dates[-1] if reliable_dates else completed_cutoff
        concept_daily, concept_inventory = _concept_daily_coverage(
            session,
            as_of_date=as_of_date,
        )
        membership, membership_inventory = _concept_membership_coverage(
            session,
            reliable_dates,
            concept_inventory["concept_count"],
        )
        security_status, security_inventory = _security_status_coverage(
            session,
            reliable_dates,
        )
        market_timing, timing_inventory = _market_timing_coverage(session, as_of_date)
        supporting = _supporting_coverage(session, as_of_date)

    snapshot = CoverageSnapshot(
        as_of_date=as_of_date,
        stock_daily=stock_daily,
        concept_daily=concept_daily,
        concept_membership=membership,
        security_status=security_status,
        candidate_minutes=PairCoverage(total_pairs=0, covered_pairs=0),
        market_timing=market_timing,
        supporting=tuple(sorted(supporting.items())),
    )
    inventory = {
        "stock_daily": stock_inventory,
        "concept_daily": concept_inventory,
        "concept_membership": membership_inventory,
        "security_status": security_inventory,
        "candidate_minutes": {
            "status": "not_assessed",
            "reason": "candidate events have not been generated",
        },
        "market_timing": timing_inventory,
    }
    return snapshot, inventory


def _stock_daily_coverage(
    session,
    *,
    completed_cutoff: date,
) -> tuple[DatasetCoverage, tuple[date, ...], dict[str, Any]]:
    count_rows = session.execute(
        select(
            schema.stock_daily_bars.c.trade_date,
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)),
        )
        .where(schema.stock_daily_bars.c.trade_date <= completed_cutoff)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(schema.stock_daily_bars.c.trade_date)
    ).all()
    reliable = tuple(
        row[0] for row in count_rows if int(row[1] or 0) >= MIN_RELIABLE_STOCK_SYMBOLS
    )
    sources = _sources(session, schema.stock_daily_bars)
    if not reliable:
        return _empty_dataset("unavailable", sources), (), {
            "minimum_daily_symbols": MIN_RELIABLE_STOCK_SYMBOLS,
            "reliable_trade_days": 0,
        }

    aggregate = session.execute(
        select(
            func.count(),
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)),
        ).where(schema.stock_daily_bars.c.trade_date.in_(reliable))
    ).one()
    reliable_counts = [int(row[1] or 0) for row in count_rows if row[0] in set(reliable)]
    maximum_count = max(reliable_counts)
    minimum_count = min(reliable_counts)
    coverage_pct = round(minimum_count / maximum_count * 100.0, 4)
    dataset = DatasetCoverage(
        rows=int(aggregate[0] or 0),
        entities=int(aggregate[1] or 0),
        trade_days=len(reliable),
        start=reliable[0],
        end=reliable[-1],
        coverage_pct=coverage_pct,
        mode="strict",
        sources=sources,
    )
    inventory = {
        "completed_cutoff": completed_cutoff.isoformat(),
        "minimum_daily_symbols": MIN_RELIABLE_STOCK_SYMBOLS,
        "raw_trade_days": len(count_rows),
        "raw_start": count_rows[0][0].isoformat() if count_rows else None,
        "raw_end": count_rows[-1][0].isoformat() if count_rows else None,
        "reliable_trade_days": len(reliable),
        "reliable_start": reliable[0].isoformat(),
        "reliable_end": reliable[-1].isoformat(),
        "minimum_reliable_cross_section": minimum_count,
        "maximum_reliable_cross_section": maximum_count,
    }
    return dataset, reliable, inventory


def _concept_daily_coverage(
    session,
    *,
    as_of_date: date,
) -> tuple[DatasetCoverage, dict[str, Any]]:
    concept_count = int(
        session.execute(
            select(func.count())
            .select_from(schema.sectors)
            .where(schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES))
        ).scalar_one()
        or 0
    )
    count_rows = session.execute(
        select(
            schema.sector_daily_bars.c.trade_date,
            func.count(func.distinct(schema.sector_daily_bars.c.sector_id)),
        )
        .select_from(
            schema.sector_daily_bars.join(
                schema.sectors,
                schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
            schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            schema.sector_daily_bars.c.trade_date <= as_of_date,
        )
        .group_by(schema.sector_daily_bars.c.trade_date)
        .order_by(schema.sector_daily_bars.c.trade_date)
    ).all()
    bound_rows = session.execute(
        select(
            schema.sector_daily_bars.c.sector_id,
            func.min(schema.sector_daily_bars.c.trade_date),
            func.max(schema.sector_daily_bars.c.trade_date),
        )
        .select_from(
            schema.sector_daily_bars.join(
                schema.sectors,
                schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
            schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            schema.sector_daily_bars.c.trade_date <= as_of_date,
        )
        .group_by(schema.sector_daily_bars.c.sector_id)
        .order_by(schema.sector_daily_bars.c.sector_id)
    ).all()
    dynamic_rows = build_dynamic_concept_coverage(
        trading_dates=tuple(row[0] for row in count_rows),
        count_rows=tuple((row[0], int(row[1] or 0)) for row in count_rows),
        bounds=tuple((str(row[0]), row[1], row[2]) for row in bound_rows),
    )
    complete_rows = tuple(row for row in dynamic_rows if row.qualifies)
    complete_dates = tuple(row.trade_date for row in complete_rows)
    sources = _sources(
        session,
        schema.sector_daily_bars,
        where_clause=(
            and_(
                schema.sector_daily_bars.c.source
                == CANONICAL_CONCEPT_INDEX_SOURCE,
                schema.sector_daily_bars.c.trade_date <= as_of_date,
            )
        ),
    )
    if not complete_dates:
        dataset = _empty_dataset("unavailable", sources)
        coverage_pct = 0.0
    else:
        aggregate = session.execute(
            select(
                func.count(),
                func.count(func.distinct(schema.sector_daily_bars.c.sector_id)),
            )
            .select_from(
                schema.sector_daily_bars.join(
                    schema.sectors,
                    schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
                )
            )
            .where(
                schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
                schema.sector_daily_bars.c.source
                == CANONICAL_CONCEPT_INDEX_SOURCE,
                schema.sector_daily_bars.c.trade_date <= as_of_date,
                schema.sector_daily_bars.c.trade_date.in_(complete_dates),
            )
        ).one()
        coverage_pct = min(row.coverage_pct for row in complete_rows)
        dataset = DatasetCoverage(
            rows=int(aggregate[0] or 0),
            entities=int(aggregate[1] or 0),
            trade_days=len(complete_dates),
            start=complete_dates[0],
            end=complete_dates[-1],
            coverage_pct=coverage_pct,
            mode="strict",
            sources=sources,
        )
    inventory = {
        "concept_count": concept_count,
        "indexed_concept_count": len(bound_rows),
        "canonical_source": CANONICAL_CONCEPT_INDEX_SOURCE,
        "minimum_active_concepts": MIN_ACTIVE_CONCEPTS,
        "minimum_cross_section_pct": MIN_COVERAGE_PCT,
        "raw_trade_days": len(count_rows),
        "raw_start": count_rows[0][0].isoformat() if count_rows else None,
        "raw_end": count_rows[-1][0].isoformat() if count_rows else None,
        "complete_trade_days": len(complete_dates),
        "complete_start": complete_dates[0].isoformat() if complete_dates else None,
        "complete_end": complete_dates[-1].isoformat() if complete_dates else None,
        "minimum_complete_cross_section_pct": coverage_pct,
        "minimum_expected_active_concepts": (
            min(row.expected_active_concepts for row in complete_rows)
            if complete_rows
            else 0
        ),
        "maximum_expected_active_concepts": (
            max(row.expected_active_concepts for row in complete_rows)
            if complete_rows
            else 0
        ),
    }
    return dataset, inventory


def _concept_membership_coverage(
    session,
    reliable_stock_dates: Sequence[date],
    concept_count: int,
) -> tuple[DatasetCoverage, dict[str, Any]]:
    proxy_coverage, proxy_inventory = _proxy_concept_membership_coverage(
        session,
        reliable_stock_dates,
        concept_count,
    )
    providers = _strict_membership_provider_inventory(
        session,
        reliable_stock_dates,
    )
    providers.extend(
        _forward_membership_provider_inventory(
            session,
            reliable_stock_dates,
        )
    )
    return _select_concept_membership_coverage(
        providers,
        proxy_coverage=proxy_coverage,
        proxy_inventory=proxy_inventory,
    )


def _proxy_concept_membership_coverage(
    session,
    reliable_stock_dates: Sequence[date],
    concept_count: int,
) -> tuple[DatasetCoverage, dict[str, Any]]:
    snapshots = schema.stock_sector_membership_snapshots
    rows = session.execute(
        select(
            snapshots.c.snapshot_date,
            snapshots.c.captured_at,
            snapshots.c.source,
            func.count(),
            func.count(func.distinct(snapshots.c.sector_id)),
            func.count(func.distinct(snapshots.c.vt_symbol)),
            func.bool_and(func.coalesce(snapshots.c.confirmed, False)),
            func.bool_and(func.coalesce(snapshots.c.is_precise, False)),
        )
        .where(snapshots.c.sector_type.in_(CONCEPT_SECTOR_TYPES))
        .group_by(
            snapshots.c.snapshot_date,
            snapshots.c.captured_at,
            snapshots.c.source,
        )
        .order_by(snapshots.c.snapshot_date, snapshots.c.captured_at)
    ).all()
    if not rows:
        return _empty_dataset("unavailable"), {
            "raw_snapshot_trade_days": 0,
            "effective_trade_days": 0,
            "mode": "unavailable",
            "captures": [],
        }

    sources = tuple(sorted({str(row[2]) for row in rows if row[2]}))
    effective_dates = tuple(
        sorted(
            {
                effective
                for row in rows
                if (
                    effective := effective_membership_date(
                        snapshot_date=row[0],
                        captured_at=row[1],
                        trading_dates=reliable_stock_dates,
                    )
                )
                is not None
            }
        )
    )
    minimum_sector_count = min(int(row[4] or 0) for row in rows)
    coverage_pct = (
        round(minimum_sector_count / concept_count * 100.0, 4)
        if concept_count
        else 0.0
    )
    dataset = DatasetCoverage(
        rows=sum(int(row[3] or 0) for row in rows),
        entities=max(int(row[5] or 0) for row in rows),
        trade_days=len(effective_dates),
        start=effective_dates[0] if effective_dates else None,
        end=effective_dates[-1] if effective_dates else None,
        coverage_pct=coverage_pct,
        mode="current_proxy",
        sources=sources,
    )
    inventory = {
        "mode": "current_proxy",
        "raw_snapshot_trade_days": len({row[0] for row in rows}),
        "raw_start": min(row[0] for row in rows).isoformat(),
        "raw_end": max(row[0] for row in rows).isoformat(),
        "effective_trade_days": len(effective_dates),
        "effective_start": effective_dates[0].isoformat() if effective_dates else None,
        "effective_end": effective_dates[-1].isoformat() if effective_dates else None,
        "minimum_sector_coverage_pct": coverage_pct,
        "captures": [
            {
                "snapshot_date": row[0].isoformat(),
                "captured_at": row[1].isoformat(),
                "source": str(row[2]),
                "rows": int(row[3] or 0),
                "sectors": int(row[4] or 0),
                "stocks": int(row[5] or 0),
            }
            for row in rows
        ],
    }
    return dataset, inventory


def _strict_membership_provider_inventory(
    session,
    reliable_stock_dates: Sequence[date],
) -> list[dict[str, Any]]:
    if not reliable_stock_dates:
        return []
    scopes = schema.low_suction_concept_membership_scopes
    history = schema.low_suction_concept_membership_history
    active_count = (
        select(func.count(func.distinct(history.c.vt_symbol)))
        .where(
            history.c.source == scopes.c.source,
            history.c.evidence_level == scopes.c.evidence_level,
            history.c.sector_id == scopes.c.sector_id,
            history.c.in_date <= scopes.c.trade_date,
            history.c.out_date > scopes.c.trade_date,
        )
        .correlate(scopes)
        .scalar_subquery()
    )
    complete_scope = and_(
        scopes.c.pagination_complete.is_(True),
        scopes.c.expected_member_count == scopes.c.returned_member_count,
        scopes.c.returned_member_count == active_count,
    )
    daily_rows = session.execute(
        select(
            scopes.c.evidence_level,
            scopes.c.source,
            scopes.c.trade_date,
            func.count(),
            func.sum(case((complete_scope, 1), else_=0)),
            func.sum(scopes.c.returned_member_count),
            func.count(func.distinct(scopes.c.sector_id)),
        )
        .where(scopes.c.trade_date.in_(tuple(reliable_stock_dates)))
        .group_by(
            scopes.c.evidence_level,
            scopes.c.source,
            scopes.c.trade_date,
        )
        .order_by(scopes.c.evidence_level, scopes.c.source, scopes.c.trade_date)
    ).all()
    entity_rows = session.execute(
        select(
            history.c.evidence_level,
            history.c.source,
            func.count(func.distinct(history.c.vt_symbol)),
        )
        .group_by(history.c.evidence_level, history.c.source)
    ).all()
    entities = {
        (str(row[0]), str(row[1])): int(row[2] or 0) for row in entity_rows
    }
    grouped: dict[tuple[str, str], list[Any]] = {}
    for row in daily_rows:
        grouped.setdefault((str(row[0]), str(row[1])), []).append(row)

    providers: list[dict[str, Any]] = []
    for (evidence_level, source), rows in grouped.items():
        complete_dates = [
            row[2]
            for row in rows
            if int(row[3] or 0) > 0 and int(row[3] or 0) == int(row[4] or 0)
        ]
        daily_coverage = [
            round(int(row[4] or 0) / int(row[3] or 1) * 100.0, 4)
            for row in rows
        ]
        providers.append(
            {
                "source": source,
                "evidence_level": evidence_level,
                "trade_days": len(complete_dates),
                "start": min(complete_dates) if complete_dates else None,
                "end": max(complete_dates) if complete_dates else None,
                "required_pairs": sum(int(row[3] or 0) for row in rows),
                "complete_pairs": sum(int(row[4] or 0) for row in rows),
                "membership_rows": sum(
                    int(row[5] or 0)
                    for row in rows
                    if int(row[3] or 0) == int(row[4] or 0)
                ),
                "entities": entities.get((evidence_level, source), 0),
                "sectors": max((int(row[6] or 0) for row in rows), default=0),
                "minimum_daily_coverage_pct": min(daily_coverage, default=0.0),
            }
        )
    return sorted(
        providers,
        key=lambda item: (str(item["evidence_level"]), str(item["source"])),
    )


def _forward_membership_provider_inventory(
    session,
    reliable_stock_dates: Sequence[date],
) -> list[dict[str, Any]]:
    if not reliable_stock_dates:
        return []
    scopes = schema.low_suction_forward_membership_snapshot_scopes
    snapshots = schema.low_suction_forward_membership_snapshots
    aggregates = (
        select(
            snapshots.c.source_trade_date.label("source_trade_date"),
            snapshots.c.source.label("source"),
            func.count().label("actual_row_count"),
            func.count(func.distinct(snapshots.c.sector_id)).label(
                "actual_sector_count"
            ),
            func.count(func.distinct(snapshots.c.vt_symbol)).label(
                "actual_symbol_count"
            ),
            func.min(snapshots.c.observed_at).label("minimum_observed_at"),
            func.max(snapshots.c.observed_at).label("maximum_observed_at"),
        )
        .where(snapshots.c.evidence_level == "strict")
        .group_by(snapshots.c.source_trade_date, snapshots.c.source)
        .subquery()
    )
    rows = session.execute(
        select(
            scopes.c.source_trade_date,
            scopes.c.observed_at,
            scopes.c.source,
            scopes.c.evidence_level,
            scopes.c.complete,
            scopes.c.expected_sector_count,
            scopes.c.returned_sector_count,
            scopes.c.row_count.label("declared_row_count"),
            scopes.c.symbol_count.label("declared_symbol_count"),
            scopes.c.manifest_version,
            aggregates.c.actual_row_count,
            aggregates.c.actual_sector_count,
            aggregates.c.actual_symbol_count,
            aggregates.c.minimum_observed_at,
            aggregates.c.maximum_observed_at,
        )
        .select_from(
            scopes.outerjoin(
                aggregates,
                and_(
                    aggregates.c.source_trade_date == scopes.c.source_trade_date,
                    aggregates.c.source == scopes.c.source,
                ),
            )
        )
        .where(scopes.c.scope_type == TRADABLE_SCOPE_TYPE)
        .order_by(scopes.c.source, scopes.c.source_trade_date)
    ).mappings().all()
    return _build_forward_membership_provider_inventory(
        [dict(row) for row in rows],
        reliable_stock_dates=reliable_stock_dates,
    )


def _select_concept_membership_coverage(
    providers: Sequence[Mapping[str, Any]],
    *,
    proxy_coverage: DatasetCoverage,
    proxy_inventory: Mapping[str, Any],
) -> tuple[DatasetCoverage, dict[str, Any]]:
    strict = [
        provider
        for provider in providers
        if provider.get("evidence_level") == "strict"
        and int(provider.get("required_pairs") or 0) > 0
        and int(provider.get("required_pairs") or 0)
        == int(provider.get("complete_pairs") or 0)
        and int(provider.get("trade_days") or 0) > 0
        and _provider_has_required_history(provider)
    ]
    serialized_providers = [_serialize_membership_provider(row) for row in providers]
    if not strict:
        return proxy_coverage, {
            **dict(proxy_inventory),
            "selected_source": None,
            "providers": serialized_providers,
        }

    selected = max(
        strict,
        key=lambda item: (
            int(item.get("trade_days") or 0),
            float(item.get("minimum_daily_coverage_pct") or 0.0),
            int(item.get("membership_rows") or 0),
            str(item.get("source") or ""),
        ),
    )
    start = _date_value(selected.get("start"))
    end = _date_value(selected.get("end"))
    coverage = DatasetCoverage(
        rows=int(selected.get("membership_rows") or 0),
        entities=int(selected.get("entities") or 0),
        trade_days=int(selected.get("trade_days") or 0),
        start=start,
        end=end,
        coverage_pct=float(selected.get("minimum_daily_coverage_pct") or 0.0),
        mode="strict",
        sources=(str(selected.get("source") or ""),),
    )
    inventory = {
        "mode": "strict",
        "selected_source": str(selected.get("source") or ""),
        "raw_snapshot_trade_days": coverage.trade_days,
        "raw_start": start.isoformat() if start else None,
        "raw_end": end.isoformat() if end else None,
        "effective_trade_days": coverage.trade_days,
        "effective_start": start.isoformat() if start else None,
        "effective_end": end.isoformat() if end else None,
        "minimum_sector_coverage_pct": coverage.coverage_pct,
        "providers": serialized_providers,
        "proxy": dict(proxy_inventory),
        "captures": [],
    }
    return coverage, inventory


def _serialize_membership_provider(provider: Mapping[str, Any]) -> dict[str, Any]:
    start = _date_value(provider.get("start"))
    end = _date_value(provider.get("end"))
    status = str(provider.get("status") or "").strip()
    if not status:
        complete = (
            int(provider.get("required_pairs") or 0) > 0
            and int(provider.get("required_pairs") or 0)
            == int(provider.get("complete_pairs") or 0)
        )
        if not complete:
            status = "invalid_scope"
        elif _provider_has_required_history(provider):
            status = "ready"
        else:
            status = "accumulating"
    return {
        **dict(provider),
        "status": status,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "calendar_span_days": (
            (end - start).days if start is not None and end is not None else 0
        ),
    }


def _security_status_coverage(
    session,
    reliable_stock_dates: Sequence[date],
) -> tuple[DatasetCoverage, dict[str, Any]]:
    if not reliable_stock_dates:
        return _empty_dataset("unavailable"), {
            "status": "unavailable",
            "selected_source": None,
            "providers": [],
            "reason": "reliable stock dates are unavailable",
        }

    scopes = schema.low_suction_security_history_scopes
    history = schema.low_suction_security_history
    covered_exists = exists(
        select(1)
        .select_from(history)
        .where(
            history.c.source == scopes.c.source,
            history.c.evidence_level == scopes.c.evidence_level,
            history.c.vt_symbol == scopes.c.vt_symbol,
            history.c.valid_from <= scopes.c.trade_date,
            history.c.valid_to > scopes.c.trade_date,
        )
        .correlate(scopes)
    )
    scope_rows = session.execute(
        select(
            scopes.c.evidence_level,
            scopes.c.source,
            func.count(),
            func.sum(case((covered_exists, 1), else_=0)),
            func.count(func.distinct(scopes.c.vt_symbol)),
            func.count(func.distinct(scopes.c.trade_date)),
            func.min(scopes.c.trade_date),
            func.max(scopes.c.trade_date),
        )
        .where(scopes.c.trade_date.in_(tuple(reliable_stock_dates)))
        .group_by(scopes.c.evidence_level, scopes.c.source)
    ).all()

    history_rows = session.execute(
        select(
            history.c.evidence_level,
            history.c.source,
            func.count(),
            func.sum(case((history.c.risk_warning.is_(True), 1), else_=0)),
            func.sum(case((history.c.suspended.is_(True), 1), else_=0)),
            func.count(
                func.distinct(
                    case(
                        (history.c.delisted_on.is_not(None), history.c.vt_symbol),
                        else_=None,
                    )
                )
            ),
        )
        .where(
            history.c.valid_from <= reliable_stock_dates[-1],
            history.c.valid_to > reliable_stock_dates[0],
        )
        .group_by(history.c.evidence_level, history.c.source)
    ).all()
    history_by_provider = {
        (str(row[0]), str(row[1])): {
            "status_rows": int(row[2] or 0),
            "risk_warning_rows": int(row[3] or 0),
            "suspended_rows": int(row[4] or 0),
            "delisted_symbols": int(row[5] or 0),
        }
        for row in history_rows
    }
    providers: list[dict[str, Any]] = []
    for row in scope_rows:
        evidence_level = str(row[0] or "invalid")
        source = str(row[1] or "")
        providers.append(
            {
                "evidence_level": evidence_level,
                "source": source,
                "required_pairs": int(row[2] or 0),
                "covered_pairs": int(row[3] or 0),
                "entities": int(row[4] or 0),
                "trade_days": int(row[5] or 0),
                "start": _date_value(row[6]),
                "end": _date_value(row[7]),
                **history_by_provider.get(
                    (evidence_level, source),
                    {
                        "status_rows": 0,
                        "risk_warning_rows": 0,
                        "suspended_rows": 0,
                        "delisted_symbols": 0,
                    },
                ),
            }
        )
    providers.extend(
        _forward_security_provider_inventory(
            session,
            reliable_stock_dates,
        )
    )
    return _build_security_status_coverage(providers)


def _forward_security_provider_inventory(
    session,
    reliable_stock_dates: Sequence[date],
) -> list[dict[str, Any]]:
    scopes = schema.low_suction_security_snapshot_scopes
    snapshots = schema.low_suction_security_snapshots
    aggregates = (
        select(
            snapshots.c.source_trade_date,
            snapshots.c.source,
            func.count().label("actual_row_count"),
            func.count(func.distinct(snapshots.c.vt_symbol)).label(
                "actual_symbol_count"
            ),
            func.sum(
                case((snapshots.c.risk_warning.is_(True), 1), else_=0)
            ).label("actual_risk_warning_count"),
            func.sum(
                case((snapshots.c.suspended.is_(True), 1), else_=0)
            ).label("actual_suspended_count"),
            func.count(
                func.distinct(
                    case(
                        (
                            and_(
                                snapshots.c.delisted_on.is_not(None),
                                snapshots.c.delisted_on
                                <= snapshots.c.source_trade_date,
                            ),
                            snapshots.c.vt_symbol,
                        ),
                        else_=None,
                    )
                )
            ).label("delisted_symbols"),
            func.min(snapshots.c.observed_at).label("minimum_observed_at"),
            func.max(snapshots.c.observed_at).label("maximum_observed_at"),
        )
        .group_by(snapshots.c.source_trade_date, snapshots.c.source)
        .subquery()
    )
    rows = session.execute(
        select(
            scopes.c.source_trade_date,
            scopes.c.source,
            scopes.c.observed_at,
            scopes.c.evidence_level,
            scopes.c.complete,
            scopes.c.expected_symbol_count,
            scopes.c.returned_symbol_count,
            scopes.c.risk_warning_count,
            scopes.c.suspended_count,
            aggregates.c.actual_row_count,
            aggregates.c.actual_symbol_count,
            aggregates.c.actual_risk_warning_count,
            aggregates.c.actual_suspended_count,
            aggregates.c.delisted_symbols,
            aggregates.c.minimum_observed_at,
            aggregates.c.maximum_observed_at,
        )
        .select_from(
            scopes.outerjoin(
                aggregates,
                and_(
                    aggregates.c.source_trade_date == scopes.c.source_trade_date,
                    aggregates.c.source == scopes.c.source,
                ),
            )
        )
        .order_by(scopes.c.source, scopes.c.source_trade_date)
    ).mappings().all()
    return _build_forward_security_provider_inventory(
        [dict(row) for row in rows],
        reliable_stock_dates=reliable_stock_dates,
    )


def _build_security_status_coverage(
    provider_rows: Sequence[Mapping[str, Any]],
) -> tuple[DatasetCoverage, dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    selectable: list[dict[str, Any]] = []
    for raw in provider_rows:
        evidence_level = str(raw.get("evidence_level") or "invalid").lower()
        source = str(raw.get("source") or "").strip()
        required_pairs = int(raw.get("required_pairs") or 0)
        covered_pairs = int(raw.get("covered_pairs") or 0)
        start = _date_value(raw.get("start"))
        end = _date_value(raw.get("end"))
        valid = (
            evidence_level in {"strict", "reconstructed"}
            and bool(source)
            and required_pairs > 0
            and 0 <= covered_pairs <= required_pairs
            and start is not None
            and end is not None
            and start <= end
        )
        history_ready = valid and _provider_has_required_history(raw)
        coverage_pct = (
            round(covered_pairs / required_pairs * 100.0, 4)
            if valid
            else 0.0
        )
        provider = {
            "evidence_level": evidence_level,
            "source": source,
            "status": (
                "invalid_scope"
                if not valid
                else "accumulating"
                if evidence_level == "strict" and not history_ready
                else "ready"
            ),
            "required_pairs": required_pairs,
            "covered_pairs": covered_pairs,
            "coverage_pct": coverage_pct,
            "entities": int(raw.get("entities") or 0),
            "trade_days": int(raw.get("trade_days") or 0),
            "start": start,
            "end": end,
            "status_rows": int(raw.get("status_rows") or 0),
            "risk_warning_rows": int(raw.get("risk_warning_rows") or 0),
            "suspended_rows": int(raw.get("suspended_rows") or 0),
            "delisted_symbols": int(raw.get("delisted_symbols") or 0),
            "source_trade_days": int(
                raw.get("source_trade_days") or raw.get("trade_days") or 0
            ),
            "rejected_captures": int(raw.get("rejected_captures") or 0),
        }
        providers.append(provider)
        if valid and (evidence_level != "strict" or history_ready):
            selectable.append(provider)

    strict = [row for row in selectable if row["evidence_level"] == "strict"]
    candidates = strict or [
        row for row in selectable if row["evidence_level"] == "reconstructed"
    ]
    selected = (
        max(
            candidates,
            key=lambda row: (
                int(row["trade_days"]),
                float(row["coverage_pct"]),
                int(row["covered_pairs"]),
                str(row["source"]),
            ),
        )
        if candidates
        else None
    )
    inventory_providers = [
        {
            **row,
            "start": row["start"].isoformat() if row["start"] else None,
            "end": row["end"].isoformat() if row["end"] else None,
        }
        for row in sorted(
            providers,
            key=lambda item: (
                str(item["evidence_level"]),
                str(item["source"]),
            ),
        )
    ]
    if selected is None:
        return _empty_dataset("unavailable"), {
            "status": "unavailable",
            "selected_source": None,
            "providers": inventory_providers,
            "reason": "no validated historical security scope",
        }

    mode = str(selected["evidence_level"])
    coverage = DatasetCoverage(
        rows=int(selected["required_pairs"]),
        entities=int(selected["entities"]),
        trade_days=int(selected["trade_days"]),
        start=selected["start"],
        end=selected["end"],
        coverage_pct=float(selected["coverage_pct"]),
        mode=mode,
        sources=(str(selected["source"]),),
    )
    return coverage, {
        "status": mode,
        "selected_source": str(selected["source"]),
        "providers": inventory_providers,
        "reason": (
            None
            if mode == "strict"
            else "reconstructed rows are excluded from the strict research gate"
        ),
    }


def _market_timing_coverage(
    session,
    as_of_date: date,
) -> tuple[DatasetCoverage, dict[str, Any]]:
    row = session.execute(
        select(schema.market_timing_panel.c.panel, schema.market_timing_panel.c.computed_at)
        .order_by(schema.market_timing_panel.c.computed_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return _empty_dataset("unavailable"), {"rows": 0, "state_counts": {}}

    timing_rows = [
        item
        for item in (row[0] or {}).get("timing_series") or []
        if (parsed := _date_value(item.get("date"))) is not None
        and parsed <= as_of_date
    ]
    dates = sorted(
        parsed for item in timing_rows if (parsed := _date_value(item.get("date")))
    )
    state_counts = Counter(
        (
            str(item.get("active_direction") or "UNKNOWN"),
            str(item.get("danger_state") or "UNKNOWN"),
        )
        for item in timing_rows
    )
    coverage = DatasetCoverage(
        rows=len(timing_rows),
        entities=len(state_counts),
        trade_days=len(set(dates)),
        start=dates[0] if dates else None,
        end=dates[-1] if dates else None,
        coverage_pct=100.0 if dates else 0.0,
        mode="point_in_time_derived",
        sources=("market_timing_panel",),
    )
    inventory = {
        "computed_at": row[1].isoformat() if row[1] else None,
        "state_counts": {
            f"{direction}/{danger}": count
            for (direction, danger), count in sorted(state_counts.items())
        },
    }
    return coverage, inventory


def _supporting_coverage(
    session,
    as_of_date: date,
) -> dict[str, DatasetCoverage]:
    return {
        "stock_minutes_1m": _table_coverage(
            session,
            schema.stock_minute_bars,
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            mode="partial_event_targeted",
            where_clause=schema.stock_minute_bars.c.interval == "1m",
            as_of_date=as_of_date,
        ),
        "stock_auction": _table_coverage(
            session,
            schema.stock_auction_snapshots,
            schema.stock_auction_snapshots.c.vt_symbol,
            schema.stock_auction_snapshots.c.trade_date,
            mode="near_term_snapshot",
            as_of_date=as_of_date,
        ),
        "stock_fund_flow": _table_coverage(
            session,
            schema.stock_fund_flows,
            schema.stock_fund_flows.c.vt_symbol,
            schema.stock_fund_flows.c.trade_date,
            mode="near_term_snapshot",
            as_of_date=as_of_date,
        ),
        "sector_fund_flow": _table_coverage(
            session,
            schema.sector_fund_flows,
            schema.sector_fund_flows.c.sector_id,
            schema.sector_fund_flows.c.trade_date,
            mode="near_term_snapshot",
            as_of_date=as_of_date,
        ),
        "dragon_tiger": _table_coverage(
            session,
            schema.stock_lhb_records,
            schema.stock_lhb_records.c.vt_symbol,
            schema.stock_lhb_records.c.trade_date,
            mode="near_term_public_record",
            as_of_date=as_of_date,
        ),
        "live_concept_strength": _table_coverage(
            session,
            schema.limit_up_concept_strength_snapshots,
            schema.limit_up_concept_strength_snapshots.c.concept_id,
            schema.limit_up_concept_strength_snapshots.c.trade_date,
            mode="near_term_live_snapshot",
            as_of_date=as_of_date,
        ),
    }


def _table_coverage(
    session,
    table,
    entity_column,
    date_column,
    *,
    mode: str,
    as_of_date: date,
    where_clause=None,
) -> DatasetCoverage:
    statement = select(
        func.count(),
        func.count(func.distinct(entity_column)),
        func.count(func.distinct(date_column)),
        func.min(date_column),
        func.max(date_column),
    ).select_from(table)
    filters = [cast(date_column, SqlDate) <= as_of_date]
    if where_clause is not None:
        filters.append(where_clause)
    statement = statement.where(*filters)
    row = session.execute(statement).one()
    sources = _sources(session, table, where_clause=and_(*filters))
    return DatasetCoverage(
        rows=int(row[0] or 0),
        entities=int(row[1] or 0),
        trade_days=int(row[2] or 0),
        start=_date_value(row[3]),
        end=_date_value(row[4]),
        coverage_pct=0.0,
        mode=mode,
        sources=sources,
    )


def _sources(session, table, *, where_clause=None) -> tuple[str, ...]:
    if "source" not in table.c:
        return ()
    statement = select(table.c.source).distinct()
    if where_clause is not None:
        statement = statement.where(where_clause)
    return tuple(
        sorted(str(row[0]) for row in session.execute(statement).all() if row[0])
    )


def _empty_dataset(
    mode: str,
    sources: Iterable[str] = (),
) -> DatasetCoverage:
    return DatasetCoverage(
        rows=0,
        entities=0,
        trade_days=0,
        start=None,
        end=None,
        coverage_pct=0.0,
        mode=mode,
        sources=tuple(sources),
    )


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:10]
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)
