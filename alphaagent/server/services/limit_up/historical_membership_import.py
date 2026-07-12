"""Historical point-in-time Shenwan industry membership imports."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

import requests
from sqlalchemy import and_, func, not_, or_, select

from alphaagent.server.core.config import get_settings
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services import market_snapshot_repository
from alphaagent.server.services.limit_up import data_quality_repository
from alphaagent.server.services.limit_up.domain import is_eligible_main_board


MIN_MEMBERSHIP_COVERAGE_PCT = 90.0
MIN_RELIABLE_DAILY_SYMBOLS = 3000
MAX_IMPORT_DATES = 100
MAX_ERROR_ITEMS = 30
MEMBERSHIP_FIELDS = (
    "ts_code",
    "name",
    "l1_code",
    "l1_name",
    "l2_code",
    "l2_name",
    "in_date",
    "out_date",
    "is_new",
)
TUSHARE_MEMBER_FIELDS = ",".join(MEMBERSHIP_FIELDS)


class HistoricalMembershipImportError(RuntimeError):
    """Raised for invalid or unsafe membership input."""


class TushareMembershipQueryError(HistoricalMembershipImportError):
    """Raised when a complete Tushare membership response is unavailable."""


def normalize_membership_intervals(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    eligible_stocks: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize interval rows and retain Shenwan level-2 memberships only."""

    normalized: dict[tuple[str, str, date, date | None], dict[str, Any]] = {}
    errors: list[str] = []
    skipped = 0
    duplicates = 0
    for index, source_row in enumerate(source_rows, start=2):
        row, reason = _normalize_membership_interval(source_row, eligible_stocks)
        if reason == "ineligible_stock":
            skipped += 1
            continue
        if reason:
            _append_error(errors, f"row {index}: {reason}")
            continue
        assert row is not None
        key = (row["vt_symbol"], row["sector_id"], row["in_date"], row["out_date"])
        if key in normalized:
            duplicates += 1
        normalized[key] = row
    return {
        "rows": list(normalized.values()),
        "accepted_count": len(normalized),
        "skipped_count": skipped,
        "duplicate_count": duplicates,
        "error_count": len(errors),
        "errors": errors,
    }


def expand_membership_intervals(
    intervals: Sequence[Mapping[str, Any]],
    trade_dates: Sequence[date],
) -> dict[str, Any]:
    """Expand intervals over trade dates and resolve overlaps point in time."""

    by_symbol: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for interval in intervals:
        by_symbol[str(interval.get("vt_symbol") or "")].append(interval)

    rows_by_date: dict[date, list[dict[str, Any]]] = {}
    conflicts: list[dict[str, Any]] = []
    conflict_count = 0
    for trade_date in sorted(set(trade_dates)):
        daily_rows: list[dict[str, Any]] = []
        for vt_symbol, symbol_intervals in by_symbol.items():
            active = [
                item
                for item in symbol_intervals
                if _interval_is_active(item, trade_date)
            ]
            if not active:
                continue
            active.sort(
                key=lambda item: (
                    _required_date(item.get("in_date"), "in_date"),
                    str(item.get("sector_id") or ""),
                )
            )
            selected = active[-1]
            if len(active) > 1:
                conflict_count += 1
                if len(conflicts) < MAX_ERROR_ITEMS:
                    conflicts.append(
                        {
                            "trade_date": trade_date.isoformat(),
                            "vt_symbol": vt_symbol,
                            "candidate_sector_ids": [
                                str(item.get("sector_id") or "") for item in active
                            ],
                            "selected_sector_id": str(selected.get("sector_id") or ""),
                        }
                    )
            daily_rows.append(_expanded_membership_row(selected, trade_date))
        rows_by_date[trade_date] = sorted(
            daily_rows,
            key=lambda item: (item["vt_symbol"], item["sector_id"]),
        )
    return {
        "rows_by_date": rows_by_date,
        "expanded_row_count": sum(len(rows) for rows in rows_by_date.values()),
        "conflict_count": conflict_count,
        "conflicts": conflicts,
    }


