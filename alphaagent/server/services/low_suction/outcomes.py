"""Fixed daily proxy outcomes with T+1 and real cash costs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pandas as pd

from alphaagent.server.services.execution import cash_ledger

DAILY_PROXY_EXIT_OFFSETS = {
    "entry_plus_1_close": 1,
    "entry_plus_3_close": 3,
    "entry_plus_5_close": 5,
}

COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_BPS = 10.0
LOT_SIZE = 100

EVENT_COLUMNS = ("event_id", "vt_symbol", "trade_date", "evidence_level")
BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "close_price",
    "high_price",
    "low_price",
    "limit_up_price",
    "limit_down_price",
    "suspended",
)


def generate_daily_proxy_outcomes(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    initial_cash: float = 100_000.0,
    cost_multiplier: float = 1.0,
) -> pd.DataFrame:
    """Enter on the first session after D and evaluate fixed legal exits."""

    _validate_inputs(events, bars, trading_dates, initial_cash, cost_multiplier)
    if events.empty:
        return _empty_outcomes()

    event_frame = events.copy()
    event_frame["trade_date"] = pd.to_datetime(
        event_frame["trade_date"], errors="raise"
    ).dt.normalize()
    bar_frame = bars.copy()
    bar_frame["trade_date"] = pd.to_datetime(
        bar_frame["trade_date"], errors="raise"
    ).dt.normalize()
    if bar_frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("bar vt_symbol/trade_date rows must be unique")
    bar_index = bar_frame.set_index(["vt_symbol", "trade_date"], drop=False)
    calendar = pd.DatetimeIndex(pd.to_datetime(list(trading_dates), errors="raise"))
    calendar = calendar.normalize().drop_duplicates().sort_values()

    rows: list[dict[str, Any]] = []
    for event in event_frame.sort_values(["trade_date", "event_id"]).to_dict("records"):
        rows.extend(
            _event_outcomes(
                event,
                bar_index,
                calendar,
                initial_cash=initial_cash,
                cost_multiplier=cost_multiplier,
            )
        )
    return pd.DataFrame(rows, columns=_empty_outcomes().columns)


def _event_outcomes(
    event: dict[str, Any],
    bar_index: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    initial_cash: float,
    cost_multiplier: float,
) -> list[dict[str, Any]]:
    signal_date = pd.Timestamp(event["trade_date"])
    later_sessions = calendar[calendar > signal_date]
    if later_sessions.empty:
        return _status_rows(event, None, calendar, "rejected", "missing_entry_session")
    entry_date = later_sessions[0]
    entry_key = (str(event["vt_symbol"]), entry_date)
    if entry_key not in bar_index.index:
        return _status_rows(event, entry_date, calendar, "rejected", "missing_entry_bar")

    entry_bar = bar_index.loc[entry_key]
    rejection = _entry_rejection(entry_bar)
    if rejection:
        return _status_rows(event, entry_date, calendar, "rejected", rejection)

    buy = cash_ledger.calculate_buy_execution(
        raw_price=float(entry_bar["open_price"]),
        cash=initial_cash,
        target_cash=initial_cash,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        lot_size=LOT_SIZE,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
        max_price=float(entry_bar["limit_up_price"]),
    )
    if buy.volume <= 0:
        return _status_rows(event, entry_date, calendar, "rejected", "insufficient_cash")

    entry_position = int(calendar.get_loc(entry_date))
    outcomes: list[dict[str, Any]] = []
    for exit_key, offset in DAILY_PROXY_EXIT_OFFSETS.items():
        exit_position = entry_position + offset
        exit_date = calendar[exit_position] if exit_position < len(calendar) else None
        base = _base_row(event, exit_key, entry_date, exit_date)
        base.update(
            {
                "entry_price_raw": float(entry_bar["open_price"]),
                "entry_price": buy.price,
                "volume": buy.volume,
                "buy_fee": buy.fee,
                "cost_multiplier": cost_multiplier,
            }
        )
        if exit_date is None:
            outcomes.append(_unclosed(base, "missing_exit_session"))
            continue
        exit_bar_key = (str(event["vt_symbol"]), exit_date)
        if exit_bar_key not in bar_index.index:
            outcomes.append(_unclosed(base, "missing_exit_bar"))
            continue
        exit_bar = bar_index.loc[exit_bar_key]
        exit_rejection = _exit_rejection(exit_bar)
        if exit_rejection:
            outcomes.append(_unclosed(base, exit_rejection))
            continue

        sell = cash_ledger.calculate_sell_execution(
            raw_price=float(exit_bar["close_price"]),
            volume=buy.volume,
            cost_price=buy.price,
            commission_rate=COMMISSION_RATE * cost_multiplier,
            stamp_tax_rate=STAMP_TAX_RATE * cost_multiplier,
            slippage_bps=SLIPPAGE_BPS * cost_multiplier,
            minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
            transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
            min_price=float(exit_bar["limit_down_price"]),
        )
        final_cash = buy.cash_after + sell.cash_delta
        base.update(
            {
                "status": "closed",
                "reason": None,
                "exit_price_raw": float(exit_bar["close_price"]),
                "exit_price": sell.price,
                "sell_fee": sell.fee,
                "total_fees": buy.fee + sell.fee,
                "gross_return_pct": (
                    float(exit_bar["close_price"]) / float(entry_bar["open_price"]) - 1.0
                )
                * 100.0,
                "net_return_pct": (final_cash / initial_cash - 1.0) * 100.0,
            }
        )
        outcomes.append(base)
    return outcomes


def _entry_rejection(bar: pd.Series) -> str | None:
    if bool(bar["suspended"]):
        return "entry_suspended"
    open_price = float(bar["open_price"])
    if open_price <= 0:
        return "invalid_entry_price"
    if open_price >= float(bar["limit_up_price"]):
        return "entry_at_limit_up"
    return None


def _exit_rejection(bar: pd.Series) -> str | None:
    if bool(bar["suspended"]):
        return "exit_suspended"
    close_price = float(bar["close_price"])
    limit_down = float(bar["limit_down_price"])
    if close_price <= 0:
        return "invalid_exit_price"
    if close_price <= limit_down and float(bar["high_price"]) <= limit_down:
        return "exit_at_limit_down"
    return None


def _status_rows(
    event: dict[str, Any],
    entry_date: pd.Timestamp | None,
    calendar: pd.DatetimeIndex,
    status: str,
    reason: str,
) -> list[dict[str, Any]]:
    entry_position = (
        int(calendar.get_loc(entry_date)) if entry_date is not None and entry_date in calendar else -1
    )
    rows = []
    for exit_key, offset in DAILY_PROXY_EXIT_OFFSETS.items():
        position = entry_position + offset
        exit_date = calendar[position] if entry_position >= 0 and position < len(calendar) else None
        row = _base_row(event, exit_key, entry_date, exit_date)
        row.update({"status": status, "reason": reason})
        rows.append(row)
    return rows


def _base_row(
    event: dict[str, Any],
    exit_key: str,
    entry_date: pd.Timestamp | None,
    exit_date: pd.Timestamp | None,
) -> dict[str, Any]:
    return {
        "event_id": str(event["event_id"]),
        "vt_symbol": str(event["vt_symbol"]),
        "signal_date": pd.Timestamp(event["trade_date"]),
        "evidence_level": str(event["evidence_level"]),
        "exit_key": exit_key,
        "entry_date": entry_date,
        "exit_date": exit_date,
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
        "gross_return_pct": None,
        "net_return_pct": None,
        "cost_multiplier": None,
    }


def _unclosed(base: dict[str, Any], reason: str) -> dict[str, Any]:
    row = dict(base)
    row.update({"status": "unclosed", "reason": reason})
    return row


def _validate_inputs(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    trading_dates: Sequence[date],
    initial_cash: float,
    cost_multiplier: float,
) -> None:
    missing_events = [column for column in EVENT_COLUMNS if column not in events]
    if missing_events:
        raise ValueError(f"missing required event columns: {', '.join(missing_events)}")
    missing_bars = [column for column in BAR_COLUMNS if column not in bars]
    if missing_bars:
        raise ValueError(f"missing required bar columns: {', '.join(missing_bars)}")
    if not trading_dates:
        raise ValueError("trading_dates must not be empty")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if cost_multiplier <= 0:
        raise ValueError("cost_multiplier must be positive")


def _empty_outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "vt_symbol",
            "signal_date",
            "evidence_level",
            "exit_key",
            "entry_date",
            "exit_date",
            "status",
            "reason",
            "entry_price_raw",
            "entry_price",
            "exit_price_raw",
            "exit_price",
            "volume",
            "buy_fee",
            "sell_fee",
            "total_fees",
            "gross_return_pct",
            "net_return_pct",
            "cost_multiplier",
        ]
    )
