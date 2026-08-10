"""Front-adjusted daily-bar input contract for the isolated low-suction study."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

QFQ_ADJUSTMENT = "qfq"
QFQ_SOURCE = "akshare.stock_zh_a_hist_tx:qfq"
QFQ_PROVIDER_TIMEOUT_SECONDS = 30.0
_REQUIRED_FIELD_ALIASES = {
    "trade_date": ("date", "日期"),
    "open_price": ("open", "开盘"),
    "close_price": ("close", "收盘"),
    "high_price": ("high", "最高"),
    "low_price": ("low", "最低"),
}
_OPTIONAL_FIELD_ALIASES = {
    # Tencent returns ``amount`` in lots rather than a monetary turnover value.
    # Its scale is stable within the source, which is sufficient for the relative
    # volume features in this isolated study.
    "volume": ("amount", "成交量"),
    "turnover": ("turnover", "成交额"),
}


class AdjustedDailyBarError(ValueError):
    """Raised when a qfq response cannot be used as a research input."""


@dataclass(frozen=True)
class AdjustedDailyBar:
    vt_symbol: str
    trade_date: date
    adjustment: str
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float | None
    turnover: float | None
    source: str
    source_fingerprint: str
    raw: dict[str, object]


@dataclass(frozen=True)
class QfqDailyScope:
    """One immutable daily coverage statement for adjusted research prices."""

    trade_date: date
    adjustment: str
    source: str
    request_fingerprint: str
    requested_symbol_count: int
    returned_symbol_count: int
    accepted_symbol_count: int
    excluded_symbol_count: int
    complete: bool
    response_fingerprint: str
    raw: dict[str, object]


def fetch_qfq_daily_bars(
    vt_symbol: str,
    *,
    start_date: date,
    end_date: date,
    history_fetcher: Callable[..., pd.DataFrame] | None = None,
) -> list[AdjustedDailyBar]:
    """Fetch one stock's Tencent AkShare qfq daily bars and normalize it."""

    normalized_symbol = _normalize_vt_symbol(vt_symbol)
    if start_date > end_date:
        raise AdjustedDailyBarError("qfq start_date cannot follow end_date")
    fetcher = history_fetcher or _akshare_stock_zh_a_hist_tx
    try:
        frame = fetcher(
            symbol=_tencent_symbol(normalized_symbol),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust=QFQ_ADJUSTMENT,
            timeout=QFQ_PROVIDER_TIMEOUT_SECONDS,
        )
    except AdjustedDailyBarError:
        raise
    except Exception as exc:
        raise AdjustedDailyBarError(
            f"qfq fetch failed for {normalized_symbol}: {exc.__class__.__name__}"
        ) from exc
    return normalize_qfq_rows(frame, normalized_symbol)


def normalize_qfq_rows(frame: pd.DataFrame, vt_symbol: str) -> list[AdjustedDailyBar]:
    """Normalize one Tencent or legacy AkShare qfq response."""

    if not isinstance(frame, pd.DataFrame):
        raise AdjustedDailyBarError("qfq response must be a pandas DataFrame")
    if any(_first_present_column(frame, aliases) is None for aliases in _REQUIRED_FIELD_ALIASES.values()):
        raise AdjustedDailyBarError("qfq response is missing OHLC columns")
    if frame.empty:
        raise AdjustedDailyBarError("qfq response is empty")

    normalized_symbol = _normalize_vt_symbol(vt_symbol)
    rows: list[AdjustedDailyBar] = []
    seen_dates: set[date] = set()
    for row_index, source_row in enumerate(frame.to_dict(orient="records")):
        trade_date = _required_trade_date(
            _required_field_value(source_row, _REQUIRED_FIELD_ALIASES["trade_date"]),
            row_index,
        )
        if trade_date in seen_dates:
            raise AdjustedDailyBarError(f"qfq response has duplicate date: {trade_date}")
        seen_dates.add(trade_date)

        open_price = _required_positive_float(
            _required_field_value(source_row, _REQUIRED_FIELD_ALIASES["open_price"]),
            "open",
            row_index,
        )
        close_price = _required_positive_float(
            _required_field_value(source_row, _REQUIRED_FIELD_ALIASES["close_price"]),
            "close",
            row_index,
        )
        high_price = _required_positive_float(
            _required_field_value(source_row, _REQUIRED_FIELD_ALIASES["high_price"]),
            "high",
            row_index,
        )
        low_price = _required_positive_float(
            _required_field_value(source_row, _REQUIRED_FIELD_ALIASES["low_price"]),
            "low",
            row_index,
        )
        if high_price < max(open_price, close_price):
            raise AdjustedDailyBarError(
                f"qfq high is below open or close at row {row_index}"
            )
        if low_price > min(open_price, close_price):
            raise AdjustedDailyBarError(
                f"qfq low is above open or close at row {row_index}"
            )

        volume = _optional_nonnegative_float(
            _optional_field_value(source_row, _OPTIONAL_FIELD_ALIASES["volume"]),
            "volume",
            row_index,
        )
        turnover = _optional_nonnegative_float(
            _optional_field_value(source_row, _OPTIONAL_FIELD_ALIASES["turnover"]),
            "turnover",
            row_index,
        )
        raw = {str(key): _json_value(value) for key, value in source_row.items()}
        rows.append(
            AdjustedDailyBar(
                vt_symbol=normalized_symbol,
                trade_date=trade_date,
                adjustment=QFQ_ADJUSTMENT,
                open_price=open_price,
                close_price=close_price,
                high_price=high_price,
                low_price=low_price,
                volume=volume,
                turnover=turnover,
                source=QFQ_SOURCE,
                source_fingerprint=_row_fingerprint(normalized_symbol, raw),
                raw=raw,
            )
        )
    return sorted(rows, key=lambda row: row.trade_date)


