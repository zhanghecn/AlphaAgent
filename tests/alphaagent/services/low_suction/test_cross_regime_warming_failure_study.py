from __future__ import annotations

from copy import deepcopy
from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cross_regime_warming_failure_study import (
    DailyContext,
    archive_warming_failure_report,
    build_trade_feature_ledger,
    build_warming_failure_report,
    enrich_trade_feature_ledger,
    load_selected_daily_context,
    render_warming_failure_json,
    render_warming_failure_markdown,
    run_warming_failure_study,
    select_support_relevance_candidate,
    select_rotation_timeliness_candidate,
)
from alphaagent.server.services.low_suction.cli import build_parser


def test_trade_feature_ledger_joins_each_trade_to_one_causal_signal() -> None:
    ledger = build_trade_feature_ledger(_source_report())

    assert [row["signal_id"] for row in ledger] == ["s1", "s2", "s3", "s4"]
    assert ledger[0]["causal_features"]["low_support_gap_pct"] == pytest.approx(
        0.5
    )
    assert ledger[0]["outcome_group"] == "winner"
    assert ledger[1]["outcome_group"] == "loser"
    assert ledger[0]["causal_features"]["feature_cutoff_date"] == "2024-01-02"


def test_trade_feature_ledger_rejects_duplicate_or_noncausal_identity() -> None:
    source = _source_report()
    source["candidate_signal_ledger"].append(
        deepcopy(source["candidate_signal_ledger"][0])
    )
    with pytest.raises(ValueError, match="signal identities must be unique"):
        build_trade_feature_ledger(source)

    source = _source_report()
    source["candidate_signal_ledger"][0]["feature_cutoff_date"] = "2024-01-03"
    with pytest.raises(ValueError, match="feature cutoff must equal entry date"):
        build_trade_feature_ledger(source)


def test_warming_requires_an_exact_and_relevant_support_hold() -> None:
    selected = select_support_relevance_candidate(
        [
            _feature_row("rotation", phase="rotation", gap_pct=-20.0),
            _feature_row("warming-near", phase="warming", gap_pct=0.5),
            _feature_row("warming-undercut", phase="warming", gap_pct=-0.1),
            _feature_row("warming-stale", phase="warming", gap_pct=8.1),
            _feature_row("uptrend", phase="uptrend", gap_pct=0.5),
        ]
    )

    assert [row["signal_id"] for row in selected] == [
        "rotation",
        "warming-near",
    ]


def test_candidate_filter_rejects_outcome_columns() -> None:
    with pytest.raises(ValueError, match="prohibited outcome"):
        select_support_relevance_candidate(
            [{**_feature_row("s1", phase="warming", gap_pct=0.5), "net_return_pct": 9.0}]
        )


def test_report_keeps_every_warming_validation_case() -> None:
    report = build_warming_failure_report(_source_report(), bootstrap_draws=20)

    cases = report["individual_cases"]["validation_warming"]
    assert [row["signal_id"] for row in cases] == ["s3", "s4"]
    assert {row["outcome_group"] for row in cases} == {"winner", "loser"}
    assert report["baseline"]["full_history"]["closed_trades"] == 4
    assert report["attribution"]["profiled_trade_count"] == 4
    assert report["formal_strategy"] is False


def test_candidate_report_preserves_rotation_and_filters_warming_only() -> None:
    report = build_warming_failure_report(_source_report(), bootstrap_draws=20)

    candidate = report["candidate"]
    assert candidate["policy_version"] == (
        "causal-leader-pullback-warming-support-relevance-v1"
    )
    assert candidate["selected_signal_ids"] == ["s1", "s3"]
    assert candidate["full_history"]["closed_trades"] == 2
    assert candidate["full_history_market_phases"] == [
        {
            "id": "rotation",
            "closed_trades": 1,
            "winning_trades": 1,
            "win_rate_pct": 100.0,
            "mean_net_return_pct": 2.0,
            "profit_factor": None,
            "signal_compound_return_pct": pytest.approx(2.0),
        },
        {
            "id": "warming",
            "closed_trades": 1,
            "winning_trades": 1,
            "win_rate_pct": 100.0,
            "mean_net_return_pct": 3.0,
            "profit_factor": None,
            "signal_compound_return_pct": pytest.approx(3.0),
        },
    ]
    assert candidate["formal_strategy"] is False
    assert "reused_validation_not_fresh_holdout" in candidate["formal_blockers"]


