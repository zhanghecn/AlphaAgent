from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.support_day_entry import (
    RULE_BAND_RECLAIM,
    RULE_EXACT_BULLISH,
    RULE_EXACT_HOLD,
    RULE_IDS,
    apply_pre_registered_rules,
    assign_common_time_blocks,
    build_support_day_events,
    execute_d1_close_trades,
    filter_common_rule_universe,
    freeze_development_rule,
    reprice_d1_close_trades,
)


def test_support_day_events_use_the_support_bar_without_outcomes() -> None:
    paths, ledger, timing = _event_inputs()

    events = build_support_day_events(paths, ledger, timing)

    assert events["signal_date"].tolist() == [
        pd.Timestamp("2026-01-06"),
        pd.Timestamp("2026-01-09"),
    ]
    assert events["signal_date"].equals(events["support_test_date"])
    assert events["feature_cutoff_date"].equals(events["signal_date"])
    assert events["required_support"].tolist() == ["ma5", "ma10"]
    assert events["active_direction"].tolist() == ["GOLD", "SILVER"]
    assert not set(events).intersection(
        {"d1_close", "net_return_pct", "exit_date", "mfe_pct", "mae_pct"}
    )


def test_pre_registered_rules_keep_exact_and_band_semantics_distinct() -> None:
    events = build_support_day_events(*_event_inputs())
    later = events.loc[events["wave_number"].eq(2)].copy()
    later.loc[:, "low_price"] = 11.05
    later.loc[:, "ma5"] = 11.40
    later.loc[:, "ma10"] = 10.90
    later.loc[:, "close_price"] = 11.45
    later.loc[:, "open_price"] = 11.10
    later.loc[:, "close_location"] = 0.75
    later.loc[:, "exact_depth_match"] = False
    later.loc[:, "required_line_near"] = False
    later.loc[:, "ma5_ma10_band_test"] = True
    later.loc[:, "ma5_reclaimed"] = True
    events = pd.concat(
        [events.loc[events["wave_number"].eq(1)], later], ignore_index=True
    )

    selected = apply_pre_registered_rules(events)

    by_rule = {
        rule: group["wave_number"].tolist()
        for rule, group in selected.groupby("rule_id", sort=False)
    }
    assert set(RULE_IDS) == {
        RULE_EXACT_HOLD,
        RULE_EXACT_BULLISH,
        RULE_BAND_RECLAIM,
    }
    assert by_rule[RULE_EXACT_HOLD] == [1]
    assert by_rule[RULE_EXACT_BULLISH] == [1]
    assert by_rule[RULE_BAND_RECLAIM] == [1, 2]


def test_rule_selection_rejects_outcome_columns() -> None:
    events = build_support_day_events(*_event_inputs()).assign(d1_close=99.0)

    with pytest.raises(ValueError, match="outcome columns"):
        apply_pre_registered_rules(events)


def test_common_rule_universe_excludes_dates_that_no_rule_can_trade() -> None:
    events = build_support_day_events(*_event_inputs())
    events.loc[events.index[0], "danger_state"] = "UNKNOWN"
    events.loc[events.index[1], "daily_return_pct"] = 9.5

    eligible = filter_common_rule_universe(events)

    assert eligible.empty


def test_d1_execution_uses_the_next_symbol_session_close() -> None:
    paths, ledger, timing = _event_inputs()
    events = build_support_day_events(paths, ledger, timing)
    selected = apply_pre_registered_rules(events)
    selected = selected.loc[selected["rule_id"].eq(RULE_EXACT_HOLD)]

    trades = execute_d1_close_trades(selected, paths)

    assert trades["entry_date"].tolist() == [
        pd.Timestamp("2026-01-06"),
        pd.Timestamp("2026-01-09"),
    ]
    assert trades["exit_date"].tolist() == [
        pd.Timestamp("2026-01-07"),
        pd.Timestamp("2026-01-12"),
    ]
    assert trades["entry_price"].tolist() == pytest.approx([10.45, 11.20])
    assert trades["d1_close"].tolist() == pytest.approx([10.70, 11.50])
    assert trades["net_return_pct"].tolist() == pytest.approx(
        [(10.70 / 10.45 - 1.0) * 100.0 - 0.2, (11.50 / 11.20 - 1.0) * 100.0 - 0.2]
    )
    assert trades["d1_net_return_pct"].tolist() == pytest.approx(
        trades["net_return_pct"].tolist()
    )


