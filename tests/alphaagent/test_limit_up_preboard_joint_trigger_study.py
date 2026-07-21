from __future__ import annotations

from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import numpy as np

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD,
    ACTION_TARGET_FIELD,
    JointTriggerModelFit,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_study import (
    _acceptance_report,
    build_research_fingerprints,
    build_forward_joint_shadow,
    build_joint_replay_orders,
    prepare_forward_joint_rows,
    render_joint_trigger_markdown,
    replay_joint_account,
)


def test_joint_replay_keeps_relay_and_uses_joint_probability() -> None:
    action_rows = enrich_same_minute_competition(
        [
            _signal("600001.SSE", "10:00:00", 0.8, 10.5),
            _signal("600001.SSE", "10:01:00", 0.82, 10.51),
            _signal("600002.SSE", "10:00:00", 0.4, 10.4),
            _signal("600002.SSE", "10:01:00", 0.4, 10.41),
        ]
    )
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

    bundle = build_joint_replay_orders(
        action_rows=action_rows,
        formal_orders=[relay],
        action_threshold=0.75,
    )

    assert [row["vt_symbol"] for row in bundle["action_signals"]] == [
        "600001.SSE"
    ]
    assert [row["vt_symbol"] for row in bundle["combined_orders"]] == [
        "600010.SSE",
        "600001.SSE",
    ]
    assert bundle["early_orders"][0]["algorithm"] == "profitable_formal_touch_3m"
    assert bundle["early_orders"][0][ACTION_SCORE_FIELD] == 0.82

    account = replay_joint_account(
        bundle["combined_orders"],
        _daily_bars(),
        [date(2026, 7, 16), date(2026, 7, 17)],
    )
    buys = [row for row in account["orders"] if row["side"] == "BUY"]
    assert [(row["vt_symbol"], row["status"]) for row in buys] == [
        ("600010.SSE", "filled"),
        ("600001.SSE", "filled"),
    ]


def test_acceptance_requires_original_account_identity_and_cash_results() -> None:
    validation = {
        "identity": {
            "selection_count": 34,
            "formal_identity_precision_pct": 80.0,
            "reachable_formal_recall_pct": 40.0,
        },
        "account_identity": {"precision_pct": 75.0},
        "accounts": {
            "formal_touch": {"win_rate": 70.0},
            "joint_action": {
                "trade_count": 20,
                "win_rate": 69.0,
                "total_return_pct": 12.0,
                "max_drawdown_pct": -6.0,
            },
            "joint_action_double_cost": {"total_return_pct": 9.0},
        },
    }
    blocks = [
        {"accounts": {"joint_action": {"trade_count": 2, "total_return_pct": value}}}
        for value in (1.0, 0.5, 0.2, -0.1, -0.5)
    ]

    accepted = _acceptance_report(
        validation,
        validation_blocks=blocks,
        models=(SimpleNamespace(status="ready"), SimpleNamespace(status="ready")),
        threshold=SimpleNamespace(status="ready"),
        baseline_parity={"passed": True},
    )
    rejected = _acceptance_report(
        {**validation, "account_identity": {"precision_pct": 50.0}},
        validation_blocks=blocks,
        models=(SimpleNamespace(status="ready"), SimpleNamespace(status="ready")),
        threshold=SimpleNamespace(status="ready"),
        baseline_parity={"passed": True},
    )

    assert accepted["passed"] is True
    assert rejected["passed"] is False
    assert rejected["checks"]["minimum_70pct_original_account_identity_precision"] is False


