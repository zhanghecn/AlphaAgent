from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.prebreakout_ignition import (
    MEMBERSHIP_EVIDENCE_LEVEL,
    build_breakout_transition_events,
    build_prebreakout_diffusion_outcomes,
    build_prebreakout_member_features,
    build_prebreakout_observation_pairs,
    build_prebreakout_stock_features,
    evaluate_prebreakout_diffusion,
    evaluate_prebreakout_features,
    prebreakout_feature_diagnostics,
)


def test_breakout_events_emit_only_false_to_true_transitions() -> None:
    events = build_breakout_transition_events(_concept_features())

    assert events["breakout_date"].tolist() == [pd.Timestamp("2025-03-12")]
    assert events["time_block"].tolist() == ["block_1"]


def test_transition_history_before_cutoff_ignores_future_mutation() -> None:
    baseline = build_breakout_transition_events(_concept_features())
    changed = _concept_features()
    changed.loc[changed["trade_date"].gt("2025-03-20"), "anchor_breakout_20"] = True

    mutated = build_breakout_transition_events(changed)

    pd.testing.assert_frame_equal(
        baseline.loc[baseline["breakout_date"].le("2025-03-20")].reset_index(
            drop=True
        ),
        mutated.loc[mutated["breakout_date"].le("2025-03-20")].reset_index(
            drop=True
        ),
    )


def test_controls_share_sector_block_and_have_twenty_session_exclusion() -> None:
    features = _concept_features()
    events = build_breakout_transition_events(features)

    pairs = build_prebreakout_observation_pairs(
        events,
        features,
        leads=(5,),
        max_events_per_block=20,
    )

    assert pairs.groupby("pair_id")["sample_role"].agg(set).eq(
        {"positive", "control"}
    ).all()
    controls = pairs.loc[pairs["sample_role"].eq("control")]
    assert controls["nearest_breakout_distance"].gt(10).all()
    assert controls["time_block"].eq("block_1").all()


def test_event_pairing_does_not_read_price_values() -> None:
    features = _concept_features()
    events = build_breakout_transition_events(features)
    baseline = build_prebreakout_observation_pairs(events, features, leads=(5,))
    changed = features.copy()
    changed["close_price"] *= 3
    changed["turnover"] *= 5

    mutated = build_prebreakout_observation_pairs(events, changed, leads=(5,))

    identity = [
        "pair_id",
        "event_id",
        "sector_id",
        "lead_days",
        "sample_role",
        "observation_date",
        "observation_position",
        "time_block",
        "nearest_breakout_distance",
    ]
    pd.testing.assert_frame_equal(baseline[identity], mutated[identity])


def test_stock_features_use_two_nonoverlapping_five_session_windows() -> None:
    rows = build_prebreakout_stock_features(_stock_bars())
    stock = rows.loc[rows["vt_symbol"].eq("600001.SSE")]
    last = stock.iloc[-1]
    closes = _stock_bars().loc[
        _stock_bars()["vt_symbol"].eq("600001.SSE"), "close_price"
    ].to_numpy()

    assert last["return_5d_pct"] == pytest.approx((closes[-1] / closes[-6] - 1) * 100)
    assert last["return_previous_5d_pct"] == pytest.approx(
        (closes[-6] / closes[-11] - 1) * 100
    )


def test_stock_features_before_cutoff_ignore_future_prices() -> None:
    baseline = build_prebreakout_stock_features(_stock_bars())
    changed = _stock_bars()
    changed.loc[changed["trade_date"].gt("2025-02-20"), "close_price"] *= 3
    changed.loc[changed["trade_date"].gt("2025-02-20"), "turnover"] *= 3

    mutated = build_prebreakout_stock_features(changed)

    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"].le("2025-02-20")].reset_index(
            drop=True
        ),
        mutated.loc[mutated["trade_date"].le("2025-02-20")].reset_index(
            drop=True
        ),
    )


def test_member_features_measure_ignition_breadth_and_top3() -> None:
    panel, leaders = build_prebreakout_member_features(
        _observation_pairs(),
        _memberships(),
        _member_stock_features(),
    )
    positive = panel.loc[panel["sample_role"].eq("positive")].iloc[0]

    assert positive["member_count"] == 4
    assert positive["ignition_share_5d_pct"] == 50.0
    assert positive["early_leader_symbol"] == "600001.SSE"
    assert positive["positive_breadth_5d_pct"] == 75.0
    assert len(
        leaders.loc[
            leaders["pair_id"].eq(positive["pair_id"])
            & leaders["sample_role"].eq("positive")
        ]
    ) == 4


def test_member_features_reject_unlabelled_membership() -> None:
    with pytest.raises(ValueError, match="evidence_level"):
        build_prebreakout_member_features(
            _observation_pairs(),
            _memberships().drop(columns="evidence_level"),
            _member_stock_features(),
        )


