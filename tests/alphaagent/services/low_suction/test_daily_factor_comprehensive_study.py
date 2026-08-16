from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.low_suction.daily_factor_comprehensive_study import (
    EXIT_PROBES,
    PERSONAL_CASES,
    PersonalResearchCase,
    audit_personal_cases,
    build_comprehensive_research_answers,
    classify_d1_limit_up_touch_proxy,
    classify_oversold_state,
    classify_trend_state,
    evaluate_close_exit_probe,
    render_comprehensive_daily_factor_markdown,
    run_comprehensive_daily_factor_study,
    source_geometry_matches,
    summarize_comprehensive_observations,
)


def _bar(
    offset: int,
    close: float,
    *,
    low: float | None = None,
    volume: float = 1_000_000.0,
) -> dict[str, object]:
    trade_date = date(2026, 1, 2) + timedelta(days=offset)
    return {
        "vt_symbol": "003032.SZSE",
        "trade_date": trade_date,
        "open_price": close * 0.995,
        "close_price": close,
        "high_price": close * 1.01,
        "low_price": low if low is not None else close * 0.99,
        "volume": volume,
    }


def _case_bars() -> list[dict[str, object]]:
    bars = [_bar(index, 10.0 + index * 0.1, volume=900_000.0 + index * 10_000.0) for index in range(70)]
    bars[68]["low_price"] = float(bars[68]["close_price"]) * 0.985
    return bars


