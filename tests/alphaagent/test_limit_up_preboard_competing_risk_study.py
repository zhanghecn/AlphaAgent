from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    competing_feature_vector,
)
from alphaagent.server.services.limit_up.preboard_competing_risk_study import (
    _acceptance_report,
    audit_minute_daily_consistency,
    build_account_path_attribution,
    build_competing_replay_orders,
    diagnose_signal_selection_failures,
    prepare_forward_competing_rows,
    render_competing_markdown,
    replay_competing_account,
    split_competing_dates,
    summarize_model_coefficients,
)


def test_competing_replay_keeps_confirmation_relay_and_cash_constraints() -> None:
    action_rows = [
        _signal("600001.SSE", "10:00:00", 0.90, 10.50),
        _signal("600002.SSE", "10:00:00", 0.80, 10.40),
        _signal("600001.SSE", "10:01:00", 0.92, 10.51),
        _signal("600002.SSE", "10:01:00", 0.85, 10.41),
    ]
    relay = {
        "vt_symbol": "600010.SSE",
        "name": "Relay",
        "entry_date": "2026-07-16",
        "result_date": "2026-07-17",
        "buy_time": "09:30:00",
        "lane": "two_to_three",
        "signal_kind": "auction",
        "entry_price": 10.0,
        "limit_price": 11.0,
        "outcome": {"next_close_price": 10.5},
    }

    bundle = build_competing_replay_orders(
        action_rows=action_rows,
        formal_orders=[relay],
        action_threshold=0.75,
    )

    assert [row["vt_symbol"] for row in bundle["action_signals"]] == [
        "600001.SSE",
        "600002.SSE",
    ]
    assert [row["vt_symbol"] for row in bundle["combined_orders"]] == [
        "600010.SSE",
        "600001.SSE",
        "600002.SSE",
    ]
    assert all(
        order["algorithm"] == "formal_identity_x_3m_timing_confirmed"
        for order in bundle["early_orders"]
    )

    account = replay_competing_account(
        bundle["combined_orders"],
        _daily_bars(),
        [date(2026, 7, 16), date(2026, 7, 17)],
    )
    buys = [order for order in account["orders"] if order["side"] == "BUY"]
    assert [(order["vt_symbol"], order["status"]) for order in buys] == [
        ("600010.SSE", "filled"),
        ("600001.SSE", "filled"),
        ("600002.SSE", "skipped"),
    ]


def test_competing_split_is_frozen_44_15_30() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(89)]

    fit, calibration, validation = split_competing_dates(dates)

    assert len(fit) == 44
    assert len(calibration) == 15
    assert len(validation) == 30
    assert fit[-1] < calibration[0] < validation[0]


def test_forward_rows_require_fresh_same_day_frames_and_dedupe_minutes() -> None:
    first = {
        **_signal("600001.SSE", "10:01:00", 0.8, 10.4),
        "captured_at": "2026-07-16T10:01:05+08:00",
        "quote_observed_at": "2026-07-16T10:01:00+08:00",
        "frame_is_stale": False,
        "source_trade_date": date(2026, 7, 16),
        "profitability_gate_sample_count": 8,
        "profitability_gate_combined_rate": 45.0,
        "support_score": 65.0,
        "features": {
            "gain_pct": 8.0,
            "return_1m_pct": 0.4,
            "return_3m_pct": 0.8,
            "return_5m_pct": 1.2,
            "prior_30m_floor_pct": 3.0,
            "session_drawdown_pct": -0.1,
            "turnover_acceleration_1m": 1.5,
            "volume_ratio_5m": 1.8,
            "bar_close_location": 0.9,
            "minute_of_window": 5.0,
        },
    }
    duplicate = {
        **first,
        "captured_at": "2026-07-16T10:01:20+08:00",
        "rank_score": 99.0,
    }
    stale = {
        **first,
        "vt_symbol": "600002.SSE",
        "frame_is_stale": True,
    }
    wrong_day = {
        **first,
        "vt_symbol": "600003.SSE",
        "source_trade_date": date(2026, 7, 15),
    }

    rows = prepare_forward_competing_rows([duplicate, stale, wrong_day, first])

    assert len(rows) == 1
    assert rows[0]["captured_at"] == first["captured_at"]
    assert rows[0]["rank_score"] == first["rank_score"]
    assert competing_feature_vector(rows[0]) is not None


