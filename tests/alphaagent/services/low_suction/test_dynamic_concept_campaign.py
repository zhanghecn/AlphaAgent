from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.dynamic_concept_campaign import (
    EXPLORATORY_ANCHOR_MODES,
    build_concept_campaign_features,
    build_dynamic_leader_ledger,
    build_exploratory_campaigns,
    build_realized_campaign_leader_proxy,
    campaign_candidate_diagnostics,
    evaluate_dynamic_leader_modes,
    evaluate_exploratory_campaigns,
    evaluate_leader_diffusion,
)


def test_concept_features_use_only_values_available_on_each_date() -> None:
    baseline = build_concept_campaign_features(_concept_bars())
    changed = _concept_bars()
    changed.loc[changed["trade_date"].gt("2025-02-14"), "close_price"] *= 4
    changed.loc[changed["trade_date"].gt("2025-02-14"), "turnover"] *= 4

    mutated = build_concept_campaign_features(changed)

    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"].le("2025-02-14")].reset_index(
            drop=True
        ),
        mutated.loc[mutated["trade_date"].le("2025-02-14")].reset_index(
            drop=True
        ),
    )


def test_anchor_modes_are_explicit_comparison_columns() -> None:
    rows = build_concept_campaign_features(_concept_bars())

    assert set(EXPLORATORY_ANCHOR_MODES) == {
        "breakout_20",
        "relative_gain_5d_q80",
        "breakout_relative",
        "breakout_relative_turnover",
    }
    for mode in EXPLORATORY_ANCHOR_MODES:
        assert rows[f"anchor_{mode}"].dtype == bool


