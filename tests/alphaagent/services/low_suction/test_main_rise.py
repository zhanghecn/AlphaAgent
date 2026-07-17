from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.main_rise import build_main_rise_states


def _bars(
    sector_id: str = "THEME_A",
    *,
    count: int = 35,
    start: date = date(2025, 1, 2),
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_id": [sector_id] * count,
            "trade_date": [start + timedelta(days=index) for index in range(count)],
            "close_price": [100.0 + index * 2.0 for index in range(count)],
            "turnover": [1_000_000.0 + index * 10_000.0 for index in range(count)],
        }
    )


def test_increasing_concept_enters_approved_main_rise_state() -> None:
    states = build_main_rise_states(_bars())
    last = states.iloc[-1]

    assert last["state"] == "MAIN_RISE_CONFIRMED"
    assert last["close_price"] > last["ma10"] > last["ma20"]
    assert last["ma10"] > last["ma10_shift_5"]
    assert last["ma20"] > last["ma20_shift_5"]
    assert last["source_cutoff_date"] == last["trade_date"]


def test_first_twenty_four_sessions_are_unknown() -> None:
    states = build_main_rise_states(_bars(count=24))

    assert set(states["state"]) == {"UNKNOWN"}


def test_flat_concept_is_not_main_rise() -> None:
    bars = _bars()
    bars["close_price"] = 100.0

    states = build_main_rise_states(bars)

    assert states.iloc[-1]["state"] == "NOT_MAIN_RISE"


def test_future_mutation_cannot_change_prior_state() -> None:
    bars = _bars()
    original = build_main_rise_states(bars)
    cutoff = pd.Timestamp(bars.iloc[-6]["trade_date"])
    original_row = original.loc[original["trade_date"] == cutoff].iloc[0]

    mutated = bars.copy()
    mutated.loc[pd.to_datetime(mutated["trade_date"]) > cutoff, "close_price"] = 1.0
    mutated_row = build_main_rise_states(mutated)
    mutated_row = mutated_row.loc[mutated_row["trade_date"] == cutoff].iloc[0]

    assert mutated_row["state"] == original_row["state"]
    assert mutated_row["ma10"] == pytest.approx(original_row["ma10"])
    assert mutated_row["ma20"] == pytest.approx(original_row["ma20"])


def test_sparse_sector_dates_are_not_forward_filled() -> None:
    complete = _bars("COMPLETE", count=35)
    sparse = _bars("SPARSE", count=35).drop(index=20)
    combined = pd.concat([complete, sparse], ignore_index=True)

    states = build_main_rise_states(combined)
    complete_last = states.loc[states["sector_id"] == "COMPLETE"].iloc[-1]
    sparse_last = states.loc[states["sector_id"] == "SPARSE"].iloc[-1]

    assert complete_last["state"] == "MAIN_RISE_CONFIRMED"
    assert sparse_last["state"] == "UNKNOWN"


def test_continuous_features_remain_features_not_hard_gates() -> None:
    bars = _bars()
    bars["turnover"] = 0.0

    last = build_main_rise_states(bars).iloc[-1]

    assert last["state"] == "MAIN_RISE_CONFIRMED"
    assert "return_5d_pct" in last.index
    assert "distance_from_20d_high_pct" in last.index
    assert "turnover_ratio_5d" in last.index


def test_missing_required_column_is_rejected() -> None:
    with pytest.raises(ValueError, match="close_price"):
        build_main_rise_states(_bars().drop(columns=["close_price"]))
