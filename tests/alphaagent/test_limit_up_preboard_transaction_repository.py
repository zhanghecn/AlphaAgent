from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import preboard_transaction_repository as repo


FEATURE_VERSION = "limit-up-preboard-transaction-flow-v1"
FINGERPRINT = "sha256:" + "a" * 64


def _scope(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "feature_version": FEATURE_VERSION,
        "vt_symbol": "000001.SZSE",
        "trade_date": date(2026, 7, 16),
        "status": "flow_ready",
        "source": "tdx.history_transaction",
        "source_host": {"name": "test"},
        "page_count": 2,
        "raw_row_count": 2_037,
        "trade_row_count": 2_037,
        "pagination_complete": True,
        "first_time": "09:25",
        "last_time": "15:00",
        "volume_matches": True,
        "observed_volume": 10_000.0,
        "expected_volume": 10_000.0,
        "volume_difference": 0.0,
        "close_difference": 0.0,
        "high_difference": 0.01,
        "low_difference": 0.02,
        "price_audit_status": "degraded",
        "input_fingerprint": FINGERPRINT,
        "feature_row_count": 2,
        "raw": {"reasons": []},
    }
    values.update(overrides)
    return values


def _rows(**overrides: object) -> list[dict[str, object]]:
    rows = [
        {
            "feature_version": FEATURE_VERSION,
            "vt_symbol": "000001.SZSE",
            "trade_date": date(2026, 7, 16),
            "bar_time": datetime(2026, 7, 16, 10, minute),
            "input_fingerprint": FINGERPRINT,
            "source": "tdx.history_transaction",
            "values": {"tx_path_efficiency_1m": value},
        }
        for minute, value in ((0, 0.5), (1, 0.6))
    ]
    for row in rows:
        row.update(overrides)
    return rows


def _pair_manifest(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "manifest_version": repo.PAIR_MANIFEST_VERSION,
        "session_count": 89,
        "start_date": date(2026, 3, 9),
        "end_date": date(2026, 7, 16),
        "status": "ready",
        "strategy_filter_version": "limit-up-current-strategy-preboard-replay-v2",
        "feature_version": FEATURE_VERSION,
        "input_fingerprint": FINGERPRINT,
        "manifest_pair_count": 15_921,
        "complete_minute_pair_count": 15_921,
        "static_upper_bound_pair_count": 1_406,
        "shared_pair_count": 2,
        "shared_prefix_count": 12,
        "pairs": [
            {"vt_symbol": "000001.SZSE", "trade_date": "2026-03-09"},
            {"vt_symbol": "600000.SSE", "trade_date": "2026-07-16"},
        ],
        "filter_audit": {"shared_candidate_pair_count": 2},
        "feature_coverage": {"feature_computed_rows": 100},
    }
    values.update(overrides)
    return values


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.calls: list[tuple[object, object | None]] = []

    def execute(self, statement, parameters=None) -> FakeResult:
        self.calls.append((statement, parameters))
        if getattr(statement, "is_select", False):
            return FakeResult(self.existing)
        return FakeResult([])


def _patch_session(monkeypatch, session: FakeSession) -> None:
    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(repo.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(repo, "get_engine", lambda: object())
    monkeypatch.setattr(repo, "session_scope", fake_session_scope)


def _compiled(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
        )
    )


def test_transaction_feature_tables_have_exact_immutable_identity() -> None:
    manifests = schema.limit_up_transaction_pair_manifests
    scopes = schema.limit_up_transaction_feature_scopes
    features = schema.limit_up_transaction_features

    assert [column.name for column in manifests.primary_key.columns] == [
        "manifest_version",
        "session_count",
        "start_date",
        "end_date",
    ]
    assert {
        "strategy_filter_version",
        "feature_version",
        "input_fingerprint",
        "pairs",
        "filter_audit",
    }.issubset(manifests.c.keys())
    assert [column.name for column in scopes.primary_key.columns] == [
        "feature_version",
        "vt_symbol",
        "trade_date",
    ]
    assert [column.name for column in features.primary_key.columns] == [
        "feature_version",
        "vt_symbol",
        "trade_date",
        "bar_time",
    ]
    assert {
        "status",
        "pagination_complete",
        "volume_matches",
        "input_fingerprint",
        "feature_row_count",
        "raw",
    }.issubset(scopes.c.keys())
    assert {"input_fingerprint", "values", "source"}.issubset(features.c.keys())


