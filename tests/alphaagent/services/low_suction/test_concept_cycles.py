from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.concept_cycles import (
    MARKET_BENCHMARK_SYMBOLS,
    CycleResearchInputs,
    CycleDefinition,
    apply_three_day_hysteresis,
    build_cycle_study_report,
    build_market_returns,
    build_cycle_candidates,
    choose_stable_cycle_definition,
    evaluate_cycle_definitions,
    select_cycle_definition,
)
from alphaagent.server.services.low_suction.research_protocol import (
    DataFingerprint,
    build_protocol_split,
    default_protocol,
)


def _market_returns(count: int = 80) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=count)
    return pd.DataFrame(
        {
            "trade_date": dates,
            "market_return_10d": np.zeros(count),
            "research_date_valid": np.ones(count, dtype=bool),
        }
    )


def _concept_bars(
    count: int = 80,
    *,
    future_close: float | None = None,
) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=count)
    rows: list[dict[str, object]] = []
    for sector_index, sector_id in enumerate(("BK_A", "BK_B", "BK_C")):
        for index, trade_date in enumerate(dates):
            close = 100.0 + index * (1.0 - sector_index * 0.15)
            if future_close is not None and sector_id == "BK_A" and index == count - 1:
                close = future_close
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": trade_date,
                    "close_price": close,
                }
            )
    return pd.DataFrame(rows)


def _qualification_frame(values: list[bool], sector_id: str = "BK_A") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_id": sector_id,
            "trade_date": pd.bdate_range("2026-06-01", periods=len(values)),
            "definition": CycleDefinition.TREND_ORDER.value,
            "history_segment": 0,
            "qualifies": values,
        }
    )


def test_future_concept_bar_does_not_change_prior_cycle_state() -> None:
    original = build_cycle_candidates(_concept_bars(), _market_returns())
    mutated = build_cycle_candidates(
        _concept_bars(future_close=9_999.0),
        _market_returns(),
    )
    cutoff = pd.Timestamp(_market_returns().iloc[-2]["trade_date"])

    pd.testing.assert_frame_equal(
        original.loc[original["trade_date"] <= cutoff].reset_index(drop=True),
        mutated.loc[mutated["trade_date"] <= cutoff].reset_index(drop=True),
    )


def test_cycle_research_rejects_stock_outcome_columns() -> None:
    bars = _concept_bars().assign(net_return_pct=10.0)

    with pytest.raises(ValueError, match="outcome columns"):
        build_cycle_candidates(bars, _market_returns())


def test_sparse_concept_date_starts_a_new_indicator_segment() -> None:
    market = _market_returns(50)
    bars = _concept_bars(50)
    missing_date = market.iloc[30]["trade_date"]
    bars = bars.loc[
        ~((bars["sector_id"] == "BK_A") & (bars["trade_date"] == missing_date))
    ]

    candidates = build_cycle_candidates(bars, market)
    next_date = market.iloc[31]["trade_date"]
    row = candidates.loc[
        (candidates["definition"] == CycleDefinition.TREND_ORDER.value)
        & (candidates["sector_id"] == "BK_A")
        & (candidates["trade_date"] == next_date)
    ].iloc[0]

    assert row["calendar_gap"]
    assert row["history_segment"] == 1
    assert pd.isna(row["ma20"])
    assert not row["qualifies"]
    assert not row["in_cycle"]


def test_one_day_break_stays_in_cycle_and_third_miss_exits() -> None:
    result = apply_three_day_hysteresis(
        _qualification_frame([True, True, True, False, True, False, False, False])
    )

    assert result["in_cycle"].tolist() == [True, True, True, True, True, True, True, False]
    assert result["miss_count"].tolist() == [0, 0, 0, 1, 0, 1, 2, 3]
    assert result["cycle_ended"].tolist() == [False] * 7 + [True]
    assert result.iloc[-1]["completed_cycle_days"] == 7


def test_strict_entry_gate_is_not_reused_as_cycle_exit_condition() -> None:
    frame = _qualification_frame([True, False, False, False, False])
    frame["entry_qualifies"] = [True, False, False, False, False]
    frame["sustain_qualifies"] = [True, True, True, True, True]

    result = apply_three_day_hysteresis(frame)

    assert result["in_cycle"].tolist() == [True] * 5
    assert result["miss_count"].tolist() == [0] * 5
    assert not result["cycle_ended"].any()


