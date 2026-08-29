# -*- coding: utf-8 -*-
"""主人坑模型核心猜想验证(2026-08-29): 四组(2板阴/阳, 4+阴/阳) 深度×宽度 地形对比.

主人猜想:
  H1 2板跟宽度有关: 太宽(地基过长)不利创新高 → gap16+ 格普遍差
  H2 2板深度有范围: 超深(<-25%)不好, 中深(-25~-8%)好
  H3 2板阴阳地形不同
  H4 4+跟深度有关: 深度是主变量(深浅间差异 > 宽度间差异)
  H5 4+浅深蓄力长: 浅坑×宽 = 好(蓄力充分)
  H6 4+太深无用: 超深坑宽度不起作用(获利盘出清)
因变量: 板留% + 破顶率%(买入后20日内收盘>上波顶, 度量"继续创新高"; 研究度量非条件).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

DD_LABS = ["浅-8~-4%", "中-15~-8", "深-25~-15", "超深<-25%"]
GP_LABS = ["窄2-5", "中6-10", "宽11-15", "很宽16+"]


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

    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    for tag, name in (("c4a", "2板阴"), ("c4b", "2板阳"), ("c4c", "4+阴"), ("c4d", "4+阳")):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        pit = tg[tg["base"] != "HIGH"].copy()
        # 未来20日收盘破上波顶(研究度量)
        brk_f = []
        for r in pit.itertuples():
            sid, i = int(r.sid), p2i[int(r.sid)][int(r.pos)]
            ph = r.prev_close / (1 + r.pull)
            fut = cl_by[sid][i + 1:i + 21]
            brk_f.append(bool((fut > ph).any()) if len(fut) else np.nan)
        pit["破顶"] = brk_f
        pit["dd"] = pd.cut(pit["low_dd"], [-0.99, -0.25, -0.15, -0.08, -0.04], labels=DD_LABS)
        pit["ww"] = pd.cut(pit["gap"], [1, 6, 11, 16, 99], labels=GP_LABS)

        print("=" * 110)
        print(f"== {name} · 深度×宽度 (n / 板留% / 20日破顶率%) ==")
        for dd in DD_LABS:
            parts = []
            for ww in GP_LABS:
                s = pit[(pit["dd"] == dd) & (pit["ww"] == ww)]
                parts.append(f"{len(s)}/{s['r_bh'].mean() * 100:+.2f}/{s['破顶'].mean() * 100:.0f}"
                             if len(s) and s["破顶"].notna().any() else "—")
            print(f"  {dd:10s}: " + " | ".join(parts))

        # 主命题: 边际效应(池内)
        print(f"  [边际] 按宽度: " + " | ".join(
            f"{ww} {len(s)}笔/{s['r_bh'].mean() * 100:+.2f}/破{s['破顶'].mean() * 100:.0f}%"
            for ww in GP_LABS if len(s := pit[pit["ww"] == ww])))
        print(f"  [边际] 按深度: " + " | ".join(
            f"{dd} {len(s)}笔/{s['r_bh'].mean() * 100:+.2f}/破{s['破顶'].mean() * 100:.0f}%"
            for dd in DD_LABS if len(s := pit[pit["dd"] == dd])))


if __name__ == "__main__":
    main()
