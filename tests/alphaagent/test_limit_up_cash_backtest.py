from __future__ import annotations

import pytest

from alphaagent.server.services.backtest import ledger


def test_buy_execution_applies_minimum_commission_transfer_fee_and_limit_cap() -> None:
    fill = ledger.calculate_buy_execution(
        raw_price=10.0,
        cash=10_000,
        target_cash=5_000,
        commission_rate=0.0003,
        slippage_bps=10,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        max_price=10.0,
    )

    assert fill.price == 10.0
    assert fill.volume == 500
    assert fill.amount == 5_000.0
    assert fill.fee == pytest.approx(5.05)
    assert fill.cash_after == pytest.approx(4_994.95)


def test_sell_execution_applies_minimum_commission_transfer_fee_and_floor() -> None:
    fill = ledger.calculate_sell_execution(
        raw_price=9.0,
        volume=500,
        cost_price=10.0,
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        min_price=9.0,
    )

    assert fill.price == 9.0
    assert fill.amount == 4_500.0
    assert fill.fee == pytest.approx(7.295)
    assert fill.cash_delta == pytest.approx(4_492.705)
    assert fill.pnl == pytest.approx(-507.295)
