"""Candidate-only TDX 5-minute coverage for event-recognition research."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from .event_recognition_falsification import load_event_falsification_inputs

INTERVAL = "5m"
WINDOW_START = "09:35"
WINDOW_END = "15:00"
REQUIRED_BARS = 48


def build_event_5m_manifest(
    candidates: pd.DataFrame,
    existing_bars: pd.DataFrame,
) -> pd.DataFrame:
    required_candidates = ("event_id", "source_date", "entry_date", "vt_symbol")
    missing = [column for column in required_candidates if column not in candidates]
    if missing:
        raise ValueError(f"missing candidate columns: {', '.join(missing)}")
    pairs = candidates.loc[:, list(required_candidates)].copy()
    pairs["source_date"] = pd.to_datetime(pairs["source_date"], errors="raise").dt.date
    pairs["entry_date"] = pd.to_datetime(pairs["entry_date"], errors="raise").dt.date
    if pairs.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("candidate minute pairs must be unique")

    counts = _coverage_counts(existing_bars)
    manifest = pairs.merge(
        counts,
        on=["vt_symbol", "entry_date"],
        how="left",
        validate="one_to_one",
    )
    integer_columns = (
        "raw_rows",
        "existing_bars",
        "duplicate_count",
        "unexpected_time_count",
    )
    for column in integer_columns:
        manifest[column] = manifest[column].fillna(0).astype(int)
    manifest["required_bars"] = REQUIRED_BARS
    manifest["first_bar"] = manifest["first_bar"].where(manifest["first_bar"].notna())
    manifest["last_bar"] = manifest["last_bar"].where(manifest["last_bar"].notna())
    manifest["source"] = manifest["source"].fillna("")
    manifest["status"] = "incomplete"
    manifest.loc[manifest["raw_rows"].eq(0), "status"] = "missing"
    invalid = manifest["duplicate_count"].gt(0) | manifest[
        "unexpected_time_count"
    ].gt(0)
    manifest.loc[invalid, "status"] = "invalid"
    complete = (
        manifest["existing_bars"].eq(REQUIRED_BARS)
        & manifest["duplicate_count"].eq(0)
        & manifest["unexpected_time_count"].eq(0)
        & manifest["first_bar"].eq(WINDOW_START)
        & manifest["last_bar"].eq(WINDOW_END)
    )
    manifest.loc[complete, "status"] = "complete"
    return manifest.sort_values(
        ["entry_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def load_event_5m_manifest() -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    inputs = load_event_falsification_inputs()
    candidates = inputs.candidates
    if candidates.empty:
        return build_event_5m_manifest(candidates, _empty_existing_bars())
    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique()))
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
    return build_event_5m_manifest(candidates, existing)


def backfill_missing_event_5m(
    *,
    dry_run: bool,
    max_gaps: int = 100,
) -> dict[str, Any]:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    capped_max_gaps = min(max(int(max_gaps), 1), 2_000)
    manifest = load_event_5m_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(capped_max_gaps)
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.source_date,
            "window": "event_recognition_entry_5m",
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
        "dataset": "low_suction_event_recognition_entry_5m",
        "manifest_pairs": int(len(manifest)),
        "manifest_complete_before": int(manifest["status"].eq("complete").sum()),
        "manifest_missing_before": int(manifest["status"].ne("complete").sum()),
        "requested_missing_pairs": len(gaps),
    }


def build_event_5m_manifest_report(manifest: pd.DataFrame) -> dict[str, Any]:
    status_counts = {
        status: int(count)
        for status, count in manifest["status"].value_counts().sort_index().items()
    }
    complete = int(status_counts.get("complete", 0))
    return {
        "dataset": "low_suction_event_recognition_entry_5m",
        "interval": INTERVAL,
        "required_bars_per_pair": REQUIRED_BARS,
        "required_window": f"{WINDOW_START}-{WINDOW_END}",
        "pair_count": int(len(manifest)),
        "symbol_count": int(manifest["vt_symbol"].nunique()),
        "date_count": int(manifest["entry_date"].nunique()),
        "complete_count": complete,
        "coverage_pct": round(complete / len(manifest) * 100.0, 4) if len(manifest) else 0.0,
        "status_counts": status_counts,
        "missing_examples": _manifest_records(
            manifest.loc[manifest["status"].ne("complete")].head(50)
        ),
    }


def render_event_5m_manifest_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_event_5m_manifest_markdown(report: dict[str, Any]) -> str:
    counts = report["status_counts"]
    return "\n".join(
        [
            "# Low-suction Event 5m Manifest",
            "",
            f"- Pairs: `{report['pair_count']}`",
            f"- Symbols/dates: `{report['symbol_count']}/{report['date_count']}`",
            f"- Required: `{report['required_bars_per_pair']}` bars, `{report['required_window']}`",
            f"- Complete: `{report['complete_count']}` (`{report['coverage_pct']:.4f}%`)",
            f"- Missing/incomplete/invalid: `{counts.get('missing', 0)}/"
            f"{counts.get('incomplete', 0)}/{counts.get('invalid', 0)}`",
            "",
        ]
    )


def _coverage_counts(existing_bars: pd.DataFrame) -> pd.DataFrame:
    required = ("vt_symbol", "trade_date", "bar_time", "interval", "source")
    missing = [column for column in required if column not in existing_bars]
    if missing:
        raise ValueError(f"missing minute bar columns: {', '.join(missing)}")
    if existing_bars.empty:
        return pd.DataFrame(
            columns=[
                "vt_symbol",
                "entry_date",
                "raw_rows",
                "existing_bars",
                "duplicate_count",
                "unexpected_time_count",
                "first_bar",
                "last_bar",
                "source",
            ]
        )
    frame = existing_bars.loc[existing_bars["interval"].eq(INTERVAL)].copy()
    frame["entry_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="raise")
    frame["hhmm"] = frame["bar_time"].dt.strftime("%H:%M")
    expected_times = set(_expected_close_times())
    rows = []
    for (symbol, entry_date), group in frame.groupby(
        ["vt_symbol", "entry_date"], sort=True
    ):
        unique_times = set(group["hhmm"])
        rows.append(
            {
                "vt_symbol": str(symbol),
                "entry_date": entry_date,
                "raw_rows": int(len(group)),
                "existing_bars": int(group["bar_time"].nunique()),
                "duplicate_count": int(len(group) - group["bar_time"].nunique()),
                "unexpected_time_count": int(len(unique_times - expected_times)),
                "first_bar": min(unique_times) if unique_times else None,
                "last_bar": max(unique_times) if unique_times else None,
                "source": ",".join(sorted(set(group["source"].astype(str)))),
            }
        )
    return pd.DataFrame(rows)


def _expected_close_times() -> tuple[str, ...]:
    def session(start: str) -> list[str]:
        current = datetime.strptime(start, "%H:%M")
        return [
            (current + timedelta(minutes=5 * index)).strftime("%H:%M")
            for index in range(24)
        ]

    return tuple([*session("09:35"), *session("13:05")])


def _manifest_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in frame.to_dict("records"):
        records.append(
            {
                key: (
                    value.isoformat()
                    if isinstance(value, date)
                    else None
                    if pd.isna(value)
                    else value
                )
                for key, value in row.items()
            }
        )
    return records


def _empty_existing_bars() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["vt_symbol", "trade_date", "bar_time", "interval", "source"]
    )
