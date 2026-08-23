"""D+1真实盈亏口径的判别力重估(回应用户口径修正):
差票 = 首板封住非一字, D+1 收盘 < 首板收盘(成本); 极端差 = D+1 收盘跌超-5%.
好票 = streak>=3 且 D+1 盘中最低 >= -6%(不埋人).
剔除除权伪信号: |D+1开盘/首板收盘 - 1| > 11%.

分箱对比(每档: n / D+1开盘均盈亏 / D+1收盘均盈亏 / 真差票率 / 限跌率):
量比 / 前20日涨停次数 / 前一天涨幅 / 市值 / 价位 / 首板高开
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


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
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["chg"] = bars["change_pct"].fillna(derived)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    lu_prev = g["lu_T"].shift(1)
    chg_prev = g["chg"].shift(1)
    bars["lu_cnt20"] = lu_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).sum())
    bars["close_tm1"] = g["close_price"].shift(1)
    bars["chg_tm1"] = g["chg"].shift(1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["low_p1"] = g["low_price"].shift(-1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["gap_open"] = bars["open_price"] / bars["close_tm1"] - 1
    limit_px = (bars["close_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[bars["streak_h"].notna() & ~bars["oneword"]
              & (bars.trade_date >= "2023-01-01")].copy()
    ev["d1_open"] = ev["open_p1"] / ev["close_price"] - 1
    ev["d1_close"] = ev["close_p1"] / ev["close_price"] - 1
    ev["d1_low"] = ev["low_p1"] / ev["close_price"] - 1
    # 除权伪信号剔除
    ev = ev[(ev["d1_open"].abs() <= 0.11)]
    ev = ev.dropna(subset=["d1_open", "d1_close", "vol_ratio", "close_tm1"])
    ev["bad"] = ev["d1_close"] < 0
    ev["bad5"] = ev["d1_close"] < -0.05
    ev["good"] = (ev["streak_h"] >= 3) & (ev["d1_low"] >= -0.06)
    ev["is_train"] = ev.trade_date < pd.Timestamp("2025-07-01")

    out = {"宇宙n": len(ev), "真差票率(D+1收<成本)": round(float(ev.bad.mean()), 3),
           "限跌率(D+1收<-5%)": round(float(ev.bad5.mean()), 3),
           "好票率(用户口径)": round(float(ev.good.mean()), 4)}

    def bins(col, edges, labels, mul=1):
        cat = pd.cut(ev[col] * mul, edges, labels=labels)
        rows = []
        for lb, sub in ev.groupby(cat, observed=True):
            if len(sub) < 50:
                continue
            rows.append({"档": str(lb), "n": len(sub),
                         "D+1开盘均%": round(float(sub.d1_open.mean()) * 100, 2),
                         "D+1收盘均%": round(float(sub.d1_close.mean()) * 100, 2),
                         "真差票率%": round(float(sub.bad.mean()) * 100, 1),
                         "限跌率%": round(float(sub.bad5.mean()) * 100, 1),
                         "好票率%": round(float(sub.good.mean()) * 100, 1)})
        return rows

    out["量比"] = bins("vol_ratio", [0, 0.8, 1.2, 2, 3, 5, 500], ["<0.8", "0.8~1.2", "1.2~2", "2~3", "3~5", ">5"])
    out["前20日涨停次数"] = bins("lu_cnt20", [-1, 0, 1, 2, 100], ["0次", "1次", "2次", "3次+"])
    out["前一天涨幅"] = bins("chg_tm1", [-100, -2, 0, 2, 5, 9, 100], ["<-2%", "-2~0%", "0~2%", "2~5%", "5~9%", ">9%"])
    out["市值亿"] = bins("cap_yi", [0, 30, 50, 80, 150, 300, 100000], ["<30", "30~50", "50~80", "80~150", "150~300", ">300"])
    out["价位"] = bins("close_tm1", [0, 3, 5, 8, 12, 20, 10000], ["<3", "3~5", "5~8", "8~12", "12~20", ">20"])
    out["首板高开"] = bins("gap_open", [-1, 0, 0.02, 0.05, 1], ["低开", "0~2%", "2~5%", ">5%"], 1)

    # 交叉: 前一天涨幅>5% × 前20日有涨停(回锅肉) —— 用户直觉的联合画像
    cross = {
        "前一天>5% 且 前20日有涨停": (ev.chg_tm1 > 5) & (ev.lu_cnt20 > 0),
        "前一天>5% 且 前20日无涨停": (ev.chg_tm1 > 5) & (ev.lu_cnt20 == 0),
        "前一天<=5% 且 前20日有涨停": (ev.chg_tm1 <= 5) & (ev.lu_cnt20 > 0),
        "前一天<=5% 且 前20日无涨停": (ev.chg_tm1 <= 5) & (ev.lu_cnt20 == 0),
    }
    rows = []
    for name, m in cross.items():
        sub = ev[m]
        rows.append({"画像": name, "n": len(sub),
                     "D+1收盘均%": round(float(sub.d1_close.mean()) * 100, 2),
                     "真差票率%": round(float(sub.bad.mean()) * 100, 1),
                     "限跌率%": round(float(sub.bad5.mean()) * 100, 1),
                     "好票率%": round(float(sub.good.mean()) * 100, 1)})
    out["交叉_前日大涨×回锅肉"] = rows

    # 好票(用户口径)画像汇总
    G = ev[ev.good]
    B = ev[ev.bad]
    out["好票画像"] = {"n": len(G),
                     "量比<1.5占比": round(float((G.vol_ratio < 1.5).mean()), 3),
                     "前20日0涨停占比": round(float((G.lu_cnt20 == 0).mean()), 3),
                     "前一天阴线占比": round(float((G.chg_tm1 < 0).mean()), 3),
                     "市值中位": round(float(G.cap_yi.median()), 0),
                     "价位中位": round(float(G.close_tm1.median()), 2)}
    out["真差票画像"] = {"n": len(B),
                       "量比<1.5占比": round(float((B.vol_ratio < 1.5).mean()), 3),
                       "前20日0涨停占比": round(float((B.lu_cnt20 == 0).mean()), 3),
                       "前一天阴线占比": round(float((B.chg_tm1 < 0).mean()), 3),
                       "前一天>5%占比": round(float((B.chg_tm1 > 5).mean()), 3),
                       "前20日有涨停占比": round(float((B.lu_cnt20 > 0).mean()), 3),
                       "市值中位": round(float(B.cap_yi.median()), 0),
                       "价位中位": round(float(B.close_tm1.median()), 2)}

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
