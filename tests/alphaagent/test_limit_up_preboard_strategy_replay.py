from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

from alphaagent.server.services.limit_up import preboard_strategy_replay as replay_module
from alphaagent.server.services.limit_up.preboard_strategy_replay import (
    IGNITION_FEATURE_NAMES,
    build_lane_prefix,
    build_strategy_prefix_rows,
    calibrate_ignition_threshold,
    evaluate_static_shared_strategy_upper_bound,
    first_current_support_signal,
    first_ignition_signal,
    fit_ignition_model,
)
from alphaagent.server.services.limit_up.preboard_strategy_study import (
    _baseline_match_phase,
    _build_variant_orders,
    _early_signal_quality,
    _variant_report,
    compare_baseline_summaries,
)


def test_shared_strategy_filter_keeps_touch_and_non_touch_candidates() -> None:
    bars = _bars()
    touched = build_strategy_prefix_rows(
        _manifest(touched=True, sealed=True, d1_close=11.2),
        _feature_row(),
        bars,
        financial_index={},
    )
    non_touch = build_strategy_prefix_rows(
        _manifest(touched=False, sealed=False, d1_close=10.5),
        _feature_row(),
        bars,
        financial_index={},
    )

    touched_signal = first_current_support_signal(touched)
    non_touch_signal = first_current_support_signal(non_touch)

    assert touched_signal is not None
    assert non_touch_signal is not None
    assert touched_signal["signal_time"] == non_touch_signal["signal_time"]
    assert touched_signal["shared_lane_decision"] == "eligible"
    assert non_touch_signal["shared_lane_decision"] == "eligible"
    assert touched_signal["profitability_gate_passed"] is True
    assert non_touch_signal["profitability_gate_passed"] is True
    assert touched_signal["target_positive"] is True
    assert non_touch_signal["target_positive"] is False


def test_static_upper_bound_keeps_every_actual_shared_pass() -> None:
    """The cheap prefilter may over-include, but must never drop an actual pass."""

    feature_variants = [
        _feature_row(),
        {
            **_feature_row(),
            "prior_touch_count_126": 3,
            "financial_snapshot": None,
            "prior_market_phase": "retreat",
        },
    ]
    manifest_variants = [
        _manifest(touched=True, sealed=True, d1_close=11.2),
        _manifest(touched=False, sealed=False, d1_close=10.5),
    ]
    actual_pass_count = 0
    for manifest in manifest_variants:
        for feature in feature_variants:
            rows = build_strategy_prefix_rows(
                manifest,
                feature,
                _bars(),
                financial_index={},
            )
            if not any(row["shared_strategy_passed"] is True for row in rows):
                continue
            actual_pass_count += 1
            upper_bound = evaluate_static_shared_strategy_upper_bound(
                manifest,
                feature,
                financial_index={},
            )
            assert upper_bound["static_upper_bound_passed"] is True
            assert upper_bound["support_score"] >= 55.0

    assert actual_pass_count > 0


def test_static_upper_bound_rejects_permanent_static_blocker() -> None:
    feature = {
        **_feature_row(),
        "prior_limit_count_126": 0,
    }

    result = evaluate_static_shared_strategy_upper_bound(
        _manifest(touched=False, sealed=False, d1_close=10.5),
        feature,
        financial_index={},
    )

    assert result["static_upper_bound_passed"] is False
    assert "limit_up_gene_missing" in result["shared_lane_blockers"]


