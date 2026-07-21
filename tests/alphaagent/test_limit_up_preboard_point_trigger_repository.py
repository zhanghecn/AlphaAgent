from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    PointTriggerDayAudit,
)
from alphaagent.server.services.limit_up import (
    preboard_point_trigger_repository as repo,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_settlement import (
    build_point_trigger_settlement_evidence,
    point_trigger_settlement_evidence_fingerprint,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
CAPTURED_AT = datetime(2026, 7, 21, 10, 15, tzinfo=SHANGHAI)
TRADE_DATE = CAPTURED_AT.date()
FIT_DATES = tuple(TRADE_DATE + timedelta(days=index) for index in range(40))
CALIBRATION_DATES = tuple(
    FIT_DATES[-1] + timedelta(days=index + 1) for index in range(15)
)
MODEL_FINGERPRINT = "sha256:" + "a" * 64
TRAINING_FINGERPRINT = "sha256:" + "b" * 64
RUNTIME_FINGERPRINT = "sha256:" + "d" * 64


def _formal_order() -> dict[str, object]:
    return {
        "vt_symbol": "000001.SZSE",
        "name": "Ping An Bank",
        "lane": "first_board",
        "entry_date": TRADE_DATE.isoformat(),
        "signal_date": TRADE_DATE.isoformat(),
        "buy_time": "10:15:30",
        "entry_price": 11.0,
        "limit_price": 11.0,
        "rank_score": 80.0,
        "pool_rank": 1,
        "source_frame_id": 102,
        "source_captured_at": CAPTURED_AT.replace(second=30).isoformat(),
        "source": "saved_live_formal_portfolio",
    }


def _audit(
    *,
    complete: bool = True,
    trade_date: date = TRADE_DATE,
) -> PointTriggerDayAudit:
    return PointTriggerDayAudit(
        contract_version=CONTRACT_VERSION,
        trade_date=trade_date,
        status="complete" if complete else "incomplete",
        is_complete=complete,
        eligible_for_model=complete,
        reason_codes=() if complete else ("scan_interval_p90_above_20s",),
        frame_count=720,
        observation_count=20_000,
        metrics={"scan_interval_p90_seconds": 15.0 if complete else 30.0},
        capture_runtime_fingerprint=RUNTIME_FINGERPRINT,
        formal_baseline_order_projection_complete=True,
        formal_baseline_orders=(_formal_order(),),
    )


def _feature_row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "frame_id": 101,
        "trade_date": TRADE_DATE,
        "captured_at": CAPTURED_AT,
        "vt_symbol": "000001.SZSE",
        "name": "Ping An Bank",
        "last_price": 10.50,
        "limit_price": 11.00,
        "quote_observed_at": CAPTURED_AT,
        "action_frame_eligible": True,
        "action_previous_frame_gap_seconds": 15.0,
        "action_quote_coverage_ratio": 1.0,
        "action_market_timing_observed": True,
        "formal_two_slot_observed": True,
        "formal_two_slot_symbols": ["000001.SZSE"],
        "frame_features": {field: 0.0 for field in FRAME_FEATURE_FIELDS},
        "identity_features": {field: 0.0 for field in IDENTITY_FEATURE_FIELDS},
        "feature_fingerprint": "sha256:" + "c" * 64,
        "label_status": "known",
        "formal_event_within_60s": True,
        "formal_identity_within_60s": True,
        "formal_identity_vt_symbol": "000001.SZSE",
        "formal_event_at": CAPTURED_AT.replace(second=30),
    }
    values.update(overrides)
    return values


def _model(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "model_fingerprint": MODEL_FINGERPRINT,
        "contract_version": CONTRACT_VERSION,
        "status": "active",
        "fit_trade_dates": list(FIT_DATES),
        "calibration_trade_dates": list(CALIBRATION_DATES),
        "validation_trade_dates": [],
        "event_model_params": {"objective": "binary"},
        "identity_model_params": {"objective": "lambdarank"},
        "action_model_params": {"max_iter": 2000},
        "frame_feature_fields": list(FRAME_FEATURE_FIELDS),
        "identity_feature_fields": list(IDENTITY_FEATURE_FIELDS),
        "action_feature_fields": ["event_probability", "identity_score"],
        "training_input_fingerprint": TRAINING_FINGERPRINT,
        "event_model_fingerprint": "sha256:" + "d" * 64,
        "identity_model_fingerprint": "sha256:" + "e" * 64,
        "action_model_fingerprint": "sha256:" + "f" * 64,
        "calibration_threshold": 0.70,
        "calibration_metrics": {"action_count": 20, "precision": 0.70},
        "model_artifact": {"format": "test", "payload": {}},
        "frozen_at": datetime.combine(
            CALIBRATION_DATES[-1],
            datetime.min.time().replace(hour=21, minute=30),
            tzinfo=SHANGHAI,
        ),
    }
    values.update(overrides)
    return values


def _action(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "model_fingerprint": MODEL_FINGERPRINT,
        "contract_version": CONTRACT_VERSION,
        "captured_at": CAPTURED_AT,
        "trade_date": TRADE_DATE,
        "daily_slot": 1,
        "frame_id": 101,
        "vt_symbol": "000001.SZSE",
        "quote_observed_at": CAPTURED_AT,
        "last_price": 10.50,
        "limit_price": 11.00,
        "action_probability": 0.82,
        "action_threshold": 0.70,
        "event_probability": 0.88,
        "identity_score": 1.25,
        "top1_margin": 0.30,
        "candidate_count": 1,
        "input_fingerprint": "sha256:" + "1" * 64,
        "decision_payload": {
            "eligible_candidate_symbols": ["000001.SZSE"],
            "concurrent_formal_two_slot_symbols": ["000001.SZSE"],
            "concurrent_formal_two_slot_observed": True,
            "event_model_fingerprint": "sha256:event",
            "identity_model_fingerprint": "sha256:identity",
            "action_model_fingerprint": "sha256:action",
        },
        "actionable": False,
        "execution_effect": "none_research_only",
        "action_kind": "research_action",
    }
    values.update(overrides)
    return values


def _settlement_evidence() -> dict[str, object]:
    return build_point_trigger_settlement_evidence(
        _action(),
        [
            {
                "id": 102,
                "trade_date": TRADE_DATE,
                "captured_at": CAPTURED_AT.replace(second=30),
            }
        ],
        [
            {
                "frame_id": 102,
                "captured_at": CAPTURED_AT.replace(second=30),
                "quote_observed_at": CAPTURED_AT.replace(second=29),
                "vt_symbol": "000001.SZSE",
                "last_price": 10.60,
                "capture_state": "rising",
            }
        ],
    )


def _settlement_evidence_fields() -> dict[str, object]:
    evidence = _settlement_evidence()
    return {
        "settlement_evidence": evidence,
        "settlement_evidence_fingerprint": (
            point_trigger_settlement_evidence_fingerprint(evidence)
        ),
    }


class FakeResult:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, results: list[FakeResult] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[object, object | None]] = []

    def execute(self, statement, parameters=None) -> FakeResult:
        self.calls.append((statement, parameters))
        return self.results.pop(0) if self.results else FakeResult()


