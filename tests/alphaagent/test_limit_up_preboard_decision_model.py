from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
)
from alphaagent.server.services.limit_up.preboard_decision_features import (
    MODEL_FEATURE_NAMES,
)
from alphaagent.server.services.limit_up.preboard_decision_model import (
    deserialize_preboard_model_bundle,
    fit_preboard_model,
    qualify_preboard_probabilities,
    score_preboard_candidate,
    serialize_preboard_model_bundle,
)


def test_model_has_only_two_touch_heads_and_keeps_d1_out_of_features() -> None:
    rows, fit_dates, calibration_dates = _training_rows()

    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    assert bundle.status == "ready"
    assert bundle.model_version == PREBOARD_DECISION_VERSION
    assert set(bundle.head_reports) == {"touch_3m", "eventual_touch"}
    assert set(bundle.feature_names) == set(MODEL_FEATURE_NAMES)
    assert not {
        "d1_net_return_pct",
        "d1_trade_win",
        "formal_d1_premium_win",
        "seal_success_rate",
    }.intersection(bundle.feature_names)


def test_probability_qualification_is_clustered_by_stock_day() -> None:
    rows: list[dict[str, object]] = []
    start = date(2026, 5, 1)
    for index in range(40):
        positive = index < 20
        trade_date = start + timedelta(days=index)
        for _ in range(5):
            rows.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "vt_symbol": f"600{index:03d}.SSE",
                    "probability_status": "ready",
                    "touch_probability_3m": 0.9 if positive else 0.1,
                    "eventual_touch_probability": 0.95 if positive else 0.05,
                    "formal_touch_within_3m": positive,
                    "eventual_formal_touch": positive,
                }
            )

    report = qualify_preboard_probabilities(rows)

    assert report["status"] == "ready"
    assert report["stock_day_count"] == 40
    for head in ("touch_3m", "eventual_touch"):
        metrics = report["heads"][head]
        assert metrics["evaluation_unit"] == "stock_day_equal_weighted_point_time"
        assert metrics["point_count"] == 200
        assert metrics["stock_day_weight_sum"] == 40.0
        assert metrics["positive_stock_days"] == 20
        assert metrics["negative_stock_days"] == 20
        assert metrics["brier"] < metrics["climatology_brier"]
        assert metrics["brier_skill"] > 0
        assert metrics["pr_auc"] > metrics["base_rate"]
        assert metrics["top_quintile_rate"] > metrics["base_rate"]
        assert metrics["top_quintile_lift"] > 1.0
        assert len(metrics["quantile_touch_rates"]) == 5
        assert metrics["calibration_points"]


def test_probability_qualification_does_not_pair_daily_peak_with_later_label() -> None:
    rows: list[dict[str, object]] = []
    start = date(2026, 5, 1)
    for index in range(40):
        positive = index < 20
        trade_date = start + timedelta(days=index)
        rows.extend(
            [
                {
                    "trade_date": trade_date.isoformat(),
                    "vt_symbol": f"600{index:03d}.SSE",
                    "probability_status": "ready",
                    "touch_probability_3m": 0.99 if positive else 0.01,
                    "eventual_touch_probability": 0.99 if positive else 0.01,
                    "formal_touch_within_3m": False,
                    "eventual_formal_touch": positive,
                },
                {
                    "trade_date": trade_date.isoformat(),
                    "vt_symbol": f"600{index:03d}.SSE",
                    "probability_status": "ready",
                    "touch_probability_3m": 0.01,
                    "eventual_touch_probability": 0.99 if positive else 0.01,
                    "formal_touch_within_3m": positive,
                    "eventual_formal_touch": positive,
                },
            ]
        )

    report = qualify_preboard_probabilities(rows)

    touch = report["heads"]["touch_3m"]
    assert report["status"] == "model_unavailable"
    assert touch["top_quintile_lift"] > 1.0
    assert touch["brier"] > touch["climatology_brier"]
    assert "brier_not_better_than_climatology" in touch["reasons"]


