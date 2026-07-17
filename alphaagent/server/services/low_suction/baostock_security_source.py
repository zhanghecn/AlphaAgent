"""BaoStock sources for reconstructed and forward security-status evidence."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from importlib import import_module
from typing import Any, Protocol
from zoneinfo import ZoneInfo

MAX_HISTORY_SYMBOLS = 500
MAX_HISTORY_CALENDAR_DAYS = 3_660
HISTORY_FIELDS = "date,code,tradestatus,isST"
FORWARD_SECURITY_SOURCE = "baostock.query_all_stock.forward"
FORWARD_EVIDENCE_LEVEL = "strict"
FORWARD_CAPTURE_START = time(15, 0)
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAIN_BOARD_PREFIXES = {
    "SSE": ("600", "601", "603", "605"),
    "SZSE": ("000", "001", "002", "003"),
}


class BaoStockSourceError(RuntimeError):
    """Raised when BaoStock cannot provide a complete bounded response."""


class BaoStockResponse(Protocol):
    error_code: str
    error_msg: str


class BaoStockQuery(BaoStockResponse, Protocol):
    fields: list[str]
    day: str

    def next(self) -> bool: ...

    def get_row_data(self) -> list[str]: ...


class BaoStockClient(Protocol):
    def login(self) -> BaoStockResponse: ...

    def logout(self) -> BaoStockResponse: ...

    def query_stock_basic(
        self,
        code: str = "",
        code_name: str = "",
    ) -> BaoStockQuery: ...

    def query_all_stock(self, day: str) -> BaoStockQuery: ...

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> BaoStockQuery: ...


@dataclass(frozen=True)
class SecurityMasterRecord:
    vt_symbol: str
    name: str
    listed_on: date
    delisted_on: date | None
    status: str
    board: str
    source_code: str


@dataclass(frozen=True)
class SecurityMasterResult:
    records: tuple[SecurityMasterRecord, ...]
    observed_at: datetime
    total_source_rows: int
    stock_rows: int
    main_board_rows: int
    delisted_main_board_rows: int


@dataclass(frozen=True)
class ForwardSecurityRecord:
    source_trade_date: date
    vt_symbol: str
    symbol: str
    exchange: str
    name: str
    status: str
    board: str
    listed_on: date
    delisted_on: date | None
    suspended: bool
    risk_warning: bool
    observed_at: datetime
    evidence_level: str
    source: str
    source_record_id: str
    source_code: str
    trade_status: str


@dataclass(frozen=True)
class ForwardSecuritySnapshotResult:
    source_trade_date: date
    observed_at: datetime
    records: tuple[ForwardSecurityRecord, ...]
    total_master_rows: int
    total_daily_rows: int
    expected_symbol_count: int
    returned_symbol_count: int
    suspended_count: int
    risk_warning_count: int
    missing_symbols: tuple[str, ...]
    evidence_level: str = FORWARD_EVIDENCE_LEVEL
    source: str = FORWARD_SECURITY_SOURCE


def fetch_forward_security_snapshot(
    *,
    source_trade_date: date,
    observed_at: datetime,
    client: BaoStockClient | None = None,
) -> ForwardSecuritySnapshotResult:
    """Capture one complete post-close main-board security-status snapshot."""

    observed = _forward_observation_time(
        observed_at,
        source_trade_date=source_trade_date,
    )
    provider = client or _default_client()
    with _authenticated(provider):
        master_rows = _query_rows(
            provider.query_stock_basic(),
            operation="query_stock_basic",
        )
        daily_query = provider.query_all_stock(source_trade_date.isoformat())
        _require_success(daily_query, operation="query_all_stock")
        response_day = str(getattr(daily_query, "day", "") or "").strip()
        if response_day != source_trade_date.isoformat():
            raise BaoStockSourceError(
                "query_all_stock response date does not match requested source date: "
                f"expected={source_trade_date.isoformat()} actual={response_day or '-'}"
            )
        daily_rows = _query_rows(daily_query, operation="query_all_stock")

    expected = _active_main_board_master(
        master_rows,
        source_trade_date=source_trade_date,
    )
    records_by_symbol: dict[str, ForwardSecurityRecord] = {}
    for row in daily_rows:
        vt_symbol = _vt_symbol_from_baostock(row.get("code"))
        if vt_symbol not in expected:
            continue
        if vt_symbol in records_by_symbol:
            raise BaoStockSourceError(
                f"query_all_stock returned duplicate expected code: {vt_symbol}"
            )
        master = expected[vt_symbol]
        records_by_symbol[vt_symbol] = _forward_security_record(
            row,
            master=master,
            source_trade_date=source_trade_date,
            observed_at=observed,
        )

    missing_symbols = tuple(sorted(set(expected) - set(records_by_symbol)))
    if missing_symbols:
        examples = ", ".join(missing_symbols[:20])
        suffix = " ..." if len(missing_symbols) > 20 else ""
        raise BaoStockSourceError(
            "query_all_stock missing active main-board symbols: "
            f"count={len(missing_symbols)} symbols={examples}{suffix}"
        )

    records = tuple(records_by_symbol[key] for key in sorted(records_by_symbol))
    return ForwardSecuritySnapshotResult(
        source_trade_date=source_trade_date,
        observed_at=observed,
        records=records,
        total_master_rows=len(master_rows),
        total_daily_rows=len(daily_rows),
        expected_symbol_count=len(expected),
        returned_symbol_count=len(records),
        suspended_count=sum(record.suspended for record in records),
        risk_warning_count=sum(record.risk_warning for record in records),
        missing_symbols=(),
    )


def fetch_security_master(
    *,
    client: BaoStockClient | None = None,
    observed_at: datetime | None = None,
) -> SecurityMasterResult:
    """Enumerate BaoStock's SSE/SZSE stock master, including delisted rows."""

    observed = _aware_observation_time(observed_at)
    provider = client or _default_client()
    with _authenticated(provider):
        source_rows = _query_rows(
            provider.query_stock_basic(),
            operation="query_stock_basic",
        )

    records: list[SecurityMasterRecord] = []
    stock_rows = 0
    main_board_rows = 0
    delisted_main_board_rows = 0
    for row in source_rows:
        if str(row.get("type") or "").strip() != "1":
            continue
        vt_symbol = _vt_symbol_from_baostock(row.get("code"))
        if vt_symbol is None:
            continue
        stock_rows += 1
        record = _master_record(row, vt_symbol=vt_symbol)
        records.append(record)
        if record.board == "main":
            main_board_rows += 1
            if record.status == "DELISTED":
                delisted_main_board_rows += 1

    return SecurityMasterResult(
        records=tuple(records),
        observed_at=observed,
        total_source_rows=len(source_rows),
        stock_rows=stock_rows,
        main_board_rows=main_board_rows,
        delisted_main_board_rows=delisted_main_board_rows,
    )