def _patch_session(monkeypatch, session: FakeSession) -> None:
    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(repo.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(repo, "get_engine", lambda: object())
    monkeypatch.setattr(repo, "session_scope", fake_session_scope)


def _compiled(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_point_trigger_tables_have_frozen_identities_without_radar_foreign_keys() -> (
    None
):
    scopes = schema.limit_up_preboard_point_day_scopes
    features = schema.limit_up_preboard_point_feature_rows
    models = schema.limit_up_preboard_point_model_versions
    actions = schema.limit_up_preboard_point_actions

    assert [column.name for column in scopes.primary_key.columns] == [
        "contract_version",
        "trade_date",
    ]
    assert [column.name for column in features.primary_key.columns] == [
        "contract_version",
        "frame_id",
        "vt_symbol",
    ]
    assert list(features.foreign_keys) == []
    assert [column.name for column in models.primary_key.columns] == [
        "model_fingerprint"
    ]
    assert any(
        isinstance(constraint, schema.UniqueConstraint)
        and [column.name for column in constraint.columns] == ["contract_version"]
        for constraint in models.constraints
    )
    assert [column.name for column in actions.primary_key.columns] == [
        "model_fingerprint",
        "captured_at",
        "vt_symbol",
    ]
    action_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in actions.constraints
        if isinstance(constraint, schema.UniqueConstraint)
    }
    assert ("model_fingerprint", "trade_date", "daily_slot") in action_unique_columns
    assert ("model_fingerprint", "trade_date", "vt_symbol") in action_unique_columns
    assert {
        "cohort_fingerprint",
        "input_fingerprint",
        "audit_metrics",
        "feature_row_count",
        "formal_baseline_order_projection_complete",
        "formal_baseline_order_count",
        "formal_baseline_orders",
        "formal_baseline_orders_fingerprint",
        "frozen_at",
    }.issubset(scopes.c.keys())
    assert {
        "frame_features",
        "identity_features",
        "label_status",
        "formal_identity_within_60s",
        "action_frame_eligible",
        "action_previous_frame_gap_seconds",
        "action_quote_coverage_ratio",
        "action_market_timing_observed",
        "formal_two_slot_observed",
        "formal_two_slot_symbols",
    }.issubset(features.c.keys())
    assert {
        "fit_trade_dates",
        "calibration_trade_dates",
        "validation_trade_dates",
        "frame_feature_fields",
        "identity_feature_fields",
        "training_input_fingerprint",
        "calibration_threshold",
        "frozen_at",
    }.issubset(models.c.keys())
    assert {
        "decision_fingerprint",
        "daily_slot",
        "actionable",
        "execution_effect",
        "fill_status",
        "formal_identity_status",
        "physical_touch_status",
        "d1_status",
        "settlement_evidence",
        "settlement_evidence_fingerprint",
    }.issubset(actions.c.keys())


def test_complete_day_rejects_nonfinite_or_missing_model_features() -> None:
    missing = _feature_row()
    missing["identity_features"][IDENTITY_FEATURE_FIELDS[0]] = None
    nonfinite = _feature_row()
    nonfinite["frame_features"][FRAME_FEATURE_FIELDS[0]] = float("nan")

    with pytest.raises(ValueError, match="identity_features.*required"):
        repo.freeze_point_trigger_day(_audit(), [missing])
    with pytest.raises(ValueError, match="frame_features.*finite"):
        repo.freeze_point_trigger_day(_audit(), [nonfinite])


def test_feature_row_rejects_forged_action_eligibility_or_missing_two_slot() -> None:
    forged = _feature_row(action_frame_eligible=False)
    missing_market_timing = _feature_row(action_market_timing_observed=False)
    missing_two_slot = _feature_row(
        formal_two_slot_observed=False,
        formal_two_slot_symbols=[],
        action_frame_eligible=False,
    )

    with pytest.raises(ValueError, match="does not match its frozen inputs"):
        repo.freeze_point_trigger_day(_audit(), [forged])
    with pytest.raises(ValueError, match="does not match its frozen inputs"):
        repo._validated_feature_row(
            missing_market_timing,
            repo._validated_audit(_audit()),
        )
    with pytest.raises(ValueError, match="require formal two-slot evidence"):
        repo.freeze_point_trigger_day(_audit(), [missing_two_slot])


def test_shakedown_day_is_rejected_before_immutable_scope_write(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError, match="eligible_after"):
        repo.freeze_point_trigger_day(
            _audit(trade_date=ELIGIBLE_AFTER),
            [],
        )

    assert session.calls == []


def test_incomplete_day_freezes_only_audit_scope(monkeypatch) -> None:
    session = FakeSession([FakeResult()])
    _patch_session(monkeypatch, session)

    result = repo.freeze_point_trigger_day(_audit(complete=False), [_feature_row()])

    assert result["status"] == "frozen_incomplete"
    assert result["rows_written"] == 0
    assert len(session.calls) == 2
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO limit_up_preboard_point_day_scopes"
    )
    assert all(
        "limit_up_preboard_point_feature_rows" not in _compiled(statement)
        for statement, _ in session.calls
    )


