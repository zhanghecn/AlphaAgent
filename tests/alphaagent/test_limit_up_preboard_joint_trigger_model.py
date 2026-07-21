from __future__ import annotations

from copy import deepcopy
from datetime import date

import numpy as np

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD,
    ACTION_TARGET_FIELD,
    PREPARE_SCORE_FIELD,
    PREPARE_TARGET_FIELD,
    JointTriggerModelFit,
    attach_joint_trigger_targets,
    calibrate_joint_threshold,
    fit_joint_trigger_model,
    joint_training_batch,
    probability_calibration_report,
    score_frozen_joint_probability,
    score_joint_trigger_rows,
)


def test_joint_targets_require_imminent_formal_touch_and_positive_return() -> None:
    rows = [
        _row("600001.SSE", "10:00:00", net_return=2.0),
        _row("600002.SSE", "10:00:00", net_return=-1.0),
        _row("600003.SSE", "10:00:00", net_return=3.0),
        _row("600004.SSE", "10:00:00", net_return=4.0),
    ]
    orders = [
        _formal_order("600001.SSE", "10:03:00"),
        _formal_order("600002.SSE", "10:03:00"),
        _formal_order("600004.SSE", "10:04:00"),
    ]

    labeled = attach_joint_trigger_targets(rows, orders)

    assert labeled[0][PREPARE_TARGET_FIELD] is True
    assert labeled[0][ACTION_TARGET_FIELD] is True
    assert labeled[1][ACTION_TARGET_FIELD] is False
    assert labeled[2][ACTION_TARGET_FIELD] is False
    assert labeled[3][PREPARE_TARGET_FIELD] is True
    assert labeled[3][ACTION_TARGET_FIELD] is False


def test_joint_training_weights_total_one_per_stock_day() -> None:
    rows = enrich_same_minute_competition(
        [
            _row("600001.SSE", "10:00:00", target=False),
            _row("600001.SSE", "10:01:00", target=False),
            _row("600002.SSE", "10:00:00", target=True),
        ]
    )

    _, _, weights, pairs = joint_training_batch(
        rows,
        allowed_dates={date(2026, 7, 16)},
        target_field=ACTION_TARGET_FIELD,
    )

    totals: dict[tuple[str, str], float] = {}
    for pair, weight in zip(pairs, weights, strict=True):
        totals[pair] = totals.get(pair, 0.0) + float(weight)
    assert totals == {
        ("600001.SSE", "2026-07-16"): 1.0,
        ("600002.SSE", "2026-07-16"): 1.0,
    }


def test_joint_fit_uses_natural_prevalence_and_ignores_validation_labels() -> None:
    rows = enrich_same_minute_competition(
        [
            _row(
                f"60000{index}.SSE",
                "10:00:00",
                signal_date="2026-07-14",
                gain=4.0 + index,
                target=index % 2 == 0,
            )
            for index in range(1, 5)
        ]
        + [
            _row(
                "600010.SSE",
                "10:00:00",
                signal_date="2026-07-15",
                gain=9.0,
                target=True,
            )
        ]
    )

    model = fit_joint_trigger_model(
        rows,
        fit_dates={date(2026, 7, 14)},
    )
    changed = deepcopy(rows)
    changed[-1][ACTION_TARGET_FIELD] = False
    changed_model = fit_joint_trigger_model(
        changed,
        fit_dates={date(2026, 7, 14)},
    )

    assert model.status == "ready"
    assert model.pipeline.named_steps["logistic"].class_weight is None
    assert model.fingerprint == changed_model.fingerprint
    reconstructed = score_frozen_joint_probability(rows[0], model)
    assert reconstructed is not None
    assert model.probability(rows[0]) is not None
    assert abs(reconstructed - model.probability(rows[0])) < 1e-8


def test_joint_fit_weights_scaler_and_loss_equally_by_stock_day() -> None:
    rows = enrich_same_minute_competition(
        [
            _row("600001.SSE", "10:00:00", gain=4.0, target=False),
            _row("600002.SSE", "10:00:00", gain=7.0, target=True),
            _row("600003.SSE", "10:00:00", gain=9.0, target=True),
        ]
    )
    duplicated = deepcopy(rows)
    repeated = deepcopy(rows[0])
    repeated["signal_time"] = "10:01:00"
    repeated["signal_at"] = "2026-07-16T10:01:00"
    duplicated.append(repeated)

    baseline = fit_joint_trigger_model(
        rows,
        fit_dates={date(2026, 7, 16)},
    )
    repeated_fit = fit_joint_trigger_model(
        duplicated,
        fit_dates={date(2026, 7, 16)},
    )

    assert baseline.status == "ready"
    assert baseline.fingerprint == repeated_fit.fingerprint


