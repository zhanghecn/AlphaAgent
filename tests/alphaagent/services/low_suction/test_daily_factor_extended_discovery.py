from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import alphaagent.server.services.low_suction.daily_factor_extended_discovery as extended_discovery
import alphaagent.server.services.low_suction.daily_picks_scanner as daily_picks_scanner
from alphaagent.server.services.low_suction.daily_factor_comprehensive_study import (
    PERSONAL_CASES,
)
from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    DISCOVERY_RULES,
    ATTACK_BODY_HOLD_RULE_KEY,
    DiscoveryRule,
    FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
    MA10_MA20_PRE_CROSS_RULE_KEY,
    POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
    PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
    PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
    RESEARCH_THREE_MA_WRAP_RULE_KEY,
    STAGED_MA10_SUPPORT_RULE_KEY,
    _ma10_ma20_next_close_required_return_pct,
    _ma10_ma30_next_close_required_return_pct,
    _has_initial_short_trend_shape,
    _is_score_candidate,
    _research_answers,
    _rule_matches,
    build_pre_attack_base_process_features,
    build_extended_daily_features,
    classify_oversold_attack_stages,
    evaluate_post_limit_up_hold,
    is_first_leg_two_ma_wrap_base_qualified,
    is_mature_first_leg_two_ma_wrap_qualified,
    matching_discovery_rule_keys,
    process_rule_predicates,
    render_extended_daily_factor_markdown,
    run_extended_daily_factor_discovery,
    score_extended_factor,
    summarize_pre_attack_base_process_observations,
    select_exit_probe,
    summarize_score_observations,
    summarize_rule_observations,
)
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.daily_factor_research import DailyFactorInputError
from alphaagent.server.services.low_suction.daily_picks_scanner import scan_low_suction_candidates


def _bar(
    trade_date: date,
    close_price: float,
    *,
    open_price: float | None = None,
    low_price: float | None = None,
    high_price: float | None = None,
    volume: float = 1_000.0,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "open_price": open_price if open_price is not None else close_price,
        "close_price": close_price,
        "low_price": low_price if low_price is not None else close_price * 0.99,
        "high_price": high_price if high_price is not None else close_price * 1.01,
        "volume": volume,
        "turnover": volume * close_price,
    }


def _yang_wrap_stable_base_history(
    *,
    signal_low: float = 9.9,
    signal_volume: float = 500.0,
    volume_path: list[float] | None = None,
) -> list[dict[str, object]]:
    """Flat MA cluster, then one wrapping candle with a controlled volume wash."""

    start = date(2025, 1, 1)
    volumes = [1_000.0] * 24 + (
        volume_path
        if volume_path is not None
        else [1_000.0, 900.0, 800.0, 700.0, 600.0, signal_volume]
    )
    history = [
        _bar(start + timedelta(days=index), 10.0, volume=volume)
        for index, volume in enumerate(volumes[:-1])
    ]
    history.append(
        _bar(
            start + timedelta(days=len(volumes) - 1),
            10.1,
            open_price=9.9,
            low_price=signal_low,
            high_price=10.2,
            volume=volumes[-1],
        )
    )
    return [{**row, "turnover_rate": 2.0} for row in history]


def test_yang_wrap_stable_base_requires_real_touch_and_contracted_volume() -> None:
    history = _yang_wrap_stable_base_history()
    stable = build_extended_daily_features(history)
    low_too_far = build_extended_daily_features(
        _yang_wrap_stable_base_history(signal_low=9.6)
    )
    volume_not_contracted = build_extended_daily_features(
        _yang_wrap_stable_base_history(signal_volume=1_000.0)
    )
    volume_not_orderly = build_extended_daily_features(
        _yang_wrap_stable_base_history(
            volume_path=[1_000.0, 900.0, 1_000.0, 900.0, 1_000.0, 500.0]
        )
    )

    assert stable["yang_wrap_three_ma"] is True
    assert stable["yang_wrap_nearest_ma_low_abs_pct"] <= 1.5
    assert stable["yang_wrap_volume_end_to_peak_ratio_6d"] == pytest.approx(0.5)
    assert stable["vol_monotone_6d"] == pytest.approx(1.0)
    assert stable["yang_wrap_stable_base"] is True
    assert low_too_far["yang_wrap_three_ma"] is True
    assert low_too_far["yang_wrap_stable_base"] is False
    assert volume_not_contracted["yang_wrap_three_ma"] is True
    assert volume_not_contracted["yang_wrap_stable_base"] is False
    assert volume_not_orderly["yang_wrap_three_ma"] is True
    assert volume_not_orderly["yang_wrap_volume_end_to_peak_ratio_6d"] == pytest.approx(0.5)
    assert volume_not_orderly["vol_monotone_6d"] == pytest.approx(0.6)
    assert volume_not_orderly["yang_wrap_stable_base"] is False
    cutoff = history[-1]["trade_date"]
    assert isinstance(cutoff, date)
    assert stable == build_extended_daily_features(
        [*history, _bar(cutoff + timedelta(days=1), 20.0, volume=9_999.0)],
        as_of_date=cutoff,
    )


def _stable_wrap_then_upper_band_confirmation_history() -> list[dict[str, object]]:
    """A causal P3 stable wrap followed by its single-session P2 confirmation."""

    start = date(2026, 1, 2)
    closes = [100 - index * 0.5 for index in range(50)]
    closes += [75 + index * 0.5 for index in range(10)]
    bars = [
        {
            **_bar(
                start + timedelta(days=index),
                close,
                volume=1_000 - max(index - 54, 0) * 100,
            ),
            "turnover_rate": 2.0,
            "vt_symbol": "600721.SSE",
        }
        for index, close in enumerate(closes)
    ]
    before_wrap = build_extended_daily_features(bars)
    bundle_bottom = min(
        float(before_wrap[field]) for field in ("ma10", "ma20", "ma30")
    )
    bundle_top = max(
        float(before_wrap[field]) for field in ("ma10", "ma20", "ma30")
    )
    bars.append(
        {
            **_bar(
                start + timedelta(days=len(bars)),
                bundle_top * 1.003,
                open_price=bundle_bottom * 0.995,
                low_price=bundle_bottom * 0.995,
                high_price=bundle_top * 1.006,
                volume=400.0,
            ),
            "turnover_rate": 2.0,
            "vt_symbol": "600721.SSE",
        }
    )
    wrap_features = build_extended_daily_features(bars)
    wrap_top = max(float(wrap_features[field]) for field in ("ma10", "ma20", "ma30"))
    bars.append(
        {
            **_bar(
                start + timedelta(days=len(bars)),
                float(wrap_features["close_price"]) * 1.02,
                open_price=wrap_top,
                low_price=wrap_top,
                high_price=float(wrap_features["close_price"]) * 1.022,
                volume=600.0,
            ),
            "turnover_rate": 2.0,
            "vt_symbol": "600721.SSE",
        }
    )
    return bars


def test_post_wrap_confirmation_requires_the_immediately_prior_stable_wrap() -> None:
    history = _stable_wrap_then_upper_band_confirmation_history()
    prior_features = build_extended_daily_features(history[:-1])
    features = build_extended_daily_features(history)

    assert process_rule_predicates(
        POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
        features,
        prior_features=prior_features,
    ) == {
        "prior_stable_three_ma_wrap": True,
        "prior_bundle_upper_edge_touch": True,
        "close_above_current_three_ma": True,
        "small_positive_candle": True,
        "candle_quiet": True,
        "turnover_1_5_to_8_pct": True,
    }
    assert matching_discovery_rule_keys(
        features,
        "oversold_rebound",
        prior_features=prior_features,
    ) == (POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,)
    assert matching_discovery_rule_keys(features, "oversold_rebound") == ()
    assert not all(
        process_rule_predicates(
            POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
            {**features, "low_price": float(features["low_price"]) * 1.03},
            prior_features=prior_features,
        ).values()
    )


def test_scan_admits_post_wrap_confirmation_into_the_product_pool() -> None:
    """2026-08 校准升级后，包裹次日上沿确认（Z）是 P1.5 同层产品规则。"""

    bars = _stable_wrap_then_upper_band_confirmation_history()
    calendar = [row["trade_date"] for row in bars]
    signal_date = calendar[-1]

    candidates = scan_low_suction_candidates(
        bars,
        calendar,
        [],
        target_dates={signal_date},
    )

    assert len(candidates) == 1
    assert candidates[0].rule_key == POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY
    assert candidates[0].setup_type == "oversold_rebound"


def test_scan_passes_only_product_oversold_rules_to_snapshot_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_date = date(2026, 7, 23)
    captured: dict[str, object] = {}

    def snapshots(*args, **kwargs):
        captured["rule_manifest"] = kwargs["rule_manifest"]
        return iter(())

    monkeypatch.setattr(
        daily_picks_scanner,
        "_iter_candidate_snapshots",
        snapshots,
    )

    assert daily_picks_scanner.scan_low_suction_candidates(
        [],
        (signal_date,),
        [],
        target_dates={signal_date},
    ) == []

    manifest = captured["rule_manifest"]
    assert isinstance(manifest, dict)
    assert {
        rule.key for rule in manifest["oversold_rebound"]
    } == {
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        STAGED_MA10_SUPPORT_RULE_KEY,
        PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
        PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
        RESEARCH_THREE_MA_WRAP_RULE_KEY,
        POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
    }


def test_baihua_20260803_reference_snapshot_is_a_post_wrap_confirmation() -> None:
    """Regression facts from 百花医药 7-31 stable wrap and 8-3 upper-band retest."""

    prior_features = {
        "long_bear_alignment": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "yang_wrap_three_ma": True,
        # 7-31 真实快照值：宽口径前置（贴线≤2.5 + 量峰比≤0.70）满足。
        "yang_wrap_nearest_ma_low_abs_pct": 1.4247,
        "yang_wrap_volume_end_to_peak_ratio_6d": 0.5286,
        "ma10": 6.949,
        "ma20": 7.017,
        "ma30": 6.9536666667,
    }
    features = {
        "low_price": 7.02,
        "close_price": 7.20,
        "ma10": 6.943,
        "ma20": 7.026,
        "ma30": 6.966,
        "small_positive_candle": True,
        "candle_quiet": True,
        "turnover_rate_pct": 3.63,
    }

    predicates = process_rule_predicates(
        POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
        features,
        prior_features=prior_features,
    )

    assert all(predicates.values())
    assert matching_discovery_rule_keys(
        features,
        "oversold_rebound",
        prior_features=prior_features,
    ) == (POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,)


