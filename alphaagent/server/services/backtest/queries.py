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
        "setup_market_exit_matrix": _setup_market_exit_matrix(enriched),
        "worst_buckets": _worst_setup_market_exit_buckets(enriched),
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
    elif state == "unknown":
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
        "note": "候选审计只用真实成交并闭仓的候选计算胜率；未成交候选只计数量，不用未来走势伪造收益。",
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
        and (_as_date(row.get("trade_date") or row.get("execute_date") or row.get("signal_date")) or date.min) <= signal_date
    ]
    events.sort(key=lambda row: (_as_date(row.get("signal_date")) or date.min, _as_date(row.get("trade_date")) or date.min, int(row.get("id") or 0)))
    entry_date = None
    held = False
    for row in events:
        side = str(row.get("side") or "").upper()
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        status = str(raw.get("status") or row.get("plan_status") or "filled")
        if status not in {"filled", "", "planned"}:
            continue
        if side == "BUY":
            held = True
            entry_date = _as_iso(row.get("trade_date") or row.get("execute_date") or row.get("signal_date"))
        elif side == "SELL":
            held = False
            entry_date = None
    return {"held": held, "entry_date": entry_date}


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
        "mid_profit_giveback_stop": "中段浮盈回撤",
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
