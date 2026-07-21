from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from hashlib import sha1
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.services.low_suction import (
    causal_leader_pullback_forward_repository as repository,
)
from alphaagent.server.services.low_suction.causal_leader_pullback_forward import (
    FORWARD_CONTRACT_VERSION,
    FORWARD_EVIDENCE_LEVEL,
    FORWARD_IDENTITY_MODE,
    blocked_causal_forward_capture,
)
from alphaagent.server.services.low_suction.forward_ma5_pullback import (
    ForwardMa5Capture,
    ForwardMa5Scope,
    build_forward_ma5_capture,
)
from tests.alphaagent.services.low_suction.test_forward_ma5_pullback import (
    _inputs as legacy_inputs,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_DATE = date(2026, 7, 20)
SIGNAL_DATE = date(2026, 7, 21)
ATTEMPTED_AT = datetime(2026, 7, 21, 19, 5, tzinfo=SHANGHAI)
FINGERPRINT = "sha256:" + "a" * 64


def test_terminal_shadow_merge_preserves_existing_trade_evidence() -> None:
    existing = {"signal_id": "s1", "d1_close": 11.0}
    incoming = {
        "signal_id": "s1",
        "d1_close": 99.0,
        "d2_fast_limit_shadow": {"status": "settled", "d2_net_return_pct": 19.8},
    }

    merged = repository._terminal_raw_with_d2_shadow(existing, incoming)

    assert merged == {
        "signal_id": "s1",
        "d1_close": 11.0,
        "d2_fast_limit_shadow": {"status": "settled", "d2_net_return_pct": 19.8},
    }


def _campaign_id(sector_id: str, anchor_date: date) -> str:
    key = (
        "breakout_relative_turnover|5.0|3|"
        f"{sector_id}|{anchor_date.isoformat()}"
    )
    return sha1(key.encode("utf-8")).hexdigest()


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def scalar_one(self) -> int:
        return len(self.rows)


class FakeSession:
    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.calls: list[tuple[object, object | None]] = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if getattr(statement, "is_select", False):
            return FakeResult(self.existing)
        return FakeResult([])


@pytest.fixture(autouse=True)
def fixed_natural_clock(monkeypatch) -> None:
    monkeypatch.setattr(repository, "_shanghai_now", lambda: ATTEMPTED_AT)


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


def test_forward_ledger_pages_candidates_with_outcome_projection(monkeypatch) -> None:
    row = {
        "signal_trade_date": SIGNAL_DATE,
        "vt_symbol": "000001.SZSE",
        "signal_eligible": True,
        "outcome_status": "closed",
    }
    session = FakeSession([{"count": 1}])
    results = iter([FakeResult([{"count": 1}]), FakeResult([row])])

    def execute(statement, parameters=None):
        session.calls.append((statement, parameters))
        return next(results)

    session.execute = execute
    _patch_session(monkeypatch, session)

    report = repository.list_causal_forward_ledger(page=1, page_size=20)

    assert report["total"] == 1
    assert report["items"][0]["outcome_status"] == "closed"
    assert report["historical_backfill_allowed"] is False
    assert "LEFT OUTER JOIN low_suction_forward_ma5_outcomes" in _compiled(
        session.calls[1][0]
    )


def _complete_capture() -> ForwardMa5Capture:
    legacy = build_forward_ma5_capture(legacy_inputs())
    row = replace(
        legacy.rows[0],
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=SOURCE_DATE,
        signal_trade_date=SIGNAL_DATE,
        identity_mode=FORWARD_IDENTITY_MODE,
        known_at=ATTEMPTED_AT,
        feature_cutoff_date=SIGNAL_DATE,
        pullback_confirmation_date=SIGNAL_DATE,
        selected_mode_at_capture=FORWARD_IDENTITY_MODE,
        input_fingerprint=FINGERPRINT,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        raw={
            "signal": {
                "signal_id": "signal-1",
                "campaign_id": "campaign-1",
            }
        },
    )
    scope = ForwardMa5Scope(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=SOURCE_DATE,
        signal_trade_date=SIGNAL_DATE,
        identity_mode=FORWARD_IDENTITY_MODE,
        known_at=ATTEMPTED_AT,
        complete=True,
        status="frozen",
        prior_top3_count=1,
        unique_candidate_count=1,
        active_concept_count=1,
        signal_count=1,
        selected_mode_at_capture=FORWARD_IDENTITY_MODE,
        input_fingerprint=FINGERPRINT,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        raw={"formal_metrics": None},
    )
    return ForwardMa5Capture(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=SOURCE_DATE,
        signal_trade_date=SIGNAL_DATE,
        input_fingerprint=FINGERPRINT,
        rows=(row,),
        scopes=(scope,),
    )


def _existing_scope(*, complete: bool, fingerprint: str = FINGERPRINT) -> list[dict[str, Any]]:
    return [
        {
            "identity_mode": FORWARD_IDENTITY_MODE,
            "complete": complete,
            "input_fingerprint": fingerprint,
        }
    ]


def _outcome(*, terminal: bool) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_version": FORWARD_CONTRACT_VERSION,
                "source_trade_date": SOURCE_DATE,
                "signal_trade_date": SIGNAL_DATE,
                "identity_mode": FORWARD_IDENTITY_MODE,
                "vt_symbol": "000001.SZSE",
                "candidate_input_fingerprint": FINGERPRINT,
                "status": "closed" if terminal else "open",
                "entry_date": SIGNAL_DATE,
                "entry_price": 10.0,
                "entry_proxy": "same_completed_session_close_research_proxy",
                "exit_date": date(2026, 7, 22) if terminal else None,
                "exit_price": 10.5 if terminal else None,
                "exit_reason": "higher_high_confirmed" if terminal else None,
                "gross_return_pct": 5.0 if terminal else None,
                "net_return_pct": 4.8 if terminal else None,
                "mae_pct": -1.0,
                "mfe_pct": 5.0,
                "round_trip_cost_pct": 0.2,
                "right_censored": False,
                "terminal": terminal,
                "last_evaluated_trade_date": date(2026, 7, 22),
                "raw": {"signal_id": "signal-1"},
            }
        ]
    )


