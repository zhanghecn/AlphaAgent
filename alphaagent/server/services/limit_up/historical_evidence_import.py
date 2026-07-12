"""Historical limit-event and opening-auction evidence imports."""

from __future__ import annotations

import csv
import io
import re
import time as time_module
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import func, select

from alphaagent.server.core.config import get_settings
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services import market_snapshot_repository
from alphaagent.server.services.limit_up.data_quality import get_limit_up_data_quality
from alphaagent.server.services.limit_up.domain import is_eligible_main_board, main_board_limit_price


SHANGHAI = ZoneInfo("Asia/Shanghai")
CANONICAL_EVENT_SOURCE = "akshare.stock_ztb_em"
DATASETS = frozenset({"events", "auction"})
EVENT_PROVIDER_START = date(2020, 1, 1)
AUCTION_PROVIDER_START = date(2025, 1, 1)
MIN_EVENT_COVERAGE_PCT = 90.0
MIN_AUCTION_COVERAGE_PCT = 95.0
MAX_IMPORT_DATES = 100
MAX_ERROR_ITEMS = 30
THS_HISTORY_TRADING_DAYS = 252
THS_PAGE_SIZE = 200
THS_MAX_PAGES = 20
THS_TIMEOUT_SECONDS = 10.0
THS_REQUEST_DELAY_SECONDS = 0.15
THS_BASE_URL = "https://data.10jqka.com.cn/dataapi/limit_up"
THS_REFERER = "https://data.10jqka.com.cn/limit_up/"
THS_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/136.0 Safari/537.36"
)
THS_FIELDS = (
    "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,"
    "1968584,19,3475914,9003,9004"
)
THS_POOL_PATHS = {
    "limit_up": "limit_up_pool",
    "open_limit": "open_limit_pool",
}

EVENT_FIELDS = (
    "trade_date",
    "ts_code",
    "name",
    "limit_type",
    "first_time",
    "last_time",
    "open_times",
    "fd_amount",
    "limit_times",
    "industry",
    "close",
    "pct_chg",
    "amount",
    "turnover_ratio",
    "up_stat",
)
AUCTION_FIELDS = (
    "trade_date",
    "ts_code",
    "name",
    "price",
    "pre_close",
    "vol",
    "amount",
    "turnover_rate",
    "volume_ratio",
    "float_share",
    "unmatched_volume",
    "unmatched_side",
    "source_quote_time",
)

TUSHARE_FIELDS = {
    "events": (
        "trade_date,ts_code,industry,name,close,pct_chg,amount,float_mv,total_mv,"
        "turnover_ratio,fd_amount,first_time,last_time,open_times,up_stat,limit_times,limit"
    ),
    "auction": (
        "trade_date,ts_code,vol,price,amount,pre_close,turnover_rate,volume_ratio,float_share"
    ),
}
TUSHARE_API_NAMES = {"events": "limit_list_d", "auction": "stk_auction"}


class HistoricalEvidenceImportError(RuntimeError):
    """Raised for invalid or unsafe historical evidence input."""


class TushareQueryError(HistoricalEvidenceImportError):
    """Raised when Tushare rejects or fails a request."""


class ThsQueryError(HistoricalEvidenceImportError):
    """Raised when the public Tonghuashun pool response is incomplete or invalid."""


def normalize_event_rows(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    expected_date: date,
    eligible_stocks: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize one complete provider event response for a trade date."""

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[str] = []
    skipped = 0
    duplicates = 0
    for index, source_row in enumerate(source_rows, start=2):
        normalized, reason = _normalize_event_row(source_row, expected_date, eligible_stocks)
        if reason == "ineligible_stock":
            skipped += 1
            continue
        if reason:
            _append_error(errors, f"row {index}: {reason}")
            continue
        assert normalized is not None
        key = (normalized["vt_symbol"], normalized["event_type"])
        if key in rows:
            duplicates += 1
        rows[key] = normalized
    return _normalization_result(rows.values(), errors, skipped, duplicates)


def normalize_auction_rows(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    expected_date: date,
    eligible_stocks: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize one complete provider auction response for a trade date."""

    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    skipped = 0
    duplicates = 0
    for index, source_row in enumerate(source_rows, start=2):
        normalized, reason = _normalize_auction_row(source_row, expected_date, eligible_stocks)
        if reason == "ineligible_stock":
            skipped += 1
            continue
        if reason:
            _append_error(errors, f"row {index}: {reason}")
            continue
        assert normalized is not None
        key = normalized["vt_symbol"]
        if key in rows:
            duplicates += 1
        rows[key] = normalized
    return _normalization_result(rows.values(), errors, skipped, duplicates)


def import_csv_evidence(
    *,
    dataset: str,
    csv_text: str,
    dry_run: bool = True,
    eligible_stocks: Mapping[str, str] | None = None,
    expected_event_symbols: Mapping[date, set[str]] | None = None,
    expected_auction_symbols: Mapping[date, set[str]] | None = None,
) -> dict[str, Any]:
    """Audit and optionally persist a complete vendor CSV export."""

    normalized_dataset = normalize_dataset(dataset)
    source_rows = _read_csv_rows(csv_text)
    rows_by_date, date_errors = _group_source_rows_by_date(source_rows)
    if eligible_stocks is None:
        _require_database()
        eligible_stocks = load_eligible_stocks()
    dates = sorted(rows_by_date)
    expected = _expected_symbols(
        normalized_dataset,
        dates,
        expected_event_symbols=expected_event_symbols,
        expected_auction_symbols=expected_auction_symbols,
        eligible_stocks=eligible_stocks,
    )
    result = _import_grouped_rows(
        normalized_dataset,
        rows_by_date,
        eligible_stocks=eligible_stocks,
        expected_symbols=expected,
        dry_run=dry_run,
    )
    result["rows_read"] = len(source_rows)
    result["errors"] = [*date_errors, *result["errors"]][:MAX_ERROR_ITEMS]
    return result


def import_tushare_evidence(
    *,
    dataset: str,
    start_date: date,
    end_date: date,
    dry_run: bool = True,
    max_dates: int = 20,
    only_missing: bool = True,
) -> dict[str, Any]:
    """Backfill bounded missing trade dates from Tushare Pro."""

    normalized_dataset = normalize_dataset(dataset)
    if not is_database_configured():
        return _unavailable_result(normalized_dataset, "DATABASE_URL not configured")
    settings = get_settings()
    token = settings.tushare_token.strip()
    if not token:
        return _unavailable_result(normalized_dataset, "TUSHARE_TOKEN not configured")
    _validate_date_range(start_date, end_date)

    eligible_stocks = load_eligible_stocks()
    dates = select_import_dates(
        normalized_dataset,
        start_date=start_date,
        end_date=end_date,
        max_dates=max_dates,
        only_missing=only_missing,
    )
    expected = _expected_symbols(
        normalized_dataset,
        dates,
        eligible_stocks=eligible_stocks,
    )
    rows_by_date: dict[date, list[dict[str, Any]]] = {}
    provider_errors: list[dict[str, str]] = []
    for trade_date in dates:
        try:
            rows_by_date[trade_date] = query_tushare_evidence(
                normalized_dataset,
                trade_date=trade_date,
                token=token,
                api_url=settings.tushare_api_url,
                timeout=float(settings.tushare_timeout_seconds),
            )
        except Exception as exc:
            provider_errors.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "status": "provider_error",
                    "reason": _safe_provider_error(exc),
                }
            )

    result = _import_grouped_rows(
        normalized_dataset,
        rows_by_date,
        eligible_stocks=eligible_stocks,
        expected_symbols=expected,
        dry_run=dry_run,
    )
    result.update(
        {
            "provider": "tushare",
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
            "candidate_date_count": len(dates),
            "provider_error_count": len(provider_errors),
            "date_results": sorted(
                [*result["date_results"], *provider_errors],
                key=lambda item: item["trade_date"],
            ),
        }
    )
    if provider_errors and result["status"] == "ready":
        result["status"] = "partial"
    elif provider_errors and not rows_by_date:
        result["status"] = "error"
    return result


