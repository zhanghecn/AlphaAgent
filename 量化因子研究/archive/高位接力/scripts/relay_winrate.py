# -*- coding: utf-8 -*-
"""高位接力 · 胜率关键筛选（第一遍：单维分档扫描）。

读 全量明细.csv（relay_research.py 产出，宿主本地跑，不进容器）：
- 胜率 = 买入后第二天收盘不亏（=1-坏票率）
- 拆两关: 封住关(当天封住率) × 次日关(封住后次日不亏率)
- 每个维度分档, 四组(二接三阴/二接三阳/三接四阴/三接四阳)各自统计,
  按「最好档-最差档胜率差」排序找关键维度
"""
import sys

import numpy as np
import pandas as pd

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)

CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
GROUPS = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]

# 维度分档定义: (列名, 分档边界或None=类别列, 显示名)
DIMS = [
    ("买入开盘%", [-99, 0, 2, 4, 6, 8, 9.5, 99], "买入开盘(竞价结果)"),
    ("买入量比", [0, 0.8, 1.2, 1.8, 3, 99], "买入量比"),
    ("买入换手%", [-1, 5, 10, 15, 20, 30, 99], "买入换手"),
    ("距60日新高%", [-99, -25, -15, -8, -3, 0.01], "地基位置(距60日新高)"),
    ("地基涨跌%", [-99, -5, -3, 0, 3, 99], "地基日涨跌"),
    ("地基前20日涨幅%", [-99, 0, 15, 30, 999], "地基前20日涨幅"),
    ("前波60日最高板", [-1, 0, 2, 3, 99], "前波60日最高板"),
    ("昨日涨停家数", [-1, 30, 50, 80, 9999], "昨日涨停家数(环境)"),
    ("b1板型", None, "首板板型"),
    ("b2板型", None, "二板板型"),
    ("b3板型", None, "三板板型(仅三接四)"),
    ("均线", None, "地基均线排列"),
]


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["胜"] = E["次日收%"] > 0
    E["封后次日胜"] = np.where(E["封住"], E["胜"], np.nan)
    # 链组合: 首板×二板
    E["链组合"] = E["b1板型"] + "→" + E["b2板型"]
    # 均线归并: 全多头+++ / 纠缠(-++或+--) / 其他
    E["均线归并"] = np.where(E["均线"] == "+++", "全多头+++",
                    np.where(E["均线"].isin(["-++", "+--"]), "纠缠(-++/+--)", "其他"))
    return E


def bin_col(s, edges):
    lab = []
    for a, b in zip(edges, edges[1:]):
        lab.append(f"{a}~{b}")
    return pd.cut(s, edges, labels=lab, right=False, include_lowest=True)


def scan_group(E, gname, min_n=30):
    sub = E[E["四组"] == gname]
    out = []
    for col, edges, label in DIMS + [("链组合", None, "链组合(首板×二板)"), ("均线归并", None, "均线三态")]:
        if col == "b3板型" and not gname.startswith("三接四"):
            continue
        if col not in sub.columns:
            continue
        s = sub.copy()
        if edges is not None:
            s["档"] = bin_col(s[col], edges)
        else:
            s["档"] = s[col].fillna("(无)")
        t = s.groupby("档", observed=True).agg(
            n=("胜", "size"),
            封住率=("封住", "mean"),
            胜率=("胜", "mean"),
            次日收益=("次日收%", "mean"),
            封后次日胜=("封后次日胜", "mean"),
            持有到断板=("持有到断板%", "mean"),
        )
        t = t[t["n"] >= min_n]
        if len(t) < 2:
            continue
        spread = t["胜率"].max() - t["胜率"].min()
        out.append((label, spread, t))
    out.sort(key=lambda x: -x[1])
    return out


def fmt_t(t):
    d = t.copy()
    for c in ("封住率", "胜率", "封后次日胜"):
        d[c] = (d[c] * 100).round(0).astype("Int64")
    d["次日收益"] = d["次日收益"].round(2)
    d["持有到断板"] = d["持有到断板"].round(2)
    return d


def main():
    E = load()
    print(f"总样本 {len(E)} 笔（不含数据末端未完）")
    for gname in GROUPS:
        sub = E[E["四组"] == gname]
        print(f"\n{'='*100}\n【{gname}】 n={len(sub)}  总胜率 {sub['胜'].mean()*100:.0f}%  "
              f"封住率 {sub['封住'].mean()*100:.0f}%  封后次日胜率 {sub['封后次日胜'].mean()*100:.0f}%")
        for rank, (label, spread, t) in enumerate(scan_group(E, gname), 1):
            if rank > 6:
                break
            print(f"\n  #{rank} {label}（胜率差 {spread*100:.0f} 个百分点）")
            print(fmt_t(t).to_string())


if __name__ == "__main__":
    main()