def test_minute_daily_consistency_checks_prices_volume_units_and_turnover() -> None:
    manifest = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 16),
                "high_price": 10.8,
                "low_price": 10.1,
                "close_price": 10.7,
                "volume": 30.0,
                "turnover": 31_700.0,
            }
        ]
    )
    minutes = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 16),
                "bar_time": "2026-07-16T09:31:00",
                "high_price": 10.5,
                "low_price": 10.1,
                "close_price": 10.4,
                "volume": 1_000.0,
                "turnover": 10_400.0,
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 16),
                "bar_time": "2026-07-16T15:00:00",
                "high_price": 10.8,
                "low_price": 10.3,
                "close_price": 10.7,
                "volume": 2_000.0,
                "turnover": 21_300.0,
            },
        ]
    )

    audit = audit_minute_daily_consistency(
        manifest,
        minutes,
        expected_bar_count=2,
    )

    assert audit["ready_pair_count"] == 1
    assert audit["ready_pair_pct"] == 100.0
    assert audit["volume_unit_ratio_median"] == 100.0


def test_competing_markdown_reads_account_trade_count() -> None:
    report = {
        "status": "ready_historical_rejected",
        "decision": "historical_rejected_no_live_promotion",
        "study_version": "test",
        "coverage": {},
        "dataset": {},
        "minute_daily_consistency": {},
        "models": {
            "identity": {
                "coefficient_summary": {
                    "positive": [{"feature": "gain_pct", "coefficient": 1.2}],
                    "negative": [],
                }
            },
            "timing_3m": {},
        },
        "threshold_selection": {},
        "phases": {
            "validation": {
                "identity": {},
                "account_identity": {},
                "account_path_attribution": {
                    "action_filled_categories": {
                        "formal_identity_false_positive": {
                            "pair_count": 1,
                            "closed_trade_count": 1,
                            "win_rate_pct": 0.0,
                            "average_return_pct": -2.0,
                            "total_net_pnl": -1000.0,
                        }
                    },
                    "missed_original_account": {
                        "pair_count": 0,
                        "category_counts": {},
                        "ledger": [],
                    },
                    "position_path": {},
                    "matched_trade_comparison": {},
                    "early_order_ledger": [
                        {
                            "trade_date": "2026-07-16",
                            "vt_symbol": "600004.SSE",
                            "execution_status": "filled",
                            "category": "filled_formal_identity_false_positive",
                            "return_pct": -2.0,
                        }
                    ],
                },
                "accounts": {
                    "formal_touch": {"trade_count": 23, "win_rate": 73.91},
                    "competing_action": {},
                    "competing_action_double_cost": {},
                    "competing_action_conservative": {},
                },
            }
        },
        "validation_blocks": [],
        "acceptance": {"checks": {}},
        "forward_validation": {},
        "limitations": [],
    }

    markdown = render_competing_markdown(report)

    assert "| 23 | 73.91% |" in markdown
    assert "`gain_pct` +1.2000" in markdown
    assert "`formal_identity_false_positive`" in markdown
    assert "600004.SSE" in markdown


def test_acceptance_counts_positive_blocks_with_closed_trades() -> None:
    validation_blocks = [
        {
            "accounts": {
                "competing_action": {
                    "trade_count": 1,
                    "total_return_pct": total_return,
                }
            }
        }
        for total_return in (1.0, 0.5, -0.5, -1.0, 0.0)
    ]

    acceptance = _acceptance_report(
        {},
        validation_blocks=validation_blocks,
        models=(SimpleNamespace(status="ready"), SimpleNamespace(status="ready")),
        threshold=SimpleNamespace(status="ready"),
        baseline_parity={"passed": True},
    )

    assert acceptance["positive_validation_block_count"] == 2