def import_ths_evidence(
    *,
    max_dates: int = THS_HISTORY_TRADING_DAYS,
    only_missing: bool = True,
    progress: Callable[[dict[str, Any]], None] | None = None,
    request_delay_seconds: float = THS_REQUEST_DELAY_SECONDS,
    http_session: Any | None = None,
) -> dict[str, Any]:
    """Backfill the public 252-trading-day Tonghuashun event window.

    Each date is independently audited against local daily limit touches and
    committed in one transaction only when coverage reaches the event gate.
    Provider failures and incomplete dates therefore preserve existing rows.
    """

    if not is_database_configured():
        return _ths_unavailable_result("DATABASE_URL not configured")
    _require_database()
    cap = min(max(int(max_dates or THS_HISTORY_TRADING_DAYS), 1), THS_HISTORY_TRADING_DAYS)
    eligible_stocks = load_eligible_stocks()
    trade_dates = select_ths_import_dates(max_dates=cap, only_missing=only_missing)
    expected = load_expected_event_symbols(trade_dates, eligible_stocks=eligible_stocks)
    total_dates = len(trade_dates)
    _report_ths_progress(
        progress,
        stage="准备同花顺历史证据",
        current=0,
        total=total_dates,
        rows_read=0,
        rows_written=0,
        message=f"待处理 {total_dates} 个交易日",
    )
    if not trade_dates:
        return {
            "status": "up_to_date",
            "dataset": "events",
            "provider": "ths",
            "dry_run": False,
            "date_count": 0,
            "accepted_date_count": 0,
            "provider_error_count": 0,
            "coverage_incomplete_count": 0,
            "rows_read": 0,
            "rows_accepted": 0,
            "rows_written": 0,
            "date_results": [],
            "errors": [],
            "message": "同花顺近252个交易日证据已覆盖，无缺失日期",
        }

    owns_session = http_session is None
    client = http_session or requests.Session()
    date_results: list[dict[str, Any]] = []
    errors: list[str] = []
    rows_read = 0
    rows_accepted = 0
    rows_written = 0
    provider_error_count = 0
    coverage_incomplete_count = 0
    try:
        for index, trade_date in enumerate(trade_dates, start=1):
            _report_ths_progress(
                progress,
                stage="读取同花顺涨停与炸板池",
                current=index - 1,
                total=total_dates,
                current_label=trade_date.isoformat(),
                rows_read=rows_read,
                rows_written=rows_written,
            )
            try:
                pools = query_ths_event_pools(
                    trade_date=trade_date,
                    session=client,
                    timeout=THS_TIMEOUT_SECONDS,
                )
                source_rows = ths_pool_rows_to_source_rows(
                    limit_up_rows=pools["limit_up"],
                    open_limit_rows=pools["open_limit"],
                    trade_date=trade_date,
                )
                normalized = normalize_event_rows(
                    source_rows,
                    expected_date=trade_date,
                    eligible_stocks=eligible_stocks,
                )
                audit = _coverage_audit(
                    "events",
                    normalized["rows"],
                    expected.get(trade_date),
                )
                date_rows_read = len(source_rows)
                date_rows_accepted = int(normalized["accepted_count"])
                date_rows_written = 0
                rows_read += date_rows_read
                rows_accepted += date_rows_accepted
                errors.extend(normalized["errors"])
                if audit["status"] == "ready":
                    date_rows_written = replace_event_evidence(
                        trade_date,
                        normalized["rows"],
                    )
                    rows_written += date_rows_written
                else:
                    coverage_incomplete_count += 1
                date_result = {
                    "trade_date": trade_date.isoformat(),
                    "status": audit["status"],
                    "rows_read": date_rows_read,
                    "rows_accepted": date_rows_accepted,
                    "rows_written": date_rows_written,
                    "skipped_count": normalized["skipped_count"],
                    "error_count": normalized["error_count"],
                    "limit_up_count": len(pools["limit_up"]),
                    "open_limit_count": len(pools["open_limit"]),
                    **audit,
                }
            except Exception as exc:
                provider_error_count += 1
                reason = _safe_provider_error(exc)
                _append_error(errors, f"{trade_date.isoformat()}: {reason}")
                date_result = {
                    "trade_date": trade_date.isoformat(),
                    "status": "provider_error",
                    "rows_read": 0,
                    "rows_accepted": 0,
                    "rows_written": 0,
                    "reason": reason,
                }
            date_results.append(date_result)
            _report_ths_progress(
                progress,
                stage="审计并写入同花顺证据",
                current=index,
                total=total_dates,
                current_label=(
                    f"{trade_date.isoformat()} · {_evidence_status_text(date_result['status'])}"
                ),
                rows_read=rows_read,
                rows_written=rows_written,
                sample_items=[
                    {
                        "trade_date": trade_date.isoformat(),
                        "title": (
                            f"{_evidence_status_text(date_result['status'])} · "
                            f"覆盖 {date_result.get('coverage_pct', 0)}%"
                        ),
                    }
                ],
            )
            if request_delay_seconds > 0 and index < total_dates:
                time_module.sleep(float(request_delay_seconds))
    finally:
        if owns_session:
            client.close()

    ready_count = sum(item.get("status") == "ready" for item in date_results)
    if ready_count == total_dates:
        status = "ready"
    elif ready_count:
        status = "partial"
    elif provider_error_count == total_dates:
        status = "error"
    else:
        status = "rejected"
    message = (
        f"同花顺近252日补数：通过 {ready_count}/{total_dates}，"
        f"供应商错误 {provider_error_count}，覆盖不足 {coverage_incomplete_count}，"
        f"写入 {rows_written} 条"
    )
    return {
        "status": status,
        "dataset": "events",
        "provider": "ths",
        "dry_run": False,
        "requested_start": trade_dates[0].isoformat(),
        "requested_end": trade_dates[-1].isoformat(),
        "candidate_date_count": total_dates,
        "date_count": total_dates,
        "accepted_date_count": ready_count,
        "provider_error_count": provider_error_count,
        "coverage_incomplete_count": coverage_incomplete_count,
        "rows_read": rows_read,
        "rows_accepted": rows_accepted,
        "rows_written": rows_written,
        "date_results": date_results,
        "errors": errors[:MAX_ERROR_ITEMS],
        "message": message,
    }


