from __future__ import annotations

from datetime import date, datetime, timedelta

from alphaagent.server.services.limit_up.leader_cycle_repository import (
    CoverageRow,
    _coverage_from_aggregate,
    coverage_row_from_rows,
    evaluate_propagation_coverage,
)
from alphaagent.server.services.limit_up.leader_cycle_research import (
    _next_descriptive_stage,
    build_daily_cycle_ledger,
    build_ignition_events,
    build_propagation_panel,
    render_daily_report,
    render_intraday_report,
)


def test_coverage_is_bounded_to_the_requested_rows() -> None:
    rows = [
        {"trade_date": date(2026, 7, 20), "vt_symbol": "600001.SSE", "frame": 1},
        {"trade_date": date(2026, 7, 20), "vt_symbol": "600002.SSE", "frame": 1},
        {"trade_date": date(2026, 7, 21), "vt_symbol": "600001.SSE", "frame": 2},
    ]

    coverage = coverage_row_from_rows(
        "minute_bars",
        rows,
        date_field="trade_date",
        symbol_field="vt_symbol",
        frame_field="frame",
        evidence_level="point_in_time_partial",
    )

    assert coverage == CoverageRow(
        dataset="minute_bars",
        first_date=date(2026, 7, 20),
        last_date=date(2026, 7, 21),
        trade_day_count=2,
        symbol_count=2,
        symbol_day_count=3,
        frame_count=2,
        row_count=3,
        evidence_level="point_in_time_partial",
    )


def test_minute_coverage_keeps_aggregate_symbol_day_count() -> None:
    coverage = _coverage_from_aggregate(
        "minute_bars_1m",
        {
            "first_date": date(2026, 7, 20),
            "last_date": date(2026, 7, 21),
            "trade_day_count": 2,
            "symbol_count": 2,
            "symbol_day_count": 3,
            "row_count": 720,
        },
    )

    assert coverage.symbol_day_count == 3


def test_propagation_coverage_requires_prior_members_and_all_windows() -> None:
    ignition_at = datetime(2026, 7, 20, 10, 0)
    required = [
        ignition_at - timedelta(minutes=1),
        ignition_at + timedelta(minutes=1),
        ignition_at + timedelta(minutes=3),
        ignition_at + timedelta(minutes=5),
        ignition_at + timedelta(minutes=10),
    ]
    members = [f"6000{index:02d}.SSE" for index in range(11)]
    minute_bars = [
        {"vt_symbol": symbol, "bar_time": moment, "trade_date": date(2026, 7, 20)}
        for symbol in members[:10]
        for moment in required
    ]
    result = evaluate_propagation_coverage(
        {
            "events": [
                {
                    "trade_date": date(2026, 7, 20),
                    "ignition_at": ignition_at,
                    "ignition_cluster_id": "power-1000",
                    "vt_symbol": members[0],
                    "sector_ids": ["BK001"],
                    "control_available": True,
                }
            ],
            "memberships": [
                {
                    "snapshot_date": date(2026, 7, 17),
                    "sector_id": "BK001",
                    "vt_symbol": symbol,
                }
                for symbol in members
            ],
            "membership_scopes": [
                {
                    "snapshot_date": date(2026, 7, 17),
                    "scope_type": "concept",
                    "complete": True,
                }
            ],
            "minute_bars": minute_bars,
        }
    )

    assert result["accepted_count"] == 1
    assert result["accepted_events"][0]["member_coverage_ratio"] == 0.9
    assert result["accepted_events"][0]["member_count"] == 10


