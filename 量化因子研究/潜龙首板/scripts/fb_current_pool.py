"""按最终条件出当前观察池(截至最新交易日) + 近30日每日池子规模."""
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
                      low_price, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2026-03-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, touched_limit
               FROM stock_limit_up_daily WHERE trade_date >= '2026-03-01'""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    name_map = stocks.set_index("vt_symbol")["name"].to_dict()

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
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_today"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values

    # 弱转强: 前2~10日有 limit_up_count>=2 记录
    lu2 = lu[lu.limit_up_count >= 2][["vt_symbol", "trade_date"]]
    tmp = bars[["vt_symbol", "trade_date"]].merge(lu2, on="vt_symbol", how="left")
    delta = (tmp["trade_date_x"] - tmp["trade_date_y"]).dt.days
    w2s = tmp[(delta >= 2) & (delta <= 10)][["vt_symbol", "trade_date_x"]].drop_duplicates()
    w2s["weak2strong"] = True
    bars = bars.merge(w2s, left_on=["vt_symbol", "trade_date"],
                      right_on=["vt_symbol", "trade_date_x"], how="left")
    bars["weak2strong"] = bars["weak2strong"].fillna(False)

    dist = bars["close_price"] / bars["ma20"] - 1
    pool_mask = (
        (~bars["lu_today"])
        & (bars["change_pct"] >= 0) & (bars["change_pct"] <= 5)
        & (bars["low_price"] > bars["ma20"])          # 昨低>MA20(模板口径)
        & (bars["ma10"] > bars["ma20"])
        & (dist >= 0) & (dist <= 0.12)
        & (bars["ret5"] >= 0) & (bars["ret5"] <= 0.15)
        & (bars["turnover_rate"] < 8)
    )
    bars["in_pool"] = pool_mask

    daily_n = bars[bars.in_pool].groupby("trade_date").size()
    print("== 近15个交易日池子规模 ==", file=sys.stderr)
    print(daily_n.tail(15).to_string(), file=sys.stderr)

    last_date = bars["trade_date"].max()
    today = bars[(bars.trade_date == last_date) & bars.in_pool].copy()
    today["name"] = today.vt_symbol.map(name_map)
    today["dist_ma20"] = (today["close_price"] / today["ma20"] - 1) * 100
    today["ret5p"] = today["ret5"] * 100
    today = today.sort_values(["weak2strong", "turnover_rate"], ascending=[False, False])
    print(f"\n== {last_date.date()} 收盘后观察池: {len(today)} 只 ==", file=sys.stderr)
    cols = ["vt_symbol", "name", "close_price", "change_pct", "turnover_rate",
            "dist_ma20", "ret5p", "weak2strong"]
    print(today[cols].round(2).to_string(index=False), file=sys.stderr)
    # 市场情绪状态(供闸门)
    lu["is_zha"] = (~lu.is_limit_up) & lu.touched_limit
    dd = lu.groupby("trade_date").agg(max_h=("limit_up_count", "max"), zha_n=("is_zha", "sum"),
                                      lianban=("limit_up_count", lambda s: (s >= 2).sum()))
    last = dd.loc[dd.index.max()]
    breadth = bars.groupby("trade_date")["change_pct"].agg(up5=lambda s: (s >= 5).sum(), total="count")
    br = breadth.loc[breadth.index.max()]
    print(f"\n== {dd.index.max().date()} 情绪: 最高板={int(last.max_h)} 炸板={int(last.zha_n)} "
          f"连板={int(last.lianban)} 涨幅>=5%占比={br.up5/br.total:.1%} ==", file=sys.stderr)


if __name__ == "__main__":
    main()
