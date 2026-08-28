# -*- coding: utf-8 -*-
"""同花顺四组条件调整探索: D缓启新组 / E弱转强改向 / A/B/C微观条件松紧.

每个候选条件输出: 触发回测(n/封板%/D1再板%/板留断走%) + V3覆盖(非首波/簇).
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
eng = create_engine(os.environ["DATABASE_URL"])
opens_map = w._open_counts(eng, bars)
bars["opens"] = [opens_map.get((s, p), np.nan) for s, p in zip(bars["sid"], bars["pos"])]

wave_keys = set(zip(waves["sid"], waves["first_pos"]))
cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()

idx = {}
for sid, grp in bars.groupby("sid", sort=False):
    idx[sid] = {"p2i": {int(p): i for i, p in enumerate(grp["pos"])},
                "c": grp["close_price"].to_numpy(), "pc": grp["prev_close"].to_numpy()}


def banhold_px(sid, pos0):
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
    i = bd["p2i"].get(int(pos0) + 20)
    return bd["c"][i] if i is not None else np.nan


# 候选条件(全部昨日口径; mx20/mx4=截至昨日窗口最大连板)
base3 = bars["mx20"] >= 3
A = bars["c_by"].copy()                                  # 补涨阴(原)
B = bars["c_by2"].copy()                                 # 补涨阳(原)
C = bars["c_kj"].copy()                                  # 二板快接(原)
R5 = (bars["c_rzq_daily"] & (bars["opens"] > 5)).fillna(False)
D_str = (bars["mx20"] == 2) & (bars["mx4"] < 2)          # 双板且断口>=5日(缓启结构)
E0 = bars["c_rzq_daily"].copy()                          # 昨日涨停+前20>=3 (不筛开板)

CANDS = {
    "A 补涨阴(原)": A,
    "B 补涨阳(原)": B,
    "C 二板快接(原)": C,
    "R5 弱转强开板>5(原)": R5,
    "D1 缓启纯结构": D_str,
    "D2 缓启+昨收阴": D_str & bars["p_yin"],
    "D3 缓启+昨阴+跌>-9%": D_str & bars["p_yin"] & (bars["p_chg"] > -0.09),
    "D4 缓启+昨阴+跌>-9+上影<4": D_str & bars["p_yin"] & (bars["p_chg"] > -0.09) & (bars["p_ush"] < 0.04),
    "E0 昨日涨停全集": E0,
    "E1 开板<=2(硬板向)": (E0 & (bars["opens"] <= 2)).fillna(False),
    "E2 开板=0(纯硬板)": (E0 & (bars["opens"] == 0)).fillna(False),
    "A-去上影": base3 & bars["p_yin"] & (bars["p_ret3"] < 0.06) & (bars["p_chg"] > -0.09),
    "A-去涨幅": base3 & bars["p_yin"] & (bars["p_ush"] < 0.04) & (bars["p_chg"] > -0.09),
    "A-纯(仅高度+阴)": base3 & bars["p_yin"],
    "B-纯(仅高度+阳)": base3 & bars["p_yang"],
    "C-去昨跌": (bars["mx4"] == 2) & bars["p_yin"],
}

wv = waves[["cluster_id", "sid", "wave_no", "first_pos"]].copy()
rows = []
for label, m in CANDS.items():
    mm = m.fillna(False).astype(bool)
    tg = bars[mm & cond_ok]
    n = len(tg)
    if n:
        buy = tg["lim_px"]
        r1c = tg["n1_close"] / buy - 1
        r1o = tg["n1_open"] / buy - 1
        bh = pd.Series([banhold_px(s, p) for s, p in zip(tg["sid"], tg["pos"])])
        rbh = (bh / buy.to_numpy() - 1).dropna()
        sealed = tg["is_lim"]
        reban = tg.loc[sealed, "n1_lim"].mean() if sealed.any() else np.nan
        s1o, s1c = r1o.mean() * 100, r1c.mean() * 100
        wr = (r1c > 0).mean() * 100
        bhv = rbh.mean() * 100
        wave1 = sum(1 for s, p in zip(tg["sid"], tg["pos"]) if (s, p) in wave_keys)
    else:
        s1o = s1c = wr = bhv = reban = np.nan
        wave1 = 0
    # 覆盖: 波首板行命中
    hits = bars.loc[mm, ["sid", "pos"]]
    hset = set(zip(hits["sid"], hits["pos"]))
    wv[f"_{label[:2]}"] = [(s, p) in hset for s, p in zip(wv["sid"], wv["first_pos"])]
    cov_w = wv.loc[(wv[f"_{label[:2]}"]) & (wv["wave_no"] > 1)].shape[0]
    cl_cov = wv.loc[wv[f"_{label[:2]}"], "cluster_id"].nunique()
    rows.append({"条件": label, "触发n": n, "封板%": round(tg["is_lim"].mean() * 100) if n else np.nan,
                 "D1再板%": round(reban * 100) if n else np.nan, "D1开%": round(s1o, 2) if n else np.nan,
                 "D1收%": round(s1c, 2) if n else np.nan, "胜率%": round(wr) if n else np.nan,
                 "板留断走%": round(bhv, 2) if n else np.nan,
                 "波覆盖(非首波)": cov_w, "簇覆盖": cl_cov, "V3波首板": wave1})

print("=" * 120)
print("== 候选条件: 触发回测 + V3覆盖 (板留断走=断板日收盘卖) ==")
print(pd.DataFrame(rows).to_string(index=False))

# 组合总覆盖
def combo_cov(masks, label):
    total = np.zeros(len(bars), dtype=bool)
    for m in masks:
        total |= m.fillna(False).astype(bool).to_numpy()
    hits = bars.loc[total, ["sid", "pos"]]
    hset = set(zip(hits["sid"], hits["pos"]))
    hit = np.fromiter(((s, p) in hset for s, p in zip(wv["sid"], wv["first_pos"])), bool, len(wv))
    wv2 = wv[hit & (wv["wave_no"] > 1)]
    print(f"{label}: 非首波覆盖 {len(wv2)}/1018 ({len(wv2)/10.18:.0f}%) | "
          f"簇覆盖 {wv2['cluster_id'].nunique()}/780 ({wv2['cluster_id'].nunique()/7.8:.0f}%)")

print("\n== 组合总覆盖 ==")
combo_cov([A, B, C, R5], "原四组")
combo_cov([A, B, C, D_str & bars["p_yin"] & (bars["p_chg"] > -0.09)],
          "A+B+C+D3(缓启新组)")
combo_cov([A, B, C, D_str & bars["p_yin"] & (bars["p_chg"] > -0.09),
           (E0 & (bars["opens"] <= 2)).fillna(False)], "A+B+C+D3+E1(硬板弱转强)")
