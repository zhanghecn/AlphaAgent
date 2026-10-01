"""二波反包盘后定版:信号状态推进 + 次日池计算(幂等,从日线重算)。

口径(卖出与 fanbao v2.2 完全同款 T+1):
- 买入日炸板 → 次日收盘卖(次日一字跌停四价合一跌≥9.5%顺延首个开板日)→ closed
- 封住 → 次日起首个未涨停日收盘卖 / 15日兜底 → closed
- 数据未到退出日 → holding(在持)
残留定版(扫描漏检兜底,日线重推):
- watching: 当日最高<涨停价 → no_trigger;最高≥涨停价且非一字 → entered;
  全天一字 → skipped_gap
- sealed_watch(T字观察): 全天一字 → skipped_gap;盘中开过(最低<涨停) → entered
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.erbo import contracts, pool as pool_mod, repository

logger = logging.getLogger(__name__)


def run_eod_finalize() -> dict[str, object]:
    """盘后主入口:定版今日信号 + 推进在持退出 + 计算次日池。"""
    data_date = pool_mod.latest_daily_date()
    if data_date is None:
        return {"status": "skipped", "message": "数据库无日线"}
    settled = _settle_residual_signals(data_date)
    finalized = _finalize_exits(data_date)
    pool_result = pool_mod.compute_pool(data_date)
    entries = pool_result.get("entries") or []
    exec_date = date.fromisoformat(str(pool_result["exec_date"]))
    saved = repository.save_pool(exec_date, entries, contracts.ERBO_RULES_VERSION)
    message = (f"数据日 {data_date}:残留定版 {settled};"
               f"退出推进 {finalized['closed']} 笔/{finalized['holding']} 在持;"
               f"次日池 {exec_date} = {saved} 只"
               f"(出手 {pool_result['filter_stats'].get('actionable')})")
    logger.info("erbo eod finalize: %s", message)
    return {"status": "ok",
            "rows_read": finalized["processed"] + len(entries),
            "rows_written": saved + finalized["closed"] + settled,
            "message": message}


def _load_bars(vts: list[str], start: date, end: date) -> pd.DataFrame:
    """读日线并补 prev_close/is_lim(轻量版,与 fanbao 同口径)。"""
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
    """定版 ≤ data_date 仍挂 watching/sealed_watch 的信号。"""
    schema.ensure_schema_once(get_engine())
    pend = repository.load_open_watching(data_date)
    if not pend:
        return 0
    vts = sorted({str(s["vt_symbol"]) for s in pend})
    start = min(s["trade_date"] for s in pend)
    bars = _load_bars(vts, start, data_date)
    bmap = {(str(r.vt_symbol), r.trade_date): r for r in bars.itertuples()} \
        if not bars.empty else {}
    settled = 0
    for sig in pend:
        vt, day = str(sig["vt_symbol"]), sig["trade_date"]
        limit_price = float(sig["limit_price"])
        bar = bmap.get((vt, day))
        sig_base = {k: sig.get(k) for k in ("name", "point", "level",
                                            "prev_close", "limit_price")}
        if bar is None:
            repository.upsert_signal(day, vt, status="no_trigger", **sig_base)
        elif str(sig["status"]) == "sealed_watch":
            one_word = (abs(float(bar.open_price) - float(bar.close_price)) <= 1e-6
                        and abs(float(bar.open_price) - float(bar.high_price)) <= 1e-6
                        and abs(float(bar.open_price) - float(bar.low_price)) <= 1e-6)
            if one_word and bool(bar.is_lim):
                repository.upsert_signal(day, vt, status="skipped_gap", **sig_base)
            elif float(bar.low_price) < limit_price - 1e-6:
                repository.upsert_signal(day, vt, status="entered",
                                         entry_price=limit_price, opened=True, **sig_base)
            else:
                repository.upsert_signal(day, vt, status="skipped_gap", **sig_base)
        else:  # watching(无首刻窗:日线 high≥涨停价即触板充分证据)
            if float(bar.high_price) < limit_price - 1e-6:
                repository.upsert_signal(day, vt, status="no_trigger", **sig_base)
            elif (abs(float(bar.open_price) - float(bar.close_price)) <= 1e-6
                  and abs(float(bar.open_price) - float(bar.high_price)) <= 1e-6
                  and abs(float(bar.open_price) - float(bar.low_price)) <= 1e-6):
                repository.upsert_signal(day, vt, status="skipped_gap", **sig_base)
            else:
                repository.upsert_signal(day, vt, status="entered",
                                         entry_price=limit_price, **sig_base)
        settled += 1
    return settled


def _finalize_exits(data_date: date) -> dict[str, int]:
    """推进 entered/holding 信号到 data_date 口径(卖出定版,T+1)。"""
    open_sigs = repository.load_open_entry_signals()
    if not open_sigs:
        return {"closed": 0, "holding": 0, "processed": 0}
    vts = sorted({str(s["vt_symbol"]) for s in open_sigs})
    min_date = min(s["trade_date"] for s in open_sigs)
    bars = _load_bars(vts, min_date, data_date)

    closed = holding = 0
    for sig in open_sigs:
        vt = str(sig["vt_symbol"])
        entry_date = sig["trade_date"]
        entry_price = float(sig["entry_price"])
        sub = bars[(bars["vt_symbol"] == vt)
                   & (bars["trade_date"] >= entry_date)
                   & (bars["trade_date"] <= data_date)] if not bars.empty else pd.DataFrame()
        if sub.empty:
            repository.upsert_signal(entry_date, vt, status="holding")
            holding += 1
            continue
        first = sub.iloc[0]
        later = sub[sub["trade_date"] > entry_date]
        bad_ticket: bool | None = None
        if not later.empty:
            bad_ticket = float(later.iloc[0]["close_price"]) < entry_price
        # 买入日封住与否:优先用信号现值(盘中记录),日线重推兜底
        sealed = (bool(sig.get("sealed")) if sig.get("sealed") is not None
                  else (abs(float(first["close_price"]) - float(sig["limit_price"])) <= 1e-6
                        and bool(first["is_lim"])))
        if not sealed:
            # 炸板:次日收盘卖,一字跌停锁死顺延首个开板日
            exit_d = exit_px = None
            prev_c = float(first["close_price"])
            for r in later.itertuples():
                ro, rc = float(r.open_price), float(r.close_price)
                locked = (ro == rc == float(r.high_price) == float(r.low_price)
                          and (rc / prev_c - 1) <= -0.095)
                prev_c = rc
                if locked:
                    continue
                exit_d, exit_px = r.trade_date, rc
                break
            if exit_d is None:
                repository.upsert_signal(entry_date, vt, status="holding",
                                         sealed=False, streak_h=0, bad_ticket=bad_ticket)
                holding += 1
                continue
            repository.upsert_signal(
                entry_date, vt, status="closed", sealed=False, streak_h=0,
                exit_date=exit_d, exit_price=exit_px,
                exit_reason="break_day_close", bad_ticket=bad_ticket,
                ret_pct=round((exit_px / entry_price - 1) * 100, 3))
            closed += 1
            continue
        # 封住:次日起首个未涨停日收盘卖,15 日兜底
        exit_d = exit_px = None
        reason = None
        for idx, r in enumerate(later.itertuples(), start=1):
            if idx > contracts.MAX_HOLD_DAYS:
                break
            if not bool(r.is_lim):
                exit_d, exit_px = r.trade_date, float(r.close_price)
                reason = "next_close_fail" if idx == 1 else "break_close"
                break
        if exit_d is None and len(later) >= contracts.MAX_HOLD_DAYS:
            last = later.iloc[contracts.MAX_HOLD_DAYS - 1]
            exit_d, exit_px = last["trade_date"], float(last["close_price"])
            reason = "max_hold_close"
        if exit_d is not None:
            streak_h = 1 + int(sum(1 for r in later.itertuples()
                                   if r.trade_date < exit_d and bool(r.is_lim)))
            repository.upsert_signal(
                entry_date, vt, status="closed", sealed=True, streak_h=streak_h,
                exit_date=exit_d, exit_price=exit_px, exit_reason=reason,
                bad_ticket=bad_ticket,
                ret_pct=round((exit_px / entry_price - 1) * 100, 3))
            closed += 1
        else:
            repository.upsert_signal(entry_date, vt, status="holding",
                                     sealed=True, bad_ticket=bad_ticket)
            holding += 1
    return {"closed": closed, "holding": holding, "processed": len(open_sigs)}
