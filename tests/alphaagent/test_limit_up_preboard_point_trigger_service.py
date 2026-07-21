from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    PointTriggerDayAudit,
)
from alphaagent.server.services.limit_up import (
    preboard_point_trigger_service as service,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = date(2026, 7, 21)
CAPTURED_AT = datetime(2026, 7, 21, 10, 15, 15, tzinfo=SHANGHAI)
FIT_DATES = tuple(TRADE_DATE + timedelta(days=index) for index in range(40))
CALIBRATION_DATES = tuple(
    FIT_DATES[-1] + timedelta(days=index + 1) for index in range(15)
)
MODEL_FROZEN_AT = datetime.combine(
    CALIBRATION_DATES[-1],
    datetime.min.time().replace(hour=21, minute=30),
    tzinfo=SHANGHAI,
)
RUNTIME_FINGERPRINT = "sha256:" + "d" * 64


@pytest.fixture(autouse=True)
def _stable_capture_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "capture_runtime_fingerprint_safely",
        lambda: RUNTIME_FINGERPRINT,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "load_day_capture_runtime_fingerprint_state",
        lambda _trade_date: {
            "frame_count": 2,
            "missing_count": 0,
            "unique_count": 1,
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
        },
        raising=False,
    )


def _audit() -> PointTriggerDayAudit:
    return PointTriggerDayAudit(
        contract_version=CONTRACT_VERSION,
        trade_date=TRADE_DATE,
        status="complete",
        is_complete=True,
        eligible_for_model=True,
        reason_codes=(),
        frame_count=720,
        observation_count=20_000,
        metrics={
            "scan_interval_p90_seconds": 15.0,
            "formal_event_static_eligible_within_60s_count": 1,
        },
        capture_runtime_fingerprint=RUNTIME_FINGERPRINT,
    )


def _feature_row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "trade_date": TRADE_DATE,
        "captured_at": CAPTURED_AT,
        "frame_id": 2,
        "vt_symbol": "600001.SSE",
        "name": "Test",
        "last_price": 10.50,
        "limit_price": 11.00,
        "quote_observed_at": CAPTURED_AT,
        "action_frame_eligible": True,
        "action_previous_frame_gap_seconds": 15.0,
        "action_quote_coverage_ratio": 1.0,
        "action_market_timing_observed": True,
        "formal_two_slot_observed": True,
        "formal_two_slot_symbols": ["600009.SSE"],
        "frame_features": {field: 0.0 for field in FRAME_FEATURE_FIELDS},
        "identity_features": {field: 0.0 for field in IDENTITY_FEATURE_FIELDS},
        "label_status": "known",
        "formal_event_within_60s": True,
        "formal_identity_within_60s": True,
        "formal_identity_vt_symbol": "600001.SSE",
        "formal_event_at": CAPTURED_AT + timedelta(seconds=30),
    }
    values.update(overrides)
    return values


def _scope(index: int) -> dict[str, object]:
    trade_date = date(2026, 7, 21) + timedelta(days=index)
    return {
        "contract_version": CONTRACT_VERSION,
        "trade_date": trade_date,
        "status": "complete",
        "is_complete": True,
        "eligible_for_model": True,
        "cohort_fingerprint": f"sha256:{index:064x}",
    }


def _active_model() -> dict[str, object]:
    values: dict[str, object] = {
        "model_fingerprint": "sha256:" + "a" * 64,
        "contract_version": CONTRACT_VERSION,
        "status": "active",
        "fit_trade_dates": list(FIT_DATES),
        "calibration_trade_dates": list(CALIBRATION_DATES),
        "validation_trade_dates": [],
        "event_model_params": service.EVENT_MODEL_PARAMETERS,
        "identity_model_params": service.IDENTITY_MODEL_PARAMETERS,
        "action_model_params": service.ACTION_MODEL_PARAMETERS,
        "frame_feature_fields": list(FRAME_FEATURE_FIELDS),
        "identity_feature_fields": list(IDENTITY_FEATURE_FIELDS),
        "action_feature_fields": list(service.ACTION_FEATURE_FIELDS),
        "training_input_fingerprint": "sha256:" + "b" * 64,
        "calibration_threshold": 0.70,
        "calibration_metrics": {"status": "ready"},
        "event_model_fingerprint": "sha256:event",
        "identity_model_fingerprint": "sha256:identity",
        "action_model_fingerprint": "sha256:action",
        "model_artifact": {"format": service.MODEL_ARTIFACT_FORMAT},
        "frozen_at": MODEL_FROZEN_AT,
    }
    values["record_fingerprint"] = service.point_trigger_model_record_fingerprint(
        values
    )
    return values


def test_default_eod_target_uses_unfrozen_post_shakedown_date(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "load_frame_dates",
        lambda: [date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)],
    )
    monkeypatch.setattr(service, "load_point_trigger_day_scopes", lambda: [])

    assert (
        service._resolve_target_trade_date(
            datetime(2026, 7, 20, 21, 30, tzinfo=SHANGHAI),
            None,
        )
        is None
    )
    assert service._resolve_target_trade_date(
        datetime(2026, 7, 21, 21, 30, tzinfo=SHANGHAI),
        None,
    ) == date(2026, 7, 21)


def test_default_eod_target_recovers_oldest_unfrozen_radar_date(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "load_frame_dates",
        lambda: [date(2026, 7, 23), date(2026, 7, 22), date(2026, 7, 21)],
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_day_scopes",
        lambda: [{"trade_date": date(2026, 7, 22)}],
    )

    assert service._resolve_target_trade_date(
        datetime(2026, 7, 23, 21, 30, tzinfo=SHANGHAI),
        None,
    ) == date(2026, 7, 21)


