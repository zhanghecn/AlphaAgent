"""Daily-bar portfolio backtest for AlphaAgent quant strategies."""

from __future__ import annotations

import csv
import io
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from itertools import product
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
from alphaagent.server.services.quant.factors import STRATEGY_ID, STRATEGY_VERSION, Bar, score_financial_report, score_stock
from alphaagent.server.services.quant.screening import (
    _load_financial_scores,
    _load_fund_flow_scores,
    _load_hot_rank_scores,
    _load_index_return_20d,
    _load_lhb_scores,
    _load_sector_scores,
)


@dataclass
class BacktestParams:
    strategy: str = STRATEGY_ID
    start: date = date(2020, 1, 1)
    end: date | None = None
    initial_cash: float = 1_000_000
    max_positions: int = 8
    max_position_pct: float = 0.125
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_bps: float = 10
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.18
    trailing_stop_pct: float = 0.08
    time_stop_days: int = 15
    candidate_limit: int = 20
    max_symbols: int = 500
    min_entry_score: float = 68.0
    strict_entry: bool = True
    intraday_entry: bool = True
    minute_entry_required: bool = False
    tail_entry_start: str = "14:30"
    tail_entry_end: str = "14:57"
    tail_entry_ma5_tolerance_pct: float = 1.5
    persist: bool = False
    symbols: list[str] | None = None
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS

    def __post_init__(self) -> None:
        self.included_boards = normalize_included_boards(self.included_boards)


@dataclass(frozen=True)
class MinuteBar:
    bar_time: datetime
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None = None
    turnover: float | None = None


@dataclass
class Position:
    vt_symbol: str
    name: str | None
    volume: int
    cost_price: float
    entry_date: date
    highest_price: float
    reason: dict[str, Any]


@dataclass
class Trade:
    trade_date: date
    vt_symbol: str
    side: str
    price: float
    volume: int
    amount: float
    fee: float
    pnl: float | None = None
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreContext:
    financial_rows_by_symbol: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def run_backtest(params: BacktestParams) -> dict[str, Any]:
    if params.strategy != STRATEGY_ID:
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
        bars_by_symbol = _load_all_bars(session, vt_symbols, params.start, end)
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
        "strategy_version": STRATEGY_VERSION,
        "start": params.start.isoformat(),
        "end": end.isoformat(),
        "metrics": run["metrics"],
        "equity": run["equity"],
        "trades": run["trades"],
        "orders": run["orders"],
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


def list_backtests(limit: int = 50) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    _ensure_backtest_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.backtest_runs).order_by(desc(schema.backtest_runs.c.id)).limit(min(max(limit, 1), 200))
        ).mappings().all()
    return {"status": "ready", "items": [_mapping_to_api(dict(row)) for row in rows]}


def backtest_metrics(backtest_id: int) -> dict[str, Any]:
    detail = get_backtest(backtest_id)
    if detail.get("status") != "ready":
        return detail
    return {"status": "ready", "backtest_id": backtest_id, "metrics": detail["item"].get("metrics") or {}}


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
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
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
    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "strategy_id": run["strategy_id"],
        "strategy_version": run["strategy_version"],
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "sample": _mapping_to_api(sample_payload),
        "metrics": metrics,
        "extended_metrics": extended_metrics,
        "summary_rows": _metric_rows(metrics),
        "trades": [_mapping_to_api(row) for row in trade_dicts],
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
        "data_quality": data_quality,
        "method": _backtest_method(params),
        "assumptions": _backtest_assumptions(params),
        "limitations": [
            "当前本地样本不是全 A，只能作为小样本真实日线模拟。",
            "分钟线只覆盖已同步股票和日期；未覆盖订单会在 raw.execution.mode 中标记为 daily_next_open_fallback，除非 minute_entry_required=true。",
            "板块周期评分、资金流、热度、龙虎榜数据不完整时会降低主线/游资信号可信度。",
            "财报仅在 publish_date 不晚于交易日时参与评分，缺披露日的数据不会用于真实回测。",
            "上证指数、沪深300、中证500、中证1000基准会临时从外部行情获取，尚未持久化为本地可审计指数表。",
            "样本内/样本外分段为时间切分的初步检查，不等同于完整 walk-forward 验证。",
            "市场环境分段当前按样本等权基准粗分，尚未使用正式指数/行业 regime 模型。",
            "参数网格验证通过 /api/backtests/{id}/validation-grid 单独重跑，报告页默认不自动嵌入以避免误触发长任务。",
        ],
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
    """Export strict-tail rejected buy orders as a minute gap CSV."""

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
                schema.backtest_orders.c.side == "BUY",
                schema.backtest_orders.c.status == "rejected",
                schema.backtest_orders.c.reason == "tail_entry_not_triggered",
            )
            .order_by(schema.backtest_orders.c.trade_date, schema.backtest_orders.c.vt_symbol, schema.backtest_orders.c.id)
        ).mappings().all()

    content, gap_count = _minute_gap_csv_content([dict(row) for row in rows])
    return {
        "status": "ready" if gap_count else "empty",
        "backtest_id": backtest_id,
        "gap_count": gap_count,
        "filename": f"alphaagent_minute_gap_backtest_{backtest_id}_{run['start_date']}_{run['end_date']}.csv",
        "content": content,
        "note": "导出 strict minute_entry_required 回测中被 tail_entry_not_triggered 拒绝的买入订单，用于补齐 D+1 尾盘 1 分钟线。",
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
        bars_by_symbol = _load_all_bars(session, vt_symbols, base_params.start, end)
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


def backtest_trades(backtest_id: int, limit: int = 500) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_backtest_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.backtest_trades)
            .where(schema.backtest_trades.c.backtest_id == backtest_id)
            .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
            .limit(min(max(limit, 1), 2000))
        ).mappings().all()
        row_dicts = [dict(row) for row in rows]
        stock_names = _load_stock_names(session, _symbols_from_rows(row_dicts))
    return {"status": "ready" if rows else "empty", "items": [_mapping_to_api(row) for row in _with_stock_names(row_dicts, stock_names)]}


def backtest_equity(backtest_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_backtest_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.backtest_daily_equity)
            .where(schema.backtest_daily_equity.c.backtest_id == backtest_id)
            .order_by(schema.backtest_daily_equity.c.trade_date)
        ).mappings().all()
    return {"status": "ready" if rows else "empty", "items": [_mapping_to_api(dict(row)) for row in rows]}


