# -*- coding: utf-8 -*-
"""「只留U形态」+「4+夹层锚修复」效果验证:
① 出手票中位置=无坑的有几笔(修复后应为0, 否则库会把该买的票藏起来)
② 4+夹层票(seg_h<4)锚修复前后: 位置分布对照 + 收益对照
③ 修复后4+组无坑票收益(确认剩下被剔的真是不洗盘的)
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

    def topped_of(sid, pos):
        i = p2i[int(sid)][int(pos)]
        c, zt = cl_by[int(sid)], zt_by[int(sid)]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return False
        return bool((c[j + 1:i] >= c[j]).any())

    big4_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
               for sid, grp in segs[segs["height"] >= 4].groupby("sid", sort=False)}

    def bigtop_vals(sid, pos):
        """→ (low_dd, pull, gap) 相对大波顶; 无大波段返回None."""
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
        return mid.min() / ph2 - 1, cl_by[int(sid)][i - 1] / ph2 - 1, int(pos) - lp2

    tgs = {}
    for name, c in (("2板补涨阴", "c4a"), ("2板补涨阳", "c4b"),
                    ("4板补涨阴", "c4c"), ("4板补涨阳", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["grp"] = name
        tg["topped"] = [topped_of(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        tgs[name] = tg

    # 出手判定(与五层一致)
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

    print("=" * 96)
    print("① 出手票中 位置=无坑 的笔数(修复后锚; 应为0否则库藏了该买的票):")
    for name, tg in tgs.items():
        out = tg[is_out(name, tg)].copy()
        # 4+组出手票位置按修复后锚(夹层seg_h<4用 bigtop)
        pos3 = []
        for r in out.itertuples():
            if name.startswith("4板") and r.seg_h < 4:
                bv = bigtop_vals(r.sid, r.pos)
                pos3.append(pos_of(bv[0], bv[1]) if bv else pos_of(r.low_dd, r.pull))
            else:
                pos3.append(pos_of(r.low_dd, r.pull))
        out["pos3"] = pos3
        n_nou = int((out["pos3"] == "无坑").sum())
        print(f"  {name}: 出手{len(out)}笔 其中无坑 {n_nou}笔 | "
              + " ".join(f"{p}:{int((out['pos3'] == p).sum())}" for p in ("坑内", "已回顶", "无坑")))

    print("\n② 4+组夹层票(seg_h<4) 锚修复前后对照:")
    for name in ("4板补涨阴", "4板补涨阳"):
        tg = tgs[name]
        sw = tg[tg["seg_h"] < 4].copy()
        if not len(sw):
            continue
        old_pos = [pos_of(dd, pu) for dd, pu in zip(sw["low_dd"], sw["pull"])]
        new_pos, new_dd = [], []
        for r in sw.itertuples():
            bv = bigtop_vals(r.sid, r.pos)
            if bv:
                new_pos.append(pos_of(bv[0], bv[1]))
                new_dd.append(bv[0])
            else:
                new_pos.append(pos_of(r.low_dd, r.pull))
                new_dd.append(r.low_dd)
        sw["old_pos"], sw["new_pos"], sw["new_dd"] = old_pos, new_pos, new_dd
        print(f"\n── {name} 夹层票 n={len(sw)} 板留均 {sw['r_bh'].mean() * 100:+.2f}:")
        for lab, col in (("修复前(小波顶)", "old_pos"), ("修复后(大波顶)", "new_pos")):
            desc = " ".join(f"{p}:{int((sw[col] == p).sum())}" for p in ("无坑", "坑内", "已回顶"))
            print(f"  {lab}: {desc}")
        flip = sw[(sw["old_pos"] == "无坑") & (sw["new_pos"] != "无坑")]
        print(f"  无坑→U 翻正 {len(flip)}笔 板留均 {flip['r_bh'].mean() * 100:+.2f} "
              f"坑深中位(大波顶) {flip['new_dd'].median() * 100:+.1f}%")
        still = sw[sw["new_pos"] == "无坑"]
        print(f"  仍无坑 {len(still)}笔 板留均 {still['r_bh'].mean() * 100:+.2f} "
              f"(大波后也没跌出坑=真没洗盘)")

    print("\n③ 修复后 4+组全体无坑票(该剔的)收益:")
    for name in ("4板补涨阴", "4板补涨阳"):
        tg = tgs[name]
        pos3 = []
        for r in tg.itertuples():
            if r.seg_h < 4:
                bv = bigtop_vals(r.sid, r.pos)
                pos3.append(pos_of(bv[0], bv[1]) if bv else pos_of(r.low_dd, r.pull))
            else:
                pos3.append(pos_of(r.low_dd, r.pull))
        tg["pos3"] = pos3
        s = tg[tg["pos3"] == "无坑"]
        print(f"  {name}: 无坑 {len(s)}笔 板留均 {s['r_bh'].mean() * 100:+.2f} "
              f"好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
