"""EOD freezing and research-only live scoring for point-trigger v9."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from math import isfinite
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import radar_validation
from alphaagent.server.services.limit_up.capture_runtime import (
    capture_runtime_fingerprint_safely,
    is_capture_runtime_fingerprint,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_daily_bars_for_symbols,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CALIBRATION_DAY_COUNT,
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    ENTRY_WINDOWS,
    FIT_DAY_COUNT,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    LIVE_CAUSAL_LOOKBACK_SECONDS,
    MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS,
    MODEL_FREEZE_DAY_COUNT,
    PointTriggerDayAudit,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_dataset import (
    attach_point_trigger_labels,
    audit_point_trigger_day,
    build_point_trigger_rows,
    finalize_point_trigger_day_audit,
    point_trigger_input_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_model import (
    ACTION_FEATURE_FIELDS,
    ACTION_MODEL_PARAMETERS,
    ACTION_SCORE_FIELD,
    EVENT_MODEL_PARAMETERS,
    EVENT_SCORE_FIELD,
    IDENTITY_MODEL_PARAMETERS,
    IDENTITY_SCORE_FIELD,
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
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    load_reliable_trade_dates,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_repository import (
    close_point_trigger_action_stage,
    freeze_point_trigger_day,
    load_active_point_trigger_model,
    load_point_trigger_actions,
    load_point_trigger_day_scopes,
    load_point_trigger_feature_rows,
    load_point_trigger_models,
    point_trigger_model_record_fingerprint,
    save_point_trigger_action,
    save_point_trigger_model,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_settlement import (
    build_point_trigger_settlement_evidence,
    point_trigger_settlement_evidence_fingerprint,
    replay_delayed_fill_outcome,
    replay_formal_identity_outcome,
    replay_physical_touch_outcome,
)
from alphaagent.server.services.limit_up.radar_observation_repository import (
    load_day_capture_runtime_fingerprint_state,
    load_frame_dates,
    load_frames as load_radar_frames,
    load_observations as load_radar_observations,
    load_point_trigger_audit_inputs,
    load_point_trigger_live_window,
    official_two_slot_evidence,
)
from alphaagent.server.services.research_runtime import require_research_runtime


SHANGHAI = ZoneInfo("Asia/Shanghai")
MODEL_ARTIFACT_FORMAT = "limit-up-preboard-point-trigger-artifact-v1"
CURRENT_DAY_FREEZE_TIME = time(15, 0)


def sync_limit_up_preboard_point_trigger(
    *,
    as_of: datetime | None = None,
    trade_date: date | None = None,
) -> dict[str, object]:
    """Freeze one radar date, settle outcomes, and freeze a model only once."""

    current_at = _local_datetime(as_of or datetime.now(SHANGHAI))
    target_date = _resolve_target_trade_date(current_at, trade_date)
    frozen: dict[str, object] = {
        "status": "no_eligible_radar_day",
        "rows_written": 0,
    }
    if target_date is not None:
        frames, audit_observations = load_point_trigger_audit_inputs(
            target_date,
            target_date,
        )
        audit = audit_point_trigger_day(frames, audit_observations)
        if audit.trade_date is None:
            audit = replace(audit, trade_date=target_date)
        audit = _apply_current_capture_runtime_gate(audit)
        rows: list[dict[str, object]] = []
        if audit.is_complete:
            observations = load_radar_observations(target_date, target_date)
            causal_rows = build_point_trigger_rows(frames, observations)
            future = future_observations_with_frame_sentinels(frames, observations)
            rows = attach_point_trigger_labels(causal_rows, future)
            audit = finalize_point_trigger_day_audit(audit, rows)
        frozen = freeze_point_trigger_day(audit, rows)
    settlement = settle_point_trigger_actions(as_of=current_at)

    scopes = _eligible_complete_scopes(load_point_trigger_day_scopes())
    models = load_point_trigger_models()
    if len(models) > 1:
        raise RuntimeError("point-trigger contract has multiple frozen model decisions")
    rows_written = int(frozen.get("rows_written") or 0) + int(
        settlement.get("stages_closed") or 0
    )
    if len(scopes) < MODEL_FREEZE_DAY_COUNT:
        return _phase_result(
            scopes,
            rows_written=rows_written,
            message="no eligible radar day" if target_date is None else None,
            day_freeze_status=str(frozen.get("status") or "unknown"),
            settlement=settlement,
        )
    if models:
        model = models[0]
        status = (
            "forward_collecting"
            if model.get("status") == "active"
            else "forward_rejected"
        )
        return {
            **_phase_counts(scopes),
            "status": status,
            "model_fingerprint": model.get("model_fingerprint"),
            "model_status": model.get("status"),
            "rows_written": rows_written,
            "day_freeze_status": str(frozen.get("status") or "unknown"),
            "settlement": settlement,
            "message": status,
        }

    return {
        **_phase_counts(scopes),
        "status": "awaiting_research_model_fit",
        "model_fingerprint": None,
        "model_status": None,
        "rows_written": rows_written,
        "day_freeze_status": str(frozen.get("status") or "unknown"),
        "settlement": settlement,
        "message": "awaiting_research_model_fit",
    }


def fit_point_trigger_model_if_ready(
    *,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Freeze the sole 40/15 model from the dedicated research runtime."""

    require_research_runtime()
    scopes = _eligible_complete_scopes(load_point_trigger_day_scopes())
    models = load_point_trigger_models()
    if len(models) > 1:
        raise RuntimeError("point-trigger contract has multiple frozen model decisions")
    if models:
        model = models[0]
        return {
            **_phase_counts(scopes),
            "status": "already_frozen",
            "model_fingerprint": model.get("model_fingerprint"),
            "model_status": model.get("status"),
        }
    if len(scopes) < MODEL_FREEZE_DAY_COUNT:
        return {
            **_phase_counts(scopes),
            "status": "not_ready_model_scope",
            "model_fingerprint": None,
            "model_status": None,
        }
    frozen_at = _local_datetime(as_of or datetime.now(SHANGHAI))
    return _fit_and_freeze_model(
        scopes[:MODEL_FREEZE_DAY_COUNT],
        frozen_at,
    )


