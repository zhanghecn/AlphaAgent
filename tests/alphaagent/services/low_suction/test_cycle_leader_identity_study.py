from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cycle_leader_identity_study import (
    build_cycle_leader_identity_report,
    build_cycle_identity_metrics,
    build_cycle_identity_labels,
    build_cycle_identity_mode_ranks,
    build_selected_mode_dynamic_identity,
    evaluate_cycle_identity_modes,
    execute_identity_gated_pullback,
    render_cycle_leader_identity_json,
    render_cycle_leader_identity_markdown,
    run_cycle_leader_identity_study,
)
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.leader_identity import LeaderIdentityMode
from alphaagent.server.services.low_suction import cycle_leader_identity_study as study


CYCLE_ID = "breakout_trend:BK0001:2025-01-02"
ENTRY_DATES = tuple(pd.bdate_range("2025-01-06", periods=3))


def _dynamic_candidates(*, entry_dates: tuple[pd.Timestamp, ...] = ENTRY_DATES) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, entry_date in enumerate(entry_dates):
        context_date = entry_date - pd.offsets.BDay(1)
        for symbol_index in range(1, 7):
            relative_order = symbol_index
            if date_index == 1 and symbol_index in {3, 4}:
                relative_order = 7 - symbol_index
            rows.append(
                {
                    "cycle_id": CYCLE_ID,
                    "sector_id": "BK0001",
                    "entry_date": entry_date,
                    "context_date": context_date,
                    "feature_cutoff_date": context_date,
                    "leader_spell_id": f"{CYCLE_ID}:60000{symbol_index}.SSE",
                    "recognition_source_date": pd.Timestamp("2025-01-03"),
                    "vt_symbol": f"60000{symbol_index}.SSE",
                    "stock_name": f"测试股份{symbol_index}",
                    "identity_feature_status": "complete",
                    "identity_cycle_relative_return": float(10 - relative_order),
                    "identity_strong_day_count_cycle": symbol_index,
                    "identity_sessions_since_strong": 6 - symbol_index,
                    "identity_turnover_median_20d": float(
                        80_000_000 + symbol_index * 20_000_000
                    ),
                    "identity_capacity_passed": symbol_index >= 2,
                    "dynamic_rank": symbol_index,
                }
            )
    return pd.DataFrame(rows)


def _trading_dates() -> tuple[date, ...]:
    return tuple(timestamp.date() for timestamp in pd.bdate_range("2025-01-03", periods=10))


def _stock_bars() -> pd.DataFrame:
    rows = []
    for symbol_index in range(1, 7):
        close = 10.0
        for trade_date in _trading_dates():
            change = 0.0
            if symbol_index == 1 and trade_date == date(2025, 1, 6):
                change = 6.0
            if symbol_index == 2 and trade_date == date(2025, 1, 8):
                change = 5.5
            close *= 1.0 + change / 100.0
            rows.append(
                {
                    "vt_symbol": f"60000{symbol_index}.SSE",
                    "trade_date": trade_date,
                    "close_price": close,
                }
            )
    return pd.DataFrame(rows)


def _realized_leaders() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": CYCLE_ID,
                "vt_symbol": f"60000{symbol_index}.SSE",
                "realized_market_rank": symbol_index,
                "realized_return_rank": 7 - symbol_index,
            }
            for symbol_index in range(1, 7)
        ]
    )


def test_all_frozen_modes_rank_the_same_d1_candidate_pool() -> None:
    ranks = build_cycle_identity_mode_ranks(_dynamic_candidates())

    assert set(ranks["identity_mode"]) == {
        mode.value for mode in LeaderIdentityMode
    }
    assert len(ranks) == 3 * 3 * 6
    first = ranks.loc[ranks["entry_date"].eq(ENTRY_DATES[0].date())]
    relative_top3 = set(
        first.loc[
            first["identity_mode"].eq("cycle_relative_strength")
            & first["mode_top3"],
            "vt_symbol",
        ]
    )
    recognition_top3 = set(
        first.loc[
            first["identity_mode"].eq("market_recognition_lexicographic")
            & first["mode_top3"],
            "vt_symbol",
        ]
    )
    consensus_top3 = set(
        first.loc[
            first["identity_mode"].eq("recognition_consensus")
            & first["mode_top3"],
            "vt_symbol",
        ]
    )

    assert relative_top3 == {"600001.SSE", "600002.SSE", "600003.SSE"}
    assert recognition_top3 == {"600004.SSE", "600005.SSE", "600006.SSE"}
    assert consensus_top3 == {"600003.SSE", "600004.SSE", "600005.SSE"}
    assert first.loc[first["mode_top3"], "mode_top3_qualified"].all()


def test_fewer_than_three_ranked_candidates_closes_every_mode() -> None:
    ranks = build_cycle_identity_mode_ranks(_dynamic_candidates().iloc[:2])

    assert not ranks["mode_top3_qualified"].any()
    assert not ranks["mode_top1"].any()
    assert not ranks["mode_top3"].any()


