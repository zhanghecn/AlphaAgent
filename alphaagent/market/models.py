"""Typed market data models used by the API layer."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Quote:
    symbol: str
    exchange: str
    vt_symbol: str
    name: str
    last_price: float | None
    change: float | None
    change_pct: float | None
    open_price: float | None
    high_price: float | None
    low_price: float | None
    previous_close: float | None
    volume: float | None
    turnover: float | None
    market_cap: float | None
    pe: float | None
    pb: float | None
    turnover_rate: float | None
    industry: str | None
    area: str | None
    trade_time: str | None
    source: str

    def to_api(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "vt_symbol": self.vt_symbol,
            "name": self.name,
            "last_price": self.last_price,
            "change": self.change,
            "change_pct": self.change_pct,
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "previous_close": self.previous_close,
            "volume": self.volume,
            "turnover": self.turnover,
            "market_cap": self.market_cap,
            "pe": self.pe,
            "pb": self.pb,
            "turnover_rate": self.turnover_rate,
            "industry": self.industry,
            "area": self.area,
            "trade_time": self.trade_time,
            "source": self.source,
        }


@dataclass(frozen=True)
class Bar:
    trade_date: date | datetime
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float
    turnover: float | None
    change_pct: float | None

    def to_api(self) -> dict[str, object]:
        if isinstance(self.trade_date, datetime):
            trade_date = self.trade_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            trade_date = self.trade_date.isoformat()
        return {
            "trade_date": trade_date,
            "open": self.open_price,
            "close": self.close_price,
            "high": self.high_price,
            "low": self.low_price,
            "volume": self.volume,
            "turnover": self.turnover,
            "change_pct": self.change_pct,
        }


@dataclass(frozen=True)
class DataSourceStatus:
    name: str
    ok: bool
    message: str
    checked_at: datetime

    def to_api(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "message": self.message,
            "checked_at": self.checked_at.isoformat(),
        }
