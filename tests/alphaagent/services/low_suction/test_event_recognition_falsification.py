from __future__ import annotations

from datetime import date

import pandas as pd

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.event_recognition_falsification import (
    EVIDENCE_LEVEL,
    build_event_falsification_report,
    build_exact_reason_relations,
    build_recognition_candidates,
    chronological_event_blocks,
    evaluate_retest_gate,
    execute_frozen_limit_grid,
    summarize_regime_diagnostics,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 7, 1),
                "vt_symbol": "600001.SSE",
                "stock_name": "示例一",
                "reason": "商业航天+卫星互联网",
                "limit_times": 2,
                "limit_up_suc_rate": 0.8,
                "fd_amount": 80.0,
                "float_market_cap": 1_000.0,
                "amount": 500.0,
            },
            {
                "event_id": 2,
                "source_date": date(2025, 7, 1),
                "vt_symbol": "600002.SSE",
                "stock_name": "示例二",
                "reason": "商业航天器",
                "limit_times": 3,
                "limit_up_suc_rate": 0.9,
                "fd_amount": 90.0,
                "float_market_cap": 1_000.0,
                "amount": 600.0,
            },
        ]
    )


def _concepts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sector_id": "BK0963", "concept_name": "商业航天"},
            {"sector_id": "BK9999", "concept_name": "卫星互联网"},
        ]
    )


def _four_relations() -> pd.DataFrame:
    rows = []
    for index in range(1, 5):
        rows.append(
            {
                "event_id": index,
                "source_date": date(2025, 7, 1),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "vt_symbol": f"60000{index}.SSE",
                "stock_name": f"示例{index}",
                "limit_times": 5 - index,
                "limit_up_suc_rate": 0.9 - index / 100,
                "fd_amount": 100.0 - index,
                "float_market_cap": 1_000.0,
                "amount": 1_000.0 - index,
            }
        )
    return pd.DataFrame(rows)


def _active_breakout_state() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": date(2025, 7, 1),
                "sector_id": "BK0963",
                "definition": "breakout_trend",
                "in_cycle": True,
                "cycle_id": "cycle-1",
                "relative_percentile": 0.95,
            }
        ]
    )


def _candidate_bars() -> pd.DataFrame:
    dates = pd.date_range("2025-04-01", "2025-07-04", freq="B")
    rows = []
    for index in range(1, 5):
        for offset, trade_date in enumerate(dates):
            close = 9.0 + offset / 70
            if trade_date.date() == date(2025, 7, 1):
                close = 10.0
            rows.append(
                {
                    "vt_symbol": f"60000{index}.SSE",
                    "trade_date": trade_date.date(),
                    "open_price": close,
                    "high_price": close * 1.01,
                    "low_price": close * 0.99,
                    "close_price": close,
                    "volume": 1_000.0,
                }
            )
    return pd.DataFrame(rows)


def _calendar() -> tuple[date, ...]:
    return tuple(pd.date_range("2025-04-01", "2025-07-04", freq="B").date)


def _candidate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 7, 1),
                "entry_date": date(2025, 7, 2),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "recognition_rank": 1,
                "signal_close": 10.0,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "evidence_level": EVIDENCE_LEVEL,
            }
        ]
    )


def _execution_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 1),
                "open_price": 9.8,
                "high_price": 10.0,
                "low_price": 9.8,
                "close_price": 10.0,
                "volume": 1_000.0,
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 2),
                "open_price": 9.9,
                "high_price": 10.0,
                "low_price": 9.55,
                "close_price": 9.8,
                "volume": 1_000.0,
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 3),
                "open_price": 9.9,
                "high_price": 10.4,
                "low_price": 9.8,
                "close_price": 10.3,
                "volume": 1_000.0,
            },
        ]
    )


def test_reason_matching_is_exact_and_does_not_use_current_members() -> None:
    relations = build_exact_reason_relations(_events(), _concepts())

    assert set(relations["concept_name"]) == {"商业航天", "卫星互联网"}
    assert set(relations["vt_symbol"]) == {"600001.SSE"}
    assert "memberships" not in relations.columns


def test_recognition_top3_requires_three_candidates_and_uses_lexicographic_order() -> None:
    candidates = build_recognition_candidates(
        _four_relations(),
        _active_breakout_state(),
        _candidate_bars(),
        _calendar(),
    )

    assert candidates["vt_symbol"].tolist() == [
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    ]
    assert candidates["recognition_rank"].tolist() == [1, 2, 3]
    assert set(candidates["evidence_level"]) == {EVIDENCE_LEVEL}


def test_recognition_cohort_is_empty_with_only_two_candidates() -> None:
    candidates = build_recognition_candidates(
        _four_relations().iloc[:2],
        _active_breakout_state(),
        _candidate_bars(),
        _calendar(),
    )

    assert candidates.empty


