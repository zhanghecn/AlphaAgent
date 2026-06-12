"""Local AlphaAgent market data adapter for vn.py data objects."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import and_, select

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, HistoryRequest

from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope


GATEWAY_NAME = "ALPHAAGENT_LOCAL"


def parse_vt_symbol(vt_symbol: str) -> tuple[str, Exchange]:
    """Parse a vn.py vt_symbol such as 600000.SSE."""

    parts = vt_symbol.strip().upper().split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("vt_symbol must look like 600000.SSE")
    try:
        exchange = Exchange(parts[1])
    except ValueError as exc:
        raise ValueError(f"unsupported exchange: {parts[1]}") from exc
    if exchange not in {Exchange.SSE, Exchange.SZSE, Exchange.BSE}:
        raise ValueError(f"unsupported A-share exchange: {exchange.value}")
    return parts[0], exchange


def history_request(vt_symbol: str, start: date | datetime, end: date | datetime | None = None) -> HistoryRequest:
    """Build a vn.py HistoryRequest for local daily bars."""

    symbol, exchange = parse_vt_symbol(vt_symbol)
    return HistoryRequest(
        symbol=symbol,
        exchange=exchange,
        start=_as_datetime(start),
        end=_as_datetime(end) if end else None,
        interval=Interval.DAILY,
    )


def query_local_daily_bars(
    vt_symbol: str,
    start: date | datetime,
    end: date | datetime | None = None,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Return local daily bars as vn.py BarData objects and API-friendly rows."""

    request = history_request(vt_symbol, start, end)
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured", "items": []}

    end_date = _as_date(end) if end else None
    clauses = [
        schema.stock_daily_bars.c.vt_symbol == request.vt_symbol,
        schema.stock_daily_bars.c.trade_date >= _as_date(start),
    ]
    if end_date is not None:
        clauses.append(schema.stock_daily_bars.c.trade_date <= end_date)

    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars)
            .where(and_(*clauses))
            .order_by(schema.stock_daily_bars.c.trade_date)
            .limit(min(max(limit, 1), 5000))
        ).mappings().all()

    bars = [_row_to_bar(dict(row), request) for row in rows]
    return {
        "status": "ready" if bars else "empty",
        "gateway_name": GATEWAY_NAME,
        "request": {
            "vt_symbol": request.vt_symbol,
            "symbol": request.symbol,
            "exchange": request.exchange.value,
            "interval": request.interval.value if request.interval else None,
            "start": request.start.isoformat(),
            "end": request.end.isoformat() if request.end else None,
        },
        "count": len(bars),
        "items": [_bar_to_api(bar) for bar in bars],
        "note": "本接口只把 AlphaAgent 本地日线表适配为 vn.py BarData；不是官方 vn.py Datafeed，也不提供实时行情或实盘交易。",
    }


def _row_to_bar(row: dict[str, Any], request: HistoryRequest) -> BarData:
    trade_date = _as_date(row["trade_date"])
    return BarData(
        gateway_name=GATEWAY_NAME,
        symbol=request.symbol,
        exchange=request.exchange,
        datetime=datetime.combine(trade_date, time()),
        interval=Interval.DAILY,
        volume=float(row.get("volume") or 0),
        turnover=float(row.get("turnover") or 0),
        open_price=float(row.get("open_price") or 0),
        high_price=float(row.get("high_price") or 0),
        low_price=float(row.get("low_price") or 0),
        close_price=float(row.get("close_price") or 0),
    )


def _bar_to_api(bar: BarData) -> dict[str, Any]:
    return {
        "vt_symbol": bar.vt_symbol,
        "symbol": bar.symbol,
        "exchange": bar.exchange.value,
        "datetime": bar.datetime.isoformat(),
        "interval": bar.interval.value if bar.interval else None,
        "volume": bar.volume,
        "turnover": bar.turnover,
        "open_price": bar.open_price,
        "high_price": bar.high_price,
        "low_price": bar.low_price,
        "close_price": bar.close_price,
        "gateway_name": bar.gateway_name,
    }


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(_as_date(value), time())
