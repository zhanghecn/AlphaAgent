"""日线层最终组合: 底座+不过热+盘面+情绪闸门 (2023+).

变体:
  S2   = 底座+不过热+盘面<6%
  S2w  = 底座+不过热+盘面<12%
  G1   = S2 + 昨日最高板>=5
  G2   = S2 + 昨日炸板<=60
  G3   = S2 + 最高板>=5 + 炸板<=60
  G3w  = S2w + 最高板>=5 + 炸板<=60
  G4   = 底座+不过热 + 最高板>=5 + 炸板<=60 (无盘面)
输出: n/seal/d1/d3/ge2/ge3, 按年.
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
    for col in ["close_price", "change_pct", "turnover_rate", "ma10", "ma20", "ret5"]:
        bars[col + "_tm1"] = g[col].shift(1)

    breadth = bars.groupby("trade_date")["change_pct"].agg(up5=lambda s: (s >= 5).sum(), total="count")
    breadth["ratio"] = breadth.up5 / breadth.total
    bars["breadth_tm1"] = bars["trade_date"].map(breadth["ratio"].sort_index().shift(1))

    # 情绪序列
    lu["is_zha"] = (~lu.is_limit_up) & lu.touched_limit
    day = lu.groupby("trade_date").agg(
        lianban_n=("limit_up_count", lambda s: (s >= 2).sum()),
        max_h=("limit_up_count", "max"),
        zha_n=("is_zha", "sum"),
    ).sort_index()
    bars["max_h_tm1"] = bars["trade_date"].map(day["max_h"].shift(1))
    bars["zha_n_tm1"] = bars["trade_date"].map(day["zha_n"].shift(1))
    bars["lianban_tm1"] = bars["trade_date"].map(day["lianban_n"].shift(1))

    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values

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

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"], bars["open_price"], bars["trigger_price"])
    bars["sealed"] = bars["lu_T"]
    bars["ret_d1"] = bars["close_p1"] / bars["entry"] - 1
    bars["ret_d1o"] = bars["open_p1"] / bars["entry"] - 1
    bars["ret_d3"] = bars["close_p3"] / bars["entry"] - 1

    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"]].copy()
    ev["year"] = ev["trade_date"].dt.year

    dist = ev["close_price_tm1"] / ev["ma20_tm1"] - 1
    c_base = ((~ev["lu_tm1"]) & (ev["change_pct_tm1"] >= 0) & (ev["change_pct_tm1"] <= 5)
              & (ev["close_price_tm1"] > ev["ma20_tm1"]) & (ev["ma10_tm1"] > ev["ma20_tm1"]))
    c_cool = ((dist >= 0) & (dist <= 0.12) & (ev["ret5_tm1"] >= 0) & (ev["ret5_tm1"] <= 0.15)
              & (ev["turnover_rate_tm1"] < 8))
    c_b6 = ev["breadth_tm1"] < 0.06
    c_b12 = ev["breadth_tm1"] < 0.12
    g_maxh = ev["max_h_tm1"] >= 5
    g_zha = ev["zha_n_tm1"] <= 60

    variants = [
        ("S2 (原盘面<6%)", c_base & c_cool & c_b6),
        ("S2w (盘面<12%)", c_base & c_cool & c_b12),
        ("S2+最高板>=5", c_base & c_cool & c_b6 & g_maxh),
        ("S2+炸板<=60", c_base & c_cool & c_b6 & g_zha),
        ("S2+双闸", c_base & c_cool & c_b6 & g_maxh & g_zha),
        ("S2w+双闸", c_base & c_cool & c_b12 & g_maxh & g_zha),
        ("无盘面+双闸", c_base & c_cool & g_maxh & g_zha),
    ]

    def stats(df, label):
        n = len(df)
        if n < 5:
            return {"label": label, "n": n}
        s = df[df["sealed"] & df["streak_h"].notna()]
        r = {"label": label, "n": n,
             "seal": round(df["sealed"].mean(), 4),
             "d1": round(df["ret_d1"].mean() * 100, 3),
             "d1o": round(df["ret_d1o"].mean() * 100, 3),
             "d3": round(df["ret_d3"].mean() * 100, 3),
             "d1w": round((df["ret_d1"] > 0).mean(), 4)}
        if len(s) >= 5:
            r["ge2"] = round(float((s.streak_h >= 2).mean()), 4)
            r["ge3"] = round(float((s.streak_h >= 3).mean()), 4)
            r["ge5"] = round(float((s.streak_h >= 5).mean()), 4)
        return r

    out = {"overall": [stats(ev[m.fillna(False)], lb) for lb, m in variants]}
    for lb, m in variants:
        sub = ev[m.fillna(False)]
        out[f"year::{lb}"] = [stats(gp, str(y)) for y, gp in sub.groupby("year")]
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
