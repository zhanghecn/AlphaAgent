# -*- coding: utf-8 -*-
"""真正的U形态识别算法(结构版, 全收盘口径) + 十票验收 + 全量重跑.

设计:
  段   = 最近≥2连板段 [s..lp]
  坑底 b = 断板期最低收盘日 argmin(close[lp+1..i])
  顶区 top = max(close[s..b-1])   坑底之前的最高收盘(段内+断板期溢出; 坑底后的新高是修复不是顶)
  坑深 low_dd = close[b]/top-1
  位置 pull = close[i]/top-1
  弹起 reb  = close[i]/close[b]-1
  底确认 conf = 信号日下标i - 坑底下标b (交易日数; 0=信号日当天还在创新低)
  坑里天数 pit_days = 断板期收盘 < top*0.96 的天数
  topped = 坑底日后, 断板期(含信号日)曾收 >= 顶区*0.98(回顶区)
十票验收标准(主人判断):
  协鑫集成 2026-02-03 = 坑里右墙(修复中)     川润/海马 = 无坑(新高不算坑)
  法尔胜 2026-03-10   = 浅坑已回顶(留)      胜通/剑桥 = 左半未起(底未确认)
  中恒电气 2026-05-12 = 留(已验证好票)      美诺华   = 中坑回顶(毒)
  华电能源 2026-05-12 = 留(浅擦格)          易德龙   = 伪U(排除)
  中视传媒 2024-01-22 = 留(已验证好票)
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


def u_struct(close, high, is_lim, streak, i, bigtop=False):
    """结构版U识别. 返回字段与旧 u_features 对齐 + conf/pit_days."""
    n = len(close)
    if i < 1 or i >= n:
        return None
    ge2 = np.flatnonzero(streak >= 2)
    lp = u_shape._last_leq(ge2, i - 1)
    if lp < 0:
        return None
    seg_h = int(streak[lp])
    mid = close[lp + 1: i + 1]
    if len(mid) == 0:
        return None
    b = lp + 1 + int(np.argmin(mid))           # 坑底日
    top = float(np.max(close[lp - seg_h + 1: b]))  # 坑底前最高收盘(含段内; b 严格不含)
    if top <= 0:
        return None
    low_dd = float(close[b]) / top - 1
    pull = float(close[i]) / top - 1
    reb = float(close[i]) / float(close[b]) - 1
    conf = i - b                                # 底确认天数
    pit_days = int((close[lp + 1: i + 1] < top * 0.96).sum())
    topped = bool((close[b + 1: i + 1] >= top * 0.98).any()) if b < i else False

    # 地基分类沿用 classify_base, 但锚换结构顶
    info = u_shape.classify_base(mid, top, float(close[i]))

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
    if bigtop and big4 and seg_h < 4:
        b4_h = int(streak[b4p])
        mid4 = close[b4p + 1: i + 1]
        if len(mid4):
            b4 = b4p + 1 + int(np.argmin(mid4))
            top4 = float(np.max(close[b4p - b4_h + 1: b4]))
            low_dd = float(close[b4]) / top4 - 1
            pull = float(close[i]) / top4 - 1
            reb = float(close[i]) / float(close[b4]) - 1
            conf = i - b4
            pit_days = int((close[b4p + 1: i + 1] < top4 * 0.96).sum())
            topped = bool((close[b4 + 1: i + 1] >= top4 * 0.98).any()) if b4 < i else False
            gap_d0 = (i + 1) - b4p

    if low_dd > -0.04:
        pos3 = u_shape.POS_NO_U
    elif pull > -0.04:
        pos3 = u_shape.POS_BREAK
    else:
        pos3 = u_shape.POS_IN

    return {"base": info["base"], "seg_h": seg_h, "gap_d0": gap_d0, "n_lim_mid": n_lim_mid,
            "topped": topped, "d23ok": d23ok, "ma_st": ma_st, "big4": big4,
            "low_dd": low_dd, "pull": pull, "reb": reb, "pos3": pos3,
            "conf": conf, "pit_days": pit_days}


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
        arr[str(vt)] = {"close": grp["close_price"].to_numpy(dtype=float),
                        "high": grp["high_price"].to_numpy(dtype=float),
                        "is_lim": grp["is_lim"].to_numpy(dtype=bool),
                        "streak": grp["streak"].to_numpy(dtype=float),
                        "dates": grp["trade_date"].dt.date.tolist()}
    return arr


CASES = [
    ("002506.SZSE", date(2026, 2, 3), False, "协鑫集成", "坑里右墙(修复中)"),
    ("000890.SZSE", date(2026, 3, 10), True, "法尔胜", "浅坑已回顶·留"),
    ("002364.SZSE", date(2026, 5, 12), True, "中恒电气", "留"),
    ("600726.SSE", date(2026, 5, 12), True, "华电能源", "浅擦·留"),
    ("603538.SSE", date(2026, 4, 9), True, "美诺华", "中坑回顶·毒"),
    ("001331.SZSE", date(2026, 7, 9), False, "胜通能源", "左半未起"),
    ("603083.SSE", date(2023, 10, 25), False, "剑桥科技", "左半未起"),
    ("002272.SZSE", date(2024, 3, 12), True, "川润股份", "无坑新高"),
    ("000572.SZSE", date(2025, 11, 17), True, "海马汽车", "无坑新高"),
    ("002819.SZSE", date(2026, 7, 7), False, "易德龙", "伪U"),
    ("600088.SSE", date(2024, 1, 22), False, "中视传媒", "留(深坑右墙)"),
]


def main():
    arr = load_arrays()
    print("══ 十票验收(结构版识别) ══")
    for vt, d, is4, name, expect in CASES:
        a = arr[vt]
        if d not in a["dates"]:
            print(f"  {name} {d}: 无数据"); continue
        i = a["dates"].index(d)
        f = u_struct(a["close"], a["high"], a["is_lim"], a["streak"], i, is4)
        print(f"  {name} {d} 期望[{expect}]: pos3={f['pos3']} base={f['base']} "
              f"坑{f['low_dd']*100:.1f}% 距顶{f['pull']*100:+.1f}% 弹{f['reb']*100:+.1f}% "
              f"底确认{f['conf']}天 坑里{f['pit_days']}天 topped={f['topped']}")


if __name__ == "__main__":
    main()
