# -*- coding: utf-8 -*-
"""四进五 · 好票坏票多维度对比(宿主机: uv run python relay_4to5_goodbad.py)。

三种好坏切法:
  A 机制切法: 走妖(终高≥6) vs 即断(终高=5) —— 彩票池的真正分界
  B 收益切法: 大赚(E3≥+10) vs 大亏(E3≤-10)
  C 方向切法: 赚(E3>0) vs 亏(E3≤0)  (对照)
数值维度: 分位数对比 + AUC(好票该维度比坏票大的概率,0.5=无区分力)。
类别维度: 各类内 好率/走妖率/大亏率。
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 230)

NUM_DIMS = [
    "b1开盘%", "b2开盘%", "b3开盘%", "b4开盘%",
    "b2换手%", "b3换手%", "b4换手%",
    "b4-b3换手", "b3-b2换手",
    "买入开盘%", "买入换手%", "买入量比",
    "地基涨跌%", "地基距MA20%", "距60日新高%", "距MA10%",
    "前波60日最高板", "前波120日最高板", "前板高度", "锚位%", "锚距",
    "首3日涨幅%", "首10日涨幅%", "首20日涨幅%",
    "昨日涨停家数", "昨日最高板", "昨日4板+家数",
]
CAT_DIMS = ["阴阳", "b4板型", "链一字数", "今开档", "b4开盘档", "地基姿态", "均线首符", "封住"]


def auc(good: pd.Series, bad: pd.Series) -> float:
    """AUC = P(随机好票 > 随机坏票)。手搓秩实现,免依赖。"""
    both = pd.concat([good.dropna(), bad.dropna()])
    if len(good.dropna()) == 0 or len(bad.dropna()) == 0:
        return float("nan")
    ranks = both.rank()
    n1, n2 = len(good.dropna()), len(bad.dropna())
    r1 = ranks.iloc[:n1].sum()
    u = r1 - n1 * (n1 + 1) / 2
    return u / (n1 * n2)


def qtable(F: pd.DataFrame, g_mask, b_mask, label_g, label_b) -> pd.DataFrame:
    rows = []
    for d in NUM_DIMS:
        g, b = F.loc[g_mask, d], F.loc[b_mask, d]
        g, b = g.dropna(), b.dropna()
        if len(g) < 5 or len(b) < 5:
            continue
        rows.append({
            "维度": d,
            f"{label_g}中位": round(g.median(), 2), f"{label_b}中位": round(b.median(), 2),
            f"{label_g}P25": round(g.quantile(.25), 2), f"{label_b}P25": round(b.quantile(.25), 2),
            f"{label_g}P75": round(g.quantile(.75), 2), f"{label_b}P75": round(b.quantile(.75), 2),
            "AUC": round(auc(g, b), 3),
        })
    t = pd.DataFrame(rows)
    return t.sort_values("AUC", key=lambda s: (s - 0.5).abs(), ascending=False)


def cat_tables(F: pd.DataFrame, g_mask, b_mask, label_g, label_b) -> None:
    for d in CAT_DIMS:
        print(f"\n—— {d} ——")
        sub = pd.DataFrame({
            "池内占比": F[d].value_counts(normalize=True, dropna=False),
            f"{label_g}率": F.loc[g_mask, d].value_counts(normalize=True, dropna=False),
            f"{label_b}率": F.loc[b_mask, d].value_counts(normalize=True, dropna=False),
        }).fillna(0).round(3) * 100
        print(sub.to_string())


def main() -> None:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    E = E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))]
    F = E[E["N"] == 4].copy()
    F["链一字数"] = F["链"].fillna("").str.count("一字")
    F["b4-b3换手"] = F["b4换手%"] - F["b3换手%"]
    F["b3-b2换手"] = F["b3换手%"] - F["b2换手%"]
    F["今开档"] = pd.cut(F["买入开盘%"], [-99, 0, 3, 6, 9.5], labels=["低<0", "平0~3", "温3~6", "强6~9.5"])
    F["b4开盘档"] = pd.cut(F["b4开盘%"], [-99, 0, 3, 7, 9.5], labels=["低<0", "平0~3", "高3~7", "强7~9.5"])
    F["均线首符"] = F["均线"].astype(str).str[0]

    print(f"四接五研究池 {len(F)} 笔\n")

    masks = {
        "A 走妖(终高≥6) vs 即断(终高=5)": (F["最终高度"] >= 6, F["最终高度"] == 5, "走妖", "即断"),
        "B 大赚(E3≥+10) vs 大亏(E3≤-10)": (F["E3%"] >= 10, F["E3%"] <= -10, "大赚", "大亏"),
    }
    for title, (gm, bm, lg, lb) in masks.items():
        print("=" * 26, title, "=" * 26)
        print(f"{lg} {int(gm.sum())} 笔(池内{gm.mean() * 100:.0f}%) | {lb} {int(bm.sum())} 笔(池内{bm.mean() * 100:.0f}%)")
        print("\n· 数值维度(按|AUC-0.5|排序):")
        print(qtable(F, gm, bm, lg, lb).to_string(index=False))
        print("\n· 类别维度(各类内两率对比,%):")
        cat_tables(F, gm, bm, lg, lb)
        print()

    print("=" * 26, "C 大亏集中度(E3≤-10 vs 池子基准)", "=" * 26)
    big_loss = F["E3%"] <= -10
    print(f"大亏 {int(big_loss.sum())} 笔 / 池 {len(F)} 笔 ({big_loss.mean() * 100:.0f}%)\n")
    rows = []
    for d in NUM_DIMS:
        g, pool = F.loc[big_loss, d].dropna(), F[d].dropna()
        if len(g) < 5:
            continue
        med_split = pool.median()
        hi_pool = (pool >= med_split).mean()
        hi_loss = (g >= med_split).mean()
        lift = hi_loss / hi_pool if hi_pool > 0 else float("nan")
        rows.append({"维度": d, f"中位分界(池)": round(med_split, 2),
                     "大亏在高半区占比": round(hi_loss * 100, 1),
                     "池子高半区占比": round(hi_pool * 100, 1), "集中度lift": round(lift, 2)})
    print(pd.DataFrame(rows).sort_values("集中度lift", ascending=False).to_string(index=False))

    print("\n" + "=" * 26, "D 走妖票的画像(终高≥6,给'原因')", "=" * 26)
    sur = F["最终高度"] >= 6
    for d in ["b4换手%", "b3换手%", "b4开盘%", "买入开盘%", "昨日4板+家数", "距60日新高%", "昨日涨停家数"]:
        print(f"  {d:14s} 走妖中位 {F.loc[sur, d].median():8.2f} | 即断中位 {F.loc[~sur, d].median():8.2f}")
    print("\n  走妖组 链一字数分布:", F.loc[sur, "链一字数"].value_counts().sort_index().to_dict())
    print("  即断组 链一字数分布:", F.loc[~sur, "链一字数"].value_counts().sort_index().to_dict())
    print("  走妖组 b4板型:", F.loc[sur, "b4板型"].value_counts().to_dict())
    print("  即断组 b4板型:", F.loc[~sur, "b4板型"].value_counts().to_dict())
    print("\n  走妖TOP8具体票:")
    for _, r in F.nlargest(8, "E3%").iterrows():
        print(f"    {r['买入日']} {r['代码']} {r['名称']} E3={r['E3%']:+.1f} 终高{r['最终高度']} "
              f"链{r['链']} b4换{r['b4换手%']} 今开{r['买入开盘%']} 家数{r['昨日4板+家数']}")
    print("  大亏TOP8具体票:")
    for _, r in F.nsmallest(8, "E3%").iterrows():
        print(f"    {r['买入日']} {r['代码']} {r['名称']} E3={r['E3%']:+.1f} 终高{r['最终高度']} "
              f"链{r['链']} b4换{r['b4换手%']} 今开{r['买入开盘%']} 家数{r['昨日4板+家数']}")


main()
