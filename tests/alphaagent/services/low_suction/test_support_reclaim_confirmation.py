from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.support_reclaim_confirmation import (
    RULE_ID,
    assign_frozen_time_blocks,
    build_support_reclaim_confirmations,
    freeze_common_block_boundaries,
    freeze_development_confirmation_rule,
)


def test_first_reclaim_close_after_support_emits_once_without_outcomes() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()

    events = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    assert events["signal_date"].tolist() == [pd.Timestamp("2026-01-08")]
    assert events["support_test_date"].tolist() == [pd.Timestamp("2026-01-06")]
    assert events["confirmation_delay_sessions"].tolist() == [2]
    assert events["rule_id"].tolist() == [RULE_ID]
    assert events["feature_cutoff_date"].equals(events["signal_date"])
    assert events["market_timing_feature_cutoff_date"].equals(
        events["signal_date"]
    )
    assert not set(events).intersection(
        {"d1_close", "net_return_pct", "exit_date", "mfe_pct", "mae_pct"}
    )


def test_new_exact_support_replaces_the_active_anchor() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    replacement = {
        **anchors.iloc[0].to_dict(),
        "signal_id": "support-replacement",
        "signal_date": pd.Timestamp("2026-01-07"),
        "support_test_date": pd.Timestamp("2026-01-07"),
        "feature_cutoff_date": pd.Timestamp("2026-01-07"),
        "high_price": 10.65,
        "close_price": 10.40,
    }
    anchors = pd.concat([anchors, pd.DataFrame([replacement])], ignore_index=True)
    ledger.loc[ledger["trade_date"].eq(pd.Timestamp("2026-01-07")), "latest_support_test_date"] = pd.Timestamp(
        "2026-01-07"
    )

    events = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    assert events["support_test_date"].tolist() == [pd.Timestamp("2026-01-07")]
    assert events["support_day_high"].tolist() == pytest.approx([10.65])
    assert events["confirmation_delay_sessions"].tolist() == [1]


def test_same_depth_non_exact_retest_keeps_latest_valid_exact_anchor() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    ledger.loc[
        ledger["trade_date"].eq(pd.Timestamp("2026-01-07")),
        "latest_support_test_date",
    ] = pd.Timestamp("2026-01-07")

    events = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    assert events["support_test_date"].tolist() == [pd.Timestamp("2026-01-06")]
    assert events["confirmation_delay_sessions"].tolist() == [2]


def test_deeper_support_invalidates_the_old_anchor() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    deeper = ledger["trade_date"].ge(pd.Timestamp("2026-01-07"))
    ledger.loc[deeper, "deepest_tested_depth"] = 2
    ledger.loc[deeper, "required_support"] = "ma5"

    events = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    assert events.empty


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("state", "terminated"),
        ("campaign_active", False),
        ("dynamic_top3", False),
        ("structure_intact", False),
    ),
)
def test_main_rise_failure_invalidates_the_old_anchor(
    column: str,
    value: object,
) -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    later = paths["trade_date"].ge(pd.Timestamp("2026-01-07"))
    if column in paths:
        paths.loc[later, column] = value
    if column in ledger:
        ledger.loc[later, column] = value

    events = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    assert events.empty


def test_wave_transition_invalidates_the_old_anchor() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    later = ledger["trade_date"].ge(pd.Timestamp("2026-01-07"))
    ledger.loc[later, "wave_number"] = 2

    events = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    assert events.empty


def test_end_of_retained_path_cannot_create_a_confirmation() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    retained = paths["trade_date"].le(pd.Timestamp("2026-01-07"))

    events = build_support_reclaim_confirmations(
        anchors,
        paths.loc[retained],
        ledger.loc[retained],
        timing,
    )

    assert events.empty


def test_post_confirmation_prices_cannot_change_signal_identity() -> None:
    anchors, paths, ledger, timing = _confirmation_inputs()
    first = build_support_reclaim_confirmations(anchors, paths, ledger, timing)
    paths.loc[paths["trade_date"].gt(pd.Timestamp("2026-01-08")), [
        "high_price",
        "low_price",
        "close_price",
        "daily_return_pct",
    ]] = [999.0, 1.0, 500.0, 99.0]

    polluted = build_support_reclaim_confirmations(anchors, paths, ledger, timing)

    columns = [
        "signal_id",
        "signal_date",
        "support_test_date",
        "entry_price",
        "record_high_price",
    ]
    assert first[columns].to_dict("records") == polluted[columns].to_dict("records")


def test_common_boundaries_do_not_recut_on_confirmation_dates() -> None:
    common_dates = pd.bdate_range("2025-01-02", periods=25)
    boundaries = freeze_common_block_boundaries(common_dates)
    confirmations = pd.DataFrame(
        {
            "signal_date": [
                common_dates[1],
                common_dates[5],
                common_dates[12],
                common_dates[18],
                common_dates[22],
                common_dates[-1] + pd.offsets.BDay(1),
            ]
        }
    )

    blocked = assign_frozen_time_blocks(confirmations, boundaries)

    assert boundaries == {
        "block_1": common_dates[4],
        "block_2": common_dates[9],
        "block_3": common_dates[14],
        "block_4": common_dates[19],
        "block_5": common_dates[24],
    }
    assert blocked["time_block"].tolist() == [
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
        "block_5",
    ]


