from __future__ import annotations

import inspect

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.main_rise_weak_to_strong_study import (
    SIGNAL_FEATURE_COLUMNS,
    WeakToStrongRule,
    assign_chronological_blocks,
    attach_close_outcomes,
    build_main_rise_path_state,
    build_report,
    candidate_rules,
    choose_rule,
    classify_support_zone,
    final_gates,
    load_study_data,
    rank_dynamic_concept_leaders,
    render_main_rise_weak_to_strong_markdown,
    select_rule_signals,
    summarize_returns,
)


def test_study_loader_accepts_canonical_concept_sector_types() -> None:
    source = inspect.getsource(load_study_data)

    assert ".c.type.in_(CONCEPT_SECTOR_TYPES)" in source


def test_candidate_grid_is_small_and_complete() -> None:
    rules = candidate_rules()

    assert len(rules) == 32
    assert len({rule.version for rule in rules}) == 32
    assert {rule.minimum_return60_pct for rule in rules} == {20.0, 35.0}
    assert {rule.minimum_top3_days10 for rule in rules} == {4, 6}
    assert {rule.minimum_new_high_days20 for rule in rules} == {2, 3}
    assert {rule.maximum_volume_ratio for rule in rules} == {0.8, 1.2}
    assert {rule.maximum_opportunity_ordinal for rule in rules} == {2, None}


def test_dynamic_rank_uses_gain_and_turnover_without_future_columns() -> None:
    frame = pd.DataFrame(
        [
            _member("a", 30.0, 20.0, 100.0, 1.4),
            _member("b", 20.0, 15.0, 300.0, 1.2),
            _member("c", 10.0, 8.0, 200.0, 1.0),
            _member("d", 5.0, 3.0, 50.0, 0.8),
        ]
    )

    ranked = rank_dynamic_concept_leaders(frame)

    assert ranked.loc[ranked["leader_rank"].eq(1), "vt_symbol"].item() == "a"
    assert ranked.loc[ranked["is_top3"], "vt_symbol"].tolist() == ["a", "b", "c"]
    assert ranked["member_count"].eq(4).all()

    with pytest.raises(ValueError, match="outcome columns are prohibited"):
        rank_dynamic_concept_leaders(frame.assign(d1_net_return_pct=99.0))


def test_dynamic_rank_is_invariant_to_future_mutation() -> None:
    first = pd.Timestamp("2026-01-05")
    second = pd.Timestamp("2026-01-06")
    rows = []
    for symbol, gain in (("a", 30.0), ("b", 20.0), ("c", 10.0)):
        rows.append(_member(symbol, gain, gain / 2, 100.0, 1.0, first))
        rows.append(_member(symbol, gain + 1, gain / 2, 100.0, 1.0, second))
    original = pd.DataFrame(rows)
    mutated = original.copy()
    mutated.loc[mutated["trade_date"].eq(second), "return20_pct"] *= -100

    before = rank_dynamic_concept_leaders(original)
    after = rank_dynamic_concept_leaders(mutated)

    left = before.loc[before["trade_date"].eq(first), ["vt_symbol", "leader_rank"]]
    right = after.loc[after["trade_date"].eq(first), ["vt_symbol", "leader_rank"]]
    pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))


def test_main_rise_path_numbers_only_restarts_confirmed_by_a_higher_high() -> None:
    path = pd.DataFrame(
        [
            _path_row("2026-01-05", 10.0, 10.2, 9.8, 5.0),
            _path_row("2026-01-06", 9.7, 10.0, 9.6, -3.0),
            _path_row("2026-01-07", 9.9, 10.0, 9.7, 2.0),
            _path_row("2026-01-08", 10.4, 10.5, 9.9, 5.0),
            _path_row("2026-01-09", 10.0, 10.3, 9.9, -3.8),
            _path_row("2026-01-12", 10.2, 10.3, 9.9, 2.0),
            _path_row("2026-01-13", 10.8, 11.0, 10.2, 5.9),
            _path_row("2026-01-14", 10.5, 10.8, 10.3, -2.8),
            _path_row("2026-01-15", 10.7, 10.8, 10.4, 1.9),
        ]
    )

    state = build_main_rise_path_state(path)
    reversals = state.loc[state["weak_to_strong_day"]]

    assert reversals["pullback_opportunity_ordinal"].tolist() == [1, 2, 3]
    assert reversals["confirmed_restart_count"].tolist() == [0, 1, 2]
    assert reversals["main_rise_active"].all()


