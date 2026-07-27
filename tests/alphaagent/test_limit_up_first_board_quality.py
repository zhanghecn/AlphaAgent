from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

from alphaagent.server.services.limit_up import history_engine, live_service
from alphaagent.server.services.limit_up.first_board_quality import (
    build_preboard_pools,
    evaluate_first_board_quality_at_time,
    first_board_action_environment_gate,
)
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    apply_preboard_parity_contract,
    preboard_market_gate,
)
from alphaagent.server.services.limit_up.live_evidence import (
    attach_historical_evidence,
    resolve_candidate_historical_evidence,
)


DECISION_AT = datetime(2026, 7, 20, 10, 15)


def test_preboard_pools_audit_quality_before_three_percent_activation() -> None:
    below_floor = _candidate("600001.SSE", change_pct=2.9)
    failed_quality = _candidate(
        "600002.SSE",
        change_pct=8.0,
        financial_risk={"level": "blocked", "blocked": True, "reasons": ["loss"]},
    )
    activated = _candidate("600003.SSE", change_pct=3.0)
    near_limit = _candidate("600004.SSE", change_pct=9.8, last_price=10.98)
    touched = _candidate(
        "600005.SSE",
        change_pct=10.0,
        state="sealed",
        last_price=11.0,
    )

    pools = build_preboard_pools(
        [below_floor, failed_quality, activated, near_limit, touched],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    )

    assert pools.adapter_input_count == 5
    assert {row["vt_symbol"] for row in pools.capture_pool} == {
        "600001.SSE",
        "600003.SSE",
        "600004.SSE",
        "600005.SSE",
    }
    assert {row["vt_symbol"] for row in pools.eligible_first_board_pool} == {
        "600001.SSE",
        "600003.SSE",
        "600004.SSE",
        "600005.SSE",
    }
    assert [row["vt_symbol"] for row in pools.quality_pool] == [
        "600003.SSE",
        "600004.SSE",
    ]
    assert pools.rejection_counts == {
        "already_touched_or_failed": 1,
        "below_observation_floor": 1,
        "risk_gate": 1,
    }
    assert {
        row["vt_symbol"]: row["pool_stage"] for row in pools.candidate_audit
    } == {
        "600001.SSE": "eligible_below_observation_floor",
        "600002.SSE": "capture_rejected",
        "600003.SSE": "quality_pool",
        "600004.SSE": "quality_pool",
        "600005.SSE": "eligible_already_touched_or_failed",
    }
    assert next(
        row
        for row in pools.candidate_audit
        if row["vt_symbol"] == "600002.SSE"
    )["rejection_codes"] == ("risk_gate",)


def test_non_shared_environment_check_is_diagnostic_only() -> None:
    result = first_board_action_environment_gate(
        _candidate("600001.SSE"),
        market_gate={"passed": True},
        execution_checks=[
            {
                "code": "sector_route",
                "status": "failed",
                "blocking": True,
                "parity_status": "live_only",
            },
            {
                "code": "turnover_rate",
                "status": "passed",
                "blocking": True,
                "parity_status": "shared",
            },
        ],
    )

    assert result["execution_environment_passed"] is True
    assert result["failed_environment_checks"] == ()
    assert result["diagnostic_environment_checks"] == ("sector_route",)


def test_preboard_parity_keeps_unreplayable_environment_diagnostic() -> None:
    candidate = apply_preboard_parity_contract(
        _candidate(
            "600001.SSE",
            snapshot_fresh=False,
            quote_fresh=False,
            execution_checks=[
                {
                    "code": "sector_route",
                    "status": "failed",
                    "blocking": True,
                    "parity_status": "shared",
                },
                {
                    "code": "stock_flow",
                    "status": "pending",
                    "blocking": True,
                    "parity_status": "shared",
                },
            ],
        )
    )
    result = first_board_action_environment_gate(
        candidate,
        market_gate=preboard_market_gate({"passed": False}),
        execution_checks=candidate["execution_checks"],
    )

    assert all(
        check["parity_status"] == "diagnostic"
        for check in candidate["execution_checks"]
    )
    assert result["execution_environment_passed"] is True
    assert result["failed_environment_checks"] == ()
    assert set(result["diagnostic_environment_checks"]) == {
        "market_gate",
        "sector_route",
        "stock_flow",
        "snapshot_freshness",
        "quote_freshness",
    }


