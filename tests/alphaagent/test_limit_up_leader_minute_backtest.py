"""Tests for the all-market minute backtest (v2, no look-ahead)."""

from __future__ import annotations

from datetime import date

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


def _bar(symbol, trade_date, open_, close, high=None, low=None, turnover=1.0e8, turnover_rate=5.0):
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
        "change_pct": 0.0,
    }


def _daily_rows(symbol=SYMBOL, prev_close=10.0, d_open=10.1, d_close=10.5, d1_open=10.6, d1_close=10.7):
    """6 根历史（D-6..D-1，收盘 9.0→prev_close）+ D 日 + D+1 日。"""
    closes = [9.0, 9.2, 9.4, 9.6, 9.8, prev_close]
    rows = [
        _bar(symbol, td, c, c) for td, c in zip(HIST_DATES, closes)
    ]
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
    bars = _daily_rows()[:6]  # D-6..D-1（收盘 9.0→10.0）
    factors = engine._d1_factors(bars)
    assert factors is not None
    # 前5日涨幅 = 10.0/9.0 - 1
    assert abs(factors["prior_return_5d_pct"] - 11.1111) < 0.01
    assert factors["prior_3d_up_days"] == 3
    # 前5日量比 = D-1 成交额 / 前5日均成交额 = 1e8/1e8
    assert abs(factors["prior_turnover_ratio_5d"] - 1.0) < 0.01
    # 流通市值 = 成交额/(换手率/100) = 1e8/0.05
    assert abs(factors["float_market_cap"] - 2.0e9) < 1.0


def test_d1_factors_change_with_d1_but_not_prefix() -> None:
    bars = _daily_rows()[:6]
    base = engine._d1_factors(bars)
    # 改 D-1 收盘 → 因子变化
    mutated = [dict(b) for b in bars]
    mutated[-1] = dict(mutated[-1], close_price=11.0)
    changed = engine._d1_factors(mutated)
    assert changed["prior_return_5d_pct"] != base["prior_return_5d_pct"]
    # 改更早的 D-6 之前的历史（前6根不变）→ 因子不变
    older = [_bar(SYMBOL, "2026-07-17", 1.0, 1.0)] + bars
    same = engine._d1_factors(older)
    assert same == base


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
