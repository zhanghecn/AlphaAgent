"""Frozen candidate contract for confirmed multi-wave leader MA5 pullbacks."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd


SCHEME_VERSION = "leader-ma5-recognition-v1"
MIN_PRIOR_STRONG_DAYS = 1

SELECTION_COLUMNS = (
    "signal_id",
    "signal_date",
    "entry_date",
    "vt_symbol",
    "strong_days_ge_9_5pct",
)


def select_scheme_candidates(ledger: pd.DataFrame) -> pd.DataFrame:
    """Apply the single frozen recognition gate to the immutable MA5 cohort."""

    _require_columns(ledger, SELECTION_COLUMNS, "MA5 attribution ledger")
    frame = ledger.copy()
    if frame["signal_id"].duplicated().any():
        raise ValueError("MA5 attribution signal IDs must be unique")
    strong_days = pd.to_numeric(
        frame["strong_days_ge_9_5pct"],
        errors="raise",
    )
    if strong_days.isna().any() or strong_days.lt(0).any():
        raise ValueError("prior strong-day counts must be non-negative")
    selected = frame.loc[strong_days.ge(MIN_PRIOR_STRONG_DAYS)].copy()
    return selected.sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def summarize_structural_results(trades: pd.DataFrame) -> dict[str, Any]:
    """Summarize already-realized structural exits after candidate selection."""

    _require_columns(
        trades,
        ("signal_id", "exit_date", "net_return_pct"),
        "scheme structural trade ledger",
    )
    returns = pd.to_numeric(trades["net_return_pct"], errors="coerce")
    closed = returns.loc[trades["exit_date"].notna() & returns.notna()]
    return {
        "signals": int(len(trades)),
        "closed_trades": int(len(closed)),
        "right_censored": int(len(trades) - len(closed)),
        "descriptive_positive_share_pct": (
            float(closed.gt(0).mean() * 100.0) if len(closed) else None
        ),
        "mean_net_return_pct": float(closed.mean()) if len(closed) else None,
        "median_net_return_pct": float(closed.median()) if len(closed) else None,
        "profit_factor": _profit_factor(closed),
    }


def summarize_structural_segments(
    trades: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Retain pooled results and every pre-existing chronological block."""

    _require_columns(trades, ("time_block",), "scheme structural trade ledger")
    segments = {"all": summarize_structural_results(trades)}
    for block_number in range(1, 6):
        block = f"block_{block_number}"
        segments[block] = summarize_structural_results(
            trades.loc[trades["time_block"].eq(block)]
        )
    return segments


def summarize_tail_results(ledger: pd.DataFrame) -> dict[str, Any]:
    """Summarize executable cash returns while retaining every attempted signal."""

    required = (
        "status",
        "entry_date",
        "net_return_pct",
        "double_cost_net_return_pct",
    )
    _require_columns(ledger, required, "scheme tail trade ledger")
    normal = pd.to_numeric(ledger["net_return_pct"], errors="coerce")
    stressed = pd.to_numeric(
        ledger["double_cost_net_return_pct"],
        errors="coerce",
    )
    closed_mask = ledger["status"].eq("closed") & normal.notna() & stressed.notna()
    closed = ledger.loc[closed_mask].copy()
    closed["net_return_pct"] = normal.loc[closed_mask]
    closed["double_cost_net_return_pct"] = stressed.loc[closed_mask]
    returns = closed["net_return_pct"]
    compound, drawdown = _daily_compounding(closed)
    return {
        "signals": int(len(ledger)),
        "closed_trades": int(len(closed)),
        "unavailable_or_unclosed": int(len(ledger) - len(closed)),
        "source_days": int(
            pd.to_datetime(closed["entry_date"], errors="raise").dt.date.nunique()
        )
        if len(closed)
        else 0,
        "win_rate_pct": (
            float(returns.gt(0).mean() * 100.0) if len(returns) else None
        ),
        "mean_net_return_pct": float(returns.mean()) if len(returns) else None,
        "median_net_return_pct": float(returns.median()) if len(returns) else None,
        "profit_factor": _profit_factor(returns),
        "double_cost_mean_net_return_pct": (
            float(closed["double_cost_net_return_pct"].mean())
            if len(closed)
            else None
        ),
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
    }


def summarize_tail_segments(
    ledger: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Retain pooled tail results and all five frozen time blocks."""

    _require_columns(ledger, ("block",), "scheme tail trade ledger")
    segments = {"all": summarize_tail_results(ledger)}
    for block_number in range(1, 6):
        segments[f"block_{block_number}"] = summarize_tail_results(
            ledger.loc[pd.to_numeric(ledger["block"], errors="coerce").eq(block_number)]
        )
    return segments


def _daily_compounding(ledger: pd.DataFrame) -> tuple[float | None, float | None]:
    if ledger.empty:
        return None, None
    daily = (
        ledger.assign(
            entry_date=pd.to_datetime(ledger["entry_date"], errors="raise").dt.date
        )
        .groupby("entry_date", sort=True)["net_return_pct"]
        .mean()
    )
    equity = (1.0 + daily / 100.0).cumprod()
    equity_with_initial = pd.concat([pd.Series([1.0]), equity], ignore_index=True)
    drawdown = equity_with_initial / equity_with_initial.cummax() - 1.0
    return (
        float((equity.iloc[-1] - 1.0) * 100.0),
        float(drawdown.min() * 100.0),
    )


def _profit_factor(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    losses = abs(float(returns.loc[returns.lt(0)].sum()))
    if losses == 0:
        return None
    return float(returns.loc[returns.gt(0)].sum()) / losses


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
