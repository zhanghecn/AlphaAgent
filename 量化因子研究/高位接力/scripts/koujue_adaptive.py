# -*- coding: utf-8 -*-
"""通用性验证+适配性口诀提取(koujue_adaptive, 主人2026-10-11指令:
「验证这个脚本的通用性 是不是适配所有行情 提取出适配性口诀」)。

设计: 把锻造炉原封不动扔进两个行情时代独立挖口诀——
  W1=2020-01~2023-08(弱市时代, K系定型段) / W2=2023-09~2026-10(强市时代)
每段独立跑完整管线, 然后交叉回放: 本段挖出的格在他段还活不活。
三分类:
  ◆ 跨时代格(两段都过纪律)=适配性口诀——所有行情都能用的
  ▲ 时代专属(本段肥, 他段亏/死)——行情切换时要跟着换的
  ○ 他段无票(形态消失, 不亏也不出现)
现役13条同样过时代矩阵对照——现役里哪些本来就是跨时代的。
"""
import types

import numpy as np
import pandas as pd

_forge_src = open("量化因子研究/高位接力/scripts/koujue_forge.py", encoding="utf-8").read()
_forge_src = _forge_src.replace("\n\nmain()\n", "\n")   # 剥掉脚本级main()调用
forge_mod = types.ModuleType("koujue_forge")
exec(compile(_forge_src, "koujue_forge.py", "exec"), forge_mod.__dict__)

W1 = ("2020-01", "2023-08")
W2 = ("2023-09", None)


def era_mask(E, era):
    m = pd.Series(True, index=E.index)
    m &= E["月"] >= era[0]
    if era[1]:
        m &= E["月"] <= era[1]
    return m


def seg_stats(E, idx, era):
    """票集 idx 在某时代的成绩与「活着」判定(n≥5 胜≥50% 剔3>0)。"""
    m = era_mask(E, era)
    sub = E.loc[list(idx)]
    sub = sub[m.loc[sub.index]]
    v = sub["E3%"]
    n = len(v)
    if n == 0:
        return dict(n=0, alive=False, kind="○无票")
    t3 = v.drop(v.nlargest(3).index).mean() if n > 3 else v.mean()
    alive = n >= 5 and (v > 0).mean() >= 0.5 and t3 > 0
    kind = "◆跨时代" if alive else ("○无票" if n < 5 else "▲他段死")
    return dict(n=n, win=(v > 0).mean(), avg=v.mean(), t3=t3,
                alive=alive, kind=kind)


def rebuild_mask(E, t):
    """按格的条件定义(pool,legs,today,inc,exc)在全时段E上重建mask——
    交叉回放必须重执行条件(票集交集必然为空: 窗内挖的票只在本窗)。"""
    fm = forge_mod
    pool, legs, tr, inc, exc, _m0 = t
    m = pd.Series(E["四组"] == pool, index=E.index)
    for a, r in legs:
        c = E[fm.COLS[a]].astype(float)
        m &= (c >= r[0]) & (c < r[1])
    c = E["买入开盘%"].astype(float)
    m &= (c >= tr[0]) & (c < tr[1])

    def resolve(ax, nm):
        for ax3, lo3, hi3, nm3 in [(a, l, h, n) for a, axes in fm.RANGE_AXES.items()
                                   for l, h, n in axes]:
            if ax3 == ax and nm3 == nm:
                cc = E[fm.COLS[ax]].astype(float)
                return pd.Series((cc >= lo3) & (cc < hi3), index=E.index)
        for ax3, axes in fm.BOOL_AXES.items():
            for nm3, fn in axes:
                if ax3 == ax and nm3 == nm:
                    return fn(E)
        if ax == "姿态" and nm in fm.POSE_AXES:
            return pd.Series(E["地基姿态"] == nm, index=E.index)
        return None

    for ax, nm in inc:
        om = resolve(ax, nm)
        if om is not None:
            m &= om
    for ax, nm in exc:
        om = resolve(ax, nm)
        if om is not None:
            m &= ~om
    return m


