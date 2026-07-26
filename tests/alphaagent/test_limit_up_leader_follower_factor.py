from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
)
from alphaagent.server.services.limit_up.leader_follower_factor import (
    attach_leader_follower_features,
    build_leader_confirmation_events,
    build_realized_follower_mappings,
    discovery_report_sha256,
    evaluate_leader_follower_factors,
    evaluate_frozen_validation,
    _factor_status,
    frozen_early_turnover_mask,
    frozen_turnover_capacity_mask,
    FROZEN_DISCOVERY_SHA256,
    render_frozen_forward_report,
    validate_leader_follower_feature_names,
)


D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)
D3 = date(2026, 7, 3)
D4 = date(2026, 7, 6)
D5 = date(2026, 7, 7)
D6 = date(2026, 7, 8)


def test_confirmed_leader_becomes_tradeable_only_after_confirmation_close() -> None:
    events = build_leader_confirmation_events(_bundle(), (D1, D2, D3, D4))

    assert len(events) == 1
    assert events.iloc[0]["ignition_date"] == D1
    assert events.iloc[0]["confirmation_date"] == D2
    assert events.iloc[0]["first_usable_date"] == D3
    assert events.iloc[0]["leader_symbol"] == "600001.SSE"
    assert events.iloc[0]["index_strength_delta"] == pytest.approx(0.1)


def test_realized_follower_return_cannot_enter_candidate_features() -> None:
    with pytest.raises(ValueError, match="future feature"):
        validate_leader_follower_feature_names(
            ["prior_leader_age_days", "realized_follower_3d_return"]
        )


def test_realized_mapping_stays_in_cycle_and_excludes_leader() -> None:
    inputs = _inputs()
    events = build_leader_confirmation_events(_bundle(), inputs.trade_dates)

    mappings = build_realized_follower_mappings(inputs, _bundle(), events)

    assert set(mappings["follower_symbol"]) == {"600002.SSE", "600003.SSE"}
    assert set(mappings["mapped_role"]) == {"leader_2", "leader_3"}
    leader_2 = mappings.loc[mappings["follower_symbol"].eq("600002.SSE")].iloc[0]
    assert leader_2["follower_first_date"] == D2
    assert leader_2["delay_sessions"] == 0
    assert leader_2["response_day_change_pct"] == pytest.approx(5.0)
    assert leader_2["forward_1d_close_return_pct"] == pytest.approx(10.0)
    assert leader_2["forward_3d_close_return_pct"] == pytest.approx(30.0)


def test_candidate_only_uses_leader_event_after_first_usable_date() -> None:
    events = build_leader_confirmation_events(_bundle(), (D1, D2, D3, D4))
    candidates = pd.DataFrame.from_records(
        [
            _candidate(D2, ["leader_2"], 2.0),
            _candidate(D3, ["leader_2"], 3.0),
        ]
    )

    result = attach_leader_follower_features(candidates, events)

    assert bool(result.iloc[0]["prior_has_confirmed_leader"]) is False
    assert bool(result.iloc[1]["prior_has_confirmed_leader"]) is True
    assert result.iloc[1]["prior_follower_role"] == "leader_2"
    assert result.iloc[1]["prior_leader_symbol"] == "600001.SSE"


def test_factor_evaluation_counts_all_selected_candidates() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                **_candidate(D3, ["leader_2"], 3.0),
                "prior_has_confirmed_leader": True,
                "prior_leader_index_strength": 0.9,
                "prior_leader_index_strength_delta": 0.1,
                "prior_leader_turnover_strength": 0.9,
                "prior_leader_ladder_strength": 0.8,
                "prior_leader_ladder_strength_delta": 0.1,
                "prior_leader_non_divergent": True,
                "prior_follower_role": "leader_2",
            },
            {
                **_candidate(D4, [], -2.0),
                "prior_has_confirmed_leader": True,
                "prior_leader_index_strength": 0.7,
                "prior_leader_index_strength_delta": -0.1,
                "prior_leader_turnover_strength": 0.6,
                "prior_leader_ladder_strength": 0.5,
                "prior_leader_ladder_strength_delta": -0.1,
                "prior_leader_non_divergent": False,
                "prior_follower_role": None,
            },
            {
                **_candidate(D5, [], 1.0),
                "prior_has_confirmed_leader": False,
                "prior_leader_index_strength": None,
                "prior_leader_index_strength_delta": None,
                "prior_leader_turnover_strength": None,
                "prior_leader_ladder_strength": None,
                "prior_leader_ladder_strength_delta": None,
                "prior_leader_non_divergent": False,
                "prior_follower_role": None,
            },
        ]
    )

    results = evaluate_leader_follower_factors(frame)

    assert results["formal_baseline"]["full"]["closed_count"] == 3
    assert results["confirmed_leader"]["full"]["closed_count"] == 2
    assert results["confirmed_leader_mapped_leader_2_3"]["full"]["closed_count"] == 1
    assert results["discovery_early_turnover_ge_080"]["full"]["closed_count"] == 1