def test_propagation_coverage_requires_members_after_excluding_ignition() -> None:
    ignition_at = datetime(2026, 7, 20, 10, 0)
    required = [
        ignition_at - timedelta(minutes=1),
        ignition_at + timedelta(minutes=1),
        ignition_at + timedelta(minutes=3),
        ignition_at + timedelta(minutes=5),
        ignition_at + timedelta(minutes=10),
    ]
    result = evaluate_propagation_coverage(
        {
            "events": [
                {
                    "trade_date": date(2026, 7, 20),
                    "ignition_at": ignition_at,
                    "ignition_cluster_id": "single-member-1000",
                    "vt_symbol": "600001.SSE",
                    "ignition_symbols": [],
                    "sector_ids": ["BK001"],
                    "control_available": True,
                }
            ],
            "memberships": [
                {
                    "snapshot_date": date(2026, 7, 17),
                    "sector_id": "BK001",
                    "vt_symbol": "600001.SSE",
                }
            ],
            "membership_scopes": [
                {
                    "snapshot_date": date(2026, 7, 17),
                    "scope_type": "concept",
                    "complete": True,
                }
            ],
            "minute_bars": [
                {"vt_symbol": "600001.SSE", "bar_time": moment}
                for moment in required
            ],
        }
    )

    assert result["accepted_count"] == 0
    assert result["excluded_events"][0]["member_count"] == 0
    assert "no_members_after_excluding_ignition" in (
        result["excluded_events"][0]["exclusion_reasons"]
    )


def test_propagation_coverage_excludes_missing_members_without_filling_zero() -> None:
    result = evaluate_propagation_coverage(
        {
            "events": [
                {
                    "trade_date": date(2026, 7, 20),
                    "ignition_at": datetime(2026, 7, 20, 10, 0),
                    "ignition_cluster_id": "power-1000",
                    "vt_symbol": "600001.SSE",
                    "sector_ids": ["BK001"],
                }
            ],
            "memberships": [],
            "minute_bars": [],
        }
    )

    reasons = result["excluded_events"][0]["exclusion_reasons"]
    assert "prior_membership_unavailable" in reasons
    assert "member_minute_coverage_below_90pct" in reasons
    assert "matched_market_control_unavailable" in reasons


def test_propagation_coverage_rejects_unverified_membership_snapshot() -> None:
    ignition_at = datetime(2026, 7, 20, 10, 0)
    required = [
        ignition_at - timedelta(minutes=1),
        ignition_at + timedelta(minutes=1),
        ignition_at + timedelta(minutes=3),
        ignition_at + timedelta(minutes=5),
        ignition_at + timedelta(minutes=10),
    ]
    result = evaluate_propagation_coverage(
        {
            "events": [
                {
                    "trade_date": date(2026, 7, 20),
                    "ignition_at": ignition_at,
                    "ignition_cluster_id": "power-1000",
                    "vt_symbol": "600001.SSE",
                    "sector_ids": ["BK001"],
                    "control_available": True,
                }
            ],
            "memberships": [
                {
                    "snapshot_date": date(2026, 7, 17),
                    "sector_id": "BK001",
                    "vt_symbol": "600001.SSE",
                }
            ],
            "membership_scopes": [
                {
                    "snapshot_date": date(2026, 7, 17),
                    "scope_type": "concept",
                    "complete": False,
                }
            ],
            "minute_bars": [
                {"vt_symbol": "600001.SSE", "bar_time": moment}
                for moment in required
            ],
        }
    )

    assert result["accepted_count"] == 0
    assert "prior_membership_unavailable" in result["excluded_events"][0]["exclusion_reasons"]


def test_daily_ledger_preserves_tied_highest_boards_and_three_clocks() -> None:
    trade_dates = [date(2026, 7, day) for day in (1, 2, 3)]
    daily_bars = [
        {
            "trade_date": trade_date,
            "vt_symbol": symbol,
            "name": name,
        }
        for trade_date in trade_dates
        for symbol, name in (("600001.SSE", "甲"), ("600002.SSE", "乙"))
    ]
    events = [
        {
            "trade_date": trade_date,
            "vt_symbol": symbol,
            "name": name,
            "is_sealed": True,
            "first_limit_time": "10:00:00",
            "turnover": 100.0,
        }
        for trade_date in trade_dates
        for symbol, name in (("600001.SSE", "甲"), ("600002.SSE", "乙"))
    ]
    events.append(
        {
            "trade_date": date(2026, 7, 4),
            "vt_symbol": "600003.SSE",
            "name": "非交易日脏记录",
            "is_sealed": True,
        }
    )
    current_memberships = [
        {
            "vt_symbol": symbol,
            "sector_id": "BK001",
            "sector_name": "电力",
            "sector_type": "concept",
        }
        for symbol in ("600001.SSE", "600002.SSE")
    ]

    ledger = build_daily_cycle_ledger(
        {
            "daily_bars": daily_bars,
            "events": events,
            "sentiment": [
                {
                    "date": trade_date,
                    "phase": "repair",
                    "score": 50.0,
                    "promotion_ladder": {},
                }
                for trade_date in trade_dates
            ],
            "memberships": [],
            "membership_scopes": [],
            "current_memberships": current_memberships,
            "fund_flows": [],
        }
    )

    assert len(ledger) == 3
    assert ledger[-1]["maximum_board_height"] == 3
    assert {row["name"] for row in ledger[-1]["highest_board_group"]} == {"甲", "乙"}
    assert {row["leadership_tenure_days"] for row in ledger[-1]["highest_board_group"]} == {3}
    assert ledger[-1]["theme_propagation_days"] is None
    assert ledger[-1]["membership_evidence_level"] == "current_membership_descriptive_only"


