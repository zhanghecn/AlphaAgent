from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CONTRACT_VERSION,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_model import (
    ACTION_FEATURE_FIELDS,
    ACTION_MODEL_PARAMETERS,
    ACTION_SCORE_FIELD,
    EVENT_MODEL_PARAMETERS,
    EVENT_SCORE_FIELD,
    IDENTITY_MODEL_PARAMETERS,
    IDENTITY_SCORE_FIELD,
    build_action_training_batch,
    build_event_training_batch,
    build_identity_training_batch,
    build_walk_forward_top1,
    calibrate_point_actions,
    fit_action_model,
    fit_event_model,
    fit_identity_ranker,
    score_action_rows,
    score_event_rows,
    score_frozen_point_top1,
    score_identity_rows,
    select_point_actions,
    select_point_top1,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _row(
    trade_date: date,
    symbol: str,
    *,
    frame_id: int,
    second: int = 0,
    event: bool = False,
    identity: bool = False,
    lane_rank: float = 70.0,
    feature_seed: float = 0.0,
) -> dict[str, object]:
    captured_at = datetime.combine(
        trade_date,
        datetime.min.time(),
        SHANGHAI,
    ).replace(hour=10, minute=15, second=second)
    frame_features = {
        field: feature_seed + index * 0.001
        for index, field in enumerate(FRAME_FEATURE_FIELDS)
    }
    identity_features = {
        field: feature_seed + index * 0.002
        for index, field in enumerate(IDENTITY_FEATURE_FIELDS)
    }
    identity_features["candidate_lane_rank_score"] = lane_rank
    return {
        "contract_version": CONTRACT_VERSION,
        "trade_date": trade_date,
        "captured_at": captured_at,
        "frame_id": frame_id,
        "vt_symbol": symbol,
        "action_frame_eligible": True,
        "action_previous_frame_gap_seconds": 15.0,
        "action_quote_coverage_ratio": 1.0,
        "action_market_timing_observed": True,
        "formal_two_slot_observed": True,
        "formal_two_slot_symbols": [],
        "frame_features": frame_features,
        "identity_features": identity_features,
        "label_status": "known",
        "formal_event_within_60s": event,
        "formal_identity_within_60s": identity,
    }


def _model_rows(dates: tuple[date, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        event = index % 2 == 0
        frame_id = 10_000 + index
        rows.extend(
            [
                _row(
                    trade_date,
                    "600001.SSE",
                    frame_id=frame_id,
                    event=event,
                    identity=event,
                    lane_rank=80.0,
                    feature_seed=float(index) / 20.0,
                ),
                _row(
                    trade_date,
                    "600002.SSE",
                    frame_id=frame_id,
                    event=event,
                    identity=False,
                    lane_rank=70.0,
                    feature_seed=float(index) / 20.0,
                ),
            ]
        )
    return rows


def test_event_training_is_one_row_per_frame_and_equal_weight_per_date() -> None:
    first = date(2026, 7, 21)
    second = date(2026, 7, 22)
    rows = [
        _row(first, "600001.SSE", frame_id=1, event=False),
        _row(first, "600002.SSE", frame_id=1, event=False),
        _row(first, "600003.SSE", frame_id=2, second=15, event=True),
        _row(second, "600001.SSE", frame_id=3, event=False),
        _row(second, "600001.SSE", frame_id=4, second=15, event=True),
        _row(second, "600001.SSE", frame_id=5, second=30, event=False),
        _row(second, "600001.SSE", frame_id=6, second=45, event=True),
    ]

    matrix, labels, weights, keys = build_event_training_batch(
        rows,
        {first, second},
    )

    assert matrix.shape == (6, len(FRAME_FEATURE_FIELDS))
    assert labels.tolist() == [0, 1, 0, 1, 0, 1]
    totals: dict[str, float] = {}
    for key, weight in zip(keys, weights, strict=True):
        totals[key[0]] = totals.get(key[0], 0.0) + float(weight)
    assert totals == pytest.approx({first.isoformat(): 1.0, second.isoformat(): 1.0})


def test_identity_groups_never_cross_frame_and_ignore_event_negative_frames() -> None:
    first = date(2026, 7, 21)
    second = date(2026, 7, 22)
    rows = [
        _row(first, "600001.SSE", frame_id=1, event=True, identity=True),
        _row(first, "600002.SSE", frame_id=1, event=True, identity=False),
        _row(second, "600001.SSE", frame_id=2, event=True, identity=False),
        _row(second, "600002.SSE", frame_id=2, event=True, identity=True),
        _row(second, "600003.SSE", frame_id=2, event=True, identity=False),
        _row(second, "600004.SSE", frame_id=3, second=15, event=False),
    ]

    matrix, labels, groups, keys = build_identity_training_batch(
        rows,
        {first, second},
    )

    assert matrix.shape == (
        5,
        len(FRAME_FEATURE_FIELDS) + len(IDENTITY_FEATURE_FIELDS),
    )
    assert labels.tolist() == [1, 0, 0, 1, 0]
    assert groups == (2, 3)
    assert len({key[:3] for key in keys[:2]}) == 1
    assert len({key[:3] for key in keys[2:]}) == 1
    assert keys[1][:3] != keys[2][:3]


def test_identity_training_ignores_event_groups_without_a_reachable_identity() -> None:
    trade_date = date(2026, 7, 21)
    rows = [
        _row(trade_date, "600001.SSE", frame_id=1, event=True, identity=False),
        _row(trade_date, "600002.SSE", frame_id=1, event=True, identity=False),
        _row(
            trade_date,
            "600003.SSE",
            frame_id=2,
            second=15,
            event=True,
            identity=True,
        ),
        _row(
            trade_date,
            "600004.SSE",
            frame_id=2,
            second=15,
            event=True,
            identity=False,
        ),
    ]

    _matrix, labels, groups, keys = build_identity_training_batch(
        rows,
        {trade_date},
    )

    assert labels.tolist() == [1, 0]
    assert groups == (2,)
    assert {key[-1] for key in keys} == {"600003.SSE", "600004.SSE"}


def test_identity_training_rejects_multiple_reachable_identities() -> None:
    trade_date = date(2026, 7, 21)
    rows = [
        _row(trade_date, "600001.SSE", frame_id=1, event=True, identity=True),
        _row(trade_date, "600002.SSE", frame_id=1, event=True, identity=True),
    ]

    with pytest.raises(
        ValueError,
        match="identity frame must contain exactly one reachable identity",
    ):
        build_identity_training_batch(rows, {trade_date})


def test_top1_is_stable_by_identity_score_lane_rank_then_symbol() -> None:
    trade_date = date(2026, 7, 21)
    rows = [
        {
            **_row(
                trade_date,
                "600002.SSE",
                frame_id=1,
                event=True,
                lane_rank=80.0,
            ),
            EVENT_SCORE_FIELD: 0.85,
            IDENTITY_SCORE_FIELD: 1.20,
        },
        {
            **_row(
                trade_date,
                "600001.SSE",
                frame_id=1,
                event=True,
                identity=True,
                lane_rank=80.0,
            ),
            EVENT_SCORE_FIELD: 0.85,
            IDENTITY_SCORE_FIELD: 1.20,
        },
        {
            **_row(
                trade_date,
                "600003.SSE",
                frame_id=1,
                event=True,
                lane_rank=99.0,
            ),
            EVENT_SCORE_FIELD: 0.85,
            IDENTITY_SCORE_FIELD: 1.10,
        },
    ]

    selected = select_point_top1(rows)

    assert len(selected) == 1
    assert selected[0]["vt_symbol"] == "600001.SSE"
    assert selected[0]["candidate_count"] == 3
    assert selected[0]["top1_margin"] == pytest.approx(0.0)


def test_event_and_identity_models_fail_closed_when_training_signal_is_missing() -> None:
    trade_date = date(2026, 7, 21)
    negative_rows = [
        _row(trade_date, "600001.SSE", frame_id=1, event=False),
        _row(trade_date, "600002.SSE", frame_id=1, event=False),
    ]

    event = fit_event_model(negative_rows, {trade_date})
    identity = fit_identity_ranker(negative_rows, {trade_date})

    assert event.status == "not_ready_event_classes"
    assert event.model is None
    assert identity.status == "not_ready_identity_groups"
    assert identity.model is None


def test_walk_forward_blocks_never_read_scored_or_future_dates() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(40))
    rows = _model_rows(dates)

    baseline = build_walk_forward_top1(rows, set(dates))
    changed = deepcopy(rows)
    for row in changed:
        if row["trade_date"] >= dates[30]:
            changed_event = not bool(row["formal_event_within_60s"])
            row["formal_event_within_60s"] = changed_event
            row["formal_identity_within_60s"] = bool(
                changed_event and row["vt_symbol"] == "600002.SSE"
            )
            row["identity_features"]["candidate_gain_pct"] = 999.0
            row["future_d1_return"] = 99.0
    repeated = build_walk_forward_top1(changed, set(dates))

    first_block = [row for row in baseline if row["trade_date"] < dates[25]]
    repeated_first_block = [row for row in repeated if row["trade_date"] < dates[25]]
    assert first_block == repeated_first_block
    assert first_block
    assert all(row["oof_training_date_end"] < row["trade_date"] for row in baseline)
    assert all(row["oof_event_model_fingerprint"] for row in baseline)
    assert all(row["oof_identity_model_fingerprint"] for row in baseline)


def test_action_target_belongs_to_selected_top1_not_another_positive_candidate() -> None:
    trade_date = date(2026, 7, 21)
    rows = [
        {
            **_row(
                trade_date,
                "600001.SSE",
                frame_id=1,
                event=True,
                identity=False,
                lane_rank=80.0,
            ),
            EVENT_SCORE_FIELD: 0.90,
            IDENTITY_SCORE_FIELD: 2.0,
            "oof_training_date_end": date(2026, 7, 20),
            "oof_event_model_fingerprint": "sha256:event",
            "oof_identity_model_fingerprint": "sha256:identity",
        },
        {
            **_row(
                trade_date,
                "600002.SSE",
                frame_id=1,
                event=True,
                identity=True,
                lane_rank=70.0,
            ),
            EVENT_SCORE_FIELD: 0.90,
            IDENTITY_SCORE_FIELD: 1.0,
            "oof_training_date_end": date(2026, 7, 20),
            "oof_event_model_fingerprint": "sha256:event",
            "oof_identity_model_fingerprint": "sha256:identity",
        },
    ]
    top1 = select_point_top1(rows)

    matrix, labels, keys = build_action_training_batch(top1)

    assert matrix.shape == (1, len(ACTION_FEATURE_FIELDS))
    assert labels.tolist() == [0]
    assert keys[0][-1] == "600001.SSE"


def test_action_model_uses_frozen_logistic_pipeline_and_is_deterministic() -> None:
    dates = tuple(date(2026, 7, 1) + timedelta(days=index) for index in range(4))
    rows = []
    for index, trade_date in enumerate(dates):
        row = _row(
            trade_date,
            f"{600001 + index}.SSE",
            frame_id=index + 1,
            event=True,
            identity=index % 2 == 0,
            feature_seed=float(index),
        )
        row.update(
            {
                EVENT_SCORE_FIELD: 0.60 + index * 0.05,
                IDENTITY_SCORE_FIELD: 0.10 + index * 0.10,
                "top1_margin": 0.05,
                "candidate_count": 2,
                "oof_training_date_end": trade_date - timedelta(days=1),
                "oof_event_model_fingerprint": "sha256:event",
                "oof_identity_model_fingerprint": "sha256:identity",
            }
        )
        rows.append(row)

    first = fit_action_model(rows)
    second = fit_action_model(deepcopy(rows))

    assert first.status == "ready"
    assert first.fingerprint == second.fingerprint
    assert first.pipeline.named_steps["logistic"].class_weight is None
    assert first.pipeline.named_steps["logistic"].max_iter == 2_000
    assert set(first.coefficient_by_feature) == set(ACTION_FEATURE_FIELDS)
    assert ACTION_MODEL_PARAMETERS == {
        "class_weight": None,
        "max_iter": 2_000,
        "random_state": 0,
    }


def test_calibration_requires_twenty_stock_days_and_seventy_percent() -> None:
    rows = []
    for index in range(20):
        trade_date = date(2026, 7, 1) + timedelta(days=index)
        row = _row(
            trade_date,
            f"{600001 + index}.SSE",
            frame_id=index + 1,
            event=True,
            identity=index < 14,
        )
        row[ACTION_SCORE_FIELD] = 0.80
        rows.append(row)

    ready = calibrate_point_actions(rows)
    too_few = calibrate_point_actions(
        [{**row, "formal_identity_within_60s": True} for row in rows[:19]]
    )
    low_precision = calibrate_point_actions(
        [
            {**row, "formal_identity_within_60s": index < 13}
            for index, row in enumerate(rows)
        ]
    )
    full_pool_reachable = {
        (row["trade_date"].isoformat(), str(row["vt_symbol"]))
        for row in rows[:14]
    } | {
        ((date(2026, 8, 1) + timedelta(days=index)).isoformat(), f"000{index:03d}.SZSE")
        for index in range(14)
    }
    pool_aware = calibrate_point_actions(
        rows,
        reachable_stock_day_pairs=full_pool_reachable,
    )

    assert ready.status == "ready"
    assert ready.threshold == pytest.approx(0.80)
    assert ready.selected_metrics["stock_day_action_count"] == 20
    assert ready.selected_metrics["formal_identity_precision"] == pytest.approx(0.70)
    assert pool_aware.selected_metrics["reachable_recall"] == pytest.approx(0.50)
    assert too_few.status == "insufficient_calibration_actions"
    assert too_few.threshold is None
    assert low_precision.status == "calibration_precision_gate_failed"
    assert low_precision.threshold is None
    assert select_point_actions(low_precision.metrics_by_threshold, threshold=None) == []


def test_action_training_and_selection_reject_ineligible_frames() -> None:
    trade_date = date(2026, 7, 21)
    row = _row(
        trade_date,
        "600001.SSE",
        frame_id=1,
        event=True,
        identity=True,
    )
    row.update(
        {
            "action_frame_eligible": False,
            EVENT_SCORE_FIELD: 0.90,
            IDENTITY_SCORE_FIELD: 1.0,
            ACTION_SCORE_FIELD: 0.95,
            "top1_margin": 0.20,
            "candidate_count": 1,
            "oof_training_date_end": trade_date - timedelta(days=1),
            "oof_event_model_fingerprint": "sha256:event",
            "oof_identity_model_fingerprint": "sha256:identity",
        }
    )

    matrix, labels, keys = build_action_training_batch([row])

    assert matrix.shape == (0, len(ACTION_FEATURE_FIELDS))
    assert labels.tolist() == []
    assert keys == ()
    assert select_point_actions([row], threshold=0.70) == []


def test_frozen_lightgbm_parameters_are_exact() -> None:
    assert EVENT_MODEL_PARAMETERS == {
        "objective": "binary",
        "n_estimators": 160,
        "learning_rate": 0.025,
        "num_leaves": 7,
        "max_depth": 3,
        "min_child_samples": 50,
        "reg_alpha": 2,
        "reg_lambda": 8,
        "colsample_bytree": 0.8,
        "random_state": 0,
        "deterministic": True,
        "force_col_wise": True,
        "n_jobs": 1,
    }
    assert IDENTITY_MODEL_PARAMETERS == {
        "objective": "lambdarank",
        "metric": "ndcg",
        "n_estimators": 120,
        "learning_rate": 0.03,
        "num_leaves": 7,
        "max_depth": 3,
        "min_child_samples": 20,
        "reg_alpha": 1,
        "reg_lambda": 5,
        "colsample_bytree": 0.8,
        "random_state": 0,
        "deterministic": True,
        "force_col_wise": True,
        "n_jobs": 1,
    }


def test_frozen_artifact_scoring_matches_in_memory_three_stage_models() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(40))
    rows = _model_rows(dates)
    event = fit_event_model(rows, set(dates))
    identity = fit_identity_ranker(rows, set(dates))
    oof = build_walk_forward_top1(rows, set(dates))
    action = fit_action_model(oof)
    scoring_rows = [row for row in rows if row["trade_date"] == dates[-1]]
    scoring_rows.extend(
        [
            _row(
                dates[-1],
                "600003.SSE",
                frame_id=20_000,
                second=15,
                lane_rank=75.0,
                feature_seed=2.10,
            ),
            _row(
                dates[-1],
                "600004.SSE",
                frame_id=20_000,
                second=15,
                lane_rank=85.0,
                feature_seed=2.20,
            ),
            _row(
                dates[-1],
                "600005.SSE",
                frame_id=20_000,
                second=15,
                lane_rank=65.0,
                feature_seed=2.00,
            ),
        ]
    )

    in_memory = score_action_rows(
        select_point_top1(
            score_identity_rows(score_event_rows(scoring_rows, event), identity)
        ),
        action,
    )
    model_record = {
        "event_model_fingerprint": event.fingerprint,
        "identity_model_fingerprint": identity.fingerprint,
        "action_model_fingerprint": action.fingerprint,
        "model_artifact": {
            "event_booster_model_text": event.booster_model_text,
            "identity_booster_model_text": identity.booster_model_text,
            "action_scaler_mean_by_feature": action.scaler_mean_by_feature,
            "action_scaler_scale_by_feature": action.scaler_scale_by_feature,
            "action_coefficient_by_feature": action.coefficient_by_feature,
            "action_intercept": action.intercept,
        },
    }
    frozen = score_frozen_point_top1(scoring_rows, model_record)
    reversed_frozen = score_frozen_point_top1(
        list(reversed(scoring_rows)),
        model_record,
    )

    assert event.status == identity.status == action.status == "ready"
    assert len(in_memory) == len(frozen) == 2
    assert reversed_frozen == frozen
    for expected, actual in zip(in_memory, frozen, strict=True):
        assert (actual["frame_id"], actual["vt_symbol"]) == (
            expected["frame_id"],
            expected["vt_symbol"],
        )
        assert actual[EVENT_SCORE_FIELD] == pytest.approx(
            expected[EVENT_SCORE_FIELD], abs=1e-10
        )
        assert actual[IDENTITY_SCORE_FIELD] == pytest.approx(
            expected[IDENTITY_SCORE_FIELD], abs=1e-10
        )
        assert actual[ACTION_SCORE_FIELD] == pytest.approx(
            expected[ACTION_SCORE_FIELD], abs=1e-10
        )
        assert actual["top1_margin"] == pytest.approx(
            expected["top1_margin"], abs=1e-10
        )
        assert actual["candidate_count"] == expected["candidate_count"]
        assert actual["identity_rank"] == expected["identity_rank"] == 1
        assert actual["event_model_fingerprint"] == event.fingerprint
        assert actual["identity_model_fingerprint"] == identity.fingerprint
        assert actual["action_model_fingerprint"] == action.fingerprint
