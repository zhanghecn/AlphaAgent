"""Candidate-only 5-minute coverage for first-divergence research."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .event_recognition_minutes import (
    INTERVAL,
    REQUIRED_BARS,
    WINDOW_END,
    WINDOW_START,
    build_event_5m_manifest,
    build_event_5m_manifest_report,
)
from .first_divergence import load_first_divergence_inputs

DATASET = "low_suction_first_divergence_observation_5m"


def build_first_divergence_5m_manifest(
    candidates: pd.DataFrame,
    existing_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the already-frozen 48-bar manifest contract."""

    return build_event_5m_manifest(candidates, existing_bars)


def load_first_divergence_5m_manifest(
    candidates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    selected_candidates = (
        candidates
        if candidates is not None
        else load_first_divergence_inputs().candidates
    )
    if selected_candidates.empty:
        return build_first_divergence_5m_manifest(
            selected_candidates,
            _empty_existing_bars(),
        )
    symbols = tuple(sorted(selected_candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(
        sorted(pd.to_datetime(selected_candidates["entry_date"]).dt.date.unique())
    )
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
    return build_first_divergence_5m_manifest(selected_candidates, existing)


def backfill_missing_first_divergence_5m(
    *,
    dry_run: bool,
    max_gaps: int = 100,
) -> dict[str, Any]:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    capped_max_gaps = min(max(int(max_gaps), 1), 2_000)
    manifest = load_first_divergence_5m_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(capped_max_gaps)
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.source_date,
            "window": "first_divergence_observation_5m",
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


def build_first_divergence_5m_manifest_report(
    manifest: pd.DataFrame,
) -> dict[str, Any]:
    report = build_event_5m_manifest_report(manifest)
    return {**report, "dataset": DATASET}


def render_first_divergence_5m_manifest_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_first_divergence_5m_manifest_markdown(report: dict[str, Any]) -> str:
    counts = report["status_counts"]
    return "\n".join(
        [
            "# Low-suction First-divergence 5m Manifest",
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
