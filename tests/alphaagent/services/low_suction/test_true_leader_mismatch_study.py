from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.true_leader_mismatch_study import (
    TrueLeaderMismatchInputs,
    attach_board_risk,
    attach_relation_risk,
    build_cycle_audit_rows,
    build_decisive_miss_reasons,
    build_frozen_truth_ledger,
    build_mismatch_report,
    classify_mismatch_categories,
    evaluate_active_consensus,
    evaluate_mismatch_rank_modes,
    load_frozen_true_leader_report,
    rank_active_consensus,
    render_mismatch_study_json,
    render_mismatch_study_markdown,
    validate_frozen_candidate_rebuild,
)


def _leader(rank: int, symbol: str, name: str) -> dict[str, object]:
    return {
        "rank": rank,
        "vt_symbol": symbol,
        "stock_name": name,
        "first_strong_date_10d": "2025-01-02",
        "future_wave_count": 4 - rank,
        "future_40d_max_excess_pct": 20.0 - rank,
    }


def _prior_report() -> dict[str, object]:
    cycles = []
    for index, cycle_date in enumerate(("2025-01-10", "2025-01-13")):
        offset = index * 10
        cycles.append(
            {
                "cycle_id": f"C{index + 1}",
                "trade_date": cycle_date,
                "sector_id": f"BK000{index + 1}",
                "concept_name": f"测试概念{index + 1}",
                "candidate_count": 4,
                "causal_top3": [
                    _leader(1, f"{600001 + offset:06d}.SSE", "甲"),
                    _leader(2, f"{600002 + offset:06d}.SSE", "乙"),
                    _leader(3, f"{600003 + offset:06d}.SSE", "丙"),
                ],
                "truth_top3": [
                    _leader(1, f"{600004 + offset:06d}.SSE", "丁"),
                    _leader(2, f"{600002 + offset:06d}.SSE", "乙"),
                    _leader(3, f"{600003 + offset:06d}.SSE", "丙"),
                ],
                "causal_top3_captured_truth_top1": False,
            }
        )
    return {
        "study_version": "true-leader-wave-identification-v1",
        "formal_metrics": None,
        "formal_selected_mode": None,
        "cycle_summaries": cycles,
    }


def test_load_frozen_report_requires_exact_sha(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_prior_report()), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA256"):
        load_frozen_true_leader_report(path)


def test_truth_ledger_preserves_frozen_cycle_and_top3() -> None:
    ledger = build_frozen_truth_ledger(_prior_report())

    assert ledger["cycle_id"].nunique() == 2
    assert ledger.loc[ledger["truth_rank"].eq(1), "vt_symbol"].tolist() == [
        "600004.SSE",
        "600014.SSE",
    ]
    assert ledger.groupby("cycle_id")["truth_rank"].count().eq(3).all()


def _cycle_rows(cycle_date: str = "2025-07-10") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": "C1",
                "trade_date": pd.Timestamp(cycle_date),
                "sector_id": "BK0001",
                "concept_name": "测试概念一",
                "candidate_count": 4,
                "captured": False,
                "truth_top1_symbol": "600004.SSE",
                "truth_top1_stock_name": "丁",
                "causal_top3_symbols": ("600001.SSE", "600002.SSE", "600003.SSE"),
            }
        ]
    )


def _relations(source_date: str = "2025-07-03") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_date": pd.Timestamp(source_date),
                "sector_id": "BK0001",
                "vt_symbol": "600004.SSE",
                "relation_method": "normalized_suffix_exact",
            }
        ]
    )


def test_relation_absence_before_source_is_unknown_not_wrong() -> None:
    rows = attach_relation_risk(
        _cycle_rows("2024-01-10"),
        _relations(),
        trading_dates=tuple(pd.bdate_range("2023-12-01", "2025-07-10").date),
        source_start=date(2025, 6, 27),
    )

    assert rows.loc[0, "truth_relation_status"] == "reason_source_unavailable"


def test_precycle_reason_confirms_truth_relation() -> None:
    rows = attach_relation_risk(
        _cycle_rows(),
        _relations(),
        trading_dates=tuple(pd.bdate_range("2025-06-01", "2025-07-10").date),
        source_start=date(2025, 6, 27),
    )

    assert rows.loc[0, "truth_relation_status"] == "reason_confirmed_precycle"
    assert rows.loc[0, "truth_relation_method"] == "normalized_suffix_exact"


def test_relation_after_cycle_cannot_confirm_precycle_identity() -> None:
    rows = attach_relation_risk(
        _cycle_rows(),
        _relations("2025-07-11"),
        trading_dates=tuple(pd.bdate_range("2025-06-01", "2025-07-11").date),
        source_start=date(2025, 6, 27),
    )

    assert rows.loc[0, "truth_relation_status"] == "reason_source_available_but_unconfirmed"


