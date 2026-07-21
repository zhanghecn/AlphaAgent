"""Read model and forward paper metrics for the low-suction swing strategy."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from math import ceil
from numbers import Integral, Real
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.market.cache import TTLCache
from alphaagent.server.db.session import DatabaseUnavailable

from . import swing_strategy_repository as repository
from .causal_leader_pullback_forward_repository import (
    load_d2_fast_limit_shadow_summary,
)
from .swing_paper_portfolio import INITIAL_CASH
from .swing_strategy import (
    IDENTITY_MODE,
    MAX_POSITIONS,
    MAX_POSITIONS_PER_CONCEPT,
    STRATEGY_VERSION,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
FORWARD_MINIMUM_CLOSED_TRADES = 300
FORWARD_MINIMUM_WIN_RATE_PCT = 60.0
FORWARD_MINIMUM_COMPOUND_RETURN_PCT = 60.0
FORWARD_MINIMUM_MAX_DRAWDOWN_PCT = -10.0
FORWARD_MINIMUM_PROFIT_FACTOR = 1.0
OVERVIEW_CACHE_TTL_SECONDS = 5.0
LIVE_REFRESH_SECONDS = 30
SETTLEMENT_REFRESH_SECONDS = 300
LIVE_REFRESH_WINDOWS = (
    (time(9, 25), time(9, 40)),
    (time(10, 25), time(10, 40)),
    (time(11, 25), time(11, 31)),
    (time(13, 25), time(13, 40)),
    (time(14, 25), time(15, 5)),
)
SETTLEMENT_REFRESH_WINDOW = (time(18, 55), time(22, 30))
CARRY_RECOMMENDATION_WINDOW = (time(9, 15), time(10, 30))
CARRY_RECOMMENDATION_MAX_CALENDAR_DAYS = 4
REFRESH_WINDOWS = (*LIVE_REFRESH_WINDOWS, SETTLEMENT_REFRESH_WINDOW)
_OVERVIEW_CACHE = TTLCache(max_items=1, copier=copy.copy)


def get_swing_strategy_overview(
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Return the independent low-suction paper product read model."""

    observed_at = _local_now(now)
    if now is not None:
        return _build_swing_strategy_overview(observed_at)
    return _OVERVIEW_CACHE.get_or_set(
        _overview_cache_key(observed_at),
        OVERVIEW_CACHE_TTL_SECONDS,
        lambda: _build_swing_strategy_overview(observed_at),
    )


def _build_swing_strategy_overview(observed_at: datetime) -> dict[str, object]:
    trade_date = observed_at.date()
    runs = repository.load_runs_for_date(trade_date=trade_date)
    signals = repository.load_signal_candidates(trade_date=trade_date)
    current_recommendations = _recommendation_records(signals)
    cached_signals = pd.DataFrame()
    if not current_recommendations and _in_carry_recommendation_window(observed_at):
        candidate_cache = repository.load_latest_unfilled_recommendations(
            before_date=trade_date
        )
        if _cache_is_recent(candidate_cache, trade_date=trade_date):
            cached_signals = candidate_cache
    positions = repository.load_positions()
    trades = repository.load_trades()
    active_positions = _active_positions(positions)
    return {
        "strategy_version": STRATEGY_VERSION,
        "strategy_status": "forward_paper_collecting",
        "execution_mode": "paper",
        "broker_orders_enabled": False,
        "contract": _strategy_contract(),
        "session": _session_overview(observed_at, runs),
        "today_candidates": _signal_records(signals),
        "recommendations": current_recommendations,
        "cached_recommendations": _cached_recommendation_records(cached_signals),
        "recommendation_cache": {
            "active": not cached_signals.empty,
            "source_trade_date": _frame_signal_date(cached_signals),
            "valid_until": (
                datetime.combine(trade_date, CARRY_RECOMMENDATION_WINDOW[1], tzinfo=SHANGHAI).isoformat()
                if not cached_signals.empty
                else None
            ),
            "policy": "latest_unfilled_previous_signal_until_10_30",
        },
        "d2_fast_limit_shadow": _d2_shadow_summary(),
        "positions": _position_records(active_positions),
        "trades": _trade_records(trades.head(200)),
        "forward_performance": _forward_performance(positions, trades),
        "evidence_boundary": {
            "historical_metrics_in_forward": False,
            "historical_evidence_is_descriptive": True,
            "historical_evidence_endpoint": "/api/low-suction/swing-research",
            "forward_metrics_source": "low_suction_paper_trades_and_position_marks",
            "broker_fill_claimed": False,
        },
        "generated_at": observed_at.isoformat(),
    }


