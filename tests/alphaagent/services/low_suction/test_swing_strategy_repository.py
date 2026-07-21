from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import swing_strategy_repository as repository
from alphaagent.server.services.low_suction.swing_strategy import (
    SwingSignalCapture,
    build_swing_signal_capture,
)
from tests.alphaagent.services.low_suction.test_swing_strategy import _inputs


def test_formal_strategy_tables_are_independent_and_auditable() -> None:
    runs = schema.low_suction_strategy_runs
    signals = schema.low_suction_strategy_signals
    positions = schema.low_suction_paper_positions
    trades = schema.low_suction_paper_trades

    assert [column.name for column in runs.primary_key.columns] == [
        "strategy_version",
        "trade_date",
        "phase",
    ]
    assert [column.name for column in signals.primary_key.columns] == ["signal_id"]
    assert [column.name for column in positions.primary_key.columns] == ["signal_id"]
    assert [column.name for column in trades.primary_key.columns] == ["signal_id"]
    assert {
        "feature_cutoff_at",
        "reference_peak_price",
        "provisional_ma5",
        "recommendation_state",
        "input_fingerprint",
    }.issubset(signals.c.keys())
    assert {
        "entry_at",
        "entry_price",
        "volume",
        "buy_fee",
        "buy_cash_delta",
        "exit_trigger_date",
        "exit_trigger_reason",
    }.issubset(positions.c.keys())
    assert {
        "exit_at",
        "exit_price",
        "sell_fee",
        "sell_cash_delta",
        "net_pnl",
        "net_return_pct",
    }.issubset(trades.c.keys())
    assert all(not name.startswith("limit_up_") for name in (
        runs.name,
        signals.name,
        positions.name,
        trades.name,
    ))


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeSession:
    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.calls: list[tuple[object, object | None]] = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if getattr(statement, "is_select", False):
            return FakeResult(self.existing)
        return FakeResult([])


def _patch_session(monkeypatch, session: FakeSession) -> None:
    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(repository.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", fake_session_scope)


def _compiled(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _capture() -> SwingSignalCapture:
    return build_swing_signal_capture(_inputs())


def test_complete_signal_capture_is_inserted_atomically(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repository.save_signal_capture(_capture())

    assert result.status == "frozen"
    assert result.rows_written == 1
    inserts = [
        statement
        for statement, _ in session.calls
        if getattr(statement, "is_insert", False)
    ]
    assert len(inserts) == 2
    assert _compiled(inserts[0]).startswith(
        "INSERT INTO low_suction_strategy_signals"
    )
    assert str(inserts[1]).startswith(
        "INSERT INTO low_suction_strategy_runs"
    )


def test_identical_complete_capture_is_idempotent(monkeypatch) -> None:
    capture = _capture()
    session = FakeSession(
        [
            {
                "complete": True,
                "input_fingerprint": capture.input_fingerprint,
            }
        ]
    )
    _patch_session(monkeypatch, session)

    result = repository.save_signal_capture(capture)

    assert result.status == "already_frozen"
    assert result.rows_written == 0
    assert len(session.calls) == 1


def test_complete_signal_capture_fingerprint_cannot_change(monkeypatch) -> None:
    capture = _capture()
    session = FakeSession(
        [{"complete": True, "input_fingerprint": "sha256:" + "f" * 64}]
    )
    _patch_session(monkeypatch, session)

    with pytest.raises(repository.SwingStrategyImmutableError):
        repository.save_signal_capture(capture)

    assert len(session.calls) == 1


def test_signal_preview_is_replaceable_and_stored_under_preview_phase(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)
    preview_at = datetime(2026, 7, 20, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    capture = _capture()
    preview = replace(
        capture,
        captured_at=preview_at,
        feature_cutoff_at=preview_at,
        candidates=tuple(
            replace(row, captured_at=preview_at, feature_cutoff_at=preview_at)
            for row in capture.candidates
        ),
    )

    result = repository.save_signal_preview(preview)

    assert result.status == "preview_replaced"
    run_insert = next(
        statement
        for statement, _ in session.calls
        if getattr(statement, "is_insert", False)
        and "low_suction_strategy_runs" in str(statement)
    )
    assert run_insert.compile(dialect=postgresql.dialect()).params["phase"] == (
        repository.PREVIEW_PHASE
    )


def test_signal_preview_cannot_replace_frozen_final_capture(monkeypatch) -> None:
    session = FakeSession([{"complete": True}])
    _patch_session(monkeypatch, session)

    result = repository.save_signal_preview(_capture())

    assert result.status == "final_preserved"
    assert not any(
        getattr(statement, "is_delete", False) for statement, _ in session.calls
    )


def test_blocked_signal_run_can_be_replaced_by_a_complete_capture(monkeypatch) -> None:
    session = FakeSession(
        [{"complete": False, "input_fingerprint": "sha256:" + "b" * 64}]
    )
    _patch_session(monkeypatch, session)

    result = repository.save_signal_capture(_capture())

    assert result.status == "frozen"
    assert any(getattr(statement, "is_delete", False) for statement, _ in session.calls)


def test_settlement_persists_daily_position_marks(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repository.save_exit_triggers(
        as_of_date=_capture().signal_trade_date,
        attempted_at=_capture().captured_at,
        decisions=(),
        marks={"signal-1": 14.4},
    )

    updates = [
        statement
        for statement, _ in session.calls
        if getattr(statement, "is_update", False)
    ]
    assert result["status"] == "complete"
    assert len(updates) == 1
    assert "last_mark_price=14.4" in _compiled(updates[0])
