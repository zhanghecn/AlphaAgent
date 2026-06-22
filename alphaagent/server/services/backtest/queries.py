"""Read-side helpers for AlphaAgent backtest reports and drilldowns."""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date, timedelta
from statistics import median
from typing import Any, Callable

from sqlalchemy import and_, desc, func, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards
from alphaagent.server.services.quant.factors import Bar, score_dragon_pullback
from alphaagent.server.services.quant import market_context
from alphaagent.server.services.quant import screening_payloads
from alphaagent.server.services.quant import screening_loaders
from alphaagent.server.services.quant.strategy_registry import score_strategy
from alphaagent.server.services.quant.low_suction_quality import (
    low_suction_dragon_context,
    low_suction_dragon_context_label,
    low_suction_launch_quality_bucket,
    low_suction_launch_quality_label,
)

DateParser = Callable[[Any], date | None]
ApiMapper = Callable[[dict[str, Any]], dict[str, Any]]
SymbolNormalizer = Callable[[Any], str]
BoardPayload = Callable[[Any, dict[str, Any] | None], dict[str, str]]
StockNameLoader = Callable[[Any, list[str]], dict[str, dict[str, Any]]]
RowsSymbols = Callable[..., list[str]]
NameAppender = Callable[[list[dict[str, Any]], dict[str, dict[str, Any]]], list[dict[str, Any]]]
ClosedTrades = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]

BUY_POINT_BAD = "buy_point_bad"
SELL_GIVEBACK = "sell_giveback"
SOLD_TOO_EARLY = "sold_too_early"
PORTFOLIO_CAPACITY_MISS = "portfolio_capacity_miss"
REPLACEMENT_BAD = "replacement_bad"
HEALTHY_TREND_WINNER = "healthy_trend_winner"
UNKNOWN = "unknown"


def backtest_trades(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    limit: int = 500,
    offset: int = 0,
    order: str = "desc",
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    ensure_schema()
    row_limit = min(max(limit, 1), 2000)
    row_offset = max(offset, 0)
    is_desc = str(order or "desc").lower() != "asc"
    ordering = (
        (desc(schema.backtest_trades.c.trade_date), desc(schema.backtest_trades.c.id))
        if is_desc
        else (schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
    )
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs.c.id).where(schema.backtest_runs.c.id == backtest_id)).first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        total = session.execute(
            select(func.count()).select_from(schema.backtest_trades).where(schema.backtest_trades.c.backtest_id == backtest_id)
        ).scalar_one()
        rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(*ordering)
            .offset(row_offset)
            .limit(row_limit)
        ).mappings().all()
        row_dicts = [dict(row) for row in rows]
        stock_names = load_stock_names(session, symbols_from_rows(row_dicts))
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "items": [to_api(row) for row in with_stock_names(row_dicts, stock_names)],
        "limit": row_limit,
        "offset": row_offset,
        "total": int(total or 0),
        "returned_count": len(rows),
        "has_more": row_offset + len(rows) < int(total or 0),
    }


def backtest_equity(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    to_api: ApiMapper,
    backtest_id: int,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    ensure_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
    return {"status": "ready" if rows else "empty", "items": [to_api(dict(row)) for row in rows]}


def backtest_daily_decisions(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    to_api: ApiMapper,
    backtest_id: int,
    limit: int = 500,
    offset: int = 0,
    order: str = "desc",
) -> dict[str, Any]:
    """Return the portfolio candidate -> signal -> order -> trade chain by execution day."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    row_limit = min(max(limit, 1), 2000)
    row_offset = max(offset, 0)
    is_desc = str(order or "desc").lower() != "asc"
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        equity_rows = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(schema.backtest_signal_events.c.backtest_id == backtest_id)
            .order_by(schema.backtest_signal_events.c.trade_date, schema.backtest_signal_events.c.id)
        ).mappings().all()
        position_counts = session.execute(
            select(
                schema.backtest_daily_positions.c.trade_date,
                func.count().label("position_snapshot_count"),
            )
            .where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
            .group_by(schema.backtest_daily_positions.c.trade_date)
            .order_by(schema.backtest_daily_positions.c.trade_date)
        ).mappings().all()
        signal_dates = sorted({row["signal_date"] for row in signal_rows if row.get("signal_date")})
        if signal_dates:
            recommendation_rows = session.execute(
                select(schema.quant_recommendations)
                .where(
                    schema.quant_recommendations.c.trade_date.in_(signal_dates),
                    schema.quant_recommendations.c.strategy_id == run["strategy_id"],
                    schema.quant_recommendations.c.strategy_version == run["strategy_version"],
                )
                .order_by(schema.quant_recommendations.c.trade_date, schema.quant_recommendations.c.rank)
            ).mappings().all()
        else:
            recommendation_rows = []

    equity_dicts = [dict(row) for row in equity_rows]
    trade_dicts = [dict(row) for row in trade_rows]
    order_dicts = [dict(row) for row in order_rows]
    signal_dicts = [dict(row) for row in signal_rows]
    recommendation_dicts = [dict(row) for row in recommendation_rows]
    position_count_dicts = [dict(row) for row in position_counts]
    items = daily_decision_rows(
        equity_dicts,
        recommendation_dicts,
        signal_dicts,
        order_dicts,
        trade_dicts,
        position_count_dicts,
    )
    items = sorted(items, key=lambda row: str(row.get("trade_date") or ""), reverse=is_desc)
    total = len(items)
    page = items[row_offset: row_offset + row_limit]
    return {
        "status": "ready" if items else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "items": [to_api(row) for row in page],
        "limit": row_limit,
        "offset": row_offset,
        "total": total,
        "returned_count": len(page),
        "has_more": row_offset + len(page) < total,
        "note": "候选按信号日落库，列表按执行日展示；严格 14:30 模型通常用上一交易日候选在下一交易日 14:30 撮合。",
    }


def backtest_trade_attribution(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    limit: int = 500,
    offset: int = 0,
    sort: str = "pnl_asc",
) -> dict[str, Any]:
    """Return portfolio-wide realized/open trade attribution."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    row_limit = min(max(limit, 1), 2000)
    row_offset = max(offset, 0)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        position_rows = session.execute(
            select(schema.backtest_daily_positions)
            .where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_positions.c.trade_date, schema.backtest_daily_positions.c.vt_symbol)
        ).mappings().all()
        trade_dicts = [dict(row) for row in trade_rows]
        position_dicts = [dict(row) for row in position_rows]
        stock_names = load_stock_names(session, symbols_from_rows(trade_dicts, position_dicts))

    named_trades = with_stock_names(trade_dicts, stock_names)
    named_positions = with_stock_names(position_dicts, stock_names)
    rows = trade_attribution(named_trades, named_positions)
    rows = _sort_attribution_rows(rows, sort)
    total = len(rows)
    page = rows[row_offset: row_offset + row_limit]
    summary = trade_attribution_summary(rows)
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "items": [to_api(row) for row in page],
        "summary": summary,
        "limit": row_limit,
        "offset": row_offset,
        "total": total,
        "returned_count": len(page),
        "has_more": row_offset + len(page) < total,
        "sort": sort,
        "note": "归因基于组合真实成交和逐日持仓快照；未平仓记录只有浮盈浮亏路径，没有已实现盈亏。",
    }


def backtest_path_diagnostics(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    vt_symbol: str | None = None,
    lookahead_days: int = 10,
    limit: int = 500,
    full_result: bool = False,
) -> dict[str, Any]:
    """Return closed trade path diagnostics for a persisted backtest."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    row_limit = min(max(limit, 1), 100_000 if full_result else 2000)
    lookahead = min(max(lookahead_days, 1), 30)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_query = select(schema.backtest_trades).where(schema.backtest_trades.c.backtest_id == backtest_id)
        position_query = select(schema.backtest_daily_positions).where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
        if vt_symbol:
            trade_query = trade_query.where(schema.backtest_trades.c.vt_symbol == vt_symbol)
            position_query = position_query.where(schema.backtest_daily_positions.c.vt_symbol == vt_symbol)
        all_trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        trade_rows = session.execute(
            trade_query.order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        position_rows = session.execute(
            position_query.order_by(schema.backtest_daily_positions.c.trade_date, schema.backtest_daily_positions.c.vt_symbol)
        ).mappings().all()
        all_trade_dicts = [dict(row) for row in all_trade_rows]
        trade_dicts = [dict(row) for row in trade_rows]
        position_dicts = [dict(row) for row in position_rows]
        future_bars = _future_daily_bars_for_trades(session, schema, trade_dicts, lookahead_days=lookahead, to_api=to_api)
        daily_bars = _daily_bars_for_trade_paths(session, schema, trade_dicts, to_api=to_api)
        stock_names = load_stock_names(session, symbols_from_rows(all_trade_dicts, trade_dicts, position_dicts, future_bars))

    named_trades = with_stock_names(trade_dicts, stock_names)
    named_all_trades = with_stock_names(all_trade_dicts, stock_names)
    named_positions = with_stock_names(position_dicts, stock_names)
    rows = trade_path_diagnostics_from_trades(
        named_trades,
        named_positions,
        future_bars,
        lookahead_days=lookahead,
        daily_bars=daily_bars,
        replacement_trades=named_all_trades,
    )
    with session_scope() as session:
        rows = market_context.annotate_rows_with_market_context(session, schema, rows, date_key="entry_date")
    rows = [_with_path_issue(row) for row in rows]
    rows.sort(key=lambda row: (_sort_number(row.get("return_pct"), default=10**18), str(row.get("entry_date") or ""), str(row.get("vt_symbol") or "")))
    page = rows[:row_limit]
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "lookahead_days": lookahead,
        "items": [to_api(row) for row in page],
        "summary": trade_path_diagnostics_summary(rows),
        "limit": row_limit,
        "total": len(rows),
        "returned_count": len(page),
        "has_more": len(page) < len(rows),
        "note": "路径诊断只用于复盘买点/卖点质量；卖出后反弹和替换交易质量都是事后归因，不参与当日交易决策。",
    }


def backtest_support_stop_matrix(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    lookahead_days: int = 10,
    sample_limit: int = 40,
) -> dict[str, Any]:
    """Return a read-only matrix that splits support-stop losses by path and replacement quality."""

    diagnostics = backtest_path_diagnostics(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=ensure_schema,
        load_stock_names=load_stock_names,
        symbols_from_rows=symbols_from_rows,
        with_stock_names=with_stock_names,
        to_api=to_api,
        backtest_id=backtest_id,
        lookahead_days=lookahead_days,
        limit=100_000,
        full_result=True,
    )
    if diagnostics.get("status") != "ready":
        return {
            **diagnostics,
            "audit_only": True,
            "not_used_for_signal_score": True,
        }

    rows = [_with_path_issue(dict(row)) for row in diagnostics.get("items") or []]
    support_rows = [row for row in rows if str(row.get("exit_reason") or "") == "support_stop"]
    summary = support_stop_matrix_summary(support_rows)
    samples = support_stop_matrix_sample_rows(support_rows, limit=sample_limit)
    return {
        "status": "ready" if support_rows else "empty",
        "backtest_id": backtest_id,
        "start_date": diagnostics.get("start_date"),
        "end_date": diagnostics.get("end_date"),
        "lookahead_days": diagnostics.get("lookahead_days"),
        "audit_only": True,
        "not_used_for_signal_score": True,
        "summary": summary,
        "items": [to_api(row) for row in samples],
        "total": len(support_rows),
        "limit": min(max(int(sample_limit or 40), 1), 200),
        "note": "支撑止损矩阵只读复用已落库成交、路径诊断和卖后替换归因；用于拆分真失败、卖早反弹、浮盈回吐和替换质量，不改变评分、买卖、卖点、仓位或排序。",
    }


def backtest_setup_market_exit_audit(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    lookahead_days: int = 10,
) -> dict[str, Any]:
    """Group closed-trade path quality by entry setup, market regime, and exit reason."""

    diagnostics = backtest_path_diagnostics(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=ensure_schema,
        load_stock_names=load_stock_names,
        symbols_from_rows=symbols_from_rows,
        with_stock_names=with_stock_names,
        to_api=to_api,
        backtest_id=backtest_id,
        lookahead_days=lookahead_days,
        limit=100_000,
        full_result=True,
    )
    if diagnostics.get("status") not in {"ready", "empty"}:
        return diagnostics
    rows = [_normalize_path_row_dates(row) for row in diagnostics.get("items") or []]
    if rows and not any(row.get("dynamic_market_regime") for row in rows):
        with session_scope() as session:
            rows = market_context.annotate_rows_with_market_context(session, schema, rows, date_key="entry_date")
    summary = setup_market_exit_audit_summary(rows)
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": diagnostics.get("start_date"),
        "end_date": diagnostics.get("end_date"),
        "lookahead_days": diagnostics.get("lookahead_days"),
        "summary": summary,
        "items": [to_api(row) for row in _worst_setup_market_exit_examples(rows)],
        "total": diagnostics.get("total"),
        "returned_count": diagnostics.get("returned_count"),
        "has_more": diagnostics.get("has_more"),
        "note": "该审计只用已落库成交和可见持仓路径做归因；大盘状态仅标记，不改变买卖、仓位或排序。",
    }


def backtest_low_suction_confirmed_path_audit(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    lookahead_days: int = 20,
) -> dict[str, Any]:
    """Audit confirmed low-suction trigger entries against alternate hold/sell paths."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    lookahead = min(max(int(lookahead_days or 20), 5), 30)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        trade_dicts = [dict(row) for row in trade_rows]
        pairs = _confirmed_low_suction_trade_pairs(trade_dicts)
        bars = _daily_bars_for_confirmed_low_suction_entries(
            session,
            schema,
            [entry for entry, _exit in pairs],
            lookahead_days=lookahead,
            to_api=to_api,
        )
        stock_names = load_stock_names(session, symbols_from_rows(trade_dicts, bars))

    named_pairs = [
        (with_stock_names([entry], stock_names)[0], with_stock_names([exit_trade], stock_names)[0] if exit_trade else None)
        for entry, exit_trade in pairs
    ]
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in bars:
        bars_by_symbol.setdefault(str(row.get("vt_symbol") or ""), []).append(row)
    rows = [
        low_suction_confirmed_path_item(
            entry,
            exit_trade,
            bars_by_symbol.get(str(entry.get("vt_symbol") or ""), []),
            lookahead_days=lookahead,
        )
        for entry, exit_trade in named_pairs
    ]
    with session_scope() as session:
        rows = market_context.annotate_rows_with_market_context(session, schema, rows, date_key="entry_date")
    rows.sort(
        key=lambda row: (
            _sort_number(row.get("low_suction_model_return_pct"), default=10**18),
            _sort_number(row.get("current_exit_return_pct"), default=10**18),
            str(row.get("entry_date") or ""),
            str(row.get("vt_symbol") or ""),
        )
    )
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "lookahead_days": lookahead,
        "audit_only": True,
        "not_used_for_signal_score": True,
        "summary": low_suction_confirmed_path_audit_summary(rows),
        "items": [to_api(row) for row in rows[:200]],
        "total": len(rows),
        "returned_count": min(len(rows), 200),
        "has_more": len(rows) > 200,
        "note": "只读审计：固定持有、失败启动退出和趋势回撤退出均为事后路径标签，不参与默认买卖、评分、排序或基线选择。",
    }


def backtest_market_phase_audit(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    to_api: ApiMapper,
    backtest_id: int,
    candidate_top_n: int = 20,
) -> dict[str, Any]:
    """Fast read-only audit for strategy results by four trading market phases."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    top_limit = min(max(int(candidate_top_n or 20), 1), 100)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        factor_rows = session.execute(
            select(schema.backtest_factor_snapshots, schema.backtest_factor_outcomes.c.payload.label("outcome_payload"))
            .outerjoin(
                schema.backtest_factor_outcomes,
                and_(
                    schema.backtest_factor_outcomes.c.backtest_id == schema.backtest_factor_snapshots.c.backtest_id,
                    schema.backtest_factor_outcomes.c.signal_date == schema.backtest_factor_snapshots.c.trade_date,
                    schema.backtest_factor_outcomes.c.vt_symbol == schema.backtest_factor_snapshots.c.vt_symbol,
                    schema.backtest_factor_outcomes.c.rank == schema.backtest_factor_snapshots.c.rank,
                ),
            )
            .where(schema.backtest_factor_snapshots.c.backtest_id == backtest_id)
            .where(schema.backtest_factor_snapshots.c.rank <= top_limit)
            .order_by(
                schema.backtest_factor_snapshots.c.trade_date,
                schema.backtest_factor_snapshots.c.rank,
                schema.backtest_factor_snapshots.c.vt_symbol,
            )
        ).mappings().all()

    closed_trades = _closed_trade_rows_by_entry_id([dict(row) for row in trade_rows])
    trade_items = _phase_audit_trade_rows(closed_trades.values())
    candidate_items = _phase_audit_candidate_rows([dict(row) for row in factor_rows])
    if _needs_market_context_annotation(trade_items):
        with session_scope() as session:
            trade_items = market_context.annotate_rows_with_market_context(session, schema, trade_items, date_key="entry_date")
    if _needs_market_context_annotation(candidate_items):
        with session_scope() as session:
            candidate_items = market_context.annotate_rows_with_market_context(session, schema, candidate_items, date_key="signal_date")
    summary = market_phase_strategy_audit_summary(trade_items, candidate_items, candidate_top_n=top_limit)
    return {
        "status": "ready" if trade_items or candidate_items else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "candidate_top_n": top_limit,
        "summary": summary,
        "items": [to_api(row) for row in trade_items[:120]],
        "candidate_items": [to_api(row) for row in candidate_items[:120]],
        "note": "行情四象限审计只复用已落库成交、候选快照和后验候选结果；不改变评分、买卖、仓位或排序。",
    }


def backtest_phase_strategy_family_matrix(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    to_api: ApiMapper,
    backtest_id: int,
    candidate_rank_limits: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Read-only phase x setup-family matrix for real trades and candidate ranks."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    rank_limits = _normalized_candidate_rank_limits(candidate_rank_limits)
    max_rank = max(rank_limits)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        factor_rows = session.execute(
            select(schema.backtest_factor_snapshots, schema.backtest_factor_outcomes.c.payload.label("outcome_payload"))
            .outerjoin(
                schema.backtest_factor_outcomes,
                and_(
                    schema.backtest_factor_outcomes.c.backtest_id == schema.backtest_factor_snapshots.c.backtest_id,
                    schema.backtest_factor_outcomes.c.signal_date == schema.backtest_factor_snapshots.c.trade_date,
                    schema.backtest_factor_outcomes.c.vt_symbol == schema.backtest_factor_snapshots.c.vt_symbol,
                    schema.backtest_factor_outcomes.c.rank == schema.backtest_factor_snapshots.c.rank,
                ),
            )
            .where(schema.backtest_factor_snapshots.c.backtest_id == backtest_id)
            .where(schema.backtest_factor_snapshots.c.rank <= max_rank)
            .order_by(
                schema.backtest_factor_snapshots.c.trade_date,
                schema.backtest_factor_snapshots.c.rank,
                schema.backtest_factor_snapshots.c.vt_symbol,
            )
        ).mappings().all()

    closed_trades = _closed_trade_rows_by_entry_id([dict(row) for row in trade_rows])
    trade_items = _phase_audit_trade_rows(closed_trades.values())
    candidate_items = _phase_audit_candidate_rows([dict(row) for row in factor_rows])
    if _needs_market_context_annotation(trade_items):
        with session_scope() as session:
            trade_items = market_context.annotate_rows_with_market_context(session, schema, trade_items, date_key="entry_date")
    if _needs_market_context_annotation(candidate_items):
        with session_scope() as session:
            candidate_items = market_context.annotate_rows_with_market_context(session, schema, candidate_items, date_key="signal_date")
    summary = phase_strategy_family_matrix_summary(
        trade_items,
        candidate_items,
        candidate_rank_limits=rank_limits,
    )
    return {
        "status": "ready" if trade_items or candidate_items else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "candidate_rank_limits": rank_limits,
        "summary": summary,
        "items": [to_api(row) for row in summary.get("real_trade_matrix", [])],
        "candidate_items": [to_api(row) for row in summary.get("candidate_rank_matrices", [])],
        "note": "策略族×行情阶段矩阵只读复用已落库成交、候选快照和候选后验；不改变评分、买卖、卖点、仓位或排序。",
    }


def backtest_replacement_quality_matrix(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    sample_limit: int = 80,
) -> dict[str, Any]:
    """Read-only matrix for sell/freed-slot replacement quality."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    limit = min(max(int(sample_limit or 80), 1), 500)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        trade_dicts = [dict(row) for row in trade_rows]
        order_dicts = [dict(row) for row in order_rows]
        stock_names = load_stock_names(session, symbols_from_rows(trade_dicts, order_dicts))

    named_trades = with_stock_names(trade_dicts, stock_names)
    named_orders = with_stock_names(order_dicts, stock_names)
    closed_trades = list(_closed_trade_rows_by_entry_id(named_trades).values())
    filled_rows = _phase_audit_trade_rows(closed_trades)
    reject_rows = _replacement_quality_reject_rows(named_orders)
    if filled_rows and not any(row.get("dynamic_market_regime") for row in filled_rows):
        with session_scope() as session:
            filled_rows = market_context.annotate_rows_with_market_context(session, schema, filled_rows, date_key="entry_date")
    if reject_rows and not any(row.get("dynamic_market_regime") for row in reject_rows):
        with session_scope() as session:
            reject_rows = market_context.annotate_rows_with_market_context(session, schema, reject_rows, date_key="trade_date")
    filled_rows = [_with_replacement_matrix_trade_fields(row) for row in filled_rows]
    reject_rows = [_with_replacement_matrix_reject_fields(row) for row in reject_rows]
    worst_filled = sorted(
        filled_rows,
        key=lambda row: (
            _sort_number(row.get("return_pct"), default=10**18),
            str(row.get("entry_date") or ""),
            str(row.get("vt_symbol") or ""),
        ),
    )[:limit]
    rejected_samples = sorted(
        reject_rows,
        key=lambda row: (
            -int(row.get("reject_reason_count") or 0),
            str(row.get("trade_date") or ""),
            str(row.get("vt_symbol") or ""),
        ),
    )[:limit]
    return {
        "status": "ready" if filled_rows or reject_rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "audit_only": True,
        "not_used_for_signal_score": True,
        "summary": replacement_quality_matrix_summary(filled_rows, reject_rows),
        "items": [to_api(row) for row in worst_filled],
        "rejected_items": [to_api(row) for row in rejected_samples],
        "total": {
            "filled_trade_count": len(filled_rows),
            "gate_reject_count": len(reject_rows),
        },
        "limit": limit,
        "note": "替换质量矩阵只读复用已落库成交和拒单 raw；用于分析卖后接力质量，不改变评分、买卖、卖点、仓位或排序。",
    }


def backtest_execution_breakpoint_matrix(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    candidate_rank_limit: int = 100,
    sample_limit: int = 120,
) -> dict[str, Any]:
    """Read-only candidate -> plan -> order -> trade breakpoint matrix."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    rank_limit = min(max(int(candidate_rank_limit or 100), 1), 200)
    limit = min(max(int(sample_limit or 120), 1), 500)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        run_dict = dict(run)
        run_params = _run_params(run_dict)
        recommendation_rows = session.execute(
            select(schema.quant_recommendations)
            .where(
                and_(
                    schema.quant_recommendations.c.trade_date >= run["start_date"],
                    schema.quant_recommendations.c.trade_date <= run["end_date"],
                    schema.quant_recommendations.c.strategy_id == run["strategy_id"],
                    schema.quant_recommendations.c.strategy_version == run["strategy_version"],
                    schema.quant_recommendations.c.rank <= rank_limit,
                )
            )
            .order_by(
                schema.quant_recommendations.c.trade_date,
                schema.quant_recommendations.c.rank,
                schema.quant_recommendations.c.vt_symbol,
            )
        ).mappings().all()
        signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(schema.backtest_signal_events.c.backtest_id == backtest_id)
            .order_by(
                schema.backtest_signal_events.c.signal_date,
                schema.backtest_signal_events.c.trade_date,
                desc(schema.backtest_signal_events.c.score),
                schema.backtest_signal_events.c.id,
            )
        ).mappings().all()
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        equity_rows = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
        position_rows = session.execute(
            select(schema.backtest_daily_positions)
            .where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_positions.c.trade_date, schema.backtest_daily_positions.c.vt_symbol)
        ).mappings().all()
        recommendation_dicts = [_recommendation_read_view(dict(row)) for row in recommendation_rows]
        signal_dicts = [dict(row) for row in signal_rows]
        order_dicts = [dict(row) for row in order_rows]
        trade_dicts = [dict(row) for row in trade_rows]
        equity_dicts = [dict(row) for row in equity_rows]
        position_dicts = [dict(row) for row in position_rows]
        stock_names = load_stock_names(
            session,
            symbols_from_rows(recommendation_dicts, signal_dicts, order_dicts, trade_dicts, position_dicts),
        )

    rows = execution_breakpoint_rows(
        recommendations=with_stock_names(recommendation_dicts, stock_names),
        signal_events=with_stock_names(signal_dicts, stock_names),
        orders=with_stock_names(order_dicts, stock_names),
        trades=with_stock_names(trade_dicts, stock_names),
        equities=equity_dicts,
        positions=position_dicts,
        run_params=run_params,
        candidate_rank_limit=rank_limit,
    )
    rows.sort(
        key=lambda row: (
            _execution_breakpoint_status_order(row.get("status")),
            str(row.get("signal_date") or ""),
            _safe_int(row.get("rank"), 10**9),
            str(row.get("vt_symbol") or ""),
        )
    )
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run_dict["start_date"].isoformat(),
        "end_date": run_dict["end_date"].isoformat(),
        "candidate_rank_limit": rank_limit,
        "audit_only": True,
        "not_used_for_signal_score": True,
        "summary": execution_breakpoint_matrix_summary(rows),
        "items": [to_api(row) for row in rows[:limit]],
        "total": len(rows),
        "returned_count": min(len(rows), limit),
        "has_more": len(rows) > limit,
        "limit": limit,
        "note": "执行断点矩阵只读复用候选、理论信号、订单、成交和持仓快照；用于解释有信号为什么没买，不改变评分、买卖、仓位、卖点或产品基线。",
    }


def backtest_rotation_opportunity_cost_matrix(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    candidate_rank_limit: int = 20,
    sample_limit: int = 120,
    holding_days: int = 20,
) -> dict[str, Any]:
    """Read-only opportunity-cost matrix for full-position missed candidates."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    rank_limit = min(max(int(candidate_rank_limit or 20), 1), 200)
    limit = min(max(int(sample_limit or 120), 1), 500)
    hold_days = min(max(int(holding_days or 20), 1), 60)
    run_dict, rows = _rotation_opportunity_cost_audit_rows(
        schema=schema,
        session_scope=session_scope,
        load_stock_names=load_stock_names,
        symbols_from_rows=symbols_from_rows,
        with_stock_names=with_stock_names,
        backtest_id=backtest_id,
        candidate_rank_limit=rank_limit,
        holding_days=hold_days,
    )
    if run_dict is None:
        return {"status": "not_found", "backtest_id": backtest_id, "items": []}
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run_dict["start_date"].isoformat(),
        "end_date": run_dict["end_date"].isoformat(),
        "candidate_rank_limit": rank_limit,
        "holding_days": hold_days,
        "audit_only": True,
        "not_used_for_signal_score": True,
        "summary": rotation_opportunity_cost_matrix_summary(rows),
        "items": [to_api(row) for row in rows[:limit]],
        "total": len(rows),
        "returned_count": min(len(rows), limit),
        "has_more": len(rows) > limit,
        "limit": limit,
        "note": "换仓机会成本矩阵只读复用候选、执行断点、真实持仓和固定持有后验；用于研究满仓时是否值得替换弱持仓，不改变评分、买卖、仓位、卖点或产品基线。",
    }


