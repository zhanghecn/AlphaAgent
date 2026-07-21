from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.multi_wave_rank_trajectory_study import (
    RANK_TRAJECTORY_FEATURES,
    RankTrajectoryResult,
    attach_rank_trajectory_classes,
    build_rank_trajectory_report,
    build_multi_wave_rank_trajectory,
    classify_rank_trajectory,
    evaluate_rank_trajectory_features,
    render_rank_trajectory_json,
    render_rank_trajectory_markdown,
    summarize_rank_trajectory_classes,
)
from alphaagent.server.services.low_suction.cli import build_parser


def _trajectory_fixture() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    tuple[date, ...],
]:
    path_dates = pd.bdate_range("2025-01-02", periods=6)
    history_dates = pd.bdate_range(end=path_dates[-1], periods=36)
    labels = pd.DataFrame(
        [
            {
                "episode_id": "episode-a",
                "cohort": "dynamic_causal_top3_proxy",
                "vt_symbol": "600001.SSE",
                "stock_name": "龙头甲",
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "anchor_date": path_dates[0],
                "first_peak_date": path_dates[2],
                "first_trough_date": path_dates[3],
                "decision_date": path_dates[5],
                "feature_cutoff_date": path_dates[5],
                "second_wave_status": "continued_to_higher_high",
                "multi_wave_leader": True,
            }
        ]
    )
    symbols = ("600001.SSE", "600002.SSE", "000001.SZSE", "000002.SZSE")
    memberships = pd.DataFrame(
        [{"sector_id": "BK001", "vt_symbol": symbol} for symbol in symbols]
    )
    path_closes = {
        "600001.SSE": (10.0, 11.0, 12.0, 11.0, 12.5, 14.0),
        "600002.SSE": (10.0, 10.5, 11.0, 11.2, 11.5, 12.0),
        "000001.SZSE": (10.0, 10.2, 10.4, 10.5, 10.8, 11.0),
        "000002.SZSE": (10.0, 10.1, 10.3, 10.4, 10.6, 10.9),
    }
    path_positions = {trade_date: index for index, trade_date in enumerate(path_dates)}
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        for history_index, trade_date in enumerate(history_dates):
            path_position = path_positions.get(trade_date)
            close = (
                path_closes[symbol][path_position]
                if path_position is not None
                else 9.0 + symbol_index * 0.1 + history_index * 0.01
            )
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "close_price": close,
                    "turnover": 1_000_000.0
                    + symbol_index * 100_000.0
                    + history_index * 10_000.0,
                }
            )
    stock_bars = pd.DataFrame(rows)
    missing_date = path_dates[3]
    stock_bars = stock_bars.loc[
        ~(
            stock_bars["vt_symbol"].eq("000002.SZSE")
            & stock_bars["trade_date"].eq(missing_date)
        )
    ].reset_index(drop=True)
    return labels, memberships, stock_bars, tuple(path_dates.date)


def test_rank_trajectory_uses_one_fixed_complete_member_denominator() -> None:
    labels, memberships, stock_bars, trading_dates = _trajectory_fixture()

    result = build_multi_wave_rank_trajectory(
        labels,
        memberships,
        stock_bars,
        trading_dates=trading_dates,
    )

    assert set(result.member_ledger["member_vt_symbol"]) == {
        "600001.SSE",
        "600002.SSE",
        "000001.SZSE",
    }
    assert result.daily_path["member_count"].eq(3).all()
    decision = result.daily_path.loc[result.daily_path["decision_date_row"]].iloc[0]
    assert decision["gain_rank"] == 1
    assert decision["rank_strength_pct"] == 100.0
    assert result.panel.iloc[0]["leader_path_top1_share_pct"] == 80.0
    assert result.panel.iloc[0]["leader_path_top3_share_pct"] == 100.0
    assert result.panel.iloc[0]["leader_top3_streak_to_decision_sessions"] == 5.0
    assert result.panel.iloc[0]["feature_complete"]
    assert pd.to_numeric(
        result.panel.loc[:, list(RANK_TRAJECTORY_FEATURES)].iloc[0]
    ).notna().all()


def test_post_decision_bars_cannot_change_rank_trajectory() -> None:
    labels, memberships, stock_bars, trading_dates = _trajectory_fixture()
    original = build_multi_wave_rank_trajectory(
        labels,
        memberships,
        stock_bars,
        trading_dates=trading_dates,
    )
    future_date = pd.Timestamp(trading_dates[-1]) + pd.offsets.BDay(1)
    future = pd.DataFrame(
        [
            {
                "vt_symbol": symbol,
                "trade_date": future_date,
                "close_price": 999.0 - index,
                "turnover": 999_000_000.0,
            }
            for index, symbol in enumerate(memberships["vt_symbol"])
        ]
    )

    changed = build_multi_wave_rank_trajectory(
        labels,
        memberships,
        pd.concat([stock_bars, future], ignore_index=True),
        trading_dates=(*trading_dates, future_date.date()),
    )

    compared = ["episode_id", "feature_cutoff_date", *RANK_TRAJECTORY_FEATURES]
    pd.testing.assert_frame_equal(original.panel[compared], changed.panel[compared])


def test_rank_trajectory_rejects_a_future_feature_cutoff() -> None:
    labels, memberships, stock_bars, trading_dates = _trajectory_fixture()
    labels.loc[0, "feature_cutoff_date"] = pd.Timestamp(trading_dates[-1]) + pd.Timedelta(
        days=1
    )

    with pytest.raises(ValueError, match="feature cutoff"):
        build_multi_wave_rank_trajectory(
            labels,
            memberships,
            stock_bars,
            trading_dates=trading_dates,
        )


