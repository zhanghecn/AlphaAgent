"""Daily-bar portfolio backtest for AlphaAgent quant strategies."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import and_, desc, func, select

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.boards import (
    DEFAULT_QUANT_INCLUDED_BOARDS,
    included_board_labels,
    normalize_included_boards,
    stock_board,
    stock_board_payload,
)
from alphaagent.market.symbols import INDEX_SYMBOLS
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.backtest import data_quality as data_quality_service
from alphaagent.server.services.backtest import execution_models, persistence, queries, reports, scoring, signal_plan, simulation, strategy_comparison, validation
from alphaagent.server.services.backtest.schemas import BacktestParams, MinuteBar, Position, ScoreContext, Trade
from alphaagent.server.services.quant.factors import STRATEGY_ID, STRATEGY_VERSION, Bar
from alphaagent.server.services.quant.financials import financial_scores_from_rows_by_symbol
from alphaagent.server.services.quant.strategy_registry import get_strategy
from alphaagent.server.services.quant.screening import (
    _load_financial_scores,
    _load_fund_flow_scores,
    _load_hot_rank_scores,
    _load_index_return_20d,
    _load_lhb_scores,
    _load_sector_scores,
)


SUPPORTED_BACKTEST_MINUTE_INTERVALS = execution_models.SUPPORTED_BACKTEST_MINUTE_INTERVALS
SUPPORTED_EXECUTION_MODELS = execution_models.SUPPORTED_EXECUTION_MODELS
BACKTEST_LOOKBACK_DAYS = 160


def run_backtest(params: BacktestParams) -> dict[str, Any]:
    strategy = get_strategy(params.strategy)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy": params.strategy}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()

    with session_scope() as session:
        end = params.end or session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()
        if end is None:
            return {"status": "empty", "message": "stock_daily_bars is empty"}
        vt_symbols = _load_symbol_universe(session, params.max_symbols, params.symbols, params.included_boards)
        if not vt_symbols:
            return {"status": "empty", "message": "stocks is empty"}
        bars_by_symbol = _load_all_bars(session, vt_symbols, _lookback_start(params.start), end)
        trading_days = _trading_days(bars_by_symbol, params.start, end)
        if len(trading_days) < 80:
            return {"status": "insufficient_data", "trading_days": len(trading_days)}

        stock_meta = _load_stock_meta(session, vt_symbols)
        score_context = _load_score_context(session, list(bars_by_symbol))
        run = _simulate(session, params, bars_by_symbol, trading_days, stock_meta, score_context=score_context)
        backtest_id = _persist_run(session, params, run, end) if params.persist else None

    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "strategy": params.strategy,
        "strategy_version": strategy.version,
        "start": params.start.isoformat(),
        "end": end.isoformat(),
        "metrics": run["metrics"],
        "equity": run["equity"],
        "trades": run["trades"],
        "orders": run["orders"],
        "signal_events": run.get("signal_events") or [],
        "assumptions": _backtest_assumptions(params),
    }


def get_backtest(backtest_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        row = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
    if not row:
        return {"status": "not_found", "id": backtest_id}
    return {"status": "ready", "item": _mapping_to_api(dict(row))}


def list_backtests(limit: int = 50, run_type: str = "all") -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    requested_type = str(run_type or "all").lower()
    item_limit = min(max(limit, 1), 200)
    query_limit = item_limit if requested_type == "all" else min(max(item_limit * 10, 200), 1000)
    with session_scope() as session:
        rows = session.execute(
            select(schema.backtest_runs).order_by(desc(schema.backtest_runs.c.id)).limit(query_limit)
        ).mappings().all()
    items = []
    for row in rows:
        payload = _mapping_to_api(dict(row))
        payload["run_type"] = _run_type_from_params(payload.get("params") or {})
        if requested_type in {"portfolio", "symbol"} and payload["run_type"] != requested_type:
            continue
        items.append(payload)
        if len(items) >= item_limit:
            break
    return {"status": "ready", "items": items}


def latest_symbol_backtest(vt_symbol: str, strategy_id: str | None = None) -> dict[str, Any]:
    """读某股最近的单股回测（trades + metrics），供单股详情免重算直接展示。

    单股回测 createSymbolBacktest persist=true 已存 backtest_runs + backtest_trades。
    单股详情进入/切换策略时读最近记录，无需重跑；仅"重新运行"才触发重算。
    """
    symbol = str(vt_symbol or "").strip().upper()
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.backtest_runs).order_by(desc(schema.backtest_runs.c.id)).limit(100)
        ).mappings().all()
        for row in rows:
            params = row.get("params") or {}
            symbols = params.get("symbols") or []
            if symbol not in symbols:
                continue
            if strategy_id and row.get("strategy_id") != strategy_id:
                continue
            backtest_id = int(row["id"])
            trades = session.execute(
                select(schema.backtest_trades)
                .where(schema.backtest_trades.c.backtest_id == backtest_id)
                .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
            ).mappings().all()
            return {
                "status": "ready",
                "backtest_id": backtest_id,
                "strategy_id": row.get("strategy_id"),
                "start_date": row["start_date"].isoformat() if row.get("start_date") else None,
                "end_date": row["end_date"].isoformat() if row.get("end_date") else None,
                "metrics": row.get("metrics") or {},
                "trade_count": len(trades),
                "trades": [_mapping_to_api(dict(t)) for t in trades],
            }
    return {"status": "empty", "vt_symbol": symbol, "message": "该股该策略暂无回测记录，可手动运行生成"}


def backtest_metrics(backtest_id: int) -> dict[str, Any]:
    detail = get_backtest(backtest_id)
    if detail.get("status") != "ready":
        return detail
    return {"status": "ready", "backtest_id": backtest_id, "metrics": detail["item"].get("metrics") or {}}


def backtest_minute_coverage(backtest_id: int) -> dict[str, Any]:
    """Summarize whether a persisted backtest can be read as real 14:30 execution."""

    report = backtest_report(backtest_id, trade_limit=1)
    if report.get("status") != "ready":
        return report
    quality = report.get("execution_quality") or {}
    method = report.get("method") or {}
    execution = method.get("execution") if isinstance(method.get("execution"), dict) else {}
    execution_model = str(execution.get("execution_model") or "unknown")
    buy_count = int(quality.get("buy_count") or 0)
    minute_1430_count = int(quality.get("minute_1430_count") or quality.get("minute_tail_entry_count") or 0)
    daily_close_proxy_count = int(quality.get("daily_close_proxy_count") or 0)
    strict_1430_rejected_count = int(
        quality.get("strict_1430_rejected_count")
        or quality.get("strict_tail_rejected_count")
        or 0
    )
    minute_gap_rejected_count = int(quality.get("minute_gap_rejected_count") or 0)
    tail_entry_rejected_count = int(quality.get("tail_entry_rejected_count") or 0)
    tail_exit_rejected_count = int(quality.get("tail_exit_rejected_count") or 0)
    minute_1430_ratio = quality.get("minute_1430_ratio")
    if minute_1430_ratio is None:
        minute_1430_ratio = _ratio_pct(minute_1430_count, buy_count)
    daily_close_proxy_ratio = quality.get("daily_close_proxy_ratio")
    if daily_close_proxy_ratio is None:
        daily_close_proxy_ratio = _ratio_pct(daily_close_proxy_count, buy_count)

    if minute_gap_rejected_count > 0:
        status = "missing_snapshots"
        next_action = "先用数据同步的股票分钟 K 线任务按回测 ID 补齐执行日 14:30 的 1m 快照，再重跑严格 14:30 回测。"
    elif buy_count == 0:
        status = "empty"
        next_action = "本次回测没有实际买入，先检查候选日期、策略阈值、股票池和板块范围。"
    elif daily_close_proxy_count > 0 or (daily_close_proxy_ratio is not None and float(daily_close_proxy_ratio) > 0):
        status = "mixed_proxy"
        next_action = "这是尾盘混合回测，收益包含收盘代理；需要严格真实性时请补齐 14:30 快照后运行 strict_1430。"
    elif strict_1430_rejected_count > 0:
        status = "strategy_not_triggered"
        next_action = "数据快照未显示缺口，严格拒单主要来自尾盘条件未触发；应复核策略阈值和候选质量，而不是补数据。"
    elif minute_1430_count > 0:
        status = "ready"
        next_action = "本次买入均可按 14:30 分钟快照解读，仍需结合反未来函数和过拟合检查。"
    else:
        status = "empty"
        next_action = "没有可归类的买入成交，先检查交易表和订单表。"

    diagnostics = [
        {
            "id": "minute_1430",
            "label": "14:30真实成交",
            "status": "pass" if buy_count > 0 and minute_1430_count == buy_count else "warning",
            "value": minute_1430_count,
            "value_type": "count",
            "message": f"{minute_1430_count} / {buy_count} 笔买入使用执行日 14:30 的 1m 快照。",
        },
        {
            "id": "daily_close_proxy",
            "label": "收盘代理",
            "status": "pass" if daily_close_proxy_count == 0 else "warning",
            "value": daily_close_proxy_count,
            "value_type": "count",
            "message": (
                "没有使用日线收盘代理。"
                if daily_close_proxy_count == 0
                else f"{daily_close_proxy_count} 笔买入缺 14:30 快照，使用执行日收盘价代理尾盘。"
            ),
        },
        {
            "id": "strict_1430_rejected",
            "label": "严格14:30拒单",
            "status": "pass" if strict_1430_rejected_count == 0 else "warning",
            "value": strict_1430_rejected_count,
            "value_type": "count",
            "message": (
                "严格 14:30 没有拒单。"
                if strict_1430_rejected_count == 0
                else f"{strict_1430_rejected_count} 笔严格 14:30 订单未成交，其中 {minute_gap_rejected_count} 笔是缺快照。"
            ),
        },
    ]
    return {
        "status": status,
        "backtest_id": backtest_id,
        "execution_model": execution_model,
        "buy_count": buy_count,
        "minute_1430_count": minute_1430_count,
        "minute_1430_ratio": minute_1430_ratio,
        "daily_close_proxy_count": daily_close_proxy_count,
        "daily_close_proxy_ratio": daily_close_proxy_ratio,
        "strict_1430_rejected_count": strict_1430_rejected_count,
        "minute_gap_rejected_count": minute_gap_rejected_count,
        "tail_entry_rejected_count": tail_entry_rejected_count,
        "tail_exit_rejected_count": tail_exit_rejected_count,
        "next_action": next_action,
        "diagnostics": diagnostics,
    }


def backtest_data_quality(backtest_id: int) -> dict[str, Any]:
    """Return a compact data-quality dashboard for one persisted backtest."""

    return data_quality_service.backtest_data_quality(
        backtest_id,
        report_loader=backtest_report,
        coverage_loader=backtest_minute_coverage,
    )


def backtest_signal_events(
    backtest_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
    vt_symbol: str | None = None,
    side: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id, "items": []}
        filters = [schema.backtest_signal_events.c.backtest_id == backtest_id]
        if start is not None:
            filters.append(schema.backtest_signal_events.c.trade_date >= start)
        if end is not None:
            filters.append(schema.backtest_signal_events.c.trade_date <= end)
        symbol = _normalize_symbol(vt_symbol or "")
        if symbol:
            filters.append(schema.backtest_signal_events.c.vt_symbol == symbol)
        normalized_side = str(side or "").strip().upper()
        if normalized_side in {"BUY", "SELL"}:
            filters.append(schema.backtest_signal_events.c.side == normalized_side)
        rows = session.execute(
            select(schema.backtest_signal_events)
            .where(and_(*filters))
            .order_by(desc(schema.backtest_signal_events.c.trade_date), schema.backtest_signal_events.c.vt_symbol, schema.backtest_signal_events.c.id)
            .limit(min(max(limit, 1), 20_000))
        ).mappings().all()
        row_dicts = [dict(row) for row in rows]
        order_rows = session.execute(
            select(schema.backtest_orders)
            .where(
                and_(
                    schema.backtest_orders.c.backtest_id == backtest_id,
                    schema.backtest_orders.c.trade_date >= (start or date.min),
                    schema.backtest_orders.c.trade_date <= (end or date.max),
                )
            )
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.vt_symbol, schema.backtest_orders.c.side, schema.backtest_orders.c.id)
        ).mappings().all()
        order_dicts = [dict(row) for row in order_rows]
        stock_names = _load_stock_names(session, _symbols_from_rows(row_dicts, order_dicts))

    linked_rows = _link_signal_events_to_orders(row_dicts, order_dicts)
    named_rows = _with_stock_names(linked_rows, stock_names)
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "run_type": _run_type_from_params(run.get("params") or {}),
        "items": [_mapping_to_api(row) for row in named_rows],
        "returned_count": len(rows),
        "note": "旧回测未生成全股票信号计划，请重跑组合回测。" if not rows else None,
    }


def backtest_signal_amount_preview(
    backtest_id: int,
    *,
    capital: float,
    max_positions: int,
    start: date | None = None,
    end: date | None = None,
    vt_symbol: str | None = None,
    side: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    events = backtest_signal_events(backtest_id, end=end, vt_symbol=vt_symbol, limit=20_000)
    if events.get("status") not in {"ready", "empty"}:
        return events
    per_trade_budget = float(capital or 0) / max(int(max_positions or 1), 1)
    lots_by_symbol: dict[str, list[dict[str, Any]]] = {}
    preview_rows = []
    normalized_side = str(side or "").strip().upper()
    event_rows = sorted(
        events.get("items") or [],
        key=lambda item: (str(item.get("trade_date") or ""), str(item.get("vt_symbol") or ""), 0 if str(item.get("side") or "").upper() == "BUY" else 1),
    )
    for item in event_rows:
        row = dict(item)
        price = _safe_float(row.get("price"))
        side = str(row.get("side") or "").upper()
        volume = 0
        amount = 0.0
        theoretical_pnl = None
        if side == "BUY" and price and price > 0:
            volume = int(per_trade_budget / price / 100) * 100
            amount = price * volume
            if volume > 0:
                lots_by_symbol.setdefault(str(row["vt_symbol"]), []).append({"volume": volume, "price": price})
        elif side == "SELL" and price and price > 0:
            open_lots = lots_by_symbol.get(str(row["vt_symbol"])) or []
            if open_lots:
                lot = open_lots.pop(0)
                volume = int(lot["volume"])
                amount = price * volume
                theoretical_pnl = (price - float(lot["price"])) * volume
        row["preview_volume"] = volume
        row["preview_amount"] = amount
        row["preview_pnl"] = theoretical_pnl
        row["preview_budget"] = per_trade_budget
        preview_rows.append(row)
    filtered_rows = []
    for row in preview_rows:
        trade_date = _as_date(row.get("trade_date"))
        row_side = str(row.get("side") or "").upper()
        if start is not None and (trade_date is None or trade_date < start):
            continue
        if end is not None and (trade_date is None or trade_date > end):
            continue
        if normalized_side in {"BUY", "SELL"} and row_side != normalized_side:
            continue
        filtered_rows.append(row)
    filtered_rows.sort(key=lambda item: (str(item.get("trade_date") or ""), str(item.get("vt_symbol") or ""), int(item.get("id") or 0)), reverse=True)
    item_limit = min(max(limit, 1), 2000)
    return {
        **events,
        "status": "ready" if filtered_rows else "empty",
        "capital": capital,
        "max_positions": max_positions,
        "per_trade_budget": per_trade_budget,
        "items": filtered_rows[:item_limit],
        "returned_count": len(filtered_rows[:item_limit]),
        "source_count": len(preview_rows),
    }


def backtest_candidate_trace(backtest_id: int, vt_symbol: str, signal_date: date) -> dict[str, Any]:
    """Explain how one daily candidate flowed into a portfolio backtest."""

    rows = queries.candidate_trace_rows(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        normalize_symbol=_normalize_symbol,
        as_date=_as_date,
        load_stock_names=_load_stock_names,
        board_payload=_stock_board_payload,
        backtest_id=backtest_id,
        vt_symbol=vt_symbol,
        signal_date=signal_date,
    )
    if rows.get("status") != "ready":
        return rows

    return _candidate_trace_summary(
        backtest_id=backtest_id,
        vt_symbol=rows["vt_symbol"],
        signal_date=signal_date,
        run=rows["run"],
        recommendation=rows["recommendation"],
        signal_rows=rows["signal_rows"],
        order_rows=rows["order_rows"],
        trade_rows=rows["trade_rows"],
        equity_row=rows["equity_row"],
        position_rows=rows["position_rows"],
        stock_names=rows["stock_names"],
        not_planned_context=rows.get("not_planned_context"),
    )


def backtest_report(backtest_id: int, trade_limit: int = 50) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}
        trades = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(desc(schema.backtest_trades.c.trade_date), desc(schema.backtest_trades.c.id))
            .limit(min(max(trade_limit, 1), 500))
        ).mappings().all()
        all_trades = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        orders = session.execute(
            select(schema.backtest_orders)
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        equity = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
        sample = session.execute(
            select(
                func.count().label("bar_count"),
                func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)).label("symbol_count"),
                func.min(schema.stock_daily_bars.c.trade_date).label("data_start"),
                func.max(schema.stock_daily_bars.c.trade_date).label("data_end"),
            ).where(
                and_(
                    schema.stock_daily_bars.c.trade_date >= run["start_date"],
                    schema.stock_daily_bars.c.trade_date <= run["end_date"],
                )
            )
        ).mappings().one()
        eligible_symbol_count = session.execute(
            select(func.count()).select_from(
                select(schema.stock_daily_bars.c.vt_symbol)
                .where(
                    and_(
                        schema.stock_daily_bars.c.trade_date >= run["start_date"],
                        schema.stock_daily_bars.c.trade_date <= run["end_date"],
                    )
                )
                .group_by(schema.stock_daily_bars.c.vt_symbol)
                .having(func.count() >= 80)
                .subquery()
            )
        ).scalar_one()
        total_stock_count = session.execute(select(func.count()).select_from(schema.stocks)).scalar_one()
        data_quality = _data_quality_snapshot(session)
        sample_bars = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.close_price,
            ).where(
                and_(
                    schema.stock_daily_bars.c.trade_date >= run["start_date"],
                    schema.stock_daily_bars.c.trade_date <= run["end_date"],
                )
            )
            .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
        ).mappings().all()
        trade_dicts = [dict(row) for row in trades]
        all_trade_dicts = [dict(row) for row in all_trades]
        order_dicts = [dict(row) for row in orders]
        stock_names = _load_stock_names(session, _symbols_from_rows(trade_dicts, all_trade_dicts, order_dicts))

    metrics = dict(run.get("metrics") or {})
    sample_payload = dict(sample)
    sample_payload["equity_days"] = len(equity)
    sample_payload["eligible_symbol_count"] = int(eligible_symbol_count or 0)
    sample_payload["universe_stock_count"] = int(total_stock_count or 0)
    sample_payload["coverage_pct"] = _ratio_pct(sample_payload.get("symbol_count"), total_stock_count)
    trade_dicts = _with_stock_names(trade_dicts, stock_names)
    all_trade_dicts = _with_stock_names(all_trade_dicts, stock_names)
    order_dicts = _with_stock_names(order_dicts, stock_names)
    recent_trade_dicts = [_mapping_to_api(row) for row in trade_dicts]
    equity_dicts = [dict(row) for row in equity]
    sample_bar_dicts = [dict(row) for row in sample_bars]
    closed_trades = _closed_trades(all_trade_dicts)
    extended_metrics = _extended_metrics(metrics, closed_trades, all_trade_dicts, order_dicts, equity_dicts)
    sample_benchmark_curve = _sample_equal_weight_curve(sample_bar_dicts)
    index_benchmark_curves = _index_benchmark_curves(run["start_date"], run["end_date"])
    benchmark = _benchmark_report(equity_dicts, sample_benchmark_curve, index_benchmark_curves)
    period_analysis = _period_analysis(equity_dicts, closed_trades, sample_benchmark_curve)
    regime_analysis = _regime_analysis(equity_dicts, closed_trades, sample_benchmark_curve)
    robustness_checks = _robustness_checks(
        metrics,
        equity_dicts,
        closed_trades,
        all_trade_dicts,
        sample_bar_dicts,
        sample_benchmark_curve,
    )
    execution_quality = _execution_quality_report(metrics, extended_metrics, data_quality, sample_payload)
    params = _params_from_run(dict(run))
    data_as_of_audit = _data_as_of_audit(params, execution_quality, data_quality)
    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "run_type": _run_type_from_params(run.get("params") or {}),
        "strategy_id": run["strategy_id"],
        "strategy_version": run["strategy_version"],
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "sample": _mapping_to_api(sample_payload),
        "metrics": metrics,
        "extended_metrics": extended_metrics,
        "summary_rows": _metric_rows(metrics),
        "trades": recent_trade_dicts,
        "recent_trades": recent_trade_dicts,
        "trade_count": len(all_trade_dicts),
        "returned_trade_count": len(trade_dicts),
        "closed_trades": closed_trades[: min(max(trade_limit, 1), 500)],
        "closed_trade_count": len(closed_trades),
        "monthly_returns": _monthly_returns(equity_dicts),
        "symbol_performance": _symbol_performance(closed_trades),
        "worst_trades": sorted(closed_trades, key=lambda item: item["pnl"])[:10],
        "order_stats": _order_stats(order_dicts),
        "equity_tail": [_mapping_to_api(row) for row in equity_dicts[-20:]],
        "benchmark": benchmark,
        "period_analysis": period_analysis,
        "regime_analysis": regime_analysis,
        "robustness_checks": robustness_checks,
        "execution_quality": execution_quality,
        "data_as_of_audit": data_as_of_audit,
        "data_quality": data_quality,
        "method": _backtest_method(params),
        "assumptions": _backtest_assumptions(params),
        "limitations": [
            "当前本地样本不是全 A，只能作为小样本真实日线模拟。",
            "默认混合尾盘回测会优先使用执行日 14:30 分钟快照；缺分钟线时使用执行日收盘价作为尾盘代理，不能称为纯分钟真实回测。",
            "板块周期评分、资金流、热度、龙虎榜数据不完整时会降低主线/游资信号可信度。",
            "财报仅在 publish_date 不晚于交易日时参与评分，缺披露日的数据不会用于真实回测。",
            "上证指数、沪深300、中证500、中证1000基准会临时从外部行情获取，尚未持久化为本地可审计指数表。",
            "样本内/样本外分段为时间切分的初步检查，不等同于完整 walk-forward 验证。",
            "市场环境分段当前按样本等权基准粗分，尚未使用正式指数/行业 regime 模型。",
            "参数网格验证通过 /api/backtests/{id}/validation-grid 单独重跑，报告页默认不自动嵌入以避免误触发长任务。",
        ],
    }


def backtest_execution_model_comparison(backtest_id: int) -> dict[str, Any]:
    """Re-run the same backtest parameters across supported execution models.

    The comparison is intentionally opt-in and non-persistent: it can be slow on
    a large local universe, and it must not create extra backtest rows simply by
    opening a report page.
    """

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}

    base_params = _params_from_run(dict(run))
    variants = [
        ("tail_close_hybrid", "尾盘混合"),
        ("strict_1430", "严格14:30"),
    ]
    rows = []
    for model, label in variants:
        params = replace(
            base_params,
            execution_model=model,
            minute_interval="1m",
            tail_entry_start="14:30",
            tail_entry_end="14:30",
            persist=False,
        )
        result = run_backtest(params)
        rows.append(_execution_model_comparison_row(model, label, result))
    summary = _execution_model_comparison_summary(rows)
    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "base_execution_model": base_params.execution_model,
        "start_date": base_params.start.isoformat(),
        "end_date": base_params.end.isoformat() if base_params.end else None,
        "strategy": base_params.strategy,
        "rows": rows,
        "summary": summary,
        "note": "对比会用同一回测参数非持久化重跑；严格14:30缺快照或尾盘未触发会拒单，不用收盘价代理。",
    }


def backtest_strategy_comparison(params: BacktestParams, strategies: list[str] | None = None) -> dict[str, Any]:
    """Run registered strategies with the same portfolio backtest parameters."""

    return strategy_comparison.compare_strategies(
        params,
        strategies=strategies,
        run_backtest=run_backtest,
    )


def _execution_model_comparison_row(model: str, label: str, result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "ready":
        return {
            "execution_model": model,
            "label": label,
            "status": result.get("status") or "error",
            "message": result.get("message"),
        }
    metrics = dict(result.get("metrics") or {})
    orders = list(result.get("orders") or [])
    trades = list(result.get("trades") or [])
    buy_count = len([trade for trade in trades if trade.get("side") == "BUY"])
    rejected_orders = [order for order in orders if order.get("status") == "rejected"]
    strict_rejected = [order for order in rejected_orders if _order_execution_model(order) == "strict_1430"]
    tail_entry_rejected = [order for order in rejected_orders if str(order.get("reason") or "") == "tail_entry_not_triggered"]
    tail_exit_rejected = [order for order in rejected_orders if str(order.get("reason") or "") == "tail_exit_not_triggered"]
    minute_gap_rejected = [
        order
        for order in strict_rejected
        if str(order.get("reason") or "") == "missing_1430_snapshot"
        or str(_order_execution(order).get("reason") or "") == "missing_1430_snapshot"
        or str(_order_execution(order).get("price_source") or "") == ""
    ]
    minute_1430_count = int(metrics.get("minute_1430_count") or 0)
    daily_close_proxy_count = int(metrics.get("daily_close_proxy_count") or 0)
    return {
        "execution_model": model,
        "label": label,
        "status": "ready",
        "final_equity": metrics.get("final_equity"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "trade_count": metrics.get("trade_count"),
        "buy_count": buy_count,
        "minute_1430_count": minute_1430_count,
        "daily_close_proxy_count": daily_close_proxy_count,
        "minute_1430_ratio": _ratio_pct(minute_1430_count, buy_count),
        "daily_close_proxy_ratio": _ratio_pct(daily_close_proxy_count, buy_count),
        "strict_1430_rejected_count": len(strict_rejected),
        "tail_entry_rejected_count": len(tail_entry_rejected),
        "tail_exit_rejected_count": len(tail_exit_rejected),
        "minute_gap_rejected_count": len(minute_gap_rejected),
    }


def _execution_model_comparison_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hybrid = next((row for row in rows if row.get("execution_model") == "tail_close_hybrid"), None)
    strict = next((row for row in rows if row.get("execution_model") == "strict_1430"), None)
    if not hybrid or not strict or hybrid.get("status") != "ready" or strict.get("status") != "ready":
        return {
            "status": "incomplete",
            "message": "至少一个执行模型未能完成重跑。",
        }
    hybrid_return = _safe_float(hybrid.get("total_return_pct"))
    strict_return = _safe_float(strict.get("total_return_pct"))
    strict_rejected = int(strict.get("strict_1430_rejected_count") or 0)
    minute_gap_rejected = int(strict.get("minute_gap_rejected_count") or 0)
    strict_buy_count = int(strict.get("buy_count") or 0)
    proxy_ratio = _safe_float(hybrid.get("daily_close_proxy_ratio")) or 0
    if strict_buy_count == 0:
        message = "严格14:30没有形成买入成交，当前收益主要依赖收盘代理或分钟覆盖不足。"
        status = "warning"
    elif minute_gap_rejected > 0:
        message = "严格14:30存在拒单，需先补齐对应执行日快照再评价收益。"
        status = "warning"
    elif strict_rejected > 0:
        message = "严格14:30仍有候选因尾盘条件未触发而拒单；这是策略条件约束，不是分钟数据缺口。"
        status = "warning"
    elif proxy_ratio > 50:
        message = "尾盘混合大量使用收盘代理，应优先看严格14:30结果。"
        status = "warning"
    else:
        message = "严格14:30可成交，且收盘代理占比较低。"
        status = "pass"
    return {
        "status": status,
        "return_delta_pct": (
            strict_return - hybrid_return
            if strict_return is not None and hybrid_return is not None
            else None
        ),
        "message": message,
    }


def backtest_report_csv(backtest_id: int, trade_limit: int = 500) -> dict[str, Any]:
    report = backtest_report(backtest_id, trade_limit)
    if report.get("status") != "ready":
        return report
    filename = f"alphaagent_backtest_{backtest_id}_{report['start_date']}_{report['end_date']}.csv"
    return {
        "status": "ready",
        "filename": filename,
        "content": _report_csv_content(report),
    }


def backtest_minute_gap_csv(backtest_id: int) -> dict[str, Any]:
    """Export strict-tail rejected orders as a minute gap CSV."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}
        rows = session.execute(
            select(schema.backtest_orders)
            .where(
                schema.backtest_orders.c.backtest_id == backtest_id,
                schema.backtest_orders.c.status == "rejected",
                schema.backtest_orders.c.reason.in_(["missing_1430_snapshot", "tail_entry_not_triggered", "tail_exit_not_triggered"]),
            )
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.vt_symbol, schema.backtest_orders.c.side, schema.backtest_orders.c.id)
        ).mappings().all()

    params = _params_from_run(dict(run))
    content, gap_count = _minute_gap_csv_content([dict(row) for row in rows])
    return {
        "status": "ready" if gap_count else "empty",
        "backtest_id": backtest_id,
        "gap_count": gap_count,
        "interval": params.minute_interval,
        "filename": f"alphaagent_minute_gap_backtest_{backtest_id}_{run['start_date']}_{run['end_date']}.csv",
        "content": content,
        "note": f"导出严格 14:30 回测中缺少执行日快照的买入/卖出订单，用于补齐 14:30 的 {params.minute_interval} 快照。",
    }


