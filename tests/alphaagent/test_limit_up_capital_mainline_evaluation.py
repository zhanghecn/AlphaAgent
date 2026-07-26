from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    build_candidate_feature_frame,
    extract_formal_candidates,
    extract_formal_recommendations,
    performance_summary,
    quality_ceiling,
    select_two_slot_account,
    validate_candidate_feature_names,
)
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
)


def test_extract_formal_candidates_freezes_eligible_entry_pool() -> None:
    rows = extract_formal_candidates(
        [
            {
                "trade_date": "2026-07-01",
                "validation_phase": "locked_holdout",
                "lane_portfolio": {
                    "candidate_pool": {
                        "first_board": [
                            _candidate("600001.SSE", "eligible", 2.0),
                            _candidate("600002.SSE", "blocked", 8.0),
                            {**_candidate("600003.SSE", "eligible", 9.0), "entry_price": None},
                        ]
                    }
                },
            }
        ]
    )

    assert rows["vt_symbol"].tolist() == ["600001.SSE"]
    assert rows.iloc[0]["return_pct"] == 2.0
    assert rows.iloc[0]["validation_phase"] == "locked_holdout"


def test_formal_recommendations_use_profitability_scope_and_right_censor() -> None:
    rows = extract_formal_recommendations(
        [
            {
                "trade_date": "2026-07-01",
                "lane_portfolio": {
                    "candidate_pool": {
                        "two_to_three": [
                            _formal_relay_candidate(
                                "600001.SSE",
                                signal_date="2026-07-01",
                                result_date="2026-07-02",
                                return_pct=2.0,
                            )
                        ]
                    }
                },
            },
            {
                "trade_date": "2026-07-02",
                "lane_portfolio": {
                    "candidate_pool": {
                        "two_to_three": [
                            _formal_relay_candidate(
                                "600002.SSE",
                                signal_date="2026-07-02",
                                result_date="2026-07-03",
                                return_pct=3.0,
                            ),
                            {
                                **_formal_relay_candidate(
                                    "600003.SSE",
                                    signal_date="2026-07-02",
                                    result_date="2026-07-03",
                                    return_pct=8.0,
                                ),
                                "entry_price": 600.0,
                                "limit_price": 600.0,
                            },
                        ]
                    }
                },
            },
        ],
        start=date(2026, 7, 1),
        end=date(2026, 7, 3),
        available_exit_keys={
            ("600001.SSE", date(2026, 7, 2)),
            ("600003.SSE", date(2026, 7, 3)),
        },
        formal_settlement_returns={
            ("600001.SSE", date(2026, 7, 1)): 1.25,
        },
    )

    assert rows["vt_symbol"].tolist() == [
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    ]
    assert rows.iloc[0]["return_pct"] == 1.25
    assert pd.isna(rows.iloc[1]["return_pct"])
    assert pd.isna(rows.iloc[2]["return_pct"])
    assert set(rows["candidate_scope"]) == {"formal_recommendations"}


def test_candidate_features_reject_future_labels() -> None:
    with pytest.raises(ValueError, match="future feature"):
        validate_candidate_feature_names(
            ["prior_mainline_percentile", "final_role", "d1_return"]
        )


def test_performance_summary_reports_retention_and_daily_equity() -> None:
    frame = pd.DataFrame(
        [
            _row("2026-07-01", "600001.SSE", 2.0),
            _row("2026-07-01", "600002.SSE", -1.0),
            _row("2026-07-02", "600003.SSE", 4.0),
        ]
    )

    summary = performance_summary(frame.iloc[:2], baseline_count=3)

    assert summary["closed_count"] == 2
    assert summary["win_rate_pct"] == 50.0
    assert summary["retention_pct"] == pytest.approx(66.6667)
    assert summary["daily_equal_weight_compounded_pct"] == pytest.approx(0.5)


def test_two_slot_account_respects_t_plus_one_occupation() -> None:
    frame = pd.DataFrame(
        [
            _row("2026-07-01", "600001.SSE", 1.0, signal_time="10:00:00"),
            _row("2026-07-01", "600002.SSE", 1.0, signal_time="10:01:00"),
            _row("2026-07-01", "600003.SSE", 1.0, signal_time="10:02:00"),
            _row("2026-07-02", "600004.SSE", 1.0, signal_time="10:00:00"),
            _row("2026-07-03", "600005.SSE", 1.0, signal_time="10:00:00"),
        ]
    )

    selected = select_two_slot_account(
        frame,
        trade_dates=(date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)),
    )

    assert selected["vt_symbol"].tolist() == [
        "600001.SSE",
        "600002.SSE",
        "600005.SSE",
    ]


