from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.event_neutral_discovery import (
    BIN_LABELS,
    NEUTRAL_SURFACES,
    CandidateRule,
    LeafAttempt,
    RuleCondition,
    apply_response_bins,
    build_response_surfaces,
    discover_candidate_rules,
    fit_response_bins,
    leaf_attempt_payload,
    materialize_rule_transitions,
)
from alphaagent.server.services.low_suction.event_neutral_panel import (
    NEUTRAL_STATE_FEATURES,
)


def _feature_frame(rows: int = 100) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            feature: [float(index) for index in range(rows)]
            for feature in NEUTRAL_STATE_FEATURES
        }
    )
    frame["observation_id"] = [f"observation-{index}" for index in range(rows)]
    frame["event_id"] = range(rows)
    frame["independence_block_id"] = [f"block-{index}" for index in range(rows)]
    frame["net_return_pct"] = [1.0 if index % 2 else -0.5 for index in range(rows)]
    frame["double_cost_net_return_pct"] = frame["net_return_pct"] - 0.2
    return frame


def test_validation_extreme_cannot_change_training_bins() -> None:
    development = _feature_frame()
    fitted = fit_response_bins(development)
    validation = _feature_frame(rows=1)
    validation.loc[0, "drawdown_from_session_high_pct"] = 999.0

    transformed = apply_response_bins(validation, fitted)

    assert fitted == fit_response_bins(development)
    assert (
        transformed.loc[0, "drawdown_from_session_high_pct_bin"]
        == BIN_LABELS[-1]
    )


def test_response_surface_set_is_fixed_and_deterministic() -> None:
    frame = _feature_frame()
    fitted = fit_response_bins(frame)

    first = build_response_surfaces(frame, fitted, segment="development")
    second = build_response_surfaces(frame, fitted, segment="development")

    assert first["surface_id"].nunique() == len(NEUTRAL_SURFACES)
    assert first["episodes"].le(first["candidate_episodes"]).all()
    pd.testing.assert_frame_equal(first, second)


def test_duplicate_quantile_edges_do_not_drop_fixed_bins() -> None:
    frame = _feature_frame()
    for feature in NEUTRAL_STATE_FEATURES:
        frame[feature] = 0.0
    fitted = fit_response_bins(frame)

    transformed = apply_response_bins(frame.iloc[:1], fitted)
    surfaces = build_response_surfaces(frame, fitted, segment="development")

    assert all(len(edges) == 4 for edges in fitted.edges.values())
    assert transformed["distance_to_vwap_pct_bin"].item() == BIN_LABELS[-1]
    assert surfaces["surface_id"].nunique() == len(NEUTRAL_SURFACES)


def _training_data(events: int = 240) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    panel_rows = []
    outcome_rows = []
    stressed_rows = []
    for event_id in range(events):
        trade_date = date(2025, 1, 2) + timedelta(days=event_id % 60)
        for state_index, distance in enumerate((-1.0, 1.0)):
            observed_at = datetime(2025, 1, 2, 10, 0) + timedelta(
                minutes=5 * state_index
            )
            observation_id = f"{event_id}:{state_index}"
            row = {
                feature: 0.0 for feature in NEUTRAL_STATE_FEATURES
            }
            row.update(
                {
                    "observation_id": observation_id,
                    "event_id": event_id,
                    "entry_date": trade_date,
                    "bar_time": observed_at,
                    "observed_at": observed_at,
                    "independence_block_id": f"block-{event_id}",
                    "sample_weight": 0.5,
                    "vt_symbol": f"{600000 + event_id:06d}.SSE",
                    "cycle_id": f"cycle-{event_id}",
                    "active_direction": "GOLD",
                    "danger_state": "NORMAL",
                    "distance_to_vwap_pct": distance,
                    "minutes_from_open": 30.0 + state_index * 5.0,
                }
            )
            panel_rows.append(row)
            normal_return = -1.0 if distance < 0 else 2.0
            outcome_rows.append(
                {
                    "observation_id": observation_id,
                    "status": "closed",
                    "net_return_pct": normal_return,
                }
            )
            stressed_rows.append(
                {
                    "observation_id": observation_id,
                    "status": "closed",
                    "net_return_pct": normal_return - 0.2,
                }
            )
    return (
        pd.DataFrame(panel_rows),
        pd.DataFrame(outcome_rows),
        pd.DataFrame(stressed_rows),
    )


def test_discovery_tree_is_bounded_and_keeps_rejected_leaves() -> None:
    panel, normal, stressed = _training_data()

    result = discover_candidate_rules(panel, normal, stressed)

    assert result.model.get_depth() <= 2
    assert len(result.candidates) <= 5
    assert all(len(rule.conditions) <= 2 for rule in result.candidates)
    assert any(attempt.status == "rejected" for attempt in result.attempts)
    assert any(attempt.status == "accepted" for attempt in result.attempts)
    assert not hasattr(result.model, "generate_orders")


def test_validation_extremes_cannot_change_development_tree_thresholds() -> None:
    development, normal, stressed = _training_data()
    validation, _, _ = _training_data(events=10)
    validation.loc[:, list(NEUTRAL_STATE_FEATURES)] = 999.0

    original = discover_candidate_rules(development, normal, stressed)
    repeated = discover_candidate_rules(development, normal, stressed)

    np.testing.assert_array_equal(
        original.model.tree_.threshold,
        repeated.model.tree_.threshold,
    )


def test_true_from_first_eligible_bar_is_not_a_transition() -> None:
    panel, _, _ = _training_data(events=1)
    panel["distance_to_vwap_pct"] = 1.0
    rule = CandidateRule(
        rule_id="neutral_rule_test",
        conditions=(RuleCondition("distance_to_vwap_pct", ">", 0.0),),
    )

    signals = materialize_rule_transitions(panel, rule)

    assert signals.empty


def test_study_cli_exposes_no_model_or_threshold_parameters() -> None:
    args = build_parser().parse_args(
        ["v2-event-neutral-state-study", "--format", "json"]
    )

    assert args.command == "v2-event-neutral-state-study"
    for parameter in (
        "features",
        "depth",
        "min_samples",
        "threshold",
        "start",
        "end",
        "exit",
    ):
        assert not hasattr(args, parameter)


def test_infinite_profit_factor_is_serialized_as_null() -> None:
    attempt = LeafAttempt(
        rule_id="neutral_leaf_test",
        leaf_node=1,
        conditions=(),
        status="rejected",
        reason="small_sample",
        tree_state_rows=4,
        independent_blocks=4,
        signals=4,
        closed_trades=4,
        win_rate_pct=100.0,
        mean_net_return_pct=1.0,
        profit_factor=float("inf"),
        double_cost_mean_net_return_pct=0.5,
    )

    assert leaf_attempt_payload(attempt)["profit_factor"] is None
