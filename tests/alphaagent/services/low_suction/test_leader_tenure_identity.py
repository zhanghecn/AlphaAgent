from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from alphaagent.server.services.low_suction.leader_tenure_identity import (
    build_causal_leader_tenures,
    select_primary_concept_events,
)


def test_top3_tenure_survives_three_rank_misses_then_expires() -> None:
    paths = _paths(
        ranks=[2, 4, None, 1, 5, 5, 5, 5],
        campaign_id="campaign-a",
    )

    result = build_causal_leader_tenures(paths)

    assert result["leader_tenure_active"].tolist() == [
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert result["sessions_since_top3"].tolist() == [0, 1, 2, 0, 1, 2, 3, 4]
    assert result["tenure_rank"].astype("Int64").tolist() == [2, 2, 2, 1, 1, 1, 1, 1]
    assert result["tenure_top3_days"].tolist() == [1, 1, 1, 2, 2, 2, 2, 2]
    assert result["tenure_best_rank"].astype("Int64").tolist() == [2, 2, 2, 1, 1, 1, 1, 1]
    assert result["current_dynamic_rank"].astype("Int64").tolist() == [
        2,
        4,
        pd.NA,
        1,
        5,
        5,
        5,
        5,
    ]
    assert result["dynamic_top3"].equals(result["leader_tenure_active"])
    assert result.loc[2, "dynamic_rank"] == 2


@pytest.mark.parametrize("failure_column", ["campaign_active", "structure_intact"])
def test_campaign_or_structure_failure_ends_tenure_immediately(
    failure_column: str,
) -> None:
    paths = _paths(ranks=[1, 4, 4], campaign_id="campaign-a")
    paths.loc[1, failure_column] = False

    result = build_causal_leader_tenures(paths)

    assert result["leader_tenure_active"].tolist() == [True, False, False]
    assert result["tenure_end_reason"].tolist() == [None, failure_column, None]


def test_tenure_prefix_is_independent_of_later_rows() -> None:
    paths = _paths(ranks=[2, 4, 1, 5, 5], campaign_id="campaign-a")
    full = build_causal_leader_tenures(paths)

    for end in range(1, len(paths) + 1):
        prefix = build_causal_leader_tenures(paths.iloc[:end].copy())
        assert_frame_equal(
            prefix.reset_index(drop=True),
            full.iloc[:end].reset_index(drop=True),
            check_dtype=True,
        )


def test_tenure_rejects_outcome_columns() -> None:
    paths = _paths(ranks=[1], campaign_id="campaign-a")
    paths["d1_net_return_pct"] = 3.0

    with pytest.raises(ValueError, match="outcome columns"):
        build_causal_leader_tenures(paths)


def test_cross_concept_breadth_is_attached_without_filtering_rows() -> None:
    first = _paths(ranks=[1, 4], campaign_id="campaign-a", sector_id="BK_A")
    second = _paths(ranks=[2, 2], campaign_id="campaign-b", sector_id="BK_B")
    paths = pd.concat([first, second], ignore_index=True)

    result = build_causal_leader_tenures(paths)

    by_date = result.groupby("trade_date", sort=True).first()
    assert by_date["active_tenure_concepts"].tolist() == [2, 2]
    assert by_date["current_top3_concepts"].tolist() == [2, 1]
    assert by_date["maximum_top3_days"].tolist() == [1, 2]
    assert len(result) == len(paths)


def test_primary_concept_selection_is_causal_unique_and_order_invariant() -> None:
    date = pd.Timestamp("2026-01-08")
    path_parts = []
    definitions = (
        ("campaign-a", "BK_A", 2, 1, 12.0, 5.0, 1.2),
        ("campaign-strong", "BK_STRONG", 3, 2, 15.0, 7.0, 1.8),
        ("campaign-c", "BK_C", 3, 3, 20.0, 9.0, 2.0),
    )
    for campaign_id, sector_id, top3_days, best_rank, gain, excess, turnover in definitions:
        part = _paths(
            ranks=[best_rank] * top3_days,
            campaign_id=campaign_id,
            sector_id=sector_id,
        )
        part["concept_gain_pct"] = gain
        part["concept_excess_gain_pct"] = excess
        part["turnover_expansion"] = turnover
        part["trade_date"] = pd.date_range(
            date - pd.Timedelta(days=top3_days - 1),
            periods=top3_days,
            freq="D",
        )
        part["feature_cutoff_date"] = part["trade_date"]
        path_parts.append(part)
    tenure_paths = build_causal_leader_tenures(
        pd.concat(path_parts, ignore_index=True)
    )
    events = pd.DataFrame(
        [
            {
                "signal_id": f"signal-{campaign_id}",
                "campaign_id": campaign_id,
                "sector_id": sector_id,
                "concept_name": sector_id,
                "vt_symbol": "600001.SSE",
                "stock_name": "样本",
                "signal_date": date,
            }
            for campaign_id, sector_id, *_ in definitions
        ]
    )

    selected = select_primary_concept_events(events, tenure_paths)
    shuffled = select_primary_concept_events(
        events.sample(frac=1.0, random_state=7).reset_index(drop=True),
        tenure_paths.sample(frac=1.0, random_state=9).reset_index(drop=True),
    )

    assert len(selected) == 1
    assert selected.iloc[0]["sector_id"] == "BK_STRONG"
    assert selected.iloc[0]["duplicate_concept_count"] == 3
    assert selected.iloc[0]["active_tenure_concepts"] == 3
    assert_frame_equal(selected, shuffled)


def test_primary_concept_selection_rejects_future_or_return_fields() -> None:
    paths = build_causal_leader_tenures(
        _paths(ranks=[1], campaign_id="campaign-a")
    )
    events = pd.DataFrame(
        [
            {
                "signal_id": "signal-a",
                "campaign_id": "campaign-a",
                "sector_id": "BK_A",
                "vt_symbol": "600001.SSE",
                "signal_date": pd.Timestamp("2026-01-01"),
                "net_return_pct": 5.0,
            }
        ]
    )

    with pytest.raises(ValueError, match="outcome columns"):
        select_primary_concept_events(events, paths)


def _paths(
    *,
    ranks: list[int | None],
    campaign_id: str,
    sector_id: str = "BK_A",
) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(ranks), freq="D")
    rank_values = pd.array(ranks, dtype="Int64")
    return pd.DataFrame(
        {
            "campaign_id": campaign_id,
            "sector_id": sector_id,
            "concept_name": sector_id,
            "trade_date": dates,
            "campaign_day": range(len(ranks)),
            "vt_symbol": "600001.SSE",
            "stock_name": "样本",
            "dynamic_rank": rank_values,
            "dynamic_top3": pd.Series(rank_values).le(3).fillna(False),
            "campaign_active": True,
            "structure_intact": True,
            "concept_gain_pct": 10.0,
            "concept_excess_gain_pct": 5.0,
            "turnover_expansion": 1.5,
            "feature_cutoff_date": dates,
        }
    )
