from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.calculated_true_leader_study import (
    build_calculated_true_leader_report,
    build_realized_leader_truth,
    evaluate_calculated_identity,
    rank_calculated_leaders,
)


def test_cli_registers_calculated_true_leader_study() -> None:
    args = build_parser().parse_args(["v2-calculated-true-leader-study"])

    assert args.command == "v2-calculated-true-leader-study"
    assert args.format == "markdown"


def _causal_relationship_pool() -> pd.DataFrame:
    cycle_date = pd.Timestamp("2025-03-11")
    rows = []
    features = (
        ("600001.SSE", 3.0, 4.0, 8.0, -0.5, 1.5, 0.95, 200_000_000.0),
        ("600002.SSE", 2.0, 3.0, 7.0, -1.0, 1.4, 0.90, 180_000_000.0),
        ("002001.SZSE", 2.0, 2.0, 6.0, -1.5, 1.3, 0.85, 160_000_000.0),
        ("600003.SSE", 1.0, 1.0, 5.0, -2.0, 1.2, 0.80, 140_000_000.0),
    )
    for relation_rank, values in enumerate(features, start=1):
        (
            symbol,
            strong_days,
            acceleration,
            return_10d,
            prior_high_distance,
            volume_ratio,
            relationship,
            turnover,
        ) = values
        rows.append(
            {
                "cycle_id": "C1",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "trade_date": cycle_date,
                "vt_symbol": symbol,
                "stock_name": symbol,
                "first_strong_date_10d": cycle_date - pd.offsets.BDay(5),
                "first_strong_sessions_ago_10d": 5.0,
                "strong_days_10": strong_days,
                "return_10d_pct": return_10d,
                "return_acceleration_5d_pct": acceleration,
                "distance_from_prior_high_pct": prior_high_distance,
                "volume_ratio_5_20": volume_ratio,
                "turnover_median_20d": turnover,
                "concept_return_10d": 0.04,
                "relationship_consensus": relationship,
                "relation_rank": relation_rank,
                "relationship_known_at": cycle_date,
                "relationship_direction": "causal",
            }
        )
    return pd.DataFrame(rows)


def test_calculated_rank_uses_frozen_lexicographic_order() -> None:
    ranked = rank_calculated_leaders(_causal_relationship_pool())

    assert ranked.loc[
        ranked["calculated_rank"].eq(1), "vt_symbol"
    ].item() == "600001.SSE"
    assert int(ranked["calculated_top3"].sum()) == 3
    assert int(ranked["baseline_top3"].sum()) == 3
    assert ranked["rank_known_at"].eq(pd.Timestamp("2025-03-11")).all()


def test_calculated_rank_rejects_truth_future_and_outcome_columns() -> None:
    for column in ("truth_rank", "future_wave_count", "exit_price"):
        with pytest.raises(ValueError, match="prohibited"):
            rank_calculated_leaders(
                _causal_relationship_pool().assign(**{column: 9})
            )


def _truth_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    tuple[date, ...],
]:
    dates = pd.bdate_range("2024-12-02", periods=72)
    cycle_position = 25
    cycle_date = dates[cycle_position]
    paths = {
        "600001.SSE": [
            (12.0, 10.5, 11.8),
            (11.7, 11.2, 11.4),
            (13.0, 11.5, 12.8),
            (12.8, 12.0, 12.2),
            (14.0, 12.3, 13.8),
        ],
        "600002.SSE": [
            (11.5, 10.5, 11.2),
            (11.4, 10.9, 11.1),
            (11.6, 11.0, 11.4),
        ],
        "002001.SZSE": [
            (11.8, 10.5, 11.5),
            (11.5, 10.9, 11.1),
            (12.2, 11.0, 12.0),
        ],
    }
    stock_rows: list[dict[str, object]] = []
    for symbol, path in paths.items():
        close = 10.0
        for index, trade_date in enumerate(dates):
            if index < cycle_position:
                high, low, close = 10.2, 9.8, 10.0
            elif index - cycle_position < len(path):
                high, low, close = path[index - cycle_position]
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
    concepts = pd.DataFrame(
        {
            "sector_id": "BK0001",
            "trade_date": dates,
            "close_price": np.linspace(100.0, 110.0, len(dates)),
        }
    )
    realized_pool = pd.DataFrame(
        [
            {
                "cycle_id": "C1",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "trade_date": cycle_date,
                "vt_symbol": symbol,
                "stock_name": symbol,
                "first_strong_date_10d": cycle_date,
                "relation_rank": rank,
                "relationship_direction": "realized",
                "relationship_known_at": dates[cycle_position + 40],
            }
            for rank, symbol in enumerate(paths, start=1)
        ]
    )
    return (
        realized_pool,
        pd.DataFrame(stock_rows),
        concepts,
        tuple(value.date() for value in dates),
    )


