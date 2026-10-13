"""纯底盘池验证: 不依赖市值/价, 只用主力底盘结构条件.

好票形态(用户分类, T-1 可知, 入选型):
  G1 全新急建仓: 前60日无涨停 且 多头排列<=10天
  G2 深洗后再起: 前20日有涨停 且 自上次涨停最深回撤>=8% 且 不创20日新高
  G3 小阳建仓: 前10日>=7阳 且 前10日涨幅<15% 且 前20日无涨停
排除型底盘(参照): R1 多头<=12天; R2 非回锅贴脸

池变体(触发宇宙: 触+8%, 非一字, 高开<8%, 剔污染; 卖出: 断板/次日开盘):
  A 纯底盘+量比: (G1|G2|G3) & 量比<1.5
  B 纯底盘无量比: (G1|G2|G3)
  C 排除型+量比: R1&R2&V (即上轮P4)
  D v5参照: 市值50&价8&V&R1&R2
  E 纯底盘+量比+市值50: 看市值在纯底盘上还剩多少增量
  F/G/H 单形态: G1&V / G2&V / G3&V
  I 纯底盘+量比 删G3小阳; J 删G2深洗 —— 删除测试
  K 金安国纪各池命中检查
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


def month_stats(df):
    if len(df) < 30:
        return None
    m = df.groupby("month")["ret"].agg(["count", "mean"])
    return {"n": len(df), "月均笔数": round(float(m["count"].mean()), 1),
            "均收": round(float(df.ret.mean()) * 100, 2),
            "胜率": round(float((df.ret > 0).mean()), 3),
            "正月占比": round(float((m["mean"] > 0).mean()), 3),
            "最差月均": round(float(m["mean"].min()) * 100, 2)}


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
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

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
    bars["day_idx"] = g.cumcount()
    last_lu_day = bars["day_idx"].where(bars.lu_T).groupby(bars.vt_symbol).ffill()
    bars["days_since_lu"] = bars["day_idx"] - last_lu_day
    bars["lu_close"] = np.where(bars.lu_T, bars.close_price, np.nan)
    bars["last_lu_close"] = bars.groupby("vt_symbol")["lu_close"].ffill()
    lu_seg = bars.groupby("vt_symbol")["lu_T"].cumsum()
    bars["since_lu_low"] = bars.groupby([bars.vt_symbol, lu_seg])["low_price"].cummin()
    bars["since_lu_dd"] = bars["since_lu_low"] / bars["last_lu_close"] - 1
    for n in (20, 60):
        bars[f"lu_cnt{n}"] = g["lu_T"].shift(1).groupby(bars.vt_symbol).transform(
            lambda s, n=n: s.rolling(n, min_periods=1).sum())
    bars["high20_prev"] = g["high_price"].transform(lambda s: s.rolling(20).max().shift(1))
    bars["yang"] = bars.close_price > bars.open_price
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "trend_days", "days_since_lu", "since_lu_dd",
                "lu_cnt20", "lu_cnt60", "yang10", "ret10"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["new_high20"] = bars["close_price_tm1"] >= bars["high20_prev"] - 1e-9
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9

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
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["good3"] = k.loc[ev.index] >= 3
    ev["is_train"] = ev.trade_date < TRAIN_END

    V = ev.vol_ratio < 1.5
    S = ev.cap_yi < 50
    P = ev.close_price_tm1 < 8
    R1 = (ev.trend_days_tm1 <= 12).fillna(True)
    R2 = ~((ev.days_since_lu_tm1 >= 2) & (ev.days_since_lu_tm1 <= 12)
           & (ev.since_lu_dd_tm1 > -0.05)).fillna(False)

    G1 = ((ev.lu_cnt60_tm1 == 0) & (ev.trend_days_tm1 <= 10)).fillna(False)
    G2 = ((ev.lu_cnt20_tm1 >= 1) & (ev.since_lu_dd_tm1 <= -0.08)
          & ~ev.new_high20.fillna(False)).fillna(False)
    G3 = ((ev.yang10_tm1 >= 7) & (ev.ret10_tm1 < 0.15) & (ev.lu_cnt20_tm1 == 0)).fillna(False)
    CHASSIS = G1 | G2 | G3

    winners = ev[ev.good3]
    wkeys = set(zip(winners.vt_symbol, winners.trade_date))

    def evaluate(mask, label):
        sub = ev[mask.fillna(False)]
        if len(sub) < 30:
            return {"label": label, "n": len(sub)}
        skeys = set(zip(sub.vt_symbol, sub.trade_date))
        caught = sum(1 for kk_ in wkeys if kk_ in skeys)
        rec = {"label": label,
               "训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
               "全": month_stats(sub),
               ">=3板率%": round(float(sub.good3.mean()) * 100, 2),
               "捕获率": round(caught / max(len(wkeys), 1), 3)}
        m = sub.groupby("month")["ret"].agg(["mean"])
        rec["负月"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                      for ix, rr in m.iterrows() if rr["mean"] <= 0}
        return rec

    out = {
        "A_纯底盘+量比": evaluate(CHASSIS & V, "A (G1|G2|G3)&V"),
        "B_纯底盘无量比": evaluate(CHASSIS, "B (G1|G2|G3)"),
        "C_排除型+量比(P4)": evaluate(R1 & R2 & V, "C R1&R2&V"),
        "D_v5参照": evaluate(S & P & V & R1 & R2, "D v5"),
        "E_纯底盘+量比+市值50": evaluate(CHASSIS & V & S, "E 底盘&V&市值50"),
        "F_G1全新急建&V": evaluate(G1 & V, "F G1&V"),
        "G_G2深洗再起&V": evaluate(G2 & V, "G G2&V"),
        "H_G3小阳&V": evaluate(G3 & V, "H G3&V"),
        "I_纯底盘&V_删G3": evaluate((G1 | G2) & V, "I (G1|G2)&V"),
        "J_纯底盘&V_删G2": evaluate((G1 | G3) & V, "J (G1|G3)&V"),
        "K_纯底盘&V_删G1": evaluate((G2 | G3) & V, "K (G2|G3)&V"),
    }
    # 形态重叠度 + 金安国纪命中
    out["形态重叠"] = {
        "G1覆盖%": round(float(G1.mean()) * 100, 1), "G2覆盖%": round(float(G2.mean()) * 100, 1),
        "G3覆盖%": round(float(G3.mean()) * 100, 1),
        "并集覆盖%": round(float(CHASSIS.mean()) * 100, 1),
        "好票中并集覆盖%": round(float(CHASSIS[winners.index].mean()) * 100, 1),
    }
    ja = ev[ev.vt_symbol == "002636.SZSE"]
    out["金安国纪_各池命中"] = {
        "n_触发": len(ja),
        "在A纯底盘": bool((CHASSIS & V).loc[ja.index].any()) if len(ja) else None,
        "在D_v5": bool((S & P & V & R1 & R2).loc[ja.index].any()) if len(ja) else None,
        "G1": bool(G1.loc[ja.index].any()) if len(ja) else None,
        "G2": bool(G2.loc[ja.index].any()) if len(ja) else None,
        "G3": bool(G3.loc[ja.index].any()) if len(ja) else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
