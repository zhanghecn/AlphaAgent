"""潜龙首板盘前池计算(v6 纯底盘版):底盘形态条件,全部来自 T-1 收盘数据(无未来函数)。

口径与 量化因子研究/潜龙首板/潜龙首板条件定稿.md v6.2 一致:
  A 类 全新急建仓:近 60 日涨停次数 = 0 且 多头排列(收>MA5>MA10>MA20)持续 ≤ 10 天
                  且 昨日涨幅 > -6% 且 近 5 日(T-5..T-1)单日涨幅均 < +7%
  B 类 小阳建仓:  近 10 日阳线 ≥ 7 根 且 近 10 日涨幅 < 15% 且 近 20 日涨停次数 = 0
  (A|B) 满足其一即入选;出货死规则(多头>12天/回锅贴脸)天然不满足 A|B。
量比条件(首板当天不爆量)是盘中属性,不进盘前池——由 live_scan 在确认时执行。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.qianlong import contracts

SHANGHAI = ZoneInfo("Asia/Shanghai")
# 130 自然日 ≈ 88 个交易日:覆盖 60 日涨停史 + 20 日 MA + 10 日阳线/涨幅窗口
_WINDOW_CAL_DAYS = 130


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
    """以 data_date(默认最新日线日)为 T-1 计算次日池(v6 底盘条件)。

    返回 {data_date, exec_date, rules_version, entries, filter_stats}。
    entries 每行含 prev_close/trigger_price/limit_price/vol_ma5/chassis_tag
    及底盘快照值(trend_days/yang10/ret10/lu_cnt20/lu_cnt60)。
    """
    engine = get_engine()
    if data_date is None:
        data_date = latest_daily_date()
    if data_date is None:
        return {"data_date": None, "exec_date": None, "entries": [],
                "rules_version": contracts.QIANLONG_RULES_VERSION,
                "filter_stats": {"error": "no_daily_bars"}}
    window_start = data_date - timedelta(days=_WINDOW_CAL_DAYS)

    bars = pd.read_sql(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover_rate,
            schema.stock_daily_bars.c.change_pct,
        ).where(schema.stock_daily_bars.c.trade_date >= window_start,
                schema.stock_daily_bars.c.trade_date <= data_date),
        engine,
    )
    lu = pd.read_sql(
        select(schema.stock_limit_up_daily.c.vt_symbol,
               schema.stock_limit_up_daily.c.trade_date,
               schema.stock_limit_up_daily.c.is_limit_up)
        .where(schema.stock_limit_up_daily.c.trade_date >= window_start,
               schema.stock_limit_up_daily.c.trade_date <= data_date),
        engine,
    )
    stocks = pd.read_sql(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.symbol,
               schema.stocks.c.name, schema.stocks.c.market_cap),
        engine,
    )
    stats: dict[str, int] = {"bars_rows": int(len(bars))}
    if bars.empty or stocks.empty:
        return {"data_date": data_date.isoformat(), "exec_date": None, "entries": [],
                "rules_version": contracts.QIANLONG_RULES_VERSION,
                "filter_stats": {**stats, "error": "empty_source"}}

    # 主板非 ST(产品统一宇宙口径)
    eligible = stocks[stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)]
    stats["eligible_universe"] = int(len(eligible))
    cap_yi = eligible.set_index("vt_symbol")["market_cap"] / 1e8
    name_map = eligible.set_index("vt_symbol")["name"]
    main_syms = set(eligible["vt_symbol"])

    bars = bars[bars["vt_symbol"].isin(main_syms)]
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret10"] = g["close_price"].transform(lambda s: s / s.shift(10) - 1)
    bars["vol_ma5"] = g["volume"].transform(lambda s: s.rolling(5).mean())
    bars["yang"] = bars["close_price"] > bars["open_price"]
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    # change_pct 列存在约 20 个交易日的历史缺口(覆盖率<50%);
    # 用收盘对收盘推导值回填(v6.2 起池条件依赖它:近5日最大单日涨幅)
    derived_chg = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived_chg)
    # 近5日(T-5..T-1)最大单日涨幅%:last 行即 T-1 结尾窗口,与 backtest.maxchg5_tm1 同窗口
    bars["maxchg5"] = g["change_pct"].transform(lambda s: s.rolling(5).max())
    # 连续多头排列天数(窗口截断不影响 ≤10 判定:超长趋势在窗口内读数必然 >10)
    bull = ((bars["close_price"] > bars["ma5"]) & (bars["ma5"] > bars["ma10"])
            & (bars["ma10"] > bars["ma20"])).fillna(False)
    run = bull.astype(int)
    bars["trend_days"] = run * run.groupby([bars["vt_symbol"], (~bull).cumsum()]).cumsum()

    # 涨停史(近20/60日次数,含 T-1 当日,与研究管线 shift(1).rolling(n) at T 同窗口)
    lu = lu[lu["vt_symbol"].isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_flag = lu[lu["is_limit_up"]][["vt_symbol", "trade_date"]].copy()
    lu_flag["is_lu"] = True
    bars = bars.merge(lu_flag, on=["vt_symbol", "trade_date"], how="left")
    bars["is_lu"] = bars["is_lu"].fillna(False).astype(bool)
    g2 = bars.groupby("vt_symbol", sort=False)
    bars["lu_cnt20"] = g2["is_lu"].transform(lambda s: s.rolling(20, min_periods=1).sum())
    bars["lu_cnt60"] = g2["is_lu"].transform(lambda s: s.rolling(60, min_periods=1).sum())

    last = bars.groupby("vt_symbol", sort=False).tail(1).copy()
    last = last[last["trade_date"] == pd.Timestamp(data_date)]
    stats["with_full_window"] = int(last["ma20"].notna().sum())

    last["cap_yi"] = last["vt_symbol"].map(cap_yi)
    last["dist_ma20"] = last["close_price"] / last["ma20"] - 1
    c = contracts
    cond_a = ((last["lu_cnt60"] <= c.CHASSIS_A_LU60_MAX)
              & (last["trend_days"] <= c.CHASSIS_A_TREND_DAYS_MAX)
              & (last["change_pct"] > c.CHASSIS_A_D1_CHG_MIN)
              & (last["maxchg5"] < c.CHASSIS_A_MAXCHG5_MAX))
    cond_b = ((last["yang10"] >= c.CHASSIS_B_YANG10_MIN)
              & (last["ret10"] < c.CHASSIS_B_RET10_MAX)
              & (last["lu_cnt20"] <= c.CHASSIS_B_LU20_MAX))
    last["chassis_tag"] = ""
    last.loc[cond_a & cond_b, "chassis_tag"] = "AB"
    last.loc[cond_a & ~cond_b, "chassis_tag"] = "A"
    last.loc[~cond_a & cond_b, "chassis_tag"] = "B"
    pool = last[cond_a | cond_b].copy()
    stats["pool"] = int(len(pool))
    stats["chassis_a"] = int(cond_a.sum())
    stats["chassis_b"] = int(cond_b.sum())
    stats["fail_trend_over_10"] = int((last["trend_days"] > c.CHASSIS_A_TREND_DAYS_MAX).sum())
    stats["has_lu60"] = int((last["lu_cnt60"] > c.CHASSIS_A_LU60_MAX).sum())
    # v6.2 A 类涨幅约束带外(仅 A 类受约束):近5日最大≥+7 过热接力带 / 昨日≤-6 深跌带
    stats["overheat5"] = int((last["maxchg5"] >= c.CHASSIS_A_MAXCHG5_MAX).sum())
    stats["d1_deep_drop"] = int((last["change_pct"] <= c.CHASSIS_A_D1_CHG_MIN).sum())

    entries = []
    for row in pool.itertuples():
        prev_close = float(row.close_price)
        entries.append({
            "vt_symbol": str(row.vt_symbol),
            "name": str(name_map.get(row.vt_symbol) or ""),
            "prev_close": prev_close,
            "trigger_price": round(prev_close * (1 + c.TRIGGER_PCT) + 1e-9, 4),
            "limit_price": round(prev_close * 1.1 + 1e-9, 2),
            "vol_ma5": _f(row.vol_ma5),
            "chassis_tag": str(row.chassis_tag),
            "trend_days": _f(row.trend_days),
            "yang10": _f(row.yang10),
            "ret10": _f(row.ret10),
            "lu_cnt20": _f(row.lu_cnt20),
            "lu_cnt60": _f(row.lu_cnt60),
            "ma20": _f(row.ma20),
            "dist_ma20": _f(row.dist_ma20),
            "chg_tm1": _f(row.change_pct),
            "low_tm1": _f(row.low_price),
            "turnover_rate_tm1": _f(row.turnover_rate),
            "market_cap_yi": _f(row.cap_yi),
        })
    entries.sort(key=lambda e: e["vt_symbol"])
    return {
        "data_date": data_date.isoformat(),
        "exec_date": next_weekday(data_date).isoformat(),
        "rules_version": c.QIANLONG_RULES_VERSION,
        "entries": entries,
        "filter_stats": stats,
    }


def _f(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
