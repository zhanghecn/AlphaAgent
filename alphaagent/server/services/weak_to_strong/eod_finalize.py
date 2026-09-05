"""N型补涨打板盘后定版:信号状态推进 + 次日池计算。

退出推进用"从数据重算"而非增量状态,天然幂等(重复跑/补跑结果一致)。
对每个未了结信号,从 stock_limit_up_daily + stock_daily_bars 逐日重放(四组统一口径):
- 买入日 T,从 T+1 起,首个未涨停日收盘卖(next_close_fail / break_close;炸板=T+1即走)
- 一路涨停到 T+20 → T+20 收盘卖(max_hold_close,研究 banhold 20 日窗口口径)
- T+20 内未断板且数据未到 T+20 → holding(在持),streak_h = 连续涨停天数
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.weak_to_strong import contracts, pool as pool_mod, repository

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
    saved = repository.save_pool(exec_date, entries, contracts.W2S_RULES_VERSION)
    touched = _backfill_touch_times(data_date)
    message = (f"数据日 {data_date}:信号定版 {finalized['closed']} 笔退出/"
               f"{finalized['holding']} 在持/{finalized['no_trigger']} 未触发;"
               f"次日池 {exec_date} = {saved} 只"
               f"(出手 {pool_result['filter_stats'].get('actionable')}: "
               + "/".join(f"{gk}{pool_result['filter_stats'].get(f'act_{gk}', 0)}"
                          for gk in contracts.GROUP_KEYS)
               + f",大盘涨停 {pool_result.get('mkt_lim_tm1')};"
               + f"首触时间补 {touched} 笔)")
    logger.info("w2s eod finalize: %s", message)
    return {"status": "ok", "rows_read": finalized["processed"] + len(entries),
            "rows_written": saved + finalized["closed"] + touched, "message": message}


_TOUCH_EDGES = (9 * 60 + 45, 10 * 60, 10 * 60 + 15, 10 * 60 + 30, 10 * 60 + 45,
                11 * 60, 11 * 60 + 15, 11 * 60 + 30, 13 * 60 + 15, 13 * 60 + 30,
                13 * 60 + 45, 14 * 60, 14 * 60 + 15, 14 * 60 + 30, 14 * 60 + 45, 15 * 60)


def _bucket_touch(hhmmss: str | None) -> str | None:
    """首封时刻 HH:MM:SS → 15mK周期末刻 HH:MM(集合竞价封板归09:45; 越界归最近段)."""
    if not hhmmss:
        return None
    try:
        h, m = int(hhmmss[:2]), int(hhmmss[3:5])
    except (ValueError, IndexError):
        return None
    mins = h * 60 + m
    if mins <= _TOUCH_EDGES[0]:
        return "09:45"
    for e in _TOUCH_EDGES:
        if mins <= e:
            return f"{e // 60:02d}:{e % 60:02d}"
    return "15:00"


def _backfill_touch_times(data_date: date) -> int:
    """当日涨停池快照(zt封板+zbgc炸板)首次封板时间 fbt → w2s_touch_times 增量.

    fbt=首封口径(≈首触的15m粒度近似, 触了没封住又封的差异在15分钟内多不可分);
    全量快照票都存(不只w2s池), 好差票库与时间研究复用. source=zt_pool.
    """
    engine = get_engine()
    snaps = pd.read_sql(
        select(schema.limit_up_pool_snapshots.c.vt_symbol,
               schema.limit_up_pool_snapshots.c.first_limit_time)
        .where(schema.limit_up_pool_snapshots.c.trade_date == data_date,
               schema.limit_up_pool_snapshots.c.pool_type.in_(["zt", "zbgc"])),
        engine)
    if snaps.empty:
        return 0
    rows = [{"vt_symbol": str(r.vt_symbol), "trade_date": data_date,
             "touch": touch, "source": "zt_pool"}
            for r in snaps.itertuples()
            if (touch := _bucket_touch(r.first_limit_time))]
    return repository.upsert_touch_times(rows)


def _finalize_signals(data_date: date) -> dict[str, int]:
    """推进所有未了结信号到 data_date 口径;定版盘中残留的 watching。"""
    engine = get_engine()
    closed = holding = no_trigger = 0

    # 1) 盘中残留状态定版(任何早于等于 data_date 的 watching → no_trigger)
    with session_scope() as session:
        rows = session.execute(
            select(schema.w2s_signals.c.trade_date, schema.w2s_signals.c.vt_symbol,
                   schema.w2s_signals.c.group_key)
            .where(schema.w2s_signals.c.trade_date <= data_date)
            .where(schema.w2s_signals.c.status == "watching")
        ).mappings().all()
    for row in rows:
        repository.upsert_signal(row["trade_date"], row["vt_symbol"], row["group_key"],
                                 status="no_trigger")
        no_trigger += 1

    # 2) 未了结信号逐日重放
    open_signals = repository.load_open_entry_signals()
    if not open_signals:
        return {"closed": 0, "holding": 0, "no_trigger": no_trigger, "processed": 0}
    vts = sorted({str(s["vt_symbol"]) for s in open_signals})
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
               schema.stock_daily_bars.c.close_price)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vts),
               schema.stock_daily_bars.c.trade_date >= min_date,
               schema.stock_daily_bars.c.trade_date <= data_date),
        engine,
    )
    lu_map = {(str(r.vt_symbol), r.trade_date): bool(r.is_limit_up)
              for r in lu.itertuples()}
    close_map = {(str(r.vt_symbol), r.trade_date): float(r.close_price)
                 for r in bars.itertuples()}
    days_by_vt: dict[str, list[date]] = {}
    for (vt, day) in close_map:
        days_by_vt.setdefault(vt, []).append(day)
    for vt in days_by_vt:
        days_by_vt[vt].sort()

    for sig in open_signals:
        vt = str(sig["vt_symbol"])
        group_key = str(sig["group_key"])
        entry_date = sig["trade_date"]
        entry_price = float(sig["entry_price"])
        days = [d for d in days_by_vt.get(vt, []) if entry_date <= d <= data_date]
        if not days:
            repository.upsert_signal(entry_date, vt, group_key, status="pending_exit")
            holding += 1
            continue
        sealed = lu_map.get((vt, entry_date), False)
        # 四组统一板留断走:T+1 起逐日检查(日序 k: T+1=2 … T+20=21,研究 banhold 口径)
        exit_day: date | None = None
        reason: str | None = None
        later = [d for d in days if d > entry_date]
        for idx, day in enumerate(later, start=2):
            if idx > contracts.MAX_HOLD_DAYS + 1:
                break
            if not lu_map.get((vt, day), False):
                exit_day = day
                reason = "next_close_fail" if idx == 2 else "break_close"
                break
        if exit_day is None and len(later) >= contracts.MAX_HOLD_DAYS:
            # 一路涨停到 T+20:兜底收盘卖
            exit_day = later[contracts.MAX_HOLD_DAYS - 1]
            reason = "max_hold_close"
        if exit_day is not None and (vt, exit_day) in close_map:
            exit_price = close_map[(vt, exit_day)]
            streak_h = sum(1 for d in days if d < exit_day and lu_map.get((vt, d), False))
            repository.upsert_signal(
                entry_date, vt, group_key,
                status="closed", sealed=sealed, streak_h=streak_h,
                exit_date=exit_day, exit_price=exit_price, exit_reason=reason,
                ret_pct=round((exit_price / entry_price - 1) * 100, 3),
            )
            closed += 1
        elif exit_day is None:
            streak_h = (1 if sealed else 0) + sum(
                1 for d in later if lu_map.get((vt, d), False))
            status = "holding" if streak_h >= 1 else "pending_exit"
            repository.upsert_signal(entry_date, vt, group_key, status=status,
                                     sealed=sealed, streak_h=streak_h)
            holding += 1
    return {"closed": closed, "holding": holding, "no_trigger": no_trigger,
            "processed": len(open_signals)}
