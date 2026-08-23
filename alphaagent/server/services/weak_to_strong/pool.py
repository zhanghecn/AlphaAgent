"""趋势弱转强盘前池计算:全部条件来自 T-1 收盘数据(无未来函数)。

口径与 量化因子研究/低吸研究/scripts/w2s_replay.py 研究管线一致(定稿 v2):
  基本条件: 主板非ST非退 / 前10个交易日内出现过≥2连板 / 昨日未涨停 / 昨日换手 3%~60%
  组划分: 最近一次≥2连板高度==2 → A 组;>=4 且距连板末日≥3个交易日 → B 组;=3 弃
  A1: 跌>3% + 下影线<2% + (量比0.7~1.2 或 振幅≥12%) + 换手8~20% + 底座(20日涨幅)<30%
  A2: (最高-收盘)/昨收<2% + 底座<30%
  B:  跌>3% + 下影线<2% + (量比0.7~1.2 或 振幅≥12%) + 换手5~25%
涨停判定与研究浮点口径一致(主板非ST:涨停价 = round(昨收×1.10+1e-9, 2),收盘等于即封板);
连板序列在本窗口内自建,与 stock_limit_up_daily(detector 口径)对主板非ST等价。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.weak_to_strong import contracts

SHANGHAI = ZoneInfo("Asia/Shanghai")
_LOOKBACK_CAL_DAYS = 130  # ≈90 个交易日,覆盖 h60pre(60)+ret20(20)+连板窗口(10)+余量


def latest_daily_date() -> date | None:
    """全市场日线最新交易日(数据基准日 T-1)。"""
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def next_weekday(day: date) -> date:
    """下一工作日(周一~周五)。节假日池会闲置,由下一真交易日的 EOD 重算覆盖。"""
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def compute_pool(data_date: date | None = None) -> dict[str, object]:
    """以 data_date(默认最新日线日)为 T-1 计算次日三组池。

    返回 {data_date, exec_date, rules_version, mkt_lim_tm1, entries, filter_stats}。
    entries 每行含 group_key/prev_close/trigger_price/limit_price 及全部条件快照值。
    """
    engine = get_engine()
    if data_date is None:
        data_date = latest_daily_date()
    if data_date is None:
        return {"data_date": None, "exec_date": None, "mkt_lim_tm1": None, "entries": [],
                "rules_version": contracts.W2S_RULES_VERSION,
                "filter_stats": {"error": "no_daily_bars"}}
    window_start = data_date - timedelta(days=_LOOKBACK_CAL_DAYS)

    bars = pd.read_sql(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover_rate,
        ).where(schema.stock_daily_bars.c.trade_date >= window_start,
                schema.stock_daily_bars.c.trade_date <= data_date),
        engine,
    )
    stocks = pd.read_sql(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.name),
        engine,
    )
    stats: dict[str, int] = {"bars_rows": int(len(bars))}
    if bars.empty or stocks.empty:
        return {"data_date": data_date.isoformat(), "exec_date": None, "mkt_lim_tm1": None,
                "entries": [], "rules_version": contracts.W2S_RULES_VERSION,
                "filter_stats": {**stats, "error": "empty_source"}}

    eligible = stocks[stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)]
    stats["eligible_universe"] = int(len(eligible))
    name_map = eligible.set_index("vt_symbol")["name"]

    bars = bars[bars["vt_symbol"].isin(set(eligible["vt_symbol"]))].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["pos"] = g.cumcount()
    # 涨停判定:主板非ST 10%,与研究浮点口径一致;窗口内 pos>=5 才参与判定
    # (对齐研究"上市>5日"口径:对老股无影响,只挡窗口内新上市票的伪连板)
    limit_px = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig_lim = bars["prev_close"].notna() & (bars["prev_close"] > 0) & (bars["pos"] >= 5)
    bars["is_lim"] = elig_lim & ((bars["close_price"] - limit_px).abs() <= 1e-6)
    is_lim_i = bars["is_lim"].astype("int8")
    brk = (~bars["is_lim"]).groupby(bars["vt_symbol"], sort=False).cumsum()
    bars["streak"] = is_lim_i.groupby([bars["vt_symbol"], brk], sort=False).cumsum()
    bars["chg"] = (bars["close_price"] / bars["prev_close"] - 1) * 100
    bars["chg_d2"] = g["chg"].shift(1)  # 前日涨跌幅(v2.2:前日也须收跌)
    low_oc = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (low_oc - bars["low_price"]) / bars["prev_close"] * 100
    bars["fade"] = (bars["high_price"] - bars["close_price"]) / bars["prev_close"] * 100
    bars["amp"] = (bars["high_price"] - bars["low_price"]) / bars["prev_close"] * 100
    bars["ret20"] = g["close_price"].transform(lambda s: (s / s.shift(20) - 1) * 100)
    gv = g["volume"]
    bars["vol_ma5"] = gv.transform(lambda s: s.rolling(5, min_periods=3).mean())
    bars["vol_rel5"] = bars["volume"] / bars["vol_ma5"]
    gs = g["streak"]
    bars["s2max10"] = gs.transform(lambda s: s.rolling(10, min_periods=1).max())
    last2 = bars["pos"].where(bars["streak"] >= 2)
    bars["last2"] = last2.groupby(bars["vt_symbol"], sort=False).ffill()
    bars["gap2"] = bars["pos"] - bars["last2"]
    bars["last_streak"] = (bars["streak"].where(bars["streak"] >= 2)
                           .groupby(bars["vt_symbol"], sort=False).ffill())
    # v2.1 位置条件:首板日收盘不得创 60 日新高(突破过顶不做)
    bars["h60pre"] = g["high_price"].transform(
        lambda s: s.rolling(contracts.HIGH60_LOOKBACK, min_periods=20).max().shift(1))
    bars["ss_pos"] = bars["last2"] - bars["last_streak"] + 1
    lk = (bars[["vt_symbol", "pos", "close_price", "h60pre"]]
          .rename(columns={"pos": "ss_pos", "close_price": "fb_close", "h60pre": "fb_h60"}))
    bars = bars.merge(lk, on=["vt_symbol", "ss_pos"], how="left")
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    bars["brk60"] = bars["fb_close"] >= bars["fb_h60"] - 1e-9  # NaN → False(历史不足视为未创)

    # 昨日大盘涨停家数(主板非ST宇宙,研究口径)
    mkt_lim = int(bars.loc[bars["trade_date"] == pd.Timestamp(data_date), "is_lim"].sum())

    last = bars.groupby("vt_symbol", sort=False).tail(1).copy()
    last = last[last["trade_date"] == pd.Timestamp(data_date)]
    stats["with_bars_on_date"] = int(len(last))

    c = contracts
    base = (last["turnover_rate"].between(c.TURNOVER_BASE_MIN, c.TURNOVER_BASE_MAX)
            & (last["s2max10"] >= 2) & (last["gap2"] >= 1) & (~last["is_lim"]))
    grp_a = last["last_streak"] == c.GROUP_A_STREAK
    grp_b = (last["last_streak"] >= c.GROUP_B_MIN_STREAK) & (last["gap2"] >= c.GROUP_B_MIN_GAP)
    cc = (last["vol_rel5"].between(c.VOL_REL5_MIN, c.VOL_REL5_MAX)
          | (last["amp"] >= c.AMP_MIN))
    panic = (last["chg"] <= c.PANIC_CHG_MAX) & (last["lshadow"] < c.LOWER_SHADOW_MAX)
    masks = {
        "a1": (base & grp_a & panic & cc
               & last["turnover_rate"].between(c.A1_TURNOVER_MIN, c.A1_TURNOVER_MAX)
               & (last["ret20"] < c.BASE20_MAX)
               & (~last["brk60"])
               & (last["chg_d2"] < 0)),
        "a2": base & grp_a & (last["fade"] < c.FADE_MAX) & (last["ret20"] < c.BASE20_MAX),
        "b": (base & grp_b & panic & cc
              & last["turnover_rate"].between(c.B_TURNOVER_MIN, c.B_TURNOVER_MAX)),
    }
    stats["pool_a1"] = int(masks["a1"].sum())
    stats["pool_a2"] = int(masks["a2"].sum())
    stats["pool_b"] = int(masks["b"].sum())
    stats["mkt_lim_tm1"] = mkt_lim

    halted = mkt_lim > c.MKT_LIM_HALT
    entries: list[dict[str, object]] = []
    for group_key, mask in masks.items():
        for row in last[mask].itertuples():
            prev_close = float(row.close_price)
            limit_price = round(prev_close * 1.10 + 1e-9, 2)
            trigger_price = (limit_price if group_key == "a2"
                             else round(prev_close * (1 + c.TRIGGER_PCT) + 1e-9, 4))
            entries.append({
                "vt_symbol": str(row.vt_symbol),
                "group_key": group_key,
                "name": str(name_map.get(row.vt_symbol) or ""),
                "prev_close": prev_close,
                "trigger_price": trigger_price,
                "limit_price": limit_price,
                "chg_tm1": _f(row.chg),
                "lshadow_tm1": _f(row.lshadow),
                "fade_tm1": _f(row.fade),
                "vol_rel5_tm1": _f(row.vol_rel5),
                "amp_tm1": _f(row.amp),
                "turnover_tm1": _f(row.turnover_rate),
                "base20_tm1": _f(row.ret20),
                "last_streak": _i(row.last_streak),
                "gap_days": _i(row.gap2),
                "mkt_lim_tm1": mkt_lim,
                "halted": halted,
            })
    entries.sort(key=lambda e: (str(e["group_key"]), str(e["vt_symbol"])))
    return {
        "data_date": data_date.isoformat(),
        "exec_date": next_weekday(data_date).isoformat(),
        "rules_version": c.W2S_RULES_VERSION,
        "mkt_lim_tm1": mkt_lim,
        "entries": entries,
        "filter_stats": stats,
    }


def _f(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _i(value: object) -> int | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) else None
