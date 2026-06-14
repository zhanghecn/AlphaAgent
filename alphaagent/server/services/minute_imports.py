"""Standard minute-bar CSV/file import helpers."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from alphaagent.market.symbols import normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope


MinuteUpsert = Callable[[str, str, list[dict[str, Any]], str, str], int]


class MinuteImportError(RuntimeError):
    """Raised for invalid minute import inputs."""


def minute_csv_template() -> str:
    """Return a minimal CSV template for importing historical minute bars."""

    return (
        "vt_symbol,bar_time,open,high,low,close,volume,turnover\n"
        "600000.SSE,2026-01-08 14:30:00,10.00,10.10,9.98,10.05,120000,1206000\n"
    )


def import_stock_minute_bars_csv(
    csv_text: str,
    *,
    interval: str = "1m",
    source: str = "manual_csv",
    dry_run: bool = False,
    ensure_schema: Callable[[], None],
    database_configured: Callable[[], bool] | None = None,
    upsert: MinuteUpsert | None = None,
) -> dict[str, Any]:
    """Import historical minute bars from CSV text into stock_minute_bars."""

    is_configured = database_configured or is_database_configured
    if not is_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    interval = normalize_minute_interval(interval)
    if not csv_text.strip():
        return {"status": "empty", "rows_read": 0, "rows_written": 0, "rows_skipped": 0, "errors": ["CSV is empty"]}

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    return import_stock_minute_bars_from_reader(
        reader,
        interval=interval,
        source=source,
        dry_run=dry_run,
        ensure_schema=ensure_schema,
        upsert=upsert,
    )


def import_stock_minute_bars_file(
    file_path: str,
    *,
    interval: str = "1m",
    source: str = "manual_csv_file",
    dry_run: bool = False,
    encoding: str = "utf-8-sig",
    project_root: Path,
    allowed_import_dirs: tuple[Path, ...],
    ensure_schema: Callable[[], None],
    database_configured: Callable[[], bool] | None = None,
    upsert: MinuteUpsert | None = None,
) -> dict[str, Any]:
    """Import historical minute bars from an allowed local CSV file path."""

    is_configured = database_configured or is_database_configured
    if not is_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    interval = normalize_minute_interval(interval)
    resolved = allowed_import_file(file_path, project_root=project_root, allowed_import_dirs=allowed_import_dirs)
    with resolved.open("r", encoding=encoding, newline="") as file:
        reader = csv.DictReader(file)
        result = import_stock_minute_bars_from_reader_streaming(
            reader,
            interval=interval,
            source=source,
            dry_run=dry_run,
            ensure_schema=ensure_schema,
            upsert=upsert,
        )
    result["file_path"] = str(resolved.relative_to(project_root))
    return result


def import_stock_minute_bars_from_reader(
    reader: csv.DictReader,
    *,
    interval: str,
    source: str,
    dry_run: bool,
    ensure_schema: Callable[[], None],
    upsert: MinuteUpsert | None = None,
) -> dict[str, Any]:
    if not reader.fieldnames:
        return {"status": "empty", "rows_read": 0, "rows_written": 0, "rows_skipped": 0, "errors": ["CSV header is missing"]}

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    errors: list[str] = []
    rows_read = 0
    rows_skipped = 0
    for row in reader:
        rows_read += 1
        normalized = {normalize_csv_key(key): value for key, value in row.items()}
        try:
            symbol, exchange = minute_csv_symbol_exchange(normalized)
            item = minute_csv_item(normalized)
        except ValueError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"row {rows_read}: {exc}")
            continue
        grouped.setdefault((symbol, exchange), []).append(item)

    rows_written = 0
    if not dry_run:
        ensure_schema()
        upsert_func = upsert or upsert_minute_bars
        for (symbol, exchange), items in grouped.items():
            rows_written += upsert_func(symbol, exchange, items, interval, source)

    return minute_import_result(rows_read, rows_written, rows_skipped, len(grouped), interval, source, dry_run, errors)


def import_stock_minute_bars_from_reader_streaming(
    reader: csv.DictReader,
    *,
    interval: str,
    source: str,
    dry_run: bool,
    ensure_schema: Callable[[], None],
    upsert: MinuteUpsert | None = None,
    batch_size: int = 2000,
) -> dict[str, Any]:
    """Import minute bars from a CSV reader without holding the whole file."""

    if not reader.fieldnames:
        return {"status": "empty", "rows_read": 0, "rows_written": 0, "rows_skipped": 0, "errors": ["CSV header is missing"]}

    errors: list[str] = []
    rows_read = 0
    rows_skipped = 0
    rows_written = 0
    symbol_keys: set[tuple[str, str]] = set()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    upsert_func = upsert or upsert_minute_bars

    if not dry_run:
        ensure_schema()

    def flush(force: bool = False) -> None:
        nonlocal rows_written, grouped
        if not grouped:
            return
        pending_count = sum(len(items) for items in grouped.values())
        if not force and pending_count < batch_size:
            return
        if not dry_run:
            for (symbol, exchange), items in grouped.items():
                rows_written += upsert_func(symbol, exchange, items, interval, source)
        grouped = {}

    for row in reader:
        rows_read += 1
        normalized = {normalize_csv_key(key): value for key, value in row.items()}
        try:
            symbol, exchange = minute_csv_symbol_exchange(normalized)
            item = minute_csv_item(normalized)
        except ValueError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"row {rows_read}: {exc}")
            continue
        key = (symbol, exchange)
        symbol_keys.add(key)
        grouped.setdefault(key, []).append(item)
        flush()

    flush(force=True)
    return minute_import_result(rows_read, rows_written, rows_skipped, len(symbol_keys), interval, source, dry_run, errors)


def minute_import_result(
    rows_read: int,
    rows_written: int,
    rows_skipped: int,
    symbol_count: int,
    interval: str,
    source: str,
    dry_run: bool,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "status": "ready" if rows_read and (rows_written or dry_run) else "empty",
        "interval": interval,
        "source": source,
        "dry_run": dry_run,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "rows_skipped": rows_skipped,
        "symbol_count": symbol_count,
        "errors": errors,
        "required_columns": ["vt_symbol 或 symbol+exchange", "bar_time/trade_date/time/datetime", "open/high/low/close"],
    }


def normalize_minute_interval(value: Any) -> str:
    interval = str(value or "1m").strip().lower()
    if interval not in {"1m", "5m", "15m", "30m", "60m"}:
        raise MinuteImportError(f"Unsupported minute interval: {interval}")
    return interval


def allowed_import_file(file_path: str, *, project_root: Path, allowed_import_dirs: tuple[Path, ...]) -> Path:
    text_path = str(file_path or "").strip()
    if not text_path:
        raise MinuteImportError("CSV file path is empty")
    raw_path = Path(text_path)
    resolved = raw_path if raw_path.is_absolute() else project_root / raw_path
    resolved = resolved.resolve()
    allowed_roots = []
    for directory in allowed_import_dirs:
        directory.mkdir(parents=True, exist_ok=True)
        allowed_roots.append(directory.resolve())
    if not resolved.is_file():
        raise MinuteImportError(f"CSV file not found: {file_path}")
    if resolved.suffix.lower() != ".csv":
        raise MinuteImportError("Only .csv files are allowed")
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        allowed = ", ".join(str(root.relative_to(project_root)) for root in allowed_roots)
        raise MinuteImportError(f"CSV file must be under one of: {allowed}")
    return resolved


def upsert_minute_bars(
    symbol: str,
    exchange: str,
    items: list[dict[str, Any]],
    interval: str,
    source: str = "akshare",
) -> int:
    """Upsert intraday bar rows for one stock."""

    if not items:
        return 0
    normalized = normalize_exchange(symbol, exchange)
    vts = vt_symbol(symbol, normalized)
    written = 0
    with session_scope() as session:
        exists = session.execute(select(schema.stocks.c.vt_symbol).where(schema.stocks.c.vt_symbol == vts)).scalar()
        if not exists:
            return 0
        for item in items:
            bar_time = parse_datetime(item.get("trade_date") or item.get("bar_time") or item.get("time"))
            if bar_time is None:
                continue
            values = {
                "vt_symbol": vts,
                "bar_time": bar_time,
                "interval": interval,
                "trade_date": bar_time.date(),
                "open_price": float(item.get("open") or item.get("open_price") or 0),
                "close_price": float(item.get("close") or item.get("close_price") or 0),
                "high_price": float(item.get("high") or item.get("high_price") or 0),
                "low_price": float(item.get("low") or item.get("low_price") or 0),
                "volume": item.get("volume"),
                "turnover": item.get("turnover"),
                "source": str(item.get("source") or source or "akshare"),
                "raw": item.get("raw") or item,
            }
            existing = session.execute(
                select(schema.stock_minute_bars).where(
                    (schema.stock_minute_bars.c.vt_symbol == vts)
                    & (schema.stock_minute_bars.c.bar_time == bar_time)
                    & (schema.stock_minute_bars.c.interval == interval)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_minute_bars.update()
                    .where(
                        (schema.stock_minute_bars.c.vt_symbol == vts)
                        & (schema.stock_minute_bars.c.bar_time == bar_time)
                        & (schema.stock_minute_bars.c.interval == interval)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_minute_bars.insert().values(**values))
            written += 1
    return written


def normalize_csv_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def minute_csv_symbol_exchange(row: dict[str, Any]) -> tuple[str, str]:
    vt_symbol_value = str(row.get("vt_symbol") or row.get("code_exchange") or "").strip().upper()
    if vt_symbol_value and "." in vt_symbol_value:
        symbol, exchange = vt_symbol_value.split(".", 1)
        return symbol.strip(), exchange.strip()
    symbol = str(row.get("symbol") or row.get("code") or row.get("股票代码") or "").strip()
    exchange = str(row.get("exchange") or row.get("market") or row.get("交易所") or "").strip().upper()
    if not symbol:
        raise ValueError("missing vt_symbol or symbol")
    if not exchange:
        exchange = normalize_exchange(symbol)
    return symbol, exchange


def minute_csv_item(row: dict[str, Any]) -> dict[str, Any]:
    bar_time = (
        row.get("bar_time")
        or row.get("trade_date")
        or row.get("datetime")
        or row.get("time")
        or row.get("date_time")
    )
    if parse_datetime(bar_time) is None:
        raise ValueError("missing or invalid bar_time")
    open_price = required_number(row, "open", "open_price", "开盘")
    high_price = required_number(row, "high", "high_price", "最高")
    low_price = required_number(row, "low", "low_price", "最低")
    close_price = required_number(row, "close", "close_price", "收盘")
    return {
        "trade_date": bar_time,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": optional_number(row, "volume", "vol", "成交量"),
        "turnover": optional_number(row, "turnover", "amount", "成交额"),
        "raw": row,
    }


def required_number(row: dict[str, Any], *keys: str) -> float:
    value = optional_number(row, *keys)
    if value is None:
        raise ValueError(f"missing numeric field: {keys[0]}")
    return value


def optional_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(normalize_csv_key(key))
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"invalid numeric field {key}: {value}") from exc
    return None


def parse_datetime(value: Any) -> datetime | None:
    """Parse common market data datetime strings into a naive local datetime."""

    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text_value = str(value or "").strip()
    if not text_value:
        return None
    text_value = text_value.replace("T", " ").replace("Z", "")
    if "+" in text_value:
        text_value = text_value.split("+", 1)[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text_value).replace(tzinfo=None)
    except ValueError:
        return None