def score_live_point_trigger(
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    """Score only the just-saved frame and persist no executable output."""

    model_record = load_active_point_trigger_model()
    if model_record is None:
        return {"status": "no_active_model", "action_saved": 0}
    _validate_active_model(model_record)

    captured_at = _as_datetime(snapshot.get("captured_at"))
    if captured_at is None:
        return {"status": "no_action_invalid_capture_time", "action_saved": 0}
    if not _has_complete_action_horizon(captured_at):
        return {"status": "no_action_cross_session_horizon", "action_saved": 0}
    trade_date = captured_at.astimezone(SHANGHAI).date()
    frames, observations = load_point_trigger_live_window(
        captured_at,
        lookback_seconds=LIVE_CAUSAL_LOOKBACK_SECONDS,
    )
    frames.sort(
        key=lambda row: (
            _datetime_key(row.get("captured_at")),
            str(row.get("id") or ""),
        )
    )
    if not frames or _as_datetime(frames[-1].get("captured_at")) != captured_at:
        return {"status": "no_action_current_frame_missing", "action_saved": 0}
    current_frame = frames[-1]
    current_quality_error = _live_frame_quality_error(current_frame, trade_date)
    if current_quality_error:
        return {"status": current_quality_error, "action_saved": 0}
    runtime_error = _live_capture_runtime_fingerprint_error(
        current_frame,
        trade_date,
    )
    if runtime_error:
        return {"status": runtime_error, "action_saved": 0}
    previous = _previous_frame_in_window(frames, captured_at)
    if previous is None:
        return {"status": "no_action_frame_gap", "action_saved": 0}
    gap = (captured_at - previous).total_seconds()
    if not 0.0 < gap <= MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS:
        return {"status": "no_action_frame_gap", "action_saved": 0}

    rows = build_point_trigger_rows(frames, observations)
    current_rows = [
        row for row in rows if row.get("frame_id") == current_frame.get("id")
    ]
    if not current_rows:
        return {"status": "no_action_no_eligible_candidate", "action_saved": 0}
    if any(row.get("action_frame_eligible") is not True for row in current_rows):
        return {"status": "no_action_frame_contract_mismatch", "action_saved": 0}
    scored = score_frozen_point_top1(current_rows, model_record)
    threshold = _number(model_record.get("calibration_threshold"))
    actions = select_point_actions(scored, threshold=threshold)
    if not actions:
        return {"status": "no_action_below_threshold", "action_saved": 0}

    formal_two_slot_symbols, formal_two_slot_observed = _frozen_two_slot_evidence(
        current_frame
    )
    if not formal_two_slot_observed:
        return {
            "status": "no_action_missing_formal_two_slot_evidence",
            "action_saved": 0,
        }

    existing = load_point_trigger_actions(
        model_fingerprint=str(model_record["model_fingerprint"]),
        trade_date=trade_date,
    )
    existing_symbols = {str(row.get("vt_symbol") or "") for row in existing}
    if len(existing) >= 2:
        return {"status": "no_action_daily_limit", "action_saved": 0}
    candidate = actions[0]
    symbol = str(candidate.get("vt_symbol") or "")
    if symbol in existing_symbols:
        return {"status": "no_action_stock_day_already_selected", "action_saved": 0}
    used_slots = {
        int(row["daily_slot"]) for row in existing if row.get("daily_slot") in (1, 2)
    }
    expected_slots = set(range(1, len(existing) + 1))
    if used_slots != expected_slots:
        return {"status": "no_action_daily_slot_inconsistent", "action_saved": 0}
    daily_slot = next(slot for slot in (1, 2) if slot not in used_slots)

    eligible_candidate_symbols = sorted(
        {
            str(row.get("vt_symbol") or "").strip()
            for row in current_rows
            if str(row.get("vt_symbol") or "").strip()
        }
    )
    saved = save_point_trigger_action(
        {
            "model_fingerprint": model_record["model_fingerprint"],
            "contract_version": CONTRACT_VERSION,
            "captured_at": captured_at,
            "trade_date": trade_date,
            "daily_slot": daily_slot,
            "frame_id": candidate["frame_id"],
            "vt_symbol": symbol,
            "quote_observed_at": candidate.get("quote_observed_at"),
            "last_price": candidate.get("last_price"),
            "limit_price": candidate.get("limit_price"),
            "action_probability": candidate.get(ACTION_SCORE_FIELD),
            "action_threshold": threshold,
            "event_probability": candidate.get(EVENT_SCORE_FIELD),
            "identity_score": candidate.get(IDENTITY_SCORE_FIELD),
            "top1_margin": candidate.get("top1_margin"),
            "candidate_count": candidate.get("candidate_count"),
            "input_fingerprint": point_trigger_input_fingerprint([candidate]),
            "decision_payload": {
                "eligible_candidate_symbols": eligible_candidate_symbols,
                "concurrent_formal_two_slot_symbols": formal_two_slot_symbols,
                "concurrent_formal_two_slot_observed": formal_two_slot_observed,
                "event_model_fingerprint": model_record.get("event_model_fingerprint"),
                "identity_model_fingerprint": model_record.get(
                    "identity_model_fingerprint"
                ),
                "action_model_fingerprint": model_record.get(
                    "action_model_fingerprint"
                ),
            },
            "actionable": False,
            "execution_effect": "none_research_only",
            "action_kind": "research_action",
        }
    )
    return {
        "status": (
            "research_action_saved"
            if saved.get("status") == "saved"
            else "research_action_already_saved"
        ),
        "action_saved": int(saved.get("status") == "saved"),
        "vt_symbol": symbol,
        "model_fingerprint": model_record["model_fingerprint"],
    }


def score_live_point_trigger_safely(
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    """Run research on an isolated copy and reduce every failure to no-action."""

    try:
        return score_live_point_trigger(deepcopy(dict(snapshot)))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "action_saved": 0,
            "error": str(exc)[:500] or exc.__class__.__name__,
        }


def future_observations_with_frame_sentinels(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep zero-candidate frames visible to the label continuity audit."""

    result = [dict(row) for row in observations]
    observed_frame_ids = {row.get("frame_id") for row in observations}
    for frame in frames:
        frame_id = frame.get("id", frame.get("frame_id"))
        captured_at = _as_datetime(frame.get("captured_at"))
        if frame_id in observed_frame_ids or captured_at is None:
            continue
        result.append(
            {
                "frame_id": frame_id,
                "captured_at": captured_at,
                "vt_symbol": "",
                "formal_action": "pass",
                "board_lane": "none",
                "formal_rank": None,
                "rank_score": None,
                "is_stale": frame.get("is_stale"),
            }
        )
    return sorted(
        result,
        key=lambda row: (
            _datetime_key(row.get("captured_at")),
            str(row.get("vt_symbol") or ""),
        ),
    )


def settle_point_trigger_actions(
    *,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Close observable action outcomes without revising any prior closure."""

    current_at = _local_datetime(as_of or datetime.now(SHANGHAI))
    actions = load_point_trigger_actions()
    pending = [
        dict(row)
        for row in actions
        if any(
            row.get(field) == "pending"
            for field in (
                "fill_status",
                "formal_identity_status",
                "physical_touch_status",
                "d1_status",
            )
        )
    ]
    if not pending:
        return {"action_count": len(actions), "stages_closed": 0}

    dates = sorted(
        {
            parsed
            for row in pending
            if (parsed := _as_date(row.get("trade_date"))) is not None
        }
    )
    d1_dates = sorted(
        {
            parsed
            for row in pending
            if row.get("d1_status") == "pending"
            and (parsed := _as_date(row.get("trade_date"))) is not None
        }
    )
    frames_by_date: dict[date, list[dict[str, object]]] = {}
    observations_by_date: dict[date, list[dict[str, object]]] = {}
    for trade_date in dates:
        frames_by_date[trade_date] = load_radar_frames(trade_date, trade_date)
        observations_by_date[trade_date] = load_radar_observations(
            trade_date, trade_date
        )

    formal_dates = sorted(
        {
            parsed
            for row in pending
            if row.get("formal_identity_status") == "pending"
            and (parsed := _as_date(row.get("trade_date"))) is not None
        }
    )
    feature_rows = load_point_trigger_feature_rows(formal_dates) if formal_dates else []

    symbols = sorted({str(row.get("vt_symbol") or "") for row in pending})
    daily_bars = (
        load_daily_bars_for_symbols(
            symbols,
            min(dates),
            current_at.date(),
        )
        if dates
        and (
            min(dates) < current_at.date()
            or current_at.time().replace(tzinfo=None) >= CURRENT_DAY_FREEZE_TIME
        )
        else []
    )
    bars_by_symbol: dict[str, list[dict[str, object]]] = {}
    bars_by_stock_day: dict[tuple[str, date], dict[str, object]] = {}
    for bar in daily_bars:
        bar_row = dict(bar)
        bar_symbol = str(bar.get("vt_symbol") or "")
        bars_by_symbol.setdefault(bar_symbol, []).append(bar_row)
        if (bar_date := _as_date(bar.get("trade_date"))) is not None:
            bars_by_stock_day[(bar_symbol, bar_date)] = bar_row
    for bars in bars_by_symbol.values():
        bars.sort(key=lambda row: str(row.get("trade_date") or ""))
    reliable_trade_dates = (
        load_reliable_trade_dates(min(d1_dates), current_at.date()) if d1_dates else []
    )

    closed_count = 0
    for action in pending:
        action_date = _as_date(action.get("trade_date"))
        captured_at = _as_datetime(action.get("captured_at"))
        symbol = str(action.get("vt_symbol") or "")
        if action_date is None or captured_at is None or not symbol:
            continue
        frames = frames_by_date.get(action_date, [])
        observations = observations_by_date.get(action_date, [])
        identity = (
            str(action.get("model_fingerprint") or ""),
            captured_at,
            symbol,
        )
        action_day_closed = bool(
            action_date < current_at.date()
            or (
                action_date == current_at.date()
                and current_at.time().replace(tzinfo=None) >= CURRENT_DAY_FREEZE_TIME
            )
        )
        evidence = (
            action.get("settlement_evidence")
            if isinstance(action.get("settlement_evidence"), Mapping)
            else None
        )

        if action.get("fill_status") == "pending" and action_day_closed:
            try:
                evidence = build_point_trigger_settlement_evidence(
                    action,
                    frames,
                    observations,
                )
            except (TypeError, ValueError):
                evidence = None
            fill = (
                replay_delayed_fill_outcome(action, evidence)
                if evidence is not None
                else None
            )
            if fill is not None:
                fill = {
                    **fill,
                    "settlement_evidence": evidence,
                    "settlement_evidence_fingerprint": (
                        point_trigger_settlement_evidence_fingerprint(evidence)
                    ),
                }
                close_point_trigger_action_stage(
                    *identity,
                    stage="delayed_fill",
                    values=fill,
                )
                action.update(fill)
                closed_count += 1

        if action.get("formal_identity_status") == "pending" and action_day_closed:
            formal = replay_formal_identity_outcome(action, feature_rows)
            if formal is not None:
                close_point_trigger_action_stage(
                    *identity,
                    stage="formal_identity",
                    values=formal,
                )
                action.update(formal)
                closed_count += 1

        if action.get("physical_touch_status") == "pending" and action_day_closed:
            touch = (
                replay_physical_touch_outcome(
                    action,
                    evidence,
                    bars_by_stock_day.get((symbol, action_date)),
                )
                if evidence is not None
                else None
            )
            if touch is not None:
                close_point_trigger_action_stage(
                    *identity,
                    stage="physical_touch",
                    values=touch,
                )
                action.update(touch)
                closed_count += 1

        if action.get("d1_status") == "pending":
            expected_d1_trade_date = next(
                (value for value in reliable_trade_dates if value > action_date),
                None,
            )
            d1 = _d1_outcome(
                action,
                bars_by_symbol.get(symbol, []),
                expected_d1_trade_date=expected_d1_trade_date,
            )
            if d1 is not None:
                close_point_trigger_action_stage(
                    *identity,
                    stage="d1_outcome",
                    values=d1,
                )
                closed_count += 1
    return {"action_count": len(actions), "stages_closed": closed_count}


def _fit_and_freeze_model(
    scopes: Sequence[Mapping[str, object]],
    frozen_at: datetime,
) -> dict[str, object]:
    fit_dates = tuple(_scope_date(row) for row in scopes[:FIT_DAY_COUNT])
    calibration_dates = tuple(
        _scope_date(row) for row in scopes[FIT_DAY_COUNT:MODEL_FREEZE_DAY_COUNT]
    )
    if any(value is None for value in (*fit_dates, *calibration_dates)):
        raise ValueError("point-trigger model scope contains an invalid date")
    typed_fit_dates = tuple(value for value in fit_dates if value is not None)
    typed_calibration_dates = tuple(
        value for value in calibration_dates if value is not None
    )
    calibration_close = datetime.combine(
        typed_calibration_dates[-1],
        CURRENT_DAY_FREEZE_TIME,
        tzinfo=SHANGHAI,
    )
    if _local_datetime(frozen_at) < calibration_close:
        raise ValueError("point-trigger model cannot freeze before calibration closes")
    all_rows = load_point_trigger_feature_rows(
        [*typed_fit_dates, *typed_calibration_dates]
    )
    fit_rows = [
        row
        for row in all_rows
        if _as_date(row.get("trade_date")) in set(typed_fit_dates)
    ]
    calibration_rows = [
        row
        for row in all_rows
        if _as_date(row.get("trade_date")) in set(typed_calibration_dates)
    ]
    event_model = fit_event_model(fit_rows, typed_fit_dates)
    identity_model = fit_identity_ranker(fit_rows, typed_fit_dates)
    oof_top1 = build_walk_forward_top1(fit_rows, typed_fit_dates)
    action_model = fit_action_model(oof_top1)

    threshold = None
    calibration_scored: list[dict[str, object]] = []
    if all(
        model.status == "ready" for model in (event_model, identity_model, action_model)
    ):
        calibration_scored = score_action_rows(
            select_point_top1(
                score_identity_rows(
                    score_event_rows(calibration_rows, event_model),
                    identity_model,
                )
            ),
            action_model,
        )
        calibration_reachable_pairs = {
            (trade_date.isoformat(), symbol)
            for row in calibration_rows
            if row.get("formal_identity_within_60s") is True
            and (trade_date := _as_date(row.get("trade_date"))) is not None
            and (symbol := str(row.get("vt_symbol") or "").strip())
        }
        threshold = calibrate_point_actions(
            calibration_scored,
            reachable_stock_day_pairs=calibration_reachable_pairs,
        )
    else:
        threshold = calibrate_point_actions([])

    ready = threshold.status == "ready" and all(
        model.status == "ready" for model in (event_model, identity_model, action_model)
    )
    training_input_fingerprint = _fingerprint(
        [
            {
                "trade_date": _scope_date(row),
                "cohort_fingerprint": row.get("cohort_fingerprint"),
            }
            for row in scopes
        ]
    )
    stage_fingerprints = {
        "event": event_model.fingerprint
        or _fingerprint({"stage": "event", "status": event_model.status}),
        "identity": identity_model.fingerprint
        or _fingerprint({"stage": "identity", "status": identity_model.status}),
        "action": action_model.fingerprint
        or _fingerprint({"stage": "action", "status": action_model.status}),
    }
    model_fingerprint = _fingerprint(
        {
            "contract_version": CONTRACT_VERSION,
            "fit_dates": typed_fit_dates,
            "calibration_dates": typed_calibration_dates,
            "training_input_fingerprint": training_input_fingerprint,
            "stage_fingerprints": stage_fingerprints,
            "threshold_status": threshold.status,
            "threshold": threshold.threshold,
        }
    )
    artifact = (
        {
            "format": MODEL_ARTIFACT_FORMAT,
            "event_booster_model_text": event_model.booster_model_text,
            "identity_booster_model_text": identity_model.booster_model_text,
            "action_scaler_mean_by_feature": action_model.scaler_mean_by_feature,
            "action_scaler_scale_by_feature": action_model.scaler_scale_by_feature,
            "action_coefficient_by_feature": action_model.coefficient_by_feature,
            "action_intercept": action_model.intercept,
        }
        if ready
        else {"format": MODEL_ARTIFACT_FORMAT, "rejection": threshold.status}
    )
    record = {
        "model_fingerprint": model_fingerprint,
        "contract_version": CONTRACT_VERSION,
        "status": "active" if ready else "rejected",
        "fit_trade_dates": list(typed_fit_dates),
        "calibration_trade_dates": list(typed_calibration_dates),
        "validation_trade_dates": [],
        "event_model_params": EVENT_MODEL_PARAMETERS,
        "identity_model_params": IDENTITY_MODEL_PARAMETERS,
        "action_model_params": ACTION_MODEL_PARAMETERS,
        "frame_feature_fields": list(FRAME_FEATURE_FIELDS),
        "identity_feature_fields": list(IDENTITY_FEATURE_FIELDS),
        "action_feature_fields": list(ACTION_FEATURE_FIELDS),
        "training_input_fingerprint": training_input_fingerprint,
        "event_model_fingerprint": stage_fingerprints["event"],
        "identity_model_fingerprint": stage_fingerprints["identity"],
        "action_model_fingerprint": stage_fingerprints["action"],
        "calibration_threshold": threshold.threshold,
        "calibration_metrics": {
            "status": threshold.status,
            "selected": threshold.selected_metrics,
            "by_threshold": list(threshold.metrics_by_threshold),
            "scored_top1_count": len(calibration_scored),
        },
        "model_artifact": artifact,
        "frozen_at": frozen_at,
    }
    saved = save_point_trigger_model(record)
    return {
        **record,
        "model_written": int(saved.get("status") == "frozen"),
    }


def _validate_active_model(model: Mapping[str, object]) -> None:
    artifact = model.get("model_artifact")
    try:
        record_fingerprint_matches = str(
            model.get("record_fingerprint") or ""
        ) == point_trigger_model_record_fingerprint(model)
    except (TypeError, ValueError):
        record_fingerprint_matches = False
    fit_dates = tuple(_as_date(value) for value in model.get("fit_trade_dates") or ())
    calibration_dates = tuple(
        _as_date(value) for value in model.get("calibration_trade_dates") or ()
    )
    validation_dates = tuple(model.get("validation_trade_dates") or ())
    cohort_valid = (
        len(fit_dates) == FIT_DAY_COUNT
        and len(calibration_dates) == CALIBRATION_DAY_COUNT
        and not validation_dates
        and all(value is not None for value in (*fit_dates, *calibration_dates))
        and len(set(fit_dates)) == FIT_DAY_COUNT
        and len(set(calibration_dates)) == CALIBRATION_DAY_COUNT
        and fit_dates == tuple(sorted(fit_dates))
        and calibration_dates == tuple(sorted(calibration_dates))
        and all(
            value is not None and value > ELIGIBLE_AFTER
            for value in (*fit_dates, *calibration_dates)
        )
        and fit_dates[-1] is not None
        and calibration_dates[0] is not None
        and fit_dates[-1] < calibration_dates[0]
    )
    if (
        model.get("contract_version") != CONTRACT_VERSION
        or model.get("status") != "active"
        or not record_fingerprint_matches
        or not cohort_valid
        or model.get("event_model_params") != EVENT_MODEL_PARAMETERS
        or model.get("identity_model_params") != IDENTITY_MODEL_PARAMETERS
        or model.get("action_model_params") != ACTION_MODEL_PARAMETERS
        or tuple(model.get("frame_feature_fields") or ()) != FRAME_FEATURE_FIELDS
        or tuple(model.get("identity_feature_fields") or ()) != IDENTITY_FEATURE_FIELDS
        or tuple(model.get("action_feature_fields") or ()) != ACTION_FEATURE_FIELDS
        or not isinstance(artifact, Mapping)
        or artifact.get("format") != MODEL_ARTIFACT_FORMAT
        or _number(model.get("calibration_threshold")) is None
    ):
        raise ValueError(
            "active point-trigger model does not match the frozen contract"
        )


def _live_frame_quality_error(
    frame: Mapping[str, object],
    trade_date: date,
) -> str | None:
    coverage = _number(frame.get("quote_coverage_ratio"))
    if frame.get("quality_status") != "ready" or frame.get("is_stale") is not False:
        return "no_action_stale_frame"
    if _as_date(frame.get("source_trade_date")) != trade_date:
        return "no_action_source_date_mismatch"
    if coverage is None or coverage < 0.90:
        return "no_action_quote_coverage"
    if not str(frame.get("market_timing_state") or "").strip():
        return "no_action_market_timing_missing"
    return None


def _apply_current_capture_runtime_gate(
    audit: PointTriggerDayAudit,
) -> PointTriggerDayAudit:
    if not audit.is_complete:
        return audit
    current = str(capture_runtime_fingerprint_safely() or "").strip()
    if not current:
        reason = "capture_runtime_fingerprint_current_missing"
    elif not is_capture_runtime_fingerprint(current):
        reason = "capture_runtime_fingerprint_current_invalid"
    elif current != audit.capture_runtime_fingerprint:
        reason = "capture_runtime_fingerprint_current_mismatch"
    else:
        return replace(
            audit,
            metrics={
                **audit.metrics,
                "capture_runtime_fingerprint_current_match": 1,
            },
        )
    return replace(
        audit,
        status="incomplete",
        is_complete=False,
        eligible_for_model=False,
        reason_codes=tuple(dict.fromkeys((*audit.reason_codes, reason))),
        metrics={
            **audit.metrics,
            "capture_runtime_fingerprint_current_match": 0,
        },
    )


def _live_capture_runtime_fingerprint_error(
    frame: Mapping[str, object],
    trade_date: date,
) -> str | None:
    frame_fingerprint = str(
        frame.get("capture_runtime_fingerprint") or ""
    ).strip()
    if not frame_fingerprint:
        return "no_action_capture_runtime_fingerprint_missing"
    if not is_capture_runtime_fingerprint(frame_fingerprint):
        return "no_action_capture_runtime_fingerprint_invalid"

    current_fingerprint = str(
        capture_runtime_fingerprint_safely() or ""
    ).strip()
    if not current_fingerprint:
        return "no_action_capture_runtime_fingerprint_missing"
    if not is_capture_runtime_fingerprint(current_fingerprint):
        return "no_action_capture_runtime_fingerprint_invalid"

    state = load_day_capture_runtime_fingerprint_state(trade_date)
    counts = tuple(
        _number(state.get(field))
        for field in ("frame_count", "missing_count", "unique_count")
    )
    if any(
        value is None or value < 0 or not value.is_integer()
        for value in counts
    ):
        return "no_action_capture_runtime_fingerprint_invalid"
    frame_count, missing_count, unique_count = (
        int(value) for value in counts if value is not None
    )
    if frame_count == 0 or missing_count > 0:
        return "no_action_capture_runtime_fingerprint_missing"
    if missing_count > frame_count or unique_count > frame_count:
        return "no_action_capture_runtime_fingerprint_invalid"
    if unique_count > 1:
        return "no_action_capture_runtime_fingerprint_changed"
    if unique_count != 1:
        return "no_action_capture_runtime_fingerprint_invalid"

    day_fingerprint = str(
        state.get("capture_runtime_fingerprint") or ""
    ).strip()
    if not is_capture_runtime_fingerprint(day_fingerprint):
        return "no_action_capture_runtime_fingerprint_invalid"
    if not (
        frame_fingerprint == day_fingerprint == current_fingerprint
    ):
        return "no_action_capture_runtime_fingerprint_mismatch"
    return None


def _previous_frame_in_window(
    frames: Sequence[Mapping[str, object]],
    captured_at: datetime,
) -> datetime | None:
    window = _window_index(captured_at)
    candidates = [
        value
        for row in frames[:-1]
        if (value := _as_datetime(row.get("captured_at"))) is not None
        and value < captured_at
        and _window_index(value) == window
    ]
    return max(candidates, default=None)


def _window_index(value: datetime) -> int | None:
    local = value.astimezone(SHANGHAI)
    current = local.time().replace(tzinfo=None)
    for index, (start, end) in enumerate(ENTRY_WINDOWS):
        if start <= current <= end:
            return index
    return None


def _has_complete_action_horizon(value: datetime) -> bool:
    local = value.astimezone(SHANGHAI)
    current = local.time().replace(tzinfo=None)
    horizon = (local + timedelta(seconds=60)).time().replace(tzinfo=None)
    return any(start <= current and horizon <= end for start, end in ENTRY_WINDOWS)


def _official_two_slot_evidence(
    snapshot: Mapping[str, object],
) -> tuple[list[str], bool]:
    return official_two_slot_evidence(snapshot)


def _frozen_two_slot_evidence(
    frame: Mapping[str, object],
) -> tuple[list[str], bool]:
    values = frame.get("formal_two_slot_symbols")
    if (
        frame.get("formal_two_slot_observed") is not True
        or not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or any(not isinstance(value, str) or not value.strip() for value in values)
    ):
        return [], False
    symbols = [value.strip() for value in values]
    if len(symbols) > 2 or len(symbols) != len(set(symbols)):
        return [], False
    return symbols, True


def _delayed_fill_outcome(
    action: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    captured_at = _as_datetime(action.get("captured_at"))
    if captured_at is None:
        return None
    projected_action = {
        **dict(action),
        "trade_date": _as_date(action.get("trade_date")) or captured_at.date(),
    }
    projected_observations: list[dict[str, object]] = []
    frames: list[dict[str, object]] = []
    for index, raw in enumerate(observations, start=1):
        row = dict(raw)
        frame_id = int(row.get("frame_id") or index)
        observed_at = _as_datetime(row.get("captured_at"))
        if observed_at is None:
            continue
        row["frame_id"] = frame_id
        row.setdefault("capture_state", "")
        projected_observations.append(row)
        frames.append(
            {
                "id": frame_id,
                "trade_date": observed_at.date(),
                "captured_at": observed_at,
            }
        )
    evidence = build_point_trigger_settlement_evidence(
        projected_action,
        frames,
        projected_observations,
    )
    return replay_delayed_fill_outcome(projected_action, evidence)


def _d1_outcome(
    action: Mapping[str, object],
    bars: Sequence[Mapping[str, object]],
    *,
    expected_d1_trade_date: date | None,
) -> dict[str, object] | None:
    fill_status = str(action.get("fill_status") or "")
    if fill_status == "pending":
        return None
    if fill_status != "filled":
        return {
            "d1_status": "not_filled",
            "d1_trade_date": None,
            "d1_close_price": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "double_cost_net_return_pct": None,
        }
    action_date = _as_date(action.get("trade_date"))
    fill_price = _number(action.get("fill_price"))
    limit_price = _number(action.get("limit_price"))
    if action_date is None or fill_price is None:
        return None
    if expected_d1_trade_date is None or expected_d1_trade_date <= action_date:
        return None
    next_bar = next(
        (
            row
            for row in bars
            if _as_date(row.get("trade_date")) == expected_d1_trade_date
        ),
        None,
    )
    close_price = _number((next_bar or {}).get("close_price"))
    d1_date = _as_date((next_bar or {}).get("trade_date"))
    if close_price is None or d1_date is None:
        return None
    normal = radar_validation._execution_outcome(
        fill_price,
        close_price,
        limit_price=limit_price,
        cost_multiplier=1.0,
    )
    stress = radar_validation._execution_outcome(
        fill_price,
        close_price,
        limit_price=limit_price,
        cost_multiplier=2.0,
    )
    if normal is None or stress is None:
        return None
    return {
        "d1_status": "closed",
        "d1_trade_date": d1_date,
        "d1_close_price": close_price,
        "gross_return_pct": round((close_price / fill_price - 1.0) * 100.0, 4),
        "net_return_pct": normal["net_return_pct"],
        "double_cost_net_return_pct": stress["net_return_pct"],
    }


def _resolve_target_trade_date(
    as_of: datetime,
    explicit: date | None,
) -> date | None:
    local_at = as_of.astimezone(SHANGHAI)
    current_date = local_at.date()
    latest_completed_date = (
        current_date
        if local_at.time().replace(tzinfo=None) >= CURRENT_DAY_FREEZE_TIME
        else current_date - timedelta(days=1)
    )
    if explicit is not None:
        return explicit if ELIGIBLE_AFTER < explicit <= latest_completed_date else None
    frozen_dates = {
        value
        for row in load_point_trigger_day_scopes()
        if (value := _scope_date(row)) is not None
    }
    candidates = {
        value
        for value in load_frame_dates()
        if value <= latest_completed_date
        and value > ELIGIBLE_AFTER
        and value not in frozen_dates
    }
    return min(candidates, default=None)


def _eligible_complete_scopes(
    scopes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result = [
        dict(row)
        for row in scopes
        if row.get("is_complete") is True
        and row.get("eligible_for_model") is True
        and (_scope_date(row) or ELIGIBLE_AFTER) > ELIGIBLE_AFTER
    ]
    return sorted(result, key=lambda row: _scope_date(row) or date.max)


def _phase_result(
    scopes: Sequence[Mapping[str, object]],
    *,
    rows_written: int,
    message: str | None = None,
    **extra: object,
) -> dict[str, object]:
    status = (
        "collecting_fit" if len(scopes) < FIT_DAY_COUNT else "collecting_calibration"
    )
    return {
        **_phase_counts(scopes),
        "status": status,
        "model_fingerprint": None,
        "model_status": None,
        "rows_written": rows_written,
        "message": message or status,
        **extra,
    }


def _phase_counts(scopes: Sequence[Mapping[str, object]]) -> dict[str, int]:
    count = len(scopes)
    return {
        "complete_day_count": count,
        "fit_day_count": min(count, FIT_DAY_COUNT),
        "calibration_day_count": min(
            max(count - FIT_DAY_COUNT, 0), CALIBRATION_DAY_COUNT
        ),
        "validation_day_count": max(count - MODEL_FREEZE_DAY_COUNT, 0),
    }


def _scope_date(scope: Mapping[str, object]) -> date | None:
    return _as_date(scope.get("trade_date"))


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported fingerprint value: {type(value).__name__}")


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return _local_datetime(parsed) if parsed.tzinfo is not None else None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return _local_datetime(value).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _datetime_key(value: object) -> str:
    parsed = _as_datetime(value)
    return parsed.isoformat() if parsed is not None else ""


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None
