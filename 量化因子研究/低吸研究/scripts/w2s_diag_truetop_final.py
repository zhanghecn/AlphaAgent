# -*- coding: utf-8 -*-
"""公共层修复终版: 锚=max(high[段起..min(信号日前日, 末板+3日)]) + topped坑底时序.
四组规则阈值一律不动. 输出: 总账对照/案例门禁/逐票diff/毒格三档新锚复测."""
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


def u_fixed(close, high, is_lim, streak, i, bigtop=False):
    n = len(close)
    if i < 1 or i >= n:
        return None
    ge2 = np.flatnonzero(streak >= 2)
    lp = u_shape._last_leq(ge2, i - 1)
    if lp < 0:
        return None
    seg_h = int(streak[lp])
    top_end = min(i, lp + 4)              # [段起 .. min(i-1, lp+3)] 溢出窗口不含信号日
    true_top = float(np.max(high[lp - seg_h + 1: top_end]))
    mid = close[lp + 1: i + 1]
    info = u_shape.classify_base(mid, true_top, float(close[i]))
    if info is None:
        return None
    lim_pos = np.flatnonzero(is_lim[: i + 1])
    j = int(lim_pos[-1]) if len(lim_pos) else -1
    bottom_pos = lp + 1 + int(np.argmin(mid))
    start = max(bottom_pos + 1, j + 1)   # 坑底后且末板(含孤立板)自身之后, 防自比恒真
    topped = bool(j >= 0 and j < i and start <= i
                  and (close[start: i + 1] >= close[j]).any())
    n_lim_mid = int(is_lim[lp + 1: i + 1].sum())
    gap_d0 = (i + 1) - lp
    d23ok = bool(i >= 3 and close[i - 1] < close[i - 2] and not is_lim[i - 2])
    def _ma(w):
        return float(np.mean(close[i - w + 1: i + 1])) if i + 1 >= w else float("nan")
    ma5, ma10, ma20, ma30 = _ma(5), _ma(10), _ma(20), _ma(30)
    ma_st = None
    if ma30 == ma30:
        ma_st = ("+" if ma5 > ma10 else "-") + ("+" if ma10 > ma20 else "-") + ("+" if ma20 > ma30 else "-")
    ge4 = np.flatnonzero(streak >= 4)
    b4p = u_shape._last_leq(ge4, i - 1)
    big4 = b4p >= 0
    low_dd, pull, reb = info["low_dd"], info["pull"], info["reb"]
    if bigtop and big4 and seg_h < 4:
        b4_h = int(streak[b4p])
        b4_top_end = min(i, b4p + 4)
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