def _strategy_contract() -> dict[str, object]:
    return {
        "universe": "shanghai_shenzhen_main_board_only",
        "main_rise": "breakout_trend_intraday_provisional",
        "identity": f"{IDENTITY_MODE}_d_minus_one_top3",
        "signal": "14:50_provisional_daily_ma5",
        "entry": "14:55_paper_quote",
        "holding_style": "multi_session_structural",
        "exit": {
            "take_profit": "reference_peak_rebreak",
            "defensive": "two_closes_below_ma20",
            "execution": "next_session_open",
        },
        "portfolio": {
            "initial_cash": INITIAL_CASH,
            "capacity": MAX_POSITIONS,
            "position_target": "one_half_current_equity",
            "concept_limit": MAX_POSITIONS_PER_CONCEPT,
            "lot_size": 100,
            "leverage": False,
        },
    }


def _d2_shadow_summary() -> dict[str, object]:
    try:
        return load_d2_fast_limit_shadow_summary()
    except DatabaseUnavailable:
        return {
            "version": "d2-fast-limit-shadow-v1",
            "trigger_rule": "d1_open_gain_gte_7_and_close_gain_gte_9_5",
            "target_samples": 20,
            "triggered": 0,
            "settled": 0,
            "improved": 0,
            "mean_return_delta_pct_points": None,
            "eligible_for_review": False,
        }


def _session_overview(
    observed_at: datetime,
    runs: pd.DataFrame,
) -> dict[str, object]:
    phases = _phase_records(runs)
    signal = phases.get(repository.SIGNAL_PHASE)
    preview = phases.get(repository.PREVIEW_PHASE)
    entry = phases.get(repository.ENTRY_PHASE)
    if _is_weekend(observed_at):
        status = "market_closed"
    elif signal and signal.get("status") == "blocked":
        status = "blocked"
    elif entry and bool(entry.get("complete")):
        status = "paper_account_active"
    elif signal and bool(signal.get("complete")):
        status = "signal_frozen"
    elif preview and bool(preview.get("complete")):
        status = "preview_ready"
    elif observed_at.time() < time(14, 50):
        status = "awaiting_signal_window"
    else:
        status = "not_run"
    final_ready = bool(signal and signal.get("complete"))
    last_scan = signal if final_ready else preview
    return {
        "trade_date": observed_at.date().isoformat(),
        "status": status,
        "market_closed": _is_weekend(observed_at),
        "auto_refresh_seconds": _auto_refresh_seconds(observed_at),
        "phases": phases,
        "alert_stage": "final_confirmation" if final_ready else "intraday_preview",
        "last_scan_at": last_scan.get("attempted_at") if last_scan else None,
        "next_scan_at": _next_low_suction_scan(observed_at),
    }


def _next_low_suction_scan(observed_at: datetime) -> str | None:
    scan_times = (time(9, 30), time(10, 30), time(11, 30), time(13, 30), time(14, 30), time(14, 50))
    for scan_time in scan_times:
        candidate = datetime.combine(observed_at.date(), scan_time, tzinfo=SHANGHAI)
        if candidate > observed_at:
            return candidate.isoformat()
    return None