def fetch_reconstructed_security_history(
    vt_symbols: Sequence[str],
    *,
    start_date: date,
    end_date: date,
    observed_at: datetime,
    client: BaoStockClient | None = None,
) -> tuple[dict[str, Any], ...]:
    """Fetch daily ST/trading status for a bounded explicit symbol set."""

    symbols = tuple(sorted({str(value).strip().upper() for value in vt_symbols}))
    if not symbols or any(not value for value in symbols):
        raise BaoStockSourceError("at least one vt_symbol is required")
    if len(symbols) > MAX_HISTORY_SYMBOLS:
        raise BaoStockSourceError(
            f"BaoStock history accepts at most {MAX_HISTORY_SYMBOLS} symbols per run"
        )
    if start_date > end_date:
        raise BaoStockSourceError("start_date must not be after end_date")
    if (end_date - start_date).days > MAX_HISTORY_CALENDAR_DAYS:
        raise BaoStockSourceError(
            f"BaoStock history range must not exceed {MAX_HISTORY_CALENDAR_DAYS} days"
        )
    observed = _aware_observation_time(observed_at)
    provider_codes = {
        vt_symbol: _baostock_code(vt_symbol) for vt_symbol in symbols
    }

    provider = client or _default_client()
    normalized: list[dict[str, Any]] = []
    with _authenticated(provider):
        for vt_symbol, provider_code in provider_codes.items():
            master_rows = _query_rows(
                provider.query_stock_basic(code=provider_code),
                operation=f"query_stock_basic({provider_code})",
            )
            if len(master_rows) != 1:
                raise BaoStockSourceError(
                    f"query_stock_basic({provider_code}) returned "
                    f"{len(master_rows)} rows; expected exactly one"
                )
            master = _master_record(master_rows[0], vt_symbol=vt_symbol)
            history_rows = _query_rows(
                provider.query_history_k_data_plus(
                    provider_code,
                    HISTORY_FIELDS,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    frequency="d",
                    adjustflag="3",
                ),
                operation=f"query_history_k_data_plus({provider_code})",
            )
            normalized.extend(
                _normalize_history_rows(
                    history_rows,
                    master=master,
                    provider_code=provider_code,
                    start_date=start_date,
                    end_date=end_date,
                    observed_at=observed,
                )
            )

    return tuple(
        sorted(
            normalized,
            key=lambda row: (str(row["vt_symbol"]), row["valid_from"]),
        )
    )