def main():
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
        arr[str(vt)] = {"close": grp["close_price"].to_numpy(dtype=float),
                        "high": grp["high_price"].to_numpy(dtype=float),
                        "is_lim": grp["is_lim"].to_numpy(dtype=bool),
                        "streak": grp["streak"].to_numpy(dtype=float),
                        "dates": grp["trade_date"].dt.date.tolist()}

    T0 = bt._build_events()
    m4 = T0["group_key"].isin([u_shape.GROUP_YIN4, u_shape.GROUP_YANG4])
    acts, feats = [], []
    for row in T0.itertuples():
        a = arr[str(row.vt_symbol)]
        f = u_fixed(a["close"], a["high"], a["is_lim"], a["streak"], int(row.pos),
                    bool(m4.loc[row.Index]))
        feats.append(f)
        acts.append(u_shape.actionable_of(str(row.group_key), f))
    T = T0.copy()
    T["new_act"] = acts
    for k in ("pos3", "topped", "low_dd", "pull", "reb", "base"):
        T["new_" + k] = [f[k] for f in feats]

    old_fire = T[T["actionable"] & T["touch"] & ~T["one_word"]]
    new_fire = T[T["new_act"] & T["touch"] & ~T["one_word"]]
    print("══ 总账(规则阈值不动, 仅公共识别层修锚) ══")
    for gk in u_shape.GROUP_KEYS + ("ALL",):
        so = old_fire if gk == "ALL" else old_fire[old_fire["group_key"] == gk]
        sn = new_fire if gk == "ALL" else new_fire[new_fire["group_key"] == gk]
        to_ = bt._trades_for(so.assign(actionable=True))
        tn_ = bt._trades_for(sn.assign(actionable=True))
        bo = to_["ret_bw"].mean() * 100 if len(to_) else 0
        bn = tn_["ret_bw"].mean() * 100 if len(tn_) else 0
        print(f"  {gk}: 旧 {len(to_)}笔 {bo:+.2f} → 新 {len(tn_)}笔 {bn:+.2f}")

    old_keys = set(zip(old_fire["vt_symbol"], old_fire["trade_date"], old_fire["group_key"]))
    new_keys = set(zip(new_fire["vt_symbol"], new_fire["trade_date"], new_fire["group_key"]))
    gained = new_fire[[ (r.vt_symbol, r.trade_date, r.group_key) not in old_keys for r in new_fire.itertuples()]]
    lost = old_fire[[ (r.vt_symbol, r.trade_date, r.group_key) not in new_keys for r in old_fire.itertuples()]]
    tg = bt._trades_for(gained.assign(actionable=True))
    tl = bt._trades_for(lost.assign(actionable=True))
    print(f"\n══ 新进 {len(tg)} 笔(逐票) ══")
    for r in tg.sort_values("ret_bw").itertuples():
        print(f"  {r.name} {r.vt_symbol} 信号{pd.Timestamp(r.trade_date).date()} {r.group_key} "
              f"bw={r.ret_bw*100:+.1f}% 坑{r.new_low_dd*100:.0f}% 距顶{r.new_pull*100:+.1f}% base={r.new_base}")
    print(f"\n══ 新丢 {len(tl)} 笔(逐票) ══")
    for r in tl.sort_values("ret_bw").itertuples():
        print(f"  {r.name} {r.vt_symbol} 信号{pd.Timestamp(r.trade_date).date()} {r.group_key} bw={r.ret_bw*100:+.1f}%")

    print("\n══ 案例门禁 ══")
    for vt, d, is4, tag in [
        ("600726.SSE", date(2026,5,12), True, "华电能源 in_yin4"),
        ("603538.SSE", date(2026,4,9), True, "美诺华 out_yin4"),
        ("002364.SZSE", date(2026,5,12), True, "中恒电气 in_yin4"),
        ("002819.SZSE", date(2026,7,7), False, "易德龙 out_any"),
        ("000892.SZSE", date(2026,8,3), False, "欢瑞世纪 out_any"),
        ("603118.SSE", date(2026,8,4), False, "共进股份 in_yang2b"),
        ("002506.SZSE", date(2026,2,3), False, "协鑫集成(修复对象)"),
    ]:
        a = arr[vt]
        i = a["dates"].index(d)
        f = u_fixed(a["close"], a["high"], a["is_lim"], a["streak"], i, is4)
        acts2 = [gk for gk in u_shape.GROUP_KEYS if u_shape.actionable_of(gk, f)]
        print(f"  {tag}: pos3={f['pos3']} topped={f['topped']} base={f['base']} "
              f"坑{f['low_dd']*100:.1f}% 距顶{f['pull']*100:+.1f}% → {'/'.join(acts2) or '不出手'}")

    print("\n══ 4+阴毒格三档·新锚复测(回顶=pull>-4%) ══")
    y4 = T[T["group_key"] == u_shape.GROUP_YIN4]
    y4 = y4[y4["touch"] & ~y4["one_word"]]
    y4 = bt._trades_for(y4.assign(actionable=True))
    for lo, hi, tag in ((-0.08, 1.0, "浅<8%回顶"), (-0.15, -0.08, "中坑8~15%回顶"), (-9, -0.15, "深>15%回顶")):
        sub = y4[(y4["new_pull"] > -0.04) & (y4["new_low_dd"] > lo) & (y4["new_low_dd"] <= hi)]
        if len(sub):
            bw = sub["ret_bw"]
            print(f"  {tag}: {len(sub)}笔 bw{bw.mean()*100:+.2f} 胜率{(bw>0).mean():.2f}")
            for r in sub.itertuples():
                print(f"    {r.name} {pd.Timestamp(r.trade_date).date()} bw={r.ret_bw*100:+.1f}% 坑{r.new_low_dd*100:.0f}%")


if __name__ == "__main__":
    main()
