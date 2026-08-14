"""连板天梯历史: 近 N 个有涨停交易日的梯队/晋级率/龙头序列(研究型端点)。

数据源 stock_limit_up_daily(A3 全历史重建产物, is_limit_up=True, 默认排除
is_st)。窗口取「有涨停行的最近 N 个 trade_date」—— 数据驱动, 既不是自然日
也不依赖 stock_daily_bars 交易日历: 某日全市场零涨停(或尚未重建)→ 当日无
is_limit_up 行 → 不进窗口, dates 只含真实有涨停的交易日; 表内历史不足 N 日
时按已有日期返回, dates 长度即实际窗口。

口径:
- matrix: 每日按 limit_up_count 分档计数, 档位 "1".."5" + "6+"(streak>=6
  合并, 与 promotion.relay_5d 同档); total=当日涨停家数(含首板);
  max_streak=当日最大连板数; leader=最高板个股, 同板位多只时取 vt_symbol
  字典序第一只(日线表无封板时间, 保证确定性), name 取 stocks 表快照,
  缺失回落 vt_symbol。
- promotion_matrix: 窗口内分板位晋级率(当日 N 板 → 窗口内下一交易日
  N+1 板), 与 promotion.by_streak 完全同口径 —— 直接复用其 _by_streak
  helper(含 8+ 合并档、晋级=次日 streak>=9、窗口尾日样本剔除), 只是窗口
  为 N 天短窗(promotion_stats 默认 250 日), 用于研究近期接力生态。
  注意语义差异: 本模块「次日」= 窗口内下一有数据日(窗口由涨停行驱动,
  天然跳过零涨停/未重建日), promotion 的「次日」= 交易日历下一日。
- leaders: 每日最高板龙头(与 matrix.leader 同一只), 透出 is_one_word。
- days: 默认 60; 合法区间 [5, 250] 由 API 层 FastAPI Query 校验(越界 422),
  服务层信任调用方。
- 性能: 两条 SQL(distinct 日期尾段 + 窗口行一次拉回, 60日×~60只≈3600行)
  + 一条 stocks 名称批量查询, Python 聚合, 无逐日循环查询, P95<100ms。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema as db_schema
from alphaagent.server.services.lianban.promotion import _by_streak

_TIER_KEYS = ("1", "2", "3", "4", "5", "6+")
_TIER_MERGE_MIN = 6  # streak>=6 合并 "6+"(与 promotion.relay_5d 同档)


def _load_window_dates(session, days: int, include_st: bool) -> list[date]:
    """有涨停行的最近 N 个 trade_date(升序; 零涨停日天然无行不进窗口)。"""
    table = db_schema.stock_limit_up_daily
    conditions = [table.c.is_limit_up.is_(True)]
    if not include_st:
        conditions.append(table.c.is_st.is_(False))
    stmt = (
        select(table.c.trade_date)
        .where(*conditions)
        .distinct()
        .order_by(table.c.trade_date.desc())
        .limit(int(days))
    )
    dates = [row[0] for row in session.execute(stmt)]
    dates.reverse()
    return dates


def _load_window_rows(
    session, start: date, end: date, include_st: bool
) -> dict[date, list[dict[str, Any]]]:
    """[start, end] 涨停行 → {trade_date: [行]}; 过滤口径与日期查询一致。

    start/end 即窗口首末日, 区间内合格日期恰好是窗口日期(窗口=最近 N 个
    合格日期), 不会拉到窗口外行。
    """
    table = db_schema.stock_limit_up_daily
    conditions = [
        table.c.trade_date >= start,
        table.c.trade_date <= end,
        table.c.is_limit_up.is_(True),
    ]
    if not include_st:
        conditions.append(table.c.is_st.is_(False))
    stmt = select(
        table.c.trade_date,
        table.c.vt_symbol,
        table.c.limit_up_count,
        table.c.is_one_word,
    ).where(*conditions)
    by_date: dict[date, list[dict[str, Any]]] = {}
    for row in session.execute(stmt):
        by_date.setdefault(row.trade_date, []).append(
            {
                "vt_symbol": str(row.vt_symbol),
                "streak": int(row.limit_up_count),
                "is_one_word": bool(row.is_one_word),
            }
        )
    return by_date


def _load_names(session, symbols: list[str]) -> dict[str, str]:
    """stocks 表名称快照(与 ladder._load_names 同查询); 缺失由调用方回落。"""
    if not symbols:
        return {}
    table = db_schema.stocks
    stmt = select(table.c.vt_symbol, table.c.name).where(
        table.c.vt_symbol.in_(symbols)
    )
    return {str(r.vt_symbol): str(r.name) for r in session.execute(stmt) if r.name}


def _tiers(day_rows: list[dict[str, Any]]) -> dict[str, int]:
    """当日分档计数: "1".."5" 独立档, streak>=6 合并 "6+"。"""
    tiers = {key: 0 for key in _TIER_KEYS}
    for row in day_rows:
        streak = row["streak"]
        if streak >= _TIER_MERGE_MIN:
            tiers["6+"] += 1
        elif streak >= 1:
            tiers[str(streak)] += 1
        # 防御: 涨停行 streak 恒 >=1; 病态 0 不进任何档(与 promotion 同处理)
    return tiers


def _top_row(day_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """当日最高板行; 同板位取 vt_symbol 字典序第一只(确定性)。"""
    if not day_rows:
        return None
    top_streak = max(row["streak"] for row in day_rows)
    return min(
        (row for row in day_rows if row["streak"] == top_streak),
        key=lambda row: row["vt_symbol"],
    )


def ladder_history(
    session, *, days: int = 60, include_st: bool = False
) -> dict[str, Any]:
    """近 N 个有涨停交易日的连板梯队历史(返回结构见模块 docstring)。"""
    dates = _load_window_dates(session, days, include_st)
    rows_by_date = (
        _load_window_rows(session, dates[0], dates[-1], include_st)
        if dates
        else {}
    )

    matrix: list[dict[str, Any]] = []
    leaders: list[dict[str, Any]] = []
    streak_maps: dict[date, dict[str, int]] = {}
    top_rows: list[tuple[date, dict[str, Any]]] = []
    for day in dates:
        day_rows = rows_by_date.get(day, [])
        streak_maps[day] = {row["vt_symbol"]: row["streak"] for row in day_rows}
        top = _top_row(day_rows)
        matrix.append(
            {
                "trade_date": day.isoformat(),
                "tiers": _tiers(day_rows),
                "total": len(day_rows),
                "max_streak": top["streak"] if top else 0,
                "leader": (
                    {
                        "vt_symbol": top["vt_symbol"],
                        "name": top["vt_symbol"],  # 占位, 下方批量回填
                        "streak": top["streak"],
                    }
                    if top
                    else None
                ),
            }
        )
        if top:
            top_rows.append((day, top))

    names = _load_names(
        session, sorted({row["vt_symbol"] for _, row in top_rows})
    )
    for day, top in top_rows:
        name = names.get(top["vt_symbol"], top["vt_symbol"])
        leaders.append(
            {
                "trade_date": day.isoformat(),
                "vt_symbol": top["vt_symbol"],
                "name": name,
                "streak": top["streak"],
                "is_one_word": top["is_one_word"],
            }
        )
    for entry in matrix:
        if entry["leader"] is not None:
            symbol = entry["leader"]["vt_symbol"]
            entry["leader"]["name"] = names.get(symbol, symbol)

    # 窗口晋级率: 与 promotion.by_streak 同口径(复用 helper, 尾日剔除在内);
    # 首板分日均值(第二返回值)是本端点不需要的副产品, 丢弃。
    promotion_matrix, _ = _by_streak(dates, streak_maps)

    return {
        "days": int(days),
        "as_of": dates[-1].isoformat() if dates else None,
        "dates": [day.isoformat() for day in dates],
        "matrix": matrix,
        "promotion_matrix": promotion_matrix,
        "leaders": leaders,
    }
