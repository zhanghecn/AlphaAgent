"""No-lookahead daily main-rise state for concept indices."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("sector_id", "trade_date", "close_price")
MAIN_RISE_CONFIRMED = "MAIN_RISE_CONFIRMED"
NOT_MAIN_RISE = "NOT_MAIN_RISE"
UNKNOWN = "UNKNOWN"


def build_main_rise_states(
    bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date] | None = None,
    evidence_level: str = "daily_discovery",
) -> pd.DataFrame:
    """Compute the approved four-condition state using data through each row."""

    _validate_bars(bars)
    if bars.empty:
        return _empty_result()

    source = bars.copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="raise").dt.normalize()
    source = source.sort_values(["sector_id", "trade_date"], kind="stable")
    if source.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("sector_id/trade_date rows must be unique")

    calendar = _calendar(source, trading_dates)
    results = [
        _build_sector_states(str(sector_id), group, calendar, evidence_level)
        for sector_id, group in source.groupby("sector_id", sort=True)
    ]
    return pd.concat(results, ignore_index=True).sort_values(
        ["sector_id", "trade_date"],
        kind="stable",
        ignore_index=True,
    )


def _build_sector_states(
    sector_id: str,
    group: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    evidence_level: str,
) -> pd.DataFrame:
    frame = group.set_index("trade_date").reindex(calendar)
    frame.index.name = "trade_date"
    frame["sector_id"] = sector_id
    frame["has_bar"] = frame["close_price"].notna()

    close = pd.to_numeric(frame["close_price"], errors="coerce")
    frame["ma10"] = close.rolling(10, min_periods=10).mean()
    frame["ma20"] = close.rolling(20, min_periods=20).mean()
    frame["ma10_shift_5"] = frame["ma10"].shift(5)
    frame["ma20_shift_5"] = frame["ma20"].shift(5)
    frame["return_5d_pct"] = _period_return(close, 5)
    frame["return_10d_pct"] = _period_return(close, 10)
    frame["return_20d_pct"] = _period_return(close, 20)
    rolling_high = close.rolling(20, min_periods=20).max()
    frame["distance_from_20d_high_pct"] = (close / rolling_high - 1.0) * 100.0
    frame["turnover_ratio_5d"] = _turnover_ratio(frame)

    required = frame[
        ["close_price", "ma10", "ma20", "ma10_shift_5", "ma20_shift_5"]
    ].notna().all(axis=1)
    confirmed = (
        required
        & (close > frame["ma10"])
        & (frame["ma10"] > frame["ma20"])
        & (frame["ma10"] > frame["ma10_shift_5"])
        & (frame["ma20"] > frame["ma20_shift_5"])
    )
    frame["state"] = np.select(
        [~required, confirmed],
        [UNKNOWN, MAIN_RISE_CONFIRMED],
        default=NOT_MAIN_RISE,
    )
    frame["state_age"] = _state_age(confirmed)
    frame["rise_cycle_id"] = _rise_cycle_id(sector_id, frame.index, confirmed)
    frame["source_cutoff_date"] = frame.index
    frame["evidence_level"] = evidence_level
    return frame.loc[frame["has_bar"]].reset_index().drop(columns=["has_bar"])


def _calendar(
    bars: pd.DataFrame,
    trading_dates: Sequence[date] | None,
) -> pd.DatetimeIndex:
    values = trading_dates if trading_dates is not None else bars["trade_date"].tolist()
    calendar = pd.DatetimeIndex(pd.to_datetime(list(values), errors="raise")).normalize()
    return calendar.drop_duplicates().sort_values()


def _period_return(close: pd.Series, sessions: int) -> pd.Series:
    previous = close.shift(sessions)
    return (close / previous - 1.0) * 100.0


def _turnover_ratio(frame: pd.DataFrame) -> pd.Series:
    if "turnover" not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    turnover = pd.to_numeric(frame["turnover"], errors="coerce")
    average = turnover.rolling(5, min_periods=5).mean()
    return turnover.div(average.where(average != 0))


def _state_age(confirmed: pd.Series) -> pd.Series:
    groups = (~confirmed).cumsum()
    return confirmed.groupby(groups).cumsum().astype(int)


def _rise_cycle_id(
    sector_id: str,
    calendar: pd.DatetimeIndex,
    confirmed: pd.Series,
) -> pd.Series:
    starts = confirmed & ~confirmed.shift(1, fill_value=False)
    start_dates = pd.Series(calendar.where(starts), index=confirmed.index).ffill()
    identifiers = start_dates.map(
        lambda value: f"{sector_id}:{value.date().isoformat()}" if pd.notna(value) else None
    )
    return identifiers.where(confirmed, None)


def _validate_bars(bars: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in bars]
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *REQUIRED_COLUMNS,
            "ma10",
            "ma20",
            "ma10_shift_5",
            "ma20_shift_5",
            "return_5d_pct",
            "return_10d_pct",
            "return_20d_pct",
            "distance_from_20d_high_pct",
            "turnover_ratio_5d",
            "state",
            "state_age",
            "rise_cycle_id",
            "source_cutoff_date",
            "evidence_level",
        ]
    )
