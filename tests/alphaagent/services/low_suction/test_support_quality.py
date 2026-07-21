from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.support_quality import (
    QUALITY_FEATURES,
    QualityCondition,
    QualityLeaf,
    apply_quality_leaf,
    describe_quality_tree,
    enrich_support_quality_events,
    evaluate_sequential_late_blocks,
    fit_development_quality_tree,
    freeze_development_quality_leaf,
)


def test_quality_events_join_only_same_day_causal_features() -> None:
    events, paths = _quality_event_inputs()

    enriched = enrich_support_quality_events(events, paths)

    assert enriched["quality_feature_cutoff_date"].equals(
        enriched["signal_date"]
    )
    assert enriched["campaign_day"].tolist() == [7, 12]
    assert enriched["concept_gain_pct"].tolist() == pytest.approx([8.0, 12.0])
    assert enriched["peak_gap_pct"].tolist() == pytest.approx([-5.0, -4.0])
    assert enriched["quality_feature_complete"].tolist() == [True, True]
    assert set(QUALITY_FEATURES).issubset(enriched)
    assert not set(enriched).intersection(
        {"d1_close", "net_return_pct", "exit_date", "mfe_pct", "mae_pct"}
    )


def test_quality_event_enrichment_rejects_outcomes_and_duplicate_paths() -> None:
    events, paths = _quality_event_inputs()

    with pytest.raises(ValueError, match="outcome columns"):
        enrich_support_quality_events(events.assign(d1_close=11.0), paths)
    with pytest.raises(ValueError, match="unique"):
        enrich_support_quality_events(events, pd.concat([paths, paths.iloc[[0]]]))


def test_quality_tree_is_deterministic_and_ignores_late_outcomes() -> None:
    trades = _tree_trades()

    first = fit_development_quality_tree(trades)
    shuffled = fit_development_quality_tree(
        trades.sample(frac=1.0, random_state=7).reset_index(drop=True)
    )
    changed_late = trades.copy()
    changed_late.loc[
        changed_late["time_block"].isin(("block_4", "block_5")),
        "net_return_pct",
    ] *= -100.0
    late_changed = fit_development_quality_tree(changed_late)

    assert describe_quality_tree(first) == describe_quality_tree(shuffled)
    assert describe_quality_tree(first) == describe_quality_tree(late_changed)
    assert describe_quality_tree(first)["tree_contract"] == {
        "max_depth": 2,
        "min_samples_leaf": 100,
        "random_state": 0,
    }
    assert first.development_rows == 600
    assert len(first.leaves) >= 2


def test_quality_leaf_application_uses_explicit_conditions() -> None:
    frame = pd.DataFrame(
        {
            "leg_gain_pct": [5.0, 12.0, 15.0],
            "strong_days_since_ignition": [3.0, 1.0, 3.0],
        }
    )
    leaf = QualityLeaf(
        rule_id="quality_leaf_test",
        leaf_node=3,
        conditions=(
            QualityCondition("leg_gain_pct", ">", 10.0),
            QualityCondition("strong_days_since_ignition", ">", 2.0),
        ),
    )

    assert apply_quality_leaf(frame, leaf).tolist() == [False, False, True]


def test_development_leaf_freeze_uses_cash_without_late_rows() -> None:
    trades = _tree_trades()
    discovery = fit_development_quality_tree(trades)
    cash_results = {
        leaf.rule_id: {"compound_return_pct": 80.0}
        for leaf in discovery.leaves
    }

    frozen = freeze_development_quality_leaf(
        trades,
        discovery,
        cash_results,
    )
    changed_late = trades.copy()
    late = changed_late["time_block"].isin(("block_4", "block_5"))
    changed_late.loc[late, "net_return_pct"] = 99.0
    repeated = freeze_development_quality_leaf(
        changed_late,
        discovery,
        cash_results,
    )

    assert frozen == repeated
    assert frozen["selected_leaf"] is not None
    selected = next(
        row
        for row in frozen["leaf_metrics"]
        if row["rule_id"] == frozen["selected_leaf"]["rule_id"]
    )
    assert selected["nomination_passed"] is True
    assert selected["development_win_rate_pct"] > 60.0


def test_block_four_failure_keeps_block_five_unread() -> None:
    trades = _tree_trades()
    trades.loc[trades["time_block"].eq("block_4"), "net_return_pct"] = -1.0
    first = evaluate_sequential_late_blocks(trades)
    changed = trades.copy()
    changed.loc[changed["time_block"].eq("block_5"), "net_return_pct"] = 99.0
    second = evaluate_sequential_late_blocks(changed)

    assert first == second
    assert first["block_4"]["passed"] is False
    assert first["block_5"] is None
    assert first["late_validation_passed"] is False


def _quality_event_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    signal_dates = pd.to_datetime(["2026-01-06", "2026-01-09"])
    events = pd.DataFrame(
        {
            "signal_id": ["support-1", "support-2"],
            "campaign_id": [1, 2],
            "vt_symbol": ["600001.SSE", "000001.SZSE"],
            "signal_date": signal_dates,
            "feature_cutoff_date": signal_dates,
            "close_price": [9.5, 12.0],
            "record_high_price": [10.0, 12.5],
            "peak_drawdown_low_pct": [-6.0, -7.0],
            "close_location": [0.7, 0.8],
            "daily_return_pct": [1.0, 2.0],
            "volume_ratio_prior5": [0.9, 1.1],
            "dynamic_rank": [1, 2],
            "wave_number": [1, 2],
        }
    )
    paths = pd.DataFrame(
        {
            "campaign_id": [1, 2],
            "vt_symbol": ["600001.SSE", "000001.SZSE"],
            "trade_date": signal_dates,
            "feature_cutoff_date": signal_dates,
            "campaign_day": [7, 12],
            "concept_gain_pct": [8.0, 12.0],
            "leg_gain_pct": [15.0, 22.0],
            "strong_days_since_ignition": [2, 3],
            "turnover_expansion": [1.2, 1.5],
        }
    )
    return events, paths


def _tree_trades() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = pd.Timestamp("2024-01-02")
    position = 0
    for block_number in range(1, 6):
        for attempt in range(200):
            high_quality = attempt < 100
            winning = (
                attempt % 10 < 7 if high_quality else attempt % 10 < 2
            )
            signal_date = start + pd.Timedelta(days=position)
            row: dict[str, object] = {
                "signal_id": f"quality-{position:04d}",
                "signal_date": signal_date,
                "exit_date": signal_date + pd.Timedelta(days=1),
                "time_block": f"block_{block_number}",
                "net_return_pct": 2.0 if winning else -1.0,
                "campaign_day": 10.0,
                "concept_gain_pct": 8.0,
                "leg_gain_pct": 15.0 if high_quality else 5.0,
                "strong_days_since_ignition": 3.0 if high_quality else 1.0,
                "turnover_expansion": 1.4,
                "volume_ratio_prior5": 1.0,
                "dynamic_rank": 1.0,
                "wave_number": 2.0,
                "peak_gap_pct": -3.0,
                "peak_drawdown_low_pct": -6.0,
                "close_location": 0.7,
                "daily_return_pct": 1.5,
            }
            rows.append(row)
            position += 1
    return pd.DataFrame.from_records(rows)
