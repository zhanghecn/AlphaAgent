# -*- coding: utf-8 -*-
"""弹回上限过滤(主人拍板 2026-08-29): 蹲类地基弹回>16% 直接过滤.

主人算术质疑验证: 弹>16%再涨停 = 距低点+27.6%+, 蹲深12~25%的坑基本填平 → 板后基本贴顶/破顶,
这种"U"语义上已是新高贴顶回踩(阴组HIGH=-0.16本就是砍的), 不是蹲完刚起跳.
① 层1里 reb>16% 的票逐笔明细 + 板后距顶((1+pull)*1.1-1)分布;
② 层1 / 白名单四层并集 过滤前后对比(笔数/板留/胜率/差票/分年/复利).
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


def stat(s, label):
    if not len(s):
        print(f"  {label}: n=0")
        return
    ys = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} 胜率 "
          f"{(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% | 分年 {ys}")
    m = s.groupby(s["trade_date"].dt.strftime("%Y-%m"))["r_bh"].mean()
    m = m[m.index >= "2023-01"]
    comp = ((1 + m[m.index < "2026-01"]).prod() - 1) * 100 if len(m) else np.nan
    print(f"    23-25月均分复利 {comp:+.1f}%")


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

    tgs = {}
    for tag, c in (("1", "c4a"), ("2", "c4b"), ("3", "c4c"), ("4", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        tgs[tag] = tg

    L1 = tgs["1"][tgs["1"]["base"].isin(["U", "MID", "FLAT", "V", "LB"])].copy()
    L1["板后距顶"] = (1 + L1["pull"]) * 1.10 - 1          # 涨停买价距上波顶

    print("== ① 层1(2板阴蹲类) 弹回>16% 的票逐笔 ==")
    fly = L1[L1["reb"] > 0.16].sort_values("reb", ascending=False)
    for r in fly.itertuples():
        print(f"  {r.vt_symbol} {r.name} {str(r.trade_date)[:10]} {BASE_CN[r.base]:　<4s} "
              f"蹲深{r.low_dd * 100:+6.1f}% 弹回{r.reb * 100:+6.1f}% 距顶{r.pull * 100:+6.1f}% "
              f"→ 板后距顶{r.板后距顶 * 100:+6.1f}% {'破顶' if r.板后距顶 > 0 else '贴顶' if r.板后距顶 > -0.03 else ''}"
              f" | {r.res} 板留{r.r_bh * 100:+.1f}%")
    n_top = (fly["板后距顶"] > -0.03).sum()
    print(f"  合计 {len(fly)} 笔: 板后距顶>-3%(基本贴顶/破顶) {n_top} 笔 "
          f"({n_top / len(fly) * 100:.0f}%), 板留均 {fly['r_bh'].mean() * 100:+.2f}%")

    print("\n== ② 过滤前后对比 ==")
    keep = ~(L1["reb"] > 0.16)
    stat(L1, "层1·过滤前")
    stat(L1[keep], "层1·过滤后(弹回≤16%)")

    L2 = tgs["2"][tgs["2"]["base"] == "DN"]
    nm3 = tgs["3"]["n_lim_mid"]
    L3 = tgs["3"][(tgs["3"]["seg_h"] >= 4) & nm3.between(1, 2)]
    L4 = tgs["4"][tgs["4"]["seg_h"] == 2]
    union_old = pd.concat([L1, L2, L3, L4], ignore_index=True)
    union_new = pd.concat([L1[keep], L2, L3, L4], ignore_index=True)
    stat(union_old, "四层并集·过滤前")
    stat(union_new, "四层并集·过滤后")


if __name__ == "__main__":
    main()