def test_complete_v2_capture_is_inserted_atomically(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    result = repository.save_causal_forward_capture(_complete_capture())

    assert result.status == "frozen"
    assert result.rows_written == 1
    assert result.scopes_written == 1
    assert len(session.calls) == 3
    assert _compiled(session.calls[1][0]).startswith(
        "INSERT INTO low_suction_forward_ma5_candidates"
    )
    assert _compiled(session.calls[2][0]).startswith(
        "INSERT INTO low_suction_forward_ma5_scopes"
    )


def test_identical_complete_v2_capture_is_idempotent(monkeypatch) -> None:
    session = FakeSession(_existing_scope(complete=True))
    _patch_session(monkeypatch, session)

    result = repository.save_causal_forward_capture(_complete_capture())

    assert result.status == "already_frozen"
    assert result.rows_written == 0
    assert result.scopes_written == 0
    assert len(session.calls) == 1


def test_complete_v2_scope_fingerprint_cannot_change(monkeypatch) -> None:
    session = FakeSession(
        _existing_scope(complete=True, fingerprint="sha256:" + "f" * 64)
    )
    _patch_session(monkeypatch, session)

    with pytest.raises(repository.CausalForwardLedgerImmutableError):
        repository.save_causal_forward_capture(_complete_capture())

    assert len(session.calls) == 1


def test_blocked_v2_scope_can_recover_only_on_the_same_signal_day(monkeypatch) -> None:
    session = FakeSession(
        _existing_scope(complete=False, fingerprint="sha256:" + "b" * 64)
    )
    _patch_session(monkeypatch, session)

    result = repository.save_causal_forward_capture(_complete_capture())

    assert result.status == "frozen"
    assert any(getattr(statement, "is_delete", False) for statement, _ in session.calls)


def test_blocked_v2_scope_cannot_be_promoted_on_a_later_day(monkeypatch) -> None:
    session = FakeSession(
        _existing_scope(complete=False, fingerprint="sha256:" + "b" * 64)
    )
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(
        repository,
        "_shanghai_now",
        lambda: datetime(2026, 7, 22, 9, 0, tzinfo=SHANGHAI),
    )

    with pytest.raises(ValueError, match="natural signal date"):
        repository.save_causal_forward_capture(_complete_capture())


def test_v2_repository_rejects_the_old_three_identity_contract(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)

    with pytest.raises(ValueError, match="V2 contract version"):
        repository.save_causal_forward_capture(
            build_forward_ma5_capture(legacy_inputs())
        )

    assert session.calls == []


def test_complete_historical_capture_cannot_be_manufactured_later(
    monkeypatch,
) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(
        repository,
        "_shanghai_now",
        lambda: datetime(2026, 7, 22, 9, 0, tzinfo=SHANGHAI),
    )

    with pytest.raises(ValueError, match="natural signal date"):
        repository.save_causal_forward_capture(_complete_capture())

    assert len(session.calls) == 1
    assert getattr(session.calls[0][0], "is_select", False)


def test_terminal_v2_outcome_is_preserved(monkeypatch) -> None:
    existing = _outcome(terminal=True).iloc[0].to_dict()
    session = FakeSession([existing])
    _patch_session(monkeypatch, session)

    result = repository.save_causal_forward_outcomes(_outcome(terminal=True))

    assert result == {"inserted": 0, "updated": 0, "terminal_preserved": 1}
    assert len(session.calls) == 1


def test_nonterminal_v2_outcome_can_advance(monkeypatch) -> None:
    existing = _outcome(terminal=False).iloc[0].to_dict()
    session = FakeSession([existing])
    _patch_session(monkeypatch, session)

    result = repository.save_causal_forward_outcomes(_outcome(terminal=True))

    assert result == {"inserted": 0, "updated": 1, "terminal_preserved": 0}
    assert any(getattr(statement, "is_update", False) for statement, _ in session.calls)


def test_blocked_capture_fixture_has_one_v2_scope_and_no_candidates() -> None:
    capture = blocked_causal_forward_capture(
        source_trade_date=SOURCE_DATE,
        signal_trade_date=SIGNAL_DATE,
        attempted_at=ATTEMPTED_AT,
        reason="strict_forward_inputs_incomplete",
    )

    assert capture.rows == ()
    assert len(capture.scopes) == 1
    assert capture.scopes[0].identity_mode == FORWARD_IDENTITY_MODE


def test_input_queries_are_strict_d1_and_daily_only() -> None:
    snapshots = repository._snapshot_statements(
        SOURCE_DATE,
        attempted_at=ATTEMPTED_AT,
    )
    compiled = {name: _compiled(statement) for name, statement in snapshots.items()}

    assert "low_suction_forward_membership_snapshot_scopes" in compiled[
        "membership_scope"
    ]
    assert "low_suction_forward_membership_snapshots" in compiled["membership_rows"]
    assert "low_suction_security_snapshot_scopes" in compiled["security_scope"]
    assert "low_suction_security_snapshots" in compiled["security_rows"]
    assert "source_trade_date = '2026-07-20'" in "\n".join(compiled.values())
    assert "observed_at <=" in compiled["membership_rows"]
    assert "computed_at <=" in compiled["market_timing_panel"]

    concept_sql = _compiled(
        repository._concept_bars_statement(("BK0001",), end=SIGNAL_DATE)
    )
    stock_sql = _compiled(
        repository._stock_bars_statement(
            ("000001.SZSE",),
            start=SOURCE_DATE,
            end=SIGNAL_DATE,
        )
    )
    all_sql = "\n".join((*compiled.values(), concept_sql, stock_sql))
    assert "sector_daily_bars" in concept_sql
    assert "eastmoney.board_kline" in concept_sql
    assert "sector_daily_bars.trade_date <= '2026-07-21'" in concept_sql
    assert "stock_daily_bars" in stock_sql
    assert "stock_minute_bars" not in all_sql
    assert "stock_fund_flows" not in all_sql
    assert "sector_fund_flow" not in all_sql


def test_outcome_rebuild_continues_each_frozen_campaign_from_its_anchor() -> None:
    dates = pd.bdate_range("2026-01-05", periods=5)
    candidates = pd.DataFrame(
        [
            {
                "sector_id": sector_id,
                "vt_symbol": vt_symbol,
                "spell_anchor_date": dates[0].date(),
                "raw": {
                    "signal": {
                        "campaign_id": _campaign_id(sector_id, dates[0].date()),
                    }
                },
            }
            for sector_id, vt_symbol in (
                ("BK_OPEN", "600001.SSE"),
                ("BK_ENDED", "600002.SSE"),
            )
        ]
    )
    concept_bars = pd.DataFrame(
        [
            {
                "sector_id": sector_id,
                "concept_name": concept_name,
                "trade_date": trade_date,
                "close_price": close_price,
            }
            for sector_id, concept_name, closes in (
                ("BK_OPEN", "仍在主升", (100.0, 103.0, 105.0, 106.0, 107.0)),
                ("BK_ENDED", "确认退潮", (100.0, 110.0, 104.0, 103.0, 102.0)),
            )
            for trade_date, close_price in zip(dates, closes, strict=True)
        ]
    )

    paths = repository._reconstruct_frozen_campaign_paths(
        candidates,
        concept_bars,
    )

    endpoints = paths.loc[paths["is_endpoint"]].set_index("sector_id")
    assert endpoints["campaign_active"].to_dict() == {
        "BK_ENDED": False,
        "BK_OPEN": True,
    }
    assert endpoints["trade_date"].dt.date.to_dict() == {
        "BK_ENDED": dates[-1].date(),
        "BK_OPEN": dates[-1].date(),
    }


def test_historical_advance_settles_but_never_captures(monkeypatch) -> None:
    def fail_if_source_pair_is_loaded(_signal_date):
        raise AssertionError("historical calls must not load a source pair")

    monkeypatch.setattr(repository, "_natural_source_pair", fail_if_source_pair_is_loaded)
    monkeypatch.setattr(
        repository,
        "settle_causal_forward_outcomes",
        lambda **_kwargs: {
            "evaluated": 2,
            "inserted": 0,
            "updated": 2,
            "terminal_preserved": 0,
        },
    )

    result = repository.advance_causal_forward(
        as_of_date=SOURCE_DATE,
        attempted_at=ATTEMPTED_AT,
    )

    assert result["captures"] == []
    assert result["blocking_reasons"] == ["historical_natural_capture_forbidden"]
    assert result["outcomes"]["evaluated"] == 2
    assert result["recommendations_created"] == 0
    assert result["orders_created"] == 0


def test_outcome_selection_includes_diagnostic_only_candidates() -> None:
    three_phase = "causal-leader-pullback-three-phase-adaptive-v1"

    assert repository._candidate_requires_outcome({"signal_eligible": True})
    assert repository._candidate_requires_outcome(
        {
            "signal_eligible": False,
            "raw": {
                "diagnostic_policies": {
                    three_phase: {"signal_eligible": True},
                }
            },
        }
    )
    assert not repository._candidate_requires_outcome(
        {
            "signal_eligible": False,
            "raw": {
                "diagnostic_policies": {
                    three_phase: {"signal_eligible": False},
                }
            },
        }
    )


def test_incomplete_natural_inputs_create_an_explicit_blocked_capture(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        repository,
        "load_causal_forward_inputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("strict membership scope is unavailable")
        ),
    )

    capture = repository._capture_natural_pair(
        SOURCE_DATE,
        SIGNAL_DATE,
        attempted_at=ATTEMPTED_AT,
    )

    assert not capture.complete
    assert capture.rows == ()
    assert capture.scopes[0].raw["blocking_reason"] == (
        "strict_forward_inputs_incomplete:strict membership scope is unavailable"
    )


