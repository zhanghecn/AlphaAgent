"""Tests for the all-market minute backtest (v2, no look-ahead)."""

from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig
from alphaagent.server.services.limit_up import leader_minute_backtest as engine

SYMBOL = "600000.SSE"
HIST_DATES = [
    "2026-07-20",
    "2026-07-21",
    "2026-07-22",
    "2026-07-23",
    "2026-07-24",
    "2026-07-27",
]
BUY_DAY = "2026-07-28"
SELL_DAY = "2026-07-29"
CALENDAR = HIST_DATES + [BUY_DAY, SELL_DAY]


def _bar(symbol, trade_date, open_, close, high=None, low=None, turnover=1.0e8, turnover_rate=5.0, change_pct=0.0):
    return {
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "open_price": open_,
        "close_price": close,
        "high_price": high if high is not None else max(open_, close),
        "low_price": low if low is not None else min(open_, close),
        "volume": 1.0e6,
        "turnover": turnover,
        "turnover_rate": turnover_rate,
        "change_pct": change_pct,
    }


def _daily_rows(symbol=SYMBOL, prev_close=10.0, d_open=10.1, d_close=10.5, d1_open=10.6, d1_close=10.7):
    """6 根历史（D-6..D-1，收盘 9.0→prev_close）+ D 日 + D+1 日。"""
    closes = [9.0, 9.2, 9.4, 9.6, 9.8, prev_close]
    rows = []
    prev_c = None
    for td, c in zip(HIST_DATES, closes):
        change = round((c / prev_c - 1) * 100, 4) if prev_c else 0.0
        rows.append(_bar(symbol, td, c, c, change_pct=change))
        prev_c = c
    rows.append(_bar(symbol, BUY_DAY, d_open, d_close, high=max(d_open, d_close, 10.6)))
    rows.append(_bar(symbol, SELL_DAY, d1_open, d1_close))
    return rows


def _world(symbol=SYMBOL, name="浦发银行", **kwargs):
    rows = _daily_rows(symbol, **kwargs)
    bars_by_symbol = {symbol: rows}
    daily_index = {(symbol, str(b["trade_date"])): b for b in rows}
    return bars_by_symbol, daily_index, {symbol: name}


def _window(closes):
    """closes: [(HH:MM:SS, close)] 的窗口分钟 bar。"""
    return [
        {"bar_time": t, "close_price": c, "open_price": c, "high_price": c, "low_price": c}
        for t, c in closes
    ]


def _run(minute_map, symbol=SYMBOL, min_day_coverage=1, **world_kwargs):
    bars_by_symbol, daily_index, names = _world(symbol=symbol, **world_kwargs)
    return engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names=names,
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=min_day_coverage,
    )


# ── _trigger_buy 纯函数 ──────────────────────────────────────────────


def test_trigger_on_surge() -> None:
    # 9:31=10.1, 9:32=10.4 → surge 2.97% ≥2%，10.4 < 涨停 11.0 → 买入
    result = engine._trigger_buy(
        _window([("09:31:00", 10.1), ("09:32:00", 10.4)]),
        open_price=10.1, prev_close=10.0,
        surge_pct=2.0, cum_pct=7.0,
        window_start="09:31:00", window_end="09:40:00",
    )
    assert result is not None
    assert result["buy_price"] == 10.4
    assert result["buy_time"] == "09:32:00"


def test_trigger_on_cum_with_tiny_surges() -> None:
    # 每步 surge<2%，但 cum 累积到 7.2% → cum 触发
    result = engine._trigger_buy(
        _window([("09:31:00", 10.18), ("09:32:00", 10.36), ("09:33:00", 10.54), ("09:34:00", 10.72)]),
        open_price=10.0, prev_close=10.0,
        surge_pct=2.0, cum_pct=7.0,
        window_start="09:31:00", window_end="09:40:00",
    )
    assert result is not None
    assert result["buy_time"] == "09:34:00"


def test_trigger_skipped_when_bar_close_at_limit() -> None:
    # 触发 bar close 已到涨停价 11.0（当时已封板，价格可观测）→ 买不到
    result = engine._trigger_buy(
        _window([("09:31:00", 10.5), ("09:32:00", 11.0)]),
        open_price=10.1, prev_close=10.0,
        surge_pct=2.0, cum_pct=7.0,
        window_start="09:31:00", window_end="09:40:00",
    )
    assert result is None


