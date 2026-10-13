""">=3板好票归纳研究: 首板的含义 + 前期走势归纳(好票vs差票来回对比).

宇宙: 主板非ST, 2023-01起, 首板封住(is_limit_up 段首, limit_up_count==1), 剔首板一字.
好票 = streak_h >= 3; 差票 = streak_h 1~2(封住但没走出3板).
口径: 全部用 T-1 及之前数据(首板前夜), 另附首板当日可观察量(量能/高开).

P1 首板的含义(核心): 前10/20/60日有无涨停 × 位置(pos60) 交叉看好票率
P2 均线排布: 多头/空头/缠绕 × 好票率
P3 前期走势归纳: ret5/10/20/60, 振幅5/20, 量比, pos60/pos250 分箱好票率
P4 昨涨分布直读: 好票里昨日阴线/平盘/0~5/5+ 占比 vs 差票(直接回答"0~5%收阳"条件排除了多少好票)
P5 首板当日: 高开档/放量倍数 好票率
P6 来回对比汇总: P(feat|好) vs P(feat|差), lift, P(好|feat) 按lift排序 —— 归纳关键条件
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
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
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ma60"] = g["close_price"].transform(lambda s: s.rolling(60).mean())
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived)
    bars["amp"] = (bars["high_price"] - bars["low_price"]) / bars["close_price"]
    for w in (5, 10, 20, 60):
        bars[f"ret{w}"] = g["close_price"].transform(lambda s, w=w: s / s.shift(w) - 1)
    bars["amp5"] = g["amp"].transform(lambda s: s.rolling(5).mean())
    bars["amp20"] = g["amp"].transform(lambda s: s.rolling(20).mean())
    bars["vol_ma5"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["low60"] = g["low_price"].transform(lambda s: s.rolling(60).min())
    bars["high60"] = g["high_price"].transform(lambda s: s.rolling(60).max())
    bars["low250"] = g["low_price"].transform(lambda s: s.rolling(250, min_periods=60).min())
    bars["high250"] = g["high_price"].transform(lambda s: s.rolling(250, min_periods=60).max())
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    lu_key = lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"]
    bars["lu_T"] = idx.map(lu_key).fillna(False).astype(bool).values
    for n in (10, 20, 60):
        bars[f"lu_cnt{n}"] = bars.groupby("vt_symbol")["lu_T"].transform(
            lambda s, n=n: s.shift(1).rolling(n, min_periods=1).sum())
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    # 只保留首板日(段首), 特征全部 T-1: 按 (vt_symbol, 前一交易日) 关联
    g2 = bars.groupby("vt_symbol", sort=False)
    prev = bars[["vt_symbol", "trade_date", "close_price", "low_price", "turnover_rate",
                 "change_pct", "ma5", "ma10", "ma20", "ma60", "ret5", "ret10", "ret20", "ret60",
                 "amp5", "amp20", "vol_ma5", "low60", "high60", "low250", "high250", "volume"]].copy()
    prev.rename(columns={c: c + "_tm1" for c in prev.columns[2:]}, inplace=True)
    prev.rename(columns={"trade_date": "tm1_date"}, inplace=True)

    ev = bars[bars["streak_h"].notna() & (bars.trade_date >= "2023-01-01")].copy()
    ev["tm1_date"] = g2["trade_date"].shift(1).loc[ev.index]
    ev = ev.merge(prev, on=["vt_symbol", "tm1_date"], how="left", suffixes=("", "_drop"))
    ev = ev[[c for c in ev.columns if not c.endswith("_drop")]]

    limit_px = (ev["close_price_tm1"] * 1.1 + 1e-9).round(2)
    ev["oneword"] = ev["low_price"] >= limit_px * 0.999
    ev = ev[~ev["oneword"]]
    ev["cap_yi"] = ev.vt_symbol.map(cap_map)
    ev["gap_open"] = ev["open_price"] / ev["close_price_tm1"] - 1
    ev["vol_ratio_T"] = ev["volume"] / ev["vol_ma5_tm1"]      # 首板日量 / 前5日均量(首板日可知)
    ev["vol_ratio_tm1"] = ev["volume_tm1"] / ev["vol_ma5_tm1"]
    ev["pos60"] = (ev["close_price_tm1"] - ev["low60_tm1"]) / (ev["high60_tm1"] - ev["low60_tm1"] + 1e-9)
    ev["pos250"] = (ev["close_price_tm1"] - ev["low250_tm1"]) / (ev["high250_tm1"] - ev["low250_tm1"] + 1e-9)
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["good"] = ev["streak_h"] >= 3
    ev["is_train"] = ev.trade_date < TRAIN_END
    ev = ev.dropna(subset=["close_price_tm1"])

    out = {"宇宙n": len(ev), "好票n": int(ev.good.sum()), "好票率": round(float(ev.good.mean()), 4)}
    G = ev[ev.good]
    B = ev[~ev.good]
    tr = ev[ev.is_train]
    Gtr = tr[tr.good]
    Btr = tr[~tr.good]

    # ── P1 首板的含义: 前N日涨停 × pos60 ─────────────────────────
    p1 = {}
    for n in (10, 20, 60):
        col = f"lu_cnt{n}"
        for pos_label, pmask in [("全部", pd.Series(True, index=tr.index)),
                                 ("低位(pos60<0.3)", tr.pos60 < 0.3),
                                 ("中位(0.3~0.7)", tr.pos60.between(0.3, 0.7)),
                                 ("高位(>0.7)", tr.pos60 > 0.7)]:
            sub = tr[pmask]
            no_lu = sub[sub[col] == 0]
            has_lu = sub[sub[col] > 0]
            p1[f"前{n}日×{pos_label}"] = {
                "无涨停": {"n": len(no_lu), "好票率%": round(float(no_lu.good.mean()) * 100, 1) if len(no_lu) else None},
                "有涨停": {"n": len(has_lu), "好票率%": round(float(has_lu.good.mean()) * 100, 1) if len(has_lu) else None}}
    out["P1_首板含义_训练段"] = p1

    # ── P2 均线排布 ──────────────────────────────────────────────
    bull = (tr.close_price_tm1 > tr.ma5_tm1) & (tr.ma5_tm1 > tr.ma10_tm1) & (tr.ma10_tm1 > tr.ma20_tm1)
    bear = (tr.close_price_tm1 < tr.ma5_tm1) & (tr.ma5_tm1 < tr.ma10_tm1) & (tr.ma10_tm1 < tr.ma20_tm1)
    ma_spread = (pd.concat([tr.ma5_tm1, tr.ma10_tm1, tr.ma20_tm1], axis=1).max(axis=1)
                 / pd.concat([tr.ma5_tm1, tr.ma10_tm1, tr.ma20_tm1], axis=1).min(axis=1) - 1)
    twist = (~bull) & (~bear) & (ma_spread < 0.03)
    p2rows = []
    for label, m in [("多头排列(C>5>10>20)", bull), ("空头排列(C<5<10<20)", bear),
                     ("缠绕(离散<3%)", twist), ("其他", ~(bull | bear | twist))]:
        sub = tr[m.fillna(False)]
        p2rows.append({"排布": label, "n": len(sub),
                       "好票率%": round(float(sub.good.mean()) * 100, 1) if len(sub) else None,
                       "好票占比%": round(float(len(sub[sub.good])) / max(len(Gtr), 1) * 100, 1)})
    out["P2_均线排布_训练段"] = p2rows

    # ── P3 前期走势分箱好票率 ─────────────────────────────────────
    def bin_lift(col, bins, labels, mul=1):
        v = tr[col] * mul
        cat = pd.cut(v, bins, labels=labels)
        rows = []
        for lb, sub in tr.groupby(cat, observed=True):
            rows.append({"档": str(lb), "n": len(sub),
                         "好票率%": round(float(sub.good.mean()) * 100, 1)})
        return rows

    out["P3_分箱"] = {
        "ret5%": bin_lift("ret5_tm1", [-1, -0.10, -0.03, 0, 0.03, 0.10, 1], ["<-10", "-10~-3", "-3~0", "0~3", "3~10", ">10"]),
        "ret20%": bin_lift("ret20_tm1", [-1, -0.15, -0.05, 0, 0.05, 0.15, 1], ["<-15", "-15~-5", "-5~0", "0~5", "5~15", ">15"]),
        "ret60%": bin_lift("ret60_tm1", [-1, -0.20, -0.05, 0, 0.10, 0.30, 1], ["<-20", "-20~-5", "-5~0", "0~10", "10~30", ">30"]),
        "amp5%": bin_lift("amp5_tm1", [0, 0.02, 0.03, 0.04, 0.06, 1], ["<2", "2~3", "3~4", "4~6", ">6"]),
        "amp20%": bin_lift("amp20_tm1", [0, 0.025, 0.035, 0.05, 1], ["<2.5", "2.5~3.5", "3.5~5", ">5"]),
        "pos60": bin_lift("pos60", [-0.1, 0.1, 0.3, 0.5, 0.7, 0.9, 1.1], ["<0.1", "0.1~0.3", "0.3~0.5", "0.5~0.7", "0.7~0.9", ">0.9"]),
        "pos250": bin_lift("pos250", [-0.1, 0.1, 0.3, 0.5, 0.7, 0.9, 1.1], ["<0.1", "0.1~0.3", "0.3~0.5", "0.5~0.7", "0.7~0.9", ">0.9"]),
        "昨日量比": bin_lift("vol_ratio_tm1", [0, 0.7, 1.0, 1.5, 2.5, 100], ["<0.7", "0.7~1", "1~1.5", "1.5~2.5", ">2.5"]),
        "市值亿": bin_lift("cap_yi", [0, 30, 50, 80, 150, 300, 100000], ["<30", "30~50", "50~80", "80~150", "150~300", ">300"]),
        "价位": bin_lift("close_price_tm1", [0, 3, 5, 8, 12, 20, 10000], ["<3", "3~5", "5~8", "8~12", "12~20", ">20"]),
        "换手%": bin_lift("turnover_rate_tm1", [-1, 1, 2, 3, 5, 8, 15, 100], ["<1", "1~2", "2~3", "3~5", "5~8", "8~15", ">15"]),
    }

    # ── P4 昨涨分布直读(回答"0~5收阳"条件排除了多少好票) ───────────
    chg_bins = pd.cut(tr.change_pct_tm1, [-100, -5, -2, 0, 2, 5, 100],
                      labels=["<-5%", "-5~-2%", "-2~0%", "0~2%", "2~5%", ">5%"])
    rows = []
    for lb, sub in tr.groupby(chg_bins, observed=True):
        rows.append({"昨涨档": str(lb), "好票中占比%": round(float(sub.good.sum()) / max(Gtr.good.sum(), 1) * 100, 1),
                     "差票中占比%": round(float((~sub.good).sum()) / max(len(Btr), 1) * 100, 1),
                     "好票率%": round(float(sub.good.mean()) * 100, 1), "n": len(sub)})
    out["P4_昨涨分布"] = rows

    # ── P5 首板当日可观察量 ───────────────────────────────────────
    out["P5_首板当日"] = {
        "高开档": bin_lift("gap_open", [-1, 0, 0.02, 0.04, 0.07, 1], ["低开", "0~2", "2~4", "4~7", ">7"], 1),
        "首板量比": bin_lift("vol_ratio_T", [0, 1, 1.5, 2, 3, 5, 500], ["<1", "1~1.5", "1.5~2", "2~3", "3~5", ">5"]),
    }

    # ── P6 来回对比汇总(归纳关键条件) ─────────────────────────────
    checks = {
        "前10日无涨停": tr.lu_cnt10 == 0, "前20日无涨停": tr.lu_cnt20 == 0,
        "前60日无涨停": tr.lu_cnt60 == 0,
        "低位pos60<0.3": tr.pos60 < 0.3, "低位pos60<0.5": tr.pos60 < 0.5,
        "pos250<0.5": tr.pos250 < 0.5,
        "多头排列": bull, "空头排列": bear, "均线缠绕": twist,
        "昨涨<=0": tr.change_pct_tm1 <= 0, "昨涨0~5": tr.change_pct_tm1.between(0, 5),
        "昨涨|x|<2": tr.change_pct_tm1.abs() < 2,
        "ret60<0": tr.ret60_tm1 < 0, "ret60>10%": tr.ret60_tm1 > 0.10,
        "amp5<3%": tr.amp5_tm1 < 0.03, "amp5>4%": tr.amp5_tm1 > 0.04,
        "昨日缩量(<0.7)": tr.vol_ratio_tm1 < 0.7, "昨日放量(>1.5)": tr.vol_ratio_tm1 > 1.5,
        "市值<50": tr.cap_yi < 50, "价<8": tr.close_price_tm1 < 8,
        "换手3~8": tr.turnover_rate_tm1.between(3, 8),
        "昨低>MA20": tr.low_price_tm1 > tr.ma20_tm1,
        "收>MA20": tr.close_price_tm1 > tr.ma20_tm1,
        "收>MA60": tr.close_price_tm1 > tr.ma60_tm1,
    }
    rows = []
    for name, m in checks.items():
        m = m.fillna(False)
        g_in = float(tr.good[m].mean()) if m.sum() else np.nan      # P(好|条件)
        g_out = float(tr.good[~m].mean()) if (~m).sum() else np.nan
        p_in_good = float(m[Gtr.index].mean())                       # P(条件|好)
        p_in_bad = float(m[Btr.index].mean())                        # P(条件|差)
        rows.append({"条件": name, "P(条件|好)": round(p_in_good, 3), "P(条件|差)": round(p_in_bad, 3),
                     "lift": round(p_in_good / max(p_in_bad, 1e-9), 2),
                     "P(好|条件)%": round(g_in * 100, 1), "P(好|否)%": round(g_out * 100, 1),
                     "条件覆盖%": round(float(m.mean()) * 100, 1)})
    out["P6_归纳_训练段"] = sorted(rows, key=lambda r: -r["lift"])

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
