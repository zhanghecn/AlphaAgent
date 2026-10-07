# -*- coding: utf-8 -*-
"""一接二 · 第5步联动联调: 主候选格内部残余判别力 + 阳组独立验证 + 机制外推。

主候选(第4步定稿方向):
  P1 = 阴地基 × 今开7~9.5 (340笔 53% +3.22 四年全正) —— 旗舰母格
  金核 = 阴 × 距MA20<-5 × 今开7~9.5 (56笔 62% +7.11)
毒格: 贴顶全维 / 今开顶格 / T字×今开<4 / 一字×前10日5~10

联调问题:
  Q1 P1格内还有没有残余毒格(逐维扫描 340 笔)
  Q2 阳组有没有独立的第二曲线(阳×低位/阳×前波连板 成色)
  Q3 机制外推: 「坑越深越肥」在阴格内是否单调(距MA20五档/位置五档/前20日档)
  Q4 今开细档单调性(6/7/8/8.5/9.5 的阴格子)
  Q5 换手/量比/市值/板型在阴格内的残余判别力
"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[(E["段"] == "主窗") & (~E["未完"])].copy()
    d["首板换手细"] = pd.cut(d["首板换手%"], [-.01, 3, 5, 8, 12, 20, 10000],
                         labels=["<3死", "3~5", "5~8", "8~12", "12~20", "20+"])
    d["市值档"] = pd.cut(d["市值亿"], [-.01, 30, 60, 120, 300, 1e9],
                      labels=["<30亿", "30~60", "60~120", "120~300", "300+"])
    d["距MA20五档"] = pd.cut(d["地基距MA20%"], [-99, -10, -5, 0, 5, 99],
                        labels=["深下<-10", "-10~-5", "-5~0", "0~5骑线", "5+上方"])
    d["首板开档"] = pd.cut(d["首板开盘%"], [-99, 0, 3, 7, 9.5, 99],
                        labels=["低开", "0~3", "3~7", "7~9.5", "顶格"])
    d["前20日档"] = pd.cut(d["前20日涨幅%"], [-99, -15, -5, 0, 5, 15, 99],
                        labels=["深跌", "跌", "平", "涨", "半山5~15", "急涨15+"])
    d["地基涨跌档"] = pd.cut(d["地基涨跌%"], [-99, -5, -3, 0, 3, 99],
                         labels=["大阴-5", "中阴", "小阴", "小阳", "中阳3+"])
    return d


def score(sub):
    if len(sub) == 0:
        return None
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    allpos = all(r["mean"] > 0 for _, r in yr.iterrows()) and len(yr) >= 3
    return (f"{len(sub)}笔 胜{(sub['E3%'] > 0).mean() * 100:.0f}% 均{sub['E3%'].mean():+.2f} "
            f"中位{sub['E3%'].median():+.2f} {'✅全正' if allpos else '❌'} ｜ "
            + " / ".join(f"{y}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows()))


def main():
    d = load()
    m7 = d["买入开盘%"].between(7, 9.5, inclusive="left")
    yin = d["地基阴阳"] == "阴"
    P1 = yin & m7
    lines = ["# 一接二 · 第5步联调", ""]

    lines.append("## Q1 P1(阴×今开7~9.5)格内逐维残余判别力")
    p1 = d[P1]
    for dim in ["位置五档", "距MA20五档", "底盘纯度", "首板板型", "首板开档", "首板换手细",
                "市值档", "前20日档", "地基涨跌档", "均线"]:
        lines.append(f"\n### {dim} (P1内)")
        for v, sub in p1.groupby(dim, observed=True):
            if len(sub) >= 5:
                lines.append(f"- {v}: {score(sub)}")

    lines.append("\n## Q2 阳组第二曲线验证(今开7~9.5内)")
    yang = d[(d["地基阴阳"] == "阳") & m7]
    for name, m in [
        ("阳×低位", yang["位置五档"] == "低位"),
        ("阳×前波连板", yang["底盘纯度"] == "前波连板"),
        ("阳×低位×前波连板", (yang["位置五档"] == "低位") & (yang["底盘纯度"] == "前波连板")),
        ("阳×5+上方MA20", yang["地基距MA20%"] >= 5),
        ("阳×距MA20 5+ ×前波连板", (yang["地基距MA20%"] >= 5) & (yang["底盘纯度"] == "前波连板")),
        ("阳×前20日急涨15+", yang["前20日涨幅%"] >= 15),
    ]:
        sub = yang[m]
        if len(sub) >= 5:
            lines.append(f"- {name}: {score(sub)}")

    lines.append("\n## Q3 机制外推: 坑深单调性(全池今开7~9.5, 不限阴阳)")
    hot = d[m7]
    for name, m in [("距MA20深下<-10", hot["地基距MA20%"] < -10),
                    ("距MA20 -10~-5", hot["地基距MA20%"].between(-10, -5, inclusive="left")),
                    ("距MA20 -5~0", hot["地基距MA20%"].between(-5, 0, inclusive="left")),
                    ("距MA20 0~5骑线", hot["地基距MA20%"].between(0, 5, inclusive="left")),
                    ("距MA20 5+上方", hot["地基距MA20%"] >= 5)]:
        lines.append(f"- {name}: {score(hot[m])}")

    lines.append("\n## Q4 阴×今开细档单调性")
    for a, b in [(5, 6), (6, 7), (7, 7.5), (7.5, 8), (8, 8.5), (8.5, 9.5)]:
        sub = d[yin & d["买入开盘%"].between(a, b, inclusive="left")]
        if len(sub):
            lines.append(f"- 今开{a}~{b}: {score(sub)}")

    lines.append("\n## Q5 阴格内换手/量比/市值/板型(P1内已扫, 此处看阴×6~9.5全档)")
    yin67 = d[yin & d["买入开盘%"].between(6, 9.5, inclusive="left")]
    for name, m in [("首板换手<3", yin67["首板换手%"] < 3),
                    ("首板换手3~8", yin67["首板换手%"].between(3, 8)),
                    ("首板换手8~20", yin67["首板换手%"].between(8, 20)),
                    ("首板换手20+", yin67["首板换手%"] >= 20),
                    ("首板量比<1", yin67["首板量比"] < 1),
                    ("首板量比≥1", yin67["首板量比"] >= 1)]:
        sub = yin67[m]
        if len(sub) >= 5:
            lines.append(f"- {name}: {score(sub)}")

    # P1 月供给与按年分布
    lines.append("\n## P1 供给节奏")
    p1_done = p1[~p1["未完"]]
    lines.append(f"- 主窗44个月共 {len(p1)} 笔, 月均 {len(p1) / p1['月'].nunique():.1f} 笔; "
                 f"有票月 {p1['月'].nunique()}/{d['月'].nunique()}")
    mm = p1.groupby("月").size()
    lines.append(f"- 单月最多 {mm.max()} 笔({mm.idxmax()}), 中位 {mm.median():.0f} 笔/月")
    lines.append(f"- 金核(阴×距MA20<-5)56笔月均 {56 / p1['月'].nunique():.1f} 笔")

    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/联调.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
