from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from math import isnan

import numpy as np
import pytest

from alphaagent.server.services.limit_up import preboard_decision_features as features
from alphaagent.server.services.limit_up import preboard_decision_model as model
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardPolicyThresholds,
)
from alphaagent.server.services.limit_up.preboard_decision_policy import (
    evaluate_preboard_decisions,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
)


def test_historical_and_live_projection_are_field_for_field_identical() -> None:
    historical, live = _equivalent_observations()

    historical_row = features.project_historical_decision_features(historical)
    live_row = features.project_live_decision_features(live)

    assert historical_row["feature_status"] == "scoreable"
    assert live_row["feature_status"] == "scoreable"
    assert historical_row["known_at"] == live_row["known_at"]
    assert historical_row["feature_values"] == live_row["feature_values"]
    assert historical_row["missing_fields"] == live_row["missing_fields"]
    assert historical_row["feature_fingerprint"] == live_row["feature_fingerprint"]
    assert historical_row["feature_names"] == list(features.MODEL_FEATURE_NAMES)
    assert historical_row["feature_values"]["gain_pct"] >= 3.0
    assert historical_row["feature_values"]["return_3m"] > 0.0
    assert historical_row["feature_values"]["quality_pool_rank"] == 1.0
    assert historical_row["source_quality"] == "official_historical_minute"
    assert live_row["source_quality"] == "sampled_quote_proxy"


def test_model_uses_quality_pool_cross_section_not_fake_market_fields() -> None:
    assert "quality_pool_count" in features.MODEL_FEATURE_NAMES
    assert "quality_pool_new_count_1m" in features.MODEL_FEATURE_NAMES
    assert "quality_pool_rank" in features.MODEL_FEATURE_NAMES
    assert "market_candidate_count_3pct" not in features.MODEL_FEATURE_NAMES
    assert "market_new_candidate_count_1m" not in features.MODEL_FEATURE_NAMES
    assert "same_minute_rank" not in features.MODEL_FEATURE_NAMES


def test_model_includes_causal_market_industry_and_recognition_context() -> None:
    expected = {
        "prior_limit_count_126",
        "prior_industry_turnover_ratio_5d",
        "prior_industry_heat_rank",
        "prior_industry_sealed_count",
        "prior_market_failed_rate",
        "prior_market_max_board",
        "prior_market_first_board_count",
        "prior_market_one_to_two_rate",
        "prior_market_two_to_three_rate",
    }

    assert expected.issubset(features.MODEL_FEATURE_NAMES)
    assert {
        "prior_market_phase_broad_rise",
        "prior_market_phase_repair",
        "prior_market_phase_mixed",
        "prior_market_phase_retreat",
    }.issubset(features.MODEL_FEATURE_NAMES)


def test_static_context_uses_candidate_values_and_explicit_missingness() -> None:
    historical, _live = _equivalent_observations()
    candidate = historical["candidate"]
    candidate.update(
        prior_market_phase="mixed",
        prior_limit_count_126=4,
        prior_market_failed_rate=27.5,
        prior_market_max_board=5,
        prior_industry_turnover_ratio_5d=1.34,
        prior_industry_heat_rank=None,
    )

    projected = features.project_historical_decision_features(historical)
    values = projected["feature_values"]

    assert values["prior_limit_count_126"] == 4.0
    assert values["prior_market_failed_rate"] == 27.5
    assert values["prior_market_max_board"] == 5.0
    assert values["prior_industry_turnover_ratio_5d"] == 1.34
    assert values["prior_industry_heat_rank"] is None
    assert values["prior_industry_heat_rank_missing"] == 1.0
    assert values["prior_market_phase_mixed"] == 1.0
    assert values["prior_market_phase_broad_rise"] == 0.0


def test_same_industry_diffusion_is_shared_by_historical_and_live() -> None:
    historical, live = _equivalent_observations()
    historical["candidate"]["industry_id"] = "801080"
    for observation, field in (
        (historical, "cross_section_snapshots"),
        (live, "quality_pool_snapshots"),
    ):
        for snapshot in observation[field]:
            for candidate in snapshot["candidates"]:
                candidate["industry_id"] = "801080"
                if candidate["vt_symbol"] == "600002.SSE":
                    candidate["change_pct"] = 5.5

    historical_row = features.project_historical_decision_features(historical)
    live_row = features.project_live_decision_features(live)
    values = historical_row["feature_values"]

    assert historical_row["feature_values"] == live_row["feature_values"]
    assert values["same_industry_candidate_count_3pct"] == 2.0
    assert values["same_industry_candidate_count_5pct"] == 2.0
    assert values["same_industry_candidate_count_7pct"] == 1.0
    assert values["same_industry_candidate_count_9pct"] == 0.0
    assert values["same_industry_candidate_rank"] == 1.0
    assert values["same_industry_leader_gap_pct"] == 0.0


