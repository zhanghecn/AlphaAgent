from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import forward_membership_repository
from alphaagent.server.services.low_suction.forward_membership import (
    ForwardMembershipCapture,
    build_forward_membership_capture,
)

SOURCE_DATE = date(2026, 7, 16)
OBSERVED_AT = datetime(2026, 7, 16, 19, 8, tzinfo=ZoneInfo("Asia/Shanghai"))


def _complete_capture() -> ForwardMembershipCapture:
    return build_forward_membership_capture(
        sectors=[{"id": "BK9000", "name": "测试题材", "type": "theme"}],
        members_by_sector={
            "BK9000": [
                {
                    "vt_symbol": "600000.SSE",
                    "source": "eastmoney.push2.board",
                }
            ]
        },
        failed_sector_ids=(),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )


def _partial_capture() -> ForwardMembershipCapture:
    return build_forward_membership_capture(
        sectors=[{"id": "BK9000", "name": "测试题材", "type": "theme"}],
        members_by_sector={},
        failed_sector_ids=("BK9000",),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )


class FakeSession:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[object, object | None]] = []
        self.fail_on_call = fail_on_call

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("insert failed")
        return None


def _patch_session(monkeypatch, session: FakeSession) -> None:
    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(
        forward_membership_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )
    monkeypatch.setattr(
        forward_membership_repository,
        "get_engine",
        lambda: object(),
    )
    monkeypatch.setattr(
        forward_membership_repository,
        "session_scope",
        fake_session_scope,
    )


def _compiled(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_forward_membership_tables_are_low_suction_owned() -> None:
    rows = schema.low_suction_forward_membership_snapshots
    scopes = schema.low_suction_forward_membership_snapshot_scopes

    assert [column.name for column in rows.primary_key.columns] == [
        "source_trade_date",
        "sector_id",
        "vt_symbol",
        "source",
    ]
    assert [column.name for column in scopes.primary_key.columns] == [
        "source_trade_date",
        "scope_type",
        "source",
    ]
    assert not rows.foreign_keys
    assert not scopes.foreign_keys
    assert {
        "observed_at",
        "sector_name",
        "sector_type",
        "manifest_class",
        "evidence_level",
        "raw",
    }.issubset(rows.c.keys())
    assert {
        "observed_at",
        "expected_sector_count",
        "returned_sector_count",
        "complete",
        "evidence_level",
        "manifest_version",
        "raw",
    }.issubset(scopes.c.keys())


def test_complete_capture_replaces_rows_and_both_scopes_in_one_transaction(
    monkeypatch,
) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    written = forward_membership_repository.save_forward_membership_capture(
        _complete_capture()
    )

    assert written == 1
    assert len(session.calls) == 4
    assert _compiled(session.calls[0][0]).startswith(
        "DELETE FROM low_suction_forward_membership_snapshots"
    )
    assert _compiled(session.calls[1][0]).startswith(
        "DELETE FROM low_suction_forward_membership_snapshot_scopes"
    )
    assert _compiled(session.calls[2][0]).startswith(
        "INSERT INTO low_suction_forward_membership_snapshots"
    )
    assert _compiled(session.calls[3][0]).startswith(
        "INSERT INTO low_suction_forward_membership_snapshot_scopes"
    )
    assert len(session.calls[2][1]) == 1
    assert len(session.calls[3][1]) == 2
    assert {
        row["scope_type"] for row in session.calls[3][1]
    } == {"concept_catalog", "concept_tradable"}


def test_partial_retry_updates_only_catalog_and_preserves_existing_strict_scope(
    monkeypatch,
) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    written = forward_membership_repository.save_forward_membership_capture(
        _partial_capture()
    )

    assert written == 0
    assert len(session.calls) == 2
    delete_sql = _compiled(session.calls[0][0])
    assert delete_sql.startswith(
        "DELETE FROM low_suction_forward_membership_snapshot_scopes"
    )
    assert "scope_type = 'concept_catalog'" in delete_sql
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO low_suction_forward_membership_snapshot_scopes"
    )
    assert [row["scope_type"] for row in session.calls[1][1]] == [
        "concept_catalog"
    ]


def test_insert_failure_escapes_the_single_transaction(monkeypatch) -> None:
    session = FakeSession(fail_on_call=4)
    _patch_session(monkeypatch, session)

    with pytest.raises(RuntimeError, match="insert failed"):
        forward_membership_repository.save_forward_membership_capture(
            _complete_capture()
        )

    assert len(session.calls) == 4


def test_repository_rejects_tampered_complete_counts(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)
    capture = _complete_capture()
    tampered = replace(
        capture,
        tradable_scope=replace(capture.tradable_scope, row_count=2),
    )

    with pytest.raises(ValueError, match="row count"):
        forward_membership_repository.save_forward_membership_capture(tampered)

    assert session.calls == []
