"""Read-only historical inputs for membership-proxy low-suction discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import and_, func, not_, or_, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

from .concept_index_coverage import (
    CANONICAL_CONCEPT_INDEX_SOURCE,
    MIN_ACTIVE_CONCEPTS,
    MIN_COVERAGE_PCT,
    build_dynamic_concept_coverage,
)
from .contracts import CONCEPT_SECTOR_TYPES

MIN_RELIABLE_STOCK_SYMBOLS = 3_000
LEADING_FEATURE_SESSIONS = 45
TRAILING_OUTCOME_SESSIONS = 6
SSE_MAIN_PREFIXES = ("600", "601", "603", "605")
SZSE_MAIN_PREFIXES = ("000", "001", "002", "003")


@dataclass(frozen=True)
class ProxyResearchInputs:
    """Frames required by the daily membership-proxy runner."""

    concept_bars: pd.DataFrame
    stock_bars: pd.DataFrame
    memberships: pd.DataFrame
    signal_dates: tuple[date, ...]
    trading_dates: tuple[date, ...]
    timing_labels: pd.DataFrame
    coverage: dict[str, Any]


def load_proxy_research_inputs(
    *,
    start: date | None = None,
    end: date | None = None,
) -> ProxyResearchInputs:
    """Load the bounded reliable overlap window without modifying PostgreSQL."""

    engine = get_engine()
    with session_scope() as session:
        reliable_dates = _reliable_stock_dates(session)
        complete_concept_dates, concept_inventory = _complete_concept_dates(
            session,
            reliable_stock_dates=reliable_dates,
        )
        signal_dates = tuple(
            trade_date
            for trade_date in complete_concept_dates
            if (start is None or trade_date >= start) and (end is None or trade_date <= end)
        )
        if not signal_dates:
            raise ValueError("no complete concept dates in the requested range")
        load_start, outcome_end, bounded_trading_dates = _bounded_calendar(
            reliable_dates,
            signal_dates,
        )

    concept_bars = pd.read_sql(
        _concept_bars_query(load_start, signal_dates[-1]),
        engine,
        parse_dates=["trade_date"],
    )
    stock_bars = pd.read_sql(
        _stock_bars_query(load_start, outcome_end),
        engine,
        parse_dates=["trade_date"],
    )
    symbols = tuple(sorted(stock_bars["vt_symbol"].dropna().astype(str).unique()))
    memberships = pd.read_sql(_memberships_query(symbols), engine)
    timing_labels = _load_timing_labels()
    coverage = {
        **concept_inventory,
        "signal_start": signal_dates[0].isoformat(),
        "signal_end": signal_dates[-1].isoformat(),
        "signal_trade_days": len(signal_dates),
        "load_start": load_start.isoformat(),
        "outcome_end": outcome_end.isoformat(),
        "stock_rows": int(len(stock_bars)),
        "stock_symbols": int(stock_bars["vt_symbol"].nunique()),
        "concept_rows": int(len(concept_bars)),
        "concepts": int(concept_bars["sector_id"].nunique()),
        "membership_rows": int(len(memberships)),
        "membership_mode": "current_proxy",
        "security_universe_mode": "current_main_board_non_st_proxy",
    }
    return ProxyResearchInputs(
        concept_bars=concept_bars,
        stock_bars=stock_bars,
        memberships=memberships,
        signal_dates=signal_dates,
        trading_dates=bounded_trading_dates,
        timing_labels=timing_labels,
        coverage=coverage,
    )


def _reliable_stock_dates(session) -> tuple[date, ...]:
    rows = session.execute(
        select(
            schema.stock_daily_bars.c.trade_date,
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)),
        )
        .where(
            schema.stock_daily_bars.c.trade_date
            <= completed_daily_bar_cutoff()
        )
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(schema.stock_daily_bars.c.trade_date)
    ).all()
    return tuple(
        row[0] for row in rows if int(row[1] or 0) >= MIN_RELIABLE_STOCK_SYMBOLS
    )


def _complete_concept_dates(
    session,
    *,
    reliable_stock_dates: tuple[date, ...],
) -> tuple[tuple[date, ...], dict[str, Any]]:
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
        )
        .group_by(schema.sector_daily_bars.c.sector_id)
        .order_by(schema.sector_daily_bars.c.sector_id)
    ).all()
    dynamic_rows = build_dynamic_concept_coverage(
        trading_dates=reliable_stock_dates,
        count_rows=tuple((row[0], int(row[1] or 0)) for row in count_rows),
        bounds=tuple((str(row[0]), row[1], row[2]) for row in bound_rows),
    )
    complete_rows = tuple(row for row in dynamic_rows if row.qualifies)
    dates = tuple(row.trade_date for row in complete_rows)
    return dates, {
        "concept_count": concept_count,
        "indexed_concept_count": len(bound_rows),
        "canonical_source": CANONICAL_CONCEPT_INDEX_SOURCE,
        "minimum_active_concepts": MIN_ACTIVE_CONCEPTS,
        "minimum_cross_section_pct": MIN_COVERAGE_PCT,
        "raw_concept_trade_days": len(count_rows),
        "complete_concept_trade_days": len(dates),
        "complete_concept_start": dates[0].isoformat() if dates else None,
        "complete_concept_end": dates[-1].isoformat() if dates else None,
        "minimum_complete_cross_section_pct": (
            min(row.coverage_pct for row in complete_rows)
            if complete_rows
            else 0.0
        ),
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


def _bounded_calendar(
    reliable_dates: tuple[date, ...],
    signal_dates: tuple[date, ...],
) -> tuple[date, date, tuple[date, ...]]:
    first_position = reliable_dates.index(signal_dates[0])
    last_position = reliable_dates.index(signal_dates[-1])
    load_position = max(0, first_position - LEADING_FEATURE_SESSIONS)
    outcome_position = min(
        len(reliable_dates) - 1,
        last_position + TRAILING_OUTCOME_SESSIONS,
    )
    bounded = reliable_dates[load_position : outcome_position + 1]
    return bounded[0], bounded[-1], bounded


def _concept_bars_query(load_start: date, signal_end: date):
    return (
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sectors.c.name.label("concept_name"),
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.open_price,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.high_price,
            schema.sector_daily_bars.c.low_price,
            schema.sector_daily_bars.c.volume,
            schema.sector_daily_bars.c.turnover,
            schema.sector_daily_bars.c.change_pct,
            schema.sector_daily_bars.c.source,
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
            schema.sector_daily_bars.c.trade_date.between(load_start, signal_end),
        )
        .order_by(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.trade_date)
    )


def _stock_bars_query(load_start: date, outcome_end: date):
    symbol = schema.stocks.c.symbol
    main_board = or_(
        and_(
            schema.stocks.c.exchange == "SSE",
            or_(*(symbol.startswith(prefix) for prefix in SSE_MAIN_PREFIXES)),
        ),
        and_(
            schema.stocks.c.exchange == "SZSE",
            or_(*(symbol.startswith(prefix) for prefix in SZSE_MAIN_PREFIXES)),
        ),
    )
    excluded_name = or_(
        schema.stocks.c.name.ilike("%ST%"),
        schema.stocks.c.name.contains("退市"),
        schema.stocks.c.name.startswith("退"),
    )
    return (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.turnover_rate,
            schema.stock_daily_bars.c.change_pct,
            schema.stock_daily_bars.c.source,
            schema.stocks.c.symbol,
            schema.stocks.c.exchange,
            schema.stocks.c.name,
        )
        .select_from(
            schema.stock_daily_bars.join(
                schema.stocks,
                schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_daily_bars.c.trade_date.between(load_start, outcome_end),
            main_board,
            not_(excluded_name),
        )
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    )


def _memberships_query(symbols: tuple[str, ...]):
    return (
        select(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.sector_name.label("concept_name"),
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stock_sector_memberships.c.source,
        )
        .where(
            schema.stock_sector_memberships.c.sector_type.in_(CONCEPT_SECTOR_TYPES),
            schema.stock_sector_memberships.c.vt_symbol.in_(symbols),
        )
        .order_by(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.vt_symbol,
        )
    )


def _load_timing_labels() -> pd.DataFrame:
    with session_scope() as session:
        panel = session.execute(
            select(schema.market_timing_panel.c.panel)
            .order_by(schema.market_timing_panel.c.computed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    rows = []
    for item in (panel or {}).get("timing_series") or []:
        rows.append(
            {
                "trade_date": pd.Timestamp(item.get("date")),
                "active_direction": str(item.get("active_direction") or "UNKNOWN"),
                "zone_direction": str(item.get("zone_direction") or "UNKNOWN"),
                "danger_state": str(item.get("danger_state") or "UNKNOWN"),
                "market_phase": str(item.get("phase") or "UNKNOWN"),
            }
        )
    return pd.DataFrame(rows)
