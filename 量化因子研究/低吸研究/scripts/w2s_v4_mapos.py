# -*- coding: utf-8 -*-
"""主人均线标尺假设验证(2026-08-29): ①4+阴坑深与连板高度的关系(高度越高蹲越深?)
②D-1收盘所处均线位置带(MA5/10/20/30/60)作为深度标尺 ③深度×均线带×阴阳 重新组织地形.

均线带(昨收=D0前收): MA5上方 / MA5~10 / MA10~20 / MA20~30 / MA30~60 / MA60下方.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

DD_LABS = ["浅-8~-4%", "中-15~-8", "深-25~-15", "超深<-25%"]
BANDS = ["MA5上方", "MA5~10", "MA10~20", "MA20~30", "MA30~60", "MA60下方"]
BAND_CN = {"MA5上方": "MA5上", "MA5~10": "5~10", "MA10~20": "10~20",
           "MA20~30": "20~30", "MA30~60": "30~60", "MA60下方": "MA60下"}


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    # 均线(昨收口径: 昨日均线) — 挂列到bars, build_base的tg自带(merge不重置列值, 行内取不错位)
    for n in (5, 10, 20, 30, 60):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))

    def band(r):
        c = r.prev_close
        if c != c or r.ma60 != r.ma60:
            return None
        if r.ma5 == r.ma5 and c > r.ma5:
            return "MA5上方"
        if r.ma10 == r.ma10 and c > r.ma10:
            return "MA5~10"
        if r.ma20 == r.ma20 and c > r.ma20:
            return "MA10~20"
        if r.ma30 == r.ma30 and c > r.ma30:
            return "MA20~30"
        if c > r.ma60:
            return "MA30~60"
        return "MA60下方"

    tgs = {}
    for tag, c in (("c4a", "c4a"), ("c4b", "c4b"), ("c4c", "c4c"), ("c4d", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        tg["均线带"] = [band(r) for r in tg.itertuples()]
        tgs[tag] = tg

    print("=" * 110)
    print("== ① 4+阴: 连板高度 × 坑深 (n / 坑深中位% / 板留%) ==")
    t = tgs["c4c"][tgs["c4c"]["base"] != "HIGH"]
    t = t.assign(hh=np.where(t["seg_h"] >= 6, "6+", t["seg_h"].astype(int).astype(str)) + "板")
    for h in sorted(t["hh"].unique()):
        s = t[t["hh"] == h]
        print(f"  上波{h}: n={len(s)} 坑深中位 {s['low_dd'].median() * 100:+.0f}% "
              f"均值 {s['low_dd'].mean() * 100:+.0f}% 板留 {s['r_bh'].mean() * 100:+.2f}% "
              f"破MA30率 {(s['均线带'].isin(['MA30~60', 'MA60下方'])).mean() * 100:.0f}%")
    hh_num = pd.to_numeric(t["seg_h"])
    print(f"  corr(连板高度, 坑深) = {hh_num.corr(t['low_dd']):+.2f}")

    print("\n== ② 四组: D-1收盘均线带 × 板留 (坑池=非HIGH) ==")
    for tag, name in (("c4a", "2板阴"), ("c4b", "2板阳"), ("c4c", "4+阴"), ("c4d", "4+阳")):
        pit = tgs[tag][tgs[tag]["base"] != "HIGH"]
        parts = []
        for b in BANDS:
            s = pit[pit["均线带"] == b]
            parts.append(f"{BAND_CN[b]} {len(s)}/{s['r_bh'].mean() * 100:+.2f}"
                         if len(s) else f"{BAND_CN[b]} —")
        print(f"  {name:6s}: " + " | ".join(parts))

    print("\n== ③ 深度 × 均线带 (4+阴 / 2板阴) 板留% ==")
    for tag, name in (("c4c", "4+阴"), ("c4a", "2板阴")):
        pit = tgs[tag][tgs[tag]["base"] != "HIGH"].copy()
        pit["dd"] = pd.cut(pit["low_dd"], [-0.99, -0.25, -0.15, -0.08, -0.04], labels=DD_LABS)
        print(f"-- {name} --")
        for b in BANDS:
            parts = []
            for dd in DD_LABS:
                s = pit[(pit["均线带"] == b) & (pit["dd"] == dd)]
                parts.append(f"{len(s)}/{s['r_bh'].mean() * 100:+.2f}" if len(s) else "—")
            print(f"  {BAND_CN[b]:7s}: " + " | ".join(parts))

    print("\n== ④ 高度 × 均线带 (4+阴) ==")
    for h in sorted(t["hh"].unique()):
        s = t[t["hh"] == h]
        parts = []
        for b in BANDS:
            ss = s[s["均线带"] == b]
            parts.append(f"{BAND_CN[b]} {len(ss)}/{ss['r_bh'].mean() * 100:+.2f}"
                         if len(ss) else f"{BAND_CN[b]} —")
        print(f"  {h}: " + " | ".join(parts))


if __name__ == "__main__":
    main()
