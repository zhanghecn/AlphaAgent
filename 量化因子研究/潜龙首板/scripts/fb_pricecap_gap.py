"""A: 股价×市值 交叉验证(好/差行情月分开) —— 检验股价<12是否regime依赖.
B: 高开>=8% 分钟级精细拆分(触板时间/封板/可买性) —— 样本边界诚实报告.
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = "2025-07-01"


def load_replay():
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
    pool = ((~bars["lu_tm1"]) & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"]) & (bars["dist_ma20"] <= 0.12)
            & (bars["turnover_rate_tm1"] < 8) & (bars["cap_yi"] < 1200))
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool & ~bars["oneword_strict"]].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    exit_open = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        exit_open = np.where((k == kk).values, ev[f"open_p{kk}"].values, exit_open)
    exit_open = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, exit_open)
    ev["ret"] = pd.Series(exit_open / ev["entry"].values - 1, index=ev.index)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (ev[f"open_p{kk}"] / ev[f"close_p{kk-1}"] - 1).abs() > 0.11
    ev = ev[~disc.fillna(False)]
    ev["is_train"] = ev.trade_date < pd.Timestamp(TRAIN_END)
    mret = ev.groupby("month")["ret"].mean()
    good_months = set(mret[mret >= 0.01].index)
    ev["good_month"] = ev.month.isin(good_months)
    return ev, main_syms, cap_map


def stat(df, label):
    r = df["ret"].dropna()
    if len(r) < 20:
        return {"label": label, "n": len(r)}
    return {"label": label, "n": len(r), "ret": round(float(r.mean()) * 100, 2),
            "win": round(float((r > 0).mean()), 3), "seal": round(float(df.sealed.mean()), 3)}


def part_a(ev):
    out = []
    pbins = [(0, 12), (12, 25), (25, 9999)]
    cbins = [(0, 300), (300, 1200)]
    for seg_lb, seg in [("全样本", ev), ("训练段", ev[ev.is_train]), ("验证段", ev[~ev.is_train]),
                        ("好行情月", ev[ev.good_month]), ("差行情月", ev[~ev.good_month])]:
        for plo, phi in pbins:
            for clo, chi in cbins:
                sub = seg[seg.close_price_tm1.between(plo, phi, inclusive="left")
                          & seg.cap_yi.between(clo, chi, inclusive="left")]
                r = stat(sub, f"{seg_lb}|股价{plo}-{phi}|市值{clo}-{chi}")
                out.append(r)
    return out


def part_b(main_syms, cap_map):
    """高开>=8%(未一字)分钟级: 触板时间/封板/可买性/收益."""
    with psycopg.connect(DSN) as conn:
        rows = []
        for interval, lo, hi in [("1m", "2026-06-01", "2026-08-12"), ("5m", "2026-04-01", "2026-05-31")]:
            daily = pd.read_sql(
                """SELECT vt_symbol, trade_date, open_price, close_price, high_price, low_price
                   FROM stock_daily_bars WHERE trade_date BETWEEN %s AND %s""", conn, params=(lo, hi))
            daily = daily[daily.vt_symbol.isin(main_syms)]
            daily["trade_date"] = pd.to_datetime(daily["trade_date"])
            daily = daily.sort_values(["vt_symbol", "trade_date"])
            daily["prev_close"] = daily.groupby("vt_symbol")["close_price"].shift(1)
            daily["gap"] = daily.open_price / daily.prev_close - 1
            limit_px = (daily.prev_close * 1.1 + 1e-9).round(2)
            daily["open_at_limit"] = daily.open_price >= limit_px * 0.999
            sel = daily[(daily.gap >= 0.08) & (~daily.open_at_limit) & daily.prev_close.notna()]
            print(f"[{interval}] 高开>=8%未一字: {len(sel)} 个", file=sys.stderr)
            for r in sel.itertuples():
                mb = pd.read_sql(
                    """SELECT bar_time, open_price, close_price, high_price, low_price
                       FROM stock_minute_bars WHERE vt_symbol=%s AND trade_date=%s AND interval=%s
                       ORDER BY bar_time""",
                    conn, params=(r.vt_symbol, r.trade_date.date(), interval))
                if mb.empty:
                    continue
                lp = round(r.prev_close * 1.1 + 1e-9, 2)
                mb["tt"] = pd.to_datetime(mb["bar_time"]).dt.strftime("%H:%M")
                touch = mb[mb.high_price >= lp - 1e-6]
                t_touch = touch.iloc[0]["tt"] if len(touch) else None
                # 进场模拟: 触板那根bar的下一根开盘价买入(若其最低价<涨停价则可买)
                fillable = None
                entry_ret_close = None
                if len(touch):
                    ti = mb.index.get_loc(touch.index[0])
                    if ti + 1 < len(mb):
                        nxt = mb.iloc[ti + 1]
                        fillable = nxt["low_price"] < lp - 1e-6
                        if fillable:
                            entry_ret_close = r.close_price / nxt["open_price"] - 1
                rows.append({
                    "sym": r.vt_symbol, "date": str(r.trade_date.date()), "interval": interval,
                    "gap": round(r.gap * 100, 1),
                    "t_touch": t_touch, "fast_touch": bool(t_touch and t_touch <= ("09:36" if interval == "1m" else "09:40")),
                    "sealed": bool(abs(r.close_price - lp) < 0.005),
                    "fillable": fillable,
                    "ret_d0": round(entry_ret_close * 100, 2) if entry_ret_close is not None else None,
                })
        return rows


def main():
    ev, main_syms, cap_map = load_replay()
    out = {"A_cross": part_a(ev)}
    rows = part_b(main_syms, cap_map)
    df = pd.DataFrame(rows)
    out["B_n"] = len(df)
    if len(df):
        for lb, sub in [("全部", df), ("2分钟内触板", df[df.fast_touch]),
                        ("未快速触板", df[~df.fast_touch])]:
            sealed = sub[sub.sealed]
            fill = sub[sub.fillable == True]
            out[f"B::{lb}"] = {
                "n": len(sub), "seal": round(sub.sealed.mean(), 3),
                "fillable_ratio": round((sub.fillable == True).mean(), 3),
                "fill_n": len(fill),
                "d0_close_after_fill": round(fill.ret_d0.mean(), 2) if len(fill) else None,
            }
        out["B_rows"] = rows[:60]
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
