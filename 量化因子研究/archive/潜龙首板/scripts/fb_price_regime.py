"""价位带分体制假设: 20~50元带是否需要/能够拥有独立条件集.

Part1 利润引擎检查(最小底座, 不加池条件): 各价位带的封板率/连板率/收益结构.
  策略利润 = 13%连板尾部驱动; 若 20~50 带连板率结构性缺失 → 引擎没有, 条件救不了.
Part2 带内单因子重扫(20~50元): 换手/市值/距MA20/昨涨幅/高开/股价 六变量分桶,
  找带内真正有判别力的条件.
Part3 组合候选规则集, 双段验证 + t检验 vs 带内裸底座, 诚实报告是否打得过"不做".
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
    bars["to_proxy_amt"] = bars["turnover_rate_tm1"] * bars["cap_yi"] / 100  # 成交额代理(亿)
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    # 最小底座: 主板非ST + 昨未涨停 + 触发 + 非一字 (不加任何池条件)
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
    base["streak2"] = base["streak_h"].fillna(0) >= 2
    px = base["close_price_tm1"]

    def st(sub):
        r = sub["ret"].dropna()
        if len(r) < 30:
            return {"n": len(r)}
        va = sub.loc[~sub.is_train, "ret"].dropna()
        return {"n": len(r), "全": round(float(r.mean()) * 100, 2),
                "验": round(float(va.mean()) * 100, 2) if len(va) else None,
                "胜率": round(float((r > 0).mean()), 3),
                "封板率": round(float(sub.sealed.mean()), 3),
                "连板率": round(float(sub.streak2.mean()), 3)}

    out = {}
    # Part1 利润引擎: 价位带 × 结构
    bands = {"<12": px < 12, "12~20": (px >= 12) & (px < 20),
             "20~50": (px >= 20) & (px < 50), ">=50": px >= 50}
    out["P1_引擎结构_裸底座"] = {lb: st(base[m]) for lb, m in bands.items()}
    # 分收益来源: 未封板 vs 封板未连 vs 连板
    for lb, m in bands.items():
        sub = base[m]
        out[f"P1_{lb}_拆分"] = {
            "未封板": st(sub[~sub.sealed]),
            "封板未连": st(sub[sub.sealed & ~sub.streak2]),
            "连板": st(sub[sub.streak2])}

    # Part2 20~50 带内单因子分桶
    h = base[(px >= 20) & (px < 50)]
    out["P2_带内_n"] = len(h)
    scans = {
        "换手": [("<3", h.turnover_rate_tm1 < 3), ("3~5", h.turnover_rate_tm1.between(3, 5)),
                 ("5~8", h.turnover_rate_tm1.between(5, 8)), ("8~12", h.turnover_rate_tm1.between(8, 12)),
                 (">=12", h.turnover_rate_tm1 >= 12)],
        "市值": [("<100亿", h.cap_yi < 100), ("100~300", h.cap_yi.between(100, 300)),
                 ("300~600", h.cap_yi.between(300, 600)), ("600~1200", h.cap_yi.between(600, 1200)),
                 (">=1200", h.cap_yi >= 1200)],
        "距MA20": [("<0", h.dist_ma20 < 0), ("0~6%", h.dist_ma20.between(0, 0.06)),
                   ("6~12%", h.dist_ma20.between(0.06, 0.12)), (">=12%", h.dist_ma20 >= 0.12)],
        "昨涨幅": [("阴", h.change_pct_tm1 < 0), ("0~3", h.change_pct_tm1.between(0, 3)),
                   ("3~5", h.change_pct_tm1.between(3, 5)), ("5~9", h.change_pct_tm1.between(5, 9)),
                   (">=9", h.change_pct_tm1 >= 9)],
        "高开": [("<0", h.gap_open < 0), ("0~2", h.gap_open.between(0, 0.02)),
                 ("2~6", h.gap_open.between(0.02, 0.06)), (">=6", h.gap_open >= 0.06)],
        "成交额代理": [("<3亿", h.to_proxy_amt < 3), ("3~8亿", h.to_proxy_amt.between(3, 8)),
                      ("8~20亿", h.to_proxy_amt.between(8, 20)), (">=20亿", h.to_proxy_amt >= 20)],
        "带内股价": [("20~30", px[(px >= 20) & (px < 50)].between(20, 30).reindex(h.index).fillna(False)),
                     ("30~40", px[(px >= 20) & (px < 50)].between(30, 40).reindex(h.index).fillna(False)),
                     ("40~50", px[(px >= 20) & (px < 50)].between(40, 50).reindex(h.index).fillna(False))],
    }
    out["P2_带内分桶"] = {var: {lb: st(h[m]) for lb, m in bks} for var, bks in scans.items()}

    # Part3 候选组合(等 P2 结果定, 先放两个结构假设)
    # H1 机构适配: 低换手+中大市值+贴MA20+小高开
    h1 = h[(h.turnover_rate_tm1 < 5) & (h.cap_yi.between(100, 1200))
           & (h.dist_ma20.between(0, 0.12)) & (h.gap_open < 0.06)
           & (h.change_pct_tm1.between(0, 5))]
    # H2 只挑引擎子集: 封板率最高的桶组合待数据, 先试 换手<5 & 市值100~600
    h2 = h[(h.turnover_rate_tm1 < 5) & (h.cap_yi.between(100, 600))
           & (h.change_pct_tm1.between(0, 5))]
    out["P3_H1_机构适配"] = st(h1)
    out["P3_H2_低换手中市值"] = st(h2)
    for name, cand in [("H1", h1), ("H2", h2)]:
        a, b = cand["ret"].dropna(), h["ret"].dropna()
        if len(a) > 30:
            t, p = sstats.ttest_ind(a, b, equal_var=False)
            out[f"P3_t_{name}_vs_带内裸"] = {"n": len(a), "cand": round(float(a.mean()) * 100, 2),
                                            "base": round(float(b.mean()) * 100, 2),
                                            "t": round(float(t), 2), "p": round(float(p), 4)}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