def test_live_projection_uses_only_completed_capture_minutes() -> None:
    historical, live = _equivalent_observations()
    decision_at = historical["decision_at"]
    final_historical_bar = historical["minute_bars"][-1]

    live_bars = features.completed_minute_bars(live, decision_at)
    projected = features.project_live_decision_features(live)

    assert live_bars[-1]["bar_time"] == final_historical_bar["bar_time"]
    assert live_bars[-1]["close_price"] == final_historical_bar["close_price"]
    assert all(row["bar_time"] <= decision_at for row in live_bars)
    assert projected["feature_status"] == "scoreable"
    assert projected["feature_values"]["gain_pct"] == pytest.approx(
        (final_historical_bar["close_price"] / historical["previous_close"] - 1.0)
        * 100.0
    )


def test_historical_and_live_inputs_share_model_and_policy_outcome() -> None:
    historical, live = _equivalent_observations()
    historical_row = features.project_historical_decision_features(historical)
    live_row = features.project_live_decision_features(live)
    decision_at = historical["decision_at"]
    last_price = historical["minute_bars"][-1]["close_price"]
    common = {
        "trade_date": decision_at.date().isoformat(),
        "decision_at": decision_at.isoformat(),
        "vt_symbol": historical["vt_symbol"],
        "board_lane": "first_board",
        "state": "near_limit",
        "change_pct": historical_row["feature_values"]["gain_pct"],
        "last_price": last_price,
        "limit_price": historical["limit_price"],
        "quality_gate_passed": True,
        "public_quality_contract_version": "limit-up-core-abc-v2",
        "public_quality_status": "qualified_waiting_trigger",
        "public_quality_preparation_passed": True,
        "quality_priority_tier": "A_industry_expanding",
        "quality_expected_d1_net_return_pct": 1.8,
        "quality_win_probability": 0.70,
        "preparation_environment_passed": True,
        "execution_environment_passed": True,
        "entry_window_passed": True,
        "profitability_gate_passed": True,
        "historical_prior_status": "ready",
        "expected_d1_net_return_pct": 1.8,
        "d1_win_probability": 0.70,
        "seal_probability_given_touch": 0.76,
        "d1_win_probability_given_seal": 0.64,
        "lane_support_score": 61.0,
    }
    bundle = _ready_model_bundle()
    thresholds = PreboardPolicyThresholds(
        minimum_touch_probability_3m=0.70,
        minimum_eventual_touch_probability=0.75,
        calibrated_dates=(date(2026, 7, 1),),
        fingerprint="sha256:shared-thresholds",
    )

    historical_decision = evaluate_preboard_decisions(
        [{**common, **historical_row}],
        model_bundle=bundle,
        thresholds=thresholds,
    )[0]
    live_decision = evaluate_preboard_decisions(
        [{**common, **live_row}],
        model_bundle=bundle,
        thresholds=thresholds,
    )[0]

    assert historical_row["source_kind"] != live_row["source_kind"]
    assert historical_row["feature_fingerprint"] == live_row["feature_fingerprint"]
    shared_result_fields = (
        "model_version",
        "model_fingerprint",
        "probability_status",
        "touch_probability_3m",
        "eventual_touch_probability",
        "decision_state",
        "daily_slot",
        "policy_version",
        "policy_fingerprint",
    )
    assert {
        field: historical_decision[field] for field in shared_result_fields
    } == {field: live_decision[field] for field in shared_result_fields}
    assert historical_decision["decision_state"] == "actionable"
    assert historical_decision["policy_version"] == PREBOARD_DECISION_VERSION


def test_quality_gate_is_required_even_for_nine_percent_stock() -> None:
    historical, _live = _equivalent_observations()
    historical["candidate"]["quality_gate_passed"] = False

    projected = features.project_historical_decision_features(historical)

    assert projected["feature_status"] == "not_scoreable_quality_gate_failed"
    assert projected["feature_values"] == {}


