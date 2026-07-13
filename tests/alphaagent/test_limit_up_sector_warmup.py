from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import history_service, live_repository
from alphaagent.server.services.limit_up.live_service import build_live_snapshot
from alphaagent.server.services.limit_up.sector_warmup import (
    attach_dynamic_group_leader_ranks,
    group_concepts,
    historical_warmup_proxy,
    historical_warmup_quality_gate,
    live_warmup_observation,
)
from alphaagent.server.services.limit_up.sector_warmup_research import (
    build_sector_warmup_research_report,
)


def _memberships(
    sector_id: str,
    sector_name: str,
    symbols: list[str],
    *,
    sector_type: str = "concept",
) -> list[dict[str, object]]:
    return [
        {
            "sector_id": sector_id,
            "sector_name": sector_name,
            "sector_type": sector_type,
            "vt_symbol": symbol,
        }
        for symbol in symbols
    ]


def test_group_concepts_is_deterministic_and_counts_overlapping_members_once():
    rows = [
        *_memberships("BK001", "光模块", [f"00000{i}.SZSE" for i in range(1, 7)]),
        *_memberships(
            "BK002",
            "CPO",
            [
                "000001.SZSE",
                "000002.SZSE",
                "000003.SZSE",
                "000004.SZSE",
                "000005.SZSE",
                "000007.SZSE",
            ],
        ),
        *_memberships("BK003", "医药商业", [f"60000{i}.SSE" for i in range(1, 7)]),
        *_memberships("BK004", "昨日涨停", [f"60100{i}.SSE" for i in range(1, 7)]),
    ]

    groups = group_concepts(rows)
    reversed_groups = group_concepts(list(reversed(rows)))

    assert groups == reversed_groups
    assert len(groups) == 2
    optical = next(
        group for group in groups if group["sector_ids"] == ["BK001", "BK002"]
    )
    assert optical["member_count"] == 7
    assert len(optical["member_symbols"]) == 7
    assert all("昨日涨停" not in group["sector_names"] for group in groups)


def test_historical_warmup_proxy_requires_all_point_in_time_components():
    confirmed = historical_warmup_proxy(
        {
            "known_at_signal": {
                "prior_industry_change_pct": 1.2,
                "prior_industry_advancing_rate": 0.64,
                "prior_industry_turnover_ratio_5d": 1.3,
            }
        }
    )
    missing = historical_warmup_proxy(
        {
            "prior_industry_change_pct": 1.2,
            "prior_industry_advancing_rate": 0.64,
        }
    )

    assert confirmed["available"] is True
    assert confirmed["confirmed"] is True
    assert confirmed["state"] in {"warming", "launch"}
    assert confirmed["execution_effect"] == "none_research_only"
    assert missing == {
        "available": False,
        "confirmed": False,
        "state": "unavailable",
        "score": None,
        "execution_effect": "none_research_only",
        "components": {
            "change_pct": 1.2,
            "advancing_rate": 0.64,
            "turnover_ratio_5d": None,
        },
    }


def test_historical_warmup_quality_gate_requires_expansion_without_crowding():
    qualified = historical_warmup_quality_gate(
        {
            "known_at_signal": {
                "prior_industry_change_pct": 0.8,
                "prior_industry_advancing_rate": 0.60,
                "prior_industry_turnover_ratio_5d": 1.10,
                "prior_industry_sealed_count": 2,
            }
        }
    )
    no_expansion = historical_warmup_quality_gate(
        {
            "prior_industry_change_pct": 0.8,
            "prior_industry_advancing_rate": 0.60,
            "prior_industry_turnover_ratio_5d": 1.10,
            "prior_industry_sealed_count": 0,
        }
    )
    crowded = historical_warmup_quality_gate(
        {
            "prior_industry_change_pct": 2.8,
            "prior_industry_advancing_rate": 0.90,
            "prior_industry_turnover_ratio_5d": 1.50,
            "prior_industry_sealed_count": 3,
        }
    )
    missing_expansion = historical_warmup_quality_gate(
        {
            "prior_industry_change_pct": 0.8,
            "prior_industry_advancing_rate": 0.60,
            "prior_industry_turnover_ratio_5d": 1.10,
        }
    )

    assert qualified["passed"] is True
    assert qualified["state"] == "qualified"
    assert qualified["hypothesis_status"] == "post_holdout_hypothesis"
    assert qualified["execution_effect"] == "none_research_only"
    assert qualified["rejection_reasons"] == []
    assert no_expansion["rejection_reasons"] == [
        "prior_industry_no_sealed_expansion"
    ]
    assert crowded["rejection_reasons"] == ["warmup_score_crowded"]
    assert missing_expansion["available"] is False
    assert missing_expansion["rejection_reasons"] == [
        "prior_industry_sealed_count_missing"
    ]


