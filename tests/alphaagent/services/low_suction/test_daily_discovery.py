from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from alphaagent.server.services.low_suction.daily_discovery import (
    _attach_timing_and_split,
    apply_theme_eligibility_guard,
    build_comparison_events,
    build_proxy_rank_features,
    prepare_stock_features,
    summarize_proxy_outcomes,
)


def _stock_bars(count: int = 35) -> pd.DataFrame:
    start = date(2026, 1, 1)
    return pd.DataFrame(
        {
            "vt_symbol": ["600000.SSE"] * count,
            "trade_date": [start + timedelta(days=index) for index in range(count)],
            "open_price": [10.0 + index * 0.1 for index in range(count)],
            "close_price": [10.05 + index * 0.1 for index in range(count)],
            "high_price": [10.1 + index * 0.1 for index in range(count)],
            "low_price": [9.9 + index * 0.1 for index in range(count)],
            "volume": [1_000_000.0] * count,
            "turnover": [10_000_000.0 + index * 100_000 for index in range(count)],
            "change_pct": [1.0] * count,
        }
    )


def test_proxy_repository_has_no_strategy_namespace_dependency() -> None:
    source = Path("alphaagent/server/services/low_suction/repository.py").read_text()

    assert "stock_daily_bars" in source
    assert "sector_daily_bars" in source
    assert "stock_sector_memberships" in source
    assert ".c.type.in_(CONCEPT_SECTOR_TYPES)" in source
    assert ".c.sector_type.in_(CONCEPT_SECTOR_TYPES)" in source
    assert "services.limit_up" not in source
    assert "services.quant" not in source


def test_stock_features_do_not_change_when_future_prices_mutate() -> None:
    bars = _stock_bars()
    dates = tuple(bars["trade_date"])
    original = prepare_stock_features(bars, trading_dates=dates)
    cutoff = pd.Timestamp(bars.iloc[-6]["trade_date"])
    original_row = original.loc[original["trade_date"] == cutoff].iloc[0]

    mutated = bars.copy()
    mutated.loc[pd.to_datetime(mutated["trade_date"]) > cutoff, "close_price"] = 1.0
    changed = prepare_stock_features(mutated, trading_dates=dates)
    changed_row = changed.loc[changed["trade_date"] == cutoff].iloc[0]

    assert changed_row["return_20d_pct"] == original_row["return_20d_pct"]
    assert changed_row["turnover_median_20d"] == original_row["turnover_median_20d"]
    assert changed_row["sessions_since_peak"] == original_row["sessions_since_peak"]


def _rank_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trade_date = pd.Timestamp("2026-07-15")
    concepts = pd.DataFrame(
        [
            {
                "sector_id": "MAIN",
                "trade_date": trade_date,
                "state": "MAIN_RISE_CONFIRMED",
                "rise_cycle_id": "MAIN:2026-07-01",
                "state_age": 5,
                "return_5d_pct": 8.0,
                "return_10d_pct": 15.0,
                "return_20d_pct": 25.0,
            },
            {
                "sector_id": "CONTROL",
                "trade_date": trade_date,
                "state": "NOT_MAIN_RISE",
                "rise_cycle_id": None,
                "state_age": 0,
                "return_5d_pct": -2.0,
                "return_10d_pct": 1.0,
                "return_20d_pct": 2.0,
            },
        ]
    )
    stocks = []
    memberships = []
    for index in range(12):
        symbol = f"600{index:03d}.SSE"
        strength = float(12 - index)
        stocks.append(
            {
                "vt_symbol": symbol,
                "trade_date": trade_date,
                "open_price": 10.2,
                "close_price": 9.8,
                "previous_close": 10.0,
                "ma5": 9.6,
                "ma10": 9.5,
                "volume_ratio_5d": 0.8,
                "return_1d_pct": -2.0,
                "return_5d_pct": strength,
                "return_10d_pct": strength + 2,
                "return_20d_pct": strength + 4,
                "limit_up_count_20d": strength,
                "strong_day_count_20d": strength,
                "sessions_since_strong": float(index),
                "max_drawdown_20d_pct": -float(index),
                "ma10_hold_ratio": strength / 12,
                "turnover": strength * 100_000_000,
                "turnover_median_20d": strength * 100_000_000,
                "turnover_nonzero_ratio": 1.0,
                "prior_strong_day": True,
                "sessions_since_peak": 3.0,
                "drawdown_from_peak_pct": -5.0,
            }
        )
        memberships.extend(
            [
                {"sector_id": "MAIN", "concept_name": "主升概念", "vt_symbol": symbol},
                {"sector_id": "CONTROL", "concept_name": "对照概念", "vt_symbol": symbol},
            ]
        )
    return concepts, pd.DataFrame(stocks), pd.DataFrame(memberships)