def test_future_mutations_cannot_change_shared_filter_or_first_signal() -> None:
    manifest = _manifest(touched=True, sealed=True, d1_close=11.2)
    bars = _bars()
    baseline_rows = build_strategy_prefix_rows(
        manifest,
        _feature_row(),
        bars,
        financial_index={},
    )
    baseline = first_current_support_signal(baseline_rows)
    assert baseline is not None

    changed_manifest = {
        **manifest,
        "high_price": 50.0,
        "close_price": 1.0,
        "touched_limit": False,
        "sealed_limit": False,
        "d1_close_price": 1.0,
    }
    changed_bars = deepcopy(bars)
    signal_index = next(
        index
        for index, bar in enumerate(changed_bars)
        if bar["bar_time"].strftime("%H:%M:%S") == baseline["signal_time"]
    )
    for bar in changed_bars[signal_index + 2 :]:
        bar.update(
            {
                "open_price": 20.0,
                "high_price": 20.0,
                "low_price": 20.0,
                "close_price": 20.0,
                "volume": 99_000_000.0,
                "turnover": 990_000_000.0,
            }
        )
    changed_rows = build_strategy_prefix_rows(
        changed_manifest,
        _feature_row(),
        changed_bars,
        financial_index={},
    )
    changed = first_current_support_signal(changed_rows)

    assert changed is not None
    assert changed["signal_at"] == baseline["signal_at"]
    assert changed["entry_at"] == baseline["entry_at"]
    assert changed["shared_lane_decision"] == baseline["shared_lane_decision"]
    assert changed["profitability_gate_reason"] == baseline["profitability_gate_reason"]
    assert changed["target_positive"] is False


def test_next_bar_open_changes_fill_only_not_the_frozen_signal() -> None:
    manifest = _manifest(touched=True, sealed=True, d1_close=11.2)
    bars = _bars()
    baseline_rows = build_strategy_prefix_rows(
        manifest,
        _feature_row(),
        bars,
        financial_index={},
    )
    baseline = first_current_support_signal(baseline_rows)
    assert baseline is not None
    assert baseline["fillable"] is True

    changed_bars = deepcopy(bars)
    signal_index = next(
        index
        for index, bar in enumerate(changed_bars)
        if bar["bar_time"].strftime("%H:%M:%S") == baseline["signal_time"]
    )
    changed_bars[signal_index + 1]["open_price"] = 11.0
    changed_rows = build_strategy_prefix_rows(
        manifest,
        _feature_row(),
        changed_bars,
        financial_index={},
    )
    changed = first_current_support_signal(changed_rows)

    assert changed is not None
    assert changed["signal_at"] == baseline["signal_at"]
    assert changed["fillable"] is False
    assert changed["net_return_pct"] is None
    assert changed["target_positive"] is False


def test_lane_prefix_reads_only_completed_bars() -> None:
    bars = _bars()
    baseline = build_lane_prefix(bars, 6, previous_close=10.0)
    changed = deepcopy(bars)
    changed[7]["close_price"] = 99.0
    changed[7]["high_price"] = 99.0
    changed[7]["volume"] = 99_000_000.0

    assert build_lane_prefix(changed, 6, previous_close=10.0) == baseline


def test_strategy_prefix_builds_lane_path_once(monkeypatch) -> None:
    calls = 0
    original = replay_module._build_lane_prefixes

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(replay_module, "_build_lane_prefixes", counted)

    rows = build_strategy_prefix_rows(
        _manifest(touched=False, sealed=False, d1_close=10.5),
        _feature_row(),
        _bars(),
        financial_index={},
    )

    assert rows
    assert calls == 1


