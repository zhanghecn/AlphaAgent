from __future__ import annotations

from copy import deepcopy
from datetime import date

import numpy as np

from alphaagent.server.services.limit_up.preboard_momentum import (
    SEAL_MODEL_FEATURE_NAMES,
)
from alphaagent.server.services.limit_up.preboard_seal_model import (
    SealModelFit,
    calibrate_seal_threshold,
    first_quality_gated_seal_signal,
    fit_quality_gated_seal_model,
    quality_candidate_outcome,
)


def test_quality_model_requires_history_gate_and_accepts_every_gain_above_three() -> (
    None
):
    below_history = _row("2026-01-02", probability=0.99, gain=9.8, samples=4)
    qualified = _row("2026-01-02", probability=0.80, gain=9.8, samples=5)
    model = _probability_model()

    signal = first_quality_gated_seal_signal(
        [below_history, qualified],
        model,
        threshold=0.75,
    )

    assert signal is not None
    assert signal["signal_time"] == qualified["signal_time"]
    assert signal["features"]["gain_pct"] == 9.8
    assert signal["model_probability"] == 0.8


def test_seal_model_never_reads_d1_outcome_fields() -> None:
    fit_date = date(2026, 1, 2)
    rows = [
        _row(fit_date.isoformat(), probability=0.2 + index / 20, sealed=index % 2 == 0)
        for index in range(20)
    ]
    mutated = deepcopy(rows)
    for row in mutated:
        row["d1_close_price"] = 1_000.0
        row["model_target"] = not bool(row["sealed_limit"])

    baseline = fit_quality_gated_seal_model(rows, fit_dates={fit_date})
    changed = fit_quality_gated_seal_model(mutated, fit_dates={fit_date})

    assert baseline.status == "ready"
    assert baseline.coefficient_by_feature == changed.coefficient_by_feature
    assert baseline.intercept == changed.intercept


def test_threshold_calibration_ignores_rows_outside_calibration_dates() -> None:
    model = _probability_model()
    calibration_date = date(2026, 1, 5)
    validation_date = date(2026, 1, 6)
    calibration_groups = [
        [_row(calibration_date.isoformat(), probability=0.80, sealed=True, index=0)],
        [_row(calibration_date.isoformat(), probability=0.60, sealed=False, index=1)],
    ]
    validation_group = [
        _row(validation_date.isoformat(), probability=0.95, sealed=False, index=2)
    ]

    baseline = calibrate_seal_threshold(
        [*calibration_groups, validation_group],
        model,
        calibration_dates={calibration_date},
        thresholds=(0.5, 0.7, 0.9),
        minimum_signal_count=1,
    )
    validation_group[0]["sealed_limit"] = True
    mutated = calibrate_seal_threshold(
        [*calibration_groups, validation_group],
        model,
        calibration_dates={calibration_date},
        thresholds=(0.5, 0.7, 0.9),
        minimum_signal_count=1,
    )

    assert baseline.status == "ready"
    assert baseline.threshold == 0.7
    assert baseline == mutated


def test_quality_candidate_outcome_counts_one_stock_day_not_every_prefix() -> None:
    rows = [
        _row("2026-01-05", probability=0.6, sealed=True, index=index)
        for index in range(4)
    ]

    outcome = quality_candidate_outcome(rows)

    assert outcome == {"eligible": True, "sealed": True}


class _FeatureProbabilityPipeline:
    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        probabilities = values[:, 1]
        return np.column_stack((1 - probabilities, probabilities))


def _probability_model() -> SealModelFit:
    return SealModelFit(
        status="ready",
        pipeline=_FeatureProbabilityPipeline(),
        training_row_count=10,
        class_counts={"negative": 5, "positive": 5},
        fit_dates=("2026-01-02",),
        coefficient_by_feature={},
        intercept=0.0,
    )


def _row(
    signal_date: str,
    *,
    probability: float,
    gain: float = 4.0,
    samples: int = 5,
    combined_rate: float = 40.0,
    sealed: bool = False,
    index: int = 0,
) -> dict[str, object]:
    features = {
        name: float(feature_index + 1)
        for feature_index, name in enumerate(SEAL_MODEL_FEATURE_NAMES)
    }
    features.update(
        gain_pct=gain,
        prior_limit_count_126=6.0,
        prior_touch_count_126=8.0,
        prior_seal_success_rate_pct_126=75.0,
        stock_d1_sample_count=float(samples),
        stock_d1_win_rate=60.0,
        stock_d1_average_return_pct=1.0,
        stock_gene_combined_win_rate=combined_rate,
    )
    # The fake pipeline reads the second feature as its probability.
    features[SEAL_MODEL_FEATURE_NAMES[1]] = probability
    return {
        "vt_symbol": f"600{index:03d}.SSE",
        "signal_date": signal_date,
        "signal_at": f"{signal_date}T10:{index:02d}:00",
        "signal_time": f"10:{index:02d}:00",
        "fillable": True,
        "before_first_limit_touch": True,
        "sealed_limit": sealed,
        "features": features,
    }
