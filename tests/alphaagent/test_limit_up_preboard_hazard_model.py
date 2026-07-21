from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

import numpy as np

from alphaagent.server.services.limit_up.preboard_hazard_model import (
    HAZARD_FEATURE_NAMES,
    attach_hazard_targets,
    calibrate_hazard_threshold,
    fit_hazard_model,
    hazard_feature_vector,
    hazard_training_batch,
    select_top2_first_crossings,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    official_one_minute_close_times,
)
from alphaagent.server.services.limit_up.preboard_momentum import build_prefix_rows
from alphaagent.server.services.limit_up.preboard_strategy_replay import (
    build_lane_prefix,
)


def test_one_minute_prefix_uses_elapsed_windows_and_next_minute_entry() -> None:
    bars = _one_minute_bars()
    manifest = {
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "trade_date": "2026-07-16",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "d1_close_price": 10.8,
    }

    rows = build_prefix_rows(manifest, bars, bar_minutes=1)
    target = next(row for row in rows if row["signal_time"] == "10:05:00")
    lane = build_lane_prefix(bars, 34, previous_close=10.0, bar_minutes=1)

    assert target["entry_time"] == "10:06:00"
    assert target["features"]["return_1m_pct"] is not None
    assert target["features"]["return_3m_pct"] is not None
    assert target["features"]["return_5m_pct"] is not None
    assert target["features"]["prior_30m_floor_pct"] is not None
    assert target["features"]["volume_ratio_5m"] is not None
    assert target["features"]["turnover_acceleration_1m"] is not None
    assert lane["point_count"] == 35
    assert lane["recent_15m_min_pct"] is not None
    assert lane["recent_30m_min_pct"] is not None

    changed = deepcopy(bars)
    for bar in changed[35:]:
        bar["close_price"] = 1.0
        bar["high_price"] = 20.0
    changed_target = next(
        row
        for row in build_prefix_rows(manifest, changed, bar_minutes=1)
        if row["signal_time"] == "10:05:00"
    )
    assert changed_target["features"] == target["features"]


def test_default_five_minute_prefix_contract_is_unchanged() -> None:
    bars = _five_minute_bars()
    manifest = {
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "trade_date": "2026-07-16",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "d1_close_price": 10.8,
    }

    assert build_prefix_rows(manifest, bars) == build_prefix_rows(
        manifest,
        bars,
        bar_minutes=5,
    )


def test_one_minute_entry_never_crosses_lunch_or_formal_window_end() -> None:
    signal_date = date(2026, 7, 16)
    bars = []
    for index, slot in enumerate(official_one_minute_close_times()):
        value = 10.30 + index * 0.0001
        bars.append(
            {
                "bar_time": datetime.fromisoformat(
                    f"{signal_date.isoformat()}T{slot}:00"
                ),
                "open_price": value,
                "high_price": value + 0.01,
                "low_price": value - 0.01,
                "close_price": value,
                "volume": 1_000.0,
                "turnover": value * 100_000,
            }
        )
    manifest = {
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "trade_date": signal_date.isoformat(),
        "previous_close": 10.0,
        "limit_price": 11.0,
    }

    rows = build_prefix_rows(manifest, bars, bar_minutes=1)
    pairs = {(row["signal_time"], row["entry_time"]) for row in rows}

    assert ("11:28:00", "11:29:00") in pairs
    assert ("14:28:00", "14:29:00") in pairs
    assert all(entry not in {"11:30:00", "13:01:00", "14:30:00"} for _, entry in pairs)
    assert build_lane_prefix(bars, 7, previous_close=10.0) == build_lane_prefix(
        bars,
        7,
        previous_close=10.0,
        bar_minutes=5,
    )


def test_hazard_targets_use_only_same_pair_future_formal_touch() -> None:
    rows = [
        _hazard_row("600001.SSE", "10:00:00"),
        _hazard_row("600002.SSE", "10:00:00"),
    ]
    orders = [
        {
            "vt_symbol": "600001.SSE",
            "entry_date": "2026-07-16",
            "lane": "first_board",
            "buy_time": "10:02:30",
        },
        {
            "vt_symbol": "600002.SSE",
            "entry_date": "2026-07-16",
            "lane": "two_to_three",
            "buy_time": "10:01:00",
        },
    ]

    labeled = attach_hazard_targets(rows, orders)

    assert labeled[0]["formal_touch_within_1m"] is False
    assert labeled[0]["formal_touch_within_3m"] is True
    assert labeled[0]["formal_touch_within_5m"] is True
    assert labeled[0]["formal_touch_lead_minutes"] == 2.5
    assert labeled[1]["formal_touch_within_5m"] is False


def test_hazard_feature_vector_rejects_missing_values() -> None:
    row = _hazard_row("600001.SSE", "10:00:00")

    vector = hazard_feature_vector(row)
    changed = deepcopy(row)
    changed["features"]["return_3m_pct"] = None

    assert vector is not None
    assert len(vector) == len(HAZARD_FEATURE_NAMES)
    assert hazard_feature_vector(changed) is None


