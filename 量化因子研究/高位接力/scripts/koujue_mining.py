# -*- coding: utf-8 -*-
"""口诀挖掘机 S2.0 复刻实验(rediscovery test): 假装不知道现有13条口诀,
在现有口诀的条件词汇表内穷举候选格+纪律过滤, 对答案量「跟目前差距大不大」。

三窗对比(v2, 首版教训: 现有口诀是时代口诀, 全时段纪律天然挖不回——
公平考卷=各用对应时代窗挖, 这才是「2年后在近窗上挖」的真实模拟):
  全时段 2020-2026        对照=13条全
  弱市时代窗 2020-08~2023-08 对照=K系(弱市组的定型段)
  强市时代窗 2023-09~2026-10 对照=强市8条

设计(requirements/koujue_autogen_drift_plan.md):
- 词汇表 = 现有口诀的窗格语言(链开盘/今开/换手/地基/姿态/前波/距新高), 语言级对齐。
- 漏斗: 基础网格(池×链开0~2腿×今开)初筛 → ×附加腿0~2 → 全纪律。
- 纪律(窗口内): n≥10 / 均值≥+3 / 胜率≥60% / 剔Top3正 / 窗口内逐年>-10。
- 对答案: 召回率 / 逼近度(每现有编号最大Jaccard) / 信噪比(J≥0.5候选数)。
"""
import itertools
import math

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 240)

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"

# ---- 词汇表(档位=现有口诀窗格语言, NaN→该腿不命中) ----
CHAIN_AXES = {  # 链开盘%档(基础网格)
    "b1开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 99, "强开"), (9.5, 99, "一字")],
    "b2开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 99, "强开"), (9.5, 99, "一字")],
    "b3开": [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 99, "强开"), (9.5, 99, "一字")],
}
TODAY_AXES = [(-99, 0, "低开"), (0, 3, "平开"), (3, 5, "温开"), (5, 7, "强开"),
              (7, 8.5, "次顶格"), (8.5, 9.5, "准顶格")]
EXTRA_AXES = {  # 附加腿(第二层)
    "b2换手": [(0, 5, "<5"), (5, 12, "5~12"), (12, 20, "12~20"), (20, 99, ">20")],
    "b3换手": [(0, 5, "<5"), (5, 10, "5~10"), (10, 15, "10~15"), (15, 20, "15~20"),
               (20, 30, "20~30"), (30, 99, ">30")],
    "地基涨跌": [(-99, 1, "<1"), (1, 3, "1~3"), (3, 99, "≥3")],
    "首10日": [(0, 20, "<20"), (20, 999, "≥20")],
    "前波60": [(-99, 2.5, "≤2板"), (2.5, 99, "≥3板")],
    "距新高": [(-99, -8, "<-8"), (-8, 99, "≥-8")],
}
POSE_AXES = ["站线上", "骑线", "贴线", "掉线下"]  # 枚举腿
COLS = {"b1开": "b1开盘%", "b2开": "b2开盘%", "b3开": "b3开盘%", "今开": "买入开盘%",
        "b2换手": "b2换手%", "b3换手": "b3换手%", "地基涨跌": "地基涨跌%",
        "首10日": "首10日涨幅%", "前波60": "前波60日最高板", "距新高": "距60日新高%"}
CHAIN_NM = {a: {(lo, hi): nm for lo, hi, nm in axes} for a, axes in CHAIN_AXES.items()}
TODAY_NM = {(lo, hi): nm for lo, hi, nm in TODAY_AXES}


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