def test_joint_markdown_keeps_candidate_account_and_joint_metrics_distinct() -> None:
    report = {
        "study_version": "test-v3",
        "status": "ready_historical_rejected",
        "decision": "historical_rejected_no_live_promotion",
        "dataset": {"candidate_pair_count": 10, "observable_prefix_count": 100},
        "models": {
            "prepare_5m": {"status": "ready", "training_pair_count": 5},
            "joint_action_3m": {
                "status": "ready",
                "training_pair_count": 5,
                "fingerprint": "abc",
            },
        },
        "threshold_selection": {"status": "ready", "threshold": 0.75},
        "phases": {
            "validation": {
                "identity": {
                    "selection_count": 4,
                    "formal_identity_precision_pct": 75.0,
                    "horizon_precision_pct": 50.0,
                    "reachable_formal_recall_pct": 40.0,
                },
                "joint_quality": {
                    "joint_precision_pct": 50.0,
                    "d1_win_rate_pct": 50.0,
                },
                "account_identity": {"precision_pct": 25.0, "recall_pct": 20.0},
                "accounts": {
                    "formal_touch": {
                        "trade_count": 3,
                        "win_rate": 66.67,
                        "total_return_pct": 8.0,
                        "max_drawdown_pct": -2.0,
                        "profit_factor": 2.5,
                    },
                    "joint_action": {
                        "trade_count": 3,
                        "win_rate": 33.33,
                        "total_return_pct": -4.0,
                        "max_drawdown_pct": -5.0,
                    },
                    "joint_action_double_cost": {},
                    "joint_action_conservative": {},
                },
            }
        },
        "validation_blocks": [],
        "acceptance": {"checks": {}},
        "forward_validation": {},
        "limitations": [],
    }

    markdown = render_joint_trigger_markdown(report)

    assert "候选身份精度" in markdown
    assert "原账户身份精度" in markdown
    assert "联合标签精度" in markdown
    assert "25.00%" in markdown
    assert "-4.00%" in markdown
    assert "共用规则后股票日：10" in markdown
    assert "2.5000" in markdown


def test_research_fingerprints_bind_dates_model_and_threshold() -> None:
    inputs = {
        "date_split": {
            "fit": {
                "start": "2026-01-01",
                "end": "2026-03-01",
                "count": 44,
                "dates": ["2026-01-01", "2026-01-02"],
            },
            "calibration": {
                "start": "2026-03-02",
                "end": "2026-03-20",
                "count": 15,
                "dates": ["2026-03-02", "2026-03-03"],
            },
            "validation": {
                "start": "2026-03-21",
                "end": "2026-05-01",
                "count": 30,
                "dates": ["2026-03-21", "2026-03-22"],
            },
        },
        "models": {"joint_action_3m": {"fingerprint": "model-a"}},
        "threshold_selection": {
            "threshold": 0.75,
            "calibration_dates": ["2026-03-02", "2026-03-03"],
        },
    }

    baseline = build_research_fingerprints(**inputs)
    repeated = build_research_fingerprints(**deepcopy(inputs))
    changed_dates = deepcopy(inputs)
    changed_dates["date_split"]["validation"]["dates"][1] = "2026-03-23"
    changed_threshold = deepcopy(inputs)
    changed_threshold["threshold_selection"]["threshold"] = 0.80

    assert baseline == repeated
    assert baseline["date_split"].startswith("sha256:")
    assert baseline["date_split"] != build_research_fingerprints(**changed_dates)["date_split"]
    assert baseline["action_policy"] != build_research_fingerprints(
        **changed_threshold
    )["action_policy"]
    assert baseline["action_policy"] != build_research_fingerprints(
        **inputs,
        confirmation_minutes=1,
    )["action_policy"]
    touch_models = {"action_touch_3m": {"fingerprint": "model-b"}}
    assert baseline["action_policy"] != build_research_fingerprints(
        **{**inputs, "models": touch_models},
        action_model_key="action_touch_3m",
        confirmation_minutes=1,
    )["action_policy"]


def test_forward_joint_rows_fail_closed_on_freshness_and_incomplete_minute() -> None:
    valid = _forward_signal("600001.SSE", "10:01:00")
    stale = {**_forward_signal("600002.SSE", "10:01:00"), "frame_is_stale": True}
    wrong_day = {
        **_forward_signal("600003.SSE", "10:01:00"),
        "source_trade_date": date(2026, 7, 19),
    }
    missing_quote = {
        **_forward_signal("600004.SSE", "10:01:00"),
        "quote_observed_at": None,
    }
    incomplete_minute = {
        **_forward_signal("600005.SSE", "10:00:00"),
        "captured_at": "2026-07-20T10:01:05+08:00",
    }

    rows = prepare_forward_joint_rows(
        [stale, wrong_day, missing_quote, incomplete_minute, valid]
    )

    assert len(rows) == 1
    assert rows[0]["vt_symbol"] == "600001.SSE"
    assert rows[0]["quote_age_seconds"] == 5.0


