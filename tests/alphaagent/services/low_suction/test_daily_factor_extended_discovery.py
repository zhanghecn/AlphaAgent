from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import alphaagent.server.services.low_suction.daily_factor_extended_discovery as extended_discovery
from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    DISCOVERY_RULES,
    DiscoveryRule,
    _broad_candidate_positions,
    _has_initial_short_trend_shape,
    _is_score_candidate,
    _research_answers,
    _rule_matches,
    build_extended_daily_features,
    evaluate_post_limit_up_hold,
    process_rule_predicates,
    render_extended_daily_factor_markdown,
    run_extended_daily_factor_discovery,
    score_extended_factor,
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


def _bear_then_m10_cross_history() -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    closes = [100 - index * 0.4 for index in range(64)] + [74.8, 76.0, 78.5, 82.0, 86.0, 89.0]
    return [
        _bar(start + timedelta(days=index), close, volume=2_000 - index * 5)
        for index, close in enumerate(closes)
    ]


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
    assert trend[0].rule_key == "v4_trend_quiet_pullback"


def _bull_aligned_with_oversold_rules_history() -> list[dict[str, object]]:
    """多头排列已成立但仍落在超跌过程窗口内的边界形态。

    取自石化油服 600871 @2026-08-04 的真实日线收盘价：MA10>MA20>MA30 三线多头已 6 天，
    但 MA10 上穿 MA30 发生在 15 日窗口内 → 同时匹配 v3 超跌落地规则。
    用于复现"多头票混进超跌族"假阳性：互斥门禁前 scan 同时产 oversold + trend 候选。
    """
    start = date(2025, 1, 1)
    closes = [
        2.83, 2.82, 2.90, 2.81, 2.71, 2.70, 2.65, 2.69, 2.71, 2.67, 2.72, 2.65, 2.68, 2.67,
        2.70, 2.72, 2.63, 2.58, 2.66, 2.64, 2.59, 2.61, 2.53, 2.54, 2.62, 2.60, 2.58, 2.40,
        2.44, 2.43, 2.41, 2.33, 2.36, 2.32, 2.38, 2.36, 2.40, 2.32, 2.31, 2.31, 2.24, 2.20,
        2.22, 2.24, 2.25, 2.19, 2.17, 2.14, 2.16, 2.14, 2.10, 2.07, 2.03, 2.05, 2.03, 2.08,
        2.07, 2.08, 2.07, 2.01, 2.06, 2.06, 2.10, 2.05, 2.17, 2.08, 2.05, 2.04, 2.17, 2.13,
        2.25, 2.29, 2.17, 2.17, 2.16, 2.20, 2.22, 2.23, 2.26, 2.24,
    ]
    return [
        _bar(start + timedelta(days=index), close, volume=1_000 + index)
        for index, close in enumerate(closes)
    ]


def test_scan_rejects_bull_aligned_from_oversold() -> None:
    """超跌/趋势互斥：多头排列(MA10>MA20>MA30)成立的票不再纳入超跌族。

    超跌反弹语义 = 空头→多头过渡期；多头一旦成立就归趋势族。这防止石化油服类
    "多头走出来仍落在 ma10_crossed_ma30_within_15d 窗口内"的票混进超跌族拿满分。
    """
    bars = [
        {**row, "vt_symbol": "600871.SSE", "turnover_rate": 2.0}
        for row in _bull_aligned_with_oversold_rules_history()
    ]
    calendar = [row["trade_date"] for row in bars]
    candidates = scan_low_suction_candidates(bars, calendar, [], target_dates={calendar[-1]})

    oversold = [candidate for candidate in candidates if candidate.setup_type == "oversold_rebound"]
    trend = [candidate for candidate in candidates if candidate.setup_type == "trend_pullback"]
    # 互斥门禁：多头票不进超跌族
    assert oversold == []
    # 但仍正常作为趋势回踩候选
    assert len(trend) >= 1