def test_strategy_prefix_reuses_static_profitability_gate(monkeypatch) -> None:
    calls = 0
    original = replay_module.scheduled_execution.first_board_profitability_gate

    def counted(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(
        replay_module.scheduled_execution,
        "first_board_profitability_gate",
        counted,
    )

    rows = build_strategy_prefix_rows(
        _manifest(touched=False, sealed=False, d1_close=10.5),
        _feature_row(),
        _bars(),
        financial_index={},
    )

    assert len(rows) > 1
    assert calls == 1


def test_manifest_membership_cannot_trigger_before_observed_three_percent() -> None:
    bars = _bars()
    closes = [10.01, 10.04, 10.08, 10.12, 10.18, 10.25, 10.31, 10.40, 10.50, 10.60]
    for index, (bar, close) in enumerate(zip(bars, closes, strict=True)):
        open_price = closes[index - 1] if index else 10.0
        bar.update(
            {
                "open_price": open_price,
                "high_price": close + 0.01,
                "low_price": min(open_price, close) - 0.01,
                "close_price": close,
            }
        )
    rows = build_strategy_prefix_rows(
        _manifest(touched=False, sealed=False, d1_close=10.5),
        _feature_row(),
        bars,
        financial_index={},
    )

    signal = first_current_support_signal(rows)

    assert signal is not None
    assert signal["features"]["gain_pct"] >= 3.0
    assert signal["signal_time"] == "10:05:00"


def test_fit_and_threshold_are_isolated_by_chronological_dates() -> None:
    rows = _model_rows()
    fit_dates = {date(2026, 1, 1), date(2026, 1, 2)}
    calibration_dates = {date(2026, 1, 3), date(2026, 1, 4)}
    validation_dates = {date(2026, 1, 5)}

    baseline_fit = fit_ignition_model(rows, fit_dates=fit_dates)
    baseline_threshold = calibrate_ignition_threshold(
        rows,
        baseline_fit,
        calibration_dates=calibration_dates,
        minimum_signal_count=1,
    )

    changed = deepcopy(rows)
    for row in changed:
        if date.fromisoformat(row["signal_date"]) in validation_dates:
            row["target_positive"] = not row["target_positive"]
            row["touched_limit"] = not row["touched_limit"]
            row["sealed_limit"] = not row["sealed_limit"]
    changed_fit = fit_ignition_model(changed, fit_dates=fit_dates)
    changed_threshold = calibrate_ignition_threshold(
        changed,
        changed_fit,
        calibration_dates=calibration_dates,
        minimum_signal_count=1,
    )

    assert baseline_fit.coefficient_by_feature == changed_fit.coefficient_by_feature
    assert baseline_fit.intercept == changed_fit.intercept
    assert baseline_threshold.threshold == changed_threshold.threshold


def test_first_ignition_signal_is_chronological_not_later_maximum() -> None:
    rows = _model_rows(single_pair=True)

    class FixedProbabilityModel:
        status = "ready"

        def __init__(self) -> None:
            self._probabilities = iter((0.6, 0.99))

        def probability(self, _: object) -> float:
            return next(self._probabilities)

    signal = first_ignition_signal(  # type: ignore[arg-type]
        rows,
        FixedProbabilityModel(),
        threshold=0.5,
    )

    assert signal is not None
    assert signal["signal_time"] == "10:00:00"
    assert signal["model_probability"] == 0.6


def test_baseline_parity_fails_closed_on_any_account_difference() -> None:
    expected = {
        "signal_count": 10,
        "filled_count": 8,
        "trade_count": 8,
        "win_count": 6,
        "win_rate": 75.0,
        "total_return_pct": 12.3456,
        "max_drawdown_pct": -3.2109,
    }

    assert compare_baseline_summaries(expected, expected)["passed"] is True
    changed = {**expected, "trade_count": 7}
    result = compare_baseline_summaries(expected, changed)

    assert result["passed"] is False
    assert result["fields"]["trade_count"] == {
        "passed": False,
        "expected": 8.0,
        "actual": 7.0,
    }


def test_signal_gain_quantiles_do_not_replace_profit_factor_inputs() -> None:
    signals = [
        {
            "signal_date": "2026-01-05",
            "net_return_pct": 2.0,
            "touched_limit": True,
            "sealed_limit": True,
            "features": {"gain_pct": 4.0},
        },
        {
            "signal_date": "2026-01-06",
            "net_return_pct": -1.0,
            "touched_limit": False,
            "sealed_limit": False,
            "features": {"gain_pct": 8.0},
        },
    ]

    quality = _early_signal_quality(signals)

    assert quality["profit_factor"] == 2.0
    assert quality["signal_gain_median_pct"] == 6.0


def test_prepare_signals_never_enter_variant_orders() -> None:
    relay = {
        "vt_symbol": "600003.SSE",
        "entry_date": "2026-01-05",
        "lane": "two_to_three",
    }
    formal_first_board = {
        "vt_symbol": "600001.SSE",
        "entry_date": "2026-01-05",
        "lane": "first_board",
    }
    action = {
        "vt_symbol": "600002.SSE",
        "entry_date": "2026-01-05",
        "lane": "first_board",
        "baseline_state": "baseline_action",
    }
    prepare = {
        "vt_symbol": "600004.SSE",
        "entry_date": "2026-01-05",
        "lane": "first_board",
        "baseline_state": "baseline_prepare",
    }

    variants = _build_variant_orders(
        [formal_first_board, relay],
        support_orders=[],
        ignition_orders=[],
        baseline_action_orders=[action],
        baseline_prepare_signals=[prepare],
    )

    assert variants["formal_touch_current"] == [formal_first_board, relay]
    assert variants["baseline_precursor_action"] == [relay, action]
    assert all(
        order.get("baseline_state") != "baseline_prepare"
        for orders in variants.values()
        for order in orders
    )


def test_variant_report_always_returns_account_sections() -> None:
    report = _variant_report(
        [],
        [],
        [],
        validation_dates=set(),
        early_signals=[],
    )

    assert report["full"]["normal"]["signal_count"] == 0
    assert report["validation"]["normal"]["signal_count"] == 0


def test_baseline_match_phase_separates_precision_recall_and_lead() -> None:
    formal_orders = [
        {
            "vt_symbol": "600001.SSE",
            "entry_date": "2026-01-05",
            "buy_time": "10:20:00",
            "lane": "first_board",
        },
        {
            "vt_symbol": "600002.SSE",
            "entry_date": "2026-01-05",
            "buy_time": "10:25:00",
            "lane": "first_board",
        },
    ]
    prefix_rows = [
        {
            **_baseline_signal("600001.SSE", target=True, signal_time="10:05:00"),
            "shared_strategy_passed": True,
            "before_first_limit_touch": True,
        },
        {
            **_baseline_signal("600002.SSE", target=True, signal_time="10:10:00"),
            "shared_strategy_passed": False,
            "before_first_limit_touch": True,
        },
    ]
    signals = [
        _baseline_signal("600001.SSE", target=True, signal_time="10:05:00"),
        _baseline_signal("600003.SSE", target=False, signal_time="10:10:00"),
    ]

    result = _baseline_match_phase(prefix_rows, formal_orders, signals)

    assert result["formal_first_board_pair_count"] == 2
    assert result["reachable_formal_pair_count"] == 1
    assert result["signal_count"] == 2
    assert result["true_positive_count"] == 1
    assert result["false_positive_count"] == 1
    assert result["formal_baseline_precision_pct"] == 50.0
    assert result["all_baseline_recall_pct"] == 50.0
    assert result["reachable_baseline_recall_pct"] == 100.0
    assert result["lead_minutes_median"] == 15.0


def _baseline_signal(
    symbol: str,
    *,
    target: bool,
    signal_time: str,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": "2026-01-05",
        "signal_at": f"2026-01-05T{signal_time}",
        "signal_time": signal_time,
        "entry_time": signal_time,
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
        "fillable": True,
        "formal_touch_baseline_target": target,
        "ignition_features": {
            name: 6.0 + index * 0.01
            for index, name in enumerate(IGNITION_FEATURE_NAMES)
        },
        "features": {
            "gain_pct": 6.0,
            "return_30m_pct": 2.0,
            "prior_30m_range_pct": 1.0,
            "prior_30m_floor_pct": 3.0,
            "breakout_margin_pct": 0.5,
            "opening_gap_pct": 1.0,
            "minute_of_window": 5.0,
        },
    }


def _manifest(
    *,
    touched: bool,
    sealed: bool,
    d1_close: float,
) -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "trade_date": "2026-01-05",
        "result_date": "2026-01-06",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "open_price": 10.15,
        "high_price": 11.0 if touched else 10.8,
        "close_price": 11.0 if sealed else 10.4,
        "touched_limit": touched,
        "sealed_limit": sealed,
        "d1_close_price": d1_close,
        "stock_d1_sample_count": 8,
        "stock_d1_win_rate": 62.5,
        "stock_d1_average_return_pct": 1.8,
        "stock_gene_combined_win_rate": 42.0,
    }


