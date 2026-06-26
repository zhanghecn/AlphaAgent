"""Financial-data visibility helpers for quant screening and backtests."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import desc, select

from alphaagent.server.db import schema
from alphaagent.server.services.quant.factors import score_financial_report, to_float


FINANCIAL_AS_OF_POLICY = "回测只使用本地已落库且 publish_date <= trade_date 的财报；详情页实时可查不等于历史当日可用。"


def financial_coverage_summary(session, vt_symbol: str, trade_date: date) -> dict[str, Any]:
    rows = session.execute(
        select(
            schema.stock_financial_reports.c.publish_date,
            schema.stock_financial_reports.c.report_date,
            schema.stock_financial_reports.c.period_type,
        )
        .where(schema.stock_financial_reports.c.vt_symbol == vt_symbol)
        .order_by(desc(schema.stock_financial_reports.c.publish_date), desc(schema.stock_financial_reports.c.report_date))
    ).mappings().all()
    return financial_coverage_summary_from_rows(rows, trade_date)


def financial_coverage_summary_from_rows(rows: list[dict[str, Any]], trade_date: date) -> dict[str, Any]:
    available = []
    latest_publish: date | None = None
    missing_publish_count = 0
    future_publish_count = 0
    for row in rows:
        publish_date = as_report_date(row.get("publish_date"))
        if publish_date is None:
            missing_publish_count += 1
            continue
        latest_publish = max(latest_publish, publish_date) if latest_publish else publish_date
        if publish_date <= trade_date:
            available.append(row)
        else:
            future_publish_count += 1
    latest_available = available[0] if available else None
    latest_available_publish = as_report_date(latest_available.get("publish_date")) if latest_available else None
    return {
        "local_report_count": len(rows),
        "usable_report_count": len(available),
        "missing_publish_date_count": missing_publish_count,
        "future_publish_date_count": future_publish_count,
        "latest_publish_date": latest_publish.isoformat() if latest_publish else None,
        "latest_usable_publish_date": latest_available_publish.isoformat() if latest_available_publish else None,
        "latest_usable_report_date": str(latest_available.get("report_date")) if latest_available else None,
        "policy": FINANCIAL_AS_OF_POLICY,
    }


def operating_cash_flow_yoy(
    rows: list[dict[str, Any]], current: dict[str, Any], trade_date: date
) -> float | None:
    """经营现金流同比改善（当期 vs 去年同期累计值）。

    修正 ``score_financial_report`` 只看绝对正负对周期反转股的错杀：覆铜板/周期品
    涨价周期里现金流常从大亏转微亏，绝对值仍为负但同比大幅改善。rows 按 report_date
    DESC 排序；去年同期 = 当期 report_date 减一年（季度末日期 replace 安全），且要求
    publish_date <= trade_date 防未来函数。分母取去年同期绝对值避免负数除法失真；
    去年同期缺失或为 0 返回 None（由打分函数退回绝对正负兜底）。
    """
    current_ocf = to_float(current.get("operating_cash_flow"))
    current_report_date = as_report_date(current.get("report_date"))
    if current_ocf is None or current_report_date is None:
        return None
    prior_target = current_report_date.replace(year=current_report_date.year - 1)
    for row in rows:
        if as_report_date(row.get("report_date")) != prior_target:
            continue
        prior_publish = as_report_date(row.get("publish_date"))
        if prior_publish is None or prior_publish > trade_date:
            continue
        prior_ocf = to_float(row.get("operating_cash_flow"))
        if prior_ocf is None or prior_ocf == 0:
            return None
        return (current_ocf - prior_ocf) / abs(prior_ocf) * 100.0
    return None


def financial_scores_from_rows_by_symbol(
    rows_by_symbol: dict[str, list[dict[str, Any]]],
    trade_date: date,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for vt_symbol, rows in rows_by_symbol.items():
        current = None
        for row in rows:
            publish_date = as_report_date(row.get("publish_date"))
            if publish_date is None or publish_date > trade_date:
                continue
            current = row
            break
        if current is None:
            continue
        enriched = dict(current)
        cash_flow_yoy = operating_cash_flow_yoy(rows, current, trade_date)
        if cash_flow_yoy is not None:
            enriched["operating_cash_flow_yoy"] = cash_flow_yoy
        result[vt_symbol] = score_financial_report(enriched)
    return result


def as_report_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
