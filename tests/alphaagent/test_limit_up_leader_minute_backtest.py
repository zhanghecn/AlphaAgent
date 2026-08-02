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


def test_simulate_min_trigger_volume_ratio_filter() -> None:
    # 触发 bar 缩量（量比 <0.94）→ 被触发量能硬滤跳过
    quiet_window = [
        {"bar_time": "09:31:00", "close_price": 10.1, "open_price": 10.1, "high_price": 10.1, "low_price": 10.1, "volume": 4.0e6},
        {"bar_time": "09:32:00", "close_price": 10.4, "open_price": 10.4, "high_price": 10.4, "low_price": 10.4, "volume": 1.0e6},
    ]
    minute_map = {date(2026, 7, 28): {SYMBOL: quiet_window}}
    bars_by_symbol, daily_index, names = _world()
    result = engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names=names,
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
        min_trigger_volume_ratio=0.94,
    )
    assert result["closed_trades"] == []
    assert result["coverage_stats"]["trigger_count"] == 0
    # 不滤则正常触发买入
    result_unfiltered = engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names=names,
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
    )
    assert result_unfiltered["coverage_stats"]["trigger_count"] == 1


# ── 扫板入场（触板/开板成交模型）──────────────────────────────────────


def _day_bar(bar_time: str, high: float, low: float, close: float) -> dict:
    return {
        "bar_time": bar_time,
        "open_price": close,
        "high_price": high,
        "low_price": low,
        "close_price": close,
        "volume": 1.0e6,
    }


def test_sweep_entry_fills_at_limit_on_open() -> None:
    # 10:05 触板（high 11.0=涨停价），10:20 开板（low 10.7<11.0）→ 按涨停价 11.0 成交
    bars = [
        _day_bar("09:31:00", 10.3, 10.0, 10.1),
        _day_bar("10:05:00", 11.0, 10.8, 11.0),  # 触板 bar（自身不算开板）
        _day_bar("10:06:00", 11.0, 11.0, 11.0),  # 封住
        _day_bar("10:20:00", 11.0, 10.7, 10.75),  # 开板！
        _day_bar("10:25:00", 11.0, 10.9, 11.0),
    ]
    entry = engine._sweep_entry(bars, prev_close=10.0)
    assert entry is not None
    assert entry["buy_price"] == 11.0  # 排板成交价=涨停价
    assert entry["buy_time"] == "10:20:00"
    assert entry["touch_time"] == "10:05:00"


def test_sweep_entry_no_fill_when_never_opens() -> None:
    # 触板后全天封死 → 买不到
    bars = [
        _day_bar("09:31:00", 10.5, 10.0, 10.3),
        _day_bar("09:40:00", 11.0, 10.95, 11.0),  # 触板
        _day_bar("10:00:00", 11.0, 11.0, 11.0),
        _day_bar("14:00:00", 11.0, 11.0, 11.0),
    ]
    assert engine._sweep_entry(bars, prev_close=10.0) is None
    status, entry = engine._sweep_entry_status(bars, prev_close=10.0)
    assert status == "no_open" and entry is None


def test_sweep_entry_no_touch() -> None:
    bars = [_day_bar("09:31:00", 10.5, 10.0, 10.3), _day_bar("14:00:00", 10.6, 10.2, 10.4)]
    status, entry = engine._sweep_entry_status(bars, prev_close=10.0)
    assert status == "no_touch" and entry is None


def test_sweep_entry_touch_bar_itself_not_open() -> None:
    # 触板 bar 内 low 也跌破（bar 内先后不可知）→ 保守等下一根开板
    bars = [
        _day_bar("10:05:00", 11.0, 10.6, 10.8),  # 触板 bar 内也曾下探，自身不算开板
        _day_bar("10:06:00", 11.0, 11.0, 11.0),
    ]
    assert engine._sweep_entry(bars, prev_close=10.0) is None


def test_sweep_entry_max_entry_time() -> None:
    bars = [
        _day_bar("10:05:00", 11.0, 10.9, 11.0),  # 触板
        _day_bar("14:30:00", 11.0, 10.8, 10.85),  # 开板但晚于 14:00
    ]
    assert engine._sweep_entry(bars, prev_close=10.0, max_entry_time="14:00:00") is None
    assert engine._sweep_entry(bars, prev_close=10.0, max_entry_time="14:35:00") is not None