def test_false_start_is_confirmed_only_when_cycle_ends() -> None:
    false_start = apply_three_day_hysteresis(
        _qualification_frame([True, False, False, False])
    )
    mature = apply_three_day_hysteresis(
        _qualification_frame([True, True, True, False, False, False])
    )

    assert false_start.loc[:2, "false_start"].isna().all()
    assert bool(false_start.iloc[-1]["false_start"])
    assert not bool(mature.iloc[-1]["false_start"])


def test_cycle_identity_is_unique_across_concepts() -> None:
    frame = pd.concat(
        [
            _qualification_frame([True, True], "BK_A"),
            _qualification_frame([True, True], "BK_B"),
        ],
        ignore_index=True,
    )
    result = apply_three_day_hysteresis(frame)

    assert result["cycle_id"].dropna().nunique() == 2


def test_persistence_requires_the_exact_next_research_date() -> None:
    frame = _qualification_frame([True, True, True, True])
    frame["calendar_position"] = [0, 1, 3, 4]
    candidates = apply_three_day_hysteresis(frame)
    metrics = evaluate_cycle_definitions(
        candidates,
        evaluation_dates=tuple(frame["trade_date"].dt.date),
    )
    metric = metrics.iloc[0]

    assert metric["events"] == 1
    assert metric["eligible_next_day_states"] == 1
    assert metric["next_day_persistence_rate"] == pytest.approx(1.0)


def test_three_of_five_fold_wins_are_required_for_stable_definition() -> None:
    stable = choose_stable_cycle_definition(
        ("trend_order", "relative_trend", "trend_order", "breakout_trend", "trend_order")
    )
    unstable = choose_stable_cycle_definition(
        ("trend_order", "relative_trend", "breakout_trend", "relative_trend", "trend_order")
    )

    assert stable == CycleDefinition.TREND_ORDER
    assert unstable is None


def test_market_composite_does_not_read_future_benchmark_closes() -> None:
    dates = pd.bdate_range("2026-01-05", periods=20)
    rows = [
        {
            "trade_date": trade_date,
            "vt_symbol": symbol,
            "close_price": 100.0 + date_index + symbol_index,
        }
        for symbol_index, symbol in enumerate(MARKET_BENCHMARK_SYMBOLS)
        for date_index, trade_date in enumerate(dates)
    ]
    bars = pd.DataFrame(rows)
    original = build_market_returns(bars, research_dates=tuple(dates.date))
    mutated_bars = bars.copy()
    mutated_bars.loc[mutated_bars["trade_date"] == dates[-1], "close_price"] = 9_999.0
    mutated = build_market_returns(mutated_bars, research_dates=tuple(dates.date))

    pd.testing.assert_frame_equal(original.iloc[:-1], mutated.iloc[:-1])


def test_cycle_selection_rejects_loaded_holdout_values() -> None:
    market = _market_returns(100)
    candidates = build_cycle_candidates(_concept_bars(100), market)
    split = build_protocol_split(
        tuple(pd.to_datetime(market["trade_date"]).dt.date),
        default_protocol(),
    )

    with pytest.raises(ValueError, match="holdout values"):
        select_cycle_definition(candidates, split)


def test_cycle_report_keeps_trade_metrics_null_and_holdout_unread() -> None:
    protocol = default_protocol()
    full_market = _market_returns(100)
    reliable_dates = tuple(pd.to_datetime(full_market["trade_date"]).dt.date)
    split = build_protocol_split(reliable_dates, protocol)
    concept_bars = _concept_bars(80)
    discovery_market = full_market.iloc[:80].copy()
    candidates = build_cycle_candidates(concept_bars, discovery_market)
    selection = select_cycle_definition(candidates, split)
    fingerprint = DataFingerprint(
        algorithm="sha256",
        digest="sha256:test",
        rows=len(concept_bars),
        columns=tuple(concept_bars.columns),
    )
    inputs = CycleResearchInputs(
        concept_bars=concept_bars,
        market_returns=discovery_market,
        split=split,
        reliable_dates=reliable_dates,
        input_fingerprint="sha256:combined",
        component_fingerprints=(("canonical_concept_bars", fingerprint),),
    )

    report = build_cycle_study_report(inputs, selection, protocol)

    assert report["formal_metrics"] is None
    assert report["stock_trade_outcomes_read"] is False
    assert report["holdout_price_values_read"] is False
    assert report["date_split"]["discovery_dates"] == 80
    assert report["date_split"]["holdout_dates"] == 20
    assert all("win_rate" not in metric for metric in report["discovery_definition_metrics"])
