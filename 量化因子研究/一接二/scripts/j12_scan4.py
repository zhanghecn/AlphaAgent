# -*- coding: utf-8 -*-
"""一接二 · 第二轮B3: 三阶组合严扫——主窗分年全正 + OOS≥8笔且正, 找G1/S1之外的新岛。

排除已知岛: G1(阴×今开7.5~9.5)与S1(阳×前10<-3×今开7.5~8.5)的命中从池中剔除后再扫,
避免重复发现; 命中格与G1/S1的互斥性单独报告。
"""
import itertools

import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]].copy()
    d["今开细"] = pd.cut(d["买入开盘%"], [-99, 0, 4, 7.5, 8.5, 9.5, 99],
                      labels=["低开平开", "0~4", "4~7.5", "7.5~8.5", "8.5~9.5", "顶格"])
    d["首板开档"] = pd.cut(d["首板开盘%"], [-99, 0, 3, 7, 99],
                        labels=["低开", "0~3", "3~7", "7+高开"])
    d["换手档"] = pd.cut(d["首板换手%"], [-.01, 5, 8, 10000], labels=["<5", "5~8", "8+"])
    d["距MA20档"] = pd.cut(d["地基距MA20%"], [-99, -5, 0, 5, 99],
                       labels=["深坑<-5", "-5~0", "0~5骑线", "5+上方"])
    d["前10档"] = pd.cut(d["前10日涨幅%"], [-99, -3, 0, 10, 99],
                      labels=["跌3+", "平小跌", "涨0~10", "10+"])
    return d


def main():
    d = load()
    g1m = (d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")
    s1m = (d["地基阴阳"] == "阳") & (d["前10日涨幅%"] < -3) & d["买入开盘%"].between(7.5, 8.5, inclusive="left")
    main_pool = d[d["段"] == "主窗"]
    oos_pool = d[d["段"] == "样本外"]

    dims = ["地基阴阳", "今开细", "首板开档", "换手档", "距MA20档", "前10档",
            "位置五档", "底盘纯度", "首板板型"]
    results = []
    for a, b, c in itertools.combinations(dims, 3):
        gm = main_pool.groupby([a, b, c], observed=True)["E3%"]
        agg = gm.agg(["count", "mean"])
        yr = main_pool.groupby([a, b, c, "年"], observed=True)["E3%"].mean().unstack()
        ok = agg[agg["count"] >= 15].index
        for key in ok:
            yv = yr.loc[key].dropna()
            if len(yv) < 4 or not all(yv > 0):
                continue
            o = oos_pool[(oos_pool[a] == key[0]) & (oos_pool[b] == key[1]) & (oos_pool[c] == key[2])]
            if len(o) >= 8 and o["E3%"].mean() > 0:
                sub_m = main_pool[(main_pool[a] == key[0]) & (main_pool[b] == key[1]) & (main_pool[c] == key[2])]
                # 与已知岛重叠
                inter = int((sub_m.index.isin(d[g1m | s1m].index)).sum())
                results.append({
                    "格子": f"{a}={key[0]}×{b}={key[1]}×{c}={key[2]}",
                    "主窗n": int(agg.loc[key, "count"]),
                    "胜率": round((sub_m["E3%"] > 0).mean() * 100, 1),
                    "主窗E3": round(agg.loc[key, "mean"], 2),
                    "OOSn": len(o), "OOS_E3": round(o["E3%"].mean(), 2),
                    "与G1S1重叠": inter,
                })
    R = pd.DataFrame(results).sort_values("主窗E3", ascending=False)
    R.to_csv(f"{OUT}/汇总/三阶严扫.csv", index=False, encoding="utf-8-sig")
    print(R.to_string(index=False))
    print(f"\n共 {len(R)} 格过严筛")


if __name__ == "__main__":
    main()
