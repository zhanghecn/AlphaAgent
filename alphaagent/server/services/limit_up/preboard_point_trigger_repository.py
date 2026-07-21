"""Immutable persistence for the forward-only pre-board point trigger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select, update

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CALIBRATION_DAY_COUNT,
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    ENTRY_WINDOWS,
    FIT_DAY_COUNT,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    PointTriggerDayAudit,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_dataset import (
    point_trigger_input_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_settlement import (
    normalize_point_trigger_settlement_evidence,
    point_trigger_settlement_evidence_fingerprint,
    settlement_evidence_matches_action,
)
from alphaagent.server.services.limit_up.capture_runtime import (
    is_capture_runtime_fingerprint,
)


PENDING = "pending"
SHANGHAI = ZoneInfo("Asia/Shanghai")


class PointTriggerScopeConflict(RuntimeError):
    """Raised when a frozen day is presented with a different cohort."""


class PointTriggerModelConflict(RuntimeError):
    """Raised when an existing model identity is presented with new contents."""


class PointTriggerActionConflict(RuntimeError):
    """Raised when an immutable research decision is changed."""


class PointTriggerSettlementConflict(RuntimeError):
    """Raised when a closed research outcome is changed."""


_STAGE_FIELDS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "delayed_fill": (
        "fill_status",
        (
            "fill_status",
            "fill_at",
            "fill_price",
            "fill_quote_observed_at",
            "settlement_evidence",
            "settlement_evidence_fingerprint",
        ),
        "fill_closed_at",
    ),
    "formal_identity": (
        "formal_identity_status",
        (
            "formal_identity_status",
            "formal_event_at",
            "formal_identity_vt_symbol",
            "formal_identity_matched",
            "original_two_slot_symbols",
            "original_two_slot_matched",
        ),
        "formal_identity_closed_at",
    ),
    "physical_touch": (
        "physical_touch_status",
        (
            "physical_touch_status",
            "physical_touch_at",
            "final_sealed",
        ),
        "physical_touch_closed_at",
    ),
    "d1_outcome": (
        "d1_status",
        (
            "d1_status",
            "d1_trade_date",
            "d1_close_price",
            "gross_return_pct",
            "net_return_pct",
            "double_cost_net_return_pct",
        ),
        "d1_closed_at",
    ),
}


def freeze_point_trigger_day(
    audit: PointTriggerDayAudit | Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Freeze one audited date and, only when complete, its feature cohort."""

    audit_values = _validated_audit(audit)
    feature_rows = (
        [_validated_feature_row(row, audit_values) for row in rows]
        if audit_values["is_complete"]
        else []
    )
    scope_values, cohort_fingerprint = _point_trigger_day_record_values(
        audit_values,
        feature_rows,
    )
    scope_values["cohort_fingerprint"] = cohort_fingerprint
    input_fingerprint = str(scope_values["input_fingerprint"])

    engine = get_engine()
    schema.ensure_schema_once(engine)
    scopes = schema.limit_up_preboard_point_day_scopes
    features = schema.limit_up_preboard_point_feature_rows
    identity = (
        scopes.c.contract_version == scope_values["contract_version"],
        scopes.c.trade_date == scope_values["trade_date"],
    )
    with session_scope() as session:
        existing = (
            session.execute(select(scopes.c.cohort_fingerprint).where(*identity))
            .mappings()
            .first()
        )
        if existing is not None:
            if str(existing.get("cohort_fingerprint") or "") != cohort_fingerprint:
                raise PointTriggerScopeConflict(
                    "point-trigger day scope is already frozen with a different cohort"
                )
            return {
                "status": "already_frozen",
                "scope_written": 0,
                "rows_written": 0,
                "input_fingerprint": input_fingerprint,
                "cohort_fingerprint": cohort_fingerprint,
            }
        if feature_rows:
            session.execute(insert(features), feature_rows)
        session.execute(insert(scopes).values(**scope_values))
    return {
        "status": "frozen" if audit_values["is_complete"] else "frozen_incomplete",
        "scope_written": 1,
        "rows_written": len(feature_rows),
        "input_fingerprint": input_fingerprint,
        "cohort_fingerprint": cohort_fingerprint,
    }