def test_complete_day_feature_cohort_is_atomic_and_idempotent(monkeypatch) -> None:
    first_session = FakeSession([FakeResult()])
    _patch_session(monkeypatch, first_session)

    first = repo.freeze_point_trigger_day(_audit(), [_feature_row()])

    assert first["status"] == "frozen"
    assert first["rows_written"] == 1
    assert len(first_session.calls) == 3
    assert _compiled(first_session.calls[1][0]).startswith(
        "INSERT INTO limit_up_preboard_point_feature_rows"
    )
    assert _compiled(first_session.calls[2][0]).startswith(
        "INSERT INTO limit_up_preboard_point_day_scopes"
    )
    scope_params = first_session.calls[2][0].compile().params
    assert scope_params["formal_baseline_order_projection_complete"] is True
    assert scope_params["formal_baseline_order_count"] == 1
    assert scope_params["formal_baseline_orders"] == [_formal_order()]

    same_session = FakeSession(
        [FakeResult([{"cohort_fingerprint": first["cohort_fingerprint"]}])]
    )
    _patch_session(monkeypatch, same_session)
    same = repo.freeze_point_trigger_day(_audit(), [_feature_row()])

    assert same["status"] == "already_frozen"
    assert same["rows_written"] == 0
    assert len(same_session.calls) == 1


