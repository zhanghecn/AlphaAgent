"""Portfolio simulation state machine for AlphaAgent backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from alphaagent.server.services.backtest import ledger, scoring
from alphaagent.server.services.backtest.schemas import BacktestParams, MinuteBar, Position, ScoreContext, Trade
from alphaagent.server.services.quant.factors import Bar, DRAGON_PULLBACK_STRATEGY_ID, evaluate_exit


@dataclass(frozen=True)
class SimulationCallbacks:
    load_minute_bar_index: Callable[[Any, list[str], date, date, str], dict[str, dict[date, list[MinuteBar]]]]
    score_day: Callable[[Any, dict[str, list[Bar]], date, BacktestParams, dict[date, list[Any]] | None, ScoreContext | None], list[Any]]
    resolve_buy_fill: Callable[[dict[str, Any], date, Bar, dict[str, dict[date, Bar]], dict[str, dict[date, list[MinuteBar]]], BacktestParams], dict[str, Any]]
    resolve_tail_sell_fill: Callable[[str, Position, date, Bar, dict[str, dict[date, list[MinuteBar]]], BacktestParams, str, date | None], dict[str, Any]]
    is_limit_up_open: Callable[[Bar], bool]
    is_limit_down_open: Callable[[Bar], bool]
    metrics: Callable[[float, list[dict[str, Any]], list[Trade]], dict[str, Any]]
    order: Callable[[date, str, str, float | None, int | None, str, str, dict[str, Any] | None], dict[str, Any]]
    trade_to_api: Callable[[Trade], dict[str, Any]]
    mapping_to_api: Callable[[dict[str, Any]], dict[str, Any]]


def simulate_portfolio(
    session,
    params: BacktestParams,
    bars_by_symbol: dict[str, list[Bar]],
    trading_days: list[date],
    stock_meta: dict[str, dict[str, Any]],
    callbacks: SimulationCallbacks,
    score_cache: dict[date, list[Any]] | None = None,
    minute_index: dict[str, dict[date, list[MinuteBar]]] | None = None,
    score_context: ScoreContext | None = None,
) -> dict[str, Any]:
    cash = params.initial_cash
    positions: dict[str, Position] = {}
    pending_buys: list[dict[str, Any]] = []
    pending_sells: list[dict[str, Any]] = []
    theoretical_positions: dict[str, Position] = {}
    trades: list[Trade] = []
    orders: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    position_snapshots: list[dict[str, Any]] = []
    signal_events: list[dict[str, Any]] = []
    bar_index = bar_index_by_symbol(bars_by_symbol)
    if params.intraday_entry:
        minute_index = (
            minute_index
            if minute_index is not None
            else callbacks.load_minute_bar_index(
                session,
                list(bars_by_symbol),
                trading_days[0],
                trading_days[-1],
                params.minute_interval,
            )
        )
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
            if not bar:
                raw = pending_sell_raw(order, position, current_day, "no_bar")
                orders.append(callbacks.order(current_day, order["vt_symbol"], "SELL", None, position.volume, "rejected", "no_bar", raw))
                continue

            if params.execution_model in {"tail_close_hybrid", "strict_1430"}:
                fill = callbacks.resolve_tail_sell_fill(
                    order["vt_symbol"],
                    position,
                    current_day,
                    bar,
                    minute_index,
                    params,
                    order["reason"],
                    order["signal_date"],
                )
                if fill.get("status") != "filled":
                    orders.append(
                        callbacks.order(
                            current_day,
                            order["vt_symbol"],
                            "SELL",
                            fill.get("price"),
                            position.volume,
                            "rejected",
                            str(fill.get("reason") or order["reason"]),
                            fill,
                        )
                    )
                    continue
                sell_raw_price = float(fill["price"])
                raw = fill
            else:
                raw = {
                    "mode": "daily_next_open_sell",
                    "signal_date": order["signal_date"].isoformat(),
                    "execute_date": current_day.isoformat(),
                    "entry_date": position.entry_date.isoformat(),
                    "reason": order["reason"],
                    "price_source": "stock_daily_bars.open_price",
                    "proxy_used": False,
                }
                raw.update(order.get("raw") or {})
                if callbacks.is_limit_down_open(bar):
                    orders.append(callbacks.order(current_day, order["vt_symbol"], "SELL", None, position.volume, "rejected", "limit_down", raw))
                    continue
                sell_raw_price = bar.open_price

            sell_execution = ledger.calculate_sell_execution(
                raw_price=sell_raw_price,
                volume=position.volume,
                cost_price=position.cost_price,
                commission_rate=params.commission_rate,
                stamp_tax_rate=params.stamp_tax_rate,
                slippage_bps=params.slippage_bps,
            )
            fill_price = sell_execution.price
            amount = sell_execution.amount
            fee = sell_execution.fee
            pnl = sell_execution.pnl
            cash += sell_execution.cash_delta
            del positions[order["vt_symbol"]]
            orders.append(callbacks.order(current_day, order["vt_symbol"], "SELL", fill_price, position.volume, "filled", order["reason"], raw))
            trades.append(Trade(current_day, order["vt_symbol"], "SELL", fill_price, position.volume, amount, fee, pnl, order["reason"], raw))

        for order in list(pending_buys):
            if order["execute_date"] != current_day:
                continue
            pending_buys.remove(order)
            if order["vt_symbol"] in positions:
                continue
            if len(positions) >= params.max_positions:
                orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", None, None, "rejected", "position_slot_unavailable", None))
                continue
            bar = today_bars.get(order["vt_symbol"])
            if not bar:
                raw = {
                    "status": "rejected",
                    "mode": "no_execute_bar",
                    "reason": "no_execute_bar",
                    "signal_date": order["signal_date"].isoformat(),
                    "execute_date": current_day.isoformat(),
                    "price_source": None,
                    "proxy_used": False,
                }
                orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", None, None, "rejected", "no_execute_bar", raw))
                continue
            if callbacks.is_limit_up_open(bar):
                raw = {
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
                orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", None, 0, "rejected", "limit_up_open_blocked", raw))
                continue
            fill = callbacks.resolve_buy_fill(order, current_day, bar, bar_index, minute_index, params)
            if fill.get("status") != "filled":
                orders.append(
                    callbacks.order(
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
            buy_execution = ledger.calculate_buy_execution(
                raw_price=float(fill["price"]),
                cash=cash,
                target_cash=params.initial_cash * params.max_position_pct,
                commission_rate=params.commission_rate,
                slippage_bps=params.slippage_bps,
            )
            fill_price = buy_execution.price
            volume = buy_execution.volume
            if volume <= 0:
                orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", fill_price, 0, "rejected", "insufficient_cash", fill))
                continue
            amount = buy_execution.amount
            fee = buy_execution.fee
            cash = buy_execution.cash_after
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
            orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", fill_price, volume, "filled", "entry_signal", fill))
            trades.append(Trade(current_day, order["vt_symbol"], "BUY", fill_price, volume, amount, fee, None, "entry_signal", entry_reason))

        pending_sell_symbols = {str(order["vt_symbol"]) for order in pending_sells}
        for vt_symbol, position in list(positions.items()):
            if vt_symbol in pending_sell_symbols:
                continue
            bar = today_bars.get(vt_symbol)
            if not bar:
                continue
            position.highest_price = max(position.highest_price, bar.high_price)
            sell_reason = sell_reason_for_position(position, bar, current_day, params)
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
            orders.append(callbacks.order(current_day, vt_symbol, "SELL", None, position.volume, "pending", sell_reason, raw))

        if index < len(trading_days) - 1:
            next_day = trading_days[index + 1]
            daily_candidates = None
            reserved_exit_count = len({str(order["vt_symbol"]) for order in pending_sells})
            free_slots = max(params.max_positions - len(positions) + reserved_exit_count - len(pending_buys), 0)
            should_score_for_rotation = params.enable_signal_rotation and params.strategy == DRAGON_PULLBACK_STRATEGY_ID
            if free_slots > 0 or should_score_for_rotation:
                if score_cache is not None and current_day not in score_cache and session is None:
                    daily_candidates = []
                else:
                    daily_candidates = callbacks.score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
            schedule_entry_plans(
                current_day,
                next_day,
                daily_candidates or [],
                positions,
                pending_buys,
                pending_sells,
                today_bars,
                params,
            )
            if not params.symbols:
                if daily_candidates is None:
                    if score_cache is not None and current_day in score_cache:
                        daily_candidates = callbacks.score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
                    elif session is not None:
                        daily_candidates = callbacks.score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
                    else:
                        daily_candidates = []
                signal_events.extend(
                    signal_events_for_day(
                        current_day,
                        next_day,
                        daily_candidates or [],
                        theoretical_positions,
                        today_bars,
                        bar_index,
                        minute_index,
                        stock_meta,
                        params,
                        callbacks,
                    )
                )

        current_market_value = market_value(positions, today_bars)
        total_equity = cash + current_market_value
        equity_curve.append(
            {
                "trade_date": current_day,
                "cash": cash,
                "market_value": current_market_value,
                "total_equity": total_equity,
                "position_count": len(positions),
            }
        )
        position_snapshots.extend(position_snapshot_rows(current_day, positions, today_bars, total_equity))

    metrics = callbacks.metrics(params.initial_cash, equity_curve, trades)
    return {
        "metrics": metrics,
        "equity": [callbacks.mapping_to_api(item) for item in equity_curve],
        "positions": [callbacks.mapping_to_api(item) for item in position_snapshots],
        "signal_events": [callbacks.mapping_to_api(item) for item in signal_events],
        "trades": [callbacks.trade_to_api(trade) for trade in trades],
        "orders": [callbacks.mapping_to_api(item) for item in orders],
    }


def schedule_entry_plans(
    signal_date: date,
    execute_date: date,
    candidates: list[Any],
    positions: dict[str, Position],
    pending_buys: list[dict[str, Any]],
    pending_sells: list[dict[str, Any]],
    today_bars: dict[str, Bar],
    params: BacktestParams,
) -> None:
    pending_buy_symbols = {str(order["vt_symbol"]) for order in pending_buys}
    pending_sell_symbols = {str(order["vt_symbol"]) for order in pending_sells}

    for candidate in candidates[: params.candidate_limit]:
        vt_symbol = str(candidate.vt_symbol)
        if vt_symbol in positions or vt_symbol in pending_buy_symbols:
            continue
        reserved_exit_count = len({str(order["vt_symbol"]) for order in pending_sells})
        free_slots = max(params.max_positions - len(positions) + reserved_exit_count - len(pending_buys), 0)
        if free_slots <= 0:
            replacement = rotation_replacement_for_candidate(candidate, positions, pending_sell_symbols, today_bars, params, signal_date)
            if replacement is None:
                continue
            pending_sells.append(
                {
                    "execute_date": execute_date,
                    "signal_date": signal_date,
                    "vt_symbol": replacement.vt_symbol,
                    "reason": "rotation_for_stronger_signal",
                    "raw": rotation_sell_raw(candidate, replacement, signal_date, execute_date, today_bars.get(replacement.vt_symbol)),
                }
            )
            pending_sell_symbols.add(replacement.vt_symbol)

        pending_buys.append(
            {
                "execute_date": execute_date,
                "signal_date": signal_date,
                "vt_symbol": vt_symbol,
                "reason": candidate_entry_reason(candidate),
            }
        )
        pending_buy_symbols.add(vt_symbol)


def rotation_replacement_for_candidate(
    candidate: Any,
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None = None,
) -> Position | None:
    if not allow_signal_rotation(candidate, params):
        return None

    candidate_score = float(getattr(candidate, "total_score", 0) or 0)
    replacement_rows: list[tuple[float, float, Position]] = []
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < params.rotation_min_holding_days:
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        holding_return_pct = position_return_pct(position, bar)
        if holding_return_pct > params.rotation_max_holding_return_pct:
            continue
        entry_score = entry_score_for_position(position)
        if candidate_score < entry_score:
            continue
        replacement_rows.append((holding_return_pct, entry_score, position))
    if not replacement_rows:
        return None
    replacement_rows.sort(key=lambda item: (item[0], item[1], item[2].entry_date, item[2].vt_symbol))
    return replacement_rows[0][2]


def allow_signal_rotation(candidate: Any, params: BacktestParams) -> bool:
    if params.strategy != DRAGON_PULLBACK_STRATEGY_ID or not params.enable_signal_rotation:
        return False
    if not bool(getattr(candidate, "entry_signal", False)):
        return False
    if float(getattr(candidate, "total_score", 0) or 0) < params.rotation_min_score:
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    if evidence.get("dragon_state") != "TAIL_BUY_READY":
        return False
    if evidence.get("fresh_tail_buy") is False:
        return False
    return True


def rotation_sell_raw(
    candidate: Any,
    replacement: Position,
    signal_date: date,
    execute_date: date,
    bar: Bar | None,
) -> dict[str, Any]:
    holding_return_pct = position_return_pct(replacement, bar) if bar else None
    return {
        "mode": "rotation_for_stronger_signal",
        "signal_date": signal_date.isoformat(),
        "execute_date": execute_date.isoformat(),
        "entry_date": replacement.entry_date.isoformat(),
        "reason": "rotation_for_stronger_signal",
        "replacement_symbol": str(candidate.vt_symbol),
        "replacement_score": float(getattr(candidate, "total_score", 0) or 0),
        "replaced_entry_score": entry_score_for_position(replacement),
        "holding_return_pct": holding_return_pct,
    }


def entry_score_for_position(position: Position) -> float:
    reason = position.reason if isinstance(position.reason, dict) else {}
    for key in ("entry_total_score", "total_score", "score"):
        value = _float_or_none(reason.get(key))
        if value is not None:
            return value
    return 0.0


def position_return_pct(position: Position, bar: Bar) -> float:
    if not position.cost_price:
        return 0.0
    return (bar.close_price / position.cost_price - 1) * 100


def candidate_entry_reason(candidate: Any) -> dict[str, Any]:
    evidence = dict(getattr(candidate, "evidence", {}) or {})
    evidence.setdefault("entry_total_score", float(getattr(candidate, "total_score", 0) or 0))
    evidence.setdefault("entry_signal_type", str(getattr(candidate, "signal_type", "") or ""))
    return evidence


def signal_events_for_day(
    signal_date: date,
    execute_date: date,
    scores: list[Any],
    theoretical_positions: dict[str, Position],
    today_bars: dict[str, Bar],
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBar]]],
    stock_meta: dict[str, dict[str, Any]],
    params: BacktestParams,
    callbacks: SimulationCallbacks,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vt_symbol, position in list(theoretical_positions.items()):
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        position.highest_price = max(position.highest_price, bar.high_price)
        sell_reason = sell_reason_for_position(position, bar, signal_date, params)
        if not sell_reason or signal_date <= position.entry_date:
            continue
        execute_bar = bar_index.get(vt_symbol, {}).get(execute_date)
        if not execute_bar:
            continue
        if params.execution_model in {"tail_close_hybrid", "strict_1430"}:
            sell_fill = callbacks.resolve_tail_sell_fill(
                vt_symbol,
                position,
                execute_date,
                execute_bar,
                minute_index,
                params,
                sell_reason,
                signal_date,
            )
            event_execute_date = execute_date
            sell_price = sell_fill.get("price") if sell_fill.get("status") == "filled" else None
            sell_raw = sell_fill
        else:
            event_execute_date = execute_date
            sell_price = execute_bar.open_price
            sell_raw = {
                "status": "filled",
                "mode": "daily_next_open",
                "entry_date": position.entry_date.isoformat(),
                "signal_date": signal_date.isoformat(),
                "execute_date": execute_date.isoformat(),
                "price_source": "stock_daily_bars.open_price",
                "proxy_used": False,
                "reason": sell_reason,
            }
        if sell_raw.get("status") == "filled":
            del theoretical_positions[vt_symbol]
        rows.append(
            {
                "trade_date": event_execute_date,
                "signal_date": signal_date,
                "execute_date": event_execute_date,
                "vt_symbol": vt_symbol,
                "side": "SELL",
                "price": sell_price,
                "score": None,
                "reason": sell_reason,
                "raw": sell_raw,
            }
        )

    for score in scores:
        if not scoring.is_buy_candidate(score, params):
            continue
        if score.vt_symbol in theoretical_positions:
            continue
        execute_bar = bar_index.get(score.vt_symbol, {}).get(execute_date)
        if not execute_bar:
            continue
        buy_fill = callbacks.resolve_buy_fill(
            {"vt_symbol": score.vt_symbol, "signal_date": signal_date, "reason": score.evidence},
            execute_date,
            execute_bar,
            bar_index,
            minute_index,
            params,
        )
        buy_price = buy_fill.get("price") if buy_fill.get("status") == "filled" else None
        buy_raw = {
            **buy_fill,
            "entry_signal": bool(score.entry_signal),
            "evidence": score.evidence,
        }
        rows.append(
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": score.vt_symbol,
                "side": "BUY",
                "price": buy_price,
                "score": score.total_score,
                "reason": "entry_signal",
                "raw": buy_raw,
            }
        )
        if buy_fill.get("status") != "filled":
            continue
        theoretical_positions[score.vt_symbol] = Position(
            vt_symbol=score.vt_symbol,
            name=stock_meta.get(score.vt_symbol, {}).get("name"),
            volume=100,
            cost_price=float(buy_price),
            entry_date=execute_date,
            highest_price=execute_bar.high_price,
            reason={**score.evidence, "execution": buy_fill},
        )
    rows.sort(key=lambda item: (item["trade_date"], item["vt_symbol"], 0 if item["side"] == "BUY" else 1))
    return rows


def sell_reason_for_position(position: Position, bar: Bar, current_day: date, params: BacktestParams) -> str | None:
    if params.strategy == DRAGON_PULLBACK_STRATEGY_ID:
        return dragon_pullback_sell_reason(position, bar, current_day, params)
    # Backtest derives absolute exit levels from params coefficients and the
    # position's cost/highest; realtime holdings instead read the stored price
    # levels directly. Both paths share factors.evaluate_exit as the single
    # source of truth for the exit priority and thresholds.
    return evaluate_exit(
        last_price=bar.close_price,
        stop_loss_price=position.cost_price * (1 - params.stop_loss_pct),
        take_profit_price=position.cost_price * (1 + params.take_profit_pct),
        trailing_stop_price=position.highest_price * (1 - params.trailing_stop_pct),
        entry_date=position.entry_date,
        current_day=current_day,
        time_stop_days=params.time_stop_days,
    )


def dragon_pullback_sell_reason(position: Position, bar: Bar, current_day: date, params: BacktestParams) -> str | None:
    """Trend-oriented exit for the dragon pullback strategy."""

    cost_price = position.cost_price
    if bar.close_price <= cost_price * (1 - params.stop_loss_pct):
        return "support_stop"

    reason = position.reason if isinstance(position.reason, dict) else {}
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    entry_support = _float_or_none(reason.get("support_price"))
    support_stop = entry_support * 0.965 if entry_support else None
    if support_stop is not None and bar.close_price <= support_stop:
        return "support_stop"
    if ma20 is not None and bar.close_price < ma20 * 0.97 and current_day > position.entry_date:
        return "trend_break"

    gain = bar.close_price / cost_price - 1 if cost_price else 0
    drawdown_from_high = bar.close_price / position.highest_price - 1 if position.highest_price else 0
    if gain >= 0.30 and drawdown_from_high <= -0.10:
        return "trend_trailing_stop"
    if gain >= 0.18 and drawdown_from_high <= -0.12:
        return "trend_trailing_stop"
    if ma10 is not None and gain > 0.08 and bar.close_price < ma10 * 0.98:
        return "trend_break"
    if (current_day - position.entry_date).days >= params.time_stop_days * 2 and gain < 0.04:
        return "time_efficiency_stop"
    return None


def bar_index_by_symbol(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, dict[date, Bar]]:
    return {symbol: {bar.trade_date: bar for bar in bars} for symbol, bars in bars_by_symbol.items()}


def market_value(positions: dict[str, Position], today_bars: dict[str, Bar]) -> float:
    value = 0.0
    for vt_symbol, position in positions.items():
        bar = today_bars.get(vt_symbol)
        if bar:
            value += bar.close_price * position.volume
        else:
            value += position.cost_price * position.volume
    return value


def position_snapshot_rows(
    trade_date: date,
    positions: dict[str, Position],
    today_bars: dict[str, Bar],
    total_equity: float,
) -> list[dict[str, Any]]:
    rows = []
    for vt_symbol, position in sorted(positions.items()):
        bar = today_bars.get(vt_symbol)
        close_price = bar.close_price if bar else position.cost_price
        current_market_value = close_price * position.volume
        cost_amount = position.cost_price * position.volume
        floating_pnl = current_market_value - cost_amount
        rows.append(
            {
                "trade_date": trade_date,
                "vt_symbol": vt_symbol,
                "name": position.name,
                "volume": position.volume,
                "cost_price": position.cost_price,
                "close_price": close_price,
                "market_value": current_market_value,
                "floating_pnl": floating_pnl,
                "floating_pnl_pct": floating_pnl / cost_amount * 100 if cost_amount else None,
                "weight_pct": current_market_value / total_equity * 100 if total_equity else None,
                "entry_date": position.entry_date,
                "holding_days": (trade_date - position.entry_date).days,
                "highest_price": position.highest_price,
                "raw": position.reason,
            }
        )
    return rows


def pending_sell_raw(order: dict[str, Any], position: Position, current_day: date, mode: str) -> dict[str, Any]:
    signal_date = _as_date(order.get("signal_date"))
    return {
        "mode": mode,
        "signal_date": signal_date.isoformat() if signal_date else None,
        "execute_date": current_day.isoformat(),
        "entry_date": position.entry_date.isoformat(),
        "reason": order.get("reason"),
        "price_source": None,
        "proxy_used": False,
    }


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
