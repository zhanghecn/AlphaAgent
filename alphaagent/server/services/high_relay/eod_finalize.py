"""高位接力打板盘后定版:信号状态推进 + 次日池计算。

退出推进用"从数据重算"而非增量状态,天然幂等(重复跑/补跑结果一致)。
口径(E3 卖出纪律,与 backtest.py 逐行一致——v6.4 竞价卖/v6.5 纯收盘价/v6.7 跌停口径):
- 买入日当天没封住(炸板,T+1 当天卖不了)→ 次日起首个非一字跌停日收盘卖
  (break_day_close);全天一字跌停=排队卖不出,顺延
- 封住了 → 持有到首个未涨停日收盘卖(next_close_fail/break_close),盘中不判断
- 唯一盘中动作(v6.4): D+1 封板、D+2 开盘≤-5% → 竞价直接卖(d2_deep_open_sell,开盘价)
- 断板日全天一字死封跌停 → 顺延首个开板日开盘卖(limit_down_defer);
  15 日满仍锁死按断板日跌停价计(limit_down_locked);其余收盘跌停按跌停价卖(v6.7)
- 一路涨停到第 15 个交易日 → 当日收盘卖(max_hold_close,研究兜底口径)
- 数据还没到退出日(含顺延路径未走完)→ holding(在持),streak_h = 买入日起连续涨停天数

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
from alphaagent.server.services.high_relay import (
    contracts, live_scan, pool as pool_mod, repository,
)

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
    recovered = _backfill_missing_pool_signals(data_date)
    settled = _settle_residual_signals(data_date)
    finalized = _finalize_exits(data_date)
    pool_result = pool_mod.compute_pool(data_date)
    entries = pool_result.get("entries") or []
    exec_date = date.fromisoformat(str(pool_result["exec_date"]))
    saved = repository.save_pool(exec_date, entries, contracts.HPR_RULES_VERSION)
    message = (f"数据日 {data_date}:首触回填 {touched};漏扫补建 {recovered};"
               f"残留定版 {settled};退出推进 {finalized['closed']} 笔/{finalized['holding']} 在持;"
               f"次日池 {exec_date} = {saved} 只"
               f"(出手 {pool_result['filter_stats'].get('actionable')}: "
               + "/".join(f"{pk}{pool_result['filter_stats'].get(f'act_{pk}', 0)}"
                          for pk in contracts.POINT_KEYS)
               + f",昨日涨停 {pool_result.get('mkt_lim_tm1')})")
    logger.info("hpr eod finalize: %s", message)
    return {"status": "ok",
            "rows_read": finalized["processed"] + len(entries),
            "rows_written": saved + finalized["closed"] + settled + recovered + touched,
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


def _dyn_group_for_date(data_date: date) -> str:
    """漏扫补建使用当月的口诀组,避免跨月后用当前组误判历史。"""
    from alphaagent.server.services.high_relay import service

    states, asof = service._load_dyn_states()
    month = data_date.isoformat()[:7]
    if month in states:
        return str(states[month])
    # 新月份尚未物化时与盘中 current_dyn_group 一致:沿用最近物化月,不擅自双开。
    if asof and asof < month and asof in states:
        return str(states[asof])
    return "both"


def _backfill_missing_pool_signals(data_date: date) -> int:
    """盘中整天漏跑时,从当日池和真实日线补建可出手票的信号。

    只处理尚无信号的可出手票;已有实时结果绝不覆写,雷达票仍只展示不触发。
    与盘中扫描共用动态组和竞价门,随后按最高价判断触板、收盘价补展示行情。
    """
    pool = repository.load_pool(data_date)
    signals = repository.load_signal_map(data_date)
    missing = [entry for entry in pool if str(entry["vt_symbol"]) not in signals]
    if not missing:
        return 0
    vts = sorted({str(entry["vt_symbol"]) for entry in missing})
    bars = _load_bars(vts, data_date - timedelta(days=20), data_date)
    bmap = {(str(r.vt_symbol), r.trade_date.date()): r for r in bars.itertuples()} \
        if not bars.empty else {}
    group = _dyn_group_for_date(data_date)
    created = 0
    for entry in missing:
        strong_ok, scan_entry = live_scan._strong_access(entry, group)
        weak_hit = str(entry.get("weak_point") or "—") != "—"
        weak_ok = weak_hit and (group in ("weak", "both")
                                or str(entry.get("weak_point")) in contracts.COMMON_POINT_KEYS)
        if not (strong_ok or weak_ok):
            continue
        vt = str(entry["vt_symbol"])
        point = str(entry["weak_point"]) if weak_ok else str(entry.get("point") or "—")
        level = "A" if weak_ok else str(entry.get("level") or "—")
        patch: dict[str, object] = {
            "name": entry.get("name"), "group4": entry.get("group4"),
            "point": point, "level": level,
            "prev_close": entry.get("prev_close"),
            "limit_price": entry.get("limit_price"),
            "rules_version": contracts.HPR_RULES_VERSION,
        }
        bar = bmap.get((vt, data_date))
        if bar is None:
            repository.upsert_signal(data_date, vt, status="no_trigger", **patch)
            created += 1
            continue
        prev_close = float(entry["prev_close"])
        limit_price = float(entry["limit_price"])
        open_pct = round((float(bar.open_price) / prev_close - 1) * 100, 2)
        close_price = float(bar.close_price)
        patch.update({
            "auction_pct": open_pct,
            "last_price": close_price,
            "change_pct": round((close_price / prev_close - 1) * 100, 3),
        })
        terminal = live_scan._first_jump_status(
            scan_entry, open_pct, strong_ok=strong_ok, weak_ok=weak_ok,
        )
        if terminal is not None:
            patch["status"] = terminal
        else:
            point, level = live_scan._point_after_auction(
                entry, open_pct, weak_ok=weak_ok, point=point,
            )
            patch["point"] = point
            patch["level"] = level
            if float(bar.high_price) < limit_price - 1e-6:
                patch["status"] = "no_trigger"
            else:
                patch.update(status="entered", entry_price=limit_price)
        repository.upsert_signal(data_date, vt, **patch)
        created += 1
    return created


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
    # pandas3: itertuples 的 trade_date 是 Timestamp,信号侧是 date——统一 .date() 作键
    bmap = {(str(r.vt_symbol), r.trade_date.date()): r for r in bars.itertuples()} \
        if not bars.empty else {}

    settled = 0
    for sig in pend:
        vt = str(sig["vt_symbol"])
        day = sig["trade_date"]
        limit_price = float(sig["limit_price"])
        bar = bmap.get((vt, day))
        status = str(sig["status"])
        # 已有行的基础字段随行带回(裸 upsert 缺 prev_close/limit_price 列,
        # INSERT 阶段就撞非空约束——停牌票无当日日线走 bar is None 分支时踩过,2026-09-30)
        sig_base = {k: sig.get(k) for k in
                    ("name", "group4", "point", "prev_close", "limit_price")}
        if bar is None:
            repository.upsert_signal(day, vt, status="no_trigger", **sig_base)
            settled += 1
            continue
        # 补录兜底(链式口径): 开盘≥9.5%顶格不命中;触板即买;没触板=no_trigger
        prev_close = float(sig["prev_close"]) if sig.get("prev_close") else None
        open_pct = (float(bar.open_price) / prev_close - 1) * 100 if prev_close else None
        if open_pct is not None and open_pct >= contracts.TODAY_CAP:
            repository.upsert_signal(day, vt, status="skipped_gap", **sig_base)
        elif float(bar.high_price) < limit_price - 1e-6:
            repository.upsert_signal(day, vt, status="no_trigger", **sig_base)
        else:
            repository.upsert_signal(day, vt, status="entered",
                                     entry_price=limit_price,
                                     auction_pct=round(open_pct, 2) if open_pct is not None else None,
                                     **sig_base)
        settled += 1
    return settled


def _finalize_exits(data_date: date) -> dict[str, int]:
    """推进所有未了结信号到 data_date 口径(E3 卖出,与 backtest.py 逐行一致)。"""
    open_signals = repository.load_open_entry_signals()
    if not open_signals:
        return {"closed": 0, "holding": 0, "processed": 0}
    vts = sorted({str(s["vt_symbol"]) for s in open_signals})
    min_date = min(s["trade_date"] for s in open_signals)
    bars = _load_bars(vts, min_date - timedelta(days=20), data_date)

    closed = holding = 0
    max_hold = contracts.MAX_HOLD_DAYS
    for sig in open_signals:
        vt = str(sig["vt_symbol"])
        entry_date = sig["trade_date"]
        entry_price = float(sig["entry_price"])
        limit_price = float(sig["limit_price"])
        # 已有行基础字段随行带回(裸 upsert 缺 prev_close 列撞非空;与 settle 同修,2026-10-01)
        sig_base = {k: sig.get(k) for k in
                    ("name", "group4", "point", "prev_close", "limit_price")}
        sub = bars[(bars["vt_symbol"] == vt)
                   & (bars["trade_date"] >= pd.Timestamp(entry_date))
                   & (bars["trade_date"] <= pd.Timestamp(data_date))] if not bars.empty else pd.DataFrame()
        if sub.empty:
            repository.upsert_signal(entry_date, vt, status="pending_exit", **sig_base)
            holding += 1
            continue
        # 统一 date 类型(pandas3 下 Timestamp 与 date 不可比较/作键);写库 exit_date 即 date
        sub = sub.copy()
        sub["trade_date"] = sub["trade_date"].dt.date
        rows = list(sub.itertuples())
        first = rows[0]
        # 封板判定=收盘涨停(与 pool.derive_daily 的 is_lim 等价)
        sealed = (abs(float(first.close_price) - limit_price) <= 1e-6
                  and bool(first.is_lim))
        if not sealed:
            # 炸板(T+1 当天卖不了): 次日起首个非一字跌停日收盘卖;
            # 全天一字跌停=排队卖不出顺延(v6.7 仅此顺延)——回测 sealed=False 分支同口径
            prev_c = float(first.close_price)
            exit_day = None
            exit_price = None
            for k in range(1, min(len(rows), max_hold + 1)):
                r = rows[k]
                ko, kc = float(r.open_price), float(r.close_price)
                locked = (ko == kc == float(r.high_price) == float(r.low_price)
                          and prev_c > 0 and (kc / prev_c - 1) <= -0.095)
                prev_c = kc
                if locked:
                    continue
                exit_day, exit_price = r.trade_date, kc
                break
            if exit_day is None and len(rows) - 1 >= max_hold:
                # 防御:15 日连续一字跌停(现实未发生)按末日收盘
                exit_day = rows[max_hold].trade_date
                exit_price = float(rows[max_hold].close_price)
            if exit_day is None:
                repository.upsert_signal(entry_date, vt, status="holding",
                                         sealed=False, streak_h=0, **sig_base)
                holding += 1
                continue
            repository.upsert_signal(
                entry_date, vt, status="closed", sealed=False, streak_h=0,
                exit_date=exit_day, exit_price=exit_price,
                exit_reason="break_day_close",
                ret_pct=round((exit_price / entry_price - 1) * 100, 3), **sig_base)
            closed += 1
            continue
        # 封住了 → E0: 次日起首个未涨停日(15 日兜底)
        hold_days: int | None = None
        capped = False
        for k in range(1, min(len(rows), max_hold + 1)):
            if not bool(rows[k].is_lim):
                hold_days = k
                break
        if hold_days is None:
            if len(rows) - 1 >= max_hold:
                hold_days = max_hold
                capped = True
            else:
                streak_h = 1 + sum(1 for r in rows[1:] if bool(r.is_lim))
                repository.upsert_signal(entry_date, vt, status="holding",
                                         sealed=True, streak_h=streak_h, **sig_base)
                holding += 1
                continue
        exit_day = None
        exit_price = None
        reason: str | None = None
        # v6.4 唯一盘中动作: D+1 封住(hold_days>=2)且 D+2 开盘≤-5% → 竞价卖(开盘价)
        if hold_days >= 2:
            d1c = float(rows[1].close_price)
            d2o = float(rows[2].open_price)
            if d1c > 0 and (d2o / d1c - 1) <= -0.05:
                exit_day = rows[2].trade_date
                exit_price = d2o
                reason = "d2_deep_open_sell"
        if exit_day is None:
            k0 = hold_days
            r0 = rows[k0]
            exit_day = r0.trade_date
            exit_price = float(r0.close_price)
            reason = ("next_close_fail" if k0 == 1 else
                      ("max_hold_close" if capped else "break_close"))
            # v6.7: 断板日全天一字死封跌停 → 排队卖不出,顺延首个开板日开盘卖
            prev0 = float(rows[k0 - 1].close_price)
            k0o, k0h, k0l = (float(r0.open_price), float(r0.high_price),
                             float(r0.low_price))
            if (exit_price <= prev0 * 0.905 + 0.011 and k0o == k0h == k0l
                    and abs(k0o - exit_price) <= 0.011):
                pc = exit_price
                deferred = False
                for j in range(k0 + 1, min(len(rows), max_hold + 1)):
                    rj = rows[j]
                    jo, jh, jl, jc = (float(rj.open_price), float(rj.high_price),
                                      float(rj.low_price), float(rj.close_price))
                    if jo == jh == jl == jc and (jc / pc - 1) <= -0.095:
                        pc = jc
                        continue
                    exit_day, exit_price = rj.trade_date, jo
                    reason = "limit_down_defer"
                    deferred = True
                    break
                if not deferred:
                    if len(rows) - 1 >= max_hold:
                        reason = "limit_down_locked"  # 15 日满仍锁死:按断板日跌停价计
                    else:
                        # 顺延路径数据未走完(还在锁死):明天再推进
                        streak_h = 1 + sum(1 for r in rows[1:] if bool(r.is_lim))
                        repository.upsert_signal(entry_date, vt, status="holding",
                                                 sealed=True, streak_h=streak_h, **sig_base)
                        holding += 1
                        continue
        streak_h = 1 + int(sum(1 for r in rows[1:]
                               if r.trade_date < exit_day and bool(r.is_lim)))
        repository.upsert_signal(
            entry_date, vt, status="closed", sealed=True, streak_h=streak_h,
            exit_date=exit_day, exit_price=exit_price, exit_reason=reason,
            ret_pct=round((exit_price / entry_price - 1) * 100, 3), **sig_base)
        closed += 1
    return {"closed": closed, "holding": holding, "processed": len(open_signals)}
