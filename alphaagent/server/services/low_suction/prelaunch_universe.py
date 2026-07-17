"""Full main-board D-1 feature universe for prelaunch research."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .universe import is_main_board_symbol


MIN_PRIOR_SESSIONS = 60
STRONG_DAY_THRESHOLD_PCT = 5.0
STRONG_LOOKBACK_SESSIONS = 10

PRELAUNCH_FEATURES = (
    "return_1d_pct",
    "return_3d_pct",
    "return_5d_pct",
    "return_10d_pct",
    "distance_to_ma5_pct",
    "distance_to_ma10_pct",
    "distance_to_ma20_pct",
    "distance_from_20d_high_pct",
    "volume_ratio_1d_to_prior5",
    "volume_ratio_5d_to_20d",
    "log_turnover_median_20d",
    "volatility_10d_pct",
)

BAR_COLUMNS = (
    "vt_symbol",
    "symbol",
    "exchange",
    "name",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
)
PROHIBITED_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "entry_price",
        "exit_price",
        "mfe_pct",
        "mae_pct",
        "verified_first_explosion",
        "d_return_pct",
    }
)
PROHIBITED_PREFIXES = ("future_", "outcome_", "exit_", "d1_", "d3_", "d5_")

OUTPUT_COLUMNS = (
    "event_id",
    "context_date",
    "entry_date",
    "feature_cutoff_date",
    "vt_symbol",
    "symbol",
    "exchange",
    "stock_name",
    "security_evidence_level",
    "prior_sessions",
    "prior_strong_days_10d",
    *PRELAUNCH_FEATURES,
)


def build_prelaunch_feature_panel(
    stock_bars: pd.DataFrame,
    *,
    target_dates: Sequence[date],
) -> pd.DataFrame:
    """Build full-universe D-1 features with no D market values exposed."""

    _reject_prohibited_columns(stock_bars)
    bars = _prepare_bars(stock_bars)
    targets = tuple(sorted(set(pd.to_datetime(tuple(target_dates), errors="raise").date)))
    if not targets or bars.empty:
        return _empty_panel()
    calendar = tuple(sorted(bars["trade_date"].unique()))
    context_by_target = _context_dates(calendar, targets)
    if not context_by_target:
        return _empty_panel()

    feature_rows = pd.concat(
        [
            _build_symbol_feature_history(vt_symbol, group)
            for vt_symbol, group in bars.groupby("vt_symbol", sort=True)
        ],
        ignore_index=True,
    )
    context_frame = pd.DataFrame(
        [
            {"entry_date": target, "trade_date": context}
            for target, context in context_by_target.items()
        ]
    )
    candidates = feature_rows.merge(
        context_frame,
        on="trade_date",
        how="inner",
        validate="many_to_many",
    ).rename(columns={"trade_date": "context_date"})
    available_d_bars = bars.loc[
        bars["trade_date"].isin(context_by_target), ["vt_symbol", "trade_date"]
    ].rename(columns={"trade_date": "entry_date"})
    candidates = candidates.merge(
        available_d_bars,
        on=["vt_symbol", "entry_date"],
        how="inner",
        validate="one_to_one",
    )
    eligible = (
        candidates["prior_sessions"].ge(MIN_PRIOR_SESSIONS)
        & candidates["prior_strong_days_10d"].eq(0)
        & candidates[list(PRELAUNCH_FEATURES)].notna().all(axis=1)
        & np.isfinite(
            candidates.loc[:, list(PRELAUNCH_FEATURES)].to_numpy(dtype=float)
        ).all(axis=1)
    )
    result = candidates.loc[eligible].copy()
    result["feature_cutoff_date"] = result["context_date"]
    result["security_evidence_level"] = "reconstructed_current_name"
    result["stock_name"] = result.pop("name")
    result["event_id"] = (
        "prelaunch:"
        + result["entry_date"].astype(str)
        + ":"
        + result["vt_symbol"].astype(str)
    )
    if result["event_id"].duplicated().any():
        raise ValueError("prelaunch feature event IDs must be unique")
    return result.loc[:, list(OUTPUT_COLUMNS)].sort_values(
        ["entry_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def _prepare_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, BAR_COLUMNS, "prelaunch stock bar")
    bars = frame.loc[:, list(BAR_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("prelaunch stock bar identities must be unique")
    for column in (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    ):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    _validate_static_identity(bars)
    main_board = [
        is_main_board_symbol(symbol, exchange)
        for symbol, exchange in zip(bars["symbol"], bars["exchange"], strict=True)
    ]
    eligible_name = ~bars["name"].map(_is_excluded_current_name)
    return bars.loc[np.asarray(main_board) & eligible_name].sort_values(
        ["vt_symbol", "trade_date"], kind="stable"
    ).reset_index(drop=True)


def _validate_static_identity(bars: pd.DataFrame) -> None:
    for column in ("symbol", "exchange", "name"):
        if bars.groupby("vt_symbol", sort=False)[column].nunique(dropna=False).gt(1).any():
            raise ValueError(f"stock {column} must be stable inside the loaded window")


def _context_dates(
    calendar: tuple[date, ...],
    targets: tuple[date, ...],
) -> dict[date, date]:
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    return {
        target: calendar[positions[target] - 1]
        for target in targets
        if target in positions and positions[target] > 0
    }


def _build_symbol_feature_history(
    vt_symbol: str,
    group: pd.DataFrame,
) -> pd.DataFrame:
    frame = group.sort_values("trade_date", kind="stable").copy()
    close = frame["close_price"]
    volume = frame["volume"]
    turnover = frame["turnover"]
    daily_return = close.pct_change(fill_method=None) * 100.0
    frame["return_1d_pct"] = daily_return
    for sessions in (3, 5, 10):
        frame[f"return_{sessions}d_pct"] = (
            close / close.shift(sessions) - 1.0
        ) * 100.0
    for sessions in (5, 10, 20):
        moving_average = close.rolling(sessions, min_periods=sessions).mean()
        frame[f"distance_to_ma{sessions}_pct"] = (
            close / moving_average.where(moving_average.gt(0)) - 1.0
        ) * 100.0
    rolling_high = close.rolling(20, min_periods=20).max()
    frame["distance_from_20d_high_pct"] = (
        close / rolling_high.where(rolling_high.gt(0)) - 1.0
    ) * 100.0
    prior_five_volume = volume.shift(1).rolling(5, min_periods=5).mean()
    frame["volume_ratio_1d_to_prior5"] = volume / prior_five_volume.where(
        prior_five_volume.gt(0)
    )
    volume_5d = volume.rolling(5, min_periods=5).mean()
    volume_20d = volume.rolling(20, min_periods=20).mean()
    frame["volume_ratio_5d_to_20d"] = volume_5d / volume_20d.where(
        volume_20d.gt(0)
    )
    turnover_median = turnover.rolling(20, min_periods=20).median()
    frame["log_turnover_median_20d"] = np.log1p(
        turnover_median.where(turnover_median.gt(0))
    )
    frame["volatility_10d_pct"] = daily_return.rolling(
        10, min_periods=10
    ).std(ddof=0)
    frame["prior_sessions"] = np.arange(1, len(frame) + 1)
    frame["prior_strong_days_10d"] = daily_return.ge(
        STRONG_DAY_THRESHOLD_PCT
    ).rolling(STRONG_LOOKBACK_SESSIONS, min_periods=STRONG_LOOKBACK_SESSIONS).sum()
    frame["vt_symbol"] = vt_symbol
    return frame.loc[
        :,
        [
            "trade_date",
            "vt_symbol",
            "symbol",
            "exchange",
            "name",
            "prior_sessions",
            "prior_strong_days_10d",
            *PRELAUNCH_FEATURES,
        ],
    ]


def _is_excluded_current_name(value: Any) -> bool:
    name = str(value or "").strip().upper()
    return "ST" in name or "退市" in name or name.startswith("退")


def _reject_prohibited_columns(frame: pd.DataFrame) -> None:
    prohibited = sorted(
        str(column)
        for column in frame.columns
        if str(column) in PROHIBITED_COLUMNS
        or str(column).lower().startswith(PROHIBITED_PREFIXES)
    )
    if prohibited:
        raise ValueError(f"prohibited prelaunch feature columns: {prohibited}")


def _empty_panel() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