def test_quality_ceiling_proves_when_seventy_is_impossible_at_retention_gate() -> None:
    frame = pd.DataFrame(
        [
            _row("2026-07-01", f"600{index:03d}.SSE", 1.0 if index < 49 else -1.0)
            for index in range(100)
        ]
    )

    ceiling = quality_ceiling(frame, minimum_retention=0.80)

    assert ceiling["required_closed_count"] == 80
    assert ceiling["maximum_possible_win_rate_pct"] == 61.25
    assert ceiling["target_70_possible"] is False


def test_same_day_concept_close_cannot_change_first_board_prior_features() -> None:
    inputs = _feature_inputs()
    panel = pd.DataFrame(
        [
            _panel_row(date(2026, 7, 1), 0.85),
            _panel_row(date(2026, 7, 2), 0.95),
        ]
    )
    bundle = {
        "concept_panel": panel,
        "concept_cycles": pd.DataFrame(
            [
                {
                    **_panel_row(date(2026, 7, 1), 0.85),
                    "concept_cycle_id": "A:1",
                    "concept_phase": "confirmation",
                },
                {
                    **_panel_row(date(2026, 7, 2), 0.95),
                    "concept_cycle_id": "A:1",
                    "concept_phase": "acceleration",
                },
            ]
        ),
        "roles": pd.DataFrame(),
        "event_ledger": pd.DataFrame(),
        "market_cycles": pd.DataFrame(
            [
                {
                    "trade_date": date(2026, 7, 1),
                    "market_cycle_id": "MC-1",
                    "market_phase": "launch",
                }
            ]
        ),
    }
    changed = {**bundle, "concept_panel": panel.copy()}
    changed["concept_panel"].loc[
        changed["concept_panel"]["trade_date"].eq(date(2026, 7, 2)),
        "mainline_percentile",
    ] = 0.0

    original = build_candidate_feature_frame(inputs, bundle).iloc[0]
    mutated = build_candidate_feature_frame(inputs, changed).iloc[0]

    assert original["prior_trade_date"] == date(2026, 7, 1)
    assert original["prior_mainline_percentile"] == 0.85
    assert original["prior_mainline_percentile"] == mutated["prior_mainline_percentile"]


def _candidate(
    vt_symbol: str,
    decision: str,
    return_pct: float,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "lane": "first_board",
        "decision": decision,
        "entry_price": 10.0,
        "limit_price": 10.0,
        "signal_time": "10:00:00",
        "pool_rank": 1,
        "outcome": {"next_close_return_pct": return_pct},
    }


def _formal_relay_candidate(
    vt_symbol: str,
    *,
    signal_date: str,
    result_date: str,
    return_pct: float,
) -> dict[str, object]:
    return {
        **_candidate(vt_symbol, "eligible", return_pct),
        "lane": "two_to_three",
        "signal_date": signal_date,
        "entry_date": signal_date,
        "result_date": result_date,
        "relay_trigger_status": "ready",
    }


def _feature_inputs() -> CapitalMainlineInputs:
    return CapitalMainlineInputs(
        trade_dates=(date(2026, 7, 1), date(2026, 7, 2)),
        concept_bars=(),
        sector_fund_flows=(),
        stock_fund_flows=(),
        memberships=(),
        membership_scopes=(),
        membership_counts=({"sector_id": "A", "member_count": 20},),
        current_memberships=(
            {
                "vt_symbol": "600001.SSE",
                "sector_id": "A",
                "sector_name": "Concept A",
                "sector_type": "concept",
            },
        ),
        stock_bars=(),
        limit_up_events=(),
        sentiment_points=(),
        formal_candidate_days=(
            {
                "trade_date": "2026-07-02",
                "validation_phase": "locked_holdout",
                "lane_portfolio": {
                    "candidate_pool": {
                        "first_board": [
                            _candidate("600001.SSE", "eligible", 2.0)
                        ]
                    }
                },
            },
        ),
        coverage={},
        fingerprints={},
    )


def _panel_row(trade_date: date, percentile: float) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "sector_id": "A",
        "sector_name": "Concept A",
        "mainline_score": percentile,
        "mainline_percentile": percentile,
        "index_strength": 0.8,
        "ladder_strength": 0.8,
        "turnover_strength": 0.8,
        "flow_strength": None,
        "capital_state": "turnover_proxy_only",
        "eligible_member_count": 20,
    }


def _row(
    trade_date: str,
    vt_symbol: str,
    return_pct: float,
    *,
    signal_time: str = "10:00:00",
) -> dict[str, object]:
    return {
        "trade_date": date.fromisoformat(trade_date),
        "vt_symbol": vt_symbol,
        "lane": "first_board",
        "signal_time": signal_time,
        "pool_rank": 1,
        "return_pct": return_pct,
    }