def test_formal_baseline_order_changes_day_cohort_fingerprint() -> None:
    audit = _audit()
    changed = _audit()
    changed_order = {**_formal_order(), "vt_symbol": "600001.SSE"}
    changed = PointTriggerDayAudit(
        **{
            **changed.__dict__,
            "formal_baseline_orders": (changed_order,),
        }
    )

    assert repo.point_trigger_day_cohort_fingerprint(
        audit, [_feature_row()]
    ) != repo.point_trigger_day_cohort_fingerprint(changed, [_feature_row()])


def test_capture_runtime_changes_day_cohort_fingerprint() -> None:
    audit = _audit()
    changed = PointTriggerDayAudit(
        **{
            **audit.__dict__,
            "capture_runtime_fingerprint": "sha256:" + "e" * 64,
        }
    )

    assert repo.point_trigger_day_cohort_fingerprint(
        audit, [_feature_row()]
    ) != repo.point_trigger_day_cohort_fingerprint(changed, [_feature_row()])


def test_changed_frozen_day_raises_scope_conflict(monkeypatch) -> None:
    session = FakeSession([FakeResult([{"cohort_fingerprint": "sha256:" + "9" * 64}])])
    _patch_session(monkeypatch, session)

    with pytest.raises(repo.PointTriggerScopeConflict):
        repo.freeze_point_trigger_day(_audit(), [_feature_row(last_price=10.60)])

    assert len(session.calls) == 1


def test_model_version_is_saved_once_with_frozen_contract(monkeypatch) -> None:
    first_session = FakeSession([FakeResult()])
    _patch_session(monkeypatch, first_session)
    first = repo.save_point_trigger_model(_model())

    assert first["status"] == "frozen"
    assert len(first_session.calls) == 2
    assert _compiled(first_session.calls[1][0]).startswith(
        "INSERT INTO limit_up_preboard_point_model_versions"
    )

    same_session = FakeSession(
        [FakeResult([{"record_fingerprint": first["record_fingerprint"]}])]
    )
    _patch_session(monkeypatch, same_session)
    assert repo.save_point_trigger_model(_model())["status"] == "already_frozen"
    assert len(same_session.calls) == 1

    conflict_session = FakeSession(
        [FakeResult([{"record_fingerprint": "sha256:" + "8" * 64}])]
    )
    _patch_session(monkeypatch, conflict_session)
    with pytest.raises(repo.PointTriggerModelConflict):
        repo.save_point_trigger_model(_model(calibration_threshold=0.75))


