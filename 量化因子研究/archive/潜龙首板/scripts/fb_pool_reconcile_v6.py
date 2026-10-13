"""v6 池对账: 产品 compute_pool(挂载宿主 v6 代码) vs 研究管线底盘条件(G1|G3).
随机取 5 个历史交易日, 比较两边名单是否 100% 一致.
注意口径差: 产品窗口 130 自然日(≈88交易日), 研究管线全历史;
trend_days>10 的票两边必然一致排除, 理论上名单应完全一致.
"""
from __future__ import annotations

import os, sys, json
from datetime import date
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402
from alphaagent.server.services.qianlong import pool as qpool  # noqa: E402
from alphaagent.server.services.qianlong import contracts  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
DATES = ["2026-06-05", "2026-07-03", "2026-07-24", "2026-08-07", "2026-08-14"]


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume
               FROM stock_daily_bars WHERE trade_date >= '2025-10-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up
               FROM stock_limit_up_daily WHERE is_limit_up
               AND trade_date >= '2025-10-01'""", conn)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main_syms = set(stocks.loc[stocks["eligible"], "vt_symbol"])

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret10"] = g["close_price"].transform(lambda s: s / s.shift(10) - 1)
    bars["yang"] = bars["close_price"] > bars["open_price"]
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    bull = ((bars.close_price > bars.ma5) & (bars.ma5 > bars.ma10)
            & (bars.ma10 > bars.ma20)).fillna(False)
    run = bull.astype(int)
    bars["trend_days"] = run * run.groupby([bars.vt_symbol, (~bull).cumsum()]).cumsum()
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])["is_limit_up"]
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key).fillna(False).astype(bool).values
    bars["lu_cnt20"] = g["lu_T"].transform(lambda s: s.rolling(20, min_periods=1).sum())
    bars["lu_cnt60"] = g["lu_T"].transform(lambda s: s.rolling(60, min_periods=1).sum())
    # 对账口径: 站在 D 行直接读(含 D 当日涨停); trend/yang/ret 用 tm1=下一交易日读 D 值
    for col in ["trend_days", "yang10", "ret10"]:
        bars[col + "_tm1"] = g[col].shift(1)

    out = {}
    for ds in DATES:
        d = pd.Timestamp(ds)
        # 研究管线: 站在 D 的次一交易日视角看 tm1 条件
        nxt = bars[bars.trade_date > d]["trade_date"].min()
        has_bar_d = set(bars.loc[bars.trade_date == d, "vt_symbol"])
        snap_d = bars[bars.trade_date == d]                    # lu_cnt 在 D 行直读
        snap_nxt = bars[bars.trade_date == nxt]                # trend/yang/ret 用 tm1 于 nxt 行
        snap_nxt = snap_nxt[snap_nxt.vt_symbol.isin(has_bar_d)]
        merged = snap_nxt.merge(
            snap_d[["vt_symbol", "lu_cnt20", "lu_cnt60"]].rename(columns={"lu_cnt20": "lu_cnt20_d", "lu_cnt60": "lu_cnt60_d"}), on="vt_symbol", how="left")
        a = ((merged.lu_cnt60_d <= 0) & (merged.trend_days_tm1 <= 10))
        b = ((merged.yang10_tm1 >= 7) & (merged.ret10_tm1 < 0.15) & (merged.lu_cnt20_d <= 0))
        research_set = set(merged.loc[(a | b).fillna(False), "vt_symbol"])
        prod = qpool.compute_pool(date.fromisoformat(ds))
        prod_set = {e["vt_symbol"] for e in prod["entries"]}
        out[ds] = {
            "research_n": len(research_set), "product_n": len(prod_set),
            "交集": len(research_set & prod_set),
            "仅研究有n": len(research_set - prod_set), "仅产品有n": len(prod_set - research_set),
            "仅研究有": sorted(research_set - prod_set)[:8],
            "仅产品有": sorted(prod_set - research_set)[:8],
            "一致": research_set == prod_set,
        }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
