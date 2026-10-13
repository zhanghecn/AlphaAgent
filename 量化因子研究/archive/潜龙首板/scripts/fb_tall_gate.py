""">3板高板研究 Step5: S1 池 × 市场广度闸门(抓大盘级崩盘月),终版候选.

闸门全部用 T-1 及之前数据(无前视):
B1 昨日全市场(主板非ST)涨跌中位 > -1.5%
B2 昨日上涨家数占比 > 30%
B3 近5日涨跌中位均值 > -0.5%
B4 昨日涨停家数 >= 20
B5 昨日封板率 >= 55%(涨停/(涨停+炸板))
对 S1 与 S3(S1∪潜龙) 分别叠加, 报训/验/全 + 负月明细.
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
            "最差月均": round(float(m["mean"].min()) * 100, 2)}


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, touched_limit
               FROM stock_limit_up_daily""", conn)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

    lu = lu.copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_m = lu[lu.vt_symbol.isin(main_syms)]
    lu_all = lu_m[lu_m.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
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
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)

    # 市场广度日序列(主板非ST全样本)
    day = bars.groupby("trade_date").agg(
        med_chg=("change_pct", "median"),
        up_ratio=("change_pct", lambda s: (s > 0).mean())).sort_index()
    lu_m2 = lu_m.copy()
    lu_m2["is_zha"] = (~lu_m2.is_limit_up) & lu_m2.touched_limit.fillna(False)
    dlu = lu_m2.groupby("trade_date").agg(
        lu_n=("is_limit_up", "sum"), zha_n=("is_zha", "sum")).sort_index()
    day = day.join(dlu)
    day["seal_rate"] = day.lu_n / (day.lu_n + day.zha_n)
    day["med_chg_5"] = day["med_chg"].rolling(5).mean()
    prev = day.shift(1).add_suffix("_tm1")   # 昨日市场状态, T日用 T-1 值(无前视)

    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars = bars.join(prev, on="trade_date")

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
    ev["is_train"] = ev.trade_date < TRAIN_END

    s1 = ((ev.close_price_tm1 < 10) & (ev.turnover_rate_tm1 < 8)
          & (ev.change_pct_tm1 <= 0) & (ev.gap_open < 0.08))
    ql = ((ev.change_pct_tm1.between(0, 5)) & (ev.low_price_tm1 > ev.ma20_tm1)
          & (ev.dist_ma20 <= 0.12) & (ev.turnover_rate_tm1 < 8)
          & (ev.cap_yi < 1200) & (ev.close_price_tm1 < 12))
    pools = {"S1": s1, "S3(S1∪QL)": s1 | ql}

    GATES = {
        "B1 昨中位>-1.5%": ev.med_chg_tm1 > -0.015,
        "B2 昨上涨占比>30%": ev.up_ratio_tm1 > 0.30,
        "B3 近5日中位>-0.5%": ev.med_chg_5_tm1 > -0.005,
        "B4 昨涨停>=20": ev.lu_n_tm1 >= 20,
        "B5 昨封板率>=55%": ev.seal_rate_tm1 >= 0.55,
    }

    out = {}
    for pname, pmask in pools.items():
        for gname, gmask in GATES.items():
            sub = ev[pmask & gmask]
            if not len(sub):
                continue
            rec = {"训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
                   "全": month_stats(sub)}
            m = sub.groupby("month")["ret"].agg(["count", "mean"])
            rec["负月"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                          for ix, rr in m.iterrows() if rr["mean"] <= 0}
            out[f"{pname} + {gname}"] = rec
        # 组合门: B2且B5
        sub = ev[pmask & GATES["B2 昨上涨占比>30%"] & GATES["B5 昨封板率>=55%"]]
        rec = {"训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
               "全": month_stats(sub)}
        m = sub.groupby("month")["ret"].agg(["count", "mean"])
        rec["负月"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                      for ix, rr in m.iterrows() if rr["mean"] <= 0}
        out[f"{pname} + B2+B5"] = rec

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
