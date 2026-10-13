# -*- coding: utf-8 -*-
"""追查(主人质疑000892 U型蹲): 2板补涨阴×U型蹲 组内, 按 pull(昨收距顶) 分层 --
"蹲完刚起跳的深坑U" vs "已弹到坑口贴顶的U"(如000892 8-04, pull=-9.8% 弹回+26.8%),
以及 pos_low 边界带(0.5~0.7)的漂移票. 验证白名单 U 格的肉有没有被贴顶U稀释.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import build_base, add_outcome

pd.set_option("display.width", 400)


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    tg, _ = build_base(bars, segs, conds=("c4a",))
    tg = add_outcome(tg, bars)
    tg["bad"] = tg["res"].isin(["炸板", "封D1负"])

    U = tg[tg["base"] == "U"].copy()
    print(f"2板补涨阴×U型蹲 全部 {len(U)} 笔, 板留均 {U['r_bh'].mean() * 100:+.2f}%\n")

    print("== ① U组按 pull(昨收距顶) 分层 ==")
    U["pull桶"] = pd.cut(U["pull"], [-0.99, -0.12, -0.08, -0.04],
                         labels=["深坑<-12%", "中位-8~-12%", "坑口-4~-8%(贴顶U)"])
    t = U.groupby("pull桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                               胜率=("r_bh", lambda s: (s > 0).mean()),
                                               差票率=("bad", "mean"))
    t["胜率"] = (t["胜率"] * 100).round(0); t["差票率"] = (t["差票率"] * 100).round(0)
    t["板留均"] = (t["板留均"] * 100).round(2)
    print(t.to_string())
    for lab in ("深坑<-12%", "中位-8~-12%", "坑口-4~-8%(贴顶U)"):
        s = U[U["pull桶"] == lab]
        if not len(s):
            continue
        ys = [f"{y}:{s[s['trade_date'].dt.year == y]['r_bh'].mean() * 100:+.2f}(n{len(s[s['trade_date'].dt.year == y])})"
              for y in (2023, 2024, 2025, 2026) if len(s[s["trade_date"].dt.year == y])]
        print(f"  {lab} 分年: {' / '.join(ys)}")

    print("\n== ② U组按弹回高度 reb 分层 ==")
    U["reb桶"] = pd.cut(U["reb"], [0.05, 0.10, 0.16, 99], labels=["弹6~10%(刚起跳)", "弹10~16%", "弹>16%(已飞)"])
    t = U.groupby("reb桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                              胜率=("r_bh", lambda s: (s > 0).mean()), 差票率=("bad", "mean"))
    t["胜率"] = (t["胜率"] * 100).round(0); t["差票率"] = (t["差票率"] * 100).round(0)
    t["板留均"] = (t["板留均"] * 100).round(2)
    print(t.to_string())

    print("\n== ③ pos_low 边界带 0.5~0.7(易V↔U漂移) vs 典型U(<0.5) ==")
    for lab, m in (("pos_low<0.5(典型U)", U["pos_low"] < 0.5),
                   ("0.5<=pos_low<=0.7(边界带)", (U["pos_low"] >= 0.5) & (U["pos_low"] <= 0.7))):
        s = U[m]
        if len(s):
            print(f"  {lab}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f}% "
                  f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}%")

    print("\n== ④ 对照: V末反组(000892 7-29所在) ==")
    V = tg[tg["base"] == "V"]
    print(f"  V末反: n={len(V)} 板留 {V['r_bh'].mean() * 100:+.2f}% 胜率 "
          f"{(V['r_bh'] > 0).mean() * 100:.0f}% 差票 {V['bad'].mean() * 100:.0f}%")

    print("\n== ⑤ 000892 8-04 在U组里的同型票(弹>16%且距顶>-12%) ==")
    s = U[(U["reb"] > 0.16) & (U["pull"] > -0.12)]
    print(f"  n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f}% 胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% "
          f"差票 {s['bad'].mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
