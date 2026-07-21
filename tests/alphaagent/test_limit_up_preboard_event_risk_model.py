from __future__ import annotations

from datetime import date
from math import log1p

import numpy as np

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_event_risk_model import (
    CANDIDATE_EVENT_FEATURE_NAMES,
    EVENT_MARKET_SCORE_FIELD,
    EVENT_RANK_SCORE_FIELD,
    MARKET_EVENT_FEATURE_NAMES,
    TOUCH_TARGET_FIELD,
    calibrate_event_risk_threshold,
    enrich_event_risk_features,
    event_market_training_batch,
    event_ranking_training_batch,
    fit_event_market_model,
    fit_event_rank_model,
    score_event_risk_rows,
    select_event_risk_signals,
)


def test_event_features_are_point_in_time_and_future_invariant() -> None:
    first = [
        _row("600001.SSE", "2026-05-04", "10:00:00", gain=6.0, rank=70.0),
        _row("600002.SSE", "2026-05-04", "10:00:00", gain=8.2, rank=80.0),
        _row("600001.SSE", "2026-05-04", "10:01:00", gain=6.4, rank=72.0),
        _row("600003.SSE", "2026-05-04", "10:01:00", gain=5.0, rank=65.0),
    ]
    future = [
        _row("600001.SSE", "2026-05-04", "10:02:00", gain=7.0, rank=75.0),
        _row("600002.SSE", "2026-05-04", "10:02:00", gain=8.8, rank=85.0),
        _row("600003.SSE", "2026-05-04", "10:02:00", gain=5.5, rank=68.0),
    ]

    before = enrich_event_risk_features(enrich_same_minute_competition(first))
    after = enrich_event_risk_features(
        enrich_same_minute_competition([*first, *future])
    )

    before_by_key = {_key(row): row for row in before}
    after_by_key = {_key(row): row for row in after}
    for key, row in before_by_key.items():
        assert after_by_key[key]["event_market_features"] == row["event_market_features"]
        assert after_by_key[key]["event_candidate_features"] == row[
            "event_candidate_features"
        ]

    ten_one = after_by_key[("600001.SSE", "10:01:00")]
    market = ten_one["event_market_features"]
    candidate = ten_one["event_candidate_features"]
    assert market["event_active_candidate_count_log1p"] == log1p(2)
    assert market["event_new_candidate_count_1m_log1p"] == log1p(1)
    assert market["event_new_candidate_count_3m_log1p"] == log1p(3)
    assert market["event_near_limit_candidate_count_log1p"] == 0.0
    assert ten_one["event_active_candidate_count"] == 2
    assert candidate["event_candidate_age_minutes_log1p"] == log1p(1)
    assert candidate["event_candidate_visible_count_3m"] == 2.0
    assert set(market) == set(MARKET_EVENT_FEATURE_NAMES)
    assert set(candidate) == set(CANDIDATE_EVENT_FEATURE_NAMES)


def test_market_batch_has_one_row_per_minute_and_one_total_weight_per_date() -> None:
    rows = enrich_event_risk_features(
        enrich_same_minute_competition(
            [
                _row("600001.SSE", "2026-05-04", "10:00:00", target=False),
                _row("600002.SSE", "2026-05-04", "10:00:00", target=True),
                _row("600001.SSE", "2026-05-04", "10:01:00", target=False),
                _row("600003.SSE", "2026-05-05", "10:00:00", target=False),
            ]
        )
    )

    matrix, labels, weights, keys = event_market_training_batch(
        rows,
        allowed_dates={date(2026, 5, 4), date(2026, 5, 5)},
    )

    assert matrix.shape == (3, len(MARKET_EVENT_FEATURE_NAMES))
    assert labels.tolist() == [1, 0, 0]
    assert keys == (
        ("2026-05-04", "10:00:00"),
        ("2026-05-04", "10:01:00"),
        ("2026-05-05", "10:00:00"),
    )
    assert np.isclose(weights[:2].sum(), 1.0)
    assert np.isclose(weights[2:].sum(), 1.0)