def _normalize_history_rows(
    rows: Sequence[dict[str, str]],
    *,
    master: SecurityMasterRecord,
    provider_code: str,
    start_date: date,
    end_date: date,
    observed_at: datetime,
) -> list[dict[str, Any]]:
    symbol, exchange = master.vt_symbol.split(".")
    normalized: list[dict[str, Any]] = []
    observed_dates: set[date] = set()
    for row in rows:
        row_code = str(row.get("code") or "").strip().lower()
        if row_code != provider_code:
            raise BaoStockSourceError(
                f"history code mismatch: expected {provider_code}, got {row_code or '-'}"
            )
        trade_date = _required_date(row.get("date"), field="date")
        if not start_date <= trade_date <= end_date:
            raise BaoStockSourceError(
                f"history date {trade_date.isoformat()} is outside requested range"
            )
        if trade_date in observed_dates:
            raise BaoStockSourceError(
                f"duplicate history date for {provider_code}: {trade_date.isoformat()}"
            )
        observed_dates.add(trade_date)
        trade_status = _binary_field(row.get("tradestatus"), field="tradestatus")
        is_st = _binary_field(row.get("isST"), field="isST")
        suspended = trade_status == "0"
        risk_warning = is_st == "1"
        status = "ST" if risk_warning else "SUSPENDED" if suspended else "LISTED"
        normalized.append(
            {
                "vt_symbol": master.vt_symbol,
                "symbol": symbol,
                "exchange": exchange,
                "name": master.name,
                "status": status,
                "board": master.board,
                "listed_on": master.listed_on,
                "delisted_on": master.delisted_on,
                "valid_from": trade_date,
                "valid_to": trade_date + timedelta(days=1),
                "suspended": suspended,
                "risk_warning": risk_warning,
                "known_at": observed_at,
                "evidence_level": "reconstructed",
                "source": "baostock.query_history_k_data_plus",
                "source_record_id": (
                    f"baostock:{provider_code}:{trade_date.isoformat()}"
                ),
            }
        )
    return normalized


def _active_main_board_master(
    rows: Sequence[dict[str, str]],
    *,
    source_trade_date: date,
) -> dict[str, SecurityMasterRecord]:
    records: dict[str, SecurityMasterRecord] = {}
    for row in rows:
        if str(row.get("type") or "").strip() != "1":
            continue
        vt_symbol = _vt_symbol_from_baostock(row.get("code"))
        if vt_symbol is None:
            continue
        record = _master_record(row, vt_symbol=vt_symbol)
        if record.board != "main":
            continue
        if record.listed_on > source_trade_date:
            continue
        if record.delisted_on is not None and record.delisted_on <= source_trade_date:
            continue
        if vt_symbol in records:
            raise BaoStockSourceError(
                f"security master returned duplicate active code: {vt_symbol}"
            )
        records[vt_symbol] = record
    if not records:
        raise BaoStockSourceError(
            "security master has no active main-board symbols for source date"
        )
    return records


def _forward_security_record(
    row: dict[str, str],
    *,
    master: SecurityMasterRecord,
    source_trade_date: date,
    observed_at: datetime,
) -> ForwardSecurityRecord:
    provider_code = str(row.get("code") or "").strip().lower()
    if provider_code != master.source_code:
        raise BaoStockSourceError(
            f"daily code does not match security master: {provider_code or '-'}"
        )
    trade_status = _binary_field(row.get("tradeStatus"), field="tradeStatus")
    name = _required_text(row.get("code_name"), field="code_name")
    suspended = trade_status == "0"
    risk_warning = "ST" in name.upper() or "退" in name
    status = (
        "DELISTING"
        if "退" in name
        else "ST"
        if "ST" in name.upper()
        else "SUSPENDED"
        if suspended
        else "LISTED"
    )
    symbol, exchange = master.vt_symbol.split(".")
    return ForwardSecurityRecord(
        source_trade_date=source_trade_date,
        vt_symbol=master.vt_symbol,
        symbol=symbol,
        exchange=exchange,
        name=name,
        status=status,
        board=master.board,
        listed_on=master.listed_on,
        delisted_on=master.delisted_on,
        suspended=suspended,
        risk_warning=risk_warning,
        observed_at=observed_at,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        source=FORWARD_SECURITY_SOURCE,
        source_record_id=(
            f"baostock-forward:{provider_code}:{source_trade_date.isoformat()}"
        ),
        source_code=provider_code,
        trade_status=trade_status,
    )


