from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cycle_leader_study import (
    build_cycle_leader_summary,
    build_dynamic_cycle_leaders,
    build_observed_cycle_periods,
    build_realized_cycle_leaders,
)


COMPLETED_CYCLE = "breakout_trend:BK0001:2025-01-02"
CENSORED_CYCLE = "breakout_trend:BK0002:2025-01-02"


def _cycle_states() -> pd.DataFrame:
    active_dates = tuple(pd.bdate_range("2025-01-02", "2025-01-09"))
    rows: list[dict[str, object]] = []
    for sector_id, cycle_id in (
        ("BK0001", COMPLETED_CYCLE),
        ("BK0002", CENSORED_CYCLE),
    ):
        for offset, trade_date in enumerate(active_dates, start=1):
            rows.append(
                {
                    "definition": "breakout_trend",
                    "sector_id": sector_id,
                    "trade_date": trade_date,
                    "in_cycle": True,
                    "cycle_id": cycle_id,
                    "cycle_start": active_dates[0],
                    "cycle_days": offset,
                    "cycle_ended": False,
                    "ended_cycle_id": None,
                }
            )
    rows.append(
        {
            "definition": "breakout_trend",
            "sector_id": "BK0001",
            "trade_date": pd.Timestamp("2025-01-10"),
            "in_cycle": False,
            "cycle_id": None,
            "cycle_start": None,
            "cycle_days": None,
            "cycle_ended": True,
            "ended_cycle_id": COMPLETED_CYCLE,
        }
    )
    return pd.DataFrame(rows)


def _candidate_spells() -> pd.DataFrame:
    rows = []
    specifications = (
        (COMPLETED_CYCLE, "BK0001", "测试概念一", "600001.SSE", "甲股份", "2025-01-03"),
        (COMPLETED_CYCLE, "BK0001", "测试概念一", "600002.SSE", "乙股份", "2025-01-06"),
        (COMPLETED_CYCLE, "BK0001", "测试概念一", "600003.SSE", "丙股份", "2025-01-07"),
        (CENSORED_CYCLE, "BK0002", "测试概念二", "600004.SSE", "丁股份", "2025-01-03"),
        (CENSORED_CYCLE, "BK0002", "测试概念二", "600005.SSE", "戊股份", "2025-01-06"),
    )
    for cycle_id, sector_id, concept_name, symbol, stock_name, recognition_date in specifications:
        rows.append(
            {
                "leader_spell_id": f"{sector_id}:{cycle_id}:{symbol}",
                "recognition_source_date": pd.Timestamp(recognition_date),
                "sector_id": sector_id,
                "concept_name": concept_name,
                "cycle_id": cycle_id,
                "vt_symbol": symbol,
                "stock_name": stock_name,
            }
        )
    return pd.DataFrame(rows)


def _stock_bars() -> pd.DataFrame:
    dates = tuple(pd.bdate_range("2024-12-02", "2025-01-10"))
    cycle_closes = {
        "600001.SSE": [10.0, 11.0, 12.1, 12.0, 12.2, 12.5],
        "600002.SSE": [10.0, 11.0, 11.0, 12.1, 13.0, 14.0],
        "600003.SSE": [10.0, 10.2, 10.5, 11.0, 12.0, 13.0],
        "600004.SSE": [8.0, 8.2, 8.4, 8.5, 8.6, 8.7],
        "600005.SSE": [9.0, 9.1, 9.2, 9.4, 9.5, 9.6],
    }
    active_dates = tuple(pd.bdate_range("2025-01-02", "2025-01-09"))
    rows = []
    for symbol, closes in cycle_closes.items():
        close_by_date = {trade_date: 9.0 for trade_date in dates}
        for trade_date, close in zip(active_dates, closes, strict=True):
            close_by_date[trade_date] = close
        for index, trade_date in enumerate(dates):
            close = close_by_date[trade_date]
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close,
                    "high_price": close * 1.02,
                    "low_price": close * 0.98,
                    "close_price": close,
                    "volume": 100_000.0 + index * 1_000.0,
                    "turnover": 200_000_000.0 + index * 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _concept_bars() -> pd.DataFrame:
    active_dates = tuple(pd.bdate_range("2025-01-02", "2025-01-09"))
    rows = []
    for sector_id, closes in (
        ("BK0001", [100.0, 102.0, 104.0, 105.0, 107.0, 110.0]),
        ("BK0002", [100.0, 100.5, 101.0, 101.5, 102.0, 102.5]),
    ):
        rows.append(
            {
                "sector_id": sector_id,
                "trade_date": pd.Timestamp("2024-12-31"),
                "close_price": 95.0,
            }
        )
        rows.extend(
            {
                "sector_id": sector_id,
                "trade_date": trade_date,
                "close_price": close,
            }
            for trade_date, close in zip(active_dates, closes, strict=True)
        )
    return pd.DataFrame(rows)


def _target_sessions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": COMPLETED_CYCLE,
                "sector_id": "BK0001",
                "entry_date": pd.Timestamp("2025-01-07"),
                "context_date": pd.Timestamp("2025-01-06"),
            },
            {
                "cycle_id": COMPLETED_CYCLE,
                "sector_id": "BK0001",
                "entry_date": pd.Timestamp("2025-01-09"),
                "context_date": pd.Timestamp("2025-01-08"),
            },
        ]
    )


