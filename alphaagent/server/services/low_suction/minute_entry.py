"""Executable one-minute entry and fixed-exit outcomes for strict research."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.server.services.execution import cash_ledger

SHANGHAI = ZoneInfo("Asia/Shanghai")
ENTRY_SIGNAL_CUTOFF = time(14, 55)
MORNING_LAST_BAR = time(11, 30)
AFTERNOON_FIRST_BAR = time(13, 1)
MARKET_CLOSE_BAR = time(15, 0)

COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_BPS = 10.0
LOT_SIZE = 100

SIGNAL_COLUMNS = (
    "event_id",
    "vt_symbol",
    "trade_date",
    "signal_at",
    "evidence_level",
)
MINUTE_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "bar_time",
    "open_price",
    "close_price",
    "high_price",
    "low_price",
    "volume",
    "limit_up_price",
    "limit_down_price",
    "suspended",
    "source",
)


@dataclass(frozen=True)
class FixedMinuteExit:
    key: str
    session_offset: int
    observation_time: time | None
    price_field: str


FIXED_MINUTE_EXITS = (
    FixedMinuteExit("d1_1000", 1, time(10, 0), "open_price"),
    FixedMinuteExit("d1_1430", 1, time(14, 30), "open_price"),
    FixedMinuteExit("d1_close", 1, None, "close_price"),
    FixedMinuteExit("d3_close", 3, None, "close_price"),
    FixedMinuteExit("d5_close", 5, None, "close_price"),
)
STRICT_MINUTE_EXIT_KEYS = tuple(target.key for target in FIXED_MINUTE_EXITS)


def generate_strict_minute_outcomes(
    signals: pd.DataFrame,
    minute_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    initial_cash: float = 100_000.0,
    cost_multiplier: float = 1.0,
) -> pd.DataFrame:
    """Fill each signal at the next executable bar and evaluate fixed exits."""

    _validate_inputs(
        signals,
        minute_bars,
        trading_dates=trading_dates,
        initial_cash=initial_cash,
        cost_multiplier=cost_multiplier,
    )
    if signals.empty:
        return _empty_outcomes()

    signal_frame = _normalized_signals(signals)
    bar_frame = _normalized_bars(minute_bars)
    calendar = _normalized_calendar(trading_dates)
    bars_by_symbol = {
        str(symbol): group.sort_values("bar_time", kind="stable").reset_index(drop=True)
        for symbol, group in bar_frame.groupby("vt_symbol", sort=False)
    }

    rows: list[dict[str, Any]] = []
    for signal in signal_frame.sort_values(
        ["signal_at", "event_id"], kind="stable"
    ).to_dict("records"):
        symbol_bars = bars_by_symbol.get(str(signal["vt_symbol"]), bar_frame.iloc[0:0])
        rows.extend(
            _signal_outcomes(
                signal,
                symbol_bars,
                calendar,
                initial_cash=initial_cash,
                cost_multiplier=cost_multiplier,
            )
        )
    return pd.DataFrame(rows, columns=_empty_outcomes().columns)


def _signal_outcomes(
    signal: dict[str, Any],
    symbol_bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    initial_cash: float,
    cost_multiplier: float,
) -> list[dict[str, Any]]:
    entry_bar, rejection = _next_entry_bar(signal, symbol_bars)
    if rejection:
        return _status_rows(
            signal,
            calendar,
            status="rejected",
            reason=rejection,
            cost_multiplier=cost_multiplier,
        )

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
        return _status_rows(
            signal,
            calendar,
            status="rejected",
            reason="insufficient_cash",
            cost_multiplier=cost_multiplier,
        )

    outcomes = []
    for target in FIXED_MINUTE_EXITS:
        outcomes.append(
            _fixed_exit_outcome(
                signal,
                entry_bar,
                buy,
                target,
                symbol_bars,
                calendar,
                initial_cash=initial_cash,
                cost_multiplier=cost_multiplier,
            )
        )
    return outcomes


def _next_entry_bar(
    signal: dict[str, Any],
    symbol_bars: pd.DataFrame,
) -> tuple[pd.Series | None, str | None]:
    signal_at = pd.Timestamp(signal["signal_at"])
    if signal_at.time() >= ENTRY_SIGNAL_CUTOFF:
        return None, "signal_at_or_after_entry_cutoff"

    candidates = symbol_bars.loc[
        (symbol_bars["trade_date"] == pd.Timestamp(signal["trade_date"]))
        & (symbol_bars["bar_time"] > signal_at)
    ]
    if candidates.empty:
        return None, "missing_next_minute_bar"
    entry_bar = candidates.iloc[0]
    entry_time = pd.Timestamp(entry_bar["bar_time"])
    if not _is_immediate_next_bar(signal_at, entry_time):
        return None, "missing_next_minute_bar"
    if entry_time.time() > ENTRY_SIGNAL_CUTOFF:
        return None, "entry_after_cutoff"
    rejection = _entry_rejection(entry_bar)
    return (None, rejection) if rejection else (entry_bar, None)


def _fixed_exit_outcome(
    signal: dict[str, Any],
    entry_bar: pd.Series,
    buy: cash_ledger.BuyExecution,
    target: FixedMinuteExit,
    symbol_bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    initial_cash: float,
    cost_multiplier: float,
) -> dict[str, Any]:
    exit_date = _target_session(
        pd.Timestamp(signal["trade_date"]),
        target.session_offset,
        calendar,
    )
    base = _base_row(
        signal,
        target,
        entry_bar=entry_bar,
        buy=buy,
        exit_date=exit_date,
        cost_multiplier=cost_multiplier,
    )
    if exit_date is None:
        return _unclosed(base, "missing_exit_session")

    exit_bar = _target_exit_bar(symbol_bars, exit_date, target)
    if exit_bar is None:
        return _unclosed(base, "missing_exit_bar")
    rejection = _exit_rejection(exit_bar, price_field=target.price_field)
    if rejection:
        base["exit_time"] = pd.Timestamp(exit_bar["bar_time"])
        return _unclosed(base, rejection)

    raw_exit_price = float(exit_bar[target.price_field])
    sell = cash_ledger.calculate_sell_execution(
        raw_price=raw_exit_price,
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
    raw_entry_price = float(entry_bar["open_price"])
    base.update(
        {
            "status": "closed",
            "reason": None,
            "exit_time": pd.Timestamp(exit_bar["bar_time"]),
            "exit_price_raw": raw_exit_price,
            "exit_price": sell.price,
            "sell_fee": sell.fee,
            "total_fees": buy.fee + sell.fee,
            "gross_return_pct": (raw_exit_price / raw_entry_price - 1.0) * 100.0,
            "net_return_pct": (final_cash / initial_cash - 1.0) * 100.0,
        }
    )
    return base


def _target_exit_bar(
    symbol_bars: pd.DataFrame,
    exit_date: pd.Timestamp,
    target: FixedMinuteExit,
) -> pd.Series | None:
    day_bars = symbol_bars.loc[symbol_bars["trade_date"] == exit_date]
    if day_bars.empty:
        return None
    if target.observation_time is None:
        close = day_bars.loc[
            day_bars["bar_time"].map(lambda value: pd.Timestamp(value).time())
            == MARKET_CLOSE_BAR
        ]
        return None if close.empty else close.iloc[-1]

    observed_at = pd.Timestamp(datetime.combine(exit_date.date(), target.observation_time))
    later = day_bars.loc[day_bars["bar_time"] > observed_at]
    if later.empty:
        return None
    candidate = later.iloc[0]
    if pd.Timestamp(candidate["bar_time"]) != observed_at + timedelta(minutes=1):
        return None
    return candidate


def _target_session(
    signal_date: pd.Timestamp,
    offset: int,
    calendar: pd.DatetimeIndex,
) -> pd.Timestamp | None:
    if signal_date not in calendar:
        return None
    position = int(calendar.get_loc(signal_date)) + offset
    return calendar[position] if position < len(calendar) else None


def _entry_rejection(bar: pd.Series) -> str | None:
    if bool(bar["suspended"]):
        return "entry_suspended"
    if float(bar["volume"]) <= 0:
        return "entry_zero_volume"
    open_price = float(bar["open_price"])
    limit_up = float(bar["limit_up_price"])
    if open_price <= 0 or limit_up <= 0:
        return "invalid_entry_price"
    if open_price >= limit_up and float(bar["low_price"]) >= limit_up:
        return "entry_one_price_limit_up"
    return None


def _exit_rejection(bar: pd.Series, *, price_field: str) -> str | None:
    if bool(bar["suspended"]):
        return "exit_suspended"
    if float(bar["volume"]) <= 0:
        return "exit_zero_volume"
    raw_price = float(bar[price_field])
    limit_down = float(bar["limit_down_price"])
    if raw_price <= 0 or limit_down <= 0:
        return "invalid_exit_price"
    if raw_price <= limit_down and float(bar["high_price"]) <= limit_down:
        return "exit_one_price_limit_down"
    return None


def _is_immediate_next_bar(signal_at: pd.Timestamp, bar_time: pd.Timestamp) -> bool:
    if bar_time == signal_at + timedelta(minutes=1):
        return True
    return (
        signal_at.date() == bar_time.date()
        and signal_at.time() == MORNING_LAST_BAR
        and bar_time.time() == AFTERNOON_FIRST_BAR
    )


def _status_rows(
    signal: dict[str, Any],
    calendar: pd.DatetimeIndex,
    *,
    status: str,
    reason: str,
    cost_multiplier: float,
) -> list[dict[str, Any]]:
    rows = []
    for target in FIXED_MINUTE_EXITS:
        exit_date = _target_session(
            pd.Timestamp(signal["trade_date"]),
            target.session_offset,
            calendar,
        )
        row = _base_row(
            signal,
            target,
            entry_bar=None,
            buy=None,
            exit_date=exit_date,
            cost_multiplier=cost_multiplier,
        )
        row.update({"status": status, "reason": reason})
        rows.append(row)
    return rows


def _base_row(
    signal: dict[str, Any],
    target: FixedMinuteExit,
    *,
    entry_bar: pd.Series | None,
    buy: cash_ledger.BuyExecution | None,
    exit_date: pd.Timestamp | None,
    cost_multiplier: float,
) -> dict[str, Any]:
    return {
        "event_id": str(signal["event_id"]),
        "vt_symbol": str(signal["vt_symbol"]),
        "signal_date": pd.Timestamp(signal["trade_date"]),
        "signal_at": pd.Timestamp(signal["signal_at"]),
        "evidence_level": str(signal["evidence_level"]),
        "exit_key": target.key,
        "entry_date": pd.Timestamp(entry_bar["trade_date"])
        if entry_bar is not None
        else None,
        "entry_time": pd.Timestamp(entry_bar["bar_time"])
        if entry_bar is not None
        else None,
        "entry_price_raw": float(entry_bar["open_price"])
        if entry_bar is not None
        else None,
        "entry_price": buy.price if buy is not None else None,
        "volume": buy.volume if buy is not None else 0,
        "buy_fee": buy.fee if buy is not None else None,
        "exit_date": exit_date,
        "exit_time": None,
        "exit_price_raw": None,
        "exit_price": None,
        "sell_fee": None,
        "total_fees": None,
        "gross_return_pct": None,
        "net_return_pct": None,
        "cost_multiplier": cost_multiplier,
        "status": None,
        "reason": None,
    }


def _unclosed(base: dict[str, Any], reason: str) -> dict[str, Any]:
    row = dict(base)
    row.update({"status": "unclosed", "reason": reason})
    return row


def _normalized_signals(signals: pd.DataFrame) -> pd.DataFrame:
    frame = signals.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["signal_at"] = frame["signal_at"].map(_local_naive_timestamp)
    if frame.duplicated("event_id").any():
        raise ValueError("signal event_id rows must be unique")
    mismatch = frame["signal_at"].dt.normalize() != frame["trade_date"]
    if mismatch.any():
        raise ValueError("signal_at date must match trade_date")
    return frame


def _normalized_bars(minute_bars: pd.DataFrame) -> pd.DataFrame:
    frame = minute_bars.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if frame.empty:
        frame["bar_time"] = pd.Series(index=frame.index, dtype="datetime64[ns]")
        return frame
    frame["bar_time"] = frame["bar_time"].map(_local_naive_timestamp)
    if frame.duplicated(["vt_symbol", "bar_time"]).any():
        raise ValueError("minute vt_symbol/bar_time rows must be unique")
    mismatch = frame["bar_time"].dt.normalize() != frame["trade_date"]
    if mismatch.any():
        raise ValueError("minute bar_time date must match trade_date")
    return frame.sort_values(["vt_symbol", "bar_time"], kind="stable")


def _local_naive_timestamp(value: Any) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(SHANGHAI).tz_localize(None)
    return parsed


def _normalized_calendar(trading_dates: Sequence[date]) -> pd.DatetimeIndex:
    calendar = pd.DatetimeIndex(pd.to_datetime(list(trading_dates), errors="raise"))
    return calendar.normalize().drop_duplicates().sort_values()


def _validate_inputs(
    signals: pd.DataFrame,
    minute_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    initial_cash: float,
    cost_multiplier: float,
) -> None:
    missing_signals = [column for column in SIGNAL_COLUMNS if column not in signals]
    if missing_signals:
        raise ValueError(f"missing signal columns: {', '.join(missing_signals)}")
    missing_bars = [column for column in MINUTE_COLUMNS if column not in minute_bars]
    if missing_bars:
        raise ValueError(f"missing minute columns: {', '.join(missing_bars)}")
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
            "signal_at",
            "evidence_level",
            "exit_key",
            "entry_date",
            "entry_time",
            "entry_price_raw",
            "entry_price",
            "volume",
            "buy_fee",
            "exit_date",
            "exit_time",
            "exit_price_raw",
            "exit_price",
            "sell_fee",
            "total_fees",
            "gross_return_pct",
            "net_return_pct",
            "cost_multiplier",
            "status",
            "reason",
        ]
    )