def _bear_then_m10_cross_history() -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    closes = [100 - index * 0.4 for index in range(64)] + [74.8, 76.0, 78.5, 82.0, 86.0, 89.0]
    return [
        _bar(start + timedelta(days=index), close, volume=2_000 - index * 5)
        for index, close in enumerate(closes)
    ]


def _bear_then_no_cross_three_ma_wrap_history() -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    history = [
        _bar(
            start + timedelta(days=index),
            100 - index * 0.4,
            volume=1_000 - max(0, index - 59) * 100,
        )
        for index in range(64)
    ]
    history.append(
        _bar(
            start + timedelta(days=64),
            84.0,
            open_price=76.1,
            low_price=76.1,
            high_price=84.5,
            volume=500.0,
        )
    )
    return [{**row, "turnover_rate": 2.0} for row in history]


def _bear_then_m10_dual_cross_history() -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    closes = [100 - index * 0.4 for index in range(64)] + [74.8, 76.0, 78.5, 82.0, 90.0, 100.0]
    return [
        _bar(start + timedelta(days=index), close, volume=2_000 - index * 5)
        for index, close in enumerate(closes)
    ]


def _bull_support_history() -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    bars = [
        _bar(start + timedelta(days=index), 10 + index * 0.2, volume=1_000 + index * 10)
        for index in range(70)
    ]
    ma5 = sum(float(row["close_price"]) for row in bars[-5:]) / 5
    bars[-1] = _bar(
        start + timedelta(days=69),
        float(bars[-1]["close_price"]),
        low_price=ma5,
        volume=1_690,
    )
    return bars


def _bull_midpoint_support_history() -> list[dict[str, object]]:
    bars = _bull_support_history()
    bars[-1] = _bar(
        date(2025, 1, 1) + timedelta(days=69),
        24.92,
        low_price=22.2,
        high_price=25.048,
        volume=1_690,
    )
    return bars


def _oversold_to_trend_history_without_regular_ma5() -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    decline = [100 - index * 0.2 for index in range(50)]
    rebound = [90.2 + (index + 1) * 1.2 for index in range(5)]
    pullback = [96.2 - (index + 1) * 0.8 for index in range(6)]
    closes = [*decline, *rebound, *pullback]
    closes[-1] = closes[-2] * 1.003
    bars = [
        _bar(start + timedelta(days=index), close, volume=1_000 + index)
        for index, close in enumerate(closes)
    ]
    bars[-1]["open_price"] = closes[-1] / 1.003
    return bars


def _three_line_bull_with_ma60_above_history() -> list[dict[str, object]]:
    """长期下跌刚转势：MA10>MA20>MA30 三线多头已形成，但 MA60 仍压在 MA30 上方。

    旧四线口径（MA10>MA20>MA30>MA60）会判 trend_bull_alignment=False；去 M60 后应放宽通过。
    """
    start = date(2025, 1, 1)
    closes = [22.0 - index * 0.18 for index in range(45)]
    base = closes[-1]
    closes += [base + index * 0.13 for index in range(30)]
    closes[-1] = closes[-2] * 0.996  # 末根小阴回踩
    return [
        _bar(start + timedelta(days=index), close, volume=1_000 + index)
        for index, close in enumerate(closes)
    ]


def test_trend_bull_alignment_admits_three_line_bull_without_ma60() -> None:
    features = build_extended_daily_features(_three_line_bull_with_ma60_above_history())

    # 三线多头已形成，但 MA60 仍在 MA30 上方（旧四线口径会因此被挡）
    assert features["ma10"] > features["ma20"] > features["ma30"]
    assert features["ma60"] > features["ma30"]
    assert features["trend_bull_alignment"] is True
    assert features["trend_all_slopes_up"] is True


def test_scan_admits_three_line_trend_candidate_without_ma60() -> None:
    bars = [
        {**row, "vt_symbol": "600001.SSE", "turnover_rate": 2.0}
        for row in _three_line_bull_with_ma60_above_history()
    ]
    calendar = [row["trade_date"] for row in bars]
    candidates = scan_low_suction_candidates(bars, calendar, [], target_dates={calendar[-1]})

    trend = [candidate for candidate in candidates if candidate.setup_type == "trend_pullback"]
    assert len(trend) == 1
    assert trend[0].rule_key == "ma5_low_touch_stable_trend"
    assert trend[0].as_dict()["rule_label"] == next(
        rule.description
        for rule in DISCOVERY_RULES["trend_pullback"]
        if rule.key == trend[0].rule_key
    )


