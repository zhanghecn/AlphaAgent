from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from alphaagent.server.api import limit_up
from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import radar_validation


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _observation(
    vt_symbol: str,
    captured_at: str,
    *,
    last_price: float,
    early_action: str = "pass",
    formal_action: str = "pass",
    score: float = 60.0,
) -> dict[str, object]:
    return {
        "trade_date": captured_at[:10],
        "captured_at": captured_at,
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "last_price": last_price,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "change_pct": round((last_price / 10.0 - 1) * 100, 4),
        "capture_state": "pre_radar" if last_price < 10.5 else "near_limit",
        "board_lane": "first_board",
        "entry_quality_score": score,
        "early_action": early_action,
        "formal_action": formal_action,
    }


def _daily_bar(vt_symbol: str, trade_date: str, close_price: float) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": close_price,
        "high_price": close_price,
        "low_price": close_price,
        "close_price": close_price,
    }


def _complete_frames(trade_dates: list[str]) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for trade_date in trade_dates:
        for start_text, end_text in (
            ("10:00:00", "11:30:00"),
            ("13:00:00", "14:30:00"),
        ):
            captured_at = datetime.fromisoformat(
                f"{trade_date}T{start_text}+08:00"
            )
            window_end = datetime.fromisoformat(
                f"{trade_date}T{end_text}+08:00"
            )
            while captured_at < window_end:
                frames.append(
                    {
                        "trade_date": trade_date,
                        "captured_at": captured_at.isoformat(),
                        "source_trade_date": trade_date,
                        "quality_status": "ready",
                        "is_stale": False,
                        "quote_coverage_ratio": 1.0,
                    }
                )
                captured_at += timedelta(seconds=15)
    return frames