def test_forward_joint_shadow_scores_missing_dynamic_fields_without_execution() -> None:
    rows = [
        _forward_signal("600001.SSE", "10:00:00"),
        {
            **_forward_signal("600001.SSE", "10:01:00"),
            "market_timing_state": "GOLD_ACTIVE",
        },
    ]
    prepare_model = _forward_model([0.7, 0.8])
    action_model = _forward_model([0.8, 0.85])

    report = build_forward_joint_shadow(
        rows,
        models={
            "prepare_5m": prepare_model,
            "joint_action_3m": action_model,
        },
        action_threshold=0.75,
    )

    assert report["scoreable_observation_count"] == 2
    assert report["research_prepare_count"] == 1
    assert report["research_action_count"] == 1
    assert report["execution_effect"] == "none_research_only"
    assert all(event["actionable"] is False for event in report["recent_research_events"])
    action_event = next(
        event
        for event in report["recent_research_events"]
        if event["research_state"] == "research_action"
    )
    assert action_event["action_score"] == 0.85
    concept = report["dynamic_overlay"]["numeric_fields"][
        "concept_change_acceleration_1m"
    ]
    assert concept["coverage_count"] == 0
    assert report["dynamic_overlay"]["market_timing_state"]["action_counts"] == {
        "GOLD_ACTIVE": 1
    }


def _forward_model(probabilities: list[float]) -> JointTriggerModelFit:
    class Pipeline:
        def predict_proba(self, matrix):
            assert matrix.shape[0] == len(probabilities)
            return np.asarray([[1 - value, value] for value in probabilities])

    return JointTriggerModelFit(
        status="ready",
        pipeline=Pipeline(),
        target_field=ACTION_TARGET_FIELD,
        training_row_count=2,
        training_pair_count=1,
        class_counts={"0": 1, "1": 1},
        fit_dates=("2026-07-01",),
        scaler_mean_by_feature={},
        scaler_scale_by_feature={},
        coefficient_by_feature={},
        intercept=None,
        fingerprint="test",
    )


def _forward_signal(symbol: str, signal_time: str) -> dict[str, object]:
    row = _signal(symbol, signal_time, 0.0, 10.5)
    row.update(
        {
            "signal_at": f"2026-07-20T{signal_time}",
            "signal_date": "2026-07-20",
            "captured_at": f"2026-07-20T{signal_time[:5]}:05+08:00",
            "quote_observed_at": f"2026-07-20T{signal_time[:5]}:00+08:00",
            "frame_is_stale": False,
            "source_trade_date": date(2026, 7, 20),
            "profitability_gate_sample_count": 8,
            "profitability_gate_combined_rate": 45.0,
        }
    )
    return row


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
        "signal_time": signal_time,
        "entry_time": signal_time,
        "entry_price": entry_price,
        "signal_price": entry_price,
        "limit_price": 11.0,
        "fillable": True,
        "before_first_limit_touch": True,
        "shared_strategy_passed": True,
        "lane": "first_board",
        "support_score": 70.0,
        "entry_quality_score": 72.0,
        "rank_score": score * 100,
        "profitability_gate_sample_count": 8,
        "profitability_gate_combined_rate": 45.0,
        ACTION_SCORE_FIELD: score,
        "outcome": {"next_close_price": 11.2},
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


def _daily_bars() -> list[dict[str, object]]:
    return [
        {
            "vt_symbol": symbol,
            "trade_date": day,
            "close_price": close,
        }
        for symbol, first, second in (
            ("600010.SSE", 10.0, 10.5),
            ("600001.SSE", 10.5, 11.2),
        )
        for day, close in (
            (date(2026, 7, 16), first),
            (date(2026, 7, 17), second),
        )
    ]
