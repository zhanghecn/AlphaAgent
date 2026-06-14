"""Cash ledger helpers for AlphaAgent backtests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuyExecution:
    price: float
    volume: int
    amount: float
    fee: float
    cash_delta: float
    cash_after: float


@dataclass(frozen=True)
class SellExecution:
    price: float
    volume: int
    amount: float
    fee: float
    pnl: float
    cash_delta: float


def calculate_buy_execution(
    *,
    raw_price: float,
    cash: float,
    target_cash: float,
    commission_rate: float,
    slippage_bps: float,
    lot_size: int = 100,
) -> BuyExecution:
    price = float(raw_price) * (1 + slippage_bps / 10000)
    budget = min(cash, target_cash)
    volume = _round_lot(budget / price, lot_size)
    if volume <= 0:
        return BuyExecution(price, 0, 0.0, 0.0, 0.0, cash)

    amount = price * volume
    fee = amount * commission_rate
    if amount + fee > cash:
        volume = _round_lot(cash / (price * (1 + commission_rate)), lot_size)
        amount = price * volume
        fee = amount * commission_rate

    if volume <= 0:
        return BuyExecution(price, 0, 0.0, 0.0, 0.0, cash)

    cash_delta = -(amount + fee)
    return BuyExecution(price, volume, amount, fee, cash_delta, cash + cash_delta)


def calculate_sell_execution(
    *,
    raw_price: float,
    volume: int,
    cost_price: float,
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_bps: float,
) -> SellExecution:
    price = float(raw_price) * (1 - slippage_bps / 10000)
    amount = price * volume
    fee = amount * (commission_rate + stamp_tax_rate)
    pnl = (price - cost_price) * volume - fee
    return SellExecution(price, volume, amount, fee, pnl, amount - fee)


def _round_lot(volume: float, lot_size: int) -> int:
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    return int(volume / lot_size) * lot_size
