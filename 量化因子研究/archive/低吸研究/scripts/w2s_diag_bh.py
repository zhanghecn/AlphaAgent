# -*- coding: utf-8 -*-
"""诊断: w2s_u1_formula.py 板留全+100%的根因."""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

bars, segs, clusters, waves, bounds = w.load_all()
g = bars.groupby("sid", sort=False)

# 复刻第一层(公式直译)拿一笔noamp票
zt = ((bars["close_price"] / bars["prev_close"] - 1 > 0.095)
      & (bars["close_price"] >= bars["high_price"] - 1e-9)).fillna(False).astype(bool)
z1 = zt.groupby(bars["sid"], sort=False).shift(1).fillna(False).astype(bool)
z2 = (zt & z1).fillna(False).astype(bool)
z2b = z2.groupby(bars["sid"], sort=False).shift(2).fillna(False).astype(bool)
z3 = (z2 & z2b).fillna(False).astype(bool)
e2 = z2.groupby(bars["sid"], sort=False).transform(
    lambda s: s.shift(1).rolling(20, min_periods=1).max()).fillna(0) > 0
e3 = z3.groupby(bars["sid"], sort=False).transform(
    lambda s: s.shift(1).rolling(20, min_periods=1).max()).fillna(0) > 0
pc = g["close_price"].shift(1)
po = g["open_price"].shift(1)
phh = g["high_price"].shift(1)
ppc = g["prev_close"].shift(1)
base = (e2 & ~e3 & ~z1 & (pc < po)
        & (pc / ppc - 1).between(-0.09, 0, inclusive="left")
        & ((phh - np.maximum(po, pc)) / ppc < 0.04)
        & (pc / g["close_price"].shift(4) - 1 < 0.06)).fillna(False).astype(bool)

bars["n1_close"] = g["close_price"].shift(-1)
bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6
bars["d0_open_lim"] = bars["open_price"] >= bars["lim_px"] - 1e-6
cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna()

cand = bars[base & cond_ok]
# 第一笔(noamp公式条件的第一个命中)
cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
hi_by = {sid: grp["high_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
z2_by = {sid: grp.to_numpy() for sid, grp in z2.groupby(bars["sid"], sort=False)}
p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
       for sid, grp in bars.groupby("sid", sort=False)}
pcs_all = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
idx = p2i

for r in cand.itertuples():
    sid = int(r.sid)
    i = p2i[sid][int(r.pos)]
    y = i - 1
    closes, highs, z2_arr = cl_by[sid], hi_by[sid], z2_by[sid]
    j = i
    while j >= 0 and not z2_arr[j]:
        j -= 1
    if j < 0 or i - j - 1 < 1:
        continue
    toph = highs[max(j - 1, 0):j + 1].max()
    lowc = closes[max(y - 19, 0):y + 1].min()
    if lowc / toph - 1 > -0.12 or not (0.08 <= closes[y] / lowc - 1 <= 0.14):
        continue
    if closes[y] / toph - 1 > -0.04:
        continue
    if closes[max(y - 2, 0):y + 1].min() <= lowc:
        continue
    # 命中! 打印这笔票 D0前后明细
    nm = getattr(r, "name", "")
    print(f"命中票: {r.trade_date} {r.vt_symbol} {nm}")
    print(f"D0 index i={i}, pos={r.pos}, lim_px={r.lim_px:.2f}")
    bd_p = idx.get(sid)
    for d in range(0, 6):
        jj = bd_p.get(int(r.pos) + d)
        if jj is None:
            print(f"  D+{d}: pos={int(r.pos)+d} -> 无数据(None)")
            break
        lim = round(pcs_all[sid][jj] * 1.10 + 1e-9, 2)
        print(f"  D+{d}: pos={int(r.pos)+d} idx={jj} close={cl_by[sid][jj]:.2f} "
              f"prev_close={pcs_all[sid][jj]:.2f} lim={lim:.2f} "
              f"{'板' if abs(cl_by[sid][jj] - lim) <= 1e-6 else '断'}")
    print(f"  banhold返回 / lim_px - 1 = ?  (人工看上面断板日close/{r.lim_px:.2f})")
    break
