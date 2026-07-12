from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from math import isnan

import pytest
from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import walk_forward_model
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


def test_feature_vector_uses_only_pretrade_fields() -> None:
    candidate = {
        **_candidate("2025-01-02", 1.5, sealed=True),
        "prior_limit_count_126": 4,
        "prior_position_120": 0.32,
        "prior_industry_leader_rank": 1,
        "prior_board": {
            "is_sealed": True,
            "first_limit_time": "10:08:00",
            "last_limit_time": "14:12:00",
            "open_times": 2,
            "seal_to_turnover_ratio": 0.06,
        },
        "financial_risk": {
            "level": "caution",
            "blocked": False,
            "reasons": ["weak_cash_flow"],
        },
        "financial_snapshot": {
            "revenue_yoy": 18.0,
            "net_profit_yoy": 25.0,
            "gross_margin": 31.0,
            "roe": 12.0,
            "debt_asset_ratio": 42.0,
            "cash_flow_quality": 1.2,
        },
    }
    baseline = walk_forward_model.feature_vector(candidate)
    mutated = {
        **candidate,
        "action": "auction_buy",
        "score": 9999,
        "outcome": {
            **candidate["outcome"],
            "sealed": False,
            "next_open_return_pct": -18.0,
            "next_close_return_pct": 19.0,
        },
    }

    mutated_vector = walk_forward_model.feature_vector(mutated)
    assert tuple(mutated_vector) == tuple(baseline)
    assert all(
        mutated_vector[name] == value
        or (isnan(mutated_vector[name]) and isnan(value))
        for name, value in baseline.items()
    )
    assert tuple(baseline) == walk_forward_model.FEATURE_NAMES
    assert "auction_gap_pct" in baseline
    assert "target_board" in baseline
    assert baseline["prior_board_open_times"] == 2.0
    assert baseline["prior_board_first_limit_minute"] == 608.0
    assert baseline["prior_board_last_limit_minute"] == 852.0
    assert baseline["financial_risk_count"] == 1.0
    assert baseline["financial_revenue_yoy"] == 18.0
    assert baseline["financial_cash_flow_quality"] == 1.2
    assert "sealed" not in baseline
    assert "score" not in baseline


def test_board_lane_samples_use_the_complete_pool_not_the_displayed_pick() -> None:
    days = _board_history_days(3, candidates_per_day=4)

    samples = walk_forward_model.build_model_samples(
        days,
        entry_mode="next_auction",
        exit_mode="next_open",
        board_lane="one_to_two",
    )

    assert len(samples) == 12
    assert {sample.vt_symbol for sample in samples[:4]} == {
        "600000.SSE",
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    }


def test_first_board_model_keeps_selection_misses_but_not_risk_blockers() -> None:
    day = _history_days(1, candidates_per_day=2)[0]
    premium_gate_miss = {
        **day["lanes"]["sweep"][0],
        "lane": "first_board",
        "decision": "blocked",
        "blockers": ["first_board_profit_growth_weak"],
        "pool_rank": 1,
    }
    fundamental_risk = {
        **day["lanes"]["sweep"][1],
        "lane": "first_board",
        "decision": "blocked",
        "blockers": ["fundamental_risk"],
        "pool_rank": 2,
    }
    day["board_candidate_pool"] = {
        "first_board": [premium_gate_miss, fundamental_risk],
        "one_to_two": [],
        "two_to_three": [],
        "high_board": [],
    }

    samples = walk_forward_model.build_model_samples(
        [day],
        entry_mode="sweep",
        exit_mode="next_open",
        board_lane="first_board",
    )

    assert [sample.vt_symbol for sample in samples] == [
        premium_gate_miss["vt_symbol"]
    ]


def test_board_lane_model_never_falls_back_to_legacy_top5() -> None:
    report = walk_forward_model.build_walk_forward_model_report(
        _history_days(32, candidates_per_day=4),
        entry_mode="next_auction",
        exit_mode="next_open",
        board_lane="one_to_two",
    )

    assert report["status"] == "insufficient_training"
    assert report["candidate_scope"] == "complete_board_lane_candidate_pool"
    assert report["coverage"]["closed_candidate_count"] == 0
    assert report["selected_candidates"] == []