def test_bounce_without_a_higher_high_does_not_create_second_opportunity() -> None:
    path = pd.DataFrame(
        [
            _path_row("2026-01-05", 10.0, 10.2, 9.8, 5.0),
            _path_row("2026-01-06", 9.7, 10.0, 9.6, -3.0),
            _path_row("2026-01-07", 9.9, 10.0, 9.7, 2.0),
            _path_row("2026-01-08", 9.6, 9.9, 9.5, -3.0),
            _path_row("2026-01-09", 9.8, 9.9, 9.6, 2.0),
        ]
    )

    state = build_main_rise_path_state(path)
    reversals = state.loc[state["weak_to_strong_day"]]

    assert reversals["pullback_opportunity_ordinal"].tolist() == [1]
    assert state.iloc[-1]["pullback_block_reason"] == "prior_restart_not_confirmed"


def test_concept_alias_change_does_not_reset_stock_pullback_sequence() -> None:
    prices = [
        ("2026-01-05", 10.0, 10.2, 9.8, 5.0),
        ("2026-01-06", 9.7, 10.0, 9.6, -3.0),
        ("2026-01-07", 9.9, 10.0, 9.7, 2.0),
        ("2026-01-08", 10.4, 10.5, 9.9, 5.0),
        ("2026-01-09", 10.0, 10.3, 9.9, -3.8),
        ("2026-01-12", 10.2, 10.3, 9.9, 2.0),
    ]
    rows = []
    for index, values in enumerate(prices, start=1):
        primary = "BK1" if index <= 3 else "BK2"
        for sector_id in ("BK1", "BK2"):
            row = _path_row(*values)
            row.update(
                {
                    "sector_id": sector_id,
                    "concept_campaign_id": f"{sector_id}:1",
                    "leader_rank": 1 if sector_id == primary else 2,
                    "stock_session_index": index,
                }
            )
            rows.append(row)

    state = build_main_rise_path_state(pd.DataFrame(rows))
    reversals = state.loc[state["weak_to_strong_day"]]

    assert len(state) == 6
    assert reversals["pullback_opportunity_ordinal"].tolist() == [1, 2]
    assert reversals["sector_id"].tolist() == ["BK1", "BK2"]


def test_main_rise_state_is_invariant_to_future_price_mutation() -> None:
    original = pd.DataFrame(
        [
            _path_row("2026-01-05", 10.0, 10.2, 9.8, 5.0),
            _path_row("2026-01-06", 9.7, 10.0, 9.6, -3.0),
            _path_row("2026-01-07", 9.9, 10.0, 9.7, 2.0),
            _path_row("2026-01-08", 10.4, 10.5, 9.9, 5.0),
        ]
    )
    mutated = original.copy()
    mutated.loc[mutated["trade_date"].eq("2026-01-08"), ["close_price", "high_price"]] = 99.0

    before = build_main_rise_path_state(original)
    after = build_main_rise_path_state(mutated)

    columns = [
        "trade_date",
        "main_rise_active",
        "pullback_opportunity_ordinal",
        "weak_to_strong_day",
        "confirmed_restart_count",
    ]
    pd.testing.assert_frame_equal(before.iloc[:3][columns], after.iloc[:3][columns])


@pytest.mark.parametrize(
    ("low", "expected"),
    ((10.1, "ma5"), (9.5, "ma10"), (8.5, "ma20"), (7.0, "below_ma20")),
)
def test_support_zone_follows_ma5_then_ma10_sequence(
    low: float, expected: str
) -> None:
    assert (
        classify_support_zone(low, ma5=10.0, ma10=9.0, ma20=8.0) == expected
    )


