# -*- coding: utf-8 -*-
"""3板对照组: 复刻V4条件(前20日窗口+昨阴/阳+上影<4%+~prev_lim), 只把连板=2换成=3,
回答「砍3板是好事还是扔掉了某地基下的甜点」. 输出与2板/4+并排对照 + 3板×地基×分桶.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base, BASE_NAME, BASE_ORDER

pd.set_option("display.width", 400)


def stat_line(tg, label):
    bad = tg["res"].isin(["炸板", "封D1负"])
    yr = " / ".join(
        f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
        if len(sy := tg[tg["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(tg)} 板留均 {tg['r_bh'].mean() * 100:+.2f} 中位 {tg['r_bh'].median() * 100:+.2f} "
          f"差票 {bad.mean() * 100:.0f}% 连板 {(tg['res'] == '连板').mean() * 100:.0f}% | 分年 {yr}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    # V4框架下连板维度的完整阶梯: ==2 / ==3 / >=4 (阴/阳各自)
    conds = {
        ("阴", "==2", "c2a"): (bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09) & (bars["p_ush"] < 0.04),
        ("阴", "==3", "c3a"): (bars["mx20"] == 3) & bars["p_yin"] & (bars["p_chg"] > -0.09) & (bars["p_ush"] < 0.04),
        ("阴", ">=4", "c4a"): (bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08) & (bars["p_ush"] < 0.04),
        ("阳", "==2", "c2b"): (bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04),
        ("阳", "==3", "c3b"): (bars["mx20"] == 3) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04),
        ("阳", ">=4", "c4b"): (bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04),
    }
    for k, m in conds.items():
        bars[k[2]] = (m & ~bars["prev_lim"]).fillna(False).astype(bool)

    res = {}
    for (yside, hgt, c), _ in conds.items():
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        res[(yside, hgt)] = tg
        stat_line(tg, f"{yside} 连板{hgt}")

    # 3板×地基 矩阵(阴/阳分列), 并排2板同地基行对照
    print("\n== 3板 × 地基 (板留均/n/差票%) vs 2板同格 ==")
    for yside in ("阴", "阳"):
        t3, t2 = res[(yside, "==3")], res[(yside, "==2")]
        rows = []
        for b in BASE_ORDER:
            s3, s2 = t3[t3["base"] == b], t2[t2["base"] == b]
            if not len(s3) and not len(s2):
                continue
            rows.append({
                "地基": f"{b}·{BASE_NAME[b]}",
                "3板n": len(s3), "3板板留": round(s3["r_bh"].mean() * 100, 2) if len(s3) else np.nan,
                "3板差票%": round(s3["bad"].mean() * 100) if len(s3) else np.nan,
                "2板n": len(s2), "2板板留": round(s2["r_bh"].mean() * 100, 2) if len(s2) else np.nan,
            })
        print(f"\n── {yside}线 ──")
        print(pd.DataFrame(rows).to_string(index=False))

    # 3板内部维度: 断板分桶 + 蹲深分桶(3板是否需要蹲更深)
    print("\n== 3板内部维度 ==")
    for yside in ("阴", "阳"):
        t3 = res[(yside, "==3")].copy()
        t3["gb"] = pd.cut(t3["gap"], [1, 5.5, 10.5, 15.5, 20.5],
                         labels=["断2-5", "断6-10", "断11-15", "断16-20"])
        t1 = t3.groupby("gb", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                                差票率=("bad", "mean"))
        t1["差票率"] = (t1["差票率"] * 100).round(0)
        t1["板留均"] = (t1["板留均"] * 100).round(2)
        print(f"\n── {yside}线 断板分桶 ──")
        print(t1.to_string())
        t3["db"] = pd.cut(-t3["low_dd"], [0, 0.04, 0.12, 0.20, 99],
                         labels=["蹲<4%", "蹲4-12%", "蹲12-20%", "蹲>20%"])
        t2_ = t3.groupby("db", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                                 差票率=("bad", "mean"))
        t2_["差票率"] = (t2_["差票率"] * 100).round(0)
        t2_["板留均"] = (t2_["板留均"] * 100).round(2)
        print(f"── {yside}线 蹲深分桶 ──")
        print(t2_.to_string())

    # 3板×地基 分年稳定性: 找 n>=8/年 且全年正的格子
    print("\n== 3板×地基 分年板留(n>=8/年) ==")
    rows = []
    for yside in ("阴", "阳"):
        t3 = res[(yside, "==3")]
        for b in BASE_ORDER:
            sub = t3[t3["base"] == b]
            ys = {yy: s for yy, s in sub.groupby(sub["trade_date"].dt.year)
                  if yy in (2023, 2024, 2025, 2026) and len(s) >= 8}
            if len(ys) < 3:
                continue
            rows.append({
                "组": f"3板{yside}", "地基": b, "n": len(sub),
                **{yy: round(s["r_bh"].mean() * 100, 2) for yy, s in sorted(ys.items())},
                "全正": "✓" if all(s["r_bh"].mean() > 0 for s in ys.values()) else "",
            })
    if rows:
        print(pd.DataFrame(rows).to_string(index=False))
    else:
        print("(无满足 n>=8/年×3年 的格子)")


if __name__ == "__main__":
    main()
