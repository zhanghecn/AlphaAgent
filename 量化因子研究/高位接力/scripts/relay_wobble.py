# -*- coding: utf-8 -*-
"""高位接力 · 第六遍：入围格子的阈值晃动测试。

每个入围组合把边界±2挪一挪, 看分年全正是否存活——只在刀口上成立的不要。
"""
import numpy as np
import pandas as pd

pd.set_option("display.width", 340)
CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
YEARS = ["2023", "2024", "2025", "2026"]


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["均线归并"] = np.where(E["均线"] == "+++", "全多头",
                    np.where(E["均线"].isin(["-++", "+--"]), "纠缠", "其他"))
    E["距前波末板"] = E["距前波末板"].fillna(-1)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    E["二板梯度"] = E["b2开盘%"] - E["b1开盘%"]
    return E


def yearly_str(sub):
    by = sub.groupby("年")["持有到断板%"].agg(["size", "mean"])
    parts, all_pos = [], True
    for y in YEARS:
        if y in by.index and by.loc[y, "size"] > 0:
            m = float(by.loc[y, "mean"])
            parts.append(f"{y}:{m:+.2f}(n={int(by.loc[y,'size'])})")
            if m <= 0:
                all_pos = False
    if len(parts) < 3:
        all_pos = False
    return ("全正✅" if all_pos else "有负年❌") + " | " + " ".join(parts)


def show(tag, sub):
    if len(sub) == 0:
        print(f"  {tag}: 空")
        return
    print(f"  {tag}: n={len(sub)} 胜率{sub['胜'].mean()*100:.0f}% "
          f"持有{sub['持有到断板%'].mean():+.2f} | {yearly_str(sub)}")


def main():
    E = load()
    print("① 三接四阳 金格: 地基位置边界晃动（×均线其他 固定）")
    base = E[(E["四组"] == "三接四阳") & (E["均线归并"] == "其他")]
    for lo, hi in [(-15, -8), (-16, -7), (-14, -9), (-17, -8), (-15, -7), (-13, -8)]:
        show(f"地基[{lo},{hi})", base[(base["距60日新高%"] >= lo) & (base["距60日新高%"] < hi)])

    print("\n② 三接四阴: 前波×换手梯度（二板换手比首板低=缩量二板, 静态版缩量）")
    sub = E[E["四组"] == "三接四阴"]
    for pw_col, th in [("前波120日最高板", 3), ("前波60日最高板", 3)]:
        for gt in (-4, -5, -6):
            show(f"{pw_col[:5]}≥{th} × 换手梯度<{gt}",
                 sub[(sub[pw_col] >= th) & (sub["换手梯度"] < gt)])
    print("  对照: 换手梯度>=-5 的前波票（缩量条件拿掉）")
    show("前波120≥3 × 换手梯度≥-5", sub[(sub["前波120日最高板"] >= 3) & (sub["换手梯度"] >= -5)])

    print("\n③ 三接四阴: 环境×二板梯度 边界晃动")
    for lo, hi in [(50, 80), (45, 85), (55, 75), (40, 90)]:
        for glo, ghi in [(0, 2), (-1, 3)]:
            show(f"昨日涨停[{lo},{hi}) × 二板梯度[{glo},{ghi})",
                 sub[(sub["昨日涨停家数"] >= lo) & (sub["昨日涨停家数"] < hi)
                     & (sub["二板梯度"] >= glo) & (sub["二板梯度"] < ghi)])

    print("\n④ 二接三阴: 二板开盘×换手梯度 边界晃动")
    sub = E[E["四组"] == "二接三阴"]
    for lo, hi in [(6, 9.5), (5, 9), (7, 10), (5.5, 9.5)]:
        for glo, ghi in [(0, 2), (-1, 3)]:
            show(f"二板开盘[{lo},{hi}) × 换手梯度[{glo},{ghi})",
                 sub[(sub["b2开盘%"] >= lo) & (sub["b2开盘%"] < hi)
                     & (sub["换手梯度"] >= glo) & (sub["换手梯度"] < ghi)])

    print("\n⑤ 二接三阳: 地基位置×二板低开 边界晃动")
    sub = E[E["四组"] == "二接三阳"]
    for lo, hi in [(-8, -3), (-9, -2), (-7, -4), (-10, -3)]:
        for b2hi in (0, 1):
            show(f"地基[{lo},{hi}) × 二板开盘<{b2hi}",
                 sub[(sub["距60日新高%"] >= lo) & (sub["距60日新高%"] < hi) & (sub["b2开盘%"] < b2hi)])

    print("\n⑥ 三接四阳金格加第三条件（无前波）晃动")
    base2 = E[(E["四组"] == "三接四阳") & (E["均线归并"] == "其他")
              & (E["距60日新高%"] >= -15) & (E["距60日新高%"] < -8)]
    show("金格×无前波", base2[base2["前波60日最高板"] == 0])
    show("金格×有前波", base2[base2["前波60日最高板"] > 0])
    show("金格×竞价0~6", base2[(base2["买入开盘%"] >= 0) & (base2["买入开盘%"] < 6)])
    show("金格×竞价6~9.5", base2[(base2["买入开盘%"] >= 6) & (base2["买入开盘%"] < 9.5)])
    show("金格×竞价≥9.5", base2[base2["买入开盘%"] >= 9.5])
    show("金格×低开", base2[base2["买入开盘%"] < 0])


if __name__ == "__main__":
    main()