def test_empty_model_report_uses_current_history_strategy_version() -> None:
    report = walk_forward_model.build_walk_forward_model_report(
        [],
        entry_mode="auction",
        exit_mode="next_open",
    )

    assert report["history_strategy_version"] == HISTORY_STRATEGY_VERSION


def test_board_lane_model_selects_at_most_one_candidate_per_day() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=12,
        calibration_days=3,
        test_days=4,
        holdout_days=5,
        max_daily_plans=2,
        min_training_samples=8,
        bootstrap_samples=20,
        estimator_count=8,
        minimum_fill_probability=0.0,
        minimum_seal_probability=0.0,
        minimum_profit_probability=0.0,
        minimum_expected_return_pct=-100.0,
        minimum_confidence_lower_pct=-100.0,
    )
    report = walk_forward_model.build_walk_forward_model_report(
        _board_history_days(32, candidates_per_day=4),
        entry_mode="next_auction",
        exit_mode="next_open",
        board_lane="one_to_two",
        config=config,
    )

    by_date: dict[str, int] = {}
    for row in report["selected_candidates"]:
        by_date[row["signal_date"]] = by_date.get(row["signal_date"], 0) + 1
    assert report["status"] == "ready"
    assert report["board_lane"] == "one_to_two"
    assert report["candidate_scope"] == "complete_board_lane_candidate_pool"
    assert report["model_contract"]["max_daily_plans"] == 1
    assert by_date and max(by_date.values()) == 1


def test_first_board_model_conditions_on_touch_when_fill_labels_are_all_true() -> None:
    days = _board_history_days(32, candidates_per_day=4)
    for day in days:
        first_board_pool = []
        for rank, candidate in enumerate(day["lanes"]["sweep"], start=1):
            outcome = dict(candidate["outcome"])
            outcome["touched"] = True
            first_board_pool.append(
                {
                    **candidate,
                    "outcome": outcome,
                    "lane": "first_board",
                    "decision": "eligible",
                    "pool_rank": rank,
                    "prior_limit_count_126": 2 + rank,
                    "prior_seal_success_rate_126": 0.55 + rank * 0.03,
                    "prior_position_120": 0.25 + rank * 0.05,
                    "financial_risk": {
                        "level": "clear",
                        "blocked": False,
                        "reasons": [],
                    },
                }
            )
        day["board_candidate_pool"]["first_board"] = first_board_pool

    config = walk_forward_model.WalkForwardConfig(
        training_days=12,
        calibration_days=3,
        test_days=4,
        holdout_days=5,
        min_training_samples=8,
        bootstrap_samples=20,
        estimator_count=8,
        minimum_fill_probability=0.0,
        minimum_seal_probability=0.0,
        minimum_profit_probability=0.0,
        minimum_expected_return_pct=-100.0,
        minimum_confidence_lower_pct=-100.0,
    )

    report = walk_forward_model.build_walk_forward_model_report(
        days,
        entry_mode="sweep",
        exit_mode="next_open",
        board_lane="first_board",
        config=config,
    )

    assert report["status"] == "ready"
    assert int(report["coverage"]["fitted_windows"]) > 0
    assert report["ranked_candidates"]
    assert all(
        row["fill_probability"] is None
        for row in report["ranked_candidates"]
    )


def test_walk_forward_windows_only_use_matured_prior_results() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=8,
        calibration_days=2,
        test_days=3,
        holdout_days=4,
        min_training_samples=4,
        bootstrap_samples=20,
    )
    days = _history_days(22)
    samples = walk_forward_model.build_model_samples(
        days,
        entry_mode="auction",
        exit_mode="next_open",
    )

    windows = walk_forward_model.build_walk_forward_windows(samples, config=config)

    assert windows
    assert windows[-1].phase == "locked_holdout"
    for window in windows:
        assert all(sample.result_date < window.test_start for sample in window.training_samples)
        assert all(sample.result_date < window.test_start for sample in window.calibration_samples)
        assert all(window.test_start <= sample.signal_date <= window.test_end for sample in window.test_samples)
    holdout = windows[-1]
    assert holdout.test_start == date(2025, 1, 1) + timedelta(days=18)
    assert holdout.test_end == date(2025, 1, 1) + timedelta(days=21)