def test_v2_report_keeps_one_identity_and_formal_metrics_null() -> None:
    capture = _complete_capture()
    scopes = pd.DataFrame([capture.scopes[0].__dict__])
    scopes.at[0, "raw"] = {
        "signal_funnel": {
            "base_confirmation": 3,
            "warming_support_relevance": 1,
        }
    }
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    candidates.at[0, "decision_reason"] = "eligible_rotation_strong_reclaim"
    candidates.at[0, "raw"] = {
        "signal": {"market_phase": "rotation"},
        "diagnostic_policies": {
            "causal-leader-pullback-rotation-next-session-v1": {
                "signal_eligible": True,
                "registered_before_first_natural_scope": True,
            }
        },
    }
    outcomes = _outcome(terminal=True)

    report = repository.build_causal_forward_report(
        scopes,
        candidates,
        outcomes,
        as_of_date=SIGNAL_DATE,
        stock_bars=pd.DataFrame(
            [
                {
                    "vt_symbol": "000001.SZSE",
                    "trade_date": SIGNAL_DATE,
                    "close_price": 10.0,
                },
                {
                    "vt_symbol": "000001.SZSE",
                    "trade_date": date(2026, 7, 22),
                    "close_price": 10.5,
                },
            ]
        ),
    )

    assert report["contract_version"] == FORWARD_CONTRACT_VERSION
    assert report["identity_mode"] == FORWARD_IDENTITY_MODE
    assert report["forward_sample"] is True
    assert report["coverage"] == {
        "scope_rows": 1,
        "complete_signal_sessions": 1,
        "blocked_signal_sessions": 0,
        "candidate_rows": 1,
        "signal_rows": 1,
        "outcome_rows": 1,
        "closed_outcomes": 1,
    }
    assert report["signal_funnel"] == {
        "base_confirmation": 3,
        "warming_support_relevance": 1,
    }
    assert report["rejection_reason_counts"] == {
        "eligible_rotation_strong_reclaim": 1
    }
    assert report["formal_metrics"] is None
    diagnostic = report["diagnostic_policies"][
        "causal-leader-pullback-rotation-next-session-v1"
    ]
    assert diagnostic["coverage"] == {
        "candidate_rows": 1,
        "closed_outcomes": 1,
        "candidate_market_phases": {"rotation": 1},
        "closed_market_phases": {"rotation": 1},
    }
    assert diagnostic["qualification"] == {
        "sample_gates_passed": False,
        "performance_gates_passed": False,
        "confidence_gates_passed": True,
        "all_gates_passed": False,
        "failed_gates": [
            "closed_outcomes<40",
            "closed_rotation<20",
            "closed_warming<20",
            "warming_win_rate<=60pct",
            "warming_mean_return<=0",
            "four_slot_cash_compound<=60pct",
        ],
    }
    assert diagnostic["four_slot_cash"]["closed_trades"] == 1
    assert diagnostic["four_slot_cash"]["cash_win_rate_pct"] == 100.0
    assert diagnostic["research_status"] == "accumulating_natural_forward"
    assert diagnostic["verified_forward_metrics"] is None
    assert diagnostic["formal_metrics"] is None


