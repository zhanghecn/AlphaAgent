# -*- coding: utf-8 -*-
"""主人均线粘合-恢复假设验证(2026-08-29): 连板后多头排列→回调粘合→重新张开的时刻=买点.

因子(D-1口径, 昨日均线):
  s510 = MA5/MA10-1, s1020 = MA10/MA20-1, s2030 = MA20/MA30-1
  事件A(MA5收复MA10): 昨s510>0 且 前1~5日内s510曾<=0  (短期粘合后张开)
  事件B(MA10收复MA20): 昨s1020>0 且 前1~5日内s1020曾<=0 (中期粘合后张开=主人主猜想)
  排列态: 全多头(s510,s1020,s2030全>0) / 局部 / 空头(s510,s1020全<0)
  粘合度: |s1020|昨 <1% / 1~3% / >3%
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)


def stat(s, label):
    if not len(s):
        print(f"  {label}: n=0")
        return
    ys = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} 胜率 "
          f"{(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% | {ys}")


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

    # 均线间距(昨日口径, 历史序列按sid建)
    ma_by = {}
    for n in (5, 10, 20, 30):
        ma_by[n] = {sid: grp["close_price"].rolling(n, min_periods=n).mean().to_numpy()
                    for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def cross_feat(sid, pos):
        """返回 (s510, s1020, s2030, 事件A, 事件B, 粘合度) — 全用昨日及以前的均线."""
        i = p2i[sid][pos] - 1
        if i < 6:
            return None
        out = []
        for (a, b) in ((5, 10), (10, 20), (20, 30)):
            ma_a, ma_b = ma_by[a][sid], ma_by[b][sid]
            out.append(ma_a[i] / ma_b[i] - 1 if ma_b[i] == ma_b[i] else np.nan)
        s510s = [ma_by[5][sid][j] / ma_by[10][sid][j] - 1
                 for j in range(i - 5, i + 1) if ma_by[10][sid][j] == ma_by[10][sid][j]]
        s1020s = [ma_by[10][sid][j] / ma_by[20][sid][j] - 1
                  for j in range(i - 5, i + 1) if ma_by[20][sid][j] == ma_by[20][sid][j]]
        evA = bool(s510s and s510s[-1] > 0 and min(s510s[:-1] or [1]) <= 0)
        evB = bool(s1020s and s1020s[-1] > 0 and min(s1020s[:-1] or [1]) <= 0)
        return out[0], out[1], out[2], evA, evB, abs(out[1]) if out[1] == out[1] else np.nan

    for tag, name in (("c4a", "2板阴"), ("c4b", "2板阳"), ("c4c", "4+阴"), ("c4d", "4+阳")):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        rows = []
        for r in tg.itertuples():
            f = cross_feat(int(r.sid), int(r.pos))
            if f is None:
                continue
            rows.append({"idx": r.Index, "s510": f[0], "s1020": f[1], "s2030": f[2],
                         "evA": f[3], "evB": f[4], "n1020": f[5]})
        ft = pd.DataFrame(rows).set_index("idx")
        tg = tg.join(ft)
        d = tg[tg["s510"] == tg["s510"]].copy()
        d["全多头"] = (d["s510"] > 0) & (d["s1020"] > 0) & (d["s2030"] > 0)
        d["空头"] = (d["s510"] < 0) & (d["s1020"] < 0)

        print("=" * 110)
        print(f"== {name} (均线可算 n={len(d)}) ==")
        print("  ① 排列态:")
        stat(d[d["全多头"]], "  全多头排列")
        stat(d[~d["全多头"] & ~d["空头"]], "  局部/粘合")
        stat(d[d["空头"]], "  空头排列")

        print("  ② 主人恢复事件(近5日曾贴穿, 昨转正):")
        stat(d[d["evB"]], "  事件B: MA10收复MA20")
        stat(d[d["evA"] & ~d["evB"]], "  事件A: MA5收复MA10(无B)")
        stat(d[d["evA"] & d["evB"]], "  A+B 同时")
        stat(d[~d["evA"] & ~d["evB"]], "  无事件")

        print("  ③ s1020(昨) 粘合度分桶:")
        d["粘"] = pd.cut(d["n1020"], [0, 0.01, 0.03, 0.08, 99],
                         labels=["<1%(贴合)", "1~3%", "3~8%", ">8%(张开)"])
        for lab in ("<1%(贴合)", "1~3%", "3~8%", ">8%(张开)"):
            stat(d[d["粘"] == lab], f"  |MA10-MA20| {lab}")


if __name__ == "__main__":
    main()