def _full_session_minutes(
    pairs: list[tuple[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for vt_symbol, trade_date in pairs:
        starts = (
            datetime.fromisoformat(f"{trade_date}T09:31:00"),
            datetime.fromisoformat(f"{trade_date}T13:01:00"),
        )
        for start in starts:
            for offset in range(120):
                bar_time = start + timedelta(minutes=offset)
                rows.append(
                    {
                        "vt_symbol": vt_symbol,
                        "trade_date": trade_date,
                        "bar_time": bar_time.isoformat(),
                        "interval": "1m",
                        "open_price": 10.30,
                        "high_price": 10.40,
                        "low_price": 10.20,
                        "close_price": 10.35,
                    }
                )
    return rows


def _complete_evidence_for(
    observations: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    pairs = sorted(
        {
            (str(row["vt_symbol"]), str(row["trade_date"]))
            for row in observations
        }
    )
    trade_dates = sorted({trade_date for _, trade_date in pairs})
    return _complete_frames(trade_dates), _full_session_minutes(pairs)


def test_first_delayed_quote_uses_the_first_saved_quote_between_20_and_60_seconds() -> None:
    signal_at = datetime.fromisoformat("2026-07-20T10:05:20+08:00")
    quotes = [
        {"captured_at": "2026-07-20T10:05:35+08:00", "last_price": 10.40},
        {"captured_at": "2026-07-20T10:05:42+08:00", "last_price": 10.55},
        {"captured_at": "2026-07-20T10:06:25+08:00", "last_price": 10.60},
    ]

    fill = radar_validation.first_delayed_quote(quotes, signal_at)

    assert fill is not None
    assert fill["last_price"] == 10.55
    assert fill["captured_at"] == "2026-07-20T10:05:42+08:00"


def test_first_delayed_quote_cannot_cross_the_entry_window_end() -> None:
    signal_at = datetime.fromisoformat("2026-07-20T14:29:45+08:00")
    quotes = [
        {"captured_at": "2026-07-20T14:29:59+08:00", "last_price": 10.40},
        {"captured_at": "2026-07-20T14:30:05+08:00", "last_price": 10.45},
    ]

    assert radar_validation.first_delayed_quote(quotes, signal_at) is None


def test_later_rank_and_future_outcome_cannot_change_the_first_signal() -> None:
    observations = [
        _observation(
            "600001.SSE",
            "2026-07-20T10:05:20+08:00",
            last_price=10.35,
            early_action="buy_now",
            score=61.0,
        ),
        _observation(
            "600001.SSE",
            "2026-07-20T10:05:42+08:00",
            last_price=10.40,
            early_action="buy_now",
            score=62.0,
        ),
        _observation(
            "600002.SSE",
            "2026-07-20T10:06:00+08:00",
            last_price=10.36,
            early_action="buy_now",
            score=60.0,
        ),
        _observation(
            "600002.SSE",
            "2026-07-20T10:06:25+08:00",
            last_price=10.42,
            early_action="buy_now",
            score=99.0,
        ),
    ]
    daily_bars = [
        _daily_bar(symbol, trade_date, close)
        for symbol in ("600001.SSE", "600002.SSE")
        for trade_date, close in (
            ("2026-07-20", 10.50),
            ("2026-07-21", 10.90),
        )
    ]

    frames, minute_bars = _complete_evidence_for(observations)
    baseline = radar_validation.build_radar_validation_report(
        frames, observations, daily_bars, minute_bars
    )
    mutated_observations = deepcopy(observations)
    mutated_observations[-1]["entry_quality_score"] = 1_000.0
    mutated_bars = deepcopy(daily_bars)
    for row in mutated_bars:
        if row["trade_date"] == "2026-07-21":
            row["close_price"] = 8.0
    mutated = radar_validation.build_radar_validation_report(
        frames, mutated_observations, mutated_bars, minute_bars
    )

    baseline_signals = baseline["contracts"]["early_3pct_same_rules"]["signals"]
    mutated_signals = mutated["contracts"]["early_3pct_same_rules"]["signals"]
    assert mutated_signals == baseline_signals
    assert baseline_signals[0]["captured_at"] == "2026-07-20T10:05:20+08:00"
    assert [row["vt_symbol"] for row in baseline_signals] == [
        "600001.SSE",
        "600002.SSE",
    ]


def test_limit_price_quote_is_queue_unknown_and_missing_quote_is_not_filled() -> None:
    observations = [
        _observation(
            "600001.SSE",
            "2026-07-20T10:05:00+08:00",
            last_price=10.40,
            early_action="buy_now",
        ),
        _observation(
            "600001.SSE",
            "2026-07-20T10:05:21+08:00",
            last_price=11.0,
            early_action="buy_now",
        ),
        _observation(
            "600002.SSE",
            "2026-07-20T10:06:00+08:00",
            last_price=10.40,
            early_action="buy_now",
        ),
    ]
    daily_bars = [
        _daily_bar(symbol, trade_date, close)
        for symbol in ("600001.SSE", "600002.SSE")
        for trade_date, close in (
            ("2026-07-20", 10.50),
            ("2026-07-21", 10.90),
        )
    ]

    frames, minute_bars = _complete_evidence_for(observations)
    report = radar_validation.build_radar_validation_report(
        frames, observations, daily_bars, minute_bars
    )
    contract = report["contracts"]["early_3pct_same_rules"]

    statuses = {row["vt_symbol"]: row["status"] for row in contract["orders"]}
    assert statuses == {
        "600001.SSE": "queue_unknown_without_l2",
        "600002.SSE": "entry_quote_missing",
    }
    metrics = contract["all_recommendations"]
    assert metrics["signal_count"] == 2
    assert metrics["closed_count"] == 0
    assert metrics["queue_unknown_count"] == 1
    assert metrics["entry_quote_missing_count"] == 1


def test_reaction_time_counts_trading_minutes_instead_of_the_lunch_break() -> None:
    observations = [
        _observation(
            "600001.SSE",
            "2026-07-20T10:00:00+08:00",
            last_price=10.30,
        )
    ]
    minute_bars = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-20",
            "bar_time": "2026-07-20T11:29:00",
            "interval": "1m",
            "open_price": 10.20,
            "high_price": 10.31,
            "low_price": 10.18,
            "close_price": 10.30,
        },
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-20",
            "bar_time": "2026-07-20T13:00:00",
            "interval": "1m",
            "open_price": 10.40,
            "high_price": 10.55,
            "low_price": 10.38,
            "close_price": 10.52,
        },
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-20",
            "bar_time": "2026-07-20T13:01:00",
            "interval": "1m",
            "open_price": 10.60,
            "high_price": 11.00,
            "low_price": 10.60,
            "close_price": 11.00,
        },
    ]

    result = radar_validation.build_reaction_time_report(observations, minute_bars)

    path = result["paths"][0]
    assert path["first_3pct_at"].endswith("11:29:00+08:00")
    assert path["first_5pct_at"].endswith("13:00:00+08:00")
    assert path["first_limit_touch_at"].endswith("13:01:00+08:00")
    assert path["lead_minutes_3pct_to_limit"] == 2
    assert path["lead_minutes_5pct_to_limit"] == 1
    assert result["caught_at_least_two_minutes_early_pct"] == 100.0


