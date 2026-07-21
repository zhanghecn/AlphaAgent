from __future__ import annotations

from datetime import date

import pandas as pd

from alphaagent.server.services.limit_up.preboard_hazard_study import (
    build_hazard_replay_orders,
    build_forward_overlay_rows,
    replay_hazard_account,
    settle_forward_actions,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    official_one_minute_close_times,
)


def test_three_minute_action_competes_before_two_position_cash_replay() -> None:
    action_rows = [
        _signal("600001.SSE", probability=0.95, entry_price=10.51),
        _signal("600002.SSE", probability=0.90, entry_price=10.41),
        _signal("600003.SSE", probability=0.85, entry_price=10.31),
    ]
    prepare_rows = [
        _signal("600004.SSE", probability=0.99, entry_price=10.21),
    ]
    relay = {
        "vt_symbol": "600010.SSE",
        "name": "Relay",
        "entry_date": "2026-07-16",
        "result_date": "2026-07-17",
        "buy_time": "09:30:00",
        "lane": "two_to_three",
        "signal_kind": "auction",
        "entry_price": 10.0,
        "limit_price": 11.0,
        "outcome": {"next_close_price": 10.5},
    }

    bundle = build_hazard_replay_orders(
        action_rows=action_rows,
        prepare_rows=prepare_rows,
        formal_orders=[relay],
        action_threshold=0.80,
        prepare_threshold=0.80,
    )

    assert [row["vt_symbol"] for row in bundle["action_signals"]] == [
        "600001.SSE",
        "600002.SSE",
    ]
    assert [row["vt_symbol"] for row in bundle["prepare_signals"]] == [
        "600004.SSE",
    ]
    assert [row["vt_symbol"] for row in bundle["combined_orders"]] == [
        "600010.SSE",
        "600001.SSE",
        "600002.SSE",
    ]
    assert all(
        order["buy_time"] == "10:01:00"
        for order in bundle["early_orders"]
    )

    account = replay_hazard_account(
        bundle["combined_orders"],
        _daily_bars(),
        [date(2026, 7, 16), date(2026, 7, 17)],
    )
    buys = [order for order in account["orders"] if order["side"] == "BUY"]

    assert [(order["vt_symbol"], order["status"]) for order in buys] == [
        ("600010.SSE", "filled"),
        ("600001.SSE", "filled"),
        ("600002.SSE", "skipped"),
    ]
    assert buys[-1]["reason"] == "position_limit"
    assert all(order["vt_symbol"] != "600004.SSE" for order in buys)


def test_conservative_entry_uses_worse_causal_price_and_rechecks_limit() -> None:
    row = _signal(
        "600001.SSE",
        probability=0.95,
        entry_price=10.50,
        signal_price=10.60,
    )

    bundle = build_hazard_replay_orders(
        action_rows=[row],
        prepare_rows=[],
        formal_orders=[],
        action_threshold=0.80,
        prepare_threshold=0.80,
        conservative_entry=True,
    )

    assert bundle["early_orders"][0]["entry_price"] == 10.6106
    assert bundle["early_orders"][0]["conservative_entry"] is True


def test_forward_overlay_joins_completed_minutes_to_saved_live_gates() -> None:
    trade_date = date(2026, 7, 16)
    bars = []
    for index, slot in enumerate(official_one_minute_close_times()[:40]):
        close = 10.25 + index * 0.01
        bars.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "bar_time": f"{trade_date.isoformat()}T{slot}:00",
                "interval": "1m",
                "open_price": close - 0.005,
                "high_price": close + 0.01,
                "low_price": close - 0.01,
                "close_price": close,
                "volume": 1_000 + index * 20,
                "turnover": (1_000 + index * 20) * close * 100,
            }
        )
    observation = {
        "trade_date": trade_date,
        "captured_at": f"{trade_date.isoformat()}T10:05:20",
        "vt_symbol": "600001.SSE",
        "name": "Forward",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "last_price": 10.60,
        "change_pct": 6.0,
        "board_lane": "first_board",
        "capture_state": "tracking",
        "support_score": 70.0,
        "entry_quality_score": 75.0,
        "rank_score": 80.0,
        "history_sample_count": 5,
        "historical_combined_rate": 40.0,
        "blocking_scope": "none",
        "blocker_codes": [],
        "concept_strength_score": 78.0,
        "concept_change_acceleration_3m": 1.2,
        "sector_main_net_inflow": 100_000_000.0,
    }

    rows = build_forward_overlay_rows([observation], pd.DataFrame(bars))

    assert len(rows) == 1
    assert rows[0]["signal_time"] == "10:05:00"
    assert rows[0]["shared_strategy_passed"] is True
    assert rows[0]["features"]["return_1m_pct"] is not None
    assert rows[0]["features"]["return_3m_pct"] is not None
    assert rows[0]["features"]["return_5m_pct"] is not None
    assert rows[0]["profitability_gate_sample_count"] == 5
    assert rows[0]["profitability_gate_combined_rate"] == 40.0
    assert rows[0]["concept_strength_score"] == 78.0
    assert rows[0]["concept_change_acceleration_3m"] == 1.2

    blocked = build_forward_overlay_rows(
        [{**observation, "blocking_scope": "sector"}],
        pd.DataFrame(bars),
    )
    assert blocked[0]["shared_strategy_passed"] is False


def test_forward_actions_settle_only_on_next_reliable_close() -> None:
    action = _signal("600001.SSE", probability=0.95, entry_price=10.50)
    daily = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": date(2026, 7, 16),
            "close_price": 10.60,
        },
        {
            "vt_symbol": "600001.SSE",
            "trade_date": date(2026, 7, 17),
            "close_price": 10.80,
        },
    ]

    settled = settle_forward_actions(
        [action],
        daily,
        [date(2026, 7, 16), date(2026, 7, 17)],
    )

    assert len(settled) == 1
    assert settled[0]["result_date"] == "2026-07-17"
    assert settled[0]["d1_close_price"] == 10.8
    assert settled[0]["net_return_pct"] is not None
    assert settled[0]["net_return_pct"] > 0


def _signal(
    symbol: str,
    *,
    probability: float,
    entry_price: float,
    signal_price: float = 10.50,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "signal_date": "2026-07-16",
        "result_date": "2026-07-17",
        "signal_at": "2026-07-16T10:00:00",
        "signal_time": "10:00:00",
        "entry_time": "10:01:00",
        "entry_price": entry_price,
        "signal_price": signal_price,
        "limit_price": 11.0,
        "fillable": True,
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
        "hazard_probability": probability,
        "entry_quality_score": probability * 100,
        "rank_score": probability * 100,
        "touched_limit": True,
        "sealed_limit": True,
        "d1_close_price": 10.8,
        "features": {"gain_pct": 5.0},
    }


def _daily_bars() -> list[dict[str, object]]:
    symbols = (
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
        "600004.SSE",
        "600010.SSE",
    )
    return [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date,
            "open_price": 10.0,
            "high_price": 10.9,
            "low_price": 9.9,
            "close_price": 10.5 if trade_date == date(2026, 7, 17) else 10.3,
        }
        for trade_date in (date(2026, 7, 16), date(2026, 7, 17))
        for symbol in symbols
    ]