def test_proxy_rank_features_keep_only_top_ten_per_concept() -> None:
    concepts, stocks, memberships = _rank_inputs()

    ranked = build_proxy_rank_features(
        concepts,
        stocks,
        memberships,
        signal_dates=(date(2026, 7, 15),),
    )

    assert len(ranked) == 20
    assert ranked.groupby("sector_id")["rank"].max().to_dict() == {
        "CONTROL": 10,
        "MAIN": 10,
    }
    assert set(ranked["evidence_level"]) == {"membership_proxy"}


def test_comparison_events_separate_product_and_falsification_cohorts() -> None:
    concepts, stocks, memberships = _rank_inputs()
    ranked = build_proxy_rank_features(
        concepts,
        stocks,
        memberships,
        signal_dates=(date(2026, 7, 15),),
    )

    comparisons = build_comparison_events(ranked)

    assert set(comparisons["cohort"]) == {
        "main_rise_rank_4_10",
        "non_main_rise_top3",
    }
    assert (comparisons["evidence_level"] == "membership_proxy").all()


def test_proxy_summary_never_exposes_formal_metrics() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "A",
                "vt_symbol": "600000.SSE",
                "trade_date": date(2026, 7, 15),
                "sector_id": "MAIN",
                "family_tags": ("first_divergence",),
                "cohort": "main_rise_top3",
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "time_split": "holdout",
            },
            {
                "event_id": "B",
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 16),
                "sector_id": "MAIN",
                "family_tags": ("first_divergence",),
                "cohort": "main_rise_rank_4_10",
                "active_direction": "SILVER",
                "danger_state": "DANGER",
                "time_split": "holdout",
            },
        ]
    )
    outcomes = pd.DataFrame(
        [
            {"event_id": "A", "exit_key": "entry_plus_1_close", "status": "closed", "net_return_pct": 2.0},
            {"event_id": "B", "exit_key": "entry_plus_1_close", "status": "closed", "net_return_pct": -1.0},
        ]
    )

    summary = summarize_proxy_outcomes(events, outcomes)

    assert summary["status"] == "exploratory_membership_proxy"
    assert summary["formal_metrics"] is None
    assert summary["matrix"][0]["evidence_level"] == "membership_proxy"


def test_timing_merge_normalizes_database_date_dtypes() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["A"],
            "trade_date": [date(2026, 7, 15)],
        }
    )
    timing_labels = pd.DataFrame(
        {
            "trade_date": pd.Series(
                [pd.Timestamp("2026-07-15")],
                dtype="datetime64[us]",
            ),
            "active_direction": ["GOLD"],
            "zone_direction": ["GOLD"],
            "danger_state": ["NORMAL"],
            "market_phase": ["主升"],
        }
    )

    result = _attach_timing_and_split(events, timing_labels)

    assert result.loc[0, "trade_date"] == pd.Timestamp("2026-07-15")
    assert result.loc[0, "active_direction"] == "GOLD"
    assert result.loc[0, "time_split"] == "insufficient_dates"


def test_theme_eligibility_guard_runs_before_formal_candidate_ranking() -> None:
    ranked = pd.DataFrame(
        [
            {"sector_id": "THEME", "trade_date": date(2026, 7, 15), "score": 80},
            {"sector_id": "EVENT", "trade_date": date(2026, 7, 15), "score": 100},
            {"sector_id": "UNKNOWN", "trade_date": date(2026, 7, 15), "score": 90},
        ]
    )
    eligibility = pd.DataFrame(
        [
            {
                "sector_id": "THEME",
                "cutoff": date(2026, 7, 15),
                "eligible": True,
                "eligibility_class": "narrative_theme",
                "eligibility_reason": "qualified",
            },
            {
                "sector_id": "EVENT",
                "cutoff": date(2026, 7, 15),
                "eligible": False,
                "eligibility_class": "mechanical_event",
                "eligibility_reason": "manifest_excluded",
            },
            {
                "sector_id": "UNKNOWN",
                "cutoff": date(2026, 7, 15),
                "eligible": False,
                "eligibility_class": "ambiguous",
                "eligibility_reason": "manifest_excluded",
            },
        ]
    )

    accepted, audited = apply_theme_eligibility_guard(
        ranked,
        eligibility,
        taxonomy_status="qualified_taxonomy",
        taxonomy_version="theme-eligibility-v1",
    )

    assert accepted["sector_id"].tolist() == ["THEME"]
    assert accepted["theme_eligibility_version"].tolist() == [
        "theme-eligibility-v1"
    ]
    assert set(audited.loc[~audited["eligible"], "sector_id"]) == {
        "EVENT",
        "UNKNOWN",
    }
