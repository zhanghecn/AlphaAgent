# -*- coding: utf-8 -*-
"""高位接力 · 首板×二板×进三竞价 三维立方体（第十六遍, 主人纠正: 不能单独看首板一字）。

阴阳分开, 每组一个立方体: 首板板型(一字/下影/实体) × 二板板型 × 进三竞价开盘档。
每个单元 n/胜率/持有; 重点回答: 首板一字在哪些组合里好、哪些组合里差。
好组合给分年。
"""
import numpy as np
import pandas as pd

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)
CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
YEARS = ["2023", "2024", "2025", "2026"]
BOARD = ["一字", "下影", "实体"]
AUC = [(-99, 0, "低开"), (0, 3, "0~3"), (3, 6, "3~6"), (6, 9.5, "6~9.5"), (9.5, 99, "顶格开")]


def yearly_str(sub):
    by = sub.groupby("年")["持有到断板%"].agg(["size", "mean"])
    return " ".join(f"{y}:{float(by.loc[y,'mean']):+.2f}(n={int(by.loc[y,'size'])})"
                    for y in YEARS if y in by.index)


def stat(sub):
    return f"{(sub['次日收%'] > 0).mean() * 100:.0f}%/{sub['持有到断板%'].mean():+.1f}(n={len(sub)})"


def main():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    E["竞价档"] = pd.cut(E["买入开盘%"], [a[0] for a in AUC] + [99], right=False,
                       labels=[a[2] for a in AUC])

    for gname in ["二接三阴", "二接三阳"]:
        sub = E[E["四组"] == gname]
        print(f"\n{'='*110}\n【{gname}】n={len(sub)}  池: {stat(sub)}")
        print("\n■ 首板板型 × 二板板型（胜率/持有/n）")
        t = sub.groupby(["b1板型", "b2板型"], observed=True).agg(
            n=("次日收%", "size"), 胜率=("次日收%", lambda s: (s > 0).mean()),
            持有=("持有到断板%", "mean"))
        pv = {}
        for (b1, b2), r in t.iterrows():
            pv.setdefault(b1, {})[b2] = f"{r['胜率']*100:.0f}%/{r['持有']:+.1f}(n={int(r['n'])})"
        header = "| 首板＼二板 | " + " | ".join(BOARD) + " |"
        print(header); print("|---|---|---|---|")
        for b1 in BOARD:
            print(f"| {b1} | " + " | ".join(pv.get(b1, {}).get(b2, "--") for b2 in BOARD) + " |")

        print("\n■ 立方体: 每个「首板×二板」格内按进三竞价档拆（只列n≥30的首二板格）")
        for b1 in BOARD:
            for b2 in BOARD:
                cell = sub[(sub["b1板型"] == b1) & (sub["b2板型"] == b2)]
                if len(cell) < 30:
                    continue
                print(f"\n  【首板{b1} × 二板{b2}】合计 {stat(cell)}")
                for lo, hi, tag in AUC:
                    s2 = cell[(cell["买入开盘%"] >= lo) & (cell["买入开盘%"] < hi)]
                    if len(s2) >= 8:
                        print(f"    进三{tag:5s} {stat(s2)} | {yearly_str(s2)}")


if __name__ == "__main__":
    main()
