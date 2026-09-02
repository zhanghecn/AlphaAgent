# -*- coding: utf-8 -*-
"""真顶锚修复·变体对比: 溢出窗口 0/3/5/∞ × topped时序 开/关.

协鑫机制: 断板期紧贴末板的惯性冲高(01-27/28, +1/+2日)才是波峰真顶;
古早/极端溢出不该改写锚. 窗口W=末板后W个交易日内的高点参与真顶.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from datetime import date
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.weak_to_strong import backtest as bt
from alphaagent.server.services.weak_to_strong import pool as pool_mod
from alphaagent.server.services.weak_to_strong import u_shape


def u_var(close, high, is_lim, streak, i, bigtop, win, timing):
    """参数化: win=溢出窗口(末板后win个交易日高点参与真顶); timing=topped坑底后时序."""
    n = len(close)
    if i < 1 or i >= n:
        return None
    ge2 = np.flatnonzero(streak >= 2)
    lp = u_shape._last_leq(ge2, i - 1)
    if lp < 0:
        return None
    seg_h = int(streak[lp])
    top_end = i + 1 if win is None else min(i + 1, lp + 1 + win)
    true_top = float(np.max(high[lp - seg_h + 1: top_end]))
    mid = close[lp + 1: i + 1]
    info = u_shape.classify_base(mid, true_top, float(close[i]))
    if info is None:
        return None

    lim_pos = np.flatnonzero(is_lim[: i + 1])
    j = int(lim_pos[-1]) if len(lim_pos) else -1
    if timing:
        bottom_pos = lp + 1 + int(np.argmin(mid))
        lo, hi_ = bottom_pos + 1, i + 1
    else:
        lo, hi_ = (j + 1), (i + 1)
    topped = bool(j >= 0 and j < i and lo < hi_ and (close[lo: hi_] >= close[j]).any())

    n_lim_mid = int(is_lim[lp + 1: i + 1].sum())
    gap_d0 = (i + 1) - lp
    d23ok = bool(i >= 3 and close[i - 1] < close[i - 2] and not is_lim[i - 2])

    def _ma(w):
        return float(np.mean(close[i - w + 1: i + 1])) if i + 1 >= w else float("nan")

    ma5, ma10, ma20, ma30 = _ma(5), _ma(10), _ma(20), _ma(30)
    ma_st = None
    if ma30 == ma30:
        ma_st = ("+" if ma5 > ma10 else "-") + ("+" if ma10 > ma20 else "-") \
            + ("+" if ma20 > ma30 else "-")

    ge4 = np.flatnonzero(streak >= 4)
    b4p = u_shape._last_leq(ge4, i - 1)
    big4 = b4p >= 0
    low_dd, pull, reb = info["low_dd"], info["pull"], info["reb"]
    if bigtop and big4 and seg_h < 4:
        b4_h = int(streak[b4p])
        b4_top_end = i + 1 if win is None else min(i + 1, b4p + 1 + win)
        b4_top = float(np.max(high[b4p - b4_h + 1: b4_top_end]))
        mid4 = close[b4p + 1: i + 1]
        if len(mid4):
            low4 = float(np.min(mid4))
            low_dd = low4 / b4_top - 1
            pull = float(close[i]) / b4_top - 1
            reb = float(close[i]) / low4 - 1
            gap_d0 = (i + 1) - b4p

    if low_dd > -0.04:
        pos3 = u_shape.POS_NO_U
    elif pull > -0.04:
        pos3 = u_shape.POS_BREAK
    else:
        pos3 = u_shape.POS_IN

    return {"base": info["base"], "seg_h": seg_h, "gap_d0": gap_d0, "n_lim_mid": n_lim_mid,
            "topped": topped, "d23ok": d23ok, "ma_st": ma_st,
            "low_dd": low_dd, "pull": pull, "reb": reb, "pos3": pos3}


def load_arrays():
    engine = get_engine()
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price, schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price, schema.stock_daily_bars.c.close_price)
        .where(schema.stock_daily_bars.c.trade_date >= date.fromisoformat(bt.BARS_START)),
        engine, parse_dates=["trade_date"])
    bars = pool_mod.derive_daily(bars)
    arr = {}
    for vt, grp in bars.groupby("vt_symbol", sort=False):
        arr[str(vt)] = {
            "close": grp["close_price"].to_numpy(dtype=float),
            "high": grp["high_price"].to_numpy(dtype=float),
            "is_lim": grp["is_lim"].to_numpy(dtype=bool),
            "streak": grp["streak"].to_numpy(dtype=float),
            "dates": grp["trade_date"].dt.date.tolist()}
    return arr


def evaluate(T, arr, win, timing):
    m4 = T["group_key"].isin([u_shape.GROUP_YIN4, u_shape.GROUP_YANG4])
    acts = []
    feats = []
    for row in T.itertuples():
        a = arr[str(row.vt_symbol)]
        f = u_var(a["close"], a["high"], a["is_lim"], a["streak"], int(row.pos),
                  bool(m4.loc[row.Index]), win, timing)
        feats.append(f)
        acts.append(u_shape.actionable_of(str(row.group_key), f))
    T = T.copy()
    T["v_act"] = acts
    T["actionable"] = acts   # _trades_for 内部按此列过滤, 必须覆盖
    T["v_pos3"] = [f["pos3"] for f in feats]
    T["v_topped"] = [f["topped"] for f in feats]
    T["v_pull"] = [f["pull"] for f in feats]
    T["v_low_dd"] = [f["low_dd"] for f in feats]
    fire = T[T["v_act"] & T["touch"] & ~T["one_word"]]
    out = {}
    for gk in u_shape.GROUP_KEYS + ("ALL",):
        sub = fire if gk == "ALL" else fire[fire["group_key"] == gk]
        t = bt._trades_for(sub)
        bw = t["ret_bw"].mean() * 100 if len(t) else float("nan")
        win_r = (t["ret_bw"] > 0).mean() if len(t) else float("nan")
        out[gk] = (len(t), bw, win_r)
    return out, T


def main():
    arr = load_arrays()
    T0 = bt._build_events()

    # 协鑫在每个变体下的标签
    a = arr["002506.SZSE"]
    i = a["dates"].index(date(2026, 2, 3))
    print("协鑫 2026-02-03 各变体标签:")
    for win, timing, tag in ((0, False, "V0现口径"), (None, True, "V1溢出全开+时序"),
                             (3, True, "V2窗口3+时序"), (5, True, "V2b窗口5+时序"),
                             (0, True, "V3仅时序")):
        f = u_var(a["close"], a["high"], a["is_lim"], a["streak"], i, False, win, timing)
        act = u_shape.actionable_of("yang2b", f)
        print(f"  {tag}: pos3={f['pos3']} topped={f['topped']} base={f['base']} "
              f"low_dd={f['low_dd']*100:.1f}% pull={f['pull']*100:+.1f}%")

    variants = [((0, False), "V0现口径"), ((None, True), "V1溢出全开+时序"),
                ((3, True), "V2窗口3+时序"), ((5, True), "V2b窗口5+时序"),
                ((0, True), "V3仅时序")]
    for (win, timing), tag in variants:
        out, _ = evaluate(T0, arr, win, timing)
        cells = "  ".join(f"{gk}:{out[gk][0]}笔{out[gk][1]:+.2f}" for gk in u_shape.GROUP_KEYS)
        print(f"{tag}: ALL {out['ALL'][0]}笔 bw{out['ALL'][1]:+.2f} 胜率{out['ALL'][2]:.2f}")
        print(f"    {cells}")


if __name__ == "__main__":
    main()
