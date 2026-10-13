# -*- coding: utf-8 -*-
"""D-1换手率判别器验证(主人假设 2026-08-29): 阴跌到点格子好差票与昨日换手有关——
有人玩(换手高)就有承接, 没人接(换手低)是死票.

口径: 昨换手 = turnover_rate.shift(1) (D-1可观测, erban研究同款字段).
个案: 海南海药(连板好票) vs 宜宾纸业(炸板差票); 全量: 4+阳×DN 52笔 + 主力②(2板阳×DN)126笔;
交互: 昨换手 × MA30位置(昨收跌破/线上, 接上轮w2s_v4_ma30.py结论).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)

TO_BINS = [0, 2, 5, 8, 15, 25, 100]
TO_LABS = ["<2(无人问津)", "2-5", "5-8", "8-15", "15-25", ">25(过热)"]


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["p_turnover"] = g["turnover_rate"].shift(1)
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    ma30_by = {sid: grp["close_price"].rolling(30, min_periods=30).mean().to_numpy()
               for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def enrich(tg):
        rows = []
        for r in tg.itertuples():
            sid = int(r.sid)
            i = p2i[sid][int(r.pos)]
            ma = ma30_by[sid]
            if ma[i - 1] != ma[i - 1] or r.p_turnover != r.p_turnover:
                continue
            rows.append({"vt": r.vt_symbol, "name": r.name, "date": str(r.trade_date)[:10],
                         "res": r.res, "r_bh": r.r_bh, "bad": r.bad, "trade_date": r.trade_date,
                         "昨换手": r.p_turnover,
                         "ma_pos": "跌破" if r.prev_close < ma[i - 1] else "线上"})
        return pd.DataFrame(rows)

    for tag, cond, label in (("4阳DN", "c4d", "4+补涨阳 × 阴跌到点"),
                             ("2阳DN", "c4b", "2板补涨阳 × 阴跌到点(主力②)")):
        tg, _ = build_base(bars, segs, conds=(cond,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        d = enrich(tg[tg["base"] == "DN"])
        print("=" * 100)
        print(f"== {label}: n={len(d)} ==")

        if tag == "4阳DN":
            print("\n① 2026-07 个案(主人所指):")
            for r in d[d["date"].str.startswith("2026-07")].itertuples():
                print(f"  {r.vt} {r.name} {r.date} {r.res}(板留{r.r_bh * 100:+.1f}%) "
                      f"昨换手 {r.昨换手:.1f}% MA30{r.ma_pos}")

        print("\n② 按昨换手分桶:")
        d["桶"] = pd.cut(d["昨换手"], TO_BINS, labels=TO_LABS)
        t = d.groupby("桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                               胜率=("r_bh", lambda s: (s > 0).mean()),
                                               差票率=("bad", "mean"))
        t["胜率"] = (t["胜率"] * 100).round(0); t["差票率"] = (t["差票率"] * 100).round(0)
        t["板留均"] = (t["板留均"] * 100).round(2)
        print(t.to_string())

        print("\n③ 昨换手粗分(承接线8%) × MA30位置 交互:")
        d["换手粗"] = np.where(d["昨换手"] >= 8, "换手>=8(有承接)", "换手<8(无人玩)")
        t = d.groupby(["换手粗", "ma_pos"]).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                                胜率=("r_bh", lambda s: (s > 0).mean()),
                                                差票率=("bad", "mean"))
        t["胜率"] = (t["胜率"] * 100).round(0); t["差票率"] = (t["差票率"] * 100).round(0)
        t["板留均"] = (t["板留均"] * 100).round(2)
        print(t.to_string())

        print("\n④ 关键桶分年:")
        for lab, m in (("换手<8", d["昨换手"] < 8), ("换手>=8", d["昨换手"] >= 8),
                       ("换手2-8", d["昨换手"].between(2, 8)), ("换手5-8", d["昨换手"].between(5, 8)),
                       ("换手2-5", d["昨换手"].between(2, 5))):
            s = d[m]
            if len(s):
                ys = [f"{y}:{s[s['trade_date'].dt.year == y]['r_bh'].mean() * 100:+.2f}"
                      f"(n{len(s[s['trade_date'].dt.year == y])})"
                      for y in (2023, 2024, 2025, 2026) if len(s[s["trade_date"].dt.year == y])]
                print(f"  {lab}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f}% | {' / '.join(ys)}")


if __name__ == "__main__":
    main()