def backtest_audit(backtest_id: int, vt_symbol: str | None = None, limit: int = 200) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    _ensure_backtest_schema()
    symbol = _normalize_symbol(vt_symbol) if vt_symbol else None
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
        stock_names = _load_stock_names(session, _symbols_from_rows(order_dicts, trade_dicts))

    params = _params_from_run(dict(run))
    order_items = [_mapping_to_api(row) for row in _with_stock_names(order_dicts, stock_names)]
    trade_items = [_mapping_to_api(row) for row in _with_stock_names(trade_dicts, stock_names)]
    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "vt_symbol": symbol,
        "strategy_id": run["strategy_id"],
        "strategy_version": run["strategy_version"],
        "start_date": run["start_date"].isoformat(),
        "end_date": run["end_date"].isoformat(),
        "method": _backtest_method(params),
        "params": _params_to_json(params),
        "orders": order_items,
        "trades": trade_items,
        "events": _audit_events(order_items, trade_items),
        "order_summary": _order_stats(order_items),
        "note": "组合回测会在历史每个交易日重新计算当日候选，并在下一交易日按执行规则买入；不是把今天候选名单套到过去。",
    }


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
    cash = params.initial_cash
    positions: dict[str, Position] = {}
    pending_buys: list[dict[str, Any]] = []
    pending_sells: list[dict[str, Any]] = []
    trades: list[Trade] = []
    orders: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    bar_index = _bar_index(bars_by_symbol)
    if params.intraday_entry:
        minute_index = minute_index if minute_index is not None else _load_minute_bar_index(session, list(bars_by_symbol), trading_days[0], trading_days[-1])
    else:
        minute_index = {}

    for index, current_day in enumerate(trading_days):
        today_bars = {symbol: bar_index[symbol][current_day] for symbol in bar_index if current_day in bar_index[symbol]}

        for order in list(pending_sells):
            if order["execute_date"] != current_day:
                continue
            pending_sells.remove(order)
            position = positions.get(order["vt_symbol"])
            if not position:
                continue
            bar = today_bars.get(order["vt_symbol"])
            raw = {
                "mode": "daily_next_open_sell",
                "signal_date": order["signal_date"].isoformat(),
                "execute_date": current_day.isoformat(),
                "entry_date": position.entry_date.isoformat(),
                "reason": order["reason"],
            }
            if not bar:
                orders.append(_order(current_day, order["vt_symbol"], "SELL", None, position.volume, "rejected", "no_bar", raw))
                continue
            if _is_limit_down_open(bar):
                orders.append(_order(current_day, order["vt_symbol"], "SELL", None, position.volume, "rejected", "limit_down", raw))
                continue
            fill_price = bar.open_price * (1 - params.slippage_bps / 10000)
            amount = fill_price * position.volume
            fee = amount * (params.commission_rate + params.stamp_tax_rate)
            pnl = (fill_price - position.cost_price) * position.volume - fee
            cash += amount - fee
            del positions[order["vt_symbol"]]
            orders.append(_order(current_day, order["vt_symbol"], "SELL", fill_price, position.volume, "filled", order["reason"], raw))
            trades.append(Trade(current_day, order["vt_symbol"], "SELL", fill_price, position.volume, amount, fee, pnl, order["reason"], raw))

        for order in list(pending_buys):
            if order["execute_date"] != current_day:
                continue
            pending_buys.remove(order)
            if order["vt_symbol"] in positions:
                continue
            if len(positions) >= params.max_positions:
                orders.append(_order(current_day, order["vt_symbol"], "BUY", None, None, "rejected", "position_slot_unavailable"))
                continue
            bar = today_bars.get(order["vt_symbol"])
            if not bar or _is_limit_up_open(bar):
                orders.append(_order(current_day, order["vt_symbol"], "BUY", None, None, "rejected", "limit_up_or_no_bar"))
                continue
            fill = _resolve_buy_fill(order, current_day, bar, bar_index, minute_index, params)
            if fill.get("status") != "filled":
                orders.append(
                    _order(
                        current_day,
                        order["vt_symbol"],
                        "BUY",
                        fill.get("price"),
                        0,
                        "rejected",
                        str(fill.get("reason") or "tail_entry_not_triggered"),
                        fill,
                    )
                )
                continue
            target_cash = params.initial_cash * params.max_position_pct
            budget = min(cash, target_cash)
            fill_price = float(fill["price"]) * (1 + params.slippage_bps / 10000)
            volume = int(budget / fill_price / 100) * 100
            if volume <= 0:
                orders.append(_order(current_day, order["vt_symbol"], "BUY", fill_price, 0, "rejected", "insufficient_cash", fill))
                continue
            amount = fill_price * volume
            fee = amount * params.commission_rate
            if amount + fee > cash:
                volume = int(cash / (fill_price * (1 + params.commission_rate)) / 100) * 100
                amount = fill_price * volume
                fee = amount * params.commission_rate
            if volume <= 0:
                orders.append(_order(current_day, order["vt_symbol"], "BUY", fill_price, 0, "rejected", "insufficient_cash", fill))
                continue
            cash -= amount + fee
            entry_reason = dict(order["reason"])
            entry_reason["execution"] = fill
            positions[order["vt_symbol"]] = Position(
                vt_symbol=order["vt_symbol"],
                name=stock_meta.get(order["vt_symbol"], {}).get("name"),
                volume=volume,
                cost_price=fill_price,
                entry_date=current_day,
                highest_price=bar.high_price,
                reason=entry_reason,
            )
            orders.append(_order(current_day, order["vt_symbol"], "BUY", fill_price, volume, "filled", "entry_signal", fill))
            trades.append(Trade(current_day, order["vt_symbol"], "BUY", fill_price, volume, amount, fee, None, "entry_signal", entry_reason))

        pending_sell_symbols = {str(order["vt_symbol"]) for order in pending_sells}
        for vt_symbol, position in list(positions.items()):
            if vt_symbol in pending_sell_symbols:
                continue
            bar = today_bars.get(vt_symbol)
            if not bar:
                continue
            position.highest_price = max(position.highest_price, bar.high_price)
            sell_reason = _sell_reason(position, bar, current_day, params)
            if not sell_reason:
                continue
            if current_day <= position.entry_date:
                continue
            if index >= len(trading_days) - 1:
                continue
            next_day = trading_days[index + 1]
            raw = {
                "mode": "daily_close_sell_signal",
                "signal_date": current_day.isoformat(),
                "execute_date": next_day.isoformat(),
                "entry_date": position.entry_date.isoformat(),
                "reason": sell_reason,
            }
            pending_sells.append(
                {
                    "execute_date": next_day,
                    "signal_date": current_day,
                    "vt_symbol": vt_symbol,
                    "reason": sell_reason,
                }
            )
            pending_sell_symbols.add(vt_symbol)
            orders.append(_order(current_day, vt_symbol, "SELL", None, position.volume, "pending", sell_reason, raw))

        if index < len(trading_days) - 1:
            next_day = trading_days[index + 1]
            reserved_exit_count = len({str(order["vt_symbol"]) for order in pending_sells})
            free_slots = max(params.max_positions - len(positions) + reserved_exit_count - len(pending_buys), 0)
            if free_slots > 0:
                candidates = _score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
                for candidate in candidates[: min(free_slots, params.candidate_limit)]:
                    if candidate.vt_symbol in positions:
                        continue
                    pending_buys.append({
                        "execute_date": next_day,
                        "signal_date": current_day,
                        "vt_symbol": candidate.vt_symbol,
                        "reason": candidate.evidence,
                    })

        total_equity = cash + _market_value(positions, today_bars)
        equity_curve.append(
            {
                "trade_date": current_day,
                "cash": cash,
                "market_value": total_equity - cash,
                "total_equity": total_equity,
                "position_count": len(positions),
            }
        )

    metrics = _metrics(params.initial_cash, equity_curve, trades)
    return {
        "metrics": metrics,
        "equity": [_mapping_to_api(item) for item in equity_curve],
        "trades": [_trade_to_api(trade) for trade in trades],
        "orders": [_mapping_to_api(item) for item in orders],
    }


