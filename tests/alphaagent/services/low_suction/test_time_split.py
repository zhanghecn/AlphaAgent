from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.time_split import (
    chronological_split_labels,
    grouped_bootstrap_interval,
)


def _events() -> pd.DataFrame:
    start = date(2025, 1, 1)
    rows = []
    for day_index in range(10):
        trade_date = start + timedelta(days=day_index)
        for stock_index in range(2):
            rows.append(
                {
                    "event_id": f"{day_index}-{stock_index}",
                    "trade_date": trade_date,
                    "rise_cycle_id": f"CYCLE-{day_index // 2}",
                    "net_return_pct": float(day_index - 4),
                }
            )
    return pd.DataFrame(rows)


def test_chronological_split_uses_unique_dates() -> None:
    labelled = chronological_split_labels(_events())
    date_splits = labelled.groupby("trade_date")["time_split"].nunique()

    assert (date_splits == 1).all()
    assert labelled.loc[labelled["time_split"] == "development", "trade_date"].nunique() == 6
    assert labelled.loc[labelled["time_split"] == "validation", "trade_date"].nunique() == 2
    assert labelled.loc[labelled["time_split"] == "holdout", "trade_date"].nunique() == 2
    assert (
        labelled.loc[labelled["time_split"] == "development", "trade_date"].max()
        < labelled.loc[labelled["time_split"] == "validation", "trade_date"].min()
    )


def test_grouped_bootstrap_is_deterministic_and_groups_correlated_rows() -> None:
    first = grouped_bootstrap_interval(
        _events(),
        value_column="net_return_pct",
        group_columns=("trade_date", "rise_cycle_id"),
        iterations=200,
        seed=7,
    )
    second = grouped_bootstrap_interval(
        _events(),
        value_column="net_return_pct",
        group_columns=("trade_date", "rise_cycle_id"),
        iterations=200,
        seed=7,
    )

    assert first == second
    assert first["groups"] == 10
    assert first["lower"] <= first["estimate"] <= first["upper"]
