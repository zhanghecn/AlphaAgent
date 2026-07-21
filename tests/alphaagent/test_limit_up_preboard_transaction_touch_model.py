from __future__ import annotations

from datetime import date

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_transaction_touch_model import (
    TOUCH_ACTION_SCORE_FIELD,
    TOUCH_ACTION_TARGET_FIELD,
    calibrate_touch_threshold,
    select_touch_action_signals,
)


def test_single_complete_minute_is_enough_and_competition_is_stable() -> None:
    rows = enrich_same_minute_competition(
        [
            _row("600001.SSE", "2026-07-16", "10:00:00", score=0.80, rank=75.0),
            _row("600002.SSE", "2026-07-16", "10:00:00", score=0.90, rank=70.0),
            _row("600003.SSE", "2026-07-16", "10:00:00", score=0.80, rank=80.0),
            _row("600001.SSE", "2026-07-16", "10:01:00", score=0.95, rank=90.0),
        ]
    )

    selected = select_touch_action_signals(rows, threshold=0.75)

    assert [(row["vt_symbol"], row["signal_time"]) for row in selected] == [
        ("600002.SSE", "10:00:00"),
        ("600003.SSE", "10:00:00"),
    ]


def test_calibration_requires_ten_selections_and_seventy_percent_precision() -> None:
    rows = enrich_same_minute_competition(
        [
            _row(
                f"600{index:03d}.SSE",
                f"2026-05-{index + 1:02d}",
                "10:00:00",
                score=0.40 if index < 9 else 0.32,
                target=index < 7,
            )
            for index in range(10)
        ]
    )
    dates = {date.fromisoformat(str(row["signal_date"])) for row in rows}

    selection = calibrate_touch_threshold(
        rows,
        calibration_dates=dates,
        thresholds=(0.30, 0.35),
    )

    assert selection.status == "ready"
    assert selection.threshold == 0.30
    assert selection.selected_metrics["selection_count"] == 10
    assert selection.selected_metrics["touch_precision"] == 0.7


def test_calibration_rejects_when_precision_gate_cannot_be_met() -> None:
    rows = enrich_same_minute_competition(
        [
            _row(
                f"600{index:03d}.SSE",
                f"2026-05-{index + 1:02d}",
                "10:00:00",
                score=0.40,
                target=index < 6,
            )
            for index in range(10)
        ]
    )
    dates = {date.fromisoformat(str(row["signal_date"])) for row in rows}

    selection = calibrate_touch_threshold(
        rows,
        calibration_dates=dates,
        thresholds=(0.30,),
    )

    assert selection.status == "calibration_precision_gate_failed"
    assert selection.threshold is None


def test_calibration_recall_excludes_unscoreable_touch_pairs() -> None:
    rows = enrich_same_minute_competition(
        [
            _row(
                f"600{index:03d}.SSE",
                f"2026-05-{index + 1:02d}",
                "10:00:00",
                score=0.40,
                target=index < 7,
            )
            for index in range(10)
        ]
    )
    rows.append(
        {
            **_row(
                "600999.SSE",
                "2026-05-11",
                "10:00:00",
                score=0.40,
                target=True,
            ),
            TOUCH_ACTION_SCORE_FIELD: None,
        }
    )
    dates = {date.fromisoformat(str(row["signal_date"])) for row in rows}

    selection = calibrate_touch_threshold(
        rows,
        calibration_dates=dates,
        thresholds=(0.30,),
    )

    assert selection.status == "ready"
    assert selection.selected_metrics["touch_true_positive_count"] == 7
    assert selection.selected_metrics["reachable_recall"] == 1.0


def _row(
    symbol: str,
    signal_date: str,
    signal_time: str,
    *,
    score: float,
    rank: float = 72.0,
    target: bool = False,
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
        TOUCH_ACTION_TARGET_FIELD: target,
        TOUCH_ACTION_SCORE_FIELD: score,
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
