"""Persistence and read models for the low-suction swing paper strategy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, insert, select, update

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
from .forward_leader_identity import FORWARD_LEADER_RANKING_VERSION
from .swing_paper_portfolio import (
    EntryFillDecision,
    ExitFillDecision,
    ExitTriggerDecision,
)
from .swing_strategy import (
    IDENTITY_MODE,
    STRATEGY_VERSION,
    SwingSignalCapture,
    SwingStrategyInputs,
)


SIGNAL_PHASE = "signal_1450"
PREVIEW_PHASE = "signal_preview"
ENTRY_PHASE = "entry_1455"
EXIT_PHASE = "exit_open"
SETTLEMENT_PHASE = "settlement_eod"
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3_000
STATIC_HISTORY_SESSIONS = 100
OPEN_POSITION_STATUSES = ("open", "exit_pending")


class SwingContextUnavailable(RuntimeError):
    """Raised when the D-1 static strategy scope is incomplete."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class SwingStrategyImmutableError(RuntimeError):
    """Raised when complete point-in-time strategy evidence would be rewritten."""


@dataclass(frozen=True)
class SignalCaptureSaveResult:
    status: str
    rows_written: int
    input_fingerprint: str


@dataclass(frozen=True)
class SwingSignalStaticContext:
    source_trade_date: date
    signal_trade_date: date
    captured_at: datetime
    leader_rows: pd.DataFrame
    leader_history: pd.DataFrame
    stock_bars: pd.DataFrame
    concept_bars: pd.DataFrame
    benchmark_bars: pd.DataFrame
    completed_dates: tuple[date, ...]
    open_positions: pd.DataFrame

    def with_live_quotes(
        self,
        *,
        stock_quotes: pd.DataFrame,
        concept_quotes: pd.DataFrame,
        benchmark_quotes: pd.DataFrame,
    ) -> SwingStrategyInputs:
        return SwingStrategyInputs(
            source_trade_date=self.source_trade_date,
            signal_trade_date=self.signal_trade_date,
            captured_at=self.captured_at,
            leader_rows=self.leader_rows,
            leader_history=self.leader_history,
            stock_bars=self.stock_bars,
            concept_bars=self.concept_bars,
            benchmark_bars=self.benchmark_bars,
            stock_quotes=stock_quotes,
            concept_quotes=concept_quotes,
            benchmark_quotes=benchmark_quotes,
            completed_dates=self.completed_dates,
            open_positions=self.open_positions,
        )


def save_signal_capture(capture: SwingSignalCapture) -> SignalCaptureSaveResult:
    """Freeze one complete 14:50 capture; a prior blocked run may recover."""

    _validate_signal_capture(capture)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    runs = schema.low_suction_strategy_runs
    signals = schema.low_suction_strategy_signals
    with session_scope() as session:
        existing = session.execute(
            select(runs.c.complete, runs.c.input_fingerprint).where(
                runs.c.strategy_version == capture.strategy_version,
                runs.c.trade_date == capture.signal_trade_date,
                runs.c.phase == SIGNAL_PHASE,
            )
        ).mappings().all()
        decision = _existing_complete_run_decision(existing, capture.input_fingerprint)
        if decision is not None:
            return SignalCaptureSaveResult(
                status=decision,
                rows_written=0,
                input_fingerprint=capture.input_fingerprint,
            )
        session.execute(
            delete(signals).where(
                signals.c.strategy_version == capture.strategy_version,
                signals.c.signal_trade_date == capture.signal_trade_date,
            )
        )
        if existing:
            session.execute(
                delete(runs).where(
                    runs.c.strategy_version == capture.strategy_version,
                    runs.c.trade_date == capture.signal_trade_date,
                    runs.c.phase == SIGNAL_PHASE,
                )
            )
        session.execute(
            delete(runs).where(
                runs.c.strategy_version == capture.strategy_version,
                runs.c.trade_date == capture.signal_trade_date,
                runs.c.phase == PREVIEW_PHASE,
            )
        )
        if capture.candidates:
            session.execute(
                insert(signals),
                [asdict(candidate) for candidate in capture.candidates],
            )
        session.execute(insert(runs).values(**_capture_run_values(capture)))
    return SignalCaptureSaveResult(
        status="frozen",
        rows_written=len(capture.candidates),
        input_fingerprint=capture.input_fingerprint,
    )


