# -*- coding: utf-8 -*-
"""U1公式直译版: 消掉动态N, 全常数窗(同花顺/通达信可直接粘贴), 回测验证公式版自身效果.

公式翻译对照(研究版动态N -> 公式版常数窗):
  上波末板锚  BARSLAST(ZT AND REF(ZT,1))      = 研究版 while stk>=2 (跳孤立夹板)
  上波顶      VALUEWHEN(ZT AND REF(ZT,1), HHV(H,2)) = 研究版上波段最高价(不含断板期)
  断板期最低  LLV(REF(C,1), 20)               = 20日窗(前置保证断板期在20日内, 上波段收盘高不污染)
  低点位置    LLV(REF(C,1), 3) > LLV(REF(C,1), 20)  = near3 近3日未创20日新低
  ZT近似      C > REF(C,1)*1.095 AND C = H    (主板10%含低价股舍入, 精确版用ZTPRICE)

三个变体一次跑:
  noamp       公式版(省略断板期振幅>10, 无变长表达; near3+弹回8~14已剔缓坡假U)
  noamp_ng5   公式版 + 断板天数N2>=6 (防20日窗罩进板前盘整区)
  amp         对照: 公式窗口 + 研究版振幅条件(仅用于看省略振幅损失多少)
对账: 与strict公式版(w2s_u1_check.py strict 29笔)交集.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)

bars, segs, clusters, waves, bounds = w.load_all()
g = bars.groupby("sid", sort=False)

# ── ZT: 主口径=平台精确涨停(is_lim, 对应公式ZTPRICE); 近似阈值单独量化(argv=approx) ──
zt = bars["is_lim"].astype(bool)
zt_approx = ((bars["close_price"] / bars["prev_close"] - 1 > 0.095)
             & (bars["close_price"] >= bars["high_price"] - 1e-9)).fillna(False).astype(bool)
if len(sys.argv) > 1 and sys.argv[1] == "approx":
    zt = zt_approx
n_zt_diff = int((zt != zt_approx).sum())
print(f"ZT口径: {'approx' if zt is zt_approx else 'is_lim(精确)'} vs 近似差异行数 {n_zt_diff}")
z1 = zt.groupby(bars["sid"], sort=False).shift(1).fillna(False).astype(bool)  # REF(ZT,1)
z2 = zt & z1                                                                  # 2连板段第2板及以后
z2 = z2.fillna(False).astype(bool)
zt2 = zt.groupby(bars["sid"], sort=False).shift(2).fillna(False).astype(bool)  # REF(ZT,2)
z3 = z2 & zt2                                                                 # stk>=3 = 今日板+昨日板+前日板

# 昨日口径的EXIST(20): 昨日..20日前窗内存在 (bool shift->object坑: 先fillna再转int)
def _exist20(s):
    return s.shift(1).fillna(False).astype(int).rolling(20, min_periods=1).max()


e2 = z2.groupby(bars["sid"], sort=False).transform(_exist20) > 0
e3 = z3.groupby(bars["sid"], sort=False).transform(_exist20) > 0

pc = g["close_price"].shift(1)      # 昨收 = REF(C,1)
po = g["open_price"].shift(1)
phh = g["high_price"].shift(1)
ppc = g["prev_close"].shift(1)      # 前收 = REF(C,2)

base = (e2 & ~e3                                  # 前20日连板=2(存在2板无3板)
        & ~z1                                     # 昨日未涨停
        & (pc < po)                               # 昨日收阴
        & (pc / ppc - 1).between(-0.09, 0, inclusive="left")   # 昨幅(-9%,0]
        & ((phh - np.maximum(po, pc)) / ppc < 0.04)            # 昨上影<4%
        & (pc / g["close_price"].shift(4) - 1 < 0.06))         # 前三日涨幅<6%
base = base.fillna(False).astype(bool)

# ── 执行层: D0触板非一字, D1有数据 ──
bars["n1_close"] = g["close_price"].shift(-1)
bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6
bars["d0_open_lim"] = bars["open_price"] >= bars["lim_px"] - 1e-6
cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna()

cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
hi_by = {sid: grp["high_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
z2_by = {sid: grp.to_numpy() for sid, grp in z2.groupby(bars["sid"], sort=False)}
p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
       for sid, grp in bars.groupby("sid", sort=False)}

cand = bars[base & cond_ok]
print(f"第一层(公式直译·前置)候选 {len(cand)} 笔")


def formula_pick(r, mode):
    """公式逐行直译: 返回None或(NG, TOPH, LOWC)."""
    sid = int(r.sid)
    i = p2i[sid][int(r.pos)]
    y = i - 1
    closes, highs, z2_arr = cl_by[sid], hi_by[sid], z2_by[sid]
    # N2 = BARSLAST(ZT AND REF(ZT,1)): 今日i往左第一个z2日(今日z2不可能, 昨日未涨停)
    j = i
    while j >= 0 and not z2_arr[j]:
        j -= 1
    if j < 0:
        return None
    n2 = i - j               # 今日距末板
    ng = n2 - 1              # 昨日距末板 = 断板天数
    if ng < 1:
        return None
    if mode == "noamp_ng5" and n2 < 6:
        return None
    toph = highs[max(j - 1, 0):j + 1].max()   # VALUEWHEN(z2, HHV(H,2))
    if mode == "varlen":
        # 变长直译: NG=BARSLAST-1, LLV/HHV/LLVBARS第二参数=NG (与strict数学同构)
        seg_c = closes[j + 1:y + 1]
        lowc = seg_c.min()                    # LLV(REF(C,1),NG)
        if lowc / toph - 1 > -0.12:
            return None
        if not (0.08 <= closes[y] / lowc - 1 <= 0.14):
            return None
        if closes[y] / toph - 1 > -0.04:
            return None
        if seg_c.max() / lowc - 1 <= 0.10:    # HHV(REF(C,1),NG)/LLV-1>10%
            return None
        if int(np.argmin(seg_c)) / (len(seg_c) - 1) > 0.6:  # LLVBARS(REF(C,1),NG)>=0.4*(NG-1)
            return None
        return (ng, toph, lowc)
    lowc = closes[max(y - 19, 0):y + 1].min()  # LLV(REF(C,1),20)
    pc_ = closes[y]
    if lowc / toph - 1 > -0.12:               # 蹲深<=-12%
        return None
    if not (0.08 <= pc_ / lowc - 1 <= 0.14):  # 弹回命门8~14
        return None
    if pc_ / toph - 1 > -0.04:                # 不贴顶
        return None
    if mode == "amp":                         # 对照: 研究版断板期振幅(公式无法表达)
        seg_c = closes[j + 1:y + 1]
        if seg_c.max() / seg_c.min() - 1 <= 0.10:
            return None
    if closes[max(y - 2, 0):y + 1].min() <= lowc:  # near3: LLV(REF(C,1),3)>LLV(REF(C,1),20)
        return None
    return (ng, toph, lowc)


# ── strict公式版29笔名单(对账基准, 照抄w2s_u1_check.py strict语义) ──
stk_by = {sid: grp["streak"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
strict_keys = set()
for r in cand.itertuples():
    sid = int(r.sid)
    i = p2i[sid][int(r.pos)]
    y = i - 1
    closes, highs = cl_by[sid], hi_by[sid]
    stk_arr = stk_by[sid]
    j = y
    while j >= 0:
        if stk_arr[j] >= 2:
            break
        j -= 1
    if j < 0:
        continue
    if y - j < 1:
        continue
    seg_c = closes[j + 1:y + 1]
    seg_h = highs[max(j - 1, 0):j + 1]
    low_c_, top_h = seg_c.min(), seg_h.max()
    if low_c_ / top_h - 1 > -0.12:
        continue
    if not (0.08 <= closes[y] / low_c_ - 1 <= 0.14):
        continue
    if closes[y] / top_h - 1 > -0.04:
        continue
    if seg_c.max() / low_c_ - 1 <= 0.10:
        continue
    if len(seg_c) > 1 and int(np.argmin(seg_c)) / (len(seg_c) - 1) > 0.6:
        continue
    strict_keys.add((r.vt_symbol, r.trade_date))

# ── 三变体回测 ──
idx = {sid: {int(p): i for i, p in enumerate(grp["pos"])} for sid, grp in bars.groupby("sid", sort=False)}
closes_all = cl_by
pcs_all = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
n1o = g["open_price"].shift(-1)
bars["n1_open"] = n1o
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


for mode in ("varlen",):
    keep = []
    ng_list = []
    for r in cand.itertuples():
        got = formula_pick(r, mode)
        if got is not None:
            keep.append(r.Index)
            ng_list.append(got[0])
    tg = bars.loc[keep].copy()
    tg["r_d1c"] = tg["n1_close"] / tg["lim_px"] - 1
    tg["res"] = np.where(~tg["is_lim"], "炸板",
                         np.where(tg["r_d1c"] < 0, np.where(tg["n1_lim"], "连板", "封D1负"),
                                  np.where(tg["n1_lim"], "连板", "封D1正")))
    tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
    tg["r_bh"] = [banhold(int(s), int(p)) / lp - 1 for s, p, lp in zip(tg["sid"], tg["pos"], tg["lim_px"])]
    keys = set(zip(tg["vt_symbol"], tg["trade_date"]))
    both = keys & strict_keys
    print("=" * 88)
    print(f"[{mode}] 触发 {len(tg)} 笔 | 差票率 {tg['bad'].mean() * 100:.0f}% | "
          f"连板率 {(tg['res'] == '连板').mean() * 100:.0f}%")
    print(f"  D1收: 均 {tg['r_d1c'].mean() * 100:+.2f}% 中位 {tg['r_d1c'].median() * 100:+.2f}%")
    print(f"  板留: 均 {tg['r_bh'].mean() * 100:+.2f}% 中位 {tg['r_bh'].median() * 100:+.2f}%")
    for yy in (2023, 2024, 2025, 2026):
        sy = tg[tg["trade_date"].dt.year == yy]
        if len(sy):
            print(f"  {yy}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% 中位 {sy['r_bh'].median() * 100:+.2f}%")
    print(f"  对账strict29: 交集 {len(both)} | 仅公式 {len(keys - strict_keys)} | 仅strict {len(strict_keys - keys)}")
    tg["date"] = tg["trade_date"].dt.strftime("%Y-%m-%d")
    if ng_list:
        print(f"  断板天数NG分布: min={min(ng_list)} max={max(ng_list)} "
              f"列表={sorted(ng_list)}")
    if mode == "noamp":
        print(tg[["vt_symbol", "date", "lim_px", "n1_close", "r_d1c", "r_bh"]].head(8).to_string())
        print(tg["r_bh"].describe().to_string())
    for s, d in sorted(keys - strict_keys)[:15]:
        ds = pd.Timestamp(d).strftime("%Y-%m-%d")
        r = tg[(tg["vt_symbol"] == s) & (tg["date"] == ds)].iloc[0]
        print(f"    仅公式: {ds} {s} {r['name']} {r['res']} 板留{r['r_bh'] * 100:+.2f}%")