def next_market_session_close_label(
    closes_by_date: Mapping[date, object],
    market_calendar: Sequence[date],
    signal_date: date,
) -> float | None:
    """Return the next market session close, without crossing a suspension gap."""

    calendar = _strict_market_calendar(market_calendar)
    try:
        signal_index = calendar.index(signal_date)
    except ValueError:
        return None
    if signal_index + 1 >= len(calendar):
        return None
    if _label_price(closes_by_date.get(signal_date)) is None:
        return None
    return _label_price(closes_by_date.get(calendar[signal_index + 1]))


def build_qfq_daily_scope(
    trade_date: date,
    *,
    expected_symbols: Sequence[str],
    accepted_rows_by_symbol: Mapping[str, AdjustedDailyBar | str],
    fetch_failures: Mapping[str, str] | None = None,
) -> QfqDailyScope:
    """Build a fail-closed daily coverage record from normalized qfq rows.

    The symbol list is intentionally fingerprinted instead of stored verbatim in
    PostgreSQL.  It keeps every daily scope auditable without duplicating a full
    market-wide universe hundreds of times.
    """

    if type(trade_date) is not date:
        raise AdjustedDailyBarError("qfq scope trade_date must be a date")
    symbols = tuple(sorted({_normalize_vt_symbol(symbol) for symbol in expected_symbols}))
    if not symbols:
        raise AdjustedDailyBarError("qfq scope expected_symbols cannot be empty")

    accepted: dict[str, str] = {}
    for raw_symbol, row in accepted_rows_by_symbol.items():
        symbol = _normalize_vt_symbol(raw_symbol)
        if symbol not in symbols:
            raise AdjustedDailyBarError(
                f"qfq row is outside declared scope: {symbol}"
            )
        if isinstance(row, AdjustedDailyBar):
            if row.vt_symbol != symbol or row.trade_date != trade_date:
                raise AdjustedDailyBarError(
                    f"qfq row does not match declared scope: {symbol}"
                )
            if row.adjustment != QFQ_ADJUSTMENT or row.source != QFQ_SOURCE:
                raise AdjustedDailyBarError(
                    f"qfq row has an unexpected source contract: {symbol}"
                )
            accepted[symbol] = row.source_fingerprint
        elif isinstance(row, str) and row.strip():
            accepted[symbol] = row.strip()
        else:
            raise AdjustedDailyBarError(
                f"qfq scope source fingerprint is invalid: {symbol}"
            )

    normalized_failures = {
        _normalize_vt_symbol(symbol): str(reason)
        for symbol, reason in (fetch_failures or {}).items()
        if _normalize_vt_symbol(symbol) in symbols
    }
    accepted_symbols = tuple(sorted(accepted))
    excluded_symbols = tuple(symbol for symbol in symbols if symbol not in accepted)
    request_material = {
        "adjustment": QFQ_ADJUSTMENT,
        "source": QFQ_SOURCE,
        "trade_date": trade_date.isoformat(),
        "symbols": symbols,
    }
    response_material = {
        "adjustment": QFQ_ADJUSTMENT,
        "source": QFQ_SOURCE,
        "trade_date": trade_date.isoformat(),
        "accepted": tuple(
            (symbol, accepted[symbol])
            for symbol in accepted_symbols
        ),
    }
    raw: dict[str, object] = {
        "request": {
            "symbols_sha256": _json_fingerprint(symbols),
            "symbol_examples": list(symbols[:20]),
        },
        "response": {
            "accepted_symbols_sha256": _json_fingerprint(accepted_symbols),
            "excluded_symbols_sha256": _json_fingerprint(excluded_symbols),
            "excluded_examples": list(excluded_symbols[:20]),
        },
        "attempt": {
            "fetch_failure_count": len(normalized_failures),
            "fetch_failure_examples": [
                {"vt_symbol": symbol, "error": normalized_failures[symbol]}
                for symbol in sorted(normalized_failures)[:20]
            ],
        },
    }
    return QfqDailyScope(
        trade_date=trade_date,
        adjustment=QFQ_ADJUSTMENT,
        source=QFQ_SOURCE,
        request_fingerprint=_json_fingerprint(request_material),
        requested_symbol_count=len(symbols),
        returned_symbol_count=len(accepted_symbols),
        accepted_symbol_count=len(accepted_symbols),
        excluded_symbol_count=len(excluded_symbols),
        complete=len(accepted_symbols) == len(symbols),
        response_fingerprint=_json_fingerprint(response_material),
        raw=raw,
    )


