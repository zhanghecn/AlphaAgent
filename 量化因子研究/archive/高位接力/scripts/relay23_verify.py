# -*- coding: utf-8 -*-
"""二接三/三接四 · P5 候选格严格验证(宿主机: uv run python relay23_verify.py)。

对 P4 搜出的 4 个头号候选格 + C2 锚位毒段做纪律验证:
  ① 七年分年一致性  ② 剔Top3  ③ 大亏清单  ④ 逐票点名(全量)
  ⑤ 边界洞扰动(窗±1)  ⑥ 与现有口诀的重叠(互补性)
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)

CANDS = {
    "W1 二接三阴·贴零平开·一板低开": lambda E: (
        (E["N"] == 2) & (E["阴阳"] == "阴") & E["b2开盘%"].between(0, 1)
        & E["买入开盘%"].between(0, 3) & (E["b1开盘%"] < 0)),
    "W2 二接三阴·一字平开·一板强开": lambda E: (
        (E["N"] == 2) & (E["阴阳"] == "阴") & (E["b2开盘%"] >= 9.5)
        & E["买入开盘%"].between(0, 3) & (E["b1开盘%"] >= 7)),
    "W3 二接三阳·贴零低开·前波=0": lambda E: (
        (E["N"] == 2) & (E["阴阳"] == "阳") & E["b2开盘%"].between(0, 1)
        & (E["买入开盘%"] < 0) & (E["前波60日最高板"] == 0)),
    "W4 三接四阴·高开温推·地基平": lambda E: (
        (E["N"] == 3) & (E["阴阳"] == "阴") & E["b3开盘%"].between(3, 7)
        & E["买入开盘%"].between(3, 6) & E["地基涨跌%"].between(-2, 1)),
}


def verify(E: pd.DataFrame, name: str, g: pd.DataFrame, tickets: bool = True) -> None:
    e3 = g["E3%"].dropna()
    if not len(g):
        print(f"{name}: 0笔")
        return
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    print("\n" + "=" * 22, name, "=" * 22)
    print(f"  n={len(g)} E3均={e3.mean():+.2f} 中位={e3.median():+.2f} "
          f"胜={(e3 > 0).mean() * 100:.0f}% 剔Top3={trim.mean():+.2f} "
          f"大亏≤-10: {(e3 <= -10).sum()}笔 封住率={g['封住'].mean() * 100:.0f}%")
    print("  分年: " + "  ".join(
        f"{y}:{len(gg)}笔{gg['E3%'].mean():+.1f}/{(gg['E3%'] > 0).mean() * 100:.0f}%"
        for y, gg in g.groupby("年")))
    print(f"  现有口诀命中: {g['口诀'].value_counts().to_dict()}")
    if tickets:
        for _, r in g.sort_values("买入日").iterrows():
            mb = f"b{r['N']}"
            print(f"    {r['买入日']} {r['代码']} {r['名称']:<8s} E3={r['E3%']:+6.1f} "
                  f"终高{r['最终高度']} 封{int(r['封住'])} "
                  f"b1开{r['b1开盘%']:+6.2f} {mb}开{r[f'{mb}开盘%']:+6.2f} "
                  f"{mb}换{r[f'{mb}换手%']:6.2f} 今开{r['买入开盘%']:+5.2f} "
                  f"地基{r['地基涨跌%']:+5.1f} 前波{r['前波60日最高板']} "
                  f"距新高{r['距60日新高%']:6.1f} 涨停家{r['昨日涨停家数']}")


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")

    for name, f in CANDS.items():
        verify(E, name, E[f(E)])

    # ── 边界洞扰动: W1/W2/W3/W4 窗±1 ──
    print("\n\n" + "=" * 22, "边界洞扰动", "=" * 22)
    probes = {
        "W1 今开扩到0~4": (E["N"] == 2) & (E["阴阳"] == "阴") & E["b2开盘%"].between(0, 1) \
            & E["买入开盘%"].between(0, 4) & (E["b1开盘%"] < 0),
        "W1 今开0~3但贴零放宽<1.5": (E["N"] == 2) & (E["阴阳"] == "阴") & (E["b2开盘%"] < 1.5) \
            & (E["b2开盘%"] >= 0) & E["买入开盘%"].between(0, 3) & (E["b1开盘%"] < 0),
        "W2 今开扩到0~4": (E["N"] == 2) & (E["阴阳"] == "阴") & (E["b2开盘%"] >= 9.5) \
            & E["买入开盘%"].between(0, 4) & (E["b1开盘%"] >= 7),
        "W2 一板放宽≥6": (E["N"] == 2) & (E["阴阳"] == "阴") & (E["b2开盘%"] >= 9.5) \
            & E["买入开盘%"].between(0, 3) & (E["b1开盘%"] >= 6),
        "W3 贴零放宽<2": (E["N"] == 2) & (E["阴阳"] == "阳") & E["b2开盘%"].between(0, 2) \
            & (E["买入开盘%"] < 0) & (E["前波60日最高板"] == 0),
        "W3 今开扩到<1": (E["N"] == 2) & (E["阴阳"] == "阳") & E["b2开盘%"].between(0, 1) \
            & (E["买入开盘%"] < 1) & (E["前波60日最高板"] == 0),
        "W4 今开扩到3~7": (E["N"] == 3) & (E["阴阳"] == "阴") & E["b3开盘%"].between(3, 7) \
            & E["买入开盘%"].between(3, 7) & E["地基涨跌%"].between(-2, 1),
        "W4 地基放宽-3~2": (E["N"] == 3) & (E["阴阳"] == "阴") & E["b3开盘%"].between(3, 7) \
            & E["买入开盘%"].between(3, 6) & E["地基涨跌%"].between(-3, 2),
    }
    for name, m in probes.items():
        g = E[m]
        e3 = g["E3%"].dropna()
        if not len(g):
            print(f"{name}: 0笔")
            continue
        trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
        print(f"  {name}: n={len(g)} E3均={e3.mean():+.2f} 胜={(e3 > 0).mean() * 100:.0f}% "
              f"剔Top3={trim.mean():+.2f} 大亏{(e3 <= -10).sum()}笔 | 分年: "
              + " ".join(f"{y}:{gg['E3%'].mean():+.1f}" for y, gg in g.groupby("年")))

    # ── C2 锚位毒段检验 ──
    print("\n\n" + "=" * 22, "C2 锚位分档(96笔命中)", "=" * 22)
    C2 = E[E["口诀"] == "C2"].copy()
    C2["锚档"] = pd.cut(C2["锚位%"].astype(float), [-99, -8, -2, 0, 5, 99],
                        labels=["深跌<-8", "回落-8~-2", "贴锚-2~0", "超0~5", "超≥5"], right=False)
    for lab in ["深跌<-8", "回落-8~-2", "贴锚-2~0", "超0~5", "超≥5"]:
        g = C2[C2["锚档"] == lab]
        nan_g = C2[C2["锚位%"].isna()] if lab == "深跌<-8" else None
        if not len(g):
            continue
        e3 = g["E3%"].dropna()
        print(f"  锚{lab}: {len(g)}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
              f"大亏{(e3 <= -10).sum()}笔 | 分年: "
              + " ".join(f"{y}:{gg['E3%'].mean():+.1f}" for y, gg in g.groupby("年")))
    g = C2[C2["锚位%"].isna()]
    e3 = g["E3%"].dropna()
    print(f"  锚nan(前20日无涨停): {len(g)}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
          f"大亏{(e3 <= -10).sum()}笔 | 分年: "
          + " ".join(f"{y}:{gg['E3%'].mean():+.1f}" for y, gg in g.groupby("年")))

    # C2 今开细分
    print("\n  C2 今开细分:")
    C2["今开细"] = pd.cut(C2["买入开盘%"].astype(float), [4.99, 6, 6.5, 7, 8.5, 9.5],
                          labels=["5~6", "6~6.5", "6.5~7", "7~8.5", "8.5~9.5"], right=False)
    for lab in ["5~6", "6~6.5", "6.5~7", "7~8.5", "8.5~9.5"]:
        g = C2[C2["今开细"] == lab]
        if not len(g):
            continue
        e3 = g["E3%"].dropna()
        print(f"  今开{lab}: {len(g)}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
              f"大亏{(e3 <= -10).sum()}笔 | 分年: "
              + " ".join(f"{y}:{gg['E3%'].mean():+.1f}" for y, gg in g.groupby("年")))


if __name__ == "__main__":
    main()
