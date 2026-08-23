"""≥50×多头 带内 好票(连板) vs 差票 基本盘对比.

好票 = streak_h>=2 (走出连板); 中 = 封板未连; 差 = 未封板.
对比 T-1 盘前特征(无未来函数): 连续小阳/阳线密度/前期涨幅/均线距离/换手结构/
量能/振幅/前60日涨停史/新高距离/市值/股价 + T日高开.
输出: 三组均值中位+t检验; 强特征分桶单调性; 好票/差票实例清单.
"""
from __future__ import annotations

import os, json
import pandas as pd
import numpy as np
import psycopg
from scipy import stats as sstats

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
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word
               FROM stock_limit_up_daily""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    name_map = stocks.set_index("vt_symbol")["name"].to_dict()
    cap_map = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()
    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    for w in (5, 10, 20, 60):
        bars[f"ma{w}"] = g["close_price"].transform(lambda s, w=w: s.rolling(w).mean())
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_flag"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values

    # ---- 盘前特征(当日口径, 之后统一 shift(1) 到 T-1) ----
    bars["sm_yang"] = (bars.change_pct >= 0) & (bars.change_pct <= 3)
    reset = (~bars["sm_yang"]).cumsum()
    bars["sm_yang_consec"] = (bars["sm_yang"].groupby([bars.vt_symbol, reset]).cumcount()
                              * bars["sm_yang"])
    bars["yang_cnt10"] = g["change_pct"].transform(
        lambda s: (s > 0).rolling(10).sum())
    for k_ in (5, 10, 20, 60):
        bars[f"ret{k_}"] = g["close_price"].transform(lambda s, k_=k_: s / s.shift(k_) - 1)
    bars["dist_ma60"] = bars.close_price / bars.ma60 - 1
    bars["hi60"] = g["high_price"].transform(lambda s: s.rolling(60).max())
    bars["newhigh60_dist"] = bars.close_price / bars.hi60 - 1
    bars["to5"] = g["turnover_rate"].transform(lambda s: s.rolling(5).mean())
    bars["to20"] = g["turnover_rate"].transform(lambda s: s.rolling(20).mean())
    bars["to_trend"] = bars.to5 / bars.to20
    bars["vol5"] = g["volume"].transform(lambda s: s.rolling(5).mean())
    bars["vol_ratio"] = bars.volume / bars.vol5
    bars["amp"] = (bars.high_price - bars.low_price) / g["close_price"].shift(1)
    bars["amp5"] = bars.groupby("vt_symbol")["amp"].transform(lambda s: s.rolling(5).mean())
    bars["lu_cnt60"] = g["lu_flag"].transform(lambda s: s.rolling(60).sum())

    feats = ["sm_yang_consec", "yang_cnt10", "ret5", "ret10", "ret20", "ret60",
             "dist_ma20", "dist_ma60", "newhigh60_dist", "turnover_rate", "to5",
             "to_trend", "vol_ratio", "amp", "amp5", "lu_cnt60"]
    bars["dist_ma20"] = bars.close_price / bars.ma20 - 1
    feat_tm1 = {}
    for c in feats:
        bars[c + "_tm1"] = g[c].shift(1)
        feat_tm1[c] = c + "_tm1"
    for col in ["close_price", "low_price", "ma5", "ma10", "ma20", "change_pct"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k_ in (2, 3, 4, 5, 6):
        bars[f"open_p{k_}"] = g["open_price"].shift(-k_)
        bars[f"close_p{k_}"] = g["close_price"].shift(-k_)
    bars["lu_T"] = bars["lu_flag"]
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
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999
    bars["bull"] = ((bars.ma5_tm1 > bars.ma10_tm1) & (bars.ma10_tm1 > bars.ma20_tm1)
                    & (bars.close_price_tm1 > bars.ma20_tm1))

    base = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"]
                & (~bars["lu_tm1"]) & ~bars["oneword_strict"] & bars["bull"]
                & (bars.close_price_tm1 >= 50)].copy()
    k = base["streak_h"].fillna(0).astype(int).clip(0, 6)
    eo = np.full(len(base), np.nan)
    for kk in range(2, 7):
        eo = np.where((k == kk).values, base[f"open_p{kk}"].values, eo)
    eo = np.where(~base["sealed"] | (k < 2), base["open_p1"].values, eo)
    base["ret"] = pd.Series(eo / base["entry"].values - 1, index=base.index)
    disc = (base["open_p1"] / base["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (base[f"open_p{kk}"].values / base[f"close_p{kk-1}"].values - 1).__abs__() > 0.11
    base = base[~pd.Series(disc, index=base.index).fillna(False)]
    base["streak2"] = base["streak_h"].fillna(0) >= 2
    base["grp"] = np.where(base.streak2, "连板", np.where(base.sealed, "封板未连", "炸板"))
    base["name"] = base.vt_symbol.map(name_map)
    base["cap_yi"] = base.vt_symbol.map(cap_map)

    out = {"n": len(base), "grp_n": base.grp.value_counts().to_dict()}
    good, mid, bad = base[base.streak2], base[base.grp == "封板未连"], base[base.grp == "炸板"]
    # 三组特征对比
    comp = {}
    for c in ["cap_yi", "close_price_tm1", "gap_open"] + [feat_tm1[c] for c in feats]:
        a, bb = good[c].dropna(), bad[c].dropna()
        m_ = mid[c].dropna()
        row = {"连板均": round(float(a.mean()), 3), "连板中位": round(float(a.median()), 3),
               "封未连均": round(float(m_.mean()), 3),
               "炸板均": round(float(bb.mean()), 3), "炸板中位": round(float(bb.median()), 3)}
        if len(a) > 20 and len(bb) > 20:
            t, p = sstats.ttest_ind(a, bb, equal_var=False)
            row["t"] = round(float(t), 2)
            row["p"] = round(float(p), 4)
        comp[c] = row
    out["三组对比"] = comp
    # 强特征分桶(连板率单调性)
    def bucket(col, edges, labels):
        sub = base.dropna(subset=[col])
        bcat = pd.cut(sub[col], edges, labels=labels)
        return {str(lb): {"n": int(len(g_)), "连板率": round(float(g_.streak2.mean()), 3),
                          "封板率": round(float(g_.sealed.mean()), 3),
                          "ret": round(float(g_.ret.mean()) * 100, 2)}
                for lb, g_ in sub.groupby(bcat, observed=True)}
    out["分桶_连续小阳"] = bucket("sm_yang_consec_tm1", [-1, 0, 2, 4, 30], ["0天", "1~2天", "3~4天", ">=5天"])
    out["分桶_前60日涨停史"] = bucket("lu_cnt60_tm1", [-1, 0, 1, 3, 50], ["0次", "1次", "2~3次", ">=4次"])
    out["分桶_量能趋势to5/to20"] = bucket("to_trend_tm1", [0, 0.8, 1.2, 2, 100], ["缩<0.8", "0.8~1.2", "1.2~2", ">=2"])
    out["分桶_近10日阳线数"] = bucket("yang_cnt10_tm1", [-1, 4, 6, 8, 10], ["<=4", "5~6", "7~8", "9~10"])
    # 实例清单
    cols = ["name", "trade_date", "ret", "sm_yang_consec_tm1", "yang_cnt10_tm1", "ret20_tm1",
            "lu_cnt60_tm1", "to_trend_tm1", "vol_ratio_tm1", "gap_open", "cap_yi", "close_price_tm1"]
    gl = good.sort_values("ret", ascending=False)[cols].head(12)
    bl = bad.sort_values("ret")[cols].head(12)
    out["好票实例"] = gl.assign(trade_date=gl.trade_date.dt.date.astype(str),
                              ret=(gl.ret * 100).round(1)).round(3).to_dict("records")
    out["差票实例"] = bl.assign(trade_date=bl.trade_date.dt.date.astype(str),
                              ret=(bl.ret * 100).round(1)).round(3).to_dict("records")
    # ---- 组合条件验证: 用显著差异特征组装, 双段检验能否救活 ----
    base["is_train"] = base.trade_date < pd.Timestamp("2025-07-01")
    base["month"] = base["trade_date"].dt.to_period("M").astype(str)

    def st2(sub):
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
                "连板率": round(float(sub.streak2.mean()), 3)}

    c1 = base[(base.lu_cnt60_tm1 >= 4) & (base.close_price_tm1 < 100) & (base.cap_yi < 500)]
    c2 = c1[c1.amp5_tm1 >= 0.07]
    c3 = c2[c2.change_pct_tm1 < 0]
    c4 = c1[c1.change_pct_tm1 < 0]
    out["组合_C1_涨停史>=4+价50~100+市值<500"] = st2(c1)
    out["组合_C2_再+振幅5>=7%"] = st2(c2)
    out["组合_C3_再+昨阴"] = st2(c3)
    out["组合_C4_C1+昨阴"] = st2(c4)
    out["对照_裸带"] = st2(base)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
