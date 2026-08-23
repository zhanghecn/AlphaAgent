"""补刀: 完整7条件池下 价位带 × 高开桶 交叉 —— 20~50带唯一的正收益口袋(高开2~6%)
在池条件下是否存活, 决定它是"第二体制"还是彻底不做."""
from __future__ import annotations

import os, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = "2025-07-01"


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word
               FROM stock_limit_up_daily""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    cap_map = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()
    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"],
                             bars["open_price"], bars["trigger_price"]) * (1 + SLIP)
    bars["sealed"] = bars["lu_T"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    pool7 = ((~bars["lu_tm1"]) & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
             & (bars["low_price_tm1"] > bars["ma20_tm1"]) & (bars["dist_ma20"] <= 0.12)
             & (bars["turnover_rate_tm1"] < 8) & (bars["cap_yi"] < 1200))
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool7
              & ~bars["oneword_strict"]].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, eo)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1).__abs__() > 0.11
    ev = ev[~pd.Series(disc, index=ev.index).fillna(False)]
    ev["is_train"] = ev.trade_date < pd.Timestamp(TRAIN_END)
    px = ev["close_price_tm1"]

    def st(sub):
        r = sub["ret"].dropna()
        if len(r) < 30:
            return {"n": len(r)}
        va = sub.loc[~sub.is_train, "ret"].dropna()
        ex = sub.loc[sub.month != "2024-09", "ret"].dropna()
        return {"n": len(r), "全": round(float(r.mean()) * 100, 2),
                "验": round(float(va.mean()) * 100, 2) if len(va) else None,
                "剔2409": round(float(ex.mean()) * 100, 2),
                "胜率": round(float((r > 0).mean()), 3),
                "连板率": round(float((sub.streak_h.fillna(0) >= 2).mean()), 3)}

    out = {}
    for blb, bm in [("<12", px < 12), ("12~20", (px >= 12) & (px < 20)),
                    ("20~50", (px >= 20) & (px < 50))]:
        sub = ev[bm]
        out[blb] = {
            "全部": st(sub),
            "高开<2%": st(sub[sub.gap_open < 0.02]),
            "高开2~6%": st(sub[sub.gap_open.between(0.02, 0.06)]),
            "高开>=6%": st(sub[sub.gap_open >= 0.06]),
        }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