def test_future_outcomes_and_bars_do_not_change_current_projection() -> None:
    historical, _live = _equivalent_observations()
    baseline = features.project_historical_decision_features(historical)
    changed = deepcopy(historical)
    changed.update(
        physical_touch_at="2026-07-20T10:25:00",
        first_limit_time="10:25:00",
        final_sealed=True,
        d1_close_price=999.0,
        net_return_pct=99.0,
    )
    future_bar = dict(changed["minute_bars"][-1])
    future_bar["bar_time"] = changed["decision_at"] + timedelta(minutes=1)
    future_bar["close_price"] = 999.0
    changed["minute_bars"].append(future_bar)

    projected = features.project_historical_decision_features(changed)

    assert projected["feature_values"] == baseline["feature_values"]
    assert projected["feature_fingerprint"] == baseline["feature_fingerprint"]


def test_forbidden_key_in_model_feature_overrides_raises() -> None:
    historical, _live = _equivalent_observations()
    historical["feature_values"] = {"first_limit_time": "10:25:00"}

    with pytest.raises(features.FutureFeatureError, match="first_limit_time"):
        features.project_historical_decision_features(historical)


def test_already_touched_prefix_is_not_scoreable() -> None:
    historical, _live = _equivalent_observations()
    historical["minute_bars"][-1]["high_price"] = historical["limit_price"]

    projected = features.project_historical_decision_features(historical)

    assert projected["feature_status"] == "not_scoreable_already_touched"


def test_missing_transaction_flow_is_missing_not_zero() -> None:
    historical, _live = _equivalent_observations()
    historical["transaction_feature_at"] = historical["decision_at"] + timedelta(
        minutes=1
    )

    projected = features.project_historical_decision_features(historical)
    vector = features.model_feature_vector(projected)

    assert projected["feature_status"] == "scoreable"
    assert projected["feature_values"]["transaction_flow_missing"] == 1.0
    assert set(TRANSACTION_FEATURE_NAMES).issubset(projected["missing_fields"])
    assert vector is not None
    tx_index = projected["feature_names"].index(TRANSACTION_FEATURE_NAMES[0])
    assert isnan(vector[tx_index])


def test_time_features_use_trading_minutes_and_skip_lunch() -> None:
    assert features.session_minute_index(datetime(2026, 7, 20, 11, 30)) == 120
    assert features.session_minute_index(datetime(2026, 7, 20, 12, 30)) == 120
    assert features.session_minute_index(datetime(2026, 7, 20, 13, 0)) == 120
    assert features.session_minute_index(datetime(2026, 7, 20, 14, 30)) == 210


def test_lane_prefix_uses_only_the_requested_completed_bars() -> None:
    bars = [
        {
            "bar_time": datetime(2026, 7, 20, 10, minute),
            "close_price": 10.0 + minute / 100,
        }
        for minute in range(1, 9)
    ]

    prefix = features.build_lane_prefix(
        bars,
        6,
        previous_close=10.0,
        bar_minutes=1,
    )

    assert prefix["point_count"] == 7
    assert prefix["last_point_time"] == "10:07:00"
    assert prefix["last_pct"] == 0.7


def test_batch_lane_prefixes_match_every_causal_point() -> None:
    bars = [
        {
            "bar_time": datetime(2026, 7, 20, 10, minute),
            "close_price": 10.0 + minute / 100,
        }
        for minute in range(1, 9)
    ]

    batched = features.build_lane_prefixes(bars, previous_close=10.0)

    assert batched == [
        features.build_lane_prefix(
            bars,
            index,
            previous_close=10.0,
        )
        for index in range(len(bars))
    ]


