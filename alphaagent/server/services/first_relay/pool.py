"""一接二池计算:T-1 收盘后给次日「首板票」打 G1/S1 候选标(判定唯一真源)。

口径 = 量化因子研究/一接二/一接二规则.md v1.1:
- 池 = 昨日恰好 1 板(孤立首板,涨停且前日不涨停)的主板非ST票(全量,雷达)
- 地基日 = 首板前一天;判定维度全部前一晚可知(阴/距MA20/距60高/前10日/换手/底盘)
- 命中 = G1(阴×今开7.5~9.5) / S1(阳×前10<-3×今开7.5~8.5);今开窗由竞价定型后复核
- 静态回避 = 贴顶(地基距60高0~10%)
- 行号语义与 j12_research.py 一致: p1=首板日, p2=地基日, p3=地基前一日
公共件(宇宙/派生列)复用 high_relay.pool, 保证两个产品同口径。
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.first_relay import contracts
from alphaagent.server.services.high_relay import pool as hpr_pool

logger = logging.getLogger(__name__)

_LOOKBACK_CAL_DAYS = 300   # ≈200 交易日, 覆盖 60日板史+h60+ma20+余量
LSHADOW_TH = 0.3           # 板型分类阈值(与研究一致)


def board_type_b1(o: float, h: float, l: float, c: float) -> str:
    """首板板型四分类(研究 board_type_b1 同口径)。"""
    if abs(o - c) <= 1e-6 and abs(o - h) <= 1e-6 and abs(o - l) <= 1e-6:
        return "一字"
    if abs(o - c) <= 1e-6 and abs(o - h) <= 1e-6:
        return "T字"
    lo = min(o, c)
    return "下影" if (lo - l) / (c / 1.10) * 100 >= LSHADOW_TH else "实体"


def tag_point(foundation_yang: bool | None, dist_h60: float | None,
              pre10_pct: float | None,
              pre20_pct: float | None = None) -> tuple[str, str, str | None, str | None, bool]:
    """判定唯一真源: 返回 (point, level, avoid_static, gate串, actionable)。

    规则顺序: 贴顶毒格 → 死水毒格(v1.2) → G1(阴) → S1(阳×前10<-3) → 不命中。
    gate = "lo_hi"(今开窗, 含lo不含hi);盘中等竞价定型后按 gate 复核。
    """
    if dist_h60 is not None and dist_h60 == dist_h60 and 0 <= dist_h60 <= 10:
        return "—", "—", contracts.AVOID_TOP_RIM, None, False
    if pre20_pct is not None and pre20_pct == pre20_pct and -8 <= pre20_pct < 0:
        return "—", "—", contracts.AVOID_DEAD_WATER, None, False
    if foundation_yang is False:
        lo, hi = contracts.POINTS["G1"]["gate"]
        return "G1", "A", None, f"{lo}_{hi}", True
    if foundation_yang is True and pre10_pct is not None and pre10_pct == pre10_pct \
            and pre10_pct < -3:
        lo, hi = contracts.POINTS["S1"]["gate"]
        return "S1", "B", None, f"{lo}_{hi}", True
    return "—", "—", None, None, False


def bonus_tags(b1_turn: float | None, pre20_pct: float | None,
               b1_open_pct: float | None) -> str | None:
    """纯特征标签(v1.2 仓位二值化后仅供看盘参考):锁板/动量深坑/秒板。"""
    tags: list[str] = []
    if b1_turn is not None and b1_turn == b1_turn and b1_turn < 8:
        tags.append(contracts.BONUS_LOCKED)
    if pre20_pct is not None and pre20_pct == pre20_pct and pre20_pct < -5:
        tags.append(contracts.BONUS_MOM_DEEP)
    if b1_open_pct is not None and b1_open_pct == b1_open_pct and b1_open_pct >= 5:
        tags.append(contracts.BONUS_FAST)
    return ",".join(tags) if tags else None


def compute_pool(data_date: date) -> dict[str, object]:
    """data_date(=首板日 T-1)收盘后算 T 日执行池。

    事件口径 = streak==1(T-1 恰好孤立首板);全量入池做雷达,
    命中/回避由 tag_point 判定。返回 entries + 统计。
    """
    engine = get_engine()
    universe = hpr_pool.load_universe(engine)
    name_map = universe.set_index("vt_symbol")["name"].to_dict()
    start = data_date - pd.Timedelta(days=_LOOKBACK_CAL_DAYS)
    bars = pd.read_sql(
        f"select vt_symbol, trade_date, open_price, high_price, low_price, close_price, "
        f"volume, turnover_rate from stock_daily_bars "
        f"where trade_date >= '{start}' and trade_date <= '{data_date}'",
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = hpr_pool.derive_daily(bars)
    # 板史(不含当日): 60日涨停次数 + 窗口内最大连板
    lim_i = bars["is_lim"].astype("int8")
    g = bars.groupby("sid", sort=False)
    bars["lim_cnt60"] = lim_i.groupby(bars["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).sum()).shift(1)
    bars["max_streak60"] = bars["streak"].groupby(bars["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).max()).shift(1)
    gc = g["close_price"]
    bars["c10"] = gc.shift(10)
    bars["c20"] = gc.shift(20)
    mkt_lim_tm1 = int(bars.loc[bars["trade_date"] == data_date, "is_lim"].sum())

    last = bars[bars["trade_date"] == pd.Timestamp(data_date)].copy()
    ev = last[last["streak"] == 1]        # T-1 恰好孤立首板
    entries: list[dict[str, object]] = []
    stats = {"pool": len(ev), "actionable": 0, "act_G1": 0, "act_S1": 0, "avoid": 0}
    for i in ev.index.to_numpy():
        i = int(i)
        p2, p3 = i - 1, i - 2          # 地基日 / 地基前一日
        if p2 < 0:
            continue
        vsym = str(bars["vt_symbol"].iat[i])
        f2c = float(bars["close_price"].iat[p2])
        f3c = float(bars["close_price"].iat[p3]) if p3 >= 0 else np.nan
        f2_h60 = bars["h60"].iat[p2]
        f2_ma20 = bars["ma20"].iat[p2]
        dist_h60 = (f2c / f2_h60 - 1) * 100 if f2_h60 == f2_h60 else None
        dist_ma20 = (f2c / f2_ma20 - 1) * 100 if f2_ma20 == f2_ma20 else None
        pre10 = (f2c / bars["c10"].iat[p2] - 1) * 100 if bars["c10"].iat[p2] == bars["c10"].iat[p2] else None
        pre20 = (f2c / bars["c20"].iat[p2] - 1) * 100 if bars["c20"].iat[p2] == bars["c20"].iat[p2] else None
        f_yang = bool(f2c >= float(bars["open_price"].iat[p2])) if f2c == f2c else None
        f_chg = (f2c / f3c - 1) * 100 if f3c == f3c else None
        point, level, avoid, gate, actionable = tag_point(
            f_yang, dist_h60, pre10, pre20)
        p1o = float(bars["open_price"].iat[i])
        p1c = float(bars["close_price"].iat[i])
        p1_prevc = f2c
        turn = bars["turnover_rate"].iat[i]
        turn = float(turn) if turn == turn else None
        lc60 = bars["lim_cnt60"].iat[i]
        ms60 = bars["max_streak60"].iat[i]
        chassis = ("纯底盘" if lc60 == 0 else ("孤立板" if ms60 == 1 else "前波连板")) \
            if lc60 == lc60 else None
        entries.append({
            "vt_symbol": vsym,
            "name": str(name_map.get(vsym) or ""),
            "point": point,
            "level": level,
            "actionable": actionable,
            "avoid_static": avoid,
            "auction_gate": gate,
            "action_hint": contracts.POINTS[point]["hint"] if point in contracts.POINTS else None,
            "bonus": bonus_tags(turn, dist_ma20, f_chg),
            "prev_close": round(p1c, 2),
            "limit_price": round(p1_prevc * 1.10 + 1e-9, 2) if p1_prevc == p1_prevc else None,
            "foundation_yang": f_yang,
            "foundation_chg": round(f_chg, 2) if f_chg == f_chg else None,
            "dist_ma20": round(dist_ma20, 2) if dist_ma20 == dist_ma20 else None,
            "dist_h60": round(dist_h60, 2) if dist_h60 == dist_h60 else None,
            "pre10_pct": round(pre10, 2) if pre10 == pre10 else None,
            "pre20_pct": round(pre20, 2) if pre20 is not None and pre20 == pre20 else None,
            "b1_type": board_type_b1(p1o, float(bars["high_price"].iat[i]),
                                     float(bars["low_price"].iat[i]), p1c),
            "b1_open": round((p1o / p1_prevc - 1) * 100, 2) if p1_prevc == p1_prevc else None,
            "b1_turn": round(turn, 2) if turn is not None else None,
            "b1_gap": round((round(p1_prevc * 1.10 + 1e-9, 2) - float(bars["low_price"].iat[i]))
                            / p1_prevc * 100, 2) if p1_prevc == p1_prevc else None,
            "chassis": chassis,
            "max_streak60": int(ms60) if ms60 == ms60 else None,
            "mkt_lim_tm1": mkt_lim_tm1,
        })
        if actionable:
            stats["actionable"] += 1
            stats[f"act_{point}"] += 1
        if avoid:
            stats["avoid"] += 1
    exec_date = hpr_pool.next_weekday(data_date)
    return {"exec_date": exec_date.isoformat(), "entries": entries,
            "filter_stats": stats, "mkt_lim_tm1": mkt_lim_tm1}