def test_candidate_attribution_uses_only_final_selected_identities() -> None:
    source = _source_report()
    source["candidate_signal_ledger"][3]["signal_low"] = 10.05

    report = build_warming_failure_report(source, bootstrap_draws=20)

    attribution = report["candidate"]["attribution"]
    assert attribution["scope"] == "final_selected_candidate_only"
    assert attribution["threshold_search"] is False
    assert attribution["profiled_trade_count"] == 3
    assert [row["signal_id"] for row in attribution["individual_cases"]] == [
        "s1",
        "s3",
        "s4",
    ]
    assert {row["id"] for row in attribution["outcome_groups"]} == {
        "loser",
        "winner",
    }
    rank_groups = attribution["causal_category_metrics"]["dynamic_rank"]
    assert {row["id"] for row in rank_groups} == {"1", "3"}
    rank_splits = attribution["causal_category_split_metrics"]["dynamic_rank"]
    rank_1 = next(row for row in rank_splits if row["id"] == "1")
    rank_3 = next(row for row in rank_splits if row["id"] == "3")
    assert rank_1["development"]["closed_trades"] == 1
    assert rank_1["validation"]["closed_trades"] == 0
    assert rank_1["both_splits_present"] is False
    assert rank_3["development"]["closed_trades"] == 0
    assert rank_3["validation"]["closed_trades"] == 2
    assert rank_3["both_splits_descriptive_pass"] is False
    support_gap = next(
        row
        for row in attribution["numeric_feature_comparisons"]
        if row["feature"] == "low_support_gap_pct"
    )
    assert support_gap["development"]["winner"]["available_values"] == 1
    assert support_gap["development"]["loser"]["available_values"] == 0
    assert support_gap["validation"]["winner"]["available_values"] == 1
    assert support_gap["validation"]["loser"]["available_values"] == 1


def test_rotation_timeliness_candidate_rejects_only_delayed_rotation() -> None:
    source = _source_report()
    source["candidate_signal_ledger"][3]["signal_low"] = 10.05
    rows = [
        dict(row["causal_features"])
        for row in build_trade_feature_ledger(source)
    ]
    rows[0]["support_test_session_gap"] = 2

    selected = select_rotation_timeliness_candidate(rows)

    assert [row["signal_id"] for row in selected] == ["s3", "s4"]


def test_enrichment_uses_only_exact_signal_support_campaign_and_prior_phase() -> None:
    ledger = build_trade_feature_ledger(_source_report())
    stock_features = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": "2024-01-02",
                "turnover_expansion": 1.4,
                "close_location": 0.75,
                "sessions_since_ignition": 3,
                "ma5": 10.0,
                "ma10": 9.5,
                "ma20": 9.0,
                "prior_high20": 11.2,
                "daily_return_pct": 10.0,
                "volume_ratio_prior5": 1.2,
                "close_price": 11.0,
                "low_price": 10.05,
                "feature_cutoff_date": "2024-01-02",
            }
        ]
    )
    campaign_paths = pd.DataFrame(
        [
            {
                "campaign_id": "campaign-1",
                "trade_date": "2024-01-02",
                "campaign_day": 7,
                "cumulative_gain_pct": 12.5,
                "feature_cutoff_date": "2024-01-02",
            }
        ]
    )
    market_timing = pd.DataFrame(
        [
            {"source_date": "2024-01-01", "market_phase": "retreat"},
            {"source_date": "2024-01-02", "market_phase": "rotation"},
        ]
    )

    enriched = enrich_trade_feature_ledger(
        ledger,
        stock_features=stock_features,
        campaign_paths=campaign_paths,
        market_timing=market_timing,
    )

    features = enriched[0]["causal_features"]
    assert features["turnover_expansion"] == pytest.approx(1.4)
    assert features["close_location"] == pytest.approx(0.75)
    assert features["sessions_since_ignition"] == 3
    assert features["signal_ma5_gap_pct"] == pytest.approx(10.0)
    assert features["campaign_day"] == 7
    assert features["concept_gain_pct"] == pytest.approx(12.5)
    assert features["previous_market_phase"] == "retreat"
    assert features["market_phase_transition"] == "retreat_to_rotation"
    assert enriched[1]["causal_features"]["turnover_expansion"] is None