def test_personal_case_manifest_covers_every_named_source_observation() -> None:
    assert [
        (
            case.name,
            case.vt_symbol,
            case.trade_date,
            case.expected_setup_type,
            case.source_anchor,
            case.required_process_rule_keys,
        )
        for case in PERSONAL_CASES
    ] == [
        (
            "传智教育 MA10 回踩",
            "003032.SZSE",
            date(2026, 7, 22),
            "oversold_rebound",
            "ma10_low_touch",
            ("staged_ma10_support_before_ma30_convergence_shrink",),
        ),
        (
            "传智教育 三线包裹",
            "003032.SZSE",
            date(2026, 7, 23),
            "oversold_rebound",
            "process_only",
            ("research_oversold_three_ma_wrap_stable_base",),
        ),
        (
            "传智教育 MA10 向 MA30 收敛",
            "003032.SZSE",
            date(2026, 7, 24),
            "oversold_rebound",
            "process_only",
            ("staged_ma10_support_before_ma30_convergence_shrink",),
        ),
        (
            "一鸣食品 MA10 贴合 MA20",
            "605179.SSE",
            date(2026, 7, 15),
            "oversold_rebound",
            "process_only",
            ("ma10_ma20_contact_pre_cross_positive_volume_expand",),
        ),
        (
            "立新能源 MA10 向 MA20 加速收敛",
            "001258.SZSE",
            date(2026, 7, 15),
            "oversold_rebound",
            "process_only",
            ("pre_cross_acceleration_weak_market",),
        ),
        (
            "爱丽家居 MA10 回贴 MA30",
            "603221.SSE",
            date(2026, 7, 20),
            "oversold_rebound",
            "process_only",
            ("ma10_ma30_retest_after_actual_cross_two_leg_volume",),
        ),
        (
            "百花医药 M10/M20 两线包裹",
            "600721.SSE",
            date(2026, 7, 14),
            "oversold_rebound",
            "process_only",
            ("first_leg_two_ma_body_wrap_before_ma30",),
        ),
        (
            "百花医药 三线包裹",
            "600721.SSE",
            date(2026, 7, 31),
            "oversold_rebound",
            "process_only",
            ("research_oversold_three_ma_wrap_stable_base",),
        ),
        (
            "百花医药 向上踩稳",
            "600721.SSE",
            date(2026, 8, 3),
            "oversold_rebound",
            "process_only",
            ("post_wrap_upper_band_reclaim_confirmation",),
        ),
        (
            "国风新材 攻击实体守住",
            "000859.SZSE",
            date(2026, 8, 7),
            "oversold_rebound",
            "process_only",
            ("attack_body_hold_after_ma10_ma20_cross_before_ma30",),
        ),
        (
            "秦安股份 MA10 上穿 MA20",
            "603758.SSE",
            date(2026, 8, 6),
            "oversold_rebound",
            "process_only",
            (),
        ),
        (
            "京投发展 价格先行攻击",
            "600683.SSE",
            date(2026, 8, 7),
            "oversold_rebound",
            "process_only",
            ("price_first_strong_attack",),
        ),
        # 2026-08 趋势族重构：连板后补涨/弱转强 21 个案例低吸点。
        (
            "科森科技 均线蓄势收盘控制",
            "603626.SSE",
            date(2024, 10, 28),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "伟时电子 五连板后转多头",
            "605218.SSE",
            date(2024, 10, 24),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "国芳集团 第二波多头确认",
            "601086.SSE",
            date(2025, 5, 16),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "诺德股份 低开小阳收盘控制",
            "600110.SSE",
            date(2025, 8, 4),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "九牧王 承接住收盘控制",
            "601566.SSE",
            date(2025, 11, 27),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "航天发展 尾盘控盘回踩",
            "000547.SZSE",
            date(2025, 12, 23),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "华电辽能 长横盘后小阳",
            "600396.SSE",
            date(2026, 4, 20),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "福达合金 第二波首小阳",
            "603045.SSE",
            date(2026, 6, 4),
            "trend_pullback",
            "process_only",
            ("limit_up_pullback_rebound",),
        ),
        (
            "双成药业 水下拉起收涨停",
            "002693.SZSE",
            date(2024, 10, 14),
            "trend_pullback",
            "process_only",
            ("limit_up_weak_to_strong_reclaim",),
        ),
        (
            "国芳集团 炸板换手弱转强",
            "601086.SSE",
            date(2025, 4, 16),
            "trend_pullback",
            "process_only",
            ("limit_up_weak_to_strong_reclaim",),
        ),
        (
            "航天发展 跌停换手拉板",
            "000547.SZSE",
            date(2025, 11, 24),
            "trend_pullback",
            "process_only",
            ("limit_up_weak_to_strong_reclaim",),
        ),
        (
            "恒尚节能 超预期拉板",
            "603137.SSE",
            date(2026, 7, 13),
            "trend_pullback",
            "process_only",
            ("limit_up_weak_to_strong_reclaim",),
        ),
        (
            "兴业股份 炸板次日水下拉起",
            "603928.SSE",
            date(2025, 6, 27),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "科森科技 承接住大阴预期",
            "603626.SSE",
            date(2025, 8, 26),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "航天发展 水下拉起多头未破",
            "000547.SZSE",
            date(2025, 11, 27),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "梦天家居 跌停预期承接",
            "603216.SSE",
            date(2025, 11, 26),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "安记食品 跌停预期控盘",
            "603696.SSE",
            date(2025, 12, 12),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "锋龙股份 高换手卡5日线",
            "002931.SZSE",
            date(2026, 2, 2),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "哈药股份 低开拉回踩MA5",
            "600664.SSE",
            date(2026, 7, 20),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "传智教育 弱转强卡点",
            "003032.SZSE",
            date(2026, 8, 7),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
        (
            "爱丽家居 弱转强停牌",
            "603221.SSE",
            date(2026, 8, 7),
            "trend_pullback",
            "process_only",
            ("research_weak_to_strong_turnover_no_limit",),
        ),
    ]


def test_unmodeled_personal_cases_stay_archived_as_research_pending() -> None:
    pending = {
        case.name: case
        for case in PERSONAL_CASES
        if case.narrative_status == "research_pending"
    }

    # 立新能源/京投发展已于 2026-08 沉淀为上穿前价格先行两子型（X/Y 规则），
    # 仅剩秦安股份无独立可量化因子，继续留档观察。
    assert set(pending) == {
        "秦安股份 MA10 上穿 MA20",
    }
    assert all(not case.required_process_rule_keys for case in pending.values())


def test_source_manifest_keeps_only_launch_dates_declared_in_current_text() -> None:
    # 2026-08 趋势族重构：启动日只取主人需求文本明说的次日多头/涨停日
    # （科森 2024-10-29 起多头行情），不再从 K 线反推。
    case = next(
        case for case in PERSONAL_CASES if case.name == "科森科技 均线蓄势收盘控制"
    )

    assert case.expected_launch_date == date(2024, 10, 29)


def test_source_geometry_uses_declared_low_anchor_not_daily_candle_direction() -> None:
    features = {
        "ma5_low_touch": True,
        "ma10_low_touch": False,
        "ma5_low_touch_broad": True,
        "daily_return_pct": 4.68,
    }

    assert source_geometry_matches(features, "ma5_low_touch") is True
    assert source_geometry_matches(features, "ma10_low_touch") is False
    assert source_geometry_matches(features, "ma5_or_ma10_low_touch") is True
    assert source_geometry_matches(features, "process_only") is True


def test_case_audit_is_causal_and_includes_predicates() -> None:
    bars = _case_bars()
    case = PersonalResearchCase(
        name="synthetic case",
        vt_symbol="003032.SZSE",
        trade_date=bars[68]["trade_date"],
        expected_setup_type="trend_pullback",
    )
    calendar = tuple(bar["trade_date"] for bar in bars)

    baseline = audit_personal_cases(bars, calendar, cases=(case,))[0]
    mutated = [dict(bar) for bar in bars]
    mutated[-1]["close_price"] = 1_000.0
    mutated[-1]["high_price"] = 1_010.0
    later = audit_personal_cases(mutated, calendar, cases=(case,))[0]

    assert baseline["observed_through"] == bars[68]["trade_date"]
    assert baseline["vt_symbol"] == "003032.SZSE"
    assert baseline["feature_snapshot"] == later["feature_snapshot"]
    assert "predicate_results" in baseline
    assert baseline["d1_close_return_pct"] is not None
    assert baseline["required_process_predicate_results"] == {}
    assert baseline["failed_required_process_predicates"] == {}
    assert baseline["source_is_oversold_attack_anchor"] is False
    assert baseline["recognized_oversold_attack_stages"] == []


def test_case_audit_marks_declared_oversold_case_as_attack_anchor() -> None:
    bars = _case_bars()
    case = PersonalResearchCase(
        name="synthetic oversold case",
        vt_symbol="003032.SZSE",
        trade_date=bars[68]["trade_date"],
        expected_setup_type="oversold_rebound",
    )

    result = audit_personal_cases(
        bars,
        tuple(bar["trade_date"] for bar in bars),
        cases=(case,),
    )[0]

    assert result["source_is_oversold_attack_anchor"] is True
    assert isinstance(result["recognized_oversold_attack_stages"], list)


def test_case_audit_keeps_a_causal_narrative_timeline_and_separate_launch_check() -> None:
    bars = _case_bars()
    case = PersonalResearchCase(
        name="narrative timeline",
        vt_symbol="003032.SZSE",
        narrative_start_date=bars[64]["trade_date"],
        trade_date=bars[67]["trade_date"],
        expected_launch_date=bars[69]["trade_date"],
        expected_setup_type="trend_pullback",
    )
    calendar = tuple(bar["trade_date"] for bar in bars)

    baseline = audit_personal_cases(bars, calendar, cases=(case,))[0]
    mutated = [dict(bar) for bar in bars]
    mutated[69]["close_price"] = 1_000.0
    mutated[69]["high_price"] = 1_010.0
    later = audit_personal_cases(mutated, calendar, cases=(case,))[0]

    assert baseline["narrative_timeline_status"] == "available"
    assert baseline["narrative_timeline"][0]["trade_date"] == bars[64]["trade_date"]
    assert baseline["narrative_timeline"][-1]["trade_date"] == bars[67]["trade_date"]
    assert baseline["narrative_timeline"] == later["narrative_timeline"]
    assert baseline["narrative_checks"]["timeline_available"] is True
    assert baseline["launch_observation"]["expected_launch_date"] == bars[69]["trade_date"]
    assert baseline["launch_observation"] != later["launch_observation"]


def test_case_launch_observation_rejects_a_missing_prior_market_bar() -> None:
    bars = _case_bars()
    case = PersonalResearchCase(
        name="gapped launch",
        vt_symbol="003032.SZSE",
        narrative_start_date=bars[64]["trade_date"],
        trade_date=bars[65]["trade_date"],
        expected_launch_date=bars[69]["trade_date"],
        expected_setup_type="trend_pullback",
    )
    gapped_history = [bar for index, bar in enumerate(bars) if index not in {66, 67, 68}]
    calendar = tuple(bar["trade_date"] for bar in bars)

    result = audit_personal_cases(gapped_history, calendar, cases=(case,))[0]

    assert result["launch_observation"]["status"] == "missing_launch_previous_market_bar"
    assert result["launch_observation"]["raw_close_return_pct"] is None


def test_case_audit_marks_raw_jump_beyond_main_board_limit_as_excluded() -> None:
    bars = _case_bars()
    case = PersonalResearchCase(
        name="raw-price jump",
        vt_symbol="003032.SZSE",
        trade_date=bars[68]["trade_date"],
        expected_setup_type="trend_pullback",
    )
    bars[69]["close_price"] = 10.0
    calendar = tuple(bar["trade_date"] for bar in bars)

    result = audit_personal_cases(bars, calendar, cases=(case,))[0]

    assert result["d1_close_return_pct"] is None
    assert result["data_status"] == "label_excluded_main_board_price_limit"


def test_oversold_taxonomy_separates_cross_price_and_volume_states() -> None:
    state = classify_oversold_state(
        {
            "ma10": 10.01,
            "ma20": 10.0,
            "ma30": 10.2,
            "close_price": 10.0,
            "daily_return_pct": -0.8,
            "volume_spearman_5d": -0.9,
            "volume_down_streak": 4,
            "volume_up_streak": 0,
        }
    )

    assert state["ma10_ma20_state"] == "near_or_crossed"
    assert state["price_state"] == "weak_or_down"
    assert state["volume_shape"] == "staircase_shrink"


def test_oversold_taxonomy_names_a_small_positive_bar_correctly() -> None:
    state = classify_oversold_state(
        {
            "ma10": 10.0,
            "ma20": 10.0,
            "ma30": 10.0,
            "close_price": 10.0,
            "daily_return_pct": 1.0,
            "volume_spearman_5d": 0.0,
            "volume_down_streak": 0,
            "volume_up_streak": 0,
        }
    )

    assert state["price_state"] == "small_positive"


def test_trend_taxonomy_uses_low_for_support_touch() -> None:
    state = classify_trend_state(
        {
            "ma5_regular": True,
            "trend_reference_line": "ma5",
            "trend_low_to_reference_pct": -0.5,
            "trend_close_to_reference_pct": 0.2,
            "daily_return_pct": -0.2,
            "bull_alignment_days": 12,
            "volume_spearman_5d": 0.0,
            "volume_down_streak": 0,
            "volume_up_streak": 0,
        }
    )

    assert state["support_line"] == "ma5"
    assert state["support_touch"] == "low_touch"
    assert state["ma5_regular"] == "yes"


def test_comprehensive_summary_has_daily_stock_and_condition_evidence() -> None:
    observations = (
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "000001.SZSE",
            "trade_date": date(2026, 1, 2),
            "d1_close_return_pct": -2.0,
            "scores": {"base": 82.0, "with_volume": 85.0},
            "state": {
                "ma10_ma20_state": "near_or_crossed",
                "ma10_ma30_state": "below",
                "ma20_ma30_state": "near_or_crossed",
                "price_state": "weak_or_down",
                "volume_shape": "staircase_shrink",
            },
            "feature_snapshot": {"daily_return_pct": -0.5},
        },
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "000001.SZSE",
            "trade_date": date(2026, 1, 3),
            "d1_close_return_pct": -1.0,
            "scores": {"base": 84.0, "with_volume": 86.0},
            "state": {
                "ma10_ma20_state": "near_or_crossed",
                "ma10_ma30_state": "below",
                "ma20_ma30_state": "near_or_crossed",
                "price_state": "weak_or_down",
                "volume_shape": "staircase_shrink",
            },
            "feature_snapshot": {"daily_return_pct": -0.3},
        },
    )
    calendar = tuple(date(2026, 1, 2) + timedelta(days=index) for index in range(15))

    report = summarize_comprehensive_observations(observations, calendar)
    family = report["families"]["oversold_rebound"]

    assert family["daily_outcomes"]
    assert family["worst_stocks"][0]["vt_symbol"] == "000001.SZSE"
    assert family["condition_outcomes"]
    assert family["score_variants"]["base"]["selection"]["selected_band"] == "80-100"


