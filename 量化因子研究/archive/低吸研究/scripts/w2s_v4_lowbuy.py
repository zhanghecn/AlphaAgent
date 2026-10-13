# -*- coding: utf-8 -*-
"""低吸验证: 2板段断板后, 收阴结束出现小阳的当天低位买入(不打板).

选股(同V4补涨阴前置, 昨日口径): 前20日连板=2 + 昨收阴 + 昨幅>-9% + 昨上影<4% + 昨日未涨停
D0=今日出现小阳, 买入口径:
  A1 盘中+2%确认: 今盘中涨幅触及+2%买(昨收×1.02), 要求开盘涨幅<2%(能低位接到)
  A2 高开也追: 买价=max(开盘价, 昨收×1.02)
  B  尾盘确认: 今日收阳且涨幅0~5%, 收盘价买
卖出矩阵: 首次触板日收盘卖(≤20日) / D1 / D3 / D5 / D10 收盘卖; 附期间最大浮亏/摸高.
变体: 昨日深阴(<-4%)后的首阳(上轮发现 深阴后小阳=反转确认).
对照: 同池打板口径(V4补涨阴).
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 500)


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    stk = bars["streak"].astype(float)
    bars["mx20v"] = stk.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).rolling(20, min_periods=1).max())
    bars["n1_close"] = g["close_price"].shift(-1)
    bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6

    # 补涨阴前置(昨日口径)
    base = ((bars["mx20v"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
            & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    hi_by = {sid: grp["high_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    lo_by = {sid: grp["low_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    rows = []
    cand = bars[base]
    for r in cand.itertuples():
        sid = int(r.sid)
        i = p2i[sid][int(r.pos)]
        cl, hi, lo = cl_by[sid], hi_by[sid], lo_by[sid]
        if i + 20 >= len(cl):
            continue
        pc = r.prev_close
        tgt2 = pc * 1.02
        o, h, c = r.open_price, r.high_price, r.close_price
        chg = c / pc - 1
        # A1: 盘中触及+2% 且 开盘未超(能接到)
        a1 = (h >= tgt2 - 1e-6) and (o < tgt2)
        # A2: 触及+2%(高开也追)
        a2 = h >= tgt2 - 1e-6
        # B: 尾盘小阳确认
        b_ = (c > o) and (0 <= chg <= 0.05)
        if not (a1 or b_):
            continue
        # 未来路径
        fut_c = cl[i + 1:i + 21]
        fut_h = hi[i + 1:i + 21]
        fut_l = lo[i + 1:i + 21]
        lims = np.round(np.concatenate(([cl[i]], fut_c[:-1])) * 1.10 + 1e-9, 2)
        touch_d = np.argmax(fut_h >= lims - 1e-6) + 1 if (fut_h >= lims - 1e-6).any() else 0
        def ret(px_buy):
            if px_buy != px_buy:
                return None
            out = {"buy": px_buy}
            for n in (1, 3, 5, 10):
                out[f"d{n}"] = fut_c[n - 1] / px_buy - 1 if n <= len(fut_c) else np.nan
            if touch_d:
                out["to_touch"] = fut_c[touch_d - 1] / px_buy - 1
            else:
                out["to_touch"] = fut_c[-1] / px_buy - 1
            out["mfe"] = fut_h.max() / px_buy - 1
            out["mae"] = fut_l.min() / px_buy - 1
            out["touch20"] = bool(touch_d)
            return out
        rows.append({
            "sid": sid, "pos": int(r.pos), "date": r.trade_date, "vt": r.vt_symbol,
            "name": r.name, "chg0": chg, "p_chg": r.p_chg,
            "deep_yin": r.p_chg < -0.04,
            "A1": ret(pc * 1.02) if a1 else None,
            "A2": ret(max(o, tgt2)) if a2 else None,
            "B": ret(c) if b_ else None,
        })
    df = pd.DataFrame(rows)
    print(f"候选(补涨阴前置) {len(cand)} 笔 → D0出小阳: A1口径 {sum(r['A1'] is not None for r in rows)} / "
          f"A2口径 {sum(r['A2'] is not None for r in rows)} / B口径 {sum(r['B'] is not None for r in rows)}")

    def stat(sub, key, label):
        vals = [r[key] for r in sub if r[key] is not None]
        if not vals:
            print(f"  {label}: n=0")
            return
        d = pd.DataFrame(vals)
        dates = [k for k, r in zip(sub_datevals, sub) if r[key] is not None]
        print(f"  {label}: n={len(d)}")
        for col, nm in (("d1", "D1卖"), ("d3", "D3卖"), ("d5", "D5卖"), ("d10", "D10卖"),
                        ("to_touch", "触板卖"), ("mfe", "期间最高"), ("mae", "期间最低")):
            s_ = d[col].dropna()
            print(f"      {nm:6s} 均 {s_.mean() * 100:+6.2f} 中位 {s_.median() * 100:+6.2f} "
                  f"胜率 {(s_ > 0).mean() * 100:3.0f}%")
        print(f"      20日内触板率 {d['touch20'].mean() * 100:.0f}%")
        for yy in (2023, 2024, 2025, 2026):
            m = [k for k, r in zip(sub_datevals, sub) if r[key] is not None and str(k)[:4] == str(yy)]
            if len(m) >= 5:
                dd = pd.DataFrame([r[key] for k, r in zip(sub_datevals, sub)
                                   if r[key] is not None and str(k)[:4] == str(yy)])
                print(f"      {yy}: n={len(dd)} 触板卖均 {dd['to_touch'].mean() * 100:+.2f} "
                      f"D5均 {dd['d5'].mean() * 100:+.2f} 差(触板卖<0) {(dd['to_touch'] < 0).mean() * 100:.0f}%")

    for key, lab in (("A1", "A1 盘中+2%低吸(开盘<2%)"), ("A2", "A2 触+2%(高开也追)"), ("B", "B 尾盘小阳买")):
        print(f"\n== {lab} ==")
        sub_datevals = list(df["date"])
        sub = df.to_dict("records")
        stat(sub, key, "全体")
        stat([r for r in sub if r["deep_yin"]], key, "  昨深阴(<-4%)后首阳")
        stat([r for r in sub if not r["deep_yin"]], key, "  昨浅阴后首阳")


if __name__ == "__main__":
    main()
