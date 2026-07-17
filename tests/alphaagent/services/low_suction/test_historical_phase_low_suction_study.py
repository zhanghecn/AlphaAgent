from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import (
    historical_phase_low_suction_study as study,
)
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.historical_phase_low_suction_study import (
    attach_phase_cohort_outcomes,
    build_historical_phase_report,
    build_historical_phase_metrics,
    build_phase_transition_cohort_trades,
    build_phase_cohort_membership,
    classify_pullback_depth,
    classify_signal_time,
    evaluate_historical_phase_cohorts,
    join_historical_phase_trades,
    render_historical_phase_json,
    render_historical_phase_markdown,
    run_historical_phase_low_suction_study,
)


def _outcome_trades() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": f"event-{index}",
                "vt_symbol": symbol,
                "entry_date": date(2025, 7, 1 + index),
                "block": 1,
                "normal_status": "closed",
                "net_return_pct": value,
                "double_cost_net_return_pct": value - 0.3,
                "leader_rank_group": "rank_1",
                "market_regime": "GOLD/NORMAL",
                "intraday_volume_class": "normal",
                "intraday_volume_ratio": 0.8,
                "signal_minutes_from_open": 20,
                "distance_to_previous_close_pct": -0.5,
            }
            for index, (symbol, value) in enumerate(
                (("000001.SZSE", 1.0), ("000002.SZSE", -1.0), ("000003.SZSE", 2.0))
            )
        ]
    )


def _phase_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "entry_date": "2025-07-01",
                "block": 1,
                "phase": "healthy_pullback",
                "phase_reason": "test",
                "phase_feature_complete": True,
                "feature_cutoff_date": date(2025, 6, 30),
                "volume_class": "contraction",
                "relative_strength_state": "improving_positive",
                "stock_close": 10.0,
                "ma5": 9.8,
                "ma10": 9.5,
                "ma20": 9.0,
                "stock_daily_return_pct": -1.0,
                "stock_return_3d_pct": 3.0,
                "stock_return_5d_pct": 5.0,
                "volume_to_prior_5d_ratio": 0.7,
                "stock_excess_concept_3d_pct": 2.0,
                "stock_excess_concept_3d_change_pct": 1.0,
                "stock_excess_market_3d_pct": 2.5,
            },
            {
                "vt_symbol": "000002.SZSE",
                "entry_date": "2025-07-02",
                "block": 2,
                "phase": "climax_risk",
                "phase_reason": "test",
                "phase_feature_complete": True,
                "feature_cutoff_date": date(2025, 7, 1),
                "volume_class": "explosion",
                "relative_strength_state": "positive_not_improving",
                "stock_close": 12.0,
                "ma5": 11.0,
                "ma10": 10.0,
                "ma20": 9.0,
                "stock_daily_return_pct": 9.8,
                "stock_return_3d_pct": 25.0,
                "stock_return_5d_pct": 35.0,
                "volume_to_prior_5d_ratio": 3.0,
                "stock_excess_concept_3d_pct": 10.0,
                "stock_excess_concept_3d_change_pct": -2.0,
                "stock_excess_market_3d_pct": 15.0,
            },
        ]
    )


def test_join_retains_unmatched_outcomes_and_reports_coverage() -> None:
    merged, coverage = join_historical_phase_trades(
        _outcome_trades(),
        _phase_panel(),
    )

    assert coverage == {
        "outcome_trades": 3,
        "matched_phase_trades": 2,
        "unmatched_phase_trades": 1,
    }
    assert len(merged) == 3
    assert merged["phase_matched"].tolist() == [True, True, False]
    assert merged.loc[merged["phase_matched"], "phase"].notna().all()


def test_join_rejects_duplicate_phase_identity() -> None:
    duplicated = pd.concat([_phase_panel(), _phase_panel().iloc[[0]]])

    with pytest.raises(ValueError, match="phase identities must be unique"):
        join_historical_phase_trades(_outcome_trades(), duplicated)


def test_join_rejects_future_or_outcome_phase_features() -> None:
    leaked = _phase_panel().assign(future_return_pct=99.0)

    with pytest.raises(ValueError, match="future or outcome"):
        join_historical_phase_trades(_outcome_trades(), leaked)


def test_frozen_entry_buckets_have_explicit_boundaries() -> None:
    assert classify_signal_time(30) == "opening_30"
    assert classify_signal_time(31) == "morning_31_120"
    assert classify_signal_time(120) == "morning_31_120"
    assert classify_signal_time(121) == "afternoon_121_plus"
    assert classify_pullback_depth(0.0) == "shallow_0_1"
    assert classify_pullback_depth(-1.0) == "shallow_0_1"
    assert classify_pullback_depth(-1.01) == "moderate_1_3"
    assert classify_pullback_depth(-3.0) == "moderate_1_3"
    assert classify_pullback_depth(-3.01) == "deep_3_plus"


