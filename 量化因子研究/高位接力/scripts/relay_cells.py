# -*- coding: utf-8 -*-
"""高位接力 · 第七遍：入围格子最终归拢。

五个分年全正+晃动存活的格子, 精确定义后:
- 逐笔明细导出 汇总/格子明细/ 供主人复核
- 格子间重叠检查(同组两格重叠多少)
- 并集统计
"""
import os

import numpy as np
import pandas as pd

pd.set_option("display.width", 340)
CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
OUTD = "/root/project/ai/vnpy/量化因子研究/高位接力/汇总/格子明细"
YEARS = ["2023", "2024", "2025", "2026"]

CELLS = {
    "二接三阴_二板高开6-9.5_换手微增0-2": lambda E: (E["四组"] == "二接三阴")
        & E["b2开盘%"].between(6, 9.5, inclusive="left")
        & (E["换手梯度"].between(0, 2, inclusive="left")),
    "二接三阳_地基距新高2-9_二板低开": lambda E: (E["四组"] == "二接三阳")
        & E["距60日新高%"].between(-9, -2, inclusive="left") & (E["b2开盘%"] < 0),
    "三接四阴_前波120有3板以上_二板缩量5点": lambda E: (E["四组"] == "三接四阴")
        & (E["前波120日最高板"] >= 3) & (E["换手梯度"] < -5),
    "三接四阴_首板下影_二板实体": lambda E: (E["四组"] == "三接四阴")
        & (E["b1板型"] == "下影") & (E["b2板型"] == "实体"),
    "三接四阳_地基距新高8-15_均线不齐_无前波": lambda E: (E["四组"] == "三接四阳")
        & E["距60日新高%"].between(-15, -8, inclusive="left")
        & (~E["均线"].isin(["+++", "-++", "+--"])) & (E["前波60日最高板"] == 0),
}


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    return E


def yearly_str(sub):
    by = sub.groupby("年")["持有到断板%"].agg(["size", "mean"])
    return " ".join(f"{y}:{float(by.loc[y,'mean']):+.2f}(n={int(by.loc[y,'size'])})"
                    for y in YEARS if y in by.index)


def main():
    E = load()
    os.makedirs(OUTD, exist_ok=True)
    cells = {}
    for name, fn in CELLS.items():
        cells[name] = E[fn(E)].copy()

    print("===== 五个入围格子 =====")
    for name, s in cells.items():
        tail3 = s["持有到断板%"].nlargest(3).sum() / max(s["持有到断板%"].sum(), 1e-9) * 100
        mo = s.groupby("月")["持有到断板%"].mean()
        print(f"\n【{name}】n={len(s)} 胜率{s['胜'].mean()*100:.0f}% "
              f"持有{s['持有到断板%'].mean():+.2f} 中位{s['持有到断板%'].median():+.2f} "
              f"尾3占{tail3:.0f}% 按月{len(mo)}个/负{(mo<0).sum()}个")
        print(f"  分年: {yearly_str(s)}")
        s.to_csv(f"{OUTD}/{name}.csv", index=False, encoding="utf-8-sig")

    print("\n===== 三接四阴两格重叠 =====")
    a, b = cells["三接四阴_前波120有3板以上_二板缩量5点"], cells["三接四阴_首板下影_二板实体"]
    ka = set(zip(a["代码"], a["买入日"]))
    kb = set(zip(b["代码"], b["买入日"]))
    print(f"前波缩量 {len(ka)} 笔, 下影实体 {len(kb)} 笔, 重叠 {len(ka & kb)} 笔")

    print("\n===== 五格并集 =====")
    allc = pd.concat(cells.values())
    key = allc["代码"] + allc["买入日"]
    dup = key.duplicated().sum()
    print(f"合计 {len(allc)} 笔（跨格重复 {dup} 笔）")
    allu = allc.drop_duplicates(subset=["代码", "买入日"])
    print(f"去重后 {len(allu)} 笔 胜率{allu['胜'].mean()*100:.0f}% "
          f"持有{allu['持有到断板%'].mean():+.2f} 中位{allu['持有到断板%'].median():+.2f}")
    print(f"  分年: {yearly_str(allu)}")
    mo = allu.groupby("月")["持有到断板%"].mean()
    print(f"  按月: {len(mo)}个月/负{(mo<0).sum()}个")

    print("\n===== 对照：各组池子整体 =====")
    for g in ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]:
        s = E[E["四组"] == g]
        print(f"{g}: n={len(s)} 胜率{s['胜'].mean()*100:.0f}% 持有{s['持有到断板%'].mean():+.2f}")


if __name__ == "__main__":
    main()
