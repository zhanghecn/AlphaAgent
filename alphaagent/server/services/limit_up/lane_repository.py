"""Rich event and point-in-time financial data for board-lane research."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime
from typing import Mapping, Sequence

from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up.domain import normalize_limit_time
from alphaagent.server.services.limit_up.lane_features import classify_financial_risk
from alphaagent.server.services.limit_up.repository import LIMIT_EVENT_TYPES

FinancialIndex = dict[str, list[tuple[date, dict[str, object]]]]
EventIndex = dict[tuple[str, date], dict[str, object]]


def load_lane_research_data(
    start: date,
    end: date,
) -> tuple[EventIndex, FinancialIndex, dict[str, object]]:
    """Load rich limit events and reports available inside a replay window."""

    schema.ensure_schema_once(get_engine())
    normalized_event_date = func.replace(
        func.substr(schema.stock_events.c.event_date, 1, 10),
        "-",
        "",
    )
    with session_scope() as session:
        event_rows = [
            dict(row)
            for row in session.execute(
                select(schema.stock_events).where(
                    schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES),
                    normalized_event_date >= start.strftime("%Y%m%d"),
                    normalized_event_date <= end.strftime("%Y%m%d"),
                )
            ).mappings()
        ]
        report_rows = [
            _plain_row(row)
            for row in session.execute(
                select(schema.stock_financial_reports)
            ).mappings()
        ]

    events = merge_rich_event_rows(event_rows)
    financials = build_financial_index(report_rows)
    path_events = [event for event in events.values() if event.get("time_preview")]
    path_dates = sorted({event["trade_date"] for event in path_events})
    event_dates = sorted({event["trade_date"] for event in events.values()})
    return events, financials, {
        "lane_event_count": len(events),
        "lane_event_trade_days": len(event_dates),
        "lane_event_start": event_dates[0].isoformat() if event_dates else None,
        "lane_event_end": event_dates[-1].isoformat() if event_dates else None,
        "intraday_path_event_count": len(path_events),
        "intraday_path_trade_days": len(path_dates),
        "intraday_path_start": path_dates[0].isoformat() if path_dates else None,
        "intraday_path_end": path_dates[-1].isoformat() if path_dates else None,
        "financial_report_count": len(report_rows),
        "financial_symbol_count": len(financials),
    }


def merge_rich_event_rows(rows: Sequence[Mapping[str, object]]) -> EventIndex:
    """Combine latest final status with the richest same-day path evidence."""

    grouped: dict[tuple[str, date], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        trade_date = _date_value(row.get("event_date"))
        symbol = str(row.get("vt_symbol") or "")
        if trade_date is not None and symbol:
            grouped[(symbol, trade_date)].append(row)

    result: EventIndex = {}
    for key, versions in grouped.items():
        status_row = max(versions, key=_row_version)
        path_row = max(versions, key=_path_row_score)
        status_raw = _raw(status_row)
        path_raw = _raw(path_row)
        richest_raw = _merged_raw(versions)
        time_preview = _path_values(path_raw.get("分时路径"))
        if not time_preview:
            time_preview = _path_values(richest_raw.get("分时路径"))
        turnover = _number(_first(richest_raw, "成交额", "amount", "turnover"))
        seal_amount = _number(
            _first(richest_raw, "封板资金", "涨停封单量", "fd_amount", "order_amount")
        )
        result[key] = {
            "vt_symbol": key[0],
            "trade_date": key[1],
            "name": str(_first(richest_raw, "名称", "name") or status_row.get("title") or ""),
            "event_type": str(status_row.get("event_type") or ""),
            "is_sealed": str(status_row.get("event_type") or "") == "limit_pool_zt",
            "first_limit_time": normalize_limit_time(
                _first(richest_raw, "首次封板时间", "首次涨停时间", "first_time")
            ),
            "last_limit_time": normalize_limit_time(
                _first(richest_raw, "最后封板时间", "last_time")
            ),
            "open_times": _integer(
                _first(richest_raw, "炸板次数", "开板次数", "open_times")
            ),
            "limit_times": _integer(
                _first(richest_raw, "连板数", "连续涨停天数", "limit_times")
            ),
            "seal_amount": seal_amount,
            "turnover": turnover,
            "turnover_rate": _number(
                _first(richest_raw, "换手率", "turnover_ratio", "turnover_rate")
            ),
            "seal_to_turnover_ratio": (
                seal_amount / turnover if seal_amount is not None and turnover else None
            ),
            "float_market_cap": _number(
                _first(richest_raw, "流通市值", "currency_value")
            ),
            "historical_seal_rate": _number(
                _first(richest_raw, "近一年封板率", "limit_up_suc_rate")
            ),
            "limit_up_shape": str(
                _first(richest_raw, "涨停形态", "limit_up_type") or ""
            ) or None,
            "limit_up_reason": str(
                _first(richest_raw, "涨停原因", "reason_type") or ""
            ) or None,
            "time_preview": time_preview,
            "status_source": str(status_row.get("source") or status_raw.get("历史证据来源") or ""),
            "path_source": str(path_row.get("source") or path_raw.get("历史证据来源") or "")
            if time_preview
            else None,
            "source_updated_at": _iso_value(status_row.get("updated_at")),
        }
    return result


def build_financial_index(rows: Sequence[Mapping[str, object]]) -> FinancialIndex:
    index: FinancialIndex = defaultdict(list)
    for row in rows:
        symbol = str(row.get("vt_symbol") or "")
        publish_date = _date_value(row.get("publish_date"))
        if not symbol or publish_date is None:
            continue
        payload = dict(row)
        payload["publish_date"] = publish_date.isoformat()
        index[symbol].append((publish_date, payload))
    for reports in index.values():
        reports.sort(key=lambda item: (item[0], str(item[1].get("report_date") or "")))
    return dict(index)


def financial_report_as_of(
    index: FinancialIndex,
    vt_symbol: str,
    signal_date: date,
) -> dict[str, object] | None:
    reports = index.get(vt_symbol) or []
    if not reports:
        return None
    position = bisect_right([item[0] for item in reports], signal_date) - 1
    return dict(reports[position][1]) if position >= 0 else None


def financial_snapshot_as_of(
    index: FinancialIndex,
    vt_symbol: str,
    signal_date: date,
) -> dict[str, object] | None:
    report = financial_report_as_of(index, vt_symbol, signal_date)
    if not report:
        return None
    fields = (
        "publish_date",
        "report_date",
        "period_type",
        "revenue_yoy",
        "net_profit_yoy",
        "gross_margin",
        "roe",
        "debt_asset_ratio",
        "cash_flow_quality",
    )
    return {field: report.get(field) for field in fields}


def financial_risk_as_of(
    index: FinancialIndex,
    vt_symbol: str,
    signal_date: date,
) -> dict[str, object]:
    return classify_financial_risk(
        financial_report_as_of(index, vt_symbol, signal_date)
    )


def _merged_raw(versions: Sequence[Mapping[str, object]]) -> dict[str, object]:
    merged: dict[str, object] = {}
    for row in sorted(versions, key=_path_row_score):
        for key, value in _raw(row).items():
            if value not in (None, "", [], {}):
                merged[str(key)] = value
    return merged


def _path_row_score(row: Mapping[str, object]) -> tuple[int, int, tuple[str, int]]:
    raw = _raw(row)
    path = _path_values(raw.get("分时路径"))
    rich_fields = sum(
        _first(raw, field) not in (None, "", [], {})
        for field in ("涨停形态", "近一年封板率", "封板资金", "换手率", "流通市值")
    )
    return len(path), rich_fields, _row_version(row)


def _row_version(row: Mapping[str, object]) -> tuple[str, int]:
    timestamp = row.get("updated_at") or row.get("created_at") or ""
    return str(timestamp), _integer(row.get("id"))


def _raw(row: Mapping[str, object]) -> Mapping[str, object]:
    raw = row.get("raw")
    return raw if isinstance(raw, Mapping) else {}


def _first(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "-"):
            return value
    return None


def _path_values(value: object) -> list[float | None]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[float | None] = []
    for item in value[:80]:
        result.append(_number(item))
    return result if any(item is not None for item in result) else []


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) >= 10 and text[4:5] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    digits = "".join(character for character in text[:10] if character.isdigit())
    if len(digits) >= 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _plain_row(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _iso_value(value) for key, value in dict(row).items()}


def _iso_value(value: object) -> object:
    return value.isoformat() if hasattr(value, "isoformat") else value
