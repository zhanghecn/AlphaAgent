""">=3板好票研究 终章: 极简条件组 + 删除测试(归纳法产物, 可交易口径全量经济验证).

候选关键条件(每条来自 Step1~3 的归纳证据, 一族一条):
  T 趋势位置: 多头排列(收>ma5>ma10>ma20) —— P6 lift 1.22, 好票率 7.3% vs 5.6%
  S 小市值: <50亿 —— lift 1.20, 7.2% vs 5.1%
  P 低价: <8元 —— lift 1.18, 7.1% vs 5.4%
  V 首板不爆量: 首板日量/前5日均量 < 1.5 —— 量比<1 档好票率 8.4%
对照条件(归纳中被判弱/反向, 不进组合只验伤):
  昨涨0~5收阳(lift 1.08, 错杀55%好票) / pos60低位(反向) / 前10日涨停(弱)

验证口径(可交易): 触+8%买入, 高开>=8%不做, 断板/次日开盘卖, 0.5%滑点, 剔一字/除权.
输出: 各组合的 训/验/全 均收/胜率/正月占比/月均笔数/>=3板捕获率 + 逐月序列;
      删除测试(全组合逐条删); 单条测试(逐条单独).
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = pd.Timestamp("2025-07-01")


def month_stats(df):
    if not len(df):
        return None
    m = df.groupby("month")["ret"].agg(["count", "mean"])
    return {"n": len(df), "月均笔数": round(float(m["count"].mean()), 1),
            "均收": round(float(df.ret.mean()) * 100, 2),
            "胜率": round(float((df.ret > 0).mean()), 3),
            "正月占比": round(float((m["mean"] > 0).mean()), 3),
            "负月": int((m["mean"] <= 0).sum()), "月数": int(len(m)),
            "最差月均": round(float(m["mean"].min()) * 100, 2)}


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count
               FROM stock_limit_up_daily WHERE is_limit_up""", conn)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

    lu = lu.copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_m = lu[lu.vt_symbol.isin(main_syms)]
    lu_all = lu_m.sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu_key = lu_m.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma5", "ma10", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["vol_ratio_T"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["bull_align"] = ((bars["close_price_tm1"] > bars["ma5_tm1"])
                          & (bars["ma5_tm1"] > bars["ma10_tm1"])
                          & (bars["ma10_tm1"] > bars["ma20_tm1"]))
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & (~bars["lu_tm1"])
              & ~bars["oneword_strict"]].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 8)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["lu_T"] | (k < 2), ev["open_p1"].values, eo)
    ev["entry"] = np.where(ev["open_price"] > ev["trigger_price"],
                           ev["open_price"], ev["trigger_price"]) * (1 + SLIP)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)].dropna(subset=["ret"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["good3"] = k.loc[ev.index] >= 3
    ev["is_train"] = ev.trade_date < TRAIN_END

    # 可交易基底: 高开<8%(规则) —— 所有组合都含此交易规则, 不算"条件"
    base = ev.gap_open < 0.08
    winners = ev[ev.good3 & base]
    wkey_all = set(zip(winners.vt_symbol, winners.trade_date))

    COND = {
        "T多头": ev["bull_align"],
        "S市值50": ev.cap_yi < 50,
        "P价8": ev.close_price_tm1 < 8,
        "V量比<1.5": ev.vol_ratio_T < 1.5,
        "V量比<2.5": ev.vol_ratio_T < 2.5,
    }

    def evaluate(mask, label):
        sub = ev[mask & base]
        if not len(sub):
            return {"label": label}
        caught = set(zip(sub.vt_symbol, sub.trade_date))
        n_caught = len([1 for kk_ in wkey_all if kk_ in caught])
        rec = {"label": label,
               "训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
               "全": month_stats(sub),
               ">=3板率%": round(float(sub.good3.mean()) * 100, 2),
               ">=3板捕获率": round(n_caught / max(len(wkey_all), 1), 3)}
        m = sub.groupby("month")["ret"].agg(["count", "mean"])
        rec["负月明细"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                          for ix, rr in m.iterrows() if rr["mean"] <= 0}
        return rec

    out = {"参照_仅交易规则(高开<8)": evaluate(base & pd.Series(True, index=ev.index), "裸触发")}
    # 单条
    for name, m in COND.items():
        out[f"单条_{name}"] = evaluate(m, name)
    # 全组合(T+S+P+V)
    full = COND["T多头"] & COND["S市值50"] & COND["P价8"] & COND["V量比<1.5"]
    out["组合_T+S+P+V1.5"] = evaluate(full, "T+S+P+V")
    full2 = COND["T多头"] & COND["S市值50"] & COND["P价8"] & COND["V量比<2.5"]
    out["组合_T+S+P+V2.5"] = evaluate(full2, "T+S+P+V2.5")
    out["组合_T+S+P(无V)"] = evaluate(COND["T多头"] & COND["S市值50"] & COND["P价8"], "T+S+P")
    out["组合_S+P(无T无V)"] = evaluate(COND["S市值50"] & COND["P价8"], "S+P")
    out["组合_T+S(无P无V)"] = evaluate(COND["T多头"] & COND["S市值50"], "T+S")
    out["组合_T+P(无S无V)"] = evaluate(COND["T多头"] & COND["P价8"], "T+P")
    # 删除测试: 全组合逐条删
    for name in ("T多头", "S市值50", "P价8", "V量比<1.5"):
        m = pd.Series(True, index=ev.index)
        for n2, mm in COND.items():
            if n2 != name and n2 in ("T多头", "S市值50", "P价8", "V量比<1.5"):
                m &= mm
        out[f"删除测试_无{name}"] = evaluate(m, f"无{name}")

    # top组合逐月
    for key in ("组合_T+S+P+V1.5", "组合_T+S+P(无V)"):
        rec = out.get(key)
        if not rec:
            continue
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
