# -*- coding: utf-8 -*-
"""主人均线形态X光(2026-08-29): U型池(不分深浅, 记录深浅) × D→D+1收益(不看封炸板)
× 好差票分开 × 两类自变量: ①D-1收盘贴哪条均线 ②MA5/10/20/30排列与交叉形态.

池: base∈{FLAT,U,V,MID,LB}(非HIGH非DN=有蹲有起的U型族), low_dd记录深浅.
因变量: r_d1c = D+1收盘/涨停价-1; 好票=r_d1c>0.
均线特征(D-1): s510/s1020/s2030 符号→8种排列态; 最近翻转距今天数(≤3=刚交叉);
最近线归属.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

MAS = (5, 10, 20, 30, 60)
DD_LABS = ["浅<8%", "中8~15", "深15~25", "超深>25"]


def flip_days_ago(arr, i, max_back=15):
    """s序列在i处的符号, 最近一次翻转距今几天(None=15日内无翻转)."""
    if arr[i] != arr[i]:
        return None
    sg = np.sign(arr[i])
    for j in range(i - 1, max(i - max_back, -1), -1):
        if arr[j] == arr[j] and np.sign(arr[j]) != sg:
            return i - j
    return None


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

    ma_by = {n: {sid: grp["close_price"].rolling(n, min_periods=n).mean().to_numpy()
                 for sid, grp in bars.groupby("sid", sort=False)} for n in MAS}
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def feats(sid, pos):
        i = p2i[sid][pos] - 1
        if i < 16:
            return None
        c = cl_by[sid][i]
        s = {}
        for a, b in ((5, 10), (10, 20), (20, 30)):
            ma_a, ma_b = ma_by[a][sid], ma_by[b][sid]
            if ma_b[i] != ma_b[i]:
                return None
            s[f"{a}_{b}"] = ma_a[i] / ma_b[i] - 1
        dists = [c / ma_by[n][sid][i] - 1 if ma_by[n][sid][i] == ma_by[n][sid][i] else np.nan
                 for n in MAS]
        if all(d != d for d in dists):
            return None
        j = int(np.nanargmin(np.abs(np.array(dists, dtype=float))))
        # 排列态字符串
        st = "".join("+" if s[k] > 0 else "-" for k in ("5_10", "10_20", "20_30"))
        # 刚交叉: 翻转≤3日
        def ser(a, b):
            ma_a, ma_b = ma_by[a][sid], ma_by[b][sid]
            return np.where(ma_b > 0, ma_a / np.where(ma_b == 0, 1, ma_b) - 1, np.nan)
        s510_arr = ser(5, 10)
        s1020_arr = ser(10, 20)
        f510 = flip_days_ago(s510_arr, i)
        f1020 = flip_days_ago(s1020_arr, i)
        return {"st": st, "near": f"MA{MAS[j]}", "dev": abs(dists[j]),
                "s510": s["5_10"], "s1020": s["10_20"], "s2030": s["20_30"],
                "f510": f510, "f1020": f1020}

    for tag, name in (("c4a", "2板阴"), ("c4b", "2板阳"), ("c4c", "4+阴"), ("c4d", "4+阳")):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        pit = tg[tg["base"].isin(["FLAT", "U", "V", "MID", "LB"])].copy()
        rows = []
        for r in pit.itertuples():
            f = feats(int(r.sid), int(r.pos))
            if f is None:
                continue
            rows.append({"idx": r.Index, **f})
        d = pit.join(pd.DataFrame(rows).set_index("idx"))
        d = d[d["st"] == d["st"]].copy()
        d["good"] = d["r_d1c"] > 0
        d["深浅"] = pd.cut(-d["low_dd"], [0, 0.08, 0.15, 0.25, 99], labels=DD_LABS)

        def line(sub, lab):
            if not len(sub):
                return f"  {lab}: n=0"
            return (f"  {lab}: n={len(sub)} 好票率{sub['good'].mean() * 100:3.0f}% "
                    f"D+1均{sub['r_d1c'].mean() * 100:+5.2f} 中位{sub['r_d1c'].median() * 100:+5.2f}")

        print("=" * 100)
        print(f"== {name} · U型池 n={len(d)} 好票率 {d['good'].mean() * 100:.0f}% "
              f"D+1均 {d['r_d1c'].mean() * 100:+.2f}% ==")
        print(" ① 深浅(记录不筛):")
        for lab in DD_LABS:
            print(line(d[d["深浅"] == lab], f"  {lab}"))
        print(" ② D-1最近线:")
        for n in MAS:
            print(line(d[d["near"] == f"MA{n}"], f"  贴MA{n}"))
        print(" ③ 排列态(s510 s1020 s2030):")
        for st in sorted(d["st"].unique()):
            sub = d[d["st"] == st]
            if len(sub) >= 8:
                print(line(sub, f"  {st}"))
        print(" ④ 刚交叉(翻转≤3日):")
        for lab, m in (("5/10刚金叉", (d["f510"] <= 3) & (d["s510"] > 0)),
                       ("5/10刚死叉", (d["f510"] <= 3) & (d["s510"] <= 0)),
                       ("10/20刚金叉", (d["f1020"] <= 3) & (d["s1020"] > 0)),
                       ("10/20刚死叉", (d["f1020"] <= 3) & (d["s1020"] <= 0)),
                       ("无交叉(>15日)", (d["f510"].isna()) & (d["f1020"].isna()))):
            print(line(d[m.fillna(False)], f"  {lab}"))
        print(" ⑤ 好差票特征对比:")
        for lab, m in (("好票", d["good"]), ("差票", ~d["good"])):
            s = d[m]
            print(f"  {lab} n={len(s)}: 深浅中位{-s['low_dd'].median() * 100:.0f}% "
                  f"s510中位{s['s510'].median() * 100:+.1f}% s1020中位{s['s1020'].median() * 100:+.1f}% "
                  f"贴MA10占{(s['near'] == 'MA10').mean() * 100:.0f}% "
                  f"全多头{'+++'}占{(s['st'] == '+++').mean() * 100:.0f}% "
                  f"刚交叉率{((s['f510'] <= 3) | (s['f1020'] <= 3)).mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
