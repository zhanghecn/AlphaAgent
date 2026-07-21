from __future__ import annotations

from datetime import date, datetime

from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)
from alphaagent.server.services.limit_up.preboard_transaction_trigger_study import (
    _coverage_rejection_report,
    build_transaction_acceptance_report,
    join_transaction_features,
    render_transaction_trigger_markdown,
)


def test_transaction_join_is_exact_by_stock_day_and_completed_minute() -> None:
    prefixes = [
        _prefix("600001.SSE", "2026-07-16", "10:00:00"),
        _prefix("600001.SSE", "2026-07-16", "10:01:00"),
        _prefix("600002.SSE", "2026-07-16", "10:00:00"),
    ]
    features = [
        _transaction("600001.SSE", date(2026, 7, 16), "10:00", 0.1),
        _transaction("600001.SSE", date(2026, 7, 16), "10:01", 0.2),
        _transaction("600001.SSE", date(2026, 7, 16), "10:02", 99.0),
    ]

    joined, audit = join_transaction_features(prefixes, features)

    assert joined[0]["transaction_features"][TRANSACTION_FEATURE_NAMES[0]] == 0.1
    assert joined[1]["transaction_features"][TRANSACTION_FEATURE_NAMES[0]] == 0.2
    assert joined[2]["transaction_features"] is None
    assert audit["prefix_count"] == 3
    assert audit["scoreable_prefix_count"] == 2
    assert audit["scoreable_prefix_pct"] == 66.6667
    assert audit["missing_feature_minute_count"] == 1
    assert audit["invalid_feature_value_count"] == 0
    assert audit["missing_prefixes"] == [
        {
            "vt_symbol": "600002.SSE",
            "signal_date": "2026-07-16",
            "signal_time": "10:00",
            "reason": "feature_minute_missing",
            "invalid_features": [],
        }
    ]
    assert audit["unused_transaction_feature_count"] == 1


def test_transaction_acceptance_fails_closed_on_coverage_baseline_and_pf() -> None:
    validation = {
        "identity": {
            "selection_count": 30,
            "formal_identity_precision_pct": 80.0,
            "reachable_formal_recall_pct": 40.0,
        },
        "account_identity": {"precision_pct": 80.0},
        "accounts": {
            "formal_touch": {"win_rate": 70.0},
            "joint_action": {
                "total_return_pct": 10.0,
                "max_drawdown_pct": -5.0,
                "win_rate": 70.0,
                "profit_factor": 1.5,
            },
            "joint_action_double_cost": {"total_return_pct": 8.0},
        },
    }
    blocks = [
        {
            "accounts": {
                "joint_action": {"trade_count": 2, "total_return_pct": 1.0}
            }
        }
        for _ in range(3)
    ] + [
        {
            "accounts": {
                "joint_action": {"trade_count": 2, "total_return_pct": -1.0}
            }
        }
        for _ in range(2)
    ]
    ready_model = type("Model", (), {"status": "ready"})()
    ready_threshold = type("Threshold", (), {"status": "ready"})()
    coverage = {
        "scope_ready_pair_pct": 100.0,
        "scoreable_prefix_pct": 100.0,
    }

    passed = build_transaction_acceptance_report(
        validation,
        validation_blocks=blocks,
        models=(ready_model, ready_model),
        threshold=ready_threshold,
        baseline_parity={"passed": True},
        v3_reference_parity={"passed": True},
        transaction_coverage=coverage,
    )
    missing = build_transaction_acceptance_report(
        validation,
        validation_blocks=blocks,
        models=(ready_model, ready_model),
        threshold=ready_threshold,
        baseline_parity={"passed": True},
        v3_reference_parity={"passed": True},
        transaction_coverage={**coverage, "scoreable_prefix_pct": 99.9},
    )
    mismatch = build_transaction_acceptance_report(
        validation,
        validation_blocks=blocks,
        models=(ready_model, ready_model),
        threshold=ready_threshold,
        baseline_parity={"passed": False},
        v3_reference_parity={"passed": True},
        transaction_coverage=coverage,
    )
    weak_pf = build_transaction_acceptance_report(
        {
            **validation,
            "accounts": {
                **validation["accounts"],
                "joint_action": {
                    **validation["accounts"]["joint_action"],
                    "profit_factor": 1.19,
                },
            },
        },
        validation_blocks=blocks,
        models=(ready_model, ready_model),
        threshold=ready_threshold,
        baseline_parity={"passed": True},
        v3_reference_parity={"passed": True},
        transaction_coverage=coverage,
    )

    assert passed["passed"] is True
    assert missing["checks"]["transaction_prefix_coverage_100pct"] is False
    assert mismatch["checks"]["baseline_parity"] is False
    assert weak_pf["checks"]["minimum_1_2_normal_account_profit_factor"] is False
    assert missing["passed"] is mismatch["passed"] is weak_pf["passed"] is False


def test_coverage_failure_is_archived_without_fake_zero_trade_results() -> None:
    report = _coverage_rejection_report(
        session_count=89,
        timings={"transaction_join_seconds": 1.25},
        transaction_coverage={
            "requested_pair_count": 962,
            "ready_pair_count": 962,
            "scope_ready_pair_pct": 100.0,
            "prefix_count": 22_821,
            "scoreable_prefix_count": 22_804,
            "scoreable_prefix_pct": 99.9255,
        },
    )

    markdown = render_transaction_trigger_markdown(report)

    assert report["status"] == "ready_historical_rejected"
    assert report["decision"] == "historical_rejected_no_live_promotion"
    assert report["model_evaluation_status"] == "not_run_fail_closed_coverage"
    assert report["acceptance"]["checks"] == {
        "transaction_scope_coverage_100pct": True,
        "transaction_prefix_coverage_100pct": False,
        "historical_model_evaluation_completed": False,
    }
    assert "v3/v4 模型和账户均未运行" in markdown
    assert "| v4逐笔模型 | 0 |" not in markdown


def _prefix(symbol: str, signal_date: str, signal_time: str) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "signal_at": f"{signal_date}T{signal_time}",
    }


def _transaction(
    symbol: str,
    trade_date: date,
    bar_time: str,
    value: float,
) -> dict[str, object]:
    return {
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "bar_time": datetime.combine(
            trade_date,
            datetime.strptime(bar_time, "%H:%M").time(),
        ),
        "input_fingerprint": "sha256:" + "a" * 64,
        "values": {
            name: value + index * 0.001
            for index, name in enumerate(TRANSACTION_FEATURE_NAMES)
        },
    }
