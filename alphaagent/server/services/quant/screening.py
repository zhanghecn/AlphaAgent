"""Database-backed quant screening orchestration."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from json import dumps
from typing import Any

from sqlalchemy import and_, desc, func, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards, stock_board, stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.quant.factors import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    Bar,
    SignalScore,
    period_return,
    score_financial_report,
    score_stock,
)


DEFAULT_RECOMMENDATION_LIMIT = 20


def screen_stocks(
    trade_date: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 500,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    min_recommendation_score: float = 60.0,
    persist: bool = False,
    auto_portfolio: bool = True,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
) -> dict[str, Any]:
    """Run the daily stock screen."""

    if strategy_id != STRATEGY_ID:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": [], "recommendations": []}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": [], "recommendations": []}
    _ensure_quant_schema()

    with session_scope() as session:
        as_of = trade_date or _latest_trade_date(session)
        if as_of is None:
            return {"status": "empty", "message": "stock_daily_bars is empty", "items": [], "recommendations": []}

        boards = normalize_included_boards(included_boards)
        stock_rows = _load_stock_universe(session, max_symbols, boards)
        symbols = [str(row["vt_symbol"]) for row in stock_rows]
        bars_by_symbol = _load_bars(session, symbols, as_of, lookback_days=160)
        index_return_20d = _load_index_return_20d(session, as_of)
        sector_scores = _load_sector_scores(session, symbols, as_of)
        financial_scores = _load_financial_scores(session, symbols, as_of)
        fund_flow_scores = _load_fund_flow_scores(session, symbols, as_of)
        hot_rank_scores = _load_hot_rank_scores(session, symbols, as_of)
        lhb_scores = _load_lhb_scores(session, symbols, as_of)

        scored = []
        stock_meta = {str(row["vt_symbol"]): dict(row) for row in stock_rows}
        for vt_symbol in symbols:
            score = score_stock(
                vt_symbol,
                bars_by_symbol.get(vt_symbol, []),
                as_of,
                index_return_20d=index_return_20d,
                sector_score=sector_scores.get(vt_symbol),
                financial_score=financial_scores.get(vt_symbol),
                fund_flow_score=fund_flow_scores.get(vt_symbol),
                hot_rank_score=hot_rank_scores.get(vt_symbol),
                lhb_score=lhb_scores.get(vt_symbol),
            )
            if score.evidence.get("status") == "ready":
                scored.append(score)

        scored.sort(key=lambda item: (-item.total_score, item.vt_symbol))
        recommendations = [
            item
            for item in scored
            if item.entry_signal or item.total_score >= min_recommendation_score
        ][:recommendation_limit]
        run_id = None
        portfolio_sync = None
        if persist:
            run_id = _persist_screen_run(session, as_of, scored, recommendations, strategy_id, boards)
            if auto_portfolio:
                portfolio_sync = _sync_quant_candidate_group(session, recommendations, stock_meta, strategy_id)

    return {
        "status": "ready" if scored else "empty",
        "strategy_id": strategy_id,
        "strategy_version": STRATEGY_VERSION,
        "trade_date": as_of.isoformat(),
        "run_id": run_id,
        "items": [_score_to_api(item, stock_meta.get(item.vt_symbol)) for item in scored],
        "recommendations": [
            _recommendation_to_api(index + 1, item, stock_meta.get(item.vt_symbol))
            for index, item in enumerate(recommendations)
        ],
        "total": len(scored),
        "recommendation_count": len(recommendations),
        "included_boards": list(boards),
        "portfolio_sync": portfolio_sync,
    }


def list_signals(trade_date: date | None = None, strategy_id: str = STRATEGY_ID, limit: int = 100) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()
    with session_scope() as session:
        run = _latest_screen_run(session, strategy_id, trade_date)
        as_of = run["trade_date"] if run else trade_date or _latest_signal_date(session) or _latest_trade_date(session)
        if as_of is None:
            return {"status": "empty", "items": []}
        filters = (
            [schema.quant_stock_signals.c.run_id == run["id"]]
            if run
            else [
                schema.quant_stock_signals.c.trade_date == as_of,
                schema.quant_stock_signals.c.strategy_id == strategy_id,
                schema.quant_stock_signals.c.strategy_version == STRATEGY_VERSION,
            ]
        )
        rows = session.execute(
            select(schema.quant_stock_signals)
            .where(and_(*filters))
            .order_by(desc(schema.quant_stock_signals.c.total_score))
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
    return {
        "status": "ready" if rows else "empty",
        "trade_date": as_of.isoformat(),
        "run_id": int(run["id"]) if run else None,
        "strategy_version": str(run["strategy_version"]) if run else STRATEGY_VERSION,
        "included_boards": _run_included_boards(run),
        "items": [_mapping_to_api(dict(row)) for row in rows],
    }


def list_recommendations(trade_date: date | None = None, strategy_id: str = STRATEGY_ID, limit: int = 50) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()
    with session_scope() as session:
        run = _latest_screen_run(session, strategy_id, trade_date)
        as_of = run["trade_date"] if run else trade_date or _latest_recommendation_date(session) or _latest_trade_date(session)
        if as_of is None:
            return {"status": "empty", "items": []}
        filters = (
            [schema.quant_recommendations.c.run_id == run["id"]]
            if run
            else [
                schema.quant_recommendations.c.trade_date == as_of,
                schema.quant_recommendations.c.strategy_id == strategy_id,
                schema.quant_recommendations.c.strategy_version == STRATEGY_VERSION,
            ]
        )
        rows = session.execute(
            select(
                schema.quant_recommendations,
                schema.stocks.c.name.label("stock_name"),
            )
            .select_from(
                schema.quant_recommendations.outerjoin(
                    schema.stocks,
                    schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(and_(*filters))
            .order_by(schema.quant_recommendations.c.rank)
            .limit(min(max(limit, 1), 200))
        ).mappings().all()
    return {
        "status": "ready" if rows else "empty",
        "trade_date": as_of.isoformat(),
        "run_id": int(run["id"]) if run else None,
        "strategy_version": str(run["strategy_version"]) if run else STRATEGY_VERSION,
        "included_boards": _run_included_boards(run),
        "items": [_recommendation_row_to_api(dict(row)) for row in rows],
    }


def get_recommendation(recommendation_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()
    with session_scope() as session:
        row = session.execute(
            select(
                schema.quant_recommendations,
                schema.stocks.c.name.label("stock_name"),
            )
            .select_from(
                schema.quant_recommendations.outerjoin(
                    schema.stocks,
                    schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(schema.quant_recommendations.c.id == recommendation_id)
        ).mappings().first()
    if not row:
        return {"status": "not_found", "id": recommendation_id}
    return {"status": "ready", "item": _recommendation_row_to_api(dict(row))}


def get_run(run_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()
    with session_scope() as session:
        row = session.execute(select(schema.quant_signal_runs).where(schema.quant_signal_runs.c.id == run_id)).mappings().first()
    if not row:
        return {"status": "not_found", "id": run_id}
    return {"status": "ready", "item": _mapping_to_api(dict(row))}


def symbol_signal_history(
    vt_symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    min_entry_score: float = 68.0,
    limit: int = 200,
) -> dict[str, Any]:
    symbol = str(vt_symbol or "").strip().upper()
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        stock = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol == symbol)).mappings().first()
        if not stock:
            return {"status": "not_found", "vt_symbol": symbol, "items": []}
        latest = end or session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date)).where(schema.stock_daily_bars.c.vt_symbol == symbol)
        ).scalar()
        if latest is None:
            return {"status": "empty", "vt_symbol": symbol, "items": []}
        earliest = start or session.execute(
            select(func.min(schema.stock_daily_bars.c.trade_date)).where(schema.stock_daily_bars.c.vt_symbol == symbol)
        ).scalar()
        bars = _load_bars(session, [symbol], latest, lookback_days=max((latest - earliest).days + 120, 200)).get(symbol, [])
        trade_dates = [bar.trade_date for bar in bars if earliest <= bar.trade_date <= latest]
        rows = []
        for trade_date in trade_dates:
            index_return_20d = _load_index_return_20d(session, trade_date)
            sector_score = _load_sector_scores(session, [symbol], trade_date).get(symbol)
            financial_score = _load_financial_scores(session, [symbol], trade_date).get(symbol)
            fund_flow_score = _load_fund_flow_scores(session, [symbol], trade_date).get(symbol)
            hot_rank_score = _load_hot_rank_scores(session, [symbol], trade_date).get(symbol)
            lhb_score = _load_lhb_scores(session, [symbol], trade_date).get(symbol)
            score = score_stock(
                symbol,
                bars,
                trade_date,
                index_return_20d=index_return_20d,
                sector_score=sector_score,
                financial_score=financial_score,
                fund_flow_score=fund_flow_score,
                hot_rank_score=hot_rank_score,
                lhb_score=lhb_score,
            )
            if score.evidence.get("status") != "ready":
                continue
            rows.append(_symbol_signal_row(score, min_entry_score))

    trigger_rows = [row for row in rows if row["entry_signal"]]
    near_rows = sorted(rows, key=lambda row: (row["failed_rule_count"], -float(row["total_score"]), abs(float(row.get("ma5_distance_pct") or 999))))[:limit]
    recent_rows = sorted(rows, key=lambda row: row["trade_date"], reverse=True)[:limit]
    best_total = max(rows, key=lambda row: float(row["total_score"]), default=None)
    best_entry_fit = near_rows[0] if near_rows else None
    return {
        "status": "ready" if rows else "empty",
        "vt_symbol": symbol,
        "name": stock.get("name"),
        **stock_board_payload(symbol, stock.get("exchange")),
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "start_date": earliest.isoformat() if earliest else None,
        "end_date": latest.isoformat(),
        "entry_signal_count": len(trigger_rows),
        "entry_signals": trigger_rows[:limit],
        "best_total_score": best_total,
        "best_entry_fit": best_entry_fit,
        "near_misses": near_rows,
        "recent": recent_rows,
        "rule": {
            "min_entry_score": min_entry_score,
            "ma5_distance_pct": "[-1.5, 2.0]",
            "min_risk_score": 35,
            "min_liquidity_score": 25,
        },
    }


def _ensure_quant_schema() -> None:
    """Allow quant screening to run from service calls, not only API startup."""

    schema.create_schema(get_engine())


def _latest_trade_date(session) -> date | None:
    return session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()


def _latest_signal_date(session) -> date | None:
    return session.execute(select(func.max(schema.quant_stock_signals.c.trade_date))).scalar()


def _latest_recommendation_date(session) -> date | None:
    return session.execute(select(func.max(schema.quant_recommendations.c.trade_date))).scalar()


def _latest_screen_run(session, strategy_id: str, trade_date: date | None = None) -> dict[str, Any] | None:
    query = select(schema.quant_signal_runs).where(
        and_(
            schema.quant_signal_runs.c.strategy_id == strategy_id,
            schema.quant_signal_runs.c.strategy_version == STRATEGY_VERSION,
            schema.quant_signal_runs.c.status == "succeeded",
        )
    )
    if trade_date is not None:
        query = query.where(schema.quant_signal_runs.c.trade_date == trade_date)
    row = session.execute(
        query
        .order_by(desc(schema.quant_signal_runs.c.trade_date), desc(schema.quant_signal_runs.c.id))
        .limit(1)
    ).mappings().first()
    return dict(row) if row else None


def _run_included_boards(run: dict[str, Any] | None) -> list[str]:
    if not run:
        return list(DEFAULT_QUANT_INCLUDED_BOARDS)
    params = run.get("params") if isinstance(run.get("params"), dict) else {}
    return list(normalize_included_boards(params.get("included_boards")))


def _load_bars(session, vt_symbols: list[str], trade_date: date, lookback_days: int) -> dict[str, list[Bar]]:
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


def _load_stock_universe(session, max_symbols: int, included_boards: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.stocks)
        .where(schema.stocks.c.vt_symbol != "000001.SSE")
        .order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
        .limit(5000)
    ).mappings().all()
    allowed = set(included_boards or DEFAULT_QUANT_INCLUDED_BOARDS)
    result = [
        dict(row)
        for row in rows
        if stock_board(row.get("vt_symbol"), row.get("exchange")) in allowed
    ]
    return result[: min(max(max_symbols, 1), 5000)]


def _load_index_return_20d(session, trade_date: date) -> float | None:
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


def _load_sector_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
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


def _load_financial_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
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
        publish_date = _parse_date(row.get("publish_date"))
        if publish_date is None or publish_date > trade_date:
            continue
        result[vt_symbol] = score_financial_report(dict(row))
    return result


def _load_fund_flow_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
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
        main = _float_or_none(row.get("main_net_inflow"))
        ratio = _float_or_none(row.get("main_net_inflow_ratio"))
        large = _float_or_none(row.get("large_net_inflow"))
        super_large = _float_or_none(row.get("super_large_net_inflow"))
        score = 50.0
        if main is not None:
            score += max(min(main / 50_000_000 * 12, 18), -18)
        if ratio is not None:
            score += max(min(ratio * 2.0, 18), -18)
        if super_large is not None:
            score += max(min(super_large / 30_000_000 * 8, 10), -10)
        if large is not None:
            score += max(min(large / 30_000_000 * 6, 8), -8)
        result[vt_symbol] = _clamp(score)
    return result


def _load_hot_rank_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
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
        rank_change = _float_or_none(row.get("rank_change"))
        if rank_change is not None:
            score += max(min(-rank_change * 1.5, 10), -10)
        result[vt_symbol] = _clamp(score)
    return result


def _load_lhb_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
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
        net_total = sum(_float_or_none(item.get("net_amount")) or 0 for item in recent)
        score += max(min(net_total / 50_000_000 * 12, 18), -18)
        buy_total = sum(_float_or_none(item.get("buy_amount")) or 0 for item in recent)
        sell_total = sum(_float_or_none(item.get("sell_amount")) or 0 for item in recent)
        if buy_total or sell_total:
            score += max(min((buy_total - sell_total) / max(buy_total + sell_total, 1) * 20, 12), -12)
        result[vt_symbol] = _clamp(score)
    return result


def _persist_screen_run(
    session,
    trade_date: date,
    scored: list[SignalScore],
    recommendations: list[SignalScore],
    strategy_id: str,
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS,
) -> int:
    now = datetime.now(timezone.utc)
    run_id = session.execute(
        schema.quant_signal_runs.insert()
        .values(
            strategy_id=strategy_id,
            strategy_version=STRATEGY_VERSION,
            trade_date=trade_date,
            status="succeeded",
            params={"included_boards": list(included_boards)},
            candidate_count=len(scored),
            signal_count=sum(1 for item in scored if item.entry_signal),
            recommendation_count=len(recommendations),
            message="daily close signal, next open execution",
            finished_at=now,
        )
        .returning(schema.quant_signal_runs.c.id)
    ).scalar_one()

    _clear_existing_screen_outputs(session, trade_date, strategy_id)

    for item in scored:
        values = _score_to_db(item, run_id, strategy_id)
        session.execute(schema.quant_stock_signals.insert().values(**values))

    for rank, item in enumerate(recommendations, start=1):
        values = _recommendation_to_db(rank, item, run_id, strategy_id)
        session.execute(schema.quant_recommendations.insert().values(**values))
    return int(run_id)


def _clear_existing_screen_outputs(session, trade_date: date, strategy_id: str) -> None:
    match_current_run = and_(
        schema.quant_recommendations.c.trade_date == trade_date,
        schema.quant_recommendations.c.strategy_id == strategy_id,
        schema.quant_recommendations.c.strategy_version == STRATEGY_VERSION,
    )
    session.execute(schema.quant_recommendations.delete().where(match_current_run))
    session.execute(
        schema.quant_stock_signals.delete().where(
            and_(
                schema.quant_stock_signals.c.trade_date == trade_date,
                schema.quant_stock_signals.c.strategy_id == strategy_id,
                schema.quant_stock_signals.c.strategy_version == STRATEGY_VERSION,
            )
        )
    )


def _sync_quant_candidate_group(
    session,
    recommendations: list[SignalScore],
    stock_meta: dict[str, dict[str, Any]],
    strategy_id: str,
) -> dict[str, Any]:
    group_id = _ensure_auto_group(session, "量化候选", "quant_candidate", "每日量化筛选候选，不代表买入")
    session.execute(
        schema.portfolio_group_items.delete().where(
            and_(
                schema.portfolio_group_items.c.group_id == group_id,
                schema.portfolio_group_items.c.source == "quant",
                schema.portfolio_group_items.c.strategy_id == strategy_id,
            )
        )
    )

    inserted = 0
    for rank, item in enumerate(recommendations, start=1):
        stock = stock_meta.get(item.vt_symbol) or {}
        values = {
            "group_id": group_id,
            "vt_symbol": item.vt_symbol,
            "name": stock.get("name"),
            "source": "quant",
            "reason": dumps(
                {
                    "rank": rank,
                    "total_score": item.total_score,
                    "trade_date": item.trade_date.isoformat(),
                    "entry_rule": item.evidence.get("entry_rule"),
                    "risk_level": item.risk_level,
                },
                ensure_ascii=False,
            ),
            "strategy_id": strategy_id,
            "strategy_version": STRATEGY_VERSION,
            "expires_at": item.trade_date + timedelta(days=7),
        }
        existing = session.execute(
            select(schema.portfolio_group_items.c.vt_symbol).where(
                and_(
                    schema.portfolio_group_items.c.group_id == group_id,
                    schema.portfolio_group_items.c.vt_symbol == item.vt_symbol,
                )
            )
        ).scalar_one_or_none()
        if existing:
            session.execute(
                schema.portfolio_group_items.update()
                .where(
                    and_(
                        schema.portfolio_group_items.c.group_id == group_id,
                        schema.portfolio_group_items.c.vt_symbol == item.vt_symbol,
                    )
                )
                .values(**values)
            )
        else:
            session.execute(schema.portfolio_group_items.insert().values(**values))
        inserted += 1

    return {"group_id": int(group_id), "group_type": "quant_candidate", "synced": inserted}


def _ensure_auto_group(session, name: str, group_type: str, description: str) -> int:
    existing = session.execute(
        select(schema.portfolio_groups.c.id).where(schema.portfolio_groups.c.group_type == group_type)
    ).scalar_one_or_none()
    if existing:
        return int(existing)
    return int(
        session.execute(
            schema.portfolio_groups.insert()
            .values(
                name=name,
                group_type=group_type,
                auto_managed=True,
                description=description,
                risk_profile="balanced",
            )
            .returning(schema.portfolio_groups.c.id)
        ).scalar_one()
    )


def _score_to_db(item: SignalScore, run_id: int | None, strategy_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "trade_date": item.trade_date,
        "vt_symbol": item.vt_symbol,
        "strategy_id": strategy_id,
        "strategy_version": STRATEGY_VERSION,
        "signal_type": item.signal_type,
        "total_score": item.total_score,
        "relative_strength_score": item.relative_strength_score,
        "washout_score": item.washout_score,
        "trend_quality_score": item.trend_quality_score,
        "sector_mainline_score": item.sector_mainline_score,
        "financial_improvement_score": item.financial_improvement_score,
        "liquidity_score": item.liquidity_score,
        "risk_score": item.risk_score,
        "entry_signal": item.entry_signal,
        "risk_level": item.risk_level,
        "evidence": item.evidence,
    }


def _recommendation_to_db(rank: int, item: SignalScore, run_id: int | None, strategy_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "trade_date": item.trade_date,
        "vt_symbol": item.vt_symbol,
        "strategy_id": strategy_id,
        "strategy_version": STRATEGY_VERSION,
        "rank": rank,
        "action": "BUY" if item.entry_signal else "WATCH",
        "horizon": "SWING",
        "confidence": item.total_score / 100,
        "total_score": item.total_score,
        "reason": item.evidence,
        "risk_control": default_risk_control(),
        "status": "active",
        "expires_at": item.trade_date + timedelta(days=7),
    }


def _symbol_signal_row(item: SignalScore, min_entry_score: float) -> dict[str, Any]:
    evidence = item.evidence or {}
    ma5_distance = evidence.get("ma5_distance_pct")
    failed_rules = []
    if item.total_score < min_entry_score:
        failed_rules.append("total_score")
    if ma5_distance is None or not (-1.5 <= float(ma5_distance) <= 2.0):
        failed_rules.append("ma5_distance")
    if item.risk_score < 35:
        failed_rules.append("risk_score")
    if item.liquidity_score < 25:
        failed_rules.append("liquidity_score")
    return {
        "trade_date": item.trade_date.isoformat(),
        "vt_symbol": item.vt_symbol,
        "total_score": item.total_score,
        "relative_strength_score": item.relative_strength_score,
        "washout_score": item.washout_score,
        "trend_quality_score": item.trend_quality_score,
        "sector_mainline_score": item.sector_mainline_score,
        "financial_improvement_score": item.financial_improvement_score,
        "liquidity_score": item.liquidity_score,
        "risk_score": item.risk_score,
        "entry_signal": item.entry_signal,
        "ma5": evidence.get("ma5"),
        "ma5_distance_pct": ma5_distance,
        "turnover20": evidence.get("turnover20"),
        "turnover_estimated_from_volume": evidence.get("turnover_estimated_from_volume"),
        "failed_rules": failed_rules,
        "failed_rule_count": len(failed_rules),
        "evidence": evidence,
    }


def _score_to_api(item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _score_to_db(item, None, STRATEGY_ID)
    payload.pop("run_id", None)
    payload["trade_date"] = item.trade_date.isoformat()
    payload["name"] = stock.get("name") if stock else None
    payload.update(stock_board_payload(item.vt_symbol, (stock or {}).get("exchange")))
    return payload


def _recommendation_to_api(rank: int, item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _recommendation_to_db(rank, item, None, STRATEGY_ID)
    payload.pop("run_id", None)
    payload["trade_date"] = item.trade_date.isoformat()
    payload["expires_at"] = payload["expires_at"].isoformat()
    payload["name"] = stock.get("name") if stock else None
    payload.update(stock_board_payload(item.vt_symbol, (stock or {}).get("exchange")))
    return payload


def default_risk_control() -> dict[str, Any]:
    return {
        "max_position_pct": 0.125,
        "stop_loss_pct": 0.07,
        "take_profit_pct": 0.18,
        "trailing_stop_pct": 0.08,
        "time_stop_days": 15,
        "execution": "D close signal; D+1 tail-window minute fill when available, otherwise next-open simulation fallback",
    }


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if result.get("vt_symbol"):
        result.update(stock_board_payload(result.get("vt_symbol")))
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _recommendation_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = _mapping_to_api(row)
    result["name"] = result.pop("stock_name", None)
    return result


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 4)