def test_walk_forward_windows_advance_on_the_full_trading_calendar() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=8,
        calibration_days=2,
        test_days=3,
        holdout_days=4,
        min_training_samples=4,
        bootstrap_samples=20,
    )
    days = _history_days(22)
    sparse_days = [day for index, day in enumerate(days) if index % 2 == 0]
    samples = walk_forward_model.build_model_samples(
        sparse_days,
        entry_mode="auction",
        exit_mode="next_open",
    )
    trading_dates = [date.fromisoformat(day["trade_date"]) for day in days]

    windows = walk_forward_model.build_walk_forward_windows(
        samples,
        config=config,
        trading_dates=trading_dates,
    )

    assert windows[0].test_start == trading_dates[8]
    assert windows[-1].test_start == trading_dates[-4]
    assert windows[-1].test_end == trading_dates[-1]


def test_holdout_outcomes_do_not_change_expanding_oos_report() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=12,
        calibration_days=3,
        test_days=4,
        holdout_days=5,
        min_training_samples=8,
        bootstrap_samples=20,
        estimator_count=8,
    )
    baseline_days = _history_days(32)
    changed_days = _history_days(32)
    for day in changed_days[-5:]:
        for candidate in day["lanes"]["auction"]:
            candidate["outcome"] = {
                **candidate["outcome"],
                "sealed": not candidate["outcome"]["sealed"],
                "next_open_return_pct": -candidate["outcome"]["next_open_return_pct"],
            }

    baseline = walk_forward_model.build_walk_forward_model_report(
        baseline_days,
        entry_mode="auction",
        exit_mode="next_open",
        config=config,
    )
    changed = walk_forward_model.build_walk_forward_model_report(
        changed_days,
        entry_mode="auction",
        exit_mode="next_open",
        config=config,
    )

    assert baseline["windows"][:-1] == changed["windows"][:-1]
    assert baseline["phase_summaries"]["expanding_oos"] == changed["phase_summaries"]["expanding_oos"]
    assert baseline["model_contract"] == changed["model_contract"]
    assert baseline["calibration_scope"] == "locked_holdout_test_predictions"
    assert baseline["calibration_phases"]["expanding_oos"] == changed["calibration_phases"]["expanding_oos"]
    assert baseline["calibration"] == baseline["calibration_phases"]["locked_holdout"]
    assert baseline["calibration"] != changed["calibration"]


def test_model_report_limits_daily_plans_and_keeps_tail_research_only() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=12,
        calibration_days=3,
        test_days=4,
        holdout_days=5,
        min_training_samples=8,
        bootstrap_samples=20,
        estimator_count=8,
        minimum_fill_probability=0.0,
        minimum_seal_probability=0.0,
        minimum_profit_probability=0.0,
        minimum_expected_return_pct=-100.0,
        minimum_confidence_lower_pct=-100.0,
    )
    report = walk_forward_model.build_walk_forward_model_report(
        _history_days(32, candidates_per_day=4),
        entry_mode="tail",
        exit_mode="next_open",
        config=config,
    )

    selected = report["selected_candidates"]
    by_date: dict[str, int] = {}
    for row in selected:
        by_date[row["signal_date"]] = by_date.get(row["signal_date"], 0) + 1
        assert row["simulation_eligible"] is False
        assert row["execution_status"] == "tail_fill_unverifiable"
    assert selected
    assert max(by_date.values()) <= 2
    assert report["upgrade_status"] == "research_only"


def test_zero_trade_report_does_not_pass_risk_or_return_gates() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=12,
        calibration_days=3,
        test_days=4,
        holdout_days=5,
        min_training_samples=8,
        bootstrap_samples=20,
        estimator_count=8,
        minimum_fill_probability=1.1,
    )
    report = walk_forward_model.build_walk_forward_model_report(
        _history_days(32, candidates_per_day=3),
        entry_mode="auction",
        exit_mode="next_open",
        config=config,
    )
    gates = {row["code"]: row for row in report["acceptance_gates"]}

    assert report["selected_candidates"] == []
    assert report["ranked_candidates"]
    assert gates["drawdown"]["passed"] is False
    assert gates["holdout_return"]["passed"] is False
    assert gates["stress_return"]["passed"] is False


