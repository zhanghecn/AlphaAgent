from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from alphaagent.server.services.limit_up.preboard_radar_sequence_study import (
    ACTION_SCORE_FIELD,
    audit_excluded_training_extension,
    audit_radar_sequence_minute_coverage,
    build_labeled_radar_rows,
    build_radar_acceptance_report,
    build_radar_sequence_scope_audit,
    fit_radar_sequence_policy,
    radar_order,
    split_radar_sequence_dates,
)
from alphaagent.server.services.limit_up.preboard_radar_sequence_model import (
    FIRST_LAYER_FEATURE_NAMES,
)


def test_radar_sequence_date_split_is_frozen_at_forty_four_fifteen_thirty() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(89))

    fit, calibration, validation = split_radar_sequence_dates(dates)

    assert fit == dates[:44]
    assert calibration == dates[44:59]
    assert validation == dates[59:]


def test_radar_sequence_date_split_rejects_any_other_session_count() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(95))

    try:
        split_radar_sequence_dates(dates)
    except ValueError as exc:
        assert str(exc) == "radar sequence study requires exactly 89 complete trade dates"
    else:
        raise AssertionError("95 dates must not be presented as an 89-day complete study")


def test_minute_coverage_gate_keeps_missing_pairs_in_the_denominator() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(89))
    fit, calibration, validation = split_radar_sequence_dates(dates)
    manifest = pd.DataFrame(
        [
            {"vt_symbol": "600001.SSE", "trade_date": fit[0]},
            {"vt_symbol": "600002.SSE", "trade_date": calibration[0]},
            {"vt_symbol": "600003.SSE", "trade_date": validation[0]},
        ]
    )
    coverage = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": fit[0],
                "coverage_status": "missing",
            },
            {
                "vt_symbol": "600002.SSE",
                "trade_date": calibration[0],
                "coverage_status": "complete",
            },
            {
                "vt_symbol": "600003.SSE",
                "trade_date": validation[0],
                "coverage_status": "complete",
            },
        ]
    )

    audit = audit_radar_sequence_minute_coverage(
        manifest,
        coverage,
        fit_dates=set(fit),
        calibration_dates=set(calibration),
        validation_dates=set(validation),
    )

    assert audit["passed"] is False
    assert audit["status"] == "blocked_by_training_minute_coverage"
    assert audit["manifest_pair_count"] == 3
    assert audit["complete_pair_count"] == 2
    assert audit["missing_pair_count"] == 1
    assert audit["phase_missing_pair_counts"] == {
        "fit": 1,
        "calibration": 0,
        "validation": 0,
    }


def test_validation_gap_fails_closed_instead_of_removing_the_date() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(89))
    fit, calibration, validation = split_radar_sequence_dates(dates)
    manifest = pd.DataFrame(
        [{"vt_symbol": "600001.SSE", "trade_date": validation[0]}]
    )
    coverage = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": validation[0],
                "coverage_status": "incomplete",
            }
        ]
    )

    audit = audit_radar_sequence_minute_coverage(
        manifest,
        coverage,
        fit_dates=set(fit),
        calibration_dates=set(calibration),
        validation_dates=set(validation),
    )

    assert audit["passed"] is False
    assert audit["status"] == "blocked_by_validation_minute_coverage"
    assert audit["phase_missing_pair_counts"]["validation"] == 1


def test_unavailable_six_day_extension_is_audited_but_not_called_complete() -> None:
    first = date(2026, 2, 27)
    excluded_dates = tuple(first + timedelta(days=index) for index in range(6))
    manifest = pd.DataFrame(
        [
            {"vt_symbol": f"60000{index}.SSE", "trade_date": trade_date}
            for index, trade_date in enumerate(excluded_dates, start=1)
        ]
    )
    coverage = manifest.assign(coverage_status="missing")

    audit = audit_excluded_training_extension(manifest, coverage)

    assert audit == {
        "status": "excluded_training_extension_provider_unavailable",
        "included_in_main_study": False,
        "trade_dates": tuple(value.isoformat() for value in excluded_dates),
        "manifest_pair_count": 6,
        "complete_pair_count": 0,
        "missing_pair_count": 6,
    }