def test_trigger_skipped_for_one_word_board() -> None:
    # 开盘价 = 涨停价（一字板）→ 买不到
    result = engine._trigger_buy(
        _window([("09:31:00", 11.0), ("09:32:00", 11.0)]),
        open_price=11.0, prev_close=10.0,
        surge_pct=2.0, cum_pct=7.0,
        window_start="09:31:00", window_end="09:40:00",
    )
    assert result is None


def test_no_trigger_when_flat() -> None:
    result = engine._trigger_buy(
        _window([("09:31:00", 10.1), ("09:32:00", 10.15), ("09:33:00", 10.2)]),
        open_price=10.1, prev_close=10.0,
        surge_pct=2.0, cum_pct=7.0,
        window_start="09:31:00", window_end="09:40:00",
    )
    assert result is None


# ── _d1_factors：只用 D-1 及更早 ──────────────────────────────────────


def test_d1_factors_use_only_prior_bars() -> None:
    rows = _daily_rows()  # 6 历史 + D + D+1
    factors = engine._d1_factors(rows[:7], BUY_DAY)  # bars_up_to_d = D-6..D
    assert factors is not None
    assert abs(factors["prior_return_5d_pct"] - 11.1111) < 0.01
    assert factors["prior_3d_up_days"] == 3
    assert abs(factors["prior_turnover_ratio_5d"] - 1.0) < 0.01
    assert abs(factors["float_market_cap"] - 2.0e9) < 1.0
    # 渐变无涨停 → 涨停基因为 0
    assert factors["prior_limit_count_126"] == 0
    assert factors["prior_limit_count_20"] == 0
    assert factors["days_since_prior_limit"] is None


def test_d1_factors_change_with_d1_but_not_prefix() -> None:
    rows = _daily_rows()
    bars_up_to_d = rows[:7]
    base = engine._d1_factors(bars_up_to_d, BUY_DAY)
    # 改 D-1（倒数第二根）→ 因子变化
    mutated = [dict(b) for b in bars_up_to_d]
    mutated[-2] = dict(mutated[-2], close_price=11.0)
    changed = engine._d1_factors(mutated, BUY_DAY)
    assert changed["prior_return_5d_pct"] != base["prior_return_5d_pct"]
    # 改 D 日（最后一根，不进因子）→ 因子不变
    mutated_d = [dict(b) for b in bars_up_to_d]
    mutated_d[-1] = dict(mutated_d[-1], close_price=99.0)
    same = engine._d1_factors(mutated_d, BUY_DAY)
    assert same["prior_return_5d_pct"] == base["prior_return_5d_pct"]
    assert same["prior_limit_count_126"] == base["prior_limit_count_126"]


# ── 校准只用之前完整月 ────────────────────────────────────────────────


def test_calibration_excludes_same_month_and_unlabeled(monkeypatch) -> None:
    captured = {}

    def fake_build(train, factors, **kwargs):
        captured["train"] = list(train)
        return {"factors": {"x": {}}, "buckets": 5}

    monkeypatch.setattr(engine, "build_calibration", fake_build)
    samples = [
        {"month": "2026-05", "is_leader": True},
        {"month": "2026-06", "is_leader": False},
        {"month": "2026-06", "is_leader": True},
        {"month": "2026-06", "is_leader": None},  # 未标答 → 排除
    ]
    engine._build_month_calibration(samples, "2026-06", min_train_samples=1, min_effect=4.0)
    assert [s["month"] for s in captured["train"]] == ["2026-05"]


# ── simulate 集成：全市场触发 + 过滤 ──────────────────────────────────