def test_comprehensive_summary_reports_fixed_interactions_touch_rates_and_failure_attribution() -> None:
    observations = (
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "000001.SZSE",
            "trade_date": date(2026, 1, 2),
            "d1_close_return_pct": -2.0,
            "d1_limit_up_touch": True,
            "d1_fresh_limit_up_touch_proxy": True,
            "scores": {"base": 82.0, "with_volume": 85.0},
            "state": {
                "ma10_ma20_state": "near_or_crossed",
                "ma10_ma30_state": "below",
                "ma20_ma30_state": "near_or_crossed",
                "price_state": "weak_or_down",
                "volume_shape": "staircase_shrink",
            },
            "feature_snapshot": {},
        },
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "000002.SZSE",
            "trade_date": date(2026, 1, 3),
            "d1_close_return_pct": 1.0,
            "d1_limit_up_touch": False,
            "d1_fresh_limit_up_touch_proxy": False,
            "scores": {"base": 82.0, "with_volume": 85.0},
            "state": {
                "ma10_ma20_state": "near_or_crossed",
                "ma10_ma30_state": "below",
                "ma20_ma30_state": "near_or_crossed",
                "price_state": "weak_or_down",
                "volume_shape": "staircase_shrink",
            },
            "feature_snapshot": {},
        },
    )
    calendar = tuple(date(2026, 1, 2) + timedelta(days=index) for index in range(15))

    family = summarize_comprehensive_observations(observations, calendar)["families"]["oversold_rebound"]

    assert family["overall"]["d1_limit_up_touch_rate_pct"] == 50.0
    assert family["overall"]["d1_fresh_limit_up_touch_proxy_rate_pct"] == 50.0
    interaction = next(
        row
        for row in family["interaction_outcomes"]
        if row["dimensions"] == ["ma10_ma20_state", "price_state", "volume_shape"]
    )
    assert interaction["sample_count"] == 2
    assert interaction["negative_rate_pct"] == 50.0
    assert any(
        row["source"] == "interaction" and row["negative_rate_pct"] == 50.0
        for row in family["failure_attribution"]
    )


