# -*- coding: utf-8 -*-
"""一接二 · 第二轮B: 第二曲线搜索——排除G1命中后的池子重新找分年全正岛。

要求: 笔数≥15 + 主窗分年全正 + 样本外(2021-2022)合计为正且两年无大负。
产出: 汇总/第二曲线扫描.md
"""
import itertools

import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]].copy()
    d["今开细档"] = pd.cut(d["买入开盘%"], [-99, 0, 2, 4, 6, 7.5, 8.5, 9.5, 99],
                        labels=["低开", "0~2", "2~4", "4~6", "6~7.5", "7.5~8.5", "8.5~9.5", "顶格"])
    d["首板开档"] = pd.cut(d["首板开盘%"], [-99, 0, 3, 7, 9.5, 99],
                        labels=["低开", "0~3", "3~7", "7~9.5", "顶格"])
    d["首板换手细"] = pd.cut(d["首板换手%"], [-.01, 3, 5, 8, 12, 10000],
                         labels=["<3", "3~5", "5~8", "8~12", "12+"])
    d["距MA20档"] = pd.cut(d["地基距MA20%"], [-99, -10, -5, 0, 5, 99],
                       labels=["深下", "-10~-5", "-5~0", "0~5骑线", "5+上方"])
    d["首板量比细"] = pd.cut(d["首板量比"], [-.01, 1, 2, 10000],
                         labels=["<1缩量", "1~2", "2+放量"])
    d["前10日档"] = pd.cut(d["前10日涨幅%"], [-99, -3, 0, 5, 10, 99],
                        labels=["跌", "平", "小涨", "5~10", "10+"])
    return d


def main():
    d = load()
    g1m = (d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")
    pool = d[~g1m]
    main_pool = pool[pool["段"] == "主窗"]
    oos_pool = pool[pool["段"] == "样本外"]

    dims = ["地基阴阳", "位置五档", "底盘纯度", "首板板型", "首板开档", "今开细档",
            "首板换手细", "距MA20档", "首板量比细", "前10日档", "均线", "首板破60高"]
    results = []
    for a in range(len(dims)):
        for b in range(a + 1, len(dims)):
            da, db = dims[a], dims[b]
            for va in main_pool[da].dropna().unique():
                for vb in main_pool[db].dropna().unique():
                    sub = main_pool[(main_pool[da] == va) & (main_pool[db] == vb)]
                    n = len(sub)
                    if n < 15:
                        continue
                    yr = sub.groupby("年")["E3%"].mean()
                    if len(yr) < 4 or not all(yr > 0):
                        continue
                    oos = oos_pool[(oos_pool[da] == va) & (oos_pool[db] == vb)]
                    oos_ok = len(oos) >= 8 and oos["E3%"].mean() > 0
                    results.append({
                        "格子": f"{da}={va} × {db}={vb}", "主窗笔数": n,
                        "胜率": round((sub["E3%"] > 0).mean() * 100, 1),
                        "主窗E3": round(sub["E3%"].mean(), 2),
                        "分年": "/".join(f"{y[2:]}:{v:+.1f}" for y, v in yr.items()),
                        "OOS笔数": len(oos), "OOS_E3": round(oos["E3%"].mean(), 2) if len(oos) else None,
                        "OOS通过": "✅" if oos_ok else ("薄" if len(oos) >= 1 else "无数据"),
                    })
    R = pd.DataFrame(results).sort_values("主窗E3", ascending=False)
    R.to_csv(f"{OUT}/汇总/第二曲线候选.csv", index=False, encoding="utf-8-sig")

    lines = [f"# 一接二 · 第二轮B: 第二曲线扫描(排除G1, 池{len(main_pool)}笔)", "",
             "入线标准: 主窗笔数≥15 + 分年全正 + 样本外为正(✅=OOS≥8笔且为正)", ""]
    lines.append(R.to_markdown(index=False))
    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/第二曲线扫描.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(R.head(30).to_string(index=False))
    print(f"\n共 {len(R)} 个过初筛格, 其中OOS✅ {(R['OOS通过'] == '✅').sum()} 个")


if __name__ == "__main__":
    main()
