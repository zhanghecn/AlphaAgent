"""底盘死规则定稿验证: 修正"回锅肉"定义 + 可交易口径(触+8%)全量经济 + 同花顺条件.

修正出货B: 距上次涨停 2~12 日 且 期间最深回撤 > -5%(没洗干净) —— 贴脸/新高回锅.
死规则候选(全部 T-1 可知):
  R1 多头排列持续 > 12 天 不做
  R2 回锅贴脸(2<=days_since_lu<=12 且 since_lu_dd > -5%) 不做
在触发宇宙(触+8%, 非一字, 高开<8%)上, 与稳月池v1(市值50+价8+量比1.5)组合:
  P0 稳月池v1(参照)
  P1 = v1 + R1
  P2 = v1 + R2
  P3 = v1 + R1 + R2
  P4 = R1+R2+量比1.5(无市值无价 —— 看新规则能否替代市值价)
  P5 = R1+R2 only
  P6 = v1 + R1 + R2 + 小阳优先标记(附加读数: 小阳子集 vs 非小阳子集)
每项: 训/验/全 均收/胜率/正月占比/月笔/>=3板率/捕获率/负月明细.
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
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["chg"] = bars["change_pct"].fillna(derived)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
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
    bars["lu_cnt12"] = g["lu_T"].shift(1).groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(12, min_periods=1).sum())
    bars["dist_ma20"] = bars["close_price"] / bars["ma20"] - 1
    bars["yang"] = bars.close_price > bars.open_price
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "trend_days", "days_since_lu", "since_lu_dd", "yang10",
                "lu_cnt12", "dist_ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
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
    ev["entry"] = ev["trigger_price"] * (1 + SLIP)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)].dropna(subset=["ret"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["good3"] = k.loc[ev.index] >= 3
    ev["is_train"] = ev.trade_date < TRAIN_END

    R1 = ev.trend_days_tm1 <= 12                       # 多头排列<=12天(>12不做)
    R2 = ~((ev.days_since_lu_tm1 >= 2) & (ev.days_since_lu_tm1 <= 12)
           & (ev.since_lu_dd_tm1 > -0.05))             # 回锅贴脸不做(保留: 从未涨停/早期涨停/深洗过)
    V = ev.vol_ratio < 1.5
    S = ev.cap_yi < 50
    P = ev.close_price_tm1 < 8
    xy = (ev.yang10_tm1 >= 7)                          # 小阳标记(附加读数)

    winners = ev[ev.good3]
    wkeys = set(zip(winners.vt_symbol, winners.trade_date))

    def evaluate(mask, label):
        sub = ev[mask]
        if len(sub) < 30:
            return {"label": label, "n": len(sub)}
        caught = sum(1 for kk_ in wkeys if kk_ in set(zip(sub.vt_symbol, sub.trade_date)))
        rec = {"label": label,
               "训": month_stats(sub[sub.is_train]), "验": month_stats(sub[~sub.is_train]),
               "全": month_stats(sub),
               ">=3板率%": round(float(sub.good3.mean()) * 100, 2),
               "捕获率": round(caught / max(len(wkeys), 1), 3)}
        m = sub.groupby("month")["ret"].agg(["count", "mean"])
        rec["负月明细"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                          for ix, rr in m.iterrows() if rr["mean"] <= 0}
        return rec

    out = {
        "P0_稳月池v1(市值+价+量比)": evaluate(S & P & V, "P0"),
        "P1_v1+R1多头<=12": evaluate(S & P & V & R1, "P1"),
        "P2_v1+R2无回锅": evaluate(S & P & V & R2, "P2"),
        "P3_v1+R1+R2": evaluate(S & P & V & R1 & R2, "P3"),
        "P4_R1+R2+量比(无市值价)": evaluate(R1 & R2 & V, "P4"),
        "P5_R1+R2裸": evaluate(R1 & R2, "P5"),
    }
    # 同花顺可表达变体: R1→20日乖离<12%, R2→近12日涨停次数=0(更严, 洗掉深回好票)
    THS = (ev.lu_cnt12_tm1 == 0) & (ev.dist_ma20_tm1 <= 0.12)
    out["P3THS_同花顺版(含量比)"] = evaluate(S & P & V & THS.fillna(False), "P3THS含量比")
    out["P3THS_纯盘前(无量比)"] = evaluate(S & P & THS.fillna(False), "P3THS纯盘前")
    # 小阳附加读数: 在 P3 池内
    sub3 = ev[S & P & V & R1 & R2]
    out["P3内_小阳子集"] = evaluate((S & P & V & R1 & R2) & xy.fillna(False), "小阳")
    out["P3内_非小阳"] = evaluate((S & P & V & R1 & R2) & ~xy.fillna(False), "非小阳")

    # R2 单独读数(回锅贴脸的毒性, 全宇宙)
    tielian = ((ev.days_since_lu_tm1 >= 2) & (ev.days_since_lu_tm1 <= 12)
               & (ev.since_lu_dd_tm1 > -0.05))
    out["R2_回锅贴脸_单独"] = evaluate(tielian.fillna(False), "回锅贴脸")
    out["R1_多头>12天_单独"] = evaluate((ev.trend_days_tm1 > 12).fillna(False), "多头>12天")

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