def main() -> None:
    E = forge_mod.load_events()
    print(f"底数 {len(E)}笔 {E['月'].min()}~{E['月'].max()}\n")
    # 两时代独立锻造(完整管线, prefixes=两组现役做对照锚)
    cards1 = forge_mod.forge(E, W1[0], W1[1], ("S", "K"), "W1弱市段(2020-01~2023-08)")
    cards2 = forge_mod.forge(E, W2[0], W2[1], ("S", "K"), "W2强市段(2023-09~2026-10)")

    # ---- 卡片交叉回放: 本段挖的新格(重叠<50%的候选卡)在他段的成绩 ----
    def home_st(era):
        wn = era_mask(E, era).to_numpy()
        e3v = E["E3%"].to_numpy()

        def _st(m):
            mv = m.to_numpy() & wn
            v = e3v[mv]
            n = len(v)
            if n == 0:
                return 0, None, None, None
            return n, v.mean(), (v > 0).mean(), (np.sort(v)[:-3].mean() if n > 3 else v.mean())
        return _st

    for label, cards, mine, other in (("W1挖的格→W2回放", cards1, W1, W2),
                                      ("W2挖的格→W1回放", cards2, W2, W1)):
        print(f"\n{'=' * 24} {label} {'=' * 24}")
        cross, era_only, silent = [], [], []
        for sc, t, s, ov, bp in cards[:80]:   # 分数Top80做交叉(全量打印不现实)
            home_n = len(s)
            m_full = rebuild_mask(E, t)
            idx_other = set(E.index[m_full & era_mask(E, other)])
            st_o = seg_stats(E, idx_other, other)
            row = dict(desc=forge_mod.describe(t, home_st(mine)),
                       home_n=home_n, other=st_o)
            if st_o["n"] == 0 or st_o["n"] < 5:
                silent.append(row)
            elif st_o["alive"]:
                cross.append(row)
            else:
                era_only.append(row)
        print(f"  跨时代(他段也活) {len(cross)} / 时代专属 {len(era_only)} / 他段无票 {len(silent)}")
        for r in cross:
            o = r["other"]
            print(f"  ◆ {r['desc']} | 本段{r['home_n']}笔 → 他段{o['n']}笔"
                  f" 胜{o['win']:.0%} 均{o['avg']:+.1f} 剔3{o['t3']:+.1f}")

    # ---- 现役13条的时代矩阵 ----
    print(f"\n{'=' * 24} 现役13条时代矩阵 {'=' * 24}")
    groups = [("强市组", "s_no"), ("弱市组", "w_no")]
    live_cross = []
    for gname, col in groups:
        for no in sorted(E[col].dropna().unique()):
            idx = set(E.index[E[col] == no])
            s1 = seg_stats(E, idx, W1)
            s2 = seg_stats(E, idx, W2)
            def txt(s):
                if s["n"] == 0:
                    return "  0笔"
                return (f"{s['n']:>3}笔 胜{s['win']:.0%} 均{s['avg']:+5.1f}"
                        f" 剔3{s['t3']:+5.1f}")
            cross = s1["alive"] and s2["alive"]
            only1 = s1["alive"] and not s2["alive"]
            only2 = s2["alive"] and not s1["alive"]
            tagk = "◆跨时代" if cross else ("▲弱市专属" if only1 else
                                          ("▲强市专属" if only2 else "✗两段都死"))
            print(f"  {no} [{tagk}]  W1: {txt(s1)} | W2: {txt(s2)}")
            if cross:
                live_cross.append((gname, no, idx))

    # ---- 适配性口诀总清单 ----
    print(f"\n{'=' * 24} 适配性口诀(跨时代) {'=' * 24}")
    print("现役跨时代条目(两段都过「活着」标准):")
    for gname, no, idx in live_cross:
        s1 = seg_stats(E, idx, W1)
        s2 = seg_stats(E, idx, W2)
        print(f"  {no}: W1 {s1['n']}笔均{s1['avg']:+.1f} / W2 {s2['n']}笔均{s2['avg']:+.1f}")
    print("\n(机器跨时代新格见上方交叉回放◆行; 两清单合一=适配所有行情的口诀池)")


main()