def test_live_warmup_observation_prefers_strongest_usable_concept():
    observation = live_warmup_observation(
        [
            {
                "sector_id": "BK001",
                "sector_name": "光模块",
                "group_id": "CWG-OPTICAL",
                "group_name": "光模块 / CPO",
                "heat_score": 72.0,
                "trend_state": "hot",
                "main_net_inflow": 2_400_000_000,
                "main_net_inflow_ratio": 4.2,
            },
            {
                "sector_id": "BK003",
                "sector_name": "通信设备",
                "group_id": "CWG-COMMS",
                "group_name": "通信设备",
                "heat_score": 48.0,
                "trend_state": "watch",
                "main_net_inflow": -300_000_000,
                "main_net_inflow_ratio": -0.8,
            },
        ]
    )

    assert observation["available"] is True
    assert observation["group_id"] == "CWG-OPTICAL"
    assert observation["group_name"] == "光模块 / CPO"
    assert observation["state"] == "launch"
    assert observation["score"] > 70
    assert observation["confidence"] == "point_in_time_proxy"


def test_dynamic_leader_rank_only_adds_shadow_fields_to_first_board():
    candidates = [
        {
            "vt_symbol": "000001.SZSE",
            "board_lane": "first_board",
            "warmup_group": "CWG-1",
            "change_pct": 9.8,
            "state": "near_limit",
            "stock_main_net_inflow_ratio": 3.0,
            "prior_touch_count_126": 8,
        },
        {
            "vt_symbol": "000002.SZSE",
            "board_lane": "first_board",
            "warmup_group": "CWG-1",
            "change_pct": 9.5,
            "state": "near_limit",
            "stock_main_net_inflow_ratio": 1.0,
            "prior_touch_count_126": 3,
        },
        {
            "vt_symbol": "000003.SZSE",
            "board_lane": "two_to_three",
            "rank_score": 88.0,
            "decision": "eligible",
        },
    ]
    original_relay = deepcopy(candidates[2])

    ranked = attach_dynamic_group_leader_ranks(candidates)

    assert ranked[0]["warmup_leader_rank"] == 1
    assert ranked[1]["warmup_leader_rank"] == 2
    assert ranked[0]["warmup_touch_count"] == 0
    assert ranked[1]["warmup_touch_count"] == 0
    assert ranked[0]["warmup_execution_effect"] == "none_research_only"
    assert ranked[2] == original_relay
    assert candidates[0].get("warmup_leader_rank") is None


def _research_candidate(
    symbol: str,
    *,
    rank_score: float,
    gross_return_pct: float,
    confirmed: bool,
    leader_rank: int,
    sealed: bool = True,
    industry_sealed_count: int | None = None,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": "first_board",
        "decision": "eligible",
        "rank_score": rank_score,
        "prior_industry_change_pct": 1.2 if confirmed else -0.2,
        "prior_industry_advancing_rate": 0.64 if confirmed else 0.42,
        "prior_industry_turnover_ratio_5d": 1.3 if confirmed else 0.8,
        "prior_industry_sealed_count": industry_sealed_count,
        "prior_industry_leader_rank": leader_rank,
        "outcome": {
            "sealed": sealed,
            "next_open_return_pct": gross_return_pct - 0.31,
        },
    }


def test_research_report_consumes_ledger_net_return_without_deducting_cost_twice():
    candidate = _research_candidate(
        "000001.SZSE",
        rank_score=90,
        gross_return_pct=1.31,
        confirmed=True,
        leader_rank=1,
    )
    candidate["outcome"]["next_open_return_pct"] = 1.0

    report = build_sector_warmup_research_report(
        [
            {
                "trade_date": "2026-01-05",
                "validation_phase": "expanding_oos",
                "board_candidate_pool": {"first_board": [candidate]},
            }
        ]
    )

    assert report["comparisons"][0]["average_net_return_pct"] == 1.0
    assert report["selected_trades"]["baseline"][0]["net_return_pct"] == 1.0


