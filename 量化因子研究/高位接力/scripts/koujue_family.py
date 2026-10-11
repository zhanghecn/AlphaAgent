# -*- coding: utf-8 -*-
"""口诀五大类: 按链形态分族, 类级筛选+类级体检+候选归类。

分类体系(链行为语言, 与口诀卡「跨阴阳铁律」和 hpr-23 审计的族级属性一致):
  锁仓系  链上有安静板(贴零/一字)=筹码被收, 今天才发力 —— A1/A2/B3/C3
  强开系  板板强开=主力连续进攻                 —— B1/K5
  低吸系  弱势链上捡尸(低开)                    —— B2/K9/K3
  换手系  不看开盘看换手接力(人气)              —— C2/K2/K4
  转弱系  强转温的喘息段                        —— C1

输出:
  1. 13条口诀的类别归属验证(人工映射 vs 数据自动归类对上才算数)
  2. 类级时代属性: 全时段/近24月成绩+色卡(类级体检——比口诀级更稳的监控粒度)
  3. 锻造炉幸存候选按类分组+类内近亲合并(J≥0.7 留最优) → 每类代表格
"""
import itertools
import math

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"

FAMILY = {  # 口诀号 → (大类, 类心法)
    "A1": ("锁仓", "前面越安静,今天的抢筹越真"),
    "A2": ("锁仓", "一字锁仓后今开转强"),
    "B3": ("锁仓", "二板贴零锁着,今开温开"),
    "C3": ("锁仓", "一字链换手接力"),
    "B1": ("强开", "板板强开主力连续行为"),
    "K5": ("锁仓", "二板贴零今开强攻(安静链今天发力)"),
    "B2": ("低吸", "弱势链上捡尸"),
    "K9": ("低吸", "一平二低今开温"),
    "K3": ("低吸", "双低开贴顶"),
    "C2": ("换手", "三板换手10~20人气接力"),
    "K2": ("换手", "四板换手弱市版"),
    "K4": ("换手", "一三换手缩量承接"),
    "C1": ("转弱", "冒泡转弱的喘息"),
}
FAMILY_ORDER = ["锁仓", "强开", "低吸", "换手", "转弱"]

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
    "缩量承接": [("vol3<vol2", None), ("vol3≥vol2", None)],
    "锚距": [("≤3", None), (">3", None)],
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


