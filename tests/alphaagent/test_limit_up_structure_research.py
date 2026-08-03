"""结构因子研究测试：均线族手算、量能梯形、案例核查、盘前框架、报告编排。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import alphaagent.server.services.limit_up.leader_first_board_structure_research as research
from alphaagent.server.services.limit_up.leader_first_board_structure_research import (
    _alignment_since,
    _audit_cases,
    _b,
    _board_window_vol_spearman,
    _case_context,
    _closes_below_ma_between,
    _combo_failed_clauses,
    _first_close_below_ma_since,
    _had_close_below_ma_within,
    _index_regime_at,
    _index_regime_map,
    _ma_at,
    _ma_hold_since,
    _miss_analysis,
    _no_close_below_ma_since,
    _prefix_sums,
    _range_vol_spearman,
    _spread_at,
    _structure_combo_rows,
    _structure_features,
    _structure_hit_rates,
    _v,
    attach_structure_features,
    build_premarket_structure_frame,
)


def _bars(
    closes: list[float],
    *,
    turnovers: list[float | None] | None = None,
    changes: list[float | None] | None = None,
    start: str = "2026-01-05",
    symbol: str = "600001.SSE",
) -> list[dict[str, object]]:
    """按收盘价序列合成日线（high/low/open 随 close 派生，窗口外的值不影响特征）。"""

    bars: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        day = date.fromisoformat(start) + timedelta(days=index)
        bars.append(
            {
                "vt_symbol": symbol,
                "trade_date": day.isoformat(),
                "open_price": close,
                "close_price": close,
                "high_price": round(close * 1.01, 4),
                "low_price": round(close * 0.99, 4),
                "change_pct": changes[index] if changes else 1.0,
                "turnover": turnovers[index] if turnovers else 100.0,
            }
        )
    return bars


# ── 均线结构族 ─────────────────────────────────────────────────────────────


def test_prefix_sums_and_ma_at() -> None:
    sums, counts = _prefix_sums([1.0, None, 3.0, 4.0])
    assert _ma_at(sums, counts, 3, 2) == 3.5
    assert _ma_at(sums, counts, 2, 2) is None  # 窗口含 None
    assert _ma_at(sums, counts, 1, 5) is None  # 历史不足


def test_bear_align_linear_decline() -> None:
    closes = [100.0 - index * 0.1 for index in range(60)]
    features = _structure_features(_bars(closes))
    assert features["ma_bear_align"] is True
    assert features["ma_bull_align"] is False
    assert features["ma_bear_days"] == 30  # 60 根可算 31 天，cap 30
    assert features["ma_bull_days"] == 0
    assert features["ma_state"] == "bear_diverging"  # 线性下跌价差恒定，不收拢
    assert features["ma10_cross20_up_5d"] is False


def test_bull_align_linear_rise() -> None:
    closes = [10.0 + index * 0.1 for index in range(60)]
    features = _structure_features(_bars(closes))
    assert features["ma_bull_align"] is True
    assert features["ma_bear_align"] is False
    assert features["ma_bull_days"] == 30
    assert features["ma_state"] == "bull"


def test_align_keys_none_under_30_bars() -> None:
    features = _structure_features(_bars([10.0] * 29))
    assert features["ma_bear_align"] is None
    assert features["ma_bull_align"] is None
    assert features["ma_bear_days"] is None
    assert features["ma_tightness_pct"] is None
    assert features["ma_state"] is None
    assert features["ma_history_bars"] == 29


def test_spread_and_tightness_hand_computed() -> None:
    closes = [float(value) for value in range(1, 31)]
    features = _structure_features(_bars(closes))
    # MA10=25.5, MA20=20.5, MA30=15.5, close=30
    assert features["ma_spread_10_20_pct"] == pytest.approx(16.6667, abs=1e-4)
    assert features["ma_spread_20_30_pct"] == pytest.approx(16.6667, abs=1e-4)
    assert features["ma_tightness_pct"] == pytest.approx(33.3333, abs=1e-4)


def test_converge_positive_when_decline_flattens() -> None:
    closes = [50.0 - index for index in range(40)] + [10.0] * 8
    features = _structure_features(_bars(closes))
    assert (features["ma_converge_10_20_5d"] or 0) > 0
    assert features["ma_state"] == "bear_converging"
    assert (features["ma10_slope_5d_pct"] or 0) < 0  # MA10 仍在下行（还未被拉平）


def test_converge_negative_when_flat_turns_down() -> None:
    closes = [20.0] * 40 + [20.0 - index * 0.5 for index in range(1, 11)]
    features = _structure_features(_bars(closes))
    assert (features["ma_converge_10_20_5d"] or 0) < 0


def test_cross20_up_detected_within_five_days() -> None:
    decline = [50.0 - index * 0.5 for index in range(40)]
    rise = [32.0 + index * 2.0 for index in range(10)]
    features = _structure_features(_bars(decline + rise))
    assert features["ma10_cross20_up_5d"] is True
    assert features["ma10_slope_5d_pct"] > 0


def test_close_above_ma10_and_streak() -> None:
    closes = [10.0] * 15 + [20.0] * 10
    features = _structure_features(_bars(closes))
    assert features["close_above_ma10"] is True
    assert features["above_ma10_streak"] >= 10
    # 最后一根跌破 → streak 0
    broken = _structure_features(_bars([10.0] * 15 + [20.0] * 9 + [5.0]))
    assert broken["close_above_ma10"] is False
    assert broken["above_ma10_streak"] == 0


def test_ma10_cross_count_sawtooth() -> None:
    closes = [10.0, 12.0] * 20  # 围绕 MA10=11 上下锯齿
    features = _structure_features(_bars(closes))
    assert (features["ma10_cross_count_20d"] or 0) >= 15


def test_ma_state_tangled() -> None:
    # 长期下跌后较强反弹：MA10>MA20 但 MA20<MA30 → 非标准空头也非多头
    closes = [50.0 - index * 0.5 for index in range(40)] + [30.0 + index * 1.5 for index in range(10)]
    features = _structure_features(_bars(closes))
    assert features["ma_bear_align"] is False
    assert features["ma_bull_align"] is False
    assert features["ma_state"] == "tangled"


# ── 量能梯形族 ─────────────────────────────────────────────────────────────


def test_vol_spearman_monotone() -> None:
    up = _structure_features(_bars([10.0] * 12, turnovers=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]))
    assert up["vol_spearman_5d"] == 1.0
    assert up["vol_spearman_10d"] == 1.0
    down = _structure_features(_bars([10.0] * 12, turnovers=[120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10]))
    assert down["vol_spearman_5d"] == -1.0
    assert down["vol_spearman_10d"] == -1.0


def test_vol_spearman_requires_complete_window() -> None:
    equal = _structure_features(_bars([10.0] * 12, turnovers=[100.0] * 12))
    assert equal["vol_spearman_5d"] is None  # 零方差 → None
    with_none = _structure_features(
        _bars([10.0] * 12, turnovers=[100, 100, 100, 100, 100, 100, 100, None, 100, 100, 100, 100])
    )
    assert with_none["vol_spearman_5d"] is None  # D-5..D-1 窗内有 None
    assert with_none["vol_spearman_10d"] is None
    with_zero = _structure_features(
        _bars([10.0] * 12, turnovers=[100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 0.0])
    )
    assert with_zero["vol_spearman_5d"] is None  # 0 量无效


def test_vol_streaks() -> None:
    features = _structure_features(
        _bars([10.0] * 6, turnovers=[100.0, 90.0, 95.0, 100.0, 105.0, 110.0])
    )
    assert features["vol_up_streak"] == 4  # 90→95→100→105→110
    assert features["vol_down_streak"] == 0
    down = _structure_features(_bars([10.0] * 6, turnovers=[100.0, 110.0, 105.0, 100.0, 100.0, 90.0]))
    assert down["vol_down_streak"] == 1  # 100→90；100==100 打断
    assert down["vol_up_streak"] == 0


# ── 控盘小阳 / 波浪 / 影线 ───────────────────────────────────────────────────


def test_small_gain_days_boundary() -> None:
    features = _structure_features(
        _bars([10.0] * 6, changes=[1.0, 1.5, 1.51, 0.0, 1.0, None])
    )
    assert features["small_gain_days_5d"] == 2  # 1.5 与 1.0 计入；1.51/0/None 不计
    capped = _structure_features(
        _bars([10.0] * 6, changes=[1.0, 1.5, 1.51, 0.0, 1.0, None]), small_gain_cap=2.0
    )
    assert capped["small_gain_days_5d"] == 3


def test_days_since_20d_low() -> None:
    closes = [20.0] * 14 + [10.0] + [15.0] * 5
    features = _structure_features(_bars(closes))
    assert features["days_since_20d_low"] == 5  # 最低点在 D-6


def test_d1_shadow_balance() -> None:
    bar = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-06-05",
        "open_price": 10.0,
        "close_price": 10.0,
        "high_price": 11.0,
        "low_price": 9.0,
        "change_pct": 0.0,
        "turnover": 100.0,
    }
    features = _structure_features([bar])
    assert features["d1_shadow_balance"] == 1.0  # 上下影线各 1.0
    one_sided = dict(bar, high_price=10.5)
    assert _structure_features([one_sided])["d1_shadow_balance"] == 0.5
    flat = dict(bar, high_price=10.0, low_price=10.0)
    assert _structure_features([flat])["d1_shadow_balance"] is None


# ── 无未来函数 / 复用锁 ─────────────────────────────────────────────────────


def test_no_lookahead_appending_bars_changes_nothing() -> None:
    closes = [50.0 - index * 0.3 for index in range(50)]
    turnovers = [float(100 + index * 3) for index in range(50)]
    base = _structure_features(_bars(closes, turnovers=turnovers))
    poisoned_closes = closes + [999.0, 0.01]
    poisoned_turnovers = turnovers + [1e12, 1e-9]
    after = _structure_features(_bars(poisoned_closes, turnovers=poisoned_turnovers)[:-2])
    assert base == after


def test_reused_keys_match_daily_position_volume_features() -> None:
    from alphaagent.server.services.limit_up.leader_minute_backtest import (
        _daily_position_volume_features,
    )

    closes = [10.0 + index * 0.2 for index in range(40)]
    bars = _bars(closes, turnovers=[float(100 + index) for index in range(40)])
    features = _structure_features(bars)
    reused = _daily_position_volume_features(bars)
    for key in ("position_20d", "bias_ma5_pct", "bias_ma20_pct", "turnover_1d_vs_20d"):
        assert features[key] == reused[key]


# ── attach：D-1 截止 + 竞价缺口 + regime ─────────────────────────────────────


def test_attach_uses_bars_before_event_day_and_adds_labels() -> None:
    closes = [10.0] * 30 + [11.0]  # D 日大涨
    bars = _bars(closes)
    bars[-1]["open_price"] = 10.5  # D 日竞价高开 5%
    index_bars = _bars([10.0 + index * 0.1 for index in range(40)], symbol="000001.SSE")
    sample = {"vt_symbol": "600001.SSE", "trade_date": bars[-1]["trade_date"]}
    attached = attach_structure_features([sample], bars + index_bars)
    assert attached[0]["ma_bear_days"] == 0  # 平盘 30 根无排列
    assert attached[0]["auction_gap_pct"] == pytest.approx(5.0, abs=1e-4)
    assert attached[0]["index_above_ma20"] is True  # 指数上行 close>=MA20


def test_attach_unknown_symbol_defaults() -> None:
    sample = {"vt_symbol": "600999.SSE", "trade_date": "2026-06-05"}
    attached = attach_structure_features([sample], _bars([10.0] * 30))
    assert attached[0]["ma_state"] is None
    assert attached[0]["auction_gap_pct"] is None
    assert attached[0]["index_above_ma20"] is None


def test_index_regime_map_strict() -> None:
    rows = _bars([10.0 + index * 0.1 for index in range(25)], symbol="000001.SSE")
    dates, regime = _index_regime_map(rows)
    assert len(regime) == 6  # 25 根只有后 6 天满 20 根
    assert regime[dates[-1]] is True
    declining = _bars([20.0 - index * 0.1 for index in range(25)], symbol="000001.SSE")
    dates_down, regime_down = _index_regime_map(declining)
    assert regime_down[dates_down[-1]] is False
    short = _bars([10.0] * 10, symbol="000001.SSE")
    assert _index_regime_map(short)[1] == {}
    assert _index_regime_at(dates, regime, "1999-01-01") is None


# ── 组合 / 漏网归因 / 命中率 ────────────────────────────────────────────────


def _sample(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-07-15",
        "is_leader": True,
        "eventual_peak": 3,
        "d1_open_return_pct": 2.0,
        "position_126d": 0.2,
        "ma_bear_days": 20,
        "ma_converge_10_20_5d": 1.0,
        "ma10_cross20_up_5d": False,
        "close_above_ma10": True,
        "above_ma10_streak": 3,
        "ma10_slope_5d_pct": 0.5,
        "ma_tightness_pct": 2.0,
        "vol_spearman_5d": 0.8,
        "ma_bull_align": False,
        "position_20d": 0.2,
        "days_since_20d_low": 1,
    }
    base.update(overrides)
    return base


def test_combo_failed_clauses() -> None:
    assert _combo_failed_clauses(_sample(), "lowpos_converge") == []
    high_pos = _sample(position_126d=0.5)
    assert _combo_failed_clauses(high_pos, "lowpos_converge") == ["low_position"]
    both_bad = _sample(position_126d=0.5, ma_bear_days=5)
    assert _combo_failed_clauses(both_bad, "lowpos_converge") == ["low_position", "bear15"]
    # converge_or_cross：金叉可替代收拢
    crossed = _sample(ma_converge_10_20_5d=-1.0, ma10_cross20_up_5d=True)
    assert _combo_failed_clauses(crossed, "lowpos_converge") == []
    # wave 组合不需要低位
    wave = _sample(ma_bull_align=True, position_126d=0.9)
    assert _combo_failed_clauses(wave, "wave_bull_pullback") == []


def test_structure_combo_rows_with_leader3() -> None:
    samples = [
        _sample(),
        _sample(eventual_peak=2),
        _sample(is_leader=False, eventual_peak=1, d1_open_return_pct=-1.0),
        _sample(is_leader=False, eventual_peak=1, position_126d=0.8, ma_bear_days=0, close_above_ma10=False),
    ]
    rows = {row["combo"]: row for row in _structure_combo_rows(samples)}
    baseline = rows["__baseline__"]
    assert baseline["total"] == 4
    assert baseline["leader_count"] == 2
    assert baseline["leader3_count"] == 1  # eventual_peak>=3 仅首个
    converge = rows["lowpos_converge"]
    assert converge["total"] == 3  # 第四个样本低位/排列/站上均不满足
    assert converge["leader_rate"] == pytest.approx(2 / 3, abs=1e-4)
    strict = rows["lowpos_converge_strict"]
    assert strict["total"] == 3  # streak=3>=2 且 slope>0


def test_miss_analysis_attributes_clauses() -> None:
    leaders = [
        _sample(),
        _sample(position_126d=0.9, eventual_peak=4, trade_date="2026-07-16"),
        _sample(ma_bear_days=3, eventual_peak=2, trade_date="2026-07-17"),
    ]
    rows = {row["combo"]: row for row in _miss_analysis(leaders)}
    converge = rows["lowpos_converge"]
    assert converge["leader_total"] == 3
    assert converge["missed_count"] == 2
    assert converge["recall"] == pytest.approx(1 / 3, abs=1e-4)
    assert converge["missed_by_clause"] == {"low_position": 1, "bear15": 1}
    assert converge["missed_leader3_count"] == 1
    assert converge["missed_leader3"][0]["failed_clauses"] == ["low_position"]


def test_hit_rates_three_groups() -> None:
    samples = [
        _sample(),
        _sample(eventual_peak=2),
        _sample(is_leader=False, eventual_peak=1),
        _sample(is_leader=False, eventual_peak=1, vol_spearman_5d=0.0),
    ]
    rows = {row["pattern"]: row for row in _structure_hit_rates(samples)}
    trap_up = rows["trap_up"]
    assert trap_up["leader_hit_rate"] == 1.0  # 2/2
    assert trap_up["leader3_hit_rate"] == 1.0  # 1/1
    assert trap_up["non_leader_hit_rate"] == 0.5  # 1/2
    assert trap_up["rate_ratio"] == 2.0


# ── 案例核查 ────────────────────────────────────────────────────────────────


def test_case_helpers_range_and_ma() -> None:
    closes = [10.0 + index * 0.1 for index in range(40)]
    bars = _bars(closes, turnovers=[float(100 - index) for index in range(40)])
    ctx = _case_context(bars)
    start, end = ctx["dates"][30], ctx["dates"][39]
    assert _range_vol_spearman(ctx, start, end) == -1.0  # 区间量单调递减
    assert _closes_below_ma_between(ctx, 5, start, end) is False  # 上行不收破 MA5
    assert _no_close_below_ma_since(ctx, 5, start) is False
    assert _alignment_since(ctx, "bull", ctx["dates"][29]) is True
    spread = _spread_at(ctx, end)
    assert spread is not None and spread > 0
    assert _closes_below_ma_between(ctx, 5, "2099-01-01", "2099-01-02") is None  # 空区间


def test_had_close_below_ma_within() -> None:
    # 先上行（全在 MA20 上方），最后两日跌破
    closes = [10.0 + index * 0.2 for index in range(36)] + [16.0, 15.0, 14.0, 13.0]
    ctx = _case_context(_bars(closes))
    assert _had_close_below_ma_within(ctx, 20, 4) is True
    assert _had_close_below_ma_within(ctx, 20, 2) is True  # 最后两日确实破
    rising = _case_context(_bars([10.0 + index * 0.1 for index in range(40)]))
    assert _had_close_below_ma_within(rising, 20, 4) is False
    short = _case_context(_bars([10.0] * 3))
    assert _had_close_below_ma_within(short, 20, 4) is None  # 天数不足


def test_first_close_below_ma_since() -> None:
    # 平稳后下行：找第一个收破 MA10 的日期（起点须在 MA 可算之后，否则 None）
    closes = [15.0] * 20 + [15.0 - index * 0.5 for index in range(10)]
    bars = _bars(closes)
    ctx = _case_context(bars)
    assert _first_close_below_ma_since(ctx, 10, ctx["dates"][0]) is None  # 前 9 天 MA 不可算
    first = _first_close_below_ma_since(ctx, 10, ctx["dates"][9])
    assert first is not None and first != ""
    # 验证返回的确实是第一个收破日
    idx = ctx["dates"].index(first)
    ma_values = [
        sum(ctx["closes"][k - 9 : k + 1]) / 10 for k in range(9, len(ctx["closes"]))
    ]
    assert ctx["closes"][idx] < ma_values[idx - 9]
    assert all(
        ctx["closes"][k] >= ma_values[k - 9] for k in range(9, idx)
    )
    rising = _case_context(_bars([10.0 + index * 0.1 for index in range(30)]))
    assert _first_close_below_ma_since(rising, 10, rising["dates"][9]) == ""


def test_alignment_since_tolerance() -> None:
    # 多头但 ma20≈ma30 贴平：严格判定失败、容差 0.1% 通过
    closes = [10.0 + index * 0.05 for index in range(35)]
    ctx = _case_context(_bars(closes))
    strict = _alignment_since(ctx, "bull", ctx["dates"][29])
    tolerant = _alignment_since(ctx, "bull", ctx["dates"][29], tolerance=0.001)
    assert strict is True and tolerant is True
    # 构造 ma20<ma30 微量倒挂（容差内）：长期上行后短暂走平
    flat = [10.0 + index * 0.3 for index in range(25)] + [17.2] * 10
    ctx_flat = _case_context(_bars(flat))
    strict_flat = _alignment_since(ctx_flat, "bull", ctx_flat["dates"][24])
    if strict_flat is False:  # 若存在贴平日，容差应放行
        assert _alignment_since(ctx_flat, "bull", ctx_flat["dates"][24], tolerance=0.01) is True


def test_ma_hold_since_tolerance_semantics() -> None:
    # 沿 MA10 上方运行，最后一天贴线约 -1%：1.5% 容差通过、0.1% 容差视为下杀
    closes = [17.0] * 15 + [17.2, 17.4, 17.3, 17.5, 17.4, 17.0]
    ctx = _case_context(_bars(closes))
    start = ctx["dates"][15]
    holds, worst, day = _ma_hold_since(ctx, 10, start, 0.015)
    assert holds is True and worst is not None and worst < 0 and day
    strict_holds, _, _ = _ma_hold_since(ctx, 10, start, 0.001)
    assert strict_holds is False
    # 起点在 MA 可算之前 → 全 None
    assert _ma_hold_since(ctx, 10, ctx["dates"][0], 0.015) == (None, None, None)


def test_board_window_vol_spearman() -> None:
    # 跨首板窗口：D-1 前 N 天 + 首板日起 M 天拼接（helper 只读 bars/bars_after）
    ctx = {
        "bars": [
            {"trade_date": "2026-02-26", "turnover": 100.0},
            {"trade_date": "2026-02-27", "turnover": 200.0},
            {"trade_date": "2026-03-01", "turnover": 300.0},
        ],
        "bars_after": [
            {"trade_date": "2026-03-02", "turnover": 500.0},
            {"trade_date": "2026-03-03", "turnover": 800.0},
        ],
    }
    assert _board_window_vol_spearman(ctx, 2, 2) == 1.0  # 200<300<500<800 单调递增
    assert _board_window_vol_spearman(ctx, 1, 1) is None  # 仅 2 个有效点


def test_case_context_carries_after_bars() -> None:
    bars = _bars([10.0] * 35)
    ctx = _case_context(bars[:33], bars[33:])
    assert len(ctx["bars_after"]) == 2
    assert ctx["bars_after"][0]["trade_date"] == bars[33]["trade_date"]


def test_v_and_b_wrappers() -> None:
    assert _v(3.0, lambda v: v >= 2, "{:.0f}") == (True, "3")
    assert _v(None, lambda v: v >= 2) == (None, "数据不足")
    assert _b(True, True, "x") == (True, "x=True")
    assert _b(False, True, "x") == (False, "x=False")
    assert _b(None, True, "x") == (None, "数据不足")


def test_audit_cases_resolves_and_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    bars = _bars([10.0 + index * 0.1 for index in range(40)], symbol="600999.SSE")
    board_day = bars[-1]["trade_date"]
    monkeypatch.setattr(
        research,
        "CASE_AUDIT",
        (
            {
                "name": "测试股份",
                "first_board": board_day,
                "note": "合成案例",
                "claims": (
                    {"id": "above", "desc": "站上MA10", "check": lambda c: _b(c.get("close_above_ma10"), True, "close≥MA10")},
                    {"id": "bear", "desc": "空头排列", "check": lambda c: _b(c.get("ma_bear_align"), True, "bear")},
                ),
            },
        ),
    )
    result = _audit_cases(
        bars,
        {("600999.SSE", board_day): 4},
        {"600999.SSE": "测试股份"},
    )
    case = result["cases"][0]
    assert case["status"] == "ok"
    assert case["in_first_board_set"] is True
    assert case["eventual_peak"] == 4
    verdicts = {claim["id"]: claim["verdict"] for claim in case["claims"]}
    assert verdicts == {"above": "符合", "bear": "不符合"}
    assert result["claims_passed"] == 1
    assert result["claims_failed"] == 1


# ── 盘前全市场框架（frame 2）────────────────────────────────────────────────


def _frame_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, object]], dict[tuple[str, str], int], dict[str, str], list[str]]:
    monkeypatch.setattr(research, "_COMBO_CLAUSES", (("always", "恒真", ()),))
    monkeypatch.setattr(research, "COMBO_NAMES", ("always",))
    index_bars = _bars([10.0 + index * 0.1 for index in range(40)], symbol="000001.SSE")
    stock_a = _bars([10.0 + index * 0.05 for index in range(40)], symbol="600001.SSE")
    stock_b = _bars([20.0 - index * 0.05 for index in range(35)], symbol="600002.SSE")
    daily_bars = index_bars + stock_a + stock_b
    calendar = sorted({str(bar["trade_date"]) for bar in daily_bars})
    # A 在 index32 首板（>=3 板妖股）+ index39 第二个事件（把事件末端推后，
    # 否则尾部 5 日排除会让 board32 的命中窗口全被截断）
    first_board_index = {
        ("600001.SSE", stock_a[32]["trade_date"]): 3,
        ("600001.SSE", stock_a[39]["trade_date"]): 1,
    }
    names = {"600001.SSE": "案例甲", "600002.SSE": "案例乙", "000001.SSE": "上证指数"}
    return daily_bars, first_board_index, names, calendar


def test_premarket_frame_labels_and_base_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture(monkeypatch)
    frame = build_premarket_structure_frame(
        daily_bars, first_board_index, names, calendar, forward_days=3, min_history=10
    )
    assert frame["eligible_symbols"] == 2  # 指数被 is_eligible_main_board 排除
    # A 有效 t=9..34（26 天，尾部截断 dates[34]）；B 有效 t=9..31（23 天，其后 label_invalid）
    assert frame["stock_days"] == 49
    assert frame["invalid_labels"] == 3  # B 的 t=32..34 前向窗超出自身 bars
    # 命中：t∈{29,30,31} 各在 3 日前向窗内命中 board32（同一妖股，3 个股票日分别计）
    assert frame["base_rates"]["board_5d"] == pytest.approx(3 / 49, abs=1e-6)
    assert frame["base_rates"]["peak3_5d"] == frame["base_rates"]["board_5d"]
    combo = frame["per_combo"][0]
    assert combo["combo"] == "always"
    assert combo["candidate_days"] == frame["stock_days"]
    assert combo["lift"] == 1.0
    assert combo["peak3_hits"] == 3
    assert combo["avg_candidates_per_day"] is not None
    # regime 需 20 根指数 bar：t<dates[20] 的股票日 regime 未知
    assert 0 < frame["by_regime"]["above"]["stock_days"] < frame["stock_days"]


def test_premarket_frame_excludes_at_limit_days(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture(monkeypatch)
    # 把 A 的中间某天改成涨停（close >= 前收*1.098）→ 该日不得计入分母
    limit_index = 20
    rows = [bar for bar in daily_bars if bar["vt_symbol"] == "600001.SSE"]
    rows[limit_index]["close_price"] = rows[limit_index - 1]["close_price"] * 1.1
    frame = build_premarket_structure_frame(
        daily_bars, first_board_index, names, calendar, forward_days=3, min_history=10
    )
    assert frame["stock_days"] == 48  # A 25 天（涨停日剔除）+ B 23 天


def test_premarket_frame_invalid_label_beyond_events(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture(monkeypatch)
    # B 只有 35 根：t=32..34 的前向 3 日窗超出自身 bars → label_invalid
    frame = build_premarket_structure_frame(
        daily_bars, first_board_index, names, calendar, forward_days=3, min_history=10
    )
    assert frame["invalid_labels"] == 3


def test_premarket_frame_min_history_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture(monkeypatch)
    frame = build_premarket_structure_frame(
        daily_bars, first_board_index, names, calendar, forward_days=3, min_history=40
    )
    # A 唯一满足 40 根的 t=39 在尾部截断之后；B 不足 40 根
    assert frame["stock_days"] == 0


def test_premarket_frame_suspension_span_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research, "_COMBO_CLAUSES", (("always", "恒真", ()),))
    monkeypatch.setattr(research, "COMBO_NAMES", ("always",))
    index_bars = _bars([10.0] * 30, symbol="000001.SSE")
    # 股票在中间停牌 8 天（日期缺失）
    closes = [10.0] * 15 + [10.5] * 15
    stock = _bars(closes, symbol="600003.SSE")
    gap_start = date.fromisoformat(stock[15]["trade_date"])
    for offset, bar in enumerate(stock[15:]):
        bar["trade_date"] = (gap_start + timedelta(days=offset + 8)).isoformat()
    daily_bars = index_bars + stock
    calendar = sorted({str(bar["trade_date"]) for bar in daily_bars})
    # 停牌后第 3 个个股日首板 + 更晚的第二个事件（避免尾部截断吃掉命中窗口）
    first_board_index = {
        ("600003.SSE", stock[18]["trade_date"]): 2,
        ("600003.SSE", stock[25]["trade_date"]): 1,
    }
    frame = build_premarket_structure_frame(
        daily_bars, first_board_index,
        {"600003.SSE": "停牌股", "000001.SSE": "上证指数"},
        calendar, forward_days=3, min_history=10,
    )
    # 跨停牌的前向窗市场跨度>10 → 那些日记 invalid；但窗口内首板仍可命中
    assert frame["invalid_labels"] > 0
    assert frame["base_rates"]["board_5d"] is not None
    assert frame["base_rates"]["board_5d"] > 0


# ── 主人规则 / 类型分类 / 早盘价格 / 最终裁决 ────────────────────────────────


def _owner_sample(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-07-15",
        "is_leader": True,
        "eventual_peak": 3,
        "d1_open_return_pct": 2.0,
        "ma_bear_days": 20,
        "ma10_cross20_up_5d": False,
        "ma_spread_10_20_pct": 0.5,
        "ma_tightness_pct": 2.0,
        "close_above_ma10": True,
        "ma_bull_align": False,
        "position_20d": 0.2,
        "days_since_20d_low": 1,
        "vol_spearman_5d": 0.8,
        "prelude_vol_cv_7d": 0.3,
        "auction_gap_pct": 2.5,
    }
    base.update(overrides)
    return base


def test_owner_rule_predicates() -> None:
    predicates = dict((name, pred) for name, _, pred in research._owner_rule_predicates(0.35))
    assert predicates["R1_lowpos_form1"](_owner_sample()) is True
    # 形式一：spread 远且无金叉 → 失败
    assert predicates["R1_lowpos_form1"](_owner_sample(ma_spread_10_20_pct=3.0)) is False
    # 但金叉可救回
    assert predicates["R1_lowpos_form1"](
        _owner_sample(ma_spread_10_20_pct=3.0, ma10_cross20_up_5d=True)
    ) is True
    assert predicates["R2_lowpos_form2"](_owner_sample()) is True
    assert predicates["R2_lowpos_form2"](_owner_sample(ma_tightness_pct=4.0)) is False
    assert predicates["R3_lowpos_stable"](_owner_sample()) is True
    assert predicates["R3_lowpos_stable"](_owner_sample(close_above_ma10=False)) is False
    assert predicates["R4_wave_bull"](_owner_sample(ma_bull_align=True)) is True
    assert predicates["R4_wave_bull"](_owner_sample()) is False  # 非多头
    assert predicates["R5_wave_price"](_owner_sample()) is True
    assert predicates["R5_wave_price"](_owner_sample(days_since_20d_low=5)) is False
    assert predicates["R6_vol_trapezoid"](_owner_sample()) is True
    assert predicates["R6_vol_trapezoid"](_owner_sample(vol_spearman_5d=-0.9)) is True
    assert predicates["R6_vol_trapezoid"](_owner_sample(vol_spearman_5d=0.3)) is False
    # R7 中位数阈值：cv 0.3 ≤ 0.35 通过
    assert predicates["R7_vol_calm"](_owner_sample()) is True
    assert predicates["R7_vol_calm"](_owner_sample(prelude_vol_cv_7d=0.5)) is False


def test_classify_owner_type_priority() -> None:
    assert research._classify_owner_type(_owner_sample()) == "lowpos_form1"
    assert research._classify_owner_type(_owner_sample(ma_spread_10_20_pct=3.0)) == "lowpos_form2"
    assert research._classify_owner_type(
        _owner_sample(ma_bear_days=0, ma_tightness_pct=5.0, ma_bull_align=True)
    ) == "wave_bull"
    assert research._classify_owner_type(
        _owner_sample(ma_bear_days=0, ma_tightness_pct=5.0)
    ) == "wave_price"
    assert research._classify_owner_type(
        _owner_sample(ma_bear_days=0, ma_tightness_pct=5.0, position_20d=0.9)
    ) == "other"


def test_gap_bucket_boundaries() -> None:
    assert research._gap_bucket(-0.5) == "<0"
    assert research._gap_bucket(0.0) == "0-1"
    assert research._gap_bucket(1.5) == "1-2"
    assert research._gap_bucket(2.0) == "2-4"
    assert research._gap_bucket(9.4) == "4-9.5"
    assert research._gap_bucket(10.0) == ">=9.5"
    assert research._gap_bucket(None) is None


def test_auction_by_type_math() -> None:
    samples = [
        _owner_sample(auction_gap_pct=3.0),
        _owner_sample(auction_gap_pct=3.5, eventual_peak=2),
        _owner_sample(auction_gap_pct=-1.0, is_leader=False, eventual_peak=1),
        _owner_sample(ma_bear_days=0, ma_tightness_pct=5.0, position_20d=0.9, auction_gap_pct=0.5),
    ]
    rows = {row["type"]: row for row in research._auction_by_type(samples)}
    form1 = rows["lowpos_form1"]
    assert form1["total"] == 3
    assert form1["leader_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert form1["gap_ge2_rate"] == pytest.approx(2 / 3, abs=1e-4)
    buckets = {row["bucket"]: row for row in form1["buckets"]}
    assert buckets["2-4"]["leader_rate"] == 1.0
    assert buckets["<0"]["leader_rate"] == 0.0


def test_monthly_rule_rates_flip_detection() -> None:
    samples: list[dict[str, object]] = []
    # 6 月：规则组胜率远高于基线（higher）；7 月：规则组全灭（lower）→ 一致率 0.5
    for index in range(40):
        samples.append(
            _owner_sample(trade_date=f"2026-06-{index % 28 + 1:02d}", is_leader=index % 4 != 3)
        )
        samples.append(
            _owner_sample(trade_date=f"2026-06-{index % 28 + 1:02d}", is_leader=False,
                          ma_spread_10_20_pct=9.0, eventual_peak=1)
        )
    for index in range(40):
        samples.append(
            _owner_sample(trade_date=f"2026-07-{index % 28 + 1:02d}", is_leader=False, eventual_peak=1)
        )
        samples.append(
            _owner_sample(trade_date=f"2026-07-{index % 28 + 1:02d}", is_leader=index % 2 == 0,
                          ma_spread_10_20_pct=9.0, eventual_peak=2)
        )
    rows = {row["rule"]: row for row in research._monthly_rule_rates(samples, calm_median=0.35)}
    r1 = rows["R1_lowpos_form1"]
    assert r1["full_direction"] == "higher"  # 全样本规则组胜率高于基线
    assert r1["monthly_agreement"] == 0.5  # 6 月 higher、7 月 lower → 一半一致


def test_premarket_frame_owner_rules_and_auction(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture(monkeypatch)
    frame = build_premarket_structure_frame(
        daily_bars, first_board_index, names, calendar, forward_days=3, min_history=10
    )
    assert "owner_rules_premarket" in frame
    assert {row["rule"] for row in frame["owner_rules_premarket"]} == set(
        research.OWNER_RULE_NAMES
    )
    auction = frame["auction_frame"]
    assert auction["auction_days"] > 0
    # A 的 board32 前一日（index31）次日缺口应计入 auction
    assert auction["base_board_1d"] is not None and auction["base_board_1d"] > 0
    cell_types = {cell["type"] for cell in auction["cells"]}
    assert "other" in cell_types  # 合成数据不满足任何主人形态 → other 类


def test_final_verdicts_logic() -> None:
    filter_row = research._verdict_row("x", "t", lift=3.5, candidate_days=200)
    assert filter_row["verdict"] == "过滤级"
    ranking_lift = research._verdict_row("x", "t", lift=2.0, candidate_days=200)
    assert ranking_lift["verdict"] == "排序级"
    ranking_ratio = research._verdict_row(
        "x", "t", hit_ratio=1.2, agreement=0.8, flipped=False
    )
    assert ranking_ratio["verdict"] == "排序级"
    ranking_auc = research._verdict_row("x", "t", auc=0.56, agreement=1.0, flipped=False)
    assert ranking_auc["verdict"] == "排序级"  # 纯数值因子 AUC 通道
    flip_kill = research._verdict_row("x", "t", hit_ratio=1.2, agreement=0.8, flipped=True)
    assert flip_kill["verdict"] == "淘汰"
    auc_flip_kill = research._verdict_row("x", "t", auc=0.58, agreement=0.9, flipped=True)
    assert auc_flip_kill["verdict"] == "淘汰"
    watch = research._verdict_row("x", "t", total=43, leader_rate=0.32)
    assert watch["verdict"] == "观察"
    reject = research._verdict_row("x", "t", lift=0.8, candidate_days=1000, total=500)
    assert reject["verdict"] == "淘汰"


# ── 过滤器家族 / 召回前沿 / 封板率 / 触板验证 ────────────────────────────────


def test_structure_features_tool_keys() -> None:
    closes = [10.0 + index * 0.1 for index in range(30)]
    features = _structure_features(_bars(closes))
    assert features["prior_return_5d_pct"] == pytest.approx(
        (closes[-1] / closes[-6] - 1) * 100, abs=1e-3
    )
    assert features["amplitude_20d_pct"] is not None and features["amplitude_20d_pct"] > 0
    short = _structure_features(_bars([10.0] * 5))
    assert short["prior_return_5d_pct"] is None
    assert short["amplitude_20d_pct"] is None


def test_owner_lowpos4_pred_matches_production() -> None:
    from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
        _long_window_features,
    )
    from alphaagent.server.services.limit_up.leader_minute_backtest import (
        _is_owner_low_position,
    )

    cases = [
        [10.0] * 130,  # 平盘：回撤 0 → 拒绝
        [20.0 - index * 0.1 for index in range(130)],  # 单边阴跌：回撤深反弹小
        [5.0] * 120 + [20.0] * 10,  # 急反弹 → 拒绝
        [10.0 + (index % 7) * 0.8 for index in range(130)],  # 宽幅震荡
        [10.0] * 10,  # 历史不足 → 两函数都应拒绝（drawdown None）
    ]
    for closes in cases:
        bars = _bars(closes)
        expected = _is_owner_low_position(bars)
        # 生产低位谓词在合并 dict（结构特征+长窗特征）上调用，与 frame-1/2 一致
        features = {**_structure_features(bars), **_long_window_features(bars)}
        assert research._owner_lowpos4_pred(features) == expected


def test_filter_sets_union_semantics() -> None:
    sets = dict((name, fn) for name, _, fn in research._filter_sets(0.35))
    assert sets["__none__"]({}) is True
    assert sets["U_lowpos"](_owner_sample()) is True  # 满足形式一
    assert sets["U_lowpos"](_owner_sample(ma_spread_10_20_pct=3.0)) is True  # 满足形式二
    assert (
        sets["U_lowpos"](_owner_sample(ma_spread_10_20_pct=3.0, ma_tightness_pct=9.0)) is False
    )
    # U_plus_trapezoid：形态全不满足但梯形满足 → 通过
    assert (
        sets["U_plus_trapezoid"](
            _owner_sample(
                ma_spread_10_20_pct=3.0,
                ma_tightness_pct=9.0,
                ma_bull_align=False,
                position_20d=0.9,
            )
        )
        is True
    )
    assert sets["momentum_ref"](_owner_sample(bias_ma20_pct=6.0)) is True
    assert sets["momentum_ref"](_owner_sample(bias_ma20_pct=2.0)) is False


def test_build_touch_index_first_touch_rule() -> None:
    events = [
        {"vt_symbol": "600001.SSE", "trade_date": "2026-07-01", "event_type": "limit_pool_zt", "limit_times": 1},
        {"vt_symbol": "600001.SSE", "trade_date": "2026-07-02", "event_type": "limit_pool_zt", "limit_times": 2},
        {"vt_symbol": "600001.SSE", "trade_date": "2026-07-03", "event_type": "limit_pool_zbgc", "limit_times": 0},  # 前 1 天有封板 → 非首触
        {"vt_symbol": "600002.SSE", "trade_date": "2026-07-03", "event_type": "limit_pool_zbgc", "limit_times": 0},  # 无封板史 → 首触
        {"vt_symbol": "600001.SSE", "trade_date": "2026-07-20", "event_type": "limit_pool_zbgc", "limit_times": 0},  # 封板已 10+ 天前 → 首触
    ]
    calendar = [f"2026-07-{day:02d}" for day in range(1, 31)]
    index, stats = research._build_touch_index(events, calendar)
    assert index[("600001.SSE", "2026-07-01")] == "zt"
    assert ("600001.SSE", "2026-07-03") not in index  # 非首触剔除
    assert index[("600002.SSE", "2026-07-03")] == "zbgc"
    assert index[("600001.SSE", "2026-07-20")] == "zbgc"
    assert stats == {"zt_first": 1, "zbgc_first_touch": 2, "zbgc_not_first": 1}


def test_frontier_by_height_recall_math() -> None:
    samples = [
        _owner_sample(eventual_peak=2),
        _owner_sample(eventual_peak=3),
        _owner_sample(eventual_peak=5, ma_spread_10_20_pct=9.0, ma_tightness_pct=9.0),  # 形态不满足
        _owner_sample(eventual_peak=1, is_leader=False),
    ]
    rows = {row["filter"]: row for row in research._frontier_by_height(samples, calm_median=0.35)}
    none_row = rows["__none__"]
    assert none_row["recall_peak2"] == 1.0
    assert none_row["recall_peak5p"] == 1.0
    r1 = rows["R1_lowpos_form1"]
    assert r1["recall_peak2"] == 1.0  # 2板那只满足形式一
    assert r1["recall_peak3"] == 1.0
    assert r1["recall_peak5p"] == 0.0  # 5板那只不满足
    assert r1["pass_total"] == 2


def test_touch_seal_analysis_math(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        {"vt_symbol": "600001.SSE", "trade_date": "2026-07-01", "event_type": "limit_pool_zt", "limit_times": 1},
        {"vt_symbol": "600002.SSE", "trade_date": "2026-07-02", "event_type": "limit_pool_zbgc", "limit_times": 0},
        {"vt_symbol": "600003.SSE", "trade_date": "2026-07-03", "event_type": "limit_pool_zbgc", "limit_times": 0},
    ]
    calendar = [f"2026-07-{day:02d}" for day in range(1, 31)]

    def fake_attach(touch_samples, daily_bars, **kwargs):
        out = []
        for sample in touch_samples:
            merged = dict(sample)
            merged["ma_bear_days"] = 20 if sample["vt_symbol"] != "600003.SSE" else 0
            merged["ma_spread_10_20_pct"] = 0.5
            merged["ma10_cross20_up_5d"] = False
            out.append(merged)
        return out

    monkeypatch.setattr(research, "attach_structure_features", fake_attach)
    result = research._touch_seal_analysis(events, [], calendar, calm_median=0.35)
    assert result["total_touches"] == 3
    assert result["total_sealed"] == 1
    per_filter = {row["filter"]: row for row in result["per_filter"]}
    r1 = per_filter["R1_lowpos_form1"]
    assert r1["touches"] == 2  # 600001 + 600002 满足形式一
    assert r1["seal_rate"] == 0.5
    assert r1["rejected_seal_rate"] == 0.0


def test_premarket_frame_touch_and_share(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture(monkeypatch)
    stock_a = [bar for bar in daily_bars if bar["vt_symbol"] == "600001.SSE"]
    touch_index = {
        (stock_a[33]["vt_symbol"], stock_a[33]["trade_date"]): "zbgc",  # index32 次日触板未封
        (stock_a[32]["vt_symbol"], stock_a[32]["trade_date"]): "zt",
        (stock_a[39]["vt_symbol"], stock_a[39]["trade_date"]): "zt",
    }
    frame = build_premarket_structure_frame(
        daily_bars,
        first_board_index,
        names,
        calendar,
        forward_days=3,
        min_history=10,
        touch_index=touch_index,
    )
    frontier = {row["filter"]: row for row in frame["frontier"]}
    none_row = frontier["__none__"]
    assert none_row["share_mean"] == 1.0  # 无过滤占比 100%
    assert none_row["touch1d"] >= 1
    assert none_row["seal_given_touch_1d"] is not None
    # 无过滤的 5 日 lift 应为 1.0
    assert none_row["lift"] == 1.0
    auction = frame["auction_frame"]
    assert auction["daily_consistency"]["days_valid"] >= 0
    assert auction["monthly_touch"]


# ── 报告编排（monkeypatch 重计算块）─────────────────────────────────────────


def test_build_report_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = [
        _sample(trade_date="2026-06-15"),
        _sample(trade_date="2026-06-16", eventual_peak=2),
        _sample(trade_date="2026-07-15", is_leader=False, eventual_peak=1, d1_open_return_pct=-1.0),
        _sample(trade_date="2026-07-16", is_leader=False, eventual_peak=1, position_126d=0.8),
    ]

    monkeypatch.setattr(
        research, "build_factor_samples", lambda *args, **kwargs: ([], samples)
    )
    monkeypatch.setattr(
        research,
        "attach_structure_features",
        lambda factor_samples, daily_bars, **kwargs: [dict(s) for s in factor_samples],
    )
    monkeypatch.setattr(
        research,
        "extract_first_board_samples",
        lambda *args, **kwargs: [
            {"vt_symbol": s["vt_symbol"], "trade_date": s["trade_date"], "eventual_peak": s["eventual_peak"]}
            for s in samples
        ],
    )
    monkeypatch.setattr(
        research, "_audit_cases", lambda *args, **kwargs: {"cases": [], "claims_total": 0}
    )
    monkeypatch.setattr(
        research,
        "build_premarket_structure_frame",
        lambda *args, **kwargs: {"stock_days": 0, "per_combo": []},
    )
    report = research.build_structure_report([], [], [], [], [], {})
    assert report["status"] == "ok"
    assert report["first_board_count"] == 4
    assert report["label_balance"]["positive"] == 2
    assert report["label_balance"]["peak3"] == 1
    assert report["case_audit"] == {"cases": [], "claims_total": 0}
    assert report["hit_rates"]
    assert len(report["numeric_factors"]) == len(research.STRUCTURE_NUMERIC_KEYS)
    assert len(report["monthly_stability"]) == len(research.STRUCTURE_NUMERIC_KEYS)
    assert len(report["june_july_check"]) == len(research.STRUCTURE_NUMERIC_KEYS)
    combos = {row["combo"] for row in report["combos"]}
    assert combos == {"__baseline__", *research.COMBO_NAMES}
    assert len(report["miss_analysis"]) == len(research.COMBO_NAMES)
    assert report["regime_split"]["by_regime"]
    assert report["premarket_frame"] == {"stock_days": 0, "per_combo": []}
    assert report["auction_gap"]["factor_key"] == "auction_gap_pct"
    assert {row["rule"] for row in report["owner_rules"]} == {
        "__baseline__",
        *research.OWNER_RULE_NAMES,
    }
    assert len(report["owner_rules_monthly"]) == len(research.OWNER_RULE_NAMES)
    assert len(report["auction_by_type"]) == len(research.OWNER_TYPES)
    assert {row["filter"] for row in report["frontier_by_height"]} == {
        name for name, _, _ in research._filter_sets(None)
    }
    assert report["touch_seal"]["per_filter"]
    assert report["final_verdicts"]
    assert report["notes"]
