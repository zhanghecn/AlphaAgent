"""Read-only data access for the limit-up Top5 MVP."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Mapping

from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.domain import event_matches_daily_bar, normalize_limit_time
from alphaagent.server.services.limit_up.sentiment import load_sentiment_points

LIMIT_EVENT_TYPES = ("limit_pool_zt", "limit_pool_zbgc")
RESEARCH_SECTOR_TYPES = ("theme", "industry")


def normalize_event_row(row: Mapping[str, object]) -> dict[str, object]:
    """Convert provider-specific event JSON into a stable research record."""

    raw = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
    event_type = str(row.get("event_type") or "")
    return {
        "vt_symbol": str(row.get("vt_symbol") or ""),
        "trade_date": _event_date_text(row.get("event_date")),
        "event_type": event_type,
        "name": str(raw.get("名称") or row.get("title") or ""),
        "industry_name": str(raw.get("所属行业") or ""),
        "close_price": _number(raw.get("最新价") or raw.get("收盘价")),
        "change_pct": _number(raw.get("涨跌幅")),
        "first_limit_time": normalize_limit_time(raw.get("首次封板时间") or raw.get("涨停时间")),
        "last_limit_time": normalize_limit_time(raw.get("最后封板时间")),
        "open_times": _integer(raw.get("炸板次数") or raw.get("开板次数")),
        "limit_times": _integer(raw.get("连板数") or raw.get("连续涨停天数")),
        "seal_amount": _number(raw.get("封板资金") or raw.get("涨停封单量")),
        "turnover": _number(raw.get("成交额")),
        "float_market_cap": _number(raw.get("流通市值")),
        "turnover_rate": _number(raw.get("换手率")),
        "is_sealed": event_type == "limit_pool_zt",
        "source": str(raw.get("历史证据来源") or row.get("source") or ""),
    }


def deduplicate_event_rows(rows: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Keep the latest intraday snapshot for each stock and trading day."""

    latest: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in rows:
        key = (str(row.get("vt_symbol") or ""), str(row.get("event_date") or ""))
        current = latest.get(key)
        if current is None or _event_version(row) > _event_version(current):
            latest[key] = row
    return list(latest.values())


def list_limit_up_event_dates() -> list[str]:
    """Return event dates that are also present in the daily-bar calendar."""

    with session_scope() as session:
        raw_dates = session.execute(
            select(schema.stock_events.c.event_date)
            .where(schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES))
            .distinct()
        ).scalars().all()
        normalized_dates = sorted(
            {
                normalized
                for value in raw_dates
                if (normalized := _event_date_text(value)) is not None
            }
        )
        if not normalized_dates:
            return []
        verified_dates = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .where(
                schema.stock_daily_bars.c.trade_date.in_(
                    [date.fromisoformat(value) for value in normalized_dates]
                )
            )
            .distinct()
        ).scalars().all()

    verified = {
        value.isoformat() if isinstance(value, date) else str(value)
        for value in verified_dates
    }
    return [value for value in normalized_dates if value in verified]