def test_current_radar_day_cannot_freeze_before_market_close(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "load_frame_dates",
        lambda: [date(2026, 7, 21)],
    )
    monkeypatch.setattr(service, "load_point_trigger_day_scopes", lambda: [])

    before_close = datetime(2026, 7, 21, 14, 59, 59, tzinfo=SHANGHAI)
    after_close = datetime(2026, 7, 21, 15, 0, tzinfo=SHANGHAI)

    assert service._resolve_target_trade_date(before_close, None) is None
    assert service._resolve_target_trade_date(before_close, date(2026, 7, 21)) is None
    assert service._resolve_target_trade_date(after_close, None) == date(2026, 7, 21)


def test_previous_unfrozen_radar_day_can_recover_before_current_close(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service,
        "load_frame_dates",
        lambda: [date(2026, 7, 21), date(2026, 7, 22)],
    )
    monkeypatch.setattr(service, "load_point_trigger_day_scopes", lambda: [])

    assert service._resolve_target_trade_date(
        datetime(2026, 7, 22, 10, 30, tzinfo=SHANGHAI),
        None,
    ) == date(2026, 7, 21)


@pytest.mark.parametrize(
    ("explicit", "expected"),
    [
        (date(2026, 7, 20), None),
        (date(2026, 7, 21), date(2026, 7, 21)),
        (date(2026, 7, 22), None),
    ],
)
def test_explicit_eod_target_stays_after_shakedown_and_not_in_the_future(
    explicit: date,
    expected: date | None,
) -> None:
    assert (
        service._resolve_target_trade_date(
            datetime(2026, 7, 21, 21, 30, tzinfo=SHANGHAI),
            explicit,
        )
        == expected
    )


def test_eod_without_new_radar_date_still_settles_pending_actions(monkeypatch) -> None:
    settlements: list[datetime] = []
    monkeypatch.setattr(
        service,
        "_resolve_target_trade_date",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_audit_inputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no radar day should be loaded")
        ),
    )
    monkeypatch.setattr(service, "load_point_trigger_day_scopes", lambda: [])
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [])
    monkeypatch.setattr(
        service,
        "settle_point_trigger_actions",
        lambda *, as_of: (
            settlements.append(as_of) or {"action_count": 1, "stages_closed": 1}
        ),
    )

    result = service.sync_limit_up_preboard_point_trigger(as_of=CAPTURED_AT)

    assert settlements == [CAPTURED_AT]
    assert result["status"] == "collecting_fit"
    assert result["rows_written"] == 1
    assert result["day_freeze_status"] == "no_eligible_radar_day"
    assert result["message"] == "no eligible radar day"


def test_incomplete_audit_skips_full_model_observation_load(monkeypatch) -> None:
    incomplete = replace(
        _audit(),
        status="incomplete",
        is_complete=False,
        eligible_for_model=False,
        reason_codes=("fresh_quote_ratio_below_98pct",),
    )
    frozen: list[tuple[PointTriggerDayAudit, list[dict[str, object]]]] = []
    monkeypatch.setattr(
        service,
        "_resolve_target_trade_date",
        lambda *_args, **_kwargs: TRADE_DATE,
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_audit_inputs",
        lambda *_args, **_kwargs: ([{"id": 2}], []),
    )
    monkeypatch.setattr(
        service,
        "load_radar_observations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("incomplete audit must not load full model observations")
        ),
    )
    monkeypatch.setattr(
        service,
        "audit_point_trigger_day",
        lambda *_args: incomplete,
    )
    monkeypatch.setattr(
        service,
        "freeze_point_trigger_day",
        lambda audit, rows: (
            frozen.append((audit, list(rows)))
            or {"status": "incomplete", "rows_written": 0}
        ),
    )
    monkeypatch.setattr(service, "settle_point_trigger_actions", lambda **_kwargs: {})
    monkeypatch.setattr(service, "load_point_trigger_day_scopes", lambda: [])
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [])

    result = service.sync_limit_up_preboard_point_trigger(trade_date=TRADE_DATE)

    assert result["day_freeze_status"] == "incomplete"
    assert frozen == [(incomplete, [])]


def test_eod_runtime_mismatch_freezes_incomplete_without_full_observation_load(
    monkeypatch,
) -> None:
    frozen: list[tuple[PointTriggerDayAudit, list[dict[str, object]]]] = []
    monkeypatch.setattr(
        service,
        "_resolve_target_trade_date",
        lambda *_args, **_kwargs: TRADE_DATE,
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_audit_inputs",
        lambda *_args, **_kwargs: ([{"id": 2}], []),
    )
    monkeypatch.setattr(service, "audit_point_trigger_day", lambda *_args: _audit())
    monkeypatch.setattr(
        service,
        "capture_runtime_fingerprint_safely",
        lambda: "sha256:" + "e" * 64,
    )
    monkeypatch.setattr(
        service,
        "load_radar_observations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime mismatch must not load full model observations")
        ),
    )
    monkeypatch.setattr(
        service,
        "freeze_point_trigger_day",
        lambda audit, rows: (
            frozen.append((audit, list(rows)))
            or {"status": "frozen_incomplete", "rows_written": 0}
        ),
    )
    monkeypatch.setattr(service, "settle_point_trigger_actions", lambda **_kwargs: {})
    monkeypatch.setattr(service, "load_point_trigger_day_scopes", lambda: [])
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [])

    result = service.sync_limit_up_preboard_point_trigger(trade_date=TRADE_DATE)

    assert result["day_freeze_status"] == "frozen_incomplete"
    assert len(frozen) == 1
    audit, rows = frozen[0]
    assert audit.is_complete is False
    assert audit.eligible_for_model is False
    assert audit.status == "incomplete"
    assert "capture_runtime_fingerprint_current_mismatch" in audit.reason_codes
    assert rows == []


