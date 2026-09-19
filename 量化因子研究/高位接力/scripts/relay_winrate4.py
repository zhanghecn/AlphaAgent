# -*- coding: utf-8 -*-
"""高位接力 · 胜率关键第四遍：静态条件两两组合穷举。

第三遍的贪心树每层只钻最好两格, 可能漏组合。本遍:
1. 每个维度里胜率高于池子且样本够的档位 = 候选条件原子
2. 两两取交集, 报 样本量≥25 的组合, 按胜率排序
3. 头部组合给分年明细 + 按月明细, 验是不是个别年份/月份撑的
全部条件仍是买入前可知的静态信息（含竞价开盘）。
"""
import itertools

import numpy as np
import pandas as pd

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)

CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
GROUPS = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]

DIMS = [
    ("买入开盘%", [-99, 0, 2, 4, 6, 8, 9.5, 99], "竞价开盘"),
    ("距60日新高%", [-99, -25, -15, -8, -3, 0.01], "地基位置"),
    ("地基涨跌%", [-99, -5, -3, 0, 3, 99], "地基日涨跌"),
    ("地基前20日涨幅%", [-99, 0, 15, 30, 999], "地基前20日涨幅"),
    ("前波60日最高板", [-1, 0, 2, 3, 99], "前波60日"),
    ("距前波末板", [-2, -0.5, 5, 10, 20, 9999], "距前波末板"),
    ("昨日涨停家数", [-1, 30, 50, 80, 9999], "昨日涨停家数"),
    ("b1开盘%", [-99, 0, 3, 6, 9.5, 99], "首板开盘"),
    ("b2开盘%", [-99, 0, 3, 6, 9.5, 99], "二板开盘"),
    ("b1换手%", [-1, 3, 6, 10, 15, 99], "首板换手"),
    ("b2换手%", [-1, 3, 6, 10, 15, 99], "二板换手"),
    ("均线归并", None, "均线三态"),
    ("b1板型", None, "首板板型"),
    ("b2板型", None, "二板板型"),
    ("链组合", None, "链组合"),
]


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["胜"] = E["次日收%"] > 0
    E["链组合"] = E["b1板型"] + "→" + E["b2板型"]
    E["均线归并"] = np.where(E["均线"] == "+++", "全多头",
                    np.where(E["均线"].isin(["-++", "+--"]), "纠缠", "其他"))
    E["距前波末板"] = E["距前波末板"].fillna(-1)
    return E


def bins_of(s, col, edges):
    if edges is not None:
        return pd.cut(s[col], edges, right=False).astype(str)
    return s[col].fillna("(无)").astype(str)


def yearly(sub):
    by = sub.groupby("年").agg(n=("持有到断板%", "size"), 收益=("持有到断板%", "mean"),
                               胜率=("胜", "mean"))
    return " ".join(f"{y}:{r.收益:+.2f}/{r.胜率*100:.0f}%(n={r.n:.0f})" for y, r in by.iterrows())


def monthly_line(sub):
    by = sub.groupby("月").agg(n=("持有到断板%", "size"), 收益=("持有到断板%", "mean"))
    neg = by[by["收益"] < 0]
    return f"{len(by)}个月, 负月{len(neg)}个" + \
           (f"（最差: {neg['收益'].idxmin()} {neg['收益'].min():+.2f}）" if len(neg) else "")


def main():
    E = load()
    out = []
    for gname in GROUPS:
        sub = E[E["四组"] == gname]
        pool_wr = sub["胜"].mean()
        out.append(f"\n{'='*100}\n【{gname}】n={len(sub)} 池胜率{pool_wr*100:.0f}%")
        # 1) 收集原子: 每维度里 胜率>池+3pp 且 n>=25 的档
        atoms = []   # (名字, mask)
        for col, edges, label in DIMS:
            if col not in sub.columns or sub[col].isna().all():
                continue
            b = bins_of(sub, col, edges)
            for lv, grp in sub.groupby(b, observed=True):
                if len(grp) >= 25 and grp["胜"].mean() > pool_wr + 0.03:
                    atoms.append((f"{label}={lv}", (b == lv)))
        out.append(f"  候选原子 {len(atoms)} 个: " + " | ".join(a for a, _ in atoms))
        # 2) 两两组合
        combos = []
        for (n1, m1), (n2, m2) in itertools.combinations(atoms, 2):
            m = (m1 & m2).fillna(False)
            s2 = sub[m]
            if len(s2) >= 25:
                combos.append((s2["胜"].mean(), s2["持有到断板%"].mean(), len(s2), n1, n2, s2))
        combos.sort(key=lambda x: -x[0])
        out.append(f"\n  两两组合头部（胜率≥55% 且 n≥25）:")
        shown = 0
        for wr, bw, n, n1, n2, s2 in combos:
            if wr < 0.55 or shown >= 10:
                break
            out.append(f"    {n1} × {n2}  →  n={n} 胜率{wr*100:.0f}% 持有{bw:+.2f}")
            out.append(f"        分年: {yearly(s2)}")
            out.append(f"        按月: {monthly_line(s2)}")
            shown += 1
        if shown == 0:
            out.append("    （没有胜率≥55%且n≥25的两条件组合）")
    text = "\n".join(out)
    print(text)
    with open("/root/project/ai/vnpy/量化因子研究/高位接力/汇总/静态组合穷举.md", "w", encoding="utf-8") as f:
        f.write("# 高位接力 · 静态条件两两组合穷举（2026-09-19）\n\n```\n" + text + "\n```\n")


if __name__ == "__main__":
    main()
