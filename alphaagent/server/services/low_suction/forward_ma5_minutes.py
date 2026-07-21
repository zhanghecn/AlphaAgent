"""Targeted five-minute collection for strict forward MA5 shadow signals."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema

from .event_recognition_minutes import (
    INTERVAL,
    WINDOW_END,
    WINDOW_START,
    build_event_5m_manifest,
)
from .forward_ma5_pullback import FORWARD_MA5_CONTRACT_VERSION
from .leader_ma5_scheme_minutes import load_existing_scheme_minutes


DATASET = "low_suction_forward_ma5_signal_5m"
WINDOW = "forward_ma5_signal_day_5m"
MAX_BACKFILL_GAPS = 500


def build_forward_ma5_signal_pairs(candidates: pd.DataFrame) -> pd.DataFrame:
    """Keep one exact signal-day pair per eligible stock, independent of rank mode."""

    required = (
        "contract_version",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
        "source_trade_date",
        "signal_eligible",
    )
    _require_columns(candidates, required, "forward MA5 candidate")
    frame = candidates.loc[:, list(required)].copy()
    frame = frame.loc[
        frame["contract_version"].astype(str).eq(FORWARD_MA5_CONTRACT_VERSION)
        & frame["signal_eligible"].astype(bool)
    ].copy()
    if frame.empty:
        return _empty_pairs()
    for column in ("signal_trade_date", "source_trade_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.date
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame = frame.sort_values(
        ["signal_trade_date", "vt_symbol", "source_trade_date", "identity_mode"],
        kind="stable",
    ).drop_duplicates(["vt_symbol", "signal_trade_date"], keep="first")
    rows = [
        {
            "event_id": f"{row.vt_symbol}:{row.signal_trade_date.isoformat()}",
            "source_date": row.source_trade_date,
            "entry_date": row.signal_trade_date,
            "vt_symbol": row.vt_symbol,
        }
        for row in frame.itertuples(index=False)
    ]
    return pd.DataFrame.from_records(rows).reset_index(drop=True)


def build_forward_ma5_signal_manifest(
    pairs: pd.DataFrame,
    existing_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the full-session 48-bar coverage contract."""

    return build_event_5m_manifest(pairs, existing_bars)


def load_forward_ma5_signal_pairs(*, engine: Any | None = None) -> pd.DataFrame:
    """Load immutable eligible forward signals from PostgreSQL."""

    from alphaagent.server.db.session import get_engine

    table = schema.low_suction_forward_ma5_candidates
    statement = (
        select(
            table.c.contract_version,
            table.c.signal_trade_date,
            table.c.identity_mode,
            table.c.vt_symbol,
            table.c.source_trade_date,
            table.c.signal_eligible,
        )
        .where(
            table.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
            table.c.signal_eligible.is_(True),
        )
        .order_by(
            table.c.signal_trade_date,
            table.c.vt_symbol,
            table.c.identity_mode,
        )
    )
    candidates = pd.read_sql(statement, engine or get_engine())
    return build_forward_ma5_signal_pairs(candidates)


def load_forward_ma5_signal_manifest() -> pd.DataFrame:
    """Load exact pairs and classify their current local coverage."""

    pairs = load_forward_ma5_signal_pairs()
    existing = load_existing_scheme_minutes(pairs)
    return build_forward_ma5_signal_manifest(pairs, existing)


def backfill_forward_ma5_signal_5m(
    *,
    dry_run: bool,
    max_gaps: int = 100,
) -> dict[str, Any]:
    """Backfill bounded signal-day gaps through the existing public TDX importer."""

    capped_max_gaps = min(max(int(max_gaps), 1), MAX_BACKFILL_GAPS)
    manifest = load_forward_ma5_signal_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(
        capped_max_gaps
    )
    complete_before = int(manifest["status"].eq("complete").sum())
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.source_date,
            "window": WINDOW,
        }
        for row in missing.itertuples(index=False)
    ]
    if not gaps:
        return {
            "status": "ready",
            "dry_run": dry_run,
            "dataset": DATASET,
            "manifest_pairs": int(len(manifest)),
            "manifest_complete_before": complete_before,
            "manifest_missing_before": 0,
            "requested_missing_pairs": 0,
            "rows_read": 0,
            "rows_written": 0,
        }
    result = _import_tdx_gaps(
        gaps=gaps,
        interval=INTERVAL,
        tail_entry_start=WINDOW_START,
        tail_entry_end=WINDOW_END,
        dry_run=dry_run,
        max_gaps=capped_max_gaps,
        max_pages_per_symbol=16,
        timeout_seconds=3.0,
    )
    return {
        **result,
        "dataset": DATASET,
        "manifest_pairs": int(len(manifest)),
        "manifest_complete_before": complete_before,
        "manifest_missing_before": int(len(manifest) - complete_before),
        "requested_missing_pairs": len(gaps),
    }


def _import_tdx_gaps(**kwargs: Any) -> dict[str, Any]:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    return import_tdx_minute_bars_for_gaps(**kwargs)


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _empty_pairs() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["event_id", "source_date", "entry_date", "vt_symbol"]
    )
