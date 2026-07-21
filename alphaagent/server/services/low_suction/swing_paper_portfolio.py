"""Pure paper-account decisions for the low-suction swing strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

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
from .stock_wave_pullbacks import build_stock_wave_features
from .swing_strategy import ENTRY_TIME, MAX_POSITIONS, QUOTE_MAX_AGE_SECONDS


SHANGHAI = ZoneInfo("Asia/Shanghai")
INITIAL_CASH = 100_000.0
OPEN_FILL_START = time(9, 30)
OPEN_FILL_END = time(9, 35)


class PaperPortfolioInputError(ValueError):
    """Raised when a paper fill would use unavailable or non-causal data."""


@dataclass(frozen=True)
class EntryFillDecision:
    signal_id: str
    strategy_version: str
    vt_symbol: str
    stock_name: str
    sector_id: str
    sector_name: str
    signal_trade_date: date
    entry_at: datetime
    quote_time: datetime
    status: str
    reason: str | None
    raw_price: float
    entry_price: float | None
    volume: int
    entry_amount: float
    buy_fee: float
    buy_cash_delta: float
    cash_after: float
    reference_peak_price: float
    quote_source: str
    broker_order_created: bool


@dataclass(frozen=True)
class ExitTriggerDecision:
    signal_id: str
    trigger_date: date
    trigger_reason: str
    exit_price: None = None


@dataclass(frozen=True)
class ExitFillDecision:
    signal_id: str
    strategy_version: str
    vt_symbol: str
    stock_name: str
    sector_id: str
    sector_name: str
    status: str
    reason: str | None
    trigger_date: date
    trigger_reason: str
    exit_trade_date: date | None
    exit_at: datetime
    quote_time: datetime
    raw_price: float
    exit_price: float | None
    exit_amount: float
    sell_fee: float
    sell_cash_delta: float
    total_fees: float
    net_pnl: float | None
    net_return_pct: float | None
    exit_deferred_sessions: int
    quote_source: str
    broker_order_created: bool


def plan_entry_fills(
    signals: pd.DataFrame,
    positions: pd.DataFrame,
    trades: pd.DataFrame,
    quotes: pd.DataFrame,
    *,
    captured_at: datetime,
) -> tuple[EntryFillDecision, ...]:
    """Plan deterministic 14:55 paper fills without creating broker orders."""

    _validate_entry_clock(captured_at)
    signal_frame = _prepare_signals(signals)
    position_frame = _prepare_positions(positions)
    trade_frame = _prepare_trades(trades)
    quote_frame = _prepare_quotes(
        quotes,
        captured_at=captured_at,
        earliest_time=ENTRY_TIME,
        latest_time=time(15, 0),
        early_message="entry quote before 14:55",
    )
    recommended = signal_frame.loc[
        signal_frame["recommendation_state"].eq("recommended")
    ].sort_values(["rank", "signal_id"], kind="stable")
    if recommended.empty:
        return ()
    required_symbols = set(recommended["vt_symbol"].astype(str))
    active = position_frame.loc[
        position_frame["status"].isin(("open", "exit_pending"))
    ]
    required_symbols.update(active["vt_symbol"].astype(str))
    _require_quote_symbols(quote_frame, required_symbols)
    quote_index = quote_frame.set_index("vt_symbol")
    cash = _account_cash(position_frame, trade_frame)
    equity = cash + sum(
        int(row.volume) * float(quote_index.loc[str(row.vt_symbol)]["last_price"])
        for row in active.itertuples(index=False)
    )
    target_cash = equity / MAX_POSITIONS
    active_symbols = set(active["vt_symbol"].astype(str))
    active_sectors = set(active["sector_id"].astype(str))
    decisions: list[EntryFillDecision] = []
    for signal in recommended.to_dict("records"):
        quote = quote_index.loc[str(signal["vt_symbol"])]
        reason = _entry_rejection(
            signal,
            quote,
            active_symbols=active_symbols,
            active_sectors=active_sectors,
            active_count=len(active_symbols),
        )
        if reason is not None:
            decisions.append(
                _rejected_entry(signal, quote, captured_at, cash, reason)
            )
            continue
        previous_close = float(quote["previous_close"])
        limit_up = _limit_price(previous_close, 1.10)
        raw_price = float(quote["last_price"])
        buy = cash_ledger.calculate_buy_execution(
            raw_price=raw_price,
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
            decisions.append(
                _rejected_entry(
                    signal,
                    quote,
                    captured_at,
                    cash,
                    "insufficient_cash",
                )
            )
            continue
        cash = buy.cash_after
        active_symbols.add(str(signal["vt_symbol"]))
        active_sectors.add(str(signal["sector_id"]))
        decisions.append(
            EntryFillDecision(
                signal_id=str(signal["signal_id"]),
                strategy_version=str(signal["strategy_version"]),
                vt_symbol=str(signal["vt_symbol"]),
                stock_name=str(signal["stock_name"]),
                sector_id=str(signal["sector_id"]),
                sector_name=str(signal["sector_name"]),
                signal_trade_date=signal["signal_trade_date"],
                entry_at=captured_at,
                quote_time=_as_datetime(quote["trade_time"]),
                status="filled",
                reason=None,
                raw_price=raw_price,
                entry_price=buy.price,
                volume=buy.volume,
                entry_amount=buy.amount,
                buy_fee=buy.fee,
                buy_cash_delta=buy.cash_delta,
                cash_after=buy.cash_after,
                reference_peak_price=float(signal["reference_peak_price"]),
                quote_source=str(quote.get("source") or ""),
                broker_order_created=False,
            )
        )
    return tuple(decisions)


def detect_exit_triggers(
    positions: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    as_of_date: date,
) -> tuple[ExitTriggerDecision, ...]:
    """Detect structural exits while leaving price and fill time unset."""

    position_frame = _prepare_positions(positions)
    bars = _prepare_daily_bars(daily_bars, as_of_date)
    decisions: list[ExitTriggerDecision] = []
    open_positions = position_frame.loc[position_frame["status"].eq("open")]
    for position in open_positions.to_dict("records"):
        symbol_bars = bars.loc[
            bars["vt_symbol"].eq(str(position["vt_symbol"]))
        ].copy()
        if symbol_bars.empty:
            continue
        features = build_stock_wave_features(symbol_bars.drop(columns="vt_symbol"))
        feature_dates = pd.to_datetime(features["trade_date"], errors="raise").dt.date
        path = features.loc[
            feature_dates.ge(position["entry_trade_date"])
            & feature_dates.le(as_of_date)
        ].copy()
        if path.empty:
            continue
        target = path.loc[
            path["high_price"].gt(float(position["reference_peak_price"]))
        ]
        below_ma20 = path["close_price"].lt(path["ma20"]).fillna(False)
        defense = path.loc[below_ma20 & below_ma20.shift(1, fill_value=False)]
        trigger_date, trigger_reason = _first_trigger(target, defense)
        if trigger_date is None or trigger_reason is None:
            continue
        decisions.append(
            ExitTriggerDecision(
                signal_id=str(position["signal_id"]),
                trigger_date=trigger_date,
                trigger_reason=trigger_reason,
            )
        )
    return tuple(decisions)


def plan_exit_fills(
    positions: pd.DataFrame,
    quotes: pd.DataFrame,
    *,
    captured_at: datetime,
) -> tuple[ExitFillDecision, ...]:
    """Plan next-session-open paper exits for previously triggered positions."""

    _validate_open_clock(captured_at)
    position_frame = _prepare_positions(positions)
    pending = position_frame.loc[position_frame["status"].eq("exit_pending")].copy()
    if pending.empty:
        return ()
    quote_frame = _prepare_quotes(
        quotes,
        captured_at=captured_at,
        earliest_time=OPEN_FILL_START,
        latest_time=OPEN_FILL_END,
        early_message="exit quote before market open",
    )
    _require_quote_symbols(quote_frame, set(pending["vt_symbol"].astype(str)))
    quote_index = quote_frame.set_index("vt_symbol")
    decisions = []
    for position in pending.sort_values("signal_id", kind="stable").to_dict("records"):
        quote = quote_index.loc[str(position["vt_symbol"])]
        quote_time = _as_datetime(quote["trade_time"])
        trigger_date = _as_date(position["exit_trigger_date"])
        if quote_time.astimezone(SHANGHAI).date() <= trigger_date:
            raise PaperPortfolioInputError("exit quote must be from a later session")
        raw_price = float(quote["open_price"])
        previous_close = float(quote["previous_close"])
        limit_down = _limit_price(previous_close, 0.90)
        deferred_sessions = int(position.get("exit_deferred_sessions") or 0)
        if raw_price <= limit_down:
            decisions.append(
                _deferred_exit(
                    position,
                    quote,
                    captured_at,
                    trigger_date,
                    raw_price,
                    deferred_sessions + 1,
                )
            )
            continue
        sell = cash_ledger.calculate_sell_execution(
            raw_price=raw_price,
            volume=int(position["volume"]),
            cost_price=float(position["entry_price"]),
            commission_rate=COMMISSION_RATE,
            stamp_tax_rate=STAMP_TAX_RATE,
            slippage_bps=SLIPPAGE_BPS,
            minimum_commission=MINIMUM_COMMISSION,
            transfer_fee_rate=TRANSFER_FEE_RATE,
            min_price=limit_down,
        )
        buy_cash_delta = float(position["buy_cash_delta"])
        invested_cash = -buy_cash_delta
        net_pnl = buy_cash_delta + sell.cash_delta
        decisions.append(
            ExitFillDecision(
                signal_id=str(position["signal_id"]),
                strategy_version=str(position["strategy_version"]),
                vt_symbol=str(position["vt_symbol"]),
                stock_name=str(position["stock_name"]),
                sector_id=str(position["sector_id"]),
                sector_name=str(position["sector_name"]),
                status="filled",
                reason=None,
                trigger_date=trigger_date,
                trigger_reason=str(position["exit_trigger_reason"]),
                exit_trade_date=quote_time.astimezone(SHANGHAI).date(),
                exit_at=captured_at,
                quote_time=quote_time,
                raw_price=raw_price,
                exit_price=sell.price,
                exit_amount=sell.amount,
                sell_fee=sell.fee,
                sell_cash_delta=sell.cash_delta,
                total_fees=float(position["buy_fee"]) + sell.fee,
                net_pnl=net_pnl,
                net_return_pct=net_pnl / invested_cash * 100.0,
                exit_deferred_sessions=deferred_sessions,
                quote_source=str(quote.get("source") or ""),
                broker_order_created=False,
            )
        )
    return tuple(decisions)


def _prepare_signals(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "signal_id",
        "strategy_version",
        "signal_trade_date",
        "captured_at",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "sector_name",
        "rank",
        "reference_peak_price",
        "recommendation_state",
    }
    _require_columns(frame, required, "paper entry signal")
    result = frame.copy()
    result["signal_trade_date"] = pd.to_datetime(
        result["signal_trade_date"], errors="raise"
    ).dt.date
    return result


def _prepare_positions(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result.reindex(
            columns=[
                "signal_id",
                "strategy_version",
                "vt_symbol",
                "stock_name",
                "sector_id",
                "sector_name",
                "status",
                "entry_trade_date",
                "entry_at",
                "entry_price",
                "entry_amount",
                "volume",
                "buy_fee",
                "buy_cash_delta",
                "reference_peak_price",
                "exit_trigger_date",
                "exit_trigger_reason",
                "exit_due_after",
                "exit_deferred_sessions",
            ]
        )
    required = {
        "signal_id",
        "vt_symbol",
        "sector_id",
        "status",
        "volume",
        "buy_cash_delta",
    }
    _require_columns(result, required, "paper position")
    if "entry_trade_date" in result:
        result["entry_trade_date"] = pd.to_datetime(
            result["entry_trade_date"], errors="raise"
        ).dt.date
    return result


def _prepare_trades(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result.reindex(columns=["signal_id", "sell_cash_delta"])
    _require_columns(result, {"signal_id", "sell_cash_delta"}, "paper trade")
    return result


def _prepare_quotes(
    frame: pd.DataFrame,
    *,
    captured_at: datetime,
    earliest_time: time,
    latest_time: time,
    early_message: str,
) -> pd.DataFrame:
    _require_aware(captured_at, "captured_at")
    _require_columns(
        frame,
        {"vt_symbol", "trade_time", "last_price", "open_price", "previous_close"},
        "paper quote",
    )
    result = frame.copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    if result.duplicated("vt_symbol").any():
        raise PaperPortfolioInputError("paper quote identity must be unique")
    observed = pd.to_datetime(result["trade_time"], errors="raise", utc=True)
    captured = pd.Timestamp(captured_at).tz_convert("UTC")
    if observed.gt(captured).any():
        raise PaperPortfolioInputError("paper quote cannot be from the future")
    ages = (captured - observed).dt.total_seconds()
    if ages.gt(QUOTE_MAX_AGE_SECONDS).any():
        raise PaperPortfolioInputError("paper quote is stale")
    local = observed.dt.tz_convert(SHANGHAI)
    if not local.dt.date.eq(captured_at.astimezone(SHANGHAI).date()).all():
        raise PaperPortfolioInputError("paper quote trade date mismatch")
    if local.dt.time.lt(earliest_time).any():
        raise PaperPortfolioInputError(early_message)
    if local.dt.time.ge(latest_time).any():
        raise PaperPortfolioInputError("paper quote is outside the fill window")
    result["trade_time"] = local
    for column in ("last_price", "open_price", "previous_close"):
        result[column] = pd.to_numeric(result[column], errors="raise")
        if result[column].le(0).any():
            raise PaperPortfolioInputError(f"paper quote {column} must be positive")
    return result


def _entry_rejection(
    signal: dict[str, Any],
    quote: pd.Series,
    *,
    active_symbols: set[str],
    active_sectors: set[str],
    active_count: int,
) -> str | None:
    symbol = str(signal["vt_symbol"])
    sector = str(signal["sector_id"])
    if symbol in active_symbols:
        return "active_symbol_position"
    if sector in active_sectors:
        return "same_concept_position"
    if active_count >= MAX_POSITIONS:
        return "capacity_full"
    raw_price = float(quote["last_price"])
    if raw_price >= float(signal["reference_peak_price"]):
        return "reference_peak_rebroken_before_entry"
    if raw_price >= _limit_price(float(quote["previous_close"]), 1.10):
        return "entry_limit_up_queue_unknown_without_l2"
    signal_time = _as_datetime(signal["captured_at"])
    if _as_datetime(quote["trade_time"]) <= signal_time:
        return "entry_quote_not_after_signal"
    return None


def _rejected_entry(
    signal: dict[str, Any],
    quote: pd.Series,
    captured_at: datetime,
    cash: float,
    reason: str,
) -> EntryFillDecision:
    return EntryFillDecision(
        signal_id=str(signal["signal_id"]),
        strategy_version=str(signal["strategy_version"]),
        vt_symbol=str(signal["vt_symbol"]),
        stock_name=str(signal["stock_name"]),
        sector_id=str(signal["sector_id"]),
        sector_name=str(signal["sector_name"]),
        signal_trade_date=signal["signal_trade_date"],
        entry_at=captured_at,
        quote_time=_as_datetime(quote["trade_time"]),
        status="rejected",
        reason=reason,
        raw_price=float(quote["last_price"]),
        entry_price=None,
        volume=0,
        entry_amount=0.0,
        buy_fee=0.0,
        buy_cash_delta=0.0,
        cash_after=cash,
        reference_peak_price=float(signal["reference_peak_price"]),
        quote_source=str(quote.get("source") or ""),
        broker_order_created=False,
    )


def _deferred_exit(
    position: dict[str, Any],
    quote: pd.Series,
    captured_at: datetime,
    trigger_date: date,
    raw_price: float,
    deferred_sessions: int,
) -> ExitFillDecision:
    return ExitFillDecision(
        signal_id=str(position["signal_id"]),
        strategy_version=str(position["strategy_version"]),
        vt_symbol=str(position["vt_symbol"]),
        stock_name=str(position["stock_name"]),
        sector_id=str(position["sector_id"]),
        sector_name=str(position["sector_name"]),
        status="deferred",
        reason="limit_down_open",
        trigger_date=trigger_date,
        trigger_reason=str(position["exit_trigger_reason"]),
        exit_trade_date=None,
        exit_at=captured_at,
        quote_time=_as_datetime(quote["trade_time"]),
        raw_price=raw_price,
        exit_price=None,
        exit_amount=0.0,
        sell_fee=0.0,
        sell_cash_delta=0.0,
        total_fees=float(position["buy_fee"]),
        net_pnl=None,
        net_return_pct=None,
        exit_deferred_sessions=deferred_sessions,
        quote_source=str(quote.get("source") or ""),
        broker_order_created=False,
    )


def _prepare_daily_bars(frame: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    required = {
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    }
    _require_columns(frame, required, "paper exit daily bar")
    result = frame.copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    result = result.loc[result["trade_date"].le(as_of_date)].copy()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise PaperPortfolioInputError("paper exit daily bar identity must be unique")
    return result


def _first_trigger(
    target: pd.DataFrame,
    defense: pd.DataFrame,
) -> tuple[date | None, str | None]:
    target_date = (
        pd.Timestamp(target.iloc[0]["trade_date"]).date() if not target.empty else None
    )
    defense_date = (
        pd.Timestamp(defense.iloc[0]["trade_date"]).date() if not defense.empty else None
    )
    if target_date is None:
        return defense_date, (
            "two_closes_below_ma20" if defense_date is not None else None
        )
    if defense_date is None or target_date <= defense_date:
        return target_date, "reference_peak_rebroken"
    return defense_date, "two_closes_below_ma20"


def _account_cash(positions: pd.DataFrame, trades: pd.DataFrame) -> float:
    buy_delta = pd.to_numeric(
        positions.get("buy_cash_delta", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0.0).sum()
    sell_delta = pd.to_numeric(
        trades.get("sell_cash_delta", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0.0).sum()
    cash = INITIAL_CASH + float(buy_delta) + float(sell_delta)
    if cash < -1e-6:
        raise PaperPortfolioInputError("paper account cash cannot be negative")
    return max(cash, 0.0)


def _require_quote_symbols(frame: pd.DataFrame, symbols: set[str]) -> None:
    missing = sorted(symbols - set(frame["vt_symbol"].astype(str)))
    if missing:
        raise PaperPortfolioInputError(
            "paper quotes missing for: " + ", ".join(missing)
        )


def _validate_entry_clock(captured_at: datetime) -> None:
    _require_aware(captured_at, "captured_at")
    local_time = captured_at.astimezone(SHANGHAI).time()
    if not ENTRY_TIME <= local_time < time(15, 0):
        raise PaperPortfolioInputError("outside 14:55 paper entry window")


def _validate_open_clock(captured_at: datetime) -> None:
    _require_aware(captured_at, "captured_at")
    local_time = captured_at.astimezone(SHANGHAI).time()
    if not OPEN_FILL_START <= local_time < OPEN_FILL_END:
        raise PaperPortfolioInputError("outside next-open paper exit window")


def _limit_price(previous_close: float, multiplier: float) -> float:
    value = Decimal(str(previous_close)) * Decimal(str(multiplier))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PaperPortfolioInputError(
            f"missing {label} columns: {', '.join(missing)}"
        )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperPortfolioInputError(f"{label} must be timezone-aware")


def _as_datetime(value: object) -> datetime:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise PaperPortfolioInputError("paper timestamp must be timezone-aware")
    return result.to_pydatetime()


def _as_date(value: object) -> date:
    if value is None or pd.isna(value):
        raise PaperPortfolioInputError("paper exit trigger date is missing")
    return pd.Timestamp(value).date()