def backtest_trend_winner_protection_matrix(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    candidate_rank_limit: int = 20,
    sample_limit: int = 120,
    holding_days: int = 20,
) -> dict[str, Any]:
    """Read-only matrix for holdings that should not be rotated away."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    rank_limit = min(max(int(candidate_rank_limit or 20), 1), 200)
    hold_days = min(max(int(holding_days or 20), 1), 60)
    run_dict, rotation_rows = _rotation_opportunity_cost_audit_rows(
        schema=schema,
        session_scope=session_scope,
        load_stock_names=load_stock_names,
        symbols_from_rows=symbols_from_rows,
        with_stock_names=with_stock_names,
        backtest_id=backtest_id,
        candidate_rank_limit=rank_limit,
        holding_days=hold_days,
    )
    if run_dict is None:
        return {"status": "not_found", "backtest_id": backtest_id, "items": []}
    rows = trend_winner_protection_rows(rotation_rows=rotation_rows)
    rows.sort(
        key=lambda row: (
            0 if row.get("protected") else 1,
            -(_safe_float(row.get("held_execute_open_return_pct")) or -10**9),
            -(_safe_float(row.get("held_real_return_pct")) or -10**9),
            str(row.get("execute_date") or ""),
            str(row.get("held_symbol") or ""),
        )
    )
    limit = min(max(int(sample_limit or 120), 1), 500)
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "start_date": run_dict["start_date"].isoformat(),
        "end_date": run_dict["end_date"].isoformat(),
        "candidate_rank_limit": rank_limit,
        "holding_days": hold_days,
        "audit_only": True,
        "not_used_for_signal_score": True,
        "summary": trend_winner_protection_matrix_summary(rows),
        "items": [to_api(row) for row in rows[:limit]],
        "total": len(rows),
        "returned_count": min(len(rows), limit),
        "has_more": len(rows) > limit,
        "limit": limit,
        "note": "趋势赢家保护矩阵只读复用满仓换仓机会矩阵；用于识别 D+1 开盘已盈利或后续证明为趋势赢家的持仓，避免把后验机会误写成粗放换仓规则。",
    }


def _rotation_opportunity_cost_audit_rows(
    *,
    schema: Any,
    session_scope: Any,
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    backtest_id: int,
    candidate_rank_limit: int = 20,
    holding_days: int = 20,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    rank_limit = min(max(int(candidate_rank_limit or 20), 1), 200)
    hold_days = min(max(int(holding_days or 20), 1), 60)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return None, []
        run_dict = dict(run)
        run_params = _run_params(run_dict)
        recommendation_rows = session.execute(
            select(schema.quant_recommendations)
            .where(
                and_(
                    schema.quant_recommendations.c.trade_date >= run["start_date"],
                    schema.quant_recommendations.c.trade_date <= run["end_date"],
                    schema.quant_recommendations.c.strategy_id == run["strategy_id"],
                    schema.quant_recommendations.c.strategy_version == run["strategy_version"],
                    schema.quant_recommendations.c.rank <= rank_limit,
                )
            )
            .order_by(
                schema.quant_recommendations.c.trade_date,
                schema.quant_recommendations.c.rank,
                schema.quant_recommendations.c.vt_symbol,
            )
        ).mappings().all()
        signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(schema.backtest_signal_events.c.backtest_id == backtest_id)
            .order_by(
                schema.backtest_signal_events.c.signal_date,
                schema.backtest_signal_events.c.trade_date,
                desc(schema.backtest_signal_events.c.score),
                schema.backtest_signal_events.c.id,
            )
        ).mappings().all()
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        equity_rows = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
        position_rows = session.execute(
            select(schema.backtest_daily_positions)
            .where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_positions.c.trade_date, schema.backtest_daily_positions.c.vt_symbol)
        ).mappings().all()
        recommendation_dicts = [_recommendation_read_view(dict(row)) for row in recommendation_rows]
        signal_dicts = [dict(row) for row in signal_rows]
        order_dicts = [dict(row) for row in order_rows]
        trade_dicts = [dict(row) for row in trade_rows]
        equity_dicts = [dict(row) for row in equity_rows]
        position_dicts = [dict(row) for row in position_rows]
        stock_names = load_stock_names(
            session,
            symbols_from_rows(recommendation_dicts, signal_dicts, order_dicts, trade_dicts, position_dicts),
        )
        named_recommendations = with_stock_names(recommendation_dicts, stock_names)
        named_signals = with_stock_names(signal_dicts, stock_names)
        named_orders = with_stock_names(order_dicts, stock_names)
        named_trades = with_stock_names(trade_dicts, stock_names)
        named_positions = with_stock_names(position_dicts, stock_names)
        breakpoint_rows = execution_breakpoint_rows(
            recommendations=named_recommendations,
            signal_events=named_signals,
            orders=named_orders,
            trades=named_trades,
            equities=equity_dicts,
            positions=named_positions,
            run_params=run_params,
            candidate_rank_limit=rank_limit,
        )
        candidate_recommendations = [
            row for row in named_recommendations if str(row.get("action") or "").upper() == "BUY"
        ]
        candidate_observations = _candidate_observation_returns(
            session,
            schema,
            candidate_recommendations,
            holding_days=hold_days,
        )
        position_exit_returns = _position_exit_returns_by_entry(named_trades)
    rows = rotation_opportunity_cost_rows(
        breakpoint_rows=breakpoint_rows,
        positions=named_positions,
        candidate_observations=candidate_observations,
        position_exit_returns=position_exit_returns,
        candidate_rank_limit=rank_limit,
        holding_days=hold_days,
    )
    if rows:
        with session_scope() as session:
            _attach_replaced_execute_open_returns(session, schema, rows)
    if rows and not any(row.get("dynamic_market_regime") for row in rows):
        with session_scope() as session:
            rows = market_context.annotate_rows_with_market_context(session, schema, rows, date_key="signal_date")
            rows = [_rotation_opportunity_enrich_row(row) for row in rows]
    rows.sort(
        key=lambda row: (
            -(_safe_float(row.get("opportunity_delta_pct")) or -10**9),
            str(row.get("signal_date") or ""),
            _safe_int(row.get("rank"), 10**9),
            str(row.get("vt_symbol") or ""),
        )
    )
    return run_dict, rows


def rotation_opportunity_cost_rows(
    *,
    breakpoint_rows: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    candidate_observations: dict[tuple[str, date | None], dict[str, Any]],
    position_exit_returns: dict[tuple[str, date | None], dict[str, Any]],
    candidate_rank_limit: int = 20,
    holding_days: int = 20,
) -> list[dict[str, Any]]:
    """Build audit rows for full-position missed candidates and weakest held position."""

    rank_limit = min(max(int(candidate_rank_limit or 20), 1), 200)
    positions_by_date: dict[date, list[dict[str, Any]]] = {}
    for position in positions:
        trade_date = _as_date(position.get("trade_date"))
        if trade_date is None:
            continue
        positions_by_date.setdefault(trade_date, []).append(position)
    position_dates = sorted(positions_by_date)
    rows: list[dict[str, Any]] = []
    for candidate in breakpoint_rows:
        if candidate.get("status") not in {"planned_not_ordered_full", "candidate_top_rank_full"}:
            continue
        if str(candidate.get("action") or "").upper() != "BUY":
            continue
        rank = _safe_int_or_none(candidate.get("rank"))
        if rank is None or rank > rank_limit:
            continue
        signal_date = _as_date(candidate.get("signal_date"))
        execute_date = _rotation_candidate_execute_date(candidate, signal_date, position_dates)
        symbol = str(candidate.get("vt_symbol") or "")
        if signal_date is None or execute_date is None or not symbol:
            continue
        held_positions = positions_by_date.get(execute_date) or []
        replacement = _weakest_rotation_position(held_positions)
        observation = candidate_observations.get((symbol, signal_date)) or {}
        candidate_return = _safe_float(observation.get("return_pct"))
        held_exit = position_exit_returns.get(
            (str((replacement or {}).get("vt_symbol") or ""), _as_date((replacement or {}).get("entry_date")))
        )
        held_return = _safe_float((held_exit or {}).get("return_pct"))
        held_current = _safe_float((replacement or {}).get("floating_pnl_pct"))
        opportunity_delta = candidate_return - held_return if candidate_return is not None and held_return is not None else None
        rows.append(
            _rotation_opportunity_enrich_row(
                {
                    **_candidate_context_fields(candidate),
                    "signal_date": signal_date,
                    "execute_date": execute_date,
                    "vt_symbol": symbol,
                    "name": candidate.get("name"),
                    "rank": rank,
                    "score": candidate.get("total_score"),
                    "status": candidate.get("status"),
                    "status_label": candidate.get("status_label"),
                    "setup_family": candidate.get("setup_family"),
                    "entry_family": candidate.get("setup_family"),
                    "entry_setup": candidate.get("entry_setup"),
                    "candidate_observation_days": holding_days,
                    "candidate_observation_status": observation.get("status"),
                    "candidate_entry_date": observation.get("entry_date"),
                    "candidate_exit_date": observation.get("exit_date"),
                    "candidate_return_pct": candidate_return,
                    "candidate_entry_price": observation.get("entry_price"),
                    "candidate_exit_price": observation.get("exit_price"),
                    "replaced_symbol": (replacement or {}).get("vt_symbol"),
                    "replaced_name": (replacement or {}).get("name"),
                    "replaced_entry_date": _as_date((replacement or {}).get("entry_date")),
                    "replaced_cost_price": (replacement or {}).get("cost_price"),
                    "replaced_snapshot_close_price": (replacement or {}).get("close_price"),
                    "replaced_holding_days": (replacement or {}).get("holding_days"),
                    "replaced_snapshot_return_pct": held_current,
                    "replaced_current_return_pct": held_current,
                    "replaced_exit_date": (held_exit or {}).get("exit_date"),
                    "replaced_real_return_pct": held_return,
                    "replaced_exit_reason": (held_exit or {}).get("exit_reason"),
                    "opportunity_delta_pct": opportunity_delta,
                    "opportunity_bucket": _rotation_opportunity_bucket(opportunity_delta),
                    "sample_summary": _rotation_opportunity_summary_text(
                        candidate_return=candidate_return,
                        held_return=held_return,
                        held_current=held_current,
                        replacement=replacement,
                    ),
                }
            )
        )
    return rows


def _rotation_candidate_execute_date(
    candidate: dict[str, Any],
    signal_date: date | None,
    position_dates: list[date],
) -> date | None:
    execute_date = _as_date(candidate.get("execute_date"))
    if execute_date is not None:
        return execute_date
    if signal_date is None:
        return None
    for item in position_dates:
        if item > signal_date:
            return item
    return signal_date


def execution_breakpoint_rows(
    *,
    recommendations: list[dict[str, Any]],
    signal_events: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    equities: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    run_params: dict[str, Any],
    candidate_rank_limit: int = 100,
) -> list[dict[str, Any]]:
    buy_signals = [row for row in signal_events if str(row.get("side") or "").upper() == "BUY"]
    buy_orders = [row for row in orders if str(row.get("side") or "").upper() == "BUY"]
    buy_trades = [row for row in trades if str(row.get("side") or "").upper() == "BUY"]
    signals_by_key = _rows_by_signal_key(buy_signals, prefer_signal_date=True)
    orders_by_key = _rows_by_signal_key(buy_orders)
    trades_by_key = _rows_by_signal_key(buy_trades)
    all_signals_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in signal_events:
        all_signals_by_symbol.setdefault(str(row.get("vt_symbol") or ""), []).append(row)
    positions_by_key = {
        (_as_date(row.get("trade_date")), str(row.get("vt_symbol") or "")): row
        for row in positions
        if _as_date(row.get("trade_date")) and row.get("vt_symbol")
    }
    equity_by_date = {_as_date(row.get("trade_date")): row for row in equities if _as_date(row.get("trade_date"))}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[date, str]] = set()
    for recommendation in recommendations:
        signal_date = _as_date(recommendation.get("trade_date"))
        symbol = str(recommendation.get("vt_symbol") or "")
        if signal_date is None or not symbol:
            continue
        key = (signal_date, symbol)
        seen.add(key)
        rows.append(
            _execution_breakpoint_row(
                signal_date=signal_date,
                symbol=symbol,
                recommendation=recommendation,
                signal_row=_first_row(signals_by_key.get(key)),
                order_row=_first_row(orders_by_key.get(key)),
                trade_row=_first_row(trades_by_key.get(key)),
                signals_by_symbol=all_signals_by_symbol,
                positions_by_key=positions_by_key,
                equity_by_date=equity_by_date,
                run_params=run_params,
                source="quant_recommendations",
            )
        )
    for key, signal_group in signals_by_key.items():
        if key in seen:
            continue
        signal_row = _first_row(signal_group)
        if signal_row is None:
            continue
        if not _signal_event_in_rank_limit(signal_row, candidate_rank_limit):
            continue
        signal_date, symbol = key
        rows.append(
            _execution_breakpoint_row(
                signal_date=signal_date,
                symbol=symbol,
                recommendation=None,
                signal_row=signal_row,
                order_row=_first_row(orders_by_key.get(key)),
                trade_row=_first_row(trades_by_key.get(key)),
                signals_by_symbol=all_signals_by_symbol,
                positions_by_key=positions_by_key,
                equity_by_date=equity_by_date,
                run_params=run_params,
                source="backtest_signal_events",
            )
        )
    return rows


def _execution_breakpoint_row(
    *,
    signal_date: date,
    symbol: str,
    recommendation: dict[str, Any] | None,
    signal_row: dict[str, Any] | None,
    order_row: dict[str, Any] | None,
    trade_row: dict[str, Any] | None,
    signals_by_symbol: dict[str, list[dict[str, Any]]],
    positions_by_key: dict[tuple[date | None, str], dict[str, Any]],
    equity_by_date: dict[date | None, dict[str, Any]],
    run_params: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    action = _execution_breakpoint_action(recommendation, signal_row, order_row, trade_row)
    execute_date = _as_date((signal_row or {}).get("execute_date") or (order_row or {}).get("trade_date") or (trade_row or {}).get("trade_date"))
    equity_row = equity_by_date.get(execute_date) or equity_by_date.get(signal_date) or {}
    theoretical = _theoretical_position_context(symbol, signals_by_symbol.get(symbol) or [], signal_date)
    real_position = positions_by_key.get((signal_date, symbol))
    execution = _signal_execution_context(signal_row)
    rank = (recommendation or {}).get("rank") or execution.get("execution_candidate_rank") or execution.get("raw_signal_rank")
    status = _execution_breakpoint_status(
        action=action,
        signal_row=signal_row,
        order_row=order_row,
        trade_row=trade_row,
        execution=execution,
        equity_row=equity_row,
        theoretical_position_context=theoretical,
        real_position=real_position,
        run_params=run_params,
        candidate_rank=rank,
        has_recommendation=recommendation is not None,
    )
    setup = (
        _signal_setup_type(signal_row)
        or _recommendation_setup_type(recommendation)
        or _trade_setup_type(trade_row)
    )
    context_fields: dict[str, Any] = {}
    for source_row in (recommendation, signal_row, trade_row):
        if source_row:
            context_fields.update(_candidate_context_fields(source_row))
    context_fields["entry_setup"] = setup
    return {
        "signal_date": signal_date,
        "execute_date": execute_date,
        "vt_symbol": symbol,
        "name": (recommendation or signal_row or trade_row or {}).get("name"),
        "source": source,
        "action": action or None,
        "rank": rank,
        "total_score": (recommendation or {}).get("total_score") or (signal_row or {}).get("score"),
        **context_fields,
        "setup_family": _market_phase_setup_family(context_fields),
        "entry_setup": setup,
        "status": status,
        "status_label": _execution_breakpoint_status_label(status),
        "status_group": _execution_breakpoint_status_group(status),
        "has_recommendation": recommendation is not None,
        "has_signal_plan": signal_row is not None,
        "has_order": order_row is not None,
        "has_trade": trade_row is not None,
        "order_status": (order_row or {}).get("status"),
        "order_reason": (order_row or {}).get("reason"),
        "execution_candidate_rank": execution.get("execution_candidate_rank"),
        "execution_candidate_selected": execution.get("execution_candidate_selected"),
        "raw_signal_rank": execution.get("raw_signal_rank"),
        "execution_lane": execution.get("execution_lane"),
        "position_count": equity_row.get("position_count"),
        "max_positions": _safe_int(run_params.get("max_positions"), 10),
        "candidate_limit": _safe_int(run_params.get("candidate_limit"), 20),
        "theoretical_held_on_signal_date": bool(theoretical.get("held")),
        "theoretical_entry_date": theoretical.get("entry_date"),
        "theoretical_marker_gap": bool(theoretical.get("held")) and real_position is None,
        "real_held_on_signal_date": real_position is not None,
        "real_entry_date": _as_iso((real_position or {}).get("entry_date")),
        "summary": _execution_breakpoint_summary(status, setup, execution, equity_row, run_params, theoretical, real_position),
    }


def _execution_breakpoint_status(
    *,
    action: str,
    signal_row: dict[str, Any] | None,
    order_row: dict[str, Any] | None,
    trade_row: dict[str, Any] | None,
    execution: dict[str, Any],
    equity_row: dict[str, Any],
    theoretical_position_context: dict[str, Any],
    real_position: dict[str, Any] | None,
    run_params: dict[str, Any],
    candidate_rank: Any = None,
    has_recommendation: bool = False,
) -> str:
    if trade_row is not None:
        return "filled"
    if order_row is not None and str(order_row.get("status") or "").lower() == "rejected":
        return "rejected"
    if action == "WATCH":
        return "watch_not_bought"
    if signal_row is not None:
        raw = signal_row.get("raw") if isinstance(signal_row.get("raw"), dict) else {}
        plan_status = str(signal_row.get("plan_status") or raw.get("status") or "").lower()
        if plan_status == "not_triggered":
            return "not_triggered"
        if plan_status == "rejected":
            return "plan_rejected"
        selected = execution.get("execution_candidate_selected")
        rank = _safe_int_or_none(execution.get("execution_candidate_rank"))
        if selected is False or rank is None:
            return "planned_not_ordered_limit"
        max_positions = _safe_int(run_params.get("max_positions"), 10)
        position_count = _safe_int(equity_row.get("position_count"), 0)
        if position_count >= max_positions:
            return "planned_not_ordered_full"
        return "planned_not_ordered_other"
    if action == "BUY" and has_recommendation:
        rank = _safe_int_or_none(candidate_rank)
        candidate_limit = _safe_int(run_params.get("candidate_limit"), 20)
        max_positions = _safe_int(run_params.get("max_positions"), 10)
        position_count = _safe_int(equity_row.get("position_count"), 0)
        if rank is not None and rank > candidate_limit:
            return "candidate_rank_outside_execution_pool"
        if real_position is not None:
            return "candidate_real_already_held"
        if position_count >= max_positions:
            return "candidate_top_rank_full"
        return "candidate_top_rank_no_order"
    if theoretical_position_context.get("held") and real_position is None:
        return "theoretical_held_real_not_held"
    if theoretical_position_context.get("held") and real_position is not None:
        return "theoretical_held_real_held"
    return "candidate_not_planned"


def _execution_breakpoint_action(
    recommendation: dict[str, Any] | None,
    signal_row: dict[str, Any] | None,
    order_row: dict[str, Any] | None,
    trade_row: dict[str, Any] | None,
) -> str:
    action = str((recommendation or {}).get("action") or "").upper()
    if action:
        return action
    for row in (signal_row, order_row, trade_row):
        side = str((row or {}).get("side") or "").upper()
        if side in {"BUY", "SELL"}:
            return side
    return "BUY" if signal_row is not None else ""


def execution_breakpoint_matrix_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "method": "只读矩阵：按信号日候选、理论计划、订单、成交和持仓快照归类执行断点。",
        "not_used_for_signal_score": True,
        "audit_only": True,
        "overall": _execution_breakpoint_metric_summary(rows),
        "by_status": _execution_breakpoint_group_metrics(rows, "status", _execution_breakpoint_status_label),
        "by_status_group": _execution_breakpoint_group_metrics(rows, "status_group", _execution_breakpoint_status_group_label),
        "by_setup_family": _execution_breakpoint_group_metrics(rows, "setup_family", _setup_family_label_for_bucket),
        "by_action": _execution_breakpoint_group_metrics(rows, "action", lambda value, _rows: str(value or "未知")),
        "theoretical_real_gap_count": sum(1 for row in rows if row.get("theoretical_marker_gap")),
        "marker_state_gap_count": sum(1 for row in rows if row.get("theoretical_marker_gap")),
        "full_position_miss_count": sum(
            1 for row in rows if row.get("status") in {"planned_not_ordered_full", "candidate_top_rank_full"}
        ),
        "execution_pool_miss_count": sum(
            1 for row in rows if row.get("status") in {"planned_not_ordered_limit", "candidate_rank_outside_execution_pool"}
        ),
        "interpretation": _execution_breakpoint_interpretation(rows),
    }


def _execution_breakpoint_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buy_rows = [row for row in rows if str(row.get("action") or "").upper() == "BUY"]
    filled = [row for row in rows if row.get("status") == "filled"]
    return {
        "candidate_count": len(rows),
        "buy_candidate_count": len(buy_rows),
        "filled_count": len(filled),
        "filled_rate": _ratio(len(filled), len(buy_rows)),
        "not_bought_count": len(rows) - len(filled),
        "avg_score": _avg(row.get("total_score") for row in rows),
        "avg_rank": _avg(row.get("rank") for row in rows),
    }


def _execution_breakpoint_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str] | Callable[[Any], str],
) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key) or "unknown", []).append(row)
    result = []
    for value, group_rows in grouped.items():
        try:
            label = labeler(value, group_rows)  # type: ignore[misc]
        except TypeError:
            label = labeler(value)  # type: ignore[operator]
        result.append({"key": value, "label": label, **_execution_breakpoint_metric_summary(group_rows)})
    result.sort(key=lambda row: (-int(row.get("candidate_count") or 0), str(row.get("key") or "")))
    return result


def _execution_breakpoint_interpretation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    full = [row for row in rows if row.get("status") in {"planned_not_ordered_full", "candidate_top_rank_full"}]
    theoretical_gap = [row for row in rows if row.get("theoretical_marker_gap")]
    limit_rows = [row for row in rows if row.get("status") in {"planned_not_ordered_limit", "candidate_rank_outside_execution_pool"}]
    no_order = [row for row in rows if row.get("status") == "candidate_top_rank_no_order"]
    return {
        "primary_issue": (
            "full_position_without_rotation"
            if full
            else "execution_limit"
            if limit_rows
            else "top_candidate_no_order"
            if no_order
            else "signal_marker_state_gap"
            if theoretical_gap
            else "none"
        ),
        "message": _execution_breakpoint_interpretation_message(full, theoretical_gap, limit_rows, no_order),
    }


def _execution_breakpoint_interpretation_message(
    full: list[dict[str, Any]],
    theoretical_gap: list[dict[str, Any]],
    limit_rows: list[dict[str, Any]],
    no_order: list[dict[str, Any]],
) -> str:
    if full:
        return "存在进入执行池但满仓未换仓的候选；应审计高质量候选是否能替换弱持仓。"
    if limit_rows:
        return "主要断点是候选未进入执行池前列；应先看评分和策略族排序质量。"
    if no_order:
        return "存在候选排名靠前但没有订单的样本；应核查执行计划、挂单和组合约束。"
    if theoretical_gap:
        return "存在理论信号标记账本与真实持仓不一致；该项主要用于解释股票详情/信号标记差异，不直接证明真实交易被压制。"
    return "未发现明显候选到真实成交断点。"


def rotation_opportunity_cost_matrix_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize full-position missed candidate opportunity costs."""

    return {
        "method": "只读矩阵：只分析满仓挡住的前列 BUY 候选，对比候选固定持有后验和同日最弱持仓真实退出收益。",
        "not_used_for_signal_score": True,
        "audit_only": True,
        "overall": _rotation_opportunity_metric_summary(rows),
        "by_opportunity_bucket": _rotation_opportunity_group_metrics(
            rows,
            "opportunity_bucket",
            _rotation_opportunity_bucket_label,
        ),
        "by_phase": _rotation_opportunity_group_metrics(rows, "market_phase", _market_phase_label_for_bucket),
        "by_setup_family": _rotation_opportunity_group_metrics(rows, "setup_family", _setup_family_label_for_bucket),
        "by_phase_setup": _rotation_opportunity_phase_setup_matrix(rows),
        "by_candidate_rank": _rotation_opportunity_derived_group_metrics(
            rows,
            "candidate_rank_bucket",
            _rotation_candidate_rank_bucket,
            _rotation_candidate_rank_label,
        ),
        "by_market_warning": _rotation_opportunity_group_metrics(
            rows,
            "market_warning_level",
            _market_warning_level_label_for_bucket,
        ),
        "by_low_suction_days": _rotation_opportunity_derived_group_metrics(
            rows,
            "low_suction_days_bucket",
            _low_suction_days_bucket,
            _rotation_low_suction_days_label,
        ),
        "by_launch_quality": _rotation_opportunity_group_metrics(
            rows,
            "low_suction_launch_quality_bucket",
            _low_suction_launch_quality_label_for_bucket,
        ),
        "by_ma_convergence": _rotation_opportunity_derived_group_metrics(
            rows,
            "ma_convergence_bucket",
            _ma_convergence_bucket,
            _rotation_ma_convergence_label,
        ),
        "by_replaced_current_return": _rotation_opportunity_derived_group_metrics(
            rows,
            "replaced_current_return_bucket",
            _rotation_replaced_current_return_bucket,
            _rotation_replaced_current_return_label,
        ),
        "by_replaced_execute_open_return": _rotation_opportunity_derived_group_metrics(
            rows,
            "replaced_execute_open_return_bucket",
            _rotation_replaced_execute_open_return_bucket,
            _rotation_replaced_execute_open_return_label,
        ),
        "by_replaced_holding_days": _rotation_opportunity_derived_group_metrics(
            rows,
            "replaced_holding_days_bucket",
            _rotation_replaced_holding_days_bucket,
            _rotation_replaced_holding_days_label,
        ),
        "interpretation": _rotation_opportunity_interpretation(rows),
    }


def _rotation_opportunity_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_returns = [
        value for row in rows if (value := _safe_float(row.get("candidate_return_pct"))) is not None
    ]
    held_returns = [
        value for row in rows if (value := _safe_float(row.get("replaced_real_return_pct"))) is not None
    ]
    deltas = [value for row in rows if (value := _safe_float(row.get("opportunity_delta_pct"))) is not None]
    execute_open_returns = [
        value for row in rows if (value := _safe_float(row.get("replaced_execute_open_return_pct"))) is not None
    ]
    positive = [value for value in deltas if value > 0]
    strong_positive = [value for value in deltas if value >= 10]
    harmful = [value for value in deltas if value <= -5]
    execute_open_weak = [value for value in execute_open_returns if value <= -5]
    execute_open_profitable = [value for value in execute_open_returns if value >= 0]
    return {
        "candidate_count": len(rows),
        "evaluated_count": len(deltas),
        "positive_count": len(positive),
        "positive_rate": _pct_ratio(len(positive), len(deltas)),
        "strong_positive_count": len(strong_positive),
        "strong_positive_rate": _pct_ratio(len(strong_positive), len(deltas)),
        "harmful_count": len(harmful),
        "harmful_rate": _pct_ratio(len(harmful), len(deltas)),
        "avg_candidate_return_pct": _avg(candidate_returns),
        "avg_replaced_real_return_pct": _avg(held_returns),
        "avg_opportunity_delta_pct": _avg(deltas),
        "median_opportunity_delta_pct": median(deltas) if deltas else None,
        "best_opportunity_delta_pct": max(deltas) if deltas else None,
        "worst_opportunity_delta_pct": min(deltas) if deltas else None,
        "execute_open_evaluated_count": len(execute_open_returns),
        "execute_open_weak_count": len(execute_open_weak),
        "execute_open_weak_rate": _pct_ratio(len(execute_open_weak), len(execute_open_returns)),
        "execute_open_profitable_count": len(execute_open_profitable),
        "execute_open_profitable_rate": _pct_ratio(len(execute_open_profitable), len(execute_open_returns)),
    }


def _rotation_opportunity_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str] | Callable[[Any], str],
) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key) or "unknown", []).append(row)
    result = []
    for value, group_rows in grouped.items():
        try:
            label = labeler(value, group_rows)  # type: ignore[misc]
        except TypeError:
            label = labeler(value)  # type: ignore[operator]
        result.append({key: None if value == "unknown" else value, "label": label, **_rotation_opportunity_metric_summary(group_rows)})
    result.sort(
        key=lambda row: (
            -int(row.get("evaluated_count") or 0),
            -float(row.get("avg_opportunity_delta_pct") or -10**9),
            str(row.get(key) or ""),
        )
    )
    return result


def _rotation_opportunity_derived_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    bucket_func: Callable[[dict[str, Any]], str],
    labeler: Callable[[Any, list[dict[str, Any]]], str] | Callable[[Any], str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(bucket_func(row) or "unknown", []).append(row)
    result = []
    for value, group_rows in grouped.items():
        try:
            label = labeler(value, group_rows)  # type: ignore[misc]
        except TypeError:
            label = labeler(value)  # type: ignore[operator]
        result.append({key: None if value == "unknown" else value, "label": label, **_rotation_opportunity_metric_summary(group_rows)})
    result.sort(
        key=lambda row: (
            -int(row.get("evaluated_count") or 0),
            -float(row.get("avg_opportunity_delta_pct") or -10**9),
            str(row.get(key) or ""),
        )
    )
    return result


def _rotation_opportunity_phase_setup_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row.get("market_phase") or "unknown"), str(row.get("setup_family") or "unknown")), []).append(row)
    result = []
    for (phase, family), group_rows in grouped.items():
        result.append(
            {
                "market_phase": None if phase == "unknown" else phase,
                "market_phase_label": _market_phase_label_for_bucket(phase, group_rows),
                "setup_family": None if family == "unknown" else family,
                "setup_family_label": _setup_family_label_for_bucket(family, group_rows),
                **_rotation_opportunity_metric_summary(group_rows),
            }
        )
    result.sort(key=lambda row: (-int(row.get("evaluated_count") or 0), str(row.get("market_phase") or ""), str(row.get("setup_family") or "")))
    return result


def _rotation_opportunity_bucket(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if delta >= 20:
        return "large_positive"
    if delta >= 10:
        return "positive"
    if delta > 0:
        return "small_positive"
    if delta <= -10:
        return "large_negative"
    if delta <= -5:
        return "negative"
    return "flat_or_noise"


def _rotation_opportunity_bucket_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "large_positive": "明显值得研究",
        "positive": "中等正机会",
        "small_positive": "小幅正机会",
        "flat_or_noise": "差异不明显",
        "negative": "可能有害",
        "large_negative": "明显有害",
        "unknown": "后验不足",
    }
    return labels.get(str(value or "unknown"), str(value or "后验不足"))


def _rotation_candidate_rank_bucket(row: dict[str, Any]) -> str:
    rank = _safe_int_or_none(row.get("rank"))
    if rank is None:
        return "unknown"
    if rank <= 3:
        return "1-3"
    if rank <= 5:
        return "4-5"
    if rank <= 10:
        return "6-10"
    if rank <= 20:
        return "11-20"
    return "20+"


def _rotation_candidate_rank_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "1-3": "候选前3",
        "4-5": "候选4-5",
        "6-10": "候选6-10",
        "11-20": "候选11-20",
        "20+": "候选20名后",
        "unknown": "排名未知",
    }
    return labels.get(str(value or "unknown"), str(value or "排名未知"))


def _rotation_low_suction_days_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "0": "无低吸蓄势",
        "1-2": "低吸1-2天",
        "3-4": "低吸3-4天",
        "5+": "低吸5天以上",
        "unknown": "低吸天数未知",
    }
    return labels.get(str(value or "unknown"), str(value or "低吸天数未知"))


def _rotation_ma_convergence_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "<=5%": "均线收敛<=5%",
        "5-8.8%": "均线收敛5-8.8%",
        "8.8-13%": "均线收敛8.8-13%",
        ">13%": "均线发散>13%",
        "unknown": "均线收敛未知",
    }
    return labels.get(str(value or "unknown"), str(value or "均线收敛未知"))


def _rotation_replaced_current_return_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("replaced_current_return_pct"))
    if value is None:
        return "unknown"
    if value <= -5:
        return "<=-5%"
    if value < 0:
        return "-5-0%"
    if value < 5:
        return "0-5%"
    return ">=5%"


def _rotation_replaced_current_return_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "<=-5%": "弱持仓浮亏<=-5%",
        "-5-0%": "弱持仓小亏",
        "0-5%": "弱持仓小赚",
        ">=5%": "弱持仓浮盈>=5%",
        "unknown": "持仓浮盈未知",
    }
    return labels.get(str(value or "unknown"), str(value or "持仓浮盈未知"))


def _rotation_replaced_execute_open_return_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("replaced_execute_open_return_pct"))
    if value is None:
        return "unknown"
    if value <= -5:
        return "<=-5%"
    if value < 0:
        return "-5-0%"
    if value < 5:
        return "0-5%"
    return ">=5%"


def _rotation_replaced_execute_open_return_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "<=-5%": "执行开盘仍亏<=-5%",
        "-5-0%": "执行开盘小亏",
        "0-5%": "执行开盘小赚",
        ">=5%": "执行开盘浮盈>=5%",
        "unknown": "执行开盘收益未知",
    }
    return labels.get(str(value or "unknown"), str(value or "执行开盘收益未知"))


def _rotation_replaced_holding_days_bucket(row: dict[str, Any]) -> str:
    days = _safe_float(row.get("replaced_holding_days"))
    if days is None:
        return "unknown"
    if days <= 3:
        return "0-3"
    if days <= 7:
        return "4-7"
    if days <= 15:
        return "8-15"
    return "15+"


def _rotation_replaced_holding_days_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "0-3": "持仓0-3天",
        "4-7": "持仓4-7天",
        "8-15": "持仓8-15天",
        "15+": "持仓15天以上",
        "unknown": "持仓天数未知",
    }
    return labels.get(str(value or "unknown"), str(value or "持仓天数未知"))


def _rotation_opportunity_interpretation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _rotation_opportunity_metric_summary(rows)
    positive_rate = _safe_float(summary.get("positive_rate")) or 0.0
    avg_delta = _safe_float(summary.get("avg_opportunity_delta_pct"))
    if not rows:
        primary = "no_full_position_missed_candidates"
        message = "没有找到满仓挡住的前列 BUY 候选。"
    elif avg_delta is not None and avg_delta > 5 and positive_rate >= 55:
        primary = "promising_but_audit_only"
        message = "满仓前列候选存在后验正机会，但仍只能作为审计；需要继续找信号日可见代理后再做默认关闭实验。"
    elif avg_delta is not None and avg_delta <= 0:
        primary = "broad_rotation_not_supported"
        message = "整体机会成本不支持宽泛换仓；应继续按行情、策略族和风险桶寻找更窄条件。"
    else:
        primary = "mixed_opportunity"
        message = "机会成本分布混合，不能直接写成默认换仓规则；应优先查看分桶和样本。"
    return {"primary_issue": primary, "message": message}


def _candidate_context_fields(row: dict[str, Any]) -> dict[str, Any]:
    reason = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    evidence = reason.get("evidence") if isinstance(reason.get("evidence"), dict) else {}
    result: dict[str, Any] = {}
    for key in (
        "dynamic_market_regime",
        "market_warning_level",
        "market_warning_label",
        "recovery_state",
        "fund_flow_state",
        "market_temperature",
        "breadth_up_ratio_20d",
        "index_return_20d",
        "market_return_20d",
        "low_suction_days",
        "low_suction_launch_confirmed",
        "low_suction_launch_quality_bucket",
        "low_suction_dragon_state",
        "ma_convergence_pct",
        "volume_ratio_5d",
        "close_location",
    ):
        value = row.get(key)
        if value is None:
            value = reason.get(key)
        if value is None:
            value = evidence.get(key)
        if value is not None:
            result[key] = value
    return result


def _rotation_opportunity_enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    explicit_family = row.get("setup_family")
    item = _with_market_phase_fields(row)
    item["setup_family"] = explicit_family or item.get("setup_family") or _market_phase_setup_family(item)
    item["setup_label"] = _setup_family_label_for_bucket(item.get("setup_family"), [item])
    bucket = item.get("low_suction_launch_quality_bucket")
    if bucket:
        item["low_suction_launch_quality_label"] = low_suction_launch_quality_label(bucket)
    return item


def trend_winner_protection_rows(*, rotation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify replacement targets by whether they should be protected."""

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rotation_rows:
        held_symbol = str(row.get("replaced_symbol") or "")
        execute_date = _as_date(row.get("execute_date"))
        if not held_symbol or execute_date is None:
            continue
        key = (execute_date, held_symbol, _as_date(row.get("replaced_entry_date")))
        grouped.setdefault(key, []).append(row)

    rows: list[dict[str, Any]] = []
    for group_rows in grouped.values():
        row = sorted(
            group_rows,
            key=lambda item: (
                -(_safe_float(item.get("opportunity_delta_pct")) or -10**9),
                _safe_int(item.get("rank"), 10**9),
                str(item.get("vt_symbol") or ""),
            ),
        )[0]
        held_symbol = str(row.get("replaced_symbol") or "")
        execute_date = _as_date(row.get("execute_date"))
        blocked_candidate_count = len(group_rows)
        positive_opportunities = [
            item for item in group_rows if (_safe_float(item.get("opportunity_delta_pct")) or 0.0) > 0
        ]
        harmful_opportunities = [
            item for item in group_rows if (_safe_float(item.get("opportunity_delta_pct")) or 0.0) < 0
        ]
        best_delta = max(
            (value for item in group_rows if (value := _safe_float(item.get("opportunity_delta_pct"))) is not None),
            default=None,
        )
        avg_delta = _avg(
            [value for item in group_rows if (value := _safe_float(item.get("opportunity_delta_pct"))) is not None]
        )
        open_return = _safe_float(row.get("replaced_execute_open_return_pct"))
        snapshot_return = _safe_float(row.get("replaced_snapshot_return_pct") or row.get("replaced_current_return_pct"))
        real_return = _safe_float(row.get("replaced_real_return_pct"))
        delta = _safe_float(row.get("opportunity_delta_pct"))
        bucket, reason = _trend_winner_protection_bucket(
            open_return=open_return,
            snapshot_return=snapshot_return,
            real_return=real_return,
            opportunity_delta=delta,
            market_phase=row.get("market_phase"),
        )
        protected = bucket in {"protect_trend_winner", "protect_open_profit", "protect_uptrend_repair"}
        replaceable = bucket == "replaceable_weak_holding"
        item = {
            "signal_date": _as_date(row.get("signal_date")),
            "execute_date": execute_date,
            "candidate_symbol": row.get("vt_symbol"),
            "candidate_name": row.get("name"),
            "candidate_rank": row.get("rank"),
            "candidate_score": row.get("score"),
            "candidate_setup_family": row.get("setup_family"),
            "candidate_return_pct": row.get("candidate_return_pct"),
            "blocked_candidate_count": blocked_candidate_count,
            "positive_opportunity_count": len(positive_opportunities),
            "harmful_opportunity_count": len(harmful_opportunities),
            "best_opportunity_delta_pct": best_delta,
            "avg_opportunity_delta_pct": avg_delta,
            "held_symbol": held_symbol,
            "held_name": row.get("replaced_name"),
            "held_entry_date": _as_date(row.get("replaced_entry_date")),
            "held_holding_days": row.get("replaced_holding_days"),
            "held_snapshot_return_pct": snapshot_return,
            "held_execute_open_return_pct": open_return,
            "held_real_return_pct": real_return,
            "held_exit_date": row.get("replaced_exit_date"),
            "held_exit_reason": row.get("replaced_exit_reason"),
            "opportunity_delta_pct": delta,
            "market_phase": row.get("market_phase"),
            "market_phase_label": row.get("market_phase_label"),
            "protection_bucket": bucket,
            "protection_label": _trend_winner_protection_label(bucket),
            "protected": protected,
            "replaceable": replaceable,
            "reason": reason,
        }
        rows.append(item)
    return rows


def trend_winner_protection_matrix_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize holdings that should be protected from rotation."""

    return {
        "method": "只读矩阵：复用满仓换仓机会矩阵，按 D+1 开盘收益、真实退出收益和行情阶段识别不能被替换的趋势持仓。",
        "audit_only": True,
        "not_used_for_signal_score": True,
        "overall": _trend_winner_protection_metric_summary(rows),
        "by_protection_bucket": _trend_winner_protection_group_metrics(rows, "protection_bucket", _trend_winner_protection_label),
        "by_phase": _trend_winner_protection_group_metrics(rows, "market_phase", _market_phase_label_for_bucket),
        "by_execute_open_return": _trend_winner_protection_derived_group_metrics(
            rows,
            "held_execute_open_return_bucket",
            _trend_winner_execute_open_bucket,
            _rotation_replaced_execute_open_return_label,
        ),
        "interpretation": _trend_winner_protection_interpretation(rows),
    }


def _trend_winner_protection_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    protected = [row for row in rows if row.get("protected")]
    replaceable = [row for row in rows if row.get("replaceable")]
    deltas = [value for row in rows if (value := _safe_float(row.get("opportunity_delta_pct"))) is not None]
    real_returns = [value for row in rows if (value := _safe_float(row.get("held_real_return_pct"))) is not None]
    open_returns = [value for row in rows if (value := _safe_float(row.get("held_execute_open_return_pct"))) is not None]
    harmful_replacements = [row for row in rows if (_safe_float(row.get("opportunity_delta_pct")) or 0) < 0]
    return {
        "candidate_count": len(rows),
        "protected_count": len(protected),
        "protected_rate": _pct_ratio(len(protected), len(rows)),
        "replaceable_count": len(replaceable),
        "replaceable_rate": _pct_ratio(len(replaceable), len(rows)),
        "harmful_replacement_count": len(harmful_replacements),
        "harmful_replacement_rate": _pct_ratio(len(harmful_replacements), len(rows)),
        "avg_held_execute_open_return_pct": _avg(open_returns),
        "avg_held_real_return_pct": _avg(real_returns),
        "avg_opportunity_delta_pct": _avg(deltas),
    }


def _trend_winner_protection_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str] | Callable[[Any], str],
) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key) or "unknown", []).append(row)
    result: list[dict[str, Any]] = []
    for value, group_rows in grouped.items():
        try:
            label = labeler(value, group_rows)  # type: ignore[misc]
        except TypeError:
            label = labeler(value)  # type: ignore[operator]
        result.append({key: None if value == "unknown" else value, "label": label, **_trend_winner_protection_metric_summary(group_rows)})
    result.sort(key=lambda row: (-int(row.get("candidate_count") or 0), str(row.get(key) or "")))
    return result


