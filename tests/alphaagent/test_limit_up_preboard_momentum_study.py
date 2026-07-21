from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up.preboard_momentum import FEATURE_NAMES
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    official_five_minute_close_times,
)
from alphaagent.server.services.limit_up.preboard_momentum_study import (
    LogisticFit,
    _first_logistic_signal,
    build_preboard_momentum_report,
    chronological_date_split,
    fit_design_logistic,
    render_preboard_momentum_markdown,
    seal_model_date_split,
)
from alphaagent.server.services.limit_up.preboard_seal_model import PRIMARY_ALGORITHM


def test_chronological_split_uses_dates_instead_of_row_counts() -> None:
    dates = [date(2026, 1, day) for day in range(1, 7)]

    design, validation = chronological_date_split(
        [dates[0], dates[0], dates[1], dates[2], dates[3], dates[4], dates[5]],
        design_session_count=4,
    )

    assert design == tuple(dates[:4])
    assert validation == tuple(dates[4:])


def test_seal_model_split_reserves_last_ten_design_dates_for_calibration() -> None:
    dates = tuple(date(2026, 1, 1) + pd.Timedelta(days=index) for index in range(40))

    fit_dates, calibration_dates = seal_model_date_split(dates)

    assert fit_dates == dates[:30]
    assert calibration_dates == dates[30:]


def test_validation_labels_cannot_change_design_logistic_coefficients() -> None:
    design_date = date(2026, 1, 2)
    validation_date = date(2026, 1, 5)
    rows = [
        _training_row(design_date, index, target=index % 2 == 0) for index in range(20)
    ] + [
        _training_row(validation_date, index + 20, target=index % 2 == 0)
        for index in range(10)
    ]

    baseline = fit_design_logistic(rows, design_dates={design_date})
    mutated_rows = deepcopy(rows)
    for row in mutated_rows:
        if row["signal_date"] == validation_date.isoformat():
            row["model_target"] = not row["model_target"]
    mutated = fit_design_logistic(mutated_rows, design_dates={design_date})

    assert baseline.status == "ready"
    assert baseline.coefficient_by_feature == mutated.coefficient_by_feature
    assert baseline.intercept == mutated.intercept
    assert baseline.training_row_count == 20


def test_logistic_signal_waits_until_the_stock_is_observably_above_three_percent() -> (
    None
):
    below = _training_row(date(2026, 1, 2), 0, target=False)
    below.update(signal_at="2026-01-02T10:00:00", signal_time="10:00:00")
    below["features"]["gain_pct"] = 2.99
    eligible = _training_row(date(2026, 1, 2), 1, target=False)
    eligible.update(signal_at="2026-01-02T10:05:00", signal_time="10:05:00")
    eligible["features"]["gain_pct"] = 3.01
    model = LogisticFit(
        status="ready",
        pipeline=_AlwaysPositivePipeline(),
        training_row_count=2,
        class_counts={"negative": 1, "positive": 1},
        design_dates=("2026-01-02",),
        coefficient_by_feature={},
        intercept=0.0,
    )

    signal = _first_logistic_signal([below, eligible], model)

    assert signal is not None
    assert signal["signal_time"] == "10:05:00"
    assert signal["features"]["gain_pct"] == 3.01


def test_logistic_training_accepts_every_observable_gain_at_or_above_three() -> None:
    design_date = date(2026, 1, 2)
    eligible_negative = _training_row(design_date, 0, target=False)
    eligible_positive = _training_row(design_date, 1, target=True)
    below = _training_row(design_date, 2, target=False)
    below["features"]["gain_pct"] = 2.99
    above = _training_row(design_date, 3, target=True)
    above["features"]["gain_pct"] = 9.80

    model = fit_design_logistic(
        [eligible_negative, eligible_positive, below, above],
        design_dates={design_date},
    )

    assert model.status == "ready"
    assert model.training_row_count == 3
    assert model.class_counts == {"negative": 1, "positive": 2}


def test_report_emits_one_signal_per_pair_and_reuses_cash_account() -> None:
    manifest = pd.DataFrame([_manifest_row()])
    minute_rows = pd.DataFrame(_complete_acceleration_bars())
    daily_rows = pd.DataFrame(
        [
            _daily_bar("2026-07-01", 10.0, 11.0, 11.0, 9.9),
            _daily_bar("2026-07-02", 11.0, 11.2, 11.3, 10.8),
        ]
    )

    report = build_preboard_momentum_report(
        manifest,
        minute_rows,
        daily_rows,
        trade_dates=[date(2026, 7, 1), date(2026, 7, 2)],
        design_session_count=1,
    )

    acceleration = report["algorithms"]["acceleration"]["full"]
    assert acceleration["all_recommendations"]["signal_count"] == 1
    assert (
        acceleration["two_position_account"]["execution_version"] == "limit-up-cash-v5"
    )
    assert (
        acceleration["two_position_account"]["execution_summary"]["max_positions"] == 2
    )
    assert acceleration["two_position_account"]["execution_summary"]["trade_count"] == 1
    assert report["seal_prediction_model"]["target"] == "d_day_final_seal"
    assert PRIMARY_ALGORITHM in report["algorithms"]
    assert "下一根5分钟开盘" in render_preboard_momentum_markdown(report)


def _training_row(signal_date: date, index: int, *, target: bool) -> dict[str, object]:
    row = {
        "signal_date": signal_date.isoformat(),
        "model_target": target,
        "fillable": True,
        "before_first_limit_touch": True,
        "features": {
            name: float(index + feature_index / 10)
            for feature_index, name in enumerate(FEATURE_NAMES)
        },
    }
    row["features"]["gain_pct"] = 4.0 + index / 100
    return row


class _AlwaysPositivePipeline:
    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        return np.asarray([[0.0, 1.0] for _ in values], dtype=float)


def _manifest_row() -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "name": "Alpha",
        "trade_date": pd.Timestamp("2026-07-01"),
        "open_price": 10.0,
        "close_price": 11.0,
        "high_price": 11.0,
        "low_price": 9.9,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "result_date": date(2026, 7, 2),
        "d1_trade_date": pd.Timestamp("2026-07-02"),
        "d1_close_price": 11.2,
        "touched_limit": True,
        "sealed_limit": True,
        "prior_limit_count_126": 6,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "stock_d1_sample_count": 5,
        "stock_d1_win_rate": 60.0,
        "stock_d1_average_return_pct": 1.0,
        "stock_gene_combined_win_rate": 45.0,
    }


def _complete_acceleration_bars() -> list[dict[str, object]]:
    slots = official_five_minute_close_times()
    closes = [10.0] * len(slots)
    setup = [10.00, 10.03, 10.08, 10.12, 10.18, 10.25, 10.45, 10.48]
    closes[: len(setup)] = setup
    closes[9] = 11.0
    volumes = [100.0] * len(slots)
    volumes[6] = 220.0
    rows = []
    previous = closes[0]
    for slot, close, volume in zip(slots, closes, volumes, strict=True):
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": pd.Timestamp("2026-07-01"),
                "bar_time": datetime.fromisoformat(f"2026-07-01T{slot}:00"),
                "interval": "5m",
                "open_price": previous,
                "high_price": min(max(previous, close) + 0.03, 11.0),
                "low_price": min(previous, close) - 0.03,
                "close_price": close,
                "volume": volume,
                "turnover": volume * close,
                "source": "fixture",
            }
        )
        previous = close
    return rows


def _daily_bar(
    trade_date: str,
    open_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": pd.Timestamp(trade_date),
        "open_price": open_price,
        "close_price": close_price,
        "high_price": high_price,
        "low_price": low_price,
    }