@pytest.mark.parametrize(
    ("complete_day_count", "expected_status"),
    [
        (39, "collecting_fit"),
        (40, "collecting_calibration"),
        (54, "collecting_calibration"),
    ],
)
def test_eod_before_fit_and_calibration_freeze_has_zero_models_and_actions(
    monkeypatch,
    complete_day_count: int,
    expected_status: str,
) -> None:
    frozen: list[tuple[PointTriggerDayAudit, list[dict[str, object]]]] = []
    model_saves: list[dict[str, object]] = []
    action_saves: list[dict[str, object]] = []
    monkeypatch.setattr(
        service, "_resolve_target_trade_date", lambda *_args, **_kwargs: TRADE_DATE
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_audit_inputs",
        lambda *_args, **_kwargs: ([{"id": 2}], []),
    )
    monkeypatch.setattr(
        service, "load_radar_observations", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(service, "audit_point_trigger_day", lambda *_args: _audit())
    monkeypatch.setattr(
        service, "build_point_trigger_rows", lambda *_args: [_feature_row()]
    )
    monkeypatch.setattr(
        service, "attach_point_trigger_labels", lambda rows, _future: list(rows)
    )
    monkeypatch.setattr(
        service,
        "freeze_point_trigger_day",
        lambda audit, rows: (
            frozen.append((audit, list(rows)))
            or {"status": "frozen", "rows_written": len(rows)}
        ),
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_day_scopes",
        lambda *_args, **_kwargs: [
            _scope(index) for index in range(complete_day_count)
        ],
    )
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [])
    monkeypatch.setattr(
        service, "save_point_trigger_model", lambda row: model_saves.append(dict(row))
    )
    monkeypatch.setattr(
        service, "save_point_trigger_action", lambda row: action_saves.append(dict(row))
    )
    monkeypatch.setattr(
        service, "settle_point_trigger_actions", lambda *_args, **_kwargs: {}
    )

    result = service.sync_limit_up_preboard_point_trigger(trade_date=TRADE_DATE)

    assert result["status"] == expected_status
    assert result["complete_day_count"] == complete_day_count
    assert len(frozen) == 1
    assert frozen[0][1][0]["formal_identity_within_60s"] is True
    assert frozen[0][0].metrics["label_known_row_count"] == 1
    assert frozen[0][0].metrics["reachable_formal_event_count"] == 1
    assert model_saves == []
    assert action_saves == []


def test_eod_reuses_the_single_frozen_model_instead_of_refitting(monkeypatch) -> None:
    monkeypatch.setattr(
        service, "_resolve_target_trade_date", lambda *_args, **_kwargs: TRADE_DATE
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_audit_inputs",
        lambda *_args, **_kwargs: ([{"id": 2}], []),
    )
    monkeypatch.setattr(
        service, "load_radar_observations", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(service, "audit_point_trigger_day", lambda *_args: _audit())
    monkeypatch.setattr(
        service, "build_point_trigger_rows", lambda *_args: [_feature_row()]
    )
    monkeypatch.setattr(
        service, "attach_point_trigger_labels", lambda rows, _future: list(rows)
    )
    monkeypatch.setattr(
        service,
        "freeze_point_trigger_day",
        lambda *_args: {"status": "already_frozen", "rows_written": 0},
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_day_scopes",
        lambda *_args, **_kwargs: [_scope(index) for index in range(55)],
    )
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [_active_model()])
    monkeypatch.setattr(
        service,
        "_fit_and_freeze_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not refit")
        ),
    )
    monkeypatch.setattr(
        service, "settle_point_trigger_actions", lambda *_args, **_kwargs: {}
    )

    result = service.sync_limit_up_preboard_point_trigger(trade_date=TRADE_DATE)

    assert result["status"] == "forward_collecting"
    assert result["model_fingerprint"] == _active_model()["model_fingerprint"]


def test_eod_waits_for_the_research_worker_instead_of_training_in_api(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service,
        "_resolve_target_trade_date",
        lambda *_args, **_kwargs: TRADE_DATE,
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_audit_inputs",
        lambda *_args, **_kwargs: ([{"id": 2}], []),
    )
    monkeypatch.setattr(
        service, "load_radar_observations", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(service, "audit_point_trigger_day", lambda *_args: _audit())
    monkeypatch.setattr(
        service, "build_point_trigger_rows", lambda *_args: [_feature_row()]
    )
    monkeypatch.setattr(
        service,
        "attach_point_trigger_labels",
        lambda rows, _future: list(rows),
    )
    monkeypatch.setattr(
        service,
        "freeze_point_trigger_day",
        lambda *_args: {"status": "frozen", "rows_written": 1},
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_day_scopes",
        lambda *_args, **_kwargs: [_scope(index) for index in range(55)],
    )
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [])
    monkeypatch.setattr(service, "settle_point_trigger_actions", lambda **_kwargs: {})
    monkeypatch.setattr(
        service,
        "_fit_and_freeze_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("API must not fit the research model")
        ),
    )

    result = service.sync_limit_up_preboard_point_trigger(trade_date=TRADE_DATE)

    assert result["status"] == "awaiting_research_model_fit"
    assert result["model_fingerprint"] is None
    assert result["model_status"] is None


def test_research_worker_entry_is_guarded_and_freezes_once(monkeypatch) -> None:
    calls: list[str] = []
    scopes = [_scope(index) for index in range(55)]
    monkeypatch.setattr(
        service,
        "require_research_runtime",
        lambda: calls.append("guarded"),
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_day_scopes",
        lambda *_args, **_kwargs: scopes,
    )
    monkeypatch.setattr(service, "load_point_trigger_models", lambda: [])
    monkeypatch.setattr(
        service,
        "_fit_and_freeze_model",
        lambda selected, frozen_at: {
            "status": "active",
            "model_fingerprint": "sha256:model",
            "selected_scope_count": len(selected),
            "frozen_at": frozen_at,
        },
    )

    result = service.fit_point_trigger_model_if_ready(as_of=CAPTURED_AT)

    assert calls == ["guarded"]
    assert result["status"] == "active"
    assert result["selected_scope_count"] == 55
    assert result["frozen_at"] == CAPTURED_AT