def test_scan_admits_calibrated_stable_three_ma_wrap_into_the_product_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-08 校准升级后，三线包裹缩量底盘（W）是 P1.5 同层产品规则。"""

    signal_date = date(2026, 7, 23)
    snapshot = SimpleNamespace(
        symbol="003032.SZSE",
        trade_date=signal_date,
        position=0,
        history=(_bar(signal_date, 10.0, volume=1_000.0),),
        features={
            "close_price": 10.0,
            "daily_return_pct": 1.0,
            "turnover_rate_pct": 9.0,
            "candle_range_pct": 2.0,
            "long_bear_alignment": True,
            "yang_wrap_three_ma": True,
            "yang_wrap_stable_base": True,
        },
        prior_features=None,
        d1_close_return_pct=1.0,
        d1_label_status="available",
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            (RESEARCH_THREE_MA_WRAP_RULE_KEY,)
            if setup_type == "oversold_rebound"
            else ()
        ),
    )

    candidates = daily_picks_scanner.scan_low_suction_candidates(
        [],
        (signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
    )

    assert len(candidates) == 1
    assert candidates[0].rule_key == RESEARCH_THREE_MA_WRAP_RULE_KEY
    assert candidates[0].setup_type == "oversold_rebound"


def test_scan_still_excludes_unvalidated_attack_body_hold_from_the_product_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_date = date(2026, 8, 7)
    snapshot = SimpleNamespace(
        symbol="000859.SZSE",
        trade_date=signal_date,
        position=0,
        history=(_bar(signal_date, 10.0, volume=1_000.0),),
        features={
            "close_price": 10.0,
            "daily_return_pct": -1.0,
            "turnover_rate_pct": 5.5,
            "candle_range_pct": 3.9,
            "long_bear_alignment": True,
        },
        prior_features=None,
        d1_close_return_pct=10.0,
        d1_label_status="available",
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            (ATTACK_BODY_HOLD_RULE_KEY,)
            if setup_type == "oversold_rebound"
            else ()
        ),
    )

    candidates = daily_picks_scanner.scan_low_suction_candidates(
        [],
        (signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
    )

    assert candidates == []


@pytest.mark.parametrize(
    "research_rule_key",
    (ATTACK_BODY_HOLD_RULE_KEY, MA10_MA20_PRE_CROSS_RULE_KEY),
)
def test_scan_excludes_research_only_oversold_rules_from_daily_candidates(
    monkeypatch: pytest.MonkeyPatch,
    research_rule_key: str,
) -> None:
    signal_date = date(2026, 7, 23)
    snapshot = SimpleNamespace(
        symbol="003032.SZSE",
        trade_date=signal_date,
        position=0,
        history=(_bar(signal_date, 10.0, volume=1_000.0),),
        features={
            "close_price": 10.0,
            "daily_return_pct": 1.0,
            "turnover_rate_pct": 2.0,
            "candle_range_pct": 2.0,
        },
        prior_features=None,
        d1_close_return_pct=1.0,
        d1_label_status="available",
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            (research_rule_key,) if setup_type == "oversold_rebound" else ()
        ),
    )

    assert daily_picks_scanner.scan_low_suction_candidates(
        [],
        (signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
    ) == []


def test_scan_admits_only_mature_first_leg_two_ma_wrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_date = date(2026, 7, 23)
    snapshot = SimpleNamespace(
        symbol="600721.SSE",
        trade_date=signal_date,
        position=0,
        history=(_bar(signal_date, 10.0, volume=1_000.0),),
        features={
            "close_price": 10.0,
            "daily_return_pct": 2.0,
            "turnover_rate_pct": 2.0,
            "candle_range_pct": 2.0,
            "close_to_ma10_pct": 2.0,
            "close_off_low_pct": 3.3,
            "ma10_ma20_convergence_efficiency_5d": 0.1561,
            "ma10_ma20_gap_narrowing_3d_pct": 1.3248,
        },
        prior_features=None,
        d1_close_return_pct=1.0,
        d1_label_status="available",
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            (STAGED_MA10_SUPPORT_RULE_KEY, FIRST_LEG_TWO_MA_WRAP_RULE_KEY)
            if setup_type == "oversold_rebound"
            else ()
        ),
    )

    def direct_attack_base(history, *, include_d_minus_one=False):
        assert include_d_minus_one is True
        return {
            "pre_attack_base_phase": "gradual_support_ladder",
            "pre_attack_base_pivot_age_sessions": 9,
        }

    monkeypatch.setattr(
        daily_picks_scanner,
        "build_pre_attack_base_process_features",
        direct_attack_base,
    )

    candidates = daily_picks_scanner.scan_low_suction_candidates(
        [],
        (signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
    )

    assert [candidate.rule_key for candidate in candidates] == [
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY
    ]
    assert candidates[0].matched_rule_keys == (
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        STAGED_MA10_SUPPORT_RULE_KEY,
    )


def test_scan_excludes_a_signal_day_closed_at_main_board_limit_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_date = date(2026, 7, 23)
    snapshot = SimpleNamespace(
        symbol="600688.SSE",
        trade_date=signal_date,
        position=1,
        history=(
            _bar(signal_date - timedelta(days=1), 10.0),
            _bar(
                signal_date,
                11.0,
                open_price=11.0,
                low_price=11.0,
                high_price=11.0,
            ),
        ),
        features={
            "close_price": 11.0,
            "daily_return_pct": 0.0,
            "turnover_rate_pct": 2.0,
            "candle_range_pct": 0.0,
        },
        prior_features=None,
        d1_close_return_pct=1.0,
        d1_label_status="available",
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        daily_picks_scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            (STAGED_MA10_SUPPORT_RULE_KEY,)
            if setup_type == "oversold_rebound"
            else ()
        ),
    )

    assert daily_picks_scanner.scan_low_suction_candidates(
        [],
        (signal_date - timedelta(days=1), signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
    ) == []


def test_signal_day_limit_up_filter_keeps_an_opened_board() -> None:
    history = (
        _bar(date(2026, 7, 22), 10.0),
        _bar(
            date(2026, 7, 23),
            10.75,
            open_price=10.8,
            low_price=10.5,
            high_price=11.0,
        ),
    )

    assert daily_picks_scanner._signal_day_limit_up_closed(history, 1) is False


def test_signal_day_limit_up_filter_excludes_a_tick_rounded_limit_close() -> None:
    history = (
        _bar(date(2026, 8, 6), 9.53),
        _bar(
            date(2026, 8, 7),
            10.48,
            open_price=10.48,
            low_price=10.48,
            high_price=10.48,
        ),
    )

    assert daily_picks_scanner._signal_day_limit_up_closed(history, 1) is True


def _m60_rising_overextended_history() -> list[dict[str, object]]:
    """MA60 跟随向上 + 三线多头 + 末段过伸：长期下跌后强反弹，MA60 已拐头向上，
    反弹稳定段有历史 low 回踩 MA5（建立本段 pullback 基准），末几天连续大涨把 MA5 拉离 MA10，
    当天安静小回踩 → M5-M10 严重过伸。
    """
    start = date(2025, 1, 1)
    decline = [30 - index * 0.22 for index in range(50)]
    rebound = [decline[-1] + index * 0.18 for index in range(45)]
    bars = [_bar(start + timedelta(days=index), close) for index, close in enumerate(decline + rebound)]

    closes = pd.Series([bar["close_price"] for bar in bars])
    ma5_series = closes.rolling(5).mean()
    pullback_index = len(bars) - 14
    bars[pullback_index] = _bar(
        start + timedelta(days=pullback_index),
        float(closes.iloc[pullback_index]),
        low_price=float(ma5_series.iloc[pullback_index]) * 0.995,
        high_price=float(closes.iloc[pullback_index]) * 1.01,
    )

    last = len(bars) - 1
    cumulative = float(closes.iloc[last - 5])
    for offset in range(4):
        index = last - 4 + offset
        cumulative *= 1.08
        bars[index] = _bar(
            start + timedelta(days=index),
            cumulative,
            low_price=cumulative * 0.99,
            high_price=cumulative * 1.01,
            volume=2500.0,
        )
    end_close = cumulative * 1.005
    bars[last] = _bar(
        start + timedelta(days=last),
        end_close,
        low_price=end_close * 0.99,
        high_price=end_close * 1.01,
        volume=2000.0,
    )
    return bars


def test_trend_overextended_fires_when_ma60_rising() -> None:
    """MA60 跟随向上 + 三线多头 + 末段过伸 → 过伸否决应触发。

    主人方案：full_bull_history 去 MA60 排列要求（不再要求 MA5>MA10>MA20>MA30>MA60），
    改判 MA60 方向跟随向上（MA60 > 5 日前）。MA60 向上时过伸统计正常生效。

    注：合成走势里三线多头与 MA60 向下互斥（持续反弹必推高 MA60），故 arrange/rising 两口径
    在合成样本上行为一致；本测试为回归保护，区分性验证依赖半年回测数据。
    """
    features = build_extended_daily_features(_m60_rising_overextended_history())

    assert features["ma10"] > features["ma20"] > features["ma30"]
    assert features["trend_bull_alignment"] is True
    assert features["trend_overextended"] is True


def _calendar(start: date = date(2025, 1, 1), days: int = 45) -> tuple[date, ...]:
    return tuple(start + timedelta(days=index) for index in range(days))


def test_oversold_cross_timing_is_causal_and_detects_m10_first() -> None:
    features = build_extended_daily_features(_bear_then_m10_cross_history())

    assert features["ma10_crossed_ma20_within_5d"] is True
    assert features["ma20_crossed_ma30_within_5d"] is False
    assert features["staged_m10_first"] is True
    assert features["long_bear_alignment"] is True
    assert features["ma10_crossed_ma20_after_long_bear_within_15d"] is True
    assert features["ma10_above_ma20"] is True
    assert features["ma10_below_ma30"] is True


def test_ma10_ma20_next_close_requirement_uses_d_and_earlier_closes() -> None:
    assert _ma10_ma20_next_close_required_return_pct([10.0] * 19) is None
    assert _ma10_ma20_next_close_required_return_pct([10.0] * 20) == 0.0
    assert _ma10_ma20_next_close_required_return_pct([10.0] * 11 + [9.0] * 9) == pytest.approx(
        111.1111
    )


def test_ma10_ma30_next_close_requirement_uses_d_and_earlier_closes() -> None:
    assert _ma10_ma30_next_close_required_return_pct([10.0] * 29) is None
    assert _ma10_ma30_next_close_required_return_pct([10.0] * 30) == 0.0
    assert _ma10_ma30_next_close_required_return_pct(
        [10.0] * 21 + [9.0] * 9
    ) == pytest.approx(111.1111)


def test_three_ma_wrap_requires_ma10_cross_after_long_bear() -> None:
    features = build_extended_daily_features(_bear_then_no_cross_three_ma_wrap_history())

    assert features["long_bear_alignment"] is True
    assert features["yang_wrap_three_ma"] is True
    assert features["yang_wrap_stable_base"] is True
    assert features["ma10_crossed_ma20_after_long_bear_within_15d"] is False
    assert features["current_full_bear_alignment"] is True
    assert _rule_matches(
        next(
            rule
            for rule in DISCOVERY_RULES["oversold_rebound"]
            if rule.key == RESEARCH_THREE_MA_WRAP_RULE_KEY
        ),
        features,
    ) is False


def test_oversold_dual_cross_keeps_m20_below_m30_without_future_data() -> None:
    history = _bear_then_m10_dual_cross_history()
    decision_date = history[-1]["trade_date"]
    features = build_extended_daily_features(history)

    assert features["ma10_crossed_ma20_within_5d"] is True
    assert features["ma10_crossed_ma30_within_5d"] is True
    assert features["ma20_crossed_ma30_within_5d"] is False
    assert features["m10_dual_cross_before_m20_m30"] is True
    assert features == build_extended_daily_features(
        history + [_bar(decision_date + timedelta(days=1), 200.0)],
        as_of_date=decision_date,
    )


def test_trend_support_uses_d_low_not_d_high() -> None:
    features = build_extended_daily_features(_bull_support_history())

    assert features["ma5_low_touch"] is True
    assert features["ma10_low_touch"] is False


def test_trend_support_compares_intraday_midpoint_separately_from_low_and_close() -> None:
    features = build_extended_daily_features(_bull_midpoint_support_history())

    assert features["intraday_midpoint_price"] == 23.624
    assert features["ma5_midpoint_near"] is True
    assert features["ma5_low_touch"] is False
    assert features["ma5_close_near"] is False


def test_appending_future_bars_cannot_change_extended_features_before_cutoff() -> None:
    history = _bear_then_m10_cross_history()
    cutoff = history[-2]["trade_date"]
    expected = build_extended_daily_features(history, as_of_date=cutoff)
    actual = build_extended_daily_features(
        [*history, _bar(date(2025, 4, 1), 120.0)],
        as_of_date=cutoff,
    )

    assert actual == expected


def test_manifest_contains_exactly_the_complete_personal_case_rules() -> None:
    expected = {
        setup_type: {
            key
            for case in PERSONAL_CASES
            if case.expected_setup_type == setup_type
            and case.narrative_status == "complete"
            for key in case.required_process_rule_keys
        }
        for setup_type in DISCOVERY_RULES
    }

    assert {
        setup_type: {rule.key for rule in rules}
        for setup_type, rules in DISCOVERY_RULES.items()
    } == expected


def test_discovery_manifest_rule_keys_are_unique_per_family() -> None:
    for rules in DISCOVERY_RULES.values():
        keys = [rule.key for rule in rules]

        assert len(keys) == len(set(keys))


def test_manifest_excludes_retired_generic_rule_families() -> None:
    rules = {rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]}
    trend_keys = {rule.key for rule in DISCOVERY_RULES["trend_pullback"]}

    assert RESEARCH_THREE_MA_WRAP_RULE_KEY in rules
    assert POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY in rules
    assert STAGED_MA10_SUPPORT_RULE_KEY in rules
    assert "ma10_low_retest_staged_m30_converging_volume_shrink" not in rules
    assert "ma10_ma30_converging_after_staged_cross_volume_shrink" not in rules
    assert "m5_m10_joint_attack_before_ma20_cross_last_volume_expand" not in rules
    assert MA10_MA20_PRE_CROSS_RULE_KEY in rules
    assert ATTACK_BODY_HOLD_RULE_KEY in rules
    assert FIRST_LEG_TWO_MA_WRAP_RULE_KEY in rules
    assert "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30" not in rules
    assert "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30" in trend_keys
    assert "v3_oversold_universal_pullback" not in rules
    assert "v4_trend_quiet_pullback" not in trend_keys


def test_explicit_personal_case_rules_expose_their_causal_requirements() -> None:
    oversold_rules = {
        rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]
    }
    trend_rules = {
        rule.key: rule for rule in DISCOVERY_RULES["trend_pullback"]
    }
    stable_wrap = {
        "long_bear_alignment": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "yang_wrap_three_ma": True,
        "yang_wrap_nearest_ma_low_abs_pct": 0.8,
        "yang_wrap_volume_end_to_peak_ratio_6d": 0.4,
    }
    post_wrap_confirmation = {
        "low_price": 10.0,
        "close_price": 10.3,
        "ma10": 9.9,
        "ma20": 10.0,
        "ma30": 10.1,
        "small_positive_candle": True,
        "candle_quiet": True,
        "turnover_rate_pct": 2.0,
    }
    post_wrap_prior = {**stable_wrap, "ma10": 9.8, "ma20": 9.9, "ma30": 10.0}
    staged_ma10_support = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma10_above_ma20": True,
        "ma10_below_ma30": True,
        "ma10_low_touch": True,
        "ma10_close_near": True,
        "ma10_ma30_fast_convergence": True,
        "volume_shape": "staircase_shrink",
        "vol_monotone_6d": 0.8,
    }
    ma10_retest_after_cross = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_within_15d": True,
        "ma10_was_above_ma30_within_15d": True,
        "ma10_ma30_contact": True,
        "aggressive_pullback": True,
        "volume_shrink_then_expand": True,
    }
    ma10_after_ma5_extension = {
        "trend_discovery_eligible": True,
        "trend_stable_bull": True,
        "ma5_regular": True,
        "ma10_low_touch": True,
        "prior_ma5_close_extension": True,
        "prior_daily_price_not_up": True,
    }
    yiming_pre_cross = {
        "long_bear_alignment": True,
        "current_full_bear_alignment": True,
        "ma10_below_ma20": True,
        "ma10_ma20_contact": True,
        "ma10_ma20_gap_narrowing": True,
        "positive_candle": True,
        "last_volume_expanded": True,
    }
    yiming_trend_transition = {
        "long_bear_alignment": True,
        "ma10_dual_cross_within_7d": True,
        "ma10_above_ma20_and_ma30": True,
        "transition_ma20_ma30_tight_contact": True,
        "ma10_ma20_slopes_up": True,
        "post_cross_pullback": True,
        "small_positive_candle": True,
        "volume_expand_then_shrink": True,
    }

    stable_wrap_key = RESEARCH_THREE_MA_WRAP_RULE_KEY
    post_wrap_key = POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY
    staged_key = STAGED_MA10_SUPPORT_RULE_KEY
    retest_key = "ma10_ma30_retest_after_actual_cross_two_leg_volume"
    yiming_pre_cross_key = MA10_MA20_PRE_CROSS_RULE_KEY
    yiming_transition_key = "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30"
    fallback_key = "ma10_low_touch_after_ma5_extension"
    assert stable_wrap_key in oversold_rules
    assert post_wrap_key in oversold_rules
    assert staged_key in oversold_rules
    assert retest_key in oversold_rules
    assert yiming_pre_cross_key in oversold_rules
    assert yiming_transition_key in trend_rules
    assert fallback_key in trend_rules
    assert process_rule_predicates(stable_wrap_key, stable_wrap) == {
        "long_bear_alignment": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "yang_wrap_three_ma": True,
        "yang_wrap_shrink_stable_base": True,
    }
    assert _rule_matches(oversold_rules[stable_wrap_key], stable_wrap) is True
    assert _rule_matches(
        oversold_rules[stable_wrap_key],
        {**stable_wrap, "yang_wrap_nearest_ma_low_abs_pct": 2.0},
    ) is False
    assert _rule_matches(
        oversold_rules[stable_wrap_key],
        {**stable_wrap, "yang_wrap_volume_end_to_peak_ratio_6d": 0.8},
    ) is False
    assert _rule_matches(
        oversold_rules[stable_wrap_key],
        {**stable_wrap, "ma10_crossed_ma20_after_long_bear_within_15d": False},
    ) is False
    assert process_rule_predicates(
        post_wrap_key,
        post_wrap_confirmation,
        prior_features=post_wrap_prior,
    ) == {
        "prior_stable_three_ma_wrap": True,
        "prior_bundle_upper_edge_touch": True,
        "close_above_current_three_ma": True,
        "small_positive_candle": True,
        "candle_quiet": True,
        "turnover_1_5_to_8_pct": True,
    }
    assert _rule_matches(
        oversold_rules[post_wrap_key],
        post_wrap_confirmation,
        prior_features=post_wrap_prior,
    ) is True
    assert _rule_matches(
        oversold_rules[post_wrap_key],
        post_wrap_confirmation,
    ) is False
    assert process_rule_predicates(staged_key, staged_ma10_support) == {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma10_above_ma20": True,
        "ma10_below_ma30": True,
        "ma10_low_touch": True,
        "ma10_close_near": True,
        "ma10_ma30_fast_convergence": True,
        "volume_shape_staircase_shrink": True,
        "volume_monotone_6d_at_least_0_8": True,
    }
    assert _rule_matches(oversold_rules[staged_key], staged_ma10_support) is True
    assert _rule_matches(
        oversold_rules[staged_key],
        {**staged_ma10_support, "ma10_close_near": False},
    ) is False
    assert _rule_matches(
        oversold_rules[staged_key],
        {**staged_ma10_support, "ma10_ma30_fast_convergence": False},
    ) is False
    assert _rule_matches(
        oversold_rules[staged_key],
        {**staged_ma10_support, "vol_monotone_6d": 0.6},
    ) is False
    assert _rule_matches(oversold_rules[retest_key], ma10_retest_after_cross) is True
    assert _rule_matches(
        oversold_rules[retest_key],
        {**ma10_retest_after_cross, "ma10_was_above_ma30_within_15d": False},
    ) is False
    assert _rule_matches(oversold_rules[yiming_pre_cross_key], yiming_pre_cross) is True
    assert _rule_matches(
        oversold_rules[yiming_pre_cross_key],
        {**yiming_pre_cross, "current_full_bear_alignment": False},
    ) is False
    assert _rule_matches(
        oversold_rules[yiming_pre_cross_key],
        {**yiming_pre_cross, "ma10_below_ma20": False},
    ) is False
    assert _rule_matches(
        trend_rules[yiming_transition_key], yiming_trend_transition
    ) is True
    assert _rule_matches(
        trend_rules[yiming_transition_key],
        {**yiming_trend_transition, "ma10_ma20_slopes_up": False},
    ) is False
    assert _rule_matches(trend_rules[fallback_key], ma10_after_ma5_extension) is True
    assert _rule_matches(
        trend_rules[fallback_key],
        {**ma10_after_ma5_extension, "prior_ma5_close_extension": False},
    ) is False


def test_attack_body_hold_requires_a_shrunk_retest_above_the_attack_open() -> None:
    features = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma10_above_ma20": True,
        "ma10_below_ma30": True,
        "ma10_ma30_fast_convergence": True,
        "prior_positive_body_pct": 4.82,
        "prior_limit_up_touched": False,
        "daily_return_pct": -1.03,
        "candle_quiet": True,
        "attack_body_low_held": True,
        "attack_body_close_held": True,
        "last_volume_to_prior_ratio": 0.72,
    }

    assert process_rule_predicates(ATTACK_BODY_HOLD_RULE_KEY, features) == {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma10_above_ma20": True,
        "ma10_below_ma30": True,
        "ma10_ma30_fast_convergence": True,
        "prior_attack_body_at_least_3_pct": True,
        "prior_attack_not_limit_up": True,
        "controlled_retest_candle": True,
        "attack_body_low_held": True,
        "attack_body_close_held": True,
        "volume_shrunk_to_80_pct_or_less": True,
    }

    rule = next(
        rule
        for rule in DISCOVERY_RULES["oversold_rebound"]
        if rule.key == ATTACK_BODY_HOLD_RULE_KEY
    )
    assert _rule_matches(rule, features) is True
    assert _rule_matches(rule, {**features, "attack_body_low_held": False}) is False
    assert _rule_matches(rule, {**features, "attack_body_close_held": False}) is False
    assert _rule_matches(rule, {**features, "prior_positive_body_pct": 2.99}) is False
    assert _rule_matches(rule, {**features, "last_volume_to_prior_ratio": 0.81}) is False


def test_first_leg_two_ma_wrap_keeps_the_d_attack_anchor_and_base_gate_separate() -> None:
    """百花 7-14 型首段攻击：D 实体跨两线，MA30 留给下一阶段。"""

    features = {
        "long_bear_alignment": True,
        "current_full_bear_alignment": True,
        "yang_wrap_two_ma": True,
        "close_below_ma30": True,
        "signal_day_not_limit_up_closed": True,
        "ma10_ma20_convergence_efficiency_5d": 0.1561,
        "ma10_ma20_gap_narrowing_3d_pct": 1.3248,
        "pre_attack_base_phase": "gradual_support_ladder",
    }
    oversold_rules = {
        rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]
    }

    assert process_rule_predicates(FIRST_LEG_TWO_MA_WRAP_RULE_KEY, features) == {
        "long_bear_alignment": True,
        "current_full_bear_alignment": True,
        "yang_wrap_two_ma": True,
        "close_below_ma30": True,
        "signal_day_not_limit_up_closed": True,
    }
    assert _rule_matches(oversold_rules[FIRST_LEG_TWO_MA_WRAP_RULE_KEY], features)
    assert is_first_leg_two_ma_wrap_base_qualified(features)
    assert not is_first_leg_two_ma_wrap_base_qualified(
        {**features, "pre_attack_base_phase": "fresh_expansion"}
    )
    assert not is_first_leg_two_ma_wrap_base_qualified(
        {**features, "ma10_ma20_convergence_efficiency_5d": 0.1560}
    )
    assert not is_first_leg_two_ma_wrap_base_qualified(
        {**features, "ma10_ma20_gap_narrowing_3d_pct": 1.3247}
    )
    assert not _rule_matches(
        oversold_rules[FIRST_LEG_TWO_MA_WRAP_RULE_KEY],
        {**features, "close_below_ma30": False},
    )


def test_baihua_20260714_mature_first_leg_requires_non_chasing_attack_and_reaction() -> None:
    """百花医药 7-14：D 日包裹 MA10/20、MA10 尚未上穿 MA20。"""

    features = {
        "pre_attack_base_phase": "gradual_support_ladder",
        "ma10_ma20_convergence_efficiency_5d": 0.3472,
        "ma10_ma20_gap_narrowing_3d_pct": 3.0831,
        "close_to_ma10_pct": 0.9094,
        "daily_return_pct": 2.6866,
        "pre_attack_base_pivot_age_sessions": 10,
        "close_off_low_pct": 4.0847,
    }

    assert is_mature_first_leg_two_ma_wrap_qualified(features)
    assert not is_mature_first_leg_two_ma_wrap_qualified(
        {**features, "close_to_ma10_pct": 3.1}
    )
    assert not is_mature_first_leg_two_ma_wrap_qualified(
        {**features, "daily_return_pct": 5.1}
    )
    assert not is_mature_first_leg_two_ma_wrap_qualified(
        {**features, "ma10_ma20_gap_narrowing_3d_pct": 4.1}
    )
    assert not is_mature_first_leg_two_ma_wrap_qualified(
        {**features, "pre_attack_base_pivot_age_sessions": 8}
    )
    assert not is_mature_first_leg_two_ma_wrap_qualified(
        {**features, "close_off_low_pct": 3.2}
    )


def test_oversold_attack_stages_keep_d_day_roles_distinct_from_scores() -> None:
    first_leg = {
        "long_bear_alignment": True,
        "current_full_bear_alignment": True,
        "ma10_below_ma20": True,
        "positive_candle": True,
        "ma10_ma20_gap_narrowing": True,
        "yang_wrap_two_ma": True,
        "close_below_ma30": True,
        "signal_day_not_limit_up_closed": True,
    }
    bridge_hold = {
        "long_bear_alignment": True,
        "ma10_above_ma20": True,
        "ma10_below_ma30": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma10_crossed_ma20_after_long_bear_age_sessions_15d": 2,
        "ma10_low_touch": True,
        "controlled_attack_body_retest_candle": True,
        "attack_body_low_held": True,
        "attack_body_close_held": True,
    }
    hold_without_ma10_touch = {
        key: value for key, value in bridge_hold.items() if key != "ma10_low_touch"
    }
    price_first = {
        "long_bear_alignment": True,
        "current_full_bear_alignment": True,
        "positive_candle": True,
        "ma10_below_ma30": True,
        "ma10_ma30_fast_convergence": True,
        "close_to_ma10_pct": 8.5,
    }

    assert classify_oversold_attack_stages(first_leg) == (
        "pre_cross_pressure",
        "first_leg_two_ma_wrap",
    )
    assert classify_oversold_attack_stages(bridge_hold) == (
        "second_leg_support_before_ma30",
        "attack_body_hold",
    )
    assert classify_oversold_attack_stages(hold_without_ma10_touch) == (
        "attack_body_hold",
    )
    assert classify_oversold_attack_stages(price_first) == (
        "price_first_observation",
    )
    assert classify_oversold_attack_stages({}) == ()


def _pre_attack_base_history(
    base_closes: list[float],
    base_lows: list[float],
    *,
    prefix_sessions: int = 30,
) -> list[dict[str, object]]:
    """Build 15 D-2-and-earlier base sessions followed by D-1 and D."""

    assert len(base_closes) == len(base_lows) == 15
    start = date(2025, 1, 1)
    history = [
        _bar(start + timedelta(days=index), 100.0, volume=1_000.0)
        for index in range(prefix_sessions)
    ]
    for offset, (close_price, low_price) in enumerate(zip(base_closes, base_lows)):
        history.append(
            _bar(
                start + timedelta(days=prefix_sessions + offset),
                close_price,
                low_price=low_price,
                high_price=max(close_price * 1.01, low_price * 1.02),
                volume=1_000.0,
            )
        )
    prior_close = base_closes[-1]
    history.extend(
        (
            _bar(
                start + timedelta(days=prefix_sessions + 15),
                prior_close * 1.05,
                low_price=prior_close,
                volume=2_000.0,
            ),
            _bar(
                start + timedelta(days=prefix_sessions + 16),
                prior_close * 1.04,
                low_price=prior_close * 1.01,
                volume=1_000.0,
            ),
        )
    )
    return history


def test_pre_attack_base_process_recognizes_release_retest_after_final_washout() -> None:
    history = _pre_attack_base_history(
        [100.0, 98.0, 96.0, 92.0, 90.0, 91.0, 96.0, 95.0, 94.0, 93.0, 94.0, 93.0, 92.5, 92.0, 93.0],
        [99.0, 96.0, 94.0, 89.0, 85.0, 90.0, 95.0, 94.0, 93.0, 92.0, 92.5, 91.5, 90.2, 90.0, 90.1],
    )

    features = build_pre_attack_base_process_features(history)

    assert features["pre_attack_base_phase"] == "release_retest_base"
    assert features["pre_attack_base_pivot_age_sessions"] == 10
    assert features["pre_attack_base_release_after_final_pivot"] is True
    assert features["pre_attack_base_settlement_sessions"] == 8
    assert features["pre_attack_base_tail_retested_release"] is True
    assert features["pre_attack_base_tail_floor_vs_pivot_pct"] == pytest.approx(5.8824)
    assert features["pre_attack_base_tail_span_to_median_range"] < 1.0


def test_pre_attack_base_process_rejects_release_before_the_final_washout() -> None:
    history = _pre_attack_base_history(
        [100.0, 106.0, 104.0, 100.0, 95.0, 90.0, 91.0, 90.5, 91.0, 90.7, 91.2, 91.0, 91.3, 91.1, 91.4],
        [99.0, 105.0, 102.0, 98.0, 92.0, 85.0, 89.0, 89.5, 89.8, 89.7, 90.0, 89.9, 90.1, 90.0, 90.2],
    )

    features = build_pre_attack_base_process_features(history)

    assert features["pre_attack_base_phase"] == "post_release_washout"
    assert features["pre_attack_base_release_after_final_pivot"] is False
    assert features["pre_attack_base_tail_floor_vs_pivot_pct"] > 0


def test_pre_attack_base_process_keeps_a_tail_washout_in_the_post_release_phase() -> None:
    history = _pre_attack_base_history(
        [100.0, 106.0, 104.0, 102.0, 100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 89.0, 88.0, 87.0, 86.0, 87.0],
        [99.0, 105.0, 102.0, 100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 87.0, 85.0, 84.0, 80.0, 82.0],
    )

    features = build_pre_attack_base_process_features(history)

    assert features["pre_attack_base_release_after_final_pivot"] is False
    assert features["pre_attack_base_tail_floor_vs_pivot_pct"] == 0.0
    assert features["pre_attack_base_phase"] == "post_release_washout"


def test_pre_attack_base_process_recognizes_gradual_support_without_a_release() -> None:
    history = _pre_attack_base_history(
        [100.0, 98.8, 97.5, 96.3, 95.4, 94.5, 95.0, 95.4, 95.8, 95.3, 95.7, 95.5, 95.8, 95.7, 95.9],
        [99.0, 97.8, 96.5, 95.3, 94.4, 92.5, 94.0, 94.5, 94.8, 94.6, 94.9, 94.8, 95.0, 94.9, 95.1],
    )

    features = build_pre_attack_base_process_features(history)

    assert features["pre_attack_base_phase"] == "gradual_support_ladder"
    assert features["pre_attack_base_release_after_final_pivot"] is False
    assert features["pre_attack_base_settlement_sessions"] == 15
    assert features["pre_attack_base_tail_floor_vs_pivot_pct"] > 0


def test_pre_attack_base_process_excludes_d_minus_one_and_d_from_its_features() -> None:
    history = _pre_attack_base_history(
        [100.0, 98.0, 96.0, 92.0, 90.0, 91.0, 96.0, 95.0, 94.0, 93.0, 94.0, 93.0, 92.5, 92.0, 93.0],
        [99.0, 96.0, 94.0, 89.0, 85.0, 90.0, 95.0, 94.0, 93.0, 92.0, 92.5, 91.5, 90.2, 90.0, 90.1],
        prefix_sessions=70,
    )
    cutoff = history[-1]["trade_date"]
    assert isinstance(cutoff, date)
    changed_attack_and_signal = [
        *history[:-2],
        _bar(history[-2]["trade_date"], 200.0, low_price=1.0, high_price=210.0, volume=99_999.0),
        _bar(history[-1]["trade_date"], 2.0, low_price=1.0, high_price=210.0, volume=1.0),
    ]

    expected = build_extended_daily_features(
        history,
        as_of_date=cutoff,
        include_pre_attack_base_features=True,
    )
    actual = build_extended_daily_features(
        changed_attack_and_signal,
        as_of_date=cutoff,
        include_pre_attack_base_features=True,
    )

    for field in (
        "pre_attack_base_phase",
        "pre_attack_base_pivot_age_sessions",
        "pre_attack_base_release_after_final_pivot",
        "pre_attack_base_settlement_sessions",
        "pre_attack_base_tail_span_to_median_range",
        "pre_attack_base_tail_floor_vs_pivot_pct",
        "pre_attack_base_tail_retested_release",
        "pre_attack_base_ma10_ma20_progress_per_churn",
    ):
        assert actual[field] == expected[field]


def test_pre_attack_base_process_can_include_d_minus_one_for_direct_attack() -> None:
    history = _pre_attack_base_history(
        [100.0, 98.0, 96.0, 92.0, 90.0, 91.0, 96.0, 95.0, 94.0, 93.0, 94.0, 93.0, 92.5, 92.0, 93.0],
        [99.0, 96.0, 94.0, 89.0, 85.0, 90.0, 95.0, 94.0, 93.0, 92.0, 92.5, 91.5, 90.2, 90.0, 90.1],
        prefix_sessions=70,
    )
    baseline = build_pre_attack_base_process_features(
        history,
        include_d_minus_one=True,
    )
    changed_signal = [
        *history[:-1],
        _bar(history[-1]["trade_date"], 2.0, low_price=1.0, high_price=210.0),
    ]
    changed_d_minus_one = [
        *history[:-2],
        _bar(history[-2]["trade_date"], 2.0, low_price=1.0, high_price=210.0),
        history[-1],
    ]

    assert (
        build_pre_attack_base_process_features(
            changed_signal,
            include_d_minus_one=True,
        )
        == baseline
    )
    assert (
        build_pre_attack_base_process_features(
            changed_d_minus_one,
            include_d_minus_one=True,
        )
        != baseline
    )


def test_pre_attack_base_process_is_opt_in_for_shared_feature_snapshots() -> None:
    history = _pre_attack_base_history(
        [100.0, 98.0, 96.0, 92.0, 90.0, 91.0, 96.0, 95.0, 94.0, 93.0, 94.0, 93.0, 92.5, 92.0, 93.0],
        [99.0, 96.0, 94.0, 89.0, 85.0, 90.0, 95.0, 94.0, 93.0, 92.0, 92.5, 91.5, 90.2, 90.0, 90.1],
        prefix_sessions=70,
    )

    ordinary = build_extended_daily_features(history)
    research = build_extended_daily_features(
        history,
        include_pre_attack_base_features=True,
    )

    assert "pre_attack_base_phase" not in ordinary
    assert research["pre_attack_base_phase"] == "release_retest_base"


def test_pre_attack_base_process_summary_keeps_same_day_comparisons_separate() -> None:
    first_day = date(2026, 7, 20)
    second_day = date(2026, 7, 21)
    report = summarize_pre_attack_base_process_observations(
        (
            {
                "rule_key": ATTACK_BODY_HOLD_RULE_KEY,
                "trade_date": first_day,
                "d1_label_status": "available",
                "d1_close_return_pct": 3.0,
                "pre_attack_base_phase": "release_retest_base",
            },
            {
                "rule_key": ATTACK_BODY_HOLD_RULE_KEY,
                "trade_date": first_day,
                "d1_label_status": "available",
                "d1_close_return_pct": -1.0,
                "pre_attack_base_phase": "fresh_expansion",
            },
            {
                "rule_key": ATTACK_BODY_HOLD_RULE_KEY,
                "trade_date": second_day,
                "d1_label_status": "available",
                "d1_close_return_pct": 1.0,
                "pre_attack_base_phase": "release_retest_base",
            },
            {
                "rule_key": ATTACK_BODY_HOLD_RULE_KEY,
                "trade_date": second_day,
                "d1_label_status": "available",
                "d1_close_return_pct": 0.0,
                "pre_attack_base_phase": "fresh_expansion",
            },
            {
                "rule_key": ATTACK_BODY_HOLD_RULE_KEY,
                "trade_date": second_day,
                "d1_label_status": "label_excluded_main_board_price_limit",
                "d1_close_return_pct": 10.2,
                "pre_attack_base_phase": "new_price_shelf",
            },
            {
                "rule_key": "another_rule",
                "trade_date": second_day,
                "d1_label_status": "available",
                "d1_close_return_pct": 99.0,
                "pre_attack_base_phase": "release_retest_base",
            },
        )
    )

    groups = {row["phase"]: row for row in report["phase_groups"]}
    retest = groups["release_retest_base"]
    expansion = groups["fresh_expansion"]

    assert report["candidate_count"] == 5
    assert report["label_excluded_main_board_price_limit_count"] == 1
    assert retest["d1_mean_return_pct"] == 2.0
    assert retest["same_day_excess"]["sample_count"] == 2
    assert retest["same_day_excess"]["mean_return_pct"] == 2.5
    assert expansion["same_day_excess"]["mean_return_pct"] == -2.5
    assert "new_price_shelf" not in groups


def test_explicit_case_phase_features_are_causal_at_the_decision_cutoff() -> None:
    history = _bear_then_m10_dual_cross_history()
    cutoff = history[-1]["trade_date"]

    expected = build_extended_daily_features(
        history,
        as_of_date=cutoff,
        include_pre_attack_base_features=True,
    )
    actual = build_extended_daily_features(
        [*history, _bar(cutoff + timedelta(days=1), 200.0, volume=99_999.0)],
        as_of_date=cutoff,
        include_pre_attack_base_features=True,
    )

    for key in (
        "pre_attack_base_phase",
        "pre_attack_base_pivot_age_sessions",
        "pre_attack_base_release_after_final_pivot",
        "pre_attack_base_settlement_sessions",
        "pre_attack_base_tail_span_to_median_range",
        "pre_attack_base_tail_floor_vs_pivot_pct",
        "pre_attack_base_tail_retested_release",
        "pre_attack_base_ma10_ma20_progress_per_churn",
        "ma10_ma30_gap_converging",
        "ma10_was_above_ma30_within_15d",
        "volume_expand_then_shrink",
        "volume_shrink_then_expand",
        "prior_ma5_close_extension",
        "trend_rebuilt_from_disorder",
        "prior_ma5_low_touch",
        "ma10_dual_cross_within_15d",
        "ma10_dual_cross_within_7d",
        "ma10_above_ma20_and_ma30",
        "transition_ma20_ma30_tight_contact",
        "ma10_ma20_slopes_up",
        "post_cross_pullback",
        "small_positive_candle",
        "trend_transition_eligible",
        "trend_transition_preparation_eligible",
    ):
        assert key in expected
        assert actual[key] == expected[key]
    assert "ma5_slope_2d_pct" not in expected
    assert "m5_m10_joint_attack_ready" not in expected


def test_extended_factor_score_keeps_volume_as_an_oversold_addition() -> None:
    oversold_features = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma10_above_ma20": True,
        "ma10_below_ma30": True,
        "staged_m10_first": True,
        "ma10_ma30_gap_converging": True,
        "ma10_ma30_fast_convergence": True,
        "ma20_ma30_contact": True,
        "ma10_low_touch": True,
        "ma10_close_near": True,
        "post_cross_pullback": True,
        "daily_return_pct": -1.0,
        "volume_shape": "staircase_shrink",
        "vol_monotone_6d": 0.8,
        "volume_expand_then_shrink": True,
    }
    trend_features = {
        "trend_bull_alignment": True,
        "trend_all_slopes_up": True,
        "trend_discovery_eligible": True,
        "trend_stable_bull": True,
        "early_trend_alignment": True,
        "ma5_regular": True,
        "ma5_low_touch": True,
        "ma10_low_touch": False,
        "prior_ma5_close_extension": False,
        "daily_return_pct": -1.0,
        "trend_rebuilt_from_disorder": True,
        "prior_ma5_low_touch": True,
    }

    oversold_scores = score_extended_factor(oversold_features, "oversold_rebound")
    assert oversold_scores == {"base": 100.0, "with_volume": 100.0}
    assert score_extended_factor(
        {**oversold_features, "m5_m10_joint_attack_ready": True},
        "oversold_rebound",
    ) == oversold_scores
    assert score_extended_factor(
        {**oversold_features, "volume_shape": "mixed", "volume_expand_then_shrink": False},
        "oversold_rebound",
    ) == {"base": 100.0, "with_volume": 80.0}
    assert score_extended_factor(trend_features, "trend_pullback") == {
        "base": 100.0,
        "with_transition_bonus": 100.0,
    }


def test_transition_bonus_does_not_require_ma5_or_ma60_trend_alignment() -> None:
    transition_features = {
        "long_bear_alignment": True,
        "ma10_dual_cross_within_7d": True,
        "ma10_above_ma20_and_ma30": True,
        "transition_ma20_ma30_tight_contact": True,
        "ma10_ma20_slopes_up": True,
        "post_cross_pullback": True,
        "small_positive_candle": True,
        "trend_transition_eligible": True,
        "volume_expand_then_shrink": True,
        "trend_bull_alignment": False,
        "trend_all_slopes_up": False,
        "trend_discovery_eligible": False,
        "ma5_regular": False,
        "ma5_low_touch": False,
        "ma10_low_touch": False,
    }

    scores = score_extended_factor(transition_features, "trend_pullback")

    assert scores == {"base": 20.0, "with_transition_bonus": 60.0}


def test_transition_is_a_trend_candidate_without_regular_ma5_or_ma60_order() -> None:
    history = _oversold_to_trend_history_without_regular_ma5()
    features = build_extended_daily_features(history)

    assert features["ma5_regular"] is False
    assert features["trend_bull_alignment"] is False
    assert features["trend_transition_eligible"] is True
    assert _is_score_candidate(features, "trend_pullback") is True


def test_source_rule_snapshots_do_not_apply_a_generic_prescreen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Named rules are evaluated before any non-source candidate filter."""

    signal_date = date(2026, 7, 23)
    history = [{**_bar(signal_date, 10.0), "vt_symbol": "003032.SZSE"}]
    monkeypatch.setattr(
        extended_discovery,
        "build_extended_daily_features",
        lambda _: {"named_source_rule": True},
    )
    monkeypatch.setattr(
        extended_discovery,
        "_matches_any_rule",
        lambda _, *, prior_features=None, rule_manifest=None: True,
    )

    snapshots = list(
        extended_discovery._iter_candidate_snapshots(
            history,
            (signal_date,),
            [],
            target_dates={signal_date},
        )
    )

    assert [snapshot.trade_date for snapshot in snapshots] == [signal_date]


