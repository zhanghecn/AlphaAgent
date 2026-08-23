""">3板高板研究 Step4: 候选池终验——逐月收益序列 + 正月占比 + >3板捕获率.

候选:
S1  = 价<10 + 换手<8 + 昨涨<=0 + 高开<8%(扫描最优之一)
S1b = 价<10 + 换手<8 + 昨涨-5~1 + 高开<8%(平盘带微调)
QL  = 潜龙8条件池(现产品, 参照系)
S2  = 潜龙条件但阳线翻平/阴: 昨涨-5~0 替换 0~5, 其余同(低>MA20/乖离<=12/换手<8/市值<1200/价<12)
S3  = S1 ∪ QL(并集, 放量+保 edge)
S1+门 = S1 且 近10日池内信号均收>0(自适应闸门)
每池输出: 训/验/全 的 n/均收/胜率/正月占比/最差月均/月均笔数/>3板率,
       >3板赢家捕获率(该池抓到的>=4板票占全市场非一字>=4板票比例),
       全期逐月(月,n,均)序列.
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
            "正收益月占比": round(float((m["mean"] > 0).mean()), 3),
            "负月数": int((m["mean"] <= 0).sum()), "月数": int(len(m)),
            "最差月均": round(float(m["mean"].min()) * 100, 2),
            ">3板率%": round(float(df.win4.mean()) * 100, 2)}


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, turnover_rate, change_pct
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
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20"]:
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
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
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
    ev["win4"] = k.loc[ev.index] >= 4
    ev["is_train"] = ev.trade_date < TRAIN_END

    # >3板赢家全集(非一字触发即被抓可能性)
    winners = ev[ev.win4]
    wkey_all = set(zip(winners.vt_symbol, winners.trade_date))

    pools = {}
    pools["S1 价10+换8+昨涨<=0+高开<8"] = (
        (ev.close_price_tm1 < 10) & (ev.turnover_rate_tm1 < 8)
        & (ev.change_pct_tm1 <= 0) & (ev.gap_open < 0.08))
    pools["S1b 昨涨-5~1微调"] = (
        (ev.close_price_tm1 < 10) & (ev.turnover_rate_tm1 < 8)
        & (ev.change_pct_tm1.between(-5, 1)) & (ev.gap_open < 0.08))
    ql = ((ev.change_pct_tm1.between(0, 5)) & (ev.low_price_tm1 > ev.ma20_tm1)
          & (ev.dist_ma20 <= 0.12) & (ev.turnover_rate_tm1 < 8)
          & (ev.cap_yi < 1200) & (ev.close_price_tm1 < 12))
    pools["QL 潜龙现产品"] = ql
    pools["S2 潜龙翻阴(昨涨-5~0)"] = (
        (ev.change_pct_tm1.between(-5, 0)) & (ev.low_price_tm1 > ev.ma20_tm1)
        & (ev.dist_ma20 <= 0.12) & (ev.turnover_rate_tm1 < 8)
        & (ev.cap_yi < 1200) & (ev.close_price_tm1 < 12))
    pools["S3 S1∪QL"] = pools["S1 价10+换8+昨涨<=0+高开<8"] | ql

    out = {}
    for name, mask in pools.items():
        sub = ev[mask]
        caught = set(zip(sub.vt_symbol, sub.trade_date))
        wsub = winners[[(s, d) in caught for s, d in zip(winners.vt_symbol, winners.trade_date)]]
        rec = {"训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
               "全": month_stats(sub),
               ">3板捕获率": round(len(wsub) / max(len(winners), 1), 3)}
        m = sub.groupby("month")["ret"].agg(["count", "mean"])
        neg = {str(ix): round(float(rr["mean"]) * 100, 2)
               for ix, rr in m.iterrows() if rr["mean"] <= 0}
        rec["负月明细"] = neg
        out[name] = rec

    # S1 + 自适应闸门(近10日池内均收>0)
    s1 = pools["S1 价10+换8+昨涨<=0+高开<8"]
    sub = ev[s1].copy()
    sig_day = sub.groupby("trade_date")["ret"].agg(["count", "mean"]).sort_index()
    all_days = pd.Index(sorted(ev.trade_date.unique()))
    day_list = list(all_days)
    gate = {}
    for i, d in enumerate(day_list):
        if i < 11:
            continue
        win = sig_day.loc[sig_day.index.isin(day_list[i - 10:i])]
        if not len(win):
            gate[d] = (0, np.nan)
        else:
            gate[d] = (int(win["count"].sum()),
                       float(np.average(win["mean"], weights=win["count"])))
    sub["gate_n"] = sub.trade_date.map(lambda d: gate.get(d, (0, np.nan))[0])
    sub["gate_ret"] = sub.trade_date.map(lambda d: gate.get(d, (0, np.nan))[1])
    for th_name, m2 in [("门均收>0", (sub.gate_n >= 3) & (sub.gate_ret > 0)),
                        ("门均收>-0.5%", (sub.gate_n >= 3) & (sub.gate_ret > -0.005))]:
        g2 = sub[m2]
        rec = {"训": month_stats(g2[g2.is_train]), "验": month_stats(g2[~g2.is_train]),
               "全": month_stats(g2)}
        m = g2.groupby("month")["ret"].agg(["count", "mean"])
        rec["负月明细"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                          for ix, rr in m.iterrows() if rr["mean"] <= 0}
        out[f"S1+{th_name}"] = rec

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
