"""Bounded TDX historical transaction data for pre-board research."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any

from alphaagent.server.services.vnpy_integration.local_data import parse_vt_symbol


TRANSACTION_PAGE_SIZE = 2_000
TDX_MAX_START = 65_500
VALID_DIRECTION_CODES = frozenset({0, 1, 2})
FIRST_TRADE_TIME = "09:25"
LAST_TRADE_TIME = "15:00"
PRICE_READY_TOLERANCE = 0.011
PRICE_DEGRADED_TOLERANCE = 0.051
LARGE_PRINT_YUAN = 1_000_000.0
VERY_LARGE_PRINT_YUAN = 5_000_000.0


def _connect_tdx(**kwargs):
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        _connect_tdx as connect,
    )

    return connect(**kwargs)


def _disconnect_tdx(api: Any) -> None:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        _disconnect_tdx as disconnect,
    )

    disconnect(api)


def _tdx_market(exchange: str) -> int:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        _tdx_market as market_code,
    )

    return market_code(exchange)


def fetch_history_transactions(
    vt_symbol: str,
    trade_date: date,
    *,
    max_pages: int = 32,
    page_size: int = TRANSACTION_PAGE_SIZE,
    timeout_seconds: float = 3.0,
) -> dict[str, object]:
    """Fetch and normalize one bounded stock-day transaction tape."""

    symbol, exchange = parse_vt_symbol(vt_symbol)
    market = _tdx_market(exchange.value)
    bounded_page_size, bounded_pages = _bounded_pagination(page_size, max_pages)
    api = None
    try:
        api, host = _connect_tdx(
            timeout_seconds=timeout_seconds,
            probe=(8, market, symbol),
        )
        return _fetch_history_result(
            api,
            host=host,
            vt_symbol=vt_symbol,
            market=market,
            symbol=symbol,
            trade_date=trade_date,
            max_pages=bounded_pages,
            page_size=bounded_page_size,
        )
    finally:
        if api is not None:
            _disconnect_tdx(api)


def iter_history_transactions(
    requests: Sequence[tuple[str, date]],
    *,
    max_pages: int = 32,
    page_size: int = TRANSACTION_PAGE_SIZE,
    timeout_seconds: float = 3.0,
):
    """Yield bounded stock-day tapes while reusing one TDX connection."""

    normalized = sorted(
        {(str(symbol), trade_date) for symbol, trade_date in requests},
        key=lambda pair: (pair[1], pair[0]),
    )
    if not normalized:
        return
    first_symbol, _ = normalized[0]
    first_code, first_exchange = parse_vt_symbol(first_symbol)
    bounded_page_size, bounded_pages = _bounded_pagination(page_size, max_pages)
    api, host = _connect_tdx(
        timeout_seconds=timeout_seconds,
        probe=(8, _tdx_market(first_exchange.value), first_code),
    )
    try:
        for vt_symbol, trade_date in normalized:
            symbol, exchange = parse_vt_symbol(vt_symbol)
            yield _fetch_history_result(
                api,
                host=host,
                vt_symbol=vt_symbol,
                market=_tdx_market(exchange.value),
                symbol=symbol,
                trade_date=trade_date,
                max_pages=bounded_pages,
                page_size=bounded_page_size,
            )
    finally:
        _disconnect_tdx(api)


def _fetch_history_result(
    api: Any,
    *,
    host: Mapping[str, object],
    vt_symbol: str,
    market: int,
    symbol: str,
    trade_date: date,
    max_pages: int,
    page_size: int,
) -> dict[str, object]:
    pages = _fetch_history_pages(
        api,
        market=market,
        symbol=symbol,
        trade_date=trade_date,
        max_pages=max_pages,
        page_size=page_size,
    )
    rows = normalize_history_pages(pages, trade_date=trade_date)
    pagination_complete = history_pages_complete(
        pages,
        page_size=page_size,
        max_pages=max_pages,
    )
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date.isoformat(),
        "source": "tdx.history_transaction",
        "host": dict(host),
        "page_count": len(pages),
        "raw_row_count": sum(len(page) for page in pages),
        "trade_row_count": len(rows),
        "pagination_complete": pagination_complete,
        "pagination_truncated": not pagination_complete,
        "rows": rows,
    }


def _bounded_pagination(page_size: int, max_pages: int) -> tuple[int, int]:
    bounded_page_size = min(max(int(page_size), 1), TRANSACTION_PAGE_SIZE)
    bounded_pages = min(
        max(int(max_pages), 1),
        max(TDX_MAX_START // bounded_page_size + 1, 1),
    )
    return bounded_page_size, bounded_pages


def normalize_history_pages(
    pages: Sequence[Sequence[Mapping[str, object]]],
    *,
    trade_date: date,
) -> list[dict[str, object]]:
    """Normalize newest-page-first TDX rows into chronological trades."""

    normalized: list[dict[str, object]] = []
    for page in reversed(pages):
        for raw in page:
            time_text = _trade_time(raw.get("time"))
            price = _positive_number(raw.get("price"))
            volume = _positive_number(raw.get("vol"))
            direction = _integer(raw.get("buyorsell"))
            if (
                time_text is None
                or not FIRST_TRADE_TIME <= time_text <= LAST_TRADE_TIME
                or price is None
                or volume is None
                or direction not in VALID_DIRECTION_CODES
            ):
                continue
            observed_at = datetime.combine(
                trade_date,
                datetime.strptime(time_text, "%H:%M").time(),
            )
            normalized.append(
                {
                    "trade_date": trade_date,
                    "observed_at": observed_at,
                    "time": time_text,
                    "price": price,
                    "volume": volume,
                    "turnover": round(price * volume * 100.0, 4),
                    "direction_code": direction,
                    "source": "tdx.history_transaction",
                    "raw": dict(raw),
                }
            )
    for sequence, row in enumerate(normalized):
        row["sequence"] = sequence
    return normalized


def validate_transaction_day(
    rows: Sequence[Mapping[str, object]],
    daily_bar: Mapping[str, object],
    *,
    pagination_complete: bool = True,
) -> dict[str, object]:
    """Validate flow completeness separately from secondary price differences."""

    ordered = sorted(rows, key=lambda row: int(row.get("sequence") or 0))
    prices = [value for row in ordered if (value := _positive_number(row.get("price")))]
    volumes = [
        value for row in ordered if (value := _positive_number(row.get("volume")))
    ]
    expected_volume = _positive_number(daily_bar.get("volume"))
    expected_high = _positive_number(daily_bar.get("high_price"))
    expected_low = _positive_number(daily_bar.get("low_price"))
    expected_close = _positive_number(daily_bar.get("close_price"))
    if not prices or not volumes or None in {
        expected_volume,
        expected_high,
        expected_low,
        expected_close,
    }:
        return {
            "status": "invalid",
            "row_count": len(ordered),
            "reasons": ["missing_trade_or_daily_values"],
        }

    observed_volume = sum(volumes)
    observed_high = max(prices)
    observed_low = min(prices)
    observed_close = prices[-1]
    volume_difference = abs(observed_volume - expected_volume)
    high_difference = abs(observed_high - expected_high)
    low_difference = abs(observed_low - expected_low)
    close_difference = abs(observed_close - expected_close)
    volume_matches = volume_difference <= 0.001
    price_differences = (high_difference, low_difference, close_difference)
    degraded_prices = all(value <= PRICE_DEGRADED_TOLERANCE for value in price_differences)
    ready_prices = all(value <= PRICE_READY_TOLERANCE for value in price_differences)
    price_audit_status = (
        "ready"
        if ready_prices
        else "degraded"
        if degraded_prices
        else "invalid"
    )
    first_time = str(ordered[0].get("time") or "")
    last_time = str(ordered[-1].get("time") or "")
    reasons: list[str] = []
    if not pagination_complete:
        reasons.append("pagination_truncated")
    if not volume_matches:
        reasons.append("daily_volume_mismatch")
    if close_difference > PRICE_READY_TOLERANCE:
        reasons.append("daily_close_mismatch")
    if first_time != FIRST_TRADE_TIME:
        reasons.append("opening_print_missing")
    if last_time != LAST_TRADE_TIME:
        reasons.append("closing_print_missing")
    return {
        "status": "flow_ready" if not reasons else "invalid",
        "reasons": reasons,
        "row_count": len(ordered),
        "pagination_complete": bool(pagination_complete),
        "first_time": first_time,
        "last_time": last_time,
        "volume_matches": volume_matches,
        "observed_volume": round(observed_volume, 4),
        "expected_volume": expected_volume,
        "volume_difference": round(volume_difference, 6),
        "observed_high": observed_high,
        "expected_high": expected_high,
        "high_difference": round(high_difference, 6),
        "observed_low": observed_low,
        "expected_low": expected_low,
        "low_difference": round(low_difference, 6),
        "observed_close": observed_close,
        "expected_close": expected_close,
        "close_difference": round(close_difference, 6),
        "price_audit_status": price_audit_status,
    }


def aggregate_transaction_minutes(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Aggregate normalized transaction rows without crossing minute boundaries."""

    grouped: dict[datetime, list[Mapping[str, object]]] = defaultdict(list)
    for row in _rows_with_price_moves(rows):
        observed_at = row.get("observed_at")
        if isinstance(observed_at, datetime):
            grouped[observed_at.replace(second=0, microsecond=0)].append(row)
    return _aggregate_transaction_groups(grouped)


