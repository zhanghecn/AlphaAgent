"""连板票首板前"安静度"细查 —— 对账用户人工观察:
"连板票首板前面几乎没涨停, 甚至 >7% 单日涨幅都没见过".

宇宙: 主板非ST 封住首板 非一字, 2023-01起. 好票 = streak>=3(另附>=2口径).
Q1 前10/20/60日涨停次数分布: 好票 vs 差票(读: 好票里多大比例首板前完全无涨停)
Q2 前10/20日最大单日涨幅分布: <3 / 3~5 / 5~7 / 7~9.5 / >=9.5(涨停级)
   关键联合读数: 前20日"既无涨停 且 无>7%单日涨幅" 的好票占比
Q3 分年(2023/2024/2025/2026)看好票安静度是否稳定(用户观察的是近期票)
Q4 矛盾调和: P(安静|好) vs P(好|安静) vs P(好|有记忆) —— 两个方向的条件概率
Q5 稳月池(市值50+价8+量比1.5+高开<8)逐月: 笔数/≥2板率/≥3板率/≥4板率
Q6 市场≥3板票(非一字)被稳月池捕获的比例; 池内好票的安静度画像
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def dist(s, bins, labels):
    cat = pd.cut(s, bins, labels=labels)
    t = cat.value_counts().reindex(labels)
    return {str(lb): round(float(v) / max(t.sum(), 1) * 100, 1) for lb, v in t.items()}


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count
               FROM stock_limit_up_daily WHERE is_limit_up""", conn)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

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
    lu_key = lu_m.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["chg"] = bars["change_pct"].fillna(derived)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    # 前N日: 涨停次数 / 最大单日涨幅 / >7%涨幅次数(全部 shift(1) 不含当日)
    lu_prev = g["lu_T"].shift(1)
    chg_prev = g["chg"].shift(1)
    for n in (10, 20, 60):
        bars[f"lu_cnt{n}"] = lu_prev.groupby(bars.vt_symbol).transform(
            lambda s, n=n: s.rolling(n, min_periods=1).sum())
        bars[f"maxchg{n}"] = chg_prev.groupby(bars.vt_symbol).transform(
            lambda s, n=n: s.rolling(n, min_periods=1).max())
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["close_tm1"] = g["close_price"].shift(1)
    bars["low_tm1"] = g["low_price"].shift(1)
    bars["gap_open"] = bars["open_price"] / bars["close_tm1"] - 1
    bars["vol_ratio_T"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    limit_px = (bars["close_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[bars["streak_h"].notna() & (bars.trade_date >= "2023-01-01") & ~bars["oneword"]].copy()
    ev = ev.dropna(subset=["close_tm1", "maxchg20"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["year"] = ev.trade_date.dt.year
    ev["good3"] = ev["streak_h"] >= 3
    ev["good2"] = ev["streak_h"] >= 2
    G = ev[ev.good3]
    B = ev[~ev.good3]

    out = {"宇宙n": len(ev), "好票n(>=3板)": len(G), "好票率": round(float(ev.good3.mean()), 4)}

    # ── Q1 涨停次数分布 ─────────────────────────────────────────
    q1 = {}
    for n in (10, 20, 60):
        col = f"lu_cnt{n}"
        bins = [-1, 0, 1, 2, 100]
        labels = ["0次", "1次", "2次", "3次+"]
        q1[f"前{n}日涨停次数"] = {
            "好票分布%": dist(G[col], bins, labels),
            "差票分布%": dist(B[col], bins, labels),
            "全体分布%": dist(ev[col], bins, labels)}
    out["Q1_首板前涨停次数"] = q1

    # ── Q2 最大单日涨幅分布 + 联合安静度 ─────────────────────────
    bins2 = [-100, 3, 5, 7, 9.5, 100]
    labels2 = ["<3%", "3~5%", "5~7%", "7~9.5%", "≥9.5%(涨停级)"]
    q2 = {}
    for n in (10, 20):
        col = f"maxchg{n}"
        q2[f"前{n}日最大单日涨幅"] = {"好票分布%": dist(G[col], bins2, labels2),
                                    "差票分布%": dist(B[col], bins2, labels2)}
    quiet20_G = (G.lu_cnt20 == 0) & (G.maxchg20 < 7)
    quiet20_B = (B.lu_cnt20 == 0) & (B.maxchg20 < 7)
    quiet20_all = (ev.lu_cnt20 == 0) & (ev.maxchg20 < 7)
    q2["联合_前20日无涨停且无>7%涨幅"] = {
        "好票中占比%": round(float(quiet20_G.mean()) * 100, 1),
        "差票中占比%": round(float(quiet20_B.mean()) * 100, 1),
        "全体占比%": round(float(quiet20_all.mean()) * 100, 1)}
    quiet10_G = (G.lu_cnt10 == 0) & (G.maxchg10 < 7)
    q2["联合_前10日无涨停且无>7%涨幅"] = {"好票中占比%": round(float(quiet10_G.mean()) * 100, 1)}
    out["Q2_首板前最大单日涨幅"] = q2

    # ── Q3 分年安静度(好票) ─────────────────────────────────────
    rows = []
    for yr, sub in G.groupby("year"):
        rows.append({"年": int(yr), "好票n": len(sub),
                     "前20日无涨停%": round(float((sub.lu_cnt20 == 0).mean()) * 100, 1),
                     "前20日无>7%%": round(float((sub.maxchg20 < 7).mean()) * 100, 1),
                     "双安静%": round(float(((sub.lu_cnt20 == 0) & (sub.maxchg20 < 7)).mean()) * 100, 1),
                     "前60日无涨停%": round(float((sub.lu_cnt60 == 0).mean()) * 100, 1)})
    out["Q3_好票安静度_分年"] = rows

    # ── Q4 两个方向的条件概率 ────────────────────────────────────
    out["Q4_矛盾调和"] = {
        "P(前20日无涨停|好票)": round(float((G.lu_cnt20 == 0).mean()), 3),
        "P(前20日无涨停|差票)": round(float((B.lu_cnt20 == 0).mean()), 3),
        "P(好票|前20日无涨停)": round(float(ev.loc[ev.lu_cnt20 == 0, "good3"].mean()), 4),
        "P(好票|前20日有涨停)": round(float(ev.loc[ev.lu_cnt20 > 0, "good3"].mean()), 4),
        "P(好票|双安静)": round(float(ev.loc[quiet20_all, "good3"].mean()), 4),
        "P(好票|非双安静)": round(float(ev.loc[~quiet20_all, "good3"].mean()), 4),
        "全体中双安静占比": round(float(quiet20_all.mean()), 3),
    }

    # ── Q5 稳月池逐月笔数与选中率 ────────────────────────────────
    pool = ev[(ev.cap_yi < 50) & (ev.close_tm1 < 8) & (ev.vol_ratio_T < 1.5)
              & (ev.gap_open < 0.08)]
    rows = []
    for mth, sub in pool.groupby("month"):
        rows.append({"month": mth, "笔数": len(sub),
                     "≥2板率%": round(float((sub.streak_h >= 2).mean()) * 100, 1),
                     "≥3板率%": round(float(sub.good3.mean()) * 100, 1),
                     "≥4板率%": round(float((sub.streak_h >= 4).mean()) * 100, 1)})
    out["Q5_稳月池逐月"] = {"汇总": {"月均笔数": round(float(pool.groupby("month").size().mean()), 1),
                                 "总n": len(pool),
                                 "≥2板率%": round(float((pool.streak_h >= 2).mean()) * 100, 1),
                                 "≥3板率%": round(float(pool.good3.mean()) * 100, 1),
                                 "≥4板率%": round(float((pool.streak_h >= 4).mean()) * 100, 1)},
                            "2025下半年起逐月": [r for r in rows if r["month"] >= "2025-07"]}

    # ── Q6 捕获率 + 池内好票画像 ─────────────────────────────────
    caught = set(zip(pool.vt_symbol, pool.trade_date))
    gkeys = list(zip(G.vt_symbol, G.trade_date))
    n_caught = sum(1 for kk in gkeys if kk in caught)
    out["Q6_捕获与池内好票"] = {
        "市场≥3板票(非一字)总数": len(G),
        "稳月池捕获数": n_caught,
        "捕获率": round(n_caught / max(len(G), 1), 3),
        "池内好票n": int(pool.good3.sum()),
        "池内好票_前20日无涨停%": round(float((pool.loc[pool.good3, "lu_cnt20"] == 0).mean()) * 100, 1),
        "池内好票_前20日无>7%%": round(float((pool.loc[pool.good3, "maxchg20"] < 7).mean()) * 100, 1),
    }

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
