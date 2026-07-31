from __future__ import annotations

from datetime import date

import pandas as pd

from alphaagent.server.services.limit_up.recognition_gate_window_grid_research import (
    GRID_VARIANTS,
    attach_recomputed_limit_counts,
    date_block_bootstrap_delta,
    select_calibration_variant,
    variant_mask,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": date(2026, 1, 5),
                "vt_symbol": "600001.SSE",
                "profitability_gate_passed": True,
                "count_evidence_verified": True,
                "prior_limit_count_42": 1,
                "prior_limit_count_63": 2,
                "prior_limit_count_126": 3,
                "return_pct": 8.0,
            },
            {
                "trade_date": date(2026, 1, 6),
                "vt_symbol": "600002.SSE",
                "profitability_gate_passed": True,
                "count_evidence_verified": True,
                "prior_limit_count_42": 2,
                "prior_limit_count_63": 3,
                "prior_limit_count_126": 4,
                "return_pct": -8.0,
            },
            {
                "trade_date": date(2026, 1, 7),
                "vt_symbol": "600003.SSE",
                "profitability_gate_passed": False,
                "count_evidence_verified": True,
                "prior_limit_count_42": 2,
                "prior_limit_count_63": 3,
                "prior_limit_count_126": 4,
                "return_pct": 9.0,
            },
        ]
    )


def _summary(*, compound: float, closed: int = 20) -> dict[str, object]:
    return {
        "closed_count": closed,
        "win_rate_pct": 65.0,
        "average_return_pct": 1.0,
        "daily_equal_weight_compounded_pct": compound,
        "hard_loss_rate_pct": 10.0,
        "maximum_drawdown_pct": -5.0,
    }


def test_grid_registers_every_contiguous_range_and_current_baseline() -> None:
    assert len(GRID_VARIANTS) == 165
    assert {(item.window_sessions, item.lower, item.upper) for item in GRID_VARIANTS} >= {
        (42, 1, 1),
        (42, 1, 10),
        (63, 5, 5),
        (126, 2, 6),
        (126, 10, 10),
    }


def test_variant_membership_is_inclusive_and_outcome_independent() -> None:
    frame = _frame()
    variant = next(
        item
        for item in GRID_VARIANTS
        if (item.window_sessions, item.lower, item.upper) == (42, 1, 2)
    )

    original = variant_mask(frame, variant)
    changed = frame.copy()
    changed["return_pct"] = [-9.0, 9.0, -9.0]

    assert original.tolist() == [True, True, False]
    assert variant_mask(changed, variant).tolist() == original.tolist()


def test_recomputed_counts_are_joined_by_signal_identity_and_fail_closed_on_drift() -> None:
    orders = _frame().iloc[:2].copy()
    orders["prior_limit_count_126"] = [3, 4]
    counts = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 1, 5),
                "vt_symbol": "600001.SSE",
                "prior_limit_count_42": 1,
                "prior_limit_count_63": 2,
                "prior_limit_count_126": 3,
            },
            {
                "trade_date": date(2026, 1, 6),
                "vt_symbol": "600002.SSE",
                "prior_limit_count_42": 2,
                "prior_limit_count_63": 3,
                "prior_limit_count_126": 5,
            },
        ]
    )

    attached, audit = attach_recomputed_limit_counts(orders, counts)

    assert audit["matched_count"] == 1
    assert audit["mismatched_count"] == 1
    assert attached["count_evidence_verified"].tolist() == [True, False]
    baseline = next(
        item
        for item in GRID_VARIANTS
        if (item.window_sessions, item.lower, item.upper) == (126, 2, 6)
    )
    assert variant_mask(attached, baseline).tolist() == [True, False]


def test_selection_uses_calibration_not_locked_holdout() -> None:
    reports = [
        {
            "name": "window_42_count_1_to_3",
            "strict": {
                "training": _summary(compound=2.0),
                "calibration": _summary(compound=5.0),
                "oos": [_summary(compound=3.0)],
                "holdout": _summary(compound=2.0),
            },
        },
        {
            "name": "window_63_count_2_to_6",
            "strict": {
                "training": _summary(compound=2.0),
                "calibration": _summary(compound=4.0),
                "oos": [_summary(compound=3.0)],
                "holdout": _summary(compound=20.0),
            },
        },
    ]

    selected = select_calibration_variant(reports)
    reports[0]["strict"]["holdout"] = _summary(compound=-99.0)

    assert selected == "window_42_count_1_to_3"
    assert select_calibration_variant(reports) == selected


def test_date_block_bootstrap_keeps_complete_dates_together() -> None:
    baseline = pd.DataFrame(
        [
            {"trade_date": date(2026, 1, 5), "return_pct": 1.0},
            {"trade_date": date(2026, 1, 5), "return_pct": 1.0},
            {"trade_date": date(2026, 1, 6), "return_pct": 1.0},
        ]
    )
    variant = pd.DataFrame(
        [
            {"trade_date": date(2026, 1, 5), "return_pct": 2.0},
            {"trade_date": date(2026, 1, 5), "return_pct": 2.0},
            {"trade_date": date(2026, 1, 6), "return_pct": 2.0},
        ]
    )

    report = date_block_bootstrap_delta(baseline, variant, draws=100, seed=7)

    assert report["mean_delta_lower_95"] == 1.0
    assert report["mean_delta_upper_95"] == 1.0