def query_ths_event_pools(
    *,
    trade_date: date,
    session: Any | None = None,
    timeout: float = THS_TIMEOUT_SECONDS,
) -> dict[str, list[dict[str, Any]]]:
    """Read both final-sealed and failed-board pools for one trade date."""

    limit_up_rows = query_ths_event_pool(
        "limit_up",
        trade_date=trade_date,
        session=session,
        timeout=timeout,
    )
    open_limit_rows = query_ths_event_pool(
        "open_limit",
        trade_date=trade_date,
        session=session,
        timeout=timeout,
    )
    sealed_codes = {str(row.get("code") or "") for row in limit_up_rows}
    failed_codes = {str(row.get("code") or "") for row in open_limit_rows}
    overlap = sorted((sealed_codes & failed_codes) - {""})
    if overlap:
        raise ThsQueryError(
            f"Tonghuashun pools overlap for {trade_date.isoformat()}: {overlap[:5]}"
        )
    return {"limit_up": limit_up_rows, "open_limit": open_limit_rows}


def query_ths_event_pool(
    pool: str,
    *,
    trade_date: date,
    session: Any | None = None,
    timeout: float = THS_TIMEOUT_SECONDS,
    page_size: int = THS_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Read and validate all pages of one Tonghuashun limit-event pool."""

    normalized_pool = str(pool or "").strip().lower()
    path = THS_POOL_PATHS.get(normalized_pool)
    if path is None:
        raise ThsQueryError(f"unsupported Tonghuashun pool: {pool}")
    safe_page_size = min(max(int(page_size or THS_PAGE_SIZE), 1), THS_PAGE_SIZE)
    client = session or requests
    rows: list[dict[str, Any]] = []
    expected_total: int | None = None
    seen_codes: set[str] = set()
    for page in range(1, THS_MAX_PAGES + 1):
        try:
            response = client.get(
                f"{THS_BASE_URL}/{path}",
                headers={"User-Agent": THS_USER_AGENT, "Referer": THS_REFERER},
                params={
                    "page": page,
                    "limit": safe_page_size,
                    "field": THS_FIELDS,
                    "filter": "HS",
                    "date": trade_date.strftime("%Y%m%d"),
                    "order_field": "330324",
                    "order_type": 0,
                },
                timeout=float(timeout),
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise ThsQueryError(
                f"Tonghuashun {normalized_pool} request failed: {exc.__class__.__name__}"
            ) from exc
        if not isinstance(body, Mapping):
            raise ThsQueryError(f"Tonghuashun {normalized_pool} returned a non-object body")
        if body.get("status_code") not in {0, "0"}:
            reason = str(body.get("status_msg") or "provider rejected request")
            raise ThsQueryError(f"Tonghuashun {normalized_pool}: {reason[:200]}")
        data = body.get("data")
        if not isinstance(data, Mapping):
            raise ThsQueryError(f"Tonghuashun {normalized_pool} response has no data object")
        response_date = _date_value(data.get("date"))
        if response_date != trade_date:
            raise ThsQueryError(
                f"Tonghuashun {normalized_pool} date mismatch: {data.get('date')}"
            )
        page_info = data.get("page")
        if not isinstance(page_info, Mapping):
            raise ThsQueryError(f"Tonghuashun {normalized_pool} response has no page metadata")
        response_page = _int_or_none(page_info.get("page"))
        total = _int_or_none(page_info.get("total"))
        if response_page != page or total is None or total < 0:
            raise ThsQueryError(f"Tonghuashun {normalized_pool} page metadata is invalid")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ThsQueryError(f"Tonghuashun {normalized_pool} total changed during pagination")
        items = data.get("info")
        if not isinstance(items, list):
            raise ThsQueryError(f"Tonghuashun {normalized_pool} response has invalid info rows")
        if not items and len(rows) < expected_total:
            raise ThsQueryError(f"Tonghuashun {normalized_pool} pagination ended early")
        for item in items:
            if not isinstance(item, Mapping):
                raise ThsQueryError(f"Tonghuashun {normalized_pool} contains a non-object row")
            code = str(item.get("code") or "").strip()
            if not code:
                raise ThsQueryError(f"Tonghuashun {normalized_pool} row has no code")
            if code in seen_codes:
                raise ThsQueryError(f"Tonghuashun {normalized_pool} duplicated code {code}")
            seen_codes.add(code)
            rows.append(dict(item))
        if len(rows) >= expected_total:
            break
    if expected_total is None or len(rows) != expected_total:
        raise ThsQueryError(
            f"Tonghuashun {normalized_pool} pagination incomplete: "
            f"{len(rows)}/{expected_total if expected_total is not None else '?'}"
        )
    return rows


def ths_pool_rows_to_source_rows(
    *,
    limit_up_rows: Sequence[Mapping[str, Any]],
    open_limit_rows: Sequence[Mapping[str, Any]],
    trade_date: date,
) -> list[dict[str, Any]]:
    """Convert Tonghuashun pool fields into the canonical event normalizer input."""

    result: list[dict[str, Any]] = []
    for pool, rows in (("limit_up", limit_up_rows), ("open_limit", open_limit_rows)):
        failed_board = pool == "open_limit"
        for source_row in rows:
            open_times = _int_or_none(source_row.get("open_num"))
            if failed_board:
                open_times = max(open_times or 0, 1)
            elif open_times is None:
                open_times = 0
            source = f"ths.{THS_POOL_PATHS[pool]}"
            result.append(
                {
                    "trade_date": trade_date.strftime("%Y%m%d"),
                    "ts_code": source_row.get("code"),
                    "name": source_row.get("name"),
                    "limit_type": "Z" if failed_board else "U",
                    "first_time": _ths_limit_time(
                        source_row.get("first_limit_up_time"),
                        trade_date,
                    ),
                    "last_time": _ths_limit_time(
                        source_row.get("last_limit_up_time"),
                        trade_date,
                    ),
                    "open_times": open_times,
                    "fd_amount": _float_or_none(source_row.get("order_amount")),
                    "limit_times": _ths_limit_times(source_row.get("high_days")),
                    "close": _float_or_none(source_row.get("latest")),
                    "pct_chg": _float_or_none(source_row.get("change_rate")),
                    "amount": _float_or_none(source_row.get("turnover")),
                    "turnover_ratio": _float_or_none(source_row.get("turnover_rate")),
                    "up_stat": _text_or_none(source_row.get("high_days")),
                    "source": source,
                    "涨停原因": _text_or_none(source_row.get("reason_type")),
                    "涨停形态": _text_or_none(source_row.get("limit_up_type")),
                    "近一年封板率": _float_or_none(source_row.get("limit_up_suc_rate")),
                    "封单量": _float_or_none(source_row.get("order_volume")),
                    "流通市值": _float_or_none(source_row.get("currency_value")),
                    "分时路径": source_row.get("time_preview"),
                    "同花顺原始字段": dict(source_row),
                }
            )
    return result


def select_ths_import_dates(
    *,
    max_dates: int = THS_HISTORY_TRADING_DAYS,
    only_missing: bool = True,
) -> list[date]:
    """Select missing dates inside the provider's latest 252-session window."""

    cap = min(max(int(max_dates or THS_HISTORY_TRADING_DAYS), 1), THS_HISTORY_TRADING_DAYS)
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= 3000)
            .order_by(schema.stock_daily_bars.c.trade_date.desc())
            .limit(THS_HISTORY_TRADING_DAYS)
        ).scalars().all()
    window = sorted(value for value in rows if isinstance(value, date))
    if only_missing and window:
        existing = load_existing_evidence_dates("events", window[0], window[-1])
        window = [value for value in window if value not in existing]
    return window[:cap]


