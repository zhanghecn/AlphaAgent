# -*- coding: utf-8 -*-
"""四进五 · P4 终审最后两格(宿主机: uv run python relay_4to5_last.py)。

收尾验:
  ① 龙头(昨日最高板=4) × 缩量(b4换<5) / × 一字
  ② 竞价低<0 × b4换<5(9笔+13.09)的扩边: 换<7 / 今开<1 / 换<5×今开<1
  ③ 尾锁×缩<5 × 家数≤3(主人的D2精华版)
全部过主人纪律: n/分年/剔Top3/大亏/逐票。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 220)


def check(E, name, mask, show=False):
    g = E[mask]
    e3 = g["E3%"].dropna()
    if not len(g):
        print(f"{name}: 0笔")
        return
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    print(f"\n◆ {name}")
    print(f"  n={len(g)} E3均={e3.mean():+.2f} 中位={e3.median():+.2f} "
          f"胜={(e3 > 0).mean() * 100:.0f}% 剔Top3={trim.mean():+.2f} 大亏={(e3 <= -10).sum()}笔")
    print("  分年: " + "  ".join(f"{y}:{len(gg)}笔{gg['E3%'].mean():+.1f}/{(gg['E3%'] > 0).mean() * 100:.0f}%"
                                for y, gg in g.groupby("年")))
    if show:
        for _, r in g.sort_values("买入日").iterrows():
            print(f"    {r['买入日']} {r['代码']} {r['名称']:<8s} E3={r['E3%']:+6.1f} 终高{r['最终高度']} "
                  f"b4换{r['b4换手%']:5.2f} 今开{r['买入开盘%']:+5.2f} 家数{r['昨日4板+家数']} "
                  f"最高板{r['昨日最高板']} 链{r['链']}")


def main() -> None:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    E = E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))].copy()
    E["年"] = E["年"].astype(int)
    F = E[E["N"] == 4].copy()

    lead = F["昨日最高板"] <= 4.5
    slim = F["b4换手%"] < 5
    check(F, "龙头×缩<5", lead & slim, show=True)
    check(F, "龙头×四板一字", lead & (F["b4开盘%"] >= 9.5))
    check(F, "龙头×缩<5×家数≤3", lead & slim & (F["昨日4板+家数"] <= 3))
    check(F, "竞价低<0×换<5", (F["买入开盘%"] < 0) & slim, show=True)
    check(F, "竞价低<0×换<7", (F["买入开盘%"] < 0) & (F["b4换手%"] < 7))
    check(F, "竞价<1×换<5", (F["买入开盘%"] < 1) & slim)
    check(F, "竞价低<0×换<5×非一字链", (F["买入开盘%"] < 0) & slim
          & (F["b4开盘%"] < 9.5))


main()
