# -*- coding: utf-8 -*-
"""连板延续关键格分年稳定性: 趋势×缩量/缩量×上午 vs 各组基准, 按年切."""
import pandas as pd

CSV = "/root/project/ai/vnpy/量化因子研究/低吸研究/N型补涨打板/连板延续明细.csv"
GNAME = {"yin2": "2板阴", "yang2": "2板阳", "yin4": "4+阴", "yang4": "4+阳"}
EARLY = {"早09:30~10:30", "中10:30~11:30"}

df = pd.read_csv(CSV, dtype={"vt_symbol": str})
df["year"] = pd.to_datetime(df["n1_date"]).dt.year
df["a1"] = df["h"] >= 2
df["seal"] = df["h"] >= 1

print(f"{'组':<5} {'画像':<12} {'年':<6} {'n':>4} {'封板%':>6} {'D+1板%':>7}")
for gk, name in GNAME.items():
    sub = df[df["g4"] == gk].copy()
    strong = sub["bias10"] == ">5"
    pics = {
        "强趋势×缩量": sub[strong & (sub["vr_d0"] < 0.8)],
        "强趋势×常量": sub[strong & (sub["vr_d0"] >= 0.8)],
        "趋势下方": sub[~strong],
    }
    if sub["tseg"].notna().any():
        pics["缩量×上午"] = sub[(sub["vr_d0"] < 0.8) & sub["tseg"].isin(EARLY)]
    for tag, x in pics.items():
        for yr, xx in x.groupby("year"):
            print(f"{name:<5} {tag:<12} {yr:<6} {len(xx):>4} "
                  f"{xx['seal'].mean() * 100:>6.1f} {xx['a1'].mean() * 100:>7.1f}")
    # 全组基准分年
    for yr, xx in sub.groupby("year"):
        print(f"{name:<5} {'(全组基准)':<12} {yr:<6} {len(xx):>4} "
              f"{xx['seal'].mean() * 100:>6.1f} {xx['a1'].mean() * 100:>7.1f}")
    print()