def test_report_attaches_cash_metrics_without_promoting_formal_strategy() -> None:
    cash = {
        "closed_trades": 2,
        "winning_trades": 2,
        "cash_win_rate_pct": 100.0,
        "compound_return_pct": 65.0,
        "maximum_drawdown_pct": -2.0,
    }

    report = build_warming_failure_report(
        _source_report(),
        bootstrap_draws=20,
        cash_metrics=cash,
    )

    assert report["candidate"]["cash"] == cash
    assert report["candidate"]["formal_strategy"] is False
    assert "four_slot_cash_not_attached" not in report["candidate"]["formal_blockers"]


def test_runner_enriches_and_runs_the_four_slot_cash_account() -> None:
    context = _daily_context()

    report = run_warming_failure_study(
        _source_report(),
        daily_context=context,
        bootstrap_draws=20,
    )

    assert report["causal_enrichment"]["stock_bar_rows"] == 8
    assert report["candidate"]["cash"]["closed_trades"] == 2
    assert report["candidate"]["cash"]["compound_return_pct"] > 0.0
    assert report["individual_cases"]["validation_warming"][0][
        "turnover_expansion"
    ] == pytest.approx(1.4)


def test_daily_context_query_binds_a_date_cutoff(monkeypatch) -> None:
    class StatementCaptured(Exception):
        pass

    def capture_statement(statement, _engine, **_kwargs):
        cutoff_values = [
            value
            for key, value in statement.compile().params.items()
            if key.startswith("trade_date_")
        ]
        assert cutoff_values == [date(2024, 1, 3)]
        raise StatementCaptured

    monkeypatch.setattr(
        "alphaagent.server.db.session.get_engine",
        lambda: object(),
    )
    monkeypatch.setattr(pd, "read_sql", capture_statement)

    with pytest.raises(StatementCaptured):
        load_selected_daily_context(
            [
                {
                    "vt_symbol": "600001.SSE",
                    "entry_date": "2024-01-02",
                    "outcome": {"exit_date": "2024-01-03"},
                    "causal_features": {"sector_id": "BK0001"},
                }
            ]
        )


def test_render_and_archive_are_deterministic_and_immutable(tmp_path) -> None:
    report = build_warming_failure_report(_source_report(), bootstrap_draws=20)
    json_text = render_warming_failure_json(report)
    markdown = render_warming_failure_markdown(report)

    assert '"study_version": "cross-regime-warming-failure-study-v5"' in json_text
    assert "s3" in markdown
    output = tmp_path / "warming.json"
    archived = archive_warming_failure_report(report, output)
    assert archived == {
        "json": str(output),
        "markdown": str(output.with_suffix(".md")),
    }
    assert archive_warming_failure_report(report, output) == archived

    changed = deepcopy(report)
    changed["research_status"] = "changed"
    with pytest.raises(ValueError, match="different contents"):
        archive_warming_failure_report(changed, output)


def test_cli_registers_the_bounded_warming_failure_command() -> None:
    args = build_parser().parse_args(
        [
            "v3-warming-failure-study",
            "--source",
            "source.json",
            "--format",
            "json",
            "--output",
            "output.json",
        ]
    )

    assert args.command == "v3-warming-failure-study"
    assert str(args.source) == "source.json"
    assert str(args.output) == "output.json"