def save_signal_preview(capture: SwingSignalCapture) -> SignalCaptureSaveResult:
    """Replace today's mutable preview unless the 14:50 capture is frozen."""

    _validate_signal_capture(capture)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    runs = schema.low_suction_strategy_runs
    signals = schema.low_suction_strategy_signals
    with session_scope() as session:
        final = session.execute(
            select(runs.c.complete).where(
                runs.c.strategy_version == capture.strategy_version,
                runs.c.trade_date == capture.signal_trade_date,
                runs.c.phase == SIGNAL_PHASE,
            )
        ).mappings().all()
        if any(bool(row.get("complete")) for row in final):
            return SignalCaptureSaveResult(
                status="final_preserved",
                rows_written=0,
                input_fingerprint=capture.input_fingerprint,
            )
        session.execute(
            delete(signals).where(
                signals.c.strategy_version == capture.strategy_version,
                signals.c.signal_trade_date == capture.signal_trade_date,
            )
        )
        session.execute(
            delete(runs).where(
                runs.c.strategy_version == capture.strategy_version,
                runs.c.trade_date == capture.signal_trade_date,
                runs.c.phase == PREVIEW_PHASE,
            )
        )
        if capture.candidates:
            session.execute(
                insert(signals),
                [asdict(candidate) for candidate in capture.candidates],
            )
        session.execute(
            insert(runs).values(
                **_capture_run_values(capture, phase=PREVIEW_PHASE)
            )
        )
    return SignalCaptureSaveResult(
        status="preview_replaced",
        rows_written=len(capture.candidates),
        input_fingerprint=capture.input_fingerprint,
    )


