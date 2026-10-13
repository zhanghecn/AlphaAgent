# -*- coding: utf-8 -*-
"""修复验证: 波峰真顶锚 + topped时序(坑底后才算收回顶上).

误判根因(协鑫集成002506 2026-02-03信号):
  旧锚=段内max high=3.45(末板一字), 断板期01-27/28溢出到3.80/3.83才是真顶;
  旧topped无时序: 坑底(01-30收3.29)之前的近顶收盘(01-27收3.69)被当"收回顶上".
  → 信号日收3.44被误判 贴顶+曾收顶上; 真实: 距真顶-10.2%=坑里.
修复:
  真顶 = max(high[段起..信号日]) (含断板期溢出)
  topped = 坑底日(断板期最低收盘)之后, 断板期(含信号日)曾收≥最后涨停日收盘
本脚本: 单票验证协鑫/易德龙 → 全量事件帧新旧对照(四组出手数/总账/案例六票).
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from datetime import date

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.weak_to_strong import backtest as bt
from alphaagent.server.services.weak_to_strong import pool as pool_mod
from alphaagent.server.services.weak_to_strong import u_shape
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from sqlalchemy import select


def u_features_fix(close, high, is_lim, streak, i, bigtop=False):
    """修正版: 真顶锚(含断板期溢出) + topped时序(坑底后)."""
    n = len(close)
    if i < 1 or i >= n:
        return None
    ge2 = np.flatnonzero(streak >= 2)
    lp = u_shape._last_leq(ge2, i - 1)
    if lp < 0:
        return None
    seg_h = int(streak[lp])
    true_top = float(np.max(high[lp - seg_h + 1: i + 1]))   # ← 修复点1: 段起→信号日
    mid = close[lp + 1: i + 1]
    info = u_shape.classify_base(mid, true_top, float(close[i]))
    if info is None:
        return None

    lim_pos = np.flatnonzero(is_lim[: i + 1])
    j = int(lim_pos[-1]) if len(lim_pos) else -1
    # ← 修复点2: 只数坑底日之后的收回顶上
    low_i = int(np.argmin(mid))
    bottom_pos = lp + 1 + low_i
    if j >= 0 and j < i and bottom_pos + 1 <= i:
        topped = bool((close[bottom_pos + 1: i + 1] >= close[j]).any())
    else:
        topped = False

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
        b4_top = float(np.max(high[b4p - b4_h + 1: i + 1]))   # 同步含溢出
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

    return {"base": info["base"], "pos_low": info["pos_low"], "amp": info["amp"],
            "brk": info["brk"], "seg_h": seg_h, "gap_d0": gap_d0, "n_lim_mid": n_lim_mid,
            "topped": topped, "d23ok": d23ok, "ma_st": ma_st, "big4": big4,
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
        arr[str(vt)] = {k: grp[c].to_numpy() for k, c in
                        (("close", "close_price"), ("high", "high_price"),
                         ("is_lim", "is_lim"), ("streak", "streak"))}
        arr[str(vt)]["dates"] = grp["trade_date"].dt.date.tolist()
        arr[str(vt)]["is_lim"] = arr[str(vt)]["is_lim"].astype(bool)
        arr[str(vt)]["close"] = arr[str(vt)]["close"].astype(float)
        arr[str(vt)]["high"] = arr[str(vt)]["high"].astype(float)
    return arr


def single(arr, vt, sig_date, bigtop):
    a = arr[vt]
    i = a["dates"].index(sig_date)
    old = u_shape.u_features(a["close"], a["high"], a["is_lim"], a["streak"], i, bigtop=bigtop)
    new = u_features_fix(a["close"], a["high"], a["is_lim"], a["streak"], i, bigtop=bigtop)
    print(f"{vt} 信号{sig_date}:")
    for tag, f in (("旧", old), ("新", new)):
        print(f"  {tag}: base={f['base']} pos3={f['pos3']} topped={f['topped']} "
              f"low_dd={f['low_dd']*100:.1f}% pull={f['pull']*100:+.1f}% "
              f"reb={f['reb']*100:.1f}% gap={f['gap_d0']} ma={f['ma_st']}")


def main():
    arr = load_arrays()
    print("══ 单票验证 ══")
    single(arr, "002506.SZSE", pd.Timestamp("2026-02-03").date(), False)   # 协鑫: 应坑内+不topped
    single(arr, "002819.SZSE", pd.Timestamp("2026-07-07").date(), False)   # 易德龙: 应保持曾收顶上排除
    single(arr, "603118.SSE", pd.Timestamp("2026-08-04").date(), False)    # 共进: 应保持纠缠出手

    print("\n══ 全量新旧对照(复用_build_events骨架, 仅换u_features) ══")
    T = bt._build_events()   # 旧口径事件帧(含 actionable/touch/one_word/前向列)
    m4 = T["group_key"].isin([u_shape.GROUP_YIN4, u_shape.GROUP_YANG4])

    # 新口径重算特征
    feats = []
    for row in T.itertuples():
        a = arr[str(row.vt_symbol)]
        feats.append(u_features_fix(a["close"], a["high"], a["is_lim"], a["streak"],
                                    int(row.pos), bigtop=bool(m4.loc[row.Index])))
    for key in ("topped", "low_dd", "pull", "reb", "pos3", "base"):
        T["new_" + key] = [f[key] for f in feats]
    T["new_actionable"] = [
        u_shape.actionable_of(g, {k: f[k] for k in ("base", "topped", "reb", "gap_d0",
                                                    "ma_st", "d23ok", "seg_h", "n_lim_mid",
                                                    "low_dd", "pull")})
        for g, f in zip(T["group_key"], feats)]

    # 分组出手对照(触板&非一字口径)
    fire_old = T[T["actionable"] & T["touch"] & ~T["one_word"]]
    fire_new = T[T["new_actionable"] & T["touch"] & ~T["one_word"]]
    for gk in u_shape.GROUP_KEYS + ("ALL",):
        sub_o = fire_old if gk == "ALL" else fire_old[fire_old["group_key"] == gk]
        sub_n = fire_new if gk == "ALL" else fire_new[fire_new["group_key"] == gk]
        to, tn = bt._trades_for(sub_o), bt._trades_for(sub_n.assign())
        bo = to["ret_bw"].mean() * 100 if len(to) else float("nan")
        bn = tn["ret_bw"].mean() * 100 if len(tn) else float("nan")
        print(f"  {gk}: 旧 {len(to)}笔 bw{bo:+.2f} → 新 {len(tn)}笔 bw{bn:+.2f}")

    # 协鑫新口径标签
    case = T[(T["vt_symbol"] == "002506.SZSE") & (T["trade_date"] == pd.Timestamp("2026-02-03"))]
    for r in case.itertuples():
        print(f"\n协鑫新标签: pos3={r.new_pos3} topped={r.new_topped} base={r.new_base} "
              f"low_dd={r.new_low_dd*100:.1f}% pull={r.new_pull*100:+.1f}% "
              f"reb={r.new_reb*100:.1f}% actionable={r.new_actionable}")

    # 新增出手/丢失出手清单
    gained = T[T["new_actionable"] & ~T["actionable"] & T["touch"] & ~T["one_word"]]
    lost = T[~T["new_actionable"] & T["actionable"] & T["touch"] & ~T["one_word"]]
    tg = bt._trades_for(gained.assign(actionable=True))
    tl = bt._trades_for(lost.assign(actionable=True))
    print(f"\n新口径新增出手 {len(tg)} 笔 bw均={tg['ret_bw'].mean()*100 if len(tg) else 0:+.2f} "
          f"胜率={(tg['ret_bw'] > 0).mean() if len(tg) else 0:.2f}")
    print(f"新口径丢失出手 {len(tl)} 笔 bw均={tl['ret_bw'].mean()*100 if len(tl) else 0:+.2f} "
          f"胜率={(tl['ret_bw'] > 0).mean() if len(tl) else 0:.2f}")
    for r in tg.sort_values("ret_bw").itertuples():
        print(f"  新增 {r.name} {pd.Timestamp(r.trade_date).date()} {r.group_key} "
              f"bw={r.ret_bw*100:+.1f}% 坑{r.new_low_dd*100:.0f}% 距真顶{r.new_pull*100:+.1f}%")
    for r in tl.sort_values("ret_bw").itertuples():
        print(f"  丢失 {r.name} {pd.Timestamp(r.trade_date).date()} {r.group_key} bw={r.ret_bw*100:+.1f}%")


if __name__ == "__main__":
    main()
