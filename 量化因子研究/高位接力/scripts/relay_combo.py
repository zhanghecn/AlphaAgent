# -*- coding: utf-8 -*-
"""高位接力 · 好差票组合研究（第X遍）：接力过程 × 阴阳中 × 二板 × 首板前3日涨幅。

主人要求：四个维度先分开研究，再组合到一起（不要各研究各的），对「连板影响力」做多维分析。

维度:
- 接力过程 = 链(b1→b2→b3 板型+开盘档序列), 拆成 各板板型 / b1档→b2档开盘序列
- 阴阳 = 地基阴阳(组内已分) + b2开盘「阴/中/阳」三档(阴<0 / 中0~3 / 阳≥3)
- 二板 = b2 板型/开盘/换手梯度 在四组(二接三阴/阳, 三接四阴/阳)的影响力
- 首板前3日 = pre3%(含地基日3日累计涨幅) 五档

结果(连板影响力):
- 封住率 / 次日连板率(再连一板) / 好票率 / 高度增益=最终高度-N / 持有到断板%

宿主机纯CSV: uv run python relay_combo.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
YEARS = ["2023", "2024", "2025", "2026"]

PRE3_BINS = [-99, -5, 0, 5, 10, 99]
PRE3_LABS = ["≤-5", "-5~0", "0~5", "5~10", ">10"]
B3_BINS = [-99, 0, 3, 99]
B3_LABS = ["阴<0", "中0~3", "阳≥3"]

pd.set_option("display.width", 400)
pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 200)


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    P = pd.read_csv(f"{ROOT}/首板前3日明细.csv", dtype={"代码": str})
    M = E.merge(P.drop(columns=["首板日"]), on=["代码", "买入日"], how="inner")
    M = M[~M["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["高度增益"] = M["最终高度"] - M["N"]
    M["b2三档"] = pd.cut(M["b2开盘%"], B3_BINS, labels=B3_LABS)
    M["b1三档"] = pd.cut(M["b1开盘%"], B3_BINS, labels=B3_LABS)
    M["pre3档"] = pd.cut(M["pre3%"], PRE3_BINS, labels=PRE3_LABS)
    M["换手梯度"] = M["b2换手%"] - M["b1换手%"]
    return M


AGG = dict(
    n=("代码", "size"),
    封住率=("封住", "mean"),
    次日连板率=("次日连板", "mean"),
    好票率=("坏票", lambda s: 1 - s.mean()),
    高度增益=("高度增益", "mean"),
    断板收益=("持有到断板%", "mean"),
)


def stat(M, by):
    t = M.groupby(by, observed=True).agg(**AGG).round(3)
    return t


def part1(M):
    print("=" * 90)
    print("第一部分 · 分开研究")
    print("=" * 90)

    print("\n【基线】四组总览")
    print(stat(M, "四组"))

    print("\n" + "-" * 70)
    print("A. 接力过程(链) —— 各板板型")
    print("\nA1. b1板型(首板) × 四组 → 连板")
    print(stat(M, ["b1板型", "四组"]))
    print("\nA2. b2板型(二板) × 四组 → 连板")
    print(stat(M, ["b2板型", "四组"]))
    print("\nA3. b3板型(三板, 仅三接四) → 连板")
    print(stat(M[M["组"] == "三接四"], ["b3板型"]))

    print("\nA4. 二接三 链型(b1板型→b2板型) → 连板 (n≥30)")
    t = stat(M[M["组"] == "二接三"], ["b1板型", "b2板型"])
    print(t[t["n"] >= 30])
    print("\nA5. 三接四 链型(b1→b2→b3板型) → 连板 (n≥20)")
    t = stat(M[M["组"] == "三接四"], ["b1板型", "b2板型", "b3板型"])
    print(t[t["n"] >= 20])

    print("\n" + "-" * 70)
    print("B. 阴阳 —— 地基阴阳(组别) × b2开盘阴阳中三档")
    print("\nB1. b2三档 × 组 → 连板 (阴阳=地基, 三档=b2开盘)")
    print(stat(M, ["组", "阴阳", "b2三档"]))

    print("\n" + "-" * 70)
    print("C. 二板特征 —— 板型×开盘×换手梯度")
    print("\nC1. b2三档 × b2板型 → 连板")
    print(stat(M, ["b2板型", "b2三档"]))
    print("\nC2. 换手梯度(b2-b1) 分档 → 连板")
    M["梯度档"] = pd.cut(M["换手梯度"], [-99, -5, 0, 5, 99], labels=["大缩<-5", "缩-5~0", "平0~5", "扩>5"])
    print(stat(M, ["梯度档", "组"]))

    print("\n" + "-" * 70)
    print("D. 首板前3日涨幅(pre3%) —— 五档 → 连板")
    print("\nD1. pre3档 × 组 → 连板")
    print(stat(M, ["pre3档", "组"]))
    print("\nD2. p3阴阳串(前3日阴阳构成, 早→晚) → 连板 (n≥30)")
    t = stat(M, ["p3阴阳"])
    print(t[t["n"] >= 30])
    print("\nD3. 对照: pre3_exbase%(不含地基日) 五档 → 次日连板率")
    M["exb档"] = pd.cut(M["pre3_exbase%"], PRE3_BINS, labels=PRE3_LABS)
    print(stat(M, ["exb档"])[["n", "次日连板率", "高度增益", "好票率"]])
    print("\nD4. 前3日各日涨幅档(pd1/pd2/pd3=地基日) → 次日连板率")
    for c in ["pd1%", "pd2%", "pd3%"]:
        d = pd.cut(M[c], PRE3_BINS, labels=PRE3_LABS)
        t = M.groupby(d, observed=True).agg(n=("代码", "size"), 次日连板率=("次日连板", "mean")).round(3)
        print(f"\n{c}:"); print(t)


def part2(M):
    print("\n" + "=" * 90)
    print("第二部分 · 组合研究 (不要各研究各的)")
    print("=" * 90)

    print("\nE. 核心交叉: 四组 × b2三档(阴阳中) × pre3档 → 连板影响力")
    for g, sub in M.groupby("四组"):
        print(f"\n===== {g} =====")
        t = sub.groupby(["b2三档", "pre3档"], observed=True).agg(**AGG).round(3)
        print(t)

    print("\n" + "-" * 70)
    print("F. 接力过程进组合: b1三档 × b2三档 × pre3档(合并四组, 分组内看)")
    for g in ["二接三", "三接四"]:
        sub = M[M["组"] == g]
        print(f"\n===== {g}: b1三档 × pre3档 → 次日连板率(只留 n≥25) =====")
        t = sub.groupby(["b1三档", "pre3档"], observed=True).agg(
            n=("代码", "size"), 次日连板率=("次日连板", "mean"), 高度增益=("高度增益", "mean")).round(3)
        print(t[t["n"] >= 25])

    print("\n" + "-" * 70)
    print("G. 三维主效应对比: 各单维 vs 全模型(均值差 = 组合增量)")
    base = M["次日连板"].mean()
    print(f"\n全样本次日连板率基线: {base:.3f}")
    for dim in ["四组", "b2三档", "pre3档", "p3阴阳", "b2板型", "b1三档"]:
        t = M.groupby(dim, observed=True)["次日连板"].agg(["size", "mean"]).round(3)
        t["对基线差"] = (t["mean"] - base).round(3)
        print(f"\n{dim}:"); print(t)


def robust(M, cell_fn, name):
    """核心格子稳健性: 分年方向 + 去最好3笔"""
    sel = cell_fn(M)
    if sel["代码"].count() < 15:
        print(f"{name}: n<15 跳过")
        return
    print(f"\n{name}: n={len(sel)} 次日连板率={sel['次日连板'].mean():.3f} 高度增益={sel['高度增益'].mean():.2f} 好票率={1 - sel['坏票'].mean():.3f}")
    yr = sel.groupby("年").agg(n=("代码", "size"), 次日连板率=("次日连板", "mean"), 断板收益=("持有到断板%", "mean")).round(3)
    print("分年:"); print(yr)
    sub = sel.nlargest(3, "持有到断板%")
    rest = sel.drop(sub.index)
    print(f"去最好3笔后: n={len(rest)} 次日连板率={rest['次日连板'].mean():.3f} 断板收益={rest['持有到断板%'].mean():.2f} 好票率={1 - rest['坏票'].mean():.3f}")


if __name__ == "__main__":
    M = load()
    print(f"样本 {len(M)} 笔 (未完已剔除)")
    part1(M)
    part2(M)