def test_rank_batch_keeps_only_mixed_risk_sets_in_stable_order() -> None:
    rows = enrich_event_risk_features(
        enrich_same_minute_competition(
            [
                _row("600002.SSE", "2026-05-04", "10:00:00", target=True),
                _row("600001.SSE", "2026-05-04", "10:00:00", target=False),
                _row("600003.SSE", "2026-05-04", "10:01:00", target=False),
                _row("600004.SSE", "2026-05-04", "10:02:00", target=True),
                _row("600005.SSE", "2026-05-04", "10:02:00", target=True),
                _row("600006.SSE", "2026-05-05", "10:00:00", target=False),
                _row("600007.SSE", "2026-05-05", "10:00:00", target=True),
            ]
        )
    )

    matrix, labels, group_sizes, group_keys, row_keys = event_ranking_training_batch(
        rows,
        allowed_dates={date(2026, 5, 4), date(2026, 5, 5)},
    )

    assert matrix.shape[0] == 4
    assert labels.tolist() == [0, 1, 0, 1]
    assert group_sizes == (2, 2)
    assert group_keys == (
        ("2026-05-04", "10:00:00"),
        ("2026-05-05", "10:00:00"),
    )
    assert row_keys == (
        ("600001.SSE", "2026-05-04", "10:00:00"),
        ("600002.SSE", "2026-05-04", "10:00:00"),
        ("600006.SSE", "2026-05-05", "10:00:00"),
        ("600007.SSE", "2026-05-05", "10:00:00"),
    )


def test_models_and_scores_are_deterministic() -> None:
    raw: list[dict[str, object]] = []
    fit_dates: set[date] = set()
    for day_offset in range(6):
        day = date(2026, 5, 4 + day_offset)
        fit_dates.add(day)
        day_text = day.isoformat()
        raw.extend(
            [
                _row(
                    f"600{day_offset * 2 + 1:03d}.SSE",
                    day_text,
                    "10:00:00",
                    gain=7.0 + day_offset / 10,
                    rank=65.0,
                    target=False,
                ),
                _row(
                    f"600{day_offset * 2 + 2:03d}.SSE",
                    day_text,
                    "10:00:00",
                    gain=8.0 + day_offset / 10,
                    rank=80.0,
                    target=True,
                ),
                _row(
                    f"601{day_offset:03d}.SSE",
                    day_text,
                    "10:01:00",
                    gain=5.0,
                    rank=60.0,
                    target=False,
                ),
            ]
        )
    rows = enrich_event_risk_features(enrich_same_minute_competition(raw))

    market_first = fit_event_market_model(rows, fit_dates=fit_dates)
    market_second = fit_event_market_model(rows, fit_dates=fit_dates)
    rank_first = fit_event_rank_model(rows, fit_dates=fit_dates)
    rank_second = fit_event_rank_model(rows, fit_dates=fit_dates)
    first_scores = score_event_risk_rows(rows, market_first, rank_first)
    second_scores = score_event_risk_rows(rows, market_second, rank_second)

    assert market_first.status == "ready"
    assert rank_first.status == "ready"
    assert market_first.fingerprint == market_second.fingerprint
    assert rank_first.fingerprint == rank_second.fingerprint
    assert [row[EVENT_MARKET_SCORE_FIELD] for row in first_scores] == [
        row[EVENT_MARKET_SCORE_FIELD] for row in second_scores
    ]
    assert [row[EVENT_RANK_SCORE_FIELD] for row in first_scores] == [
        row[EVENT_RANK_SCORE_FIELD] for row in second_scores
    ]


def test_scoring_fails_closed_when_either_model_is_not_ready() -> None:
    fit_date = date(2026, 5, 4)
    rows = enrich_event_risk_features(
        enrich_same_minute_competition(
            [
                _row("600001.SSE", fit_date.isoformat(), "10:00:00", target=False),
                _row("600002.SSE", fit_date.isoformat(), "10:00:00", target=True),
                _row("600003.SSE", fit_date.isoformat(), "10:01:00", target=False),
            ]
        )
    )
    ready_market = fit_event_market_model(rows, fit_dates={fit_date})
    ready_rank = fit_event_rank_model(rows, fit_dates={fit_date})
    missing_market = fit_event_market_model(rows, fit_dates=set())
    missing_rank = fit_event_rank_model(rows, fit_dates=set())

    assert ready_market.status == "ready"
    assert ready_rank.status == "ready"
    assert score_event_risk_rows(rows, missing_market, ready_rank) == []
    assert score_event_risk_rows(rows, ready_market, missing_rank) == []


