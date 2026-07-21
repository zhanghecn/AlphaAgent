from __future__ import annotations

from copy import deepcopy
from datetime import date

from alphaagent.server.services.limit_up.preboard_baseline_model import (
    attach_baseline_account_targets,
    attach_formal_baseline_targets,
    baseline_candidate_vector,
    baseline_reachability,
    calibrate_baseline_thresholds,
    first_baseline_signal,
    fit_baseline_model,
)


def test_targets_only_current_formal_first_board_pairs() -> None:
    rows = [
        {
            key: value
            for key, value in _row(
                symbol,
                "2026-01-05",
                target=False,
            ).items()
            if key != "formal_touch_baseline_target"
        }
        for symbol in ("600001.SSE", "600002.SSE")
    ]
    orders = [
        {
            "vt_symbol": "600001.SSE",
            "entry_date": "2026-01-05",
            "lane": "first_board",
        },
        {
            "vt_symbol": "600002.SSE",
            "entry_date": "2026-01-05",
            "lane": "two_to_three",
        },
    ]

    labeled = attach_formal_baseline_targets(rows, orders)

    assert [row["formal_touch_baseline_target"] for row in labeled] == [True, False]
    assert all("formal_touch_baseline_target" not in row for row in rows)


def test_account_targets_only_filled_first_board_buys() -> None:
    rows = [
        _row("600001.SSE", "2026-01-05", target=False),
        _row("600002.SSE", "2026-01-05", target=False),
    ]
    buy_orders = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-01-05",
            "lane": "first_board",
            "side": "BUY",
            "status": "filled",
        },
        {
            "vt_symbol": "600002.SSE",
            "trade_date": "2026-01-05",
            "lane": "first_board",
            "side": "BUY",
            "status": "skipped",
        },
    ]

    labeled = attach_baseline_account_targets(rows, buy_orders)

    assert [row["formal_touch_account_target"] for row in labeled] == [True, False]


def test_reachability_counts_only_model_eligible_formal_pairs() -> None:
    rows = [
        _row("600001.SSE", "2026-01-05", target=False),
        {
            **_row("600002.SSE", "2026-01-05", target=False),
            "shared_strategy_passed": False,
        },
        _row("600003.SSE", "2026-01-05", target=False),
    ]
    orders = [
        {
            "vt_symbol": "600001.SSE",
            "entry_date": "2026-01-05",
            "lane": "first_board",
        },
        {
            "vt_symbol": "600002.SSE",
            "entry_date": "2026-01-05",
            "lane": "first_board",
        },
    ]

    result = baseline_reachability(rows, orders)

    assert result["formal_first_board_pair_count"] == 2
    assert result["reachable_formal_pair_count"] == 1
    assert result["unreachable_formal_pair_count"] == 1


def test_outcome_mutations_cannot_change_baseline_vector() -> None:
    row = _row("600001.SSE", "2026-01-05", target=True)
    baseline = baseline_candidate_vector(row)
    changed = {
        **deepcopy(row),
        "touched_limit": False,
        "sealed_limit": False,
        "d1_close_price": 1.0,
        "net_return_pct": -90.0,
        "formal_touch_baseline_target": False,
    }

    assert baseline is not None
    assert baseline_candidate_vector(changed) == baseline


def test_validation_targets_cannot_change_fit_or_thresholds() -> None:
    rows = _model_rows()
    fit_dates = {date(2026, 1, 1), date(2026, 1, 2)}
    calibration_dates = {date(2026, 1, 3)}
    validation_date = date(2026, 1, 4)

    baseline_fit = fit_baseline_model(rows, fit_dates=fit_dates)
    baseline_thresholds = calibrate_baseline_thresholds(
        rows,
        baseline_fit,
        calibration_dates=calibration_dates,
        minimum_signal_count=1,
    )
    changed = deepcopy(rows)
    for row in changed:
        if date.fromisoformat(str(row["signal_date"])) == validation_date:
            row["formal_touch_baseline_target"] = not bool(
                row["formal_touch_baseline_target"]
            )
            row["d1_close_price"] = 1.0

    changed_fit = fit_baseline_model(changed, fit_dates=fit_dates)
    changed_thresholds = calibrate_baseline_thresholds(
        changed,
        changed_fit,
        calibration_dates=calibration_dates,
        minimum_signal_count=1,
    )

    assert baseline_fit.status == "ready"
    assert baseline_fit.coefficient_by_feature == changed_fit.coefficient_by_feature
    assert baseline_fit.intercept == changed_fit.intercept
    assert baseline_thresholds.prepare_threshold == changed_thresholds.prepare_threshold
    assert baseline_thresholds.action_threshold == changed_thresholds.action_threshold
    assert baseline_thresholds.action_threshold is not None
    assert baseline_thresholds.prepare_threshold is not None
    assert (
        baseline_thresholds.action_threshold
        >= baseline_thresholds.prepare_threshold
    )


def test_state_signals_freeze_first_threshold_crossing() -> None:
    rows = [
        _row("600001.SSE", "2026-01-05", target=True, signal_time="10:00:00"),
        _row("600001.SSE", "2026-01-05", target=True, signal_time="10:05:00"),
    ]

    class FixedProbabilityModel:
        status = "ready"

        def __init__(self) -> None:
            self._values = iter((0.70, 0.99))

        def probability(self, _: object) -> float:
            return next(self._values)

    signal = first_baseline_signal(  # type: ignore[arg-type]
        rows,
        FixedProbabilityModel(),
        threshold=0.65,
        stage="prepare",
    )

    assert signal is not None
    assert signal["signal_time"] == "10:00:00"
    assert signal["baseline_state"] == "baseline_prepare"
    assert signal["model_probability"] == 0.7


def _model_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for day_index, day in enumerate(range(1, 5), start=1):
        for stock_index, positive in enumerate((False, True), start=1):
            base = 0.1 * day_index + 0.4 * stock_index
            rows.append(
                _row(
                    f"60000{stock_index}.SSE",
                    f"2026-01-{day:02d}",
                    target=positive,
                    base=base,
                )
            )
    return rows


def _row(
    symbol: str,
    signal_date: str,
    *,
    target: bool,
    signal_time: str = "10:00:00",
    base: float = 1.0,
) -> dict[str, object]:
    ignition_features = {
        "gain_pct": 3.0 + base,
        "return_5m_pct": 0.2 + base,
        "return_15m_pct": 0.4 + base,
        "acceleration_pct": 0.1 + base,
        "distance_to_limit_pct": 5.0 - min(base, 4.0),
        "session_drawdown_pct": -0.1,
        "bar_close_location": 0.8,
        "volume_ratio_30m": 1.0 + base,
        "amount_ratio_30m": 1.1 + base,
        "amount_acceleration_ratio": 1.0 + base,
        "support_score": 60.0 + base,
        "entry_quality_score": 65.0 + base,
        "rank_score": 70.0 + base,
    }
    prefix_features = {
        "gain_pct": ignition_features["gain_pct"],
        "return_30m_pct": 0.6 + base,
        "prior_30m_range_pct": 1.2,
        "prior_30m_floor_pct": 2.5,
        "breakout_margin_pct": 0.3 + base,
        "opening_gap_pct": 1.0,
        "minute_of_window": 0.0,
    }
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_at": f"{signal_date}T{signal_time}",
        "signal_time": signal_time,
        "entry_time": "10:01:00",
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
        "fillable": True,
        "ignition_features": ignition_features,
        "features": prefix_features,
        "formal_touch_baseline_target": target,
        "d1_close_price": 11.0,
    }
