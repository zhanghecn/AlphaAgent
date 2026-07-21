"""Cash-account simulation for the frozen leader MA5 structural exit."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from alphaagent.server.services.execution import cash_ledger

from .outcomes import (
    COMMISSION_RATE,
    LOT_SIZE,
    MINIMUM_COMMISSION,
    SLIPPAGE_BPS,
    STAMP_TAX_RATE,
    TRANSFER_FEE_RATE,
)


INITIAL_CASH = 100_000.0
CAPACITIES = (1, 2, 3, 4)

TRADE_COLUMNS = (
    "signal_id",
    "vt_symbol",
    "sector_id",
    "entry_date",
    "exit_date",
    "causal_rank",
)
BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
)
ENTRY_PRICE_OVERRIDE_COLUMN = "entry_price_raw_override"
EXIT_PRICE_MODE_COLUMN = "exit_price_mode"
EXIT_PRICE_MODES = frozenset({"close", "open"})


def simulate_structural_cash_account(
    trades: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    capacity: int,
    initial_cash: float = INITIAL_CASH,
) -> dict[str, Any]:
    """Run one fixed-capacity, no-leverage, mark-to-market cash account."""

    if capacity not in CAPACITIES:
        raise ValueError(f"capacity must be one of {CAPACITIES}")
    if initial_cash <= 0:
        raise ValueError("initial cash must be positive")
    trade_frame = _prepare_trades(trades)
    bar_frame = _prepare_bars(daily_bars)
    bar_index = {
        (str(row.vt_symbol), row.trade_date): row
        for row in bar_frame.itertuples(index=False)
    }
    calendar = tuple(sorted(bar_frame["trade_date"].unique()))
    entries = {
        trade_date: group.sort_values(
            ["causal_rank", "signal_id"],
            kind="stable",
        )
        for trade_date, group in trade_frame.groupby("entry_date", sort=True)
    }
    cash = float(initial_cash)
    minimum_cash = cash
    positions: dict[str, dict[str, Any]] = {}
    ledger: dict[str, dict[str, Any]] = {}
    equity_rows = [{"trade_date": None, "equity": cash, "cash": cash}]

    for trade_date in calendar:
        day_entries = entries.get(trade_date, _empty_trades())
        account_equity = (
            _closing_equity(cash, positions, bar_index, trade_date)
            if _uses_intraday_entry(day_entries)
            else _opening_equity(cash, positions, bar_index, trade_date)
        )
        target_cash = account_equity / capacity
        for trade in day_entries.to_dict("records"):
            cash = _attempt_entry(
                trade,
                trade_date=trade_date,
                cash=cash,
                target_cash=target_cash,
                capacity=capacity,
                positions=positions,
                ledger=ledger,
                bar_index=bar_index,
            )
            minimum_cash = min(minimum_cash, cash)
        cash = _attempt_due_exits(
            trade_date=trade_date,
            cash=cash,
            positions=positions,
            ledger=ledger,
            bar_index=bar_index,
        )
        minimum_cash = min(minimum_cash, cash)
        equity_rows.append(
            {
                "trade_date": trade_date,
                "equity": _closing_equity(cash, positions, bar_index, trade_date),
                "cash": cash,
            }
        )

    for signal_id, position in positions.items():
        ledger[signal_id].update(
            {
                "status": "unclosed",
                "reason": "missing_executable_exit_before_data_end",
                "exit_deferred_sessions": int(position["exit_deferred_sessions"]),
            }
        )
    records = [
        ledger[str(row.signal_id)]
        for row in trade_frame.itertuples(index=False)
    ]
    return _build_result(
        capacity=capacity,
        initial_cash=initial_cash,
        minimum_cash=minimum_cash,
        ledger=records,
        equity_rows=equity_rows,
    )


def simulate_capacity_comparison(
    trades: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Report all predeclared capacities without selecting a winner."""

    result = {}
    for capacity in CAPACITIES:
        simulation = simulate_structural_cash_account(
            trades,
            daily_bars,
            capacity=capacity,
        )
        result[f"capacity_{capacity}"] = {
            key: value
            for key, value in simulation.items()
            if key not in {"trade_ledger", "equity_curve"}
        }
    return result