def test_live_adapter_membership_comes_only_from_trace_capture() -> None:
    captured = _candidate("600001.SSE", action="pass")
    trace_only = _candidate("600002.SSE", action="pass")
    lane_only = _candidate("600099.SSE", action="buy_now")
    evidence = _candidate(
        "600001.SSE",
        action="buy_now",
        portfolio_selected=True,
        historical_evidence={
            **_candidate("600001.SSE")["historical_evidence"],
            "average_return_pct": 3.5,
        },
    )
    snapshot = {
        "trace_capture_candidates": [captured, trace_only],
        "early_radar_recommendations": {
            "lanes": {"now": [evidence, lane_only], "tail": [], "next_auction": []}
        },
    }

    rows = live_service.live_preboard_adapter_rows(snapshot)

    assert [row["vt_symbol"] for row in rows] == ["600001.SSE", "600002.SSE"]
    assert rows[0]["historical_evidence"]["average_return_pct"] == 3.5
    assert "action" not in rows[0]
    assert "portfolio_selected" not in rows[0]


def test_live_adapter_reuses_same_frame_shared_and_core_quality(monkeypatch) -> None:
    raw = _candidate(
        "600001.SSE",
        prior_market_failed_rate=None,
        action="pass",
    )
    materialized = {
        **_candidate("600001.SSE", action="observe"),
        "preboard_decision_contract_version": "limit-up-preboard-decision-v1",
        "quality_evaluated_at": DECISION_AT.isoformat(),
        "quality_gate_passed": True,
        "core_quality_contract_version": "limit-up-core-abc-v1",
        "core_quality_gate_passed": False,
        "core_quality_gate_reason": "B_recognition_only_outside_entry_window",
        "base_ab_quality_gate_passed": True,
        "base_ab_quality_gate_reason": "qualified",
        "c_quality_gate_passed": False,
        "quality_priority_tier": "B_recognition_only",
        "lane_blockers": [],
    }
    rows = live_service.live_preboard_adapter_rows(
        {
            "trace_capture_candidates": [raw],
            "early_radar_recommendations": {
                "lanes": {"now": [materialized], "tail": [], "next_auction": []}
            },
        }
    )
    monkeypatch.setattr(
        "alphaagent.server.services.limit_up.first_board_quality.evaluate_first_board_quality_at_time",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("same-frame quality must not be recomputed from raw fields")
        ),
    )

    pools = build_preboard_pools(
        rows,
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    )

    assert [row["vt_symbol"] for row in pools.quality_pool] == ["600001.SSE"]
    assert pools.quality_pool[0]["core_quality_gate_passed"] is False
    assert pools.quality_pool[0]["core_quality_preparation_passed"] is True
    assert pools.quality_pool[0]["quality_priority_tier"] == "B_recognition_only"


def test_live_materialized_quality_still_requires_core_abc_preparation() -> None:
    rejected = {
        **_candidate("600001.SSE"),
        "preboard_decision_contract_version": "limit-up-preboard-decision-v1",
        "quality_evaluated_at": DECISION_AT.isoformat(),
        "quality_gate_passed": True,
        "core_quality_gate_passed": False,
        "core_quality_gate_reason": "prior_limit_count_126_above_6",
        "base_ab_quality_gate_passed": False,
        "base_ab_quality_gate_reason": "prior_limit_count_126_above_6",
        "c_quality_gate_passed": False,
    }

    pools = build_preboard_pools(
        [rejected],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    )

    assert pools.eligible_first_board_pool == ()
    assert pools.quality_pool == ()
    assert pools.rejection_counts == {"prior_limit_count_126_above_6": 1}
    assert pools.candidate_audit[0]["pool_stage"] == "core_quality_rejected"


def test_old_recommendation_action_does_not_change_live_adapter_rows() -> None:
    trace = _candidate("600001.SSE", action="buy_now", portfolio_selected=True)
    base = {
        "trace_capture_candidates": [trace],
        "early_radar_recommendations": {
            "lanes": {"now": [_candidate("600001.SSE", action="observe")]}
        },
    }
    changed = deepcopy(base)
    changed["early_radar_recommendations"]["lanes"]["now"][0]["action"] = (
        "buy_now"
    )
    changed["early_radar_recommendations"]["lanes"]["now"][0][
        "portfolio_selected"
    ] = True

    assert live_service.live_preboard_adapter_rows(base) == (
        live_service.live_preboard_adapter_rows(changed)
    )


