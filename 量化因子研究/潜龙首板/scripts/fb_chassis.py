"""底盘结构研究(用户主力框架的可计算验证): 建仓时间 × 涨停史形态.

可计算变量(全部 T-1 收盘前数据):
  trend_days   连续多头排列天数 (close>ma5>ma10>ma20)
  above20_days 连续站上MA20天数
  lu_cnt20/60  前20/60日涨停次数
  days_since_lu 距最近一次涨停天数
  since_lu_dd  最近一次涨停收盘 → 其后最低价 的最大回撤(洗盘深度)
  new_high20   T-1收盘创20日新高
  yang10       前10日阳线数, ret10 前10日涨幅

用户分类器:
  出货A 建仓过久: trend_days>=15
  出货B 回锅新高: 前20日有涨停 且 创20日新高
  好1 全新急建仓: 60日无涨停 且 trend_days<=10
  好2 洗盘后再起: 前20日有涨停 且 since_lu_dd<=-8% 且 不创新高
  好3 小阳建仓: 10日>=7阳 且 ret10<15% 且 前20日无涨停

结局: 好票(streak>=3 且 D+1盘中不埋人) / 真差票(D+1收<成本) / 闷杀(D+1<-5%) /
      D+1收盘均 / 长持口径(断板卖)每笔收益 / 逐月稳定性.
宇宙: 主板非ST 封住首板非一字 2023-01起, 剔D+1隔夜缺口>11%除权伪信号.
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
                      low_price, volume, change_pct
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
    derived = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["chg"] = bars["change_pct"].fillna(derived)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["ret10"] = g["close_price"].transform(lambda s: s / s.shift(10) - 1)
    bars["ret20"] = g["close_price"].transform(lambda s: s / s.shift(20) - 1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_m.set_index(["vt_symbol", "trade_date"])["is_limit_up"])\
        .fillna(False).astype(bool).values
    lu_prev = g["lu_T"].shift(1)
    bars["lu_cnt20"] = lu_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).sum())
    bars["lu_cnt60"] = lu_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(60, min_periods=1).sum())

    # 连续多头排列天数 / 连续站上MA20天数(截至当日, 取tm1用)
    bull = ((bars.close_price > bars.ma5) & (bars.ma5 > bars.ma10) & (bars.ma10 > bars.ma20)).fillna(False)
    above = (bars.close_price > bars.ma20).fillna(False)
    for name, cond in [("trend_days", bull), ("above20_days", above)]:
        run = cond.astype(int)
        seg_key = (~cond).cumsum()
        bars[name] = (run * run.groupby([bars.vt_symbol, seg_key]).cumsum()).clip(0, 40)

    # 上次涨停距今 + 上次涨停以来最深回撤
    bars["day_idx"] = g.cumcount()
    last_lu_day = bars["day_idx"].where(bars.lu_T).groupby(bars.vt_symbol).ffill()
    bars["days_since_lu"] = bars["day_idx"] - last_lu_day
    bars["lu_close"] = np.where(bars.lu_T, bars.close_price, np.nan)
    bars["last_lu_close"] = bars.groupby("vt_symbol")["lu_close"].ffill()
    lu_seg = bars.groupby("vt_symbol")["lu_T"].cumsum()
    bars["since_lu_low"] = bars.groupby([bars.vt_symbol, lu_seg])["low_price"].cummin()
    bars["since_lu_dd"] = bars["since_lu_low"] / bars["last_lu_close"] - 1

    bars["high20_prev"] = g["high_price"].transform(lambda s: s.rolling(20).max().shift(1))
    bars["yang"] = (bars.close_price > bars.open_price)
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())

    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["low_p1"] = g["low_price"].shift(-1)
    for k in (2, 3, 4, 5, 6, 7, 8):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "chg", "trend_days", "above20_days", "days_since_lu",
                "since_lu_dd", "ret10", "ret20", "yang10", "ma20"]:
        bars[col + "_tm1"] = g[col].shift(1)
    bars = bars.join(first, on=["vt_symbol", "trade_date"])
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    bars["new_high20"] = bars["close_price_tm1"] >= bars["high20_prev"] - 1e-9
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword"] = bars["low_price"] >= limit_px * 0.999

    ev = bars[bars["streak_h"].notna() & ~bars["oneword"]
              & (bars.trade_date >= "2023-01-01")].copy()
    ev["d1_open"] = ev["open_p1"] / ev["close_price"] - 1
    ev["d1_close"] = ev["close_p1"] / ev["close_price"] - 1
    ev["d1_low"] = ev["low_p1"] / ev["close_price"] - 1
    ev = ev[ev["d1_open"].abs() <= 0.11]
    # 长持口径 ret(断板日/次日开盘卖)
    k = ev["streak_h"].astype(int).clip(1, 8)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 9):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(k < 2, ev["open_p1"].values, eo)
    ev["ret_hold"] = pd.Series(eo / (ev["close_price"] * (1 + SLIP)) - 1, index=ev.index)
    ev = ev.dropna(subset=["d1_close", "d1_low", "vol_ratio", "close_price_tm1", "ret_hold"])
    ev["month"] = ev.trade_date.dt.to_period("M").astype(str)
    ev["good"] = (ev["streak_h"] >= 3) & (ev["d1_low"] >= -0.06)
    ev["bad"] = ev["d1_close"] < 0
    ev["bad5"] = ev["d1_close"] < -0.05
    ev["is_train"] = ev.trade_date < TRAIN_END

    def block(sub, label):
        if len(sub) < 30:
            return {"标签": label, "n": len(sub)}
        return {"标签": label, "n": len(sub),
                "好票率%": round(float(sub.good.mean()) * 100, 1),
                "真差票率%": round(float(sub.bad.mean()) * 100, 1),
                "闷杀率%": round(float(sub.bad5.mean()) * 100, 1),
                "D+1收盘均%": round(float(sub.d1_close.mean()) * 100, 2),
                "长持均%": round(float(sub.ret_hold.mean()) * 100, 2)}

    out = {"宇宙n": len(ev), "基线": block(ev, "全体")}

    # A 建仓时间分箱
    rows = []
    for lo, hi in [(0, 0), (1, 3), (4, 7), (8, 12), (13, 20), (21, 40)]:
        sub = ev[ev.trend_days_tm1.between(lo, hi)]
        rows.append(block(sub, f"多头排列{lo}~{hi}天"))
    out["A_建仓时间分箱"] = rows

    # B 回锅×新高 交叉
    rows = []
    for lu_lab, m1 in [("前20日无涨停", ev.lu_cnt20 == 0), ("1~2次", ev.lu_cnt20.between(1, 2)),
                       ("3次+", ev.lu_cnt20 >= 3)]:
        for nh_lab, m2 in [("不创新高", ~ev.new_high20), ("创20日新高", ev.new_high20)]:
            rows.append(block(ev[m1 & m2.fillna(False)], f"{lu_lab}×{nh_lab}"))
    out["B_回锅新高交叉"] = rows

    # C 洗盘深度分箱(仅有涨停史 60日内)
    has_lu = ev.days_since_lu_tm1.notna() & (ev.days_since_lu_tm1 <= 60)
    rows = []
    for lo, hi, lab in [(-0.001, 1, "几乎没回(>-0.1%)"), (-0.05, -0.001, "浅回0~5%"),
                        (-0.10, -0.05, "回5~10%"), (-0.20, -0.10, "回10~20%"), (-1, -0.20, "深回>20%")]:
        sub = ev[has_lu & ev.since_lu_dd_tm1.between(lo, hi)]
        rows.append(block(sub, f"涨停后{lab}"))
    out["C_洗盘深度(有涨停史)"] = rows

    # D 用户底盘分类器
    cls = {
        "出货A_建仓过久(多头>=15天)": ev.trend_days_tm1 >= 15,
        "出货A'_建仓过久(多头>=20天)": ev.trend_days_tm1 >= 20,
        "出货B_回锅创新高": (ev.lu_cnt20 >= 1) & ev.new_high20.fillna(False),
        "好1_全新急建仓(60日无板+多头<=10天)": (ev.lu_cnt60 == 0) & (ev.trend_days_tm1 <= 10),
        "好2_洗盘后再起(20日有板+深回8%+不创新高)": (
            (ev.lu_cnt20 >= 1) & (ev.since_lu_dd_tm1 <= -0.08) & ~ev.new_high20.fillna(False)),
        "好3_小阳建仓(10日7阳+涨幅<15%+无板)": (
            (ev.yang10_tm1 >= 7) & (ev.ret10_tm1 < 0.15) & (ev.lu_cnt20 == 0)),
    }
    out["D_底盘分类器"] = [block(ev[m.fillna(False)], name) for name, m in cls.items()]

    # E 组合: 可做(好1|好2|好3) vs 禁做(出货A|出货B) —— 长持口径逐月
    do = (cls["好1_全新急建仓(60日无板+多头<=10天)"] | cls["好2_洗盘后再起(20日有板+深回8%+不创新高)"]
          | cls["好3_小阳建仓(10日7阳+涨幅<15%+无板)"]).fillna(False)
    dont = (cls["出货A_建仓过久(多头>=15天)"] | cls["出货B_回锅创新高"]).fillna(False)
    for name, m in [("可做(好1|2|3)", do), ("禁做(出货A|B)", dont),
                    ("既不也不(中间地带)", ~do & ~dont)]:
        sub = ev[m]
        rec = block(sub, name)
        if len(sub) >= 30:
            mm = sub.groupby("month")["ret_hold"].agg(["count", "mean"])
            rec["正月占比_长持"] = round(float((mm["mean"] > 0).mean()), 3)
            rec["训长持均%"] = round(float(sub.loc[sub.is_train, "ret_hold"].mean()) * 100, 2)
            rec["验长持均%"] = round(float(sub.loc[~sub.is_train, "ret_hold"].mean()) * 100, 2)
            rec["负月"] = {str(ix): round(float(rr["mean"]) * 100, 2)
                          for ix, rr in mm.iterrows() if rr["mean"] <= 0}
        out.setdefault("E_组合", []).append(rec)

    # F 好票在其内的分布校验: 用户框架的可做集合覆盖了多少好票
    G = ev[ev.good]
    out["F_好票覆盖"] = {"好票n": len(G),
                       "落入可做集合%": round(float(do[G.index].mean()) * 100, 1),
                       "落入禁做集合%": round(float(dont[G.index].mean()) * 100, 1),
                       "差票落入禁做%": round(float(dont[ev.bad].mean()) * 100, 1),
                       "全体落入禁做%": round(float(dont.mean()) * 100, 1)}

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