def test_simulate_buys_on_trigger() -> None:
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run(minute_map)
    trades = result["closed_trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert abs(trade["buy_price"] - 10.4) < 0.02
    assert trade["buy_time"] == "09:32:00"
    assert trade["exit_date"] == SELL_DAY
    # paper 标签已结算（D+1 卖出后 is_leader 有值）
    assert result["coverage_stats"]["train_samples_labeled"] >= 1


def test_simulate_skips_sparse_coverage_day() -> None:
    # 分钟覆盖只有 1 只 < 阈值 2 → 整日不交易
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run(minute_map, min_day_coverage=2)
    assert result["closed_trades"] == []
    assert result["coverage_stats"]["days_skipped_low_coverage"] >= 1


def test_simulate_skips_non_main_board() -> None:
    symbol = "300001.SZSE"  # 创业板（20cm），不在主板范围
    minute_map = {date(2026, 7, 28): {symbol: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run(minute_map, symbol=symbol, name="测试股")
    assert result["closed_trades"] == []


def test_simulate_skips_st_stock() -> None:
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run(minute_map, name="ST测试")
    assert result["closed_trades"] == []


def test_simulate_skips_sealed_at_trigger() -> None:
    # 触发 bar close = 涨停价 11.0 → 当时已封板，买不到
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.5), ("09:32:00", 11.0)])}}
    result = _run(minute_map)
    assert result["closed_trades"] == []


# ── 首板 / 低位过滤 + 涨停基因（v3 核心）────────────────────────────────


def test_d1_factors_limit_gene() -> None:
    # 历史含一次涨停（D-1 涨停）→ 涨停基因计数正确
    closes = [9.0, 9.0, 9.0, 9.0, 9.0, 10.0]  # D-1=10.0 vs D-2=9.0（11.1% 涨停）
    rows = [_bar(SYMBOL, td, c, c) for td, c in zip(HIST_DATES, closes)]
    rows.append(_bar(SYMBOL, BUY_DAY, 10.1, 10.5))
    factors = engine._d1_factors(rows[:7], BUY_DAY)
    assert factors["prior_limit_count_126"] == 1
    assert factors["prior_limit_count_20"] == 1
    assert factors["days_since_prior_limit"] == 0  # D-1 就是涨停日


def test_simulate_skips_non_first_board() -> None:
    # D-1 已涨停（连板延续，非首板）→ 首板过滤排除
    closes = [9.0, 9.0, 9.0, 9.0, 9.0, 10.0]  # D-1=10.0 vs D-2=9.0（涨停）
    rows = [_bar(SYMBOL, td, c, c) for td, c in zip(HIST_DATES, closes)]
    rows.append(_bar(SYMBOL, BUY_DAY, 10.1, 10.5, high=10.6))
    rows.append(_bar(SYMBOL, SELL_DAY, 10.6, 10.7))
    bars_by_symbol = {SYMBOL: rows}
    daily_index = {(SYMBOL, str(b["trade_date"])): b for b in rows}
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names={SYMBOL: "测试"},
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
    )
    assert result["closed_trades"] == []


def test_simulate_skips_high_position() -> None:
    # 前20日累计涨幅 >10%（高位追涨）→ 低位过滤排除（首板仍成立）
    hist_dates = [(date(2026, 6, 1) + timedelta(days=i)).isoformat() for i in range(25)]
    closes = [9.0] * 5 + [10.0] * 18 + [10.4, 10.5]  # D-21=9.0, D-1=10.5（前20日16.7%）；D-1/D-2 不涨停
    rows = [_bar(SYMBOL, td, c, c) for td, c in zip(hist_dates, closes)]
    buy_day = "2026-06-26"
    sell_day = "2026-06-27"
    rows.append(_bar(SYMBOL, buy_day, 10.6, 11.0))
    rows.append(_bar(SYMBOL, sell_day, 11.0, 11.1))
    calendar = hist_dates + [buy_day, sell_day]
    bars_by_symbol = {SYMBOL: rows}
    daily_index = {(SYMBOL, str(b["trade_date"])): b for b in rows}
    minute_map = {date(2026, 6, 26): {SYMBOL: _window([("09:31:00", 10.6), ("09:32:00", 10.9)])}}
    result = engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=calendar,
        names={SYMBOL: "测试"},
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
    )
    assert result["closed_trades"] == []


# ── v4：位置过滤 A/B + 滞后温度门 + 板块动量查找 ──────────────────────


def _long_bars(closes: list[float]) -> list[dict]:
    dates = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(len(closes))]
    rows = []
    prev = None
    for td, close in zip(dates, closes, strict=True):
        change = round((close / prev - 1) * 100, 4) if prev else 0.0
        rows.append(_bar(SYMBOL, td, close, close, change_pct=change))
        prev = close
    return rows


