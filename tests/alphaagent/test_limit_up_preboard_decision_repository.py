from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import preboard_decision_repository as repo
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardExecutionMode,
    PreboardPolicyThresholds,
)


class _Result:
    rowcount = 1


class _Session:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement):
        self.statements.append(statement)
        return _Result()


def _patch_session(monkeypatch, session: _Session) -> None:
    @contextmanager
    def scope():
        yield session

    monkeypatch.setattr(repo, "get_engine", lambda: object())
    monkeypatch.setattr(repo.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(repo, "session_scope", scope)


def _row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "decision_version": PREBOARD_DECISION_VERSION,
        "frame_id": 101,
        "vt_symbol": "600001.SSE",
        "trade_date": date(2026, 7, 21),
        "decision_at": datetime(2026, 7, 21, 10, 5),
        "known_at": datetime(2026, 7, 21, 10, 5),
        "name": "板前样本",
        "last_price": 10.6,
        "limit_price": 11.0,
        "quality_gate_passed": True,
        "feature_status": "scoreable",
        "feature_fingerprint": "sha256:" + "a" * 64,
        "feature_values": {"gain_pct": 6.0},
        "source_quality": "sampled_quote_proxy",
        "label_status": "pending",
    }
    values.update(overrides)
    return values


def test_current_schema_has_shared_decision_columns() -> None:
    features = schema.limit_up_preboard_point_feature_rows
    models = schema.limit_up_preboard_point_model_versions
    actions = schema.limit_up_preboard_point_actions

    assert {
        "decision_payload",
        "feature_status",
        "formal_touch_within_3m",
        "eventual_formal_touch",
        "source_quality",
    }.issubset(features.c.keys())
    assert {
        "decision_version",
        "feature_fingerprint",
        "probability_qualification_status",
        "historical_promotion_status",
        "policy_thresholds",
    }.issubset(models.c.keys())
    assert {
        "execution_mode",
        "decision_state",
        "touch_probability_3m",
        "eventual_touch_probability",
        "expected_d1_net_return_pct",
        "d1_win_probability",
        "seal_probability_given_touch",
    }.issubset(actions.c.keys())


def test_save_feature_rows_writes_only_shared_payload(monkeypatch) -> None:
    session = _Session()
    _patch_session(monkeypatch, session)

    written = repo.save_decision_feature_rows([_row()])

    assert written == 1
    statement = session.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.startswith("INSERT INTO limit_up_preboard_point_feature_rows")
    values = statement.compile(dialect=postgresql.dialect()).params
    assert values["contract_version_m0"] == PREBOARD_DECISION_VERSION
    assert values["frame_features_m0"] == {}
    assert values["identity_features_m0"] == {}
    assert values["feature_status_m0"] == "scoreable"
    assert values["decision_payload_m0"]["feature_values"] == {"gain_pct": 6.0}


def test_save_feature_rows_rejects_inactive_or_unfingerprinted_rows() -> None:
    with pytest.raises(ValueError, match="inactive preboard decision version"):
        repo.save_decision_feature_rows([_row(decision_version="obsolete-contract")])
    with pytest.raises(ValueError, match="scoreable row requires feature fingerprint"):
        repo.save_decision_feature_rows([_row(feature_fingerprint=None)])


def test_research_observations_never_create_action_rows() -> None:
    thresholds = PreboardPolicyThresholds(
        minimum_touch_probability_3m=0.6,
        minimum_eventual_touch_probability=0.7,
        calibrated_dates=(date(2026, 7, 20),),
        fingerprint="sha256:" + "b" * 64,
    )

    written = repo.save_decision_actions(
        [
            _row(
                decision_state="observe",
                execution_mode="research_only",
                touch_probability_3m=0.9,
                eventual_touch_probability=0.95,
            )
        ],
        thresholds=thresholds,
    )

    assert written == 0


