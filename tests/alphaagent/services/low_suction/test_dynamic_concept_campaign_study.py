from __future__ import annotations

import json

import pandas as pd

from alphaagent.server.services.low_suction.dynamic_concept_campaign_study import (
    build_dynamic_campaign_report,
    evaluate_recent_fund_corroboration,
    filter_exploratory_concept_universe,
    render_dynamic_campaign_json,
    render_dynamic_campaign_markdown,
)


def test_recent_fund_track_is_separate_from_historical_selection() -> None:
    report = _report()

    assert report["research_tracks"]["recent_real_fund"]["selection_role"] == (
        "corroboration_only"
    )
    assert report["research_tracks"]["historical_campaign"]["net_inflow_used"] is (
        False
    )


def test_concept_universe_excludes_only_manifest_controls() -> None:
    bars = pd.DataFrame(
        {
            "sector_id": ["BK0816", "BK1637", "BK1158", "BK0800", "BK9999"],
            "concept_name": ["昨日连板", "东方财富热股", "微盘股", "人工智能", "未分类概念"],
            "trade_date": pd.to_datetime(["2025-01-02"] * 5),
        }
    )

    eligible, audit = filter_exploratory_concept_universe(bars)

    assert set(eligible["sector_id"]) == {"BK0800", "BK9999"}
    assert audit["excluded_control_sector_ids"] == ["BK0816", "BK1158", "BK1637"]
    assert audit["retained_unclassified_sectors"] == 1


def test_fund_corroboration_reports_coverage_and_spearman() -> None:
    leaders = _recent_dynamic_leaders()
    overlapping_episode = leaders.loc[leaders["trade_date"].eq("2025-01-02")].assign(
        episode_id="overlapping-episode"
    )
    evidence = evaluate_recent_fund_corroboration(
        _recent_concept_features(),
        _sector_flows(),
        pd.concat([leaders, overlapping_episode], ignore_index=True),
        _stock_flows(),
    )

    assert evidence["sector_trade_dates"] == 3
    assert evidence["stock_trade_dates"] == 3
    assert evidence["historical_selection_eligible"] is False
    assert evidence["sector_return_1d_inflow_spearman"] == 1.0
    assert evidence["stock_gain_top3_inflow_top3_overlap_pct"] == 100.0


def test_fund_corroboration_returns_reason_when_coverage_is_absent() -> None:
    evidence = evaluate_recent_fund_corroboration(
        _recent_concept_features(),
        pd.DataFrame(),
        _recent_dynamic_leaders(),
        pd.DataFrame(),
    )

    assert evidence["sector_return_1d_inflow_spearman"] is None
    assert evidence["stock_gain_top3_inflow_top3_overlap_pct"] is None
    assert "missing" in evidence["sector_status"]
    assert "missing" in evidence["stock_status"]


def test_report_cannot_claim_a_frozen_rule_or_low_suction_profit() -> None:
    report = _report()
    serialized = json.dumps(report, ensure_ascii=False).lower()

    assert report["research_status"] == "exploratory_not_frozen"
    assert report["frozen_parameters"] == []
    assert report["tables_read"]["low_suction_outcomes"] == 0
    assert "win_rate" not in serialized
    assert "compound" not in serialized


def test_renderers_preserve_membership_and_fund_limitations() -> None:
    report = _report()

    markdown = render_dynamic_campaign_markdown(report)
    payload = json.loads(render_dynamic_campaign_json(report))

    assert "当前成员生存偏差代理" in markdown
    assert "近期真实净流入仅作旁证" in markdown
    assert "未冻结" in markdown
    assert payload["research_status"] == "exploratory_not_frozen"


