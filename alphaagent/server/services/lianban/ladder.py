"""连板天梯梯队构建: 当日涨停股按连板数降序分档。

数据源双模式(口径与 lianban 天梯页对齐):
- pool_archive: limit_up_pool_snapshots 当日 pool_type="zt" 有行 → 梯队与
  盘口字段(首封/末封时间、封单额、炸板次数、涨停统计)全从归档行取;
  归档表无 is_st 列, ST 由名称推导(与 detector 同口径 "ST" in name.upper())。
- daily_rebuild: 归档无当日行(历史日期超出东财 ~3 周窗口)→ 降级从
  stock_limit_up_daily(is_limit_up=True) 取梯队, 盘口字段一律 None, 但仍提供
  limit_up_count/close_price/change_pct/is_one_word/is_st/board;
  name 取 stocks 表快照。

口径:
- ST 过滤: 两模式默认排除 ST(include_st=True 关闭), 对齐东财/lianban 口径。
- is_reverse(「反」徽标): limit_stat_boards > limit_up_count → True
  (实证: 一鸣食品 13/9 连板4 → 反; 秦安 5/5 连板5 → 不标); 统计缺失
  (含 daily_rebuild 模式)→ None(前端不显示)。
- today_promotion(今日 X进Y 实际晋级率): 一律由 stock_limit_up_daily 计算
  (它有全历史; 与 pool_archive 的口径一致性由 A6 对账保障)。streak=N(N>=2)档:
  base=前一交易日 streak==N-1 的非ST家数, promoted=其中今日 streak==N 的家数;
  1板档即 1进2: base=昨日首板数, promoted=其中今日2板数(与2板档数值相同)。
  前一交易日 = stock_limit_up_daily 中 < trade_date 的最大 trade_date;
  当日未重建或前一日缺失 → today_promotion=None 容错。
- concepts: 每股最多 3 个概念名, join stock_sector_memberships→sectors
  (type='concept'), 一次批量查询。sectors 无权重/热度列, 按概念名
  sorted() 取前 3(Python 侧排序, 跨数据库确定性, 不依赖 DB collation)。
- 排序: 档内 first_limit_time 升序(None 最后, 同则 vt_symbol); 档位 streak
  降序; 空档不输出。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema as db_schema

MAX_CONCEPTS_PER_STOCK = 3

_POOL_TYPE_ZT = "zt"


def _is_st_name(name: str | None) -> bool:
    """归档行无 is_st 列, 按名称推导(与 detector 同口径)。"""
    return "ST" in (name or "").upper()


def _is_reverse(
    stat_days: int | None, stat_boards: int | None, count: int | None
) -> bool | None:
    """反包徽标: 统计板数 > 当前连板数; 任一缺失 → None(前端不显示)。"""
    if stat_days is None or stat_boards is None or count is None:
        return None
    return stat_boards > count


def _load_pool_rows(session, trade_date: date) -> list[dict]:
    table = db_schema.limit_up_pool_snapshots
    stmt = select(table).where(
        table.c.trade_date == trade_date,
        table.c.pool_type == _POOL_TYPE_ZT,
    )
    return [dict(row) for row in session.execute(stmt).mappings()]


def _stocks_from_pool(rows: list[dict], include_st: bool) -> list[dict]:
    """pool_archive 模式个股 payload: 全字段从归档行取。

    limit_up_count 缺失容错为 1(zt 池内股票至少是首板); is_reverse 的
    count 用原始值(None → None)。
    """
    stocks = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        is_st = _is_st_name(name)
        if is_st and not include_st:
            continue
        vt_symbol = str(row["vt_symbol"])
        count = row.get("limit_up_count")
        stocks.append(
            {
                "vt_symbol": vt_symbol,
                "name": name or vt_symbol,
                "limit_up_count": int(count) if count is not None else 1,
                "first_limit_time": row.get("first_limit_time"),
                "last_limit_time": row.get("last_limit_time"),
                "limit_amount": row.get("limit_amount"),
                "break_count": row.get("break_count"),
                "limit_stat_days": row.get("limit_stat_days"),
                "limit_stat_boards": row.get("limit_stat_boards"),
                "is_reverse": _is_reverse(
                    row.get("limit_stat_days"), row.get("limit_stat_boards"), count
                ),
                "industry": row.get("industry"),
                "close_price": row.get("close_price"),
                "change_pct": row.get("change_pct"),
                "is_one_word": None,
                "is_st": is_st,
                "board": None,
                "concepts": [],
            }
        )
    return stocks


def _load_names(session, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    table = db_schema.stocks
    stmt = select(table.c.vt_symbol, table.c.name).where(
        table.c.vt_symbol.in_(symbols)
    )
    return {str(r.vt_symbol): str(r.name) for r in session.execute(stmt) if r.name}


def _stocks_from_daily(session, trade_date: date, include_st: bool) -> list[dict]:
    """daily_rebuild 模式个股 payload: 盘口字段 None, 日线字段保留。"""
    table = db_schema.stock_limit_up_daily
    stmt = select(table).where(
        table.c.trade_date == trade_date,
        table.c.is_limit_up.is_(True),
    )
    rows = [dict(row) for row in session.execute(stmt).mappings()]
    names = _load_names(session, [str(r["vt_symbol"]) for r in rows])
    stocks = []
    for row in rows:
        is_st = bool(row.get("is_st"))
        if is_st and not include_st:
            continue
        vt_symbol = str(row["vt_symbol"])
        stocks.append(
            {
                "vt_symbol": vt_symbol,
                "name": names.get(vt_symbol, vt_symbol),
                "limit_up_count": int(row.get("limit_up_count") or 0),
                "first_limit_time": None,
                "last_limit_time": None,
                "limit_amount": None,
                "break_count": None,
                "limit_stat_days": None,
                "limit_stat_boards": None,
                "is_reverse": None,
                "industry": None,
                "close_price": row.get("close_price"),
                "change_pct": row.get("change_pct"),
                "is_one_word": bool(row.get("is_one_word")),
                "is_st": is_st,
                "board": row.get("board"),
                "concepts": [],
            }
        )
    return stocks


def _load_concepts(session, symbols: list[str]) -> dict[str, list[str]]:
    """每股最多 3 个概念名: join 板块表过滤 type='concept', 名称排序取前 3。

    一次批量查询(无 N+1); Python 侧 sorted 保证跨数据库确定性
    (不依赖 DB collation); 同名概念去重。
    """
    if not symbols:
        return {}
    membership = db_schema.stock_sector_memberships
    sector = db_schema.sectors
    stmt = (
        select(membership.c.vt_symbol, sector.c.name)
        .select_from(membership.join(sector, membership.c.sector_id == sector.c.id))
        .where(
            membership.c.vt_symbol.in_(symbols),
            sector.c.type == "concept",
        )
    )
    by_symbol: dict[str, set[str]] = {}
    for vt_symbol, name in session.execute(stmt):
        if name:
            by_symbol.setdefault(str(vt_symbol), set()).add(str(name))
    return {
        symbol: sorted(names)[:MAX_CONCEPTS_PER_STOCK]
        for symbol, names in by_symbol.items()
    }


def _load_streak_map(session, trade_date: date, include_st: bool) -> dict[str, int]:
    """某日涨停股 {vt_symbol: streak}(is_limit_up=True, 按 include_st 过滤)。"""
    table = db_schema.stock_limit_up_daily
    stmt = select(
        table.c.vt_symbol, table.c.limit_up_count, table.c.is_st
    ).where(
        table.c.trade_date == trade_date,
        table.c.is_limit_up.is_(True),
    )
    return {
        str(r.vt_symbol): int(r.limit_up_count)
        for r in session.execute(stmt)
        if include_st or not r.is_st
    }


def _load_promotion_maps(
    session, trade_date: date, include_st: bool
) -> tuple[dict[str, int] | None, dict[str, int] | None]:
    """(前一日 streak 映射, 当日 streak 映射); 任一日无重建数据 → (None, None)。"""
    table = db_schema.stock_limit_up_daily
    today_map = _load_streak_map(session, trade_date, include_st)
    if not today_map:
        # 当日尚未 rebuild(或当日无涨停): 晋级率无法计算, None 容错。
        return None, None
    prev_date = session.execute(
        select(func.max(table.c.trade_date)).where(table.c.trade_date < trade_date)
    ).scalar()
    if prev_date is None:
        return None, None
    return _load_streak_map(session, prev_date, include_st), today_map


def _today_promotion(
    streak: int, prev_map: dict[str, int] | None, today_map: dict[str, int] | None
) -> dict | None:
    """今日 X进Y 实际晋级率。

    N>=2 档: base=昨日 streak==N-1 家数, promoted=其中今日 streak==N 家数;
    1板档即 1进2: base=昨日首板数, promoted=其中今日2板数。
    base==0(数据缺口/ST 切换等极端场景)→ rate=None 不除零。
    """
    if prev_map is None or today_map is None:
        return None
    prev_streak = streak - 1 if streak >= 2 else 1
    today_streak = streak if streak >= 2 else 2
    base_set = {s for s, count in prev_map.items() if count == prev_streak}
    promoted = sum(1 for s in base_set if today_map.get(s) == today_streak)
    base = len(base_set)
    return {
        "base": base,
        "promoted": promoted,
        "rate": round(promoted / base, 3) if base else None,
    }


def _stock_sort_key(stock: dict) -> tuple:
    """档内: first_limit_time 升序, None 最后, 同则 vt_symbol。"""
    first = stock["first_limit_time"]
    return (first is None, first or "", stock["vt_symbol"])


def build_ladder(
    session,
    trade_date: date,
    *,
    include_st: bool = False,
    pool_rows_override: list[dict] | None = None,
) -> dict[str, Any]:
    """连板天梯: 当日涨停股按连板数降序分档。

    返回 {"trade_date": iso, "source": "pool_archive" | "daily_rebuild" |
    "live_pool", "tiers": [{"streak", "count", "today_promotion", "stocks":
    [...]}, ...]}; 个股字段见模块 docstring(两模式键集一致, 不可用字段 None)。

    pool_rows_override: live 模式注入的归档行形状 zt 池(B4 盘中实时分流,
    当日归档未落库, 查表必空); 提供时不查表, source 标 "live_pool";
    空列表视同无归档, 回落 daily_rebuild 路径。
    """
    if pool_rows_override is not None:
        pool_rows = pool_rows_override
        source = "live_pool"
    else:
        pool_rows = _load_pool_rows(session, trade_date)
        source = "pool_archive"
    if pool_rows:
        stocks = _stocks_from_pool(pool_rows, include_st)
    else:
        source = "daily_rebuild"
        stocks = _stocks_from_daily(session, trade_date, include_st)

    concepts = _load_concepts(session, [s["vt_symbol"] for s in stocks])
    for stock in stocks:
        stock["concepts"] = concepts.get(stock["vt_symbol"], [])

    prev_map, today_map = _load_promotion_maps(session, trade_date, include_st)

    by_streak: dict[int, list[dict]] = {}
    for stock in stocks:
        by_streak.setdefault(stock["limit_up_count"], []).append(stock)

    tiers = []
    for streak in sorted(by_streak, reverse=True):
        group = sorted(by_streak[streak], key=_stock_sort_key)
        tiers.append(
            {
                "streak": streak,
                "count": len(group),
                "today_promotion": _today_promotion(streak, prev_map, today_map),
                "stocks": group,
            }
        )

    return {
        "trade_date": trade_date.isoformat(),
        "source": source,
        "tiers": tiers,
    }