def load_daily_bars_all(start: date, end: date) -> list[dict[str, object]]:
    """全市场日线（不做 events 过滤），供全市场回测的 D-1 因子与 D+1 卖出。"""

    statement = select(
        schema.stock_daily_bars.c.vt_symbol,
        schema.stock_daily_bars.c.trade_date,
        schema.stock_daily_bars.c.open_price,
        schema.stock_daily_bars.c.close_price,
        schema.stock_daily_bars.c.high_price,
        schema.stock_daily_bars.c.low_price,
        schema.stock_daily_bars.c.volume,
        schema.stock_daily_bars.c.turnover,
        schema.stock_daily_bars.c.turnover_rate,
        schema.stock_daily_bars.c.change_pct,
    ).where(
        schema.stock_daily_bars.c.trade_date >= start,
        schema.stock_daily_bars.c.trade_date <= end,
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def load_stock_names() -> dict[str, str]:
    """全部股票名称（ST 过滤用）。"""

    with session_scope() as session:
        rows = session.execute(
            select(schema.stocks.c.vt_symbol, schema.stocks.c.name)
        ).all()
    return {str(row[0]): str(row[1] or "") for row in rows}


def load_window_minute_bars(
    trade_date: date,
    *,
    start_time: str = "09:25:00",
    end_time: str = "09:41:00",
) -> dict[str, list[dict[str, object]]]:
    """加载某交易日窗口（默认 9:25-9:41）的 1 分钟 bar，按票分组。

    返回 ``{vt_symbol: [bar, ...]}``，bar_time 为 ``HH:MM:SS``，按时间升序。
    """

    start_dt = datetime.combine(trade_date, time.fromisoformat(start_time))
    end_dt = datetime.combine(trade_date, time.fromisoformat(end_time))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.open_price,
            schema.stock_minute_bars.c.close_price,
            schema.stock_minute_bars.c.high_price,
            schema.stock_minute_bars.c.low_price,
            schema.stock_minute_bars.c.volume,
            schema.stock_minute_bars.c.turnover,
        )
        .where(
            schema.stock_minute_bars.c.trade_date == trade_date,
            schema.stock_minute_bars.c.interval == "1m",
            schema.stock_minute_bars.c.bar_time >= start_dt,
            schema.stock_minute_bars.c.bar_time <= end_dt,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    result: dict[str, list[dict[str, object]]] = {}
    with session_scope() as session:
        for row in session.execute(statement).mappings().all():
            symbol = str(row["vt_symbol"])
            bar_time = row["bar_time"]
            result.setdefault(symbol, []).append(
                {
                    "vt_symbol": symbol,
                    "bar_time": bar_time.strftime("%H:%M:%S")
                    if hasattr(bar_time, "strftime")
                    else str(bar_time)[-8:],
                    "open_price": row["open_price"],
                    "close_price": row["close_price"],
                    "high_price": row["high_price"],
                    "low_price": row["low_price"],
                    "volume": row["volume"],
                    "turnover": row["turnover"],
                }
            )
    return result


def load_limit_up_dataset(
    start: date | None = None,
    end: date | None = None,
) -> dict[str, object]:
    """Load a bounded read-only dataset for the dashboard and proxy backtest."""

    with session_scope() as session:
        event_statement = select(schema.stock_events).where(
            schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES)
        )
        normalized_event_date = func.replace(
            func.substr(schema.stock_events.c.event_date, 1, 10),
            "-",
            "",
        )
        if start is not None:
            event_statement = event_statement.where(
                normalized_event_date >= start.strftime("%Y%m%d")
            )
        if end is not None:
            event_statement = event_statement.where(
                normalized_event_date <= end.strftime("%Y%m%d")
            )
        event_rows = session.execute(event_statement).mappings().all()
        events = [
            normalize_event_row(dict(row))
            for row in deduplicate_event_rows([dict(row) for row in event_rows])
        ]
        events = [event for event in events if _date_in_range(event.get("trade_date"), start, end)]
        symbols = sorted({str(event["vt_symbol"]) for event in events if event.get("vt_symbol")})

        if not events or not symbols:
            return _empty_dataset(events)

        event_dates = sorted({str(event["trade_date"]) for event in events if event.get("trade_date")})
        first_date = date.fromisoformat(event_dates[0])
        last_date = date.fromisoformat(event_dates[-1])
        data_start = first_date - timedelta(days=35)
        data_end = last_date + timedelta(days=10)

        memberships = [
            _plain_row(row)
            for row in session.execute(
                select(schema.stock_sector_memberships).where(
                    schema.stock_sector_memberships.c.vt_symbol.in_(symbols),
                    schema.stock_sector_memberships.c.sector_type.in_(RESEARCH_SECTOR_TYPES),
                )
            ).mappings().all()
        ]
        sector_ids = sorted({str(row["sector_id"]) for row in memberships if row.get("sector_id")})

        sector_flows: list[dict[str, object]] = []
        sector_scores: list[dict[str, object]] = []
        if sector_ids:
            sector_flows = [
                _plain_row(row)
                for row in session.execute(
                    select(
                        schema.sector_fund_flows,
                        schema.sectors.c.name.label("sector_name"),
                        schema.sectors.c.category.label("sector_category"),
                        schema.sectors.c.path.label("sector_path"),
                    )
                    .join(schema.sectors, schema.sectors.c.id == schema.sector_fund_flows.c.sector_id)
                    .where(
                        schema.sector_fund_flows.c.sector_id.in_(sector_ids),
                        schema.sector_fund_flows.c.period == "即时",
                    )
                ).mappings().all()
            ]
            sector_scores = [
                _plain_row(row)
                for row in session.execute(
                    select(schema.sector_period_scores).where(
                        schema.sector_period_scores.c.sector_id.in_(sector_ids),
                        schema.sector_period_scores.c.period == "20d",
                        schema.sector_period_scores.c.as_of_date >= data_start,
                        schema.sector_period_scores.c.as_of_date <= last_date,
                    )
                ).mappings().all()
            ]

        stock_flows = [
            _plain_row(row)
            for row in session.execute(
                select(schema.stock_fund_flows).where(
                    schema.stock_fund_flows.c.vt_symbol.in_(symbols),
                    schema.stock_fund_flows.c.period == "即时",
                )
            ).mappings().all()
            if _text_date_in_range(row.get("trade_date"), data_start, data_end)
        ]
        window_event_date_text = func.replace(
            func.substr(schema.stock_events.c.event_date, 1, 10),
            "-",
            "",
        )
        window_event_date = func.to_date(window_event_date_text, "YYYYMMDD")
        event_window_exists = (
            select(1)
            .select_from(schema.stock_events)
            .where(
                schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES),
                schema.stock_events.c.vt_symbol == schema.stock_daily_bars.c.vt_symbol,
                window_event_date.between(first_date, last_date),
                schema.stock_daily_bars.c.trade_date >= window_event_date - 35,
                schema.stock_daily_bars.c.trade_date <= window_event_date + 10,
            )
            .exists()
        )
        daily_bars = [
            _daily_bar_row(row)
            for row in session.execute(
                select(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.open_price,
                    schema.stock_daily_bars.c.close_price,
                    schema.stock_daily_bars.c.high_price,
                    schema.stock_daily_bars.c.low_price,
                    schema.stock_daily_bars.c.volume,
                    schema.stock_daily_bars.c.turnover,
                    schema.stock_daily_bars.c.turnover_rate,
                    schema.stock_daily_bars.c.change_pct,
                ).where(
                    schema.stock_daily_bars.c.vt_symbol.in_(symbols),
                    schema.stock_daily_bars.c.trade_date >= data_start,
                    schema.stock_daily_bars.c.trade_date <= data_end,
                    event_window_exists,
                )
            ).mappings().all()
        ]
        sentiment_points = load_sentiment_points(session, data_start, last_date)
        timing_panel = session.execute(
            select(schema.market_timing_panel.c.panel).where(
                schema.market_timing_panel.c.id == 1
            )
        ).scalar_one_or_none()
        timing_signals = (
            list((timing_panel.get("chart") or {}).get("signals") or [])
            if isinstance(timing_panel, Mapping)
            else []
        )

    sector_flow_dates = {
        _event_date_text(row.get("trade_date"))
        for row in sector_flows
        if row.get("trade_date")
    }
    valid_trade_dates = {
        str(row["trade_date"])
        for row in daily_bars
        if row.get("trade_date")
    }
    daily_bars_by_key = {
        (str(row.get("vt_symbol") or ""), str(row.get("trade_date") or "")): row
        for row in daily_bars
    }
    event_count_before_validation = len(events)
    events = [
        event
        for event in events
        if str(event.get("trade_date") or "") in valid_trade_dates
        and (
            daily_bar := daily_bars_by_key.get(
                (str(event.get("vt_symbol") or ""), str(event.get("trade_date") or "")),
            )
        ) is not None
        and event_matches_daily_bar(event, daily_bar)
    ]
    event_dates = sorted({str(event["trade_date"]) for event in events if event.get("trade_date")})
    failed_events = [event for event in events if not bool(event.get("is_sealed"))]
    failed_with_last_seal = [event for event in failed_events if event.get("last_limit_time")]
    observed_reseals = [
        event
        for event in events
        if event.get("first_limit_time")
        and event.get("last_limit_time")
        and str(event["last_limit_time"]) > str(event["first_limit_time"])
    ]
    return {
        "events": events,
        "memberships": memberships,
        "sector_flows": sector_flows,
        "sector_scores": sector_scores,
        "stock_flows": stock_flows,
        "daily_bars": daily_bars,
        "sentiment_points": sentiment_points,
        "timing_signals": timing_signals,
        "coverage": {
            "event_start": event_dates[0] if event_dates else None,
            "event_end": event_dates[-1] if event_dates else None,
            "event_trade_days": len(event_dates),
            "event_count": len(events),
            "event_rejected_count": event_count_before_validation - len(events),
            "sector_flow_trade_days": len(sector_flow_dates),
            "sector_score_trade_days": len(
                {str(row.get("as_of_date") or "") for row in sector_scores if row.get("as_of_date")}
            ),
            "sentiment_trade_days": len(sentiment_points),
            "timing_signal_count": len(timing_signals),
            "stock_flow_trade_days": len(
                {str(row.get("trade_date") or "") for row in stock_flows if row.get("trade_date")}
            ),
            "observed_reseal_event_count": len(observed_reseals),
            "failed_board_event_count": len(failed_events),
            "failed_board_last_seal_coverage": round(
                len(failed_with_last_seal) / len(failed_events), 4
            )
            if failed_events
            else None,
            "strict_reseal_queue_coverage": False,
            "membership_mode": "current_snapshot",
            "minute_or_tick_coverage": False,
        },
    }