def test_research_report_adds_post_holdout_quality_gate_and_trade_diagnostics():
    quality = _research_candidate(
        "600001.SSE",
        rank_score=90,
        gross_return_pct=2.31,
        confirmed=True,
        leader_rank=2,
        industry_sealed_count=2,
    )
    no_expansion_loss = _research_candidate(
        "600002.SSE",
        rank_score=90,
        gross_return_pct=-4.69,
        confirmed=True,
        leader_rank=12,
        sealed=False,
        industry_sealed_count=0,
    )
    no_expansion_loss["prior_amount_ratio_5d"] = 0.8
    crowded_loss = _research_candidate(
        "600003.SSE",
        rank_score=90,
        gross_return_pct=-2.69,
        confirmed=True,
        leader_rank=1,
        industry_sealed_count=3,
    )
    crowded_loss.update(
        {
            "prior_industry_change_pct": 2.8,
            "prior_industry_advancing_rate": 0.90,
            "prior_industry_turnover_ratio_5d": 1.50,
        }
    )
    missed_winner = _research_candidate(
        "600004.SSE",
        rank_score=90,
        gross_return_pct=5.31,
        confirmed=False,
        leader_rank=3,
        industry_sealed_count=0,
    )
    missed_loser = _research_candidate(
        "600005.SSE",
        rank_score=90,
        gross_return_pct=-1.69,
        confirmed=False,
        leader_rank=4,
        industry_sealed_count=0,
    )
    rows = [
        {
            "trade_date": "2026-01-05",
            "validation_phase": "expanding_oos",
            "board_candidate_pool": {"first_board": [quality]},
        },
        {
            "trade_date": "2026-01-06",
            "validation_phase": "locked_holdout",
            "board_candidate_pool": {"first_board": [no_expansion_loss]},
        },
        {
            "trade_date": "2026-01-07",
            "validation_phase": "locked_holdout",
            "board_candidate_pool": {"first_board": [crowded_loss]},
        },
        {
            "trade_date": "2026-01-08",
            "validation_phase": "locked_holdout",
            "board_candidate_pool": {"first_board": [missed_winner]},
        },
        {
            "trade_date": "2026-01-09",
            "validation_phase": "locked_holdout",
            "board_candidate_pool": {"first_board": [missed_loser]},
        },
    ]

    report = build_sector_warmup_research_report(rows)
    comparisons = {item["variant"]: item for item in report["comparisons"]}
    losses = report["diagnostics"]["locked_holdout_losses"]
    missed = report["diagnostics"]["locked_holdout_missed_winners"]

    assert comparisons["warmup_quality_gate"]["trade_count"] == 1
    assert comparisons["warmup_quality_gate"]["average_net_return_pct"] == 2.0
    assert comparisons["warmup_quality_gate"]["formal"] is False
    assert comparisons["warmup_quality_gate"]["hypothesis_status"] == (
        "post_holdout_hypothesis"
    )
    assert report["quality_gate_validation"]["passed"] is False
    assert report["quality_gate_validation"]["promotion_eligible"] is False
    assert report["quality_gate_validation"]["evaluated_variant"] == (
        "warmup_quality_gate"
    )
    assert report["simulation_eligible"] is False
    assert [row["vt_symbol"] for row in losses] == ["600002.SSE", "600003.SSE"]
    assert losses[0]["warmup_quality_passed"] is False
    assert "prior_industry_no_sealed_expansion" in losses[0]["reason_codes"]
    assert "entry_day_failed_to_seal" in losses[0]["reason_codes"]
    assert "warmup_score_crowded" in losses[1]["reason_codes"]
    assert [row["vt_symbol"] for row in missed] == ["600004.SSE"]
    assert missed[0]["reason_codes"] == ["warmup_not_confirmed"]