def test_validation_labels_cannot_change_fit_calibration_or_action_policy() -> None:
    raw: list[dict[str, object]] = []
    fit_dates: set[date] = set()
    for day_offset in range(6):
        day = date(2026, 5, 4 + day_offset)
        fit_dates.add(day)
        day_text = day.isoformat()
        raw.extend(
            [
                _row(
                    f"600{day_offset * 2 + 1:03d}.SSE",
                    day_text,
                    "10:00:00",
                    gain=7.0,
                    rank=65.0,
                    target=False,
                ),
                _row(
                    f"600{day_offset * 2 + 2:03d}.SSE",
                    day_text,
                    "10:00:00",
                    gain=8.0,
                    rank=80.0,
                    target=True,
                ),
                _row(
                    f"601{day_offset:03d}.SSE",
                    day_text,
                    "10:01:00",
                    gain=5.0,
                    rank=60.0,
                    target=False,
                ),
            ]
        )

    calibration_dates = {date(2026, 5, 10), date(2026, 5, 11)}
    validation_date = date(2026, 5, 12)
    for day in [*sorted(calibration_dates), validation_date]:
        day_text = day.isoformat()
        raw.extend(
            [
                _row("602001.SSE", day_text, "10:00:00", target=False),
                _row("602002.SSE", day_text, "10:00:00", target=True),
            ]
        )

    rows = enrich_event_risk_features(enrich_same_minute_competition(raw))
    changed_validation = [
        {
            **row,
            TOUCH_TARGET_FIELD: not bool(row.get(TOUCH_TARGET_FIELD)),
            "formal_baseline_identity": not bool(
                row.get("formal_baseline_identity")
            ),
            "oracle_future_identity": True,
        }
        if row.get("signal_date") == validation_date.isoformat()
        else dict(row)
        for row in rows
    ]

    first_market = fit_event_market_model(rows, fit_dates=fit_dates)
    first_rank = fit_event_rank_model(rows, fit_dates=fit_dates)
    changed_market = fit_event_market_model(changed_validation, fit_dates=fit_dates)
    changed_rank = fit_event_rank_model(changed_validation, fit_dates=fit_dates)
    first_scores = score_event_risk_rows(rows, first_market, first_rank)
    changed_scores = score_event_risk_rows(
        changed_validation,
        changed_market,
        changed_rank,
    )
    first_threshold = calibrate_event_risk_threshold(
        first_scores,
        calibration_dates=calibration_dates,
        minimum_selection_count=1,
        minimum_precision=0.0,
    )
    changed_threshold = calibrate_event_risk_threshold(
        changed_scores,
        calibration_dates=calibration_dates,
        minimum_selection_count=1,
        minimum_precision=0.0,
    )

    assert first_market.fingerprint == changed_market.fingerprint
    assert first_rank.fingerprint == changed_rank.fingerprint
    assert first_threshold == changed_threshold
    assert [
        (row["vt_symbol"], row["signal_date"], row["signal_time"])
        for row in select_event_risk_signals(
            first_scores,
            threshold=first_threshold.threshold or 0.0,
        )
    ] == [
        (row["vt_symbol"], row["signal_date"], row["signal_time"])
        for row in select_event_risk_signals(
            changed_scores,
            threshold=changed_threshold.threshold or 0.0,
        )
    ]


def test_selector_uses_only_top_ranked_candidate_and_daily_capacity() -> None:
    rows = [
        _scored_row("600001.SSE", "2026-05-04", "10:00:00", 0.8, 0.7),
        _scored_row("600002.SSE", "2026-05-04", "10:00:00", 0.8, 0.9),
        _scored_row("600001.SSE", "2026-05-04", "10:01:00", 0.9, 1.0),
        _scored_row("600003.SSE", "2026-05-04", "10:01:00", 0.9, 0.8),
        _scored_row("600004.SSE", "2026-05-04", "10:02:00", 0.9, 0.95),
        _scored_row("600005.SSE", "2026-05-04", "10:03:00", 0.9, 0.99),
    ]

    selected = select_event_risk_signals(rows, threshold=0.75)

    assert [(row["vt_symbol"], row["signal_time"]) for row in selected] == [
        ("600002.SSE", "10:00:00"),
        ("600001.SSE", "10:01:00"),
    ]


