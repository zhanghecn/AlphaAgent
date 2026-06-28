"""Portfolio simulation state machine for AlphaAgent backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from alphaagent.server.services.backtest import ledger, scoring
from alphaagent.server.services.backtest.schemas import BacktestParams, MinuteBar, Position, ScoreContext, Trade
from alphaagent.server.services.quant import candidate_lanes
from alphaagent.server.services.quant.factors import Bar, DRAGON_PULLBACK_STRATEGY_ID, evaluate_exit
from alphaagent.server.services.quant.low_suction_quality import low_suction_launch_quality_bucket

STEALTH_LOW_SUCTION_ROTATION_MIN_SCORE = 90.0
STEALTH_LOW_SUCTION_ROTATION_MIN_HOLDING_DAYS = 5
STEALTH_LOW_SUCTION_ROTATION_MAX_HOLDING_RETURN_PCT = -1.0
STEALTH_LOW_SUCTION_ROTATION_MAX_PORTFOLIO_DRAWDOWN_PCT = -8.0
LOW_SUCTION_PULLBACK_ENTRY_BUCKETS = {"balanced_first_lift", "late_pullback_launch"}
LOW_SUCTION_CONFIRMED_ENTRY_MODE = "low_suction_trigger_day_confirmed_next_open"
DYNAMIC_FAILED_LAUNCH_EXIT_STOP = "dynamic_failed_launch_exit_stop"
LOW_SUCTION_FAILED_FOLLOW_BRANCH_STOP = "low_suction_failed_follow_branch_stop"
LOW_SUCTION_OPENED_SPACE_GIVEBACK_STOP = "low_suction_opened_space_giveback_stop"
WEAK_HOLDING_QUALITY_ROTATION_REASON = "rotation_for_weak_holding_quality_candidate"
PROTECTED_WEAK_HOLDING_ROTATION_REASON = "rotation_for_protected_weak_holding_candidate"
PROTECTED_WEAK_HOLDING_UPTREND_REPAIR_BUFFER_PCT = 3.0
PROTECTED_WEAK_HOLDING_TREND_BUFFER_PCT = 2.0
PROTECTED_WEAK_HOLDING_UPTREND_REGIMES = {"strong_broad", "narrow_mainline_bull", "mainline_pullback"}
HIGH_QUALITY_ROTATION_HARD_FAILURES = {
    "distribution_risk",
    "high_level_sideways_distribution_risk",
    "volume_stall_risk",
    "weak_rebound_ma5_below_ma10",
    "ma20_broken",
    "pullback_too_deep",
    "liquidity_score",
    "risk_score",
    "overheat",
}


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
    pending_pullback_buys: list[dict[str, Any]] = []
    pending_sells: list[dict[str, Any]] = []
    pending_reclaim_checks: dict[str, dict[str, Any]] = {}
    branch_replacement_gates: list[dict[str, Any]] = []
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
        age_low_suction_branch_replacement_gates(branch_replacement_gates, current_day)

        for order in list(pending_pullback_buys):
            if order["execute_date"] != current_day:
                continue
            decision = low_suction_pullback_entry_decision(order, current_day, bar=today_bars.get(order["vt_symbol"]))
            if decision["status"] == "waiting":
                if index < len(trading_days) - 1:
                    order["execute_date"] = trading_days[index + 1]
                    continue
                decision = {**decision, "status": "expired", "reason": "no_more_trading_days"}
            pending_pullback_buys.remove(order)
            if decision["status"] == "expired":
                orders.append(
                    callbacks.order(
                        current_day,
                        order["vt_symbol"],
                        "BUY",
                        None,
                        0,
                        "rejected",
                        "low_suction_pullback_entry_expired",
                        decision,
                    )
                )
                continue
            if decision["status"] == "filled":
                if params.enable_low_suction_trigger_day_confirmation:
                    confirmation = low_suction_trigger_day_confirmation(order, decision, today_bars.get(order["vt_symbol"]))
                    if not confirmation["confirmed"]:
                        orders.append(
                            callbacks.order(
                                current_day,
                                order["vt_symbol"],
                                "BUY",
                                None,
                                0,
                                "rejected",
                                "low_suction_trigger_day_confirmation_failed",
                                confirmation,
                            )
                        )
                        continue
                    if index >= len(trading_days) - 1:
                        raw = {**confirmation, "status": "expired", "reason": "no_next_execute_day"}
                        orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", None, 0, "rejected", "no_next_execute_day", raw))
                        continue
                    order["execute_date"] = trading_days[index + 1]
                    order["trigger_day_confirmation"] = confirmation
                    order.pop("entry_execution_mode", None)
                    pending_buys.append(order)
                else:
                    order["execute_date"] = current_day
                    order["pullback_entry_prechecked_fill"] = decision
                    pending_buys.insert(0, order)

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
                if weak_holding_rotation_sell_invalid_at_execute(order, position, bar, params):
                    raw.update(weak_holding_rotation_cancel_raw(position, bar, params, order))
                    orders.append(
                        callbacks.order(
                            current_day,
                            order["vt_symbol"],
                            "SELL",
                            None,
                            position.volume,
                            "cancelled",
                            str(order.get("reason") or WEAK_HOLDING_QUALITY_ROTATION_REASON),
                            raw,
                        )
                    )
                    continue
                raw.update(weak_holding_rotation_execute_raw(order, position, bar, params))
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
            replacement_gate = replacement_quality_gate_from_sell(order, current_day, params)
            if replacement_gate:
                branch_replacement_gates.append(replacement_gate)
            orders.append(callbacks.order(current_day, order["vt_symbol"], "SELL", fill_price, position.volume, "filled", order["reason"], raw))
            trades.append(Trade(current_day, order["vt_symbol"], "SELL", fill_price, position.volume, amount, fee, pnl, order["reason"], raw))

        for order in list(pending_buys):
            if order["execute_date"] != current_day:
                continue
            pullback_decision = order.pop("pullback_entry_prechecked_fill", None) or low_suction_pullback_entry_decision(
                order,
                current_day,
                bar=today_bars.get(order["vt_symbol"]),
            )
            if pullback_decision["status"] == "waiting":
                if index < len(trading_days) - 1:
                    order["execute_date"] = trading_days[index + 1]
                    continue
                pullback_decision = {**pullback_decision, "status": "expired", "reason": "no_more_trading_days"}
            if pullback_decision["status"] == "waiting":
                continue
            pending_buys.remove(order)
            if pullback_decision["status"] == "expired":
                raw = dict(pullback_decision)
                orders.append(
                    callbacks.order(
                        current_day,
                        order["vt_symbol"],
                        "BUY",
                        None,
                        0,
                        "rejected",
                        "low_suction_pullback_entry_expired",
                        raw,
                    )
                )
                continue
            if order["vt_symbol"] in positions:
                continue
            if len(positions) >= params.max_positions:
                orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", None, None, "rejected", "position_slot_unavailable", None))
                continue
            gate_decision = low_suction_branch_replacement_gate_decision(
                order,
                positions,
                branch_replacement_gates,
                current_day,
                params,
            )
            if gate_decision.get("status") == "rejected":
                orders.append(
                    callbacks.order(
                        current_day,
                        order["vt_symbol"],
                        "BUY",
                        None,
                        0,
                        "rejected",
                        str(gate_decision.get("mode") or "low_suction_branch_replacement_quality_gate"),
                        gate_decision,
                    )
                )
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
            if pullback_decision["status"] == "filled":
                fill = dict(fill)
                fill.update(pullback_decision)
                fill["status"] = "filled"
            if order.get("trigger_day_confirmation"):
                fill = dict(fill)
                fill.update(
                    {
                        "mode": "low_suction_trigger_day_confirmed_next_open",
                        "trigger_day_confirmation": order["trigger_day_confirmation"],
                        "trigger_signal_date": _iso_date(order.get("signal_date")),
                        "price_source": "stock_daily_bars.open_price",
                        "proxy_used": False,
                    }
                )
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
            if gate_decision.get("status") == "accepted" and gate_decision.get("gate_id") is not None:
                consume_low_suction_branch_replacement_gate(branch_replacement_gates, str(gate_decision["gate_id"]))
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
                lowest_price=bar.low_price,
                reason=entry_reason,
                last_price=bar.close_price,
            )
            orders.append(callbacks.order(current_day, order["vt_symbol"], "BUY", fill_price, volume, "filled", "entry_signal", order_raw))
            trades.append(Trade(current_day, order["vt_symbol"], "BUY", fill_price, volume, amount, fee, None, "entry_signal", entry_reason))

        for vt_symbol, check in list(pending_reclaim_checks.items()):
            if check["check_date"] != current_day:
                continue
            pending_reclaim_checks.pop(vt_symbol, None)
            position = positions.get(vt_symbol)
            if not position:
                continue
            bar = today_bars.get(vt_symbol)
            if not bar:
                continue
            if support_reclaim_delay_recovered(position, bar, params):
                raw = {
                    "mode": "contextual_support_reclaim_delay_recovered",
                    "signal_date": check["signal_date"].isoformat(),
                    "check_date": current_day.isoformat(),
                    "entry_date": position.entry_date.isoformat(),
                    "reason": "contextual_support_reclaim_delay_recovered",
                    "original_reason": check["reason"],
                    "not_used_for_signal_score": True,
                }
                orders.append(
                    callbacks.order(
                        current_day,
                        vt_symbol,
                        "SELL",
                        None,
                        position.volume,
                        "cancelled",
                        "contextual_support_reclaim_delay_recovered",
                        raw,
                    )
                )
                continue
            if index >= len(trading_days) - 1:
                continue
            next_day = trading_days[index + 1]
            raw = {
                "mode": "contextual_support_reclaim_delay_failed",
                "signal_date": current_day.isoformat(),
                "execute_date": next_day.isoformat(),
                "entry_date": position.entry_date.isoformat(),
                "reason": check["reason"],
                "delayed_from_signal_date": check["signal_date"].isoformat(),
                "not_used_for_signal_score": True,
            }
            pending_sells.append(
                {
                    "execute_date": next_day,
                    "signal_date": current_day,
                    "vt_symbol": vt_symbol,
                    "reason": check["reason"],
                    "raw": raw,
                }
            )
            orders.append(callbacks.order(current_day, vt_symbol, "SELL", None, position.volume, "pending", check["reason"], raw))

        current_buy_signal_symbols: set[str] = set()
        should_load_exit_candidates = (
            params.enable_dynamic_failed_launch_exit_stop
            or params.enable_failed_launch_exit_stop
            or contextual_failed_launch_exit_needs_replacement_lookup(positions, today_bars, params)
            or (params.enable_contextual_support_reclaim_delay and bool(positions))
        )
        if should_load_exit_candidates and index < len(trading_days) - 1:
            if params.enable_dynamic_failed_launch_exit_stop or params.enable_failed_launch_exit_stop:
                if score_cache is not None and current_day not in score_cache and session is None:
                    daily_candidates = []
                else:
                    daily_candidates = callbacks.score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
            elif score_cache is not None and current_day in score_cache:
                daily_candidates = callbacks.score_day(session, bars_by_symbol, current_day, params, score_cache, score_context)
            else:
                daily_candidates = []
            current_buy_signal_symbols = {
                str(candidate.vt_symbol)
                for candidate in daily_candidates or []
                if bool(getattr(candidate, "entry_signal", False))
            }

        pending_sell_symbols = {str(order["vt_symbol"]) for order in pending_sells}
        pending_buy_symbols = {str(order["vt_symbol"]) for order in pending_buys}
        for vt_symbol, position in list(positions.items()):
            if vt_symbol in pending_sell_symbols:
                continue
            bar = today_bars.get(vt_symbol)
            if not bar:
                continue
            position.visible_holding_bars += 1
            position.last_price = bar.close_price
            position.highest_price = max(position.highest_price, bar.high_price)
            position.lowest_price = min(position.lowest_price if position.lowest_price is not None else bar.low_price, bar.low_price)
            sell_reason = sell_reason_for_position(
                position,
                bar,
                current_day,
                params,
                current_buy_signal=vt_symbol in current_buy_signal_symbols,
                replacement_available=has_strong_replacement_candidate(
                    daily_candidates or [],
                    positions,
                    pending_buy_symbols,
                    pending_sell_symbols,
                    position,
                    params,
                ),
            )
            if not sell_reason:
                continue
            if current_day <= position.entry_date:
                continue
            if index >= len(trading_days) - 1:
                continue
            next_day = trading_days[index + 1]
            replacement_score_gap = strongest_replacement_score_gap(
                daily_candidates or [],
                positions,
                pending_buy_symbols,
                pending_sell_symbols,
                position,
                params,
            )
            if params.enable_contextual_support_reclaim_delay and sell_reason == "support_stop":
                delay_decision = should_delay_contextual_support_reclaim(
                    exit_reason=sell_reason,
                    position=position,
                    bar=bar,
                    params=params,
                    replacement_score_gap=replacement_score_gap,
                )
                if delay_decision["delay"]:
                    pending_reclaim_checks[vt_symbol] = {
                        "check_date": next_day,
                        "signal_date": current_day,
                        "vt_symbol": vt_symbol,
                        "reason": sell_reason,
                    }
                    raw = {
                        "mode": "contextual_support_reclaim_delay",
                        "signal_date": current_day.isoformat(),
                        "check_date": next_day.isoformat(),
                        "entry_date": position.entry_date.isoformat(),
                        "reason": "contextual_support_reclaim_delay",
                        "original_reason": sell_reason,
                        "replacement_score_gap": replacement_score_gap,
                        "delay_reasons": delay_decision["notes"],
                        "not_used_for_signal_score": True,
                    }
                    orders.append(
                        callbacks.order(
                            current_day,
                            vt_symbol,
                            "SELL",
                            None,
                            position.volume,
                            "review_pending",
                            "contextual_support_reclaim_delay",
                            raw,
                        )
                    )
                    continue
            raw = {
                "mode": "daily_close_sell_signal",
                "signal_date": current_day.isoformat(),
                "execute_date": next_day.isoformat(),
                "entry_date": position.entry_date.isoformat(),
                "reason": sell_reason,
            }
            dynamic_failed_raw = dynamic_failed_launch_exit_sell_raw(position, bar, sell_reason)
            branch_raw = low_suction_confirmed_branch_sell_raw(position, sell_reason)
            raw.update(dynamic_failed_raw)
            raw.update(branch_raw)
            pending_sell = {
                "execute_date": next_day,
                "signal_date": current_day,
                "vt_symbol": vt_symbol,
                "reason": sell_reason,
            }
            extra_raw = {}
            extra_raw.update(dynamic_failed_raw)
            extra_raw.update(branch_raw)
            if extra_raw:
                pending_sell["raw"] = extra_raw
            pending_sells.append(pending_sell)
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
                pending_pullback_buys,
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


def age_low_suction_branch_replacement_gates(gates: list[dict[str, Any]], current_day: date) -> None:
    for gate in list(gates):
        if gate.get("last_seen_date") == current_day:
            continue
        gate["wait_count"] = int(gate.get("wait_count") or 0) + 1
        gate["last_seen_date"] = current_day
        if int(gate.get("wait_count") or 0) > int(gate.get("expires_after_trade_count") or 0):
            gates.remove(gate)


def schedule_entry_plans(
    signal_date: date,
    execute_date: date,
    candidates: list[Any],
    positions: dict[str, Position],
    pending_buys: list[dict[str, Any]],
    pending_pullback_buys: list[dict[str, Any]],
    pending_sells: list[dict[str, Any]],
    today_bars: dict[str, Bar],
    params: BacktestParams,
) -> None:
    pending_buy_symbols = {str(order["vt_symbol"]) for order in pending_buys}
    pending_pullback_symbols = {str(order["vt_symbol"]) for order in pending_pullback_buys}
    pending_sell_symbols = {str(order["vt_symbol"]) for order in pending_sells}
    pool_context = candidate_lanes.execution_pool_context(candidates, params.candidate_limit, params.strategy)

    for candidate in execution_candidate_pool(candidates, params):
        vt_symbol = str(candidate.vt_symbol)
        if vt_symbol in positions or vt_symbol in pending_buy_symbols or vt_symbol in pending_pullback_symbols:
            continue
        entry_plan = entry_plan_for_candidate(candidate, signal_date, execute_date, pool_context.get(vt_symbol), params)
        if low_suction_pullback_entry_observation_only(entry_plan, params):
            pending_pullback_buys.append(entry_plan)
            pending_pullback_symbols.add(vt_symbol)
            continue
        reserved_exit_count = len({str(order["vt_symbol"]) for order in pending_sells})
        free_slots = max(params.max_positions - len(positions) + reserved_exit_count - len(pending_buys), 0)
        if free_slots <= 0:
            replacement = rotation_replacement_for_candidate(candidate, positions, pending_sell_symbols, today_bars, params, signal_date)
            if replacement is None:
                continue
            rotation_reason = rotation_reason_for_candidate(candidate, params)
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
                **entry_plan,
            }
        )
        pending_buy_symbols.add(vt_symbol)


def replacement_quality_gate_from_sell(
    order: dict[str, Any],
    current_day: date,
    params: BacktestParams,
) -> dict[str, Any] | None:
    reason = str(order.get("reason") or "")
    low_suction_branch_reasons = {LOW_SUCTION_FAILED_FOLLOW_BRANCH_STOP, LOW_SUCTION_OPENED_SPACE_GIVEBACK_STOP}
    if reason in low_suction_branch_reasons and params.enable_low_suction_branch_replacement_quality_gate:
        mode = "low_suction_branch_replacement_quality_gate"
    elif reason == DYNAMIC_FAILED_LAUNCH_EXIT_STOP and params.enable_dynamic_failed_launch_replacement_quality_gate:
        mode = "dynamic_failed_launch_replacement_quality_gate"
    else:
        return None
    wait_days = max(int(params.low_suction_branch_replacement_gate_wait_days or 0), 1)
    raw = order.get("raw") if isinstance(order.get("raw"), dict) else {}
    gate_id = f"{order.get('vt_symbol')}:{current_day.isoformat()}:{reason}:{len(str(raw))}"
    return {
        "gate_id": gate_id,
        "mode": mode,
        "source_symbol": str(order.get("vt_symbol") or ""),
        "source_reason": reason,
        "sell_execute_date": current_day,
        "expires_after_trade_count": wait_days,
        "wait_count": 1,
        "last_seen_date": current_day,
        "source_raw": raw,
        "not_used_for_signal_score": True,
    }


def low_suction_branch_replacement_gate_from_sell(
    order: dict[str, Any],
    current_day: date,
    params: BacktestParams,
) -> dict[str, Any] | None:
    return replacement_quality_gate_from_sell(order, current_day, params)


def low_suction_branch_replacement_gate_decision(
    order: dict[str, Any],
    positions: dict[str, Position],
    gates: list[dict[str, Any]],
    current_day: date,
    params: BacktestParams,
) -> dict[str, Any]:
    if not replacement_quality_gate_enabled(params):
        return {"status": "not_applicable"}
    gate = first_active_low_suction_branch_replacement_gate(gates)
    if not gate:
        return {"status": "not_applicable"}
    reason = order.get("reason") if isinstance(order.get("reason"), dict) else {}
    strict_setup_note = low_suction_branch_replacement_strict_setup_note(reason, params)
    open_slots = max(params.max_positions - len(positions), 0)
    if open_slots > len(gates) and not strict_setup_note:
        return {"status": "not_applicable"}
    quality = low_suction_branch_replacement_quality(reason, params)
    base = {
        "mode": str(gate.get("mode") or "low_suction_branch_replacement_quality_gate"),
        "status": "accepted" if quality["allowed"] else "rejected",
        "execute_date": current_day.isoformat(),
        "vt_symbol": order.get("vt_symbol"),
        "gate_id": gate.get("gate_id"),
        "gate_source_symbol": gate.get("source_symbol"),
        "gate_source_reason": gate.get("source_reason"),
        "gate_wait_count": gate.get("wait_count"),
        "gate_max_wait_days": gate.get("expires_after_trade_count"),
        "quality": quality,
        "not_used_for_signal_score": True,
    }
    if quality["allowed"]:
        return base
    return base


def replacement_quality_gate_enabled(params: BacktestParams) -> bool:
    return bool(
        params.enable_low_suction_branch_replacement_quality_gate
        or params.enable_dynamic_failed_launch_replacement_quality_gate
    )


def first_active_low_suction_branch_replacement_gate(gates: list[dict[str, Any]]) -> dict[str, Any] | None:
    return gates[0] if gates else None


def consume_low_suction_branch_replacement_gate(gates: list[dict[str, Any]], gate_id: str) -> None:
    for gate in list(gates):
        if str(gate.get("gate_id") or "") == gate_id:
            gates.remove(gate)
            return


def low_suction_branch_replacement_quality(reason: dict[str, Any], params: BacktestParams) -> dict[str, Any]:
    score = _float_or_none(reason.get("entry_total_score") or reason.get("total_score") or reason.get("score")) or 0.0
    setup = str(reason.get("entry_setup") or reason.get("setup_type") or "")
    family = str(reason.get("setup_family") or "")
    bucket = str(reason.get("low_suction_launch_quality_bucket") or "")
    market_warning = _float_or_none(reason.get("market_warning_level")) or 0.0
    ma_convergence = _float_or_none(reason.get("ma_convergence_pct"))
    failed_rules = {str(rule) for rule in (reason.get("failed_rules") or [])}
    risk_flags = {str(flag) for flag in (reason.get("risk_flags") or [])}
    notes: list[str] = []
    allowed = True
    if score < params.low_suction_branch_replacement_min_score:
        allowed = False
        notes.append("score_below_gate")
    if market_warning > params.low_suction_branch_replacement_max_market_warning_level:
        allowed = False
        notes.append("market_warning_too_high")
    if failed_rules or risk_flags:
        allowed = False
        notes.append("has_failed_or_risk_flags")
    strict_setup_note = low_suction_branch_replacement_strict_setup_note(reason, params)
    if strict_setup_note:
        allowed = False
        notes.append(strict_setup_note)
    if family in {"low_suction_buildup", "dragon_low_suction_overlap"} and not bool(reason.get("low_suction_launch_confirmed")):
        allowed = False
        notes.append("low_suction_overlap_unconfirmed")
    if setup == "stealth_low_suction":
        if bucket in {"unconfirmed_buildup", "repeated_launch"}:
            allowed = False
            notes.append("weak_low_suction_launch_bucket")
        if ma_convergence is None or ma_convergence > params.low_suction_branch_replacement_max_low_suction_ma_convergence_pct:
            allowed = False
            notes.append("low_suction_ma_convergence_too_wide")
    elif setup == "dragon_pullback":
        if ma_convergence is None or ma_convergence > params.low_suction_branch_replacement_max_dragon_ma_convergence_pct:
            allowed = False
            notes.append("dragon_ma_convergence_too_wide")
        if reason.get("fresh_tail_buy") is False:
            allowed = False
            notes.append("dragon_not_fresh_tail_buy")
    else:
        allowed = False
        notes.append("unsupported_setup")
    return {
        "allowed": allowed,
        "notes": notes,
        "entry_score": score,
        "entry_setup": setup,
        "setup_family": family,
        "low_suction_launch_quality_bucket": bucket,
        "market_warning_level": market_warning,
        "ma_convergence_pct": ma_convergence,
        "not_used_for_signal_score": True,
    }


def low_suction_branch_replacement_strict_setup_note(reason: dict[str, Any], params: BacktestParams) -> str | None:
    if not params.enable_low_suction_branch_replacement_strict_setup_gate:
        return None
    family = str(reason.get("setup_family") or "")
    bucket = str(reason.get("low_suction_launch_quality_bucket") or "")
    launch_confirmed = bool(reason.get("low_suction_launch_confirmed"))
    if family in {"low_suction_buildup", "dragon_low_suction_overlap"} and not launch_confirmed:
        return "strict_setup_gate_unconfirmed_buildup_or_overlap"
    if bucket == "unconfirmed_buildup":
        return "strict_setup_gate_unconfirmed_buildup_or_overlap"
    return None


def entry_plan_for_candidate(
    candidate: Any,
    signal_date: date,
    execute_date: date,
    execution_context: dict[str, Any] | None,
    params: BacktestParams,
) -> dict[str, Any]:
    reason = candidate_entry_reason(candidate, execution_context)
    plan = {
        "execute_date": execute_date,
        "signal_date": signal_date,
        "vt_symbol": str(candidate.vt_symbol),
        "reason": reason,
    }
    pullback_plan = low_suction_pullback_entry_plan(reason, signal_date, execute_date, params)
    if pullback_plan:
        plan.update(pullback_plan)
    return plan


def low_suction_pullback_entry_plan(
    reason: dict[str, Any],
    signal_date: date,
    first_execute_date: date,
    params: BacktestParams,
) -> dict[str, Any] | None:
    if not low_suction_pullback_entry_applies(reason, params):
        return None
    target = low_suction_pullback_entry_target(reason, params)
    if target is None:
        return None
    return {
        "entry_execution_mode": "low_suction_pullback_entry",
        "pullback_entry_target": target,
        "pullback_entry_wait_count": 0,
        "pullback_entry_first_execute_date": first_execute_date,
        "pullback_entry_max_wait_days": max(int(params.low_suction_pullback_entry_max_wait_days or 0), 1),
        "pullback_entry_source": "ma10" if _float_or_none(reason.get("ma10")) is not None else "support_price",
        "raw": {
            "mode": "low_suction_pullback_entry_pending",
            "signal_date": signal_date.isoformat(),
            "first_execute_date": first_execute_date.isoformat(),
            "target_price": target,
            "target_source": "ma10" if _float_or_none(reason.get("ma10")) is not None else "support_price",
            "max_wait_days": max(int(params.low_suction_pullback_entry_max_wait_days or 0), 1),
            "not_used_for_signal_score": True,
        },
    }


def low_suction_pullback_entry_observation_only(plan: dict[str, Any], params: BacktestParams) -> bool:
    return (
        bool(params.enable_low_suction_pullback_entry)
        and not bool(params.low_suction_pullback_entry_reserve_slot)
        and plan.get("entry_execution_mode") == "low_suction_pullback_entry"
    )


def low_suction_pullback_entry_applies(reason: dict[str, Any], params: BacktestParams) -> bool:
    if not params.enable_low_suction_pullback_entry:
        return False
    if params.strategy != DRAGON_PULLBACK_STRATEGY_ID or params.execution_model != "legacy_next_open":
        return False
    setup = str(reason.get("entry_setup") or reason.get("setup_type") or "")
    low_suction_days = _float_or_none(reason.get("low_suction_days")) or 0.0
    if setup != "stealth_low_suction" and low_suction_days < 3:
        return False
    if not bool(reason.get("low_suction_launch_confirmed")):
        return False
    bucket = str(reason.get("low_suction_launch_quality_bucket") or low_suction_launch_quality_bucket(reason))
    if bucket not in LOW_SUCTION_PULLBACK_ENTRY_BUCKETS:
        return False
    bad_flags = {"distribution_risk", "high_level_sideways_distribution_risk", "volume_stall_risk"}
    risk_flags = {str(flag) for flag in (reason.get("risk_flags") or [])}
    failed_rules = {str(rule) for rule in (reason.get("failed_rules") or [])}
    return not (risk_flags & bad_flags or failed_rules & bad_flags)


def low_suction_pullback_entry_target(reason: dict[str, Any], params: BacktestParams) -> float | None:
    base = _float_or_none(reason.get("ma10")) or _float_or_none(reason.get("support_price"))
    if base is None or base <= 0:
        return None
    return base * (1 + max(float(params.low_suction_pullback_entry_buffer_pct or 0.0), 0.0))


def low_suction_trigger_day_confirmation(order: dict[str, Any], decision: dict[str, Any], bar: Bar | None) -> dict[str, Any]:
    reason = order.get("reason") if isinstance(order.get("reason"), dict) else {}
    target = _float_or_none(decision.get("target_price") or order.get("pullback_entry_target"))
    volume5 = _float_or_none(reason.get("volume5"))
    if bar is None:
        return {
            **decision,
            "confirmed": False,
            "status": "rejected",
            "reason": "missing_trigger_day_bar",
            "price": None,
            "price_source": None,
            "proxy_used": False,
        }
    bullish_close = bool(bar.close_price > bar.open_price)
    volume_confirmed = bool(volume5 is not None and bar.volume is not None and float(bar.volume) >= volume5)
    close_reclaimed_target = bool(target is not None and bar.close_price >= target)
    confirmed = bullish_close and volume_confirmed and close_reclaimed_target
    return {
        **decision,
        "confirmed": confirmed,
        "status": "confirmed" if confirmed else "rejected",
        "reason": "low_suction_trigger_day_confirmed" if confirmed else "low_suction_trigger_day_confirmation_failed",
        "trigger_date": bar.trade_date.isoformat(),
        "trigger_open_price": bar.open_price,
        "trigger_high_price": bar.high_price,
        "trigger_low_price": bar.low_price,
        "trigger_close_price": bar.close_price,
        "trigger_volume": bar.volume,
        "signal_volume5": volume5,
        "trigger_bullish_close": bullish_close,
        "trigger_volume_ge_signal_volume5": volume_confirmed,
        "trigger_close_ge_pullback_target": close_reclaimed_target,
        "price": None,
        "price_source": None,
        "proxy_used": False,
        "not_used_for_signal_score": True,
    }


def low_suction_pullback_entry_decision(order: dict[str, Any], current_day: date, bar: Bar | None) -> dict[str, Any]:
    if order.get("entry_execution_mode") != "low_suction_pullback_entry":
        return {"status": "not_applicable"}
    wait_count = int(order.get("pullback_entry_wait_count") or 0) + 1
    order["pullback_entry_wait_count"] = wait_count
    target = _float_or_none(order.get("pullback_entry_target"))
    max_wait = max(int(order.get("pullback_entry_max_wait_days") or 1), 1)
    base = {
        "execution_model": "legacy_next_open",
        "mode": "low_suction_pullback_entry",
        "signal_date": _iso_date(order.get("signal_date")),
        "execute_date": current_day.isoformat(),
        "first_execute_date": _iso_date(order.get("pullback_entry_first_execute_date")),
        "target_price": target,
        "target_source": order.get("pullback_entry_source"),
        "wait_count": wait_count,
        "max_wait_days": max_wait,
        "not_used_for_signal_score": True,
    }
    if target is None or target <= 0:
        return {**base, "status": "expired", "reason": "missing_pullback_entry_target", "price": None, "price_source": None, "proxy_used": False}
    if bar is None:
        if wait_count >= max_wait:
            return {**base, "status": "expired", "reason": "no_execute_bar", "price": None, "price_source": None, "proxy_used": False}
        return {**base, "status": "waiting", "reason": "no_execute_bar", "price": None, "price_source": None, "proxy_used": False}
    if bar.open_price <= target:
        return {
            **base,
            "status": "filled",
            "reason": "open_at_or_below_pullback_target",
            "price": bar.open_price,
            "price_source": "stock_daily_bars.open_price",
            "proxy_used": False,
        }
    if bar.low_price <= target:
        return {
            **base,
            "status": "filled",
            "reason": "low_touch_pullback_target",
            "price": target,
            "price_source": "stock_daily_bars.low_touch_limit_proxy",
            "proxy_used": True,
            "open_price": bar.open_price,
            "low_price": bar.low_price,
            "high_price": bar.high_price,
            "close_price": bar.close_price,
        }
    if wait_count >= max_wait:
        return {
            **base,
            "status": "expired",
            "reason": "pullback_target_not_touched",
            "price": None,
            "price_source": "stock_daily_bars.low_price",
            "proxy_used": False,
            "open_price": bar.open_price,
            "low_price": bar.low_price,
            "high_price": bar.high_price,
            "close_price": bar.close_price,
        }
    return {
        **base,
        "status": "waiting",
        "reason": "pullback_target_not_touched",
        "price": None,
        "price_source": "stock_daily_bars.low_price",
        "proxy_used": False,
        "open_price": bar.open_price,
        "low_price": bar.low_price,
        "high_price": bar.high_price,
        "close_price": bar.close_price,
    }


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
    if params.enable_phase_replacement_quality:
        replacement = phase_replacement_quality_replacement_for_candidate(
            candidate,
            positions,
            pending_sell_symbols,
            today_bars,
            params,
            signal_date,
        )
        if replacement is not None:
            return replacement
    if params.enable_missed_candidate_quality_rotation:
        replacement = missed_candidate_quality_replacement_for_candidate(
            candidate,
            positions,
            pending_sell_symbols,
            today_bars,
            params,
            signal_date,
        )
        if replacement is not None:
            return replacement
    if params.enable_protected_weak_holding_rotation:
        replacement = protected_weak_holding_rotation_replacement_for_candidate(
            candidate,
            positions,
            pending_sell_symbols,
            today_bars,
            params,
            signal_date,
        )
        if replacement is not None:
            return replacement
    if params.enable_weak_holding_quality_rotation:
        replacement = weak_holding_quality_rotation_replacement_for_candidate(
            candidate,
            positions,
            pending_sell_symbols,
            today_bars,
            params,
            signal_date,
        )
        if replacement is not None:
            return replacement
    if params.enable_high_quality_trend_rotation:
        replacement = high_quality_trend_rotation_replacement_for_candidate(
            candidate,
            positions,
            pending_sell_symbols,
            today_bars,
            params,
            signal_date,
        )
        if replacement is not None:
            return replacement
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
        if low_suction_confirmed_opened_space_rotation_protected(position, today_bars.get(vt_symbol), params):
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


def has_strong_replacement_candidate(
    candidates: list[Any],
    positions: dict[str, Position],
    pending_buy_symbols: set[str],
    pending_sell_symbols: set[str],
    position: Position,
    params: BacktestParams,
) -> bool:
    if not params.enable_contextual_failed_launch_exit_stop:
        return False

    entry_score = entry_score_for_position(position)
    held_symbols = set(positions)
    for candidate in execution_candidate_pool(candidates, params):
        vt_symbol = str(getattr(candidate, "vt_symbol", "") or "")
        if not vt_symbol or vt_symbol in held_symbols:
            continue
        if vt_symbol in pending_buy_symbols or vt_symbol in pending_sell_symbols:
            continue
        if not bool(getattr(candidate, "entry_signal", False)):
            continue
        total_score = float(getattr(candidate, "total_score", 0) or 0)
        if total_score < params.rotation_min_score:
            continue
        if entry_score and total_score < entry_score + params.rotation_min_score_gap:
            continue
        if not scoring.is_buy_candidate(candidate, params):
            continue
        return True
    return False


def strongest_replacement_score_gap(
    candidates: list[Any],
    positions: dict[str, Position],
    pending_buy_symbols: set[str],
    pending_sell_symbols: set[str],
    position: Position,
    params: BacktestParams,
) -> float | None:
    entry_score = entry_score_for_position(position)
    held_symbols = set(positions)
    best_gap: float | None = None
    for candidate in execution_candidate_pool(candidates, params):
        vt_symbol = str(getattr(candidate, "vt_symbol", "") or "")
        if not vt_symbol or vt_symbol in held_symbols:
            continue
        if vt_symbol in pending_buy_symbols or vt_symbol in pending_sell_symbols:
            continue
        if not bool(getattr(candidate, "entry_signal", False)):
            continue
        if not scoring.is_buy_candidate(candidate, params):
            continue
        gap = float(getattr(candidate, "total_score", 0) or 0) - entry_score
        if best_gap is None or gap > best_gap:
            best_gap = gap
    return best_gap


def contextual_failed_launch_exit_needs_replacement_lookup(
    positions: dict[str, Position],
    today_bars: dict[str, Bar],
    params: BacktestParams,
) -> bool:
    if params.strategy != DRAGON_PULLBACK_STRATEGY_ID or not params.enable_contextual_failed_launch_exit_stop:
        return False
    for vt_symbol, position in positions.items():
        bar = today_bars.get(vt_symbol)
        if bar and contextual_failed_launch_exit_preflight_applies(position, bar):
            return True
    return False


def allow_signal_rotation(candidate: Any, params: BacktestParams) -> bool:
    if params.strategy != DRAGON_PULLBACK_STRATEGY_ID or not params.enable_signal_rotation:
        return False
    if not bool(getattr(candidate, "entry_signal", False)):
        return False
    if params.enable_phase_replacement_quality and phase_replacement_quality_candidate(candidate, params):
        return True
    if params.enable_missed_candidate_quality_rotation and missed_candidate_quality_rotation_candidate(candidate, params):
        return True
    if params.enable_protected_weak_holding_rotation and protected_weak_holding_rotation_candidate(candidate, params):
        return True
    if params.enable_weak_holding_quality_rotation and weak_holding_quality_rotation_candidate(candidate, params):
        return True
    if params.enable_high_quality_trend_rotation and high_quality_trend_rotation_candidate(candidate, params):
        return True
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


def missed_candidate_quality_rotation_candidate(candidate: Any, params: BacktestParams) -> bool:
    if float(getattr(candidate, "total_score", 0) or 0) < params.missed_rotation_min_score:
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    if evidence.get("dragon_state") != "TAIL_BUY_READY" and str(evidence.get("entry_setup") or "") != "stealth_low_suction":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") == "unconfirmed_buildup":
        return False
    if evidence.get("low_suction_launch_confirmed") is False and float(evidence.get("low_suction_days") or 0) >= 3:
        return False
    return True


def high_quality_trend_rotation_candidate(candidate: Any, params: BacktestParams) -> bool:
    if float(getattr(candidate, "total_score", 0) or 0) < params.high_quality_rotation_min_score:
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    execution = evidence.get("candidate_execution") if isinstance(evidence.get("candidate_execution"), dict) else {}
    execution_rank = _int_or_none(execution.get("execution_candidate_rank"))
    if execution_rank is None:
        execution_rank = _int_or_none(execution.get("raw_signal_rank"))
    if execution_rank is not None and execution_rank > max(int(params.high_quality_rotation_max_rank or 10), 1):
        return False
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    dragon_ready = evidence.get("dragon_state") == "TAIL_BUY_READY" and evidence.get("fresh_tail_buy") is not False
    low_suction_confirmed = (
        setup == "stealth_low_suction"
        and bool(evidence.get("low_suction_launch_confirmed"))
        and str(evidence.get("low_suction_launch_quality_bucket") or low_suction_launch_quality_bucket(evidence))
        in {"balanced_first_lift", "other_confirmed_launch"}
    )
    if not (dragon_ready or low_suction_confirmed):
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") == "unconfirmed_buildup":
        return False
    return not has_hard_rotation_risk(evidence)


def weak_holding_quality_rotation_candidate(candidate: Any, params: BacktestParams) -> bool:
    if not bool(getattr(candidate, "entry_signal", False)):
        return False
    if float(getattr(candidate, "total_score", 0) or 0) < params.weak_holding_rotation_min_score:
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    execution = evidence.get("candidate_execution") if isinstance(evidence.get("candidate_execution"), dict) else {}
    execution_rank = _int_or_none(execution.get("execution_candidate_rank"))
    if execution_rank is None:
        execution_rank = _int_or_none(execution.get("raw_signal_rank"))
    if execution_rank is not None and execution_rank > max(int(params.weak_holding_rotation_max_rank or 20), 1):
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") == "unconfirmed_buildup":
        return False
    if has_hard_rotation_risk(evidence):
        return False
    return (
        weak_rotation_tight_ma_candidate(evidence, params)
        or weak_rotation_low_suction_candidate(evidence, params)
        or weak_rotation_fresh_dragon_candidate(evidence)
    )


def protected_weak_holding_rotation_candidate(candidate: Any, params: BacktestParams) -> bool:
    return weak_holding_quality_rotation_candidate(candidate, params)


def weak_rotation_tight_ma_candidate(evidence: dict[str, Any], params: BacktestParams) -> bool:
    convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    return bool(convergence is not None and convergence <= params.weak_holding_rotation_max_ma_convergence_pct)


def weak_rotation_low_suction_candidate(evidence: dict[str, Any], params: BacktestParams) -> bool:
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    if low_suction_days < params.weak_holding_rotation_min_low_suction_days:
        return False
    if not bool(evidence.get("low_suction_launch_confirmed")):
        return False
    bucket = str(evidence.get("low_suction_launch_quality_bucket") or low_suction_launch_quality_bucket(evidence))
    return bucket in {"balanced_first_lift", "other_confirmed_launch", "late_pullback_launch"}


def weak_rotation_fresh_dragon_candidate(evidence: dict[str, Any]) -> bool:
    return bool(evidence.get("dragon_state") == "TAIL_BUY_READY" and evidence.get("fresh_tail_buy") is not False)


def has_hard_rotation_risk(evidence: dict[str, Any]) -> bool:
    failures = {str(rule) for rule in (evidence.get("failed_rules") or [])}
    risk_flags = {str(flag) for flag in (evidence.get("risk_flags") or [])}
    return bool(failures & HIGH_QUALITY_ROTATION_HARD_FAILURES or risk_flags & HIGH_QUALITY_ROTATION_HARD_FAILURES)


def phase_replacement_quality_candidate(candidate: Any, params: BacktestParams) -> bool:
    if not params.enable_phase_replacement_quality:
        return False
    if float(getattr(candidate, "total_score", 0) or 0) < max(params.rotation_min_score, 98.0):
        return False
    evidence = getattr(candidate, "evidence", {}) or {}
    family = str(evidence.get("setup_family") or "")
    if family not in {"dragon_pullback", "low_suction_first_lift", "dragon_low_suction_overlap"}:
        return False
    if family == "low_suction_first_lift" and not bool(evidence.get("low_suction_launch_confirmed")):
        return False
    selector = evidence.get("phase_aware_setup_selector") if isinstance(evidence.get("phase_aware_setup_selector"), dict) else {}
    if selector and selector.get("allowed") is False:
        return False
    return True


def phase_replacement_quality_replacement_for_candidate(
    candidate: Any,
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None,
) -> Position | None:
    if not phase_replacement_quality_candidate(candidate, params):
        return None
    candidate_score = float(getattr(candidate, "total_score", 0) or 0)
    rows: list[tuple[float, float, Position]] = []
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        if low_suction_confirmed_opened_space_rotation_protected(position, today_bars.get(vt_symbol), params):
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < max(params.rotation_min_holding_days, 4):
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        holding_return_pct = position_return_pct(position, bar)
        if holding_return_pct > min(params.rotation_max_holding_return_pct, 1.0):
            continue
        entry_score = entry_score_for_position(position)
        if candidate_score < entry_score + max(params.rotation_min_score_gap, 10.0):
            continue
        if current_same_stock_hold_signal(position, bar):
            continue
        rows.append((holding_return_pct, entry_score, position))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1], item[2].entry_date, item[2].vt_symbol))
    return rows[0][2]


def missed_candidate_quality_replacement_for_candidate(
    candidate: Any,
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None,
) -> Position | None:
    if not missed_candidate_quality_rotation_candidate(candidate, params):
        return None
    candidate_score = float(getattr(candidate, "total_score", 0) or 0)
    rows: list[tuple[float, float, Position]] = []
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        if low_suction_confirmed_opened_space_rotation_protected(position, today_bars.get(vt_symbol), params):
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < params.missed_rotation_min_held_days:
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        holding_return_pct = position_return_pct(position, bar)
        if holding_return_pct > params.missed_rotation_max_held_return_pct:
            continue
        entry_score = entry_score_for_position(position)
        if candidate_score < entry_score + params.missed_rotation_min_score_gap:
            continue
        if current_same_stock_hold_signal(position, bar):
            continue
        rows.append((holding_return_pct, entry_score, position))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1], item[2].entry_date, item[2].vt_symbol))
    return rows[0][2]


def weak_holding_quality_rotation_replacement_for_candidate(
    candidate: Any,
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None,
) -> Position | None:
    if not weak_holding_quality_rotation_candidate(candidate, params):
        return None
    candidate_score = float(getattr(candidate, "total_score", 0) or 0)
    rows: list[tuple[float, float, date, str, Position]] = []
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        if low_suction_confirmed_opened_space_rotation_protected(position, bar, params):
            continue
        if current_same_stock_hold_signal(position, bar):
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < params.weak_holding_rotation_min_held_days:
            continue
        holding_return_pct = position_return_pct(position, bar)
        if holding_return_pct > params.weak_holding_rotation_max_held_return_pct:
            continue
        entry_score = entry_score_for_position(position)
        if candidate_score < entry_score + params.weak_holding_rotation_min_score_gap:
            continue
        rows.append((holding_return_pct, entry_score, position.entry_date, vt_symbol, position))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return rows[0][4]


def protected_weak_holding_rotation_replacement_for_candidate(
    candidate: Any,
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None,
) -> Position | None:
    if not protected_weak_holding_rotation_candidate(candidate, params):
        return None
    candidate_score = float(getattr(candidate, "total_score", 0) or 0)
    rows: list[tuple[float, float, date, str, Position]] = []
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < params.weak_holding_rotation_min_held_days:
            continue
        entry_score = entry_score_for_position(position)
        if candidate_score < entry_score + params.weak_holding_rotation_min_score_gap:
            continue
        decision = protected_weak_holding_replacement_decision(
            position,
            bar,
            params,
            price=bar.close_price,
            price_source="signal_close",
            include_close_context=True,
        )
        if not decision["replaceable"]:
            continue
        rows.append((float(decision["current_return_pct"]), entry_score, position.entry_date, vt_symbol, position))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return rows[0][4]


def high_quality_trend_rotation_replacement_for_candidate(
    candidate: Any,
    positions: dict[str, Position],
    pending_sell_symbols: set[str],
    today_bars: dict[str, Bar],
    params: BacktestParams,
    signal_date: date | None,
) -> Position | None:
    if not high_quality_trend_rotation_candidate(candidate, params):
        return None
    candidate_score = float(getattr(candidate, "total_score", 0) or 0)
    rows: list[tuple[float, float, date, str, Position]] = []
    for vt_symbol, position in positions.items():
        if vt_symbol in pending_sell_symbols:
            continue
        bar = today_bars.get(vt_symbol)
        if not bar:
            continue
        if low_suction_confirmed_opened_space_rotation_protected(position, bar, params):
            continue
        if current_same_stock_hold_signal(position, bar):
            continue
        if signal_date is not None and (signal_date - position.entry_date).days < params.high_quality_rotation_min_held_days:
            continue
        holding_return_pct = position_return_pct(position, bar)
        if holding_return_pct > params.high_quality_rotation_max_held_return_pct:
            continue
        entry_score = entry_score_for_position(position)
        if candidate_score < entry_score + params.high_quality_rotation_min_score_gap:
            continue
        rows.append((holding_return_pct, entry_score, position.entry_date, vt_symbol, position))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return rows[0][4]


def current_same_stock_hold_signal(position: Position, bar: Bar) -> bool:
    context = dragon_pullback_hold_context(position, bar)
    return bool(context["low_base_accumulation"] or (context["ma_support_pullback"] and context["price_volume_sync"]))


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
        if low_suction_confirmed_opened_space_rotation_protected(position, today_bars.get(vt_symbol), params):
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


def weak_holding_rotation_sell_invalid_at_execute(
    order: dict[str, Any],
    position: Position,
    bar: Bar,
    params: BacktestParams,
) -> bool:
    reason = str(order.get("reason") or "")
    if not weak_holding_rotation_reason(reason):
        return False
    if reason == PROTECTED_WEAK_HOLDING_ROTATION_REASON:
        decision = protected_weak_holding_replacement_decision(
            position,
            bar,
            params,
            price=bar.open_price,
            price_source="execute_open",
            include_close_context=False,
        )
        return not bool(decision["replaceable"])
    execute_return_pct = position_execute_return_pct(position, bar)
    return execute_return_pct > params.weak_holding_rotation_max_held_return_pct


def weak_holding_rotation_execute_raw(
    order: dict[str, Any],
    position: Position,
    bar: Bar,
    params: BacktestParams,
) -> dict[str, Any]:
    reason = str(order.get("reason") or "")
    if not weak_holding_rotation_reason(reason):
        return {}
    raw: dict[str, Any] = {}
    if reason == PROTECTED_WEAK_HOLDING_ROTATION_REASON:
        raw["protected_weak_holding_decision"] = protected_weak_holding_replacement_decision(
            position,
            bar,
            params,
            price=bar.open_price,
            price_source="execute_open",
            include_close_context=False,
        )
    return {
        **raw,
        "execute_open_return_pct": position_execute_return_pct(position, bar),
        "max_held_return_pct": params.weak_holding_rotation_max_held_return_pct,
        "not_used_for_signal_score": True,
    }


def weak_holding_rotation_cancel_raw(position: Position, bar: Bar, params: BacktestParams, order: dict[str, Any] | None = None) -> dict[str, Any]:
    reason = str((order or {}).get("reason") or "")
    decision = (
        protected_weak_holding_replacement_decision(
            position,
            bar,
            params,
            price=bar.open_price,
            price_source="execute_open",
            include_close_context=False,
        )
        if reason == PROTECTED_WEAK_HOLDING_ROTATION_REASON
        else None
    )
    raw = {
        "status": "cancelled",
        "cancel_reason": "weak_holding_no_longer_below_threshold_at_execute",
        "execute_open_return_pct": position_execute_return_pct(position, bar),
        "max_held_return_pct": params.weak_holding_rotation_max_held_return_pct,
        "not_used_for_signal_score": True,
    }
    if decision is not None:
        raw["cancel_reason"] = str(decision["reason"])
        raw["protection_bucket"] = decision["bucket"]
        raw["protected_weak_holding_decision"] = decision
    return raw


def weak_holding_rotation_reason(reason: str) -> bool:
    return reason in {WEAK_HOLDING_QUALITY_ROTATION_REASON, PROTECTED_WEAK_HOLDING_ROTATION_REASON}


def rotation_reason_for_candidate(candidate: Any, params: BacktestParams | None = None) -> str:
    if (
        params is not None
        and params.enable_protected_weak_holding_rotation
        and protected_weak_holding_rotation_candidate(candidate, params)
    ):
        return PROTECTED_WEAK_HOLDING_ROTATION_REASON
    if (
        params is not None
        and params.enable_weak_holding_quality_rotation
        and weak_holding_quality_rotation_candidate(candidate, params)
    ):
        return WEAK_HOLDING_QUALITY_ROTATION_REASON
    if params is not None and params.enable_high_quality_trend_rotation and high_quality_trend_rotation_candidate(candidate, params):
        return "rotation_for_high_quality_trend_candidate"
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


def protected_weak_holding_replacement_decision(
    position: Position,
    bar: Bar,
    params: BacktestParams,
    *,
    price: float,
    price_source: str,
    include_close_context: bool,
) -> dict[str, Any]:
    current_return_pct = _position_return_pct_at_price(position, price)
    high_return_pct = _position_return_pct_at_price(position, position.highest_price)
    threshold = float(params.weak_holding_rotation_max_held_return_pct)
    reason = position.reason if isinstance(position.reason, dict) else {}
    uptrendish = position_market_is_uptrendish(reason)
    recovery = str(reason.get("recovery_state") or "")
    bucket = "replaceable_weak_holding"
    protection_reason = "execute_open_still_weak" if price_source == "execute_open" else "signal_close_still_weak"
    replaceable = True

    if current_return_pct > threshold:
        replaceable = False
        bucket = "protect_open_profit" if current_return_pct >= 0 else "protect_repaired_holding"
        protection_reason = "holding_no_longer_below_weak_threshold"
    elif uptrendish and current_return_pct > threshold - PROTECTED_WEAK_HOLDING_UPTREND_REPAIR_BUFFER_PCT:
        replaceable = False
        bucket = "protect_uptrend_repair"
        protection_reason = "uptrend_holding_near_repair"
    elif recovery == "warming_confirmed" and current_return_pct > threshold - PROTECTED_WEAK_HOLDING_TREND_BUFFER_PCT:
        replaceable = False
        bucket = "protect_uptrend_repair"
        protection_reason = "warming_holding_near_repair"
    elif (
        high_return_pct >= 12.0
        and current_return_pct > threshold - PROTECTED_WEAK_HOLDING_TREND_BUFFER_PCT
        and (uptrendish or (include_close_context and current_same_stock_hold_signal(position, bar)))
    ):
        replaceable = False
        bucket = "protect_trend_winner"
        protection_reason = "visible_trend_winner_not_deeply_weak"
    elif include_close_context and (
        low_suction_confirmed_opened_space_rotation_protected(position, bar, params)
        or current_same_stock_hold_signal(position, bar)
    ):
        replaceable = False
        bucket = "protect_same_stock_hold_signal"
        protection_reason = "current_holding_still_has_support_signal"

    return {
        "replaceable": replaceable,
        "bucket": bucket,
        "reason": protection_reason,
        "price_source": price_source,
        "current_return_pct": round(current_return_pct, 4),
        "high_return_pct": round(high_return_pct, 4),
        "weak_threshold_pct": threshold,
        "dynamic_market_regime": reason.get("dynamic_market_regime"),
        "recovery_state": reason.get("recovery_state"),
        "not_used_for_signal_score": True,
    }


def position_market_is_uptrendish(reason: dict[str, Any]) -> bool:
    regime = str(reason.get("dynamic_market_regime") or "")
    phase = str(reason.get("market_phase") or reason.get("trading_market_phase") or "")
    if regime in PROTECTED_WEAK_HOLDING_UPTREND_REGIMES:
        return True
    return phase in {"uptrend", "主升"}


def _position_return_pct_at_price(position: Position, price: float | None) -> float:
    if not position.cost_price or price is None:
        return 0.0
    return (float(price) / float(position.cost_price) - 1) * 100


def position_return_pct(position: Position, bar: Bar) -> float:
    if not position.cost_price:
        return 0.0
    return (bar.close_price / position.cost_price - 1) * 100


def position_execute_return_pct(position: Position, bar: Bar) -> float:
    if not position.cost_price:
        return 0.0
    return (bar.open_price / position.cost_price - 1) * 100


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
        position.lowest_price = min(position.lowest_price if position.lowest_price is not None else bar.low_price, bar.low_price)
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
            lowest_price=execute_bar.low_price,
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
    replacement_available: bool = False,
) -> str | None:
    if params.strategy == DRAGON_PULLBACK_STRATEGY_ID:
        return dragon_pullback_sell_reason(
            position,
            bar,
            current_day,
            params,
            current_buy_signal=current_buy_signal,
            replacement_available=replacement_available,
        )
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
    replacement_available: bool = False,
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

    drawdown_from_high = bar.close_price / position.highest_price - 1 if position.highest_price else 0
    high_gain = position.highest_price / cost_price - 1 if cost_price and position.highest_price else 0
    low_suction_branch_decision = low_suction_confirmed_branch_decision(position, bar, params)
    if low_suction_branch_decision.get("triggered"):
        position.low_suction_confirmed_branch = str(low_suction_branch_decision.get("branch") or "")
        position.low_suction_confirmed_branch_raw = low_suction_branch_decision
        return str(low_suction_branch_decision["reason"])
    opened_space_hold = low_suction_branch_decision.get("branch") == "opened_space"
    if opened_space_hold:
        position.low_suction_confirmed_branch = "opened_space"
        position.low_suction_confirmed_branch_raw = low_suction_branch_decision
    if support_stop is not None and bar.close_price <= support_stop:
        return "support_stop"
    if ma20 is not None and bar.close_price < ma20 * 0.97 and current_day > position.entry_date:
        return "trend_break"
    if (
        params.enable_dynamic_failed_launch_exit_stop
        and dynamic_failed_launch_exit_stop_applies(position, bar, gain, high_gain, hold_soft_exit, current_buy_signal)
    ):
        return DYNAMIC_FAILED_LAUNCH_EXIT_STOP
    if (
        params.enable_contextual_failed_launch_exit_stop
        and contextual_failed_launch_exit_stop_applies(position, bar, gain, high_gain, hold_soft_exit, replacement_available)
    ):
        return "contextual_failed_launch_exit_stop"
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
    if params.enable_contextual_peak_giveback_stop:
        peak_decision = should_trigger_contextual_peak_giveback_stop(
            highest_return_pct=high_gain,
            current_return_pct=gain,
            holding_days=(current_day - position.entry_date).days,
            has_current_buy_or_hold_signal=hold_soft_exit,
            market_warning_level=_float_or_none(reason.get("market_warning_level")) or 0,
            support_reclaim_failed=peak_giveback_support_reclaim_failed(position, bar),
            distribution_risk=bool(
                reason.get("high_level_sideways_distribution_risk")
                or reason.get("volume_stall_risk")
                or reason.get("distribution_risk")
            ),
            min_high_gain_pct=params.peak_giveback_min_high_gain_pct,
            max_current_gain_pct=params.peak_giveback_max_current_gain_pct,
            drawdown_pct=params.peak_giveback_drawdown_pct,
            min_holding_days=params.peak_giveback_min_holding_days,
        )
        if peak_decision["trigger"]:
            return str(peak_decision["reason"])
    if high_gain >= 0.25 and gain <= 0.12 and drawdown_from_high <= -0.12:
        return "profit_protection_stop"
    if high_gain >= 0.18 and gain <= 0.08 and drawdown_from_high <= -0.10:
        return "profit_protection_stop"
    trend_trailing_drawdown_buffer = max(params.trend_trailing_dd_buffer_pct, 0.0)
    if gain >= 0.30 and drawdown_from_high <= -(0.10 + trend_trailing_drawdown_buffer):
        return "trend_trailing_stop"
    if gain >= 0.18 and drawdown_from_high <= -(0.12 + trend_trailing_drawdown_buffer):
        return "trend_trailing_stop"
    if ma10 is not None and gain > 0.08 and bar.close_price < ma10 * 0.98:
        if hold_soft_exit and ma20 is not None and bar.close_price >= ma20 * 0.99:
            return None
        return "trend_break"
    if (current_day - position.entry_date).days >= params.time_stop_days * 2 and gain < 0.04:
        if hold_soft_exit or opened_space_hold:
            return None
        return "time_efficiency_stop"
    return None


def low_suction_confirmed_branch_decision(position: Position, bar: Bar, params: BacktestParams) -> dict[str, Any]:
    """Return a default-off branch exit decision for confirmed low-suction entries."""

    if (
        not params.enable_low_suction_confirmed_branch_exit
        or params.strategy != DRAGON_PULLBACK_STRATEGY_ID
        or not is_low_suction_trigger_day_confirmed_position(position)
        or not position.cost_price
    ):
        return {"active": False, "not_used_for_signal_score": True}
    high_return_pct = (position.highest_price / position.cost_price - 1) * 100 if position.highest_price else 0.0
    low_price = position.lowest_price if position.lowest_price is not None else bar.low_price
    low_return_pct = (low_price / position.cost_price - 1) * 100 if low_price else 0.0
    close_return_pct = (bar.close_price / position.cost_price - 1) * 100 if bar.close_price else 0.0
    giveback_pct = high_return_pct - close_return_pct
    base = {
        "active": True,
        "visible_holding_bars": position.visible_holding_bars,
        "high_return_pct": round(high_return_pct, 4),
        "low_return_pct": round(low_return_pct, 4),
        "close_return_pct": round(close_return_pct, 4),
        "giveback_from_peak_pct": round(giveback_pct, 4),
        "entry_date": position.entry_date.isoformat(),
        "signal_date": bar.trade_date.isoformat(),
        "not_used_for_signal_score": True,
    }
    if (
        position.visible_holding_bars == 3
        and low_return_pct <= params.low_suction_failed_follow_d3_low_pct
        and high_return_pct < params.low_suction_failed_follow_d3_high_pct
        and close_return_pct <= params.low_suction_failed_follow_d3_close_pct
    ):
        return {
            **base,
            "branch": "failed_follow",
            "triggered": True,
            "reason": LOW_SUCTION_FAILED_FOLLOW_BRANCH_STOP,
            "label": "低吸确认后三日没拉起破位撤",
        }
    opened_space = position.low_suction_confirmed_branch == "opened_space" or bool(
        position.visible_holding_bars == 5
        and high_return_pct >= params.low_suction_opened_space_d5_high_pct
        and low_return_pct > params.low_suction_opened_space_d5_low_pct
    )
    if not opened_space:
        return {**base, "branch": "unclassified", "triggered": False, "reason": None}
    if (high_return_pct >= 8.0 and giveback_pct >= 5.0 and close_return_pct <= 4.0) or (
        high_return_pct >= 15.0 and giveback_pct >= 8.0
    ):
        return {
            **base,
            "branch": "opened_space",
            "triggered": True,
            "reason": LOW_SUCTION_OPENED_SPACE_GIVEBACK_STOP,
            "label": "低吸打开空间后回撤卖",
        }
    return {
        **base,
        "branch": "opened_space",
        "triggered": False,
        "reason": None,
        "label": "低吸已打开空间，等待趋势回撤",
    }


def is_low_suction_trigger_day_confirmed_position(position: Position) -> bool:
    reason = position.reason if isinstance(position.reason, dict) else {}
    execution = reason.get("execution") if isinstance(reason.get("execution"), dict) else {}
    return str(execution.get("mode") or "") == LOW_SUCTION_CONFIRMED_ENTRY_MODE


def low_suction_confirmed_opened_space_rotation_protected(
    position: Position,
    bar: Bar | None,
    params: BacktestParams,
) -> bool:
    if bar is None:
        return False
    decision = low_suction_confirmed_branch_decision(position, bar, params)
    return bool(decision.get("branch") == "opened_space" and not decision.get("triggered"))


def low_suction_confirmed_branch_sell_raw(position: Position, sell_reason: str) -> dict[str, Any]:
    if sell_reason not in {LOW_SUCTION_FAILED_FOLLOW_BRANCH_STOP, LOW_SUCTION_OPENED_SPACE_GIVEBACK_STOP}:
        return {}
    raw = position.low_suction_confirmed_branch_raw if isinstance(position.low_suction_confirmed_branch_raw, dict) else {}
    return {
        "low_suction_confirmed_branch": position.low_suction_confirmed_branch,
        "low_suction_confirmed_branch_decision": raw,
        "not_used_for_signal_score": True,
    }


def dynamic_failed_launch_exit_sell_raw(position: Position, bar: Bar, sell_reason: str) -> dict[str, Any]:
    if sell_reason != DYNAMIC_FAILED_LAUNCH_EXIT_STOP:
        return {}
    reason = position.reason if isinstance(position.reason, dict) else {}
    return {
        "dynamic_failed_launch_exit_decision": dynamic_failed_launch_exit_decision(position, bar, reason),
        "not_used_for_signal_score": True,
    }


def dynamic_failed_launch_exit_stop_applies(
    position: Position,
    bar: Bar,
    gain: float,
    high_gain: float,
    hold_soft_exit: bool,
    current_buy_signal: bool,
) -> bool:
    reason = position.reason if isinstance(position.reason, dict) else {}
    decision = dynamic_failed_launch_exit_decision(position, bar, reason)
    return bool(
        decision["triggered"]
        and not hold_soft_exit
        and not current_buy_signal
        and gain <= -0.02
        and high_gain < 0.025
    )


def dynamic_failed_launch_exit_decision(position: Position, bar: Bar, reason: dict[str, Any]) -> dict[str, Any]:
    """Classify a narrow, visible failed-launch path for default-off sell experiments."""

    setup = str(reason.get("entry_setup") or reason.get("setup_type") or "")
    visible_bars = int(position.visible_holding_bars or 0)
    cost_price = float(position.cost_price or 0)
    highest_price = float(position.highest_price or 0)
    visible_low_candidates = [value for value in [position.lowest_price, bar.low_price] if value is not None]
    lowest_price = float(min(visible_low_candidates) if visible_low_candidates else 0)
    high_return_pct = (highest_price / cost_price - 1) * 100 if cost_price and highest_price else 0.0
    low_return_pct = (lowest_price / cost_price - 1) * 100 if cost_price and lowest_price else 0.0
    close_return_pct = (bar.close_price / cost_price - 1) * 100 if cost_price and bar.close_price else 0.0
    support_price = _float_or_none(reason.get("support_price"))
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    min_ma = min(value for value in [ma10, ma20] if value is not None) if (ma10 is not None or ma20 is not None) else None
    failed_support = bool(support_price is not None and bar.close_price < support_price * 0.985)
    failed_ma = bool(min_ma is not None and bar.close_price < min_ma * 0.985)
    no_opened_space = high_return_pct < 2.5
    weak_low_path = low_return_pct <= -3.0
    weak_close = close_return_pct <= -2.0
    within_early_window = 3 <= visible_bars <= 5
    supported_setup = setup in {"dragon_pullback", "stealth_low_suction"}
    triggered = bool(
        supported_setup
        and within_early_window
        and no_opened_space
        and weak_low_path
        and weak_close
        and (failed_support or failed_ma)
    )
    notes: list[str] = []
    if not supported_setup:
        notes.append("unsupported_setup")
    if not within_early_window:
        notes.append("outside_early_window")
    if not no_opened_space:
        notes.append("opened_space")
    if not weak_low_path:
        notes.append("low_path_not_weak")
    if not weak_close:
        notes.append("close_not_weak")
    if not (failed_support or failed_ma):
        notes.append("support_or_ma_not_failed")
    return {
        "triggered": triggered,
        "reason": DYNAMIC_FAILED_LAUNCH_EXIT_STOP if triggered else None,
        "label": "买后真失败启动动态撤退" if triggered else "未触发动态失败启动撤退",
        "entry_setup": setup,
        "visible_holding_bars": visible_bars,
        "high_return_pct": round(high_return_pct, 4),
        "low_return_pct": round(low_return_pct, 4),
        "close_return_pct": round(close_return_pct, 4),
        "failed_support": failed_support,
        "failed_ma": failed_ma,
        "notes": notes,
        "not_used_for_signal_score": True,
    }


def failed_launch_exit_stop_applies(
    position: Position,
    bar: Bar,
    gain: float,
    high_gain: float,
    hold_soft_exit: bool,
) -> bool:
    reason = position.reason if isinstance(position.reason, dict) else {}
    return _failed_launch_exit_conditions_met(
        visible_holding_bars=position.visible_holding_bars,
        reason=reason,
        bar=bar,
        gain=gain,
        high_gain=high_gain,
        hold_soft_exit=hold_soft_exit,
    )


def contextual_failed_launch_exit_preflight_applies(position: Position, bar: Bar) -> bool:
    cost_price = position.cost_price
    if not cost_price:
        return False
    projected_highest_price = max(position.highest_price, bar.high_price)
    gain = bar.close_price / cost_price - 1
    high_gain = projected_highest_price / cost_price - 1 if projected_highest_price else 0
    hold_context = dragon_pullback_hold_context(position, bar)
    hold_soft_exit = hold_context["low_base_accumulation"] or (
        hold_context["ma_support_pullback"] and hold_context["price_volume_sync"]
    )
    reason = position.reason if isinstance(position.reason, dict) else {}
    return _failed_launch_exit_conditions_met(
        visible_holding_bars=position.visible_holding_bars + 1,
        reason=reason,
        bar=bar,
        gain=gain,
        high_gain=high_gain,
        hold_soft_exit=hold_soft_exit,
    )


def _failed_launch_exit_conditions_met(
    *,
    visible_holding_bars: int,
    reason: dict[str, Any],
    bar: Bar,
    gain: float,
    high_gain: float,
    hold_soft_exit: bool,
) -> bool:
    if visible_holding_bars < 3 or hold_soft_exit:
        return False
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


def contextual_failed_launch_exit_stop_applies(
    position: Position,
    bar: Bar,
    gain: float,
    high_gain: float,
    hold_soft_exit: bool,
    replacement_available: bool,
) -> bool:
    if not replacement_available:
        return False
    return failed_launch_exit_stop_applies(position, bar, gain, high_gain, hold_soft_exit)


def should_delay_contextual_support_reclaim(
    *,
    exit_reason: str,
    position: Position,
    bar: Bar,
    params: BacktestParams,
    replacement_score_gap: float | None,
) -> dict[str, Any]:
    """Return whether a support stop should wait one close for reclaim."""

    if exit_reason != "support_stop":
        return {"delay": False, "notes": []}
    if bar.close_price <= position.cost_price * (1 - params.stop_loss_pct - 0.02):
        return {"delay": False, "notes": ["破位超过硬止损缓冲"]}
    high_gain = position.highest_price / position.cost_price - 1 if position.cost_price and position.highest_price else 0.0
    if high_gain < 0:
        return {"delay": False, "notes": ["持仓路径没有可见正浮盈"]}
    range_pct = (bar.high_price / bar.low_price - 1) * 100 if bar.low_price else 0.0
    if range_pct < params.support_reclaim_delay_min_sell_day_range_pct:
        return {"delay": False, "notes": ["卖出日振幅不足，不像恐慌洗盘"]}
    if replacement_score_gap is not None and replacement_score_gap > params.support_reclaim_delay_max_replacement_score_gap:
        return {"delay": False, "notes": ["存在更强替换候选"]}
    reason = position.reason if isinstance(position.reason, dict) else {}
    warning = _float_or_none(reason.get("market_warning_level")) or 0
    regime = str(reason.get("dynamic_market_regime") or "")
    if warning > params.support_reclaim_delay_max_warning_level and regime not in {"mainline_pullback", "choppy_rotation"}:
        return {"delay": False, "notes": ["市场风险过高"]}
    if reason.get("high_level_sideways_distribution_risk") or reason.get("volume_stall_risk"):
        return {"delay": False, "notes": ["存在高位派发或放量滞涨风险"]}
    return {
        "delay": True,
        "notes": ["支撑止损疑似恐慌洗盘，且无明显更强替换候选，等待一次支撑收复"],
        "not_used_for_signal_score": True,
    }


def support_reclaim_delay_recovered(position: Position, bar: Bar, params: BacktestParams) -> bool:
    del params
    reason = position.reason if isinstance(position.reason, dict) else {}
    support = _float_or_none(reason.get("support_price"))
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    reclaimed_support = bool(support is not None and bar.close_price >= support * 0.99)
    reclaimed_ma10 = bool(ma10 is not None and bar.close_price >= ma10 * 0.99)
    held_ma20 = bool(ma20 is not None and bar.close_price >= ma20 * 0.99)
    return reclaimed_support or reclaimed_ma10 or held_ma20


def should_trigger_contextual_peak_giveback_stop(
    *,
    highest_return_pct: float,
    current_return_pct: float,
    holding_days: int,
    has_current_buy_or_hold_signal: bool,
    market_warning_level: float | int,
    support_reclaim_failed: bool,
    distribution_risk: bool,
    min_high_gain_pct: float = 0.12,
    max_current_gain_pct: float = 0.03,
    drawdown_pct: float = 0.07,
    min_holding_days: int = 5,
) -> dict[str, Any]:
    """Return a research-only peak-giveback exit decision."""

    giveback = float(highest_return_pct or 0) - float(current_return_pct or 0)
    trigger = bool(
        holding_days >= min_holding_days
        and highest_return_pct >= min_high_gain_pct
        and current_return_pct <= max_current_gain_pct
        and giveback >= drawdown_pct
        and not has_current_buy_or_hold_signal
        and (support_reclaim_failed or distribution_risk or float(market_warning_level or 0) >= 3)
    )
    return {
        "trigger": trigger,
        "reason": "contextual_peak_giveback_stop" if trigger else None,
        "giveback_from_peak_pct": giveback,
        "not_used_for_signal_score": True,
    }


def peak_giveback_support_reclaim_failed(position: Position, bar: Bar) -> bool:
    reason = position.reason if isinstance(position.reason, dict) else {}
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    support = _float_or_none(reason.get("support_price"))
    failed_support = bool(support is not None and bar.close_price < support * 0.99)
    failed_ma = bool(ma10 is not None and bar.close_price < ma10 * 0.985)
    failed_mid_ma = bool(ma20 is not None and bar.close_price < ma20 * 0.99)
    return failed_support or failed_ma or failed_mid_ma


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


def _iso_date(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
