""">3板高板研究 Step3: 接力模型(首板次日开盘买)——成交口径完全真实,无打板滑点争议.

宇宙: 主板非ST, 2023-01起, 首板封板(is_limit_up 且 limit_up_count==1 的段首),
      排除首板一字(筹码断层,接力不做,用户指定).
进场: 首板次日(T+1)开盘价 ×1.005 滑点.
卖出: 走出>=2板 → 断板日开盘(cap 8板); 未走出(T+1未封) → T+2开盘卖.
额外维度: T+1 高开幅度 gap2(接力竞价的核心信号).

模型对照:
M_B 接力裸池(无筛选)
M_B+特征筛选组合(小市值/低价/昨涨/换手/乖离/gap2 档位)
目标: 逐月收益为正占比最大化, 训/验双段.
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


def month_stats(df, retcol="ret"):
    if not len(df):
        return None
    m = df.groupby("month")[retcol].agg(["count", "mean"])
    return {"n": len(df), "月均笔数": round(float(m["count"].mean()), 1),
            "均收": round(float(df[retcol].mean()) * 100, 2),
            "胜率": round(float((df[retcol] > 0).mean()), 3),
            "正收益月占比": round(float((m["mean"] > 0).mean()), 3),
            "最差月均": round(float(m["mean"].min()) * 100, 2)}


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
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    bars["ma20_slope"] = g["ma20"].shift(1) / g["ma20"].shift(6) - 1
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    # 宇宙: 首板封板日(streak_h 存在), 非一字
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["streak_h"].notna()
              & ~bars["oneword_strict"]].copy()
    ev["k"] = ev["streak_h"].astype(int).clip(1, 8)
    # T+1 一字开盘(买不进/不想接): open_p1 >= 涨停价(以首板收盘为基准+10%)
    limit_p1 = (ev["close_price"] * 1.1 + 1e-9).round(2)
    ev["p1_oneword_open"] = ev["open_p1"] >= limit_p1 * 0.999
    ev["gap2"] = ev["open_p1"] / ev["close_price"] - 1
    ev["entry"] = ev["open_p1"] * (1 + SLIP)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((ev["k"] == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(ev["k"] < 2, ev["open_p2"].values, eo)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    # 除权污染
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 9):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)]
    ev = ev[~ev["p1_oneword_open"]]  # T+1 一字开接不到/不接
    ev = ev.dropna(subset=["ret"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["win4"] = ev["streak_h"] >= 4
    ev["is_train"] = ev.trade_date < TRAIN_END
    tr = ev[ev.is_train]

    out = {"接力宇宙n": len(ev), ">3板占比": round(float(ev.win4.mean()), 4),
           "M_B裸池": {"全": month_stats(ev), "训": month_stats(tr),
                       "验": month_stats(ev[~ev.is_train])}}

    # gap2 分档(接力竞价信号)
    gb = pd.cut(ev["gap2"], [-1, -0.02, 0, 0.02, 0.04, 0.07, 1],
                labels=["<-2%", "-2~0%", "0~2%", "2~4%", "4~7%", ">=7%"])
    rows = []
    for bnd, sub in ev.groupby(gb, observed=True):
        subtr = sub[sub.is_train]
        rows.append({"gap2档": str(bnd), "n": len(sub),
                     "全均": round(float(sub.ret.mean()) * 100, 2),
                     "训均": round(float(subtr.ret.mean()) * 100, 2),
                     "胜率": round(float((sub.ret > 0).mean()), 3),
                     ">3板率%": round(float(sub.win4.mean()) * 100, 2),
                     "走出2板率%": round(float((sub.streak_h >= 2).mean()) * 100, 1)})
    out["gap2分档"] = rows

    # 特征筛选组合(在接力宇宙上)
    CANDS = {
        "市值<50": ev.cap_yi < 50, "市值<80": ev.cap_yi < 80, "市值<120": ev.cap_yi < 120,
        "价<8": ev.close_price_tm1 < 8, "价<10": ev.close_price_tm1 < 10, "价<15": ev.close_price_tm1 < 15,
        "昨涨<=0": ev.change_pct_tm1 <= 0, "昨涨-3~3": ev.change_pct_tm1.between(-3, 3),
        "昨涨<5": ev.change_pct_tm1 < 5,
        "换手3~15": ev.turnover_rate_tm1.between(3, 15), "换手<15": ev.turnover_rate_tm1 < 15,
        "乖离-5~12": ev.dist_ma20.between(-0.05, 0.12), "乖离<12": ev.dist_ma20 < 0.12,
        "MA20上行": ev.ma20_slope > 0,
        "gap2在0~4": ev.gap2.between(0, 0.04), "gap2在2~7": ev.gap2.between(0.02, 0.07),
        "gap2<4%": ev.gap2 < 0.04, "gap2<7%": ev.gap2 < 0.07, "gap2低开": ev.gap2 < 0,
        "前60日>0": ev.ret60_tm1 > 0,
    }
    single = []
    for name, m in CANDS.items():
        st_tr = month_stats(ev[m & ev.is_train])
        st_all = month_stats(ev[m])
        if st_tr and st_all and st_tr["月均笔数"] >= 10:
            single.append({"条件": name, "训": st_tr, "全": st_all})
    single.sort(key=lambda r: (-r["训"]["正收益月占比"], -r["训"]["均收"]))
    out["接力单条件_top10"] = [
        {"条件": r["条件"],
         "训": {k: r["训"][k] for k in ("均收", "胜率", "正收益月占比", "最差月均", "月均笔数")},
         "全": {k: r["全"][k] for k in ("均收", "正收益月占比", "最差月均")}}
        for r in single[:10]]

    # 贪心组合(种子=top5)
    seeds = [r["条件"] for r in single[:5]]
    results = []
    for seed in seeds:
        cur = [seed]
        for _ in range(3):
            best = None
            for name in CANDS:
                if name in cur:
                    continue
                mask = pd.Series(True, index=ev.index)
                for c_ in cur + [name]:
                    mask &= CANDS[c_]
                sub_tr = ev[mask & ev.is_train]
                if len(sub_tr) < 150:
                    continue
                st = month_stats(sub_tr)
                if not st or st["月均笔数"] < 8:
                    continue
                key = (st["正收益月占比"], st["均收"])
                if best is None or key > best[0]:
                    best = (key, name)
            if best is None:
                break
            cur.append(best[1])
            results.append(list(cur))
    seen, uniq = set(), []
    for combo in results:
        kk = tuple(sorted(combo))
        if kk not in seen:
            seen.add(kk)
            uniq.append(combo)
    rows = []
    for combo in uniq:
        mask = pd.Series(True, index=ev.index)
        for c_ in combo:
            mask &= CANDS[c_]
        st_tr = month_stats(ev[mask & ev.is_train])
        st_va = month_stats(ev[mask & ~ev.is_train])
        st_all = month_stats(ev[mask])
        if not (st_tr and st_va and st_all) or st_all["月均笔数"] < 8:
            continue
        rows.append({"组合": "+".join(combo), "训": st_tr, "验": st_va, "全": st_all})
    rows.sort(key=lambda r: (-r["全"]["正收益月占比"], -r["全"]["均收"]))
    out["接力组合_top12"] = [
        {"组合": r["组合"],
         "训": {k: r["训"][k] for k in ("n", "均收", "胜率", "正收益月占比", "最差月均", "月均笔数")},
         "验": {k: r["验"][k] for k in ("n", "均收", "胜率", "正收益月占比", "最差月均", "月均笔数")},
         "全正月": r["全"]["正收益月占比"], "全最差": r["全"]["最差月均"]}
        for r in rows[:12]]

    # top3 逐月
    details = {}
    for r in rows[:3]:
        mask = pd.Series(True, index=ev.index)
        for c_ in r["组合"].split("+"):
            mask &= CANDS[c_]
        sub = ev[mask]
        m = sub.groupby("month")["ret"].agg(["count", "mean"])
        details[r["组合"]] = [{"month": str(ix), "n": int(rr["count"]),
                               "均": round(float(rr["mean"]) * 100, 2)} for ix, rr in m.iterrows()]
    out["top3逐月"] = details
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