def _score_day(
    session,
    bars_by_symbol: dict[str, list[Bar]],
    trade_date: date,
    params: BacktestParams,
    score_cache: dict[date, list[Any]] | None = None,
    score_context: ScoreContext | None = None,
):
    if score_cache is not None and trade_date in score_cache:
        scores = score_cache[trade_date]
    else:
        scores = _score_candidates_for_day(session, bars_by_symbol, trade_date, score_context)
        if score_cache is not None:
            score_cache[trade_date] = scores
    candidates = [score for score in scores if _is_buy_candidate(score, params)]
    candidates.sort(key=lambda item: (-item.total_score, item.vt_symbol))
    return candidates


def _score_candidates_for_day(
    session,
    bars_by_symbol: dict[str, list[Bar]],
    trade_date: date,
    score_context: ScoreContext | None = None,
) -> list[Any]:
    vt_symbols = list(bars_by_symbol.keys())
    index_return_20d = _load_index_return_20d(session, trade_date)
    sector_scores = _load_sector_scores(session, vt_symbols, trade_date)
    financial_scores = (
        _financial_scores_from_context(score_context, trade_date)
        if score_context is not None
        else _load_financial_scores(session, vt_symbols, trade_date)
    )
    fund_flow_scores = _load_fund_flow_scores(session, vt_symbols, trade_date)
    hot_rank_scores = _load_hot_rank_scores(session, vt_symbols, trade_date)
    lhb_scores = _load_lhb_scores(session, vt_symbols, trade_date)
    scores = []
    for vt_symbol, bars in bars_by_symbol.items():
        score = score_stock(
            vt_symbol,
            bars,
            trade_date,
            index_return_20d=index_return_20d,
            sector_score=sector_scores.get(vt_symbol),
            financial_score=financial_scores.get(vt_symbol),
            fund_flow_score=fund_flow_scores.get(vt_symbol),
            hot_rank_score=hot_rank_scores.get(vt_symbol),
            lhb_score=lhb_scores.get(vt_symbol),
        )
        scores.append(score)
    scores.sort(key=lambda item: (-item.total_score, item.vt_symbol))
    return scores


def _is_buy_candidate(score, params: BacktestParams) -> bool:
    if score.evidence.get("status") != "ready":
        return False
    if score.total_score < params.min_entry_score:
        return False
    if score.risk_score < 35 or score.liquidity_score < 25:
        return False
    if params.strict_entry:
        return bool(score.entry_signal)
    return True


def _sell_reason(position: Position, bar: Bar, current_day: date, params: BacktestParams) -> str | None:
    if bar.close_price <= position.cost_price * (1 - params.stop_loss_pct):
        return "stop_loss"
    if bar.close_price >= position.cost_price * (1 + params.take_profit_pct):
        return "take_profit"
    if bar.close_price <= position.highest_price * (1 - params.trailing_stop_pct):
        return "trailing_stop"
    if (current_day - position.entry_date).days >= params.time_stop_days * 2:
        return "time_stop"
    return None


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
    result: dict[str, float] = {}
    for vt_symbol, rows in score_context.financial_rows_by_symbol.items():
        for row in rows:
            publish_date = _as_date(row.get("publish_date"))
            if publish_date is None or publish_date > trade_date:
                continue
            result[vt_symbol] = score_financial_report(row)
            break
    return result


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
    return {symbol: {bar.trade_date: bar for bar in bars} for symbol, bars in bars_by_symbol.items()}


def _market_value(positions: dict[str, Position], today_bars: dict[str, Bar]) -> float:
    value = 0.0
    for vt_symbol, position in positions.items():
        bar = today_bars.get(vt_symbol)
        if bar:
            value += bar.close_price * position.volume
        else:
            value += position.cost_price * position.volume
    return value


def _resolve_buy_fill(
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    params: BacktestParams,
) -> dict[str, Any]:
    vt_symbol = str(order["vt_symbol"])
    if not params.intraday_entry:
        return {"status": "filled", "price": daily_bar.open_price, "mode": "daily_next_open"}

    reference_date = _as_date(order.get("signal_date")) or _previous_trade_date(bar_index.get(vt_symbol, {}), current_day)
    ma5 = _ma5_for_entry_day(bar_index.get(vt_symbol, {}), reference_date) if reference_date else None
    minute_bars = minute_index.get(vt_symbol, {}).get(current_day, [])
    trigger = _tail_entry_trigger(minute_bars, ma5, params)
    if trigger:
        return {
            "status": "filled",
            "price": trigger.close_price,
            "mode": "minute_tail_ma5",
            "bar_time": trigger.bar_time.isoformat(sep=" "),
            "reference_date": reference_date.isoformat() if reference_date else None,
            "ma5": ma5,
            "ma5_distance_pct": _pct_distance(trigger.close_price, ma5),
            "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        }
    if params.minute_entry_required:
        return {
            "status": "rejected",
            "price": None,
            "reason": "tail_entry_not_triggered",
            "mode": "minute_tail_ma5_required",
            "minute_bar_count": len(minute_bars),
            "reference_date": reference_date.isoformat() if reference_date else None,
            "ma5": ma5,
            "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        }
    return {
        "status": "filled",
        "price": daily_bar.open_price,
        "mode": "daily_next_open_fallback",
        "fallback_reason": "minute_tail_entry_unavailable_or_not_triggered",
        "minute_bar_count": len(minute_bars),
        "reference_date": reference_date.isoformat() if reference_date else None,
        "ma5": ma5,
        "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
    }


def _tail_entry_trigger(minute_bars: list[MinuteBar], ma5: float | None, params: BacktestParams) -> MinuteBar | None:
    if ma5 is None or ma5 <= 0:
        return None
    start = _parse_hhmm(params.tail_entry_start)
    end = _parse_hhmm(params.tail_entry_end)
    for bar in sorted(minute_bars, key=lambda item: item.bar_time):
        hhmm = bar.bar_time.time()
        if hhmm < start or hhmm > end:
            continue
        distance = _pct_distance(bar.close_price, ma5)
        if distance is not None and abs(distance) <= params.tail_entry_ma5_tolerance_pct:
            return bar
    return None


def _ma5_for_entry_day(symbol_bars: dict[date, Bar], reference_date: date | None) -> float | None:
    if reference_date is None:
        return None
    closes = [bar.close_price for day, bar in sorted(symbol_bars.items()) if day <= reference_date]
    if len(closes) < 5:
        return None
    return sum(closes[-5:]) / 5


def _previous_trade_date(symbol_bars: dict[date, Bar], current_day: date) -> date | None:
    previous = [day for day in symbol_bars if day < current_day]
    return max(previous) if previous else None


def _parse_hhmm(value: str):
    return datetime.strptime(value, "%H:%M").time()


def _pct_distance(value: float | None, reference: float | None) -> float | None:
    if value is None or reference in (None, 0):
        return None
    return (float(value) / float(reference) - 1) * 100


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
        "trade_count": len(sell_trades),
        "win_rate": len(wins) / len(sell_trades) if sell_trades else 0,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) else None,
        "average_win": mean(wins) if wins else 0,
        "average_loss": mean(losses) if losses else 0,
        "sharpe": sharpe,
        "minute_tail_entry_count": execution_modes.get("minute_tail_ma5", 0),
        "daily_open_fallback_count": execution_modes.get("daily_next_open_fallback", 0),
    }