@pytest.mark.parametrize(
    "column",
    ["realized_return_rank", "future_return_pct", "net_return_pct", "exit_price"],
)
def test_identity_ranking_rejects_future_and_trade_outcomes(column: str) -> None:
    with pytest.raises(ValueError, match="prohibited"):
        build_cycle_identity_mode_ranks(_dynamic_candidates().assign(**{column: 1.0}))


def test_identity_labels_use_next_real_session_and_d_to_d5_strong_events() -> None:
    ranks = build_cycle_identity_mode_ranks(_dynamic_candidates())
    labels = build_cycle_identity_labels(
        ranks,
        _stock_bars(),
        _realized_leaders(),
        trading_dates=_trading_dates(),
    )
    first_relative = labels.loc[
        labels["entry_date"].eq(ENTRY_DATES[0].date())
        & labels["identity_mode"].eq("cycle_relative_strength")
        & labels["mode_top3"]
    ].set_index("vt_symbol")

    assert first_relative.loc["600001.SSE", "retained_top3_next_session"] == 1.0
    assert first_relative.loc["600003.SSE", "retained_top3_next_session"] == 0.0
    assert first_relative.loc["600001.SSE", "strong_event_lead_sessions"] == 0.0
    assert first_relative.loc["600002.SSE", "strong_event_lead_sessions"] == 2.0
    assert first_relative.loc["600003.SSE", "strong_event_lead_sessions"] == 6.0
    assert bool(first_relative.loc["600001.SSE", "realized_market_top1"])
    assert not bool(first_relative.loc["600001.SSE", "realized_return_top1"])
    assert "realized_market_top1" not in ranks


def test_incomplete_future_horizon_keeps_strong_event_label_null() -> None:
    last_date = pd.Timestamp(_trading_dates()[-1])
    dynamic = _dynamic_candidates(entry_dates=(last_date,))
    ranks = build_cycle_identity_mode_ranks(dynamic)
    labels = build_cycle_identity_labels(
        ranks,
        _stock_bars(),
        _realized_leaders(),
        trading_dates=_trading_dates(),
    )

    assert labels.loc[labels["mode_top3"], "strong_event_lead_sessions"].isna().all()
    assert labels.loc[labels["mode_top3"], "retained_top3_next_session"].isna().all()


def _metric_labels(*, candidate_better_in_validation: bool = True) -> pd.DataFrame:
    modes = tuple(mode.value for mode in LeaderIdentityMode)
    rows = []
    for block in range(1, 6):
        for session_in_block in range(40):
            entry_date = date(2025, block + 1, 1) + pd.Timedelta(days=session_in_block)
            for mode in modes:
                if mode == "cycle_relative_strength":
                    retention_rate = (
                        0.80
                        if block <= 3 or candidate_better_in_validation
                        else 0.75
                    )
                    strong_lead = 2.0
                    capacity = True
                elif mode == "market_recognition_lexicographic":
                    retention_rate = (
                        0.70
                        if block <= 3 or candidate_better_in_validation
                        else 0.85
                    )
                    strong_lead = 3.0
                    capacity = True
                else:
                    retention_rate = 0.60
                    strong_lead = 1.0
                    capacity = False
                for rank in range(1, 4):
                    observation_index = session_in_block * 3 + rank - 1
                    rows.append(
                        {
                            "cycle_id": f"cycle-{block}-{session_in_block}",
                            "sector_id": f"BK{block:04d}",
                            "entry_date": entry_date,
                            "identity_mode": mode,
                            "vt_symbol": f"60000{rank}.SSE",
                            "rank": rank,
                            "mode_top3_qualified": True,
                            "mode_top1": rank == 1,
                            "mode_top3": True,
                            "retained_top3_next_session": float(
                                observation_index % 20 < round(retention_rate * 20)
                            ),
                            "strong_event_lead_sessions": strong_lead,
                            "capacity_passed": capacity,
                            "realized_market_top1": rank == 1,
                            "realized_return_top1": rank == 2,
                            "block": block,
                        }
                    )
    return pd.DataFrame(rows)


def test_identity_metrics_keep_all_modes_and_time_segments() -> None:
    metrics = build_cycle_identity_metrics(_metric_labels())

    assert set(metrics["identity_mode"]) == {
        mode.value for mode in LeaderIdentityMode
    }
    assert {"all", "development", "validation", "block_1", "block_5"}.issubset(
        set(metrics["segment"])
    )
    relative = metrics.loc[
        metrics["identity_mode"].eq("cycle_relative_strength")
        & metrics["segment"].eq("development")
    ].iloc[0]
    assert relative["qualified_concept_sessions"] == 120
    assert relative["top3_observations"] == 360
    assert relative["eligible_retention_observations"] == 360
    assert relative["next_session_top3_retention"] == pytest.approx(0.8)
    assert relative["strong_event_lead_sessions"] == 2.0
    assert relative["realized_market_top1_coverage"] == 1.0