def test_cohort_membership_uses_phase_plus_at_most_one_causal_condition() -> None:
    merged, _coverage = join_historical_phase_trades(
        _outcome_trades(),
        _phase_panel(),
    )

    membership = build_phase_cohort_membership(merged)
    mutated = build_phase_cohort_membership(
        merged.assign(net_return_pct=[99.0, -99.0, 50.0])
    )

    assert len(membership) == 16
    assert membership.groupby("event_id").size().eq(8).all()
    assert not {
        "net_return_pct",
        "double_cost_net_return_pct",
        "outcome_group",
    } & set(membership.columns)
    assert membership["condition_count"].isin((1, 2)).all()
    pd.testing.assert_frame_equal(membership, mutated)


def _cohort_rows(
    cohort_key: str,
    *,
    validation_fails: bool,
) -> list[dict[str, object]]:
    dates = tuple(pd.bdate_range("2025-01-02", periods=50).date)
    development_returns = [1.0] * 21 + [-0.5] * 9
    validation_returns = (
        [1.0] * 6 + [-1.0] * 14
        if validation_fails
        else [1.0] * 14 + [-0.5] * 6
    )
    returns = development_returns + validation_returns
    rows = []
    for index, (entry_date, net_return) in enumerate(zip(dates, returns, strict=True)):
        if index < 30:
            block = index % 3 + 1
        else:
            block = index % 2 + 4
        rows.append(
            {
                "event_id": f"{cohort_key}-{index}",
                "entry_date": entry_date,
                "block": block,
                "phase": "healthy_pullback",
                "table_id": "phase_x_test",
                "cohort_key": cohort_key,
                "condition_count": 2,
                "normal_status": "closed",
                "net_return_pct": net_return,
                "double_cost_net_return_pct": net_return - 0.1,
            }
        )
    return rows


def test_time_split_rejects_development_edge_that_fails_validation() -> None:
    cohort_trades = pd.DataFrame(
        _cohort_rows("stable", validation_fails=False)
        + _cohort_rows("fails_late", validation_fails=True)
    )

    metrics = build_historical_phase_metrics(cohort_trades)
    evaluation = evaluate_historical_phase_cohorts(metrics)
    status = evaluation.set_index("cohort_key")["status"].to_dict()

    assert status == {
        "fails_late": "validation_failed",
        "stable": "high_win_confirmed",
    }
    stable_validation = metrics.loc[
        metrics["cohort_key"].eq("stable")
        & metrics["segment"].eq("validation")
    ].iloc[0]
    assert stable_validation["win_rate_pct"] == pytest.approx(70.0)
    assert stable_validation["compound_return_pct"] > 0
    assert stable_validation["maximum_drawdown_pct"] <= 0


def test_outcomes_are_attached_after_membership_identity_is_frozen() -> None:
    merged, _coverage = join_historical_phase_trades(
        _outcome_trades(),
        _phase_panel(),
    )
    membership = build_phase_cohort_membership(merged)

    cohort_trades = attach_phase_cohort_outcomes(membership, merged)

    assert len(cohort_trades) == len(membership)
    assert cohort_trades["net_return_pct"].notna().all()
    assert not cohort_trades.duplicated(
        ["event_id", "table_id", "cohort_key"]
    ).any()


def _small_study_frames() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, object],
]:
    merged, coverage = join_historical_phase_trades(
        _outcome_trades(),
        _phase_panel(),
    )
    merged["outcome_group"] = merged["net_return_pct"].map(
        lambda value: "winner" if value > 0 else "loser"
    )
    membership = build_phase_cohort_membership(merged)
    cohort_trades = attach_phase_cohort_outcomes(membership, merged)
    metrics = build_historical_phase_metrics(cohort_trades)
    evaluation = evaluate_historical_phase_cohorts(metrics)
    metadata: dict[str, object] = {
        "coverage": {
            **coverage,
            "phase_panel_rows": 2,
            "cohort_membership_rows": len(membership),
        },
        "input_fingerprints": {"test": {"sha256": "abc"}},
    }
    return merged, membership, cohort_trades, metrics, evaluation, metadata