def _feature_row() -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-01-05",
        "industry_id": "BK001",
        "industry_name": "电子",
        "auction_gap_pct": 1.5,
        "prior_streak": 0,
        "prior_break_streak": 0,
        "prior_limit_count_126": 3,
        "prior_touch_count_126": 8,
        "prior_limit_count_5": 0,
        "prior_limit_count_10": 1,
        "prior_seal_success_rate_126": 0.5,
        "trade_days_since_prior_limit": 10,
        "pullback_from_prior_limit_pct": -10.0,
        "prior_position_120": 0.4,
        "prior_change_pct": -1.0,
        "prior_open_gap_pct": 0.5,
        "prior_low_change_pct": -2.0,
        "prior_amplitude_pct": 5.0,
        "prior_return_5d_pct": -3.0,
        "prior_return_20d_pct": 2.0,
        "prior_turnover_rate": 8.0,
        "prior_amount_ratio_5d": 1.5,
        "prior_industry_heat_score": 70.0,
        "prior_industry_heat_rank": 2,
        "prior_industry_count": 50,
        "prior_industry_leader_rank": 1,
        "prior_industry_stock_count": 30,
        "prior_market_phase": "mixed",
        "prior_market_failed_rate": 0.4,
        "financial_risk": {"blocked": False},
        "financial_snapshot": {"net_profit_yoy": 20.0},
    }