def test_first_pair_manifest_is_frozen_once(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repo.save_transaction_pair_manifest(_pair_manifest())

    assert result == {
        "status": "frozen",
        "manifest_written": 1,
        "input_fingerprint": FINGERPRINT,
        "shared_pair_count": 2,
    }
    assert len(session.calls) == 2
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO limit_up_transaction_pair_manifests"
    )


def test_pair_manifest_is_idempotent_and_conflicts_fail_closed(monkeypatch) -> None:
    same = FakeSession([{"input_fingerprint": FINGERPRINT}])
    _patch_session(monkeypatch, same)
    assert repo.save_transaction_pair_manifest(_pair_manifest())["status"] == (
        "already_frozen"
    )
    assert len(same.calls) == 1

    conflict = FakeSession(
        [{"input_fingerprint": "sha256:" + "b" * 64}]
    )
    _patch_session(monkeypatch, conflict)
    assert repo.save_transaction_pair_manifest(_pair_manifest())["status"] == (
        "fingerprint_conflict"
    )
    assert len(conflict.calls) == 1


def test_first_ready_capture_is_saved_atomically(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repo.save_transaction_feature_capture(_scope(), _rows())

    assert result == {
        "status": "frozen",
        "rows_written": 2,
        "scope_written": 1,
        "input_fingerprint": FINGERPRINT,
    }
    assert len(session.calls) == 3
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO limit_up_transaction_features"
    )
    assert _compiled(session.calls[2][0]).startswith(
        "INSERT INTO limit_up_transaction_feature_scopes"
    )


def test_identical_ready_capture_is_idempotent(monkeypatch) -> None:
    session = FakeSession(
        [{"status": "flow_ready", "input_fingerprint": FINGERPRINT}]
    )
    _patch_session(monkeypatch, session)

    result = repo.save_transaction_feature_capture(_scope(), _rows())

    assert result["status"] == "already_frozen"
    assert result["rows_written"] == 0
    assert len(session.calls) == 1


def test_ready_capture_fingerprint_conflict_is_not_overwritten(monkeypatch) -> None:
    session = FakeSession(
        [
            {
                "status": "flow_ready",
                "input_fingerprint": "sha256:" + "b" * 64,
            }
        ]
    )
    _patch_session(monkeypatch, session)

    result = repo.save_transaction_feature_capture(_scope(), _rows())

    assert result["status"] == "fingerprint_conflict"
    assert result["rows_written"] == 0
    assert len(session.calls) == 1


def test_invalid_scope_can_be_replaced_by_ready_capture(monkeypatch) -> None:
    session = FakeSession(
        [{"status": "invalid", "input_fingerprint": "sha256:" + "c" * 64}]
    )
    _patch_session(monkeypatch, session)

    result = repo.save_transaction_feature_capture(_scope(), _rows())

    assert result["status"] == "frozen"
    assert sum(getattr(statement, "is_delete", False) for statement, _ in session.calls) == 2


def test_coverage_uses_exact_requested_stock_days() -> None:
    pairs = [
        ("000001.SZSE", date(2026, 7, 16)),
        ("600000.SSE", date(2026, 7, 16)),
    ]
    scopes = [
        _scope(),
        _scope(vt_symbol="002001.SZSE"),
    ]

    coverage = repo.build_transaction_feature_coverage(pairs, scopes)

    assert coverage["requested_pair_count"] == 2
    assert coverage["ready_pair_count"] == 1
    assert coverage["missing_pair_count"] == 1
    assert coverage["ready_pair_pct"] == 50.0
    assert coverage["missing_pairs"] == [
        {"vt_symbol": "600000.SSE", "trade_date": "2026-07-16"}
    ]
    assert coverage["pending_pairs"] == [
        {"vt_symbol": "600000.SSE", "trade_date": "2026-07-16"}
    ]
