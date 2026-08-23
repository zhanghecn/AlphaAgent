"""除权污染量化 + 开盘即板定义修正.

1. 污染: 持有窗口内隔夜跳空 |open/前收-1| > 11%(10%限幅下不可能=除权/复牌无涨跌幅)
   → 统计受影响笔数, 剔除后重算整体/逐月.
2. 开盘即板修正: 真正买不进 = low >= 涨停价*0.999(一字封死全天无低位成交);
   open>=limit 但 low<limit = 开盘触板但有成交(可买, 含秒板炸板/回封) → 分组看收益.
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005


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
    bars["open_at_limit"] = bars["open_price"] >= limit_px * 0.999
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999  # 全天未低于涨停价=真买不进

    pool = ((~bars["lu_tm1"])
            & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"])
            & (bars["dist_ma20"] <= 0.12)
            & (bars["turnover_rate_tm1"] < 8)
            & (bars["cap_yi"] < 1200))
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool].copy()

    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    exit_open = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        exit_open = np.where((k == kk).values, ev[f"open_p{kk}"].values, exit_open)
    exit_open = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, exit_open)
    ev["ret"] = pd.Series(exit_open / ev["entry"].values - 1, index=ev.index)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)

    # ===== 1. 除权/复牌污染: 持有窗口内任意隔夜跳空 > 11% =====
    # 进场夜: open_p1 vs close(T); 持有期: open_pj vs close_p(j-1)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (ev[f"open_p{kk}"] / ev[f"close_p{kk-1}"] - 1).abs() > 0.11
    ev["polluted"] = disc.fillna(False)
    pol = ev[ev.polluted]
    print(f"污染笔数: {len(pol)}/{len(ev)} = {len(pol)/len(ev):.2%}", file=sys.stderr)

    def stat(df, label):
        r = df["ret"].dropna()
        m = df.groupby("month")["ret"].mean()
        return {"label": label, "n": len(df),
                "ret": round(float(r.mean()) * 100, 2),
                "win": round(float((r > 0).mean()), 3),
                "pos_month": f"{int((m > 0).sum())}/{len(m)}"}

    out = {"pollution_n": len(pol), "pollution_pct": round(len(pol) / len(ev), 4)}
    out["all_with_pollution"] = stat(ev, "含污染")
    out["all_clean"] = stat(ev[~ev.polluted], "剔除污染")
    out["polluted_only"] = stat(pol, "仅污染笔")
    # 剔除污染后的逐月
    m2 = ev[~ev.polluted].groupby("month")["ret"].agg(["mean", "size"])
    out["clean_by_month"] = [{"month": str(i), "n": int(r["size"]), "ret": round(r["mean"] * 100, 2)}
                             for i, r in m2.iterrows() if r["size"] >= 5]

    # ===== 2. 开盘即板定义修正(gap>=8% 细分) =====
    g8 = ev[ev.gap_open >= 0.08]
    out["gap8_split"] = [
        stat(g8[g8.oneword_strict], "gap>=8% 真一字封死(买不进)"),
        stat(g8[(~g8.oneword_strict) & g8.open_at_limit], "gap>=8% 开盘触板但有低位成交(可买)"),
        stat(g8[~g8.open_at_limit], "gap>=8% 开盘未触板(可买)"),
        stat(ev[(ev.gap_open >= 0.02) & (~ev.oneword_strict)], "gap>=2% 仅剔真一字"),
        stat(ev[(ev.gap_open >= 0.02) & (~ev.oneword_strict) & (~ev.polluted)], "gap>=2% 剔真一字+剔污染"),
        stat(ev[~ev.polluted], "原7条 剔污染"),
    ]
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