def point_trigger_day_record_is_intact(
    scope: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> bool:
    """Verify a loaded day scope and all of its frozen labels/features."""

    try:
        audit_values = _validated_audit(_stored_scope_audit(scope))
        feature_rows = (
            [_validated_feature_row(row, audit_values) for row in rows]
            if audit_values["is_complete"]
            else []
        )
        scope_values, cohort_fingerprint = _point_trigger_day_record_values(
            audit_values,
            feature_rows,
        )
    except (TypeError, ValueError):
        return False
    if (
        int(scope.get("feature_row_count") or 0) != len(feature_rows)
        or int(scope.get("formal_baseline_order_count") or 0)
        != int(scope_values["formal_baseline_order_count"])
        or str(scope.get("formal_baseline_orders_fingerprint") or "")
        != str(scope_values["formal_baseline_orders_fingerprint"])
        or str(scope.get("input_fingerprint") or "")
        != str(scope_values["input_fingerprint"])
        or str(scope.get("cohort_fingerprint") or "") != cohort_fingerprint
    ):
        return False
    return all(
        str(raw.get("feature_fingerprint") or "")
        == str(normalized.get("feature_fingerprint") or "")
        for raw, normalized in zip(rows, feature_rows, strict=True)
    )


def point_trigger_day_cohort_fingerprint(
    audit: PointTriggerDayAudit | Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> str:
    """Build the canonical immutable cohort fingerprint without writing it."""

    audit_values = _validated_audit(audit)
    feature_rows = (
        [_validated_feature_row(row, audit_values) for row in rows]
        if audit_values["is_complete"]
        else []
    )
    _, cohort_fingerprint = _point_trigger_day_record_values(
        audit_values,
        feature_rows,
    )
    return cohort_fingerprint


def save_point_trigger_model(
    model: Mapping[str, object],
) -> dict[str, object]:
    """Save one complete model record without permitting later mutation."""

    values = _validated_model(model)
    record_fingerprint = _fingerprint(values)
    values["record_fingerprint"] = record_fingerprint

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_model_versions
    with session_scope() as session:
        existing = (
            session.execute(
                select(table.c.record_fingerprint).where(
                    table.c.model_fingerprint == values["model_fingerprint"]
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if str(existing.get("record_fingerprint") or "") != record_fingerprint:
                raise PointTriggerModelConflict(
                    "point-trigger model fingerprint is already frozen with different contents"
                )
            return {
                "status": "already_frozen",
                "model_fingerprint": values["model_fingerprint"],
                "record_fingerprint": record_fingerprint,
            }
        session.execute(insert(table).values(**values))
    return {
        "status": "frozen",
        "model_fingerprint": values["model_fingerprint"],
        "record_fingerprint": record_fingerprint,
    }


def point_trigger_model_record_fingerprint(
    model: Mapping[str, object],
) -> str:
    """Recompute the immutable fingerprint from a stored model record."""

    return _fingerprint(_validated_model(model))


def point_trigger_action_decision_fingerprint(
    action: Mapping[str, object],
) -> str:
    """Recompute the immutable fingerprint from a stored action decision."""

    return _fingerprint(_validated_action(action))


def save_point_trigger_action(
    action: Mapping[str, object],
) -> dict[str, object]:
    """Save one non-executable research decision exactly once."""

    values = _validated_action(action)
    decision_fingerprint = _fingerprint(values)
    values.update(
        {
            "decision_fingerprint": decision_fingerprint,
            "fill_status": PENDING,
            "formal_identity_status": PENDING,
            "physical_touch_status": PENDING,
            "d1_status": PENDING,
        }
    )

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_actions
    identity = _action_identity(table, values)
    with session_scope() as session:
        existing = (
            session.execute(select(table.c.decision_fingerprint).where(*identity))
            .mappings()
            .first()
        )
        if existing is not None:
            if str(existing.get("decision_fingerprint") or "") != decision_fingerprint:
                raise PointTriggerActionConflict(
                    "point-trigger action decision is immutable"
                )
            return {
                "status": "already_saved",
                "decision_fingerprint": decision_fingerprint,
            }
        session.execute(insert(table).values(**values))
    return {
        "status": "saved",
        "decision_fingerprint": decision_fingerprint,
    }


def close_point_trigger_action_stage(
    model_fingerprint: str,
    captured_at: datetime,
    vt_symbol: str,
    *,
    stage: str,
    values: Mapping[str, object],
) -> dict[str, object]:
    """Close one outcome stage atomically from pending; never revise it."""

    if stage not in _STAGE_FIELDS:
        raise ValueError(f"unknown point-trigger action stage: {stage}")
    status_field, allowed_fields, closed_at_field = _STAGE_FIELDS[stage]
    unexpected = sorted(set(values) - set(allowed_fields))
    if unexpected:
        raise ValueError(f"fields not allowed for {stage}: {', '.join(unexpected)}")
    identity_values = {
        "model_fingerprint": _required_text(model_fingerprint, "model_fingerprint"),
        "captured_at": _required_datetime(captured_at, "captured_at"),
        "vt_symbol": _required_text(vt_symbol, "vt_symbol"),
    }
    normalized = _validated_stage_values(stage, values)
    status = str(normalized.get(status_field) or "").strip()
    if not status or status == PENDING:
        raise ValueError(f"{status_field} must close to a non-pending status")
    if stage == "delayed_fill" and not settlement_evidence_matches_action(
        normalized["settlement_evidence"],
        {
            **identity_values,
            "trade_date": identity_values["captured_at"].astimezone(SHANGHAI).date(),
        },
    ):
        raise ValueError("settlement_evidence does not belong to the action")
    closed_at = datetime.now(timezone.utc)
    update_values = {**normalized, closed_at_field: closed_at}

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_actions
    identity = _action_identity(table, identity_values)
    with session_scope() as session:
        result = session.execute(
            update(table)
            .where(*identity, getattr(table.c, status_field) == PENDING)
            .values(**update_values)
        )
        if int(getattr(result, "rowcount", 0) or 0) == 1:
            return {"status": "closed", "stage": stage}
        selected_fields = [getattr(table.c, field) for field in allowed_fields]
        selected_fields.append(getattr(table.c, closed_at_field))
        existing = (
            session.execute(select(*selected_fields).where(*identity))
            .mappings()
            .first()
        )
        if existing is None:
            raise KeyError("point-trigger action does not exist")
        if all(
            _equivalent(existing.get(field), value)
            for field, value in normalized.items()
        ):
            return {"status": "already_closed", "stage": stage}
        raise PointTriggerSettlementConflict(
            f"point-trigger action stage {stage} is already closed with different values"
        )


def load_point_trigger_day_scopes(
    *,
    contract_version: str = CONTRACT_VERSION,
) -> list[dict[str, object]]:
    """Load frozen day scopes in chronological order."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_day_scopes
    with session_scope() as session:
        rows = (
            session.execute(
                select(table)
                .where(table.c.contract_version == str(contract_version))
                .order_by(table.c.trade_date)
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def load_point_trigger_feature_rows(
    trade_dates: Sequence[date],
    *,
    contract_version: str = CONTRACT_VERSION,
) -> list[dict[str, object]]:
    """Load the exact immutable feature cohorts requested by model fitting."""

    requested = sorted(set(trade_dates))
    if not requested:
        return []
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_feature_rows
    with session_scope() as session:
        rows = (
            session.execute(
                select(table)
                .where(
                    table.c.contract_version == str(contract_version),
                    table.c.trade_date.in_(requested),
                )
                .order_by(table.c.trade_date, table.c.captured_at, table.c.vt_symbol)
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def load_point_trigger_models(
    *,
    contract_version: str = CONTRACT_VERSION,
) -> list[dict[str, object]]:
    """Load every frozen model decision for this research contract."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_model_versions
    with session_scope() as session:
        rows = (
            session.execute(
                select(table)
                .where(table.c.contract_version == str(contract_version))
                .order_by(table.c.frozen_at, table.c.model_fingerprint)
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def load_active_point_trigger_model(
    *,
    contract_version: str = CONTRACT_VERSION,
) -> dict[str, object] | None:
    """Return the unique active frozen model, failing closed on ambiguity."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_model_versions
    with session_scope() as session:
        rows = (
            session.execute(
                select(table)
                .where(
                    table.c.contract_version == str(contract_version),
                    table.c.status == "active",
                )
                .order_by(table.c.frozen_at, table.c.model_fingerprint)
                .limit(2)
            )
            .mappings()
            .all()
        )
    if len(rows) > 1:
        raise PointTriggerModelConflict(
            "multiple active point-trigger models are forbidden"
        )
    return dict(rows[0]) if rows else None


def load_point_trigger_actions(
    *,
    model_fingerprint: str | None = None,
    trade_date: date | None = None,
) -> list[dict[str, object]]:
    """Load a bounded action ledger slice for scoring or settlement."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_preboard_point_actions
    statement = select(table)
    if model_fingerprint:
        statement = statement.where(table.c.model_fingerprint == str(model_fingerprint))
    if trade_date is not None:
        statement = statement.where(table.c.trade_date == trade_date)
    statement = statement.order_by(
        table.c.trade_date,
        table.c.captured_at,
        table.c.vt_symbol,
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def _validated_audit(
    audit: PointTriggerDayAudit | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(audit, Mapping):
        raw = dict(audit)
    elif is_dataclass(audit):
        raw = asdict(audit)
    else:
        raise TypeError("audit must be PointTriggerDayAudit or a mapping")
    contract_version = _required_text(raw.get("contract_version"), "contract_version")
    if contract_version != CONTRACT_VERSION:
        raise ValueError("audit contract_version does not match the frozen contract")
    trade_date = _required_date(raw.get("trade_date"), "trade_date")
    if trade_date <= ELIGIBLE_AFTER:
        raise ValueError("audit trade_date must be after eligible_after")
    projection_complete = _required_boolean(
        raw.get("formal_baseline_order_projection_complete"),
        "formal_baseline_order_projection_complete",
    )
    formal_orders = _validated_formal_baseline_orders(
        raw.get("formal_baseline_orders"),
        trade_date=trade_date,
    )
    is_complete = bool(raw.get("is_complete"))
    capture_runtime_fingerprint = _optional_text(
        raw.get("capture_runtime_fingerprint")
    )
    if (
        capture_runtime_fingerprint is not None
        and not is_capture_runtime_fingerprint(capture_runtime_fingerprint)
    ):
        raise ValueError("capture_runtime_fingerprint is invalid")
    if is_complete and capture_runtime_fingerprint is None:
        raise ValueError("complete audit requires a capture runtime fingerprint")
    if is_complete and not projection_complete:
        raise ValueError("complete audit requires a formal baseline order projection")
    if not projection_complete and formal_orders:
        raise ValueError("incomplete formal baseline order projection must be empty")
    return {
        "contract_version": contract_version,
        "trade_date": trade_date,
        "status": _required_text(raw.get("status"), "status"),
        "is_complete": is_complete,
        "eligible_for_model": bool(raw.get("eligible_for_model")),
        "reason_codes": [str(value) for value in raw.get("reason_codes") or []],
        "frame_count": _required_nonnegative_integer(
            raw.get("frame_count"), "frame_count"
        ),
        "observation_count": _required_nonnegative_integer(
            raw.get("observation_count"), "observation_count"
        ),
        "audit_metrics": _json_mapping(raw.get("metrics"), "metrics"),
        "capture_runtime_fingerprint": capture_runtime_fingerprint,
        "formal_baseline_order_projection_complete": projection_complete,
        "formal_baseline_orders": formal_orders,
    }


def _point_trigger_day_record_values(
    audit_values: Mapping[str, object],
    feature_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], str]:
    input_fingerprint = (
        point_trigger_input_fingerprint(feature_rows)
        if feature_rows
        else _fingerprint({"audit": audit_values, "feature_rows": []})
    )
    formal_orders = list(audit_values["formal_baseline_orders"])
    scope_values = {
        **dict(audit_values),
        "formal_baseline_order_count": len(formal_orders),
        "formal_baseline_orders_fingerprint": _fingerprint(formal_orders),
        "input_fingerprint": input_fingerprint,
        "feature_row_count": len(feature_rows),
    }
    cohort_fingerprint = _fingerprint(
        {
            "scope": scope_values,
            "feature_rows": list(feature_rows),
        }
    )
    return scope_values, cohort_fingerprint


def _stored_scope_audit(scope: Mapping[str, object]) -> dict[str, object]:
    return {
        "contract_version": scope.get("contract_version"),
        "trade_date": scope.get("trade_date"),
        "status": scope.get("status"),
        "is_complete": scope.get("is_complete"),
        "eligible_for_model": scope.get("eligible_for_model"),
        "reason_codes": scope.get("reason_codes"),
        "frame_count": scope.get("frame_count"),
        "observation_count": scope.get("observation_count"),
        "metrics": scope.get("audit_metrics"),
        "capture_runtime_fingerprint": scope.get(
            "capture_runtime_fingerprint"
        ),
        "formal_baseline_order_projection_complete": scope.get(
            "formal_baseline_order_projection_complete"
        ),
        "formal_baseline_orders": scope.get("formal_baseline_orders"),
    }


def _validated_formal_baseline_orders(
    value: object,
    *,
    trade_date: date,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("formal_baseline_orders must be a sequence")
    orders = [
        _validated_formal_baseline_order(order, trade_date=trade_date)
        for order in value
    ]
    symbols = [str(order["vt_symbol"]) for order in orders]
    if len(symbols) != len(set(symbols)):
        raise ValueError("formal_baseline_orders must contain one order per stock-day")
    captured = [str(order["source_captured_at"]) for order in orders]
    if captured != sorted(captured):
        raise ValueError("formal_baseline_orders must preserve arrival order")
    return orders


def _validated_formal_baseline_order(
    value: object,
    *,
    trade_date: date,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("formal_baseline_orders must contain mappings")
    expected_fields = {
        "vt_symbol",
        "name",
        "lane",
        "entry_date",
        "signal_date",
        "buy_time",
        "entry_price",
        "limit_price",
        "rank_score",
        "pool_rank",
        "source_frame_id",
        "source_captured_at",
        "source",
    }
    if set(value) != expected_fields:
        raise ValueError("formal baseline order does not match its frozen contract")
    entry_date = _required_date(value.get("entry_date"), "entry_date")
    signal_date = _required_date(value.get("signal_date"), "signal_date")
    if entry_date != trade_date or signal_date != trade_date:
        raise ValueError("formal baseline order is outside the audited day")
    lane = _required_text(value.get("lane"), "lane")
    if lane not in {"first_board", "two_to_three"}:
        raise ValueError("formal baseline order lane is not executable")
    buy_time = _required_iso_time(value.get("buy_time"), "buy_time")
    captured_at = _required_iso_datetime(
        value.get("source_captured_at"),
        "source_captured_at",
    )
    local_capture = datetime.fromisoformat(captured_at).astimezone(SHANGHAI)
    if (
        local_capture.date() != trade_date
        or local_capture.strftime("%H:%M:%S") != buy_time
    ):
        raise ValueError("formal baseline order time does not match its source frame")
    entry_price = _required_number(value.get("entry_price"), "entry_price")
    limit_price = _required_number(value.get("limit_price"), "limit_price")
    if entry_price <= 0.0 or limit_price <= 0.0 or entry_price != limit_price:
        raise ValueError("formal baseline order must enter at its positive limit price")
    pool_rank = _required_nonnegative_integer(value.get("pool_rank"), "pool_rank")
    if pool_rank not in (1, 2):
        raise ValueError("formal baseline order pool_rank must be 1 or 2")
    source = _required_text(value.get("source"), "source")
    if source != "saved_live_formal_portfolio":
        raise ValueError("formal baseline order source is not the saved live portfolio")
    return {
        "vt_symbol": _required_text(value.get("vt_symbol"), "vt_symbol"),
        "name": _required_text(value.get("name"), "name"),
        "lane": lane,
        "entry_date": entry_date.isoformat(),
        "signal_date": signal_date.isoformat(),
        "buy_time": buy_time,
        "entry_price": entry_price,
        "limit_price": limit_price,
        "rank_score": _required_number(value.get("rank_score"), "rank_score"),
        "pool_rank": pool_rank,
        "source_frame_id": _required_nonnegative_integer(
            value.get("source_frame_id"), "source_frame_id"
        ),
        "source_captured_at": captured_at,
        "source": source,
    }


def _validated_feature_row(
    row: Mapping[str, object],
    audit: Mapping[str, object],
) -> dict[str, object]:
    contract_version = _required_text(row.get("contract_version"), "contract_version")
    trade_date = _required_date(row.get("trade_date"), "trade_date")
    if (
        contract_version != audit["contract_version"]
        or trade_date != audit["trade_date"]
    ):
        raise ValueError("feature row is outside the audited day scope")
    frame_features = _exact_feature_mapping(
        row.get("frame_features"), FRAME_FEATURE_FIELDS, "frame_features"
    )
    identity_features = _exact_feature_mapping(
        row.get("identity_features"), IDENTITY_FEATURE_FIELDS, "identity_features"
    )
    captured_at = _required_datetime(row.get("captured_at"), "captured_at")
    action_previous_gap = _optional_number(
        row.get("action_previous_frame_gap_seconds"),
        "action_previous_frame_gap_seconds",
    )
    action_quote_coverage = _optional_number(
        row.get("action_quote_coverage_ratio"),
        "action_quote_coverage_ratio",
    )
    action_market_timing_observed = _required_boolean(
        row.get("action_market_timing_observed"),
        "action_market_timing_observed",
    )
    formal_two_slot_observed = _required_boolean(
        row.get("formal_two_slot_observed"), "formal_two_slot_observed"
    )
    if formal_two_slot_observed is not True:
        raise ValueError("complete feature rows require formal two-slot evidence")
    action_frame_eligible = _required_boolean(
        row.get("action_frame_eligible"), "action_frame_eligible"
    )
    expected_action_eligible = _expected_action_frame_eligible(
        captured_at,
        previous_gap_seconds=action_previous_gap,
        quote_coverage_ratio=action_quote_coverage,
        market_timing_observed=action_market_timing_observed,
        formal_two_slot_observed=formal_two_slot_observed,
    )
    if action_frame_eligible is not expected_action_eligible:
        raise ValueError("action_frame_eligible does not match its frozen inputs")
    values = {
        "contract_version": contract_version,
        "frame_id": _required_nonnegative_integer(row.get("frame_id"), "frame_id"),
        "vt_symbol": _required_text(row.get("vt_symbol"), "vt_symbol"),
        "trade_date": trade_date,
        "captured_at": captured_at,
        "name": str(row.get("name") or ""),
        "last_price": _optional_number(row.get("last_price"), "last_price"),
        "limit_price": _optional_number(row.get("limit_price"), "limit_price"),
        "quote_observed_at": _optional_datetime(
            row.get("quote_observed_at"), "quote_observed_at"
        ),
        "action_frame_eligible": action_frame_eligible,
        "action_previous_frame_gap_seconds": action_previous_gap,
        "action_quote_coverage_ratio": action_quote_coverage,
        "action_market_timing_observed": action_market_timing_observed,
        "formal_two_slot_observed": formal_two_slot_observed,
        "formal_two_slot_symbols": _validated_two_slot_symbols(
            row.get("formal_two_slot_symbols"),
            observed=row.get("formal_two_slot_observed"),
        ),
        "frame_features": frame_features,
        "identity_features": identity_features,
        "label_status": _required_text(row.get("label_status"), "label_status"),
        "formal_event_within_60s": _optional_boolean(
            row.get("formal_event_within_60s"), "formal_event_within_60s"
        ),
        "formal_identity_within_60s": _optional_boolean(
            row.get("formal_identity_within_60s"),
            "formal_identity_within_60s",
        ),
        "formal_identity_vt_symbol": _optional_text(
            row.get("formal_identity_vt_symbol")
        ),
        "formal_event_at": _optional_datetime(
            row.get("formal_event_at"), "formal_event_at"
        ),
    }
    values["feature_fingerprint"] = point_trigger_input_fingerprint([values])
    return values


def _validated_model(model: Mapping[str, object]) -> dict[str, object]:
    contract_version = _required_text(model.get("contract_version"), "contract_version")
    if contract_version != CONTRACT_VERSION:
        raise ValueError("model contract_version does not match the frozen contract")
    fit_dates = _date_list(model.get("fit_trade_dates"), "fit_trade_dates")
    calibration_dates = _date_list(
        model.get("calibration_trade_dates"), "calibration_trade_dates"
    )
    validation_dates = _date_list(
        model.get("validation_trade_dates"), "validation_trade_dates"
    )
    cohorts = [set(fit_dates), set(calibration_dates), set(validation_dates)]
    frozen_stage_dates_valid = (
        len(fit_dates) == FIT_DAY_COUNT
        and len(calibration_dates) == CALIBRATION_DAY_COUNT
        and not validation_dates
        and len(cohorts[0]) == FIT_DAY_COUNT
        and len(cohorts[1]) == CALIBRATION_DAY_COUNT
        and fit_dates == sorted(fit_dates)
        and calibration_dates == sorted(calibration_dates)
        and all(value > ELIGIBLE_AFTER for value in (*fit_dates, *calibration_dates))
        and fit_dates[-1] < calibration_dates[0]
    )
    if not frozen_stage_dates_valid or any(
        cohorts[left] & cohorts[right]
        for left in range(3)
        for right in range(left + 1, 3)
    ):
        raise ValueError(
            "model date cohorts must match the frozen 40/15 contract after eligible_after"
        )
    frame_fields = _text_list(model.get("frame_feature_fields"), "frame_feature_fields")
    identity_fields = _text_list(
        model.get("identity_feature_fields"), "identity_feature_fields"
    )
    if tuple(frame_fields) != FRAME_FEATURE_FIELDS:
        raise ValueError("frame feature whitelist does not match the frozen contract")
    if tuple(identity_fields) != IDENTITY_FEATURE_FIELDS:
        raise ValueError(
            "identity feature whitelist does not match the frozen contract"
        )
    frozen_at = _required_datetime(model.get("frozen_at"), "frozen_at")
    calibration_close = datetime.combine(
        calibration_dates[-1],
        time(15, 0),
        tzinfo=SHANGHAI,
    )
    if frozen_at.astimezone(SHANGHAI) < calibration_close:
        raise ValueError("model date cohorts cannot freeze before calibration closes")
    threshold = _optional_probability(
        model.get("calibration_threshold"), "calibration_threshold"
    )
    return {
        "model_fingerprint": _required_text(
            model.get("model_fingerprint"), "model_fingerprint"
        ),
        "contract_version": contract_version,
        "status": _required_text(model.get("status"), "status"),
        "fit_trade_dates": [value.isoformat() for value in fit_dates],
        "calibration_trade_dates": [value.isoformat() for value in calibration_dates],
        "validation_trade_dates": [value.isoformat() for value in validation_dates],
        "event_model_params": _json_mapping(
            model.get("event_model_params"), "event_model_params"
        ),
        "identity_model_params": _json_mapping(
            model.get("identity_model_params"), "identity_model_params"
        ),
        "action_model_params": _json_mapping(
            model.get("action_model_params"), "action_model_params"
        ),
        "frame_feature_fields": frame_fields,
        "identity_feature_fields": identity_fields,
        "action_feature_fields": _text_list(
            model.get("action_feature_fields"), "action_feature_fields"
        ),
        "training_input_fingerprint": _required_text(
            model.get("training_input_fingerprint"), "training_input_fingerprint"
        ),
        "event_model_fingerprint": _required_text(
            model.get("event_model_fingerprint"), "event_model_fingerprint"
        ),
        "identity_model_fingerprint": _required_text(
            model.get("identity_model_fingerprint"), "identity_model_fingerprint"
        ),
        "action_model_fingerprint": _required_text(
            model.get("action_model_fingerprint"), "action_model_fingerprint"
        ),
        "calibration_threshold": threshold,
        "calibration_metrics": _json_mapping(
            model.get("calibration_metrics"), "calibration_metrics"
        ),
        "model_artifact": _json_mapping(model.get("model_artifact"), "model_artifact"),
        "frozen_at": frozen_at,
    }


def _validated_action(action: Mapping[str, object]) -> dict[str, object]:
    contract_version = _required_text(
        action.get("contract_version"), "contract_version"
    )
    if contract_version != CONTRACT_VERSION:
        raise ValueError("action contract_version does not match the frozen contract")
    if action.get("actionable") not in (None, False):
        raise ValueError("point-trigger research actions must not be actionable")
    execution_effect = str(action.get("execution_effect") or "none_research_only")
    if execution_effect != "none_research_only":
        raise ValueError("point-trigger research actions cannot affect execution")
    action_kind = str(action.get("action_kind") or "research_action")
    if action_kind != "research_action":
        raise ValueError("point-trigger actions must use research_action")
    captured_at = _required_datetime(action.get("captured_at"), "captured_at")
    trade_date = _required_date(action.get("trade_date"), "trade_date")
    if captured_at.astimezone(SHANGHAI).date() != trade_date:
        raise ValueError("action trade_date must match captured_at")
    daily_slot = _required_nonnegative_integer(action.get("daily_slot"), "daily_slot")
    if daily_slot not in (1, 2):
        raise ValueError("action daily_slot must be 1 or 2")
    local_capture = captured_at.astimezone(SHANGHAI)
    local_horizon = local_capture + timedelta(seconds=60)
    if not any(
        start <= local_capture.time().replace(tzinfo=None) <= end
        and local_horizon.time().replace(tzinfo=None) <= end
        for start, end in ENTRY_WINDOWS
    ):
        raise ValueError("action must have a complete in-session horizon")
    symbol = _required_text(action.get("vt_symbol"), "vt_symbol")
    quote_observed_at = _required_datetime(
        action.get("quote_observed_at"),
        "quote_observed_at",
    )
    quote_age = (captured_at - quote_observed_at).total_seconds()
    if not 0.0 <= quote_age <= 60.0:
        raise ValueError("action quote must be known and fresh at capture time")
    last_price = _required_number(action.get("last_price"), "last_price")
    limit_price = _required_number(action.get("limit_price"), "limit_price")
    if last_price <= 0.0 or limit_price <= 0.0 or last_price >= limit_price:
        raise ValueError("action must be saved strictly before the limit price")
    action_probability = _required_probability(
        action.get("action_probability"), "action_probability"
    )
    action_threshold = _required_probability(
        action.get("action_threshold"), "action_threshold"
    )
    if action_probability < action_threshold:
        raise ValueError("action probability must meet its frozen threshold")
    candidate_count = _required_nonnegative_integer(
        action.get("candidate_count"), "candidate_count"
    )
    if candidate_count < 1:
        raise ValueError("action candidate_count must be positive")
    decision_payload = _validated_action_decision_payload(
        action.get("decision_payload"),
        symbol=symbol,
        candidate_count=candidate_count,
    )
    return {
        "model_fingerprint": _required_text(
            action.get("model_fingerprint"), "model_fingerprint"
        ),
        "captured_at": captured_at,
        "vt_symbol": symbol,
        "contract_version": contract_version,
        "trade_date": trade_date,
        "daily_slot": daily_slot,
        "frame_id": _required_nonnegative_integer(action.get("frame_id"), "frame_id"),
        "quote_observed_at": quote_observed_at,
        "last_price": last_price,
        "limit_price": limit_price,
        "action_probability": action_probability,
        "action_threshold": action_threshold,
        "event_probability": _required_probability(
            action.get("event_probability"), "event_probability"
        ),
        "identity_score": _required_number(
            action.get("identity_score"), "identity_score"
        ),
        "top1_margin": _optional_number(action.get("top1_margin"), "top1_margin"),
        "candidate_count": candidate_count,
        "input_fingerprint": _required_text(
            action.get("input_fingerprint"), "input_fingerprint"
        ),
        "decision_payload": decision_payload,
        "actionable": False,
        "execution_effect": execution_effect,
        "action_kind": action_kind,
    }


def _validated_action_decision_payload(
    value: object,
    *,
    symbol: str,
    candidate_count: int,
) -> dict[str, object]:
    payload = _json_mapping(value, "decision_payload")
    expected_fields = {
        "eligible_candidate_symbols",
        "concurrent_formal_two_slot_symbols",
        "concurrent_formal_two_slot_observed",
        "event_model_fingerprint",
        "identity_model_fingerprint",
        "action_model_fingerprint",
    }
    if set(payload) != expected_fields:
        raise ValueError("decision_payload does not match the frozen contract")
    eligible = _text_list(
        payload.get("eligible_candidate_symbols"),
        "eligible_candidate_symbols",
    )
    two_slot = _text_list(
        payload.get("concurrent_formal_two_slot_symbols"),
        "concurrent_formal_two_slot_symbols",
    )
    if symbol not in eligible or len(eligible) != candidate_count:
        raise ValueError("decision candidate cohort is inconsistent")
    if len(two_slot) > 2:
        raise ValueError("formal two-slot evidence cannot exceed two symbols")
    if payload.get("concurrent_formal_two_slot_observed") is not True:
        raise ValueError("formal two-slot evidence must be observed")
    return {
        "eligible_candidate_symbols": eligible,
        "concurrent_formal_two_slot_symbols": two_slot,
        "concurrent_formal_two_slot_observed": True,
        "event_model_fingerprint": _required_text(
            payload.get("event_model_fingerprint"),
            "event_model_fingerprint",
        ),
        "identity_model_fingerprint": _required_text(
            payload.get("identity_model_fingerprint"),
            "identity_model_fingerprint",
        ),
        "action_model_fingerprint": _required_text(
            payload.get("action_model_fingerprint"),
            "action_model_fingerprint",
        ),
    }


def _validated_stage_values(
    stage: str,
    values: Mapping[str, object],
) -> dict[str, object]:
    normalized = dict(values)
    datetime_fields = {
        "fill_at",
        "fill_quote_observed_at",
        "formal_event_at",
        "physical_touch_at",
    }
    number_fields = {
        "fill_price",
        "d1_close_price",
        "gross_return_pct",
        "net_return_pct",
        "double_cost_net_return_pct",
    }
    boolean_fields = {
        "formal_identity_matched",
        "original_two_slot_matched",
        "final_sealed",
    }
    for field in datetime_fields & normalized.keys():
        normalized[field] = _optional_datetime(normalized[field], field)
    for field in number_fields & normalized.keys():
        normalized[field] = _optional_number(normalized[field], field)
    for field in boolean_fields & normalized.keys():
        normalized[field] = _optional_boolean(normalized[field], field)
    if "d1_trade_date" in normalized:
        normalized["d1_trade_date"] = (
            _required_date(normalized["d1_trade_date"], "d1_trade_date")
            if normalized["d1_trade_date"] is not None
            else None
        )
    if "formal_identity_vt_symbol" in normalized:
        normalized["formal_identity_vt_symbol"] = _optional_text(
            normalized["formal_identity_vt_symbol"]
        )
    if "original_two_slot_symbols" in normalized:
        normalized["original_two_slot_symbols"] = _text_list(
            normalized["original_two_slot_symbols"], "original_two_slot_symbols"
        )
    if stage == "delayed_fill":
        if {
            "settlement_evidence",
            "settlement_evidence_fingerprint",
        } - normalized.keys():
            raise ValueError("delayed_fill requires immutable settlement evidence")
        evidence = normalize_point_trigger_settlement_evidence(
            normalized["settlement_evidence"]
        )
        evidence_fingerprint = _required_text(
            normalized["settlement_evidence_fingerprint"],
            "settlement_evidence_fingerprint",
        )
        if evidence_fingerprint != point_trigger_settlement_evidence_fingerprint(
            evidence
        ):
            raise ValueError("settlement_evidence_fingerprint does not match evidence")
        normalized["settlement_evidence"] = evidence
        normalized["settlement_evidence_fingerprint"] = evidence_fingerprint
    return normalized


def _action_identity(table, values: Mapping[str, object]) -> tuple[object, ...]:
    return (
        table.c.model_fingerprint == values["model_fingerprint"],
        table.c.captured_at == values["captured_at"],
        table.c.vt_symbol == values["vt_symbol"],
    )


def _exact_feature_mapping(
    value: object,
    fields: Sequence[str],
    name: str,
) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    missing = sorted(set(fields) - set(value))
    extra = sorted(set(value) - set(fields))
    if missing or extra:
        raise ValueError(f"{name} does not match its frozen field whitelist")
    return {
        field: _required_number(value[field], f"{name}.{field}") for field in fields
    }


def _json_mapping(value: object, name: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    normalized = _canonical_value(dict(value))
    if not isinstance(normalized, dict):
        raise ValueError(f"{name} must be a JSON object")
    return normalized


def _json_scalar(value: object, name: str) -> object:
    normalized = _canonical_value(value)
    if isinstance(normalized, (dict, list)):
        raise ValueError(f"{name} must be a scalar")
    return normalized


def _text_list(value: object, name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    result = [str(item).strip() for item in value]
    if any(not item for item in result) or len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique non-empty fields")
    return result


def _date_list(value: object, name: str) -> list[date]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    return [_required_date(item, name) for item in value]


def _required_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_date(value: object, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date") from exc
    raise ValueError(f"{name} is required")


def _required_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _required_iso_datetime(value: object, name: str) -> str:
    if isinstance(value, datetime):
        parsed = _required_datetime(value, name)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO datetime") from exc
        parsed = _required_datetime(parsed, name)
    else:
        raise ValueError(f"{name} is required")
    return parsed.astimezone(SHANGHAI).isoformat()


def _required_iso_time(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO time")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO time") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{name} must not include a timezone")
    return parsed.replace(microsecond=0).isoformat()


def _optional_datetime(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    return _required_datetime(value, name)


def _required_number(value: object, name: str) -> float:
    number = _optional_number(value, name)
    if number is None:
        raise ValueError(f"{name} is required")
    return number


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _required_probability(value: object, name: str) -> float:
    number = _required_number(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _optional_probability(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _required_probability(value, name)


def _required_nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if number < 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{name} must be a non-negative integer")
    return number


def _optional_boolean(value: object, name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _required_boolean(value: object, name: str) -> bool:
    parsed = _optional_boolean(value, name)
    if parsed is None:
        raise ValueError(f"{name} is required")
    return parsed


def _validated_two_slot_symbols(
    value: object,
    *,
    observed: object,
) -> list[str]:
    symbols = _text_list(value, "formal_two_slot_symbols")
    if len(symbols) > 2:
        raise ValueError("formal_two_slot_symbols cannot contain more than two symbols")
    if observed is not True and symbols:
        raise ValueError("unobserved formal two-slot evidence cannot contain symbols")
    return symbols


def _expected_action_frame_eligible(
    captured_at: datetime,
    *,
    previous_gap_seconds: float | None,
    quote_coverage_ratio: float | None,
    market_timing_observed: bool,
    formal_two_slot_observed: bool,
) -> bool:
    local = captured_at.astimezone(SHANGHAI)
    current_time = local.time().replace(tzinfo=None)
    horizon_time = (local + timedelta(seconds=60)).time().replace(tzinfo=None)
    complete_horizon = any(
        start <= current_time and horizon_time <= end for start, end in ENTRY_WINDOWS
    )
    return bool(
        formal_two_slot_observed
        and previous_gap_seconds is not None
        and 0.0 < previous_gap_seconds <= 20.0
        and quote_coverage_ratio is not None
        and quote_coverage_ratio >= 0.90
        and market_timing_observed
        and complete_horizon
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _canonical_value(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fingerprinted datetimes must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("fingerprinted numbers must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"value is not JSON serializable: {type(value).__name__}")


def _equivalent(left: object, right: object) -> bool:
    return _canonical_value(left) == _canonical_value(right)
