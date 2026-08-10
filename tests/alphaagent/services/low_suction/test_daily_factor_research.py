from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.low_suction import (
    daily_factor_research as daily_factor_research_module,
)
from alphaagent.server.services.low_suction.daily_factor_research import (
    build_daily_features,
    classify_daily_setup,
    d1_close_label_status,
    explain_setup_eligibility,
    label_d1_close_return_pct,
    render_daily_factor_markdown,
    run_daily_factor_study,
    select_score_band,
    secondary_daily_setup,
    split_market_calendar,
    summarize_score_bands,
    score_oversold,
    score_trend,
)


def _bar(
    index: int,
    close: float,
    *,
    open_price: float | None = None,
    low_price: float | None = None,
    volume: float | None = 1_000_000.0,
) -> dict[str, object]:
    return {
        "trade_date": date(2026, 1, 2) + timedelta(days=index),
        "open_price": open_price if open_price is not None else close * 0.998,
        "close_price": close,
        "high_price": close * 1.006,
        "low_price": low_price if low_price is not None else close * 0.99,
        "volume": volume,
    }


def _uptrend_then_ma5_touch() -> list[dict[str, object]]:
    closes = [10.0 + index * 0.15 for index in range(70)]
    bars = [_bar(index, close) for index, close in enumerate(closes)]
    bars[-1]["low_price"] = closes[-1] * 0.985
    return bars


def _oversold_reclaim() -> list[dict[str, object]]:
    closes = [20.0 - index * 0.15 for index in range(40)]
    closes.extend([closes[-1]] * 30)
    closes.append(closes[-1] * 0.996)
    return [
        _bar(
            index,
            close,
            open_price=close * 1.002,
            low_price=close * 0.99,
            volume=1_500_000.0 - index * 5_000.0,
        )
        for index, close in enumerate(closes)
    ]


def test_trend_candidate_requires_ma10_ma20_ma30_order() -> None:
    features = build_daily_features(_uptrend_then_ma5_touch())

    assert features["trend_pullback_eligible"] is True
    assert features["trend_reference_line"] == "ma5"
    assert features["ma10"] > features["ma20"] > features["ma30"]
    assert classify_daily_setup(features) == "trend_pullback"


def test_trend_candidate_fails_when_the_long_ma_order_is_broken() -> None:
    bars = _uptrend_then_ma5_touch()
    for index in range(20):
        bars[-1 - index]["close_price"] = 10.0
        bars[-1 - index]["open_price"] = 10.0
        bars[-1 - index]["high_price"] = 10.1
        bars[-1 - index]["low_price"] = 9.9

    features = build_daily_features(bars)

    assert features["trend_pullback_eligible"] is False
    assert features["trend_reference_line"] is None


def _three_line_bull_with_ma60_still_above() -> list[dict[str, object]]:
    """长期下跌刚转势：MA10>MA20>MA30 三线多头已形成，但 MA60 仍压在 MA30 上方。

    旧口径（要求 MA10>MA20>MA30>MA60）会把它挡在门外；去掉 M60 后应入选趋势低吸。
    """
    closes = [22.0 - index * 0.18 for index in range(45)]
    base = closes[-1]
    closes += [base + index * 0.13 for index in range(30)]
    closes[-1] = closes[-2] * 0.996  # 末根小阴回踩 MA5
    return [_bar(index, close) for index, close in enumerate(closes)]


def test_trend_candidate_admits_three_line_bull_without_ma60() -> None:
    features = build_daily_features(_three_line_bull_with_ma60_still_above())

    # 三线多头已形成，但 MA60 仍在 MA30 上方（旧四线口径会因此被挡）
    assert features["ma10"] > features["ma20"] > features["ma30"]
    assert features["ma60"] > features["ma30"]
    # 去掉 M60 门禁后应入选趋势候选
    assert features["trend_pullback_eligible"] is True
    assert features["trend_reference_line"] == "ma5"
    assert classify_daily_setup(features) == "trend_pullback"


