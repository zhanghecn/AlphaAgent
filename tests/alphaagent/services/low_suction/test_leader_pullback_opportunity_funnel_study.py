from __future__ import annotations

import pandas as pd

from alphaagent.server.services.low_suction.leader_pullback_opportunity_funnel_study import (
    attach_funnel_attribution,
    build_support_touch_opportunities,
    summarize_funnel,
)


def test_support_touch_parent_and_funnel_are_auditable() -> None:
    dates = pd.bdate_range("2026-01-05", periods=5)
    daily = pd.DataFrame([
        _daily(dates[0], "advancing", 1, "ma5", None),
        _daily(dates[1], "pullback", 1, "ma5", dates[1]),
        _daily(dates[2], "pullback", 1, "ma5", dates[1]),
        _daily(dates[3], "pullback", 2, "ma10", dates[3]),
    ])
    paths = pd.DataFrame([_path(day, low) for day, low in zip(dates[:4], [11, 9.9, 10.2, 8.9])])
    bars = pd.DataFrame({
        "vt_symbol": ["600001.SSE"] * 5,
        "trade_date": dates,
        "close_price": [10.8, 10.1, 10.6, 9.2, 9.8],
    })
    opportunities = build_support_touch_opportunities(daily, paths, bars)
    assert opportunities["support_line"].tolist() == ["ma5", "ma10"]
    assert opportunities["d1_net_return_pct"].round(3).tolist() == [5.8, -2.2]

    signals = pd.DataFrame([{
        "campaign_id": "c1", "vt_symbol": "600001.SSE", "required_support": "ma5",
        "support_test_date": dates[1], "signal_id": "s1", "signal_date": dates[2],
        "signal_daily_return_pct": 9.0, "signal_close": 10.6,
        "reference_peak_price": 11.0, "market_phase": "rotation",
        "active_direction": "GOLD", "danger_state": "NORMAL",
        "signal_low": 10.0, "support_price": 10.0,
    }])
    trades = pd.DataFrame([{
        "signal_id": "s1", "entry_date": dates[2], "exit_date": dates[4],
        "sector_id": "BK1", "vt_symbol": "600001.SSE", "dynamic_rank": 1,
        "exit_reason": "d1_loss_stop", "net_return_pct": -1.0,
    }])
    attributed = attach_funnel_attribution(opportunities, signals, trades, trades)
    assert attributed["terminal_reason"].tolist() == ["two_slot_trade", "no_next_day_confirmation"]
    summary = summarize_funnel(attributed)
    assert summary["stages"]["parent"]["opportunities"] == 2
    assert summary["stages"]["two_slot_accepted"]["opportunities"] == 1


def _daily(day, state, wave, support, tested):
    return {
        "campaign_id": "c1", "vt_symbol": "600001.SSE", "trade_date": day,
        "state": state, "wave_number": wave, "required_support": support,
        "deepest_tested_support": support if tested is not None else None,
        "latest_support_test_date": tested, "dynamic_rank": 1, "dynamic_top3": True,
        "structure_intact": True,
    }


def _path(day, low):
    return {
        "campaign_id": "c1", "sector_id": "BK1", "concept_name": "测试概念",
        "vt_symbol": "600001.SSE", "stock_name": "测试股", "trade_date": day,
        "campaign_active": True, "close_price": 10.0, "low_price": low,
        "ma5": 10.0, "ma10": 9.0,
    }