def test_concept_features_reject_duplicate_identity() -> None:
    bars = _concept_bars()
    duplicate = pd.concat([bars, bars.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="unique"):
        build_concept_campaign_features(duplicate)


def test_active_campaign_suppresses_repeated_anchor_triggers() -> None:
    features = _direct_features(
        closes=(100.0, 104.0, 108.0, 102.0),
        triggers=(True, True, True, False),
    )

    campaigns, path = build_exploratory_campaigns(
        features,
        anchor_modes=("breakout_20",),
        exit_candidates=((5.0, 1),),
    )

    assert len(campaigns) == 1
    assert path["campaign_day"].tolist() == [0, 1, 2, 3]
    assert campaigns.iloc[0]["end_reason"] == "confirmed_running_peak_drawdown"


def test_campaign_end_uses_running_peak_and_confirmation_count() -> None:
    features = _direct_features(
        closes=(100.0, 110.0, 104.0, 103.0, 102.0),
        triggers=(True, False, False, False, False),
    )

    campaigns, _ = build_exploratory_campaigns(
        features,
        anchor_modes=("breakout_20",),
        exit_candidates=((5.0, 3),),
    )

    ended = campaigns.iloc[0]
    assert ended["end_reason"] == "confirmed_running_peak_drawdown"
    assert ended["end_date"] == pd.Timestamp("2025-01-07")
    assert ended["campaign_days"] == 5


def test_right_censored_campaign_is_not_called_a_completed_end() -> None:
    features = _direct_features(
        closes=(100.0, 103.0, 105.0),
        triggers=(True, False, False),
    )

    campaigns, _ = build_exploratory_campaigns(
        features,
        anchor_modes=("breakout_20",),
        exit_candidates=((5.0, 1),),
    )

    row = campaigns.iloc[0]
    assert bool(row["right_censored"])
    assert row["end_reason"] == "right_censored"
    assert pd.isna(row["higher_high_within_10_after_end"])


def test_campaign_evaluation_reports_launch_and_false_end_metrics() -> None:
    campaigns = pd.DataFrame(
        {
            "campaign_id": ["a", "b"],
            "anchor_mode": ["breakout_20", "breakout_20"],
            "exit_drawdown_pct": [5.0, 5.0],
            "exit_confirm_sessions": [1, 1],
            "anchor_date": pd.to_datetime(["2025-01-02", "2025-02-03"]),
            "right_censored": [False, False],
            "campaign_days": [8, 12],
            "peak_gain_pct": [8.0, 4.0],
            "terminal_gain_pct": [2.0, -2.0],
            "days_to_peak": [4, 3],
            "reached_5pct": [True, False],
            "reached_10pct": [False, False],
            "higher_high_within_10_after_end": [True, False],
            "post_end_further_drawdown_pct": [-1.0, -3.0],
        }
    )

    evaluated = evaluate_exploratory_campaigns(
        campaigns,
        pd.DataFrame(),
        block_count=1,
    )
    row = evaluated.loc[evaluated["scope"].eq("pooled")].iloc[0]

    assert row["campaigns"] == 2
    assert row["reach_5pct_rate"] == 50.0
    assert row["higher_high_within_10_after_end_rate"] == 50.0


def test_campaign_evaluation_has_five_chronological_blocks() -> None:
    campaigns = _evaluation_campaigns()

    evaluated = evaluate_exploratory_campaigns(
        campaigns,
        pd.DataFrame(),
        block_count=5,
    )

    assert set(evaluated.loc[evaluated["scope"].ne("pooled"), "scope"]) == {
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    }


def test_campaign_diagnostics_align_block_medians_by_scope() -> None:
    metrics = evaluate_exploratory_campaigns(
        pd.concat(
            [
                _evaluation_campaigns(),
                _evaluation_campaigns().assign(
                    campaign_id=lambda frame: "other-" + frame["campaign_id"],
                    anchor_mode="relative_gain_5d_q80",
                    peak_gain_pct=lambda frame: frame["peak_gain_pct"] + 1.0,
                ),
            ],
            ignore_index=True,
        ),
        pd.DataFrame(),
        block_count=5,
    )

    diagnostics = campaign_candidate_diagnostics(metrics)

    assert len(diagnostics) == 2
    assert all(row["block_count"] == 5 for row in diagnostics)


def test_dynamic_leader_rank_changes_when_a_member_overtakes() -> None:
    ledger = build_dynamic_leader_ledger(
        _leader_campaign_path(),
        _memberships(),
        _leader_stock_bars(),
    )

    top1 = ledger.loc[
        ledger["cumulative_gain_rank"].eq(1),
        ["campaign_day", "vt_symbol"],
    ]

    assert top1.to_records(index=False).tolist() == [
        (0, "600001.SSE"),
        (1, "600002.SSE"),
    ]


def test_dynamic_leader_rows_before_cutoff_ignore_future_stock_mutation() -> None:
    baseline = build_dynamic_leader_ledger(
        _leader_campaign_path(),
        _memberships(),
        _leader_stock_bars(),
    )
    changed = _leader_stock_bars()
    changed.loc[changed["trade_date"].gt("2025-01-03"), "close_price"] *= 3
    changed.loc[changed["trade_date"].gt("2025-01-03"), "turnover"] *= 3

    mutated = build_dynamic_leader_ledger(
        _leader_campaign_path(),
        _memberships(),
        changed,
    )

    columns = sorted(set(baseline) & set(mutated))
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"].le("2025-01-03"), columns].reset_index(
            drop=True
        ),
        mutated.loc[mutated["trade_date"].le("2025-01-03"), columns].reset_index(
            drop=True
        ),
    )


def test_dynamic_leader_rejects_unlabelled_membership_proxy() -> None:
    memberships = _memberships().drop(columns="evidence_level")

    with pytest.raises(ValueError, match="evidence_level"):
        build_dynamic_leader_ledger(
            _leader_campaign_path(),
            memberships,
            _leader_stock_bars(),
        )


def test_realized_campaign_proxy_prefers_persistent_repeated_high_leader() -> None:
    truth = build_realized_campaign_leader_proxy(_realized_ledger())

    assert truth.loc[truth["realized_rank"].eq(1), "vt_symbol"].item() == (
        "600002.SSE"
    )