def import_membership_csv(
    *,
    csv_text: str,
    start_date: date,
    end_date: date,
    dry_run: bool = True,
    max_dates: int = 20,
    only_missing: bool = False,
    eligible_stocks: Mapping[str, str] | None = None,
    trade_dates: Sequence[date] | None = None,
    expected_symbols: Mapping[date, set[str]] | None = None,
) -> dict[str, Any]:
    """Audit and optionally persist a complete interval CSV export."""

    _validate_date_range(start_date, end_date)
    source_rows = _read_csv_rows(csv_text)
    if eligible_stocks is None:
        _require_database()
        eligible_stocks = load_eligible_stocks()
    dates = _resolve_trade_dates(
        start_date=start_date,
        end_date=end_date,
        max_dates=max_dates,
        only_missing=only_missing,
        trade_dates=trade_dates,
    )
    expected = (
        expected_symbols
        if expected_symbols is not None
        else load_expected_symbols_by_date(dates)
    )
    normalized = normalize_membership_intervals(
        source_rows,
        eligible_stocks=eligible_stocks,
    )
    result = _import_normalized_intervals(
        normalized,
        trade_dates=dates,
        expected_symbols=expected,
        dry_run=dry_run,
        provider="csv",
    )
    result.update(
        {
            "rows_read": len(source_rows),
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
            "candidate_date_count": len(dates),
        }
    )
    return result


def import_tushare_memberships(
    *,
    start_date: date,
    end_date: date,
    dry_run: bool = True,
    max_dates: int = 20,
    only_missing: bool = True,
) -> dict[str, Any]:
    """Backfill bounded point-in-time industry dates from Tushare Pro."""

    if not is_database_configured():
        return _unavailable_result("DATABASE_URL not configured", dry_run=dry_run)
    settings = get_settings()
    token = settings.tushare_token.strip()
    if not token:
        return _unavailable_result("TUSHARE_TOKEN not configured", dry_run=dry_run)
    _validate_date_range(start_date, end_date)
    _require_database()

    eligible_stocks = load_eligible_stocks()
    dates = select_membership_trade_dates(
        start_date=start_date,
        end_date=end_date,
        max_dates=max_dates,
        only_missing=only_missing,
    )
    if not dates:
        return _empty_result(
            provider="tushare",
            dry_run=dry_run,
            start_date=start_date,
            end_date=end_date,
        )
    expected = load_expected_symbols_by_date(dates)
    try:
        source_rows = query_tushare_membership_intervals(
            token=token,
            api_url=settings.tushare_api_url,
            timeout=float(settings.tushare_timeout_seconds),
        )
    except Exception as exc:
        reason = _safe_provider_error(exc)
        return {
            "status": "error",
            "dataset": "industry_memberships",
            "provider": "tushare",
            "dry_run": bool(dry_run),
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
            "candidate_date_count": len(dates),
            "date_count": len(dates),
            "accepted_date_count": 0,
            "rows_read": 0,
            "rows_accepted": 0,
            "rows_written": 0,
            "conflict_count": 0,
            "date_results": [
                {
                    "trade_date": trade_date.isoformat(),
                    "status": "provider_error",
                    "reason": reason,
                    "rows_written": 0,
                }
                for trade_date in dates
            ],
            "errors": [reason],
            "message": "Tushare行业成员响应不完整，未写入任何日期",
        }

    normalized = normalize_membership_intervals(
        source_rows,
        eligible_stocks=eligible_stocks,
    )
    result = _import_normalized_intervals(
        normalized,
        trade_dates=dates,
        expected_symbols=expected,
        dry_run=dry_run,
        provider="tushare",
    )
    result.update(
        {
            "rows_read": len(source_rows),
            "requested_start": start_date.isoformat(),
            "requested_end": end_date.isoformat(),
            "candidate_date_count": len(dates),
        }
    )
    return result


