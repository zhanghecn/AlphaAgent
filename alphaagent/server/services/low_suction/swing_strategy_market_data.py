"""Free point-in-time quote collection for the low-suction swing strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.models import Quote


@dataclass(frozen=True)
class SwingLiveSnapshot:
    stock_quotes: pd.DataFrame
    concept_quotes: pd.DataFrame
    benchmark_quotes: pd.DataFrame


class SwingMarketDataError(RuntimeError):
    """Raised when a required free intraday quote surface is unavailable."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def collect_signal_market_snapshot(
    leader_rows: pd.DataFrame,
    *,
    captured_at: datetime,
    adapter: AkShareAdapter | Any | None = None,
) -> SwingLiveSnapshot:
    """Collect the stock, concept, and benchmark frames required at 14:50."""

    del captured_at
    required = {"vt_symbol", "sector_id"}
    missing = sorted(required - set(leader_rows.columns))
    if missing:
        raise SwingMarketDataError(
            "leader_quote_scope_invalid",
            "missing leader quote scope columns: " + ", ".join(missing),
        )
    symbols = set(leader_rows["vt_symbol"].astype(str))
    sectors = set(leader_rows["sector_id"].astype(str))
    source = adapter or AkShareAdapter()
    stock_quotes = collect_stock_quotes(symbols, adapter=source)
    concept_quotes = _collect_concept_quotes(sectors, source)
    benchmark_quotes = _collect_benchmark_quotes(source)
    return SwingLiveSnapshot(
        stock_quotes=stock_quotes,
        concept_quotes=concept_quotes,
        benchmark_quotes=benchmark_quotes,
    )


def collect_stock_quotes(
    vt_symbols: set[str] | list[str] | tuple[str, ...],
    *,
    adapter: AkShareAdapter | Any | None = None,
) -> pd.DataFrame:
    """Collect one current quote per requested symbol from the full free snapshot."""

    symbols = {str(symbol) for symbol in vt_symbols if str(symbol)}
    if not symbols:
        return pd.DataFrame(columns=_stock_quote_columns())
    source = adapter or AkShareAdapter()
    try:
        payload = source.all_stock_quotes()
        items = _payload_items(payload)
    except Exception as exc:
        items = _targeted_quote_items(source, symbols, cause=exc)
    rows = [item for item in items if str(item.get("vt_symbol") or "") in symbols]
    found = {str(item.get("vt_symbol") or "") for item in rows}
    missing = symbols - found
    if missing:
        rows.extend(_targeted_quote_items(source, missing))
        found = {str(item.get("vt_symbol") or "") for item in rows}
    missing = sorted(symbols - found)
    if missing:
        raise SwingMarketDataError(
            "intraday_stock_quotes_missing",
            "intraday stock quotes missing: " + ", ".join(missing),
        )
    frame = pd.DataFrame.from_records(rows)
    absent_columns = [column for column in _stock_quote_columns() if column not in frame]
    if absent_columns:
        for column in absent_columns:
            frame[column] = None
    return (
        frame.loc[:, list(_stock_quote_columns())]
        .drop_duplicates("vt_symbol", keep="last")
        .sort_values("vt_symbol", kind="stable")
        .reset_index(drop=True)
    )


def _collect_concept_quotes(
    sector_ids: set[str],
    adapter: AkShareAdapter | Any,
) -> pd.DataFrame:
    try:
        payload = adapter.live_board_quotes("concept", limit=1000)
    except Exception as exc:
        raise SwingMarketDataError(
            "intraday_concept_quotes_unavailable",
            f"intraday concept quotes unavailable: {exc.__class__.__name__}",
        ) from exc
    observed_at = payload.get("updated_at") if isinstance(payload, dict) else None
    if not observed_at:
        raise SwingMarketDataError("intraday_concept_quote_timestamp_missing")
    rows = [
        {
            "sector_id": str(item.get("id") or ""),
            "captured_at": observed_at,
            "change_pct": item.get("change_pct"),
            "source": str(item.get("source") or payload.get("source") or ""),
        }
        for item in _payload_items(payload)
        if str(item.get("id") or "") in sector_ids
    ]
    found = {row["sector_id"] for row in rows}
    missing = sorted(sector_ids - found)
    if missing:
        raise SwingMarketDataError(
            "intraday_concept_quotes_missing",
            "intraday concept quotes missing: " + ", ".join(missing),
        )
    return pd.DataFrame.from_records(
        rows,
        columns=["sector_id", "captured_at", "change_pct", "source"],
    )


def _collect_benchmark_quotes(adapter: AkShareAdapter | Any) -> pd.DataFrame:
    try:
        raw_quotes = adapter.get_indices()
    except Exception as exc:
        raise SwingMarketDataError(
            "intraday_benchmark_quotes_unavailable",
            f"intraday benchmark quotes unavailable: {exc.__class__.__name__}",
        ) from exc
    items = [
        quote.to_api() if isinstance(quote, Quote) else dict(quote)
        for quote in raw_quotes
    ]
    symbols = {"000300.SSE", "000905.SSE", "000852.SSE"}
    rows = [
        {
            "vt_symbol": str(item.get("vt_symbol") or ""),
            "trade_time": item.get("trade_time"),
            "last_price": item.get("last_price"),
            "source": str(item.get("source") or ""),
        }
        for item in items
        if str(item.get("vt_symbol") or "") in symbols
    ]
    found = {row["vt_symbol"] for row in rows}
    missing = sorted(symbols - found)
    if missing:
        raise SwingMarketDataError(
            "intraday_benchmark_quotes_missing",
            "intraday benchmark quotes missing: " + ", ".join(missing),
        )
    return pd.DataFrame.from_records(
        rows,
        columns=["vt_symbol", "trade_time", "last_price", "source"],
    )


def _targeted_quote_items(
    adapter: AkShareAdapter | Any,
    vt_symbols: set[str],
    *,
    cause: Exception | None = None,
) -> list[dict[str, Any]]:
    requests = []
    for vt_symbol in sorted(vt_symbols):
        symbol, separator, exchange = vt_symbol.partition(".")
        if not separator:
            raise SwingMarketDataError("invalid_vt_symbol", vt_symbol)
        requests.append({"symbol": symbol, "exchange": exchange})
    try:
        raw_quotes = adapter.get_quotes(requests)
    except Exception as exc:
        source_error = cause or exc
        raise SwingMarketDataError(
            "intraday_stock_quotes_unavailable",
            f"intraday stock quotes unavailable: {source_error.__class__.__name__}",
        ) from exc
    return [
        quote.to_api() if isinstance(quote, Quote) else dict(quote)
        for quote in raw_quotes
    ]


def _payload_items(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [item for item in (payload.get("items") or []) if isinstance(item, dict)]


def _stock_quote_columns() -> tuple[str, ...]:
    return (
        "vt_symbol",
        "name",
        "trade_time",
        "last_price",
        "open_price",
        "high_price",
        "low_price",
        "previous_close",
        "volume",
        "turnover",
        "source",
    )
