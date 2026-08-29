# -*- coding: utf-8 -*-
"""诊断: 研究版连板判据(mx20==2) vs 公式直译判据(e2&~e3) 差349笔的根因."""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)
bars, segs, clusters, waves, bounds = w.load_all()
g = bars.groupby("sid", sort=False)

# 研究版判据
stk = bars["streak"].astype(float)
mx20 = stk.groupby(bars["sid"], sort=False).transform(
    lambda s: s.shift(1).rolling(20, min_periods=1).max())

# 公式直译判据
zt = bars["is_lim"].astype(bool)
z1 = zt.groupby(bars["sid"], sort=False).shift(1).fillna(False).astype(bool)
z2 = (zt & z1).fillna(False).astype(bool)
z2b = z2.groupby(bars["sid"], sort=False).shift(2).fillna(False).astype(bool)
z3 = (z2 & z2b).fillna(False).astype(bool)


def _exist20(s):
    return s.shift(1).fillna(False).astype(int).rolling(20, min_periods=1).max()


e2 = z2.groupby(bars["sid"], sort=False).transform(_exist20) > 0
e3 = z3.groupby(bars["sid"], sort=False).transform(_exist20) > 0
f_judge = e2 & ~e3
r_judge = (mx20 == 2)

print(f"研究判据(mx20==2): {int(r_judge.sum())} 行 | 公式判据(e2&~e3): {int(f_judge.sum())} 行")
print(f"对称差: {int((r_judge ^ f_judge).sum())} 行")

# 校验: z2 与 stk>=2 是否逐行一致
z2_stk = stk >= 2
print(f"z2 与 (streak>=2) 不一致行: {int((z2 != z2_stk.fillna(False)).sum())}")

# 差异样例
diff_idx = bars.index[r_judge ^ f_judge][:6]
cols = ["trade_date", "vt_symbol", "streak", "is_lim"]
sel = bars.loc[diff_idx, cols].copy()
sel["mx20"] = mx20.loc[diff_idx]
sel["e2"] = e2.loc[diff_idx]
sel["e3"] = e3.loc[diff_idx]
sel["r_judge"] = r_judge.loc[diff_idx]
sel["f_judge"] = f_judge.loc[diff_idx]
print(sel.to_string())

# 深挖第一笔差异票: 打印它前25日的 streak/is_lim/z2/e2/e3
if len(diff_idx):
    r0 = bars.loc[diff_idx[0]]
    sid = int(r0["sid"])
    grp = bars[bars["sid"] == sid]
    i0 = grp.index.get_loc(diff_idx[0])
    lo = max(i0 - 25, 0)
    sub = grp.iloc[lo:i0 + 1][["trade_date", "streak", "is_lim", "close_price"]].copy()
    sub["z2"] = z2.loc[sub.index]
    sub["z3"] = z3.loc[sub.index]
    sub["mx20"] = mx20.loc[sub.index]
    sub["e2"] = e2.loc[sub.index]
    sub["e3"] = e3.loc[sub.index]
    print("\n差异票#0 明细(前25日):")
    print(sub.to_string())