def _auto_refresh_seconds(observed_at: datetime) -> int:
    mode = _refresh_mode(observed_at)
    if mode == "live":
        return LIVE_REFRESH_SECONDS
    if mode == "settlement":
        return SETTLEMENT_REFRESH_SECONDS
    next_window = _next_refresh_window_start(observed_at)
    return max(ceil((next_window - observed_at).total_seconds()), 1)


def _next_refresh_window_start(observed_at: datetime) -> datetime:
    for day_offset in range(8):
        candidate_date = observed_at.date() + timedelta(days=day_offset)
        if candidate_date.weekday() >= 5:
            continue
        for start, _ in REFRESH_WINDOWS:
            candidate = datetime.combine(candidate_date, start, tzinfo=SHANGHAI)
            if candidate > observed_at:
                return candidate
    raise RuntimeError("next low-suction refresh window is unavailable")


def _overview_cache_key(observed_at: datetime) -> str:
    return f"{observed_at.date().isoformat()}:{_refresh_mode(observed_at)}"


def _refresh_mode(observed_at: datetime) -> str:
    current = observed_at.time().replace(tzinfo=None)
    if _is_weekend(observed_at):
        return "waiting"
    if any(start <= current < end for start, end in LIVE_REFRESH_WINDOWS):
        return "live"
    if SETTLEMENT_REFRESH_WINDOW[0] <= current < SETTLEMENT_REFRESH_WINDOW[1]:
        return "settlement"
    return "waiting"


def _phase_records(runs: pd.DataFrame) -> dict[str, dict[str, object]]:
    if runs.empty:
        return {}
    records: dict[str, dict[str, object]] = {}
    for row in runs.to_dict("records"):
        phase = str(row.get("phase") or "")
        if not phase:
            continue
        records[phase] = {
            "status": str(row.get("status") or "unknown"),
            "complete": bool(row.get("complete")),
            "attempted_at": _json_value(row.get("attempted_at")),
            "candidate_count": int(row.get("candidate_count") or 0),
            "recommendation_count": int(row.get("recommendation_count") or 0),
            "positions_opened": int(row.get("positions_opened") or 0),
            "positions_closed": int(row.get("positions_closed") or 0),
            "blocking_reasons": _json_value(row.get("blocking_reasons") or []),
        }
    return records


def _active_positions(positions: pd.DataFrame) -> pd.DataFrame:
    if positions.empty or "status" not in positions:
        return positions.iloc[0:0].copy()
    return positions.loc[
        positions["status"].isin(repository.OPEN_POSITION_STATUSES)
    ].copy()


