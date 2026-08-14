"""连板双口径对账: 东财涨停池 vs 日线重建 的当日涨停名单核对。

两口径(非ST口径, 与 review.py 统计口径一致):
- 东财侧: limit_up_pool_snapshots 当日 pool_type="zt" 行。东财涨停池天然
  不含 ST(实证 2026-08-12: 92 行 0 只 ST 名称), 故这里刻意不再做名称
  过滤——若东财口径漂移开始收录 ST, 对账应报警而不是被静默对齐。
- 日线侧: stock_limit_up_daily 当日 is_limit_up=True AND NOT is_st。
  当日是否「重建已跑」用任意行(含摸板/ST行)存在性判定: 重建只写涨停/
  摸板两类行, 某日即使全市场零涨停, 只要有摸板行也视为有数据。

已知合理差异(少量 diff 不一定是数据事故, 逐日盯 diff_count 突增即可):
- 东财漏收: close=high 铁定涨停但东财池未收录(2026-08-12 开开实业
  600272.SSE, close=high=17.27);
- 本地日线缺口: 个股日线停更导致日线侧漏判(2026-08-12 蓝盾光电
  300862.SZSE, 本地日线 2026-07-24 后缺失);
- 涨停价舍入/基准口径差: detector 按 round(prev_close*(1+ratio), 2) 精确
  命中判定, 与交易所/东财口径偶差一分(2026-08-12 浩淼科技 920856.BSE:
  11.49*1.30=14.937, detector 算 14.94, 实际收 14.93 被东财计为涨停)。

任一侧当日无数据 → status=missing_*(不炸, 返回空名单); 此时 matched/
diff 无意义置 0, verdict 按 diff_count=0 恒为 "aligned", 消费方应先看
status。健康巡检见 data_sync._lianban_parity_health(缺侧或 major_diff
→ warning)。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema as db_schema

# verdict 阈值: diff_count==0 aligned; <=2 minor_diff; >2 major_diff。
_MINOR_DIFF_MAX = 2


def _verdict(diff_count: int) -> str:
    if diff_count == 0:
        return "aligned"
    if diff_count <= _MINOR_DIFF_MAX:
        return "minor_diff"
    return "major_diff"


def parity_report(session, trade_date: date) -> dict[str, Any]:
    """东财涨停池口径 vs 日线重建口径 的当日涨停名单对账。

    返回 {trade_date, status, em_count, daily_count, matched, diff_count,
    em_only, daily_only, verdict}; 字段语义见模块 docstring。
    """
    snapshots = db_schema.limit_up_pool_snapshots
    daily = db_schema.stock_limit_up_daily

    pool_rows = session.execute(
        select(snapshots.c.vt_symbol, snapshots.c.name).where(
            snapshots.c.trade_date == trade_date,
            snapshots.c.pool_type == "zt",
        )
    ).all()
    daily_limit_rows = session.execute(
        select(daily.c.vt_symbol).where(
            daily.c.trade_date == trade_date,
            daily.c.is_limit_up.is_(True),
            daily.c.is_st.is_(False),
        )
    ).all()
    # 当日重建是否已跑: 任意行(含摸板/ST)存在即视为有数据。
    daily_present = session.execute(
        select(daily.c.vt_symbol).where(daily.c.trade_date == trade_date).limit(1)
    ).first() is not None

    em_names = {str(r.vt_symbol): r.name for r in pool_rows}
    daily_symbols = {str(r.vt_symbol) for r in daily_limit_rows}

    report: dict[str, Any] = {
        "trade_date": trade_date.isoformat(),
        "status": "ok",
        "em_count": len(em_names),
        "daily_count": len(daily_symbols),
        "matched": 0,
        "diff_count": 0,
        "em_only": [],
        "daily_only": [],
        "verdict": "aligned",
    }
    if not em_names and not daily_present:
        report["status"] = "missing_both"
        return report
    if not em_names:
        report["status"] = "missing_pool"
        return report
    if not daily_present:
        report["status"] = "missing_daily"
        return report

    em_only = sorted(set(em_names) - daily_symbols)
    daily_only = sorted(daily_symbols - set(em_names))
    names = _resolve_names(session, em_names, em_only, daily_only)

    report["matched"] = len(set(em_names) & daily_symbols)
    report["em_only"] = [
        {"vt_symbol": sym, "name": names.get(sym)} for sym in em_only
    ]
    report["daily_only"] = [
        {"vt_symbol": sym, "name": names.get(sym)} for sym in daily_only
    ]
    report["diff_count"] = len(em_only) + len(daily_only)
    report["verdict"] = _verdict(report["diff_count"])
    return report


def _resolve_names(
    session,
    em_names: dict[str, str | None],
    em_only: list[str],
    daily_only: list[str],
) -> dict[str, str | None]:
    """差异名单的名称: 东财侧用池行名称; 仅日线侧的查 stocks 表(重建表无
    name 列), stocks 未收录的符号容错为 None。"""
    names: dict[str, str | None] = {sym: em_names.get(sym) for sym in em_only}
    if daily_only:
        rows = session.execute(
            select(db_schema.stocks.c.vt_symbol, db_schema.stocks.c.name).where(
                db_schema.stocks.c.vt_symbol.in_(daily_only)
            )
        ).all()
        resolved = {str(r.vt_symbol): r.name for r in rows}
        for sym in daily_only:
            names[sym] = resolved.get(sym)
    return names


def latest_common_trade_date(session) -> date | None:
    """最近一个双侧都有数据的交易日(东财 zt 池 ∩ 日线重建, 按归档日期求交)。

    任一侧空表/无重叠日 → None。不用 min(两侧各自 max_date): 某一侧中间
    缺一天时 min(max) 可能落在缺口上, 交集口径才保证双侧真都有数据。
    """
    snapshots = db_schema.limit_up_pool_snapshots
    daily = db_schema.stock_limit_up_daily
    pool_dates = (
        select(snapshots.c.trade_date)
        .where(snapshots.c.pool_type == "zt")
        .distinct()
    )
    return session.execute(
        select(func.max(daily.c.trade_date)).where(
            daily.c.trade_date.in_(pool_dates)
        )
    ).scalar()


def latest_parity_report(session) -> dict[str, Any] | None:
    """最近一个双侧都有数据的交易日的 parity_report; 无重叠日 → None。"""
    target = latest_common_trade_date(session)
    if target is None:
        return None
    return parity_report(session, target)
