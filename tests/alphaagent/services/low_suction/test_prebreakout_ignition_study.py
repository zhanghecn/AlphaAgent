from __future__ import annotations

import json

import pandas as pd

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.prebreakout_ignition_study import (
    build_prebreakout_report,
    evaluate_recent_fund_pair_coverage,
    render_prebreakout_json,
    render_prebreakout_markdown,
)


def test_report_is_exploratory_and_reads_no_trade_outcomes() -> None:
    report = build_prebreakout_report(**_report_arguments())
    serialized = json.dumps(report, ensure_ascii=False).lower()

    assert report["research_status"] == "exploratory_not_frozen"
    assert report["frozen_parameters"] == []
    assert report["tables_read"]["low_suction_outcomes"] == 0
    assert report["membership_evidence"] == "current_membership_survivorship_proxy"
    assert "win_rate" not in serialized
    assert "compound_return" not in serialized


def test_markdown_distinguishes_prediction_from_historical_conditioning() -> None:
    report = build_prebreakout_report(**_report_arguments())

    text = render_prebreakout_markdown(report)
    payload = json.loads(render_prebreakout_json(report))

    assert "同概念匹配对照" in text
    assert "不能证明因果带动" in text
    assert "未冻结" in text
    assert "突破前" in text
    assert "本轮发现" in text
    assert "五时段稳定性" in text
    assert "40 / 0.6100" in text
    assert payload["research_status"] == "exploratory_not_frozen"


def test_recent_fund_coverage_does_not_read_flow_values() -> None:
    observations = _observations()
    leaders = _early_leaders()
    sector_flows = pd.DataFrame(
        {
            "sector_id": ["BK001", "BK001"],
            "trade_date": pd.to_datetime(["2025-01-06", "2025-01-13"]),
            "main_net_inflow": [1.0, 2.0],
        }
    )
    stock_flows = pd.DataFrame(
        {
            "vt_symbol": ["600001.SSE", "600002.SSE"],
            "trade_date": pd.to_datetime(["2025-01-06", "2025-01-13"]),
            "main_net_inflow": [3.0, 4.0],
        }
    )

    baseline = evaluate_recent_fund_pair_coverage(
        observations,
        leaders,
        sector_flows,
        stock_flows,
    )
    changed = evaluate_recent_fund_pair_coverage(
        observations,
        leaders,
        sector_flows.assign(main_net_inflow=[-1e12, 1e12]),
        stock_flows.assign(main_net_inflow=[1e12, -1e12]),
    )

    assert baseline == changed
    assert baseline["joint_matched_pairs"] == 1
    assert baseline["flow_values_used"] is False
    assert baseline["historical_feature_selection_eligible"] is False


def test_cli_registers_prebreakout_ignition_study() -> None:
    args = build_parser().parse_args(
        ["v2-prebreakout-ignition-study", "--format", "json"]
    )

    assert args.command == "v2-prebreakout-ignition-study"
    assert args.format == "json"


def _report_arguments() -> dict[str, object]:
    return {
        "coverage": {
            "concept_bar_rows": 100,
            "concepts": 2,
            "concept_start": "2024-01-02",
            "concept_end": "2025-01-02",
            "current_membership_rows": 8,
            "strict_historical_membership_rows": 0,
            "stock_bar_rows": 400,
            "stock_symbols": 8,
            "sector_fund_flow_rows": 2,
            "stock_fund_flow_rows": 2,
            "breakout_transition_events": 20,
            "matched_pairs": 16,
        },
        "fingerprints": {},
        "feature_metrics": pd.DataFrame(_feature_metric_rows()),
        "feature_diagnostics": [
            {
                "lead_days": 5,
                "feature": "ignition_share_5d_pct",
                "pooled_pairs": 200,
                "pooled_rank_auc": 0.62,
                "stable_blocks": 5,
                "all_blocks_sufficient": True,
                "status": "candidate_for_forward_validation",
            }
        ],
        "diffusion_metrics": pd.DataFrame(
            [
                {
                    "lead_days": 5,
                    "future_days": 5,
                    "scope": "pooled",
                    "pairs": 14,
                    "positive_follower_median_return_pct": 4.0,
                    "control_follower_median_return_pct": 1.0,
                    "median_follower_return_difference_pct": 3.0,
                    "positive_follower_breadth_pct": 60.0,
                    "control_follower_breadth_pct": 50.0,
                    "median_follower_breadth_difference_pct_points": 10.0,
                    "positive_leader_retained_top1_rate_pct": 40.0,
                    "control_leader_retained_top1_rate_pct": 30.0,
                    "positive_leader_retained_top3_rate_pct": 70.0,
                    "control_leader_retained_top3_rate_pct": 60.0,
                    "positive_leader_gain_follower_return_spearman": 0.2,
                }
            ]
        ),
        "recent_fund_coverage": {
            "selection_role": "coverage_only",
            "sector_trade_dates": 2,
            "stock_trade_dates": 2,
            "sector_matched_pairs": 1,
            "stock_early_leader_matched_pairs": 1,
            "joint_matched_pairs": 1,
            "minimum_pairs_for_separate_analysis": 30,
            "separate_analysis_eligible": False,
            "historical_feature_selection_eligible": False,
            "flow_values_used": False,
        },
        "matched_examples": [
            {
                "pair_id": "pair-1",
                "lead_days": 5,
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "breakout_date": "2025-01-20T00:00:00",
                "positive_observation_date": "2025-01-13T00:00:00",
                "control_observation_date": "2025-01-06T00:00:00",
                "positive_early_leader_symbol": "600001.SSE",
                "control_early_leader_symbol": "600002.SSE",
            }
        ],
    }


def _feature_metric_rows() -> list[dict[str, object]]:
    rows = [
        {
            "lead_days": 5,
            "feature": "ignition_share_5d_pct",
            "scope": "pooled",
            "pairs": 200,
            "positive_median": 30.0,
            "control_median": 20.0,
            "median_paired_difference": 10.0,
            "matched_positive_higher_rate_pct": 65.0,
            "rank_auc": 0.62,
        }
    ]
    rows.extend(
        {
            "lead_days": 5,
            "feature": "ignition_share_5d_pct",
            "scope": f"block_{block}",
            "pairs": 40,
            "positive_median": 30.0,
            "control_median": 20.0,
            "median_paired_difference": 10.0,
            "matched_positive_higher_rate_pct": 65.0,
            "rank_auc": 0.61,
        }
        for block in range(1, 6)
    )
    return rows


def _observations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pair_id": ["pair-1", "pair-1"],
            "sample_role": ["positive", "control"],
            "sector_id": ["BK001", "BK001"],
            "observation_date": pd.to_datetime(["2025-01-06", "2025-01-13"]),
        }
    )


def _early_leaders() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pair_id": ["pair-1", "pair-1"],
            "sample_role": ["positive", "control"],
            "observation_date": pd.to_datetime(["2025-01-06", "2025-01-13"]),
            "vt_symbol": ["600001.SSE", "600002.SSE"],
            "early_leader": [True, True],
        }
    )
