# -*- coding: utf-8 -*-
"""2板补涨阳 微观维度: 昨阳涨幅(小阳多大) × 前天(D-2)阴阳/跌幅 → 好差票区别(主人假设).

维度:
  昨幅桶: -3~0(假阳) / 0~2(极小阳) / 2~4(小阳) / 4~7(中阳) / 7~10(大阳未涨停)
  D-2: 阴/阳, 阴时跌幅分桶
输出: 2026-07/08主人样例 + 全期 + 分年稳定性.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    # D-2(前天) 口径: 收盘/开盘/涨跌幅
    c2 = g["close_price"].shift(2)
    o2 = g["open_price"].shift(2)
    pc2 = g["close_price"].shift(3)          # D-2的前收 → D-2涨跌幅分母
    bars["chg_d2"] = (c2 / pc2 - 1) * 100
    bars["yin_d2"] = (c2 < o2).fillna(False).astype(bool)
    bars["yang_d2"] = (c2 > o2).fillna(False).astype(bool)

    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    tg, _ = build_base(bars, segs, conds=("c4b",))
    tg = add_outcome(tg, bars)
    tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
    tg["ym"] = tg["trade_date"].dt.strftime("%Y-%m")
    tg["date"] = tg["trade_date"].dt.strftime("%Y-%m-%d")

    ZF = [-3, 0, 2, 4, 7, 10.1]
    ZL = ["-3~0(假阳)", "0~2(极小阳)", "2~4(小阳)", "4~7(中阳)", "7~10(大阳)"]
    tg["昨幅桶"] = pd.cut(tg["p_chg"] * 100, ZF, labels=ZL)

    def tbl(sub, label):
        t = sub.groupby("昨幅桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                                    差票率=("bad", "mean"))
        if len(t):
            t["差票率"] = (t["差票率"] * 100).round(0)
            t["板留均"] = (t["板留均"] * 100).round(2)
            print(f"\n{label}")
            print(t.to_string())

    print("=" * 96)
    print("① 昨阳涨幅(小阳多大) × 好差")
    tbl(tg[(tg["date"] >= "2026-07-01")], "主人样例 2026-07/08:")
    tbl(tg, "全期 2023-2026:")
    for yy in (2023, 2024, 2025, 2026):
        sy = tg[tg["trade_date"].dt.year == yy]
        if len(sy):
            t = sy.groupby("昨幅桶", observed=True)["r_bh"].mean() * 100
            print(f"  {yy}: " + " | ".join(f"{k.split('(')[0]}:{v:+.2f}(n{int((sy['昨幅桶']==k).sum())})"
                                            for k, v in t.items()))

    print("\n" + "=" * 96)
    print("② D-2(前天) 阴阳 × 好差")
    for lab, m in (("前天阴", tg["yin_d2"]), ("前天阳", tg["yang_d2"]), ("前天平", ~tg["yin_d2"] & ~tg["yang_d2"])):
        s = tg[m]
        if not len(s):
            continue
        print(f"  {lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} 差票 {s['bad'].mean() * 100:.0f}% "
              f"胜率 {(s['r_bh'] > 0).mean() * 100:.0f}%")
    s07 = tg[(tg["date"] >= "2026-07-01")]
    for lab, m in (("样例·前天阴", s07["yin_d2"]), ("样例·前天阳", s07["yang_d2"])):
        s = s07[m]
        if len(s):
            print(f"  {lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} 差票 {s['bad'].mean() * 100:.0f}%")

    print("\n" + "=" * 96)
    print("③ 前天阴时, 阴线跌幅分桶 × 好差")
    D2 = [-99, -7, -4, -2, 0]
    DL = ["深阴<-7%", "中阴-7~-4", "浅阴-4~-2", "微阴-2~0"]
    tg["前阴幅桶"] = pd.cut(tg["chg_d2"], D2, labels=DL)
    sub = tg[tg["yin_d2"]]
    sub = sub.assign(桶=pd.cut(sub["chg_d2"], D2, labels=DL))
    t = sub.groupby("桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"), 差票率=("bad", "mean"))
    t["差票率"] = (t["差票率"] * 100).round(0); t["板留均"] = (t["板留均"] * 100).round(2)
    print("全期(前天阴的票):"); print(t.to_string())
    s07y = s07[s07["yin_d2"]].assign(桶=pd.cut(s07[s07["yin_d2"]]["chg_d2"], D2, labels=DL))
    t = s07y.groupby("桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"), 差票率=("bad", "mean"))
    if len(t):
        t["差票率"] = (t["差票率"] * 100).round(0); t["板留均"] = (t["板留均"] * 100).round(2)
        print("样例 2026-07/08(前天阴):"); print(t.to_string())

    # 分年稳定性: 前天阴深(<-4) vs 其余
    print("\n④ 分年: 前天深阴(<-4%) vs 其余")
    deep = tg[tg["yin_d2"] & (tg["chg_d2"] < -4)]
    rest = tg[~(tg["yin_d2"] & (tg["chg_d2"] < -4))]
    for yy in (2023, 2024, 2025, 2026):
        a = deep[deep["trade_date"].dt.year == yy]
        b = rest[rest["trade_date"].dt.year == yy]
        if len(a) and len(b):
            print(f"  {yy}: 深阴 n={len(a)} 板留{a['r_bh'].mean() * 100:+.2f} 差票{a['bad'].mean() * 100:.0f}% "
                  f"| 其余 n={len(b)} 板留{b['r_bh'].mean() * 100:+.2f} 差票{b['bad'].mean() * 100:.0f}%")

    # 交互: 昨幅小(0~2) × 前天深阴 = 主人假设的"弱反弹"票
    print("\n⑤ 交互: 昨幅×前天阴深(<-4)")
    weak = tg[tg["昨幅桶"] == "0~2(极小阳)"]
    for lab, m in (("极小阳+前天深阴", (tg["昨幅桶"] == "0~2(极小阳)") & tg["yin_d2"] & (tg["chg_d2"] < -4)),
                   ("极小阳+其他", (tg["昨幅桶"] == "0~2(极小阳)") & ~(tg["yin_d2"] & (tg["chg_d2"] < -4))),
                   ("非极小阳+前天深阴", (tg["昨幅桶"] != "0~2(极小阳)") & tg["yin_d2"] & (tg["chg_d2"] < -4))):
        s = tg[m]
        if len(s):
            print(f"  {lab}: n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} 差票 {s['bad'].mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
