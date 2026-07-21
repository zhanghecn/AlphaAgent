from __future__ import annotations

from copy import deepcopy
from datetime import date

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    COMPETING_FEATURE_NAMES,
    attach_competing_risk_targets,
    calibrate_competing_threshold,
    competing_feature_vector,
    enrich_same_minute_competition,
    fit_competing_risk_model,
    score_frozen_competing_probability,
    score_competing_risk_rows,
    select_confirmed_competing_signals,
)


def test_same_minute_features_are_causal_and_cross_sectional() -> None:
    rows = [
        _row("600001.SSE", "10:00:00", gain=8.0, rank=80.0),
        _row("600002.SSE", "10:00:00", gain=6.0, rank=60.0),
        _row("600003.SSE", "10:01:00", gain=9.0, rank=90.0),
    ]

    enriched = enrich_same_minute_competition(rows)
    first = enriched[0]["competing_features"]
    second = enriched[1]["competing_features"]
    later = enriched[2]["competing_features"]

    assert first["active_candidate_count_log1p"] == second[
        "active_candidate_count_log1p"
    ]
    assert first["gain_strength_pct"] == 1.0
    assert second["gain_strength_pct"] == 0.5
    assert first["rank_strength_pct"] == 1.0
    assert later["gain_strength_pct"] == 1.0

    changed = deepcopy(rows)
    changed[0]["formal_baseline_identity"] = True
    changed[0]["formal_touch_within_3m"] = True
    changed[0]["net_return_pct"] = 9.0
    changed[2]["features"]["gain_pct"] = 1.0
    changed_enriched = enrich_same_minute_competition(changed)

    assert changed_enriched[0]["competing_features"] == first
    assert changed_enriched[1]["competing_features"] == second


def test_targets_separate_formal_identity_from_short_horizon() -> None:
    rows = [
        _row("600001.SSE", "10:00:00"),
        _row("600002.SSE", "10:00:00"),
    ]
    orders = [
        {
            "vt_symbol": "600001.SSE",
            "entry_date": "2026-07-16",
            "lane": "first_board",
            "buy_time": "10:04:00",
        }
    ]

    labeled = attach_competing_risk_targets(rows, orders)

    assert labeled[0]["formal_baseline_identity"] is True
    assert labeled[0]["formal_touch_within_3m"] is False
    assert labeled[1]["formal_baseline_identity"] is False
    assert labeled[1]["formal_touch_within_3m"] is False


def test_competing_vector_rejects_missing_point_in_time_fields() -> None:
    row = enrich_same_minute_competition([_row("600001.SSE", "10:00:00")])[0]

    assert len(competing_feature_vector(row) or []) == len(COMPETING_FEATURE_NAMES)
    row["rank_score"] = None
    assert competing_feature_vector(row) is None


def test_two_heads_ignore_dates_outside_fit_and_score_by_product() -> None:
    rows = enrich_same_minute_competition(
        [
            _row(
                "600001.SSE",
                "10:00:00",
                signal_date="2026-07-14",
                identity=False,
                hazard=False,
                gain=4.0,
            ),
            _row(
                "600002.SSE",
                "10:00:00",
                signal_date="2026-07-14",
                identity=True,
                hazard=True,
                gain=8.0,
            ),
            _row(
                "600003.SSE",
                "10:00:00",
                signal_date="2026-07-15",
                identity=True,
                hazard=True,
                gain=9.0,
            ),
        ]
    )
    identity = fit_competing_risk_model(
        rows,
        fit_dates={date(2026, 7, 14)},
        target_field="formal_baseline_identity",
    )
    hazard = fit_competing_risk_model(
        rows,
        fit_dates={date(2026, 7, 14)},
        target_field="formal_touch_within_3m",
    )
    changed = deepcopy(rows)
    changed[-1]["formal_baseline_identity"] = False
    changed[-1]["formal_touch_within_3m"] = False

    assert identity.status == "ready"
    assert hazard.status == "ready"
    assert identity.fingerprint == fit_competing_risk_model(
        changed,
        fit_dates={date(2026, 7, 14)},
        target_field="formal_baseline_identity",
    ).fingerprint

    class FixedModel:
        status = "ready"

        def __init__(self, field: str) -> None:
            self.field = field

        def probability(self, row):
            return float(row[self.field])

    scored = score_competing_risk_rows(
        [{**rows[0], "identity_probability": 0.8, "timing_probability": 0.5}],
        FixedModel("identity_probability"),
        FixedModel("timing_probability"),
    )
    assert scored[0]["action_score"] == 0.4

    reconstructed = score_frozen_competing_probability(rows[0], identity)
    assert reconstructed is not None
    assert identity.probability(rows[0]) is not None
    assert abs(reconstructed - identity.probability(rows[0])) < 1e-8


