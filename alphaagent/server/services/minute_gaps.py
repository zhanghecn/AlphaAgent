"""Structured minute-gap helpers for autonomous provider backfill."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope


class MinuteGapError(ValueError):
    """Raised when an internally discovered minute gap is invalid."""


def normalize_minute_gap_requirements(
    gaps: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Normalize database-discovered symbol/date gaps without file input."""

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    errors: list[str] = []
    rows_skipped = 0
    for index, gap in enumerate(gaps, start=1):
        try:
            vt_symbol = str(gap.get("vt_symbol") or "").strip().upper()
            if "." not in vt_symbol:
                raise MinuteGapError("missing or invalid vt_symbol")
            trade_date = parse_date(gap.get("trade_date"))
            if trade_date is None:
                raise MinuteGapError("missing or invalid trade_date")
            key = (vt_symbol, trade_date)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "vt_symbol": vt_symbol,
                    "trade_date": trade_date,
                    "reference_date": parse_date(gap.get("reference_date")),
                    "window": str(gap.get("window") or "").strip(),
                }
            )
        except MinuteGapError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"gap {index}: {exc}")
    return {
        "items": items,
        "rows_read": len(gaps),
        "rows_skipped": rows_skipped,
        "errors": errors,
    }


def audit_minute_gap_requirements(
    requirements: dict[str, Any],
    *,
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
    min_tail_bars: int,
    coverage_counts: Callable[
        [list[dict[str, Any]], str, str, str],
        dict[tuple[str, date], int],
    ]
    | None = None,
) -> dict[str, Any]:
    """Check whether local minute bars cover discovered provider gaps."""

    if requirements["errors"] and not requirements["items"]:
        return {
            "status": "empty",
            "rows_read": requirements["rows_read"],
            "rows_skipped": requirements["rows_skipped"],
            "errors": requirements["errors"],
        }

    items = requirements["items"]
    coverage_fn = coverage_counts or minute_gap_coverage_counts
    coverage = coverage_fn(items, interval, tail_entry_start, tail_entry_end)
    covered = []
    missing = []
    for item in items:
        key = (item["vt_symbol"], item["trade_date"])
        count = int(coverage.get(key, 0) or 0)
        row = {**item, "minute_bar_count": count, "required_tail_bars": min_tail_bars}
        if count >= min_tail_bars:
            covered.append(row)
        else:
            row["missing_reason"] = (
                "no_tail_window_minute_bars"
                if count == 0
                else "insufficient_tail_window_minute_bars"
            )
            missing.append(row)

    unique_symbols = sorted({item["vt_symbol"] for item in items})
    unique_dates = sorted({item["trade_date"] for item in items})
    missing_symbols = sorted({item["vt_symbol"] for item in missing})
    missing_dates = sorted({item["trade_date"] for item in missing})
    return {
        "status": "ready" if not missing else "incomplete",
        "interval": interval,
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "required_tail_bars": min_tail_bars,
        "rows_read": requirements["rows_read"],
        "rows_skipped": requirements["rows_skipped"],
        "gap_count": len(items),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "coverage_pct": round(len(covered) / len(items) * 100, 4) if items else 0,
        "symbol_count": len(unique_symbols),
        "date_count": len(unique_dates),
        "missing_symbol_count": len(missing_symbols),
        "missing_date_count": len(missing_dates),
        "symbols": unique_symbols[:500],
        "missing_symbols": missing_symbols[:500],
        "missing_dates": [item.isoformat() for item in missing_dates[:500]],
        "covered_examples": minute_gap_rows_to_api(covered[:20]),
        "missing_examples": minute_gap_rows_to_api(missing[:100]),
        "errors": requirements["errors"],
        "next_action": (
            "provider_backfill_complete"
            if not missing
            else "retry missing provider gaps according to the persistent backoff ledger"
        ),
    }


def minute_gap_coverage_counts(
    items: list[dict[str, Any]],
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
) -> dict[tuple[str, date], int]:
    """Count local minute bars covering each autonomous gap."""

    if not items:
        return {}
    vt_symbols = sorted({item["vt_symbol"] for item in items})
    dates = sorted({item["trade_date"] for item in items})
    start_time = parse_time_value(tail_entry_start)
    end_time = parse_time_value(tail_entry_end)
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_minute_bars.c.vt_symbol,
                schema.stock_minute_bars.c.trade_date,
                func.count().label("bar_count"),
            )
            .where(
                schema.stock_minute_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_minute_bars.c.trade_date >= dates[0],
                schema.stock_minute_bars.c.trade_date <= dates[-1],
                schema.stock_minute_bars.c.interval == interval,
                func.to_char(schema.stock_minute_bars.c.bar_time, "HH24:MI")
                >= start_time,
                func.to_char(schema.stock_minute_bars.c.bar_time, "HH24:MI")
                <= end_time,
            )
            .group_by(
                schema.stock_minute_bars.c.vt_symbol,
                schema.stock_minute_bars.c.trade_date,
            )
        ).mappings().all()
    return {
        (str(row["vt_symbol"]), row["trade_date"]): int(row["bar_count"] or 0)
        for row in rows
    }


def minute_gap_rows_to_api(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "trade_date": (
                row["trade_date"].isoformat()
                if isinstance(row.get("trade_date"), date)
                else row.get("trade_date")
            ),
            "reference_date": (
                row["reference_date"].isoformat()
                if isinstance(row.get("reference_date"), date)
                else row.get("reference_date")
            ),
        }
        for row in rows
    ]


def parse_time_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise MinuteGapError("time is empty")
    try:
        parsed = datetime.strptime(text[:5], "%H:%M")
    except ValueError as exc:
        raise MinuteGapError(f"invalid HH:MM time: {text}") from exc
    return parsed.strftime("%H:%M")


def parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