def test_signal_selection_deduplicates_concept_aliases_and_has_no_outcome() -> None:
    rows = [
        _signal_row("BK1", "Concept A", rank=2, concept_relative=0.8),
        _signal_row("BK2", "Concept B", rank=1, concept_relative=0.7),
    ]
    features = assign_chronological_blocks(
        pd.DataFrame(rows * 5).assign(
            trade_date=[
                pd.Timestamp("2026-01-05"),
                pd.Timestamp("2026-01-05"),
                pd.Timestamp("2026-01-06"),
                pd.Timestamp("2026-01-06"),
                pd.Timestamp("2026-01-07"),
                pd.Timestamp("2026-01-07"),
                pd.Timestamp("2026-01-08"),
                pd.Timestamp("2026-01-08"),
                pd.Timestamp("2026-01-09"),
                pd.Timestamp("2026-01-09"),
            ]
        )
    )
    rule = _rule()

    selected = select_rule_signals(features, rule)

    assert len(selected) == 5
    assert selected["sector_id"].eq("BK2").all()
    assert "d1_net_return_pct" not in selected

    with pytest.raises(ValueError, match="outcome columns are prohibited"):
        select_rule_signals(features.assign(d1_net_return_pct=1.0), rule)


def test_later_confirmed_restart_can_reuse_ma10_support() -> None:
    row = _signal_row("BK1", "Concept", rank=1)
    row.update(
        {
            "confirmed_restart_count": 2,
            "pullback_opportunity_ordinal": 3,
            "support_zone": "ma10",
        }
    )
    features = pd.DataFrame([row])
    features["block"] = 1

    selected = select_rule_signals(features, _rule())

    assert len(selected) == 1


def test_outcomes_attach_only_after_signal_freeze() -> None:
    features = pd.DataFrame([_signal_row("BK1", "Concept", rank=1)])
    features["block"] = 1
    signal = select_rule_signals(features, _rule())
    outcomes = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2026-01-05"),
                "vt_symbol": "000001.SZSE",
                "close_d1": 11.0,
                "close_d3": 12.0,
                "close_d5": 13.0,
                "d1_net_return_pct": 9.8,
                "d3_net_return_pct": 19.8,
                "d5_net_return_pct": 29.8,
            }
        ]
    )

    trade = attach_close_outcomes(signal, outcomes).iloc[0]

    assert trade["d1_net_return_pct"] == pytest.approx(9.8)
    assert summarize_returns(pd.DataFrame([trade]))["positive_rate_pct"] == 100.0


def test_choose_rule_uses_only_qualified_grid_rows() -> None:
    grid = pd.DataFrame(
        [
            _grid_row("a", qualified=False, validation_mean=9.0),
            _grid_row("b", qualified=True, validation_mean=1.0),
            _grid_row("c", qualified=True, validation_mean=2.0),
        ]
    )

    selected = choose_rule(grid)

    assert selected is not None
    assert selected.version == "c"


def test_final_gates_report_exact_failure() -> None:
    metrics = pd.DataFrame(
        [
            _metric("all", 120, 61.0, 0.5, 1.3, -10.0, compound=61.0),
            _metric("block_4", 35, 61.0, 0.5, 1.2, -5.0, compound=5.0),
            _metric("block_5", 10, 61.0, 1.0, 1.4, -4.0, compound=5.0),
        ]
    )

    qualified, failures = final_gates(metrics)

    assert not qualified
    assert failures == ["block5_trades_below_30"]


def test_final_gates_require_strictly_more_than_sixty_percent() -> None:
    metrics = pd.DataFrame(
        [
            _metric("all", 120, 60.0, 0.5, 1.3, -10.0, compound=60.0),
            _metric("block_4", 35, 60.0, 0.5, 1.2, -5.0, compound=5.0),
            _metric("block_5", 35, 60.0, 1.0, 1.4, -4.0, compound=5.0),
        ]
    )

    qualified, failures = final_gates(metrics)

    assert not qualified
    assert "pooled_win_rate_not_above_60" in failures
    assert "pooled_compound_not_above_60" in failures
    assert "block4_win_rate_not_above_60" in failures
    assert "block5_win_rate_not_above_60" in failures


def test_report_keeps_strategy_non_production() -> None:
    report = build_report(
        coverage={"eligible_concepts": 2},
        fingerprints={},
        grid=pd.DataFrame(),
        selected_rule=_rule(),
        trades=pd.DataFrame(),
        metrics=pd.DataFrame(),
        qualified=False,
        failed_gates=["holdout_failed"],
        cases=pd.DataFrame(),
        outcome_profiles=pd.DataFrame(),
    )

    markdown = render_main_rise_weak_to_strong_markdown(report)

    assert report["research_rule_frozen"] is True
    assert report["production_ready"] is False
    assert report["formal_metrics"] is None
    assert "holdout_failed" in markdown


