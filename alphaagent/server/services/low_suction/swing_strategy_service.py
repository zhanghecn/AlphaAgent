"""Lifecycle orchestration for the low-suction swing paper strategy."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

from . import swing_strategy_market_data as market_data
from . import swing_strategy_repository as repository
from .swing_paper_portfolio import (
    PaperPortfolioInputError,
    detect_exit_triggers,
    plan_entry_fills,
    plan_exit_fills,
)
from .swing_strategy import (
    STRATEGY_VERSION,
    SwingSignalInputError,
    build_swing_signal_capture,
)
from .swing_strategy_market_data import SwingMarketDataError
from .swing_strategy_overview import get_swing_strategy_overview
from .swing_strategy_repository import SwingContextUnavailable


SHANGHAI = ZoneInfo("Asia/Shanghai")
__all__ = (
    "capture_swing_preview",
    "capture_swing_signals",
    "fill_swing_entries",
    "fill_swing_exits",
    "get_swing_strategy_overview",
    "settle_swing_positions",
)


def capture_swing_preview(
    *,
    now: datetime | None = None,
    adapter: Any | None = None,
) -> dict[str, object]:
    """Publish a replaceable intraday warning without creating a position."""

    observed_at = _local_now(now)
    if _is_weekend(observed_at):
        return _market_closed_result(observed_at, phase=repository.PREVIEW_PHASE)
    source_date: date | None = None
    try:
        context = repository.load_signal_static_context(
            signal_trade_date=observed_at.date(),
            captured_at=observed_at,
        )
        source_date = context.source_trade_date
        snapshot = market_data.collect_signal_market_snapshot(
            context.leader_rows,
            captured_at=observed_at,
            adapter=adapter,
        )
        capture = build_swing_signal_capture(
            context.with_live_quotes(
                stock_quotes=snapshot.stock_quotes,
                concept_quotes=snapshot.concept_quotes,
                benchmark_quotes=snapshot.benchmark_quotes,
            ),
            preview=True,
        )
        saved = repository.save_signal_preview(capture)
    except (SwingContextUnavailable, SwingMarketDataError, SwingSignalInputError) as exc:
        reason = _error_code(exc)
        repository.save_blocked_run(
            trade_date=observed_at.date(),
            phase=repository.PREVIEW_PHASE,
            attempted_at=observed_at,
            source_trade_date=source_date,
            blocking_reasons=[reason],
            raw={"message": str(exc)},
        )
        return _blocked_result(
            observed_at,
            phase=repository.PREVIEW_PHASE,
            reasons=[reason],
        )
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": repository.PREVIEW_PHASE,
        "trade_date": observed_at.date().isoformat(),
        "source_trade_date": capture.source_trade_date.isoformat(),
        "status": "preview_ready" if saved.status != "final_preserved" else "final_preserved",
        "save_status": saved.status,
        "candidate_rows": len(capture.candidates),
        "recommendations_created": capture.recommendation_count,
        "positions_opened": 0,
        "positions_closed": 0,
        "broker_orders_created": 0,
        "input_fingerprint": capture.input_fingerprint,
        "blocking_reasons": [],
    }


def capture_swing_signals(
    *,
    now: datetime | None = None,
    adapter: Any | None = None,
) -> dict[str, object]:
    """Freeze D-1 Top3 based recommendations from a causal D 14:50 snapshot."""

    observed_at = _local_now(now)
    if _is_weekend(observed_at):
        return _market_closed_result(observed_at, phase=repository.SIGNAL_PHASE)
    source_date: date | None = None
    try:
        context = repository.load_signal_static_context(
            signal_trade_date=observed_at.date(),
            captured_at=observed_at,
        )
        source_date = context.source_trade_date
        snapshot = market_data.collect_signal_market_snapshot(
            context.leader_rows,
            captured_at=observed_at,
            adapter=adapter,
        )
        capture = build_swing_signal_capture(
            context.with_live_quotes(
                stock_quotes=snapshot.stock_quotes,
                concept_quotes=snapshot.concept_quotes,
                benchmark_quotes=snapshot.benchmark_quotes,
            )
        )
        saved = repository.save_signal_capture(capture)
    except (SwingContextUnavailable, SwingMarketDataError, SwingSignalInputError) as exc:
        reason = _error_code(exc)
        repository.save_blocked_run(
            trade_date=observed_at.date(),
            phase=repository.SIGNAL_PHASE,
            attempted_at=observed_at,
            source_trade_date=source_date,
            blocking_reasons=[reason],
            raw={"message": str(exc)},
        )
        return _blocked_result(
            observed_at,
            phase=repository.SIGNAL_PHASE,
            reasons=[reason],
        )
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": repository.SIGNAL_PHASE,
        "trade_date": observed_at.date().isoformat(),
        "source_trade_date": capture.source_trade_date.isoformat(),
        "status": "ready",
        "save_status": saved.status,
        "candidate_rows": len(capture.candidates),
        "recommendations_created": capture.recommendation_count,
        "positions_opened": 0,
        "positions_closed": 0,
        "broker_orders_created": 0,
        "input_fingerprint": capture.input_fingerprint,
        "blocking_reasons": [],
    }


def fill_swing_entries(
    *,
    now: datetime | None = None,
    adapter: Any | None = None,
) -> dict[str, object]:
    """Fill frozen recommendations in the paper account from post-signal quotes."""

    observed_at = _local_now(now)
    if _is_weekend(observed_at):
        return _market_closed_result(observed_at, phase=repository.ENTRY_PHASE)
    signal_run = repository.load_run(
        trade_date=observed_at.date(),
        phase=repository.SIGNAL_PHASE,
    )
    if not signal_run or not bool(signal_run.get("complete")):
        return _save_and_return_blocked(
            observed_at,
            phase=repository.ENTRY_PHASE,
            reasons=["signal_capture_not_ready"],
        )
    try:
        signals = repository.load_recommended_signals(trade_date=observed_at.date())
        positions = repository.load_positions()
        trades = repository.load_trades()
        required_symbols = set(
            signals.get("vt_symbol", pd.Series(dtype=str)).astype(str)
        )
        if not positions.empty:
            active = positions.loc[
                positions["status"].isin(repository.OPEN_POSITION_STATUSES)
            ]
            required_symbols.update(active["vt_symbol"].astype(str))
        quotes = market_data.collect_stock_quotes(required_symbols, adapter=adapter)
        decisions = plan_entry_fills(
            signals,
            positions,
            trades,
            quotes,
            captured_at=observed_at,
        )
        saved = repository.save_entry_decisions(
            trade_date=observed_at.date(),
            attempted_at=observed_at,
            decisions=decisions,
        )
    except (SwingMarketDataError, PaperPortfolioInputError) as exc:
        return _save_and_return_blocked(
            observed_at,
            phase=repository.ENTRY_PHASE,
            reasons=[_error_code(exc)],
            message=str(exc),
        )
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": repository.ENTRY_PHASE,
        "trade_date": observed_at.date().isoformat(),
        "status": str(saved.get("status") or "complete"),
        "recommendations_read": len(signals),
        "positions_opened": sum(decision.status == "filled" for decision in decisions),
        "positions_closed": 0,
        "rejected_entries": sum(
            decision.status == "rejected" for decision in decisions
        ),
        "broker_orders_created": 0,
        "blocking_reasons": [],
    }


def settle_swing_positions(
    *,
    as_of_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Mark structural triggers from completed daily bars without selling yet."""

    observed_at = _local_now(now)
    requested_cutoff = as_of_date or completed_daily_bar_cutoff(observed_at)
    cutoff = (
        requested_cutoff
        if as_of_date is not None
        else repository.latest_complete_daily_date(as_of_date=requested_cutoff)
    )
    if cutoff is None:
        return _save_and_return_blocked(
            observed_at,
            phase=repository.SETTLEMENT_PHASE,
            reasons=["complete_daily_session_missing"],
        )
    positions = repository.load_positions(statuses=("open",))
    bars = repository.load_position_daily_bars(positions, as_of_date=cutoff)
    decisions = (
        detect_exit_triggers(positions, bars, as_of_date=cutoff)
        if not positions.empty
        else ()
    )
    marks = _latest_position_marks(positions, bars, as_of_date=cutoff)
    saved = repository.save_exit_triggers(
        as_of_date=cutoff,
        attempted_at=observed_at,
        decisions=decisions,
        marks=marks,
    )
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": repository.SETTLEMENT_PHASE,
        "trade_date": cutoff.isoformat(),
        "status": str(saved.get("status") or "complete"),
        "open_positions_read": len(positions),
        "positions_marked": len(marks),
        "triggers_created": len(decisions),
        "positions_opened": 0,
        "positions_closed": 0,
        "broker_orders_created": 0,
        "blocking_reasons": [],
    }


