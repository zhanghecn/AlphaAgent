"""Unit tests for the pure exit-rule evaluator.

evaluate_exit is the single source of truth for "when should a held position
sell", reused by both the backtest engine (sell_reason_for_position) and the
realtime holdings endpoint (groups.holdings). It accepts absolute price levels
(not coefficients) so each caller supplies whichever price source it has.
"""

from __future__ import annotations

from datetime import date

from alphaagent.server.services.quant.factors import evaluate_exit


def test_evaluate_exit_returns_stop_loss_when_price_falls_below_line() -> None:
    assert (
        evaluate_exit(
            last_price=9.0,
            stop_loss_price=9.3,
            take_profit_price=11.8,
            trailing_stop_price=9.2,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 1, 10),
        )
        == "stop_loss"
    )


def test_evaluate_exit_returns_take_profit_when_price_rises_above_line() -> None:
    assert (
        evaluate_exit(
            last_price=12.0,
            stop_loss_price=9.3,
            take_profit_price=11.8,
            trailing_stop_price=9.2,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 1, 10),
        )
        == "take_profit"
    )


def test_evaluate_exit_returns_trailing_stop_when_only_trailing_breached() -> None:
    # stop_loss 9.0 not breached (9.5 > 9.0), take_profit 11.8 not reached,
    # but trailing 9.6 is breached (9.5 <= 9.6) -> trailing_stop wins.
    assert (
        evaluate_exit(
            last_price=9.5,
            stop_loss_price=9.0,
            take_profit_price=11.8,
            trailing_stop_price=9.6,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 1, 10),
        )
        == "trailing_stop"
    )


def test_evaluate_exit_returns_time_stop_when_held_too_long() -> None:
    # No price line breached, but held >= time_stop_days*2 (default 15*2=30 days).
    assert (
        evaluate_exit(
            last_price=10.5,
            stop_loss_price=9.3,
            take_profit_price=11.8,
            trailing_stop_price=9.2,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 2, 1),  # 31 days >= 30
        )
        == "time_stop"
    )


def test_evaluate_exit_returns_none_when_no_rule_triggered() -> None:
    assert (
        evaluate_exit(
            last_price=10.5,
            stop_loss_price=9.3,
            take_profit_price=11.8,
            trailing_stop_price=9.2,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 1, 10),  # 9 days < 30
        )
        is None
    )


def test_evaluate_exit_stop_loss_takes_priority_over_take_profit() -> None:
    # A pathological price that breaches both stop_loss and take_profit:
    # stop_loss wins by priority order.
    assert (
        evaluate_exit(
            last_price=9.0,
            stop_loss_price=9.3,
            take_profit_price=8.0,  # 9.0 >= 8.0 would trigger take_profit
            trailing_stop_price=9.2,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 1, 10),
        )
        == "stop_loss"
    )


def test_evaluate_exit_skips_missing_price_lines() -> None:
    # Realtime positions may have null stop/take/trailing (manual entry);
    # the evaluator must skip absent lines, not crash.
    assert (
        evaluate_exit(
            last_price=10.5,
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_price=None,
            entry_date=date(2025, 1, 1),
            current_day=date(2025, 2, 1),  # only time_stop can fire
        )
        == "time_stop"
    )


def test_evaluate_exit_skips_time_stop_when_dates_missing() -> None:
    assert (
        evaluate_exit(
            last_price=10.5,
            stop_loss_price=9.3,
            take_profit_price=11.8,
            trailing_stop_price=9.2,
            entry_date=None,
            current_day=None,
        )
        is None
    )
