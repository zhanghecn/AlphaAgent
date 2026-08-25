"""A 急仓上影线研究: 限制昨日(T-1)上影线能否提高连板率 / D+1 收益 / 胜率.

问题(用户 2026-08-25): v6.1 A 类池内, T-1 上影线长(冲高回落/上方抛压重)的票
是否次日动能弱? 扫描上影线切点, 找训练/验证双段同向的过滤带.

口径 = 产品 build_events()(单一口径来源, 不复制管线).
上影线三口径:
  ushadow_pct   相对昨收% = (T-1高 - max(T-1开, T-1收)) / T-2收 × 100  (主口径, 同花顺可表达)
  ushadow_self  自归一%   = (T-1高 - max(T-1开, T-1收)) / T-1收 × 100  (对照)
  ushadow_amp   占振幅    = (T-1高 - max(开,收)) / (T-1高 - T-1低)      (对照, 高=低时置 NaN)
T-2 收盘由 close_tm1/(1+chg_tm1/100) 反推——change_pct 已回填推导值, 反推无损.
研究对象 = A 类(chassis_tag ∈ A/AB); B 类同表打印作对照(确认因子是否 A 特异).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/app")
from alphaagent.server.services.qianlong.backtest import build_events  # noqa: E402

W_D1_MIN = 0.05  # 好票 D+1 溢价阈值(与 fb_winner_loser 同口径)

# 上影线主口径分箱边(百分数): 冲高几分钱到炸板深影
BINS_PCT = [-0.01, 0.5, 1.5, 2.5, 3.5, 5, 7, 99]
BINS_SELF = [-0.01, 0.5, 1.5, 2.5, 3.5, 5, 7, 99]
BINS_AMP = [-0.01, 0.1, 0.25, 0.4, 0.55, 0.7, 1.01]


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}"


def _bucket_stats(df: pd.DataFrame) -> dict[str, float]:
    """n/连板率/封板率/D+1均/均收/胜率/W%/L%/均D-1涨幅(防混杂). 小样本也出均值."""
    n = len(df)
    if n == 0:
        return {"n": 0}
    d1 = df["d1_ret"].dropna()
    return {
        "n": n,
        "连板%": round(float((df["streak_k"] >= 2).mean()) * 100, 1),
        "封板%": round(float(df["sealed"].mean()) * 100, 1),
        "D+1均%": round(float(d1.mean()) * 100, 2) if len(d1) else np.nan,
        "均收%": round(float(df["ret"].mean()) * 100, 2),
        "胜率%": round(float((df["ret"] > 0).mean()) * 100, 1),
        "W%": round(float(df["W"].mean()) * 100, 1),
        "L%": round(float(df["L"].mean()) * 100, 1),
        "均D1涨%": round(float(df["change_pct_tm1"].mean()), 2),
    }


def _print_bucket_table(ev: pd.DataFrame, col: str, bins: list[float],
                        fmt=_fmt_pct) -> None:
    binned = pd.cut(ev[col], bins)
    print(f"\n--- {col} 分桶 (基线在表头) ---")
    base = _bucket_stats(ev)
    print(f"{'区间':<14}{'n':>6}{'连板%':>7}{'封板%':>7}{'D+1均':>8}{'均收':>8}"
          f"{'胜率':>7}{'W%':>7}{'L%':>7}{'均D1涨':>8}"
          f"{'| 验n':>7}{'验连板':>7}{'验D+1':>8}{'验均收':>8}{'验胜率':>7}")
    print(f"{'(全体)':<14}{base['n']:>6}{base['连板%']:>7.1f}{base['封板%']:>7.1f}"
          f"{base['D+1均%']:>8.2f}{base['均收%']:>8.2f}{base['胜率%']:>7.1f}"
          f"{base['W%']:>7.1f}{base['L%']:>7.1f}{base['均D1涨%']:>8.2f}")
    for iv, gdf in ev.groupby(binned, observed=True):
        s = _bucket_stats(gdf)
        v = _bucket_stats(gdf[~gdf.is_train])
        if s["n"] == 0:
            continue
        rng = f"({fmt(iv.left)},{fmt(iv.right)}]"
        vstr = (f"{v['n']:>7}{v['连板%']:>7.1f}{v['D+1均%']:>8.2f}"
                f"{v['均收%']:>8.2f}{v['胜率%']:>7.1f}") if v["n"] else (
                f"{0:>7}{'--':>7}{'--':>8}{'--':>8}{'--':>7}")
        print(f"{rng:<14}{s['n']:>6}{s['连板%']:>7.1f}{s['封板%']:>7.1f}"
              f"{s['D+1均%']:>8.2f}{s['均收%']:>8.2f}{s['胜率%']:>7.1f}"
              f"{s['W%']:>7.1f}{s['L%']:>7.1f}{s['均D1涨%']:>8.2f}{vstr}")


def main() -> None:
    pd.set_option("display.width", 220)
    ev = build_events()
    ev["d1_ret"] = ev["open_p1"] / ev["entry"] - 1
    ev["W"] = (ev["streak_k"] >= 2) | (ev["d1_ret"] >= W_D1_MIN)
    ev["L"] = (~ev["sealed"]) & (ev["d1_ret"] < 0)

    # 上影线三口径
    top_tm1 = np.maximum(ev["open_price_tm1"], ev["close_price_tm1"])
    raw_shadow = ev["high_price_tm1"] - top_tm1
    close_tm2 = ev["close_price_tm1"] / (1 + ev["change_pct_tm1"] / 100)
    ev["ushadow_pct"] = raw_shadow / close_tm2 * 100
    ev["ushadow_self"] = raw_shadow / ev["close_price_tm1"] * 100
    rng_tm1 = ev["high_price_tm1"] - ev["low_price_tm1"]
    ev["ushadow_amp"] = np.where(rng_tm1 > 0, raw_shadow / rng_tm1, np.nan)

    a = ev[ev["chassis_tag"].isin(["A", "AB"])].copy()
    b = ev[ev["chassis_tag"].isin(["B", "AB"])].copy()
    b_only = ev[ev["chassis_tag"] == "B"].copy()
    print("=" * 110)
    print(f"事件总数 {len(ev)}   A类(含AB) {len(a)}   B类(含AB) {len(b)}   纯B {len(b_only)}")
    print(f"好票 W = 连板 或 D+1>=+{W_D1_MIN * 100:.0f}%   差票 L = 炸板且D+1<0")
    print("=" * 110)

    # ── [0] 上影线分布 ──
    print("\n[0] A类 上影线分布分位数(相对昨收%):")
    qs = a["ushadow_pct"].quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    print("  " + "  ".join(f"p{int(q * 100)}={v:.2f}" for q, v in qs.items()))
    print(f"  上影=0(光头/收最高) 占比 {(a['ushadow_pct'] <= 1e-9).mean() * 100:.1f}%   "
          f"NaN 占比 {a['ushadow_pct'].isna().mean() * 100:.2f}%")

    # ── [1] 三口径分桶(全 A 类) ──
    print(f"\n[1] A类 上影线三口径分桶 (基线: {_bucket_stats(a)})")
    _print_bucket_table(a, "ushadow_pct", BINS_PCT)
    _print_bucket_table(a, "ushadow_self", BINS_SELF)
    _print_bucket_table(a, "ushadow_amp", BINS_AMP, fmt=lambda v: f"{v:.2f}")

    # ── [1b] 纯 B 对照 ──
    print("\n[1b] 纯B类 对照(主口径, 确认因子是否 A 特异):")
    _print_bucket_table(b_only, "ushadow_pct", BINS_PCT)

    # ── [2] AUC ──
    print("\n[2] AUC(W好票 vs L差票; <0.5 = 低值偏好票 → 限上影有理)")
    for tag, sub in [("A类", a), ("纯B", b_only)]:
        for seg_name, seg in [("全期", sub), ("验证", sub[~sub.is_train])]:
            wl = seg[seg["W"] | seg["L"]]
            w_vals = wl.loc[wl["W"], "ushadow_pct"].dropna()
            l_vals = wl.loc[wl["L"], "ushadow_pct"].dropna()
            if len(w_vals) < 10 or len(l_vals) < 10:
                print(f"{tag:<5}{seg_name:<4} 样本不足(W{len(w_vals)}/L{len(l_vals)})")
                continue
            ranks = pd.concat([w_vals, l_vals]).rank()
            auc = (ranks.iloc[:len(w_vals)].sum()
                   - len(w_vals) * (len(w_vals) + 1) / 2) / (len(w_vals) * len(l_vals))
            print(f"{tag:<5}{seg_name:<4} ushadow_pct AUC = {auc:.3f}  (W{len(w_vals)}/L{len(l_vals)})")

    # ── [3] 切点扫描: 剔除「上影线 ≥ X」──
    print("\n[3] 切点扫描(A类): 规则 = T-1上影线(相对昨收%) ≥ X 剔除")
    print("    报告保留池变化: n/均收/胜率/连板率/正月率 × 训练/验证")
    total_w, total_l = a["W"].sum(), a["L"].sum()
    a_v = a[~a.is_train]
    total_w_v, total_l_v = a_v["W"].sum(), a_v["L"].sum()
    base_a = _bucket_stats(a)
    base_a_v = _bucket_stats(a_v)

    def _pos_month_rate(df: pd.DataFrame) -> float:
        if not len(df):
            return np.nan
        m = df.groupby(df.trade_date.dt.to_period("M"))["ret"].mean()
        return float((m > 0).mean() * 100)

    print(f"{'切点':>6}{'移除n':>7}{'杀伤%':>7}{'误伤%':>7}"
          f"{'| 剩n':>7}{'剩均收':>8}{'剩胜率':>8}{'剩连板':>8}{'剩正月':>8}"
          f"{'| 验剩n':>8}{'验均收':>8}{'验胜率':>8}{'验连板':>8}{'验正月':>8}")
    print(f"{'基线':>6}{'':>7}{'':>7}{'':>7}"
          f"{base_a['n']:>7}{base_a['均收%']:>8.2f}{base_a['胜率%']:>8.1f}"
          f"{base_a['连板%']:>8.1f}{_pos_month_rate(a):>8.0f}"
          f"{base_a_v['n']:>8}{base_a_v['均收%']:>8.2f}{base_a_v['胜率%']:>8.1f}"
          f"{base_a_v['连板%']:>8.1f}{_pos_month_rate(a_v):>8.0f}")
    for cut in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0]:
        mask = (a["ushadow_pct"] >= cut).fillna(False)
        rm, keep = a[mask], a[~mask]
        keep_v = keep[~keep.is_train]
        if len(keep) == 0:
            continue
        s, sv = _bucket_stats(keep), _bucket_stats(keep_v)
        kill = rm["L"].sum() / total_l * 100
        coll = rm["W"].sum() / total_w * 100
        print(f"{cut:>6.1f}{len(rm):>7}{kill:>7.1f}{coll:>7.1f}"
              f"{s['n']:>7}{s['均收%']:>8.2f}{s['胜率%']:>8.1f}{s['连板%']:>8.1f}"
              f"{_pos_month_rate(keep):>8.0f}"
              f"{sv['n']:>8}{sv['均收%']:>8.2f}{sv['胜率%']:>8.1f}{sv['连板%']:>8.1f}"
              f"{_pos_month_rate(keep_v):>8.0f}")

    # ── [4] 混杂检查: 控制D-1涨幅带上影线是否独立 ──
    print("\n[4] 混杂检查: 按D-1涨幅分层后, 上影线≥3 的稀释是否仍在")
    for lo, hi in [(-6, -2), (-2, 0), (0, 2), (2, 4), (4, 7)]:
        layer = a[(a["change_pct_tm1"] > lo) & (a["change_pct_tm1"] <= hi)]
        if len(layer) < 30:
            print(f"  D1涨({lo},{hi}]: n={len(layer)} 样本不足")
            continue
        hi_s = layer[layer["ushadow_pct"] >= 3]
        lo_s = layer[layer["ushadow_pct"] < 3]
        h, l_ = _bucket_stats(hi_s), _bucket_stats(lo_s)
        hv, lv = _bucket_stats(hi_s[~hi_s.is_train]), _bucket_stats(lo_s[~lo_s.is_train])
        print(f"  D1涨({lo:>3},{hi:>3}]: 影≥3 n={h['n']:>4} 均{h['均收%']:>6.2f} "
              f"连板{h['连板%']:>5.1f} | 影<3 n={l_['n']:>4} 均{l_['均收%']:>6.2f} "
              f"连板{l_['连板%']:>5.1f} || 验: {hv['均收%'] if hv['n'] else '--':>6} "
              f"vs {lv['均收%'] if lv['n'] else '--':>6}")

    # ── [5] 候选切点逐月稳定性(均收为负的月数对比) ──
    print("\n[5] 最优候选(按扫描结果人工选)逐月对比: 上影线切点将打在此节之后")


if __name__ == "__main__":
    main()