def test_leader_mode_evaluation_uses_identical_complete_campaigns() -> None:
    ledger = _mode_evaluation_ledger()
    truth = build_realized_campaign_leader_proxy(ledger)

    metrics = evaluate_dynamic_leader_modes(ledger, truth, block_count=1)
    pooled = metrics.loc[metrics["scope"].eq("pooled")]

    assert pooled.groupby("campaign_day_bucket")["qualified_campaigns"].nunique().eq(
        1
    ).all()
    assert set(pooled["leader_mode"]) == {
        "cumulative_gain",
        "ignition_gain",
        "gain_persistence",
        "gain_persistence_turnover",
    }


def test_leader_diffusion_separates_early_leader_from_future_followers() -> None:
    metrics = evaluate_leader_diffusion(_diffusion_ledger(), block_count=1)
    row = metrics.loc[
        metrics["scope"].eq("pooled")
        & metrics["leader_mode"].eq("cumulative_gain")
        & metrics["future_day"].eq(3)
    ].iloc[0]

    assert row["qualified_campaigns"] == 5
    assert row["leader_retained_top1_rate_pct"] == 100.0
    assert row["median_follower_gain_delta_pct"] == 6.0
    assert row["median_positive_breadth_delta_pct_points"] == 100.0
    assert row["leader_gain_follower_delta_spearman"] == pytest.approx(1.0)


def _concept_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=40)
    rows: list[dict[str, object]] = []
    for sector_index, sector_id in enumerate(("BK001", "BK002", "BK003")):
        for day, trade_date in enumerate(dates):
            close = 100.0 + day * (0.5 + sector_index * 0.1)
            rows.append(
                {
                    "sector_id": sector_id,
                    "concept_name": f"概念{sector_index + 1}",
                    "trade_date": trade_date,
                    "open_price": close - 0.2,
                    "high_price": close + 0.5,
                    "low_price": close - 0.5,
                    "close_price": close,
                    "turnover": 1_000_000.0 + day * 10_000 + sector_index * 1_000,
                }
            )
    return pd.DataFrame(rows)


def _direct_features(
    *,
    closes: Iterable[float],
    triggers: Iterable[bool],
) -> pd.DataFrame:
    close_values = tuple(closes)
    trigger_values = tuple(triggers)
    dates = pd.bdate_range("2025-01-01", periods=len(close_values))
    frame = pd.DataFrame(
        {
            "sector_id": "BK001",
            "concept_name": "测试概念",
            "trade_date": dates,
            "close_price": close_values,
            "anchor_breakout_20": trigger_values,
        }
    )
    for mode in EXPLORATORY_ANCHOR_MODES:
        column = f"anchor_{mode}"
        if column not in frame:
            frame[column] = False
    return frame


def _evaluation_campaigns() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=20)
    return pd.DataFrame(
        {
            "campaign_id": [f"campaign-{index}" for index in range(20)],
            "anchor_mode": "breakout_20",
            "exit_drawdown_pct": 5.0,
            "exit_confirm_sessions": 1,
            "anchor_date": dates,
            "right_censored": False,
            "campaign_days": 10,
            "peak_gain_pct": np.arange(20, dtype=float),
            "terminal_gain_pct": np.arange(20, dtype=float) / 2,
            "days_to_peak": 4,
            "reached_5pct": [index >= 5 for index in range(20)],
            "reached_10pct": [index >= 10 for index in range(20)],
            "higher_high_within_10_after_end": [index % 2 == 0 for index in range(20)],
            "post_end_further_drawdown_pct": -2.0,
        }
    )


def _leader_campaign_path() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "campaign_id": ["campaign-1", "campaign-1"],
            "anchor_mode": ["breakout_20", "breakout_20"],
            "sector_id": ["BK001", "BK001"],
            "concept_name": ["测试概念", "测试概念"],
            "anchor_date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
            "trade_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "campaign_day": [0, 1],
            "close_price": [101.0, 103.0],
            "cumulative_gain_pct": [1.0, 3.0],
            "is_endpoint": [False, True],
        }
    )


def _memberships() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_id": ["BK001", "BK001"],
            "vt_symbol": ["600001.SSE", "600002.SSE"],
            "stock_name": ["甲", "乙"],
            "evidence_level": [
                "current_membership_survivorship_proxy",
                "current_membership_survivorship_proxy",
            ],
        }
    )