def backtest_validation_grid(backtest_id: int, max_variants: int = 54) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()

    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id}

        base_params = _params_from_run(dict(run))
        end = _as_date(run["end_date"]) or base_params.end or date.today()
        vt_symbols = _load_symbol_universe(session, base_params.max_symbols, base_params.symbols, base_params.included_boards)
        if not vt_symbols:
            return {"status": "empty", "message": "stocks is empty"}
        bars_by_symbol = _load_all_bars(session, vt_symbols, _lookback_start(base_params.start), end)
        trading_days = _trading_days(bars_by_symbol, base_params.start, end)
        if len(trading_days) < 80:
            return {"status": "insufficient_data", "trading_days": len(trading_days)}
        stock_meta = _load_stock_meta(session, vt_symbols)
        score_context = _load_score_context(session, list(bars_by_symbol))
        result = _run_validation_grid(session, backtest_id, base_params, bars_by_symbol, trading_days, stock_meta, max_variants, score_context)

    return result


def backtest_validation_grid_csv(backtest_id: int, max_variants: int = 54) -> dict[str, Any]:
    grid = backtest_validation_grid(backtest_id, max_variants)
    if grid.get("status") != "ready":
        return grid
    filename = f"alphaagent_validation_grid_{backtest_id}_{grid['start_date']}_{grid['end_date']}.csv"
    return {
        "status": "ready",
        "filename": filename,
        "content": _validation_grid_csv_content(grid),
    }


