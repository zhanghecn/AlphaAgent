# -*- coding: utf-8 -*-
"""4+组门槛 4→5 对照(主人提问 2026-08-29): 按 V4 定稿口径重跑 5+ 全套.

背景: 妖股阶梯(w2s_v4_board5.py)曾测 ≥4+0.29→≥5+1.09→≥6+2.41(阴), 但未按白名单口径展开.
本脚本: ①第一层(5+阴/阳全量 vs 4+) ②地基矩阵 ③夹层(孤立板/2板小波穿插)白名单层对照
④恰5板vs5板+内部拆解(记忆: 恰5是坑-0.84/恰6峰值).
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
    print(f"  {label}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} 中位 "
          f"{s['r_bh'].median() * 100:+.2f} 胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% "
          f"差票 {s['bad'].mean() * 100:.0f}% 连板 {(s['res'] == '连板').mean() * 100:.0f}% | {ys}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    tgs = {}
    for tag, mx, yin, floor in (("c4c", 4, True, -0.08), ("c4d", 4, False, -0.03),
                                ("c5c", 5, True, -0.08), ("c5d", 5, False, -0.03)):
        p = bars["p_yin"] if yin else bars["p_yang"]
        bars[tag] = ((bars["mx20"] >= mx) & p & (bars["p_chg"] > floor)
                     & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    for tag in ("c4c", "c4d", "c5c", "c5d"):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        tgs[tag] = tg

    print("=" * 104)
    print("== ① 第一层: 4+ vs 5+ 全量 ==")
    for tag, lab in (("c4c", "4+阴"), ("c5c", "5+阴"), ("c4d", "4+阳"), ("c5d", "5+阳")):
        stat(tgs[tag], lab)

    print("\n== ② 地基矩阵: 5+阴 / 5+阳 (n, 板留, 差票%) ==")
    for tag in ("c5c", "c5d"):
        tg = tgs[tag]
        t = tg.groupby("base").agg(n=("r_bh", "size"), 板留=("r_bh", "mean"),
                                   差票=("bad", "mean"))
        t["差票"] = (t["差票"] * 100).round(0)
        t["板留"] = (t["板留"] * 100).round(2)
        t = t.reindex(["HIGH", "FLAT", "U", "V", "MID", "LB", "DN"]).dropna()
        print(f"-- {tag} --")
        print(" | ".join(f"{BASE_CN[b]} {int(r['n'])}笔/{r['板留']:+.2f}/{r['差票']:.0f}%"
                         for b, r in t.iterrows()))

    print("\n== ③ 白名单夹层层: 4+ vs 5+ ==")
    for ct, cy, lab in (("c4c", "c5c", "阴×孤立板穿插"), ("c4d", "c5d", "阳×2板小波穿插")):
        for tag, tl in ((ct, "4+"), (cy, "5+")):
            tg = tgs[tag]
            nm = tg["n_lim_mid"]
            if "阴" in lab:
                s = tg[(tg["seg_h"] >= 4) & nm.between(1, 2)]
            else:
                s = tg[tg["seg_h"] == 2]
            stat(s, f"{tl}{lab}")

    print("\n== ④ 恰5板 vs ≥6 (5+内部拆解) ==")
    for tag, lab in (("c5c", "5+阴"), ("c5d", "5+阳")):
        tg = tgs[tag]
        # mx20 恰好=5: 窗口内最大连板=5; ≥6: mx20>=6
        stat(tg[tg["mx20"] == 5], f"{lab}·恰5板(mx20=5)")
        stat(tg[tg["mx20"] >= 6], f"{lab}·≥6板")

    print("\n== ⑤ 月度密度: 5+阴/5+阳 笔/月 ==")
    for tag in ("c5c", "c5d"):
        s = tgs[tag]
        n_m = s.groupby(s["trade_date"].dt.strftime("%Y-%m")).size()
        print(f"  {tag}: 总{n_m.sum()}笔 / {len(n_m)}个月, 月均 {n_m.mean():.1f}, "
              f"最多 {n_m.max()}笔({n_m.idxmax()})")


if __name__ == "__main__":
    main()
