"""AkShare minute-bar importer for near-date 14:30 backtest gaps."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from collections.abc import Mapping, Sequence
from typing import Any

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.data_sync import _upsert_minute_bars
from alphaagent.server.services.minute_gaps import (
    audit_minute_gap_requirements,
    normalize_minute_gap_requirements,
)
from alphaagent.server.services.vnpy_integration.local_data import parse_vt_symbol


SUPPORTED_INTERVALS = {"1m"}


def import_akshare_minute_bars_for_gaps(
    *,
    gaps: Sequence[Mapping[str, Any]],
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    dry_run: bool = True,
    max_gaps: int = 200,
) -> dict[str, Any]:
    """Fetch AkShare/EastMoney 1m bars and keep only the 14:30 snapshot.

    AkShare public minute history is useful for very recent dates, but does not
    reliably cover long historical backtest ranges.  The importer therefore
    reports missing symbol-date pairs explicitly instead of fabricating bars.
    """

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}

    interval_key = str(interval or "1m").strip().lower()
    if interval_key not in SUPPORTED_INTERVALS:
        return {"status": "unsupported_interval", "interval": interval, "supported": sorted(SUPPORTED_INTERVALS)}

    requirements = normalize_minute_gap_requirements(gaps)
    if requirements["errors"] and not requirements["items"]:
        return {
            "status": "empty",
            "dry_run": dry_run,
            "interval": interval_key,
            "gap_count": 0,
            "processed_gap_count": 0,
            "rows_read": 0,
            "rows_written": 0,
            "errors": requirements["errors"],
        }

    capped_max_gaps = min(max(int(max_gaps or 200), 1), 5_000)
    items = requirements["items"][:capped_max_gaps]
    grouped = _group_requirements(items)
    if not grouped:
        return {
            "status": "empty",
            "dry_run": dry_run,
            "interval": interval_key,
            "gap_count": len(requirements["items"]),
            "processed_gap_count": 0,
            "rows_read": 0,
            "rows_written": 0,
            "errors": requirements["errors"],
        }

    adapter = AkShareAdapter()
    rows_read = 0
    rows_written = 0
    request_errors: list[str] = []
    fetched_counts: dict[tuple[str, date], int] = defaultdict(int)
    missing_pairs: list[dict[str, str]] = []

    for vt_symbol, target_dates in grouped.items():
        try:
            symbol, exchange = parse_vt_symbol(vt_symbol)
        except Exception as exc:
            if len(request_errors) < 50:
                request_errors.append(f"{vt_symbol}: {exc.__class__.__name__}")
            continue

        for target_date in sorted(target_dates):
            try:
                data = adapter.stock_bars(
                    symbol,
                    exchange.value,
                    limit=300,
                    interval="1m",
                    start_date=target_date,
                    end_date=target_date,
                )
            except Exception as exc:
                if len(missing_pairs) < 100:
                    missing_pairs.append(
                        {
                            "vt_symbol": vt_symbol,
                            "trade_date": target_date.isoformat(),
                            "reason": f"source_unavailable_for_date:{exc.__class__.__name__}",
                        }
                    )
                continue

            tail_rows = [
                row
                for row in (_minute_item_to_row(item) for item in data.get("items") or [])
                if row is not None
                and row["trade_date"].date() == target_date
                and tail_entry_start <= row["trade_date"].strftime("%H:%M") <= tail_entry_end
            ]
            rows_read += len(tail_rows)
            for row in tail_rows:
                fetched_counts[(vt_symbol, row["trade_date"].date())] += 1
            if tail_rows and not dry_run:
                rows_written += _upsert_minute_bars(symbol, exchange.value, tail_rows, interval_key, "akshare_eastmoney_1m")
            elif not tail_rows and len(missing_pairs) < 100:
                missing_pairs.append(
                    {
                        "vt_symbol": vt_symbol,
                        "trade_date": target_date.isoformat(),
                        "reason": "no_1430_snapshot",
                    }
                )

    audit_after = audit_minute_gap_requirements(
        requirements,
        interval=interval_key,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        min_tail_bars=1,
    )
    preview_covered = [
        {"vt_symbol": vt_symbol, "trade_date": trade_date.isoformat(), "minute_bar_count": count}
        for (vt_symbol, trade_date), count in sorted(fetched_counts.items())
        if count > 0
    ]
    status = "ready" if rows_read > 0 else "empty"
    if request_errors and rows_read > 0:
        status = "partial"
    elif request_errors and rows_read == 0:
        status = "error"

    return {
        "status": status,
        "interval": interval_key,
        "dry_run": dry_run,
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "gap_count": len(requirements["items"]),
        "processed_gap_count": len(items),
        "unprocessed_gap_count": max(len(requirements["items"]) - len(items), 0),
        "symbol_count": len(grouped),
        "date_count": len({item["trade_date"] for item in items}),
        "rows_read": rows_read,
        "rows_written": rows_written,
        "preview_covered_gap_count": len(preview_covered),
        "preview_covered_examples": preview_covered[:50],
        "missing_examples": missing_pairs[:50],
        "rows_skipped": requirements["rows_skipped"],
        "errors": [*requirements["errors"], *request_errors],
        "audit_after": audit_after,
        "source": "akshare_eastmoney_1m",
        "note": "AkShare/东方财富公共分钟线仅适合作为近端 14:30 快照补充；历史日期缺失时需要严格标记为未覆盖。",
    }


def _group_requirements(items: list[dict[str, Any]]) -> dict[str, set[date]]:
    grouped: dict[str, set[date]] = defaultdict(set)
    for item in items:
        grouped[str(item["vt_symbol"])].add(item["trade_date"])
    return dict(grouped)


def _minute_item_to_row(item: dict[str, Any]) -> dict[str, Any] | None:
    dt = _parse_datetime(item.get("trade_date"))
    if dt is None:
        return None
    return {
        "trade_date": dt,
        "open": item.get("open"),
        "high": item.get("high"),
        "low": item.get("low"),
        "close": item.get("close"),
        "volume": item.get("volume"),
        "turnover": item.get("turnover"),
        "raw": item,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None