def test_d1_initial_trend_shape_keeps_ma5_and_ma60_out_of_the_outcome_label() -> None:
    d1_features = {
        "ma5": 9.5,
        "ma10": 10.3,
        "ma20": 10.2,
        "ma30": 10.1,
        "ma60": 10.8,
        "ma10_slope_5d_pct": 0.8,
        "ma20_slope_5d_pct": 0.2,
    }

    assert _has_initial_short_trend_shape(d1_features) is True
    assert _has_initial_short_trend_shape(
        {**d1_features, "ma20_slope_5d_pct": 0.0}
    ) is False


def test_extended_score_reserves_the_top_band_for_a_complete_source_process() -> None:
    generic_oversold = {
        "long_bear_alignment": True,
        "staged_m10_first": True,
        "ma10_ma30_gap_converging": True,
        "ma10_low_touch": True,
        "daily_return_pct": -1.0,
        "oversold_process_eligible": False,
        "volume_shape": "mixed",
    }

    assert score_extended_factor(generic_oversold, "oversold_rebound") == {
        "base": 80.0,
        "with_volume": 64.0,
    }


def test_extended_factor_score_rejects_unknown_family() -> None:
    with pytest.raises(DailyFactorInputError, match="unsupported extended score setup type"):
        score_extended_factor({}, "unknown")


