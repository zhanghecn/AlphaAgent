# -*- coding: utf-8 -*-
"""趋势弱转强(w2s)研究复跑/对账脚本 —— 池定义与回测口径的唯一研究侧事实源。

用法(容器内):
    docker exec -i vnpy-alphaagent-api-1 python 量化因子研究/低吸研究/scripts/w2s_replay.py anchors
    docker exec -i vnpy-alphaagent-api-1 python 量化因子研究/低吸研究/scripts/w2s_replay.py pool 2026-08-21
    docker exec -i vnpy-alphaagent-api-1 python 量化因子研究/低吸研究/scripts/w2s_replay.py cases

口径 = 趋势低吸研究-弱转强v2.md 定稿 v3.0(2026-08-25):
- 基本条件: 主板/非ST非退/上市>5日/前10个交易日内出现过≥2连板/昨日未涨停/昨日换手3%~60%
- 组划分: 最近一次≥2连板高度==2 → A组; >=4 且距连板末日>=3个交易日 → B组; ==3 删除不做
- A1: +昨日跌>3% +下影线<2% +(量比0.7~1.2 或 振幅>=12%) +换手8~20% +近20日涨幅<30%; +7%直接打
- A2: +昨日收阳 +上影线<2%(同花顺标准口径,收阳时=收盘距全日高点) +换手8~20% +近20日涨幅<30%;
  +9%限价直接打(准封板确认,封板率65%;封板确认入场已证伪不可执行——79%次日一字买不到)
- B:  +昨日跌>3% +下影线<2% +(量比0.7~1.2 或 振幅>=12%) +换手5~25%; +7%直接打
- 盘中规则: A1/A2 竞价0~+4% 过滤; 昨日大盘(主板非ST)涨停>110家停手
- 卖出: A2 买入日未封板→当日收盘卖(未封当日走); 封板及A1/B → T+1起首个未涨停日收盘卖,
  T+15仍未断板则T+15收盘卖
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

warnings.filterwarnings("ignore")
pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 100)

END = "2026-08-21"
START_BARS = "2023-03-28"
START_EVT = pd.Timestamp("2023-04-01")

RULES_VERSION = "w2s-v3.0"
A2_TRIGGER_PCT = 0.09

# ── 案例门禁(验收3): (名称, 信号日, 期望) ──
CASES = [
    ("平潭发展", "2025-10-22", "in_a1"),      # 入A1池, 次日+7%触发, 5连板
    ("晋拓股份", "2026-07-09", "out_any"),    # 换手61%超上限不入池
    ("汇嘉时代", "2023-10-31", "out_a1"),     # 量比1.64 出清确认不过
    ("厦门港务", "2025-12-12", "out_b"),      # 前段4板但回落仅1天
    ("荣盛发展", "2023-07-27", "out_any"),    # 误杀代表: 跌停收+量比1.33+换手22+底座67
    ("华正新材", "2026-08-06", "in_a2"),      # A2-v3 好票: 断板收阳+上影1.0, 次日+9%触发买, 封板+7.27%
    ("上工申贝", "2024-03-15", "out_a2"),     # 十字星收阴, 不满足「昨日收阳」
]


def build_events(eng):
    stocks = pd.read_sql("select vt_symbol, name from stocks", eng)
    stocks["code6"] = stocks["vt_symbol"].str[:6]

    def board_of(c):
        if c.startswith(("300", "301")):
            return "cyb"
        if c.startswith(("688", "689")):
            return "kcb"
        if c.startswith(("8", "4", "92")):
            return "bse"
        return "main"

    stocks["board"] = stocks["code6"].map(board_of)
    stocks["bad"] = stocks["name"].str.upper().str.contains("ST") | stocks["name"].str.contains("退")

    bars = pd.read_sql(
        "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, volume, turnover_rate "
        f"from stock_daily_bars where trade_date >= '{START_BARS}' and trade_date <= '{END}'",
        eng, parse_dates=["trade_date"])
    bars = bars.merge(stocks[["vt_symbol", "name", "board", "bad", "code6"]], on="vt_symbol", how="left")
    bars = bars[(bars["board"] == "main") & (~bars["bad"])].copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)
    bars["sid"], _ = pd.factorize(bars["vt_symbol"])
    g = bars.groupby("sid", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["pos"] = g.cumcount().astype("int32")
    bars["gap_days"] = g["trade_date"].diff().dt.days
    bars["limit_price"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig = bars["prev_close"].notna() & (bars["prev_close"] > 0) & (bars["pos"] >= 5)
    bars["is_lim"] = elig & ((bars["close_price"] - bars["limit_price"]).abs() <= 1e-6)
    ow = ((bars["open_price"] - bars["close_price"]).abs() <= 1e-6) & \
         ((bars["open_price"] - bars["high_price"]).abs() <= 1e-6) & \
         ((bars["open_price"] - bars["low_price"]).abs() <= 1e-6)
    bars["one_word"] = bars["is_lim"] & ow
    is_lim_i = bars["is_lim"].astype("int8")
    brk = (~bars["is_lim"]).groupby(bars["sid"], sort=False).cumsum()
    bars["streak"] = is_lim_i.groupby([bars["sid"], brk], sort=False).cumsum()
    bars["amp"] = (bars["high_price"] - bars["low_price"]) / bars["prev_close"]
    bars["chg"] = bars["close_price"] / bars["prev_close"] - 1
    bars["chg_d2"] = g["chg"].shift(1)  # 前日涨跌幅(v2.2)
    lo = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (lo - bars["low_price"]) / bars["prev_close"] * 100
    # v3.0 A2:同花顺标准上影线(最高-实体顶)/昨收 + 昨日收阳
    hi_oc = pd.concat([bars["open_price"], bars["close_price"]], axis=1).max(axis=1)
    bars["ushadow"] = (bars["high_price"] - hi_oc) / bars["prev_close"] * 100
    bars["yang"] = bars["close_price"] > bars["open_price"]
    bars["amp_pct"] = bars["amp"] * 100
    bars.drop(columns=["limit_price"], inplace=True)

    gc = g["close_price"]
    bars["ret20"] = gc.transform(lambda s: s / s.shift(20) - 1)
    bars["base20"] = bars["ret20"] * 100
    gv = g["volume"]
    bars["vol_ma5"] = gv.transform(lambda s: s.rolling(5, min_periods=3).mean())
    bars["vol_rel5"] = bars["volume"] / bars["vol_ma5"]

    gs = g["streak"]
    bars["s2max10"] = gs.transform(lambda s: s.rolling(10, min_periods=1).max())
    last2 = bars["pos"].where(bars["streak"] >= 2)
    bars["last2"] = last2.groupby(bars["sid"], sort=False).ffill()
    bars["gap2"] = bars["pos"] - bars["last2"]
    bars["last_streak"] = bars["streak"].where(bars["streak"] >= 2).groupby(bars["sid"], sort=False).ffill()
    # v2.1 位置条件:首板日收盘不得创 60 日新高(突破过顶不做)
    bars["h60pre"] = g["high_price"].transform(lambda s: s.rolling(60, min_periods=20).max().shift(1))
    bars["ss_pos"] = bars["last2"] - bars["last_streak"] + 1
    lk = (bars[["sid", "pos", "close_price", "h60pre"]]
          .rename(columns={"pos": "ss_pos", "close_price": "fb_close", "h60pre": "fb_h60"}))
    bars = bars.merge(lk, on=["sid", "ss_pos"], how="left")
    bars.sort_values(["sid", "trade_date"], inplace=True)
    bars.reset_index(drop=True, inplace=True)
    g = bars.groupby("sid", sort=False)  # merge 后刷新,供后续前向列对齐
    bars["brk60"] = bars["fb_close"] >= bars["fb_h60"] - 1e-9

    mkt = bars.groupby("trade_date", sort=False)["is_lim"].sum().rename("mkt_lim")
    bars = bars.merge(mkt, on="trade_date", how="left")

    for k in range(1, 16):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)
        bars[f"n{k}_gap"] = g["gap_days"].shift(-k)

    T = bars[(bars["trade_date"] >= START_EVT)
             & (bars["s2max10"] >= 2) & (bars["gap2"] >= 1) & (~bars["is_lim"])].copy()
    T = T[T["n1_close"].notna() & (T["n1_gap"] <= 10)].copy()
    pc1 = T["close_price"]
    T["reach7"] = (T["n1_high"] / pc1 - 1 >= 0.07) & (T["n1_low"] / pc1 - 1 <= 0.07)
    T["reach9"] = (T["n1_high"] / pc1 - 1 >= A2_TRIGGER_PCT) & (
        T["n1_low"] / pc1 - 1 <= A2_TRIGGER_PCT)
    T["seal"] = T["n1_is_lim"].fillna(False).astype(bool)
    T["open_g"] = T["n1_open"] / pc1 - 1
    T["n2_lim"] = T["n2_is_lim"].fillna(False).astype(bool)
    T["year"] = T["trade_date"].dt.strftime("%Y")
    return T


def split_groups(T):
    """基本条件 + 组划分 + 各组条件。返回 {group_key: 掩码}(事件池行级)。"""
    base = T["turnover_rate"].between(3, 60)
    grp_a = T["last_streak"] == 2
    grp_b = (T["last_streak"] >= 4) & (T["gap2"] >= 3)
    cc = T["vol_rel5"].between(0.7, 1.2) | (T["amp_pct"] >= 12)
    panic = (T["chg"] <= -0.03) & (T["lshadow"] < 2)
    return {
        "a1": base & grp_a & panic & cc & T["turnover_rate"].between(8, 20) & (T["base20"] < 30)
              & (~T["brk60"]) & (T["chg_d2"] < 0),
        "a2": base & grp_a & T["yang"] & (T["ushadow"] < 2)
              & T["turnover_rate"].between(8, 20) & (T["base20"] < 30),
        "b": base & grp_b & panic & cc & T["turnover_rate"].between(5, 25),
    }


def board_walk_ret(e, ep):
    """板留断走: n2..n15 首个未涨停日收盘卖; 全板则 n15 收盘。返回逐笔收益 Series。"""
    exit_px = pd.Series(np.nan, index=e.index)
    for k in range(2, 16):
        lim = e[f"n{k}_is_lim"].fillna(False).astype(bool)
        hit = exit_px.isna() & (~lim) & e[f"n{k}_close"].notna()
        exit_px[hit] = e.loc[hit, f"n{k}_close"]
    still = exit_px.isna() & e["n15_close"].notna()
    exit_px[still] = e.loc[still, "n15_close"]
    return exit_px / ep - 1


def trades_for(T, mask, group_key, auction=False, halt=False):
    """事件池行 → 成交明细(研究口径)。
    A1/B: reach7 触发, 买价=昨收×1.07;A2(v3): reach9 触发, 买价=昨收×1.09。
    卖出: A2 买入日未封板→当日收盘卖(未封当日走), 封板→板留断走;
    A1/B → T+1 起首个未涨停日收盘;T+15 兜底。返回 DataFrame。
    """
    e = T[mask].copy()
    if auction:
        e = e[e["open_g"].between(0.0, 0.04)]
    if halt:
        e = e[e["mkt_lim"] <= 110]
    if group_key == "a2":
        e = e[e["reach9"]]
        e["entry_price"] = e["close_price"] * (1 + A2_TRIGGER_PCT)
    else:
        e = e[e["reach7"]]
        e["entry_price"] = e["close_price"] * 1.07
    r1 = e["n2_close"] / e["entry_price"] - 1
    e["ret_d1"] = r1
    bw = board_walk_ret(e, e["entry_price"])
    if group_key == "a2":
        same_day = e["n1_close"] / e["entry_price"] - 1
        e["ret_exec"] = np.where(e["seal"], bw, same_day)  # 实际执行收益
        e["ret_bw"] = e["ret_exec"]
    else:
        e["ret_bw"] = bw
    e = e[e["ret_d1"].notna()].copy()
    e["sealed_d1"] = e["seal"]
    e["group"] = group_key
    return e


def stat_line(label, e):
    if len(e) == 0:
        print(f"{label:44s} n=0")
        return
    seal = e["sealed_d1"].mean() * 100
    r1 = e["ret_d1"]
    lian = e["n2_lim"].mean() * 100
    bw = e["ret_bw"].mean() * 100
    print(f"{label:44s} n={len(e):4d} 封{seal:4.0f}% D+1 {r1.mean()*100:+5.2f}%/{(r1>0).mean()*100:.0f}% 连{lian:3.0f}% 板留{bw:+5.2f}")


def cmd_anchors(eng):
    T = build_events(eng)
    groups = split_groups(T)
    print(f"规则版本 {RULES_VERSION}  事件池 {len(T)} 票日  {START_EVT.date()} ~ {END}")
    print("== 终版(无盘中规则) ==")
    final = {}
    for gk in ("a1", "a2", "b"):
        e = trades_for(T, groups[gk], gk)
        final[gk] = e
        stat_line(f"{gk.upper()} 终版", e)
    if len(final.get("a2", [])):
        print(f"A2 终版实际执行收益(未封当日卖/封板板留): "
              f"{final['a2']['ret_bw'].mean()*100:+.2f}%/{(final['a2']['ret_bw']>0).mean()*100:.0f}%")
    print("== 产品口径(A1/A2+竞价0~4+停手; B 仅停手) ==")
    prod = {}
    prod["a1"] = trades_for(T, groups["a1"], "a1", auction=True, halt=True)
    stat_line("A1 终版+竞价0~4+停手", prod["a1"])
    prod["a2"] = trades_for(T, groups["a2"], "a2", auction=True, halt=True)
    stat_line("A2 终版+竞价0~4+停手", prod["a2"])
    prod["b"] = trades_for(T, groups["b"], "b", halt=True)
    stat_line("B 终版+停手", prod["b"])
    print("== 分年(产品口径) ==")
    for gk in ("a1", "a2", "b"):
        e = prod[gk]
        by = e.groupby("year").agg(
            n=("ret_d1", "size"),
            ret=("ret_d1", lambda s: round(s.mean() * 100, 2)),
            win=("ret_d1", lambda s: round((s > 0).mean() * 100)),
        )
        print(gk.upper(), " ".join(f"{y}:{r.ret:+.1f}/{r.win:.0f}(n={r.n})" for y, r in by.iterrows()))
    print("== 月度(产品口径, 供回测页对照) ==")
    for gk in ("a1", "a2", "b"):
        e = prod[gk].copy()
        e["ym"] = e["trade_date"].dt.strftime("%Y-%m")
        by = e.groupby("ym").agg(n=("ret_d1", "size"), ret=("ret_d1", lambda s: round(s.mean() * 100, 2)))
        print(gk.upper(), by.to_string())


def cmd_pool(eng, day):
    T = build_events(eng)
    groups = split_groups(T)
    day_ts = pd.Timestamp(day)
    for gk in ("a1", "a2", "b"):
        sub = T[groups[gk] & (T["trade_date"] == day_ts)]
        print(f"== {day} {gk.upper()} 池 n={len(sub)} ==")
        cols = ["vt_symbol", "name", "chg", "lshadow", "ushadow", "yang", "vol_rel5", "amp_pct",
                "turnover_rate", "base20", "last_streak", "gap2", "mkt_lim"]
        print(sub[cols].to_string(index=False))


def cmd_cases(eng):
    T = build_events(eng)
    groups = split_groups(T)
    for name, day, expect in CASES:
        sub = T[(T["name"] == name) & (T["trade_date"] == day)]
        if len(sub) == 0:
            print(f"{name} {day}: 事件池外(当日不在T池)  期望 {expect}")
            continue
        row = sub.iloc[0]
        in_g = [gk.upper() for gk in ("a1", "a2", "b") if bool(groups[gk].loc[row.name])]
        print(f"{name} {day}: 入组={in_g or '无'} 期望 {expect} | "
              f"chg={row['chg']*100:.1f} 下影={row['lshadow']:.2f} 上影={row['ushadow']:.2f} "
              f"量比={row['vol_rel5']:.2f} 振幅={row['amp_pct']:.1f} 换手={row['turnover_rate']:.1f} "
              f"底座={row['base20']:.0f} 前段={row['last_streak']:.0f} 距末日={row['gap2']:.0f}")


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "anchors"
    if cmd == "anchors":
        cmd_anchors(eng)
    elif cmd == "pool":
        cmd_pool(eng, sys.argv[2])
    elif cmd == "cases":
        cmd_cases(eng)
    else:
        raise SystemExit(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    main()
