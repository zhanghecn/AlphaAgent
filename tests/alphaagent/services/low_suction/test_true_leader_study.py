from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.true_leader_study import (
    assign_true_leader_blocks,
    build_cycle_leader_truth,
    build_emotion_cycle_candidates,
    build_point_in_time_stock_features,
    evaluate_true_leader_identity,
    rank_causal_cycle_leaders,
)


def _feature_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-12-02", periods=30)
    strong_positions = {
        "600001.SSE": {21, 28},
        "600002.SSE": {27},
        "002001.SZSE": {29},
        "600004.SSE": set(),
    }
    rows = []
    for symbol, positions in strong_positions.items():
        close = 10.0
        for index, trade_date in enumerate(dates):
            daily_return = 0.006
            if index in positions:
                daily_return = 0.065
            close *= 1.0 + daily_return
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close * 0.995,
                    "high_price": close * 1.01,
                    "low_price": close * 0.99,
                    "close_price": close,
                    "volume": 1_000_000.0 + index * 10_000.0,
                    "turnover": 120_000_000.0 + index * 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _cycle_starts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": "breakout_trend:BK0001:2025-01-10",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "trade_date": pd.Timestamp("2025-01-10"),
                "relative_percentile": 0.90,
                "close_price": 105.0,
                "concept_return_10d": 0.05,
            }
        ]
    )


def _memberships() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sector_id": "BK0001", "vt_symbol": "600001.SSE", "stock_name": "甲股份"},
            {"sector_id": "BK0001", "vt_symbol": "600002.SSE", "stock_name": "乙股份"},
            {"sector_id": "BK0001", "vt_symbol": "002001.SZSE", "stock_name": "丙股份"},
            {"sector_id": "BK0001", "vt_symbol": "600004.SSE", "stock_name": "丁股份"},
        ]
    )


def _qualified_candidates() -> pd.DataFrame:
    features = build_point_in_time_stock_features(_feature_bars())
    return build_emotion_cycle_candidates(_cycle_starts(), _memberships(), features)


def test_stock_features_do_not_change_when_future_bars_change() -> None:
    bars = _feature_bars()
    cutoff = pd.Timestamp("2025-01-06")
    baseline = build_point_in_time_stock_features(bars)
    changed = bars.copy()
    future = changed["trade_date"].gt(cutoff)
    changed.loc[future, ["open_price", "high_price", "low_price", "close_price"]] *= 5
    mutated = build_point_in_time_stock_features(changed)
    columns = [
        "vt_symbol",
        "trade_date",
        "strong_days_10",
        "return_10d_pct",
        "ma5",
        "ma10",
        "ma20",
        "first_strong_sessions_ago_10d",
    ]

    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"].le(cutoff), columns].reset_index(drop=True),
        mutated.loc[mutated["trade_date"].le(cutoff), columns].reset_index(drop=True),
    )


def test_emotion_cycle_gate_builds_three_ignited_main_board_candidates() -> None:
    rows = _qualified_candidates()

    assert set(rows["vt_symbol"]) == {"600001.SSE", "600002.SSE", "002001.SZSE"}
    assert rows["feature_cutoff_date"].eq(pd.Timestamp("2025-01-10")).all()
    assert rows["complete_member_count"].eq(4).all()
    assert rows["recent_ignited_count"].eq(3).all()
    assert rows["evidence_level"].eq("current_membership_and_security_proxy").all()


def test_emotion_cycle_gate_rejects_weak_concept_relative_strength() -> None:
    weak = _cycle_starts().assign(relative_percentile=0.79)
    rows = build_emotion_cycle_candidates(
        weak,
        _memberships(),
        build_point_in_time_stock_features(_feature_bars()),
    )

    assert rows.empty


