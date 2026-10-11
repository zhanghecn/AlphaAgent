# -*- coding: utf-8 -*-
"""四进五 · P2 口诀候选钻取(宿主机: uv run python relay_4to5_drill.py)。

核心假说: 「末板缩量锁仓」是跨板位通用判别器(N=2/3/4 都看 bN 换手<5)。
候选体检: n/月均/分年7年/剔Top3/大亏笔/具体票。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 220)


def load() -> pd.DataFrame:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    return E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))].copy()


def check(E: pd.DataFrame, name: str, mask, show_tickets: bool = False) -> None:
    g = E[mask]
    e3 = g["E3%"].dropna()
    if not len(g):
        print(f"{name}: 0 笔")
        return
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    print(f"\n◆ {name}")
    print(f"  n={len(g)} 月均={len(g) / 82:.2f} E3均={e3.mean():+.2f} 中位={e3.median():+.2f} "
          f"胜率={(e3 > 0).mean() * 100:.1f}% 剔Top3均={trim.mean():+.2f} "
          f"大亏(<-10)={(e3 < -10).sum()}笔 封住率={g['封住'].mean() * 100:.0f}%")
    yr = g.groupby("年")["E3%"].agg(["size", "mean", lambda s: (s > 0).mean() * 100])
    yr.columns = ["n", "E3均", "胜%"]
    print("  分年: " + "  ".join(f"{y}:{int(r['n'])}笔{r['E3均']:+.2f}/{r['胜%']:.0f}%"
                              for y, r in yr.iterrows()))
    if show_tickets:
        top = g.nlargest(5, "E3%")[["买入日", "代码", "名称", "E3%", "最终高度", "b4换手%", "买入开盘%"]]
        bot = g.nsmallest(3, "E3%")[["买入日", "代码", "名称", "E3%", "最终高度", "b4换手%", "买入开盘%"]]
        print("  赚票TOP5:")
        for _, r in top.iterrows():
            print(f"    {r['买入日']} {r['代码']} {r['名称']} E3={r['E3%']:+.1f} 终高{r['最终高度']} "
                  f"b4换{r['b4换手%']} 今开{r['买入开盘%']}")
        print("  亏票TOP3:")
        for _, r in bot.iterrows():
            print(f"    {r['买入日']} {r['代码']} {r['名称']} E3={r['E3%']:+.1f} 终高{r['最终高度']} "
                  f"b4换{r['b4换手%']} 今开{r['买入开盘%']}")


def main() -> None:
    E = load()
    for n in (2, 3, 4):
        E.loc[E["N"] == n, "末板换手%"] = E.loc[E["N"] == n, f"b{n}换手%"]
    F = E[E["N"] == 4].copy()

    print("=" * 28, "A. 跨板位通用假说: 末板缩量锁仓(bN换手<5)", "=" * 28)
    for n in (2, 3, 4):
        g = E[E["N"] == n]
        check(g, f"{n}接{n + 1} × 末板换手<5", g["末板换手%"] < 5)

    print("\n" + "=" * 28, "B. 四接五主池变体", "=" * 28)
    check(F, "B1 四板换手<5(含一字)", F["b4换手%"] < 5)
    check(F, "B2 四板换手<5 且 非一字", (F["b4换手%"] < 5) & (F["b4板型"] != "一字"))
    check(F, "B3 四板一字", F["b4板型"] == "一字")
    check(F, "B4 双缩量: 三板<5 × 四板<5", (F["b3换手%"] < 5) & (F["b4换手%"] < 5))
    check(F, "B5 双缩量 且 今开≥3", (F["b3换手%"] < 5) & (F["b4换手%"] < 5) & (F["买入开盘%"] >= 3))
    check(F, "B6 双缩量 且 非一字四板", (F["b3换手%"] < 5) & (F["b4换手%"] < 5) & (F["b4板型"] != "一字"))

    print("\n" + "=" * 28, "C. C3式直译: 四板一字×换手3~5×今开6~9.5", "=" * 28)
    check(F, "C1 四板一字 × b4换3~5 × 今开6~9.5",
          (F["b4板型"] == "一字") & F["b4换手%"].between(3, 5) & F["买入开盘%"].between(6, 9.5))
    check(F, "C2 四板换手3~5 × 今开6~9.5(不限一字)",
          F["b4换手%"].between(3, 5) & F["买入开盘%"].between(6, 9.5))

    print("\n" + "=" * 28, "D. 市场拥挤度叠加(昨日4板+家数)", "=" * 28)
    check(F, "D1 全池 × 昨日4板+家数≤3", F["昨日4板+家数"] <= 3)
    check(F, "D2 四板换手<5 × 家数≤3", (F["b4换手%"] < 5) & (F["昨日4板+家数"] <= 3))
    check(F, "D3 双缩量 × 家数≤3",
          (F["b3换手%"] < 5) & (F["b4换手%"] < 5) & (F["昨日4板+家数"] <= 3))

    print("\n" + "=" * 28, "E. 股票内生叠加(前波/距新高/阴阳)", "=" * 28)
    check(F, "E1 四板换手<5 × 前波60=0", (F["b4换手%"] < 5) & (F["前波60日最高板"] == 0))
    check(F, "E2 双缩量 × 前波60=0",
          (F["b3换手%"] < 5) & (F["b4换手%"] < 5) & (F["前波60日最高板"] == 0))
    check(F, "E3 四板换手<5 × 阴", (F["b4换手%"] < 5) & (F["阴阳"] == "阴"))
    check(F, "E4 四板换手<5 × 阳", (F["b4换手%"] < 5) & (F["阴阳"] == "阳"))
    check(F, "E5 四板换手<5 × 距新高<-8(不贴顶)", (F["b4换手%"] < 5) & (F["距60日新高%"] < -8))
    check(F, "E6 双缩量 × 距新高<-8",
          (F["b3换手%"] < 5) & (F["b4换手%"] < 5) & (F["距60日新高%"] < -8))

    print("\n" + "=" * 28, "F. 通用二联检验(2/3板同尺对照,防5板特化)", "=" * 28)
    for n in (2, 3):
        g = E[E["N"] == n]
        check(g, f"{n}接{n + 1} × 双缩量(前两板换手<5)",
              (g[f"b{n - 1}换手%"] < 5) & (g[f"b{n}换手%"] < 5))

    print("\n" + "=" * 28, "G. 赚亏票细看(B1全体)", "=" * 28)
    check(F, "B1复看(带票)", F["b4换手%"] < 5, show_tickets=True)


main()
