# -*- coding: utf-8 -*-
"""坑三状态识别体检(主人要求): 防两类误判——真坑误判无坑 / 真贴顶(高位震荡)误判U.
① 四组×三状态×曾收顶上 分布与收益(确认无坑是否该剔出展示)
② 边界审计: 无坑里坑深-3~-4%的(差一口气) 逐日还原看是否真贴顶;
   坑内里浅坑+曾收顶上的(易德龙型)确认标注可见; 已回顶抽样核对确实跌过>4%又爬回
③ 锚正确性: 4+夹层票(最近段=2板小波)顶=小波顶而非大波顶, 检查是否漏掉大波深坑
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 300)

GROUPS = [("2板补涨阴", "c4a"), ("2板补涨阳", "c4b"),
          ("4板补涨阴", "c4c"), ("4板补涨阳", "c4d")]


def pos_of(low_dd, pull):
    if low_dd == low_dd and low_dd > -0.04:
        return "无坑"
    if pull == pull and pull > -0.04:
        return "已回顶"
    return "坑内"


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
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def topped_of(sid, pos):
        i = p2i[int(sid)][int(pos)]
        c, zt = cl_by[int(sid)], zt_by[int(sid)]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return False
        return bool((c[j + 1:i] >= c[j]).any())

    all_t = []
    for name, c in GROUPS:
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["grp"] = name
        tg["topped"] = [topped_of(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        all_t.append(tg)
    t = pd.concat(all_t, ignore_index=True)
    t["pos3"] = [pos_of(dd, pu) for dd, pu in zip(t["low_dd"], t["pull"])]

    print("=" * 96)
    print("① 四组 × 坑三状态 (板留均 / 好票率):")
    for name, _ in GROUPS:
        sub = t[t["grp"] == name]
        print(f"\n── {name} (n={len(sub)}):")
        for p3 in ("无坑", "坑内", "已回顶"):
            s = sub[sub["pos3"] == p3]
            if not len(s):
                continue
            s_tp = s[s["topped"]]
            print(f"  {p3}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
                  f"好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}% | 其中曾收顶上 {len(s_tp)}笔 "
                  f"{s_tp['r_bh'].mean() * 100:+.2f}" if len(s_tp) else
                  f"  {p3}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
                  f"好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}%")

    print("\n" + "=" * 96)
    print("② 边界审计1: 无坑 但坑深-3~-4%(差一口气) —— 是否真贴顶还是误判?")
    b1 = t[(t["pos3"] == "无坑") & (t["low_dd"] <= -0.03)]
    print(f"  n={len(b1)} 板留均 {b1['r_bh'].mean() * 100:+.2f} "
          f"好票率 {(b1['r_d1c'] > 0).mean() * 100:.0f}%")
    print("  对照·无坑整体(坑深>-3%几乎没跌):")
    b0 = t[(t["pos3"] == "无坑") & (t["low_dd"] > -0.03)]
    print(f"  n={len(b0)} 板留均 {b0['r_bh'].mean() * 100:+.2f} "
          f"好票率 {(b0['r_d1c'] > 0).mean() * 100:.0f}%")

    print("\n③ 边界审计2: 坑内 但曾收顶上(易德龙型高位震荡) —— 各组表现:")
    b2 = t[(t["pos3"] == "坑内") & t["topped"]]
    for name, _ in GROUPS:
        s = b2[b2["grp"] == name]
        if len(s):
            print(f"  {name}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
                  f"好票率 {(s['r_d1c'] > 0).mean() * 100:.0f}%")

    print("\n④ 边界审计3: 已回顶抽样逐日还原(核: 确实跌过>4%又爬回):")
    samp = t[(t["pos3"] == "已回顶")].sample(3, random_state=7)
    for _, r in samp.iterrows():
        sid, pos = int(r["sid"]), int(r["pos"])
        i = p2i[sid][pos]
        c, zt = cl_by[sid], zt_by[sid]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        top = c[j]
        seg = c[j + 1:i]
        dts = bars[bars["sid"] == sid]["trade_date"].to_numpy()
        print(f"  {r['vt_symbol']} {r['name']} {str(r['trade_date'].date())} [{r['grp']}] "
              f"顶日{str(pd.Timestamp(dts[j]).date())} 顶{top:.2f}")
        path = " ".join(f"{pd.Timestamp(dts[k]).date()}:{c[k]:.2f}({(c[k]/top-1)*100:+.1f}%)"
                        + ("板" if zt[k] else "") for k in range(j, i + 1))
        print(f"    {path}")

    print("\n⑤ 锚审计: 4+夹层票(最近段=2板小波)的顶=小波顶, 大波深坑是否漏算?")
    sw = t[t["grp"].str.startswith("4板") & (t["seg_h"] == 2)]
    print(f"  4+夹层票 n={len(sw)}: 位置分布 " +
          " ".join(f"{p3}:{len(sw[sw['pos3'] == p3])}" for p3 in ("无坑", "坑内", "已回顶")))
    swU = sw[sw["pos3"] == "无坑"]
    print(f"  其中无坑 {len(swU)}笔 板留均 {swU['r_bh'].mean() * 100:+.2f} "
          f"(若按大波顶算有深坑却被判无坑, 这里会漏好票)")


if __name__ == "__main__":
    main()
