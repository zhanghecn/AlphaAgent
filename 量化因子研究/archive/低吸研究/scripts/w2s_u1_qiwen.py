# -*- coding: utf-8 -*-
"""U1问财近似版回测: 同花顺动态板块自然语言可表达的口径, 量化每处近似的代价.

问财可表达构件 vs 研究版:
  近20日涨停次数=2      ~ 前20日连板=2 (混入孤立双板, 回测量化)
  最后涨停距今7~19天     ~ N2=BARSLAST(末板) (次数=2下精确成立)
  昨收/近K日最低收盘     ~ 弹回8~14 (K固定窗罩板前低位, 扫描K)
  近3日未创K日收盘新低   ~ near3
  蹲深/不贴顶/振幅/pos_low: 问财无法表达, 舍弃 (触板日近20日最高价恒=今日涨停价, 锚失效)
输出: K扫描的 n/差票率/板留/分年 + 与strict29笔对账.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)

bars, segs, clusters, waves, bounds = w.load_all()
g = bars.groupby("sid", sort=False)

zt = bars["is_lim"].astype(bool)
# 近20日涨停次数(昨日口径, 问财"近20日"含今日但今日盘中未封=不计, 等价)
cnt20 = zt.groupby(bars["sid"], sort=False).transform(
    lambda s: s.shift(1).fillna(False).astype(int).rolling(20, min_periods=1).sum())
# 连板=2精确口径(对照: 隔离孤立双板污染)
z1 = zt.groupby(bars["sid"], sort=False).shift(1).fillna(False).astype(bool)
z2 = (zt & z1).fillna(False).astype(bool)
zt2 = zt.groupby(bars["sid"], sort=False).shift(2).fillna(False).astype(bool)
z3 = (z2 & zt2).fillna(False).astype(bool)


def _exist20(s):
    return s.shift(1).fillna(False).astype(int).rolling(20, min_periods=1).max()


e2 = z2.groupby(bars["sid"], sort=False).transform(_exist20) > 0
e3 = z3.groupby(bars["sid"], sort=False).transform(_exist20) > 0

pc = g["close_price"].shift(1)
po = g["open_price"].shift(1)
phh = g["high_price"].shift(1)
ppc = g["prev_close"].shift(1)

base_q = ((cnt20 == 2)                                    # 问财最简前置: 仅涨停次数=2(孤立双板混入)
          & (pc < po)                                     # 昨日收阴
          & (pc / ppc - 1).between(-0.09, 0, inclusive="left")   # 昨幅(-9%,0]
          & ((phh - np.maximum(po, pc)) / ppc < 0.04)     # 昨上影<4%
          & (pc / g["close_price"].shift(4) - 1 < 0.06))  # 前三日涨幅<6%
base_q = base_q.fillna(False).astype(bool)

bars["n1_close"] = g["close_price"].shift(-1)
bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6
bars["d0_open_lim"] = bars["open_price"] >= bars["lim_px"] - 1e-6
cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna()

cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
zt_by = {sid: grp.to_numpy() for sid, grp in zt.groupby(bars["sid"], sort=False)}
stk_by = {sid: grp["streak"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
       for sid, grp in bars.groupby("sid", sort=False)}

cand = bars[base_q & cond_ok]
print(f"第一层候选(连板=2 ∧ 次数=2): {len(cand)} 笔 (连板口径1128/次数口径1464)")

# strict29笔名单(对账基准)
hi_by = {sid: grp["high_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
strict_keys = set()
for r in cand.itertuples():
    sid = int(r.sid)
    i = p2i[sid][int(r.pos)]
    y = i - 1
    closes, highs, stk_arr = cl_by[sid], hi_by[sid], stk_by[sid]
    j = y
    while j >= 0:
        if stk_arr[j] >= 2:
            break
        j -= 1
    if j < 0 or y - j < 1:
        continue
    seg_c = closes[j + 1:y + 1]
    low_c, top_h = seg_c.min(), highs[max(j - 1, 0):j + 1].max()
    if low_c / top_h - 1 > -0.12:
        continue
    if not (0.08 <= closes[y] / low_c - 1 <= 0.14):
        continue
    if closes[y] / top_h - 1 > -0.04:
        continue
    if seg_c.max() / low_c - 1 <= 0.10:
        continue
    if len(seg_c) > 1 and int(np.argmin(seg_c)) / (len(seg_c) - 1) > 0.6:
        continue
    strict_keys.add((r.vt_symbol, r.trade_date))
print(f"对账基准 strict: {len(strict_keys)} 笔")

idx = p2i
closes_all = cl_by
pcs_all = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)


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


# ── 「涨停后」事件锚定口径: 问财若有涨停后系列字段则精确; LOW_MODE=low试最低价口径 ──
lo_by = {sid: grp["low_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
for LOW_MODE in ("close", "low"):
    keep = []
    for r in cand.itertuples():
        sid = int(r.sid)
        i = p2i[sid][int(r.pos)]
        y = i - 1
        closes, zt_arr = cl_by[sid], zt_by[sid]
        lows = lo_by[sid]
        j = y  # 问财经口径: 盘中今日未收盘确认, 最后涨停=今日之前(跳过今日)
        while j >= 0 and not zt_arr[j]:
            j -= 1
        if j < 0:
            continue
        n2 = i - j
        if not (7 <= n2 <= 19):
            continue
        seg_c = closes[j + 1:y + 1]
        seg_l = lows[j + 1:y + 1]
        # 蹲: 涨停后最低 / 涨停日收盘(=顶, 连板日high=close=涨停价) -1 <= -12%
        bot = seg_l.min() if LOW_MODE == "low" else seg_c.min()
        top = closes[j]                     # 涨停当日收盘价
        if bot / top - 1 > -0.12:
            continue
        # 弹回: 昨收 / 涨停后最低 -1 ∈ [8,14]
        if not (0.08 <= closes[y] / bot - 1 <= 0.14):
            continue
        # 不贴顶: 昨收 / 涨停日收盘 -1 <= -4%
        if closes[y] / top - 1 > -0.04:
            continue
        # 振幅: 断板期收盘振幅>10%
        if seg_c.max() / seg_c.min() - 1 <= 0.10:
            continue
        # near3: 近3日未创涨停后收盘新低
        if seg_c[-3:].min() <= seg_c.min():
            continue
        keep.append(r.Index)
    tg = bars.loc[keep].copy()
    if not len(tg):
        print(f"[K={K}] 0笔")
        continue
    tg["r_d1c"] = tg["n1_close"] / tg["lim_px"] - 1
    tg["res"] = np.where(~tg["is_lim"], "炸板",
                         np.where(tg["r_d1c"] < 0, np.where(tg["n1_lim"], "连板", "封D1负"),
                                  np.where(tg["n1_lim"], "连板", "封D1正")))
    tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
    tg["r_bh"] = [banhold(int(s), int(p)) / lp - 1 for s, p, lp in zip(tg["sid"], tg["pos"], tg["lim_px"])]
    keys = set(zip(tg["vt_symbol"], tg["trade_date"]))
    both = keys & strict_keys
    print("=" * 86)
    print(f"[涨停后口径·最低{LOW_MODE}] 触发 {len(tg)} 笔 | 差票率 {tg['bad'].mean() * 100:.0f}% | "
          f"连板率 {(tg['res'] == '连板').mean() * 100:.0f}%")
    print(f"  D1收: 均 {tg['r_d1c'].mean() * 100:+.2f}% 中位 {tg['r_d1c'].median() * 100:+.2f}%")
    print(f"  板留: 均 {tg['r_bh'].mean() * 100:+.2f}% 中位 {tg['r_bh'].median() * 100:+.2f}%")
    for yy in (2023, 2024, 2025, 2026):
        sy = tg[tg["trade_date"].dt.year == yy]
        if len(sy):
            print(f"  {yy}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% 中位 {sy['r_bh'].median() * 100:+.2f}%")
    print(f"  对账strict29: 交集 {len(both)}/{len(strict_keys)} | 仅问财 {len(keys - strict_keys)}")
