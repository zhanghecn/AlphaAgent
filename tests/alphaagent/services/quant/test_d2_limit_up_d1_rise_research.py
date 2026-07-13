from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.quant.d2_limit_up_d1_rise_research import (
    build_event_frame,
    main_board_limit_price,
    summarize_event_frame,
)


TRADING_DAYS = (
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
)


def _bar(
    vt_symbol: str,
    name: str,
    trade_date: date,
    close: float,
    *,
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": name,
        "trade_date": trade_date,
        "open_price": open_price if open_price is not None else close,
        "high_price": high if high is not None else close,
        "low_price": low if low is not None else close,
        "close_price": close,
        "change_pct": None,
    }


def _pattern_rows(
    vt_symbol: str,
    name: str,
    *,
    d2_close: float = 11.0,
    d2_high: float | None = None,
    d1_close: float = 11.5,
    d_open: float = 11.615,
    d_high: float = 12.65,
    d_low: float = 10.925,
    d_close: float = 12.075,
) -> list[dict[str, object]]:
    d3, d2, d1, outcome = TRADING_DAYS
    return [
        _bar(vt_symbol, name, d3, 10.0),
        _bar(vt_symbol, name, d2, d2_close, high=d2_high or d2_close, low=10.0),
        _bar(vt_symbol, name, d1, d1_close, high=max(d1_close, d2_close), low=min(d1_close, d2_close)),
        _bar(
            vt_symbol,
            name,
            outcome,
            d_close,
            open_price=d_open,
            high=d_high,
            low=d_low,
        ),
    ]


def test_selects_only_closed_limit_then_positive_non_limit_main_board_event() -> None:
    rows = [
        *_pattern_rows("600001.SSE", "有效样本"),
        *_pattern_rows("600002.SSE", "仅触板", d2_close=10.8, d2_high=11.0, d1_close=11.2),
        *_pattern_rows("600003.SSE", "次日平盘", d1_close=11.0),
        *_pattern_rows("600004.SSE", "次日再涨停", d1_close=12.1),
        *_pattern_rows("600005.SSE", "*ST样本"),
        *_pattern_rows("300001.SZSE", "创业板样本"),
    ]

    events = build_event_frame(pd.DataFrame(rows))

    assert events["vt_symbol"].tolist() == ["600001.SSE"]
    event = events.iloc[0]
    assert event["d2_date"].date() == date(2026, 1, 6)
    assert event["entry_date"].date() == date(2026, 1, 7)
    assert event["outcome_date"].date() == date(2026, 1, 8)
    assert event["entry_price"] == 11.5
    assert event["d1_return_pct"] == pytest.approx(4.5454545)
    assert event["gross_open_return_pct"] == pytest.approx(1.0)
    assert event["gross_high_return_pct"] == pytest.approx(10.0)
    assert event["gross_low_return_pct"] == pytest.approx(-5.0)
    assert event["gross_close_return_pct"] == pytest.approx(5.0)
    assert event["net_close_return_pct"] == pytest.approx(4.69)
    assert bool(event["outcome_data_valid"]) is True


def test_outcome_prices_do_not_change_signal_membership() -> None:
    winner = pd.DataFrame(_pattern_rows("600001.SSE", "样本"))
    loser = winner.copy()
    outcome_day = pd.Timestamp(TRADING_DAYS[-1])
    outcome_mask = pd.to_datetime(loser["trade_date"]).eq(outcome_day)
    loser.loc[outcome_mask, ["open_price", "high_price", "low_price", "close_price"]] = [10.925, 11.27, 10.35, 10.58]

    winner_events = build_event_frame(winner)
    loser_events = build_event_frame(loser)

    signal_columns = ["vt_symbol", "d2_date", "entry_date", "entry_price", "d1_return_pct"]
    pd.testing.assert_frame_equal(
        winner_events[signal_columns].reset_index(drop=True),
        loser_events[signal_columns].reset_index(drop=True),
    )
    assert winner_events.iloc[0]["gross_close_return_pct"] == pytest.approx(5.0)
    assert loser_events.iloc[0]["gross_close_return_pct"] == pytest.approx(-8.0)

    discontinuity = winner.copy()
    discontinuity.loc[
        pd.to_datetime(discontinuity["trade_date"]).eq(outcome_day),
        ["open_price", "high_price", "low_price", "close_price"],
    ] = [8.5, 8.7, 7.9, 8.05]
    discontinuity_events = build_event_frame(discontinuity)

    assert discontinuity_events["vt_symbol"].tolist() == ["600001.SSE"]
    assert bool(discontinuity_events.iloc[0]["outcome_data_valid"]) is False
    discontinuity_report = summarize_event_frame(discontinuity_events)
    assert discontinuity_report["dataset"]["signal_count"] == 1
    assert discontinuity_report["dataset"]["excluded_outcome_count"] == 1
    assert discontinuity_report["dataset"]["sample_count"] == 0


