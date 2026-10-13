"""首板日线层细化对比(2023-01起, 数据稠密区).

变体对比:
  A 底座
  B 底座+不过热
  C 底座+不过热+盘面<6%
  D = C 且换手 5~8%
  E = B + 盘面<4% / <8% (广度阈值敏感性)
  F = C 但换手 <5%
输出: 整体/按年/按季, 封板率 D+1 D+3, streak>=2/3/5.
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
START = "2022-06-01"
REPORT_START = "2023-01-01"


def load():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= %s""", conn, params=(START,))
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word
               FROM stock_limit_up_daily""", conn)
    return stocks, bars, lu


def main():
    stocks, bars, lu = load()
    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
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

    breadth = bars.groupby("trade_date")["change_pct"].agg(up5=lambda s: (s >= 5).sum(), total="count")
    breadth["ratio"] = breadth.up5 / breadth.total
    breadth_prev = breadth["ratio"].sort_index().shift(1)

    for col in ["close_price", "open_price", "change_pct", "turnover_rate", "ma10", "ma20", "ret5"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars["breadth_tm1"] = bars["trade_date"].map(breadth_prev)

    lu_flag = lu_key["is_limit_up"]
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_flag).fillna(False).astype(bool).values
    tm1_date = bars.groupby("vt_symbol", sort=False)["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_flag).fillna(False).astype(bool).values

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"], bars["open_price"], bars["trigger_price"])
    bars["sealed"] = bars["lu_T"]
    bars["ret_d1"] = bars["close_p1"] / bars["entry"] - 1
    bars["ret_d1_open"] = bars["open_p1"] / bars["entry"] - 1
    bars["ret_d3"] = bars["close_p3"] / bars["entry"] - 1

    # streak 高度(首板事件)
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]].set_index(["vt_symbol", "trade_date"])
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    ev = bars[(bars.trade_date >= REPORT_START) & bars["triggered"]].copy()
    print(f"触发事件总数(2023+): {len(ev):,}", file=sys.stderr)

    dist_ma20 = ev["close_price_tm1"] / ev["ma20_tm1"] - 1
    c_base = ((~ev["lu_tm1"]) & (ev["change_pct_tm1"] >= 0) & (ev["change_pct_tm1"] <= 5)
              & (ev["close_price_tm1"] > ev["ma20_tm1"]) & (ev["ma10_tm1"] > ev["ma20_tm1"]))
    c_cool = ((dist_ma20 >= 0) & (dist_ma20 <= 0.12)
              & (ev["ret5_tm1"] >= 0) & (ev["ret5_tm1"] <= 0.15)
              & (ev["turnover_rate_tm1"] < 8))
    c_b6 = ev["breadth_tm1"] < 0.06
    c_b4 = ev["breadth_tm1"] < 0.04
    c_b8 = ev["breadth_tm1"] < 0.08
    c_to58 = ev["turnover_rate_tm1"].between(5, 8)
    c_to5 = ev["turnover_rate_tm1"] < 5

    variants = [
        ("A 底座", c_base),
        ("B +不过热", c_base & c_cool),
        ("C +盘面<6%", c_base & c_cool & c_b6),
        ("D C+换手5~8", c_base & c_cool & c_b6 & c_to58),
        ("E1 B+盘面<4%", c_base & c_cool & c_b4),
        ("E2 B+盘面<8%", c_base & c_cool & c_b8),
        ("F C+换手<5%", c_base & c_cool & c_b6 & c_to5),
    ]

    def stats(df, label):
        n = len(df)
        if n < 5:
            return {"label": label, "n": n}
        sealed = df[df["sealed"]]
        r = {
            "label": label, "n": n,
            "seal": round(len(sealed) / n, 4),
            "d1": round(df["ret_d1"].mean() * 100, 3),
            "d1o": round(df["ret_d1_open"].mean() * 100, 3),
            "d3": round(df["ret_d3"].mean() * 100, 3),
            "d1w": round((df["ret_d1"] > 0).mean(), 4),
        }
        s = df[df["sealed"] & df["streak_h"].notna()]
        if len(s) >= 5:
            r["streak>=2"] = round(float((s.streak_h >= 2).mean()), 4)
            r["streak>=3"] = round(float((s.streak_h >= 3).mean()), 4)
            r["streak>=5"] = round(float((s.streak_h >= 5).mean()), 4)
        return r

    out = {"overall": [stats(ev[m], lb) for lb, m in variants]}
    ev["year"] = ev["trade_date"].dt.year
    ev["quarter"] = ev["trade_date"].dt.to_period("Q").astype(str)
    for lb, m in variants:
        sub = ev[m]
        out[f"year::{lb}"] = [stats(gp, str(y)) for y, gp in sub.groupby("year")]
    for lb in ["B +不过热", "C +盘面<6%"]:
        m = dict(variants)[lb]
        out[f"quarter::{lb}"] = [stats(gp, q) for q, gp in ev[m].groupby("quarter")]

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