def test_position_filter_low_position_mode() -> None:
    bars = _long_bars([9.0] * 21 + [10.5])  # return_20d = 16.7% > 10%
    assert engine._position_filter_pass(bars, "low_position", 10.0, None) is False
    assert engine._position_filter_pass(bars, "none", 10.0, None) is True


def test_position_filter_deep_drop_excludes_return_20d() -> None:
    bars = _long_bars([10.0] * 21 + [9.0])  # return_20d = -10% ≤ -8.5% → 深跌
    assert engine._position_filter_pass(bars, "deep_drop_exclusion", 10.0, None) is False
    # 板块爆发豁免（concept_r20 ≥ 16.5）
    assert engine._position_filter_pass(bars, "deep_drop_exclusion", 10.0, 20.0) is True
    # 温和回调不排除
    bars_ok = _long_bars([10.0] * 21 + [9.5])  # return_20d = -5%
    assert engine._position_filter_pass(bars_ok, "deep_drop_exclusion", 10.0, None) is True


def test_position_filter_deep_drop_excludes_drawdown_126d() -> None:
    # 126 窗口内高点 13.0 → 现值 10.0，回撤 -23% ≤ -21% → 深跌（13.0 须在窗口内）
    closes = [9.0, 13.0] + [10.0] * 125
    bars = _long_bars(closes)
    assert engine._position_filter_pass(bars, "deep_drop_exclusion", 10.0, None) is False
    assert engine._position_filter_pass(bars, "deep_drop_exclusion", 10.0, 18.0) is True


def test_build_first_board_counts_symbol_aware_ratio() -> None:
    main = [
        _bar("600001.SSE", "2026-07-27", 10.0, 10.0),
        _bar("600001.SSE", "2026-07-28", 10.0, 11.0),  # +10% 主板涨停 → 首板
        _bar("600001.SSE", "2026-07-29", 11.0, 12.1),  # 连板非首板
    ]
    chinext = [
        _bar("300001.SZSE", "2026-07-27", 10.0, 10.0),
        _bar("300001.SZSE", "2026-07-28", 10.0, 11.5),  # +15% 创业板未涨停 → 不算
    ]
    counts = engine.build_first_board_counts({"600001.SSE": main, "300001.SZSE": chinext})
    assert counts.get("2026-07-28") == 1
    assert "2026-07-29" not in counts


def test_build_sector_r20_lookup_uses_prior_closes() -> None:
    memberships = [
        {"vt_symbol": SYMBOL, "sector_id": "BK0001", "sector_type": "concept"}
    ]
    sector_bars = []
    closes = [100.0] * 20 + [110.0, 110.0]  # 22 根；查 07-22 时用其前 21 根收盘
    dates = [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(22)]
    for td, close in zip(dates, closes):
        sector_bars.append(
            {"sector_id": "BK0001", "trade_date": td, "close_price": close, "change_pct": 0.0}
        )
    lookup = engine.build_sector_r20_lookup(memberships, sector_bars)
    # 查询 D 日 = 2026-07-22 → 用严格 D 前收盘：110/100-1 = 10%
    assert lookup(SYMBOL, "2026-07-22") == 10.0
    # 查询首日（无历史收盘）→ None
    assert lookup(SYMBOL, "2026-07-01") is None
    # 非成员票 → None
    assert lookup("600099.SSE", "2026-07-22") is None


def test_simulate_temperature_gate_skips_hot_day() -> None:
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run_temperature(minute_map, lag1_counts={"2026-07-27": 80}, threshold=69.0)
    assert result["closed_trades"] == []
    assert result["coverage_stats"]["days_skipped_hot_market"] == 1


def test_simulate_temperature_gate_allows_cold_day() -> None:
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run_temperature(minute_map, lag1_counts={"2026-07-27": 30}, threshold=69.0)
    assert len(result["closed_trades"]) == 1
    assert result["coverage_stats"]["days_skipped_hot_market"] == 0


def _run_temperature(minute_map, lag1_counts, threshold):
    bars_by_symbol, daily_index, names = _world()
    return engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names=names,
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
        max_lag1_first_board_count=threshold,
        lag1_first_board_counts=lag1_counts,
    )