def test_oversold_candidate_uses_prior_bear_structure_and_convergence() -> None:
    features = build_daily_features(_oversold_reclaim())

    assert features["prior_bear_alignment_days"] >= 5
    assert features["oversold_rebound_eligible"] is True
    assert features["convergence"] > 0.0
    assert classify_daily_setup(features) == "oversold_rebound"


def test_oversold_candidate_rejects_a_large_signal_day_chase() -> None:
    bars = _oversold_reclaim()
    bars[-1]["open_price"] = float(bars[-1]["close_price"]) * 0.94
    bars[-1]["high_price"] = float(bars[-1]["close_price"]) * 1.01
    bars[-1]["low_price"] = float(bars[-1]["close_price"]) * 0.93

    assert build_daily_features(bars)["oversold_rebound_eligible"] is False


def test_oversold_eligibility_explanation_includes_every_hard_gate() -> None:
    predicates = explain_setup_eligibility(
        {
            "ma10": 13.959,
            "ma20": 13.4805,
            "ma30": 13.4827,
            "prior_bear_alignment_days": 37,
            "ma_cluster_spread_pct": 1.8166,
            "ma10_20_distance_pct": 3.6168,
            "daily_return_pct": 2.1622,
            "close_to_ma10_pct": -5.2224,
        },
        "oversold_rebound",
    )

    assert predicates["prior_bear_structure"] is True
    assert predicates["ma_cluster_spread_within_3pct"] is True
    assert predicates["ma10_ma20_distance_within_2_5pct"] is False
    assert predicates["close_within_4pct_of_ma10"] is False


def test_trend_eligibility_explanation_separates_low_touch_from_close_recovery() -> None:
    predicates = explain_setup_eligibility(
        {
            "trend_alignment": 1.0,
            "ma10_slope_5d_pct": 1.0,
            "ma20_slope_5d_pct": 1.0,
            "ma30_slope_5d_pct": 1.0,
            "ma60_slope_5d_pct": 1.0,
            "trend_reference_line": "ma5",
            "trend_low_to_reference_pct": -2.05,
            "trend_close_to_reference_pct": -1.70,
            "daily_return_pct": -2.8,
        },
        "trend_pullback",
    )

    assert predicates["support_low_within_minus4_to_1_5pct"] is True
    assert predicates["support_close_recovered_above_minus1_5pct"] is False


def test_volume_is_an_optional_oversold_component_not_a_candidate_gate() -> None:
    bars = _oversold_reclaim()
    without_volume = [{**bar, "volume": None} for bar in bars]

    with_volume_features = build_daily_features(bars)
    without_volume_features = build_daily_features(without_volume)

    assert with_volume_features["oversold_rebound_eligible"] is True
    assert without_volume_features["oversold_rebound_eligible"] is True
    assert with_volume_features["conditional_volume"] is not None
    assert without_volume_features["conditional_volume"] is None


def test_appending_future_bars_does_not_change_features_before_the_cutoff() -> None:
    bars = _uptrend_then_ma5_touch()
    cutoff = bars[-1]["trade_date"]
    future_bars = [_bar(70, 100.0), _bar(71, 80.0)]
    future_bars[0]["close_price"] = 0.0

    assert build_daily_features(bars) == build_daily_features(
        bars + future_bars,
        as_of_date=cutoff,
    )


def test_classification_keeps_one_primary_type_and_retains_secondary_type() -> None:
    features = {
        "trend_pullback_eligible": True,
        "oversold_rebound_eligible": True,
    }

    assert classify_daily_setup(features) == "trend_pullback"
    assert secondary_daily_setup(features) == "oversold_rebound"


def test_d1_close_label_never_uses_a_later_stock_bar_after_suspension() -> None:
    calendar = [date(2026, 2, 12), date(2026, 2, 13), date(2026, 2, 16)]
    closes = {
        date(2026, 2, 12): 2.78,
        date(2026, 3, 9): 3.06,
    }

    assert label_d1_close_return_pct(closes, calendar, date(2026, 2, 12)) is None


