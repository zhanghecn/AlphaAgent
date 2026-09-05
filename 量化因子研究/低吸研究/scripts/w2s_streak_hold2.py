# -*- coding: utf-8 -*-
"""N型 · 2板在手后的持有决策(D+1涨停后继续拿 or 拿一天即可落袋)——主人2026-09-05追问.

样本: 全量触板事件中 h>=2 (D0封+D+1再封=2板在手) 的笔.
对比口径(决策时点=D+1收盘后):
  落袋B = D+2开盘卖 n3_open/entry-1   (拿一天即可)
  继续A = 板留断走 ret_bw              (现状规则)
  差额 = A-B; 再拆 2进3成功/失败两臂:
    成功臂增量 = ret_bw - n3_open/entry (3板+票从D+2开盘继续拿多赚的)
    失败臂损失 = n3_close/n3_open - 1   (D+2断板日 开盘跑 vs 拿到收盘)
特征: vr_d0(D0量比)、vr_d1(D+1量比,最新鲜)、n2 gap(D+1开盘)、bias10、D0触板段.
容器内跑.
"""
import sys
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.weak_to_strong import backtest, repository

GNAME = {"yin2": "2板阴", "yang2": "2板阳", "yin4": "4+阴", "yang4": "4+阳"}


def build_two() -> pd.DataFrame:
    T = backtest._build_events()
    s = T[T["touch"] & ~T["one_word"]].copy()
    s["g4"] = s["group_key"].replace({"yang2a": "yang2", "yang2b": "yang2"})
    s = s[s["g4"].isin(GNAME)].copy()

    ncol = max(int(c.split("_")[0][1:]) for c in s.columns if c.endswith("_is_lim"))
    mat = s[[f"n{k}_is_lim" for k in range(1, ncol + 1)]].fillna(False).to_numpy(dtype=bool)
    h = np.zeros(len(s), dtype=int)
    for j in range(mat.shape[1]):
        h[(h == j) & mat[:, j]] = j + 1
    s["h"] = h

    # 板留断走收益(全量口径,放开actionable)——同 _trades_for 循环
    exit_px = pd.Series(np.nan, index=s.index)
    for k in range(2, ncol + 1):
        lim = s[f"n{k}_is_lim"].fillna(False).astype(bool)
        avail = s[f"n{k}_close"].notna()
        hit = exit_px.isna() & (~lim) & avail
        exit_px[hit] = s.loc[hit, f"n{k}_close"]
    still = exit_px.isna() & s[f"n{ncol}_close"].notna()
    exit_px[still] = s.loc[still, f"n{ncol}_close"]
    s["ret_bw"] = exit_px / s["lim_px"] - 1
    s = s[s["h"] >= 2].copy()  # 2板在手

    # D+1量比: 读事件票volume, n2_date行取 vr=vol/前5日均量
    vts = sorted(set(s["vt_symbol"]))
    engine = get_engine()
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.volume)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vts)), engine,
        parse_dates=["trade_date"])
    bars = bars.sort_values(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma10"] = g["close_price"].transform(lambda x: x.rolling(10).mean())
    bars["vr"] = g["volume"].transform(lambda x: x / x.rolling(5).mean().shift(1))
    d0 = bars.rename(columns={"trade_date": "n1_date"})[["vt_symbol", "n1_date", "vr", "ma10"]]
    d1 = bars.rename(columns={"trade_date": "n2_date"})[["vt_symbol", "n2_date", "vr"]]
    s = s.merge(d0.rename(columns={"vr": "vr_d0", "ma10": "ma10_d0"}),
                on=["vt_symbol", "n1_date"], how="left")
    s = s.merge(d1.rename(columns={"vr": "vr_d1"}), on=["vt_symbol", "n2_date"], how="left")

    s["bias10"] = (s["n1_close"] / s["ma10_d0"] - 1) * 100  # D0收盘/D0的ma10
    s["B"] = s["n3_open"] / s["lim_px"] - 1                 # D+2开盘落袋
    s["A_B"] = s["ret_bw"] - s["B"]                          # 继续拿的增量
    s["lim3"] = s["n3_is_lim"].fillna(False).astype(bool)    # 2进3
    fail = ~s["lim3"]
    s["fail_oc"] = np.where(fail, s["n3_close"] / s["n3_open"] - 1, np.nan)  # 失败日开盘→收盘
    s["succ_inc"] = np.where(s["lim3"], s["A_B"], np.nan)                    # 成功臂D+2开盘起的增量
    s["gap_d1"] = s["n2_open"] / s["n1_close"] - 1           # D+1开盘涨幅(一字=0.1)

    tmap = repository.load_touch_map()
    s["touch_d0"] = [tmap.get((str(v), d.date() if hasattr(d, "date") else d))
                     for v, d in zip(s["vt_symbol"], s["n1_date"])]
    def seg(hhmm):
        m = int(hhmm[:2]) * 60 + int(hhmm[3:5])
        return ("早" if m <= 630 else "中" if m <= 690 else "午" if m <= 840 else "尾")
    s["tseg"] = s["touch_d0"].map(lambda x: seg(x) if isinstance(x, str) else None)
    return s


def show(s: pd.DataFrame, label: str) -> None:
    lim3 = s["lim3"]
    print(f"\n【{label}】n={len(s)}")
    if not len(s):
        return
    print(f"  2进3率 {lim3.mean() * 100:.0f}% | 4板+ {(s['h'] >= 4).mean() * 100:.0f}%")
    print(f"  落袋B(D+2开盘卖) 均 {s['B'].mean() * 100:+.1f}% | 继续A(板留断走) 均 {s['ret_bw'].mean() * 100:+.1f}%"
          f" | 增量A-B 均 {s['A_B'].mean() * 100:+.1f}%  中位 {s['A_B'].median() * 100:+.1f}%")
    f, k = s[~lim3], s[lim3]
    if len(f):
        print(f"  失败臂({len(f)}笔): D+2开盘→收盘 均 {f['fail_oc'].mean() * 100:+.1f}%"
              f" (开盘跑可避开这段)")
    if len(k):
        print(f"  成功臂({len(k)}笔): D+2开盘起继续拿的增量 均 {k['succ_inc'].mean() * 100:+.1f}%")


def by_feat(s: pd.DataFrame, name: str) -> None:
    print(f"\n  ── {name} × 特征 ──")
    rows = []
    for tag, mask in [
        ("D+1缩量<0.8", s["vr_d1"] < 0.8), ("D+1平量", (s["vr_d1"] >= 0.8) & (s["vr_d1"] < 1.5)),
        ("D+1放>=1.5", s["vr_d1"] >= 1.5),
        ("D0缩量<0.8", s["vr_d0"] < 0.8), ("D0放>=1.5", s["vr_d0"] >= 1.5),
        ("D+1一字开盘", s["gap_d1"] > 0.09), ("D+1高开5~9%", (s["gap_d1"] > 0.05) & (s["gap_d1"] <= 0.09)),
        ("D+1低开/平开", s["gap_d1"] <= 0.05),
        ("趋势上方bias10>5", s["bias10"] > 5), ("趋势下方", s["bias10"] <= 5),
        ("D0触板:早", s["tseg"] == "早"), ("D0触板:午/尾", s["tseg"].isin(["午", "尾"])),
    ]:
        x = s[mask.fillna(False)]
        if len(x) < 8:
            continue
        rows.append({"特征": tag, "n": len(x),
                     "2进3%": round(x["lim3"].mean() * 100),
                     "落袋B%": round(x["B"].mean() * 100, 1),
                     "继续A%": round(x["ret_bw"].mean() * 100, 1),
                     "增量A-B%": round(x["A_B"].mean() * 100, 1)})
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> None:
    s = build_two()
    print(f"2板在手样本: {len(s)} 笔 (2023-04~2026-09 全量触板口径)")
    for gk, name in GNAME.items():
        sub = s[s["g4"] == gk]
        show(sub, name)
        by_feat(sub, name)
    out = s[["vt_symbol", "name", "g4", "n1_date", "h", "lim3", "vr_d0", "vr_d1",
             "gap_d1", "bias10", "tseg", "B", "ret_bw", "A_B"]].copy()
    out["n1_date"] = pd.to_datetime(out["n1_date"]).dt.strftime("%Y-%m-%d")
    out.to_csv("/tmp/w2s_hold2_detail.csv", index=False, encoding="utf-8-sig")
    print("\n逐笔: /tmp/w2s_hold2_detail.csv")


if __name__ == "__main__":
    main()