def test_diagnostic_publishes_verified_metrics_only_after_all_gates_pass() -> None:
    entry_dates = pd.bdate_range("2026-01-05", periods=40)
    candidates: list[dict[str, object]] = []
    outcomes: list[dict[str, object]] = []
    bars: list[dict[str, object]] = []
    policy = "causal-leader-pullback-rotation-next-session-v1"
    for index, entry in enumerate(entry_dates):
        entry_date = entry.date()
        exit_date = (entry + pd.offsets.BDay(1)).date()
        symbol = f"600{index:03d}.SSE"
        signal_id = f"signal-{index:03d}"
        phase = "rotation" if index < 20 else "warming"
        candidates.append(
            {
                "signal_trade_date": entry_date,
                "vt_symbol": symbol,
                "sector_id": f"BK{index:04d}",
                "rank": index % 3 + 1,
                "raw": {
                    "signal": {
                        "signal_id": signal_id,
                        "market_phase": phase,
                    },
                    "diagnostic_policies": {
                        policy: {"signal_eligible": True}
                    },
                },
            }
        )
        outcomes.append(
            {
                "signal_trade_date": entry_date,
                "vt_symbol": symbol,
                "entry_date": entry_date,
                "entry_price": 10.0,
                "exit_date": exit_date,
                "net_return_pct": 10.0,
            }
        )
        bars.extend(
            [
                {
                    "vt_symbol": symbol,
                    "trade_date": entry_date,
                    "close_price": 10.0,
                },
                {
                    "vt_symbol": symbol,
                    "trade_date": exit_date,
                    "close_price": 11.0,
                },
            ]
        )

    diagnostic = repository._build_rotation_next_session_forward_diagnostic(
        pd.DataFrame(candidates),
        pd.DataFrame(outcomes),
        stock_bars=pd.DataFrame(bars),
    )

    assert diagnostic["qualification"] == {
        "sample_gates_passed": True,
        "performance_gates_passed": True,
        "confidence_gates_passed": True,
        "all_gates_passed": True,
        "failed_gates": [],
    }
    assert diagnostic["research_status"] == (
        "forward_qualified_candidate_for_review"
    )
    assert diagnostic["verified_forward_metrics"]["closed"] == 40
    assert diagnostic["verified_forward_metrics"]["four_slot_cash"][
        "compound_return_pct"
    ] > 60.0
    assert diagnostic["recommendations_created"] == 0
    assert diagnostic["orders_created"] == 0

    failed = repository._build_rotation_next_session_forward_diagnostic(
        pd.DataFrame(candidates),
        pd.DataFrame(outcomes).assign(net_return_pct=-10.0),
        stock_bars=pd.DataFrame(bars),
    )
    assert failed["qualification"]["sample_gates_passed"] is True
    assert failed["qualification"]["performance_gates_passed"] is False
    assert failed["qualification"]["all_gates_passed"] is False
    assert failed["research_status"] == "forward_performance_below_gate"
    assert failed["verified_forward_metrics"] is None


