# -*- coding: utf-8 -*-
"""口诀总表: 现有13条 + 锻造候选, 一张速查表, 按五大类分组。全活算, 无写死。

- 现役13条: tag_scheme/tag_weak 打标(判定=产品代码 import, 与线上零漂移),
  成绩实时算——产品口诀改版后重跑即自动更新。
- 候选行: 每次运行内嵌锻造漏斗重新挖掘(合并档网格→全纪律→按类分组→类内
  近亲合并→每类Top1, 剔除与现役重叠≥50%的)——数据更新后候选自动变。
- 数据源: /tmp/relay23_tagged.pkl 为加速缓存; 数据更新后删掉它即从 CSV 重建
  (CSV=四进五全量明细.csv, 换新数据直接覆盖同路径)。
- 产品判定层(pool.py 的 SCHEMES)是「写死」的——那是立规后的规则本身,
  改它走改版流程, 与本研究脚本无关。
"""
import itertools
import math

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"

EXIST = {
    "A1": ("双平贴零", "锁仓"), "A2": ("一字转强", "锁仓"), "B3": ("贴零温开", "锁仓"),
    "C3": ("一字换手", "锁仓"), "K5": ("二板贴零强开", "锁仓"),
    "B1": ("强开系", "强开"),
    "B2": ("捡尸", "低吸"), "K3": ("双低贴顶", "低吸"), "K9": ("一平二低温开", "低吸"),
    "C2": ("四板便捷", "换手"), "K2": ("四板换手弱市版", "换手"), "K4": ("一三换手缩量承接", "换手"),
    "C1": ("冒泡转弱", "转弱"),
}
FAMILY_ORDER = ["锁仓", "强开", "低吸", "换手", "转弱"]
CAND_NO = {"锁仓": "S", "强开": "Q", "低吸": "L", "换手": "H", "转弱": "Z"}

CHAIN_AXES = {
    "b1开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")],
    "b2开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")],
    "b3开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")],
}
TODAY_AXES = [(-99, 0, "低开"), (0, 3, "平开"), (3, 5, "温开"), (5, 7, "强开"),
              (7, 8.5, "次顶格"), (8.5, 9.5, "准顶格")]
EXTRA_AXES = {
    "b1换手": [(0, 5, "<5"), (5, 12, "5~12"), (12, 99, ">12")],
    "b2换手": [(0, 5, "<5"), (5, 12, "5~12"), (12, 20, "12~20"), (20, 99, ">20")],
    "b3换手": [(0, 5, "<5"), (5, 10, "5~10"), (10, 15, "10~15"), (15, 20, "15~20"),
               (20, 30, "20~30"), (30, 99, ">30")],
    "地基涨跌": [(-99, 1, "<1"), (1, 3, "1~3"), (3, 99, "≥3")],
    "首10日": [(0, 10, "<10"), (10, 20, "10~20"), (20, 999, "≥20")],
    "前波60": [(-0.5, 0.5, "=0"), (0.5, 2.5, "1~2"), (2.5, 99, "≥3")],
    "距新高": [(-99, -8, "<-8"), (-8, 99, "≥-8")],
    "锚位": [(-99, 3, "<3"), (3, 5, "3~5"), (5, 99, "≥5")],
}
POSE_AXES = ["站线上", "骑线", "贴线", "掉线下"]
COLS = {"b1开": "b1开盘%", "b2开": "b2开盘%", "b3开": "b3开盘%", "今开": "买入开盘%",
        "b1换手": "b1换手%", "b2换手": "b2换手%", "b3换手": "b3换手%",
        "地基涨跌": "地基涨跌%", "首10日": "首10日涨幅%", "前波60": "前波60日最高板",
        "距新高": "距60日新高%", "锚位": "锚位%"}
CHAIN_NM = {a: {(lo, hi): nm for lo, hi, nm in axes} for a, axes in CHAIN_AXES.items()}
TODAY_NM = {(lo, hi): nm for lo, hi, nm in TODAY_AXES}


def merged_windows(order, max_span=3):
    out = []
    for i in range(len(order)):
        for j in range(i + 1, min(i + max_span, len(order)) + 1):
            out.append((order[i][0], order[j - 1][1]))
    return out


def nm_of(nm_dict, r):
    return nm_dict[r] if r in nm_dict else f"{r[0]:g}~{r[1]:g}"


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


def row_stats(E, idx, months_r24):
    sub = E.loc[list(idx)]
    e3 = sub["E3%"]
    trim = e3.drop(e3.nlargest(3).index).mean() if len(sub) > 3 else e3.mean()
    yrs = {int(y): g["E3%"].sum() for y, g in sub.groupby("年")}
    worst = min(yrs.values()) if yrs else 0.0
    r24 = sub[sub["月"].isin(months_r24)]["E3%"]
    return (len(sub), (e3 > 0).mean(), e3.mean(), trim, worst,
            r24.mean() if len(r24) else float("nan"))


