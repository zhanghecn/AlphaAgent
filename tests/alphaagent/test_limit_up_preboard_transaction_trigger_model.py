from __future__ import annotations

from copy import deepcopy
from datetime import date

import numpy as np

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    COMPETING_FEATURE_NAMES,
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_TARGET_FIELD,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)
from alphaagent.server.services.limit_up.preboard_transaction_trigger_model import (
    TRANSACTION_ACTION_SCORE_FIELD,
    TRANSACTION_TRIGGER_FEATURE_NAMES,
    TransactionTriggerModelFit,
    calibrate_transaction_threshold,
    fit_transaction_trigger_model,
    score_frozen_transaction_probability,
    score_transaction_trigger_rows,
    transaction_training_batch,
    transaction_trigger_feature_vector,
)


def test_transaction_trigger_feature_order_is_frozen_and_missing_fails_closed() -> None:
    row = _enriched_rows(_row("600001.SSE", "10:00:00"))[0]

    vector = transaction_trigger_feature_vector(row)
    missing = deepcopy(row)
    del missing["transaction_features"][TRANSACTION_FEATURE_NAMES[-1]]
    nonfinite = deepcopy(row)
    nonfinite["transaction_features"][TRANSACTION_FEATURE_NAMES[0]] = float("nan")

    assert TRANSACTION_TRIGGER_FEATURE_NAMES == (
        *COMPETING_FEATURE_NAMES,
        *TRANSACTION_FEATURE_NAMES,
    )
    assert len(vector or []) == 29
    assert transaction_trigger_feature_vector(missing) is None
    assert transaction_trigger_feature_vector(nonfinite) is None


def test_transaction_training_weights_total_one_per_stock_day() -> None:
    rows = _enriched_rows(
        _row("600001.SSE", "10:00:00", target=False),
        _row("600001.SSE", "10:01:00", target=False),
        _row("600002.SSE", "10:00:00", target=True),
    )

    _, _, weights, pairs = transaction_training_batch(
        rows,
        allowed_dates={date(2026, 7, 16)},
    )

    totals: dict[tuple[str, str], float] = {}
    for pair, weight in zip(pairs, weights, strict=True):
        totals[pair] = totals.get(pair, 0.0) + float(weight)
    assert totals == {
        ("600001.SSE", "2026-07-16"): 1.0,
        ("600002.SSE", "2026-07-16"): 1.0,
    }


def test_transaction_fit_is_natural_prevalence_and_fit_isolated() -> None:
    rows = _enriched_rows(
        *[
            _row(
                f"60000{index}.SSE",
                "10:00:00",
                signal_date="2026-07-14",
                gain=4.0 + index,
                target=index % 2 == 0,
            )
            for index in range(1, 5)
        ],
        _row(
            "600010.SSE",
            "10:00:00",
            signal_date="2026-07-15",
            gain=9.0,
            target=True,
        ),
    )

    model = fit_transaction_trigger_model(
        rows,
        fit_dates={date(2026, 7, 14)},
    )
    changed = deepcopy(rows)
    changed[-1][ACTION_TARGET_FIELD] = False
    changed[-1]["net_return_pct"] = -99.0
    changed_model = fit_transaction_trigger_model(
        changed,
        fit_dates={date(2026, 7, 14)},
    )

    assert model.status == "ready"
    assert model.pipeline.named_steps["logistic"].class_weight is None
    assert model.feature_version == TRANSACTION_FEATURE_VERSION
    assert model.transaction_feature_names == TRANSACTION_FEATURE_NAMES
    assert model.fingerprint == changed_model.fingerprint
    assert model.fingerprint is not None and model.fingerprint.startswith("sha256:")
    reconstructed = score_frozen_transaction_probability(rows[0], model)
    assert reconstructed is not None
    assert model.probability(rows[0]) is not None
    assert abs(reconstructed - model.probability(rows[0])) < 1e-8


def test_transaction_scoring_calls_pipeline_once_for_all_finite_rows() -> None:
    rows = _enriched_rows(
        _row("600001.SSE", "10:00:00"),
        _row("600002.SSE", "10:00:00", gain=8.0),
    )

    class CountingPipeline:
        calls = 0

        def predict_proba(self, matrix):
            self.calls += 1
            assert matrix.shape == (2, 29)
            return np.asarray([[0.8, 0.2], [0.3, 0.7]])

    pipeline = CountingPipeline()
    model = TransactionTriggerModelFit(
        status="ready",
        pipeline=pipeline,
        target_field=ACTION_TARGET_FIELD,
        feature_version=TRANSACTION_FEATURE_VERSION,
        transaction_feature_names=TRANSACTION_FEATURE_NAMES,
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

    scored = score_transaction_trigger_rows(rows, model)

    assert pipeline.calls == 1
    assert [row[TRANSACTION_ACTION_SCORE_FIELD] for row in scored] == [0.2, 0.7]


def test_transaction_threshold_reads_only_calibration_dates() -> None:
    rows = _enriched_rows(
        _row("600001.SSE", "10:00:00", signal_date="2026-07-15", target=True),
        _row("600001.SSE", "10:01:00", signal_date="2026-07-15", target=True),
        _row("600002.SSE", "10:00:00", signal_date="2026-07-15", target=False),
        _row("600002.SSE", "10:01:00", signal_date="2026-07-15", target=False),
        _row("600003.SSE", "10:00:00", signal_date="2026-07-16", target=False),
        _row("600003.SSE", "10:01:00", signal_date="2026-07-16", target=False),
    )
    scores = (0.8, 0.8, 0.4, 0.4, 0.99, 0.99)
    scored = [
        {**row, TRANSACTION_ACTION_SCORE_FIELD: score}
        for row, score in zip(rows, scores, strict=True)
    ]

    baseline = calibrate_transaction_threshold(
        scored,
        calibration_dates={date(2026, 7, 15)},
        thresholds=(0.35, 0.75),
        minimum_selection_count=1,
    )
    changed = deepcopy(scored)
    changed[-1][TRANSACTION_ACTION_SCORE_FIELD] = 0.01
    changed[-1][ACTION_TARGET_FIELD] = True
    repeated = calibrate_transaction_threshold(
        changed,
        calibration_dates={date(2026, 7, 15)},
        thresholds=(0.35, 0.75),
        minimum_selection_count=1,
    )

    assert baseline.status == "ready"
    assert baseline.threshold == 0.75
    assert baseline == repeated


def _enriched_rows(*rows: dict[str, object]) -> list[dict[str, object]]:
    return enrich_same_minute_competition(list(rows))


def _row(
    symbol: str,
    signal_time: str,
    *,
    signal_date: str = "2026-07-16",
    gain: float = 6.0,
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
        "net_return_pct": 1.0,
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
        "transaction_features": {
            name: 0.1 + index * 0.01
            for index, name in enumerate(TRANSACTION_FEATURE_NAMES)
        },
    }
