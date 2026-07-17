from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import (
    cli,
    dc_membership_import,
    reporting,
    theme_eligibility_research,
)
from alphaagent.server.services.low_suction.proxy_reporting import (
    build_proxy_evidence,
    render_proxy_markdown,
)


def _report() -> dict[str, object]:
    return {
        "research_version": "low-suction-data-quality-v2",
        "as_of_date": "2026-07-15",
        "status": "blocked_by_data_quality",
        "strict_ready": False,
        "evidence_level": "membership_proxy",
        "blocking_gaps": [
            "historical_concept_membership",
            "historical_security_status",
            "candidate_minute_paths",
        ],
        "formal_metrics": None,
        "coverage": {
            "stock_daily": {
                "rows": 4_288_952,
                "entities": 5_675,
                "trade_days": 799,
                "start": "2023-03-28",
                "end": "2026-07-15",
                "calendar_span_days": 1_205,
                "coverage_pct": 92.209,
                "mode": "strict",
                "sources": ["akshare"],
            },
            "concept_daily": {
                "rows": 333_871,
                "entities": 498,
                "trade_days": 799,
                "start": "2023-03-28",
                "end": "2026-07-15",
                "coverage_pct": 99.7567,
                "mode": "strict",
                "sources": ["eastmoney.board_kline"],
            },
            "concept_membership": {
                "rows": 211_782,
                "entities": 5_610,
                "trade_days": 2,
                "start": "2026-07-14",
                "end": "2026-07-15",
                "coverage_pct": 100.0,
                "mode": "current_proxy",
                "sources": ["eastmoney.push2.board"],
            },
            "security_status": {
                "rows": 0,
                "entities": 0,
                "trade_days": 0,
                "start": None,
                "end": None,
                "coverage_pct": 0.0,
                "mode": "unavailable",
                "sources": [],
            },
            "candidate_minutes": {
                "total_pairs": 0,
                "covered_pairs": 0,
                "coverage_pct": 0.0,
            },
            "market_timing": {
                "rows": 518,
                "entities": 5,
                "trade_days": 518,
                "start": "2024-05-28",
                "end": "2026-07-15",
                "coverage_pct": 100.0,
                "mode": "point_in_time_derived",
                "sources": ["market_timing_panel"],
            },
            "supporting": {
                "stock_minutes_1m": {
                    "rows": 1_045_389,
                    "entities": 1_709,
                    "trade_days": 105,
                    "start": "2026-01-20",
                    "end": "2026-07-15",
                    "coverage_pct": 0.0,
                    "mode": "partial_event_targeted",
                    "sources": ["eastmoney.stock_kline_minute"],
                }
            },
        },
        "inventory": {
            "stock_daily": {
                "raw_trade_days": 7_913,
            },
            "concept_daily": {
                "concept_count": 498,
                "indexed_concept_count": 498,
                "canonical_source": "eastmoney.board_kline",
                "minimum_active_concepts": 300,
                "minimum_cross_section_pct": 90.0,
                "minimum_expected_active_concepts": 371,
                "maximum_expected_active_concepts": 495,
                "raw_trade_days": 859,
                "raw_start": "2022-12-26",
                "raw_end": "2026-07-15",
                "complete_trade_days": 799,
                "complete_start": "2023-03-28",
                "complete_end": "2026-07-15",
            },
            "concept_membership": {
                "raw_snapshot_trade_days": 3,
                "effective_trade_days": 2,
                "captures": [],
            },
            "market_timing": {
                "state_counts": {
                    "GOLD/NORMAL": 395,
                    "SILVER/NORMAL": 66,
                    "SILVER/DANGER": 30,
                }
            },
        },
        "source_limitations": {
            "tushare_dc_member": {
                "status": "candidate_historical_membership_unconfigured",
                "reason": "official dc_member supports historical daily constituents but has not been measured locally",
                "url": "https://tushare.pro/document/2?doc_id=363",
            },
            "tushare_ths_member": {
                "status": "not_strict_historical_membership",
                "reason": "official documentation marks in_date/out_date as unavailable",
                "url": "https://tushare.pro/document/2?doc_id=261",
            }
        },
    }


def test_markdown_keeps_formal_metrics_null_and_lists_gaps() -> None:
    markdown = reporting.render_audit_markdown(_report())

    assert "结论：`blocked_by_data_quality`" in markdown
    assert "正式胜率、复利、利润因子和回撤：`null`" in markdown
    assert "历史概念成员" in markdown
    assert "历史证券状态" in markdown
    assert "498" in markdown
    assert "`1,205` 个自然日" in markdown
    assert "Supporting Coverage" in markdown
    assert "1,045,389" in markdown
    assert "2022-12-26..2026-07-15" in markdown
    assert "动态有效概念分母：`371..495`" in markdown
    assert "股票和概念指数的三年日线门槛都已通过" in markdown
    assert "三年可靠股票日线" not in markdown
    assert "| 证券状态 | `unavailable` | 0 | 0 | 0 | - |" in markdown
    assert "https://tushare.pro/document/2?doc_id=261" in markdown
    assert "https://tushare.pro/document/2?doc_id=363" in markdown
    assert "python -m alphaagent.server.services.low_suction.cli audit" in markdown