def test_live_adapter_reprojects_materialized_environment_checks() -> None:
    candidate = _candidate(
        "600001.SSE",
        change_pct=8.9,
        execution_checks=[
            {
                "code": "stock_momentum",
                "status": "pending",
                "blocking": True,
                "parity_status": "shared",
            },
            {
                "code": "sector_route",
                "status": "pending",
                "blocking": True,
                "parity_status": "shared",
            },
            {
                "code": "stock_flow",
                "status": "pending",
                "blocking": True,
                "parity_status": "shared",
            },
        ],
    )
    rows = live_service.live_preboard_adapter_rows(
        {
            "trace_capture_candidates": [candidate],
            "early_radar_recommendations": {"lanes": {}},
        }
    )

    pools = build_preboard_pools(
        rows,
        decision_at=DECISION_AT,
        market_gate=preboard_market_gate({"passed": False}),
    )

    assert len(pools.quality_pool) == 1
    row = pools.quality_pool[0]
    assert row["execution_environment_passed"] is True
    assert row["failed_environment_checks"] == ()
    assert set(row["diagnostic_environment_checks"]) == {
        "market_gate",
        "sector_route",
        "stock_flow",
    }


def test_quality_pool_excludes_plain_three_percent_failed_and_touched_stocks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        history_engine,
        "_board_lane_candidates_from_day",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("future event universe must not be read")
        ),
    )
    qualified = _candidate("600003.SSE", change_pct=6.0, action="observe")
    plain_three = _candidate(
        "600001.SSE",
        change_pct=3.0,
        historical_evidence={},
    )
    failed_eight = _candidate(
        "600002.SSE",
        change_pct=8.0,
        financial_risk={"level": "blocked", "blocked": True, "reasons": ["loss"]},
    )
    touched = _candidate(
        "600004.SSE",
        change_pct=10.0,
        state="sealed",
        last_price=11.0,
    )

    pool = build_preboard_pools(
        [plain_three, failed_eight, qualified, touched],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    ).quality_pool

    assert [row["vt_symbol"] for row in pool] == ["600003.SSE"]
    assert pool[0]["quality_gate_passed"] is True


def test_preboard_pool_defers_only_intraday_route_blockers() -> None:
    candidate = _candidate(
        "600003.SSE",
        change_pct=8.9,
        last_price=10.89,
        path_prefix={},
        prior_industry_heat_score=None,
    )

    pools = build_preboard_pools(
        [candidate],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    )

    assert len(pools.capture_pool) == 1
    assert len(pools.eligible_first_board_pool) == 1
    assert len(pools.quality_pool) == 1
    row = pools.quality_pool[0]
    assert row["lane_decision"] == "blocked"
    assert row["preboard_hard_blockers"] == ()
    assert set(row["preboard_deferred_blockers"]) == {
        "industry_heat_unavailable",
        "intraday_support_unavailable",
    }


def test_preboard_pool_rejects_fixed_formal_lane_blockers() -> None:
    candidate = _candidate(
        "600003.SSE",
        change_pct=8.9,
        last_price=10.89,
        financial_snapshot=None,
        prior_market_failed_rate=0.10,
    )

    pools = build_preboard_pools(
        [candidate],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    )

    assert len(pools.capture_pool) == 1
    assert pools.eligible_first_board_pool == ()
    assert pools.quality_pool == ()
    rejected = pools.candidate_audit[0]
    assert rejected["pool_stage"] == "quality_rejected"
    assert set(rejected["preboard_hard_blockers"]) == {
        "financial_report_unavailable",
        "first_board_repair_setup_missing",
    }


def test_preboard_pool_keeps_static_lane_failures_blocking() -> None:
    low_quality = _candidate(
        "600003.SSE",
        change_pct=8.9,
        prior_position_120=0.90,
        pullback_from_prior_limit_pct=-2.0,
        trade_days_since_prior_limit=2,
    )
    too_little_touch_history = _candidate(
        "600004.SSE",
        change_pct=8.9,
        prior_touch_count_126=2,
    )

    pools = build_preboard_pools(
        [low_quality, too_little_touch_history],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    )

    assert len(pools.capture_pool) == 2
    assert pools.eligible_first_board_pool == ()
    assert pools.quality_pool == ()
    assert pools.rejection_counts == {
        "first_board_touch_gene_weak": 1,
        "low_position_missing": 1,
    }