def save_blocked_run(
    *,
    trade_date: date,
    phase: str,
    attempted_at: datetime,
    blocking_reasons: Sequence[str],
    source_trade_date: date | None = None,
    raw: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Persist an explicit blocker unless a complete phase is already frozen."""

    reasons = tuple(sorted({str(reason) for reason in blocking_reasons if reason}))
    fingerprint = _blocked_fingerprint(
        trade_date=trade_date,
        phase=phase,
        source_trade_date=source_trade_date,
        blocking_reasons=reasons,
    )
    engine = get_engine()
    schema.ensure_schema_once(engine)
    runs = schema.low_suction_strategy_runs
    with session_scope() as session:
        existing = session.execute(
            select(runs.c.complete, runs.c.input_fingerprint).where(
                runs.c.strategy_version == STRATEGY_VERSION,
                runs.c.trade_date == trade_date,
                runs.c.phase == phase,
            )
        ).mappings().all()
        if len(existing) > 1:
            raise SwingStrategyImmutableError("strategy run identity is duplicated")
        if existing and bool(existing[0].get("complete")):
            return {
                "status": "complete_preserved",
                "input_fingerprint": str(existing[0].get("input_fingerprint") or ""),
            }
        values = {
            "strategy_version": STRATEGY_VERSION,
            "trade_date": trade_date,
            "phase": phase,
            "source_trade_date": source_trade_date,
            "attempted_at": attempted_at,
            "feature_cutoff_at": None,
            "status": "blocked",
            "complete": False,
            "candidate_count": 0,
            "recommendation_count": 0,
            "positions_opened": 0,
            "positions_closed": 0,
            "input_fingerprint": fingerprint,
            "blocking_reasons": list(reasons),
            "raw": dict(raw or {}),
        }
        if existing:
            session.execute(
                delete(runs).where(
                    runs.c.strategy_version == STRATEGY_VERSION,
                    runs.c.trade_date == trade_date,
                    runs.c.phase == phase,
                )
            )
        session.execute(insert(runs).values(**values))
    return {"status": "blocked", "input_fingerprint": fingerprint}


def load_signal_static_context(
    *,
    signal_trade_date: date,
    captured_at: datetime,
) -> SwingSignalStaticContext:
    """Load the latest complete and still-unbound D-1 Top3 strategy scope."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    completed_statement = (
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date < signal_trade_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
            >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
        )
        .order_by(schema.stock_daily_bars.c.trade_date.desc())
        .limit(STATIC_HISTORY_SESSIONS)
    )
    with session_scope() as session:
        completed_desc = tuple(session.execute(completed_statement).scalars())
        if not completed_desc:
            raise SwingContextUnavailable("completed_d_minus_one_session_missing")
        source_date = completed_desc[0]
        scope_rows = session.execute(
            select(schema.low_suction_forward_leader_rank_snapshot_scopes).where(
                schema.low_suction_forward_leader_rank_snapshot_scopes.c.source_trade_date
                == source_date,
                schema.low_suction_forward_leader_rank_snapshot_scopes.c.ranking_version
                == FORWARD_LEADER_RANKING_VERSION,
                schema.low_suction_forward_leader_rank_snapshot_scopes.c.identity_mode
                == IDENTITY_MODE,
                schema.low_suction_forward_leader_rank_snapshot_scopes.c.complete.is_(True),
            )
        ).mappings().all()
        _validate_signal_scope(scope_rows, captured_at=captured_at)
        leader_rows = session.execute(
            select(schema.low_suction_forward_leader_rank_snapshots).where(
                schema.low_suction_forward_leader_rank_snapshots.c.source_trade_date
                == source_date,
                schema.low_suction_forward_leader_rank_snapshots.c.ranking_version
                == FORWARD_LEADER_RANKING_VERSION,
                schema.low_suction_forward_leader_rank_snapshots.c.identity_mode
                == IDENTITY_MODE,
                schema.low_suction_forward_leader_rank_snapshots.c.is_top3.is_(True),
            )
        ).mappings().all()
        if not leader_rows:
            raise SwingContextUnavailable("d_minus_one_top3_missing")
        history_start = min(completed_desc)
        leader_history = session.execute(
            select(schema.low_suction_forward_leader_rank_snapshots).where(
                schema.low_suction_forward_leader_rank_snapshots.c.source_trade_date.between(
                    history_start,
                    source_date,
                ),
                schema.low_suction_forward_leader_rank_snapshots.c.ranking_version
                == FORWARD_LEADER_RANKING_VERSION,
                schema.low_suction_forward_leader_rank_snapshots.c.identity_mode
                == IDENTITY_MODE,
                schema.low_suction_forward_leader_rank_snapshots.c.is_top3.is_(True),
            )
        ).mappings().all()
        open_positions = session.execute(
            select(schema.low_suction_paper_positions).where(
                schema.low_suction_paper_positions.c.strategy_version
                == STRATEGY_VERSION,
                schema.low_suction_paper_positions.c.status.in_(OPEN_POSITION_STATUSES),
            )
        ).mappings().all()

    leaders = pd.DataFrame(leader_rows)
    symbols = tuple(sorted(leaders["vt_symbol"].astype(str).unique()))
    sectors = tuple(sorted(leaders["sector_id"].astype(str).unique()))
    completed_dates = tuple(sorted(completed_desc))
    with session_scope() as session:
        stock_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.open_price,
                schema.stock_daily_bars.c.high_price,
                schema.stock_daily_bars.c.low_price,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.volume,
                schema.stock_daily_bars.c.turnover,
                schema.stock_daily_bars.c.change_pct,
                schema.stock_daily_bars.c.source,
            ).where(
                schema.stock_daily_bars.c.vt_symbol.in_(symbols),
                schema.stock_daily_bars.c.trade_date.in_(completed_dates),
            )
        ).mappings().all()
        concept_rows = session.execute(
            select(
                schema.sector_daily_bars.c.sector_id,
                schema.sectors.c.name.label("concept_name"),
                schema.sector_daily_bars.c.trade_date,
                schema.sector_daily_bars.c.close_price,
                schema.sector_daily_bars.c.source,
            )
            .select_from(
                schema.sector_daily_bars.join(
                    schema.sectors,
                    schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
                )
            )
            .where(
                schema.sector_daily_bars.c.sector_id.in_(sectors),
                schema.sector_daily_bars.c.trade_date.in_(completed_dates),
                schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            )
        ).mappings().all()
        benchmark_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.source,
            ).where(
                schema.stock_daily_bars.c.vt_symbol.in_(
                    ("000300.SSE", "000905.SSE", "000852.SSE")
                ),
                schema.stock_daily_bars.c.trade_date.in_(completed_dates),
            )
        ).mappings().all()
    return SwingSignalStaticContext(
        source_trade_date=source_date,
        signal_trade_date=signal_trade_date,
        captured_at=captured_at,
        leader_rows=leaders,
        leader_history=pd.DataFrame(leader_history),
        stock_bars=pd.DataFrame(stock_rows),
        concept_bars=pd.DataFrame(concept_rows),
        benchmark_bars=pd.DataFrame(benchmark_rows),
        completed_dates=completed_dates,
        open_positions=pd.DataFrame(
            open_positions,
            columns=schema.low_suction_paper_positions.c.keys(),
        ),
    )