def test_three_phase_diagnostic_requires_uptrend_rotation_and_warming() -> None:
    policy = "causal-leader-pullback-three-phase-adaptive-v1"
    phases = ["uptrend"] * 10 + ["rotation"] * 20 + ["warming"] * 20
    candidates: list[dict[str, object]] = []
    outcomes: list[dict[str, object]] = []
    bars: list[dict[str, object]] = []
    for index, (entry, phase) in enumerate(
        zip(pd.bdate_range("2026-01-05", periods=50), phases, strict=True)
    ):
        entry_date = entry.date()
        exit_date = (entry + pd.offsets.BDay(1)).date()
        symbol = f"601{index:03d}.SSE"
        candidates.append(
            {
                "signal_trade_date": entry_date,
                "vt_symbol": symbol,
                "sector_id": f"BK{index:04d}",
                "rank": index % 3 + 1,
                "raw": {
                    "signal": {
                        "signal_id": f"three-phase-{index:03d}",
                        "market_phase": phase,
                    },
                    "diagnostic_policies": {
                        policy: {
                            "signal_eligible": True,
                            "qualification_contract_version": (
                                "three-phase-natural-qualification-wilson-v1"
                            ),
                        }
                    },
                },
            }
        )
        outcomes.append(
            {
                "signal_trade_date": entry_date,
                "vt_symbol": symbol,
                "entry_date": entry_date,
                "entry_price": 10.0,
                "exit_date": exit_date,
                "net_return_pct": 10.0,
            }
        )
        bars.extend(
            [
                {"vt_symbol": symbol, "trade_date": entry_date, "close_price": 10.0},
                {"vt_symbol": symbol, "trade_date": exit_date, "close_price": 11.0},
            ]
        )

    diagnostic = repository._build_three_phase_forward_diagnostic(
        pd.DataFrame(candidates),
        pd.DataFrame(outcomes),
        stock_bars=pd.DataFrame(bars),
    )

    assert diagnostic["qualification"] == {
        "sample_gates_passed": True,
        "performance_gates_passed": True,
        "confidence_gates_passed": True,
        "all_gates_passed": True,
        "failed_gates": [],
    }
    assert diagnostic["qualification_contract_version"] == (
        "three-phase-natural-qualification-wilson-v1"
    )
    assert diagnostic["verified_forward_metrics"]["closed"] == 50
    assert diagnostic["verified_forward_metrics"]["market_phase_metrics"][
        "uptrend"
    ]["closed"] == 10

    weak_confidence_outcomes = pd.DataFrame(outcomes)
    weak_confidence_outcomes.loc[:2, "net_return_pct"] = -1.0
    weak_confidence = repository._build_three_phase_forward_diagnostic(
        pd.DataFrame(candidates),
        weak_confidence_outcomes,
        stock_bars=pd.DataFrame(bars),
    )

    assert weak_confidence["market_phase_metrics"]["uptrend"]["win_rate_pct"] == 70.0
    assert weak_confidence["qualification"]["sample_gates_passed"] is True
    assert weak_confidence["qualification"]["performance_gates_passed"] is True
    assert weak_confidence["qualification"]["confidence_gates_passed"] is False
    assert weak_confidence["qualification"]["all_gates_passed"] is False
    assert weak_confidence["qualification"]["failed_gates"] == [
        "uptrend_wilson_95_lower<=60pct"
    ]
    assert weak_confidence["research_status"] == "forward_performance_below_gate"
    assert weak_confidence["verified_forward_metrics"] is None

    candidates[0]["raw"]["diagnostic_policies"][policy][
        "qualification_contract_version"
    ] = "stale-contract"
    with pytest.raises(ValueError, match="qualification contract version mismatch"):
        repository._build_three_phase_forward_diagnostic(
            pd.DataFrame(candidates),
            pd.DataFrame(outcomes),
            stock_bars=pd.DataFrame(bars),
        )