def test_report_range_keeps_leading_training_context() -> None:
    config = walk_forward_model.WalkForwardConfig(
        training_days=12,
        calibration_days=3,
        test_days=4,
        holdout_days=5,
        min_training_samples=8,
        bootstrap_samples=20,
        estimator_count=8,
    )
    days = _history_days(32, candidates_per_day=3)
    evaluation_start = date(2025, 1, 20)
    full = walk_forward_model.build_walk_forward_model_report(
        days,
        entry_mode="auction",
        exit_mode="next_open",
        config=config,
    )
    ranged = walk_forward_model.build_walk_forward_model_report(
        days,
        entry_mode="auction",
        exit_mode="next_open",
        evaluation_start=evaluation_start,
        config=config,
    )

    expected = [
        row for row in full["ranked_candidates"]
        if row["signal_date"] >= evaluation_start.isoformat()
    ]
    assert ranged["ranked_candidates"] == expected
    assert ranged["coverage"]["selected_trade_days"] == 13
    assert ranged["evaluation_range"]["start"] == "2025-01-20"


def test_model_report_api_forwards_shared_history_controls(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_report(start, end, entry_mode, exit_mode):
        captured.update(start=start, end=end, entry_mode=entry_mode, exit_mode=exit_mode)
        return {"status": "ready", "upgrade_status": "research_only", "windows": []}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_history_model_report", fake_report)

    response = TestClient(create_app()).get(
        "/api/limit-up/history/model-report",
        params={
            "start": "2024-01-15",
            "end": "2026-07-10",
            "entry_mode": "next_auction",
            "exit_mode": "next_close",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "start": date(2024, 1, 15),
        "end": date(2026, 7, 10),
        "entry_mode": "next_auction",
        "exit_mode": "next_close",
    }


def test_model_report_api_can_run_a_complete_board_lane_pool(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_report(start, end, entry_mode, exit_mode, *, board_lane=None):
        captured.update(
            start=start,
            end=end,
            entry_mode=entry_mode,
            exit_mode=exit_mode,
            board_lane=board_lane,
        )
        return {
            "status": "insufficient_training",
            "candidate_scope": "complete_board_lane_candidate_pool",
        }

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_history_model_report", fake_report)

    response = TestClient(create_app()).get(
        "/api/limit-up/history/model-report",
        params={"lane": "one_to_two", "exit_mode": "next_open"},
    )

    assert response.status_code == 200
    assert captured["board_lane"] == "one_to_two"
    assert response.json()["data"]["candidate_scope"] == "complete_board_lane_candidate_pool"


def test_model_report_api_rejects_invalid_date_range(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)

    response = TestClient(create_app()).get(
        "/api/limit-up/history/model-report",
        params={"start": "2026-07-10", "end": "2024-01-15"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_model_report_api_returns_structured_service_failure(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    def fail_report(*_args: object) -> dict[str, object]:
        raise RuntimeError("model failed")

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_history_model_report", fail_report)

    response = TestClient(create_app()).get("/api/limit-up/history/model-report")

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "LIMIT_UP_RESEARCH_ERROR"
    assert payload["error"]["detail"] == {"reason": "RuntimeError"}


def test_config_rejects_overlapping_calibration_window() -> None:
    with pytest.raises(ValueError, match="calibration_days"):
        replace(walk_forward_model.DEFAULT_CONFIG, calibration_days=252)


def _history_days(count: int, *, candidates_per_day: int = 2) -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    days: list[dict[str, object]] = []
    for offset in range(count):
        signal_date = start + timedelta(days=offset)
        candidates = [
            _candidate(
                signal_date.isoformat(),
                return_pct=(2.5 if (offset + index) % 3 else -1.5),
                sealed=(offset + index) % 4 != 0,
                index=index,
            )
            for index in range(candidates_per_day)
        ]
        days.append(
            {
                "trade_date": signal_date.isoformat(),
                "validation_phase": "locked_holdout" if offset >= count - 5 else "expanding_oos",
                "coverage": {
                    "reliable_trade_days": count,
                    "industry_membership_survivorship_risk": True,
                },
                "lanes": {
                    "auction": [dict(row) for row in candidates],
                    "sweep": [dict(row) for row in candidates],
                    "tail": [dict(row) for row in candidates],
                    "next_auction": [dict(row) for row in candidates],
                },
            }
        )
    return days


def _board_history_days(
    count: int,
    *,
    candidates_per_day: int,
) -> list[dict[str, object]]:
    days = _history_days(count, candidates_per_day=candidates_per_day)
    for day in days:
        pool = [
            {
                **candidate,
                "lane": "one_to_two",
                "decision": "eligible",
                "pool_rank": rank,
                "prior_limit_count_126": 2 + rank,
                "prior_seal_success_rate_126": 0.55 + rank * 0.03,
                "prior_position_120": 0.25 + rank * 0.05,
                "prior_industry_leader_rank": 1 if rank % 2 else 2,
                "prior_board": {
                    "is_sealed": True,
                    "first_limit_time": f"10:{rank * 5:02d}:00",
                    "last_limit_time": f"14:{rank * 5:02d}:00",
                    "open_times": rank % 4,
                    "seal_to_turnover_ratio": 0.03 + rank * 0.01,
                },
                "financial_risk": {
                    "level": "clear",
                    "blocked": False,
                    "reasons": [],
                },
            }
            for rank, candidate in enumerate(day["lanes"]["next_auction"], start=1)
        ]
        day["board_candidate_pool"] = {
            "first_board": [],
            "one_to_two": pool,
            "two_to_three": [],
            "high_board": [],
        }
        day["board_lanes"] = {
            "first_board": [],
            "one_to_two": pool[:1],
            "two_to_three": [],
            "high_board": [],
        }
    return days


def _candidate(
    signal_date: str,
    return_pct: float,
    *,
    sealed: bool,
    index: int = 0,
) -> dict[str, object]:
    signal = date.fromisoformat(signal_date)
    return {
        "vt_symbol": f"600{index:03d}.SSE",
        "name": f"样本{index}",
        "industry_name": "测试行业",
        "signal_date": signal_date,
        "result_date": (signal + timedelta(days=1)).isoformat(),
        "target_board": 1 if index % 2 == 0 else 2,
        "prior_streak": index % 2,
        "rank": index + 1,
        "action": "auction_buy",
        "known_at_signal": {
            "auction_gap_pct": 1.2 + index * 0.6,
            "prior_change_pct": -1.0 + index,
            "prior_return_5d_pct": float(index),
            "prior_return_20d_pct": float(index * 2),
            "prior_turnover_rate": 3.0 + index,
            "prior_amount_ratio_5d": 1.0 + index * 0.1,
            "prior_amplitude_pct": 4.0 + index,
            "prior_industry_heat_score": 55.0 + index,
            "prior_industry_leadership_score": 60.0 + index,
            "prior_industry_change_pct": 1.0 + index * 0.1,
            "prior_industry_return_5d_pct": 2.0 + index * 0.2,
            "prior_industry_advancing_rate": 0.5 + index * 0.01,
            "prior_industry_turnover_ratio_5d": 1.1 + index * 0.05,
            "prior_market_advancing_rate": 0.45 + (index % 2) * 0.1,
            "prior_market_failed_rate": 0.25 + (index % 2) * 0.05,
            "prior_market_one_to_two_rate": 0.2,
            "prior_market_two_to_three_rate": 0.15,
            "prior_market_phase": "repair" if index % 2 == 0 else "broad_rise",
        },
        "outcome": {
            "touched": sealed or index % 2 == 0,
            "sealed": sealed,
            "next_open_return_pct": return_pct,
            "next_close_return_pct": return_pct - 0.5,
        },
        "execution_confidence": "daily_open_proxy",
    }