def test_scope_audit_freezes_complete_main_window_and_input_fingerprints() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(95))
    manifest = pd.DataFrame(
        [
            {
                "vt_symbol": f"{600000 + index}.SSE",
                "trade_date": trade_date,
                "stock_d1_sample_count": 5 + index,
                "stock_gene_combined_win_rate": 30.0 + index / 10,
            }
            for index, trade_date in enumerate(dates)
        ]
    )
    coverage = manifest.loc[:, ["vt_symbol", "trade_date"]].assign(
        coverage_status=["missing"] * 6 + ["complete"] * 89,
        raw_row_count=[0] * 6 + [240] * 89,
        unique_row_count=[0] * 6 + [240] * 89,
        valid_slot_count=[0] * 6 + [240] * 89,
    )

    audit = build_radar_sequence_scope_audit(manifest, coverage)

    assert audit["status"] == "ready"
    assert audit["probed_trade_date_count"] == 95
    assert audit["main_window"]["trade_date_count"] == 89
    assert audit["main_window"]["manifest_pair_count"] == 89
    assert audit["main_window"]["coverage"]["passed"] is True
    assert audit["main_window"]["fit_dates"] == tuple(
        value.isoformat() for value in dates[6:50]
    )
    assert audit["main_window"]["calibration_dates"] == tuple(
        value.isoformat() for value in dates[50:65]
    )
    assert audit["main_window"]["validation_dates"] == tuple(
        value.isoformat() for value in dates[65:]
    )
    assert audit["excluded_training_extension"]["missing_pair_count"] == 6
    assert audit["excluded_training_extension"]["included_in_main_study"] is False
    assert set(audit["input_fingerprints"]) == {
        "manifest_pairs_sha256",
        "minute_coverage_sha256",
        "history_quality_sha256",
    }
    assert all(
        str(value).startswith("sha256:")
        for value in audit["input_fingerprints"].values()
    )


def test_scope_audit_refuses_to_hide_a_gap_inside_main_window() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(95))
    manifest = pd.DataFrame(
        [
            {"vt_symbol": f"{600000 + index}.SSE", "trade_date": trade_date}
            for index, trade_date in enumerate(dates)
        ]
    )
    statuses = ["missing"] * 6 + ["complete"] * 89
    statuses[-1] = "missing"
    coverage = manifest.loc[:, ["vt_symbol", "trade_date"]].assign(
        coverage_status=statuses
    )

    audit = build_radar_sequence_scope_audit(manifest, coverage)

    assert audit["status"] == "blocked_by_validation_minute_coverage"
    assert audit["main_window"]["coverage"]["missing_pair_count"] == 1