def test_d1_close_label_keeps_tick_rounded_main_board_limit_closes() -> None:
    calendar = (date(2026, 2, 12), date(2026, 2, 13))
    exact_limit_close = {
        date(2026, 2, 12): 2.00,
        date(2026, 2, 13): 1.80,
    }
    exact_limit_up_close = {
        date(2026, 2, 12): 2.00,
        date(2026, 2, 13): 2.20,
    }
    rounded_tick_limit_close = {
        date(2026, 2, 12): 2.26,
        date(2026, 2, 13): 2.03,
    }
    rounded_tick_limit_up = {
        date(2026, 2, 12): 9.56,
        date(2026, 2, 13): 10.52,
    }
    raw_price_jump = {
        date(2026, 2, 12): 33.90,
        date(2026, 2, 13): 18.26,
    }

    assert label_d1_close_return_pct(exact_limit_close, calendar, date(2026, 2, 12)) == -10.0
    assert d1_close_label_status(exact_limit_close, calendar, date(2026, 2, 12)) == (
        -10.0,
        "available",
    )
    assert label_d1_close_return_pct(exact_limit_up_close, calendar, date(2026, 2, 12)) == 10.0
    assert d1_close_label_status(exact_limit_up_close, calendar, date(2026, 2, 12)) == (
        10.0,
        "available",
    )
    assert label_d1_close_return_pct(rounded_tick_limit_close, calendar, date(2026, 2, 12)) == -10.177
    assert d1_close_label_status(rounded_tick_limit_close, calendar, date(2026, 2, 12)) == (
        -10.177,
        "available",
    )
    assert label_d1_close_return_pct(rounded_tick_limit_up, calendar, date(2026, 2, 12)) == 10.0418
    assert d1_close_label_status(rounded_tick_limit_up, calendar, date(2026, 2, 12)) == (
        10.0418,
        "available",
    )
    assert label_d1_close_return_pct(raw_price_jump, calendar, date(2026, 2, 12)) is None
    assert d1_close_label_status(raw_price_jump, calendar, date(2026, 2, 12)) == (
        None,
        "label_excluded_main_board_price_limit",
    )


def test_d1_label_diagnostics_distinguish_main_board_price_limit_exclusions() -> None:
    calendar = (date(2026, 2, 12), date(2026, 2, 13))
    label, reason = daily_factor_research_module._eligible_d1_label(
        {
            date(2026, 2, 12): 33.90,
            date(2026, 2, 13): 18.26,
        },
        calendar,
        {trade_date: index for index, trade_date in enumerate(calendar)},
        "603876.SSE",
        date(2026, 2, 12),
        set(),
    )

    assert label is None
    assert reason == "label_excluded_main_board_price_limit_count"


def test_main_board_price_limit_exclusion_does_not_enter_score_panels(
    monkeypatch,
) -> None:
    bars = [{**bar, "vt_symbol": "603876.SSE"} for bar in _oversold_reclaim()]
    signal_index = len(bars) - 2
    raw_jump_close = float(bars[signal_index]["close_price"]) * 0.5
    bars[-1].update(
        open_price=raw_jump_close,
        close_price=raw_jump_close,
        high_price=raw_jump_close * 1.01,
        low_price=raw_jump_close * 0.99,
    )
    calendar = tuple(bar["trade_date"] for bar in bars)
    features = {
        "setup_type": "oversold_rebound",
        "secondary_setup_type": None,
    }

    monkeypatch.setattr(
        daily_factor_research_module,
        "_candidate_positions",
        lambda history: (signal_index,),
    )
    monkeypatch.setattr(
        daily_factor_research_module,
        "build_daily_features",
        lambda history: features,
    )
    monkeypatch.setattr(
        daily_factor_research_module,
        "classify_daily_setup",
        lambda value: "oversold_rebound",
    )
    monkeypatch.setattr(
        daily_factor_research_module,
        "score_factor_variants",
        lambda value: {"base": 80.0, "with_volume": 80.0},
    )

    panels, diagnostics, _ = daily_factor_research_module._build_research_panels(
        bars,
        calendar,
        (),
    )

    assert panels["oversold_rebound"]["base"] == []
    assert panels["oversold_rebound"]["with_volume"] == []
    assert diagnostics["label_excluded_main_board_price_limit_count"] == 1