def backtest_trades(backtest_id: int, limit: int = 500, offset: int = 0, order: str = "desc") -> dict[str, Any]:
    return queries.backtest_trades(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        load_stock_names=_load_stock_names,
        symbols_from_rows=_symbols_from_rows,
        with_stock_names=_with_stock_names,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
        limit=limit,
        offset=offset,
        order=order,
    )


def backtest_equity(backtest_id: int) -> dict[str, Any]:
    return queries.backtest_equity(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
    )


def backtest_daily_decisions(backtest_id: int, limit: int = 500, offset: int = 0, order: str = "desc") -> dict[str, Any]:
    return queries.backtest_daily_decisions(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
        limit=limit,
        offset=offset,
        order=order,
    )


def backtest_trade_attribution(backtest_id: int, limit: int = 500, offset: int = 0, sort: str = "pnl_asc") -> dict[str, Any]:
    return queries.backtest_trade_attribution(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        load_stock_names=_load_stock_names,
        symbols_from_rows=_symbols_from_rows,
        with_stock_names=_with_stock_names,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
        limit=limit,
        offset=offset,
        sort=sort,
    )


def backtest_drilldown_options(backtest_id: int) -> dict[str, Any]:
    """Return complete date and symbol choices for backtest drilldown."""

    if not is_database_configured():
        return {"status": "unavailable", "dates": [], "symbols": [], "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "id": backtest_id, "dates": [], "symbols": []}
        equity_rows = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
        trade_rows = session.execute(
            select(
                schema.backtest_trades.c.trade_date,
                schema.backtest_trades.c.vt_symbol,
                schema.backtest_trades.c.side,
            )
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
        ).mappings().all()
        order_rows = session.execute(
            select(
                schema.backtest_orders.c.trade_date,
                schema.backtest_orders.c.vt_symbol,
                schema.backtest_orders.c.side,
                schema.backtest_orders.c.status,
                schema.backtest_orders.c.reason,
            )
            .where(schema.backtest_orders.c.backtest_id == backtest_id)
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.id)
        ).mappings().all()
        signal_rows = session.execute(
            select(
                schema.backtest_signal_events.c.trade_date,
                schema.backtest_signal_events.c.signal_date,
                schema.backtest_signal_events.c.execute_date,
                schema.backtest_signal_events.c.vt_symbol,
                schema.backtest_signal_events.c.side,
                schema.backtest_signal_events.c.raw,
            )
            .where(schema.backtest_signal_events.c.backtest_id == backtest_id)
            .order_by(schema.backtest_signal_events.c.trade_date, schema.backtest_signal_events.c.id)
        ).mappings().all()
        position_rows = session.execute(
            select(
                schema.backtest_daily_positions.c.trade_date,
                schema.backtest_daily_positions.c.vt_symbol,
            )
            .where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_positions.c.trade_date, schema.backtest_daily_positions.c.vt_symbol)
        ).mappings().all()

        equity_dicts = [dict(row) for row in equity_rows]
        trade_dicts = [dict(row) for row in trade_rows]
        order_dicts = [dict(row) for row in order_rows]
        signal_dicts = [dict(row) for row in signal_rows]
        position_dicts = [dict(row) for row in position_rows]
        signal_dates = sorted({row["signal_date"] for row in signal_dicts if row.get("signal_date")})
        if signal_dates:
            recommendation_rows = session.execute(
                select(
                    schema.quant_recommendations.c.trade_date,
                    schema.quant_recommendations.c.action,
                )
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
        stock_names = _load_stock_names(
            session,
            _symbols_from_rows(trade_dicts, order_dicts, signal_dicts, position_dicts),
        )

    dates = _backtest_drilldown_date_options(equity_dicts, trade_dicts, order_dicts, signal_dicts, position_dicts, recommendation_dicts)
    symbols = _backtest_drilldown_symbol_options(trade_dicts, order_dicts, signal_dicts, position_dicts, stock_names)
    return {
        "status": "ready" if dates or symbols else "empty",
        "backtest_id": backtest_id,
        "run_type": _run_type_from_params(run.get("params") or {}),
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "dates": dates,
        "symbols": symbols,
        "date_count": len(dates),
        "symbol_count": len(symbols),
        "note": "日期来自每日权益曲线；股票来自成交、订单、理论信号和持仓快照的合集。",
    }


def backtest_day_detail(backtest_id: int, trade_date: date) -> dict[str, Any]:
    return queries.backtest_day_detail(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        load_stock_names=_load_stock_names,
        symbols_from_rows=_symbols_from_rows,
        with_stock_names=_with_stock_names,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
        trade_date=trade_date,
    )


def backtest_symbol_detail(backtest_id: int, vt_symbol: str) -> dict[str, Any]:
    return queries.backtest_symbol_detail(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        normalize_symbol=_normalize_symbol,
        load_stock_names=_load_stock_names,
        with_stock_names=_with_stock_names,
        board_payload=_stock_board_payload,
        closed_trades=_closed_trades,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
        vt_symbol=vt_symbol,
    )


def backtest_audit(backtest_id: int, vt_symbol: str | None = None, limit: int = 200) -> dict[str, Any]:
    return queries.audit_rows(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        normalize_symbol=_normalize_symbol,
        load_stock_names=_load_stock_names,
        symbols_from_rows=_symbols_from_rows,
        with_stock_names=_with_stock_names,
        to_api=_mapping_to_api,
        params_from_run=_params_from_run,
        params_to_json=_params_to_json,
        backtest_method=_backtest_method,
        audit_events=_audit_events,
        order_stats=_order_stats,
        backtest_id=backtest_id,
        vt_symbol=vt_symbol,
        limit=limit,
    )


def _ensure_backtest_schema() -> None:
    """Allow backtests to run from CLI/service calls, not only API startup."""

    schema.create_schema(get_engine())


def _simulate(
    session,
    params: BacktestParams,
    bars_by_symbol: dict[str, list[Bar]],
    trading_days: list[date],
    stock_meta: dict[str, dict[str, Any]],
    score_cache: dict[date, list[Any]] | None = None,
    minute_index: dict[str, dict[date, list[MinuteBar]]] | None = None,
    score_context: ScoreContext | None = None,
) -> dict[str, Any]:
    return simulation.simulate_portfolio(
        session,
        params,
        bars_by_symbol,
        trading_days,
        stock_meta,
        _simulation_callbacks(),
        score_cache=score_cache,
        minute_index=minute_index,
        score_context=score_context,
    )


def _simulation_callbacks() -> simulation.SimulationCallbacks:
    return simulation.SimulationCallbacks(
        load_minute_bar_index=_load_minute_bar_index,
        score_day=_score_day,
        resolve_buy_fill=_resolve_buy_fill,
        resolve_tail_sell_fill=_resolve_tail_sell_fill,
        is_limit_up_open=_is_limit_up_open,
        is_limit_down_open=_is_limit_down_open,
        metrics=_metrics,
        order=_order,
        trade_to_api=_trade_to_api,
        mapping_to_api=_mapping_to_api,
    )


def _score_day(
    session,
    bars_by_symbol: dict[str, list[Bar]],
    trade_date: date,
    params: BacktestParams,
    score_cache: dict[date, list[Any]] | None = None,
    score_context: ScoreContext | None = None,
):
    return scoring.score_day(
        session,
        bars_by_symbol,
        trade_date,
        params,
        score_cache,
        score_context,
        score_candidates_for_day=_score_candidates_for_day,
    )


def _score_candidates_for_day(
    session,
    bars_by_symbol: dict[str, list[Bar]],
    trade_date: date,
    params: BacktestParams,
    score_context: ScoreContext | None = None,
) -> list[Any]:
    return scoring.score_candidates_for_day(
        session,
        bars_by_symbol,
        trade_date,
        params,
        score_context,
        load_index_return_20d=_load_index_return_20d,
        load_sector_scores=_load_sector_scores,
        load_financial_scores=_load_financial_scores,
        load_fund_flow_scores=_load_fund_flow_scores,
        load_hot_rank_scores=_load_hot_rank_scores,
        load_lhb_scores=_load_lhb_scores,
        financial_scores_from_context=_financial_scores_from_context,
    )


def _is_buy_candidate(score, params: BacktestParams) -> bool:
    return scoring.is_buy_candidate(score, params)


def _signal_events_for_day(
    signal_date: date,
    execute_date: date,
    scores: list[Any],
    theoretical_positions: dict[str, Position],
    today_bars: dict[str, Bar],
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    stock_meta: dict[str, dict[str, Any]],
    params: BacktestParams,
) -> list[dict[str, Any]]:
    return simulation.signal_events_for_day(
        signal_date,
        execute_date,
        scores,
        theoretical_positions,
        today_bars,
        bar_index,
        minute_index,
        stock_meta,
        params,
        _simulation_callbacks(),
    )


def _sell_reason(position: Position, bar: Bar, current_day: date, params: BacktestParams) -> str | None:
    return simulation.sell_reason_for_position(position, bar, current_day, params)


def _load_symbol_universe(
    session,
    max_symbols: int,
    symbols: list[str] | None = None,
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS,
) -> list[str]:
    requested = [_normalize_symbol(symbol) for symbol in symbols or [] if _normalize_symbol(symbol)]
    if requested:
        existing = session.execute(
            select(schema.stocks.c.vt_symbol)
            .where(schema.stocks.c.vt_symbol.in_(requested))
            .order_by(schema.stocks.c.vt_symbol)
        ).all()
        found = {str(row[0]) for row in existing}
        return [symbol for symbol in requested if symbol in found]

    rows = session.execute(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.exchange)
        .where(schema.stocks.c.vt_symbol != "000001.SSE")
        .order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
        .limit(5000)
    ).all()
    allowed = set(normalize_included_boards(included_boards))
    result = [
        str(row[0])
        for row in rows
        if stock_board(row[0], row[1]) in allowed
    ]
    return result[: min(max(max_symbols, 1), 5000)]


def _load_stock_meta(session, vt_symbols: list[str]) -> dict[str, dict[str, Any]]:
    rows = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol.in_(vt_symbols))).mappings().all()
    return {str(row["vt_symbol"]): dict(row) for row in rows}


def _load_stock_names(session, vt_symbols: list[str]) -> dict[str, dict[str, Any]]:
    symbols = sorted({symbol for symbol in vt_symbols if symbol})
    if not symbols:
        return {}
    rows = session.execute(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.name, schema.stocks.c.exchange)
        .where(schema.stocks.c.vt_symbol.in_(symbols))
    ).mappings().all()
    return {str(row["vt_symbol"]): dict(row) for row in rows}


def _symbols_from_rows(*row_groups: list[dict[str, Any]]) -> list[str]:
    symbols: set[str] = set()
    for rows in row_groups:
        for row in rows:
            symbol = str(row.get("vt_symbol") or "").strip().upper()
            if symbol:
                symbols.add(symbol)
    return sorted(symbols)


def _stock_board_payload(vt_symbol: Any, stock: dict[str, Any] | None = None) -> dict[str, str]:
    return stock_board_payload(vt_symbol, (stock or {}).get("exchange"))


