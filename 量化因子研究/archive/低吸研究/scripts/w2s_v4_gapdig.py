# -*- coding: utf-8 -*-
"""主人时间维度假设核查(2026-08-29): ①"浅蹲"实际=横盘够久(4+阳HIGH浅蹲按断板天数拆)
②2板阳的好地基是否都是"隔一段时间"的(地基×断板天数矩阵+好格子gap分布)
③主力②(2板阳×DN)按gap分桶+分年.

gap=断板天数(上波≥2板段末板到D0的交易日数), D-1可观测.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

BASE_CN = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
           "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}
GAP_BINS = [1, 6, 11, 16, 99]
GAP_LABS = ["断2-5", "断6-10", "断11-15", "断16+"]


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
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    tgb, _ = build_base(bars, segs, conds=("c4b",))
    tgb = add_outcome(tgb, bars)
    tgb["bad"] = tgb["res"].isin(["炸板", "封D1负"])
    tgd, _ = build_base(bars, segs, conds=("c4d",))
    tgd = add_outcome(tgd, bars)
    tgd["bad"] = tgd["res"].isin(["炸板", "封D1负"])

    print("=" * 104)
    print("== ① 2板阳: 地基 × 断板天数 板留矩阵 (n/板留/胜率) ==")
    tgb["gap桶"] = pd.cut(tgb["gap"], GAP_BINS, labels=GAP_LABS)
    for b in ("DN", "HIGH", "FLAT", "V", "MID", "U", "LB"):
        sub = tgb[tgb["base"] == b]
        if not len(sub):
            continue
        parts = []
        for gl in GAP_LABS:
            s = sub[sub["gap桶"] == gl]
            if len(s):
                parts.append(f"{gl} {len(s)}笔/{s['r_bh'].mean() * 100:+.2f}/{(s['r_bh'] > 0).mean() * 100:.0f}%")
            else:
                parts.append(f"{gl} —")
        print(f"  {BASE_CN[b]:　<5s}: " + " | ".join(parts))

    print("\n== ② 主力②(2板阳×DN) gap分桶+分年 ==")
    for gl in GAP_LABS:
        s = tgb[(tgb["base"] == "DN") & (tgb["gap桶"] == gl)]
        stat(s, f"  DN·{gl}")

    print("\n== ③ 2板阳好差票 gap 分布(中位/均值) ==")
    for b in ("DN", "FLAT", "HIGH", "V", "MID"):
        sub = tgb[tgb["base"] == b]
        if not len(sub):
            continue
        gd, gb = sub[sub["bad"]]["gap"], sub[~sub["bad"]]["gap"]
        print(f"  {BASE_CN[b]:　<5s}: 差票gap中位 {gd.median():.0f} 均 {gd.mean():.0f} | "
              f"好票gap中位 {gb.median():.0f} 均 {gb.mean():.0f}")

    print("\n== ④ 4+阳 HIGH浅蹲(-12~-4%) × gap (主人: 浅蹲要横盘够久) ==")
    H = tgd[(tgd["base"] == "HIGH") & (tgd["low_dd"] > -0.12) & (tgd["low_dd"] <= -0.04)]
    H = H.assign(gap桶=pd.cut(H["gap"], GAP_BINS, labels=GAP_LABS))
    for gl in GAP_LABS:
        stat(H[H["gap桶"] == gl], f"  浅蹲HIGH·{gl}")
    print("  对照: 4+阳 HIGH深蹲(≤-12%)×gap:")
    H2 = tgd[(tgd["base"] == "HIGH") & (tgd["low_dd"] <= -0.12)]
    H2 = H2.assign(gap桶=pd.cut(H2["gap"], GAP_BINS, labels=GAP_LABS))
    for gl in GAP_LABS:
        stat(H2[H2["gap桶"] == gl], f"  深蹲HIGH·{gl}")


if __name__ == "__main__":
    main()