def test_score_factor_selects_a_development_band_without_later_segment_leakage() -> None:
    calendar = _calendar(days=70)
    observations: list[dict[str, object]] = []
    for index, trade_date in enumerate(calendar):
        observations.extend(
            (
                {
                    "setup_type": "oversold_rebound",
                    "score_variant": "base",
                    "score": 95.0,
                    "vt_symbol": f"000{index:03d}.SZSE",
                    "trade_date": trade_date,
                    "d1_close_return_pct": 0.1 if index < 39 else -2.0,
                    "d1_label_status": "available",
                },
                {
                    "setup_type": "oversold_rebound",
                    "score_variant": "with_volume",
                    "score": 65.0,
                    "vt_symbol": f"600{index:03d}.SSE",
                    "trade_date": trade_date,
                    "d1_close_return_pct": 2.0 if index < 39 else 9.0,
                    "d1_label_status": "available",
                },
            )
        )

    report = summarize_score_observations(
        observations,
        calendar,
        source_case_bands={
            "oversold_rebound": {
                "base": ("90-100",),
                "with_volume": ("90-100",),
            },
        },
    )
    selected = report["families"]["oversold_rebound"]["selected_score_factor"]

    assert selected["variant"] == "base"
    assert selected["band"] == "90-100"
    assert selected["selection_mode"] == "development_window"
    assert selected["holdout"]["d1_mean_return_pct"] == -2.0
    assert selected["qualification_gate"]["passed"] is False
    assert selected["case_membership_gate"]["passed"] is True