def mine_candidates(E, exist_union):
    """内嵌锻造漏斗(活挖): 合并档网格+交互腿 → 全纪律 → 类分组 → 每类Top1。
    剔除与现役并集重叠≥50%的(那是现有口诀近亲, 不算新候选)。"""
    e3v = E["E3%"].to_numpy()
    yr = E["年"].to_numpy()
    # 限定现有口诀生态位(二接三/三接四)——四进五/五接六已被 P1/P2 证伪, 不进候选
    live_pools = ("二接三阳", "二接三阴", "三接四阳", "三接四阴")
    pools = {g: idx for g, idx in E.groupby("四组").groups.items() if g in live_pools}

    def window_mask(col, rng):
        c = E[col].astype(float)
        return pd.Series((c >= rng[0]) & (c < rng[1]), index=E.index)

    rng_mask = {a: {(lo, hi): (lambda c=E[COLS[a]].astype(float): (c >= lo) & (c < hi))()
                    for lo, hi, _ in axes} for a, axes in EXTRA_AXES.items()}
    pose_mask = {p: E["地基姿态"] == p for p in POSE_AXES}
    extra_opts = [(a, nm, rng_mask[a][(lo, hi)])
                  for a, axes in EXTRA_AXES.items() for lo, hi, nm in axes]
    extra_opts += [("姿态", p, pose_mask[p]) for p in POSE_AXES]

    def st(m):
        n = int(m.sum())
        if n == 0:
            return 0, None, None, None
        v = e3v[m.to_numpy()]
        return n, v.mean(), (v > 0).mean(), (np.sort(v)[:-3].mean() if n > 3 else v.mean())

    def passes(m):
        mv = m.to_numpy()
        n = int(mv.sum())
        if n < 10:
            return False
        v = e3v[mv]
        if v.mean() < 3.0 or (v > 0).mean() < 0.60:
            return False
        if n > 3 and np.sort(v)[:-3].mean() <= 0:
            return False
        return not (pd.Series(v).groupby(yr[mv]).sum() < -10).any()

    chain_opts = {a: merged_windows([(lo, hi) for lo, hi, _ in axes]) for a, axes in CHAIN_AXES.items()}
    today_opts = merged_windows([(lo, hi) for lo, hi, _ in TODAY_AXES])

    def family_of(legs, tr, inc):
        def touches(r, seg):
            return not (r[1] <= seg[0] or r[0] >= seg[1])
        wins = [r for _, r in legs]
        if any(touches(r, (9.5, 99)) or touches(r, (0, 3)) for r in wins):
            return "锁仓"
        if any(touches(r, (7, 9.5)) for r in wins):
            return "强开"
        if any(touches(r, (-99, 0)) for r in wins):
            return "低吸"
        if any("换手" in a for a, _ in inc):
            return "换手"
        return "转弱"

    def score(t):
        n, a_v, w, t3 = st(t[4])
        return (a_v or 0.0) * math.log(max(n, 1))

    grouped = {fam: [] for fam in FAMILY_ORDER}
    for pool, pidx in pools.items():
        pm = pd.Series(False, index=E.index)
        pm.loc[pidx] = True
        for c1 in [(None, None)] + [("b1开", r) for r in chain_opts["b1开"]]:
            for c2 in [(None, None)] + [("b2开", r) for r in chain_opts["b2开"]]:
                for c3 in [(None, None)] + [("b3开", r) for r in chain_opts["b3开"]]:
                    legs = [x for x in (c1, c2, c3) if x[0]]
                    if len(legs) == 3:
                        continue
                    m0 = pm
                    for a, r in legs:
                        m0 = m0 & window_mask(COLS[a], r)
                    if int(m0.sum()) < 10:
                        continue
                    for tr in today_opts:
                        m = m0 & window_mask("买入开盘%", tr)
                        n, a_v, _, _ = st(m)
                        if n < 10 or a_v is None or a_v < 2.0:
                            continue
                        for m2, inc in ((m, []),) + tuple(
                                (m & om, [(ax, nm)]) for ax, nm, om in extra_opts
                                if int((m & om).sum()) >= 10):
                            if not passes(m2):
                                continue
                            s = set(E.index[m2.to_numpy()])
                            if len(s & exist_union) / len(s) >= 0.5:
                                continue  # 现役近亲
                            t = (pool, legs, tr, inc, m2)
                            grouped[family_of(legs, tr, inc)].append((t, s))
    out = []
    for fam in FAMILY_ORDER:
        items = grouped[fam]
        if not items:
            continue
        items.sort(key=lambda x: -score(x[0]))
        t, s = items[0]  # 每类Top1(类内最高分即天然近亲代表)
        out.append((fam, t, s))
    return out


