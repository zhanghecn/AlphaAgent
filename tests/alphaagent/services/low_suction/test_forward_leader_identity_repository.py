from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import (
    forward_leader_identity_repository as repository,
)
from alphaagent.server.services.low_suction.forward_leader_identity import (
    FORWARD_LEADER_RANKING_VERSION,
    FORWARD_RANK_EVIDENCE_LEVEL,
    FORWARD_TARGET_SESSION,
    ForwardLeaderCapture,
    ForwardLeaderRankRow,
    ForwardLeaderRankScope,
)
from alphaagent.server.services.low_suction.leader_identity import LeaderIdentityMode

SOURCE_DATE = date(2026, 7, 16)
KNOWN_AT = datetime(2026, 7, 16, 18, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
FINGERPRINT = "sha256:" + "a" * 64


def test_forward_leader_tables_have_immutable_source_keys() -> None:
    rows = schema.low_suction_forward_leader_rank_snapshots
    scopes = schema.low_suction_forward_leader_rank_snapshot_scopes

    assert [column.name for column in rows.primary_key.columns] == [
        "source_trade_date",
        "ranking_version",
        "identity_mode",
        "sector_id",
        "vt_symbol",
    ]
    assert [column.name for column in scopes.primary_key.columns] == [
        "source_trade_date",
        "ranking_version",
        "identity_mode",
    ]
    assert not rows.foreign_keys
    assert not scopes.foreign_keys
    assert {
        "target_session",
        "target_trade_date",
        "known_at",
        "feature_cutoff",
        "sector_name",
        "cycle_id",
        "cycle_start",
        "cycle_days",
        "cycle_relative_return",
        "strong_day_count_cycle",
        "sessions_since_strong",
        "turnover_median_20d",
        "capacity_passed",
        "relative_strength_rank",
        "market_recognition_rank",
        "rank",
        "rank_eligible",
        "is_top3",
        "excluded_reason",
        "input_fingerprint",
        "evidence_level",
        "raw",
    }.issubset(rows.c.keys())
    assert {
        "target_session",
        "target_trade_date",
        "known_at",
        "feature_cutoff",
        "main_rise_definition",
        "active_concept_count",
        "membership_row_count",
        "main_board_member_count",
        "security_eligible_count",
        "ranked_row_count",
        "top3_row_count",
        "excluded_row_count",
        "complete",
        "status",
        "input_fingerprint",
        "selected_mode",
        "evidence_level",
        "raw",
    }.issubset(scopes.c.keys())


def _capture(*, complete: bool = True, fingerprint: str = FINGERPRINT) -> ForwardLeaderCapture:
    rows = []
    scopes = []
    for mode in LeaderIdentityMode:
        if complete:
            rows.append(
                ForwardLeaderRankRow(
                    source_trade_date=SOURCE_DATE,
                    ranking_version=FORWARD_LEADER_RANKING_VERSION,
                    identity_mode=mode.value,
                    sector_id="BK_TEST",
                    vt_symbol="000001.SZSE",
                    target_session=FORWARD_TARGET_SESSION,
                    target_trade_date=None,
                    known_at=KNOWN_AT,
                    feature_cutoff=KNOWN_AT.replace(hour=15, minute=0),
                    membership_known_at=KNOWN_AT.replace(minute=0),
                    security_known_at=KNOWN_AT,
                    sector_name="测试主升",
                    cycle_id="BK_TEST:2026-07-15",
                    cycle_start=date(2026, 7, 15),
                    cycle_days=2,
                    cycle_relative_return=3.0,
                    strong_day_count_cycle=1,
                    sessions_since_strong=0,
                    turnover_median_20d=200_000_000.0,
                    capacity_passed=True,
                    relative_strength_rank=1,
                    market_recognition_rank=1,
                    rank=1,
                    rank_eligible=True,
                    is_top3=True,
                    excluded_reason=None,
                    input_fingerprint=fingerprint,
                    evidence_level=FORWARD_RANK_EVIDENCE_LEVEL,
                    raw={},
                )
            )
        scopes.append(
            ForwardLeaderRankScope(
                source_trade_date=SOURCE_DATE,
                ranking_version=FORWARD_LEADER_RANKING_VERSION,
                identity_mode=mode.value,
                target_session=FORWARD_TARGET_SESSION,
                target_trade_date=None,
                known_at=KNOWN_AT,
                feature_cutoff=KNOWN_AT.replace(hour=15, minute=0),
                main_rise_definition="breakout_trend",
                active_concept_count=1 if complete else 0,
                membership_row_count=1,
                main_board_member_count=1 if complete else 0,
                security_eligible_count=1 if complete else 0,
                ranked_row_count=1 if complete else 0,
                top3_row_count=1 if complete else 0,
                excluded_row_count=0,
                complete=complete,
                status="frozen_unbound" if complete else "blocked",
                input_fingerprint=fingerprint,
                selected_mode=None,
                evidence_level=(
                    FORWARD_RANK_EVIDENCE_LEVEL
                    if complete
                    else "rejected_incomplete_forward_inputs"
                ),
                raw={} if complete else {"blocking_reason": "test_gap"},
            )
        )
    return ForwardLeaderCapture(
        source_trade_date=SOURCE_DATE,
        ranking_version=FORWARD_LEADER_RANKING_VERSION,
        input_fingerprint=fingerprint,
        rows=tuple(rows),
        scopes=tuple(scopes),
    )


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


def test_source_statements_use_exact_strict_snapshots_and_source_cutoff() -> None:
    statements = repository._source_statements(
        SOURCE_DATE,
        trading_dates=(date(2026, 7, 15), SOURCE_DATE),
        vt_symbols=("000001.SZSE",),
        stock_start=date(2026, 7, 15),
    )
    compiled = {name: _compiled(statement) for name, statement in statements.items()}

    assert "low_suction_forward_membership_snapshot_scopes" in compiled[
        "membership_scope"
    ]
    assert "scope_type = 'concept_tradable'" in compiled["membership_scope"]
    assert "source_trade_date = '2026-07-16'" in compiled["membership_rows"]
    assert "low_suction_security_snapshot_scopes" in compiled["security_scope"]
    assert "source_trade_date = '2026-07-16'" in compiled["security_rows"]
    assert "sector_daily_bars.trade_date IN ('2026-07-15', '2026-07-16')" in compiled[
        "concept_bars"
    ]
    assert "stock_daily_bars.trade_date BETWEEN '2026-07-15' AND '2026-07-16'" in compiled[
        "stock_bars"
    ]
    all_sql = "\n".join(compiled.values())
    assert "stock_sector_memberships" not in all_sql
    assert "sector_memberships" not in all_sql


def test_complete_capture_is_inserted_atomically(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repository.save_forward_leader_capture(_capture())

    assert result.status == "frozen"
    assert result.rows_written == 3
    assert result.scopes_written == 3
    assert len(session.calls) == 3
    assert session.calls[0][0].is_select
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO low_suction_forward_leader_rank_snapshots"
    )
    assert _compiled(session.calls[2][0]).startswith(
        "INSERT INTO low_suction_forward_leader_rank_snapshot_scopes"
    )


def test_same_complete_fingerprint_is_idempotent(monkeypatch) -> None:
    existing = [
        {
            "identity_mode": mode.value,
            "complete": True,
            "input_fingerprint": FINGERPRINT,
        }
        for mode in LeaderIdentityMode
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_leader_capture(_capture())

    assert result.status == "already_frozen"
    assert result.rows_written == 0
    assert len(session.calls) == 1


def test_changed_fingerprint_cannot_mutate_complete_freeze(monkeypatch) -> None:
    existing = [
        {
            "identity_mode": mode.value,
            "complete": True,
            "input_fingerprint": FINGERPRINT,
        }
        for mode in LeaderIdentityMode
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    with pytest.raises(repository.ForwardLeaderLedgerImmutableError):
        repository.save_forward_leader_capture(
            _capture(fingerprint="sha256:" + "b" * 64)
        )

    assert len(session.calls) == 1


def test_closed_retry_cannot_overwrite_complete_freeze(monkeypatch) -> None:
    existing = [
        {
            "identity_mode": mode.value,
            "complete": True,
            "input_fingerprint": FINGERPRINT,
        }
        for mode in LeaderIdentityMode
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_leader_capture(_capture(complete=False))

    assert result.status == "complete_preserved"
    assert len(session.calls) == 1


def test_complete_retry_promotes_previous_closed_scopes(monkeypatch) -> None:
    existing = [
        {
            "identity_mode": mode.value,
            "complete": False,
            "input_fingerprint": "sha256:" + "c" * 64,
        }
        for mode in LeaderIdentityMode
    ]
    session = FakeSession(existing)
    _patch_session(monkeypatch, session)

    result = repository.save_forward_leader_capture(_capture())

    assert result.status == "frozen"
    assert result.rows_written == 3
    assert any(getattr(call[0], "is_delete", False) for call in session.calls)


def test_next_completed_session_binding_never_uses_calendar_day_guess() -> None:
    assert repository.resolve_next_completed_session(
        SOURCE_DATE,
        (SOURCE_DATE, date(2026, 7, 20)),
    ) == date(2026, 7, 20)
    assert (
        repository.resolve_next_completed_session(SOURCE_DATE, (SOURCE_DATE,))
        is None
    )


def _ledger_frames(
    *,
    session_count: int,
    sector_count: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[date, ...]]:
    source_dates = tuple(
        timestamp.date()
        for timestamp in pd.bdate_range("2026-01-05", periods=session_count)
    )
    completed_dates = tuple(
        timestamp.date()
        for timestamp in pd.bdate_range(
            source_dates[0],
            periods=session_count + 6,
        )
    )
    scopes = []
    ranks = []
    for source_index, source_date in enumerate(source_dates):
        target_date = completed_dates[source_index + 1]
        for mode in LeaderIdentityMode:
            scopes.append(
                {
                    "source_trade_date": source_date,
                    "target_trade_date": target_date,
                    "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                    "identity_mode": mode.value,
                    "complete": True,
                    "status": "frozen_bound",
                    "input_fingerprint": FINGERPRINT,
                }
            )
            for sector_index in range(sector_count):
                for rank in range(1, 4):
                    ranks.append(
                        {
                            "source_trade_date": source_date,
                            "target_trade_date": target_date,
                            "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                            "identity_mode": mode.value,
                            "sector_id": f"BK{sector_index:04d}",
                            "sector_name": f"概念{sector_index}",
                            "vt_symbol": f"00000{rank}.SZSE",
                            "rank": rank,
                            "is_top3": True,
                            "capacity_passed": rank <= 2,
                            "raw": {"stock_name": f"股票{rank}"},
                        }
                    )
    daily_bars = []
    for symbol_rank in range(1, 4):
        for trade_date in completed_dates:
            daily_bars.append(
                {
                    "vt_symbol": f"00000{symbol_rank}.SZSE",
                    "trade_date": trade_date,
                    "change_pct": 6.0,
                    "close_price": 10.0,
                }
            )
    return (
        pd.DataFrame(scopes),
        pd.DataFrame(ranks),
        pd.DataFrame(daily_bars),
        completed_dates,
    )


def test_forward_evaluation_reports_partial_metrics_without_trade_returns() -> None:
    scopes, ranks, daily_bars, completed_dates = _ledger_frames(session_count=2)

    report = repository.evaluate_forward_leader_ledger(
        scopes,
        ranks,
        daily_bars,
        completed_dates=completed_dates,
    )

    assert report["source_sessions"] == 2
    assert report["bound_sessions"] == 2
    assert report["selected_mode"] is None
    assert report["selection_status"] == "accumulating_forward_identity"
    assert report["formal_metrics"] is None
    assert report["low_suction_outcomes_read"] is False
    for metric in report["mode_metrics"]:
        assert metric["eligible_retention_observations"] == 3
        assert metric["next_session_top3_retention"] == pytest.approx(1.0)
        assert metric["strong_event_lead_observations"] == 6
        assert metric["strong_event_lead_sessions"] == pytest.approx(0.0)
        assert metric["capacity_pass_rate"] == pytest.approx(2 / 3)


def test_forward_mode_overlap_is_stable_for_json_evidence() -> None:
    overlap_shapes = (
        [(3, 3)] * 20
        + [(2, 4)] * 8
        + [(2, 3)] * 3
        + [(1, 4)] * 3
        + [(1, 3)]
        + [(0, 4)]
    )
    rows = []
    for sector_index, (intersection_size, union_size) in enumerate(overlap_shapes):
        sector_id = f"BK{sector_index:04d}"
        shared = [
            f"shared-{sector_index}-{symbol_index}"
            for symbol_index in range(intersection_size)
        ]
        left_symbols = shared + [
            f"left-{sector_index}-{symbol_index}"
            for symbol_index in range(3 - intersection_size)
        ]
        right_symbols = shared + [
            f"right-{sector_index}-{symbol_index}"
            for symbol_index in range(union_size - 3)
        ]
        for identity_mode, symbols in (
            (LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH.value, left_symbols),
            (LeaderIdentityMode.RECOGNITION_CONSENSUS.value, right_symbols),
        ):
            rows.extend(
                {
                    "source_trade_date": SOURCE_DATE,
                    "identity_mode": identity_mode,
                    "sector_id": sector_id,
                    "vt_symbol": symbol,
                }
                for symbol in symbols
            )
    top3 = pd.DataFrame(rows)

    overlaps = repository._mode_top3_overlap(top3)
    shuffled = repository._mode_top3_overlap(
        top3.sample(frac=1, random_state=17).reset_index(drop=True)
    )
    metric = next(
        row
        for row in overlaps
        if row["left_mode"]
        == LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH.value
        and row["right_mode"] == LeaderIdentityMode.RECOGNITION_CONSENSUS.value
    )

    assert metric["concept_sessions"] == 36
    assert metric["mean_top3_jaccard"] == 0.752314814815
    assert shuffled == overlaps


def test_forward_mode_selection_waits_for_sixty_bound_sessions() -> None:
    short = _ledger_frames(session_count=59, sector_count=4)
    short_report = repository.evaluate_forward_leader_ledger(
        short[0],
        short[1],
        short[2],
        completed_dates=short[3],
    )
    assert short_report["selected_mode"] is None

    mature = _ledger_frames(session_count=60, sector_count=4)
    mature_report = repository.evaluate_forward_leader_ledger(
        mature[0],
        mature[1],
        mature[2],
        completed_dates=mature[3],
    )

    assert mature_report["selected_mode"] == "cycle_relative_strength"
    assert mature_report["selection_status"] == "selected_forward_identity"
    assert mature_report["fold_win_counts"] == {"cycle_relative_strength": 5}