def _m10_far_above_ma30_oversold_history() -> list[dict[str, object]]:
    """M10 已远穿 M30（上穿过程结束）但 low 仍贴 M10 的边界形态。

    取自中闽能源 600163 @2026-08-03：空头后一根大阳 → 均线纠缠横盘，M10=5.29 已远在
    M30=5.10 上方 +3.67%（过程结束），low 仍贴 M10。不是"准备上穿处的 M10 回踩"，
    不该作超跌低吸。复现 v3_staged 规则因只看 ma20<ma30、漏看 M10vsM30 的误纳。
    """
    start = date(2025, 1, 1)
    closes = [
        6.17, 5.94, 5.95, 6.24, 6.15, 6.08, 6.11, 6.04, 6.13, 6.31, 6.35, 6.68, 6.34, 6.19,
        6.25, 6.17, 6.17, 6.38, 6.50, 6.47, 6.63, 6.74, 6.93, 6.96, 6.67, 6.80, 7.04, 6.53,
        6.35, 6.32, 6.54, 6.53, 6.75, 6.95, 6.92, 7.14, 6.91, 7.27, 7.03, 6.54, 6.01, 6.04,
        5.61, 5.68, 6.23, 5.98, 6.01, 5.85, 5.63, 5.54, 5.48, 5.25, 5.14, 4.99, 5.06, 5.15,
        5.16, 5.13, 5.13, 5.06, 4.89, 4.77, 4.72, 4.81, 4.73, 4.83, 4.90, 4.86, 4.90, 5.19,
        5.15, 5.28, 5.39, 5.09, 5.30, 5.26, 5.34, 5.33, 5.33, 5.41,
    ]
    return [
        _bar(start + timedelta(days=index), close, volume=1_000 + index)
        for index, close in enumerate(closes)
    ]


def test_scan_rejects_m10_far_above_ma30_from_oversold() -> None:
    """超跌低吸位置必须在「M10 准备上穿/回贴 M30」的地方。

    M10 已远穿 M30（过程结束）= 不是"准备上穿处的回踩"，不该作超跌低吸。
    防止中闽能源类「空头后均线纠缠、M10 早穿完 M30、low 贴 M10」的横盘票混进超跌族。
    """
    bars = [
        {**row, "vt_symbol": "600163.SSE", "turnover_rate": 2.0}
        for row in _m10_far_above_ma30_oversold_history()
    ]
    calendar = [row["trade_date"] for row in bars]
    candidates = scan_low_suction_candidates(bars, calendar, [], target_dates={calendar[-1]})

    oversold = [candidate for candidate in candidates if candidate.setup_type == "oversold_rebound"]
    assert oversold == []


