# -*- coding: utf-8 -*-
"""U1文字条件核查v2: 断板期锚定(距上次涨停N天)替代20日窗, 修正窗口污染.

文字条件v2(与回测口径同构):
  主板/非ST / 前20日连板=2 / 昨日未涨停 / 昨日收阴 / 昨幅-9%~0 / 昨上影<4% / 前三日涨幅<6%
  N = 昨日距上次涨停的天数(上次涨停=上波末板)
  蹲深: N日内最低收盘 / (N+2)日内最高价 - 1 <= -12%
  弹回: 昨收 / N日内最低收盘 - 1 ∈ 8%~14%     (命门)
  不贴顶: 昨收 / (N+2)日内最高价 - 1 <= -4%
  近3日未创N日收盘新低                         (近似U型左半, 剔V末反)
对账目标(研究版U1): 33笔 差票36% 连板24% D1收+2.62/中位+2.10 板留+5.77/中位+2.10.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)
MODE = sys.argv[1] if len(sys.argv) > 1 else "strict"

bars, segs, clusters, waves, bounds = w.load_all()
g = bars.groupby("sid", sort=False)

# ── 第一层: 补涨阴日线条件(昨日口径, 与_ths_daily同构) ──
pc = g["close_price"].shift(1)
po = g["open_price"].shift(1)
phh = g["high_price"].shift(1)
ppc = g["prev_close"].shift(1)
stk = bars["streak"].astype(float)
mx20 = stk.groupby(bars["sid"], sort=False).transform(lambda s: s.shift(1).rolling(20, min_periods=1).max())
base = ((mx20 == 2)
        & ~g["is_lim"].shift(1).fillna(False).astype(bool)
        & (pc < po)
        & (pc / ppc - 1).between(-0.09, 0, inclusive="left")
        & ((phh - np.maximum(po, pc)) / ppc < 0.04)
        & (pc / g["close_price"].shift(4) - 1 < 0.06)).fillna(False).astype(bool)

# ── 第二层: 断板期锚定(逐行变长窗口, 只对base候选行算) ──
cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
hi_by = {sid: grp["high_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
stk_by = {sid: grp["streak"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
       for sid, grp in bars.groupby("sid", sort=False)}

bars["n1_open"] = g["open_price"].shift(-1)
bars["n1_close"] = g["close_price"].shift(-1)
bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6
bars["d0_open_lim"] = bars["open_price"] >= bars["lim_px"] - 1e-6
cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()

cand = bars[base & cond_ok]
print(f"第一层(补涨阴·前20日连板=2)候选 {len(cand)} 笔")
keep = []
for r in cand.itertuples():
    sid = int(r.sid)
    i = p2i[sid][int(r.pos)]          # D0 行index
    y = i - 1                          # 昨日
    # 昨日距上波末板N: 从y往回找最近连板段(>=2板)的末板, 跳过断板期孤立夹板(与研究版big_by同构)
    closes, highs = cl_by[sid], hi_by[sid]
    stk_arr = stk_by[sid]
    j = y
    while j >= 0:
        if stk_arr[j] >= 2:            # 该日属于连板段(从右往左首个, 即该段末板)
            break
        j -= 1
    if j < 0:
        continue                       # 无>=2连板段
    n_gap = y - j                      # 断板天数(上波末板->昨日)
    if n_gap < 1:
        continue
    seg_c = closes[j + 1: y + 1]       # 断板期收盘(末板次日..昨日)
    seg_h = highs[max(j - 1, 0): j + 1]  # 上波顶=上波2板段最高价(不含断板期, 与研究版同构)
    low_c, top_h = seg_c.min(), seg_h.max()
    prev_close = closes[y]
    if low_c / top_h - 1 > -0.12:      # 蹲深>=12%
        continue
    reb = prev_close / low_c - 1
    if not (0.08 <= reb <= 0.14):      # 弹回命门8~14
        continue
    if prev_close / top_h - 1 > -0.04:  # 不贴顶
        continue
    if seg_c.max() / low_c - 1 <= 0.10:  # 断板期收盘振幅>10%(剔缓坡假U, FLAT优先级同构)
        continue
    # 低点位置: 研究版U=pos_low<=0.6(最低收盘在断板期前中段); 近3日版=放宽近似
    pos_low = int(np.argmin(seg_c)) / (len(seg_c) - 1) if len(seg_c) > 1 else 0.0
    low_i = int(np.argmin(seg_c))
    if MODE == "strict" and pos_low > 0.6:
        continue
    if MODE == "near3" and seg_c[-3:].min() <= low_c:
        continue
    if MODE == "near5" and (len(seg_c) < 5 or seg_c[-5:].min() <= low_c or pos_low > 0.75):
        continue
    keep.append((r.Index, pos_low, reb, low_c / top_h - 1, n_gap, low_i))
tg = bars.loc[[k[0] for k in keep]].copy()
print(f"MODE={MODE}")
tg["r_d1o"] = tg["n1_open"] / tg["lim_px"] - 1
tg["r_d1c"] = tg["n1_close"] / tg["lim_px"] - 1
tg["res"] = np.where(~tg["is_lim"], "炸板",
                     np.where(tg["r_d1c"] < 0, np.where(tg["n1_lim"], "连板", "封D1负"),
                              np.where(tg["n1_lim"], "连板", "封D1正")))
tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
tg["date"] = tg["trade_date"].dt.strftime("%Y-%m-%d")

idx = {sid: {int(p): i for i, p in enumerate(grp["pos"])} for sid, grp in bars.groupby("sid", sort=False)}
closes_all = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
pcs_all = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}


def banhold(sid, pos0):
    bd_p, bd_c = idx.get(sid), closes_all.get(sid)
    if bd_p is None:
        return np.nan
    for d in range(1, 21):
        j = bd_p.get(pos0 + d)
        if j is None:
            k = bd_p.get(pos0 + d - 1)
            return bd_c[k] if k is not None else np.nan
        lim = round(pcs_all[sid][j] * 1.10 + 1e-9, 2)
        if abs(bd_c[j] - lim) > 1e-6:
            return bd_c[j]
    return bd_c[bd_p.get(pos0 + 20, len(bd_c) - 1)]


tg["r_bh"] = [banhold(int(s), int(p)) / lp - 1 for s, p, lp in zip(tg["sid"], tg["pos"], tg["lim_px"])]

print("=" * 90)
print(f"文字条件v2版U1: 触发 {len(tg)} 笔 | 差票率 {tg['bad'].mean() * 100:.0f}% | "
      f"连板率 {(tg['res'] == '连板').mean() * 100:.0f}%")
print(f"  D1收: 均 {tg['r_d1c'].mean() * 100:+.2f}% 中位 {tg['r_d1c'].median() * 100:+.2f}%")
print(f"  板留: 均 {tg['r_bh'].mean() * 100:+.2f}% 中位 {tg['r_bh'].median() * 100:+.2f}%")
for y in (2023, 2024, 2025, 2026):
    sy = tg[tg["trade_date"].dt.year == y]
    if len(sy):
        print(f"  {y}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% 中位 {sy['r_bh'].median() * 100:+.2f}%")

# ── 对账 ──
print("\n== 对账: 文字v2版 vs 研究版 ==")
ref = pd.read_csv("/app/w2s_v3_out/地基研究/补涨阴地基全量.csv", encoding="utf-8-sig",
                  dtype={"vt_symbol": str})
ref_u1 = ref[(ref["地基"].str.startswith("U")) & (ref["上波高"] <= 2)
             & (ref["弹回%"].between(8, 14))]
keys_txt = set(zip(tg["vt_symbol"], tg["date"]))
keys_ref = set(zip(ref_u1["vt_symbol"], ref_u1["date"]))
both = keys_txt & keys_ref
print(f"  文字v2版 {len(keys_txt)} 笔, 研究版 {len(keys_ref)} 笔, 交集 {len(both)} "
      f"({len(both) / max(len(keys_txt | keys_ref), 1) * 100:.0f}% 一致)")
for tag, keys, src in [("仅文字v2", keys_txt - keys_ref, tg), ("仅研究版", keys_ref - keys_txt, ref_u1)]:
    if not keys:
        continue
    print(f"  {tag} {len(keys)} 笔:")
    for s, d in sorted(keys):
        if tag == "仅文字v2":
            r = tg[(tg["vt_symbol"] == s) & (tg["date"] == d)].iloc[0]
            print(f"    {d} {s} {r['name']} {r['res']} D1收{r['r_d1c'] * 100:+.2f}% 板留{r['r_bh'] * 100:+.2f}%")
        else:
            r = ref_u1[(ref_u1["vt_symbol"] == s) & (ref_u1["date"] == d)].iloc[0]
            print(f"    {d} {s} {r['name']} {r['res']} D1收{r['D1收%']:+.2f}% 板留{r['板留%']:+.2f}%")
