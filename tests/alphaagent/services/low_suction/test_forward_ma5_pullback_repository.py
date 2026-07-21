from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import (
    forward_ma5_pullback_repository as repository,
)
from alphaagent.server.services.low_suction.forward_ma5_pullback import (
    ForwardMa5Capture,
    build_forward_ma5_capture,
    evaluate_forward_ma5_outcomes,
)
from tests.alphaagent.services.low_suction.test_forward_ma5_pullback import (
    _bars,
    _calendar,
    _inputs,
)


def test_forward_ma5_tables_are_isolated_by_contract_and_candidate_identity() -> None:
    candidates = schema.low_suction_forward_ma5_candidates
    scopes = schema.low_suction_forward_ma5_scopes
    outcomes = schema.low_suction_forward_ma5_outcomes

    assert [column.name for column in candidates.primary_key.columns] == [
        "contract_version",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
    ]
    assert [column.name for column in scopes.primary_key.columns] == [
        "contract_version",
        "signal_trade_date",
        "identity_mode",
    ]
    assert [column.name for column in outcomes.primary_key.columns] == [
        "contract_version",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
    ]
    assert not candidates.foreign_keys
    assert not scopes.foreign_keys
    assert not outcomes.foreign_keys
    assert {
        "source_trade_date",
        "known_at",
        "feature_cutoff_date",
        "sector_id",
        "rank",
        "spell_anchor_date",
        "current_wave_number",
        "reference_peak_price",
        "support_line",
        "stock_structure_intact",
        "concept_main_rise_intact",
        "stock_main_net_inflow",
        "sector_main_net_inflow",
        "market_timing_direction",
        "signal_eligible",
        "decision_reason",
        "input_fingerprint",
        "raw",
    }.issubset(candidates.c.keys())
    assert {
        "status",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "net_return_pct",
        "mae_pct",
        "mfe_pct",
        "right_censored",
        "terminal",
        "last_evaluated_trade_date",
    }.issubset(outcomes.c.keys())


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


def _capture() -> ForwardMa5Capture:
    return build_forward_ma5_capture(_inputs())


def test_complete_capture_is_inserted_atomically(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repository.save_forward_ma5_capture(_capture())

    assert result.status == "frozen"
    assert result.rows_written == 3
    assert result.scopes_written == 3
    assert len(session.calls) == 3
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO low_suction_forward_ma5_candidates"
    )
    assert _compiled(session.calls[2][0]).startswith(
        "INSERT INTO low_suction_forward_ma5_scopes"
    )