def test_json_output_is_deterministic() -> None:
    first = reporting.render_audit_json(_report())
    second = reporting.render_audit_json(_report())

    assert first == second
    assert json.loads(first)["formal_metrics"] is None


def test_output_path_must_stay_in_evidence_directory(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "memory" / "06_backtests"
    evidence_dir.mkdir(parents=True)

    accepted = reporting.validated_output_path(
        evidence_dir / "audit.md",
        evidence_dir=evidence_dir,
    )
    assert accepted == (evidence_dir / "audit.md").resolve()

    with pytest.raises(ValueError, match="memory/06_backtests"):
        reporting.validated_output_path(
            tmp_path / "outside.md",
            evidence_dir=evidence_dir,
        )


def test_cli_prints_json_without_database_details(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_data_quality_report", _report)

    exit_code = cli.main(["audit", "--format", "json"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert json.loads(output)["status"] == "blocked_by_data_quality"
    assert "DATABASE_URL" not in output


def test_membership_source_status_cli_never_exposes_credentials(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        dc_membership_import,
        "membership_source_status",
        lambda: {
            "status": "ready_for_probe",
            "configured": True,
            "strict_ready": False,
            "source": "tushare.dc_member.lag1",
        },
    )

    exit_code = cli.main(["membership-source-status"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert json.loads(output)["status"] == "ready_for_probe"
    assert "secret" not in output
    assert "token" not in output.lower()


def test_membership_probe_and_backfill_cli_keep_write_explicit(
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, object]] = []

    def run(**kwargs):
        calls.append(kwargs)
        return {"status": "unconfigured", "strict_ready": False}

    monkeypatch.setattr(dc_membership_import, "run_dc_membership_import", run)

    assert cli.main(
        [
            "membership-probe",
            "--start",
            "2023-03-28",
            "--end",
            "2026-07-15",
            "--format",
            "json",
        ]
    ) == 0
    capsys.readouterr()
    assert cli.main(
        [
            "membership-backfill",
            "--start",
            "2023-03-28",
            "--end",
            "2026-07-15",
            "--write",
        ]
    ) == 0
    capsys.readouterr()

    assert calls[0]["dry_run"] is True
    assert calls[0]["max_dates"] == 5
    assert calls[1]["dry_run"] is False
    assert calls[1]["max_dates"] == 800


def test_theme_eligibility_cli_reports_blocker_without_strategy_metrics(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        theme_eligibility_research,
        "run_current_theme_eligibility_audit",
        lambda **_kwargs: {
            "status": "blocked_by_historical_membership",
            "qualified": False,
            "formal_metrics": None,
            "rule": None,
        },
    )

    exit_code = cli.main(
        [
            "theme-eligibility-research",
            "--start",
            "2023-03-28",
            "--end",
            "2026-07-15",
            "--format",
            "json",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["status"] == "blocked_by_historical_membership"
    assert report["formal_metrics"] is None


def test_proxy_evidence_prioritizes_validation_then_reports_holdout() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": f"E{index}",
                "vt_symbol": f"600{index:03d}.SSE",
                "trade_date": pd.Timestamp("2026-04-01") + pd.Timedelta(days=index),
                "sector_id": "THEME_A",
                "family_tags": ("first_divergence",),
                "cohort": "main_rise_top3",
                "time_split": "validation" if index < 3 else "holdout",
                "active_direction": "GOLD" if index % 2 == 0 else "SILVER",
                "danger_state": "NORMAL",
            }
            for index in range(6)
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "event_id": f"E{index}",
                "exit_key": "entry_plus_1_close",
                "status": "closed",
                "reason": None,
                "net_return_pct": 2.0 if index != 4 else -1.0,
            }
            for index in range(6)
        ]
    )
    stressed = outcomes.copy()
    stressed["net_return_pct"] = stressed["net_return_pct"] - 0.5

    evidence = build_proxy_evidence(
        events,
        outcomes,
        stressed,
        coverage={"signal_trade_days": 6},
        minimum_validation_trades=2,
    )
    markdown = render_proxy_markdown(evidence)

    assert evidence["formal_metrics"] is None
    assert evidence["status"] == "archived_membership_proxy"
    assert evidence["selectable_for_v2"] is False
    assert evidence["superseded_by"] == "low-suction-research-v2"
    assert evidence["market_timing_metrics"]
    assert evidence["strict_retest_priorities"][0]["family"] == "first_divergence"
    assert evidence["strict_retest_priorities"][0]["holdout"]["closed"] == 3
    assert "不能作为正式胜率或复利" in markdown
