# -*- coding: utf-8 -*-
"""终极验证: 假如现有口诀全不适应市场, 脚本能否挖出新口诀?

walk-forward 实验: 站在 2023-09(上次口诀大换代·弱市组→强市组切换点),
假装现役口诀全部失效, 只用切换前 24 个月(2021-09~2023-08)训练挖掘:
  合并档网格 → 近窗纪律(n≥10/胜≥60%/剔3正/近窗逐年>-10) → 每类Top1
然后在切换后 39 个月(2023-09~2026-10, 样本外)回放成绩。

验收: 挖出的"新口诀"样本外是否赚钱; 对照=现役强市组同段(+9.21/72%)。
这也检验全时段纪律的死穴: 新时代口诀在旧时代数据里没有好成绩,
只有近窗纪律才挖得出(训练窗含弱市段, 考验最严酷)。
"""
import itertools
import math

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

CSV = "量化因子研究/高位接力/四进五全量明细.csv"
CUT = "2023-08"            # 站在切换点前夜
TRAIN_MONTHS = 24          # 训练窗=切换前24月
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


def run(E, cut):
    global CUT
    CUT = cut
    E = E[E["E3%"].notna()]
    E = E[E["四组"].isin(LIVE_POOLS)].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]

    months_all = sorted(E["月"].unique())
    cut_i = months_all.index(cut) + 1
    train_m = set(months_all[max(0, cut_i - TRAIN_MONTHS):cut_i])
    test_m = set(months_all[cut_i:])
    tr = E[E["月"].isin(train_m)]
    te = E[E["月"].isin(test_m)]
    print(f"训练窗 {min(train_m)}~{max(train_m)} {len(tr)}笔 | 样本外 {min(test_m)}~"
          f"{max(test_m)} {len(te)}笔 | 站在 {CUT} 假装现役口诀全死")

    e3v = tr["E3%"].to_numpy()
    yr = tr["年"].to_numpy()
    idx_tr = tr.index

    def window_mask(col, rng):
        c = tr[col].astype(float)
        return pd.Series((c >= rng[0]) & (c < rng[1]), index=idx_tr)

    rng_mask = {a: {(lo, hi): (lambda c=tr[COLS[a]].astype(float): (c >= lo) & (c < hi))()
                    for lo, hi, _ in axes} for a, axes in EXTRA_AXES.items()}
    pose_mask = {p: tr["地基姿态"] == p for p in POSE_AXES}
    extra_opts = [(a, nm, rng_mask[a][(lo, hi)])
                  for a, axes in EXTRA_AXES.items() for lo, hi, nm in axes]
    extra_opts += [("姿态", p, pose_mask[p]) for p in POSE_AXES]

    def st(m):
        n = int(m.sum())
        if n == 0:
            return 0, None, None, None
        v = e3v[m.to_numpy()]
        return n, v.mean(), (v > 0).mean(), (np.sort(v)[:-3].mean() if n > 3 else v.mean())

    def passes(m):  # 近窗纪律(训练窗内)
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

    def score(m):
        n, a_v, w, t3 = st(m)
        return (a_v or 0.0) * math.log(max(n, 1))

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
                        m0 = m0 & window_mask(COLS[a], r)
                    if int(m0.sum()) < 10:
                        continue
                    for trw in today_opts:
                        m = m0 & window_mask("买入开盘%", trw)
                        n, a_v, _, _ = st(m)
                        if n < 10 or a_v is None or a_v < 2.0:
                            continue
                        for m2, inc in ((m, []),) + tuple(
                                (m & om, [(ax, nm)]) for ax, nm, om in extra_opts
                                if int((m & om).sum()) >= 10):
                            if passes(m2):
                                grouped[family_of(legs, inc)].append((pool, legs, trw, inc, m2))

    print(f"\n{'='*26} 站在{CUT}挖出的新口诀 → 样本外回放 {'='*26}")
    leg_f = lambda legs: "×".join(f"{a}{nm_of(CHAIN_NM[a], r)}" for a, r in legs) or "链不限"
    all_hits_te = []
    for fam in FAMILY_ORDER:
        items = grouped[fam]
        if not items:
            print(f"\n—— {fam}系: 训练窗无幸存格")
            continue
        items.sort(key=lambda x: -score(x[4]))
        pool, legs, trw, inc, m2 = items[0]

        def build_mask(df):
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
        mte = build_mask(te)
        mtr = build_mask(tr)
        sub_te = te[mte]
        sub_tr = tr[mtr]
        # 训练格含池过滤(重算: 只留当初池)——grouped 没存池, 用近似: 样本外全池回放并注明
        n_te = len(sub_te)
        yrs = {int(y): g["E3%"].sum() for y, g in sub_te.groupby("年")}
        yr_txt = " ".join(f"{y:+.0f}" for y, yv in sorted(yrs.items()))
        inc_txt = "·".join(f"{a}{nm}" for a, nm in inc) or "—"
        print(f"\n—— {fam}系新口诀: {pool}|链{leg_f(legs)}|今开{nm_of(TODAY_NM, trw)}|{inc_txt}")
        print(f"    训练窗: {len(sub_tr)}笔 均{sub_tr['E3%'].mean():+.1f} 胜{(sub_tr['E3%'] > 0).mean():.0%}")
        if n_te == 0:
            print("    样本外: 0笔(形态消失)")
            continue
        print(f"    样本外: {n_te}笔 均{sub_te['E3%'].mean():+.1f} 胜{(sub_te['E3%'] > 0).mean():.0%}"
              f" 和{sub_te['E3%'].sum():+.1f} | 分年 {yr_txt}")
        trim = sub_te["E3%"].drop(sub_te["E3%"].nlargest(3).index).mean() if n_te > 3 else sub_te["E3%"].mean()
        print(f"    剔3: {trim:+.1f} | 近12月均: "
              f"{sub_te[sub_te['月'] >= sorted(test_m)[-12]]['E3%'].mean():+.1f}"
              if len(sub_te[sub_te['月'] >= sorted(test_m)[-12]]) else "    近12月无票")
        all_hits_te.append(sub_te)

    if all_hits_te:
        union_te = pd.concat(all_hits_te)
        union_te = union_te.drop_duplicates(subset=["代码", "买入日"])
        print(f"\n{'='*26} 五类新口诀并集(样本外总账) {'='*26}")
        print(f"{len(union_te)}笔 胜{(union_te['E3%'] > 0).mean():.0%} "
              f"均{union_te['E3%'].mean():+.2f} 和{union_te['E3%'].sum():+.1f} "
              f"月均{len(union_te) / (len(test_m)):.1f}笔")
        yr_u = union_te.groupby("年")["E3%"].agg(["count", "sum"])
        print(yr_u.to_string())
        # 对照: 现役强市组同段
        cur = te[te["s_no"].notna()].drop_duplicates(subset=["代码", "买入日"])
        print(f"对照现役强市组同段: {len(cur)}笔 胜{(cur['E3%'] > 0).mean():.0%} "
              f"均{cur['E3%'].mean():+.2f} 和{cur['E3%'].sum():+.1f}")


def main() -> None:
    E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()]
    E = E[E["四组"].isin(LIVE_POOLS)].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    # 场景1: 切换前夜(信息边界考验) / 场景2: 切换后15月(新王确认考验)
    run(E, "2023-08")
    run(E, "2024-12")


main()
