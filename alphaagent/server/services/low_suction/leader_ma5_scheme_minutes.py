"""Exact five-minute coverage for the frozen leader MA5 scheme."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pandas as pd
from sqlalchemy import select, tuple_

from alphaagent.server.db import schema

from .event_recognition_minutes import (
    INTERVAL,
    REQUIRED_BARS,
    WINDOW_END,
    WINDOW_START,
    build_event_5m_manifest,
)


DATASET = "low_suction_leader_ma5_scheme_5m"
WINDOW = "leader_ma5_scheme_signal_and_next_session_5m"
MAX_BACKFILL_GAPS = 2_000

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


def build_scheme_minute_pairs(candidates: pd.DataFrame) -> pd.DataFrame:
    """Map every scheme signal to its exact signal and next-session dates."""

    required = ("signal_id", "signal_date", "entry_date", "vt_symbol")
    _require_columns(candidates, required, "leader MA5 scheme candidate")
    frame = candidates.loc[:, list(required)].copy()
    if frame["signal_id"].duplicated().any():
        raise ValueError("leader MA5 scheme signal IDs must be unique")
    for column in ("signal_date", "entry_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.date

    rows: list[dict[str, Any]] = []
    for candidate in frame.sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).to_dict("records"):
        signal_id = str(candidate["signal_id"])
        source_date = candidate["signal_date"]
        for role, trade_date in (
            ("signal", source_date),
            ("next_session", candidate["entry_date"]),
        ):
            rows.append(
                {
                    "event_id": f"{signal_id}:{role}",
                    "signal_id": signal_id,
                    "source_date": source_date,
                    "entry_date": trade_date,
                    "vt_symbol": str(candidate["vt_symbol"]),
                    "pair_role": role,
                }
            )
    pairs = pd.DataFrame.from_records(rows)
    if pairs.empty:
        return _empty_pairs()
    if pairs.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("leader MA5 minute symbol/date pairs must be unique")
    return pairs.reset_index(drop=True)


def build_scheme_5m_manifest(
    pairs: pd.DataFrame,
    existing_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the established 48-bar coverage contract to exact scheme pairs."""

    _require_columns(
        pairs,
        ("event_id", "signal_id", "pair_role"),
        "scheme minute pair",
    )
    manifest = build_event_5m_manifest(pairs, existing_bars)
    roles = pairs.loc[:, ["event_id", "signal_id", "pair_role"]]
    return manifest.merge(
        roles,
        on="event_id",
        how="left",
        validate="one_to_one",
    )


def load_existing_scheme_minutes(
    pairs: pd.DataFrame,
    *,
    engine: Any | None = None,
) -> pd.DataFrame:
    """Load only the required symbol/date pairs from PostgreSQL."""

    from alphaagent.server.db.session import get_engine

    _require_columns(pairs, ("vt_symbol", "entry_date"), "scheme minute pair")
    exact_pairs = sorted(
        {
            (
                str(row.vt_symbol),
                pd.Timestamp(row.entry_date).date(),
            )
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
            table.c.interval == INTERVAL,
        )
        .order_by(table.c.vt_symbol, table.c.trade_date, table.c.bar_time)
    )
    return pd.read_sql(
        statement,
        engine or get_engine(),
        parse_dates=["bar_time"],
    )


def load_scheme_5m_manifest(
    candidates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Load the frozen scheme cohort and report exact minute coverage."""

    if candidates is None:
        from .leader_ma5_scheme_study import load_frozen_scheme_candidates

        candidates = load_frozen_scheme_candidates()
    pairs = build_scheme_minute_pairs(candidates)
    existing = load_existing_scheme_minutes(pairs)
    return build_scheme_5m_manifest(pairs, existing)


def backfill_missing_scheme_5m(
    *,
    dry_run: bool,
    max_gaps: int = 100,
) -> dict[str, Any]:
    """Backfill only bounded incomplete pairs through the existing TDX importer."""

    capped_max_gaps = min(max(int(max_gaps), 1), MAX_BACKFILL_GAPS)
    manifest = load_scheme_5m_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(
        capped_max_gaps
    )
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.source_date,
            "window": WINDOW,
        }
        for row in missing.itertuples(index=False)
    ]
    complete_before = int(manifest["status"].eq("complete").sum())
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
        max_pages_per_symbol=81,
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


def build_scheme_5m_manifest_report(manifest: pd.DataFrame) -> dict[str, Any]:
    """Render stable coverage totals without exposing outcome data."""

    counts = {
        str(status): int(count)
        for status, count in manifest["status"].value_counts().sort_index().items()
    }
    complete = int(counts.get("complete", 0))
    return {
        "dataset": DATASET,
        "interval": INTERVAL,
        "required_bars_per_pair": REQUIRED_BARS,
        "required_window": f"{WINDOW_START}-{WINDOW_END}",
        "pair_count": int(len(manifest)),
        "symbol_count": int(manifest["vt_symbol"].nunique()),
        "date_count": int(manifest["entry_date"].nunique()),
        "complete_count": complete,
        "coverage_pct": (
            float(complete / len(manifest) * 100.0) if len(manifest) else 0.0
        ),
        "status_counts": counts,
    }


def render_scheme_5m_manifest_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_scheme_5m_manifest_markdown(report: dict[str, Any]) -> str:
    counts = report["status_counts"]
    return "\n".join(
        [
            "# Leader MA5 Scheme 5m Manifest",
            "",
            f"- Pairs: `{report['pair_count']}`",
            f"- Symbols/dates: `{report['symbol_count']}/{report['date_count']}`",
            f"- Complete: `{report['complete_count']}` "
            f"(`{report['coverage_pct']:.4f}%`)",
            f"- Missing/incomplete/invalid: `{counts.get('missing', 0)}/"
            f"{counts.get('incomplete', 0)}/{counts.get('invalid', 0)}`",
            "",
        ]
    )


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
        columns=[
            "event_id",
            "signal_id",
            "source_date",
            "entry_date",
            "vt_symbol",
            "pair_role",
        ]
    )
