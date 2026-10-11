# -*- coding: utf-8 -*-
"""口诀组自动选择算法穷举(宿主机: uv run python relay23_groupselect.py)。

任务(主人2026-10-10): 优化口诀自动提取——弱市组/强市组的选用算法穷举,
验证「2023年混合口诀最好」说法, 找保证每年最大化用最佳口诀的算法。

现有机制(v7.8口径基线): 每月末按近12交易月(不含当月)两组各自命中票
E3均值高者整组启用; 组样本<8笔或均非正→双开(both=两组任一命中都打)。

穷举族:
  A 组级硬切换: 窗口{6,9,12,15,18,24}×判据{均值,胜率,总和,中位,剔Top3}
    ×门槛{5,8,12} + 滞后确认/阈值带/模糊带双开/指数衰减/空仓态
  B 混合: 全开并集/交集/双命中豁免/副组高门槛放行
  C 票级: 口诀级滚动启用/票级择优(单命中要求该组近12月为正)

全程无未来函数: 判m月只用m之前的数据。评估: n/E3均/胜率/总和/最大回撤/
切换次数/分年一致性。基线须复现207笔+9.34。
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
    """一笔票分别打强市/弱市组标, 返回(强市口诀号|None, 弱市口诀号|None)。"""
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


# ---------------- 状态判定算法 ----------------
# 输入: 月度序列 months, 每月两组命中票的收益列表 s_rs[m]/w_rs[m]
# 输出: {月: 状态} 状态 ∈ strong/weak/both/none

def st_group(months, s_rs, w_rs, window=12, metric="avg", min_n=8,
             lag=1, band=0.0, fuzzy=None, half_life=None, stop0=False):
    """组级硬切换通用机。fuzzy=δ: |两组均值差|<δ→both; band=X: 挑战组须超现任X点才切;
    lag=2: 连续2月挑战成功才切; half_life: 指数衰减加权(月); stop0: 两组均非正→none。"""
    out, cur, win_streak = {}, "both", 0

    def agg(rs):
        if not rs:
            return None, 0
        if half_life:  # 指数衰减: 越近的月权重越大
            vals, wts = [], []
            k = math.log(2) / half_life
            for j, (mo, r) in enumerate(rs):
                vals.append(r)
                wts.append(math.exp(-k * (len(rs) - 1 - j)))
            sw = sum(wts)
            return sum(v * w for v, w in zip(vals, wts)) / sw, len(vals)
        vals = [r for _, r in rs]
        if metric == "avg":
            return sum(vals) / len(vals), len(vals)
        if metric == "win":
            return sum(1 for v in vals if v > 0) / len(vals), len(vals)
        if metric == "sum":
            return sum(vals), len(vals)
        if metric == "med":
            vs = sorted(vals)
            return vs[len(vs) // 2] if len(vs) % 2 else (vs[len(vs) // 2 - 1] + vs[len(vs) // 2]) / 2, len(vals)
        if metric == "trim":  # 剔Top3均值
            vs = sorted(vals)[:-3] if len(vals) > 3 else vals
            return sum(vs) / len(vs), len(vals)
        raise ValueError(metric)

    for i, m in enumerate(months):
        ms = set(months[max(0, i - window):i])
        s_hist = [(mo, r) for mo in ms for r in s_rs.get(mo, [])]
        w_hist = [(mo, r) for mo in ms for r in w_rs.get(mo, [])]
        sa, sn = agg(s_hist)
        wa, wn = agg(w_hist)
        if sn >= min_n and wn >= min_n:
            chal = "weak" if wa > sa else "strong"
            if fuzzy is not None and abs(wa - sa) < fuzzy:
                nxt = "both"
            elif stop0 and sa <= 0 and wa <= 0:
                nxt = "none"
            elif band and cur in ("strong", "weak") and chal != cur:
                cur_v, ch_v = (sa, wa) if cur == "strong" else (wa, sa)
                nxt = chal if ch_v > cur_v + band else cur
            elif lag >= 2 and cur in ("strong", "weak") and chal != cur:
                win_streak = win_streak + 1 if getattr(st_group, "_pc", None) == chal else 1
                st_group._pc = chal
                nxt = chal if win_streak >= lag else cur
                if nxt != chal:
                    out[m] = cur
                    continue
            else:
                nxt = chal
                win_streak = 0
        elif wn >= min_n and wa is not None and wa > 0:
            nxt = "weak"
            win_streak = 0
        elif sn >= min_n and sa is not None and sa > 0:
            nxt = "strong"
            win_streak = 0
        else:
            nxt = "both" if not stop0 else ("none" if (sa or 0) <= 0 and (wa or 0) <= 0 and (sn + wn) > 0 else "both")
            win_streak = 0
        out[m] = nxt
        cur = nxt
    return out


# ---------------- 评估 ----------------

def simulate(df, states):
    """按月状态过滤成交, 返回出手df。both=并集去重, none=空仓。"""
    rows = []
    for m, st in states.items():
        g = df[df["月"] == m]
        if st == "strong":
            rows.append(g[g["s_no"].notna()])
        elif st == "weak":
            rows.append(g[g["w_no"].notna()])
        elif st == "both":
            rows.append(g[g["s_no"].notna() | g["w_no"].notna()])
    return pd.concat(rows) if rows else df.iloc[0:0]


def evaluate(name, trades, months_all, show=False):
    e3 = trades["E3%"].dropna()
    if not len(trades):
        print(f"{name:<28s} 0笔")
        return None
    seq = trades.sort_values("买入日")["E3%"].tolist()
    peak, mdd, cum = 0.0, 0.0, 0.0
    for v in seq:
        cum += v
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    yr = trades.groupby("年")["E3%"].agg(["size", "sum", "mean"])
    yr_sum = {int(y): yr.loc[y, "sum"] for y in yr.index}
    neg_years = [y for y in range(2020, 2027) if yr_sum.get(y, 0) < 0]
    n_switch = "—"
    r = dict(name=name, n=len(trades), avg=e3.mean(), win=(e3 > 0).mean() * 100,
             total=e3.sum(), mdd=mdd, yr=yr_sum, neg=neg_years)
    if show:
        print(f"{name:<28s} {r['n']:4d}笔 均{r['avg']:+6.2f} 胜{r['win']:3.0f}% "
              f"和{r['total']:+7.1f} 回撤{r['mdd']:6.1f} 负年{r['neg'] or '无'}")
    return r


def yearly_str(trades):
    return " ".join(f"{y}:{g['E3%'].sum():+6.1f}/{len(g)}笔"
                    for y, g in trades.groupby("年"))


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E = E[E["E3%"].notna()].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    print(f"事件 {len(E)} 笔 {E['月'].min()}~{E['月'].max()}")

    # 两组分别打标
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    both = E["s_no"].notna() & E["w_no"].notna()
    print(f"强市组命中 {E['s_no'].notna().sum()} 笔 | 弱市组命中 {E['w_no'].notna().sum()} 笔 "
          f"| 双命中 {both.sum()} 笔 | 并集 {(E['s_no'].notna() | E['w_no'].notna()).sum()} 笔")
    if both.sum():
        bb = E[both]
        print(f"  双命中组合: {(bb['s_no'] + '×' + bb['w_no']).value_counts().to_dict()}")
        print(f"  双命中票表现: 均{bb['E3%'].mean():+.2f} 胜{(bb['E3%'] > 0).mean() * 100:.0f}%")

    months = sorted(E["月"].unique())
    # 产品口径(v7.0轻表): 双命中票状态统计归弱市组(窄格先拿);
    # 成交口径不变(strong月照样打双命中票, 见simulate)
    hit_w = E["w_no"].notna()
    hit_s_pure = E["s_no"].notna() & E["w_no"].isna()
    s_rs = {m: g["E3%"].tolist() for m, g in E[hit_s_pure].groupby("月")}
    w_rs = {m: g["E3%"].tolist() for m, g in E[hit_w].groupby("月")}

    # ---- 基线复现 ----
    print("\n" + "=" * 30, "基线复现校验", "=" * 30)
    base_states = st_group(months, s_rs, w_rs)
    base = simulate(E, base_states)
    evaluate("基线(W12均值min8=现状)", base, months, show=True)
    sw = pd.Series(base_states)
    changes = sw[sw != sw.shift()].iloc[1:]
    print("切换史:", {m: s for m, s in changes.items()})

    # ---- A族 组级硬切换变体 ----
    print("\n" + "=" * 30, "A族 组级硬切换", "=" * 30)
    results = {"基线W12均值n8": evaluate("基线W12均值n8(现状)", base, months)}
    cands = {}
    for w in (6, 9, 15, 18, 24):
        cands[f"A窗{w}"] = st_group(months, s_rs, w_rs, window=w)
    for mt in ("win", "sum", "med", "trim"):
        cands[f"A判据{mt}"] = st_group(months, s_rs, w_rs, metric=mt)
    for n in (5, 12):
        cands[f"A门槛{n}"] = st_group(months, s_rs, w_rs, min_n=n)
    cands["A滞后2月确认"] = st_group(months, s_rs, w_rs, lag=2)
    cands["A阈值带2点"] = st_group(months, s_rs, w_rs, band=2.0)
    cands["A模糊带2双开"] = st_group(months, s_rs, w_rs, fuzzy=2.0)
    cands["A模糊带3双开"] = st_group(months, s_rs, w_rs, fuzzy=3.0)
    cands["A衰减hl6"] = st_group(months, s_rs, w_rs, half_life=6)
    cands["A衰减hl3"] = st_group(months, s_rs, w_rs, half_life=3)
    cands["A空仓态"] = st_group(months, s_rs, w_rs, stop0=True)
    # 第二轮: trim判据稳健性(窗×门槛×模糊带) + 针对2023机理的切换加速
    for w in (9, 15):
        cands[f"A判据trim窗{w}"] = st_group(months, s_rs, w_rs, window=w, metric="trim")
    cands["A判据trim门槛5"] = st_group(months, s_rs, w_rs, metric="trim", min_n=5)
    cands["A判据trim模糊带2"] = st_group(months, s_rs, w_rs, metric="trim", fuzzy=2.0)
    for nm, st in cands.items():
        t = simulate(E, st)
        swx = pd.Series(st)
        nsw = int((swx != swx.shift()).sum() - 1)
        r = evaluate(nm, t, months)
        if r:
            r["switch"] = nsw
            results[nm] = r

    # ---- B族 混合 ----
    print("\n" + "=" * 30, "B族 混合", "=" * 30)
    # B6 双窗加速: 主判同基线(W12均值); 挑战组近6月与近12月均值双超现任→立即切
    def dual_win(months, s_rs, w_rs, w_long=12, w_short=6, min_n=8, short_n=3):
        out, cur = {}, "both"
        for i, m in enumerate(months):
            def avg(g_rs, w_):
                ms = set(months[max(0, i - w_):i])
                rs = [r for mo in ms for r in g_rs.get(mo, [])]
                return (sum(rs) / len(rs) if rs else None), len(rs)
            sa, sn = avg(s_rs, w_long)
            wa, wn = avg(w_rs, w_long)
            sa6, sn6 = avg(s_rs, w_short)
            wa6, wn6 = avg(w_rs, w_short)
            if sn >= min_n and wn >= min_n:
                chal = "weak" if wa > sa else "strong"
                if cur in ("strong", "weak") and chal != cur:
                    ca6, cu6 = (wa6, sa6) if chal == "weak" else (sa6, wa6)
                    cn6 = wn6 if chal == "weak" else sn6
                    if ca6 is not None and cu6 is not None and cn6 >= short_n and ca6 > cu6:
                        cur = chal      # 双窗一致 → 立即切
                elif cur == "both":
                    cur = chal
            elif wn >= min_n and wa and wa > 0:
                cur = "weak"
            elif sn >= min_n and sa and sa > 0:
                cur = "strong"
            else:
                cur = "both"
            out[m] = cur
        return out
    # B7 漏肉保护: 基线状态之上, 未启用组近3月命中≥3笔且均值>8 → 当月双开
    def leak_guard(months, s_rs, w_rs, base, g_n=3, g_avg=8.0):
        out = {}
        for i, m in enumerate(months):
            st = base[m]
            if st in ("strong", "weak"):
                g_rs = w_rs if st == "strong" else s_rs
                ms = set(months[max(0, i - 3):i])
                rs = [r for mo in ms for r in g_rs.get(mo, [])]
                if len(rs) >= g_n and sum(rs) / len(rs) > g_avg:
                    st = "both"
            out[m] = st
        return out
    cands2 = {"B双窗加速6+12": dual_win(months, s_rs, w_rs),
              "B双窗加速4+12": dual_win(months, s_rs, w_rs, w_short=4),
              "B漏肉保护3月>8": leak_guard(months, s_rs, w_rs, base_states),
              "B漏肉保护3月>5": leak_guard(months, s_rs, w_rs, base_states, g_avg=5.0),
              "B漏肉+trim": leak_guard(months, s_rs, w_rs,
                                       st_group(months, s_rs, w_rs, metric="trim"))}
    for nm, st in cands2.items():
        t = simulate(E, st)
        swx = pd.Series(st)
        r = evaluate(nm, t, months)
        if r:
            r["switch"] = int((swx != swx.shift()).sum() - 1)
            results[nm] = r

    open_all = E[E["s_no"].notna() | E["w_no"].notna()]
    results["B全开并集"] = evaluate("B全开并集(对照)", open_all, months)
    inter = E[both]
    results["B交集"] = evaluate("B交集(双命中才打)", inter, months)
    # 双命中豁免: 动态组成交 + 所有双命中票
    dual = pd.concat([base, E[both]]).drop_duplicates(subset=["代码", "买入日"])
    results["B基线+双命中豁免"] = evaluate("B基线+双命中豁免", dual, months)
    # 副组高门槛: 主组全打 + 副组票仅当副组近12月均>5
    sub_states = {}
    for i, m in enumerate(months):
        ms = set(months[max(0, i - 12):i])
        st_now = base_states[m]
        sub = "weak" if st_now == "strong" else "strong"
        rs = [r for mo in ms for r in (w_rs if sub == "weak" else s_rs).get(mo, [])]
        sub_states[m] = (st_now, sub if (len(rs) >= 5 and sum(rs) / len(rs) > 5) else None)
    rows = []
    for m, (main_g, sub_g) in sub_states.items():
        g = E[E["月"] == m]
        msk = g["s_no"].notna() if main_g == "strong" else g["w_no"].notna()
        if main_g == "both":
            msk = g["s_no"].notna() | g["w_no"].notna()
        if sub_g:
            msk = msk | (g["w_no"].notna() if sub_g == "weak" else g["s_no"].notna())
        rows.append(g[msk])
    results["B副组均值>5放行"] = evaluate("B副组均值>5放行", pd.concat(rows), months)

    # ---- C族 票级/口诀级 ----
    print("\n" + "=" * 30, "C族 票级/口诀级", "=" * 30)
    # C1 口诀级滚动: 每条口诀近12月均值>0才启用(两组13条独立)
    for w in (12, 24):
        point_rs = {}
        for _, r0 in E.iterrows():
            for no in (r0["s_no"], r0["w_no"]):
                if no:
                    point_rs.setdefault(no, {}).setdefault(r0["月"], []).append(r0["E3%"])
        rows = []
        for i, m in enumerate(months):
            ms = set(months[max(0, i - w):i])
            ok = set()
            for no, bym in point_rs.items():
                rs = [r for mo in ms for r in bym.get(mo, [])]
                if len(rs) >= 3 and sum(rs) / len(rs) > 0:
                    ok.add(no)
            g = E[E["月"] == m]
            rows.append(g[g["s_no"].isin(ok) | g["w_no"].isin(ok)])
        results[f"C口诀级滚动{w}月"] = evaluate(f"C口诀级滚动{w}月(均值>0)", pd.concat(rows), months)
    # C2 票级择优: 双命中都打; 单命中要求命中组近12月均值>0
    rows = []
    for i, m in enumerate(months):
        ms = set(months[max(0, i - 12):i])
        s_hist = [r for mo in ms for r in s_rs.get(mo, [])]
        w_hist = [r for mo in ms for r in w_rs.get(mo, [])]
        s_ok = len(s_hist) >= 3 and sum(s_hist) / len(s_hist) > 0
        w_ok = len(w_hist) >= 3 and sum(w_hist) / len(w_hist) > 0
        g = E[E["月"] == m]
        msk = ((g["s_no"].notna() & s_ok) | (g["w_no"].notna() & w_ok))
        rows.append(g[msk])
    results["C票级择优"] = evaluate("C票级择优(命中组近12月>0)", pd.concat(rows), months)

    # ---- 总表 ----
    print("\n" + "=" * 30, "算法总表(按E3总和排序)", "=" * 30)
    hdr = f"{'算法':<26s} {'笔数':>4s} {'均值':>7s} {'胜率':>4s} {'总和':>8s} {'回撤':>7s} {'切换':>3s}  分年和(2020~2026)"
    print(hdr)
    for nm, r in sorted(results.items(), key=lambda kv: -(kv[1]["total"] if kv[1] else -9e9)):
        if not r:
            continue
        yrs = " ".join(f"{r['yr'].get(y, 0):+6.1f}" for y in range(2020, 2027))
        sw = r.get("switch", "—")
        flag = " ⚠负年" + str(r["neg"]) if r["neg"] else ""
        print(f"{nm:<26s} {r['n']:4d} {r['avg']:+7.2f} {r['win']:3.0f}% {r['total']:+8.1f} "
              f"{r['mdd']:7.1f} {str(sw):>3s}  {yrs}{flag}")

    # ---- 2023专项: 验证「混合最好」 ----
    print("\n" + "=" * 30, "2023专项(主人: 2023实际混合最好?)", "=" * 30)
    y23 = E[E["年"] == 2023]
    s23 = y23[y23["s_no"].notna()]
    w23 = y23[y23["w_no"].notna()]
    u23 = y23[y23["s_no"].notna() | y23["w_no"].notna()]
    d23 = base[base["年"] == 2023]
    for nm, g in (("全年强市组", s23), ("全年弱市组", w23),
                  ("全年并集(混合)", u23), ("动态组(现状)", d23)):
        e3 = g["E3%"]
        print(f"  {nm:<12s} {len(g):3d}笔 均{e3.mean():+6.2f} 胜{(e3 > 0).mean() * 100:3.0f}% 和{e3.sum():+7.1f}")
    print("\n  2023逐月(强市组/弱市组各自命中表现, 现状启用):")
    for m in sorted(y23["月"].unique()):
        g = y23[y23["月"] == m]
        gs, gw = g[g["s_no"].notna()]["E3%"], g[g["w_no"].notna()]["E3%"]
        st = base_states[m]
        def ms(x):
            return f"{len(x)}笔{x.mean():+5.1f}" if len(x) else "  —  "
        print(f"    {m} [{st:>6s}] 强市组:{ms(gs)} | 弱市组:{ms(gw)}")


main()