def test_recognition_candidate_requires_entry_and_exit_inside_calendar() -> None:
    candidates = build_recognition_candidates(
        _four_relations(),
        _active_breakout_state(),
        _candidate_bars(),
        tuple(pd.date_range("2025-04-01", "2025-07-02", freq="B").date),
    )

    assert candidates.empty


def test_limit_order_uses_next_session_low_but_not_close_to_decide_fill() -> None:
    outcomes = execute_frozen_limit_grid(
        _candidate(),
        _execution_bars(),
        trading_dates=(date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3)),
    )

    assert outcomes.loc[outcomes["entry_depth_pct"].eq(4), "status"].item() == "closed"
    assert outcomes.loc[outcomes["entry_depth_pct"].eq(6), "status"].item() == "not_filled"


def test_double_cost_never_improves_net_return() -> None:
    normal = execute_frozen_limit_grid(
        _candidate(),
        _execution_bars(),
        trading_dates=(date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3)),
        cost_multiplier=1.0,
    )
    stressed = execute_frozen_limit_grid(
        _candidate(),
        _execution_bars(),
        trading_dates=(date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3)),
        cost_multiplier=2.0,
    )
    joined = normal.merge(
        stressed,
        on=["event_id", "entry_depth_pct"],
        suffixes=("_normal", "_stressed"),
    )
    closed = joined.loc[
        joined["status_normal"].eq("closed") & joined["status_stressed"].eq("closed")
    ]

    assert closed["net_return_pct_stressed"].le(closed["net_return_pct_normal"]).all()


def test_chronological_event_blocks_are_disjoint_and_ordered() -> None:
    dates = tuple(pd.date_range("2025-06-27", periods=20, freq="B").date)
    blocks = chronological_event_blocks(dates, block_count=5)

    assert blocks["source_date"].nunique() == 20
    assert blocks.groupby("block")["source_date"].max().is_monotonic_increasing


def test_retest_gate_requires_four_positive_blocks_and_double_cost() -> None:
    metrics = pd.DataFrame(
        [
            {
                "entry_depth_pct": 4.0,
                "closed_trades": 120,
                "positive_blocks": 4,
                "double_cost_mean_net_return_pct": 0.2,
            }
        ]
    )

    decision = evaluate_retest_gate(metrics)

    assert decision["status"] == "worth_strict_retest"
    assert decision["formal_rule_selected"] is False


def test_regime_diagnostic_reports_context_without_selecting_a_policy() -> None:
    normal = execute_frozen_limit_grid(
        _candidate(),
        _execution_bars(),
        trading_dates=(date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3)),
    )
    stressed = execute_frozen_limit_grid(
        _candidate(),
        _execution_bars(),
        trading_dates=(date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3)),
        cost_multiplier=2.0,
    )

    diagnostics = summarize_regime_diagnostics(normal, stressed)

    assert set(diagnostics["regime_key"]) == {"GOLD/NORMAL"}
    assert "policy" not in diagnostics.columns
    assert diagnostics["observed_time_blocks"].max() == 1
    assert not diagnostics["material_days_at_least_20"].any()


def test_empty_depth_metrics_fail_closed_as_no_edge() -> None:
    decision = evaluate_retest_gate(
        pd.DataFrame(
            columns=[
                "entry_depth_pct",
                "closed_trades",
                "positive_blocks",
                "double_cost_mean_net_return_pct",
            ]
        )
    )

    assert decision["status"] == "no_event_recognition_edge"


def test_report_never_exposes_formal_metrics_or_a_strict_top3_claim() -> None:
    metrics = pd.DataFrame(
        [
            {
                "entry_depth_pct": 4.0,
                "closed_trades": 120,
                "positive_blocks": 4,
                "double_cost_mean_net_return_pct": 0.2,
                "qualified_for_strict_retest": True,
            }
        ]
    )
    report = build_event_falsification_report(
        coverage={"event_dates": 96},
        depth_metrics=metrics,
        block_metrics=pd.DataFrame(),
        discovery_start=date(2023, 3, 28),
        discovery_end=date(2025, 11, 17),
        input_fingerprints={},
    )

    assert report["formal_metrics"] is None
    assert report["holdout_price_values_read"] is False
    assert report["cohort_label"] == "recognition_top3_incomplete_denominator"


def test_cli_does_not_allow_event_study_parameter_search() -> None:
    args = build_parser().parse_args(
        ["v2-event-falsification", "--format", "json"]
    )

    assert args.command == "v2-event-falsification"
    assert not hasattr(args, "start")
    assert not hasattr(args, "entry_depths")