def test_pair_balanced_training_weights_sum_to_one_per_stock_day() -> None:
    rows = [
        _hazard_row("600001.SSE", "10:00:00", target=False),
        _hazard_row("600001.SSE", "10:01:00", target=True),
        _hazard_row("600002.SSE", "10:00:00", target=False),
    ]

    matrix, labels, weights, pairs = hazard_training_batch(
        rows,
        allowed_dates={date(2026, 7, 16)},
        target_field="formal_touch_within_3m",
    )

    assert matrix.shape == (3, len(HAZARD_FEATURE_NAMES))
    assert labels.tolist() == [0, 1, 0]
    first_pair_weight = sum(
        weight
        for weight, pair in zip(weights, pairs, strict=True)
        if pair[0] == "600001.SSE"
    )
    assert first_pair_weight == 1.0
    assert sum(weights) == 2.0


def test_fit_ignores_later_dates_and_calibration_selects_top2() -> None:
    fit_rows = [
        _hazard_row("600001.SSE", "10:00:00", signal_date="2026-07-14", target=False, gain=4.0),
        _hazard_row("600002.SSE", "10:00:00", signal_date="2026-07-14", target=True, gain=8.0),
        _hazard_row("600003.SSE", "10:00:00", signal_date="2026-07-15", target=False, gain=5.0),
        _hazard_row("600004.SSE", "10:00:00", signal_date="2026-07-15", target=True, gain=9.0),
    ]
    model = fit_hazard_model(
        fit_rows,
        fit_dates={date(2026, 7, 14)},
        target_field="formal_touch_within_3m",
    )
    changed = deepcopy(fit_rows)
    changed[-1]["formal_touch_within_3m"] = False
    same_model = fit_hazard_model(
        changed,
        fit_dates={date(2026, 7, 14)},
        target_field="formal_touch_within_3m",
    )

    assert model.status == "ready"
    assert model.fingerprint is not None
    assert model.fingerprint == same_model.fingerprint
    assert model.coefficient_by_feature == same_model.coefficient_by_feature

    class ProbabilityModel:
        status = "ready"

        @staticmethod
        def probability(row):
            return float(row["hazard_probability"])

    calibration_rows = [
        _hazard_row("600010.SSE", "10:00:00", signal_date="2026-07-15", target=True, probability=0.95),
        _hazard_row("600011.SSE", "10:00:00", signal_date="2026-07-15", target=True, probability=0.90),
        _hazard_row("600012.SSE", "10:00:00", signal_date="2026-07-15", target=False, probability=0.85),
    ]
    selection = calibrate_hazard_threshold(
        calibration_rows,
        ProbabilityModel(),
        calibration_dates={date(2026, 7, 15)},
        target_field="formal_touch_within_3m",
        thresholds=(0.8, 0.9),
        minimum_selection_count=2,
    )

    assert selection.status == "ready"
    assert selection.threshold == 0.9
    assert selection.selected_metrics["selection_count"] == 2
    assert selection.selected_metrics["precision"] == 1.0


def test_top2_uses_first_crossing_and_same_minute_competition() -> None:
    rows = [
        _hazard_row("600001.SSE", "10:00:00", probability=0.80),
        _hazard_row("600001.SSE", "10:01:00", probability=0.99),
        _hazard_row("600002.SSE", "10:00:00", probability=0.90),
        _hazard_row("600003.SSE", "10:00:00", probability=0.85),
    ]

    selected = select_top2_first_crossings(
        rows,
        threshold=0.8,
        probability_field="hazard_probability",
    )

    assert [(row["vt_symbol"], row["signal_time"]) for row in selected] == [
        ("600002.SSE", "10:00:00"),
        ("600003.SSE", "10:00:00"),
    ]


def _hazard_row(
    symbol: str,
    signal_time: str,
    *,
    signal_date: str = "2026-07-16",
    target: bool = False,
    gain: float = 6.0,
    probability: float = 0.8,
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
        "rank_score": 72.0,
        "hazard_probability": probability,
        "formal_touch_within_3m": target,
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


def _one_minute_bars() -> list[dict[str, object]]:
    start = datetime(2026, 7, 16, 9, 31)
    rows = []
    for index in range(40):
        value = 10.0 + index * 0.01
        rows.append(
            {
                "bar_time": start + timedelta(minutes=index),
                "open_price": value - 0.005,
                "high_price": value + 0.01,
                "low_price": value - 0.01,
                "close_price": value,
                "volume": 1_000 + index * 20,
                "turnover": (1_000 + index * 20) * value * 100,
            }
        )
    return rows


def _five_minute_bars() -> list[dict[str, object]]:
    start = datetime(2026, 7, 16, 9, 35)
    return [
        {
            "bar_time": start + timedelta(minutes=index * 5),
            "open_price": 10.0 + index * 0.02,
            "high_price": 10.03 + index * 0.02,
            "low_price": 9.99 + index * 0.02,
            "close_price": 10.01 + index * 0.02,
            "volume": 1_000 + index * 10,
            "turnover": 1_000_000 + index * 10_000,
        }
        for index in range(12)
    ]
