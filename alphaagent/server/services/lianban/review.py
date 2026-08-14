"""连板复盘页单页 payload 总装。

设计原则: 所有子块容错独立降级 —— 某块数据缺失 → 该块 null/空 +
data_quality.missing 标注, 不拖垮整页。live(盘中实时)分流判断在 API 层
(B4), 本服务默认只读落库数据; live 时由 API 层把实时五池映射成归档行
形状后经 pool_rows_override 注入, 走 final 同路径聚合。

mode:
- final: limit_up_pool_snapshots 当日 zt 池有行(盘后五池归档完成);
- rebuild: 归档无当日 zt 行但 stock_limit_up_daily 当日有行(历史旧日期,
  超出东财 ~3 周归档窗口, 由 A3 全历史重建覆盖);
- live: API 层(B4)盘中分流 —— 当日(中国时区)尚无 zt 归档时拉实时五池,
  经 archive.pool_row 映射成归档行形状后由 pool_rows_override 注入;
  聚合走 final 同路径(归档行口径), payload mode="live" 且
  data_quality.pool_archived=False / live=True。override 的 zt 为空 →
  ReviewNotFound(开盘前实时池尚无涨停, 同"当日无数据"语义)。
- 三者都无 → ReviewNotFound(API 层转 404), 常见于非交易日/数据未就绪。

口径(与 B1 ladder / B2 promotion 对齐):
- ST 过滤: 统计家数/梯队/题材/接力一律排除 ST(归档行无 is_st 列, 复用
  ladder._is_st_name 名称推导; 重建行用 is_st 列)。zt_previous(昨涨停今表现)
  按东财原名单不滤 ST(实证两口径结果一致, 且语义是"昨日涨停股整体表现")。
- 封板率 seal_rate = zt/(zt+zbgc), 任一侧缺失 → None。
- *_prev(前一交易日同口径): final 模式优先取归档前一 zt 日, 归档缺失回落
  重建表前一交易日; rebuild 模式只走重建表。都没有 → 全 None + missing
  "pool_prev"。
- 昨涨停今表现 prev_lu_*: 优先 zt_previous 池(归档在当日的昨日名单, 两种
  mode 通用), 缺失回落重建表前一交易日 is_limit_up 非ST名单; join 当日
  stock_daily_bars.change_pct(NULL 剔除) → 均值/中位(2 位)/翻红率(3 位)。
- 六指数: 上证/深证/创业板/科创50/上证50/北证50 当日日线涨跌幅。指数行的
  change_pct 列同步端不落库(实测 NULL), 缺失时按 当日close/前收close 回补
  计算(2 位); 上证50/北证50 尚未同步(INDEX_SYMBOLS 只落 7 个基准指数)
  → 该格 None + missing "indices:<key>", 键位始终齐全。
- new_high_63/new_low_63: 当日 close >= 该股此前 63 个交易日(不含当日,
  按 stock_daily_bars 交易日历取)最高 high 的家数; 新低对称。排除指数行;
  历史不足 63 日的按已有窗口计, 无任何历史 bar 的不进分母(内连接)。
- total_amount: 当日 stock_daily_bars turnover 求和, 排除全部已知指数行
  (INDEX_SYMBOLS 7 个 + 上证50/北证50 两个预留位)。
- 情绪: mainline_sentiment_history id=1 单行 points JSONB 中找当日 point,
  sentiment 块挂原文; stats.sentiment_phase = phase_label 补"期"字
  (point 里是"退潮"/"冰点", 复盘页口径是"退潮期"/"冰点期")。
- 接力 relay: 昨日各板位(重建表 prev 日 is_limit_up 非ST)个股今日表现。
  status: promoted=今日 streak>昨日(今日 streak 取重建表, 重建缺失回落
  归档 zt 的 limit_up_count); broken=今日在 zbgc 归档池(final)或重建行
  touched_limit 未封(rebuild); open=其他(断板未摸板等)。档内按今日涨幅
  降序(None 最后)。first_board 子块 = promotion.first_board_today +
  first_board_mean。
- themes 热点题材: 涨停股按主题材分组——优先概念(东财 concept memberships
  特异性分配, 见 theme_concepts.py, 对标 lianban 概念级题材如液冷/稀土
  永磁), 未入概念组的回落行业(final 用归档行 industry, rebuild 从 stocks
  表 industry 列补, 都无 → "其他"组); 组带 kind(concept|industry);
  leader=组内最高连板(同板位首封最早); 组内按首封时间升序(None 最后);
  组间按家数降序(同数按组名)。
- theme_strength 主线强度: sector_fund_flows 当日 period="即时"(实测列值
  为 即时/5日/10日, "今日"只在 raw 里)主力净额 Top8, change_pct 取
  raw["今日涨跌幅"]; sector_daily_metrics 目前空表, 不采用。
- hot_leaders 人气榜: stock_hot_ranks 取 rank_time 不晚于复盘日(as-of:
  rank_time < 次日日期串, 字典序比较 —— 实测格式为 ISO 截断 30 字符如
  "2026-08-13T06:30:17.195234+00:", 日期前缀完整零填充, 字典序即时间序)
  的最后一批 Top10, 避免把未来的榜塞进历史复盘页; join 当日连板 streak 与
  日线涨幅。块结构 {"as_of": 批次 rank_time | None, "items": [...]}。
  数据源(akshare stock_hot_rank_em)无人气分值, hot_score 恒 None
  (契约占位, 前端按 rank 渲染)。
- data_quality: pool_archived=是否 final; live=是否盘中实时分流;
  rebuild_date=重建表最大日期; missing=降级块清单(如 ["indices:sz50",
  "sentiment","margin"])。

异常隔离(总装韧性): mode 判定所需的两个基础查询(当日归档/重建行)不降级
—— 它们故障(如缺表 OperationalError)时 mode 无意义, 异常向上抛; 其余
所有子块(含核心的 ladder/promotion)经 _guarded 独立降级: 异常 → log +
该块 None/空 + missing 加 "<block>:error", 整页仍可渲染。

性能: 除 ladder/promotion(各自 <100ms 已验证)外均为单日小查询; 唯一的
大查询是 63 日新高新低(63 日 × 全市场 GROUP BY + 当日内连接, 走
ix_stock_daily_bars_date_symbol; 2026-08-13 复盘实测 ~1.8s, heap-fetch
瓶颈, 生产硬件显著更快)。情绪 points 整行取回 Python 侧找当日(几百日 ×
小 dict, 量级可忽略)。历史日期的 payload 不可变 → B4 进程内缓存兜底
整页 P95<100ms(重复访问走缓存, 首次计算承担一次性成本)。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from statistics import median
from typing import Any

from sqlalchemy import case, func, select

from alphaagent.market.symbols import INDEX_SYMBOLS
from alphaagent.server.db import schema as db_schema
from alphaagent.server.services.lianban.ladder import (
    _is_reverse,
    _is_st_name,
    build_ladder,
)
from alphaagent.server.services.lianban.margin import latest_margin_balance
from alphaagent.server.services.lianban.promotion import promotion_stats
from alphaagent.server.services.lianban.theme_concepts import assign_theme_concepts

__all__ = ["ReviewNotFound", "build_review"]

logger = logging.getLogger(__name__)


class ReviewNotFound(Exception):
    """当日既无涨停池归档也无日线重建(非交易日/数据未就绪)。"""


_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 复盘页页头六指数(键位定稿, 前端按 key 渲染; 缺数据的格 None 容错)。
_INDEX_SPECS: tuple[tuple[str, str, str], ...] = (
    ("sh", "上证", "000001.SSE"),
    ("sz", "深证", "399001.SZSE"),
    ("cyb", "创业板", "399006.SZSE"),
    ("kc50", "科创50", "000688.SSE"),
    ("sz50", "上证50", "000016.SSE"),
    ("bz50", "北证50", "899050.BSE"),
)

# 成交额/新高新低统计要排除的全部指数行: 已落库的 7 个基准指数 + 两个预留位。
_ALL_INDEX_VT_SYMBOLS: tuple[str, ...] = tuple(
    sorted(
        {f"{item['symbol']}.{item['exchange']}" for item in INDEX_SYMBOLS}
        | {spec[2] for spec in _INDEX_SPECS}
    )
)

_NEW_HIGH_LOW_DAYS = 63
_THEME_STRENGTH_LIMIT = 8
_HOT_LEADERS_LIMIT = 10
_FUND_FLOW_PERIOD = "即时"  # sector_fund_flows.period 实测值(今日/5日/10日中的当日档)
_OTHER_INDUSTRY = "其他"

_EMPTY_POOL_STATS: dict[str, Any] = {
    "limit_up": None,
    "broken": None,
    "limit_down": None,
    "lianban": None,
    "max_streak": None,
}


def _empty_first_board() -> dict[str, Any]:
    return {"base": 0, "promoted": 0, "rate": None, "mean": None}


def _empty_relay() -> dict[str, Any]:
    return {"tiers": [], "first_board": _empty_first_board()}


def _empty_hot_leaders() -> dict[str, Any]:
    return {"as_of": None, "items": []}


def _guarded(missing: list[str], block: str, fn: Any, fallback: Any) -> Any:
    """子块异常隔离: 记日志 + missing 标 "<block>:error" + 返回空形, 不拖垮整页。"""
    try:
        return fn()
    except Exception as exc:
        logger.warning("review block %s failed: %s", block, exc, exc_info=True)
        missing.append(f"{block}:error")
        return fallback


# ── 基础加载 ─────────────────────────────────────────────────────────────


def _load_pools(session, trade_date: date) -> dict[str, list[dict]]:
    """当日五池归档行 → {pool_type: [row]}; 一次查询。"""
    table = db_schema.limit_up_pool_snapshots
    stmt = select(table).where(table.c.trade_date == trade_date)
    pools: dict[str, list[dict]] = {}
    for row in session.execute(stmt).mappings():
        pools.setdefault(str(row["pool_type"]), []).append(dict(row))
    return pools


def _load_daily_rows(session, trade_date: date) -> list[dict]:
    """当日 stock_limit_up_daily 全部行(涨停 + 摸板)。"""
    table = db_schema.stock_limit_up_daily
    stmt = select(table).where(table.c.trade_date == trade_date)
    return [dict(row) for row in session.execute(stmt).mappings()]


def _prev_archive_date(session, trade_date: date) -> date | None:
    """归档中 < 当日的最近 zt 池日期。"""
    table = db_schema.limit_up_pool_snapshots
    return session.execute(
        select(func.max(table.c.trade_date)).where(
            table.c.trade_date < trade_date,
            table.c.pool_type == "zt",
        )
    ).scalar()


def _prev_daily_date(session, trade_date: date) -> date | None:
    """重建表中 < 当日的最近日期。"""
    table = db_schema.stock_limit_up_daily
    return session.execute(
        select(func.max(table.c.trade_date)).where(
            table.c.trade_date < trade_date
        )
    ).scalar()


def _load_names(session, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    table = db_schema.stocks
    stmt = select(table.c.vt_symbol, table.c.name).where(
        table.c.vt_symbol.in_(symbols)
    )
    return {str(r.vt_symbol): str(r.name) for r in session.execute(stmt) if r.name}


def _load_industries(session, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    table = db_schema.stocks
    stmt = select(table.c.vt_symbol, table.c.industry).where(
        table.c.vt_symbol.in_(symbols)
    )
    return {
        str(r.vt_symbol): str(r.industry)
        for r in session.execute(stmt)
        if r.industry
    }


def _load_change_map(session, trade_date: date, symbols: list[str]) -> dict[str, float]:
    """当日日线 change_pct 映射(无当日 bar 或 NULL → 不在映射里)。"""
    if not symbols:
        return {}
    table = db_schema.stock_daily_bars
    stmt = select(table.c.vt_symbol, table.c.change_pct).where(
        table.c.trade_date == trade_date,
        table.c.vt_symbol.in_(symbols),
        table.c.change_pct.isnot(None),
    )
    return {str(r.vt_symbol): float(r.change_pct) for r in session.execute(stmt)}


# ── stats 各口径 ─────────────────────────────────────────────────────────


def _archive_pool_stats(pools: dict[str, list[dict]]) -> dict[str, Any]:
    """final 口径: zt/zbgc/dtgc 家数 + 连板家数 + 最高板(非ST)。"""
    zt = [r for r in pools.get("zt", []) if not _is_st_name(r.get("name"))]
    zbgc = [r for r in pools.get("zbgc", []) if not _is_st_name(r.get("name"))]
    dtgc = [r for r in pools.get("dtgc", []) if not _is_st_name(r.get("name"))]
    streaks = [
        int(r["limit_up_count"]) for r in zt if r.get("limit_up_count") is not None
    ]
    return {
        "limit_up": len(zt),
        "broken": len(zbgc),
        "limit_down": len(dtgc),
        "lianban": sum(1 for streak in streaks if streak >= 2),
        "max_streak": max(streaks) if streaks else None,
    }


def _rebuild_pool_stats(daily_rows: list[dict]) -> dict[str, Any]:
    """rebuild 口径: 重建表 is_limit_up 非ST家数; 炸板/跌停无数据源 → None。"""
    ups = [r for r in daily_rows if r["is_limit_up"] and not r.get("is_st")]
    streaks = [int(r["limit_up_count"]) for r in ups]
    return {
        "limit_up": len(ups),
        "broken": None,
        "limit_down": None,
        "lianban": sum(1 for streak in streaks if streak >= 2),
        "max_streak": max(streaks) if streaks else None,
    }


def _seal_rate(stats: dict[str, Any]) -> float | None:
    """zt/(zt+zbgc); 任一侧缺失或全零 → None。"""
    limit_up = stats["limit_up"]
    broken = stats["broken"]
    if limit_up is None or broken is None or limit_up + broken == 0:
        return None
    return round(limit_up / (limit_up + broken), 3)


def _prev_lu_performance(
    session,
    trade_date: date,
    zt_previous_rows: list[dict],
    prev_daily: date | None,
) -> tuple[float | None, float | None, float | None]:
    """昨涨停今表现(均值/中位/翻红率); 名单缺失或全无当日涨幅 → 全 None。"""
    symbols: list[str]
    if zt_previous_rows:
        # 东财昨日涨停池原名单(不滤 ST, 语义=昨日涨停股整体表现)。
        symbols = [str(r["vt_symbol"]) for r in zt_previous_rows]
    elif prev_daily is not None:
        rows = _load_daily_rows(session, prev_daily)
        symbols = [
            str(r["vt_symbol"])
            for r in rows
            if r["is_limit_up"] and not r.get("is_st")
        ]
    else:
        return None, None, None
    changes = list(_load_change_map(session, trade_date, symbols).values())
    if not changes:
        return None, None, None
    rise = sum(1 for change in changes if change > 0)
    return (
        round(sum(changes) / len(changes), 2),
        round(median(changes), 2),
        round(rise / len(changes), 3),
    )


def _sentiment_point(session, trade_date: date) -> dict[str, Any] | None:
    """mainline_sentiment_history id=1 的 points 里找当日 point(原文)。"""
    table = db_schema.mainline_sentiment_history
    points = session.execute(
        select(table.c.points).where(table.c.id == 1)
    ).scalar()
    if not points:
        return None
    iso = trade_date.isoformat()
    for point in points:
        if isinstance(point, dict) and point.get("date") == iso:
            return point
    return None


def _sentiment_phase(point: dict[str, Any] | None) -> str | None:
    """phase_label 补"期"字对齐复盘页口径(退潮→退潮期); 已带期则原样。"""
    if not point:
        return None
    label = point.get("phase_label")
    if not label:
        return None
    text = str(label)
    return text if text.endswith("期") else f"{text}期"


def _indices(session, trade_date: date) -> tuple[list[dict], list[str]]:
    """六指数当日 change_pct; 返回 (indices, 缺失的 key 清单)。

    指数行的 change_pct 列在同步端不落库(实测为 NULL), 列缺失时用当日
    close / 前一交易日 close 回补计算(2 位)。当日无 bar → None + missing。
    每指数一条 limit 2 的索引小查询(PK vt_symbol+trade_date)。
    """
    bars = db_schema.stock_daily_bars
    indices = []
    missing = []
    for key, name, vt_symbol in _INDEX_SPECS:
        rows = session.execute(
            select(bars.c.trade_date, bars.c.close_price, bars.c.change_pct)
            .where(
                bars.c.vt_symbol == vt_symbol,
                bars.c.trade_date <= trade_date,
            )
            .order_by(bars.c.trade_date.desc())
            .limit(2)
        ).all()
        change_pct = None
        if rows and rows[0].trade_date == trade_date:
            change_pct = rows[0].change_pct
            if (
                change_pct is None
                and len(rows) > 1
                and rows[0].close_price is not None
                and rows[1].close_price
            ):
                change_pct = round(
                    (rows[0].close_price / rows[1].close_price - 1) * 100, 2
                )
        if change_pct is None:
            missing.append(f"indices:{key}")
        indices.append(
            {
                "key": key,
                "name": name,
                "vt_symbol": vt_symbol,
                "change_pct": change_pct,
            }
        )
    return indices, missing


def _new_high_low(session, trade_date: date) -> tuple[int | None, int | None]:
    """63 日新高/新低家数(close vs 此前 63 交易日最高 high/最低 low)。

    两条索引友好查询: 交易日历( distinct desc limit 63) + 窗口内
    GROUP BY 极值与当日行的内连接条件计数。无任何历史 → (None, None)。
    """
    bars = db_schema.stock_daily_bars
    days = (
        session.execute(
            select(bars.c.trade_date)
            .where(bars.c.trade_date < trade_date)
            .distinct()
            .order_by(bars.c.trade_date.desc())
            .limit(_NEW_HIGH_LOW_DAYS)
        )
        .scalars()
        .all()
    )
    if not days:
        return None, None
    hist = (
        select(
            bars.c.vt_symbol.label("vt_symbol"),
            func.max(bars.c.high_price).label("max_high"),
            func.min(bars.c.low_price).label("min_low"),
        )
        .where(bars.c.trade_date.in_(days))
        .group_by(bars.c.vt_symbol)
        .subquery()
    )
    today = (
        select(
            bars.c.vt_symbol.label("vt_symbol"),
            bars.c.close_price.label("close_price"),
        )
        .where(
            bars.c.trade_date == trade_date,
            bars.c.vt_symbol.notin_(_ALL_INDEX_VT_SYMBOLS),
        )
        .subquery()
    )
    stmt = select(
        func.coalesce(
            func.sum(case((today.c.close_price >= hist.c.max_high, 1), else_=0)), 0
        ),
        func.coalesce(
            func.sum(case((today.c.close_price <= hist.c.min_low, 1), else_=0)), 0
        ),
    ).select_from(today.join(hist, hist.c.vt_symbol == today.c.vt_symbol))
    high_count, low_count = session.execute(stmt).one()
    return int(high_count), int(low_count)


def _total_amount(session, trade_date: date) -> float | None:
    """两市成交额: 当日全部股票 turnover 求和(排除指数行)。"""
    bars = db_schema.stock_daily_bars
    value = session.execute(
        select(func.sum(bars.c.turnover)).where(
            bars.c.trade_date == trade_date,
            bars.c.vt_symbol.notin_(_ALL_INDEX_VT_SYMBOLS),
        )
    ).scalar()
    return float(value) if value is not None else None


# ── relay 梯队接力 ───────────────────────────────────────────────────────


def _today_streak_map(
    daily_rows: list[dict], pools: dict[str, list[dict]]
) -> dict[str, int]:
    """当日 {vt_symbol: streak}: 重建表优先, 未重建回落归档 zt 的 limit_up_count。"""
    result = {
        str(r["vt_symbol"]): int(r["limit_up_count"])
        for r in daily_rows
        if r["is_limit_up"]
    }
    if result:
        return result
    return {
        str(r["vt_symbol"]): int(r["limit_up_count"])
        for r in pools.get("zt", [])
        if r.get("limit_up_count") is not None
    }


def _relay_sort(stock: dict) -> tuple:
    """档内: 今日涨幅降序, None 最后, 同则 vt_symbol。"""
    change = stock["today_change_pct"]
    return (change is None, -(change or 0.0), stock["vt_symbol"])


def _build_relay(
    session,
    trade_date: date,
    mode: str,
    daily_rows: list[dict],
    pools: dict[str, list[dict]],
    prev_daily: date | None,
    promotion: dict[str, Any] | None,
) -> dict[str, Any]:
    """昨日各板位个股今日表现 + 首板晋级子块(promotion 降级为 None 时
    first_board 给空形, 梯队 tiers 不受影响)。"""
    today_streak = _today_streak_map(daily_rows, pools)
    if mode == "final":
        broken_symbols = {str(r["vt_symbol"]) for r in pools.get("zbgc", [])}
    else:
        broken_symbols = {
            str(r["vt_symbol"])
            for r in daily_rows
            if r.get("touched_limit") and not r["is_limit_up"]
        }

    tiers = []
    if prev_daily is not None:
        prev_rows = [
            r
            for r in _load_daily_rows(session, prev_daily)
            if r["is_limit_up"] and not r.get("is_st")
        ]
        symbols = [str(r["vt_symbol"]) for r in prev_rows]
        changes = _load_change_map(session, trade_date, symbols)
        names = _load_names(session, symbols)
        by_streak: dict[int, list[dict]] = {}
        for row in prev_rows:
            symbol = str(row["vt_symbol"])
            prev_streak = int(row["limit_up_count"])
            streak = today_streak.get(symbol)
            if streak is not None and streak > prev_streak:
                status = "promoted"
            elif symbol in broken_symbols:
                status = "broken"
            else:
                status = "open"
            by_streak.setdefault(prev_streak, []).append(
                {
                    "vt_symbol": symbol,
                    "name": names.get(symbol, symbol),
                    "today_change_pct": changes.get(symbol),
                    "status": status,
                    "today_streak": streak,
                }
            )
        for prev_streak in sorted(by_streak, reverse=True):
            tiers.append(
                {
                    "prev_streak": prev_streak,
                    "stocks": sorted(by_streak[prev_streak], key=_relay_sort),
                }
            )

    if promotion is None:
        first_board = _empty_first_board()
    else:
        first = promotion["first_board_today"]
        first_board = {
            "base": first["base"],
            "promoted": first["promoted"],
            "rate": first["rate"],
            "mean": promotion["first_board_mean"],
        }
    return {"tiers": tiers, "first_board": first_board}


# ── 炸板/题材/主线强度/人气榜 ────────────────────────────────────────────


def _first_time_sort(stock: dict) -> tuple:
    """首封时间升序, None 最后, 同则 vt_symbol(与 B1 档内排序一致)。"""
    first = stock["first_limit_time"]
    return (first is None, first or "", stock["vt_symbol"])


def _broken_list(pools: dict[str, list[dict]]) -> list[dict]:
    """zbgc 归档行按首封时间升序(final 模式限定)。"""
    rows = [
        {
            "vt_symbol": str(r["vt_symbol"]),
            "name": str(r.get("name") or r["vt_symbol"]),
            "first_limit_time": r.get("first_limit_time"),
            "break_count": r.get("break_count"),
            "industry": r.get("industry"),
        }
        for r in pools.get("zbgc", [])
    ]
    return sorted(rows, key=_first_time_sort)


def _themes(
    session, mode: str, pools: dict[str, list[dict]], daily_rows: list[dict],
    trade_date: date | None = None,
) -> list[dict]:
    """涨停股按行业分组: count/leader(最高板, 同板首封最早)/成员(首封升序)。"""
    entries = []
    if mode == "final":
        for row in pools.get("zt", []):
            name = str(row.get("name") or "").strip()
            if _is_st_name(name):
                continue
            symbol = str(row["vt_symbol"])
            count = row.get("limit_up_count")
            entries.append(
                {
                    "vt_symbol": symbol,
                    "name": name or symbol,
                    "limit_up_count": int(count) if count is not None else 1,
                    "first_limit_time": row.get("first_limit_time"),
                    "is_reverse": _is_reverse(
                        row.get("limit_stat_days"),
                        row.get("limit_stat_boards"),
                        count,
                    ),
                    "industry": row.get("industry"),
                }
            )
    else:
        ups = [r for r in daily_rows if r["is_limit_up"] and not r.get("is_st")]
        symbols = [str(r["vt_symbol"]) for r in ups]
        names = _load_names(session, symbols)
        industries = _load_industries(session, symbols)
        for row in ups:
            symbol = str(row["vt_symbol"])
            entries.append(
                {
                    "vt_symbol": symbol,
                    "name": names.get(symbol, symbol),
                    "limit_up_count": int(row["limit_up_count"]),
                    "first_limit_time": None,
                    "is_reverse": None,
                    "industry": industries.get(symbol),
                }
            )

    groups: dict[str, list[dict]] = {}
    kinds: dict[str, str] = {}
    from alphaagent.server.services.lianban.news_driver import news_concepts_for_date

    concept_names = assign_theme_concepts(
        session,
        [e["vt_symbol"] for e in entries],
        news_concepts=news_concepts_for_date(session, trade_date),
    )
    for entry in entries:
        concept = concept_names.get(entry["vt_symbol"])
        industry = str(entry.pop("industry") or _OTHER_INDUSTRY)
        key = concept or industry
        if key not in kinds:
            kinds[key] = "concept" if concept else "industry"
        groups.setdefault(key, []).append(entry)

    themes = []
    for group_name, stocks in groups.items():
        ordered = sorted(stocks, key=_first_time_sort)
        leader = min(
            ordered,
            key=lambda s: (
                -s["limit_up_count"],
                s["first_limit_time"] is None,
                s["first_limit_time"] or "",
                s["vt_symbol"],
            ),
        )
        themes.append(
            {
                "name": group_name,
                "kind": kinds[group_name],
                "count": len(ordered),
                "leader": {
                    "vt_symbol": leader["vt_symbol"],
                    "name": leader["name"],
                    "limit_up_count": leader["limit_up_count"],
                },
                "stocks": ordered,
            }
        )
    return sorted(themes, key=lambda t: (-t["count"], t["name"]))


def _theme_strength(session, trade_date: date) -> list[dict]:
    """主线强度: 板块资金流当日"即时"档主力净额 Top8(涨幅取 raw 今日涨跌幅)。"""
    flows = db_schema.sector_fund_flows
    sectors = db_schema.sectors
    stmt = (
        select(
            sectors.c.name,
            flows.c.main_net_inflow,
            flows.c.raw,
        )
        .select_from(flows.join(sectors, flows.c.sector_id == sectors.c.id))
        .where(
            flows.c.trade_date == trade_date.isoformat(),
            flows.c.period == _FUND_FLOW_PERIOD,
        )
    )
    rows = []
    for row in session.execute(stmt).mappings():
        change_pct = None
        raw = row.get("raw")
        if isinstance(raw, dict):
            try:
                value = raw.get("今日涨跌幅")
                change_pct = float(value) if value is not None else None
            except (TypeError, ValueError):
                change_pct = None
        rows.append(
            {
                "name": str(row["name"]),
                "change_pct": change_pct,
                "main_net_inflow": row.get("main_net_inflow"),
            }
        )
    rows.sort(
        key=lambda r: (
            r["main_net_inflow"] is None,
            -(r["main_net_inflow"] or 0.0),
            r["name"],
        )
    )
    return rows[:_THEME_STRENGTH_LIMIT]


def _hot_leaders(
    session, trade_date: date, today_streak: dict[str, int]
) -> dict[str, Any]:
    """人气榜 as-of 复盘日的最后一批 Top10 join 当日连板/涨幅。

    as-of: rank_time < 次日日期串(字典序; 实测 rank_time 为 ISO 截断 30
    字符, 日期前缀完整零填充, 字典序即时间序), 防止把晚于复盘日的批次
    塞进历史复盘页(时间穿越)。返回 {"as_of": 批次 rank_time | None,
    "items": [...]}; 源无人气分值 → hot_score None。
    """
    table = db_schema.stock_hot_ranks
    cutoff = (trade_date + timedelta(days=1)).isoformat()
    latest = session.execute(
        select(func.max(table.c.rank_time)).where(table.c.rank_time < cutoff)
    ).scalar()
    if latest is None:
        return _empty_hot_leaders()
    stmt = select(table.c.vt_symbol, table.c.rank, table.c.keywords).where(
        table.c.rank_time == latest
    )
    rows = [dict(row) for row in session.execute(stmt).mappings()]
    rows.sort(
        key=lambda r: (r.get("rank") is None, r.get("rank") or 0, str(r["vt_symbol"]))
    )
    rows = rows[:_HOT_LEADERS_LIMIT]
    symbols = [str(r["vt_symbol"]) for r in rows]
    names = _load_names(session, symbols)
    changes = _load_change_map(session, trade_date, symbols)
    items = [
        {
            "rank": row.get("rank"),
            "vt_symbol": str(row["vt_symbol"]),
            "name": names.get(str(row["vt_symbol"]), str(row["vt_symbol"])),
            "hot_score": None,  # akshare stock_hot_rank_em 无人气分值, 契约占位
            "limit_up_count": today_streak.get(str(row["vt_symbol"])),
            "change_pct": changes.get(str(row["vt_symbol"])),
            "keywords": list(row.get("keywords") or []),
        }
        for row in rows
    ]
    return {"as_of": latest, "items": items}


# ── 总装 ─────────────────────────────────────────────────────────────────


def build_review(
    session,
    trade_date: date,
    *,
    pool_rows_override: dict[str, list[dict]] | None = None,
    mode_override: str | None = None,
) -> dict[str, Any]:
    """复盘页单页全量 payload(结构见模块 docstring 与任务契约)。

    pool_rows_override: live 模式注入的"归档行形状"五池(archive.pool_row
    映射结果)。提供时 _load_pools 不查表, 聚合走 final 同路径, mode 报
    "live"(或 mode_override 指定值); 其余子块(情绪/资金流/热榜/融资等)
    照常从库读, live 当日它们是盘中累积数据, 由 data_quality.live 诚实标注。
    live 特化处理:
    - ladder 直接吃 override 的 zt 行(当日归档未落库, 查表必空);
    - promotion 锚定最近重建日(当日重建未跑, 避免"当日有盘中日线但无重建"
      把窗口尾日算成全员 0 晋级的污染样本), payload 内 trade_date 即 as-of。

    Raises:
        ReviewNotFound: 当日既无涨停池归档(zt)也无日线重建行; 或 override
            的 zt 池为空(开盘前实时池尚无涨停)。
        其他异常: mode 判定基础查询(归档/重建表读取)故障时向上抛。
    """
    # mode 判定基础查询不降级: 它们故障时整页无意义(见模块 docstring)。
    if pool_rows_override is not None:
        pools = pool_rows_override
        daily_rows = _load_daily_rows(session, trade_date)
        if not pools.get("zt"):
            raise ReviewNotFound(
                f"复盘数据不存在: {trade_date.isoformat()}(实时涨停池为空)"
            )
        mode = mode_override or "live"
    else:
        pools = _load_pools(session, trade_date)
        daily_rows = _load_daily_rows(session, trade_date)
        if pools.get("zt"):
            mode = "final"
        elif daily_rows:
            mode = "rebuild"
        else:
            raise ReviewNotFound(
                f"复盘数据不存在: {trade_date.isoformat()}(无涨停池归档且无日线重建)"
            )
    # 聚合口径: live(含 mode_override 自定义标识)与 final 同走归档行路径,
    # 仅 rebuild 走重建表口径。
    agg = "rebuild" if mode == "rebuild" else "final"

    missing: list[str] = []

    indices, missing_indices = _guarded(
        missing,
        "indices",
        lambda: _indices(session, trade_date),
        (
            [
                {"key": key, "name": name, "vt_symbol": vt, "change_pct": None}
                for key, name, vt in _INDEX_SPECS
            ],
            [],
        ),
    )
    missing.extend(missing_indices)

    if agg == "final":
        current = _archive_pool_stats(pools)
    else:
        current = _rebuild_pool_stats(daily_rows)

    # 前一交易日同口径: final/live 优先归档, 回落重建; rebuild 只走重建。
    prev_daily = _prev_daily_date(session, trade_date)
    prev = dict(_EMPTY_POOL_STATS)
    prev_found = False
    if agg == "final":
        prev_archive = _guarded(
            missing, "pool_prev", lambda: _prev_archive_date(session, trade_date), None
        )
        if prev_archive is not None:
            prev = _archive_pool_stats(_load_pools(session, prev_archive))
            prev_found = True
    if not prev_found and prev_daily is not None:
        prev = _rebuild_pool_stats(_load_daily_rows(session, prev_daily))
        prev_found = True
    if not prev_found and f"pool_prev:error" not in missing:
        missing.append("pool_prev")

    prev_lu_avg, prev_lu_median, prev_lu_ratio = _guarded(
        missing,
        "prev_lu",
        lambda: _prev_lu_performance(
            session, trade_date, pools.get("zt_previous", []), prev_daily
        ),
        (None, None, None),
    )
    if prev_lu_avg is None and "prev_lu:error" not in missing:
        missing.append("prev_lu")

    point = _guarded(
        missing, "sentiment", lambda: _sentiment_point(session, trade_date), None
    )
    if point is None and "sentiment:error" not in missing:
        missing.append("sentiment")

    margin = _guarded(missing, "margin", lambda: latest_margin_balance(session), None)
    if margin is None and "margin:error" not in missing:
        missing.append("margin")

    new_high, new_low = _guarded(
        missing, "new_high_low", lambda: _new_high_low(session, trade_date), (None, None)
    )
    ladder = _guarded(
        missing,
        "ladder",
        lambda: build_ladder(
            session,
            trade_date,
            pool_rows_override=(
                pools.get("zt") if pool_rows_override is not None else None
            ),
        ),
        None,
    )
    # 重建表最大日期(数据质量块复用)。live 模式当日重建未跑, promotion 锚定
    # 最近重建日(诚实 as-of), 避免当日盘中日线已部分落库时窗口尾日污染统计。
    rebuild_date = session.execute(
        select(func.max(db_schema.stock_limit_up_daily.c.trade_date))
    ).scalar()
    promotion_date = trade_date
    if (
        pool_rows_override is not None
        and rebuild_date is not None
        and rebuild_date < trade_date
    ):
        promotion_date = rebuild_date
    promotion = _guarded(
        missing, "promotion", lambda: promotion_stats(session, promotion_date), None
    )
    relay = _guarded(
        missing,
        "relay",
        lambda: _build_relay(
            session, trade_date, agg, daily_rows, pools, prev_daily, promotion
        ),
        _empty_relay(),
    )

    if agg == "final":
        broken_list = _guarded(
            missing, "broken_list", lambda: _broken_list(pools), []
        )
    else:
        broken_list = []
        missing.append("broken_list")

    theme_strength = _guarded(
        missing, "theme_strength", lambda: _theme_strength(session, trade_date), []
    )
    if not theme_strength and "theme_strength:error" not in missing:
        missing.append("theme_strength")

    today_streak = _today_streak_map(daily_rows, pools)
    hot_leaders = _guarded(
        missing,
        "hot_leaders",
        lambda: _hot_leaders(session, trade_date, today_streak),
        _empty_hot_leaders(),
    )
    if not hot_leaders["items"] and "hot_leaders:error" not in missing:
        missing.append("hot_leaders")

    stats = {
        "limit_up": current["limit_up"],
        "limit_up_prev": prev["limit_up"],
        "lianban": current["lianban"],
        "lianban_prev": prev["lianban"],
        "max_streak": current["max_streak"],
        "max_streak_prev": prev["max_streak"],
        "limit_down": current["limit_down"],
        "limit_down_prev": prev["limit_down"],
        "seal_rate": _seal_rate(current),
        "seal_rate_prev": _seal_rate(prev),
        "broken": current["broken"],
        "broken_prev": prev["broken"],
        "prev_lu_avg_change": prev_lu_avg,
        "prev_lu_median_change": prev_lu_median,
        "prev_lu_rise_ratio": prev_lu_ratio,
        "sentiment_phase": _sentiment_phase(point),
        "sentiment_score": point.get("score") if point else None,
        "rise_count": point.get("rise_count") if point else None,
        "fall_count": point.get("fall_count") if point else None,
        "new_high_63": new_high,
        "new_low_63": new_low,
        "total_amount": _guarded(
            missing, "total_amount", lambda: _total_amount(session, trade_date), None
        ),
        "margin_balance": margin.get("margin_balance") if margin else None,
        "margin_change": margin.get("change") if margin else None,
        "margin_date": margin.get("trade_date") if margin else None,
    }

    return {
        "trade_date": trade_date.isoformat(),
        "mode": mode,
        "weekday": _WEEKDAYS[trade_date.weekday()],
        "indices": indices,
        "stats": stats,
        "sentiment": point,
        "ladder": ladder,
        "promotion": promotion,
        "relay": relay,
        "broken_list": broken_list,
        "themes": _guarded(
            missing,
            "themes",
            lambda: _themes(session, agg, pools, daily_rows, trade_date),
            [],
        ),
        "theme_strength": theme_strength,
        "hot_leaders": hot_leaders,
        "data_quality": {
            "pool_archived": mode == "final",
            "live": mode == "live",
            "rebuild_date": rebuild_date.isoformat() if rebuild_date else None,
            "missing": missing,
        },
    }