def test_rule_selection_uses_development_not_validation_or_holdout() -> None:
    calendar = _calendar(days=70)
    rules = {
        "oversold_rebound": (
            DiscoveryRule("development_winner", "oversold_rebound", "test"),
            DiscoveryRule("holdout_winner", "oversold_rebound", "test"),
        ),
        "trend_pullback": (),
    }
    observations: list[dict[str, object]] = []
    for index, trade_date in enumerate(calendar):
        if index < 39:
            observations.extend(
                (
                    {
                        "setup_type": "oversold_rebound",
                        "rule_key": "development_winner",
                        "vt_symbol": f"000{index:03d}.SZSE",
                        "trade_date": trade_date,
                        "d1_close_return_pct": 2.0,
                        "d1_label_status": "available",
                    },
                    {
                        "setup_type": "oversold_rebound",
                        "rule_key": "holdout_winner",
                        "vt_symbol": f"600{index:03d}.SSE",
                        "trade_date": trade_date,
                        "d1_close_return_pct": 0.1,
                        "d1_label_status": "available",
                    },
                )
            )
        else:
            observations.append(
                {
                    "setup_type": "oversold_rebound",
                    "rule_key": "holdout_winner",
                    "vt_symbol": f"600{index:03d}.SSE",
                    "trade_date": trade_date,
                    "d1_close_return_pct": 9.0,
                    "d1_label_status": "available",
                }
            )

    report = summarize_rule_observations(observations, calendar, rule_manifest=rules)

    assert report["families"]["oversold_rebound"]["selected_rule"]["key"] == "development_winner"


