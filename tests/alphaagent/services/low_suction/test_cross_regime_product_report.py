from __future__ import annotations

from alphaagent.server.services.low_suction.cross_regime_product_report import (
    POLICY_VERSION,
    SOURCE_STUDY_VERSION,
    VARIANT,
    build_cross_regime_product_report,
)


def test_product_report_reads_market_phase_identifiers_from_group_column() -> None:
    report = build_cross_regime_product_report(
        _source_report(),
        source_path="memory/06_backtests/source.json",
        source_sha256="source-sha256",
    )

    assert [row["id"] for row in report["market_phases"]] == [
        "rotation",
        "warming",
    ]


def test_product_report_separates_point_gate_from_sequential_validation() -> None:
    report = build_cross_regime_product_report(
        _source_report(),
        source_path="memory/06_backtests/source.json",
        source_sha256="source-sha256",
    )

    assert report["historical_proxy_gate_passed"] is True
    assert report["research_status"] == (
        "historical_proxy_point_gate_passed_sequential_regime_failed"
    )
    assert report["sequential_audit"]["split"]["validation_blocks"] == [
        "block_4",
        "block_5",
    ]
    assert (
        report["sequential_audit"]["qualification"][
            "sequential_cross_regime_passed"
        ]
        is False
    )
    assert report["qualification"]["sequential_cross_regime_passed"] is False


def _source_report() -> dict[str, object]:
    signal = {
        "signal_id": "signal-1",
        "stock_name": "测试龙头",
        "concept_name": "测试概念",
        "support_price": 10.0,
        "signal_low": 9.9,
        "reference_peak_price": 10.5,
        "signal_close": 10.2,
        "signal_daily_return_pct": 8.5,
    }
    trade = {
        "variant": VARIANT,
        "signal_id": "signal-1",
        "campaign_id": "campaign-1",
        "entry_date": "2025-01-02",
        "vt_symbol": "600001.SSE",
        "market_phase": "rotation",
        "time_block": "block_1",
        "dynamic_rank": 1,
        "wave_number": 1,
        "support_line": "ma5",
        "support_test_date": "2024-12-31",
        "entry_price": 10.2,
        "d1_date": "2025-01-03",
        "d1_net_return_pct": 1.0,
        "exit_date": "2025-01-03",
        "exit_price": 10.4,
        "exit_reason": "higher_high_confirmed",
        "net_return_pct": 1.76,
    }
    return {
        "study_version": SOURCE_STUDY_VERSION,
        "algorithm_version": "causal-leader-pullback-close-v2",
        "policy_version": POLICY_VERSION,
        "contract": {
            "concept_campaign": "campaign-rule",
            "leader_rank": "leader-rule",
            "round_trip_cost_pct": 0.2,
        },
        "coverage": {"concepts": 10, "candidate_signals": 20},
        "signal_funnel": {"cross_regime_support_reclaim_confirmations": 2},
        "candidate_signal_ledger": [signal],
        "trade_ledger": [trade],
        "overall_metrics": [_metric_row()],
        "cash_results": {
            VARIANT: {
                "initial_cash": 100_000.0,
                "final_equity": 101_000.0,
                "closed_trades": 1,
                "winning_trades": 1,
                "cash_win_rate_pct": 100.0,
                "compound_return_pct": 1.0,
                "maximum_drawdown_pct": 0.0,
                "capacity": 4,
            }
        },
        "decisions": [
            {
                "variant": VARIANT,
                "historical_proxy_gate_passed": True,
                "stable_time_blocks": 5,
                "qualified_market_phases": ["rotation", "warming"],
            }
        ],
        "market_phase_metrics": [
            _metric_row(group="rotation"),
            _metric_row(group="warming"),
        ],
        "time_block_metrics": [
            _metric_row(time_block=f"block_{index}") for index in range(1, 6)
        ],
    }


def _metric_row(**identity: str) -> dict[str, object]:
    return {
        "variant": VARIANT,
        "closed_trades": 1,
        "positive_rate_pct": 100.0,
        "mean_net_return_pct": 1.76,
        "profit_factor": 2.0,
        "compound_return_pct": 1.76,
        "maximum_drawdown_pct": 0.0,
        **identity,
    }
