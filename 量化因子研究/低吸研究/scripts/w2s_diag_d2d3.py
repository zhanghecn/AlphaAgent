# -*- coding: utf-8 -*-
"""主人猜想验证: 好U形态「D-2收盘 < D-3收盘」(右侧新鲜探低), 前提D-3不是连板末尾板(涨停日).
验证池: 2板补涨阴 层①出手池(蹲类×弹回≤16%×坑宽6-15) + 母池对照; 附2板阳/4+阴同测.
好差口径=D+1盈亏(r_d1c>0好票).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)


def stat(s, lab):
    if not len(s):
        print(f"  {lab}: n=0")
        return
    yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    print(f"  {lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% "
          f"连板 {(s['res'] == '连板').mean() * 100:.0f}% | 分年 {yr}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    for n in (5, 10, 20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    ok = bars[["ma5", "ma10", "ma20", "ma30"]].notna().all(axis=1)
    bars["ma_st"] = ""
    bars.loc[ok, "ma_st"] = (
        np.where(bars.loc[ok, "ma5"] > bars.loc[ok, "ma10"], "+", "-")
        + np.where(bars.loc[ok, "ma10"] > bars.loc[ok, "ma20"], "+", "-")
        + np.where(bars.loc[ok, "ma20"] > bars.loc[ok, "ma30"], "+", "-"))
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    tg1, _ = build_base(bars, segs, conds=("c4a",))
    tg1 = add_outcome(tg1, bars)
    tg2, _ = build_base(bars, segs, conds=("c4b",))
    tg2 = add_outcome(tg2, bars)
    tg3, _ = build_base(bars, segs, conds=("c4c",))
    tg3 = add_outcome(tg3, bars)

    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def d23(r):
        """→ (D-2收<D-3收, D-3是否涨停=末尾板), 数据不足返回 (None, None)."""
        sid, pos = int(r.sid), int(r.pos)
        i = p2i[sid][pos]
        if i < 4:
            return None, None
        c = cl_by[sid]
        return c[i - 2] < c[i - 3], bool(zt_by[sid][i - 3])

    for tg in (tg1, tg2, tg3):
        r23 = [d23(r) for r in tg.itertuples()]
        tg["d2_lt_d3"] = [a for a, _ in r23]
        tg["d3_lim"] = [b for _, b in r23]

    # 主人条件: D-2<D-3 且 D-3非末尾板
    def owner_cond(s):
        return (s["d2_lt_d3"] == True) & (s["d3_lim"] == False)

    squat = ["U", "MID", "FLAT", "V", "LB"]
    l1 = tg1[tg1["base"].isin(squat) & ~(tg1["reb"] > 0.16) & tg1["gap"].between(6, 15)]
    print("=" * 90)
    print(f"① 2板阴 层①出手池(蹲类+弹回≤16%+坑宽6-15): n={len(l1)}")
    stat(l1[owner_cond(l1)], "D-2<D-3 且D-3非末尾板")
    stat(l1[~owner_cond(l1)], "其余")
    stat(l1[(l1["d2_lt_d3"] == True) & (l1["d3_lim"] == True)], "其中: D-3是末尾板(主人说要排除)")
    stat(l1[l1["d2_lt_d3"] == False], "其中: D-2≥D-3(右侧已抬高)")

    pool1 = tg1[tg1["base"].isin(squat) & ~(tg1["reb"] > 0.16)]
    print(f"\n② 2板阴 层①母池(不限坑宽): n={len(pool1)}")
    stat(pool1[owner_cond(pool1)], "D-2<D-3 且D-3非末尾板")
    stat(pool1[~owner_cond(pool1)], "其余")

    l2 = tg2[tg2["base"].isin(squat) & tg2["ma_st"].isin(["-++", "+--"])]
    print(f"\n③ 2板阳 层②'纠缠态池: n={len(l2)}")
    stat(l2[owner_cond(l2)], "D-2<D-3 且D-3非末尾板")
    stat(l2[~owner_cond(l2)], "其余")

    l3 = tg3[(tg3["seg_h"] >= 4) & tg3["n_lim_mid"].between(1, 2)
             & (tg3["ma_st"] == "+++") & (tg3["low_dd"] <= -0.04)]
    print(f"\n④ 4+阴 层③池: n={len(l3)}")
    stat(l3[owner_cond(l3)], "D-2<D-3 且D-3非末尾板")
    stat(l3[~owner_cond(l3)], "其余")

    # 组合试算: 层①加主人条件
    print("\n⑤ 若层①加「D-2<D-3且D-3非末尾板」:")
    stat(l1[owner_cond(l1)], "层①×主人条件")
    print(f"   对比原层① n={len(l1)} 板留均 {l1['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(l1['r_bh'] > 0).mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
