# -*- coding: utf-8 -*-
"""补涨阴·2026-08 好票vs差票 底盘对比: 为什么同条件结局两极."""
import sys

sys.path.insert(0, "/app")
import os

import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)
pd.set_option("display.max_columns", 60)

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

cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()
YM = sys.argv[1] if len(sys.argv) > 1 else "2026-08"
tg = bars[bars["c_by"] & cond_ok & (bars["trade_date"].dt.strftime("%Y-%m") == YM)].copy()
print(f"补涨阴·{YM} 触发 {len(tg)} 笔 (修复后口径)")

rows = []
for r in tg.itertuples():
    sid = int(r.sid)
    arr = big_by.get(sid)
    i = p2i_by[sid][int(r.pos)]
    li = arr[:, 0].searchsorted(int(r.pos), side="left")
    if li == 0:
        continue
    lp, ph = int(arr[li - 1, 0]), float(arr[li - 1, 1])
    # 上波高度: 上波段streak
    seg_h = segs[(segs["sid"] == sid) & (segs["last_pos"] == lp)]["height"].max()
    chg = chg_by[sid]
    j0, j1 = p2i_by[sid].get(lp + 1), i - 1           # 断板期[上波末板次日, 昨日]
    mid = chg[j0: j1 + 1] if (j0 is not None and j1 is not None) else np.array([np.nan])
    mid = mid[~np.isnan(mid)]
    n_mid = len(mid)
    # 断板期间最低回撤(期间最低价/上波顶-1)
    low_seg = bars[(bars["sid"] == sid) & (bars["pos"] > lp) & (bars["pos"] < int(r.pos))]["low_price"]
    low_dd = low_seg.min() / ph - 1 if len(low_seg) else np.nan
    # 均线乖离(昨收): 用bars内 rolling 需要历史, 手工算
    closes = bars.loc[bars["sid"] == sid, "close_price"].to_numpy()
    pc_i = i - 1
    ma = lambda n: closes[pc_i - n + 1: pc_i + 1].mean() if pc_i + 1 >= n else np.nan
    rows.append({
        "code": r.vt_symbol, "name": r.name, "date": r.trade_date.strftime("%m-%d"),
        "res": "炸板" if not r.is_lim else ("封D1负" if (r.n1_close / r.lim_px - 1) < 0
                                            else ("连板" if r.n1_lim else "封D1正")),
        "r1c": (r.n1_close / r.lim_px - 1) * 100,
        "上波高": seg_h, "断板": int(r.pos) - lp, "回撤%": (r.prev_close / ph - 1) * 100,
        "最低回撤%": low_dd * 100,
        "洗后弹%": (r.prev_close / (ph * (1 + low_dd)) - 1) * 100 if low_dd == low_dd else np.nan,
        "下坡日%": ((mid < -0.005).mean() * 100) if n_mid else np.nan,
        "昨幅%": r.p_chg * 100, "昨上影%": (r.p_ush if r.p_ush == r.p_ush else 0) * 100,
        "ret5%": (r.prev_close / closes[pc_i - 5] - 1) * 100 if pc_i >= 5 else np.nan,
        "ret20%": (r.prev_close / closes[pc_i - 20] - 1) * 100 if pc_i >= 20 else np.nan,
        "bias10%": (r.prev_close / ma(10) - 1) * 100 if ma(10) == ma(10) else np.nan,
        "bias20%": (r.prev_close / ma(20) - 1) * 100 if ma(20) == ma(20) else np.nan,
    })
df = pd.DataFrame(rows)
df["好坏"] = np.where(df["res"].isin(["炸板", "封D1负"]), "差", "好")
print(f"差票 {int((df['好坏'] == '差').sum())} / 好票 {int((df['好坏'] == '好').sum())}\n")

cmp_cols = ["上波高", "断板", "回撤%", "最低回撤%", "洗后弹%", "下坡日%", "昨幅%", "昨上影%",
            "ret5%", "ret20%", "bias10%", "bias20%"]
print("== 底盘特征: 差票 vs 好票 (均值 / 中位数) ==")
tab = df.groupby("好坏")[cmp_cols].agg(["mean", "median"]).round(1).T
print(tab.to_string())

print("\n== 分桶差票率 ==")
for dim, bins, labs in [
    ("回撤%", [-99, -20, -10, -4, 0], ["深洗<-20", "-20~-10", "-10~-4", "贴顶>-4"]),
    ("断板", [0, 6, 11, 16, 99], ["2-5", "6-10", "11-15", "16+"]),
    ("上波高", [1.5, 2.5, 3.5, 99], ["2板", "3板", "4板+"]),
    ("洗后弹%", [-99, -2, 2, 99], ["贴底<-2", "中位-2~2", "弹高>2"]),
    ("bias10%", [-99, -5, 0, 5, 99], ["<-5", "-5~0", "0~5", ">5"]),
    ("ret20%", [-99, 0, 10, 99], ["<0", "0~10", ">10"]),
]:
    b = pd.cut(df[dim], bins, labels=labs)
    t = df.groupby(b, observed=True)["好坏"].agg(
        n="size", 差票率=lambda s: round((s == "差").mean() * 100))
    print(f"\n{dim}:")
    print(t.to_string())

pd.set_option("display.max_rows", 100)
print("\n== 全部票明细 (差票在前, 共进股份★) ==")
df["_s"] = (df["好坏"] == "差").astype(int)
df = df.sort_values(["_s", "r1c"])
for _, r in df.iterrows():
    star = "★" if "共进" in r["name"] else " "
    print(f"{star}{r['code'][:6]} {r['name']:<5s} {r['date']} {r['res']:４<４}".replace("４", " ")
          + f" D1{r['r1c']:+6.1f}% | 上波{r['上波高']:.0f}板 断{r['断板']:>2.0f}日 "
          f"回撤{r['回撤%']:+6.1f}% 最低{r['最低回撤%']:+6.1f}% 弹{r['洗后弹%']:+5.1f}% "
          f"下坡{r['下坡日%']:>3.0f}% 昨{r['昨幅%']:+5.1f}% 影{r['昨上影%']:.1f}% "
          f"r5{r['ret5%']:+6.1f}% r20{r['ret20%']:+6.1f}% b10{r['bias10%']:+5.1f}%")
