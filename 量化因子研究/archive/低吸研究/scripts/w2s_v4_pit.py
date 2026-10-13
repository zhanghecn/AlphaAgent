# -*- coding: utf-8 -*-
"""主人统一坑模型验证(2026-08-29): U/V/横盘/中位浅调 = 同一个坑, 参数(深度×宽度)不同.

检验: ①深度×宽度 地形图(板留)是否连续平滑 ②同一(深,宽)格子里不同离散地基标签是否等价
(等价→分类冗余,主人统一观成立; 不等价→边界有信息) ③控制深宽后 pos_low(U/V分界)剩余区分力.
七分类的连续本质: 深度=low_dd(距顶) 宽度=gap(断板天数) 位置=pull/reb/pos_low.
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
DD_BINS = [-99, -0.25, -0.15, -0.08, 0.01]
DD_LABS = ["超深<-25%", "深-25~-15", "中-15~-8", "浅>-8%"]
GP_BINS = [1, 6, 11, 16, 99]
GP_LABS = ["窄2-5天", "中6-10", "宽11-15", "很宽16+"]


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
        # 坑形态池: 排除HIGH(已出坑) 看FLAT/U/V/MID/LB; DN=坑底进度条一端也放入对照
        pit = tg[tg["base"].isin(["FLAT", "U", "V", "MID", "LB", "DN"])].copy()
        pit["深"] = pd.cut(pit["low_dd"], DD_BINS, labels=DD_LABS)
        pit["宽"] = pd.cut(pit["gap"], GP_BINS, labels=GP_LABS)

        print("=" * 108)
        print(f"== {name} · 坑模型: 深度×宽度 地形图 (n/板留%; 池=FLAT+U+V+MID+LB+DN) ==")
        for dd in DD_LABS:
            parts = []
            for gp in GP_LABS:
                s = pit[(pit["深"] == dd) & (pit["宽"] == gp)]
                parts.append(f"{len(s)}笔/{s['r_bh'].mean() * 100:+.2f}" if len(s) else "—")
            print(f"  {dd:10s}: " + " | ".join(f"{gp} {p}" for gp, p in zip(GP_LABS, parts)))

        print("\n  同一(深,宽)格子内 离散标签是否等价 (n>=3的标签并排):")
        for dd in DD_LABS:
            for gp in GP_LABS:
                cell = pit[(pit["深"] == dd) & (pit["宽"] == gp)]
                if len(cell) < 10:
                    continue
                labs = []
                for b, s in cell.groupby("base"):
                    if len(s) >= 3:
                        labs.append(f"{BASE_CN[b]} {len(s)}/{s['r_bh'].mean() * 100:+.2f}")
                if len(labs) >= 2:
                    print(f"    {dd}×{gp}: " + " | ".join(labs))

        print("\n  控制深宽后 当前位置(pull分桶)的区分力 (全池):")
        pit["位"] = pd.cut(pit["pull"], [-99, -0.20, -0.12, -0.06, -0.04],
                           labels=["坑底-20以下", "坑壁-20~-12", "半坡-12~-6", "坑口-6~-4"])
        for wz in ("坑底-20以下", "坑壁-20~-12", "半坡-12~-6", "坑口-6~-4"):
            s = pit[pit["位"] == wz]
            if len(s):
                print(f"    {wz}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} "
                      f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}%")

        print("\n  控制深宽后 pos_low(U/V分界) 剩余区分力 (深+超深×弹回>=6%的子池):")
        sub = pit[(pit["low_dd"] <= -0.12) & (pit["reb"] >= 0.06)]
        for lab, m in (("低点前段(pos_low<0.4)", sub["pos_low"] < 0.4),
                       ("低点中段(0.4~0.6)", (sub["pos_low"] >= 0.4) & (sub["pos_low"] < 0.6)),
                       ("低点后段(>0.6)", sub["pos_low"] >= 0.6)):
            s = sub[m]
            if len(s):
                print(f"    {lab}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} "
                      f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
