# -*- coding: utf-8 -*-
"""修复前后对照表(主人要): 年×四组, 修复前=全量触发(无坑混入+夹层小波顶锚),
修复后=U形态池(无坑剔出+出手票保留+夹层大波顶锚). 指标: n/D+1收均/板留均/好票率/出手n/出手板留.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)


def pos_of(low_dd, pull):
    if low_dd == low_dd and low_dd > -0.04:
        return "无坑"
    if pull == pull and pull > -0.04:
        return "已回顶"
    return "坑内"


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
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}
    big4_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
               for sid, grp in segs[segs["height"] >= 4].groupby("sid", sort=False)}

    def topped_of(sid, pos):
        i = p2i[int(sid)][int(pos)]
        c, zt = cl_by[int(sid)], zt_by[int(sid)]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return False
        return bool((c[j + 1:i] >= c[j]).any())

    def bigtop_vals(sid, pos):
        arr = big4_by.get(int(sid))
        if arr is None:
            return None
        li = arr[:, 0].searchsorted(int(pos), side="left")
        if li == 0:
            return None
        lp2, ph2 = int(arr[li - 1, 0]), float(arr[li - 1, 1])
        i = p2i[int(sid)][int(pos)]
        mid = cl_by[int(sid)][lp2 + 1:i]
        if not len(mid):
            return None
        return mid.min() / ph2 - 1, cl_by[int(sid)][i - 1] / ph2 - 1

    squat = ["U", "MID", "FLAT", "V", "LB"]

    def is_out(name, tg):
        if name == "2板补涨阴":
            return (tg["base"].isin(squat) & ~tg["topped"]
                    & ~(tg["reb"] > 0.16) & tg["gap"].between(6, 15))
        if name == "2板补涨阳":
            return ((tg["base"] == "DN") & ~tg["topped"]) | \
                   (tg["base"].isin(squat) & tg["ma_st"].isin(["-++", "+--"]))
        if name == "4板补涨阴":
            return ((tg["seg_h"] >= 4) & tg["n_lim_mid"].between(1, 2)
                    & (tg["ma_st"] == "+++") & (tg["low_dd"] <= -0.04))
        return tg["seg_h"] == 2

    def stat_line(s, out):
        o = s[out.reindex(s.index).fillna(False)] if len(s) else s
        return (f"n={len(s):>4} D+1收 {s['r_d1c'].mean() * 100:+.2f} "
                f"板留 {s['r_bh'].mean() * 100:+.2f} 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}%"
                f" | ✅出手{len(o)}笔" + (f" 板留 {o['r_bh'].mean() * 100:+.2f}" if len(o) else ""))

    for name, c in (("2板补涨阴", "c4a"), ("2板补涨阳", "c4b"),
                    ("4板补涨阴", "c4c"), ("4板补涨阳", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["topped"] = [topped_of(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        tg["yy"] = tg["trade_date"].dt.year
        out = is_out(name, tg)
        # 修复前位置(小波顶锚) / 修复后位置(4+夹层改大波顶)
        tg["pos_old"] = [pos_of(dd, pu) for dd, pu in zip(tg["low_dd"], tg["pull"])]
        if name.startswith("4板"):
            newp = []
            for r in tg.itertuples():
                if r.seg_h < 4:
                    bv = bigtop_vals(r.sid, r.pos)
                    newp.append(pos_of(bv[0], bv[1]) if bv else pos_of(r.low_dd, r.pull))
                else:
                    newp.append(pos_of(r.low_dd, r.pull))
            tg["pos_new"] = newp
        else:
            tg["pos_new"] = tg["pos_old"]
        old_pool = tg                                  # 修复前=全量触发
        new_pool = tg[(tg["pos_new"] != "无坑") | out]  # 修复后=U形态+出手票
        print("=" * 100)
        print(f"【{name}】 修复前 n={len(old_pool)} → 修复后 n={len(new_pool)} "
              f"(剔出非出手无坑 {len(old_pool) - len(new_pool)}笔)")
        print(f"  全期 前: {stat_line(old_pool, out)}")
        print(f"  全期 后: {stat_line(new_pool, out)}")
        for yy in (2023, 2024, 2025, 2026):
            so, sn = old_pool[old_pool["yy"] == yy], new_pool[new_pool["yy"] == yy]
            if not len(so):
                continue
            print(f"  {yy} 前: {stat_line(so, out)}")
            print(f"       后: {stat_line(sn, out)}")


if __name__ == "__main__":
    main()
