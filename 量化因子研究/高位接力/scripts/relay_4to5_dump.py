# -*- coding: utf-8 -*-
"""四进五 · P0 全量事件导出(容器内跑: docker exec -i vnpy-alphaagent-api-1 python < 本文件)。

stdout = 事件明细CSV(重定向到 量化因子研究/高位接力/四进五全量明细.csv), stderr = 日志。
事件口径与产品 backtest.build_events 逐字一致(streak_prev∈{2,3,4,5} & 触板 & 非一字,
2020-01 起), E3 退出逻辑逐字复刻(v6.4 D+2深开竞价卖/v6.5收盘价/v6.7一字跌停顺延);
static_fields 本就 n_board 通用(b1~bN 字段自动出)。
新增高度环境列: 昨日/当日涨停家数、昨日/当日全市场最高板、昨日4板+家数
(昨日口径 T-1 收盘可得可作判定;当日列仅诊断用)。
"""
import sys

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.high_relay import pool as pool_mod

BARS_START = "2019-06-01"      # 暖机(前波120/h60/ma30),与产品一致
EVENTS_START = pd.Timestamp("2020-01-01")
N_TARGETS = (2, 3, 4, 5)       # 昨日恰好N连板,今天打第N+1板
N_CN = {2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}   # 组名用汉字,与产品 group4 键一致
MAX_K = 15


def log(*a):
    print(*a, file=sys.stderr)