def test_probability_qualification_rejects_too_few_negative_stock_days() -> None:
    rows = [
        {
            "trade_date": (date(2026, 5, 1) + timedelta(days=index)).isoformat(),
            "vt_symbol": f"600{index:03d}.SSE",
            "probability_status": "ready",
            "touch_probability_3m": 0.9,
            "eventual_touch_probability": 0.9,
            "formal_touch_within_3m": True,
            "eventual_formal_touch": True,
        }
        for index in range(25)
    ]

    report = qualify_preboard_probabilities(rows)

    assert report["status"] == "model_unavailable"
    assert "touch_3m:negative_stock_days_below_20" in report["reasons"]


def test_fit_weights_each_stock_day_equally_despite_prefix_count() -> None:
    rows, fit_dates, calibration_dates = _training_rows(variable_prefixes=True)

    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    report = bundle.head_reports["touch_3m"]
    assert report["fit_pair_weight_sum_min"] == 1.0
    assert report["fit_pair_weight_sum_max"] == 1.0
    assert report["calibration_pair_weight_sum_min"] == 1.0
    assert report["calibration_pair_weight_sum_max"] == 1.0


def test_validation_labels_do_not_change_model_fingerprint() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    validation_date = max(calibration_dates) + timedelta(days=1)
    validation = _row(validation_date, "600999.SSE", 0, positive=False)
    first = fit_preboard_model(
        [*rows, validation],
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )
    changed = {
        **validation,
        "formal_touch_within_3m": True,
        "eventual_formal_touch": True,
    }
    second = fit_preboard_model(
        [*rows, changed],
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    assert first.fingerprint == second.fingerprint


def test_quality_failed_rows_cannot_fit_or_score() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    for row in rows:
        row["quality_gate_passed"] = False

    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )
    score = score_preboard_candidate(bundle, rows[0])

    assert bundle.status == "insufficient_fit"
    assert score["probability_status"] == "quality_gate_failed"
    assert score["touch_probability_3m"] is None
    assert score["eventual_touch_probability"] is None


def test_calibration_requires_positive_and_negative_stock_days() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    for row in rows:
        if date.fromisoformat(str(row["trade_date"])) in calibration_dates:
            row["formal_touch_within_3m"] = False
            row["eventual_formal_touch"] = False

    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    assert bundle.status == "insufficient_calibration"
    assert bundle.head_reports["touch_3m"]["status"] == (
        "insufficient_calibration_classes"
    )


def test_calibration_requires_twenty_effective_stock_days() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    retained_calibration_dates = set(sorted(calibration_dates)[:4])
    rows = [
        row
        for row in rows
        if date.fromisoformat(str(row["trade_date"])) not in calibration_dates
        or date.fromisoformat(str(row["trade_date"])) in retained_calibration_dates
    ]

    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    assert bundle.status == "insufficient_calibration"
    assert bundle.head_reports["touch_3m"]["calibration_pair_count"] == 16
    assert bundle.head_reports["touch_3m"]["status"] == (
        "insufficient_calibration_pairs"
    )


def test_score_preserves_historical_priors_and_probabilities_are_bounded() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )
    row = {
        **rows[0],
        "expected_d1_net_return_pct": 1.35,
        "d1_win_probability": 0.68,
        "seal_probability_given_touch": 0.74,
        "d1_win_probability_given_seal": 0.63,
    }

    score = score_preboard_candidate(bundle, row)

    assert score["probability_status"] == "ready"
    assert 0.0 <= float(score["touch_probability_3m"]) <= 1.0
    assert 0.0 <= float(score["eventual_touch_probability"]) <= 1.0
    assert score["expected_d1_net_return_pct"] == 1.35
    assert score["d1_win_probability"] == 0.68
    assert score["seal_probability_given_touch"] == 0.74
    assert score["d1_win_probability_given_seal"] == 0.63


def test_missing_transaction_values_are_nan_not_zero_and_remain_scoreable() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )
    row = {**rows[0], "feature_values": dict(rows[0]["feature_values"])}
    row["feature_values"]["tx_large_print_turnover_share_1m"] = None
    row["feature_values"]["tx_large_print_turnover_share_1m_missing"] = 1.0
    row["feature_values"]["transaction_flow_missing"] = 1.0

    score = score_preboard_candidate(bundle, row)

    assert score["probability_status"] == "ready"