def test_fifty_fifth_complete_day_freezes_exact_40_15_model_once(monkeypatch) -> None:
    scopes = [_scope(index) for index in range(55)]
    event = SimpleNamespace(
        status="ready",
        fingerprint="sha256:event",
        booster_model_text="event-model",
    )
    identity = SimpleNamespace(
        status="ready",
        fingerprint="sha256:identity",
        booster_model_text="identity-model",
    )
    action = SimpleNamespace(
        status="ready",
        fingerprint="sha256:action",
        scaler_mean_by_feature={field: 0.0 for field in service.ACTION_FEATURE_FIELDS},
        scaler_scale_by_feature={field: 1.0 for field in service.ACTION_FEATURE_FIELDS},
        coefficient_by_feature={field: 0.0 for field in service.ACTION_FEATURE_FIELDS},
        intercept=0.0,
    )
    threshold = SimpleNamespace(
        status="ready",
        threshold=0.70,
        selected_metrics={
            "stock_day_action_count": 20,
            "formal_identity_precision": 0.70,
        },
        metrics_by_threshold=(),
    )
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(service, "load_point_trigger_feature_rows", lambda _dates: [])
    monkeypatch.setattr(service, "fit_event_model", lambda *_args: event)
    monkeypatch.setattr(service, "fit_identity_ranker", lambda *_args: identity)
    monkeypatch.setattr(service, "build_walk_forward_top1", lambda *_args: [])
    monkeypatch.setattr(service, "fit_action_model", lambda *_args: action)
    monkeypatch.setattr(service, "score_event_rows", lambda rows, _model: list(rows))
    monkeypatch.setattr(service, "score_identity_rows", lambda rows, _model: list(rows))
    monkeypatch.setattr(service, "select_point_top1", lambda rows: list(rows))
    monkeypatch.setattr(service, "score_action_rows", lambda rows, _model: list(rows))
    monkeypatch.setattr(
        service,
        "calibrate_point_actions",
        lambda _rows, **_kwargs: threshold,
    )
    monkeypatch.setattr(
        service,
        "save_point_trigger_model",
        lambda record: saved.append(dict(record)) or {"status": "frozen"},
    )

    result = service._fit_and_freeze_model(scopes, MODEL_FROZEN_AT)

    assert result["status"] == "active"
    assert result["model_written"] == 1
    assert len(saved) == 1
    assert saved[0]["fit_trade_dates"] == [row["trade_date"] for row in scopes[:40]]
    assert saved[0]["calibration_trade_dates"] == [
        row["trade_date"] for row in scopes[40:55]
    ]
    assert saved[0]["validation_trade_dates"] == []
    assert saved[0]["model_artifact"]["format"] == service.MODEL_ARTIFACT_FORMAT


def test_model_cannot_freeze_before_calibration_closes() -> None:
    scopes = [_scope(index) for index in range(55)]

    with pytest.raises(ValueError, match="before calibration closes"):
        service._fit_and_freeze_model(scopes, CAPTURED_AT)


def test_live_scoring_without_a_unique_active_model_has_zero_actions(
    monkeypatch,
) -> None:
    action_saves: list[dict[str, object]] = []
    monkeypatch.setattr(service, "load_active_point_trigger_model", lambda: None)
    monkeypatch.setattr(
        service, "save_point_trigger_action", lambda row: action_saves.append(dict(row))
    )

    result = service.score_live_point_trigger({"captured_at": CAPTURED_AT.isoformat()})

    assert result == {"status": "no_active_model", "action_saved": 0}
    assert action_saves == []


def test_live_scoring_rejects_active_model_with_shakedown_fit_date() -> None:
    model = _active_model()
    model["fit_trade_dates"] = [ELIGIBLE_AFTER, *FIT_DATES[1:]]

    with pytest.raises(ValueError, match="frozen contract"):
        service._validate_active_model(model)


def test_live_scoring_rejects_active_model_record_drift() -> None:
    model = _active_model()
    model["model_artifact"] = {
        **model["model_artifact"],
        "event_booster_model_text": "tampered-model",
    }

    with pytest.raises(ValueError, match="frozen contract"):
        service._validate_active_model(model)


