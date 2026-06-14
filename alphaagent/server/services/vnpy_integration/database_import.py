"""Import vn.py database bars into AlphaAgent research tables."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from vnpy.trader.constant import Interval
from vnpy.trader.database import get_database

from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.data_sync import (
    _audit_minute_gap_requirements,
    _upsert_minute_bars,
    load_minute_gap_requirements,
)
from alphaagent.server.services.vnpy_integration.local_data import parse_vt_symbol


SUPPORTED_INTERVALS = {
    "1m": Interval.MINUTE,
}


def import_vnpy_minute_bars(
    vt_symbol: str,
    start: date | datetime | str,
    end: date | datetime | str | None = None,
    *,
    interval: str = "1m",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Load minute bars from the configured vn.py database and write AlphaAgent rows."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}

    interval_key = str(interval or "1m").strip().lower()
    vnpy_interval = SUPPORTED_INTERVALS.get(interval_key)
    if vnpy_interval is None:
        return {"status": "unsupported_interval", "interval": interval, "supported": sorted(SUPPORTED_INTERVALS)}

    symbol, exchange = parse_vt_symbol(vt_symbol)
    start_dt = _as_datetime(start)
    end_dt = _as_datetime(end) if end else datetime.combine(start_dt.date(), time(23, 59, 59))

    database = get_database()
    bars = database.load_bar_data(symbol, exchange, vnpy_interval, start_dt, end_dt)
    items = [
        {
            "trade_date": bar.datetime,
            "open": float(bar.open_price or 0),
            "high": float(bar.high_price or 0),
            "low": float(bar.low_price or 0),
            "close": float(bar.close_price or 0),
            "volume": float(bar.volume or 0),
            "turnover": float(bar.turnover or 0),
            "source": "vnpy_database",
            "raw": {
                "gateway_name": bar.gateway_name,
                "interval": bar.interval.value if bar.interval else interval_key,
            },
        }
        for bar in bars
    ]

    rows_written = 0 if dry_run else _upsert_minute_bars(symbol, exchange.value, items, interval_key, "vnpy_database")
    return {
        "status": "ready" if bars else "empty",
        "vt_symbol": f"{symbol}.{exchange.value}",
        "symbol": symbol,
        "exchange": exchange.value,
        "interval": interval_key,
        "dry_run": dry_run,
        "rows_read": len(bars),
        "rows_written": rows_written,
        "start": start_dt.isoformat(sep=" "),
        "end": end_dt.isoformat(sep=" "),
        "source": "vnpy_database",
        "note": "从当前 vn.py database.name 配置读取 BarData；需要先用 DataManager/Datafeed/Gateway 把历史分钟线写入 vn.py 数据库。",
    }


def import_vnpy_minute_bars_for_gaps(
    *,
    gap_csv_text: str = "",
    gap_file_path: str = "",
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    dry_run: bool = True,
    max_gaps: int = 2000,
) -> dict[str, Any]:
    """Load vn.py minute bars for strict-tail gap rows and upsert them.

    The gap CSV is the file produced by strict minute backtests.  Each row
    represents an execution date and symbol that must have a visible 14:30
    snapshot before the strict backtest can claim a real fill.
    """

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}

    interval_key = str(interval or "1m").strip().lower()
    vnpy_interval = SUPPORTED_INTERVALS.get(interval_key)
    if vnpy_interval is None:
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

    all_items = requirements["items"]
    capped_max_gaps = min(max(int(max_gaps or 2000), 1), 20_000)
    items = all_items[:capped_max_gaps]
    database = get_database()
    start_tail = _as_time(tail_entry_start)
    end_tail = _as_time(tail_entry_end)

    rows_read = 0
    rows_written = 0
    empty_requests = 0
    request_errors: list[str] = []
    symbol_dates: set[tuple[str, date]] = set()
    symbols: set[str] = set()
    dates: set[date] = set()

    for item in items:
        vt_symbol = item["vt_symbol"]
        trade_date = item["trade_date"]
        symbol_dates.add((vt_symbol, trade_date))
        symbols.add(vt_symbol)
        dates.add(trade_date)
        try:
            symbol, exchange = parse_vt_symbol(vt_symbol)
            start_dt = datetime.combine(trade_date, start_tail)
            end_dt = datetime.combine(trade_date, end_tail)
            bars = database.load_bar_data(symbol, exchange, vnpy_interval, start_dt, end_dt)
        except Exception as exc:
            if len(request_errors) < 20:
                request_errors.append(f"{vt_symbol} {trade_date.isoformat()}: {exc.__class__.__name__}")
            continue

        rows_read += len(bars)
        if not bars:
            empty_requests += 1
            continue
        bar_items = [
            {
                "trade_date": bar.datetime,
                "open": float(bar.open_price or 0),
                "high": float(bar.high_price or 0),
                "low": float(bar.low_price or 0),
                "close": float(bar.close_price or 0),
                "volume": float(bar.volume or 0),
                "turnover": float(bar.turnover or 0),
                "source": "vnpy_database_gap",
                "raw": {
                    "gateway_name": bar.gateway_name,
                    "interval": bar.interval.value if bar.interval else interval_key,
                    "gap_trade_date": trade_date.isoformat(),
                },
            }
            for bar in bars
        ]
        if not dry_run:
            rows_written += _upsert_minute_bars(symbol, exchange.value, bar_items, interval_key, "vnpy_database_gap")

    audit_after = _audit_minute_gap_requirements(
        requirements,
        interval=interval_key,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        min_tail_bars=1,
    )
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
        "gap_count": len(all_items),
        "processed_gap_count": len(items),
        "unprocessed_gap_count": max(len(all_items) - len(items), 0),
        "symbol_count": len(symbols),
        "date_count": len(dates),
        "symbol_date_count": len(symbol_dates),
        "rows_read": rows_read,
        "rows_written": rows_written,
        "empty_request_count": empty_requests,
        "rows_skipped": requirements["rows_skipped"],
        "errors": [*requirements["errors"], *request_errors],
        "audit_after": audit_after,
        "source": "vnpy_database",
        "note": "按严格尾盘缺口从当前 vn.py database.name 配置读取分钟线；vn.py 数据库为空时不会产生写入。",
    }


def _as_time(value: str) -> time:
    text = str(value or "").strip()
    if not text:
        raise ValueError("time is empty")
    return datetime.strptime(text[:5], "%H:%M").time()


def _as_datetime(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time())
    text = str(value)
    if "T" in text or " " in text:
        return datetime.fromisoformat(text.replace("T", " ")[:19])
    return datetime.combine(date.fromisoformat(text[:10]), time())
