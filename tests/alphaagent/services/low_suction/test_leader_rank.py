from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.leader_rank import (
    RANK_BLOCK_WEIGHTS,
    rank_concept_leaders,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _features(count: int = 5, *, cutoff: datetime | None = None) -> pd.DataFrame:
    resolved_cutoff = cutoff or datetime(2026, 7, 15, 15, 0, tzinfo=SHANGHAI)
    rows = []
    for index in range(count):
        strength = float(count - index)
        rows.append(
            {
                "sector_id": "THEME_A",
                "cutoff": resolved_cutoff,
                "feature_cutoff": resolved_cutoff,
                "vt_symbol": f"60000{index}.SSE",
                "turnover": strength * 100_000_000,
                "relative_strength_5d": strength,
                "relative_strength_10d": strength,
                "relative_strength_20d": strength,
                "limit_up_count_20d": strength,
                "strong_day_count_20d": strength,
                "sessions_since_strong": float(index),
                "max_drawdown_20d_pct": -float(index),
                "divergence_relative_return": strength,
                "ma10_hold_ratio": strength / count,
                "turnover_median_20d": strength * 100_000_000,
                "turnover_nonzero_ratio": 1.0,
                "concept_correlation_20d": strength / count,
                "launch_lead_sessions": strength,
                "intraday_lead_ratio": strength / count,
            }
        )
    return pd.DataFrame(rows)


def test_rank_blocks_are_fixed_equal_weights() -> None:
    assert RANK_BLOCK_WEIGHTS == {
        "relative_strength_score": 0.2,
        "active_gene_score": 0.2,
        "resilience_score": 0.2,
        "liquidity_score": 0.2,
        "concept_leadership_score": 0.2,
    }


def test_ranking_is_deterministic_and_marks_top_three() -> None:
    ranked = rank_concept_leaders(_features(), membership_mode="strict")

    assert ranked["rank"].tolist() == [1, 2, 3, 4, 5]
    assert ranked["is_top3"].tolist() == [True, True, True, False, False]
    assert ranked.iloc[0]["vt_symbol"] == "600000.SSE"
    assert set(ranked["evidence_level"]) == {"strict"}


def test_proxy_membership_can_only_produce_proxy_rank() -> None:
    ranked = rank_concept_leaders(_features(), membership_mode="current_proxy")

    assert set(ranked["evidence_level"]) == {"membership_proxy"}
    assert set(ranked["membership_mode"]) == {"current_proxy"}


def test_outcome_columns_are_rejected() -> None:
    features = _features()
    features["future_d1_return"] = 99.0

    with pytest.raises(ValueError, match="outcome columns"):
        rank_concept_leaders(features, membership_mode="strict")


def test_features_after_cutoff_are_rejected() -> None:
    features = _features()
    features.loc[0, "feature_cutoff"] = features.loc[0, "cutoff"] + timedelta(minutes=1)

    with pytest.raises(ValueError, match="after cutoff"):
        rank_concept_leaders(features, membership_mode="strict")


def test_future_group_cannot_change_prior_rank() -> None:
    prior = _features()
    original = rank_concept_leaders(prior, membership_mode="current_proxy")
    future = _features(
        cutoff=datetime(2026, 7, 16, 15, 0, tzinfo=SHANGHAI),
    )
    future["relative_strength_5d"] = future["relative_strength_5d"] * -100

    combined = rank_concept_leaders(
        pd.concat([prior, future], ignore_index=True),
        membership_mode="current_proxy",
    )
    prior_again = combined.loc[combined["cutoff"] == prior.iloc[0]["cutoff"]]

    assert prior_again["vt_symbol"].tolist() == original["vt_symbol"].tolist()
    assert prior_again["rank"].tolist() == original["rank"].tolist()


def test_low_capacity_stock_does_not_receive_false_liquidity_score() -> None:
    features = _features(count=2)
    features.loc[0, ["turnover", "turnover_median_20d"]] = 1.0
    features.loc[0, "turnover_nonzero_ratio"] = 0.1

    ranked = rank_concept_leaders(features, membership_mode="strict")
    by_symbol = ranked.set_index("vt_symbol")

    assert (
        by_symbol.loc["600000.SSE", "liquidity_score"]
        < by_symbol.loc["600001.SSE", "liquidity_score"]
    )


def test_ties_use_turnover_then_symbol() -> None:
    features = _features(count=3)
    factor_columns = [
        column
        for column in features.columns
        if column not in {"sector_id", "cutoff", "feature_cutoff", "vt_symbol", "turnover"}
    ]
    features[factor_columns] = 1.0
    features["turnover"] = [100.0, 300.0, 300.0]

    ranked = rank_concept_leaders(features, membership_mode="strict")

    assert ranked["vt_symbol"].tolist() == [
        "600001.SSE",
        "600002.SSE",
        "600000.SSE",
    ]
