# -*- coding: utf-8 -*-
"""高位接力 · 胜率关键钻透（第二遍）。

第一遍结论: 买入量比/买入换手在四组都是区分度前二(胜率差26~45个百分点)。
本遍回答四个问题:
1. 稳不稳: 量比档×分年、换手档×分年; 量比<1.2按月看是不是个别月份撑的
2. 独不独立: 量比×开盘交叉(开盘是用户点名维度, 看是否被量比吸收)
3. 能不能提前知道: 买入当天量比收盘才定型(有未来函数嫌疑),
   前置板(首板/二板)的换手和开盘在买入前就知道, 测它们的区分度
4. 两关分解: 低量比的甜多少来自封住率、多少来自封后次日
"""
import numpy as np
import pandas as pd

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)

CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
GROUPS = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]
VR_EDGES = [0, 0.8, 1.2, 1.8, 3, 99]
VR_LABELS = ["<0.8", "0.8~1.2", "1.2~1.8", "1.8~3", ">3"]


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["胜"] = E["次日收%"] > 0
    E["量比档"] = pd.cut(E["买入量比"], VR_EDGES, labels=VR_LABELS, right=False)
    E["开盘档"] = pd.cut(E["买入开盘%"], [-99, 0, 2, 4, 6, 8, 9.5, 99],
                       labels=["低开", "0~2", "2~4", "4~6", "6~8", "8~9.5", "近涨停开"], right=False)
    return E


def pct(s):
    return f"{s.mean() * 100:.0f}%" if len(s) else "--"


def main():
    E = load()
    for gname in GROUPS:
        sub = E[E["四组"] == gname]
        print(f"\n{'='*100}\n【{gname}】n={len(sub)}")

        print("\n  ① 量比档 × 分年（次日胜率%, 数字下是n）")
        t = sub.groupby(["量比档", "年"], observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"))
        pv = t.reset_index().pivot(index="量比档", columns="年", values="胜率")
        pn = t.reset_index().pivot(index="量比档", columns="年", values="n")
        show = pv.copy()
        for y in pv.columns:
            show[y] = [f"{v*100:.0f}({n:.0f})" if v == v else "--" for v, n in zip(pv[y], pn[y])]
        print(show.to_string())

        print("\n  ② 量比 × 开盘 交叉（次日胜率%, n）")
        t2 = sub.groupby(["量比档", "开盘档"], observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"))
        pv2 = t2.reset_index().pivot(index="量比档", columns="开盘档", values="胜率")
        pn2 = t2.reset_index().pivot(index="量比档", columns="开盘档", values="n")
        show2 = pv2.copy()
        for c in pv2.columns:
            show2[c] = [f"{v*100:.0f}({n:.0f})" if v == v and n >= 10 else "--"
                        for v, n in zip(pv2[c], pn2[c])]
        print(show2.to_string())

        print("\n  ③ 买入前就知道的信息: 前置板换手/开盘（次日胜率%, n）")
        for col, edges in [("b2换手%", [-1, 3, 6, 10, 15, 25, 99]), ("b2开盘%", [-99, 0, 3, 6, 9.5, 99]),
                           ("b1换手%", [-1, 3, 6, 10, 15, 25, 99])]:
            s = sub.copy()
            s["档"] = pd.cut(s[col], edges, right=False)
            t3 = s.groupby("档", observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                                    封住率=("封住", "mean"),
                                                    持有到断板=("持有到断板%", "mean"))
            t3 = t3[t3["n"] >= 20]
            t3["胜率"] = (t3["胜率"] * 100).round(0)
            t3["封住率"] = (t3["封住率"] * 100).round(0)
            t3["持有到断板"] = t3["持有到断板"].round(2)
            print(f"    [{col}]")
            print(t3.to_string())

        print("\n  ④ 两关分解（按量比档）: 封住率 / 封住后次日胜率 / 炸板后次日收复率")
        sub2 = sub.copy()
        sub2["封后胜"] = np.where(sub2["封住"], sub2["胜"], np.nan)
        sub2["炸后收复"] = np.where(~sub2["封住"], sub2["胜"], np.nan)
        t4 = sub2.groupby("量比档", observed=True).agg(
            n=("胜", "size"), 封住率=("封住", "mean"), 封后胜=("封后胜", "mean"),
            炸后收复=("炸后收复", "mean"))
        for c in ("封住率", "封后胜", "炸后收复"):
            t4[c] = (t4[c] * 100).round(0)
        print(t4.to_string())

    # 按月稳定性: 量比<1.2 vs >=1.2, 全体合并看月份覆盖率
    print(f"\n{'='*100}\n⑤ 按月稳定性: 量比<1.2 vs ≥1.2（全组合并, 每月胜率%）")
    E["低量"] = E["买入量比"] < 1.2
    mo = E.groupby(["月", "低量"]).agg(n=("胜", "size"), 胜率=("胜", "mean")).reset_index()
    pv5 = mo.pivot(index="月", columns="低量", values="胜率")
    pn5 = mo.pivot(index="月", columns="低量", values="n")
    win = 0
    total = 0
    for ym in pv5.index:
        lo, hi = pv5.loc[ym, True], pv5.loc[ym, False]
        nlo = pn5.loc[ym, True]
        if lo == lo and hi == hi and nlo >= 3:
            total += 1
            win += lo > hi
    print(f"可比月份 {total} 个, 低量比胜率更高的月份 {win} 个（占比 {win/max(total,1)*100:.0f}%）")
    bad_months = []
    for ym in pv5.index:
        lo, hi = pv5.loc[ym, True], pv5.loc[ym, False]
        if lo == lo and hi == hi and (pn5.loc[ym, True] or 0) >= 3 and lo < hi:
            bad_months.append(f"{ym}(低{lo*100:.0f}/高{hi*100:.0f})")
    print("低量比反而差的月份:", " ".join(bad_months) if bad_months else "无")


if __name__ == "__main__":
    main()