def test_board_risk_marks_duplicate_leader_and_high_jaccard() -> None:
    cycles = pd.concat(
        [
            _cycle_rows(),
            _cycle_rows().assign(
                cycle_id="C2",
                sector_id="BK0002",
                concept_name="测试概念二",
            ),
        ],
        ignore_index=True,
    )
    memberships = pd.DataFrame(
        [
            {"sector_id": "BK0001", "vt_symbol": value}
            for value in ("A", "B", "C", "D", "E")
        ]
        + [
            {"sector_id": "BK0002", "vt_symbol": value}
            for value in ("A", "B", "C", "D", "F")
        ]
    )
    rows = attach_board_risk(cycles, memberships)

    assert rows["truth_top1_concept_count_same_date"].eq(2).all()
    assert rows["max_same_date_member_jaccard"].eq(4 / 6).all()
    assert not rows["near_duplicate_board"].any()


def test_board_risk_marks_subset_membership_at_threshold_as_near_duplicate() -> None:
    cycles = pd.concat(
        [
            _cycle_rows(),
            _cycle_rows().assign(cycle_id="C2", sector_id="BK0002"),
        ],
        ignore_index=True,
    )
    memberships = pd.DataFrame(
        [
            {"sector_id": "BK0001", "vt_symbol": value}
            for value in ("A", "B", "C", "D", "E")
        ]
        + [
            {"sector_id": "BK0002", "vt_symbol": value}
            for value in ("A", "B", "C", "D")
        ]
    )

    rows = attach_board_risk(cycles, memberships)

    assert rows["max_same_date_member_jaccard"].eq(0.8).all()
    assert rows["near_duplicate_board"].all()


def _candidate_features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": "C1",
                "trade_date": pd.Timestamp("2025-01-10"),
                "vt_symbol": "600001.SSE",
                "main_rise_alive": True,
                "ignition_precedes_concept": True,
                "first_strong_sessions_ago_10d": 8,
                "last_strong_sessions_ago_10d": 5,
                "strong_days_10": 1,
                "stock_excess_concept_10d_pct": 10.0,
                "distance_from_prior_high_pct": -1.0,
                "turnover_median_20d": 200_000_000.0,
                "causal_rank": 1,
                "baseline_rank": 2,
            },
            {
                "cycle_id": "C1",
                "trade_date": pd.Timestamp("2025-01-10"),
                "vt_symbol": "600002.SSE",
                "main_rise_alive": True,
                "ignition_precedes_concept": True,
                "first_strong_sessions_ago_10d": 6,
                "last_strong_sessions_ago_10d": 0,
                "strong_days_10": 3,
                "stock_excess_concept_10d_pct": 12.0,
                "distance_from_prior_high_pct": 0.0,
                "turnover_median_20d": 180_000_000.0,
                "causal_rank": 2,
                "baseline_rank": 1,
            },
            {
                "cycle_id": "C1",
                "trade_date": pd.Timestamp("2025-01-10"),
                "vt_symbol": "600003.SSE",
                "main_rise_alive": False,
                "ignition_precedes_concept": True,
                "first_strong_sessions_ago_10d": 7,
                "last_strong_sessions_ago_10d": 1,
                "strong_days_10": 2,
                "stock_excess_concept_10d_pct": 8.0,
                "distance_from_prior_high_pct": -2.0,
                "turnover_median_20d": 160_000_000.0,
                "causal_rank": 3,
                "baseline_rank": 3,
            },
            {
                "cycle_id": "C1",
                "trade_date": pd.Timestamp("2025-01-10"),
                "vt_symbol": "600004.SSE",
                "main_rise_alive": False,
                "ignition_precedes_concept": True,
                "first_strong_sessions_ago_10d": 7,
                "last_strong_sessions_ago_10d": 1,
                "strong_days_10": 1,
                "stock_excess_concept_10d_pct": 20.0,
                "distance_from_prior_high_pct": 1.0,
                "turnover_median_20d": 300_000_000.0,
                "causal_rank": 4,
                "baseline_rank": 4,
            },
        ]
    )


def test_active_consensus_prioritizes_repeat_and_recent_strength() -> None:
    ranks = rank_active_consensus(_candidate_features())

    assert ranks.loc[ranks["active_consensus_rank"].eq(1), "vt_symbol"].item() == "600002.SSE"
    assert int(ranks["active_consensus_top3"].sum()) == 3


def test_active_consensus_rejects_truth_and_future_columns() -> None:
    with pytest.raises(ValueError, match="truth|future"):
        rank_active_consensus(_candidate_features().assign(truth_rank=1))


def test_decisive_reason_uses_top3_inclusion_boundary() -> None:
    rows = build_decisive_miss_reasons(_cycle_rows("2025-01-10"), _candidate_features())

    assert rows.loc[0, "causal_top3_cutoff_symbol"] == "600003.SSE"
    assert rows.loc[0, "decisive_miss_reason"] == "truth_fewer_strong_days_10"


