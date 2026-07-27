"""Persistence boundary for the single pre-board decision contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
import os

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardExecutionMode,
    PreboardPolicyThresholds,
)
from alphaagent.server.services.limit_up.preboard_decision_model import (
    PreboardModelBundle,
    deserialize_preboard_model_bundle,
    serialize_preboard_model_bundle,
)


_ACTION_STAGE_FIELDS = {
    "fill": (
        "fill_status",
        {
            "fill_status",
            "fill_at",
            "fill_price",
            "fill_quote_observed_at",
            "settlement_evidence",
            "settlement_evidence_fingerprint",
        },
        "fill_closed_at",
    ),
    "formal_touch": (
        "formal_identity_status",
        {
            "formal_identity_status",
            "formal_event_at",
            "formal_identity_vt_symbol",
            "formal_identity_matched",
            "original_two_slot_matched",
        },
        "formal_identity_closed_at",
    ),
    "physical_touch": (
        "physical_touch_status",
        {"physical_touch_status", "physical_touch_at", "final_sealed"},
        "physical_touch_closed_at",
    ),
    "d1": (
        "d1_status",
        {
            "d1_status",
            "d1_trade_date",
            "d1_close_price",
            "gross_return_pct",
            "net_return_pct",
            "double_cost_net_return_pct",
        },
        "d1_closed_at",
    ),
}


def save_decision_feature_rows(rows: Sequence[Mapping[str, object]]) -> int:
    """Insert immutable live feature rows; duplicate frame identities are ignored."""

    values = [_feature_row_values(row) for row in rows]
    if not values:
        return 0
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_feature_rows
    statement = pg_insert(table).values(values)
    statement = statement.on_conflict_do_nothing(
        index_elements=("contract_version", "frame_id", "vt_symbol")
    )
    with session_scope() as session:
        result = session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


def load_decision_feature_rows(
    trade_dates: Sequence[date],
    *,
    symbols: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    requested = sorted(set(trade_dates))
    if not requested:
        return []
    requested_symbols = sorted(
        {str(symbol).strip() for symbol in symbols or () if str(symbol).strip()}
    )
    if symbols is not None and not requested_symbols:
        return []
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_feature_rows
    statement = (
        select(table)
        .where(
            table.c.contract_version == PREBOARD_DECISION_VERSION,
            table.c.trade_date.in_(requested),
        )
        .order_by(table.c.trade_date, table.c.captured_at, table.c.vt_symbol)
    )
    if requested_symbols:
        statement = statement.where(table.c.vt_symbol.in_(requested_symbols))
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [_restore_feature_row(row) for row in rows]


def load_decision_day_scopes() -> list[dict[str, object]]:
    """Load only scopes frozen under the active shared decision contract."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_day_scopes
    statement = (
        select(table)
        .where(table.c.contract_version == PREBOARD_DECISION_VERSION)
        .order_by(table.c.trade_date)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def label_decision_feature_rows(
    trade_date: date,
    labels: Mapping[tuple[int, str], Mapping[str, object]],
) -> int:
    """Attach future labels after features were frozen; never rewrite inputs."""

    if not labels:
        return 0
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_feature_rows
    updated = 0
    with session_scope() as session:
        for (frame_id, symbol), raw in labels.items():
            values = {
                "label_status": str(raw.get("label_status") or "known"),
                "formal_touch_within_3m": _optional_bool(
                    raw.get("formal_touch_within_3m")
                ),
                "eventual_formal_touch": _optional_bool(
                    raw.get("eventual_formal_touch")
                ),
            }
            result = session.execute(
                update(table)
                .where(
                    table.c.contract_version == PREBOARD_DECISION_VERSION,
                    table.c.trade_date == trade_date,
                    table.c.frame_id == int(frame_id),
                    table.c.vt_symbol == str(symbol),
                    table.c.label_status == "pending",
                )
                .values(**values)
            )
            updated += int(getattr(result, "rowcount", 0) or 0)
    return updated


def save_decision_day_scope(
    trade_date: date,
    *,
    status: str,
    frame_count: int,
    observation_count: int,
    feature_rows: Sequence[Mapping[str, object]],
    reason_codes: Sequence[str] = (),
    audit_metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Freeze one daily scope without rewriting an existing cohort."""

    complete = status == "complete"
    payload = [_json_mapping(row) for row in feature_rows]
    input_fingerprint = _sha256(payload)
    empty_fingerprint = _sha256([])
    values = {
        "contract_version": PREBOARD_DECISION_VERSION,
        "trade_date": trade_date,
        "status": str(status),
        "is_complete": complete,
        "eligible_for_model": complete
        and any(row.get("feature_status") == "scoreable" for row in feature_rows),
        "reason_codes": [str(value) for value in reason_codes],
        "frame_count": max(int(frame_count), 0),
        "observation_count": max(int(observation_count), 0),
        "audit_metrics": _json_mapping(audit_metrics or {}),
        "capture_runtime_fingerprint": None,
        "formal_baseline_order_projection_complete": True,
        "formal_baseline_order_count": 0,
        "formal_baseline_orders": [],
        "formal_baseline_orders_fingerprint": empty_fingerprint,
        "input_fingerprint": input_fingerprint,
        "cohort_fingerprint": _sha256(
            {"trade_date": trade_date.isoformat(), "rows": payload}
        ),
        "feature_row_count": len(feature_rows),
    }
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_day_scopes
    statement = pg_insert(table).values(**values).on_conflict_do_nothing(
        index_elements=("contract_version", "trade_date")
    )
    with session_scope() as session:
        result = session.execute(statement)
    return {
        "status": "frozen" if int(getattr(result, "rowcount", 0) or 0) else "already_frozen",
        "feature_row_count": len(feature_rows),
        "input_fingerprint": input_fingerprint,
    }


def save_decision_model(
    bundle: PreboardModelBundle,
    *,
    probability_qualification: Mapping[str, object],
    historical_promotion_status: str,
    thresholds: PreboardPolicyThresholds | None,
    validation_dates: Sequence[date] = (),
) -> dict[str, object]:
    """Freeze one model artifact for the active contract without overwriting it."""

    if (
        bundle.feature_version != PREBOARD_DECISION_VERSION
        or bundle.model_version != PREBOARD_DECISION_VERSION
    ):
        raise ValueError("inactive preboard model version")
    if not _fingerprint(bundle.fingerprint):
        raise ValueError("model fingerprint is invalid")
    qualification_status = str(
        probability_qualification.get("status") or "model_unavailable"
    )
    policy = _policy_values(thresholds)
    frozen_at = datetime.now(timezone.utc)
    artifact = serialize_preboard_model_bundle(bundle)
    feature_fingerprint = _sha256(list(bundle.feature_names))
    values: dict[str, object] = {
        "model_fingerprint": bundle.fingerprint,
        "contract_version": PREBOARD_DECISION_VERSION,
        "decision_version": PREBOARD_DECISION_VERSION,
        "feature_fingerprint": feature_fingerprint,
        "probability_qualification_status": qualification_status,
        "historical_promotion_status": str(historical_promotion_status),
        "policy_thresholds": policy,
        "status": "active" if qualification_status == "ready" else "rejected",
        "fit_trade_dates": [value.isoformat() for value in bundle.fit_dates],
        "calibration_trade_dates": [
            value.isoformat() for value in bundle.calibration_dates
        ],
        "validation_trade_dates": [
            value.isoformat() for value in sorted(set(validation_dates))
        ],
        "event_model_params": {"head": "touch_3m"},
        "identity_model_params": {"head": "eventual_touch"},
        "action_model_params": {},
        "frame_feature_fields": list(bundle.feature_names),
        "identity_feature_fields": [],
        "action_feature_fields": [],
        "training_input_fingerprint": bundle.training_input_fingerprint,
        "event_model_fingerprint": _sha256(
            {"model": bundle.fingerprint, "head": "touch_3m"}
        ),
        "identity_model_fingerprint": _sha256(
            {"model": bundle.fingerprint, "head": "eventual_touch"}
        ),
        "action_model_fingerprint": _sha256(
            {"model": bundle.fingerprint, "policy": policy}
        ),
        "calibration_threshold": (
            thresholds.minimum_touch_probability_3m if thresholds else None
        ),
        "calibration_metrics": _json_mapping(probability_qualification),
        "model_artifact": artifact,
        "record_fingerprint": "",
        "frozen_at": frozen_at,
    }
    values["record_fingerprint"] = _sha256(_json_mapping(values))
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_model_versions
    statement = pg_insert(table).values(**values).on_conflict_do_nothing(
        index_elements=("contract_version",)
    )
    with session_scope() as session:
        result = session.execute(statement)
    return {
        "status": (
            "frozen" if int(getattr(result, "rowcount", 0) or 0) else "already_frozen"
        ),
        "model_fingerprint": bundle.fingerprint,
        "feature_fingerprint": feature_fingerprint,
        "record_fingerprint": values["record_fingerprint"],
    }


def load_active_decision_runtime() -> dict[str, object] | None:
    """Load and verify the sole active model; old contracts cannot match."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_model_versions
    statement = (
        select(table)
        .where(
            table.c.contract_version == PREBOARD_DECISION_VERSION,
            table.c.decision_version == PREBOARD_DECISION_VERSION,
            table.c.status == "active",
        )
        .order_by(table.c.frozen_at, table.c.model_fingerprint)
        .limit(2)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError("multiple active preboard decision models are forbidden")
    row = dict(rows[0])
    if row.get("probability_qualification_status") != "ready":
        raise ValueError("active preboard model has not passed probability qualification")
    artifact = row.get("model_artifact")
    if not isinstance(artifact, Mapping):
        raise ValueError("active preboard model artifact is missing")
    bundle = deserialize_preboard_model_bundle(artifact)
    if (
        bundle.feature_version != PREBOARD_DECISION_VERSION
        or bundle.model_version != PREBOARD_DECISION_VERSION
        or bundle.fingerprint != row.get("model_fingerprint")
    ):
        raise ValueError("active preboard model contract mismatch")
    expected_features = _sha256(list(bundle.feature_names))
    if row.get("feature_fingerprint") != expected_features:
        raise ValueError("active preboard feature fingerprint mismatch")
    historical_status = str(row.get("historical_promotion_status") or "")
    configured_formal_fingerprint = str(
        os.environ.get("ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT") or ""
    ).strip()
    if (
        historical_status == "forward_pass_for_formal"
        and configured_formal_fingerprint == bundle.fingerprint
    ):
        execution_mode = PreboardExecutionMode.FORMAL
        formal_activation_status = "enabled"
    elif historical_status in {
        "historical_pass_for_shadow",
        "forward_pass_for_formal",
    }:
        execution_mode = PreboardExecutionMode.SHADOW
        formal_activation_status = (
            "fingerprint_mismatch"
            if configured_formal_fingerprint
            else "fingerprint_not_configured"
        )
    else:
        execution_mode = PreboardExecutionMode.RESEARCH_ONLY
        formal_activation_status = "not_eligible"
    thresholds = (
        _restore_policy_thresholds(row.get("policy_thresholds"))
        if execution_mode is not PreboardExecutionMode.RESEARCH_ONLY
        else None
    )
    return {
        "model_bundle": bundle,
        "thresholds": thresholds,
        "execution_mode": execution_mode,
        "probability_qualification_status": "ready",
        "historical_promotion_status": historical_status,
        "model_fingerprint": bundle.fingerprint,
        "feature_fingerprint": expected_features,
        "formal_activation_status": formal_activation_status,
    }


def save_decision_actions(
    rows: Sequence[Mapping[str, object]],
    *,
    thresholds: PreboardPolicyThresholds,
) -> int:
    """Persist only threshold-passing shadow/formal slot decisions."""

    values = [
        _action_row_values(row, thresholds=thresholds)
        for row in rows
        if str(row.get("decision_state") or "") == "actionable"
        and str(row.get("execution_mode") or "")
        in {PreboardExecutionMode.SHADOW.value, PreboardExecutionMode.FORMAL.value}
    ]
    if not values:
        return 0
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_actions
    statement = pg_insert(table).values(values).on_conflict_do_nothing()
    with session_scope() as session:
        result = session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


def load_decision_actions(
    *,
    trade_date: date | None = None,
    start: date | None = None,
    end: date | None = None,
    symbols: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """Load only actions emitted by the active shared contract."""

    if trade_date is not None and (start is not None or end is not None):
        raise ValueError("trade_date cannot be combined with start or end")
    requested_symbols = sorted(
        {str(symbol).strip() for symbol in symbols or () if str(symbol).strip()}
    )
    if symbols is not None and not requested_symbols:
        return []

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_actions
    statement = select(table).where(
        table.c.contract_version == PREBOARD_DECISION_VERSION,
        table.c.execution_mode.in_(("shadow", "formal")),
    )
    if trade_date is not None:
        statement = statement.where(table.c.trade_date == trade_date)
    if start is not None:
        statement = statement.where(table.c.trade_date >= start)
    if end is not None:
        statement = statement.where(table.c.trade_date <= end)
    if requested_symbols:
        statement = statement.where(table.c.vt_symbol.in_(requested_symbols))
    statement = statement.order_by(
        table.c.trade_date,
        table.c.captured_at,
        table.c.vt_symbol,
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def close_decision_action_stage(
    action: Mapping[str, object],
    *,
    stage: str,
    values: Mapping[str, object],
) -> dict[str, object]:
    """Close one current-contract action stage exactly once."""

    if stage not in _ACTION_STAGE_FIELDS:
        raise ValueError(f"unknown preboard action stage: {stage}")
    status_field, allowed_fields, closed_at_field = _ACTION_STAGE_FIELDS[stage]
    unexpected = sorted(set(values) - allowed_fields)
    if unexpected:
        raise ValueError(f"fields not allowed for {stage}: {', '.join(unexpected)}")
    status = str(values.get(status_field) or "")
    if not status or status == "pending":
        raise ValueError(f"{status_field} must close to a terminal status")
    model_fingerprint = _required_fingerprint(
        action.get("model_fingerprint"), "model_fingerprint"
    )
    captured_at = _required_datetime(action.get("captured_at"), "captured_at")
    symbol = _required_text(action.get("vt_symbol"), "vt_symbol")
    normalized = {
        key: _json_value(value) if key == "settlement_evidence" else value
        for key, value in values.items()
    }
    normalized[closed_at_field] = datetime.now(timezone.utc)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_actions
    identity = (
        table.c.contract_version == PREBOARD_DECISION_VERSION,
        table.c.model_fingerprint == model_fingerprint,
        table.c.captured_at == captured_at,
        table.c.vt_symbol == symbol,
    )
    with session_scope() as session:
        result = session.execute(
            update(table)
            .where(*identity, getattr(table.c, status_field) == "pending")
            .values(**normalized)
        )
        if int(getattr(result, "rowcount", 0) or 0) == 1:
            return {"status": "closed", "stage": stage}
        existing = (
            session.execute(
                select(*(getattr(table.c, field) for field in allowed_fields)).where(
                    *identity
                )
            )
            .mappings()
            .first()
        )
    if existing is None:
        raise KeyError("preboard decision action does not exist")
    if all(_equivalent(existing.get(key), value) for key, value in values.items()):
        return {"status": "already_closed", "stage": stage}
    raise RuntimeError(f"preboard action stage {stage} is already closed differently")


def _action_row_values(
    row: Mapping[str, object],
    *,
    thresholds: PreboardPolicyThresholds,
) -> dict[str, object]:
    if row.get("decision_version") != PREBOARD_DECISION_VERSION:
        raise ValueError("inactive preboard action version")
    mode = str(row.get("execution_mode") or "")
    if mode not in {"shadow", "formal"}:
        raise ValueError("research observations cannot create action rows")
    captured_at = _required_datetime(
        row.get("decision_at") or row.get("captured_at"),
        "decision_at",
    )
    touch = _required_probability(row.get("touch_probability_3m"), "touch_probability_3m")
    eventual = _required_probability(
        row.get("eventual_touch_probability"),
        "eventual_touch_probability",
    )
    portfolio_selected = row.get("portfolio_selected") is True
    slot = _optional_integer(row.get("daily_slot"))
    if portfolio_selected and slot not in {1, 2}:
        raise ValueError("portfolio recommendation requires daily_slot 1 or 2")
    if not portfolio_selected and slot is not None:
        raise ValueError("full recommendation outside portfolio cannot have daily_slot")
    decision = {
        "model_fingerprint": _required_fingerprint(
            row.get("model_fingerprint"), "model_fingerprint"
        ),
        "captured_at": captured_at,
        "vt_symbol": _required_text(row.get("vt_symbol"), "vt_symbol"),
        "contract_version": PREBOARD_DECISION_VERSION,
        "trade_date": _required_date(
            row.get("trade_date") or captured_at.date(), "trade_date"
        ),
        "daily_slot": slot,
        "portfolio_selected": portfolio_selected,
        "frame_id": _required_integer(row.get("frame_id"), "frame_id"),
        "quote_observed_at": _optional_datetime(row.get("quote_observed_at")),
        "last_price": _number(row.get("last_price")),
        "limit_price": _number(row.get("limit_price")),
        "action_probability": touch,
        "action_threshold": thresholds.minimum_touch_probability_3m,
        "event_probability": touch,
        "identity_score": eventual,
        "top1_margin": None,
        "candidate_count": max(_optional_integer(row.get("candidate_count")) or 1, 1),
        "input_fingerprint": _required_fingerprint(
            row.get("feature_fingerprint"), "feature_fingerprint"
        ),
        "decision_payload": _json_mapping(row),
        "execution_mode": mode,
        "decision_state": "actionable",
        "touch_probability_3m": touch,
        "eventual_touch_probability": eventual,
        "expected_d1_net_return_pct": _number(
            row.get("expected_d1_net_return_pct")
        ),
        "d1_win_probability": _number(row.get("d1_win_probability")),
        "seal_probability_given_touch": _number(
            row.get("seal_probability_given_touch")
        ),
        "actionable": mode == "formal",
        "execution_effect": "formal" if mode == "formal" else "shadow_only",
        "action_kind": "preboard_probability",
    }
    decision["decision_fingerprint"] = _sha256(_json_mapping(decision))
    return {
        **decision,
        "fill_status": "pending",
        "formal_identity_status": "pending",
        "original_two_slot_symbols": [],
        "physical_touch_status": "pending",
        "d1_status": "pending",
    }


def _policy_values(
    thresholds: PreboardPolicyThresholds | None,
) -> dict[str, object]:
    if thresholds is None:
        return {}
    return {
        "minimum_touch_probability_3m": thresholds.minimum_touch_probability_3m,
        "minimum_eventual_touch_probability": (
            thresholds.minimum_eventual_touch_probability
        ),
        "calibrated_dates": [value.isoformat() for value in thresholds.calibrated_dates],
        "fingerprint": thresholds.fingerprint,
    }


def _restore_policy_thresholds(value: object) -> PreboardPolicyThresholds:
    if not isinstance(value, Mapping):
        raise ValueError("active preboard policy thresholds are missing")
    dates = tuple(
        _required_date(item, "calibrated_date")
        for item in value.get("calibrated_dates") or []
    )
    return PreboardPolicyThresholds(
        minimum_touch_probability_3m=_required_probability(
            value.get("minimum_touch_probability_3m"),
            "minimum_touch_probability_3m",
        ),
        minimum_eventual_touch_probability=_required_probability(
            value.get("minimum_eventual_touch_probability"),
            "minimum_eventual_touch_probability",
        ),
        calibrated_dates=dates,
        fingerprint=_required_fingerprint(value.get("fingerprint"), "policy fingerprint"),
    )


def _equivalent(left: object, right: object) -> bool:
    if isinstance(left, datetime) and isinstance(right, datetime):
        return left == right
    if isinstance(left, date) and isinstance(right, date):
        return left == right
    return _json_value(left) == _json_value(right)


def _feature_row_values(row: Mapping[str, object]) -> dict[str, object]:
    if row.get("decision_version") != PREBOARD_DECISION_VERSION:
        raise ValueError("inactive preboard decision version")
    feature_status = str(row.get("feature_status") or "unavailable")
    feature_fingerprint = str(row.get("feature_fingerprint") or "")
    if feature_status == "scoreable" and not _fingerprint(feature_fingerprint):
        raise ValueError("scoreable row requires feature fingerprint")
    decision_at = _required_datetime(
        row.get("decision_at") or row.get("captured_at"),
        "decision_at",
    )
    known_at = _optional_datetime(row.get("known_at"))
    if known_at is not None and not _not_after(known_at, decision_at):
        raise ValueError("known_at must not be after decision_at")
    trade_date = _required_date(row.get("trade_date"), "trade_date")
    return {
        "contract_version": PREBOARD_DECISION_VERSION,
        "frame_id": _required_integer(row.get("frame_id"), "frame_id"),
        "vt_symbol": _required_text(row.get("vt_symbol"), "vt_symbol"),
        "trade_date": trade_date,
        "captured_at": decision_at,
        "name": str(row.get("name") or row.get("vt_symbol") or "")[:80],
        "last_price": _number(row.get("last_price")),
        "limit_price": _number(row.get("limit_price")),
        "quote_observed_at": _optional_datetime(row.get("quote_observed_at")),
        "action_frame_eligible": feature_status == "scoreable",
        "action_previous_frame_gap_seconds": None,
        "action_quote_coverage_ratio": None,
        "action_market_timing_observed": row.get("market_timing_state") is not None,
        "formal_two_slot_observed": False,
        "formal_two_slot_symbols": [],
        "frame_features": {},
        "identity_features": {},
        "feature_fingerprint": feature_fingerprint,
        "decision_payload": _json_mapping(row),
        "feature_status": feature_status,
        "formal_touch_within_3m": _optional_bool(
            row.get("formal_touch_within_3m")
        ),
        "eventual_formal_touch": _optional_bool(
            row.get("eventual_formal_touch")
        ),
        "source_quality": str(row.get("source_quality") or "unknown")[:40],
        "label_status": str(row.get("label_status") or "pending")[:40],
        "formal_event_within_60s": None,
        "formal_identity_within_60s": None,
        "formal_identity_vt_symbol": None,
        "formal_event_at": None,
    }


def _restore_feature_row(row: Mapping[str, object]) -> dict[str, object]:
    payload = row.get("decision_payload")
    payload = dict(payload) if isinstance(payload, Mapping) else {}
    return {
        **payload,
        "decision_version": PREBOARD_DECISION_VERSION,
        "frame_id": row.get("frame_id"),
        "vt_symbol": row.get("vt_symbol"),
        "trade_date": row.get("trade_date"),
        "decision_at": row.get("captured_at"),
        "feature_status": row.get("feature_status"),
        "feature_fingerprint": row.get("feature_fingerprint"),
        "formal_touch_within_3m": row.get("formal_touch_within_3m"),
        "eventual_formal_touch": row.get("eventual_formal_touch"),
        "source_quality": row.get("source_quality"),
        "label_status": row.get("label_status"),
        "_decision_payload_present": bool(payload),
    }


def _json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and not isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_integer(value: object, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is required") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _optional_integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_date(value: object, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError as exc:
        raise ValueError(f"{field} is required") from exc


def _required_datetime(value: object, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _required_probability(value: object, field: str) -> float:
    parsed = _number(value)
    if parsed is None or not 0.0 <= parsed <= 1.0:
        raise ValueError(f"{field} must be a probability")
    return parsed


def _required_fingerprint(value: object, field: str) -> str:
    parsed = str(value or "")
    if not _fingerprint(parsed):
        raise ValueError(f"{field} is invalid")
    return parsed


def _fingerprint(value: str) -> bool:
    return value.startswith("sha256:") and len(value) == 71


def _not_after(value: datetime, cutoff: datetime) -> bool:
    if value.tzinfo is None and cutoff.tzinfo is not None:
        value = value.replace(tzinfo=cutoff.tzinfo)
    elif value.tzinfo is not None and cutoff.tzinfo is None:
        value = value.replace(tzinfo=None)
    return value <= cutoff


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return "sha256:" + sha256(encoded).hexdigest()
