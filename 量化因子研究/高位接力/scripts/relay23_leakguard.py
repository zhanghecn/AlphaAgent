# -*- coding: utf-8 -*-
"""口诀组选择·第三轮: 漏肉保护参数高原+逐票点名(宿主机: uv run python relay23_leakguard.py)。

第二轮结论: 「未启用组近3月命中≥3笔且均值>X→当月双开」的漏肉保护是唯一
真实改进(X=8: +32.6, 逐年不差于基线; X=5: +44.7但2026年少5.2点)。
本轮:
  1. 参数高原: 窗{2,3,4,6}×笔数{2,3,4}×均值{3,5,8,10}全网格——高原才算数
  2. 最优档触发月份明细+多打/漏打票逐票点名(主人纪律)
  3. 反向「毒票保护」: 启用组近3月均<0→当月空仓, 测是否再加一层
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 260)


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


def st_base(months, s_rs, w_rs, window=12, min_n=8):
    """现状基线(v7.8口径)。"""
    out = {}
    for i, m in enumerate(months):
        ms = set(months[max(0, i - window):i])
        wk = [r for mo in ms for r in w_rs.get(mo, [])]
        st = [r for mo in ms for r in s_rs.get(mo, [])]
        wa = sum(wk) / len(wk) if wk else None
        sa = sum(st) / len(st) if st else None
        if len(wk) >= min_n and len(st) >= min_n:
            out[m] = "weak" if wa > sa else "strong"
        elif len(wk) >= min_n and wa > 0:
            out[m] = "weak"
        elif len(st) >= min_n and sa > 0:
            out[m] = "strong"
        else:
            out[m] = "both"
    return out


def leak_guard(months, s_rs, w_rs, base, g_win=3, g_n=3, g_avg=8.0,
               toxic_stop=False):
    """漏肉保护: 未启用组近g_win月命中≥g_n笔且均值>g_avg→当月双开。
    toxic_stop: 加一层毒票保护(启用组近g_win月≥g_n笔且均值<0→当月空仓)。"""
    out = {}
    for i, m in enumerate(months):
        st = base[m]
        ms = set(months[max(0, i - g_win):i])
        if st in ("strong", "weak"):
            sub = w_rs if st == "strong" else s_rs
            rs = [r for mo in ms for r in sub.get(mo, [])]
            if len(rs) >= g_n and sum(rs) / len(rs) > g_avg:
                st = "both"
            elif toxic_stop:
                cur = s_rs if st == "strong" else w_rs
                crs = [r for mo in ms for r in cur.get(mo, [])]
                if len(crs) >= g_n and sum(crs) / len(crs) < 0:
                    st = "none"
        out[m] = st
    return out


def simulate(E, states):
    rows = []
    for m, st in states.items():
        g = E[E["月"] == m]
        if st == "strong":
            rows.append(g[g["s_no"].notna()])
        elif st == "weak":
            rows.append(g[g["w_no"].notna()])
        elif st == "both":
            rows.append(g[g["s_no"].notna() | g["w_no"].notna()])
    return pd.concat(rows) if rows else E.iloc[0:0]


def ev(name, t):
    e3 = t["E3%"].dropna()
    yr = {int(y): g["E3%"].sum() for y, g in t.groupby("年")}
    return dict(name=name, n=len(t), avg=e3.mean(), total=e3.sum(), yr=yr)


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E = E[E["E3%"].notna()].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    months = sorted(E["月"].unique())
    hit_w = E["w_no"].notna()
    s_rs = {m: g["E3%"].tolist() for m, g in E[E["s_no"].notna() & E["w_no"].isna()].groupby("月")}
    w_rs = {m: g["E3%"].tolist() for m, g in E[hit_w].groupby("月")}

    base_states = st_base(months, s_rs, w_rs)
    base = simulate(E, base_states)
    rb = ev("基线", base)
    print(f"基线: {rb['n']}笔 均{rb['avg']:+.2f} 和{rb['total']:+.1f}")

    # ---- 1. 参数高原网格 ----
    print("\n" + "=" * 26, "漏肉保护参数高原(Δ=对基线总和差)", "=" * 26)
    print(f"{'窗\\笔\\均':<10s}" + "".join(f"{a:>8.0f}" for a in (3, 5, 8, 10)))
    grid = {}
    for gw in (2, 3, 4, 6):
        for gn in (2, 3, 4):
            row = []
            for ga in (3.0, 5.0, 8.0, 10.0):
                st = leak_guard(months, s_rs, w_rs, base_states, gw, gn, ga)
                r = ev("", simulate(E, st))
                neg = [y for y in range(2020, 2027)
                       if r["yr"].get(y, 0) < rb["yr"].get(y, 0) - 1e-9]
                grid[(gw, gn, ga)] = (r, neg)
                row.append(f"{r['total'] - rb['total']:+5.1f}{'↓' if neg else ' '}")
            print(f"窗{gw}月 笔{gn:<3d}" + "".join(f"{c:>8s}" for c in row))
    print("(↓=存在比基线差的年份)")

    # ---- 2. 代表档逐年 ----
    print("\n—— 代表档分年和(2020~2026) ——")
    for gw, gn, ga in ((3, 3, 5.0), (3, 3, 8.0), (2, 3, 8.0), (4, 3, 8.0), (6, 3, 8.0), (3, 2, 8.0)):
        st = leak_guard(months, s_rs, w_rs, base_states, gw, gn, ga)
        t = simulate(E, st)
        r = ev(f"窗{gw}笔{gn}均{ga}", t)
        yrs = " ".join(f"{r['yr'].get(y, 0):+6.1f}" for y in range(2020, 2027))
        print(f"  窗{gw}笔{gn}均{ga:<4.0f}: {r['n']:3d}笔 均{r['avg']:+6.2f} 和{r['total']:+7.1f} | {yrs}")
    print(f"  基线{'':<7s}: {rb['n']:3d}笔 均{rb['avg']:+6.2f} 和{rb['total']:+7.1f} | "
          + " ".join(f"{rb['yr'].get(y, 0):+6.1f}" for y in range(2020, 2027)))

    # ---- 3. 毒票保护叠加 ----
    print("\n—— 叠加毒票保护(启用组近3月<0→空仓) ——")
    for ga in (5.0, 8.0):
        st = leak_guard(months, s_rs, w_rs, base_states, 3, 3, ga, toxic_stop=True)
        t = simulate(E, st)
        r = ev("", t)
        none_months = [m for m, s in st.items() if s == "none"]
        yrs = " ".join(f"{r['yr'].get(y, 0):+6.1f}" for y in range(2020, 2027))
        print(f"  漏肉{ga}+毒票保护: {r['n']:3d}笔 和{r['total']:+7.1f} | {yrs} | 空仓月:{none_months}")

    # ---- 4. 最优档逐票点名(漏肉窗3笔3均8 vs 基线) ----
    print("\n" + "=" * 26, "漏肉保护(窗3笔3均8) vs 基线: 差异逐票点名", "=" * 26)
    st8 = leak_guard(months, s_rs, w_rs, base_states, 3, 3, 8.0)
    t8 = simulate(E, st8)
    key = lambda d: set(zip(d["代码"], d["买入日"].astype(str)))
    added = t8[~t8.apply(lambda r: (r["代码"], str(r["买入日"])) in key(base), axis=1)]
    dropped = base[~base.apply(lambda r: (r["代码"], str(r["买入日"])) in key(t8), axis=1)]
    trig = [m for m in months if st8[m] != base_states[m]]
    print(f"状态不同月 {len(trig)} 个: {trig}")
    print(f"\n多打 {len(added)} 笔(漏肉保护救回):")
    for _, r in added.sort_values("买入日").iterrows():
        tag = r["s_no"] if pd.notna(r["s_no"]) else r["w_no"]
        print(f"  {str(r['买入日'])[:10]} {r['代码']} {r['名称']:<8s} {tag:>3s} "
              f"E3={r['E3%']:+6.1f} (当月状态 {base_states[str(r['月'])]}→both)")
    print(f"\n少打 {len(dropped)} 笔:")
    for _, r in dropped.sort_values("买入日").iterrows():
        print(f"  {str(r['买入日'])[:10]} {r['代码']} {r['名称']:<8s} E3={r['E3%']:+6.1f}")
    print(f"\n多打票合计 E3: {added['E3%'].sum():+.1f} | 少打票合计: {dropped['E3%'].sum():+.1f}")

    # ---- 5. X=5档的2026年差异票(为何比基线少5.2点) ----
    st5 = leak_guard(months, s_rs, w_rs, base_states, 3, 3, 5.0)
    t5 = simulate(E, st5)
    add5 = t5[~t5.apply(lambda r: (r["代码"], str(r["买入日"])) in key(base), axis=1)]
    a26 = add5[add5["年"] == 2026]
    print(f"\nX=5档2026年多打票(该档2026年比基线少5.2点的来源):")
    for _, r in a26.sort_values("买入日").iterrows():
        print(f"  {str(r['买入日'])[:10]} {r['代码']} {r['名称']:<8s} E3={r['E3%']:+6.1f}")


main()