def _source_report() -> dict[str, object]:
    rows = [
        ("s1", "block_1", "rotation", 0.5, 2.0, "2024-01-02"),
        ("s2", "block_2", "warming", -0.5, -1.0, "2024-02-02"),
        ("s3", "block_4", "warming", 0.5, 3.0, "2025-01-02"),
        ("s4", "block_5", "warming", 9.0, -2.0, "2026-01-02"),
    ]
    signals = []
    trades = []
    for position, (signal_id, block, phase, gap, result, entry_date) in enumerate(
        rows,
        start=1,
    ):
        support_price = 10.0
        signals.append(
            {
                "signal_id": signal_id,
                "campaign_id": f"campaign-{position}",
                "sector_id": f"BK{position:04d}",
                "concept_name": f"概念{position}",
                "vt_symbol": f"600{position:03d}.SSE",
                "stock_name": f"股票{position}",
                "signal_date": entry_date,
                "feature_cutoff_date": entry_date,
                "stock_leg_number": 1,
                "wave_number": position,
                "required_support": "ma5" if position == 1 else "ma10",
                "support_line": "ma10",
                "support_depth": 2,
                "support_test_date": entry_date,
                "support_test_session_gap": 1,
                "support_price": support_price,
                "signal_close": 11.0,
                "signal_low": support_price * (1.0 + gap / 100.0),
                "signal_daily_return_pct": 10.0,
                "volume_ratio_prior5": 1.2,
                "reference_peak_date": entry_date,
                "reference_peak_price": 11.2,
                "dynamic_rank": min(position, 3),
                "market_phase": phase,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
            }
        )
        trades.append(
            {
                "variant": "cross_regime_support_reclaim_confirmation",
                "signal_id": signal_id,
                "campaign_id": f"campaign-{position}",
                "sector_id": f"BK{position:04d}",
                "vt_symbol": f"600{position:03d}.SSE",
                "entry_date": entry_date,
                "entry_price": 11.0,
                "exit_date": (
                    pd.Timestamp(entry_date) + pd.Timedelta(days=1)
                ).date().isoformat(),
                "exit_price": 11.0 * (1.0 + (result + 0.2) / 100.0),
                "net_return_pct": result,
                "time_block": block,
                "market_phase": phase,
                "market_regime": "GOLD/NORMAL",
                "dynamic_rank": min(position, 3),
                "wave_number": position,
                "support_line": "ma10",
                "support_test_date": entry_date,
            }
        )
    return {
        "policy_version": "causal-leader-pullback-cross-regime-v3",
        "formal_strategy": False,
        "candidate_signal_ledger": signals,
        "trade_ledger": trades,
    }


def _feature_row(
    signal_id: str,
    *,
    phase: str,
    gap_pct: float,
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "market_phase": phase,
        "low_support_gap_pct": gap_pct,
        "feature_cutoff_date": "2025-01-02",
    }


def _daily_context() -> DailyContext:
    source = _source_report()
    signal_rows = source["candidate_signal_ledger"]
    trade_by_signal = {row["signal_id"]: row for row in source["trade_ledger"]}
    stock_rows = []
    campaign_rows = []
    timing_rows = []
    for signal in signal_rows:
        stock_rows.append(
            {
                "vt_symbol": signal["vt_symbol"],
                "trade_date": signal["signal_date"],
                "open_price": 10.0,
                "high_price": 11.2,
                "low_price": signal["signal_low"],
                "close_price": signal["signal_close"],
                "volume": 1_000.0,
                "turnover": 10_000.0,
                "turnover_expansion": 1.4,
                "close_location": 0.75,
                "sessions_since_ignition": 3,
                "ma5": 10.0,
                "ma10": 9.5,
                "ma20": 9.0,
                "prior_high20": 11.2,
                "daily_return_pct": 10.0,
                "volume_ratio_prior5": 1.2,
                "feature_cutoff_date": signal["signal_date"],
            }
        )
        stock_rows.append(
            {
                "vt_symbol": signal["vt_symbol"],
                "trade_date": trade_by_signal[signal["signal_id"]]["exit_date"],
                "open_price": 11.0,
                "high_price": 11.5,
                "low_price": 10.8,
                "close_price": 11.2,
                "volume": 1_000.0,
                "turnover": 10_000.0,
                "turnover_expansion": 1.0,
                "close_location": 0.5,
                "sessions_since_ignition": 4,
                "ma5": 10.2,
                "ma10": 9.7,
                "ma20": 9.2,
                "prior_high20": 11.2,
                "daily_return_pct": 1.0,
                "volume_ratio_prior5": 1.0,
                "feature_cutoff_date": trade_by_signal[signal["signal_id"]][
                    "exit_date"
                ],
            }
        )
        campaign_rows.append(
            {
                "campaign_id": signal["campaign_id"],
                "trade_date": signal["signal_date"],
                "campaign_day": 7,
                "cumulative_gain_pct": 12.5,
                "feature_cutoff_date": signal["signal_date"],
            }
        )
        timing_rows.append(
            {
                "source_date": signal["signal_date"],
                "market_phase": signal["market_phase"],
            }
        )
    stock_bars = pd.DataFrame(stock_rows)
    return DailyContext(
        stock_bars=stock_bars,
        stock_features=stock_bars.copy(),
        campaign_paths=pd.DataFrame(campaign_rows),
        market_timing=pd.DataFrame(timing_rows),
        coverage={"stock_bar_rows": len(stock_rows)},
    )
