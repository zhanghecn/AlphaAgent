"""首板接力×关键条件: 首板收盘确认(非一字+小市值+低价+不爆量) → T+1开盘买 → 断板卖.

V(量比)条件 T 日收盘才确定, 所以可执行买点 = T+1 开盘(真实成交价, 无打板成交争议).
宇宙: 主板非ST, 首板封住非一字, 2023-01起.
进场: T+1 开盘 ×1.005; T+1 一字开(买不进)剔除.
卖出: streak>=2 → 断板日开盘(cap 8); 未走出2板 → T+2 开盘.
对照组:
  R0 裸接力(无筛选)
  R_S / R_P / R_V 单条
  R_SP / R_SV / R_PV / R_SPV 组合
  R_SPV+gap2<7% / R_SPV+gap2在2~7%(竞价过强不接?)
每项: 训/验/全 均收/胜率/正月占比/月笔 + 负月明细 + >=3板率.
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
                      low_price, volume, turnover_rate, change_pct
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
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    bars["close_tm1"] = g["close_price"].shift(1)
    bars["low_tm1"] = g["low_price"].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    limit_px = (bars["close_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_T"] = bars["low_price"] >= limit_px * 0.999
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["vol_ratio_T"] = bars["volume"] / bars["vol_ma5_prev"]

    # 宇宙: 首板封住 非一字
    ev = bars[bars["streak_h"].notna() & (bars.trade_date >= "2023-01-01")
              & ~bars["oneword_T"]].copy()
    ev["k"] = ev["streak_h"].astype(int).clip(1, 8)
    limit_p1 = (ev["close_price"] * 1.1 + 1e-9).round(2)
    ev["p1_oneword_open"] = ev["open_p1"] >= limit_p1 * 0.999   # T+1 一字开买不进
    ev["gap2"] = ev["open_p1"] / ev["close_price"] - 1
    ev["entry"] = ev["open_p1"] * (1 + SLIP)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((ev["k"] == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(ev["k"] < 2, ev["open_p2"].values, eo)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)]
    ev = ev[~ev["p1_oneword_open"]]
    ev = ev.dropna(subset=["ret"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["good3"] = ev["streak_h"] >= 3
    ev["is_train"] = ev.trade_date < TRAIN_END

    S = ev.cap_yi < 50
    P = ev.close_tm1 < 8
    V = ev.vol_ratio_T < 1.5
    combos = {
        "R0_裸接力": pd.Series(True, index=ev.index),
        "R_S": S, "R_P": P, "R_V": V,
        "R_SP": S & P, "R_SV": S & V, "R_PV": P & V,
        "R_SPV": S & P & V,
        "R_SPV+gap2<7%": S & P & V & (ev.gap2 < 0.07),
        "R_SPV+gap2在2~7%": S & P & V & (ev.gap2.between(0.02, 0.07)),
        "R_SPV+gap2<4%": S & P & V & (ev.gap2 < 0.04),
    }
    out = {}
    for name, m in combos.items():
        sub = ev[m]
        rec = {"训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
               "全": month_stats(sub),
               ">=3板率%": round(float(sub.good3.mean()) * 100, 2) if len(sub) else None}
        mm = sub.groupby("month")["ret"].agg(["count", "mean"])
        rec["负月明细"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                          for ix, rr in mm.iterrows() if rr["mean"] <= 0}
        out[name] = rec
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