def _low_above_ma10_fake_pullback_history() -> list[dict[str, object]]:
    """low 没真回踩到 M10（low 在 M10 上方 +1.4%）却靠 _support_low_touch 的 +1.5% 宽上限
    被当"贴 M10"的假回踩。取自 600743 真实 OHLC @2026-08-04：low=2.15，M10=2.12，
    low_to_ma10=+1.46%。主人研究票 low 到 M10 全部 ≤+0.59%（真触及/跌破），这是 A 类冲高型假回踩。"""
    start = date(2025, 1, 1)
    ohlc = [
        (2.20, 2.41, 2.09, 2.41), (2.59, 2.65, 2.52, 2.65), (2.92, 2.92, 2.81, 2.92), (3.21, 3.21, 3.15, 3.21),
        (3.53, 3.53, 2.89, 2.89), (2.85, 2.95, 2.62, 2.65), (2.56, 2.79, 2.56, 2.69), (2.55, 2.66, 2.42, 2.59),
        (2.51, 2.82, 2.51, 2.60), (2.53, 2.62, 2.44, 2.47), (2.47, 2.50, 2.40, 2.50), (2.47, 2.49, 2.38, 2.38),
        (2.35, 2.35, 2.27, 2.33), (2.35, 2.36, 2.28, 2.31), (2.30, 2.42, 2.30, 2.40), (2.38, 2.53, 2.36, 2.47),
        (2.46, 2.57, 2.43, 2.54), (2.54, 2.60, 2.50, 2.60), (2.57, 2.86, 2.55, 2.78), (2.76, 2.85, 2.67, 2.69),
        (2.69, 2.72, 2.63, 2.71), (2.68, 2.72, 2.61, 2.67), (2.70, 2.71, 2.58, 2.61), (2.59, 2.85, 2.58, 2.69),
        (2.66, 2.71, 2.52, 2.69), (2.68, 2.72, 2.63, 2.68), (2.63, 2.67, 2.61, 2.63), (2.61, 2.63, 2.40, 2.44),
        (2.45, 2.47, 2.42, 2.46), (2.46, 2.55, 2.45, 2.49), (2.51, 2.55, 2.37, 2.40), (2.39, 2.40, 2.28, 2.32),
        (2.31, 2.49, 2.29, 2.45), (2.44, 2.65, 2.42, 2.46), (2.40, 2.71, 2.33, 2.58), (2.55, 2.59, 2.42, 2.53),
        (2.48, 2.61, 2.41, 2.57), (2.55, 2.83, 2.50, 2.57), (2.41, 2.59, 2.41, 2.49), (2.41, 2.60, 2.40, 2.47),
        (2.47, 2.48, 2.30, 2.37), (2.37, 2.37, 2.27, 2.31), (2.29, 2.32, 2.22, 2.24), (2.24, 2.27, 2.22, 2.25),
        (2.25, 2.29, 2.16, 2.17), (2.15, 2.17, 2.09, 2.11), (2.11, 2.12, 2.05, 2.10), (2.10, 2.23, 2.07, 2.12),
        (2.10, 2.22, 2.09, 2.21), (2.19, 2.43, 2.18, 2.43), (2.48, 2.55, 2.28, 2.34), (2.37, 2.39, 2.22, 2.31),
        (2.29, 2.30, 2.18, 2.18), (2.21, 2.30, 2.10, 2.15), (2.14, 2.18, 2.11, 2.16), (2.20, 2.24, 2.15, 2.20),
        (2.20, 2.27, 2.13, 2.14), (2.14, 2.21, 2.13, 2.18), (2.17, 2.19, 2.12, 2.14), (2.15, 2.16, 2.06, 2.08),
        (2.07, 2.10, 2.03, 2.06), (2.06, 2.12, 2.04, 2.10), (2.08, 2.21, 2.06, 2.14), (2.14, 2.16, 2.02, 2.04),
        (2.03, 2.08, 2.00, 2.08), (2.07, 2.14, 2.05, 2.09), (2.08, 2.12, 2.06, 2.08), (2.08, 2.10, 1.98, 2.01),
        (2.02, 2.05, 1.97, 1.98), (1.99, 1.99, 1.88, 1.96), (1.94, 1.98, 1.93, 1.97), (1.96, 2.05, 1.95, 2.04),
        (2.04, 2.15, 2.02, 2.05), (2.02, 2.17, 2.02, 2.13), (2.11, 2.26, 2.11, 2.18), (2.17, 2.19, 2.14, 2.17),
        (2.16, 2.19, 2.12, 2.14), (2.14, 2.19, 2.13, 2.15), (2.16, 2.19, 2.15, 2.18), (2.19, 2.20, 2.15, 2.18),
    ]
    return [
        _bar(start + timedelta(days=index), close, open_price=open_price, high_price=high_price, low_price=low_price)
        for index, (open_price, high_price, low_price, close) in enumerate(ohlc)
    ]


def test_scan_rejects_low_above_ma10_fake_pullback() -> None:
    """超跌低吸位置要求 low 真回踩 M10（触及/跌破），不是靠宽阈值"擦"到 M10 上方。

    low 在 M10 上方 +1.4%（没真回踩）的 A 类冲高型假回踩不该作超跌低吸。
    主人研究票 low 到 M10 全部 ≤+0.59%。
    """
    bars = [
        {**row, "vt_symbol": "600743.SSE", "turnover_rate": 2.0}
        for row in _low_above_ma10_fake_pullback_history()
    ]
    calendar = [row["trade_date"] for row in bars]
    candidates = scan_low_suction_candidates(bars, calendar, [], target_dates={calendar[-1]})

    oversold = [candidate for candidate in candidates if candidate.setup_type == "oversold_rebound"]
    assert oversold == []


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


