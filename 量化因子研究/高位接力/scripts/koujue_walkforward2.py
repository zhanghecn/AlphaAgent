# -*- coding: utf-8 -*-
"""walk-forward v2: 把「人挑口诀的标准」翻译成数据指标, 替换分数Top1。

主人论点: 人也是数据分析出来的, 所有规律都应可识别。人挑格时真实用的标准:
  R1 参数高原(邻档变体都肥=区域肥, 不是点肥) —— 主人方法论第一条
  R2 时间分散(肥票跨季度重复出现, 不是一波行情的运气)
  R3 边界稳定(窗±1扰动不崩)
  R4 剔3厚度(剔掉Top3还剩三成以上)
  R5 交互增益(格均值−最强单腿均值≥+2: AND结构的超额信息, 真行为逻辑;
     只复现单腿的格没有口诀价值)
挑选 = 五指标全过门槛 → 按(邻格min均值×log n)排序, 每类稳健Top1;
另测「类内稳健Top5并集」(现役组本身就是8条口诀的并集, 对标物应是并集)。
双场景重跑: 切换前夜2023-08 / 切换后15月2024-12。
"""
import itertools
import math

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

CSV = "量化因子研究/高位接力/四进五全量明细.csv"
LIVE_POOLS = ("二接三阳", "二接三阴", "三接四阳", "三接四阴")
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
}
POSE_AXES = ["站线上", "骑线", "贴线", "掉线下"]
COLS = {"b1开": "b1开盘%", "b2开": "b2开盘%", "b3开": "b3开盘%", "今开": "买入开盘%",
        "b1换手": "b1换手%", "b2换手": "b2换手%", "b3换手": "b3换手%",
        "地基涨跌": "地基涨跌%", "首10日": "首10日涨幅%", "前波60": "前波60日最高板",
        "距新高": "距60日新高%", "锚位": "锚位%"}
CHAIN_NM = {a: {(lo, hi): nm for lo, hi, nm in axes} for a, axes in CHAIN_AXES.items()}
TODAY_NM = {(lo, hi): nm for lo, hi, nm in TODAY_AXES}
R1_MIN = 0.5    # 邻档最差均值/本格均值 ≥ 0.5(高原)
R2_QUARTERS = 3  # 肥票覆盖季度数 ≥ 3
R3_MIN = 0.0    # 已并入R1(细扰动中位数), 此阈值弃用
R4_MIN = 0.30   # 剔3/均值≥0.3(彩票主杀手, 恢复)
R5_GAIN = 2.0   # 格均值−最强单腿均值 ≥ +2
R6_MAX = 13.0   # 训练窗均值 ≤ +13(真口诀天花板, 超过=过拟合, v3发现)


def merged_windows(order, max_span=3):
    out = []
    for i in range(len(order)):
        for j in range(i + 1, min(i + max_span, len(order)) + 1):
            out.append((order[i][0], order[j - 1][1]))
    return out


def nm_of(d, r):
    return d[r] if r in d else f"{r[0]:g}~{r[1]:g}"


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


def build_mask(df, pool, legs, trw, inc):
    m = pd.Series(df["四组"] == pool, index=df.index)
    for a, r in legs:
        c = df[COLS[a]].astype(float)
        m &= (c >= r[0]) & (c < r[1])
    c = df["买入开盘%"].astype(float)
    m &= (c >= trw[0]) & (c < trw[1])
    for ax, nm in inc:
        if ax == "姿态":
            m &= df["地基姿态"] == nm
        else:
            for a2, axes2 in EXTRA_AXES.items():
                if a2 == ax:
                    for lo, hi, nm2 in axes2:
                        if nm2 == nm:
                            c2 = df[COLS[ax]].astype(float)
                            m &= (c2 >= lo) & (c2 < hi)
    return m


