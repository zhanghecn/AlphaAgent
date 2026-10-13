"""连板高度判别特征分析(任务2, 日线层, 2023+).

样本: 主板非ST首板(limit_up_count==1 且非一字), 2023-01起.
目标: streak>=2 / >=3 / >=5 的条件概率, 按特征分箱.
特征(T-1): change_pct, turnover_rate, dist_ma20, ret5, 是否5日内有涨停后断板(弱转强)
特征(T):   gap_open, 当日换手率, 量比(vs 5日均量), breadth_tm1
另: 弱转强定义 = 前5日内有 limit_up_count>=2 的连板后断板(首板前10日内出现过连板记录).
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
DAILY_START = "2022-06-01"
REPORT_START = "2023-01-01"


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= %s""", conn, params=(DAILY_START,))
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word
               FROM stock_limit_up_daily""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    main_syms = set(stocks.loc[(stocks.board == "main") & (~stocks.is_st), "vt_symbol"])

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])

    g = bars.groupby("vt_symbol", sort=False)
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["vol_ma5"] = g["volume"].transform(lambda s: s.rolling(5).mean())
    for col in ["close_price", "change_pct", "turnover_rate", "ma10", "ma20", "ret5"]:
        bars[col + "_tm1"] = g[col].shift(1)

    breadth = bars.groupby("trade_date")["change_pct"].agg(up5=lambda s: (s >= 5).sum(), total="count")
    breadth["ratio"] = breadth.up5 / breadth.total
    bars["breadth_tm1"] = bars["trade_date"].map(breadth["ratio"].sort_index().shift(1))

    # streak 高度
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])

    # 弱转强: 首板日前 2~10 个自然日内存在同票 limit_up_count>=2(连板后断板再首板)
    lu2 = lu_all[lu_all.limit_up_count >= 2][["vt_symbol", "trade_date"]].copy()
    lu2["had_lianban"] = True

    fb = lu_all[(lu_all.limit_up_count == 1) & (~lu_all.is_one_word) & (lu_all.trade_date >= REPORT_START)].copy()
    fb = fb.merge(bars[["vt_symbol", "trade_date", "open_price", "close_price", "volume",
                        "turnover_rate", "change_pct", "vol_ma5", "breadth_tm1",
                        "close_price_tm1", "change_pct_tm1", "turnover_rate_tm1",
                        "ma10_tm1", "ma20_tm1", "ret5_tm1"]],
                  on=["vt_symbol", "trade_date"], how="left")

    # 前10日内连板经历(弱转强标记)
    chk = fb[["vt_symbol", "trade_date"]].copy()
    chk["d0"] = chk["trade_date"]
    m = chk.merge(lu2, on="vt_symbol", how="left")
    m["delta"] = (m["d0"] - m["trade_date_y"]).dt.days if "trade_date_y" in m else (m["d0"] - m["trade_date"]).dt.days
    # merge 后列名: trade_date_x=首板日, trade_date_y=连板日
    delta = (m["trade_date_x"] - m["trade_date_y"]).dt.days
    wts = m[(delta >= 2) & (delta <= 10)][["vt_symbol", "trade_date_x"]].drop_duplicates()
    wts["weak2strong"] = True
    fb = fb.merge(wts, left_on=["vt_symbol", "trade_date"], right_on=["vt_symbol", "trade_date_x"], how="left")
    fb["weak2strong"] = fb["weak2strong"].fillna(False)
    fb.drop(columns=[c for c in ["trade_date_x", "trade_date_y"] if c in fb.columns], inplace=True)

    fb["gap_open"] = fb["open_price"] / fb["close_price_tm1"] - 1
    fb["vol_ratio"] = fb["volume"] / fb["vol_ma5"]
    fb["dist_ma20"] = fb["close_price_tm1"] / fb["ma20_tm1"] - 1
    fb["grp"] = pd.cut(fb["streak_h"], [0, 1, 2, 4, 99], labels=["1板", "2板", "3-4板", "5板+"])

    print(f"首板样本(2023+): {len(fb):,}  弱转强占比: {fb.weak2strong.mean():.1%}", file=sys.stderr)

    out = {"n": len(fb), "grp_counts": fb["grp"].value_counts().to_dict()}

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

    out["lift_turnover_T"] = lift("turnover_rate", [0, 2, 4, 6, 8, 12, 20, 100])
    out["lift_turnover_tm1"] = lift("turnover_rate_tm1", [0, 2, 4, 6, 8, 12, 20, 100])
    out["lift_gap_open"] = lift("gap_open", [-1, 0, 0.02, 0.04, 0.06, 0.08, 1])
    out["lift_vol_ratio"] = lift("vol_ratio", [0, 1, 1.5, 2, 3, 5, 8, 100])
    out["lift_dist_ma20"] = lift("dist_ma20", [-1, 0, 0.03, 0.06, 0.09, 0.12, 0.2, 1])
    out["lift_ret5_tm1"] = lift("ret5_tm1", [-1, 0, 0.05, 0.1, 0.15, 0.2, 1])
    out["lift_change_tm1"] = lift("change_pct_tm1", [-11, 0, 2, 5, 7, 11])
    out["lift_breadth_tm1"] = lift("breadth_tm1", [0, 0.02, 0.04, 0.06, 0.08, 0.12, 1])

    # 弱转强 vs 非
    for flag, sub in fb.groupby("weak2strong"):
        out[f"weak2strong={flag}"] = {
            "n": int(len(sub)),
            "ge2": round(float((sub.streak_h >= 2).mean()), 4),
            "ge3": round(float((sub.streak_h >= 3).mean()), 4),
            "ge5": round(float((sub.streak_h >= 5).mean()), 4),
        }

    # 组合: 核心结论条件(底座+不过热)在首板样本内的 lift
    c_base = ((fb["change_pct_tm1"] >= 0) & (fb["change_pct_tm1"] <= 5)
              & (fb["close_price_tm1"] > fb["ma20_tm1"]) & (fb["ma10_tm1"] > fb["ma20_tm1"]))
    c_cool = ((fb["dist_ma20"].between(0, 0.12)) & (fb["ret5_tm1"].between(0, 0.15))
              & (fb["turnover_rate_tm1"] < 8))
    c_b6 = fb["breadth_tm1"] < 0.06
    for lb, m in [("首板全体", pd.Series(True, index=fb.index)),
                  ("底座", c_base), ("底座+不过热", c_base & c_cool),
                  ("底座+不过热+盘面", c_base & c_cool & c_b6)]:
        sub = fb[m.fillna(False)]
        out[f"combo::{lb}"] = {
            "n": int(len(sub)), "pct_of_all": round(len(sub) / len(fb), 4),
            "ge2": round(float((sub.streak_h >= 2).mean()), 4),
            "ge3": round(float((sub.streak_h >= 3).mean()), 4),
            "ge5": round(float((sub.streak_h >= 5).mean()), 4),
        }

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