def fill_swing_exits(
    *,
    now: datetime | None = None,
    adapter: Any | None = None,
) -> dict[str, object]:
    """Fill previously triggered exits from the next session opening price."""

    observed_at = _local_now(now)
    if _is_weekend(observed_at):
        return _market_closed_result(observed_at, phase=repository.EXIT_PHASE)
    try:
        positions = repository.load_positions(statuses=("exit_pending",))
        required_symbols = set(
            positions.get("vt_symbol", pd.Series(dtype=str)).astype(str)
        )
        quotes = market_data.collect_stock_quotes(required_symbols, adapter=adapter)
        decisions = plan_exit_fills(
            positions,
            quotes,
            captured_at=observed_at,
        )
        saved = repository.save_exit_decisions(
            trade_date=observed_at.date(),
            attempted_at=observed_at,
            decisions=decisions,
        )
    except (SwingMarketDataError, PaperPortfolioInputError) as exc:
        return _save_and_return_blocked(
            observed_at,
            phase=repository.EXIT_PHASE,
            reasons=[_error_code(exc)],
            message=str(exc),
        )
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": repository.EXIT_PHASE,
        "trade_date": observed_at.date().isoformat(),
        "status": str(saved.get("status") or "complete"),
        "pending_positions_read": len(positions),
        "positions_opened": 0,
        "positions_closed": sum(
            decision.status == "filled" for decision in decisions
        ),
        "deferred_exits": sum(
            decision.status == "deferred" for decision in decisions
        ),
        "broker_orders_created": 0,
        "blocking_reasons": [],
    }


