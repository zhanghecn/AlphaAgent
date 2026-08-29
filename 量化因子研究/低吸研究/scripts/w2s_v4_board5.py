# -*- coding: utf-8 -*-
"""4+→5+ 门槛对照: 前20日连板>=4 → >=5/6/8, 检验「尽可能取妖股」的效果.
输出: 阶梯全景(阴/阳全量+分年) / >=5内部按窗口最大连板精确值分桶 / 最近段高度×地基 /
白名单出手层口径在>=5下的表现(妖股票的U型蹲/阴跌到点).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base, BASE_ORDER

BASE_CN = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
           "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}

pd.set_option("display.width", 500)


def stat(tg, label):
    bad = tg["res"].isin(["炸板", "封D1负"])
    yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := tg[tg["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(tg)} 板留均 {tg['r_bh'].mean() * 100:+.2f} 中位 {tg['r_bh'].median() * 100:+.2f} "
          f"胜率 {(tg['r_bh'] > 0).mean() * 100:.0f}% 差票 {bad.mean() * 100:.0f}% "
          f"连板 {(tg['res'] == '连板').mean() * 100:.0f}% | 分年 {yr}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    res = {}
    # ── 阶梯: >=4(现行) / >=5 / >=6 / >=8, 阴/阳 ──
    for yside, pcol, chg_min in (("阴", "p_yin", -0.08), ("阳", "p_yang", -0.03)):
        print("=" * 96)
        print(f"【{yside}线 门槛阶梯】")
        for th, tag in ((4, ">=4(现行)"), (5, ">=5"), (6, ">=6"), (8, ">=8")):
            c = f"c5_{yside}{th}"
            bars[c] = ((bars["mx20"] >= th) & bars[pcol] & (bars["p_chg"] > chg_min)
                       & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
            tg, _ = build_base(bars, segs, conds=(c,))
            tg = add_outcome(tg, bars)
            tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
            res[(yside, th)] = tg
            stat(tg, f"连板{tag}")

    # ── >=5 内部: 窗口最大连板精确值分桶(5/6/7/8+) = 妖股浓度 ──
    print("\n" + "=" * 96)
    print("【>=5 内部: 窗口内最大连板精确值分桶(妖股浓度)】")
    for yside in ("阴", "阳"):
        t5 = res[(yside, 5)].copy()
        t5["h"] = pd.cut(t5["mx20"], [4.5, 5.5, 6.5, 7.5, 99], labels=["恰5板", "6板", "7板", "8板+"])
        t = t5.groupby("h", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                               板留中位=("r_bh", "median"), 差票率=("bad", "mean"),
                                               连板率=("res", lambda s: (s == "连板").mean()))
        for c in ("差票率", "连板率"):
            t[c] = (t[c] * 100).round(0)
        for c in ("板留均", "板留中位"):
            t[c] = (t[c] * 100).round(2)
        print(f"\n── {yside}线 ──")
        print(t.to_string())

    # ── >=5 × 地基 矩阵(对照>=4同格) ──
    print("\n" + "=" * 96)
    print("【>=5 × 地基 (板留均/n) vs >=4 同格】")
    for yside in ("阴", "阳"):
        t5, t4 = res[(yside, 5)], res[(yside, 4)]
        rows = []
        for b in BASE_ORDER:
            s5, s4 = t5[t5["base"] == b], t4[t4["base"] == b]
            if not len(s5) and not len(s4):
                continue
            rows.append({"地基": BASE_CN[b],
                         "≥5板n": len(s5), "≥5板板留": round(s5["r_bh"].mean() * 100, 2) if len(s5) else np.nan,
                         "≥4板n": len(s4), "≥4板板留": round(s4["r_bh"].mean() * 100, 2) if len(s4) else np.nan})
        print(f"\n── {yside}线 ──")
        print(pd.DataFrame(rows).to_string(index=False))

    # ── >=6 阴线 × 地基 + 精确值分桶(黄金层内部结构) ──
    print("\n" + "=" * 96)
    print("【>=6 阴线 × 地基 (黄金层内部) + 恰6/7/8+分桶】")
    t6 = res[("阴", 6)].copy()
    rows = []
    for b in BASE_ORDER:
        s = t6[t6["base"] == b]
        if not len(s):
            continue
        rows.append({"地基": BASE_CN[b], "n": len(s),
                     "板留均": round(s["r_bh"].mean() * 100, 2),
                     "板留中位": round(s["r_bh"].median() * 100, 2),
                     "胜率%": round((s["r_bh"] > 0).mean() * 100),
                     "连板%": round((s["res"] == "连板").mean() * 100)})
    print(pd.DataFrame(rows).to_string(index=False))
    t6["h"] = pd.cut(t6["mx20"], [5.5, 6.5, 7.5, 99], labels=["恰6板", "7板", "8板+"])
    for hlab in ("恰6板", "7板", "8板+"):
        s = t6[t6["h"] == hlab]
        if len(s):
            stat(s, f"全量×{hlab}")

    # ── >=5 出手层口径(白名单: 阴=U型蹲+阴跌到点) + 分桶细分 ──
    print("\n" + "=" * 96)
    print("【>=5 阴线 出手层(白名单=U型蹲+阴跌到点) 及内部细分】")
    t5 = res[("阴", 5)].copy()
    wl = t5[t5["base"].isin(["U", "DN"])]
    if len(wl):
        stat(wl, "出手层(U型蹲+阴跌到点)")
        for b in ("U", "DN"):
            s = wl[wl["base"] == b]
            if len(s):
                stat(s, f"  {BASE_CN[b]}")
    # 妖股浓度 × 出手层 交叉: 恰5板 vs 6板+
    t5["h"] = pd.cut(t5["mx20"], [4.5, 5.5, 99], labels=["恰5板", "6板+"])
    for hlab in ("恰5板", "6板+"):
        s = t5[(t5["h"] == hlab) & t5["base"].isin(["U", "DN"])]
        if len(s):
            stat(s, f"出手层×{hlab}")
        s2 = t5[t5["h"] == hlab]
        if len(s2):
            stat(s2, f"全量×{hlab}")


if __name__ == "__main__":
    main()
