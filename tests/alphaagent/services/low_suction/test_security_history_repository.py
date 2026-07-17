from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import security_history_repository
from alphaagent.server.services.low_suction.historical_inputs import (
    HistoricalSecurityBatch,
    HistoricalSecurityRecord,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _record(
    vt_symbol: str = "600001.SSE",
    *,
    evidence_level: str = "reconstructed",
) -> HistoricalSecurityRecord:
    symbol, exchange = vt_symbol.split(".")
    return HistoricalSecurityRecord.from_mapping(
        {
            "vt_symbol": vt_symbol,
            "symbol": symbol,
            "exchange": exchange,
            "name": "历史证券",
            "status": "LISTED",
            "board": "main",
            "listed_on": date(1998, 1, 1),
            "delisted_on": None,
            "valid_from": date(2026, 7, 1),
            "valid_to": date(2026, 7, 2),
            "suspended": False,
            "risk_warning": False,
            "known_at": datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
            "evidence_level": evidence_level,
            "source": "baostock",
            "source_record_id": f"baostock:{vt_symbol}:2026-07-01",
        }
    )


def _batch() -> HistoricalSecurityBatch:
    return HistoricalSecurityBatch(
        records=(_record(),),
        required_pairs=((date(2026, 7, 1), "600001.SSE"),),
        source="baostock",
        evidence_level="reconstructed",
    )


class _FakeSession:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[object, object | None]] = []
        self.fail_on_call = fail_on_call

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("insert failed")
        return None


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_security_history_table_does_not_reference_current_stocks() -> None:
    table = schema.low_suction_security_history
    scope_table = schema.low_suction_security_history_scopes

    assert table.name == "low_suction_security_history"
    assert not table.foreign_keys
    assert not scope_table.foreign_keys
    assert table.c.evidence_level.nullable is False
    assert table.c.source_record_id.nullable is False
    constraint_names = {constraint.name for constraint in table.constraints}
    assert "uq_low_suction_security_source_record" in constraint_names
    scope_constraint_names = {
        constraint.name for constraint in scope_table.constraints
    }
    assert "uq_low_suction_security_scope_pair" in scope_constraint_names


def test_replace_deletes_provider_symbol_scope_then_bulk_inserts(monkeypatch) -> None:
    fake_session = _FakeSession()

    @contextmanager
    def fake_session_scope():
        yield fake_session

    monkeypatch.setattr(
        security_history_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )
    monkeypatch.setattr(
        security_history_repository,
        "get_engine",
        lambda: object(),
    )
    monkeypatch.setattr(
        security_history_repository,
        "session_scope",
        fake_session_scope,
    )

    written = security_history_repository.replace_security_history(_batch())

    assert written == 1
    assert len(fake_session.calls) == 4
    history_delete_sql = _compiled(fake_session.calls[0][0])
    scope_delete_sql = _compiled(fake_session.calls[1][0])
    history_insert_sql = _compiled(fake_session.calls[2][0])
    scope_insert_sql = _compiled(fake_session.calls[3][0])
    assert history_delete_sql.startswith("DELETE FROM low_suction_security_history")
    assert "source = 'baostock'" in history_delete_sql
    assert "vt_symbol IN ('600001.SSE')" in history_delete_sql
    assert scope_delete_sql.startswith(
        "DELETE FROM low_suction_security_history_scopes"
    )
    assert history_insert_sql.startswith("INSERT INTO low_suction_security_history")
    assert scope_insert_sql.startswith(
        "INSERT INTO low_suction_security_history_scopes"
    )
    assert fake_session.calls[2][1] == [
        {
            "vt_symbol": "600001.SSE",
            "symbol": "600001",
            "exchange": "SSE",
            "name": "历史证券",
            "status": "LISTED",
            "board": "main",
            "listed_on": date(1998, 1, 1),
            "delisted_on": None,
            "valid_from": date(2026, 7, 1),
            "valid_to": date(2026, 7, 2),
            "suspended": False,
            "risk_warning": False,
            "known_at": datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
            "evidence_level": "reconstructed",
            "source": "baostock",
            "source_record_id": "baostock:600001.SSE:2026-07-01",
        }
    ]
    assert fake_session.calls[3][1] == [
        {
            "trade_date": date(2026, 7, 1),
            "vt_symbol": "600001.SSE",
            "evidence_level": "reconstructed",
            "source": "baostock",
        }
    ]


def test_insert_failure_escapes_the_transaction_scope(monkeypatch) -> None:
    fake_session = _FakeSession(fail_on_call=3)

    @contextmanager
    def fake_session_scope():
        yield fake_session

    monkeypatch.setattr(
        security_history_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )
    monkeypatch.setattr(
        security_history_repository,
        "get_engine",
        lambda: object(),
    )
    monkeypatch.setattr(
        security_history_repository,
        "session_scope",
        fake_session_scope,
    )

    with pytest.raises(RuntimeError, match="insert failed"):
        security_history_repository.replace_security_history(_batch())

    assert len(fake_session.calls) == 3


def test_replace_rejects_records_outside_declared_symbol_scope() -> None:
    batch = HistoricalSecurityBatch(
        records=(_record("600002.SSE"),),
        required_pairs=((date(2026, 7, 1), "600001.SSE"),),
        source="baostock",
        evidence_level="reconstructed",
    )

    with pytest.raises(ValueError, match="outside declared symbol scope"):
        security_history_repository.replace_security_history(batch)
