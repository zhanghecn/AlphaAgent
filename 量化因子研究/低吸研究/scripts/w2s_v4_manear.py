# -*- coding: utf-8 -*-
"""主人补充维度(2026-08-29): D-1收盘距离哪条均线最近(贴线归属) + 偏离度.

因子(D-1口径): dist_n = 昨收/昨MA_n - 1 (n=5/10/20/30/60)
  最近线 = argmin|dist_n|; 偏离 = min|dist_n| (越小越贴线)
个案: 锦江航运2025-04-15(2板阳·横盘平台·差票). 四组: 最近线归属×偏离度.
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
    print(f"  {label}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} 胜率 "
          f"{(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% | {ys}")


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

    def near_feat(sid, pos):
        i = p2i[sid][pos] - 1
        if i < 1:
            return None
        c = cl_by[sid][i]
        dists = []
        for n in MAS:
            m = ma_by[n][sid][i]
            dists.append(c / m - 1 if m == m else np.nan)
        if all(d != d for d in dists):
            return None
        j = int(np.nanargmin(np.abs(np.array(dists, dtype=float))))
        return MAS[j], abs(dists[j]), dists[j]

    for tag, name in (("c4a", "2板阴"), ("c4b", "2板阳"), ("c4c", "4+阴"), ("c4d", "4+阳")):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        rows = []
        for r in tg.itertuples():
            f = near_feat(int(r.sid), int(r.pos))
            if f is None:
                continue
            rows.append({"idx": r.Index, "near": f"MA{f[0]}", "dev": f[1], "raw": f[2]})
        ft = pd.DataFrame(rows).set_index("idx")
        d = tg.join(ft)
        d = d[d["near"] == d["near"]].copy()

        print("=" * 108)
        print(f"== {name} (n={len(d)}) · D-1距哪条均线最近 ==")
        print("  ① 最近线归属:")
        for n in MAS:
            stat(d[d["near"] == f"MA{n}"], f"  最近MA{n}")

        print("  ② 偏离度(距最近线):")
        d["偏"] = pd.cut(d["dev"], [0, 0.01, 0.03, 0.06, 99],
                         labels=["<1%(贴线)", "1~3%", "3~6%", ">6%(悬空)"])
        for lab in ("<1%(贴线)", "1~3%", "3~6%", ">6%(悬空)"):
            stat(d[d["偏"] == lab], f"  {lab}")

        print("  ③ 最近线×贴线(<1.5%)交叉:")
        for n in MAS:
            s = d[(d["near"] == f"MA{n}") & (d["dev"] < 0.015)]
            if len(s):
                stat(s, f"  贴MA{n}")

    # 个案
    print("\n个案 锦江航运 2025-04-15 (2板阳·横盘平台·封D1负):")
    tg, _ = build_base(bars, segs, conds=("c4b",))
    tg = add_outcome(tg, bars)
    for r in tg[tg["vt_symbol"] == "601083.SSE"].itertuples():
        if str(r.trade_date)[:10] == "2025-04-15":
            f = near_feat(int(r.sid), int(r.pos))
            print(f"  最近线=MA{f[0]} 偏离{f[1] * 100:.1f}% 带符号{f[2] * 100:+.1f}% "
                  f"板留{r.r_bh * 100:+.1f}%")


if __name__ == "__main__":
    main()