def _forward_performance(
    positions: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, object]:
    active = _active_positions(positions)
    buy_cash = _column_sum(positions, "buy_cash_delta")
    sell_cash = _column_sum(trades, "sell_cash_delta")
    cash = INITIAL_CASH + buy_cash + sell_cash
    market_value = sum(
        _position_market_value(row) for row in active.to_dict("records")
    )
    equity = cash + market_value
    realized_pnl = _column_sum(trades, "net_pnl")
    unrealized_pnl = market_value + _column_sum(active, "buy_cash_delta")
    returns = _numeric_series(trades, "net_return_pct")
    pnls = _numeric_series(trades, "net_pnl")
    wins = int((pnls > 0).sum())
    losses = pnls.loc[pnls < 0]
    profits = pnls.loc[pnls > 0]
    profit_factor = (
        float(profits.sum() / abs(losses.sum()))
        if not profits.empty and not losses.empty
        else None
    )
    compound_return_pct = (equity / INITIAL_CASH - 1.0) * 100.0
    maximum_drawdown_pct = _account_drawdown_pct(trades, current_equity=equity)
    closed_trades = int(len(trades))
    win_rate_pct = wins / closed_trades * 100.0 if closed_trades else None
    return {
        "initial_cash": round(INITIAL_CASH, 2),
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "equity": round(equity, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "closed_trades": closed_trades,
        "winning_trades": wins,
        "win_rate_pct": _rounded_optional(win_rate_pct),
        "mean_net_return_pct": _rounded_optional(
            float(returns.mean()) if not returns.empty else None
        ),
        "profit_factor": _rounded_optional(profit_factor),
        "compound_return_pct": round(compound_return_pct, 4),
        "maximum_drawdown_pct": round(maximum_drawdown_pct, 4),
        "total_fees": round(_column_sum(trades, "total_fees"), 2),
        "qualification": _qualification(
            closed_trades=closed_trades,
            win_rate_pct=win_rate_pct,
            compound_return_pct=compound_return_pct,
            maximum_drawdown_pct=maximum_drawdown_pct,
            profit_factor=profit_factor,
        ),
    }


def _qualification(
    *,
    closed_trades: int,
    win_rate_pct: float | None,
    compound_return_pct: float,
    maximum_drawdown_pct: float,
    profit_factor: float | None,
) -> dict[str, object]:
    checks = {
        "minimum_closed_trades": closed_trades >= FORWARD_MINIMUM_CLOSED_TRADES,
        "win_rate": (
            win_rate_pct is not None
            and win_rate_pct > FORWARD_MINIMUM_WIN_RATE_PCT
        ),
        "compound_return": (
            compound_return_pct > FORWARD_MINIMUM_COMPOUND_RETURN_PCT
        ),
        "maximum_drawdown": (
            maximum_drawdown_pct >= FORWARD_MINIMUM_MAX_DRAWDOWN_PCT
        ),
        "profit_factor": (
            profit_factor is not None
            and profit_factor > FORWARD_MINIMUM_PROFIT_FACTOR
        ),
        "double_cost_positive": False,
        "bootstrap_lower_bound_positive": False,
    }
    qualified = all(checks.values())
    status = (
        "qualified"
        if qualified
        else "collecting_forward_evidence"
        if closed_trades < FORWARD_MINIMUM_CLOSED_TRADES
        else "not_qualified"
    )
    return {
        "status": status,
        "qualified": qualified,
        "checks": checks,
        "thresholds": {
            "closed_trades": FORWARD_MINIMUM_CLOSED_TRADES,
            "win_rate_pct_strictly_above": FORWARD_MINIMUM_WIN_RATE_PCT,
            "compound_return_pct_strictly_above": (
                FORWARD_MINIMUM_COMPOUND_RETURN_PCT
            ),
            "maximum_drawdown_pct_not_below": (
                FORWARD_MINIMUM_MAX_DRAWDOWN_PCT
            ),
            "profit_factor_strictly_above": FORWARD_MINIMUM_PROFIT_FACTOR,
        },
    }


def _account_drawdown_pct(trades: pd.DataFrame, *, current_equity: float) -> float:
    curve = [INITIAL_CASH]
    if not trades.empty and "net_pnl" in trades:
        ordered = trades.copy()
        if "exit_at" in ordered:
            ordered = ordered.sort_values("exit_at", kind="stable")
        equity = INITIAL_CASH
        for value in pd.to_numeric(ordered["net_pnl"], errors="coerce").dropna():
            equity += float(value)
            curve.append(equity)
    if abs(curve[-1] - current_equity) > 1e-9:
        curve.append(current_equity)
    peak = curve[0]
    maximum_drawdown = 0.0
    for equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            maximum_drawdown = min(maximum_drawdown, (equity / peak - 1.0) * 100.0)
    return maximum_drawdown


def _signal_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    fields = (
        "signal_id",
        "signal_trade_date",
        "captured_at",
        "feature_cutoff_at",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "sector_name",
        "rank",
        "current_wave_number",
        "confirmed_higher_highs",
        "reference_peak_price",
        "support_line",
        "support_price",
        "provisional_close",
        "provisional_ma5",
        "signal_eligible",
        "decision_reason",
        "recommendation_state",
        "portfolio_reason",
        "quote_trade_time",
        "evidence_level",
    )
    return _selected_records(frame, fields)


def _recommendation_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty or "recommendation_state" not in frame:
        return []
    recommended = frame.loc[
        frame["recommendation_state"].isin({"recommended", "filled", "rejected"})
    ]
    return _signal_records(recommended)


def _cached_recommendation_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    records = _signal_records(frame)
    for record in records:
        record["recommendation_source"] = "previous_close_cache"
        record["cached"] = True
    return records


def _in_carry_recommendation_window(observed_at: datetime) -> bool:
    current = observed_at.time().replace(tzinfo=None)
    return (
        observed_at.weekday() < 5
        and CARRY_RECOMMENDATION_WINDOW[0] <= current <= CARRY_RECOMMENDATION_WINDOW[1]
    )


def _cache_is_recent(frame: pd.DataFrame, *, trade_date: date) -> bool:
    source_date = _frame_signal_date(frame)
    if source_date is None:
        return False
    return 0 < (trade_date - date.fromisoformat(source_date)).days <= CARRY_RECOMMENDATION_MAX_CALENDAR_DAYS


def _frame_signal_date(frame: pd.DataFrame) -> str | None:
    if frame.empty or "signal_trade_date" not in frame:
        return None
    value = pd.to_datetime(frame.iloc[0]["signal_trade_date"], errors="coerce")
    return None if pd.isna(value) else value.date().isoformat()


def _position_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    records = []
    for row in frame.to_dict("records"):
        market_value = _position_market_value(row)
        invested = -float(row.get("buy_cash_delta") or 0.0)
        unrealized_pnl = market_value - invested
        records.append(
            {
                **_selected_record(
                    row,
                    (
                        "signal_id",
                        "vt_symbol",
                        "stock_name",
                        "sector_id",
                        "sector_name",
                        "status",
                        "entry_trade_date",
                        "entry_at",
                        "entry_price",
                        "volume",
                        "reference_peak_price",
                        "exit_trigger_date",
                        "exit_trigger_reason",
                        "exit_due_after",
                        "exit_deferred_sessions",
                        "last_mark_date",
                        "last_mark_price",
                    ),
                ),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_return_pct": (
                    round(unrealized_pnl / invested * 100.0, 4)
                    if invested > 0
                    else None
                ),
            }
        )
    return records