def _trend_winner_protection_derived_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    bucket_func: Callable[[dict[str, Any]], str],
    labeler: Callable[[Any, list[dict[str, Any]]], str] | Callable[[Any], str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(bucket_func(row) or "unknown", []).append(row)
    result: list[dict[str, Any]] = []
    for value, group_rows in grouped.items():
        try:
            label = labeler(value, group_rows)  # type: ignore[misc]
        except TypeError:
            label = labeler(value)  # type: ignore[operator]
        result.append({key: None if value == "unknown" else value, "label": label, **_trend_winner_protection_metric_summary(group_rows)})
    result.sort(key=lambda row: (-int(row.get("candidate_count") or 0), str(row.get(key) or "")))
    return result


def _trend_winner_protection_bucket(
    *,
    open_return: float | None,
    snapshot_return: float | None,
    real_return: float | None,
    opportunity_delta: float | None,
    market_phase: Any,
) -> tuple[str, str]:
    phase = str(market_phase or "")
    visible_return = open_return if open_return is not None else snapshot_return
    if visible_return is not None and visible_return >= 5 and (real_return is None or real_return >= 0):
        return "protect_trend_winner", "执行开盘已盈利且真实退出仍盈利"
    if visible_return is not None and visible_return >= 0 and phase == "uptrend":
        return "protect_uptrend_repair", "主升环境下执行开盘已修复"
    if visible_return is not None and visible_return >= 0:
        return "protect_open_profit", "执行开盘已盈利或亏损已修复"
    if visible_return is not None and visible_return <= -5 and (opportunity_delta is None or opportunity_delta > 0):
        return "replaceable_weak_holding", "执行开盘仍明显亏损，才适合作为换仓审计对象"
    return "needs_manual_review", "执行开盘状态不足以支持直接替换或保护"


def _trend_winner_protection_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "protect_trend_winner": "保护趋势赢家",
        "protect_uptrend_repair": "主升修复保护",
        "protect_open_profit": "开盘盈利保护",
        "replaceable_weak_holding": "可研究弱持仓替换",
        "needs_manual_review": "需要人工复核",
        "unknown": "状态未知",
    }
    return labels.get(str(value or "unknown"), str(value or "状态未知"))


def _trend_winner_execute_open_bucket(row: dict[str, Any]) -> str:
    return _rotation_replaced_execute_open_return_bucket({"replaced_execute_open_return_pct": row.get("held_execute_open_return_pct")})


def _trend_winner_protection_interpretation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _trend_winner_protection_metric_summary(rows)
    protected_rate = _safe_float(summary.get("protected_rate")) or 0.0
    replaceable_rate = _safe_float(summary.get("replaceable_rate")) or 0.0
    if not rows:
        primary = "no_full_position_rotation_samples"
        message = "没有满仓换仓样本，无法评估趋势赢家保护。"
    elif protected_rate >= replaceable_rate:
        primary = "protect_winners_before_rotation"
        message = "需要先保护 D+1 开盘已修复或盈利的持仓，再讨论换仓；否则容易卖掉趋势赢家。"
    else:
        primary = "weak_holding_rotation_needs_narrow_test"
        message = "执行开盘仍弱的样本占比较高，但仍需默认关闭实验验证，不能直接改变默认策略。"
    return {"primary_issue": primary, "message": message}


def _attach_replaced_execute_open_returns(session: Any, schema: Any, rows: list[dict[str, Any]]) -> None:
    symbols = sorted({str(row.get("replaced_symbol") or "") for row in rows if row.get("replaced_symbol")})
    dates = sorted({_as_date(row.get("execute_date")) for row in rows if _as_date(row.get("execute_date"))})
    if not symbols or not dates:
        return
    bar_rows = session.execute(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
        ).where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.in_(dates),
        )
    ).mappings().all()
    opens = {
        (str(row["vt_symbol"]), _as_date(row["trade_date"])): _safe_float(row.get("open_price"))
        for row in bar_rows
    }
    for row in rows:
        key = (str(row.get("replaced_symbol") or ""), _as_date(row.get("execute_date")))
        open_price = opens.get(key)
        cost_price = _safe_float(row.get("replaced_cost_price"))
        row["replaced_execute_open_price"] = open_price
        row["replaced_execute_open_return_pct"] = (
            (open_price / cost_price - 1) * 100 if open_price is not None and cost_price else None
        )
        row["replaced_execute_open_return_source"] = (
            "stock_daily_bars.open_price" if open_price is not None and cost_price else None
        )


