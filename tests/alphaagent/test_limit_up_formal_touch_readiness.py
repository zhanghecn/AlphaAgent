from datetime import datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.formal_touch_readiness import (
    audit_frozen_research_evidence,
    assess_probability_threshold,
    build_mother_pool,
    build_landmark_rows,
    build_pre_touch_rows,
    chronological_split,
    classify_quality_requirement,
    evaluate_touch_now,
    joint_event_label,
    leave_one_out_concept_metrics,
    pool_fingerprint,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_joint_label_requires_touch_and_formal_quality() -> None:
    assert joint_event_label(later_touched=True, formal_actionable=True) == 1
    assert joint_event_label(later_touched=True, formal_actionable=False) == 0
    assert joint_event_label(later_touched=False, formal_actionable=False) == 0


def test_counterfactual_touch_uses_public_contract() -> None:
    decision = evaluate_touch_now(
        {
            "lane": "first_board",
            "prior_limit_count_126": 3,
            "prior_industry_turnover_ratio_5d": 1.1,
            "stock_d1_sample_count": 5,
            "stock_d1_win_rate": 80.0,
            "stock_d1_average_return_pct": 2.0,
            "stock_gene_combined_win_rate": 40.0,
        },
        datetime(2026, 7, 28, 10, 20, tzinfo=SHANGHAI),
    )

    assert decision["public_quality_contract_version"] == "limit-up-core-abc-v2"
    assert decision["public_quality_trigger_observed"] is True
    assert decision["public_quality_actionable"] is True
    assert decision["quality_entry_effective_time"] == "10:20:00"


def test_quality_requirement_categories_are_explicit() -> None:
    assert classify_quality_requirement("risk_gate") == "mandatory"
    assert classify_quality_requirement("concept_state") == "progressive"
    assert classify_quality_requirement("trigger_not_observed") == "trigger"


def test_mutating_outcomes_does_not_change_mother_pool_membership() -> None:
    static_rows = [
        {
            "trade_date": "2026-07-28",
            "vt_symbol": "600001.SSE",
            "eligible_main_board": True,
            "mandatory_gate_passed": True,
            "prior_history_count": 126,
            "previous_close": 10.0,
            "first_three_pct_at": "2026-07-28T10:01:00+08:00",
        },
        {
            "trade_date": "2026-07-28",
            "vt_symbol": "300001.SZSE",
            "eligible_main_board": False,
            "mandatory_gate_passed": True,
            "prior_history_count": 126,
            "previous_close": 10.0,
            "first_three_pct_at": "2026-07-28T10:02:00+08:00",
        },
    ]
    original = build_mother_pool(static_rows, {"600001.SSE": {"touched": True}})
    mutated = build_mother_pool(static_rows, {"600001.SSE": {"touched": False}})

    assert pool_fingerprint(original) == pool_fingerprint(mutated)
    assert [row["vt_symbol"] for row in original] == ["600001.SSE"]


def test_point_rows_stop_strictly_before_first_touch() -> None:
    observations = [
        {"captured_at": "2026-07-28T10:00:00+08:00", "change_pct": 3.1},
        {"captured_at": "2026-07-28T10:02:00+08:00", "change_pct": 7.0},
        {"captured_at": "2026-07-28T10:03:00+08:00", "change_pct": 10.0},
    ]
    touch_at = datetime(2026, 7, 28, 10, 3, tzinfo=SHANGHAI)

    rows = build_pre_touch_rows(observations, touch_at)

    assert [row["change_pct"] for row in rows] == [3.1, 7.0]
    assert all(row["observed_at"] < touch_at for row in rows)


def test_leave_one_out_removes_candidate_from_available_breadth() -> None:
    result = leave_one_out_concept_metrics(
        {
            "observed_count": 20,
            "rise_count": 12,
            "strong_3_count": 5,
            "strong_5_count": 4,
            "strong_7_count": 3,
            "near_limit_count": 2,
            "average_change_pct": 2.0,
            "median_change_pct": 1.2,
        },
        candidate_change_pct=8.2,
        candidate_near_limit=True,
    )

    assert result["observed_count_ex_self"] == 19
    assert result["rise_count_ex_self"] == 11
    assert result["strong_3_count_ex_self"] == 4
    assert result["strong_5_count_ex_self"] == 3
    assert result["strong_7_count_ex_self"] == 2
    assert result["near_limit_count_ex_self"] == 1
    assert result["average_change_pct_ex_self"] == 1.673684
    assert result["median_change_pct_ex_self"] is None


def test_chronological_split_has_no_overlap() -> None:
    dates = [f"2026-01-{day:02d}" for day in range(1, 32)] + [
        f"2026-02-{day:02d}" for day in range(1, 18)
    ]

    split = chronological_split(dates)

    assert len(split.fit) >= 20
    assert len(split.calibration) >= 10
    assert len(split.validation) >= 10
    assert max(split.fit) < min(split.calibration)
    assert max(split.calibration) < min(split.validation)
    assert not (set(split.fit) & set(split.calibration) & set(split.validation))


def test_landmarks_are_strictly_pre_touch_and_use_early_entry_price() -> None:
    candidate = {
        "trade_date": "2026-07-28",
        "vt_symbol": "600001.SSE",
        "name": "样例",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "d1_close_price": 11.2,
        "lane": "first_board",
        "prior_limit_count_126": 3,
        "prior_industry_turnover_ratio_5d": 1.1,
        "stock_d1_sample_count": 5,
        "stock_d1_win_rate": 80.0,
        "stock_d1_average_return_pct": 2.0,
        "stock_gene_combined_win_rate": 40.0,
    }
    minute_rows = [
        {"bar_time": "2026-07-28T10:01:00", "close_price": 10.3, "high_price": 10.3, "volume": 100, "turnover": 1030},
        {"bar_time": "2026-07-28T10:02:00", "close_price": 10.5, "high_price": 10.5, "volume": 150, "turnover": 1575},
        {"bar_time": "2026-07-28T10:03:00", "close_price": 10.7, "high_price": 10.7, "volume": 250, "turnover": 2675},
        {"bar_time": "2026-07-28T10:04:00", "close_price": 11.0, "high_price": 11.0, "volume": 400, "turnover": 4400},
    ]

    rows = build_landmark_rows(
        candidate,
        minute_rows,
        formal_actionable=True,
    )

    assert [row["landmark_change_pct"] for row in rows] == [3.0, 5.0, 7.0]
    assert [row["lead_minutes"] for row in rows] == [3, 2, 1]
    assert all(row["joint_event_label"] == 1 for row in rows)
    assert rows[0]["early_entry_d1_net_return_pct"] > rows[0]["formal_d1_net_return_pct"]
    assert all(row["observed_at"] < row["physical_touch_at"] for row in rows)


def test_probability_threshold_requires_calibration_quality_and_lead_time() -> None:
    decision = assess_probability_threshold(
        {
            "sample_count": 31,
            "precision": 0.66,
            "recall": 0.35,
            "median_lead_minutes": 3.0,
            "d1_win_rate": 0.62,
            "d1_mean_net_return_pct": 0.8,
            "beats_base_rate": True,
            "beats_shuffled_control": True,
        },
        displayed_probability=0.70,
    )

    assert decision["eligible"] is True


def test_probability_threshold_rejects_an_empty_high_probability_bucket() -> None:
    decision = assess_probability_threshold(
        {
            "sample_count": 0,
            "precision": None,
            "recall": 0.0,
            "median_lead_minutes": None,
            "d1_win_rate": None,
            "d1_mean_net_return_pct": None,
            "beats_base_rate": False,
            "beats_shuffled_control": False,
        },
        displayed_probability=0.60,
    )

    assert decision["eligible"] is False
    assert "sample_count" in decision["failed_checks"]
    assert "calibrated_precision" in decision["failed_checks"]


def test_frozen_evidence_audit_rejects_uncalibrated_thresholds() -> None:
    audit = audit_frozen_research_evidence(
        {
            "decision": "REJECT/INSUFFICIENT",
            "target": "later_physical_touch_and_formal_buy_now",
            "ablations": {
                "Q+M+F": {
                    "beats_base_rate_brier": True,
                    "beats_shuffled_pr_auc": True,
                    "threshold_80": {
                        "sample_count": 61,
                        "precision": 0.4754,
                        "recall": 0.4754,
                        "median_lead_minutes": 5.0,
                        "d1_win_rate": 0.4754,
                        "d1_mean_net_return_pct": 0.73,
                    },
                }
            },
            "strict_concept": {
                "fit_trade_date_count": 0,
                "calibration_trade_date_count": 0,
                "validation_trade_date_count": 2,
                "minimum_required": {
                    "fit": 20,
                    "calibration": 10,
                    "validation": 10,
                },
            },
        }
    )

    assert audit["product_eligible"] is False
    assert audit["eligible_threshold_count"] == 0
    assert audit["frozen_decision_consistent"] is True
    assert audit["reason_codes"] == [
        "strict_concept_coverage_insufficient",
        "no_probability_threshold_passed",
    ]
