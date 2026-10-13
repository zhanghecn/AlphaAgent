"""情绪闸门验证: 昨日连板生态 vs 今日首板晋级率 (任务4核心增量).

对 2023+ 主板非ST首板(非一字), 按 T-1 日的市场情绪指标分箱看 P(>=2板):
  - 昨日涨停家数 / 连板家数 / 最高连板高度 / 炸板率
  - 昨日首板家数(供给)
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name FROM stocks", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word, touched_limit
               FROM stock_limit_up_daily WHERE trade_date >= '2022-11-01'""", conn)
    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])

    # 每日情绪序列
    lu["is_zha"] = (~lu.is_limit_up) & lu.touched_limit
    day = lu.groupby("trade_date").agg(
        lu_n=("is_limit_up", "sum"),
        lianban_n=("limit_up_count", lambda s: (s >= 2).sum()),
        max_h=("limit_up_count", "max"),
        zha_n=("is_zha", "sum"),
        first_n=("limit_up_count", lambda s: (s == 1).sum()),
    )
    day["seal_rate"] = day.lu_n / (day.lu_n + day.zha_n)
    day = day.sort_index()
    day_prev = day.shift(1).add_suffix("_tm1")  # T-1 情绪

    # streak 段
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    fb = lu_all[(lu_all.limit_up_count == 1) & (~lu_all.is_one_word) & (lu_all.trade_date >= "2023-01-01")].copy()

    fb = fb.join(day_prev, on="trade_date")
    print(f"首板样本: {len(fb):,}", file=sys.stderr)

    def lift(col, bins):
        f = fb[fb[col].notna()].copy()
        f["bin"] = pd.cut(f[col], bins)
        t = f.groupby("bin", observed=True).agg(
            n=("streak_h", "size"),
            ge2=("streak_h", lambda s: (s >= 2).mean()),
            ge3=("streak_h", lambda s: (s >= 3).mean()),
            ge5=("streak_h", lambda s: (s >= 5).mean()),
        ).round(4)
        return [{"bin": str(i), "n": int(r.n), "ge2": r.ge2, "ge3": r.ge3, "ge5": r.ge5}
                for i, r in t.iterrows()]

    out = {
        "lianban_n_tm1": lift("lianban_n_tm1", [-1, 5, 10, 20, 30, 50, 1000]),
        "max_h_tm1": lift("max_h_tm1", [0, 2, 3, 4, 5, 7, 100]),
        "seal_rate_tm1": lift("seal_rate_tm1", [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]),
        "lu_n_tm1": lift("lu_n_tm1", [-1, 20, 40, 60, 80, 120, 10000]),
        "first_n_tm1": lift("first_n_tm1", [-1, 10, 20, 30, 45, 70, 10000]),
        "zha_n_tm1": lift("zha_n_tm1", [-1, 5, 10, 20, 35, 60, 10000]),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