def test_scores_are_equal_weighted_and_volume_is_an_explicit_ablation() -> None:
    oversold = {
        "bear_duration": 0.4,
        "convergence": 0.6,
        "cross_phase": 0.8,
        "close_quality": 1.0,
        "conditional_volume": 0.2,
    }
    trend = {
        "trend_alignment": 1.0,
        "trend_slope": 0.8,
        "trend_support": 0.6,
        "trend_pullback": 0.4,
        "conditional_volume": 0.2,
    }

    assert score_oversold(oversold, include_volume=False) == 70.0
    assert score_oversold(oversold, include_volume=True) == 60.0
    assert score_trend(trend, include_volume=False) == 70.0
    assert score_trend(trend, include_volume=True) == 60.0


def test_time_split_reserves_embargo_between_development_and_validation() -> None:
    calendar = [date(2026, 1, 1) + timedelta(days=index) for index in range(30)]

    split = split_market_calendar(calendar, embargo_days=3)

    assert split.development_dates
    assert split.embargo_dates
    assert split.validation_dates
    assert split.holdout_dates
    assert split.development_dates[-1] < split.embargo_dates[0] < split.validation_dates[0]
    assert set(split.development_dates).isdisjoint(split.validation_dates)
    assert set(split.validation_dates).isdisjoint(split.holdout_dates)


def test_score_band_is_selected_from_development_not_holdout() -> None:
    development_dates = (date(2026, 1, 2), date(2026, 1, 3))
    validation_dates = (date(2026, 1, 6),)
    holdout_dates = (date(2026, 1, 7),)
    panel = [
        {"trade_date": development_dates[0], "score": 62.0, "d1_close_return_pct": 1.0},
        {"trade_date": development_dates[1], "score": 84.0, "d1_close_return_pct": 2.0},
        {"trade_date": validation_dates[0], "score": 84.0, "d1_close_return_pct": 1.5},
        {"trade_date": holdout_dates[0], "score": 62.0, "d1_close_return_pct": 99.0},
    ]

    result = select_score_band(panel, development_dates, validation_dates)

    assert result["selected_band"] == "80-100"
    assert set(result["selection_dates"]).isdisjoint(holdout_dates)
    assert result["validation"]["d1_mean_return_pct"] == 1.5


def test_score_band_summary_reports_candidate_days_and_positive_return_interval() -> None:
    panel = [
        {"trade_date": date(2026, 1, 2), "score": 62.0, "d1_close_return_pct": 1.0},
        {"trade_date": date(2026, 1, 2), "score": 64.0, "d1_close_return_pct": -1.0},
        {"trade_date": date(2026, 1, 3), "score": 84.0, "d1_close_return_pct": 2.0},
    ]

    summary = {row["band"]: row for row in summarize_score_bands(panel)}

    medium = summary["60-79"]
    assert medium["sample_count"] == 2
    assert medium["candidate_days"] == 1
    assert medium["d1_mean_return_pct"] == 0.0
    assert medium["positive_return_ci95_pct"] is not None


def test_daily_factor_study_is_fail_closed_when_adjusted_input_is_blocked() -> None:
    report = run_daily_factor_study(
        bars=(),
        market_calendar=(),
        security_status=(),
        evidence_level="blocked_by_adjusted_prices",
        blockers=("adjusted_qfq_scope_incomplete",),
        coverage={"adjusted_prices": {"ready": False}},
        input_sha256="blocked-input",
    )

    assert report["conclusion"] == "data_blocker"
    assert report["evidence_level"] == "blocked_by_adjusted_prices"
    assert report["factor_results"]["oversold_rebound"]["base"]["score_bands"]
    assert report["factor_results"]["trend_pullback"]["with_volume"]["score_bands"]