def test_fit_drops_all_missing_columns_and_scores_with_the_same_projection() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    for row in rows:
        row["feature_values"]["main_net_inflow_delta_3m"] = None
        row["feature_values"]["main_net_inflow_delta_3m_missing"] = 1.0

    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    assert bundle.status == "ready"
    for report in bundle.head_reports.values():
        assert "main_net_inflow_delta_3m" in report["dropped_fit_feature_names"]
    assert score_preboard_candidate(bundle, rows[0])["probability_status"] == "ready"


def test_monotonic_constraints_do_not_reduce_probability_when_board_is_nearer() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )
    far = {**rows[0], "feature_values": dict(rows[0]["feature_values"])}
    near = {**rows[0], "feature_values": dict(rows[0]["feature_values"])}
    far["feature_values"].update(gain_pct=4.0, distance_to_limit_pct=5.0)
    near["feature_values"].update(gain_pct=8.0, distance_to_limit_pct=1.0)

    far_score = score_preboard_candidate(bundle, far)
    near_score = score_preboard_candidate(bundle, near)

    assert float(near_score["touch_probability_3m"]) >= float(
        far_score["touch_probability_3m"]
    )
    assert float(near_score["eventual_touch_probability"]) >= float(
        far_score["eventual_touch_probability"]
    )


def test_model_artifact_round_trip_keeps_fingerprint_and_scores() -> None:
    rows, fit_dates, calibration_dates = _training_rows()
    bundle = fit_preboard_model(
        rows,
        fit_dates=fit_dates,
        calibration_dates=calibration_dates,
    )

    restored = deserialize_preboard_model_bundle(
        serialize_preboard_model_bundle(bundle)
    )

    assert restored.fingerprint == bundle.fingerprint
    assert score_preboard_candidate(restored, rows[0]) == score_preboard_candidate(
        bundle,
        rows[0],
    )


def _training_rows(
    *,
    variable_prefixes: bool = False,
) -> tuple[list[dict[str, object]], set[date], set[date]]:
    start = date(2026, 1, 5)
    fit_dates = {start + timedelta(days=index) for index in range(12)}
    calibration_dates = {start + timedelta(days=12 + index) for index in range(6)}
    rows: list[dict[str, object]] = []
    for trade_date in sorted(fit_dates | calibration_dates):
        for symbol_index in range(4):
            prefix_count = symbol_index + 1 if variable_prefixes else 2
            positive = symbol_index % 2 == 0
            for prefix_index in range(prefix_count):
                rows.append(
                    _row(
                        trade_date,
                        f"600{symbol_index:03d}.SSE",
                        prefix_index,
                        positive=positive,
                    )
                )
    return rows, fit_dates, calibration_dates


def _row(
    trade_date: date,
    symbol: str,
    prefix_index: int,
    *,
    positive: bool,
) -> dict[str, object]:
    gain = (7.2 if positive else 3.6) + prefix_index * 0.15
    values = {
        name: round(0.1 + feature_index * 0.002 + prefix_index * 0.01, 8)
        for feature_index, name in enumerate(MODEL_FEATURE_NAMES)
    }
    values.update(
        gain_pct=gain,
        distance_to_limit_pct=10.0 - gain,
        transaction_flow_missing=0.0,
    )
    for name in MODEL_FEATURE_NAMES:
        if name.endswith("_missing"):
            values[name] = 0.0
    return {
        "trade_date": trade_date.isoformat(),
        "signal_date": trade_date.isoformat(),
        "decision_at": f"{trade_date.isoformat()}T10:{prefix_index:02d}:00",
        "known_at": f"{trade_date.isoformat()}T10:{prefix_index:02d}:00",
        "vt_symbol": symbol,
        "board_lane": "first_board",
        "state": "near_limit",
        "change_pct": gain,
        "last_price": 10.0 + gain / 10.0,
        "limit_price": 11.0,
        "quality_gate_passed": True,
        "feature_contract_version": PREBOARD_DECISION_VERSION,
        "feature_status": "scoreable",
        "feature_fingerprint": "sha256:" + "a" * 64,
        "feature_names": list(MODEL_FEATURE_NAMES),
        "feature_values": values,
        "formal_touch_within_3m": positive and prefix_index >= 1,
        "eventual_formal_touch": positive,
    }