def test_rule_summary_reports_d1_short_trend_as_an_outcome_label() -> None:
    calendar = _calendar(days=70)
    rules = {
        "oversold_rebound": (),
        "trend_pullback": (DiscoveryRule("transition", "trend_pullback", "test"),),
    }
    observations = [
        {
            "setup_type": "trend_pullback",
            "rule_key": "transition",
            "vt_symbol": f"600{index:03d}.SSE",
            "trade_date": trade_date,
            "d1_close_return_pct": 1.0,
            "d1_label_status": "available",
            "d1_initial_short_trend_formed": index % 2 == 0,
        }
        for index, trade_date in enumerate(calendar)
    ]

    report = summarize_rule_observations(observations, calendar, rule_manifest=rules)
    summary = report["families"]["trend_pullback"]["rules"][0]["overall"]

    assert summary["d1_initial_short_trend_formed_available_count"] == 70
    assert summary["d1_initial_short_trend_formed_count"] == 35
    assert summary["d1_initial_short_trend_formed_rate_pct"] == 50.0


def test_transition_rule_splits_the_optional_volume_confirmation() -> None:
    calendar = _calendar(days=70)
    transition_key = "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30"
    rules = {
        "oversold_rebound": (),
        "trend_pullback": (DiscoveryRule(transition_key, "trend_pullback", "test"),),
    }
    observations = [
        {
            "setup_type": "trend_pullback",
            "rule_key": transition_key,
            "vt_symbol": f"600{index:03d}.SSE",
            "trade_date": trade_date,
            "d1_close_return_pct": 1.0 if index % 2 == 0 else -1.0,
            "d1_label_status": "available",
            "transition_volume_expand_then_shrink": index % 2 == 0,
        }
        for index, trade_date in enumerate(calendar)
    ]

    report = summarize_rule_observations(observations, calendar, rule_manifest=rules)
    comparison = report["families"]["trend_pullback"]["rules"][0]["overall"][
        "transition_volume_comparison"
    ]

    assert comparison["expand_then_shrink"]["sample_count"] == 35
    assert comparison["expand_then_shrink"]["d1_mean_return_pct"] == 1.0
    assert comparison["other_volume_pattern"]["sample_count"] == 35
    assert comparison["other_volume_pattern"]["d1_mean_return_pct"] == -1.0


def test_transition_rule_splits_d1_initial_trend_outcome_by_return() -> None:
    calendar = _calendar(days=70)
    transition_key = "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30"
    rules = {
        "oversold_rebound": (),
        "trend_pullback": (DiscoveryRule(transition_key, "trend_pullback", "test"),),
    }
    observations = [
        {
            "setup_type": "trend_pullback",
            "rule_key": transition_key,
            "vt_symbol": f"600{index:03d}.SSE",
            "trade_date": trade_date,
            "d1_close_return_pct": 1.0 if index % 2 == 0 else -1.0,
            "d1_label_status": "available",
            "d1_initial_short_trend_formed": index % 2 == 0,
        }
        for index, trade_date in enumerate(calendar)
    ]

    report = summarize_rule_observations(observations, calendar, rule_manifest=rules)
    comparison = report["families"]["trend_pullback"]["rules"][0]["overall"][
        "d1_initial_short_trend_comparison"
    ]

    assert comparison["formed"]["sample_count"] == 35
    assert comparison["formed"]["d1_mean_return_pct"] == 1.0
    assert comparison["not_formed"]["sample_count"] == 35
    assert comparison["not_formed"]["d1_mean_return_pct"] == -1.0


def test_rule_report_keeps_detailed_failures_only_for_the_selected_rule() -> None:
    calendar = _calendar(days=70)
    rules = {
        "oversold_rebound": (
            DiscoveryRule("development_winner", "oversold_rebound", "test"),
            DiscoveryRule("holdout_winner", "oversold_rebound", "test"),
        ),
        "trend_pullback": (),
    }
    observations = [
        {
            "setup_type": "oversold_rebound",
            "rule_key": rule_key,
            "vt_symbol": f"000{index:03d}.SZSE",
            "trade_date": trade_date,
            "d1_close_return_pct": 2.0 if rule_key == "development_winner" else 0.1,
            "d1_label_status": "available",
        }
        for index, trade_date in enumerate(calendar)
        for rule_key in ("development_winner", "holdout_winner")
    ]

    report = summarize_rule_observations(observations, calendar, rule_manifest=rules)
    rendered = {
        row["key"]: row
        for row in report["families"]["oversold_rebound"]["rules"]
    }

    assert "full" in rendered["development_winner"]
    assert "worst_days" in rendered["development_winner"]["full"]
    assert "full" not in rendered["holdout_winner"]


def test_frozen_recent_half_year_rule_cannot_be_replaced_by_full_history_winner() -> None:
    calendar = _calendar(days=70)
    rules = {
        "oversold_rebound": (
            DiscoveryRule("frozen_recent_rule", "oversold_rebound", "test"),
            DiscoveryRule("full_history_winner", "oversold_rebound", "test"),
        ),
        "trend_pullback": (
            DiscoveryRule("frozen_trend_rule", "trend_pullback", "test"),
        ),
    }
    observations: list[dict[str, object]] = []
    for index, trade_date in enumerate(calendar):
        observations.extend(
            (
                {
                    "setup_type": "oversold_rebound",
                    "rule_key": "frozen_recent_rule",
                    "vt_symbol": f"000{index:03d}.SZSE",
                    "trade_date": trade_date,
                    "d1_close_return_pct": 0.1,
                    "d1_label_status": "available",
                },
                {
                    "setup_type": "oversold_rebound",
                    "rule_key": "full_history_winner",
                    "vt_symbol": f"600{index:03d}.SSE",
                    "trade_date": trade_date,
                    "d1_close_return_pct": 2.0,
                    "d1_label_status": "available",
                },
            )
        )

    report = summarize_rule_observations(
        observations,
        calendar,
        rule_manifest=rules,
        frozen_rule_keys={
            "oversold_rebound": "frozen_recent_rule",
            "trend_pullback": "frozen_trend_rule",
        },
    )
    selected = report["families"]["oversold_rebound"]["selected_rule"]

    assert selected["key"] == "frozen_recent_rule"
    assert selected["selection_mode"] == "frozen_recent_half_year"
    assert selected["development"]["d1_mean_return_pct"] == 0.1


def test_frozen_rule_must_belong_to_its_declared_family() -> None:
    calendar = _calendar(days=70)
    rules = {
        "oversold_rebound": (
            DiscoveryRule("oversold_rule", "oversold_rebound", "test"),
        ),
        "trend_pullback": (
            DiscoveryRule("trend_rule", "trend_pullback", "test"),
        ),
    }

    with pytest.raises(DailyFactorInputError, match="does not belong"):
        summarize_rule_observations(
            (),
            calendar,
            rule_manifest=rules,
            frozen_rule_keys={
                "oversold_rebound": "trend_rule",
                "trend_pullback": "trend_rule",
            },
        )


