"""二波反包 池计算与特征:妖股波段结构特征(全 T-1 口径) + 次日执行池。

特征全部由日线 rolling 推出(无逐票回溯),与回测/研究同一函数,防口径漂移:
  gap       = 截至昨日连续未涨停收盘天数(notlim_prev, 昨日起算)
  gain30    = 昨收 / 31个交易日前收 - 1        (30日妖股波段)
  dd        = 昨收 / 截至昨日20日最高收盘 - 1  (深洗带)
  ma20gap   = 昨收 / 截至昨日MA20 - 1          (不破线)
  lim30     = 截至昨日30日内涨停收盘次数        (波段内补涨次数)
  yy        = 昨收 < T-2收 = 阴                (跌幅口径,与 fanbao 同)
  last_open = 昨日开盘%                         (A/B 档判定)
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.erbo import contracts
from alphaagent.server.services.fanbao import pool as fbb_pool  # 复用宇宙/日线推导/交易日工具

_LOOKBACK_CAL_DAYS = 200  # ≈130 个交易日,覆盖 31 日波段 + 20 日均线 + 余量


def latest_daily_date() -> date | None:
    return fbb_pool.latest_daily_date()


def derive_features(bars: pd.DataFrame) -> pd.DataFrame:
    """在 fanbao.derive_daily 产物上加二波特征列(组内 rolling,昨收口径)。"""
    bars = bars.copy()
    g = bars.groupby("sid", sort=False)
    bars["pc"] = g["close_price"].shift(1)
    bars["pc2"] = g["close_price"].shift(2)
    bars["po"] = g["open_price"].shift(1)
    bars["gain30"] = bars["pc"] / g["close_price"].shift(31) - 1
    bars["hh20"] = g["pc"].transform(lambda s: s.rolling(20).max())
    bars["dd"] = bars["pc"] / bars["hh20"] - 1
    bars["ma20"] = g["pc"].transform(lambda s: s.rolling(20).mean())
    bars["ma20gap"] = bars["pc"] / bars["ma20"] - 1
    bars["lim30"] = g["is_lim"].transform(lambda s: s.rolling(30).sum()).shift(1)
    bars["yy"] = np.where(bars["pc"] < bars["pc2"], "阴", "阳")
    bars["last_open"] = (bars["po"] / bars["pc2"] - 1) * 100
    return bars


def _struct_ok(d: pd.DataFrame) -> pd.Series:
    """池结构条件(昨日口径):阴 × 断3~7 × 波段50~80 × 洗8~15 × MA20≥5% × 涨停≥2。"""
    return ((d["yy"] == "阴")
            & d["notlim_prev"].between(contracts.GAP_LO, contracts.GAP_HI)
            & d["gain30"].between(contracts.GAIN30_LO, contracts.GAIN30_HI)
            & d["dd"].between(contracts.DD_LO, contracts.DD_HI)
            & (d["ma20gap"] >= contracts.MA20_MIN)
            & (d["lim30"] >= contracts.LIM30_MIN))


def compute_pool(data_date: date | None = None) -> dict[str, object]:
    """以 data_date(默认最新日线日)为 T-1 计算次日执行池(结构满足全量+打档)。

    返回 {data_date, exec_date, rules_version, mkt_lim_tm1, entries, filter_stats}。"""
    engine = get_engine()
    if data_date is None:
        data_date = latest_daily_date()
    if data_date is None:
        return {"data_date": None, "exec_date": None, "mkt_lim_tm1": None, "entries": [],
                "rules_version": contracts.ERBO_RULES_VERSION,
                "filter_stats": {"error": "no_daily_bars"}}
    window_start = data_date - timedelta(days=_LOOKBACK_CAL_DAYS)
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price,
               schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.volume)
        .where(schema.stock_daily_bars.c.trade_date >= window_start,
               schema.stock_daily_bars.c.trade_date <= data_date),
        engine, parse_dates=["trade_date"])
    universe = fbb_pool.load_universe(engine)
    if bars.empty or universe.empty:
        return {"data_date": data_date.isoformat(), "exec_date": None, "mkt_lim_tm1": None,
                "entries": [], "rules_version": contracts.ERBO_RULES_VERSION,
                "filter_stats": {"error": "no_bars"}}
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = fbb_pool.derive_daily(bars)
    bars = derive_features(bars)
    name_map = universe.set_index("vt_symbol")["name"].to_dict()

    d = bars[bars["trade_date"] == pd.Timestamp(data_date)].copy()
    d = d[_struct_ok(d) & d["gain30"].notna() & d["dd"].notna() & d["ma20gap"].notna()]
    mkt_lim_tm1 = None
    mkt_col = d["mkt_prev"].dropna()
    if len(mkt_col):
        mkt_lim_tm1 = int(mkt_col.iloc[0])

    entries: list[dict[str, object]] = []
    act = 0
    for _, r in d.iterrows():
        vt = str(r["vt_symbol"])
        last_open = float(r["last_open"]) if r["last_open"] == r["last_open"] else None
        point = contracts.tag_point(last_open)
        dead = contracts.dead_open_reason(last_open)
        actionable = point != "—"
        if actionable:
            act += 1
        entries.append({
            "vt_symbol": vt,
            "name": name_map.get(vt, ""),
            "gap": int(r["notlim_prev"]),
            "gain30_pct": round(float(r["gain30"]) * 100, 1),
            "dd_pct": round(float(r["dd"]) * 100, 1),
            "ma20gap_pct": round(float(r["ma20gap"]) * 100, 1),
            "lim30": int(r["lim30"]) if r["lim30"] == r["lim30"] else None,
            "yin_yang": str(r["yy"]),
            "last_open_pct": round(last_open, 1) if last_open is not None else None,
            "point": point,
            "level": contracts.POINT_LEVELS.get(point, "—"),
            "actionable": actionable,
            "avoid_static": dead,
            "cold_market": contracts.is_cold_market(
                float(mkt_lim_tm1) if mkt_lim_tm1 is not None else None),
            "prev_close": round(float(r["pc"]), 2),
            "limit_price": round(float(r["limit_price"]), 2),
        })
    entries.sort(key=lambda e: (not e["actionable"], str(e["point"]), str(e["vt_symbol"])))
    exec_date = fbb_pool.next_weekday(data_date)
    return {
        "data_date": data_date.isoformat(),
        "exec_date": exec_date.isoformat(),
        "rules_version": contracts.ERBO_RULES_VERSION,
        "mkt_lim_tm1": mkt_lim_tm1,
        "entries": entries,
        "filter_stats": {"struct_n": len(entries), "actionable": act,
                         "dead": len(entries) - act},
    }
