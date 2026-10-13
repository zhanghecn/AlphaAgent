# -*- coding: utf-8 -*-
"""4+阴 U底座上 D-3/D-2/D-1 涨幅幅度研究(主人: 横盘控制×-+规律, 不脱离U形态).
底座=洗盘坑存在(low_dd<=-4%)×MA20>MA30. 横盘=三日每日|涨幅|≤3%.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)


def stat(s, lab, ind="  "):
    if not len(s):
        print(f"{ind}{lab}: n=0")
        return
    yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    nm = s["trade_date"].dt.strftime("%Y-%m").nunique()
    print(f"{ind}{lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% "
          f"连板 {(s['res'] == '连板').mean() * 100:.0f}% | 分年 {yr} | 月均{len(s) / nm:.1f}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    for n in (20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    oc_by = {sid: grp[["open_price", "close_price"]].to_numpy()
             for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def d123(sid, pos):
        i = p2i[int(sid)][int(pos)]
        oc = oc_by[int(sid)]
        if i < 5:
            return None
        pat = "".join("+" if oc[i - k][1] > oc[i - k][0] else "-" for k in (3, 2, 1))
        chgs = [oc[i - k][1] / oc[i - k - 1][1] - 1 for k in (3, 2, 1)]  # (D-3, D-2, D-1)
        return pat, *chgs

    for name, c in (("4板补涨阴", "c4c"), ("4板补涨阳", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        info = [d123(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        tg = tg[[x is not None for x in info]].copy()
        info = [x for x in info if x is not None]
        tg["pat"] = [x[0] for x in info]
        tg["d3"], tg["d2"], tg["d1"] = ([x[1] for x in info], [x[2] for x in info],
                                        [x[3] for x in info])
        base = tg[(tg["low_dd"] <= -0.04) & (tg["ma20"] > tg["ma30"])].copy()
        base["横盘"] = (base[["d1", "d2", "d3"]].abs().max(axis=1) <= 0.03)
        print("=" * 100)
        print(f"【{name}】 洗盘坑存在×MA20>MA30: n={len(base)}")
        stat(base, "底座全体", "")
        stat(base[base["横盘"]], "横盘(三日|幅|≤3%)", "")
        stat(base[~base["横盘"]], "非横盘", "")

        print("\n  横盘 × 阴阳形态:")
        hp = base[base["横盘"]]
        for pat, s in sorted(hp.groupby("pat"), key=lambda kv: -len(kv[1])):
            stat(s, f"横盘×{pat}", "    ")

        if name == "4板补涨阴":
            print("\n  -+- 内部幅度拆解(横盘/非横盘 × D-2阳线涨幅 × D-1阴线跌幅):")
            p = base[base["pat"] == "-+-"]
            stat(p, "-+- 全体")
            stat(p[p["横盘"]], "-+-×横盘(三日小幅)")
            stat(p[~p["横盘"]], "-+-×非横盘")
            print("    D-2阳线幅度:")
            for lo, hi, lab in ((-9, 0.01, "<1%(假弹)"), (0.01, 0.03, "1~3%(小弹)"),
                                (0.03, 0.06, "3~6%(中弹)"), (0.06, 9, ">6%(大弹)")):
                s = p[p["d2"].between(lo, hi, inclusive="right")]
                stat(s, f"D-2弹{lab}", "      ")
            print("    D-1阴线幅度:")
            for lo, hi, lab in ((-9, -0.05, "跌>5%(重砸)"), (-0.05, -0.02, "跌2~5%"),
                                (-0.02, 0.0, "跌0~2%(轻压)"), (0.0, 9, "收涨(假阴)")):
                s = p[p["d1"].between(lo, hi, inclusive="right")]
                stat(s, f"D-1{lab}", "      ")
            print("    D-3阴线幅度:")
            for lo, hi, lab in ((-9, -0.05, "跌>5%"), (-0.05, -0.02, "跌2~5%"),
                                (-0.02, 0.0, "跌0~2%"), (0.0, 9, "收涨(假阴)")):
                s = p[p["d3"].between(lo, hi, inclusive="right")]
                stat(s, f"D-3{lab}", "      ")


if __name__ == "__main__":
    main()
