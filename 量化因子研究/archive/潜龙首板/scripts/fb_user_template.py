"""用户模板条件验证: 主板/非ST/前十日有连板/MA10>MA20/昨日最低>MA20/昨日振幅<8%.

A  = 模板原样
B  = A + 昨日未涨停(首板语义)
C  = B + 不过热(距MA20 0~12% / 前5日0~15% / 换手<8%)
D  = C + 情绪闸门(广度<12% + 炸板<=60)
另: 振幅分箱 lift; 昨日最低>MA20 vs 收盘>MA20 对比.
两个样本集: 首板样本(看晋级ge2/ge3/ge5) + 日线触发样本(看seal/d1/d3).
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-06-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word, touched_limit
               FROM stock_limit_up_daily WHERE trade_date >= '2022-11-01'""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])

    g = bars.groupby("vt_symbol", sort=False)
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p3"] = g["close_price"].shift(-3)
    # T-1 特征 + T-2 收盘(算振幅)
    for col in ["close_price", "open_price", "high_price", "low_price",
                "change_pct", "turnover_rate", "ma10", "ma20", "ret5"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars["close_tm2"] = g["close_price"].shift(2)
    bars["amp_tm1"] = (bars["high_price_tm1"] - bars["low_price_tm1"]) / bars["close_tm2"]

    breadth = bars.groupby("trade_date")["change_pct"].agg(up5=lambda s: (s >= 5).sum(), total="count")
    breadth["ratio"] = breadth.up5 / breadth.total
    bars["breadth_tm1"] = bars["trade_date"].map(breadth["ratio"].sort_index().shift(1))

    lu["is_zha"] = (~lu.is_limit_up) & lu.touched_limit
    day = lu.groupby("trade_date").agg(
        max_h=("limit_up_count", "max"), zha_n=("is_zha", "sum")).sort_index()
    bars["zha_n_tm1"] = bars["trade_date"].map(day["zha_n"].shift(1))

    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values

    # streak 段 + 弱转强(前2~10日有连板记录)
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    lu2 = lu_all[lu_all.limit_up_count >= 2][["vt_symbol", "trade_date"]]
    tmp = bars[["vt_symbol", "trade_date"]].merge(lu2, on="vt_symbol", how="left")
    delta = (tmp["trade_date_x"] - tmp["trade_date_y"]).dt.days
    w2s = tmp[(delta >= 2) & (delta <= 10)][["vt_symbol", "trade_date_x"]].drop_duplicates()
    w2s["weak2strong"] = True
    bars = bars.merge(w2s, left_on=["vt_symbol", "trade_date"],
                      right_on=["vt_symbol", "trade_date_x"], how="left")
    bars["weak2strong"] = bars["weak2strong"].fillna(False)

    # ===== 条件定义 =====
    c_ma = (bars["ma10_tm1"] > bars["ma20_tm1"])
    c_low_above = bars["low_price_tm1"] > bars["ma20_tm1"]      # 模板: 昨日最低>MA20
    c_close_above = bars["close_price_tm1"] > bars["ma20_tm1"]  # 我的: 昨日收盘>MA20
    c_amp = bars["amp_tm1"] < 0.08
    c_w2s = bars["weak2strong"]
    c_notlu = ~bars["lu_tm1"]
    dist = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    c_cool = ((dist >= 0) & (dist <= 0.12) & (bars["ret5_tm1"] >= 0) & (bars["ret5_tm1"] <= 0.15)
              & (bars["turnover_rate_tm1"] < 8))
    c_gate = (bars["breadth_tm1"] < 0.12) & (bars["zha_n_tm1"] <= 60)

    tpl = c_ma & c_low_above & c_amp & c_w2s  # 模板核心(主板非ST已在样本内)

    # ===== 样本集1: 首板(2023+, 非一字) 看晋级 =====
    fb = bars[(bars.trade_date >= "2023-01-01") & bars["streak_h"].notna()].copy()
    out = {"fb_n": len(fb)}

    def lift_fb(mask, label):
        sub = fb[mask.reindex(fb.index).fillna(False)]
        if len(sub) < 5:
            return {"label": label, "n": len(sub)}
        return {"label": label, "n": int(len(sub)),
                "ge2": round(float((sub.streak_h >= 2).mean()), 4),
                "ge3": round(float((sub.streak_h >= 3).mean()), 4),
                "ge5": round(float((sub.streak_h >= 5).mean()), 4)}

    out["fb_all"] = lift_fb(pd.Series(True, index=fb.index), "首板全体")
    out["fb_tpl"] = lift_fb(tpl, "A 模板原样")
    out["fb_tpl_notlu"] = lift_fb(tpl & c_notlu, "B +昨日未涨停")
    out["fb_tpl_cool"] = lift_fb(tpl & c_notlu & c_cool, "C +不过热")
    out["fb_tpl_gate"] = lift_fb(tpl & c_notlu & c_cool & c_gate, "D +情绪闸门")
    out["fb_low_vs_close"] = [
        lift_fb(c_ma & c_low_above, "MA10>20 且 昨低>MA20"),
        lift_fb(c_ma & c_close_above, "MA10>20 且 昨收>MA20"),
        lift_fb(c_ma & c_low_above & c_amp, "昨低>MA20 + 振幅<8%"),
    ]
    # 振幅分箱
    f = fb[fb.amp_tm1.notna()].copy()
    f["bin"] = pd.cut(f["amp_tm1"], [0, 0.03, 0.05, 0.08, 0.12, 1])
    t = f.groupby("bin", observed=True).agg(
        n=("streak_h", "size"), ge2=("streak_h", lambda s: (s >= 2).mean()),
        ge3=("streak_h", lambda s: (s >= 3).mean()), ge5=("streak_h", lambda s: (s >= 5).mean())).round(4)
    out["fb_amp_bins"] = [{"bin": str(i), "n": int(r.n), "ge2": r.ge2, "ge3": r.ge3, "ge5": r.ge5}
                          for i, r in t.iterrows()]

    # ===== 样本集2: 日线触发(+8%) 看封板/溢价 =====
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"], bars["open_price"], bars["trigger_price"])
    bars["sealed"] = bars["lu_T"]
    bars["ret_d1"] = bars["close_p1"] / bars["entry"] - 1
    bars["ret_d3"] = bars["close_p3"] / bars["entry"] - 1
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"]].copy()

    def lift_ev(mask, label):
        sub = ev[mask.reindex(ev.index).fillna(False)]
        if len(sub) < 5:
            return {"label": label, "n": len(sub)}
        return {"label": label, "n": int(len(sub)),
                "seal": round(float(sub.sealed.mean()), 4),
                "d1": round(float(sub.ret_d1.mean()) * 100, 3),
                "d3": round(float(sub.ret_d3.mean()) * 100, 3)}

    out["ev_base"] = lift_ev(c_notlu, "触发基线(仅昨未涨停)")
    out["ev_tpl"] = lift_ev(tpl, "A 模板原样")
    out["ev_tpl_notlu"] = lift_ev(tpl & c_notlu, "B +昨日未涨停")
    out["ev_tpl_cool"] = lift_ev(tpl & c_notlu & c_cool, "C +不过热")
    out["ev_tpl_gate"] = lift_ev(tpl & c_notlu & c_cool & c_gate, "D +情绪闸门")

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