def test_manifest_keeps_core_and_volume_sibling_rules() -> None:
    names = {rule.key for rule in DISCOVERY_RULES["oversold_rebound"]}

    assert "m10_m20_near_or_crossed_down" in names
    assert "m10_m20_near_or_crossed_down_volume_shrink" in names


def test_discovery_manifest_rule_keys_are_unique_per_family() -> None:
    for rules in DISCOVERY_RULES.values():
        keys = [rule.key for rule in rules]

        assert len(keys) == len(set(keys))


def test_manifest_pairs_every_oversold_core_rule_with_expand_and_shrink_volume() -> None:
    rules = {rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]}
    core_keys = {
        "m10_m20_near_or_crossed_down",
        "m10_m30_near_or_crossed_down",
        "m20_m30_near_or_crossed_down",
        "staged_m10_first_down",
        "m10_dual_cross_before_m20_m30_down",
    }

    for core_key in core_keys:
        shrink = rules[f"{core_key}_volume_shrink"]
        expand = rules[f"{core_key}_volume_expand"]

        assert shrink.core_rule_key == core_key
        assert shrink.volume_shape == "staircase_shrink"
        assert expand.core_rule_key == core_key
        assert expand.volume_shape == "staircase_expand"


def test_manifest_includes_source_process_probes_and_volume_siblings() -> None:
    rules = {rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]}
    trend_keys = {rule.key for rule in DISCOVERY_RULES["trend_pullback"]}

    assert "m20_m30_convergence_after_m10_cross_pullback" not in rules
    assert "m20_m30_convergence_after_long_bear_m10_cross_pullback" not in rules
    assert "ma10_ma30_converging_after_staged_cross_volume_shrink" in rules
    assert "ma10_ma20_contact_pre_cross_positive_volume_expand" in rules
    assert "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30" not in rules
    assert "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30" in trend_keys
    assert "oversold_to_trend_pre_cross_ma10_ma20_contact" in trend_keys
    assert "m10_m30_contact_after_m10_cross_aggressive_pullback" in rules
    assert "ma10_low_touch_regular_ma5_down" in trend_keys
    assert "ma5_low_touch_broad_down" in trend_keys
    assert "ma10_low_retest_during_staged_cross" in rules
    assert "m5_m10_joint_attack_before_ma20_cross" in rules
    assert "ma10_low_retest_after_long_bear_staged_cross" in rules
    assert "m5_m10_joint_attack_after_long_bear" in rules
    assert "m10_m30_contact_after_long_bear_aggressive_pullback" in rules
    assert "ma5_low_touch_after_trend_rebuild" in trend_keys
    assert "ma5_low_touch_any_candle" in trend_keys
    assert "ma5_low_touch_early_trend_any_candle" in trend_keys
    assert "ma10_low_touch_early_trend_regular_ma5_down" in trend_keys


def test_volume_siblings_require_their_declared_volume_shape() -> None:
    rules = {rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]}
    features = {
        "oversold_discovery_eligible": True,
        "price_state": "weak_or_down",
        "ma10_ma20_near_or_recent_cross": True,
        "volume_shape": "staircase_shrink",
    }

    shrink = rules["m10_m20_near_or_crossed_down_volume_shrink"]
    expand = rules["m10_m20_near_or_crossed_down_volume_expand"]

    assert _rule_matches(shrink, features) is True
    assert _rule_matches(expand, features) is False
    assert _rule_matches(expand, {**features, "volume_shape": "staircase_expand"}) is True


