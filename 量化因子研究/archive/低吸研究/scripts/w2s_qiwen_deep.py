# -*- coding: utf-8 -*-
"""缓启·企稳代入验证 + 缓启组深层形态统计.

1. 四组(缓启企稳版)对 弱转强v3 的覆盖: 票级/波级/簇级/五组分类交叉
2. 缓启结构内: 前日×昨日涨幅矩阵 / 距上波顶部背离度 / 断板期间坡度平稳度
"""
import sys

sys.path.insert(0, "/app")
import os

import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from sqlalchemy import create_engine

pd.set_option("display.width", 320)

bars, segs, clusters, waves, bounds = w.load_all()
w._ths_daily(bars)
g = bars.groupby("sid", sort=False)
bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
bars["n1_open"] = g["open_price"].shift(-1)
bars["n1_close"] = g["close_price"].shift(-1)
bars["p2_yin"] = (g["close_price"].shift(2) < g["open_price"].shift(2)).fillna(False).astype(bool)
bars["p2_chg"] = g["close_price"].shift(2) / g["close_price"].shift(3) - 1
eng = create_engine(os.environ["DATABASE_URL"])
opens_map = w._open_counts(eng, bars)
bars["opens"] = [opens_map.get((s, p), np.nan) for s, p in zip(bars["sid"], bars["pos"])]
bars["c_rzq"] = (bars["c_rzq_daily"] & (bars["opens"] > 5)).fillna(False).astype(bool)
cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()

idx = {}
for sid, grp in bars.groupby("sid", sort=False):
    idx[sid] = {"p2i": {int(p): i for i, p in enumerate(grp["pos"])},
                "c": grp["close_price"].to_numpy(), "pc": grp["prev_close"].to_numpy(),
                "chg": (grp["close_price"].pct_change()).to_numpy()}
def bh(sid, pos0):
    bd = idx.get(sid)
    if bd is None:
        return np.nan
    for d in range(1, 21):
        i = bd["p2i"].get(int(pos0) + d)
        if i is None:
            j = bd["p2i"].get(int(pos0) + d - 1)
            return bd["c"][j] if j is not None else np.nan
        lim = round(bd["pc"][i] * 1.10 + 1e-9, 2)
        if abs(bd["c"][i] - lim) > 1e-6:
            return bd["c"][i]
    return bd["c"][bd["p2i"][int(pos0) + 20]]

wave_keys = set(zip(waves["sid"], waves["first_pos"]))
v3_stocks = set(waves.merge(bars[["sid", "vt_symbol"]].drop_duplicates(), on="sid")["vt_symbol"])
grp_map = w.assign_groups(clusters, waves).set_index("cluster_id")["group"]
wv_all = waves.merge(bars[["sid", "vt_symbol"]].drop_duplicates(), on="sid")
wv_all["group"] = wv_all["cluster_id"].map(grp_map)

# ── ① 缓启·企稳代入四组: 覆盖 ──
D_QW = (bars["mx20"] == 2) & (bars["mx4"] < 2) & bars["p2_yin"] & bars["p_yang"] & (bars["p_chg"] < 0.03)
Z_qiwen = bars["c_by"] | bars["c_kj"] | D_QW | bars["c_rzq"]
Z_old = bars["c_by"] | bars["c_kj"] | bars["c_dh"] | bars["c_rzq"]

def coverage(mask, label):
    hits = bars.loc[mask & cond_ok, ["sid", "pos", "vt_symbol"]]
    hset = set(zip(hits["sid"], hits["pos"]))
    tst = set(hits["vt_symbol"])
    wv = waves[waves["wave_no"] > 1]
    wc = sum(1 for s, p in zip(wv["sid"], wv["first_pos"]) if (s, p) in hset)
    wv2 = waves.copy()
    wv2["hit"] = [(s, p) in hset for s, p in zip(wv2["sid"], wv2["first_pos"])]
    cl = wv2.groupby("cluster_id")["hit"].any()
    print(f"{label}: 票级 {len(v3_stocks & tst)}/634 ({len(v3_stocks & tst) / 634 * 100:.0f}%) | "
          f"波级(非首波) {wc}/1018 ({wc / 10.18:.0f}%) | 簇级 {int(cl.sum())}/780 ({cl.mean() * 100:.0f}%)")
    # 五组分类交叉(簇级)
    wv_all["hit"] = wv_all["cluster_id"].isin(cl[cl].index)
    tab = wv_all.groupby("group").agg(簇数=("hit", "size"))
    tab["命中簇"] = wv_all[wv_all["hit"]].groupby("group").size()
    print(tab.fillna(0).assign(覆盖pct=lambda x: (x["命中簇"] / x["簇数"] * 100).round(0)).to_string())

print("=" * 100)
print("== ① 缓启·企稳代入后的覆盖率 ==")
coverage(Z_qiwen, "四组·企稳版(缓启→企稳子集)")
print()
coverage(Z_old, "对照·四组(缓启原版)")

# ── ② 缓启结构内深层形态统计 ──
big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
big_by_sid = {sid: grp[["last_pos", "high_price"]].to_numpy() for sid, grp in big.groupby("sid", sort=False)}