def test_sequence_features_are_frozen_before_future_targets_are_attached(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def enrich(rows):
        calls.append("features")
        assert all("formal_touch_within_3m" not in row for row in rows)
        return [
            {
                "signal_date": "2026-07-02",
                "signal_time": "10:00",
                "vt_symbol": "600001.SSE",
                "sequence_features": {name: 1.0 for name in FIRST_LAYER_FEATURE_NAMES},
            }
        ]

    def attach(rows, formal_orders):
        calls.append("targets")
        assert rows[0]["sequence_features"]
        return [{**dict(rows[0]), "formal_touch_within_3m": True}]

    monkeypatch.setattr(
        "alphaagent.server.services.limit_up.preboard_radar_sequence_study.enrich_radar_sequence_features",
        enrich,
    )
    monkeypatch.setattr(
        "alphaagent.server.services.limit_up.preboard_radar_sequence_study.attach_competing_risk_targets",
        attach,
    )

    result = build_labeled_radar_rows(
        [
            {
                "signal_date": "2026-07-02",
                "signal_time": "10:00",
                "vt_symbol": "600001.SSE",
                "entry_price": 9.8,
            }
        ],
        [],
    )

    assert calls == ["features", "targets"]
    assert result[0]["entry_price"] == 9.8
    assert result[0]["formal_touch_within_3m"] is True


def test_radar_order_preserves_next_minute_fill_and_conservative_price() -> None:
    signal = {
        "signal_date": "2026-07-02",
        "signal_time": "10:00",
        "entry_time": "10:01",
        "vt_symbol": "600001.SSE",
        "fillable": True,
        "signal_price": 9.70,
        "entry_price": 9.705,
        "limit_price": 10.0,
        ACTION_SCORE_FIELD: 0.8,
    }

    normal = radar_order(signal, conservative_entry=False)
    conservative = radar_order(signal, conservative_entry=True)

    assert normal is not None
    assert conservative is not None
    assert normal["algorithm"] == "radar_sequence_top1_v8"
    assert normal["buy_time"] == "10:01"
    assert normal["entry_price"] == 9.705
    assert conservative["entry_price"] == 9.7097
    assert conservative["conservative_entry"] is True


def test_radar_acceptance_applies_every_frozen_historical_gate() -> None:
    validation = {
        "identity": {
            "selection_count": 30,
            "formal_identity_precision_pct": 75.0,
            "reachable_formal_recall_pct": 35.0,
        },
        "account_identity": {"precision_pct": 75.0},
        "accounts": {
            "formal_touch": {"win_rate": 70.0},
            "joint_action": {
                "trade_count": 30,
                "win_rate": 69.0,
                "total_return_pct": 20.0,
                "max_drawdown_pct": -8.0,
                "profit_factor": 1.5,
            },
            "joint_action_double_cost": {"total_return_pct": 15.0},
        },
    }
    blocks = [
        {"accounts": {"joint_action": {"trade_count": 2, "total_return_pct": 1.0}}}
        for _ in range(3)
    ] + [
        {"accounts": {"joint_action": {"trade_count": 2, "total_return_pct": -1.0}}}
        for _ in range(2)
    ]
    ready_model = SimpleNamespace(status="ready")
    ready_threshold = SimpleNamespace(status="ready")

    accepted = build_radar_acceptance_report(
        validation,
        validation_blocks=blocks,
        candidate_model=ready_model,
        action_model=ready_model,
        threshold=ready_threshold,
        baseline_parity={"passed": True},
    )
    weak_pf = build_radar_acceptance_report(
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
        candidate_model=ready_model,
        action_model=ready_model,
        threshold=ready_threshold,
        baseline_parity={"passed": True},
    )

    assert accepted["passed"] is True
    assert weak_pf["passed"] is False
    assert weak_pf["checks"]["minimum_1_2_normal_account_profit_factor"] is False


def test_validation_future_mutation_cannot_change_policy_or_action_identity() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(61))
    fit_dates = set(dates[:44])
    calibration_dates = set(dates[44:59])
    validation_dates = set(dates[59:])
    rows = _policy_rows(dates)
    baseline = fit_radar_sequence_policy(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
        validation_dates=validation_dates,
    )
    changed = [dict(row) for row in rows]
    for row in changed:
        if date.fromisoformat(str(row["signal_date"])) in validation_dates:
            row["formal_touch_within_3m"] = not row["formal_touch_within_3m"]
            row["d1_net_return_pct"] = 99.0
            row["original_account_identity"] = True
    rerun = fit_radar_sequence_policy(
        changed,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
        validation_dates=validation_dates,
    )

    assert baseline["candidate_model"].fingerprint == rerun["candidate_model"].fingerprint
    assert baseline["action_model"].fingerprint == rerun["action_model"].fingerprint
    assert baseline["threshold"] == rerun["threshold"]
    assert [
        (row["signal_date"], row["signal_time"], row["vt_symbol"])
        for row in baseline["validation_actions"]
    ] == [
        (row["signal_date"], row["signal_time"], row["vt_symbol"])
        for row in rerun["validation_actions"]
    ]


def _policy_rows(dates: tuple[date, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for date_index, trade_date in enumerate(dates):
        for minute_index, signal_time in enumerate(("10:00", "10:01")):
            for symbol_index, symbol in enumerate(("600001.SSE", "600002.SSE")):
                offset = date_index + minute_index + symbol_index
                label = bool((date_index + symbol_index) % 3 == 0)
                rows.append(
                    {
                        "signal_date": trade_date.isoformat(),
                        "signal_time": signal_time,
                        "vt_symbol": symbol,
                        "rank_score": 50.0 + symbol_index,
                        "sequence_features": {
                            name: float((index + 1) * 0.1 + offset * 0.01)
                            for index, name in enumerate(FIRST_LAYER_FEATURE_NAMES)
                        },
                        "formal_touch_within_3m": label,
                    }
                )
    return rows