def test_source_process_rules_keep_personal_paths_and_support_branches_separate() -> None:
    oversold_rules = {rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]}
    trend_rules = {rule.key: rule for rule in DISCOVERY_RULES["trend_pullback"]}
    yiming_pre_cross_features = {
        "long_bear_alignment": True,
        "ma10_below_ma20": True,
        "ma10_ma20_contact": True,
        "ma10_ma20_gap_narrowing": True,
        "positive_candle": True,
        "last_volume_expanded": True,
    }
    yiming_trend_transition_features = {
        "long_bear_alignment": True,
        "ma10_dual_cross_within_7d": True,
        "ma10_above_ma20_and_ma30": True,
        "transition_ma20_ma30_tight_contact": True,
        "ma10_ma20_slopes_up": True,
        "post_cross_pullback": True,
        "small_positive_candle": True,
    }
    retest_features = {
        "oversold_process_eligible": True,
        "ma10_crossed_ma20_within_15d": True,
        "ma10_ma30_contact": True,
        "aggressive_pullback": True,
        "volume_shape": "staircase_expand",
    }
    ma10_support_features = {
        "trend_discovery_eligible": True,
        "trend_stable_bull": True,
        "price_state": "weak_or_down",
        "ma5_regular": True,
        "ma10_low_touch": True,
    }
    broad_ma5_features = {
        "trend_discovery_eligible": True,
        "trend_stable_bull": True,
        "price_state": "weak_or_down",
        "ma5_regular": True,
        "ma5_low_touch_broad": True,
    }
    staged_retest_features = {
        "oversold_process_eligible": True,
        "staged_m10_first": True,
        "ma10_low_touch": True,
    }
    joint_attack_features = {
        "oversold_process_eligible": True,
        "m5_m10_joint_attack_ready": True,
    }
    rebuilt_trend_features = {
        "trend_discovery_eligible": True,
        "trend_stable_bull": True,
        "trend_rebuilt_recently": True,
        "ma5_regular": True,
        "ma5_low_touch_broad": True,
    }
    any_candle_ma5_features = {
        "trend_bull_alignment": True,
        "trend_all_slopes_up": True,
        "ma5_regular": True,
        "ma5_low_touch": True,
        "price_state": "large_green",
    }

    assert _rule_matches(
        oversold_rules["ma10_ma20_contact_pre_cross_positive_volume_expand"],
        yiming_pre_cross_features,
    ) is True
    assert _rule_matches(
        trend_rules["oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30"],
        yiming_trend_transition_features,
    ) is True
    assert _rule_matches(
        oversold_rules["m10_m30_contact_after_m10_cross_aggressive_pullback_volume_expand"],
        retest_features,
    ) is True
    assert _rule_matches(
        trend_rules["ma10_low_touch_regular_ma5_down"], ma10_support_features
    ) is True
    assert _rule_matches(
        trend_rules["ma5_low_touch_broad_down"], broad_ma5_features
    ) is True
    assert _rule_matches(
        oversold_rules["ma10_low_retest_during_staged_cross"],
        staged_retest_features,
    ) is True
    assert _rule_matches(
        oversold_rules["m5_m10_joint_attack_before_ma20_cross"],
        joint_attack_features,
    ) is True
    assert _rule_matches(
        trend_rules["ma5_low_touch_after_trend_rebuild"],
        rebuilt_trend_features,
    ) is True
    assert _rule_matches(
        trend_rules["ma5_low_touch_any_candle"],
        any_candle_ma5_features,
    ) is True


