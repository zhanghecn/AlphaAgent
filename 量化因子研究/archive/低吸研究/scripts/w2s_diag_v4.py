# -*- coding: utf-8 -*-
"""诊断: V4阳线组 昨日涨停混入票全貌(孤立夹板 vs 连板中继追板, 后者被build_base drop)."""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome

pd.set_option("display.width", 400)
bars, segs, clusters, waves, bounds = w.load_all()
w._ths_daily(bars)
g = bars.groupby("sid", sort=False)
stk = bars["streak"].astype(float)
bars["mx10"] = stk.groupby(bars["sid"], sort=False).transform(
    lambda s: s.shift(1).rolling(10, min_periods=1).max())
bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

bars["c4b"] = (bars["mx10"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04)
bars["c4d"] = (bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04)
for c in ("c4b", "c4d"):
    bars[c] = bars[c].fillna(False).astype(bool)

for name, c in (("2板补涨阳", "c4b"), ("4板补涨阳", "c4d")):
    m = bars[c] & bars["prev_lim"] & bars["touch"] & ~bars["d0_open_lim"] \
        & bars["n1_close"].notna() & bars["n1_open"].notna()
    tg = bars[m].copy()
    tg["p_streak2"] = g["streak"].shift(1).reindex(tg.index)
    tg = add_outcome(tg, bars)
    tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
    print("=" * 88)
    print(f"【{name}】昨日涨停混入 {len(tg)} 笔全貌:")
    for lbl, mk in (("昨日孤立板(夹板,地基可算)", tg["p_streak2"] == 1),
                    ("昨日连板中继(追板,被drop)", tg["p_streak2"] >= 2)):
        s = tg[mk]
        if not len(s):
            continue
        print(f"  {lbl}: n={len(s)} | 板留均 {s['r_bh'].mean() * 100:+.2f} 中位 {s['r_bh'].median() * 100:+.2f} "
              f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% "
              f"连板 {(s['res'] == '连板').mean() * 100:.0f}% D1收均 {s['r_d1c'].mean() * 100:+.2f}")
        for yy in (2023, 2024, 2025, 2026):
            sy = s[s["trade_date"].dt.year == yy]
            if len(sy):
                print(f"    {yy}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% 差票 {sy['bad'].mean() * 100:.0f}%")