def test_joint_scoring_calls_pipeline_once_for_all_rows() -> None:
    rows = enrich_same_minute_competition(
        [
            _row("600001.SSE", "10:00:00"),
            _row("600002.SSE", "10:00:00", gain=8.0),
        ]
    )

    class CountingPipeline:
        calls = 0

        def predict_proba(self, matrix):
            self.calls += 1
            assert matrix.shape[0] == 2
            return np.asarray([[0.8, 0.2], [0.3, 0.7]])

    pipeline = CountingPipeline()
    model = JointTriggerModelFit(
        status="ready",
        pipeline=pipeline,
        target_field=ACTION_TARGET_FIELD,
        training_row_count=2,
        training_pair_count=2,
        class_counts={"0": 1, "1": 1},
        fit_dates=("2026-07-14",),
        scaler_mean_by_feature={},
        scaler_scale_by_feature={},
        coefficient_by_feature={},
        intercept=None,
        fingerprint="test",
    )

    scored = score_joint_trigger_rows(rows, model)
    prepared = score_joint_trigger_rows(
        rows,
        model,
        score_field=PREPARE_SCORE_FIELD,
    )

    assert pipeline.calls == 2
    assert [row[ACTION_SCORE_FIELD] for row in scored] == [0.2, 0.7]
    assert [row[PREPARE_SCORE_FIELD] for row in prepared] == [0.2, 0.7]


def test_joint_threshold_reads_only_calibration_dates() -> None:
    rows = [
        _scored_row("600001.SSE", "10:00:00", 0.8, True),
        _scored_row("600001.SSE", "10:01:00", 0.8, True),
        _scored_row("600002.SSE", "10:00:00", 0.4, False),
        _scored_row("600002.SSE", "10:01:00", 0.4, False),
        _scored_row(
            "600003.SSE",
            "10:00:00",
            0.99,
            False,
            signal_date="2026-07-16",
        ),
        _scored_row(
            "600003.SSE",
            "10:01:00",
            0.99,
            False,
            signal_date="2026-07-16",
        ),
    ]

    baseline = calibrate_joint_threshold(
        rows,
        calibration_dates={date(2026, 7, 15)},
        thresholds=(0.35, 0.75),
        minimum_selection_count=1,
    )
    changed = deepcopy(rows)
    changed[-1][ACTION_SCORE_FIELD] = 0.01
    changed[-1][ACTION_TARGET_FIELD] = True
    repeated = calibrate_joint_threshold(
        changed,
        calibration_dates={date(2026, 7, 15)},
        thresholds=(0.35, 0.75),
        minimum_selection_count=1,
    )

    assert baseline.status == "ready"
    assert baseline.threshold == 0.75
    assert baseline == repeated


def test_joint_threshold_scores_the_selected_minute_not_a_later_positive_minute() -> None:
    rows = [
        _scored_row("600001.SSE", "10:00:00", 0.8, False),
        _scored_row("600001.SSE", "10:01:00", 0.8, False),
        _scored_row("600001.SSE", "10:02:00", 0.1, True),
        _scored_row("600002.SSE", "10:00:00", 0.8, True),
        _scored_row("600002.SSE", "10:01:00", 0.8, True),
    ]

    selection = calibrate_joint_threshold(
        rows,
        calibration_dates={date(2026, 7, 15)},
        thresholds=(0.75,),
        minimum_selection_count=1,
    )

    assert selection.status == "ready"
    assert selection.selected_metrics["selection_count"] == 2
    assert selection.selected_metrics["joint_true_positive_count"] == 1
    assert selection.selected_metrics["joint_precision"] == 0.5
    assert selection.selected_metrics["reachable_recall"] == 0.5


def test_probability_calibration_reports_brier_and_fixed_bins() -> None:
    rows = [
        _scored_row("600001.SSE", "10:00:00", 0.2, False),
        _scored_row("600002.SSE", "10:00:00", 0.8, True),
        _scored_row(
            "600003.SSE",
            "10:00:00",
            0.99,
            False,
            signal_date="2026-07-16",
        ),
    ]

    report = probability_calibration_report(
        rows,
        allowed_dates={date(2026, 7, 15)},
        bin_count=5,
    )

    assert report["observation_count"] == 2
    assert report["positive_count"] == 1
    assert report["base_rate_pct"] == 50.0
    assert report["brier_score"] == 0.04
    assert report["score_distribution"] == {
        "p25": 0.35,
        "median": 0.5,
        "p75": 0.65,
    }
    assert [row["observation_count"] for row in report["bins"]] == [0, 1, 0, 0, 1]


def _formal_order(symbol: str, buy_time: str) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "entry_date": "2026-07-16",
        "lane": "first_board",
        "buy_time": buy_time,
    }


def _scored_row(
    symbol: str,
    signal_time: str,
    score: float,
    target: bool,
    *,
    signal_date: str = "2026-07-15",
) -> dict[str, object]:
    return {
        **_row(
            symbol,
            signal_time,
            signal_date=signal_date,
            target=target,
        ),
        ACTION_SCORE_FIELD: score,
    }


def _row(
    symbol: str,
    signal_time: str,
    *,
    signal_date: str = "2026-07-16",
    gain: float = 6.0,
    net_return: float = 1.0,
    target: bool = False,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "signal_at": f"{signal_date}T{signal_time}",
        "entry_price": 10.5,
        "limit_price": 11.0,
        "fillable": True,
        "before_first_limit_touch": True,
        "shared_strategy_passed": True,
        "support_score": 70.0,
        "entry_quality_score": 72.0,
        "rank_score": 74.0,
        "profitability_gate_sample_count": 8,
        "profitability_gate_combined_rate": 45.0,
        "net_return_pct": net_return,
        ACTION_TARGET_FIELD: target,
        "features": {
            "gain_pct": gain,
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
