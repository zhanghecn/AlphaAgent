"""Database loaders for quant screening and backtests."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards, stock_board
from alphaagent.server.db import schema
from alphaagent.server.services.quant.factors import Bar, period_return, score_financial_report


def latest_trade_date(session) -> date | None:
    return session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()


def latest_complete_trade_date(session, min_symbol_count: int = 3000) -> date | None:
    row = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= min_symbol_count)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(1)
    ).first()
    return row[0] if row else None


def daily_symbol_count(session, trade_date: date) -> int:
    return int(
        session.execute(
            select(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))).where(
                schema.stock_daily_bars.c.trade_date == trade_date
            )
        ).scalar()
        or 0
    )


def earliest_trade_date(session) -> date | None:
    return session.execute(select(func.min(schema.stock_daily_bars.c.trade_date))).scalar()


def latest_signal_date(session) -> date | None:
    return session.execute(select(func.max(schema.quant_stock_signals.c.trade_date))).scalar()


def latest_recommendation_date(session) -> date | None:
    return session.execute(select(func.max(schema.quant_recommendations.c.trade_date))).scalar()


def latest_screen_run(
    session,
    strategy_id: str,
    strategy_version: str,
    trade_date: date | None = None,
    *,
    signal_evidence_schema_version: str | None = None,
) -> dict[str, Any] | None:
    query = select(schema.quant_signal_runs).where(
        and_(
            schema.quant_signal_runs.c.strategy_id == strategy_id,
            schema.quant_signal_runs.c.strategy_version == strategy_version,
            schema.quant_signal_runs.c.status == "succeeded",
        )
    )
    if trade_date is not None:
        query = query.where(schema.quant_signal_runs.c.trade_date == trade_date)
    rows = session.execute(
        query
        .order_by(desc(schema.quant_signal_runs.c.trade_date), desc(schema.quant_signal_runs.c.id))
        .limit(50 if signal_evidence_schema_version else 1)
    ).mappings().all()
    for row in rows:
        payload = dict(row)
        if signal_evidence_schema_version is None:
            return payload
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if params.get("signal_evidence_schema_version") == signal_evidence_schema_version:
            return payload
    return None


def trading_dates_between(session, start: date, end: date) -> list[date]:
    rows = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(
            and_(
                schema.stock_daily_bars.c.trade_date >= start,
                schema.stock_daily_bars.c.trade_date <= end,
            )
        )
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(schema.stock_daily_bars.c.trade_date)
    ).all()
    return [row[0] for row in rows]


def run_included_boards(run: dict[str, Any] | None) -> list[str]:
    if not run:
        return list(DEFAULT_QUANT_INCLUDED_BOARDS)
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    return list(normalize_included_boards(params.get("included_boards")))


def load_bars(session, vt_symbols: list[str], trade_date: date, lookback_days: int) -> dict[str, list[Bar]]:
    if not vt_symbols:
        return {}
    start = trade_date - timedelta(days=lookback_days * 2)
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(
            and_(
                schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_daily_bars.c.trade_date >= start,
                schema.stock_daily_bars.c.trade_date <= trade_date,
            )
        )
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    result: dict[str, list[Bar]] = defaultdict(list)
    for row in rows:
        result[str(row["vt_symbol"])].append(
            Bar(
                trade_date=row["trade_date"],
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=float(row["close_price"]),
                volume=row.get("volume"),
                turnover=row.get("turnover"),
                change_pct=row.get("change_pct"),
            )
        )
    return result


def load_intraday_temp_bars(session, vt_symbols: list[str], trade_date: date, interval: str = "1m") -> dict[str, Bar]:
    if not vt_symbols:
        return {}
    aggregate = (
        select(
            schema.stock_minute_bars.c.vt_symbol.label("vt_symbol"),
            func.min(schema.stock_minute_bars.c.bar_time).label("first_time"),
            func.max(schema.stock_minute_bars.c.bar_time).label("last_time"),
            func.max(schema.stock_minute_bars.c.high_price).label("high_price"),
            func.min(schema.stock_minute_bars.c.low_price).label("low_price"),
            func.sum(schema.stock_minute_bars.c.volume).label("volume"),
            func.sum(schema.stock_minute_bars.c.turnover).label("turnover"),
        )
        .where(
            and_(
                schema.stock_minute_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_minute_bars.c.trade_date == trade_date,
                schema.stock_minute_bars.c.interval == interval,
            )
        )
        .group_by(schema.stock_minute_bars.c.vt_symbol)
        .subquery()
    )
    first_bar = schema.stock_minute_bars.alias("first_bar")
    last_bar = schema.stock_minute_bars.alias("last_bar")
    rows = session.execute(
        select(
            aggregate.c.vt_symbol,
            first_bar.c.open_price.label("open_price"),
            last_bar.c.close_price.label("close_price"),
            aggregate.c.high_price,
            aggregate.c.low_price,
            aggregate.c.volume,
            aggregate.c.turnover,
        )
        .select_from(
            aggregate
            .join(
                first_bar,
                and_(
                    first_bar.c.vt_symbol == aggregate.c.vt_symbol,
                    first_bar.c.trade_date == trade_date,
                    first_bar.c.interval == interval,
                    first_bar.c.bar_time == aggregate.c.first_time,
                ),
            )
            .join(
                last_bar,
                and_(
                    last_bar.c.vt_symbol == aggregate.c.vt_symbol,
                    last_bar.c.trade_date == trade_date,
                    last_bar.c.interval == interval,
                    last_bar.c.bar_time == aggregate.c.last_time,
                ),
            )
        )
    ).mappings().all()

    result: dict[str, Bar] = {}
    for row in rows:
        result[str(row["vt_symbol"])] = Bar(
            trade_date=trade_date,
            open_price=float(row["open_price"]),
            high_price=float(row["high_price"]),
            low_price=float(row["low_price"]),
            close_price=float(row["close_price"]),
            volume=float(row["volume"]) if row.get("volume") is not None else None,
            turnover=float(row["turnover"]) if row.get("turnover") is not None else None,
            change_pct=None,
        )
    return result


def load_stock_universe(session, max_symbols: int, included_boards: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.stocks)
        .where(schema.stocks.c.vt_symbol != "000001.SSE")
        .order_by(schema.stocks.c.vt_symbol)
        .limit(5000)
    ).mappings().all()
    allowed = set(included_boards or DEFAULT_QUANT_INCLUDED_BOARDS)
    result = [
        dict(row)
        for row in rows
        if stock_board(row.get("vt_symbol"), row.get("exchange")) in allowed
    ]
    return result[: min(max(max_symbols, 1), 5000)]


def load_index_return_20d(session, trade_date: date) -> float | None:
    rows = session.execute(
        select(schema.stock_daily_bars.c.close_price)
        .where(
            and_(
                schema.stock_daily_bars.c.vt_symbol == "000001.SSE",
                schema.stock_daily_bars.c.trade_date <= trade_date,
            )
        )
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(21)
    ).all()
    closes = [float(row[0]) for row in reversed(rows)]
    return period_return(closes, 20)


def load_sector_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    if not vt_symbols:
        return {}
    memberships = session.execute(
        select(schema.stock_sector_memberships.c.vt_symbol, schema.stock_sector_memberships.c.sector_id)
        .where(schema.stock_sector_memberships.c.vt_symbol.in_(vt_symbols))
    ).mappings().all()
    if not memberships:
        return {}
    sector_ids = sorted({str(row["sector_id"]) for row in memberships})
    latest_scores = session.execute(
        select(schema.sector_period_scores)
        .where(
            and_(
                schema.sector_period_scores.c.sector_id.in_(sector_ids),
                schema.sector_period_scores.c.period == "20d",
                schema.sector_period_scores.c.as_of_date <= trade_date,
            )
        )
        .order_by(desc(schema.sector_period_scores.c.as_of_date))
    ).mappings().all()
    sector_score: dict[str, float] = {}
    for row in latest_scores:
        sector_id = str(row["sector_id"])
        if sector_id not in sector_score:
            sector_score[sector_id] = float(row.get("heat_score") or 50)
    by_symbol: dict[str, float] = {}
    for row in memberships:
        score = sector_score.get(str(row["sector_id"]))
        if score is None:
            continue
        vt_symbol = str(row["vt_symbol"])
        by_symbol[vt_symbol] = max(by_symbol.get(vt_symbol, 0), score)
    return by_symbol


def load_financial_scores(session, vt_symbols: list[str], trade_date: date, parse_date) -> dict[str, float]:
    if not vt_symbols:
        return {}
    rows = session.execute(
        select(schema.stock_financial_reports)
        .where(schema.stock_financial_reports.c.vt_symbol.in_(vt_symbols))
        .order_by(schema.stock_financial_reports.c.vt_symbol, desc(schema.stock_financial_reports.c.report_date))
    ).mappings().all()
    result: dict[str, float] = {}
    for row in rows:
        vt_symbol = str(row["vt_symbol"])
        if vt_symbol in result:
            continue
        publish_date = parse_date(row.get("publish_date"))
        if publish_date is None or publish_date > trade_date:
            continue
        result[vt_symbol] = score_financial_report(dict(row))
    return result


def load_fund_flow_scores(session, vt_symbols: list[str], trade_date: date, float_or_none, clamp) -> dict[str, float]:
    if not vt_symbols:
        return {}
    rows = session.execute(
        select(schema.stock_fund_flows)
        .where(
            and_(
                schema.stock_fund_flows.c.vt_symbol.in_(vt_symbols),
                schema.stock_fund_flows.c.trade_date <= trade_date.isoformat(),
            )
        )
        .order_by(schema.stock_fund_flows.c.vt_symbol, desc(schema.stock_fund_flows.c.trade_date))
    ).mappings().all()
    result: dict[str, float] = {}
    for row in rows:
        vt_symbol = str(row["vt_symbol"])
        if vt_symbol in result:
            continue
        main = float_or_none(row.get("main_net_inflow"))
        ratio = float_or_none(row.get("main_net_inflow_ratio"))
        large = float_or_none(row.get("large_net_inflow"))
        super_large = float_or_none(row.get("super_large_net_inflow"))
        score = 50.0
        if main is not None:
            score += max(min(main / 50_000_000 * 12, 18), -18)
        if ratio is not None:
            score += max(min(ratio * 2.0, 18), -18)
        if super_large is not None:
            score += max(min(super_large / 30_000_000 * 8, 10), -10)
        if large is not None:
            score += max(min(large / 30_000_000 * 6, 8), -8)
        result[vt_symbol] = clamp(score)
    return result


def load_hot_rank_scores(session, vt_symbols: list[str], trade_date: date, float_or_none, clamp) -> dict[str, float]:
    if not vt_symbols:
        return {}
    end_prefix = trade_date.isoformat()
    rows = session.execute(
        select(schema.stock_hot_ranks)
        .where(schema.stock_hot_ranks.c.vt_symbol.in_(vt_symbols))
        .order_by(schema.stock_hot_ranks.c.vt_symbol, desc(schema.stock_hot_ranks.c.rank_time))
    ).mappings().all()
    result: dict[str, float] = {}
    for row in rows:
        vt_symbol = str(row["vt_symbol"])
        if vt_symbol in result:
            continue
        rank_time = str(row.get("rank_time") or "")
        if rank_time and rank_time[:10] > end_prefix:
            continue
        rank = row.get("rank")
        try:
            rank_value = int(rank)
        except (TypeError, ValueError):
            continue
        score = max(35.0, 100.0 - max(rank_value - 1, 0) * 0.8)
        rank_change = float_or_none(row.get("rank_change"))
        if rank_change is not None:
            score += max(min(-rank_change * 1.5, 10), -10)
        result[vt_symbol] = clamp(score)
    return result


def load_lhb_scores(session, vt_symbols: list[str], trade_date: date, float_or_none, clamp) -> dict[str, float]:
    if not vt_symbols:
        return {}
    start_date = (trade_date - timedelta(days=30)).isoformat()
    end_date = trade_date.isoformat()
    rows = session.execute(
        select(schema.stock_lhb_records)
        .where(
            and_(
                schema.stock_lhb_records.c.vt_symbol.in_(vt_symbols),
                schema.stock_lhb_records.c.trade_date >= start_date,
                schema.stock_lhb_records.c.trade_date <= end_date,
            )
        )
        .order_by(schema.stock_lhb_records.c.vt_symbol, desc(schema.stock_lhb_records.c.trade_date))
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["vt_symbol"])].append(dict(row))
    result: dict[str, float] = {}
    for vt_symbol, items in grouped.items():
        score = 50.0
        recent = items[:5]
        score += min(len(recent) * 4, 16)
        net_total = sum(float_or_none(item.get("net_amount")) or 0 for item in recent)
        score += max(min(net_total / 50_000_000 * 12, 18), -18)
        buy_total = sum(float_or_none(item.get("buy_amount")) or 0 for item in recent)
        sell_total = sum(float_or_none(item.get("sell_amount")) or 0 for item in recent)
        if buy_total or sell_total:
            score += max(min((buy_total - sell_total) / max(buy_total + sell_total, 1) * 20, 12), -12)
        result[vt_symbol] = clamp(score)
    return result
