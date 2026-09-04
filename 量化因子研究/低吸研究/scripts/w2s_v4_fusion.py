# -*- coding: utf-8 -*-
"""主人融合优化(2026-08-29): U深宽 × 均线形态 × D-1贴线位置 → 四组各自的复合筛选器.

方法: 从好差票对比中已求得的各组最强信号组装融合候选, 与现白名单对照.
主指标: 板留分年(打板的钱) + D+1好票率(炸板也认口径). 防过拟合: 候选条件≤3层.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

MAS = (5, 10, 20, 30, 60)


def stat(s, label):
    if not len(s):
        print(f"  {label}: n=0")
        return
    ys = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(s)} 板留{s['r_bh'].mean() * 100:+5.2f} 胜率"
          f"{(s['r_bh'] > 0).mean() * 100:3.0f}% 差票{s['bad'].mean() * 100:3.0f}% "
          f"D+1好票率{(s['r_d1c'] > 0).mean() * 100:3.0f}% | 分年 {ys}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    ma_by = {n: {sid: grp["close_price"].rolling(n, min_periods=n).mean().to_numpy()
                 for sid, grp in bars.groupby("sid", sort=False)} for n in MAS}
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def feats(sid, pos):
        i = p2i[sid][pos] - 1
        if i < 16:
            return None
        c = cl_by[sid][i]
        s = {}
        for a, b in ((5, 10), (10, 20), (20, 30)):
            if ma_by[b][sid][i] != ma_by[b][sid][i]:
                return None
            s[f"{a}_{b}"] = ma_by[a][sid][i] / ma_by[b][sid][i] - 1
        dists = [c / ma_by[n][sid][i] - 1 if ma_by[n][sid][i] == ma_by[n][sid][i] else np.nan
                 for n in MAS]
        if all(d != d for d in dists):
            return None
        j = int(np.nanargmin(np.abs(np.array(dists, dtype=float))))
        return {"st": "".join("+" if s[k] > 0 else "-" for k in ("5_10", "10_20", "20_30")),
                "near": f"MA{MAS[j]}", "s510": s["5_10"], "s1020": s["10_20"]}

    tgs = {}
    for tag, c in (("c4a", "c4a"), ("c4b", "c4b"), ("c4c", "c4c"), ("c4d", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        rows = []
        for r in tg.itertuples():
            f = feats(int(r.sid), int(r.pos))
            if f is not None:
                rows.append({"idx": r.Index, **f})
        tgs[tag] = tg.join(pd.DataFrame(rows).set_index("idx")) if rows else tg

    P = {"c4a": "2板阴", "c4b": "2板阳", "c4c": "4+阴", "c4d": "4+阳"}
    U = {t: tgs[t][tgs[t]["base"].isin(["FLAT", "U", "V", "MID", "LB"])] for t in tgs}

    print("=" * 112)
    print("== 2板阴: 现白名单层① vs 融合候选 ==")
    wl1 = tgs["c4a"][tgs["c4a"]["base"].isin(["U", "MID", "FLAT", "V", "LB"])
                     & ~(tgs["c4a"]["reb"] > 0.16)]
    stat(wl1, "基线·现层①(蹲类+弹回≤16%)        ")
    d = wl1[wl1["st"] == wl1["st"]]
    stat(d[d["gap"].between(6, 15)], "F1a 基线∩坑宽6-15            ")
    stat(d[(d["s510"] < 0) & (d["s1020"] < 0)], "F1b 基线∩空头排列(5,10均在20下) ")
    stat(d[d["near"].isin(["MA30", "MA60"])], "F1c 基线∩贴MA30/60            ")
    stat(d[d["gap"].between(6, 15) & ((d["s510"] < 0) & (d["s1020"] < 0))],
         "F1d 基线∩坑宽6-15∩空头排列     ")

    print("\n== 2板阳: U池(白名单无坑格) vs 融合候选 ==")
    stat(U["c4b"][U["c4b"]["st"] == U["c4b"]["st"]], "基线·U池全体                 ")
    d = U["c4b"][U["c4b"]["st"] == U["c4b"]["st"]]
    stat(d[d["st"].isin(["-++", "+--"])], "F2a U池∩(-++或+--)纠缠态      ")
    stat(d[d["s510"] < 0], "F2b U池∩s510<0(MA5在MA10下)   ")
    stat(d[(d["s510"] < 0) & (d["gap"] <= 10)], "F2c U池∩s510<0∩坑宽≤10       ")
    stat(d[d["near"] == "MA10"], "F2d U池∩贴MA10               ")

    print("\n== 4+阴: U池 vs 融合候选 ==")
    d = U["c4c"][U["c4c"]["st"] == U["c4c"]["st"]]
    stat(d, "基线·U池全体                 ")
    stat(d[d["st"] == "+++"], "F3a U池∩全多头+++            ")
    stat(d[(d["st"] == "+++") & (-d["low_dd"] < 0.15)], "F3b U池∩+++∩浅中坑(<15%)     ")
    stat(d[d["near"] == "MA10"], "F3c U池∩贴MA10               ")
    wl3 = tgs["c4c"][(tgs["c4c"]["seg_h"] >= 4) & tgs["c4c"]["n_lim_mid"].between(1, 2)]
    stat(wl3, "对照·现层③(孤立板穿插,全体池) ")
    stat(wl3[wl3["st"] == "+++"], "F3d 层③∩全多头+++            ")

    print("\n== 4+阳: U池(全组最弱) vs 融合候选 ==")
    d = U["c4d"][U["c4d"]["st"] == U["c4d"]["st"]]
    stat(d, "基线·U池全体                 ")
    stat(d[d["s1020"] < 0.03], "F4a U池∩收敛(s1020<3%)       ")
    stat(d[(d["s1020"] < 0.03) & (d["s510"] > 0)], "F4b U池∩收敛∩s510>0(短期已修复)")
    stat(d[d["near"] == "MA10"], "F4c U池∩贴MA10               ")
    wl4 = tgs["c4d"][tgs["c4d"]["seg_h"] == 2]
    stat(wl4, "对照·现层④(2板小波穿插,全体池)")

    # ══ 新白名单并集总账: F1a + DN首阳 + F2a(新格) + F3d + 层④ ══
    print("\n== 新白名单并集 vs 现并集(771笔+1.59) ==")
    parts = [
        wl1[(wl1["st"] == wl1["st"]) & wl1["gap"].between(6, 15)],           # 层①' F1a
        tgs["c4b"][tgs["c4b"]["base"] == "DN"],                              # 层② DN首阳
        U["c4b"][(U["c4b"]["st"] == U["c4b"]["st"])
                 & U["c4b"]["st"].isin(["-++", "+--"])],                     # 层②' F2a 新格
        wl3[wl3["st"] == "+++"],                                             # 层③' F3d
        wl4,                                                                  # 层④
    ]
    new_u = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["sid", "pos"])
    stat(new_u, "新并集(F1a+DN+F2a+F3d+层④)")
    m = new_u.groupby(new_u["trade_date"].dt.strftime("%Y-%m"))["r_bh"].mean()
    m = m[m.index >= "2023-01"]
    print(f"   23-25月均分复利 {((1 + m[m.index < '2026-01']).prod() - 1) * 100:+.1f}%")


if __name__ == "__main__":
    main()