def _attempt_entry(
    trade: dict[str, Any],
    *,
    trade_date: Any,
    cash: float,
    target_cash: float,
    capacity: int,
    positions: dict[str, dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
    bar_index: dict[tuple[str, Any], Any],
) -> float:
    signal_id = str(trade["signal_id"])
    base = _base_ledger_row(trade)
    active_sectors = {str(position["sector_id"]) for position in positions.values()}
    if str(trade["sector_id"]) in active_sectors:
        ledger[signal_id] = _finished(base, "skipped", "same_concept_position")
        return cash
    if len(positions) >= capacity:
        ledger[signal_id] = _finished(base, "skipped", "capacity_full")
        return cash
    bar = bar_index.get((str(trade["vt_symbol"]), trade_date))
    previous = _previous_bar(bar_index, str(trade["vt_symbol"]), trade_date)
    if bar is None or previous is None:
        ledger[signal_id] = _finished(base, "rejected", "missing_entry_bar")
        return cash
    override = trade.get(ENTRY_PRICE_OVERRIDE_COLUMN)
    entry_open = (
        float(override)
        if override is not None and not pd.isna(override)
        else float(bar.open_price)
    )
    limit_up = _limit_price(float(previous.close_price), 1.10)
    if entry_open <= 0:
        ledger[signal_id] = _finished(base, "rejected", "invalid_entry_price")
        return cash
    if entry_open >= limit_up:
        ledger[signal_id] = _finished(
            base,
            "rejected",
            "entry_limit_up_queue_unknown_without_l2",
        )
        return cash
    buy = cash_ledger.calculate_buy_execution(
        raw_price=entry_open,
        cash=cash,
        target_cash=target_cash,
        commission_rate=COMMISSION_RATE,
        slippage_bps=SLIPPAGE_BPS,
        lot_size=LOT_SIZE,
        minimum_commission=MINIMUM_COMMISSION,
        transfer_fee_rate=TRANSFER_FEE_RATE,
        max_price=limit_up,
    )
    if buy.volume <= 0:
        ledger[signal_id] = _finished(base, "rejected", "insufficient_cash")
        return cash
    position = {
        **trade,
        "buy": buy,
        "exit_deferred_sessions": 0,
    }
    positions[signal_id] = position
    base.update(
        {
            "status": "open",
            "entry_price_raw": entry_open,
            "entry_price": buy.price,
            "volume": buy.volume,
            "buy_fee": buy.fee,
        }
    )
    ledger[signal_id] = base
    return buy.cash_after


def _attempt_due_exits(
    *,
    trade_date: Any,
    cash: float,
    positions: dict[str, dict[str, Any]],
    ledger: dict[str, dict[str, Any]],
    bar_index: dict[tuple[str, Any], Any],
) -> float:
    due_ids = [
        signal_id
        for signal_id, position in positions.items()
        if position["exit_date"] <= trade_date
    ]
    for signal_id in sorted(due_ids):
        position = positions[signal_id]
        symbol = str(position["vt_symbol"])
        bar = bar_index.get((symbol, trade_date))
        previous = _previous_bar(bar_index, symbol, trade_date)
        if bar is None or previous is None:
            position["exit_deferred_sessions"] += 1
            continue
        limit_down = _limit_price(float(previous.close_price), 0.90)
        exit_mode = str(position.get(EXIT_PRICE_MODE_COLUMN) or "close")
        raw_exit_price = float(
            bar.open_price if exit_mode == "open" else bar.close_price
        )
        blocked_at_limit_down = (
            raw_exit_price <= limit_down
            if exit_mode == "open"
            else float(bar.close_price) <= limit_down
            and float(bar.high_price) <= limit_down
        )
        if blocked_at_limit_down:
            position["exit_deferred_sessions"] += 1
            continue
        buy = position["buy"]
        sell = cash_ledger.calculate_sell_execution(
            raw_price=raw_exit_price,
            volume=int(buy.volume),
            cost_price=float(buy.price),
            commission_rate=COMMISSION_RATE,
            stamp_tax_rate=STAMP_TAX_RATE,
            slippage_bps=SLIPPAGE_BPS,
            minimum_commission=MINIMUM_COMMISSION,
            transfer_fee_rate=TRANSFER_FEE_RATE,
            min_price=limit_down,
        )
        cash += sell.cash_delta
        invested_cash = -float(buy.cash_delta)
        pnl = float(sell.cash_delta + buy.cash_delta)
        ledger[signal_id].update(
            {
                "status": "closed",
                "reason": None,
                "actual_exit_date": trade_date,
                "exit_deferred_sessions": int(position["exit_deferred_sessions"]),
                "exit_price_raw": raw_exit_price,
                "exit_price": sell.price,
                "sell_fee": sell.fee,
                "total_fees": float(buy.fee + sell.fee),
                "pnl": pnl,
                "net_return_pct": pnl / invested_cash * 100.0,
            }
        )
        del positions[signal_id]
    return cash


def _build_result(
    *,
    capacity: int,
    initial_cash: float,
    minimum_cash: float,
    ledger: list[dict[str, Any]],
    equity_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    equity = pd.Series([float(row["equity"]) for row in equity_rows])
    drawdown = equity / equity.cummax() - 1.0
    closed = [row for row in ledger if row["status"] == "closed"]
    statuses = Counter(str(row["status"]) for row in ledger)
    reasons = Counter(
        str(row["reason"])
        for row in ledger
        if row.get("reason") is not None
    )
    final_equity = float(equity.iloc[-1])
    wins = sum(float(row.get("pnl") or 0.0) > 0 for row in closed)
    return {
        "capacity": capacity,
        "initial_cash": float(initial_cash),
        "final_equity": final_equity,
        "compound_return_pct": (final_equity / initial_cash - 1.0) * 100.0,
        "maximum_drawdown_pct": float(drawdown.min() * 100.0),
        "minimum_cash": float(minimum_cash),
        "signals": len(ledger),
        "accepted_entries": int(statuses["closed"] + statuses["open"] + statuses["unclosed"]),
        "closed_trades": len(closed),
        "winning_trades": wins,
        "cash_win_rate_pct": wins / len(closed) * 100.0 if closed else None,
        "skipped_entries": int(statuses["skipped"]),
        "rejected_entries": int(statuses["rejected"]),
        "unclosed_trades": int(statuses["unclosed"]),
        "total_fees": float(sum(float(row.get("total_fees") or 0.0) for row in ledger)),
        "status_counts": dict(sorted(statuses.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "trade_ledger": ledger,
        "equity_curve": equity_rows,
    }


def _opening_equity(
    cash: float,
    positions: dict[str, dict[str, Any]],
    bar_index: dict[tuple[str, Any], Any],
    trade_date: Any,
) -> float:
    return cash + sum(
        int(position["buy"].volume)
        * _position_price(position, bar_index, trade_date, "open_price")
        for position in positions.values()
    )


def _closing_equity(
    cash: float,
    positions: dict[str, dict[str, Any]],
    bar_index: dict[tuple[str, Any], Any],
    trade_date: Any,
) -> float:
    return cash + sum(
        int(position["buy"].volume)
        * _position_price(position, bar_index, trade_date, "close_price")
        for position in positions.values()
    )


def _position_price(
    position: dict[str, Any],
    bar_index: dict[tuple[str, Any], Any],
    trade_date: Any,
    column: str,
) -> float:
    symbol = str(position["vt_symbol"])
    bar = bar_index.get((symbol, trade_date))
    if bar is not None:
        return float(getattr(bar, column))
    previous = _previous_bar(bar_index, symbol, trade_date)
    if previous is None:
        raise ValueError(
            f"missing mark-to-market bar for {position['vt_symbol']} on {trade_date}"
        )
    return float(previous.close_price)


def _previous_bar(
    bar_index: dict[tuple[str, Any], Any],
    symbol: str,
    trade_date: Any,
) -> Any | None:
    dates = sorted(
        date_value
        for (bar_symbol, date_value) in bar_index
        if bar_symbol == symbol and date_value < trade_date
    )
    return bar_index.get((symbol, dates[-1])) if dates else None


def _prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    _require_columns(trades, TRADE_COLUMNS, "leader MA5 structural trade")
    columns = list(TRADE_COLUMNS)
    columns.extend(
        column
        for column in (ENTRY_PRICE_OVERRIDE_COLUMN, EXIT_PRICE_MODE_COLUMN)
        if column in trades
    )
    frame = trades.loc[:, columns].copy()
    frame["signal_id"] = frame["signal_id"].astype(str)
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["sector_id"] = frame["sector_id"].astype(str)
    for column in ("entry_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.date
    frame["causal_rank"] = pd.to_numeric(
        frame["causal_rank"],
        errors="raise",
    ).astype(int)
    if ENTRY_PRICE_OVERRIDE_COLUMN in frame:
        frame[ENTRY_PRICE_OVERRIDE_COLUMN] = pd.to_numeric(
            frame[ENTRY_PRICE_OVERRIDE_COLUMN],
            errors="raise",
        )
        invalid_override = frame[ENTRY_PRICE_OVERRIDE_COLUMN].notna() & frame[
            ENTRY_PRICE_OVERRIDE_COLUMN
        ].le(0)
        if invalid_override.any():
            raise ValueError("intraday entry price overrides must be positive")
    if EXIT_PRICE_MODE_COLUMN in frame:
        frame[EXIT_PRICE_MODE_COLUMN] = frame[EXIT_PRICE_MODE_COLUMN].astype(str)
        invalid_modes = ~frame[EXIT_PRICE_MODE_COLUMN].isin(EXIT_PRICE_MODES)
        if invalid_modes.any():
            raise ValueError("exit price mode must be open or close")
    if frame["signal_id"].duplicated().any():
        raise ValueError("leader MA5 structural signal IDs must be unique")
    if (frame["exit_date"] < frame["entry_date"]).any():
        raise ValueError("structural exit cannot precede entry")
    return frame.sort_values(
        ["entry_date", "causal_rank", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def _prepare_bars(daily_bars: pd.DataFrame) -> pd.DataFrame:
    _require_columns(daily_bars, BAR_COLUMNS, "leader MA5 cash daily bar")
    frame = daily_bars.loc[:, list(BAR_COLUMNS)].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"],
        errors="raise",
    ).dt.date
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("leader MA5 cash daily bar identities must be unique")
    for column in BAR_COLUMNS[2:]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    coherent = (
        frame["low_price"].le(frame[["open_price", "close_price"]].min(axis=1))
        & frame["high_price"].ge(frame[["open_price", "close_price"]].max(axis=1))
        & frame["low_price"].gt(0)
    )
    if not coherent.all():
        raise ValueError("leader MA5 cash daily OHLC values are incoherent")
    return frame.sort_values(
        ["trade_date", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def _base_ledger_row(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": str(trade["signal_id"]),
        "vt_symbol": str(trade["vt_symbol"]),
        "sector_id": str(trade["sector_id"]),
        "causal_rank": int(trade["causal_rank"]),
        "entry_date": trade["entry_date"],
        "planned_exit_date": trade["exit_date"],
        "exit_price_mode": str(trade.get(EXIT_PRICE_MODE_COLUMN) or "close"),
        "actual_exit_date": None,
        "exit_deferred_sessions": 0,
        "status": None,
        "reason": None,
        "entry_price_raw": None,
        "entry_price": None,
        "exit_price_raw": None,
        "exit_price": None,
        "volume": 0,
        "buy_fee": None,
        "sell_fee": None,
        "total_fees": None,
        "pnl": None,
        "net_return_pct": None,
    }


def _finished(base: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    row = dict(base)
    row.update({"status": status, "reason": reason})
    return row


def _limit_price(previous_close: float, multiplier: float) -> float:
    value = Decimal(str(previous_close)) * Decimal(str(multiplier))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLUMNS)


def _uses_intraday_entry(day_entries: pd.DataFrame) -> bool:
    return (
        ENTRY_PRICE_OVERRIDE_COLUMN in day_entries
        and day_entries[ENTRY_PRICE_OVERRIDE_COLUMN].notna().any()
    )
