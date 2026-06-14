"""Strict 14:30 minute-gap parsing and vendor manifest helpers."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select

from alphaagent.market.symbols import normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope


class MinuteGapError(RuntimeError):
    """Raised for invalid strict 14:30 minute-gap inputs."""


def strict_gap_interval(value: Any) -> str:
    interval = str(value or "1m").strip().lower()
    if interval not in {"1m", "1", "1min", "1分钟"}:
        raise MinuteGapError("Strict 14:30 gap workflows only support 1m snapshots")
    return "1m"


def load_minute_gap_requirements(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    allowed_import_file: Callable[[str], Path],
) -> dict[str, Any]:
    """Load strict-tail gap requirements from inline CSV text or an allowed file."""

    if str(file_path or "").strip():
        resolved = allowed_import_file(file_path)
        with resolved.open("r", encoding="utf-8-sig", newline="") as file:
            return parse_minute_gap_reader(csv.DictReader(file))
    if not str(gap_csv_text or "").strip():
        return {"items": [], "rows_read": 0, "rows_skipped": 0, "errors": ["CSV is empty"]}
    return parse_minute_gap_requirements(gap_csv_text)


def parse_minute_gap_requirements(gap_csv_text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(gap_csv_text.lstrip("\ufeff")))
    return parse_minute_gap_reader(reader)


def parse_minute_gap_reader(reader: csv.DictReader) -> dict[str, Any]:
    if not reader.fieldnames:
        return {"items": [], "rows_read": 0, "rows_skipped": 0, "errors": ["CSV header is missing"]}

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    errors: list[str] = []
    rows_read = 0
    rows_skipped = 0
    for row in reader:
        rows_read += 1
        normalized = {normalize_csv_key(key): value for key, value in row.items()}
        try:
            vt_symbol_value = str(normalized.get("vt_symbol") or "").strip().upper()
            if not vt_symbol_value:
                symbol, exchange = minute_csv_symbol_exchange(normalized)
                vt_symbol_value = vt_symbol(symbol, normalize_exchange(symbol, exchange))
            trade_date = parse_date(
                normalized.get("trade_date")
                or normalized.get("bar_date")
                or normalized.get("date")
            )
            if trade_date is None:
                raise ValueError("missing or invalid trade_date")
            key = (vt_symbol_value, trade_date)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "vt_symbol": vt_symbol_value,
                    "trade_date": trade_date,
                    "reference_date": parse_date(normalized.get("reference_date")),
                    "ma5": optional_number(normalized, "ma5"),
                    "window": str(normalized.get("window") or "").strip(),
                }
            )
        except ValueError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"row {rows_read}: {exc}")
    return {"items": items, "rows_read": rows_read, "rows_skipped": rows_skipped, "errors": errors}


def minute_gap_import_template(gap_csv_text: str, *, sample_limit: int = 200) -> str:
    """Build a minute-bar import template scoped to rows from a gap CSV."""

    parsed = parse_minute_gap_requirements(gap_csv_text)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["vt_symbol", "bar_time", "open", "high", "low", "close", "volume", "turnover"])
    seen: set[tuple[str, date]] = set()
    for item in parsed["items"]:
        key = (item["vt_symbol"], item["trade_date"])
        if key in seen:
            continue
        seen.add(key)
        writer.writerow([item["vt_symbol"], f"{item['trade_date'].isoformat()} 14:30:00", "", "", "", "", "", ""])
        if len(seen) >= max(sample_limit, 1):
            break
    return "\ufeff" + buffer.getvalue()


def minute_gap_vendor_manifest(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    sample_limit: int = 20,
    allowed_import_file: Callable[[str], Path],
) -> dict[str, Any]:
    """Build a provider-facing request manifest from a strict-tail gap CSV."""

    requirements = load_minute_gap_requirements(gap_csv_text, file_path=file_path, allowed_import_file=allowed_import_file)
    items = requirements["items"]
    rows = minute_gap_vendor_rows(items, tail_entry_start, tail_entry_end)
    symbols = sorted({row["vt_symbol"] for row in rows})
    dates = sorted({row["trade_date"] for row in rows})
    return {
        "status": "ready" if rows else "empty",
        "rows_read": requirements["rows_read"],
        "rows_skipped": requirements["rows_skipped"],
        "errors": requirements["errors"],
        "request_count": len(rows),
        "symbol_count": len(symbols),
        "date_count": len(dates),
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "start_date": dates[0].isoformat() if dates else None,
        "end_date": dates[-1].isoformat() if dates else None,
        "symbols": symbols[:500],
        "dates": [item.isoformat() for item in dates[:500]],
        "sample_rows": [vendor_row_to_api(row) for row in rows[: max(sample_limit, 1)]],
        "required_import_columns": ["vt_symbol", "bar_time", "open", "high", "low", "close", "volume", "turnover"],
        "provider_notes": [
            "每个 vt_symbol + trade_date 需要覆盖 tail_start 至 tail_end 的真实 1 分钟 K 线。",
            "AlphaAgent 导入 CSV 使用 vt_symbol,bar_time,open,high,low,close,volume,turnover。",
            "Tushare Pro 可按 ts_code + start_date/end_date + freq=1min 拉取；返回行必须属于目标 trade_date。",
            "vn.py 数据库可按 symbol/exchange/Interval.MINUTE 查询同一窗口后通过 /api/vnpy/import-minute-bars/gaps 导入。",
        ],
    }


def minute_gap_vendor_manifest_csv(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    allowed_import_file: Callable[[str], Path],
) -> str:
    """Return a provider-facing CSV request list for strict-tail gaps."""

    requirements = load_minute_gap_requirements(gap_csv_text, file_path=file_path, allowed_import_file=allowed_import_file)
    rows = minute_gap_vendor_rows(requirements["items"], tail_entry_start, tail_entry_end)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "vt_symbol",
            "symbol",
            "exchange",
            "tushare_ts_code",
            "trade_date",
            "tail_start",
            "tail_end",
            "start_datetime",
            "end_datetime",
            "reference_date",
            "ma5",
            "alphaagent_import_columns",
            "note",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["vt_symbol"],
                row["symbol"],
                row["exchange"],
                row["tushare_ts_code"],
                row["trade_date"].isoformat(),
                row["tail_start"],
                row["tail_end"],
                row["start_datetime"],
                row["end_datetime"],
                row["reference_date"].isoformat() if row.get("reference_date") else "",
                row.get("ma5") if row.get("ma5") is not None else "",
                "vt_symbol,bar_time,open,high,low,close,volume,turnover",
                "return all real 1m bars in [tail_start, tail_end] for this symbol-date",
            ]
        )
    return "\ufeff" + buffer.getvalue()


def audit_minute_gap_requirements(
    requirements: dict[str, Any],
    *,
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
    min_tail_bars: int,
    coverage_counts: Callable[[list[dict[str, Any]], str, str, str], dict[tuple[str, date], int]] | None = None,
) -> dict[str, Any]:
    """Check whether parsed strict-tail gaps are covered by local minute bars."""

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
            row["missing_reason"] = "no_tail_window_minute_bars" if count == 0 else "insufficient_tail_window_minute_bars"
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
            "strict_tail_backtest_ready"
            if not missing
            else f"import historical {interval} bars for missing_symbols/missing_dates, then rerun audit and strict backtest"
        ),
    }


def minute_gap_coverage_counts(
    items: list[dict[str, Any]],
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
) -> dict[tuple[str, date], int]:
    """Count local minute bars that cover each strict-tail gap row."""

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
                func.to_char(schema.stock_minute_bars.c.bar_time, "HH24:MI") >= start_time,
                func.to_char(schema.stock_minute_bars.c.bar_time, "HH24:MI") <= end_time,
            )
            .group_by(schema.stock_minute_bars.c.vt_symbol, schema.stock_minute_bars.c.trade_date)
        ).mappings().all()
    return {(str(row["vt_symbol"]), row["trade_date"]): int(row["bar_count"] or 0) for row in rows}


def minute_gap_vendor_rows(items: list[dict[str, Any]], tail_entry_start: str, tail_entry_end: str) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, date]] = set()
    start_time = parse_time_value(tail_entry_start)
    end_time = parse_time_value(tail_entry_end)
    for item in sorted(items, key=lambda value: (value["trade_date"], value["vt_symbol"])):
        key = (item["vt_symbol"], item["trade_date"])
        if key in seen:
            continue
        seen.add(key)
        symbol, exchange = split_vt_symbol(item["vt_symbol"])
        rows.append(
            {
                "vt_symbol": item["vt_symbol"],
                "symbol": symbol,
                "exchange": exchange,
                "tushare_ts_code": tushare_ts_code(symbol, exchange),
                "trade_date": item["trade_date"],
                "tail_start": start_time,
                "tail_end": end_time,
                "start_datetime": f"{item['trade_date'].isoformat()} {start_time}:00",
                "end_datetime": f"{item['trade_date'].isoformat()} {end_time}:00",
                "reference_date": item.get("reference_date"),
                "ma5": item.get("ma5"),
            }
        )
    return rows


def minute_gap_rows_to_api(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append(
            {
                **row,
                "trade_date": row["trade_date"].isoformat() if isinstance(row.get("trade_date"), date) else row.get("trade_date"),
                "reference_date": row["reference_date"].isoformat() if isinstance(row.get("reference_date"), date) else row.get("reference_date"),
            }
        )
    return result


def split_vt_symbol(value: str) -> tuple[str, str]:
    parts = str(value or "").strip().upper().split(".")
    if len(parts) != 2:
        return str(value or "").strip().upper(), ""
    return parts[0], parts[1]


def tushare_ts_code(symbol: str, exchange: str) -> str:
    suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(exchange, exchange)
    return f"{symbol}.{suffix}" if symbol and suffix else symbol


def vendor_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "trade_date": row["trade_date"].isoformat() if isinstance(row.get("trade_date"), date) else row.get("trade_date"),
        "reference_date": row["reference_date"].isoformat() if isinstance(row.get("reference_date"), date) else row.get("reference_date"),
    }


def parse_time_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("time is empty")
    try:
        parsed = datetime.strptime(text[:5], "%H:%M")
    except ValueError as exc:
        raise ValueError(f"invalid HH:MM time: {text}") from exc
    return parsed.strftime("%H:%M")


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


def parse_date(value: Any) -> date | None:
    """Parse various date formats into a date object."""

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
