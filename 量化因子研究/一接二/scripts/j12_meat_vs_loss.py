# -*- coding: utf-8 -*-
"""一接二 · 大肉票 vs 大亏票 全维度对撞(找被忽略的判别器)。

大肉 = E3 ≥ +20; 大亏 = E3 ≤ -10; 其余 = 中间票。
A 名单: 全部大肉/大亏逐票列出(看具体票)
B 数值维对撞: 大肉中位 vs 大亏中位 vs 中间票中位 + 分离度排序(找被忽略的条件)
C 分类维对撞: 各档位的大肉数/大亏数/肉亏比
D 双维交叉: 肉亏分离最大的两维交叉, 找纯肉格/纯亏格
"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"
MEAT_TH, LOSS_TH = 20, -10


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
             & d["买入开盘%"].between(7.5, 8.5, inclusive="left")].copy()


def main():
    d = load()
    G = g1s1(d)
    if "市值亿" in G.columns:
        G["市值亿"] = G["市值亿"] / 1e8   # stocks.market_cap 原值是元, 换成亿
    G["阵营"] = np.where(G["E3%"] >= MEAT_TH, "肉", np.where(G["E3%"] <= LOSS_TH, "亏", "中"))
    meat = G[G["阵营"] == "肉"]
    loss = G[G["阵营"] == "亏"]
    mid = G[G["阵营"] == "中"]
    lines = [f"# 一接二 · 大肉({MEAT_TH}+) vs 大亏({LOSS_TH}-) 对撞", "",
             f"命中428笔 = 大肉{len(meat)} + 大亏{len(loss)} + 中间{len(mid)}", ""]

    # A 名单
    lines.append("## A 大肉票全名单")
    for _, r in meat.sort_values("E3%", ascending=False).iterrows():
        lines.append(f"- {r['买入日'].date()} {r['名称']}({r['地基阴阳']}) E3{r['E3%']:+.0f} "
                     f"今开{r['买入开盘%']:+.1f} 换手{r['首板换手%']:.1f} 量比{r['首板量比']:.1f} "
                     f"开口{r['首板开口%']:.1f} 板型{r['首板板型']} 首板开{r['首板开盘%']:+.1f} "
                     f"距MA20{r['地基距MA20%']:+.1f} 距60高{r['地基距60高%']:+.1f} "
                     f"前10{r['前10日涨幅%']:+.1f} 前20{r['前20日涨幅%']:+.1f} 地基{r['地基涨跌%']:+.1f} "
                     f"底盘{r['底盘纯度']}(连{r['60日最大连板']}) 市值{r['市值亿'] if r['市值亿'] == r['市值亿'] else '—'} "
                     f"均线{r['均线']} 涨停家数{int(r['昨日涨停家数'])}")
    lines.append("\n## A2 大亏票全名单")
    for _, r in loss.sort_values("E3%").iterrows():
        lines.append(f"- {r['买入日'].date()} {r['名称']}({r['地基阴阳']}) E3{r['E3%']:+.0f} "
                     f"今开{r['买入开盘%']:+.1f} 换手{r['首板换手%']:.1f} 量比{r['首板量比']:.1f} "
                     f"开口{r['首板开口%']:.1f} 板型{r['首板板型']} 首板开{r['首板开盘%']:+.1f} "
                     f"距MA20{r['地基距MA20%']:+.1f} 距60高{r['地基距60高%']:+.1f} "
                     f"前10{r['前10日涨幅%']:+.1f} 前20{r['前20日涨幅%']:+.1f} 地基{r['地基涨跌%']:+.1f} "
                     f"底盘{r['底盘纯度']}(连{r['60日最大连板']}) 市值{r['市值亿'] if r['市值亿'] == r['市值亿'] else '—'} "
                     f"均线{r['均线']} 涨停家数{int(r['昨日涨停家数'])}")

    # B 数值维对撞
    num_dims = ["首板换手%", "首板量比", "首板开口%", "首板开盘%", "地基距MA20%", "地基距60高%",
                "前10日涨幅%", "前20日涨幅%", "地基涨跌%", "60日最大连板", "60日板数",
                "市值亿", "昨日涨停家数", "买入开盘%"]
    lines.append("\n## B 数值维对撞(中位数: 大肉 vs 大亏 vs 中间 | 分离度=|肉-亏|/中间IQR)")
    rows = []
    for c in num_dims:
        m, l, k = meat[c].median(), loss[c].median(), mid[c].median()
        iqr = (mid[c].quantile(0.75) - mid[c].quantile(0.25)) or 1
        rows.append((c, m, l, k, abs(m - l) / iqr))
    for c, m, l, k, sep in sorted(rows, key=lambda x: -x[4]):
        lines.append(f"- {c}: 肉{m:+.1f} vs 亏{l:+.1f} (中间{k:+.1f}) 分离度{sep:.2f}")

    # C 分类维对撞
    lines.append("\n## C 分类维对撞(各档: 肉数/亏数/肉亏比)")
    cat_dims = [("首板板型", None), ("底盘纯度", None), ("均线", None),
                ("换手档", pd.cut(G["首板换手%"], [-.01, 3, 5, 8, 12, 10000],
                              labels=["<3", "3~5", "5~8", "8~12", "12+"])),
                ("量比档", pd.cut(G["首板量比"], [-.01, 1, 1.5, 2, 10000],
                              labels=["<1缩", "1~1.5", "1.5~2", "2+放"])),
                ("开口档", pd.cut(G["首板开口%"], [-.01, 0.01, 1, 2, 100],
                              labels=["未开口", "0~1", "1~2", "2+"])),
                ("首板开档", pd.cut(G["首板开盘%"], [-99, 0, 3, 7, 99],
                              labels=["低开", "0~3", "3~7", "7+"])),
                ("距MA20档", pd.cut(G["地基距MA20%"], [-99, -5, 0, 5, 99],
                                labels=["深坑<-5", "-5~0", "0~5骑线", "5+上方"])),
                ("前10档", pd.cut(G["前10日涨幅%"], [-99, -5, 0, 5, 99],
                              labels=["深跌", "跌", "平涨", "涨"])),
                ("市值档", pd.cut(G["市值亿"], [-.01, 30, 60, 120, 300, 1e9],
                              labels=["<30亿", "30~60", "60~120", "120~300", "300+"])),
                ("连板档", pd.cut(G["60日最大连板"].astype(float), [-1, 0.5, 1.5, 3.5, 99],
                              labels=["无板", "孤立1板", "2~3板", "4+板"])),
                ("涨停家数档", pd.cut(G["昨日涨停家数"], [-1, 40, 80, 999],
                                 labels=["冰点<40", "40~80", ">80"])),
                ("持有档", G["持有天数"].map(lambda x: "当日走" if x == 1 else "2~3天" if x <= 3 else "4+天"))]
    for name, buckets in cat_dims:
        col = buckets if buckets is not None else G[name]
        lines.append(f"\n### {name}")
        for v in pd.Series(col).dropna().unique():
            mmask = (col == v) & (G["阵营"] == "肉")
            lmask = (col == v) & (G["阵营"] == "亏")
            nm, nl = int(mmask.sum()), int(lmask.sum())
            base = G[col == v]
            lines.append(f"- {v}: 肉{nm}/亏{nl} 比{(nm / nl if nl else float('inf')):.1f} "
                         f"| 档内肉率{nm / len(base) * 100:.0f}% 亏率{nl / len(base) * 100:.0f}% "
                         f"(档均{base['E3%'].mean():+.2f} n={len(base)})")

    # D 肉亏名单年份分布
    lines.append("\n## D 肉亏年份分布")
    for y in sorted(G["年"].unique()):
        sub = G[G["年"] == y]
        lines.append(f"- {y}: 肉{(sub['阵营'] == '肉').sum()} 亏{(sub['阵营'] == '亏').sum()} "
                     f"({(sub['阵营'] == '肉').sum() / max(1, (sub['阵营'] != '中').sum()) * 100:.0f}%肉)")

    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/大肉大亏对撞.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