def test_daily_factor_study_always_reports_base_and_volume_variants() -> None:
    oversold_bars = [
        {**bar, "vt_symbol": "001258.SZSE"}
        for bar in _oversold_reclaim()
    ]
    trend_bars = [
        {**bar, "vt_symbol": "600396.SSE"}
        for bar in _uptrend_then_ma5_touch()
    ]
    bars = oversold_bars + trend_bars
    calendar = tuple(sorted({bar["trade_date"] for bar in bars}))
    status = [
        {
            "trade_date": trade_date,
            "vt_symbol": symbol,
            "evidence_level": "reconstructed",
            "board": "main",
            "status": "LISTED",
            "listed_on": date(2020, 1, 1),
            "suspended": False,
            "risk_warning": False,
        }
        for symbol in ("001258.SZSE", "600396.SSE")
        for trade_date in calendar
    ]

    report = run_daily_factor_study(
        bars=bars,
        market_calendar=calendar,
        security_status=status,
        evidence_level="exploratory_reconstructed_security",
        blockers=(),
        coverage={},
        input_sha256="synthetic-input",
    )

    assert report["conclusion"] == "exploratory_only"
    for setup_type in ("oversold_rebound", "trend_pullback"):
        assert set(report["factor_results"][setup_type]) == {"base", "with_volume"}
        assert len(report["factor_results"][setup_type]["base"]["score_bands"]) == 4
        assert len(report["factor_results"][setup_type]["with_volume"]["score_bands"]) == 4


def test_raw_unadjusted_study_stays_exploratory_even_with_available_bars() -> None:
    bars = [
        {**bar, "vt_symbol": "001258.SZSE"}
        for bar in _oversold_reclaim()
    ]
    calendar = tuple(sorted({bar["trade_date"] for bar in bars}))

    report = run_daily_factor_study(
        bars=bars,
        market_calendar=calendar,
        security_status=(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="raw-input",
    )

    assert report["status"] == "exploratory_complete"
    assert report["conclusion"] == "exploratory_only"
    assert report["qualified_rules"] == []
    assert report["factor_results"]["oversold_rebound"]["base"]["score_bands"]
    markdown = render_daily_factor_markdown(report)
    assert "当前数据已完成探索研究" in markdown
    assert "## 时间外准入门槛" in markdown
    assert "| oversold_rebound | base |" in markdown


def test_non_strict_evidence_never_reports_a_formal_qualified_rule(
    monkeypatch,
) -> None:
    calendar = tuple(date(2026, 1, 2) + timedelta(days=index) for index in range(30))
    panels = {
        setup_type: {variant: [] for variant in ("base", "with_volume")}
        for setup_type in ("oversold_rebound", "trend_pullback")
    }
    passed_result = {
        "selection": {
            "selected_band": "80-100",
            "validation": {"d1_mean_return_pct": 1.0},
        },
        "holdout": {"d1_mean_return_pct": 1.0},
        "qualification_gate": {"passed": True, "reasons": []},
    }
    monkeypatch.setattr(
        daily_factor_research_module,
        "_build_research_panels",
        lambda bars, market_calendar, security_status: (panels, {}, []),
    )
    monkeypatch.setattr(
        daily_factor_research_module,
        "_evaluate_factor_variant",
        lambda panel, split: passed_result,
    )

    report = run_daily_factor_study(
        bars=(),
        market_calendar=calendar,
        security_status=(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="raw-input",
    )

    assert report["status"] == "exploratory_complete"
    assert report["conclusion"] == "exploratory_only"
    assert report["qualified_rules"] == []