def _weakest_rotation_position(positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not positions:
        return None
    return sorted(
        positions,
        key=lambda row: (
            _safe_float(row.get("floating_pnl_pct")) if _safe_float(row.get("floating_pnl_pct")) is not None else 10**9,
            -_safe_int(row.get("holding_days"), 0),
            str(row.get("vt_symbol") or ""),
        ),
    )[0]


def _position_exit_returns_by_entry(trades: list[dict[str, Any]]) -> dict[tuple[str, date | None], dict[str, Any]]:
    result: dict[tuple[str, date | None], dict[str, Any]] = {}
    for key, closed in _closed_trade_rows_by_entry(trades).items():
        result[key] = {
            **closed,
            "exit_reason": closed.get("exit_reason") or closed.get("reason"),
        }
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    sell_reasons_by_key: dict[tuple[str, date | None], Any] = {}
    for trade in sorted(trades, key=lambda item: (_as_date(item.get("trade_date")) or date.min, int(item.get("id") or 0))):
        side = str(trade.get("side") or "").upper()
        symbol = str(trade.get("vt_symbol") or "")
        if side == "BUY":
            open_by_symbol.setdefault(symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_by_symbol.setdefault(symbol, []).pop(0) if open_by_symbol.get(symbol) else None
        if not entry:
            continue
        sell_reasons_by_key[(symbol, _as_date(entry.get("trade_date")))] = trade.get("reason")
    for key, reason in sell_reasons_by_key.items():
        if key in result:
            result[key]["exit_reason"] = result[key].get("exit_reason") or reason
    if result:
        return result
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for trade in sorted(trades, key=lambda item: (_as_date(item.get("trade_date")) or date.min, int(item.get("id") or 0))):
        side = str(trade.get("side") or "").upper()
        symbol = str(trade.get("vt_symbol") or "")
        if side == "BUY":
            open_by_symbol.setdefault(symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_by_symbol.setdefault(symbol, []).pop(0) if open_by_symbol.get(symbol) else None
        if not entry:
            continue
        amount = _safe_float(entry.get("amount")) or 0.0
        pnl = _safe_float(trade.get("pnl")) or 0.0
        result[(symbol, _as_date(entry.get("trade_date")))] = {
            "vt_symbol": symbol,
            "entry_date": _as_date(entry.get("trade_date")),
            "exit_date": _as_date(trade.get("trade_date")),
            "pnl": pnl,
            "return_pct": pnl / amount * 100 if amount else None,
            "exit_reason": trade.get("reason"),
        }
    return result


def _rotation_opportunity_summary_text(
    *,
    candidate_return: float | None,
    held_return: float | None,
    held_current: float | None,
    replacement: dict[str, Any] | None,
) -> str:
    if candidate_return is None:
        return "候选固定持有后验不足。"
    if held_return is None:
        held_text = f"弱持仓当日浮盈 {held_current:.2f}%" if held_current is not None else "弱持仓后验不足"
        return f"候选固定后验 {candidate_return:.2f}%；{held_text}。"
    delta = candidate_return - held_return
    symbol = str((replacement or {}).get("vt_symbol") or "弱持仓")
    return f"候选固定后验 {candidate_return:.2f}%，对比 {symbol} 真实退出 {held_return:.2f}%，差值 {delta:.2f}%。"


def _rows_by_signal_key(rows: list[dict[str, Any]], *, prefer_signal_date: bool = False) -> dict[tuple[date, str], list[dict[str, Any]]]:
    grouped: dict[tuple[date, str], list[dict[str, Any]]] = {}
    for row in rows:
        signal_date = _event_signal_date(row, prefer_signal_date=prefer_signal_date)
        symbol = str(row.get("vt_symbol") or "")
        if signal_date is None or not symbol:
            continue
        grouped.setdefault((signal_date, symbol), []).append(row)
    return grouped


def _event_signal_date(row: dict[str, Any], *, prefer_signal_date: bool = False) -> date | None:
    if prefer_signal_date:
        parsed = _as_date(row.get("signal_date"))
        if parsed is not None:
            return parsed
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    return (
        _as_date(raw.get("signal_date"))
        or _as_date(execution.get("signal_date"))
        or _as_date(row.get("signal_date"))
        or _as_date(row.get("trade_date"))
    )


def _signal_event_in_rank_limit(row: dict[str, Any], candidate_rank_limit: int) -> bool:
    execution = _signal_execution_context(row)
    rank = _safe_int_or_none(execution.get("execution_candidate_rank"))
    if rank is None:
        rank = _safe_int_or_none(execution.get("raw_signal_rank"))
    return rank is not None and rank <= min(max(int(candidate_rank_limit or 100), 1), 200)


def _first_row(rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _recommendation_setup_type(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    reason = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    evidence = reason.get("evidence") if isinstance(reason.get("evidence"), dict) else {}
    return reason.get("entry_setup") or reason.get("setup_type") or evidence.get("entry_setup") or evidence.get("setup_type")


def _trade_setup_type(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    return raw.get("entry_setup") or raw.get("setup_type")


def _execution_breakpoint_summary(
    status: str,
    setup: str | None,
    execution: dict[str, Any],
    equity_row: dict[str, Any],
    run_params: dict[str, Any],
    theoretical: dict[str, Any],
    real_position: dict[str, Any] | None,
) -> str:
    setup_text = _setup_family_label_for_bucket(_market_phase_setup_family({"entry_setup": setup}), [])
    if status == "filled":
        return "候选最终进入真实组合并成交。"
    if status == "watch_not_bought":
        return "候选为观察状态，默认组合不买入。"
    if status == "rejected":
        return "候选进入订单链路，但真实订单被拒绝。"
    if status == "planned_not_ordered_full":
        rank = execution.get("execution_candidate_rank")
        return f"{setup_text}信号进入执行池第 {rank} 名，但执行日组合满仓 {equity_row.get('position_count')}/{_safe_int(run_params.get('max_positions'), 10)}，未触发换仓。"
    if status == "planned_not_ordered_limit":
        return f"{setup_text}信号存在，但没有进入组合执行前 {_safe_int(run_params.get('candidate_limit'), 20)} 名。"
    if status == "candidate_top_rank_full":
        return f"候选排名在执行观察范围内，但当日组合满仓 {equity_row.get('position_count')}/{_safe_int(run_params.get('max_positions'), 10)}，没有触发换仓。"
    if status == "candidate_rank_outside_execution_pool":
        return f"候选排名未进入组合执行前 {_safe_int(run_params.get('candidate_limit'), 20)} 名，默认只作为观察。"
    if status == "candidate_top_rank_no_order":
        return "候选排名在执行观察范围内，但没有对应理论计划、订单或成交，需要核查执行计划链路。"
    if status == "candidate_real_already_held":
        return "候选没有重复写入 BUY，但真实组合当日已经持有该股。"
    if status == "theoretical_held_real_not_held":
        return f"理论信号标记账本自 {theoretical.get('entry_date') or '此前'} 起已标记持有，但真实组合当日未持有；这是信号展示/理论账本差异。"
    if status == "theoretical_held_real_held":
        return f"理论信号层已持有，真实组合当日也持有，未重复写入 BUY。"
    if status == "not_triggered":
        return "理论计划存在，但执行条件未触发。"
    if status == "plan_rejected":
        return "理论计划存在，但计划状态为拒绝。"
    if real_position is not None:
        return "候选没有进入当天 BUY 计划，但真实组合已有持仓。"
    return "候选没有进入当天理论 BUY 计划，需要核查候选、理论计划和执行状态。"


def _execution_breakpoint_status_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "filled": "真实买入",
        "watch_not_bought": "观察未买",
        "rejected": "订单拒买",
        "not_triggered": "理论未触发",
        "plan_rejected": "计划拒绝",
        "planned_not_ordered_full": "满仓未换仓",
        "planned_not_ordered_limit": "执行池外",
        "planned_not_ordered_other": "计划未下单",
        "candidate_top_rank_full": "候选前列但满仓",
        "candidate_rank_outside_execution_pool": "候选执行池外",
        "candidate_top_rank_no_order": "候选前列无订单",
        "candidate_real_already_held": "真实组合已持有",
        "theoretical_held_real_not_held": "理论标记与真实持仓不一致",
        "theoretical_held_real_held": "理论标记和真实均已持有",
        "candidate_not_planned": "候选未进计划",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _execution_breakpoint_status_group(value: Any) -> str:
    text = str(value or "")
    if text == "filled":
        return "filled"
    if text in {"watch_not_bought", "rejected", "not_triggered", "plan_rejected"}:
        return "risk_or_condition"
    if text in {
        "planned_not_ordered_full",
        "planned_not_ordered_limit",
        "planned_not_ordered_other",
        "candidate_top_rank_full",
        "candidate_rank_outside_execution_pool",
        "candidate_top_rank_no_order",
    }:
        return "portfolio_execution"
    if text in {"candidate_real_already_held", "theoretical_held_real_not_held", "theoretical_held_real_held"}:
        return "holding_state"
    return "planning_gap"


def _execution_breakpoint_status_group_label(value: Any, _rows: list[dict[str, Any]] | None = None) -> str:
    labels = {
        "filled": "真实成交",
        "risk_or_condition": "观察/拒买/未触发",
        "portfolio_execution": "组合执行断点",
        "holding_state": "持仓状态断点",
        "planning_gap": "理论计划断点",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _execution_breakpoint_status_order(value: Any) -> int:
    order = {
        "planned_not_ordered_full": 0,
        "candidate_top_rank_full": 1,
        "candidate_top_rank_no_order": 2,
        "planned_not_ordered_limit": 3,
        "candidate_rank_outside_execution_pool": 4,
        "planned_not_ordered_other": 5,
        "candidate_not_planned": 6,
        "rejected": 7,
        "not_triggered": 8,
        "plan_rejected": 9,
        "watch_not_bought": 10,
        "theoretical_held_real_not_held": 11,
        "candidate_real_already_held": 12,
        "filled": 13,
        "theoretical_held_real_held": 14,
    }
    return order.get(str(value or ""), 99)


def setup_market_exit_audit_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = [_with_path_issue(row) for row in rows]
    return {
        "overall": _path_metric_summary(enriched),
        "by_entry_setup": _group_path_metrics(enriched, "entry_setup", _entry_setup_label),
        "by_dynamic_market_regime": _group_path_metrics(enriched, "dynamic_market_regime", _dynamic_market_label_for_bucket),
        "by_market_warning": _group_path_metrics(enriched, "market_warning_label", lambda value, _rows: str(value or "未知")),
        "by_entry_context": _group_path_metrics(enriched, "entry_context_state", _entry_context_label_for_bucket),
        "by_short_term_trade_context": _group_path_metrics(
            enriched,
            "short_term_trade_context",
            _short_term_trade_context_label_for_bucket,
        ),
        "by_market_mainline_trade_context": _group_path_metrics(
            enriched,
            "market_mainline_trade_context",
            _market_mainline_trade_context_label_for_bucket,
        ),
        "by_entry_launch_diagnostic": _group_path_metrics(
            enriched,
            "entry_launch_diagnostic_state",
            _entry_launch_diagnostic_label_for_bucket,
        ),
        "by_low_suction_dragon_context": _group_path_metrics(
            enriched,
            "low_suction_dragon_state",
            _low_suction_dragon_context_label_for_bucket,
        ),
        "by_fund_flow_coverage": _group_path_metrics(enriched, "fund_flow_coverage_state", _fund_flow_coverage_label_for_bucket),
        "by_exit_reason": _group_path_metrics(enriched, "exit_reason", _exit_reason_label_for_bucket),
        "by_issue_type": _group_path_metrics(enriched, "path_issue_type", _path_issue_label_for_bucket),
        "by_early_follow_through": _group_path_metrics(
            enriched,
            "early_follow_through_state",
            _early_follow_through_label_for_bucket,
        ),
        "entry_launch_quality_audit": entry_launch_quality_audit(enriched),
        "support_stop_context_audit": support_stop_context_audit(enriched),
        "exit_path_replacement_quality": exit_path_replacement_quality_summary(enriched),
        "market_context_validation": market_context_validation_summary(enriched),
        "setup_market_exit_matrix": _setup_market_exit_matrix(enriched),
        "buy_sell_problem_matrix": buy_sell_problem_matrix(enriched),
        "worst_buckets": _worst_setup_market_exit_buckets(enriched),
    }


def market_phase_strategy_audit_summary(
    trade_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    candidate_top_n: int = 20,
) -> dict[str, Any]:
    enriched_trades = [_with_market_phase_fields(_with_nested_signal_evidence(row)) for row in trade_rows]
    enriched_candidates = [_with_market_phase_fields(_with_nested_signal_evidence(row)) for row in candidate_rows]
    return {
        "method": "只读审计：交易结果按买入日行情四象限聚合；候选结果使用固定持有后验，只验证候选质量，不参与信号日交易。",
        "overall": _phase_trade_metric_summary(enriched_trades),
        "by_phase": _phase_group_metrics(enriched_trades, "market_phase", _market_phase_label_for_bucket),
        "by_phase_setup": _phase_setup_matrix(enriched_trades),
        "by_setup": _phase_group_metrics(enriched_trades, "setup_family", _setup_family_label_for_bucket),
        "candidate_top_n": candidate_top_n,
        "candidate_by_phase": _phase_candidate_group_metrics(enriched_candidates, "market_phase", _market_phase_label_for_bucket),
        "candidate_by_phase_setup": _phase_candidate_setup_matrix(enriched_candidates),
        "diagnostics": _market_phase_diagnostics(enriched_trades, enriched_candidates),
        "not_used_for_signal_score": True,
    }


def phase_strategy_family_matrix_summary(
    trade_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    candidate_rank_limits: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Return a stable phase x strategy-family matrix for product audit reports."""

    rank_limits = _normalized_candidate_rank_limits(candidate_rank_limits)
    enriched_trades = [_with_market_phase_fields(_with_nested_signal_evidence(row)) for row in trade_rows]
    enriched_candidates = [_with_market_phase_fields(_with_nested_signal_evidence(row)) for row in candidate_rows]
    candidate_matrices = []
    for limit in rank_limits:
        limited_candidates = [
            row for row in enriched_candidates if 0 < _safe_int(row.get("rank"), limit + 1) <= limit
        ]
        candidate_matrices.append(
            {
                "rank_limit": limit,
                "candidate_count": len(limited_candidates),
                "by_phase": _phase_candidate_group_metrics(
                    limited_candidates,
                    "market_phase",
                    _market_phase_label_for_bucket,
                ),
                "by_phase_setup": _phase_candidate_setup_matrix(limited_candidates),
                "by_setup": _phase_candidate_group_metrics(
                    limited_candidates,
                    "setup_family",
                    _setup_family_label_for_bucket,
                ),
            }
        )
    return {
        "method": "只读矩阵：真实成交按买入日可见行情阶段聚合；候选按信号日可见行情阶段和固定持有后验聚合。",
        "real_trade_matrix": _phase_setup_matrix(enriched_trades),
        "real_trade_by_phase": _phase_group_metrics(enriched_trades, "market_phase", _market_phase_label_for_bucket),
        "real_trade_by_setup": _phase_group_metrics(enriched_trades, "setup_family", _setup_family_label_for_bucket),
        "candidate_rank_limits": rank_limits,
        "candidate_rank_matrices": candidate_matrices,
        "coverage": {
            "trade_count": len(enriched_trades),
            "candidate_count": len(enriched_candidates),
            "candidate_max_rank_loaded": max(rank_limits),
        },
        "interpretation": _phase_strategy_family_interpretation(enriched_trades, enriched_candidates),
        "not_used_for_signal_score": True,
        "audit_only": True,
    }


def replacement_quality_matrix_summary(
    trade_rows: list[dict[str, Any]],
    reject_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize filled replacements/trades and gate rejects by phase/family."""

    filled = [_with_replacement_matrix_trade_fields(row) for row in trade_rows]
    rejects = [_with_replacement_matrix_reject_fields(row) for row in reject_rows]
    return {
        "method": "只读矩阵：真实成交按买入日行情/策略族聚合；闸门拒买按执行日可见行情和拒买原因聚合。",
        "filled_overall": _phase_trade_metric_summary(filled),
        "filled_by_phase": _phase_group_metrics(filled, "market_phase", _market_phase_label_for_bucket),
        "filled_by_setup_family": _phase_group_metrics(filled, "setup_family", _setup_family_label_for_bucket),
        "filled_by_phase_setup": _phase_setup_matrix(filled),
        "filled_by_low_suction_bucket": _phase_group_metrics(
            filled,
            "low_suction_launch_quality_bucket",
            _low_suction_launch_quality_label_for_bucket,
        ),
        "filled_by_exit_reason": _phase_group_metrics(filled, "exit_reason", _exit_reason_label_for_bucket),
        "rejected_overall": _replacement_reject_metric_summary(rejects),
        "rejected_by_phase": _replacement_reject_group_metrics(rejects, "market_phase", _market_phase_label_for_bucket),
        "rejected_by_setup_family": _replacement_reject_group_metrics(rejects, "setup_family", _setup_family_label_for_bucket),
        "rejected_by_low_suction_bucket": _replacement_reject_group_metrics(
            rejects,
            "low_suction_launch_quality_bucket",
            _low_suction_launch_quality_label_for_bucket,
        ),
        "rejected_by_warning_level": _replacement_reject_group_metrics(
            rejects,
            "market_warning_level",
            _market_warning_level_label_for_bucket,
        ),
        "rejected_reason_counts": _replacement_reject_reason_counts(rejects),
        "interpretation": _replacement_quality_interpretation(filled, rejects),
        "not_used_for_signal_score": True,
        "audit_only": True,
    }


def backtest_day_detail(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    trade_date: date,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    ensure_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}
        equity = session.execute(
            select(schema.backtest_daily_equity)
            .where(
                schema.backtest_daily_equity.c.backtest_id == backtest_id,
                schema.backtest_daily_equity.c.trade_date == trade_date,
            )
        ).mappings().first()
        position_rows = session.execute(
            select(schema.backtest_daily_positions)
            .where(
                schema.backtest_daily_positions.c.backtest_id == backtest_id,
                schema.backtest_daily_positions.c.trade_date == trade_date,
            )
            .order_by(desc(schema.backtest_daily_positions.c.market_value), schema.backtest_daily_positions.c.vt_symbol)
        ).mappings().all()
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(
                schema.backtest_trades.c.backtest_id == backtest_id,
                schema.backtest_trades.c.trade_date == trade_date,
            )
            .order_by(schema.backtest_trades.c.id)
        ).mappings().all()
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(
                schema.backtest_orders.c.backtest_id == backtest_id,
                schema.backtest_orders.c.trade_date == trade_date,
            )
            .order_by(schema.backtest_orders.c.id)
        ).mappings().all()
        signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(
                schema.backtest_signal_events.c.backtest_id == backtest_id,
                schema.backtest_signal_events.c.trade_date == trade_date,
            )
            .order_by(schema.backtest_signal_events.c.id)
        ).mappings().all()
        position_dicts = [dict(row) for row in position_rows]
        trade_dicts = [dict(row) for row in trade_rows]
        order_dicts = [dict(row) for row in order_rows]
        signal_dicts = [dict(row) for row in signal_rows]
        signal_dates = sorted({row["signal_date"] for row in signal_dicts if row.get("signal_date")})
        if signal_dates:
            recommendation_rows = session.execute(
                select(schema.quant_recommendations)
                .where(
                    schema.quant_recommendations.c.trade_date.in_(signal_dates),
                    schema.quant_recommendations.c.strategy_id == run["strategy_id"],
                    schema.quant_recommendations.c.strategy_version == run["strategy_version"],
                )
                .order_by(schema.quant_recommendations.c.trade_date, schema.quant_recommendations.c.rank)
            ).mappings().all()
        else:
            recommendation_rows = []
        recommendation_dicts = [dict(row) for row in recommendation_rows]
        stock_names = load_stock_names(session, symbols_from_rows(position_dicts, trade_dicts, order_dicts, signal_dicts, recommendation_dicts))

    named_positions = with_stock_names(position_dicts, stock_names)
    named_trades = with_stock_names(trade_dicts, stock_names)
    named_orders = with_stock_names(order_dicts, stock_names)
    named_signals = with_stock_names(signal_dicts, stock_names)
    named_recommendations = with_stock_names(recommendation_dicts, stock_names)
    buys = [row for row in named_trades if row.get("side") == "BUY"]
    sells = [row for row in named_trades if row.get("side") == "SELL"]
    decision_summary = daily_decision_summary(named_recommendations, named_signals, named_orders, named_trades)
    decision_summary["source_signal_dates"] = sorted({str(row.get("signal_date") or row.get("trade_date") or "") for row in named_signals if row.get("signal_date") or row.get("trade_date")})
    return {
        "status": "ready" if equity or position_rows or trade_rows or order_rows else "empty",
        "backtest_id": backtest_id,
        "trade_date": trade_date.isoformat(),
        "equity": to_api(dict(equity)) if equity else None,
        "positions": [to_api(row) for row in named_positions],
        "trades": [to_api(row) for row in named_trades],
        "buy_trades": [to_api(row) for row in buys],
        "sell_trades": [to_api(row) for row in sells],
        "orders": [to_api(row) for row in named_orders],
        "signals": [to_api(row) for row in named_signals],
        "recommendations": [to_api(row) for row in named_recommendations],
        "decision_summary": to_api(decision_summary),
        "snapshot_available": bool(position_rows),
        "note": "旧回测没有逐股持仓快照时，需要重跑回测后才能查看每日每只持仓市值。",
    }


def backtest_symbol_detail(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    normalize_symbol: SymbolNormalizer,
    load_stock_names: StockNameLoader,
    with_stock_names: NameAppender,
    board_payload: BoardPayload,
    closed_trades: ClosedTrades,
    to_api: ApiMapper,
    backtest_id: int,
    vt_symbol: str,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    symbol = normalize_symbol(vt_symbol)
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    ensure_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}
        position_rows = session.execute(
            select(schema.backtest_daily_positions)
            .where(
                schema.backtest_daily_positions.c.backtest_id == backtest_id,
                schema.backtest_daily_positions.c.vt_symbol == symbol,
            )
            .order_by(schema.backtest_daily_positions.c.trade_date)
        ).mappings().all()
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(
                schema.backtest_trades.c.backtest_id == backtest_id,
                schema.backtest_trades.c.vt_symbol == symbol,
            )
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(
                schema.backtest_orders.c.backtest_id == backtest_id,
                schema.backtest_orders.c.vt_symbol == symbol,
            )
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        position_dicts = [dict(row) for row in position_rows]
        trade_dicts = [dict(row) for row in trade_rows]
        order_dicts = [dict(row) for row in order_rows]
        stock_names = load_stock_names(session, [symbol])

    named_positions = with_stock_names(position_dicts, stock_names)
    named_trades = with_stock_names(trade_dicts, stock_names)
    attribution = trade_attribution(named_trades, named_positions)
    return {
        "status": "ready" if position_rows or trade_rows or order_rows else "empty",
        "backtest_id": backtest_id,
        "vt_symbol": symbol,
        **board_payload(symbol, stock_names.get(symbol)),
        "name": (stock_names.get(symbol) or {}).get("name"),
        "positions": [_entry_enriched_api_row(row, to_api) for row in named_positions],
        "trades": [_entry_enriched_api_row(row, to_api) for row in named_trades],
        "orders": [_entry_enriched_api_row(row, to_api) for row in with_stock_names(order_dicts, stock_names)],
        "closed_trades": closed_trades(named_trades),
        "trade_attribution": [to_api(row) for row in attribution],
        "snapshot_available": bool(position_rows),
        "note": "旧回测没有逐股持仓快照时，需要重跑回测后才能查看该股票每日持仓路径。",
    }


def daily_decision_summary(
    recommendations: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate the candidate -> signal -> order -> trade chain for one day."""

    buy_recommendations = [row for row in recommendations if str(row.get("action") or "").upper() == "BUY"]
    watch_recommendations = [row for row in recommendations if str(row.get("action") or "").upper() == "WATCH"]
    buy_signals = [row for row in signals if str(row.get("side") or "").upper() == "BUY"]
    sell_signals = [row for row in signals if str(row.get("side") or "").upper() == "SELL"]
    buy_orders = [row for row in orders if str(row.get("side") or "").upper() == "BUY"]
    sell_orders = [row for row in orders if str(row.get("side") or "").upper() == "SELL"]
    filled_orders = [row for row in orders if str(row.get("status") or "") == "filled"]
    rejected_orders = [row for row in orders if str(row.get("status") or "") == "rejected"]
    buy_trades = [row for row in trades if str(row.get("side") or "").upper() == "BUY"]
    sell_trades = [row for row in trades if str(row.get("side") or "").upper() == "SELL"]
    buy_amount = sum(float(row.get("amount") or 0) + float(row.get("fee") or 0) for row in buy_trades)
    sell_cash_in = sum(float(row.get("amount") or 0) - float(row.get("fee") or 0) for row in sell_trades)
    realized_pnl = sum(float(row.get("pnl") or 0) for row in sell_trades if row.get("pnl") is not None)
    if buy_trades or sell_trades:
        status = "traded"
        status_label = "有成交"
    elif rejected_orders:
        status = "rejected"
        status_label = "有拒单"
    elif buy_signals or sell_signals:
        status = "planned"
        status_label = "有计划未成交"
    elif buy_recommendations or watch_recommendations:
        status = "candidates_only"
        status_label = "仅候选"
    else:
        status = "empty"
        status_label = "无候选链路"
    return {
        "status": status,
        "status_label": status_label,
        "buy_candidate_count": len(buy_recommendations),
        "watch_candidate_count": len(watch_recommendations),
        "buy_signal_count": len(buy_signals),
        "sell_signal_count": len(sell_signals),
        "buy_order_count": len(buy_orders),
        "sell_order_count": len(sell_orders),
        "filled_order_count": len(filled_orders),
        "rejected_order_count": len(rejected_orders),
        "buy_trade_count": len(buy_trades),
        "sell_trade_count": len(sell_trades),
        "buy_amount": buy_amount,
        "sell_cash_in": sell_cash_in,
        "realized_pnl": realized_pnl,
        "rejected_reasons": _reason_counts(rejected_orders),
    }


def daily_decision_rows(
    equity_rows: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    position_counts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate the daily decision chain for all execution days in one backtest."""

    trading_days = sorted({parsed for parsed in (_as_date(row.get("trade_date")) for row in equity_rows) if parsed})
    next_trading_day = {day: trading_days[index + 1] for index, day in enumerate(trading_days[:-1])}
    recommendations_by_signal_date: dict[date, list[dict[str, Any]]] = {}
    signals_by_trade_date: dict[date, list[dict[str, Any]]] = {}
    orders_by_trade_date: dict[date, list[dict[str, Any]]] = {}
    trades_by_trade_date: dict[date, list[dict[str, Any]]] = {}
    signal_dates_by_trade_date: dict[date, set[date]] = {}
    for row in recommendations:
        signal_date = _as_date(row.get("trade_date"))
        if signal_date:
            recommendations_by_signal_date.setdefault(signal_date, []).append(row)
    for row in signals:
        trade_date = _as_date(row.get("trade_date") or row.get("execute_date"))
        if not trade_date:
            continue
        signals_by_trade_date.setdefault(trade_date, []).append(row)
        signal_date = _as_date(row.get("signal_date"))
        if signal_date:
            signal_dates_by_trade_date.setdefault(trade_date, set()).add(signal_date)
    for row in orders:
        trade_date = _as_date(row.get("trade_date"))
        if trade_date:
            orders_by_trade_date.setdefault(trade_date, []).append(row)
    for row in trades:
        trade_date = _as_date(row.get("trade_date"))
        if trade_date:
            trades_by_trade_date.setdefault(trade_date, []).append(row)
    for signal_date in recommendations_by_signal_date:
        if any(signal_date in dates for dates in signal_dates_by_trade_date.values()):
            continue
        execute_date = next_trading_day.get(signal_date)
        if execute_date:
            signal_dates_by_trade_date.setdefault(execute_date, set()).add(signal_date)

    position_count_by_date = {
        parsed: int(row.get("position_snapshot_count") or row.get("count") or 0)
        for row in position_counts or []
        if (parsed := _as_date(row.get("trade_date")))
    }
    equity_by_date = {parsed: row for row in equity_rows if (parsed := _as_date(row.get("trade_date")))}
    all_dates = set(equity_by_date)
    all_dates.update(signals_by_trade_date)
    all_dates.update(orders_by_trade_date)
    all_dates.update(trades_by_trade_date)
    all_dates.update(signal_dates_by_trade_date)

    result = []
    for trade_date in sorted(all_dates):
        source_signal_dates = sorted(signal_dates_by_trade_date.get(trade_date) or [])
        source_recommendations = [
            row
            for signal_date in source_signal_dates
            for row in recommendations_by_signal_date.get(signal_date, [])
        ]
        day_signals = signals_by_trade_date.get(trade_date, [])
        day_orders = orders_by_trade_date.get(trade_date, [])
        day_trades = trades_by_trade_date.get(trade_date, [])
        summary = daily_decision_summary(source_recommendations, day_signals, day_orders, day_trades)
        equity = equity_by_date.get(trade_date) or {}
        result.append(
            {
                "trade_date": trade_date,
                "cash": equity.get("cash"),
                "market_value": equity.get("market_value"),
                "total_equity": equity.get("total_equity"),
                "drawdown_pct": equity.get("drawdown_pct"),
                "position_count": int(equity.get("position_count") or 0),
                "position_snapshot_count": position_count_by_date.get(trade_date, 0),
                "source_signal_dates": source_signal_dates,
                **summary,
            }
        )
    return result


def trade_attribution(trades: list[dict[str, Any]], positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return per-lot realized/open attribution with position path extremes."""

    positions_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in positions:
        positions_by_symbol.setdefault(str(row.get("vt_symbol") or ""), []).append(row)
    for rows in positions_by_symbol.values():
        rows.sort(key=lambda item: str(item.get("trade_date") or ""))

    open_trades: dict[str, list[dict[str, Any]]] = {}
    result: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda item: (str(item.get("trade_date") or ""), int(item.get("id") or 0))):
        vt_symbol = str(trade.get("vt_symbol") or "")
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            open_trades.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_trades.setdefault(vt_symbol, []).pop(0) if open_trades.get(vt_symbol) else None
        result.append(_attribution_row(vt_symbol, entry, trade, positions_by_symbol.get(vt_symbol, []), status="closed"))

    for vt_symbol, rows in open_trades.items():
        for entry in rows:
            result.append(_attribution_row(vt_symbol, entry, None, positions_by_symbol.get(vt_symbol, []), status="open"))

    result.sort(key=lambda item: (str(item.get("entry_date") or ""), str(item.get("vt_symbol") or "")), reverse=True)
    return result


def trade_path_diagnostic_row(
    vt_symbol: str,
    entry: dict[str, Any],
    exit_trade: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    future_bars: list[dict[str, Any]] | None = None,
    *,
    lookahead_days: int = 10,
    daily_bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one closed trade's visible holding path plus post-exit rebound."""

    entry_date = _as_date(entry.get("trade_date"))
    exit_date = _as_date((exit_trade or {}).get("trade_date"))
    path = [
        row
        for row in positions
        if str(row.get("vt_symbol") or "") == vt_symbol
        and (entry_date is None or (_as_date(row.get("trade_date")) or date.min) >= entry_date)
        and (exit_date is None or (_as_date(row.get("trade_date")) or date.max) <= exit_date)
    ]
    path.sort(key=lambda row: _as_date(row.get("trade_date")) or date.min)
    future_path = [
        row
        for row in future_bars or []
        if str(row.get("vt_symbol") or "") == vt_symbol
        and _is_within_lookahead(_as_date(row.get("trade_date")), exit_date, lookahead_days)
    ]
    entry_raw = _entry_raw_payload(entry)
    entry_price = _safe_float(entry.get("price"))
    exit_price = _safe_float((exit_trade or {}).get("price"))
    future_closes = [value for row in future_path if (value := _safe_float(row.get("close_price"))) is not None]
    post_exit_max_return_pct = None
    if exit_price and future_closes:
        post_exit_max_return_pct = round((max(future_closes) / exit_price - 1) * 100, 4)

    return_pct = None
    if entry_price and exit_price:
        return_pct = (exit_price / entry_price - 1) * 100
    follow_through = _early_follow_through_diagnostic(path)
    mae_pct = _min_number(row.get("floating_pnl_pct") for row in path)
    mfe_pct = _max_number(row.get("floating_pnl_pct") for row in path)
    signal_bar_context = _sell_signal_bar_context(vt_symbol, exit_date, daily_bars or [])
    review = _rebound_prone_support_stop_review(
        exit_reason=(exit_trade or {}).get("reason"),
        mfe_pct=mfe_pct,
        early_mfe_pct=follow_through.get("early_mfe_pct"),
        early_follow_through_state=follow_through.get("early_follow_through_state"),
        signal_intraday_range_pct=signal_bar_context.get("sell_signal_intraday_range_pct"),
    )
    return {
        "vt_symbol": vt_symbol,
        "name": (entry or exit_trade or {}).get("name"),
        "board": (entry or exit_trade or {}).get("board"),
        "board_label": (entry or exit_trade or {}).get("board_label"),
        "entry_trade_id": entry.get("id"),
        "exit_trade_id": (exit_trade or {}).get("id"),
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_amount": _safe_float(entry.get("amount")),
        "exit_amount": _safe_float((exit_trade or {}).get("amount")),
        "pnl": _safe_float((exit_trade or {}).get("pnl")),
        "entry_setup": entry_raw.get("entry_setup") or entry_raw.get("setup_type"),
        "entry_score": _entry_raw_number(entry_raw, "entry_total_score", "total_score", "score"),
        "low_suction_days": _entry_raw_number(entry_raw, "low_suction_days"),
        "low_suction_buildup_score": _entry_raw_number(entry_raw, "low_suction_buildup_score"),
        "stealth_low_suction_score": _entry_raw_number(entry_raw, "stealth_low_suction_score"),
        "low_suction_launch_confirmed": bool(entry_raw.get("low_suction_launch_confirmed")),
        "low_suction_launch_quality_bucket": entry_raw.get("low_suction_launch_quality_bucket"),
        "low_suction_launch_quality_label": entry_raw.get("low_suction_launch_quality_label"),
        "low_suction_dragon_state": entry_raw.get("low_suction_dragon_state"),
        "low_suction_dragon_label": entry_raw.get("low_suction_dragon_label"),
        "low_suction_dragon_conflict": bool(entry_raw.get("low_suction_dragon_conflict")),
        "low_suction_dragon_conflict_level": entry_raw.get("low_suction_dragon_conflict_level"),
        "low_suction_dragon_notes": entry_raw.get("low_suction_dragon_notes") if isinstance(entry_raw.get("low_suction_dragon_notes"), list) else [],
        "ma_convergence_pct": _entry_raw_number(entry_raw, "ma_convergence_pct"),
        "volume_ratio_5d_20d": _entry_raw_number(entry_raw, "volume_ratio_5d_20d"),
        "support_hold_days": _entry_raw_number(entry_raw, "support_hold_days"),
        "pullback_days": _entry_raw_number(entry_raw, "pullback_days"),
        "drawdown_from_pivot_pct": _entry_raw_number(entry_raw, "drawdown_from_pivot_pct"),
        "close_location_in_range": _entry_raw_number(entry_raw, "close_location_in_range"),
        "ma5_distance_pct": _entry_raw_number(entry_raw, "ma5_distance_pct"),
        "ma10_distance_pct": _entry_raw_number(entry_raw, "ma10_distance_pct"),
        "ma20_distance_pct": _entry_raw_number(entry_raw, "ma20_distance_pct"),
        "fresh_tail_buy": bool(entry_raw.get("fresh_tail_buy")),
        "tail_buy_repeat_days": _entry_raw_number(entry_raw, "tail_buy_repeat_days"),
        "recent_limit_up_20d": bool(entry_raw.get("recent_limit_up_20d")),
        "large_bull_count_20d": _entry_raw_number(entry_raw, "large_bull_count_20d"),
        "near_limit_up_count_20d": _entry_raw_number(entry_raw, "near_limit_up_count_20d"),
        "consecutive_bull_closes": _entry_raw_number(entry_raw, "consecutive_bull_closes"),
        "upward_gap_in_leg": bool(entry_raw.get("upward_gap_in_leg")),
        "persistent_volume_expansion": bool(entry_raw.get("persistent_volume_expansion")),
        "limit_up_start_factor_count": _entry_raw_number(entry_raw, "limit_up_start_factor_count"),
        "weak_index_strength_confirmation": bool(entry_raw.get("weak_index_strength_confirmation")),
        "index_return_20d": _entry_raw_number(entry_raw, "index_return_20d"),
        "early_dragon_pullback_risk": bool(entry_raw.get("early_dragon_pullback_risk")),
        "exit_reason": (exit_trade or {}).get("reason"),
        "exit_reason_label": reason_label((exit_trade or {}).get("reason")),
        "return_pct": round(return_pct, 4) if return_pct is not None else None,
        "mae_pct": mae_pct,
        "mfe_pct": mfe_pct,
        **follow_through,
        **signal_bar_context,
        **review,
        "post_exit_max_return_pct": post_exit_max_return_pct,
        "sold_before_rebound": bool(post_exit_max_return_pct is not None and post_exit_max_return_pct >= 8.0),
    }


def _sell_signal_bar_context(
    vt_symbol: str,
    exit_date: date | None,
    daily_bars: list[dict[str, Any]],
) -> dict[str, Any]:
    if exit_date is None or not daily_bars:
        return {}
    symbol_bars = [row for row in daily_bars if str(row.get("vt_symbol") or "") == vt_symbol]
    symbol_bars.sort(key=lambda row: _as_date(row.get("trade_date")) or date.min)
    exit_index = next(
        (index for index, row in enumerate(symbol_bars) if _as_date(row.get("trade_date")) == exit_date),
        None,
    )
    if exit_index is None or exit_index <= 0:
        return {}
    signal_bar = symbol_bars[exit_index - 1]
    previous_bar = symbol_bars[exit_index - 2] if exit_index >= 2 else None
    open_price = _safe_float(signal_bar.get("open_price"))
    close_price = _safe_float(signal_bar.get("close_price"))
    high_price = _safe_float(signal_bar.get("high_price"))
    low_price = _safe_float(signal_bar.get("low_price"))
    if not all(value is not None for value in (open_price, close_price, high_price, low_price)) or not close_price:
        return {}
    bar_range = high_price - low_price
    context = {
        "sell_signal_date": _as_date(signal_bar.get("trade_date")),
        "sell_signal_change_pct": _safe_float(signal_bar.get("change_pct")),
        "sell_signal_body_pct": (close_price / open_price - 1) * 100 if open_price else None,
        "sell_signal_intraday_range_pct": bar_range / close_price * 100 if close_price else None,
        "sell_signal_close_location": (close_price - low_price) / bar_range if bar_range else None,
        "sell_signal_lower_shadow_pct": (min(open_price, close_price) - low_price) / close_price * 100,
        "sell_signal_upper_shadow_pct": (high_price - max(open_price, close_price)) / close_price * 100,
    }
    previous_close = _safe_float((previous_bar or {}).get("close_price"))
    if previous_close:
        context["sell_signal_gap_pct"] = (open_price / previous_close - 1) * 100 if open_price else None
        context["sell_signal_close_vs_prev_pct"] = (close_price / previous_close - 1) * 100
    return {key: (round(value, 4) if isinstance(value, float) else value) for key, value in context.items()}


def _rebound_prone_support_stop_review(
    *,
    exit_reason: Any,
    mfe_pct: float | None,
    early_mfe_pct: float | None,
    early_follow_through_state: Any,
    signal_intraday_range_pct: float | None,
) -> dict[str, Any]:
    if str(exit_reason or "") != "support_stop":
        return {"rebound_prone_support_stop_review": False, "rebound_prone_support_stop_score": 0.0, "rebound_prone_support_stop_notes": []}
    score = 0.0
    notes: list[str] = []
    if early_mfe_pct is not None and early_mfe_pct >= 0:
        score += 35.0
        notes.append("买后曾有承接/MFE")
    if mfe_pct is not None and 0 <= mfe_pct <= 3.0:
        score += 30.0
        notes.append("持仓曾小幅浮盈但未打开空间")
    elif mfe_pct is not None and mfe_pct >= 3.0:
        score += 20.0
        notes.append("持仓路径曾有明显 MFE")
    if str(early_follow_through_state or "") == "confirmed_follow_through":
        score += 20.0
        notes.append("早期跟随确认")
    elif str(early_follow_through_state or "") == "weak_follow_through":
        score += 10.0
        notes.append("早期弱跟随")
    if signal_intraday_range_pct is not None and signal_intraday_range_pct >= 5.0:
        score += 25.0
        notes.append("卖出信号日宽幅恐慌")
    score = min(score, 100.0)
    return {
        "rebound_prone_support_stop_review": score >= 60.0,
        "rebound_prone_support_stop_score": round(score, 4),
        "rebound_prone_support_stop_notes": notes,
    }


def trade_path_diagnostics_from_trades(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    future_bars: list[dict[str, Any]],
    *,
    lookahead_days: int = 10,
    daily_bars: list[dict[str, Any]] | None = None,
    replacement_trades: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    positions_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in positions:
        positions_by_symbol.setdefault(str(row.get("vt_symbol") or ""), []).append(row)
    daily_bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in daily_bars or []:
        daily_bars_by_symbol.setdefault(str(row.get("vt_symbol") or ""), []).append(row)
    future_bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in future_bars or []:
        future_bars_by_symbol.setdefault(str(row.get("vt_symbol") or ""), []).append(row)

    open_trades: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda item: (str(item.get("trade_date") or ""), int(item.get("id") or 0))):
        vt_symbol = str(trade.get("vt_symbol") or "")
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            open_trades.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_trades.setdefault(vt_symbol, []).pop(0) if open_trades.get(vt_symbol) else None
        if entry is None:
            continue
        rows.append(
            trade_path_diagnostic_row(
                vt_symbol,
                entry,
                trade,
                positions_by_symbol.get(vt_symbol, []),
                future_bars_by_symbol.get(vt_symbol, []),
                lookahead_days=lookahead_days,
                daily_bars=daily_bars_by_symbol.get(vt_symbol, []),
            )
        )
    return _attach_replacement_trade_quality(rows, replacement_trades or trades)


def low_suction_confirmed_path_item(
    entry: dict[str, Any],
    exit_trade: dict[str, Any] | None,
    daily_bars: list[dict[str, Any]],
    *,
    lookahead_days: int = 20,
) -> dict[str, Any]:
    """Compare actual exit against fixed-hold and low-suction-specific exit proxies."""

    vt_symbol = str(entry.get("vt_symbol") or "")
    entry_date = _as_date(entry.get("trade_date"))
    exit_date = _as_date((exit_trade or {}).get("trade_date"))
    entry_price = _safe_float(entry.get("price"))
    exit_price = _safe_float((exit_trade or {}).get("price"))
    entry_raw = _entry_raw_payload(entry)
    path = [
        row
        for row in daily_bars
        if str(row.get("vt_symbol") or "") == vt_symbol
        and (entry_date is None or (_as_date(row.get("trade_date")) or date.min) >= entry_date)
    ]
    path.sort(key=lambda row: _as_date(row.get("trade_date")) or date.min)
    path = path[: max(lookahead_days, 1) + 1]
    path_metrics = _low_suction_forward_path_metrics(path, entry_price)
    failed_exit = _low_suction_failed_follow_exit(path, entry_price)
    trend_exit = _low_suction_trend_giveback_exit(path, entry_price)
    model_exit = failed_exit if failed_exit.get("triggered") else trend_exit
    model_return = _safe_float(model_exit.get("return_pct"))
    current_return = (exit_price / entry_price - 1) * 100 if entry_price and exit_price else None
    return {
        "vt_symbol": vt_symbol,
        "name": entry.get("name"),
        "entry_trade_id": entry.get("id"),
        "exit_trade_id": (exit_trade or {}).get("id"),
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_amount": _safe_float(entry.get("amount")),
        "pnl": _safe_float((exit_trade or {}).get("pnl")),
        "current_exit_reason": (exit_trade or {}).get("reason"),
        "current_exit_reason_label": reason_label((exit_trade or {}).get("reason")),
        "current_exit_return_pct": round(current_return, 4) if current_return is not None else None,
        "entry_setup": entry_raw.get("entry_setup") or entry_raw.get("setup_type"),
        "entry_score": _entry_raw_number(entry_raw, "entry_total_score", "total_score", "score"),
        "low_suction_days": _entry_raw_number(entry_raw, "low_suction_days"),
        "low_suction_launch_quality_bucket": entry_raw.get("low_suction_launch_quality_bucket"),
        "low_suction_launch_quality_label": entry_raw.get("low_suction_launch_quality_label"),
        "trigger_day_confirmation": entry_raw.get("trigger_day_confirmation")
        if isinstance(entry_raw.get("trigger_day_confirmation"), dict)
        else {},
        "execution_mode": _entry_execution_mode(entry),
        **path_metrics,
        "failed_follow_exit": failed_exit,
        "failed_follow_exit_triggered": bool(failed_exit.get("triggered")),
        "failed_follow_exit_return_pct": failed_exit.get("return_pct"),
        "trend_giveback_exit": trend_exit,
        "trend_giveback_exit_triggered": bool(trend_exit.get("triggered")),
        "trend_giveback_exit_return_pct": trend_exit.get("return_pct"),
        "low_suction_model_exit_type": model_exit.get("exit_type"),
        "low_suction_model_exit_label": model_exit.get("exit_label"),
        "low_suction_model_exit_date": model_exit.get("exit_date"),
        "low_suction_model_return_pct": model_return,
        "model_vs_current_delta_pct": round(model_return - current_return, 4)
        if model_return is not None and current_return is not None
        else None,
        "audit_only": True,
        "not_used_for_signal_score": True,
    }


def low_suction_confirmed_path_audit_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "audit_only": True,
        "not_used_for_signal_score": True,
        "overall": _low_suction_confirmed_metric_summary(rows),
        "by_year": _group_low_suction_confirmed_metrics(rows, "entry_year", _entry_year_bucket),
        "by_dynamic_market_regime": _group_low_suction_confirmed_metrics(rows, "dynamic_market_regime", _dynamic_market_label_for_bucket),
        "by_market_warning": _group_low_suction_confirmed_metrics(rows, "market_warning_label", lambda value, _rows: str(value or "未知风险")),
        "by_low_suction_launch_quality": _group_low_suction_confirmed_metrics(
            rows,
            "low_suction_launch_quality_bucket",
            _low_suction_launch_quality_label_for_bucket,
        ),
        "by_model_exit_type": _group_low_suction_confirmed_metrics(rows, "low_suction_model_exit_type", _low_suction_model_exit_label),
        "read": _low_suction_confirmed_path_read(rows),
    }


def _confirmed_low_suction_trade_pairs(trades: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    open_trades: dict[str, list[dict[str, Any]]] = {}
    pairs: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for trade in sorted(trades, key=_trade_sort_key):
        vt_symbol = str(trade.get("vt_symbol") or "")
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            open_trades.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_trades.setdefault(vt_symbol, []).pop(0) if open_trades.get(vt_symbol) else None
        if entry is not None and _entry_execution_mode(entry) == "low_suction_trigger_day_confirmed_next_open":
            pairs.append((entry, trade))
    for entries in open_trades.values():
        for entry in entries:
            if _entry_execution_mode(entry) == "low_suction_trigger_day_confirmed_next_open":
                pairs.append((entry, None))
    pairs.sort(key=lambda pair: _trade_sort_key(pair[0]))
    return pairs


def _daily_bars_for_confirmed_low_suction_entries(
    session: Any,
    schema: Any,
    entries: list[dict[str, Any]],
    *,
    lookahead_days: int,
    to_api: ApiMapper,
) -> list[dict[str, Any]]:
    if not entries:
        return []
    symbols = sorted({str(entry.get("vt_symbol") or "") for entry in entries if entry.get("vt_symbol")})
    entry_dates = [parsed for entry in entries if (parsed := _as_date(entry.get("trade_date")))]
    if not symbols or not entry_dates:
        return []
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(symbols))
        .where(schema.stock_daily_bars.c.trade_date >= min(entry_dates))
        .where(schema.stock_daily_bars.c.trade_date <= max(entry_dates) + timedelta(days=lookahead_days + 20))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    return [to_api(dict(row)) for row in rows]


def _entry_execution_mode(entry: dict[str, Any]) -> str:
    raw = entry.get("raw") if isinstance(entry.get("raw"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    return str(execution.get("mode") or raw.get("mode") or "")


def _low_suction_forward_path_metrics(path: list[dict[str, Any]], entry_price: float | None) -> dict[str, Any]:
    returns = [_bar_close_return(row, entry_price) for row in path]
    highs = [_bar_high_return(row, entry_price) for row in path]
    lows = [_bar_low_return(row, entry_price) for row in path]
    clean_returns = [value for value in returns if value is not None]
    clean_highs = [value for value in highs if value is not None]
    clean_lows = [value for value in lows if value is not None]
    return {
        "forward_bar_count": len(path),
        "fixed_5d_return_pct": _fixed_path_return(path, entry_price, 5),
        "fixed_10d_return_pct": _fixed_path_return(path, entry_price, 10),
        "fixed_20d_return_pct": _fixed_path_return(path, entry_price, 20),
        "forward_mfe_pct": round(max(clean_highs), 4) if clean_highs else None,
        "forward_mae_pct": round(min(clean_lows), 4) if clean_lows else None,
        "forward_last_return_pct": round(clean_returns[-1], 4) if clean_returns else None,
        "opened_space": bool(clean_highs and max(clean_highs) >= 6.0),
    }


def _low_suction_failed_follow_exit(path: list[dict[str, Any]], entry_price: float | None) -> dict[str, Any]:
    early_path = path[:3]
    best_high = None
    for row in early_path:
        high_return = _bar_high_return(row, entry_price)
        low_return = _bar_low_return(row, entry_price)
        close_return = _bar_close_return(row, entry_price)
        trade_date = _as_date(row.get("trade_date"))
        best_high = high_return if best_high is None else max(best_high, high_return if high_return is not None else best_high)
        no_lift = best_high is None or best_high < 2.0
        if no_lift and low_return is not None and low_return <= -3.5:
            return _low_suction_exit_payload("failed_follow", "没拉起来破位撤", trade_date, close_return)
        if no_lift and close_return is not None and close_return <= -2.5:
            return _low_suction_exit_payload("failed_follow", "没拉起来弱收撤", trade_date, close_return)
    last_return = _bar_close_return(early_path[-1], entry_price) if early_path else None
    return _low_suction_exit_payload("hold", "未触发失败启动退出", _as_date(early_path[-1].get("trade_date")) if early_path else None, last_return, triggered=False)


def _low_suction_trend_giveback_exit(path: list[dict[str, Any]], entry_price: float | None) -> dict[str, Any]:
    peak_return: float | None = None
    fallback = _low_suction_exit_payload(
        "fixed_20d_or_last",
        "未触发趋势回撤，持有到观察终点",
        _as_date(path[-1].get("trade_date")) if path else None,
        _bar_close_return(path[-1], entry_price) if path else None,
        triggered=False,
    )
    for row in path:
        high_return = _bar_high_return(row, entry_price)
        close_return = _bar_close_return(row, entry_price)
        trade_date = _as_date(row.get("trade_date"))
        if high_return is not None:
            peak_return = high_return if peak_return is None else max(peak_return, high_return)
        if peak_return is None or close_return is None:
            continue
        if peak_return >= 8.0 and peak_return - close_return >= 5.0 and close_return <= 4.0:
            return _low_suction_exit_payload("trend_giveback", "拉起后高位回撤卖", trade_date, close_return)
        if peak_return >= 15.0 and peak_return - close_return >= 8.0:
            return _low_suction_exit_payload("trend_giveback", "大幅浮盈回吐卖", trade_date, close_return)
    return fallback


def _low_suction_exit_payload(
    exit_type: str,
    exit_label: str,
    exit_date: date | None,
    return_pct: float | None,
    *,
    triggered: bool = True,
) -> dict[str, Any]:
    return {
        "triggered": triggered,
        "exit_type": exit_type,
        "exit_label": exit_label,
        "exit_date": exit_date,
        "return_pct": round(return_pct, 4) if return_pct is not None else None,
    }


def _fixed_path_return(path: list[dict[str, Any]], entry_price: float | None, days: int) -> float | None:
    if not path:
        return None
    index = min(max(days - 1, 0), len(path) - 1)
    return_value = _bar_close_return(path[index], entry_price)
    return round(return_value, 4) if return_value is not None else None


def _bar_close_return(row: dict[str, Any], entry_price: float | None) -> float | None:
    close_price = _safe_float(row.get("close_price"))
    return (close_price / entry_price - 1) * 100 if entry_price and close_price else None


def _bar_high_return(row: dict[str, Any], entry_price: float | None) -> float | None:
    high_price = _safe_float(row.get("high_price"))
    return (high_price / entry_price - 1) * 100 if entry_price and high_price else None


def _bar_low_return(row: dict[str, Any], entry_price: float | None) -> float | None:
    low_price = _safe_float(row.get("low_price"))
    return (low_price / entry_price - 1) * 100 if entry_price and low_price else None


def _low_suction_confirmed_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current_returns = [value for row in rows if (value := _safe_float(row.get("current_exit_return_pct"))) is not None]
    fixed5 = [value for row in rows if (value := _safe_float(row.get("fixed_5d_return_pct"))) is not None]
    fixed10 = [value for row in rows if (value := _safe_float(row.get("fixed_10d_return_pct"))) is not None]
    fixed20 = [value for row in rows if (value := _safe_float(row.get("fixed_20d_return_pct"))) is not None]
    model_returns = [value for row in rows if (value := _safe_float(row.get("low_suction_model_return_pct"))) is not None]
    deltas = [value for row in rows if (value := _safe_float(row.get("model_vs_current_delta_pct"))) is not None]
    return {
        "trade_count": len(rows),
        "current_exit": _return_series_summary(current_returns),
        "fixed_5d": _return_series_summary(fixed5),
        "fixed_10d": _return_series_summary(fixed10),
        "fixed_20d": _return_series_summary(fixed20),
        "low_suction_model": _return_series_summary(model_returns),
        "avg_model_vs_current_delta_pct": _avg(deltas),
        "positive_model_delta_count": sum(1 for value in deltas if value > 0),
        "failed_follow_exit_count": sum(1 for row in rows if row.get("failed_follow_exit_triggered")),
        "trend_giveback_exit_count": sum(1 for row in rows if row.get("trend_giveback_exit_triggered")),
        "opened_space_count": sum(1 for row in rows if row.get("opened_space")),
        "avg_forward_mae_pct": _avg(row.get("forward_mae_pct") for row in rows),
        "avg_forward_mfe_pct": _avg(row.get("forward_mfe_pct") for row in rows),
    }


def _return_series_summary(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    return {
        "evaluated_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(values) * 100 if values else None,
        "avg_return_pct": _avg(values),
        "median_return_pct": median(values) if values else None,
        "total_return_pct": sum(values) if values else None,
    }


def _group_low_suction_confirmed_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    values: dict[str, Any] = {}
    for row in rows:
        item = dict(row)
        if key == "entry_year":
            item[key] = _as_date(item.get("entry_date")).year if _as_date(item.get("entry_date")) else None
        raw_value = item.get(key) or "unknown"
        group_key = str(raw_value)
        groups.setdefault(group_key, []).append(item)
        values.setdefault(group_key, raw_value)
    result = []
    for group_key, bucket_rows in groups.items():
        result.append(
            {
                key: None if group_key == "unknown" else values[group_key],
                "label": labeler(values[group_key], bucket_rows),
                **_low_suction_confirmed_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (-int(item.get("trade_count") or 0), _sort_number(item["current_exit"].get("avg_return_pct"), default=10**18)))
    return result


def _entry_year_bucket(value: Any, _rows: list[dict[str, Any]]) -> str:
    return str(value or "未知年份")


def _low_suction_model_exit_label(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("low_suction_model_exit_label"):
            return str(row["low_suction_model_exit_label"])
    labels = {
        "failed_follow": "没拉起来撤",
        "trend_giveback": "拉起后回撤卖",
        "fixed_20d_or_last": "观察期持有",
        "hold": "继续持有",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _low_suction_launch_quality_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("low_suction_launch_quality_label"):
            return str(row["low_suction_launch_quality_label"])
    return low_suction_launch_quality_label(value)


def _low_suction_confirmed_path_read(rows: list[dict[str, Any]]) -> dict[str, Any]:
    overall = _low_suction_confirmed_metric_summary(rows)
    current_avg = _safe_float(overall["current_exit"].get("avg_return_pct"))
    fixed20_avg = _safe_float(overall["fixed_20d"].get("avg_return_pct"))
    model_avg = _safe_float(overall["low_suction_model"].get("avg_return_pct"))
    notes = []
    if fixed20_avg is not None and current_avg is not None and fixed20_avg > current_avg:
        notes.append("固定 20 日观察优于当前卖点，说明当前卖点可能兑现不足。")
    if model_avg is not None and current_avg is not None and model_avg > current_avg:
        notes.append("低吸专用失败/回撤模型优于当前卖点代理，值得进入下一轮默认关闭实验。")
    if overall["failed_follow_exit_count"]:
        notes.append("存在没拉起来就破位的样本，需要失败启动风控。")
    if overall["trend_giveback_exit_count"]:
        notes.append("存在拉起后回吐样本，需要趋势回撤卖点。")
    if not notes:
        notes.append("当前样本没有证明低吸专用卖点优于默认卖点。")
    return {
        "current_exit_avg_return_pct": current_avg,
        "fixed_20d_avg_return_pct": fixed20_avg,
        "low_suction_model_avg_return_pct": model_avg,
        "notes": notes,
    }


def _attach_replacement_trade_quality(rows: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    closed_by_entry_id = _closed_trade_rows_by_entry_id(trades)
    closed_by_entry_id.update({row.get("entry_trade_id"): row for row in rows if row.get("entry_trade_id") is not None})
    sorted_buys = [
        trade
        for trade in sorted(trades, key=_trade_sort_key)
        if str(trade.get("side") or "").upper() == "BUY"
    ]
    buy_index = 0
    for row in sorted(rows, key=lambda item: (_as_date(item.get("exit_date")) or date.max, int(item.get("exit_trade_id") or 0))):
        exit_trade_id = row.get("exit_trade_id")
        if exit_trade_id is None:
            row.update(_replacement_quality_payload(None, None, row))
            continue
        exit_key = (_as_date(row.get("exit_date")) or date.min, int(exit_trade_id or 0))
        while buy_index < len(sorted_buys) and _trade_sort_key(sorted_buys[buy_index]) <= exit_key:
            buy_index += 1
        if buy_index >= len(sorted_buys):
            row.update(_replacement_quality_payload(None, None, row))
            continue
        replacement = sorted_buys[buy_index]
        buy_index += 1
        row.update(_replacement_quality_payload(replacement, closed_by_entry_id.get(replacement.get("id")), row))
    return rows


def _replacement_quality_payload(
    replacement_entry: dict[str, Any] | None,
    replacement_closed_row: dict[str, Any] | None,
    source_row: dict[str, Any],
) -> dict[str, Any]:
    if replacement_entry is None:
        return {
            "replacement_status": "none",
            "replacement_outcome": "no_replacement",
            "replacement_outcome_label": "未释放到后续买入",
        }
    raw = _entry_raw_payload(replacement_entry)
    replacement_return = _safe_float((replacement_closed_row or {}).get("return_pct"))
    source_return = _safe_float(source_row.get("return_pct"))
    delta = replacement_return - source_return if replacement_return is not None and source_return is not None else None
    outcome, label = _replacement_outcome(replacement_return)
    return {
        "replacement_status": "closed" if replacement_closed_row else "open",
        "replacement_trade_id": replacement_entry.get("id"),
        "replacement_vt_symbol": replacement_entry.get("vt_symbol"),
        "replacement_name": replacement_entry.get("name"),
        "replacement_entry_date": _as_date(replacement_entry.get("trade_date")),
        "replacement_entry_price": _safe_float(replacement_entry.get("price")),
        "replacement_entry_setup": raw.get("entry_setup") or raw.get("setup_type"),
        "replacement_entry_score": _entry_raw_number(raw, "entry_total_score", "total_score", "score"),
        "replacement_exit_date": (replacement_closed_row or {}).get("exit_date"),
        "replacement_exit_reason": (replacement_closed_row or {}).get("exit_reason"),
        "replacement_exit_reason_label": (replacement_closed_row or {}).get("exit_reason_label"),
        "replacement_return_pct": replacement_return,
        "replacement_pnl": _safe_float((replacement_closed_row or {}).get("pnl")),
        "replacement_return_delta_pct": round(delta, 4) if delta is not None else None,
        "replacement_outcome": outcome,
        "replacement_outcome_label": label,
    }


def _replacement_outcome(return_pct: float | None) -> tuple[str, str]:
    if return_pct is None:
        return "open_replacement", "替换持仓未闭合"
    if return_pct >= 8.0:
        return "strong_replacement", "替换买入强盈利"
    if return_pct > 0:
        return "profitable_replacement", "替换买入盈利"
    if return_pct <= -5.0:
        return "bad_replacement", "替换买入亏损"
    return "weak_replacement", "替换买入弱表现"


def _closed_trade_rows_by_entry_id(trades: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    open_trades: dict[str, list[dict[str, Any]]] = {}
    result: dict[Any, dict[str, Any]] = {}
    for trade in sorted(trades, key=_trade_sort_key):
        vt_symbol = str(trade.get("vt_symbol") or "")
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            open_trades.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_trades.setdefault(vt_symbol, []).pop(0) if open_trades.get(vt_symbol) else None
        if entry is None:
            continue
        entry_price = _safe_float(entry.get("price"))
        exit_price = _safe_float(trade.get("price"))
        return_pct = (exit_price / entry_price - 1) * 100 if entry_price and exit_price else None
        result[entry.get("id")] = {
            "vt_symbol": vt_symbol,
            "entry_trade_id": entry.get("id"),
            "exit_trade_id": trade.get("id"),
            "entry_date": _as_date(entry.get("trade_date")),
            "exit_date": _as_date(trade.get("trade_date")),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "exit_reason": trade.get("reason"),
            "exit_reason_label": reason_label(trade.get("reason")),
            "return_pct": round(return_pct, 4) if return_pct is not None else None,
            "pnl": _safe_float(trade.get("pnl")),
            "raw": entry.get("raw") if isinstance(entry.get("raw"), dict) else {},
        }
    return result


def _trade_sort_key(trade: dict[str, Any]) -> tuple[date, int]:
    return (_as_date(trade.get("trade_date")) or date.min, int(trade.get("id") or 0))


def trade_path_diagnostics_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = [_with_path_issue(row) for row in rows]
    losses = [row for row in rows if _safe_float(row.get("return_pct")) is not None and float(row["return_pct"]) < 0]
    rebounds = [row for row in rows if row.get("sold_before_rebound")]
    mae_values = [value for row in rows if (value := _safe_float(row.get("mae_pct"))) is not None]
    mfe_values = [value for row in rows if (value := _safe_float(row.get("mfe_pct"))) is not None]
    replacement_returns = [value for row in rows if (value := _safe_float(row.get("replacement_return_pct"))) is not None]
    replacement_deltas = [value for row in rows if (value := _safe_float(row.get("replacement_return_delta_pct"))) is not None]
    return {
        "trade_count": len(rows),
        "loss_count": len(losses),
        "sold_before_rebound_count": len(rebounds),
        "rebound_prone_support_stop_review_count": sum(1 for row in rows if row.get("rebound_prone_support_stop_review")),
        "replacement_trade_count": sum(1 for row in rows if row.get("replacement_trade_id") is not None),
        "bad_replacement_count": sum(1 for row in rows if row.get("replacement_outcome") == "bad_replacement"),
        "strong_replacement_count": sum(1 for row in rows if row.get("replacement_outcome") == "strong_replacement"),
        "avg_replacement_return_pct": _avg(replacement_returns),
        "avg_replacement_return_delta_pct": _avg(replacement_deltas),
        "by_replacement_outcome": _group_path_metrics(enriched, "replacement_outcome", _replacement_outcome_label_for_bucket),
        "by_dynamic_market_regime": _group_path_metrics(enriched, "dynamic_market_regime", _dynamic_market_label_for_bucket),
        "by_market_warning": _group_path_metrics(enriched, "market_warning_label", lambda value, _rows: str(value or "未知")),
        "by_entry_context": _group_path_metrics(enriched, "entry_context_state", _entry_context_label_for_bucket),
        "by_short_term_trade_context": _group_path_metrics(
            enriched,
            "short_term_trade_context",
            _short_term_trade_context_label_for_bucket,
        ),
        "by_market_mainline_trade_context": _group_path_metrics(
            enriched,
            "market_mainline_trade_context",
            _market_mainline_trade_context_label_for_bucket,
        ),
        "by_entry_launch_diagnostic": _group_path_metrics(
            enriched,
            "entry_launch_diagnostic_state",
            _entry_launch_diagnostic_label_for_bucket,
        ),
        "by_low_suction_dragon_context": _group_path_metrics(
            enriched,
            "low_suction_dragon_state",
            _low_suction_dragon_context_label_for_bucket,
        ),
        "by_fund_flow_coverage": _group_path_metrics(enriched, "fund_flow_coverage_state", _fund_flow_coverage_label_for_bucket),
        "dynamic_market_sources": _top_candidate_dynamic_market_sources(rows),
        "avg_mae_pct": sum(mae_values) / len(mae_values) if mae_values else None,
        "avg_mfe_pct": sum(mfe_values) / len(mfe_values) if mfe_values else None,
    }


def _normalize_path_row_dates(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["entry_date"] = _as_date(item.get("entry_date"))
    item["exit_date"] = _as_date(item.get("exit_date"))
    return item


def _with_path_issue(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if not item.get("early_follow_through_state"):
        item.update(_early_follow_through_from_metrics(item))
    item["giveback_pct"] = _path_giveback_pct(item)
    issue_type, issue_label = _classify_path_issue(item)
    item["path_issue_type"] = issue_type
    item["path_issue_label"] = issue_label
    item.update(_entry_context_marker(item))
    item.update(_entry_launch_diagnostic_marker(item))
    item.update(_low_suction_dragon_context_marker(item))
    item.update(_fund_flow_coverage_marker(item))
    item.update(_market_mainline_trade_context_marker(item))
    item.update(_short_term_trade_context_marker(item))
    return item


def _path_giveback_pct(row: dict[str, Any]) -> float | None:
    mfe = _safe_float(row.get("mfe_pct"))
    ret = _safe_float(row.get("return_pct"))
    if mfe is None or ret is None:
        return None
    return round(max(0.0, mfe - ret), 4)


def _early_follow_through_diagnostic(path: list[dict[str, Any]], *, days: int = 3) -> dict[str, Any]:
    early_path = path[:max(days, 1)]
    early_mae = _min_number(row.get("floating_pnl_pct") for row in early_path)
    early_mfe = _max_number(row.get("floating_pnl_pct") for row in early_path)
    early_last_return = _safe_float(early_path[-1].get("floating_pnl_pct")) if early_path else None
    state, label = _classify_early_follow_through(early_mae, early_mfe, early_last_return)
    return {
        "early_follow_through_days": len(early_path),
        "early_mae_pct": early_mae,
        "early_mfe_pct": early_mfe,
        "early_return_pct": early_last_return,
        "early_follow_through_state": state,
        "early_follow_through_label": label,
    }


def _early_follow_through_from_metrics(row: dict[str, Any]) -> dict[str, Any]:
    early_mae = _safe_float(row.get("early_mae_pct"))
    early_mfe = _safe_float(row.get("early_mfe_pct"))
    early_last_return = _safe_float(row.get("early_return_pct"))
    state, label = _classify_early_follow_through(early_mae, early_mfe, early_last_return)
    return {
        "early_follow_through_state": state,
        "early_follow_through_label": label,
    }


def _classify_early_follow_through(
    early_mae: float | None,
    early_mfe: float | None,
    early_last_return: float | None,
) -> tuple[str, str]:
    if early_mae is None and early_mfe is None and early_last_return is None:
        return "unknown", "早期路径未知"
    if (early_mae is not None and early_mae <= -4.0) and (early_mfe is None or early_mfe < 2.0):
        return "failed_launch", "启动后立即失败"
    if (early_last_return is not None and early_last_return <= -2.0) and (early_mfe is None or early_mfe < 3.0):
        return "failed_launch", "启动后立即失败"
    if early_mfe is not None and early_mfe >= 4.0:
        return "confirmed_follow_through", "买后资金跟随"
    if early_mfe is not None and early_mfe >= 1.5:
        return "weak_follow_through", "买后弱跟随"
    return "no_follow_through", "买后无跟随"


def _classify_path_issue(row: dict[str, Any]) -> tuple[str, str]:
    ret = _safe_float(row.get("return_pct"))
    mae = _safe_float(row.get("mae_pct"))
    mfe = _safe_float(row.get("mfe_pct"))
    giveback = _safe_float(row.get("giveback_pct"))
    early_state = str(row.get("early_follow_through_state") or "")
    if row.get("sold_before_rebound"):
        return "sold_before_rebound", "卖早后反弹"
    if giveback is not None and giveback >= 8.0 and (mfe or 0) >= 8.0:
        return "exit_giveback", "回撤/卖点问题"
    if ret is not None and ret < 0 and early_state in {"failed_launch", "no_follow_through"}:
        return "entry_follow_through", "买后无承接"
    if ret is not None and ret < 0 and (mfe is None or mfe < 4.0) and (mae is not None and mae <= -5.0):
        return "entry_quality", "买点质量问题"
    if ret is not None and ret < 0:
        return "loss_control", "亏损控制问题"
    return "healthy", "正常盈利"


def _entry_context_marker(row: dict[str, Any]) -> dict[str, Any]:
    if not any(row.get(key) for key in ("dynamic_market_regime", "market_warning_label", "recovery_state", "fund_flow_state")):
        return {
            "entry_context_state": "unknown",
            "entry_context_label": "市场环境未知",
            "entry_context_notes": [],
        }
    warning_level = _safe_float(row.get("market_warning_level")) or 0.0
    breadth = _safe_float(row.get("market_breadth_score"))
    recovery = str(row.get("recovery_state") or "")
    regime = str(row.get("dynamic_market_regime") or "")
    fund_flow = str(row.get("fund_flow_state") or "")
    notes = []
    if regime in {"crash", "weak_defensive"} or warning_level >= 3:
        state, label = "risk_off", "环境向下/强风险"
        notes.append(str(row.get("market_warning_label") or label))
    elif recovery in {"warming_confirmed", "stabilizing"}:
        state, label = "warming", str(row.get("recovery_label") or "回暖观察")
    elif breadth is not None and breadth < 42:
        state, label = "weak_breadth", "市场广度弱"
    elif regime in {"false_bull", "choppy_rotation"} and recovery == "none":
        state, label = "not_warmed", "震荡但未回暖"
    else:
        state, label = "neutral", str(row.get("dynamic_market_label") or "环境中性")
    if fund_flow in {"outflow", "continuous_outflow", "panic_outflow"}:
        notes.append(str(row.get("fund_flow_label") or "资金流出"))
    elif fund_flow == "unknown":
        notes.append("资金流数据不足")
    return {
        "entry_context_state": state,
        "entry_context_label": label,
        "entry_context_notes": notes,
    }


def _entry_launch_diagnostic_marker(row: dict[str, Any]) -> dict[str, Any]:
    setup = str(row.get("entry_setup") or "")
    early_state = str(row.get("early_follow_through_state") or "")
    low_suction_days = _safe_float(row.get("low_suction_days")) or 0.0
    launch_confirmed = bool(row.get("low_suction_launch_confirmed"))
    close_location = _safe_float(row.get("close_location_in_range"))
    volume_ratio = _safe_float(row.get("volume_ratio_5d_20d"))
    pullback_days = _safe_float(row.get("pullback_days"))
    notes = []
    if early_state == "failed_launch":
        state, label = "failed_launch", "启动后立即失败"
    elif setup == "dragon_pullback" and row.get("early_dragon_pullback_risk"):
        state, label = "early_dragon_risk", "经典龙回头偏早"
    elif setup == "stealth_low_suction" and launch_confirmed:
        if early_state in {"confirmed_follow_through", "weak_follow_through"}:
            state, label = "low_suction_followed", "低吸启动后有跟随"
        else:
            state, label = "low_suction_unfollowed", "低吸启动未见承接"
    elif low_suction_days >= 5 and not launch_confirmed:
        state, label = "low_suction_waiting", "低吸蓄势仍在等待"
    elif early_state == "confirmed_follow_through":
        state, label = "followed", "买后资金跟随"
    elif early_state == "weak_follow_through":
        state, label = "weak_followed", "买后弱跟随"
    else:
        state, label = "watch", "启动质量观察"
    if pullback_days is not None and pullback_days >= 12:
        notes.append("回踩时间偏长")
    if volume_ratio is not None and volume_ratio < 0.7:
        notes.append("量能偏弱")
    if close_location is not None and close_location >= 0.70:
        notes.append("收盘位置偏高，需防弱反抽")
    return {
        "entry_launch_diagnostic_state": state,
        "entry_launch_diagnostic_label": label,
        "entry_launch_diagnostic_notes": notes,
    }


def _low_suction_dragon_context_marker(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    quality_bucket = row.get("low_suction_launch_quality_bucket") or low_suction_launch_quality_bucket(payload)
    quality_label = row.get("low_suction_launch_quality_label") or low_suction_launch_quality_label(quality_bucket)
    payload.update(
        {
            "entry_setup": row.get("entry_setup"),
            "setup_type": row.get("entry_setup"),
            "low_suction_days": row.get("low_suction_days"),
            "low_suction_launch_confirmed": row.get("low_suction_launch_confirmed"),
            "low_suction_launch_quality_bucket": quality_bucket,
            "low_suction_launch_quality_label": quality_label,
            "early_dragon_pullback_risk": row.get("early_dragon_pullback_risk"),
            "entry_launch_diagnostic_state": row.get("entry_launch_diagnostic_state"),
            "early_follow_through_state": row.get("early_follow_through_state"),
            "ma_convergence_pct": row.get("ma_convergence_pct"),
            "latest_change_pct": row.get("latest_change_pct"),
            "close_location_in_range": row.get("close_location_in_range"),
        }
    )
    return {
        "low_suction_launch_quality_bucket": quality_bucket,
        "low_suction_launch_quality_label": quality_label,
        **low_suction_dragon_context(payload),
    }


def _fund_flow_coverage_marker(row: dict[str, Any]) -> dict[str, Any]:
    source = str(row.get("fund_flow_source") or "")
    state = str(row.get("fund_flow_state") or "")
    if source == "sector_fund_flows":
        coverage_state, coverage_label = "market_fund_flow", "市场资金流可用"
    elif source == "stock_fund_flows_partial":
        coverage_state, coverage_label = "partial_stock_fund_flow", "局部个股资金流"
    elif state in {"", "unknown", "insufficient_data"}:
        coverage_state, coverage_label = "missing", "资金流数据不足"
    else:
        coverage_state, coverage_label = "available", "资金流可用"
    return {
        "fund_flow_coverage_state": coverage_state,
        "fund_flow_coverage_label": coverage_label,
    }


def _market_mainline_trade_context_marker(row: dict[str, Any]) -> dict[str, Any]:
    """Map market/mainline context into read-only review buckets."""

    regime = str(row.get("dynamic_market_regime") or "")
    regime_label = str(row.get("dynamic_market_label") or "")
    theme_state = str(row.get("theme_state") or "")
    alignment = str(row.get("stock_theme_alignment") or "")
    dominant_theme = str(row.get("dominant_theme") or "")
    market_warning = _safe_float(row.get("market_warning_level")) or 0.0
    fund_flow = str(row.get("fund_flow_state") or "")
    launch_state = str(row.get("entry_launch_diagnostic_state") or row.get("early_follow_through_state") or "")
    setup = str(row.get("entry_setup") or "")
    notes = []
    if regime_label:
        notes.append(regime_label)
    if dominant_theme:
        notes.append(f"主线 {dominant_theme}")

    if regime in {"weak_defensive", "crash"} or market_warning >= 3 or fund_flow in {"continuous_outflow", "panic_outflow"}:
        state, label = "risk_off", "退潮/弱市防守"
        notes.append("大盘或资金处于防守状态")
    elif regime == "narrow_theme_bull" and theme_state in {"active", "active_pullback"} and alignment in {"leader_theme", "theme_related"}:
        state, label = "mainline_pullback", "主线分歧回踩"
        notes.append("主线仍在，候选属于主线或相关方向")
    elif regime == "narrow_theme_bull" and theme_state == "active":
        state, label = "mainline_active", "窄牛主线活跃"
        notes.append("主线活跃但候选主线对齐不足")
    elif regime == "choppy_rotation" and alignment in {"leader_theme", "theme_related"}:
        state, label = "rotation_theme_candidate", "震荡轮动主线候选"
        notes.append("震荡期主线/相关候选")
    elif regime in {"choppy_rotation", "false_bull"} and setup == "stealth_low_suction":
        state, label = "rotation_low_suction_watch", "震荡低吸观察"
        notes.append("震荡/假强势环境下的低吸观察")
    elif alignment == "isolated_candidate":
        state, label = "isolated_strength", "弱市独立强票"
        notes.append("非主线对齐，需看自身承接")
    elif launch_state in {"followed", "low_suction_followed", "confirmed_follow_through"}:
        state, label = "market_follow_through", "买后承接验证"
        notes.append("买后有承接，作为路径复盘")
    else:
        state, label = "unknown_mainline", "主线未知/普通轮动"
        notes.append("主线数据不足或未对齐")

    return {
        "market_mainline_trade_context": state,
        "market_mainline_trade_context_label": label,
        "market_mainline_trade_context_notes": _dedupe_texts(notes),
    }


def _short_term_trade_context_marker(row: dict[str, Any]) -> dict[str, Any]:
    """Map public short-term/youzi concepts to observable path context."""

    entry_context = str(row.get("entry_context_state") or "")
    launch_state = str(row.get("entry_launch_diagnostic_state") or row.get("early_follow_through_state") or "")
    replacement_outcome = str(row.get("replacement_outcome") or "")
    exit_reason = str(row.get("exit_reason") or "")
    setup = str(row.get("entry_setup") or "")
    fund_flow = str(row.get("fund_flow_state") or "")
    theme_state = str(row.get("theme_state") or "")
    market_warning = _safe_float(row.get("market_warning_level")) or 0.0
    mfe = _safe_float(row.get("mfe_pct"))
    giveback = _safe_float(row.get("giveback_pct"))
    sold_before_rebound = bool(row.get("sold_before_rebound"))
    notes: list[str] = []

    if entry_context == "risk_off" or market_warning >= 3 or fund_flow in {"continuous_outflow", "panic_outflow"}:
        context, label = "defensive_tide", "退潮防守"
        notes.append("大盘/资金环境偏防守")
    elif sold_before_rebound and replacement_outcome == "bad_replacement":
        context, label = "failed_slot_replacement", "卖早且替换差"
        notes.append("释放仓位后的替换交易质量差")
    elif exit_reason == "support_stop" and launch_state in {"failed_launch", "no_follow_through"}:
        context, label = "failed_launch_cut", "假启动止损"
        notes.append("买后三日无承接")
    elif giveback is not None and giveback >= 8.0 and (mfe or 0.0) >= 8.0:
        context, label = "trend_profit_giveback", "趋势浮盈回吐"
        notes.append("有趋势利润但后续回撤")
    elif entry_context == "warming" and launch_state in {"followed", "low_suction_followed", "confirmed_follow_through"}:
        context, label = "warming_follow_through", "回暖后资金跟随"
        notes.append("回暖期买后有承接")
    elif entry_context in {"not_warmed", "weak_breadth"} and setup == "stealth_low_suction":
        context, label = "divergence_low_suction", "分歧低吸观察"
        notes.append("低吸发生在未回暖或弱广度环境")
    elif theme_state in {"mainline_active", "leader_theme"} or entry_context == "mainline_active":
        context, label = "mainline_active", "主线活跃"
        notes.append("主线/题材状态活跃")
    elif launch_state in {"followed", "low_suction_followed", "confirmed_follow_through"}:
        context, label = "follow_through", "买后承接"
        notes.append("买后有资金跟随")
    else:
        context, label = "neutral_rotation", "震荡轮动"

    return {
        "short_term_trade_context": context,
        "short_term_trade_context_label": label,
        "short_term_trade_context_notes": notes,
    }


def _dedupe_texts(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def support_stop_context_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Split support-stop exits into context buckets for sell/hold research."""

    support_rows = [row for row in rows if str(row.get("exit_reason") or "") == "support_stop"]
    return {
        "method": "只读归因：用已成交路径的 MAE/MFE、买后三日承接和卖后10日反弹拆分 support_stop，不改变卖点规则。",
        "overall": _path_metric_summary(support_rows),
        "by_context": _support_stop_context_bucket_rows(support_rows),
    }


def support_stop_matrix_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize support-stop rows for focused sell/risk-control research."""

    enriched = [support_stop_matrix_row(row) for row in rows]
    return {
        "method": "只读矩阵：只看真实 support_stop 闭仓路径，按上下文、行情、策略族、买后三日承接和卖后替换质量拆分；不改变默认卖点。",
        "overall": _path_metric_summary(enriched),
        "by_support_stop_context": _group_path_metrics(
            enriched,
            "support_stop_context",
            _support_stop_context_label_for_bucket,
        ),
        "by_path_issue": _group_path_metrics(enriched, "path_issue_type", _path_issue_label_for_bucket),
        "by_early_follow_through": _group_path_metrics(
            enriched,
            "early_follow_through_state",
            _early_follow_through_label_for_bucket,
        ),
        "by_setup_family": _group_path_metrics(enriched, "setup_family", _setup_family_label_for_bucket),
        "by_market_phase": _group_path_metrics(enriched, "market_phase", _market_phase_label_for_bucket),
        "by_phase_setup": _support_stop_phase_setup_matrix(enriched),
        "by_replacement_outcome": _group_path_metrics(
            enriched,
            "replacement_outcome",
            _replacement_outcome_label_for_bucket,
        ),
        "interpretation": _support_stop_matrix_interpretation(enriched),
        "audit_only": True,
        "not_used_for_signal_score": True,
    }


def support_stop_matrix_row(row: dict[str, Any]) -> dict[str, Any]:
    item = _with_market_phase_fields(_with_path_issue(dict(row)))
    context, label = _classify_support_stop_context(item)
    item["support_stop_context"] = context
    item["support_stop_context_label"] = label
    return item


def support_stop_matrix_sample_rows(rows: list[dict[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    capped = min(max(int(limit or 40), 1), 200)
    enriched = [support_stop_matrix_row(row) for row in rows]
    enriched.sort(
        key=lambda row: (
            _support_stop_sample_priority(row),
            _sort_number(row.get("return_pct"), default=0),
            -_sort_number(row.get("mfe_pct"), default=0),
            str(row.get("entry_date") or ""),
            str(row.get("vt_symbol") or ""),
        )
    )
    return enriched[:capped]


def _support_stop_sample_priority(row: dict[str, Any]) -> int:
    priority = {
        "clean_float_profit_giveback": 0,
        "high_mfe_then_rebound_after_stop": 1,
        "stopped_then_rebounded": 2,
        "true_failed_launch_stop": 3,
        "had_follow_through_but_lost_support": 4,
        "other_support_stop": 5,
    }
    return priority.get(str(row.get("support_stop_context") or ""), 99)


def _support_stop_phase_setup_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    values: dict[tuple[str, str], tuple[Any, Any]] = {}
    for row in rows:
        phase = row.get("market_phase") or "unknown"
        setup = row.get("setup_family") or "unknown"
        key = (str(phase), str(setup))
        groups.setdefault(key, []).append(row)
        values.setdefault(key, (phase, setup))
    result = []
    for key, bucket_rows in groups.items():
        phase, setup = values[key]
        result.append(
            {
                "market_phase": None if str(phase) == "unknown" else phase,
                "phase_label": _market_phase_label_for_bucket(phase, bucket_rows),
                "setup_family": None if str(setup) == "unknown" else setup,
                "setup_label": _setup_family_label_for_bucket(setup, bucket_rows),
                **_path_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (-int(item.get("trade_count") or 0), _sort_number(item.get("total_pnl"), default=10**18)))
    return result


def _support_stop_matrix_interpretation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    contexts = {str(row.get("support_stop_context") or "") for row in rows}
    true_failed = [row for row in rows if row.get("support_stop_context") == "true_failed_launch_stop"]
    rebound = [row for row in rows if row.get("support_stop_context") in {"stopped_then_rebounded", "high_mfe_then_rebound_after_stop"}]
    giveback = [row for row in rows if row.get("support_stop_context") == "clean_float_profit_giveback"]
    bad_replacements = [row for row in rows if row.get("replacement_outcome") == "bad_replacement"]
    return {
        "needs_failed_launch_control": bool(true_failed),
        "needs_rebound_guard": bool(rebound),
        "needs_profit_giveback_control": bool(giveback),
        "needs_replacement_quality_gate": bool(bad_replacements),
        "notes": [
            "存在真失败启动止损样本，买后可见连续破位/无上冲可以继续做默认关闭风控实验。"
            if true_failed else "真失败启动样本不足，暂不支持新增失败启动卖点。",
            "存在卖后反弹样本，不能把 support_stop 简单提前或加速。"
            if rebound else "卖后反弹样本不足，延迟卖出暂不优先。",
            "存在浮盈回吐后破位样本，动态最高收益回撤卖点仍值得窄口径审计。"
            if giveback else "浮盈回吐样本不足，不应新增宽泛高点回撤卖点。",
            "卖后坏替换仍多，任何卖点实验都必须同时报告替换质量。"
            if bad_replacements else "坏替换不明显，卖点实验可更关注原持仓路径。",
        ],
        "context_count": len(contexts),
    }


def exit_path_replacement_quality_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize sell path, support-stop context and freed-slot replacement quality."""

    return {
        "method": "只读归因：按闭仓路径、支撑止损上下文和卖出后的下一笔真实 BUY 衡量替换质量；不改变卖点规则。",
        "overall": _path_metric_summary(rows),
        "by_trade_problem_type": buy_sell_problem_matrix(rows)["by_problem"],
        "by_exit_reason": _group_path_metrics(rows, "exit_reason", _exit_reason_label_for_bucket),
        "by_support_stop_context": support_stop_context_audit(rows)["by_context"],
        "replacement_quality_summary": replacement_quality_summary(rows),
        "not_used_for_signal_score": True,
    }


def replacement_quality_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    replacement_returns = [value for row in rows if (value := _safe_float(row.get("replacement_return_pct"))) is not None]
    replacement_deltas = [value for row in rows if (value := _safe_float(row.get("replacement_return_delta_pct"))) is not None]
    return {
        "replacement_trade_count": sum(1 for row in rows if row.get("replacement_trade_id") is not None),
        "bad_replacement_count": sum(1 for row in rows if row.get("replacement_outcome") == "bad_replacement"),
        "strong_replacement_count": sum(1 for row in rows if row.get("replacement_outcome") == "strong_replacement"),
        "avg_replacement_return_pct": _avg(replacement_returns),
        "avg_replacement_return_delta_pct": _avg(replacement_deltas),
        "by_replacement_outcome": _group_path_metrics(rows, "replacement_outcome", _replacement_outcome_label_for_bucket),
    }


def market_context_validation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize strategy path quality across market and fund-flow context buckets."""

    non_strong_rows = [
        row
        for row in rows
        if str(row.get("dynamic_market_regime") or "") not in {"strong_broad", "narrow_mainline_bull"}
    ]
    return {
        "method": "只读归因：按买入日市场/主线/资金流环境分组，用于检查是否只依赖强势行情；不改变买卖、排序或仓位。",
        "by_market_regime": _group_path_metrics(rows, "dynamic_market_regime", _dynamic_market_label_for_bucket),
        "by_market_warning_level": _group_path_metrics(rows, "market_warning_level", _market_warning_level_label_for_bucket),
        "by_market_recovery_level": _group_path_metrics(rows, "market_recovery_level", _market_recovery_level_label_for_bucket),
        "by_fund_flow_state": _group_path_metrics(rows, "fund_flow_state", _fund_flow_state_label_for_bucket),
        "by_market_mainline_trade_context": _group_path_metrics(
            rows,
            "market_mainline_trade_context",
            _market_mainline_trade_context_label_for_bucket,
        ),
        "excluding_strong_market": _path_metric_summary(non_strong_rows),
        "fund_flow_coverage": {
            "by_coverage": _group_path_metrics(rows, "fund_flow_coverage_state", _fund_flow_coverage_label_for_bucket),
            "insufficient_data_count": sum(1 for row in rows if row.get("fund_flow_coverage_state") == "missing"),
        },
        "not_used_for_signal_score": True,
    }


def classify_buy_sell_problem(row: dict[str, Any]) -> str:
    """Classify the dominant reason a candidate/trade needs review."""

    actual_return = _first_number(row.get("return_pct"), row.get("current_strategy_return_pct"), row.get("closed_return_pct"))
    fixed_return = _first_number(row.get("return_20d"), row.get("fixed_return_20d"), row.get("observation_return_pct"))
    mfe = _first_number(row.get("mfe_pct"), row.get("mfe_20d"), row.get("current_strategy_mfe_pct"))
    replacement_return = _safe_float(row.get("replacement_return_pct"))
    not_filled_reason = str(row.get("not_filled_reason") or row.get("not_ordered_reason") or row.get("skip_reason") or "")

    if row.get("sold_before_rebound") and str(row.get("exit_reason") or "") == "support_stop":
        return SOLD_TOO_EARLY
    giveback = _safe_float(row.get("giveback_pct"))
    if actual_return is not None and actual_return < 0 and (
        (fixed_return is not None and fixed_return > 5.0)
        or (mfe is not None and mfe >= 8.0 and (giveback is None or giveback >= 8.0))
    ):
        return SELL_GIVEBACK
    if fixed_return is not None and fixed_return > 5.0 and actual_return is None and _is_capacity_miss_reason(not_filled_reason):
        return PORTFOLIO_CAPACITY_MISS
    if replacement_return is not None and replacement_return < -3.0:
        return REPLACEMENT_BAD
    if (actual_return is not None and actual_return > 10.0) or (mfe is not None and mfe > 15.0 and (actual_return is None or actual_return >= 0)):
        return HEALTHY_TREND_WINNER
    if fixed_return is not None and fixed_return < -3.0 and (actual_return is None or actual_return < 0):
        return BUY_POINT_BAD
    if actual_return is not None and actual_return < 0 and str(row.get("path_issue_type") or "") in {"entry_quality", "entry_follow_through"}:
        return BUY_POINT_BAD
    return UNKNOWN


def buy_sell_problem_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = []
    for row in rows:
        item = dict(row)
        item["trade_problem_type"] = classify_buy_sell_problem(item)
        item["trade_problem_label"] = _buy_sell_problem_label(item["trade_problem_type"])
        enriched.append(item)
    return {
        "by_problem": _group_path_metrics(enriched, "trade_problem_type", _buy_sell_problem_label_for_bucket),
        "by_setup_problem": _buy_sell_problem_pair_buckets(enriched, "entry_setup", "trade_problem_type", _entry_setup_label),
        "by_market_problem": _buy_sell_problem_pair_buckets(enriched, "dynamic_market_regime", "trade_problem_type", _dynamic_market_label_for_bucket),
        "focused_symbols": _buy_sell_problem_focus_rows(enriched),
    }


def _support_stop_context_bucket_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        context, label = _classify_support_stop_context(row)
        item = dict(row)
        item["support_stop_context"] = context
        item["support_stop_context_label"] = label
        groups.setdefault(context, []).append(item)
    result = []
    for context, bucket_rows in groups.items():
        result.append(
            {
                "support_stop_context": context,
                "label": bucket_rows[0].get("support_stop_context_label") or context,
                **_path_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (-int(item.get("trade_count") or 0), _sort_number(item.get("avg_return_pct"), default=10**18)))
    return result


def _classify_support_stop_context(row: dict[str, Any]) -> tuple[str, str]:
    mfe = _safe_float(row.get("mfe_pct"))
    giveback = _safe_float(row.get("giveback_pct"))
    early_state = str(row.get("early_follow_through_state") or "")
    sold_before_rebound = bool(row.get("sold_before_rebound"))
    if mfe is not None and mfe >= 8.0 and giveback is not None and giveback >= 8.0 and not sold_before_rebound:
        return "clean_float_profit_giveback", "浮盈回吐后破位"
    if mfe is not None and mfe >= 8.0 and sold_before_rebound:
        return "high_mfe_then_rebound_after_stop", "高浮盈后止损又反弹"
    if sold_before_rebound:
        return "stopped_then_rebounded", "止损后反弹"
    if early_state in {"failed_launch", "no_follow_through"} and (mfe is None or mfe < 4.0):
        return "true_failed_launch_stop", "真失败启动止损"
    if early_state in {"confirmed_follow_through", "weak_follow_through"}:
        return "had_follow_through_but_lost_support", "有承接但后续破支撑"
    return "other_support_stop", "其他支撑止损"


def _support_stop_context_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("support_stop_context_label"):
            return str(row["support_stop_context_label"])
    labels = {
        "clean_float_profit_giveback": "浮盈回吐后破位",
        "high_mfe_then_rebound_after_stop": "高浮盈后止损又反弹",
        "stopped_then_rebounded": "止损后反弹",
        "true_failed_launch_stop": "真失败启动止损",
        "had_follow_through_but_lost_support": "有承接但后续破支撑",
        "other_support_stop": "其他支撑止损",
        "unknown": "未知支撑止损",
    }
    return labels.get(str(value or "unknown"), str(value or "未知支撑止损"))


def _buy_sell_problem_pair_buckets(
    rows: list[dict[str, Any]],
    group_key: str,
    problem_key: str,
    group_labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    values: dict[tuple[str, str], tuple[Any, Any]] = {}
    for row in rows:
        group_value = row.get(group_key) or "unknown"
        problem_value = row.get(problem_key) or UNKNOWN
        key = (str(group_value), str(problem_value))
        groups.setdefault(key, []).append(row)
        values.setdefault(key, (group_value, problem_value))
    result = []
    for key, bucket_rows in groups.items():
        group_value, problem_value = values[key]
        result.append(
            {
                group_key: None if str(group_value) == "unknown" else group_value,
                f"{group_key}_label": group_labeler(group_value, bucket_rows),
                problem_key: problem_value,
                "problem_label": _buy_sell_problem_label(problem_value),
                **_path_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (-int(item.get("trade_count") or 0), _sort_number(item.get("avg_return_pct"), default=10**18)))
    return result


def _buy_sell_problem_focus_rows(rows: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    problem_priority = {
        SELL_GIVEBACK: 0,
        SOLD_TOO_EARLY: 1,
        BUY_POINT_BAD: 2,
        REPLACEMENT_BAD: 3,
        PORTFOLIO_CAPACITY_MISS: 4,
        UNKNOWN: 5,
        HEALTHY_TREND_WINNER: 6,
    }
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            problem_priority.get(str(row.get("trade_problem_type") or UNKNOWN), 99),
            _sort_number(row.get("return_pct"), default=0),
            -_sort_number(row.get("mfe_pct"), default=0),
        ),
    )
    return [
        {
            "vt_symbol": row.get("vt_symbol"),
            "name": row.get("name"),
            "entry_date": row.get("entry_date"),
            "exit_date": row.get("exit_date"),
            "entry_setup": row.get("entry_setup"),
            "dynamic_market_regime": row.get("dynamic_market_regime"),
            "exit_reason": row.get("exit_reason"),
            "return_pct": row.get("return_pct"),
            "mfe_pct": row.get("mfe_pct"),
            "mae_pct": row.get("mae_pct"),
            "sold_before_rebound": row.get("sold_before_rebound"),
            "replacement_outcome": row.get("replacement_outcome"),
            "replacement_return_pct": row.get("replacement_return_pct"),
            "trade_problem_type": row.get("trade_problem_type"),
            "trade_problem_label": row.get("trade_problem_label"),
        }
        for row in sorted_rows[:limit]
    ]


def _buy_sell_problem_label_for_bucket(value: Any, _rows: list[dict[str, Any]]) -> str:
    return _buy_sell_problem_label(value)


def _buy_sell_problem_label(value: Any) -> str:
    labels = {
        BUY_POINT_BAD: "买点问题",
        SELL_GIVEBACK: "卖点回撤问题",
        SOLD_TOO_EARLY: "卖早反弹",
        PORTFOLIO_CAPACITY_MISS: "满仓错过",
        REPLACEMENT_BAD: "替换交易变差",
        HEALTHY_TREND_WINNER: "趋势赢家",
        UNKNOWN: "未归类",
    }
    return labels.get(str(value or UNKNOWN), str(value or UNKNOWN))


def _is_capacity_miss_reason(reason: str) -> bool:
    return reason in {
        "full_position",
        "position_slot_unavailable",
        "no_rotation",
        "no_rotation_candidate",
        "lower_rank",
        "already_held",
    }


def _first_number(*values: Any) -> float | None:
    for value in values:
        numeric = _safe_float(value)
        if numeric is not None:
            return numeric
    return None


def _path_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _safe_float(row.get("return_pct"))) is not None]
    replacement_returns = [value for row in rows if (value := _safe_float(row.get("replacement_return_pct"))) is not None]
    replacement_deltas = [value for row in rows if (value := _safe_float(row.get("replacement_return_delta_pct"))) is not None]
    pnl_values = [value for row in rows if (value := _safe_float(row.get("pnl"))) is not None]
    losses = [value for value in returns if value < 0]
    wins = [value for value in returns if value > 0]
    mae_values = [value for row in rows if (value := _safe_float(row.get("mae_pct"))) is not None]
    mfe_values = [value for row in rows if (value := _safe_float(row.get("mfe_pct"))) is not None]
    givebacks = [value for row in rows if (value := _safe_float(row.get("giveback_pct"))) is not None]
    return {
        "trade_count": len(rows),
        "evaluated_count": len(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(returns) * 100 if returns else None,
        "avg_return_pct": _avg(returns),
        "median_return_pct": median(returns) if returns else None,
        "total_return_pct": sum(returns) if returns else None,
        "replacement_trade_count": sum(1 for row in rows if row.get("replacement_trade_id") is not None),
        "bad_replacement_count": sum(1 for row in rows if row.get("replacement_outcome") == "bad_replacement"),
        "strong_replacement_count": sum(1 for row in rows if row.get("replacement_outcome") == "strong_replacement"),
        "avg_replacement_return_pct": _avg(replacement_returns),
        "avg_replacement_return_delta_pct": _avg(replacement_deltas),
        "total_pnl": sum(pnl_values) if pnl_values else None,
        "avg_pnl": _avg(pnl_values),
        "avg_mae_pct": _avg(mae_values),
        "worst_mae_pct": min(mae_values) if mae_values else None,
        "avg_mfe_pct": _avg(mfe_values),
        "best_mfe_pct": max(mfe_values) if mfe_values else None,
        "avg_giveback_pct": _avg(givebacks),
        "max_giveback_pct": max(givebacks) if givebacks else None,
        "sold_before_rebound_count": sum(1 for row in rows if row.get("sold_before_rebound")),
        "exit_giveback_count": sum(1 for row in rows if row.get("path_issue_type") == "exit_giveback"),
        "entry_quality_issue_count": sum(1 for row in rows if row.get("path_issue_type") == "entry_quality"),
        "entry_follow_through_issue_count": sum(1 for row in rows if row.get("path_issue_type") == "entry_follow_through"),
        "loss_control_issue_count": sum(1 for row in rows if row.get("path_issue_type") == "loss_control"),
        "failed_launch_count": sum(1 for row in rows if row.get("early_follow_through_state") == "failed_launch"),
        "no_follow_through_count": sum(1 for row in rows if row.get("early_follow_through_state") == "no_follow_through"),
        "confirmed_follow_through_count": sum(
            1 for row in rows if row.get("early_follow_through_state") == "confirmed_follow_through"
        ),
    }


def _phase_audit_trade_rows(rows: Any) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        raw = _entry_raw_payload(item)
        item["entry_setup"] = raw.get("entry_setup") or raw.get("setup_type") or item.get("entry_setup")
        item["entry_score"] = _entry_raw_number(raw, "entry_total_score", "total_score", "score")
        item["low_suction_days"] = _entry_raw_number(raw, "low_suction_days")
        item["low_suction_launch_confirmed"] = bool(raw.get("low_suction_launch_confirmed"))
        item["low_suction_dragon_state"] = raw.get("low_suction_dragon_state")
        item["dynamic_market_regime"] = raw.get("dynamic_market_regime") or raw.get("regime")
        item["dynamic_market_label"] = raw.get("dynamic_market_label")
        item["market_warning_level"] = raw.get("market_warning_level")
        item["recovery_state"] = raw.get("recovery_state")
        item["fund_flow_state"] = raw.get("fund_flow_state")
        item["market_score"] = raw.get("market_score")
        item["market_breadth_score"] = raw.get("market_breadth_score") or raw.get("breadth_score")
        item["theme_strength"] = raw.get("theme_strength")
        result.append(item)
    return result


def _phase_audit_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row.get("payload") or {})
        outcome = row.get("outcome_payload")
        if isinstance(outcome, dict):
            item["outcome"] = outcome
            item["observation_return_pct"] = _first_number(
                outcome.get("return_pct"),
                outcome.get("fixed_return_20d"),
                outcome.get("return_20d"),
            )
            item["observation_mae_pct"] = _first_number(outcome.get("mae_pct"), outcome.get("mae_20d"))
            item["observation_mfe_pct"] = _first_number(outcome.get("mfe_pct"), outcome.get("mfe_20d"))
        item.setdefault("rank", row.get("rank"))
        item.setdefault("vt_symbol", row.get("vt_symbol"))
        item.setdefault("signal_date", row.get("trade_date"))
        item.setdefault("entry_family", row.get("entry_family"))
        result.append(item)
    return result


def _with_market_phase_fields(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    phase = market_context.classify_trading_market_phase(item)
    item["market_phase"] = phase["phase"]
    item["market_phase_label"] = phase["label"]
    item["market_phase_confidence"] = phase["confidence"]
    item["market_phase_position_hint"] = phase["position_hint"]
    item["market_phase_preferred_setups"] = phase["preferred_setups"]
    item["market_phase_notes"] = phase["notes"]
    item["setup_family"] = _market_phase_setup_family(item)
    return item


def _with_nested_signal_evidence(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    for key, value in evidence.items():
        item.setdefault(key, value)
    return item


def market_phase_setup_family(row: dict[str, Any]) -> str:
    """Return the strategy-family bucket used by phase/family audits and experiments."""

    return _market_phase_setup_family(row)


def _market_phase_setup_family(row: dict[str, Any]) -> str:
    setup = str(row.get("entry_setup") or row.get("setup_primary") or row.get("entry_family") or "")
    low_suction_days = _safe_float(row.get("low_suction_days")) or 0.0
    launch_confirmed = bool(row.get("low_suction_launch_confirmed"))
    dragon_state = str(row.get("low_suction_dragon_state") or "")
    if setup == "dragon_pullback" and (low_suction_days >= 3 or dragon_state in {"overlap", "synergy"}):
        return "dragon_low_suction_overlap"
    if setup == "dragon_pullback":
        return "dragon_pullback"
    if setup in {"stealth_low_suction", "low_position_reclaim"} or low_suction_days >= 3:
        return "low_suction_first_lift" if launch_confirmed else "low_suction_buildup"
    if setup:
        return setup
    return "unknown"


def _phase_trade_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _safe_float(row.get("return_pct"))) is not None]
    pnl_values = [value for row in rows if (value := _safe_float(row.get("pnl"))) is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    return {
        "trade_count": len(rows),
        "evaluated_count": len(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(returns) * 100 if returns else None,
        "avg_return_pct": _avg(returns),
        "median_return_pct": median(returns) if returns else None,
        "total_return_pct": sum(returns) if returns else None,
        "total_pnl": sum(pnl_values) if pnl_values else None,
        "avg_pnl": _avg(pnl_values),
        "worst_return_pct": min(returns) if returns else None,
        "best_return_pct": max(returns) if returns else None,
        "support_stop_count": sum(1 for row in rows if str(row.get("exit_reason") or "") == "support_stop"),
        "trailing_stop_count": sum(1 for row in rows if str(row.get("exit_reason") or "") == "trailing_stop"),
        "time_stop_count": sum(1 for row in rows if str(row.get("exit_reason") or "") == "time_stop"),
    }


def _phase_candidate_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _safe_float(row.get("observation_return_pct"))) is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    return {
        "candidate_count": len(rows),
        "evaluated_count": len(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(returns) * 100 if returns else None,
        "avg_return_pct": _avg(returns),
        "median_return_pct": median(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "best_return_pct": max(returns) if returns else None,
        "mae_5_pct_loss_ratio": _rate((_safe_float(row.get("observation_mae_pct")) or 0) <= -5 for row in rows),
        "mfe_8_pct_hit_ratio": _rate((_safe_float(row.get("observation_mfe_pct")) or 0) >= 8 for row in rows),
    }


def _phase_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups, values = _group_rows_by_key(rows, key)
    result = [
        {
            key: None if group_key == "unknown" else values[group_key],
            "label": labeler(values[group_key], bucket_rows),
            **_phase_trade_metric_summary(bucket_rows),
        }
        for group_key, bucket_rows in groups.items()
    ]
    result.sort(key=lambda item: (-int(item.get("trade_count") or 0), _sort_number(item.get("avg_return_pct"), default=10**18)))
    return result


def _phase_candidate_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups, values = _group_rows_by_key(rows, key)
    result = [
        {
            key: None if group_key == "unknown" else values[group_key],
            "label": labeler(values[group_key], bucket_rows),
            **_phase_candidate_metric_summary(bucket_rows),
        }
        for group_key, bucket_rows in groups.items()
    ]
    result.sort(key=lambda item: (-int(item.get("candidate_count") or 0), _sort_number(item.get("avg_return_pct"), default=10**18)))
    return result


def _phase_setup_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row.get("market_phase") or "unknown"), str(row.get("setup_family") or "unknown")), []).append(row)
    result = []
    for (phase, setup), bucket_rows in groups.items():
        result.append(
            {
                "market_phase": None if phase == "unknown" else phase,
                "phase_label": _market_phase_label_for_bucket(phase, bucket_rows),
                "setup_family": None if setup == "unknown" else setup,
                "setup_label": _setup_family_label_for_bucket(setup, bucket_rows),
                **_phase_trade_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (str(item.get("market_phase") or ""), -int(item.get("trade_count") or 0)))
    return result


def _phase_candidate_setup_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row.get("market_phase") or "unknown"), str(row.get("setup_family") or "unknown")), []).append(row)
    result = []
    for (phase, setup), bucket_rows in groups.items():
        result.append(
            {
                "market_phase": None if phase == "unknown" else phase,
                "phase_label": _market_phase_label_for_bucket(phase, bucket_rows),
                "setup_family": None if setup == "unknown" else setup,
                "setup_label": _setup_family_label_for_bucket(setup, bucket_rows),
                **_phase_candidate_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (str(item.get("market_phase") or ""), -int(item.get("candidate_count") or 0)))
    return result


def _normalized_candidate_rank_limits(values: list[int] | tuple[int, ...] | None) -> list[int]:
    raw_values = list(values or [10, 20, 100])
    limits = sorted({min(max(_safe_int(value, 20), 1), 100) for value in raw_values})
    return limits or [10, 20, 100]


def _needs_market_context_annotation(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and any(not row.get("dynamic_market_regime") for row in rows)


def _phase_strategy_family_interpretation(
    trade_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    trade_matrix = _phase_setup_matrix(trade_rows)
    candidate_matrix = _phase_candidate_setup_matrix(candidate_rows)
    weak_real_buildup = [
        row for row in trade_matrix
        if row.get("setup_family") == "low_suction_buildup"
        and (_safe_float(row.get("avg_return_pct")) or 0.0) <= 0
    ]
    weak_real_overlap = [
        row for row in trade_matrix
        if row.get("setup_family") == "dragon_low_suction_overlap"
        and (_safe_float(row.get("avg_return_pct")) or 0.0) <= 0
    ]
    strong_candidate_uptrend = [
        row for row in candidate_matrix
        if row.get("market_phase") == "uptrend"
        and (_safe_float(row.get("avg_return_pct")) or 0.0) > 0
    ]
    weak_real_uptrend = [
        row for row in _phase_group_metrics(trade_rows, "market_phase", _market_phase_label_for_bucket)
        if row.get("market_phase") == "uptrend"
        and (_safe_float(row.get("avg_return_pct")) or 0.0) <= 0
    ]
    return {
        "low_suction_buildup_observation_only": bool(weak_real_buildup),
        "overlap_requires_conflict_resolution": bool(weak_real_overlap),
        "market_phase_not_raw_score_bonus": bool(strong_candidate_uptrend and weak_real_uptrend),
        "notes": [
            "低吸蓄势用于观察簇，不应每天画 BUY。"
            if weak_real_buildup else "低吸蓄势仍需按样本继续观察。",
            "龙回头+低吸重叠需要冲突解析，不能自动叠分。"
            if weak_real_overlap else "重叠样本不足或未显示明显负向。",
            "主升候选质量和真实成交质量存在差异，优先查执行/替换/卖点。"
            if strong_candidate_uptrend and weak_real_uptrend else "行情阶段仍保持只读分层。",
        ],
    }


def _replacement_quality_reject_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for order in orders:
        if str(order.get("side") or "").upper() != "BUY":
            continue
        if str(order.get("status") or "") != "rejected":
            continue
        if str(order.get("reason") or "") not in {
            "low_suction_branch_replacement_quality_gate",
            "dynamic_failed_launch_replacement_quality_gate",
        }:
            continue
        raw = order.get("raw") if isinstance(order.get("raw"), dict) else {}
        quality = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
        item = {
            "vt_symbol": order.get("vt_symbol") or raw.get("vt_symbol"),
            "name": order.get("name"),
            "trade_date": _as_date(order.get("trade_date")) or _as_date(raw.get("execute_date")),
            "order_id": order.get("id"),
            "reject_reason": order.get("reason"),
            "reject_reason_label": reason_label(order.get("reason")) or "替换质量闸门",
            "entry_setup": quality.get("entry_setup") or raw.get("entry_setup"),
            "setup_family": quality.get("setup_family") or raw.get("setup_family"),
            "entry_score": _safe_float(quality.get("entry_score")),
            "low_suction_launch_quality_bucket": quality.get("low_suction_launch_quality_bucket"),
            "market_warning_level": quality.get("market_warning_level"),
            "ma_convergence_pct": quality.get("ma_convergence_pct"),
            "gate_id": raw.get("gate_id"),
            "gate_source_symbol": raw.get("gate_source_symbol"),
            "gate_source_reason": raw.get("gate_source_reason"),
            "gate_wait_count": raw.get("gate_wait_count"),
            "gate_max_wait_days": raw.get("gate_max_wait_days"),
            "reject_reasons": [str(note) for note in (quality.get("notes") or [])],
            "raw": raw,
        }
        rows.append(item)
    return rows


def _with_replacement_matrix_trade_fields(row: dict[str, Any]) -> dict[str, Any]:
    item = _with_market_phase_fields(row)
    raw = _entry_raw_payload({"raw": item.get("raw") if isinstance(item.get("raw"), dict) else {}})
    item["entry_setup"] = raw.get("entry_setup") or raw.get("setup_type") or item.get("entry_setup")
    item["entry_score"] = _first_number(
        _entry_raw_number(raw, "entry_total_score", "total_score", "score"),
        item.get("entry_score"),
    )
    item["low_suction_days"] = _first_number(_entry_raw_number(raw, "low_suction_days"), item.get("low_suction_days"))
    item["low_suction_launch_confirmed"] = bool(raw.get("low_suction_launch_confirmed", item.get("low_suction_launch_confirmed")))
    item["low_suction_dragon_state"] = raw.get("low_suction_dragon_state") or item.get("low_suction_dragon_state")
    item["low_suction_launch_quality_bucket"] = (
        raw.get("low_suction_launch_quality_bucket")
        or item.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(item)
    )
    item["low_suction_launch_quality_label"] = low_suction_launch_quality_label(item["low_suction_launch_quality_bucket"])
    item["setup_family"] = _market_phase_setup_family(item)
    item["setup_label"] = _setup_family_label_for_bucket(item.get("setup_family"), [item])
    return item


def _with_replacement_matrix_reject_fields(row: dict[str, Any]) -> dict[str, Any]:
    explicit_family = row.get("setup_family")
    item = _with_market_phase_fields(row)
    bucket = item.get("low_suction_launch_quality_bucket") or low_suction_launch_quality_bucket(item)
    item["low_suction_launch_quality_bucket"] = bucket
    item["low_suction_launch_quality_label"] = low_suction_launch_quality_label(bucket)
    item["setup_family"] = explicit_family or item.get("setup_family") or _market_phase_setup_family(item)
    item["setup_label"] = _setup_family_label_for_bucket(item.get("setup_family"), [item])
    item["reject_reason_count"] = len(item.get("reject_reasons") or [])
    return item


def _replacement_reject_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [value for row in rows if (value := _safe_float(row.get("entry_score"))) is not None]
    warnings = [value for row in rows if (value := _safe_float(row.get("market_warning_level"))) is not None]
    return {
        "reject_count": len(rows),
        "avg_entry_score": _avg(scores),
        "avg_market_warning_level": _avg(warnings),
        "high_warning_count": sum(1 for row in rows if (_safe_float(row.get("market_warning_level")) or 0.0) >= 2),
        "reason_count": sum(len(row.get("reject_reasons") or []) for row in rows),
        "unique_reason_count": len({reason for row in rows for reason in (row.get("reject_reasons") or [])}),
    }


def _replacement_reject_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups, values = _group_rows_by_key(rows, key)
    result = [
        {
            key: None if group_key == "unknown" else values[group_key],
            "label": labeler(values[group_key], bucket_rows),
            **_replacement_reject_metric_summary(bucket_rows),
        }
        for group_key, bucket_rows in groups.items()
    ]
    result.sort(key=lambda item: (-int(item.get("reject_count") or 0), str(item.get(key) or "")))
    return result


def _replacement_reject_reason_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        for reason in row.get("reject_reasons") or []:
            counts[str(reason)] = counts.get(str(reason), 0) + 1
    result = [{"reason": reason, "label": _replacement_reject_reason_label(reason), "count": count} for reason, count in counts.items()]
    result.sort(key=lambda item: (-int(item["count"]), str(item["reason"])))
    return result


def _replacement_reject_reason_label(reason: Any) -> str:
    labels = {
        "score_below_gate": "分数低于接力闸门",
        "market_warning_too_high": "市场风险等级过高",
        "has_failed_or_risk_flags": "候选带失败/风险标记",
        "low_suction_overlap_unconfirmed": "低吸/龙回头重叠未确认",
        "strict_setup_gate_unconfirmed_buildup_or_overlap": "严格接力闸门：低吸蓄势/重叠未启动",
        "weak_low_suction_launch_bucket": "低吸启动桶偏弱",
        "low_suction_ma_convergence_too_wide": "低吸均线收敛过宽",
        "dragon_ma_convergence_too_wide": "龙回头均线收敛过宽",
        "dragon_not_fresh_tail_buy": "龙回头不是新鲜回踩",
        "unsupported_setup": "不支持的接力形态",
    }
    return labels.get(str(reason or ""), str(reason or "未知拒买原因"))


def _replacement_quality_interpretation(trade_rows: list[dict[str, Any]], reject_rows: list[dict[str, Any]]) -> dict[str, Any]:
    filled_by_regime = _phase_group_metrics(trade_rows, "dynamic_market_regime", _dynamic_market_label_for_bucket)
    filled_by_setup = _phase_group_metrics(trade_rows, "setup_family", _setup_family_label_for_bucket)
    weak_regimes = [
        row for row in filled_by_regime
        if int(row.get("trade_count") or 0) >= 5 and (_safe_float(row.get("avg_return_pct")) or 0.0) <= 0
    ]
    weak_setups = [
        row for row in filled_by_setup
        if int(row.get("trade_count") or 0) >= 5 and (_safe_float(row.get("avg_return_pct")) or 0.0) <= 0
    ]
    return {
        "replacement_quality_needs_market_phase": bool(weak_regimes),
        "low_suction_buildup_observation_only": any(row.get("setup_family") == "low_suction_buildup" for row in weak_setups),
        "overlap_requires_conflict_resolution": any(row.get("setup_family") == "dragon_low_suction_overlap" for row in weak_setups),
        "gate_reject_count": len(reject_rows),
        "notes": [
            "卖后接力质量存在行情分层差异，应继续按行情阶段审计，而不是继续加单条阈值。"
            if weak_regimes else "当前样本未显示明显的行情分层接力亏损。",
            "低吸蓄势仍应作为观察簇，不应每天作为买点接力。"
            if any(row.get("setup_family") == "low_suction_buildup" for row in weak_setups) else "低吸蓄势桶在当前样本未形成足够负向证据。",
            "龙回头+低吸重叠需要冲突解析，不能自动叠分。"
            if any(row.get("setup_family") == "dragon_low_suction_overlap" for row in weak_setups) else "重叠桶在当前样本未形成足够负向证据。",
        ],
    }


def _group_rows_by_key(rows: list[dict[str, Any]], key: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    values: dict[str, Any] = {}
    for row in rows:
        raw_value = row.get(key) or "unknown"
        group_key = str(raw_value)
        groups.setdefault(group_key, []).append(row)
        values.setdefault(group_key, raw_value)
    return groups, values


def _market_phase_diagnostics(trade_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics = []
    phase_buckets = _phase_group_metrics(trade_rows, "market_phase", _market_phase_label_for_bucket)
    for bucket in phase_buckets:
        phase = bucket.get("market_phase") or "unknown"
        win_rate = _safe_float(bucket.get("win_rate"))
        avg_return = _safe_float(bucket.get("avg_return_pct"))
        trade_count = int(bucket.get("trade_count") or 0)
        if trade_count < 10:
            diagnostics.append(
                {
                    "phase": phase,
                    "level": "watch",
                    "message": "样本不足，不能直接作为调参依据。",
                }
            )
        elif win_rate is not None and avg_return is not None and win_rate < 30 and avg_return <= 0:
            diagnostics.append(
                {
                    "phase": phase,
                    "level": "risk",
                    "message": "该行情下真实成交胜率和均值都弱，优先研究降仓/空仓。",
                }
            )
        elif win_rate is not None and win_rate >= 40 and avg_return is not None and avg_return > 0:
            diagnostics.append(
                {
                    "phase": phase,
                    "level": "opportunity",
                    "message": "该行情下真实成交质量较好，可研究保留或加仓条件。",
                }
            )
    if candidate_rows and not any(row.get("fund_flow_state") not in {None, "", "unknown"} for row in candidate_rows + trade_rows):
        diagnostics.append(
            {
                "phase": "all",
                "level": "data_gap",
                "message": "资金流字段覆盖不足，暂不能把资金出逃/回流作为强交易门控。",
            }
        )
    return diagnostics


def _market_phase_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("market_phase_label"):
            return str(row["market_phase_label"])
    labels = {
        "uptrend": "主升",
        "rotation": "震荡",
        "retreat": "退潮",
        "warming": "回暖",
        "unknown": "行情未知",
    }
    return labels.get(str(value or "unknown"), str(value or "行情未知"))


def _setup_family_label_for_bucket(value: Any, _rows: list[dict[str, Any]]) -> str:
    labels = {
        "dragon_pullback": "龙回头",
        "low_suction_buildup": "低吸蓄势",
        "low_suction_first_lift": "低吸首启",
        "dragon_low_suction_overlap": "龙回头+低吸",
        "low_position_reclaim": "低位均线收复",
        "unknown": "未知形态",
    }
    return labels.get(str(value or "unknown"), str(value or "未知形态"))


def _group_path_metrics(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    values: dict[str, Any] = {}
    for row in rows:
        raw_value = row.get(key) or "unknown"
        group_key = str(raw_value)
        groups.setdefault(group_key, []).append(row)
        values.setdefault(group_key, raw_value)
    result = []
    for group_key, bucket_rows in groups.items():
        result.append(
            {
                key: None if group_key == "unknown" else values[group_key],
                "label": labeler(values[group_key], bucket_rows),
                **_path_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (-int(item.get("trade_count") or 0), _sort_number(item.get("avg_return_pct"), default=10**18)))
    return result


def entry_launch_quality_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare visible entry factors against early post-entry follow-through."""

    return {
        "method": "只使用买入成交 raw 里在信号日已可见的入场因子；early_follow_through 是事后路径标签，只用于复盘归因。",
        "overall": _entry_launch_quality_summary(rows),
        "by_entry_setup": _entry_launch_quality_buckets(rows, "entry_setup", _entry_setup_label),
        "by_low_suction_days": _entry_launch_quality_derived_buckets(
            rows,
            "low_suction_days_bucket",
            _low_suction_days_bucket,
            _identity_label,
        ),
        "by_ma_convergence": _entry_launch_quality_derived_buckets(
            rows,
            "ma_convergence_bucket",
            _ma_convergence_bucket,
            _identity_label,
        ),
        "by_volume_ratio": _entry_launch_quality_derived_buckets(
            rows,
            "volume_ratio_bucket",
            _volume_ratio_bucket,
            _identity_label,
        ),
        "by_pullback_days": _entry_launch_quality_derived_buckets(
            rows,
            "pullback_days_bucket",
            _pullback_days_bucket,
            _identity_label,
        ),
        "by_close_location": _entry_launch_quality_derived_buckets(
            rows,
            "close_location_bucket",
            _close_location_bucket,
            _identity_label,
        ),
        "by_tail_repeat": _entry_launch_quality_derived_buckets(
            rows,
            "tail_repeat_bucket",
            _tail_repeat_bucket,
            _identity_label,
        ),
        "by_low_suction_launch_quality": _entry_launch_quality_derived_buckets(
            rows,
            "low_suction_launch_quality_bucket",
            _low_suction_launch_quality_bucket,
            _low_suction_launch_quality_label,
        ),
        "by_dynamic_market_regime": _entry_launch_quality_buckets(
            rows,
            "dynamic_market_regime",
            _dynamic_market_label_for_bucket,
        ),
        "risk_contrast": _entry_launch_risk_contrast(rows),
    }


def _entry_launch_quality_buckets(
    rows: list[dict[str, Any]],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    values: dict[str, Any] = {}
    for row in rows:
        value = row.get(key) or "unknown"
        group_key = str(value)
        groups.setdefault(group_key, []).append(row)
        values.setdefault(group_key, value)
    return _entry_launch_quality_bucket_rows(groups, values, key, labeler)


def _entry_launch_quality_derived_buckets(
    rows: list[dict[str, Any]],
    key: str,
    bucketer: Callable[[dict[str, Any]], str],
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    values: dict[str, Any] = {}
    for row in rows:
        value = bucketer(row)
        groups.setdefault(value, []).append(row)
        values.setdefault(value, value)
    return _entry_launch_quality_bucket_rows(groups, values, key, labeler)


def _entry_launch_quality_bucket_rows(
    groups: dict[str, list[dict[str, Any]]],
    values: dict[str, Any],
    key: str,
    labeler: Callable[[Any, list[dict[str, Any]]], str],
) -> list[dict[str, Any]]:
    result = []
    for group_key, bucket_rows in groups.items():
        result.append(
            {
                key: None if group_key == "unknown" else values[group_key],
                "label": labeler(values[group_key], bucket_rows),
                **_entry_launch_quality_summary(bucket_rows),
            }
        )
    result.sort(
        key=lambda item: (
            -int(item.get("trade_count") or 0),
            -_sort_number(item.get("failed_launch_rate"), default=0),
            _sort_number(item.get("avg_return_pct"), default=10**18),
        )
    )
    return result


def _entry_launch_quality_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _safe_float(row.get("return_pct"))) is not None]
    failed = [row for row in rows if row.get("early_follow_through_state") == "failed_launch"]
    no_follow = [row for row in rows if row.get("early_follow_through_state") == "no_follow_through"]
    weak = [row for row in rows if row.get("early_follow_through_state") == "weak_follow_through"]
    confirmed = [row for row in rows if row.get("early_follow_through_state") == "confirmed_follow_through"]
    return {
        "trade_count": len(rows),
        "evaluated_count": len(returns),
        "win_rate": _rate((_safe_float(row.get("return_pct")) or 0) > 0 for row in rows if _safe_float(row.get("return_pct")) is not None),
        "avg_return_pct": _avg(returns),
        "failed_launch_count": len(failed),
        "failed_launch_rate": _pct_ratio(len(failed), len(rows)),
        "no_follow_through_count": len(no_follow),
        "no_follow_through_rate": _pct_ratio(len(no_follow), len(rows)),
        "weak_follow_through_count": len(weak),
        "weak_follow_through_rate": _pct_ratio(len(weak), len(rows)),
        "confirmed_follow_through_count": len(confirmed),
        "confirmed_follow_through_rate": _pct_ratio(len(confirmed), len(rows)),
        "avg_entry_score": _avg(row.get("entry_score") for row in rows),
        "avg_low_suction_days": _avg(row.get("low_suction_days") for row in rows),
        "avg_ma_convergence_pct": _avg(row.get("ma_convergence_pct") for row in rows),
        "avg_volume_ratio_5d_20d": _avg(row.get("volume_ratio_5d_20d") for row in rows),
        "avg_tail_buy_repeat_days": _avg(row.get("tail_buy_repeat_days") for row in rows),
        "sold_before_rebound_count": sum(1 for row in rows if row.get("sold_before_rebound")),
    }


def _entry_launch_risk_contrast(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if row.get("early_follow_through_state") == "failed_launch"]
    confirmed = [row for row in rows if row.get("early_follow_through_state") == "confirmed_follow_through"]
    return {
        "failed_launch": _entry_factor_average_snapshot(failed),
        "confirmed_follow_through": _entry_factor_average_snapshot(confirmed),
        "note": "对比值只说明相关性，不代表可直接硬拒；需要后续全局回测验证。"
    }


def _entry_factor_average_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trade_count": len(rows),
        "avg_return_pct": _avg(row.get("return_pct") for row in rows),
        "avg_entry_score": _avg(row.get("entry_score") for row in rows),
        "avg_low_suction_days": _avg(row.get("low_suction_days") for row in rows),
        "avg_ma_convergence_pct": _avg(row.get("ma_convergence_pct") for row in rows),
        "avg_volume_ratio_5d_20d": _avg(row.get("volume_ratio_5d_20d") for row in rows),
        "avg_pullback_days": _avg(row.get("pullback_days") for row in rows),
        "avg_close_location_in_range": _avg(row.get("close_location_in_range") for row in rows),
        "avg_tail_buy_repeat_days": _avg(row.get("tail_buy_repeat_days") for row in rows),
        "recent_limit_up_rate": _rate(row.get("recent_limit_up_20d") for row in rows),
        "low_suction_launch_confirmed_rate": _rate(row.get("low_suction_launch_confirmed") for row in rows),
    }


def _low_suction_days_bucket(row: dict[str, Any]) -> str:
    days = _safe_float(row.get("low_suction_days"))
    if days is None:
        return "unknown"
    if days <= 0:
        return "0"
    if days <= 2:
        return "1-2"
    if days <= 4:
        return "3-4"
    return "5+"


def _ma_convergence_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("ma_convergence_pct"))
    if value is None:
        return "unknown"
    if value <= 5.0:
        return "<=5%"
    if value <= 8.8:
        return "5-8.8%"
    if value <= 13.0:
        return "8.8-13%"
    return ">13%"


def _volume_ratio_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("volume_ratio_5d_20d"))
    if value is None:
        return "unknown"
    if value < 0.7:
        return "<0.7"
    if value <= 1.2:
        return "0.7-1.2"
    if value <= 1.8:
        return "1.2-1.8"
    return ">1.8"


def _pullback_days_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("pullback_days"))
    if value is None:
        return "unknown"
    if value <= 2:
        return "0-2"
    if value <= 5:
        return "3-5"
    if value <= 8:
        return "6-8"
    if value <= 12:
        return "9-12"
    return "12+"


def _close_location_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("close_location_in_range"))
    if value is None:
        return "unknown"
    if value < 0.45:
        return "<0.45"
    if value < 0.58:
        return "0.45-0.58"
    if value < 0.70:
        return "0.58-0.70"
    return ">=0.70"


def _tail_repeat_bucket(row: dict[str, Any]) -> str:
    value = _safe_float(row.get("tail_buy_repeat_days"))
    if value is None:
        return "unknown"
    if value <= 0:
        return "0"
    if value <= 2:
        return "1-2"
    return "3+"


def _low_suction_launch_quality_bucket(row: dict[str, Any]) -> str:
    return low_suction_launch_quality_bucket(row)


def _low_suction_launch_quality_label(value: Any, _rows: list[dict[str, Any]]) -> str:
    return low_suction_launch_quality_label(value)


def _low_suction_dragon_context_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("low_suction_dragon_label"):
            return str(row["low_suction_dragon_label"])
    return low_suction_dragon_context_label(value)


def _identity_label(value: Any, _rows: list[dict[str, Any]]) -> str:
    return str(value or "未知")


def _setup_market_exit_matrix(rows: list[dict[str, Any]], *, min_trades: int = 1) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("entry_setup") or "unknown"),
            str(row.get("dynamic_market_regime") or "unknown"),
            str(row.get("exit_reason") or "unknown"),
        )
        groups.setdefault(key, []).append(row)
    result = []
    for (setup, regime, reason), bucket_rows in groups.items():
        if len(bucket_rows) < min_trades:
            continue
        result.append(
            {
                "entry_setup": None if setup == "unknown" else setup,
                "entry_setup_label": _entry_setup_label(setup, bucket_rows),
                "dynamic_market_regime": None if regime == "unknown" else regime,
                "dynamic_market_label": _dynamic_market_label_for_bucket(regime, bucket_rows),
                "exit_reason": None if reason == "unknown" else reason,
                "exit_reason_label": _exit_reason_label_for_bucket(reason, bucket_rows),
                **_path_metric_summary(bucket_rows),
            }
        )
    result.sort(key=lambda item: (_sort_number(item.get("avg_return_pct"), default=10**18), -int(item.get("trade_count") or 0)))
    return result


def _worst_setup_market_exit_buckets(rows: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    matrix = [row for row in _setup_market_exit_matrix(rows) if int(row.get("trade_count") or 0) >= 2]
    return matrix[:limit]


def _worst_setup_market_exit_examples(rows: list[dict[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    enriched = [_with_path_issue(row) for row in rows]
    enriched.sort(
        key=lambda row: (
            _sort_number(row.get("return_pct"), default=10**18),
            -_sort_number(row.get("giveback_pct"), default=0),
            str(row.get("entry_date") or ""),
            str(row.get("vt_symbol") or ""),
        )
    )
    return enriched[:limit]


def _entry_setup_label(value: Any, _rows: list[dict[str, Any]]) -> str:
    labels = {
        "dragon_pullback": "龙回头",
        "stealth_low_suction": "低吸洗盘",
        "ma5_pullback": "MA5回踩",
        "unknown": "未知买点",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _dynamic_market_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("dynamic_market_label"):
            return str(row["dynamic_market_label"])
    return str(value or "未知")


def _market_warning_level_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("market_warning_label"):
            return str(row["market_warning_label"])
    if value is None or str(value) == "unknown":
        return "未知风险"
    return f"风险等级 {value}"


def _market_recovery_level_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("market_recovery_label"):
            return str(row["market_recovery_label"])
        if row.get("recovery_label"):
            return str(row["recovery_label"])
    if value is None or str(value) == "unknown":
        return "未知回暖"
    return f"回暖等级 {value}"


def _fund_flow_state_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("fund_flow_label"):
            return str(row["fund_flow_label"])
    labels = {
        "inflow": "资金流入",
        "recovery": "资金回流",
        "outflow": "资金流出",
        "continuous_outflow": "连续流出",
        "panic_outflow": "恐慌流出",
        "insufficient_data": "资金流数据不足",
        "unknown": "未知资金流",
    }
    return labels.get(str(value or "unknown"), str(value or "未知资金流"))


def _exit_reason_label_for_bucket(value: Any, _rows: list[dict[str, Any]]) -> str:
    return reason_label(value) or "未知卖点"


def _path_issue_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("path_issue_label"):
            return str(row["path_issue_label"])
    labels = {
        "sold_before_rebound": "卖早后反弹",
        "exit_giveback": "回撤/卖点问题",
        "entry_follow_through": "买后无承接",
        "entry_quality": "买点质量问题",
        "loss_control": "亏损控制问题",
        "healthy": "正常盈利",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _early_follow_through_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("early_follow_through_label"):
            return str(row["early_follow_through_label"])
    labels = {
        "failed_launch": "启动后立即失败",
        "no_follow_through": "买后无跟随",
        "weak_follow_through": "买后弱跟随",
        "confirmed_follow_through": "买后资金跟随",
        "unknown": "早期路径未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _entry_context_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("entry_context_label"):
            return str(row["entry_context_label"])
    labels = {
        "risk_off": "环境向下/强风险",
        "weak_breadth": "市场广度弱",
        "not_warmed": "震荡但未回暖",
        "warming": "回暖观察",
        "neutral": "环境中性",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _short_term_trade_context_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("short_term_trade_context_label"):
            return str(row["short_term_trade_context_label"])
    labels = {
        "defensive_tide": "退潮防守",
        "failed_slot_replacement": "卖早且替换差",
        "failed_launch_cut": "假启动止损",
        "trend_profit_giveback": "趋势浮盈回吐",
        "warming_follow_through": "回暖后资金跟随",
        "divergence_low_suction": "分歧低吸观察",
        "mainline_active": "主线活跃",
        "follow_through": "买后承接",
        "neutral_rotation": "震荡轮动",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _market_mainline_trade_context_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("market_mainline_trade_context_label"):
            return str(row["market_mainline_trade_context_label"])
    labels = {
        "risk_off": "退潮/弱市防守",
        "mainline_pullback": "主线分歧回踩",
        "mainline_active": "窄牛主线活跃",
        "rotation_theme_candidate": "震荡轮动主线候选",
        "rotation_low_suction_watch": "震荡低吸观察",
        "isolated_strength": "弱市独立强票",
        "market_follow_through": "买后承接验证",
        "unknown_mainline": "主线未知/普通轮动",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _entry_launch_diagnostic_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("entry_launch_diagnostic_label"):
            return str(row["entry_launch_diagnostic_label"])
    labels = {
        "failed_launch": "启动后立即失败",
        "early_dragon_risk": "经典龙回头偏早",
        "low_suction_followed": "低吸启动后有跟随",
        "low_suction_unfollowed": "低吸启动未见承接",
        "low_suction_waiting": "低吸蓄势仍在等待",
        "followed": "买后资金跟随",
        "weak_followed": "买后弱跟随",
        "watch": "启动质量观察",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _fund_flow_coverage_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("fund_flow_coverage_label"):
            return str(row["fund_flow_coverage_label"])
    labels = {
        "market_fund_flow": "市场资金流可用",
        "partial_stock_fund_flow": "局部个股资金流",
        "available": "资金流可用",
        "missing": "资金流数据不足",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _replacement_outcome_label_for_bucket(value: Any, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("replacement_outcome_label"):
            return str(row["replacement_outcome_label"])
    labels = {
        "no_replacement": "未释放到后续买入",
        "open_replacement": "替换持仓未闭合",
        "strong_replacement": "替换买入强盈利",
        "profitable_replacement": "替换买入盈利",
        "weak_replacement": "替换买入弱表现",
        "bad_replacement": "替换买入亏损",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def low_suction_start_factor_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    low_suction_rows = [row for row in rows if row.get("entry_setup") == "stealth_low_suction"]
    winners = [row for row in low_suction_rows if (_safe_float(row.get("return_pct")) or 0) > 0]
    losers = [row for row in low_suction_rows if (_safe_float(row.get("return_pct")) or 0) <= 0]
    weak_rows = [row for row in low_suction_rows if _is_weak_or_sideways_market_row(row)]
    return {
        "total": len(low_suction_rows),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "win_rate": _rate((_safe_float(row.get("return_pct")) or 0) > 0 for row in low_suction_rows),
        "avg_return_pct": _avg(row.get("return_pct") for row in low_suction_rows),
        "weak_or_sideways_index_count": len(weak_rows),
        "weak_or_sideways_index_win_rate": _rate((_safe_float(row.get("return_pct")) or 0) > 0 for row in weak_rows),
        "market_return_sources": sorted({str(row.get("market_return_20d_source")) for row in low_suction_rows if row.get("market_return_20d_source")}),
        "winner_factor_avg": _avg(row.get("limit_up_start_factor_count") for row in winners),
        "loser_factor_avg": _avg(row.get("limit_up_start_factor_count") for row in losers),
        "winner_recent_limit_up_rate": _rate(row.get("recent_limit_up_20d") for row in winners),
        "winner_consecutive_bull_rate": _rate((_safe_float(row.get("consecutive_bull_closes")) or 0) >= 4 for row in winners),
        "winner_upward_gap_rate": _rate(row.get("upward_gap_in_leg") for row in winners),
        "winner_persistent_volume_rate": _rate(row.get("persistent_volume_expansion") for row in winners),
        "factor_buckets": _low_suction_factor_buckets(low_suction_rows),
        "focused_examples": _low_suction_factor_examples(low_suction_rows),
    }


def backtest_low_suction_start_factor_audit(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    lookahead_days: int = 10,
) -> dict[str, Any]:
    diagnostics = backtest_path_diagnostics(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=ensure_schema,
        load_stock_names=load_stock_names,
        symbols_from_rows=symbols_from_rows,
        with_stock_names=with_stock_names,
        to_api=to_api,
        backtest_id=backtest_id,
        lookahead_days=lookahead_days,
        limit=2000,
    )
    if diagnostics.get("status") not in {"ready", "empty"}:
        return diagnostics
    rows = [row for row in diagnostics.get("items") or [] if row.get("entry_setup") == "stealth_low_suction"]
    rows = _fill_low_suction_start_factors(
        schema=schema,
        session_scope=session_scope,
        rows=rows,
    )
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "lookahead_days": diagnostics.get("lookahead_days"),
        "summary": low_suction_start_factor_summary(rows),
        "items": rows,
        "note": "低吸涨停启动四信号当前只做审计；未通过全局回测前不改变买入评分或候选名额。",
    }


def top_candidate_bucket_summary(rows: list[dict[str, Any]], top_n: int = 10) -> dict[str, Any]:
    top_limit = min(max(int(top_n or 10), 1), 100)
    top_rows = [row for row in rows if int(_safe_float(row.get("rank")) or 0) <= top_limit]
    other_rows = [row for row in rows if int(_safe_float(row.get("rank")) or 0) > top_limit]
    evaluated_top = [row for row in top_rows if _safe_float(row.get("return_pct")) is not None]
    evaluated_other = [row for row in other_rows if _safe_float(row.get("return_pct")) is not None]
    top_strong_rows = [row for row in top_rows if _top_candidate_row_regime(row) == "strong"]
    top_excluding_strong_rows = [row for row in top_rows if _top_candidate_row_regime(row) != "strong"]
    return {
        "top_n": top_limit,
        "total_count": len(rows),
        "evaluated_count": len([row for row in rows if _safe_float(row.get("return_pct")) is not None]),
        "top_count": len(top_rows),
        "top_evaluated_count": len(evaluated_top),
        "top_win_rate": _ratio(
            len([row for row in evaluated_top if (_safe_float(row.get("return_pct")) or 0) > 0]),
            len(evaluated_top),
        ),
        "top_avg_return_pct": _avg(row.get("return_pct") for row in evaluated_top),
        "top_avg_benchmark_return_pct": _avg(row.get("benchmark_return_pct") for row in top_rows),
        "top_avg_excess_return_pct": _avg(row.get("excess_return_pct") for row in evaluated_top),
        "other_count": len(other_rows),
        "other_evaluated_count": len(evaluated_other),
        "other_win_rate": _ratio(
            len([row for row in evaluated_other if (_safe_float(row.get("return_pct")) or 0) > 0]),
            len(evaluated_other),
        ),
        "other_avg_return_pct": _avg(row.get("return_pct") for row in evaluated_other),
        "other_avg_benchmark_return_pct": _avg(row.get("benchmark_return_pct") for row in other_rows),
        "other_avg_excess_return_pct": _avg(row.get("excess_return_pct") for row in evaluated_other),
        "market_buckets": _top_candidate_market_buckets(top_rows),
        "top_strong_summary": _top_candidate_metric_summary(top_strong_rows),
        "top_excluding_strong_summary": _top_candidate_metric_summary(top_excluding_strong_rows),
        "top_strong_candidate_share": _ratio(len(top_strong_rows), len(top_rows)),
        "benchmark_sources": _top_candidate_benchmark_sources(top_rows),
        "dynamic_market_sources": _top_candidate_dynamic_market_sources(top_rows),
        "candidate_observation": candidate_observation_summary(top_rows),
        "dynamic_market_buckets": market_context.summarize_contexts(
            top_rows,
            return_key="return_pct",
            excess_key="excess_return_pct",
            evaluated_predicate=lambda row: _safe_float(row.get("return_pct")) is not None,
        ),
        "theme_alignment_buckets": _theme_alignment_buckets(top_rows, return_key="return_pct", excess_key="excess_return_pct"),
    }


def candidate_observation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable_rows = [row for row in rows if _safe_float(row.get("observation_return_pct")) is not None]
    excluding_strong = [row for row in rows if _top_candidate_row_regime(row) != "strong"]
    market_buckets = []
    for regime in ("strong", "weak", "choppy", "unknown"):
        bucket_rows = [row for row in rows if _top_candidate_row_regime(row) == regime]
        if not bucket_rows:
            continue
        market_buckets.append(
            {
                "regime": regime,
                "label": {"strong": "强势", "weak": "弱势", "choppy": "震荡", "unknown": "未知"}[regime],
                **_candidate_observation_metric_summary(bucket_rows),
            }
        )
    return {
        **_candidate_observation_metric_summary(rows),
        "evaluable_count": len(evaluable_rows),
        "excluding_strong_summary": _candidate_observation_metric_summary(excluding_strong),
        "market_buckets": market_buckets,
        "dynamic_market_buckets": market_context.summarize_contexts(
            rows,
            return_key="observation_return_pct",
            excess_key="observation_excess_return_pct",
            evaluated_predicate=lambda row: _safe_float(row.get("observation_return_pct")) is not None,
        ),
        "theme_alignment_buckets": _theme_alignment_buckets(
            rows,
            return_key="observation_return_pct",
            excess_key="observation_excess_return_pct",
        ),
        "holding_days": 20,
        "method": "D+1开盘观察买入，持有20个交易日后按收盘价观察收益；只用于候选质量事后审计，不参与策略交易。",
    }


def backtest_top_candidate_audit(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    backtest_id: int,
    top_n: int = 10,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    ensure_schema()
    top_limit = min(max(int(top_n or 10), 1), 100)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        strategy_id = str(run["strategy_id"])
        strategy_version = str(run["strategy_version"])
        recommendation_rows = session.execute(
            select(schema.quant_recommendations)
            .where(
                and_(
                    schema.quant_recommendations.c.trade_date >= run["start_date"],
                    schema.quant_recommendations.c.trade_date <= run["end_date"],
                    schema.quant_recommendations.c.strategy_id == strategy_id,
                    schema.quant_recommendations.c.strategy_version == strategy_version,
                    schema.quant_recommendations.c.rank <= max(top_limit * 3, top_limit + 20),
                )
            )
            .order_by(schema.quant_recommendations.c.trade_date, schema.quant_recommendations.c.rank, schema.quant_recommendations.c.vt_symbol)
        ).mappings().all()
        trade_rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        recommendation_dicts = [
            row
            for row in (_recommendation_read_view(dict(row)) for row in recommendation_rows)
            if str(row.get("action") or "").upper() == "BUY"
        ]
        trade_dicts = [dict(row) for row in trade_rows]
        entry_dates = [_as_date(row.get("trade_date")) for row in recommendation_dicts]
        entry_dates = [day for day in entry_dates if day is not None]
        benchmark_by_date = _market_returns_20d_for_audit(session, schema, sorted(set(entry_dates)))
        observation_by_key = _candidate_observation_returns(session, schema, recommendation_dicts, holding_days=20)
        stock_names = load_stock_names(session, symbols_from_rows(recommendation_dicts, trade_dicts))
    named_recommendations = with_stock_names(recommendation_dicts, stock_names)
    named_trades = with_stock_names(trade_dicts, stock_names)
    closed_by_key = _closed_trade_rows_by_entry(named_trades)
    rows = []
    for recommendation in named_recommendations:
        signal_date = _as_date(recommendation.get("trade_date"))
        vt_symbol = str(recommendation.get("vt_symbol") or "")
        closed = closed_by_key.get((vt_symbol, signal_date)) if signal_date else None
        benchmark = benchmark_by_date.get(signal_date) if signal_date else None
        return_pct = closed.get("return_pct") if closed else None
        benchmark_return = (benchmark or {}).get("return_20d")
        observation = observation_by_key.get((vt_symbol, signal_date)) if signal_date else None
        observation_return = (observation or {}).get("return_pct")
        rows.append(
            {
                "signal_date": signal_date,
                "rank": recommendation.get("rank"),
                "vt_symbol": vt_symbol,
                "name": recommendation.get("name"),
                "score": recommendation.get("total_score"),
                "reason": recommendation.get("reason") if isinstance(recommendation.get("reason"), dict) else {},
                "entry_date": closed.get("entry_date") if closed else None,
                "exit_date": closed.get("exit_date") if closed else None,
                "return_pct": return_pct,
                "benchmark_return_pct": benchmark_return,
                "benchmark_source": (benchmark or {}).get("source"),
                "excess_return_pct": return_pct - benchmark_return if return_pct is not None and benchmark_return is not None else None,
                "market_regime": _candidate_market_regime(benchmark_return),
                "evaluated": closed is not None,
                "observation_entry_date": (observation or {}).get("entry_date"),
                "observation_exit_date": (observation or {}).get("exit_date"),
                "observation_entry_price": (observation or {}).get("entry_price"),
                "observation_exit_price": (observation or {}).get("exit_price"),
                "observation_return_pct": observation_return,
                "observation_excess_return_pct": observation_return - benchmark_return if observation_return is not None and benchmark_return is not None else None,
                "observation_status": (observation or {}).get("status") or "missing_bar",
            }
        )
    with session_scope() as session:
        rows = market_context.annotate_rows_with_market_context(session, schema, rows, date_key="signal_date")
    summary = top_candidate_bucket_summary(rows, top_n=top_limit)
    response_rows = [{key: value for key, value in row.items() if key != "reason"} for row in rows]
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "top_n": top_limit,
        "summary": summary,
        "items": [to_api(row) for row in response_rows],
        "note": "成交审计只用组合成交并闭仓的候选计算胜率；未成交候选只计数量，不用未来走势伪造收益。",
    }


def _future_daily_bars_for_trades(
    session: Any,
    schema: Any,
    trades: list[dict[str, Any]],
    *,
    lookahead_days: int,
    to_api: ApiMapper,
) -> list[dict[str, Any]]:
    sell_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "SELL"]
    if not sell_trades:
        return []
    symbols = sorted({str(trade.get("vt_symbol") or "") for trade in sell_trades if trade.get("vt_symbol")})
    sell_dates = [parsed for trade in sell_trades if (parsed := _as_date(trade.get("trade_date")))]
    if not symbols or not sell_dates:
        return []
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(symbols))
        .where(schema.stock_daily_bars.c.trade_date > min(sell_dates))
        .where(schema.stock_daily_bars.c.trade_date <= max(sell_dates) + timedelta(days=lookahead_days + 7))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    return [to_api(dict(row)) for row in rows]


def _daily_bars_for_trade_paths(
    session: Any,
    schema: Any,
    trades: list[dict[str, Any]],
    *,
    to_api: ApiMapper,
) -> list[dict[str, Any]]:
    sell_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "SELL"]
    if not sell_trades:
        return []
    symbols = sorted({str(trade.get("vt_symbol") or "") for trade in sell_trades if trade.get("vt_symbol")})
    sell_dates = [parsed for trade in sell_trades if (parsed := _as_date(trade.get("trade_date")))]
    if not symbols or not sell_dates:
        return []
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(symbols))
        .where(schema.stock_daily_bars.c.trade_date >= min(sell_dates) - timedelta(days=30))
        .where(schema.stock_daily_bars.c.trade_date <= max(sell_dates))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    return [to_api(dict(row)) for row in rows]


def _fill_low_suction_start_factors(
    *,
    schema: Any,
    session_scope: Any,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing_rows = [
        row
        for row in rows
        if row.get("limit_up_start_factor_count") is None
        and row.get("entry_date")
        and row.get("vt_symbol")
    ]
    if not missing_rows:
        return rows
    symbols = sorted({str(row["vt_symbol"]) for row in missing_rows})
    entry_dates = [_as_date(row.get("entry_date")) for row in missing_rows]
    entry_dates = [day for day in entry_dates if day is not None]
    if not symbols or not entry_dates:
        return rows
    start = min(entry_dates) - timedelta(days=180)
    end = max(entry_dates)
    with session_scope() as session:
        bars_by_symbol = _daily_bars_by_symbol(session, schema, symbols, start, end)
        market_returns = {
            day: _market_return_20d_for_audit(session, schema, day)
            for day in sorted(set(entry_dates))
        }
    enriched = []
    for row in rows:
        entry_date = _as_date(row.get("entry_date"))
        vt_symbol = str(row.get("vt_symbol") or "")
        if row.get("limit_up_start_factor_count") is not None or entry_date is None or not vt_symbol:
            enriched.append(row)
            continue
        score = score_dragon_pullback(
            vt_symbol,
            bars_by_symbol.get(vt_symbol, []),
            entry_date,
            index_return_20d=market_returns.get(entry_date, {}).get("return_20d"),
        )
        evidence = score.evidence if score.evidence.get("status") == "ready" else {}
        enriched.append(_merge_start_factor_evidence(row, evidence, market_returns.get(entry_date) or {}))
    return enriched


def _daily_bars_by_symbol(
    session: Any,
    schema: Any,
    symbols: list[str],
    start: date,
    end: date,
) -> dict[str, list[Bar]]:
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(symbols))
        .where(schema.stock_daily_bars.c.trade_date >= start)
        .where(schema.stock_daily_bars.c.trade_date <= end)
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    result: dict[str, list[Bar]] = {}
    for row in rows:
        result.setdefault(str(row["vt_symbol"]), []).append(
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


def _index_return_20d_from_session(session: Any, schema: Any, trade_date: date) -> float | None:
    rows = session.execute(
        select(schema.stock_daily_bars.c.close_price)
        .where(schema.stock_daily_bars.c.vt_symbol == "000001.SSE")
        .where(schema.stock_daily_bars.c.trade_date <= trade_date)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(21)
    ).all()
    closes = [float(row[0]) for row in reversed(rows)]
    if len(closes) <= 20 or not closes[0]:
        return None
    return (closes[-1] / closes[0] - 1) * 100


def _market_return_20d_for_audit(session: Any, schema: Any, trade_date: date) -> dict[str, Any]:
    index_return = _index_return_20d_from_session(session, schema, trade_date)
    if index_return is not None:
        return {"return_20d": index_return, "source": "000001.SSE"}
    proxy_return = _equal_weight_market_return_20d_from_session(session, schema, trade_date)
    return {"return_20d": proxy_return, "source": "equal_weight_stock_proxy" if proxy_return is not None else "unavailable"}


def _market_returns_20d_for_audit(session: Any, schema: Any, trade_dates: list[date]) -> dict[date, dict[str, Any]]:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
        return {}
    index_returns = _index_returns_20d_from_session(session, schema, dates)
    missing_dates = [day for day in dates if day not in index_returns]
    proxy_returns = _equal_weight_market_returns_20d_from_session(session, schema, missing_dates) if missing_dates else {}
    return {
        day: (
            {"return_20d": index_returns[day], "source": "000001.SSE"}
            if day in index_returns
            else {
                "return_20d": proxy_returns.get(day),
                "source": "equal_weight_stock_proxy" if proxy_returns.get(day) is not None else "unavailable",
            }
        )
        for day in dates
    }


def _index_returns_20d_from_session(session: Any, schema: Any, trade_dates: list[date]) -> dict[date, float]:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
        return {}
    rows = session.execute(
        select(
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.close_price,
        )
        .where(schema.stock_daily_bars.c.vt_symbol == "000001.SSE")
        .where(schema.stock_daily_bars.c.trade_date >= dates[0] - timedelta(days=60))
        .where(schema.stock_daily_bars.c.trade_date <= dates[-1])
        .order_by(schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    closes_by_date = {row["trade_date"]: float(row["close_price"]) for row in rows}
    ordered_dates = [row["trade_date"] for row in rows]
    result: dict[date, float] = {}
    for trade_date in dates:
        index = bisect_right(ordered_dates, trade_date) - 1
        baseline_index = index - 20
        if baseline_index < 0:
            continue
        start_close = closes_by_date.get(ordered_dates[baseline_index])
        end_close = closes_by_date.get(ordered_dates[index])
        if start_close and end_close:
            result[trade_date] = (end_close / start_close - 1) * 100
    return result


def _equal_weight_market_return_20d_from_session(session: Any, schema: Any, trade_date: date) -> float | None:
    trading_days = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date <= trade_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(21)
    ).all()
    dates = [row[0] for row in reversed(trading_days)]
    if len(dates) <= 20:
        return None
    start_date = dates[0]
    end_date = dates[-1]
    rows = session.execute(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.close_price,
        )
        .where(schema.stock_daily_bars.c.trade_date.in_([start_date, end_date]))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    closes_by_symbol: dict[str, dict[date, float]] = {}
    for row in rows:
        closes_by_symbol.setdefault(str(row["vt_symbol"]), {})[row["trade_date"]] = float(row["close_price"])
    returns = [
        values[end_date] / values[start_date] - 1
        for values in closes_by_symbol.values()
        if values.get(start_date) and values.get(end_date)
    ]
    if not returns:
        return None
    return sum(returns) / len(returns) * 100


def _equal_weight_market_returns_20d_from_session(session: Any, schema: Any, trade_dates: list[date]) -> dict[date, float | None]:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
        return {}
    trading_days = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date >= dates[0] - timedelta(days=70))
        .where(schema.stock_daily_bars.c.trade_date <= dates[-1])
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(schema.stock_daily_bars.c.trade_date)
    ).all()
    ordered_dates = [row[0] for row in trading_days]
    date_pairs: dict[date, tuple[date, date]] = {}
    needed_dates: set[date] = set()
    for trade_date in dates:
        index = bisect_right(ordered_dates, trade_date) - 1
        baseline_index = index - 20
        if baseline_index < 0:
            continue
        start_date = ordered_dates[baseline_index]
        end_date = ordered_dates[index]
        date_pairs[trade_date] = (start_date, end_date)
        needed_dates.update((start_date, end_date))
    if not needed_dates:
        return {day: None for day in dates}
    rows = session.execute(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.close_price,
        )
        .where(schema.stock_daily_bars.c.trade_date.in_(sorted(needed_dates)))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    closes_by_date_symbol: dict[date, dict[str, float]] = {}
    for row in rows:
        closes_by_date_symbol.setdefault(row["trade_date"], {})[str(row["vt_symbol"])] = float(row["close_price"])
    result: dict[date, float | None] = {}
    for trade_date in dates:
        pair = date_pairs.get(trade_date)
        if not pair:
            result[trade_date] = None
            continue
        start_date, end_date = pair
        start_values = closes_by_date_symbol.get(start_date, {})
        end_values = closes_by_date_symbol.get(end_date, {})
        returns = [
            end_close / start_close - 1
            for symbol, start_close in start_values.items()
            if start_close and (end_close := end_values.get(symbol))
        ]
        result[trade_date] = sum(returns) / len(returns) * 100 if returns else None
    return result


def _merge_start_factor_evidence(row: dict[str, Any], evidence: dict[str, Any], market_return: dict[str, Any]) -> dict[str, Any]:
    if not evidence:
        return row
    merged = dict(row)
    for key in (
        "recent_limit_up_20d",
        "consecutive_bull_closes",
        "upward_gap_in_leg",
        "persistent_volume_expansion",
        "limit_up_start_factor_count",
        "weak_index_strength_confirmation",
        "index_return_20d",
    ):
        if key in evidence:
            merged[key] = evidence[key]
    if market_return:
        merged["market_return_20d_source"] = market_return.get("source")
        merged["market_return_20d"] = market_return.get("return_20d")
    return merged


def _is_within_lookahead(trade_date: date | None, exit_date: date | None, lookahead_days: int) -> bool:
    if trade_date is None or exit_date is None or trade_date <= exit_date:
        return False
    return (trade_date - exit_date).days <= lookahead_days


def _low_suction_factor_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("0-1", lambda count: count <= 1),
        ("2", lambda count: count == 2),
        ("3-4", lambda count: count >= 3),
    ]
    result = []
    for label, matches in buckets:
        bucket_rows = [
            row
            for row in rows
            if matches(int(_safe_float(row.get("limit_up_start_factor_count")) or 0))
        ]
        result.append(
            {
                "bucket": label,
                "trade_count": len(bucket_rows),
                "win_rate": _rate((_safe_float(row.get("return_pct")) or 0) > 0 for row in bucket_rows),
                "avg_return_pct": _avg(row.get("return_pct") for row in bucket_rows),
                "weak_or_sideways_index_count": len(
                    [
                        row
                        for row in bucket_rows
                        if _is_weak_or_sideways_market_row(row)
                    ]
                ),
            }
        )
    return result


def _low_suction_factor_examples(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda row: _sort_number(row.get("return_pct"), default=0), reverse=True)
    examples = [*sorted_rows[: limit // 2], *list(reversed(sorted_rows[-(limit // 2):]))]
    return [
        {
            "vt_symbol": row.get("vt_symbol"),
            "name": row.get("name"),
            "entry_date": row.get("entry_date"),
            "exit_date": row.get("exit_date"),
            "return_pct": row.get("return_pct"),
            "limit_up_start_factor_count": row.get("limit_up_start_factor_count"),
            "recent_limit_up_20d": row.get("recent_limit_up_20d"),
            "consecutive_bull_closes": row.get("consecutive_bull_closes"),
            "upward_gap_in_leg": row.get("upward_gap_in_leg"),
            "persistent_volume_expansion": row.get("persistent_volume_expansion"),
            "weak_index_strength_confirmation": row.get("weak_index_strength_confirmation"),
            "market_return_20d": row.get("market_return_20d"),
            "market_return_20d_source": row.get("market_return_20d_source"),
        }
        for row in examples
    ]


def _top_candidate_market_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for regime in ("strong", "weak", "choppy", "unknown"):
        bucket_rows = [row for row in rows if str(row.get("market_regime") or "unknown") == regime]
        if not bucket_rows:
            continue
        result.append(
            {
                "regime": regime,
                "label": {"strong": "强势", "weak": "弱势", "choppy": "震荡", "unknown": "未知"}[regime],
                **_top_candidate_metric_summary(bucket_rows),
            }
        )
    return result


def _top_candidate_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated_rows = [row for row in rows if _safe_float(row.get("return_pct")) is not None]
    return {
        "candidate_count": len(rows),
        "evaluated_count": len(evaluated_rows),
        "win_rate": _ratio(
            len([row for row in evaluated_rows if (_safe_float(row.get("return_pct")) or 0) > 0]),
            len(evaluated_rows),
        ),
        "avg_return_pct": _avg(row.get("return_pct") for row in evaluated_rows),
        "avg_benchmark_return_pct": _avg(row.get("benchmark_return_pct") for row in rows),
        "avg_excess_return_pct": _avg(row.get("excess_return_pct") for row in evaluated_rows),
    }


def _candidate_observation_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed_rows = [row for row in rows if _safe_float(row.get("observation_return_pct")) is not None]
    return {
        "candidate_count": len(rows),
        "observed_count": len(observed_rows),
        "win_rate": _ratio(
            len([row for row in observed_rows if (_safe_float(row.get("observation_return_pct")) or 0) > 0]),
            len(observed_rows),
        ),
        "avg_return_pct": _avg(row.get("observation_return_pct") for row in observed_rows),
        "avg_benchmark_return_pct": _avg(row.get("benchmark_return_pct") for row in rows),
        "avg_excess_return_pct": _avg(row.get("observation_excess_return_pct") for row in observed_rows),
    }


def _theme_alignment_buckets(rows: list[dict[str, Any]], *, return_key: str, excess_key: str) -> list[dict[str, Any]]:
    result = []
    labels = {
        "leader_theme": "主线内",
        "theme_related": "主线相关",
        "isolated_candidate": "独立强票",
        "unknown": "未知",
    }
    for alignment in ("leader_theme", "theme_related", "isolated_candidate", "unknown"):
        bucket_rows = [row for row in rows if str(row.get("stock_theme_alignment") or "unknown") == alignment]
        if not bucket_rows:
            continue
        evaluated_rows = [row for row in bucket_rows if _safe_float(row.get(return_key)) is not None]
        result.append(
            {
                "alignment": alignment,
                "label": labels[alignment],
                "candidate_count": len(bucket_rows),
                "evaluated_count": len(evaluated_rows),
                "win_rate": _ratio(
                    len([row for row in evaluated_rows if (_safe_float(row.get(return_key)) or 0) > 0]),
                    len(evaluated_rows),
                ),
                "avg_return_pct": _avg(row.get(return_key) for row in evaluated_rows),
                "avg_excess_return_pct": _avg(row.get(excess_key) for row in evaluated_rows),
                "avg_market_score": _avg(row.get("market_score") for row in bucket_rows),
                "avg_theme_strength": _avg(row.get("theme_strength") for row in bucket_rows),
            }
        )
    return result


def _top_candidate_row_regime(row: dict[str, Any]) -> str:
    regime = row.get("market_regime")
    if regime:
        return str(regime)
    return _candidate_market_regime(_safe_float(row.get("benchmark_return_pct")))


def _top_candidate_benchmark_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("benchmark_source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return [{"source": source, "count": count} for source, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _top_candidate_dynamic_market_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("dynamic_market_source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return [{"source": source, "count": count} for source, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _candidate_observation_returns(
    session: Any,
    schema: Any,
    recommendation_rows: list[dict[str, Any]],
    *,
    holding_days: int,
) -> dict[tuple[str, date | None], dict[str, Any]]:
    signals = [
        (str(row.get("vt_symbol") or ""), _as_date(row.get("trade_date")))
        for row in recommendation_rows
        if row.get("vt_symbol") and _as_date(row.get("trade_date"))
    ]
    if not signals:
        return {}
    symbols = sorted({symbol for symbol, _signal_date in signals if symbol})
    signal_dates = [signal_date for _symbol, signal_date in signals if signal_date is not None]
    if not symbols or not signal_dates:
        return {}
    rows = session.execute(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.close_price,
        )
        .where(schema.stock_daily_bars.c.vt_symbol.in_(symbols))
        .where(schema.stock_daily_bars.c.trade_date > min(signal_dates))
        .where(schema.stock_daily_bars.c.trade_date <= max(signal_dates) + timedelta(days=holding_days * 3 + 20))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    dates_by_symbol: dict[str, list[date]] = {}
    for row in rows:
        symbol = str(row["vt_symbol"])
        bar = dict(row)
        bars_by_symbol.setdefault(symbol, []).append(bar)
        dates_by_symbol.setdefault(symbol, []).append(bar["trade_date"])
    result: dict[tuple[str, date | None], dict[str, Any]] = {}
    for symbol, signal_date in signals:
        bars = bars_by_symbol.get(symbol) or []
        dates = dates_by_symbol.get(symbol) or []
        key = (symbol, signal_date)
        if not bars or signal_date is None:
            result[key] = {"status": "missing_bar"}
            continue
        entry_index = bisect_right(dates, signal_date)
        exit_index = entry_index + max(int(holding_days or 20), 1) - 1
        if entry_index >= len(bars):
            result[key] = {"status": "missing_entry_bar"}
            continue
        if exit_index >= len(bars):
            result[key] = {
                "status": "missing_exit_bar",
                "entry_date": bars[entry_index].get("trade_date"),
                "entry_price": _safe_float(bars[entry_index].get("open_price")),
            }
            continue
        entry_bar = bars[entry_index]
        exit_bar = bars[exit_index]
        entry_price = _safe_float(entry_bar.get("open_price"))
        exit_price = _safe_float(exit_bar.get("close_price"))
        result[key] = {
            "status": "ready" if entry_price and exit_price else "missing_price",
            "entry_date": entry_bar.get("trade_date"),
            "exit_date": exit_bar.get("trade_date"),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": (exit_price / entry_price - 1) * 100 if entry_price and exit_price else None,
        }
    return result


def _candidate_market_regime(benchmark_return_pct: float | None) -> str:
    if benchmark_return_pct is None:
        return "unknown"
    if benchmark_return_pct >= 5:
        return "strong"
    if benchmark_return_pct <= -3:
        return "weak"
    return "choppy"


def _closed_trade_rows_by_entry(trades: list[dict[str, Any]]) -> dict[tuple[str, date | None], dict[str, Any]]:
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    result: dict[tuple[str, date | None], dict[str, Any]] = {}
    for trade in sorted(trades, key=lambda item: (_as_date(item.get("trade_date")) or date.min, int(item.get("id") or 0))):
        side = str(trade.get("side") or "").upper()
        vt_symbol = str(trade.get("vt_symbol") or "")
        if side == "BUY":
            open_by_symbol.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_by_symbol.setdefault(vt_symbol, []).pop(0) if open_by_symbol.get(vt_symbol) else None
        if not entry:
            continue
        entry_date = _as_date(entry.get("trade_date"))
        exit_date = _as_date(trade.get("trade_date"))
        amount = float(entry.get("amount") or 0)
        pnl = float(trade.get("pnl") or 0)
        result[(vt_symbol, entry_date)] = {
            "vt_symbol": vt_symbol,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "pnl": pnl,
            "return_pct": pnl / amount * 100 if amount else None,
        }
    return result


def _avg(values) -> float | None:
    parsed = [value for value in (_safe_float(value) for value in values) if value is not None]
    return sum(parsed) / len(parsed) if parsed else None


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _pct_ratio(numerator: int | float, denominator: int | float) -> float | None:
    ratio = _ratio(numerator, denominator)
    return ratio * 100 if ratio is not None else None


def _rate(values) -> float | None:
    parsed = [bool(value) for value in values]
    return sum(1 for value in parsed if value) / len(parsed) * 100 if parsed else None


def _is_weak_or_sideways_market_row(row: dict[str, Any]) -> bool:
    if row.get("weak_index_strength_confirmation"):
        return True
    for key in ("index_return_20d", "market_return_20d"):
        value = _safe_float(row.get(key))
        if value is not None and value <= 0:
            return True
    return False


def trade_attribution_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in rows if row.get("status") == "closed"]
    open_rows = [row for row in rows if row.get("status") == "open"]
    realized = [float(row.get("pnl") or 0) for row in closed if row.get("pnl") is not None]
    losses = [value for value in realized if value < 0]
    wins = [value for value in realized if value > 0]
    return {
        "total_count": len(rows),
        "closed_count": len(closed),
        "open_count": len(open_rows),
        "realized_pnl": sum(realized),
        "loss_pnl": sum(losses),
        "win_pnl": sum(wins),
        "win_rate": len(wins) / len(closed) * 100 if closed else 0,
        "worst_trade_pnl": min(realized) if realized else None,
        "best_trade_pnl": max(realized) if realized else None,
        "largest_open_drawdown": _min_number(row.get("min_floating_pnl") for row in rows),
        "largest_open_profit": _max_number(row.get("max_floating_pnl") for row in rows),
    }


def _sort_attribution_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    mode = str(sort or "pnl_asc")
    if mode == "pnl_desc":
        return sorted(rows, key=lambda row: _sort_number(row.get("pnl"), default=-10**18), reverse=True)
    if mode == "entry_desc":
        return sorted(rows, key=lambda row: (str(row.get("entry_date") or ""), str(row.get("vt_symbol") or "")), reverse=True)
    if mode == "entry_asc":
        return sorted(rows, key=lambda row: (str(row.get("entry_date") or ""), str(row.get("vt_symbol") or "")))
    return sorted(rows, key=lambda row: (_sort_number(row.get("pnl"), default=10**18), str(row.get("entry_date") or ""), str(row.get("vt_symbol") or "")))


def _attribution_row(
    vt_symbol: str,
    entry: dict[str, Any] | None,
    exit_trade: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    *,
    status: str,
) -> dict[str, Any]:
    entry_date = entry.get("trade_date") if entry else None
    exit_date = exit_trade.get("trade_date") if exit_trade else None
    path = [
        row for row in positions
        if (entry_date is None or row.get("trade_date") >= entry_date)
        and (exit_date is None or row.get("trade_date") <= exit_date)
    ]
    max_floating_pnl = _max_number(row.get("floating_pnl") for row in path)
    min_floating_pnl = _min_number(row.get("floating_pnl") for row in path)
    max_floating_pnl_pct = _max_number(row.get("floating_pnl_pct") for row in path)
    min_floating_pnl_pct = _min_number(row.get("floating_pnl_pct") for row in path)
    entry_raw = _entry_raw_payload(entry)
    execution = entry_raw.get("execution") if isinstance(entry_raw.get("execution"), dict) else {}
    entry_score = _entry_raw_number(entry_raw, "entry_total_score", "total_score")
    low_suction_days = _entry_raw_number(entry_raw, "low_suction_days")
    low_suction_score = _entry_raw_number(entry_raw, "low_suction_buildup_score")
    ma_convergence_pct = _entry_raw_number(entry_raw, "ma_convergence_pct")
    amount = float((entry or {}).get("amount") or 0)
    pnl = float(exit_trade.get("pnl") or 0) if exit_trade and exit_trade.get("pnl") is not None else None
    return {
        "vt_symbol": vt_symbol,
        "name": (entry or exit_trade or {}).get("name"),
        "board": (entry or exit_trade or {}).get("board"),
        "board_label": (entry or exit_trade or {}).get("board_label"),
        "status": status,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": (entry or {}).get("price"),
        "exit_price": (exit_trade or {}).get("price"),
        "volume": (entry or exit_trade or {}).get("volume"),
        "entry_amount": amount,
        "exit_amount": (exit_trade or {}).get("amount"),
        "fee": float((entry or {}).get("fee") or 0) + float((exit_trade or {}).get("fee") or 0),
        "pnl": pnl,
        "return_pct": pnl / amount * 100 if pnl is not None and amount else None,
        "holding_days": (exit_date - entry_date).days if hasattr(exit_date, "toordinal") and hasattr(entry_date, "toordinal") else None,
        "exit_reason": (exit_trade or {}).get("reason"),
        "exit_reason_label": reason_label((exit_trade or {}).get("reason")),
        "max_floating_pnl": max_floating_pnl,
        "min_floating_pnl": min_floating_pnl,
        "max_floating_pnl_pct": max_floating_pnl_pct,
        "min_floating_pnl_pct": min_floating_pnl_pct,
        "entry_score": entry_score,
        "entry_state": entry_raw.get("dragon_state"),
        "entry_support_type": entry_raw.get("support_type"),
        "low_suction_days": low_suction_days,
        "low_suction_buildup_score": low_suction_score,
        "ma_convergence_pct": ma_convergence_pct,
        "entry_failed_rules": entry_raw.get("failed_rules") if isinstance(entry_raw.get("failed_rules"), list) else [],
        "execution_mode": execution.get("mode"),
        "price_source": execution.get("price_source"),
        "proxy_used": execution.get("proxy_used"),
        "bar_time": execution.get("bar_time"),
    }


def _reason_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {"reason": reason, "reason_label": reason_label(reason), "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _max_number(values) -> float | None:
    parsed = [float(value) for value in values if value is not None]
    return max(parsed) if parsed else None


def _min_number(values) -> float | None:
    parsed = [float(value) for value in values if value is not None]
    return min(parsed) if parsed else None


def _entry_raw_number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _entry_raw_payload(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry or not isinstance(entry.get("raw"), dict):
        return {}
    raw = dict(entry.get("raw") or {})
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    if evidence:
        merged = dict(evidence)
        merged.update(raw)
        return _enrich_entry_raw_payload(merged)
    return _enrich_entry_raw_payload(raw)


def _entry_enriched_api_row(row: dict[str, Any], to_api: ApiMapper) -> dict[str, Any]:
    item = to_api(row)
    if isinstance(item.get("raw"), dict):
        item["raw"] = _enrich_entry_raw_payload(dict(item["raw"]))
    return item


def _enrich_entry_raw_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if "early_dragon_pullback_risk" in raw:
        return raw
    setup = str(raw.get("entry_setup") or raw.get("setup_type") or "")
    low_suction_days = _entry_raw_number(raw, "low_suction_days") or 0.0
    ma_convergence = _entry_raw_number(raw, "ma_convergence_pct")
    latest_change = _entry_raw_number(raw, "latest_change_pct")
    close_location = _entry_raw_number(raw, "close_location_in_range")
    raw["early_dragon_pullback_risk"] = bool(
        setup == "dragon_pullback"
        and low_suction_days <= 0
        and ma_convergence is not None
        and ma_convergence >= 18.0
        and latest_change is not None
        and latest_change >= 1.0
        and close_location is not None
        and close_location >= 0.55
    )
    return raw


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sort_number(value: Any, *, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def candidate_trace_rows(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    normalize_symbol: SymbolNormalizer,
    as_date: DateParser,
    load_stock_names: StockNameLoader,
    board_payload: BoardPayload,
    backtest_id: int,
    vt_symbol: str,
    signal_date: date,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    symbol = normalize_symbol(vt_symbol)
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    ensure_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}
        strategy_id = str(run["strategy_id"])
        strategy_version = str(run["strategy_version"])
        run_params = _run_params(dict(run))
        recommendation = session.execute(
            select(schema.quant_recommendations)
            .where(
                and_(
                    schema.quant_recommendations.c.trade_date == signal_date,
                    schema.quant_recommendations.c.vt_symbol == symbol,
                    schema.quant_recommendations.c.strategy_id == strategy_id,
                    schema.quant_recommendations.c.strategy_version == strategy_version,
                )
            )
            .order_by(schema.quant_recommendations.c.rank, desc(schema.quant_recommendations.c.id))
        ).mappings().first()
        same_day_recommendations = session.execute(
            select(schema.quant_recommendations)
            .where(
                and_(
                    schema.quant_recommendations.c.trade_date == signal_date,
                    schema.quant_recommendations.c.strategy_id == strategy_id,
                    schema.quant_recommendations.c.strategy_version == strategy_version,
                )
            )
            .order_by(schema.quant_recommendations.c.rank, schema.quant_recommendations.c.vt_symbol)
        ).mappings().all()
        signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(
                and_(
                    schema.backtest_signal_events.c.backtest_id == backtest_id,
                    schema.backtest_signal_events.c.vt_symbol == symbol,
                    schema.backtest_signal_events.c.signal_date == signal_date,
                )
            )
            .order_by(schema.backtest_signal_events.c.trade_date, schema.backtest_signal_events.c.id)
        ).mappings().all()
        same_day_signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(
                and_(
                    schema.backtest_signal_events.c.backtest_id == backtest_id,
                    schema.backtest_signal_events.c.signal_date == signal_date,
                )
            )
            .order_by(desc(schema.backtest_signal_events.c.score), schema.backtest_signal_events.c.vt_symbol, schema.backtest_signal_events.c.id)
        ).mappings().all()
        target_theoretical_signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(
                and_(
                    schema.backtest_signal_events.c.backtest_id == backtest_id,
                    schema.backtest_signal_events.c.vt_symbol == symbol,
                    schema.backtest_signal_events.c.signal_date <= signal_date,
                )
            )
            .order_by(schema.backtest_signal_events.c.signal_date, schema.backtest_signal_events.c.trade_date, schema.backtest_signal_events.c.id)
        ).mappings().all()
        signal_bounds = session.execute(
            select(
                func.min(schema.backtest_signal_events.c.signal_date).label("first_signal_date"),
                func.max(schema.backtest_signal_events.c.signal_date).label("last_signal_date"),
                func.count().label("signal_event_count"),
            )
            .where(schema.backtest_signal_events.c.backtest_id == backtest_id)
        ).mappings().first()
        execute_dates = sorted({as_date(row["execute_date"]) for row in signal_rows if as_date(row["execute_date"])})
        if execute_dates:
            order_rows = session.execute(
                select(schema.backtest_orders)
                .where(
                    and_(
                        schema.backtest_orders.c.backtest_id == backtest_id,
                        schema.backtest_orders.c.vt_symbol == symbol,
                        schema.backtest_orders.c.trade_date.in_(execute_dates),
                    )
                )
                .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
            ).mappings().all()
            trade_rows = session.execute(
                select(schema.backtest_trades)
                .where(
                    and_(
                        schema.backtest_trades.c.backtest_id == backtest_id,
                        schema.backtest_trades.c.vt_symbol == symbol,
                        schema.backtest_trades.c.trade_date.in_(execute_dates),
                    )
                )
                .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
            ).mappings().all()
        else:
            order_rows = session.execute(
                select(schema.backtest_orders)
                .where(
                    and_(
                        schema.backtest_orders.c.backtest_id == backtest_id,
                        schema.backtest_orders.c.vt_symbol == symbol,
                        schema.backtest_orders.c.raw["signal_date"].as_string() == signal_date.isoformat(),
                    )
                )
                .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
            ).mappings().all()
            trade_rows = session.execute(
                select(schema.backtest_trades)
                .where(
                    and_(
                        schema.backtest_trades.c.backtest_id == backtest_id,
                        schema.backtest_trades.c.vt_symbol == symbol,
                        schema.backtest_trades.c.raw["execution"]["signal_date"].as_string() == signal_date.isoformat(),
                    )
                )
                .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
            ).mappings().all()
            execute_dates = sorted({as_date(row["trade_date"]) for row in [*order_rows, *trade_rows] if as_date(row["trade_date"])})
        equity_date = execute_dates[0] if execute_dates else signal_date
        equity_row = session.execute(
            select(schema.backtest_daily_equity).where(
                and_(
                    schema.backtest_daily_equity.c.backtest_id == backtest_id,
                    schema.backtest_daily_equity.c.trade_date == equity_date,
                )
            )
        ).mappings().first()
        position_rows = session.execute(
            select(schema.backtest_daily_positions)
            .where(
                and_(
                    schema.backtest_daily_positions.c.backtest_id == backtest_id,
                    schema.backtest_daily_positions.c.vt_symbol == symbol,
                    schema.backtest_daily_positions.c.trade_date >= signal_date,
                )
            )
            .order_by(schema.backtest_daily_positions.c.trade_date)
            .limit(20)
        ).mappings().all()
        target_real_position = session.execute(
            select(schema.backtest_daily_positions)
            .where(
                and_(
                    schema.backtest_daily_positions.c.backtest_id == backtest_id,
                    schema.backtest_daily_positions.c.vt_symbol == symbol,
                    schema.backtest_daily_positions.c.trade_date == signal_date,
                )
            )
        ).mappings().first()
        universe_context = _universe_context(
            session,
            schema,
            symbol,
            run_params,
            board_payload,
        )
        planned_dicts = [dict(row) for row in same_day_signal_rows]
        target_theoretical_dicts = [dict(row) for row in target_theoretical_signal_rows]
        recommendation_dicts = [_recommendation_read_view(dict(row)) for row in same_day_recommendations]
        recommendation_dict = _recommendation_read_view(dict(recommendation)) if recommendation else None
        signal_snapshot = _signal_snapshot_for_date(
            session,
            schema,
            symbol,
            signal_date,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            min_entry_score=_safe_float(run_params.get("min_entry_score")) or 76.0,
        )
        theoretical_position_context = _theoretical_position_context(symbol, target_theoretical_dicts, signal_date)
        stock_names = load_stock_names(session, _symbols_from_many([{"vt_symbol": symbol}], planned_dicts, recommendation_dicts))

    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "run": dict(run),
        "recommendation": recommendation_dict,
        "signal_rows": [dict(row) for row in signal_rows],
        "order_rows": [dict(row) for row in order_rows],
        "trade_rows": [dict(row) for row in trade_rows],
        "equity_row": dict(equity_row) if equity_row else None,
        "position_rows": [dict(row) for row in position_rows],
        "stock_names": stock_names,
        "not_planned_context": _not_planned_context(
            run=dict(run),
            run_params=run_params,
            symbol=symbol,
            signal_date=signal_date,
            recommendation=recommendation_dict,
            same_day_recommendations=recommendation_dicts,
            same_day_signal_rows=planned_dicts,
            signal_bounds=dict(signal_bounds) if signal_bounds else {},
            universe_context=universe_context,
            theoretical_position_context=theoretical_position_context,
            target_real_position=dict(target_real_position) if target_real_position else None,
            signal_snapshot=signal_snapshot,
            stock_names=stock_names,
        ),
    }


def _run_params(run: dict[str, Any]) -> dict[str, Any]:
    raw = run.get("params") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def _universe_context(
    session,
    schema: Any,
    symbol: str,
    params: dict[str, Any],
    board_payload: BoardPayload,
) -> dict[str, Any]:
    max_symbols = _safe_int(params.get("max_symbols"), 5000)
    included_boards = list(normalize_included_boards(params.get("included_boards") or DEFAULT_QUANT_INCLUDED_BOARDS))
    rows = session.execute(
        select(
            schema.stocks.c.vt_symbol,
            schema.stocks.c.name,
            schema.stocks.c.exchange,
            schema.stocks.c.turnover,
            schema.stocks.c.market_cap,
        )
        .where(schema.stocks.c.vt_symbol != "000001.SSE")
        .order_by(schema.stocks.c.vt_symbol)
        .limit(5000)
    ).mappings().all()
    allowed = set(included_boards)
    target_rank = None
    target_row = None
    allowed_count = 0
    for row in rows:
        stock = dict(row)
        board = board_payload(stock["vt_symbol"], stock).get("board")
        if board not in allowed:
            continue
        allowed_count += 1
        if stock["vt_symbol"] == symbol:
            target_rank = allowed_count
            target_row = stock
            break
    return {
        "included_boards": included_boards,
        "max_symbols": max_symbols,
        "target_universe_rank": target_rank,
        "target_in_universe": target_rank is not None and target_rank <= max_symbols,
        "target_stock": target_row,
    }


def _not_planned_context(
    *,
    run: dict[str, Any],
    run_params: dict[str, Any],
    symbol: str,
    signal_date: date,
    recommendation: dict[str, Any] | None,
    same_day_recommendations: list[dict[str, Any]],
    same_day_signal_rows: list[dict[str, Any]],
    signal_bounds: dict[str, Any],
    universe_context: dict[str, Any],
    theoretical_position_context: dict[str, Any],
    target_real_position: dict[str, Any] | None,
    signal_snapshot: dict[str, Any] | None,
    stock_names: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buy_recommendations = [row for row in same_day_recommendations if str(row.get("action") or "").upper() == "BUY"]
    watch_recommendations = [row for row in same_day_recommendations if str(row.get("action") or "").upper() == "WATCH"]
    buy_signals = [row for row in same_day_signal_rows if str(row.get("side") or "").upper() == "BUY"]
    sell_signals = [row for row in same_day_signal_rows if str(row.get("side") or "").upper() == "SELL"]
    target_signal_rank, target_signal_row = _target_signal_context(symbol, buy_signals)
    target_execution = _signal_execution_context(target_signal_row)
    first_signal_date = _as_iso(signal_bounds.get("first_signal_date"))
    last_signal_date = _as_iso(signal_bounds.get("last_signal_date"))
    likely_reason, likely_reason_label = _not_planned_reason(
        signal_date=signal_date,
        recommendation=recommendation,
        same_day_signal_rows=same_day_signal_rows,
        first_signal_date=signal_bounds.get("first_signal_date"),
        last_signal_date=signal_bounds.get("last_signal_date"),
        universe_context=universe_context,
    )
    return {
        "likely_reason": likely_reason,
        "likely_reason_label": likely_reason_label,
        "backtest_start_date": _as_iso(run.get("start_date")),
        "backtest_end_date": _as_iso(run.get("end_date")),
        "first_signal_date": first_signal_date,
        "last_signal_date": last_signal_date,
        "signal_event_count": int(signal_bounds.get("signal_event_count") or 0),
        "signal_date_has_plan": bool(same_day_signal_rows),
        "signal_date_plan_count": len(same_day_signal_rows),
        "signal_date_buy_plan_count": len(buy_signals),
        "signal_date_sell_plan_count": len(sell_signals),
        "candidate_limit": _safe_int(run_params.get("candidate_limit"), 20),
        "max_positions": _safe_int(run_params.get("max_positions"), 8),
        "max_symbols": universe_context.get("max_symbols"),
        "included_boards": universe_context.get("included_boards") or [],
        "target_in_universe": universe_context.get("target_in_universe"),
        "target_universe_rank": universe_context.get("target_universe_rank"),
        "recommendation_run_id": (recommendation or {}).get("run_id"),
        "recommendation_rank": (recommendation or {}).get("rank"),
        "recommendation_action": (recommendation or {}).get("action"),
        "recommendation_score": (recommendation or {}).get("total_score"),
        "target_signal_rank": target_signal_rank,
        "target_signal_score": target_signal_row.get("score") if target_signal_row else None,
        "target_signal_setup": _signal_setup_type(target_signal_row),
        "target_execution_lane": target_execution.get("execution_lane"),
        "target_raw_signal_rank": target_execution.get("raw_signal_rank"),
        "target_execution_candidate_rank": target_execution.get("execution_candidate_rank"),
        "target_execution_candidate_selected": target_execution.get("execution_candidate_selected"),
        "target_theoretical_held_on_signal_date": bool(theoretical_position_context.get("held")),
        "target_theoretical_entry_date": theoretical_position_context.get("entry_date"),
        "target_real_held_on_signal_date": bool(target_real_position),
        "target_real_entry_date": _as_iso((target_real_position or {}).get("entry_date")),
        "signal_snapshot": signal_snapshot,
        "target_exceeds_candidate_limit": (
            (
                target_execution.get("execution_candidate_selected") is False
                if target_execution
                else target_signal_rank is not None
            )
            and (
                target_execution.get("execution_candidate_rank") is None
                if target_execution
                else target_signal_rank > _safe_int(run_params.get("candidate_limit"), 20)
            )
        ),
        "persisted_recommendation_count": len(same_day_recommendations),
        "persisted_buy_candidate_count": len(buy_recommendations),
        "persisted_watch_candidate_count": len(watch_recommendations),
        "same_day_top_recommendations": _top_recommendation_context(same_day_recommendations, stock_names),
        "planned_buy_symbols": _top_signal_context(buy_signals, stock_names),
        "target_symbol": symbol,
    }


def _theoretical_position_context(symbol: str, same_day_signal_rows: list[dict[str, Any]], signal_date: date) -> dict[str, Any]:
    """Infer whether the theoretical signal ledger already holds the target."""

    events = [
        row
        for row in same_day_signal_rows
        if str(row.get("vt_symbol") or "") == symbol
        and (_theoretical_event_effective_date(row) or date.min) <= signal_date
    ]
    events.sort(
        key=lambda row: (
            _theoretical_event_effective_date(row) or date.min,
            _as_date(row.get("signal_date")) or date.min,
            int(row.get("id") or 0),
        )
    )
    entry_date = None
    held = False
    for row in events:
        side = str(row.get("side") or "").upper()
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        status = str(raw.get("status") or row.get("plan_status") or "filled").lower()
        if status not in {"filled", "", "planned"}:
            continue
        if side == "BUY":
            held = True
            entry_date = _as_iso(_theoretical_event_effective_date(row))
        elif side == "SELL":
            held = False
            entry_date = None
    return {"held": held, "entry_date": entry_date}


def _theoretical_event_effective_date(row: dict[str, Any]) -> date | None:
    return _as_date(row.get("execute_date") or row.get("trade_date") or row.get("signal_date"))


def _target_signal_context(symbol: str, buy_signals: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    for index, row in enumerate(buy_signals, start=1):
        if str(row.get("vt_symbol") or "") == symbol:
            return index, row
    return None, None


def _signal_setup_type(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    return evidence.get("setup_type") or evidence.get("entry_setup")


def _signal_execution_context(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    context = raw.get("candidate_execution") if isinstance(raw.get("candidate_execution"), dict) else {}
    return dict(context)


def _not_planned_reason(
    *,
    signal_date: date,
    recommendation: dict[str, Any] | None,
    same_day_signal_rows: list[dict[str, Any]],
    first_signal_date: Any,
    last_signal_date: Any,
    universe_context: dict[str, Any],
) -> tuple[str, str]:
    if recommendation is None:
        return "not_in_persisted_candidates", "未进入该日落库候选"
    if not universe_context.get("target_in_universe"):
        rank = universe_context.get("target_universe_rank")
        if rank:
            return "outside_backtest_universe", f"股票池排名第 {rank}，超过回测 max_symbols"
        return "outside_backtest_universe", "不在该回测股票池"
    parsed_first = _as_date(first_signal_date)
    parsed_last = _as_date(last_signal_date)
    if parsed_first and signal_date < parsed_first:
        return "before_first_signal_date", f"信号日早于该回测首个可复盘信号日 {parsed_first.isoformat()}"
    if parsed_last and signal_date > parsed_last:
        return "after_last_signal_date", f"信号日晚于该回测最后可复盘信号日 {parsed_last.isoformat()}"
    if not same_day_signal_rows:
        return "signal_date_has_no_plan", "该信号日没有生成回测理论计划"
    return "not_in_same_day_plan", "该股票不在该信号日理论计划中"


def _top_recommendation_context(rows: list[dict[str, Any]], stock_names: dict[str, dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    result = []
    for row in rows[:limit]:
        symbol = str(row.get("vt_symbol") or "")
        stock = stock_names.get(symbol) or {}
        result.append(
            {
                "vt_symbol": symbol,
                "name": stock.get("name"),
                "rank": row.get("rank"),
                "action": row.get("action"),
                "total_score": row.get("total_score"),
            }
        )
    return result


def _top_signal_context(rows: list[dict[str, Any]], stock_names: dict[str, dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    result = []
    for rank, row in enumerate(rows[:limit], start=1):
        symbol = str(row.get("vt_symbol") or "")
        stock = stock_names.get(symbol) or {}
        result.append(
            {
                "vt_symbol": symbol,
                "name": stock.get("name"),
                "rank": rank,
                "trade_date": _as_iso(row.get("trade_date")),
                "execute_date": _as_iso(row.get("execute_date")),
                "score": row.get("score"),
                "reason": row.get("reason"),
                "setup_type": _signal_setup_type(row),
            }
        )
    return result


def _recommendation_read_view(row: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.recommendation_row_to_api(row)


def _signal_snapshot_for_date(
    session: Any,
    schema: Any,
    symbol: str,
    signal_date: date,
    *,
    strategy_id: str,
    strategy_version: str,
    min_entry_score: float,
) -> dict[str, Any] | None:
    persisted = session.execute(
        select(schema.quant_stock_signals)
        .where(
            and_(
                schema.quant_stock_signals.c.trade_date == signal_date,
                schema.quant_stock_signals.c.vt_symbol == symbol,
                schema.quant_stock_signals.c.strategy_id == strategy_id,
                schema.quant_stock_signals.c.strategy_version == strategy_version,
            )
        )
        .order_by(desc(schema.quant_stock_signals.c.total_score), desc(schema.quant_stock_signals.c.id))
    ).mappings().first()
    if persisted:
        return _signal_snapshot_from_score_row(dict(persisted), min_entry_score, source="quant_stock_signals")

    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(
            and_(
                schema.stock_daily_bars.c.vt_symbol == symbol,
                schema.stock_daily_bars.c.trade_date >= signal_date - timedelta(days=360),
                schema.stock_daily_bars.c.trade_date <= signal_date,
            )
        )
        .order_by(schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    bars = [
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
        for row in rows
    ]
    if not bars or bars[-1].trade_date != signal_date:
        return None

    market_snapshot = market_context.compute_market_contexts(session, schema, [signal_date]).get(signal_date)
    market_payload = market_snapshot.to_dict() if market_snapshot else None
    market_return = _market_return_20d_for_audit(session, schema, signal_date)
    score = score_strategy(
        strategy_id,
        symbol,
        bars[-180:],
        signal_date,
        index_return_20d=(market_payload or {}).get("index_return_20d") or market_return.get("return_20d"),
        sector_score=screening_loaders.load_sector_scores(session, [symbol], signal_date).get(symbol),
        financial_score=screening_loaders.load_financial_scores(session, [symbol], signal_date, _as_date).get(symbol),
        fund_flow_score=screening_loaders.load_fund_flow_scores(session, [symbol], signal_date, _safe_float, _clamp).get(symbol),
        hot_rank_score=screening_loaders.load_hot_rank_scores(session, [symbol], signal_date, _safe_float, _clamp).get(symbol),
        lhb_score=screening_loaders.load_lhb_scores(session, [symbol], signal_date, _safe_float, _clamp).get(symbol),
    )
    if score.evidence.get("status") != "ready":
        return {
            "source": "dynamic_score",
            "trade_date": signal_date.isoformat(),
            "vt_symbol": symbol,
            "status": score.evidence.get("status") or "not_ready",
        }
    if market_payload:
        _attach_market_context_to_score(score, market_payload)
    return _signal_snapshot_from_score(
        score,
        min_entry_score,
        source="dynamic_score",
    )


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 4)


def _attach_market_context_to_score(score: Any, payload: dict[str, Any]) -> None:
    if not payload:
        return
    compact_keys = (
        "regime",
        "label",
        "market_score",
        "trend_score",
        "momentum_score",
        "breadth_score",
        "risk_score",
        "theme_state",
        "dominant_theme",
        "dominant_theme_id",
        "theme_strength",
        "fund_flow_state",
        "fund_flow_label",
        "fund_flow_score",
        "fund_flow_streak_days",
        "fund_flow_source",
        "main_net_inflow",
        "main_net_inflow_ratio",
        "fund_flow_worsening_days",
        "fund_flow_new_low",
        "fund_flow_recovery_from_streak_days",
        "market_warning_level",
        "market_warning_label",
        "recovery_state",
        "recovery_label",
        "index_return_5d",
        "index_return_20d",
        "drawdown_60d_pct",
        "source",
        "notes",
    )
    context = {key: payload.get(key) for key in compact_keys if key in payload}
    score.evidence["market_context"] = context
    score.evidence["market_context_summary"] = market_context.market_context_summary(payload)
    score.evidence["dynamic_market_regime"] = payload.get("regime")
    score.evidence["dynamic_market_label"] = payload.get("label")
    score.evidence["market_warning_level"] = payload.get("market_warning_level")
    score.evidence["market_warning_label"] = payload.get("market_warning_label")
    score.evidence["fund_flow_state"] = payload.get("fund_flow_state")
    score.evidence["fund_flow_label"] = payload.get("fund_flow_label")
    score.evidence["fund_flow_streak_days"] = payload.get("fund_flow_streak_days")
    score.evidence["fund_flow_source"] = payload.get("fund_flow_source")
    score.evidence["recovery_state"] = payload.get("recovery_state")
    score.evidence["recovery_label"] = payload.get("recovery_label")


def _signal_snapshot_from_score_row(row: dict[str, Any], min_entry_score: float, *, source: str) -> dict[str, Any]:
    class _RowScore:
        pass

    item = _RowScore()
    item.vt_symbol = str(row.get("vt_symbol") or "")
    item.trade_date = row.get("trade_date")
    item.signal_type = str(row.get("signal_type") or row.get("strategy_id") or "")
    item.total_score = float(row.get("total_score") or 0.0)
    item.relative_strength_score = float(row.get("relative_strength_score") or 0.0)
    item.washout_score = float(row.get("washout_score") or 0.0)
    item.trend_quality_score = float(row.get("trend_quality_score") or 0.0)
    item.sector_mainline_score = float(row.get("sector_mainline_score") or 0.0)
    item.financial_improvement_score = float(row.get("financial_improvement_score") or 0.0)
    item.liquidity_score = float(row.get("liquidity_score") or 0.0)
    item.risk_score = float(row.get("risk_score") or 0.0)
    item.entry_signal = bool(row.get("entry_signal"))
    item.evidence = dict(row.get("evidence") or {})
    return _signal_snapshot_from_score(item, min_entry_score, source=source, run_id=row.get("run_id"))


def _signal_snapshot_from_score(score: Any, min_entry_score: float, *, source: str, run_id: Any = None) -> dict[str, Any]:
    payload = screening_payloads.symbol_signal_row(score, min_entry_score)
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    snapshot = {
        "source": source,
        "run_id": run_id,
        "trade_date": payload.get("trade_date"),
        "vt_symbol": payload.get("vt_symbol"),
        "total_score": payload.get("total_score"),
        "raw_entry_signal": payload.get("raw_entry_signal"),
        "executable_entry_signal": payload.get("executable_entry_signal"),
        "action": payload.get("action"),
        "failed_rules": payload.get("failed_rules") or [],
        "signal_label": payload.get("signal_label"),
        "signal_role": payload.get("signal_role"),
        "entry_setup": evidence.get("entry_setup") or evidence.get("setup_type"),
        "low_suction_days": evidence.get("low_suction_days"),
        "low_suction_launch_confirmed": evidence.get("low_suction_launch_confirmed"),
        "low_suction_launch_quality_bucket": evidence.get("low_suction_launch_quality_bucket"),
        "ma_convergence_pct": evidence.get("ma_convergence_pct"),
        "latest_change_pct": evidence.get("latest_change_pct"),
        "close_location_in_range": evidence.get("close_location_in_range"),
    }
    return {key: value for key, value in snapshot.items() if value is not None}


def _symbols_from_many(*row_groups: list[dict[str, Any]]) -> list[str]:
    symbols = set()
    for rows in row_groups:
        for row in rows:
            symbol = str(row.get("vt_symbol") or "").strip().upper()
            if symbol:
                symbols.add(symbol)
    return sorted(symbols)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def _as_iso(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def audit_rows(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    normalize_symbol: SymbolNormalizer,
    load_stock_names: StockNameLoader,
    symbols_from_rows: RowsSymbols,
    with_stock_names: NameAppender,
    to_api: ApiMapper,
    params_from_run: Callable[[dict[str, Any]], Any],
    params_to_json: Callable[[Any], dict[str, Any]],
    backtest_method: Callable[[Any], dict[str, Any]],
    audit_events: Callable[[list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]],
    order_stats: Callable[[list[dict[str, Any]]], dict[str, Any]],
    backtest_id: int,
    vt_symbol: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    ensure_schema()
    symbol = normalize_symbol(vt_symbol) if vt_symbol else None
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}

        order_query = (
            select(schema.backtest_orders)
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        )
        trade_query = (
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        )
        if symbol:
            order_query = order_query.where(schema.backtest_orders.c.vt_symbol == symbol)
            trade_query = trade_query.where(schema.backtest_trades.c.vt_symbol == symbol)

        orders = session.execute(order_query.limit(min(max(limit, 1), 1000))).mappings().all()
        trades = session.execute(trade_query.limit(min(max(limit, 1), 1000))).mappings().all()
        order_dicts = [dict(row) for row in orders]
        trade_dicts = [dict(row) for row in trades]
        stock_names = load_stock_names(session, symbols_from_rows(order_dicts, trade_dicts))

    params = params_from_run(dict(run))
    order_items = [to_api(row) for row in with_stock_names(order_dicts, stock_names)]
    trade_items = [to_api(row) for row in with_stock_names(trade_dicts, stock_names)]
    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "vt_symbol": symbol,
        "strategy_id": run["strategy_id"],
        "strategy_version": run["strategy_version"],
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "method": backtest_method(params),
        "params": params_to_json(params),
        "orders": order_items,
        "trades": trade_items,
        "events": audit_events(order_items, trade_items),
        "order_summary": order_stats(order_items),
        "note": "组合回测会在历史每个交易日重新计算可见候选；默认日线模型用上一交易日候选在下一交易日开盘撮合，不是把今天候选名单套到过去。",
    }


def reason_label(reason: Any) -> str | None:
    text = str(reason or "").strip()
    if not text:
        return None
    labels = {
        "entry_signal": "买入信号",
        "support_stop": "支撑止损",
        "trend_break": "趋势破位",
        "trend_trailing_stop": "趋势回撤",
        "time_efficiency_stop": "时间效率",
        "dynamic_failed_launch_exit_stop": "动态失败启动撤退",
        "dynamic_failed_launch_replacement_quality_gate": "动态失败启动后替换质量闸门",
        "mid_profit_giveback_stop": "中段浮盈回撤",
        "low_suction_failed_follow_branch_stop": "低吸确认后没拉起撤",
        "low_suction_opened_space_giveback_stop": "低吸打开空间后回撤",
        "stop_loss": "止损",
        "take_profit": "止盈",
        "trailing_stop": "移动止盈/回撤止损",
        "profit_protection_stop": "浮盈保护",
        "fragile_structure_stop": "脆弱结构破位",
        "time_stop": "持仓超时",
        "missing_1430_snapshot": "缺14:30快照",
        "tail_entry_not_triggered": "尾盘入场未触发",
        "tail_exit_not_triggered": "尾盘卖出未触发",
        "limit_up_open_blocked": "开盘涨停买不到",
        "limit_up_tail_unfilled": "涨停买不到",
        "limit_down_open_blocked": "开盘跌停卖不出",
        "limit_down_tail_blocked": "跌停卖不出",
        "no_execute_bar": "缺少执行日K线",
        "limit_up_or_no_bar": "涨停或缺少执行日K线",
        "position_slot_unavailable": "持仓名额不足",
        "insufficient_cash": "现金不足",
        "minute_tail_entry_unavailable_or_not_triggered": "尾盘分钟不可用或未触发",
        "not_ordered": "未下单",
        "not_selected": "未入选",
        "candidate_not_planned": "候选未进入组合计划",
        "watch_not_bought": "观察未买",
        "planned_not_ordered": "计划未下单",
        "rotation_for_stronger_signal": "强信号换仓",
        "rotation_for_stealth_low_suction": "低吸洗盘换仓",
        "rotation_for_protected_weak_holding_candidate": "趋势保护弱持仓换仓",
        "low_suction_branch_replacement_quality_gate": "低吸分支替换质量闸门",
    }
    return labels.get(text, text)


def drilldown_date_options(
    equity_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    recommendation_rows: list[dict[str, Any]] | None = None,
    *,
    as_date: DateParser,
    to_api: ApiMapper,
) -> list[dict[str, Any]]:
    by_date: dict[date, dict[str, Any]] = {}
    recommendations_by_signal_date: dict[date, dict[str, int]] = {}
    applied_signal_dates_by_trade_date: dict[date, set[date]] = {}
    for row in recommendation_rows or []:
        signal_date = as_date(row.get("trade_date"))
        if signal_date is None:
            continue
        counts = recommendations_by_signal_date.setdefault(signal_date, {"buy": 0, "watch": 0})
        action = str(row.get("action") or "").upper()
        if action == "BUY":
            counts["buy"] += 1
        elif action == "WATCH":
            counts["watch"] += 1

    def item_for(value: Any) -> dict[str, Any] | None:
        trade_date = as_date(value)
        if trade_date is None:
            return None
        return by_date.setdefault(
            trade_date,
            {
                "trade_date": trade_date,
                "cash": None,
                "market_value": None,
                "total_equity": None,
                "drawdown_pct": None,
                "position_count": 0,
                "buy_trade_count": 0,
                "sell_trade_count": 0,
                "buy_candidate_count": 0,
                "watch_candidate_count": 0,
                "buy_signal_count": 0,
                "sell_signal_count": 0,
                "filled_order_count": 0,
                "rejected_order_count": 0,
                "signal_event_count": 0,
                "position_snapshot_count": 0,
            },
        )

    for row in equity_rows:
        item = item_for(row.get("trade_date"))
        if item is None:
            continue
        item["cash"] = row.get("cash")
        item["market_value"] = row.get("market_value")
        item["total_equity"] = row.get("total_equity")
        item["drawdown_pct"] = row.get("drawdown_pct")
        item["position_count"] = int(row.get("position_count") or 0)
    for row in trade_rows:
        item = item_for(row.get("trade_date"))
        if item is None:
            continue
        if str(row.get("side") or "").upper() == "BUY":
            item["buy_trade_count"] += 1
        elif str(row.get("side") or "").upper() == "SELL":
            item["sell_trade_count"] += 1
    for row in order_rows:
        item = item_for(row.get("trade_date"))
        if item is None:
            continue
        if str(row.get("status") or "") == "filled":
            item["filled_order_count"] += 1
        elif str(row.get("status") or "") == "rejected":
            item["rejected_order_count"] += 1
    for row in signal_rows:
        trade_date = as_date(row.get("trade_date"))
        item = item_for(trade_date)
        if item is not None:
            item["signal_event_count"] += 1
            side = str(row.get("side") or "").upper()
            if side == "BUY":
                item["buy_signal_count"] += 1
            elif side == "SELL":
                item["sell_signal_count"] += 1
            signal_date = as_date(row.get("signal_date"))
            if signal_date is not None:
                counts = recommendations_by_signal_date.get(signal_date)
                applied = applied_signal_dates_by_trade_date.setdefault(trade_date, set()) if trade_date is not None else set()
                if counts and signal_date not in applied:
                    item["buy_candidate_count"] += counts["buy"]
                    item["watch_candidate_count"] += counts["watch"]
                    applied.add(signal_date)
    for row in position_rows:
        item = item_for(row.get("trade_date"))
        if item is not None:
            item["position_snapshot_count"] += 1

    return [to_api(row) for _, row in sorted(by_date.items(), reverse=True)]


def drilldown_symbol_options(
    trade_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    stock_names: dict[str, dict[str, Any]],
    *,
    as_date: DateParser,
    normalize_symbol: SymbolNormalizer,
    board_payload: BoardPayload,
    to_api: ApiMapper,
) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}

    def item_for(vt_symbol: Any) -> dict[str, Any] | None:
        symbol = normalize_symbol(vt_symbol)
        if not symbol:
            return None
        item = by_symbol.get(symbol)
        if item is None:
            stock = stock_names.get(symbol) or {}
            item = {
                "vt_symbol": symbol,
                **board_payload(symbol, stock),
                "name": stock.get("name"),
                "trade_count": 0,
                "buy_trade_count": 0,
                "sell_trade_count": 0,
                "order_count": 0,
                "filled_order_count": 0,
                "rejected_order_count": 0,
                "signal_event_count": 0,
                "buy_signal_count": 0,
                "sell_signal_count": 0,
                "position_day_count": 0,
                "first_signal_date": None,
                "first_trade_date": None,
                "last_trade_date": None,
                "status": "unknown",
                "status_label": "待核查",
                "main_reason": None,
                "main_reason_label": None,
            }
            by_symbol[symbol] = item
        return item

    def update_min(item: dict[str, Any], key: str, value: Any) -> None:
        current = as_date(item.get(key))
        next_value = as_date(value)
        if next_value is not None and (current is None or next_value < current):
            item[key] = next_value

    def update_max(item: dict[str, Any], key: str, value: Any) -> None:
        current = as_date(item.get(key))
        next_value = as_date(value)
        if next_value is not None and (current is None or next_value > current):
            item[key] = next_value

    for row in trade_rows:
        item = item_for(row.get("vt_symbol"))
        if item is None:
            continue
        side = str(row.get("side") or "").upper()
        item["trade_count"] += 1
        if side == "BUY":
            item["buy_trade_count"] += 1
        elif side == "SELL":
            item["sell_trade_count"] += 1
        update_min(item, "first_trade_date", row.get("trade_date"))
        update_max(item, "last_trade_date", row.get("trade_date"))
    for row in order_rows:
        item = item_for(row.get("vt_symbol"))
        if item is None:
            continue
        item["order_count"] += 1
        if str(row.get("status") or "") == "filled":
            item["filled_order_count"] += 1
        elif str(row.get("status") or "") == "rejected":
            item["rejected_order_count"] += 1
            if not item.get("main_reason"):
                item["main_reason"] = row.get("reason")
                item["main_reason_label"] = reason_label(row.get("reason"))
    for row in signal_rows:
        item = item_for(row.get("vt_symbol"))
        if item is None:
            continue
        side = str(row.get("side") or "").upper()
        item["signal_event_count"] += 1
        if side == "BUY":
            item["buy_signal_count"] += 1
        elif side == "SELL":
            item["sell_signal_count"] += 1
        update_min(item, "first_signal_date", row.get("signal_date") or row.get("trade_date"))
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        if not item.get("main_reason") and raw.get("reason"):
            item["main_reason"] = raw.get("reason")
            item["main_reason_label"] = reason_label(raw.get("reason"))
    for row in position_rows:
        item = item_for(row.get("vt_symbol"))
        if item is not None:
            item["position_day_count"] += 1

    for item in by_symbol.values():
        if item["trade_count"] > 0:
            item["status"] = "traded"
            item["status_label"] = "有成交"
            if item["rejected_order_count"] == 0:
                item["main_reason"] = None
                item["main_reason_label"] = None
        elif item["rejected_order_count"] > 0:
            item["status"] = "rejected"
            item["status_label"] = "有拒单"
        elif item["signal_event_count"] > 0:
            item["status"] = "signal_only"
            item["status_label"] = "有信号未成交"
        elif item["position_day_count"] > 0:
            item["status"] = "position_only"
            item["status_label"] = "仅持仓快照"

    return [
        to_api(item)
        for item in sorted(
            by_symbol.values(),
            key=lambda row: (
                0 if row["trade_count"] else 1 if row["rejected_order_count"] else 2 if row["signal_event_count"] else 3,
                str(row.get("vt_symbol") or ""),
            ),
        )
    ]