def test_future_labels_cannot_change_point_in_time_quality() -> None:
    candidate = _candidate("600001.SSE", change_pct=6.0)
    baseline = evaluate_first_board_quality_at_time(
        candidate,
        decision_at=DECISION_AT,
        market_gate={"passed": True},
        execution_checks=candidate["execution_checks"],
    )
    changed = {
        **candidate,
        "physical_touch_at": "2026-07-20T10:17:00",
        "first_limit_time": "10:17:00",
        "final_sealed": False,
        "d1_net_return_pct": -9.0,
    }
    after = evaluate_first_board_quality_at_time(
        changed,
        decision_at=DECISION_AT,
        market_gate={"passed": True},
        execution_checks=changed["execution_checks"],
    )

    keys = (
        "quality_gate_passed",
        "lane_blockers",
        "lane_support_score",
        "lane_entry_quality_score",
        "profitability_gate_passed",
        "preparation_environment_passed",
        "execution_environment_passed",
    )
    assert {key: baseline[key] for key in keys} == {
        key: after[key] for key in keys
    }


def test_environment_replaces_only_old_stock_momentum_check() -> None:
    momentum_only = first_board_action_environment_gate(
        _candidate("600001.SSE"),
        market_gate={"passed": True},
        execution_checks=[
            {"code": "stock_momentum", "status": "pending", "blocking": True},
            {"code": "sector_route", "status": "passed", "blocking": True},
        ],
    )
    sector_failed = first_board_action_environment_gate(
        _candidate("600001.SSE"),
        market_gate={"passed": True},
        execution_checks=[
            {"code": "stock_momentum", "status": "passed", "blocking": True},
            {"code": "sector_route", "status": "failed", "blocking": True},
        ],
    )

    assert momentum_only["execution_environment_passed"] is True
    assert momentum_only["failed_environment_checks"] == ()
    assert sector_failed["execution_environment_passed"] is False
    assert sector_failed["failed_environment_checks"] == ("sector_route",)


def test_prepare_environment_can_pass_before_formal_entry_window() -> None:
    result = first_board_action_environment_gate(
        _candidate("600001.SSE", entry_window_passed=False),
        market_gate={"passed": True},
        execution_checks=[
            {"code": "stock_momentum", "status": "pending", "blocking": True},
            {"code": "sector_route", "status": "passed", "blocking": True},
        ],
    )

    assert result["preparation_environment_passed"] is True
    assert result["execution_environment_passed"] is False
    assert result["failed_environment_checks"] == ("entry_window",)


def test_direct_historical_evidence_matches_snapshot_attachment() -> None:
    signal = {
        "vt_symbol": "600001.SSE",
        "board_level": 1,
        "entry_kind": "momentum",
        "action": "observe",
    }
    candidate = _candidate("600001.SSE")
    analog_index = {
        ("sweep", 1, "repair", "1-3", "0.8-2.0", "0-3"): {
            "sample_count": 80,
        }
    }
    stock_index = {
        "600001.SSE": {
            "sample_count": 7,
            "win_count": 5,
            "win_rate": 71.4286,
            "average_return_pct": 2.1,
        }
    }
    market_context = {"sentiment": {"phase": "repair"}}
    direct = resolve_candidate_historical_evidence(
        signal,
        candidate,
        market_context,
        "now",
        date(2026, 7, 20),
        analog_index,
        stock_index,
    )
    snapshot = attach_historical_evidence(
        {
            "trade_date": "2026-07-20",
            "market_context": market_context,
            "candidates": [candidate],
            "recommendations": {
                "lanes": {"now": [signal], "tail": [], "next_auction": []}
            },
        },
        analog_index=analog_index,
        stock_d1_index=stock_index,
    )
    attached = snapshot["recommendations"]["lanes"]["now"][0]

    assert attached["historical_evidence"] == direct


