from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from alphaagent.server.services.low_suction import cli, v2_audit
from alphaagent.server.services.low_suction.research_protocol import default_protocol
from alphaagent.server.services.low_suction.v2_audit import (
    StrictStageCounts,
    build_v2_stage_audit,
)


def _dates(count: int) -> tuple[date, ...]:
    start = date(2023, 3, 28)
    return tuple(start + timedelta(days=index) for index in range(count))


def _quality_report() -> dict[str, object]:
    return {
        "status": "blocked_by_data_quality",
        "blocking_gaps": [
            "historical_concept_membership",
            "historical_security_status",
            "candidate_minute_paths",
        ],
        "formal_metrics": None,
        "coverage": {
            "concept_membership": {
                "trade_days": 3,
                "mode": "current_proxy",
            },
            "security_status": {"trade_days": 0, "mode": "unavailable"},
            "candidate_minutes": {
                "total_pairs": 0,
                "covered_pairs": 0,
                "coverage_pct": 0.0,
            },
        },
        "inventory": {
            "market_timing": {
                "state_counts": {
                    "GOLD/NORMAL": 395,
                    "SILVER/NORMAL": 67,
                    "SILVER/DANGER": 30,
                    "NEUTRAL/NORMAL": 23,
                    "GOLD/DANGER": 4,
                }
            }
        },
    }


def test_v2_audit_separates_completed_cycle_from_blocked_leader_stage() -> None:
    report = build_v2_stage_audit(
        _quality_report(),
        cycle_dates=_dates(800),
        strict_counts=StrictStageCounts(0, 0, 0, 0),
        protocol=default_protocol(),
    )

    assert report["conclusion"] == "blocked_by_data_quality"
    assert report["formal_metrics"] is None
    assert report["stages"]["cycle"]["status"] == "completed"
    assert report["stages"]["cycle"]["frozen_definition"] == "breakout_trend"
    assert report["stages"]["leader"]["status"] == "blocked"
    assert report["stages"]["leader"]["strict_membership_dates"] == 0
    assert report["stages"]["leader"]["strict_security_dates"] == 0
    assert report["stages"]["state"]["status"] == "blocked"
    assert report["stages"]["validation"]["status"] == "blocked"


def test_v2_audit_exposes_strict_sixty_percent_targets_and_regimes() -> None:
    report = build_v2_stage_audit(
        _quality_report(),
        cycle_dates=_dates(800),
        strict_counts=StrictStageCounts(0, 0, 0, 0),
        protocol=default_protocol(),
    )
    targets = report["qualification_targets"]

    assert targets["win_rate_pct"] == "> 60.0"
    assert targets["compounded_return_pct"] == "> 60.0"
    assert targets["minimum_traded_regimes"] == 2
    assert targets["per_traded_regime_win_rate_pct"] == "> 60.0"
    assert report["market_regime_inventory"]["SILVER/DANGER"] == 30


def test_v2_audit_keeps_forward_accumulation_separate_from_historical_strict() -> None:
    report = build_v2_stage_audit(
        _quality_report(),
        cycle_dates=_dates(800),
        strict_counts=StrictStageCounts(
            0,
            0,
            0,
            0,
            forward_membership_dates=0,
            forward_security_dates=1,
            forward_membership_rows=0,
            forward_security_rows=3_192,
        ),
        protocol=default_protocol(),
    )
    leader = report["stages"]["leader"]

    assert leader["strict_security_dates"] == 0
    assert leader["forward_security_accumulating_dates"] == 1
    assert leader["forward_security_rows"] == 3_192
    assert leader["status"] == "blocked"


def test_v2_audit_reads_only_low_suction_tradable_forward_memberships() -> None:
    source = Path(
        "alphaagent/server/services/low_suction/v2_audit.py"
    ).read_text()

    assert "low_suction_forward_membership_snapshot_scopes" in source
    assert "low_suction_forward_membership_snapshots" in source
    assert "TRADABLE_SCOPE_TYPE" in source


def test_v2_audit_cli_is_read_only_and_keeps_metrics_null(monkeypatch, capsys) -> None:
    expected = build_v2_stage_audit(
        _quality_report(),
        cycle_dates=_dates(800),
        strict_counts=StrictStageCounts(0, 0, 0, 0),
        protocol=default_protocol(),
    )
    monkeypatch.setattr(v2_audit, "load_v2_stage_audit", lambda: expected)

    assert cli.main(["v2-audit", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["formal_metrics"] is None
    assert payload["stages"]["leader"]["status"] == "blocked"