def test_source_stage_rules_require_long_bear_or_early_trend_alignment() -> None:
    oversold_rules = {rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]}
    trend_rules = {rule.key: rule for rule in DISCOVERY_RULES["trend_pullback"]}
    long_bear_staged = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "staged_m10_first": True,
        "ma10_low_touch": True,
    }
    early_ma5 = {
        "early_trend_alignment": True,
        "trend_all_slopes_up": True,
        "ma5_regular": True,
        "ma5_low_touch": True,
    }
    early_ma10 = {
        "early_trend_alignment": True,
        "trend_discovery_eligible": True,
        "price_state": "weak_or_down",
        "ma5_regular": True,
        "ma10_low_touch": True,
    }

    assert _rule_matches(
        oversold_rules["ma10_low_retest_after_long_bear_staged_cross"],
        long_bear_staged,
    ) is True
    assert _rule_matches(
        oversold_rules["ma10_low_retest_after_long_bear_staged_cross"],
        {**long_bear_staged, "long_bear_alignment": False},
    ) is False
    assert _rule_matches(
        trend_rules["ma5_low_touch_early_trend_any_candle"], early_ma5
    ) is True
    assert _rule_matches(
        trend_rules["ma5_low_touch_early_trend_any_candle"],
        {**early_ma5, "early_trend_alignment": False},
    ) is False
    assert _rule_matches(
        trend_rules["ma10_low_touch_early_trend_regular_ma5_down"], early_ma10
    ) is True


