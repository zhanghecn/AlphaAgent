from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import membership_history_repository
from alphaagent.server.services.low_suction.historical_inputs import (
    HistoricalMembershipBatch,
    HistoricalMembershipRecord,
    HistoricalMembershipScope,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _record(
    *,
    sector_id: str = "BK1184",
    vt_symbol: str = "600001.SSE",
    source_record_id: str = "member-1",
) -> HistoricalMembershipRecord:
    return HistoricalMembershipRecord.from_mapping(
        {
            "sector_id": sector_id,
            "sector_name": "人形机器人",
            "vt_symbol": vt_symbol,
            "in_date": date(2026, 7, 1),
            "out_date": date(2026, 7, 2),
            "known_at": datetime(2026, 6, 30, 23, 59, tzinfo=SHANGHAI),
            "evidence_level": "strict",
            "source": "tushare.dc_member.lag1",
            "source_record_id": source_record_id,
        }
    )


def _scope(sector_id: str = "BK1184") -> HistoricalMembershipScope:
    return HistoricalMembershipScope.from_mapping(
        {
            "trade_date": date(2026, 7, 1),
            "source_trade_date": date(2026, 6, 30),
            "sector_id": sector_id,
            "expected_member_count": 1,
            "returned_member_count": 1,
            "pagination_complete": True,
            "known_at": datetime(2026, 6, 30, 23, 59, tzinfo=SHANGHAI),
            "evidence_level": "strict",
            "source": "tushare.dc_member.lag1",
            "source_request_id": f"scope:{sector_id}",
        }
    )


def _batch() -> HistoricalMembershipBatch:
    return HistoricalMembershipBatch(
        records=(_record(),),
        scopes=(_scope(),),
        required_pairs=((date(2026, 7, 1), "BK1184"),),
        source="tushare.dc_member.lag1",
        evidence_level="strict",
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


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_membership_tables_are_source_isolated_and_have_no_current_foreign_keys() -> None:
    history = schema.low_suction_concept_membership_history
    scopes = schema.low_suction_concept_membership_scopes

    assert not history.foreign_keys
    assert not scopes.foreign_keys
    assert history.c.evidence_level.nullable is False
    assert scopes.c.source_trade_date.nullable is False
    history_constraints = {constraint.name for constraint in history.constraints}
    scope_constraints = {constraint.name for constraint in scopes.constraints}
    assert "uq_low_suction_membership_source_record" in history_constraints
    assert "uq_low_suction_membership_scope_pair" in scope_constraints
    assert "uq_low_suction_membership_scope_request" in scope_constraints


def test_replace_deletes_only_provider_then_inserts_history_and_scopes(
    monkeypatch,
) -> None:
    session = FakeSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(
        membership_history_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )
    monkeypatch.setattr(membership_history_repository, "get_engine", lambda: object())
    monkeypatch.setattr(
        membership_history_repository,
        "session_scope",
        fake_session_scope,
    )

    written = membership_history_repository.replace_membership_history(_batch())

    assert written == 1
    assert len(session.calls) == 4
    assert _compiled(session.calls[0][0]).startswith(
        "DELETE FROM low_suction_concept_membership_history"
    )
    assert "source = 'tushare.dc_member.lag1'" in _compiled(session.calls[0][0])
    assert _compiled(session.calls[1][0]).startswith(
        "DELETE FROM low_suction_concept_membership_scopes"
    )
    assert _compiled(session.calls[2][0]).startswith(
        "INSERT INTO low_suction_concept_membership_history"
    )
    assert _compiled(session.calls[3][0]).startswith(
        "INSERT INTO low_suction_concept_membership_scopes"
    )
    assert session.calls[2][1] == [
        {
            "sector_id": "BK1184",
            "sector_name": "人形机器人",
            "vt_symbol": "600001.SSE",
            "in_date": date(2026, 7, 1),
            "out_date": date(2026, 7, 2),
            "known_at": datetime(2026, 6, 30, 23, 59, tzinfo=SHANGHAI),
            "evidence_level": "strict",
            "source": "tushare.dc_member.lag1",
            "source_record_id": "member-1",
            "raw": {},
        }
    ]
    assert session.calls[3][1] == [
        {
            "trade_date": date(2026, 7, 1),
            "source_trade_date": date(2026, 6, 30),
            "sector_id": "BK1184",
            "expected_member_count": 1,
            "returned_member_count": 1,
            "pagination_complete": True,
            "known_at": datetime(2026, 6, 30, 23, 59, tzinfo=SHANGHAI),
            "evidence_level": "strict",
            "source": "tushare.dc_member.lag1",
            "source_request_id": "scope:BK1184",
            "raw": {},
        }
    ]


def test_insert_failure_escapes_single_transaction_scope(monkeypatch) -> None:
    session = FakeSession(fail_on_call=3)

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(
        membership_history_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )
    monkeypatch.setattr(membership_history_repository, "get_engine", lambda: object())
    monkeypatch.setattr(
        membership_history_repository,
        "session_scope",
        fake_session_scope,
    )

    with pytest.raises(RuntimeError, match="insert failed"):
        membership_history_repository.replace_membership_history(_batch())

    assert len(session.calls) == 3


def test_replace_rejects_outside_scope_or_duplicate_source_records() -> None:
    outside = HistoricalMembershipBatch(
        records=(_record(sector_id="BK9999"),),
        scopes=(_scope(),),
        required_pairs=((date(2026, 7, 1), "BK1184"),),
        source="tushare.dc_member.lag1",
        evidence_level="strict",
    )
    with pytest.raises(ValueError, match="outside declared sector scope"):
        membership_history_repository.replace_membership_history(outside)

    duplicate = HistoricalMembershipBatch(
        records=(
            _record(vt_symbol="600001.SSE", source_record_id="same"),
            _record(vt_symbol="600002.SSE", source_record_id="same"),
        ),
        scopes=(_scope(),),
        required_pairs=((date(2026, 7, 1), "BK1184"),),
        source="tushare.dc_member.lag1",
        evidence_level="strict",
    )
    with pytest.raises(ValueError, match="source_record_id"):
        membership_history_repository.replace_membership_history(duplicate)
