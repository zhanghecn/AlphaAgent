from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import historical_replay_repository as repository


def _run() -> dict[str, object]:
    return {
        "run_id": "replay-1",
        "policy_version": "causal-leader-pullback-three-phase-adaptive-v1",
        "qualification_contract_version": "three-phase-natural-qualification-wilson-v1",
        "evidence_level": "exploratory_survivorship_proxy",
        "membership_mode": "current_membership_replayed_backward",
        "input_fingerprint": "a" * 64,
        "regression_artifact_sha256": "b" * 64,
        "trade_count": 2,
        "metrics": {"positive_rate_pct": 50.0},
        "built_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
    }


def _trades() -> pd.DataFrame:
    common = {
        "campaign_id": "campaign-1",
        "sector_id": "BK0001",
        "concept_name": "光通信",
        "stock_name": "示例股份",
        "time_block": "development",
        "dynamic_rank": 1,
        "wave_number": 2,
        "support_line": "MA5",
        "support_price": 10.0,
        "support_test_date": date(2026, 6, 24),
        "entry_price": 10.2,
        "d1_date": date(2026, 6, 26),
        "d1_close": 10.6,
        "exit_date": date(2026, 6, 27),
        "exit_price": 10.8,
        "exit_reason": "higher_high_confirmed",
        "holding_sessions": 2,
    }
    return pd.DataFrame(
        [
            {
                **common,
                "signal_id": "signal-1",
                "vt_symbol": "000001.SZSE",
                "market_phase": "rotation",
                "signal_date": date(2026, 6, 25),
                "d1_net_return_pct": 3.9,
                "net_return_pct": 5.7,
            },
            {
                **common,
                "signal_id": "signal-2",
                "vt_symbol": "600001.SSE",
                "market_phase": "uptrend",
                "signal_date": date(2026, 7, 2),
                "d1_net_return_pct": -1.2,
                "net_return_pct": -0.8,
            },
        ]
    )


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None, scalar: int = 0) -> None:
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one(self) -> int:
        return self.scalar


class FakeSession:
    def __init__(self, select_results: list[FakeResult] | None = None) -> None:
        self.select_results = list(select_results or [])
        self.calls: list[tuple[object, object | None]] = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if getattr(statement, "is_select", False):
            return self.select_results.pop(0) if self.select_results else FakeResult()
        return FakeResult()


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
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_historical_replay_schema_has_run_and_trade_identities() -> None:
    assert set(schema.low_suction_historical_replay_runs.primary_key.columns.keys()) == {
        "run_id"
    }
    assert set(schema.low_suction_historical_replay_trades.primary_key.columns.keys()) == {
        "run_id",
        "signal_id",
    }
    assert schema.low_suction_historical_replay_runs.c.evidence_level.nullable is False
    assert schema.low_suction_historical_replay_runs.c.membership_mode.nullable is False


def test_save_replay_inserts_run_and_database_derived_rows(monkeypatch) -> None:
    session = FakeSession([FakeResult([])])
    _patch_session(monkeypatch, session)

    result = repository.save_replay_run(_run(), _trades())

    assert result == {"status": "saved", "runs_written": 1, "trades_written": 2}
    assert str(session.calls[1][0]).startswith(
        "INSERT INTO low_suction_historical_replay_runs"
    )
    assert str(session.calls[2][0]).startswith(
        "INSERT INTO low_suction_historical_replay_trades"
    )


def test_save_replay_rejects_changed_rows_for_existing_run(monkeypatch) -> None:
    first_session = FakeSession([FakeResult([])])
    _patch_session(monkeypatch, first_session)
    repository.save_replay_run(_run(), _trades())
    inserted = first_session.calls[1][0].compile().params

    changed = _trades().copy()
    changed.loc[0, "net_return_pct"] = 99.0
    second_session = FakeSession([FakeResult([inserted])])
    _patch_session(monkeypatch, second_session)

    with pytest.raises(repository.HistoricalReplayImmutableError):
        repository.save_replay_run(_run(), changed)


def test_strict_evidence_rejects_current_membership_proxy(monkeypatch) -> None:
    run = _run()
    run["evidence_level"] = "strict_point_in_time"
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError, match="point-in-time"):
        repository.save_replay_run(run, _trades())

    assert session.calls == []


def test_list_replay_trades_filters_phase_and_paginates(monkeypatch) -> None:
    row = _trades().iloc[0].to_dict() | {"run_id": "replay-1"}
    session = FakeSession([FakeResult(scalar=1), FakeResult([row])])
    _patch_session(monkeypatch, session)

    result = repository.list_replay_trades(
        run_id="replay-1", market_phase="rotation", page=1, page_size=20
    )

    assert result["total"] == 1
    assert result["items"][0]["market_phase"] == "rotation"
    sql = _compiled(session.calls[1][0])
    assert "market_phase = 'rotation'" in sql
    assert "LIMIT 20 OFFSET 0" in sql


@pytest.mark.parametrize("page_size", [0, 101])
def test_list_replay_trades_rejects_unbounded_page_size(page_size: int) -> None:
    with pytest.raises(ValueError, match="page_size"):
        repository.list_replay_trades(run_id="replay-1", page_size=page_size)
