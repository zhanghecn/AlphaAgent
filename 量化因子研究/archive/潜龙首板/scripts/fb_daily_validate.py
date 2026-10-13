"""首板日线条件全历史验证(任务1+部分任务2).

验证 首板研究核心结论.md 的日线四类条件:
  底座:   主板非ST; T-1 未涨停且 0%<=涨幅<=5%; close>MA20; MA10>MA20
  不过热: 0<=close/MA20-1<=12%; 0<=前5日涨幅<=15%; T-1换手<8%
  盘面:   T-1 主板非ST 涨幅>=5% 占比 < 6%
事件日T: high>=prev_close*1.08 视为触发进场, entry=max(1.08*prev_close, open)
产出: 触发数/封板率/D+1/D+3(相对进场价), 按年分层, 条件逐级递进, 连板高度分布.
"""
from __future__ import annotations

import os
import sys
import json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
START = "2004-06-01"   # 加载起点(留均线lookback)
REPORT_START = "2005-01-01"

def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql(
            "SELECT vt_symbol, symbol, name FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= %s""", conn,
            params=(START,))
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count,
                      is_one_word, touched_limit
               FROM stock_limit_up_daily""", conn)
    return stocks, bars, lu


def main() -> None:
    stocks, bars, lu = load()
    # 主板: 60x/68x 是 SSE; 000/001/002/003 SZSE 主板. 排除 300/301(cyb) 688(kcb) 8/4/92(bse)
    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    print(f"主板非ST股票数(按当前名称): {len(main_syms)}", file=sys.stderr)

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    print(f"主板日线行数: {len(bars):,}  区间: {bars.trade_date.min().date()} ~ {bars.trade_date.max().date()}", file=sys.stderr)

    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])

    g = bars.groupby("vt_symbol", sort=False)
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    # 次日/第3日收盘(个股自己的交易日序列)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p3"] = g["close_price"].shift(-3)

    # 盘面广度: 每日主板非ST 涨幅>=5% 占比
    breadth = bars.groupby("trade_date")["change_pct"].agg(
        up5=lambda s: (s >= 5).sum(), total="count")
    breadth["ratio"] = breadth.up5 / breadth.total

    # 将 T-1 特征移到 T 行上
    for col in ["close_price", "open_price", "change_pct", "turnover_rate", "ma10", "ma20", "ret5"]:
        bars[col + "_tm1"] = g[col].shift(1)
    breadth_prev = breadth["ratio"].sort_index().shift(1)  # 上一交易日广度
    bars["breadth_tm1"] = bars["trade_date"].map(breadth_prev)

    # T-1 是否涨停 / T 日涨停信息
    lu_flag = lu_key["is_limit_up"]
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_flag).fillna(False).astype(bool).values
    tm1_map = bars.groupby("vt_symbol", sort=False)["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_map])
    bars["lu_tm1"] = idx_tm1.map(lu_flag).fillna(False).astype(bool).values
    bars["oneword_T"] = idx.map(lu_key["is_one_word"]).fillna(False).astype(bool).values
    bars["lucount_T"] = idx.map(lu_key["limit_up_count"]).fillna(0).astype(int).values

    # 事件日 T 触发与进场
    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"],
                             bars["open_price"], bars["trigger_price"])
    bars["sealed"] = bars["lu_T"]
    bars["ret_d0_close"] = bars["close_price"] / bars["entry"] - 1
    bars["ret_d1_open"] = bars["open_p1"] / bars["entry"] - 1
    bars["ret_d1"] = bars["close_p1"] / bars["entry"] - 1
    bars["ret_d3"] = bars["close_p3"] / bars["entry"] - 1

    ev = bars[(bars.trade_date >= REPORT_START) & bars["triggered"]].copy()

    # 条件定义(全部基于 T-1)
    c_base = ((~ev["lu_tm1"])
              & (ev["change_pct_tm1"] >= 0) & (ev["change_pct_tm1"] <= 5)
              & (ev["close_price_tm1"] > ev["ma20_tm1"])
              & (ev["ma10_tm1"] > ev["ma20_tm1"]))
    c_cool = ((ev["close_price_tm1"] / ev["ma20_tm1"] - 1 >= 0)
              & (ev["close_price_tm1"] / ev["ma20_tm1"] - 1 <= 0.12)
              & (ev["ret5_tm1"] >= 0) & (ev["ret5_tm1"] <= 0.15)
              & (ev["turnover_rate_tm1"] < 8))
    c_breadth = ev["breadth_tm1"] < 0.06
    c_not_lu_tm1 = ~ev["lu_tm1"]

    ev["year"] = ev["trade_date"].dt.year

    def stats(df: pd.DataFrame, label: str) -> dict:
        n = len(df)
        if n == 0:
            return {"label": label, "n": 0}
        sealed = df[df["sealed"]]
        return {
            "label": label, "n_trigger": n,
            "seal_rate": round(len(sealed) / n, 4),
            "d1_mean": round(df["ret_d1"].mean() * 100, 3),
            "d1_median": round(df["ret_d1"].median() * 100, 3),
            "d1_win": round((df["ret_d1"] > 0).mean(), 4),
            "d3_mean": round(df["ret_d3"].mean() * 100, 3),
            "d3_win": round((df["ret_d3"] > 0).mean(), 4),
            "d1open_mean": round(df["ret_d1_open"].mean() * 100, 3),
            "d0close_mean": round(df["ret_d0_close"].mean() * 100, 3),
        }

    layers = [
        ("L0 无筛选(仅触发+8%)", ev),
        ("L0b T-1未涨停", ev[c_not_lu_tm1]),
        ("L1 +底座", ev[c_base]),
        ("L2 +不过热", ev[c_base & c_cool]),
        ("L3 +盘面<6%", ev[c_base & c_cool & c_breadth]),
    ]

    out = {"overall": [stats(df, lb) for lb, df in [(l, d) for l, d in layers]]}

    # 按年分层(对 L3 全条件 与 L0b 基线)
    for tag, mask in [("L3_full", c_base & c_cool & c_breadth), ("baseline_notlu", c_not_lu_tm1)]:
        sub = ev[mask]
        rows = []
        for y, grp in sub.groupby("year"):
            rows.append(stats(grp, str(y)))
        out[f"by_year_{tag}"] = rows

    # 连板高度: 仅看封住的事件, 其首板后最终连板高度(向后连续涨停计数)
    # 用 limit_up_daily 直接算: 每个首板(lucount==1)往后该票 streak 最大 lucount
    lu1 = lu[(lu.is_limit_up) & (lu.limit_up_count == 1) & (~lu.is_one_word)].copy()
    lu1.sort_values(["vt_symbol", "trade_date"], inplace=True)
    # streak 高度 = 从首板日起连续 is_limit_up 的最大 limit_up_count
    # limit_up_count 已是当日连板数, 取该首板之后 30 个交易日内同票最大 count 且 streak 连续
    # 简化: 用同票未来 40 天内 limit_up_count 最大值, 但需与首板 streak 相连.
    # 精确法: 对每个首板事件, streak = 连续涨停段; 用 diff 断段.
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
    first = first.set_index(["vt_symbol", "trade_date"])
    ev = ev.join(first, on=["vt_symbol", "trade_date"])

    for tag, mask in [("L3_full", c_base & c_cool & c_breadth), ("baseline_notlu", c_not_lu_tm1)]:
        sub = ev[mask & ev["sealed"] & ev["streak_h"].notna()]
        if len(sub):
            dist = sub["streak_h"].value_counts().sort_index()
            out[f"streak_dist_{tag}"] = {
                "n": int(len(sub)),
                "mean_streak": round(float(sub["streak_h"].mean()), 3),
                "pct_ge2": round(float((sub.streak_h >= 2).mean()), 4),
                "pct_ge3": round(float((sub.streak_h >= 3).mean()), 4),
                "pct_ge5": round(float((sub.streak_h >= 5).mean()), 4),
                "dist": {str(int(k)): int(v) for k, v in dist.items()},
            }

    # 近2年逐月明细(供与 3/6/7月 结论对账)
    recent = ev[c_base & c_cool & c_breadth & (ev.trade_date >= "2025-01-01")]
    rows = []
    for ym, grp in recent.groupby(ev.trade_date.dt.to_period("M")):
        rows.append(stats(grp, str(ym)))
    out["L3_by_month_2025plus"] = rows

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