def query_tushare_membership_intervals(
    *,
    token: str,
    api_url: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Load the complete SW2021 hierarchy before any daily write."""

    classifications = _query_tushare_api(
        "index_classify",
        token=token,
        api_url=api_url,
        timeout=timeout,
        params={"level": "L1", "src": "SW2021"},
        fields="index_code,industry_name,level,industry_code,is_pub,parent_code,src",
    )
    l1_codes = sorted(
        {
            str(
                row.get("index_code")
                or row.get("industry_code")
                or row.get("l1_code")
                or ""
            ).strip()
            for row in classifications
        }
        - {""}
    )
    if not l1_codes:
        raise TushareMembershipQueryError("index_classify returned no SW2021 L1 industries")

    rows: list[dict[str, Any]] = []
    for l1_code in l1_codes:
        members = _query_tushare_api(
            "index_member_all",
            token=token,
            api_url=api_url,
            timeout=timeout,
            params={"l1_code": l1_code},
            fields=TUSHARE_MEMBER_FIELDS,
        )
        if not members:
            raise TushareMembershipQueryError(
                f"index_member_all returned no rows for {l1_code}"
            )
        rows.extend(members)
    if not rows:
        raise TushareMembershipQueryError("index_member_all returned no membership intervals")
    return rows


def historical_membership_status() -> dict[str, Any]:
    """Return provider configuration and stored point-in-time coverage."""

    settings = get_settings()
    coverage: Mapping[str, Any] = {}
    if is_database_configured():
        coverage = data_quality_repository.load_membership_data_quality_counts()
    return {
        "status": "ready" if is_database_configured() else "unavailable",
        "provider": {
            "id": "tushare",
            "configured": bool(settings.tushare_token.strip()),
            "api_url": settings.tushare_api_url,
            "token_exposed": False,
            "apis": ["index_classify", "index_member_all"],
        },
        "dataset": {
            "label": "申万二级逐日行业成员",
            "minimum_coverage_pct": MIN_MEMBERSHIP_COVERAGE_PCT,
            "coverage": dict(coverage),
        },
        "csv_import_available": True,
        "limitations": [
            "有效区间按 in_date <= 交易日 < out_date 展开。",
            "覆盖不足90%的日期整日拒绝写入，旧行业快照保持不变。",
            "这里只补行业归属；逐日概念题材、Tick/L2和严格竞价仍是独立门禁。",
        ],
    }


def membership_csv_template() -> str:
    """Return a UTF-8-BOM interval CSV template."""

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=MEMBERSHIP_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "l1_code": "801780.SI",
            "l1_name": "银行",
            "l2_code": "851911.SI",
            "l2_name": "股份制银行Ⅱ",
            "in_date": "20210101",
            "out_date": "",
            "is_new": "Y",
        }
    )
    return "\ufeff" + buffer.getvalue()


def replace_industry_membership_snapshot(
    trade_date: date,
    rows: Sequence[Mapping[str, Any]],
    *,
    captured_at: datetime | None = None,
) -> int:
    """Replace only the industry scope for one validated trade date."""

    if not rows:
        raise HistoricalMembershipImportError("validated membership rows are empty")
    return market_snapshot_repository.replace_stock_sector_membership_snapshot_scope(
        rows,
        snapshot_date=trade_date,
        captured_at=captured_at or datetime.now(timezone.utc),
        sector_type="industry",
    )


def load_eligible_stocks() -> dict[str, str]:
    with session_scope() as session:
        rows = session.execute(select(schema.stocks.c.vt_symbol, schema.stocks.c.name)).all()
    return {
        str(vt_symbol): str(name or vt_symbol)
        for vt_symbol, name in rows
        if is_eligible_main_board(str(vt_symbol), str(name or ""))
    }


def select_membership_trade_dates(
    *,
    start_date: date,
    end_date: date,
    max_dates: int,
    only_missing: bool,
) -> list[date]:
    """Select bounded reliable local dates, oldest first."""

    _validate_date_range(start_date, end_date)
    cap = min(max(int(max_dates or 20), 1), MAX_IMPORT_DATES)
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .where(schema.stock_daily_bars.c.trade_date.between(start_date, end_date))
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(
                func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
                >= MIN_RELIABLE_DAILY_SYMBOLS
            )
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).scalars().all()
    dates = [value for value in rows if isinstance(value, date)]
    if only_missing and dates:
        expected = load_expected_symbols_by_date(dates)
        existing = load_qualifying_industry_snapshot_dates(dates, expected_symbols=expected)
        dates = [value for value in dates if value not in existing]
    return dates[:cap]


def load_expected_symbols_by_date(
    trade_dates: Sequence[date],
) -> dict[date, set[str]]:
    dates = sorted(set(trade_dates))
    if not dates:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.vt_symbol,
            )
            .select_from(
                schema.stock_daily_bars.join(
                    schema.stocks,
                    schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(
                schema.stock_daily_bars.c.trade_date.in_(dates),
                _eligible_main_board_condition(),
            )
        ).all()
    result: dict[date, set[str]] = {trade_date: set() for trade_date in dates}
    for trade_date, vt_symbol in rows:
        result[trade_date].add(str(vt_symbol))
    return result


def load_qualifying_industry_snapshot_dates(
    trade_dates: Sequence[date],
    *,
    expected_symbols: Mapping[date, set[str]],
) -> set[date]:
    dates = sorted(set(trade_dates))
    if not dates:
        return set()
    snapshots = schema.stock_sector_membership_snapshots
    with session_scope() as session:
        rows = session.execute(
            select(snapshots.c.snapshot_date, snapshots.c.vt_symbol).where(
                snapshots.c.snapshot_date.in_(dates),
                snapshots.c.sector_type == "industry",
            )
        ).all()
    covered: dict[date, set[str]] = defaultdict(set)
    for snapshot_date, vt_symbol in rows:
        covered[snapshot_date].add(str(vt_symbol))
    return {
        trade_date
        for trade_date in dates
        if expected_symbols.get(trade_date)
        and _pct(
            len(covered.get(trade_date, set()) & expected_symbols[trade_date]),
            len(expected_symbols[trade_date]),
        )
        >= MIN_MEMBERSHIP_COVERAGE_PCT
    }


def _normalize_membership_interval(
    source_row: Mapping[str, Any],
    eligible_stocks: Mapping[str, str] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    vt_symbol = _vt_symbol(source_row.get("ts_code") or source_row.get("vt_symbol"))
    if not vt_symbol:
        return None, "invalid ts_code"
    source_name = str(source_row.get("name") or "").strip()
    name = eligible_stocks.get(vt_symbol) if eligible_stocks is not None else source_name
    if not name or not is_eligible_main_board(vt_symbol, name):
        return None, "ineligible_stock"
    sector_id = str(source_row.get("l2_code") or "").strip()
    sector_name = str(source_row.get("l2_name") or "").strip()
    if not sector_id or not sector_name:
        return None, "l2_code and l2_name are required"
    in_date = _date_value(source_row.get("in_date"))
    out_date = _date_value(source_row.get("out_date"))
    if in_date is None:
        return None, "invalid in_date"
    if str(source_row.get("out_date") or "").strip() and out_date is None:
        return None, "invalid out_date"
    if out_date is not None and out_date <= in_date:
        return None, "out_date must be after in_date"
    source = str(source_row.get("source") or "tushare.index_member_all")
    raw = {
        **dict(source_row),
        "in_date": in_date.isoformat(),
        "out_date": out_date.isoformat() if out_date else None,
        "membership_interval_semantics": "in_date_inclusive_out_date_exclusive",
    }
    return {
        "vt_symbol": vt_symbol,
        "name": name,
        "sector_id": sector_id,
        "sector_name": sector_name,
        "sector_type": "industry",
        "rank": 2,
        "confirmed": True,
        "is_precise": True,
        "source": source,
        "in_date": in_date,
        "out_date": out_date,
        "l1_code": str(source_row.get("l1_code") or "").strip() or None,
        "l1_name": str(source_row.get("l1_name") or "").strip() or None,
        "raw": raw,
    }, None


def _expanded_membership_row(interval: Mapping[str, Any], trade_date: date) -> dict[str, Any]:
    raw = dict(interval.get("raw") or {})
    raw["snapshot_trade_date"] = trade_date.isoformat()
    return {
        "vt_symbol": str(interval["vt_symbol"]),
        "sector_id": str(interval["sector_id"]),
        "sector_name": str(interval["sector_name"]),
        "sector_type": "industry",
        "rank": 2,
        "confirmed": True,
        "is_precise": True,
        "source": str(interval.get("source") or "tushare.index_member_all"),
        "raw": raw,
    }


def _import_normalized_intervals(
    normalized: Mapping[str, Any],
    *,
    trade_dates: Sequence[date],
    expected_symbols: Mapping[date, set[str]],
    dry_run: bool,
    provider: str,
) -> dict[str, Any]:
    expanded = expand_membership_intervals(normalized.get("rows") or [], trade_dates)
    date_results: list[dict[str, Any]] = []
    rows_written = 0
    captured_at = datetime.now(timezone.utc)
    for trade_date in sorted(set(trade_dates)):
        rows = expanded["rows_by_date"].get(trade_date, [])
        audit = _coverage_audit(rows, expected_symbols.get(trade_date))
        result = {
            "trade_date": trade_date.isoformat(),
            "rows_read": len(rows),
            "rows_accepted": len(rows),
            "rows_written": 0,
            **audit,
        }
        if audit["status"] == "ready" and not dry_run:
            result["rows_written"] = replace_industry_membership_snapshot(
                trade_date,
                rows,
                captured_at=captured_at,
            )
            rows_written += result["rows_written"]
        date_results.append(result)
    return {
        "status": _aggregate_status(date_results),
        "dataset": "industry_memberships",
        "provider": provider,
        "dry_run": bool(dry_run),
        "date_count": len(date_results),
        "accepted_date_count": sum(item["status"] == "ready" for item in date_results),
        "rows_read": int(normalized.get("accepted_count") or 0),
        "rows_accepted": int(normalized.get("accepted_count") or 0),
        "expanded_rows": expanded["expanded_row_count"],
        "rows_written": rows_written,
        "skipped_count": int(normalized.get("skipped_count") or 0),
        "duplicate_count": int(normalized.get("duplicate_count") or 0),
        "conflict_count": expanded["conflict_count"],
        "conflicts": expanded["conflicts"],
        "date_results": date_results,
        "errors": list(normalized.get("errors") or [])[:MAX_ERROR_ITEMS],
    }


def _coverage_audit(
    rows: Sequence[Mapping[str, Any]],
    expected_symbols: set[str] | None,
) -> dict[str, Any]:
    if not expected_symbols:
        return {
            "status": "reference_missing",
            "reason": "缺少当日主板非ST日线参照",
            "expected_count": 0,
            "covered_count": 0,
            "coverage_pct": 0.0,
            "missing_symbols": [],
        }
    accepted = {str(row.get("vt_symbol") or "") for row in rows}
    covered = accepted & expected_symbols
    coverage_pct = _pct(len(covered), len(expected_symbols))
    ready = bool(rows) and coverage_pct >= MIN_MEMBERSHIP_COVERAGE_PCT
    return {
        "status": "ready" if ready else "coverage_incomplete",
        "reason": None if ready else f"行业覆盖低于{MIN_MEMBERSHIP_COVERAGE_PCT:g}%",
        "expected_count": len(expected_symbols),
        "covered_count": len(covered),
        "coverage_pct": coverage_pct,
        "missing_symbols": sorted(expected_symbols - accepted)[:20],
    }


def _resolve_trade_dates(
    *,
    start_date: date,
    end_date: date,
    max_dates: int,
    only_missing: bool,
    trade_dates: Sequence[date] | None,
) -> list[date]:
    cap = min(max(int(max_dates or 20), 1), MAX_IMPORT_DATES)
    if trade_dates is not None:
        return sorted(
            {value for value in trade_dates if start_date <= value <= end_date}
        )[:cap]
    return select_membership_trade_dates(
        start_date=start_date,
        end_date=end_date,
        max_dates=cap,
        only_missing=only_missing,
    )


def _query_tushare_api(
    api_name: str,
    *,
    token: str,
    api_url: str,
    timeout: float,
    params: Mapping[str, Any],
    fields: str,
) -> list[dict[str, Any]]:
    response = requests.post(
        api_url,
        json={
            "api_name": api_name,
            "token": token,
            "params": dict(params),
            "fields": fields,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") not in {0, "0", None}:
        raise TushareMembershipQueryError(
            str(body.get("msg") or body.get("message") or f"{api_name} failed")
        )
    data = body.get("data") or {}
    response_fields = data.get("fields") or []
    items = data.get("items") or []
    return [dict(zip(response_fields, item, strict=False)) for item in items]


def _read_csv_rows(csv_text: str) -> list[dict[str, Any]]:
    text = str(csv_text or "").lstrip("\ufeff").strip()
    if not text:
        raise HistoricalMembershipImportError("csv_text is empty")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HistoricalMembershipImportError("CSV header is missing")
    missing = [field for field in MEMBERSHIP_FIELDS if field not in reader.fieldnames]
    if missing:
        raise HistoricalMembershipImportError(
            f"CSV missing required columns: {', '.join(missing)}"
        )
    return [dict(row) for row in reader]


def _eligible_main_board_condition():
    symbol = schema.stocks.c.symbol
    exchange = schema.stocks.c.exchange
    normalized_name = func.upper(func.replace(func.coalesce(schema.stocks.c.name, ""), "*", ""))
    excluded_name = or_(
        normalized_name.contains("ST"),
        normalized_name.contains("退"),
        normalized_name.startswith("S"),
        normalized_name.startswith("N"),
        normalized_name.startswith("C"),
    )
    return and_(
        or_(
            and_(
                exchange == "SSE",
                or_(*(symbol.startswith(prefix) for prefix in ("600", "601", "603", "605"))),
            ),
            and_(
                exchange == "SZSE",
                or_(*(symbol.startswith(prefix) for prefix in ("000", "001", "002", "003"))),
            ),
        ),
        not_(excluded_name),
    )


def _interval_is_active(interval: Mapping[str, Any], trade_date: date) -> bool:
    in_date = _required_date(interval.get("in_date"), "in_date")
    out_date = _date_value(interval.get("out_date"))
    return in_date <= trade_date and (out_date is None or trade_date < out_date)


def _required_date(value: Any, field: str) -> date:
    result = _date_value(value)
    if result is None:
        raise HistoricalMembershipImportError(f"invalid {field}")
    return result


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
    exchange = {
        "SH": "SSE",
        "SSE": "SSE",
        "SZ": "SZSE",
        "SZSE": "SZSE",
        "BJ": "BSE",
        "BSE": "BSE",
    }.get(suffix)
    if not code.isdigit() or exchange is None:
        return None
    return f"{code}.{exchange}"


def _validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HistoricalMembershipImportError("start_date must not be after end_date")
    if (end_date - start_date).days > 3660:
        raise HistoricalMembershipImportError("date range must not exceed 3660 calendar days")


def _require_database() -> None:
    if not is_database_configured():
        raise HistoricalMembershipImportError("DATABASE_URL not configured")
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


def _unavailable_result(message: str, *, dry_run: bool) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "dataset": "industry_memberships",
        "provider": "tushare",
        "dry_run": bool(dry_run),
        "date_count": 0,
        "rows_read": 0,
        "rows_accepted": 0,
        "rows_written": 0,
        "conflict_count": 0,
        "date_results": [],
        "errors": [],
        "message": message,
    }


def _empty_result(
    *,
    provider: str,
    dry_run: bool,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    return {
        "status": "empty",
        "dataset": "industry_memberships",
        "provider": provider,
        "dry_run": bool(dry_run),
        "requested_start": start_date.isoformat(),
        "requested_end": end_date.isoformat(),
        "candidate_date_count": 0,
        "date_count": 0,
        "rows_read": 0,
        "rows_accepted": 0,
        "rows_written": 0,
        "conflict_count": 0,
        "date_results": [],
        "errors": [],
        "message": "所选范围没有需要回补的可靠交易日",
    }


def _safe_provider_error(exc: Exception) -> str:
    if isinstance(exc, TushareMembershipQueryError):
        return str(exc)[:300]
    return exc.__class__.__name__


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


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 4)
