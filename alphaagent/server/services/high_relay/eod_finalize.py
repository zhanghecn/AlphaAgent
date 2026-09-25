"""高位接力打板盘后定版:信号状态推进 + 次日池计算。

退出推进用"从数据重算"而非增量状态,天然幂等(重复跑/补跑结果一致)。
口径(连板链组合方案 A1~D2, E3 卖出纪律):
- 买入日当天没封住(炸板)→ 当天收盘价卖(break_day_close),不隔夜赌
- 封住了 → 买入次日起首个未涨停日收盘卖(next_close_fail/break_close)
- 一路涨停到第 15 个交易日 → 当日收盘卖(max_hold_close,研究兜底口径)
- 数据还没到退出日 → holding(在持),streak_h = 买入日起连续涨停天数

残留状态定版(扫描漏检/服务中断兜底,全部由日线+首触时间重推):
- watching: 当日最高<涨停价 → no_trigger;首触≤09:45 → entered(回填);
  首触>09:45 或无时刻数据 → late_touch(保守不补买入)
- 竞价开盘≥9.5%(顶格/一字)→ skipped_gap(正常开盘口径外,补录兜底同判);
  盘中开过(最低<涨停) → entered(排板成交,买价=涨停价)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.high_relay import contracts, pool as pool_mod, repository

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")

_TOUCH_EDGES = (9 * 60 + 45, 10 * 60, 10 * 60 + 15, 10 * 60 + 30, 10 * 60 + 45,
                11 * 60, 11 * 60 + 15, 11 * 60 + 30, 13 * 60 + 15, 13 * 60 + 30,
                13 * 60 + 45, 14 * 60, 14 * 60 + 15, 14 * 60 + 30, 14 * 60 + 45, 15 * 60)


def run_eod_finalize() -> dict[str, object]:
    """盘后主入口:回填首触时间 + 定版今日信号 + 推进在持退出 + 计算次日池。"""
    data_date = pool_mod.latest_daily_date()
    if data_date is None:
        return {"status": "skipped", "message": "数据库无日线"}
    touched = _backfill_touch_times(data_date)
    settled = _settle_residual_signals(data_date)
    finalized = _finalize_exits(data_date)
    pool_result = pool_mod.compute_pool(data_date)
    entries = pool_result.get("entries") or []
    exec_date = date.fromisoformat(str(pool_result["exec_date"]))
    saved = repository.save_pool(exec_date, entries, contracts.HPR_RULES_VERSION)
    message = (f"数据日 {data_date}:首触回填 {touched};残留定版 {settled};"
               f"退出推进 {finalized['closed']} 笔/{finalized['holding']} 在持;"
               f"次日池 {exec_date} = {saved} 只"
               f"(出手 {pool_result['filter_stats'].get('actionable')}: "
               + "/".join(f"{pk}{pool_result['filter_stats'].get(f'act_{pk}', 0)}"
                          for pk in contracts.POINT_KEYS)
               + f",昨日涨停 {pool_result.get('mkt_lim_tm1')})")
    logger.info("hpr eod finalize: %s", message)
    return {"status": "ok",
            "rows_read": finalized["processed"] + len(entries),
            "rows_written": saved + finalized["closed"] + settled + touched,
            "message": message}


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

    与 w2s eod 同口径同表(全市场通用心跳表,幂等 upsert),本服务自足不依赖 w2s 任务。
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


def _load_bars(vts: list[str], start: date, end: date) -> pd.DataFrame:
    """读日线并补 prev_close/is_lim(与 pool.derive_daily 同口径的轻量版)。"""
    engine = get_engine()
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price,
               schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.close_price)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vts),
               schema.stock_daily_bars.c.trade_date >= start,
               schema.stock_daily_bars.c.trade_date <= end),
        engine, parse_dates=["trade_date"])
    if bars.empty:
        return bars
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["limit_price"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig = bars["prev_close"].notna() & (bars["prev_close"] > 0)
    bars["is_lim"] = elig & ((bars["close_price"] - bars["limit_price"]).abs() <= 1e-6)
    return bars


def _settle_residual_signals(data_date: date) -> int:
    """定版 ≤ data_date 仍挂在 watching/sealed_watch 的信号(扫描漏检兜底)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.hpr_signals)
            .where(schema.hpr_signals.c.trade_date <= data_date)
            .where(schema.hpr_signals.c.status.in_(["watching", "sealed_watch"]))
        ).mappings().all()
    pend = [dict(r) for r in rows]
    if not pend:
        return 0
    vts = sorted({str(r["vt_symbol"]) for r in pend})
    start = min(r["trade_date"] for r in pend)
    bars = _load_bars(vts, start, data_date)
    bmap = {(str(r.vt_symbol), r.trade_date): r for r in bars.itertuples()} \
        if not bars.empty else {}

    settled = 0
    for sig in pend:
        vt = str(sig["vt_symbol"])
        day = sig["trade_date"]
        limit_price = float(sig["limit_price"])
        bar = bmap.get((vt, day))
        status = str(sig["status"])
        if bar is None:
            repository.upsert_signal(day, vt, status="no_trigger")
            settled += 1
            continue
        # 补录兜底(链式口径): 开盘≥9.5%顶格不命中;触板即买;没触板=no_trigger
        prev_close = float(sig["prev_close"]) if sig.get("prev_close") else None
        open_pct = (float(bar.open_price) / prev_close - 1) * 100 if prev_close else None
        if open_pct is not None and open_pct >= contracts.TODAY_CAP:
            repository.upsert_signal(day, vt, status="skipped_gap")
        elif float(bar.high_price) < limit_price - 1e-6:
            repository.upsert_signal(day, vt, status="no_trigger")
        else:
            repository.upsert_signal(day, vt, status="entered",
                                     entry_price=limit_price,
                                     auction_pct=round(open_pct, 2) if open_pct is not None else None)
        settled += 1
    return settled


