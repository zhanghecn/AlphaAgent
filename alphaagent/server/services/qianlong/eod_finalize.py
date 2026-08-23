"""潜龙首板盘后定版:信号状态推进 + 次日池计算。

退出推进用"从数据重算"而非增量状态,天然幂等(重复跑/补跑结果一致):
对每个未了结信号,从 stock_limit_up_daily 逐日重放 entry_date 到最新日线日:
- 首板日未封板 → 次日开盘卖(next_open_fail)
- 封板但次日未连板 → 次日开盘卖(next_open_nostreak)
- 连板中某日未涨停 → 该日开盘卖(break_open)
- 一路涨停到最新日 → holding,streak_h = 连续涨停天数
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.qianlong import contracts, pool as pool_mod, repository

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def run_eod_finalize() -> dict[str, object]:
    """盘后主入口:定版今日信号 + 推进在持退出 + 计算次日池。"""
    data_date = pool_mod.latest_daily_date()
    if data_date is None:
        return {"status": "skipped", "message": "数据库无日线"}
    finalized = _finalize_signals(data_date)
    pool_result = pool_mod.compute_pool(data_date)
    entries = pool_result.get("entries") or []
    exec_date = date.fromisoformat(str(pool_result["exec_date"]))
    saved = repository.save_pool(exec_date, entries, contracts.QIANLONG_RULES_VERSION)
    message = (f"数据日 {data_date}:信号定版 {finalized['closed']} 笔退出/"
               f"{finalized['holding']} 在持/{finalized['no_trigger']} 未触发;"
               f"次日池 {exec_date} = {saved} 只")
    logger.info("qianlong eod finalize: %s", message)
    return {"status": "ok", "rows_read": finalized["processed"] + len(entries),
            "rows_written": saved + finalized["closed"], "message": message}


def _finalize_signals(data_date: date) -> dict[str, int]:
    """推进所有未了结信号到 data_date 口径;定版盘中残留的 watching/touched。"""
    engine = get_engine()
    closed = holding = no_trigger = 0

    # 1) 盘中残留状态定版(任何早于等于 data_date 的 watching/touched → no_trigger)
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_signals.c.trade_date, schema.qianlong_signals.c.vt_symbol,
                   schema.qianlong_signals.c.status)
            .where(schema.qianlong_signals.c.trade_date <= data_date)
            .where(schema.qianlong_signals.c.status.in_(["watching", "touched"]))
        ).mappings().all()
    for row in rows:
        repository.upsert_signal(row["trade_date"], row["vt_symbol"], status="no_trigger")
        no_trigger += 1

    # 2) 未了结信号逐日重放
    open_signals = repository.load_open_entry_signals()
    if not open_signals:
        return {"closed": 0, "holding": 0, "no_trigger": no_trigger, "processed": 0}
    vts = [str(s["vt_symbol"]) for s in open_signals]
    min_date = min(s["trade_date"] for s in open_signals)
    lu = pd.read_sql(
        select(schema.stock_limit_up_daily.c.vt_symbol,
               schema.stock_limit_up_daily.c.trade_date,
               schema.stock_limit_up_daily.c.is_limit_up)
        .where(schema.stock_limit_up_daily.c.vt_symbol.in_(vts),
               schema.stock_limit_up_daily.c.trade_date >= min_date,
               schema.stock_limit_up_daily.c.trade_date <= data_date),
        engine,
    )
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vts),
               schema.stock_daily_bars.c.trade_date >= min_date,
               schema.stock_daily_bars.c.trade_date <= data_date),
        engine,
    )
    lu_map = {(str(r.vt_symbol), r.trade_date): bool(r.is_limit_up)
              for r in lu.itertuples()}
    open_map = {(str(r.vt_symbol), r.trade_date): float(r.open_price)
                for r in bars.itertuples()}
    all_dates = sorted({d for _, d in lu_map} | {d for _, d in open_map})

    for sig in open_signals:
        vt = str(sig["vt_symbol"])
        entry_date = sig["trade_date"]
        entry_price = float(sig["entry_price"])
        days = [d for d in all_dates if entry_date <= d <= data_date]
        streak = 0
        exit_day: date | None = None
        reason: str | None = None
        for idx, day in enumerate(days):
            if lu_map.get((vt, day), False):
                streak += 1
                continue
            # 首个未涨停日
            if idx == 0:
                # 首板日未封:次日开盘卖(次日已在 days 里则下一循环处理不到,直接定位)
                nxt = days[1] if len(days) > 1 else None
                if nxt is not None:
                    exit_day, reason = nxt, "next_open_fail"
                break
            exit_day = day
            reason = "next_open_nostreak" if streak == 1 else "break_open"
            break
        if exit_day is not None and exit_day in open_map:
            exit_price = open_map[(vt, exit_day)]
            repository.upsert_signal(
                entry_date, vt,
                status="closed", sealed=streak >= 1, streak_h=streak,
                exit_date=exit_day, exit_price=exit_price, exit_reason=reason,
                ret_pct=round((exit_price / entry_price - 1) * 100, 3),
            )
            closed += 1
        elif exit_day is None and streak >= 1:
            repository.upsert_signal(
                entry_date, vt, status="holding", sealed=True, streak_h=streak,
            )
            holding += 1
        else:
            # 首板日未封且次日数据未到:等下一个 EOD
            repository.upsert_signal(entry_date, vt, status="pending_exit", sealed=False,
                                     streak_h=0)
            holding += 1
    return {"closed": closed, "holding": holding, "no_trigger": no_trigger,
            "processed": len(open_signals)}
