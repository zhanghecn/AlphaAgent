"""First-touch time research for main-board limit-up events."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Any

import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up.domain import (
    is_eligible_main_board,
    normalize_limit_time,
)
from alphaagent.server.services.limit_up.lane_repository import merge_rich_event_rows
from alphaagent.server.services.limit_up.repository import LIMIT_EVENT_TYPES


ROUND_TRIP_COST_RATE = 0.0031
MAX_MAIN_BOARD_D1_MOVE_PCT = 11.5
MIN_RANK_SAMPLES = 30
CALENDAR_SYMBOL = "000001.SSE"

TIME_BUCKETS = (
    ("auction_open", "09:25-09:30", 9 * 3600 + 25 * 60, 9 * 3600 + 30 * 60, False),
    ("morning_0930_1000", "09:30-10:00", 9 * 3600 + 30 * 60, 10 * 3600, False),
    ("morning_1000_1100", "10:00-11:00", 10 * 3600, 11 * 3600, False),
    ("morning_1100_1130", "11:00-11:30", 11 * 3600, 11 * 3600 + 30 * 60, True),
    ("afternoon_1300_1400", "13:00-14:00", 13 * 3600, 14 * 3600, False),
    ("afternoon_1400_1500", "14:00-15:00", 14 * 3600, 15 * 3600, True),
)


def classify_first_limit_time(value: object) -> tuple[str, str] | None:
    """Map a provider time value into a stable first-touch bucket."""

    normalized = normalize_limit_time(value)
    if normalized is None:
        return None
    hour, minute, second = (int(part) for part in normalized.split(":"))
    seconds = hour * 3600 + minute * 60 + second
    for key, label, start, end, inclusive_end in TIME_BUCKETS:
        if seconds >= start and (seconds <= end if inclusive_end else seconds < end):
            return key, label
    return None


def build_time_bucket_observations(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    trading_dates: Sequence[object],
    *,
    total_cost_rate: float = ROUND_TRIP_COST_RATE,
) -> pd.DataFrame:
    """Attach exact D+1 paths while preserving the original event decision."""

    if total_cost_rate < 0:
        raise ValueError("total_cost_rate must be non-negative")
    calendar = sorted({parsed for value in trading_dates if (parsed := _date_value(value)) is not None})
    calendar_set = set(calendar)
    next_date = {calendar[index]: calendar[index + 1] for index in range(len(calendar) - 1)}
    bars = _bar_index(daily_bars)
    rows = [
        _observation(dict(event), bars, calendar_set, next_date, total_cost_rate)
        for event in events
    ]
    frame = pd.DataFrame(rows)
    frame.attrs["total_cost_rate"] = total_cost_rate
    return frame


def summarize_time_buckets(
    observations: pd.DataFrame,
    *,
    min_rank_samples: int = MIN_RANK_SAMPLES,
) -> dict[str, object]:
    """Summarize seal success and sealed-board D+1 premiums by time bucket."""

    if observations.empty:
        return _empty_report(observations)
    required = {
        "bucket_key",
        "bucket_label",
        "event_date",
        "touch_eligible",
        "is_sealed",
        "premium_ready",
        "reseal_proxy",
    }
    missing = sorted(required.difference(observations.columns))
    if missing:
        raise ValueError(f"observations missing required columns: {', '.join(missing)}")

    rows = [_bucket_summary(observations, key, label) for key, label, *_ in TIME_BUCKETS]
    by_year = _yearly_summaries(observations)
    status_counts = Counter(str(value) for value in observations["outcome_status"])
    report = {
        "status": "ready",
        "coverage": dict(observations.attrs.get("coverage") or {}),
        "dataset": _dataset_summary(observations),
        "costs": {
            "total_round_trip_cost_pct": _round(
                float(observations.attrs.get("total_cost_rate", ROUND_TRIP_COST_RATE)) * 100
            )
        },
        "by_time_bucket": rows,
        "by_year": by_year,
        "exclusions": {
            "invalid_first_limit_time": status_counts["invalid_first_limit_time"],
            "event_date_not_in_calendar": status_counts["event_date_not_in_calendar"],
            "missing_d_bar": status_counts["missing_d_bar"],
            "missing_next_trade_date": status_counts["missing_next_trade_date"],
            "missing_d1_bar": status_counts["missing_d1_bar"],
            "invalid_d1_path": status_counts["invalid_d1_path"],
        },
        "best_buckets": _best_buckets(rows, max(int(min_rank_samples), 1)),
        "limitations": _limitations(),
    }
    return report


def run_time_bucket_research() -> dict[str, object]:
    """Load current auditable history and run the time-bucket study."""

    events, bars, trading_dates, coverage = _load_research_data()
    observations = build_time_bucket_observations(events, bars, trading_dates)
    observations.attrs["coverage"] = coverage
    report = summarize_time_buckets(observations)
    _validate_report(report)
    return report


def render_markdown_report(report: Mapping[str, object]) -> str:
    """Render the research result as a compact Chinese evidence report."""

    coverage = _mapping(report.get("coverage"))
    dataset = _mapping(report.get("dataset"))
    exclusions = _mapping(report.get("exclusions"))
    lines = [
        "# 涨停首次触板时间分段研究",
        "",
        "## 口径",
        "",
        "- 主样本：沪深主板、当前名称非 ST，按首次触板时间分段。",
        "- 封板率：最终封住数 / 同时段全部触板数（含最终炸板）。",
        "- D+1 溢价：只统计最终封住且下一交易日行情合法的样本，以 D 日收盘价为基准。",
        "- 回封代理：`open_times > 0` 且最终封住；它仍不等于真实排队成交。",
        "",
        "## 数据覆盖",
        "",
        f"- 可信事件区间：`{coverage.get('event_start')}` 至 `{coverage.get('event_end')}`，`{coverage.get('event_trade_days', 0)}` 个交易日。",
        f"- 供应商原始事件日期 `{coverage.get('source_event_trade_days', 0)}` 个；排除非交易日 `{', '.join(coverage.get('non_trading_event_dates') or []) or '-'}`。",
        f"- 原始事件 `{coverage.get('raw_event_rows', 0)}` 行；去重后 `{coverage.get('deduplicated_event_count', 0)}` 条；可信主板非 ST `{coverage.get('eligible_event_count', 0)}` 条。",
        f"- 进入封板率分母 `{dataset.get('touch_count', 0)}` 条；最终封住 `{dataset.get('sealed_count', 0)}` 条；D+1 有效溢价 `{dataset.get('premium_sample_count', 0)}` 条。",
        "",
        "## 全部封板样本",
        "",
        "| 首次触板 | 触板数 | 封住数 | 封板率 | D+1样本 | 开盘胜率 | 开盘均值 | 开盘净胜率 | 开盘净均值 | 收盘胜率 | 收盘均值 | 收盘净胜率 | 收盘净均值 | 最高均值 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("by_time_bucket") or []:
        item = _mapping(row)
        lines.append(
            f"| {item.get('bucket_label')} | {item.get('touch_count')} | {item.get('sealed_count')} | "
            f"{_pct(item.get('seal_success_rate_pct'))} | {item.get('premium_sample_count')} | "
            f"{_pct(item.get('d1_open_gross_win_rate_pct'))} | {_pct(item.get('d1_open_gross_average_return_pct'))} | "
            f"{_pct(item.get('d1_open_net_win_rate_pct'))} | {_pct(item.get('d1_open_net_average_return_pct'))} | "
            f"{_pct(item.get('d1_close_gross_win_rate_pct'))} | {_pct(item.get('d1_close_gross_average_return_pct'))} | "
            f"{_pct(item.get('d1_close_net_win_rate_pct'))} | {_pct(item.get('d1_close_net_average_return_pct'))} | "
            f"{_pct(item.get('d1_high_gross_average_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## 回封可成交代理",
            "",
            "| 首次触板 | 样本 | D+1开盘净胜率 | 开盘净均值 | D+1收盘净胜率 | 收盘净均值 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("by_time_bucket") or []:
        item = _mapping(row)
        lines.append(
            f"| {item.get('bucket_label')} | {item.get('reseal_proxy_sample_count')} | "
            f"{_pct(item.get('reseal_d1_open_net_win_rate_pct'))} | {_pct(item.get('reseal_d1_open_net_average_return_pct'))} | "
            f"{_pct(item.get('reseal_d1_close_net_win_rate_pct'))} | {_pct(item.get('reseal_d1_close_net_average_return_pct'))} |"
        )
    lines.extend(["", "## 最优分段", ""])
    for key, label in (
        ("seal_success", "封板成功率"),
        ("d1_open_net", "D+1 开盘净收益"),
        ("d1_close_net", "D+1 收盘净收益"),
        ("reseal_d1_open_net", "回封代理 D+1 开盘净收益"),
        ("reseal_d1_close_net", "回封代理 D+1 收盘净收益"),
    ):
        item = _mapping(_mapping(report.get("best_buckets")).get(key))
        lines.append(
            f"- {label}最高：`{item.get('bucket_label') or '-'}`，样本 `{item.get('sample_count') or 0}`，指标 `{_pct(item.get('value'))}`。"
        )
    lines.extend(
        [
            "",
            "## 年度方向核对",
            "",
            "| 年份 | 首次触板 | 触板数 | 封板率 | D+1样本 | 开盘净均值 | 收盘净均值 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("by_year") or []:
        item = _mapping(row)
        lines.append(
            f"| {item.get('year')} | {item.get('bucket_label')} | {item.get('touch_count')} | "
            f"{_pct(item.get('seal_success_rate_pct'))} | {item.get('premium_sample_count')} | "
            f"{_pct(item.get('d1_open_net_average_return_pct'))} | {_pct(item.get('d1_close_net_average_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## 数据排除",
            "",
            f"- 时间不可用/非交易时段：`{exclusions.get('invalid_first_limit_time', 0)}`。",
            f"- D 日不在交易日历：`{exclusions.get('event_date_not_in_calendar', 0)}`；缺 D 日线：`{exclusions.get('missing_d_bar', 0)}`。",
            f"- 无下一交易日：`{exclusions.get('missing_next_trade_date', 0)}`；缺 D+1 日线：`{exclusions.get('missing_d1_bar', 0)}`。",
            f"- D+1 价格断点：`{exclusions.get('invalid_d1_path', 0)}`。",
            "",
            "## 限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    return "\n".join(lines).rstrip() + "\n"


def _observation(
    event: dict[str, object],
    bars: Mapping[tuple[str, date], Mapping[str, object]],
    calendar: set[date],
    next_dates: Mapping[date, date],
    total_cost_rate: float,
) -> dict[str, object]:
    symbol = str(event.get("vt_symbol") or "")
    event_date = _date_value(event.get("trade_date"))
    bucket = classify_first_limit_time(event.get("first_limit_time"))
    d_bar = bars.get((symbol, event_date)) if event_date else None
    status = _touch_status(event_date, bucket, d_bar, calendar)
    next_date = next_dates.get(event_date) if event_date else None
    d1_bar = bars.get((symbol, next_date)) if next_date else None
    is_sealed = bool(event.get("is_sealed"))
    returns: dict[str, float | None] = {
        "d1_open_gross_return_pct": None,
        "d1_high_gross_return_pct": None,
        "d1_low_gross_return_pct": None,
        "d1_close_gross_return_pct": None,
        "d1_open_net_return_pct": None,
        "d1_close_net_return_pct": None,
    }
    if status == "touch_ready":
        status, returns = _outcome_values(is_sealed, d_bar, d1_bar, next_date, total_cost_rate)
    premium_ready = status == "ready"
    open_times = _integer(event.get("open_times"))
    return {
        **event,
        "event_date": event_date,
        "first_limit_time": normalize_limit_time(event.get("first_limit_time")),
        "bucket_key": bucket[0] if bucket else None,
        "bucket_label": bucket[1] if bucket else None,
        "is_sealed": is_sealed,
        "open_times": open_times,
        "touch_eligible": status not in {
            "invalid_first_limit_time",
            "event_date_not_in_calendar",
            "missing_d_bar",
        },
        "next_trade_date": next_date,
        "premium_ready": premium_ready,
        "reseal_proxy": premium_ready and open_times > 0,
        "outcome_status": status,
        **returns,
    }


def _touch_status(
    event_date: date | None,
    bucket: tuple[str, str] | None,
    d_bar: Mapping[str, object] | None,
    calendar: set[date],
) -> str:
    if bucket is None:
        return "invalid_first_limit_time"
    if event_date is None or event_date not in calendar:
        return "event_date_not_in_calendar"
    if d_bar is None or _number(d_bar.get("close_price")) in (None, 0):
        return "missing_d_bar"
    return "touch_ready"


def _outcome_values(
    is_sealed: bool,
    d_bar: Mapping[str, object] | None,
    d1_bar: Mapping[str, object] | None,
    next_date: date | None,
    total_cost_rate: float,
) -> tuple[str, dict[str, float | None]]:
    if not is_sealed:
        return "not_sealed", _empty_returns()
    if next_date is None:
        return "missing_next_trade_date", _empty_returns()
    if d1_bar is None:
        return "missing_d1_bar", _empty_returns()
    entry = _number((d_bar or {}).get("close_price"))
    path = {
        key: _return_pct(entry, _number(d1_bar.get(column)))
        for key, column in (
            ("open", "open_price"),
            ("high", "high_price"),
            ("low", "low_price"),
            ("close", "close_price"),
        )
    }
    if any(
        value is None or abs(value) > MAX_MAIN_BOARD_D1_MOVE_PCT
        for value in path.values()
    ):
        return "invalid_d1_path", _empty_returns()
    cost_pct = total_cost_rate * 100
    return "ready", {
        "d1_open_gross_return_pct": path["open"],
        "d1_high_gross_return_pct": path["high"],
        "d1_low_gross_return_pct": path["low"],
        "d1_close_gross_return_pct": path["close"],
        "d1_open_net_return_pct": path["open"] - cost_pct,
        "d1_close_net_return_pct": path["close"] - cost_pct,
    }


def _bucket_summary(frame: pd.DataFrame, key: str, label: str) -> dict[str, object]:
    touches = frame[frame["touch_eligible"] & frame["bucket_key"].eq(key)]
    sealed = touches[touches["is_sealed"]]
    premiums = touches[touches["premium_ready"]]
    reseals = touches[touches["reseal_proxy"]]
    open_gross = _return_metrics(premiums["d1_open_gross_return_pct"])
    close_gross = _return_metrics(premiums["d1_close_gross_return_pct"])
    open_net = _return_metrics(premiums["d1_open_net_return_pct"])
    close_net = _return_metrics(premiums["d1_close_net_return_pct"])
    reseal_open = _return_metrics(reseals["d1_open_net_return_pct"])
    reseal_close = _return_metrics(reseals["d1_close_net_return_pct"])
    return {
        "bucket_key": key,
        "bucket_label": label,
        "touch_count": len(touches),
        "sealed_count": len(sealed),
        "seal_success_rate_pct": _rate(len(sealed), len(touches)),
        "premium_sample_count": len(premiums),
        "d1_open_gross_win_rate_pct": open_gross["win_rate_pct"],
        "d1_open_gross_average_return_pct": open_gross["average_return_pct"],
        "d1_open_gross_median_return_pct": open_gross["median_return_pct"],
        "d1_open_net_win_rate_pct": open_net["win_rate_pct"],
        "d1_open_net_average_return_pct": open_net["average_return_pct"],
        "d1_close_gross_win_rate_pct": close_gross["win_rate_pct"],
        "d1_close_gross_average_return_pct": close_gross["average_return_pct"],
        "d1_close_gross_median_return_pct": close_gross["median_return_pct"],
        "d1_close_net_win_rate_pct": close_net["win_rate_pct"],
        "d1_close_net_average_return_pct": close_net["average_return_pct"],
        "d1_high_gross_average_return_pct": _average(premiums["d1_high_gross_return_pct"]),
        "d1_low_gross_average_return_pct": _average(premiums["d1_low_gross_return_pct"]),
        "reseal_proxy_sample_count": len(reseals),
        "reseal_d1_open_net_win_rate_pct": reseal_open["win_rate_pct"],
        "reseal_d1_open_net_average_return_pct": reseal_open["average_return_pct"],
        "reseal_d1_close_net_win_rate_pct": reseal_close["win_rate_pct"],
        "reseal_d1_close_net_average_return_pct": reseal_close["average_return_pct"],
    }


def _yearly_summaries(frame: pd.DataFrame) -> list[dict[str, object]]:
    eligible = frame[frame["touch_eligible"] & frame["event_date"].notna()].copy()
    if eligible.empty:
        return []
    eligible["year"] = eligible["event_date"].map(lambda value: value.year)
    rows: list[dict[str, object]] = []
    for year, subset in eligible.groupby("year", sort=True):
        for key, label, *_ in TIME_BUCKETS:
            summary = _bucket_summary(subset, key, label)
            if summary["touch_count"]:
                rows.append({"year": int(year), **summary})
    return rows


def _best_buckets(rows: Sequence[Mapping[str, object]], minimum: int) -> dict[str, object]:
    return {
        "seal_success": _best(rows, "seal_success_rate_pct", "touch_count", minimum),
        "d1_open_net": _best(rows, "d1_open_net_average_return_pct", "premium_sample_count", minimum),
        "d1_close_net": _best(rows, "d1_close_net_average_return_pct", "premium_sample_count", minimum),
        "reseal_d1_open_net": _best(
            rows,
            "reseal_d1_open_net_average_return_pct",
            "reseal_proxy_sample_count",
            minimum,
        ),
        "reseal_d1_close_net": _best(
            rows,
            "reseal_d1_close_net_average_return_pct",
            "reseal_proxy_sample_count",
            minimum,
        ),
    }


def _best(
    rows: Sequence[Mapping[str, object]],
    metric: str,
    sample_field: str,
    minimum: int,
) -> dict[str, object] | None:
    eligible = [
        row
        for row in rows
        if int(row.get(sample_field) or 0) >= minimum and _number(row.get(metric)) is not None
    ]
    if not eligible:
        return None
    winner = max(eligible, key=lambda row: float(row[metric]))
    return {
        "bucket_key": winner["bucket_key"],
        "bucket_label": winner["bucket_label"],
        "sample_count": winner[sample_field],
        "value": winner[metric],
    }


def _dataset_summary(frame: pd.DataFrame) -> dict[str, object]:
    eligible = frame[frame["touch_eligible"]]
    premiums = eligible[eligible["premium_ready"]]
    dates = eligible["event_date"].dropna()
    return {
        "observation_count": len(frame),
        "touch_count": len(eligible),
        "sealed_count": int(eligible["is_sealed"].sum()),
        "premium_sample_count": len(premiums),
        "reseal_proxy_sample_count": int(eligible["reseal_proxy"].sum()),
        "event_start": dates.min().isoformat() if not dates.empty else None,
        "event_end": dates.max().isoformat() if not dates.empty else None,
        "event_trade_days": int(dates.nunique()),
    }


def _load_research_data() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[date],
    dict[str, object],
]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        event_rows = [
            dict(row)
            for row in session.execute(
                select(schema.stock_events).where(
                    schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES)
                )
            ).mappings()
        ]
        merged = merge_rich_event_rows(event_rows)
        symbols = sorted({symbol for symbol, _ in merged})
        stock_names = dict(
            session.execute(
                select(schema.stocks.c.vt_symbol, schema.stocks.c.name).where(
                    schema.stocks.c.vt_symbol.in_(symbols)
                )
            ).all()
        )
        events = [
            {**event, "name": str(stock_names.get(symbol) or event.get("name") or "")}
            for (symbol, _), event in merged.items()
            if is_eligible_main_board(symbol, str(stock_names.get(symbol) or event.get("name") or ""))
        ]
        if not events:
            return [], [], [], _coverage(event_rows, merged, events, [], [])
        event_dates = sorted({event["trade_date"] for event in events})
        calendar = list(
            session.execute(
                select(schema.stock_daily_bars.c.trade_date)
                .where(
                    schema.stock_daily_bars.c.vt_symbol == CALENDAR_SYMBOL,
                    schema.stock_daily_bars.c.trade_date >= event_dates[0],
                )
                .order_by(schema.stock_daily_bars.c.trade_date)
            ).scalars()
        )
        bar_end = calendar[-1] if calendar else event_dates[-1]
        event_symbols = sorted({str(event["vt_symbol"]) for event in events})
        bars = [
            dict(row)
            for row in session.execute(
                select(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.open_price,
                    schema.stock_daily_bars.c.high_price,
                    schema.stock_daily_bars.c.low_price,
                    schema.stock_daily_bars.c.close_price,
                ).where(
                    schema.stock_daily_bars.c.vt_symbol.in_(event_symbols),
                    schema.stock_daily_bars.c.trade_date.between(event_dates[0], bar_end),
                )
            ).mappings()
        ]
    return events, bars, calendar, _coverage(event_rows, merged, events, bars, calendar)


def _coverage(
    raw_rows: Sequence[Mapping[str, object]],
    merged: Mapping[object, object],
    events: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> dict[str, object]:
    dates = sorted({_date_value(event.get("trade_date")) for event in events} - {None})
    calendar_set = set(calendar)
    reliable_dates = [trade_date for trade_date in dates if trade_date in calendar_set]
    non_trading_dates = [trade_date for trade_date in dates if trade_date not in calendar_set]
    sources = Counter(str(row.get("source") or "") for row in raw_rows)
    return {
        "raw_event_rows": len(raw_rows),
        "deduplicated_event_count": len(merged),
        "eligible_event_count": len(events),
        "event_start": reliable_dates[0].isoformat() if reliable_dates else None,
        "event_end": reliable_dates[-1].isoformat() if reliable_dates else None,
        "source_event_trade_days": len(dates),
        "event_trade_days": len(reliable_dates),
        "non_trading_event_dates": [value.isoformat() for value in non_trading_dates],
        "daily_bar_rows": len(bars),
        "calendar_days": len(calendar),
        "sources": dict(sorted(sources.items())),
        "universe": "current_main_board_non_st",
    }


def _bar_index(rows: Sequence[Mapping[str, object]]) -> dict[tuple[str, date], Mapping[str, object]]:
    result: dict[tuple[str, date], Mapping[str, object]] = {}
    for row in rows:
        symbol = str(row.get("vt_symbol") or "")
        trade_date = _date_value(row.get("trade_date"))
        if symbol and trade_date:
            result[(symbol, trade_date)] = row
    return result


def _return_metrics(values: pd.Series) -> dict[str, float | int | None]:
    numbers = pd.to_numeric(values, errors="coerce").dropna()
    if numbers.empty:
        return {"sample_count": 0, "win_rate_pct": None, "average_return_pct": None, "median_return_pct": None}
    return {
        "sample_count": len(numbers),
        "win_rate_pct": _round((numbers > 0).mean() * 100),
        "average_return_pct": _round(numbers.mean()),
        "median_return_pct": _round(numbers.median()),
    }


def _return_pct(base: float | None, value: float | None) -> float | None:
    if base is None or base <= 0 or value is None:
        return None
    return (value / base - 1) * 100


def _empty_returns() -> dict[str, float | None]:
    return {
        "d1_open_gross_return_pct": None,
        "d1_high_gross_return_pct": None,
        "d1_low_gross_return_pct": None,
        "d1_close_gross_return_pct": None,
        "d1_open_net_return_pct": None,
        "d1_close_net_return_pct": None,
    }


def _average(values: pd.Series) -> float | None:
    numbers = [_number(value) for value in values]
    valid = [value for value in numbers if value is not None]
    return _round(mean(valid)) if valid else None


def _rate(numerator: int, denominator: int) -> float | None:
    return _round(numerator / denominator * 100) if denominator else None


def _date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value)[:10].replace("-", "")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _round(value: object, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _pct(value: object) -> str:
    number = _round(value)
    return "-" if number is None else f"{number:.4f}%"


def _limitations() -> list[str]:
    return [
        "当前可信时间路径只覆盖 2025-06-27 起的沪深主板，不能称为 A 股自上市以来全部历史。",
        "创业板、科创板和北交所时间路径历史明显更短，未混入主板结果。",
        "证券范围按当前名称过滤非 ST，缺少逐日历史风险警示状态，存在幸存者偏差。",
        "D+1 溢价是最终封板后的条件结果；必须和同时间段封板成功率一起解读。",
        "09:25 一字板和早盘秒板通常无法成交；全部封板样本衡量板质量，不代表实盘收益。",
        "open_times > 0 只证明存在开板窗口，缺少 Tick/L2 时仍不能证明真实委托成交。",
    ]


def _empty_report(observations: pd.DataFrame) -> dict[str, object]:
    empty = pd.DataFrame(
        columns=(
            "touch_eligible",
            "bucket_key",
            "is_sealed",
            "premium_ready",
            "reseal_proxy",
            "d1_open_gross_return_pct",
            "d1_high_gross_return_pct",
            "d1_low_gross_return_pct",
            "d1_close_gross_return_pct",
            "d1_open_net_return_pct",
            "d1_close_net_return_pct",
        )
    )
    return {
        "status": "insufficient_data",
        "coverage": dict(observations.attrs.get("coverage") or {}),
        "dataset": {
            "observation_count": 0,
            "touch_count": 0,
            "sealed_count": 0,
            "premium_sample_count": 0,
            "reseal_proxy_sample_count": 0,
        },
        "costs": {"total_round_trip_cost_pct": ROUND_TRIP_COST_RATE * 100},
        "by_time_bucket": [_bucket_summary(empty, key, label) for key, label, *_ in TIME_BUCKETS],
        "by_year": [],
        "exclusions": {},
        "best_buckets": {},
        "limitations": _limitations(),
    }


def _validate_report(report: Mapping[str, object]) -> None:
    dataset = _mapping(report.get("dataset"))
    rows = report.get("by_time_bucket") or []
    if int(dataset.get("touch_count") or 0) != sum(int(_mapping(row).get("touch_count") or 0) for row in rows):
        raise RuntimeError("time-bucket touch counts are inconsistent")
    if int(dataset.get("premium_sample_count") or 0) != sum(
        int(_mapping(row).get("premium_sample_count") or 0) for row in rows
    ):
        raise RuntimeError("time-bucket premium counts are inconsistent")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_time_bucket_research()
    markdown = render_markdown_report(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(args.output)
        return
    print(markdown, end="")


if __name__ == "__main__":
    main()