def test_simulate_sweep_board_end_to_end() -> None:
    # 全日分钟 bar：09:40 触板、10:20 开板 → 扫板买入，D+1 高开留仓
    sweep_window = [
        _day_bar("09:31:00", 10.3, 10.0, 10.1),
        _day_bar("09:40:00", 11.0, 10.9, 11.0),  # 触板
        _day_bar("09:41:00", 11.0, 11.0, 11.0),
        _day_bar("10:20:00", 11.0, 10.7, 10.75),  # 开板 → 11.0 成交
        _day_bar("10:30:00", 11.0, 10.9, 11.0),  # 回封
        _day_bar("15:00:00", 11.0, 11.0, 11.0),
    ]
    minute_map = {date(2026, 7, 28): {SYMBOL: sweep_window}}
    bars_by_symbol, daily_index, names = _world()
    result = engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names=names,
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
        entry_mode="sweep_board",
    )
    trades = result["closed_trades"]
    assert len(trades) == 1
    assert abs(trades[0]["buy_price"] - 11.0) < 0.02
    assert trades[0]["buy_time"] == "10:20:00"
    assert result["coverage_stats"]["sweep_filled"] == 1
    # 对照：触板未开板 → 无交易
    sealed_window = [
        _day_bar("09:40:00", 11.0, 10.95, 11.0),
        _day_bar("15:00:00", 11.0, 11.0, 11.0),
    ]
    result2 = engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names=names,
        minute_loader=lambda d: {date(2026, 7, 28): {SYMBOL: sealed_window}}.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
        entry_mode="sweep_board",
    )
    assert result2["closed_trades"] == []
    assert result2["coverage_stats"]["sweep_no_open"] == 1


def test_main_saves_sweep_to_sweep_table(monkeypatch) -> None:
    saved: dict[str, object] = {}
    monkeypatch.setattr(engine, "run_minute_backtest", lambda **kwargs: {"ok": True})
    import alphaagent.server.services.limit_up.leader_sweep_repository as sweep_repo

    # save_minute_backtest_run 是引擎模块顶层导入，patch 引擎命名空间
    monkeypatch.setattr(engine, "save_minute_backtest_run", lambda v, r: saved.update(minute=(v, r)))
    monkeypatch.setattr(sweep_repo, "save_sweep_backtest_run", lambda v, r: saved.update(sweep=(v, r)))
    # 扫板 → 扫板表
    engine.main(["--start", "2026-07-01", "--end", "2026-07-31", "--entry-mode", "sweep_board"])
    assert "sweep" in saved and "minute" not in saved
    # 分钟级 → 分钟级表
    saved.clear()
    engine.main(["--start", "2026-07-01", "--end", "2026-07-31"])
    assert "minute" in saved and "sweep" not in saved


def test_sweep_entry_weak_touch_bar_rejected() -> None:
    # 触板 bar 收在 bar 下半部（high 11.0/low 10.5/close 10.6 → 位置 0.2 < 0.57）→ 放弃
    bars = [
        _day_bar("10:05:00", 11.0, 10.5, 10.6),  # 触板但收弱势
        _day_bar("10:20:00", 10.8, 10.6, 10.7),
    ]
    status, entry = engine._sweep_entry_status(
        bars, prev_close=10.0, min_touch_bar_close_position=0.57
    )
    assert status == "weak_touch" and entry is None
    # 不设阈值则正常触板→开板成交
    status2, entry2 = engine._sweep_entry_status(bars, prev_close=10.0)
    assert status2 == "filled" and entry2 is not None
    # 触板 bar 收强势（close 11.0 位置 1.0）→ 通过
    strong = [
        _day_bar("10:05:00", 11.0, 10.5, 11.0),
        _day_bar("10:20:00", 11.0, 10.6, 10.7),
    ]
    status3, entry3 = engine._sweep_entry_status(
        strong, prev_close=10.0, min_touch_bar_close_position=0.57
    )
    assert status3 == "filled" and entry3 is not None


def test_index_ma20_gate_logic() -> None:
    # 20 根收盘 10.0 + D-1 收盘 9.0（< MA20≈9.95）→ 门拦下
    rows = [{"trade_date": f"2026-06-{i+1:02d}", "close_price": 10.0} for i in range(20)]
    rows.append({"trade_date": "2026-06-21", "close_price": 9.0})
    idx = {engine.INDEX_VT_SYMBOL: rows}
    assert engine._index_above_ma20(idx, "2026-06-21") is False
    # D-1 收盘 10.1（≥ MA20）→ 放行
    rows[-1]["close_price"] = 10.1
    assert engine._index_above_ma20(idx, "2026-06-21") is True
    # 数据不足 20 根 → 默认放行
    assert engine._index_above_ma20({engine.INDEX_VT_SYMBOL: rows[:5]}, "2026-06-05") is True
    # prev_day 之后的行不可见（无未来函数）
    rows2 = [{"trade_date": "2026-06-10", "close_price": 5.0}] + rows[:20]
    idx2 = {engine.INDEX_VT_SYMBOL: rows2}
    assert engine._index_above_ma20(idx2, "2026-06-09") is True  # 5.0 在 06-09 之后不可见


