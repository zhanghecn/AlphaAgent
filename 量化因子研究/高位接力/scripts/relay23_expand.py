# -*- coding: utf-8 -*-
"""二接三/三接四 · P4 留档扩窗项全时段终审(宿主机: uv run python relay23_expand.py)。

口诀卡留档攒样本的四项, 用 2020-2026 全时段数据终审(原数字是2023-26段):
  E1. A1强开分支下延: 阳×二板<1×一板<0×二换<12×今开5~6(A1窗6~9.5的下界段)
  E2. B3温开上延: 阴×二板<1×今开6~7×地基姿态过关(B3窗3~6的上界段)
  E3. 阴组三板一字温开: 阴×二板≥1×三板开≥9.5×今开3~6(9-30留档31笔68%+7.76)
  E4. C2阴组金格: 阴×C2条件×前波60=0(留档22笔+17.11胜86%零大亏)
每项: n/分年/剔Top3/大亏/逐票/与现有口诀重叠/边界洞扰动。
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def nn(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def tag_row(row) -> str:
    g4 = row["四组"]
    s = tag_scheme(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                   auction_pct=nn(row["买入开盘%"]), b2_turn=nn(row["b2换手%"]),
                   b3_turn=nn(row["b3换手%"]), foundation_chg=nn(row["地基涨跌%"]),
                   pre10_pct=nn(row["首10日涨幅%"]), foundation_pose=nn(row["地基姿态"]),
                   anchor_pos=nn(row["锚位%"]), anchor_dist=nn(row["锚距"]))
    if s is not None:
        return str(s["no"])
    w = tag_weak(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                 auction_pct=nn(row["买入开盘%"]), b1_turn=nn(row["b1换手%"]),
                 b2_turn=nn(row["b2换手%"]), b3_turn=nn(row["b3换手%"]),
                 foundation_chg=nn(row["地基涨跌%"]), prev_wave60=nn(row["前波60日最高板"]),
                 dist_h60=nn(row["距60日新高%"]))
    return str(w["no"]) if w is not None else "—"


def verify(E, name, mask, show=True):
    g = E[mask].copy()
    e3 = g["E3%"].dropna()
    if not len(g):
        print(f"{name}: 0笔")
        return g
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    print("\n" + "=" * 20, name, "=" * 20)
    print(f"  n={len(g)} E3均={e3.mean():+.2f} 中位={e3.median():+.2f} "
          f"胜={(e3 > 0).mean() * 100:.0f}% 剔Top3={trim.mean():+.2f} "
          f"大亏={(e3 <= -10).sum()}笔 封住率={g['封住'].mean() * 100:.0f}%")
    print("  分年: " + "  ".join(
        f"{y}:{len(gg)}笔{gg['E3%'].mean():+.1f}/{(gg['E3%'] > 0).mean() * 100:.0f}%"
        for y, gg in g.groupby("年")))
    wk = g[g["年"] <= 2022]["E3%"].dropna()
    st = g[g["年"] >= 2023]["E3%"].dropna()
    print(f"  时代: 弱20-22 {len(wk)}笔{wk.mean():+.2f}/{(wk > 0).mean() * 100:.0f}% | "
          f"强23+ {len(st)}笔{st.mean():+.2f}/{(st > 0).mean() * 100:.0f}%")
    print(f"  现有口诀命中: {g['口诀'].value_counts().to_dict()}")
    if show:
        for _, r in g.sort_values("买入日").iterrows():
            mb = f"b{r['N']}"
            print(f"    {r['买入日']} {r['代码']} {r['名称']:<8s} E3={r['E3%']:+6.1f} "
                  f"终高{r['最终高度']} {r['口诀']:>3s} "
                  f"b1开{r['b1开盘%']:+6.2f} {mb}开{r[f'{mb}开盘%']:+6.2f} "
                  f"{mb}换{r[f'{mb}换手%']:6.2f} 今开{r['买入开盘%']:+5.2f} "
                  f"地基{r['地基涨跌%']:+5.1f} 前波{r['前波60日最高板']}")
    return g


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")

    # E1: A1强开分支下延(阳×二板<1×一板<0×二换<12×今开5~6)
    verify(E, "E1 A1下延(阳×二板<1×一板<0×二换<12×今开5~6)",
           (E["N"] == 2) & (E["阴阳"] == "阳") & (E["b2开盘%"] < 1)
           & (E["b1开盘%"] < 0) & (E["b2换手%"] < 12)
           & E["买入开盘%"].between(5, 6))

    # E2: B3温开上延(阴×二板<1×今开6~7×地基站线/骑线)
    verify(E, "E2 B3上延(阴×二板<1×今开6~7×地基姿态)",
           (E["N"] == 3) & (E["阴阳"] == "阴") & (E["b2开盘%"] < 1)
           & E["买入开盘%"].between(6, 7)
           & E["地基姿态"].isin(("站线上", "骑线")))

    # E3: 阴组三板一字温开(阴×二板≥1×三板开≥9.5×今开3~6)
    g3 = verify(E, "E3 阴组三板一字温开(阴×二板≥1×三板一字×今开3~6)",
                (E["N"] == 3) & (E["阴阳"] == "阴") & (E["b2开盘%"] >= 1)
                & (E["b3开盘%"] >= 9.5) & E["买入开盘%"].between(3, 6))
    # E3边界: 今开2~3 / 今开6~7 / 二板<1放开
    print("\n  E3边界扰动:")
    for nm, m in {
        "今开2~6": (E["N"] == 3) & (E["阴阳"] == "阴") & (E["b2开盘%"] >= 1)
            & (E["b3开盘%"] >= 9.5) & E["买入开盘%"].between(2, 6),
        "今开3~7": (E["N"] == 3) & (E["阴阳"] == "阴") & (E["b2开盘%"] >= 1)
            & (E["b3开盘%"] >= 9.5) & E["买入开盘%"].between(3, 7),
        "二板放开(不限≥1)": (E["N"] == 3) & (E["阴阳"] == "阴")
            & (E["b3开盘%"] >= 9.5) & E["买入开盘%"].between(3, 6),
    }.items():
        gg = E[m]
        e3 = gg["E3%"].dropna()
        print(f"    {nm}: {len(gg)}笔 {e3.mean():+.2f}/{(e3 > 0).mean() * 100:.0f}% | 分年: "
              + " ".join(f"{y}:{gg2['E3%'].mean():+.1f}" for y, gg2 in gg.groupby("年")))

    # E4: C2阴组金格(阴×前波60=0×三换10~20×今开5~9.5, 先看C2命中里的, 再看全格)
    c2_cond = ((E["N"] == 3) & E["b3换手%"].between(10, 20)
               & E["买入开盘%"].between(5, 9.5))
    verify(E, "E4a C2金格(阴×三换10~20×今开5~9.5×前波=0)",
           c2_cond & (E["阴阳"] == "阴") & (E["前波60日最高板"] == 0))
    print("\n  E4对照(阳×同条件):")
    gg = E[c2_cond & (E["阴阳"] == "阳") & (E["前波60日最高板"] == 0)]
    e3 = gg["E3%"].dropna()
    print(f"    阳: {len(gg)}笔 {e3.mean():+.2f}/{(e3 > 0).mean() * 100:.0f}% | 分年: "
          + " ".join(f"{y}:{g2['E3%'].mean():+.1f}" for y, g2 in gg.groupby("年")))
    gg = E[c2_cond & (E["阴阳"] == "阴") & (E["前波60日最高板"] > 0)]
    e3 = gg["E3%"].dropna()
    print(f"    阴×前波>0: {len(gg)}笔 {e3.mean():+.2f}/{(e3 > 0).mean() * 100:.0f}% | 分年: "
          + " ".join(f"{y}:{g2['E3%'].mean():+.1f}" for y, g2 in gg.groupby("年")))


main()
