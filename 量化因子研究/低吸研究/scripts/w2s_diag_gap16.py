# -*- coding: utf-8 -*-
"""主人核查: 2板补涨阴「坑宽16天+不在6~15」被剔的票是不是大多好票?
层①条件去掉坑宽限制, 按坑宽档切: 2-5 / 6-10 / 11-15 / 16-20 / 21+.
好差口径=D+1盈亏(主人定稿: r_d1c>0为好票, 炸板次日收复也算好).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    tg, _ = build_base(bars, segs, conds=("c4a",))
    tg = add_outcome(tg, bars)
    tg["bad"] = tg["r_d1c"] <= 0          # D+1盈亏口径

    pool = tg[tg["base"].isin(["U", "MID", "FLAT", "V", "LB"])
              & ~(tg["reb"] > 0.16)].copy()   # 层①去掉坑宽限制的母池
    print(f"层①母池(蹲类+弹回≤16%, 不限坑宽): n={len(pool)} "
          f"板留均 {pool['r_bh'].mean() * 100:+.2f} 好票率 {(~pool['bad']).mean() * 100:.0f}%")

    bands = [(2, 5), (6, 10), (11, 15), (16, 20), (21, 99)]
    print("\n坑宽档 × 全期:")
    print(f"{'坑宽':>8} {'n':>4} {'板留均':>7} {'胜率':>5} {'好票率':>6} {'连板%':>5}  分年板留")
    for lo, hi in bands:
        s = pool[pool["gap"].between(lo, hi)]
        if not len(s):
            continue
        yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}(n{len(sy)})"
                        for yy in (2023, 2024, 2025, 2026)
                        if len(sy := s[s["trade_date"].dt.year == yy]))
        print(f"{f'{lo}-{hi}':>8} {len(s):>4} {s['r_bh'].mean() * 100:>+7.2f} "
              f"{(s['r_bh'] > 0).mean() * 100:>4.0f}% {(~s['bad']).mean() * 100:>5.0f}% "
              f"{(s['res'] == '连板').mean() * 100:>4.0f}%  {yr}")

    # 2026-08 单月: 主人看到的现象
    m = pool[pool["trade_date"].dt.strftime("%Y-%m") == "2026-08"]
    print(f"\n2026-08 单月 层①母池: n={len(m)}")
    for lo, hi in bands:
        s = m[m["gap"].between(lo, hi)]
        if len(s):
            print(f"  坑宽{lo}-{hi}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
                  f"好票率 {(~s['bad']).mean() * 100:.0f}%")
    print("\n2026-08 坑宽≥16 逐笔:")
    s16 = m[m["gap"] >= 16].sort_values("trade_date")
    for _, r in s16.iterrows():
        print(f"  {r['vt_symbol']} {r['name']} {r['trade_date'].date()} 坑宽{r['gap']:.0f} "
              f"坑深{r['low_dd'] * 100:+.1f} 弹回{r['reb'] * 100:+.1f} "
              f"{r['res']} D1收{r['r_d1c'] * 100:+.1f} 板留{r['r_bh'] * 100:+.1f} "
              f"{'好票' if not r['bad'] else '差票'}")


if __name__ == "__main__":
    main()