def test_frozen_discovery_report_digest_matches_archived_evidence() -> None:
    path = Path(
        "memory/06_backtests/limit_up_leader_follower_factor_formal_discovery_2026_03_07.md"
    )

    assert discovery_report_sha256(path) == FROZEN_DISCOVERY_SHA256


def test_frozen_factor_requires_coverage_turnover_and_no_confirmed_leader() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                "prior_turnover_strength": 0.80,
                "prior_has_confirmed_leader": False,
                "prior_leader_event_coverage_available": True,
            },
            {
                "prior_turnover_strength": 0.90,
                "prior_has_confirmed_leader": True,
                "prior_leader_event_coverage_available": True,
            },
            {
                "prior_turnover_strength": 0.90,
                "prior_has_confirmed_leader": False,
                "prior_leader_event_coverage_available": False,
            },
            {
                "prior_turnover_strength": 0.79,
                "prior_has_confirmed_leader": False,
                "prior_leader_event_coverage_available": True,
            },
        ]
    )

    assert frozen_early_turnover_mask(frame).tolist() == [True, False, False, False]


def test_frozen_capacity_factor_does_not_require_leader_state() -> None:
    frame = pd.DataFrame.from_records(
        [
            {"prior_turnover_strength": 0.80, "prior_has_confirmed_leader": False},
            {"prior_turnover_strength": 0.90, "prior_has_confirmed_leader": True},
            {"prior_turnover_strength": 0.79, "prior_has_confirmed_leader": False},
        ]
    )

    assert frozen_turnover_capacity_mask(frame).tolist() == [True, True, False]


def test_discovery_gate_requires_30_rows_and_three_covered_months() -> None:
    strong = {"closed_count": 30, "win_rate_pct": 70.0}
    holdout = {"closed_count": 10, "win_rate_pct": 70.0}

    assert _factor_status(strong, strong, holdout, 3) == "candidate_for_806d_validation"
    assert _factor_status({**strong, "closed_count": 29}, strong, holdout, 3) == "small_sample"
    assert _factor_status(strong, strong, holdout, 2) == "small_sample"


def test_validation_keeps_pre_discovery_and_seen_window_separate() -> None:
    frame = pd.DataFrame.from_records(
        [
            _validation_candidate(date(2024, 1, 2), 0.90, False, 2.0),
            _validation_candidate(date(2024, 1, 3), 0.70, False, -1.0),
            _validation_candidate(date(2026, 3, 2), 0.90, False, 3.0),
            _validation_candidate(date(2026, 3, 3), 0.90, True, -2.0),
        ]
    )

    result = evaluate_frozen_validation(frame)

    assert result["full_806"]["frozen"]["closed_count"] == 3
    assert result["independent_pre_discovery"]["frozen"]["closed_count"] == 1
    assert result["discovery_reference"]["frozen"]["closed_count"] == 2
    assert result["qualification"]["historical_proxy_gate_passed"] is False
    assert result["contract"]["turnover_threshold"] == 0.80


def test_forward_report_starts_empty_and_preserves_qualification_gate() -> None:
    report = render_frozen_forward_report(
        {"qualification": {"decision": "historical_proxy_rejected"}},
        discovery_digest=FROZEN_DISCOVERY_SHA256,
    )

    assert "not_started_waiting_for_unseen_sessions" in report
    assert "至少 `60` 个新交易日" in report
    assert "historical_proxy_rejected" in report


def _bundle() -> dict[str, pd.DataFrame]:
    roles = pd.DataFrame.from_records(
        [
            _role(D1, "CYCLE-1", "BK001", "600001.SSE", "Leader", 1, 1, ["ignition_candidate"], ["confirmed_ignition_leader"]),
            _role(D2, "CYCLE-1", "BK001", "600001.SSE", "Leader", 2, 1, ["capacity_core"], []),
            _role(D2, "CYCLE-1", "BK001", "600002.SSE", "Follower 2", 1, 2, ["leader_2"], []),
            _role(D2, "CYCLE-1", "BK001", "600003.SSE", "Follower 3", 1, 3, ["leader_3"], []),
            _role(D2, "CYCLE-X", "BK999", "600004.SSE", "Other", 1, 2, ["leader_2"], []),
        ]
    )
    event_ledger = pd.DataFrame.from_records(
        [
            {"trade_date": D1, "vt_symbol": "600001.SSE", "is_limit_up": True, "limit_up_streak": 1},
            {"trade_date": D2, "vt_symbol": "600001.SSE", "is_limit_up": True, "limit_up_streak": 2},
        ]
    )
    cycles = pd.DataFrame.from_records(
        [
            _cycle(D1, "CYCLE-1", "BK001", 0.70, 0.60, 0.50, 0.02, "ignition_candidate"),
            _cycle(D2, "CYCLE-1", "BK001", 0.80, 0.75, 0.70, 0.05, "confirmation"),
            _cycle(D2, "CYCLE-X", "BK999", 0.95, 0.95, 0.95, 0.20, "confirmation"),
        ]
    )
    return {
        "roles": roles,
        "event_ledger": event_ledger,
        "event_links": roles.loc[
            roles["trade_date"].eq(D1) & roles["vt_symbol"].eq("600001.SSE")
        ].assign(
            is_limit_up=True,
            turnover=100.0,
        ),
        "concept_cycles": cycles,
        "concept_panel": cycles.copy(),
    }


