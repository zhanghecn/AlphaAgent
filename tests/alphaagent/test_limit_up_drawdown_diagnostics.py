from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.limit_up import cash_backtest
from alphaagent.server.services.limit_up.drawdown_diagnostics import (
    analyze_account_drawdown,
    analyze_recommendation_regime,
)
from alphaagent.server.services.limit_up.causal_exit_research import (
    analyze_precommitted_auction_limit_readiness,
    analyze_post_auction_exit_surface,
    attach_d0_first_board_open_benchmark,
    build_withdrawn_policy_audit,
)


def test_account_diagnostics_find_longest_loss_streak_and_recovery() -> None:
    account = {
        "executed_trades": [
            _trade("600001.SSE", "2026-01-02", "2026-01-03", 5.0, "sealed"),
            _trade("600002.SSE", "2026-01-04", "2026-01-05", -1.0, "sealed"),
            _trade("600003.SSE", "2026-01-05", "2026-01-06", -2.0, "failed"),
            _trade("600004.SSE", "2026-01-06", "2026-01-07", 1.0, "sealed"),
        ],
        "skipped_orders": [],
        "equity_curve": [
            _equity("2026-01-02", 100_000),
            _equity("2026-01-03", 110_000),
            _equity("2026-01-05", 105_000),
            _equity("2026-01-06", 95_000),
            _equity("2026-01-07", 111_000),
        ],
    }

    result = analyze_account_drawdown(
        account,
        validation_start=date(2026, 1, 1),
        freeze_date=date(2026, 12, 31),
    )

    streak = result["longest_losing_streak"]
    assert streak["count"] == 2
    assert streak["start_date"] == "2026-01-05"
    assert streak["end_date"] == "2026-01-06"
    assert streak["first_entry_date"] == "2026-01-04"
    assert streak["compound_return_pct"] == pytest.approx(-2.98)
    assert [row["vt_symbol"] for row in streak["trades"]] == [
        "600002.SSE",
        "600003.SSE",
    ]

    episode = result["maximum_drawdown_episode"]
    assert episode["peak_date"] == "2026-01-03"
    assert episode["trough_date"] == "2026-01-06"
    assert episode["recovery_date"] == "2026-01-07"
    assert episode["drawdown_pct"] == pytest.approx(-13.6364)
    assert [row["vt_symbol"] for row in episode["principal_losses"]] == [
        "600003.SSE",
        "600002.SSE",
    ]


def test_account_diagnostics_compare_executed_and_skipped_same_periods() -> None:
    account = {
        "executed_trades": [
            _trade("600001.SSE", "2026-06-01", "2026-06-02", 3.0, "sealed"),
            _trade("600002.SSE", "2026-07-01", "2026-07-02", -1.0, "sealed"),
            _trade("600003.SSE", "2026-07-02", "2026-07-03", 5.0, "sealed"),
        ],
        "skipped_orders": [
            _skipped("600004.SSE", "2026-06-01", 2.0),
            _skipped("600005.SSE", "2026-07-01", -4.0),
            _skipped("600006.SSE", "2026-07-02", -2.0),
        ],
        "equity_curve": [],
    }

    result = analyze_account_drawdown(
        account,
        validation_start=date(2026, 6, 1),
        freeze_date=date(2026, 7, 31),
    )

    validation = result["execution_filter"]["time_validation"]
    assert validation["executed"] == {
        "count": 3,
        "win_count": 2,
        "win_rate": 66.6667,
        "average_return_pct": 2.3333,
    }
    assert validation["skipped"]["count"] == 3
    assert validation["skipped"]["win_rate"] == pytest.approx(33.3333)
    assert validation["skipped"]["average_return_pct"] == pytest.approx(-1.3333)

    latest = result["execution_filter"]["latest_entry_month"]
    assert latest["month"] == "2026-07"
    assert latest["executed"]["count"] == 2
    assert latest["executed"]["win_rate"] == 50.0
    assert latest["skipped"]["count"] == 2
    assert latest["skipped"]["win_rate"] == 0.0
    assert latest["skipped"]["average_return_pct"] == -3.0


def test_board_status_is_reported_as_outcome_only_attribution() -> None:
    account = {
        "executed_trades": [
            _trade("600001.SSE", "2026-01-02", "2026-01-03", 4.0, "sealed"),
            _trade("600002.SSE", "2026-01-03", "2026-01-04", -6.0, "failed"),
            _trade("600003.SSE", "2026-01-04", "2026-01-05", 1.0, "failed"),
        ],
        "skipped_orders": [],
        "equity_curve": [],
    }

    result = analyze_account_drawdown(
        account,
        validation_start=date(2026, 1, 1),
        freeze_date=date(2026, 12, 31),
    )

    attribution = result["board_outcome_attribution"]
    assert attribution["actionability"] == "outcome_only_not_entry_filter"
    groups = {row["status"]: row for row in attribution["groups"]}
    assert groups["sealed"]["win_rate"] == 100.0
    assert groups["failed"]["count"] == 2
    assert groups["failed"]["win_rate"] == 50.0
    assert groups["failed"]["average_return_pct"] == -2.5
    assert groups["failed"]["hard_loss_count"] == 1
    assert attribution["hard_loss_failed_count"] == 1
    assert attribution["hard_loss_count"] == 1