def _latest_position_marks(
    positions: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    as_of_date: date,
) -> dict[str, float]:
    if positions.empty or bars.empty:
        return {}
    required_position_columns = {"signal_id", "vt_symbol"}
    required_bar_columns = {"vt_symbol", "trade_date", "close_price"}
    if not required_position_columns.issubset(positions.columns):
        return {}
    if not required_bar_columns.issubset(bars.columns):
        return {}
    current = bars.copy()
    current["trade_date"] = pd.to_datetime(
        current["trade_date"], errors="coerce"
    ).dt.date
    current = current.loc[current["trade_date"].eq(as_of_date)].copy()
    if current.empty:
        return {}
    current["close_price"] = pd.to_numeric(
        current["close_price"], errors="coerce"
    )
    close_by_symbol = (
        current.dropna(subset=["close_price"])
        .drop_duplicates("vt_symbol", keep="last")
        .set_index("vt_symbol")["close_price"]
    )
    return {
        str(row.signal_id): float(close_by_symbol.loc[str(row.vt_symbol)])
        for row in positions.itertuples(index=False)
        if str(row.vt_symbol) in close_by_symbol
        and float(close_by_symbol.loc[str(row.vt_symbol)]) > 0
    }


def _save_and_return_blocked(
    observed_at: datetime,
    *,
    phase: str,
    reasons: list[str],
    message: str | None = None,
) -> dict[str, object]:
    repository.save_blocked_run(
        trade_date=observed_at.date(),
        phase=phase,
        attempted_at=observed_at,
        blocking_reasons=reasons,
        raw={"message": message} if message else {},
    )
    return _blocked_result(observed_at, phase=phase, reasons=reasons)


def _blocked_result(
    observed_at: datetime,
    *,
    phase: str,
    reasons: list[str],
) -> dict[str, object]:
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": phase,
        "trade_date": observed_at.date().isoformat(),
        "status": "blocked",
        "candidate_rows": 0,
        "recommendations_created": 0,
        "positions_opened": 0,
        "positions_closed": 0,
        "broker_orders_created": 0,
        "blocking_reasons": reasons,
    }


def _market_closed_result(observed_at: datetime, *, phase: str) -> dict[str, object]:
    return {
        "strategy_version": STRATEGY_VERSION,
        "phase": phase,
        "trade_date": observed_at.date().isoformat(),
        "status": "market_closed",
        "candidate_rows": 0,
        "recommendations_created": 0,
        "positions_opened": 0,
        "positions_closed": 0,
        "broker_orders_created": 0,
        "blocking_reasons": [],
    }


def _local_now(value: datetime | None) -> datetime:
    observed = value or datetime.now(SHANGHAI)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("swing strategy time must be timezone-aware")
    return observed.astimezone(SHANGHAI)


def _is_weekend(value: datetime) -> bool:
    return value.weekday() >= 5


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code:
        return str(code)
    normalized = re.sub(r"[^a-z0-9]+", "_", str(exc).lower()).strip("_")
    return normalized or exc.__class__.__name__.lower()
