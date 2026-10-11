# -*- coding: utf-8 -*-
"""口诀锻造炉: 把「口诀如何被做出来」的原始研究管线完整脚本化。

管线原文(弱市口诀卡v5.md, 牛市口诀同管线):
  四组×链档×今开档网格 → 肥格 → 一板/换手交互 → 差票过滤腿 → 边界洞检验 → 胜率>60%收口

对照上版(koujue_mining.py 召回 21%/0%/32%)补齐的三块:
  1. 关系腿: 缩量承接(三换<二换)/b1换手窗/前波60精确档(=0)/锚位档 —— K系精髓
  2. 差票过滤腿(层4): 格内 E3<0 亏票 vs 赚票的档位富集分析 → 自动生成排除腿
     (单维+二维组合, C2「先手小阳×三开<7 不碰」的机器版), 剔后均值升才收
  3. 边界洞检验(层5): 数值窗±1 扰动降幅<50% 才过(防参数孤峰, 主人纪律第5条)

三窗复刻对答案 + 人审级口诀卡(条件人话/全数字/逐票点名/扰动结果)。
"""
import itertools
import math

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"

# ---- 词汇表: 档位=现有口诀窗格语言 + 关系腿(K系精髓) ----
CHAIN_AXES = {
    "b1开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")],
    "b2开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")],
    "b3开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"), (9.5, 99, "一字")],
}
TODAY_AXES = [(-99, 0, "低开"), (0, 3, "平开"), (3, 5, "温开"), (5, 7, "强开"),
              (7, 8.5, "次顶格"), (8.5, 9.5, "准顶格")]
