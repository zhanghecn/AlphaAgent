"""连板晋级率统计: lianban「明日晋级率≈XX% / 历史均值16.3%」的历史频率口径。

数据源 stock_limit_up_daily(A3 全历史重建产物, 只含涨停行与摸板行,
这里只取 is_limit_up=True); 交易日序列取 stock_daily_bars distinct
trade_date(≤ 当日, 降序 LIMIT 截断后反序 —— 只需窗口尾段, 避免全历史
物化; 2026-08-13 实测: 全量 distinct 升序 ~1.9s, 截断后 ms~百ms 级),
「次日」= 日历中的下一交易日(跨周末/假期自然正确)。

口径:
- 样本窗口: ≤ trade_date 的最近 lookback 个交易日(含当日)。
- by_streak(明日晋级率): 窗口内 streak==N 的个股, 次一交易日存在同一
  vt_symbol streak==N+1 涨停行的频率。N=1..7; streak>=8 合并为 "8+"
  一档(样本太少), 其晋级=次日 streak>=9。次日未涨停的个股在
  stock_limit_up_daily 无行 → 未晋级(仍计分母)。
  尾部剔除: 窗口最后一日的样本没有次日可判, 不进分母(计入会永远拉低
  频率); 即分母只含窗口前 len-1 个样本日。注意本模块不感知 rebuild
  缺口: 若某日历日整表无涨停行(未重建), 其前一日样本会对空表判 0,
  调用方应传已完成重建的交易日(B1 同款前置条件)。
- first_board_today(当日实际 1进2): base=前一交易日(日历中当日前一天)
  streak==1 家数, promoted=其中当日 streak==2 家数。当日无涨停行
  (未重建)或无前一日 → base=promoted=0, rate=None(与 B1 容错一致)。
- first_board_mean(历史均值): 窗口内有首板(base>0)的样本日的 1进2
  实际晋级率的分日均值 —— 对齐 lianban「历史均值16.3%」口径, 不是
  总样本比例; 首板为 0 的日子频率不可定义, 从均值剔除。
- relay_5d(五日接力矩阵): 日历最后 5 个交易日(含当日)每日各板位家数,
  streak>=6 合并 "6+"; 与 lookback 无关。
- ST: 全部口径默认排除(is_st 列), include_st=True 切换。
- 性能: 两次查询(日历 distinct + 窗口涨停行一次拉回), Python 聚合,
  无逐日循环查询。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema as db_schema

_STREAK_BUCKETS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
_STREAK_TOP = "8+"
_TOP_MIN = 8  # streak>=8 进合并档
_TOP_PROMOTED_MIN = 9  # 合并档晋级=次日 streak>=9
_RELAY_DAYS = 5
_RELAY_MERGE_MIN = 6  # relay 中 streak>=6 合并 "6+"


def _rate(promoted: int, samples: int) -> float | None:
    """频率保留 3 位小数(与 B1 today_promotion 一致); 无样本 → None 不除零。"""
    return round(promoted / samples, 3) if samples else None


def _load_calendar(session, trade_date: date, lookback: int) -> list[date]:
    """≤ 当日的交易日序列尾段(stock_daily_bars distinct, 升序)。

    只需要尾部 max(lookback+2, relay天数) 日(样本窗口 + 当日前一日 +
    relay_5d), 降序 LIMIT 截断再反序, 避免全历史 distinct 物化(实测
    全量 ~1.9s → 截断后 ms~百ms 级); 与全量取尾段语义完全等价。
    """
    table = db_schema.stock_daily_bars
    limit = max(int(lookback) + 2, _RELAY_DAYS)
    stmt = (
        select(table.c.trade_date)
        .where(table.c.trade_date <= trade_date)
        .distinct()
        .order_by(table.c.trade_date.desc())
        .limit(limit)
    )
    days = [row[0] for row in session.execute(stmt)]
    days.reverse()
    return days


def _load_streak_maps(
    session, start: date, end: date, include_st: bool
) -> dict[date, dict[str, int]]:
    """[start, end] 涨停行 → {trade_date: {vt_symbol: streak}}(按 include_st 过滤)。"""
    table = db_schema.stock_limit_up_daily
    stmt = select(
        table.c.trade_date,
        table.c.vt_symbol,
        table.c.limit_up_count,
        table.c.is_st,
    ).where(
        table.c.trade_date >= start,
        table.c.trade_date <= end,
        table.c.is_limit_up.is_(True),
    )
    by_date: dict[date, dict[str, int]] = {}
    for row in session.execute(stmt):
        if row.is_st and not include_st:
            continue
        by_date.setdefault(row.trade_date, {})[str(row.vt_symbol)] = int(
            row.limit_up_count
        )
    return by_date


def _empty_result(trade_date: date, lookback: int) -> dict[str, Any]:
    return {
        "trade_date": trade_date.isoformat(),
        "lookback_days": lookback,
        "sample_start": None,
        "sample_end": None,
        "by_streak": [
            {"streak": n, "samples": 0, "promoted": 0, "rate": None}
            for n in (*_STREAK_BUCKETS, _STREAK_TOP)
        ],
        "first_board_today": {"base": 0, "promoted": 0, "rate": None},
        "first_board_mean": None,
        "relay_5d": [],
    }


def _by_streak(
    window: list[date], by_date: dict[date, dict[str, int]]
) -> tuple[list[dict[str, Any]], list[float]]:
    """各板位历史晋级频率 + 逐日 1进2 频率序列(供分日均值)。

    分母日=窗口前 len-1 日(最后一日无次日可判, 尾部剔除)。
    """
    counts: dict[Any, list[int]] = {n: [0, 0] for n in _STREAK_BUCKETS}
    counts[_STREAK_TOP] = [0, 0]
    first_board_rates: list[float] = []

    for index, day in enumerate(window[:-1]):
        today_map = by_date.get(day, {})
        next_map = by_date.get(window[index + 1], {})
        day_base = 0
        day_promoted = 0
        for symbol, streak in today_map.items():
            next_streak = next_map.get(symbol)
            if streak >= _TOP_MIN:
                bucket = counts[_STREAK_TOP]
                promoted = next_streak is not None and next_streak >= _TOP_PROMOTED_MIN
            elif streak >= 1:
                bucket = counts[streak]
                promoted = next_streak == streak + 1
            else:
                continue  # 防御: 涨停行 streak 恒 >=1
            bucket[0] += 1
            if promoted:
                bucket[1] += 1
            if streak == 1:
                day_base += 1
                day_promoted += int(promoted)
        if day_base:
            first_board_rates.append(day_promoted / day_base)

    by_streak = [
        {
            "streak": key,
            "samples": counts[key][0],
            "promoted": counts[key][1],
            "rate": _rate(counts[key][1], counts[key][0]),
        }
        for key in (*_STREAK_BUCKETS, _STREAK_TOP)
    ]
    return by_streak, first_board_rates


def _first_board_today(
    calendar: list[date], trade_date: date, by_date: dict[date, dict[str, int]]
) -> dict[str, Any]:
    """当日实际 1进2; 当日无涨停行(未重建)或无前一日 → rate=None。"""
    today_map = by_date.get(trade_date, {})
    if not calendar or calendar[-1] != trade_date or len(calendar) < 2 or not today_map:
        return {"base": 0, "promoted": 0, "rate": None}
    prev_map = by_date.get(calendar[-2], {})
    base_set = {s for s, streak in prev_map.items() if streak == 1}
    promoted = sum(1 for s in base_set if today_map.get(s) == 2)
    return {
        "base": len(base_set),
        "promoted": promoted,
        "rate": _rate(promoted, len(base_set)),
    }


def _relay_5d(
    calendar: list[date], by_date: dict[date, dict[str, int]]
) -> list[dict[str, Any]]:
    """日历最后 5 个交易日各板位家数(streak>=6 合并 "6+")。"""
    relay = []
    for day in calendar[-_RELAY_DAYS:]:
        tiers = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 0}
        for streak in by_date.get(day, {}).values():
            if streak >= _RELAY_MERGE_MIN:
                tiers["6+"] += 1
            elif streak >= 1:
                tiers[str(streak)] += 1
        relay.append({"trade_date": day.isoformat(), "tiers": tiers})
    return relay


def promotion_stats(
    session, trade_date: date, *, lookback: int = 250, include_st: bool = False
) -> dict[str, Any]:
    """连板晋级率统计(返回结构见模块 docstring 与本函数下方组装)。"""
    calendar = _load_calendar(session, trade_date, lookback)
    window = calendar[-lookback:] if lookback > 0 else []
    if not window:
        return _empty_result(trade_date, lookback)

    # 一次查询覆盖: 样本窗口 + 当日前一日(lookback==1 时可能在窗口外)
    # + relay 首日(lookback<5 时可能在窗口外)。
    load_start = min(window[0], calendar[max(0, len(calendar) - _RELAY_DAYS)])
    if len(calendar) >= 2 and calendar[-1] == trade_date:
        load_start = min(load_start, calendar[-2])
    by_date = _load_streak_maps(session, load_start, trade_date, include_st)

    by_streak, first_board_rates = _by_streak(window, by_date)
    first_board_mean = (
        round(sum(first_board_rates) / len(first_board_rates), 3)
        if first_board_rates
        else None
    )

    return {
        "trade_date": trade_date.isoformat(),
        "lookback_days": lookback,
        "sample_start": window[0].isoformat(),
        "sample_end": window[-1].isoformat(),
        "by_streak": by_streak,
        "first_board_today": _first_board_today(calendar, trade_date, by_date),
        "first_board_mean": first_board_mean,
        "relay_5d": _relay_5d(calendar, by_date),
    }