def test_identical_complete_capture_is_idempotent(monkeypatch) -> None:
    capture = _capture()
    existing = [
        {
            "identity_mode": scope.identity_mode,
            "complete": True,
            "input_fingerprint": capture.input_fingerprint,
        }
        for scope in capture.scopes
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_ma5_capture(capture)

    assert result.status == "already_frozen"
    assert result.rows_written == 0
    assert len(session.calls) == 1


def test_complete_capture_fingerprint_cannot_change(monkeypatch) -> None:
    capture = _capture()
    existing = [
        {
            "identity_mode": scope.identity_mode,
            "complete": True,
            "input_fingerprint": "sha256:" + "f" * 64,
        }
        for scope in capture.scopes
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    with pytest.raises(repository.ForwardMa5LedgerImmutableError):
        repository.save_forward_ma5_capture(capture)

    assert len(session.calls) == 1


def test_blocked_capture_can_be_promoted(monkeypatch) -> None:
    existing = [
        {
            "identity_mode": scope.identity_mode,
            "complete": False,
            "input_fingerprint": "sha256:" + "b" * 64,
        }
        for scope in _capture().scopes
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_ma5_capture(_capture())

    assert result.status == "frozen"
    assert any(getattr(statement, "is_delete", False) for statement, _ in session.calls)


def test_terminal_outcome_is_preserved(monkeypatch) -> None:
    capture = _capture()
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    outcomes = evaluate_forward_ma5_outcomes(
        candidates,
        _bars(),
        completed_dates=_calendar(),
    )
    existing = [
        {
            "contract_version": outcomes.iloc[0]["contract_version"],
            "signal_trade_date": outcomes.iloc[0]["signal_trade_date"],
            "identity_mode": outcomes.iloc[0]["identity_mode"],
            "vt_symbol": outcomes.iloc[0]["vt_symbol"],
            "candidate_input_fingerprint": outcomes.iloc[0][
                "candidate_input_fingerprint"
            ],
            "terminal": True,
            "status": "closed",
        }
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_ma5_outcomes(outcomes)

    assert result == {"inserted": 0, "updated": 0, "terminal_preserved": 1}
    assert len(session.calls) == 1


def test_nonterminal_outcome_advances_with_new_completed_bars(monkeypatch) -> None:
    capture = _capture()
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    outcomes = evaluate_forward_ma5_outcomes(
        candidates,
        _bars(),
        completed_dates=_calendar(),
    )
    existing = [
        {
            "contract_version": outcomes.iloc[0]["contract_version"],
            "signal_trade_date": outcomes.iloc[0]["signal_trade_date"],
            "identity_mode": outcomes.iloc[0]["identity_mode"],
            "vt_symbol": outcomes.iloc[0]["vt_symbol"],
            "candidate_input_fingerprint": outcomes.iloc[0][
                "candidate_input_fingerprint"
            ],
            "terminal": False,
            "status": "open",
        }
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_ma5_outcomes(outcomes)

    assert result == {"inserted": 0, "updated": 1, "terminal_preserved": 0}
    assert any(getattr(statement, "is_update", False) for statement, _ in session.calls)


def test_eligible_source_pairs_omit_complete_frozen_signal_dates(monkeypatch) -> None:
    class SequencedSession:
        def __init__(self) -> None:
            self.results = [
                [
                    {
                        "source_trade_date": date(2026, 7, 16),
                        "target_trade_date": date(2026, 7, 17),
                        "mode_count": 3,
                        "all_complete": True,
                    },
                    {
                        "source_trade_date": date(2026, 7, 17),
                        "target_trade_date": date(2026, 7, 20),
                        "mode_count": 3,
                        "all_complete": True,
                    },
                ],
                [
                    {
                        "signal_trade_date": date(2026, 7, 17),
                        "mode_count": 3,
                        "all_complete": True,
                    }
                ],
            ]

        def execute(self, statement):
            del statement
            return FakeResult(self.results.pop(0))

    session = SequencedSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(repository.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", fake_session_scope)

    pairs = repository._eligible_source_pairs(date(2026, 7, 20))

    assert pairs == ((date(2026, 7, 17), date(2026, 7, 20)),)


def test_source_queries_use_only_strict_forward_ledgers() -> None:
    statements = repository._capture_statements(
        source_trade_date=_inputs().source_trade_date,
        signal_trade_date=_inputs().signal_trade_date,
        attempted_at=_inputs().attempted_at,
    )
    compiled = {name: _compiled(statement) for name, statement in statements.items()}

    assert "low_suction_forward_leader_rank_snapshot_scopes" in compiled[
        "prior_scopes"
    ]
    assert "low_suction_forward_leader_rank_snapshots" in compiled["rank_history"]
    assert "sector_fund_flow_snapshots" in compiled["sector_fund_flows"]
    assert "captured_at <=" in compiled["sector_fund_flows"]
    all_sql = "\n".join(compiled.values())
    assert "stock_sector_memberships" not in all_sql
    assert "sector_memberships" not in all_sql


def test_blocked_capture_fixture_has_no_candidates() -> None:
    scopes = _inputs().signal_scopes.copy()
    scopes.loc[scopes.index[0], "complete"] = False
    capture = build_forward_ma5_capture(replace(_inputs(), signal_scopes=scopes))

    assert not capture.complete
    assert capture.rows == ()


def test_report_is_deterministic_and_keeps_formal_metrics_null() -> None:
    blocked = build_forward_ma5_capture(
        replace(
            _inputs(),
            signal_scopes=_inputs().signal_scopes.assign(complete=False),
        )
    )
    scopes = pd.DataFrame([scope.__dict__ for scope in blocked.scopes])

    report = repository.build_forward_ma5_shadow_report(
        scopes,
        pd.DataFrame(),
        pd.DataFrame(),
        selected_mode=None,
        selection_status="accumulating_forward_identity",
        as_of_date=_inputs().signal_trade_date,
    )
    first_json = repository.render_forward_ma5_json(report)
    second_json = repository.render_forward_ma5_json(report)
    markdown = repository.render_forward_ma5_markdown(report)

    assert report["research_status"] == "blocked_by_strict_forward_inputs"
    assert report["formal_metrics"] == {
        "top3_mode": None,
        "win_rate_pct": None,
        "average_net_return_pct": None,
        "compounded_return_pct": None,
        "profit_factor": None,
        "maximum_drawdown_pct": None,
    }
    assert first_json == second_json
    assert '"formal_metrics"' in first_json
    assert "正式 Top3、胜率、收益、复利、利润因子和回撤：`null`" in markdown
    assert "signal_top3_scopes_not_complete" in markdown
