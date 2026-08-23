""">=3板研究 稳健性终验: S+P+V 网格 + 逐月全景 + 量比条件盘中可执行性.

R1 参数高原: 市值{40,50,60,80} × 价{6,8,10,12} × 量比{1.0,1.5,2.0,2.5}
   每格报 验段正月占比/均收 + 全期正月占比 —— 看是否成片(稳健)而非尖峰(过拟合)
R2 定稿候选(市值50+价8+量比1.5) 41个月逐月全景 + ex-2024-09 对照
R3 量比条件盘中可执行性(分钟era 2026-06~08): 触及时刻量比 vs 全日量比的翻转率,
   以及用"触及时刻量比<1.5"重新计算的逐笔收益
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


def load():
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
    lu_key = lu_m.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["vol_ratio_T"] = bars["volume"] / bars["vol_ma5_prev"]
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & (~bars["lu_tm1"])
              & ~bars["oneword_strict"]].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 8)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["lu_T"] | (k < 2), ev["open_p1"].values, eo)
    ev["entry"] = np.where(ev["open_price"] > ev["trigger_price"],
                           ev["open_price"], ev["trigger_price"]) * (1 + SLIP)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)].dropna(subset=["ret"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["is_train"] = ev.trade_date < TRAIN_END
    return ev[ev.gap_open < 0.08]


def main():
    ev = load()
    out = {}

    # R1 网格
    grid = []
    for cap in (40, 50, 60, 80):
        for price in (6, 8, 10, 12):
            for vr in (1.0, 1.5, 2.0, 2.5):
                m = (ev.cap_yi < cap) & (ev.close_price_tm1 < price) & (ev.vol_ratio_T < vr)
                sub = ev[m]
                st_all = month_stats(sub)
                st_va = month_stats(sub[~sub.is_train])
                if not st_all or not st_va or st_all["月均笔数"] < 20:
                    continue
                grid.append({"市值": cap, "价": price, "量比": vr,
                             "验正月": st_va["正月占比"], "验均": st_va["均收"],
                             "全正月": st_all["正月占比"], "全均": st_all["均收"],
                             "全月笔": st_all["月均笔数"]})
    out["R1_网格"] = grid

    # R2 定稿候选逐月 + ex2409
    final = ev[(ev.cap_yi < 50) & (ev.close_price_tm1 < 8) & (ev.vol_ratio_T < 1.5)]
    m = final.groupby("month")["ret"].agg(["count", "mean"])
    out["R2_逐月"] = [{"month": str(ix), "n": int(rr["count"]),
                       "均": round(float(rr["mean"]) * 100, 2)} for ix, rr in m.iterrows()]
    out["R2_全"] = month_stats(final)
    out["R2_训"] = month_stats(final[final.is_train])
    out["R2_验"] = month_stats(final[~final.is_train])
    out["R2_剔202409"] = month_stats(final[final.month != "2024-09"])
    out["R2_2026逐月"] = [r for r in out["R2_逐月"] if r["month"] >= "2026-01"]

    # R3 量比盘中可执行性(1m era: 2026-06~08) —— 在 S+P 池上测(不带量比过滤)
    sub = ev[(ev.cap_yi < 50) & (ev.close_price_tm1 < 8) & (ev.trade_date >= "2026-06-01")]
    rows = []
    with psycopg.connect(DSN) as conn:
        for mth, gsub in sub.groupby("month"):
            pairs = gsub[["vt_symbol", "trade_date"]].drop_duplicates()
            if not len(pairs):
                continue
            vals = ",".join(f"('{s}','{d.date()}')" for s, d in pairs.itertuples(index=False))
            mb = pd.read_sql(
                f"""SELECT m.vt_symbol, m.trade_date, m.bar_time, m.high_price, m.volume
                    FROM stock_minute_bars m JOIN (VALUES {vals}) AS v(s, d)
                      ON m.vt_symbol = v.s AND m.trade_date = v.d::date
                    WHERE m.interval = '1m'""", conn)
            if mb.empty:
                continue
            mb["trade_date"] = pd.to_datetime(mb["trade_date"])
            eidx = gsub.set_index(["vt_symbol", "trade_date"])
            for (sym, d), day in mb.groupby(["vt_symbol", "trade_date"]):
                key = (sym, d)
                if key not in eidx.index:
                    continue
                e = eidx.loc[key]
                if isinstance(e, pd.DataFrame):
                    e = e.iloc[0]
                day = day.sort_values("bar_time")
                trig = e["trigger_price"]
                hit = day.index[day["high_price"] >= trig - 1e-9]
                if len(hit) == 0:
                    continue
                fh_pos = day.index.get_loc(hit[0])
                # 分钟成交量与日线成交量单位不同(股 vs 手), 用当日总量反推换算系数
                minute_total = float(day["volume"].sum())
                daily_vol = float(e["volume"])
                if minute_total <= 0 or not np.isfinite(daily_vol) or daily_vol <= 0:
                    continue
                scale = daily_vol / minute_total     # 日线单位/分钟单位
                vol_at_touch = float(day["volume"].iloc[:fh_pos + 1].sum()) * scale
                vr_touch = vol_at_touch / float(e["vol_ma5_prev"]) if e["vol_ma5_prev"] else np.nan
                rows.append({"month": str(mth), "vr_full": float(e["vol_ratio_T"]),
                             "vr_touch": vr_touch, "ret": float(e["ret"]),
                             "pass_full": bool(e["vol_ratio_T"] < 1.5),
                             "pass_touch": bool(vr_touch < 1.5)})
    if rows:
        rdf = pd.DataFrame(rows)
        flip = rdf[rdf.pass_full != rdf.pass_touch]
        kept_touch = rdf[rdf.pass_touch]
        out["R3_量比盘中"] = {
            "n": len(rdf), "翻转率": round(len(flip) / len(rdf), 3),
            "全日口径通过n": int(rdf.pass_full.sum()),
            "触及口径通过n": int(kept_touch.pass_touch.sum()),
            "触及口径均收": round(float(kept_touch.ret.mean()) * 100, 2) if len(kept_touch) else None,
            "全日口径均收(对照)": round(float(rdf.loc[rdf.pass_full, "ret"].mean()) * 100, 2)
            if rdf.pass_full.sum() else None,
            "触及多放进来(全日>=1.5但触及<1.5)的均收": round(
                float(rdf.loc[(~rdf.pass_full) & (rdf.pass_touch), "ret"].mean()) * 100, 2)
            if ((~rdf.pass_full) & (rdf.pass_touch)).sum() else None,
            "n_多放": int(((~rdf.pass_full) & (rdf.pass_touch)).sum()),
            "触及剔除(触及已爆量)的均收": round(float(rdf.loc[~rdf.pass_touch, "ret"].mean()) * 100, 2)
            if (~rdf.pass_touch).sum() else None,
            "n_触及剔除": int((~rdf.pass_touch).sum())}

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