def run(E, cut):
    months_all = sorted(E["月"].unique())
    cut_i = months_all.index(cut) + 1
    train_m = set(months_all[max(0, cut_i - 24):cut_i])
    test_m = set(months_all[cut_i:])
    tr, te = E[E["月"].isin(train_m)], E[E["月"].isin(test_m)]
    print(f"\n{'#' * 30} 场景: 站在 {cut} {'#' * 30}")
    print(f"训练 {min(train_m)}~{max(train_m)} {len(tr)}笔 | 样本外 {min(test_m)}~{max(test_m)} {len(te)}笔")

    e3v = tr["E3%"].to_numpy()
    yr = tr["年"].to_numpy()
    idx_tr = tr.index
    rng_mask = {a: {(lo, hi): (lambda c=tr[COLS[a]].astype(float): (c >= lo) & (c < hi))()
                    for lo, hi, _ in axes} for a, axes in EXTRA_AXES.items()}
    pose_mask = {p: tr["地基姿态"] == p for p in POSE_AXES}
    extra_opts = [(a, nm, rng_mask[a][(lo, hi)])
                  for a, axes in EXTRA_AXES.items() for lo, hi, nm in axes]
    extra_opts += [("姿态", p, pose_mask[p]) for p in POSE_AXES]
    base_avg = e3v.mean()

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

    def family_of(legs, inc):
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

    # ---- 挖掘 ----
    grouped = {fam: [] for fam in FAMILY_ORDER}
    for pool in LIVE_POOLS:
        pm = pd.Series(tr["四组"] == pool, index=idx_tr)
        for c1 in [(None, None)] + [("b1开", r) for r in chain_opts["b1开"]]:
            for c2 in [(None, None)] + [("b2开", r) for r in chain_opts["b2开"]]:
                for c3 in [(None, None)] + [("b3开", r) for r in chain_opts["b3开"]]:
                    legs = [x for x in (c1, c2, c3) if x[0]]
                    if len(legs) == 3:
                        continue
                    m0 = pm
                    for a, r in legs:
                        m0 = m0 & rng_chain(tr, a, r)
                    if int(m0.sum()) < 10:
                        continue
                    for trw in today_opts:
                        m = m0 & rng_today(tr, trw)
                        n, a_v, _, _ = st(m)
                        if n < 10 or a_v is None or a_v < 2.0:
                            continue
                        cand1 = []
                        for ax, nm, om in extra_opts:
                            m2 = m & om
                            if int(m2.sum()) < 10:
                                continue
                            cand1.append(((ax, nm), m2))
                        combos = [([], m)] + [([c], mm) for c, mm in cand1]
                        for (ca, ma), (cb, mb) in itertools.combinations(cand1, 2):
                            if ca[0] == cb[0]:
                                continue
                            m3 = ma & mb
                            if int(m3.sum()) >= 10:
                                combos.append(([ca, cb], m3))
                        for inc, m2 in combos:
                            if passes(m2):
                                grouped[family_of(legs, inc)].append((pool, legs, trw, inc, m2))

    # ---- 人择标准五指标 ----
    def robustness(pool, legs, trw, inc, m2):
        n0, a0, _, t3 = st(m2)
        if a0 is None or a0 <= 0:
            return None
        sub = tr[m2.to_numpy()]
        # R1 参数高原: 邻档变体最差均值
        probes_vals = []
        for a, r in legs:
            for dlo, dhi in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                probes_vals.append(st(build_mask_probe(
                    tr, pool, legs, trw, inc, COLS[a], r[0] + dlo, r[1] + dhi)))
        for dlo, dhi in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            probes_vals.append(st(build_mask_probe(
                tr, pool, legs, trw, inc, "买入开盘%", trw[0] + dlo, trw[1] + dhi)))
        pv = [v for _, v, _, _ in probes_vals if v is not None]
        nb_avgs = pv
        r1 = (float(np.median([v / a0 for v in pv])) if pv else 0.0)
        # R2 时间分散: 肥票覆盖季度数
        q = ((sub["月"].str[:4].astype(int) * 4) + ((sub["月"].str[5:7].astype(int) - 1) // 3))
        r2 = sub[sub["E3%"] > 0].assign(q=q[sub["E3%"] > 0])["q"].nunique()
        # R3 边界±1
        probes = []
        for a, r in legs:
            c = tr[COLS[a]].astype(float)
            for dlo, dhi in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                probes.append((COLS[a], r[0] + dlo, r[1] + dhi))
        for dlo, dhi in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            probes.append(("买入开盘%", trw[0] + dlo, trw[1] + dhi))
        bp = []
        for col, lo2, hi2 in probes:
            m3 = build_mask(tr, pool, legs, trw, inc)
            c = tr[col].astype(float)
            m3 &= (c >= lo2) & (c < hi2)
            # 还原该腿原窗(被build重设过): 直接重算
            m3 = build_mask_probe(tr, pool, legs, trw, inc, col, lo2, hi2)
            if st(m3)[0] >= 5:
                bp.append(st(m3)[1])
        r3 = (min(bp) / a0) if bp else 0.0
        # R4 剔3厚度
        r4 = (t3 / a0) if a0 else 0.0
        # R5 交互增益: 格均值 − 最强单腿均值
        single_best = base_avg
        for a, r in legs:
            m4 = pd.Series((tr[COLS[a]].astype(float) >= r[0])
                           & (tr[COLS[a]].astype(float) < r[1]), index=idx_tr)
            m4 &= pd.Series(tr["四组"] == pool, index=idx_tr)
            av = st(m4)[1]
            if av is not None:
                single_best = max(single_best, av)
        c = tr["买入开盘%"].astype(float)
        m5 = (c >= trw[0]) & (c < trw[1])
        m5 &= pd.Series(tr["四组"] == pool, index=idx_tr).to_numpy()
        av5 = st(pd.Series(m5, index=idx_tr))[1]
        if av5 is not None:
            single_best = max(single_best, av5)
        r5 = a0 - single_best
        ok = (r1 >= 0.7 and r2 >= R2_QUARTERS
              and r4 >= R4_MIN and r5 >= R5_GAIN and a0 <= R6_MAX)
        return {"ok": ok, "r1": r1, "r2": r2, "r3": r3, "r4": r4, "r5": r5,
                "score": (t3 if t3 and t3 > 0 else 0) * math.log(max(n0, 1))}

    hits_te_top1, hits_te_top5 = [], []
    for fam in FAMILY_ORDER:
        items = grouped[fam]
        if not items:
            continue
        rob = []
        for pool, legs, trw, inc, m2 in items:
            rr = robustness(pool, legs, trw, inc, m2)
            if rr and rr["ok"]:
                rob.append(((pool, legs, trw, inc, m2), rr))
        if not rob:
            print(f"  {fam}系: 幸存{len(items)}格, 五指标全过 0 格")
            continue
        rob.sort(key=lambda x: -x[1]["score"])
        print(f"  {fam}系: 幸存{len(items)}格, 五指标全过 {len(rob)} 格")
        for (pool, legs, trw, inc, m2), rr in rob[:5]:
            mte = build_mask(te, pool, legs, trw, inc)
            sub_te = te[mte]
            n0, a0, _, t3 = st(m2)
            tail = (f"样本外{len(sub_te)}笔"
                    + (f" 均{sub_te['E3%'].mean():+.1f} 和{sub_te['E3%'].sum():+.1f}"
                       f" 胜{(sub_te['E3%'] > 0).mean():.0%}" if len(sub_te) else " 无票"))
            print(f"    [{pool}|{'×'.join(nm_of(CHAIN_NM[a], r) for a, r in legs) or '链不限'}|"
                  f"今开{nm_of(TODAY_NM, trw)}|{','.join(n for _, n in inc) or '—'}] "
                  f"训{n0}笔+{a0:.1f} R{rr['r1']:.1f}/{rr['r2']}/{rr['r3']:.1f}/{rr['r4']:.1f}/{rr['r5']:+.1f} → {tail}")
            if len(sub_te):
                hits_te_top5.append(sub_te)
        # Top1
        pool, legs, trw, inc, m2 = rob[0][0]
        sub_te = te[build_mask(te, pool, legs, trw, inc)]
        if len(sub_te):
            hits_te_top1.append(sub_te)

    def report(name, hits):
        if not hits:
            print(f"  {name}: 样本外无票")
            return
        u = pd.concat(hits).drop_duplicates(subset=["代码", "买入日"])
        print(f"  {name}: {len(u)}笔 胜{(u['E3%'] > 0).mean():.0%} "
              f"均{u['E3%'].mean():+.2f} 和{u['E3%'].sum():+.1f} 月均"
              f"{len(u) / len(test_m):.1f}笔")

    print(f"—— 样本外总账({cut}) ——")
    report("每类稳健Top1", hits_te_top1)
    report("每类稳健Top5并集", hits_te_top5)
    cur = te[te["s_no"].notna()].drop_duplicates(subset=["代码", "买入日"])
    print(f"  对照现役强市组: {len(cur)}笔 胜{(cur['E3%'] > 0).mean():.0%} "
          f"均{cur['E3%'].mean():+.2f} 和{cur['E3%'].sum():+.1f}")


def rng_chain(df, a, r):
    c = df[COLS[a]].astype(float)
    return pd.Series((c >= r[0]) & (c < r[1]), index=df.index)


def rng_today(df, r):
    c = df["买入开盘%"].astype(float)
    return pd.Series((c >= r[0]) & (c < r[1]), index=df.index)


def adj_windows(order, r):
    """窗 r 的邻档(左邻/右邻合并版)。"""
    out = []
    for i, w in enumerate(order):
        if w == r:
            if i > 0:
                out.append((order[i - 1][0], r[1]))
            if i < len(order) - 1:
                out.append((r[0], order[i + 1][1]))
    if r not in order:  # 合并窗: 找覆盖的档并扩展
        idxs = [i for i, w in enumerate(order) if not (w[1] <= r[0] or w[0] >= r[1])]
        if idxs:
            lo_i, hi_i = min(idxs), max(idxs)
            if hi_i + 1 < len(order):
                out.append((r[0], order[hi_i + 1][1]))
            if lo_i > 0:
                out.append((order[lo_i - 1][0], r[1]))
    return out


def build_mask_probe(df, pool, legs, trw, inc, col, lo2, hi2):
    m = pd.Series(df["四组"] == pool, index=df.index)
    for a, r in legs:
        cc = df[COLS[a]].astype(float)
        if COLS[a] == col:
            m &= (cc >= lo2) & (cc < hi2)
        else:
            m &= (cc >= r[0]) & (cc < r[1])
    c = df["买入开盘%"].astype(float)
    if col == "买入开盘%":
        m &= (c >= lo2) & (c < hi2)
    else:
        m &= (c >= trw[0]) & (c < trw[1])
    for ax, nm in inc:
        if ax == "姿态":
            m &= df["地基姿态"] == nm
        else:
            for a2, axes2 in EXTRA_AXES.items():
                if a2 == ax:
                    for lo, hi, nm2 in axes2:
                        if nm2 == nm:
                            c2 = df[COLS[ax]].astype(float)
                            m &= (c2 >= lo) & (c2 < hi)
    return m


def main() -> None:
    E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()]
    E = E[E["四组"].isin(LIVE_POOLS)].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    run(E, "2023-08")
    run(E, "2024-12")


main()
