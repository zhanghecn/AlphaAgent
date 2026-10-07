# -*- coding: utf-8 -*-
"""一接二 · 差年根因分析: 2021/2022/2026 为什么弱(对照 2023-2025)。

三层拆解:
  A 年度结构: 均值/胜率/中位/封板率/尾部贡献(top3)/大亏数(E3<-10)/环境(涨停家数)
  B 月度定位: 差年里的拖累月 + 当月情绪(昨日涨停家数均值)
  C 环境分层: 情绪档(<40冰点/40~80/>80亢奋) × 分年 —— 差年是否=情绪差年
  D 分支: G1/S1 分年谁拖累
  E 亏损票画像: 差年 vs 好年 的亏损票(E3<=-10)特征对比
"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]].copy()
    if "首开一字" in d.columns:
        d = d[~d["首开一字"]]
    return d


def g1s1(d):
    return d[(d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")
             | (d["地基阴阳"] == "阳") & (d["前10日涨幅%"] < -3)
             & d["买入开盘%"].between(7.5, 8.5, inclusive="left")]


def main():
    d = load()
    G = g1s1(d)
    lines = ["# 一接二 · 差年根因(2021/2022/2026 vs 2023-2025)", ""]

    # A 年度结构
    lines.append("## A 年度结构总账")
    lines.append("| 年 | 笔数 | 胜率 | 均值 | 中位 | 封板率 | top3贡献 | 大亏<-10 | 平均涨停家数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for y, sub in G.groupby("年"):
        top3 = sub.nlargest(3, "E3%")["E3%"].sum()
        lines.append(
            f"| {y} | {len(sub)} | {(sub['E3%'] > 0).mean() * 100:.0f}% | {sub['E3%'].mean():+.2f} "
            f"| {sub['E3%'].median():+.2f} | {sub['封住'].mean() * 100:.0f}% "
            f"| {top3 / len(sub):+.2f}/笔 | {(sub['E3%'] < -10).sum()}笔 "
            f"| {sub['昨日涨停家数'].mean():.0f} |")

    # B 月度定位(差年)
    lines.append("\n## B 差年月度定位(拖累月标 ◀)")
    for y in ["2021", "2022", "2026"]:
        sub = G[G["年"] == y]
        lines.append(f"\n### {y}")
        for m, ms in sub.groupby("月"):
            mk = "◀拖累" if ms["E3%"].mean() < -3 else ""
            lines.append(f"- {m}: {len(ms)}笔 均{ms['E3%'].mean():+.2f} "
                         f"(当月均涨停家数 {ms['昨日涨停家数'].mean():.0f}) {mk}")

    # C 环境分层
    lines.append("\n## C 环境分层(昨日涨停家数档 × 分年, G1∪S1)")
    G = G.copy()
    G["情绪档"] = pd.cut(G["昨日涨停家数"], [-1, 40, 80, 999],
                    labels=["冰点<40", "正常40~80", "亢奋>80"])
    for tag, sub in G.groupby("情绪档", observed=True):
        yr = sub.groupby("年")["E3%"].mean()
        lines.append(f"- {tag}: 合计{len(sub)}笔 均{sub['E3%'].mean():+.2f} "
                     f"胜{(sub['E3%'] > 0).mean() * 100:.0f}% ｜ "
                     + " / ".join(f"{y}:{yr.get(y, float('nan')):+.2f}" for y in
                                  ["2021", "2022", "2023", "2024", "2025", "2026"] if y in yr.index))

    # D 分支分年
    lines.append("\n## D 分支分年")
    for p, mk in [("G1", lambda x: (x["地基阴阳"] == "阴") & x["买入开盘%"].between(7.5, 9.5, inclusive="left")),
                  ("S1", lambda x: (x["地基阴阳"] == "阳") & (x["前10日涨幅%"] < -3) & x["买入开盘%"].between(7.5, 8.5, inclusive="left"))]:
        sub = G[mk(G)]
        yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
        lines.append(f"- {p}: " + " / ".join(
            f"{y}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows()))

    # E 亏损票画像(差年 vs 好年)
    lines.append("\n## E 亏损票画像(E3<=-10, 差年 vs 好年)")
    for tag, years in [("差年21/22/26", ["2021", "2022", "2026"]), ("好年23-25", ["2023", "2024", "2025"])]:
        sub = G[G["年"].isin(years)]
        bad = sub[sub["E3%"] <= -10]
        good = sub[sub["E3%"] > 0]
        lines.append(f"\n### {tag}: 命中{len(sub)}笔, 大亏{len(bad)}笔({len(bad) / len(sub) * 100:.0f}%), "
                     f"大亏合计{bad['E3%'].sum():+.1f}占总盘子{sub['E3%'].sum():+.1f}")
        if len(bad):
            lines.append(f"- 大亏票特征中位: 换手{bad['首板换手%'].median():.1f} "
                         f"距MA20{bad['地基距MA20%'].median():+.1f} 距60高{bad['地基距60高%'].median():+.1f} "
                         f"前10日{bad['前10日涨幅%'].median():+.1f}")
            lines.append(f"- 赚钱票特征中位: 换手{good['首板换手%'].median():.1f} "
                         f"距MA20{good['地基距MA20%'].median():+.1f} 距60高{good['地基距60高%'].median():+.1f} "
                         f"前10日{good['前10日涨幅%'].median():+.1f}")
        top3 = sub.nlargest(3, "E3%")
        lines.append(f"- 最好3笔: " + "、".join(f"{r['买入日'].date()}{r['名称']}{r['E3%']:+.0f}" for _, r in top3.iterrows()))

    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/差年根因.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
