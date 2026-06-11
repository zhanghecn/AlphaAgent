"""TDX public quote minute-bar importer for strict-tail backtest gaps."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.data_sync import (
    _audit_minute_gap_requirements,
    _upsert_minute_bars,
    load_minute_gap_requirements,
)
from alphaagent.server.services.vnpy_integration.local_data import parse_vt_symbol


SUPPORTED_INTERVALS = {"1m": 8}
TDX_PAGE_SIZE = 800
TDX_MAX_START = 65500


def import_tdx_minute_bars_for_gaps(
    *,
    gap_csv_text: str = "",
    gap_file_path: str = "",
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:57",
    dry_run: bool = True,
    max_gaps: int = 2000,
    max_pages_per_symbol: int = 32,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Fetch public TDX 1m bars for strict-tail gap rows and upsert them.

    TDX pages are newest-first and bounded by the wire protocol.  This importer
    groups gap rows by symbol, scans pages until the oldest requested date has
    been passed or the per-symbol page cap is reached, and only accepts rows
    whose timestamp belongs to the requested symbol-date and tail window.
    """

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}

    interval_key = str(interval or "1m").strip().lower()
    category = SUPPORTED_INTERVALS.get(interval_key)
    if category is None:
        return {"status": "unsupported_interval", "interval": interval, "supported": sorted(SUPPORTED_INTERVALS)}

    requirements = load_minute_gap_requirements(gap_csv_text, file_path=gap_file_path)
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

    capped_max_gaps = min(max(int(max_gaps or 2000), 1), 20_000)
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

    try:
        api, host = _connect_tdx(timeout_seconds=timeout_seconds)
    except Exception as exc:
        return {
            "status": "unavailable",
            "message": "TDX public quote server unavailable",
            "reason": exc.__class__.__name__,
            "note": "通达信公开行情服务器可补部分历史 1 分钟线；网络不可达时请改用 Tushare/RQData/XT/QMT/券商导出 CSV。",
        }

    rows_read = 0
    rows_written = 0
    remote_rows_scanned = 0
    empty_page_count = 0
    request_errors: list[str] = []
    unsupported_symbols: list[str] = []
    fetched_counts: dict[tuple[str, date], int] = defaultdict(int)
    processed_symbol_count = 0

    try:
        for vt_symbol, target_dates in grouped.items():
            processed_symbol_count += 1
            try:
                symbol, exchange = parse_vt_symbol(vt_symbol)
                market = _tdx_market(exchange.value)
            except Exception as exc:
                if len(unsupported_symbols) < 50:
                    unsupported_symbols.append(f"{vt_symbol}: {exc.__class__.__name__}")
                continue

            symbol_rows, scanned, empty_pages, errors = _fetch_symbol_tail_rows(
                api,
                category=category,
                market=market,
                symbol=symbol,
                vt_symbol=vt_symbol,
                target_dates=target_dates,
                tail_entry_start=tail_entry_start,
                tail_entry_end=tail_entry_end,
                max_pages=max_pages_per_symbol,
            )
            remote_rows_scanned += scanned
            empty_page_count += empty_pages
            request_errors.extend(error for error in errors if len(request_errors) < 20)
            rows_read += len(symbol_rows)
            for row in symbol_rows:
                fetched_counts[(vt_symbol, row["trade_date"].date())] += 1
            if symbol_rows and not dry_run:
                rows_written += _upsert_minute_bars(symbol, exchange.value, symbol_rows, interval_key, "tdx_public_hq")
    finally:
        try:
            api.disconnect()
        except Exception:
            pass

    audit_after = _audit_minute_gap_requirements(
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
        "tdx_category": category,
        "dry_run": dry_run,
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "gap_count": len(requirements["items"]),
        "processed_gap_count": len(items),
        "unprocessed_gap_count": max(len(requirements["items"]) - len(items), 0),
        "processed_symbol_count": processed_symbol_count,
        "symbol_count": len(grouped),
        "date_count": len({item["trade_date"] for item in items}),
        "rows_read": rows_read,
        "rows_written": rows_written,
        "remote_rows_scanned": remote_rows_scanned,
        "empty_page_count": empty_page_count,
        "preview_covered_gap_count": len(preview_covered),
        "preview_covered_examples": preview_covered[:50],
        "unsupported_symbols": unsupported_symbols,
        "rows_skipped": requirements["rows_skipped"],
        "errors": [*requirements["errors"], *request_errors],
        "audit_after": audit_after,
        "source": "tdx_public_hq",
        "host": host,
        "note": "使用通达信公开行情服务器补真实历史 1 分钟线；公开服务器可回溯范围有限，缺口仍需由 audit_after 判定。",
    }


