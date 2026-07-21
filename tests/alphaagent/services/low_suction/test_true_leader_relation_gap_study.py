from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.true_leader_relation_gap_study import (
    RelationGapInputs,
    audit_relation_gap_cases,
    build_relation_gap_cases,
    build_relation_gap_report,
    load_frozen_mismatch_report,
    render_relation_gap_study_json,
    render_relation_gap_study_markdown,
)


def _mismatch_row(
    *,
    cycle_id: str,
    relation_status: str,
    cycle_date: str = "2025-09-10",
    concept_name: str = "目标概念",
    sector_id: str = "BK0001",
) -> dict[str, object]:
    return {
        "cycle_id": cycle_id,
        "trade_date": cycle_date,
        "sector_id": sector_id,
        "concept_name": concept_name,
        "truth_top1_symbol": "600001.SSE",
        "truth_top1_stock_name": "测试股份",
        "truth_relation_status": relation_status,
        "mismatch_category": "relation_or_board_data_risk",
        "decisive_miss_reason": "truth_main_rise_not_alive",
        "truth_causal_rank": 5,
        "truth_top1_concept_count_same_date": 1,
    }


def _frozen_report() -> dict[str, object]:
    return {
        "study_version": "true-leader-mismatch-audit-v1",
        "formal_metrics": None,
        "formal_selected_mode": None,
        "low_suction_outcomes_read": False,
        "coverage": {
            "discovery_start": "2023-03-28",
            "discovery_end": "2025-11-17",
            "outer_holdout_end": "2026-07-16",
        },
        "mismatch_ledger": [
            _mismatch_row(
                cycle_id="C1",
                relation_status="reason_source_unavailable",
            ),
            _mismatch_row(
                cycle_id="C2",
                relation_status="reason_source_available_but_unconfirmed",
            ),
        ],
    }


def test_frozen_mismatch_report_requires_exact_sha(tmp_path: Path) -> None:
    path = tmp_path / "mismatch.json"
    path.write_text(json.dumps(_frozen_report()), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA256"):
        load_frozen_mismatch_report(path)


def test_build_relation_gap_cases_keeps_only_unconfirmed_misses() -> None:
    cases = build_relation_gap_cases(_frozen_report())

    assert cases["cycle_id"].tolist() == ["C2"]
    assert cases["truth_relation_status"].eq(
        "reason_source_available_but_unconfirmed"
    ).all()


def _cases(
    cycle_date: str,
    *,
    concept_name: str = "目标概念",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _mismatch_row(
                cycle_id="C2",
                relation_status="reason_source_available_but_unconfirmed",
                cycle_date=cycle_date,
                concept_name=concept_name,
            )
        ]
    )


def _events(
    event_date: str,
    reason: str,
    *,
    event_type: str = "limit_pool_zt",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": pd.Timestamp(event_date),
                "vt_symbol": "600001.SSE",
                "event_type": event_type,
                "source": "akshare.stock_ztb_em",
                "reason": reason,
            }
        ]
    )


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "source_date",
            "vt_symbol",
            "event_type",
            "source",
            "reason",
        ]
    )


def _concepts(concept_name: str = "目标概念") -> pd.DataFrame:
    return pd.DataFrame(
        [{"sector_id": "BK0001", "concept_name": concept_name}]
    )


def test_source_start_inside_window_is_partial_not_full() -> None:
    rows = audit_relation_gap_cases(
        _cases("2025-07-04", concept_name="免疫治疗"),
        _events("2025-07-04", "创新药+细胞免疫治疗"),
        _concepts("免疫治疗"),
        trading_dates=tuple(pd.bdate_range("2025-06-09", "2025-07-04").date),
        evidence_dates=tuple(pd.bdate_range("2025-06-27", "2025-07-04").date),
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "window_coverage_status"] == "partial_inventory_window"
    assert rows.loc[0, "inventory_covered_sessions"] < 20
    assert rows.loc[0, "stock_evidence_status"] == "reason_target_unconfirmed"


def test_full_window_with_no_stock_event_stays_unknown() -> None:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)
    rows = audit_relation_gap_cases(
        _cases("2025-09-10"),
        _empty_events(),
        _concepts(),
        trading_dates=dates,
        evidence_dates=dates,
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "gap_resolution"] == "unresolved_no_stock_limit_event"
    assert not bool(rows.loc[0, "promoted_to_precycle_confirmed"])
    assert not bool(rows.loc[0, "current_membership_proven_wrong"])


def test_full_window_with_event_but_no_reason_stays_unknown() -> None:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)
    rows = audit_relation_gap_cases(
        _cases("2025-09-10"),
        _events("2025-09-04", "", event_type="limit_pool_zbgc"),
        _concepts(),
        trading_dates=dates,
        evidence_dates=dates,
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "gap_resolution"] == "unresolved_reason_missing"
    assert rows.loc[0, "failed_event_count"] == 1