def test_confirmed_policy_reconsiders_competition_and_caps_daily_actions() -> None:
    rows = enrich_same_minute_competition(
        [
            _row("600001.SSE", "10:00:00", score=0.80, rank=80.0),
            _row("600002.SSE", "10:00:00", score=0.90, rank=90.0),
            _row("600003.SSE", "10:00:00", score=0.80, rank=70.0),
            _row("600001.SSE", "10:01:00", score=0.85, rank=85.0),
            _row("600002.SSE", "10:01:00", score=0.40, rank=40.0),
            _row("600003.SSE", "10:01:00", score=0.95, rank=95.0),
            _row("600001.SSE", "10:02:00", score=0.90, rank=90.0),
            _row("600003.SSE", "10:02:00", score=0.96, rank=96.0),
            _row("600004.SSE", "10:02:00", score=0.99, rank=99.0),
            _row("600004.SSE", "10:03:00", score=0.99, rank=99.0),
        ]
    )

    selected = select_confirmed_competing_signals(
        rows,
        threshold=0.75,
        score_field="action_score",
        confirmation_minutes=2,
        max_daily_actions=2,
    )

    assert [(row["vt_symbol"], row["signal_time"]) for row in selected] == [
        ("600003.SSE", "10:01:00"),
        ("600001.SSE", "10:01:00"),
    ]


def test_calibration_uses_only_declared_dates_and_confirmed_signals() -> None:
    calibration_rows = enrich_same_minute_competition(
        [
            _row(
                "600001.SSE",
                "10:00:00",
                signal_date="2026-07-15",
                identity=True,
                hazard=True,
                score=0.9,
            ),
            _row(
                "600001.SSE",
                "10:01:00",
                signal_date="2026-07-15",
                identity=True,
                hazard=True,
                score=0.9,
            ),
            _row(
                "600002.SSE",
                "10:00:00",
                signal_date="2026-07-15",
                identity=False,
                hazard=False,
                score=0.6,
            ),
            _row(
                "600002.SSE",
                "10:01:00",
                signal_date="2026-07-15",
                identity=False,
                hazard=False,
                score=0.6,
            ),
            _row(
                "600003.SSE",
                "10:00:00",
                signal_date="2026-07-16",
                identity=False,
                hazard=False,
                score=0.99,
            ),
            _row(
                "600003.SSE",
                "10:01:00",
                signal_date="2026-07-16",
                identity=False,
                hazard=False,
                score=0.99,
            ),
        ]
    )

    selection = calibrate_competing_threshold(
        calibration_rows,
        calibration_dates={date(2026, 7, 15)},
        thresholds=(0.5, 0.8),
        minimum_selection_count=1,
    )

    assert selection.status == "ready"
    assert selection.threshold == 0.8
    assert selection.selected_metrics["selection_count"] == 1
    assert selection.selected_metrics["horizon_precision"] == 1.0


def _row(
    symbol: str,
    signal_time: str,
    *,
    signal_date: str = "2026-07-16",
    gain: float = 6.0,
    rank: float = 72.0,
    identity: bool = False,
    hazard: bool = False,
    score: float = 0.8,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "signal_at": f"{signal_date}T{signal_time}",
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
        "support_score": 65.0,
        "entry_quality_score": 70.0,
        "rank_score": rank,
        "profitability_gate_sample_count": 8,
        "profitability_gate_combined_rate": 45.0,
        "formal_baseline_identity": identity,
        "formal_touch_within_3m": hazard,
        "action_score": score,
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
