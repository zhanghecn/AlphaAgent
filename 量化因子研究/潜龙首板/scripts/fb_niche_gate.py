"""生态位健康度闸门: 用池内信号近N日封板率/连板率(当日收盘即可观测,无未来函数)决定是否开仓.

背景: 2026-04~07 池生态位失效(240笔均-0.42%), 月度熔断太粗(07月仍-6.9%).
闸门在 T 日开盘前用 T-1 及之前的池内信号表现计算, 全部当日收盘已知, 严格无前视.

输出:
1. 闸门逐阈值效果: 全样本/训/验/差月窗(2026-04~07)/2026-08 各段 笔数+均收
2. 差月窗内 闸门开/关 日的逐月明细
3. 最佳闸门的月度收益序列(2025-10起)
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


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count
               FROM stock_limit_up_daily WHERE is_limit_up""", conn)

    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    lu_all = lu.sort_values(["vt_symbol", "trade_date"]).copy()
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
    pool = ((~bars["lu_tm1"])
            & bars["change_pct_tm1"].between(0, 5)
            & (bars["low_price_tm1"] > bars["ma20_tm1"])
            & (bars["dist_ma20"] <= 0.12)
            & (bars["turnover_rate_tm1"] < 8)
            & (bars["cap_yi"] < 1200)
            & (bars["close_price_tm1"] < 12))
    ev = bars[(bars.trade_date >= "2023-01-01") & bars["triggered"] & pool
              & ~bars["oneword_strict"]].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, eo)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
    for kk in range(2, 7):
        disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                           index=ev.index).abs() > 0.11)
    ev = ev[~disc.fillna(False)].dropna(subset=["ret"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)

    # ── 闸门序列: 每个交易日用此前10个交易日内的池内信号表现(当日收盘已知) ──
    sig_day = ev.groupby("trade_date").agg(
        n=("sealed", "size"), seal=("sealed", "mean"),
        streak2=("streak_h", lambda s: (s.fillna(0) >= 2).mean()),
        ret=("ret", "mean")).sort_index()
    all_days = pd.Index(sorted(bars.trade_date.unique()))
    gate_rows = []
    day_list = list(all_days)
    pos = {d: i for i, d in enumerate(day_list)}
    for i, d in enumerate(day_list):
        if i < 11:
            continue
        win_days = day_list[i - 10:i]           # T-10 ~ T-1, 不含 T
        sub = sig_day.loc[sig_day.index.isin(win_days)]
        if not len(sub):
            gate_rows.append((d, 0, np.nan, np.nan, np.nan))
            continue
        gate_rows.append((d, int(sub.n.sum()), float(np.average(sub.seal, weights=sub.n)),
                          float(np.average(sub.streak2, weights=sub.n)),
                          float(np.average(sub.ret, weights=sub.n))))
    gates = pd.DataFrame(gate_rows, columns=["trade_date", "sig_n", "seal10", "streak10", "ret10"])
    gates = gates.set_index("trade_date")
    ev = ev.join(gates, on="trade_date")

    def block(df, label):
        if not len(df):
            return {"label": label, "n": 0}
        r = df.ret
        win = df[(df.trade_date >= "2026-04-01") & (df.trade_date <= "2026-07-31")]
        aug = df[df.month == "2026-08"]
        tr = df[df.trade_date < TRAIN_END]
        va = df[df.trade_date >= TRAIN_END]
        return {"label": label, "全n": len(df), "全均": round(float(r.mean()) * 100, 2),
                "训": round(float(tr.ret.mean()) * 100, 2) if len(tr) else None,
                "验": round(float(va.ret.mean()) * 100, 2) if len(va) else None,
                "差月窗n": len(win), "差月窗均": round(float(win.ret.mean()) * 100, 2) if len(win) else None,
                "202608n": len(aug), "202608均": round(float(aug.ret.mean()) * 100, 2) if len(aug) else None}

    out = {"门槛扫描": [block(ev, "无闸门(基线)")]}
    for th in (0.30, 0.35, 0.40, 0.45, 0.50):
        out["门槛扫描"].append(block(ev[(ev.sig_n >= 3) & (ev.seal10 >= th)], f"近10日封板率>={th:.2f}"))
    for th in (0.03, 0.05, 0.08):
        out["门槛扫描"].append(block(ev[(ev.sig_n >= 3) & (ev.streak10 >= th)], f"近10日连板率>={th:.2f}"))
    out["门槛扫描"].append(block(ev[(ev.sig_n >= 3) & (ev.ret10 > 0)], "近10日均收>0"))

    # 最佳候选月度明细(近10日封板率>=0.40)
    for tag, mask in [("seal10>=0.40", (ev.sig_n >= 3) & (ev.seal10 >= 0.40)),
                      ("streak10>=0.05", (ev.sig_n >= 3) & (ev.streak10 >= 0.05))]:
        sub = ev[mask]
        rows = []
        for m, gm in sub.groupby("month"):
            if m >= "2025-10":
                rows.append(f"{m}:n={len(gm)},{gm.ret.mean()*100:+.2f}")
        out[f"月度_{tag}"] = rows
        # 差月窗逐月被闸门过滤掉多少
        win_all = ev[(ev.trade_date >= "2026-04-01") & (ev.trade_date <= "2026-07-31")]
        win_kept = sub[(sub.trade_date >= "2026-04-01") & (sub.trade_date <= "2026-07-31")]
        out[f"差月窗过滤_{tag}"] = {
            "原n": len(win_all), "留n": len(win_kept),
            "原均": round(float(win_all.ret.mean()) * 100, 2),
            "留均": round(float(win_kept.ret.mean()) * 100, 2) if len(win_kept) else None,
            "被滤掉部分的均": round(float(win_all.loc[win_all.index.difference(win_kept.index)].ret.mean()) * 100, 2)
            if len(win_all) - len(win_kept) > 3 else None}

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
