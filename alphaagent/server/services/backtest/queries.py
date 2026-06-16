"""Read-side helpers for AlphaAgent backtest reports and drilldowns."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

from sqlalchemy import and_, desc, func, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards

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
        "positions": [to_api(row) for row in named_positions],
        "trades": [to_api(row) for row in named_trades],
        "orders": [to_api(row) for row in with_stock_names(order_dicts, stock_names)],
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
    entry_raw = entry.get("raw") if isinstance((entry or {}).get("raw"), dict) else {}
    execution = entry_raw.get("execution") if isinstance(entry_raw.get("execution"), dict) else {}
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
            order_rows = []
            trade_rows = []
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
        universe_context = _universe_context(
            session,
            schema,
            symbol,
            run_params,
            board_payload,
        )
        planned_dicts = [dict(row) for row in same_day_signal_rows]
        recommendation_dicts = [dict(row) for row in same_day_recommendations]
        stock_names = load_stock_names(session, _symbols_from_many([{"vt_symbol": symbol}], planned_dicts, recommendation_dicts))

    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "run": dict(run),
        "recommendation": dict(recommendation) if recommendation else None,
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
            recommendation=dict(recommendation) if recommendation else None,
            same_day_recommendations=recommendation_dicts,
            same_day_signal_rows=planned_dicts,
            signal_bounds=dict(signal_bounds) if signal_bounds else {},
            universe_context=universe_context,
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
    max_symbols = _safe_int(params.get("max_symbols"), 500)
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
        .order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
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
    stock_names: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    buy_recommendations = [row for row in same_day_recommendations if str(row.get("action") or "").upper() == "BUY"]
    watch_recommendations = [row for row in same_day_recommendations if str(row.get("action") or "").upper() == "WATCH"]
    buy_signals = [row for row in same_day_signal_rows if str(row.get("side") or "").upper() == "BUY"]
    sell_signals = [row for row in same_day_signal_rows if str(row.get("side") or "").upper() == "SELL"]
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
        "persisted_recommendation_count": len(same_day_recommendations),
        "persisted_buy_candidate_count": len(buy_recommendations),
        "persisted_watch_candidate_count": len(watch_recommendations),
        "same_day_top_recommendations": _top_recommendation_context(same_day_recommendations, stock_names),
        "planned_buy_symbols": _top_signal_context(buy_signals, stock_names),
        "target_symbol": symbol,
    }


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
    for row in rows[:limit]:
        symbol = str(row.get("vt_symbol") or "")
        stock = stock_names.get(symbol) or {}
        result.append(
            {
                "vt_symbol": symbol,
                "name": stock.get("name"),
                "trade_date": _as_iso(row.get("trade_date")),
                "execute_date": _as_iso(row.get("execute_date")),
                "score": row.get("score"),
                "reason": row.get("reason"),
            }
        )
    return result


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
        "stop_loss": "止损",
        "take_profit": "止盈",
        "trailing_stop": "移动止盈/回撤止损",
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
