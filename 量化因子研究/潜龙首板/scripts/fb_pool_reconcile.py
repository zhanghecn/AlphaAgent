"""P0 对账:产品池(qianlong.pool.compute_pool) vs 研究管线池,随机 5 个数据日.

研究管线口径(fb_final_binary pool7 + 股价<12 = v4 8 条):
  主板(else 分支)/非ST(名称含ST)/昨涨0~5/昨低>MA20/距MA20<=12%/换手<8/市值<1200亿/价<12/昨日未涨停
产品口径: is_eligible_main_board(600/601/603/605+000/001/002/003, 剔ST/退/N/C/S前缀)
两套宇宙差异单独报告;条件逻辑用同一宇宙再对一次(应 100%)。
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.qianlong import pool as pool_mod  # noqa: E402
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def research_pool(data_date, universe="research"):
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, close_price, low_price, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= %s AND trade_date <= %s""",
            conn, params=(data_date - pd.Timedelta(days=45), data_date))
        lu = pd.read_sql(
            "SELECT vt_symbol, trade_date, is_limit_up FROM stock_limit_up_daily WHERE trade_date = %s",
            conn, params=(data_date,))
    if universe == "research":
        stocks["board"] = np.where(
            stocks["symbol"].str.startswith(("300", "301")), "cyb",
            np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                     np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
        stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
        uni = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    else:
        uni = set(stocks.loc[stocks.apply(
            lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1),
            "vt_symbol"])
    cap = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()
    bars = bars[bars.vt_symbol.isin(uni)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    # 与产品一致的 change_pct 缺口回填(收盘对收盘推导)
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    last = bars.groupby("vt_symbol", sort=False).tail(1).copy()
    last = last[last.trade_date == pd.Timestamp(data_date)]
    last["cap_yi"] = last.vt_symbol.map(cap)
    last["dist"] = last.close_price / last.ma20 - 1
    lu_set = set(lu.loc[lu.is_limit_up, "vt_symbol"])
    mask = (last.ma20.notna()
            & last.change_pct.between(0, 5, inclusive="both")
            & (last.low_price > last.ma20)
            & (last.dist <= 0.12)
            & (last.turnover_rate < 8)
            & (last.cap_yi < 1200)
            & (last.close_price < 12)
            & (~last.vt_symbol.isin(lu_set)))
    return set(last.loc[mask, "vt_symbol"])


def main():
    with psycopg.connect(DSN) as conn:
        dates = [r[0] for r in conn.execute(
            """SELECT DISTINCT trade_date FROM stock_daily_bars
               WHERE trade_date <= '2026-08-21' ORDER BY trade_date DESC LIMIT 40""").fetchall()]
    pick = [dates[i] for i in (0, 7, 15, 23, 39)]  # 分散 5 个数据日
    # 显式纳入 change_pct 缺口日(覆盖率仅 4/5537)验证推导回填
    for gap_day in ("2026-08-12", "2026-07-31"):
        gd = pd.Timestamp(gap_day).date()
        if gd not in pick:
            pick.append(gd)
    out = {}
    for d in pick:
        prod = pool_mod.compute_pool(d)
        prod_set = {e["vt_symbol"] for e in prod["entries"]}
        research = research_pool(d, "research")
        research_uni_p = research_pool(d, "product")
        out[str(d)] = {
            "product_n": len(prod_set),
            "research_n": len(research),
            "diff_product_minus_research": sorted(prod_set - research),
            "diff_research_minus_product": sorted(research - prod_set),
            "same_universe_exact_match": prod_set == research_uni_p,
        }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
