# -*- coding: utf-8 -*-
"""主人个案核查: 华电能源600726 2026-05-13 层③✅出手「孤板×多头」封D1负 —— 坑深仅-6%擦边、已爬回顶上, 这也算U吗?
① 逐日走势还原(锚=最近≥2板段最高价, build_base口径)
② 层③全量: U状态(坑内/突破) × 坑深档 交叉 —— 浅坑擦边回顶是否毒格
③ 全4+阴底池同拆(放大数据看「浅坑擦边」是否天然弱)
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)


def st(s, lab, ind="  "):
    if not len(s):
        print(f"{ind}{lab}: n=0")
        return
    yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    print(f"{ind}{lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
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
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    tg, _ = build_base(bars, segs, conds=("c4c",))
    tg = add_outcome(tg, bars)
    L3 = tg[(tg["seg_h"] >= 4) & tg["n_lim_mid"].between(1, 2)
            & (tg["ma_st"] == "+++") & (tg["low_dd"] <= -0.04)].copy()
    L3["st3"] = np.where(L3["pull"] > -0.04, "U突破(已回顶)", "U坑内")

    # ① 华电能源逐日还原
    r0 = L3[(L3["vt_symbol"] == "600726.SSE")
            & (L3["trade_date"].dt.strftime("%Y-%m-%d") == "2026-05-13")]
    if len(r0):
        r0 = r0.iloc[0]
        sid, pos = int(r0["sid"]), int(r0["pos"])
        print(f"① 600726 华电能源 2026-05-13 层③档案: 坑深low_dd={r0['low_dd'] * 100:+.1f}% "
              f"昨收距顶pull={r0['pull'] * 100:+.1f}% 坑底弹起reb={r0['reb'] * 100:+.1f}% "
              f"坑宽gap={r0['gap']:.0f}天 seg_h={r0['seg_h']:.0f} 断板期孤立板={r0['n_lim_mid']:.0f} "
              f"均线={r0['ma_st']}")
        sg = segs[(segs["sid"] == sid) & (segs["height"] >= 2)
                  & (segs["last_pos"] < pos)].sort_values("last_pos")
        ph = float(sg["high_price"].iloc[-1])
        lp = int(sg["last_pos"].iloc[-1])
        sb = bars[bars["sid"] == sid].reset_index(drop=True)
        i = int(sb.index[sb["pos"] == pos][0])
        print(f"   锚段: 末板pos={lp} 段最高价ph={ph:.2f} ({sb.loc[sb['pos'] == lp, 'trade_date'].iloc[0].date()})")
        print(f"   {'日期':>10} {'收':>8} {'幅%':>6} {'标记':>6} {'距顶%':>7}")
        for _, r in sb.iloc[max(0, i - 30):i + 2].iterrows():
            pull = (r["close_price"] / ph - 1) * 100
            mark = "涨停" if r["is_lim"] else ("◀信号日" if r["pos"] == pos else "")
            print(f"   {str(r['trade_date'].date()):>10} {r['close_price']:>8.2f} "
                  f"{r['p_chg'] * 100 if r['p_chg'] == r['p_chg'] else float('nan'):>+6.1f} "
                  f"{mark:>6} {pull:>+7.1f}")

    # ② 层③全量: U状态 × 坑深档
    print(f"\n② 层③全量 n={len(L3)}:")
    st(L3, "层③全体", "")
    for lab, s in (("U坑内(昨收仍在坑里)", L3[L3["st3"] == "U坑内"]),
                   ("U突破(已爬回顶上)", L3[L3["st3"] == "U突破(已回顶)"])):
        st(s, lab)
    print("  坑深档 × U状态:")
    for lo, hi, dlab in ((-0.08, -0.04, "擦边坑4~8%"), (-0.15, -0.08, "中坑8~15%"),
                         (-9, -0.15, "深坑>15%")):
        s0 = L3[L3["low_dd"].between(lo, hi, inclusive="right")]
        st(s0, f"{dlab} 全体")
        for slab in ("U坑内", "U突破(已回顶)"):
            s = s0[s0["st3"] == slab]
            if len(s):
                st(s, f"{dlab}×{slab}", "    ")

    # ③ 全4+阴底池(不套层③其他条件): U状态 × 坑深档 —— 放大数据看浅坑擦边
    print(f"\n③ 全4+阴触发底池 n={len(tg)} (不套孤板/均线条件):")
    tg2 = tg.copy()
    tg2["st3"] = np.where(tg2["low_dd"] > -0.04, "无U",
                          np.where(tg2["pull"] > -0.04, "U突破(已回顶)", "U坑内"))
    for lab in ("无U", "U突破(已回顶)", "U坑内"):
        st(tg2[tg2["st3"] == lab], lab, "")
    print("  U突破 × 坑深档(浅坑擦边回顶=贴顶伪U?):")
    u = tg2[tg2["st3"] == "U突破(已回顶)"]
    for lo, hi, dlab in ((-0.08, -0.04, "擦边坑4~8%"), (-0.15, -0.08, "中坑8~15%"),
                         (-9, -0.15, "深坑>15%")):
        s = u[u["low_dd"].between(lo, hi, inclusive="right")]
        st(s, f"U突破×{dlab}")
    print("  华电能源所在格 = 层③ × 擦边坑4~8% × U突破")


if __name__ == "__main__":
    main()