def test_account_path_attribution_separates_identity_and_position_failures() -> None:
    first_day = date(2026, 7, 13)
    matched_day = date(2026, 7, 15)
    false_positive_day = date(2026, 7, 17)
    relay = _order(
        "600010.SSE",
        first_day,
        date(2026, 7, 14),
        "09:30:00",
        lane="two_to_three",
        signal_kind="auction",
    )
    formal_orders = [
        relay,
        _order("600001.SSE", first_day, date(2026, 7, 14), "10:05:00"),
        _order("600002.SSE", first_day, date(2026, 7, 14), "10:06:00"),
        _order("600003.SSE", matched_day, date(2026, 7, 16), "10:05:00"),
    ]
    action_orders = [
        relay,
        _order(
            "600002.SSE",
            first_day,
            date(2026, 7, 14),
            "10:00:00",
            algorithm="formal_identity_x_3m_timing_confirmed",
        ),
        _order(
            "600001.SSE",
            first_day,
            date(2026, 7, 14),
            "10:01:00",
            algorithm="formal_identity_x_3m_timing_confirmed",
        ),
        _order(
            "600003.SSE",
            matched_day,
            date(2026, 7, 16),
            "10:00:00",
            algorithm="formal_identity_x_3m_timing_confirmed",
        ),
        _order(
            "600004.SSE",
            false_positive_day,
            date(2026, 7, 20),
            "10:00:00",
            algorithm="formal_identity_x_3m_timing_confirmed",
        ),
    ]
    trade_dates = [
        first_day,
        date(2026, 7, 14),
        matched_day,
        date(2026, 7, 16),
        false_positive_day,
        date(2026, 7, 20),
    ]

    report = build_account_path_attribution(
        formal_orders=formal_orders,
        action_orders=action_orders,
        bars=_account_bars(trade_dates),
        trade_dates=trade_dates,
        allowed_dates={first_day, matched_day, false_positive_day},
    )

    categories = report["action_filled_categories"]
    assert categories["matched_original_account"]["pair_count"] == 1
    assert categories["formal_identity_true_but_not_original_account"]["pair_count"] == 1
    assert categories["formal_identity_false_positive"]["pair_count"] == 1
    assert categories["formal_identity_false_positive"]["eventually_touched_count"] == 1
    assert report["action_filled_feature_profiles"][
        "formal_identity_false_positive"
    ]["action_score"]["median"] == 0.95
    assert report["missed_original_account"]["pair_count"] == 1
    assert report["missed_original_account"]["category_counts"] == {
        "action_signal_blocked_by_position_limit": 1
    }
    assert report["position_path"]["action_order_position_limit_count"] == 1
    assert report["position_path"][
        "original_account_signal_blocked_by_position_limit_count"
    ] == 1
    assert report["selection_confirmation_minutes"] == 2


def test_model_coefficient_summary_uses_standardized_direction_and_magnitude() -> None:
    summary = summarize_model_coefficients(
        {"small_positive": 0.5, "negative": -2.0, "largest_positive": 3.0},
        limit=2,
    )

    assert summary == {
        "positive": [
            {"feature": "largest_positive", "coefficient": 3.0},
            {"feature": "small_positive", "coefficient": 0.5},
        ],
        "negative": [{"feature": "negative", "coefficient": -2.0}],
    }