DH = bars[(bars["mx20"] == 2) & (bars["mx4"] < 2) & cond_ok].copy()
rows = []
for r in DH.itertuples():
    bd = idx.get(r.sid)
    arr = big_by_sid.get(r.sid)
    i = int(r.pos)
    if bd is None or arr is None:
        continue
    li = arr[:, 0].searchsorted(i, side="left")
    if li == 0:
        continue
    lp, ph = int(arr[li - 1, 0]), float(arr[li - 1, 1])
    j0, j1 = bd["p2i"].get(lp + 1), bd["p2i"].get(i - 1)   # 断板期: 上波末板次日..昨日
    if j0 is None or j1 is None or j1 - j0 + 1 < 2:
        continue
    chg = bd["chg"][j0: j1 + 1]
    chg = chg[~np.isnan(chg)]
    n = len(chg)
    up = (chg > 0.005).sum() / n
    dn = (chg < -0.005).sum() / n
    flat = 1 - up - dn
    rows.append({
        "sid": r.sid, "pos": r.pos, "vt_symbol": r.vt_symbol,
        "p2_chg": r.p2_chg, "p_chg": r.p_chg, "is_lim": r.is_lim,
        "n1_close": r.n1_close, "n1_lim": r.n1_lim,
        "buy": r.lim_px,
        "gap": n + 1,
        "pull": r.prev_close / ph - 1,            # 昨收距上波顶
        "up": up, "dn": dn, "flat": flat,
        "eff": abs(chg.sum()) / (np.abs(chg).sum() + 1e-9),   # 单边效率(1=直线,0=折腾)
        "min_chg": chg.min() if n else np.nan,
        "cum": chg.sum(),
    })
df = pd.DataFrame(rows)
df["r_d1c"] = df["n1_close"] / df["buy"] - 1
df["r_bh"] = pd.Series([bh(s, p) for s, p in zip(df["sid"], df["pos"])]) / df["buy"] - 1
df["is_wv"] = [(s, p) in wave_keys for s, p in zip(df["sid"], df["pos"])]
df["qiwen"] = (df["p_chg"] < 0.03) & (df["p_chg"] > 0) & df["p_chg"].notna()  # 粗占位, 下用原始bars口径
qw_keys = set(zip(bars.loc[D_QW & cond_ok, "sid"], bars.loc[D_QW & cond_ok, "pos"]))
df["qiwen"] = [(s, p) in qw_keys for s, p in zip(df["sid"], df["pos"])]
print(f"\n== ② 缓启结构 n={len(df)} (可计算断板特征) ==")

def pstat(dfsub, by):
    def _row(s):
        sealed = s[s["is_lim"]]
        return pd.Series({"n": len(s), "封板%": round(s["is_lim"].mean() * 100),
                          "D1收%": round(s["r_d1c"].mean() * 100, 2),
                          "板留%": round(s["r_bh"].mean() * 100, 2),
                          "胜率%": round((s["r_d1c"] > 0).mean() * 100),
                          "再板%": round(sealed["n1_lim"].mean() * 100) if len(sealed) else np.nan,
                          "波覆盖": int(s["is_wv"].sum())})
    return dfsub.groupby(by, observed=True).apply(_row, include_groups=False)

print("\n-- 2a 前日涨幅 × 昨日涨幅 矩阵 (p2_chg桶×p_chg桶 → 板留%) --")
df["b2"] = pd.cut(df["p2_chg"], [-1, -0.05, -0.02, 0, 1], labels=["前日<-5", "-5~-2", "-2~0", "前日>0"])
df["b1"] = pd.cut(df["p_chg"], [-1, -0.02, 0, 0.02, 0.05, 1], labels=["昨<-2", "-2~0", "0~2", "2~5", "昨>5"])
print("n:")
print(pd.crosstab(df["b2"], df["b1"]).to_string())
print("板留%:")
print(df.pivot_table(index="b2", columns="b1", values="r_bh", aggfunc=lambda s: round(s.mean() * 100, 2)).to_string())
print("D1收%:")
print(df.pivot_table(index="b2", columns="b1", values="r_d1c", aggfunc=lambda s: round(s.mean() * 100, 2)).to_string())

print("\n-- 2b 距上波顶部背离度 --")
df["pb"] = pd.cut(df["pull"], [-1, -0.30, -0.20, -0.10, -0.04, 0.5],
                  labels=["深洗<-30", "-30~-20", "-20~-10", "-10~-4", "贴顶>-4"])
print(pstat(df, "pb").to_string())

print("\n-- 2c 断板期间坡度形态 (涨日/跌日/横盘日占比主导) --")
def slope(r):
    if r["flat"] >= 0.5:
        return "横盘主导"
    if r["up"] >= 0.55:
        return "上坡主导"
    if r["dn"] >= 0.55:
        return "下坡主导"
    return "涨跌互现"
df["slope"] = df.apply(slope, axis=1)
print(pstat(df, "slope").to_string())

print("\n-- 2d 单边效率(路径平滑度) --")
df["eb"] = pd.cut(df["eff"], [-0.01, 0.2, 0.4, 0.6, 1.01], labels=["纯折腾<0.2", "0.2~0.4", "0.4~0.6", "单边>0.6"])
print(pstat(df, "eb").to_string())

print("\n-- 2e 断板天数 --")
df["gb"] = pd.cut(df["gap"], [0, 6, 10, 15, 25], labels=["5-6日", "7-10", "11-15", "16-20"])
print(pstat(df, "gb").to_string())

print("\n-- 2f 企稳 × 背离度 交叉 --")
print(pstat(df, ["qiwen", "pb"]).to_string())

print("\n-- 2g 企稳 × 坡度 交叉 --")
print(pstat(df, ["qiwen", "slope"]).to_string())