@pytest.mark.parametrize(
    "overrides",
    [
        {"fit_trade_dates": list(FIT_DATES[:-1])},
        {"calibration_trade_dates": list(CALIBRATION_DATES[:-1])},
        {"fit_trade_dates": [ELIGIBLE_AFTER, *FIT_DATES[1:]]},
        {"fit_trade_dates": [FIT_DATES[1], FIT_DATES[0], *FIT_DATES[2:]]},
        {"fit_trade_dates": [*FIT_DATES, FIT_DATES[-1]]},
        {
            "frozen_at": datetime.combine(
                CALIBRATION_DATES[-1] - timedelta(days=1),
                datetime.min.time().replace(hour=21, minute=30),
                tzinfo=SHANGHAI,
            )
        },
    ],
)
def test_model_rejects_non_frozen_stage_dates_before_write(
    monkeypatch,
    overrides: dict[str, object],
) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError, match="model date cohorts"):
        repo.save_point_trigger_model(_model(**overrides))

    assert session.calls == []


def test_action_decision_is_immutable_and_research_only(monkeypatch) -> None:
    first_session = FakeSession([FakeResult()])
    _patch_session(monkeypatch, first_session)
    first = repo.save_point_trigger_action(_action())

    assert first["status"] == "saved"
    assert len(first_session.calls) == 2
    statement, _ = first_session.calls[1]
    assert _compiled(statement).startswith(
        "INSERT INTO limit_up_preboard_point_actions"
    )
    parameters = statement.compile().params
    assert parameters["actionable"] is False
    assert parameters["execution_effect"] == "none_research_only"
    assert parameters["fill_status"] == "pending"
    assert parameters["formal_identity_status"] == "pending"
    assert parameters["physical_touch_status"] == "pending"
    assert parameters["d1_status"] == "pending"

    same_session = FakeSession(
        [FakeResult([{"decision_fingerprint": first["decision_fingerprint"]}])]
    )
    _patch_session(monkeypatch, same_session)
    assert repo.save_point_trigger_action(_action())["status"] == "already_saved"
    assert len(same_session.calls) == 1

    conflict_session = FakeSession(
        [FakeResult([{"decision_fingerprint": "sha256:" + "7" * 64}])]
    )
    _patch_session(monkeypatch, conflict_session)
    with pytest.raises(repo.PointTriggerActionConflict):
        repo.save_point_trigger_action(_action(action_probability=0.91))


@pytest.mark.parametrize(
    "overrides",
    [
        {"decision_payload": {}},
        {"trade_date": TRADE_DATE + timedelta(days=1)},
        {"action_probability": 0.69},
        {"daily_slot": 0},
        {"daily_slot": 3},
    ],
)
def test_action_rejects_incomplete_or_inconsistent_frozen_decision(
    monkeypatch,
    overrides: dict[str, object],
) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError):
        repo.save_point_trigger_action(_action(**overrides))

    assert session.calls == []


