# -*- coding: utf-8 -*-
"""补涨阴全量触发(1905笔) 底盘特征挖掘 → 差票过滤条件确定.

方法: 全量分桶 → 环境分层(昨涨停家数) → 候选过滤逐条叠加 → 2023-25选/2026外推验证.
差票 = D0炸板 或 封板但D1收<0(相对涨停价买入). 全部条件为 D-1 可观测(同花顺可表达).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)

bars, segs, clusters, waves, bounds = w.load_all()
w._ths_daily(bars)
g = bars.groupby("sid", sort=False)
bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
bars["n1_open"] = g["open_price"].shift(-1)
bars["n1_close"] = g["close_price"].shift(-1)

big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
big_by = {sid: grp.sort_values("last_pos")[["last_pos", "high_price"]].to_numpy()
          for sid, grp in big.groupby("sid", sort=False)}
chg_by = {sid: grp["close_price"].pct_change().to_numpy()
          for sid, grp in bars.groupby("sid", sort=False)}
p2i_by = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
          for sid, grp in bars.groupby("sid", sort=False)}
close_arr = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
low_arr = {sid: grp["low_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
seg_h_by = {(int(r.sid), int(r.last_pos)): int(r.height)
             for r in segs[segs["height"] >= 2].itertuples()}

# 环境: 昨日涨停家数 + 20日涨停均值趋势
mkt = bars.groupby("trade_date")["is_lim"].sum().rename("mkt_lim").reset_index()
mkt["mkt_prev"] = mkt["mkt_lim"].shift(1)
mkt["mkt20"] = mkt["mkt_lim"].rolling(20, min_periods=10).mean()
mkt["mkt20_slope"] = mkt["mkt20"] - mkt["mkt20"].shift(5)
mkt_map = mkt.set_index("trade_date")[["mkt_prev", "mkt20", "mkt20_slope"]]

cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()
tg = bars[bars["c_by"] & cond_ok].copy()
tg = tg.merge(mkt_map, left_on="trade_date", right_index=True, how="left")
print(f"补涨阴全量触发 {len(tg)} 笔")

rows = []
for r in tg.itertuples():
    sid = int(r.sid)
    arr = big_by.get(sid)
    if arr is None:
        continue
    i = p2i_by[sid][int(r.pos)]
    li = arr[:, 0].searchsorted(int(r.pos), side="left")
    if li == 0:
        continue
    lp, ph = int(arr[li - 1, 0]), float(arr[li - 1, 1])
    closes = close_arr[sid]
    pc_i = i - 1
    ma = lambda n: closes[pc_i - n + 1: pc_i + 1].mean() if pc_i + 1 >= n else np.nan
    lows = low_arr[sid][lp + 1: i]
    low_dd = lows.min() / ph - 1 if len(lows) else np.nan
    r1c = r.n1_close / r.lim_px - 1
    rows.append({
        "year": r.trade_date.year, "sid": sid, "pos": int(r.pos),
        "bad": (not r.is_lim) or (r1c < 0),
        "r1c": r1c * 100, "sealed": bool(r.is_lim),
        "seg_h": seg_h_by.get((sid, lp), np.nan),
        "gap": int(r.pos) - lp,
        "pull": (r.prev_close / ph - 1) * 100,
        "low_dd": low_dd * 100 if low_dd == low_dd else np.nan,
        "reb": (r.prev_close / (ph * (1 + low_dd)) - 1) * 100 if low_dd == low_dd else np.nan,
        "p_chg": r.p_chg * 100, "p_ush": (r.p_ush if r.p_ush == r.p_ush else 0) * 100,
        "ret5": (r.prev_close / closes[pc_i - 5] - 1) * 100 if pc_i >= 5 else np.nan,
        "ret20": (r.prev_close / closes[pc_i - 20] - 1) * 100 if pc_i >= 20 else np.nan,
        "bias10": (r.prev_close / ma(10) - 1) * 100 if ma(10) == ma(10) else np.nan,
        "bias20": (r.prev_close / ma(20) - 1) * 100 if ma(20) == ma(20) else np.nan,
        "mkt_prev": r.mkt_prev, "mkt20_slope": r.mkt20_slope,
    })
df = pd.DataFrame(rows)
print(f"差票率基线 {df['bad'].mean() * 100:.0f}% (n={len(df)})\n")


def bucket_bad(dfsub, dim, bins, labs, label=""):
    b = pd.cut(dfsub[dim], bins, labels=labs)
    t = dfsub.groupby(b, observed=True)["bad"].agg(n="size", 差票率=lambda s: round(s.mean() * 100))
    t["保留%"] = (t["n"] / len(dfsub) * 100).round(0)
    print(f"\n{label or dim}:")
    print(t.to_string())


print("=" * 80)
print("== 一阶: 全量分桶差票率 ==")
bucket_bad(df, "pull", [-99, -25, -15, -8, -4, 99], ["P 深洗<-25", "P -25~-15", "P -15~-8", "P -8~-4", "P 贴顶>-4"])
bucket_bad(df, "gap", [0, 6, 11, 16, 99], ["G 断2-5", "G 6-10", "G 11-15", "G 16+"])
bucket_bad(df, "reb", [-99, -2, 2, 8, 16, 99], ["R 趴底<-2", "R -2~2", "R 弹2~8", "R 弹8~16", "R 弹>16"])
bucket_bad(df, "seg_h", [1.5, 2.5, 3.5, 4.5, 99], ["H 2板", "H 3板", "H 4板", "H 5板+"])
bucket_bad(df, "ret5", [-99, -8, -3, 0, 99], ["5 <-8", "5 -8~-3", "5 -3~0", "5 >0"])
bucket_bad(df, "ret20", [-99, -5, 5, 15, 99], ["20 <-5", "20 -5~5", "20 5~15", "20 >15"])
bucket_bad(df, "bias10", [-99, -8, -3, 0, 3, 99], ["B <-8", "B -8~-3", "B -3~0", "B 0~3", "B >3"])
bucket_bad(df, "p_chg", [-10, -6, -3, 0], ["昨<-6", "昨-6~-3", "昨-3~0"])
bucket_bad(df, "mkt_prev", [0, 45, 70, 100, 999], ["M昨停<45", "M 45-70", "M 70-100", "M >100"])
bucket_bad(df, "low_dd", [-99, -30, -20, -12, 0], ["L <-30", "L -30~-20", "L -20~-12", "L >-12"])

print("\n" + "=" * 80)
print("== 环境分层: 昨涨停家数 × 主要维度 (找跨环境稳定信号) ==")
for env, ev in [("冷<45", df["mkt_prev"] < 45), ("中45-100", df["mkt_prev"].between(45, 100)),
                ("热>100", df["mkt_prev"] > 100)]:
    sub = df[ev.fillna(False)]
    if len(sub) < 50:
        continue
    print(f"\n--- 环境 {env} (n={len(sub)}, 差票率{sub['bad'].mean() * 100:.0f}%) ---")
    for dim, bins, labs in [
        ("pull", [-99, -15, -4, 99], ["深洗<-15", "中-15~-4", "贴顶>-4"]),
        ("reb", [-99, 2, 8, 99], ["趴/低<2", "弹2~8", "弹>8"]),
        ("gap", [0, 6, 11, 99], ["2-5", "6-10", "11+"]),
        ("bias10", [-99, -3, 3, 99], ["<-3", "-3~3", ">3"]),
        ("ret20", [-99, 0, 15, 99], ["<0", "0~15", ">15"]),
    ]:
        b = pd.cut(sub[dim], bins, labels=labs)
        t = sub.groupby(b, observed=True)["bad"].agg(n="size", 差票率=lambda s: round(s.mean() * 100))
        print(f"{dim}: " + " | ".join(f"{ix}(n={int(r['n'])},{r['差票率']}%)" for ix, r in t.iterrows()))

print("\n" + "=" * 80)
print("== 候选过滤条件逐条叠加 (全量 + 分年稳定性 + 板留对照) ==")
idx = {sid: {int(p): i for i, p in enumerate(grp["pos"])} for sid, grp in bars.groupby("sid", sort=False)}
closes_all = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
pcs = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}


def banhold(sid, pos0):
    bd_p, bd_c = idx.get(sid), closes_all.get(sid)
    if bd_p is None:
        return np.nan
    for d in range(1, 21):
        j = bd_p.get(pos0 + d)
        if j is None:
            k = bd_p.get(pos0 + d - 1)
            return bd_c[k] if k is not None else np.nan
        lim = round(pcs[sid][j] * 1.10 + 1e-9, 2)
        if abs(bd_c[j] - lim) > 1e-6:
            return bd_c[j]
    return bd_c[bd_p.get(pos0 + 20, len(bd_c) - 1)]


buy_px = {int(r.sid): {} for r in tg.itertuples()}
for r in tg.itertuples():
    buy_px[int(r.sid)][int(r.pos)] = r.lim_px
df["r_bh"] = [banhold(s, p) / buy_px[s][p] - 1 if p in buy_px.get(s, {}) else np.nan
              for s, p in zip(df["sid"], df["pos"])]

FILTERS = {
    "F0 无过滤(基线)": pd.Series(True, index=df.index),
    "F1 剔贴顶(回撤<=-4%)": df["pull"] <= -4,
    "F2 剔趴底(洗后弹>=2%)": df["reb"] >= 2,
    "F3 剔断板2-5日": df["gap"] >= 6,
    "F4 剔20日涨幅>15%": df["ret20"] <= 15,
    "F5 昨涨停家数<=100": df["mkt_prev"] <= 100,
    "F1+F2": (df["pull"] <= -4) & (df["reb"] >= 2),
    "F1+F2+F4": (df["pull"] <= -4) & (df["reb"] >= 2) & (df["ret20"] <= 15),
    "F1+F2+F4+F5": (df["pull"] <= -4) & (df["reb"] >= 2) & (df["ret20"] <= 15) & (df["mkt_prev"] <= 100),
    "全加F3": (df["pull"] <= -4) & (df["reb"] >= 2) & (df["ret20"] <= 15) & (df["mkt_prev"] <= 100) & (df["gap"] >= 6),
}
res = []
for name, m in FILTERS.items():
    sub = df[m.fillna(False)]
    row = {"过滤": name, "n": len(sub), "保留%": round(len(sub) / len(df) * 100),
           "差票率%": round(sub["bad"].mean() * 100),
           "D1收%": round(sub["r1c"].mean(), 2), "板留%": round(sub["r_bh"].mean() * 100, 2)}
    for y in (2023, 2024, 2025, 2026):
        sy = sub[sub["year"] == y]
        row[f"{y}差%"] = round(sy["bad"].mean() * 100) if len(sy) else np.nan
        row[f"{y}板留"] = round(sy["r_bh"].mean() * 100, 1) if len(sy) else np.nan
    res.append(row)
print(pd.DataFrame(res).to_string(index=False))
