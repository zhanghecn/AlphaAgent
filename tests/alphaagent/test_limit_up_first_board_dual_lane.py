from __future__ import annotations

from copy import deepcopy

import pytest

from alphaagent.server.services.limit_up.first_board_dual_lane import (
    collect_rotation_forward_evidence,
    evaluate_rotation_shadow,
)


def _candidate() -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "name": "轮动龙头",
        "board_lane": "first_board",
        "board_level": 1,
        "state": "near_limit",
        "distance_to_limit_pct": 0.6,
        "limit_price": 11.0,
        "seen_before_seal": True,
        "missed_preseal_entry": False,
        "warmup_group": "CWG-ROTATION",
        "warmup_group_name": "创新药",
        "warmup_trend_state": "ROTATION",
        "warmup_flow_trade_date": "2026-07-13",
        "warmup_main_net_inflow": 800_000_000.0,
        "warmup_main_net_inflow_ratio": 3.2,
        "warmup_leader_rank": 1,
        "warmup_touch_count": 2,
        "market_dragon_rank": 2,
        "action": "observe",
        "portfolio_selected": False,
    }


def _snapshot(
    candidate: dict[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
    result = {
        "trade_date": "2026-07-13",
        "captured_at": "2026-07-13T10:15:00+08:00",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "data_quality": {"is_stale": False},
        "candidates": [candidate or _candidate()],
    }
    result.update(overrides)
    return result


def test_rotation_shadow_triggers_only_for_same_day_concept_leader_before_seal():
    candidate = _candidate()
    original_action = candidate["action"]
    original_rank = candidate["market_dragon_rank"]
    original_portfolio_state = candidate["portfolio_selected"]

    result = evaluate_rotation_shadow(_snapshot(candidate), candidate)

    assert result["rotation_shadow_state"] == "trigger"
    assert result["rotation_shadow_passed"] is True
    assert result["rotation_shadow_entry_price"] == 11.0
    assert result["rotation_shadow_execution_effect"] == "none_research_only"
    assert candidate["action"] == original_action
    assert candidate["market_dragon_rank"] == original_rank
    assert candidate["portfolio_selected"] == original_portfolio_state


@pytest.mark.parametrize(
    ("snapshot_change", "candidate_change", "reason"),
    [
        ({"mode": "stale_snapshot"}, {}, "snapshot_not_live"),
        ({"data_quality": {"is_stale": True}}, {}, "snapshot_stale"),
        ({"session_stage": "closed"}, {}, "session_not_active"),
        ({"captured_at": "2026-07-11T10:15:00+08:00", "trade_date": "2026-07-11"}, {}, "not_trade_weekday"),
        ({}, {"warmup_flow_trade_date": "2026-07-10"}, "concept_flow_date_mismatch"),
        ({}, {"warmup_main_net_inflow": -1.0}, "concept_flow_not_positive"),
        ({}, {"warmup_leader_rank": 3}, "not_dynamic_top2"),
        ({}, {"warmup_touch_count": 1}, "concept_diffusion_insufficient"),
        ({}, {"vt_symbol": "300001.SZSE"}, "not_main_board_first_board"),
    ],
)
def test_rotation_shadow_fails_closed_when_point_in_time_evidence_is_invalid(
    snapshot_change: dict[str, object],
    candidate_change: dict[str, object],
    reason: str,
):
    candidate = {**_candidate(), **candidate_change}
    snapshot = _snapshot(candidate, **snapshot_change)

    result = evaluate_rotation_shadow(snapshot, candidate)

    assert result["rotation_shadow_passed"] is False
    assert reason in result["rotation_shadow_reason_codes"]


def test_rotation_shadow_separates_early_watch_from_missed_sealed_board():
    watch_candidate = {**_candidate(), "distance_to_limit_pct": 1.8}
    missed_candidate = {
        **_candidate(),
        "state": "sealed",
        "seen_before_seal": False,
        "missed_preseal_entry": True,
    }

    watch = evaluate_rotation_shadow(_snapshot(watch_candidate), watch_candidate)
    missed = evaluate_rotation_shadow(_snapshot(missed_candidate), missed_candidate)

    assert watch["rotation_shadow_state"] == "watch"
    assert watch["rotation_shadow_passed"] is False
    assert missed["rotation_shadow_state"] == "missed"
    assert missed["rotation_shadow_passed"] is False
    assert "first_seen_after_seal" in missed["rotation_shadow_reason_codes"]


def test_rotation_forward_uses_first_real_trigger_and_never_historical_proxy():
    first = _snapshot()
    later_candidate = {**_candidate(), "distance_to_limit_pct": 0.2}
    later = _snapshot(
        later_candidate,
        captured_at="2026-07-13T10:16:00+08:00",
    )
    historical = {
        **deepcopy(first),
        "mode": "daily_point_in_time",
        "captured_at": "2025-01-02T10:15:00+08:00",
        "trade_date": "2025-01-02",
    }

    evidence = collect_rotation_forward_evidence(
        [historical, later, first],
        forward_start="2026-07-13",
    )

    assert evidence["historical_substitution"] is False
    assert evidence["snapshot_day_count"] == 1
    assert evidence["trigger_count"] == 1
    assert evidence["trigger_signals"][0]["signal_time"] == "10:15:00"
    assert evidence["trigger_signals"][0]["entry_price"] == 11.0