def _metric_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {
        "initial_cash": "初始资金",
        "final_equity": "期末权益",
        "total_return_pct": "总收益率",
        "annual_return_pct": "年化收益率",
        "max_drawdown_pct": "最大回撤",
        "trade_count": "平仓交易数",
        "win_rate": "胜率",
        "profit_factor": "盈亏比",
        "average_win": "平均盈利",
        "average_loss": "平均亏损",
        "sharpe": "Sharpe",
        "minute_tail_entry_count": "分钟尾盘成交数",
        "daily_open_fallback_count": "日线开盘回退成交数",
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
    sell_trades = [trade for trade in all_trades if trade.get("side") == "SELL"]
    buy_trades = [trade for trade in all_trades if trade.get("side") == "BUY"]
    holding_days = [int(trade["holding_days"]) for trade in closed_trades if trade.get("holding_days") is not None]
    traded_amount = sum(float(trade.get("amount") or 0) for trade in all_trades)
    initial_cash = float(metrics.get("initial_cash") or 0)
    rejected_orders = [order for order in orders if order.get("status") == "rejected"]
    exposure = [float(row.get("market_value") or 0) / float(row.get("total_equity") or 1) for row in equity if row.get("total_equity")]
    execution_modes = _trade_execution_mode_counts(buy_trades)

    return {
        "total_trade_rows": len(all_trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "closed_trade_count": len(closed_trades),
        "open_trade_count": max(len(buy_trades) - len(sell_trades), 0),
        "average_holding_days": mean(holding_days) if holding_days else 0,
        "median_holding_days": _median(holding_days),
        "turnover_pct": traded_amount / initial_cash * 100 if initial_cash else None,
        "traded_amount": traded_amount,
        "average_exposure_pct": mean(exposure) * 100 if exposure else 0,
        "max_position_count": max((int(row.get("position_count") or 0) for row in equity), default=0),
        "rejected_order_count": len(rejected_orders),
        "filled_order_count": len([order for order in orders if order.get("status") == "filled"]),
        "execution_modes": execution_modes,
    }


def _execution_quality_report(
    metrics: dict[str, Any],
    extended_metrics: dict[str, Any],
    data_quality: dict[str, Any],
    sample: dict[str, Any],
) -> dict[str, Any]:
    execution_modes = extended_metrics.get("execution_modes") or {}
    buy_count = int(extended_metrics.get("buy_count") or 0)
    minute_tail_count = int(metrics.get("minute_tail_entry_count") or execution_modes.get("minute_tail_ma5") or 0)
    daily_fallback_count = int(metrics.get("daily_open_fallback_count") or execution_modes.get("daily_next_open_fallback") or 0)
    minute_bar_count = int((data_quality.get("stock_minute_bars") or {}).get("count") or 0)
    daily_bar_count = int((data_quality.get("stock_daily_bars") or {}).get("count") or 0)
    financial_count = int((data_quality.get("stock_financial_reports") or {}).get("count") or 0)
    coverage_pct = sample.get("coverage_pct")

    diagnostics = [
        {
            "id": "minute_tail_entry_coverage",
            "label": "尾盘分钟成交覆盖",
            "status": "pass" if buy_count > 0 and minute_tail_count / buy_count >= 0.8 else "warning",
            "value": _ratio_pct(minute_tail_count, buy_count),
            "value_type": "pct",
            "message": (
                "大多数买入由分钟尾盘 MA5 规则成交。"
                if buy_count > 0 and minute_tail_count / buy_count >= 0.8
                else "当前买入主要不是分钟尾盘成交，不能宣称已充分验证尾盘低吸。"
            ),
        },
        {
            "id": "daily_open_fallback_rate",
            "label": "日线开盘回退占比",
            "status": "pass" if buy_count == 0 or daily_fallback_count / buy_count <= 0.2 else "warning",
            "value": _ratio_pct(daily_fallback_count, buy_count),
            "value_type": "pct",
            "message": (
                "日线开盘回退占比较低。"
                if buy_count == 0 or daily_fallback_count / buy_count <= 0.2
                else "多数买入回退到 D+1 开盘，尾盘成交真实性依赖后续补分钟数据。"
            ),
        },
        {
            "id": "daily_sample_coverage",
            "label": "股票池日线覆盖",
            "status": "pass" if coverage_pct is not None and float(coverage_pct) >= 80 else "warning",
            "value": coverage_pct,
            "value_type": "pct",
            "message": (
                "日线样本接近全股票池覆盖。"
                if coverage_pct is not None and float(coverage_pct) >= 80
                else "当前回测样本不是全 A，只能代表本地已同步股票池。"
            ),
        },
        {
            "id": "financial_data_presence",
            "label": "财报数据覆盖",
            "status": "pass" if financial_count > 0 else "warning",
            "value": financial_count,
            "value_type": "count",
            "message": "财报数据已参与披露日约束评分。" if financial_count > 0 else "财报数据缺失，现金流改善只能降级处理。",
        },
    ]

    return {
        "status": "warning" if any(item["status"] != "pass" for item in diagnostics) else "pass",
        "buy_count": buy_count,
        "minute_tail_entry_count": minute_tail_count,
        "daily_open_fallback_count": daily_fallback_count,
        "minute_tail_entry_ratio": _ratio_pct(minute_tail_count, buy_count),
        "daily_open_fallback_ratio": _ratio_pct(daily_fallback_count, buy_count),
        "minute_bar_count": minute_bar_count,
        "daily_bar_count": daily_bar_count,
        "financial_report_count": financial_count,
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
        _load_minute_bar_index(session, list(bars_by_symbol), trading_days[0], trading_days[-1])
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
    min_scores = [64.0, 68.0, 72.0]
    stop_losses = [0.05, 0.07, 0.09]
    take_profits = [0.14, 0.18, 0.22]
    strict_values = [True, False]
    variants = []
    for min_score, stop_loss, take_profit, strict_entry in product(min_scores, stop_losses, take_profits, strict_values):
        variants.append(
            replace(
                base_params,
                min_entry_score=min_score,
                stop_loss_pct=stop_loss,
                take_profit_pct=take_profit,
                strict_entry=strict_entry,
                persist=False,
            )
        )
    max_count = max(min(max_variants, len(variants)), 1)
    base_index = next((index for index, params in enumerate(variants) if _same_grid_params(params, base_params)), None)
    if base_index is None or base_index < max_count:
        return variants[:max_count]
    selected = variants[: max_count - 1]
    selected.append(variants[base_index])
    return selected


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
    strategy_return = metrics.get("total_return_pct")
    sample_return = _nav_return_pct(sample_benchmark_curve)
    return {
        "variant_id": variant_id,
        "is_base_params": _same_grid_params(params, base_params),
        "min_entry_score": params.min_entry_score,
        "stop_loss_pct": params.stop_loss_pct,
        "take_profit_pct": params.take_profit_pct,
        "strict_entry": params.strict_entry,
        "final_equity": metrics.get("final_equity"),
        "total_return_pct": strategy_return,
        "annual_return_pct": metrics.get("annual_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "trade_count": metrics.get("trade_count"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "sharpe": metrics.get("sharpe"),
        "in_sample_return_pct": (in_sample or {}).get("return_pct"),
        "out_sample_return_pct": (out_sample or {}).get("return_pct"),
        "out_sample_excess_pct": (out_sample or {}).get("excess_return_pct"),
        "sample_equal_weight_return_pct": sample_return,
        "sample_equal_weight_excess_pct": (
            float(strategy_return) - float(sample_return)
            if strategy_return is not None and sample_return is not None
            else None
        ),
        "high_friction_return_pct": (high_friction or {}).get("total_return_pct"),
    }


def _validation_grid_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = _numeric_values(rows, "total_return_pct")
    out_returns = _numeric_values(rows, "out_sample_return_pct")
    excess_returns = _numeric_values(rows, "sample_equal_weight_excess_pct")
    high_friction_returns = _numeric_values(rows, "high_friction_return_pct")
    base_row = next((row for row in rows if row.get("is_base_params")), None)
    ranked_total = sorted(rows, key=lambda row: (float(row.get("total_return_pct") or -1e9), -abs(float(row.get("max_drawdown_pct") or 0))), reverse=True)
    ranked_out = sorted(rows, key=lambda row: (float(row.get("out_sample_return_pct") or -1e9), -abs(float(row.get("max_drawdown_pct") or 0))), reverse=True)

    return {
        "variant_count": len(rows),
        "positive_count": len([value for value in returns if value > 0]),
        "positive_ratio": _ratio_pct(len([value for value in returns if value > 0]), len(returns)),
        "out_sample_positive_count": len([value for value in out_returns if value > 0]),
        "out_sample_positive_ratio": _ratio_pct(len([value for value in out_returns if value > 0]), len(out_returns)),
        "sample_excess_positive_count": len([value for value in excess_returns if value > 0]),
        "sample_excess_positive_ratio": _ratio_pct(len([value for value in excess_returns if value > 0]), len(excess_returns)),
        "high_friction_positive_count": len([value for value in high_friction_returns if value > 0]),
        "high_friction_positive_ratio": _ratio_pct(len([value for value in high_friction_returns if value > 0]), len(high_friction_returns)),
        "return_avg_pct": mean(returns) if returns else None,
        "return_median_pct": _median(returns) if returns else None,
        "return_min_pct": min(returns) if returns else None,
        "return_max_pct": max(returns) if returns else None,
        "out_sample_return_median_pct": _median(out_returns) if out_returns else None,
        "base_variant_id": base_row.get("variant_id") if base_row else None,
        "base_total_return_pct": base_row.get("total_return_pct") if base_row else None,
        "base_out_sample_return_pct": base_row.get("out_sample_return_pct") if base_row else None,
        "base_total_rank": _rank_for_variant(ranked_total, base_row),
        "base_out_sample_rank": _rank_for_variant(ranked_out, base_row),
        "best_total_variant_id": ranked_total[0]["variant_id"] if ranked_total else None,
        "best_out_sample_variant_id": ranked_out[0]["variant_id"] if ranked_out else None,
    }


def _validation_grid_diagnostics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    positive_ratio = summary.get("positive_ratio")
    out_ratio = summary.get("out_sample_positive_ratio")
    excess_ratio = summary.get("sample_excess_positive_ratio")
    friction_ratio = summary.get("high_friction_positive_ratio")
    base_out_rank = summary.get("base_out_sample_rank")
    variant_count = int(summary.get("variant_count") or 0)

    return [
        {
            "id": "grid_positive_ratio",
            "label": "参数组合盈利占比",
            "status": "pass" if positive_ratio is not None and positive_ratio >= 60 else "warning",
            "value": positive_ratio,
            "value_type": "pct",
            "message": "多数参数组合为正收益" if positive_ratio is not None and positive_ratio >= 60 else "盈利依赖少数组合，参数敏感性偏高。",
        },
        {
            "id": "grid_out_sample_positive_ratio",
            "label": "样本外盈利占比",
            "status": "pass" if out_ratio is not None and out_ratio >= 50 else "fail",
            "value": out_ratio,
            "value_type": "pct",
            "message": "样本外多数参数为正收益" if out_ratio is not None and out_ratio >= 50 else "样本外稳定性不足，不能认为策略已抗过拟合。",
        },
        {
            "id": "grid_sample_excess_ratio",
            "label": "跑赢样本等权占比",
            "status": "pass" if excess_ratio is not None and excess_ratio >= 50 else "fail",
            "value": excess_ratio,
            "value_type": "pct",
            "message": "多数参数跑赢样本等权" if excess_ratio is not None and excess_ratio >= 50 else "多数参数未跑赢样本等权，选股优势仍不足。",
        },
        {
            "id": "grid_high_friction_ratio",
            "label": "高摩擦正收益占比",
            "status": "pass" if friction_ratio is not None and friction_ratio >= 60 else "warning",
            "value": friction_ratio,
            "value_type": "pct",
            "message": "多数参数在更高交易成本下仍为正" if friction_ratio is not None and friction_ratio >= 60 else "交易成本压力下收益容易被吃掉。",
        },
        {
            "id": "base_out_sample_rank",
            "label": "当前参数样本外排名",
            "status": "pass" if base_out_rank and variant_count and base_out_rank <= max(1, int(variant_count * 0.33)) else "warning",
            "value": base_out_rank,
            "value_type": "count",
            "message": "当前参数处于样本外排名前列" if base_out_rank and variant_count and base_out_rank <= max(1, int(variant_count * 0.33)) else "当前参数不是样本外最稳组合，需谨慎使用默认值。",
        },
    ]


def _walk_forward_grid_analysis(
    variant_runs: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
    *,
    train_days: int = 60,
    test_days: int = 20,
    step_days: int = 20,
) -> dict[str, Any]:
    if not variant_runs:
        return {"status": "insufficient_data", "folds": [], "diagnostics": []}
    dates = [
        _as_date(row.get("trade_date"))
        for row in sorted(variant_runs[0].get("equity") or [], key=lambda item: item["trade_date"])
    ]
    dates = [item for item in dates if item is not None]
    if len(dates) < train_days + test_days:
        return {
            "status": "insufficient_data",
            "method": "rolling_train_select_then_test",
            "folds": [],
            "diagnostics": [],
            "limitations": [f"交易日不足，至少需要 {train_days + test_days} 个交易日。"],
        }

    folds = []
    max_start = len(dates) - train_days - test_days
    for fold_index, start_index in enumerate(range(0, max_start + 1, step_days), start=1):
        train_start = dates[start_index]
        train_end = dates[start_index + train_days - 1]
        test_start = train_end
        test_end = dates[start_index + train_days + test_days - 1]
        ranked = []
        for variant in variant_runs:
            train_summary = _variant_period_summary(
                f"fold_{fold_index}_train",
                "训练窗口",
                variant,
                train_start,
                train_end,
                benchmark_curve,
            )
            test_summary = _variant_period_summary(
                f"fold_{fold_index}_test",
                "测试窗口",
                variant,
                test_start,
                test_end,
                benchmark_curve,
                exclude_start_trade_date=True,
            )
            if train_summary and test_summary:
                ranked.append((variant, train_summary, test_summary))
        if not ranked:
            continue
        selected, train_summary, test_summary = max(
            ranked,
            key=lambda item: (
                float(item[1].get("return_pct") or -1e9),
                float(item[1].get("excess_return_pct") or -1e9),
                -abs(float(item[1].get("max_drawdown_pct") or 0)),
            ),
        )
        params: BacktestParams = selected["params"]
        folds.append(
            {
                "id": f"fold_{fold_index}",
                "train_start_date": train_start.isoformat(),
                "train_end_date": train_end.isoformat(),
                "test_start_date": test_start.isoformat(),
                "test_end_date": test_end.isoformat(),
                "train_days": train_summary["days"],
                "test_days": test_summary["days"],
                "selected_variant_id": selected["variant_id"],
                "min_entry_score": params.min_entry_score,
                "stop_loss_pct": params.stop_loss_pct,
                "take_profit_pct": params.take_profit_pct,
                "strict_entry": params.strict_entry,
                "train_return_pct": train_summary["return_pct"],
                "train_excess_return_pct": train_summary.get("excess_return_pct"),
                "train_max_drawdown_pct": train_summary["max_drawdown_pct"],
                "train_trade_count": train_summary["trade_count"],
                "test_return_pct": test_summary["return_pct"],
                "test_benchmark_return_pct": test_summary.get("benchmark_return_pct"),
                "test_excess_return_pct": test_summary.get("excess_return_pct"),
                "test_max_drawdown_pct": test_summary["max_drawdown_pct"],
                "test_trade_count": test_summary["trade_count"],
                "test_win_rate": test_summary["win_rate"],
                "test_pnl": test_summary["pnl"],
            }
        )

    summary = _walk_forward_summary(folds)
    return {
        "status": "ready" if folds else "empty",
        "method": "rolling_train_select_then_test",
        "train_days": train_days,
        "test_days": test_days,
        "step_days": step_days,
        "folds": folds,
        "summary": summary,
        "diagnostics": _walk_forward_diagnostics(summary),
        "limitations": [
            "每个折叠只在训练窗口按收益/超额/回撤选择参数，再在后续窗口测试；没有使用未来窗口选择参数。",
            "当前样本只有约数月日线，折叠数量有限，不能代表完整牛熊周期。",
        ],
    }


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
    rows = [
        row for row in variant.get("equity") or []
        if start_date <= _as_date(row.get("trade_date")) <= end_date
    ]
    if len(rows) < 2:
        return None
    return _period_summary(
        period_id,
        label,
        rows,
        variant.get("closed_trades") or [],
        benchmark_curve,
        exclude_start_trade_date=exclude_start_trade_date,
    )


def _walk_forward_summary(folds: list[dict[str, Any]]) -> dict[str, Any]:
    test_returns = _numeric_values(folds, "test_return_pct")
    test_excess = _numeric_values(folds, "test_excess_return_pct")
    selected_counts: dict[int, int] = defaultdict(int)
    for fold in folds:
        selected_counts[int(fold["selected_variant_id"])] += 1
    most_selected_variant_id = None
    if selected_counts:
        most_selected_variant_id = max(selected_counts.items(), key=lambda item: (item[1], -item[0]))[0]
    return {
        "fold_count": len(folds),
        "positive_test_count": len([value for value in test_returns if value > 0]),
        "positive_test_ratio": _ratio_pct(len([value for value in test_returns if value > 0]), len(test_returns)),
        "excess_positive_count": len([value for value in test_excess if value > 0]),
        "excess_positive_ratio": _ratio_pct(len([value for value in test_excess if value > 0]), len(test_excess)),
        "test_return_avg_pct": mean(test_returns) if test_returns else None,
        "test_return_median_pct": _median(test_returns) if test_returns else None,
        "test_return_min_pct": min(test_returns) if test_returns else None,
        "test_return_max_pct": max(test_returns) if test_returns else None,
        "test_excess_avg_pct": mean(test_excess) if test_excess else None,
        "most_selected_variant_id": most_selected_variant_id,
        "selected_variant_counts": dict(sorted(selected_counts.items())),
    }


def _walk_forward_diagnostics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    fold_count = int(summary.get("fold_count") or 0)
    positive_ratio = summary.get("positive_test_ratio")
    excess_ratio = summary.get("excess_positive_ratio")
    excess_avg = summary.get("test_excess_avg_pct")
    return [
        {
            "id": "walk_forward_fold_count",
            "label": "滚动折叠数量",
            "status": "pass" if fold_count >= 3 else "warning",
            "value": fold_count,
            "value_type": "count",
            "message": "折叠数量可用于初步判断" if fold_count >= 3 else "折叠数量不足，只能作烟测。",
        },
        {
            "id": "walk_forward_positive_ratio",
            "label": "测试窗口盈利占比",
            "status": "pass" if positive_ratio is not None and positive_ratio >= 50 else "fail",
            "value": positive_ratio,
            "value_type": "pct",
            "message": "多数未来测试窗口为正收益" if positive_ratio is not None and positive_ratio >= 50 else "未来测试窗口盈利稳定性不足。",
        },
        {
            "id": "walk_forward_excess_ratio",
            "label": "测试窗口超额占比",
            "status": "pass" if excess_ratio is not None and excess_ratio >= 50 else "fail",
            "value": excess_ratio,
            "value_type": "pct",
            "message": "多数未来测试窗口跑赢样本等权" if excess_ratio is not None and excess_ratio >= 50 else "多数未来测试窗口未跑赢样本等权。",
        },
        {
            "id": "walk_forward_avg_excess",
            "label": "测试窗口平均超额",
            "status": "pass" if excess_avg is not None and excess_avg > 0 else "fail",
            "value": excess_avg,
            "value_type": "pct",
            "message": "未来测试窗口平均超额为正" if excess_avg is not None and excess_avg > 0 else "未来测试窗口平均超额为负。",
        },
    ]


def _top_validation_variants(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            float(row.get("out_sample_return_pct") if row.get("out_sample_return_pct") is not None else -1e9),
            float(row.get("total_return_pct") if row.get("total_return_pct") is not None else -1e9),
            -abs(float(row.get("max_drawdown_pct") or 0)),
        ),
        reverse=True,
    )
    return ordered[:limit]


def _numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(key)
        if value is not None:
            values.append(float(value))
    return values


def _rank_for_variant(ordered_rows: list[dict[str, Any]], target: dict[str, Any] | None) -> int | None:
    if not target:
        return None
    target_id = target.get("variant_id")
    for index, row in enumerate(ordered_rows, start=1):
        if row.get("variant_id") == target_id:
            return index
    return None


def _same_grid_params(params: BacktestParams, base_params: BacktestParams) -> bool:
    return (
        abs(params.min_entry_score - base_params.min_entry_score) < 1e-9
        and abs(params.stop_loss_pct - base_params.stop_loss_pct) < 1e-9
        and abs(params.take_profit_pct - base_params.take_profit_pct) < 1e-9
        and params.strict_entry == base_params.strict_entry
    )


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
        intraday_entry=_truthy(raw_params.get("intraday_entry", True)),
        minute_entry_required=_truthy(raw_params.get("minute_entry_required", False)),
        tail_entry_start=str(raw_params.get("tail_entry_start") or "14:30"),
        tail_entry_end=str(raw_params.get("tail_entry_end") or "14:57"),
        tail_entry_ma5_tolerance_pct=float(raw_params.get("tail_entry_ma5_tolerance_pct") or 1.5),
        symbols=[_normalize_symbol(symbol) for symbol in (raw_params.get("symbols") or []) if _normalize_symbol(symbol)],
        included_boards=normalize_included_boards(raw_params.get("included_boards")),
        persist=False,
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _validation_grid_csv_content(grid: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    _write_section(writer, "参数网格摘要")
    writer.writerow(["回测ID", grid["backtest_id"]])
    writer.writerow(["策略", grid["strategy"]])
    writer.writerow(["版本", grid["strategy_version"]])
    writer.writerow(["区间", f"{grid['start_date']} 至 {grid['end_date']}"])
    writer.writerow(["方法", grid["method"]])
    writer.writerow(["组合数量", grid["variant_count"]])
    writer.writerow([])

    _write_dict_rows(writer, "参数空间", [grid.get("param_space") or {}])
    _write_dict_rows(writer, "汇总", [grid.get("summary") or {}])
    _write_dict_rows(writer, "诊断", grid.get("diagnostics") or [])
    walk_forward = grid.get("walk_forward") or {}
    _write_dict_rows(writer, "Walk Forward 汇总", [walk_forward.get("summary") or {}] if walk_forward.get("summary") else [])
    _write_dict_rows(writer, "Walk Forward 诊断", walk_forward.get("diagnostics") or [])
    _write_dict_rows(writer, "Walk Forward 折叠", walk_forward.get("folds") or [])
    _write_dict_rows(writer, "样本外Top组合", grid.get("top_variants") or [])
    _write_dict_rows(writer, "全部参数组合", grid.get("rows") or [])

    _write_section(writer, "限制")
    writer.writerow(["说明"])
    for item in grid.get("limitations") or []:
        writer.writerow([item])

    return "\ufeff" + buffer.getvalue()


def _nav_return_pct(curve: list[dict[str, Any]]) -> float | None:
    if not curve:
        return None
    return (float(curve[-1].get("nav") or 0) - 1) * 100


def _report_csv_content(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    _write_section(writer, "回测摘要")
    writer.writerow(["回测ID", report["backtest_id"]])
    writer.writerow(["策略", report["strategy_id"]])
    writer.writerow(["版本", report["strategy_version"]])
    writer.writerow(["区间", f"{report['start_date']} 至 {report['end_date']}"])
    writer.writerow(["执行模型", report["assumptions"].get("execution")])
    writer.writerow([])

    _write_section(writer, "核心指标")
    writer.writerow(["指标", "数值"])
    for row in report.get("summary_rows") or []:
        writer.writerow([row["label"], row.get("value")])
    writer.writerow([])

    _write_section(writer, "样本覆盖")
    writer.writerow(["字段", "数值"])
    for key, value in (report.get("sample") or {}).items():
        writer.writerow([key, value])
    writer.writerow([])

    _write_dict_rows(writer, "扩展交易指标", [report.get("extended_metrics") or {}])
    execution_quality = report.get("execution_quality") or {}
    _write_dict_rows(
        writer,
        "成交真实性检查",
        [{key: value for key, value in execution_quality.items() if key != "diagnostics"}] if execution_quality else [],
    )
    _write_dict_rows(writer, "成交真实性诊断", execution_quality.get("diagnostics") or [])
    _write_dict_rows(writer, "基准对比", (report.get("benchmark") or {}).get("benchmarks") or [])
    _write_dict_rows(writer, "样本内样本外", (report.get("period_analysis") or {}).get("periods") or [])
    _write_dict_rows(writer, "市场环境分段", (report.get("regime_analysis") or {}).get("periods") or [])
    robustness = report.get("robustness_checks") or {}
    _write_dict_rows(writer, "年度分段", robustness.get("yearly_periods") or [])
    _write_dict_rows(writer, "成本压力测试", robustness.get("cost_stress") or [])
    random_baseline = robustness.get("random_baseline") or {}
    _write_dict_rows(writer, "随机样本基准摘要", [{key: value for key, value in random_baseline.items() if key != "runs"}] if random_baseline else [])
    _write_dict_rows(writer, "随机样本基准明细", random_baseline.get("runs") or [])
    _write_dict_rows(writer, "反过拟合诊断", robustness.get("diagnostics") or [])
    _write_dict_rows(writer, "月度收益", report.get("monthly_returns") or [])
    _write_dict_rows(writer, "个股贡献", report.get("symbol_performance") or [])
    _write_dict_rows(writer, "最差交易", report.get("worst_trades") or [])
    _write_dict_rows(writer, "交易明细", report.get("trades") or [])
    _write_dict_rows(writer, "已闭仓交易", report.get("closed_trades") or [])

    order_stats = report.get("order_stats") or {}
    order_rows = [
        {"type": "status", "name": key, "count": value}
        for key, value in (order_stats.get("by_status") or {}).items()
    ]
    order_rows.extend(
        {"type": "reason", "name": key, "count": value}
        for key, value in (order_stats.get("by_reason") or {}).items()
    )
    _write_dict_rows(writer, "订单统计", order_rows)
    _write_dict_rows(writer, "未成交示例", order_stats.get("rejected_examples") or [])

    data_quality = report.get("data_quality") or {}
    data_quality_rows = [
        {"table": key, "count": value.get("count")}
        for key, value in data_quality.items()
        if isinstance(value, dict)
    ]
    _write_dict_rows(writer, "数据质量", data_quality_rows)

    _write_section(writer, "限制")
    writer.writerow(["说明"])
    for item in [*(data_quality.get("limitations") or []), *(report.get("limitations") or [])]:
        writer.writerow([item])

    return "\ufeff" + buffer.getvalue()


def _minute_gap_csv_content(orders: list[dict[str, Any]]) -> tuple[str, int]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["trade_date", "vt_symbol", "reference_date", "window", "ma5", "minute_bar_count", "missing_reason"])
    gap_count = 0
    seen: set[tuple[str, date]] = set()
    for order in orders:
        trade_date = _as_date(order.get("trade_date"))
        vt_symbol = str(order.get("vt_symbol") or "").strip().upper()
        raw = order.get("raw") or {}
        if not trade_date or not vt_symbol or not isinstance(raw, dict):
            continue
        execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else raw
        if not isinstance(execution, dict) or execution.get("mode") != "minute_tail_ma5_required":
            continue
        key = (vt_symbol, trade_date)
        if key in seen:
            continue
        seen.add(key)
        writer.writerow(
            [
                trade_date.isoformat(),
                vt_symbol,
                execution.get("reference_date") or "",
                execution.get("window") or "",
                execution.get("ma5") if execution.get("ma5") is not None else "",
                execution.get("minute_bar_count") if execution.get("minute_bar_count") is not None else "",
                execution.get("reason") or "tail_entry_not_triggered",
            ]
        )
        gap_count += 1
    return "\ufeff" + buffer.getvalue(), gap_count


def _write_section(writer: csv.writer, title: str) -> None:
    writer.writerow([f"## {title}"])


def _write_dict_rows(writer: csv.writer, title: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    writer.writerow([])
    _write_section(writer, title)
    keys = _ordered_csv_keys(rows)
    writer.writerow(keys)
    for row in rows:
        writer.writerow([_csv_value(row.get(key)) for key in keys])
    writer.writerow([])


def _ordered_csv_keys(rows: list[dict[str, Any]]) -> list[str]:
    keys = []
    for row in rows:
        for key in row:
            if key not in keys and key != "windows":
                keys.append(key)
    return keys


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return str(value)
    return value


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
    result["limitations"] = [
        "stock_fund_flows、stock_hot_ranks、stock_lhb_records 为空时，游资/情绪信号只能使用价格成交量代理。",
        "sector_period_scores 为空时，主线板块评分退化为中性或缺失。",
        "stock_minute_bars 覆盖不足时，尾盘低吸只能对已同步样本做分钟级验证。",
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
        "signal_timing": "每个历史交易日收盘后，只使用当日及以前可见数据重新打分生成候选。",
        "execution_timing": "买入在下一交易日执行；卖出信号在 D 日收盘后确认，只能在 D+1 开盘撮合。",
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
            "intraday_entry": params.intraday_entry,
            "minute_entry_required": params.minute_entry_required,
            "tail_entry_window": f"{params.tail_entry_start}-{params.tail_entry_end}",
            "tail_entry_ma5_tolerance_pct": params.tail_entry_ma5_tolerance_pct,
        },
    }


def _backtest_assumptions(params: BacktestParams) -> dict[str, str]:
    return {
        "candidate_generation": "历史逐日重新打分：D 日收盘后生成 D 日候选，D+1 才能买入。",
        "execution": "Buy: D close signal -> D+1 tail-window minute fill, or D+1 open fallback unless minute_entry_required=true. Sell: D close exit signal -> D+1 open fill.",
        "tail_entry": "uses prior visible daily MA5 and the configured intraday window; no same-day close look-ahead",
        "tail_entry_window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        "minute_entry_required": str(params.minute_entry_required),
        "costs": "commission, stamp tax on sells, and slippage are included",
        "positioning": "equal cash budget per position, 100-share lot rounded",
        "turnover": "turnover_pct uses traded notional divided by initial cash",
        "data_as_of_policy": "daily bars only; financial data requires publish_date",
    }


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


def _persist_run(session, params: BacktestParams, run: dict[str, Any], end: date) -> int:
    metrics = run["metrics"]
    backtest_id = session.execute(
        schema.backtest_runs.insert()
        .values(
            strategy_id=params.strategy,
            strategy_version=STRATEGY_VERSION,
            start_date=params.start,
            end_date=end,
            status="succeeded",
            initial_cash=params.initial_cash,
            final_equity=metrics.get("final_equity"),
            params=_params_to_json(params),
            metrics=metrics,
            finished_at=datetime.now(timezone.utc),
        )
        .returning(schema.backtest_runs.c.id)
    ).scalar_one()
    for item in run["equity"]:
        session.execute(
            schema.backtest_daily_equity.insert().values(
                backtest_id=backtest_id,
                **_table_values(schema.backtest_daily_equity, item),
            )
        )
    for item in run["orders"]:
        session.execute(
            schema.backtest_orders.insert().values(
                backtest_id=backtest_id,
                **_table_values(schema.backtest_orders, item),
            )
        )
    for item in run["trades"]:
        session.execute(
            schema.backtest_trades.insert().values(
                backtest_id=backtest_id,
                **_table_values(schema.backtest_trades, item),
            )
        )
    for key, value in metrics.items():
        if isinstance(value, (int, float)) or value is None:
            session.execute(schema.backtest_metrics.insert().values(backtest_id=backtest_id, metric_key=key, metric_value=value))
        else:
            session.execute(schema.backtest_metrics.insert().values(backtest_id=backtest_id, metric_key=key, metric_text=str(value)))
    return int(backtest_id)


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
        "raw": trade.raw,
    }


def _table_values(table, item: dict[str, Any]) -> dict[str, Any]:
    columns = set(table.c.keys())
    return {
        key: value
        for key, value in _parse_dates(item).items()
        if key in columns and key not in {"id", "backtest_id", "created_at"}
    }


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _parse_dates(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("trade_date", "entry_date", "start_date", "end_date"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = date.fromisoformat(value[:10])
    return result


def _params_to_json(params: BacktestParams) -> dict[str, Any]:
    result = dict(params.__dict__)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        elif isinstance(value, tuple):
            result[key] = list(value)
    return result