@pytest.mark.parametrize(
    (
        "path_top3",
        "recovery_top3",
        "decision_strength",
        "expected",
    ),
    [
        (80.0, 80.0, 80.0, "persistent_leader"),
        (100.0, 100.0, 49.999, "lost_leadership"),
        (79.999, 79.999, 70.0, "mixed_trajectory"),
        (100.0, 49.999, 100.0, "lost_leadership"),
    ],
)
def test_rank_trajectory_classes_use_only_predeclared_boundaries(
    path_top3: float,
    recovery_top3: float,
    decision_strength: float,
    expected: str,
) -> None:
    assert (
        classify_rank_trajectory(
            path_top3_share_pct=path_top3,
            recovery_top3_share_pct=recovery_top3,
            decision_strength_pct=decision_strength,
        )
        == expected
    )


def _diagnostic_panel() -> pd.DataFrame:
    rows = []
    for block in range(1, 6):
        for row_index in range(100):
            persistent = row_index >= 50
            within_group = row_index - 50 if persistent else row_index
            positive_limit = 35 if block <= 3 else 33
            negative_group_positive_limit = 15 if block <= 3 else 17
            positive = within_group < (
                positive_limit if persistent else negative_group_positive_limit
            )
            row = {
                "episode_id": f"block-{block}-{row_index}",
                "decision_date": pd.Timestamp("2025-01-01")
                + pd.Timedelta(days=block),
                "block": block,
                "multi_wave_leader": positive,
                "feature_complete": True,
            }
            row.update(dict.fromkeys(RANK_TRAJECTORY_FEATURES, 0.0))
            row["leader_path_top3_share_pct"] = 90.0 if persistent else 30.0
            row["leader_recovery_top3_share_pct"] = 90.0 if persistent else 30.0
            row["leader_decision_strength_pct"] = 90.0 if persistent else 30.0
            rows.append(row)
    return attach_rank_trajectory_classes(pd.DataFrame(rows))


def test_direction_frozen_auc_gate_requires_all_registered_stability_checks() -> None:
    metrics = evaluate_rank_trajectory_features(_diagnostic_panel())
    top3 = metrics.loc[
        metrics["feature"].eq("leader_path_top3_share_pct")
    ].iloc[0]

    assert top3["direction"] == "higher"
    assert top3["development_directional_auc"] == pytest.approx(0.70)
    assert top3["block_4_directional_auc"] == pytest.approx(0.66)
    assert top3["block_5_directional_auc"] == pytest.approx(0.66)
    assert top3["stable_blocks"] == 5
    assert top3["candidate_for_new_forward_block"]


def test_trajectory_class_summary_keeps_pooled_and_block_rows_separate() -> None:
    summary = summarize_rank_trajectory_classes(_diagnostic_panel())
    pooled = summary.loc[summary["scope"].eq("pooled")].set_index(
        "trajectory_class"
    )

    assert pooled.loc["persistent_leader", "rows"] == 250
    assert pooled.loc["persistent_leader", "continuation_share_pct"] == pytest.approx(
        68.4
    )
    assert pooled.loc["lost_leadership", "rows"] == 250
    assert pooled.loc["lost_leadership", "continuation_share_pct"] == pytest.approx(
        31.6
    )
    assert set(summary["scope"]) == {
        "pooled",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    }


def test_report_keeps_reused_proxy_diagnostics_separate_from_formal_metrics() -> None:
    panel = _diagnostic_panel()
    result = RankTrajectoryResult(
        panel=panel,
        daily_path=pd.DataFrame(),
        member_ledger=pd.DataFrame(),
        exclusions=pd.DataFrame(),
    )
    diagnostics = evaluate_rank_trajectory_features(panel)
    class_summary = summarize_rank_trajectory_classes(panel)

    report = build_rank_trajectory_report(
        result=result,
        diagnostics=diagnostics,
        class_summary=class_summary,
        new_information_coverage={
            "stock_fund_flow_dates": 27,
            "stock_fund_flow_label_overlap_dates": 0,
            "sector_fund_flow_dates": 21,
            "sector_fund_flow_label_overlap_dates": 0,
            "membership_snapshot_dates": 5,
            "membership_snapshot_label_overlap_dates": 0,
        },
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
    )

    assert report["research_status"] == (
        "exploratory_candidate_requires_new_forward_block"
    )
    assert report["validation_status"] == "reused_history_not_validation"
    assert report["membership_evidence"] == (
        "current_membership_and_security_proxy"
    )
    assert report["formal_metrics"] == {
        "win_rate_pct": None,
        "compounded_return_pct": None,
        "profit_factor": None,
        "maximum_drawdown_pct": None,
    }
    rendered_json = render_rank_trajectory_json(report)
    rendered_markdown = render_rank_trajectory_markdown(report)
    assert render_rank_trajectory_json(report) == rendered_json
    assert '"formal_metrics"' in rendered_json
    assert "正式低吸胜率、收益、复利：`null`" in rendered_markdown


def test_cli_accepts_multi_wave_rank_trajectory_study() -> None:
    args = build_parser().parse_args(
        ["v2-multi-wave-rank-trajectory-study", "--format", "json"]
    )

    assert args.command == "v2-multi-wave-rank-trajectory-study"
    assert args.format == "json"
