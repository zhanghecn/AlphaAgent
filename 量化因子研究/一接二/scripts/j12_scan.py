# -*- coding: utf-8 -*-
"""一接二 · 第3步全景普查: 交叉矩阵 + 连续细切 + 正期望岛/毒格清单。

读 j12_research.py 导出的 全量明细.csv(容器内 /tmp/research/j12_out/),
只做后处理, 不碰数据库。主窗(2023-01起) E3 口径。

格内 = 笔数 胜率E3% 均值E3; ★ = 笔数≥15 且 胜率≥50% 且 E3>+1.5(对齐hpr星标,门槛≥15);
格<5笔只标笔数。输出: 汇总/逐维矩阵.md
"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"
MIN_N, MIN_WR, MIN_E3 = 15, 50.0, 1.5     # ★门槛(计划拍板: 最低笔数≥15)


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[(E["段"] == "主窗") & (~E["未完"])].copy()
    # 连续维度补充细切档
    d["今开细档"] = pd.cut(d["买入开盘%"], [-99, 0, 2, 4, 6, 7, 8, 8.5, 9.5, 99],
                        labels=["低开", "0~2", "2~4", "4~6", "6~7", "7~8", "8~8.5", "8.5~9.5", "顶格"])
    d["首板开档"] = pd.cut(d["首板开盘%"], [-99, 0, 3, 7, 9.5, 99],
                        labels=["低开", "0~3", "3~7", "7~9.5", "顶格"])
    d["前20日档"] = pd.cut(d["前20日涨幅%"], [-99, -15, -5, 0, 5, 15, 99],
                        labels=["深跌", "跌", "平", "涨", "半山5~15", "急涨15+"])
    d["前10日档"] = pd.cut(d["前10日涨幅%"], [-99, -10, -3, 0, 5, 10, 99],
                        labels=["深跌", "跌", "平", "涨", "5~10", "10+透支"])
    d["地基距MA20档"] = pd.cut(d["地基距MA20%"], [-99, -10, -5, 0, 5, 99],
                           labels=["深下", "-10~-5", "-5~0", "0~5", "5+上方"])
    d["首板换手细"] = pd.cut(d["首板换手%"], [-.01, 3, 5, 8, 12, 20, 10000],
                         labels=["<3死", "3~5", "5~8", "8~12", "12~20", "20+"])
    d["市值档"] = pd.cut(d["市值亿"], [-.01, 30, 60, 120, 300, 1e9],
                      labels=["<30亿", "30~60", "60~120", "120~300", "300+"])
    d["地基涨跌档"] = pd.cut(d["地基涨跌%"], [-99, -5, -3, 0, 3, 99],
                         labels=["大阴-5", "中阴", "小阴", "小阳", "中阳3+"])
    d["首板量比细"] = pd.cut(d["首板量比"], [-.01, 1, 1.5, 2, 3, 10000],
                         labels=["<1缩量", "1~1.5", "1.5~2", "2~3", "3+放量"])
    return d


def cell(sub):
    n = len(sub)
    if n < 5:
        return f"{n}笔"
    wr = (sub["E3%"] > 0).mean() * 100
    mn = sub["E3%"].mean()
    star = "★" if (n >= MIN_N and wr >= MIN_WR and mn > MIN_E3) else ""
    return f"{n}笔{wr:.0f}%{mn:+.2f}{star}"


def matrix(d, row_dim, col_dim, title, lines):
    lines.append(f"\n### {title}\n")
    cols = [c for c in d[col_dim].dtype.categories] if hasattr(d[col_dim].dtype, "categories") \
        else sorted(d[col_dim].dropna().unique())
    rows = [r for r in d[row_dim].dtype.categories] if hasattr(d[row_dim].dtype, "categories") \
        else sorted(d[row_dim].dropna().unique())
    lines.append("| 行\\列 | " + " | ".join(str(c) for c in cols) + " |")
    lines.append("|" + "---|" * (len(cols) + 1))
    for r in rows:
        cells = []
        for c in cols:
            sub = d[(d[row_dim] == r) & (d[col_dim] == c)]
            cells.append(cell(sub) if len(sub) else "—")
        lines.append(f"| {r} | " + " | ".join(cells) + " |")


def years_line(sub):
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    return " / ".join(f"{y[:4]}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows())


def stars_and_poisons(d, lines):
    """全交叉星格扫描: 两两维度组合找★格和毒格(笔数≥15且E3<-2)。"""
    dims = ["地基阴阳", "位置五档", "底盘纯度", "首板板型", "今开档", "均线", "首板破60高",
            "首板开档", "前20日档", "前10日档", "地基距MA20档", "首板换手细", "市值档",
            "地基涨跌档", "首板量比细", "今开细档"]
    stars, poisons = [], []
    for a in range(len(dims)):
        for b in range(a + 1, len(dims)):
            da, db = dims[a], dims[b]
            for va in d[da].dropna().unique():
                for vb in d[db].dropna().unique():
                    sub = d[(d[da] == va) & (d[db] == vb)]
                    n = len(sub)
                    if n < MIN_N:
                        continue
                    wr = (sub["E3%"] > 0).mean() * 100
                    mn = sub["E3%"].mean()
                    tag = f"{da}={va} × {db}={vb}"
                    if wr >= MIN_WR and mn > MIN_E3:
                        stars.append((n, wr, mn, tag, years_line(sub)))
                    elif mn < -2.0:
                        poisons.append((n, wr, mn, tag, years_line(sub)))
    stars.sort(key=lambda x: -x[2])
    poisons.sort(key=lambda x: x[2])
    lines.append(f"\n### ★格清单(笔数≥{MIN_N} 胜率≥{MIN_WR}% E3>+{MIN_E3}, 按均值降序)\n")
    lines.append("| 笔数 | 胜率 | E3均值 | 格子 | 分年 |")
    lines.append("|---|---|---|---|---|")
    for n, wr, mn, tag, yr in stars[:60]:
        lines.append(f"| {n} | {wr:.0f}% | {mn:+.2f} | {tag} | {yr} |")
    lines.append(f"\n### 毒格清单(笔数≥{MIN_N} 且 E3<-2, 按均值升序)\n")
    lines.append("| 笔数 | 胜率 | E3均值 | 格子 | 分年 |")
    lines.append("|---|---|---|---|---|")
    for n, wr, mn, tag, yr in poisons[:40]:
        lines.append(f"| {n} | {wr:.0f}% | {mn:+.2f} | {tag} | {yr} |")


def main():
    d = load()
    lines = [f"# 一接二 · 第3步全景普查(主窗 {len(d)} 笔已完, E3 口径)", ""]
    lines.append(f"格内=笔数 胜率E3% 均值E3; ★=笔数≥{MIN_N}且胜率≥{MIN_WR}%且E3>+{MIN_E3}; 格<5笔只标笔数")

    # 今开为列的核心矩阵组
    for row, title in [("地基阴阳", "地基阴阳 × 今开"), ("位置五档", "位置五档 × 今开"),
                       ("首板板型", "首板板型 × 今开"), ("底盘纯度", "底盘纯度 × 今开"),
                       ("首板破60高", "首板破60高 × 今开"), ("首板开档", "首板开档 × 今开"),
                       ("首板换手细", "首板换手细 × 今开"), ("前20日档", "前20日档 × 今开"),
                       ("首板量比细", "首板量比细 × 今开"), ("市值档", "市值档 × 今开"),
                       ("地基距MA20档", "地基距MA20档 × 今开")]:
        matrix(d, row, "今开档", title, lines)
    # 无今开的交叉
    for (r, c, t) in [("位置五档", "底盘纯度", "位置五档 × 底盘纯度"),
                      ("位置五档", "首板板型", "位置五档 × 首板板型"),
                      ("底盘纯度", "首板板型", "底盘纯度 × 首板板型"),
                      ("今开细档", "位置五档", "今开细档 × 位置五档"),
                      ("今开细档", "首板开档", "今开细档 × 首板开档"),
                      ("今开细档", "首板换手细", "今开细档 × 首板换手细"),
                      ("今开细档", "前10日档", "今开细档 × 前10日档"),
                      ("今开细档", "地基涨跌档", "今开细档 × 地基涨跌档")]:
        matrix(d, r, c, t, lines)

    # 核心立方体切片: 今开7~9.5(唯一全正大档)内部
    hot = d[d["今开档"] == "7~9.5"]
    lines.append(f"\n### 金档切片: 今开7~9.5 (n={len(hot)}, 胜{(hot['E3%'] > 0).mean() * 100:.0f}%, "
                 f"均{hot['E3%'].mean():+.2f}) 内部逐维\n")
    for dim in ["位置五档", "底盘纯度", "首板板型", "首板开档", "首板换手细", "前20日档",
                "前10日档", "地基阴阳", "市值档", "首板量比细", "地基距MA20档", "均线"]:
        for v, sub in hot.groupby(dim, observed=True):
            if len(sub) >= 5:
                lines.append(f"- {dim}={v}: {cell(sub)}" + (f" ｜ {years_line(sub)}"
                                                            if len(sub) >= MIN_N else ""))

    stars_and_poisons(d, lines)
    with open(f"{OUT}/汇总/逐维矩阵.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    # 控制台回显星格/毒格头几行
    txt = "\n".join(lines)
    i = txt.find("### ★格清单")
    print(txt[i:i + 3500])


if __name__ == "__main__":
    main()