def test_period_ledger_retains_completed_and_censored_cycles() -> None:
    periods = build_observed_cycle_periods(_cycle_states(), _candidate_spells())

    assert periods["cycle_id"].tolist() == [COMPLETED_CYCLE, CENSORED_CYCLE]
    by_cycle = periods.set_index("cycle_id")
    assert by_cycle.loc[COMPLETED_CYCLE, "period_status"] == "completed"
    assert by_cycle.loc[COMPLETED_CYCLE, "candidate_count"] == 3
    assert by_cycle.loc[COMPLETED_CYCLE, "active_sessions"] == 6
    assert by_cycle.loc[CENSORED_CYCLE, "period_status"] == "censored_at_discovery_end"
    assert by_cycle.loc[CENSORED_CYCLE, "candidate_count"] == 2


def test_realized_market_and_return_leaders_are_separate_labels() -> None:
    periods = build_observed_cycle_periods(_cycle_states(), _candidate_spells())
    leaders = build_realized_cycle_leaders(
        periods,
        _candidate_spells(),
        _stock_bars(),
        _concept_bars(),
    )
    completed = leaders.loc[leaders["cycle_id"].eq(COMPLETED_CYCLE)].set_index("vt_symbol")

    assert completed.loc["600001.SSE", "realized_market_rank"] == 1
    assert completed.loc["600002.SSE", "realized_return_rank"] == 1
    assert completed.loc["600003.SSE", "realized_return_rank"] == 2
    assert completed["realized_market_rank"].notna().all()
    assert completed["realized_return_rank"].notna().all()


def test_dynamic_leaders_use_only_recognized_stocks_and_d1_bars() -> None:
    periods = build_observed_cycle_periods(_cycle_states(), _candidate_spells())
    dynamic = build_dynamic_cycle_leaders(
        periods,
        _candidate_spells(),
        _target_sessions(),
        _stock_bars(),
        _concept_bars(),
    )
    first = dynamic.loc[dynamic["entry_date"].eq(pd.Timestamp("2025-01-07"))]
    second = dynamic.loc[dynamic["entry_date"].eq(pd.Timestamp("2025-01-09"))]

    assert set(first["vt_symbol"]) == {"600001.SSE", "600002.SSE"}
    assert first["dynamic_pool_size"].eq(2).all()
    assert not first["dynamic_top3_qualified"].any()
    assert set(second["vt_symbol"]) == {
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    }
    assert second["dynamic_pool_size"].eq(3).all()
    assert second["dynamic_top3_qualified"].all()
    assert second["feature_cutoff_date"].eq(pd.Timestamp("2025-01-08")).all()

    by_symbol = second.set_index("vt_symbol")
    assert by_symbol["identity_feature_status"].eq("complete").all()
    assert by_symbol.loc[
        "600001.SSE", "identity_cycle_relative_return"
    ] == pytest.approx((12.2 / 9.0 - 107.0 / 95.0) * 100.0)
    assert by_symbol.loc["600001.SSE", "identity_strong_day_count_cycle"] == 3
    assert by_symbol.loc["600001.SSE", "identity_sessions_since_strong"] == 2
    assert by_symbol.loc[
        "600001.SSE", "identity_turnover_median_20d"
    ] > 100_000_000.0
    assert bool(by_symbol.loc["600001.SSE", "identity_capacity_passed"])


def test_dynamic_rank_is_invariant_to_entry_day_and_future_prices() -> None:
    periods = build_observed_cycle_periods(_cycle_states(), _candidate_spells())
    baseline = build_dynamic_cycle_leaders(
        periods,
        _candidate_spells(),
        _target_sessions(),
        _stock_bars(),
        _concept_bars(),
    )
    changed_bars = _stock_bars().copy()
    future = pd.to_datetime(changed_bars["trade_date"]).ge(pd.Timestamp("2025-01-09"))
    changed_bars.loc[future, ["open_price", "high_price", "low_price", "close_price"]] = 99.0
    changed = build_dynamic_cycle_leaders(
        periods,
        _candidate_spells(),
        _target_sessions(),
        changed_bars,
        _concept_bars(),
    )
    columns = [
        "cycle_id",
        "entry_date",
        "vt_symbol",
        "dynamic_rank",
        "dynamic_excess_return_pct",
        "feature_cutoff_date",
        "identity_feature_status",
        "identity_cycle_relative_return",
        "identity_strong_day_count_cycle",
        "identity_sessions_since_strong",
        "identity_turnover_median_20d",
        "identity_capacity_passed",
    ]

    pd.testing.assert_frame_equal(baseline[columns], changed[columns])


def test_dynamic_rank_rejects_realized_outcome_columns() -> None:
    periods = build_observed_cycle_periods(_cycle_states(), _candidate_spells())
    leaked = _candidate_spells().assign(realized_return_rank=1)

    with pytest.raises(ValueError, match="realized"):
        build_dynamic_cycle_leaders(
            periods,
            leaked,
            _target_sessions(),
            _stock_bars(),
            _concept_bars(),
        )


def test_cycle_summary_lists_every_period_and_both_top3_views() -> None:
    periods = build_observed_cycle_periods(_cycle_states(), _candidate_spells())
    realized = build_realized_cycle_leaders(
        periods,
        _candidate_spells(),
        _stock_bars(),
        _concept_bars(),
    )
    dynamic = build_dynamic_cycle_leaders(
        periods,
        _candidate_spells(),
        _target_sessions(),
        _stock_bars(),
        _concept_bars(),
    )
    summary = build_cycle_leader_summary(periods, realized, dynamic)

    assert len(summary) == 2
    completed = summary.loc[summary["cycle_id"].eq(COMPLETED_CYCLE)].iloc[0]
    assert completed["realized_market_top3"].split(" | ")[0].startswith("甲股份")
    assert completed["realized_return_top3"].split(" | ")[0].startswith("乙股份")
    assert completed["dynamic_sessions"] == 2
    assert completed["qualified_dynamic_sessions"] == 1