def test_failure_attribution_quantifies_deterioration_against_family_baseline() -> None:
    observations = (
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "000001.SZSE",
            "trade_date": date(2026, 1, 2),
            "d1_close_return_pct": -2.0,
            "scores": {"base": 82.0, "with_volume": 85.0},
            "state": {"price_state": "weak_or_down"},
            "feature_snapshot": {},
        },
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "000002.SZSE",
            "trade_date": date(2026, 1, 3),
            "d1_close_return_pct": 1.0,
            "scores": {"base": 82.0, "with_volume": 85.0},
            "state": {"price_state": "small_positive"},
            "feature_snapshot": {},
        },
    )
    calendar = tuple(date(2026, 1, 2) + timedelta(days=index) for index in range(15))

    family = summarize_comprehensive_observations(observations, calendar)["families"][
        "oversold_rebound"
    ]
    bad_state = next(
        row
        for row in family["failure_attribution"]
        if row["state"] == {"price_state": "weak_or_down"}
    )

    assert bad_state["sample_share_pct"] == 50.0
    assert bad_state["d1_mean_delta_vs_family_pct"] == -1.5
    assert bad_state["negative_rate_delta_vs_family_pct"] == 50.0


def test_d1_limit_up_touch_proxy_requires_valid_strict_10_percent_ohlc() -> None:
    result = classify_d1_limit_up_touch_proxy(
        signal_bar={"close_price": 10.0, "high_price": 10.1},
        d1_bar={
            "open_price": 10.2,
            "high_price": 11.0,
            "low_price": 10.0,
            "close_price": 10.8,
        },
        prior_signal_bar={"close_price": 9.5},
    )

    assert result["d1_limit_up_touch"] is True
    assert result["d1_fresh_limit_up_touch_proxy"] is True
    assert result["d1_limit_up_close_proxy"] is False
    assert result["d1_fresh_limit_up_close_proxy"] is False
    assert result["d1_limit_up_touch_status"] == "available"

    close_limit = classify_d1_limit_up_touch_proxy(
        signal_bar={"close_price": 10.0, "high_price": 10.1},
        d1_bar={
            "open_price": 10.2,
            "high_price": 11.0,
            "low_price": 10.0,
            "close_price": 11.0,
        },
        prior_signal_bar={"close_price": 9.5},
    )

    assert close_limit["d1_limit_up_close_proxy"] is True
    assert close_limit["d1_fresh_limit_up_close_proxy"] is True
    assert close_limit["d1_limit_up_close_proxy_status"] == "available"

    invalid = classify_d1_limit_up_touch_proxy(
        signal_bar={"close_price": 10.0, "high_price": 10.1},
        d1_bar={
            "open_price": 10.2,
            "high_price": 11.01,
            "low_price": 10.0,
            "close_price": 11.01,
        },
        prior_signal_bar={"close_price": 9.5},
    )

    assert invalid["d1_limit_up_touch"] is None
    assert invalid["d1_limit_up_close_proxy"] is None
    assert invalid["d1_limit_up_touch_status"] == "raw_price_limit_outlier"


