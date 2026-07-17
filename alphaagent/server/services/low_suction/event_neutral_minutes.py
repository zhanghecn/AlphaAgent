"""Candidate-only 5-minute coverage for neutral event-spell days."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .event_neutral_days import load_event_neutral_inputs
from .event_recognition_minutes import (
    INTERVAL,
    REQUIRED_BARS,
    WINDOW_END,
    WINDOW_START,
    build_event_5m_manifest,
    build_event_5m_manifest_report,
)

DATASET = "low_suction_event_neutral_observation_5m"


def build_event_neutral_5m_manifest(
    candidates: pd.DataFrame,
    existing_bars: pd.DataFrame,
) -> pd.DataFrame:
    if "context_date" not in candidates:
        raise ValueError("missing candidate columns: context_date")
    context = candidates.loc[:, ["event_id", "context_date"]].copy()
    context["context_date"] = pd.to_datetime(
        context["context_date"], errors="raise"
    ).dt.date
    if context.duplicated(["event_id"]).any():
        raise ValueError("neutral candidate event IDs must be unique")
    manifest = build_event_5m_manifest(candidates, existing_bars)
    return manifest.merge(
        context,
        on="event_id",
        how="left",
        validate="one_to_one",
    )


def load_event_neutral_5m_manifest(
    candidates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    selected = (
        candidates if candidates is not None else load_event_neutral_inputs().candidates
    )
    if selected.empty:
        return build_event_neutral_5m_manifest(selected, _empty_existing_bars())
    symbols = tuple(sorted(selected["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(selected["entry_date"]).dt.date.unique()))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.interval,
            schema.stock_minute_bars.c.source,
        )
        .where(
            schema.stock_minute_bars.c.vt_symbol.in_(symbols),
            schema.stock_minute_bars.c.trade_date.between(dates[0], dates[-1]),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    existing = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    return build_event_neutral_5m_manifest(selected, existing)


def load_complete_event_neutral_5m_bars(candidates: pd.DataFrame) -> pd.DataFrame:
    """Load exact candidate OHLCV bars after the 48-bar manifest is complete."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    if candidates.empty:
        return pd.DataFrame(
            columns=[
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
            ]
        )
    manifest = load_event_neutral_5m_manifest(candidates)
    if manifest["status"].ne("complete").any():
        raise ValueError("event-neutral 5m manifest must be complete before loading bars")
    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique()))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.interval,
            schema.stock_minute_bars.c.open_price,
            schema.stock_minute_bars.c.high_price,
            schema.stock_minute_bars.c.low_price,
            schema.stock_minute_bars.c.close_price,
            schema.stock_minute_bars.c.volume,
            schema.stock_minute_bars.c.turnover,
            schema.stock_minute_bars.c.source,
        )
        .where(
            schema.stock_minute_bars.c.vt_symbol.in_(symbols),
            schema.stock_minute_bars.c.trade_date.between(dates[0], dates[-1]),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    loaded = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    bars = _filter_candidate_bars(candidates, loaded)
    grouped = bars.groupby(["vt_symbol", "trade_date"], sort=False)["bar_time"].nunique()
    if len(bars) != len(candidates) * REQUIRED_BARS or not grouped.eq(REQUIRED_BARS).all():
        raise ValueError("every event-neutral candidate requires exactly 48 complete 5m bars")
    return bars


def backfill_missing_event_neutral_5m(
    *,
    dry_run: bool,
    max_gaps: int = 2_000,
) -> dict[str, Any]:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    capped_max_gaps = min(max(int(max_gaps), 1), 2_000)
    manifest = load_event_neutral_5m_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(capped_max_gaps)
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.context_date,
            "window": "event_neutral_observation_5m",
        }
        for row in missing.itertuples(index=False)
    ]
    if not gaps:
        return {
            "status": "ready",
            "dry_run": dry_run,
            "manifest_pairs": int(len(manifest)),
            "manifest_complete_before": int(manifest["status"].eq("complete").sum()),
            "manifest_missing_before": 0,
            "rows_read": 0,
            "rows_written": 0,
        }
    result = import_tdx_minute_bars_for_gaps(
        gaps=gaps,
        interval=INTERVAL,
        tail_entry_start=WINDOW_START,
        tail_entry_end=WINDOW_END,
        dry_run=dry_run,
        max_gaps=capped_max_gaps,
        max_pages_per_symbol=81,
        timeout_seconds=3.0,
    )
    return {
        **result,
        "dataset": DATASET,
        "manifest_pairs": int(len(manifest)),
        "manifest_complete_before": int(manifest["status"].eq("complete").sum()),
        "manifest_missing_before": int(manifest["status"].ne("complete").sum()),
        "requested_missing_pairs": len(gaps),
    }


def build_event_neutral_5m_manifest_report(
    manifest: pd.DataFrame,
) -> dict[str, Any]:
    return {**build_event_5m_manifest_report(manifest), "dataset": DATASET}


def render_event_neutral_5m_manifest_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_event_neutral_5m_manifest_markdown(report: dict[str, Any]) -> str:
    counts = report["status_counts"]
    return "\n".join(
        [
            "# Low-suction Event-neutral 5m Manifest",
            "",
            f"- Pairs: `{report['pair_count']}`",
            f"- Symbols/dates: `{report['symbol_count']}/{report['date_count']}`",
            f"- Required: `{REQUIRED_BARS}` bars, `{WINDOW_START}-{WINDOW_END}`",
            f"- Complete: `{report['complete_count']}` "
            f"(`{report['coverage_pct']:.4f}%`)",
            f"- Missing/incomplete/invalid: `{counts.get('missing', 0)}/"
            f"{counts.get('incomplete', 0)}/{counts.get('invalid', 0)}`",
            "",
        ]
    )


def _empty_existing_bars() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["vt_symbol", "trade_date", "bar_time", "interval", "source"]
    )


def _filter_candidate_bars(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    pairs = candidates.loc[:, ["vt_symbol", "entry_date"]].copy()
    pairs["trade_date"] = pd.to_datetime(pairs.pop("entry_date")).dt.date
    if pairs.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("event-neutral candidate stock/date pairs must be unique")
    bars = minute_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    bars["bar_time"] = pd.to_datetime(bars["bar_time"], errors="raise")
    return bars.merge(
        pairs,
        on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    ).sort_values(["vt_symbol", "trade_date", "bar_time"], kind="stable").reset_index(
        drop=True
    )