@pytest.mark.parametrize(
    ("frame_fingerprint", "day_state", "runtime_fingerprint", "expected_status"),
    [
        (
            None,
            {
                "frame_count": 2,
                "missing_count": 0,
                "unique_count": 1,
                "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            },
            RUNTIME_FINGERPRINT,
            "no_action_capture_runtime_fingerprint_missing",
        ),
        (
            "not-a-fingerprint",
            {
                "frame_count": 2,
                "missing_count": 0,
                "unique_count": 1,
                "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            },
            RUNTIME_FINGERPRINT,
            "no_action_capture_runtime_fingerprint_invalid",
        ),
        (
            RUNTIME_FINGERPRINT,
            {
                "frame_count": 2,
                "missing_count": 0,
                "unique_count": 2,
                "capture_runtime_fingerprint": None,
            },
            RUNTIME_FINGERPRINT,
            "no_action_capture_runtime_fingerprint_changed",
        ),
        (
            RUNTIME_FINGERPRINT,
            {
                "frame_count": 2,
                "missing_count": 0,
                "unique_count": 1,
                "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            },
            "sha256:" + "e" * 64,
            "no_action_capture_runtime_fingerprint_mismatch",
        ),
    ],
)
def test_live_scoring_fails_closed_on_capture_runtime_state(
    monkeypatch,
    frame_fingerprint: str | None,
    day_state: dict[str, object],
    runtime_fingerprint: str,
    expected_status: str,
) -> None:
    frames = [
        {
            "id": 1,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT - timedelta(seconds=15),
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": [],
        },
        {
            "id": 2,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT,
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": frame_fingerprint,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": [],
        },
    ]
    monkeypatch.setattr(service, "load_active_point_trigger_model", _active_model)
    monkeypatch.setattr(
        service,
        "load_point_trigger_live_window",
        lambda *_args, **_kwargs: (frames, []),
    )
    monkeypatch.setattr(
        service,
        "load_day_capture_runtime_fingerprint_state",
        lambda _trade_date: day_state,
    )
    monkeypatch.setattr(
        service,
        "capture_runtime_fingerprint_safely",
        lambda: runtime_fingerprint,
    )
    monkeypatch.setattr(
        service,
        "save_point_trigger_action",
        lambda _row: (_ for _ in ()).throw(
            AssertionError("invalid runtime state must not save an action")
        ),
    )

    result = service.score_live_point_trigger(
        {"captured_at": CAPTURED_AT.isoformat()}
    )

    assert result == {"status": expected_status, "action_saved": 0}


def test_live_scoring_fails_closed_on_frame_gap(monkeypatch) -> None:
    frames = [
        {
            "id": 1,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT - timedelta(seconds=21),
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": ["600009.SSE"],
        },
        {
            "id": 2,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT,
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": ["600009.SSE"],
        },
    ]
    action_saves: list[dict[str, object]] = []
    monkeypatch.setattr(service, "load_active_point_trigger_model", _active_model)
    monkeypatch.setattr(
        service,
        "load_point_trigger_live_window",
        lambda *_args, **_kwargs: (frames, []),
    )
    monkeypatch.setattr(
        service, "save_point_trigger_action", lambda row: action_saves.append(dict(row))
    )

    result = service.score_live_point_trigger({"captured_at": CAPTURED_AT.isoformat()})

    assert result["status"] == "no_action_frame_gap"
    assert result["action_saved"] == 0
    assert action_saves == []


@pytest.mark.parametrize(
    ("existing_actions", "expected_status", "expected_slot"),
    [
        ([], "research_action_saved", 1),
        (
            [{"vt_symbol": "600008.SSE", "daily_slot": 1}],
            "research_action_saved",
            2,
        ),
        (
            [{"vt_symbol": "600008.SSE", "daily_slot": 3}],
            "no_action_daily_slot_inconsistent",
            None,
        ),
        (
            [{"vt_symbol": "600008.SSE", "daily_slot": 2}],
            "no_action_daily_slot_inconsistent",
            None,
        ),
    ],
)
def test_live_scoring_respects_frozen_daily_slots(
    monkeypatch,
    existing_actions: list[dict[str, object]],
    expected_status: str,
    expected_slot: int | None,
) -> None:
    frames = [
        {
            "id": 1,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT - timedelta(seconds=15),
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": ["600009.SSE"],
        },
        {
            "id": 2,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT,
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": ["600009.SSE"],
        },
    ]
    candidate = {
        **_feature_row(),
        "point_event_probability": 0.90,
        "point_identity_score": 1.20,
        "point_action_probability": 0.82,
        "top1_margin": 0.30,
        "candidate_count": 3,
    }
    saved: list[dict[str, object]] = []
    window_calls: list[tuple[datetime, int]] = []
    monkeypatch.setattr(service, "load_active_point_trigger_model", _active_model)
    monkeypatch.setattr(
        service,
        "load_point_trigger_live_window",
        lambda captured_at, *, lookback_seconds: (
            window_calls.append((captured_at, lookback_seconds)) or (frames, [])
        ),
    )
    monkeypatch.setattr(
        service, "build_point_trigger_rows", lambda *_args: [_feature_row()]
    )
    monkeypatch.setattr(
        service, "score_frozen_point_top1", lambda *_args, **_kwargs: [candidate]
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_actions",
        lambda *_args, **_kwargs: existing_actions,
    )
    monkeypatch.setattr(
        service,
        "save_point_trigger_action",
        lambda row: (
            saved.append(dict(row))
            or {"status": "saved", "decision_fingerprint": "sha256:test"}
        ),
    )

    snapshot = {
        "captured_at": CAPTURED_AT.isoformat(),
        "recommendations": {
            "lanes": {
                "now": [{"vt_symbol": "600009.SSE", "portfolio_selected": True}],
                "tail": [],
                "next_auction": [],
            }
        },
    }
    result = service.score_live_point_trigger(snapshot)

    assert result["status"] == expected_status
    assert result["action_saved"] == int(expected_slot is not None)
    assert window_calls == [(CAPTURED_AT, 220)]
    if expected_slot is None:
        assert saved == []
        return
    assert len(saved) == 1
    assert saved[0]["vt_symbol"] == "600001.SSE"
    assert saved[0]["daily_slot"] == expected_slot
    assert saved[0]["actionable"] is False
    assert saved[0]["execution_effect"] == "none_research_only"
    assert saved[0]["action_kind"] == "research_action"
    assert saved[0]["decision_payload"]["eligible_candidate_symbols"] == ["600001.SSE"]
    assert saved[0]["decision_payload"]["concurrent_formal_two_slot_symbols"] == [
        "600009.SSE"
    ]
    assert saved[0]["decision_payload"]["concurrent_formal_two_slot_observed"] is True


@pytest.mark.parametrize(
    ("snapshot", "expected_symbols", "expected_observed"),
    [
        ({}, [], False),
        ({"recommendations": {"lanes": {"now": []}}}, [], False),
        (
            {"recommendations": {"portfolio": [], "lanes": {"now": []}}},
            [],
            True,
        ),
        (
            {
                "recommendations": {
                    "lanes": {
                        "now": [
                            {
                                "vt_symbol": "600001.SSE",
                                "portfolio_selected": False,
                            }
                        ]
                    }
                }
            },
            [],
            True,
        ),
        (
            {
                "recommendations": {
                    "portfolio": [
                        {"vt_symbol": "600001.SSE"},
                        {"vt_symbol": "600002.SSE"},
                        {"vt_symbol": "600003.SSE"},
                    ]
                }
            },
            [],
            False,
        ),
        (
            {
                "recommendations": {
                    "portfolio": [
                        {"vt_symbol": "600002.SSE"},
                        {"vt_symbol": "600001.SSE"},
                    ]
                }
            },
            ["600002.SSE", "600001.SSE"],
            True,
        ),
    ],
)
def test_official_two_slot_evidence_distinguishes_known_empty_from_missing(
    snapshot: dict[str, object],
    expected_symbols: list[str],
    expected_observed: bool,
) -> None:
    symbols, observed = service._official_two_slot_evidence(snapshot)

    assert symbols == expected_symbols
    assert observed is expected_observed


def test_live_action_uses_frozen_frame_two_slot_not_unfrozen_snapshot(
    monkeypatch,
) -> None:
    frames = [
        {
            "id": 1,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT - timedelta(seconds=15),
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": True,
            "formal_two_slot_symbols": [],
        },
        {
            "id": 2,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT,
            "quality_status": "ready",
            "is_stale": False,
            "source_trade_date": TRADE_DATE,
            "quote_coverage_ratio": 1.0,
            "market_timing_state": "GOLD_ACTIVE",
            "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
            "formal_two_slot_observed": False,
            "formal_two_slot_symbols": None,
        },
    ]
    monkeypatch.setattr(service, "load_active_point_trigger_model", _active_model)
    monkeypatch.setattr(
        service,
        "load_point_trigger_live_window",
        lambda *_args, **_kwargs: (frames, []),
    )
    monkeypatch.setattr(
        service,
        "build_point_trigger_rows",
        lambda *_args: [_feature_row()],
    )
    monkeypatch.setattr(
        service,
        "score_frozen_point_top1",
        lambda *_args, **_kwargs: [
            {
                **_feature_row(),
                "point_action_probability": 0.90,
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "select_point_actions",
        lambda rows, **_kwargs: list(rows),
    )

    result = service.score_live_point_trigger(
        {
            "captured_at": CAPTURED_AT.isoformat(),
            "recommendations": {"portfolio": [{"vt_symbol": "600001.SSE"}]},
        }
    )

    assert result == {
        "status": "no_action_missing_formal_two_slot_evidence",
        "action_saved": 0,
    }


def test_live_action_requires_a_complete_60_second_session_horizon(monkeypatch) -> None:
    monkeypatch.setattr(service, "load_active_point_trigger_model", _active_model)

    result = service.score_live_point_trigger(
        {
            "captured_at": datetime(
                2026,
                7,
                21,
                11,
                29,
                30,
                tzinfo=SHANGHAI,
            ).isoformat()
        }
    )

    assert result == {
        "status": "no_action_cross_session_horizon",
        "action_saved": 0,
    }


def test_settlement_labels_identity_against_the_frozen_candidate_cohort(
    monkeypatch,
) -> None:
    action = {
        "model_fingerprint": "sha256:model",
        "trade_date": TRADE_DATE,
        "captured_at": CAPTURED_AT,
        "frame_id": 100,
        "vt_symbol": "600001.SSE",
        "decision_payload": {
            "eligible_candidate_symbols": ["600001.SSE", "600002.SSE"],
            "concurrent_formal_two_slot_symbols": [
                "600001.SSE",
                "600009.SSE",
            ],
            "concurrent_formal_two_slot_observed": True,
        },
        "fill_status": "queue_unknown_without_l2",
        "formal_identity_status": "pending",
        "physical_touch_status": "not_touched",
        "d1_status": "not_filled",
    }
    frames = [
        {"id": 100, "captured_at": CAPTURED_AT},
        {"id": 101, "captured_at": CAPTURED_AT + timedelta(seconds=15)},
        {"id": 102, "captured_at": CAPTURED_AT + timedelta(seconds=30)},
    ]
    observations = [
        {
            "frame_id": 101,
            "captured_at": CAPTURED_AT + timedelta(seconds=15),
            "vt_symbol": symbol,
            "formal_action": "pass",
            "board_lane": "first_board",
        }
        for symbol in ("600001.SSE", "600002.SSE")
    ]
    observations.append(
        {
            "frame_id": 102,
            "captured_at": CAPTURED_AT + timedelta(seconds=30),
            "vt_symbol": "600002.SSE",
            "formal_action": "buy_now",
            "board_lane": "first_board",
            "formal_rank": 1,
        }
    )
    closures: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        service, "load_point_trigger_actions", lambda *_args, **_kwargs: [action]
    )
    monkeypatch.setattr(service, "load_radar_frames", lambda *_args, **_kwargs: frames)
    monkeypatch.setattr(
        service,
        "load_radar_observations",
        lambda *_args, **_kwargs: observations,
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_feature_rows",
        lambda *_args, **_kwargs: [
            {
                "trade_date": TRADE_DATE,
                "captured_at": CAPTURED_AT,
                "frame_id": 100,
                "vt_symbol": "600001.SSE",
                "label_status": "known",
                "formal_event_within_60s": True,
                "formal_identity_within_60s": False,
                "formal_event_at": CAPTURED_AT + timedelta(seconds=30),
                "formal_identity_vt_symbol": "600002.SSE",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "load_daily_bars_for_symbols",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        service,
        "close_point_trigger_action_stage",
        lambda *_args, stage, values: (
            closures.append((stage, dict(values))) or {"status": "closed"}
        ),
    )

    result = service.settle_point_trigger_actions(
        as_of=datetime(2026, 7, 21, 21, 30, tzinfo=SHANGHAI)
    )

    assert result == {"action_count": 1, "stages_closed": 1}
    assert closures == [
        (
            "formal_identity",
            {
                "formal_identity_status": "missed",
                "formal_event_at": CAPTURED_AT + timedelta(seconds=30),
                "formal_identity_vt_symbol": "600002.SSE",
                "formal_identity_matched": False,
            },
        )
    ]


def test_delayed_fill_uses_only_the_first_fresh_quote() -> None:
    action = {
        "captured_at": CAPTURED_AT,
        "vt_symbol": "600001.SSE",
        "limit_price": 11.0,
    }
    observations = [
        {
            "captured_at": CAPTURED_AT + timedelta(seconds=20),
            "quote_observed_at": CAPTURED_AT + timedelta(seconds=20),
            "vt_symbol": "600001.SSE",
            "last_price": 11.0,
        },
        {
            "captured_at": CAPTURED_AT + timedelta(seconds=40),
            "quote_observed_at": CAPTURED_AT + timedelta(seconds=40),
            "vt_symbol": "600001.SSE",
            "last_price": 10.8,
        },
    ]

    assert service._delayed_fill_outcome(action, observations) == {
        "fill_status": "queue_unknown_without_l2",
        "fill_at": None,
        "fill_price": None,
        "fill_quote_observed_at": CAPTURED_AT + timedelta(seconds=20),
    }
    assert service._delayed_fill_outcome(action, []) == {
        "fill_status": "queue_unknown_without_l2",
        "fill_at": None,
        "fill_price": None,
        "fill_quote_observed_at": None,
    }


def test_delayed_fill_rejects_a_frame_carrying_a_pre_window_quote() -> None:
    action = {
        "captured_at": CAPTURED_AT,
        "vt_symbol": "600001.SSE",
        "limit_price": 11.0,
    }
    observations = [
        {
            "captured_at": CAPTURED_AT + timedelta(seconds=20),
            "quote_observed_at": CAPTURED_AT + timedelta(seconds=10),
            "vt_symbol": "600001.SSE",
            "last_price": 10.6,
        },
        {
            "captured_at": CAPTURED_AT + timedelta(seconds=30),
            "quote_observed_at": CAPTURED_AT + timedelta(seconds=30),
            "vt_symbol": "600001.SSE",
            "last_price": 11.0,
        },
    ]

    assert service._delayed_fill_outcome(action, observations) == {
        "fill_status": "queue_unknown_without_l2",
        "fill_at": None,
        "fill_price": None,
        "fill_quote_observed_at": CAPTURED_AT + timedelta(seconds=30),
    }


def test_eod_settlement_freezes_evidence_and_replays_three_intraday_stages(
    monkeypatch,
) -> None:
    action = {
        "model_fingerprint": "sha256:model",
        "trade_date": TRADE_DATE,
        "captured_at": CAPTURED_AT,
        "frame_id": 100,
        "vt_symbol": "600001.SSE",
        "limit_price": 11.0,
        "fill_status": "pending",
        "formal_identity_status": "pending",
        "physical_touch_status": "pending",
        "d1_status": "pending",
    }
    frames = [
        {
            "id": frame_id,
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT + timedelta(seconds=seconds),
        }
        for frame_id, seconds in ((100, 0), (101, 20), (102, 50), (103, 60))
    ]
    observations = [
        {
            "frame_id": 101,
            "captured_at": CAPTURED_AT + timedelta(seconds=20),
            "quote_observed_at": CAPTURED_AT + timedelta(seconds=20),
            "vt_symbol": "600001.SSE",
            "last_price": 10.6,
            "capture_state": "rising",
        },
        {
            "frame_id": 102,
            "captured_at": CAPTURED_AT + timedelta(seconds=50),
            "quote_observed_at": CAPTURED_AT + timedelta(seconds=50),
            "vt_symbol": "600001.SSE",
            "last_price": 11.0,
            "capture_state": "sealed",
        },
    ]
    feature_rows = [
        {
            "trade_date": TRADE_DATE,
            "captured_at": CAPTURED_AT,
            "frame_id": 100,
            "vt_symbol": "600001.SSE",
            "label_status": "known",
            "formal_event_within_60s": True,
            "formal_identity_within_60s": True,
            "formal_event_at": CAPTURED_AT + timedelta(seconds=50),
            "formal_identity_vt_symbol": "600001.SSE",
        }
    ]
    daily_bar = {
        "vt_symbol": "600001.SSE",
        "trade_date": TRADE_DATE,
        "high_price": 11.0,
        "close_price": 11.0,
    }
    closures: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        service, "load_point_trigger_actions", lambda *_args, **_kwargs: [action]
    )
    monkeypatch.setattr(service, "load_radar_frames", lambda *_args, **_kwargs: frames)
    monkeypatch.setattr(
        service, "load_radar_observations", lambda *_args, **_kwargs: observations
    )
    monkeypatch.setattr(
        service,
        "load_point_trigger_feature_rows",
        lambda *_args, **_kwargs: feature_rows,
    )
    monkeypatch.setattr(
        service,
        "load_daily_bars_for_symbols",
        lambda *_args, **_kwargs: [daily_bar],
    )
    monkeypatch.setattr(
        service,
        "load_reliable_trade_dates",
        lambda *_args, **_kwargs: [TRADE_DATE],
    )
    monkeypatch.setattr(
        service,
        "close_point_trigger_action_stage",
        lambda *_args, stage, values: (
            closures.append((stage, dict(values))) or {"status": "closed"}
        ),
    )

    result = service.settle_point_trigger_actions(
        as_of=datetime(2026, 7, 21, 21, 30, tzinfo=SHANGHAI)
    )

    assert result == {"action_count": 1, "stages_closed": 3}
    assert [stage for stage, _values in closures] == [
        "delayed_fill",
        "formal_identity",
        "physical_touch",
    ]
    fill = closures[0][1]
    assert fill["fill_status"] == "filled"
    assert fill["fill_price"] == 10.6
    assert fill["settlement_evidence_fingerprint"] == (
        service.point_trigger_settlement_evidence_fingerprint(
            fill["settlement_evidence"]
        )
    )
    assert closures[1][1]["formal_identity_status"] == "matched"
    assert closures[2][1] == {
        "physical_touch_status": "touched",
        "physical_touch_at": CAPTURED_AT + timedelta(seconds=50),
        "final_sealed": True,
    }


def test_intraday_settlement_does_not_freeze_partial_action_evidence(
    monkeypatch,
) -> None:
    action = {
        "model_fingerprint": "sha256:model",
        "trade_date": TRADE_DATE,
        "captured_at": CAPTURED_AT,
        "frame_id": 100,
        "vt_symbol": "600001.SSE",
        "limit_price": 11.0,
        "fill_status": "pending",
        "formal_identity_status": "pending",
        "physical_touch_status": "pending",
        "d1_status": "pending",
    }
    monkeypatch.setattr(
        service, "load_point_trigger_actions", lambda *_args, **_kwargs: [action]
    )
    monkeypatch.setattr(service, "load_radar_frames", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        service, "load_radar_observations", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        service, "load_point_trigger_feature_rows", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        service,
        "load_reliable_trade_dates",
        lambda *_args, **_kwargs: [TRADE_DATE],
    )
    monkeypatch.setattr(
        service,
        "close_point_trigger_action_stage",
        lambda *_args, **_kwargs: pytest.fail("intraday stage must remain pending"),
    )

    result = service.settle_point_trigger_actions(
        as_of=datetime(2026, 7, 21, 14, 45, tzinfo=SHANGHAI)
    )

    assert result == {"action_count": 1, "stages_closed": 0}


def test_settlement_does_not_use_d2_when_the_exact_d1_bar_is_missing(
    monkeypatch,
) -> None:
    d1_trade_date = TRADE_DATE + timedelta(days=1)
    d2_trade_date = TRADE_DATE + timedelta(days=2)
    action = _filled_action_waiting_for_d1()
    closures: list[tuple[str, dict[str, object]]] = []
    _stub_d1_settlement_inputs(
        monkeypatch,
        action=action,
        reliable_dates=[TRADE_DATE, d1_trade_date, d2_trade_date],
        bars=[
            {
                "vt_symbol": action["vt_symbol"],
                "trade_date": d2_trade_date,
                "close_price": 11.4,
            }
        ],
        closures=closures,
    )

    result = service.settle_point_trigger_actions(
        as_of=datetime(2026, 7, 23, 21, 30, tzinfo=SHANGHAI)
    )

    assert result == {"action_count": 1, "stages_closed": 0}
    assert closures == []


def test_settlement_closes_on_the_exact_d1_market_trade_date(monkeypatch) -> None:
    d1_trade_date = TRADE_DATE + timedelta(days=1)
    d2_trade_date = TRADE_DATE + timedelta(days=2)
    action = _filled_action_waiting_for_d1()
    closures: list[tuple[str, dict[str, object]]] = []
    _stub_d1_settlement_inputs(
        monkeypatch,
        action=action,
        reliable_dates=[TRADE_DATE, d1_trade_date, d2_trade_date],
        bars=[
            {
                "vt_symbol": action["vt_symbol"],
                "trade_date": d1_trade_date,
                "close_price": 11.2,
            },
            {
                "vt_symbol": action["vt_symbol"],
                "trade_date": d2_trade_date,
                "close_price": 11.4,
            },
        ],
        closures=closures,
    )

    result = service.settle_point_trigger_actions(
        as_of=datetime(2026, 7, 23, 21, 30, tzinfo=SHANGHAI)
    )

    assert result == {"action_count": 1, "stages_closed": 1}
    assert len(closures) == 1
    assert closures[0][0] == "d1_outcome"
    assert closures[0][1]["d1_status"] == "closed"
    assert closures[0][1]["d1_trade_date"] == d1_trade_date
    assert closures[0][1]["d1_close_price"] == 11.2


def _filled_action_waiting_for_d1() -> dict[str, object]:
    return {
        "model_fingerprint": "sha256:model",
        "trade_date": TRADE_DATE,
        "captured_at": CAPTURED_AT,
        "vt_symbol": "600001.SSE",
        "fill_status": "filled",
        "fill_price": 10.5,
        "limit_price": 11.0,
        "formal_identity_status": "matched",
        "physical_touch_status": "touched",
        "d1_status": "pending",
    }


def _stub_d1_settlement_inputs(
    monkeypatch,
    *,
    action: dict[str, object],
    reliable_dates: list[date],
    bars: list[dict[str, object]],
    closures: list[tuple[str, dict[str, object]]],
) -> None:
    monkeypatch.setattr(
        service, "load_point_trigger_actions", lambda *_args, **_kwargs: [action]
    )
    monkeypatch.setattr(service, "load_radar_frames", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        service, "load_radar_observations", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        service,
        "load_reliable_trade_dates",
        lambda *_args, **_kwargs: reliable_dates,
    )
    monkeypatch.setattr(
        service,
        "load_daily_bars_for_symbols",
        lambda *_args, **_kwargs: bars,
    )
    monkeypatch.setattr(
        service,
        "close_point_trigger_action_stage",
        lambda *_args, stage, values: (
            closures.append((stage, dict(values))) or {"status": "closed"}
        ),
    )


def test_research_snapshot_argument_is_never_mutated_on_failure(monkeypatch) -> None:
    snapshot = {
        "candidates": [{"vt_symbol": "600001.SSE", "rank": 1}],
        "recommendations": {"lanes": {"now": [{"action": "buy_now"}]}},
        "portfolio": [{"vt_symbol": "600001.SSE"}],
        "action": "buy_now",
        "rank": 1,
        "data_quality": {"status": "ready", "is_stale": False},
    }
    before = deepcopy(snapshot)

    def failing_score(research_snapshot):
        research_snapshot["candidates"].clear()
        research_snapshot["action"] = "pass"
        raise RuntimeError("research store down")

    monkeypatch.setattr(service, "score_live_point_trigger", failing_score)

    error = service.score_live_point_trigger_safely(snapshot)

    assert error["status"] == "error"
    assert snapshot == before


def test_zero_candidate_frames_are_present_in_label_coverage() -> None:
    frames = [
        {"id": 1, "captured_at": CAPTURED_AT},
        {"id": 2, "captured_at": CAPTURED_AT + timedelta(seconds=15)},
    ]
    observations = [
        {
            "frame_id": 2,
            "captured_at": CAPTURED_AT + timedelta(seconds=15),
            "vt_symbol": "600001.SSE",
            "formal_action": "pass",
            "board_lane": "first_board",
        }
    ]

    future = service.future_observations_with_frame_sentinels(frames, observations)

    assert {row["captured_at"] for row in future} == {
        CAPTURED_AT,
        CAPTURED_AT + timedelta(seconds=15),
    }
    assert any(row["frame_id"] == 1 and row["vt_symbol"] == "" for row in future)