def test_rejects_pattern_when_stock_skips_an_intervening_market_day() -> None:
    d3, d2, missing_day, entry_day, outcome_day = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
    )
    calendar_rows = [
        _bar("600999.SSE", "交易日锚点", day, 10.0)
        for day in (d3, d2, missing_day, entry_day, outcome_day)
    ]
    suspended_rows = [
        _bar("600001.SSE", "停牌跳日", d3, 10.0),
        _bar("600001.SSE", "停牌跳日", d2, 11.0),
        _bar("600001.SSE", "停牌跳日", entry_day, 11.5),
        _bar("600001.SSE", "停牌跳日", outcome_day, 12.0),
    ]

    events = build_event_frame(pd.DataFrame([*calendar_rows, *suspended_rows]))

    assert events.empty


def test_main_board_limit_price_uses_half_up_cent_rounding() -> None:
    assert main_board_limit_price(6.05) == 6.66
    assert main_board_limit_price(10.0) == 11.0


def test_compounds_equal_weight_daily_returns_after_costs() -> None:
    events = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "name": "甲",
                "entry_date": pd.Timestamp("2026-01-07"),
                "outcome_date": pd.Timestamp("2026-01-08"),
                "d1_return_pct": 3.0,
                "gross_open_return_pct": 2.0,
                "gross_high_return_pct": 12.0,
                "gross_low_return_pct": -2.0,
                "gross_close_return_pct": 10.0,
                "net_close_return_pct": 9.69,
                "market_return_pct": 1.0,
                "excess_close_return_pct": 9.0,
                "d_close_limit_up": True,
            },
            {
                "vt_symbol": "600002.SSE",
                "name": "乙",
                "entry_date": pd.Timestamp("2026-01-07"),
                "outcome_date": pd.Timestamp("2026-01-08"),
                "d1_return_pct": 4.0,
                "gross_open_return_pct": -2.0,
                "gross_high_return_pct": 1.0,
                "gross_low_return_pct": -12.0,
                "gross_close_return_pct": -10.0,
                "net_close_return_pct": -10.31,
                "market_return_pct": 1.0,
                "excess_close_return_pct": -11.0,
                "d_close_limit_up": False,
            },
            {
                "vt_symbol": "600003.SSE",
                "name": "丙",
                "entry_date": pd.Timestamp("2026-01-08"),
                "outcome_date": pd.Timestamp("2026-01-09"),
                "d1_return_pct": 5.0,
                "gross_open_return_pct": 3.0,
                "gross_high_return_pct": 11.0,
                "gross_low_return_pct": -1.0,
                "gross_close_return_pct": 10.0,
                "net_close_return_pct": 9.69,
                "market_return_pct": 2.0,
                "excess_close_return_pct": 8.0,
                "d_close_limit_up": True,
            },
        ]
    )

    report = summarize_event_frame(events)

    assert report["trade_summary"]["gross_win_rate_pct"] == pytest.approx(66.6667)
    assert report["portfolio"]["signal_day_count"] == 2
    assert report["portfolio"]["gross_compound_return_pct"] == pytest.approx(10.0)
    assert report["portfolio"]["net_compound_return_pct"] == pytest.approx(9.35, abs=0.0001)
    assert report["portfolio"]["net_max_drawdown_pct"] == pytest.approx(-0.31)
    assert report["portfolio"]["average_positions_per_signal_day"] == pytest.approx(1.5)
    assert report["portfolio"]["max_positions_per_signal_day"] == 2
