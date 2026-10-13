""">3板(>=4板)高板首板研究 Step1: 宇宙普查 + 特征分离度.

宇宙: 主板非ST, 2023-01起, T日最高触及+8%, 前日未涨停, 剔除首板一字(买不进).
赢家 = 该首板段最终 streak_h >= 4; 输家 = streak_h 0~3(0=炸板未封,1=单板的,2/3=断板).
买入口径(日线): 触发价=昨收*1.08, 进场=触发价*1.005; 连板则断板日开盘卖, 否则次日开盘卖.

输出:
A 月度宇宙: 首板n / >=2板 / >=3板 / >=4板(>3板,非一字) / 一字占比 / 20cm>3板数
B 理论上限: >3板非一字票逐月 n + 平均ret(假设全部吃到)
C 特征对比: >3板 vs 0~3板 中位数 + Welch t(训练段2025-07前)
D 分箱lift: 各特征5档的>3板命中率
E 赢家高开分布: gap_open 分档(高开>=8%禁做规则对高板票的损失)
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg
from scipy import stats as sstats

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = pd.Timestamp("2025-07-01")


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
    stocks["board20"] = stocks["symbol"].str.startswith(("300", "301", "688", "689"))
    syms20 = set(stocks.loc[stocks.board20, "vt_symbol"])

    # streak 段(主板)
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
    # 20cm 的 >3板 计数(只数个数)
    lu20 = lu[lu.vt_symbol.isin(syms20)]
    lu20_all = lu20.sort_values(["vt_symbol", "trade_date"]).copy()
    lu20_all["gap"] = lu20_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu20_all["new_seg"] = (lu20_all["gap"].isna()) | (lu20_all["gap"] > 7) | (lu20_all["limit_up_count"] == 1)
    lu20_all["seg"] = lu20_all.groupby("vt_symbol")["new_seg"].cumsum()
    seg20 = lu20_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu20_all = lu20_all.join(seg20, on=["vt_symbol", "seg"])
    first20 = lu20_all[(lu20_all.limit_up_count == 1) & (lu20_all.streak_h >= 4)].copy()
    first20["month"] = first20.trade_date.dt.to_period("M").astype(str)
    cnt20 = first20.groupby("month").size()

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu_key = lu_m.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ma20_q1"] = g["ma20"].shift(1)
    bars["ma20_q6"] = g["ma20"].shift(6)
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["ret60"] = g["close_price"].transform(lambda s: s / s.shift(60) - 1)
    bars["amp5"] = g.apply(lambda x: ((x["high_price"] - x["low_price"]) / x["close_price"]))\
        .groupby(bars.vt_symbol).transform(lambda s: s.rolling(5).mean()) if False else None
    # 振幅5日均(避免 groupby.apply 慢): 先算单日振幅再 rolling
    bars["amp"] = (bars["high_price"] - bars["low_price"]) / bars["close_price"]
    bars["amp5"] = bars.groupby("vt_symbol")["amp"].transform(lambda s: s.rolling(5).mean())
    bars["high250"] = g["high_price"].transform(lambda s: s.rolling(250, min_periods=60).max())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20",
                "ret5", "ret60", "amp5", "high250", "volume"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars["lu_flag"] = bars["lu_T"]
    bars["lu_cnt20"] = bars.groupby("vt_symbol")["lu_flag"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    bars["lu_cnt60"] = bars.groupby("vt_symbol")["lu_flag"].transform(
        lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    bars["ma20_slope"] = bars["ma20_q1"] / bars["ma20_q6"] - 1
    bars["vol_rel"] = bars["volume_tm1"] / bars.groupby("vt_symbol")["volume_tm1"].transform(
        lambda s: s.rolling(5).mean())
    bars["near_high250"] = bars["close_price_tm1"] >= bars["high250_tm1"] * 0.97
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    # 宇宙: 首板日(前日未涨停) 触+8% 非一字
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & (~bars["lu_tm1"])
              & ~bars["oneword_strict"]].copy()
    ev["streak_k"] = ev["streak_h"].fillna(0).astype(int).clip(0, 8)
    k = ev["streak_k"]
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
    ev["win4"] = ev["streak_k"] >= 4
    ev["is_train"] = ev.trade_date < TRAIN_END

    out = {"宇宙总n": len(ev), "赢家n(>=4板)": int(ev.win4.sum()),
           "总命中率": round(float(ev.win4.mean()), 4)}

    # ── A 月度宇宙 ────────────────────────────────────────────────
    rows = []
    for mth, sub in ev.groupby("month"):
        rows.append({"month": mth, "触发n": len(sub),
                     ">=2板": int((sub.streak_k >= 2).sum()),
                     ">=3板": int((sub.streak_k >= 3).sum()),
                     ">3板": int(sub.win4.sum()),
                     "命中率%": round(float(sub.win4.mean()) * 100, 1),
                     "20cm>3板": int(cnt20.get(mth, 0))})
    out["A_月度宇宙"] = rows

    # ── B 理论上限(赢家全吃到) ─────────────────────────────────────
    w = ev[ev.win4]
    rows = []
    for mth, sub in w.groupby("month"):
        rows.append({"month": mth, "n": len(sub), "avg_ret": round(float(sub.ret.mean()) * 100, 2),
                     "胜率": round(float((sub.ret > 0).mean()), 3)})
    out["B_赢家理论上限"] = {"全期n": len(w), "全期均": round(float(w.ret.mean()) * 100, 2),
                            "全期胜率": round(float((w.ret > 0).mean()), 3),
                            "月度": rows[-12:]}

    # ── C 特征对比(>3板 vs 0~3板) ─────────────────────────────────
    feats = {"close_price_tm1": ("价位", 1), "cap_yi": ("市值亿", 1),
             "turnover_rate_tm1": ("换手%", 1), "dist_ma20": ("乖离%", 100),
             "change_pct_tm1": ("昨涨%", 1), "gap_open": ("高开%", 100),
             "ret5_tm1": ("前5日%", 100), "ret60_tm1": ("前60日%", 100),
             "amp5_tm1": ("振幅5日%", 100), "lu_cnt20": ("20日涨停数", 1),
             "lu_cnt60": ("60日涨停数", 1), "ma20_slope": ("MA20斜率%", 100),
             "vol_rel": ("昨日量比5日", 1)}
    lose = ev[~ev.win4]
    rows = []
    for f, (label, mul) in feats.items():
        a = pd.to_numeric(w.loc[w.is_train, f], errors="coerce").dropna() * mul
        b = pd.to_numeric(lose.loc[lose.is_train, f], errors="coerce").dropna() * mul
        if len(a) < 30:
            continue
        t, p = sstats.ttest_ind(a, b, equal_var=False)
        rows.append({"特征": label, "赢家中位": round(float(a.median()), 2),
                     "输家中位": round(float(b.median()), 2),
                     "t": round(float(t), 2), "p": round(float(p), 5)})
    out["C_特征对比_训练段"] = sorted(rows, key=lambda r: -abs(r["t"]))
    out["C_年新高占比"] = {"赢家": round(float(w.loc[w.is_train, "near_high250"].mean()), 3),
                          "输家": round(float(lose.loc[lose.is_train, "near_high250"].mean()), 3)}

    # ── D 分箱lift(训练段) ────────────────────────────────────────
    lift = {}
    tr = ev[ev.is_train]
    for f, (label, mul) in feats.items():
        v = pd.to_numeric(tr[f], errors="coerce") * mul
        try:
            bins = pd.qcut(v, 5, duplicates="drop")
        except ValueError:
            continue
        tab = tr.groupby(bins, observed=True)["win4"].agg(["count", "mean"])
        lift[label] = [{"bin": str(ix), "n": int(r["count"]),
                        ">3板率%": round(float(r["mean"]) * 100, 1)}
                       for ix, r in tab.iterrows()]
    out["D_分箱lift"] = lift

    # ── E 赢家高开分布 ────────────────────────────────────────────
    gp = pd.cut(w["gap_open"], [-1, 0, 0.02, 0.06, 0.08, 1],
                labels=["低开/平开", "0~2%", "2~6%", "6~8%", ">=8%"])
    out["E_赢家高开分布"] = [{"档": str(ix), "n": int(r["count"]), "占比%": round(float(r["mean"]) * 100, 1)}
                             for ix, r in w.groupby(gp, observed=True)["win4"].agg(["count", "mean"]).iterrows()]

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
