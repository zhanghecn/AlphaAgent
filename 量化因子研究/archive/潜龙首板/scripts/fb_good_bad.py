"""好票/差票明细 + 候选新因子检验.

复用 fb_minute_entry 的日线层; 扫描分钟线输出逐笔明细:
  结果分类: BAD=未封板 / MID=封板止步1板 / GOOD=晋级2板+
  候选新因子: lu_cnt20(前20日涨停次数,股性) / ret60(中期位置) / near_high250(距250日新高<=3%)
             ind_lu_tm1(昨日同行业涨停数,板块联动) / hit_time(触发时间) / gap_open
             limit_touch_time(触板时间,结果描述) / open_cnt(触板后开板次数,结果描述)
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/tmp/fb")
from fb_minute_entry import DSN, load_daily, build_events, MIN_1M_RANGE, MIN_5M_RANGE  # noqa: E402


def enrich(bars: pd.DataFrame, stocks: pd.DataFrame, lu: pd.DataFrame) -> pd.DataFrame:
    g = bars.groupby("vt_symbol", sort=False)
    bars["ret60_tm1"] = g["close_price"].transform(lambda s: (s / s.shift(60) - 1).shift(1))
    bars["high250_tm1"] = g["high_price"].transform(lambda s: s.rolling(250, min_periods=60).max().shift(1))
    bars["near_high250"] = bars["close_price_tm1"] >= bars["high250_tm1"] * 0.97
    bars["lu_cnt20"] = g["lu_T"].transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    # 弱转强: 前2~10日 limit_up_count>=2
    lu2 = lu[lu.limit_up_count >= 2][["vt_symbol", "trade_date"]].copy()
    lu2["trade_date"] = pd.to_datetime(lu2["trade_date"])
    tmp = bars[["vt_symbol", "trade_date"]].copy()
    tmp["trade_date"] = pd.to_datetime(tmp["trade_date"])
    tmp = tmp.merge(lu2, on="vt_symbol", how="left", suffixes=("", "_lu"))
    ycol = "trade_date_lu" if "trade_date_lu" in tmp.columns else "trade_date_y"
    xcol = "trade_date" if "trade_date" in tmp.columns else "trade_date_x"
    delta = (pd.to_datetime(tmp[xcol]) - pd.to_datetime(tmp[ycol])).dt.days
    w2s = tmp[(delta >= 2) & (delta <= 10)][["vt_symbol", xcol]].drop_duplicates()
    w2s.columns = ["vt_symbol", "trade_date"]
    w2s["weak2strong"] = True
    bars = bars.merge(w2s, on=["vt_symbol", "trade_date"], how="left")
    bars["weak2strong"] = bars["weak2strong"].fillna(False)
    # 同行业昨日涨停数(industry 单独补查)
    with psycopg.connect(DSN) as conn:
        ind_df = pd.read_sql("SELECT vt_symbol, industry FROM stocks", conn)
    ind_map = ind_df.set_index("vt_symbol")["industry"].fillna("").to_dict()
    bars["industry"] = bars.vt_symbol.map(ind_map).fillna("")
    lu_ind = lu[lu.is_limit_up].copy()
    lu_ind["industry"] = lu_ind.vt_symbol.map(ind_map).fillna("")
    ind_cnt = lu_ind.groupby(["industry", "trade_date"]).size().rename("ind_lu")
    tm1_date = g["trade_date"].shift(1)
    bars["ind_lu_tm1"] = pd.MultiIndex.from_arrays([bars["industry"], tm1_date]).map(ind_cnt).fillna(0).astype(int).values
    bars.loc[bars["industry"] == "", "ind_lu_tm1"] = 0
    # 昨日市场最高板/炸板数
    lu["is_zha"] = (~lu.is_limit_up) & lu.touched_limit
    day = lu.groupby("trade_date").agg(max_h=("limit_up_count", "max"),
                                       zha_n=("is_zha", "sum")).sort_index()
    bars["max_h_tm1"] = bars["trade_date"].map(day["max_h"].shift(1))
    bars["zha_tm1"] = bars["trade_date"].map(day["zha_n"].shift(1))
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    return bars


def scan(events: pd.DataFrame, interval: str, lo: str, hi: str) -> pd.DataFrame:
    pairs = events[["vt_symbol", "trade_date"]].drop_duplicates().copy()
    pairs["month"] = pairs["trade_date"].dt.to_period("M")
    ev_idx = events.set_index(["vt_symbol", "trade_date"])
    rows = []
    with psycopg.connect(DSN) as conn:
        for mon, sub in pairs.groupby("month"):
            vals = ",".join(f"('{s}','{d.date()}')" for s, d in
                            sub[["vt_symbol", "trade_date"]].itertuples(index=False))
            mb = pd.read_sql(
                f"""SELECT m.vt_symbol, m.trade_date, m.bar_time, m.open_price, m.close_price,
                           m.high_price, m.low_price, m.volume
                    FROM stock_minute_bars m
                    JOIN (VALUES {vals}) AS v(s, d)
                      ON m.vt_symbol = v.s AND m.trade_date = v.d::date
                    WHERE m.interval = %s""", conn, params=(interval,))
            if mb.empty:
                continue
            mb["bar_time"] = pd.to_datetime(mb["bar_time"])
            mb["trade_date"] = pd.to_datetime(mb["trade_date"])
            mb["tt"] = mb["bar_time"].dt.strftime("%H:%M")
            print(f"[{interval}] {mon}: {mb.groupby(['vt_symbol','trade_date']).ngroups}/{len(sub)} 对", file=sys.stderr)
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
                hit_idx = day.index[day["hit"]]
                if len(hit_idx) == 0:
                    continue
                fh = int(hit_idx[0])  # 全日首次触发(不再分窗口)
                bar = day.loc[fh]
                if bar["close_price"] < trig - 1e-9:
                    continue  # 未收住, 放弃
                if fh + 1 >= len(day):
                    continue
                entry = float(day.loc[fh + 1, "open_price"])
                # 触板(涨停价)描述字段
                limit_px = round(ev["close_price_tm1"] * 1.1 + 1e-9, 2)
                lt = day.index[day["high_price"] >= limit_px - 1e-6]
                lt_time = day.loc[int(lt[0]), "tt"] if len(lt) else None
                open_cnt = None
                if len(lt):
                    after_touch = day.loc[int(lt[0]):]
                    open_cnt = int((after_touch["low_price"] < limit_px - 1e-6).sum())
                rows.append({
                    "vt_symbol": sym, "trade_date": str(d.date()), "interval": interval,
                    "hit_time": bar["tt"],
                    "gap_open": round(float(day.loc[0, "open_price"] / ev["close_price_tm1"] - 1) * 100, 2),
                    "entry": entry,
                    "sealed": bool(ev["lu_T"]),
                    "streak_h": int(ev["streak_h"]) if np.isfinite(ev.get("streak_h", np.nan)) else 0,
                    "d0c": round(float(ev["close_price"] / entry - 1) * 100, 2),
                    "d1o": round(float(ev["open_p1"] / entry - 1) * 100, 2) if np.isfinite(ev["open_p1"]) else None,
                    "d1": round(float(ev["close_p1"] / entry - 1) * 100, 2) if np.isfinite(ev["close_p1"]) else None,
                    "d3": round(float(ev["close_p3"] / entry - 1) * 100, 2) if np.isfinite(ev["close_p3"]) else None,
                    "chg_tm1": round(float(ev["change_pct_tm1"]), 2),
                    "to_tm1": round(float(ev["turnover_rate_tm1"]), 2),
                    "dist_ma20": round(float(ev["dist_ma20"]) * 100, 2),
                    "ret5_tm1": round(float(ev["ret5_tm1"]) * 100, 2),
                    "ret60_tm1": round(float(ev["ret60_tm1"]) * 100, 2) if np.isfinite(ev["ret60_tm1"]) else None,
                    "lu_cnt20": int(ev["lu_cnt20"]),
                    "near_high250": bool(ev["near_high250"]),
                    "weak2strong": bool(ev["weak2strong"]),
                    "ind_lu_tm1": int(ev["ind_lu_tm1"]),
                    "breadth_tm1": round(float(ev["breadth_tm1"]) * 100, 2) if np.isfinite(ev["breadth_tm1"]) else None,
                    "max_h_tm1": int(ev["max_h_tm1"]) if np.isfinite(ev["max_h_tm1"]) else None,
                    "zha_tm1": int(ev["zha_tm1"]) if np.isfinite(ev["zha_tm1"]) else None,
                    "lt_time": lt_time, "open_cnt": open_cnt,
                })
            del mb
    return pd.DataFrame(rows)


def cls(r) -> str:
    if not r["sealed"]:
        return "BAD"
    return "GOOD" if r["streak_h"] >= 2 else "MID"


def main():
    stocks, bars, lu = load_daily()
    bars = build_events(stocks, bars, lu)
    bars = enrich(bars, stocks, lu)
    name_map = stocks.set_index("vt_symbol")["name"].to_dict()

    all_rows = []
    for interval, (lo, hi) in [("1m", MIN_1M_RANGE), ("5m", MIN_5M_RANGE)]:
        ev = bars[(bars.trade_date >= lo) & (bars.trade_date <= hi) & bars["set_S2"]]
        df = scan(ev, interval, lo, hi)
        all_rows.append(df)
    res = pd.concat(all_rows, ignore_index=True)
    res["name"] = res.vt_symbol.map(name_map)
    res["cls"] = res.apply(cls, axis=1)
    print(f"总明细: {len(res)} 笔 (GOOD={ (res.cls=='GOOD').sum() }, MID={ (res.cls=='MID').sum() }, BAD={ (res.cls=='BAD').sum() })", file=sys.stderr)

    # ===== 分组特征对比 =====
    feats = ["gap_open", "chg_tm1", "to_tm1", "dist_ma20", "ret5_tm1", "ret60_tm1",
             "lu_cnt20", "ind_lu_tm1", "breadth_tm1", "max_h_tm1", "zha_tm1"]
    cmp = res.groupby("cls")[feats].median().round(2).T
    print("\n== 中位数对比(BAD/MID/GOOD) ==", file=sys.stderr)
    print(cmp.to_string(), file=sys.stderr)
    for col in ["weak2strong", "near_high250"]:
        t = res.groupby("cls")[col].mean().round(3)
        print(f"{col}: {t.to_dict()}", file=sys.stderr)

    # 新因子 lift: P(GOOD) / P(BAD) 按分箱
    def lift(col, bins):
        f = res[res[col].notna()].copy()
        f["bin"] = pd.cut(f[col], bins)
        t = f.groupby("bin", observed=True)["cls"].agg(
            n="size", good=lambda s: (s == "GOOD").mean(), bad=lambda s: (s == "BAD").mean()).round(3)
        return [{"bin": str(i), "n": int(r.n), "P_good": r.good, "P_bad": r.bad} for i, r in t.iterrows()]

    res["hit_min"] = res["hit_time"].str.replace(":", "").astype(int)
    out = {
        "lift_lu_cnt20": lift("lu_cnt20", [-1, 0, 1, 2, 3, 20]),
        "lift_ret60": lift("ret60_tm1", [-100, 0, 10, 20, 35, 500]),
        "lift_near_high250": [(str(k), {"n": int(len(g_)), "P_good": round((g_.cls == 'GOOD').mean(), 3),
                                        "P_bad": round((g_.cls == 'BAD').mean(), 3)})
                              for k, g_ in res.groupby("near_high250")],
        "lift_ind_lu": lift("ind_lu_tm1", [-1, 0, 1, 3, 6, 100]),
        "lift_hit_time": lift("hit_min", [0, 935, 945, 1000, 1030, 1130, 1400, 1500]),
        "lift_gap": lift("gap_open", [-10, 0, 2, 4, 6, 8, 11]),
        "lift_max_h": lift("max_h_tm1", [0, 2, 3, 4, 5, 7, 30]),
    }
    # 触发早(<10:00)且触板时间也早的描述统计
    res["lt_early"] = res.lt_time.notna() & (res.lt_time <= "10:00")
    print("\n== 触板时间<=10:00 且最终封住的开板次数 ==", file=sys.stderr)
    t = res[(res.sealed)].groupby("cls")["open_cnt"].median()
    print(t.to_string(), file=sys.stderr)

    # ===== 明细表(1m 全部 + 5m 全部) =====
    res = res.sort_values(["cls", "trade_date"], ascending=[True, True])
    out["rows"] = res.to_dict("records")
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