def test_development_freeze_cannot_read_late_block_returns() -> None:
    trades = _gate_trades(late_return=30.0)
    double_cost = trades.assign(net_return_pct=trades["net_return_pct"] - 0.2)

    first = freeze_development_confirmation_rule(
        trades,
        double_cost,
        {"compound_return_pct": 25.0},
    )
    polluted = trades.copy()
    polluted.loc[polluted["time_block"].isin(("block_4", "block_5")), "net_return_pct"] = -30.0
    second = freeze_development_confirmation_rule(
        polluted,
        double_cost,
        {"compound_return_pct": 25.0},
    )

    assert first == second
    assert first["selected_rule"] == RULE_ID
    assert first["development_metrics"]["closed_trades"] == 120
    assert first["development_metrics"]["win_rate_pct"] == pytest.approx(65.0)


def _confirmation_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dates = pd.bdate_range("2026-01-05", periods=6)
    closes = [10.80, 10.35, 10.40, 10.70, 10.75, 10.90]
    highs = [10.95, 10.60, 10.55, 10.78, 10.82, 10.98]
    paths = pd.DataFrame(
        {
            "campaign_id": ["campaign-1"] * len(dates),
            "sector_id": ["BK0001"] * len(dates),
            "concept_name": ["测试概念"] * len(dates),
            "vt_symbol": ["600001.SSE"] * len(dates),
            "stock_name": ["测试股份"] * len(dates),
            "trade_date": dates,
            "open_price": [value - 0.10 for value in closes],
            "high_price": highs,
            "low_price": [10.70, 10.10, 10.20, 10.35, 10.50, 10.70],
            "close_price": closes,
            "previous_close": [10.60, *closes[:-1]],
            "daily_return_pct": [2.0, -4.2, 0.5, 2.9, 0.5, 1.4],
            "ma5": [10.20] * len(dates),
            "ma10": [9.80] * len(dates),
            "ma20": [9.40] * len(dates),
            "volume_ratio_prior5": [1.0, 0.8, 0.7, 1.1, 1.2, 1.3],
            "close_location": [0.7] * len(dates),
            "campaign_active": [True] * len(dates),
            "dynamic_rank": [1] * len(dates),
            "dynamic_top3": [True] * len(dates),
            "structure_intact": [True] * len(dates),
            "feature_cutoff_date": dates,
        }
    )
    ledger = pd.DataFrame(
        {
            "campaign_id": ["campaign-1"] * len(dates),
            "vt_symbol": ["600001.SSE"] * len(dates),
            "trade_date": dates,
            "state": ["advancing", "pullback", "pullback", "pullback", "pullback", "pullback"],
            "wave_number": [1] * len(dates),
            "record_high_price": [11.0] * len(dates),
            "record_high_date": [dates[0]] * len(dates),
            "deepest_tested_depth": [0, 1, 1, 1, 1, 1],
            "required_support": [None, "ma5", "ma5", "ma5", "ma5", "ma5"],
            "latest_support_test_date": [pd.NaT, dates[1], dates[1], dates[1], dates[1], dates[1]],
            "dynamic_top3": [True] * len(dates),
            "structure_intact": [True] * len(dates),
        }
    )
    anchors = pd.DataFrame(
        [
            {
                "rule_id": "support_day_exact_hold",
                "signal_id": "support-anchor",
                "campaign_id": "campaign-1",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "signal_date": dates[1],
                "support_test_date": dates[1],
                "feature_cutoff_date": dates[1],
                "high_price": highs[1],
                "close_price": closes[1],
                "required_support": "ma5",
                "required_support_depth": 1,
                "required_support_price": 10.20,
                "wave_number": 1,
                "record_high_price": 11.0,
                "dynamic_rank": 1,
            }
        ]
    )
    timing = pd.DataFrame(
        {
            "source_date": dates,
            "active_direction": ["GOLD"] * len(dates),
            "danger_state": ["NORMAL"] * len(dates),
            "market_phase": ["rotation"] * len(dates),
        }
    )
    return anchors, paths, ledger, timing


def _gate_trades(*, late_return: float) -> pd.DataFrame:
    rows = []
    for position in range(140):
        if position < 120:
            block = f"block_{position // 40 + 1}"
            within_block = position % 40
            value = 2.0 if within_block < 26 else -1.0
        else:
            block = "block_4" if position < 130 else "block_5"
            value = late_return
        rows.append(
            {
                "rule_id": RULE_ID,
                "signal_id": f"signal-{position}",
                "time_block": block,
                "entry_date": pd.Timestamp("2024-01-02")
                + pd.offsets.BDay(position),
                "exit_date": pd.Timestamp("2024-01-03")
                + pd.offsets.BDay(position),
                "net_return_pct": value,
            }
        )
    return pd.DataFrame(rows)
