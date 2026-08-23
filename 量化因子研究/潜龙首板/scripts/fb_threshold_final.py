"""阈值定论扫描: 股价/市值 每个候选阈值的全段+双段+t检验; 输出确定性结论用数字.

回答:
Q1 股价阈值: <8/<10/<12/<15/<20/<25/不限 哪个最优? <12 vs 12~25 差异是否统计显著?
Q2 市值阈值: <300/<600/<800/<1000/<1200/不限 差异显著性?
Q3 gap>=8% 可买组 vs 2~6%gap组 差异显著性(合并日线+分钟证据).
Q4 时段: 午后13-14点 vs 上午 差异显著性(分钟样本).
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg
from scipy import stats as sstats

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = "2025-07-01"


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word
               FROM stock_limit_up_daily""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    cap_map = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"],
                             bars["open_price"], bars["trigger_price"]) * (1 + SLIP)
    bars["sealed"] = bars["lu_T"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999
    pool = ((~bars["lu_tm1"]) & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"]) & (bars["dist_ma20"] <= 0.12)
            & (bars["turnover_rate_tm1"] < 8) & (bars["cap_yi"] < 1200))
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool & ~bars["oneword_strict"]].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    exit_open = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        exit_open = np.where((k == kk).values, ev[f"open_p{kk}"].values, exit_open)
    exit_open = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, exit_open)
    ev["ret"] = pd.Series(exit_open / ev["entry"].values - 1, index=ev.index)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (ev[f"open_p{kk}"] / ev[f"close_p{kk-1}"] - 1).abs() > 0.11
    ev = ev[~disc.fillna(False)]
    ev["is_train"] = ev.trade_date < pd.Timestamp(TRAIN_END)
    print(f"n={len(ev):,}", file=sys.stderr)

    out = {}

    def row(mask, label):
        sub = ev[mask.fillna(False)]
        r = sub["ret"].dropna()
        tr = sub[sub.is_train]["ret"].dropna()
        va = sub[~sub.is_train]["ret"].dropna()
        return {"label": label, "n": len(r),
                "all": round(float(r.mean()) * 100, 2) if len(r) else None,
                "train": round(float(tr.mean()) * 100, 2) if len(tr) else None,
                "valid": round(float(va.mean()) * 100, 2) if len(va) else None,
                "win": round(float((r > 0).mean()), 3) if len(r) else None}

    # Q1 股价阈值扫描
    out["price_scan"] = [row(ev.close_price_tm1 < t, f"股价<{t}元")
                         for t in (8, 10, 12, 15, 20, 25, 99999)]
    # t检验: <12 vs >=12
    a = ev[ev.close_price_tm1 < 12]["ret"].dropna()
    b = ev[ev.close_price_tm1 >= 12]["ret"].dropna()
    t, p = sstats.ttest_ind(a, b, equal_var=False)
    out["price_ttest_lt12_vs_ge12"] = {"n_a": len(a), "n_b": len(b),
                                       "mean_a": round(float(a.mean()) * 100, 2),
                                       "mean_b": round(float(b.mean()) * 100, 2),
                                       "t": round(float(t), 2), "p": round(float(p), 5)}
    # <20 vs >=20
    a2 = ev[ev.close_price_tm1 < 20]["ret"].dropna()
    b2 = ev[ev.close_price_tm1 >= 20]["ret"].dropna()
    t2, p2 = sstats.ttest_ind(a2, b2, equal_var=False)
    out["price_ttest_lt20_vs_ge20"] = {"n_a": len(a2), "n_b": len(b2),
                                       "mean_a": round(float(a2.mean()) * 100, 2),
                                       "mean_b": round(float(b2.mean()) * 100, 2),
                                       "t": round(float(t2), 2), "p": round(float(p2), 5)}

    # Q2 市值阈值扫描
    out["cap_scan"] = [row(ev.cap_yi < t, f"市值<{t}亿")
                       for t in (300, 600, 800, 1000, 1200, 999999)]
    ac = ev[ev.cap_yi < 1200]["ret"].dropna()
    # 当前 ev 已经 cap<1200, 需全体对比: 重算无市值限制的触发集
    pool_nc = ((~bars["lu_tm1"]) & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
               & (bars["low_price_tm1"] > bars["ma20_tm1"]) & (bars["dist_ma20"] <= 0.12)
               & (bars["turnover_rate_tm1"] < 8))
    ev_nc = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool_nc & ~bars["oneword_strict"]].copy()
    k = ev_nc["streak_h"].fillna(0).astype(int).clip(0, 6)
    eo = np.full(len(ev_nc), np.nan)
    for kk in range(2, 7):
        eo = np.where((k == kk).values, ev_nc[f"open_p{kk}"].values, eo)
    eo = np.where(~ev_nc["sealed"] | (k < 2), ev_nc["open_p1"].values, eo)
    ev_nc["ret"] = pd.Series(eo / ev_nc["entry"].values - 1, index=ev_nc.index)
    a3 = ev_nc[ev_nc.cap_yi < 1200]["ret"].dropna()
    b3 = ev_nc[ev_nc.cap_yi >= 1200]["ret"].dropna()
    t3, p3 = sstats.ttest_ind(a3, b3, equal_var=False)
    out["cap_ttest_lt1200_vs_ge1200"] = {"n_a": len(a3), "n_b": len(b3),
                                         "mean_a": round(float(a3.mean()) * 100, 2),
                                         "mean_b": round(float(b3.mean()) * 100, 2),
                                         "t": round(float(t3), 2), "p": round(float(p3), 5)}
    # 500~1200亿组单独看(用户关心的中大盘)
    mid = ev_nc[ev_nc.cap_yi.between(500, 1200)]["ret"].dropna()
    small = ev_nc[ev_nc.cap_yi < 500]["ret"].dropna()
    t4, p4 = sstats.ttest_ind(small, mid, equal_var=False)
    out["cap_ttest_lt500_vs_500to1200"] = {"n_a": len(small), "n_b": len(mid),
                                           "mean_small": round(float(small.mean()) * 100, 2),
                                           "mean_mid": round(float(mid.mean()) * 100, 2),
                                           "t": round(float(t4), 2), "p": round(float(p4), 5)}

    # Q3 gap: 2~6% vs >=8%可买(open<limit) —— 日线大样本
    g26 = ev[(ev.gap_open >= 0.02) & (ev.gap_open < 0.06)]["ret"].dropna()
    g8b = ev[(ev.gap_open >= 0.08)]["ret"].dropna()  # 已剔真一字
    t5, p5 = sstats.ttest_ind(g26, g8b, equal_var=False)
    out["gap_ttest_2to6_vs_ge8_buyable"] = {"n_a": len(g26), "n_b": len(g8b),
                                            "mean_26": round(float(g26.mean()) * 100, 2),
                                            "mean_8": round(float(g8b.mean()) * 100, 2),
                                            "t": round(float(t5), 2), "p": round(float(p5), 5)}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
