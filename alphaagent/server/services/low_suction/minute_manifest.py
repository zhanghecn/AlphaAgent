"""Candidate-directed one-minute coverage manifests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select, tuple_

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope

SHANGHAI = ZoneInfo("Asia/Shanghai")
QUERY_CHUNK_SIZE = 500
EVENT_COLUMNS = ("event_id", "vt_symbol", "trade_date", "evidence_level")
BAR_COLUMNS = ("vt_symbol", "trade_date", "bar_time", "source")


@dataclass(frozen=True)
class RequiredMinuteWindow:
    label: str
    first_bar: time
    last_bar: time

    @property
    def expected_bars(self) -> int:
        anchor = date(2000, 1, 1)
        start = datetime.combine(anchor, self.first_bar)
        end = datetime.combine(anchor, self.last_bar)
        return int((end - start).total_seconds() // 60) + 1


REQUIRED_ENTRY_WINDOWS = (
    RequiredMinuteWindow("09:30-10:00", time(9, 31), time(10, 0)),
    RequiredMinuteWindow("10:00-11:30", time(10, 1), time(11, 30)),
    RequiredMinuteWindow("13:00-14:30", time(13, 1), time(14, 30)),
    RequiredMinuteWindow("14:30-14:55", time(14, 31), time(14, 55)),
)


def build_candidate_minute_manifest(
    events: pd.DataFrame,
    minute_bars: pd.DataFrame,
    *,
    windows: Sequence[RequiredMinuteWindow] = REQUIRED_ENTRY_WINDOWS,
) -> pd.DataFrame:
    """Report exact coverage only for supplied event symbol/date pairs."""

    _validate_columns(events, EVENT_COLUMNS, label="event")
    _validate_columns(minute_bars, BAR_COLUMNS, label="minute")
    if not windows:
        raise ValueError("at least one required minute window is required")

    event_frame = _normalized_events(events)
    bar_frame = _normalized_bars(minute_bars)
    rows: list[dict[str, Any]] = []
    for event in event_frame.sort_values(
        ["trade_date", "vt_symbol", "event_id"], kind="stable"
    ).to_dict("records"):
        event_bars = bar_frame.loc[
            (bar_frame["vt_symbol"] == event["vt_symbol"])
            & (bar_frame["trade_date"] == event["trade_date"])
        ]
        rows.extend(_event_window_rows(event, event_bars, windows))
    return pd.DataFrame(rows, columns=_empty_manifest().columns)


def load_existing_candidate_minutes(events: pd.DataFrame) -> pd.DataFrame:
    """Read only exact event symbol/date pairs from PostgreSQL."""

    _validate_columns(events, EVENT_COLUMNS, label="event")
    normalized = _normalized_events(events)
    pairs = sorted(
        {
            (str(row.vt_symbol), pd.Timestamp(row.trade_date).date())
            for row in normalized.itertuples(index=False)
        }
    )
    if not pairs:
        return _empty_minute_bars()

    rows: list[dict[str, Any]] = []
    table = schema.stock_minute_bars
    with session_scope() as session:
        for chunk in _chunks(pairs, QUERY_CHUNK_SIZE):
            statement = (
                select(
                    table.c.vt_symbol,
                    table.c.trade_date,
                    table.c.bar_time,
                    table.c.open_price,
                    table.c.close_price,
                    table.c.high_price,
                    table.c.low_price,
                    table.c.volume,
                    table.c.turnover,
                    table.c.source,
                )
                .where(
                    tuple_(table.c.vt_symbol, table.c.trade_date).in_(chunk),
                    table.c.interval == "1m",
                )
                .order_by(table.c.vt_symbol, table.c.bar_time)
            )
            rows.extend(dict(row) for row in session.execute(statement).mappings())
    return pd.DataFrame(rows, columns=_empty_minute_bars().columns)


def render_minute_manifest_json(manifest: pd.DataFrame) -> str:
    records = _serializable_records(manifest)
    payload = {
        "status": "candidate_minute_manifest",
        "evidence_level": _manifest_evidence_level(manifest),
        "formal_metrics": None,
        "rows": len(records),
        "complete_rows": sum(row["rejection_reason"] is None for row in records),
        "manifest": records,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def render_minute_manifest_csv(manifest: pd.DataFrame) -> str:
    return manifest.to_csv(index=False, lineterminator="\n")


def _event_window_rows(
    event: dict[str, Any],
    event_bars: pd.DataFrame,
    windows: Sequence[RequiredMinuteWindow],
) -> list[dict[str, Any]]:
    rows = []
    for window in windows:
        selected = event_bars.loc[
            event_bars["bar_time"].map(
                lambda value,
                first_bar=window.first_bar,
                last_bar=window.last_bar: (
                    first_bar <= pd.Timestamp(value).time() <= last_bar
                )
            )
        ]
        existing = int(selected["bar_time"].nunique())
        sources = tuple(sorted(selected["source"].dropna().astype(str).unique()))
        if existing == window.expected_bars:
            rejection = None
        elif existing == 0:
            rejection = "missing_minute_window"
        else:
            rejection = "incomplete_minute_window"
        rows.append(
            {
                "event_id": str(event["event_id"]),
                "vt_symbol": str(event["vt_symbol"]),
                "trade_date": pd.Timestamp(event["trade_date"]),
                "required_window": window.label,
                "expected_bars": window.expected_bars,
                "existing_bars": existing,
                "source": ",".join(sources) if sources else None,
                "rejection_reason": rejection,
                "evidence_level": str(event["evidence_level"]),
            }
        )
    return rows


def _normalized_events(events: pd.DataFrame) -> pd.DataFrame:
    frame = events.loc[:, EVENT_COLUMNS].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str).str.strip().str.upper()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if frame.duplicated("event_id").any():
        raise ValueError("event_id rows must be unique")
    return frame


def _normalized_bars(minute_bars: pd.DataFrame) -> pd.DataFrame:
    frame = minute_bars.copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str).str.strip().str.upper()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if frame.empty:
        frame["bar_time"] = pd.Series(index=frame.index, dtype="datetime64[ns]")
        return frame
    frame["bar_time"] = frame["bar_time"].map(_local_naive_timestamp)
    if frame.duplicated(["vt_symbol", "bar_time"]).any():
        raise ValueError("minute vt_symbol/bar_time rows must be unique")
    if (frame["bar_time"].dt.normalize() != frame["trade_date"]).any():
        raise ValueError("minute bar_time date must match trade_date")
    return frame


def _local_naive_timestamp(value: Any) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(SHANGHAI).tz_localize(None)
    return parsed


def _manifest_evidence_level(manifest: pd.DataFrame) -> str:
    if manifest.empty:
        return "invalid"
    levels = sorted(manifest["evidence_level"].dropna().astype(str).unique())
    return levels[0] if len(levels) == 1 else "mixed"


def _serializable_records(manifest: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in manifest.to_dict("records"):
        trade_date = row.get("trade_date")
        row["trade_date"] = (
            pd.Timestamp(trade_date).date().isoformat()
            if trade_date is not None and not pd.isna(trade_date)
            else None
        )
        for key, value in tuple(row.items()):
            if pd.isna(value):
                row[key] = None
        records.append(row)
    return records


def _validate_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _chunks(values: Sequence[Any], size: int):
    for offset in range(0, len(values), size):
        yield list(values[offset : offset + size])


def _empty_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "vt_symbol",
            "trade_date",
            "required_window",
            "expected_bars",
            "existing_bars",
            "source",
            "rejection_reason",
            "evidence_level",
        ]
    )


def _empty_minute_bars() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "trade_date",
            "bar_time",
            "open_price",
            "close_price",
            "high_price",
            "low_price",
            "volume",
            "turnover",
            "source",
        ]
    )
