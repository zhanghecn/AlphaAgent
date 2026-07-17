"""Import vn.py database bars into AlphaAgent research tables."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from vnpy.trader.constant import Interval
from vnpy.trader.database import get_database

from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.data_sync import _upsert_minute_bars
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


def _as_datetime(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time())
    text = str(value)
    if "T" in text or " " in text:
        return datetime.fromisoformat(text.replace("T", " ")[:19])
    return datetime.combine(date.fromisoformat(text[:10]), time())
