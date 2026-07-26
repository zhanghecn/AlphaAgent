"""Chronological cash-account simulation for limit-up candidates."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, median

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up.versions import CORE_AB_STRATEGY_VERSION

ACCOUNT_EXECUTION_VERSION = CORE_AB_STRATEGY_VERSION
SUPPORTED_EXIT_MODES = {"dynamic", "next_open", "next_close", "next_1430"}


@dataclass(frozen=True)
class CashBacktestConfig:
    initial_cash: float = 100_000.0
    max_positions: int = 4
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps: float = 10.0
    lot_size: int = 100

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        rates = (
            self.commission_rate,
            self.minimum_commission,
            self.stamp_tax_rate,
            self.transfer_fee_rate,
            self.slippage_bps,
        )
        if any(value < 0 for value in rates):
            raise ValueError("execution costs must be non-negative")


@dataclass(frozen=True)
class PreparedSignal:
    candidate: dict[str, object]
    vt_symbol: str
    entry_date: date
    result_date: date | None
    buy_time: str
    auction_entry: bool


@dataclass
class CashPosition:
    position_id: str
    candidate: dict[str, object]
    vt_symbol: str
    volume: int
    entry_date: date
    planned_exit_date: date
    buy_time: str
    buy_price: float
    buy_amount: float
    buy_fee: float
    cash_cost: float
    last_close: float
    planned_exit_mode: str
    uses_dynamic_exit: bool
    pending_exit: bool = False


@dataclass
class AccountState:
    cash: float
    positions: dict[str, CashPosition]
    orders: list[dict[str, object]]
    closed_trades: list[dict[str, object]]
    total_fees: float = 0.0


def calculate_round_trip_outcome(
    entry_price: float,
    exit_price: float,
    *,
    limit_price: float | None,
    cost_multiplier: float = 1.0,
    position_cash: float = 50_000.0,
) -> dict[str, float] | None:
    """Price one independent A-share slot with the formal fee contract."""

    multiplier = max(float(cost_multiplier), 0.0)
    config = CashBacktestConfig(
        max_positions=2,
        commission_rate=0.0003 * multiplier,
        minimum_commission=5.0 * multiplier,
        stamp_tax_rate=0.0005 * multiplier,
        transfer_fee_rate=0.00001 * multiplier,
        slippage_bps=10.0 * multiplier,
    )
    buy = cash_ledger.calculate_buy_execution(
        raw_price=entry_price,
        cash=position_cash,
        target_cash=position_cash,
        commission_rate=config.commission_rate,
        slippage_bps=config.slippage_bps,
        lot_size=config.lot_size,
        minimum_commission=config.minimum_commission,
        transfer_fee_rate=config.transfer_fee_rate,
        max_price=limit_price,
    )
    if buy.volume <= 0:
        return None
    sell = cash_ledger.calculate_sell_execution(
        raw_price=exit_price,
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=config.commission_rate,
        stamp_tax_rate=config.stamp_tax_rate,
        slippage_bps=config.slippage_bps,
        minimum_commission=config.minimum_commission,
        transfer_fee_rate=config.transfer_fee_rate,
    )
    cash_cost = buy.amount + buy.fee
    return {
        "entry_price": round(buy.price, 6),
        "exit_price": round(sell.price, 6),
        "net_return_pct": round((sell.cash_delta / cash_cost - 1.0) * 100.0, 10),
    }


def simulate_limit_up_account(
    signals: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date | str],
    exit_mode: str,
    config: CashBacktestConfig | None = None,
) -> dict[str, object]:
    """Replay selected signals without leverage or same-time cash reuse."""

    if exit_mode not in SUPPORTED_EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    account_config = config or CashBacktestConfig()
    prepared = [_prepare_signal(signal) for signal in signals]
    bar_index = _bar_index(bars)
    calendar = _simulation_calendar(prepared, bars, trade_dates)
    prepared = [_resolve_result_date(signal, calendar) for signal in prepared]
    entries = _group_entries(prepared)
    state = AccountState(
        cash=account_config.initial_cash,
        positions={},
        orders=[],
        closed_trades=[],
    )
    equity_curve: list[dict[str, object]] = []
    previous_equity = account_config.initial_cash
    peak_equity = account_config.initial_cash
    last_entry_date = max((signal.entry_date for signal in prepared), default=None)

    for current_date in calendar:
        if (
            last_entry_date is not None
            and current_date > last_entry_date
            and not state.positions
            and not _has_entries_on_or_after(entries, current_date)
        ):
            break
        day_target_cash = previous_equity / account_config.max_positions
        day_signals = entries.get(current_date, [])
        auction_signals = [signal for signal in day_signals if signal.auction_entry]
        intraday_signals = [signal for signal in day_signals if not signal.auction_entry]

        _process_entries(
            state,
            auction_signals,
            bar_index,
            day_target_cash,
            account_config,
            exit_mode,
        )
        _process_open_exits(
            state,
            current_date,
            bar_index,
            exit_mode,
            account_config,
        )
        _process_entries(
            state,
            intraday_signals,
            bar_index,
            day_target_cash,
            account_config,
            exit_mode,
        )
        _process_close_exits(
            state,
            current_date,
            bar_index,
            exit_mode,
            account_config,
        )

        market_value = _mark_positions(state.positions, current_date, bar_index)
        total_equity = state.cash + market_value
        peak_equity = max(peak_equity, total_equity)
        equity_curve.append(
            _equity_row(
                current_date=current_date,
                state=state,
                market_value=market_value,
                total_equity=total_equity,
                previous_equity=previous_equity,
                peak_equity=peak_equity,
                initial_cash=account_config.initial_cash,
            )
        )
        previous_equity = total_equity

    open_positions = _open_position_rows(state.positions)
    summary = _execution_summary(
        signals=prepared,
        state=state,
        equity_curve=equity_curve,
        config=account_config,
    )
    return {
        "account_config": asdict(account_config),
        "execution_version": ACCOUNT_EXECUTION_VERSION,
        "execution_summary": summary,
        "equity_curve": equity_curve,
        "orders": state.orders,
        "executed_trades": state.closed_trades,
        "skipped_orders": [
            order
            for order in state.orders
            if order.get("side") == "BUY" and order.get("status") == "skipped"
        ],
        "open_positions": open_positions,
        "execution_assumptions": {
            "cash_reuse": "after_fill_only",
            "same_auction_sale_cash_reuse": False,
            "lot_size": account_config.lot_size,
            "t_plus_one": True,
            "locked_limit_exit": "daily_bar_conservative_retry",
            "first_board_queue": "fill_proxy_without_l2",
            "exit_policy": "per_position" if exit_mode == "dynamic" else exit_mode,
        },
    }


def _prepare_signal(signal: Mapping[str, object]) -> PreparedSignal:
    candidate = dict(signal)
    vt_symbol = str(candidate.get("vt_symbol") or "").strip()
    if not vt_symbol:
        raise ValueError("signal vt_symbol is required")
    entry_date = _as_date(candidate.get("entry_date") or candidate.get("signal_date"))
    result_date = _optional_date(candidate.get("result_date") or candidate.get("exit_date"))
    if result_date is not None and result_date <= entry_date:
        raise ValueError("result_date must be after entry_date")
    buy_time = str(candidate.get("buy_time") or candidate.get("signal_time") or "09:30:00")
    lane = str(candidate.get("lane") or "")
    signal_kind = str(candidate.get("signal_kind") or "")
    auction_entry = signal_kind == "auction" or (
        lane != "first_board" and buy_time <= "09:30:00"
    )
    return PreparedSignal(
        candidate=candidate,
        vt_symbol=vt_symbol,
        entry_date=entry_date,
        result_date=result_date,
        buy_time=buy_time,
        auction_entry=auction_entry,
    )


def _resolve_result_date(
    signal: PreparedSignal,
    calendar: Sequence[date],
) -> PreparedSignal:
    if signal.result_date is not None:
        return signal
    next_trade_date = next(
        (trade_date for trade_date in calendar if trade_date > signal.entry_date),
        None,
    )
    return replace(signal, result_date=next_trade_date)


def _group_entries(
    signals: Sequence[PreparedSignal],
) -> dict[date, list[PreparedSignal]]:
    grouped: dict[date, list[PreparedSignal]] = defaultdict(list)
    for signal in signals:
        grouped[signal.entry_date].append(signal)
    for rows in grouped.values():
        rows.sort(key=_entry_sort_key)
    return dict(grouped)


def _entry_sort_key(signal: PreparedSignal) -> tuple[object, ...]:
    candidate = signal.candidate
    quality_order = 0 if candidate.get("two_to_three_quality_tier") == "A" else 1
    lane_priority = (
        0
        if str(candidate.get("lane") or "") in {"two_to_three", "high_board"}
        else 1
    )
    return (
        signal.buy_time,
        lane_priority,
        quality_order,
        -float(candidate.get("rank_score") or 0),
        int(candidate.get("lane_rank") or candidate.get("pool_rank") or 1_000_000),
        signal.vt_symbol,
    )


def _process_entries(
    state: AccountState,
    signals: Sequence[PreparedSignal],
    bar_index: Mapping[tuple[str, date], Mapping[str, object]],
    target_cash: float,
    config: CashBacktestConfig,
    exit_mode: str,
) -> None:
    for signal in signals:
        rejection = _entry_rejection_reason(state, signal, target_cash, config)
        if rejection is not None:
            state.orders.append(_skipped_buy_order(signal, rejection, state.cash))
            continue
        raw_price = _number(signal.candidate.get("entry_price"))
        if raw_price is None or raw_price <= 0:
            state.orders.append(_skipped_buy_order(signal, "invalid_entry_price", state.cash))
            continue
        limit_price = _number(signal.candidate.get("limit_price"))
        fill = cash_ledger.calculate_buy_execution(
            raw_price=raw_price,
            cash=state.cash,
            target_cash=target_cash,
            commission_rate=config.commission_rate,
            slippage_bps=config.slippage_bps,
            lot_size=config.lot_size,
            minimum_commission=config.minimum_commission,
            transfer_fee_rate=config.transfer_fee_rate,
            max_price=limit_price,
        )
        if fill.volume <= 0:
            reason = (
                "below_one_lot"
                if target_cash < fill.price * config.lot_size
                else "insufficient_cash"
            )
            state.orders.append(_skipped_buy_order(signal, reason, state.cash))
            continue
        _open_position(state, signal, fill, bar_index, exit_mode)


def _entry_rejection_reason(
    state: AccountState,
    signal: PreparedSignal,
    target_cash: float,
    config: CashBacktestConfig,
) -> str | None:
    if signal.vt_symbol in state.positions:
        return "duplicate_position"
    if len(state.positions) >= config.max_positions:
        return "position_limit"
    if state.cash <= 0 or target_cash <= 0:
        return "insufficient_cash"
    return None


def _open_position(
    state: AccountState,
    signal: PreparedSignal,
    fill: cash_ledger.BuyExecution,
    bar_index: Mapping[tuple[str, date], Mapping[str, object]],
    exit_mode: str,
) -> None:
    bar = bar_index.get((signal.vt_symbol, signal.entry_date)) or {}
    outcome = signal.candidate.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    close_price = (
        _number(bar.get("close_price"))
        or _number(outcome.get("entry_day_close_price"))
        or fill.price
    )
    cash_cost = fill.amount + fill.fee
    position = CashPosition(
        position_id=f"{signal.entry_date.isoformat()}:{signal.vt_symbol}",
        candidate=signal.candidate,
        vt_symbol=signal.vt_symbol,
        volume=fill.volume,
        entry_date=signal.entry_date,
        planned_exit_date=signal.result_date or date.max,
        buy_time=signal.buy_time,
        buy_price=fill.price,
        buy_amount=fill.amount,
        buy_fee=fill.fee,
        cash_cost=cash_cost,
        last_close=close_price,
        planned_exit_mode=_resolved_position_exit_mode(signal.candidate, exit_mode),
        uses_dynamic_exit=exit_mode == "dynamic",
    )
    state.positions[signal.vt_symbol] = position
    state.cash = fill.cash_after
    state.total_fees += fill.fee
    state.orders.append(
        {
            "order_id": f"{position.position_id}:BUY",
            "side": "BUY",
            "status": "filled",
            "reason": None,
            "vt_symbol": signal.vt_symbol,
            "name": signal.candidate.get("name"),
            "lane": signal.candidate.get("lane"),
            "trade_date": signal.entry_date.isoformat(),
            "trade_time": signal.buy_time,
            "raw_price": _number(signal.candidate.get("entry_price")),
            "price": fill.price,
            "volume": fill.volume,
            "amount": fill.amount,
            "fee": fill.fee,
            "cash_after": state.cash,
        }
    )


def _process_open_exits(
    state: AccountState,
    current_date: date,
    bar_index: Mapping[tuple[str, date], Mapping[str, object]],
    exit_mode: str,
    config: CashBacktestConfig,
) -> None:
    for position in list(state.positions.values()):
        planned_open = (
            current_date == position.planned_exit_date
            and position.planned_exit_mode == "next_open"
        )
        retry_open = current_date > position.planned_exit_date
        if not planned_open and not retry_open:
            continue
        bar = bar_index.get((position.vt_symbol, current_date))
        reason = (
            _planned_exit_reason(position, "open") if planned_open else "retry_open"
        )
        if not _try_exit(state, position, current_date, "09:30:00", bar, "open_price", reason, config):
            position.pending_exit = True


def _process_close_exits(
    state: AccountState,
    current_date: date,
    bar_index: Mapping[tuple[str, date], Mapping[str, object]],
    exit_mode: str,
    config: CashBacktestConfig,
) -> None:
    for position in list(state.positions.values()):
        planned_1430 = (
            current_date == position.planned_exit_date
            and position.planned_exit_mode == "next_1430"
        )
        planned_close = (
            current_date == position.planned_exit_date
            and position.planned_exit_mode == "next_close"
        )
        if not planned_1430 and not planned_close and not position.pending_exit:
            continue
        if current_date < position.planned_exit_date:
            continue
        bar = bar_index.get((position.vt_symbol, current_date))
        if planned_1430:
            if not _try_exit(
                state,
                position,
                current_date,
                "14:30:00",
                bar,
                "price_1430",
                "planned_1430",
                config,
                price_source_field="price_1430_source",
                missing_reason="exit_quote_missing",
            ):
                position.pending_exit = True
            continue
        if planned_close:
            reason = _planned_exit_reason(position, "close")
        elif current_date == position.planned_exit_date:
            reason = "emergency_close"
        else:
            reason = "retry_close"
        if not _try_exit(state, position, current_date, "15:00:00", bar, "close_price", reason, config):
            position.pending_exit = True


def _try_exit(
    state: AccountState,
    position: CashPosition,
    trade_date: date,
    trade_time: str,
    bar: Mapping[str, object] | None,
    price_field: str,
    exit_reason: str,
    config: CashBacktestConfig,
    *,
    price_source_field: str | None = None,
    missing_reason: str = "missing_market_data",
) -> bool:
    raw_price = _number((bar or {}).get(price_field))
    limit_down = _limit_down_price(position.last_close)
    if raw_price is None:
        _append_pending_sell(state, position, trade_date, trade_time, missing_reason)
        return False
    if raw_price <= limit_down + 1e-9:
        _append_pending_sell(state, position, trade_date, trade_time, "limit_down_locked")
        return False
    _close_position(
        state,
        position,
        trade_date,
        trade_time,
        raw_price,
        limit_down,
        exit_reason,
        config,
        exit_price_source=(
            str((bar or {}).get(price_source_field) or "") or None
            if price_source_field
            else "daily_open"
            if price_field == "open_price"
            else "daily_close"
        ),
    )
    return True


def _close_position(
    state: AccountState,
    position: CashPosition,
    trade_date: date,
    trade_time: str,
    raw_price: float,
    limit_down: float,
    exit_reason: str,
    config: CashBacktestConfig,
    *,
    exit_price_source: str | None,
) -> None:
    fill = cash_ledger.calculate_sell_execution(
        raw_price=raw_price,
        volume=position.volume,
        cost_price=position.buy_price,
        commission_rate=config.commission_rate,
        stamp_tax_rate=config.stamp_tax_rate,
        slippage_bps=config.slippage_bps,
        minimum_commission=config.minimum_commission,
        transfer_fee_rate=config.transfer_fee_rate,
        min_price=limit_down,
    )
    state.cash += fill.cash_delta
    state.total_fees += fill.fee
    net_pnl = fill.cash_delta - position.cash_cost
    return_pct = net_pnl / position.cash_cost * 100 if position.cash_cost else 0.0
    sell_order = {
        "order_id": f"{position.position_id}:SELL:{trade_date.isoformat()}:{trade_time}",
        "side": "SELL",
        "status": "filled",
        "reason": exit_reason,
        "vt_symbol": position.vt_symbol,
        "name": position.candidate.get("name"),
        "lane": position.candidate.get("lane"),
        "trade_date": trade_date.isoformat(),
        "trade_time": trade_time,
        "raw_price": raw_price,
        "price": fill.price,
        "volume": fill.volume,
        "amount": fill.amount,
        "fee": fill.fee,
        "price_source": exit_price_source,
        "price_proxy": exit_price_source == "daily_close_proxy",
        "cash_after": state.cash,
    }
    state.orders.append(sell_order)
    state.closed_trades.append(
        {
            **position.candidate,
            "entry_date": position.entry_date.isoformat(),
            "exit_date": trade_date.isoformat(),
            "entry_price": position.buy_price,
            "exit_price": fill.price,
            "buy_date": position.entry_date.isoformat(),
            "buy_time": position.buy_time,
            "buy_price": position.buy_price,
            "volume": position.volume,
            "buy_amount": position.buy_amount,
            "buy_fee": position.buy_fee,
            "sell_date": trade_date.isoformat(),
            "sell_time": trade_time,
            "sell_price": fill.price,
            "sell_amount": fill.amount,
            "sell_fee": fill.fee,
            "total_fee": position.buy_fee + fill.fee,
            "net_pnl": net_pnl,
            "return_pct": return_pct,
            "is_win": net_pnl > 0,
            "is_hard_loss": return_pct <= -5,
            "d1_outcome": _d1_outcome(return_pct, position.candidate),
            "d_board_status": _board_status(position.candidate),
            "exit_reason": exit_reason,
            "exit_price_source": exit_price_source,
            "exit_price_proxy": exit_price_source == "daily_close_proxy",
            "result_status": "closed",
        }
    )
    del state.positions[position.vt_symbol]


def _resolved_position_exit_mode(
    candidate: Mapping[str, object],
    exit_mode: str,
) -> str:
    if exit_mode != "dynamic":
        return exit_mode
    decision = candidate.get("dynamic_exit")
    decision = decision if isinstance(decision, Mapping) else {}
    return "next_open" if decision.get("mode") == "auction_exit" else "next_close"


def _planned_exit_reason(position: CashPosition, session: str) -> str:
    if position.uses_dynamic_exit:
        return "dynamic_auction_exit" if session == "open" else "dynamic_tail_exit"
    if position.planned_exit_mode == "next_1430":
        return "planned_1430"
    return "planned_open" if session == "open" else "planned_close"


def _append_pending_sell(
    state: AccountState,
    position: CashPosition,
    trade_date: date,
    trade_time: str,
    reason: str,
) -> None:
    state.orders.append(
        {
            "order_id": f"{position.position_id}:SELL:{trade_date.isoformat()}:{trade_time}",
            "side": "SELL",
            "status": "pending",
            "reason": reason,
            "vt_symbol": position.vt_symbol,
            "name": position.candidate.get("name"),
            "lane": position.candidate.get("lane"),
            "trade_date": trade_date.isoformat(),
            "trade_time": trade_time,
            "price": None,
            "volume": position.volume,
            "amount": None,
            "fee": None,
            "cash_after": state.cash,
        }
    )


def _skipped_buy_order(
    signal: PreparedSignal,
    reason: str,
    cash: float,
) -> dict[str, object]:
    candidate = signal.candidate
    outcome = candidate.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    next_close_return = _number(outcome.get("next_close_return_pct"))
    result_date_raw = candidate.get("result_date")
    return {
        "order_id": f"{signal.entry_date.isoformat()}:{signal.vt_symbol}:BUY",
        "side": "BUY",
        "status": "skipped",
        "reason": reason,
        "vt_symbol": signal.vt_symbol,
        "name": candidate.get("name"),
        "lane": candidate.get("lane"),
        "trade_date": signal.entry_date.isoformat(),
        "trade_time": signal.buy_time,
        "raw_price": _number(candidate.get("entry_price")),
        "price": None,
        "volume": 0,
        "amount": 0.0,
        "fee": 0.0,
        "cash_after": cash,
        # 反事实收益：如果当时按规则买入，次日（D+1）尾盘按官方收盘价卖出能赚多少。
        # 直接取候选自带的事后结果，口径与成交单一致（已扣双边费用和滑点）。
        "buy_price": _number(candidate.get("entry_price")),
        "result_date": result_date_raw.isoformat() if hasattr(result_date_raw, "isoformat") else (str(result_date_raw)[:10] or None),
        "d1_close_price": _number(outcome.get("next_close_price")),
        "d1_return_pct": next_close_return,
        "d_board_status": _skipped_board_status(outcome),
        "is_win": next_close_return is not None and next_close_return > 0,
    }


def _skipped_board_status(outcome: Mapping[str, object]) -> str | None:
    """把候选事后结果映射成与成交单一致的板上状态。"""
    if not outcome:
        return None
    if outcome.get("sealed"):
        return "sealed"
    if outcome.get("touched"):
        return "failed"
    return "no_limit"


def _mark_positions(
    positions: Mapping[str, CashPosition],
    current_date: date,
    bar_index: Mapping[tuple[str, date], Mapping[str, object]],
) -> float:
    market_value = 0.0
    for position in positions.values():
        bar = bar_index.get((position.vt_symbol, current_date)) or {}
        close_price = _number(bar.get("close_price"))
        if close_price is not None and close_price > 0:
            position.last_close = close_price
        market_value += position.last_close * position.volume
    return market_value


def _equity_row(
    *,
    current_date: date,
    state: AccountState,
    market_value: float,
    total_equity: float,
    previous_equity: float,
    peak_equity: float,
    initial_cash: float,
) -> dict[str, object]:
    daily_return = (total_equity / previous_equity - 1) * 100 if previous_equity else 0.0
    drawdown = (total_equity / peak_equity - 1) * 100 if peak_equity else 0.0
    closed_today = sum(
        str(trade.get("sell_date") or "") == current_date.isoformat()
        for trade in state.closed_trades
    )
    return {
        "result_date": current_date.isoformat(),
        "trade_count": closed_today,
        "cash": round(state.cash, 4),
        "market_value": round(market_value, 4),
        "total_equity": round(total_equity, 4),
        "position_count": len(state.positions),
        "utilization_pct": round(market_value / total_equity * 100, 4) if total_equity else 0.0,
        "daily_return_pct": round(daily_return, 4),
        "equity": round(total_equity / initial_cash, 6),
        "total_return_pct": round((total_equity / initial_cash - 1) * 100, 4),
        "drawdown_pct": round(drawdown, 4),
    }


def _execution_summary(
    *,
    signals: Sequence[PreparedSignal],
    state: AccountState,
    equity_curve: Sequence[Mapping[str, object]],
    config: CashBacktestConfig,
) -> dict[str, object]:
    trades = state.closed_trades
    returns = [float(trade["return_pct"]) for trade in trades]
    pnls = [float(trade["net_pnl"]) for trade in trades]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    buy_orders = [
        order
        for order in state.orders
        if order.get("side") == "BUY" and order.get("status") == "filled"
    ]
    skipped = [
        order
        for order in state.orders
        if order.get("side") == "BUY" and order.get("status") == "skipped"
    ]
    final_equity = (
        float(equity_curve[-1]["total_equity"])
        if equity_curve
        else config.initial_cash
    )
    utilizations = [float(row.get("utilization_pct") or 0) for row in equity_curve]
    drawdowns = [float(row.get("drawdown_pct") or 0) for row in equity_curve]
    trade_dates = {str(order.get("trade_date") or "") for order in buy_orders}
    return {
        "initial_cash": config.initial_cash,
        "final_equity": round(final_equity, 4),
        "signal_count": len(signals),
        "filled_count": len(buy_orders),
        "fill_rate": round(len(buy_orders) / len(signals) * 100, 4) if signals else None,
        "buy_count": len(buy_orders),
        "trade_count": len(trades),
        "open_position_count": len(state.positions),
        "skipped_count": len(skipped),
        "skipped_reasons": dict(Counter(str(order.get("reason") or "unknown") for order in skipped)),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(trades) * 100, 4) if trades else None,
        "average_return_pct": round(mean(returns), 4) if returns else None,
        "median_return_pct": round(median(returns), 4) if returns else None,
        "total_return_pct": round((final_equity / config.initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(min(drawdowns), 4) if drawdowns else 0.0,
        "hard_loss_count": sum(value <= -5 for value in returns),
        "hard_loss_rate": round(sum(value <= -5 for value in returns) / len(returns) * 100, 4) if returns else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        "total_fees": round(state.total_fees, 4),
        "average_utilization_pct": round(mean(utilizations), 4) if utilizations else 0.0,
        "peak_utilization_pct": round(max(utilizations), 4) if utilizations else 0.0,
        "trade_day_count": len(trade_dates),
        "average_trades_per_day": round(len(buy_orders) / len(trade_dates), 4) if trade_dates else 0.0,
        "max_trades_per_day": _max_orders_per_day(buy_orders),
        "max_industry_concentration_pct": _max_industry_concentration(trades),
        "seal_rate": _signal_seal_rate(signals),
    }


def _open_position_rows(
    positions: Mapping[str, CashPosition],
) -> list[dict[str, object]]:
    return [
        {
            **position.candidate,
            "buy_date": position.entry_date.isoformat(),
            "buy_time": position.buy_time,
            "buy_price": position.buy_price,
            "volume": position.volume,
            "buy_amount": position.buy_amount,
            "buy_fee": position.buy_fee,
            "cash_cost": position.cash_cost,
            "last_close": position.last_close,
            "market_value": position.last_close * position.volume,
            "unrealized_pnl": position.last_close * position.volume - position.cash_cost,
            "planned_exit_date": position.planned_exit_date.isoformat(),
            "pending_exit": position.pending_exit,
            "result_status": "open",
        }
        for position in sorted(positions.values(), key=lambda item: item.position_id)
    ]


def _bar_index(
    bars: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], dict[str, object]]:
    result: dict[tuple[str, date], dict[str, object]] = {}
    for raw_bar in bars:
        vt_symbol = str(raw_bar.get("vt_symbol") or "").strip()
        if not vt_symbol:
            continue
        trade_date = _as_date(raw_bar.get("trade_date"))
        result[(vt_symbol, trade_date)] = dict(raw_bar)
    return result


def _simulation_calendar(
    signals: Sequence[PreparedSignal],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date | str],
) -> list[date]:
    dates = {_as_date(value) for value in trade_dates}
    dates.update(signal.entry_date for signal in signals)
    dates.update(signal.result_date for signal in signals if signal.result_date is not None)
    dates.update(
        _as_date(bar.get("trade_date"))
        for bar in bars
        if bar.get("trade_date") is not None
    )
    first_entry = min((signal.entry_date for signal in signals), default=None)
    return sorted(value for value in dates if first_entry is None or value >= first_entry)


def _has_entries_on_or_after(
    entries: Mapping[date, Sequence[PreparedSignal]],
    current_date: date,
) -> bool:
    return any(trade_date >= current_date and rows for trade_date, rows in entries.items())


def _limit_down_price(previous_close: float) -> float:
    value = Decimal(str(previous_close)) * Decimal("0.90")
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _max_orders_per_day(orders: Sequence[Mapping[str, object]]) -> int:
    counts = Counter(str(order.get("trade_date") or "") for order in orders)
    return max(counts.values(), default=0)


def _max_industry_concentration(
    trades: Sequence[Mapping[str, object]],
) -> float | None:
    if not trades:
        return None
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get("buy_date") or trade.get("entry_date") or "")].append(trade)
    concentrations = []
    for rows in grouped.values():
        counts = Counter(
            str(row.get("industry_id") or row.get("industry_name") or "UNCLASSIFIED")
            for row in rows
        )
        concentrations.append(max(counts.values()) / len(rows) * 100)
    return round(max(concentrations), 4)


def _signal_seal_rate(signals: Sequence[PreparedSignal]) -> float | None:
    known = []
    for signal in signals:
        outcome = signal.candidate.get("outcome")
        if isinstance(outcome, Mapping) and outcome.get("sealed") is not None:
            known.append(bool(outcome.get("sealed")))
    return round(sum(known) / len(known) * 100, 4) if known else None


def _d1_outcome(
    return_pct: float,
    candidate: Mapping[str, object],
) -> str:
    outcome = candidate.get("outcome")
    sealed = bool(outcome.get("sealed")) if isinstance(outcome, Mapping) else False
    if return_pct >= 9:
        return "continuation_limit_up" if sealed else "next_limit_up_after_failed_board"
    if return_pct > 0:
        return "d1_premium"
    if return_pct <= -5:
        return "direct_breakdown"
    return "no_premium"


def _board_status(candidate: Mapping[str, object]) -> str:
    outcome = candidate.get("outcome")
    if not isinstance(outcome, Mapping):
        return "unknown"
    if outcome.get("sealed"):
        return "sealed"
    if outcome.get("touched"):
        return "failed"
    return "no_limit"


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("date value is required")
    return date.fromisoformat(str(value)[:10])


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    return _as_date(value)


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number