def mine(E: pd.DataFrame, lo: str | None, hi: str | None, prefixes: tuple,
         label: str) -> None:
    """在一个窗口上跑完整挖掘漏斗并对答案。lo/hi=None 表示不限。"""
    W = pd.Series(True, index=E.index)
    if lo:
        W &= E["月"] >= lo
    if hi:
        W &= E["月"] <= hi
    e3v = E["E3%"].to_numpy()
    yr = E["年"].to_numpy()
    wn = W.to_numpy()

    # 现有口诀命中集合(对照答案, 只取本窗对应的组)
    exist = {}
    for col in ("s_no", "w_no"):
        pre = "S" if col == "s_no" else "K"
        if pre not in prefixes:
            continue
        for c, g in E[W & E[col].notna()].groupby(col):
            exist[f"{pre}{c}"] = set(g.index)
    union_exist = set().union(*exist.values()) if exist else set()

    pools = {g: idx for g, idx in E.groupby("四组").groups.items()}
    chain_mask = {a: {(lo2, hi2): (lambda c=E[COLS[a]].astype(float): (c >= lo2) & (c < hi2))()
                      for lo2, hi2, _ in axes} for a, axes in CHAIN_AXES.items()}
    today_mask = {(lo2, hi2): (lambda c=E["买入开盘%"].astype(float): (c >= lo2) & (c < hi2))()
                  for lo2, hi2, _ in TODAY_AXES}
    extra_mask = {a: {(lo2, hi2): (lambda c=E[COLS[a]].astype(float): (c >= lo2) & (c < hi2))()
                      for lo2, hi2, _ in axes} for a, axes in EXTRA_AXES.items()}
    pose_mask = {p: E["地基姿态"] == p for p in POSE_AXES}

    def stats_mask(m):
        mv = m.to_numpy() & wn
        n = int(mv.sum())
        if n == 0:
            return 0, None, None, None
        v = e3v[mv]
        t3 = np.sort(v)[:-3].mean() if n > 3 else v.mean()
        return n, v.mean(), (v > 0).mean(), t3

    def passes(m):
        """窗口内纪律: n≥10/均≥3/胜≥60%/剔3正/逐年>-10。"""
        mv = m.to_numpy() & wn
        n = int(mv.sum())
        if n < 10:
            return False
        v = e3v[mv]
        if v.mean() < 3.0 or (v > 0).mean() < 0.60:
            return False
        if n > 3 and np.sort(v)[:-3].mean() <= 0:
            return False
        dfy = pd.Series(v).groupby(yr[mv]).sum()
        return not (dfy < -10).any()

    # ---- 层1: 基础网格(池×链开0~2腿×今开) ----
    base_alive = []
    grid = 0
    for pool, pidx in pools.items():
        pm = pd.Series(False, index=E.index)
        pm.loc[pidx] = True
        for c1 in [(None, None)] + [("b1开", r) for r in chain_mask["b1开"]]:
            for c2 in [(None, None)] + [("b2开", r) for r in chain_mask["b2开"]]:
                for c3 in [(None, None)] + [("b3开", r) for r in chain_mask["b3开"]]:
                    legs = [x for x in (c1, c2, c3) if x[0]]
                    if len(legs) == 3:
                        continue  # 链开最多2腿
                    m0 = pm
                    for a, r in legs:
                        m0 = m0 & chain_mask[a][r]
                    if int((m0.to_numpy() & wn).sum()) < 10:
                        continue
                    for tr, tm in today_mask.items():
                        m = m0 & tm
                        grid += 1
                        n, a_v, w, _ = stats_mask(m)
                        if n >= 10 and a_v is not None and a_v >= 2.0:
                            base_alive.append((pool, legs, tr, m))

    # ---- 层2: 附加腿0~2 + 全纪律 ----
    survivors = []
    extra_opts = [(a, (lo2, hi2), nm) for a, axes in EXTRA_AXES.items()
                  for lo2, hi2, nm in axes] + [("姿态", None, p) for p in POSE_AXES]
    for pool, legs, tr, m0 in base_alive:
        if passes(m0):
            survivors.append((pool, legs, tr, [], m0))
        cand1 = []
        for ax, r, nm in extra_opts:
            m = m0 & (pose_mask[nm] if ax == "姿态" else extra_mask[ax][r])
            if int((m.to_numpy() & wn).sum()) < 10:
                continue
            cand1.append(((ax, nm), m))
            if passes(m):
                survivors.append((pool, legs, tr, [(ax, nm)], m))
        for (ca, ma), (cb, mb) in itertools.combinations(cand1, 2):
            if ca[0] == cb[0]:
                continue  # 同维至多一腿
            m = ma & mb
            if int((m.to_numpy() & wn).sum()) >= 10 and passes(m):
                survivors.append((pool, legs, tr, [ca, cb], m))

    print(f"\n{'=' * 30} {label} {'=' * 30}")
    print(f"窗口内{int(wn.sum())}笔 | 网格{grid}格 初筛{len(base_alive)}格"
          f" → 全纪律幸存{len(survivors)}候选 | 对照{len(exist)}条/{len(union_exist)}笔")

    # ---- 对答案 ----
    def jac(a, b):
        return len(a & b) / len(a | b) if a | b else 0.0

    def describe(args):
        pool, legs, tr, ext, m = args
        n, a_v, w, t3 = stats_mask(m)
        leg_txt = "×".join(f"{a}{CHAIN_NM[a][r]}" for a, r in legs) or "链不限"
        ext_txt = "×".join(f"{a}{nm}" for a, nm in ext) or "无"
        return (f"{pool}|{leg_txt}|今开{TODAY_NM[tr]}|{ext_txt}"
                f" ({n}笔 均{a_v:+.1f} 胜{w:.0%} 剔3{t3:+.1f})")

    surv_sets = [set(E.index[(m.to_numpy() & wn)]) for *_, m in survivors]
    covered = set().union(*surv_sets) if surv_sets else set()
    if union_exist:
        recall = len(covered & union_exist) / len(union_exist)
        print(f"召回率: 对照{len(union_exist)}笔中被覆盖{len(covered & union_exist)}笔 = {recall:.0%}")
        print("逼近度(每编号最大Jaccard候选):")
        for k in sorted(exist):
            best, bj = None, 0.0
            for s, args in zip(surv_sets, survivors):
                j = jac(exist[k], s)
                if j > bj:
                    bj, best = j, args
            if best is None:
                print(f"  {k}: 无重叠 ({len(exist[k])}笔)")
            else:
                print(f"  {k}: J={bj:.2f} ← {describe(best)}")
    n_hi = sum(1 for s in surv_sets for k in exist if jac(s, exist[k]) >= 0.5)
    print(f"信噪比: J≥0.5候选 {n_hi}个; 纯新增覆盖(对照全不命中) "
          f"{len(covered - union_exist)}笔")

    scored = []
    for args, s in zip(survivors, surv_sets):
        pool, legs, tr, ext, m = args
        n, a_v, w, t3 = stats_mask(m)
        ov = len(s & union_exist) / len(s) if union_exist and len(s) else 0
        scored.append((a_v * math.log(n), args, ov))
    scored.sort(key=lambda x: -x[0])
    print(f"幸存Top10(挖掘机视角):")
    for _, args, ov in scored[:10]:
        print(f"  {describe(args)} 重叠{ov:.0%}")


def main() -> None:
    E = load_events()
    mine(E, None, None, ("S", "K"), "全时段 2020-01~2026-10(对照13条)")
    mine(E, "2020-08", "2023-08", ("K",), "弱市时代窗 2020-08~2023-08(对照K系)")
    mine(E, "2023-09", None, ("S",), "强市时代窗 2023-09~2026-10(对照强市8条)")


main()
