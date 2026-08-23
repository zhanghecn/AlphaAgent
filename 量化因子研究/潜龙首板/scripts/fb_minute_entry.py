"""首板分钟级进场规则验证(1m: 2026-06~08; 5m: 2026-04~05 样本外).

步骤:
1. 日线层算候选事件集合:
   S0 基线: T-1未涨停 + 当日high>=昨收*1.08
   S1 +底座+不过热
   S2 +盘面<6% (全组合)
2. 仅对候选(symbol,date)拉分钟线, 扫描窗口内首次到+8%:
   - 触发bar: high >= trigger; 质量: 该bar close >= trigger (收住)
   - 量能变体: V0无 / V1 触发bar量>=2x 当日此前均量 / V2 >=2.5x 前5日同分钟均量
   - 进场: 下一bar open
3. 结果: 封板率/炸板率/D0close/D+1open/D+1/D+3, 按月份与窗口分层.
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
DAILY_START = "2025-10-01"      # 留均线/前5日 lookback
MIN_1M_RANGE = ("2026-06-01", "2026-08-12")
MIN_5M_RANGE = ("2026-04-01", "2026-05-31")


def load_daily():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= %s""", conn, params=(DAILY_START,))
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word, touched_limit
               FROM stock_limit_up_daily WHERE trade_date >= %s""", conn, params=(MIN_5M_RANGE[0],))
    return stocks, bars, lu


def build_events(stocks, bars, lu):
    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])

    g = bars.groupby("vt_symbol", sort=False)
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["vol_ma5"] = g["volume"].transform(lambda s: s.rolling(5).mean())
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p3"] = g["close_price"].shift(-3)

    breadth = bars.groupby("trade_date")["change_pct"].agg(up5=lambda s: (s >= 5).sum(), total="count")
    breadth["ratio"] = breadth.up5 / breadth.total
    breadth_prev = breadth["ratio"].sort_index().shift(1)

    for col in ["close_price", "open_price", "change_pct", "turnover_rate", "ma10", "ma20", "ret5", "vol_ma5"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars["breadth_tm1"] = bars["trade_date"].map(breadth_prev)

    lu_flag = lu_key["is_limit_up"]
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_flag).fillna(False).astype(bool).values
    bars["touched_T"] = idx.map(lu_key["touched_limit"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_flag).fillna(False).astype(bool).values

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["daily_touched8"] = bars["high_price"] >= bars["trigger_price"] - 1e-9

    # streak 高度(首板后连续涨停段最高板数, 供收益分解)
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    dist = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    c_base = ((~bars["lu_tm1"]) & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
              & (bars["close_price_tm1"] > bars["ma20_tm1"]) & (bars["ma10_tm1"] > bars["ma20_tm1"]))
    c_cool = ((dist >= 0) & (dist <= 0.12) & (bars["ret5_tm1"] >= 0) & (bars["ret5_tm1"] <= 0.15)
              & (bars["turnover_rate_tm1"] < 8))
    c_b6 = bars["breadth_tm1"] < 0.06

    bars["set_S0"] = (~bars["lu_tm1"]) & bars["daily_touched8"]
    bars["set_S1"] = c_base & c_cool & bars["daily_touched8"]
    bars["set_S2"] = c_base & c_cool & c_b6 & bars["daily_touched8"]
    return bars


def scan_minutes(events: pd.DataFrame, interval: str, date_lo: str, date_hi: str,
                 windows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """对候选(symbol,date)逐日扫描分钟线. 按月分块控内存.
    量参考: vol_ma5_daily/240 近似同分钟均量(免拉历史分钟)."""
    pairs = events[["vt_symbol", "trade_date"]].drop_duplicates().copy()
    pairs["month"] = pairs["trade_date"].dt.to_period("M")
    print(f"[{interval}] 候选对 {len(pairs):,} 涉及股票 {pairs.vt_symbol.nunique()}", file=sys.stderr)

    ev_idx = events.set_index(["vt_symbol", "trade_date"])
    rows = []
    with psycopg.connect(DSN) as conn:
        for mon, sub in pairs.groupby("month"):
            # VALUES join 精确拉候选对, 避免笛卡尔过取
            vals = ",".join(
                f"('{s}','{d.date()}')" for s, d in sub[["vt_symbol", "trade_date"]].itertuples(index=False))
            mb = pd.read_sql(
                f"""SELECT m.vt_symbol, m.trade_date, m.bar_time, m.open_price, m.close_price,
                           m.high_price, m.low_price, m.volume
                    FROM stock_minute_bars m
                    JOIN (VALUES {vals}) AS v(s, d)
                      ON m.vt_symbol = v.s AND m.trade_date = v.d::date
                    WHERE m.interval = %s""",
                conn, params=(interval,))
            if mb.empty:
                print(f"[{interval}] {mon}: 无分钟数据({len(sub)}对)", file=sys.stderr)
                continue
            mb["bar_time"] = pd.to_datetime(mb["bar_time"])
            mb["trade_date"] = pd.to_datetime(mb["trade_date"])
            mb["tt"] = mb["bar_time"].dt.strftime("%H:%M")
            print(f"[{interval}] {mon}: 覆盖 {mb.groupby(['vt_symbol','trade_date']).ngroups}/{len(sub)} 对, {len(mb):,}行", file=sys.stderr)
            # 单位抽查: 分钟量日合计 / 日成交量 中位比(≈1 同单位; ≈100 分钟=股日线=手)
            try:
                dv = events.set_index(["vt_symbol", "trade_date"])["volume"]
                smp = mb.groupby(["vt_symbol", "trade_date"])["volume"].sum().head(2000)
                ratio = (smp / dv.reindex(smp.index)).median()
                print(f"[{interval}] {mon}: 分钟/日量单位比中位数 = {ratio:.3f}", file=sys.stderr)
            except Exception as e:
                print(f"units check skip: {e}", file=sys.stderr)

            for (sym, d), day in mb.groupby(["vt_symbol", "trade_date"], sort=True):
                key = (sym, d)
                if key not in ev_idx.index:
                    continue
                ev = ev_idx.loc[key]
                trig = ev["trigger_price"]
                if not np.isfinite(trig) or trig <= 0:
                    continue
                day = day.sort_values("bar_time").reset_index(drop=True)
                day["hit"] = day["high_price"] >= trig - 1e-9
                any_hit_idx = day.index[day["hit"]]
                if len(any_hit_idx) == 0:
                    continue
                day_first_hit = int(any_hit_idx[0])
                # 单位: 分钟量=股, 日线量=手(实测比值100) → vol_ma5*100 换算为股
                bars_per_day = 48 if interval == "5m" else 240
                vol_ref = (ev["vol_ma5_tm1"] * 100.0 / 240.0) if np.isfinite(ev.get("vol_ma5_tm1", np.nan)) else np.nan
                for wname, wlo, whi in windows:
                    in_win = day[(day["tt"] >= wlo) & (day["tt"] <= whi)]
                    win_hit = in_win.index[in_win["hit"]]
                    if len(win_hit) == 0:
                        continue
                    first_hit = int(win_hit[0])
                    fh_time = day.loc[first_hit, "tt"]
                    bar = day.loc[first_hit]
                    hold = bar["close_price"] >= trig - 1e-9
                    prior = day.loc[:first_hit - 1]
                    v_intra = (bar["volume"] >= 2.0 * prior["volume"].mean()) if len(prior) >= 3 else np.nan
                    v_ref5 = (bar["volume"] >= 2.5 * vol_ref * (5 if interval == "5m" else 1)) if np.isfinite(vol_ref) and vol_ref > 0 else np.nan
                    # 触发bar自身形态(进场前可知):
                    shadow = float(bar["high_price"] / max(bar["close_price"], 1e-9) - 1)  # 上影(相对收盘)
                    # 量能持续(确认型, 进场需延后): 后续3bar均量/触发bar量
                    nxt3 = day.loc[first_hit + 1:first_hit + 3]
                    sustain_vol = float(nxt3["volume"].mean() / bar["volume"]) if len(nxt3) == 3 and bar["volume"] > 0 else np.nan
                    # 价格持续: 触发后3根(含触发)收盘均>=trig —— 确认型
                    conf3 = day.loc[first_hit:first_hit + 2]
                    price_sustain3 = bool((conf3["close_price"] >= trig - 1e-9).all()) if len(conf3) == 3 else False
                    if first_hit + 1 >= len(day):
                        continue
                    nxt = day.loc[first_hit + 1]
                    entry = float(nxt["open_price"])
                    # 确认型进场: 第3根bar收盘(若价格持续成立)
                    entry_conf = float(day.loc[first_hit + 2, "close_price"]) if first_hit + 2 < len(day) else np.nan
                    after = day.loc[first_hit + 1:]
                    rows.append({
                        "vt_symbol": sym, "trade_date": d, "window": wname,
                        "hit_time": fh_time,
                        "pre_hit": day_first_hit < first_hit,
                        "gap_open": float(day.loc[0, "open_price"] / ev["close_price_tm1"] - 1),
                        "hold8": bool(hold),
                        "v_intra2x": v_intra, "v_ref5_2p5x": v_ref5,
                        "shadow": shadow,
                        "sustain_vol": sustain_vol,
                        "price_sustain3": price_sustain3,
                        "entry": entry,
                        "entry_conf": entry_conf,
                        "sealed": bool(ev["lu_T"]),
                        "touched_limit": bool(ev["touched_T"]),
                        "ret_d0_close": float(ev["close_price"] / entry - 1),
                        "ret_d1_open": float(ev["open_p1"] / entry - 1) if np.isfinite(ev["open_p1"]) else np.nan,
                        "ret_d1": float(ev["close_p1"] / entry - 1) if np.isfinite(ev["close_p1"]) else np.nan,
                        "ret_d3": float(ev["close_p3"] / entry - 1) if np.isfinite(ev["close_p3"]) else np.nan,
                        "retc_d1": float(ev["close_p1"] / entry_conf - 1) if np.isfinite(entry_conf) and np.isfinite(ev["close_p1"]) else np.nan,
                        "retc_d3": float(ev["close_p3"] / entry_conf - 1) if np.isfinite(entry_conf) and np.isfinite(ev["close_p3"]) else np.nan,
                        "mfe": float(after["high_price"].max() / entry - 1) if len(after) else np.nan,
                        "mae": float(after["low_price"].min() / entry - 1) if len(after) else np.nan,
                        "streak_h": float(ev["streak_h"]) if np.isfinite(ev.get("streak_h", np.nan)) else np.nan,
                        "set_S1": bool(ev["set_S1"]), "set_S2": bool(ev["set_S2"]),
                    })
            del mb
    return pd.DataFrame(rows)


def agg(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n < 3:
        return {"label": label, "n": n}
    return {
        "label": label, "n": n,
        "seal": round(df["sealed"].mean(), 4),
        "zha": round(((~df["sealed"]) & df["touched_limit"]).mean(), 4),
        "d0c": round(df["ret_d0_close"].mean() * 100, 2),
        "d1o": round(df["ret_d1_open"].mean() * 100, 2),
        "d1": round(df["ret_d1"].mean() * 100, 2),
        "d1w": round((df["ret_d1"] > 0).mean(), 4),
        "d3": round(df["ret_d3"].mean() * 100, 2),
        "mfe": round(df["mfe"].mean() * 100, 2),
        "mae": round(df["mae"].mean() * 100, 2),
    }


def main():
    stocks, bars, lu = load_daily()
    bars = build_events(stocks, bars, lu)

    windows_1m = [("0931-0945", "09:31", "09:45"), ("0946-1000", "09:46", "10:00"),
                  ("1001-1030", "10:01", "10:30"), ("1031-1130", "10:31", "11:30"),
                  ("0931-1130", "09:31", "11:30"),
                  ("1300-1400", "13:00", "14:00"), ("1400-1457", "14:00", "14:57")]
    windows_5m = [("0935-0945", "09:35", "09:45"), ("0950-1030", "09:50", "10:30"),
                  ("1030-1455", "10:30", "14:55")]

    out = {}
    for tag, interval, (lo, hi), windows in [
            ("1m", "1m", MIN_1M_RANGE, windows_1m),
            ("5m", "5m", MIN_5M_RANGE, windows_5m)]:
        ev_range = bars[(bars.trade_date >= lo) & (bars.trade_date <= hi) & bars["set_S0"]]
        res = scan_minutes(ev_range, interval, lo, hi, windows)
        if res.empty:
            continue
        res["month"] = res["trade_date"].dt.to_period("M").astype(str)
        block = {}
        for wname in res["window"].unique():
            w = res[res.window == wname]
            conf = w[w.hold8 & w.set_S2 & w.price_sustain3].copy()
            if len(conf):  # 确认型进场: 用第3根收盘价进场后的收益替换
                conf["ret_d1"] = conf["retc_d1"]
                conf["ret_d3"] = conf["retc_d3"]
            variants = [
                ("S0无过滤", w),
                ("S0+收住", w[w.hold8]),
                ("S1+收住", w[w.hold8 & w.set_S1]),
                ("S2+收住", w[w.hold8 & w.set_S2]),
                ("S2+收住+短上影<=1.5%", w[w.hold8 & w.set_S2 & (w.shadow <= 0.015)]),
                ("S2+收住+同分钟量2.5x", w[w.hold8 & w.set_S2 & (w.v_ref5_2p5x == True)]),
                ("S2+确认3分钟(延后进场)", conf),
            ]
            block[wname] = [agg(v, lb) for lb, v in variants]
        # 按月(主窗口)
        main_w = res[res.window == windows[0][0]]
        block["_by_month_S2_full"] = [
            agg(gp, m) for m, gp in main_w[main_w.hold8 & main_w.set_S2].groupby("month")]
        block["_by_month_S1_full"] = [
            agg(gp, m) for m, gp in main_w[main_w.hold8 & main_w.set_S1].groupby("month")]
        # 高开影响
        w0 = main_w[main_w.hold8 & main_w.set_S2]
        block["_gap_split_S2"] = [
            agg(w0[w0.gap_open < 0.03], "低开/平开(<+3%)"),
            agg(w0[(w0.gap_open >= 0.03) & (w0.gap_open < 0.06)], "中开(+3~6%)"),
            agg(w0[w0.gap_open >= 0.06], "高开(>=+6%)"),
        ]
        # 收益分解(所有窗口合并, S2+收住): 钱从哪来
        allw = res[res.hold8 & res.set_S2]
        block["_streak_decomp_S2_allwindows"] = [
            agg(allw[~allw.sealed], "未封板"),
            agg(allw[allw.streak_h == 1], "封板但止步1板"),
            agg(allw[allw.streak_h == 2], "2板"),
            agg(allw[allw.streak_h >= 3], "3板+"),
        ]
        out[tag] = block
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