def _bars() -> list[dict[str, object]]:
    closes = [10.10, 10.15, 10.20, 10.30, 10.40, 10.50, 10.60, 10.70, 10.80, 11.00]
    start = datetime(2026, 1, 5, 9, 35)
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        open_price = closes[index - 1] if index else 10.05
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 1, 5),
                "bar_time": start + timedelta(minutes=index * 5),
                "interval": "5m",
                "open_price": open_price,
                "high_price": close + 0.01,
                "low_price": min(open_price, close) - 0.01,
                "close_price": close,
                "volume": 1000.0 + index * 100,
                "turnover": (1000.0 + index * 100) * close,
            }
        )
    return rows


def _model_rows(*, single_pair: bool = False) -> list[dict[str, object]]:
    dates = [date(2026, 1, 5)] if single_pair else [
        date(2026, 1, 1),
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 4),
        date(2026, 1, 5),
        date(2026, 1, 5),
    ]
    rows: list[dict[str, object]] = []
    for index, signal_date in enumerate(dates):
        positive = index % 2 == 0
        feature_value = 2.0 if positive else -2.0
        signal_time = "10:00:00" if index % 2 == 0 else "10:05:00"
        rows.append(
            {
                "vt_symbol": f"600{index // 2 + 1:03d}.SSE",
                "signal_date": signal_date.isoformat(),
                "signal_time": signal_time,
                "signal_at": f"{signal_date.isoformat()}T{signal_time}",
                "entry_at": f"{signal_date.isoformat()}T10:06:00",
                "entry_time": "10:06:00",
                "shared_strategy_passed": True,
                "target_positive": positive,
                "touched_limit": positive,
                "sealed_limit": positive,
                "ignition_features": {
                    name: feature_value + position * 0.01
                    for position, name in enumerate(IGNITION_FEATURE_NAMES)
                },
            }
        )
    return rows