def test_scan_gap_includes_unobserved_entry_window_edges() -> None:
    trade_date = "2026-07-20"
    frames = [
        {
            "trade_date": trade_date,
            "captured_at": f"{trade_date}T{captured_time}+08:00",
            "source_trade_date": trade_date,
            "quality_status": "ready",
            "is_stale": False,
            "quote_coverage_ratio": 1.0,
        }
        for captured_time in (
            "10:45:00",
            "10:45:15",
            "13:45:00",
            "13:45:15",
        )
    ]

    coverage = radar_validation.build_validation_coverage(frames, [], [])

    assert coverage["complete_trade_days"] == 0
    assert coverage["scan_gap_p90_seconds"] == 2700.0
    assert coverage["daily"][0]["scan_gap_p90_seconds"] == 2700.0


def test_minute_coverage_rejects_240_rows_outside_official_minute_slots() -> None:
    trade_date = "2026-07-20"
    shifted_rows: list[dict[str, object]] = []
    for start in (
        datetime.fromisoformat(f"{trade_date}T09:30:00"),
        datetime.fromisoformat(f"{trade_date}T13:00:00"),
    ):
        for offset in range(120):
            bar_time = start + timedelta(minutes=offset)
            shifted_rows.append(
                {
                    "vt_symbol": "600001.SSE",
                    "trade_date": trade_date,
                    "bar_time": bar_time.isoformat(),
                    "interval": "1m",
                    "open_price": 10.30,
                    "high_price": 10.40,
                    "low_price": 10.20,
                    "close_price": 10.35,
                }
            )
    observations = [
        _observation(
            "600001.SSE",
            f"{trade_date}T10:05:00+08:00",
            last_price=10.40,
        )
    ]

    coverage = radar_validation.build_validation_coverage(
        _complete_frames([trade_date]),
        observations,
        shifted_rows,
    )

    assert coverage["observed_minute_pair_count"] == 1
    assert coverage["complete_minute_pair_count"] == 0
    assert coverage["complete_trade_days"] == 0


def test_two_position_view_uses_arrival_order_after_fillability_checks() -> None:
    observations: list[dict[str, object]] = []
    daily_bars: list[dict[str, object]] = []
    for index, symbol in enumerate(("600001.SSE", "600002.SSE", "600003.SSE")):
        second = index * 10
        observations.extend(
            [
                _observation(
                    symbol,
                    f"2026-07-20T10:05:{second:02d}+08:00",
                    last_price=10.35,
                    early_action="buy_now",
                ),
                _observation(
                    symbol,
                    f"2026-07-20T10:05:{second + 21:02d}+08:00",
                    last_price=10.40,
                    early_action="buy_now",
                ),
            ]
        )
        daily_bars.extend(
            [
                _daily_bar(symbol, "2026-07-20", 10.50),
                _daily_bar(symbol, "2026-07-21", 10.90),
            ]
        )

    frames, minute_bars = _complete_evidence_for(observations)
    report = radar_validation.build_radar_validation_report(
        frames, observations, daily_bars, minute_bars
    )
    account = report["contracts"]["early_3pct_same_rules"][
        "two_position_account"
    ]

    assert account["account_config"]["max_positions"] == 2
    assert account["execution_summary"]["signal_count"] == 3
    assert account["execution_summary"]["filled_count"] == 2
    assert account["execution_summary"]["skipped_reasons"] == {
        "position_limit": 1
    }