def test_d1_cost_sensitivity_reuses_the_executed_trade_ledger() -> None:
    paths, ledger, timing = _event_inputs()
    events = apply_pre_registered_rules(build_support_day_events(paths, ledger, timing))
    base = execute_d1_close_trades(
        events.loc[events["rule_id"].eq(RULE_EXACT_HOLD)],
        paths,
    )

    repriced = reprice_d1_close_trades(base, round_trip_cost_pct=0.4)

    assert repriced["signal_id"].tolist() == base["signal_id"].tolist()
    assert repriced["entry_date"].equals(base["entry_date"])
    assert repriced["exit_date"].equals(base["exit_date"])
    assert repriced["round_trip_cost_pct"].tolist() == [0.4, 0.4]
    assert repriced["net_return_pct"].tolist() == pytest.approx(
        (base["net_return_pct"] - 0.2).tolist()
    )
    assert repriced["d1_net_return_pct"].tolist() == pytest.approx(
        repriced["net_return_pct"].tolist()
    )


def test_d1_execution_rejects_same_stock_reentry_on_the_exit_close() -> None:
    selected = pd.DataFrame(
        [
            {
                "rule_id": RULE_EXACT_HOLD,
                "signal_id": "first",
                "campaign_id": "campaign-1",
                "vt_symbol": "600001.SSE",
                "signal_date": pd.Timestamp("2026-01-06"),
                "close_price": 10.0,
                "dynamic_rank": 1,
            },
            {
                "rule_id": RULE_EXACT_HOLD,
                "signal_id": "overlap",
                "campaign_id": "campaign-2",
                "vt_symbol": "600001.SSE",
                "signal_date": pd.Timestamp("2026-01-07"),
                "close_price": 10.5,
                "dynamic_rank": 1,
            },
        ]
    )
    price_calendar = pd.DataFrame(
        {
            "vt_symbol": ["600001.SSE"] * 3,
            "trade_date": pd.to_datetime(
                ["2026-01-06", "2026-01-07", "2026-01-08"]
            ),
            "close_price": [10.0, 10.5, 11.0],
        }
    )

    trades = execute_d1_close_trades(selected, price_calendar)

    assert trades["signal_id"].tolist() == ["first"]


def test_common_blocks_are_rule_independent() -> None:
    dates = pd.bdate_range("2025-01-02", periods=25)
    events = pd.DataFrame({"signal_date": dates})
    selected = pd.concat(
        [
            events.iloc[:15].assign(rule_id=RULE_EXACT_HOLD),
            events.iloc[10:].assign(rule_id=RULE_BAND_RECLAIM),
        ],
        ignore_index=True,
    )

    blocked = assign_common_time_blocks(selected, event_dates=dates)

    overlap = blocked.loc[blocked["signal_date"].eq(dates[10])]
    assert overlap["time_block"].nunique() == 1
    assert overlap["time_block"].iat[0] == "block_3"


