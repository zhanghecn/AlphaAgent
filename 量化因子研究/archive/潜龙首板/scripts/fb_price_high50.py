"""≥50元 × 多头排列 机构底盘检验.

多头定义: ma5>ma10>ma20 且 收盘>ma20 (昨收口径, T-1日数据).
加强: +ma20上行(ma20>5日前) +收盘>ma5.

回答:
Q1 ≥50×多头 vs ≥50裸: 双段是否正, t检验
Q2 交互: 多头对 <12 带加多少分 vs 对 ≥50 带加多少分 —— 是否机构带专属适配
Q3 ≥50×多头 带内再扫: 高开/换手/市值/距MA20, 找存活口袋
Q4 候选组合双段验证
"""
from __future__ import annotations

import os, json
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
    for w in (5, 10, 20):
        bars[f"ma{w}"] = g["close_price"].transform(lambda s, w=w: s.rolling(w).mean())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct",
                "ma5", "ma10", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars["ma20_tm6"] = g["ma20"].shift(6)
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
    # 多头排列(T-1)
    bars["bull"] = ((bars.ma5_tm1 > bars.ma10_tm1) & (bars.ma10_tm1 > bars.ma20_tm1)
                    & (bars.close_price_tm1 > bars.ma20_tm1))
    bars["bull_up"] = bars["bull"] & (bars.ma20_tm1 > bars.ma20_tm6)  # 加强: ma20上行

    base = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"]
                & (~bars["lu_tm1"]) & ~bars["oneword_strict"]].copy()
    k = base["streak_h"].fillna(0).astype(int).clip(0, 6)
    eo = np.full(len(base), np.nan)
    for kk in range(2, 7):
        eo = np.where((k == kk).values, base[f"open_p{kk}"].values, eo)
    eo = np.where(~base["sealed"] | (k < 2), base["open_p1"].values, eo)
    base["ret"] = pd.Series(eo / base["entry"].values - 1, index=base.index)
    base["month"] = base["trade_date"].dt.to_period("M").astype(str)
    disc = (base["open_p1"] / base["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (base[f"open_p{kk}"].values / base[f"close_p{kk-1}"].values - 1).__abs__() > 0.11
    base = base[~pd.Series(disc, index=base.index).fillna(False)]
    base["is_train"] = base.trade_date < pd.Timestamp(TRAIN_END)
    px = base["close_price_tm1"]

    def st(sub):
        r = sub["ret"].dropna()
        if len(r) < 30:
            return {"n": len(r)}
        tr = sub.loc[sub.is_train, "ret"].dropna()
        va = sub.loc[~sub.is_train, "ret"].dropna()
        ex = sub.loc[sub.month != "2024-09", "ret"].dropna()
        return {"n": len(r), "全": round(float(r.mean()) * 100, 2),
                "训": round(float(tr.mean()) * 100, 2),
                "验": round(float(va.mean()) * 100, 2) if len(va) else None,
                "剔2409": round(float(ex.mean()) * 100, 2),
                "胜率": round(float((r > 0).mean()), 3),
                "封板率": round(float(sub.sealed.mean()), 3),
                "连板率": round(float((sub.streak_h.fillna(0) >= 2).mean()), 3)}

    out = {}
    h = base[px >= 50]
    lo = base[px < 12]
    # Q1 ≥50: 裸 vs 多头 vs 强多头
    out["Q1_≥50"] = {"裸": st(h), "多头": st(h[h.bull]), "强多头(ma20上行)": st(h[h.bull_up]),
                     "非多头": st(h[~h.bull])}
    a, b = h.loc[h.bull, "ret"].dropna(), h["ret"].dropna()
    if len(a) > 30:
        t, p = sstats.ttest_ind(a, b, equal_var=False)
        out["Q1_t_多头vs裸"] = {"n": len(a), "t": round(float(t), 2), "p": round(float(p), 4)}
    # Q2 交互: <12 带对照
    out["Q2_<12对照"] = {"裸": st(lo), "多头": st(lo[lo.bull]), "非多头": st(lo[~lo.bull])}
    # 交互增量 = 多头-非多头, 两带对比
    for lb, sub in [("≥50", h), ("<12", lo)]:
        d_bull = sub.loc[sub.bull, "ret"].mean() - sub.loc[~sub.bull, "ret"].mean()
        d_bull_v = (sub.loc[sub.bull & ~sub.is_train, "ret"].mean()
                    - sub.loc[~sub.bull & ~sub.is_train, "ret"].mean())
        out[f"Q2_{lb}_多头增量"] = {"全": round(float(d_bull) * 100, 2),
                                   "验": round(float(d_bull_v) * 100, 2)}
    # Q3 ≥50×多头 带内再扫
    hb = h[h.bull]
    out["Q3_≥50×多头_n"] = len(hb)
    out["Q3_带内"] = {
        "高开": {"<0": st(hb[hb.gap_open < 0]), "0~2": st(hb[hb.gap_open.between(0, 0.02)]),
                 "2~6": st(hb[hb.gap_open.between(0.02, 0.06)]), ">=6": st(hb[hb.gap_open >= 0.06])},
        "换手": {"<3": st(hb[hb.turnover_rate_tm1 < 3]),
                 "3~8": st(hb[hb.turnover_rate_tm1.between(3, 8)]),
                 ">=8": st(hb[hb.turnover_rate_tm1 >= 8])},
        "市值": {"<300": st(hb[hb.cap_yi < 300]), "300~1200": st(hb[hb.cap_yi.between(300, 1200)]),
                 ">=1200": st(hb[hb.cap_yi >= 1200])},
        "距MA20": {"0~6": st(hb[hb.dist_ma20.between(0, 0.06)]),
                   "6~15": st(hb[hb.dist_ma20.between(0.06, 0.15)]),
                   ">=15": st(hb[hb.dist_ma20 >= 0.15])},
        "昨涨幅": {"阴": st(hb[hb.change_pct_tm1 < 0]),
                   "0~5": st(hb[hb.change_pct_tm1.between(0, 5)]),
                   ">=5": st(hb[hb.change_pct_tm1 >= 5])},
    }
    # Q4 候选组合
    c1 = hb[(hb.gap_open.between(0, 0.06)) & (hb.turnover_rate_tm1 < 8)
            & (hb.change_pct_tm1.between(0, 5)) & (hb.cap_yi < 1200)]
    out["Q4_组合_多头+平开小高开+阳0~5+换手<8+市值<1200"] = st(c1)
    if len(c1) > 30:
        t, p = sstats.ttest_ind(c1["ret"].dropna(), h["ret"].dropna(), equal_var=False)
        out["Q4_t_组合vs裸"] = {"n": len(c1), "t": round(float(t), 2), "p": round(float(p), 4)}
    # Q5 趋势回踩口袋: 多头×昨日阴线×距MA20 6~15% (Q3 唯一双段皆正的交叉)
    p1 = hb[hb.change_pct_tm1 < 0]
    p2 = p1[p1.dist_ma20.between(0.06, 0.15)]
    p3 = p2[p2.gap_open < 0.06]
    p4 = p2[p2.gap_open < 0.02]
    out["Q5_多头×阴线"] = st(p1)
    out["Q5_多头×阴线×dist6~15"] = st(p2)
    out["Q5_再×高开<6"] = st(p3)
    out["Q5_再×高开<2"] = st(p4)
    # 对照: 同形态在 <12 带
    q = lo[lo.bull & (lo.change_pct_tm1 < 0) & lo.dist_ma20.between(0.06, 0.15)]
    out["Q5_同形态_<12对照"] = st(q)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