def test_realized_truth_prefers_repeated_higher_high_waves() -> None:
    realized, stocks, concepts, trading_dates = _truth_inputs()
    truth = build_realized_leader_truth(
        realized,
        stocks,
        concepts,
        trading_dates=trading_dates,
    )

    leader = truth.loc[truth["truth_rank"].eq(1)].iloc[0]
    assert leader["vt_symbol"] == "600001.SSE"
    assert leader["future_wave_count"] == 3
    assert truth["truth_status"].eq("complete").all()


def test_realized_truth_censors_incomplete_forty_session_horizon() -> None:
    realized, stocks, concepts, trading_dates = _truth_inputs()
    realized = realized.assign(trade_date=pd.Timestamp(trading_dates[-5]))
    truth = build_realized_leader_truth(
        realized,
        stocks,
        concepts,
        trading_dates=trading_dates,
    )

    assert truth["truth_status"].eq("censored_incomplete_40d").all()
    assert truth["truth_rank"].isna().all()


def _evaluation_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    rank_rows: list[dict[str, object]] = []
    truth_rows: list[dict[str, object]] = []
    symbols = ("600001.SSE", "600002.SSE", "600003.SSE", "600004.SSE")
    for cycle_index, cycle_date in enumerate(pd.bdate_range("2025-01-02", periods=10)):
        cycle_id = f"C{cycle_index}"
        for calculated_rank, symbol in enumerate(symbols, start=1):
            baseline_rank = 4 if calculated_rank == 1 else calculated_rank - 1
            rank_rows.append(
                {
                    "cycle_id": cycle_id,
                    "trade_date": cycle_date,
                    "vt_symbol": symbol,
                    "calculated_rank": calculated_rank,
                    "calculated_top1": calculated_rank == 1,
                    "calculated_top3": calculated_rank <= 3,
                    "baseline_rank": baseline_rank,
                    "baseline_top1": baseline_rank == 1,
                    "baseline_top3": baseline_rank <= 3,
                }
            )
        for truth_rank, symbol in enumerate(symbols[:3], start=1):
            truth_rows.append(
                {
                    "cycle_id": cycle_id,
                    "trade_date": cycle_date,
                    "vt_symbol": symbol,
                    "truth_status": "complete",
                    "truth_rank": truth_rank,
                    "truth_top1": truth_rank == 1,
                    "truth_top3": True,
                    "future_wave_count": 4 - truth_rank,
                    "future_40d_max_excess_pct": 30.0 - truth_rank,
                }
            )
    return pd.DataFrame(rank_rows), pd.DataFrame(truth_rows)


def test_identity_modes_use_identical_cycles_and_five_date_blocks() -> None:
    ranks, truth = _evaluation_inputs()
    metrics = evaluate_calculated_identity(ranks, truth, block_count=5)

    assert set(metrics["mode"]) == {
        "calculated_leadership",
        "ten_day_excess_baseline",
    }
    assert metrics.loc[
        metrics["segment"].eq("all"), "qualified_cycles"
    ].nunique() == 1
    assert set(metrics["segment"]) == {
        "all",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    }
    pooled = metrics.loc[metrics["segment"].eq("all")].set_index("mode")
    assert pooled.loc["calculated_leadership", "top1_exact_rate_pct"] == 100.0
    assert pooled.loc[
        "calculated_leadership", "relation_pool_truth_top1_capture_rate_pct"
    ] == 100.0
    assert pooled.loc["ten_day_excess_baseline", "top1_exact_rate_pct"] == 0.0


def test_failed_identity_gate_keeps_strategy_outputs_null() -> None:
    ranks, truth = _evaluation_inputs()
    metrics = evaluate_calculated_identity(ranks, truth, block_count=5)
    weak = metrics.copy()
    pooled = weak["segment"].eq("all") & weak["mode"].eq(
        "calculated_leadership"
    )
    weak.loc[
        pooled,
        [
            "top1_exact_rate_pct",
            "top3_truth_top1_capture_rate_pct",
            "mean_truth_top3_overlap_pct",
        ],
    ] = [20.0, 50.0, 40.0]
    report = build_calculated_true_leader_report(
        coverage={"qualified_cycles": 10},
        fingerprints={},
        ranks=ranks,
        truth=truth,
        metrics=weak,
    )

    assert report["formal_top3"] is False
    assert report["formal_low_suction_metrics"] is None
    assert report["outcome_data_read"] is False
    assert report["membership_rows_read"] == 0
    assert report["reason_rows_read"] == 0
