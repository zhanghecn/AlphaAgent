"""趋势弱转强回测引擎:日线口径全量回放 + 物化报告。

口径 = 量化因子研究/低吸研究/scripts/w2s_replay.py(定稿 v2,一字不改):
- 事件池: 主板非ST非退 / 前10日内出现过≥2连板 / 昨日未涨停 / 昨日换手3%~60%
- 组划分: 最近一次≥2连板高度==2 → A 组;>=4 且距末日≥3交易日 → B 组;=3 弃
- A1: 跌>3%+下影<2%+(量比0.7~1.2 或 振幅≥12%)+换手8~20%+底座<30%;+7%直接打
- A2: (最高-收盘)/昨收<2%+底座<30%;收盘封板才买(买价=涨停价)
- B:  跌>3%+下影<2%+(量比0.7~1.2 或 振幅≥12%)+换手5~25%;+7%直接打
- 盘中规则: A1 竞价0~+4% 过滤;昨日大盘(主板非ST)涨停>110 家停手
- 卖出: 买入日T,T+1 起首个未涨停日收盘卖,T+15 兜底
日线保守口径:A1/B 最高价触及+7% 且最低价不高于触发价(买得进)才算触发;无滑点;
日线未复权(除权极端收益 ~2% 噪声,规则说明披露)。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.weak_to_strong import contracts

REPLAY_START = pd.Timestamp("2023-04-01")
BARS_START = "2023-03-28"  # 数据起点(ret20 需 20 根前置,首批事件 ~2023-04-26 起才有底座)


def run_backtest() -> dict[str, object]:
    """全量回放并返回物化 payload(不写库,由调用方持久化)。"""
    T = _build_events()
    groups = _split_groups(T)

    trades: dict[str, pd.DataFrame] = {}
    product: dict[str, pd.DataFrame] = {}
    for gk in contracts.GROUP_KEYS:
        trades[gk] = _trades_for(T, groups[gk], gk, auction=False, halt=False)
    product["a1"] = _product_filter(trades["a1"], auction=True)
    product["a2"] = _product_filter(trades["a2"], auction=False)
    product["b"] = _product_filter(trades["b"], auction=False)

    summary: dict[str, object] = {}
    for gk in contracts.GROUP_KEYS:
        summary[gk] = _stats(trades[gk])
        summary[f"{gk}_product"] = _stats(product[gk])

    all_prod = pd.concat([product[gk] for gk in contracts.GROUP_KEYS], ignore_index=True)
    coverage = {
        "from": _date_str(all_prod["entry_date"].min()),
        "to": _date_str(all_prod["entry_date"].max()),
        "months": int(all_prod["entry_date"].dt.to_period("M").nunique()) if len(all_prod) else 0,
    }

    payload: dict[str, object] = {
        "rules_version": contracts.W2S_RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "caliber": ("日线保守口径:A1/B 最高价触及 +7% 且最低价 ≤ 触发价即算触发(买价=昨收×1.07);"
                    "A2 收盘封板才视为买入(买价=涨停价);卖出=T+1 起首个未涨停日收盘,T+15 兜底;"
                    "无滑点,日线未复权"),
        "group_labels": contracts.GROUP_LABELS,
        "summary": summary,
        "yearly": {gk: _yearly(product[gk]) for gk in contracts.GROUP_KEYS},
        "monthly": {gk: _monthly(product[gk]) for gk in contracts.GROUP_KEYS},
        "curves": {gk: _curve(product[gk]) for gk in contracts.GROUP_KEYS},
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "anchor_check": _anchor_check(summary),
        "case_gates": _case_gates(T, groups),
    }
    payload["ledger_days"] = _ledger_days(all_prod)
    return payload


# ── 事件池构建(与 w2s_replay.py 同口径) ──

def _build_events() -> pd.DataFrame:
    engine = get_engine()
    stocks = pd.read_sql(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.name), engine)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    name_map = main.set_index("vt_symbol")["name"].to_dict()

    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price,
               schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.volume,
               schema.stock_daily_bars.c.turnover_rate)
        .where(schema.stock_daily_bars.c.trade_date >= date.fromisoformat(BARS_START)),
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(main["vt_symbol"]))].copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)
    bars["sid"], _ = pd.factorize(bars["vt_symbol"])
    g = bars.groupby("sid", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["pos"] = g.cumcount().astype("int32")
    bars["gap_days"] = g["trade_date"].diff().dt.days
    limit_px = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig = bars["prev_close"].notna() & (bars["prev_close"] > 0) & (bars["pos"] >= 5)
    bars["is_lim"] = elig & ((bars["close_price"] - limit_px).abs() <= 1e-6)
    is_lim_i = bars["is_lim"].astype("int8")
    brk = (~bars["is_lim"]).groupby(bars["sid"], sort=False).cumsum()
    bars["streak"] = is_lim_i.groupby([bars["sid"], brk], sort=False).cumsum()
    bars["chg"] = (bars["close_price"] / bars["prev_close"] - 1) * 100
    bars["chg_d2"] = g["chg"].shift(1)  # 前日涨跌幅(v2.2:前日也须收跌)
    low_oc = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (low_oc - bars["low_price"]) / bars["prev_close"] * 100
    bars["fade"] = (bars["high_price"] - bars["close_price"]) / bars["prev_close"] * 100
    bars["amp"] = (bars["high_price"] - bars["low_price"]) / bars["prev_close"] * 100
    bars["base20"] = g["close_price"].transform(lambda s: (s / s.shift(20) - 1) * 100)
    gv = g["volume"]
    bars["vol_ma5"] = gv.transform(lambda s: s.rolling(5, min_periods=3).mean())
    bars["vol_rel5"] = bars["volume"] / bars["vol_ma5"]
    gs = g["streak"]
    bars["s2max10"] = gs.transform(lambda s: s.rolling(10, min_periods=1).max())
    last2 = bars["pos"].where(bars["streak"] >= 2)
    bars["last2"] = last2.groupby(bars["sid"], sort=False).ffill()
    bars["gap2"] = bars["pos"] - bars["last2"]
    bars["last_streak"] = (bars["streak"].where(bars["streak"] >= 2)
                           .groupby(bars["sid"], sort=False).ffill())
    # v2.1 位置条件:首板日收盘不得创 60 日新高(突破过顶不做)
    bars["h60pre"] = g["high_price"].transform(
        lambda s: s.rolling(contracts.HIGH60_LOOKBACK, min_periods=20).max().shift(1))
    bars["ss_pos"] = bars["last2"] - bars["last_streak"] + 1
    lk = (bars[["sid", "pos", "close_price", "h60pre"]]
          .rename(columns={"pos": "ss_pos", "close_price": "fb_close", "h60pre": "fb_h60"}))
    bars = bars.merge(lk, on=["sid", "ss_pos"], how="left")
    bars.sort_values(["sid", "trade_date"], inplace=True)
    bars.reset_index(drop=True, inplace=True)
    g = bars.groupby("sid", sort=False)  # merge 后刷新,供后续 n{k} 前向列对齐
    bars["brk60"] = bars["fb_close"] >= bars["fb_h60"] - 1e-9  # NaN → False(历史不足视为未创)
    mkt = bars.groupby("trade_date", sort=False)["is_lim"].sum().rename("mkt_lim")
    bars = bars.merge(mkt, on="trade_date", how="left")
    bars["name"] = bars["vt_symbol"].map(name_map)

    for k in range(1, 16):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)
        bars[f"n{k}_date"] = g["trade_date"].shift(-k)
        bars[f"n{k}_gap"] = g["gap_days"].shift(-k)

    T = bars[(bars["trade_date"] >= REPLAY_START)
             & (bars["s2max10"] >= 2) & (bars["gap2"] >= 1) & (~bars["is_lim"])].copy()
    T = T[T["n1_close"].notna() & (T["n1_gap"] <= 10)].copy()
    pc1 = T["close_price"]
    T["reach7"] = (T["n1_high"] / pc1 - 1 >= 0.07) & (T["n1_low"] / pc1 - 1 <= 0.07)
    T["seal"] = T["n1_is_lim"].fillna(False).astype(bool)
    T["open_g"] = T["n1_open"] / pc1 - 1
    T["n2_lim"] = T["n2_is_lim"].fillna(False).astype(bool)
    return T


def _split_groups(T: pd.DataFrame) -> dict[str, pd.Series]:
    c = contracts
    base = (T["turnover_rate"].between(c.TURNOVER_BASE_MIN, c.TURNOVER_BASE_MAX))
    grp_a = T["last_streak"] == c.GROUP_A_STREAK
    grp_b = (T["last_streak"] >= c.GROUP_B_MIN_STREAK) & (T["gap2"] >= c.GROUP_B_MIN_GAP)
    cc = T["vol_rel5"].between(c.VOL_REL5_MIN, c.VOL_REL5_MAX) | (T["amp"] >= c.AMP_MIN)
    panic = (T["chg"] <= c.PANIC_CHG_MAX) & (T["lshadow"] < c.LOWER_SHADOW_MAX)
    return {
        "a1": base & grp_a & panic & cc & T["turnover_rate"].between(
            c.A1_TURNOVER_MIN, c.A1_TURNOVER_MAX) & (T["base20"] < c.BASE20_MAX)
            & (~T["brk60"]) & (T["chg_d2"] < 0),
        "a2": base & grp_a & (T["fade"] < c.FADE_MAX) & (T["base20"] < c.BASE20_MAX),
        "b": base & grp_b & panic & cc & T["turnover_rate"].between(
            c.B_TURNOVER_MIN, c.B_TURNOVER_MAX),
    }


# ── 成交回放 ──

def _trades_for(T: pd.DataFrame, mask: pd.Series, group_key: str,
                auction: bool, halt: bool) -> pd.DataFrame:
    e = T[mask].copy()
    if auction:
        e = e[e["open_g"].between(contracts.AUCTION_GAP_MIN, contracts.AUCTION_GAP_MAX)]
    if halt:
        e = e[e["mkt_lim"] <= contracts.MKT_LIM_HALT]
    if group_key == "a2":
        e = e[e["seal"]]
        e["entry_price"] = np.round(e["close_price"] * 1.10 + 1e-9, 2)
    else:
        e = e[e["reach7"]]
        e["entry_price"] = e["close_price"] * (1 + contracts.TRIGGER_PCT)
    e["entry_date"] = e["n1_date"]
    e["ret_d1"] = e["n2_close"] / e["entry_price"] - 1
    e = e[e["ret_d1"].notna() & e["entry_date"].notna()].copy()

    # 板留断走: n2..n15 首个未涨停日收盘卖;全板则 n15 收盘
    exit_px = pd.Series(np.nan, index=e.index)
    exit_dt = pd.Series(pd.NaT, index=e.index)
    hold_days = pd.Series(np.nan, index=e.index)  # 退出日相对买入日的日序(n2=2 … n15=15)
    reason = pd.Series("open_end", index=e.index, dtype=object)
    for k in range(2, 16):
        lim = e[f"n{k}_is_lim"].fillna(False).astype(bool)
        avail = e[f"n{k}_close"].notna() & e[f"n{k}_date"].notna()
        hit = exit_px.isna() & (~lim) & avail
        exit_px[hit] = e.loc[hit, f"n{k}_close"]
        exit_dt[hit] = e.loc[hit, f"n{k}_date"]
        hold_days[hit] = k
        reason[hit] = "next_close_fail" if k == 2 else "break_close"
    still = exit_px.isna() & e["n15_close"].notna() & e["n15_date"].notna()
    exit_px[still] = e.loc[still, "n15_close"]
    exit_dt[still] = e.loc[still, "n15_date"]
    hold_days[still] = 15
    reason[still] = "max_hold_close"
    e["exit_price_bw"] = exit_px
    e["exit_date_bw"] = exit_dt
    e["hold_days"] = hold_days
    e["ret_bw"] = e["exit_price_bw"] / e["entry_price"] - 1
    # 连板高度 = 买入日起连续涨停天数:退出日为 n2..n15 首个未涨停日,
    # 买入日封板 → 高度 = hold_days-1;买入日未封 → 高度 = hold_days-2(可能 0)
    e["exit_reason"] = reason
    e["streak_h"] = (e["hold_days"] - 1 - (~e["seal"]).astype(int)).clip(lower=0)
    e["group"] = group_key
    return e


def _product_filter(e: pd.DataFrame, auction: bool) -> pd.DataFrame:
    out = e[e["mkt_lim"] <= contracts.MKT_LIM_HALT]
    if auction:
        out = out[out["open_g"].between(contracts.AUCTION_GAP_MIN, contracts.AUCTION_GAP_MAX)]
    return out.copy()


# ── 统计与物化 ──

def _stats(e: pd.DataFrame) -> dict[str, object]:
    r = e["ret_d1"].dropna()
    if len(r) == 0:
        return {"n": 0}
    bw = e["ret_bw"].dropna()
    return {
        "n": int(len(r)),
        "seal": round(float(e["seal"].mean()), 3),
        "avg_pct": round(float(r.mean()) * 100, 2),
        "win": round(float((r > 0).mean()), 3),
        "streak2": round(float(e["n2_lim"].mean()), 3),
        "bw_pct": round(float(bw.mean()) * 100, 2) if len(bw) else None,
        "bw_win": round(float((bw > 0).mean()), 3) if len(bw) else None,
    }


def _yearly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    year = e["entry_date"].dt.year.astype(str)
    return [{"year": y, **_stats(g_)} for y, g_ in e.groupby(year)]


def _monthly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    month = e["entry_date"].dt.to_period("M").astype(str)
    return [{"month": m, **_stats(g_)} for m, g_ in e.groupby(month)]


def _curve(e: pd.DataFrame) -> list[dict[str, object]]:
    """逐笔等权累计收益曲线(每笔固定 1 单位,按入场日汇总后累加,不复利)。"""
    if not len(e):
        return []
    daily = e.dropna(subset=["ret_bw"]).groupby(
        e["entry_date"].dt.date)["ret_bw"].sum().sort_index()
    cum = (daily * 100).cumsum()
    return [{"date": d.isoformat(), "cum_pct": round(float(v), 2)} for d, v in cum.items()]


def _anchor_check(summary: dict[str, object]) -> dict[str, object]:
    """与修正锚点自校对;容差仅来自新增交易日与宇宙口径微差(302132 一只)。"""
    tol = contracts.ANCHOR_TOLERANCES
    out: dict[str, object] = {}
    for key, anchor in contracts.BACKTEST_ANCHORS.items():
        s = summary.get(key) or {}
        n = int(s.get("n", 0) or 0)
        avg = float(s.get("avg_pct", 0.0) or 0.0)
        win = float(s.get("win", 0.0) or 0.0)
        n_diff = n - int(anchor["n"])
        avg_diff = round(avg - float(anchor["avg_pct"]), 2)
        win_diff = round(win - float(anchor["win"]), 3)
        passed = (abs(n_diff) <= max(5, int(anchor["n"] * tol["n_pct"]))
                  and abs(avg_diff) <= tol["avg_pct"]
                  and abs(win_diff) <= tol["win"])
        out[key] = {"n_diff": n_diff, "avg_diff": avg_diff, "win_diff": win_diff,
                    "pass": bool(passed)}
    out["note"] = "差异应仅来自锚点之后的新增交易日;若同口径回溯期数值漂移即口径被破坏"
    return out


def _case_gates(T: pd.DataFrame, groups: dict[str, pd.Series]) -> list[dict[str, object]]:
    """案例门禁:具名案例的池归属与期望比对。"""
    out: list[dict[str, object]] = []
    for case in contracts.CASE_GATES:
        sub = T[(T["name"] == case["name"])
                & (T["trade_date"] == pd.Timestamp(str(case["date"])))]
        actual_groups: list[str] = []
        if len(sub):
            row = sub.iloc[0]
            actual_groups = [gk for gk in contracts.GROUP_KEYS if bool(groups[gk].loc[row.name])]
        expect = str(case["expect"])
        if expect == "in_a1":
            passed = "a1" in actual_groups
        elif expect == "out_a1":
            passed = "a1" not in actual_groups
        elif expect == "out_b":
            passed = "b" not in actual_groups
        else:  # out_any
            passed = not actual_groups
        out.append({"name": case["name"], "date": case["date"], "expect": expect,
                    "actual_groups": actual_groups, "pass": bool(passed),
                    "note": case["note"]})
    return out


def _ledger_days(all_trades: pd.DataFrame) -> list[dict[str, object]]:
    """全历史模拟交割单(产品口径,全组合并,不限仓位不限天数;月份筛选由 API 层切片)。"""
    e = all_trades.dropna(subset=["ret_bw", "exit_date_bw"]).copy()
    if not len(e):
        return []
    e["entry_day"] = e["entry_date"].dt.date
    out: list[dict[str, object]] = []
    for day, g_ in sorted(e.groupby("entry_day"), key=lambda kv: kv[0], reverse=True):
        items = [{
            "vt_symbol": str(r.vt_symbol),
            "name": str(r.name),
            "group": str(r.group),
            "group_label": contracts.GROUP_LABELS.get(str(r.group), ""),
            "entry_price": _sr(r.entry_price, 3),
            "gap_open_pct": _sr(float(r.open_g) * 100 if pd.notna(r.open_g) else None, 2),
            "sealed": bool(r.seal),
            "streak_h": int(r.streak_h) if pd.notna(r.streak_h) else 0,
            "exit_date": pd.Timestamp(r.exit_date_bw).date().isoformat(),
            "exit_price": _sr(r.exit_price_bw, 3),
            "exit_reason": str(r.exit_reason),
            "ret_pct": _sr(float(r.ret_bw) * 100, 2),
        } for r in g_.itertuples()]
        rets = [float(t["ret_pct"]) for t in items if t["ret_pct"] is not None]
        out.append({
            "trade_date": day.isoformat(),
            "trades": items,
            "count": len(items),
            "win": sum(1 for r in rets if r > 0),
            "avg_ret_pct": round(sum(rets) / len(rets), 2) if rets else None,
        })
    return out


def _date_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return pd.Timestamp(value).date().isoformat()  # type: ignore[arg-type]


def _sr(value: object, ndigits: int) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(number, ndigits) if math.isfinite(number) else None