def test_incomplete_days_are_excluded_from_both_contracts() -> None:
    complete = "2026-07-20"
    incomplete = "2026-07-21"
    observations = [
        _observation(
            symbol,
            f"{trade_date}T10:05:00+08:00",
            last_price=10.60,
            early_action="buy_now",
            formal_action="buy_now",
        )
        for trade_date, symbol in (
            (complete, "600001.SSE"),
            (incomplete, "600002.SSE"),
        )
    ] + [
        _observation(
            symbol,
            f"{trade_date}T10:05:25+08:00",
            last_price=10.65,
            early_action="buy_now",
            formal_action="buy_now",
        )
        for trade_date, symbol in (
            (complete, "600001.SSE"),
            (incomplete, "600002.SSE"),
        )
    ]
    frames = _complete_frames([complete, incomplete])
    minute_bars = _full_session_minutes([("600001.SSE", complete)])
    daily_bars = [
        _daily_bar("600001.SSE", complete, 10.70),
        _daily_bar("600001.SSE", incomplete, 10.90),
        _daily_bar("600002.SSE", incomplete, 10.70),
        _daily_bar("600002.SSE", "2026-07-22", 8.00),
    ]

    report = radar_validation.build_radar_validation_report(
        frames,
        observations,
        daily_bars,
        minute_bars,
        trade_calendar=[complete, incomplete, "2026-07-22"],
    )

    assert report["coverage"]["observed_trade_days"] == 2
    assert report["coverage"]["complete_trade_days"] == 1
    assert report["coverage"]["evaluation_day_dates"] == [complete]
    for contract in radar_validation.CONTRACT_ACTION_FIELDS:
        signals = report["contracts"][contract]["signals"]
        assert [(row["signal_date"], row["vt_symbol"]) for row in signals] == [
            (complete, "600001.SSE")
        ]


def test_first_sixty_complete_days_form_a_frozen_evaluation_cohort() -> None:
    first = date(2026, 1, 2)
    trade_dates = [(first + timedelta(days=offset)).isoformat() for offset in range(62)]
    signal_dates = trade_dates[:61]
    observations: list[dict[str, object]] = []
    for trade_date in signal_dates:
        observations.extend(
            [
                {
                    **_observation(
                        "600001.SSE",
                        f"{trade_date}T10:05:00+08:00",
                        last_price=10.60,
                        early_action="buy_now",
                        formal_action="buy_now",
                    ),
                    "trade_date": trade_date,
                },
                {
                    **_observation(
                        "600001.SSE",
                        f"{trade_date}T10:05:25+08:00",
                        last_price=10.65,
                        early_action="buy_now",
                        formal_action="buy_now",
                    ),
                    "trade_date": trade_date,
                },
            ]
        )
    frames = _complete_frames(signal_dates)
    minute_bars = _full_session_minutes(
        [("600001.SSE", trade_date) for trade_date in signal_dates]
    )
    daily_bars = [
        _daily_bar("600001.SSE", trade_date, 10.90)
        for trade_date in trade_dates
    ]

    baseline = radar_validation.build_radar_validation_report(
        frames,
        observations,
        daily_bars,
        minute_bars,
        trade_calendar=trade_dates,
    )
    mutated_bars = deepcopy(daily_bars)
    for row in mutated_bars:
        if row["trade_date"] == trade_dates[61]:
            row["close_price"] = 1.0
    mutated = radar_validation.build_radar_validation_report(
        frames,
        observations,
        mutated_bars,
        minute_bars,
        trade_calendar=trade_dates,
    )

    assert baseline["coverage"]["complete_trade_days"] == 61
    assert baseline["coverage"]["evaluation_trade_days"] == 60
    assert baseline["coverage"]["evaluation_cohort_frozen"] is True
    assert baseline["coverage"]["evaluation_day_dates"] == signal_dates[:60]
    for contract in radar_validation.CONTRACT_ACTION_FIELDS:
        baseline_contract = baseline["contracts"][contract]
        mutated_contract = mutated["contracts"][contract]
        assert len(baseline_contract["signals"]) == 60
        assert baseline_contract["signals"] == mutated_contract["signals"]
        assert (
            baseline_contract["all_recommendations"]
            == mutated_contract["all_recommendations"]
        )


