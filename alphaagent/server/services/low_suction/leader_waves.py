"""Ordered daily state machine for main-rise leader waves."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


BAR_COLUMNS = (
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)
WAVE_COLUMNS = (
    "wave_number",
    "wave_start_date",
    "peak_date",
    "peak_price",
    "trough_date",
    "trough_price",
    "pullback_pct",
    "higher_high_date",
    "higher_high_price",
    "recovery_sessions",
    "trough_volume_ratio_5d",
    "trough_ma5",
    "trough_ma10",
    "trough_ma20",
    "trough_to_ma5_pct",
    "trough_to_ma10_pct",
    "trough_to_ma20_pct",
    "deepest_tested_support",
    "trough_close_reclaimed_ma5",
    "trough_close_reclaimed_ma10",
    "structural_break_date",
    "resolution_status",
    "observation_end",
)


def build_leader_wave_ledger(
    daily_bars: pd.DataFrame,
    *,
    anchor_date: date,
    observation_end: date | None = None,
    minimum_pullback_pct: float = 5.0,
) -> pd.DataFrame:
    """Label record-high waves using strictly ordered daily observations."""

    if minimum_pullback_pct <= 0 or minimum_pullback_pct >= 100:
        raise ValueError("minimum pullback must be between zero and 100")
    bars = _prepare_bars(daily_bars)
    anchor = pd.Timestamp(anchor_date).normalize()
    boundary = (
        pd.Timestamp(observation_end).normalize()
        if observation_end is not None
        else bars["trade_date"].max()
    )
    if boundary < anchor:
        raise ValueError("observation end cannot precede anchor")
    observed = bars.loc[bars["trade_date"].le(boundary)].copy()
    if anchor not in set(observed["trade_date"]):
        raise ValueError("anchor date must have a daily bar")

    positions = {
        pd.Timestamp(value): index
        for index, value in enumerate(observed["trade_date"].tolist())
    }
    campaign = observed.loc[observed["trade_date"].ge(anchor)].reset_index(drop=True)
    first = campaign.iloc[0]
    wave_number = 1
    wave_start_date = pd.Timestamp(first["trade_date"])
    peak_date = wave_start_date
    peak_price = float(first["high_price"])
    pullback_active = False
    trough_date: pd.Timestamp | None = None
    trough_price: float | None = None
    rows: list[dict[str, Any]] = []
    threshold_multiplier = 1.0 - minimum_pullback_pct / 100.0

    for bar in campaign.iloc[1:].itertuples(index=False):
        trade_date = pd.Timestamp(bar.trade_date)
        high_price = float(bar.high_price)
        low_price = float(bar.low_price)
        if not pullback_active:
            if high_price > peak_price:
                peak_price = high_price
                peak_date = trade_date
            if trade_date > peak_date and low_price <= peak_price * threshold_multiplier:
                pullback_active = True
                trough_date = trade_date
                trough_price = low_price
            continue

        assert trough_date is not None and trough_price is not None
        if trade_date > trough_date and high_price > peak_price:
            rows.append(
                _wave_row(
                    observed,
                    positions,
                    wave_number=wave_number,
                    wave_start_date=wave_start_date,
                    peak_date=peak_date,
                    peak_price=peak_price,
                    trough_date=trough_date,
                    trough_price=trough_price,
                    higher_high_date=trade_date,
                    higher_high_price=high_price,
                    structural_break_date=None,
                    resolution_status="continued_to_higher_high",
                    observation_end=boundary,
                )
            )
            wave_number += 1
            wave_start_date = trade_date
            peak_date = trade_date
            peak_price = high_price
            pullback_active = False
            trough_date = None
            trough_price = None
            continue
        if low_price < trough_price:
            trough_date = trade_date
            trough_price = low_price

    structural_break_date: pd.Timestamp | None = None
    if pullback_active:
        assert trough_date is not None and trough_price is not None
        structural_break_date = _first_structural_break(
            observed,
            start_date=peak_date,
        )
        final_status = (
            "terminal_failure_observed"
            if structural_break_date is not None
            else "unresolved_pullback_censored"
        )
    else:
        final_status = "open_at_observation_end"
    rows.append(
        _wave_row(
            observed,
            positions,
            wave_number=wave_number,
            wave_start_date=wave_start_date,
            peak_date=peak_date,
            peak_price=peak_price,
            trough_date=trough_date,
            trough_price=trough_price,
            higher_high_date=None,
            higher_high_price=None,
            structural_break_date=structural_break_date,
            resolution_status=final_status,
            observation_end=boundary,
        )
    )
    return pd.DataFrame(rows, columns=list(WAVE_COLUMNS))


def build_causal_wave_snapshot(
    daily_bars: pd.DataFrame,
    *,
    anchor_date: date,
    cutoff_date: date,
    minimum_pullback_pct: float = 5.0,
) -> dict[str, object]:
    """Summarize wave evidence confirmed by one explicit cutoff."""

    ledger = build_leader_wave_ledger(
        daily_bars,
        anchor_date=anchor_date,
        observation_end=cutoff_date,
        minimum_pullback_pct=minimum_pullback_pct,
    )
    current = ledger.iloc[-1]
    in_pullback = pd.notna(current["trough_date"]) and pd.isna(
        current["higher_high_date"]
    )
    break_date = current["structural_break_date"]
    return {
        "current_wave_number": int(current["wave_number"]),
        "confirmed_higher_highs": int(current["wave_number"]) - 1,
        "current_record_high": float(current["peak_price"]),
        "latest_peak_date": pd.Timestamp(current["peak_date"]).date().isoformat(),
        "current_state": "pullback" if in_pullback else "advancing",
        "structural_state": "broken" if pd.notna(break_date) else "intact",
        "structural_break_date": (
            pd.Timestamp(break_date).date().isoformat()
            if pd.notna(break_date)
            else None
        ),
        "feature_cutoff_date": pd.Timestamp(cutoff_date).date().isoformat(),
    }


def _prepare_bars(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(BAR_COLUMNS) - set(frame))
    if missing:
        raise ValueError(f"missing daily bar columns: {', '.join(missing)}")
    bars = frame.loc[:, list(BAR_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars["trade_date"].duplicated().any():
        raise ValueError("daily bar dates must be unique for one stock")
    numeric_columns = list(BAR_COLUMNS[1:])
    bars[numeric_columns] = bars[numeric_columns].apply(
        pd.to_numeric,
        errors="raise",
    )
    numeric = bars[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric <= 0).any():
        raise ValueError("daily OHLCV values must be finite and positive")
    invalid_range = (
        bars["high_price"].lt(bars[["open_price", "close_price"]].max(axis=1))
        | bars["high_price"].lt(bars["low_price"])
        | bars["low_price"].gt(bars[["open_price", "close_price"]].min(axis=1))
    )
    if invalid_range.any():
        raise ValueError("daily OHLC ranges are inconsistent")
    bars = bars.sort_values("trade_date", kind="stable").reset_index(drop=True)
    bars["ma5"] = bars["close_price"].rolling(5, min_periods=5).mean()
    bars["ma10"] = bars["close_price"].rolling(10, min_periods=10).mean()
    bars["ma20"] = bars["close_price"].rolling(20, min_periods=20).mean()
    bars["prior_volume_median_5d"] = (
        bars["volume"].shift(1).rolling(5, min_periods=5).median()
    )
    below_ma10 = bars["close_price"].lt(bars["ma10"])
    bars["structural_break"] = bars["close_price"].lt(bars["ma20"]) | (
        below_ma10
        & below_ma10.shift(1, fill_value=False)
        & bars["ma5"].le(bars["ma10"])
    )
    return bars


def _wave_row(
    bars: pd.DataFrame,
    positions: dict[pd.Timestamp, int],
    *,
    wave_number: int,
    wave_start_date: pd.Timestamp,
    peak_date: pd.Timestamp,
    peak_price: float,
    trough_date: pd.Timestamp | None,
    trough_price: float | None,
    higher_high_date: pd.Timestamp | None,
    higher_high_price: float | None,
    structural_break_date: pd.Timestamp | None,
    resolution_status: str,
    observation_end: pd.Timestamp,
) -> dict[str, Any]:
    trough = (
        bars.loc[bars["trade_date"].eq(trough_date)].iloc[0]
        if trough_date is not None
        else None
    )
    ma5 = _finite_or_none(trough["ma5"] if trough is not None else None)
    ma10 = _finite_or_none(trough["ma10"] if trough is not None else None)
    ma20 = _finite_or_none(trough["ma20"] if trough is not None else None)
    close = _finite_or_none(trough["close_price"] if trough is not None else None)
    prior_volume = _finite_or_none(
        trough["prior_volume_median_5d"] if trough is not None else None
    )
    volume = _finite_or_none(trough["volume"] if trough is not None else None)
    return {
        "wave_number": wave_number,
        "wave_start_date": wave_start_date,
        "peak_date": peak_date,
        "peak_price": peak_price,
        "trough_date": trough_date,
        "trough_price": trough_price,
        "pullback_pct": (
            (float(trough_price) / peak_price - 1.0) * 100.0
            if trough_price is not None
            else None
        ),
        "higher_high_date": higher_high_date,
        "higher_high_price": higher_high_price,
        "recovery_sessions": (
            positions[higher_high_date] - positions[trough_date]
            if higher_high_date is not None and trough_date is not None
            else None
        ),
        "trough_volume_ratio_5d": (
            volume / prior_volume
            if volume is not None and prior_volume is not None and prior_volume > 0
            else None
        ),
        "trough_ma5": ma5,
        "trough_ma10": ma10,
        "trough_ma20": ma20,
        "trough_to_ma5_pct": _distance_pct(trough_price, ma5),
        "trough_to_ma10_pct": _distance_pct(trough_price, ma10),
        "trough_to_ma20_pct": _distance_pct(trough_price, ma20),
        "deepest_tested_support": _support_level(trough_price, ma5, ma10, ma20),
        "trough_close_reclaimed_ma5": (
            bool(close >= ma5) if close is not None and ma5 is not None else None
        ),
        "trough_close_reclaimed_ma10": (
            bool(close >= ma10) if close is not None and ma10 is not None else None
        ),
        "structural_break_date": structural_break_date,
        "resolution_status": resolution_status,
        "observation_end": observation_end,
    }


def _first_structural_break(
    bars: pd.DataFrame,
    *,
    start_date: pd.Timestamp,
) -> pd.Timestamp | None:
    matches = bars.loc[
        bars["trade_date"].gt(start_date) & bars["structural_break"],
        "trade_date",
    ]
    return pd.Timestamp(matches.iloc[0]) if not matches.empty else None


def _support_level(
    trough_price: float | None,
    ma5: float | None,
    ma10: float | None,
    ma20: float | None,
) -> str | None:
    if trough_price is None:
        return None
    if ma5 is None or ma10 is None or ma20 is None:
        return "insufficient_ma_history"
    if trough_price < ma20:
        return "below_ma20"
    if trough_price <= ma10:
        return "ma10"
    if trough_price <= ma5:
        return "ma5"
    return "above_ma5"


def _distance_pct(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return (float(value) / reference - 1.0) * 100.0


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None