def test_frozen_candidate_rebuild_requires_exact_causal_top3() -> None:
    frozen = build_frozen_truth_ledger(_prior_report()).loc[
        lambda rows: rows["cycle_id"].eq("C1")
    ]
    candidates = rank_active_consensus(
        _candidate_features().assign(sector_id="BK0001")
    )

    validate_frozen_candidate_rebuild(candidates, frozen)

    changed = candidates.copy()
    changed.loc[changed["vt_symbol"].eq("600004.SSE"), "causal_rank"] = 3
    changed.loc[changed["vt_symbol"].eq("600003.SSE"), "causal_rank"] = 4
    with pytest.raises(ValueError, match="causal Top3"):
        validate_frozen_candidate_rebuild(changed, frozen)


def test_mismatch_category_separates_unknown_relation_from_ranking_failure() -> None:
    rows = pd.concat(
        [
            _cycle_rows().assign(
                truth_relation_status="reason_source_unavailable",
                truth_top1_concept_count_same_date=1,
                near_duplicate_board=False,
            ),
            _cycle_rows().assign(
                cycle_id="C2",
                truth_relation_status="reason_confirmed_precycle",
                truth_top1_concept_count_same_date=1,
                near_duplicate_board=False,
            ),
        ],
        ignore_index=True,
    )

    classified = classify_mismatch_categories(rows)

    assert classified["mismatch_category"].tolist() == [
        "relation_or_board_data_risk",
        "credible_relation_ranking_failure",
    ]
    assert classified.loc[0, "relation_board_risk_reasons"] == (
        "reason_source_unavailable",
    )


def _truth_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": "C1",
                "trade_date": pd.Timestamp("2025-01-10"),
                "vt_symbol": symbol,
                "truth_rank": rank,
            }
            for rank, symbol in enumerate(
                ("600004.SSE", "600002.SSE", "600003.SSE"),
                start=1,
            )
        ]
    )


def test_mode_metrics_use_identical_frozen_cycles() -> None:
    candidates = rank_active_consensus(_candidate_features())
    metrics = evaluate_mismatch_rank_modes(candidates, _truth_rows(), block_count=1)
    pooled = metrics.loc[metrics["segment"].eq("all")]

    assert pooled.groupby("mode")["qualified_cycles"].first().nunique() == 1
    assert set(pooled["mode"]) == {
        "causal_leadership",
        "active_consensus",
        "ten_day_excess_baseline",
    }


def test_active_consensus_decision_never_selects_formal_mode() -> None:
    candidates = rank_active_consensus(_candidate_features())
    metrics = evaluate_mismatch_rank_modes(candidates, _truth_rows(), block_count=1)
    decision = evaluate_active_consensus(metrics)

    assert decision["formal_selected_mode"] is None
    assert decision["identity_accuracy_gate_passed"] is False


def test_report_keeps_ledgers_and_active_consensus_exploratory() -> None:
    prior_report = _prior_report()
    frozen_truth = build_frozen_truth_ledger(prior_report).loc[
        lambda rows: rows["cycle_id"].eq("C1")
    ].reset_index(drop=True)
    cycle_rows = build_cycle_audit_rows(frozen_truth)
    candidates = rank_active_consensus(_candidate_features())
    relation_rows = attach_relation_risk(
        cycle_rows,
        _relations("2025-01-03"),
        trading_dates=tuple(pd.bdate_range("2024-12-01", "2025-01-10").date),
        source_start=date(2025, 1, 1),
    )
    audited = classify_mismatch_categories(
        attach_board_risk(
            relation_rows,
            pd.DataFrame(
                [
                    {"sector_id": "BK0001", "vt_symbol": symbol}
                    for symbol in candidates["vt_symbol"]
                ]
            ),
        )
    )
    misses = build_decisive_miss_reasons(audited, candidates)
    metrics = evaluate_mismatch_rank_modes(candidates, frozen_truth, block_count=1)
    decision = evaluate_active_consensus(metrics)
    inputs = TrueLeaderMismatchInputs(
        prior_report=prior_report,
        frozen_truth=frozen_truth,
        cycle_rows=cycle_rows,
        candidates=candidates,
        memberships=pd.DataFrame(),
        reason_relations=pd.DataFrame(),
        trading_dates=tuple(pd.bdate_range("2024-12-01", "2025-01-10").date),
        coverage={"reason_event_source_start": "2025-01-01"},
        fingerprints={},
    )

    report = build_mismatch_report(
        inputs,
        cycle_audit=audited,
        miss_rows=misses,
        metrics=metrics,
        decision=decision,
    )

    assert report["formal_selected_mode"] is None
    assert report["low_suction_outcomes_read"] is False
    assert report["coverage"]["audited_cycles"] == 1
    assert report["coverage"]["mismatch_cycles"] == 1
    assert len(report["cycle_audit"]) == 1
    assert len(report["mismatch_ledger"]) == 1
    assert json.loads(render_mismatch_study_json(report))["study_version"] == (
        "true-leader-mismatch-audit-v1"
    )
    assert "真龙头漏抓审计" in render_mismatch_study_markdown(report)


def test_cli_registers_true_leader_mismatch_study() -> None:
    args = build_parser().parse_args(["v2-true-leader-mismatch-study"])

    assert args.command == "v2-true-leader-mismatch-study"