@pytest.mark.parametrize(
    ("stage", "values", "status_column"),
    [
        (
            "delayed_fill",
            {
                "fill_status": "filled",
                "fill_at": CAPTURED_AT.replace(second=30),
                "fill_price": 10.60,
                "fill_quote_observed_at": CAPTURED_AT.replace(second=29),
                **_settlement_evidence_fields(),
            },
            "fill_status",
        ),
        (
            "formal_identity",
            {
                "formal_identity_status": "matched",
                "formal_event_at": CAPTURED_AT.replace(second=30),
                "formal_identity_vt_symbol": "000001.SZSE",
                "formal_identity_matched": True,
                "original_two_slot_symbols": ["000001.SZSE", "600000.SSE"],
                "original_two_slot_matched": True,
            },
            "formal_identity_status",
        ),
        (
            "physical_touch",
            {
                "physical_touch_status": "touched",
                "physical_touch_at": CAPTURED_AT.replace(second=35),
                "final_sealed": True,
            },
            "physical_touch_status",
        ),
        (
            "d1_outcome",
            {
                "d1_status": "closed",
                "d1_trade_date": date(2026, 7, 22),
                "d1_close_price": 11.20,
                "gross_return_pct": 5.66,
                "net_return_pct": 5.40,
                "double_cost_net_return_pct": 5.14,
            },
            "d1_status",
        ),
    ],
)
def test_action_outcome_stages_close_only_from_pending(
    monkeypatch,
    stage: str,
    values: dict[str, object],
    status_column: str,
) -> None:
    session = FakeSession([FakeResult(rowcount=1)])
    _patch_session(monkeypatch, session)

    result = repo.close_point_trigger_action_stage(
        MODEL_FINGERPRINT,
        CAPTURED_AT,
        "000001.SZSE",
        stage=stage,
        values=values,
    )

    assert result["status"] == "closed"
    sql = _compiled(session.calls[0][0])
    assert sql.startswith("UPDATE limit_up_preboard_point_actions")
    assert f"limit_up_preboard_point_actions.{status_column} = " in sql
    assert "pending" in session.calls[0][0].compile().params.values()


def test_closed_action_stage_is_idempotent_but_cannot_be_rewritten(monkeypatch) -> None:
    values = {
        "fill_status": "filled",
        "fill_at": CAPTURED_AT.replace(second=30),
        "fill_price": 10.60,
        "fill_quote_observed_at": CAPTURED_AT.replace(second=29),
        **_settlement_evidence_fields(),
    }
    existing = {**values, "fill_closed_at": CAPTURED_AT.replace(minute=20)}
    same_session = FakeSession([FakeResult(rowcount=0), FakeResult([existing])])
    _patch_session(monkeypatch, same_session)

    assert (
        repo.close_point_trigger_action_stage(
            MODEL_FINGERPRINT,
            CAPTURED_AT,
            "000001.SZSE",
            stage="delayed_fill",
            values=values,
        )["status"]
        == "already_closed"
    )

    conflict_session = FakeSession([FakeResult(rowcount=0), FakeResult([existing])])
    _patch_session(monkeypatch, conflict_session)
    with pytest.raises(repo.PointTriggerSettlementConflict):
        repo.close_point_trigger_action_stage(
            MODEL_FINGERPRINT,
            CAPTURED_AT,
            "000001.SZSE",
            stage="delayed_fill",
            values={**values, "fill_price": 10.70},
        )


@pytest.mark.parametrize(
    "values",
    [
        {
            "fill_status": "filled",
            "fill_at": CAPTURED_AT.replace(second=30),
            "fill_price": 10.60,
            "fill_quote_observed_at": CAPTURED_AT.replace(second=29),
        },
        {
            "fill_status": "filled",
            "fill_at": CAPTURED_AT.replace(second=30),
            "fill_price": 10.60,
            "fill_quote_observed_at": CAPTURED_AT.replace(second=29),
            **_settlement_evidence_fields(),
            "settlement_evidence_fingerprint": "sha256:" + "0" * 64,
        },
    ],
)
def test_delayed_fill_rejects_missing_or_tampered_evidence_before_sql(
    monkeypatch,
    values: dict[str, object],
) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError, match="settlement evidence|fingerprint"):
        repo.close_point_trigger_action_stage(
            MODEL_FINGERPRINT,
            CAPTURED_AT,
            "000001.SZSE",
            stage="delayed_fill",
            values=values,
        )

    assert session.calls == []


def test_closure_rejects_decision_fields_before_issuing_sql(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError, match="not allowed"):
        repo.close_point_trigger_action_stage(
            MODEL_FINGERPRINT,
            CAPTURED_AT,
            "000001.SZSE",
            stage="delayed_fill",
            values={"fill_status": "filled", "action_probability": 0.99},
        )

    assert session.calls == []
