"""Unified strategy replay built from persisted quant signals."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards, stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.backtest import execution_models, scoring, simulation
from alphaagent.server.services.backtest.schemas import BacktestParams, MinuteBar, Position
from alphaagent.server.services.quant import screening_payloads
from alphaagent.server.services.quant.factors import STRATEGY_ID, Bar, SignalScore
from alphaagent.server.services.quant.strategy_registry import get_strategy


DEFAULT_REPLAY_MIN_ENTRY_SCORE = 68.0


def create_replay_run(
    *,
    start: date,
    end: date,
    strategy_id: str = STRATEGY_ID,
    max_symbols: int = 5000,
    min_entry_score: float = DEFAULT_REPLAY_MIN_ENTRY_SCORE,
    strict_entry: bool = True,
    execution_model: str = "legacy_next_open",
    minute_interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    tail_entry_ma5_tolerance_pct: float = 1.5,
    stop_loss_pct: float = 0.08,  # 与 schemas 默认同步(2026-06-24)
    take_profit_pct: float = 0.18,
    trailing_stop_pct: float = 0.08,
    time_stop_days: int = 15,
    included_boards: list[str] | tuple[str, ...] | str | None = None,
) -> dict[str, Any]:
    """Create an auditable replay from already persisted quant signals."""

    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    if start > end:
        return {"status": "invalid_range", "message": "start must be earlier than or equal to end"}
    _ensure_schema()

    params = _params(
        strategy_id=strategy.id,
        start=start,
        end=end,
        max_symbols=max_symbols,
        min_entry_score=min_entry_score,
        strict_entry=strict_entry,
        execution_model=execution_model,
        minute_interval=minute_interval,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        tail_entry_ma5_tolerance_pct=tail_entry_ma5_tolerance_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        time_stop_days=time_stop_days,
        included_boards=included_boards,
    )

    with session_scope() as session:
        signal_rows = _load_signal_rows(session, strategy.id, strategy.version, start, end, params)
        if not signal_rows:
            replay_id = _insert_run(
                session,
                strategy.id,
                strategy.version,
                start,
                end,
                "empty",
                _params_to_json(params),
                {"signal_count": 0, "attempt_count": 0},
                "区间内没有已保存的量化信号，无法生成买卖记录。",
            )
            return {
                "status": "empty",
                "replay_run_id": replay_id,
                "strategy_id": strategy.id,
                "strategy_version": strategy.version,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "message": "区间内没有已保存的量化信号，无法生成买卖记录。",
            }

        vt_symbols = _limited_symbols(signal_rows, params.max_symbols)
        bars_by_symbol = _load_all_bars(session, vt_symbols, _lookback_start(start), end)
        trading_days = _trading_days(bars_by_symbol, start, end)
        if len(trading_days) < 2:
            replay_id = _insert_run(
                session,
                strategy.id,
                strategy.version,
                start,
                end,
                "insufficient_data",
                _params_to_json(params),
                {"signal_count": len(signal_rows), "attempt_count": 0},
                "区间内日线数据不足，无法生成买卖记录。",
            )
            return {
                "status": "insufficient_data",
                "replay_run_id": replay_id,
                "strategy_id": strategy.id,
                "strategy_version": strategy.version,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "message": "区间内日线数据不足，无法生成买卖记录。",
            }

        minute_index = _load_minute_bar_index(session, vt_symbols, start, end, params.minute_interval)
        stock_meta = _load_stock_meta(session, vt_symbols)
        attempts = _replay_attempts(
            signal_rows,
            bars_by_symbol,
            trading_days,
            stock_meta,
            minute_index,
            params,
        )
        metrics = _summary_metrics(attempts)
        replay_id = _insert_run(
            session,
            strategy.id,
            strategy.version,
            start,
            end,
            "ready",
            _params_to_json(params),
            metrics,
            None,
        )
        _insert_attempts(session, replay_id, attempts)

    return {
        "status": "ready",
        "replay_run_id": replay_id,
        "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "metrics": metrics,
    }


def latest_symbol_replay(vt_symbol: str, strategy_id: str = STRATEGY_ID) -> dict[str, Any]:
    symbol = _normalize_symbol(vt_symbol)
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id}
    _ensure_schema()
    with session_scope() as session:
        symbol_run = session.execute(
            select(schema.strategy_replay_runs.c.id)
            .select_from(
                schema.strategy_replay_runs.join(
                    schema.strategy_replay_attempts,
                    schema.strategy_replay_runs.c.id == schema.strategy_replay_attempts.c.replay_run_id,
                )
            )
            .where(
                and_(
                    schema.strategy_replay_runs.c.strategy_id == strategy.id,
                    schema.strategy_replay_runs.c.strategy_version == strategy.version,
                    schema.strategy_replay_attempts.c.vt_symbol == symbol,
                )
            )
            .order_by(desc(schema.strategy_replay_runs.c.id))
            .limit(1)
        ).scalar_one_or_none()
        if symbol_run:
            return symbol_replay(int(symbol_run), symbol)
        run = session.execute(
            select(schema.strategy_replay_runs)
            .where(
                and_(
                    schema.strategy_replay_runs.c.strategy_id == strategy.id,
                    schema.strategy_replay_runs.c.strategy_version == strategy.version,
                )
            )
            .order_by(desc(schema.strategy_replay_runs.c.id))
            .limit(1)
        ).mappings().first()
        if not run:
            return {
                "status": "empty",
                "vt_symbol": symbol,
                "strategy_id": strategy.id,
                "message": "该股暂无全局买卖记录，请先在量化页刷新候选并回测。",
            }
    return symbol_replay(int(run["id"]), symbol)


def symbol_replay(replay_run_id: int, vt_symbol: str) -> dict[str, Any]:
    symbol = _normalize_symbol(vt_symbol)
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_schema()
    with session_scope() as session:
        run = session.execute(
            select(schema.strategy_replay_runs).where(schema.strategy_replay_runs.c.id == replay_run_id)
        ).mappings().first()
        if not run:
            return {"status": "not_found", "replay_run_id": replay_run_id}
        rows = session.execute(
            select(schema.strategy_replay_attempts)
            .where(
                and_(
                    schema.strategy_replay_attempts.c.replay_run_id == replay_run_id,
                    schema.strategy_replay_attempts.c.vt_symbol == symbol,
                )
            )
            .order_by(schema.strategy_replay_attempts.c.signal_date, schema.strategy_replay_attempts.c.side, schema.strategy_replay_attempts.c.id)
        ).mappings().all()
        stock = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol == symbol)).mappings().first()
    attempts = [_mapping_to_api(dict(row)) for row in rows]
    trades = _closed_trades(attempts)
    events = _events_from_attempts(attempts)
    summary = _symbol_summary(attempts, trades)
    return {
        "status": "ready" if attempts else "empty",
        "replay_run_id": replay_run_id,
        "vt_symbol": symbol,
        "name": stock.get("name") if stock else None,
        **stock_board_payload(symbol, stock.get("exchange") if stock else None),
        "strategy_id": run["strategy_id"],
        "strategy_version": run["strategy_version"],
        "start_date": run["start_date"].isoformat() if run.get("start_date") else None,
        "end_date": run["end_date"].isoformat() if run.get("end_date") else None,
        "params": run.get("params") or {},
        "summary": summary,
        "attempts": attempts,
        "events": events,
        "closed_trades": trades,
        "message": None if attempts else "该股在最新全局买卖记录中没有信号或执行记录。",
    }


def list_replay_runs(strategy_id: str = STRATEGY_ID, limit: int = 80) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": [], "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id, "items": []}
    _ensure_schema()
    with session_scope() as session:
        rows = session.execute(
            select(schema.strategy_replay_runs)
            .where(
                and_(
                    schema.strategy_replay_runs.c.strategy_id == strategy.id,
                    schema.strategy_replay_runs.c.strategy_version == strategy.version,
                )
            )
            .order_by(desc(schema.strategy_replay_runs.c.id))
            .limit(min(max(limit, 1), 300))
        ).mappings().all()
    return {"status": "ready" if rows else "empty", "items": [_mapping_to_api(dict(row)) for row in rows]}


def get_replay_run(replay_run_id: int) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    _ensure_schema()
    with session_scope() as session:
        row = session.execute(
            select(schema.strategy_replay_runs).where(schema.strategy_replay_runs.c.id == replay_run_id)
        ).mappings().first()
    if not row:
        return {"status": "not_found", "replay_run_id": replay_run_id}
    return {"status": "ready", "item": _mapping_to_api(dict(row))}


def _replay_attempts(
    signal_rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Bar]],
    trading_days: list[date],
    stock_meta: dict[str, dict[str, Any]],
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    params: BacktestParams,
) -> list[dict[str, Any]]:
    signals_by_date = _signals_by_date(signal_rows, params)
    bar_index = simulation.bar_index_by_symbol(bars_by_symbol)
    positions: dict[str, Position] = {}
    pending_buys: list[dict[str, Any]] = []
    pending_sells: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    for index, current_day in enumerate(trading_days):
        today_bars = {symbol: by_date[current_day] for symbol, by_date in bar_index.items() if current_day in by_date}

        for order in list(pending_sells):
            if order["execute_date"] != current_day:
                continue
            pending_sells.remove(order)
            position = positions.get(order["vt_symbol"])
            if not position:
                continue
            bar = today_bars.get(order["vt_symbol"])
            attempt = _sell_attempt(order, position, current_day, bar, minute_index, params)
            attempts.append(attempt)
            if attempt["execution_status"] == "filled":
                del positions[order["vt_symbol"]]

        for order in list(pending_buys):
            if order["execute_date"] != current_day:
                continue
            pending_buys.remove(order)
            if order["vt_symbol"] in positions:
                continue
            bar = today_bars.get(order["vt_symbol"])
            attempt = _buy_attempt(order, current_day, bar, bar_index, minute_index, params)
            attempts.append(attempt)
            if attempt["execution_status"] != "filled":
                continue
            entry_reason = dict(order.get("evidence") or order.get("reason") or {})
            entry_reason["execution"] = attempt["raw"]
            positions[order["vt_symbol"]] = Position(
                vt_symbol=order["vt_symbol"],
                name=stock_meta.get(order["vt_symbol"], {}).get("name"),
                volume=100,
                cost_price=float(attempt["price"]),
                entry_date=current_day,
                highest_price=bar.high_price if bar else float(attempt["price"]),
                lowest_price=bar.low_price if bar else float(attempt["price"]),
                reason=entry_reason,
            )

        for vt_symbol, position in list(positions.items()):
            bar = today_bars.get(vt_symbol)
            if not bar:
                continue
            position.visible_holding_bars += 1
            position.highest_price = max(position.highest_price, bar.high_price)
            position.lowest_price = min(position.lowest_price if position.lowest_price is not None else bar.low_price, bar.low_price)
            sell_reason = simulation.sell_reason_for_position(position, bar, current_day, params)
            if not sell_reason or current_day <= position.entry_date or index >= len(trading_days) - 1:
                continue
            if any(order["vt_symbol"] == vt_symbol for order in pending_sells):
                continue
            pending_sells.append(
                {
                    "signal_run_id": None,
                    "signal_date": current_day,
                    "execute_date": trading_days[index + 1],
                    "vt_symbol": vt_symbol,
                    "side": "SELL",
                    "signal_type": "exit_signal",
                    "score": None,
                    "reason": sell_reason,
                    "evidence": {"reason": sell_reason, "entry_date": position.entry_date.isoformat()},
                }
            )

        next_day = trading_days[index + 1] if index < len(trading_days) - 1 else None
        for signal in signals_by_date.get(current_day, []):
            if signal["vt_symbol"] in positions:
                attempts.append(_signal_only_attempt(signal, current_day, current_day, "already_holding"))
                continue
            if next_day is None:
                attempts.append(_signal_only_attempt(signal, current_day, current_day, "no_next_trade_date"))
                continue
            pending_buys.append(
                {
                    "signal_run_id": signal.get("run_id"),
                    "signal_date": current_day,
                    "execute_date": next_day,
                    "vt_symbol": signal["vt_symbol"],
                    "side": "BUY",
                    "signal_type": signal.get("signal_type"),
                    "score": signal.get("total_score"),
                    "reason": signal.get("evidence") or {},
                    "evidence": signal.get("evidence") or {},
                }
            )
    return attempts


def _signal_only_attempt(signal: dict[str, Any], signal_date: date, execute_date: date, reason: str) -> dict[str, Any]:
    evidence = signal.get("evidence") or {}
    return {
        "signal_run_id": signal.get("run_id"),
        "signal_date": signal_date,
        "execute_date": execute_date,
        "vt_symbol": signal["vt_symbol"],
        "side": "BUY",
        "signal_type": signal.get("signal_type"),
        "plan_status": "signal_only",
        "execution_status": "signal_only",
        "price": None,
        "price_source": None,
        "proxy_used": False,
        "reject_reason": reason,
        "score": _float_or_none(signal.get("total_score")),
        "raw": {
            "status": "signal_only",
            "reason": reason,
            "signal_date": signal_date.isoformat(),
            "execute_date": execute_date.isoformat(),
            "evidence": evidence,
        },
    }


def _buy_attempt(
    order: dict[str, Any],
    current_day: date,
    bar: Bar | None,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    params: BacktestParams,
) -> dict[str, Any]:
    if not bar:
        fill = {
            "status": "rejected",
            "mode": "no_execute_bar",
            "reason": "no_execute_bar",
            "signal_date": order["signal_date"].isoformat(),
            "execute_date": current_day.isoformat(),
            "price_source": None,
            "proxy_used": False,
        }
        return _attempt_row(order, current_day, "rejected", None, fill)
    if _is_limit_up_open(bar):
        fill = {
            "status": "rejected",
            "mode": "limit_up_open_blocked",
            "reason": "limit_up_open_blocked",
            "signal_date": order["signal_date"].isoformat(),
            "execute_date": current_day.isoformat(),
            "price_source": "stock_daily_bars.open_price",
            "proxy_used": False,
            "open_price": bar.open_price,
            "high_price": bar.high_price,
            "low_price": bar.low_price,
            "close_price": bar.close_price,
            "change_pct": bar.change_pct,
        }
        return _attempt_row(order, current_day, "rejected", None, fill)
    fill = execution_models.resolve_buy_fill(order, current_day, bar, bar_index, minute_index, params)
    status = "filled" if fill.get("status") == "filled" else "rejected"
    price = fill.get("price") if status == "filled" else fill.get("price")
    return _attempt_row(order, current_day, status, price, fill)


def _sell_attempt(
    order: dict[str, Any],
    position: Position,
    current_day: date,
    bar: Bar | None,
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    params: BacktestParams,
) -> dict[str, Any]:
    if not bar:
        fill = {
            "status": "rejected",
            "mode": "no_execute_bar",
            "reason": "no_execute_bar",
            "signal_date": order["signal_date"].isoformat(),
            "execute_date": current_day.isoformat(),
            "price_source": None,
            "proxy_used": False,
        }
        return _attempt_row(order, current_day, "rejected", None, fill)
    fill = execution_models.resolve_tail_sell_fill(
        order["vt_symbol"],
        position,
        current_day,
        bar,
        minute_index,
        params,
        str(order["reason"]),
        order["signal_date"],
    )
    status = "filled" if fill.get("status") == "filled" else "rejected"
    price = fill.get("price") if status == "filled" else fill.get("price")
    return _attempt_row(order, current_day, status, price, fill)


def _attempt_row(
    order: dict[str, Any],
    execute_date: date,
    status: str,
    price: Any,
    fill: dict[str, Any],
) -> dict[str, Any]:
    reason = str(fill.get("reason") or order.get("reason") or "")
    plan_status = "filled" if status == "filled" else "not_triggered"
    raw = {
        **fill,
        "evidence": order.get("evidence") or order.get("reason") or {},
    }
    return {
        "signal_run_id": order.get("signal_run_id"),
        "signal_date": order["signal_date"],
        "execute_date": execute_date,
        "vt_symbol": order["vt_symbol"],
        "side": order["side"],
        "signal_type": order.get("signal_type"),
        "plan_status": plan_status,
        "execution_status": status,
        "price": _float_or_none(price),
        "price_source": fill.get("price_source"),
        "proxy_used": bool(fill.get("proxy_used") or False),
        "reject_reason": None if status == "filled" else reason,
        "score": _float_or_none(order.get("score")),
        "raw": raw,
    }


def _signals_by_date(signal_rows: list[dict[str, Any]], params: BacktestParams) -> dict[date, list[dict[str, Any]]]:
    result: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in signal_rows:
        if not _is_buy_signal(row, params):
            continue
        result[row["trade_date"]].append(row)
    for rows in result.values():
        rows.sort(key=lambda item: (-(float(item.get("total_score") or 0)), str(item.get("vt_symbol") or "")))
    return dict(result)


def _is_buy_signal(row: dict[str, Any], params: BacktestParams) -> bool:
    """Compatibility predicate for tests and callers passing unscreened rows."""

    score = _signal_score_from_row(row)
    return scoring.is_buy_candidate(score, params)


def _closed_trades(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trades: list[dict[str, Any]] = []
    for row in sorted(attempts, key=lambda item: (str(item.get("execute_date") or ""), str(item.get("side") or ""))):
        if row.get("execution_status") != "filled" or row.get("price") is None:
            continue
        side = str(row.get("side") or "").upper()
        symbol = str(row.get("vt_symbol") or "")
        if side == "BUY":
            open_lots[symbol].append(row)
            continue
        if side != "SELL" or not open_lots[symbol]:
            continue
        entry = open_lots[symbol].pop(0)
        entry_price = float(entry["price"])
        exit_price = float(row["price"])
        return_pct = (exit_price / entry_price - 1) * 100 if entry_price else None
        entry_date = _as_date(entry.get("execute_date"))
        exit_date = _as_date(row.get("execute_date"))
        trades.append(
            {
                "vt_symbol": symbol,
                "entry_date": entry.get("execute_date"),
                "exit_date": row.get("execute_date"),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": return_pct,
                "holding_days": (exit_date - entry_date).days if entry_date and exit_date else None,
                "exit_reason": row.get("raw", {}).get("reason") or row.get("reject_reason"),
            }
        )
    return trades


def _events_from_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in attempts:
        if row.get("side") == "BUY":
            events.append(
                {
                    "event_type": "signal",
                    "trade_date": row.get("signal_date"),
                    "signal_date": row.get("signal_date"),
                    "execute_date": row.get("execute_date"),
                    "vt_symbol": row.get("vt_symbol"),
                    "side": "BUY",
                    "status": "signal",
                    "price": None,
                    "score": row.get("score"),
                    "reason": "entry_signal",
                    "raw": row.get("raw") or {},
                }
            )
        events.append(
            {
                "event_type": "execution",
                "trade_date": row.get("execute_date"),
                "signal_date": row.get("signal_date"),
                "execute_date": row.get("execute_date"),
                "vt_symbol": row.get("vt_symbol"),
                "side": row.get("side"),
                "status": row.get("execution_status"),
                "price": row.get("price"),
                "score": row.get("score"),
                "reason": row.get("reject_reason") or (row.get("raw") or {}).get("reason"),
                "price_source": row.get("price_source"),
                "proxy_used": row.get("proxy_used"),
                "raw": row.get("raw") or {},
            }
        )
    return events


def _symbol_summary(attempts: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    buy_attempts = [row for row in attempts if row.get("side") == "BUY"]
    buy_filled = [row for row in buy_attempts if row.get("execution_status") == "filled"]
    rejected = [row for row in attempts if row.get("execution_status") == "rejected"]
    returns = [float(row["return_pct"]) for row in trades if row.get("return_pct") is not None]
    compound = None
    if returns:
        value = 1.0
        for item in returns:
            value *= 1 + item / 100
        compound = (value - 1) * 100
    return {
        "signal_count": len(buy_attempts),
        "buy_filled_count": len(buy_filled),
        "rejected_count": len(rejected),
        "closed_trade_count": len(trades),
        "compound_return_pct": compound,
        "average_return_pct": sum(returns) / len(returns) if returns else None,
        "win_rate_pct": len([item for item in returns if item > 0]) / len(returns) * 100 if returns else None,
        "reject_reasons": _reject_reason_counts(rejected),
        "current_status": _current_status(attempts),
    }


def _summary_metrics(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    rejected = [row for row in attempts if row.get("execution_status") == "rejected"]
    return {
        "attempt_count": len(attempts),
        "buy_attempt_count": len([row for row in attempts if row.get("side") == "BUY"]),
        "sell_attempt_count": len([row for row in attempts if row.get("side") == "SELL"]),
        "filled_count": len([row for row in attempts if row.get("execution_status") == "filled"]),
        "rejected_count": len(rejected),
        "reject_reasons": _reject_reason_counts(rejected),
    }


def _current_status(attempts: list[dict[str, Any]]) -> str:
    filled = [row for row in attempts if row.get("execution_status") == "filled"]
    if not filled:
        return "no_position"
    last = sorted(filled, key=lambda item: str(item.get("execute_date") or ""))[-1]
    return "holding" if last.get("side") == "BUY" else "closed"


def _reject_reason_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        reason = str(row.get("reject_reason") or "unknown")
        counts[reason] += 1
    return [{"reason": reason, "count": count} for reason, count in sorted(counts.items())]


def _load_signal_rows(
    session,
    strategy_id: str,
    strategy_version: str,
    start: date,
    end: date,
    params: BacktestParams,
) -> list[dict[str, Any]]:
    min_score_prefilter = screening_payloads.signal_score_prefilter_threshold(strategy_id, params.min_entry_score)
    filters = [
        schema.quant_stock_signals.c.strategy_id == strategy_id,
        schema.quant_stock_signals.c.strategy_version == strategy_version,
        schema.quant_stock_signals.c.trade_date >= start,
        schema.quant_stock_signals.c.trade_date <= end,
        schema.quant_stock_signals.c.total_score >= min_score_prefilter,
        schema.quant_stock_signals.c.risk_score >= 35,
        schema.quant_stock_signals.c.liquidity_score >= 25,
    ]
    rows = session.execute(
        select(schema.quant_stock_signals)
        .where(and_(*filters))
        .order_by(schema.quant_stock_signals.c.trade_date, desc(schema.quant_stock_signals.c.total_score), schema.quant_stock_signals.c.vt_symbol)
    ).mappings().all()
    return [dict(row) for row in rows]


def _signal_score_from_row(row: dict[str, Any]) -> SignalScore:
    return SignalScore(
        vt_symbol=str(row.get("vt_symbol") or ""),
        trade_date=row["trade_date"],
        signal_type=str(row.get("signal_type") or row.get("strategy_id") or STRATEGY_ID),
        total_score=float(row.get("total_score") or 0),
        relative_strength_score=float(row.get("relative_strength_score") or 0),
        washout_score=float(row.get("washout_score") or 0),
        trend_quality_score=float(row.get("trend_quality_score") or 0),
        sector_mainline_score=float(row.get("sector_mainline_score") or 50),
        financial_improvement_score=float(row.get("financial_improvement_score") or 50),
        liquidity_score=float(row.get("liquidity_score") or 0),
        risk_score=float(row.get("risk_score") or 50),
        entry_signal=bool(row.get("entry_signal")),
        risk_level=str(row.get("risk_level") or "MEDIUM"),
        evidence=dict(row.get("evidence") or {}),
    )


def _limited_symbols(signal_rows: list[dict[str, Any]], max_symbols: int) -> list[str]:
    ranked = sorted(
        {
            str(row["vt_symbol"]): max(float(row.get("total_score") or 0), 0)
            for row in signal_rows
        }.items(),
        key=lambda item: (-item[1], item[0]),
    )
    return [symbol for symbol, _score in ranked[: min(max(max_symbols, 1), 5000)]]


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


def _load_stock_meta(session, vt_symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not vt_symbols:
        return {}
    rows = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol.in_(vt_symbols))).mappings().all()
    return {str(row["vt_symbol"]): dict(row) for row in rows}


def _trading_days(bars_by_symbol: dict[str, list[Bar]], start: date, end: date) -> list[date]:
    days = {bar.trade_date for bars in bars_by_symbol.values() for bar in bars if start <= bar.trade_date <= end}
    return sorted(days)


def _insert_run(
    session,
    strategy_id: str,
    strategy_version: str,
    start: date,
    end: date,
    status: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    message: str | None,
) -> int:
    return int(
        session.execute(
            schema.strategy_replay_runs.insert()
            .values(
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                start_date=start,
                end_date=end,
                status=status,
                params=params,
                metrics=metrics,
                message=message,
                finished_at=func.now(),
            )
            .returning(schema.strategy_replay_runs.c.id)
        ).scalar_one()
    )


def _insert_attempts(session, replay_id: int, attempts: list[dict[str, Any]]) -> None:
    if not attempts:
        return
    rows = [{"replay_run_id": replay_id, **attempt} for attempt in attempts]
    session.execute(schema.strategy_replay_attempts.insert(), rows)


def _params(
    *,
    strategy_id: str,
    start: date,
    end: date,
    max_symbols: int,
    min_entry_score: float,
    strict_entry: bool,
    execution_model: str,
    minute_interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
    tail_entry_ma5_tolerance_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_stop_pct: float,
    time_stop_days: int,
    included_boards: list[str] | tuple[str, ...] | str | None,
) -> BacktestParams:
    uses_minute_execution = execution_model in {"tail_close_hybrid", "strict_1430"}
    return BacktestParams(
        strategy=strategy_id,
        start=start,
        end=end,
        initial_cash=1.0,
        max_positions=5000,
        max_position_pct=1.0,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        time_stop_days=time_stop_days,
        candidate_limit=5000,
        max_symbols=max_symbols,
        min_entry_score=min_entry_score,
        strict_entry=strict_entry,
        execution_model=execution_model,
        intraday_entry=uses_minute_execution,
        minute_entry_required=execution_model == "strict_1430",
        minute_interval=minute_interval,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        tail_entry_ma5_tolerance_pct=tail_entry_ma5_tolerance_pct,
        persist=False,
        included_boards=normalize_included_boards(included_boards or DEFAULT_QUANT_INCLUDED_BOARDS),
    )


def _params_to_json(params: BacktestParams) -> dict[str, Any]:
    payload = {
        "strategy": params.strategy,
        "start": params.start.isoformat(),
        "end": params.end.isoformat() if params.end else None,
        "max_symbols": params.max_symbols,
        "min_entry_score": params.min_entry_score,
        "strict_entry": params.strict_entry,
        "execution_model": params.execution_model,
        "intraday_entry": params.intraday_entry,
        "minute_entry_required": params.minute_entry_required,
        "stop_loss_pct": params.stop_loss_pct,
        "take_profit_pct": params.take_profit_pct,
        "trailing_stop_pct": params.trailing_stop_pct,
        "time_stop_days": params.time_stop_days,
        "enable_signal_rotation": params.enable_signal_rotation,
        "rotation_min_score": params.rotation_min_score,
        "rotation_min_score_gap": params.rotation_min_score_gap,
        "rotation_max_holding_return_pct": params.rotation_max_holding_return_pct,
        "rotation_min_holding_days": params.rotation_min_holding_days,
        "require_low_suction_launch_confirmation": params.require_low_suction_launch_confirmation,
        "exclude_repeated_dragon_pullback": params.exclude_repeated_dragon_pullback,
        "require_low_suction_launch_for_low_suction_context": params.require_low_suction_launch_for_low_suction_context,
        "require_balanced_low_suction_launch_quality": params.require_balanced_low_suction_launch_quality,
        "enable_entry_launch_quality_score": params.enable_entry_launch_quality_score,
        "enable_entry_launch_risk_penalty": params.enable_entry_launch_risk_penalty,
        "enable_low_suction_market_risk_penalty": params.enable_low_suction_market_risk_penalty,
        "enable_market_adaptive_setup_weighting": params.enable_market_adaptive_setup_weighting,
        "enable_low_suction_first_lift_bonus": params.enable_low_suction_first_lift_bonus,
        "enable_low_suction_lifecycle_ranking": params.enable_low_suction_lifecycle_ranking,
        "enable_low_suction_buildup_quality_lane": params.enable_low_suction_buildup_quality_lane,
        "enable_candidate_tail_risk_penalty": params.enable_candidate_tail_risk_penalty,
        "enable_mainline_momentum_lane": params.enable_mainline_momentum_lane,
        "enable_mainline_momentum_risk_control": params.enable_mainline_momentum_risk_control,
        "enable_mainline_momentum_hard_filter": params.enable_mainline_momentum_hard_filter,
        "enable_surge_quality_lane": params.enable_surge_quality_lane,
        "enable_top20_day_quality_gate": params.enable_top20_day_quality_gate,
        "enable_weekly_top_fractal_relief": params.enable_weekly_top_fractal_relief,
        "enable_pure_loss_weak_bucket_penalty": params.enable_pure_loss_weak_bucket_penalty,
        "enable_selective_setup_quality_lane": params.enable_selective_setup_quality_lane,
        "enable_high_risk_d2_follow_through_entry": params.enable_high_risk_d2_follow_through_entry,
        "enable_dynamic_failed_launch_exit_stop": params.enable_dynamic_failed_launch_exit_stop,
        "enable_dynamic_failed_launch_replacement_quality_gate": params.enable_dynamic_failed_launch_replacement_quality_gate,
        "enable_failed_launch_exit_stop": params.enable_failed_launch_exit_stop,
        "enable_contextual_failed_launch_exit_stop": params.enable_contextual_failed_launch_exit_stop,
        "enable_mid_profit_giveback_stop": params.enable_mid_profit_giveback_stop,
        "mid_profit_giveback_min_high_gain_pct": params.mid_profit_giveback_min_high_gain_pct,
        "mid_profit_giveback_max_current_gain_pct": params.mid_profit_giveback_max_current_gain_pct,
        "mid_profit_giveback_drawdown_pct": params.mid_profit_giveback_drawdown_pct,
        "enable_contextual_support_reclaim_delay": params.enable_contextual_support_reclaim_delay,
        "support_reclaim_delay_max_warning_level": params.support_reclaim_delay_max_warning_level,
        "support_reclaim_delay_max_replacement_score_gap": params.support_reclaim_delay_max_replacement_score_gap,
        "support_reclaim_delay_min_sell_day_range_pct": params.support_reclaim_delay_min_sell_day_range_pct,
        "enable_contextual_peak_giveback_stop": params.enable_contextual_peak_giveback_stop,
        "peak_giveback_min_high_gain_pct": params.peak_giveback_min_high_gain_pct,
        "peak_giveback_max_current_gain_pct": params.peak_giveback_max_current_gain_pct,
        "peak_giveback_drawdown_pct": params.peak_giveback_drawdown_pct,
        "peak_giveback_min_holding_days": params.peak_giveback_min_holding_days,
        "enable_low_suction_false_launch_watch_gate": params.enable_low_suction_false_launch_watch_gate,
        "low_suction_false_launch_min_days": params.low_suction_false_launch_min_days,
        "low_suction_false_launch_min_warning_level": params.low_suction_false_launch_min_warning_level,
        "low_suction_false_launch_max_recovery_level": params.low_suction_false_launch_max_recovery_level,
        "enable_missed_candidate_quality_rotation": params.enable_missed_candidate_quality_rotation,
        "missed_rotation_min_score": params.missed_rotation_min_score,
        "missed_rotation_min_score_gap": params.missed_rotation_min_score_gap,
        "missed_rotation_max_held_return_pct": params.missed_rotation_max_held_return_pct,
        "missed_rotation_min_held_days": params.missed_rotation_min_held_days,
        "enable_high_quality_trend_rotation": params.enable_high_quality_trend_rotation,
        "high_quality_rotation_min_score": params.high_quality_rotation_min_score,
        "high_quality_rotation_max_rank": params.high_quality_rotation_max_rank,
        "high_quality_rotation_min_score_gap": params.high_quality_rotation_min_score_gap,
        "high_quality_rotation_max_held_return_pct": params.high_quality_rotation_max_held_return_pct,
        "high_quality_rotation_min_held_days": params.high_quality_rotation_min_held_days,
        "enable_weak_holding_quality_rotation": params.enable_weak_holding_quality_rotation,
        "weak_holding_rotation_min_score": params.weak_holding_rotation_min_score,
        "weak_holding_rotation_max_rank": params.weak_holding_rotation_max_rank,
        "weak_holding_rotation_min_score_gap": params.weak_holding_rotation_min_score_gap,
        "weak_holding_rotation_max_held_return_pct": params.weak_holding_rotation_max_held_return_pct,
        "weak_holding_rotation_min_held_days": params.weak_holding_rotation_min_held_days,
        "weak_holding_rotation_max_ma_convergence_pct": params.weak_holding_rotation_max_ma_convergence_pct,
        "weak_holding_rotation_min_low_suction_days": params.weak_holding_rotation_min_low_suction_days,
        "enable_protected_weak_holding_rotation": params.enable_protected_weak_holding_rotation,
        "enable_low_suction_pullback_entry": params.enable_low_suction_pullback_entry,
        "low_suction_pullback_entry_max_wait_days": params.low_suction_pullback_entry_max_wait_days,
        "low_suction_pullback_entry_buffer_pct": params.low_suction_pullback_entry_buffer_pct,
        "low_suction_pullback_entry_reserve_slot": params.low_suction_pullback_entry_reserve_slot,
        "enable_low_suction_trigger_day_confirmation": params.enable_low_suction_trigger_day_confirmation,
        "enable_low_suction_confirmed_branch_exit": params.enable_low_suction_confirmed_branch_exit,
        "low_suction_failed_follow_d3_low_pct": params.low_suction_failed_follow_d3_low_pct,
        "low_suction_failed_follow_d3_high_pct": params.low_suction_failed_follow_d3_high_pct,
        "low_suction_failed_follow_d3_close_pct": params.low_suction_failed_follow_d3_close_pct,
        "low_suction_opened_space_d5_high_pct": params.low_suction_opened_space_d5_high_pct,
        "low_suction_opened_space_d5_low_pct": params.low_suction_opened_space_d5_low_pct,
        "enable_low_suction_branch_replacement_quality_gate": params.enable_low_suction_branch_replacement_quality_gate,
        "low_suction_branch_replacement_gate_wait_days": params.low_suction_branch_replacement_gate_wait_days,
        "low_suction_branch_replacement_min_score": params.low_suction_branch_replacement_min_score,
        "low_suction_branch_replacement_max_market_warning_level": params.low_suction_branch_replacement_max_market_warning_level,
        "low_suction_branch_replacement_max_low_suction_ma_convergence_pct": params.low_suction_branch_replacement_max_low_suction_ma_convergence_pct,
        "low_suction_branch_replacement_max_dragon_ma_convergence_pct": params.low_suction_branch_replacement_max_dragon_ma_convergence_pct,
        "enable_low_suction_branch_replacement_strict_setup_gate": params.enable_low_suction_branch_replacement_strict_setup_gate,
        "setup_family_filter": params.setup_family_filter,
        "enable_phase_aware_setup_selector": params.enable_phase_aware_setup_selector,
        "enable_phase_replacement_quality": params.enable_phase_replacement_quality,
        "reuse_signal_cache": params.reuse_signal_cache,
        "exclude_from_product_baseline": params.exclude_from_product_baseline,
        "included_boards": list(params.included_boards),
    }
    if params.execution_model in {"tail_close_hybrid", "strict_1430"}:
        payload.update(
            {
                "minute_interval": params.minute_interval,
                "tail_entry_start": params.tail_entry_start,
                "tail_entry_end": params.tail_entry_end,
                "tail_entry_ma5_tolerance_pct": params.tail_entry_ma5_tolerance_pct,
            }
        )
    return payload


def _is_limit_up_open(bar: Bar) -> bool:
    return bool(bar.change_pct is not None and bar.change_pct >= 9.8 and bar.open_price >= bar.close_price * 0.995)


def _lookback_start(start: date) -> date:
    return start - timedelta(days=320)


def _ensure_schema() -> None:
    schema.ensure_schema_once(get_engine())


def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