def historical_evidence_status() -> dict[str, Any]:
    """Return provider configuration and current strict-gate coverage."""

    settings = get_settings()
    quality = get_limit_up_data_quality() if is_database_configured() else {}
    source_counts = quality.get("source_counts") if isinstance(quality, Mapping) else {}
    source_counts = source_counts if isinstance(source_counts, Mapping) else {}
    return {
        "status": "ready" if is_database_configured() else "unavailable",
        "provider": {
            "id": "tushare",
            "configured": bool(settings.tushare_token.strip()),
            "api_url": settings.tushare_api_url,
            "token_exposed": False,
        },
        "ths_provider": {
            "id": "ths",
            "configured": True,
            "history_trade_days": THS_HISTORY_TRADING_DAYS,
            "minimum_coverage_pct": MIN_EVENT_COVERAGE_PCT,
            "pools": list(THS_POOL_PATHS.values()),
        },
        "datasets": {
            "events": {
                "label": "涨停/炸板路径",
                "api_name": TUSHARE_API_NAMES["events"],
                "provider_start": EVENT_PROVIDER_START.isoformat(),
                "coverage": source_counts.get("events") or {},
                "minimum_coverage_pct": MIN_EVENT_COVERAGE_PCT,
            },
            "auction": {
                "label": "开盘集合竞价",
                "api_name": TUSHARE_API_NAMES["auction"],
                "provider_start": AUCTION_PROVIDER_START.isoformat(),
                "coverage": source_counts.get("auction") or {},
                "minimum_coverage_pct": MIN_AUCTION_COVERAGE_PCT,
            },
        },
        "csv_import_available": True,
        "limitations": [
            "同花顺公开历史接口只覆盖最近252个交易日，不能当作500日全历史。",
            "Tushare竞价没有未匹配量，只能形成部分竞价证据。",
            "历史导入时间与行情发生时点分开保存，不能冒充当时实时采集。",
            "Tick/L2队列和逐日概念成员未补齐前，模拟执行门禁继续关闭。",
        ],
    }