RANGE_AXES = {  # 数值窗附加腿(可做边界扰动)
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
BOOL_AXES = {  # 关系腿(布尔, 不可扰动)
    "缩量承接": [("vol3<vol2", lambda E: E["b3换手%"].astype(float) < E["b2换手%"].astype(float)),
                 ("vol3≥vol2", lambda E: E["b3换手%"].astype(float) >= E["b2换手%"].astype(float))],
    "锚距": [("锚距≤3", lambda E: E["锚距"].astype(float) <= 3), ("锚距>3", lambda E: E["锚距"].astype(float) > 3)],
}
POSE_AXES = ["站线上", "骑线", "贴线", "掉线下"]
COLS = {"b1开": "b1开盘%", "b2开": "b2开盘%", "b3开": "b3开盘%", "今开": "买入开盘%",
        "b1换手": "b1换手%", "b2换手": "b2换手%", "b3换手": "b3换手%",
        "地基涨跌": "地基涨跌%", "首10日": "首10日涨幅%", "前波60": "前波60日最高板",
        "距新高": "距60日新高%", "锚位": "锚位%"}
CHAIN_NM = {a: {(lo, hi): nm for lo, hi, nm in axes} for a, axes in CHAIN_AXES.items()}
TODAY_NM = {(lo, hi): nm for lo, hi, nm in TODAY_AXES}


def merged_windows(order, max_span=3):
    """相邻档合并窗全集(单档+相邻2档+相邻3档)——人工宽窗的网格全集。"""
    out = []
    for i in range(len(order)):
        for j in range(i + 1, min(i + max_span, len(order)) + 1):
            out.append((order[i][0], order[j - 1][1]))
    return out


def nm_of(nm_dict, r):
    """档名; 合并窗回退到数字窗(lo~hi)。"""
    if r in nm_dict:
        return nm_dict[r]
    return f"{r[0]:g}~{r[1]:g}"


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


def load_events() -> pd.DataFrame:
    try:
        E = pd.read_pickle(PKL)
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    return E


def forge(E: pd.DataFrame, lo, hi, prefixes, label, top_k_cards=8) -> list:
    """完整锻造管线(层1~6), 返回送人审的候选卡列表。"""
    W = pd.Series(True, index=E.index)
    if lo:
        W &= E["月"] >= lo
    if hi:
        W &= E["月"] <= hi
    e3v = E["E3%"].to_numpy()
    yr = E["年"].to_numpy()
    wn = W.to_numpy()

    exist = {}
    for col in ("s_no", "w_no"):
        pre = "S" if col == "s_no" else "K"
        if pre not in prefixes:
            continue
        for c, g in E[W & E[col].notna()].groupby(col):
            exist[f"{pre}{c}"] = set(g.index)
    union_exist = set().union(*exist.values()) if exist else set()

    pools = {g: idx for g, idx in E.groupby("四组").groups.items()}

    def window_mask(col, rng):
        c = E[col].astype(float)
        return pd.Series((c >= rng[0]) & (c < rng[1]), index=E.index)

    rng_mask = {a: {(lo2, hi2): (lambda c=E[COLS[a]].astype(float): (c >= lo2) & (c < hi2))()
                    for lo2, hi2, _ in axes} for a, axes in RANGE_AXES.items()}
    bool_mask = {a: {nm: f(E) for nm, f in axes} for a, axes in BOOL_AXES.items()}
    pose_mask = {p: E["地基姿态"] == p for p in POSE_AXES}

    # 全维度档位清单(层3/层4共用; 数值档记 (axis,(lo,hi),nm,mask), 布尔/枚举同构)
    def all_extra_options():
        opts = []
        for a, axes in RANGE_AXES.items():
            for lo2, hi2, nm in axes:
                opts.append((a, (lo2, hi2), nm, rng_mask[a][(lo2, hi2)]))
        for a, axes in BOOL_AXES.items():
            for nm, _ in axes:
                opts.append((a, None, nm, bool_mask[a][nm]))
        for p in POSE_AXES:
            opts.append(("姿态", None, p, pose_mask[p]))
        return opts

    extra_opts = all_extra_options()

    def st(m):
        mv = m.to_numpy() & wn
        n = int(mv.sum())
        if n == 0:
            return 0, None, None, None
        v = e3v[mv]
        t3 = np.sort(v)[:-3].mean() if n > 3 else v.mean()
        return n, v.mean(), (v > 0).mean(), t3

    def passes(m, min_avg=3.0):
        mv = m.to_numpy() & wn
        n = int(mv.sum())
        if n < 10:
            return False
        v = e3v[mv]
        if v.mean() < min_avg or (v > 0).mean() < 0.60:
            return False
        if n > 3 and np.sort(v)[:-3].mean() <= 0:
            return False
        return not (pd.Series(v).groupby(yr[mv]).sum() < -10).any()

    # ---- 层1+2: 四组×链档×今开档网格(合并档全集=人工宽窗形态) → 肥格(均≥+2) ----
    chain_opts = {a: merged_windows([(lo, hi) for lo, hi, _ in axes]) for a, axes in CHAIN_AXES.items()}
    today_opts = merged_windows([(lo, hi) for lo, hi, _ in TODAY_AXES])
    base_alive = []
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
                    if int((m0.to_numpy() & wn).sum()) < 10:
                        continue
                    for tr in today_opts:
                        m = m0 & window_mask("买入开盘%", tr)
                        n, a_v, _, _ = st(m)
                        if n >= 10 and a_v is not None and a_v >= 2.0:
                            base_alive.append((pool, legs, tr, m))

    # ---- 层3: 交互腿(0~2个, 含关系腿) + 纪律初筛 ----
    rough = []  # (pool, chain_legs, today窗, 包含腿[(axis,nm)], mask)
    for pool, legs, tr, m0 in base_alive:
        rough.append((pool, legs, tr, [], m0))
        cand1 = []
        for ax, r, nm, om in extra_opts:
            m = m0 & om
            if int((m.to_numpy() & wn).sum()) < 10:
                continue
            cand1.append(((ax, nm), m))
            rough.append((pool, legs, tr, [(ax, nm)], m))
        for (ca, ma), (cb, mb) in itertools.combinations(cand1, 2):
            if ca[0] == cb[0]:
                continue
            m = ma & mb
            if int((m.to_numpy() & wn).sum()) >= 10:
                rough.append((pool, legs, tr, [ca, cb], m))

    # ---- 层4: 直接过纪律收下; 没过的差票过滤腿拯救(单维+二维, 原管线核心步) ----
    forged = []  # (pool, legs, tr, 包含腿, 排除腿[(axis,nm)], mask)
    for pool, legs, tr, inc, m0 in rough:
        if passes(m0):
            forged.append((pool, legs, tr, inc, [], m0))
        mv = m0.to_numpy() & wn
        n = int(mv.sum())
        if n < 12:
            continue
        lm = mv & (e3v < 0)
        wm2 = mv & (e3v >= 0)
        nl, nw = int(lm.sum()), int(wm2.sum())
        if nl < 3 or nw < 5:
            continue
        rich = []
        for ax, r, nm, om in extra_opts:
            ov = om.to_numpy()
            pl = (ov & lm).sum() / nl
            pw = (ov & wm2).sum() / nw
            if pl - pw >= 0.25 and (ov & lm).sum() >= 3:
                rich.append((pl - pw, ax, nm, ov))
        rich.sort(key=lambda x: -x[0])
        for gain, ax, nm, ov in rich[:3]:
            exc = m0 & ~pd.Series(ov, index=E.index)
            if passes(exc):
                forged.append((pool, legs, tr, inc, [(ax, nm)], exc))
            lm2 = lm & ov
            nl2 = int(lm2.sum())
            if nl2 >= 3:
                for ax2, r2, nm2, ov2 in extra_opts:
                    if ax2 == ax:
                        continue
                    o2 = ov2.to_numpy()
                    pl2 = (o2 & lm2).sum() / nl2
                    pw2 = (o2 & wm2).sum() / nw
                    if pl2 - pw2 >= 0.25 and (o2 & lm2).sum() >= 3:
                        exc2 = m0 & ~pd.Series(ov, index=E.index) & ~pd.Series(o2, index=E.index)
                        if passes(exc2):
                            forged.append((pool, legs, tr, inc,
                                           [(ax, nm), (ax2, nm2)], exc2))

    # 去重(同条件签名只留一个)
    def sig(t):
        pool, legs, tr, inc, exc, _ = t
        return (pool, tuple(sorted((a, nm_of(CHAIN_NM[a], r)) for a, r in legs)), tr,
                tuple(sorted(inc)), tuple(sorted(exc)))
    seen, uniq = set(), []
    for t in forged:
        s = sig(t)
        if s not in seen:
            seen.add(s)
            uniq.append(t)
    forged = uniq

    def resolve(ax, nm):
        """名字 → 档位 mask(包含/排除腿共用)。"""
        for ax3, r3, nm3, om3 in extra_opts:
            if ax3 == ax and nm3 == nm:
                return om3
        return None

    def score(t):
        n, a_v, w, t3 = st(t[5])
        return (a_v or 0.0) * math.log(max(n, 1))

    # ---- 层5: 边界洞检验(数值窗±1, 只对高分候选) + 层6 收口已在 passes ----
    forged.sort(key=lambda x: -score(x))

    def boundary_probe(t):
        """对格的数值腿做±1扰动, 返回最差档均值与原均值之比。"""
        pool, legs, tr, inc, exc, m0 = t
        _, a0, _, _ = st(m0)
        if a0 is None:
            return 0.0
        worst = a0
        probes = [(COLS[a], r) for a, r in legs] + [("买入开盘%", tr)]
        for col, (lo2, hi2) in probes:
            base = E[col].astype(float)
            for dlo, dhi in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                mp = (base >= lo2 + dlo) & (base < hi2 + dhi)
                m = pd.Series(mp, index=E.index)
                # 重建其他腿
                for a2, r2 in legs:
                    if COLS[a2] == col:
                        continue
                    m &= window_mask(COLS[a2], r2)
                m &= pd.Series(E["四组"] == pool, index=E.index)
                if col != "买入开盘%":
                    m &= window_mask("买入开盘%", tr)
                for ax, nm in inc:
                    for ax3, r3, nm3, om3 in extra_opts:
                        if ax3 == ax and nm3 == nm:
                            m &= om3
                            break
                for ax, nm in exc:
                    for ax3, r3, nm3, om3 in extra_opts:
                        if ax3 == ax and nm3 == nm:
                            m &= ~om3
                            break
                _, ap, _, _ = st(m)
                if ap is not None:
                    worst = min(worst, ap)
        return worst / a0 if a0 else 0.0

    # ---- 对答案 ----
    def jac(a, b):
        return len(a & b) / len(a | b) if a | b else 0.0

    surv_sets = [set(E.index[(t[5].to_numpy() & wn)]) for t in forged]
    covered = set().union(*surv_sets) if surv_sets else set()
    recall = len(covered & union_exist) / len(union_exist) if union_exist else float("nan")
    n_hi = sum(1 for s in surv_sets for k in exist if jac(s, exist[k]) >= 0.5)

    print(f"\n{'=' * 28} {label} {'=' * 28}")
    print(f"窗内{int(wn.sum())}笔 | 肥格{len(base_alive)} → 粗格{len(rough)} → 锻造后{len(forged)}"
          f" | 对照{len(exist)}条/{len(union_exist)}笔")
    print(f"召回率: {len(covered & union_exist)}/{len(union_exist)} = {recall:.0%} | "
          f"J≥0.5候选 {n_hi}个 | 纯新增覆盖 {len(covered - union_exist)}笔")
    print("逼近度:")
    for k in sorted(exist):
        best, bj = None, 0.0
        for s, t in zip(surv_sets, forged):
            j = jac(exist[k], s)
            if j > bj:
                bj, best = j, t
        print(f"  {k}: J={bj:.2f} ({len(exist[k])}笔)"
              + (f" ← {describe(best, st)}" if best is not None else " 无重叠"))

    # ---- 人审口诀卡(与现有重叠<50%的高分候选, 边界扰动+逐票) ----
    cards = []
    for t in forged:
        s = set(E.index[(t[5].to_numpy() & wn)])
        ov = max((jac(s, exist[k]) for k in exist), default=0)
        if ov >= 0.5:
            continue
        bp = boundary_probe(t)
        cards.append((score(t), t, s, ov, bp))
    cards.sort(key=lambda x: -x[0])
    print(f"\n人审候选卡(重叠<50%, 边界±1扰动比值≥0.5 才算稳): Top{top_k_cards}")
    for sc, t, s, ov, bp in cards[:top_k_cards]:
        pool, legs, tr, inc, exc, m = t
        n, a_v, w, t3 = st(m)
        idx = E.index[(m.to_numpy() & wn)]
        sub = E.loc[idx].sort_values("买入日")
        yrs = " ".join(f"{y:+.1f}" for y in sub.groupby("年")["E3%"].sum().reindex(
            range(int(sub["年"].min()), int(sub["年"].max()) + 1), fill_value=0))
        print(f"\n  [锻造候选] {pool}|{'×'.join(f'{a}{nm_of(CHAIN_NM[a], r)}' for a, r in legs) or '链不限'}"
              f"|今开{nm_of(TODAY_NM, tr)}|包含:{'/'.join(f'{a}{nm}' for a, nm in inc) or '无'}"
              f"|剔:{'/'.join(f'{a}{nm}' for a, nm in exc) or '无'}")
        print(f"    {n}笔 胜{w:.0%} 均{a_v:+.1f} 剔3{t3:+.1f} | 分年 {yrs} | "
              f"重叠{ov:.0%} 边界扰动比值{bp:.2f}{'⚠不稳' if bp < 0.5 else '✓'}")
        tail = sub.tail(10)
        for _, r in tail.iterrows():
            print(f"      {str(r['买入日'])[:10]} {r['代码']} {str(r['名称'])[:6]:<6s} E3={r['E3%']:+6.1f}")
    return cards


def describe(t, st) -> str:
    pool, legs, tr, inc, exc, m = t
    n, a_v, w, t3 = st(m)
    return (f"{pool}|{'×'.join(f'{a}{nm_of(CHAIN_NM[a], r)}' for a, r in legs) or '链不限'}"
            f"|今开{nm_of(TODAY_NM, tr)}|{n}笔 均{a_v:+.1f} 胜{w:.0%}")


def main() -> None:
    E = load_events()
    forge(E, None, None, ("S", "K"), "全时段 2020-01~2026-10(对照13条)")
    forge(E, "2020-08", "2023-08", ("K",), "弱市时代窗 2020-08~2023-08(对照K系)")
    forge(E, "2023-09", None, ("S",), "强市时代窗 2023-09~2026-10(对照强市8条)")


main()
