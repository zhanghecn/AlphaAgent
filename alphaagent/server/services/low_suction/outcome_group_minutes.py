"""Candidate-only 5-minute coverage for the D+1 outcome-group study."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .event_neutral_days import load_event_neutral_comparison_inputs
from .event_neutral_minutes import (
    build_event_neutral_5m_manifest,
    load_event_neutral_5m_manifest,
)
from .event_recognition_minutes import (
    INTERVAL,
    REQUIRED_BARS,
    WINDOW_END,
    WINDOW_START,
    build_event_5m_manifest_report,
)

DATASET = "low_suction_outcome_group_observation_5m"


def build_outcome_group_5m_manifest(
    candidates: pd.DataFrame,
    existing_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the existing exact 48-bar contract to comparison candidates."""

    return build_event_neutral_5m_manifest(candidates, existing_bars)


def load_outcome_group_5m_manifest(
    candidates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    selected = (
        candidates
        if candidates is not None
        else load_event_neutral_comparison_inputs().candidates
    )
    return load_event_neutral_5m_manifest(selected)


def backfill_missing_outcome_group_5m(
    *,
    dry_run: bool,
    max_gaps: int = 2_000,
) -> dict[str, Any]:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    capped_max_gaps = min(max(int(max_gaps), 1), 2_000)
    manifest = load_outcome_group_5m_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(capped_max_gaps)
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.context_date,
            "window": "outcome_group_observation_5m",
        }
        for row in missing.itertuples(index=False)
    ]
    if not gaps:
        return {
            "status": "ready",
            "dry_run": dry_run,
            "dataset": DATASET,
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


def build_outcome_group_5m_manifest_report(
    manifest: pd.DataFrame,
) -> dict[str, Any]:
    return {**build_event_5m_manifest_report(manifest), "dataset": DATASET}


def render_outcome_group_5m_manifest_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_outcome_group_5m_manifest_markdown(report: dict[str, Any]) -> str:
    counts = report["status_counts"]
    return "\n".join(
        [
            "# Low-suction Outcome-group 5m Manifest",
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