def main() -> None:
    try:
        E = pd.read_pickle(PKL)
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    e3v = E["E3%"].to_numpy()
    yr = E["年"].to_numpy()
    months = sorted(E["月"].unique())
    r24m = set(months[-25:-1])

    # ---- 1. 类别归属: 人工映射 vs 数据自动归类(按类原型命中并集的最大归属) ----
    koujue_no = {}
    for col in ("s_no", "w_no"):
        for c in E[E[col].notna()][col].unique():
            koujue_no[c] = E[E[col] == c].index
    fam_sets = {}
    for c in koujue_no:
        fam = FAMILY.get(c, ("?", ""))[0]
        fam_sets.setdefault(fam, set()).update(koujue_no[c])

    print("===== 1) 13条口诀五大类归属 =====")
    for fam in FAMILY_ORDER:
        members = [c for c in sorted(FAMILY) if FAMILY[c][0] == fam]
        tip = FAMILY[members[0]][1]
        print(f"  {fam}系({tip}): {'/'.join(members)}"
              f" — 命中{len(fam_sets.get(fam, set()))}笔")

    # ---- 2. 类级时代属性 + 类级体检(近24月 vs 全时段) ----
    print("\n===== 2) 类级成绩(全时段 / 近24月)与体检 =====")
    rows = []
    for fam in FAMILY_ORDER:
        idx = list(fam_sets.get(fam, set()))
        if not idx:
            continue
        sub = E.loc[idx]
        r24 = sub[sub["月"].isin(r24m)]
        cum_avg = sub["E3%"].mean()
        r24_avg = r24["E3%"].mean() if len(r24) else None
        ratio = r24_avg / cum_avg if (r24_avg is not None and cum_avg) else None
        yrs = {int(y): g["E3%"].sum() for y, g in sub.groupby("年")}
        color = "绿" if (ratio is None or ratio >= 0.5) else ("黄" if ratio >= 0 else "红")
        rows.append({"大类": fam, "全时段笔": len(sub), "全时段均": round(cum_avg, 2),
                     "全时段胜": f"{(sub['E3%'] > 0).mean():.0%}",
                     "近24月笔": len(r24), "近24月均": None if r24_avg is None else round(r24_avg, 2),
                     "近/全比": None if ratio is None else round(ratio, 2), "色": color})
    print(pd.DataFrame(rows).to_string(index=False))
    print("分年和(全时段):")
    for fam in FAMILY_ORDER:
        idx = list(fam_sets.get(fam, set()))
        if not idx:
            continue
        sub = E.loc[idx]
        yrs = " ".join(f"{y:+6.1f}" for y in [sub[sub['年'] == y]['E3%'].sum() for y in range(2020, 2027)])
        print(f"  {fam}: {yrs}")

    # ---- 3. 锻造炉幸存候选按类分组 + 类内近亲合并 ----
    pools = {g: idx for g, idx in E.groupby("四组").groups.items()}

    def window_mask(col, rng):
        c = E[col].astype(float)
        return pd.Series((c >= rng[0]) & (c < rng[1]), index=E.index)

    rng_mask = {a: {(lo, hi): (lambda c=E[COLS[a]].astype(float): (c >= lo) & (c < hi))()
                    for lo, hi, _ in [t for t in axes if isinstance(t[0], (int, float))]}
                for a, axes in EXTRA_AXES.items()}
    bool_mask = {}
    bool_mask["缩量承接"] = {"vol3<vol2": E["b3换手%"].astype(float) < E["b2换手%"].astype(float),
                             "vol3≥vol2": E["b3换手%"].astype(float) >= E["b2换手%"].astype(float)}
    bool_mask["锚距"] = {"≤3": E["锚距"].astype(float) <= 3, ">3": E["锚距"].astype(float) > 3}
    pose_mask = {p: E["地基姿态"] == p for p in POSE_AXES}

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

    extra_opts = []
    for a, axes in EXTRA_AXES.items():
        for t in axes:
            if isinstance(t[0], (int, float)):
                lo, hi, nm = t
                extra_opts.append((a, nm, rng_mask[a][(lo, hi)]))
            else:
                nm, _ = t
                extra_opts.append((a, nm, bool_mask[a][nm]))
    for p in POSE_AXES:
        extra_opts.append(("姿态", p, pose_mask[p]))

    chain_opts = {a: merged_windows([(lo, hi) for lo, hi, _ in axes]) for a, axes in CHAIN_AXES.items()}
    today_opts = merged_windows([(lo, hi) for lo, hi, _ in TODAY_AXES])

    forged = []
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
                        if n >= 10 and a_v is not None and a_v >= 2.0:
                            if passes(m):
                                forged.append((pool, legs, tr, [], m))
                            cand1 = []
                            for ax, nm, om in extra_opts:
                                m2 = m & om
                                if int(m2.sum()) < 10:
                                    continue
                                cand1.append(((ax, nm), m2))
                                if passes(m2):
                                    forged.append((pool, legs, tr, [(ax, nm)], m2))
                            for (ca, ma), (cb, mb) in itertools.combinations(cand1, 2):
                                if ca[0] == cb[0]:
                                    continue
                                m3 = ma & mb
                                if int(m3.sum()) >= 10 and passes(m3):
                                    forged.append((pool, legs, tr, [ca, cb], m3))

    def score(t):
        n, a_v, w, t3 = st(t[4])
        return (a_v or 0.0) * math.log(max(n, 1))

    def jac(a, b):
        return len(a & b) / len(a | b) if a | b else 0.0

    # 候选归类: 按形态特征判(链开窗触及什么档), 不按票面重叠——
    # 锁仓=链触及一字/贴零(安静板); 强开=触及强开; 低吸=触及低开;
    # 换手=链不限/温开但有换手腿; 转弱=温开×今开低窗无换手腿。
    def touches(r, seg):
        lo, hi = r
        return not (hi <= seg[0] or lo >= seg[1])

    def family_of(legs, tr, inc):
        chain_wins = [r for _, r in legs]
        if any(touches(r, (9.5, 99)) or touches(r, (0, 3)) for r in chain_wins):
            return "锁仓"
        if any(touches(r, (7, 9.5)) for r in chain_wins):
            return "强开"
        if any(touches(r, (-99, 0)) for r in chain_wins):
            return "低吸"
        if any(a.startswith("b") and "换手" in a for a, _ in inc):
            return "换手"
        if tr[1] <= 3:
            return "转弱"
        return "转弱"

    grouped = {fam: [] for fam in FAMILY_ORDER}
    for t in forged:
        pool, legs, tr, inc, m = t
        fam = family_of(legs, tr, inc)
        s = set(E.index[m.to_numpy()])
        j = jac(s, fam_sets.get(fam, set()))
        grouped[fam].append((t, s, j))

    print(f"\n===== 3) 锻造候选按大类分组(幸存{len(forged)}个, 类内近亲J≥0.7合并) =====")
    for fam in FAMILY_ORDER:
        items = grouped[fam]
        if not items:
            print(f"\n—— {fam}系: 无幸存候选")
            continue
        items.sort(key=lambda x: -score(x[0]))
        keep = []
        for t, s, j in items:
            if any(jac(s, s2) >= 0.7 for _, s2, _ in keep):
                continue
            keep.append((t, s, j))
        print(f"\n—— {fam}系: 幸存{len(items)}个 → 近亲合并后{len(keep)}个代表(Top3):")
        for t, s, j in keep[:3]:
            pool, legs, tr, inc, m = t
            n, a_v, w, t3 = st(m)
            sub = E.loc[list(s)]
            yrs = " ".join(f"{y:+.1f}" for y in [sub[sub['年'] == y]['E3%'].sum() for y in range(2020, 2027)])
            leg_txt = "×".join(f"{a}{nm_of(CHAIN_NM[a], r)}" for a, r in legs) or "链不限"
            inc_txt = "×".join(f"{a}{nm}" for a, nm in inc) or "无"
            print(f"  [{pool}|{leg_txt}|今开{nm_of(TODAY_NM, tr)}|{inc_txt}]"
                  f" {n}笔 胜{w:.0%} 均{a_v:+.1f} 剔3{t3:+.1f}")
            print(f"    分年 {yrs} | 与{fam}原型重叠{j:.0%}")


main()