def _leader_stock_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-11-20", "2025-01-03")
    rows: list[dict[str, object]] = []
    for symbol, final_prices in (
        ("600001.SSE", (103.0, 104.0)),
        ("600002.SSE", (102.0, 110.0)),
    ):
        for index, trade_date in enumerate(dates):
            close = 100.0
            if trade_date == pd.Timestamp("2025-01-02"):
                close = final_prices[0]
            elif trade_date == pd.Timestamp("2025-01-03"):
                close = final_prices[1]
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "close_price": close,
                    "turnover": 1_000_000.0 + index * 10_000,
                }
            )
    return pd.DataFrame(rows)


def _realized_ledger() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day in range(4):
        for symbol, top3, excess in (
            ("600001.SSE", True, 5.0 + day),
            ("600002.SSE", day > 0, 4.0 + day * 3),
            ("600003.SSE", True, 3.0 + day),
        ):
            rows.append(
                {
                    "episode_id": "episode-1",
                    "anchor_mode": "breakout_20",
                    "sector_id": "BK001",
                    "anchor_date": pd.Timestamp("2025-01-02"),
                    "trade_date": pd.Timestamp("2025-01-02")
                    + pd.offsets.BDay(day),
                    "campaign_day": day,
                    "vt_symbol": symbol,
                    "stock_excess_concept_pct": excess,
                    "member_cumulative_gain_pct": excess + 2,
                    "cumulative_gain_top3": top3,
                }
            )
    return pd.DataFrame(rows)


def _mode_evaluation_ledger() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    symbols = ("600001.SSE", "600002.SSE", "600003.SSE")
    for episode_index in range(3):
        episode_id = f"episode-{episode_index}"
        anchor_date = pd.Timestamp("2025-01-02") + pd.offsets.BDay(
            episode_index * 5
        )
        for day in (0, 1, 3):
            for rank, symbol in enumerate(symbols, start=1):
                rows.append(
                    {
                        "episode_id": episode_id,
                        "anchor_mode": "breakout_20",
                        "sector_id": f"BK{episode_index:03d}",
                        "anchor_date": anchor_date,
                        "trade_date": anchor_date + pd.offsets.BDay(day),
                        "campaign_day": day,
                        "vt_symbol": symbol,
                        "stock_excess_concept_pct": 6.0 - rank + day,
                        "member_cumulative_gain_pct": 8.0 - rank + day,
                        "cumulative_gain_rank": rank,
                        "ignition_gain_rank": rank,
                        "gain_persistence_rank": rank,
                        "gain_persistence_turnover_rank": rank,
                        "cumulative_gain_top3": True,
                    }
                )
    return pd.DataFrame(rows)


def _diffusion_ledger() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    symbols = ("600001.SSE", "600002.SSE", "600003.SSE")
    for episode_index in range(5):
        episode_id = f"diffusion-{episode_index}"
        anchor_date = pd.Timestamp("2025-01-02") + pd.offsets.BDay(
            episode_index * 5
        )
        leader_gain = float(episode_index + 1)
        for day in (0, 3):
            for rank, symbol in enumerate(symbols, start=1):
                member_gain = (
                    leader_gain + 5.0
                    if symbol == "600001.SSE" and day == 3
                    else leader_gain
                    if symbol == "600001.SSE"
                    else leader_gain * 2.0
                    if day == 3
                    else 0.0
                )
                row: dict[str, object] = {
                    "episode_id": episode_id,
                    "anchor_mode": "breakout_20",
                    "anchor_date": anchor_date,
                    "trade_date": anchor_date + pd.offsets.BDay(day),
                    "campaign_day": day,
                    "vt_symbol": symbol,
                    "member_cumulative_gain_pct": member_gain,
                }
                for mode in (
                    "cumulative_gain",
                    "ignition_gain",
                    "gain_persistence",
                    "gain_persistence_turnover",
                ):
                    row[f"{mode}_rank"] = rank
                rows.append(row)
    return pd.DataFrame(rows)