def test_quality_gate_never_backfills_after_rejecting_original_gate_top1():
    crowded_top1 = _research_candidate(
        "600001.SSE",
        rank_score=90,
        gross_return_pct=-2.69,
        confirmed=True,
        leader_rank=1,
        industry_sealed_count=3,
    )
    crowded_top1.update(
        {
            "prior_industry_change_pct": 2.8,
            "prior_industry_advancing_rate": 0.90,
            "prior_industry_turnover_ratio_5d": 1.50,
        }
    )
    lower_ranked_quality = _research_candidate(
        "600002.SSE",
        rank_score=80,
        gross_return_pct=5.31,
        confirmed=True,
        leader_rank=2,
        industry_sealed_count=2,
    )

    report = build_sector_warmup_research_report(
        [
            {
                "trade_date": "2026-01-05",
                "validation_phase": "expanding_oos",
                "board_candidate_pool": {
                    "first_board": [crowded_top1, lower_ranked_quality]
                },
            }
        ]
    )
    comparisons = {item["variant"]: item for item in report["comparisons"]}

    assert report["selected_trades"]["warmup_gate"][0]["vt_symbol"] == "600001.SSE"
    assert comparisons["warmup_quality_gate"]["trade_count"] == 0
    assert report["selected_trades"]["warmup_quality_gate"] == []


def test_quality_gate_formal_data_only_requires_post_freeze_point_in_time_coverage():
    historical = _research_candidate(
        "600001.SSE",
        rank_score=90,
        gross_return_pct=1.31,
        confirmed=True,
        leader_rank=1,
        industry_sealed_count=2,
    )
    rows = [
        {
            "trade_date": "2025-06-27",
            "validation_phase": "expanding_oos",
            "board_candidate_pool": {"first_board": [historical]},
        }
    ]
    for offset in range(30):
        candidate = _research_candidate(
            f"601{offset:03d}.SSE",
            rank_score=90,
            gross_return_pct=1.31,
            confirmed=True,
            leader_rank=1,
            industry_sealed_count=2,
        )
        rows.append(
            {
                "trade_date": date.fromordinal(
                    date(2026, 7, 13).toordinal() + offset
                ).isoformat(),
                "validation_phase": "locked_holdout",
                "board_candidate_pool": {"first_board": [candidate]},
            }
        )

    report = build_sector_warmup_research_report(
        rows,
        data_coverage={
            "membership_snapshot_days": 500,
            "membership_snapshot_start": "2026-07-13",
            "membership_snapshot_end": "2028-12-31",
            "concept_daily_bar_days": 500,
            "concept_daily_bar_start": "2025-01-01",
            "concept_daily_bar_end": "2028-12-31",
            "intraday_fund_snapshot_days": 60,
            "intraday_fund_snapshot_start": "2026-07-13",
            "intraday_fund_snapshot_end": "2028-12-31",
            "signal_time_feature_linkage_ready": True,
        },
    )
    checks = {
        check["code"]: check["passed"]
        for check in report["quality_gate_validation"]["checks"]
    }

    assert report["formal_concept_backtest_ready"] is False
    assert checks["formal_data"] is True
    assert checks["post_freeze_forward_count"] is True
    assert report["quality_gate_validation"]["passed"] is True
    assert report["quality_gate_validation"]["promotion_eligible"] is False
    assert report["simulation_eligible"] is False


