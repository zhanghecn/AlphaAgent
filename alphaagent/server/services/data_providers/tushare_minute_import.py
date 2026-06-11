"""Tushare Pro minute-bar importer for strict-tail backtest gaps."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import requests

from alphaagent.server.core.config import get_settings
from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.data_sync import (
    _audit_minute_gap_requirements,
    _upsert_minute_bars,
    load_minute_gap_requirements,
)
from alphaagent.server.services.vnpy_integration.local_data import parse_vt_symbol


SUPPORTED_INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "60min"}


def import_tushare_minute_bars_for_gaps(
    *,
    gap_csv_text: str = "",
    gap_file_path: str = "",
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:57",
    dry_run: bool = True,
    max_gaps: int = 200,
) -> dict[str, Any]:
    """Fetch Tushare Pro stk_mins bars for strict-tail gap rows."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}

    settings = get_settings()
    token = settings.tushare_token.strip()
    if not token:
        return {
            "status": "unavailable",
            "message": "TUSHARE_TOKEN not configured",
            "note": "需要 Tushare Pro token 且开通分钟数据权限后，才能按缺口补真实历史 1 分钟线。",
        }

    interval_key = str(interval or "1m").strip().lower()
    ts_freq = SUPPORTED_INTERVALS.get(interval_key)
    if ts_freq is None:
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

    items = requirements["items"][: min(max(int(max_gaps or 200), 1), 5000)]
    rows_read = 0
    rows_written = 0
    empty_requests = 0
    request_errors: list[str] = []
    skipped_wrong_date = 0
    symbols: set[str] = set()
    dates: set[date] = set()

    for item in items:
        vt_symbol = item["vt_symbol"]
        trade_date = item["trade_date"]
        symbols.add(vt_symbol)
        dates.add(trade_date)
        try:
            symbol, exchange = parse_vt_symbol(vt_symbol)
            ts_code = _ts_code(symbol, exchange.value)
            bars = _query_stk_mins(
                token=token,
                api_url=settings.tushare_api_url,
                timeout=float(settings.tushare_timeout_seconds),
                ts_code=ts_code,
                freq=ts_freq,
                start_dt=datetime.combine(trade_date, _as_time(tail_entry_start)),
                end_dt=datetime.combine(trade_date, _as_time(tail_entry_end)),
            )
        except Exception as exc:
            if len(request_errors) < 20:
                request_errors.append(f"{vt_symbol} {trade_date.isoformat()}: {exc.__class__.__name__}")
            continue

        if not bars:
            empty_requests += 1
            continue

        normalized = []
        for row in bars:
            bar_time = _parse_ts_datetime(row.get("trade_time") or row.get("trade_date") or row.get("datetime"))
            if bar_time is None or bar_time.date() != trade_date:
                skipped_wrong_date += 1
                continue
            normalized.append(
                {
                    "trade_date": bar_time,
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("vol") or row.get("volume"),
                    "turnover": row.get("amount") or row.get("turnover"),
                    "source": "tushare_stk_mins",
                    "raw": {**row, "ts_code": ts_code, "freq": ts_freq},
                }
            )
        rows_read += len(normalized)
        if not normalized:
            empty_requests += 1
            continue
        if not dry_run:
            rows_written += _upsert_minute_bars(symbol, exchange.value, normalized, interval_key, "tushare_stk_mins")

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
        "tushare_freq": ts_freq,
        "dry_run": dry_run,
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "gap_count": len(requirements["items"]),
        "processed_gap_count": len(items),
        "unprocessed_gap_count": max(len(requirements["items"]) - len(items), 0),
        "symbol_count": len(symbols),
        "date_count": len(dates),
        "rows_read": rows_read,
        "rows_written": rows_written,
        "empty_request_count": empty_requests,
        "rows_skipped": requirements["rows_skipped"] + skipped_wrong_date,
        "wrong_date_row_count": skipped_wrong_date,
        "errors": [*requirements["errors"], *request_errors],
        "audit_after": audit_after,
        "source": "tushare_stk_mins",
        "note": "使用 Tushare Pro stk_mins 接口按缺口补历史分钟线；需要 token 和分钟数据权限。",
    }


def _query_stk_mins(
    *,
    token: str,
    api_url: str,
    timeout: float,
    ts_code: str,
    freq: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict[str, Any]]:
    payload = {
        "api_name": "stk_mins",
        "token": token,
        "params": {
            "ts_code": ts_code,
            "freq": freq,
            "start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "fields": "ts_code,trade_time,open,close,high,low,vol,amount",
    }
    response = requests.post(api_url, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if data.get("code") not in {0, "0", None}:
        raise RuntimeError(str(data.get("msg") or data.get("message") or "Tushare error"))
    inner = data.get("data") or {}
    fields = inner.get("fields") or []
    items = inner.get("items") or []
    return [dict(zip(fields, row, strict=False)) for row in items]


def _ts_code(symbol: str, exchange: str) -> str:
    suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(exchange)
    if suffix is None:
        raise ValueError(f"unsupported exchange for Tushare: {exchange}")
    return f"{symbol}.{suffix}"


def _as_time(value: str) -> time:
    text = str(value or "").strip()
    if not text:
        raise ValueError("time is empty")
    return datetime.strptime(text[:5], "%H:%M").time()


def _parse_ts_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("T", " ")[:19])
    except ValueError:
        return None