def evidence_csv_template(dataset: str) -> str:
    """Return a UTF-8-BOM CSV template for one evidence dataset."""

    normalized = normalize_dataset(dataset)
    fields = EVENT_FIELDS if normalized == "events" else AUCTION_FIELDS
    sample = _event_template_sample() if normalized == "events" else _auction_template_sample()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerow(sample)
    return "\ufeff" + buffer.getvalue()


def query_tushare_evidence(
    dataset: str,
    *,
    trade_date: date,
    token: str,
    api_url: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Query one complete Tushare dataset for one trade date."""

    normalized = normalize_dataset(dataset)
    payload = {
        "api_name": TUSHARE_API_NAMES[normalized],
        "token": token,
        "params": {"trade_date": trade_date.strftime("%Y%m%d")},
        "fields": TUSHARE_FIELDS[normalized],
    }
    response = requests.post(api_url, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if body.get("code") not in {0, "0", None}:
        raise TushareQueryError(str(body.get("msg") or body.get("message") or "Tushare error"))
    data = body.get("data") or {}
    fields = data.get("fields") or []
    items = data.get("items") or []
    return [dict(zip(fields, item, strict=False)) for item in items]


def select_import_dates(
    dataset: str,
    *,
    start_date: date,
    end_date: date,
    max_dates: int,
    only_missing: bool,
) -> list[date]:
    """Select bounded reliable trade dates in chronological order."""

    normalized = normalize_dataset(dataset)
    _validate_date_range(start_date, end_date)
    provider_start = EVENT_PROVIDER_START if normalized == "events" else AUCTION_PROVIDER_START
    effective_start = max(start_date, provider_start)
    cap = min(max(int(max_dates or 20), 1), MAX_IMPORT_DATES)
    if effective_start > end_date:
        return []

    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .where(schema.stock_daily_bars.c.trade_date.between(effective_start, end_date))
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= 3000)
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).scalars().all()
    dates = [value for value in rows if isinstance(value, date)]
    if only_missing:
        existing = load_existing_evidence_dates(normalized, effective_start, end_date)
        dates = [value for value in dates if value not in existing]
    return dates[:cap]


def load_existing_evidence_dates(dataset: str, start_date: date, end_date: date) -> set[date]:
    normalized = normalize_dataset(dataset)
    if normalized == "auction":
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_auction_snapshots.c.trade_date)
                .where(schema.stock_auction_snapshots.c.trade_date.between(start_date, end_date))
                .distinct()
            ).scalars().all()
        return {value for value in rows if isinstance(value, date)}

    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_events.c.event_date)
            .where(
                schema.stock_events.c.event_type.in_(("limit_pool_zt", "limit_pool_zbgc")),
                schema.stock_events.c.event_date.in_(
                    _date_strings_between(start_date, end_date)
                ),
            )
            .distinct()
        ).scalars().all()
    return {parsed for value in rows if (parsed := _date_value(value)) is not None}


def load_eligible_stocks() -> dict[str, str]:
    """Load the current main-board non-ST universe used by the product."""

    with session_scope() as session:
        rows = session.execute(
            select(schema.stocks.c.vt_symbol, schema.stocks.c.name)
        ).all()
    return {
        str(vt_symbol): str(name or vt_symbol)
        for vt_symbol, name in rows
        if is_eligible_main_board(str(vt_symbol), str(name or ""))
    }


def load_expected_event_symbols(
    trade_dates: Sequence[date],
    *,
    eligible_stocks: Mapping[str, str],
) -> dict[date, set[str]]:
    """Derive a completeness reference from daily limit touches."""

    dates = sorted(set(trade_dates))
    if not dates:
        return {}
    previous_dates = _previous_trade_dates(dates)
    load_dates = sorted(set(dates) | set(previous_dates.values()))
    bars = _load_daily_bar_map(load_dates, eligible_stocks)
    expected: dict[date, set[str]] = {}
    for trade_date in dates:
        prior_date = previous_dates.get(trade_date)
        current = bars.get(trade_date, {})
        prior = bars.get(prior_date, {}) if prior_date else {}
        expected[trade_date] = {
            symbol
            for symbol, row in current.items()
            if _touches_limit(row.get("high_price"), (prior.get(symbol) or {}).get("close_price"))
        }
    return expected


def load_expected_auction_symbols(
    trade_dates: Sequence[date],
    *,
    eligible_stocks: Mapping[str, str],
) -> dict[date, set[str]]:
    """Return stocks with a daily bar that should have auction evidence."""

    dates = sorted(set(trade_dates))
    bars = _load_daily_bar_map(dates, eligible_stocks)
    return {
        trade_date: {
            symbol
            for symbol, row in bars.get(trade_date, {}).items()
            if _float_or_none(row.get("open_price")) not in {None, 0.0}
        }
        for trade_date in dates
    }


def replace_event_evidence(trade_date: date, rows: Sequence[Mapping[str, Any]]) -> int:
    """Atomically replace one date's canonical limit and failed-board rows."""

    values = [_event_insert_values(trade_date, row) for row in rows]
    if not values:
        raise HistoricalEvidenceImportError("validated event rows are empty")
    event_dates = (trade_date.isoformat(), trade_date.strftime("%Y%m%d"))
    with session_scope() as session:
        session.execute(
            schema.stock_events.delete().where(
                schema.stock_events.c.source == CANONICAL_EVENT_SOURCE,
                schema.stock_events.c.event_type.in_(("limit_pool_zt", "limit_pool_zbgc")),
                schema.stock_events.c.event_date.in_(event_dates),
            )
        )
        session.execute(schema.stock_events.insert().values(values))
    return len(values)


def replace_auction_evidence(trade_date: date, rows: Sequence[Mapping[str, Any]]) -> int:
    """Atomically replace one date's full opening-auction snapshot."""

    if not rows:
        raise HistoricalEvidenceImportError("validated auction rows are empty")
    return market_snapshot_repository.save_stock_auction_snapshots(
        rows,
        trade_date=trade_date,
        captured_at=datetime.now(timezone.utc),
    )


def normalize_dataset(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "event": "events",
        "events": "events",
        "limit_events": "events",
        "auction": "auction",
        "auctions": "auction",
        "opening_auction": "auction",
    }
    result = aliases.get(normalized)
    if result not in DATASETS:
        raise HistoricalEvidenceImportError(f"unsupported evidence dataset: {value}")
    return result


def _normalize_event_row(
    source_row: Mapping[str, Any],
    expected_date: date,
    eligible_stocks: Mapping[str, str] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    trade_date = _date_value(source_row.get("trade_date"))
    if trade_date != expected_date:
        return None, "trade_date does not match requested date"
    vt_symbol = _vt_symbol(source_row.get("ts_code") or source_row.get("vt_symbol"))
    if not vt_symbol:
        return None, "invalid ts_code"
    name = _eligible_name(vt_symbol, source_row.get("name"), eligible_stocks)
    if name is None or not is_eligible_main_board(vt_symbol, name):
        return None, "ineligible_stock"
    event_type = _event_type(source_row.get("limit") or source_row.get("limit_type"))
    if event_type is None:
        return None, "limit_type must be U or Z"
    first_time = _text_or_none(_first_present(source_row, "first_time", "首次封板时间"))
    if not first_time:
        return None, "first_time is required"
    raw = {
        **dict(source_row),
        "代码": vt_symbol.split(".", 1)[0],
        "名称": name,
        "首次封板时间": first_time,
        "最后封板时间": _text_or_none(_first_present(source_row, "last_time", "最后封板时间")),
        "炸板次数": _int_or_none(_first_present(source_row, "open_times", "炸板次数")),
        "封板资金": _float_or_none(_first_present(source_row, "fd_amount", "封板资金")),
        "连板数": _int_or_none(_first_present(source_row, "limit_times", "连板数")),
        "所属行业": _text_or_none(_first_present(source_row, "industry", "所属行业")),
        "最新价": _float_or_none(_first_present(source_row, "close", "最新价")),
        "涨跌幅": _float_or_none(_first_present(source_row, "pct_chg", "涨跌幅")),
        "成交额": _float_or_none(_first_present(source_row, "amount", "成交额")),
        "换手率": _float_or_none(_first_present(source_row, "turnover_ratio", "换手率")),
        "涨停统计": _text_or_none(_first_present(source_row, "up_stat", "涨停统计")),
        "历史证据来源": str(source_row.get("source") or "tushare.limit_list_d"),
    }
    return {
        "vt_symbol": vt_symbol,
        "name": name,
        "event_type": event_type,
        "raw": raw,
    }, None


def _normalize_auction_row(
    source_row: Mapping[str, Any],
    expected_date: date,
    eligible_stocks: Mapping[str, str] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    trade_date = _date_value(source_row.get("trade_date"))
    if trade_date != expected_date:
        return None, "trade_date does not match requested date"
    vt_symbol = _vt_symbol(source_row.get("ts_code") or source_row.get("vt_symbol"))
    if not vt_symbol:
        return None, "invalid ts_code"
    name = _eligible_name(vt_symbol, source_row.get("name"), eligible_stocks)
    if name is None or not is_eligible_main_board(vt_symbol, name):
        return None, "ineligible_stock"
    auction_price = _float_or_none(_first_present(source_row, "price", "auction_price"))
    previous_close = _float_or_none(_first_present(source_row, "pre_close", "previous_close"))
    matched_volume = _float_or_none(_first_present(source_row, "vol", "matched_volume"))
    matched_amount = _float_or_none(_first_present(source_row, "amount", "matched_amount"))
    if auction_price is None or previous_close is None or matched_volume is None or matched_amount is None:
        return None, "price, pre_close, vol and amount are required"
    quote_time = _text_or_none(source_row.get("source_quote_time")) or "09:25:00"
    source = str(source_row.get("source") or "tushare.stk_auction")
    return {
        "vt_symbol": vt_symbol,
        "name": name,
        "auction_price": auction_price,
        "previous_close": previous_close,
        "matched_volume": matched_volume,
        "matched_amount": matched_amount,
        "unmatched_volume": _float_or_none(source_row.get("unmatched_volume")),
        "unmatched_side": _text_or_none(source_row.get("unmatched_side")),
        "source_quote_time": quote_time,
        "source_updated_at": f"{expected_date.isoformat()}T{quote_time[:8]}+08:00",
        "auction_status": "matched" if matched_volume > 0 else "no_match",
        "turnover_rate": _float_or_none(source_row.get("turnover_rate")),
        "volume_ratio": _float_or_none(source_row.get("volume_ratio")),
        "float_share": _float_or_none(source_row.get("float_share")),
        "source": source,
        "raw": {**dict(source_row), "历史证据来源": source},
    }, None


def _import_grouped_rows(
    dataset: str,
    rows_by_date: Mapping[date, Sequence[Mapping[str, Any]]],
    *,
    eligible_stocks: Mapping[str, str],
    expected_symbols: Mapping[date, set[str]],
    dry_run: bool,
) -> dict[str, Any]:
    date_results = []
    rows_accepted = 0
    rows_written = 0
    errors: list[str] = []
    for trade_date in sorted(rows_by_date):
        normalized = _normalize_for_dataset(dataset, rows_by_date[trade_date], trade_date, eligible_stocks)
        audit = _coverage_audit(dataset, normalized["rows"], expected_symbols.get(trade_date))
        result = {
            "trade_date": trade_date.isoformat(),
            "rows_read": len(rows_by_date[trade_date]),
            "rows_accepted": normalized["accepted_count"],
            "rows_written": 0,
            "skipped_count": normalized["skipped_count"],
            "error_count": normalized["error_count"],
            **audit,
        }
        rows_accepted += normalized["accepted_count"]
        errors.extend(normalized["errors"])
        if audit["status"] == "ready" and not dry_run:
            result["rows_written"] = _replace_dataset_date(dataset, trade_date, normalized["rows"])
            rows_written += result["rows_written"]
        date_results.append(result)
    status = _aggregate_status(date_results)
    return {
        "status": status,
        "dataset": dataset,
        "provider": "csv" if rows_by_date else "unknown",
        "dry_run": bool(dry_run),
        "date_count": len(rows_by_date),
        "accepted_date_count": sum(item["status"] == "ready" for item in date_results),
        "rows_read": sum(len(rows) for rows in rows_by_date.values()),
        "rows_accepted": rows_accepted,
        "rows_written": rows_written,
        "date_results": date_results,
        "errors": errors[:MAX_ERROR_ITEMS],
    }


def _coverage_audit(
    dataset: str,
    rows: Sequence[Mapping[str, Any]],
    expected_symbols: set[str] | None,
) -> dict[str, Any]:
    if expected_symbols is None:
        return {
            "status": "reference_missing",
            "expected_count": 0,
            "covered_count": 0,
            "coverage_pct": 0.0,
            "missing_symbols": [],
        }
    accepted = {str(row.get("vt_symbol") or "") for row in rows}
    covered = accepted & expected_symbols
    expected_count = len(expected_symbols)
    coverage_pct = 100.0 if expected_count == 0 and not accepted else _pct(len(covered), expected_count)
    threshold = MIN_EVENT_COVERAGE_PCT if dataset == "events" else MIN_AUCTION_COVERAGE_PCT
    ready = bool(rows) and coverage_pct >= threshold
    return {
        "status": "ready" if ready else "coverage_incomplete",
        "expected_count": expected_count,
        "covered_count": len(covered),
        "coverage_pct": coverage_pct,
        "missing_symbols": sorted(expected_symbols - accepted)[:20],
    }


def _expected_symbols(
    dataset: str,
    dates: Sequence[date],
    *,
    expected_event_symbols: Mapping[date, set[str]] | None = None,
    expected_auction_symbols: Mapping[date, set[str]] | None = None,
    eligible_stocks: Mapping[str, str],
) -> Mapping[date, set[str]]:
    if dataset == "events":
        if expected_event_symbols is not None:
            return expected_event_symbols
        return load_expected_event_symbols(dates, eligible_stocks=eligible_stocks)
    if expected_auction_symbols is not None:
        return expected_auction_symbols
    return load_expected_auction_symbols(dates, eligible_stocks=eligible_stocks)


def _normalize_for_dataset(
    dataset: str,
    rows: Sequence[Mapping[str, Any]],
    trade_date: date,
    eligible_stocks: Mapping[str, str],
) -> dict[str, Any]:
    if dataset == "events":
        return normalize_event_rows(rows, expected_date=trade_date, eligible_stocks=eligible_stocks)
    return normalize_auction_rows(rows, expected_date=trade_date, eligible_stocks=eligible_stocks)


def _replace_dataset_date(dataset: str, trade_date: date, rows: Sequence[Mapping[str, Any]]) -> int:
    if dataset == "events":
        return replace_event_evidence(trade_date, rows)
    return replace_auction_evidence(trade_date, rows)


def _read_csv_rows(csv_text: str) -> list[dict[str, Any]]:
    text = str(csv_text or "").lstrip("\ufeff").strip()
    if not text:
        raise HistoricalEvidenceImportError("csv_text is empty")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HistoricalEvidenceImportError("CSV header is missing")
    return [dict(row) for row in reader]


def _group_source_rows_by_date(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[date, list[dict[str, Any]]], list[str]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    errors: list[str] = []
    for index, row in enumerate(rows, start=2):
        trade_date = _date_value(row.get("trade_date"))
        if trade_date is None:
            _append_error(errors, f"row {index}: invalid trade_date")
            continue
        grouped[trade_date].append(dict(row))
    return dict(grouped), errors


def _normalization_result(
    rows: Iterable[dict[str, Any]],
    errors: list[str],
    skipped: int,
    duplicates: int,
) -> dict[str, Any]:
    accepted = list(rows)
    return {
        "rows": accepted,
        "accepted_count": len(accepted),
        "skipped_count": skipped,
        "duplicate_count": duplicates,
        "error_count": len(errors),
        "errors": errors,
    }


def _eligible_name(
    vt_symbol: str,
    source_name: Any,
    eligible_stocks: Mapping[str, str] | None,
) -> str | None:
    if eligible_stocks is not None:
        return eligible_stocks.get(vt_symbol)
    name = str(source_name or "").strip()
    return name or vt_symbol.split(".", 1)[0]


def _event_type(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    mapping = {
        "U": "limit_pool_zt",
        "Z": "limit_pool_zbgc",
        "涨停": "limit_pool_zt",
        "涨停池": "limit_pool_zt",
        "炸板": "limit_pool_zbgc",
        "炸板池": "limit_pool_zbgc",
    }
    return mapping.get(normalized)


def _vt_symbol(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    code, separator, suffix = text.partition(".")
    if not separator:
        if code.startswith(("600", "601", "603", "605", "688")):
            suffix = "SH"
        elif code.startswith(("000", "001", "002", "003", "300", "301")):
            suffix = "SZ"
        elif code.startswith(("4", "8", "920")):
            suffix = "BJ"
    exchange = {"SH": "SSE", "SSE": "SSE", "SZ": "SZSE", "SZSE": "SZSE", "BJ": "BSE", "BSE": "BSE"}.get(suffix)
    if not code.isdigit() or exchange is None:
        return None
    return f"{code}.{exchange}"


def _event_insert_values(trade_date: date, row: Mapping[str, Any]) -> dict[str, Any]:
    event_type = str(row["event_type"])
    pool = "zt" if event_type == "limit_pool_zt" else "zbgc"
    name = str(row.get("name") or row["vt_symbol"])
    return {
        "vt_symbol": row["vt_symbol"],
        "event_date": trade_date.strftime("%Y%m%d"),
        "event_type": event_type,
        "title": f"{pool}: {name}",
        "summary": str(row.get("raw") or {}),
        "url": None,
        "keywords": [pool],
        "sentiment": "positive" if pool == "zt" else "negative",
        "importance": 0.8 if pool == "zt" else 0.5,
        "source": CANONICAL_EVENT_SOURCE,
        "raw": row.get("raw") or {},
    }


def _previous_trade_dates(trade_dates: Sequence[date]) -> dict[date, date]:
    result: dict[date, date] = {}
    with session_scope() as session:
        for trade_date in trade_dates:
            previous = session.execute(
                select(func.max(schema.stock_daily_bars.c.trade_date)).where(
                    schema.stock_daily_bars.c.trade_date < trade_date
                )
            ).scalar_one_or_none()
            if isinstance(previous, date):
                result[trade_date] = previous
    return result


def _load_daily_bar_map(
    trade_dates: Sequence[date],
    eligible_stocks: Mapping[str, str],
) -> dict[date, dict[str, dict[str, Any]]]:
    if not trade_dates or not eligible_stocks:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.open_price,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.high_price,
            ).where(
                schema.stock_daily_bars.c.trade_date.in_(list(trade_dates)),
                schema.stock_daily_bars.c.vt_symbol.in_(list(eligible_stocks)),
            )
        ).mappings().all()
    result: dict[date, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        result[row["trade_date"]][str(row["vt_symbol"])] = dict(row)
    return dict(result)


def _touches_limit(high_price: Any, previous_close: Any) -> bool:
    high = _float_or_none(high_price)
    prior = _float_or_none(previous_close)
    if high is None or prior is None or prior <= 0:
        return False
    return high >= main_board_limit_price(prior) - 0.005


def _date_strings_between(start_date: date, end_date: date) -> list[str]:
    with session_scope() as session:
        dates = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .where(schema.stock_daily_bars.c.trade_date.between(start_date, end_date))
            .distinct()
        ).scalars().all()
    result = []
    for value in dates:
        if isinstance(value, date):
            result.extend((value.isoformat(), value.strftime("%Y%m%d")))
    return result


def _validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HistoricalEvidenceImportError("start_date must not be after end_date")
    if (end_date - start_date).days > 3660:
        raise HistoricalEvidenceImportError("date range must not exceed 3660 calendar days")


def _require_database() -> None:
    if not is_database_configured():
        raise HistoricalEvidenceImportError("DATABASE_URL not configured")
    schema.ensure_schema_once(get_engine())


def _aggregate_status(date_results: Sequence[Mapping[str, Any]]) -> str:
    if not date_results:
        return "empty"
    ready_count = sum(item.get("status") == "ready" for item in date_results)
    if ready_count == len(date_results):
        return "ready"
    if ready_count:
        return "partial"
    return "rejected"


def _unavailable_result(dataset: str, message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "dataset": dataset,
        "provider": "tushare",
        "dry_run": True,
        "date_count": 0,
        "rows_read": 0,
        "rows_written": 0,
        "date_results": [],
        "errors": [],
        "message": message,
    }


def _safe_provider_error(exc: Exception) -> str:
    if isinstance(exc, (TushareQueryError, ThsQueryError)):
        return str(exc)[:300]
    return exc.__class__.__name__


def _ths_limit_time(value: Any, expected_date: date) -> str | None:
    if value in (None, "", 0, "0"):
        return None
    text = str(value).strip()
    if text.isdigit() and len(text) >= 9:
        try:
            parsed = datetime.fromtimestamp(int(text), tz=SHANGHAI)
        except (OverflowError, OSError, ValueError) as exc:
            raise ThsQueryError(f"invalid Tonghuashun limit timestamp: {text[:20]}") from exc
        if parsed.date() != expected_date:
            raise ThsQueryError(
                f"Tonghuashun limit timestamp date mismatch: {parsed.date().isoformat()}"
            )
        return parsed.strftime("%H:%M:%S")
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    digits = digits.zfill(6)[-6:]
    try:
        parsed_time = time(int(digits[:2]), int(digits[2:4]), int(digits[4:]))
    except ValueError as exc:
        raise ThsQueryError(f"invalid Tonghuashun limit time: {text[:20]}") from exc
    return parsed_time.isoformat()


def _ths_limit_times(value: Any) -> int | None:
    text = str(value or "").strip()
    if text == "首板":
        return 1
    matches = re.findall(r"(\d+)板", text)
    return int(matches[-1]) if matches else None


def _report_ths_progress(
    progress: Callable[[dict[str, Any]], None] | None,
    **patch: Any,
) -> None:
    if progress is None:
        return
    if "current" in patch:
        patch["progress_current"] = patch.pop("current")
    if "total" in patch:
        patch["progress_total"] = patch.pop("total")
    try:
        progress(dict(patch))
    except Exception:
        return


def _evidence_status_text(status: Any) -> str:
    return {
        "ready": "通过",
        "coverage_incomplete": "覆盖不足",
        "reference_missing": "缺少参照",
        "provider_error": "供应商错误",
    }.get(str(status or ""), str(status or "未知"))


def _ths_unavailable_result(message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "dataset": "events",
        "provider": "ths",
        "dry_run": False,
        "date_count": 0,
        "accepted_date_count": 0,
        "provider_error_count": 0,
        "coverage_incomplete_count": 0,
        "rows_read": 0,
        "rows_accepted": 0,
        "rows_written": 0,
        "date_results": [],
        "errors": [],
        "message": message,
    }


def _append_error(errors: list[str], message: str) -> None:
    if len(errors) < MAX_ERROR_ITEMS:
        errors.append(message)


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return int(number) if number is not None else None


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_present(values: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 4)


def _event_template_sample() -> dict[str, Any]:
    return {
        "trade_date": "2026-07-10",
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "limit_type": "U",
        "first_time": "09:33:05",
        "last_time": "14:31:52",
        "open_times": 2,
        "fd_amount": 128000000,
        "limit_times": 2,
        "industry": "通信设备",
        "close": 10.45,
        "pct_chg": 10.0,
        "amount": 880000000,
        "turnover_ratio": 12.4,
        "up_stat": "2/2",
    }


def _auction_template_sample() -> dict[str, Any]:
    return {
        "trade_date": "2026-07-10",
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "price": 10.45,
        "pre_close": 10.0,
        "vol": 320000,
        "amount": 3344000,
        "turnover_rate": 0.8,
        "volume_ratio": 2.1,
        "float_share": 40000,
        "unmatched_volume": "",
        "unmatched_side": "",
        "source_quote_time": "09:25:00",
    }