def test_feature_evaluation_uses_complete_pairs_and_reports_auc() -> None:
    metrics = evaluate_prebreakout_features(_feature_panel(), block_count=5)
    pooled = metrics.loc[
        metrics["scope"].eq("pooled")
        & metrics["lead_days"].eq(5)
        & metrics["feature"].eq("ignition_share_5d_pct")
    ].iloc[0]

    assert pooled["pairs"] == 10
    assert pooled["matched_positive_higher_rate_pct"] == 100.0
    assert pooled["rank_auc"] == 1.0


def test_feature_candidate_requires_four_stable_blocks() -> None:
    diagnostics = prebreakout_feature_diagnostics(_stable_feature_metrics())

    assert diagnostics[0]["status"] == "candidate_for_forward_validation"


def test_later_outcomes_keep_early_leader_identity_frozen() -> None:
    outcomes = build_prebreakout_diffusion_outcomes(
        _outcome_observations(),
        _early_member_ledger(),
        _memberships(),
        _outcome_stock_bars(),
        _concept_calendar(),
        future_days=(5,),
    )
    row = outcomes.loc[outcomes["sample_role"].eq("positive")].iloc[0]

    assert row["early_leader_symbol"] == "600001.SSE"
    assert bool(row["early_leader_retained_top3"])
    assert row["follower_positive_breadth_pct"] == 100.0


def test_diffusion_comparison_reports_matched_difference() -> None:
    metrics = evaluate_prebreakout_diffusion(_diffusion_outcomes(), block_count=5)
    pooled = metrics.loc[
        metrics["scope"].eq("pooled")
        & metrics["lead_days"].eq(5)
        & metrics["future_days"].eq(5)
    ].iloc[0]

    assert pooled["pairs"] == 10
    assert pooled["median_follower_return_difference_pct"] == 4.0


def _concept_features() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=100)
    breakout_date = dates[49]
    frame = pd.DataFrame(
        {
            "sector_id": "BK001",
            "concept_name": "测试概念",
            "trade_date": dates,
            "close_price": 100.0 + np.arange(len(dates), dtype=float),
            "turnover": 1_000_000.0 + np.arange(len(dates), dtype=float) * 1_000,
            "anchor_breakout_20": False,
            "return_1d_pct": np.linspace(-1.0, 1.0, len(dates)),
            "return_3d_pct": np.linspace(-2.0, 2.0, len(dates)),
            "return_5d_pct": np.linspace(-3.0, 3.0, len(dates)),
            "return_10d_pct": np.linspace(-4.0, 4.0, len(dates)),
            "relative_gain_5d_percentile": 0.5,
            "turnover_expansion": 1.0,
        }
    )
    frame.loc[frame["trade_date"].between(breakout_date, dates[51]), "anchor_breakout_20"] = True
    return frame


def _stock_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=45)
    rows: list[dict[str, object]] = []
    for stock_index, symbol in enumerate(("600001.SSE", "600002.SSE")):
        for day, trade_date in enumerate(dates):
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "close_price": 100.0 + day * (1.0 + stock_index * 0.1),
                    "turnover": 1_000_000.0 + day * 10_000 + stock_index * 50_000,
                }
            )
    return pd.DataFrame(rows)


def _observation_pairs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pair_id": ["pair-1", "pair-1"],
            "event_id": ["event-1", "event-1"],
            "sector_id": ["BK001", "BK001"],
            "concept_name": ["测试概念", "测试概念"],
            "breakout_date": pd.to_datetime(["2025-02-10", "2025-02-10"]),
            "lead_days": [5, 5],
            "sample_role": ["positive", "control"],
            "observation_date": pd.to_datetime(["2025-02-03", "2025-01-20"]),
            "observation_position": [20, 10],
            "time_block": ["block_1", "block_1"],
            "nearest_breakout_distance": [5, 20],
            "concept_return_1d_pct": [1.0, -1.0],
            "concept_return_3d_pct": [2.0, -2.0],
            "concept_return_5d_pct": [3.0, -3.0],
            "concept_return_10d_pct": [4.0, -4.0],
            "relative_gain_5d_percentile": [0.8, 0.2],
            "concept_turnover_expansion": [1.2, 0.8],
        }
    )


def _memberships() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_id": "BK001",
            "vt_symbol": [
                "600001.SSE",
                "600002.SSE",
                "600003.SSE",
                "600004.SSE",
            ],
            "stock_name": ["甲", "乙", "丙", "丁"],
            "evidence_level": MEMBERSHIP_EVIDENCE_LEVEL,
        }
    )