def test_active_model_query_requires_both_current_contract_fields(monkeypatch) -> None:
    class _Rows:
        def mappings(self):
            return self

        def all(self):
            return []

    class _ReadSession:
        def __init__(self) -> None:
            self.statement = None

        def execute(self, statement):
            self.statement = statement
            return _Rows()

    session = _ReadSession()
    _patch_session(monkeypatch, session)

    assert repo.load_active_decision_runtime() is None
    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert PREBOARD_DECISION_VERSION in compiled.params.values()
    assert "decision_version" in str(compiled)
    assert "contract_version" in str(compiled)


def test_historically_rejected_qualified_model_loads_for_research_only(
    monkeypatch,
) -> None:
    fingerprint = "sha256:" + "d" * 64
    bundle = SimpleNamespace(
        feature_version=PREBOARD_DECISION_VERSION,
        model_version=PREBOARD_DECISION_VERSION,
        fingerprint=fingerprint,
        feature_names=("gain_pct",),
    )
    row = {
        "probability_qualification_status": "ready",
        "historical_promotion_status": "historical_rejected",
        "model_artifact": {"format": "test"},
        "model_fingerprint": fingerprint,
        "feature_fingerprint": repo._sha256(["gain_pct"]),
        "policy_thresholds": {},
    }

    class _Rows:
        def mappings(self):
            return self

        def all(self):
            return [row]

    class _ReadSession:
        def execute(self, _statement):
            return _Rows()

    _patch_session(monkeypatch, _ReadSession())
    monkeypatch.setattr(
        repo,
        "deserialize_preboard_model_bundle",
        lambda _artifact: bundle,
    )
    monkeypatch.delenv("ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT", raising=False)

    runtime = repo.load_active_decision_runtime()

    assert runtime is not None
    assert runtime["model_bundle"] is bundle
    assert runtime["thresholds"] is None
    assert runtime["execution_mode"] is PreboardExecutionMode.RESEARCH_ONLY
    assert runtime["historical_promotion_status"] == "historical_rejected"
    assert runtime["formal_activation_status"] == "not_eligible"


def test_formal_runtime_requires_exact_configured_model_fingerprint(
    monkeypatch,
) -> None:
    fingerprint = "sha256:" + "e" * 64
    bundle = SimpleNamespace(
        feature_version=PREBOARD_DECISION_VERSION,
        model_version=PREBOARD_DECISION_VERSION,
        fingerprint=fingerprint,
        feature_names=("gain_pct",),
    )
    row = {
        "probability_qualification_status": "ready",
        "historical_promotion_status": "forward_pass_for_formal",
        "model_artifact": {"format": "test"},
        "model_fingerprint": fingerprint,
        "feature_fingerprint": repo._sha256(["gain_pct"]),
        "policy_thresholds": {
            "minimum_touch_probability_3m": 0.6,
            "minimum_eventual_touch_probability": 0.7,
            "calibrated_dates": ["2026-07-20"],
            "fingerprint": "sha256:" + "f" * 64,
        },
    }

    class _Rows:
        def mappings(self):
            return self

        def all(self):
            return [row]

    class _ReadSession:
        def execute(self, _statement):
            return _Rows()

    _patch_session(monkeypatch, _ReadSession())
    monkeypatch.setattr(
        repo,
        "deserialize_preboard_model_bundle",
        lambda _artifact: bundle,
    )
    monkeypatch.setenv(
        "ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT",
        "sha256:" + "0" * 64,
    )
    shadow = repo.load_active_decision_runtime()
    monkeypatch.setenv(
        "ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT",
        fingerprint,
    )
    formal = repo.load_active_decision_runtime()

    assert shadow is not None
    assert shadow["execution_mode"] is PreboardExecutionMode.SHADOW
    assert shadow["formal_activation_status"] == "fingerprint_mismatch"
    assert formal is not None
    assert formal["execution_mode"] is PreboardExecutionMode.FORMAL
    assert formal["formal_activation_status"] == "enabled"