def test_radar_validation_endpoint_is_read_only(monkeypatch) -> None:
    expected = {
        "status": "collecting",
        "coverage": {"complete_trade_days": 3},
    }
    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_radar_validation", lambda: expected)
    monkeypatch.setattr(
        limit_up,
        "refresh_live_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("GET must not fetch quotes")),
    )
    monkeypatch.setattr(
        limit_up,
        "backfill_limit_up_event_minutes",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("GET must not start backfills")
        ),
    )

    response = TestClient(create_app()).get("/api/limit-up/radar-validation")

    assert response.status_code == 200
    assert response.json()["data"] == expected


def _acceptance_inputs() -> dict[str, object]:
    return {
        "coverage": {
            "complete_trade_days": 60,
            "minute_pair_coverage_pct": 95.0,
            "valid_frame_ratio_pct": 98.0,
            "scan_gap_p90_seconds": 20.0,
        },
        "early_metrics": {
            "closed_count": 300,
            "awaiting_d1_close_count": 0,
            "days_with_at_least_one_recommendation": 40,
            "win_rate_pct": 60.0,
            "average_net_return_pct": 1.0,
            "profit_factor": 1.5,
            "loss_count": 30,
            "max_drawdown_pct": -15.0,
            "double_cost_profit_factor": 1.2,
            "double_cost_loss_count": 35,
            "max_single_date_profit_share_pct": 15.0,
        },
        "formal_metrics": {
            "awaiting_d1_close_count": 0,
            "win_rate_pct": 62.0,
            "average_net_return_pct": 1.2,
        },
        "comparison": {
            "early_minus_formal_win_rate_pp": -2.0,
            "early_minus_formal_average_return_pp": -0.2,
            "queue_unknown_reduction_pct": 20.0,
        },
        "reaction_time": {
            "fast_path_caught_two_minutes_early_pct": 50.0,
        },
        "chronological_blocks": [
            {
                "closed_count": 40,
                "average_net_return_pct": 0.1 if index < 4 else 0.0,
                "profit_factor": 1.0,
                "positive": index < 4,
            }
            for index in range(5)
        ],
    }


def test_acceptance_gate_accepts_every_exact_boundary() -> None:
    result = radar_validation.evaluate_radar_acceptance(**_acceptance_inputs())

    assert result["status"] == "accepted"
    assert result["eligible_for_activation"] is True
    assert result["recommended_contract"] == "early_3pct_same_rules"
    assert result["production_contract"] == "formal_5pct"
    assert result["selected_contract"] == "formal_5pct"
    assert result["activation_required"] is True
    assert result["production_contract_mismatch"] is True
    assert result["failed_gate_keys"] == []


def test_acceptance_only_reports_3pct_as_current_after_production_activation() -> None:
    inputs = _acceptance_inputs()
    inputs["production_contract"] = "early_3pct_same_rules"

    result = radar_validation.evaluate_radar_acceptance(**inputs)

    assert result["status"] == "accepted"
    assert result["recommended_contract"] == "early_3pct_same_rules"
    assert result["production_contract"] == "early_3pct_same_rules"
    assert result["selected_contract"] == "early_3pct_same_rules"
    assert result["activation_required"] is False
    assert result["production_contract_mismatch"] is False


