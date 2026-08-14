"""涨停池五池近三周回补(手动 job)。

从 stock_daily_bars 取最近 days 个 distinct 交易日(降序), 逐日:
- 该日 zt 池已归档(limit_up_pool_snapshots 存在 (trade_date, "zt") 行)则跳过;
- 否则调 archive.archive_daily_pools 落库; 抓取日之间 sleep 防东财限流。

东财池只有近 ~3 周历史, 窗口外的日子接口返回 0 行属正常(计入 empty)。
本任务为手动触发, 不挂任何定时档; 当日若被盘中手动回补, 当晚 eod 归档任务
仍会 delete+insert 重写当日五池, 不会残留盘中部分快照。

Known limitation: 按日跳过判定只看 zt 池——当日 zt 有行即跳过整日, 其余池
(zbgc/dtgc/zt_previous/strong)的个别缺口不补; 要补洞可直接对该日重跑
archive_daily_pools(delete+insert 幂等)。
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any

from sqlalchemy import desc, select

from alphaagent.server.db import schema as db_schema
from alphaagent.server.services.lianban.archive import archive_daily_pools

DEFAULT_BACKFILL_DAYS = 25
DEFAULT_SLEEP_SECONDS = 1.0


def _recent_trade_dates(session, days: int) -> list[date]:
    """stock_daily_bars 最近 days 个 distinct 交易日, 降序。"""
    bars = db_schema.stock_daily_bars
    rows = session.execute(
        select(bars.c.trade_date)
        .distinct()
        .order_by(desc(bars.c.trade_date))
        .limit(int(days))
    ).all()
    return [row[0] for row in rows]


def _zt_pool_archived(session, trade_date: date) -> bool:
    table = db_schema.limit_up_pool_snapshots
    row = session.execute(
        select(table.c.vt_symbol)
        .where(
            table.c.trade_date == trade_date,
            table.c.pool_type == "zt",
        )
        .limit(1)
    ).first()
    return row is not None


def backfill_pool_snapshots(
    session,
    *,
    days: int = DEFAULT_BACKFILL_DAYS,
    adapter: Any = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict[str, Any]:
    """回补最近 days 个交易日的五池归档。

    返回 {"archived": [...], "skipped_existing": [...], "empty": [...]}
    (均为 iso 日期字符串, 降序)。
    """
    dates = _recent_trade_dates(session, days)
    skipped: list[date] = []
    pending: list[date] = []
    for trade_date in dates:
        if _zt_pool_archived(session, trade_date):
            skipped.append(trade_date)
        else:
            pending.append(trade_date)

    archived: list[str] = []
    empty: list[str] = []
    for index, trade_date in enumerate(pending):
        result = archive_daily_pools(session, trade_date, adapter=adapter)
        if int(result.get("rows_written") or 0) > 0:
            archived.append(trade_date.isoformat())
        else:
            empty.append(trade_date.isoformat())
        # 只在抓取日之间 sleep(跳过的不发请求, 无需限流; 最后一次抓完不再睡)
        if index < len(pending) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {
        "archived": archived,
        "skipped_existing": [d.isoformat() for d in skipped],
        "empty": empty,
    }