def test_historical_report_keeps_formal_and_strict_top3_claims_closed() -> None:
    merged, membership, cohort_trades, metrics, evaluation, metadata = (
        _small_study_frames()
    )

    report = build_historical_phase_report(
        merged,
        membership,
        cohort_trades,
        metrics,
        evaluation,
        metadata,
    )
    payload = render_historical_phase_json(report)
    markdown = render_historical_phase_markdown(report)

    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert report["strict_historical_top3_claim"] is False
    assert report["coverage"]["matched_phase_trades"] == 2
    assert report["cohort_gate_summary"]["stable_positive_expectation_cohorts"] == 0
    assert (
        report["transition_environment_evaluation"][
            "environment_positive_confirmed_cohorts"
        ]
        == 0
    )
    assert '"formal_metrics": null' in payload
    assert "历史事件 Top3 代理" in markdown


def test_run_study_uses_existing_historical_loaders_without_forward_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = _small_study_frames()
    monkeypatch.setattr(study, "load_historical_phase_low_suction_data", lambda: frames)

    report = run_historical_phase_low_suction_study()
    args = build_parser().parse_args(
        ["v2-historical-phase-low-suction-study", "--format", "json"]
    )

    assert report["forward_ledger_rows_read"] == 0
    assert args.command == "v2-historical-phase-low-suction-study"
    assert args.format == "json"


def test_transition_outcomes_join_only_after_frozen_rule_and_phase_identity() -> None:
    normal = pd.DataFrame(
        [
            {
                "transition_id": "transition-1",
                "rule": "vwap_reclaim",
                "vt_symbol": "000001.SZSE",
                "entry_date": date(2025, 7, 1),
                "recognition_rank": 1,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "status": "closed",
                "net_return_pct": 1.2,
            },
            {
                "transition_id": "transition-2",
                "rule": "open_reclaim",
                "vt_symbol": "000002.SZSE",
                "entry_date": date(2025, 7, 2),
                "recognition_rank": 2,
                "active_direction": "SILVER",
                "danger_state": "NORMAL",
                "status": "closed",
                "net_return_pct": -0.8,
            },
        ]
    )
    stressed = normal.loc[:, ["transition_id"]].assign(
        net_return_pct=[0.9, -1.1]
    )

    trades, coverage = build_phase_transition_cohort_trades(
        normal,
        stressed,
        _phase_panel(),
    )

    assert coverage == {
        "transition_outcomes": 2,
        "transition_phase_matched": 2,
        "transition_phase_unmatched": 0,
    }
    assert trades["table_id"].eq("phase_x_transition_rule").all()
    assert trades["condition_count"].eq(2).all()
    assert trades["cohort_key"].tolist() == [
        "phase=healthy_pullback|transition_rule=vwap_reclaim",
        "phase=climax_risk|transition_rule=open_reclaim",
    ]
    assert trades["double_cost_net_return_pct"].tolist() == [0.9, -1.1]
    assert trades["market_regime"].tolist() == ["GOLD/NORMAL", "SILVER/NORMAL"]
    assert trades["leader_rank_group"].tolist() == ["rank_1", "rank_2_3"]


def test_transition_phase_join_rejects_unregistered_rule() -> None:
    normal = pd.DataFrame(
        [
            {
                "transition_id": "transition-1",
                "rule": "fitted_magic_reclaim",
                "vt_symbol": "000001.SZSE",
                "entry_date": date(2025, 7, 1),
                "recognition_rank": 1,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "status": "closed",
                "net_return_pct": 1.2,
            }
        ]
    )
    stressed = normal.loc[:, ["transition_id"]].assign(net_return_pct=[0.9])

    with pytest.raises(ValueError, match="unregistered transition rules"):
        build_phase_transition_cohort_trades(normal, stressed, _phase_panel())


def test_time_split_positive_transition_is_rejected_when_regime_changes() -> None:
    cohort_key = "phase=divergence_restart|transition_rule=vwap_reclaim"
    stable = pd.DataFrame([{"cohort_key": cohort_key}])
    attribution = pd.DataFrame(
        [
            {
                "cohort_key": cohort_key,
                "dimension": "market_regime",
                "value": "GOLD/NORMAL",
                "segment": segment,
                "closed_trades": trades,
                "source_days": days,
                "win_rate_pct": win_rate,
                "mean_net_return_pct": mean_return,
                "profit_factor": profit_factor,
                "double_cost_mean_net_return_pct": double_mean,
            }
            for segment, trades, days, win_rate, mean_return, profit_factor, double_mean in (
                ("development", 47, 30, 40.0, 0.4, 1.2, 0.1),
                ("validation", 16, 8, 31.0, -2.4, 0.4, -2.7),
            )
        ]
    )

    result = study._evaluate_transition_environments(stable, attribution)

    assert result["environment_positive_confirmed_cohorts"] == 0
    assert result["regime_confounded_cohorts"] == 1
    assert result["cohorts"][0]["comparable_regimes"] == ["GOLD/NORMAL"]
