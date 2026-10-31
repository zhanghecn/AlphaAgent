from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "量化因子研究"
    / "一接二"
    / "scripts"
    / "j12_open9_research.py"
)


def _load_module():
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    spec = importlib.util.spec_from_file_location("j12_open9_research", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trigger_is_first_cent_strictly_above_nine_percent():
    module = _load_module()

    assert module.trigger_9pct(10.00) == pytest.approx(10.91)
    assert module.trigger_9pct(5.50) == pytest.approx(6.00)
    assert module.trigger_9pct(3.65) == pytest.approx(3.98)


def test_entry_buys_at_trigger_when_price_crosses_nine_percent():
    module = _load_module()

    entry = module.open9_entry(open_price=10.20, high_price=10.91, prev_close=10.00)

    assert entry == pytest.approx(10.91)


def test_entry_does_not_require_eventual_limit_up_touch():
    module = _load_module()

    entry = module.open9_entry(open_price=10.20, high_price=10.91, prev_close=10.00)

    assert entry == pytest.approx(10.91)
    assert 10.91 < module.limit_10pct(10.00)


def test_entry_uses_open_when_gap_is_already_above_trigger():
    module = _load_module()

    entry = module.open9_entry(open_price=10.95, high_price=11.00, prev_close=10.00)

    assert entry == pytest.approx(10.95)


def test_entry_rejects_prices_not_above_nine_percent():
    module = _load_module()

    assert module.open9_entry(open_price=10.20, high_price=10.90, prev_close=10.00) is None


def test_entry_rejects_open_at_limit_even_if_it_later_opens():
    module = _load_module()

    assert module.open9_entry(open_price=11.00, high_price=11.00, prev_close=10.00) is None


def _synthetic_bars(module, mode: str) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    dates = pd.bdate_range("2023-01-02", periods=90)
    close = np.linspace(10.0, 10.45, len(dates))
    open_ = np.r_[10.0, close[:-1] * 1.0005]
    bars = pd.DataFrame({
        "vt_symbol": "000001.SZSE",
        "trade_date": dates,
        "open_price": open_,
        "high_price": np.maximum(open_, close) * 1.002,
        "low_price": np.minimum(open_, close) * 0.998,
        "close_price": close,
        "volume": 1000.0,
        "turnover_rate": 5.0,
    })
    p1, buy = 65, 66
    foundation_close = float(bars.at[p1 - 1, "close_price"])
    b1_limit = module.limit_10pct(foundation_close)
    bars.loc[p1, ["open_price", "high_price", "low_price", "close_price"]] = [
        foundation_close * 1.01,
        b1_limit,
        foundation_close,
        b1_limit,
    ]
    bars.loc[p1, ["volume", "turnover_rate"]] = [1500.0, 8.0]

    b1_close = float(bars.at[p1, "close_price"])
    buy_limit = module.limit_10pct(b1_close)
    trigger = module.trigger_9pct(b1_close)
    bars.loc[buy, ["open_price", "high_price", "low_price", "close_price"]] = [
        b1_close * 1.005,
        trigger if mode == "near" else buy_limit,
        b1_close,
        b1_close * 1.04 if mode == "near" else buy_limit,
    ]
    bars.loc[buy, ["volume", "turnover_rate"]] = [2000.0, 10.0]

    if mode == "open_limit":
        bars.loc[buy, ["open_price", "high_price", "low_price", "close_price"]] = [
            buy_limit, buy_limit, b1_close * 1.02, b1_close * 1.05,
        ]
    elif mode == "near":
        next_close = trigger * 1.02
        bars.loc[buy + 1, ["open_price", "high_price", "low_price", "close_price"]] = [
            trigger, next_close, trigger * 0.99, next_close,
        ]
    elif mode in {"sealed", "deep_open"}:
        next_limit = module.limit_10pct(buy_limit)
        bars.loc[buy + 1, ["open_price", "high_price", "low_price", "close_price"]] = [
            buy_limit * 1.01, next_limit, buy_limit, next_limit,
        ]
        if mode == "deep_open":
            bars.loc[buy + 2, ["open_price", "high_price", "low_price", "close_price"]] = [
                next_limit * 0.94, next_limit * 1.01, next_limit * 0.93, next_limit * 0.95,
            ]
        else:
            bars.loc[buy + 2, ["open_price", "high_price", "low_price", "close_price"]] = [
                next_limit * 1.01, next_limit * 1.03, next_limit, next_limit * 1.02,
            ]
    return bars, dates


def test_events_include_nine_percent_near_miss_and_exit_next_day_close():
    module = _load_module()
    bars, dates = _synthetic_bars(module, "near")

    events = module.build_events(bars)

    assert len(events) == 1
    row = events.iloc[0]
    assert row["trade_date"] == dates[66]
    assert row["entry_price"] == pytest.approx(module.trigger_9pct(bars.at[65, "close_price"]))
    assert not row["touched_limit"]
    assert not row["sealed"]
    assert not row["good_board"]
    assert row["exit_date"] == dates[67]
    assert row["e3_pct"] == pytest.approx(2.0)
    assert row["tail_pct"] == pytest.approx(2.0)


def test_events_hold_sealed_board_until_first_break_day_close():
    module = _load_module()
    bars, dates = _synthetic_bars(module, "sealed")

    events = module.build_events(bars)

    assert len(events) == 1
    row = events.iloc[0]
    expected_exit = bars.at[68, "close_price"]
    assert row["sealed"]
    assert row["touched_limit"]
    assert row["good_board"]
    assert row["exit_date"] == dates[68]
    assert row["e3_pct"] == pytest.approx((expected_exit / row["entry_price"] - 1) * 100)


def test_events_exclude_open_at_limit_before_the_day_opens():
    module = _load_module()
    bars, _ = _synthetic_bars(module, "open_limit")

    assert module.build_events(bars).empty


def test_tail_rule_does_not_inherit_deep_open_auction_exit():
    module = _load_module()
    bars, dates = _synthetic_bars(module, "deep_open")

    row = module.build_events(bars).iloc[0]

    assert row["exit_reason"] == "d2_deep_open_sell"
    assert row["exit_price"] == pytest.approx(bars.at[68, "open_price"])
    assert row["tail_exit_date"] == dates[68]
    assert row["tail_exit_price"] == pytest.approx(bars.at[68, "close_price"])
    assert row["tail_pct"] == pytest.approx((bars.at[68, "close_price"] / row["entry_price"] - 1) * 100)


def test_events_export_entry_known_j12_and_hpr_features():
    module = _load_module()
    bars, _ = _synthetic_bars(module, "sealed")

    row = module.build_events(bars).iloc[0]

    assert row["b1_open"] == pytest.approx(1.0)
    assert row["b1_turn"] == pytest.approx(8.0)
    assert row["today_open"] == pytest.approx(0.5)
    assert row["second_turn"] == pytest.approx(10.0)
    assert row["foundation_turn"] == pytest.approx(5.0)
    assert row["b1_turn_change"] == pytest.approx(3.0)
    assert row["b1_volume_ratio"] == pytest.approx(1.5)
    assert row["b1_vol_rel5"] == pytest.approx(1500 / 1100)
    expected_gap = (bars.at[65, "high_price"] - bars.at[65, "low_price"]) / bars.at[64, "close_price"] * 100
    assert row["b1_gap"] == pytest.approx(expected_gap)
    assert row["b1_break60"]
    assert row["lim_cnt60"] == 0
    assert row["max_streak60"] == 0
    assert row["prev_wave60"] == 0
    assert row["listing_age"] == 65
    assert pd.notna(row["pre5_pct"])
    assert pd.notna(row["pre10_pct"])
    assert pd.notna(row["pre20_pct"])
    assert pd.notna(row["pre60_pct"])
    assert row["foundation_pose"] in {"站线上", "骑线", "贴线", "掉线下"}