def test_daily_report_contains_cycle_role_and_data_limit_sections() -> None:
    report = render_daily_report(
        [
            {
                "trade_date": date(2026, 7, 20),
                "market_phase": "repair",
                "maximum_board_height": 1,
                "highest_board_group": [],
                "main_theme": None,
                "instant_fund_main_attack": None,
                "theme_stage": None,
                "membership_evidence_level": "current_membership_descriptive_only",
                "role_groups": [],
            }
        ],
        [],
    )

    assert "### Cycle summary" in report
    assert "### Daily switches" in report
    assert "### Role tenure" in report
    assert "### Data limits" in report


def test_daily_ledger_excludes_after_the_fact_style_concepts() -> None:
    trade_date = date(2026, 7, 20)
    ledger = build_daily_cycle_ledger(
        {
            "daily_bars": [
                {"trade_date": trade_date, "vt_symbol": "600001.SSE", "name": "甲"},
            ],
            "events": [
                {
                    "trade_date": trade_date,
                    "vt_symbol": "600001.SSE",
                    "name": "甲",
                    "is_sealed": True,
                    "first_limit_time": "10:00:00",
                }
            ],
            "memberships": [],
            "membership_scopes": [],
            "current_memberships": [
                {
                    "vt_symbol": "600001.SSE",
                    "sector_id": "BK001",
                    "sector_name": "电力",
                    "sector_type": "concept",
                },
                {
                    "vt_symbol": "600001.SSE",
                    "sector_id": "BK1675",
                    "sector_name": "历史新高",
                    "sector_type": "concept",
                },
            ],
            "fund_flows": [],
        }
    )

    assert ledger[0]["main_theme"]["group_name"] == "电力"


def test_descriptive_stage_marks_growth_after_divergence_as_reflux() -> None:
    assert _next_descriptive_stage("divergence", 1, 2) == "reflux"


def test_ignitions_within_sixty_seconds_form_one_cluster() -> None:
    payload = {
        "events": [
            {
                "trade_date": date(2026, 7, 20),
                "vt_symbol": "600001.SSE",
                "name": "甲",
                "first_limit_time": "10:00:00",
            },
            {
                "trade_date": date(2026, 7, 20),
                "vt_symbol": "600002.SSE",
                "name": "乙",
                "first_limit_time": "10:00:45",
            },
        ],
        "memberships": [
            {
                "snapshot_date": date(2026, 7, 17),
                "vt_symbol": symbol,
                "sector_id": "BK001",
                "sector_name": "电力",
            }
            for symbol in ("600001.SSE", "600002.SSE", "600003.SSE")
        ]
        + [
            {
                "snapshot_date": date(2026, 7, 17),
                "vt_symbol": symbol,
                "sector_id": "BK1675",
                "sector_name": "历史新高",
            }
            for symbol in ("600001.SSE", "600002.SSE")
        ],
        "membership_scopes": [
            {
                "snapshot_date": date(2026, 7, 17),
                "scope_type": "concept",
                "complete": True,
            }
        ],
    }

    events = build_ignition_events(payload)

    assert len(events) == 1
    assert events[0]["co_ignition"] is True
    assert events[0]["ignition_symbols"] == ["600001.SSE", "600002.SSE"]
    assert events[0]["concept_group_name"] == "电力"