# ── 前奏形态因子（prelude pattern，默认只 dump 观察）─────────────────────


def _rows_with_closes(closes, d_open=10.1, d_close=10.5, d1_open=10.6, d1_close=10.7):
    """按 closes 构造历史日线（change_pct 由 closes 自算）+ D 日 + D+1 日。"""
    rows = []
    prev = None
    for td, c in zip(HIST_DATES, closes, strict=True):
        change = round((c / prev - 1) * 100, 4) if prev else 0.0
        rows.append(_bar(SYMBOL, td, c, c, change_pct=change))
        prev = c
    rows.append(_bar(SYMBOL, BUY_DAY, d_open, d_close, high=max(d_open, d_close)))
    rows.append(_bar(SYMBOL, SELL_DAY, d1_open, d1_close))
    return rows


def _run_rows(rows, minute_map, **simulate_kwargs):
    bars_by_symbol = {SYMBOL: rows}
    daily_index = {(SYMBOL, str(b["trade_date"])): b for b in rows}
    return engine.simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=CALENDAR,
        names={SYMBOL: "浦发银行"},
        minute_loader=lambda d: minute_map.get(d, {}),
        config=CashBacktestConfig(max_positions=3),
        min_day_coverage=1,
        **simulate_kwargs,
    )


def test_d1_factors_include_prelude_features() -> None:
    rows = _daily_rows()  # 渐变小阳（每日 ~2.2%）→ 最后 3 根全小阳
    factors = engine._d1_factors(rows[:7], BUY_DAY)
    assert factors["prelude_pattern"] == "small_yang"
    assert factors["prelude_small_yang_streak"] == 3
    assert factors["prelude_small_yin_streak"] == 0
    # 历史仅 6 根 < 10 → 量能特征为 None
    assert factors["prelude_vol_cv_7d"] is None
    assert factors["prelude_vol_shift_ratio"] is None


def test_simulate_prelude_any_keeps_pattern_stock() -> None:
    # 默认渐变历史 = 小阳 streak 3 → require=any 正常买入
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run_rows(_daily_rows(), minute_map, require_prelude_pattern="any")
    assert len(result["closed_trades"]) == 1
    assert result["coverage_stats"]["candidates_skipped_prelude"] == 0


def test_simulate_prelude_any_skips_no_pattern() -> None:
    # D-2 涨 4.17%（>3 打断）、D-1 跌 3.0%（小阴 streak=1）→ 无形态
    closes = [9.0, 9.2, 9.4, 9.6, 10.0, 9.7]
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    result = _run_rows(_rows_with_closes(closes), minute_map, require_prelude_pattern="any")
    assert result["closed_trades"] == []
    assert result["coverage_stats"]["candidates_skipped_prelude"] >= 1
    # 对照：不启用硬滤则正常买入
    result_off = _run_rows(_rows_with_closes(closes), minute_map)
    assert len(result_off["closed_trades"]) == 1


def test_simulate_prelude_small_yang_rejects_yin_stock() -> None:
    # D-2 -2.08%、D-1 -1.06% → 小阴 streak=2（small_yin）；涨停价 9.3×1.1=10.23
    closes = [9.0, 9.2, 9.4, 9.6, 9.4, 9.3]
    rows = _rows_with_closes(closes, d_open=9.4, d_close=9.7, d1_open=9.8, d1_close=9.9)
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 9.4), ("09:32:00", 9.6)])}}
    rejected = _run_rows(rows, minute_map, require_prelude_pattern="small_yang")
    assert rejected["closed_trades"] == []
    assert rejected["coverage_stats"]["candidates_skipped_prelude"] >= 1
    accepted = _run_rows(rows, minute_map, require_prelude_pattern="small_yin")
    assert len(accepted["closed_trades"]) == 1


def test_prelude_factors_join_calibration_pool(monkeypatch) -> None:
    captured = {}

    def fake_calib(train, month, **kwargs):
        captured["factors"] = tuple(kwargs.get("candidate_factors") or ())
        return None

    monkeypatch.setattr(engine, "_build_month_calibration", fake_calib)
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    _run_rows(
        _daily_rows(),
        minute_map,
        candidate_factors=("return_20d_pct",),
        include_prelude_factors_in_calibration=True,
    )
    for key in engine.PRELUDE_CALIBRATION_FEATURES:
        assert key in captured["factors"]


def test_prelude_mode_validation() -> None:
    minute_map = {date(2026, 7, 28): {SYMBOL: _window([("09:31:00", 10.1), ("09:32:00", 10.4)])}}
    try:
        _run_rows(_daily_rows(), minute_map, require_prelude_pattern="bogus")
        raise AssertionError("should raise")
    except ValueError:
        pass


