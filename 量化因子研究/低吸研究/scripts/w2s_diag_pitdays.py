# -*- coding: utf-8 -*-
"""主人个案核查: 易德龙603380 2026-07-08「✅U坑」D1收-10% —— 主人说看着是贴顶新高不像U.
① 逐日走势还原 ② 假设: 假U=坑宽虽够但「真正跌进坑里(距顶>4%)的天数」很少(横盘贴顶+昨日急跌),
   全量验证层①池按「坑里天数」分层.
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

    # ① 易德龙逐日还原
    sb = bars[bars["vt_symbol"] == "603380.SSE"]
    win = sb[(sb["trade_date"] >= "2026-06-08") & (sb["trade_date"] <= "2026-07-09")]
    print("① 603380 易德龙 2026-06-08~07-09 逐日:")
    print(f"{'日期':>10} {'收':>8} {'幅%':>6} {'涨停':>4} {'距顶%':>7}")
    top = None
    for _, r in win.iterrows():
        if r["is_lim"]:
            top = r["close_price"]
        pull = (r["close_price"] / top - 1) * 100 if top else np.nan
        print(f"{str(r['trade_date'].date()):>10} {r['close_price']:>8.2f} "
              f"{r['p_chg'] * 100 if r['p_chg'] == r['p_chg'] else float('nan'):>+6.1f} "
              f"{'涨停' if r['is_lim'] else '':>4} {pull:>+7.1f}")

    # ② 全量: 层①池按「坑里天数」分层 (坑=收盘距顶>4%; 锚=昨日前最后一次涨停日, 与问财口径一致)
    tg, _ = build_base(bars, segs, conds=("c4a",))
    tg = add_outcome(tg, bars)
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def pit_days(r):
        """断板期内 (收盘距顶>4%的真坑天数, 曾收顶上方的天数)."""
        sid, pos = int(r.sid), int(r.pos)
        i = p2i[sid][pos]
        c, zt = cl_by[sid], zt_by[sid]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return np.nan, np.nan
        seg = c[j + 1:i]
        return int((seg < c[j] * 0.96).sum()), int((seg >= c[j]).sum())

    l1 = tg[tg["base"].isin(["U", "MID", "FLAT", "V", "LB"])
            & ~(tg["reb"] > 0.16) & tg["gap"].between(6, 15)].copy()
    pd_ab = [pit_days(r) for r in l1.itertuples()]
    l1["pit_days"] = [a for a, _ in pd_ab]
    l1["top_days"] = [b for _, b in pd_ab]
    print(f"\n② 层①池 n={len(l1)} 按坑里天数分层:")
    for lo, hi in ((0, 1), (2, 3), (4, 6), (7, 99)):
        s = l1[l1["pit_days"].between(lo, hi)]
        if not len(s):
            continue
        yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                        if len(sy := s[s["trade_date"].dt.year == yy]))
        print(f"  坑里{lo}-{hi}天: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
              f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% "
              f"| 分年 {yr}")
    # 规则A: 断板期曾收在顶上方(=贴顶震荡伪U) 剔除
    print("\n  规则A·断板期是否曾收在顶上方:")
    for lab, s in (("曾收顶上(伪U)", l1[l1["top_days"] > 0]),
                   ("从未收顶上(真U)", l1[l1["top_days"] == 0])):
        yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                        if len(sy := s[s["trade_date"].dt.year == yy]))
        print(f"  {lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
              f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% "
              f"| 分年 {yr}")
    # 规则B: 曾收顶上 × 坑深 交叉
    print("\n  规则B·曾收顶上 × 坑深:")
    for lab2, m in (("浅坑<10%", l1["low_dd"] > -0.10), ("深坑≥10%", l1["low_dd"] <= -0.10)):
        for lab1, s0 in (("曾收顶上", l1[l1["top_days"] > 0]), ("从未", l1[l1["top_days"] == 0])):
            s = s0[m.reindex(s0.index)]
            if len(s):
                print(f"    {lab2}×{lab1}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
                      f"好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}%")
    # 易德龙的坑里天数
    r0 = l1[(l1["vt_symbol"] == "603380.SSE")
            & (l1["trade_date"].dt.strftime("%Y-%m-%d") == "2026-07-08")]
    if len(r0):
        print(f"\n  易德龙: 坑宽{r0['gap'].iloc[0]:.0f} 坑里天数={r0['pit_days'].iloc[0]} "
              f"曾收顶上天数={r0['top_days'].iloc[0]} 坑深{r0['low_dd'].iloc[0] * 100:+.1f}%")


if __name__ == "__main__":
    main()