def load_recommended_signals(*, trade_date: date) -> pd.DataFrame:
    return _read_table(
        select(schema.low_suction_strategy_signals)
        .where(
            schema.low_suction_strategy_signals.c.strategy_version
            == STRATEGY_VERSION,
            schema.low_suction_strategy_signals.c.signal_trade_date == trade_date,
            schema.low_suction_strategy_signals.c.recommendation_state
            == "recommended",
        )
        .order_by(
            schema.low_suction_strategy_signals.c.rank,
            schema.low_suction_strategy_signals.c.signal_id,
        )
    )


def load_run(*, trade_date: date, phase: str) -> dict[str, Any] | None:
    engine = get_engine()
    schema.ensure_schema_once(engine)
    with session_scope() as session:
        row = session.execute(
            select(schema.low_suction_strategy_runs).where(
                schema.low_suction_strategy_runs.c.strategy_version
                == STRATEGY_VERSION,
                schema.low_suction_strategy_runs.c.trade_date == trade_date,
                schema.low_suction_strategy_runs.c.phase == phase,
            )
        ).mappings().one_or_none()
    return dict(row) if row else None


def load_runs_for_date(*, trade_date: date) -> pd.DataFrame:
    table = schema.low_suction_strategy_runs
    return _read_table(
        select(table)
        .where(
            table.c.strategy_version == STRATEGY_VERSION,
            table.c.trade_date == trade_date,
        )
        .order_by(table.c.attempted_at, table.c.phase)
    )


def load_signal_candidates(*, trade_date: date) -> pd.DataFrame:
    table = schema.low_suction_strategy_signals
    return _read_table(
        select(table)
        .where(
            table.c.strategy_version == STRATEGY_VERSION,
            table.c.signal_trade_date == trade_date,
        )
        .order_by(table.c.rank, table.c.vt_symbol, table.c.sector_id)
    )


def load_latest_unfilled_recommendations(*, before_date: date) -> pd.DataFrame:
    """Load the latest persisted recommendation set that was never filled."""

    table = schema.low_suction_strategy_signals
    latest_date = (
        select(func.max(table.c.signal_trade_date))
        .where(
            table.c.strategy_version == STRATEGY_VERSION,
            table.c.signal_trade_date < before_date,
            table.c.recommendation_state == "recommended",
        )
        .scalar_subquery()
    )
    return _read_table(
        select(table)
        .where(
            table.c.strategy_version == STRATEGY_VERSION,
            table.c.signal_trade_date == latest_date,
            table.c.recommendation_state == "recommended",
        )
        .order_by(table.c.rank, table.c.vt_symbol, table.c.sector_id)
    )


def load_positions(*, statuses: Sequence[str] | None = None) -> pd.DataFrame:
    table = schema.low_suction_paper_positions
    statement = select(table).where(table.c.strategy_version == STRATEGY_VERSION)
    if statuses is not None:
        statement = statement.where(table.c.status.in_(tuple(statuses)))
    return _read_table(statement.order_by(table.c.entry_at, table.c.signal_id))