def test_selector_breaks_ranker_ties_by_base_rank_then_symbol() -> None:
    rows = [
        _scored_row(
            "600002.SSE",
            "2026-05-04",
            "10:00:00",
            0.8,
            0.9,
            base_rank=70.0,
        ),
        _scored_row(
            "600001.SSE",
            "2026-05-04",
            "10:00:00",
            0.8,
            0.9,
            base_rank=80.0,
        ),
        _scored_row("600004.SSE", "2026-05-05", "10:00:00", 0.8, 0.9),
        _scored_row("600003.SSE", "2026-05-05", "10:00:00", 0.8, 0.9),
    ]

    selected = select_event_risk_signals(rows, threshold=0.75)

    assert [row["vt_symbol"] for row in selected] == [
        "600001.SSE",
        "600003.SSE",
    ]


def test_calibration_requires_ten_selections_and_seventy_percent_precision() -> None:
    rows = [
        _scored_row(
            f"600{index:03d}.SSE",
            f"2026-05-{index + 1:02d}",
            "10:00:00",
            0.40 if index < 9 else 0.32,
            1.0,
            target=index < 7,
        )
        for index in range(10)
    ]
    dates = {date.fromisoformat(str(row["signal_date"])) for row in rows}

    selection = calibrate_event_risk_threshold(
        rows,
        calibration_dates=dates,
        thresholds=(0.30, 0.35),
    )

    assert selection.status == "ready"
    assert selection.threshold == 0.30
    assert selection.selected_metrics["selection_count"] == 10
    assert selection.selected_metrics["touch_precision"] == 0.7


def test_calibration_fails_closed_when_precision_gate_is_missed() -> None:
    rows = [
        _scored_row(
            f"600{index:03d}.SSE",
            f"2026-05-{index + 1:02d}",
            "10:00:00",
            0.40,
            1.0,
            target=index < 6,
        )
        for index in range(10)
    ]
    dates = {date.fromisoformat(str(row["signal_date"])) for row in rows}

    selection = calibrate_event_risk_threshold(
        rows,
        calibration_dates=dates,
        thresholds=(0.30,),
    )

    assert selection.status == "calibration_precision_gate_failed"
    assert selection.threshold is None


def _scored_row(
    symbol: str,
    signal_date: str,
    signal_time: str,
    market_score: float,
    rank_score: float,
    *,
    base_rank: float = 72.0,
    target: bool = False,
) -> dict[str, object]:
    return {
        **_row(
            symbol,
            signal_date,
            signal_time,
            rank=base_rank,
            target=target,
        ),
        EVENT_MARKET_SCORE_FIELD: market_score,
        EVENT_RANK_SCORE_FIELD: rank_score,
    }


def _row(
    symbol: str,
    signal_date: str,
    signal_time: str,
    *,
    gain: float = 7.0,
    rank: float = 72.0,
    target: bool = False,
) -> dict[str, object]:
    tx_imbalance = (rank - 70.0) / 20.0
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
        TOUCH_TARGET_FIELD: target,
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
            "tx_trade_count_acceleration_1m_5m": 1.1,
            "tx_max_print_turnover_share_1m": 0.2,
            "tx_large_print_turnover_share_1m": 0.4,
            "tx_large_print_turnover_share_3m": 0.4,
            "tx_direction_01_imbalance_1m": 0.1,
            "tx_direction_01_imbalance_3m": 0.1,
            "tx_price_move_turnover_imbalance_1m": tx_imbalance,
            "tx_price_move_turnover_imbalance_3m": tx_imbalance,
            "tx_path_efficiency_1m": 0.5,
        },
    }


def _key(row: dict[str, object]) -> tuple[str, str]:
    return str(row["vt_symbol"]), str(row["signal_time"])