def main() -> None:
    try:
        E = pd.read_pickle(PKL)
        src = PKL
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
        src = CSV
    E = E[E["E3%"].notna()].copy()
    # 限定二三接生态位(与现役口诀同池), CSV 全板位时自动裁掉 N=4/5
    E = E[E["四组"].isin(("二接三阳", "二接三阴", "三接四阳", "三接四阴"))].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    print(f"(数据源 {src}, {len(E)}笔二三接; 候选行当次实时挖掘, 运行约2~4分钟...)")
    months = sorted(E["月"].unique())
    r24m = set(months[-25:-1])

    DESC = {
        "A1": ("阳·二接三", "二板<1", "6~9.5", "一板<3·二换<12", "现役强市组"),
        "A2": ("阳·二接三", "二板≥9.5一字", "7~8.5", "前10日≥10不碰·假锁排除", "现役强市组"),
        "B3": ("阴·三接四", "二板<1", "3~6", "地基姿态要有人做", "现役强市组"),
        "C3": ("阴/阳·三接四", "二板或三板一字", "6~9.5", "三板换手3~5", "现役强市组"),
        "K5": ("阴·三接四", "二板0~3", "6~9.5", "前波60=0", "现役弱市组"),
        "B1": ("阴·二接三", "二板强开(7~8.5续强/≥7转温)", "6~9.5/3~5", "转温:一板≥7·换手≥5", "现役强市组"),
        "B2": ("阴·二接三", "二板<0或2~3", "<0", "一板<0", "现役强市组"),
        "K3": ("阳·二接三", "双低开", "3~6", "距新高≥-8", "现役弱市组"),
        "K9": ("阴·二接三", "一板0~3×二板<0", "3~7", "—", "现役弱市组"),
        "C2": ("阴/阳·三接四", "三板换手10~20", "5~9.5", "先手小阳×三开<7不碰·锚回避", "现役强市组"),
        "K2": ("阴·三接四", "三板换手10~15", "6~9.5", "地基涨<1·限阴", "现役弱市组"),
        "K4": ("阳·三接四", "三换12~20缩量承接", "0~3", "一板换手≥5·限阳", "现役弱市组"),
        "C1": ("阴/阳·二接三", "二板3~7温开", "<3", "一板≥7", "现役强市组"),
    }

    exist_idx = {}
    for col in ("s_no", "w_no"):
        for c, g in E[E[col].notna()].groupby(col):
            exist_idx.setdefault(c, set()).update(g.index)
    exist_union = set().union(*exist_idx.values())

    print("(候选行为当次实时挖掘, 运行约2~4分钟...)")
    cands = {fam: (t, s) for fam, t, s in mine_candidates(E, exist_union)}

    rows = []
    cand_count = {fam: 0 for fam in FAMILY_ORDER}
    for fam in FAMILY_ORDER:
        for c in [k for k in EXIST if EXIST[k][1] == fam]:
            idx = exist_idx.get(c, set())
            if not idx:
                continue
            n, w, a, t3, worst, r24 = row_stats(E, idx, r24m)
            pool, leg, today, extra, status = DESC[c]
            rows.append({"类": fam, "编号口诀": f"{c} {EXIST[c][0]}", "池": pool,
                         "判别腿": leg, "今开": today, "附加": extra,
                         "成绩(E3)": f"{n}笔·胜{w:.0%}·均{a:+.1f}·剔3{t3:+.1f}",
                         "最差年": f"{worst:+.0f}", "近24月": f"{r24:+.1f}", "状态": status})
        if fam in cands:
            (pool, legs, tr, inc, m2), s = cands[fam]
            cand_count[fam] += 1
            n, w, a, t3, worst, r24 = row_stats(E, s, r24m)
            leg_txt = "×".join(f"{a}{nm_of(CHAIN_NM[a], r)}" for a, r in legs) or "链不限"
            inc_txt = "·".join(f"{a}{nm}" for a, nm in inc) or "—"
            rows.append({"类": fam, "编号口诀": f"{CAND_NO[fam]}{cand_count[fam]} (当次挖掘)",
                         "池": pool, "判别腿": leg_txt, "今开": nm_of(TODAY_NM, tr),
                         "附加": inc_txt,
                         "成绩(E3)": f"{n}笔·胜{w:.0%}·均{a:+.1f}·剔3{t3:+.1f}",
                         "最差年": f"{worst:+.0f}",
                         "近24月": "—" if math.isnan(r24) else f"{r24:+.1f}",
                         "状态": "候选待审"})

    print("| 类 | 编号·口诀 | 池 | 判别腿 | 今开 | 附加 | 成绩(E3) | 最差年 | 近24月 | 状态 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    last = None
    for r in rows:
        cls = r["类"] if r["类"] != last else ""
        last = r["类"]
        print(f"| {cls} | {r['编号口诀']} | {r['池']} | {r['判别腿']} | {r['今开']} "
              f"| {r['附加']} | {r['成绩(E3)']} | {r['最差年']} | {r['近24月']} | {r['状态']} |")


main()