def test_same_concept_can_have_multiple_distinct_cycles() -> None:
    cycles = pd.concat(
        [
            _cycle_starts(),
            _cycle_starts().assign(cycle_id="breakout_trend:BK0001:2025-01-10:second"),
        ],
        ignore_index=True,
    )
    rows = build_emotion_cycle_candidates(
        cycles,
        _memberships(),
        build_point_in_time_stock_features(_feature_bars()),
    )

    assert rows["cycle_id"].nunique() == 2
    assert len(rows) == 6


def test_emotion_cycle_gate_excludes_chinext_star_and_current_st() -> None:
    memberships = pd.concat(
        [
            _memberships(),
            pd.DataFrame(
                [
                    {"sector_id": "BK0001", "vt_symbol": "300001.SZSE", "stock_name": "创业样本"},
                    {"sector_id": "BK0001", "vt_symbol": "688001.SSE", "stock_name": "科创样本"},
                    {"sector_id": "BK0001", "vt_symbol": "600005.SSE", "stock_name": "*ST样本"},
                ]
            ),
        ],
        ignore_index=True,
    )
    features = build_point_in_time_stock_features(_feature_bars())
    extras = pd.concat(
        [
            features.loc[features["vt_symbol"].eq("600001.SSE")].assign(vt_symbol=symbol)
            for symbol in ("300001.SZSE", "688001.SSE", "600005.SSE")
        ],
        ignore_index=True,
    )
    rows = build_emotion_cycle_candidates(
        _cycle_starts(),
        memberships,
        pd.concat([features, extras], ignore_index=True),
    )

    assert not set(rows["vt_symbol"]) & {"300001.SZSE", "688001.SSE", "600005.SSE"}


def test_causal_rank_prefers_live_preleading_repeat_strength() -> None:
    ranked = rank_causal_cycle_leaders(_qualified_candidates())

    assert ranked.loc[ranked["causal_rank"].eq(1), "vt_symbol"].item() == "600001.SSE"
    assert int(ranked["causal_top3"].sum()) == 3
    assert int(ranked["baseline_top3"].sum()) == 3


def test_causal_rank_rejects_future_columns() -> None:
    leaked = _qualified_candidates().assign(future_40d_max_excess_pct=999.0)

    with pytest.raises(ValueError, match="future"):
        rank_causal_cycle_leaders(leaked)


def _truth_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[date, ...]]:
    dates = pd.bdate_range("2024-12-02", periods=70)
    cycle_date = dates[25]
    paths = {
        "600001.SSE": [(12.0, 10.5, 11.8), (11.7, 11.2, 11.4), (13.0, 11.5, 12.8), (12.8, 12.0, 12.2), (14.0, 12.3, 13.8)],
        "600002.SSE": [(11.5, 10.5, 11.2), (11.4, 10.9, 11.1), (11.6, 11.0, 11.4)],
        "002001.SZSE": [(11.8, 10.5, 11.5), (11.5, 10.9, 11.1), (12.2, 11.0, 12.0)],
    }
    stock_rows = []
    for symbol, path in paths.items():
        close = 10.0
        for index, trade_date in enumerate(dates):
            if index < 25:
                high, low, close = 10.2, 9.8, 10.0
            elif index - 25 < len(path):
                high, low, close = path[index - 25]
            else:
                close *= 1.002
                high, low = close * 1.005, close * 0.995
            stock_rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close,
                    "high_price": high,
                    "low_price": low,
                    "close_price": close,
                    "volume": 1_000_000.0,
                    "turnover": 150_000_000.0,
                }
            )
    concept = pd.DataFrame(
        {
            "sector_id": "BK0001",
            "trade_date": dates,
            "close_price": np.linspace(100.0, 110.0, len(dates)),
        }
    )
    ranks = pd.DataFrame(
        [
            {
                "cycle_id": "C1",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "trade_date": cycle_date,
                "vt_symbol": symbol,
                "stock_name": name,
                "first_strong_date_10d": cycle_date,
                "causal_rank": rank,
                "causal_top1": rank == 1,
                "causal_top3": True,
                "baseline_rank": 4 - rank,
                "baseline_top1": rank == 3,
                "baseline_top3": True,
            }
            for rank, (symbol, name) in enumerate(
                (("600001.SSE", "甲股份"), ("600002.SSE", "乙股份"), ("002001.SZSE", "丙股份")),
                start=1,
            )
        ]
    )
    return ranks, pd.DataFrame(stock_rows), concept, tuple(value.date() for value in dates)