def _group_requirements(items: list[dict[str, Any]]) -> dict[str, set[date]]:
    grouped: dict[str, set[date]] = defaultdict(set)
    for item in items:
        grouped[str(item["vt_symbol"])].add(item["trade_date"])
    return dict(grouped)


def _connect_tdx(*, timeout_seconds: float):
    try:
        from pytdx.config.hosts import hq_hosts
        from pytdx.hq import TdxHq_API
    except Exception as exc:
        raise RuntimeError("pytdx is not installed") from exc

    last_error: Exception | None = None
    for name, ip, port in hq_hosts[:80]:
        api = TdxHq_API(raise_exception=True)
        try:
            if api.connect(ip, port, time_out=max(float(timeout_seconds or 3.0), 0.5)):
                return api, {"name": name, "ip": ip, "port": port}
        except Exception as exc:
            last_error = exc
            try:
                api.disconnect()
            except Exception:
                pass
    raise RuntimeError(f"no available TDX host: {last_error.__class__.__name__ if last_error else 'empty'}")


def _fetch_symbol_tail_rows(
    api,
    *,
    category: int,
    market: int,
    symbol: str,
    vt_symbol: str,
    target_dates: set[date],
    tail_entry_start: str,
    tail_entry_end: str,
    max_pages: int,
) -> tuple[list[dict[str, Any]], int, int, list[str]]:
    target_dates = set(target_dates)
    if not target_dates:
        return [], 0, 0, []

    min_target = min(target_dates)
    rows: list[dict[str, Any]] = []
    scanned = 0
    empty_pages = 0
    errors: list[str] = []
    max_pages = min(max(int(max_pages or 32), 1), max(TDX_MAX_START // TDX_PAGE_SIZE, 1))

    for page in range(max_pages):
        start = page * TDX_PAGE_SIZE
        if start > TDX_MAX_START:
            break
        try:
            page_rows = api.get_security_bars(category, market, symbol, start, TDX_PAGE_SIZE) or []
        except Exception as exc:
            errors.append(f"{vt_symbol} start={start}: {exc.__class__.__name__}")
            break

        if not page_rows:
            empty_pages += 1
            break

        scanned += len(page_rows)
        page_dates: list[date] = []
        for raw in page_rows:
            bar_time = _parse_tdx_datetime(raw)
            if bar_time is None:
                continue
            page_dates.append(bar_time.date())
            if bar_time.date() not in target_dates:
                continue
            hhmm = bar_time.strftime("%H:%M")
            if hhmm < tail_entry_start or hhmm > tail_entry_end:
                continue
            rows.append(_tdx_row_to_item(raw, bar_time, vt_symbol, category))

        if page_dates and min(page_dates) < min_target:
            break

    return rows, scanned, empty_pages, errors


def _tdx_market(exchange: str) -> int:
    normalized = str(exchange or "").strip().upper()
    if normalized == "SSE":
        return 1
    if normalized == "SZSE":
        return 0
    raise ValueError(f"unsupported TDX exchange: {exchange}")


def _parse_tdx_datetime(row: dict[str, Any]) -> datetime | None:
    value = row.get("datetime")
    if value:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    try:
        return datetime(
            int(row["year"]),
            int(row["month"]),
            int(row["day"]),
            int(row["hour"]),
            int(row["minute"]),
        )
    except Exception:
        return None


def _tdx_row_to_item(row: dict[str, Any], bar_time: datetime, vt_symbol: str, category: int) -> dict[str, Any]:
    return {
        "trade_date": bar_time,
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "volume": row.get("vol") or row.get("volume"),
        "turnover": row.get("amount") or row.get("turnover"),
        "source": "tdx_public_hq",
        "raw": {**dict(row), "vt_symbol": vt_symbol, "tdx_category": category},
    }