def test_sixty_day_review_waits_for_both_contracts_to_finish_d1_settlement() -> None:
    inputs = _acceptance_inputs()
    inputs["formal_metrics"]["awaiting_d1_close_count"] = 1

    result = radar_validation.evaluate_radar_acceptance(**inputs)

    assert result["status"] == "ready_for_review"
    assert result["eligible_for_activation"] is False
    assert result["selected_contract"] == "formal_5pct"
    assert "pending_d1_settlements" in result["failed_gate_keys"]


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("coverage", "complete_trade_days", 59),
        ("early_metrics", "closed_count", 299),
        ("early_metrics", "days_with_at_least_one_recommendation", 39),
        ("coverage", "minute_pair_coverage_pct", 94.9999),
        ("coverage", "valid_frame_ratio_pct", 97.9999),
        ("coverage", "scan_gap_p90_seconds", 20.0001),
        ("early_metrics", "win_rate_pct", 59.9999),
        ("early_metrics", "average_net_return_pct", 0.9999),
        ("early_metrics", "profit_factor", 1.4999),
        ("early_metrics", "max_drawdown_pct", -15.0001),
        ("early_metrics", "double_cost_profit_factor", 1.1999),
        ("early_metrics", "max_single_date_profit_share_pct", 15.0001),
        ("comparison", "early_minus_formal_win_rate_pp", -2.0001),
        ("comparison", "early_minus_formal_average_return_pp", -0.2001),
        ("comparison", "queue_unknown_reduction_pct", 19.9999),
        ("reaction_time", "fast_path_caught_two_minutes_early_pct", 49.9999),
    ],
)
def test_acceptance_gate_fails_immediately_outside_each_boundary(
    section: str,
    key: str,
    value: object,
) -> None:
    inputs = _acceptance_inputs()
    inputs[section][key] = value

    result = radar_validation.evaluate_radar_acceptance(**inputs)

    assert result["eligible_for_activation"] is False
    assert result["selected_contract"] == "formal_5pct"
    assert result["status"] == (
        "process_ready"
        if section == "coverage" and key == "complete_trade_days"
        else "rejected"
    )


def test_acceptance_gate_fails_closed_for_missing_metrics_and_bad_blocks() -> None:
    missing = _acceptance_inputs()
    missing["coverage"]["minute_pair_coverage_pct"] = None
    missing_result = radar_validation.evaluate_radar_acceptance(**missing)

    bad_blocks = _acceptance_inputs()
    bad_blocks["chronological_blocks"][0]["closed_count"] = 39
    bad_blocks["chronological_blocks"][1]["profit_factor"] = 0.9999
    bad_blocks["chronological_blocks"][3]["positive"] = False
    bad_blocks["chronological_blocks"][3]["average_net_return_pct"] = -0.1
    block_result = radar_validation.evaluate_radar_acceptance(**bad_blocks)

    assert missing_result["status"] == "rejected"
    assert "minute_pair_coverage_pct" in missing_result["failed_gate_keys"]
    assert block_result["status"] == "rejected"
    assert {
        "chronological_block_size",
        "chronological_block_profit_factor",
        "positive_chronological_blocks",
    }.issubset(block_result["failed_gate_keys"])


def test_research_shadow_event_never_becomes_an_actionable_recommendation() -> None:
    row = {
        "vt_symbol": "600001.SSE",
        "signal_date": "2026-07-20",
        "signal_time": "10:01:00",
        "captured_at": "2026-07-20T10:01:05+08:00",
        "prepare_probability": 0.7,
        "action_probability": 0.4,
    }

    event = radar_validation.build_read_only_research_event(
        row,
        state=radar_validation.RESEARCH_ACTION_STATE,
        prepare_score_field="prepare_probability",
        action_score_field="action_probability",
    )

    assert event["research_state"] == "research_action"
    assert event["execution_effect"] == "none_research_only"
    assert event["actionable"] is False
    assert "action" not in event
    assert "actionable_recommendations" not in event