def _with_stock_names(rows: list[dict[str, Any]], names: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        vt_symbol = str(item.get("vt_symbol") or "")
        stock = names.get(vt_symbol) or {}
        item["name"] = item.get("name") or stock.get("name")
        item.update(_stock_board_payload(vt_symbol, stock))
        result.append(item)
    return result


def _link_signal_events_to_orders(events: list[dict[str, Any]], orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return signal_plan.link_signal_events_to_orders(events, orders, as_date=_as_date)


def _backtest_drilldown_date_options(
    equity_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    recommendation_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return queries.drilldown_date_options(
        equity_rows,
        trade_rows,
        order_rows,
        signal_rows,
        position_rows,
        recommendation_rows,
        as_date=_as_date,
        to_api=_mapping_to_api,
    )


def _backtest_drilldown_symbol_options(
    trade_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    stock_names: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return queries.drilldown_symbol_options(
        trade_rows,
        order_rows,
        signal_rows,
        position_rows,
        stock_names,
        as_date=_as_date,
        normalize_symbol=_normalize_symbol,
        board_payload=_stock_board_payload,
        to_api=_mapping_to_api,
    )


def _candidate_trace_summary(
    *,
    backtest_id: int,
    vt_symbol: str,
    signal_date: date,
    run: dict[str, Any],
    recommendation: dict[str, Any] | None,
    signal_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    equity_row: dict[str, Any] | None,
    position_rows: list[dict[str, Any]],
    stock_names: dict[str, dict[str, Any]],
    not_planned_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    linked_signals = _link_signal_events_to_orders(signal_rows, order_rows)
    named_signals = _with_stock_names(linked_signals, stock_names)
    named_orders = _with_stock_names(order_rows, stock_names)
    named_trades = _with_stock_names(trade_rows, stock_names)
    named_positions = _with_stock_names(position_rows, stock_names)
    buy_orders = [row for row in named_orders if str(row.get("side") or "").upper() == "BUY"]
    buy_trades = [row for row in named_trades if str(row.get("side") or "").upper() == "BUY"]
    action = str((recommendation or {}).get("action") or "").upper()
    first_signal = named_signals[0] if named_signals else None
    first_order = buy_orders[0] if buy_orders else (named_orders[0] if named_orders else None)
    linked_status = str(first_order.get("status") or "") if first_order else "not_ordered"
    first_plan_status = str(first_signal.get("plan_status") or "") if first_signal else ""
    first_signal_raw = first_signal.get("raw") if isinstance(first_signal, dict) and isinstance(first_signal.get("raw"), dict) else {}
    first_signal_reason = str(first_signal.get("linked_order_reason") or first_signal_raw.get("reason") or "") if first_signal else ""

    if buy_trades:
        status = "filled"
        summary = "候选为 BUY，组合回测已下单并成交。"
    elif first_order and str(first_order.get("status") or "") == "rejected":
        status = "rejected"
        summary = f"候选进入买入计划，但真实组合订单被拒绝：{first_order.get('reason') or 'unknown'}。"
    elif action == "WATCH":
        status = "watch_not_bought"
        summary = "候选是 WATCH，默认组合回测不会买入观察股。"
    elif recommendation and not first_signal:
        status = "candidate_not_planned"
        summary = _candidate_not_planned_summary(not_planned_context)
    elif first_signal:
        if first_plan_status in {"not_triggered", "rejected"}:
            status = first_plan_status
            summary = _candidate_trace_plan_summary(first_signal_reason)
        else:
            status = "planned_not_ordered"
            summary = "理论信号存在，但没有找到对应真实组合订单，通常是组合资金、仓位或回测链路未记录完整。"
    else:
        status = "not_selected"
        summary = "该股票在这个信号日没有进入当前回测策略的候选或信号计划。"

    planned_execute_date = first_signal.get("execute_date") if first_signal else first_order.get("trade_date") if first_order else None
    result = {
        "status": status,
        "summary": summary,
        "backtest_id": backtest_id,
        "signal_date": signal_date.isoformat(),
        "planned_execute_date": planned_execute_date.isoformat() if hasattr(planned_execute_date, "isoformat") else planned_execute_date,
        "vt_symbol": vt_symbol,
        **_stock_board_payload(vt_symbol, stock_names.get(vt_symbol)),
        "name": (stock_names.get(vt_symbol) or {}).get("name"),
        "strategy_id": run.get("strategy_id"),
        "strategy_version": run.get("strategy_version"),
        "run_type": _run_type_from_params(run.get("params") or {}),
        "action": action or None,
        "rank": (recommendation or {}).get("rank"),
        "total_score": (recommendation or {}).get("total_score"),
        "recommendation": _mapping_to_api(_with_stock_names([recommendation], stock_names)[0]) if recommendation else None,
        "signals": [_mapping_to_api(row) for row in named_signals],
        "orders": [_mapping_to_api(row) for row in named_orders],
        "trades": [_mapping_to_api(row) for row in named_trades],
        "positions": [_mapping_to_api(row) for row in named_positions],
        "equity": _mapping_to_api(equity_row) if equity_row else None,
        "linked_order_status": linked_status,
        "linked_order_reason": first_order.get("reason") if first_order else None,
        "diagnostics": _candidate_trace_diagnostics(recommendation, named_signals, named_orders, named_trades),
        "not_planned_context": _mapping_to_api(not_planned_context) if status == "candidate_not_planned" and not_planned_context else None,
    }
    if first_signal:
        result["plan_status"] = first_signal.get("plan_status")
        result["plan_status_label"] = first_signal.get("plan_status_label")
    return result


def _candidate_not_planned_summary(context: dict[str, Any] | None) -> str:
    if not context:
        return "候选存在，但没有进入该回测的理论买入计划，通常是排名、持仓上限、策略参数或回测区间不一致。"
    reason = str(context.get("likely_reason") or "")
    label = str(context.get("likely_reason_label") or "").strip()
    if reason == "before_first_signal_date":
        return f"候选存在，但信号日处于该回测的预热/明细空窗期：{label}。回测需要先加载足够历史K线计算 MA60、60日回撤等指标。"
    if reason == "after_last_signal_date":
        return f"候选存在，但信号日不在该回测已记录的信号明细范围内：{label}。"
    if reason == "outside_backtest_universe":
        return f"候选存在，但不在该回测股票池内：{label}。"
    if reason == "signal_date_has_no_plan":
        return f"候选存在，但该信号日没有生成回测理论计划：{label}。"
    if reason == "not_in_same_day_plan":
        return f"候选存在，但该股票没有进入该信号日理论计划：{label}。"
    if reason == "not_in_persisted_candidates":
        return "该股票没有进入这一天的落库候选。"
    return f"候选存在，但没有进入该回测的理论买入计划。{label or '需要核查回测参数、股票池和候选生成链路。'}"


def _candidate_trace_plan_summary(reason: str) -> str:
    return signal_plan.candidate_trace_plan_summary(reason)


def _candidate_trace_diagnostics(
    recommendation: dict[str, Any] | None,
    signal_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return signal_plan.candidate_trace_diagnostics(recommendation, signal_rows, order_rows, trade_rows)


def _signal_plan_status(raw: dict[str, Any], order: dict[str, Any] | None) -> str:
    return signal_plan.signal_plan_status(raw, order)


def _signal_plan_status_label(status: str) -> str:
    return signal_plan.signal_plan_status_label(status)


def _load_score_context(session, vt_symbols: list[str]) -> ScoreContext:
    return ScoreContext(financial_rows_by_symbol=_load_financial_rows_by_symbol(session, vt_symbols))


def _load_financial_rows_by_symbol(session, vt_symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not vt_symbols:
        return {}
    rows = session.execute(
        select(schema.stock_financial_reports)
        .where(schema.stock_financial_reports.c.vt_symbol.in_(vt_symbols))
        .order_by(schema.stock_financial_reports.c.vt_symbol, desc(schema.stock_financial_reports.c.report_date))
    ).mappings().all()
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row["vt_symbol"])].append(dict(row))
    return dict(result)


def _financial_scores_from_context(score_context: ScoreContext | None, trade_date: date) -> dict[str, float]:
    if score_context is None:
        return {}
    return financial_scores_from_rows_by_symbol(score_context.financial_rows_by_symbol, trade_date)


def _load_all_bars(session, vt_symbols: list[str], start: date, end: date) -> dict[str, list[Bar]]:
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(
            and_(
                schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_daily_bars.c.trade_date >= start,
                schema.stock_daily_bars.c.trade_date <= end,
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
    return dict(result)


def _lookback_start(start: date) -> date:
    """Load enough pre-start bars for MA60 and 60-day drawdown factors."""

    return start - timedelta(days=BACKTEST_LOOKBACK_DAYS * 2)


def _load_minute_bar_index(
    session,
    vt_symbols: list[str],
    start: date,
    end: date,
    interval: str = "1m",
) -> dict[str, dict[date, list[MinuteBar]]]:
    if not vt_symbols or not hasattr(schema, "stock_minute_bars"):
        return {}
    rows = session.execute(
        select(schema.stock_minute_bars)
        .where(
            and_(
                schema.stock_minute_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_minute_bars.c.trade_date >= start,
                schema.stock_minute_bars.c.trade_date <= end,
                schema.stock_minute_bars.c.interval == interval,
            )
        )
        .order_by(schema.stock_minute_bars.c.vt_symbol, schema.stock_minute_bars.c.bar_time)
    ).mappings().all()
    result: dict[str, dict[date, list[MinuteBar]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        bar = MinuteBar(
            bar_time=row["bar_time"],
            trade_date=row["trade_date"],
            open_price=float(row["open_price"]),
            high_price=float(row["high_price"]),
            low_price=float(row["low_price"]),
            close_price=float(row["close_price"]),
            volume=row.get("volume"),
            turnover=row.get("turnover"),
        )
        result[str(row["vt_symbol"])][bar.trade_date].append(bar)
    return {symbol: dict(by_date) for symbol, by_date in result.items()}


def _trading_days(bars_by_symbol: dict[str, list[Bar]], start: date, end: date) -> list[date]:
    days = {bar.trade_date for bars in bars_by_symbol.values() for bar in bars if start <= bar.trade_date <= end}
    return sorted(days)


def _bar_index(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, dict[date, Bar]]:
    return simulation.bar_index_by_symbol(bars_by_symbol)


def _market_value(positions: dict[str, Position], today_bars: dict[str, Bar]) -> float:
    return simulation.market_value(positions, today_bars)


def _position_snapshot_rows(
    trade_date: date,
    positions: dict[str, Position],
    today_bars: dict[str, Bar],
    total_equity: float,
) -> list[dict[str, Any]]:
    return simulation.position_snapshot_rows(trade_date, positions, today_bars, total_equity)


def _resolve_buy_fill(
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    params: BacktestParams,
) -> dict[str, Any]:
    return execution_models.resolve_buy_fill(order, current_day, daily_bar, bar_index, minute_index, params)


def _resolve_tail_sell_fill(
    vt_symbol: str,
    position: Position,
    current_day: date,
    daily_bar: Bar,
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    params: BacktestParams,
    reason: str,
    signal_date: date | None = None,
) -> dict[str, Any]:
    return execution_models.resolve_tail_sell_fill(
        vt_symbol,
        position,
        current_day,
        daily_bar,
        minute_index,
        params,
        reason,
        signal_date=signal_date,
    )


def _pending_sell_raw(order: dict[str, Any], position: Position, current_day: date, mode: str) -> dict[str, Any]:
    return simulation.pending_sell_raw(order, position, current_day, mode)


def _metrics(initial_cash: float, equity_curve: list[dict[str, Any]], trades: list[Trade]) -> dict[str, Any]:
    if not equity_curve:
        return {}
    final_equity = float(equity_curve[-1]["total_equity"])
    total_return = (final_equity / initial_cash - 1) * 100 if initial_cash else 0
    peak = float(equity_curve[0]["total_equity"])
    max_dd = 0.0
    daily_returns = []
    prev = peak
    for item in equity_curve:
        equity = float(item["total_equity"])
        peak = max(peak, equity)
        dd = (equity / peak - 1) * 100 if peak else 0
        item["drawdown_pct"] = dd
        max_dd = min(max_dd, dd)
        if prev:
            daily_returns.append(equity / prev - 1)
        prev = equity
    sell_trades = [trade for trade in trades if trade.side == "SELL"]
    buy_trades = [trade for trade in trades if trade.side == "BUY"]
    wins = [trade.pnl or 0 for trade in sell_trades if (trade.pnl or 0) > 0]
    losses = [trade.pnl or 0 for trade in sell_trades if (trade.pnl or 0) <= 0]
    annual_return = _annualized_return(total_return, len(equity_curve))
    sharpe = _sharpe(daily_returns)
    execution_modes = _execution_mode_counts(buy_trades)
    return {
        "initial_cash": initial_cash,
        "final_equity": final_equity,
        "total_return_pct": total_return,
        "annual_return_pct": annual_return,
        "max_drawdown_pct": max_dd,
        "total_trade_rows": len(trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "trade_count": len(sell_trades),
        "open_trade_count": max(len(buy_trades) - len(sell_trades), 0),
        "win_rate": len(wins) / len(sell_trades) if sell_trades else 0,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) else None,
        "average_win": mean(wins) if wins else 0,
        "average_loss": mean(losses) if losses else 0,
        "sharpe": sharpe,
        "minute_1430_count": execution_modes.get("minute_1430", 0),
        "daily_close_proxy_count": execution_modes.get("daily_close_proxy", 0),
    }


def _metric_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {
        "initial_cash": "初始资金",
        "final_equity": "期末权益",
        "total_return_pct": "总收益率",
        "annual_return_pct": "年化收益率",
        "max_drawdown_pct": "最大回撤",
        "total_trade_rows": "成交记录数",
        "buy_count": "买入笔数",
        "sell_count": "卖出笔数",
        "trade_count": "平仓交易数",
        "open_trade_count": "持仓中笔数",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
        "average_win": "平均盈利",
        "average_loss": "平均亏损",
        "sharpe": "Sharpe",
        "minute_1430_count": "14:30真实成交数",
        "daily_close_proxy_count": "日线收盘代理成交数",
    }
    return [
        {"key": key, "label": label, "value": metrics.get(key)}
        for key, label in labels.items()
        if key in metrics
    ]


def _execution_mode_counts(buy_trades: list[Trade]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in buy_trades:
        raw = trade.raw or {}
        execution = raw.get("execution") if isinstance(raw, dict) else None
        mode = execution.get("mode") if isinstance(execution, dict) else None
        if not mode:
            mode = "unknown"
        counts[str(mode)] = counts.get(str(mode), 0) + 1
    return counts


def _extended_metrics(
    metrics: dict[str, Any],
    closed_trades: list[dict[str, Any]],
    all_trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    equity: list[dict[str, Any]],
) -> dict[str, Any]:
    return reports.extended_metrics(
        metrics,
        closed_trades,
        all_trades,
        orders,
        equity,
        order_execution_model=_order_execution_model,
        order_execution=_order_execution,
        trade_execution_mode_counts=_trade_execution_mode_counts,
        median=_median,
    )


def _execution_quality_report(
    metrics: dict[str, Any],
    extended_metrics: dict[str, Any],
    data_quality: dict[str, Any],
    sample: dict[str, Any],
) -> dict[str, Any]:
    return reports.execution_quality_report(
        metrics,
        extended_metrics,
        data_quality,
        sample,
        ratio_pct=_ratio_pct,
    )


def _data_as_of_audit(
    params: BacktestParams,
    execution_quality: dict[str, Any],
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    daily_close_proxy_ratio = execution_quality.get("daily_close_proxy_ratio")
    minute_gap_rejected_count = int(execution_quality.get("minute_gap_rejected_count") or 0)
    financial_count = int((data_quality.get("stock_financial_reports") or {}).get("count") or 0)
    diagnostics = [
        {
            "id": "candidate_daily_visibility",
            "label": "候选数据可见性",
            "status": "pass",
            "value": None,
            "value_type": "text",
            "message": "候选逐交易日重新评分，只使用信号日及以前的日线、资金流、热度、龙虎榜和板块数据。",
        },
        {
            "id": "financial_publish_date",
            "label": "财报披露日约束",
            "status": "pass" if financial_count > 0 else "warning",
            "value": financial_count,
            "value_type": "count",
            "message": (
                "财报评分只读取 publish_date <= trade_date 的本地财报。"
                if financial_count > 0
                else "本地财报为空或覆盖不足，详情页现在可查的财报不会自动进入历史当日评分。"
            ),
        },
        {
            "id": "execution_after_signal",
            "label": "信号后执行",
            "status": "pass",
            "value": None,
            "value_type": "text",
            "message": _execution_timing(params),
        },
        {
            "id": "tail_proxy_risk",
            "label": "尾盘代理风险",
            "status": "warning" if daily_close_proxy_ratio is not None and float(daily_close_proxy_ratio) > 50 else "pass",
            "value": daily_close_proxy_ratio,
            "value_type": "pct",
            "message": (
                "收盘代理占比较高，当前结果不能按纯 14:30 分钟真实回测解读。"
                if daily_close_proxy_ratio is not None and float(daily_close_proxy_ratio) > 50
                else "收盘代理占比未超过一半，但仍应查看成交真实性检查。"
            ),
        },
        {
            "id": "strict_minute_gap",
            "label": "严格分钟缺口",
            "status": "warning" if minute_gap_rejected_count > 0 else "pass",
            "value": minute_gap_rejected_count,
            "value_type": "count",
            "message": (
                "存在缺 14:30 快照导致的严格拒单，应先补齐分钟线再判断策略真实收益。"
                if minute_gap_rejected_count > 0
                else "本报告未发现严格 14:30 缺口拒单。"
            ),
        },
        {
            "id": "overfit_scope",
            "label": "过拟合验证范围",
            "status": "warning",
            "value": None,
            "value_type": "text",
            "message": "当前报告内置分段、随机样本和成本压力检查；多年全 A walk-forward 与参数网格需要单独运行后才可证明稳健性。",
        },
    ]
    return {
        "status": "warning" if any(item["status"] != "pass" for item in diagnostics) else "pass",
        "policy": "反未来函数审计只证明当前实现的数据可见性约束，不证明策略有效或不过拟合。",
        "diagnostics": diagnostics,
    }


def _trade_execution_mode_counts(buy_trades: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in buy_trades:
        raw = trade.get("raw") or {}
        execution = raw.get("execution") if isinstance(raw, dict) else None
        mode = execution.get("mode") if isinstance(execution, dict) else None
        if not mode:
            mode = "unknown"
        counts[str(mode)] = counts.get(str(mode), 0) + 1
    return counts


def _order_execution(order: dict[str, Any]) -> dict[str, Any]:
    raw = order.get("raw") if isinstance(order.get("raw"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else raw
    return execution if isinstance(execution, dict) else {}


def _order_execution_model(order: dict[str, Any]) -> str:
    return str(_order_execution(order).get("execution_model") or "")


def _closed_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    result: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda item: (item["trade_date"], item.get("id") or 0)):
        side = str(trade.get("side") or "")
        vt_symbol = str(trade.get("vt_symbol") or "")
        if side == "BUY":
            open_by_symbol[vt_symbol].append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_by_symbol[vt_symbol].pop(0) if open_by_symbol[vt_symbol] else None
        entry_date = _as_date((entry or {}).get("trade_date") or (trade.get("raw") or {}).get("entry_date"))
        exit_date = _as_date(trade.get("trade_date"))
        pnl = float(trade.get("pnl") or 0)
        amount = float((entry or {}).get("amount") or trade.get("amount") or 0)
        result.append(
            {
                "vt_symbol": vt_symbol,
                "name": (entry or {}).get("name") or trade.get("name"),
                **(
                    {
                        "board": (entry or {}).get("board") or trade.get("board") or _stock_board_payload(vt_symbol)["board"],
                        "board_label": (entry or {}).get("board_label")
                        or trade.get("board_label")
                        or _stock_board_payload(vt_symbol)["board_label"],
                    }
                ),
                "entry_date": entry_date.isoformat() if entry_date else None,
                "exit_date": exit_date.isoformat() if exit_date else None,
                "entry_price": float(entry.get("price")) if entry and entry.get("price") is not None else None,
                "exit_price": float(trade.get("price") or 0),
                "volume": int(trade.get("volume") or 0),
                "amount": amount,
                "fee": float(trade.get("fee") or 0) + float((entry or {}).get("fee") or 0),
                "pnl": pnl,
                "return_pct": pnl / amount * 100 if amount else None,
                "holding_days": (exit_date - entry_date).days if entry_date and exit_date else None,
                "exit_reason": trade.get("reason"),
            }
        )
    return result


def _monthly_returns(equity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not equity:
        return []
    rows = sorted(equity, key=lambda item: item["trade_date"])
    result = []
    month_start_equity = float(rows[0]["total_equity"])
    month_start_date = _as_date(rows[0]["trade_date"])
    prev_month = month_start_date.strftime("%Y-%m") if month_start_date else ""
    month_peak = month_start_equity
    month_max_dd = 0.0
    prev_row = rows[0]

    for row in rows:
        current_date = _as_date(row["trade_date"])
        if current_date is None:
            continue
        current_month = current_date.strftime("%Y-%m")
        current_equity = float(row["total_equity"])
        if current_month != prev_month:
            prev_equity = float(prev_row["total_equity"])
            result.append(
                {
                    "month": prev_month,
                    "start_date": month_start_date.isoformat() if month_start_date else None,
                    "end_date": _as_date(prev_row["trade_date"]).isoformat(),
                    "start_equity": month_start_equity,
                    "end_equity": prev_equity,
                    "return_pct": (prev_equity / month_start_equity - 1) * 100 if month_start_equity else 0,
                    "max_drawdown_pct": month_max_dd,
                }
            )
            prev_month = current_month
            month_start_date = current_date
            month_start_equity = float(prev_row["total_equity"])
            month_peak = month_start_equity
            month_max_dd = min(0.0, (current_equity / month_peak - 1) * 100 if month_peak else 0)
        month_peak = max(month_peak, current_equity)
        month_max_dd = min(month_max_dd, (current_equity / month_peak - 1) * 100 if month_peak else 0)
        prev_row = row

    end_equity = float(prev_row["total_equity"])
    result.append(
        {
            "month": prev_month,
            "start_date": month_start_date.isoformat() if month_start_date else None,
            "end_date": _as_date(prev_row["trade_date"]).isoformat(),
            "start_equity": month_start_equity,
            "end_equity": end_equity,
            "return_pct": (end_equity / month_start_equity - 1) * 100 if month_start_equity else 0,
            "max_drawdown_pct": month_max_dd,
        }
    )
    return result


def _symbol_performance(closed_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in closed_trades:
        vt_symbol = str(trade["vt_symbol"])
        item = grouped.setdefault(
            vt_symbol,
            {
                "vt_symbol": vt_symbol,
                "name": trade.get("name"),
                "board": trade.get("board") or _stock_board_payload(vt_symbol)["board"],
                "board_label": trade.get("board_label") or _stock_board_payload(vt_symbol)["board_label"],
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "pnl": 0.0,
                "amount": 0.0,
                "best_trade": None,
                "worst_trade": None,
            },
        )
        if not item.get("name") and trade.get("name"):
            item["name"] = trade.get("name")
        if not item.get("board") and trade.get("board"):
            item["board"] = trade.get("board")
            item["board_label"] = trade.get("board_label")
        pnl = float(trade.get("pnl") or 0)
        item["trade_count"] += 1
        item["win_count"] += 1 if pnl > 0 else 0
        item["loss_count"] += 1 if pnl <= 0 else 0
        item["pnl"] += pnl
        item["amount"] += float(trade.get("amount") or 0)
        item["best_trade"] = pnl if item["best_trade"] is None else max(item["best_trade"], pnl)
        item["worst_trade"] = pnl if item["worst_trade"] is None else min(item["worst_trade"], pnl)

    result = []
    for item in grouped.values():
        amount = float(item["amount"] or 0)
        item["win_rate"] = item["win_count"] / item["trade_count"] if item["trade_count"] else 0
        item["return_pct"] = item["pnl"] / amount * 100 if amount else None
        result.append(item)
    result.sort(key=lambda item: (item["pnl"], item["vt_symbol"]), reverse=True)
    return result


def _order_stats(orders: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    by_reason: dict[str, int] = defaultdict(int)
    rejected_examples = []
    for order in orders:
        status = str(order.get("status") or "unknown")
        reason = str(order.get("reason") or "unknown")
        by_status[status] += 1
        by_reason[reason] += 1
        if status == "rejected" and len(rejected_examples) < 10:
            rejected_examples.append(_mapping_to_api(order))
    return {
        "total": len(orders),
        "by_status": dict(sorted(by_status.items())),
        "by_reason": dict(sorted(by_reason.items())),
        "rejected_examples": rejected_examples,
    }


def _benchmark_report(
    equity: list[dict[str, Any]],
    sample_equal_weight: list[dict[str, Any]],
    index_curves: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    benchmarks = []
    if sample_equal_weight:
        item = _benchmark_metrics("sample_equal_weight", "样本等权基准", sample_equal_weight, equity)
        item["curve_tail"] = [_mapping_to_api(row) for row in sample_equal_weight[-20:]]
        benchmarks.append(item)
    for curve_payload in index_curves or []:
        curve = curve_payload.get("curve") or []
        if curve:
            item = _benchmark_metrics(curve_payload["id"], curve_payload["name"], curve, equity)
            item["source"] = curve_payload.get("source")
            benchmarks.append(item)
            continue
        benchmarks.append(
            {
                "id": curve_payload["id"],
                "name": curve_payload["name"],
                "status": "missing",
                "reason": curve_payload.get("reason") or "指数日线暂不可用。",
            }
        )
    return {"status": "ready", "benchmarks": benchmarks}


def _index_benchmark_curves(start_date: date, end_date: date) -> list[dict[str, Any]]:
    result = []
    adapter = AkShareAdapter()
    benchmark_defs = [
        item for item in INDEX_SYMBOLS
        if item["symbol"] in {"000001", "000300", "000905", "000852"}
    ]
    limit = min(max((end_date - start_date).days + 20, 80), 3000)
    for item in benchmark_defs:
        symbol = item["symbol"]
        exchange = item["exchange"]
        payload = {
            "id": f"index_{symbol}_{exchange.lower()}",
            "name": item["name"],
            "source": None,
            "curve": [],
        }
        try:
            bars = adapter.stock_bars(symbol, exchange, limit=limit, interval="1d")
            payload["source"] = bars.get("source")
            payload["curve"] = _bars_nav_curve(bars.get("items") or [], start_date, end_date)
            if not payload["curve"]:
                payload["reason"] = "外部指数数据可访问，但回测区间内没有可用 K 线。"
        except Exception as exc:
            payload["reason"] = f"外部指数基准获取失败：{exc.__class__.__name__}"
        result.append(payload)
    return result


def _bars_nav_curve(bars: list[dict[str, Any]], start_date: date, end_date: date) -> list[dict[str, Any]]:
    rows = []
    for row in bars:
        trade_date = _as_date(row.get("trade_date"))
        close_price = row.get("close") if "close" in row else row.get("close_price")
        if trade_date is None or close_price is None:
            continue
        if start_date <= trade_date <= end_date:
            rows.append({"trade_date": trade_date, "close_price": float(close_price)})
    rows.sort(key=lambda item: item["trade_date"])
    if len(rows) < 2:
        return []

    nav = 1.0
    curve = [{"trade_date": rows[0]["trade_date"], "nav": nav, "daily_return": 0.0, "member_count": 1}]
    prev_close = rows[0]["close_price"]
    for row in rows[1:]:
        close_price = row["close_price"]
        daily_return = close_price / prev_close - 1 if prev_close else 0.0
        nav *= 1 + daily_return
        curve.append({"trade_date": row["trade_date"], "nav": nav, "daily_return": daily_return, "member_count": 1})
        prev_close = close_price
    return curve


def _sample_equal_weight_curve(sample_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_dates = []
    for row in sample_bars:
        vt_symbol = str(row.get("vt_symbol") or "")
        if not vt_symbol:
            continue
        bars_by_symbol[vt_symbol].append(row)
        trade_date = _as_date(row.get("trade_date"))
        if trade_date:
            all_dates.append(trade_date)
    if not all_dates:
        return []

    daily_returns: dict[date, list[float]] = defaultdict(list)
    for bars in bars_by_symbol.values():
        ordered = sorted(bars, key=lambda item: item["trade_date"])
        prev_close = None
        for row in ordered:
            close_price = float(row.get("close_price") or 0)
            if prev_close and close_price:
                daily_returns[_as_date(row["trade_date"])].append(close_price / prev_close - 1)
            prev_close = close_price or prev_close

    nav = 1.0
    curve = [{"trade_date": min(all_dates), "nav": nav, "daily_return": 0.0, "member_count": 0}]
    for trade_date in sorted(daily_returns):
        returns = daily_returns[trade_date]
        if not returns:
            continue
        nav *= 1 + mean(returns)
        curve.append({"trade_date": trade_date, "nav": nav, "daily_return": mean(returns), "member_count": len(returns)})
    return curve


def _benchmark_metrics(
    benchmark_id: str,
    name: str,
    curve: list[dict[str, Any]],
    strategy_equity: list[dict[str, Any]],
) -> dict[str, Any]:
    if not curve:
        return {"id": benchmark_id, "name": name, "status": "empty"}
    final_nav = float(curve[-1]["nav"])
    return_pct = (final_nav - 1) * 100
    max_dd = _nav_max_drawdown(curve)
    strategy_return = _equity_return_pct(strategy_equity)
    return {
        "id": benchmark_id,
        "name": name,
        "status": "ready",
        "start_date": _as_date(curve[0]["trade_date"]).isoformat(),
        "end_date": _as_date(curve[-1]["trade_date"]).isoformat(),
        "days": len(curve),
        "return_pct": return_pct,
        "max_drawdown_pct": max_dd,
        "strategy_return_pct": strategy_return,
        "excess_return_pct": strategy_return - return_pct if strategy_return is not None else None,
        "final_nav": final_nav,
    }


def _period_analysis(
    equity: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(equity) < 2:
        return {"status": "insufficient_data", "periods": []}
    rows = sorted(equity, key=lambda item: item["trade_date"])
    split_index = max(1, int(len(rows) * 0.6) - 1)
    in_sample = rows[: split_index + 1]
    out_sample = rows[split_index:]
    periods = [
        _period_summary("in_sample", "样本内 60%", in_sample, closed_trades, benchmark_curve),
        _period_summary("out_of_sample", "样本外 40%", out_sample, closed_trades, benchmark_curve, exclude_start_trade_date=True),
    ]
    return {
        "status": "ready",
        "method": "time_split_60_40",
        "note": "按权益交易日时间切分的初步样本外检查，不是参数训练后的 walk-forward。",
        "periods": periods,
    }


def _period_summary(
    period_id: str,
    label: str,
    rows: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
    *,
    exclude_start_trade_date: bool = False,
) -> dict[str, Any]:
    start_date = _as_date(rows[0]["trade_date"])
    end_date = _as_date(rows[-1]["trade_date"])
    start_equity = float(rows[0]["total_equity"])
    end_equity = float(rows[-1]["total_equity"])
    period_trades = [
        trade for trade in closed_trades
        if trade.get("exit_date")
        and (start_date < _as_date(trade["exit_date"]) if exclude_start_trade_date else start_date <= _as_date(trade["exit_date"]))
        and _as_date(trade["exit_date"]) <= end_date
    ]
    pnl_values = [float(trade.get("pnl") or 0) for trade in period_trades]
    wins = [value for value in pnl_values if value > 0]
    benchmark_return = _period_benchmark_return(benchmark_curve, start_date, end_date)
    strategy_return = (end_equity / start_equity - 1) * 100 if start_equity else 0
    return {
        "id": period_id,
        "label": label,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": len(rows),
        "start_equity": start_equity,
        "end_equity": end_equity,
        "return_pct": strategy_return,
        "max_drawdown_pct": _equity_max_drawdown(rows),
        "trade_count": len(period_trades),
        "win_rate": len(wins) / len(period_trades) if period_trades else 0,
        "pnl": sum(pnl_values),
        "benchmark_return_pct": benchmark_return,
        "excess_return_pct": strategy_return - benchmark_return if benchmark_return is not None else None,
    }


def _period_benchmark_return(curve: list[dict[str, Any]], start_date: date, end_date: date) -> float | None:
    if not curve:
        return None
    start_nav = None
    end_nav = None
    for row in sorted(curve, key=lambda item: item["trade_date"]):
        trade_date = _as_date(row["trade_date"])
        nav = float(row.get("nav") or 0)
        if start_nav is None and trade_date >= start_date:
            start_nav = nav
        if start_date <= trade_date <= end_date:
            end_nav = nav
        if trade_date > end_date:
            break
    if start_nav is None or end_nav is None:
        return None
    return (end_nav / start_nav - 1) * 100 if start_nav else None


def _regime_analysis(
    equity: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(equity) < 40 or len(benchmark_curve) < 40:
        return {"status": "insufficient_data", "benchmark_id": "sample_equal_weight", "periods": []}

    benchmark_by_date = {_as_date(row["trade_date"]): row for row in benchmark_curve}
    equity_by_date = {_as_date(row["trade_date"]): row for row in equity}
    ordered_dates = sorted(date_ for date_ in benchmark_by_date if date_ in equity_by_date)
    if len(ordered_dates) < 40:
        return {"status": "insufficient_data", "benchmark_id": "sample_equal_weight", "periods": []}

    windows = []
    window_size = 20
    for start_index in range(0, len(ordered_dates) - window_size + 1, window_size):
        dates = ordered_dates[start_index:start_index + window_size]
        start_date = dates[0]
        end_date = dates[-1]
        benchmark_return = _period_benchmark_return(benchmark_curve, start_date, end_date)
        if benchmark_return is None:
            continue
        regime = _classify_regime(benchmark_return)
        strategy_rows = [equity_by_date[trade_date] for trade_date in dates]
        strategy_return = _equity_return_pct(strategy_rows) or 0.0
        period_trades = [
            trade for trade in closed_trades
            if trade.get("exit_date") and start_date <= _as_date(trade["exit_date"]) <= end_date
        ]
        pnl_values = [float(trade.get("pnl") or 0) for trade in period_trades]
        wins = [value for value in pnl_values if value > 0]
        windows.append(
            {
                "regime": regime,
                "start_date": start_date,
                "end_date": end_date,
                "days": len(strategy_rows),
                "strategy_return_pct": strategy_return,
                "benchmark_return_pct": benchmark_return,
                "max_drawdown_pct": _equity_max_drawdown(strategy_rows),
                "trade_count": len(period_trades),
                "win_count": len(wins),
                "pnl": sum(pnl_values),
            }
        )

    grouped: dict[str, dict[str, Any]] = {}
    for window in windows:
        item = grouped.setdefault(
            window["regime"],
            {
                "regime": window["regime"],
                "window_count": 0,
                "days": 0,
                "strategy_return_pct": 0.0,
                "benchmark_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "trade_count": 0,
                "win_count": 0,
                "pnl": 0.0,
                "windows": [],
            },
        )
        item["window_count"] += 1
        item["days"] += window["days"]
        item["strategy_return_pct"] += window["strategy_return_pct"]
        item["benchmark_return_pct"] += window["benchmark_return_pct"]
        item["max_drawdown_pct"] = min(item["max_drawdown_pct"], window["max_drawdown_pct"])
        item["trade_count"] += window["trade_count"]
        item["win_count"] += window["win_count"]
        item["pnl"] += window["pnl"]
        item["windows"].append(_mapping_to_api(window))

    periods = []
    for regime in ("strong", "weak", "choppy"):
        item = grouped.get(regime)
        if not item:
            continue
        window_count = item["window_count"]
        item["avg_strategy_return_pct"] = item.pop("strategy_return_pct") / window_count
        item["avg_benchmark_return_pct"] = item.pop("benchmark_return_pct") / window_count
        item["win_rate"] = item["win_count"] / item["trade_count"] if item["trade_count"] else 0
        item["label"] = {"strong": "样本强势", "weak": "样本弱势", "choppy": "样本震荡"}[regime]
        periods.append(item)

    return {
        "status": "ready" if periods else "empty",
        "benchmark_id": "sample_equal_weight",
        "method": "20 trading-day windows classified by sample equal-weight return",
        "note": "指数日线缺失时使用样本等权基准划分强弱环境；这不是正式沪深指数市场分段。",
        "periods": periods,
    }


def _classify_regime(benchmark_return_pct: float) -> str:
    if benchmark_return_pct >= 5:
        return "strong"
    if benchmark_return_pct <= -3:
        return "weak"
    return "choppy"


def _robustness_checks(
    metrics: dict[str, Any],
    equity: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    sample_bars: list[dict[str, Any]],
    sample_benchmark_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    yearly = _calendar_period_analysis(equity, closed_trades, sample_benchmark_curve)
    cost_stress = _cost_stress_tests(metrics, trades)
    random_baseline = _random_equal_weight_baseline(sample_bars)
    diagnostics = _robustness_diagnostics(metrics, yearly, cost_stress, random_baseline, sample_benchmark_curve)
    return {
        "status": "ready",
        "yearly_periods": yearly,
        "cost_stress": cost_stress,
        "random_baseline": random_baseline,
        "diagnostics": diagnostics,
        "limitations": [
            "成本压力测试复用已发生交易和权益曲线做近似扣减，没有重新撮合涨跌停和仓位路径。",
            "随机基准为固定种子、多组样本等权组合，不是完整蒙特卡洛执行策略。",
            "年度分段按当前本地样本区间切分；本地历史不足时不能覆盖完整 2020-2024 周期。",
        ],
    }


def _calendar_period_analysis(
    equity: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(equity, key=lambda item: item["trade_date"]):
        trade_date = _as_date(row["trade_date"])
        if trade_date:
            rows_by_year[trade_date.year].append(row)

    result = []
    for year, rows in sorted(rows_by_year.items()):
        if len(rows) < 2:
            continue
        result.append(_period_summary(str(year), f"{year}年", rows, closed_trades, benchmark_curve))
    return result


def _cost_stress_tests(metrics: dict[str, Any], trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    initial_cash = float(metrics.get("initial_cash") or 0)
    final_equity = float(metrics.get("final_equity") or 0)
    base_return = float(metrics.get("total_return_pct") or 0)
    if not initial_cash:
        return []

    traded_amount = sum(float(trade.get("amount") or 0) for trade in trades)
    sell_amount = sum(float(trade.get("amount") or 0) for trade in trades if trade.get("side") == "SELL")
    scenarios = [
        {"id": "base", "label": "原始成本", "extra_bps": 0, "extra_stamp_tax_bps": 0},
        {"id": "slippage_plus_10bps", "label": "滑点再加10bp", "extra_bps": 10, "extra_stamp_tax_bps": 0},
        {"id": "slippage_plus_30bps", "label": "滑点再加30bp", "extra_bps": 30, "extra_stamp_tax_bps": 0},
        {"id": "stamp_tax_plus_5bps", "label": "卖出税费再加5bp", "extra_bps": 0, "extra_stamp_tax_bps": 5},
        {"id": "high_friction", "label": "高摩擦：滑点30bp+卖出5bp", "extra_bps": 30, "extra_stamp_tax_bps": 5},
    ]
    result = []
    for scenario in scenarios:
        extra_cost = traded_amount * scenario["extra_bps"] / 10000 + sell_amount * scenario["extra_stamp_tax_bps"] / 10000
        stressed_equity = final_equity - extra_cost
        stressed_return = (stressed_equity / initial_cash - 1) * 100
        result.append(
            {
                **scenario,
                "extra_cost": extra_cost,
                "final_equity": stressed_equity,
                "total_return_pct": stressed_return,
                "return_delta_pct": stressed_return - base_return,
            }
        )
    return result


def _random_equal_weight_baseline(sample_bars: list[dict[str, Any]], *, seeds: int = 20, sample_size: int = 30) -> dict[str, Any]:
    bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sample_bars:
        vt_symbol = str(row.get("vt_symbol") or "")
        if vt_symbol:
            bars_by_symbol[vt_symbol].append(row)
    symbols = sorted(bars_by_symbol)
    if len(symbols) < 2:
        return {"status": "insufficient_data", "runs": []}

    pick_size = min(max(sample_size, 1), len(symbols))
    runs = []
    for seed in range(seeds):
        rng = random.Random(20260611 + seed)
        selected = sorted(rng.sample(symbols, pick_size))
        rows = [row for symbol in selected for row in bars_by_symbol[symbol]]
        curve = _sample_equal_weight_curve(rows)
        runs.append(
            {
                "seed": seed,
                "symbol_count": pick_size,
                "return_pct": _nav_return_pct(curve),
                "max_drawdown_pct": _nav_max_drawdown(curve) if curve else None,
            }
        )

    returns = [float(row["return_pct"]) for row in runs if row.get("return_pct") is not None]
    drawdowns = [float(row["max_drawdown_pct"]) for row in runs if row.get("max_drawdown_pct") is not None]
    return {
        "status": "ready" if returns else "empty",
        "method": "fixed_seed_equal_weight_subsamples",
        "seed_base": 20260611,
        "run_count": len(runs),
        "sample_size": pick_size,
        "return_avg_pct": mean(returns) if returns else None,
        "return_median_pct": _median(returns) if returns else None,
        "return_min_pct": min(returns) if returns else None,
        "return_max_pct": max(returns) if returns else None,
        "max_drawdown_avg_pct": mean(drawdowns) if drawdowns else None,
        "runs": runs,
    }


def _robustness_diagnostics(
    metrics: dict[str, Any],
    yearly: list[dict[str, Any]],
    cost_stress: list[dict[str, Any]],
    random_baseline: dict[str, Any],
    sample_benchmark_curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    strategy_return = float(metrics.get("total_return_pct") or 0)
    sample_return = _nav_return_pct(sample_benchmark_curve)
    random_avg = random_baseline.get("return_avg_pct")
    high_friction = next((row for row in cost_stress if row["id"] == "high_friction"), None)
    positive_years = [row for row in yearly if float(row.get("return_pct") or 0) > 0]

    result = [
        {
            "id": "sample_equal_weight_excess",
            "label": "样本等权超额",
            "status": "pass" if sample_return is not None and strategy_return > sample_return else "fail",
            "value": strategy_return - sample_return if sample_return is not None else None,
            "message": "策略跑赢样本等权基准" if sample_return is not None and strategy_return > sample_return else "策略未跑赢样本等权基准，需警惕只是在热门样本中择时。",
        },
        {
            "id": "random_baseline_excess",
            "label": "随机样本超额",
            "status": "pass" if random_avg is not None and strategy_return > float(random_avg) else "fail",
            "value": strategy_return - float(random_avg) if random_avg is not None else None,
            "message": "策略跑赢随机样本平均收益" if random_avg is not None and strategy_return > float(random_avg) else "策略未跑赢随机样本平均收益。",
        },
        {
            "id": "high_friction_positive",
            "label": "高摩擦仍盈利",
            "status": "pass" if high_friction and high_friction["total_return_pct"] > 0 else "fail",
            "value": high_friction["total_return_pct"] if high_friction else None,
            "message": "高摩擦成本下仍保持正收益" if high_friction and high_friction["total_return_pct"] > 0 else "高摩擦成本下收益转负或不可验证。",
        },
        {
            "id": "calendar_periods_positive",
            "label": "年度稳定性",
            "status": "pass" if yearly and len(positive_years) == len(yearly) else "warning",
            "value": len(positive_years),
            "value_type": "count",
            "message": "当前覆盖年度均为正收益" if yearly and len(positive_years) == len(yearly) else "年度覆盖不足或存在负收益年度。",
        },
    ]
    return result


def _run_validation_grid(
    session,
    backtest_id: int,
    base_params: BacktestParams,
    bars_by_symbol: dict[str, list[Bar]],
    trading_days: list[date],
    stock_meta: dict[str, dict[str, Any]],
    max_variants: int,
    score_context: ScoreContext | None = None,
) -> dict[str, Any]:
    variants = _validation_param_variants(base_params, max_variants)
    if not variants:
        return {"status": "empty", "backtest_id": backtest_id, "rows": []}

    sample_benchmark_curve = _sample_equal_weight_curve(_bars_to_rows(bars_by_symbol))
    score_cache: dict[date, list[Any]] = {}
    shared_minute_index = (
        _load_minute_bar_index(
            session,
            list(bars_by_symbol),
            trading_days[0],
            trading_days[-1],
            base_params.minute_interval,
        )
        if base_params.intraday_entry
        else {}
    )
    rows = []
    variant_runs = []
    for index, params in enumerate(variants, start=1):
        run = _simulate(session, params, bars_by_symbol, trading_days, stock_meta, score_cache, shared_minute_index, score_context)
        closed_trades = _closed_trades(run["trades"])
        variant_runs.append(
            {
                "variant_id": index,
                "params": params,
                "metrics": run["metrics"],
                "equity": run["equity"],
                "closed_trades": closed_trades,
            }
        )
        periods = _period_analysis(run["equity"], closed_trades, sample_benchmark_curve).get("periods") or []
        in_sample = next((row for row in periods if row.get("id") == "in_sample"), None)
        out_sample = next((row for row in periods if row.get("id") == "out_of_sample"), None)
        cost_stress = _cost_stress_tests(run["metrics"], run["trades"])
        high_friction = next((row for row in cost_stress if row["id"] == "high_friction"), None)
        rows.append(
            _validation_row(
                index,
                params,
                base_params,
                run["metrics"],
                in_sample,
                out_sample,
                sample_benchmark_curve,
                high_friction,
            )
        )

    summary = _validation_grid_summary(rows)
    diagnostics = _validation_grid_diagnostics(summary)
    walk_forward = _walk_forward_grid_analysis(variant_runs, sample_benchmark_curve)
    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "strategy": base_params.strategy,
        "strategy_version": STRATEGY_VERSION,
        "start_date": base_params.start.isoformat(),
        "end_date": (base_params.end or trading_days[-1]).isoformat(),
        "method": "full_resimulation_parameter_grid",
        "variant_count": len(rows),
        "param_space": {
            "min_entry_score": sorted({row["min_entry_score"] for row in rows}),
            "stop_loss_pct": sorted({row["stop_loss_pct"] for row in rows}),
            "take_profit_pct": sorted({row["take_profit_pct"] for row in rows}),
            "strict_entry": sorted({row["strict_entry"] for row in rows}),
        },
        "base_params": _params_to_json(base_params),
        "summary": summary,
        "diagnostics": diagnostics,
        "walk_forward": walk_forward,
        "top_variants": _top_validation_variants(rows),
        "rows": rows,
        "limitations": [
            "参数网格会重新跑选股、入场、出场和仓位路径，但仍使用日线数据，不能验证真实尾盘 14:30 后成交。",
            "网格参数空间只覆盖第一版关键参数，不代表所有可调参数都已穷举。",
            "walk-forward 使用滚动训练/测试窗口，但当前本地历史过短，不能替代 3-5 年跨市场环境验证。",
            "外部财报、资金流、龙虎榜数据不足时，网格只能验证价格成交量代理信号的稳健性。",
        ],
    }


def _validation_param_variants(base_params: BacktestParams, max_variants: int) -> list[BacktestParams]:
    return validation.validation_param_variants(base_params, max_variants, same_grid_params=_same_grid_params)


def _validation_row(
    variant_id: int,
    params: BacktestParams,
    base_params: BacktestParams,
    metrics: dict[str, Any],
    in_sample: dict[str, Any] | None,
    out_sample: dict[str, Any] | None,
    sample_benchmark_curve: list[dict[str, Any]],
    high_friction: dict[str, Any] | None,
) -> dict[str, Any]:
    return validation.validation_row(
        variant_id,
        params,
        base_params,
        metrics,
        in_sample,
        out_sample,
        sample_benchmark_curve,
        high_friction,
        nav_return_pct=_nav_return_pct,
        same_grid_params=_same_grid_params,
    )


def _validation_grid_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return validation.validation_grid_summary(rows, ratio_pct=_ratio_pct, median=_median, rank_for_variant=_rank_for_variant)


def _validation_grid_diagnostics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return validation.validation_grid_diagnostics(summary)


def _walk_forward_grid_analysis(
    variant_runs: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
    *,
    train_days: int = 60,
    test_days: int = 20,
    step_days: int = 20,
) -> dict[str, Any]:
    return validation.walk_forward_grid_analysis(
        variant_runs,
        benchmark_curve,
        as_date=_as_date,
        period_summary=_period_summary,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
    )


def _variant_period_summary(
    period_id: str,
    label: str,
    variant: dict[str, Any],
    start_date: date,
    end_date: date,
    benchmark_curve: list[dict[str, Any]],
    *,
    exclude_start_trade_date: bool = False,
) -> dict[str, Any] | None:
    return validation.variant_period_summary(
        period_id,
        label,
        variant,
        start_date,
        end_date,
        benchmark_curve,
        as_date=_as_date,
        period_summary=_period_summary,
        exclude_start_trade_date=exclude_start_trade_date,
    )


def _walk_forward_summary(folds: list[dict[str, Any]]) -> dict[str, Any]:
    return validation.walk_forward_summary(folds, ratio_pct=_ratio_pct, median=_median)


def _walk_forward_diagnostics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return validation.walk_forward_diagnostics(summary)


def _top_validation_variants(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return validation.top_validation_variants(rows, limit)


def _numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    return validation.numeric_values(rows, key)


def _rank_for_variant(ordered_rows: list[dict[str, Any]], target: dict[str, Any] | None) -> int | None:
    return validation.rank_for_variant(ordered_rows, target)


def _same_grid_params(params: BacktestParams, base_params: BacktestParams) -> bool:
    return validation.same_grid_params(params, base_params)


def _bars_to_rows(bars_by_symbol: dict[str, list[Bar]]) -> list[dict[str, Any]]:
    rows = []
    for vt_symbol, bars in bars_by_symbol.items():
        for bar in bars:
            rows.append(
                {
                    "vt_symbol": vt_symbol,
                    "trade_date": bar.trade_date,
                    "close_price": bar.close_price,
                }
            )
    return rows


def _params_from_run(run: dict[str, Any]) -> BacktestParams:
    raw_params = run.get("params") or {}
    if isinstance(raw_params, str):
        try:
            raw_params = json.loads(raw_params)
        except json.JSONDecodeError:
            raw_params = {}
    if not isinstance(raw_params, dict):
        raw_params = {}

    return BacktestParams(
        strategy=str(raw_params.get("strategy") or run.get("strategy_id") or STRATEGY_ID),
        start=_as_date(raw_params.get("start") or run.get("start_date")) or date(2020, 1, 1),
        end=_as_date(raw_params.get("end") or run.get("end_date")),
        initial_cash=float(raw_params.get("initial_cash") or run.get("initial_cash") or 1_000_000),
        max_positions=int(raw_params.get("max_positions") or 8),
        max_position_pct=float(raw_params.get("max_position_pct") or 0.125),
        commission_rate=float(raw_params.get("commission_rate") or 0.0003),
        stamp_tax_rate=float(raw_params.get("stamp_tax_rate") or 0.0005),
        slippage_bps=float(raw_params.get("slippage_bps") or 10),
        stop_loss_pct=float(raw_params.get("stop_loss_pct") or 0.07),
        take_profit_pct=float(raw_params.get("take_profit_pct") or 0.18),
        trailing_stop_pct=float(raw_params.get("trailing_stop_pct") or 0.08),
        time_stop_days=int(raw_params.get("time_stop_days") or 15),
        candidate_limit=int(raw_params.get("candidate_limit") or 20),
        max_symbols=int(raw_params.get("max_symbols") or 500),
        min_entry_score=float(raw_params.get("min_entry_score") or 68),
        strict_entry=_truthy(raw_params.get("strict_entry", True)),
        execution_model=str(raw_params.get("execution_model") or "legacy_next_open"),
        intraday_entry=_truthy(raw_params.get("intraday_entry", True)),
        minute_entry_required=_truthy(raw_params.get("minute_entry_required", False)),
        minute_interval=_legacy_minute_interval(raw_params.get("minute_interval") or "1m"),
        tail_entry_start=str(raw_params.get("tail_entry_start") or "14:30"),
        tail_entry_end=str(raw_params.get("tail_entry_end") or "14:30"),
        tail_entry_ma5_tolerance_pct=float(raw_params.get("tail_entry_ma5_tolerance_pct") or 1.5),
        symbols=[_normalize_symbol(symbol) for symbol in (raw_params.get("symbols") or []) if _normalize_symbol(symbol)],
        included_boards=normalize_included_boards(raw_params.get("included_boards")),
        persist=False,
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _normalize_execution_model(value: Any) -> str:
    return execution_models.normalize_execution_model(value)


def _normalize_backtest_minute_interval(value: Any) -> str:
    interval = str(value or "1m").strip().lower()
    aliases = {
        "1": "1m",
        "1min": "1m",
        "1分钟": "1m",
    }
    interval = aliases.get(interval, interval)
    if interval not in SUPPORTED_BACKTEST_MINUTE_INTERVALS:
        supported = ", ".join(sorted(SUPPORTED_BACKTEST_MINUTE_INTERVALS))
        raise ValueError(f"Unsupported backtest minute interval: {interval}; supported: {supported}")
    return interval


def _legacy_minute_interval(value: Any) -> str:
    try:
        return _normalize_backtest_minute_interval(value)
    except ValueError:
        return "1m"


def _validation_grid_csv_content(grid: dict[str, Any]) -> str:
    return reports.validation_grid_csv_content(grid)


def _nav_return_pct(curve: list[dict[str, Any]]) -> float | None:
    if not curve:
        return None
    return (float(curve[-1].get("nav") or 0) - 1) * 100


def _report_csv_content(report: dict[str, Any]) -> str:
    return reports.report_csv_content(report)


def _minute_gap_csv_content(orders: list[dict[str, Any]]) -> tuple[str, int]:
    return reports.minute_gap_csv_content(orders, as_date=_as_date)


def _equity_return_pct(equity: list[dict[str, Any]]) -> float | None:
    if len(equity) < 2:
        return None
    start = float(equity[0].get("total_equity") or 0)
    end = float(equity[-1].get("total_equity") or 0)
    return (end / start - 1) * 100 if start else None


def _equity_max_drawdown(equity: list[dict[str, Any]]) -> float:
    peak = None
    max_dd = 0.0
    for row in equity:
        value = float(row.get("total_equity") or 0)
        peak = value if peak is None else max(peak, value)
        if peak:
            max_dd = min(max_dd, (value / peak - 1) * 100)
    return max_dd


def _nav_max_drawdown(curve: list[dict[str, Any]]) -> float:
    peak = None
    max_dd = 0.0
    for row in curve:
        value = float(row.get("nav") or 0)
        peak = value if peak is None else max(peak, value)
        if peak:
            max_dd = min(max_dd, (value / peak - 1) * 100)
    return max_dd


def _data_quality_snapshot(session) -> dict[str, Any]:
    tables = {
        "stocks": schema.stocks,
        "stock_daily_bars": schema.stock_daily_bars,
        "stock_minute_bars": schema.stock_minute_bars,
        "stock_financial_reports": schema.stock_financial_reports,
        "sector_period_scores": schema.sector_period_scores,
        "stock_fund_flows": schema.stock_fund_flows,
        "stock_hot_ranks": schema.stock_hot_ranks,
        "stock_lhb_records": schema.stock_lhb_records,
    }
    result = {}
    for name, table in tables.items():
        count = session.execute(select(func.count()).select_from(table)).scalar_one()
        result[name] = {"count": int(count or 0)}
    daily_count = int((result.get("stock_daily_bars") or {}).get("count") or 0)
    daily_turnover_count = session.execute(
        select(func.count()).select_from(schema.stock_daily_bars).where(schema.stock_daily_bars.c.turnover.is_not(None))
    ).scalar_one()
    result["stock_daily_bars"]["turnover_count"] = int(daily_turnover_count or 0)
    result["stock_daily_bars"]["turnover_coverage_pct"] = _ratio_pct(daily_turnover_count, daily_count)
    result["limitations"] = [
        "stock_fund_flows、stock_hot_ranks、stock_lhb_records 为空时，游资/情绪信号只能使用价格成交量代理。",
        "sector_period_scores 为空时，主线板块评分退化为中性或缺失。",
        "stock_minute_bars 覆盖不足时，尾盘低吸只能对已同步样本做分钟级验证。",
        "stock_financial_reports 为空时，股票详情页实时可查财报也不会进入筛选/回测评分。",
        "stock_daily_bars.turnover 覆盖不足时，流动性评分会退化为 close * volume 估算，可能影响买点过滤。",
    ]
    return result


def _median(values: list[int | float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _ratio_pct(numerator: Any, denominator: Any) -> float | None:
    if not denominator:
        return None
    return float(numerator or 0) / float(denominator) * 100


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _backtest_method(params: BacktestParams) -> dict[str, Any]:
    board_labels = included_board_labels(params.included_boards)
    universe = (
        "指定股票"
        if params.symbols
        else f"按成交额/市值取前 {params.max_symbols} 只本地股票；板块：{', '.join(board_labels)}"
    )
    return {
        "id": "daily_dynamic_candidate_backtest",
        "name": "历史逐日动态候选回测",
        "signal_timing": _execution_signal_timing(params),
        "execution_timing": _execution_timing(params),
        "candidate_policy": "不是用今天的候选名单回测全部历史。",
        "universe": universe,
        "symbols": params.symbols or [],
        "included_boards": list(params.included_boards),
        "included_board_labels": board_labels,
        "entry_filter": {
            "min_entry_score": params.min_entry_score,
            "strict_entry": params.strict_entry,
            "candidate_limit": params.candidate_limit,
        },
        "execution": {
            "execution_model": params.execution_model,
            "intraday_entry": params.intraday_entry,
            "minute_entry_required": params.minute_entry_required,
            "minute_interval": params.minute_interval,
            "tail_entry_window": f"{params.tail_entry_start}-{params.tail_entry_end}",
            "tail_entry_ma5_tolerance_pct": params.tail_entry_ma5_tolerance_pct,
        },
    }


def _backtest_assumptions(params: BacktestParams) -> dict[str, str]:
    return {
        "candidate_generation": _execution_signal_timing(params),
        "execution": _execution_timing(params),
        "execution_model": params.execution_model,
        "tail_entry": _tail_entry_assumption(params),
        "minute_interval": params.minute_interval,
        "tail_entry_window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        "minute_entry_required": str(params.minute_entry_required),
        "costs": "commission, stamp tax on sells, and slippage are included",
        "positioning": "equal cash budget per position, 100-share lot rounded",
        "turnover": "turnover_pct uses traded notional divided by initial cash",
        "data_as_of_policy": "daily bars only; financial data requires publish_date",
    }


def _execution_signal_timing(params: BacktestParams) -> str:
    if params.execution_model in {"tail_close_hybrid", "strict_1430"}:
        return "D 日收盘后生成下一交易日计划；买入和卖出都只执行已经可见的前一交易日信号。"
    return "历史逐日重新打分：D 日收盘后生成 D 日候选，D+1 才能买入。"


def _execution_timing(params: BacktestParams) -> str:
    if params.execution_model == "tail_close_hybrid":
        return "买入/卖出均为收盘信号后的下一交易日执行；优先使用执行日 14:30 分钟快照，没有分钟线时使用执行日收盘价作为尾盘代理。"
    if params.execution_model == "strict_1430":
        return "买入/卖出均为收盘信号后的下一交易日执行；只在执行日 14:30 分钟快照存在时成交，缺 14:30 数据或未触发时拒单。"
    return "兼容旧模型：买入为 D 收盘信号 -> D+1 尾盘分钟/开盘回退；卖出为 D 收盘信号 -> D+1 开盘。"


def _tail_entry_assumption(params: BacktestParams) -> str:
    if params.execution_model == "strict_1430":
        return "严格 14:30 模型使用 D 日收盘可见日线生成下一交易日计划；执行日只在 14:30 的 1 分钟快照存在且满足尾盘条件时成交，否则拒单。"
    if params.execution_model == "tail_close_hybrid":
        return "尾盘混合模型使用 D 日收盘可见日线生成下一交易日计划；执行日 14:30 分钟价优先，无分钟线时用执行日收盘价作为尾盘代理。"
    return "旧兼容模型用于历史报告对比，不作为当前严格 14:30 真实回测口径。"


def _audit_events(orders: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for order in orders:
        raw = order.get("raw") if isinstance(order.get("raw"), dict) else {}
        execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else raw
        events.append(
            {
                "event_type": "order",
                "trade_date": order.get("trade_date"),
                "vt_symbol": order.get("vt_symbol"),
                "name": order.get("name"),
                "board": order.get("board") or _stock_board_payload(order.get("vt_symbol"))["board"],
                "board_label": order.get("board_label") or _stock_board_payload(order.get("vt_symbol"))["board_label"],
                "side": order.get("side"),
                "status": order.get("status"),
                "reason": order.get("reason"),
                "price": order.get("price"),
                "volume": order.get("volume"),
                "execution_mode": execution.get("mode") if isinstance(execution, dict) else None,
                "message": _audit_order_message(order, execution if isinstance(execution, dict) else {}),
                "raw": raw,
            }
        )
    for trade in trades:
        raw = trade.get("raw") if isinstance(trade.get("raw"), dict) else {}
        execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
        events.append(
            {
                "event_type": "trade",
                "trade_date": trade.get("trade_date"),
                "vt_symbol": trade.get("vt_symbol"),
                "name": trade.get("name"),
                "board": trade.get("board") or _stock_board_payload(trade.get("vt_symbol"))["board"],
                "board_label": trade.get("board_label") or _stock_board_payload(trade.get("vt_symbol"))["board_label"],
                "side": trade.get("side"),
                "status": "filled",
                "reason": trade.get("reason"),
                "price": trade.get("price"),
                "volume": trade.get("volume"),
                "pnl": trade.get("pnl"),
                "execution_mode": execution.get("mode"),
                "message": _audit_trade_message(trade, execution),
                "raw": raw,
            }
        )
    events.sort(key=lambda item: (str(item.get("trade_date") or ""), str(item.get("vt_symbol") or ""), item["event_type"]))
    return events


def _audit_order_message(order: dict[str, Any], execution: dict[str, Any]) -> str:
    side = "买入" if order.get("side") == "BUY" else "卖出"
    status = "已成交" if order.get("status") == "filled" else "未成交"
    reason = order.get("reason") or "unknown"
    mode = execution.get("mode")
    if mode == "minute_1430":
        return f"{side}{status}：使用执行日 14:30 真实分钟快照成交，原因 {reason}。"
    if mode == "daily_close_proxy":
        return f"{side}{status}：缺少执行日 14:30 分钟线，使用执行日收盘价作为尾盘代理，原因 {reason}。"
    if mode == "minute_1430_sell":
        return f"{side}{status}：使用执行日 14:30 真实分钟快照卖出，原因 {reason}。"
    if mode == "daily_close_proxy_sell":
        return f"{side}{status}：缺少执行日 14:30 分钟线，使用执行日收盘价作为尾盘代理卖出，原因 {reason}。"
    if mode == "limit_up_tail_unfilled":
        return f"{side}{status}：执行日尾盘涨停或接近涨停，保守判定买不到。"
    if mode == "limit_down_tail_blocked":
        return f"{side}{status}：执行日尾盘跌停或接近跌停，保守判定卖不出。"
    if mode in {"strict_1430_required", "strict_1430_required_sell"}:
        return f"{side}{status}：严格 14:30 模式缺少可用分钟快照或未触发，原因 {reason}。"
    if mode == "minute_tail_ma5":
        return f"{side}{status}：尾盘分钟线接近可见 MA5，原因 {reason}。"
    if mode == "daily_next_open_fallback":
        return f"{side}{status}：分钟尾盘不可用或未触发，回退到 D+1 开盘，原因 {reason}。"
    if mode == "minute_tail_ma5_required":
        return f"{side}{status}：严格分钟模式下尾盘 MA5 未触发或缺分钟线，原因 {reason}。"
    if mode == "daily_close_sell_signal":
        execute_date = execution.get("execute_date")
        return f"卖出信号：收盘后触发 {reason}，计划 {execute_date or '下一交易日'} 开盘撮合。"
    if mode == "daily_next_open_sell":
        signal_date = execution.get("signal_date")
        return f"卖出{status}：{signal_date or '前一交易日'} 收盘信号，当前开盘撮合，原因 {reason}。"
    return f"{side}{status}：{reason}。"


def _audit_trade_message(trade: dict[str, Any], execution: dict[str, Any]) -> str:
    side = "买入" if trade.get("side") == "BUY" else "卖出"
    mode = execution.get("mode")
    if mode == "minute_1430":
        return f"{side}成交：执行日 14:30 真实分钟快照，价格 {trade.get('price')}。"
    if mode == "daily_close_proxy":
        return f"{side}成交：执行日收盘价代理尾盘，价格 {trade.get('price')}。"
    if mode == "minute_1430_sell":
        return f"{side}成交：执行日 14:30 真实分钟快照，盈亏 {trade.get('pnl')}。"
    if mode == "daily_close_proxy_sell":
        return f"{side}成交：执行日收盘价代理尾盘，盈亏 {trade.get('pnl')}。"
    if side == "买入" and mode:
        return f"{side}成交：执行模式 {mode}，价格 {trade.get('price')}。"
    if side == "卖出":
        if mode == "daily_next_open_sell":
            signal_date = execution.get("signal_date")
            return f"{side}成交：{signal_date or '前一交易日'} 收盘触发 {trade.get('reason') or 'unknown'}，当前开盘成交，盈亏 {trade.get('pnl')}。"
        return f"{side}成交：退出原因 {trade.get('reason') or 'unknown'}，盈亏 {trade.get('pnl')}。"
    return f"{side}成交。"


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def _iso_date(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _annualized_return(total_return_pct: float, trading_days: int) -> float:
    if trading_days <= 0:
        return 0.0
    return ((1 + total_return_pct / 100) ** (252 / trading_days) - 1) * 100


def _sharpe(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    std = pstdev(daily_returns)
    if std == 0:
        return None
    return mean(daily_returns) / std * sqrt(252)


def _order(
    trade_date: date,
    vt_symbol: str,
    side: str,
    price: float | None,
    volume: int | None,
    status: str,
    reason: str,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    board = _stock_board_payload(vt_symbol)
    return {
        "trade_date": trade_date,
        "vt_symbol": vt_symbol,
        **board,
        "side": side,
        "price": price,
        "volume": volume,
        "status": status,
        "reason": reason,
        "raw": raw or {},
    }


def _is_limit_up_open(bar: Bar) -> bool:
    return bool(bar.change_pct is not None and bar.change_pct >= 9.8 and bar.open_price >= bar.close_price * 0.995)


def _is_limit_down_open(bar: Bar) -> bool:
    return bool(bar.change_pct is not None and bar.change_pct <= -9.8 and bar.open_price <= bar.close_price * 1.005)


def _is_limit_up_tail(vt_symbol: str, bar: Bar) -> bool:
    threshold = _daily_limit_threshold(vt_symbol)
    return bool(bar.change_pct is not None and bar.change_pct >= threshold)


def _is_limit_down_tail(vt_symbol: str, bar: Bar) -> bool:
    threshold = _daily_limit_threshold(vt_symbol)
    return bool(bar.change_pct is not None and bar.change_pct <= -threshold)


def _daily_limit_threshold(vt_symbol: str) -> float:
    board = stock_board(vt_symbol)
    if board == "bse":
        return 29.8
    if board in {"star", "chinext"}:
        return 19.8
    return 9.8


def _persist_run(session, params: BacktestParams, run: dict[str, Any], end: date) -> int:
    return persistence.persist_run(session, params, run, end, params_to_json=_params_to_json)


def _trade_to_api(trade: Trade) -> dict[str, Any]:
    return {
        "trade_date": trade.trade_date.isoformat(),
        "vt_symbol": trade.vt_symbol,
        **_stock_board_payload(trade.vt_symbol),
        "side": trade.side,
        "price": trade.price,
        "volume": trade.volume,
        "amount": trade.amount,
        "fee": trade.fee,
        "pnl": trade.pnl,
        "reason": trade.reason,
        "raw": _normalize_backtest_raw(trade.raw),
    }


def _table_values(table, item: dict[str, Any]) -> dict[str, Any]:
    return persistence.table_values(table, item)


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if isinstance(result.get("raw"), dict):
        result["raw"] = _normalize_backtest_raw(result["raw"])
    if "reason" in result and "reason_label" not in result:
        result["reason_label"] = backtest_reason_label(result.get("reason"))
    if "linked_order_reason" in result and "linked_order_reason_label" not in result:
        result["linked_order_reason_label"] = backtest_reason_label(result.get("linked_order_reason"))
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def backtest_reason_label(reason: Any) -> str | None:
    return queries.reason_label(reason)


def _normalize_backtest_raw(value: dict[str, Any]) -> dict[str, Any]:
    raw = {}
    for key, item in dict(value or {}).items():
        if isinstance(item, dict):
            raw[key] = _normalize_backtest_raw(item)
        elif hasattr(item, "isoformat"):
            raw[key] = item.isoformat()
        else:
            raw[key] = item
    if raw.get("entry_rule") == "daily_close_signal_next_open_execution":
        raw.pop("entry_rule", None)
        raw.setdefault("selection_rule", "daily_close_visible_signal")
        raw.setdefault("entry_setup", "ma5_pullback")
    return raw


def _run_type_from_params(params: dict[str, Any]) -> str:
    symbols = [symbol for symbol in (params.get("symbols") or []) if symbol]
    return "symbol" if len(symbols) == 1 else "portfolio"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dates(row: dict[str, Any]) -> dict[str, Any]:
    return persistence.parse_dates(row)


def _params_to_json(params: BacktestParams) -> dict[str, Any]:
    result = dict(params.__dict__)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif isinstance(value, tuple):
            result[key] = list(value)
    return result