def test_development_rule_freeze_cannot_read_profitable_late_blocks() -> None:
    trades = pd.concat(
        [
            _rule_trades(RULE_EXACT_HOLD, development_winners=62, late_return=20.0),
            _rule_trades(RULE_BAND_RECLAIM, development_winners=75, late_return=-20.0),
        ],
        ignore_index=True,
    )
    double_cost = trades.assign(net_return_pct=trades["net_return_pct"] - 0.2)
    cash = {
        RULE_EXACT_HOLD: {"compound_return_pct": 30.0},
        RULE_BAND_RECLAIM: {"compound_return_pct": 45.0},
    }

    frozen = freeze_development_rule(trades, double_cost, cash)

    assert frozen["selected_rule"] == RULE_BAND_RECLAIM
    exact = next(
        row for row in frozen["candidate_metrics"] if row["rule_id"] == RULE_EXACT_HOLD
    )
    assert exact["development_closed_trades"] == 100
    assert exact["development_win_rate_pct"] == pytest.approx(62.0)


def _event_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(
        [
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
            "2026-01-12",
        ]
    )
    closes = [10.80, 10.45, 10.70, 11.60, 11.20, 11.50]
    lows = [10.70, 10.18, 10.35, 11.40, 10.88, 11.20]
    rows = []
    for position, trade_date in enumerate(dates):
        rows.append(
            {
                "campaign_id": "campaign-1",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "trade_date": trade_date,
                "open_price": closes[position] - 0.15,
                "high_price": closes[position] + 0.20,
                "low_price": lows[position],
                "close_price": closes[position],
                "daily_return_pct": 2.0,
                "ma5": 10.25 if position < 3 else 11.25,
                "ma10": 9.90 if position < 3 else 10.90,
                "ma20": 9.50 if position < 3 else 10.20,
                "previous_close": closes[position - 1] if position else 10.60,
                "volume_ratio_prior5": 0.85,
                "close_location": 0.70,
                "campaign_active": True,
                "dynamic_rank": 1,
                "dynamic_top3": True,
                "structure_intact": True,
                "feature_cutoff_date": trade_date,
            }
        )
    paths = pd.DataFrame(rows)
    ledger = pd.DataFrame(
        [
            {
                "campaign_id": "campaign-1",
                "vt_symbol": "600001.SSE",
                "trade_date": dates[1],
                "state": "pullback",
                "wave_number": 1,
                "record_high_price": 11.0,
                "record_high_date": dates[0],
                "deepest_tested_support": "ma5",
                "deepest_tested_depth": 1,
                "required_support": "ma5",
                "latest_support_test_date": dates[1],
                "dynamic_top3": True,
                "structure_intact": True,
            },
            {
                "campaign_id": "campaign-1",
                "vt_symbol": "600001.SSE",
                "trade_date": dates[4],
                "state": "pullback",
                "wave_number": 2,
                "record_high_price": 11.8,
                "record_high_date": dates[3],
                "deepest_tested_support": "ma10",
                "deepest_tested_depth": 2,
                "required_support": "ma10",
                "latest_support_test_date": dates[4],
                "dynamic_top3": True,
                "structure_intact": True,
            },
        ]
    )
    timing = pd.DataFrame(
        {
            "source_date": [dates[1], dates[4]],
            "active_direction": ["GOLD", "SILVER"],
            "danger_state": ["NORMAL", "NORMAL"],
            "market_phase": ["rotation", "warming"],
        }
    )
    return paths, ledger, timing


def _rule_trades(
    rule_id: str,
    *,
    development_winners: int,
    late_return: float,
) -> pd.DataFrame:
    rows = []
    for position in range(120):
        if position < 100:
            value = 2.0 if position < development_winners else -1.0
            block = f"block_{position // 34 + 1}"
            if block == "block_4":
                block = "block_3"
        else:
            value = late_return
            block = "block_4" if position < 110 else "block_5"
        rows.append(
            {
                "rule_id": rule_id,
                "signal_id": f"{rule_id}-{position}",
                "entry_date": pd.Timestamp("2025-01-02") + pd.Timedelta(days=position),
                "exit_date": pd.Timestamp("2025-01-03") + pd.Timedelta(days=position),
                "net_return_pct": value,
                "time_block": block,
            }
        )
    return pd.DataFrame(rows)
