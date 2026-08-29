# -*- coding: utf-8 -*-
"""V4白名单定稿终版统计: ①五组覆盖率(白名单口径) ②每年/每月可交易日与触发密度 ③胜率收益.

白名单(2026-08-29主人定稿):
  层1 主力 2板补涨阴 × 蹲类地基(U型蹲/中位浅调/横盘平台/V末反/L趴底)
  层2 主力 2板补涨阳 × 阴跌到点(阴跌尽头首阳)
  层3 狙击 4+补涨阴 × 孤立板穿插(最近段=大波seg_h>=4 且 断板期孤立板1~2个)
  层4 狙击 4+补涨阳 × 2板小波穿插(seg_h==2)
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

BASE_CN = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
           "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    # 均线排列态(D-1口径, 融合五层用)
    for n in (5, 10, 20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    ok = bars[["ma5", "ma10", "ma20", "ma30"]].notna().all(axis=1)
    bars["ma_st"] = ""
    bars.loc[ok, "ma_st"] = (
        np.where(bars.loc[ok, "ma5"] > bars.loc[ok, "ma10"], "+", "-")
        + np.where(bars.loc[ok, "ma10"] > bars.loc[ok, "ma20"], "+", "-")
        + np.where(bars.loc[ok, "ma20"] > bars.loc[ok, "ma30"], "+", "-"))
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4c"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    tgs = {}
    for tag, c in (("1", "c4a"), ("2", "c4b"), ("3", "c4c"), ("4", "c4d")):
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        tg["ym"] = tg["trade_date"].dt.strftime("%Y-%m")
        tgs[tag] = tg

    # 白名单五层(2026-08-29融合定稿, 主人拍板; w2s_v4_fusion.py/maxray.py):
    #   层① 2板阴×蹲类×弹回≤16%×坑宽6-15 | 层② 2板阳×DN首阳 | 层②' 2板阳×蹲类×纠缠态
    #   层③ 4+阴×孤立板穿插×全多头 | 层④ 4+阳×2板小波穿插(不变)
    L = {}
    L["层①·2板阴蹲类×坑宽6-15"] = tgs["1"][tgs["1"]["base"].isin(["U", "MID", "FLAT", "V", "LB"])
                                            & ~(tgs["1"]["reb"] > 0.16)
                                            & tgs["1"]["gap"].between(6, 15)]
    L["层②·2板阳首阳"] = tgs["2"][tgs["2"]["base"] == "DN"]
    L["层②'·2板阳纠缠态"] = tgs["2"][tgs["2"]["base"].isin(["U", "MID", "FLAT", "V", "LB"])
                                     & tgs["2"]["ma_st"].isin(["-++", "+--"])]
    nm3 = tgs["3"]["n_lim_mid"]
    L["层③·4+阴孤板×全多头"] = tgs["3"][(tgs["3"]["seg_h"] >= 4) & nm3.between(1, 2)
                                        & (tgs["3"]["ma_st"] == "+++")
                                        & (tgs["3"]["low_dd"] <= -0.04)]   # 蹲过(排无坑新高票)
    L["层④·4+阳2板穿插"] = tgs["4"][tgs["4"]["seg_h"] == 2]

    # ══ ① 覆盖率(白名单口径) ══
    print("=" * 96)
    print("① 覆盖率: V3五组波首板 → 白名单四层并集(对照: 四组第一层并集 61%)")
    wl_keys = set()
    for name, s in L.items():
        wl_keys |= set(zip(s["sid"], s["pos"]))
    wv = waves.merge(bars[["sid", "pos", "d0_open_lim"]], left_on=["sid", "first_pos"],
                     right_on=["sid", "pos"], how="left")
    wv["hit"] = [(s, p) in wl_keys for s, p in zip(wv["sid"], wv["first_pos"])]
    cg = w.assign_groups(clusters, waves)
    gmap = dict(zip(cg["cluster_id"], cg["group"]))
    wv["grp5"] = wv["cluster_id"].map(gmap)
    wv2 = wv[wv["wave_no"] > 1]
    n_wv2 = len(wv2)
    hit2 = int(wv2["hit"].sum())
    print(f"  非首波 {n_wv2} 波: 白名单命中 {hit2} ({hit2 / n_wv2 * 100:.0f}%) "
          f"| 其中一字买不进 {int(wv2[wv2['hit']]['d0_open_lim'].sum())}")
    t = wv2.groupby("grp5").apply(lambda s: pd.Series({
        "波数": len(s), "命中": int(s["hit"].sum()),
        "覆盖率%": round(s["hit"].mean() * 100)}), include_groups=False)
    print(t.to_string())
    cl_hit = wv.groupby("cluster_id")["hit"].any()
    cl_grp = pd.Series({cid: gmap[cid] for cid in wv["cluster_id"].unique()})
    cc = pd.DataFrame({"命中": cl_hit})
    cc["grp5"] = cl_grp
    t = cc.groupby("grp5").apply(lambda s: pd.Series({
        "簇数": len(s), "命中": int(s["命中"].sum()),
        "簇覆盖%": round(s["命中"].mean() * 100)}), include_groups=False)
    print(f"簇级: {int(cl_hit.sum())}/{len(cl_hit)} ({cl_hit.mean() * 100:.0f}%)")
    print(t.to_string())

    # ══ ② 可交易日 × 触发密度 ══
    print("\n" + "=" * 96)
    print("② 每年/每月可交易日 与 白名单触发密度 (笔/交易日)")
    allwl = pd.concat([s.assign(层=k) for k, s in L.items()], ignore_index=True)
    td = bars.drop_duplicates("trade_date").copy()
    td["ym"] = td["trade_date"].dt.strftime("%Y-%m")
    ntd = td.groupby("ym").size().rename("交易日")
    dens = allwl.groupby("ym").size().rename("笔数")
    mt = pd.concat([ntd, dens], axis=1).fillna(0)
    mt["笔/日"] = (mt["笔数"] / mt["交易日"]).round(2)
    mt["月占比%"] = (mt["笔数"] / mt["笔数"].sum() * 100).round(1)
    mt = mt[mt["笔数"] > 0].astype({"笔数": int})
    print(f"2023-2026明细:")
    print(mt.loc[mt.index >= "2023-01"].to_string())
    yr = allwl.groupby(allwl["trade_date"].dt.year).size()
    ytd = td.groupby(td["trade_date"].dt.year).size()
    print("\n年度汇总:")
    for y in sorted(yr.index):
        s = allwl[allwl["trade_date"].dt.year == y]
        print(f"  {y}: 交易日 {ytd[y]} | 白名单 {len(s)} 笔 "
              f"(日均 {len(s) / ytd[y]:.2f} 笔/日) | 板留均 {s['r_bh'].mean() * 100:+.2f}% "
              f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}%")

    # ══ ③ 胜率收益: 每层年度 + 月度 ══
    print("\n" + "=" * 96)
    print("③ 白名单四层 胜率收益")
    for name, s in L.items():
        yr_stat = " / ".join(
            f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
            if len(sy := s[s["trade_date"].dt.year == yy]))
        print(f"\n── {name}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} 中位 "
              f"{s['r_bh'].median() * 100:+.2f} 胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% "
              f"差票 {s['bad'].mean() * 100:.0f}% 连板 {(s['res'] == '连板').mean() * 100:.0f}% "
              f"| 分年 {yr_stat}")
        # 月度: n/胜率/板留均 (紧凑行)
        parts = []
        for ym, ms in s.groupby("ym"):
            if ym < "2023-01":
                continue
            parts.append(f"{ym[2:]}月 n{len(ms)}/{ms['r_bh'].mean() * 100:+.1f}/{(ms['r_bh'] > 0).mean() * 100:.0f}%")
        for i in range(0, len(parts), 6):
            print("   " + " | ".join(parts[i:i + 6]))

    # 并集总账
    print(f"\n── 白名单并集: n={len(allwl)} 板留均 {allwl['r_bh'].mean() * 100:+.2f} "
          f"胜率 {(allwl['r_bh'] > 0).mean() * 100:.0f}% 差票 {allwl['bad'].mean() * 100:.0f}%")
    yr_stat = " / ".join(
        f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
        if len(sy := allwl[allwl["trade_date"].dt.year == yy]))
    print(f"   分年 {yr_stat}")
    mret = allwl.groupby("ym")["r_bh"].mean()   # r_bh已是小数, 勿再除100
    m3 = mret[mret.index >= "2023-01"]
    print(f"   月均分复利(23-25完整年连乘): {((1 + m3[m3.index < '2026-01']).prod() - 1) * 100:+.1f}%")


if __name__ == "__main__":
    main()
