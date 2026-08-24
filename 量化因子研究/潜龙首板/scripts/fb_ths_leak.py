"""同花顺镜像漏网 + 池外边缘带质量量化.

问题1: A串近似"空头排列 或 20日乖离率<10%"相对研究精确条件"多头排列<=10天",
        漏了多少票、漏掉的票质量如何?(用户指出"空头排列"与"多头<=10天"看似矛盾)
问题2: B串近似"近10日上涨天数>=7 且 涨幅0~15%"相对研究"阳线>=7根 且 涨幅<15%",
        漏/多收多少?
问题3: 今天涨>7%触发但刚好被底盘条件滤掉的票(边缘带: 多头11~15天等)质量如何?
        ——决定条件要不要放宽.

口径与 fb_chassis_pool.py 完全一致(触发宇宙: 触+8%, 非一字, 高开<8%, 剔污染;
卖出: 断板/次日开盘, 滑点0.5%; lu_cnt 为研究口径不含 T-1 当日, 与产品差一个边界日).
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = pd.Timestamp("2025-07-01")


def st(df):
    """紧凑统计: n/均收/胜率/>=3板率 + 验证段均收."""
    if len(df) < 10:
        return {"n": len(df)}
    v = df[~df.is_train]
    return {"n": len(df),
            "均收": round(float(df.ret.mean()) * 100, 2),
            "胜率": round(float((df.ret > 0).mean()), 3),
            ">=3板率%": round(float(df.good3.mean()) * 100, 2),
            "验n": len(v),
            "验均收": round(float(v.ret.mean()) * 100, 2) if len(v) >= 10 else None,
            "验>=3板率%": round(float(v.good3.mean()) * 100, 2) if len(v) >= 10 else None}


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count
               FROM stock_limit_up_daily WHERE is_limit_up""", conn)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main_syms = set(stocks.loc[stocks["eligible"], "vt_symbol"])

    lu = lu.copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_m = lu[lu.vt_symbol.isin(main_syms)]
    lu_all = lu_m.sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["ret10"] = g["close_price"].transform(lambda s: s / s.shift(10) - 1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    bull = ((bars.close_price > bars.ma5) & (bars.ma5 > bars.ma10)
            & (bars.ma10 > bars.ma20)).fillna(False)
    run = bull.astype(int)
    bars["trend_days"] = (run * run.groupby([bars.vt_symbol, (~bull).cumsum()]).cumsum()).clip(0, 60)
    # 空头排列(同花顺口径: MA5<MA10<MA20)
    bars["bear"] = ((bars.ma5 < bars.ma10) & (bars.ma10 < bars.ma20)).fillna(False)
    bars["bias20"] = bars["close_price"] / bars["ma20"] - 1
    bars["up_day"] = bars["close_price"] > g["close_price"].shift(1)
    bars["up10"] = bars["up_day"].groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(10, min_periods=5).sum())
    for n in (20, 60):
        bars[f"lu_cnt{n}"] = g["lu_T"].shift(1).groupby(bars.vt_symbol).transform(
            lambda s, n=n: s.rolling(n, min_periods=1).sum())
    bars["yang"] = bars.close_price > bars.open_price
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "trend_days", "lu_cnt20", "lu_cnt60", "yang10",
                "ret10", "bear", "bias20", "up10"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & (~bars["lu_tm1"])
              & ~bars["oneword"] & (bars.gap_open < 0.08)].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 8)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["lu_T"] | (k < 2), ev["open_p1"].values, eo)
    ev["ret"] = pd.Series(eo / (ev["trigger_price"] * (1 + SLIP)).values - 1, index=ev.index)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)].dropna(subset=["ret"])
    ev["good3"] = k.loc[ev.index] >= 3
    ev["is_train"] = ev.trade_date < TRAIN_END

    V = ev.vol_ratio < 1.5
    G1 = ((ev.lu_cnt60_tm1 == 0) & (ev.trend_days_tm1 <= 10)).fillna(False)
    G3 = ((ev.yang10_tm1 >= 7) & (ev.ret10_tm1 < 0.15) & (ev.lu_cnt20_tm1 == 0)).fillna(False)

    # ===== 问题1: A类镜像漏网 =====
    thsA = (ev.bear_tm1 | (ev.bias20_tm1 < 0.10)).fillna(False)
    thsA15 = (ev.bear_tm1 | (ev.bias20_tm1 < 0.15)).fillna(False)
    a_pool = G1 & V
    out = {"A类_G1池总": st(ev[a_pool])}
    out["A池_镜像接住"] = st(ev[a_pool & thsA])
    missA = a_pool & ~thsA
    out["A池_镜像漏掉"] = st(ev[missA])
    td = ev.trend_days_tm1
    out["A漏_趋势龄0天_无排列涨急(bias>=10)"] = st(ev[missA & (td == 0)])
    out["A漏_趋势龄1~5天_bias>=10"] = st(ev[missA & (td >= 1) & (td <= 5)])
    out["A漏_趋势龄6~10天_bias>=10"] = st(ev[missA & (td >= 6) & (td <= 10)])
    # 镜像误纳: 镜像接住但研究池不要(多头>10天但bias<10 —— 建仓过久漏进来)
    overA = (~G1) & (ev.lu_cnt60_tm1 == 0) & thsA & V
    out["A镜像_误纳_建仓过久(多头>10天但bias<10或空头?)"] = st(ev[overA])
    out["A镜像_误纳中_多头11~20天"] = st(ev[overA & (td >= 11) & (td <= 20)])
    out["A镜像_误纳中_多头>20天"] = st(ev[overA & (td > 20)])
    # 乖离阈值放宽到15%的增量
    add15 = a_pool & ~thsA & thsA15
    out["A_乖离放宽15_多接住"] = st(ev[add15])
    out["A_乖离放宽15_多误纳(多头>10)"] = st(ev[(~G1) & (ev.lu_cnt60_tm1 == 0)
                                               & ~thsA & thsA15 & V])

    # ===== 问题2: B类镜像 =====
    thsB = ((ev.up10_tm1 >= 7) & (ev.ret10_tm1 >= 0) & (ev.ret10_tm1 < 0.15)
            & (ev.lu_cnt20_tm1 == 0)).fillna(False)
    b_pool = G3 & V
    out["B类_G3池总"] = st(ev[b_pool])
    out["B池_镜像接住"] = st(ev[b_pool & thsB])
    out["B池_镜像漏掉"] = st(ev[b_pool & ~thsB])
    out["B漏_涨天不足7(阳线多但有低开高走)"] = st(ev[b_pool & (ev.up10_tm1 < 7)])
    out["B漏_涨幅下限(10日收益<0)"] = st(ev[b_pool & (ev.up10_tm1 >= 7)
                                             & (ev.ret10_tm1 < 0)])
    overB = thsB & ~G3 & V
    out["B镜像_误纳(涨天够但阳线不够)"] = st(ev[overB])

    # ===== 问题3: 池外边缘带(今天触发+8%但底盘刚好不符) =====
    in_pool = (G1 | G3) & V
    out["池外_全部触发&量比<1.5"] = st(ev[~in_pool & V])
    out["池外_多头11~12天(刚好过线)"] = st(ev[~in_pool & V & (td >= 11) & (td <= 12)
                                             & (ev.lu_cnt60_tm1 == 0)])
    out["池外_多头13~15天"] = st(ev[~in_pool & V & (td >= 13) & (td <= 15)
                                  & (ev.lu_cnt60_tm1 == 0)])
    out["池外_多头16~30天"] = st(ev[~in_pool & V & (td >= 16) & (td <= 30)
                                  & (ev.lu_cnt60_tm1 == 0)])
    out["池外_多头>30天"] = st(ev[~in_pool & V & (td > 30) & (ev.lu_cnt60_tm1 == 0)])
    out["池外_60日内有涨停1~2次(回锅)"] = st(ev[~in_pool & V
                                              & (ev.lu_cnt60_tm1.between(1, 2))])
    out["池外_60日内涨停>=3次(反复炒)"] = st(ev[~in_pool & V & (ev.lu_cnt60_tm1 >= 3)])

    # ===== 好票视角: 漏网好票长什么样 =====
    winners = ev[ev.good3 & V]
    out["好票总(触发&量比<1.5)"] = {"n": len(winners)}
    out["好票_在池"] = {"n": int(in_pool[winners.index].sum())}
    w_out = winners[~in_pool[winners.index]]
    out["好票_池外分布"] = {
        "多头11~15天": int(((td >= 11) & (td <= 15))[w_out.index].sum()),
        "多头>15天": int((td > 15)[w_out.index].sum()),
        "60日内有涨停(回锅/反复)": int((ev.lu_cnt60_tm1 >= 1)[w_out.index].sum()),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
