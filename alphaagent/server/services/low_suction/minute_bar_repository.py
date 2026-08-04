"""Read exact local minute bars for bounded low-suction coverage checks."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import select, tuple_

from alphaagent.server.db import schema


MINUTE_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "bar_time",
    "interval",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "source",
)


def load_existing_minute_bars(
    pairs: pd.DataFrame,
    *,
    engine: Any | None = None,
) -> pd.DataFrame:
    """Load only the declared symbol/date pairs from PostgreSQL."""

    from alphaagent.server.db.session import get_engine

    required = {"vt_symbol", "entry_date"}
    missing = sorted(required - set(pairs.columns))
    if missing:
        raise ValueError(f"missing minute-pair columns: {', '.join(missing)}")
    exact_pairs = sorted(
        {
            (str(row.vt_symbol), pd.Timestamp(row.entry_date).date())
            for row in pairs.itertuples(index=False)
        }
    )
    if not exact_pairs:
        return pd.DataFrame(columns=MINUTE_COLUMNS)
    table = schema.stock_minute_bars
    statement = (
        select(*(getattr(table.c, column) for column in MINUTE_COLUMNS))
        .where(
            tuple_(table.c.vt_symbol, table.c.trade_date).in_(exact_pairs),
            table.c.interval == "5m",
        )
        .order_by(table.c.vt_symbol, table.c.trade_date, table.c.bar_time)
    )
    return pd.read_sql(
        statement,
        engine or get_engine(),
        parse_dates=["bar_time"],
    )
