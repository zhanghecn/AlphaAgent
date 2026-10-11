# -*- coding: utf-8 -*-
"""P2+P5 收尾(宿主机: uv run python relay23_tail.py)。

P2 五接六画像: N=5 子集全谱(分年/形态/环境), 找窄格, 不达标则画像留档。
P5 顶格开口探索: 今开≥9.5 顶格票(现全部跳过)的开口率与开口后表现——
   若一字/T字开口常见且不毒, 「顶格排队」是纯增量; 15分钟粒度只给方向。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "—"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):4d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f} 亏:{(e3 <= -10).sum():2d}")


def yearly(g: pd.DataFrame) -> str:
    return " ".join(f"{y}:{len(gg)}{gg['E3%'].mean():+.1f}"
                    for y, gg in g.groupby("年"))


def main() -> None:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    E = E[~E["未完"].astype(bool)].copy()
    E["年"] = E["年"].astype(int)

    print("=" * 24, "P2 五接六画像", "=" * 24)
    F = E[(E["N"] == 5) & (~E["顶格"].astype(bool))]
    print(f"N=5 全池: {stat(F)}")
    print(f"分年: {yearly(F)}")
    print(f"\n最终高度分布(买6板后走到几):")
    print(F.groupby("最终高度").agg(n=("E3%", "size"), E3均=("E3%", "mean")).round(2).to_string())
    print("\n—— 末板换手×今开 ——")
    for lo, hi, lab in ((0, 5, "缩<5"), (5, 15, "5~15"), (15, 99, "15+")):
        for jlo, jhi, jlab in ((-99, 3, "今<3"), (3, 9.5, "今3~9.5")):
            g = F[F["b5换手%"].between(lo, hi) & F["买入开盘%"].between(jlo, jhi)]
            if len(g) >= 5:
                print(f"  五板换{lab}×{jlab}: {stat(g)} | {yearly(g)}")
    print("\n—— 阴阳×龙头(昨日最高板=5=自己是最高) ——")
    for y in ("阳", "阴"):
        for lead, lname in ((True, "龙头"), (False, "小弟")):
            g = F[(F["阴阳"] == y) & ((F["昨日最高板"] <= 5.5) == lead)]
            if len(g) >= 5:
                print(f"  {y}{lname}: {stat(g)}")

    print("\n" + "=" * 24, "P5 顶格开口探索(今开≥9.5)", "=" * 24)
    TG = E[E["顶格"].astype(bool)]
    print(f"顶格票(全部板位): {len(TG)} 笔 | E3均 {TG['E3%'].mean():+.2f} "
          f"(注: 此为'假设顶格价买到'的纸面收益, 实际排队买不到)")
    for n in (2, 3, 4, 5):
        g = TG[TG["N"] == n]
        if len(g):
            print(f"  {n}接{n + 1}顶格: {stat(g)} | 封住率{g['封住'].mean() * 100:.0f}% | {yearly(g)}")
    # 顶格票 vs 非顶格的收益差 = 逆向选择强度
    NT = E[~E["顶格"].astype(bool)]
    print(f"\n对照非顶格: {stat(NT)}")
    print(f"顶格纸面均 {TG['E3%'].mean():+.2f} vs 非顶格 {NT['E3%'].mean():+.2f} "
          f"→ 顶格被跳过每年放弃的纸面收益: {TG.groupby('年')['E3%'].sum().round(1).to_dict()}")

    # 顶格票的一字/T字结构: 封住率+次日开
    print("\n顶格票买入日封住率(全天封死=排队买不到; 炸板=开口能买):")
    for n in (2, 3, 4):
        g = TG[TG["N"] == n]
        if len(g):
            print(f"  {n}接{n + 1}: 封住{g['封住'].mean() * 100:.0f}% "
                  f"(炸板{(~g['封住']).mean() * 100:.0f}%可开口买入, "
                  f"炸板票E3均 {g[~g['封住']]['E3%'].mean():+.2f})")


main()