def _akshare_stock_zh_a_hist_tx(**kwargs: object) -> pd.DataFrame:
    try:
        # DataSyncRunner initializes AkShareAdapter, which deliberately keeps
        # the top-level package as a lightweight namespace stub. Importing the
        # concrete provider module works in both that path and direct use.
        module = importlib.import_module("akshare.stock_feature.stock_hist_tx")
    except ImportError as exc:
        raise AdjustedDailyBarError("akshare is required for qfq daily bars") from exc
    fetcher = getattr(module, "stock_zh_a_hist_tx", None)
    if not callable(fetcher):
        raise AdjustedDailyBarError("akshare.stock_zh_a_hist_tx is unavailable")
    result = fetcher(**kwargs)
    if not isinstance(result, pd.DataFrame):
        raise AdjustedDailyBarError("akshare qfq response must be a pandas DataFrame")
    return result


def _normalize_vt_symbol(vt_symbol: str) -> str:
    normalized = str(vt_symbol or "").strip().upper()
    symbol, separator, exchange = normalized.partition(".")
    if (
        not separator
        or len(symbol) != 6
        or not symbol.isdigit()
        or not exchange
        or "." in exchange
    ):
        raise AdjustedDailyBarError(f"invalid vt_symbol for qfq daily bars: {normalized or '-'}")
    return normalized


def _tencent_symbol(vt_symbol: str) -> str:
    symbol, exchange = vt_symbol.split(".", maxsplit=1)
    prefix = {"SSE": "sh", "SZSE": "sz"}.get(exchange)
    if prefix is None:
        raise AdjustedDailyBarError(
            f"Tencent qfq daily bars do not support exchange: {exchange}"
        )
    return f"{prefix}{symbol}"


def _first_present_column(frame: pd.DataFrame, aliases: Sequence[str]) -> str | None:
    return next((column for column in aliases if column in frame.columns), None)


def _required_field_value(
    source_row: Mapping[str, object],
    aliases: Sequence[str],
) -> object:
    for column in aliases:
        if column in source_row:
            return source_row[column]
    raise AdjustedDailyBarError("qfq response is missing OHLC columns")


def _optional_field_value(
    source_row: Mapping[str, object],
    aliases: Sequence[str],
) -> object | None:
    return next((source_row[column] for column in aliases if column in source_row), None)


def _required_trade_date(value: object, row_index: int) -> date:
    try:
        parsed = (
            pd.to_datetime(value, unit="ms", errors="raise")
            if isinstance(value, (int, float)) and abs(value) >= 100_000_000_000
            else pd.to_datetime(value, errors="raise")
        )
    except (TypeError, ValueError) as exc:
        raise AdjustedDailyBarError(f"qfq date is invalid at row {row_index}") from exc
    if pd.isna(parsed):
        raise AdjustedDailyBarError(f"qfq date is invalid at row {row_index}")
    return parsed.date()


def _required_positive_float(value: object, field: str, row_index: int) -> float:
    number = _finite_float(value, field, row_index)
    if number <= 0:
        raise AdjustedDailyBarError(f"qfq {field} must be positive at row {row_index}")
    return number


def _optional_nonnegative_float(
    value: object,
    field: str,
    row_index: int,
) -> float | None:
    if _is_missing(value):
        return None
    number = _finite_float(value, field, row_index)
    if number < 0:
        raise AdjustedDailyBarError(f"qfq {field} cannot be negative at row {row_index}")
    return number


def _finite_float(value: object, field: str, row_index: int) -> float:
    if isinstance(value, bool):
        raise AdjustedDailyBarError(f"qfq {field} is not numeric at row {row_index}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AdjustedDailyBarError(f"qfq {field} is not numeric at row {row_index}") from exc
    if not math.isfinite(number):
        raise AdjustedDailyBarError(f"qfq {field} is not finite at row {row_index}")
    return number


def _strict_market_calendar(market_calendar: Sequence[date]) -> tuple[date, ...]:
    calendar = tuple(market_calendar)
    if any(type(trade_date) is not date for trade_date in calendar):
        raise AdjustedDailyBarError("market calendar must contain date values")
    if any(current <= previous for previous, current in zip(calendar, calendar[1:])):
        raise AdjustedDailyBarError("market calendar must be strictly increasing")
    return calendar


def _label_price(value: object) -> float | None:
    if _is_missing(value) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _json_value(value: object) -> object:
    if _is_missing(value):
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        return _json_value(item())
    return str(value)


def _row_fingerprint(vt_symbol: str, raw: Mapping[str, object]) -> str:
    material = {
        "adjustment": QFQ_ADJUSTMENT,
        "source": QFQ_SOURCE,
        "vt_symbol": vt_symbol,
        "raw": raw,
    }
    return _json_fingerprint(material)


def _json_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
