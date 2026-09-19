# -*- coding: utf-8 -*-
"""高位接力 · 地基/均线/反包 候选格验证（第二十遍）。

对第十九遍扫出的候选格做严格验证:
- C1 二接三阴 × 地基假阴真阳（阴线但涨跌幅>=0）
- C2 二接三阳 × 地基涨跌>=4% × 断1~3天反包
- C3 三接四阳 × 前板高度>=2 × 距MA10<5%（二波接力, 地基没暴涨）
- C4 B1加料: B1 × 60日内无板
- C5 三接四阴 × 大阴<=-5% × 距MA10<-10%（深跌远离均线）

每个候选: 总表+分年 / 去最好3笔 / 边界晃动 / 与四方案点重叠 / 首刻过滤叠加。
另: 断1天反包 四组各自细查（是否与地基大小/阴阳组合后可用）。

容器内跑: python /tmp/research/relay_foundation2.py
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, "/tmp/research")
import relay_research as rr
import relay_foundation as rf

OUT = "/tmp/research/relay_out"
YEARS = ["2023", "2024", "2025", "2026"]


def year_str(sub):
    out = []
    for y in YEARS:
        sy = sub[sub["年"] == y]
        out.append(f"{sy['持有到断板%'].mean():+.2f}/{len(sy)}" if len(sy) else "0笔")
    return " | ".join(out)


def all_pos(sub):
    ys = [sub[sub["年"] == y] for y in YEARS]
    return all(len(s) > 0 and s["持有到断板%"].mean() > 0 for s in ys)


def one(lines, fin, name, mask):
    sub = fin[mask]
    lines.append(f"\n### {name}\n")
    if len(sub) == 0:
        lines.append("0笔\n")
        return sub
    win = (sub["次日收%"] > 0).mean() * 100
    hold = sub["持有到断板%"].mean()
    e3 = sub["E3%"].mean() if "E3%" in sub.columns else np.nan
    lines.append(f"- 合计：{len(sub)}笔 胜率{win:.0f}% 持有{hold:+.2f}"
                 + (f" E3卖出{e3:+.2f}" if e3 == e3 else ""))
    lines.append(f"- 分年（持有/笔数）：{year_str(sub)}"
                 + ("　✅分年全正" if all_pos(sub) else "　❌有负年"))
    # 去最好3笔
    if len(sub) >= 8:
        tri = sub.sort_values("持有到断板%", ascending=False).iloc[3:]
        ys = [tri[tri["年"] == y]["持有到断板%"].mean() for y in YEARS]
        lines.append(f"- 去最好3笔后：{len(tri)}笔 持有{tri['持有到断板%'].mean():+.2f}，"
                     f"分年 " + " ".join(f"{y:+.2f}" if y == y else "无" for y in ys))
    # 与方案点重叠
    ov = sub[sub["方案点"] != "—"]
    lines.append(f"- 与四方案点重叠：{len(ov)}/{len(sub)} 笔"
                 + (f"（{dict(ov['方案点'].value_counts())}）" if len(ov) else ""))
    # 首刻叠加
    if "首刻" in sub.columns:
        sk = sub[sub["首刻"] == "首刻"]
        if len(sk):
            lines.append(f"- 叠加首刻过滤：{len(sk)}笔 胜率{(sk['次日收%'] > 0).mean() * 100:.0f}% "
                         f"持有{sk['持有到断板%'].mean():+.2f}，分年 {year_str(sk)}")
    return sub


def wobble(lines, fin, title, variants):
    """variants = [(说明, mask), ...]"""
    lines.append(f"\n**{title} 晃动测试**\n")
    lines.append("| 变体 | 笔数 | 胜率 | 持有 | 分年 | 全正 |")
    lines.append("|---|---|---|---|---|---|")
    for name, m in variants:
        s = fin[m]
        if len(s) == 0:
            lines.append(f"| {name} | 0 | | | | |")
            continue
        lines.append(f"| {name} | {len(s)} | {(s['次日收%'] > 0).mean() * 100:.0f}% "
                     f"| {s['持有到断板%'].mean():+.2f} | {year_str(s)} | "
                     f"{'✅' if all_pos(s) else '❌'} |")
    lines.append("")


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    E, bars, end = rr.build_events(eng)
    E["年"] = E["年"].astype(str)
    E2 = rf.augment(E, bars)
    E2 = rf.tag_scheme(E2)
    fin = E2[~E2["未完"]].copy()

    # 首刻列(15m窗2024-08-15起)
    try:
        T = pd.read_csv(f"{OUT}/触板时间明细-全量.csv", dtype={"代码": str})
        mm = pd.to_datetime(T["触板时间"], format="%H:%M", errors="coerce")
        T["首刻"] = np.where(mm.isna(), "无数据",
                    np.where((mm.dt.hour * 60 + mm.dt.minute) <= 585, "首刻", "非首刻"))
        fin = fin.merge(T[["代码", "买入日", "首刻"]], on=["代码", "买入日"], how="left")
    except Exception as e:
        print("触板时间缺失:", e)
    # E3卖出列
    try:
        X = pd.read_csv(f"{OUT}/逐笔卖出规则.csv", dtype={"代码": str})
        e3col = [c for c in X.columns if "E3" in c]
        if e3col:
            fin = fin.merge(X[["代码", "买入日", e3col[0]]].rename(columns={e3col[0]: "E3%"}),
                            on=["代码", "买入日"], how="left")
    except Exception as e:
        print("卖出规则缺失:", e)

    g23y = fin["四组"] == "二接三阴"
    g22y = fin["四组"] == "二接三阳"
    g34y = fin["四组"] == "三接四阴"
    g34yang = fin["四组"] == "三接四阳"

    lines = [f"# 高位接力 · 地基/均线/反包 候选格验证（2026-09-19 第二十遍）", "",
             "候选来自 汇总/地基均线反包.md 的扫描，这里做：分年全正、去最好3笔、边界晃动、"
             "与四方案点重叠、首刻过滤叠加。", ""]

    # ---- C1 二接三阴 假阴真阳 ----
    c1 = g23y & (fin["地基涨跌%"] >= 0)
    one(lines, fin, "C1 二接三阴 × 地基阴线但涨跌幅≥0%（假阴真阳=高开低走收阴但没跌）", c1)
    wobble(lines, fin, "C1 边界（涨跌幅下限）", [
        ("≥-1%", g23y & (fin["地基涨跌%"] >= -1)),
        ("≥0%（原）", c1),
        ("≥1%", g23y & (fin["地基涨跌%"] >= 1)),
        ("≥2%", g23y & (fin["地基涨跌%"] >= 2)),
    ])
    # C1 × 断板反包
    one(lines, fin, "C1b C1 × 断1~15天反包", c1 & fin["反包结构"].isin(["断1天", "断2~3天", "断4~7天", "断8~15天"]))
    one(lines, fin, "C1c C1 × 60日内无板", c1 & (fin["反包结构"] == "60日内无板"))

    # ---- C2 二接三阳 大阳地基×快速反包 ----
    c2 = g22y & (fin["地基涨跌%"] >= 4) & fin["反包结构"].isin(["断1天", "断2~3天"])
    one(lines, fin, "C2 二接三阳 × 地基涨≥4% × 断1~3天反包", c2)
    wobble(lines, fin, "C2 地基涨幅边界", [
        ("≥3%×断1~3", g22y & (fin["地基涨跌%"] >= 3) & fin["反包结构"].isin(["断1天", "断2~3天"])),
        ("≥4%×断1~3（原）", c2),
        ("≥5%×断1~3", g22y & (fin["地基涨跌%"] >= 5) & fin["反包结构"].isin(["断1天", "断2~3天"])),
        ("≥4%×断1天", g22y & (fin["地基涨跌%"] >= 4) & (fin["反包结构"] == "断1天")),
        ("≥4%×断1~7", g22y & (fin["地基涨跌%"] >= 4) & fin["反包结构"].isin(["断1天", "断2~3天", "断4~7天"])),
    ])

    # ---- C3 三接四阳 二波接力 ----
    c3 = g34yang & (fin["前板高度"].fillna(0) >= 2) & (fin["距MA10%"] < 5)
    one(lines, fin, "C3 三接四阳 × 前板高度≥2（二波）× 地基距MA10<5%", c3)
    wobble(lines, fin, "C3 MA10距离边界", [
        ("<3%", g34yang & (fin["前板高度"].fillna(0) >= 2) & (fin["距MA10%"] < 3)),
        ("<5%（原）", c3),
        ("<7%", g34yang & (fin["前板高度"].fillna(0) >= 2) & (fin["距MA10%"] < 7)),
        ("前板≥2 不加MA", g34yang & (fin["前板高度"].fillna(0) >= 2)),
    ])
    one(lines, fin, "C3b 三接四阳 × 前板≥2 × 地基|涨跌|<4%", g34yang & (fin["前板高度"].fillna(0) >= 2) & (fin["地基涨跌%"].abs() < 4))

    # ---- C4 B1 × 60日内无板 ----
    b1m = fin["方案点"] == "B1"
    one(lines, fin, "C4 B1 × 60日内无板", b1m & (fin["反包结构"] == "60日内无板"))
    one(lines, fin, "C4对照 B1 × 有近期反包(断1~15天)", b1m & fin["反包结构"].isin(["断1天", "断2~3天", "断4~7天", "断8~15天"]))

    # ---- C5 三接四阴 深跌 ----
    c5 = g34y & (fin["地基涨跌%"] <= -5) & (fin["距MA10%"] < -10)
    one(lines, fin, "C5 三接四阴 × 地基跌≤-5% × 距MA10<-10%（深跌远离均线）", c5)

    # ---- 断1天反包 四组细查 ----
    lines.append("\n## 断1天反包 四组细查（池级最好格, 但分年不全正, 看与什么组合能修）\n")
    d1 = fin["反包结构"] == "断1天"
    for gname, gm in [("二接三阴", g23y), ("二接三阳", g22y), ("三接四阴", g34y), ("三接四阳", g34yang)]:
        sub = fin[gm & d1]
        lines.append(f"**{gname} × 断1天**：{len(sub)}笔 胜率{(sub['次日收%'] > 0).mean() * 100:.0f}% "
                     f"持有{sub['持有到断板%'].mean():+.2f}，分年 {year_str(sub)}")
        for extra_name, em in [("×地基涨≥0", fin["地基涨跌%"] >= 0), ("×地基涨<0", fin["地基涨跌%"] < 0),
                               ("×MA10下", fin["MA10位置"] == "下"), ("×前板≥2", fin["前板高度"].fillna(0) >= 2)]:
            s2 = sub[em.loc[sub.index]]
            if len(s2):
                lines.append(f"  - {extra_name}: {len(s2)}笔 {(s2['次日收%'] > 0).mean() * 100:.0f}% "
                             f"{s2['持有到断板%'].mean():+.2f}，分年 {year_str(s2)}")
        lines.append("")

    text = "\n".join(lines)
    with open(f"{OUT}/汇总/地基均线反包-验证.md", "w", encoding="utf-8") as fp:
        fp.write(text)
    print(text)
    print(f"\n已写 {OUT}/汇总/地基均线反包-验证.md")


if __name__ == "__main__":
    main()
