# -*- coding: utf-8 -*-
"""一接二 · 第4步候选格挖掘: 参数化扫描 + 边界晃动 + 格间重叠 + 候选定稿。

读全量明细.csv(容器内), 主窗 E3 口径。产出 汇总/候选格.md。

候选机制主线(第3步观察): 「挖坑首板 + 竞价强开确认」——
坑深代理 = 阴地基/低位/距MA20深下/前20日跌/前波连板(有人做过), 确认 = 今开7~9.5。
毒格主线: 贴顶全维 / 今开顶格 / 首板开3~7族。
"""
import itertools

import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[(E["段"] == "主窗") & (~E["未完"])].copy()
    return d


def score(sub):
    if len(sub) == 0:
        return None
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    allpos = all(r["mean"] > 0 for _, r in yr.iterrows()) and len(yr) >= 3
    return {
        "n": len(sub), "wr": (sub["E3%"] > 0).mean() * 100, "e3": sub["E3%"].mean(),
        "med": sub["E3%"].median(), "worst": sub["E3%"].min(),
        "allpos": allpos,
        "yr": " / ".join(f"{y}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows()),
    }


def fmt(s):
    return f"{s['n']}笔 胜{s['wr']:.0f}% 均{s['e3']:+.2f} 中位{s['med']:+.2f} 最差{s['worst']:+.1f} " \
           f"{'✅全正' if s['allpos'] else '❌'} ｜ {s['yr']}"


def wobble(d, name, base_mask, wobbles, lines):
    """边界晃动: base_mask=None 的项在 wobbles 里给出不同边界的 mask 函数。"""
    lines.append(f"\n#### {name}")
    for wname, mask in wobbles:
        s = score(d[mask(d)])
        if s:
            lines.append(f"- {wname}: {fmt(s)}")


def main():
    d = load()
    open_ = d["买入开盘%"]
    lines = ["# 一接二 · 第4步候选格(主窗 E3 口径)", ""]

    # ── 候选1: 阴地基 × 今开档(边界晃动) ──
    wobble(d, "候选1 阴地基 × 今开", None, [
        (f"阴×今开{a}~{b}", lambda dd, a=a, b=b: (dd["地基阴阳"] == "阴") & (dd["买入开盘%"] >= a) & (dd["买入开盘%"] < b))
        for a, b in [(6, 9.5), (6.5, 9.5), (7, 9.5), (7.5, 9.5), (7, 9.2), (6, 8.5), (8.5, 9.5)]
    ], lines)
    # 阳对照
    wobble(d, "候选1对照 阳地基 × 今开", None, [
        (f"阳×今开{a}~{b}", lambda dd, a=a, b=b: (dd["地基阴阳"] == "阳") & (dd["买入开盘%"] >= a) & (dd["买入开盘%"] < b))
        for a, b in [(7, 9.5), (8.5, 9.5)]
    ], lines)

    # ── 候选2: 位置(坑深) × 今开7~9.5 ──
    wobble(d, "候选2 位置坑深 × 今开7~9.5", None, [
        (f"距60高<{c} × 今开7~9.5", lambda dd, c=c: (dd["地基距60高%"] < c) & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5))
        for c in [-5, -10, -15, -20]
    ] + [
        (f"跌透或低位(<-10) × 今开7~9.5", lambda dd: (dd["位置五档"].isin(["跌透", "低位"])) & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5)),
        ("跌透 × 今开4~9.5", lambda dd: (dd["位置五档"] == "跌透") & (dd["买入开盘%"] >= 4) & (dd["买入开盘%"] < 9.5)),
    ], lines)

    # ── 候选3: 地基距MA20(坑深代理2) × 今开 ──
    wobble(d, "候选3 地基距MA20 × 今开7~9.5", None, [
        (f"距MA20<{c} × 今开7~9.5", lambda dd, c=c: (dd["地基距MA20%"] < c) & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5))
        for c in [0, -5, -10]
    ], lines)

    # ── 候选4: 前20日跌幅 × 今开 ──
    wobble(d, "候选4 前20日涨幅 × 今开7~9.5", None, [
        (f"前20日<{c} × 今开7~9.5", lambda dd, c=c: (dd["前20日涨幅%"] < c) & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5))
        for c in [0, -5, 5]
    ], lines)

    # ── 候选5: 底盘 × 今开 ──
    wobble(d, "候选5 底盘纯度 × 今开7~9.5", None, [
        ("前波连板 × 今开7~9.5", lambda dd: (dd["底盘纯度"] == "前波连板") & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5)),
        ("60日最大连板≥2 × 今开7~9.5", lambda dd: (dd["60日最大连板"] >= 2) & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5)),
        ("纯底盘 × 今开7~9.5", lambda dd: (dd["底盘纯度"] == "纯底盘") & (dd["买入开盘%"] >= 7) & (dd["买入开盘%"] < 9.5)),
    ], lines)

    # ── 候选6: 纯静态格(无今开, 前一晚全知道) ──
    wobble(d, "候选6 纯静态格(无今开)", None, [
        ("深下MA20(<-10) × 大阴地基(<-5)", lambda dd: (dd["地基距MA20%"] < -10) & (dd["地基涨跌%"] < -5)),
        ("阴 × 跌透/低位", lambda dd: (dd["地基阴阳"] == "阴") & (dd["位置五档"].isin(["跌透", "低位"]))),
        ("阴 × 前20日<0", lambda dd: (dd["地基阴阳"] == "阴") & (dd["前20日涨幅%"] < 0)),
    ], lines)

    # ── 组合格: 阴 × 低位 × 今开7~9.5 及主候选交集 ──
    m7 = (d["买入开盘%"] >= 7) & (d["买入开盘%"] < 9.5)
    yin = d["地基阴阳"] == "阴"
    low = d["位置五档"].isin(["跌透", "低位"])
    wave = d["底盘纯度"] == "前波连板"
    ma20deep = d["地基距MA20%"] < -5
    pre20down = d["前20日涨幅%"] < 0
    lines.append("\n#### 组合交集")
    combos = [
        ("阴×今开7~9.5(基准)", yin & m7),
        ("阴×低位×今开7~9.5", yin & low & m7),
        ("阴×前波连板×今开7~9.5", yin & wave & m7),
        ("阴×距MA20<-5×今开7~9.5", yin & ma20deep & m7),
        ("阴×前20跌×今开7~9.5", yin & pre20down & m7),
        ("低位×前波连板×今开7~9.5", low & wave & m7),
        ("阴×低位×前波连板×今开7~9.5", yin & low & wave & m7),
        ("阴或距MA20<-5 × 今开7~9.5(并集坑深)", (yin | ma20deep) & m7),
    ]
    for name, m in combos:
        s = score(d[m])
        if s:
            lines.append(f"- {name}: {fmt(s)}")

    # ── 格间重叠: 主候选两两交集占各自比例 ──
    lines.append("\n#### 格间重叠(交集笔数 / 占小格%)")
    named = [("阴×7~9.5", yin & m7), ("低位×7~9.5", low & m7), ("前波连板×7~9.5", wave & m7),
             ("距MA20<-5×7~9.5", ma20deep & m7), ("前20跌×7~9.5", pre20down & m7)]
    lines.append("| 格A | 格B | 交集 | 占A% | 占B% |")
    lines.append("|---|---|---|---|---|")
    for (na, ma), (nb, mb) in itertools.combinations(named, 2):
        inter = (ma & mb).sum()
        lines.append(f"| {na} | {nb} | {int(inter)} | {inter / ma.sum() * 100:.0f}% | {inter / mb.sum() * 100:.0f}% |")

    # ── 毒格回避正式化 ──
    lines.append("\n#### 毒格回避候选(含分年)")
    poisons = [
        ("贴顶(地基距60高0~10%) 全部", d["位置五档"] == "贴顶"),
        ("今开顶格(≥9.5) 全部", open_ >= 9.5),
        ("首板破60高 × 今开顶格", d["首板破60高"] & (open_ >= 9.5)),
        ("T字 × 今开<4", (d["首板板型"] == "T字") & (open_ < 4)),
        ("首板一字 × 前10日5~10", (d["首板板型"] == "一字") & (d["前10日涨幅%"] >= 5) & (d["前10日涨幅%"] < 10)),
    ]
    for name, m in poisons:
        s = score(d[m])
        if s:
            lines.append(f"- {name}: {fmt(s)}")

    # ── 金档内阴阳×坑深的独立贡献分解 ──
    lines.append("\n#### 今开7~9.5 内: 阴阳 × 位置 分解")
    for yy in ["阴", "阳"]:
        for pp in ["跌透", "低位", "半山"]:
            s = score(d[(d["地基阴阳"] == yy) & (d["位置五档"] == pp) & m7])
            if s and s["n"] >= 5:
                lines.append(f"- {yy}×{pp}: {fmt(s)}")
    lines.append("\n#### 今开7~9.5 内: 阴阳 × 底盘 分解")
    for yy in ["阴", "阳"]:
        for pp in ["前波连板", "孤立板", "纯底盘"]:
            s = score(d[(d["地基阴阳"] == yy) & (d["底盘纯度"] == pp) & m7])
            if s and s["n"] >= 5:
                lines.append(f"- {yy}×{pp}: {fmt(s)}")
    lines.append("\n#### 今开7~9.5 内: 阴阳 × 前20日档 分解")
    for yy in ["阴", "阳"]:
        lo, hi = (-99, 0) if yy == "阴" else (0, 99)
        s = score(d[(d["地基阴阳"] == yy) & d["前20日涨幅%"].between(lo, hi) & m7])
        if s:
            lines.append(f"- {yy}×前20日{lo}~{hi}: {fmt(s)}")

    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/候选格.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
