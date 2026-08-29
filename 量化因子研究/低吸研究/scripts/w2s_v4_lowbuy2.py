# -*- coding: utf-8 -*-
"""条件C低吸版v2(修正): 昨日首阳条件C筛选 → 今日开盘直接低吸, 池子不要求今日触板.

v1两错: 研究版merge重置index致开盘价取错票(-99%); 近似版池子预筛touch=幸存者偏差(+8%假象).
v2池 = 条件C全部昨日口径筛选 + 排一字开盘(买不到) + 有次日数据; 今日触板与否交给未来.
买入口径: 开盘价买 / 盘中昨收×1.02(开盘<2%). 卖出: D0收/D1/D3/D5/D10/触板卖(≤20日).
两版条件: 研究版(地基=阴跌到点, inline计算不带touch) / 问财近似版(最后涨停锚).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import classify_base, add_outcome

pd.set_option("display.width", 500)


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    hi_by = {sid: grp["high_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    lo_by = {sid: grp["low_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].astype(bool).to_numpy()
             for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}
    big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
    big_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
              for sid, grp in big.groupby("sid", sort=False)}

    # 候选: 条件C基本部分 + 排一字 + 有明日数据 (不要求今日触板!)
    cand = bars[bars["c4b"] & ~bars["d0_open_lim"] & bars["n1_close"].notna()]

    rows = []
    for r in cand.itertuples():
        sid = int(r.sid)
        i = p2i[sid][int(r.pos)]
        cl, hi, lo, zt_arr = cl_by[sid], hi_by[sid], lo_by[sid], zt_by[sid]
        if i + 20 >= len(cl) or i < 2:
            continue
        y = i - 1
        # 研究版地基: 最近≥2板段的断板期 → classify_base
        arr = big_by.get(sid)
        if arr is None or arr[:, 0].searchsorted(int(r.pos), side="left") == 0:
            continue
        li = arr[:, 0].searchsorted(int(r.pos), side="left")
        lp, ph = int(arr[li - 1, 0]), float(arr[li - 1, 1])
        mid_c = cl[lp + 1:i]
        info = classify_base(mid_c, ph, r.prev_close)
        if info is None or info["base"] != "DN":
            is_dn = False
        else:
            is_dn = True
        # 问财近似版L2: 最后涨停锚
        j = y
        while j >= 0 and not zt_arr[j]:
            j -= 1
        approx_ok = False
        if j >= 0:
            seg_c = cl[j + 1:y + 1]
            if len(seg_c):
                top, low_c = cl[j], seg_c.min()
                near3 = seg_c[-3:].min() <= low_c if len(seg_c) >= 3 else True
                approx_ok = (cl[y] / top - 1 <= -0.04) and near3 and (cl[y] / low_c - 1 < 0.03)
        if not (is_dn or approx_ok):
            continue
        pc0 = cl[y]
        o = r.open_price
        d0_lim = round(pc0 * 1.10 + 1e-9, 2)
        d0_touch = hi[i] >= d0_lim - 1e-6
        fut_c = cl[i + 1:i + 21]
        fut_h_after = hi[i + 1:i + 21]
        fut_l_all = lo[i:i + 20]
        lims_after = np.round(np.concatenate(([cl[i]], fut_c[:-1])) * 1.10 + 1e-9, 2)
        touch_after = np.argmax(fut_h_after >= lims_after - 1e-6) + 1 \
            if (fut_h_after >= lims_after - 1e-6).any() else 0
        rec = {"year": str(r.trade_date)[:4], "vt": r.vt_symbol, "d0_touch": d0_touch,
               "is_dn": is_dn, "approx": approx_ok}
        for tag, pb in (("open", o), ("p2", pc0 * 1.02 if (o < pc0 * 1.02 and hi[i] >= pc0 * 1.02 - 1e-6) else np.nan)):
            if pb != pb:
                continue
            rec[tag] = pb
            rec[f"{tag}_d0c"] = cl[i] / pb - 1
            for n in (1, 3, 5, 10):
                rec[f"{tag}_d{n}"] = fut_c[n - 1] / pb - 1 if n <= len(fut_c) else np.nan
            if d0_touch or touch_after:
                rec[f"{tag}_touch"] = (cl[i] if d0_touch else fut_c[touch_after - 1]) / pb - 1
            else:
                rec[f"{tag}_touch"] = fut_c[-1] / pb - 1
            rec[f"{tag}_mae"] = fut_l_all.min() / pb - 1
        rows.append(rec)
    d = pd.DataFrame(rows)
    print(f"条件C候选(昨首阳, 不要求今日触板) → 命中: 研究版(DN) {int(d['is_dn'].sum())} / "
          f"近似版 {int(d['approx'].sum())} / 并集 {len(d)}")
    print(f"今日(D0)实际触板率: {d['d0_touch'].mean() * 100:.0f}%  (低吸会买到不触板的票)")

    def report(sub, label):
        print(f"\n== {label}: n={len(sub)} ==")
        for tag, nm in (("open", "开盘买"), ("p2", "盘中+2%买")):
            if f"{tag}_touch" not in sub.columns:
                continue
            ss = sub[sub[f"{tag}_touch"].notna()]
            if not len(ss):
                continue
            print(f"  [{nm}] n={len(ss)} | D0触板 {ss['d0_touch'].mean() * 100:.0f}%")
            for col, cn in (("d0c", "D0收盘卖"), ("d1", "D1卖"), ("d3", "D3卖"), ("d5", "D5卖"),
                            ("d10", "D10卖"), ("touch", "触板卖(≤20日)"), ("mae", "期间最低")):
                s_ = ss[f"{tag}_{col}"].dropna()
                if len(s_):
                    print(f"      {cn:12s} 均 {s_.mean() * 100:+6.2f} 中位 {s_.median() * 100:+6.2f} "
                          f"胜率 {(s_ > 0).mean() * 100:3.0f}%")
            for yy in ("2023", "2024", "2025", "2026"):
                sy = ss[ss["year"] == yy]
                if len(sy) >= 5:
                    print(f"      {yy}: n={len(sy)} 触板卖均 {sy[f'{tag}_touch'].mean() * 100:+.2f} "
                          f"D5均 {sy[f'{tag}_d5'].mean() * 100:+.2f} 触板卖胜率 "
                          f"{(sy[f'{tag}_touch'] > 0).mean() * 100:.0f}%")
            # 触板/未触板拆分
            for lab, mk in (("D0触板票", ss["d0_touch"]), ("D0未触板票", ~ss["d0_touch"])):
                s2 = ss[mk]
                if len(s2):
                    print(f"      [{lab}] n={len(s2)} 触板卖均 {s2[f'{tag}_touch'].mean() * 100:+.2f} "
                          f"D5均 {s2[f'{tag}_d5'].mean() * 100:+.2f} 期间最低均 {s2[f'{tag}_mae'].mean() * 100:+.2f}")

    report(d[d["is_dn"]], "条件C·研究版(地基=阴跌到点)")
    report(d[d["approx"]], "条件C·问财近似版")


if __name__ == "__main__":
    main()