def main() -> None:
    engine = get_engine()
    universe = pool_mod.load_universe(engine)
    name_map = universe.set_index("vt_symbol")["name"].to_dict()
    log(f"宇宙票数 {len(universe)}")

    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price,
               schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.volume,
               schema.stock_daily_bars.c.turnover_rate)
        .where(schema.stock_daily_bars.c.trade_date >= pd.Timestamp(BARS_START)),
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = pool_mod.derive_daily(bars)
    log(f"bars {len(bars)} 行")

    g = bars.groupby("sid", sort=False)
    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    # 高度环境(全市场=宇宙内): 每日最高板 / 4板+家数(昨日口径可作判定,当日仅诊断)
    lim_rows = bars[bars["is_lim"]]
    day_top = lim_rows.groupby("trade_date")["streak"].max()
    day_ge4 = lim_rows[lim_rows["streak"] >= 4].groupby("trade_date").size()
    day_lim = bars.groupby("trade_date", sort=False)["is_lim"].sum()
    top_prev = day_top.shift(1)
    ge4_prev = day_ge4.shift(1)
    lim_prev = day_lim.shift(1)

    ev_mask = (bars["streak_prev"].isin(N_TARGETS) & bars["touch"]
               & (bars["trade_date"] >= EVENTS_START) & (~bars["one_word"]))
    ev = bars[ev_mask]
    ctx = pool_mod.make_ctx(bars)

    cols = {c: bars[c].to_numpy() for c in
            ["close_price", "open_price", "prev_close", "limit_price", "is_lim",
             "turnover_rate", "vol_rel5", "mkt_lim", "mkt_prev", "trade_date"]}
    rows: list[dict[str, object]] = []
    for i in ev.index.to_numpy():
        i = int(i)
        i_last = i - 1
        n_board = int(bars["streak"].iat[i_last])
        if n_board not in N_TARGETS:
            continue
        rec = pool_mod.static_fields(ctx, i_last, n_board)
        if rec is None:
            continue
        yang = bool(rec["foundation_yang"])
        td = pd.Timestamp(cols["trade_date"][i])
        buy = round(float(cols["limit_price"][i]), 2)
        buy_open = round((float(cols["open_price"][i])
                          / float(cols["prev_close"][i]) - 1) * 100, 2)
        sealed = bool(cols["is_lim"][i])
        n1c = bars["n1_close"].iat[i]
        n1o = bars["n1_open"].iat[i]
        # E0 持有到断板(与产品逐字一致)
        exit_e0, hold_days = np.nan, None
        exit_idx: int | None = None
        capped = False
        final_h = n_board + 1          # 最终高度(含买入日封住的延续)
        for k in range(1, MAX_K + 1):
            v = bars[f"n{k}_is_lim"].iat[i]
            c = bars[f"n{k}_close"].iat[i]
            if c != c:
                break
            if bool(v):
                final_h += 1
                continue
            if exit_e0 != exit_e0:
                exit_e0, hold_days = c, k
                exit_idx = i + k
            break
        if exit_e0 != exit_e0 and bars[f"n{MAX_K}_close"].iat[i] == bars[f"n{MAX_K}_close"].iat[i]:
            exit_e0, hold_days = bars[f"n{MAX_K}_close"].iat[i], MAX_K
            exit_idx = i + MAX_K
            capped = True
        unfinished = exit_e0 != exit_e0

        def _defer(k0: int, dn_close: float) -> tuple[float, int | None, str]:
            pc = dn_close
            for j in range(k0 + 1, MAX_K + 1):
                jo = float(bars[f"n{j}_open"].iat[i])
                if jo != jo:
                    break
                jh = float(bars[f"n{j}_high"].iat[i])
                jl = float(bars[f"n{j}_low"].iat[i])
                jc = float(bars[f"n{j}_close"].iat[i])
                if jo == jh == jl == jc and (jc / pc - 1) <= -0.095:
                    pc = jc
                    continue
                return float(jo), i + j, "limit_down_defer"
            return dn_close, i + k0, "limit_down_locked"

        if sealed:
            d2o = bars["n2_open"].iat[i]
            d1c = bars["n1_close"].iat[i]
            if (hold_days is not None and hold_days >= 2 and d2o == d2o
                    and d1c == d1c and (d2o / d1c - 1) <= -0.05):
                exit_e3, e3_date = float(d2o), i + 2
                e3_reason = "d2_deep_open_sell"
            elif hold_days is not None:
                exit_e3, e3_date = float(exit_e0), exit_idx
                e3_reason = ("next_close_fail" if hold_days == 1 else
                             ("max_hold_close" if capped else "break_close"))
                hd0 = int(hold_days)
                prev0 = (float(bars[f"n{hd0 - 1}_close"].iat[i]) if hd0 > 1
                         else float(bars["limit_price"].iat[i]))
                k0o = float(bars[f"n{hd0}_open"].iat[i])
                k0h = float(bars[f"n{hd0}_high"].iat[i])
                k0l = float(bars[f"n{hd0}_low"].iat[i])
                if (float(exit_e0) <= prev0 * 0.905 + 0.011
                        and k0o == k0h and k0h == k0l
                        and abs(k0o - float(exit_e0)) <= 0.011):
                    exit_e3, e3_date, e3_reason = _defer(hd0, float(exit_e0))
            else:
                exit_e3, e3_date, e3_reason = np.nan, None, None
        else:
            exit_e3, e3_date, e3_reason = np.nan, None, None
            prev_c = float(cols["close_price"][i])
            for k in range(1, MAX_K + 1):
                ko = float(bars[f"n{k}_open"].iat[i])
                kc = float(bars[f"n{k}_close"].iat[i])
                if kc != kc:
                    break
                kh = float(bars[f"n{k}_high"].iat[i])
                kl = float(bars[f"n{k}_low"].iat[i])
                locked = ko == kc == kh == kl and (kc / prev_c - 1) <= -0.095
                prev_c = kc
                if locked:
                    continue
                exit_e3 = float(kc)
                e3_date = i + k
                e3_reason = "break_day_close"
                break
        e3_exit_date = None
        if not unfinished and e3_date is not None:
            e3_exit_date = pd.Timestamp(bars["trade_date"].iat[e3_date]).date().isoformat()

        r: dict[str, object] = {
            "代码": str(bars["vt_symbol"].iat[i]),
            "名称": str(name_map.get(bars["vt_symbol"].iat[i]) or ""),
            "买入日": td.date().isoformat(),
            "组": f"{N_CN[n_board]}接{N_CN[n_board + 1]}",
            "四组": f"{N_CN[n_board]}接{N_CN[n_board + 1]}" + ("阳" if yang else "阴"),
            "N": n_board,
            "阴阳": "阳" if yang else "阴",
            "买价": buy,
            "买入开盘%": buy_open,
            "顶格": buy_open >= 9.5,
            "买入换手%": round(float(cols["turnover_rate"][i]), 2)
                        if cols["turnover_rate"][i] == cols["turnover_rate"][i] else None,
            "买入量比": round(float(cols["vol_rel5"][i]), 2)
                       if cols["vol_rel5"][i] == cols["vol_rel5"][i] else None,
            "封住": sealed,
            "次日开%": round((n1o / buy - 1) * 100, 2) if n1o == n1o else np.nan,
            "次日收%": round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan,
            "持有到断板%": round((exit_e0 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3%": round((exit_e3 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3原因": e3_reason if not unfinished else None,
            "E3退出日": e3_exit_date,
            "持有天数": hold_days,
            "最终高度": final_h,
            "未完": unfinished,
            "链": rec["chain"],
            "换手梯度": rec["turn_grad"],
            "地基涨跌%": rec["foundation_chg"],
            "地基阴阳": "阳" if yang else "阴",
            "地基姿态": rec.get("foundation_pose"),
            "地基距MA20%": rec.get("foundation_ma20_gap"),
            "距60日新高%": rec["dist_h60"],
            "均线": rec["ma_state"],
            "距MA10%": rec["dist_ma10"],
            "前板高度": rec["prior_height"],
            "前波60日最高板": rec["prev_wave60"],
            "前波120日最高板": rec["prev_wave120"],
            "锚位%": rec.get("anchor_pos"),
            "锚距": rec.get("anchor_dist"),
            "首3日涨幅%": rec.get("pre3_pct"),
            "首10日涨幅%": rec.get("pre10_pct"),
            "首20日涨幅%": rec.get("pre20_pct"),
            "昨日涨停家数": int(lim_prev.get(td, 0)) if pd.notna(lim_prev.get(td)) else None,
            "买入日涨停家数": int(cols["mkt_lim"][i]) if cols["mkt_lim"][i] == cols["mkt_lim"][i] else None,
            "昨日最高板": int(top_prev.get(td, 0)) if pd.notna(top_prev.get(td)) else None,
            "买入日最高板": int(day_top.get(td, 0)) if pd.notna(day_top.get(td)) else None,
            "昨日4板+家数": int(ge4_prev.get(td, 0)) if pd.notna(ge4_prev.get(td)) else None,
        }
        for k in range(1, n_board + 1):
            r[f"b{k}板型"] = rec.get(f"b{k}_type")
            r[f"b{k}开盘%"] = rec.get(f"b{k}_open")
            r[f"b{k}换手%"] = rec.get(f"b{k}_turn")
        rows.append(r)
    E = pd.DataFrame(rows)
    E["月"] = pd.Series([s[:7] for s in E["买入日"]])
    E["年"] = pd.Series([s[:4] for s in E["买入日"]])
    E.to_csv(sys.stdout, index=False)
    log(f"事件 {len(E)} 行 → stdout CSV")


main()
