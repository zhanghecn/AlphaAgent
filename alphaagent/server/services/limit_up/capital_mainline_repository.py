"""Read-only data access for daily capital-mainline research."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from json import dumps
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, tuple_

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up import (
    cash_backtest,
    first_board_stock_gene_research,
    history_repository,
    lane_repository,
    repository,
    scheduled_execution,
    sentiment,
)
from alphaagent.server.services.limit_up.capital_mainline_contract import EvidenceLevel
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


CANONICAL_CONCEPT_SOURCE = "eastmoney.board_kline"
SHANGHAI = ZoneInfo("Asia/Shanghai")
FORMAL_EXIT_KEY_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class CapitalMainlineInputs:
    trade_dates: tuple[date, ...]
    concept_bars: tuple[dict[str, object], ...]
    sector_fund_flows: tuple[dict[str, object], ...]
    stock_fund_flows: tuple[dict[str, object], ...]
    memberships: tuple[dict[str, object], ...]
    membership_scopes: tuple[dict[str, object], ...]
    membership_counts: tuple[dict[str, object], ...]
    current_memberships: tuple[dict[str, object], ...]
    stock_bars: tuple[dict[str, object], ...]
    limit_up_events: tuple[dict[str, object], ...]
    sentiment_points: tuple[dict[str, object], ...]
    formal_candidate_days: tuple[dict[str, object], ...]
    coverage: dict[str, object]
    fingerprints: dict[str, object]
    formal_exit_keys: tuple[tuple[str, date], ...] = ()
    formal_exit_prices: tuple[tuple[str, date, float], ...] = ()
    formal_settlement_returns: tuple[tuple[str, date, float], ...] | None = None


def load_capital_mainline_inputs(
    start: date,
    end: date,
    *,
    include_formal_candidates: bool = True,
    include_prior_formal_evidence: bool = False,
    include_stock_bars: bool = True,
    include_all_concept_members: bool = False,
    reconstruct_missing_limit_up_events: bool = False,
) -> CapitalMainlineInputs:
    if start > end:
        raise ValueError("start must be on or before end")
    schema.ensure_schema_once(get_engine())
    warmup_start = _concept_warmup_start(start)
    with session_scope() as session:
        trade_dates = tuple(
            session.execute(
                select(schema.stock_daily_bars.c.trade_date)
                .where(schema.stock_daily_bars.c.trade_date.between(start, end))
                .distinct()
                .order_by(schema.stock_daily_bars.c.trade_date)
            ).scalars()
        )
        concept_bars = _rows(
            session,
            select(
                schema.sector_daily_bars.c.sector_id,
                schema.sectors.c.name.label("sector_name"),
                schema.sector_daily_bars.c.trade_date,
                schema.sector_daily_bars.c.open_price,
                schema.sector_daily_bars.c.high_price,
                schema.sector_daily_bars.c.low_price,
                schema.sector_daily_bars.c.close_price,
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
                schema.sectors.c.type == "concept",
                schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_SOURCE,
                schema.sector_daily_bars.c.trade_date.between(warmup_start, end),
            )
            .order_by(
                schema.sector_daily_bars.c.sector_id,
                schema.sector_daily_bars.c.trade_date,
            ),
        )
        sector_fund_flows = _rows(
            session,
            select(
                schema.sector_fund_flows.c.sector_id,
                schema.sectors.c.name.label("sector_name"),
                schema.sector_fund_flows.c.trade_date,
                schema.sector_fund_flows.c.period,
                schema.sector_fund_flows.c.main_net_inflow,
                schema.sector_fund_flows.c.main_net_inflow_ratio,
                schema.sector_fund_flows.c.rank,
                schema.sector_fund_flows.c.source,
                schema.sector_fund_flows.c.raw,
                schema.sector_fund_flows.c.created_at,
                schema.sector_fund_flows.c.updated_at,
            )
            .select_from(
                schema.sector_fund_flows.join(
                    schema.sectors,
                    schema.sector_fund_flows.c.sector_id == schema.sectors.c.id,
                )
            )
            .where(
                schema.sectors.c.type == "concept",
                schema.sector_fund_flows.c.trade_date >= start.isoformat(),
                schema.sector_fund_flows.c.trade_date <= end.isoformat(),
            ),
        )
        stock_fund_flows = _rows(
            session,
            select(
                schema.stock_fund_flows.c.vt_symbol,
                schema.stock_fund_flows.c.trade_date,
                schema.stock_fund_flows.c.period,
                schema.stock_fund_flows.c.main_net_inflow,
                schema.stock_fund_flows.c.main_net_inflow_ratio,
                schema.stock_fund_flows.c.source,
                schema.stock_fund_flows.c.raw,
                schema.stock_fund_flows.c.created_at,
                schema.stock_fund_flows.c.updated_at,
            ).where(
                schema.stock_fund_flows.c.trade_date >= start.isoformat(),
                schema.stock_fund_flows.c.trade_date <= end.isoformat(),
            ),
        )
        normalized_event_date = func.replace(
            func.substr(schema.stock_events.c.event_date, 1, 10),
            "-",
            "",
        )
        observed_event_symbols = (
            select(schema.stock_events.c.vt_symbol)
            .where(
                schema.stock_events.c.event_type.in_(repository.LIMIT_EVENT_TYPES),
                normalized_event_date >= start.strftime("%Y%m%d"),
                normalized_event_date <= end.strftime("%Y%m%d"),
            )
            .distinct()
        )
        if reconstruct_missing_limit_up_events:
            reconstructed_event_symbols = (
                select(schema.stock_daily_bars.c.vt_symbol)
                .where(
                    schema.stock_daily_bars.c.trade_date.between(start, end),
                    schema.stock_daily_bars.c.change_pct >= 9.5,
                )
                .distinct()
            )
            event_symbols = observed_event_symbols.union(reconstructed_event_symbols)
        else:
            event_symbols = observed_event_symbols
        concept_member_symbols = (
            select(schema.stock_sector_memberships.c.vt_symbol)
            .where(schema.stock_sector_memberships.c.sector_type == "concept")
            .distinct()
            .union(
                select(schema.stock_sector_membership_snapshots.c.vt_symbol)
                .where(
                    schema.stock_sector_membership_snapshots.c.snapshot_date.between(
                        start - timedelta(days=15),
                        end,
                    ),
                    schema.stock_sector_membership_snapshots.c.sector_type
                    == "concept",
                )
                .distinct()
            )
        )
        stock_bar_symbols = (
            concept_member_symbols if include_all_concept_members else event_symbols
        )
        stock_bar_start = (
            start - timedelta(days=15)
            if include_all_concept_members
            else start
        )
        membership_conditions = [
            schema.stock_sector_membership_snapshots.c.snapshot_date.between(
                start - timedelta(days=15),
                end,
            ),
            schema.stock_sector_membership_snapshots.c.sector_type == "concept",
        ]
        current_membership_conditions = [
            schema.stock_sector_memberships.c.sector_type == "concept"
        ]
        if not include_all_concept_members:
            membership_conditions.append(
                schema.stock_sector_membership_snapshots.c.vt_symbol.in_(
                    event_symbols
                )
            )
            current_membership_conditions.append(
                schema.stock_sector_memberships.c.vt_symbol.in_(event_symbols)
            )
        memberships = _rows(
            session,
            select(
                schema.stock_sector_membership_snapshots.c.snapshot_date,
                schema.stock_sector_membership_snapshots.c.vt_symbol,
                schema.stock_sector_membership_snapshots.c.sector_id,
                schema.stock_sector_membership_snapshots.c.sector_name,
                schema.stock_sector_membership_snapshots.c.sector_type,
                schema.stock_sector_membership_snapshots.c.captured_at,
            ).where(*membership_conditions),
        )
        membership_scopes = _rows(
            session,
            select(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date,
                schema.stock_sector_membership_snapshot_scopes.c.scope_type,
                schema.stock_sector_membership_snapshot_scopes.c.captured_at,
                schema.stock_sector_membership_snapshot_scopes.c.expected_sector_count,
                schema.stock_sector_membership_snapshot_scopes.c.captured_sector_count,
                schema.stock_sector_membership_snapshot_scopes.c.row_count,
                schema.stock_sector_membership_snapshot_scopes.c.symbol_count,
                schema.stock_sector_membership_snapshot_scopes.c.complete,
                schema.stock_sector_membership_snapshot_scopes.c.evidence_level,
            ).where(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date.between(
                    start - timedelta(days=15),
                    end,
                ),
                schema.stock_sector_membership_snapshot_scopes.c.scope_type == "concept",
            ),
        )
        current_memberships = _rows(
            session,
            select(
                schema.stock_sector_memberships.c.vt_symbol,
                schema.stock_sector_memberships.c.sector_id,
                schema.stock_sector_memberships.c.sector_name,
                schema.stock_sector_memberships.c.sector_type,
            ).where(*current_membership_conditions),
        )
        snapshot_counts = _rows(
            session,
            select(
                schema.stock_sector_membership_snapshots.c.snapshot_date,
                schema.stock_sector_membership_snapshots.c.sector_id,
                func.count(
                    func.distinct(
                        schema.stock_sector_membership_snapshots.c.vt_symbol
                    )
                ).label("member_count"),
            )
            .where(
                schema.stock_sector_membership_snapshots.c.snapshot_date.between(
                    start - timedelta(days=15),
                    end,
                ),
                schema.stock_sector_membership_snapshots.c.sector_type == "concept",
            )
            .group_by(
                schema.stock_sector_membership_snapshots.c.snapshot_date,
                schema.stock_sector_membership_snapshots.c.sector_id,
            ),
        )
        current_counts = _rows(
            session,
            select(
                schema.stock_sector_memberships.c.sector_id,
                func.count(
                    func.distinct(schema.stock_sector_memberships.c.vt_symbol)
                ).label("member_count"),
            )
            .where(schema.stock_sector_memberships.c.sector_type == "concept")
            .group_by(schema.stock_sector_memberships.c.sector_id),
        )
        membership_counts = tuple(snapshot_counts) + tuple(current_counts)
        stock_bars = (
            _rows(
                session,
                select(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stocks.c.name,
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.open_price,
                    schema.stock_daily_bars.c.high_price,
                    schema.stock_daily_bars.c.low_price,
                    schema.stock_daily_bars.c.close_price,
                    schema.stock_daily_bars.c.turnover,
                    schema.stock_daily_bars.c.turnover_rate,
                    schema.stock_daily_bars.c.change_pct,
                )
                .select_from(
                    schema.stock_daily_bars.join(
                        schema.stocks,
                        schema.stock_daily_bars.c.vt_symbol
                        == schema.stocks.c.vt_symbol,
                    )
                )
                .where(
                    schema.stock_daily_bars.c.trade_date.between(
                        stock_bar_start,
                        end,
                    ),
                    schema.stock_daily_bars.c.vt_symbol.in_(stock_bar_symbols),
                )
                .order_by(
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.vt_symbol,
                ),
            )
            if include_stock_bars
            else []
        )
        raw_event_rows = _rows(
            session,
            select(schema.stock_events).where(
                schema.stock_events.c.event_type.in_(repository.LIMIT_EVENT_TYPES),
                normalized_event_date >= start.strftime("%Y%m%d"),
                normalized_event_date <= end.strftime("%Y%m%d"),
            ),
        )
        reconstructed_limit_up_rows = (
            _rows(
                session,
                select(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stocks.c.name,
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.close_price,
                    schema.stock_daily_bars.c.turnover,
                    schema.stock_daily_bars.c.turnover_rate,
                    schema.stock_daily_bars.c.change_pct,
                )
                .select_from(
                    schema.stock_daily_bars.join(
                        schema.stocks,
                        schema.stock_daily_bars.c.vt_symbol
                        == schema.stocks.c.vt_symbol,
                    )
                )
                .where(
                    schema.stock_daily_bars.c.trade_date.between(start, end),
                    schema.stock_daily_bars.c.change_pct >= 9.5,
                )
                .order_by(
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.vt_symbol,
                ),
            )
            if reconstruct_missing_limit_up_events
            else []
        )
        sentiment_points = tuple(sentiment.load_sentiment_points(session, start, end))

    events = {
        identity: _without_intraday_paths(event)
        for identity, event in lane_repository.merge_rich_event_rows(
            raw_event_rows
        ).items()
    }
    observed_event_dates = sorted(
        {
            event["trade_date"]
            for event in events.values()
            if isinstance(event.get("trade_date"), date)
        }
    )
    observed_event_start = observed_event_dates[0] if observed_event_dates else None
    reconstructed_events = tuple(
        {
            **row,
            "is_sealed": True,
            "event_type": "daily_close_reconstructed_limit_up",
            "source": "stock_daily_bars.daily_close_proxy",
        }
        for row in reconstructed_limit_up_rows
        if (observed_event_start is None or row["trade_date"] < observed_event_start)
        and _eligible_reconstructed_limit_up(row)
    )
    for event in reconstructed_events:
        identity = (event["trade_date"], str(event["vt_symbol"]), "reconstructed")
        events[identity] = event
    event_dates = sorted(
        {
            event["trade_date"]
            for event in events.values()
            if isinstance(event.get("trade_date"), date)
        }
    )
    event_coverage = {
        "lane_event_count": len(events),
        "lane_event_trade_days": len(event_dates),
        "lane_event_start": event_dates[0].isoformat() if event_dates else None,
        "lane_event_end": event_dates[-1].isoformat() if event_dates else None,
        "observed_event_start": (
            observed_event_start.isoformat() if observed_event_start else None
        ),
        "observed_event_end": (
            observed_event_dates[-1].isoformat() if observed_event_dates else None
        ),
        "observed_event_trade_days": len(observed_event_dates),
        "reconstructed_event_count": len(reconstructed_events),
        "reconstructed_event_start": (
            min(event["trade_date"] for event in reconstructed_events).isoformat()
            if reconstructed_events
            else None
        ),
        "reconstructed_event_end": (
            max(event["trade_date"] for event in reconstructed_events).isoformat()
            if reconstructed_events
            else None
        ),
        "intraday_path_event_count": 0,
        "minute_rows_read": 0,
        "stock_bar_universe": (
            "all_concept_members"
            if include_all_concept_members
            else "limit_event_symbols"
        ),
        "stock_bar_start": stock_bar_start.isoformat(),
    }
    formal_candidate_days = (
        history_repository.load_history_range(
            HISTORY_STRATEGY_VERSION,
            None if include_prior_formal_evidence else start,
            end,
            compact=False,
        )
        if include_formal_candidates
        else []
    )
    formal_exit_prices = _load_formal_exit_prices(formal_candidate_days)
    formal_exit_keys = tuple(
        (vt_symbol, trade_date)
        for vt_symbol, trade_date, _ in formal_exit_prices
    )
    formal_settlement_returns = _load_formal_settlement_returns(
        formal_candidate_days,
        trade_dates,
        start=start,
        end=end,
    )
    frames = {
        "concept_bars": concept_bars,
        "sector_fund_flows": sector_fund_flows,
        "stock_fund_flows": stock_fund_flows,
        "memberships": memberships,
        "membership_counts": membership_counts,
        "current_memberships": current_memberships,
        "stock_bars": stock_bars,
        "limit_up_events": tuple(events.values()),
        "sentiment_points": sentiment_points,
    }
    coverage = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "warmup_start": warmup_start.isoformat(),
        "trade_days": len(trade_dates),
        "event_coverage": event_coverage,
        **{f"{name}_rows": len(rows) for name, rows in frames.items()},
        "concepts": len({str(row["sector_id"]) for row in concept_bars}),
        "complete_membership_dates": sorted(
            str(row["snapshot_date"])
            for row in membership_scopes
            if row.get("complete") is True
        ),
        "minute_rows_read": 0,
    }
    return CapitalMainlineInputs(
        trade_dates=trade_dates,
        concept_bars=tuple(concept_bars),
        sector_fund_flows=tuple(sector_fund_flows),
        stock_fund_flows=tuple(stock_fund_flows),
        memberships=tuple(memberships),
        membership_scopes=tuple(membership_scopes),
        membership_counts=membership_counts,
        current_memberships=tuple(current_memberships),
        stock_bars=tuple(stock_bars),
        limit_up_events=tuple(events.values()),
        sentiment_points=sentiment_points,
        formal_candidate_days=tuple(formal_candidate_days),
        coverage=coverage,
        fingerprints={name: _fingerprint(rows) for name, rows in frames.items()},
        formal_exit_keys=formal_exit_keys,
        formal_exit_prices=formal_exit_prices,
        formal_settlement_returns=formal_settlement_returns,
    )


def membership_rows_for_date(
    inputs: CapitalMainlineInputs,
    trade_date: date,
) -> tuple[tuple[dict[str, object], ...], EvidenceLevel, date | None]:
    complete_dates = sorted(
        {
            _as_date(row.get("snapshot_date"))
            for row in inputs.membership_scopes
            if row.get("complete") is True
            and _as_date(row.get("snapshot_date")) is not None
            and _as_date(row.get("snapshot_date")) < trade_date
        }
    )
    if complete_dates:
        snapshot_date = complete_dates[-1]
        return (
            tuple(
                row
                for row in inputs.memberships
                if _as_date(row.get("snapshot_date")) == snapshot_date
            ),
            EvidenceLevel.POINT_IN_TIME,
            snapshot_date,
        )
    return (
        inputs.current_memberships,
        EvidenceLevel.CURRENT_MEMBERSHIP_PROXY,
        None,
    )


def _eligible_reconstructed_limit_up(row: Mapping[str, object]) -> bool:
    from alphaagent.server.services.limit_up.domain import is_eligible_main_board

    return is_eligible_main_board(
        str(row.get("vt_symbol") or ""),
        str(row.get("name") or ""),
    )


def _load_formal_exit_prices(
    days: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, date, float], ...]:
    requests = sorted(
        {
            (str(candidate.get("vt_symbol") or ""), result_date)
            for day in days
            for candidate in _candidate_pool_rows(day)
            if (result_date := _as_date(candidate.get("result_date"))) is not None
            and candidate.get("vt_symbol")
        }
    )
    if not requests:
        return ()
    available: dict[tuple[str, date], float] = {}
    with session_scope() as session:
        for offset in range(0, len(requests), FORMAL_EXIT_KEY_BATCH_SIZE):
            batch = requests[offset : offset + FORMAL_EXIT_KEY_BATCH_SIZE]
            rows = session.execute(
                select(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.close_price,
                ).where(
                    tuple_(
                        schema.stock_daily_bars.c.vt_symbol,
                        schema.stock_daily_bars.c.trade_date,
                    ).in_(batch),
                    schema.stock_daily_bars.c.close_price > 0,
                )
            ).all()
            available.update(
                {
                    (str(row[0]), row[1]): float(row[2])
                    for row in rows
                }
            )
    return tuple(
        (vt_symbol, trade_date, close_price)
        for (vt_symbol, trade_date), close_price in sorted(available.items())
    )


def _candidate_pool_rows(
    day: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    portfolio = day.get("lane_portfolio")
    portfolio = portfolio if isinstance(portfolio, Mapping) else {}
    pools = portfolio.get("candidate_pool")
    pools = pools if isinstance(pools, Mapping) else {}
    return tuple(
        candidate
        for candidates in pools.values()
        if isinstance(candidates, Sequence)
        and not isinstance(candidates, (str, bytes))
        for candidate in candidates
        if isinstance(candidate, Mapping)
    )


def _load_formal_settlement_returns(
    days: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    start: date,
    end: date,
) -> tuple[tuple[str, date, float], ...]:
    if not days or not trade_dates:
        return ()
    orders = scheduled_execution.extract_scheduled_orders(days)
    enriched = first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
        days,
        orders,
    )
    qualified, _ = scheduled_execution.filter_profitability_qualified_orders(enriched)
    scoped = [
        order
        for order in qualified
        if (
            signal_date := _as_date(
                order.get("signal_date") or order.get("entry_date")
            )
        )
        is not None
        and start <= signal_date <= end
    ]
    if not scoped:
        return ()
    first_signal_date = min(
        signal_date
        for order in scoped
        if (
            signal_date := _as_date(
                order.get("signal_date") or order.get("entry_date")
            )
        )
        is not None
    )
    symbols = sorted({str(order.get("vt_symbol") or "") for order in scoped})
    bars = history_repository.load_account_daily_bars(
        symbols,
        first_signal_date,
        end,
    )
    bars_by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for bar in bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(dict(bar))
    config = cash_backtest.CashBacktestConfig(
        initial_cash=100_000,
        max_positions=scheduled_execution.MAX_POSITIONS,
    )
    settlements: list[tuple[str, date, float]] = []
    for order in scoped:
        vt_symbol = str(order.get("vt_symbol") or "")
        signal_date = _as_date(order.get("signal_date") or order.get("entry_date"))
        account = cash_backtest.simulate_limit_up_account(
            [order],
            bars_by_symbol.get(vt_symbol, []),
            trade_dates,
            scheduled_execution.EXIT_MODE,
            config,
        )
        trades = account.get("executed_trades") or []
        if signal_date is None or len(trades) != 1:
            continue
        settlements.append(
            (vt_symbol, signal_date, float(trades[0]["return_pct"]))
        )
    return tuple(sorted(settlements))


def fund_flow_known_at(row: Mapping[str, object]) -> datetime | None:
    raw = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
    source_value = raw.get("source_updated_at") if isinstance(raw, Mapping) else None
    parsed = _as_datetime(source_value)
    if parsed is not None:
        return parsed
    return _as_datetime(row.get("updated_at"))


def flow_is_known_for_next_session(
    row: Mapping[str, object],
    next_trade_date: date,
    *,
    decision_time: time = time(9, 25),
) -> bool:
    known_at = fund_flow_known_at(row)
    if known_at is None:
        return False
    cutoff = datetime.combine(next_trade_date, decision_time, tzinfo=SHANGHAI)
    return known_at <= cutoff


def _concept_warmup_start(start: date) -> date:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        values = tuple(
            session.execute(
                select(schema.sector_daily_bars.c.trade_date)
                .select_from(
                    schema.sector_daily_bars.join(
                        schema.sectors,
                        schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
                    )
                )
                .where(
                    schema.sectors.c.type == "concept",
                    schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_SOURCE,
                    schema.sector_daily_bars.c.trade_date < start,
                )
                .distinct()
                .order_by(schema.sector_daily_bars.c.trade_date.desc())
                .limit(25)
            ).scalars()
        )
    return min(values) if values else start


def _rows(session: Any, statement: Any) -> tuple[dict[str, object], ...]:
    return tuple(dict(row) for row in session.execute(statement).mappings())


def _fingerprint(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    identities = [
        (
            row.get("trade_date") or row.get("snapshot_date"),
            row.get("sector_id") or row.get("vt_symbol"),
            row.get("period"),
        )
        for row in rows
    ]
    payload = dumps(identities, ensure_ascii=True, sort_keys=True, default=str)
    return {"rows": len(rows), "sha256": sha256(payload.encode()).hexdigest()}


def _without_intraday_paths(event: Mapping[str, object]) -> dict[str, object]:
    excluded = {
        "minute_price_path",
        "minute_path_bar_count",
        "minute_path_valid_point_count",
        "path_source",
        "time_preview",
    }
    return {str(key): value for key, value in event.items() if key not in excluded}


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)
