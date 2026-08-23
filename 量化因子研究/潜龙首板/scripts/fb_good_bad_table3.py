"""好票差票逐月对照 v3: v2 口径(D+1真亏/下影深) + v5池选中标记.
好票: 当月最高连板前3 且 D+1盘中最低>=-6%; 下影深的高板票单独标注.
差票: 首板封住但 D+1 收盘<成本, 跌最狠前3.
每只标注 v5池判定(市值<50/价<8/多头<=12天/非回锅贴脸/量比<1.5): 逐条列出不满足项.
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
SHADOW_TH = -0.06


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
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    bull = ((bars.close_price > bars.ma5) & (bars.ma5 > bars.ma10)
            & (bars.ma10 > bars.ma20)).fillna(False)
    run = bull.astype(int)
    bars["trend_days"] = (run * run.groupby([bars.vt_symbol, (~bull).cumsum()]).cumsum()).clip(0, 60)
    bars["day_idx"] = g.cumcount()
    last_lu_day = bars["day_idx"].where(bars.lu_T).groupby(bars.vt_symbol).ffill()
    bars["days_since_lu"] = bars["day_idx"] - last_lu_day
    bars["lu_close"] = np.where(bars.lu_T, bars.close_price, np.nan)
    bars["last_lu_close"] = bars.groupby("vt_symbol")["lu_close"].ffill()
    lu_seg = bars.groupby("vt_symbol")["lu_T"].cumsum()
    bars["since_lu_low"] = bars.groupby([bars.vt_symbol, lu_seg])["low_price"].cummin()
    bars["since_lu_dd"] = bars["since_lu_low"] / bars["last_lu_close"] - 1
    bars["lu_cnt20"] = g["lu_T"].shift(1).groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).sum())
    bars["maxchg20"] = g["chg"].shift(1).groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).max())
    bars["close_tm1"] = g["close_price"].shift(1)
    bars["chg_tm1"] = g["chg"].shift(1)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["low_p1"] = g["low_price"].shift(-1)
    bars["open_p1"] = g["open_price"].shift(-1)
    for col in ["trend_days", "days_since_lu", "since_lu_dd"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["name"] = bars.vt_symbol.map(name_map)
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    limit_px = (bars["close_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[bars["streak_h"].notna() & ~bars["oneword"]].copy()
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["d1_close"] = ev["close_p1"] / ev["close_price"] - 1
    ev["d1_low"] = ev["low_p1"] / ev["close_price"] - 1
    ev = ev.dropna(subset=["close_tm1", "vol_ratio", "maxchg20", "d1_close", "d1_low", "open_p1"])
    ev = ev[(ev["open_p1"] / ev["close_price"] - 1).abs() <= 0.11]

    def v5_fail(r):
        """返回 v5 池不满足项的中文描述; 全部满足返回 '选中'."""
        fails = []
        if not r.cap_yi < 50:
            fails.append(f"市值{r.cap_yi:.0f}亿")
        if not r.close_tm1 < 8:
            fails.append(f"价{r.close_tm1:.1f}元")
        if not (np.isfinite(r.trend_days_tm1) and r.trend_days_tm1 <= 12):
            fails.append(f"多头{int(r.trend_days_tm1)}天")
        if (np.isfinite(r.days_since_lu_tm1) and 2 <= r.days_since_lu_tm1 <= 12
                and np.isfinite(r.since_lu_dd_tm1) and r.since_lu_dd_tm1 > -0.05):
            fails.append("回锅贴脸")
        if not r.vol_ratio < 1.5:
            fails.append(f"量比{r.vol_ratio:.1f}")
        return "✓选中" if not fails else "✗" + "/".join(fails)

    def row(r, note=""):
        return (f"| {r['name']}{note} | {int(r['streak_h'])}板 | {r.trade_date.strftime('%m-%d')} "
                f"| {r.close_tm1:.2f} | {r.cap_yi:.0f} | {r.chg_tm1:+.1f}% "
                f"| {int(r.lu_cnt20)}次 | {int(r.trend_days_tm1) if np.isfinite(r.trend_days_tm1) else 0}天 "
                f"| {r.vol_ratio:.1f} | {r.d1_close*100:+.1f}% | {r.d1_low*100:+.1f}% | {v5_fail(r)} |")

    header = ("| 票 | 板数 | 首板日 | 前收盘(元) | 市值(亿) | 前一天涨跌 | 前20日涨停 | 多头排列持续 | "
              "首板量比 | D+1收盘 | D+1盘中最低 | v5池判定 |")
    sep = "|" + "---|" * 12
    lines = []
    for mth in MONTHS:
        sub = ev[ev.month == mth]
        tall = sub[sub.streak_h >= 3].sort_values("streak_h", ascending=False)
        good = tall[tall.d1_low >= SHADOW_TH].head(3)
        shadowed = tall[tall.d1_low < SHADOW_TH].head(2)
        bad = sub[(sub.streak_h == 1) & (sub.d1_close < 0)].nsmallest(3, "d1_close")
        lines.append(f"\n### {mth}\n")
        lines.append("**好票(当月最高连板,D+1 不埋人)**\n")
        lines.append(header); lines.append(sep)
        for _, r in good.iterrows():
            lines.append(row(r))
        for _, r in shadowed.iterrows():
            lines.append(row(r, note=" ⚠️下影深"))
        lines.append("")
        lines.append("**差票(D+1 收盘真亏钱,跌最狠的)**\n")
        lines.append(header); lines.append(sep)
        for _, r in bad.iterrows():
            lines.append(row(r))
    text = "\n".join(lines)
    print(text)
    with open("/tmp/out/好票差票月度对照.md", "w", encoding="utf-8") as f:
        f.write("# 好票 vs 差票 逐月对照 v3(带 v5 池判定)\n\n")
        f.write("口径:主板非ST,首板非一字,成本=首板收盘价。剔 D+1 隔夜缺口>11% 的除权伪信号。\n")
        f.write("好票=≥3板且D+1盘中最低≥-6%;⚠️下影深=高板但D+1盘中砸超-6%,不算好票。\n")
        f.write("差票=首板封住但D+1收盘低于成本,跌最狠前3。\n")
        f.write("v5池判定=市值<50亿/价<8元/多头排列≤12天/非回锅贴脸/首板量比<1.5,逐条列出不满足项。\n")
        f.write(text)


if __name__ == "__main__":
    main()