def test_case_audit_markdown_shows_scores_bands_and_touch_proxy() -> None:
    report = {
        "research_version": "test",
        "evidence_level": "exploratory_raw_unadjusted",
        "conclusion": "exploratory_only",
        "case_audit": [
            {
                "name": "case",
                "trade_date": date(2026, 1, 2),
                "expected_setup_type": "oversold_rebound",
                "setup_type": "oversold_rebound",
                "d1_close_return_pct": 1.0,
                "data_status": "available",
                "narrative_status": "complete",
                "state": {},
                "predicate_results": {},
                "scores": {"base": 80.0},
                "score_band_membership": {"base": {"score_band": "80-100"}},
                "d1_limit_up_touch": True,
                "d1_fresh_limit_up_touch_proxy": True,
                "d1_limit_up_close_proxy": True,
                "d1_fresh_limit_up_close_proxy": True,
                "narrative_timeline_status": "available",
                "narrative_checks": {"timeline_available": True},
                "narrative_timeline": [
                    {
                        "trade_date": date(2026, 1, 2),
                        "ma10_ma20_state": "near_or_crossed",
                    }
                ],
                "launch_observation": {"expected_launch_date": date(2026, 1, 3)},
            }
        ],
        "families": {},
        "research_answers": [],
    }

    markdown = render_comprehensive_daily_factor_markdown(report)

    assert "分数桶归属" in markdown
    assert "当前数据已完成探索研究" in markdown
    assert "D+1 日线触板/新鲜触板代理" in markdown
    assert "因果日线时间线" in markdown
    assert "收盘涨停/新鲜收盘涨停代理" in markdown


