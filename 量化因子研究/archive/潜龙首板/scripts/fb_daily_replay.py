"""最终7条池 · 纯日线历史回放(2023-01起, 44个月).

进场: high >= 昨收*1.08 → 以 1.08*昨收 买入(开盘跳空>+8%则以开盘价买);
      另加 0.5% 滑点档(真实进场=下一分钟开盘, 比 +8% 略高).
卖出(定稿规则): 未封板 → 次日开盘走; 封板未晋级 → 次日开盘走;
      晋级k板(k>=2) → 断板日收盘走(近似: 第k-1个板收盘价 = T+k-1 收盘).
输出: 按月 n/封板率/平均每笔收益/胜率; 全样本上影线分组; 逐月正收益统计.
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIPPAGE = 0.005  # 进场滑点档


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
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["open_p1"] = g["open_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20"]:
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
    bars["entry_raw"] = np.where(bars["open_price"] > bars["trigger_price"],
                                 bars["open_price"], bars["trigger_price"])
    bars["sealed"] = bars["lu_T"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)

    # 最终7条池
    dist = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    pool = ((~bars["lu_tm1"])
            & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"])
            & (dist <= 0.12)
            & (bars["turnover_rate_tm1"] < 8)
            & (bars["cap_yi"] < 1200))

    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool].copy()
    print(f"回放触发样本(2023+): {len(ev):,}", file=sys.stderr)

    def build_ret(df, slip):
        e = df["entry_raw"] * (1 + slip)
        sealed = df["sealed"]
        k = df["streak_h"].fillna(0).astype(int).clip(0, 6)
        exit_open = np.full(len(df), np.nan)
        for kk in range(2, 7):
            sel = (k == kk).values if hasattr(k, 'values') else (k == kk)
            px = df[f"open_p{kk}"].values
            exit_open = np.where(sel, px, exit_open)
        exit_open = np.where(~sealed | (k < 2), df["open_p1"].values, exit_open)
        # 未封板/仅1板 → 次日(T+1)开盘走; 晋级k板 → 断板日(T+k)开盘走
        ret = exit_open / e.values - 1
        return pd.Series(ret, index=df.index)

    ev["ret0"] = build_ret(ev, 0.0)
    ev["ret_s"] = build_ret(ev, SLIPPAGE)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    ev["upper_shadow_close"] = ev["close_price"] / ev["close_price_tm1"] - 1  # 收盘涨幅
    ev["held8_eod"] = ev["close_price"] >= ev["trigger_price"]  # 全天收在+8%上

    def mstat(df, label):
        n = len(df)
        if n < 3:
            return {"label": label, "n": n}
        r = df["ret_s"].dropna()
        return {"label": label, "n": n,
                "seal": round(float(df.sealed.mean()), 3),
                "ret": round(float(r.mean()) * 100, 2),
                "win": round(float((r > 0).mean()), 3),
                "med": round(float(r.median()) * 100, 2)}

    out = {}
    out["overall_slip0"] = mstat(ev.assign(ret_s=ev["ret0"]), "全体(无滑点)")
    out["overall_slip05"] = mstat(ev, "全体(0.5%滑点)")
    months = []
    for m, g_ in ev.groupby("month"):
        months.append(mstat(g_, m))
    out["by_month"] = months
    pos = sum(1 for r in months if r.get("ret", 0) > 0)
    out["month_pos_ratio"] = f"{pos}/{len(months)}"

    # 上影线分组(解释「收住」在日线口径的意义与陷阱)
    out["shadow_groups"] = [
        mstat(ev[ev["held8_eod"]], "全天收>=+8%(短上影/收住)"),
        mstat(ev[~ev["held8_eod"]], "摸+8%但收盘<+8%(长上影/回落)"),
    ]
    # 按日聚合(等权买当天所有信号): 每日组合收益 → 每月均值与正收益日占比
    day_ret = ev.groupby("trade_date")["ret_s"].mean()
    day_ret.index = pd.to_datetime(day_ret.index)
    dm = day_ret.groupby(day_ret.index.to_period("M")).agg(["mean", "size"])
    dm["pos_days"] = day_ret.groupby(day_ret.index.to_period("M")).apply(lambda s: (s > 0).mean())
    out["daily_portfolio_by_month"] = [
        {"month": str(i), "days": int(r["size"]), "avg_day_ret": round(r["mean"] * 100, 2),
         "pos_day_ratio": round(float(r["pos_days"]), 2)} for i, r in dm.iterrows()]
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
