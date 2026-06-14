"""Database-backed quant screening orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, desc, func, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards, stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.quant.factors import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    Bar,
    SignalScore,
)
from alphaagent.server.services.quant import screening_loaders, screening_payloads, screening_persistence
from alphaagent.server.services.quant.financials import financial_coverage_summary
from alphaagent.server.services.quant.strategy_registry import get_strategy, score_strategy


DEFAULT_RECOMMENDATION_LIMIT = 20


def list_available_strategies() -> dict[str, Any]:
    from alphaagent.server.services.quant.strategy_registry import list_strategies

    items = list_strategies()
    return {"status": "ready", "items": items, "default_strategy_id": STRATEGY_ID}


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

    strategy = get_strategy(strategy_id)
    if strategy is None:
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
            score = score_strategy(
                strategy.id,
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
                # 信号日收盘价随 evidence 存储，供买卖计划预算与单股回测复用（免重算）
                bars = bars_by_symbol.get(vt_symbol, [])
                if bars:
                    score.evidence["close_price"] = float(bars[-1].close_price)
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
            run_id = _persist_screen_run(session, as_of, scored, recommendations, strategy.id, strategy.version, boards)
            if auto_portfolio:
                portfolio_sync = _sync_quant_candidate_group(session, recommendations, stock_meta, strategy.id, strategy.version)

    return {
        "status": "ready" if scored else "empty",
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
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


def screen_stocks_range(
    start: date | None = None,
    end: date | None = None,
    *,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 500,
    recommendation_limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    min_recommendation_score: float = 60.0,
    persist: bool = False,
    auto_portfolio: bool = True,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
) -> dict[str, Any]:
    """Run daily screens for every local trading date in a range."""

    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": [], "recommendations": [], "runs": []}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": [], "recommendations": [], "runs": []}
    _ensure_quant_schema()

    with session_scope() as session:
        latest = end or _latest_trade_date(session)
        if latest is None:
            return {"status": "empty", "message": "stock_daily_bars is empty", "items": [], "recommendations": [], "runs": []}
        start_date = start or _earliest_trade_date(session) or latest
        if start_date > latest:
            return {
                "status": "invalid_range",
                "message": "start date must be earlier than or equal to end date",
                "start_date": start_date.isoformat(),
                "end_date": latest.isoformat(),
                "items": [],
                "recommendations": [],
                "runs": [],
            }
        trade_dates = _trading_dates_between(session, start_date, latest)

    if not trade_dates:
        return {
            "status": "empty",
            "message": "no local trading dates in range",
            "start_date": start_date.isoformat(),
            "end_date": latest.isoformat(),
            "items": [],
            "recommendations": [],
            "runs": [],
        }

    runs = []
    latest_result: dict[str, Any] | None = None
    succeeded_count = 0
    range_recommendation_count = 0
    boards = list(normalize_included_boards(included_boards))

    for index, trade_date in enumerate(trade_dates):
        result = screen_stocks(
            trade_date,
            strategy_id=strategy.id,
            max_symbols=max_symbols,
            recommendation_limit=recommendation_limit,
            min_recommendation_score=min_recommendation_score,
            persist=persist,
            auto_portfolio=auto_portfolio and index == len(trade_dates) - 1,
            included_boards=boards,
        )
        latest_result = result
        status = str(result.get("status") or "empty")
        if status == "ready":
            succeeded_count += 1
        recommendation_count = int(result.get("recommendation_count") or 0)
        range_recommendation_count += recommendation_count
        runs.append(
            {
                "trade_date": trade_date.isoformat(),
                "status": status,
                "run_id": result.get("run_id"),
                "candidate_count": int(result.get("total") or 0),
                "recommendation_count": recommendation_count,
            }
        )

    latest_result = latest_result or {}
    status = "ready" if succeeded_count else str(latest_result.get("status") or "empty")
    return {
        "status": status,
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "start_date": trade_dates[0].isoformat(),
        "end_date": trade_dates[-1].isoformat(),
        "trade_date": latest_result.get("trade_date") or trade_dates[-1].isoformat(),
        "run_id": latest_result.get("run_id"),
        "total_dates": len(trade_dates),
        "succeeded_count": succeeded_count,
        "range_recommendation_count": range_recommendation_count,
        "total": int(latest_result.get("total") or 0),
        "recommendation_count": int(latest_result.get("recommendation_count") or 0),
        "included_boards": latest_result.get("included_boards") or boards,
        "items": latest_result.get("items") or [],
        "recommendations": latest_result.get("recommendations") or [],
        "portfolio_sync": latest_result.get("portfolio_sync"),
        "runs": runs,
    }


def list_signals(trade_date: date | None = None, strategy_id: str = STRATEGY_ID, limit: int = 100) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        run = _latest_screen_run(session, strategy.id, trade_date)
        as_of = run["trade_date"] if run else trade_date or _latest_signal_date(session) or _latest_trade_date(session)
        if as_of is None:
            return {"status": "empty", "items": []}
        filters = (
            [schema.quant_stock_signals.c.run_id == run["id"]]
            if run
            else [
                schema.quant_stock_signals.c.trade_date == as_of,
                schema.quant_stock_signals.c.strategy_id == strategy.id,
                schema.quant_stock_signals.c.strategy_version == strategy.version,
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
        "strategy_id": strategy.id,
        "strategy_version": str(run["strategy_version"]) if run else strategy.version,
        "included_boards": _run_included_boards(run),
        "items": [_mapping_to_api(dict(row)) for row in rows],
    }


def list_screen_runs(strategy_id: str = STRATEGY_ID, limit: int = 120) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.quant_signal_runs)
            .where(schema.quant_signal_runs.c.strategy_id == strategy.id)
            .order_by(desc(schema.quant_signal_runs.c.trade_date), desc(schema.quant_signal_runs.c.id))
            .limit(min(max(limit, 1), 500))
        ).mappings().all()
        row_dicts = [dict(row) for row in rows]
        run_ids = [int(row["id"]) for row in row_dicts]
        action_counts: dict[int, dict[str, int]] = {run_id: {"BUY": 0, "WATCH": 0} for run_id in run_ids}
        if run_ids:
            count_rows = session.execute(
                select(
                    schema.quant_recommendations.c.run_id,
                    schema.quant_recommendations.c.action,
                    func.count().label("count"),
                )
                .where(schema.quant_recommendations.c.run_id.in_(run_ids))
                .group_by(schema.quant_recommendations.c.run_id, schema.quant_recommendations.c.action)
            ).mappings().all()
            for count_row in count_rows:
                run_id = int(count_row["run_id"])
                action = str(count_row["action"] or "").upper()
                if action in {"BUY", "WATCH"}:
                    action_counts.setdefault(run_id, {"BUY": 0, "WATCH": 0})[action] = int(count_row["count"] or 0)
        items = []
        for row in row_dicts:
            payload = _mapping_to_api(row)
            counts = action_counts.get(int(row["id"]), {"BUY": 0, "WATCH": 0})
            payload["buy_recommendation_count"] = counts["BUY"]
            payload["watch_recommendation_count"] = counts["WATCH"]
            items.append(payload)
    return {"status": "ready" if rows else "empty", "items": items}


def list_trading_dates(start: date | None = None, end: date | None = None, limit: int = 600) -> dict[str, Any]:
    """List local A-share trading dates from daily bar storage."""

    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_quant_schema()

    filters = []
    if start is not None:
        filters.append(schema.stock_daily_bars.c.trade_date >= start)
    if end is not None:
        filters.append(schema.stock_daily_bars.c.trade_date <= end)

    query = (
        select(
            schema.stock_daily_bars.c.trade_date,
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)).label("symbol_count"),
        )
        .group_by(schema.stock_daily_bars.c.trade_date)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(min(max(limit, 1), 2000))
    )
    if filters:
        query = query.where(and_(*filters))

    with session_scope() as session:
        rows = session.execute(query).mappings().all()

    items = [
        {
            "trade_date": row["trade_date"].isoformat(),
            "symbol_count": int(row["symbol_count"] or 0),
        }
        for row in rows
    ]
    return {
        "status": "ready" if items else "empty",
        "items": items,
        "latest_trade_date": items[0]["trade_date"] if items else None,
        "returned_count": len(items),
    }


def list_recommendations(trade_date: date | None = None, strategy_id: str = STRATEGY_ID, limit: int = 50) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_quant_schema()
    with session_scope() as session:
        run = _latest_screen_run(session, strategy.id, trade_date)
        as_of = run["trade_date"] if run else trade_date or _latest_recommendation_date(session) or _latest_trade_date(session)
        if as_of is None:
            return {"status": "empty", "items": []}
        filters = (
            [schema.quant_recommendations.c.run_id == run["id"]]
            if run
            else [
                schema.quant_recommendations.c.trade_date == as_of,
                schema.quant_recommendations.c.strategy_id == strategy.id,
                schema.quant_recommendations.c.strategy_version == strategy.version,
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
        "strategy_id": strategy.id,
        "strategy_version": str(run["strategy_version"]) if run else strategy.version,
        "included_boards": _run_included_boards(run),
        "items": [_recommendation_row_to_api(dict(row)) for row in rows],
    }


def latest_trade_plan(vt_symbol: str, strategy_id: str = STRATEGY_ID) -> dict[str, Any]:
    """返回某股最近一次候选的买卖计划（risk_control.trade_plan）。

    候选筛选时已预算并存储买卖计划，单股详情直接读取，避免重跑回测。
    """
    symbol = str(vt_symbol or "").strip().upper()
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id}
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
            .where(
                and_(
                    schema.quant_recommendations.c.vt_symbol == symbol,
                    schema.quant_recommendations.c.strategy_id == strategy.id,
                )
            )
            .order_by(desc(schema.quant_recommendations.c.trade_date))
            .limit(1)
        ).mappings().first()
    if not row:
        return {"status": "empty", "vt_symbol": symbol, "message": "该股未在候选列表中"}
    risk_control = row.get("risk_control") or {}
    trade_plan = risk_control.get("trade_plan") if isinstance(risk_control, dict) else None
    return {
        "status": "ready" if trade_plan else "no_plan",
        "vt_symbol": symbol,
        "name": row.get("stock_name"),
        "trade_date": row["trade_date"].isoformat() if row.get("trade_date") else None,
        "strategy_id": strategy.id,
        "rank": row.get("rank"),
        "action": row.get("action"),
        "total_score": row.get("total_score"),
        "trade_plan": trade_plan,
        "risk_control": risk_control,
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
    strategy_id: str = STRATEGY_ID,
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
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
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
        financial_coverage = financial_coverage_summary(session, symbol, latest)
        bars = _load_bars(session, [symbol], latest, lookback_days=max((latest - earliest).days + 120, 200)).get(symbol, [])
        trade_dates = [bar.trade_date for bar in bars if earliest <= bar.trade_date <= latest]
        effective_min_entry_score = (
            float(min_entry_score)
            if min_entry_score is not None and float(min_entry_score) != 68.0
            else float(strategy.default_min_entry_score)
        )
        rows = []
        for trade_date in trade_dates:
            index_return_20d = _load_index_return_20d(session, trade_date)
            sector_score = _load_sector_scores(session, [symbol], trade_date).get(symbol)
            financial_score = _load_financial_scores(session, [symbol], trade_date).get(symbol)
            fund_flow_score = _load_fund_flow_scores(session, [symbol], trade_date).get(symbol)
            hot_rank_score = _load_hot_rank_scores(session, [symbol], trade_date).get(symbol)
            lhb_score = _load_lhb_scores(session, [symbol], trade_date).get(symbol)
            score = score_strategy(
                strategy.id,
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
            rows.append(_symbol_signal_row(score, effective_min_entry_score))

    trigger_rows = [row for row in rows if row["entry_signal"]]
    near_rows = sorted(rows, key=lambda row: _symbol_signal_fit_key(row, strategy.id))[:limit]
    recent_rows = sorted(rows, key=lambda row: row["trade_date"], reverse=True)[:limit]
    best_total = max(rows, key=lambda row: float(row["total_score"]), default=None)
    best_entry_fit = near_rows[0] if near_rows else None
    scored_date_count = len(rows)
    return {
        "status": "ready" if rows else "empty",
        "vt_symbol": symbol,
        "name": stock.get("name"),
        **stock_board_payload(symbol, stock.get("exchange")),
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "start_date": earliest.isoformat() if earliest else None,
        "end_date": latest.isoformat(),
        "scored_date_count": scored_date_count,
        "entry_signal_count": len(trigger_rows),
        "watch_count": max(scored_date_count - len(trigger_rows), 0),
        "entry_signals": trigger_rows[:limit],
        "best_total_score": best_total,
        "best_entry_fit": best_entry_fit,
        "near_misses": near_rows,
        "recent": recent_rows,
        "financial_coverage": financial_coverage,
        "rule": _strategy_rule_payload(strategy.id, effective_min_entry_score),
    }


def symbol_strategy_comparison(
    vt_symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    """Compare every registered strategy for one stock and date range."""

    strategies = list_available_strategies().get("items") or []
    items: list[dict[str, Any]] = []
    base_payload: dict[str, Any] | None = None
    for strategy in strategies:
        strategy_id = str(strategy.get("id") or "")
        history = symbol_signal_history(
            vt_symbol,
            strategy_id=strategy_id,
            start=start,
            end=end,
            min_entry_score=float(strategy.get("default_min_entry_score") or 68.0),
            limit=limit,
        )
        if history.get("status") not in {"ready", "empty"}:
            items.append(
                {
                    "strategy": strategy,
                    "status": history.get("status"),
                    "strategy_id": strategy_id,
                    "strategy_version": strategy.get("version"),
                    "message": history.get("message"),
                    "scored_date_count": 0,
                    "entry_signal_count": 0,
                    "watch_count": 0,
                    "best_entry_fit": None,
                    "best_total_score": None,
                    "entry_signals": [],
                    "recent": [],
                    "rule": {},
                }
            )
            continue
        if base_payload is None:
            base_payload = {
                "vt_symbol": history.get("vt_symbol"),
                "name": history.get("name"),
                "board": history.get("board"),
                "board_label": history.get("board_label"),
                "start_date": history.get("start_date"),
                "end_date": history.get("end_date"),
                "financial_coverage": history.get("financial_coverage"),
            }
        recent = history.get("recent") or []
        items.append(
            {
                "strategy": strategy,
                "status": history.get("status"),
                "strategy_id": history.get("strategy_id") or strategy_id,
                "strategy_version": history.get("strategy_version") or strategy.get("version"),
                "scored_date_count": int(history.get("scored_date_count") or 0),
                "entry_signal_count": int(history.get("entry_signal_count") or 0),
                "watch_count": int(history.get("watch_count") or 0),
                "best_entry_fit": history.get("best_entry_fit"),
                "best_total_score": history.get("best_total_score"),
                "entry_signals": history.get("entry_signals") or [],
                "recent": recent,
                "rule": history.get("rule") or {},
            }
        )

    if base_payload is None:
        first = items[0] if items else {}
        return {
            "status": first.get("status") or "empty",
            "vt_symbol": str(vt_symbol or "").strip().upper(),
            "items": items,
        }
    return {
        "status": "ready",
        **base_payload,
        "items": items,
    }


def _ensure_quant_schema() -> None:
    """Allow quant screening to run from service calls, not only API startup."""

    schema.create_schema(get_engine())


def _latest_trade_date(session) -> date | None:
    return screening_loaders.latest_trade_date(session)


def _earliest_trade_date(session) -> date | None:
    return screening_loaders.earliest_trade_date(session)


def _latest_signal_date(session) -> date | None:
    return screening_loaders.latest_signal_date(session)


def _latest_recommendation_date(session) -> date | None:
    return screening_loaders.latest_recommendation_date(session)


def _latest_screen_run(session, strategy_id: str, trade_date: date | None = None) -> dict[str, Any] | None:
    strategy = get_strategy(strategy_id)
    strategy_version = strategy.version if strategy else STRATEGY_VERSION
    return screening_loaders.latest_screen_run(session, strategy_id, strategy_version, trade_date)


def _trading_dates_between(session, start: date, end: date) -> list[date]:
    return screening_loaders.trading_dates_between(session, start, end)


def _run_included_boards(run: dict[str, Any] | None) -> list[str]:
    return screening_loaders.run_included_boards(run)


def _load_bars(session, vt_symbols: list[str], trade_date: date, lookback_days: int) -> dict[str, list[Bar]]:
    return screening_loaders.load_bars(session, vt_symbols, trade_date, lookback_days)


def _load_stock_universe(session, max_symbols: int, included_boards: tuple[str, ...]) -> list[dict[str, Any]]:
    return screening_loaders.load_stock_universe(session, max_symbols, included_boards)


def _load_index_return_20d(session, trade_date: date) -> float | None:
    return screening_loaders.load_index_return_20d(session, trade_date)


def _load_sector_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_sector_scores(session, vt_symbols, trade_date)


def _load_financial_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_financial_scores(session, vt_symbols, trade_date, _parse_date)


def _load_fund_flow_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_fund_flow_scores(session, vt_symbols, trade_date, _float_or_none, _clamp)


def _load_hot_rank_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_hot_rank_scores(session, vt_symbols, trade_date, _float_or_none, _clamp)


def _load_lhb_scores(session, vt_symbols: list[str], trade_date: date) -> dict[str, float]:
    return screening_loaders.load_lhb_scores(session, vt_symbols, trade_date, _float_or_none, _clamp)


def _persist_screen_run(
    session,
    trade_date: date,
    scored: list[SignalScore],
    recommendations: list[SignalScore],
    strategy_id: str,
    strategy_version: str | tuple[str, ...] = STRATEGY_VERSION,
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS,
) -> int:
    if isinstance(strategy_version, tuple):
        included_boards = strategy_version
        strategy_version = STRATEGY_VERSION
    return screening_persistence.persist_screen_run(
        session,
        trade_date,
        scored,
        recommendations,
        strategy_id,
        strategy_version,
        included_boards,
    )


def _clear_existing_screen_outputs(session, trade_date: date, strategy_id: str, strategy_version: str = STRATEGY_VERSION) -> None:
    screening_persistence.clear_existing_screen_outputs(session, trade_date, strategy_id, strategy_version)


def _sync_quant_candidate_group(
    session,
    recommendations: list[SignalScore],
    stock_meta: dict[str, dict[str, Any]],
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
) -> dict[str, Any]:
    return screening_persistence.sync_quant_candidate_group(
        session,
        recommendations,
        stock_meta,
        strategy_id,
        strategy_version,
    )


def _ensure_auto_group(session, name: str, group_type: str, description: str) -> int:
    return screening_persistence.ensure_auto_group(session, name, group_type, description)


def _score_to_db(item: SignalScore, run_id: int | None, strategy_id: str, strategy_version: str = STRATEGY_VERSION) -> dict[str, Any]:
    return screening_payloads.score_to_db(item, run_id, strategy_id, strategy_version)


def _recommendation_to_db(
    rank: int,
    item: SignalScore,
    run_id: int | None,
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
    *,
    min_entry_score: float | None = None,
) -> dict[str, Any]:
    return screening_payloads.recommendation_to_db(
        rank,
        item,
        run_id,
        strategy_id,
        strategy_version,
        min_entry_score=min_entry_score,
    )


def _symbol_signal_row(item: SignalScore, min_entry_score: float) -> dict[str, Any]:
    return screening_payloads.symbol_signal_row(item, min_entry_score)


def _symbol_signal_fit_key(row: dict[str, Any], strategy_id: str) -> tuple[int, float, float]:
    return screening_payloads.symbol_signal_fit_key(row, strategy_id)


def _strategy_rule_payload(strategy_id: str, min_entry_score: float) -> dict[str, Any]:
    return screening_payloads.strategy_rule_payload(strategy_id, min_entry_score)


def _failed_entry_rules(item: SignalScore, min_entry_score: float) -> list[str]:
    return screening_payloads.failed_entry_rules(item, min_entry_score)


def _score_to_api(item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    return screening_payloads.score_to_api(item, stock)


def _recommendation_to_api(rank: int, item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    return screening_payloads.recommendation_to_api(rank, item, stock)


def default_risk_control() -> dict[str, Any]:
    return screening_payloads.default_risk_control()


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.mapping_to_api(row)


def _recommendation_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.recommendation_row_to_api(row)


def _normalize_quant_evidence(value: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.normalize_quant_evidence(value)


def _normalize_risk_control(value: dict[str, Any]) -> dict[str, Any]:
    return screening_payloads.normalize_risk_control(value)


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