# ── 主人版低位（owner_low_position，锚点校准 2026-08-02）─────────────────────


def _lowpos_bars(high_close=15.0, low_close=10.0, n=130):
    """前段高位后段贴底的 130 根日线（position/drawdown/rebound 由窗口自算）。"""
    rows = []
    for i in range(n):
        close = high_close if i < n - 30 else low_close
        rows.append(
            {
                "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "close_price": close,
                "high_price": close,
                "low_price": close,
                "turnover": 1.0e8,
                "change_pct": 0.0,
            }
        )
    return rows


def test_owner_low_position_anchor_semantics() -> None:
    # 贴底（立新能源型）：drawdown=-33%、rebound=0、ret5d=0 → 低位
    assert engine._is_owner_low_position(_lowpos_bars()) is True
    # 高位（至纯 07-10 型）：半年区间顶部、反弹巨大 → 非低位
    high_rows = _lowpos_bars(high_close=8.0, low_close=13.0)
    assert engine._is_owner_low_position(high_rows) is False
    # 中位（至纯 07-10 型）：高 15 → 低 10 → 反弹到 12.5（dd -17% 不够深）
    mid_rows = []
    for i in range(130):
        close = 15.0 if i < 70 else (10.0 if i < 100 else 12.5)
        mid_rows.append(
            {
                "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "close_price": close,
                "high_price": close,
                "low_price": close,
                "turnover": 1.0e8,
                "change_pct": 0.0,
            }
        )
    assert engine._is_owner_low_position(mid_rows) is False


def test_owner_low_position_rejects_v_shape_rebound() -> None:
    """至纯 07-31 型：跌得够深但已急反弹（reb>12% 且 ret5d>6%）→ 非低位。"""

    rows = []
    for i in range(130):
        if i < 60:
            close = 40.0  # 126 日高点
        elif i < 120:
            close = 22.0  # 深跌到 22（dd -45%）
        else:
            close = 25.5  # 近 5 日急反弹至 25.5（reb +15.9%、ret5d +15.9%）
        rows.append(
            {
                "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "close_price": close,
                "high_price": close,
                "low_price": close,
                "turnover": 1.0e8,
                "change_pct": 0.0,
            }
        )
    assert engine._is_owner_low_position(rows) is False
    # 对照：同样深跌但反弹温和（reb +4.5%、ret5d 平）→ 低位
    for row in rows[120:]:
        row["close_price"] = row["high_price"] = row["low_price"] = 23.0
    assert engine._is_owner_low_position(rows) is True


def test_owner_low_position_rejects_volatile_bottom() -> None:
    """至纯 07-31 型（变体）：贴底但近 20 日剧烈震荡（振幅>40%）→ 非低位。"""

    # dd=-30.4% ✓、reb=+2.6% ✓、ret5d=+2.6% ✓，仅近 20 日振幅 (27-19)/19=42% 超标
    closes = [28.0] * 100 + [19.0] * 15 + [27.0, 19.5, 20.0, 19.0, 19.5, 19.2, 19.0, 19.1, 19.0, 19.5]
    rows = [
        {
            "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "close_price": close,
            "high_price": close,
            "low_price": close,
            "turnover": 1.0e8,
            "change_pct": 0.0,
        }
        for i, close in enumerate(closes)
    ]
    assert engine._is_owner_low_position(rows) is False
    # 对照：后 20 日横盘（振幅 2.6%）→ 低位
    closes2 = [28.0] * 100 + [19.0] * 15 + [19.5] * 15
    rows2 = [
        {
            "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "close_price": close,
            "high_price": close,
            "low_price": close,
            "turnover": 1.0e8,
            "change_pct": 0.0,
        }
        for i, close in enumerate(closes2)
    ]
    assert engine._is_owner_low_position(rows2) is True


def test_owner_low_position_rebound_path() -> None:
    # rebound 路径：position 略高（0.3）但距低点反弹 ≤12% → 低位
    rows = []
    for i in range(130):
        if i < 70:
            close = 15.0  # 126 日高点区
        elif i < 100:
            close = 10.0  # 126 日低点
        else:
            close = 11.0  # 反弹 10%（≤12%）→ rebound 路径成立
        rows.append(
            {
                "trade_date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                "close_price": close,
                "high_price": close,
                "low_price": close,
                "turnover": 1.0e8,
                "change_pct": 0.0,
            }
        )
    assert engine._is_owner_low_position(rows) is True
    # 反弹 30%（>12%）且 position 0.5 → 非低位
    for row in rows[100:]:
        row["close_price"] = row["high_price"] = row["low_price"] = 13.0
    assert engine._is_owner_low_position(rows) is False