def test_intraday_report_marks_zero_accepted_events_as_insufficient() -> None:
    report = render_intraday_report(
        {
            "accepted_count": 0,
            "excluded_count": 1,
            "accepted_events": [],
            "excluded_events": [
                {
                    "ignition_cluster_id": "power-1000",
                    "concept_group_name": "电力",
                    "member_count": 10,
                    "covered_member_count": 4,
                    "member_coverage_ratio": 0.4,
                    "exclusion_reasons": ["member_minute_coverage_below_90pct"],
                }
            ],
        },
        [],
    )

    assert "research_only/insufficient_point_in_time_coverage" in report
    assert "member_minute_coverage_below_90pct | 1" in report


def test_intraday_report_marks_fewer_than_thirty_events_as_insufficient() -> None:
    report = render_intraday_report(
        {
            "accepted_count": 1,
            "excluded_count": 0,
            "accepted_events": [
                {
                    "ignition_cluster_id": "power-1000",
                    "concept_group_name": "电力",
                    "member_count": 10,
                    "covered_member_count": 10,
                    "member_coverage_ratio": 1.0,
                    "exclusion_reasons": [],
                }
            ],
            "excluded_events": [],
        },
        [],
    )

    assert "research_only/insufficient_point_in_time_coverage" in report


def test_propagation_excludes_leader_and_removes_market_wide_rise() -> None:
    ignition_at = datetime(2026, 7, 20, 10, 0)
    moments = [
        ignition_at - timedelta(minutes=1),
        ignition_at + timedelta(minutes=1),
        ignition_at + timedelta(minutes=3),
        ignition_at + timedelta(minutes=5),
        ignition_at + timedelta(minutes=10),
    ]
    minute_bars = []
    for symbol in ("600001.SSE", "600002.SSE", "600003.SSE", "600004.SSE"):
        for index, moment in enumerate(moments):
            change = 0.0 if index == 0 else 2.0
            if symbol == "600001.SSE" and index:
                change = 9.8
            minute_bars.append(
                {
                    "vt_symbol": symbol,
                    "bar_time": moment,
                    "change_pct": change,
                    "turnover": 100.0 + index,
                }
            )
    event = {
        "trade_date": date(2026, 7, 20),
        "ignition_at": ignition_at,
        "ignition_cluster_id": "power-1000",
        "concept_group_id": "BK001",
        "ignition_symbols": ["600001.SSE"],
        "member_symbols": ["600001.SSE", "600002.SSE", "600003.SSE"],
        "control_symbols": ["600004.SSE"],
        "member_coverage_ratio": 1.0,
    }

    panel = build_propagation_panel([event], {"minute_bars": minute_bars})
    median_rows = [row for row in panel if row["metric"] == "median_change_pct"]
    rise_rows = [row for row in panel if row["metric"] == "rise_count"]

    assert all(row["raw_theme_delta_ex_leader"] == 2.0 for row in median_rows)
    assert all(row["incremental_propagation"] == 0.0 for row in median_rows)
    assert all(row["incremental_propagation"] == 0.0 for row in rise_rows)


def test_members_already_strong_before_ignition_add_no_propagation() -> None:
    ignition_at = datetime(2026, 7, 20, 10, 0)
    moments = [
        ignition_at - timedelta(minutes=1),
        ignition_at + timedelta(minutes=1),
        ignition_at + timedelta(minutes=3),
        ignition_at + timedelta(minutes=5),
        ignition_at + timedelta(minutes=10),
    ]
    minute_bars = [
        {"vt_symbol": symbol, "bar_time": moment, "change_pct": 5.0}
        for symbol in ("600002.SSE", "600003.SSE")
        for moment in moments
    ]
    event = {
        "trade_date": date(2026, 7, 20),
        "ignition_at": ignition_at,
        "ignition_cluster_id": "power-1000",
        "concept_group_id": "BK001",
        "ignition_symbols": ["600001.SSE"],
        "member_symbols": ["600001.SSE", "600002.SSE"],
        "control_symbols": ["600003.SSE"],
        "member_coverage_ratio": 1.0,
    }

    panel = build_propagation_panel([event], {"minute_bars": minute_bars})

    assert all(row["raw_theme_delta_ex_leader"] == 0.0 for row in panel)
    assert all(row["incremental_propagation"] == 0.0 for row in panel)
