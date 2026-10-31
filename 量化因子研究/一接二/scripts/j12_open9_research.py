# -*- coding: utf-8 -*-
"""一接二 +9% 可成交研究：入场价格与事件口径。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from alphaagent.server.services.first_relay.backtest import _e3_exit
from alphaagent.server.services.first_relay.pool import board_type_b1
from alphaagent.server.services.high_relay.pool import board_of, derive_daily, make_ctx, static_fields

START_EVT = pd.Timestamp("2021-01-01")
MAX_K = 15


def limit_10pct(prev_close: float) -> float:
    """主板涨停价：不复权昨收乘 1.10 后四舍五入到分。"""
    return round(prev_close * 1.10 + 1e-9, 2)


def trigger_9pct(prev_close: float) -> float:
    """严格高于昨收 +9% 的第一个可报价（最小价位 0.01 元）。"""
    return round(math.floor(prev_close * 109 + 1e-7) / 100 + 0.01, 2)


def open9_entry(open_price: float, high_price: float, prev_close: float) -> float | None:
    """开盘非涨停时，盘中首次突破 +9% 的假定成交价。"""
    if prev_close <= 0:
        return None
    if open_price >= limit_10pct(prev_close) - 1e-9:
        return None
    trigger = trigger_9pct(prev_close)
    if high_price + 1e-9 < trigger:
        return None
    return round(max(open_price, trigger), 2)


def _tail_exit(daily, i, sealed, exit_e0, hold_days, exit_idx, capped):
    """纯断板尾盘退出：不启用 D+2 深开竞价卖，跌停顺延与产品一致。"""
    if not sealed:
        return _e3_exit(daily, i, sealed, exit_e0, hold_days, exit_idx, capped)
    if hold_days is None:
        return np.nan, None, None
    reason = "next_close_fail" if hold_days == 1 else (
        "max_hold_close" if capped else "break_close")
    hd0 = int(hold_days)
    previous_close = float(daily[f"n{hd0 - 1}_close"].iat[i]) if hd0 > 1 \
        else float(daily["limit_price"].iat[i])
    day_open = float(daily[f"n{hd0}_open"].iat[i])
    day_high = float(daily[f"n{hd0}_high"].iat[i])
    day_low = float(daily[f"n{hd0}_low"].iat[i])
    if (float(exit_e0) <= previous_close * 0.905 + 0.011
            and day_open == day_high == day_low
            and abs(day_open - float(exit_e0)) <= 0.011):
        previous = float(exit_e0)
        for j in range(hd0 + 1, MAX_K + 1):
            next_open = float(daily[f"n{j}_open"].iat[i])
            if pd.isna(next_open):
                break
            next_high = float(daily[f"n{j}_high"].iat[i])
            next_low = float(daily[f"n{j}_low"].iat[i])
            next_close = float(daily[f"n{j}_close"].iat[i])
            if next_open == next_high == next_low == next_close \
                    and (next_close / previous - 1) <= -0.095:
                previous = next_close
                continue
            return next_open, i + j, "limit_down_defer"
        return float(exit_e0), exit_idx, "limit_down_locked"
    return float(exit_e0), exit_idx, reason


def build_events(
    bars: pd.DataFrame,
    name_map: dict[str, str] | None = None,
    cap_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    """从原始日线构建 +9% 触发事件，收益沿用产品 E3 退出。"""
    daily = derive_daily(bars)
    grouped = daily.groupby("sid", sort=False)
    future: dict[str, pd.Series] = {}
    source_fields = {
        "close": "close_price", "open": "open_price", "high": "high_price",
        "low": "low_price", "is_lim": "is_lim",
    }
    for k in range(1, MAX_K + 1):
        for field, source in source_fields.items():
            future[f"n{k}_{field}"] = grouped[source].shift(-k)
    daily = pd.concat([daily, pd.DataFrame(future, index=daily.index)], axis=1)

    close_group = daily.groupby("sid", sort=False)["close_price"]
    for n in (5, 15, 30, 40, 60):
        daily[f"c{n}"] = close_group.shift(n)
    lim_i = daily["is_lim"].astype("int8")
    for window in (60, 120):
        daily[f"lim_cnt{window}"] = lim_i.groupby(daily["sid"], sort=False).transform(
            lambda values, w=window: values.rolling(w, min_periods=20).sum()).shift(1)
        daily[f"max_streak{window}"] = daily["streak"].groupby(daily["sid"], sort=False).transform(
            lambda values, w=window: values.rolling(w, min_periods=20).max()).shift(1)
    ctx = make_ctx(daily)

    trigger = daily["prev_close"].map(
        lambda value: trigger_9pct(value) if pd.notna(value) and value > 0 else np.nan)
    event_mask = (
        daily["streak_prev"].eq(1)
        & daily["trade_date"].ge(START_EVT)
        & daily["high_price"].ge(trigger - 1e-9)
        & daily["open_price"].lt(daily["limit_price"] - 1e-9)
    )

    rows: list[dict[str, object]] = []
    for i in daily.index[event_mask].to_numpy():
        i = int(i)
        prev_close = float(daily["prev_close"].iat[i])
        entry = open9_entry(
            float(daily["open_price"].iat[i]),
            float(daily["high_price"].iat[i]),
            prev_close,
        )
        if entry is None:
            continue
        p1, p2 = i - 1, i - 2
        static = static_fields(ctx, p1, 1)
        if static is None:
            continue
        f2o = float(daily["open_price"].iat[p2])
        f2h = float(daily["high_price"].iat[p2])
        f2l = float(daily["low_price"].iat[p2])
        f2c = float(daily["close_price"].iat[p2])
        f2_prev = float(daily["prev_close"].iat[p2])
        f2_turn = float(daily["turnover_rate"].iat[p2])
        f2_volume = float(daily["volume"].iat[p2])
        f2_ma20 = float(daily["ma20"].iat[p2])
        p1o = float(daily["open_price"].iat[p1])
        p1h = float(daily["high_price"].iat[p1])
        p1l = float(daily["low_price"].iat[p1])
        p1c = float(daily["close_price"].iat[p1])
        p1_limit = float(daily["limit_price"].iat[p1])
        p1_volume = float(daily["volume"].iat[p1])
        b1_turn = static.get("b1_turn")
        lc60 = daily["lim_cnt60"].iat[p1]
        ms60 = daily["max_streak60"].iat[p1]
        chassis = None
        if pd.notna(lc60) and pd.notna(ms60):
            chassis = "纯底盘" if lc60 == 0 else ("孤立板" if ms60 == 1 else "前波连板")
        pre_extra: dict[str, float] = {}
        for n in (5, 15, 30, 40, 60):
            base = daily[f"c{n}"].iat[p2]
            pre_extra[f"pre{n}_pct"] = (f2c / base - 1) * 100 \
                if pd.notna(base) and base > 0 else np.nan
        ma_values = [daily[f"ma{n}"].iat[p2] for n in (5, 10, 20, 30)]
        ma_simple = "多头" if all(pd.notna(value) for value in ma_values) and \
            ma_values[0] > ma_values[1] > ma_values[2] > ma_values[3] else "乱"
        symbol = str(daily["vt_symbol"].iat[i])
        market_cap = (cap_map or {}).get(symbol)
        trade_date = pd.Timestamp(daily["trade_date"].iat[i])
        sealed = bool(daily["is_lim"].iat[i])
        exit_e0, hold_days, exit_idx, capped = np.nan, None, None, False
        if sealed:
            for k in range(1, MAX_K + 1):
                next_close = daily[f"n{k}_close"].iat[i]
                if pd.isna(next_close):
                    break
                if not bool(daily[f"n{k}_is_lim"].iat[i]):
                    exit_e0, hold_days, exit_idx = float(next_close), k, i + k
                    break
            if pd.isna(exit_e0) and pd.notna(daily[f"n{MAX_K}_close"].iat[i]):
                exit_e0 = float(daily[f"n{MAX_K}_close"].iat[i])
                hold_days, exit_idx, capped = MAX_K, i + MAX_K, True
        exit_price, exit_i, reason = _e3_exit(
            daily, i, sealed, exit_e0, hold_days, exit_idx, capped)
        tail_price, tail_i, tail_reason = _tail_exit(
            daily, i, sealed, exit_e0, hold_days, exit_idx, capped)
        second_turn = round(float(daily["turnover_rate"].iat[i]), 2)
        next_close = daily["n1_close"].iat[i]
        f2_h60 = daily["h60"].iat[p2]
        rows.append({
            **static,
            "vt_symbol": symbol,
            "name": (name_map or {}).get(symbol, symbol),
            "trade_date": trade_date,
            "year": int(trade_date.year),
            "month": trade_date.strftime("%Y-%m"),
            "segment": "主窗" if trade_date >= pd.Timestamp("2023-01-01") else "样本外",
            "prev_close": prev_close,
            "limit_price": float(daily["limit_price"].iat[i]),
            "trigger_price": trigger_9pct(prev_close),
            "entry_price": entry,
            "today_open": round((float(daily["open_price"].iat[i]) / prev_close - 1) * 100, 2),
            "second_close_pct": (float(daily["close_price"].iat[i]) / prev_close - 1) * 100,
            "second_vol_rel5": float(daily["vol_rel5"].iat[i]),
            "sealed": sealed,
            "touched_limit": bool(daily["touch"].iat[i]),
            "second_turn": second_turn,
            "good_board": sealed and second_turn < 12,
            "next_close_pct": (float(next_close) / entry - 1) * 100 if pd.notna(next_close) else np.nan,
            "exit_price": exit_price,
            "exit_date": pd.Timestamp(daily["trade_date"].iat[exit_i]) if exit_i is not None else pd.NaT,
            "exit_reason": reason,
            "hold_days": int(exit_i - i) if exit_i is not None else None,
            "e3_pct": (exit_price / entry - 1) * 100 if exit_i is not None else np.nan,
            "tail_exit_price": tail_price,
            "tail_exit_date": pd.Timestamp(daily["trade_date"].iat[tail_i]) if tail_i is not None else pd.NaT,
            "tail_exit_reason": tail_reason,
            "tail_hold_days": int(tail_i - i) if tail_i is not None else None,
            "tail_pct": (tail_price / entry - 1) * 100 if tail_i is not None else np.nan,
            "unfinished": tail_i is None or pd.isna(tail_price),
            "b1_type4": board_type_b1(p1o, p1h, p1l, p1c),
            "b1_gap": (p1_limit - p1l) / f2c * 100,
            "b1_amplitude": (p1h - p1l) / f2c * 100,
            "b1_body": (p1c / p1o - 1) * 100,
            "b1_lower_shadow": (min(p1o, p1c) - p1l) / f2c * 100,
            "b1_vol_rel5": float(daily["vol_rel5"].iat[p1]),
            "b1_volume_ratio": p1_volume / f2_volume if f2_volume > 0 else np.nan,
            "b1_turn_change": float(b1_turn) - f2_turn if b1_turn is not None else np.nan,
            "b1_turn_ratio": float(b1_turn) / f2_turn if b1_turn is not None and f2_turn > 0 else np.nan,
            "b1_break60": bool(p1c > f2_h60) if pd.notna(f2_h60) else None,
            "b1_ma20_gap": (p1c / f2_ma20 - 1) * 100 if pd.notna(f2_ma20) and f2_ma20 > 0 else np.nan,
            "foundation_open": (f2o / f2_prev - 1) * 100 if f2_prev > 0 else np.nan,
            "foundation_amplitude": (f2h - f2l) / f2_prev * 100 if f2_prev > 0 else np.nan,
            "foundation_body": (f2c / f2o - 1) * 100 if f2o > 0 else np.nan,
            "foundation_upper_shadow": (f2h - max(f2o, f2c)) / f2_prev * 100 if f2_prev > 0 else np.nan,
            "foundation_lower_shadow": (min(f2o, f2c) - f2l) / f2_prev * 100 if f2_prev > 0 else np.nan,
            "foundation_turn": f2_turn,
            "foundation_vol_rel5": float(daily["vol_rel5"].iat[p2]),
            "chassis": chassis,
            "lim_cnt60": int(lc60) if pd.notna(lc60) else None,
            "max_streak60": int(ms60) if pd.notna(ms60) else None,
            "lim_cnt120": int(daily["lim_cnt120"].iat[p1]) if pd.notna(daily["lim_cnt120"].iat[p1]) else None,
            "max_streak120": int(daily["max_streak120"].iat[p1]) if pd.notna(daily["max_streak120"].iat[p1]) else None,
            "ma_simple": ma_simple,
            "listing_age": int(daily["pos"].iat[p1]),
            "mkt_prev": int(daily["mkt_prev"].iat[i]) if pd.notna(daily["mkt_prev"].iat[i]) else None,
            "current_market_cap_yi": float(market_cap) / 1e8 if market_cap is not None and pd.notna(market_cap) else None,
            **pre_extra,
        })
    result = pd.DataFrame(rows)
    eligible = daily["streak_prev"].eq(1) & daily["trade_date"].ge(START_EVT)
    triggered = eligible & daily["high_price"].ge(trigger - 1e-9)
    open_limit = daily["open_price"].ge(daily["limit_price"] - 1e-9)
    result.attrs["audit"] = {
        "first_board_next_days": int(eligible.sum()),
        "triggered_before_open_filter": int(triggered.sum()),
        "open_limit_excluded": int((triggered & open_limit).sum()),
        "events_after_open_filter": int(event_mask.sum()),
        "built_events": int(len(result)),
    }
    return result


def main() -> None:
    """容器内只读重建：python /tmp/research/j12_open9_research.py。"""
    import json
    import os

    from sqlalchemy import create_engine, text

    output = os.environ.get("J12_OPEN9_OUT", "/tmp/research/j12_open9_out")
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        conn.execute(text("BEGIN TRANSACTION READ ONLY"))
        end = pd.read_sql("select max(trade_date)::text as end from stock_daily_bars", conn).iat[0, 0]
        stocks = pd.read_sql("select vt_symbol, name, market_cap from stocks", conn)
        stocks["code6"] = stocks["vt_symbol"].str[:6]
        stocks["board"] = stocks["code6"].map(board_of)
        names = stocks["name"].fillna("")
        bad = names.str.upper().str.contains("ST") | names.str.contains("退")
        universe = stocks[(stocks["board"] == "main") & ~bad].copy()
        symbols = universe["vt_symbol"].tolist()
        bars = pd.read_sql(
            text(
                "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, "
                "volume, turnover_rate from stock_daily_bars "
                "where trade_date >= '2020-06-01' and trade_date <= :end "
                "and vt_symbol = any(:symbols)"
            ),
            conn,
            params={"symbols": symbols, "end": end},
            parse_dates=["trade_date"],
        )
        conn.rollback()

    print(f"日线 2020-06-01~{end}，主板非ST {len(symbols)} 只，{len(bars)} 行")
    events = build_events(
        bars,
        name_map=universe.set_index("vt_symbol")["name"].to_dict(),
        cap_map=universe.set_index("vt_symbol")["market_cap"].to_dict(),
    )
    os.makedirs(output, exist_ok=True)
    events.to_csv(f"{output}/events.csv", index=False, encoding="utf-8-sig")
    done = events[~events["unfinished"]]
    metadata = {
        "data_end": end,
        "rows": len(events),
        "finished": len(done),
        "trade_start": str(events["trade_date"].min().date()),
        "trade_end": str(events["trade_date"].max().date()),
        "columns": events.columns.tolist(),
        **events.attrs["audit"],
    }
    with open(f"{output}/metadata.json", "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in metadata.items() if key != "columns"}, ensure_ascii=False))
    for segment, sub in done.groupby("segment"):
        print(
            f"{segment}: {len(sub)}笔 尾盘均值{sub['tail_pct'].mean():+.3f}% "
            f"胜{sub['tail_pct'].gt(0).mean() * 100:.1f}% 封板{sub['sealed'].mean() * 100:.1f}% "
            f"好板{sub['good_board'].mean() * 100:.1f}% 未触涨停{(~sub['touched_limit']).mean() * 100:.1f}%"
        )


if __name__ == "__main__":
    main()