def test_research_report_keeps_baseline_rank_gate_and_leader_proxy_distinct():
    rows = [
        {
            "trade_date": "2026-01-05",
            "validation_phase": "expanding_oos",
            "board_candidate_pool": {
                "first_board": [
                    _research_candidate(
                        "000001.SZSE",
                        rank_score=90,
                        gross_return_pct=-0.69,
                        confirmed=False,
                        leader_rank=1,
                    ),
                    _research_candidate(
                        "000002.SZSE",
                        rank_score=80,
                        gross_return_pct=2.31,
                        confirmed=True,
                        leader_rank=5,
                    ),
                ],
                "two_to_three": [
                    {
                        "vt_symbol": "000099.SZSE",
                        "decision": "eligible",
                        "rank_score": 99,
                    }
                ],
            },
        },
        {
            "trade_date": "2026-01-06",
            "validation_phase": "locked_holdout",
            "board_candidate_pool": {
                "first_board": [
                    _research_candidate(
                        "000003.SZSE",
                        rank_score=90,
                        gross_return_pct=-0.69,
                        confirmed=True,
                        leader_rank=1,
                    ),
                    _research_candidate(
                        "000004.SZSE",
                        rank_score=80,
                        gross_return_pct=1.31,
                        confirmed=False,
                        leader_rank=3,
                    ),
                ]
            },
        },
        {
            "trade_date": "2026-01-07",
            "validation_phase": "locked_holdout",
            "board_candidate_pool": {
                "first_board": [
                    _research_candidate(
                        "000005.SZSE",
                        rank_score=90,
                        gross_return_pct=2.31,
                        confirmed=False,
                        leader_rank=2,
                    )
                ]
            },
        },
    ]
    original = deepcopy(rows)

    report = build_sector_warmup_research_report(
        rows,
        data_coverage={
            "membership_snapshot_days": 0,
            "intraday_fund_snapshot_days": 1,
        },
    )
    comparisons = {item["variant"]: item for item in report["comparisons"]}

    assert rows == original
    assert report["status"] == "ready"
    assert report["research_status"] == "proxy_only"
    assert report["simulation_eligible"] is False
    acceptance = {
        check["code"]: check["passed"] for check in report["acceptance"]["checks"]
    }
    assert acceptance["locked_holdout_direction"] is False
    assert acceptance["post_freeze_forward_count"] is False
    assert acceptance["post_freeze_forward_direction"] is False
    assert report["lane_isolation"] == {
        "passed": True,
        "affected_lanes": ["first_board"],
        "unchanged_lanes": ["one_to_two", "two_to_three", "high_board"],
    }
    assert comparisons["baseline"]["trade_count"] == 3
    assert comparisons["baseline"]["average_net_return_pct"] == 0.0
    assert comparisons["warmup_rank"]["trade_count"] == 3
    assert comparisons["warmup_rank"]["average_net_return_pct"] == 1.0
    assert comparisons["warmup_gate"]["trade_count"] == 2
    assert comparisons["warmup_gate"]["average_net_return_pct"] == 0.5
    assert comparisons["warmup_gate"]["formal"] is False
    assert report["selected_trades"]["warmup_gate"][0]["vt_symbol"] == "000002.SZSE"
    assert comparisons["warmup_leader_proxy"]["trade_count"] == 1
    assert comparisons["warmup_leader_proxy"]["formal"] is False
    assert comparisons["baseline"]["initial_cash"] == 100_000.0
    assert report["data_coverage"]["membership_snapshot_days"] == 0


def test_research_acceptance_never_uses_full_sample_to_hide_failed_holdout():
    rows: list[dict[str, object]] = []
    for offset in range(170):
        phase = "locked_holdout" if offset >= 140 else "expanding_oos"
        confirmed = offset < 120 or (offset >= 140 and offset % 2 == 0)
        gross_return = 1.31 if offset < 120 else -4.69
        rows.append(
            {
                "trade_date": date.fromordinal(
                    date(2025, 1, 1).toordinal() + offset
                ).isoformat(),
                "validation_phase": phase,
                "board_candidate_pool": {
                    "first_board": [
                        _research_candidate(
                            f"600{offset:03d}.SSE",
                            rank_score=90,
                            gross_return_pct=gross_return,
                            confirmed=confirmed,
                            leader_rank=1,
                            sealed=confirmed,
                        )
                    ]
                },
            }
        )

    report = build_sector_warmup_research_report(
        rows,
        data_coverage={
            "membership_snapshot_days": 500,
            "membership_snapshot_start": "2024-01-01",
            "membership_snapshot_end": "2026-01-01",
            "concept_daily_bar_days": 500,
            "concept_daily_bar_start": "2024-01-01",
            "concept_daily_bar_end": "2026-01-01",
            "intraday_fund_snapshot_days": 60,
            "intraday_fund_snapshot_start": "2024-01-01",
            "intraday_fund_snapshot_end": "2026-01-01",
            "signal_time_feature_linkage_ready": True,
        },
    )
    comparisons = {row["variant"]: row for row in report["comparisons"]}
    checks = {
        check["code"]: check["passed"] for check in report["acceptance"]["checks"]
    }

    assert comparisons["warmup_gate"]["trade_count"] >= 100
    assert comparisons["warmup_gate"]["formal"] is True
    assert checks["formal_data"] is True
    assert checks["sample_count"] is True
    assert checks["expanding_oos_direction"] is True
    assert checks["locked_holdout_direction"] is False
    assert checks["post_freeze_forward_count"] is False
    assert report["simulation_eligible"] is False


