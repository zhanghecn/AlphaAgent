from __future__ import annotations

from datetime import date

import pandas as pd

from alphaagent.server.services.limit_up.capital_mainline_research import (
    discover_concept_cycles,
    discover_market_cycles,
    pairwise_aliases,
    rank_cycle_roles,
    select_primary_concept,
)
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
)


def test_broad_concept_does_not_win_by_absolute_limit_count() -> None:
    selected = select_primary_concept(
        [
            {
                "sector_id": "A",
                "mainline_score": 0.52,
                "ladder_strength": 0.42,
                "flow_strength": 0.30,
                "index_strength": 0.45,
                "member_count": 1000,
                "sealed_count": 20,
            },
            {
                "sector_id": "B",
                "mainline_score": 0.88,
                "ladder_strength": 0.90,
                "flow_strength": 0.85,
                "index_strength": 0.82,
                "member_count": 40,
                "sealed_count": 6,
            },
        ]
    )
    assert selected == "B"


def test_close_multi_theme_scores_remain_unresolved() -> None:
    selected = select_primary_concept(
        [
            {
                "sector_id": "A",
                "mainline_score": 0.80,
                "ladder_strength": 0.80,
                "flow_strength": 0.80,
                "index_strength": 0.80,
            },
            {
                "sector_id": "B",
                "mainline_score": 0.79,
                "ladder_strength": 0.79,
                "flow_strength": 0.79,
                "index_strength": 0.79,
            },
        ]
    )
    assert selected is None


def test_alias_pairs_do_not_form_a_transitive_mega_group() -> None:
    members = {
        "A": {f"S{i}" for i in range(10)},
        "B": {f"S{i}" for i in range(5, 15)},
        "C": {f"S{i}" for i in range(10, 20)},
    }
    dates = pd.date_range("2026-01-01", periods=6)
    history = pd.DataFrame(
        [
            {"trade_date": day, "sector_id": sector, "return_1d_pct": value}
            for sector, values in {
                "A": [1, 2, 3, 4, 5, 6],
                "B": [1, 2, 3, 4, 5, 6],
                "C": [1, 2, 3, 4, 5, 6],
            }.items()
            for day, value in zip(dates, values, strict=True)
        ]
    )
    aliases = pairwise_aliases(members, history, min_jaccard=0.30)
    assert aliases == [("A", "B"), ("B", "C")]
    assert ("A", "C") not in aliases


def test_market_cycle_can_cross_calendar_month() -> None:
    inputs = _inputs_with_sentiment(
        [
            {"date": date(2026, 3, 30), "score": 25, "phase": "ice"},
            {"date": date(2026, 3, 31), "score": 35, "phase": "repair"},
            {"date": date(2026, 4, 1), "score": 52, "phase": "repair"},
            {"date": date(2026, 4, 2), "score": 72, "phase": "climax"},
        ]
    )
    cycles = discover_market_cycles(inputs)
    assert cycles.loc[cycles["trade_date"].ge(date(2026, 3, 31)), "market_cycle_id"].nunique() == 1


def test_concept_cycle_does_not_rewrite_earlier_phase_from_future() -> None:
    panel = _concept_panel()
    first = discover_concept_cycles(panel.iloc[:3], pd.DataFrame())
    changed = panel.copy()
    changed.loc[changed["trade_date"].eq(date(2026, 4, 3)), "mainline_percentile"] = 0.0
    second = discover_concept_cycles(changed, pd.DataFrame())
    assert first.iloc[0]["concept_phase"] == second.iloc[0]["concept_phase"]
    assert first.iloc[0]["concept_cycle_id"] == second.iloc[0]["concept_cycle_id"]


def test_market_cycle_does_not_rewrite_earlier_rows_from_future() -> None:
    rows = [
        {"date": date(2026, 4, 1), "score": 25, "phase": "ice"},
        {"date": date(2026, 4, 2), "score": 52, "phase": "repair"},
        {"date": date(2026, 4, 3), "score": 70, "phase": "climax"},
    ]
    original = discover_market_cycles(_inputs_with_sentiment(rows))
    changed = discover_market_cycles(
        _inputs_with_sentiment(
            rows
            + [{"date": date(2026, 4, 7), "score": 5, "phase": "ice"}]
        )
    )

    assert original[["market_cycle_id", "market_phase"]].to_dict("records") == changed.iloc[:3][
        ["market_cycle_id", "market_phase"]
    ].to_dict("records")


