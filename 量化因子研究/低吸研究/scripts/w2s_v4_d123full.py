# -*- coding: utf-8 -*-
"""4+阴阳 U底座(U坑存在×MA20>MA30) D-3/D-2/D-1 全形态×全幅度完整扫描.
不做形态预设: 每种阴阳形态 × 每日幅度档全拆; 假阴(收阴蜡烛但收涨)单独成轴.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)

BANDS = [(-9, -0.05, "跌>5%"), (-0.05, -0.02, "跌2~5%"), (-0.02, 0.0, "跌0~2%"),
         (0.0, 0.02, "涨0~2%"), (0.02, 0.05, "涨2~5%"), (0.05, 9, "涨>5%")]


def st(s):
    if not len(s):
        return None
    yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    return (f"n={len(s)} 板留{s['r_bh'].mean() * 100:+.2f} 胜率{(s['r_bh'] > 0).mean() * 100:.0f}% "
            f"好票{(s['r_d1c'] > 0).mean() * 100:.0f}% | {yr}")


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
        return (pat, *[oc[i - k][1] / oc[i - k - 1][1] - 1 for k in (3, 2, 1)])

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
        base["横盘"] = base[["d1", "d2", "d3"]].abs().max(axis=1) <= 0.03
        print("=" * 100)
        print(f"【{name}】U底座 n={len(base)}  底座均 {base['r_bh'].mean() * 100:+.2f}")

        print("\n■ 单日幅度档(不分形态, 整组底座):")
        for col, dlab in (("d3", "D-3"), ("d2", "D-2"), ("d1", "D-1")):
            cells = []
            for lo, hi, blab in BANDS:
                s = base[base[col].between(lo, hi, inclusive="right")]
                if len(s) >= 10:
                    cells.append(f"{blab}: {len(s)}笔 {s['r_bh'].mean() * 100:+.2f}"
                                 f"/好票{(s['r_d1c'] > 0).mean() * 100:.0f}%")
            print(f"  {dlab}: " + " | ".join(cells))

        print("\n■ 全形态 × 横盘:")
        for pat in sorted(base["pat"].unique()):
            s0 = base[base["pat"] == pat]
            h = s0[s0["横盘"]]
            line = f"  {pat}: 全体 {st(s0)}"
            print(line)
            if len(h) >= 5:
                print(f"      横盘子集 {st(h)}")

        print("\n■ 假阴/假阳轴(蜡烛阴但收涨 / 蜡烛阳但收跌), 整组底座:")
        if name == "4板补涨阴":
            for col, dlab in (("d3", "D-3"), ("d2", "D-2"), ("d1", "D-1")):
                s = base[base[col] >= 0]
                print(f"  {dlab}假阴(收涨): {st(s)}")
        else:
            for col, dlab in (("d3", "D-3"), ("d2", "D-2"), ("d1", "D-1")):
                s = base[base[col] < 0]
                print(f"  {dlab}假阳(收跌): {st(s)}")

        print("\n■ 每形态 × D-1幅度档(末端那天最关键):")
        for pat in sorted(base["pat"].unique()):
            s0 = base[base["pat"] == pat]
            cells = []
            for lo, hi, blab in BANDS:
                s = s0[s0["d1"].between(lo, hi, inclusive="right")]
                if len(s) >= 5:
                    cells.append(f"{blab}:{len(s)}笔{s['r_bh'].mean() * 100:+.2f}")
            print(f"  {pat}: " + " | ".join(cells))

        print("\n■ 每形态 × D-3幅度档(开头那天):")
        for pat in sorted(base["pat"].unique()):
            s0 = base[base["pat"] == pat]
            cells = []
            for lo, hi, blab in BANDS:
                s = s0[s0["d3"].between(lo, hi, inclusive="right")]
                if len(s) >= 5:
                    cells.append(f"{blab}:{len(s)}笔{s['r_bh'].mean() * 100:+.2f}")
            print(f"  {pat}: " + " | ".join(cells))


if __name__ == "__main__":
    main()