def test_research_stays_proxy_only_when_snapshot_dates_do_not_cover_events():
    report = build_sector_warmup_research_report(
        [
            {
                "trade_date": "2025-01-05",
                "validation_phase": "locked_holdout",
                "board_candidate_pool": {
                    "first_board": [
                        _research_candidate(
                            "600001.SSE",
                            rank_score=90,
                            gross_return_pct=1.31,
                            confirmed=True,
                            leader_rank=1,
                        )
                    ]
                },
            }
        ],
        data_coverage={
            "membership_snapshot_days": 500,
            "membership_snapshot_start": "2026-01-01",
            "membership_snapshot_end": "2027-12-31",
            "concept_daily_bar_days": 500,
            "concept_daily_bar_start": "2024-01-01",
            "concept_daily_bar_end": "2027-12-31",
            "intraday_fund_snapshot_days": 60,
            "intraday_fund_snapshot_start": "2024-01-01",
            "intraday_fund_snapshot_end": "2027-12-31",
            "signal_time_feature_linkage_ready": True,
        },
    )

    assert report["research_status"] == "proxy_only"
    assert report["formal_concept_backtest_ready"] is False
    assert report["simulation_eligible"] is False


def test_research_assigns_dates_after_rule_freeze_to_forward_validation():
    candidate = _research_candidate(
        "600001.SSE",
        rank_score=90,
        gross_return_pct=1.31,
        confirmed=True,
        leader_rank=1,
    )
    candidate["validation_phase"] = "locked_holdout"
    report = build_sector_warmup_research_report(
        [
            {
                "trade_date": "2026-07-13",
                "validation_phase": "locked_holdout",
                "board_candidate_pool": {"first_board": [candidate]},
            }
        ]
    )
    forward = {
        row["variant"]: row for row in report["phase_summaries"]["post_freeze_forward"]
    }
    holdout = {
        row["variant"]: row for row in report["phase_summaries"]["locked_holdout"]
    }

    assert forward["warmup_gate"]["trade_count"] == 1
    assert holdout["warmup_gate"]["trade_count"] == 0


def test_research_report_excludes_blocked_and_unclosed_candidates():
    blocked = _research_candidate(
        "000001.SZSE",
        rank_score=99,
        gross_return_pct=10.0,
        confirmed=True,
        leader_rank=1,
    )
    blocked["decision"] = "blocked"
    unclosed = _research_candidate(
        "000002.SZSE",
        rank_score=98,
        gross_return_pct=5.0,
        confirmed=True,
        leader_rank=1,
    )
    unclosed["outcome"] = {"sealed": True, "next_open_return_pct": None}
    eligible = _research_candidate(
        "000003.SZSE",
        rank_score=80,
        gross_return_pct=1.31,
        confirmed=True,
        leader_rank=1,
    )

    report = build_sector_warmup_research_report(
        [
            {
                "trade_date": "2026-01-05",
                "validation_phase": "expanding_oos",
                "board_candidate_pool": {"first_board": [blocked, unclosed, eligible]},
            }
        ]
    )

    assert report["candidate_funnel"] == {
        "raw_first_board": 3,
        "eligible": 2,
        "closed": 1,
        "warmup_confirmed": 1,
        "warmup_quality_confirmed": 0,
    }
    assert report["comparisons"][0]["trade_count"] == 1