def test_truth_labels_are_attached_after_frozen_ranks() -> None:
    ranks, stocks, concepts, trading_dates = _truth_inputs()
    labels = build_cycle_leader_truth(
        ranks,
        stocks,
        concepts,
        trading_dates=trading_dates,
        horizon=40,
    )

    truth = labels.loc[labels["truth_rank"].eq(1)].iloc[0]
    assert truth["vt_symbol"] == "600001.SSE"
    assert truth["future_wave_count"] == 3
    assert labels["causal_rank"].tolist() == ranks["causal_rank"].tolist()


def test_incomplete_truth_horizon_is_censored() -> None:
    ranks, stocks, concepts, trading_dates = _truth_inputs()
    ranks = ranks.assign(trade_date=pd.Timestamp(trading_dates[-5]))
    labels = build_cycle_leader_truth(
        ranks,
        stocks,
        concepts,
        trading_dates=trading_dates,
        horizon=40,
    )

    assert labels["truth_status"].eq("censored_incomplete_40d").all()
    assert labels["truth_rank"].isna().all()


def _evaluation_labels() -> pd.DataFrame:
    rows = []
    for cycle_index, cycle_date in enumerate(pd.bdate_range("2025-01-02", periods=10)):
        for rank, symbol in enumerate(("600001.SSE", "600002.SSE", "600003.SSE"), start=1):
            truth_rank = rank
            causal_rank = rank
            baseline_rank = 3 if rank == 1 else rank - 1
            rows.append(
                {
                    "cycle_id": f"C{cycle_index}",
                    "trade_date": cycle_date,
                    "vt_symbol": symbol,
                    "truth_status": "complete",
                    "truth_cycle_qualified": True,
                    "truth_rank": truth_rank,
                    "truth_top1": truth_rank == 1,
                    "truth_top3": True,
                    "causal_rank": causal_rank,
                    "causal_top1": causal_rank == 1,
                    "causal_top3": True,
                    "baseline_rank": baseline_rank,
                    "baseline_top1": baseline_rank == 1,
                    "baseline_top3": True,
                    "future_wave_count": 4 - truth_rank,
                    "future_40d_max_excess_pct": 30.0 - truth_rank,
                }
            )
    return pd.DataFrame(rows)


def test_block_assignment_is_chronological_and_deterministic() -> None:
    labels = _evaluation_labels()
    baseline = assign_true_leader_blocks(labels, block_count=5)
    shuffled = assign_true_leader_blocks(labels.sample(frac=1, random_state=9), block_count=5)
    columns = ["cycle_id", "vt_symbol", "block"]

    pd.testing.assert_frame_equal(
        baseline[columns].sort_values(columns[:2]).reset_index(drop=True),
        shuffled[columns].sort_values(columns[:2]).reset_index(drop=True),
    )


def test_identity_metrics_compare_causal_and_baseline_on_same_cycles() -> None:
    metrics = evaluate_true_leader_identity(
        assign_true_leader_blocks(_evaluation_labels(), block_count=5)
    )
    pooled = metrics.loc[metrics["segment"].eq("all")].set_index("mode")

    assert pooled.loc["causal_leadership", "qualified_cycles"] == 10
    assert pooled.loc["ten_day_excess_baseline", "qualified_cycles"] == 10
    assert pooled.loc["causal_leadership", "top1_exact_rate_pct"] == 100.0
    assert pooled.loc["ten_day_excess_baseline", "top1_exact_rate_pct"] == 0.0


def test_cli_registers_true_leader_wave_study() -> None:
    args = build_parser().parse_args(["v2-true-leader-wave-study"])

    assert args.command == "v2-true-leader-wave-study"
