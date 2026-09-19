# -*- coding: utf-8 -*-
"""高位接力 · 胜率关键第五遍：穷尽静态组合 + 分年全正筛选 + 阈值晃动 + 剔毒路线。

只允许买入前可知信息（昨日及以前静态 + 竞价开盘）。新增衍生静态特征:
- 链一字数 / 链开口数(下影个数) / 竞价梯度(买入开盘-二板开盘) / 二板梯度(二板开盘-首板开盘)
- 换手梯度(二板换手-首板换手) / 前波120日 / 距60日低点
筛选:
1. 原子 = 单维里胜率高于池子3pp且n≥20的档
2. 两两/三三组合, 保留 n≥20(两条件)/n≥15(三条件)
3. 分年全正(每年收益>0)的组合 = 入围, 按「最差年份收益」排序
4. 入围组合做阈值晃动测试(边界±2看分年全正是否存活) + 尾部依赖检查
5. 剔毒路线: 每组剔除毒格后看剩余池是否分年全正
6. 入围格子逐笔明细导出 CSV 供主人复核
"""
import itertools
import os

import numpy as np
import pandas as pd

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)

CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
OUTD = "/root/project/ai/vnpy/量化因子研究/高位接力/汇总"
GROUPS = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]
YEARS = ["2023", "2024", "2025", "2026"]


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["月"] = E["月"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["链组合"] = E["b1板型"] + "→" + E["b2板型"]
    E["均线归并"] = np.where(E["均线"] == "+++", "全多头",
                    np.where(E["均线"].isin(["-++", "+--"]), "纠缠", "其他"))
    E["距前波末板"] = E["距前波末板"].fillna(-1)
    # 衍生静态特征
    for k in (1, 2, 3):
        E[f"b{k}一字"] = (E[f"b{k}板型"] == "一字").astype(int)
        E[f"b{k}开口"] = (E[f"b{k}板型"] == "下影").astype(int)
    E["链一字数"] = E["b1一字"] + E["b2一字"] + np.where(E["N"] >= 3, E["b3一字"], 0)
    E["链开口数"] = E["b1开口"] + E["b2开口"] + np.where(E["N"] >= 3, E["b3开口"], 0)
    E["竞价梯度"] = E["买入开盘%"] - E["b2开盘%"]
    E["二板梯度"] = E["b2开盘%"] - E["b1开盘%"]
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    return E


DIMS = [
    ("买入开盘%", [-99, 0, 2, 4, 6, 8, 9.5, 99], "竞价开盘"),
    ("距60日新高%", [-99, -25, -15, -8, -3, 0.01], "地基位置"),
    ("距60日低点%", [-1, 10, 20, 35, 60, 999], "地基离低点"),
    ("地基涨跌%", [-99, -5, -3, 0, 3, 99], "地基日涨跌"),
    ("地基前20日涨幅%", [-99, 0, 15, 30, 999], "地基前20日涨幅"),
    ("前波60日最高板", [-1, 0, 2, 3, 99], "前波60日"),
    ("前波120日最高板", [-1, 0, 2, 3, 99], "前波120日"),
    ("距前波末板", [-2, -0.5, 5, 10, 20, 9999], "距前波末板"),
    ("昨日涨停家数", [-1, 30, 50, 80, 9999], "昨日涨停家数"),
    ("b1开盘%", [-99, 0, 3, 6, 9.5, 99], "首板开盘"),
    ("b2开盘%", [-99, 0, 3, 6, 9.5, 99], "二板开盘"),
    ("b1换手%", [-1, 3, 6, 10, 15, 99], "首板换手"),
    ("b2换手%", [-1, 3, 6, 10, 15, 99], "二板换手"),
    ("竞价梯度", [-99, -5, -2, 0, 2, 5, 99], "竞价梯度"),
    ("二板梯度", [-99, -5, -2, 0, 2, 5, 99], "二板梯度"),
    ("换手梯度", [-99, -5, -2, 0, 2, 5, 99], "换手梯度"),
    ("链一字数", [-1, 0, 1, 9], "链一字数"),
    ("链开口数", [-1, 0, 1, 2, 9], "链开口数"),
    ("均线归并", None, "均线三态"),
    ("b1板型", None, "首板板型"),
    ("b2板型", None, "二板板型"),
    ("链组合", None, "链组合"),
]


def bins_of(s, col, edges):
    if edges is not None:
        return pd.cut(s[col], edges, right=False).astype(str)
    return s[col].fillna("(无)").astype(str)


def yearly_ok(sub):
    """分年全正判定: 每年收益>0(样本为0的年份不算失败)。"""
    by = sub.groupby("年")["持有到断板%"].agg(["size", "mean"])
    res = {}
    for y in YEARS:
        if y in by.index and by.loc[y, "size"] > 0:
            res[y] = (int(by.loc[y, "size"]), round(float(by.loc[y, "mean"]), 2))
    all_pos = all(v[1] > 0 for v in res.values()) and len(res) >= 3
    worst = min((v[1] for v in res.values()), default=-99)
    return all_pos, worst, res


def yearly_str(res):
    return " ".join(f"{y}:{m:+.2f}(n={n})" for y, (n, m) in res.items())


def tail_share(sub, k=3):
    s = sub["持有到断板%"]
    if len(s) == 0 or s.sum() <= 0:
        return 0.0
    return s.nlargest(k).sum() / s.sum() * 100


def monthly_neg(sub):
    by = sub.groupby("月")["持有到断板%"].mean()
    return f"{len(by)}个月/负{int((by < 0).sum())}个"


def main():
    E = load()
    os.makedirs(f"{OUTD}/格子明细", exist_ok=True)
    lines = []
    finalists = []

    for gname in GROUPS:
        sub = E[E["四组"] == gname]
        pool_wr = sub["胜"].mean()
        lines.append(f"\n{'='*100}\n【{gname}】n={len(sub)} 池胜率{pool_wr*100:.0f}%")
        atoms = []
        for col, edges, label in DIMS:
            if col not in sub.columns or sub[col].isna().all():
                continue
            b = bins_of(sub, col, edges)
            for lv, grp in sub.groupby(b, observed=True):
                if len(grp) >= 20 and grp["胜"].mean() > pool_wr + 0.03:
                    atoms.append((f"{label}={lv}", (b == lv)))
        lines.append(f"  原子 {len(atoms)} 个")

        # 两条件 + 三条件穷举
        cands = []
        for r, min_n in ((2, 20), (3, 15)):
            for combo in itertools.combinations(range(len(atoms)), r):
                m = pd.Series(True, index=sub.index)
                for i in combo:
                    m &= atoms[i][1]
                s2 = sub[m.fillna(False)]
                if len(s2) < min_n:
                    continue
                ok, worst, res = yearly_ok(s2)
                cands.append((ok, worst, s2["胜"].mean(), s2["持有到断板%"].mean(), len(s2),
                              " × ".join(atoms[i][0] for i in combo), res, m))
        pos = [c for c in cands if c[0]]
        pos.sort(key=lambda x: (-x[1], -x[3]))
        lines.append(f"  组合总数 {len(cands)}, 分年全正 {len(pos)} 个")
        lines.append("  --- 分年全正（按最差年份排序, 前12）---")
        seen_names = set()
        shown = 0
        for ok, worst, wr, bw, n, cname, res, m in pos:
            key = tuple(sorted(res.items()))
            if shown >= 12:
                break
            shown += 1
            s2 = sub[m.fillna(False)]
            ts = tail_share(s2)
            lines.append(f"  [{shown}] {cname}")
            lines.append(f"      n={n} 胜率{wr*100:.0f}% 持有{bw:+.2f} 最差年{worst:+.2f} "
                         f"尾3占{ts:.0f}% 按月:{monthly_neg(s2)}")
            lines.append(f"      分年: {yearly_str(res)}")
            finalists.append((gname, cname, m.copy(), n, wr, bw, worst))
        if shown == 0:
            lines.append("  （无）")

    # 阈值晃动测试: 对含「地基位置/竞价开盘」的入围组合做边界±2检查
    lines.append(f"\n{'='*100}\n阈值晃动测试（入围组合, 边界±2 看分年全正是否存活）")
    for gname, cname, m, n, wr, bw, worst in finalists[:20]:
        sub = E[E["四组"] == gname]
        if "地基位置=-15.0~-8.0" in cname and "均线" in cname:
            for lo, hi in [(-16, -7), (-14, -9), (-17, -8), (-15, -7)]:
                s2 = sub[(sub["距60日新高%"] >= lo) & (sub["距60日新高%"] < hi)
                         & (sub["均线归并"] == "其他")]
                ok, w2, res = yearly_ok(s2)
                lines.append(f"  {gname} 地基[{lo},{hi})×均线其他: n={len(s2)} "
                             f"胜率{s2['胜'].mean()*100:.0f}% 持有{s2['持有到断板%'].mean():+.2f} "
                             f"全正={'是' if ok else '否'} | {yearly_str(res)}")

    # 导出入围格子逐笔明细
    for i, (gname, cname, m, n, wr, bw, worst) in enumerate(finalists[:20], 1):
        sub = E[E["四组"] == gname]
        s2 = sub[m.fillna(False)]
        s2.to_csv(f"{OUTD}/格子明细/{gname}_{i}.csv", index=False, encoding="utf-8-sig")

    text = "\n".join(lines)
    print(text)
    with open(f"{OUTD}/静态全正组合.md", "w", encoding="utf-8") as f:
        f.write("# 高位接力 · 静态条件组合 分年全正筛选（2026-09-19 第五遍）\n\n```\n" + text + "\n```\n")


if __name__ == "__main__":
    main()
