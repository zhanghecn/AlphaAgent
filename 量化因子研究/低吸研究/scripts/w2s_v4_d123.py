# -*- coding: utf-8 -*-
"""4+阴阳 × 洗盘坑存在 × MA20>MA30 底座上, D-3/D-2/D-1 阴阳排列与涨幅结构研究(主人猜想).
阴阳=蜡烛收盘vs开盘; 另收集三日各自涨跌幅与累计涨幅. 阴组D-1恒阴→4种形态; 阳组D-1恒阳→4种.
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
    print(f"{ind}{lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% "
          f"连板 {(s['res'] == '连板').mean() * 100:.0f}% | 分年 {yr}")


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
        """→ (形态串 D-3D-2D-1, 三日各自涨幅, 三日累计)"""
        i = p2i[int(sid)][int(pos)]
        oc = oc_by[int(sid)]
        if i < 5:
            return None, None, None
        pat = "".join("+" if oc[i - k][1] > oc[i - k][0] else "-" for k in (3, 2, 1))
        chgs = [oc[i - k][1] / oc[i - k - 1][1] - 1 for k in (3, 2, 1)]
        cum = oc[i - 1][1] / oc[i - 4][1] - 1
        return pat, chgs, cum

    for name, c in (("4板补涨阴", "c4c"), ("4板补涨阳", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        info = [d123(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        tg["pat"] = [a for a, _, _ in info]
        tg["chg_d1"] = [b[2] if b else np.nan for _, b, _ in info]  # D-1涨幅
        tg["chg_d2"] = [b[1] if b else np.nan for _, b, _ in info]  # D-2涨幅
        tg["chg_d3"] = [b[0] if b else np.nan for _, b, _ in info]  # D-3涨幅
        tg["cum3"] = [d for _, _, d in info]
        tg = tg[tg["pat"].notna()]
        uok = tg["low_dd"] <= -0.04
        maok = tg["ma20"] > tg["ma30"]
        base = tg[uok & maok]
        print("=" * 100)
        print(f"【{name}】 洗盘坑存在×MA20>MA30 底座: n={len(base)} "
              f"(全组 {len(tg)} | 无坑或MA空头 {len(tg) - len(base)})")
        stat(base, "底座全体", "")

        print("\n  D-3 D-2 D-1 阴阳排列(D-1已由组条件固定):")
        for pat, s in sorted(base.groupby("pat"), key=lambda kv: -len(kv[1])):
            stat(s, f"{pat}", "    ")

        print("\n  三日累计涨幅(cum3)分档:")
        for lo, hi, lab in ((-9, -0.08, "累计<-8%"), (-0.08, -0.03, "-8~-3%"),
                            (-0.03, 0.0, "-3~0%"), (0.0, 0.03, "0~+3%"), (0.03, 9, ">+3%")):
            s = base[base["cum3"].between(lo, hi, inclusive="right")]
            stat(s, f"{lab} (n={len(s)})", "    ")

        print("\n  单日结构看点:")
        stat(base[base["chg_d1"] <= -0.05], "D-1大跌≥5%", "    ")
        stat(base[base["chg_d1"] >= 0.0], "D-1收涨(假阴/真阳)", "    ")
        stat(base[(base["chg_d3"] <= -0.05) & (base["chg_d1"] >= -0.02)], "D-3大跌≥5%但D-1已收窄(跌速收敛)", "    ")
        stat(base[(base["chg_d2"] <= -0.05)], "D-2大跌≥5%", "    ")


if __name__ == "__main__":
    main()
