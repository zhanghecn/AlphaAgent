# -*- coding: utf-8 -*-
"""「断板期曾收顶上方=伪U」规则跨层验证: 层①剔法两案 + 层②/②'/层③池同测."""
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
          f"| 分年 {yr}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    for n in (5, 10, 20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    ok = bars[["ma5", "ma10", "ma20", "ma30"]].notna().all(axis=1)
    bars["ma_st"] = ""
    bars.loc[ok, "ma_st"] = (
        np.where(bars.loc[ok, "ma5"] > bars.loc[ok, "ma10"], "+", "-")
        + np.where(bars.loc[ok, "ma10"] > bars.loc[ok, "ma20"], "+", "-")
        + np.where(bars.loc[ok, "ma20"] > bars.loc[ok, "ma30"], "+", "-"))
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    tgs = {}
    for tag, c in (("1", "c4a"), ("2", "c4b"), ("3", "c4c")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tgs[tag] = add_outcome(tg, bars)

    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def topped(r):
        sid, pos = int(r.sid), int(r.pos)
        i = p2i[sid][pos]
        c, zt = cl_by[sid], zt_by[sid]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return False
        return bool((c[j + 1:i] >= c[j]).any())

    squat = ["U", "MID", "FLAT", "V", "LB"]
    l1 = tgs["1"][tgs["1"]["base"].isin(squat) & ~(tgs["1"]["reb"] > 0.16)
                  & tgs["1"]["gap"].between(6, 15)].copy()
    l1["topped"] = [topped(r) for r in l1.itertuples()]
    print("① 层①(2板阴蹲类×弹回≤16%×坑宽6-15) 剔法两案:")
    stat(l1, "原层①")
    stat(l1[~l1["topped"]], "案A: 剔全部曾收顶上")
    stat(l1[~(l1["topped"] & (l1["low_dd"] > -0.10))], "案B: 只剔浅坑×曾收顶上")

    for tag, lab, m in (
            ("2", "层② 2板阳首阳", tgs["2"]["base"] == "DN"),
            ("2", "层②' 2板阳纠缠", tgs["2"]["base"].isin(squat)
             & tgs["2"]["ma_st"].isin(["-++", "+--"])),
            ("3", "层③ 4+阴孤板多头蹲过", (tgs["3"]["seg_h"] >= 4)
             & tgs["3"]["n_lim_mid"].between(1, 2) & (tgs["3"]["ma_st"] == "+++")
             & (tgs["3"]["low_dd"] <= -0.04))):
        s = tgs[tag][m].copy()
        s["topped"] = [topped(r) for r in s.itertuples()]
        print(f"\n{lab}: n={len(s)}")
        stat(s[~s["topped"]], "  从未收顶上")
        stat(s[s["topped"]], "  曾收顶上")


if __name__ == "__main__":
    main()
