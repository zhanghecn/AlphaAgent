"""首板条件进一步优化 + 训练/验证双段验证.

切分: train 2023-01~2025-06 / valid 2025-07~2026-08.
候选(每个单独加在7条池上, 两段分别统计, 同向才成立):
A 昨日收位 (close-low)/(high-low)  [光头阳 vs 光脚]
B 昨日相对换手 = 换手/前5日均换手  [缩量蓄势 vs 放量]
C 昨日振幅 (high-low)/前收
D 昨日量/5日均量
E 昨涨幅下限放开到 -2%(允许小阴)
F 市值下限(<30亿剔除)
G 股价带
H 距MA20 收紧 3~10%
最后: 两段同向的赢家组合, 报告 train/valid/all + 月度正收益率.
"""
from __future__ import annotations

import os, sys, json
import pandas as pd
import numpy as np
import psycopg

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
    bars["vol_ma5"] = g["volume"].transform(lambda s: s.rolling(5).mean())
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "open_price", "high_price", "low_price",
                "turnover_rate", "change_pct", "ma20", "to_ma5", "vol_ma5", "volume"]:
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
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    # 候选因子(T-1)
    rng = (bars["high_price_tm1"] - bars["low_price_tm1"]).replace(0, np.nan)
    bars["close_pos_tm1"] = (bars["close_price_tm1"] - bars["low_price_tm1"]) / rng  # 昨收位
    bars["amp_tm1"] = rng / bars["close_price_tm1"] * (bars["close_price_tm1"] / bars["close_price_tm1"])  # placeholder
    bars["amp_tm1"] = (bars["high_price_tm1"] - bars["low_price_tm1"]) / bars["close_price_tm1"]
    bars["to_rel_tm1"] = bars["turnover_rate_tm1"] / bars["to_ma5_tm1"]      # 昨日相对换手
    bars["vol_rel_tm1"] = bars["volume_tm1"] / bars["vol_ma5_tm1"]           # 昨日量比

    pool = ((~bars["lu_tm1"])
            & (bars["change_pct_tm1"] >= 0) & (bars["change_pct_tm1"] <= 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"])
            & (bars["dist_ma20"] <= 0.12)
            & (bars["turnover_rate_tm1"] < 8)
            & (bars["cap_yi"] < 1200))
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool & ~bars["oneword_strict"]].copy()

    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    exit_open = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        exit_open = np.where((k == kk).values, ev[f"open_p{kk}"].values, exit_open)
    exit_open = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, exit_open)
    ev["ret"] = pd.Series(exit_open / ev["entry"].values - 1, index=ev.index)
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    # 除权污染剔除
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (ev[f"open_p{kk}"] / ev[f"close_p{kk-1}"] - 1).abs() > 0.11
    ev = ev[~disc.fillna(False)]
    ev["is_train"] = ev.trade_date < pd.Timestamp(TRAIN_END)
    print(f"回放样本: {len(ev):,} (train={ev.is_train.sum():,}, valid={(~ev.is_train).sum():,})", file=sys.stderr)

    def stat(df, label):
        r = df["ret"].dropna()
        if len(r) < 30:
            return {"label": label, "n": len(r)}
        m = df.groupby("month")["ret"].mean()
        return {"label": label, "n": len(r),
                "ret": round(float(r.mean()) * 100, 2),
                "win": round(float((r > 0).mean()), 3),
                "pos_month": f"{int((m > 0).sum())}/{len(m)}"}

    def two_seg(mask, label):
        sub = ev[mask.fillna(False)] if hasattr(mask, "fillna") else ev[mask]
        return {"label": label,
                "train": stat(sub[sub.is_train], label + "|train"),
                "valid": stat(sub[~sub.is_train], label + "|valid")}

    out = {"base": [two_seg(pd.Series(True, index=ev.index), "base7条"),
                    ]}
    out["base"][0]["all"] = stat(ev, "base|all")

    cands = []
    # A 昨收位
    for lo, hi in [(0, 0.4), (0.4, 0.7), (0.7, 0.9), (0.9, 1.01)]:
        cands.append((f"A收位{lo}~{hi}", ev["close_pos_tm1"].between(lo, hi, inclusive="right")))
    # B 昨日相对换手
    for lo, hi in [(0, 0.8), (0.8, 1.2), (1.2, 2.0), (2.0, 100)]:
        cands.append((f"B相对换手{lo}~{hi}", ev["to_rel_tm1"].between(lo, hi, inclusive="right")))
    # C 昨日振幅
    for lo, hi in [(0, 0.03), (0.03, 0.05), (0.05, 0.08), (0.08, 1)]:
        cands.append((f"C振幅{lo}~{hi}", ev["amp_tm1"].between(lo, hi, inclusive="right")))
    # D 昨日量比
    for lo, hi in [(0, 0.8), (0.8, 1.2), (1.2, 2.0), (2.0, 100)]:
        cands.append((f"D量比{lo}~{hi}", ev["vol_rel_tm1"].between(lo, hi, inclusive="right")))
    # E 昨涨幅下限放开(在池外加: 允许-2~0%的日子 —— 需重算池, 近似: 直接在触发集里对比)
    #    近似法: 从全体触发(放宽池)看 -2~0% 档表现
    pool_loose = ((~bars["lu_tm1"])
                  & (bars["change_pct_tm1"] >= -2) & (bars["change_pct_tm1"] < 0)
                  & (bars["low_price_tm1"] > bars["ma20_tm1"])
                  & (bars["dist_ma20"] <= 0.12)
                  & (bars["turnover_rate_tm1"] < 8)
                  & (bars["cap_yi"] < 1200))
    ev2 = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool_loose & ~bars["oneword_strict"]].copy()
    if len(ev2):
        k2 = ev2["streak_h"].fillna(0).astype(int).clip(0, 6)
        eo = np.full(len(ev2), np.nan)
        for kk in range(2, 7):
            eo = np.where((k2 == kk).values, ev2[f"open_p{kk}"].values, eo)
        eo = np.where(~ev2["sealed"] | (k2 < 2), ev2["open_p1"].values, eo)
        ev2["ret"] = pd.Series(eo / (np.where(ev2["open_price"] > ev2["trigger_price"],
                                              ev2["open_price"], ev2["trigger_price"]) * (1 + SLIP)) - 1, index=ev2.index)
        ev2["month"] = ev2["trade_date"].dt.to_period("M").astype(str)
        ev2["is_train"] = ev2.trade_date < pd.Timestamp(TRAIN_END)
        out["E小阴档"] = {"train": stat(ev2[ev2.is_train], "昨-2~0%|train"),
                          "valid": stat(ev2[~ev2.is_train], "昨-2~0%|valid"),
                          "all": stat(ev2, "昨-2~0%|all")}
    # F 市值下限
    cands.append(("F市值>=30亿", ev["cap_yi"] >= 30))
    cands.append(("F市值30~300亿", ev["cap_yi"].between(30, 300)))
    # G 股价带
    for lo, hi in [(0, 5), (5, 12), (12, 25), (25, 1000)]:
        cands.append((f"G股价{lo}~{hi}元", ev["close_price_tm1"].between(lo, hi, inclusive="right")))
    # H 距MA20 收紧
    cands.append(("H距MA20 3~10%", ev["dist_ma20"].between(0.03, 0.10)))
    cands.append(("H距MA20 0~6%", ev["dist_ma20"] <= 0.06))

    out["candidates"] = [two_seg(m, lb) for lb, m in cands]

    # ===== 组合验证: 股价<12元(唯一双段胜者) =====
    composites = [
        ("base+股价<12", ev["close_price_tm1"] < 12),
        ("base+股价<12+gap>=2%", (ev["close_price_tm1"] < 12) & (ev.gap_open >= 0.02)),
        ("base+gap>=2%", ev.gap_open >= 0.02),
        ("base+股价<15", ev["close_price_tm1"] < 15),
    ]
    comp = []
    for lb, m in composites:
        row = two_seg(m, lb)
        row["all"] = stat(ev[m.fillna(False)], lb + "|all")
        comp.append(row)
    out["composites"] = comp
    # 最终组合逐月
    fm = ev[(ev["close_price_tm1"] < 12)].groupby("month")["ret"].agg(["mean", "size"])
    out["final_by_month"] = [{"month": str(i), "n": int(r["size"]), "ret": round(r["mean"] * 100, 2)}
                             for i, r in fm.iterrows() if r["size"] >= 3]
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
