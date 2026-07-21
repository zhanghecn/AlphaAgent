from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

import numpy as np

from alphaagent.server.services.limit_up.preboard_momentum import (
    FEATURE_NAMES,
    HISTORY_FEATURE_NAMES,
)
from alphaagent.server.services.limit_up.preboard_touch_model import (
    MODEL_VARIANTS,
    TouchModelFit,
    attach_later_touch_targets,
    calibrate_touch_threshold,
    first_touch_signal,
    fit_touch_model,
    touch_training_batch,
)


def test_later_touch_target_uses_only_bars_after_the_decision() -> None:
    prefix_rows = [_row(signal_at="2026-07-01T10:00:00")]
    bars = _bars(
        highs=[10.50, 10.65, 10.80, 11.00, 10.90],
        opens=[10.40, 10.50, 10.65, 10.80, 11.00],
    )

    labeled = attach_later_touch_targets(prefix_rows, bars)

    assert labeled[0]["later_touch"] is True
    assert labeled[0]["bars_to_touch"] == 3
    assert labeled[0]["trading_minutes_to_touch"] == 15
    assert labeled[0]["first_touch_at"] == "2026-07-01T10:15:00"


def test_touch_label_does_not_read_seal_d1_or_next_open() -> None:
    row = _row(signal_at="2026-07-01T10:00:00")
    bars = _bars(
        highs=[10.50, 10.65, 11.00],
        opens=[10.40, 10.50, 10.65],
    )
    baseline = attach_later_touch_targets([row], bars)
    mutated_row = {**row, "sealed_limit": False, "d1_close_price": 1.0}
    mutated_bars = deepcopy(bars)
    mutated_bars[1]["open_price"] = 11.0

    changed = attach_later_touch_targets([mutated_row], mutated_bars)

    assert baseline[0]["later_touch"] == changed[0]["later_touch"]
    assert baseline[0]["bars_to_touch"] == changed[0]["bars_to_touch"]


def test_signal_selection_does_not_read_the_future_next_open() -> None:
    model = _probability_model("intraday_only_logistic")
    fillable = _row(fillable=True, entry_price=10.70)
    unfillable = {**fillable, "fillable": False, "entry_price": 11.0}

    baseline = first_touch_signal([fillable], model, threshold=0.70)
    changed = first_touch_signal([unfillable], model, threshold=0.70)

    assert baseline is not None
    assert changed is not None
    assert baseline["signal_time"] == changed["signal_time"]
    assert baseline["model_probability"] == changed["model_probability"]
    assert baseline["fillable"] is True
    assert changed["fillable"] is False


def test_signal_selection_ignores_outcomes_and_rejects_noncausal_rows() -> None:
    model = _probability_model("intraday_only_logistic")
    eligible = _row()
    mutated = {
        **eligible,
        "later_touch": False,
        "sealed_limit": False,
        "d1_close_price": 1.0,
    }
    below_three = _row(index=1)
    below_three["features"]["gain_pct"] = 2.99
    already_touched = _row(index=2)
    already_touched["before_first_limit_touch"] = False

    baseline = first_touch_signal([eligible], model, threshold=0.70)
    changed = first_touch_signal(
        [below_three, already_touched, mutated],
        model,
        threshold=0.70,
    )

    assert baseline is not None
    assert changed is not None
    assert baseline["signal_time"] == changed["signal_time"]
    assert baseline["model_probability"] == changed["model_probability"]


def test_feature_variants_apply_the_declared_history_gate() -> None:
    qualified = _row(later_touch=True)
    insufficient = _row(index=1, later_touch=False, samples=4)

    intraday_matrix, intraday_targets = touch_training_batch(
        [qualified, insufficient],
        "intraday_only_logistic",
    )
    gated_matrix, gated_targets = touch_training_batch(
        [qualified, insufficient],
        "history_gate_intraday_logistic",
    )
    full_matrix, full_targets = touch_training_batch(
        [qualified, insufficient],
        "history_gate_full_logistic",
    )

    assert len(MODEL_VARIANTS) == 6
    assert intraday_matrix.shape == (2, len(FEATURE_NAMES))
    assert intraday_targets.tolist() == [1, 0]
    assert gated_matrix.shape == (1, len(FEATURE_NAMES))
    assert gated_targets.tolist() == [1]
    assert full_matrix.shape == (1, len((*FEATURE_NAMES, *HISTORY_FEATURE_NAMES)))
    assert full_targets.tolist() == [1]