def _report() -> dict[str, object]:
    return build_dynamic_campaign_report(
        coverage={
            "concept_bar_rows": 120,
            "concepts": 3,
            "concept_start": "2024-01-02",
            "concept_end": "2025-01-02",
            "current_membership_rows": 9,
            "strict_historical_membership_rows": 0,
            "stock_bar_rows": 360,
            "stock_symbols": 9,
            "sector_fund_flow_rows": 9,
            "sector_fund_flow_dates": 3,
            "stock_fund_flow_rows": 27,
            "stock_fund_flow_dates": 3,
        },
        fingerprints={},
        campaign_metrics=pd.DataFrame(
            [
                {
                    "anchor_mode": "breakout_20",
                    "exit_drawdown_pct": 5.0,
                    "exit_confirm_sessions": 1,
                    "scope": "pooled",
                    "campaigns": 20,
                    "completed_campaigns": 18,
                    "right_censored_campaigns": 2,
                    "median_campaign_days": 12.0,
                    "median_peak_gain_pct": 8.0,
                    "p75_peak_gain_pct": 12.0,
                    "median_terminal_gain_pct": 2.0,
                    "reach_5pct_rate": 60.0,
                    "reach_10pct_rate": 30.0,
                    "median_days_to_peak": 6.0,
                    "higher_high_within_10_after_end_rate": 25.0,
                    "median_post_end_further_drawdown_pct": -3.0,
                }
            ]
        ),
        campaign_diagnostics=[
            {
                "anchor_mode": "breakout_20",
                "exit_drawdown_pct": 5.0,
                "exit_confirm_sessions": 1,
                "campaigns": 20,
                "pareto_dominated": False,
                "blocks_at_or_above_median_reach": 2,
                "block_count": 5,
                "status": "exploratory_not_selected",
            }
        ],
        leader_metrics=pd.DataFrame(
            [
                {
                    "anchor_mode": "breakout_20",
                    "campaign_day_bucket": "D+5",
                    "scope": "pooled",
                    "leader_mode": "cumulative_gain",
                    "qualified_campaigns": 10,
                    "top1_exact_rate_pct": 30.0,
                    "top3_capture_realized_top1_rate_pct": 60.0,
                    "mean_realized_top3_overlap_pct": 50.0,
                }
            ]
        ),
        recent_fund_evidence={
            "sector_status": "available_short_history",
            "stock_status": "available_short_history",
            "historical_selection_eligible": False,
            "sector_trade_dates": 3,
            "stock_trade_dates": 3,
            "sector_return_1d_inflow_spearman": 1.0,
            "sector_return_5d_inflow_spearman": 0.8,
            "sector_turnover_expansion_inflow_spearman": 0.7,
            "stock_gain_top3_inflow_top3_overlap_pct": 100.0,
            "stock_overlap_groups": 3,
        },
        examples=[
            {
                "label": "high_peak_gain",
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "anchor_date": "2025-01-02",
                "peak_gain_pct": 12.0,
                "terminal_gain_pct": 3.0,
            }
        ],
    )


def _recent_concept_features() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    rows: list[dict[str, object]] = []
    for date_index, trade_date in enumerate(dates):
        for sector_index, sector_id in enumerate(("BK001", "BK002", "BK003")):
            value = float(sector_index + date_index)
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": trade_date,
                    "return_1d_pct": value,
                    "return_5d_pct": value + 1.0,
                    "turnover_expansion": value + 2.0,
                }
            )
    return pd.DataFrame(rows)


def _sector_flows() -> pd.DataFrame:
    features = _recent_concept_features()
    return features.assign(
        period="即时",
        main_net_inflow=features["return_1d_pct"] * 1_000_000.0,
    )[["sector_id", "trade_date", "period", "main_net_inflow"]]


def _recent_dynamic_leaders() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    rows: list[dict[str, object]] = []
    for date_index, trade_date in enumerate(dates):
        for rank in range(1, 5):
            rows.append(
                {
                    "episode_id": f"episode-{date_index}",
                    "sector_id": "BK001",
                    "trade_date": trade_date,
                    "vt_symbol": f"60000{rank}.SSE",
                    "cumulative_gain_rank": rank,
                }
            )
    return pd.DataFrame(rows)


def _stock_flows() -> pd.DataFrame:
    leaders = _recent_dynamic_leaders()
    return leaders.assign(
        period="即时",
        main_net_inflow=(5 - leaders["cumulative_gain_rank"]) * 1_000_000.0,
    )[["vt_symbol", "trade_date", "period", "main_net_inflow"]]