def test_history_and_live_adapters_produce_identical_shared_quality(
    monkeypatch,
) -> None:
    candidate = _candidate(
        "600001.SSE",
        quote_observed_at=DECISION_AT.isoformat(),
    )
    historical = build_preboard_pools(
        [candidate],
        decision_at=DECISION_AT,
        market_gate={"passed": True},
    ).quality_pool[0]
    monkeypatch.setattr(
        live_service,
        "_live_research_candidate",
        lambda row, *_args, **_kwargs: dict(row),
    )
    monkeypatch.setattr(
        live_service,
        "build_first_board_execution_checks_at_time",
        lambda _row: list(candidate["execution_checks"]),
    )
    snapshot = {
        "captured_at": DECISION_AT.isoformat(),
        "market_context": {"sentiment": {}},
        "data_quality": {"is_stale": False, "snapshot_age_seconds": 0},
        "candidates": [candidate],
        "recommendations": {
            "market_gate": {"passed": True},
            "lanes": {
                "now": [candidate],
                "tail": [],
                "next_auction": [],
            },
        },
    }

    live = live_service._attach_shared_first_board_quality(snapshot)[
        "recommendations"
    ]["lanes"]["now"][0]

    keys = (
        "universe_gate_passed",
        "quality_gate_passed",
        "preparation_environment_passed",
        "execution_environment_passed",
        "failed_environment_checks",
        "lane_decision",
        "lane_blockers",
        "lane_support_score",
        "lane_entry_quality_score",
        "lane_rank_score",
        "profitability_gate_passed",
        "profitability_gate_reason",
        "historical_prior_status",
        "expected_d1_net_return_pct",
        "d1_win_probability",
        "seal_probability_given_touch",
        "d1_win_probability_given_seal",
    )
    assert {key: live[key] for key in keys} == {
        key: historical[key] for key in keys
    }


def _candidate(symbol: str, **overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "vt_symbol": symbol,
        "name": "主板样本",
        "board_level": 1,
        "board_lane": "first_board",
        "previous_limit_up": False,
        "prior_streak": 0,
        "target_board": 1,
        "state": "near_limit",
        "change_pct": 6.0,
        "last_price": 10.6,
        "limit_price": 11.0,
        "action": "observe",
        "entry_window_passed": True,
        "snapshot_fresh": True,
        "quote_fresh": True,
        "risk_gate_passed": True,
        "signal_kind": "intraday",
        "prior_limit_count_126": 3,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "prior_limit_count_5": 0,
        "trade_days_since_prior_limit": 18,
        "pullback_from_prior_limit_pct": -12.0,
        "prior_position_120": 0.28,
        "auction_gap_pct": 3.2,
        "prior_turnover_rate": 9.0,
        "prior_amount_ratio_5d": 1.6,
        "prior_amplitude_pct": 7.0,
        "prior_low_change_pct": -2.0,
        "prior_industry_heat_score": 72.0,
        "prior_industry_heat_rank": 2,
        "prior_industry_count": 30,
        "prior_industry_leader_rank": 1,
        "prior_market_phase": "repair",
        "prior_market_failed_rate": 0.40,
        "prior_market_one_to_two_rate": 0.30,
        "prior_market_two_to_three_rate": 0.25,
        "financial_risk": {"level": "clear", "blocked": False, "reasons": []},
        "financial_snapshot": {
            "publish_date": "2026-06-30",
            "period_type": "quarterly",
            "net_profit_yoy": 18.0,
        },
        "path_prefix": {
            "point_count": 15,
            "last_pct": 6.0,
            "touch_count": 0,
            "break_count": 0,
            "reseal_count": 0,
            "minimum_pct": 0.0,
            "approach_3point_pct": 3.0,
            "recent_15m_min_pct": 3.0,
            "recent_15m_change_pct": 3.0,
            "recent_15m_range_pct": 3.0,
            "recent_15m_drawdown_pct": 0.0,
            "recent_30m_min_pct": 1.8,
            "recent_30m_change_pct": 4.0,
        },
        "historical_evidence": {
            "status": "ready",
            "as_of_date": "2026-07-20",
            "effective_sample_count": 80,
            "average_return_pct": 2.0,
            "smoothed_win_rate": 68.0,
            "stock_gene_touch_count": 8,
            "stock_gene_seal_count": 6,
            "seal_success_rate": 75.0,
            "d1_money_effect_sample_count": 7,
            "d1_money_effect_win_rate": 64.0,
            "d1_money_effect_average_return_pct": 2.1,
            "historical_win_rate": 48.0,
        },
        "execution_checks": [
            {"code": "stock_momentum", "status": "pending", "blocking": True},
            {"code": "sector_route", "status": "passed", "blocking": True},
            {"code": "stock_flow", "status": "passed", "blocking": True},
            {"code": "turnover_rate", "status": "passed", "blocking": True},
        ],
    }
    candidate.update(deepcopy(overrides))
    return candidate