def _equivalent_observations() -> tuple[dict[str, object], dict[str, object]]:
    first_bar_close = datetime(2026, 7, 20, 10, 1)
    closes = [10.00 + index * 0.025 for index in range(20)]
    minute_bars: list[dict[str, object]] = []
    live_frames: list[dict[str, object]] = []
    cumulative_volume = 0.0
    cumulative_turnover = 0.0
    for index, close in enumerate(closes):
        bar_time = first_bar_close + timedelta(minutes=index)
        capture_minute = bar_time - timedelta(minutes=1)
        open_price = closes[index - 1] if index else 10.00
        high_price = max(open_price, close) + 0.01
        low_price = min(open_price, close) - 0.01
        volume = 1_000.0 + index * 10.0
        turnover = volume * close
        minute_bars.append(
            {
                "bar_time": bar_time,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close,
                "volume": volume,
                "turnover": turnover,
            }
        )
        prices = (open_price, high_price, low_price, close)
        for part, price in enumerate(prices, start=1):
            live_frames.append(
                {
                    "captured_at": capture_minute
                    + timedelta(seconds=part * 15 - 1),
                    "last_price": price,
                    "volume": cumulative_volume + volume * part / 4,
                    "turnover": cumulative_turnover + turnover * part / 4,
                }
            )
        cumulative_volume += volume
        cumulative_turnover += turnover

    decision_at = first_bar_close + timedelta(minutes=19, seconds=5)
    live_frames.append(
        {
            "captured_at": decision_at - timedelta(seconds=1),
            "last_price": 10.64,
            "volume": cumulative_volume + 500.0,
            "turnover": cumulative_turnover + 5_320.0,
        }
    )
    transaction = {
        name: round(0.05 + index * 0.01, 8)
        for index, name in enumerate(TRANSACTION_FEATURE_NAMES)
    }
    common = {
        "vt_symbol": "600001.SSE",
        "decision_at": decision_at,
        "previous_close": 9.70,
        "limit_price": 10.67,
        "candidate": {
            "quality_gate_passed": True,
            "lane_support_score": 61.0,
            "lane_entry_quality_score": 72.0,
            "main_net_inflow_delta_3m": 8_000_000.0,
            "sector_change_1m": 0.4,
            "sector_breadth_3pct": 0.3,
            "sector_candidate_acceleration_3m": 2.0,
        },
        "candidate_first_observed_at": first_bar_close,
        "transaction_status": "flow_ready",
        "transaction_feature_at": first_bar_close + timedelta(minutes=19),
        "transaction_features": transaction,
    }
    historical = {
        **common,
        "source_quality": "official_historical_minute",
        "minute_bars": minute_bars,
        "cross_section_snapshots": _cross_section_snapshots(
            first_bar_close,
            closes,
            live=False,
        ),
    }
    live = {
        **common,
        "source_quality": "sampled_quote_proxy",
        "completed_minute_bars": minute_bars,
        "quality_pool_snapshots": _cross_section_snapshots(
            first_bar_close,
            closes,
            live=False,
        ),
        "candidate_frames": live_frames,
        "initial_cumulative_volume": 0.0,
        "initial_cumulative_turnover": 0.0,
        "cross_section_frames": [
            *_cross_section_snapshots(first_bar_close, closes, live=True),
            {
                "captured_at": decision_at - timedelta(seconds=1),
                "candidates": [
                    {
                        "vt_symbol": "600001.SSE",
                        "change_pct": 9.69,
                        "last_price": 10.64,
                        "limit_price": 10.67,
                    }
                ],
            },
        ],
    }
    return historical, live


def _cross_section_snapshots(
    first_bar_close: datetime,
    closes: list[float],
    *,
    live: bool,
) -> list[dict[str, object]]:
    rows = []
    for index, close in enumerate(closes):
        bar_close = first_bar_close + timedelta(minutes=index)
        captured_at = bar_close - timedelta(seconds=1) if live else bar_close
        rows.append(
            {
                "captured_at": captured_at,
                "candidates": [
                    {
                        "vt_symbol": "600001.SSE",
                        "change_pct": (close / 9.70 - 1.0) * 100.0,
                        "last_price": close,
                        "limit_price": 10.67,
                    },
                    {
                        "vt_symbol": "600002.SSE",
                        "change_pct": 2.0 + index * 0.01,
                        "last_price": 10.2,
                        "limit_price": 11.0,
                    },
                ],
            }
        )
    return rows


class _ConstantEstimator:
    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        positive = np.full(matrix.shape[0], 0.8, dtype=float)
        return np.column_stack((1.0 - positive, positive))


class _IdentityCalibrator:
    def predict(self, values: np.ndarray) -> np.ndarray:
        return values


def _ready_model_bundle() -> model.PreboardModelBundle:
    head = model._ProbabilityHead(
        status="ready",
        estimator=_ConstantEstimator(),
        calibrator=_IdentityCalibrator(),
        feature_indices=tuple(range(len(features.MODEL_FEATURE_NAMES))),
    )
    return model.PreboardModelBundle(
        status="ready",
        feature_version=PREBOARD_DECISION_VERSION,
        model_version=PREBOARD_DECISION_VERSION,
        fit_dates=(date(2026, 6, 1),),
        calibration_dates=(date(2026, 7, 1),),
        feature_names=tuple(features.MODEL_FEATURE_NAMES),
        touch_3m_model=head,
        eventual_touch_model=head,
        fingerprint="sha256:shared-model",
        training_input_fingerprint="sha256:shared-input",
        head_reports={},
    )
