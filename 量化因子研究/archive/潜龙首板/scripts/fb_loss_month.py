"""亏损月/低收益月专题: 月内好票差票对比 + 市场环境 + 候选条件.

分组: LOSS月 = 月内平均每笔收益 < 1%; GOOD月 >= 1%.
输出:
1. 全部41个月的市场环境表(广度/最高板/炸板/涨停数/涨跌中位)
2. LOSS月内: 盈利票 vs 亏损票 特征中位数 + 分箱 lift
3. 同样特征在 GOOD月 的表现(判别力是否只在差月有效)
4. LOSS月典型好票/差票明细各15笔
5. 候选条件: 加在7条池上, 看 LOSS月/GOOD月 各自收益变化
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word, touched_limit
               FROM stock_limit_up_daily""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    cap_map = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()
    name_map = stocks.set_index("vt_symbol")["name"].to_dict()

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])

    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["ret60"] = g["close_price"].transform(lambda s: s / s.shift(60) - 1)
    bars["high250"] = g["high_price"].transform(lambda s: s.rolling(250, min_periods=60).max())
    bars["open_p1"] = g["open_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
    for col in ["close_price", "open_price", "low_price", "turnover_rate", "change_pct",
                "ma20", "ret5", "ret60", "high250"]:
        bars[col + "_tm1"] = g[col].shift(1)

    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars["lu_flag"] = bars["lu_T"]
    bars["lu_cnt20"] = g["lu_flag"].transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())

    # streak
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    # 市场环境日序列(全部由个股数据自建)
    day = bars.groupby("trade_date").agg(
        med_chg=("change_pct", "median"),
        up_ratio=("change_pct", lambda s: (s > 0).mean()),
        up5_ratio=("change_pct", lambda s: (s >= 5).mean()),
    ).sort_index()
    lu["is_zha"] = (~lu.is_limit_up) & lu.touched_limit
    dlu = lu.groupby("trade_date").agg(
        lu_n=("is_limit_up", "sum"),
        max_h=("limit_up_count", "max"),
        zha_n=("is_zha", "sum")).sort_index()
    day = day.join(dlu)
    day["seal_rate"] = day.lu_n / (day.lu_n + day.zha_n)
    prev = day.shift(1).add_suffix("_tm1")
    bars = bars.join(prev, on="trade_date")

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"],
                             bars["open_price"], bars["trigger_price"]) * (1 + SLIP)
    bars["sealed"] = bars["lu_T"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    bars["near_high250"] = bars["close_price_tm1"] >= bars["high250_tm1"] * 0.97

    pool = ((~bars["lu_tm1"])
            & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"])
            & (bars["dist_ma20"] <= 0.12)
            & (bars["turnover_rate_tm1"] < 8)
            & (bars["cap_yi"] < 1200))

    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool].copy()

    # 卖出模拟
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    exit_open = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        sel = (k == kk).values
        exit_open = np.where(sel, ev[f"open_p{kk}"].values, exit_open)
    exit_open = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, exit_open)
    ev["ret"] = pd.Series(exit_open / ev["entry"].values - 1, index=ev.index)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    ev["name"] = ev.vt_symbol.map(name_map)

    # 月份分组
    mret = ev.groupby("month")["ret"].mean()
    loss_months = set(mret[mret < 0.01].index)  # <1%
    ev["loss_month"] = ev["month"].isin(loss_months)

    # 1) 月度环境表
    env = day[[c for c in day.columns if not c.endswith("_tm1")]].copy()
    env_m = env.groupby(env.index.to_period("M").astype(str)).agg(
        med_chg=("med_chg", "mean"), up5=("up5_ratio", "mean"),
        max_h=("max_h", "mean"), zha=("zha_n", "mean"), lu_n=("lu_n", "mean"),
        seal_rate=("seal_rate", "mean"))
    env_m["ret"] = mret
    env_m["n"] = ev.groupby("month").size()
    env_m = env_m.dropna(subset=["ret"])
    rows = []
    for mth, r in env_m.iterrows():
        rows.append({"month": str(mth), "n": int(r.n), "ret": round(r.ret * 100, 2),
                     "med_chg": round(r.med_chg * 100, 2), "up5": round(r.up5 * 100, 2),
                     "max_h": round(r.max_h, 1), "zha": round(r.zha, 0),
                     "lu_n": round(r.lu_n, 0), "seal_rate": round(r.seal_rate, 2),
                     "LOSS": str(mth) in loss_months})
    out = {"month_env": rows}

    # 2) LOSS月内 好票(赚) vs 差票(亏) 特征对比
    L = ev[ev.loss_month]
    G = ev[~ev.loss_month]
    feats = {"gap_open": 100, "change_pct_tm1": 1, "turnover_rate_tm1": 1, "dist_ma20": 100,
             "ret5_tm1": 100, "ret60_tm1": 100, "lu_cnt20": 1, "cap_yi": 1,
             "up5_ratio_tm1": 100, "max_h_tm1": 1, "zha_n_tm1": 1, "seal_rate_tm1": 100,
             "med_chg_tm1": 100}

    def cmp_block(df, label):
        win = df[df.ret > 0]
        los = df[df.ret <= 0]
        r = {"label": label, "n": len(df), "n_win": len(win), "n_los": len(los),
             "ret": round(df.ret.mean() * 100, 2), "seal": round(df.sealed.mean(), 3)}
        for f, mul in feats.items():
            r[f"w_{f}"] = round(float(win[f].median()) * mul, 2) if len(win) else None
            r[f"l_{f}"] = round(float(los[f].median()) * mul, 2) if len(los) else None
        return r

    out["cmp_LOSS_month"] = cmp_block(L, "亏损/低收益月")
    out["cmp_GOOD_month"] = cmp_block(G, "盈利月")

    # 3) 候选条件: 加在池上, 分别看 LOSS月/GOOD月 效果
    def eff(mask_extra, label):
        sub = ev[mask_extra]
        l = sub[sub.loss_month]
        gg = sub[~sub.loss_month]
        return {"label": label,
                "LOSS_n": len(l), "LOSS_ret": round(l.ret.mean() * 100, 2) if len(l) > 5 else None,
                "GOOD_n": len(gg), "GOOD_ret": round(gg.ret.mean() * 100, 2) if len(gg) > 5 else None,
                "ALL_ret": round(sub.ret.mean() * 100, 2) if len(sub) > 5 else None}

    base = pd.Series(True, index=ev.index)
    cands = [
        ("原7条", base),
        ("+gap<=0(低开/平开)", ev["gap_open"] <= 0.001),
        ("+gap>=2%", ev["gap_open"] >= 0.02),
        ("+换手2~6%", ev["turnover_rate_tm1"].between(2, 6)),
        ("+距MA20 2~10%", ev["dist_ma20"].between(0.02, 0.10)),
        ("+前60日<10%", ev["ret60_tm1"] < 0.10),
        ("+前60日<0(中期下跌)", ev["ret60_tm1"] < 0),
        ("+非年新高", ~ev["near_high250"]),
        ("+近20日无涨停", ev["lu_cnt20"] == 0),
        ("+市值<300亿", ev["cap_yi"] < 300),
        ("+昨日涨跌中位>0", ev["med_chg_tm1"] > 0),
        ("+昨日涨停>=30家", ev["lu_n_tm1"] >= 30),
        ("+昨日最高板>=4", ev["max_h_tm1"] >= 4),
        ("+昨日封板率>=65%", ev["seal_rate_tm1"] >= 0.65),
    ]
    out["candidates"] = [eff(m, lb) for lb, m in cands]

    # 4) LOSS月 典型明细
    Ls = L.sort_values("trade_date")
    cols = ["trade_date", "name", "ret", "sealed", "streak_h", "gap_open", "turnover_rate_tm1",
            "dist_ma20", "ret60_tm1", "cap_yi", "med_chg_tm1", "max_h_tm1"]
    win_ex = Ls[Ls.ret > 0].nlargest(15, "ret")[cols]
    los_ex = Ls[Ls.ret <= -0.03].nsmallest(15, "ret")[cols]
    for df in (win_ex, los_ex):
        df["trade_date"] = df.trade_date.dt.strftime("%m-%d")
        df["ret"] = (df.ret * 100).round(1)
        df["gap_open"] = (df.gap_open * 100).round(1)
        df["dist_ma20"] = (df.dist_ma20 * 100).round(1)
        df["ret60_tm1"] = (df.ret60_tm1 * 100).round(0)
        df["cap_yi"] = df.cap_yi.round(0)
        df["med_chg_tm1"] = (df.med_chg_tm1 * 100).round(2)
    out["LOSS_win_examples"] = win_ex.to_dict("records")
    out["LOSS_los_examples"] = los_ex.to_dict("records")

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
