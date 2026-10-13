# -*- coding: utf-8 -*-
"""层③候选修订验证: 剔除「中坑8~15%×已回顶(已回顶)」7笔-1.98毒格后, 层③完整指标与分年.
对照: 现层③ n=34 +4.01 全正.
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
    nm = s["trade_date"].dt.strftime("%Y-%m").nunique()
    print(f"{ind}{lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% "
          f"连板 {(s['res'] == '连板').mean() * 100:.0f}% | 分年 {yr} | 月均{len(s) / nm:.1f}")


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
    brk = L3["pull"] > -0.04                      # 已回顶(已回顶)
    mid = L3["low_dd"].between(-0.15, -0.08, inclusive="right")   # 中坑8~15%
    toxic = brk & mid

    st(L3, "现层③(对照)", "")
    st(L3[toxic], "被剔: 中坑8~15%×已回顶", "")
    st(L3[~toxic], "修订层③(剔毒格后)", "")

    # 合并进并集看总账变化: 修订前后并集差 = 这7笔从并集消失(它们只属于层③)
    print("\n  被剔7笔明细:")
    cols = ["vt_symbol", "trade_date", "low_dd", "pull", "gap", "r_bh", "res"]
    t = L3[toxic][cols].copy()
    t["trade_date"] = t["trade_date"].dt.strftime("%Y-%m-%d")
    t["low_dd"] = (t["low_dd"] * 100).round(1)
    t["pull"] = (t["pull"] * 100).round(1)
    t["r_bh"] = (t["r_bh"] * 100).round(1)
    print(t.to_string(index=False, header=["代码", "信号日", "坑深%", "距顶%", "坑宽", "板留%", "结果"]))


if __name__ == "__main__":
    main()
