"""好票差票逐月对照(人话版): 每月最高连板 top3 好票 vs 首板爆量但只走1板的 top3 差票.
列全部用大白话数字, 无术语. 输出 markdown 直接可贴.
"""
from __future__ import annotations

import os, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
MONTHS = ["2025-11", "2025-12", "2026-01", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count
               FROM stock_limit_up_daily WHERE is_limit_up""", conn)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()
    name_map = main.set_index("vt_symbol")["name"].to_dict()

    lu = lu.copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_m = lu[lu.vt_symbol.isin(main_syms)]
    lu_all = lu_m.sort_values(["vt_symbol", "trade_date"]).copy()
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
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["chg"] = bars["change_pct"].fillna(derived)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key := lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    lu_prev = g["lu_T"].shift(1)
    chg_prev = g["chg"].shift(1)
    bars["lu_cnt20"] = lu_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).sum())
    bars["maxchg20"] = chg_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).max())
    bars["ret20"] = g["close_price"].transform(lambda s: s / s.shift(21) - 1)
    bars["close_tm1"] = g["close_price"].shift(1)
    bars["chg_tm1"] = g["chg"].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["name"] = bars.vt_symbol.map(name_map)
    bars["gap_open"] = bars["open_price"] / bars["close_tm1"] - 1
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    limit_px = (bars["close_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[bars["streak_h"].notna() & ~bars["oneword"]].copy()
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)

    def row(r):
        return (f"| {r['name']} | {int(r['streak_h'])}板 | {r.trade_date.strftime('%m-%d')} "
                f"| {r.close_tm1:.2f} | {r.cap_yi:.0f} | {r.chg_tm1:+.1f}% "
                f"| {int(r.lu_cnt20)}次 | {r.maxchg20:+.1f}% | {r.ret20*100:+.0f}% "
                f"| {r.vol_ratio:.1f} | {r.gap_open*100:+.1f}% |")

    lines = []
    header = ("| 票 | 走了几板 | 首板日 | 首板前收盘(元) | 市值(亿) | 前一天涨跌 | "
              "前20日涨停 | 前20日最大单日涨 | 前20日累计涨跌 | 首板当天量比 | 首板高开 |")
    sep = "|" + "---|" * 11
    for mth in MONTHS:
        sub = ev[ev.month == mth].dropna(subset=["close_tm1", "vol_ratio", "maxchg20"])
        good = sub[sub.streak_h >= 3].nlargest(3, "streak_h")
        bad = sub[sub.streak_h == 1].nlargest(3, "vol_ratio")
        lines.append(f"\n### {mth}\n")
        lines.append("**好票(当月连板最高的)**\n")
        lines.append(header)
        lines.append(sep)
        for _, r in good.iterrows():
            lines.append(row(r))
        lines.append("")
        lines.append("**差票(首板封住但只走1板、当天量最大的)**\n")
        lines.append(header)
        lines.append(sep)
        for _, r in bad.iterrows():
            lines.append(row(r))
    text = "\n".join(lines)
    print(text)
    with open("/tmp/out/好票差票月度对照.md", "w", encoding="utf-8") as f:
        f.write("# 好票 vs 差票 逐月对照(首板前数字全摆开)\n")
        f.write("\n口径:主板非ST,首板非一字。好票=当月连板最高前3;差票=首板封住但只走1板且当天量最大前3。\n")
        f.write("量比=首板当天全天成交量 ÷ 前5日平均量(<1.5=没爆量,越大越爆)。\n")
        f.write(text)


if __name__ == "__main__":
    main()
