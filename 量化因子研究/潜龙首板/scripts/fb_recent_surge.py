"""近5日大阳因子: T-5..T-1 内出现过单日涨幅 >7% 的票, 是好依据还是坏依据.

问题(用户 2026-08-25): A/B 分开统计「前5个交易日内出现过涨幅>7%」的胜率/收益,
按涨幅档位划分; 若是反向依据则评估过滤价值(反向思考).

口径 = 产品 build_events()(单一口径来源); 特征(T-1 视角截断, 无前视):
  maxchg5_tm1     近5日(T-5..T-1)最大单日涨幅%
  bigcnt7_5tm1    近5日内 ≥7% 大阳天数
  lastbig7_off_tm1 距最近一次 ≥7% 大阳的交易日数(1=T-1 大阳, NaN=上市以来无)
注: A 类 D-1 带(-6,+7)已天然排除 T-1 大阳 → 本因子对 A 检验 T-2~T-5 存量动能;
   B 类无 D-1 带, T-1 大阳可进(B 的 10日涨幅<15% 允许单日 7%+).
分组与产品 A/B 卡对齐: A = A+AB, B = B+AB.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/app")
from alphaagent.server.services.qianlong.backtest import build_events  # noqa: E402

W_D1_MIN = 0.05

# 近5日最大单日涨幅分箱(百分数): 7 两侧细分, 验证 7 是不是真临界
BINS = [-99, 0, 3, 5, 6, 7, 8, 9, 11, 99]


def _stats(df: pd.DataFrame) -> dict[str, float]:
    """n/连板%/封板%/D+1均%/均收%/胜率%/W%/L%/均ret10. 小样本也出均值(主人规则)."""
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
        "均ret10": round(float(df["ret10_tm1"].mean()) * 100, 1),
    }


def _pos_month_rate(df: pd.DataFrame) -> float:
    if not len(df):
        return np.nan
    m = df.groupby(df.trade_date.dt.to_period("M"))["ret"].mean()
    return float((m > 0).mean() * 100)


def _bucket_table(sub: pd.DataFrame, col: str, bins: list[float],
                  label: str, fmt=lambda v: f"{v:.0f}") -> None:
    base = _stats(sub)
    print(f"\n--- [{label}] {col} 分桶 ---")
    print(f"{'区间':<12}{'n':>6}{'连板%':>7}{'封板%':>7}{'D+1均':>8}{'均收':>8}"
          f"{'胜率':>7}{'W%':>7}{'L%':>7}{'ret10':>7}"
          f"{'| 验n':>6}{'验均收':>8}{'验胜率':>7}{'验连板':>7}")
    print(f"{'(全体)':<12}{base['n']:>6}{base['连板%']:>7.1f}{base['封板%']:>7.1f}"
          f"{base['D+1均%']:>8.2f}{base['均收%']:>8.2f}{base['胜率%']:>7.1f}"
          f"{base['W%']:>7.1f}{base['L%']:>7.1f}{base['均ret10']:>7.1f}")
    binned = pd.cut(sub[col], bins)
    for iv, gdf in sub.groupby(binned, observed=True):
        s = _stats(gdf)
        if s["n"] == 0:
            continue
        v = gdf[~gdf.is_train]
        sv = _stats(v)
        vstr = (f"{sv['n']:>6}{sv['均收%']:>8.2f}{sv['胜率%']:>7.1f}{sv['连板%']:>7.1f}"
                if sv["n"] else f"{0:>6}{'--':>8}{'--':>7}{'--':>7}")
        print(f"({fmt(iv.left)},{fmt(iv.right)}]"
              f"{s['n']:>6}{s['连板%']:>7.1f}{s['封板%']:>7.1f}{s['D+1均%']:>8.2f}"
              f"{s['均收%']:>8.2f}{s['胜率%']:>7.1f}{s['W%']:>7.1f}{s['L%']:>7.1f}"
              f"{s['均ret10']:>7.1f}{vstr}")


def _keep_effect(sub: pd.DataFrame, mask: pd.Series, rule: str) -> None:
    """过滤视角: 剔除 mask 组后保留池变化 + 杀伤/误伤."""
    rm, keep = sub[mask], sub[~mask]
    keep_v = keep[~keep.is_train]
    rm_v = rm[~rm.is_train]
    s, sv = _stats(keep), _stats(keep_v)
    tot_l, tot_w = sub["L"].sum(), sub["W"].sum()
    kill = rm["L"].sum() / tot_l * 100 if tot_l else np.nan
    coll = rm["W"].sum() / tot_w * 100 if tot_w else np.nan
    print(f"{rule:<24}{len(rm):>6}{rm['ret'].mean() * 100 if len(rm) else np.nan:>8.2f}"
          f"{kill:>8.1f}{coll:>8.1f}"
          f"{s['n']:>7}{s['均收%']:>8.2f}{s['胜率%']:>8.1f}{s['连板%']:>8.1f}"
          f"{_pos_month_rate(keep):>7.0f}"
          f"{sv['n']:>7}{sv['均收%']:>8.2f}{sv['胜率%']:>8.1f}{sv['连板%']:>8.1f}"
          f"{_pos_month_rate(keep_v):>7.0f}")


def main() -> None:
    pd.set_option("display.width", 220)
    ev = build_events()
    ev["d1_ret"] = ev["open_p1"] / ev["entry"] - 1
    ev["W"] = (ev["streak_k"] >= 2) | (ev["d1_ret"] >= W_D1_MIN)
    ev["L"] = (~ev["sealed"]) & (ev["d1_ret"] < 0)

    groups = [("A类(含AB)", ev[ev["chassis_tag"].isin(["A", "AB"])]),
              ("B类(含AB)", ev[ev["chassis_tag"].isin(["B", "AB"])])]
    print("=" * 118)
    print(f"事件总数 {len(ev)}   " + "   ".join(f"{name} {len(g_)}" for name, g_ in groups))
    print(f"好票 W = 连板 或 D+1>=+{W_D1_MIN * 100:.0f}%   差票 L = 炸板且D+1<0")
    print("=" * 118)

    # ── [1] 近5日最大单日涨幅分桶(按档位划分, 主问题) ──
    print("\n[1] 近5日(T-5..T-1)最大单日涨幅% 分桶 —— 主表")
    for name, sub in groups:
        _bucket_table(sub, "maxchg5_tm1", BINS, name)

    # ── [2] 布尔切点扫描: 出现过 ≥c% 大阳 → 剔除的保留池效果 ──
    print("\n[2] 反向过滤扫描: 规则 = 近5日出现最大单日涨幅≥c% 的票剔除")
    print("    (若 c 档是坏依据 → 剔除后保留池均收/胜率/连板/正月率应全面提升)")
    for name, sub in groups:
        base = _stats(sub)
        base_v = _stats(sub[~sub.is_train])
        print(f"\n== {name} ==  基线 n={base['n']} 均{base['均收%']:+.2f} "
              f"胜{base['胜率%']} 连板{base['连板%']} 正月{_pos_month_rate(sub):.0f}% | "
              f"验证 n={base_v['n']} 均{base_v['均收%']:+.2f} 连板{base_v['连板%']}")
        print(f"{'规则':<24}{'移除n':>6}{'移除均':>8}{'杀伤%':>8}{'误伤%':>8}"
              f"{'| 剩n':>7}{'剩均收':>8}{'剩胜率':>8}{'剩连板':>8}{'剩正月':>7}"
              f"{'| 验剩n':>7}{'验均收':>8}{'验胜率':>8}{'验连板':>8}{'验正月':>7}")
        for c in [4, 5, 6, 7, 8, 9]:
            mask = (sub["maxchg5_tm1"] >= c).fillna(False)
            if mask.sum() < 20:
                print(f"(≥{c}%: 仅{int(mask.sum())}笔, 样本不足跳过)")
                continue
            _keep_effect(sub, mask, f"近5日最大涨幅≥{c}%")

    # ── [3] recency: 大阳出现的位置(限定近5日有≥7%大阳的样本) ──
    print("\n[3] recency: 最近一次≥7%大阳距今几个交易日(1=T-1 大阳; 对照=5日内无)")
    for name, sub in groups:
        bins_off = [0.5, 1.5, 2.5, 3.5, 5.5, 99]
        base = _stats(sub)
        print(f"\n== {name} ==  基线 均{base['均收%']:+.2f} 胜{base['胜率%']} 连板{base['连板%']}")
        print(f"{'off':<10}{'n':>6}{'连板%':>7}{'D+1均':>8}{'均收':>8}{'胜率':>7}{'L%':>7}"
              f"{'| 验n':>6}{'验均收':>8}{'验胜率':>7}")
        has7 = (sub["maxchg5_tm1"] >= 7).fillna(False)
        for lo, hi in zip(bins_off[:-1], bins_off[1:]):
            gdf = sub[(sub["lastbig7_off_tm1"] > lo) & (sub["lastbig7_off_tm1"] <= hi)]
            if not len(gdf):
                print(f"{f'{lo:.0f}~{hi:.0f}天':<10}{0:>6}")
                continue
            s = _stats(gdf)
            sv = _stats(gdf[~gdf.is_train])
            vstr = (f"{sv['n']:>6}{sv['均收%']:>8.2f}{sv['胜率%']:>7.1f}"
                    if sv["n"] else f"{0:>6}{'--':>8}{'--':>7}")
            print(f"{f'{lo:.0f}~{hi:.0f}天':<10}{s['n']:>6}{s['连板%']:>7.1f}"
                  f"{s['D+1均%']:>8.2f}{s['均收%']:>8.2f}{s['胜率%']:>7.1f}{s['L%']:>7.1f}{vstr}")
        gdf = sub[~has7]
        s = _stats(gdf)
        sv = _stats(gdf[~gdf.is_train])
        vstr = (f"{sv['n']:>6}{sv['均收%']:>8.2f}{sv['胜率%']:>7.1f}"
                if sv["n"] else f"{0:>6}{'--':>8}{'--':>7}")
        print(f"{'5日内无':<10}{s['n']:>6}{s['连板%']:>7.1f}{s['D+1均%']:>8.2f}"
              f"{s['均收%']:>8.2f}{s['胜率%']:>7.1f}{s['L%']:>7.1f}{vstr}")

    # ── [4] 次数效应: 近5日 ≥7% 大阳天数 ──
    print("\n[4] 近5日 ≥7% 大阳天数:")
    for name, sub in groups:
        _bucket_table(sub, "bigcnt7_5tm1", [-1, 0.5, 1.5, 2.5, 9],
                      name, fmt=lambda v: f"{v:.0f}")

    # ── [5] 混杂检查: maxchg5≥7 组 vs <7 组的构成差异 ──
    print("\n[5] 混杂检查(全期均值): 组间构成差")
    for name, sub in groups:
        m = (sub["maxchg5_tm1"] >= 7).fillna(False)
        for tag, gdf in [("5日内有≥7大阳", sub[m]), ("无", sub[~m])]:
            if not len(gdf):
                continue
            print(f"  {name:<10}{tag:<14}n={len(gdf):>5} "
                  f"ret10={gdf['ret10_tm1'].mean() * 100:>6.1f}% "
                  f"yang10={gdf['yang10_tm1'].mean():>4.1f} "
                  f"D1涨={gdf['change_pct_tm1'].mean():>6.2f}% "
                  f"换手={gdf['turnover_rate_tm1'].mean():>5.2f}% "
                  f"T日量比={gdf['vol_ratio'].mean():>4.2f} "
                  f"价={gdf['close_price_tm1'].mean():>6.2f} "
                  f"市值={gdf['cap_yi'].mean():>6.0f}亿")


if __name__ == "__main__":
    main()