def load_trades(*, limit: int | None = None) -> pd.DataFrame:
    table = schema.low_suction_paper_trades
    statement = (
        select(table)
        .where(table.c.strategy_version == STRATEGY_VERSION)
        .order_by(table.c.exit_at.desc(), table.c.signal_id)
    )
    if limit is not None:
        statement = statement.limit(max(int(limit), 1))
    return _read_table(statement)


def load_position_daily_bars(
    positions: pd.DataFrame,
    *,
    as_of_date: date,
) -> pd.DataFrame:
    if positions.empty:
        return pd.DataFrame()
    symbols = tuple(sorted(positions["vt_symbol"].astype(str).unique()))
    entry_dates = pd.to_datetime(positions["entry_trade_date"], errors="raise").dt.date
    start = min(entry_dates) - timedelta(days=60)
    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(start, as_of_date),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    return _read_table(statement)


def latest_complete_daily_date(*, as_of_date: date) -> date | None:
    """Return the latest full-market daily session available to settlement."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    statement = (
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date <= as_of_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
            >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
        )
        .order_by(schema.stock_daily_bars.c.trade_date.desc())
        .limit(1)
    )
    with session_scope() as session:
        return session.execute(statement).scalar_one_or_none()


def save_entry_decisions(
    *,
    trade_date: date,
    attempted_at: datetime,
    decisions: Sequence[EntryFillDecision],
) -> dict[str, object]:
    """Persist one complete 14:55 paper decision set atomically."""

    fingerprint = _decision_fingerprint(ENTRY_PHASE, trade_date, decisions)
    with _phase_write_session(
        phase=ENTRY_PHASE,
        trade_date=trade_date,
        attempted_at=attempted_at,
        input_fingerprint=fingerprint,
    ) as phase:
        if phase["preserved"]:
            return phase
        session = phase["session"]
        opened = 0
        for decision in decisions:
            state = "filled" if decision.status == "filled" else "rejected"
            session.execute(
                update(schema.low_suction_strategy_signals)
                .where(schema.low_suction_strategy_signals.c.signal_id == decision.signal_id)
                .values(
                    recommendation_state=state,
                    portfolio_reason=decision.reason,
                )
            )
            if decision.status != "filled":
                continue
            session.execute(
                insert(schema.low_suction_paper_positions).values(
                    signal_id=decision.signal_id,
                    strategy_version=decision.strategy_version,
                    vt_symbol=decision.vt_symbol,
                    stock_name=decision.stock_name,
                    sector_id=decision.sector_id,
                    sector_name=decision.sector_name,
                    status="open",
                    entry_trade_date=decision.signal_trade_date,
                    entry_at=decision.entry_at,
                    entry_quote_time=decision.quote_time,
                    entry_raw_price=decision.raw_price,
                    entry_price=decision.entry_price,
                    volume=decision.volume,
                    entry_amount=decision.entry_amount,
                    buy_fee=decision.buy_fee,
                    buy_cash_delta=decision.buy_cash_delta,
                    reference_peak_price=decision.reference_peak_price,
                    exit_trigger_date=None,
                    exit_trigger_reason=None,
                    exit_due_after=None,
                    exit_deferred_sessions=0,
                    last_mark_date=decision.signal_trade_date,
                    last_mark_price=decision.raw_price,
                    raw={
                        "quote_source": decision.quote_source,
                        "broker_order_created": False,
                    },
                )
            )
            opened += 1
        _insert_phase_run(
            session,
            phase=ENTRY_PHASE,
            trade_date=trade_date,
            attempted_at=attempted_at,
            fingerprint=fingerprint,
            positions_opened=opened,
            raw={"decision_count": len(decisions)},
        )
    return {
        "status": "complete",
        "positions_opened": opened,
        "decisions": len(decisions),
        "input_fingerprint": fingerprint,
    }


def save_exit_triggers(
    *,
    as_of_date: date,
    attempted_at: datetime,
    decisions: Sequence[ExitTriggerDecision],
    marks: Mapping[str, float],
) -> dict[str, object]:
    normalized_marks = {
        str(signal_id): float(price)
        for signal_id, price in marks.items()
        if float(price) > 0
    }
    fingerprint = _decision_fingerprint(
        SETTLEMENT_PHASE,
        as_of_date,
        decisions,
        context={"marks": dict(sorted(normalized_marks.items()))},
    )
    with _phase_write_session(
        phase=SETTLEMENT_PHASE,
        trade_date=as_of_date,
        attempted_at=attempted_at,
        input_fingerprint=fingerprint,
    ) as phase:
        if phase["preserved"]:
            return phase
        session = phase["session"]
        for signal_id, mark_price in sorted(normalized_marks.items()):
            session.execute(
                update(schema.low_suction_paper_positions)
                .where(
                    schema.low_suction_paper_positions.c.strategy_version
                    == STRATEGY_VERSION,
                    schema.low_suction_paper_positions.c.signal_id == signal_id,
                    schema.low_suction_paper_positions.c.status.in_(
                        OPEN_POSITION_STATUSES
                    ),
                )
                .values(
                    last_mark_date=as_of_date,
                    last_mark_price=mark_price,
                )
            )
        for decision in decisions:
            session.execute(
                update(schema.low_suction_paper_positions)
                .where(
                    schema.low_suction_paper_positions.c.signal_id
                    == decision.signal_id,
                    schema.low_suction_paper_positions.c.status == "open",
                )
                .values(
                    status="exit_pending",
                    exit_trigger_date=decision.trigger_date,
                    exit_trigger_reason=decision.trigger_reason,
                    exit_due_after=decision.trigger_date,
                )
            )
        _insert_phase_run(
            session,
            phase=SETTLEMENT_PHASE,
            trade_date=as_of_date,
            attempted_at=attempted_at,
            fingerprint=fingerprint,
            raw={
                "trigger_count": len(decisions),
                "mark_count": len(normalized_marks),
            },
        )
    return {
        "status": "complete",
        "triggers_created": len(decisions),
        "positions_marked": len(normalized_marks),
        "input_fingerprint": fingerprint,
    }


def save_exit_decisions(
    *,
    trade_date: date,
    attempted_at: datetime,
    decisions: Sequence[ExitFillDecision],
) -> dict[str, object]:
    fingerprint = _decision_fingerprint(EXIT_PHASE, trade_date, decisions)
    with _phase_write_session(
        phase=EXIT_PHASE,
        trade_date=trade_date,
        attempted_at=attempted_at,
        input_fingerprint=fingerprint,
    ) as phase:
        if phase["preserved"]:
            return phase
        session = phase["session"]
        closed = 0
        for decision in decisions:
            if decision.status == "deferred":
                session.execute(
                    update(schema.low_suction_paper_positions)
                    .where(
                        schema.low_suction_paper_positions.c.signal_id
                        == decision.signal_id
                    )
                    .values(exit_deferred_sessions=decision.exit_deferred_sessions)
                )
                continue
            session.execute(
                update(schema.low_suction_paper_positions)
                .where(
                    schema.low_suction_paper_positions.c.signal_id
                    == decision.signal_id
                )
                .values(
                    status="closed",
                    last_mark_date=decision.exit_trade_date,
                    last_mark_price=decision.exit_price,
                )
            )
            position = session.execute(
                select(schema.low_suction_paper_positions).where(
                    schema.low_suction_paper_positions.c.signal_id
                    == decision.signal_id
                )
            ).mappings().one()
            session.execute(
                insert(schema.low_suction_paper_trades).values(
                    signal_id=decision.signal_id,
                    strategy_version=decision.strategy_version,
                    vt_symbol=decision.vt_symbol,
                    stock_name=decision.stock_name,
                    sector_id=decision.sector_id,
                    sector_name=decision.sector_name,
                    entry_trade_date=position["entry_trade_date"],
                    entry_at=position["entry_at"],
                    entry_price=position["entry_price"],
                    volume=position["volume"],
                    entry_amount=position["entry_amount"],
                    buy_fee=position["buy_fee"],
                    buy_cash_delta=position["buy_cash_delta"],
                    exit_trigger_date=decision.trigger_date,
                    exit_trigger_reason=decision.trigger_reason,
                    exit_trade_date=decision.exit_trade_date,
                    exit_at=decision.exit_at,
                    exit_quote_time=decision.quote_time,
                    exit_raw_price=decision.raw_price,
                    exit_price=decision.exit_price,
                    exit_amount=decision.exit_amount,
                    sell_fee=decision.sell_fee,
                    sell_cash_delta=decision.sell_cash_delta,
                    total_fees=decision.total_fees,
                    net_pnl=decision.net_pnl,
                    net_return_pct=decision.net_return_pct,
                    exit_deferred_sessions=decision.exit_deferred_sessions,
                    evidence_level="strict_intraday_forward_paper",
                    raw={
                        "quote_source": decision.quote_source,
                        "broker_order_created": False,
                    },
                )
            )
            closed += 1
        _insert_phase_run(
            session,
            phase=EXIT_PHASE,
            trade_date=trade_date,
            attempted_at=attempted_at,
            fingerprint=fingerprint,
            positions_closed=closed,
            raw={"decision_count": len(decisions)},
        )
    return {
        "status": "complete",
        "positions_closed": closed,
        "decisions": len(decisions),
        "input_fingerprint": fingerprint,
    }


def _capture_run_values(
    capture: SwingSignalCapture,
    *,
    phase: str = SIGNAL_PHASE,
) -> dict[str, object]:
    return {
        "strategy_version": capture.strategy_version,
        "trade_date": capture.signal_trade_date,
        "phase": phase,
        "source_trade_date": capture.source_trade_date,
        "attempted_at": capture.captured_at,
        "feature_cutoff_at": capture.feature_cutoff_at,
        "status": capture.status,
        "complete": True,
        "candidate_count": len(capture.candidates),
        "recommendation_count": capture.recommendation_count,
        "positions_opened": 0,
        "positions_closed": 0,
        "input_fingerprint": capture.input_fingerprint,
        "blocking_reasons": [],
        "raw": {
            "execution_mode": "paper",
            "broker_orders_enabled": False,
        },
    }


def _validate_signal_scope(
    rows: Sequence[Mapping[str, Any]],
    *,
    captured_at: datetime,
) -> None:
    if len(rows) != 1:
        raise SwingContextUnavailable("d_minus_one_top3_scope_incomplete")
    row = rows[0]
    if row.get("target_trade_date") is not None:
        raise SwingContextUnavailable("d_minus_one_top3_scope_already_bound")
    if not bool(row.get("complete")):
        raise SwingContextUnavailable("d_minus_one_top3_scope_incomplete")
    for column in ("known_at", "feature_cutoff"):
        value = row.get(column)
        if value is None:
            raise SwingContextUnavailable(f"d_minus_one_{column}_missing")
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise SwingContextUnavailable(f"d_minus_one_{column}_timezone_missing")
        if timestamp > pd.Timestamp(captured_at):
            raise SwingContextUnavailable(f"d_minus_one_{column}_after_signal")


def _read_table(statement: object) -> pd.DataFrame:
    engine = get_engine()
    schema.ensure_schema_once(engine)
    return pd.read_sql(statement, engine)


@contextmanager
def _phase_write_session(
    *,
    phase: str,
    trade_date: date,
    attempted_at: datetime,
    input_fingerprint: str,
):
    del attempted_at
    engine = get_engine()
    schema.ensure_schema_once(engine)
    runs = schema.low_suction_strategy_runs
    with session_scope() as session:
        existing = session.execute(
            select(runs.c.complete, runs.c.input_fingerprint).where(
                runs.c.strategy_version == STRATEGY_VERSION,
                runs.c.trade_date == trade_date,
                runs.c.phase == phase,
            )
        ).mappings().all()
        if len(existing) > 1:
            raise SwingStrategyImmutableError("strategy phase identity is duplicated")
        if existing and bool(existing[0].get("complete")):
            yield {
                "status": "already_complete",
                "preserved": True,
                "session": session,
                "input_fingerprint": str(
                    existing[0].get("input_fingerprint") or input_fingerprint
                ),
            }
            return
        if existing:
            session.execute(
                delete(runs).where(
                    runs.c.strategy_version == STRATEGY_VERSION,
                    runs.c.trade_date == trade_date,
                    runs.c.phase == phase,
                )
            )
        yield {
            "status": "writable",
            "preserved": False,
            "session": session,
            "input_fingerprint": input_fingerprint,
        }


def _insert_phase_run(
    session: Any,
    *,
    phase: str,
    trade_date: date,
    attempted_at: datetime,
    fingerprint: str,
    positions_opened: int = 0,
    positions_closed: int = 0,
    raw: Mapping[str, Any] | None = None,
) -> None:
    session.execute(
        insert(schema.low_suction_strategy_runs).values(
            strategy_version=STRATEGY_VERSION,
            trade_date=trade_date,
            phase=phase,
            source_trade_date=None,
            attempted_at=attempted_at,
            feature_cutoff_at=None,
            status="complete",
            complete=True,
            candidate_count=0,
            recommendation_count=0,
            positions_opened=positions_opened,
            positions_closed=positions_closed,
            input_fingerprint=fingerprint,
            blocking_reasons=[],
            raw=dict(raw or {}),
        )
    )


def _decision_fingerprint(
    phase: str,
    trade_date: date,
    decisions: Sequence[object],
    *,
    context: Mapping[str, object] | None = None,
) -> str:
    payload = {
        "strategy_version": STRATEGY_VERSION,
        "phase": phase,
        "trade_date": trade_date.isoformat(),
        "decisions": [asdict(decision) for decision in decisions],
        "context": dict(context or {}),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _existing_complete_run_decision(
    existing: Sequence[Mapping[str, Any]],
    input_fingerprint: str,
) -> str | None:
    if not existing:
        return None
    if len(existing) > 1:
        raise SwingStrategyImmutableError("strategy run identity is duplicated")
    row = existing[0]
    if not bool(row.get("complete")):
        return None
    if str(row.get("input_fingerprint") or "") != input_fingerprint:
        raise SwingStrategyImmutableError(
            "complete low-suction signal fingerprint is immutable"
        )
    return "already_frozen"


def _validate_signal_capture(capture: SwingSignalCapture) -> None:
    if capture.strategy_version != STRATEGY_VERSION:
        raise ValueError("low-suction strategy version mismatch")
    if capture.status != "ready":
        raise ValueError("only ready signal captures can be frozen")
    if not capture.input_fingerprint.startswith("sha256:"):
        raise ValueError("signal capture fingerprint must use sha256")
    signal_ids = [candidate.signal_id for candidate in capture.candidates]
    if len(signal_ids) != len(set(signal_ids)):
        raise ValueError("signal candidate identity must be unique")
    for candidate in capture.candidates:
        if (
            candidate.strategy_version != capture.strategy_version
            or candidate.signal_trade_date != capture.signal_trade_date
            or candidate.source_trade_date != capture.source_trade_date
            or candidate.input_fingerprint != capture.input_fingerprint
        ):
            raise ValueError("signal candidate does not match capture")
    recommendations = sum(
        candidate.recommendation_state == "recommended"
        for candidate in capture.candidates
    )
    if recommendations != capture.recommendation_count:
        raise ValueError("signal recommendation count does not match capture")


def _blocked_fingerprint(
    *,
    trade_date: date,
    phase: str,
    source_trade_date: date | None,
    blocking_reasons: Sequence[str],
) -> str:
    payload = json.dumps(
        {
            "strategy_version": STRATEGY_VERSION,
            "trade_date": trade_date.isoformat(),
            "phase": phase,
            "source_trade_date": (
                source_trade_date.isoformat() if source_trade_date else None
            ),
            "blocking_reasons": list(blocking_reasons),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
