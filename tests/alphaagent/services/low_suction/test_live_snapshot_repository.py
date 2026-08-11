"""Tests for the one-row low-suction live recommendation snapshot."""

from contextlib import contextmanager

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import live_snapshot_repository


def test_live_snapshot_table_is_registered() -> None:
    assert "low_suction_live_snapshots" in schema.metadata.tables


def test_storage_payload_excludes_scanner_fields_and_diagnostics() -> None:
    stored = live_snapshot_repository._storage_payload(
        {
            "status": "ok",
            "score_version": "current",
            "scan_trace": [{"id": 1}],
            "_scan_spot_active_symbols": 5_001,
        }
    )

    assert stored == {"status": "ok", "score_version": "current"}


def test_load_snapshot_rejects_a_stale_score_version(monkeypatch) -> None:
    class Result:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "score_version": "old-score",
                "payload": {"score_version": "old-score", "status": "ok"},
            }

    class Session:
        def execute(self, _statement):
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(live_snapshot_repository, "get_engine", lambda: object())
    monkeypatch.setattr(live_snapshot_repository, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        live_snapshot_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )

    assert live_snapshot_repository.load_live_snapshot("current-score") is None