def test_signal_selection_diagnosis_separates_each_causal_stage() -> None:
    trade_date = date(2026, 7, 16)
    pairs = {
        ("600001.SSE", trade_date),
        ("600002.SSE", trade_date),
        ("600003.SSE", trade_date),
        ("600004.SSE", trade_date),
    }
    observations = [
        _selection_row("600002.SSE", "10:00:00", 0.80),
        _selection_row("600002.SSE", "10:01:00", 0.85),
        _selection_row("600003.SSE", "10:00:00", 0.95),
        _selection_row("600003.SSE", "10:01:00", 0.80),
        _selection_row("600003.SSE", "10:02:00", 0.95),
        _selection_row("600004.SSE", "10:00:00", 0.95),
        _selection_row("600004.SSE", "10:01:00", 0.96),
    ]
    selected = [
        _selection_row("600010.SSE", "09:59:00", 0.99),
        _selection_row("600011.SSE", "10:00:00", 0.99),
    ]

    diagnosis = diagnose_signal_selection_failures(
        pairs,
        observation_rows=observations,
        scored_rows=observations,
        selected_signals=selected,
        threshold=0.90,
        confirmation_minutes=2,
        max_daily_actions=2,
    )

    assert diagnosis[("600001.SSE", trade_date)]["category"] == (
        "no_eligible_preboard_prefix"
    )
    assert diagnosis[("600002.SSE", trade_date)]["category"] == (
        "score_below_action_threshold"
    )
    assert diagnosis[("600003.SSE", trade_date)]["category"] == (
        "threshold_not_confirmed_two_minutes"
    )
    assert diagnosis[("600004.SSE", trade_date)]["category"] == (
        "daily_action_slots_already_filled"
    )

    one_minute = diagnose_signal_selection_failures(
        {("600003.SSE", trade_date)},
        observation_rows=observations,
        scored_rows=observations,
        selected_signals=(),
        threshold=0.90,
        confirmation_minutes=1,
        max_daily_actions=2,
    )
    assert one_minute[("600003.SSE", trade_date)]["first_confirmation_time"] == (
        "10:00:00"
    )
    assert one_minute[("600003.SSE", trade_date)]["category"] == (
        "confirmed_not_selected_unexpected"
    )


def _signal(
    symbol: str,
    signal_time: str,
    score: float,
    entry_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "signal_date": "2026-07-16",
        "result_date": "2026-07-17",
        "signal_at": f"2026-07-16T{signal_time}",
        "signal_time": signal_time,
        "signal_price": entry_price - 0.01,
        "entry_time": "10:02:00",
        "entry_price": entry_price,
        "limit_price": 11.0,
        "fillable": True,
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
        "action_score": score,
        "identity_probability": score,
        "timing_probability": score,
        "entry_quality_score": score * 100,
        "rank_score": score * 100,
        "features": {"gain_pct": 8.0},
    }


def _daily_bars() -> list[dict[str, object]]:
    symbols = ("600001.SSE", "600002.SSE", "600010.SSE")
    return [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date,
            "open_price": 10.0,
            "high_price": 10.9,
            "low_price": 9.9,
            "close_price": 10.5 if trade_date == date(2026, 7, 17) else 10.3,
        }
        for trade_date in (date(2026, 7, 16), date(2026, 7, 17))
        for symbol in symbols
    ]


def _order(
    symbol: str,
    entry_date: date,
    result_date: date,
    buy_time: str,
    *,
    lane: str = "first_board",
    signal_kind: str = "momentum",
    algorithm: str | None = None,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "entry_date": entry_date.isoformat(),
        "result_date": result_date.isoformat(),
        "buy_time": buy_time,
        "lane": lane,
        "signal_kind": signal_kind,
        "entry_price": 10.0,
        "limit_price": 11.0,
        "rank_score": 80.0,
        "algorithm": algorithm,
        "identity_probability": 0.98,
        "timing_probability": 0.97,
        "action_score": 0.95,
        "support_score": 65.0,
        "base_rank_score": 80.0,
        "features": {
            "gain_pct": 8.5,
            "return_3m_pct": 1.2,
            "prior_30m_floor_pct": 4.0,
        },
        "outcome": {
            "touched": True,
            "sealed": True,
            "next_close_price": 10.5,
        },
    }


def _selection_row(
    symbol: str,
    signal_time: str,
    action_score: float,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": "2026-07-16",
        "signal_time": signal_time,
        "action_score": action_score,
    }


def _account_bars(trade_dates: list[date]) -> list[dict[str, object]]:
    symbols = tuple(f"60000{index}.SSE" for index in range(1, 5)) + ("600010.SSE",)
    return [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date,
            "open_price": 10.0,
            "high_price": 10.8,
            "low_price": 9.9,
            "close_price": 10.5,
        }
        for trade_date in trade_dates
        for symbol in symbols
    ]
