# -*- coding: utf-8 -*-
"""坑连续因子抽象(主人定调 2026-08-29): V=窄U, 横盘/中位浅调=浅U, 全部统一为U的深宽参数,
仅新高贴顶(出坑)除外. 抽象因子(全D-1可观测):

  坑深 dd = low_dd  (断板期最低收盘距上波顶, 越深越负)
  坑宽 ww = gap     (断板天数)
  进度 pr = 1 - pull/low_dd  (0=还在坑底, 1=爬回坑口; 对坑深归一, 跨票可比)
  洗速 sp = |low_dd|/gap     (平均每天蹲多深)

验证: ①非HIGH池(全体坑) dd×pr 地形 ②pr 单调性 ③连续出手条件 vs 现白名单层①(488笔+1.54)
④DN是否被 pr≈0 自动分离 ⑤标签点云在因子空间的分布(归并检查).
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
DD_LABS = ["浅坑-8~-4%", "中坑-15~-8", "深坑-25~-15", "超深<-25%"]
PR_LABS = ["pr0~0.3(坑底)", "pr0.3~0.6(下坡)", "pr0.6~0.85(半坡上)", "pr0.85~1(坑口)"]


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

    for tag, name in (("c4a", "2板阴(出手组)"), ("c4b", "2板阳")):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        pit = tg[tg["base"] != "HIGH"].copy()          # 全体坑(非出坑)
        pit["dd"] = pd.cut(pit["low_dd"], [-0.99, -0.25, -0.15, -0.08, -0.04], labels=DD_LABS)
        pit["pr"] = 1 - pit["pull"] / pit["low_dd"]     # 进度因子(坑深归一)
        pit["pr桶"] = pd.cut(pit["pr"], [0, 0.3, 0.6, 0.85, 1.0], labels=PR_LABS)

        print("=" * 110)
        print(f"== {name} · 坑连续因子: 坑深 × 爬坑进度 板留地形 (n/板留%) ==")
        for dd in DD_LABS:
            parts = []
            for pr in PR_LABS:
                s = pit[(pit["dd"] == dd) & (pit["pr桶"] == pr)]
                parts.append(f"{len(s)}/{s['r_bh'].mean() * 100:+.2f}" if len(s) else "—")
            print(f"  {dd:12s}: " + " | ".join(f"{p}" for p in parts))

        print("\n  同格子标签构成(n>=3): ")
        for dd in DD_LABS:
            for pr in PR_LABS:
                cell = pit[(pit["dd"] == dd) & (pit["pr桶"] == pr)]
                if len(cell) < 12:
                    continue
                labs = [f"{BASE_CN[b]} {len(s)}/{s['r_bh'].mean() * 100:+.2f}"
                        for b, s in cell.groupby("base") if len(s) >= 3]
                if len(labs) >= 2:
                    print(f"    {dd}×{pr}: " + " | ".join(labs))

        print("\n  连续因子出手条件 vs 现白名单:")
        wl = tg[tg["base"].isin(["U", "MID", "FLAT", "V", "LB"]) & ~(tg["reb"] > 0.16)]
        stat(wl, "现白名单层①(标签版)")
        cond = pit[(pit["dd"].isin(["中坑-15~-8", "深坑-25~-15"]))
                   & pit["pr桶"].isin(["pr0.3~0.6(下坡)", "pr0.6~0.85(半坡上)"])]
        stat(cond, "连续版: 中深坑×pr0.3~0.85")
        cond2 = pit[pit["pr桶"].isin(["pr0.3~0.6(下坡)", "pr0.6~0.85(半坡上)"])
                    & pit["dd"].isin(["中坑-15~-8", "深坑-25~-15", "浅坑-8~-4%"])
                    & (pit["reb"] <= 0.16)]
        stat(cond2, "连续版+浅坑+弹回≤16%")

        print("\n  DN 的 pr 分布(验证进度因子自动分离坑底票):")
        dn = pit[pit["base"] == "DN"]
        print(f"    DN: n={len(dn)} pr中位 {dn['pr'].median():.2f} | pr<0.3 占 "
              f"{(dn['pr'] < 0.3).mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