def test_fit_ignores_rows_outside_fit_dates() -> None:
    fit_date = date(2026, 7, 1)
    validation_date = date(2026, 7, 2)
    rows = [
        _row(index=index, signal_date=fit_date, later_touch=index % 2 == 0)
        for index in range(20)
    ] + [
        _row(
            index=index + 20,
            signal_date=validation_date,
            later_touch=index % 2 == 0,
        )
        for index in range(10)
    ]
    mutated = deepcopy(rows)
    for row in mutated:
        if row["signal_date"] == validation_date.isoformat():
            row["later_touch"] = not bool(row["later_touch"])

    baseline = fit_touch_model(
        rows,
        variant="intraday_only_logistic",
        fit_dates={fit_date},
    )
    changed = fit_touch_model(
        mutated,
        variant="intraday_only_logistic",
        fit_dates={fit_date},
    )

    assert baseline.status == "ready"
    assert baseline.training_row_count == 20
    assert baseline.importance_by_feature == changed.importance_by_feature
    assert baseline.intercept == changed.intercept


def test_touch_threshold_calibration_ignores_validation_groups() -> None:
    model = _probability_model("intraday_only_logistic")
    calibration_date = date(2026, 7, 1)
    validation_date = date(2026, 7, 2)
    calibration_groups = [
        [_row(signal_date=calibration_date, probability=0.80, later_touch=True)],
        [
            _row(
                index=1,
                signal_date=calibration_date,
                probability=0.60,
                later_touch=False,
            )
        ],
    ]
    validation_group = [
        _row(
            index=2,
            signal_date=validation_date,
            probability=0.95,
            later_touch=False,
        )
    ]

    baseline = calibrate_touch_threshold(
        [*calibration_groups, validation_group],
        model,
        calibration_dates={calibration_date},
        thresholds=(0.5, 0.7, 0.9),
        minimum_signal_count=1,
    )
    validation_group[0]["later_touch"] = True
    changed = calibrate_touch_threshold(
        [*calibration_groups, validation_group],
        model,
        calibration_dates={calibration_date},
        thresholds=(0.5, 0.7, 0.9),
        minimum_signal_count=1,
    )

    assert baseline.status == "ready"
    assert baseline.threshold == 0.7
    assert baseline == changed


class _FeatureProbabilityPipeline:
    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        probabilities = values[:, 1]
        return np.column_stack((1 - probabilities, probabilities))


def _probability_model(variant: str) -> TouchModelFit:
    return TouchModelFit(
        status="ready",
        variant=variant,
        estimator_kind="logistic",
        pipeline=_FeatureProbabilityPipeline(),
        training_row_count=10,
        class_counts={"negative": 5, "positive": 5},
        fit_dates=("2026-07-01",),
        feature_names=FEATURE_NAMES,
        importance_by_feature={},
        intercept=0.0,
    )


def _row(
    *,
    index: int = 0,
    signal_date: date = date(2026, 7, 1),
    signal_at: str | None = None,
    probability: float = 0.80,
    fillable: bool = True,
    entry_price: float = 10.70,
    later_touch: bool = True,
    samples: int = 5,
    combined_rate: float = 40.0,
) -> dict[str, object]:
    features = {
        name: float(index + feature_index + 1)
        for feature_index, name in enumerate((*FEATURE_NAMES, *HISTORY_FEATURE_NAMES))
    }
    features.update(
        gain_pct=4.0 + index / 100,
        prior_limit_count_126=6.0,
        prior_touch_count_126=8.0,
        prior_seal_success_rate_pct_126=75.0,
        stock_d1_sample_count=float(samples),
        stock_d1_win_rate=60.0,
        stock_d1_average_return_pct=1.0,
        stock_gene_combined_win_rate=combined_rate,
    )
    # The test estimator reads the second selected feature as probability.
    features[FEATURE_NAMES[1]] = probability
    timestamp = signal_at or f"{signal_date.isoformat()}T10:{index:02d}:00"
    return {
        "vt_symbol": f"600{index:03d}.SSE",
        "name": f"Alpha {index}",
        "signal_date": signal_date.isoformat(),
        "signal_at": timestamp,
        "signal_time": timestamp[11:],
        "entry_time": "10:01:00",
        "entry_price": entry_price,
        "limit_price": 11.0,
        "fillable": fillable,
        "before_first_limit_touch": True,
        "later_touch": later_touch,
        "sealed_limit": True,
        "d1_close_price": 11.20,
        "features": features,
    }


def _bars(
    *,
    highs: list[float],
    opens: list[float],
) -> list[dict[str, object]]:
    return [
        {
            "bar_time": datetime.fromisoformat(f"2026-07-01T10:{index * 5:02d}:00"),
            "high_price": high,
            "open_price": open_price,
        }
        for index, (high, open_price) in enumerate(zip(highs, opens, strict=True))
    ]