def _trade_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    fields = (
        "signal_id",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "sector_name",
        "entry_trade_date",
        "entry_at",
        "entry_price",
        "volume",
        "exit_trigger_date",
        "exit_trigger_reason",
        "exit_trade_date",
        "exit_at",
        "exit_price",
        "total_fees",
        "net_pnl",
        "net_return_pct",
        "exit_deferred_sessions",
        "evidence_level",
    )
    return _selected_records(frame, fields)


def _selected_records(
    frame: pd.DataFrame,
    fields: tuple[str, ...],
) -> list[dict[str, object]]:
    return [_selected_record(row, fields) for row in frame.to_dict("records")]


def _selected_record(
    row: Mapping[str, object],
    fields: tuple[str, ...],
) -> dict[str, object]:
    return {field: _json_value(row.get(field)) for field in fields if field in row}


def _position_market_value(row: Mapping[str, object]) -> float:
    mark = row.get("last_mark_price")
    if mark is None or pd.isna(mark):
        mark = row.get("entry_price") or 0.0
    return int(row.get("volume") or 0) * float(mark)


def _column_sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna().astype(float)


def _rounded_optional(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _json_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return None if pd.isna(value) else float(value)
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def _local_now(value: datetime | None) -> datetime:
    observed = value or datetime.now(SHANGHAI)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("swing strategy time must be timezone-aware")
    return observed.astimezone(SHANGHAI)


def _is_weekend(value: datetime) -> bool:
    return value.weekday() >= 5
