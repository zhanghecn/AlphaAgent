# -*- coding: utf-8 -*-
"""4+补涨阳 专项研究(主人: 先不算夹层seg_h==2): U坑条件×均线条件能否独立成立.
维度: ①U三状态 ②U坑内×坑深×弹回 ③均线8排列态 ④均线收敛度(s510/s1020乖离) ⑤曾收顶上 ⑥组合格.
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
        return "无U"
    if pull == pull and pull > -0.04:
        return "U突破"
    return "U坑内"


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
    for n in (5, 10, 20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    ok = bars[["ma5", "ma10", "ma20", "ma30"]].notna().all(axis=1)
    bars["ma_st"] = ""
    bars.loc[ok, "ma_st"] = (
        np.where(bars.loc[ok, "ma5"] > bars.loc[ok, "ma10"], "+", "-")
        + np.where(bars.loc[ok, "ma10"] > bars.loc[ok, "ma20"], "+", "-")
        + np.where(bars.loc[ok, "ma20"] > bars.loc[ok, "ma30"], "+", "-"))
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    tg, _ = build_base(bars, segs, conds=("c4d",))
    tg = add_outcome(tg, bars)
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

    tg["topped"] = [topped_of(s, p) for s, p in zip(tg["sid"], tg["pos"])]
    tg["pos3"] = [pos_of(dd, pu) for dd, pu in zip(tg["low_dd"], tg["pull"])]
    # 均线乖离(D-1口径): s510=ma5/ma10-1, s1020=ma10/ma20-1
    tg["s510"] = tg["ma5"] / tg["ma10"] - 1
    tg["s1020"] = tg["ma10"] / tg["ma20"] - 1

    print(f"seg_h分布(剔夹层前): {dict(tg['seg_h'].value_counts().sort_index())}")
    pool = tg[tg["seg_h"] != 2].copy()          # 主人: 先不算夹层
    print(f"底池: 4+阳 非夹层 n={len(pool)} (剔2板小波穿插 {len(tg) - len(pool)}笔)")
    stat(tg[tg["seg_h"] == 2], "对照·夹层票(本研究不看)", "")
    stat(pool, "非夹层底池", "")

    print("\n① U三状态:")
    for p3 in ("无U", "U坑内", "U突破"):
        s = pool[pool["pos3"] == p3]
        stat(s, p3)
        if p3 != "无U":
            stat(s[s["topped"]], f"{p3}×曾收顶上", "    ")
            stat(s[~s["topped"]], f"{p3}×未收顶上", "    ")

    print("\n② U坑内 × 坑深 × 弹回:")
    uin = pool[pool["pos3"] == "U坑内"]
    for lo, hi, lab in ((-0.10, -0.04, "浅坑4~10%"), (-0.18, -0.10, "中坑10~18%"),
                        (-9, -0.18, "深坑>18%")):
        s = uin[uin["low_dd"].between(lo, hi, inclusive="right")]
        stat(s, f"{lab} (n={len(s)})")
        for rlo, rhi, rlab in ((-9, 0.03, "贴坑底"), (0.03, 0.16, "弹起3~16"), (0.16, 99, "弹飞>16")):
            ss = s[s["reb"].between(rlo, rhi, inclusive="right")]
            if len(ss):
                stat(ss, f"{lab}×{rlab}", "    ")

    print("\n③ 均线8排列态 × 底池 / ×U坑内:")
    for st in ("+++", "++-", "+-+", "+--", "-++", "-+-", "--+", "---"):
        s = pool[pool["ma_st"] == st]
        su = uin[uin["ma_st"] == st]
        if len(s) >= 8:
            stat(s, f"{st} 底池")
            if len(su) >= 5:
                stat(su, f"{st} ×U坑内", "    ")

    print("\n④ 均线收敛度(U坑内, s1020=MA10/MA20乖离):")
    for lo, hi, lab in ((-9, 0.0, "空(10<20)"), (0.0, 0.03, "收敛0~3%"),
                        (0.03, 0.06, "发散3~6%"), (0.06, 99, "很发散>6%")):
        s = uin[uin["s1020"].between(lo, hi, inclusive="right")]
        stat(s, f"s1020 {lab}")

    print("\n⑤ 组合尝试: U坑内 × 深坑>10% × 纠缠态(-++/+--):")
    stat(uin[(uin["low_dd"] <= -0.10) & uin["ma_st"].isin(["-++", "+--"])], "U坑内×深>10%×纠缠")
    stat(uin[(uin["low_dd"] <= -0.10) & (uin["s1020"] <= 0.03)], "U坑内×深>10%×收敛(1020≤3%)")
    stat(uin[uin["reb"].between(0.03, 0.16) & uin["ma_st"].isin(["-++", "+--"])], "U坑内×弹起×纠缠")
    stat(uin[uin["reb"].between(0.03, 0.16) & ~uin["topped"]], "U坑内×弹起×未收顶上")
    stat(pool[(pool["pos3"] == "U突破") & ~pool["topped"]], "U突破×未收顶上")
    stat(pool[(pool["pos3"] == "U突破") & pool["topped"]], "U突破×曾收顶上")


if __name__ == "__main__":
    main()