def test_explicit_personal_case_rules_expose_their_causal_requirements() -> None:
    oversold_rules = {
        rule.key: rule for rule in DISCOVERY_RULES["oversold_rebound"]
    }
    trend_rules = {
        rule.key: rule for rule in DISCOVERY_RULES["trend_pullback"]
    }
    staged_retest = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "staged_m10_first": True,
        "ma10_low_touch": True,
        "ma10_ma30_gap_converging": True,
        "volume_shape": "staircase_shrink",
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
    joint_attack_with_last_volume_expand = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "m5_m10_joint_attack_ready": True,
        "last_volume_expanded": True,
    }
    chizhi_ma30_convergence = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "staged_m10_first": True,
        "ma10_ma30_gap_converging": True,
        "volume_shape": "staircase_shrink",
    }
    yiming_pre_cross = {
        "long_bear_alignment": True,
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

    staged_key = "ma10_low_retest_staged_m30_converging_volume_shrink"
    retest_key = "ma10_ma30_retest_after_actual_cross_two_leg_volume"
    joint_attack_key = "m5_m10_joint_attack_before_ma20_cross_last_volume_expand"
    chizhi_ma30_key = "ma10_ma30_converging_after_staged_cross_volume_shrink"
    yiming_pre_cross_key = "ma10_ma20_contact_pre_cross_positive_volume_expand"
    yiming_transition_key = "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30"
    fallback_key = "ma10_low_touch_after_ma5_extension"
    assert staged_key in oversold_rules
    assert retest_key in oversold_rules
    assert joint_attack_key in oversold_rules
    assert chizhi_ma30_key in oversold_rules
    assert yiming_pre_cross_key in oversold_rules
    assert yiming_transition_key in trend_rules
    assert fallback_key in trend_rules
    assert process_rule_predicates(staged_key, staged_retest) == {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "staged_m10_first": True,
        "ma10_low_touch": True,
        "ma10_ma30_gap_converging": True,
        "volume_shape_staircase_shrink": True,
    }
    assert _rule_matches(oversold_rules[staged_key], staged_retest) is True
    assert _rule_matches(oversold_rules[staged_key], {**staged_retest, "ma10_ma30_gap_converging": False}) is False
    assert _rule_matches(oversold_rules[retest_key], ma10_retest_after_cross) is True
    assert _rule_matches(
        oversold_rules[retest_key],
        {**ma10_retest_after_cross, "ma10_was_above_ma30_within_15d": False},
    ) is False
    assert _rule_matches(
        oversold_rules[joint_attack_key], joint_attack_with_last_volume_expand
    ) is True
    assert _rule_matches(
        oversold_rules[joint_attack_key],
        {**joint_attack_with_last_volume_expand, "last_volume_expanded": False},
    ) is False
    assert _rule_matches(oversold_rules[chizhi_ma30_key], chizhi_ma30_convergence) is True
    assert _rule_matches(
        oversold_rules[chizhi_ma30_key],
        {**chizhi_ma30_convergence, "ma10_ma30_gap_converging": False},
    ) is False
    assert _rule_matches(oversold_rules[yiming_pre_cross_key], yiming_pre_cross) is True
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


def test_explicit_case_phase_features_are_causal_at_the_decision_cutoff() -> None:
    history = _bear_then_m10_dual_cross_history()
    cutoff = history[-1]["trade_date"]

    expected = build_extended_daily_features(history, as_of_date=cutoff)
    actual = build_extended_daily_features(
        [*history, _bar(cutoff + timedelta(days=1), 200.0, volume=99_999.0)],
        as_of_date=cutoff,
    )

    for key in (
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


def test_extended_factor_score_keeps_volume_as_an_oversold_addition() -> None:
    oversold_features = {
        "long_bear_alignment": True,
        "oversold_process_eligible": True,
        "staged_m10_first": True,
        "m5_m10_joint_attack_ready": True,
        "ma10_ma30_gap_converging": True,
        "ma20_ma30_contact": True,
        "ma10_low_touch": True,
        "post_cross_pullback": True,
        "daily_return_pct": -1.0,
        "volume_shape": "staircase_shrink",
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
    assert len(history) - 1 in _broad_candidate_positions(history)


def test_pre_cross_transition_remains_reportable_but_not_a_scored_trend_candidate() -> None:
    trend_rules = {rule.key: rule for rule in DISCOVERY_RULES["trend_pullback"]}
    features = {
        "long_bear_alignment": True,
        "ma10_below_ma20": True,
        "ma10_ma20_contact": True,
        "ma10_ma20_gap_narrowing": True,
        "positive_candle": True,
        "trend_transition_preparation_eligible": True,
        "trend_transition_eligible": False,
        "trend_bull_alignment": False,
        "trend_all_slopes_up": False,
        "trend_discovery_eligible": False,
        "ma5_regular": False,
        "ma5_low_touch": False,
        "ma10_low_touch": False,
        "daily_return_pct": 3.0581,
    }

    rule = trend_rules["oversold_to_trend_pre_cross_ma10_ma20_contact"]
    assert _rule_matches(rule, features) is True
    assert _is_score_candidate(features, "trend_pullback") is False


def test_broad_candidate_prescreen_only_evaluates_requested_signal_dates() -> None:
    history = _oversold_to_trend_history_without_regular_ma5()
    last_position = len(history) - 1
    last_date = history[last_position]["trade_date"]
    previous_date = history[last_position - 1]["trade_date"]

    assert _broad_candidate_positions(
        history,
        candidate_dates={last_date},
    ) == (last_position,)
    assert last_position not in _broad_candidate_positions(
        history,
        candidate_dates={previous_date},
    )


def test_broad_candidate_prescreen_keeps_pre_cross_transition_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A MA10/20 preparation point must not be lost before rule matching."""

    history = [
        _bar(
            date(2025, 1, 1) + timedelta(days=index),
            100.5 if index == 14 else 100.0,
            open_price=100.0 if index == 14 else 100.0,
        )
        for index in range(15)
    ]

    def fake_moving_average_series(
        closes: list[float],
        window: int,
    ) -> list[float | None]:
        values_by_window = {
            5: [100.0] * 15,
            10: [98.0] * 11 + [98.8, 99.0, 99.3, 99.7],
            20: [100.0] * 15,
            30: [110.0] * 15,
            60: [120.0] * 15,
        }
        return values_by_window[window][: len(closes)]

    monkeypatch.setattr(
        extended_discovery,
        "_moving_average_series",
        fake_moving_average_series,
    )

    last_position = len(history) - 1
    assert _broad_candidate_positions(
        history,
        candidate_dates={history[-1]["trade_date"]},
    ) == (last_position,)


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


def test_research_answers_do_not_promote_unvalidated_exit_or_volume_delta() -> None:
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
                "volume_incremental_deltas": [
                    {
                        "segments": {
                            "holdout": {"d1_mean_delta_pct": 0.1},
                        }
                    }
                ],
            },
            "trend_pullback": {"selected_rule": None},
        },
    }

    answers = {row["question"]: row for row in _research_answers(report)}

    assert answers["成交量附加因子何时有增量"]["status"] == "exploratory_observation"
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
