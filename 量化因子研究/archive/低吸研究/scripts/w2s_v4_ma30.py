# -*- coding: utf-8 -*-
"""MA30判别器验证(主人假设 2026-08-29): 阴跌到点格子的好差票, 好票基本没跌破30均线.

口径(全部D-1可观测, 无未来): MA30=含昨日的30日收盘均线.
  昨收距MA30 = 昨收/昨MA30-1; 期间最深 = 断板期逐日(收盘/当日MA30-1)的最小值; 曾破=期间最深<0.
个案: 4板补涨阳 2026-07 两笔(海南海药连板/宜宾纸业炸板) + 全期分桶 + 2板阳×DN(主力②)对照.
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
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4d"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    ma30_by = {sid: grp["close_price"].rolling(30, min_periods=30).mean().to_numpy()
               for sid, grp in bars.groupby("sid", sort=False)}
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}
    big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
    big_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
              for sid, grp in big.groupby("sid", sort=False)}

    def enrich(tg):
        rows = []
        for r in tg.itertuples():
            sid = int(r.sid)
            i = p2i[sid][int(r.pos)]
            ma, cl = ma30_by[sid], cl_by[sid]
            if i < 1 or ma[i - 1] != ma[i - 1]:
                continue
            arr = big_by.get(sid)
            if arr is None or arr[:, 0].searchsorted(int(r.pos), side="left") == 0:
                continue
            lp = int(arr[arr[:, 0].searchsorted(int(r.pos), side="left") - 1, 0])
            rat_mid = [cl[j] / ma[j] - 1 for j in range(lp + 1, i) if ma[j] == ma[j]]
            rows.append({"vt": r.vt_symbol, "name": r.name, "date": str(r.trade_date)[:10],
                         "res": r.res, "r_bh": r.r_bh, "bad": r.bad,
                         "trade_date": r.trade_date,
                         "昨距MA30": cl[i - 1] / ma[i - 1] - 1,
                         "期间最深": min(rat_mid) if rat_mid else np.nan,
                         "曾破": (min(rat_mid) < 0) if rat_mid else np.nan})
        return pd.DataFrame(rows)

    for tag, cond, label in (("4阳DN", "c4d", "4+补涨阳 × 阴跌到点"),
                             ("2阳DN", "c4b", "2板补涨阳 × 阴跌到点(主力②)")):
        tg, _ = build_base(bars, segs, conds=(cond,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        d = enrich(tg[tg["base"] == "DN"])
        print("=" * 100)
        print(f"== {label}: n={len(d)} (MA30可算) ==")

        if tag == "4阳DN":
            print("\n① 2026-07 个案(主人所指):")
            for r in d[d["date"].str.startswith("2026-07")].itertuples():
                print(f"  {r.vt} {r.name} {r.date} {r.res}(板留{r.r_bh * 100:+.1f}%) "
                      f"昨收距MA30 {r.昨距MA30 * 100:+.1f}% 期间最深 {r.期间最深 * 100:+.1f}% "
                      f"{'曾破' if r.曾破 else '未破'}")

        print("\n② 按昨收距MA30 分桶:")
        d["桶"] = pd.cut(d["昨距MA30"], [-99, -0.10, -0.05, -0.02, 0, 99],
                         labels=["深破<-10%", "-10~-5%", "-5~-2%", "-2~0%(贴线)", "线上>=0%"])
        t = d.groupby("桶", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                               胜率=("r_bh", lambda s: (s > 0).mean()),
                                               差票率=("bad", "mean"))
        t["胜率"] = (t["胜率"] * 100).round(0); t["差票率"] = (t["差票率"] * 100).round(0)
        t["板留均"] = (t["板留均"] * 100).round(2)
        print(t.to_string())
        for lab in ("深破<-10%", "-10~-5%", "-5~-2%", "-2~0%(贴线)", "线上>=0%"):
            s = d[d["桶"] == lab]
            if not len(s):
                continue
            ys = [f"{y}:{s[s['trade_date'].dt.year == y]['r_bh'].mean() * 100:+.2f}"
                  f"(n{len(s[s['trade_date'].dt.year == y])})"
                  for y in (2023, 2024, 2025, 2026) if len(s[s["trade_date"].dt.year == y])]
            print(f"  {lab} 分年: {' / '.join(ys)}")

        print("\n③ 断板期曾破MA30 vs 始终在线上:")
        for lab, m in (("始终未破", d["曾破"] == False), ("曾破", d["曾破"] == True)):
            s = d[m]
            if len(s):
                print(f"  {lab}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f}% 胜率 "
                      f"{(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% "
                      f"连板 {(s['res'] == '连板').mean() * 100:.0f}%")

        print("\n④ 昨收在线上/跌破 二分:")
        for lab, m in (("昨收>=MA30", d["昨距MA30"] >= 0), ("昨收<MA30", d["昨距MA30"] < 0)):
            s = d[m]
            if len(s):
                ys = [f"{y}:{s[s['trade_date'].dt.year == y]['r_bh'].mean() * 100:+.2f}"
                      for y in (2023, 2024, 2025, 2026) if len(s[s["trade_date"].dt.year == y])]
                print(f"  {lab}: n={len(s)} 板留 {s['r_bh'].mean() * 100:+.2f}% 胜率 "
                      f"{(s['r_bh'] > 0).mean() * 100:.0f}% 差票 {s['bad'].mean() * 100:.0f}% | {' / '.join(ys)}")


if __name__ == "__main__":
    main()
