# -*- coding: utf-8 -*-
"""二接三/三接四 · P8 市场地位与情绪方向(宿主机: uv run python relay23_position.py)。

新维度(全部 T-1 收盘可知):
  A. 市场地位 = 昨日全市场最高板 - 自己板位N
     差=0 → 我就是最高板(龙头接力); 差≥3 → 小弟接力
     「龙头有溢价/小弟没人抬」是否成立?
  B. 情绪方向 = 昨日涨停家数 vs 前日涨停家数(环比升/降)
  C. 地位 × 口诀命中票(精选票的龙头效应)
  D. 3接4阴两个边缘格复核: 一字×换手10~20 / 实体→下影
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


def era(g: pd.DataFrame) -> str:
    wk = g[g["年"] <= 2022]["E3%"].dropna()
    st = g[g["年"] >= 2023]["E3%"].dropna()
    return (f"弱{len(wk):3d}{wk.mean():+5.1f}/{(wk > 0).mean() * 100:2.0f}% "
            f"强{len(st):3d}{st.mean():+5.1f}/{(st > 0).mean() * 100:2.0f}%")


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E["地位差"] = E["昨日最高板"] - E["N"]

    print("=" * 26, "A. 市场地位(昨日最高板 - 自己N)", "=" * 26)
    E["地位"] = pd.cut(E["地位差"], [-99, 0.5, 1.5, 2.5, 99],
                       labels=["我就是最高(差0)", "差1", "差2", "差3+(小弟)"], right=False)
    for n in (2, 3):
        sub = E[E["N"] == n]
        print(f"\n◆ {n}接{n + 1}")
        for lab in ["我就是最高(差0)", "差1", "差2", "差3+(小弟)"]:
            g = sub[sub["地位"] == lab]
            if not len(g):
                continue
            print(f"  {lab:>14s}: {stat(g)} | {era(g)}")

    print("\n—— 地位 × 阴阳 × 今开档(找龙头效应最强的格) ——")
    E["今开档"] = pd.cut(E["买入开盘%"], [-99, 0, 3, 6, 9.5],
                         labels=["低<0", "平0~3", "温3~6", "强6~9.5"], right=False)
    for n in (2, 3):
        sub = E[E["N"] == n]
        lead = sub[sub["地位差"] <= 0.5]
        fol = sub[sub["地位差"] >= 2.5]
        print(f"\n  {n}接{n + 1} 龙头(差0) {stat(lead)}")
        print(f"  {n}接{n + 1} 小弟(差3+) {stat(fol)}")
        for y in ("阳", "阴"):
            print(f"    {y}: 龙头 {stat(lead[lead['阴阳'] == y])} | 小弟 {stat(fol[fol['阴阳'] == y])}")

    print("\n" + "=" * 26, "B. 情绪方向(涨停家数环比)", "=" * 26)
    # CSV只有昨日涨停家数; 用 买入日涨停家数 是当日的(事后)。环比无法直接算——
    # 用「昨日涨停家数 vs 昨日在全池的滚动中位」近似? 改算: 昨日家数 / 近20日中位
    day_lim = E.groupby("买入日")["昨日涨停家数"].first().sort_index()
    med20 = day_lim.rolling(20, min_periods=10).median()
    ratio_map = (day_lim / med20).to_dict()
    E["情绪环比"] = E["买入日"].map(ratio_map)
    E["情绪方向"] = pd.cut(E["情绪环比"], [0, 0.7, 1.0, 1.4, 99],
                           labels=["急降<0.7", "降0.7~1.0", "升1.0~1.4", "急升≥1.4"], right=False)
    for lab in ["急降<0.7", "降0.7~1.0", "升1.0~1.4", "急升≥1.4"]:
        g = E[E["情绪方向"] == lab]
        if not len(g):
            continue
        print(f"  {lab:>9s}: {stat(g)} | {era(g)}")

    print("\n" + "=" * 26, "C. 地位 × 口诀命中票", "=" * 26)
    H = E[E["口诀"] != "—"]
    for lab in ["我就是最高(差0)", "差1", "差2", "差3+(小弟)"]:
        g = H[H["地位"] == lab]
        if not len(g):
            continue
        print(f"  {lab:>14s}: {stat(g)} | {era(g)}")
    print("\n  分口诀 × 地位(命中票):")
    for no in ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3", "K5", "K9"):
        g = H[H["口诀"] == no]
        if not len(g):
            continue
        lead = g[g["地位差"] <= 0.5]
        fol = g[g["地位差"] >= 2.5]
        print(f"    {no}: 龙头 {stat(lead)} | 小弟 {stat(fol)}")

    print("\n" + "=" * 26, "D. 边缘格复核", "=" * 26)
    E["末板换"] = E.apply(lambda r: r["b2换手%"] if r["N"] == 2 else r["b3换手%"], axis=1)
    g1 = E[(E["N"] == 3) & (E["阴阳"] == "阴") & (E["b3开盘%"] >= 9.5)
           & E["b3换手%"].between(10, 20)]
    print(f"  3接4阴×三板一字×三换10~20: {stat(g1)}")
    if len(g1):
        print("    分年: " + " ".join(f"{y}:{len(gg)}{gg['E3%'].mean():+.1f}"
                                      for y, gg in g1.groupby("年")))
        print(f"    今开分布: {pd.cut(g1['买入开盘%'], [-99, 0, 3, 6, 9.5]).value_counts().sort_index().to_dict()}")
        print(f"    现有命中: {g1['口诀'].value_counts().to_dict()}")
        print("    今开×成绩:")
        for lo, hi in ((-99, 0), (0, 3), (3, 6), (6, 9.5)):
            gg = g1[g1["买入开盘%"].between(lo, hi)]
            if len(gg):
                print(f"      今开{lo}~{hi}: {stat(gg)}")
    g2 = E[(E["N"] == 3) & (E["阴阳"] == "阴") & (E["b2板型"] == "实体") & (E["b3板型"] == "下影")]
    print(f"\n  3接4阴×实体→下影: {stat(g2)}")
    if len(g2):
        print("    分年: " + " ".join(f"{y}:{len(gg)}{gg['E3%'].mean():+.1f}"
                                      for y, gg in g2.groupby("年")))


if __name__ == "__main__":
    main()