def test_future_confirmation_changes_realized_role_but_not_asof_role() -> None:
    first_date = date(2026, 4, 1)
    next_date = date(2026, 4, 2)
    concept_cycles = pd.DataFrame(
        [
            {
                "trade_date": first_date,
                "sector_id": "A",
                "sector_name": "Concept A",
                "market_cycle_id": "MC-1",
                "concept_cycle_id": "A:1",
                "concept_cycle_start": first_date,
                "concept_phase": "ignition_candidate",
                "mainline_score": 0.9,
                "mainline_percentile": 0.9,
                "index_strength": 0.8,
                "ladder_strength": 0.8,
                "flow_strength": 0.8,
                "capital_state": "turnover_proxy_only",
                "membership_evidence_level": "point_in_time",
                "membership_snapshot_date": date(2026, 3, 31),
                "sealed_count": 1,
                "unique_follower_ratio": 0.0,
            }
        ]
    )
    event_links = pd.DataFrame(
        [
            {
                "trade_date": first_date,
                "vt_symbol": "600001.SSE",
                "name": "Example",
                "sector_id": "A",
                "limit_up_streak": 1,
                "turnover": 100.0,
                "board_pattern": "ignition_candidate",
            }
        ]
    )
    base_ledger = pd.DataFrame(
        [
            {
                "trade_date": first_date,
                "vt_symbol": "600001.SSE",
                "is_limit_up": True,
                "limit_up_streak": 1,
            },
            {
                "trade_date": next_date,
                "vt_symbol": "600001.SSE",
                "is_limit_up": True,
                "limit_up_streak": 2,
            },
        ]
    )
    failed_next_day = base_ledger.copy()
    failed_next_day.loc[failed_next_day["trade_date"].eq(next_date), "is_limit_up"] = False

    confirmed = rank_cycle_roles(
        pd.DataFrame(), concept_cycles, event_links, base_ledger
    )
    failed = rank_cycle_roles(
        pd.DataFrame(), concept_cycles, event_links, failed_next_day
    )

    assert confirmed.iloc[0]["role_asof"] == failed.iloc[0]["role_asof"]
    assert "confirmed_ignition_leader" in confirmed.iloc[0]["role_realized"]
    assert "confirmed_ignition_leader" not in failed.iloc[0]["role_realized"]


def _inputs_with_sentiment(rows: list[dict[str, object]]) -> CapitalMainlineInputs:
    return CapitalMainlineInputs(
        trade_dates=tuple(row["date"] for row in rows),
        concept_bars=(),
        sector_fund_flows=(),
        stock_fund_flows=(),
        memberships=(),
        membership_scopes=(),
        membership_counts=(),
        current_memberships=(),
        stock_bars=(),
        limit_up_events=(),
        sentiment_points=tuple(rows),
        formal_candidate_days=(),
        coverage={},
        fingerprints={},
    )


def _concept_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": date(2026, 4, 1),
                "sector_id": "A",
                "sector_name": "Concept A",
                "mainline_percentile": 0.90,
                "first_board_count": 1,
                "sealed_count": 1,
                "one_to_two_count": 0,
                "two_to_three_count": 0,
                "index_strength": 0.80,
                "capital_state": "turnover_proxy_only",
                "mainline_rank": 1,
            },
            {
                "trade_date": date(2026, 4, 2),
                "sector_id": "A",
                "sector_name": "Concept A",
                "mainline_percentile": 0.85,
                "first_board_count": 0,
                "sealed_count": 2,
                "one_to_two_count": 1,
                "two_to_three_count": 0,
                "index_strength": 0.82,
                "capital_state": "turnover_proxy_only",
                "mainline_rank": 1,
            },
            {
                "trade_date": date(2026, 4, 3),
                "sector_id": "A",
                "sector_name": "Concept A",
                "mainline_percentile": 0.88,
                "first_board_count": 1,
                "sealed_count": 3,
                "one_to_two_count": 0,
                "two_to_three_count": 1,
                "index_strength": 0.84,
                "capital_state": "turnover_proxy_only",
                "mainline_rank": 1,
            },
        ]
    )
