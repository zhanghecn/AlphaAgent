# -*- coding: utf-8 -*-
"""一接二 · 新判别器体检: 大肉大亏对撞发现的四条候选腿, 全部过严格检验。

候选(对撞分离度排序):
  L1 首板开7+(高开秒板): 肉8/亏2 比4.0, 52笔 +6.28
  L2 市值120~300亿:      肉11/亏2 比5.5, 68笔 +7.19  ←市值=当前快照(近似)
  L3 底盘4+板(妖股再起): 肉1/亏4 比0.2, 39笔 +2.58(毒)
  L4 市值30~60亿:        肉7/亏16 比0.4, 144笔 +2.24(毒)
检验: 主窗/OOS 分年 + 边界晃动 + G1±腿 增量 + 骑线交互。
"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]].copy()
    if "首开一字" in d.columns:
        d = d[~d["首开一字"]]
    d["市值亿"] = d["市值亿"] / 1e8
    return d


def g1s1(d):
    return d[(d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")
             | (d["地基阴阳"] == "阳") & (d["前10日涨幅%"] < -3)
             & d["买入开盘%"].between(7.5, 8.5, inclusive="left")].copy()


def stat(sub, name):
    if not len(sub):
        print(f"  {name}: 0笔")
        return
    main = sub[sub["段"] == "主窗"]
    oos = sub[sub["段"] == "样本外"]
    for tag, s in [("主窗", main), ("OOS", oos)]:
        if len(s):
            yr = s.groupby("年")["E3%"].agg(["count", "mean"])
            ok = "✅" if all(yr["mean"] > 0) and len(yr) >= (4 if tag == "主窗" else 2) else "❌"
            ys = "/".join(f"{y[2:]}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows())
            print(f"  {name} {tag}: {len(s)}笔 胜{(s['E3%'] > 0).mean() * 100:.0f}% "
                  f"均{s['E3%'].mean():+.2f} {ok} ({ys})")


def main():
    d = load()
    G = g1s1(d)
    print("=== L1 首板开档(高开秒板) · 边界晃动 ===")
    for a in [5, 6, 7, 8]:
        stat(G[G["首板开盘%"] >= a], f"首板开>={a}")
    for a in [3, 5, 7]:
        stat(G[G["首板开盘%"] < a], f"首板开<{a}(对照)")

    print("\n=== L2 市值档 · 边界晃动 ===")
    for lo, hi in [(100, 300), (120, 300), (120, 400), (100, 400), (80, 300)]:
        stat(G[G["市值亿"].between(lo, hi)], f"市值{lo}~{hi}亿")
    for lo, hi in [(20, 60), (30, 60), (30, 120)]:
        stat(G[G["市值亿"].between(lo, hi)], f"市值{lo}~{hi}亿(毒?)")
    stat(G[G["市值亿"] < 30], "市值<30亿")

    print("\n=== L3 底盘连板高度 ===")
    for h in [3, 4, 5]:
        stat(G[G["60日最大连板"] >= h], f"60日最大连板>={h}")
    stat(G[G["60日最大连板"].between(2, 3)], "连板2~3(对照)")
    stat(G[G["60日最大连板"] <= 1], "连板<=1(对照)")

    print("\n=== 组合: G1 ± 新腿 的增量(主窗/OOS) ===")
    g1 = G[(G["地基阴阳"] == "阴") & G["买入开盘%"].between(7.5, 9.5, inclusive="left")]
    stat(g1, "G1裸")
    stat(g1[g1["首板开盘%"] >= 7], "G1×首板开7+")
    stat(g1[g1["市值亿"].between(120, 300)], "G1×市值120~300")
    stat(g1[g1["市值亿"].between(30, 60)], "G1×市值30~60(毒?)")
    stat(g1[g1["60日最大连板"] >= 4], "G1×连板4+(毒?)")
    stat(g1[g1["60日最大连板"] <= 3], "G1×连板<=3")
    stat(g1[(g1["首板开盘%"] >= 7) | g1["市值亿"].between(120, 300)], "G1×(秒板∪中盘)并集")
    stat(g1[~((g1["首板开盘%"] >= 7) | g1["市值亿"].between(120, 300))], "G1减并集")

    print("\n=== 剔毒版: G1 − (30~60亿 ∪ 连板4+ ∪ 骑线) ===")
    poison = (g1["市值亿"].between(30, 60)) | (g1["60日最大连板"] >= 4) | g1["地基距MA20%"].between(0, 5)
    stat(g1[~poison], "G1剔三毒")
    stat(g1[poison], "被剔的毒票(对照)")

    print("\n=== 样本外单独看四条腿 ===")
    oos = G[G["段"] == "样本外"]
    stat(oos[oos["首板开盘%"] >= 7], "OOS 首板开7+")
    stat(oos[oos["市值亿"].between(120, 300)], "OOS 市值120~300")
    stat(oos[oos["市值亿"].between(30, 60)], "OOS 市值30~60")
    stat(oos[oos["60日最大连板"] >= 4], "OOS 连板4+")


if __name__ == "__main__":
    main()