def test_missing_inventory_date_is_not_a_full_window() -> None:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)
    evidence_dates = tuple(value for index, value in enumerate(dates) if index != 5)
    rows = audit_relation_gap_cases(
        _cases("2025-09-10"),
        _empty_events(),
        _concepts(),
        trading_dates=dates,
        evidence_dates=evidence_dates,
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "window_coverage_status"] == "inventory_date_gap"
    assert rows.loc[0, "gap_resolution"] == "unresolved_inventory_date_gap"


def test_lexical_containment_is_diagnostic_only() -> None:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)
    rows = audit_relation_gap_cases(
        _cases("2025-09-10", concept_name="免疫治疗"),
        _events("2025-09-10", "细胞免疫治疗"),
        _concepts("免疫治疗"),
        trading_dates=dates,
        evidence_dates=dates,
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "lexical_containment_tokens"] == ("细胞免疫治疗",)
    assert rows.loc[0, "gap_resolution"] == (
        "unresolved_lexical_candidate_requires_external_verification"
    )
    assert not bool(rows.loc[0, "promoted_to_precycle_confirmed"])


def test_exact_other_concept_is_not_target_confirmation() -> None:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)
    concepts = pd.DataFrame(
        [
            {"sector_id": "BK0001", "concept_name": "光伏概念"},
            {"sector_id": "BK0002", "concept_name": "储能概念"},
        ]
    )
    rows = audit_relation_gap_cases(
        _cases("2025-09-10", concept_name="光伏概念"),
        _events("2025-09-05", "储能"),
        concepts,
        trading_dates=dates,
        evidence_dates=dates,
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "gap_resolution"] == (
        "unresolved_event_points_to_other_concepts"
    )
    assert rows.loc[0, "other_concept_names"] == ("储能概念",)
    assert not bool(rows.loc[0, "current_membership_proven_wrong"])


def test_precycle_exact_target_conflicts_with_frozen_unconfirmed_case() -> None:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)

    with pytest.raises(ValueError, match="precycle exact target"):
        audit_relation_gap_cases(
            _cases("2025-09-10", concept_name="目标概念"),
            _events("2025-09-05", "目标概念"),
            _concepts("目标概念"),
            trading_dates=dates,
            evidence_dates=dates,
            discovery_end=date(2025, 11, 17),
        )


def test_postcycle_exact_relation_never_moves_backward() -> None:
    trading_dates = tuple(pd.bdate_range("2025-08-18", "2025-09-16").date)
    rows = audit_relation_gap_cases(
        _cases("2025-09-12", concept_name="统一大市场"),
        _events("2025-09-16", "统一大市场"),
        _concepts("统一大市场"),
        trading_dates=trading_dates,
        evidence_dates=trading_dates,
        discovery_end=date(2025, 11, 17),
    )

    assert rows.loc[0, "postcycle_target_relation_dates"] == (
        date(2025, 9, 16),
    )
    assert not bool(rows.loc[0, "promoted_to_precycle_confirmed"])


def _audited_cases() -> pd.DataFrame:
    dates = tuple(pd.bdate_range("2025-08-14", "2025-09-10").date)
    return audit_relation_gap_cases(
        _cases("2025-09-10"),
        _empty_events(),
        _concepts(),
        trading_dates=dates,
        evidence_dates=dates,
        discovery_end=date(2025, 11, 17),
    )


def test_report_keeps_all_cases_and_no_formal_outputs() -> None:
    inputs = RelationGapInputs(
        prior_report=_frozen_report(),
        cases=_cases("2025-09-10"),
        events=_empty_events(),
        concepts=_concepts(),
        trading_dates=tuple(pd.bdate_range("2025-08-14", "2025-09-10").date),
        evidence_dates=tuple(pd.bdate_range("2025-08-14", "2025-09-10").date),
        discovery_end=date(2025, 11, 17),
        coverage={},
        fingerprints={},
    )

    report = build_relation_gap_report(inputs, audited_cases=_audited_cases())

    assert report["coverage"]["audited_cases"] == 1
    assert len(report["case_ledger"]) == 1
    assert report["formal_selected_mode"] is None
    assert report["low_suction_outcomes_read"] is False
    assert report["semantic_aliases_promoted"] is False
    assert json.loads(render_relation_gap_study_json(report))["study_version"] == (
        "true-leader-relation-gap-audit-v1"
    )
    assert "真龙头关系缺口审计" in render_relation_gap_study_markdown(report)


def test_cli_registers_true_leader_relation_gap_study() -> None:
    args = build_parser().parse_args(["v2-true-leader-relation-gap-study"])

    assert args.command == "v2-true-leader-relation-gap-study"
