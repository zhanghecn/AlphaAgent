"""Portfolio simulation state machine for AlphaAgent backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from alphaagent.server.services.backtest import ledger, scoring
from alphaagent.server.services.backtest.schemas import BacktestParams, MinuteBar, Position, ScoreContext, Trade
from alphaagent.server.services.quant import candidate_lanes
from alphaagent.server.services.quant.factors import Bar, DRAGON_PULLBACK_STRATEGY_ID, evaluate_exit

STEALTH_LOW_SUCTION_ROTATION_MIN_SCORE = 90.0
STEALTH_LOW_SUCTION_ROTATION_MIN_HOLDING_DAYS = 5
STEALTH_LOW_SUCTION_ROTATION_MAX_HOLDING_RETURN_PCT = -1.0
STEALTH_LOW_SUCTION_ROTATION_MAX_PORTFOLIO_DRAWDOWN_PCT = -8.0


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
        daily_candidates = None

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
            order_raw = dict(entry_reason)
            order_raw.update(fill)
            positions[order["vt_symbol"]] = Position(
                vt_symbol=order["vt_symbol"],
                name=stock_meta.get(order["vt_symbol"], {}).get("name"),
                volume=volume,
                cost_price=fill_price,
                entry_date=current_day,
                highest_price=bar.high_price,
                reason=entry_reason,
                last_price=bar.close_price,
            )
            orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", fill_price, volume, "filled", "entry_signal", order_raw))
            trades.append(Trade(current_day, order["vt_symbol"], "BUY", fill_price, volume, amount, fee, None, "entry_signal", entry_reason))

        current_buy_signal_symbols: set[str] = set()
        if params.enable_failed_launch_exit_stop and index < len(trading_days) - 1:
            if score_cache is not None and current_day not in score_cache and session is None:
                daily_candidates = []
            else:
                daily_candidates = callbacks.score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
            current_buy_signal_symbols = {
                str(candidate.vt_symbol)
                for candidate in daily_candidates or []
                if bool(getattr(candidate, "entry_signal", False))
            }

        pending_sell_symbols = {str(order["vt_symbol"]) for order in pending_sells}
        for vt_symbol, position in list(positions.items()):
            if vt_symbol in pending_sell_symbols:
                continue
            bar = today_bars.get(vt_symbol)
            if not bar:
                continue
            position.visible_holding_bars += 1
            position.last_price = bar.close_price
            position.highest_price = max(position.highest_price, bar.high_price)
            sell_reason = sell_reason_for_position(
                position,
                bar,
                current_day,
                params,
                current_buy_signal=vt_symbol in current_buy_signal_symbols,
            )
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
    pool_context = candidate_lanes.execution_pool_context(candidates, params.candidate_limit, params.strategy)

    for candidate in execution_candidate_pool(candidates, params):
        vt_symbol = str(candidate.vt_symbol)
        if vt_symbol in positions or vt_symbol in pending_buy_symbols:
            continue
        reserved_exit_count = len({str(order["vt_symbol"]) for order in pending_sells})
        free_slots = max(params.max_positions - len(positions) + reserved_exit_count - len(pending_buys), 0)
        if free_slots <= 0:
            replacement = rotation_replacement_for_candidate(candidate, positions, pending_sell_symbols, today_bars, params, signal_date)
            if replacement is None:
                continue
            rotation_reason = rotation_reason_for_candidate(candidate)
            pending_sells.append(
                {
                    "execute_date": execute_date,
                    "signal_date": signal_date,
                    "vt_symbol": replacement.vt_symbol,
                    "reason": rotation_reason,
                    "raw": rotation_sell_raw(candidate, replacement, signal_date, execute_date, today_bars.get(replacement.vt_symbol), rotation_reason),
                }
            )
            pending_sell_symbols.add(replacement.vt_symbol)

        pending_buys.append(
            {
                "execute_date": execute_date,
                "signal_date": signal_date,
                "vt_symbol": vt_symbol,
                "reason": candidate_entry_reason(candidate, pool_context.get(vt_symbol)),
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
    if is_stealth_low_suction_rotation_candidate(candidate):
        if portfolio_drawdown_pct(positions, today_bars, params.initial_cash) > STEALTH_LOW_SUCTION_ROTATION_MAX_PORTFOLIO_DRAWDOWN_PCT:
            return None
        return low_efficiency_replacement_for_stealth_low_suction(
            positions,
            pending_sell_symbols,
            today_bars,
            params,
            signal_date,
        )

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
        if candidate_score < entry_score + params.rotation_min_score_gap:
            continue
        replacement_rows.append((holding_return_pct, entry_score, position))
    if not replacement_rows:
        return None
    replacement_rows.sort(key=lambda item: (item[0], item[1], item[2].entry_date, item[2].vt_symbol))
    return replacement_rows[0][2]


def execution_candidate_pool(candidates: list[Any], params: BacktestParams) -> list[Any]:
    return candidate_lanes.select_dragon_pullback_execution_pool(candidates, params.candidate_limit, params.strategy)


def allow_signal_rotation(candidate: Any, params: BacktestParams) -> bool:
    if params.strategy != DRAGON_PULLBACK_STRATEGY_ID or not params.enable_signal_rotation:
        return False
    if not bool(getattr(candidate, "entry_signal", False)):
        return False
    if is_stealth_low_suction_rotation_candidate(candidate):
        return True
    if float(getattr(candidate, "total_score", 0) or 0) < params.rotation_min_score:
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    if evidence.get("dragon_state") != "TAIL_BUY_READY":
        return False
    if evidence.get("fresh_tail_buy") is False:
        return False
    return True


def low_efficiency_replacement_for_stealth_low_suction(
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None,
) -> Position | None:
    replacement_rows: list[tuple[float, int, float, Position]] = []
    min_holding_days = max(params.rotation_min_holding_days, STEALTH_LOW_SUCTION_ROTATION_MIN_HOLDING_DAYS)
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < min_holding_days:
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        holding_return_pct = position_return_pct(position, bar)
        if holding_return_pct > STEALTH_LOW_SUCTION_ROTATION_MAX_HOLDING_RETURN_PCT:
            continue
        holding_days = (signal_date - position.entry_date).days if signal_date else 0
        replacement_rows.append((holding_return_pct, -holding_days, entry_score_for_position(position), position))
    if not replacement_rows:
        return None
    replacement_rows.sort(key=lambda item: (item[0], item[1], item[2], item[3].vt_symbol))
    return replacement_rows[0][3]


def is_stealth_low_suction_rotation_candidate(candidate: Any) -> bool:
    if not bool(getattr(candidate, "entry_signal", False)):
        return False
    if float(getattr(candidate, "total_score", 0) or 0) < STEALTH_LOW_SUCTION_ROTATION_MIN_SCORE:
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if setup != "stealth_low_suction":
        return False
    if _float_or_none(evidence.get("low_suction_days")) is None or float(evidence.get("low_suction_days") or 0) < 3:
        return False
    if float(evidence.get("low_suction_buildup_score") or 0) < 95:
        return False
    if float(evidence.get("stealth_low_suction_score") or 0) < 95:
        return False
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    if ma_convergence is None or ma_convergence > 4.0:
        return False
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    if volume_ratio is None or not (0.55 <= volume_ratio <= 1.45):
        return False
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    if ma20_distance is None or ma20_distance < -2.5:
        return False
    hard_failures = {
        "distribution_risk",
        "weak_rebound_ma5_below_ma10",
        "ma20_broken",
        "pullback_too_deep",
        "liquidity_score",
        "risk_score",
        "overheat",
    }
    failures = {str(rule) for rule in (evidence.get("failed_rules") or [])}
    risk_flags = {str(flag) for flag in (evidence.get("risk_flags") or [])}
    return not (failures & hard_failures or risk_flags & hard_failures)


def stealth_low_suction_rotation_key(candidate: Any) -> tuple[float, float, float, float, str]:
    evidence = getattr(candidate, "evidence", {}) or {}
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    return (
        -float(evidence.get("stealth_low_suction_score") or 0),
        -float(evidence.get("low_suction_buildup_score") or 0),
        -float(evidence.get("low_suction_days") or 0),
        ma_convergence if ma_convergence is not None else 999.0,
        str(getattr(candidate, "vt_symbol", "")),
    )


def rotation_sell_raw(
    candidate: Any,
    replacement: Position,
    signal_date: date,
    execute_date: date,
    bar: Bar | None,
    reason: str = "rotation_for_stronger_signal",
) -> dict[str, Any]:
    holding_return_pct = position_return_pct(replacement, bar) if bar else None
    return {
        "mode": reason,
        "signal_date": signal_date.isoformat(),
        "execute_date": execute_date.isoformat(),
        "entry_date": replacement.entry_date.isoformat(),
        "reason": reason,
        "replacement_symbol": str(candidate.vt_symbol),
        "replacement_score": float(getattr(candidate, "total_score", 0) or 0),
        "replaced_entry_score": entry_score_for_position(replacement),
        "holding_return_pct": holding_return_pct,
    }


def rotation_reason_for_candidate(candidate: Any) -> str:
    if is_stealth_low_suction_rotation_candidate(candidate):
        return "rotation_for_stealth_low_suction"
    return "rotation_for_stronger_signal"


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


def portfolio_drawdown_pct(positions: dict[str, Position], today_bars: dict[str, Bar], initial_cash: float) -> float:
    if not initial_cash:
        return 0.0
    total_cost = sum(position.cost_price * position.volume for position in positions.values())
    cash_proxy = max(float(initial_cash) - total_cost, 0.0)
    equity = cash_proxy + market_value(positions, today_bars)
    return (equity / float(initial_cash) - 1) * 100


def candidate_entry_reason(candidate: Any, execution_context: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = dict(getattr(candidate, "evidence", {}) or {})
    evidence.setdefault("entry_total_score", float(getattr(candidate, "total_score", 0) or 0))
    evidence.setdefault("entry_signal_type", str(getattr(candidate, "signal_type", "") or ""))
    if execution_context:
        evidence["candidate_execution"] = dict(execution_context)
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
    pool_context = candidate_lanes.execution_pool_context(scores, params.candidate_limit, params.strategy)
    current_buy_signal_symbols = {str(score.vt_symbol) for score in scores if bool(getattr(score, "entry_signal", False))}
    for vt_symbol, position in list(theoretical_positions.items()):
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        position.visible_holding_bars += 1
        position.highest_price = max(position.highest_price, bar.high_price)
        sell_reason = sell_reason_for_position(
            position,
            bar,
            signal_date,
            params,
            current_buy_signal=vt_symbol in current_buy_signal_symbols,
        )
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
            "candidate_execution": pool_context.get(str(score.vt_symbol)),
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
            last_price=execute_bar.close_price,
        )
    rows.sort(key=lambda item: (item["trade_date"], item["vt_symbol"], 0 if item["side"] == "BUY" else 1))
    return rows


def sell_reason_for_position(
    position: Position,
    bar: Bar,
    current_day: date,
    params: BacktestParams,
    *,
    current_buy_signal: bool = False,
) -> str | None:
    if params.strategy == DRAGON_PULLBACK_STRATEGY_ID:
        return dragon_pullback_sell_reason(position, bar, current_day, params, current_buy_signal=current_buy_signal)
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


def dragon_pullback_sell_reason(
    position: Position,
    bar: Bar,
    current_day: date,
    params: BacktestParams,
    *,
    current_buy_signal: bool = False,
) -> str | None:
    """Trend-oriented exit for the dragon pullback strategy."""

    cost_price = position.cost_price
    if bar.close_price <= cost_price * (1 - params.stop_loss_pct):
        return "support_stop"

    reason = position.reason if isinstance(position.reason, dict) else {}
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    entry_support = _float_or_none(reason.get("support_price"))
    max_drawdown_60d = _float_or_none(reason.get("max_drawdown_60d"))
    fragile_entry = max_drawdown_60d is not None and max_drawdown_60d <= -25.0
    gain = bar.close_price / cost_price - 1 if cost_price else 0
    support_stop = entry_support * 0.965 if entry_support else None
    hold_context = dragon_pullback_hold_context(position, bar)
    hold_soft_exit = (
        hold_context["low_base_accumulation"]
        or (hold_context["ma_support_pullback"] and hold_context["price_volume_sync"])
        or current_buy_signal
    )
    if fragile_entry and gain < 0.04:
        if bar.close_price <= cost_price * 0.95:
            return "fragile_structure_stop"
        if entry_support is not None and bar.close_price <= entry_support * 0.98:
            return "fragile_structure_stop"
    if support_stop is not None and bar.close_price <= support_stop:
        return "support_stop"
    if ma20 is not None and bar.close_price < ma20 * 0.97 and current_day > position.entry_date:
        return "trend_break"

    drawdown_from_high = bar.close_price / position.highest_price - 1 if position.highest_price else 0
    high_gain = position.highest_price / cost_price - 1 if cost_price and position.highest_price else 0
    if (
        params.enable_failed_launch_exit_stop
        and failed_launch_exit_stop_applies(position, bar, gain, high_gain, hold_soft_exit)
    ):
        return "failed_launch_exit_stop"
    if (
        params.enable_mid_profit_giveback_stop
        and str(reason.get("entry_setup") or reason.get("setup_type") or "") == "dragon_pullback"
        and not hold_soft_exit
        and high_gain >= params.mid_profit_giveback_min_high_gain_pct
        and gain <= params.mid_profit_giveback_max_current_gain_pct
        and drawdown_from_high <= -params.mid_profit_giveback_drawdown_pct
    ):
        return "mid_profit_giveback_stop"
    if high_gain >= 0.25 and gain <= 0.12 and drawdown_from_high <= -0.12:
        return "profit_protection_stop"
    if high_gain >= 0.18 and gain <= 0.08 and drawdown_from_high <= -0.10:
        return "profit_protection_stop"
    if gain >= 0.30 and drawdown_from_high <= -0.10:
        return "trend_trailing_stop"
    if gain >= 0.18 and drawdown_from_high <= -0.12:
        return "trend_trailing_stop"
    if ma10 is not None and gain > 0.08 and bar.close_price < ma10 * 0.98:
        if hold_soft_exit and ma20 is not None and bar.close_price >= ma20 * 0.99:
            return None
        return "trend_break"
    if (current_day - position.entry_date).days >= params.time_stop_days * 2 and gain < 0.04:
        if hold_soft_exit:
            return None
        return "time_efficiency_stop"
    return None


def failed_launch_exit_stop_applies(
    position: Position,
    bar: Bar,
    gain: float,
    high_gain: float,
    hold_soft_exit: bool,
) -> bool:
    if position.visible_holding_bars < 3 or hold_soft_exit:
        return False
    reason = position.reason if isinstance(position.reason, dict) else {}
    setup = str(reason.get("entry_setup") or reason.get("setup_type") or "")
    if setup not in {"dragon_pullback", "stealth_low_suction"}:
        return False
    if high_gain >= 0.025:
        return False

    entry_support = _float_or_none(reason.get("support_price"))
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    weak_close = gain <= -0.025
    failed_support_reclaim = bool(entry_support is not None and bar.close_price < entry_support * 0.99)
    failed_ma_reclaim = bool(
        ma10 is not None
        and ma20 is not None
        and bar.close_price < min(ma10, ma20) * 0.995
    )
    return weak_close and (failed_support_reclaim or failed_ma_reclaim)


def dragon_pullback_hold_context(position: Position, bar: Bar) -> dict[str, bool]:
    reason = position.reason if isinstance(position.reason, dict) else {}
    low_base_days = int(reason.get("low_base_days") or 0)
    price_location = _float_or_none(reason.get("price_location_60d_pct"))
    base_volatility = _float_or_none(reason.get("base_volatility_20d_pct"))
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    latest_change = _float_or_none(reason.get("latest_change_pct"))
    volume_ratio = _float_or_none(reason.get("volume_ratio_5d_20d"))
    return {
        "low_base_accumulation": bool(
            low_base_days >= 30
            and price_location is not None
            and price_location <= 35
            and base_volatility is not None
            and base_volatility <= 8
            and ma20 is not None
            and bar.close_price >= ma20 * 0.98
        ),
        "ma_support_pullback": bool(
            ma10 is not None
            and ma20 is not None
            and bar.low_price <= ma10 * 1.02
            and bar.close_price >= ma20 * 0.99
        ),
        "price_volume_sync": bool(
            latest_change is not None
            and latest_change >= 0
            and volume_ratio is not None
            and 0.9 <= volume_ratio <= 1.8
        ),
    }


def bar_index_by_symbol(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, dict[date, Bar]]:
    return {symbol: {bar.trade_date: bar for bar in bars} for symbol, bars in bars_by_symbol.items()}


def market_value(positions: dict[str, Position], today_bars: dict[str, Bar]) -> float:
    value = 0.0
    for vt_symbol, position in positions.items():
        bar = today_bars.get(vt_symbol)
        if bar:
            value += bar.close_price * position.volume
            position.last_price = bar.close_price
        else:
            fallback_price = position.last_price if position.last_price is not None else position.cost_price
            value += fallback_price * position.volume
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
        if bar:
            close_price = bar.close_price
            position.last_price = close_price
        else:
            close_price = position.last_price if position.last_price is not None else position.cost_price
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
