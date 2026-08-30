# -*- coding: utf-8 -*-
"""2板组 mx窗口扫描(主人: 前20日连板=2 是否改15, 多少合适): W∈{10,12,15,18,20,25,30}.
mxW==2 = 昨日前W个交易日内最大连板数恰好2. build_base特征与窗口无关(锚=最近≥2板段),
故建 mx30>=2 超集一次, 各W过滤即可; 同步看全池与白名单层①/层②/层②'.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)
WS = (10, 12, 15, 18, 20, 25, 30)


def yr_line(s):
    return " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                      if len(sy := s[s["trade_date"].dt.year == yy]))


def st(s, lab, ind="  "):
    if not len(s):
        print(f"{ind}{lab}: n=0")
        return
    print(f"{ind}{lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% | 分年 {yr_line(s)}")


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
    stk = bars["streak"].astype(float)
    for wd in WS:
        if wd == 20:
            continue  # mx20 已有
        bars[f"mx{wd}"] = stk.groupby(bars["sid"], sort=False).transform(
            lambda s, wd=wd: s.shift(1).rolling(wd, min_periods=1).max())

    # 超集(任W可中的票都在内): mx30>=2 + 各组基础过滤
    bars["sup_y"] = ((bars["mx30"] >= 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                     & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["sup_g"] = ((bars["mx30"] >= 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                     & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    # 断板期曾收顶上(层①②用), 与窗口无关
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def _topped(sid, pos):
        i = p2i[int(sid)][int(pos)]
        c, zt = cl_by[int(sid)], zt_by[int(sid)]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return False
        return bool((c[j + 1:i] >= c[j]).any())

    dun = ["U", "MID", "FLAT", "V", "LB"]
    for name, c in (("2板补涨阴", "sup_y"), ("2板补涨阳", "sup_g")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["topped"] = [_topped(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        print("=" * 96)
        print(f"【{name}】超集 n={len(tg)}")
        print(f"{'W':>4} | {'全池n':>5} {'全池均':>7} {'胜率':>4} | 白名单层 n / 板留均 / 分年")
        for wd in WS:
            sub = tg[tg[f"mx{wd}"] == 2]
            if name == "2板补涨阴":
                lay = sub[sub["base"].isin(dun) & ~(sub["reb"] > 0.16)
                          & sub["gap"].between(6, 15) & ~sub["topped"]]
                lname = "层①"
            else:
                l2 = sub[(sub["base"] == "DN") & ~sub["topped"]]
                l2p = sub[sub["base"].isin(dun) & sub["ma_st"].isin(["-++", "+--"])]
                lay = (l2, l2p)
                lname = "层②/②'"
            line = (f"{wd:>4} | {len(sub):>5} {sub['r_bh'].mean() * 100:>+7.2f} "
                    f"{(sub['r_bh'] > 0).mean() * 100:>3.0f}% | ")
            if name == "2板补涨阴":
                line += f"{lname} n={len(lay)} {lay['r_bh'].mean() * 100:+.2f} | {yr_line(lay)}"
            else:
                line += (f"层② n={len(l2)} {l2['r_bh'].mean() * 100:+.2f} | {yr_line(l2)}")
                line += (f"\n     | {'':>5} {'':>7} {'':>4} | "
                         f"层②' n={len(l2p)} {l2p['r_bh'].mean() * 100:+.2f} | {yr_line(l2p)}")
            print(line)

        # W=15 vs W=20 的票进出分析(主人关心15): 进=15有20无(老3板出窗), 出=20有15无
        if True:
            k15 = set(zip(tg[tg["mx15"] == 2]["sid"], tg[tg["mx15"] == 2]["pos"]))
            k20 = set(zip(tg["sid"], tg["pos"])) & set(
                zip(tg[tg["mx20"] == 2]["sid"], tg[tg["mx20"] == 2]["pos"]))
            tg["k"] = list(zip(tg["sid"], tg["pos"]))
            inn = tg[tg["k"].isin(k15 - k20)]
            out = tg[tg["k"].isin(k20 - k15)]
            print(f"\n  W=15相对W=20: 新进 {len(inn)}笔 ", end="")
            st(inn, "", "")
            print(f"               移出 {len(out)}笔 ", end="")
            st(out, "", "")
            if len(out):
                gout = out["gap"].describe()
                print(f"               移出票gap分布: 中位{gout['50%']:.0f} 最小{gout['min']:.0f} 最大{gout['max']:.0f}")


if __name__ == "__main__":
    main()
