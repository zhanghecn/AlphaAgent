# -*- coding: utf-8 -*-
"""逐口诀找腿分析: 每条口诀内部 赚票vs亏票 × 全维特征(地基优先) 逐一对比。

主人验收口径: 像当年做 C2 先手小阳腿/A2 前10日腿那样——单条口诀拿出来,
命中票内部赚亏两组, 地基(涨跌/阴阳/姿态/距MA20/锚位/锚距)及其他维度
逐一对比, 差异档逐票点名。加板位视角(二接三/三接四)。
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"

# 维度顺序: 地基系优先(主人点名), 其余按判别习惯
FEATURES = [
    ("地基涨跌%", [(-99, 1, "<1"), (1, 3, "1~3"), (3, 99, "≥3")]),
    ("地基阴阳", None),
    ("地基姿态", None),
    ("地基距MA20%", [(-99, 0, "<0"), (0, 5, "0~5"), (5, 99, "≥5")]),
    ("锚位%", [(-99, 3, "<3"), (3, 5, "3~5"), (5, 99, "≥5")]),
    ("锚距", [(-99, 3, "≤3"), (3, 99, ">3")]),
    ("首10日涨幅%", [(0, 10, "<10"), (10, 20, "10~20"), (20, 999, "≥20")]),
    ("首20日涨幅%", [(0, 15, "<15"), (15, 30, "15~30"), (30, 999, "≥30")]),
    ("前波60日最高板", [(-0.5, 0.5, "=0"), (0.5, 2.5, "1~2"), (2.5, 99, "≥3")]),
    ("距60日新高%", [(-99, -8, "<-8"), (-8, 0, "-8~0"), (0, 99, "≥0")]),
    ("b1开盘%", [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")]),
    ("b2开盘%", [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")]),
    ("b3开盘%", [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")]),
    ("b1换手%", [(0, 5, "<5"), (5, 12, "5~12"), (12, 999, "≥12")]),
    ("b2换手%", [(0, 5, "<5"), (5, 12, "5~12"), (12, 20, "12~20"), (20, 999, "≥20")]),
    ("b3换手%", [(0, 5, "<5"), (5, 10, "5~10"), (10, 15, "10~15"), (15, 20, "15~20"), (20, 999, "≥20")]),
    ("买入量比", [(0, 0.8, "<0.8"), (0.8, 1.5, "0.8~1.5"), (1.5, 999, "≥1.5")]),
    ("昨日涨停家数", [(0, 30, "<30"), (30, 80, "30~80"), (80, 999, "≥80")]),
    ("阴阳", None),
]


def nn(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def tag_both(row):
    g4 = row["四组"]
    s = tag_scheme(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                   auction_pct=nn(row["买入开盘%"]), b2_turn=nn(row["b2换手%"]),
                   b3_turn=nn(row["b3换手%"]), foundation_chg=nn(row["地基涨跌%"]),
                   pre10_pct=nn(row["首10日涨幅%"]), foundation_pose=nn(row["地基姿态"]),
                   anchor_pos=nn(row["锚位%"]), anchor_dist=nn(row["锚距"]))
    w = tag_weak(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                 auction_pct=nn(row["买入开盘%"]), b1_turn=nn(row["b1换手%"]),
                 b2_turn=nn(row["b2换手%"]), b3_turn=nn(row["b3换手%"]),
                 foundation_chg=nn(row["地基涨跌%"]), prev_wave60=nn(row["前波60日最高板"]),
                 dist_h60=nn(row["距60日新高%"]))
    return (str(s["no"]) if s is not None else None,
            str(w["no"]) if w is not None else None)


def legbin(col, bins, v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if bins is None:
        return str(v)
    for lo, hi, nm in bins:
        if lo <= v < hi:
            return nm
    return None


def analyze(E, sub, title):
    """一个口诀(或池)内部 赚vs亏 全维对比; 差异档逐票点名。"""
    win, loss = sub[sub["E3%"] >= 0], sub[sub["E3%"] < 0]
    nw, nl = len(win), len(loss)
    if nw < 5 or nl < 3:
        print(f"\n### {title}: {len(sub)}笔(赚{nw}/亏{nl}) — 样本不足不分析")
        return
    small = len(sub) < 20
    gap_min, cell_min = (0.10, 2) if small else (0.15, 3)
    print(f"\n### {title}: {len(sub)}笔 胜{nw / len(sub):.0%} 均{sub['E3%'].mean():+.1f}"
          f" (赚{nw}vs亏{nl}, 门槛差≥{gap_min:.0%}两侧≥{cell_min}笔)")
    found = []
    for col, bins in FEATURES:
        if col not in E.columns:
            continue
        vw = E.loc[win.index, col].map(lambda x: legbin(col, bins, x))
        vl = E.loc[loss.index, col].map(lambda x: legbin(col, bins, x))
        cw, cl = vw.value_counts(), vl.value_counts()
        for nm in sorted(set(cw.index) | set(cl.index), key=str):
            if cw.get(nm, 0) < cell_min or cl.get(nm, 0) < cell_min:
                continue
            fw = cw[nm] / nw
            fl = cl[nm] / nl
            if fw - fl >= gap_min:
                found.append((col, nm, fw, fl, "赚", vw[vw == nm].index, vl[vl == nm].index))
            elif fl - fw >= gap_min:
                found.append((col, nm, fw, fl, "亏", vw[vw == nm].index, vl[vl == nm].index))
    if not found:
        print("  无显著差异档(该口诀内部赚亏票在事前维度上已同质)")
        return
    found.sort(key=lambda x: -abs(x[2] - x[3]))
    for col, nm, fw, fl, side, wi, li in found[:6]:
        print(f"  [{col}={nm}] 赚{fw:.0%} vs 亏{fl:.0%} → 偏{side}"
              f"({(wi if side == '赚' else li).size}笔)")
        show = wi if side == "赚" else li
        got = E.loc[show].sort_values("E3%")
        pick = got.head(4) if side == "亏" else got.tail(4)
        names = " ".join(f"{str(r['买入日'])[:10]}{str(r['名称'])[:5]}({r['E3%']:+.0f})"
                         for _, r in pick.iterrows())
        print(f"    {side}票: {names}")


def main() -> None:
    try:
        E = pd.read_pickle(PKL)
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()].copy()
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]

    # 板位视角(主人点名: 二接三地基 / 三接四地基)
    analyze(E, E[E["N"] == 2], "二接三全池")
    analyze(E, E[E["N"] == 3], "三接四全池")

    # 逐条口诀(强市8+弱市5)
    for col, pre in (("s_no", "强市"), ("w_no", "弱市")):
        for c in sorted(E[E[col].notna()][col].unique()):
            sub = E[E[col] == c]
            analyze(E, sub, f"{pre}{c}({sub['四组'].iloc[0] if len(sub) else '?'})")


main()