def aggregate_transaction_close_minutes(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Map trades to the causal close labels used by stored one-minute bars."""

    grouped: dict[datetime, list[Mapping[str, object]]] = defaultdict(list)
    for row in _rows_with_price_moves(rows):
        observed_at = row.get("observed_at")
        if not isinstance(observed_at, datetime):
            continue
        bar_time = _transaction_bar_close(observed_at)
        if bar_time is not None:
            grouped[bar_time].append(row)
    return _aggregate_transaction_groups(grouped)


def _aggregate_transaction_groups(
    grouped: Mapping[datetime, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    """Aggregate already-aligned chronological transaction groups."""

    result: list[dict[str, object]] = []
    for bar_time in sorted(grouped):
        minute_rows = list(grouped[bar_time])
        prices = [float(row["price"]) for row in minute_rows]
        volumes = [float(row["volume"]) for row in minute_rows]
        turnovers = [float(row["turnover"]) for row in minute_rows]
        direction_volumes = {
            code: sum(
                float(row["volume"])
                for row in minute_rows
                if row.get("direction_code") == code
            )
            for code in sorted(VALID_DIRECTION_CODES)
        }
        direction_turnovers = {
            code: sum(
                float(row["turnover"])
                for row in minute_rows
                if row.get("direction_code") == code
            )
            for code in sorted(VALID_DIRECTION_CODES)
        }
        result.append(
            {
                "trade_date": bar_time.date(),
                "bar_time": bar_time,
                "open_price": prices[0],
                "high_price": max(prices),
                "low_price": min(prices),
                "close_price": prices[-1],
                "volume": round(sum(volumes), 4),
                "turnover": round(sum(turnovers), 4),
                "trade_count": len(minute_rows),
                "max_print_turnover": max(turnovers),
                "large_print_count": sum(
                    value >= LARGE_PRINT_YUAN for value in turnovers
                ),
                "large_print_turnover": round(
                    sum(value for value in turnovers if value >= LARGE_PRINT_YUAN),
                    4,
                ),
                "very_large_print_count": sum(
                    value >= VERY_LARGE_PRINT_YUAN for value in turnovers
                ),
                "very_large_print_turnover": round(
                    sum(
                        value for value in turnovers if value >= VERY_LARGE_PRINT_YUAN
                    ),
                    4,
                ),
                **{
                    f"direction_{code}_volume": round(direction_volumes[code], 4)
                    for code in sorted(VALID_DIRECTION_CODES)
                },
                **{
                    f"direction_{code}_turnover": round(
                        direction_turnovers[code],
                        4,
                    )
                    for code in sorted(VALID_DIRECTION_CODES)
                },
                "price_up_turnover": round(
                    sum(
                        float(row["turnover"])
                        for row in minute_rows
                        if int(row.get("price_move") or 0) > 0
                    ),
                    4,
                ),
                "price_down_turnover": round(
                    sum(
                        float(row["turnover"])
                        for row in minute_rows
                        if int(row.get("price_move") or 0) < 0
                    ),
                    4,
                ),
                "price_flat_turnover": round(
                    sum(
                        float(row["turnover"])
                        for row in minute_rows
                        if int(row.get("price_move") or 0) == 0
                    ),
                    4,
                ),
                "absolute_price_path": round(
                    sum(float(row.get("absolute_price_change") or 0.0) for row in minute_rows),
                    6,
                ),
                "signed_price_path": round(
                    sum(float(row.get("price_change") or 0.0) for row in minute_rows),
                    6,
                ),
                "source_cutoff_time": max(str(row.get("time") or "") for row in minute_rows),
                "source": "tdx.history_transaction",
            }
        )
    return result


def history_pages_complete(
    pages: Sequence[Sequence[Mapping[str, object]]],
    *,
    page_size: int,
    max_pages: int,
) -> bool:
    """Return true only when a short terminal page proves pagination ended."""

    bounded_size = max(int(page_size), 1)
    bounded_pages = max(int(max_pages), 1)
    return bool(pages) and len(pages) <= bounded_pages and len(pages[-1]) < bounded_size


def _rows_with_price_moves(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ordered = sorted(rows, key=lambda item: int(item.get("sequence") or 0))
    result: list[dict[str, object]] = []
    previous_price: float | None = None
    for raw in ordered:
        price = _positive_number(raw.get("price"))
        if price is None:
            continue
        change = 0.0 if previous_price is None else price - previous_price
        result.append(
            {
                **dict(raw),
                "price_move": 1 if change > 0 else -1 if change < 0 else 0,
                "price_change": change,
                "absolute_price_change": abs(change),
            }
        )
        previous_price = price
    return result


def _transaction_bar_close(observed_at: datetime) -> datetime | None:
    """Return the stored one-minute close label for one minute-resolution print."""

    observed = observed_at.replace(second=0, microsecond=0)
    value = observed.time()
    if value == time(9, 25):
        return datetime.combine(observed.date(), time(9, 31))
    if time(9, 30) <= value <= time(11, 28):
        return observed + timedelta(minutes=1)
    if time(11, 29) <= value <= time(11, 30):
        return datetime.combine(observed.date(), time(11, 30))
    if time(13, 0) <= value <= time(14, 29):
        return observed + timedelta(minutes=1)
    return None


def _fetch_history_pages(
    api: Any,
    *,
    market: int,
    symbol: str,
    trade_date: date,
    max_pages: int,
    page_size: int,
) -> list[list[Mapping[str, object]]]:
    pages: list[list[Mapping[str, object]]] = []
    date_number = int(trade_date.strftime("%Y%m%d"))
    for page_index in range(max_pages):
        start = page_index * page_size
        if start > TDX_MAX_START:
            break
        rows = api.get_history_transaction_data(
            market,
            symbol,
            start,
            page_size,
            date_number,
        ) or []
        pages.append([dict(row) for row in rows if isinstance(row, Mapping)])
        if len(rows) < page_size:
            break
    return pages


def _trade_time(value: object) -> str | None:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def _positive_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) and parsed > 0 else None


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
