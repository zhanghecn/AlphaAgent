"""v5 池终验三合一:
V1 逐月选中率对比: 裸触发 / 潜龙v4池 / v5稳月池 / v5同花顺版
   每月: 笔数、≥2板率、≥3板率、≥4板率、妖股率(>=5板) —— 看是否好转
V2 金安国际 2026-06-08 首板个案: 全维度画像 + 底盘归类
V3 市值×价放宽网格(底盘规则固定: 多头<=12天+非回锅贴脸+量比<1.5, 高开<8%):
   市值 {50,80,120,200,不限} × 价 {8,12,20,不限}
   每格: 训/验/全 均收+正月占比+月笔+>=3板率+捕获率 —— 底盘好能否放大市值价
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
    name_map = main.set_index("vt_symbol")["name"].to_dict()

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
    bars["lu_cnt20"] = g["lu_T"].shift(1).groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).sum())
    bars["dist_ma20"] = bars["close_price"] / bars["ma20"] - 1
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["low_p1"] = g["low_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "trend_days", "days_since_lu", "since_lu_dd",
                "lu_cnt12", "lu_cnt20", "dist_ma20", "turnover_rate", "chg", "ma20",
                "low_price"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["name"] = bars.vt_symbol.map(name_map)
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
    ev["is_train"] = ev.trade_date < TRAIN_END

    R1 = (ev.trend_days_tm1 <= 12).fillna(True)
    R2 = ~((ev.days_since_lu_tm1 >= 2) & (ev.days_since_lu_tm1 <= 12)
           & (ev.since_lu_dd_tm1 > -0.05)).fillna(False)
    V = ev.vol_ratio < 1.5
    S = ev.cap_yi < 50
    P = ev.close_price_tm1 < 8
    THS = (ev.lu_cnt12_tm1 == 0) & (ev.dist_ma20_tm1 <= 0.12)
    QL = ((ev.chg_tm1.between(0, 5)) & (ev.low_price_tm1 > ev.ma20_tm1)
          & (ev.dist_ma20_tm1 <= 0.12) & (ev.turnover_rate_tm1 < 8)
          & (ev.cap_yi < 1200) & (ev.close_price_tm1 < 12))

    # ── V1 逐月选中率对比(近 10 个月) ─────────────────────────────
    groups = {"裸触发": pd.Series(True, index=ev.index), "潜龙v4": QL.fillna(False),
              "v5稳月池": (S & P & V & R1 & R2).fillna(False),
              "v5同花顺版": (S & P & V & THS).fillna(False)}
    rows = []
    for mth in sorted(ev.month.unique()):
        if mth < "2025-10":
            continue
        sub_all = ev[ev.month == mth]
        row = {"month": mth}
        for gname, gm in groups.items():
            sub = sub_all[gm[sub_all.index]]
            if len(sub) < 5:
                row[gname] = f"n={len(sub)}"
                continue
            row[gname] = (f"n={len(sub)} ≥2板{(sub.streak_h.fillna(0)>=2).mean()*100:.0f}% "
                          f"≥3板{(sub.streak_h.fillna(0)>=3).mean()*100:.0f}% "
                          f"妖{(sub.streak_h.fillna(0)>=5).mean()*100:.1f}%")
        rows.append(row)
    out = {"V1_逐月选中率": rows}

    # ── V2 金安国际个案 ────────────────────────────────────────────
    lucnt_map = lu_m.set_index(["vt_symbol", "trade_date"])["limit_up_count"].to_dict()
    ja = stocks[stocks["name"].str.contains("金安", na=False)]
    if len(ja):
        jsym = ja.iloc[0]["vt_symbol"]
        jb = bars[(bars.vt_symbol == jsym)
                  & (bars.trade_date >= "2026-05-15") & (bars.trade_date <= "2026-06-20")].copy()
        first_day = jb[jb["streak_h"].notna()]
        detail = []
        for _, r in jb.iterrows():
            detail.append({
                "date": r.trade_date.strftime("%m-%d"), "close": round(float(r.close_price), 2),
                "chg%": round(float(r.chg), 1) if np.isfinite(r.chg) else None,
                "涨停": bool(r.lu_T),
                "板数": int(lucnt_map.get((jsym, r.trade_date), 0)) if r.lu_T else 0,
                "多头天数": int(r.trend_days) if np.isfinite(r.trend_days) else 0,
                "量比": round(float(r.vol_ratio), 2) if np.isfinite(r.vol_ratio) else None,
                "乖离%": round(float(r.dist_ma20) * 100, 1) if np.isfinite(r.dist_ma20) else None,
                "streak_h": int(r.streak_h) if np.isfinite(r.streak_h) else None,
                "前12日涨停": int(r.lu_cnt12) if np.isfinite(r.lu_cnt12) else 0,
                "前20日涨停": int(r.lu_cnt20) if np.isfinite(r.lu_cnt20) else 0,
            })
        cap = cap_map.get(jsym)
        # 首板日的完整画像
        fd = first_day.iloc[0] if len(first_day) else None
        profile = None
        if fd is not None:
            profile = {
                "首板日": fd.trade_date.strftime("%Y-%m-%d"),
                "最终板数": int(fd.streak_h),
                "市值亿": round(float(cap), 0) if cap else None,
                "首板前收盘": round(float(fd.close_price_tm1), 2),
                "首板前一日涨跌%": round(float(fd.chg_tm1), 1) if np.isfinite(fd.chg_tm1) else None,
                "多头排列天数(T-1)": int(fd.trend_days_tm1) if np.isfinite(fd.trend_days_tm1) else None,
                "前12日涨停": int(fd.lu_cnt12_tm1) if np.isfinite(fd.lu_cnt12_tm1) else 0,
                "前20日涨停": int(fd.lu_cnt20_tm1) if np.isfinite(fd.lu_cnt20_tm1) else 0,
                "距上次涨停天数": int(fd.days_since_lu_tm1) if np.isfinite(fd.days_since_lu_tm1) else None,
                "上次涨停后最深回撤%": round(float(fd.since_lu_dd_tm1) * 100, 1)
                if np.isfinite(fd.since_lu_dd_tm1) else None,
                "首板量比": round(float(fd.vol_ratio), 2) if np.isfinite(fd.vol_ratio) else None,
                "高开%": round(float(fd.gap_open) * 100, 1),
                "20日乖离%": round(float(fd.dist_ma20_tm1) * 100, 1) if np.isfinite(fd.dist_ma20_tm1) else None,
                "D+1开盘%": round(float(fd.open_p1 / fd.close_price - 1) * 100, 1),
                "D+1收盘%": round(float(fd.close_p1 / fd.close_price - 1) * 100, 1),
                "D+1盘中最低%": round(float(fd.low_p1 / fd.close_price - 1) * 100, 1),
            }
            # 底盘归类
            tags = []
            if profile["前12日涨停"] == 0 and (profile["多头排列天数(T-1)"] or 0) <= 10:
                tags.append("全新急建仓型")
            if profile["前20日涨停"] and profile["前20日涨停"] > 0 and \
               (profile["上次涨停后最深回撤%"] or 0) <= -8:
                tags.append("深洗后再起型")
            if (profile["多头排列天数(T-1)"] or 0) > 12:
                tags.append("建仓过久(出货嫌疑)")
            if profile["距上次涨停天数"] and 2 <= profile["距上次涨停天数"] <= 12 and \
               (profile["上次涨停后最深回撤%"] or -1) > -5:
                tags.append("回锅贴脸(出货嫌疑)")
            profile["底盘归类"] = tags or ["中间地带"]
        out["V2_金安国际"] = {"vt_symbol": jsym, "名称": ja.iloc[0]["name"],
                              "画像": profile, "逐日": detail}

    # ── V3 市值×价放宽网格(底盘规则+量比固定) ──────────────────────
    winners = ev[ev.streak_h.fillna(0) >= 3]
    wkeys = set(zip(winners.vt_symbol, winners.trade_date))
    grid = []
    for cap in (50, 80, 120, 200, 10**9):
        for price in (8, 12, 20, 10**9):
            m = R1 & R2 & V & (ev.cap_yi < cap) & (ev.close_price_tm1 < price)
            sub = ev[m.fillna(False)]
            if len(sub) < 100:
                continue
            tr = sub[sub.is_train]
            va = sub[~sub.is_train]
            mm = sub.groupby("month")["ret"].mean()
            caught = sum(1 for kk_ in wkeys if kk_ in set(zip(sub.vt_symbol, sub.trade_date)))
            grid.append({
                "市值<": "不限" if cap > 1e8 else cap, "价<": "不限" if price > 1e8 else price,
                "全n": len(sub), "月笔": round(len(sub) / max(sub.month.nunique(), 1), 0),
                "全均": round(float(sub.ret.mean()) * 100, 2),
                "训均": round(float(tr.ret.mean()) * 100, 2),
                "验均": round(float(va.ret.mean()) * 100, 2) if len(va) > 30 else None,
                "验胜率": round(float((va.ret > 0).mean()), 3) if len(va) > 30 else None,
                "正月占比": round(float((mm > 0).mean()), 3),
                ">=3板率%": round(float((sub.streak_h.fillna(0) >= 3).mean()) * 100, 2),
                "妖股率%": round(float((sub.streak_h.fillna(0) >= 5).mean()) * 100, 2),
                "捕获率": round(caught / max(len(wkeys), 1), 3)})
    out["V3_市值价放宽网格"] = grid

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