def test_recommendation_regime_compares_design_and_validation_without_positions() -> None:
    orders = [
        _outcome_order("2026-01-20", 3.0),
        _outcome_order("2026-02-20", 1.0),
        _outcome_order("2026-04-20", -2.0),
        _outcome_order("2026-05-20", 1.0),
    ]

    result = analyze_recommendation_regime(
        orders,
        design_start=date(2026, 1, 16),
        validation_start=date(2026, 4, 14),
        freeze_date=date(2026, 7, 15),
    )

    assert result["design_sample"] == {
        "count": 2,
        "win_count": 2,
        "win_rate": 100.0,
        "average_return_pct": 2.0,
    }
    assert result["time_validation"] == {
        "count": 2,
        "win_count": 1,
        "win_rate": 50.0,
        "average_return_pct": -0.5,
    }
    assert result["win_rate_delta_pct_points"] == -50.0


def test_invalid_same_price_shadow_is_withdrawn_without_metrics() -> None:
    result = build_withdrawn_policy_audit()

    assert result["policy_version"] == "first-board-auction-take-profit-shadow-v1"
    assert result["status"] == "invalidated_same_price_decision_fill_lookahead"
    assert result["published_metrics_withdrawn"] is True
    assert result["published_metrics"] is None
    assert "summary" not in result


def test_d0_open_benchmark_decides_before_d1_price_is_known() -> None:
    orders = [
        _signal("600001.SSE", "first_board", 2.0),
        _signal("600002.SSE", "first_board", 1.9999),
        _signal("600003.SSE", "two_to_three", 8.0),
        _signal("600004.SSE", "first_board", None),
    ]

    result = attach_d0_first_board_open_benchmark(orders)

    assert result[0]["dynamic_exit"]["mode"] == "auction_exit"
    assert result[0]["dynamic_exit"]["decision_time"] == "D0 after close"
    assert result[1]["dynamic_exit"]["mode"] == "auction_exit"
    assert result[2]["dynamic_exit"]["mode"] == "tail_exit"
    assert result[3]["dynamic_exit"]["mode"] == "auction_exit"
    assert "dynamic_exit" not in orders[0]


def test_post_auction_surface_blocks_account_metrics_when_0931_is_missing() -> None:
    trades = [
        _execution_trade("600001.SSE", 2.5, 3.0),
        _execution_trade("600002.SSE", 4.0, -1.0),
    ]
    prices = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-02",
            "price_0931": 10.4,
            "price_source": "minute_0931_open",
        }
    ]

    result = analyze_post_auction_exit_surface(
        trades,
        prices,
        config=cash_backtest.CashBacktestConfig(slippage_bps=0),
    )

    assert result["status"] == "blocked_by_execution_price_coverage"
    assert result["coverage"] == {
        "required_pair_count": 2,
        "covered_pair_count": 1,
        "missing_pair_count": 1,
        "coverage_pct": 50.0,
        "minimum_coverage_pct": 95.0,
        "coverage_passed": False,
    }
    assert result["account_performance"] is None
    threshold_rows = {row["threshold_pct"]: row for row in result["threshold_rows"]}
    assert threshold_rows[2.0]["trigger_count"] == 1
    assert threshold_rows[3.0]["trigger_count"] == 0
    assert threshold_rows[2.0]["sample_count"] == 1


def test_precommitted_auction_limit_requires_strict_fill_evidence() -> None:
    trades = [
        _execution_trade("600001.SSE", 2.5, 3.0),
        _execution_trade("600002.SSE", 4.0, -1.0),
    ]
    evidence = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-02",
            "strict_complete": False,
            "matched_volume": 10_000,
            "unmatched_volume": None,
        }
    ]

    result = analyze_precommitted_auction_limit_readiness(trades, evidence)

    assert result["status"] == "blocked_by_auction_fill_evidence"
    assert result["selected_threshold_pct"] is None
    assert result["account_performance"] is None
    assert result["coverage"] == {
        "required_pair_count": 2,
        "snapshot_covered_pair_count": 1,
        "strict_complete_pair_count": 0,
        "unmatched_volume_pair_count": 0,
        "strict_coverage_pct": 0.0,
        "minimum_strict_coverage_pct": 95.0,
        "coverage_passed": False,
    }


def _trade(
    symbol: str,
    entry_date: str,
    exit_date: str,
    return_pct: float,
    board_status: str,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": "first_board",
        "entry_date": entry_date,
        "buy_date": entry_date,
        "exit_date": exit_date,
        "sell_date": exit_date,
        "return_pct": return_pct,
        "net_pnl": return_pct * 100,
        "d_board_status": board_status,
        "is_hard_loss": return_pct <= -5,
    }


def _skipped(symbol: str, trade_date: str, return_pct: float) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": "first_board",
        "trade_date": trade_date,
        "d1_return_pct": return_pct,
        "reason": "position_limit",
    }


def _equity(trade_date: str, total_equity: float) -> dict[str, object]:
    return {
        "result_date": trade_date,
        "total_equity": total_equity,
    }


def _signal(
    symbol: str,
    lane: str,
    open_return_pct: float | None,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "lane": lane,
        "outcome": {
            "next_open_return_pct": open_return_pct,
            "next_close_return_pct": 3.0,
        },
    }


def _outcome_order(entry_date: str, return_pct: float) -> dict[str, object]:
    return {
        "entry_date": entry_date,
        "lane": "first_board",
        "outcome": {"next_close_return_pct": return_pct},
    }


def _execution_trade(
    symbol: str,
    next_open_return_pct: float,
    close_return_pct: float,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "lane": "first_board",
        "exit_date": "2026-07-02",
        "buy_price": 10.0,
        "buy_amount": 1_000.0,
        "buy_fee": 0.0,
        "volume": 100,
        "return_pct": close_return_pct,
        "outcome": {"next_open_return_pct": next_open_return_pct},
    }
