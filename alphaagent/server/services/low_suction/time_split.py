"""Chronological splits and grouped uncertainty for low-suction events."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


def chronological_split_labels(events: pd.DataFrame) -> pd.DataFrame:
    """Label unique dates as 60% development, 20% validation, 20% holdout."""

    if "trade_date" not in events:
        raise ValueError("trade_date is required")
    result = events.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.normalize()
    dates = sorted(result["trade_date"].dropna().unique())
    if len(dates) < 3:
        raise ValueError("at least three unique event dates are required")

    development_end = max(1, int(len(dates) * 0.6))
    validation_end = max(development_end + 1, int(len(dates) * 0.8))
    validation_end = min(validation_end, len(dates) - 1)
    labels = {
        **{trade_date: "development" for trade_date in dates[:development_end]},
        **{
            trade_date: "validation"
            for trade_date in dates[development_end:validation_end]
        },
        **{trade_date: "holdout" for trade_date in dates[validation_end:]},
    }
    result["time_split"] = result["trade_date"].map(labels)
    return result


def grouped_bootstrap_interval(
    frame: pd.DataFrame,
    *,
    value_column: str,
    group_columns: Sequence[str],
    iterations: int = 1_000,
    seed: int = 17,
) -> dict[str, Any]:
    """Bootstrap group means so correlated concept/day rows move together."""

    required = [value_column, *group_columns]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"missing bootstrap columns: {', '.join(missing)}")
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    working = frame.dropna(subset=required).copy()
    grouped = working.groupby(list(group_columns), sort=True)[value_column].mean()
    values = grouped.to_numpy(dtype=float)
    if not len(values):
        return {"estimate": None, "lower": None, "upper": None, "groups": 0}

    generator = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=float)
    for index in range(iterations):
        samples[index] = generator.choice(values, size=len(values), replace=True).mean()
    return {
        "estimate": float(values.mean()),
        "lower": float(np.quantile(samples, 0.025)),
        "upper": float(np.quantile(samples, 0.975)),
        "groups": int(len(values)),
    }