def test_strict_price_limit_exclusion_does_not_enter_discovery_statistics() -> None:
    calendar = _calendar()
    rules = {
        "oversold_rebound": (DiscoveryRule("rule", "oversold_rebound", "test"),),
        "trend_pullback": (),
    }
    report = summarize_rule_observations(
        (
            {
                "setup_type": "oversold_rebound",
                "rule_key": "rule",
                "vt_symbol": "000001.SZSE",
                "trade_date": calendar[0],
                "d1_close_return_pct": None,
                "d1_label_status": "label_excluded_main_board_price_limit",
            },
        ),
        calendar,
        rule_manifest=rules,
    )
    summary = report["families"]["oversold_rebound"]["rules"][0]["overall"]

    assert summary["candidate_count"] == 0
    assert summary["sample_count"] == 0
    assert summary["label_excluded_main_board_price_limit_count"] == 1


def test_exit_selection_uses_development_only() -> None:
    calendar = _calendar(days=70)
    rows = []
    for index, trade_date in enumerate(calendar):
        rows.extend(
            (
                {
                    "probe": "d3_close",
                    "trade_date": trade_date,
                    "status": "closed",
                    "return_pct": 1.0 if index < 39 else -2.0,
                },
                {
                    "probe": "d5_close",
                    "trade_date": trade_date,
                    "status": "closed",
                    "return_pct": 0.1 if index < 39 else 9.0,
                },
            )
        )

    result = select_exit_probe(rows, market_calendar=calendar)

    assert result["selected_probe"] == "d3_close"
    assert result["holdout"]["mean_return_pct"] == -2.0


def test_post_limit_up_hold_begins_after_first_strict_limit_up_close() -> None:
    entry_date = date(2025, 1, 1)
    result = evaluate_post_limit_up_hold(
        {"entry_date": entry_date, "entry_price": 10.0},
        (
            {"trade_date": entry_date + timedelta(days=1), "close_price": 11.0},
            {"trade_date": entry_date + timedelta(days=2), "close_price": 11.1},
            {"trade_date": entry_date + timedelta(days=3), "close_price": 11.3},
        ),
        holding_sessions=2,
    )

    assert result["status"] == "closed"
    assert result["first_limit_up_close_date"] == entry_date + timedelta(days=1)
    assert result["first_limit_up_close_price"] == 11.0
    assert result["exit_date"] == entry_date + timedelta(days=3)
    assert result["entry_to_exit_return_pct"] == 13.0
    assert result["post_limit_up_return_pct"] == 2.7273
    assert result["return_pct"] == 2.7273
    assert result["holding_sessions"] == 2


def test_research_answers_do_not_promote_an_unvalidated_exit() -> None:
    exit_selection = {
        "selected_probe": "d3_close",
        "qualification_gate": {"passed": False},
        "validation": {"mean_return_pct": 0.4},
        "holdout": {"mean_return_pct": -0.2},
    }
    report = {
        "status": "exploratory_complete",
        "families": {
            "oversold_rebound": {
                "selected_rule": {
                    "key": "oversold_rule",
                    "validation": {"d1_mean_return_pct": 0.4},
                    "holdout": {"d1_mean_return_pct": -0.2},
                    "qualification_gate": {"passed": False},
                    "exit_selection": exit_selection,
                    "post_limit_up_exit_selection": exit_selection,
                },
            },
            "trend_pullback": {"selected_rule": None},
        },
    }

    answers = {row["question"]: row for row in _research_answers(report)}

    assert answers["超跌反弹的收盘卖点"]["status"] == "not_supported"
    assert answers["超跌反弹的首次严格涨停后持有"]["status"] == "not_supported"


def test_post_limit_up_hold_marks_an_incomplete_search_window_unavailable() -> None:
    entry_date = date(2025, 1, 1)
    result = evaluate_post_limit_up_hold(
        {"entry_date": entry_date, "entry_price": 10.0},
        (
            {"trade_date": entry_date + timedelta(days=1), "close_price": 10.2},
            {"trade_date": entry_date + timedelta(days=2), "close_price": 10.3},
        ),
        holding_sessions=1,
    )

    assert result["status"] == "unavailable"
    assert result["exit_reason"] == "missing_limit_up_search_window"


def test_post_limit_up_hold_excludes_a_tick_rounded_10_point_1_percent_close() -> None:
    entry_date = date(2025, 1, 1)
    result = evaluate_post_limit_up_hold(
        {"entry_date": entry_date, "entry_price": 10.0},
        (
            {"trade_date": entry_date + timedelta(days=1), "close_price": 11.01},
            {"trade_date": entry_date + timedelta(days=2), "close_price": 11.1},
        ),
        holding_sessions=1,
    )

    assert result["status"] == "unavailable"
    assert result["exit_reason"] == "raw_price_limit_outlier"


def test_renderer_includes_manifest_and_raw_evidence_gate() -> None:
    markdown = render_extended_daily_factor_markdown(
        {
            "research_version": "test",
            "evidence_level": "exploratory_raw_unadjusted",
            "conclusion": "exploratory_only",
            "time_split": None,
            "families": {},
        }
    )

    assert "预登记候选规则" in markdown
    assert "不能升级为正式策略结论" in markdown
    assert "严格超过 [-10%, +10%]" in markdown


def test_renderer_marks_pre_attack_base_paths_as_observational() -> None:
    markdown = render_extended_daily_factor_markdown(
        {
            "research_version": "test",
            "evidence_level": "exploratory_raw_unadjusted",
            "conclusion": "exploratory_only",
            "time_split": None,
            "families": {},
            "score_factors": {},
            "case_score_membership": {},
            "full_history_score_gate": {},
            "research_answers": [],
            "pre_attack_base_process": {
                "feature_cutoff": "D-2",
                "candidate_count": 2,
                "label_excluded_main_board_price_limit_count": 0,
                "phase_groups": [
                    {
                        "phase": "release_retest_base",
                        "sample_count": 2,
                        "d1_mean_return_pct": 1.2,
                        "win_rate_pct": 100.0,
                        "same_day_excess": {
                            "sample_count": 2,
                            "mean_return_pct": 0.8,
                        },
                    }
                ],
            },
        }
    )

    assert "攻击前底盘过程（观察性）" in markdown
    assert "本观察表不参与规则选择、分数或实时推荐" in markdown
    assert "首段两线攻击另有冻结资格门" in markdown
    assert "release_retest_base" in markdown


def test_renderer_shows_selected_score_factor_and_personal_case_membership() -> None:
    markdown = render_extended_daily_factor_markdown(
        {
            "research_version": "test",
            "evidence_level": "exploratory_raw_unadjusted",
            "conclusion": "exploratory_only",
            "time_split": None,
            "families": {},
            "score_factors": {
                "oversold_rebound": {
                    "variants": [
                        {
                            "variant": "base",
                            "bands": [
                                {
                                    "band": "80-100",
                                    "overall": {"sample_count": 30, "d1_mean_return_pct": 1.0},
                                    "segments": {
                                        "validation": {"overall": {"d1_mean_return_pct": 0.5}},
                                        "holdout": {"overall": {"d1_mean_return_pct": 0.2}},
                                    },
                                }
                            ],
                        }
                    ],
                    "selected_score_factor": {
                        "variant": "base",
                        "band": "80-100",
                        "qualification_gate": {"passed": False},
                    },
                }
            },
            "case_score_membership": {
                "传智教育 MA10 回踩": {
                    "trade_date": "2026-07-22",
                    "scores": {"base": 80.0},
                    "score_bands": {"base": "80-100"},
                    "selected_score_factor": {"matched": True},
                }
            },
        }
    )

    assert "综合分数因子" in markdown
    assert "传智教育 MA10 回踩" in markdown
    assert "80-100" in markdown


def test_cli_declares_read_only_extended_discovery_command() -> None:
    args = build_parser().parse_args(
        [
            "daily-factor-extended-discovery",
            "--price-basis",
            "raw_unadjusted",
            "--format",
            "markdown",
        ]
    )

    assert args.command == "daily-factor-extended-discovery"
    assert args.price_basis == "raw_unadjusted"


def test_cli_accepts_a_frozen_rule_for_each_setup_type() -> None:
    args = build_parser().parse_args(
        [
            "daily-factor-extended-discovery",
            "--price-basis",
            "raw_unadjusted",
            "--frozen-rule",
            "oversold_rebound=oversold_rule",
            "--frozen-rule",
            "trend_pullback=trend_rule",
        ]
    )

    assert args.frozen_rule == [
        "oversold_rebound=oversold_rule",
        "trend_pullback=trend_rule",
    ]


def test_cli_can_skip_exit_probes_during_preliminary_factor_discovery() -> None:
    args = build_parser().parse_args(
        [
            "daily-factor-extended-discovery",
            "--price-basis",
            "raw_unadjusted",
            "--skip-exit-probes",
        ]
    )

    assert args.skip_exit_probes is True


def test_raw_extended_discovery_stays_exploratory_end_to_end() -> None:
    bars = [
        {**row, "vt_symbol": "000001.SZSE"}
        for row in _bull_support_history()
    ]
    report = run_extended_daily_factor_discovery(
        bars=bars,
        market_calendar=tuple(row["trade_date"] for row in bars),
        security_status=(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="test-input",
    )

    assert report["status"] == "exploratory_complete"
    assert report["conclusion"] == "exploratory_only"
    assert report["qualified_rules"] == []
    assert set(report["score_factors"]) == {"oversold_rebound", "trend_pullback"}
    assert "selected_score_factor" in report["score_factors"]["trend_pullback"]
    assert report["case_score_membership"]
    assert report["pre_attack_base_process"]["feature_cutoff"].startswith("D-2")


def test_raw_extended_discovery_accepts_a_sorted_dataframe_without_bulk_records() -> None:
    bars = [
        {**row, "vt_symbol": "000001.SZSE"}
        for row in _bull_support_history()
    ]

    report = run_extended_daily_factor_discovery(
        bars=pd.DataFrame(bars),
        market_calendar=tuple(row["trade_date"] for row in bars),
        security_status=(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="dataframe-input",
        include_exit_evidence=False,
    )

    assert report["status"] == "exploratory_complete"
    assert report["conclusion"] == "exploratory_only"
    assert report["selection_protocol"]["include_exit_evidence"] is False
