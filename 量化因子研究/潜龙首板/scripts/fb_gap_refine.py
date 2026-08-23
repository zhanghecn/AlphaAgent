"""gap_open 精细化 + 组合条件 + 月度正收益率(最终检验)."""
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
    bars["ret60"] = g["close_price"].transform(lambda s: s / s.shift(60) - 1)
    bars["open_p1"] = g["open_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20", "ret60"]:
        bars[col + "_tm1"] = g[col].shift(1)

    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars["lu_cnt20"] = g["lu_T"].transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())

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
    # 开盘即涨停(一字/秒板)≈买不进: 开盘价 >= 涨停价*0.999
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["open_at_limit"] = bars["open_price"] >= limit_px * 0.999

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

    mret0 = ev.groupby("month")["ret"].mean()
    loss_months = set(mret0[mret0 < 0.01].index)

    def full(mask, label):
        sub = ev[mask.fillna(False)]
        if len(sub) < 30:
            return {"label": label, "n": len(sub)}
        m = sub.groupby("month")["ret"].mean()
        l = sub[sub.month.isin(loss_months)]
        return {"label": label, "n": len(sub),
                "ret": round(sub.ret.mean() * 100, 2),
                "seal": round(sub.sealed.mean(), 3),
                "pos_month": f"{int((m > 0).sum())}/{len(m)}",
                "LOSS_ret": round(l.ret.mean() * 100, 2) if len(l) > 5 else None,
                "win": round((sub.ret > 0).mean(), 3)}

    out = {"base": full(pd.Series(True, index=ev.index), "原7条")}
    # gap 分箱
    bins = [(-1, 0), (0, 0.01), (0.01, 0.02), (0.02, 0.03), (0.03, 0.04),
            (0.04, 0.06), (0.06, 0.08), (0.08, 1)]
    out["gap_bins"] = []
    for lo, hi in bins:
        m = (ev.gap_open > lo) & (ev.gap_open <= hi)
        r = full(m, f"gap {lo:.0%}~{hi:.0%}")
        out["gap_bins"].append(r)
    # 组合
    g28 = (ev.gap_open >= 0.02) & (ev.gap_open < 0.08)
    out["combos"] = [
        full(ev.gap_open >= 0.02, "gap>=2%"),
        full((ev.gap_open >= 0.02) & (~ev.open_at_limit), "gap>=2% 剔除开盘即板"),
        full((ev.gap_open >= 0.08) & (ev.open_at_limit), "gap>=8% 且开盘即板(买不进)"),
        full((ev.gap_open >= 0.08) & (~ev.open_at_limit), "gap>=8% 未封开(回封型可买)"),
        full(g28, "gap 2~8%"),
        full(g28 & (ev.lu_cnt20 == 0), "gap2~8 + 近20日无涨停"),
        full(g28 & (ev.ret60_tm1 < 0.10), "gap2~8 + 前60日<10%"),
        full(g28 & (ev.lu_cnt20 == 0) & (ev.ret60_tm1 < 0.10), "gap2~8 + 无涨停 + 前60<10%"),
        full((ev.gap_open >= 0.02) & (ev.ret60_tm1 < 0.10), "gap>=2 + 前60<10%"),
        full((ev.gap_open >= 0.02) & (~ev.open_at_limit) & (ev.ret60_tm1 < 0.10), "gap>=2 剔开盘即板 + 前60<10%"),
    ]
    # 最终组合的逐月
    final = ev[(ev.gap_open >= 0.02) & (ev.gap_open < 0.08) & (ev.lu_cnt20 == 0) & (ev.ret60_tm1 < 0.10)]
    fm = final.groupby("month")["ret"].agg(["mean", "size"]).round(4)
    out["final_by_month"] = [{"month": str(i), "n": int(r["size"]), "ret": round(r["mean"] * 100, 2)}
                             for i, r in fm.iterrows()]

    # ===== 熔断纪律回测: 月内累计亏 X% 后当月停手(按日组合收益序列) =====
    def circuit(df, x):
        """返回逐月 (无熔断总收益, 熔断后总收益, 熔断后天数/总天数)."""
        dr = df.groupby("trade_date")["ret"].mean().dropna()
        res = {}
        for mth, grp in dr.groupby(dr.index.to_period("M").astype(str)):
            cum = 0.0
            kept = []
            for dt, r in grp.items():
                if cum <= x:
                    break
                kept.append(r)
                cum += r
            res[str(mth)] = (float(grp.sum()), float(np.sum(kept)) if kept else 0.0,
                             len(kept), len(grp))
        return res

    for label, df in [("原7条", ev), ("gap>=2剔一字", ev[(ev.gap_open >= 0.02) & (~ev.open_at_limit)])]:
        base = circuit(df, -999)  # 无熔断
        for x in (-0.03, -0.05, -0.08):
            res = circuit(df, x)
            full_sums = [v[0] for v in res.values()]
            kept_sums = [v[1] for v in res.values()]
            out[f"circuit::{label}::x={x}"] = {
                "月均总收益_无熔断": round(float(np.mean(full_sums)) * 100, 2),
                "月均总收益_熔断后": round(float(np.mean(kept_sums)) * 100, 2),
                "最差月_无熔断": round(min(full_sums) * 100, 2),
                "最差月_熔断后": round(min(kept_sums) * 100, 2),
                "正收益月_无熔断": f"{sum(1 for v in full_sums if v > 0)}/{len(full_sums)}",
                "正收益月_熔断后": f"{sum(1 for v in kept_sums if v > 0)}/{len(kept_sums)}",
                "熔断改善月数": sum(1 for v in res.values() if v[1] > v[0]),
                "熔断变差月数": sum(1 for v in res.values() if v[1] < v[0] - 1e-9),
            }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
