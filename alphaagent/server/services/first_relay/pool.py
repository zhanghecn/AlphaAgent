"""一接二 j12-v2.0 实时候选池与统一事件字段。

池为 data_date 恰好孤立首板的主板非 ST 票。T-1 盘后只做静态候选，
F3/F6/F9 的今开窗由竞价数据复核；F1~F10 任一命中即出手，同票同日复核去重。
公共日线与静态字段复用 high_relay.pool，入场价格复用 execution。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.first_relay import contracts, execution
from alphaagent.server.services.high_relay import pool as hpr_pool

logger = logging.getLogger(__name__)

_LOOKBACK_CAL_DAYS = 300   # ≈200 交易日, 覆盖 60日板史+h60+ma20+余量
LSHADOW_TH = 0.3           # 板型分类阈值(与研究一致)


def board_type_b1(o: float, h: float, l: float, c: float) -> str:
    """首板板型四分类(研究 board_type_b1 同口径)。"""
    if abs(o - c) <= 1e-6 and abs(o - h) <= 1e-6 and abs(o - l) <= 1e-6:
        return "一字"
    if abs(o - c) <= 1e-6 and abs(o - h) <= 1e-6:
        return "T字"
    lo = min(o, c)
    return "下影" if (lo - l) / (c / 1.10) * 100 >= LSHADOW_TH else "实体"


def tag_point(
    fields: Mapping[str, object],
    check_gate: bool = True,
) -> tuple[str, str, str | None, str | None, bool]:
    """按 F1~F10 顺序判定，返回 (主点, 级别, 回避, 今开窗, 是否出手)。

    check_gate=False 用于 T-1 盘后静态候选，只跳过规则自带的今开窗。
    若同时命中无窗规则，则不再需要今开窗；否则返回全部命中窗口的并集
    （相邻/重叠窗口合并，不相邻窗口用 | 连接）。
    """
    hits = contracts.match_points(fields, check_gate=check_gate)
    if not hits:
        return "—", "—", None, None, False
    gate = None
    if all(contracts.POINTS[rule_id]["gate"] is not None for rule_id in hits):
        intervals: list[tuple[float, float]] = sorted({
            contracts.POINTS[rule_id]["gate"] for rule_id in hits
        })  # type: ignore[assignment]
        merged: list[tuple[float, float]] = []
        for lo, hi in intervals:
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        gate = "|".join(f"{lo}_{hi}" for lo, hi in merged)
    return hits[0], "A", None, gate, True


def event_fields(
    bars: pd.DataFrame,
    ctx: dict[str, object],
    i_last: int,
) -> dict[str, object] | None:
    """生成首板事件的统一静态字段；i_last 为首板日 p1。

    bars 必须先过 hpr_pool.derive_daily，ctx 必须由同一批 bars 一次性 make_ctx。
    判定数值沿用研究口径：static_fields 已舍入的字段保持原值，其余不在判定前舍入。
    """
    static = hpr_pool.static_fields(ctx, i_last, 1)
    if static is None:
        return None
    rec = dict(static)
    p1, p2 = i_last, i_last - 1
    sid = int(bars["sid"].iat[p1])

    f2o = float(bars["open_price"].iat[p2])
    f2h = float(bars["high_price"].iat[p2])
    f2l = float(bars["low_price"].iat[p2])
    f2c = float(bars["close_price"].iat[p2])
    f2_prev = float(bars["prev_close"].iat[p2])
    f2_turn = float(bars["turnover_rate"].iat[p2])
    f2_h60 = bars["h60"].iat[p2]

    c5_i = p2 - 5
    if c5_i >= 0 and int(bars["sid"].iat[c5_i]) == sid:
        c5 = float(bars["close_price"].iat[c5_i])
        rec["pre5_pct"] = (f2c / c5 - 1) * 100 if c5 > 0 else None
    else:
        rec["pre5_pct"] = None
    rec["foundation_amplitude"] = (f2h - f2l) / f2_prev * 100 if f2_prev > 0 else np.nan
    rec["foundation_body"] = (f2c / f2o - 1) * 100 if f2o > 0 else np.nan
    rec["foundation_vol_rel5"] = float(bars["vol_rel5"].iat[p2])
    rec["foundation_turn"] = f2_turn

    p1o = float(bars["open_price"].iat[p1])
    p1h = float(bars["high_price"].iat[p1])
    p1l = float(bars["low_price"].iat[p1])
    p1c = float(bars["close_price"].iat[p1])
    p1_limit = float(bars["limit_price"].iat[p1])
    b1_turn = static.get("b1_turn")
    rec["b1_gap"] = (p1_limit - p1l) / f2c * 100
    rec["b1_vol_rel5"] = float(bars["vol_rel5"].iat[p1])
    rec["b1_turn_change"] = float(b1_turn) - f2_turn if b1_turn is not None else np.nan
    rec["b1_break60"] = bool(p1c > f2_h60) if pd.notna(f2_h60) else None
    rec["b1_type"] = board_type_b1(p1o, p1h, p1l, p1c)

    # 二板日执行价格：昨收是首板收盘，不是地基收盘。
    rec["prev_close"] = p1c
    rec["limit_price"] = execution.limit_10pct(p1c)
    rec["trigger_price"] = execution.trigger_9pct(p1c)

    # 现有看盘字段；chassis 所需的板史列由 compute_pool 预先补入。
    rec["dist_ma20"] = static.get("foundation_ma20_gap")
    lc60 = bars["lim_cnt60"].iat[p1] if "lim_cnt60" in bars else np.nan
    ms60 = bars["max_streak60"].iat[p1] if "max_streak60" in bars else np.nan
    rec["chassis"] = (
        "纯底盘" if lc60 == 0 else ("孤立板" if ms60 == 1 else "前波连板")
    ) if pd.notna(lc60) and pd.notna(ms60) else None
    rec["lim_cnt60"] = int(lc60) if pd.notna(lc60) else None
    rec["max_streak60"] = int(ms60) if pd.notna(ms60) else None
    return rec


def compute_pool(data_date: date) -> dict[str, object]:
    """data_date(首板日 T-1)收盘后计算 T 日综合候选池。"""
    engine = get_engine()
    universe = hpr_pool.load_universe(engine)
    name_map = universe.set_index("vt_symbol")["name"].to_dict()
    start = data_date - pd.Timedelta(days=_LOOKBACK_CAL_DAYS)
    bars = pd.read_sql(
        f"select vt_symbol, trade_date, open_price, high_price, low_price, close_price, "
        f"volume, turnover_rate from stock_daily_bars "
        f"where trade_date >= '{start}' and trade_date <= '{data_date}'",
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = hpr_pool.derive_daily(bars)

    # 板史仅用于 chassis/UI；最终规则字段统一由 event_fields 生成。
    lim_i = bars["is_lim"].astype("int8")
    bars["lim_cnt60"] = lim_i.groupby(bars["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).sum()).shift(1)
    bars["max_streak60"] = bars["streak"].groupby(bars["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).max()).shift(1)
    ctx = hpr_pool.make_ctx(bars)

    mkt_lim_tm1 = int(bars.loc[bars["trade_date"] == data_date, "is_lim"].sum())
    last = bars[bars["trade_date"] == pd.Timestamp(data_date)].copy()
    ev = last[last["streak"] == 1]
    entries: list[dict[str, object]] = []
    stats = {"pool": len(ev), "actionable": 0, "avoid": 0}
    stats.update({f"act_F{i}": 0 for i in range(1, 11)})
    actionable_symbols: set[str] = set()

    for i in ev.index.to_numpy():
        i = int(i)
        fields = event_fields(bars, ctx, i)
        if fields is None:
            continue
        vsym = str(bars["vt_symbol"].iat[i])
        point, level, avoid, gate, actionable = tag_point(fields, check_gate=False)
        hits = contracts.match_points(fields, check_gate=False)
        entry = dict(fields)
        entry.update({
            "vt_symbol": vsym,
            "name": str(name_map.get(vsym) or ""),
            "point": point,
            "level": level,
            "actionable": actionable,
            "avoid_static": avoid,
            "auction_gate": gate,
            "action_hint": contracts.POINTS[point]["hint"] if point in contracts.POINTS else None,
            "rule_ids": "+".join(hits) if hits else None,
            "bonus": "同中" + ",".join(hits[1:]) if len(hits) > 1 else None,
            "mkt_lim_tm1": mkt_lim_tm1,
        })
        entries.append(entry)
        if actionable:
            actionable_symbols.add(vsym)
            for rule_id in hits:
                stats[f"act_{rule_id}"] += 1

    stats["actionable"] = len(actionable_symbols)
    exec_date = hpr_pool.next_weekday(data_date)
    return {"exec_date": exec_date.isoformat(), "entries": entries,
            "filter_stats": stats, "mkt_lim_tm1": mkt_lim_tm1}