def _master_record(
    row: dict[str, str],
    *,
    vt_symbol: str,
) -> SecurityMasterRecord:
    provider_code = str(row.get("code") or "").strip().lower()
    if _vt_symbol_from_baostock(provider_code) != vt_symbol:
        raise BaoStockSourceError(
            f"security master code does not match requested symbol {vt_symbol}"
        )
    listed_on = _required_date(row.get("ipoDate"), field="ipoDate")
    delisted_on = _optional_date(row.get("outDate"), field="outDate")
    raw_status = str(row.get("status") or "").strip()
    if raw_status not in {"0", "1"}:
        raise BaoStockSourceError("security master status must be 0 or 1")
    return SecurityMasterRecord(
        vt_symbol=vt_symbol,
        name=_required_text(row.get("code_name"), field="code_name"),
        listed_on=listed_on,
        delisted_on=delisted_on,
        status=("DELISTED" if raw_status == "0" or delisted_on else "LISTED"),
        board=_board(vt_symbol),
        source_code=provider_code,
    )


def _query_rows(
    query: BaoStockQuery,
    *,
    operation: str,
) -> list[dict[str, str]]:
    _require_success(query, operation=operation)
    fields = [str(field).strip() for field in query.fields]
    if not fields or any(not field for field in fields) or len(fields) != len(set(fields)):
        raise BaoStockSourceError(f"{operation} returned invalid fields")
    rows: list[dict[str, str]] = []
    while query.next():
        values = query.get_row_data()
        if len(values) != len(fields):
            raise BaoStockSourceError(
                f"{operation} returned a row with {len(values)} values for "
                f"{len(fields)} fields"
            )
        rows.append(dict(zip(fields, values, strict=True)))
    _require_success(query, operation=operation)
    return rows


@contextmanager
def _authenticated(client: BaoStockClient) -> Iterator[None]:
    with redirect_stdout(StringIO()):
        login = client.login()
    _require_success(login, operation="login")
    try:
        yield
    finally:
        active_exception = sys.exc_info()[0] is not None
        with redirect_stdout(StringIO()):
            logout = client.logout()
        if not active_exception:
            _require_success(logout, operation="logout")


def _require_success(response: BaoStockResponse, *, operation: str) -> None:
    error_code = str(getattr(response, "error_code", "") or "")
    if error_code == "0":
        return
    message = str(getattr(response, "error_msg", "") or "provider error")[:200]
    raise BaoStockSourceError(f"BaoStock {operation} failed ({error_code}): {message}")


def _default_client() -> BaoStockClient:
    try:
        return import_module("baostock")
    except ImportError as exc:
        raise BaoStockSourceError(
            "BaoStock is not installed; install the server dependency group"
        ) from exc


def _vt_symbol_from_baostock(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    prefix, separator, symbol = text.partition(".")
    exchange = {"sh": "SSE", "sz": "SZSE"}.get(prefix)
    if not separator or exchange is None or len(symbol) != 6 or not symbol.isdigit():
        return None
    return f"{symbol}.{exchange}"


def _baostock_code(vt_symbol: str) -> str:
    symbol, separator, exchange = vt_symbol.partition(".")
    prefix = {"SSE": "sh", "SZSE": "sz"}.get(exchange)
    if (
        not separator
        or prefix is None
        or len(symbol) != 6
        or not symbol.isdigit()
    ):
        raise BaoStockSourceError(f"unsupported vt_symbol: {vt_symbol}")
    return f"{prefix}.{symbol}"


def _board(vt_symbol: str) -> str:
    symbol, exchange = vt_symbol.split(".")
    if symbol.startswith(MAIN_BOARD_PREFIXES.get(exchange, ())):
        return "main"
    if exchange == "SZSE" and symbol.startswith(("300", "301")):
        return "chinext"
    if exchange == "SSE" and symbol.startswith("688"):
        return "star"
    return "other"


def _aware_observation_time(value: datetime | None) -> datetime:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise BaoStockSourceError("observed_at must include a timezone")
    return observed


def _forward_observation_time(
    value: datetime,
    *,
    source_trade_date: date,
) -> datetime:
    observed = _aware_observation_time(value)
    local_observed = observed.astimezone(SHANGHAI)
    if local_observed.date() != source_trade_date:
        raise BaoStockSourceError(
            "forward observation must use the same Shanghai date as source_trade_date"
        )
    if local_observed.time().replace(tzinfo=None) < FORWARD_CAPTURE_START:
        raise BaoStockSourceError("forward observation must be captured post-close")
    return observed


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BaoStockSourceError(f"security master {field} is required")
    return text


def _required_date(value: Any, *, field: str) -> date:
    parsed = _optional_date(value, field=field)
    if parsed is None:
        raise BaoStockSourceError(f"BaoStock {field} is required")
    return parsed


def _optional_date(value: Any, *, field: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise BaoStockSourceError(
            f"BaoStock {field} must be an ISO date"
        ) from exc


def _binary_field(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if text not in {"0", "1"}:
        raise BaoStockSourceError(f"BaoStock {field} must be 0 or 1")
    return text