def _empty_dataset(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "events": events,
        "memberships": [],
        "sector_flows": [],
        "sector_scores": [],
        "stock_flows": [],
        "daily_bars": [],
        "sentiment_points": [],
        "timing_signals": [],
        "coverage": {
            "event_start": None,
            "event_end": None,
            "event_trade_days": 0,
            "event_count": len(events),
            "sector_flow_trade_days": 0,
            "stock_flow_trade_days": 0,
            "observed_reseal_event_count": 0,
            "failed_board_event_count": 0,
            "failed_board_last_seal_coverage": None,
            "strict_reseal_queue_coverage": False,
            "membership_mode": "current_snapshot",
            "minute_or_tick_coverage": False,
        },
    }


def _plain_row(row: Mapping[str, Any]) -> dict[str, object]:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    return result


def _daily_bar_row(row: Mapping[str, Any]) -> dict[str, object]:
    result = _plain_row(row)
    result["trade_date"] = _event_date_text(result.get("trade_date"))
    return result


def _event_date_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return date(
                int(text[:4]),
                int(text[4:6]),
                int(text[6:8]),
            ).isoformat()
        except ValueError:
            return None
    for format_string in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], format_string).date().isoformat()
        except ValueError:
            continue
    return None


def _date_in_range(value: object, start: date | None, end: date | None) -> bool:
    normalized = _event_date_text(value)
    if normalized is None:
        return False
    parsed = date.fromisoformat(normalized)
    return (start is None or parsed >= start) and (end is None or parsed <= end)


def _text_date_in_range(value: object, start: date, end: date) -> bool:
    normalized = _event_date_text(value)
    if normalized is None:
        return False
    parsed = date.fromisoformat(normalized)
    return start <= parsed <= end


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _event_version(row: Mapping[str, object]) -> tuple[str, int]:
    timestamp = row.get("updated_at") or row.get("created_at") or ""
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        row_id = 0
    return str(timestamp), row_id
