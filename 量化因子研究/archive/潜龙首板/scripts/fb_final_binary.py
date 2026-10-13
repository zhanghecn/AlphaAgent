"""终案三问:
Q1 阴线假设: 昨日 -5~0% 阴线 × 放量(相对换手>1.2)/缩量 vs 昨日 0~5% 阳线(基线池)
Q2 时段截止: 首次触发时间分箱的收益 + 上午vs午后 t检验(分钟era, 池内, 收住)
Q3 股价最终线: <12 定案复核
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg
from scipy import stats as sstats

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
    bars["to_ma5"] = g["turnover_rate"].transform(lambda s: s.rolling(5).mean())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20", "to_ma5"]:
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
    bars["to_rel"] = bars["turnover_rate_tm1"] / bars["to_ma5_tm1"]
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    base_other = ((~bars["lu_tm1"]) & (bars["low_price_tm1"] > bars["ma20_tm1"])
                  & (bars["dist_ma20"] <= 0.12) & (bars["turnover_rate_tm1"] < 8)
                  & (bars["cap_yi"] < 1200) & (bars["close_price_tm1"] < 20))

    def build(mask):
        ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & mask
                  & ~bars["oneword_strict"]].copy()
        if not len(ev):
            return ev
        k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
        eo = np.full(len(ev), np.nan)
        for kk in range(2, 7):
            eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
        eo = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, eo)
        ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
        ev["is_train"] = ev.trade_date < pd.Timestamp(TRAIN_END)
        disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
        for kk in range(2, 7):
            disc |= (ev[f"open_p{kk}"] / ev[f"close_p{kk-1}"] - 1).abs() > 0.11
        return ev[~disc.fillna(False)]

    def stat(df, label):
        r = df["ret"].dropna()
        if len(r) < 20:
            return {"label": label, "n": len(r)}
        tr, va = r[df.is_train], r[~df.is_train]
        return {"label": label, "n": len(r), "all": round(float(r.mean()) * 100, 2),
                "train": round(float(tr.mean()) * 100, 2), "valid": round(float(va.mean()) * 100, 2),
                "win": round(float((r > 0).mean()), 3), "seal": round(float(df.sealed.mean()), 3)}

    out = {}
    # Q1 阴线假设(股价<20版本池 + 阴线替换阳线)
    pos = build(base_other & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5))
    neg_vol_up = build(base_other & (bars["change_pct_tm1"] >= -5) & (bars["change_pct_tm1"] < 0)
                       & (bars["to_rel"] > 1.2))
    neg_vol_dn = build(base_other & (bars["change_pct_tm1"] >= -5) & (bars["change_pct_tm1"] < 0)
                       & (bars["to_rel"] <= 1.2))
    neg_big_vol = build(base_other & (bars["change_pct_tm1"] >= -5) & (bars["change_pct_tm1"] < -2)
                        & (bars["to_rel"] > 1.2))
    out["Q1"] = [stat(pos, "阳线0~5%(基线)"),
                 stat(neg_vol_up, "阴线-5~0%+放量(相对换手>1.2)"),
                 stat(neg_vol_dn, "阴线-5~0%+缩量"),
                 stat(neg_big_vol, "中阴-5~-2%+放量")]
    if len(pos) and len(neg_vol_up):
        t, p = sstats.ttest_ind(pos["ret"].dropna(), neg_vol_up["ret"].dropna(), equal_var=False)
        out["Q1_ttest_阳vs阴放量"] = {"t": round(float(t), 2), "p": round(float(p), 5)}

    # Q3 股价线(定案复核: <12 vs <20 二选一, 基线=阳线池)
    p12 = build(base_other & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
                & (bars["close_price_tm1"] < 12))
    out["Q3"] = [stat(pos, "股价<20"), stat(p12, "股价<12")]

    # Q2 时段(分钟era, 池内, 收住, 首次触发)
    pool_daily = (base_other & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
                  & (bars["close_price_tm1"] < 12))
    rows = []
    with psycopg.connect(DSN) as conn:
        for interval, lo, hi in [("1m", "2026-06-01", "2026-08-12"), ("5m", "2026-04-01", "2026-05-31")]:
            evd = bars[(bars.trade_date >= lo) & (bars.trade_date <= hi) & bars["triggered"]
                       & pool_daily & ~bars["oneword_strict"]]
            pairs = evd[["vt_symbol", "trade_date"]].drop_duplicates()
            by_month = pairs.groupby(pairs.trade_date.dt.to_period("M"))
            for mon, sub in by_month:
                vals = ",".join(f"('{s}','{d.date()}')" for s, d in
                                sub[["vt_symbol", "trade_date"]].itertuples(index=False))
                mb = pd.read_sql(
                    f"""SELECT m.vt_symbol, m.trade_date, m.bar_time, m.open_price, m.close_price,
                               m.high_price, m.low_price
                        FROM stock_minute_bars m JOIN (VALUES {vals}) AS v(s, d)
                          ON m.vt_symbol = v.s AND m.trade_date = v.d::date
                        WHERE m.interval = %s""", conn, params=(interval,))
                if mb.empty:
                    continue
                mb["bar_time"] = pd.to_datetime(mb["bar_time"])
                mb["trade_date"] = pd.to_datetime(mb["trade_date"])
                mb["tt"] = mb["bar_time"].dt.strftime("%H:%M")
                ev_idx = evd.set_index(["vt_symbol", "trade_date"])
                for (sym, d), day in mb.groupby(["vt_symbol", "trade_date"]):
                    key = (sym, d)
                    if key not in ev_idx.index:
                        continue
                    ev = ev_idx.loc[key]
                    trig = ev["trigger_price"]
                    day = day.sort_values("bar_time").reset_index(drop=True)
                    hit = day.index[day["high_price"] >= trig - 1e-9]
                    if len(hit) == 0:
                        continue
                    fh = int(hit[0])
                    if day.loc[fh, "close_price"] < trig - 1e-9 or fh + 1 >= len(day):
                        continue
                    entry = float(day.loc[fh + 1, "open_price"])
                    kk = int(ev["streak_h"]) if np.isfinite(ev.get("streak_h", np.nan)) else 0
                    kk = min(kk, 6)
                    if not ev["sealed"] or kk < 2:
                        exit_px = ev["open_p1"]
                    else:
                        exit_px = ev[f"open_p{kk}"]
                    if not np.isfinite(exit_px):
                        continue
                    rows.append({"tt": day.loc[fh, "tt"], "ret": float(exit_px / (entry * (1 + SLIP)) - 1),
                                 "sealed": bool(ev["sealed"]), "streak": kk})
            del mb
    mr = pd.DataFrame(rows)
    out["Q2_n"] = len(mr)
    if len(mr):
        mr["bucket"] = pd.cut(mr["tt"], ["00:00", "09:45", "11:30", "14:00", "15:00"],
                              labels=["<=09:45", "09:45~11:30", "13:00前~14:00", "14:00后"])
        out["Q2_buckets"] = [
            {"bucket": str(b), "n": len(g_), "ret": round(g_.ret.mean() * 100, 2),
             "win": round((g_.ret > 0).mean(), 3), "seal": round(g_.sealed.mean(), 3),
             "ge2": round((g_.streak >= 2).mean(), 3)}
            for b, g_ in mr.groupby("bucket", observed=True)]
        am = mr[mr.tt <= "11:30"]["ret"]
        pm = mr[(mr.tt >= "13:00") & (mr.tt < "14:00")]["ret"]
        if len(pm) > 5:
            t, p = sstats.ttest_ind(am, pm, equal_var=False)
            out["Q2_ttest_上午vs13~14"] = {"n_am": len(am), "n_pm": len(pm),
                                          "am": round(float(am.mean()) * 100, 2),
                                          "pm": round(float(pm.mean()) * 100, 2),
                                          "t": round(float(t), 2), "p": round(float(p), 4)}
        # 含/不含13~14点的组合对比(做或不做的直接答案)
        out["Q2_decision"] = {
            "仅上午(<=11:30)": {"n": len(am), "ret": round(float(am.mean()) * 100, 2)},
            "上午+13~14": {"n": len(am) + len(pm),
                            "ret": round(float(pd.concat([am, pm]).mean()) * 100, 2)}}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