def _member_stock_features() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for trade_date, multiplier in (
        (pd.Timestamp("2025-02-03"), 1.0),
        (pd.Timestamp("2025-01-20"), 0.5),
    ):
        for index, symbol in enumerate(_memberships()["vt_symbol"]):
            return_5d = (8.0, 5.0, 2.0, -1.0)[index] * multiplier
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "close_price": 100.0 + return_5d,
                    "return_1d_pct": (2.0, 1.0, -0.5, -1.0)[index],
                    "return_5d_pct": return_5d,
                    "return_previous_5d_pct": (-1.0, 1.0, -2.0, -3.0)[index],
                    "strong_day_count_5": (1, 1, 0, 0)[index],
                    "turnover": (400.0, 300.0, 200.0, 100.0)[index],
                    "turnover_expansion": (1.5, 1.2, 1.0, 0.8)[index],
                }
            )
    return pd.DataFrame(rows)


def _feature_panel() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for pair_index in range(10):
        for role, value in (("positive", 10.0 + pair_index), ("control", float(pair_index))):
            row: dict[str, object] = {
                "pair_id": f"pair-{pair_index}",
                "lead_days": 5,
                "sample_role": role,
                "time_block": f"block_{pair_index // 2 + 1}",
            }
            for feature in _all_feature_names():
                row[feature] = value
            rows.append(row)
    return pd.DataFrame(rows)


def _stable_feature_metrics() -> pd.DataFrame:
    rows = [
        {
            "lead_days": 5,
            "feature": "ignition_share_5d_pct",
            "scope": "pooled",
            "pairs": 200,
            "rank_auc": 0.65,
        }
    ]
    rows.extend(
        {
            "lead_days": 5,
            "feature": "ignition_share_5d_pct",
            "scope": f"block_{block}",
            "pairs": 40,
            "rank_auc": 0.60 if block <= 4 else 0.54,
        }
        for block in range(1, 6)
    )
    return pd.DataFrame(rows)


def _outcome_observations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pair_id": ["pair-1", "pair-1"],
            "event_id": ["event-1", "event-1"],
            "sector_id": ["BK001", "BK001"],
            "lead_days": [5, 5],
            "sample_role": ["positive", "control"],
            "observation_date": pd.to_datetime(["2025-01-15", "2025-01-08"]),
            "observation_position": [9, 4],
            "time_block": ["block_1", "block_1"],
        }
    )


def _early_member_ledger() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for role, observation_date in (
        ("positive", pd.Timestamp("2025-01-15")),
        ("control", pd.Timestamp("2025-01-08")),
    ):
        for rank, symbol in enumerate(_memberships()["vt_symbol"], start=1):
            rows.append(
                {
                    "pair_id": "pair-1",
                    "sample_role": role,
                    "sector_id": "BK001",
                    "lead_days": 5,
                    "time_block": "block_1",
                    "observation_date": observation_date,
                    "vt_symbol": symbol,
                    "early_return_5d_pct": float(5 - rank),
                    "early_rank": rank,
                    "early_leader": rank == 1,
                }
            )
    return pd.DataFrame(rows)


def _concept_calendar() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_id": "BK001",
            "trade_date": pd.bdate_range("2025-01-02", periods=30),
        }
    )


def _outcome_stock_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=30)
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(_memberships()["vt_symbol"]):
        for day, trade_date in enumerate(dates):
            close = 100.0 + day * (4 - symbol_index)
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "close_price": close,
                    "turnover": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _diffusion_outcomes() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for pair_index in range(10):
        for role, follower_return in (("positive", 6.0), ("control", 2.0)):
            rows.append(
                {
                    "pair_id": f"pair-{pair_index}",
                    "lead_days": 5,
                    "future_days": 5,
                    "sample_role": role,
                    "time_block": f"block_{pair_index // 2 + 1}",
                    "early_leader_return_5d_pct": float(pair_index),
                    "early_leader_retained_top1": role == "positive",
                    "early_leader_retained_top3": True,
                    "follower_median_return_pct": follower_return,
                    "follower_positive_breadth_pct": 100.0 if role == "positive" else 50.0,
                }
            )
    return pd.DataFrame(rows)


def _all_feature_names() -> tuple[str, ...]:
    return (
        "concept_return_1d_pct",
        "concept_return_3d_pct",
        "concept_return_5d_pct",
        "concept_return_10d_pct",
        "relative_gain_5d_percentile",
        "concept_turnover_expansion",
        "same_day_positive_breadth_pct",
        "positive_breadth_5d_pct",
        "breadth_5d_change_pct_points",
        "ignition_share_5d_pct",
        "leader_return_5d_pct",
        "top3_mean_return_5d_pct",
        "top3_turnover_share_pct",
        "top3_mean_turnover_expansion",
        "top3_positive_gain_concentration_pct",
    )
