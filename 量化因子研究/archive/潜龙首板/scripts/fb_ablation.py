"""首板池条件消融实验(2023+ 日线触发样本, 大样本).

目标: 精简条件. 逐条 leave-one-out, 看 seal/d1/d3/ge2 变化.
冗余检验: 昨未涨停 vs 涨幅0~5%; 距MA20下界0 vs 昨低>MA20; ret5下界0.
市值用当前快照(超大盘判定稳定, 小票有漂移, 注意).
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


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
    cap_map = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()  # 亿

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])

    g = bars.groupby("vt_symbol", sort=False)
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["ret60"] = g["close_price"].transform(lambda s: s / s.shift(60) - 1)
    bars["high250"] = g["high_price"].transform(lambda s: s.rolling(250, min_periods=60).max())
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p3"] = g["close_price"].shift(-3)
    for col in ["close_price", "low_price", "change_pct", "turnover_rate",
                "ma10", "ma20", "ret5", "ret60", "high250"]:
        bars[col + "_tm1"] = g[col].shift(1)

    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values

    # streak(晋级)
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
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"], bars["open_price"], bars["trigger_price"])
    bars["sealed"] = bars["lu_T"]
    bars["ret_d1"] = bars["close_p1"] / bars["entry"] - 1
    bars["ret_d3"] = bars["close_p3"] / bars["entry"] - 1
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)

    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"]].copy()
    print(f"触发样本: {len(ev):,}", file=sys.stderr)

    dist = ev["close_price_tm1"] / ev["ma20_tm1"] - 1
    conds = {
        "昨未涨停": ~ev["lu_tm1"],
        "昨涨幅0~5": (ev["change_pct_tm1"] >= 0) & (ev["change_pct_tm1"] <= 5),
        "昨低>MA20": ev["low_price_tm1"] > ev["ma20_tm1"],
        "MA10>20": ev["ma10_tm1"] > ev["ma20_tm1"],
        "距MA20<=12": dist <= 0.12,
        "距MA20>=0": dist >= 0,
        "前5日<=15": ev["ret5_tm1"] <= 0.15,
        "前5日>=0": ev["ret5_tm1"] >= 0,
        "前60日<20": ev["ret60_tm1"] < 0.20,
        "非年新高": ev["close_price_tm1"] < ev["high250_tm1"] * 0.97,
        "换手<8": ev["turnover_rate_tm1"] < 8,
        "市值<1200亿": ev["cap_yi"] < 1200,
    }
    full_names = ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "MA10>20", "距MA20<=12", "距MA20>=0",
                  "前5日<=15", "前5日>=0", "前60日<20", "非年新高", "换手<8", "市值<1200亿"]

    def stat_df(sub, label):
        n = len(sub)
        if n < 10:
            return {"label": label, "n": n}
        s = sub[sub["sealed"] & sub["streak_h"].notna()]
        return {"label": label, "n": n,
                "seal": round(float(sub.sealed.mean()), 4),
                "d1": round(float(sub.ret_d1.mean()) * 100, 3),
                "d3": round(float(sub.ret_d3.mean()) * 100, 3),
                "ge2": round(float((s.streak_h >= 2).mean()), 4) if len(s) > 10 else None,
                "ge5": round(float((s.streak_h >= 5).mean()), 4) if len(s) > 10 else None}

    def stat(mask, label):
        return stat_df(ev[mask.fillna(False)], label)

    out = {}
    out["baseline_仅触发"] = stat(~ev["lu_tm1"], "基线(仅昨未涨停)")
    full = pd.Series(True, index=ev.index)
    for nm in full_names:
        full &= conds[nm]
    out["FULL_全条件"] = stat(full, "全条件")
    # leave-one-out
    loo = []
    for nm in full_names:
        m = pd.Series(True, index=ev.index)
        for nm2 in full_names:
            if nm2 != nm:
                m &= conds[nm2]
        loo.append(stat(m, f"去掉[{nm}]"))
    out["leave_one_out"] = loo
    # 冗余检验
    out["redundancy"] = [
        stat(conds["昨涨幅0~5"] & ~conds["昨未涨停"], "涨幅0~5但涨停(应为空)"),
        stat(conds["昨低>MA20"] & ~conds["距MA20>=0"], "昨低>MA20但距<0(应为空)"),
    ]
    # 精简候选: 每个子集
    cand_sets = {
        "极简A(涨幅/昨低MA20/MA10/距12/前5/换手)": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "MA10>20", "距MA20<=12", "前5日<=15", "换手<8"],
        "A+前60": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "MA10>20", "距MA20<=12", "前5日<=15", "换手<8", "前60日<20"],
        "A+前60+非年新高": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "MA10>20", "距MA20<=12", "前5日<=15", "换手<8", "前60日<20", "非年新高"],
        "A+前60+非年新高+市值": full_names,
        "仅核心4条(涨幅/昨低MA20/MA10/换手)": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "MA10>20", "换手<8"],
        "最终极简5条(涨幅/昨低MA20/距12/换手/市值)": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "距MA20<=12", "换手<8", "市值<1200亿"],
        "最终极简5条+MA10": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "MA10>20", "距MA20<=12", "换手<8", "市值<1200亿"],
        "极简无市值(涨幅/昨低MA20/距12/换手)": ["昨未涨停", "昨涨幅0~5", "昨低>MA20", "距MA20<=12", "换手<8"],
    }
    ev["year"] = ev["trade_date"].dt.year
    for lb, names in cand_sets.items():
        m = pd.Series(True, index=ev.index)
        for nm in names:
            m &= conds[nm]
        out[f"set::{lb}"] = stat(m, lb)
        if lb.startswith("最终极简"):
            out[f"year::{lb}"] = [stat_df(g_, str(y)) for y, g_ in ev[m.fillna(False)].groupby("year")]

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