def _inputs() -> CapitalMainlineInputs:
    bars: list[dict[str, object]] = []
    closes = {
        "600001.SSE": [10.0, 11.0, 11.2, 11.1, 11.4, 11.5],
        "600002.SSE": [10.0, 10.0, 11.0, 11.5, 13.0, 13.5],
        "600003.SSE": [20.0, 20.0, 21.0, 20.5, 22.0, 22.5],
        "600004.SSE": [8.0, 8.0, 9.0, 9.2, 9.3, 9.5],
    }
    for symbol, values in closes.items():
        for trade_date, close_price in zip((D1, D2, D3, D4, D5, D6), values):
            bars.append(
                {
                    "trade_date": trade_date,
                    "vt_symbol": symbol,
                    "close_price": close_price,
                    "change_pct": 5.0 if trade_date == D2 and symbol != "600001.SSE" else 1.0,
                }
            )
    return CapitalMainlineInputs(
        trade_dates=(D1, D2, D3, D4, D5, D6),
        concept_bars=(),
        sector_fund_flows=(),
        stock_fund_flows=(),
        memberships=(),
        membership_scopes=(),
        membership_counts=(),
        current_memberships=(),
        stock_bars=tuple(bars),
        limit_up_events=(),
        sentiment_points=(),
        formal_candidate_days=(),
        coverage={},
        fingerprints={},
    )


def _role(
    trade_date: date,
    cycle_id: str,
    sector_id: str,
    symbol: str,
    name: str,
    streak: int,
    order: int,
    role_asof: list[str],
    role_realized: list[str],
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "market_cycle_id": "MARKET-1",
        "concept_cycle_id": cycle_id,
        "sector_id": sector_id,
        "sector_name": "Concept 1" if sector_id == "BK001" else "Other Concept",
        "vt_symbol": symbol,
        "name": name,
        "limit_up_streak": streak,
        "role_order": order,
        "role_asof": role_asof,
        "role_realized": role_realized,
        "membership_evidence_level": "point_in_time",
    }


def _cycle(
    trade_date: date,
    cycle_id: str,
    sector_id: str,
    index_strength: float,
    turnover_strength: float,
    ladder_strength: float,
    follower_ratio: float,
    phase: str,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "market_cycle_id": "MARKET-1",
        "concept_cycle_id": cycle_id,
        "sector_id": sector_id,
        "sector_name": "Concept 1" if sector_id == "BK001" else "Other Concept",
        "index_strength": index_strength,
        "turnover_strength": turnover_strength,
        "ladder_strength": ladder_strength,
        "unique_follower_ratio": follower_ratio,
        "concept_phase": phase,
        "capital_state": "turnover_proxy_only",
        "membership_evidence_level": "point_in_time",
    }


def _candidate(
    trade_date: date,
    prior_roles: list[str],
    return_pct: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "prior_trade_date": D2,
        "vt_symbol": "600002.SSE",
        "name": "Candidate",
        "lane": "first_board",
        "signal_time": "10:00:00",
        "pool_rank": 1,
        "return_pct": return_pct,
        "prior_sector_id": "BK001",
        "prior_sector_name": "Concept 1",
        "prior_concept_cycle_id": "CYCLE-1",
        "prior_roles_asof": prior_roles,
        "prior_turnover_strength": 0.9,
    }


def _validation_candidate(
    trade_date: date,
    turnover_strength: float,
    has_confirmed_leader: bool,
    return_pct: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "vt_symbol": "600001.SSE",
        "lane": "first_board",
        "signal_time": "10:00:00",
        "pool_rank": 1,
        "return_pct": return_pct,
        "prior_turnover_strength": turnover_strength,
        "prior_has_confirmed_leader": has_confirmed_leader,
        "prior_leader_event_coverage_available": True,
        "prior_leader_event_evidence_level": "daily_close_reconstructed_proxy",
    }