def test_comprehensive_study_marks_available_raw_input_as_exploratory_only() -> None:
    bars = _case_bars()
    report = run_comprehensive_daily_factor_study(
        bars=bars,
        market_calendar=tuple(bar["trade_date"] for bar in bars),
        security_status=(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="raw-input",
    )

    assert report["status"] == "exploratory_complete"
    assert report["conclusion"] == "exploratory_only"
    assert report["qualified_rules"] == []


def test_comprehensive_summary_counts_main_board_price_limit_label_exclusions() -> None:
    observations = (
        {
            "setup_type": "oversold_rebound",
            "vt_symbol": "603876.SSE",
            "trade_date": date(2026, 1, 2),
            "d1_close_return_pct": None,
            "d1_label_status": "label_excluded_main_board_price_limit",
            "scores": {"base": 82.0, "with_volume": 85.0},
            "state": {"price_state": "weak_or_down"},
            "feature_snapshot": {},
            "exit_outcomes": (),
        },
    )
    calendar = tuple(date(2026, 1, 2) + timedelta(days=index) for index in range(15))

    report = summarize_comprehensive_observations(observations, calendar)
    overall = report["families"]["oversold_rebound"]["overall"]

    assert overall["sample_count"] == 0
    assert overall["candidate_count"] == 0
    assert overall["label_unavailable_count"] == 0
    assert overall["label_excluded_main_board_price_limit_count"] == 1


def test_exit_probe_is_after_entry_and_uses_close_only() -> None:
    entry_date = date(2026, 1, 2)
    candidate = {
        "entry_date": entry_date,
        "entry_price": 10.0,
        "setup_type": "oversold_rebound",
    }
    future_bars = (
        {"trade_date": entry_date + timedelta(days=1), "close_price": 10.5, "ma10": 9.8},
        {"trade_date": entry_date + timedelta(days=2), "close_price": 11.0, "ma10": 10.0},
    )

    result = evaluate_close_exit_probe(candidate, future_bars, probe=EXIT_PROBES["oversold_rebound"][1])

    assert result["entry_date"] < result["exit_date"]
    assert result["exit_price_mode"] == "close"
    assert result["holding_sessions"] == 2
    assert result["return_pct"] == 10.0


def test_exit_probe_excludes_raw_price_jump_beyond_main_board_limit() -> None:
    entry_date = date(2026, 1, 2)
    candidate = {
        "entry_date": entry_date,
        "entry_price": 33.90,
        "setup_type": "oversold_rebound",
    }
    future_bars = (
        {"trade_date": entry_date + timedelta(days=1), "close_price": 18.26, "ma10": 18.0},
    )

    result = evaluate_close_exit_probe(
        candidate,
        future_bars,
        probe=EXIT_PROBES["oversold_rebound"][0],
    )

    assert result["status"] == "unavailable"
    assert result["exit_reason"] == "raw_price_limit_outlier"


def test_research_answers_include_raw_findings_without_promoting_a_rule() -> None:
    family = {
        "score_variants": {
            "base": {
                "selection": {
                    "selected_band": "80-100",
                    "holdout": {"d1_mean_return_pct": -0.1},
                }
            },
            "with_volume": {
                "selection": {
                    "selected_band": "60-79",
                    "holdout": {"d1_mean_return_pct": -0.2},
                }
            },
        },
        "condition_outcomes": [
            {"dimension": "ma10_ma20_state", "value": "near_or_crossed", "d1_mean_return_pct": 0.01},
            {"dimension": "price_state", "value": "weak_or_down", "d1_mean_return_pct": 0.02},
            {"dimension": "price_state", "value": "small_positive", "d1_mean_return_pct": 0.03},
            {"dimension": "volume_shape", "value": "staircase_shrink", "d1_mean_return_pct": 0.04},
            {"dimension": "volume_shape", "value": "mixed", "d1_mean_return_pct": 0.05},
            {"dimension": "support_line", "value": "ma5", "d1_mean_return_pct": 0.06},
            {"dimension": "support_line", "value": "ma10", "d1_mean_return_pct": 0.07},
        ],
        "exit_probes": [{"probe": "d5_close", "mean_return_pct": 0.08}],
    }
    answers = build_comprehensive_research_answers(
        {
            "evidence_level": "exploratory_raw_unadjusted",
            "status": "exploratory_complete",
            "blockers": [],
            "case_audit": [
                {
                    "narrative_status": "complete",
                    "expected_setup_matched": True,
                    "data_status": "available",
                },
                {
                    "narrative_status": "complete",
                    "expected_setup_matched": False,
                    "data_status": "label_unavailable",
                },
            ],
            "families": {
                "oversold_rebound": family,
                "trend_pullback": family,
            },
        }
    )
    by_question = {answer["question"]: answer for answer in answers}

    assert by_question["最佳分数区间是否成立"]["status"] == "not_supported"
    assert "80-100 / -0.1000%" in by_question["最佳分数区间是否成立"]["detail"]
    assert "梯形缩量 D+1 0.0400%" in by_question["成交量附加因子何时有效"]["detail"]
    assert "MA10/20 贴合 + 弱势/下跌 + 梯形缩量" in by_question[
        "超跌：M10贴近M20何时更容易D+1收益或日线触板"
    ]["detail"]
    assert "MA5 低点触及" in by_question[
        "趋势：MA5还是MA10，低点触及还是收盘附近"
    ]["detail"]
    assert "不支持形成正式交易规则" in by_question["两类低吸的卖点"]["detail"]
