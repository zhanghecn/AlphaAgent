"""涨停记忆×竞价缺口打板回测测试：触碰记忆窗/臂过滤/T+1 收益/成本/月度。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import alphaagent.server.services.limit_up.recent_touch_auction_backtest as backtest
from alphaagent.server.services.limit_up.recent_touch_auction_backtest import (
    _arm_filter,
    _board_event_map,
    _gap_bucket,
    _had_recent_touch,
    _simulate_hold_exit,
    _touch_positions_by_symbol,
    build_backtest_report,
    generate_entries,
    run_backtest,
    summarize_entries,
)


def _bars(
    rows: list[tuple[str, float, float]],
    *,
    symbol: str = "600001.SSE",
) -> list[dict[str, object]]:
    """(date, open, close) 合成日线；high/low 随 max/min 派生。"""

    return [
        {
            "vt_symbol": symbol,
            "trade_date": day,
            "open_price": open_,
            "close_price": close,
            "high_price": max(open_, close),
            "low_price": min(open_, close),
            "change_pct": 1.0,
            "turnover": 100.0,
        }
        for day, open_, close in rows
    ]


def _day_series(
    start: str, opens_closes: list[tuple[float, float]], *, symbol: str = "600001.SSE"
) -> list[dict[str, object]]:
    base = date.fromisoformat(start)
    return _bars(
        [
            ((base + timedelta(days=index)).isoformat(), open_, close)
            for index, (open_, close) in enumerate(opens_closes)
        ],
        symbol=symbol,
    )


# ── 事件索引 ────────────────────────────────────────────────────────────────


def test_touch_positions_and_lookback_window() -> None:
    calendar = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]
    events = [
        {"event_type": "limit_pool_zt", "vt_symbol": "600001.SSE", "trade_date": "2026-07-01"},
        {"event_type": "limit_pool_zbgc", "vt_symbol": "600001.SSE", "trade_date": "2026-07-01"},
        {"event_type": "other", "vt_symbol": "600001.SSE", "trade_date": "2026-07-03"},
    ]
    touches = _touch_positions_by_symbol(events, calendar)
    assert touches == {"600001.SSE": [0]}  # 同日 zt+zbgc 去重
    assert _had_recent_touch(touches["600001.SSE"], 1, lookback=2) is True
    assert _had_recent_touch(touches["600001.SSE"], 0, lookback=2) is False  # 当日不算
    assert _had_recent_touch(touches["600001.SSE"], 3, lookback=2) is False  # 窗外（隔2日）
    assert _had_recent_touch([], 3, lookback=20) is False


def test_board_event_map_zt_priority() -> None:
    events = [
        {"event_type": "limit_pool_zbgc", "vt_symbol": "600001.SSE", "trade_date": "2026-07-01"},
        {"event_type": "limit_pool_zt", "vt_symbol": "600001.SSE", "trade_date": "2026-07-01"},
        {"event_type": "limit_pool_zbgc", "vt_symbol": "600002.SSE", "trade_date": "2026-07-02"},
    ]
    board = _board_event_map(events)
    assert board[("600001.SSE", "2026-07-01")] == "zt"
    assert board[("600002.SSE", "2026-07-02")] == "zbgc"


# ── 交易条目生成 ─────────────────────────────────────────────────────────────


def _fixture() -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], dict[str, str]]:
    # 600001：5 天，D-1 收 100 → D 开 102（缺口 2%）收 106，D+1 开 107
    stock_a = _day_series(
        "2026-07-01",
        [(98, 99), (99, 100), (102, 106), (107, 108), (108, 109)],
        symbol="600001.SSE",
    )
    # 000002：D 低开（缺口 -2%）
    stock_b = _day_series(
        "2026-07-01",
        [(100, 99), (99, 100), (98, 97), (97, 98), (98, 99)],
        symbol="000002.SZSE",
    )
    daily_bars = stock_a + stock_b
    calendar = sorted({str(bar["trade_date"]) for bar in daily_bars})
    events = [
        # A 在 7-01（首个市场日）封过板 → 后续 20 市场日内有记忆
        {"event_type": "limit_pool_zt", "vt_symbol": "600001.SSE", "trade_date": "2026-07-01", "limit_times": 1},
        # A 在 7-03（买入当天）又封板（结局标签）
        {"event_type": "limit_pool_zt", "vt_symbol": "600001.SSE", "trade_date": "2026-07-03", "limit_times": 1},
    ]
    names = {"600001.SSE": "案例甲", "000002.SZSE": "案例乙"}
    return daily_bars, events, calendar, names


def test_generate_entries_fields_and_window() -> None:
    daily_bars, events, calendar, names = _fixture()
    entries, stats = generate_entries(daily_bars, events, calendar, names)
    # 每股 2 条：index2/3（index1 候选历史不足 2 根、index4 无 D+1 出场）
    assert len(entries) == 4
    entry = next(e for e in entries if e["trade_date"] == "2026-07-03" and e["vt_symbol"] == "600001.SSE")
    assert entry["gap_pct"] == pytest.approx(2.0, abs=1e-3)
    assert entry["recent_touch"] is True  # 7-01 封板在 20 日窗内
    assert entry["ret_intraday_pct"] == pytest.approx((106 / 102 - 1) * 100, abs=1e-3)
    assert entry["ret_t1_pct"] == pytest.approx((107 / 102 - 1) * 100, abs=1e-3)
    assert entry["sealed"] is True and entry["touched"] is True
    # B 票 7-03：无记忆、低开
    entry_b = next(e for e in entries if e["trade_date"] == "2026-07-03" and e["vt_symbol"] == "000002.SZSE")
    assert entry_b["recent_touch"] is False
    assert entry_b["gap_pct"] == pytest.approx(-2.0, abs=1e-3)
    assert stats["dropped_no_exit"] == 2  # 两票各自的最后一日


def test_generate_entries_excludes_d1_limit_days() -> None:
    # D-1 收盘涨停（close >= 前收×1.098）→ 次日不做候选
    stock = _day_series(
        "2026-07-01", [(100, 100), (100, 110.0), (115, 116), (116, 117), (117, 118)]
    )
    calendar = sorted({str(bar["trade_date"]) for bar in stock})
    entries, _ = generate_entries(stock, [], calendar, {"600001.SSE": "案例"})
    days = {str(entry["trade_date"]) for entry in entries}
    assert days == {"2026-07-04"}  # 7-03 因 D-1=7-02 涨停剔除；7-05 无 D+1 出场


def test_entries_no_lookahead_touch_only_past() -> None:
    """未来的触碰不改变过去某日的记忆判定。"""

    daily_bars, events, calendar, names = _fixture()
    before = generate_entries(daily_bars, events, calendar, names)[0]
    future_events = events + [
        {"event_type": "limit_pool_zt", "vt_symbol": "000002.SZSE", "trade_date": "2026-07-05", "limit_times": 1}
    ]
    after = generate_entries(daily_bars, future_events, calendar, names)[0]
    key = lambda e: (e["vt_symbol"], e["trade_date"])
    before_map = {key(e): e["recent_touch"] for e in before}
    after_map = {key(e): e["recent_touch"] for e in after}
    # 000002 票 7-05 的触碰只影响 7-05 之后（样本内没有更晚的交易日了）
    for entry_key, value in before_map.items():
        if entry_key[1] < "2026-07-05":
            assert after_map[entry_key] == value


# ── v2 持有卖出规则（涨停卖一半/不涨停全卖）───────────────────────────────────


def test_hold_exit_seal_halving_sequence() -> None:
    """100 买入 → 110 涨停卖一半 → 121 涨停再卖一半 → 118 未涨停全卖（手算）。"""

    rows = _day_series(
        "2026-07-01", [(100, 100), (101, 110), (111, 121), (119, 118)]
    )
    result = _simulate_hold_exit(rows, 0)
    # proceeds = 0.5×110 + 0.25×121 + 0.25×118 = 55 + 30.25 + 29.5 = 114.75
    assert result["v2_ret_pct"] == pytest.approx(14.75, abs=1e-3)
    assert result["v2_seal_days"] == 2
    assert result["v2_hold_days"] == 3
    assert result["v2_exit_reason"] == "no_seal"
    assert result["v2_exit_date"] == "2026-07-04"


def test_hold_exit_no_seal_sells_all_next_day() -> None:
    rows = _day_series("2026-07-01", [(100, 100), (100, 101)])
    result = _simulate_hold_exit(rows, 0)
    assert result["v2_ret_pct"] == pytest.approx(1.0, abs=1e-3)
    assert result["v2_seal_days"] == 0
    assert result["v2_exit_reason"] == "no_seal"


def test_hold_exit_window_end_censored() -> None:
    """数据耗尽仍涨停：剩余仓位以最后收盘价清仓并标 window_end。"""

    rows = _day_series("2026-07-01", [(100, 100), (101, 110), (111, 121)])
    result = _simulate_hold_exit(rows, 0)
    # 0.5×110 + 0.25×121 + 剩余0.25×121（删失）= 55 + 30.25 + 30.25 = 115.5
    assert result["v2_ret_pct"] == pytest.approx(15.5, abs=1e-3)
    assert result["v2_exit_reason"] == "window_end"


def test_hold_exit_max_hold_cap() -> None:
    """连续 20 日涨停触发 MAX_HOLD_DAYS 强制清仓。"""

    pairs = [(100, 100)]
    price = 100.0
    for _ in range(22):
        price = round(price * 1.1, 2)
        pairs.append((price, price))
    rows = _day_series("2026-07-01", pairs)
    result = _simulate_hold_exit(rows, 0)
    assert result["v2_exit_reason"] == "max_hold"
    assert result["v2_hold_days"] == 20
    assert result["v2_seal_days"] == 20


def test_hold_exit_missing_close_skipped() -> None:
    """缺数据日视同停牌顺延（不判定不卖），恢复后继续走规则。"""

    rows = _day_series("2026-07-01", [(100, 100), (100, 100), (101, 110), (111, 118)])
    rows[1]["close_price"] = None  # D+1 缺收盘
    result = _simulate_hold_exit(rows, 0)
    # D+1 跳过；D+2 的前收(rows[1])也是 None 跳过；D+3：118 < 110×1.098 未涨停全卖
    assert result["v2_ret_pct"] == pytest.approx(18.0, abs=1e-3)
    assert result["v2_hold_days"] == 1
    assert result["v2_exit_reason"] == "no_seal"


# ── 臂过滤 / 汇总 ────────────────────────────────────────────────────────────


def test_arm_filter_membership() -> None:
    params = {"gap_min": 1.0, "gap_max": 4.0, "chase_max": 9.5}
    assert _arm_filter({"gap_pct": 2.0, "recent_touch": True}, **params) == (
        "A_auction_only",
        "B_combo",
    )
    assert _arm_filter({"gap_pct": 2.0, "recent_touch": False}, **params) == ("A_auction_only",)
    assert _arm_filter({"gap_pct": -1.0, "recent_touch": True}, **params) == ("C_touch_no_confirm",)
    assert _arm_filter({"gap_pct": 5.0, "recent_touch": True}, **params) == ("D_chase",)
    assert _arm_filter({"gap_pct": 5.0, "recent_touch": False}, **params) == ()
    assert _arm_filter({"gap_pct": 9.6, "recent_touch": True}, **params) == ()  # 一字买不进


def test_summarize_entries_math_and_cost() -> None:
    entries = [
        {"ret_t1_pct": 2.0, "ret_intraday_pct": 3.0, "sealed": True, "touched": True, "eventual_peak": 3},
        {"ret_t1_pct": -1.0, "ret_intraday_pct": -2.0, "sealed": False, "touched": True, "eventual_peak": 1},
        {"ret_t1_pct": 0.5, "ret_intraday_pct": 0.5, "sealed": False, "touched": False, "eventual_peak": None},
    ]
    summary = summarize_entries(entries, cost_pct=0.2)
    assert summary["trades"] == 3
    assert summary["mean_t1_gross"] == pytest.approx(0.5, abs=1e-4)
    assert summary["mean_t1_net"] == pytest.approx(0.3, abs=1e-4)
    assert summary["win_rate"] == pytest.approx(2 / 3, abs=1e-4)  # 1.8 和 0.3 为正
    assert summary["seal_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert summary["touch_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["peak2_share"] == pytest.approx(0.5, abs=1e-4)  # peak3 一个、peak1 一个
    assert summary["v2_trades"] == 0  # 无 v2 键时优雅为零
    assert summarize_entries([], cost_pct=0.2)["trades"] == 0


def test_gap_bucket_edges() -> None:
    assert _gap_bucket(-0.5) == "-99~0"
    assert _gap_bucket(0.0) == "0~1"
    assert _gap_bucket(1.0) == "1~2"
    assert _gap_bucket(2.0) == "2~4"
    assert _gap_bucket(4.0) == "4~9.5"
    assert _gap_bucket(9.5) == "9.5~999"


# ── 报告编排 ────────────────────────────────────────────────────────────────


def test_build_backtest_report_arms_and_monthly() -> None:
    daily_bars, events, calendar, names = _fixture()
    entries, stats = generate_entries(daily_bars, events, calendar, names)
    report = build_backtest_report(entries, stats, cost_pct=0.2)
    arms = {row["arm"]: row for row in report["arms"]}
    # A 臂：缺口 1-4% → 只有 A 票 7-03（2%）；B 臂同样它（有记忆）
    assert arms["A_auction_only"]["trades"] == 1
    assert arms["B_combo"]["trades"] == 1
    assert arms["B_combo"]["win_rate"] == 1.0  # 4.9%-0.2% 净正
    # v2：7-04 收盘 108 < 106×1.098 未涨停 → 全卖，收益 108/102-1=5.88%
    assert arms["B_combo"]["v2_mean_gross"] == pytest.approx(5.8824, abs=1e-3)
    assert arms["B_combo"]["v2_exit_reasons"] == {"no_seal": 1}
    assert arms["C_touch_no_confirm"]["trades"] == 1  # A 票 7-04 缺口 0.94%<1%
    assert report["trade_days"] == 2
    assert report["combo_month_count"] == 1
    assert report["combo_profitable_months"] == 1
    assert report["combo_profitable_months_v2"] == 1
    assert len(report["touch_gap_gradient"]) == 6


def test_run_backtest_smoke(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    daily_bars, events, calendar, names = _fixture()
    monkeypatch.setattr(
        backtest, "load_limit_up_dataset", lambda *args, **kwargs: {"events": events}
    )
    monkeypatch.setattr(backtest, "load_daily_bars_all", lambda *args, **kwargs: daily_bars)
    monkeypatch.setattr(backtest, "load_stock_names", lambda: names)
    report = run_backtest(start=date(2026, 7, 1), end=date(2026, 7, 5))
    assert report["status"] == "ok"
    assert report["trade_days"] == 2  # 7-03/7-04 有候选（7-02 候选历史不足、7-05 无 D+1）
    arms = {row["arm"]: row for row in report["arms"]}
    assert arms["B_combo"]["trades"] == 1
