# -*- coding: utf-8 -*-
"""一接二 · 前N日涨幅全窗口扫描(地基前的浮动, 找被忽略的窗口)。

现有研究只看过 前10/前20 两个窗口; 此处 N∈{3,5,10,15,20,30,40,60} 全扫:
  1 每窗口与 E3 的 Spearman 相关
  2 每窗口按分位切5档 → 各档成绩(主窗+OOS 分年)
  3 最强窗口的大肉/大亏对撞 + 与已知信息层(换手/距MA20)的独立增量
口径: 前N日涨幅 = 地基日收盘 / 地基日前N个交易日收盘 - 1。
"""
import os

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import create_engine

OUT = "/tmp/research/j12_out"
NS = [3, 5, 10, 15, 20, 30, 40, 60]


def load_hits():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"], dtype={"代码": str})
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]].copy()
    if "首开一字" in d.columns:
        d = d[~d["首开一字"]]
    G = d[(d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")
          | (d["地基阴阳"] == "阳") & (d["前10日涨幅%"] < -3)
          & d["买入开盘%"].between(7.5, 8.5, inclusive="left")].copy()
    return G


def main():
    G = load_hits()
    eng = create_engine(os.environ["DATABASE_URL"])
    # 拉每票买入日前 75 个自然日~买入日的日线, 算地基日(p2)往前N日涨幅
    rows = []
    for _, r in G.iterrows():
        vsym, dt = r["代码"], pd.Timestamp(r["买入日"])
        bars = pd.read_sql(
            f"select trade_date, close_price from stock_daily_bars "
            f"where vt_symbol='{vsym}' and trade_date >= '{(dt - pd.Timedelta(days=160)).date()}' "
            f"and trade_date <= '{dt.date()}' order by trade_date",
            eng, parse_dates=["trade_date"]).reset_index(drop=True)
        idx = bars.index[bars["trade_date"] == dt]
        if not len(idx):
            continue
        i = int(idx[0])
        p2 = i - 2   # 地基日
        if p2 < 0:
            continue
        rec = {"代码": vsym, "买入日": dt}
        for n in NS:
            j = p2 - n
            rec[f"前{n}日%"] = (bars["close_price"].iat[p2] / bars["close_price"].iat[j] - 1) * 100 \
                if j >= 0 else np.nan
        rows.append(rec)
    P = pd.DataFrame(rows)
    G = G.merge(P, on=["代码", "买入日"], how="inner")
    print(f"命中 {len(G)} 笔已补全前N日涨幅\n")

    # 1 各窗口与 E3 相关
    print("== 各窗口与E3的Spearman相关(负=跌得越多赚得越多) ==")
    for n in NS:
        c = G[f"前{n}日%"]
        rho, p = stats.spearmanr(c, G["E3%"], nan_policy="omit")
        print(f"  前{n}日: rho={rho:+.3f} p={p:.3f}")

    # 2 各窗口分位5档成绩
    for n in NS:
        col = f"前{n}日%"
        q = pd.qcut(G[col], 5, duplicates="drop")
        print(f"\n== 前{n}日涨幅 五分位 ==")
        for k, sub in G.groupby(q, observed=True):
            main_ = sub[sub["段"] == "主窗"]
            oos = sub[sub["段"] == "样本外"]
            yr = main_.groupby("年")["E3%"].mean()
            ok = "✅" if all(yr > 0) and len(yr) >= 4 else ("❌" if any(yr < 0) else "?")
            lo, hi = sub[col].min(), sub[col].max()
            print(f"  [{lo:+7.1f},{hi:+7.1f}]: {len(sub)}笔 均{sub['E3%'].mean():+6.2f} "
                  f"肉{(sub['E3%'] >= 20).sum()}亏{(sub['E3%'] <= -10).sum()} "
                  f"主窗{len(main_)}笔均{main_['E3%'].mean():+6.2f}{ok} "
                  f"OOS{len(oos)}笔均{oos['E3%'].mean() if len(oos) else float('nan'):+6.2f}"
                  f"{'✅' if len(oos) and oos['E3%'].mean() > 0 else '❌' if len(oos) else ''}")

    # 3 大肉大亏中位对比(每窗口)
    meat, loss = G[G["E3%"] >= 20], G[G["E3%"] <= -10]
    print("\n== 大肉 vs 大亏 中位数(每窗口) ==")
    for n in NS:
        c = f"前{n}日%"
        print(f"  前{n}日: 肉{meat[c].median():+.1f} vs 亏{loss[c].median():+.1f} "
              f"(全体{G[c].median():+.1f})")

    G.to_csv(f"{OUT}/汇总/命中票前N日涨幅.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