def test_history_service_loads_and_caches_sector_warmup_report(monkeypatch):
    calls = {"rows": 0, "coverage": 0}
    rows = [
        {
            "trade_date": "2026-01-05",
            "validation_phase": "expanding_oos",
            "board_candidate_pool": {
                "first_board": [
                    _research_candidate(
                        "000001.SZSE",
                        rank_score=90,
                        gross_return_pct=1.31,
                        confirmed=True,
                        leader_rank=1,
                    )
                ]
            },
        }
    ]

    def load_rows(*_args, **_kwargs):
        calls["rows"] += 1
        return rows

    def load_coverage():
        calls["coverage"] += 1
        return {"membership_snapshot_days": 0, "concept_daily_bar_days": 253}

    monkeypatch.setattr(
        history_service.history_repository, "load_history_range", load_rows
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_sector_warmup_data_coverage",
        load_coverage,
    )
    history_service._SECTOR_WARMUP_REPORT_CACHE.clear()

    first = history_service.get_sector_warmup_research(
        date(2026, 1, 1),
        date(2026, 1, 31),
    )
    second = history_service.get_sector_warmup_research(
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    assert first == second
    assert first["candidate_funnel"]["closed"] == 1
    assert calls == {"rows": 1, "coverage": 1}


def test_history_service_compares_real_four_position_cash_accounts(monkeypatch):
    candidate = _research_candidate(
        "600001.SSE",
        rank_score=90,
        gross_return_pct=5.0,
        confirmed=True,
        leader_rank=1,
        industry_sealed_count=2,
    )
    candidate.update(
        {
            "entry_date": "2026-01-05",
            "signal_date": "2026-01-05",
            "result_date": "2026-01-06",
            "signal_time": "10:15:00",
            "buy_time": "10:15:00",
            "signal_kind": "first_touch",
            "entry_price": 10.0,
            "limit_price": 10.0,
        }
    )
    candidate["outcome"].update(
        {
            "entry_day_close_price": 10.0,
            "next_open_price": 10.5,
            "next_close_price": 10.6,
        }
    )
    rows = [
        {
            "trade_date": "2026-01-05",
            "validation_phase": "expanding_oos",
            "board_candidate_pool": {"first_board": [candidate]},
        }
    ]
    bars = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-01-05",
            "open_price": 9.5,
            "high_price": 10.0,
            "low_price": 9.4,
            "close_price": 10.0,
        },
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-01-06",
            "open_price": 10.5,
            "high_price": 10.7,
            "low_price": 10.4,
            "close_price": 10.6,
        },
    ]
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        lambda *_args, **_kwargs: rows,
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_sector_warmup_data_coverage",
        lambda: {},
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args, **_kwargs: bars,
    )
    monkeypatch.setattr(
        history_service.live_repository,
        "load_snapshots_between",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        history_service.live_repository,
        "list_daily_trade_dates",
        lambda: ["2026-01-05", "2026-01-06"],
    )
    history_service._SECTOR_WARMUP_REPORT_CACHE.clear()

    report = history_service.get_sector_warmup_research(None, None)
    accounts = {
        row["variant"]: row for row in report["cash_accounts"]["comparisons"]
    }
    continuation = accounts["continuation_quality"]
    dual = accounts["dual_lane"]

    assert report["cash_accounts"]["account_config"]["initial_cash"] == 100_000
    assert report["cash_accounts"]["account_config"]["max_positions"] == 4
    assert continuation["summary"]["trade_count"] == 1
    assert continuation["summary"]["final_equity"] > 100_000
    assert dual["summary"] == continuation["summary"]
    assert report["rotation_forward"]["trigger_count"] == 0
    assert report["rotation_forward"]["closed_trade_count"] == 0
    assert report["rotation_forward"]["historical_substitution"] is False


def test_sector_warmup_api_validates_dates_and_returns_report(monkeypatch):
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_sector_warmup_research",
        lambda start, end: {
            "status": "ready",
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
    )
    client = TestClient(create_app())

    invalid = client.get(
        "/api/limit-up/history/sector-warmup?start=2026-02-01&end=2026-01-01"
    )
    response = client.get(
        "/api/limit-up/history/sector-warmup?start=2026-01-01&end=2026-01-31"
    )

    assert invalid.status_code == 400
    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ready",
        "start": "2026-01-01",
        "end": "2026-01-31",
    }


