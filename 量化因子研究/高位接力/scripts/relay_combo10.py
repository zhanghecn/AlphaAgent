# -*- coding: utf-8 -*-
"""高位接力 · B/C/D 组细边界扫描（第三十二遍）。

A 族同款方法复制到 B(二接三阴)/C(三接四阳)/D(三接四阴):
  ① 今开全窗细箱边际  ② 一板/二板(/三板)细箱边际  ③ 链矩阵(right=False)
  ④ 换手率维度  ⑤ 候选格分年+逐票。
用法: uv run python relay_combo10.py B|C|D
"""
import sys
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 480)
pd.set_option("display.max_rows", 400)

GROUP = sys.argv[1] if len(sys.argv) > 1 else "B"
GMAP = {
    "B": ("二接三", "阴"),          # 链=一板×二板, 今天=三板位
    "C": ("三接四", "阳"),          # 链=一板×二板×三板, 今天=四板位
    "D": ("三接四", "阴"),
}


def load():
    grp, yy = GMAP[GROUP]
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    M = E[~E["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["胜"] = ~M["坏票"].fillna(True).astype(bool)
    return M[(M["组"] == grp) & (M["阴阳"] == yy)
             & (M["买入开盘%"] < 9.5)].copy()   # 正常开盘全窗(不限今开档)


def rep(df, label, show_year=True):
    if not len(df):
        print(f"{label}: 0笔")
        return
    extra = ""
    if show_year:
        y = df.groupby("年").agg(n=("胜", "size"), w=("胜", "mean"))
        extra = " | " + " ".join(f"{i}年{int(r['n'])}笔{r['mean']*100:.0f}%"
                                 for i, r in y.iterrows())
    print(f"{label}: {len(df):3d}笔 胜{df['胜'].mean()*100:3.0f}% "
          f"连板{df['次日连板'].mean()*100:3.0f}% 均{df['持有到断板%'].mean():+7.2f}{extra}")


def scan(M, col, bins, labels, title):
    print("=" * 110)
    print(title)
    print("=" * 110)
    t = M.groupby(pd.cut(M[col], bins, labels=labels, right=False),
                  observed=False).agg(n=("代码", "size"), 胜率=("胜", "mean"),
                                      收益=("持有到断板%", "mean"),
                                      连板率=("次日连板", "mean"))
    print(t.round(3).to_string())
    print()


if __name__ == "__main__":
    S = load()
    grp, yy = GMAP[GROUP]
    print(f"### {GROUP}组 = {grp}·{yy}地基 × 正常开盘全窗: {len(S)}笔\n")

    # ── ① 今开全窗细箱 ──
    scan(S, "买入开盘%", [-99, -3, 0, 1, 2, 3, 4, 5, 6, 7, 8.5, 9.5],
         ["<-3", "-3~0", "0~1", "1~2", "2~3", "3~4", "4~5", "5~6",
          "6~7", "7~8.5", "8.5~9.5"],
         f"① {GROUP}组 今天开盘% 全窗细箱")

    # ── ② 链上板细箱 ──
    scan(S, "b1开盘%", [-99, 0, 1, 3, 5, 7, 99],
         ["<0", "0~1", "1~3", "3~5", "5~7", "≥7"], f"②a {GROUP}组 一板开盘%")
    scan(S, "b2开盘%", [-99, 0, 1, 3, 5, 7, 8.5, 9.5, 99],
         ["<0", "0~1", "1~3", "3~5", "5~7", "7~8.5", "8.5~9.5", "一字"],
         f"②b {GROUP}组 二板开盘%")
    if GROUP in ("C", "D"):
        scan(S, "b3开盘%", [-99, 0, 1, 3, 5, 7, 8.5, 9.5, 99],
             ["<0", "0~1", "1~3", "3~5", "5~7", "7~8.5", "8.5~9.5", "一字"],
             f"②c {GROUP}组 三板开盘%")

    # ── ③ 链矩阵: 一板3档 × 二板细档 ──
    B1C = pd.cut(S["b1开盘%"], [-99, 0, 3, 99], labels=["一板<0", "一板0~3", "一板≥3"],
                 right=False)
    B2C = pd.cut(S["b2开盘%"], [-99, 0, 1, 3, 5, 7, 8.5, 9.5, 99],
                 labels=["<0", "0~1", "1~3", "3~5", "5~7", "7~8.5", "8.5~9.5", "一字"],
                 right=False)
    print("=" * 110)
    print(f"③ {GROUP}组 一板×二板 矩阵 (今开<9.5 全窗)")
    print("=" * 110)
    for (a, b), sub in S.groupby([B1C, B2C], observed=True):
        rep(sub, f"{a} × 二板{b}", show_year=False)
    print()

    if GROUP in ("C", "D"):
        # 三板×今开 矩阵(三接四专属)
        B3C = pd.cut(S["b3开盘%"], [-99, 0, 3, 7, 9.5, 99],
                     labels=["<0", "0~3", "3~7", "7~9.5", "一字"], right=False)
        TC = pd.cut(S["买入开盘%"], [-99, 0, 3, 6, 9.5],
                    labels=["今<0", "今0~3", "今3~6", "今6~9.5"], right=False)
        print("=" * 110)
        print(f"③b {GROUP}组 三板 × 今开 矩阵")
        print("=" * 110)
        for (a, b), sub in S.groupby([B3C, TC], observed=True):
            rep(sub, f"三板{a} × {b}", show_year=False)
        print()

    # ── ④ 换手率维度 ──
    scan(S, "b2换手%", [-1, 3, 5, 8, 12, 999],
         ["<3", "3~5", "5~8", "8~12", "≥12"], f"④a {GROUP}组 二板换手率%")
    if GROUP in ("C", "D"):
        scan(S, "b3换手%", [-1, 3, 5, 8, 12, 999],
             ["<3", "3~5", "5~8", "8~12", "≥12"], f"④b {GROUP}组 三板换手率%")
