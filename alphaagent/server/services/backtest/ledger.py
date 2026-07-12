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
    minimum_commission: float = 0.0,
    transfer_fee_rate: float = 0.0,
    max_price: float | None = None,
) -> BuyExecution:
    price = float(raw_price) * (1 + slippage_bps / 10000)
    if max_price is not None:
        price = min(price, float(max_price))
    budget = min(cash, target_cash)
    volume = _round_lot(budget / price, lot_size)
    while volume > 0:
        amount = price * volume
        fee = _transaction_fee(
            amount,
            commission_rate=commission_rate,
            minimum_commission=minimum_commission,
            transfer_fee_rate=transfer_fee_rate,
        )
        if amount + fee <= cash:
            cash_delta = -(amount + fee)
            return BuyExecution(
                price,
                volume,
                amount,
                fee,
                cash_delta,
                cash + cash_delta,
            )
        volume -= lot_size

    return BuyExecution(price, 0, 0.0, 0.0, 0.0, cash)


def calculate_sell_execution(
    *,
    raw_price: float,
    volume: int,
    cost_price: float,
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_bps: float,
    minimum_commission: float = 0.0,
    transfer_fee_rate: float = 0.0,
    min_price: float | None = None,
) -> SellExecution:
    price = float(raw_price) * (1 - slippage_bps / 10000)
    if min_price is not None:
        price = max(price, float(min_price))
    amount = price * volume
    fee = _transaction_fee(
        amount,
        commission_rate=commission_rate,
        minimum_commission=minimum_commission,
        transfer_fee_rate=transfer_fee_rate,
    ) + amount * stamp_tax_rate
    pnl = (price - cost_price) * volume - fee
    return SellExecution(price, volume, amount, fee, pnl, amount - fee)


def _round_lot(volume: float, lot_size: int) -> int:
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    return int(volume / lot_size) * lot_size


def _transaction_fee(
    amount: float,
    *,
    commission_rate: float,
    minimum_commission: float,
    transfer_fee_rate: float,
) -> float:
    if amount <= 0:
        return 0.0
    commission = max(amount * commission_rate, minimum_commission)
    return commission + amount * transfer_fee_rate
