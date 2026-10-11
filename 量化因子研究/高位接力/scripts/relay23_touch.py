# -*- coding: utf-8 -*-
"""P0+P3 触板时间维度(宿主机: uv run python relay23_touch.py)。

P0: 触板时间明细(2024+,2408行)合并进事件表, 对齐率报告。
P3: 触板时间判别力扫描(只用合法特征):
  a) 今日触板时间(买入瞬间即知): 早盘≤10:30 / 午盘 / 尾盘≥14:00
  b) 历史板封板形态(T-1收盘即知): 末板的触板早晚/开口段数/最深回落
用途1(质量): 尾盘触板若毒 → 口诀加时间腿; 用途2(交易数): 肥格收编候选。
限制: 仅2024-01起覆盖, 结论只管强市段, 不做跨时代外推。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "—"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):4d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f} 亏:{(e3 <= -10).sum():2d} 封住:{g['封住'].mean() * 100:2.0f}%")


def yearly(g: pd.DataFrame) -> str:
    return " ".join(f"{y}:{len(gg)}笔{gg['E3%'].mean():+.1f}"
                    for y, gg in g.groupby("年"))


def touch_bucket(t: str) -> str:
    """触板时间(15分钟粒度标签如'09:45') → 时段桶。"""
    if not isinstance(t, str) or ":" not in t:
        return "无"
    hh, mm = int(t[:2]), int(t[3:5])
    v = hh * 60 + mm
    if v <= 10 * 60 + 30:
        return "早盘≤10:30"
    if v < 14 * 60:
        return "午盘"
    return "尾盘≥14:00"


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    T = pd.read_csv(f"{ROOT}/触板时间明细-全量.csv", dtype={"代码": str})
    T.columns = [c.strip("﻿") for c in T.columns]
    print(f"事件表 {len(E)} 笔; 触板明细 {len(T)} 行 "
          f"({T['买入日'].min()[:10]}~{T['买入日'].max()[:10]})")

    # P0: 合并(代码+买入日)
    M = E.merge(T[["代码", "买入日", "触板时间", "封板时间", "开口段数", "最深回落%",
                   "b1触板时间", "b1封板时间", "b1开口段数",
                   "b2触板时间", "b2封板时间", "b2开口段数",
                   "b3触板时间", "b3封板时间", "b3开口段数"]],
                on=["代码", "买入日"], how="left")
    hit = M["触板时间"].notna()
    print(f"合并对齐: {int(hit.sum())}/{len(M)} ({hit.mean() * 100:.0f}%)")
    e24 = M[M["年"] >= 2024]
    print(f"2024+段事件 {len(e24)} 笔, 对齐 {int(e24['触板时间'].notna().sum())} "
          f"({e24['触板时间'].notna().mean() * 100:.0f}%)")
    M.to_pickle("/tmp/relay23_touch.pkl")

    # 只对齐到的子集做判别力分析(2024+)
    S = M[M["触板时间"].notna()].copy()
    S["触板段"] = S["触板时间"].map(touch_bucket)
    S["末板触板段"] = S.apply(lambda r: (r["b2触板时间"] if r["N"] == 2 else r["b3触板时间"]), axis=1)
    S["末板触段"] = S["末板触板段"].map(touch_bucket)
    S["末板开口段数"] = S.apply(lambda r: (r["b2开口段数"] if r["N"] == 2 else r["b3开口段数"]), axis=1)

    print("\n" + "=" * 24, "P3a 今日触板时间(买入瞬间已知)", "=" * 24)
    print("—— 全池(2024+) × 触板段 ——")
    for lab in ["早盘≤10:30", "午盘", "尾盘≥14:00"]:
        g = S[S["触板段"] == lab]
        print(f"  {lab}: {stat(g)}")
        print(f"      分年: {yearly(g)}")
    print("\n—— 触板段 × 口诀命中 ——")
    for lab in ["早盘≤10:30", "午盘", "尾盘≥14:00"]:
        gh = S[(S["触板段"] == lab) & (S["口诀"] != "—")]
        gm = S[(S["触板段"] == lab) & (S["口诀"] == "—")]
        print(f"  {lab}: 命中 {stat(gh)} | 漏网 {stat(gm)}")
    print("\n—— 分口诀 × 触板段(命中票, 找尾盘毒的口诀) ——")
    for no in ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3", "K5"):
        g = S[S["口诀"] == no]
        if len(g) < 8:
            continue
        parts = []
        for lab in ["早盘≤10:30", "午盘", "尾盘≥14:00"]:
            gg = g[g["触板段"] == lab]
            if len(gg):
                e3 = gg["E3%"].dropna()
                parts.append(f"{lab[:2]}:{len(gg)}笔{e3.mean():+.1f}/{(e3 > 0).mean() * 100:.0f}%")
        print(f"  {no}: " + " | ".join(parts))

    print("\n" + "=" * 24, "P3b 历史末板封板形态(T-1已知)", "=" * 24)
    print("—— 末板触板时段(昨天它是几点触的板) ——")
    for lab in ["早盘≤10:30", "午盘", "尾盘≥14:00"]:
        g = S[S["末板触段"] == lab]
        print(f"  末板{lab}: {stat(g)}")
    print("\n—— 末板开口段数(昨天炸过几次) ——")
    S["开口桶"] = pd.cut(S["末板开口段数"].astype(float), [0, 1.5, 3.5, 99],
                         labels=["0~1次(硬封)", "2~3次", "4+(烂板)"], right=False)
    for lab in ["0~1次(硬封)", "2~3次", "4+(烂板)"]:
        g = S[S["开口桶"] == lab]
        print(f"  {lab}: {stat(g)}")
    print("\n—— 末板触段 × 口诀命中 ——")
    for lab in ["早盘≤10:30", "午盘", "尾盘≥14:00"]:
        gh = S[(S["末板触段"] == lab) & (S["口诀"] != "—")]
        gm = S[(S["末板触段"] == lab) & (S["口诀"] == "—")]
        print(f"  {lab}: 命中 {stat(gh)} | 漏网 {stat(gm)}")


main()
