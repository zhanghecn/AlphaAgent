"""融合计分卡研究测试：旅程因子手算、计分卡爬坡、桶/TopN/底线、编排。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import alphaagent.server.services.limit_up.leader_first_board_fused_score_research as research
from alphaagent.server.services.limit_up.leader_first_board_fused_score_research import (
    _frame1_analysis,
    _fused_score,
    _journey_features,
    _lowpos_score,
    _ramp,
    _score_bucket,
    _sensitivity_rows,
    _touch_dates_by_symbol,
    _volume_bonus,
    _wave_score,
    attach_fused_scores,
    build_fused_frame,
    build_fused_report,
)


def _bars(
    closes: list[float],
    *,
    turnovers: list[float | None] | None = None,
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
                "change_pct": 1.0,
                "turnover": turnovers[index] if turnovers else 100.0,
            }
        )
    return bars


# ── 旅程因子（_journey_features）────────────────────────────────────────────


def test_journey_linear_decline() -> None:
    """线性下跌：全程空头排列，价差恒定 → 不收拢（conv=0）、阶段 0。"""

    closes = [100.0 - index * 0.1 for index in range(70)]
    features = _journey_features(_bars(closes))
    assert features["bear_run_max_40d"] == 40  # 窗内 40 天全空头
    assert (features["bear_depth_peak_pct"] or 0) > 0
    assert (features["spread_peak_abs_pct"] or 0) > 0
    assert features["conv_days"] == 0  # 价差恒定，未收窄一半
    assert features["cross_stage"] == 0
    assert features["pure_20d"] is None  # 未传触碰集合


def test_journey_converging_when_decline_flattens() -> None:
    """急跌转平缓：价差收窄 → conv_days>0，空头基底仍在。"""

    closes = [50.0 - index for index in range(40)] + [10.0 - index * 0.01 for index in range(30)]
    features = _journey_features(_bars(closes))
    assert features["bear_run_max_40d"] == 40
    assert (features["conv_days"] or 0) > 0
    assert features["cross_stage"] == 0


def test_journey_cross_stage_one() -> None:
    """V 形反转：MA10 已上穿 MA20、MA20 仍在 MA30 下方 → 阶段 1（手算验证）。"""

    # 57 根缓跌（40→12）+ 12 根 1.0/日反弹（13..24）：
    # MA10=19.5 > MA20=16.6，MA30=17.15 > MA20 → stage 1
    closes = [40.0 - 0.5 * index for index in range(57)] + [
        12.0 + (index + 1) * 1.0 for index in range(12)
    ]
    features = _journey_features(_bars(closes))
    assert features["cross_stage"] == 1
    assert (features["bear_run_max_40d"] or 0) >= 25  # 窗内 28 天空头基底


def test_journey_cross_stage_two_on_bull() -> None:
    closes = [10.0 + index * 0.1 for index in range(70)]
    features = _journey_features(_bars(closes))
    assert features["cross_stage"] == 2
    assert features["bear_run_max_40d"] == 0  # 窗内无空头日


def test_journey_insufficient_history() -> None:
    """68 根（<69）：旅程键 None，但 cross_stage（只需 30 根）仍可算。"""

    features = _journey_features(_bars([100.0 - index * 0.1 for index in range(68)]))
    assert features["bear_run_max_40d"] is None
    assert features["conv_days"] is None
    assert features["cross_stage"] == 0


def test_journey_purity_window() -> None:
    bars = _bars([10.0] * 30)
    dates = [str(bar["trade_date"]) for bar in bars]
    # 窗内（D-1 当天也算）有触碰 → 不纯
    assert _journey_features(bars, {dates[-1]})["pure_20d"] is False
    assert _journey_features(bars, {dates[-20]})["pure_20d"] is False
    # 窗外（第 21 根之前）→ 纯
    assert _journey_features(bars, {dates[-21]})["pure_20d"] is True
    assert _journey_features(bars, set())["pure_20d"] is True
    # 历史不足 20 根 → None；触碰集合未知 → None
    assert _journey_features(bars[:19], {dates[0]})["pure_20d"] is None
    assert _journey_features(bars, None)["pure_20d"] is None


def test_touch_dates_by_symbol_filters_event_types() -> None:
    events = [
        {"event_type": "limit_pool_zt", "vt_symbol": "600001.SSE", "trade_date": "2026-07-01"},
        {"event_type": "limit_pool_zbgc", "vt_symbol": "600001.SSE", "trade_date": "2026-07-02"},
        {"event_type": "limit_pool_zt", "vt_symbol": "600001.SSE", "trade_date": "2026-07-02"},
        {"event_type": "other", "vt_symbol": "600001.SSE", "trade_date": "2026-07-03"},
    ]
    touches = _touch_dates_by_symbol(events)
    assert touches == {"600001.SSE": {"2026-07-01", "2026-07-02"}}


# ── 计分卡（纯函数，字典特征直测）───────────────────────────────────────────


def test_ramp_and_volume_bonus() -> None:
    assert _ramp(None, 10) == 0.0
    assert _ramp(-5, 10) == 0.0
    assert _ramp(5, 10) == 0.5
    assert _ramp(15, 10) == 1.0
    assert _volume_bonus(None) == 0.0
    assert _volume_bonus(0.3) == 0.0
    assert _volume_bonus(-0.6) == 0.5  # 萎缩梯形也算
    assert _volume_bonus(0.7) == 1.0


def _lowpos_features(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "bear_run_max_40d": 20,
        "bear_depth_peak_pct": 6.0,
        "conv_days": 10,
        "cross_stage": 1,
        "above_ma10_streak": 3,
        "vol_spearman_5d": 0.8,
        "pure_20d": False,  # v2：近 20 日有触碰 → L7_recent_touch +1
    }
    base.update(overrides)
    return base


def test_lowpos_score_gate() -> None:
    """资格门：最长空头 <15 不合格（score=0 但 raw 保留诊断值）。"""

    weak = _lowpos_score(_lowpos_features(bear_run_max_40d=14))
    assert weak["qualified"] is False
    assert weak["score"] == 0.0
    assert weak["raw"] > 0  # 子分仍算得出，供诊断
    missing = _lowpos_score(_lowpos_features(bear_run_max_40d=None))
    assert missing["qualified"] is False


def test_lowpos_score_full_marks() -> None:
    full = _lowpos_score(
        _lowpos_features(
            bear_run_max_40d=30,
            bear_depth_peak_pct=8.0,
            conv_days=15,
            cross_stage=2,
            above_ma10_streak=5,
            vol_spearman_5d=0.9,
            pure_20d=False,  # v2：有触碰才满分
        )
    )
    assert full["qualified"] is True
    assert full["score"] == pytest.approx(7.0)
    assert _lowpos_score(_lowpos_features(pure_20d=True))["subs"]["L7_recent_touch"] == 0.0
    partial = _lowpos_score(_lowpos_features())
    # 6/8 + 20/30 + 10/15 + 1/2 + 3/5 + 1 + 1 = 0.75+0.6667+0.6667+0.5+0.6+1+1
    assert partial["score"] == pytest.approx(5.1833, abs=1e-3)


def test_lowpos_score_none_subs_zero() -> None:
    """子分输入 None（历史不足）→ 该子分 0，不送分。"""

    result = _lowpos_score(
        _lowpos_features(bear_depth_peak_pct=None, conv_days=None, pure_20d=None)
    )
    assert result["subs"]["L1_depth"] == 0.0
    assert result["subs"]["L3_converge"] == 0.0
    assert result["subs"]["L7_recent_touch"] == 0.0


def test_wave_score_requires_bull_alignment() -> None:
    features = {
        "ma_bull_align": False,
        "ma_state": "bear_diverging",
        "ma_bull_days": 30,
        "position_20d": 0.0,
        "days_since_20d_low": 0,
        "vol_spearman_5d": 0.9,
    }
    assert _wave_score(features)["score"] == 0.0
    assert _wave_score({**features, "ma_bull_align": None, "ma_state": None})["score"] == 0.0
    full = _wave_score({**features, "ma_bull_align": True})
    assert full["qualified"] is True
    assert full["score"] == pytest.approx(4.0)


def test_wave_score_sideways_gate() -> None:
    """v2 横盘波浪门：均线缠绕 + 20 日低位 + 低点企稳（爱丽型）。"""

    sideways = _wave_score(
        {
            "ma_bull_align": False,
            "ma_state": "tangled",
            "ma_bull_days": 0,
            "position_20d": 0.05,
            "days_since_20d_low": 0,
            "vol_spearman_5d": 0.8,
        }
    )
    assert sideways["qualified"] is True
    # W1=0 + W2=0.9375 + W3=1 + W4=1 = 2.9375（横盘波浪拿不到多头时长分）
    assert sideways["score"] == pytest.approx(2.9375, abs=1e-3)
    # 缠绕但位置不够低 → 不合格
    assert _wave_score({**sideways_fixture(), "position_20d": 0.6})["qualified"] is False


def sideways_fixture() -> dict[str, object]:
    return {
        "ma_bull_align": False,
        "ma_state": "tangled",
        "ma_bull_days": 0,
        "position_20d": 0.05,
        "days_since_20d_low": 0,
        "vol_spearman_5d": 0.8,
    }


def test_wave_score_ramps() -> None:
    result = _wave_score(
        {
            "ma_bull_align": True,
            "ma_bull_days": 10,  # 0.5
            "position_20d": 0.4,  # (0.8-0.4)/0.8 = 0.5
            "days_since_20d_low": 1,  # 1-1/3
            "vol_spearman_5d": 0.5,  # 0.5
        }
    )
    assert result["score"] == pytest.approx(0.5 + 0.5 + 2 / 3 + 0.5, abs=1e-3)


def test_fused_score_takes_normalized_max_and_type() -> None:
    # 低位不合格、波浪满分 → fused 取波浪，类型 wave
    fused = _fused_score(
        {
            "bear_run_max_40d": 0,
            "ma_bull_align": True,
            "ma_bull_days": 20,
            "position_20d": 0.0,
            "days_since_20d_low": 0,
            "vol_spearman_5d": 0.8,
        }
    )
    assert fused["fused_type"] == "wave"
    assert fused["fused_score"] == pytest.approx(1.0)
    # 双资格 → both
    both = _fused_score(_lowpos_features(ma_bull_align=True, cross_stage=2))
    assert both["fused_type"] == "both"
    # 都不合格 → 0 分无类型
    none = _fused_score({"bear_run_max_40d": 0, "ma_bull_align": False})
    assert none["fused_score"] == 0.0
    assert none["fused_type"] is None


def test_score_bucket_boundaries() -> None:
    assert _score_bucket(0) == "0(未入榜)"
    assert _score_bucket(None) == "0(未入榜)"
    assert _score_bucket(0.001) == "0.0-0.2"
    assert _score_bucket(0.2) == "0.2-0.4"  # 踩线进右桶
    assert _score_bucket(0.6) == "0.6-0.8"
    assert _score_bucket(1.0) == "0.8-1.0"


# ── attach（frame-1 后处理）─────────────────────────────────────────────────


def _sample(symbol: str, trade_date: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "is_leader": True,
        "eventual_peak": 3,
    }
    base.update(overrides)
    return base


def test_attach_fused_scores_adds_keys_and_flattens_subs() -> None:
    bars = _bars([10.0 + index * 0.1 for index in range(40)])
    trade_date = str(bars[35]["trade_date"])
    attached = attach_fused_scores([_sample("600001.SSE", trade_date)], bars, {})
    row = attached[0]
    assert row["fused_type"] == "wave"  # 多头排列但无 69 根历史 → 低位门 None 不合格
    assert row["fused_score"] > 0
    assert "lowpos_L1_depth" in row and "wave_W1_bull_duration" in row
    assert row["bear_run_max_40d"] is None  # 40 < 69 历史不足


def test_attach_no_lookahead_future_bars_irrelevant() -> None:
    bars = _bars([10.0 + index * 0.1 for index in range(70)])
    trade_date = str(bars[60]["trade_date"])
    sample = _sample("600001.SSE", trade_date)
    full = attach_fused_scores([sample], bars, {"600001.SSE": set()})
    truncated = attach_fused_scores([sample], bars[:61], {"600001.SSE": set()})
    assert full[0]["fused_score"] == truncated[0]["fused_score"]
    assert full[0]["bear_run_max_40d"] == truncated[0]["bear_run_max_40d"]
    assert full[0]["conv_days"] == truncated[0]["conv_days"]


# ── frame-2 全市场框架 ─────────────────────────────────────────────────────


def _frame_fixture() -> tuple[
    list[dict[str, object]], dict[tuple[str, str], int], dict[str, str], list[str]
]:
    index_bars = _bars([10.0 + index * 0.1 for index in range(40)], symbol="000001.SSE")
    stock_a = _bars([10.0 + index * 0.05 for index in range(40)], symbol="600001.SSE")
    stock_b = _bars([20.0 - index * 0.05 for index in range(35)], symbol="600002.SSE")
    daily_bars = index_bars + stock_a + stock_b
    calendar = sorted({str(bar["trade_date"]) for bar in daily_bars})
    # A 在 index32 首板（3 板妖股）+ index39 第二事件（避免尾部截断吃掉命中窗）
    first_board_index = {
        ("600001.SSE", stock_a[32]["trade_date"]): 3,
        ("600001.SSE", stock_a[39]["trade_date"]): 1,
    }
    names = {"600001.SSE": "案例甲", "600002.SSE": "案例乙", "000001.SSE": "上证指数"}
    return daily_bars, first_board_index, names, calendar


def test_fused_frame_basic_tallies_and_conservation() -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture()
    frame = build_fused_frame(
        daily_bars,
        first_board_index,
        names,
        calendar,
        touch_dates_by_symbol={},
        forward_days=3,
        min_history=10,
    )
    # 与老框架同一标签口径：A t=9..34（26 天）+ B t=9..31（23 天）
    assert frame["scanned_days"] == 49
    assert frame["invalid_labels"] == 3
    assert frame["totals"] == {"days": 49, "board": 3, "leader": 3, "peak3": 3}
    # 六桶守恒：桶内股票日合计 = 总股票日
    assert sum(row["days"] for row in frame["buckets"]) == 49
    # A 多头排列 t>=29 入榜（波浪分），B 阴跌无 69 根历史 → 0 分
    assert frame["qualified_days"] == 6
    assert frame["buckets"][0]["days"] == 43  # 0(未入榜)
    # 命中全部落在 0.0-0.2 桶（波浪小子分），lift 显著 >1
    low_bucket = frame["buckets"][1]
    assert low_bucket["board"] == 3
    assert (low_bucket["lift"] or 0) > 1
    # 更细的桶全空 → 单调性无法算（如实 None）
    assert frame["bucket_monotonicity_spearman"] is None
    # Top-N：唯一候选是 A，N=1 即全召回
    top1 = frame["topn"][0]
    assert top1["n"] == 5
    assert top1["boards_captured"] == 3
    assert top1["board_recall"] == 1.0
    # 底线曲线 19 档；floors 四档结构齐全
    assert len(frame["lift_curve"]) == 19
    assert [row["lift_target"] for row in frame["floors"]] == [1.0, 1.5, 2.0, 3.0]
    # 对照组/月度/regime 结构齐全
    gates = {row["gate"] for row in frame["comparisons"]}
    assert "momentum_ref(bias20>=5)" in gates and "L7_recent_touch" in gates
    assert set(frame["monthly"]) >= {"monthly_agreement", "months", "june_july"}
    assert set(frame["regime"]) == {"above", "below"}


def test_fused_frame_min_history_gate() -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture()
    frame = build_fused_frame(
        daily_bars,
        first_board_index,
        names,
        calendar,
        touch_dates_by_symbol={},
        forward_days=3,
        min_history=40,
    )
    assert frame["scanned_days"] == 0  # A 唯一 40 根的 t=39 在尾部截断后；B 不足


def test_fused_frame_topn_tie_break_by_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    """同分按代码升序：两只同形态多头票，600001 排前，N=1 只取它。"""

    monkeypatch.setattr(research, "TOP_N_LIST", (1, 2))

    index_bars = _bars([10.0 + index * 0.1 for index in range(50)], symbol="000001.SSE")
    stock_a = _bars([10.0 + index * 0.05 for index in range(50)], symbol="600001.SSE")
    stock_c = _bars([10.0 + index * 0.05 for index in range(50)], symbol="600002.SSE")
    daily_bars = index_bars + stock_a + stock_c
    calendar = sorted({str(bar["trade_date"]) for bar in daily_bars})
    # C（代码大）首板；A 不板。若 N=1 取 A（同分代码升序）→ 漏掉 C 的板
    first_board_index = {
        ("600002.SSE", stock_c[32]["trade_date"]): 2,
        ("600002.SSE", stock_c[45]["trade_date"]): 1,
    }
    frame = build_fused_frame(
        daily_bars,
        first_board_index,
        {"600001.SSE": "甲", "600002.SSE": "乙", "000001.SSE": "上证指数"},
        calendar,
        touch_dates_by_symbol={},
        forward_days=3,
        min_history=10,
    )
    top1 = next(row for row in frame["topn"] if row["n"] == 1)
    top2 = next(row for row in frame["topn"] if row["n"] == 2)
    assert top1["boards_captured"] == 0  # 确定性漏板：证明排序确实是分数降序+代码升序
    assert top2["boards_captured"] == 3  # N=2 才把 C 装进来


# ── frame-1 分析 / 敏感性 / 裁决 / 编排 ─────────────────────────────────────


def _rich_samples() -> list[dict[str, object]]:
    """20 个合成样本：分数/类型/标签/子分键齐全（frame-1 分析结构测试用）。"""

    samples: list[dict[str, object]] = []
    for index in range(20):
        leader = index % 2 == 0
        score = round(0.05 * index, 2)
        samples.append(
            _sample(
                "600001.SSE",
                f"2026-0{1 + index % 6}-15",
                is_leader=leader,
                eventual_peak=3 if leader else 1,
                fused_score=score,
                fused_type="lowpos" if index % 3 == 0 else ("wave" if index % 3 == 1 else None),
                lowpos_score=score * 7,
                wave_score=score * 4,
                bias_ma20_pct=float(index),
                **{f"lowpos_{key}": score for key in (
                    "L1_depth", "L2_duration", "L3_converge", "L4_stage",
                    "L5_stabilize", "L6_volume", "L7_recent_touch",
                )},
                **{f"wave_{key}": score for key in (
                    "W1_bull_duration", "W2_pullback", "W3_stabilize", "W4_volume",
                )},
            )
        )
    return samples


def test_frame1_analysis_structure() -> None:
    frame1 = _frame1_analysis(_rich_samples(), {"600001.SSE": "案例甲"})
    assert frame1["qualified_count"] == 19  # 除 index0 外 score>0
    assert len(frame1["auc_rows"]) == 15  # 3 总分 + 11 子分 + bias_ma20
    assert frame1["bucket_outcomes"][0]["bucket"] == "__baseline__"
    assert {row["type"] for row in frame1["type_outcomes"]} == {
        "__baseline__", "lowpos", "wave", "both", "none",
    }
    # 漏网妖股：score=0 且 peak>=3 → 只有 index0
    assert len(frame1["missed_peak3"]) == 1
    assert "monthly" in frame1 and "june_july" in frame1


def test_sensitivity_rows_variants() -> None:
    bars = _bars([10.0 + index * 0.1 for index in range(70)])
    trade_date = str(bars[65]["trade_date"])
    samples = [_sample("600001.SSE", trade_date)]
    rows = _sensitivity_rows(samples, bars, {})
    labels = [row["variant"] for row in rows]
    assert labels == [
        "bear_gate=15(中央)",
        "bear_gate=10",
        "bear_gate=20",
        "purity_window=10",
        "purity_window=30",
        "conv_cap=10",
        "conv_cap=20",
    ]


def test_final_verdicts_pass_and_fail() -> None:
    passing_frame2 = {
        "bucket_monotonicity_spearman": 0.9,
        "buckets": [{}, {}, {}, {}, {}, {"lift": 2.5, "days": 150, "leader_recall": 0.3}],
        "comparisons": [
            {"gate": "L4_stage>=1", "leader_recall": 0.2},
            {"gate": "momentum_ref(bias20>=5)", "leader_recall": 0.4},
        ],
        "monthly": {"monthly_agreement": 0.8, "june_july": {"flipped": False}},
    }
    verdicts = research._final_verdicts({"frame2": passing_frame2})
    assert verdicts["overall_passed"] is True
    assert verdicts["passed_count"] == 4
    # 逐条破坏：单调性不达标 / 顶桶被子分打败 / 6-7 月翻转
    bad_mono = {**passing_frame2, "bucket_monotonicity_spearman": 0.5}
    assert research._final_verdicts({"frame2": bad_mono})["passed_count"] == 3
    bad_recall = {
        **passing_frame2,
        "comparisons": [{"gate": "L4_stage>=1", "leader_recall": 0.5}],
    }
    assert research._final_verdicts({"frame2": bad_recall})["passed_count"] == 3
    bad_flip = {
        **passing_frame2,
        "monthly": {"monthly_agreement": 0.8, "june_july": {"flipped": True}},
    }
    assert research._final_verdicts({"frame2": bad_flip})["passed_count"] == 3


def test_build_fused_report_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    daily_bars, first_board_index, names, calendar = _frame_fixture()
    fake_samples = [
        _sample("600001.SSE", str(bar["trade_date"]), is_leader=(index == 32))
        for index, bar in enumerate(
            [row for row in daily_bars if row["vt_symbol"] == "600001.SSE"][30:36], start=30
        )
    ]
    monkeypatch.setattr(
        research, "build_factor_samples", lambda *args, **kwargs: ({}, fake_samples)
    )
    monkeypatch.setattr(
        research,
        "extract_first_board_samples",
        lambda *args, **kwargs: [
            {"vt_symbol": symbol, "trade_date": day, "eventual_peak": peak}
            for (symbol, day), peak in first_board_index.items()
        ],
    )
    report = build_fused_report(
        [],
        daily_bars,
        calendar,
        [],
        [],
        names,
        purity_events=[],
        forward_days=3,
        min_history=10,
    )
    assert report["status"] == "ok"
    assert report["first_board_count"] == 6
    assert set(report["frame1"]) >= {"auc_rows", "bucket_outcomes", "missed_peak3"}
    assert report["frame2"]["scanned_days"] == 49
    assert len(report["sensitivity"]) == 7
    assert report["final_verdicts"]["passed_count"] is not None