def test_live_snapshot_serializes_shadow_warmup_only_for_first_board():
    captured_at = datetime(2026, 7, 13, 10, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    quotes = {
        "trade_date": "20260713",
        "items": [
            {
                "vt_symbol": "600001.SSE",
                "name": "首板候选",
                "previous_close": 10.0,
                "last_price": 10.92,
                "change_pct": 9.2,
                "turnover": 500_000_000.0,
                "turnover_rate": 8.0,
            },
            {
                "vt_symbol": "600002.SSE",
                "name": "二进三候选",
                "previous_close": 10.0,
                "last_price": 10.90,
                "change_pct": 9.0,
                "turnover": 600_000_000.0,
                "turnover_rate": 12.0,
            },
        ],
    }
    context = {
        "by_symbol": {
            "600001.SSE": {
                "sector_id": "BK001",
                "sector_name": "光模块",
                "previous_close": 10.0,
                "prior_streak": 0,
                "lane_feature_ready": False,
                "concept_contexts": [
                    {
                        "sector_id": "BK001",
                        "sector_name": "光模块",
                        "group_id": "CWG-OPTICAL",
                        "group_name": "光模块 / CPO",
                        "heat_score": 72.0,
                        "trend_state": "ROTATION",
                        "main_net_inflow": 2_400_000_000.0,
                        "main_net_inflow_ratio": 4.2,
                        "flow_trade_date": "2026-07-13",
                    }
                ],
            },
            "600002.SSE": {
                "sector_id": "BK002",
                "sector_name": "机器人",
                "previous_close": 10.0,
                "prior_streak": 2,
                "lane_feature_ready": False,
                "concept_contexts": [
                    {
                        "sector_id": "BK002",
                        "sector_name": "机器人",
                        "group_id": "CWG-ROBOT",
                        "group_name": "机器人",
                        "heat_score": 80.0,
                        "main_net_inflow": 3_000_000_000.0,
                        "main_net_inflow_ratio": 5.0,
                    }
                ],
            },
        },
        "sentiment": {"phase": "repair"},
    }

    snapshot = build_live_snapshot(
        quotes, {"trade_date": "20260713", "pools": {}}, captured_at, context
    )
    candidates = {
        candidate["vt_symbol"]: candidate for candidate in snapshot["candidates"]
    }
    signals = {
        signal["vt_symbol"]: signal
        for lane in snapshot["recommendations"]["lanes"].values()
        for signal in lane
    }

    first = candidates["600001.SSE"]
    relay = candidates["600002.SSE"]
    assert first["board_lane"] == "first_board"
    assert first["warmup_group"] == "CWG-OPTICAL"
    assert first["warmup_state"] == "launch"
    assert first["warmup_leader_rank"] == 1
    assert first["warmup_flow_trade_date"] == "2026-07-13"
    assert first["rotation_shadow_state"] == "rejected"
    assert "concept_diffusion_insufficient" in first[
        "rotation_shadow_reason_codes"
    ]
    assert signals["600001.SSE"]["warmup_execution_effect"] == "none_research_only"
    assert signals["600001.SSE"]["rotation_shadow_execution_effect"] == (
        "none_research_only"
    )
    assert relay["board_lane"] == "two_to_three"
    assert "warmup_group" not in relay
    assert "warmup_state" not in signals["600002.SSE"]


def test_live_repository_aggregates_overlapping_concepts_into_one_context():
    candidate_memberships = [
        {
            "vt_symbol": "600001.SSE",
            "sector_id": "BK001",
            "sector_name": "光模块",
            "sector_type": "theme",
        },
        {
            "vt_symbol": "600001.SSE",
            "sector_id": "BK002",
            "sector_name": "CPO",
            "sector_type": "theme",
        },
    ]
    all_memberships = [
        *_memberships(
            "BK001",
            "光模块",
            [f"00000{i}.SZSE" for i in range(1, 7)],
            sector_type="theme",
        ),
        *_memberships(
            "BK002",
            "CPO",
            [
                "000001.SZSE",
                "000002.SZSE",
                "000003.SZSE",
                "000004.SZSE",
                "000005.SZSE",
                "000007.SZSE",
            ],
            sector_type="theme",
        ),
    ]
    scores = {
        "BK001": {"heat_score": 72.0, "trend_state": "hot"},
        "BK002": {"heat_score": 68.0, "trend_state": "watch"},
    }
    flows = {
        "BK001": {
            "main_net_inflow": 2_000_000_000.0,
            "main_net_inflow_ratio": 4.0,
            "trade_date": "2026-07-13",
        },
        "BK002": {
            "main_net_inflow": 1_000_000_000.0,
            "main_net_inflow_ratio": 2.0,
            "trade_date": "2026-07-13",
        },
    }

    contexts = live_repository._concept_group_contexts(
        candidate_memberships,
        all_memberships,
        scores,
        flows,
    )

    assert len(contexts) == 1
    assert contexts[0]["group_name"] == "光模块 / CPO"
    assert contexts[0]["sector_ids"] == ["BK001", "BK002"]
    assert contexts[0]["heat_score"] == 70.0
    assert contexts[0]["main_net_inflow"] == 1_500_000_000.0
    assert contexts[0]["main_net_inflow_ratio"] == 3.0
    assert contexts[0]["flow_trade_date"] == "2026-07-13"


def test_live_repository_keeps_concept_rows_out_of_existing_primary_context():
    memberships = [
        {
            "sector_id": "INDUSTRY",
            "sector_name": "通信设备",
            "sector_type": "industry",
            "rank": 2,
        },
        {
            "sector_id": "CONCEPT",
            "sector_name": "CPO",
            "sector_type": "concept",
            "rank": 1,
        },
    ]
    scores = {
        "INDUSTRY": {"heat_score": 50.0},
        "CONCEPT": {"heat_score": 99.0},
    }

    selected = live_repository._best_membership(memberships, scores, {})

    assert selected["sector_id"] == "INDUSTRY"