def _finalize_exits(data_date: date) -> dict[str, int]:
    """推进所有未了结信号到 data_date 口径(E3 卖出)。"""
    open_signals = repository.load_open_entry_signals()
    if not open_signals:
        return {"closed": 0, "holding": 0, "processed": 0}
    vts = sorted({str(s["vt_symbol"]) for s in open_signals})
    min_date = min(s["trade_date"] for s in open_signals)
    bars = _load_bars(vts, min_date - timedelta(days=20), data_date)

    closed = holding = 0
    for sig in open_signals:
        vt = str(sig["vt_symbol"])
        entry_date = sig["trade_date"]
        entry_price = float(sig["entry_price"])
        limit_price = float(sig["limit_price"])
        sub = bars[(bars["vt_symbol"] == vt)
                   & (bars["trade_date"] >= entry_date)
                   & (bars["trade_date"] <= data_date)] if not bars.empty else pd.DataFrame()
        if sub.empty:
            repository.upsert_signal(entry_date, vt, status="pending_exit")
            holding += 1
            continue
        first = sub.iloc[0]
        # 买入日没封住 → 当天收盘卖(E3);判定用池触发价(=当日涨停价)
        sealed = abs(float(first["close_price"]) - limit_price) <= 1e-6 and bool(first["is_lim"])
        if not sealed:
            exit_price = float(first["close_price"])
            repository.upsert_signal(
                entry_date, vt, status="closed", sealed=False, streak_h=0,
                exit_date=entry_date, exit_price=exit_price,
                exit_reason="break_day_close",
                ret_pct=round((exit_price / entry_price - 1) * 100, 3))
            closed += 1
            continue
        # 封住了 → 次日起首个未涨停日收盘卖,15 日兜底
        later = sub[sub["trade_date"] > entry_date]
        exit_day: date | None = None
        exit_price: float | None = None
        reason: str | None = None
        for idx, r in enumerate(later.itertuples(), start=1):
            if idx > contracts.MAX_HOLD_DAYS:
                break
            if not bool(r.is_lim):
                exit_day = r.trade_date
                exit_price = float(r.close_price)
                reason = "next_close_fail" if idx == 1 else "break_close"
                break
        if exit_day is None and len(later) >= contracts.MAX_HOLD_DAYS:
            last = later.iloc[contracts.MAX_HOLD_DAYS - 1]
            exit_day = last["trade_date"]
            exit_price = float(last["close_price"])
            reason = "max_hold_close"
        if exit_day is not None and exit_price is not None:
            streak_h = 1 + int(sum(1 for r in later.itertuples()
                                   if r.trade_date < exit_day and bool(r.is_lim)))
            repository.upsert_signal(
                entry_date, vt, status="closed", sealed=True, streak_h=streak_h,
                exit_date=exit_day, exit_price=exit_price, exit_reason=reason,
                ret_pct=round((exit_price / entry_price - 1) * 100, 3))
            closed += 1
        else:
            streak_h = 1 + int(sum(1 for r in later.itertuples() if bool(r.is_lim)))
            repository.upsert_signal(entry_date, vt, status="holding",
                                     sealed=True, streak_h=streak_h)
            holding += 1
    return {"closed": closed, "holding": holding, "processed": len(open_signals)}
