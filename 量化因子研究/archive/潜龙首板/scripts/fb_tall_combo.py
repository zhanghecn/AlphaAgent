""">3板高板首板研究 Step2: 条件组合扫描,目标=逐月收益稳定为正.

口径同 Step1(日线,+8%触发,0.5%滑点,断板/次日开盘卖,剔一字与除权).
扫描: 单条件档位 → 贪心前向组合(最多4条), 排名目标=训练段正收益月占比(同分比月均),
约束: 训练段 n>=800 且 月均>=25笔/月. 输出 top 组合的 训/验/全 三段 + 逐月序列(验收用).
"""
from __future__ import annotations

import os, json, sys
import itertools
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = pd.Timestamp("2025-07-01")


def load_events():
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
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["ret60"] = g["close_price"].transform(lambda s: s / s.shift(60) - 1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20", "ret60"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars["ma20_q1"] = g["ma20"].shift(1)
    bars["ma20_q6"] = g["ma20"].shift(6)
    bars["ma20_slope"] = bars["ma20_q1"] / bars["ma20_q6"] - 1
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
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
    ev["win4"] = ev["streak_h"].fillna(0).astype(int) >= 4
    ev["is_train"] = ev.trade_date < TRAIN_END
    return ev


def month_stats(df):
    if not len(df):
        return None
    m = df.groupby("month")["ret"].agg(["count", "mean"])
    pos_ratio = float((m["mean"] > 0).mean())
    return {"n": len(df), "月均笔数": round(float(m["count"].mean()), 1),
            "均收": round(float(df.ret.mean()) * 100, 2),
            "胜率": round(float((df.ret > 0).mean()), 3),
            ">3板率%": round(float(df.win4.mean()) * 100, 2),
            "正收益月占比": round(pos_ratio, 3),
            "最差月均": round(float(m["mean"].min()) * 100, 2),
            "月数": int(len(m))}


def main():
    ev = load_events()
    tr = ev[ev.is_train]

    CANDS = {
        "市值<40": ev.cap_yi < 40, "市值<50": ev.cap_yi < 50, "市值<60": ev.cap_yi < 60,
        "市值<80": ev.cap_yi < 80,
        "价<6": ev.close_price_tm1 < 6, "价<8": ev.close_price_tm1 < 8,
        "价<10": ev.close_price_tm1 < 10, "价<12": ev.close_price_tm1 < 12,
        "昨涨-3~1": ev.change_pct_tm1.between(-3, 1), "昨涨-5~2": ev.change_pct_tm1.between(-5, 2),
        "昨涨-3~3": ev.change_pct_tm1.between(-3, 3), "昨涨<=0": ev.change_pct_tm1 <= 0,
        "昨涨0~5": ev.change_pct_tm1.between(0, 5),
        "换手2~8": ev.turnover_rate_tm1.between(2, 8), "换手3~10": ev.turnover_rate_tm1.between(3, 10),
        "换手<8": ev.turnover_rate_tm1 < 8, "换手>=3": ev.turnover_rate_tm1 >= 3,
        "乖离-5~12": ev.dist_ma20.between(-0.05, 0.12), "乖离0~12": ev.dist_ma20.between(0, 0.12),
        "乖离-10~10": ev.dist_ma20.between(-0.10, 0.10),
        "MA20上行": ev.ma20_slope > 0, "MA20强上行": ev.ma20_slope > 0.005,
        "前60日>0": ev.ret60_tm1 > 0, "前60日>-10%": ev.ret60_tm1 > -0.10,
        "低开平开": ev.gap_open < 0.02, "高开<6%": ev.gap_open < 0.06, "高开<8%": ev.gap_open < 0.08,
        "昨低>MA20": ev.low_price_tm1 > ev.ma20_tm1,
    }
    CANDS_TR = {k: v[ev.is_train] for k, v in CANDS.items()}

    def score(df_c, df_all, mask_all):
        sub = df_all[mask_all]
        if len(sub) < 300:
            return None
        st = month_stats(sub)
        if not st or st["月均笔数"] < 25:
            return None
        return st

    # 单条件
    single = []
    for name, m in CANDS.items():
        st = score(None, ev, m)
        st_tr = month_stats(tr[CANDS_TR[name]])
        if st and st_tr:
            single.append({"条件": name, "训": st_tr, "全": st})
    single.sort(key=lambda r: (-r["训"]["正收益月占比"], -r["训"]["均收"]))
    out = {"单条件_top12": [{"条件": r["条件"],
                            "训": {k: r["训"][k] for k in ("均收", "正收益月占比", "最差月均", "月均笔数", ">3板率%")},
                            "全": {k: r["全"][k] for k in ("均收", "正收益月占比", "最差月均", "月均笔数", ">3板率%")}}
                           for r in single[:12]]}

    # 贪心前向: 从训练段最优3个种子出发, 最多4条
    seeds = [r["条件"] for r in single[:6]]
    results = []

    def greedy(seed):
        cur = [seed]
        cur_mask_tr = CANDS_TR[seed].copy()
        cur_mask_all = CANDS[seed].copy()
        for _ in range(3):
            best = None
            for name in CANDS:
                if name in cur:
                    continue
                m_tr = cur_mask_tr & CANDS_TR[name]
                sub_tr = tr[m_tr]
                if len(sub_tr) < 800:
                    continue
                st = month_stats(sub_tr)
                if not st or st["月均笔数"] < 25:
                    continue
                key = (st["正收益月占比"], st["均收"])
                if best is None or key > best[0]:
                    best = (key, name, m_tr)
            if best is None:
                break
            cur.append(best[1])
            cur_mask_tr = cur_mask_tr & CANDS_TR[best[1]]
            mask_all = np.logical_and.reduce([CANDS[c] for c in cur])
            results.append(list(cur))
        return cur

    for s in seeds:
        greedy(s)
    # 去重(同集合)
    seen = set()
    uniq = []
    for combo in results:
        key = tuple(sorted(combo))
        if key not in seen:
            seen.add(key)
            uniq.append(combo)

    rows = []
    for combo in uniq:
        mask_all = pd.Series(True, index=ev.index)
        for c_ in combo:
            mask_all &= CANDS[c_]
        st_tr = month_stats(ev[mask_all & ev.is_train])
        st_va = month_stats(ev[mask_all & ~ev.is_train])
        st_all = month_stats(ev[mask_all])
        if not st_tr or not st_va or not st_all:
            continue
        if st_all["月均笔数"] < 25:
            continue
        rows.append({"组合": "+".join(combo), "训": st_tr, "验": st_va, "全": st_all})
    rows.sort(key=lambda r: (-r["全"]["正收益月占比"], -r["全"]["均收"]))
    out["组合_top15"] = [{"组合": r["组合"],
                         "训": {k: r["训"][k] for k in ("n", "均收", "胜率", "正收益月占比", "最差月均", "月均笔数", ">3板率%")},
                         "验": {k: r["验"][k] for k in ("n", "均收", "胜率", "正收益月占比", "最差月均", "月均笔数", ">3板率%")},
                         "全": {k: r["全"][k] for k in ("正收益月占比", "最差月均")}}
                        for r in rows[:15]]

    # top3 组合的逐月明细(全期)
    details = {}
    for r in rows[:3]:
        combo = r["组合"].split("+")
        mask_all = pd.Series(True, index=ev.index)
        for c_ in combo:
            mask_all &= CANDS[c_]
        sub = ev[mask_all]
        m = sub.groupby("month")["ret"].agg(["count", "mean"])
        details[r["组合"]] = [{"month": str(ix), "n": int(rr["count"]),
                               "均收": round(float(rr["mean"]) * 100, 2)}
                              for ix, rr in m.iterrows()]
    out["top3逐月"] = details

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