def _member(
    symbol: str,
    return20: float,
    return10: float,
    turnover5: float,
    expansion: float,
    trade_date: pd.Timestamp | None = None,
) -> dict[str, object]:
    resolved_trade_date = trade_date or pd.Timestamp("2026-01-05")
    return {
        "sector_id": "BK1",
        "trade_date": resolved_trade_date,
        "vt_symbol": symbol,
        "return60_pct": return20 * 1.5,
        "return20_pct": return20,
        "return10_pct": return10,
        "turnover5": turnover5,
        "turnover_expansion": expansion,
    }


def _rule() -> WeakToStrongRule:
    return WeakToStrongRule(
        version="test-rule",
        minimum_return60_pct=20.0,
        minimum_top3_days10=4,
        minimum_new_high_days20=2,
        maximum_volume_ratio=1.2,
    )


def _signal_row(
    sector_id: str,
    concept_name: str,
    *,
    rank: int,
    concept_relative: float = 0.8,
) -> dict[str, object]:
    row = {column: 1.0 for column in SIGNAL_FEATURE_COLUMNS}
    row.update(
        {
            "sector_id": sector_id,
            "concept_name": concept_name,
            "trade_date": pd.Timestamp("2026-01-05"),
            "vt_symbol": "000001.SZSE",
            "stock_name": "Synthetic",
            "open_price": 9.9,
            "high_price": 10.2,
            "low_price": 9.7,
            "close_price": 10.0,
            "daily_return_pct": 2.0,
            "prior_daily_return_pct": -2.0,
            "return20_pct": 25.0,
            "return60_pct": 45.0,
            "ma5": 9.8,
            "ma10": 9.5,
            "ma20": 9.0,
            "ma60": 8.0,
            "episode_pullback_low": 9.7,
            "drawdown_from_prior_high_pct": -5.0,
            "volume_ratio5": 1.0,
            "close_location": 0.8,
            "concept_daily_return_pct": 1.0,
            "concept_prior_daily_return_pct": -1.0,
            "concept_relative_pct": concept_relative,
            "leader_score": 0.9,
            "leader_rank": rank,
            "prior_leader_rank": rank,
            "member_count": 10,
            "top3_days5": 4,
            "top3_days10": 7,
            "new_high_days20": 3,
            "main_rise_active": True,
            "main_rise_active_sessions": 10,
            "main_rise_gain_pct": 20.0,
            "confirmed_restart_count": 0,
            "pullback_opportunity_ordinal": 1,
            "pullback_duration": 2,
            "weak_to_strong_day": True,
            "pullback_block_reason": None,
            "concept_restrength": True,
            "active_direction": "GOLD",
            "danger_state": "NORMAL",
            "support_zone": "ma5",
        }
    )
    return row


def _grid_row(
    version: str, *, qualified: bool, validation_mean: float
) -> dict[str, object]:
    return {
        **_rule().__dict__,
        "version": version,
        "selection_qualified": qualified,
        "validation_mean_return_pct": validation_mean,
        "validation_profit_factor": 1.5,
        "development_mean_return_pct": 1.0,
    }


def _metric(
    segment: str,
    trades: int,
    positive_rate: float,
    mean: float,
    profit_factor: float,
    drawdown: float,
    *,
    compound: float = 10.0,
) -> dict[str, object]:
    return {
        "segment": segment,
        "closed_trades": trades,
        "positive_rate_pct": positive_rate,
        "mean_return_pct": mean,
        "median_return_pct": mean,
        "profit_factor": profit_factor,
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
    }


def _path_row(
    trade_date: str,
    close_price: float,
    high_price: float,
    low_price: float,
    daily_return_pct: float,
) -> dict[str, object]:
    return {
        "sector_id": "BK1",
        "concept_campaign_id": "BK1:1",
        "candidate_run_id": 1,
        "trade_date": trade_date,
        "vt_symbol": "000001.SZSE",
        "open_price": close_price * 0.99,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "daily_return_pct": daily_return_pct,
        "return60_pct": 30.0,
        "top3_days10": 5,
        "new_high_days20": 2,
        "ma5": 9.6,
        "ma10": 9.3,
        "ma20": 9.0,
        "ma60": 8.0,
    }
