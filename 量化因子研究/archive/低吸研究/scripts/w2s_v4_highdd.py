# -*- coding: utf-8 -*-
"""主人统一地基假设核查(2026-08-29): ①MID/FLAT/U 同属"U(洗盘蓄势)类" ②HIGH不好
③HIGH里较好的是"之前V/U过又爬回顶"的(蹲深≤-12%的深V回来票).

拆解: HIGH格内按 low_dd(断板期最低收盘距顶) 分三层:
  深蹲回来≤-12%(=V/U口径的蹲深) / 浅蹲-12~-4% / 没蹲>-4%(横顶/顶上).
个案: 宗申动力2024-04-19(HIGH好票但蹲深-2.1%没蹲过) + brk(破顶)交叉.
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


def stat(s, label):
    if not len(s):
        print(f"  {label}: n=0")
        return
    ys = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := s[s["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f} 胜率 "
          f"{(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% "
          f"连板 {(s['res'] == '连板').mean() * 100:.0f}% | {ys}")


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

    print("=" * 104)
    print("== ① 蹲类归并验证: MID/FLAT/U/V/LB 三~五格并排 (各组分年方向是否一致) ==")
    for tag, name in (("c4a", "2板阴"), ("c4b", "2板阳"), ("c4c", "4+阴"), ("c4d", "4+阳")):
        tg, _ = build_base(bars, segs, conds=(tag,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        print(f"-- {name} --")
        for b in ("FLAT", "U", "MID", "V", "LB"):
            stat(tg[tg["base"] == b], f"  {BASE_CN[b]}")
        stat(tg[tg["base"].isin(["FLAT", "U", "MID", "V", "LB"])], "  合并蹲类")

        print(f"\n-- {name} · HIGH 内部按蹲深拆 --")
        H = tg[tg["base"] == "HIGH"]
        stat(H[H["low_dd"] <= -0.12], "  深蹲回来(≤-12%, V/U过)")
        stat(H[(H["low_dd"] > -0.12) & (H["low_dd"] <= -0.04)], "  浅蹲(-12~-4%)")
        stat(H[H["low_dd"] > -0.04], "  没蹲(>-4%, 横顶)")
        print("    破顶brk交叉:")
        stat(H[H["brk"] & (H["low_dd"] <= -0.12)], "    蹲过×破过顶")
        stat(H[~H["brk"] & (H["low_dd"] <= -0.12)], "    蹲过×未破顶")
        stat(H[H["brk"] & (H["low_dd"] > -0.04)], "    没蹲×破过顶(新高强势)")
        stat(H[~H["brk"] & (H["low_dd"] > -0.04)], "    没蹲×未破顶(纯贴顶)")
        print()

    # 个案
    tg, _ = build_base(bars, segs, conds=("c4b",))
    tg = add_outcome(tg, bars)
    for r in tg[(tg["vt_symbol"] == "001696.SZSE")].itertuples():
        if str(r.trade_date)[:10] in ("2024-04-10", "2024-04-19"):
            print(f"个案 {str(r.trade_date)[:10]} 宗申动力: base={r.base} 蹲深{r.low_dd * 100:+.1f}% "
                  f"回撤{r.pull * 100:+.1f}% 弹回{r.reb * 100:+.1f}% brk={r.brk} "
                  f"板留{r.r_bh * 100:+.1f}%")


if __name__ == "__main__":
    main()
