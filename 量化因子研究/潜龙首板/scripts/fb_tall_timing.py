"""买点时点诚实性终测(分钟era 2026-06~08, S+P池: 市值<50+价<8):

M1 触及即买(日线保守口径基准)
M2 收住确认(触板分钟收住→下一分钟开盘买, 潜龙实时规则同款)
M3 收住+触及量比<1.0(盘中可比口径)
M4 收住+触及量比<1.5
M5 尾盘确认无V: 14:50 价格仍>=触发价 且 非封死(14:51开盘价<涨停价可成交) → 14:51开盘买
M6 尾盘确认+V: 加 14:50 累计量比<1.5(此刻量比≈全日,无前视)
M7 尾盘确认+V<1.2

所有变体共用: 卖出=断板日开盘/次日开盘(日线), 进场分钟真实价格×1.005滑点, 高开>=8%不做.
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


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume
               FROM stock_daily_bars WHERE trade_date >= '2026-01-01'""", conn)
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
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["open_p1"] = g["open_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["close_tm1"] = g["close_price"].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["trigger_price"] = bars["close_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_tm1"] - 1
    limit_px = (bars["close_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999
    bars["limit_px"] = limit_px

    ev = bars[(bars.trade_date >= "2026-06-01") & bars["triggered"] & (~bars["lu_tm1"])
              & ~bars["oneword_strict"] & (bars.cap_yi < 50) & (bars.close_tm1 < 8)
              & (bars.gap_open < 0.08)].copy()
    ev["k"] = ev["streak_h"].fillna(0).astype(int).clip(0, 8)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((ev["k"] == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["lu_T"] | (ev["k"] < 2), ev["open_p1"].values, eo)
    ev["exit_px"] = eo
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)].dropna(subset=["exit_px"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)

    results = {f"M{i}": [] for i in range(1, 8)}
    with psycopg.connect(DSN) as conn:
        for mth, gsub in ev.groupby("month"):
            pairs = gsub[["vt_symbol", "trade_date"]].drop_duplicates()
            vals = ",".join(f"('{s}','{d.date()}')" for s, d in pairs.itertuples(index=False))
            mb = pd.read_sql(
                f"""SELECT m.vt_symbol, m.trade_date, m.bar_time, m.open_price, m.close_price,
                           m.high_price, m.volume
                    FROM stock_minute_bars m JOIN (VALUES {vals}) AS v(s, d)
                      ON m.vt_symbol = v.s AND m.trade_date = v.d::date
                    WHERE m.interval = '1m'""", conn)
            if mb.empty:
                continue
            mb["trade_date"] = pd.to_datetime(mb["trade_date"])
            mb["bar_time"] = pd.to_datetime(mb["bar_time"])
            mb["tt"] = mb["bar_time"].dt.strftime("%H:%M")
            eidx = gsub.set_index(["vt_symbol", "trade_date"])
            for (sym, d), day in mb.groupby(["vt_symbol", "trade_date"]):
                key = (sym, d)
                if key not in eidx.index:
                    continue
                e = eidx.loc[key]
                if isinstance(e, pd.DataFrame):
                    e = e.iloc[0]
                day = day.sort_values("bar_time").reset_index(drop=True)
                trig = float(e["trigger_price"])
                lpx = float(e["limit_px"])
                vref = float(e["vol_ma5_prev"]) if e["vol_ma5_prev"] else np.nan
                minute_total = float(day["volume"].sum())
                daily_vol = float(e["volume"])
                if minute_total <= 0 or daily_vol <= 0 or not np.isfinite(vref):
                    continue
                scale = daily_vol / minute_total
                hit = day.index[day["high_price"] >= trig - 1e-9]
                if len(hit) == 0:
                    continue
                fh = int(hit[0])
                vol_cum = day["volume"].cumsum() * scale
                vr_at = vol_cum / vref          # 各分钟累计量比(日线单位)
                exit_px = float(e["exit_px"])

                # M1 触及即买(触发价)
                results["M1"].append(exit_px / (trig * (1 + SLIP)) - 1)
                # M2 收住: 触板分钟收≥触发价, 下一分钟开盘买
                held = day.loc[fh, "close_price"] >= trig - 1e-9
                if held and fh + 1 < len(day) and day.loc[fh, "tt"] <= "11:30":
                    ent = float(day.loc[fh + 1, "open_price"]) * (1 + SLIP)
                    results["M2"].append(exit_px / ent - 1)
                    vr_touch = float(vr_at.iloc[fh])
                    if vr_touch < 1.0:
                        results["M3"].append(exit_px / ent - 1)
                    if vr_touch < 1.5:
                        results["M4"].append(exit_px / ent - 1)
                # 尾盘确认: 14:50 收盘仍>=触发价, 14:51 开盘买(非封死才有成交)
                d1450 = day[day.tt <= "14:50"]
                if len(d1450) and float(d1450["close_price"].iloc[-1]) >= trig - 1e-9:
                    nxt = day[day.tt == "14:51"]
                    if len(nxt):
                        ent1451 = float(nxt["open_price"].iloc[0])
                        sealed_no_fill = ent1451 >= lpx * 0.999
                        if not sealed_no_fill:
                            ent = ent1451 * (1 + SLIP)
                            results["M5"].append(exit_px / ent - 1)
                            vr1450 = float(vr_at.iloc[len(d1450) - 1])
                            if vr1450 < 1.5:
                                results["M6"].append(exit_px / ent - 1)
                            if vr1450 < 1.2:
                                results["M7"].append(exit_px / ent - 1)
            del mb

    out = {}
    for name, rets in results.items():
        r = pd.Series(rets).dropna()
        out[name] = {"n": len(r), "均收": round(float(r.mean()) * 100, 2) if len(r) else None,
                     "胜率": round(float((r > 0).mean()), 3) if len(r) else None,
                     "中位": round(float(r.median()) * 100, 2) if len(r) else None}
    # 月度拆分 M2/M5/M6
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
