# -*- coding: utf-8 -*-
"""V4问题2对照: 2板组 前10日窗(mx10==2) vs 前20日窗(mx20==2), 检验被切掉的断板11~20天长缓启层.

两窗语义均为「窗口内最大连板恰为2」(排除3+); 20日窗新增票 = 断板11~20天被10日窗漏掉的2板段票.
输出: 两窗全量对比 / 新增层断板gap分桶 / 20日窗版 地基×断板 交叉 / 新增层地基分布.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base, BASE_NAME, BASE_ORDER

pd.set_option("display.width", 400)


def stat(tg, label):
    bad = tg["res"].isin(["炸板", "封D1负"])
    print(f"  {label}: n={len(tg)} 板留均 {tg['r_bh'].mean() * 100:+.2f} 中位 {tg['r_bh'].median() * 100:+.2f} "
          f"胜率 {(tg['r_bh'] > 0).mean() * 100:.0f}% 差票 {bad.mean() * 100:.0f}% "
          f"连板 {(tg['res'] == '连板').mean() * 100:.0f}%")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    stk = bars["streak"].astype(float)
    bars["mx10"] = stk.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).max())
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    # 10日窗(现行) / 20日窗(对照), 同为「恰2板」语义
    for tag, mx in (("w10", bars["mx10"]), ("w20", bars["mx20"])):
        bars[f"a_{tag}"] = (mx == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09) \
            & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
        bars[f"b_{tag}"] = (mx == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03) \
            & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
        for c in (f"a_{tag}", f"b_{tag}"):
            bars[c] = bars[c].fillna(False).astype(bool)

    for name, cw10, cw20 in (("2板补涨阴", "a_w10", "a_w20"), ("2板补涨阳", "b_w10", "b_w20")):
        t10, _ = build_base(bars, segs, conds=(cw10,))
        t20, _ = build_base(bars, segs, conds=(cw20,))
        t10, t20 = add_outcome(t10, bars), add_outcome(t20, bars)
        for t in (t10, t20):
            t["bad"] = t["res"].isin(["炸板", "封D1负"])
        print("=" * 92)
        print(f"【{name}】")
        stat(t10, "10日窗(现行)")
        stat(t20, "20日窗(对照)")

        # 新增层 = 20日窗命中而10日窗未命中 (断板11~20天)
        k20 = set(zip(t20["sid"], t20["pos"]))
        k10 = set(zip(t10["sid"], t10["pos"]))
        add_ = t20[[k in (k20 - k10) for k in zip(t20["sid"], t20["pos"])]].copy()
        stat(add_, "仅20日窗(断板11~20新增层)")
        if len(add_):
            for yy in (2023, 2024, 2025, 2026):
                sy = add_[add_["trade_date"].dt.year == yy]
                if len(sy):
                    print(f"    {yy}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% "
                          f"中位 {sy['r_bh'].median() * 100:+.2f}% 差票 {sy['bad'].mean() * 100:.0f}%")
            t = add_.groupby("base").agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                         差票率=("bad", "mean"))
            t["差票率"] = (t["差票率"] * 100).round(0)
            t["板留均"] = (t["板留均"] * 100).round(2)
            print("  新增层地基分布:")
            print(t.reindex(BASE_ORDER).dropna(how="all").to_string())

        # 20日窗版断板gap分桶 (gap=今日距上波末板交易日数, >=2; 1=昨日末板已被~prev_lim排除)
        t20["gb"] = pd.cut(t20["gap"], [1, 5.5, 10.5, 15.5, 20.5],
                           labels=["断2-5", "断6-10", "断11-15", "断16-20"])
        t1 = t20.groupby("gb", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                                 板留中位=("r_bh", "median"), 差票率=("bad", "mean"),
                                                 连板率=("res", lambda s: (s == "连板").mean()))
        for c in ("差票率", "连板率"):
            t1[c] = (t1[c] * 100).round(0)
        for c in ("板留均", "板留中位"):
            t1[c] = (t1[c] * 100).round(2)
        print("  20日窗版 断板天数分桶:")
        print(t1.to_string())
        # 断16-20 分年稳定性
        s16 = t20[t20["gap"] >= 16]
        if len(s16):
            print("  断16-20 分年:")
            for yy in (2023, 2024, 2025, 2026):
                sy = s16[s16["trade_date"].dt.year == yy]
                if len(sy):
                    print(f"    {yy}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% "
                          f"差票 {sy['bad'].mean() * 100:.0f}%")

        # 地基 × 断板 交叉(板留均) — 看 FLAT 等甜点地基集中在哪个断板带
        piv = (t20.pivot_table(index="base", columns="gb", values="r_bh", aggfunc="mean") * 100).round(2)
        pn = t20.pivot_table(index="base", columns="gb", values="r_bh", aggfunc="size")
        print("  20日窗版 地基×断板 板留均 (括号=n):")
        for b in BASE_ORDER:
            if b not in piv.index:
                continue
            cells = []
            for c in piv.columns:
                v, n = piv.loc[b, c], pn.loc[b, c]
                cells.append(f"{v:+.2f}({int(n)})" if pd.notna(v) else "-")
            print(f"    {b:<5s}: " + " | ".join(cells))


if __name__ == "__main__":
    main()