def test_stable_mode_must_beat_baseline_in_both_pooled_segments() -> None:
    improved = evaluate_cycle_identity_modes(
        build_cycle_identity_metrics(_metric_labels())
    )
    inconsistent = evaluate_cycle_identity_modes(
        build_cycle_identity_metrics(
            _metric_labels(candidate_better_in_validation=False)
        )
    )

    assert improved["proxy_selected_mode"] == "cycle_relative_strength"
    assert improved["fold_win_counts"] == {"cycle_relative_strength": 5}
    assert improved["overall_conclusion"] == "improved_proxy_identity_found"
    assert improved["pullback_retest_allowed"] is True
    assert improved["formal_selected_mode"] is None
    assert improved["low_suction_outcomes_read"] is False
    assert inconsistent["proxy_selected_mode"] == "cycle_relative_strength"
    assert inconsistent["fold_win_counts"] == {
        "cycle_relative_strength": 3,
        "market_recognition_lexicographic": 2,
    }
    assert (
        inconsistent["overall_conclusion"]
        == "stable_proxy_identity_not_consistently_better"
    )
    assert inconsistent["pullback_retest_allowed"] is False


def test_insufficient_blocks_cannot_select_a_proxy_mode() -> None:
    labels = _metric_labels().groupby(
        ["block", "identity_mode"], sort=False
    ).head(20)
    evaluation = evaluate_cycle_identity_modes(build_cycle_identity_metrics(labels))

    assert evaluation["proxy_selected_mode"] is None
    assert evaluation["fold_winners"] == [
        {"block": block, "identity_mode": None, "status": "insufficient_sample"}
        for block in range(1, 6)
    ]
    assert evaluation["pullback_retest_allowed"] is False


def test_pullback_runner_is_only_called_after_identity_improvement() -> None:
    calls: list[str] = []

    def runner(mode: str) -> dict[str, str]:
        calls.append(mode)
        return {"mode": mode}

    blocked = evaluate_cycle_identity_modes(
        build_cycle_identity_metrics(
            _metric_labels(candidate_better_in_validation=False)
        )
    )
    blocked_result = execute_identity_gated_pullback(blocked, runner)
    allowed = evaluate_cycle_identity_modes(
        build_cycle_identity_metrics(_metric_labels())
    )
    allowed_result = execute_identity_gated_pullback(allowed, runner)

    assert blocked_result["status"] == "not_run_identity_gate_failed"
    assert blocked_result["low_suction_outcomes_read"] is False
    assert calls == ["cycle_relative_strength"]
    assert allowed_result["status"] == "completed_reused_history_diagnostic"
    assert allowed_result["low_suction_outcomes_read"] is True


def test_selected_mode_adapter_uses_only_qualified_mode_flags() -> None:
    ranks = build_cycle_identity_mode_ranks(_dynamic_candidates())
    dynamic = build_selected_mode_dynamic_identity(
        ranks,
        "cycle_relative_strength",
    )

    assert dynamic.duplicated(["cycle_id", "entry_date", "vt_symbol"]).sum() == 0
    assert dynamic["dynamic_top3_qualified"].all()
    assert dynamic.groupby(["cycle_id", "entry_date"])["dynamic_top1"].sum().eq(1).all()
    assert dynamic.groupby(["cycle_id", "entry_date"])["dynamic_top3"].sum().eq(3).all()


def _report_parts() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    labels = _metric_labels(candidate_better_in_validation=False)
    metrics = build_cycle_identity_metrics(labels)
    evaluation = evaluate_cycle_identity_modes(metrics)
    pullback = {
        "status": "not_run_identity_gate_failed",
        "selected_mode": None,
        "low_suction_outcomes_read": False,
        "report": None,
    }
    metadata = {
        "coverage": {
            "observed_periods": 53,
            "identity_rows": len(labels),
            "qualified_identity_sessions": 200,
        },
        "input_fingerprints": {"identity": {"sha256": "test"}},
        "discovery_start": date(2025, 1, 1),
        "discovery_end": date(2025, 6, 30),
    }
    return labels, metrics, evaluation, pullback, metadata


def test_report_preserves_proxy_boundary_all_modes_and_block_winners() -> None:
    report = build_cycle_leader_identity_report(*_report_parts())
    payload = render_cycle_leader_identity_json(report)
    markdown = render_cycle_leader_identity_markdown(report)

    assert len(report["identity_ledger"]) == len(_report_parts()[0])
    assert report["formal_selected_mode"] is None
    assert report["formal_metrics"] is None
    assert report["strict_historical_top3_claim"] is False
    assert report["low_suction_outcomes_read"] is False
    assert '"formal_selected_mode": null' in payload
    for mode in LeaderIdentityMode:
        assert mode.value in markdown
    assert "五块身份赢家" in markdown
    assert "event_candidate_pool_proxy" in markdown


def test_runner_and_cli_do_not_expose_identity_or_threshold_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        study,
        "load_cycle_leader_identity_study_data",
        lambda: _report_parts(),
    )

    report = run_cycle_leader_identity_study()
    args = build_parser().parse_args(
        ["v2-cycle-leader-identity-study", "--format", "json"]
    )

    assert report["candidate_pool"] == "event_candidate_pool_proxy"
    assert args.command == "v2-cycle-leader-identity-study"
    assert not hasattr(args, "identity_mode")
    assert not hasattr(args, "threshold")
