"""U型补涨打板盘前池计算:全部条件来自 T-1 收盘数据(无未来函数)。

口径 = 量化因子研究/低吸研究/U型补涨打板.md 定稿(2026-08-30, 原趋势弱转强V4):
  触发池(四组基本条件):
    2板补涨阴: 前20日最大连板=2 + 昨收阴 + 昨幅>-9% + 昨上影<4% + 昨日未涨停
    2板补涨阳: 前20日最大连板=2 + 昨收阳 + 昨幅>-3% + 昨上影<4% + 昨日未涨停
    4+补涨阴:  前20日最大连板>=4 + 昨收阴 + 昨幅>-8% + 昨上影<4% + 昨日未涨停
    4+补涨阳:  前20日最大连板>=4 + 昨收阳 + 昨幅>-3% + 昨上影<4% + 昨日未涨停
  出手白名单(u_shape.actionable_of): 2板阴=U坑蹲类×弹回≤16%×坑宽6-15×未收顶上;
    2板阳=坑底首阳×未收顶上 或 坑中纠缠×下探中; 4+阴=孤板×全多头×U坑存在×剔中坑回顶;
    4+阳=2板小波穿插(夹层)。
  池=触发池全量(雷达)+actionable 出手标记; 盘中只对 actionable 票开买入触发。
  买入=板上买(触板买涨停价, 一字排除); 卖出=板留断走(T+1起首个未涨停日收盘)。
涨停判定与研究浮点口径一致(主板非ST:涨停价 = round(昨收×1.10+1e-9, 2),收盘等于即封板);
连板序列在本窗口内自建,与 stock_limit_up_daily(detector 口径)对主板非ST等价。
指数对齐:研究事件行=D0(触板日),本模块信号行=T-1(=研究D-1);
  mx20/均线在信号日无 shift(=研究 shift(1) 于 D0);坑宽 gap_d0=(信号日+1)-末板=研究 gap。
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.weak_to_strong import contracts, u_shape

SHANGHAI = ZoneInfo("Asia/Shanghai")
_LOOKBACK_CAL_DAYS = 130  # ≈90 个交易日,覆盖 ma30(30)+mx20(20)+段锚+余量


def latest_daily_date() -> date | None:
    """全市场日线最新交易日(数据基准日 T-1)。"""
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def next_weekday(day: date) -> date:
    """下一工作日(周一~周五)。节假日池会闲置,由下一真交易日的 EOD 重算覆盖。"""
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def derive_daily(bars: pd.DataFrame) -> pd.DataFrame:
    """日线派生列(pool/backtest 共用基础件;U模型部分在 u_shape 按候选行算)。"""
    bars = bars.copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)
    g = bars.groupby("vt_symbol", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["pos"] = g.cumcount()
    # 涨停判定:主板非ST 10%,与研究浮点口径一致;窗口内 pos>=5 才参与判定
    # (对齐研究"上市>5日"口径:对老股无影响,只挡窗口内新上市票的伪连板)
    limit_px = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig_lim = bars["prev_close"].notna() & (bars["prev_close"] > 0) & (bars["pos"] >= 5)
    bars["is_lim"] = elig_lim & ((bars["close_price"] - limit_px).abs() <= 1e-6)
    is_lim_i = bars["is_lim"].astype("int8")
    brk = (~bars["is_lim"]).groupby(bars["vt_symbol"], sort=False).cumsum()
    bars["streak"] = is_lim_i.groupby([bars["vt_symbol"], brk], sort=False).cumsum()
    bars["chg"] = (bars["close_price"] / bars["prev_close"] - 1) * 100
    high_oc = pd.concat([bars["open_price"], bars["close_price"]], axis=1).max(axis=1)
    bars["ushadow"] = (bars["high_price"] - high_oc) / bars["prev_close"] * 100
    bars["yang"] = bars["close_price"] > bars["open_price"]
    bars["yin"] = bars["close_price"] < bars["open_price"]
    # 前20日最大连板(信号日口径=研究 mx20: rolling(20) 无 shift 于 T-1 行)
    gs = g["streak"]
    bars["mx20"] = gs.transform(lambda s: s.rolling(contracts.MX_WINDOW, min_periods=1).max())
    return bars


def group_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    """四组基本条件布尔 mask(作用于信号日行;返回五组 key,yang2 两通道此处合并为 yang2*)。"""
    c = contracts
    common = (~df["is_lim"]) & (df["ushadow"] < c.USHADOW_MAX)
    return {
        "yin2": (common & (df["mx20"] == 2) & df["yin"] & (df["chg"] > c.YIN_CHG_MIN)),
        "yang2*": (common & (df["mx20"] == 2) & df["yang"] & (df["chg"] > c.YANG_CHG_MIN)),
        "yin4": (common & (df["mx20"] >= 4) & df["yin"] & (df["chg"] > c.YIN4_CHG_MIN)),
        "yang4": (common & (df["mx20"] >= 4) & df["yang"] & (df["chg"] > c.YANG_CHG_MIN)),
    }


def split_yang2_channel(f: dict) -> str:
    """2板阳触发按地基分道(显示桶): DN→坑底首阳通道, 其余→坑中纠缠通道。"""
    return u_shape.GROUP_YANG2A if f["base"] == "DN" else u_shape.GROUP_YANG2B


def compute_pool(data_date: date | None = None) -> dict[str, object]:
    """以 data_date(默认最新日线日)为 T-1 计算次日四组池(触发全量+出手标记)。

    返回 {data_date, exec_date, rules_version, mkt_lim_tm1, entries, filter_stats}。
    entries 每行含 group_key(五组)/actionable/prev_close/trigger_price(=limit_price)/
    limit_price 及 U 模型快照(base/pos3/low_dd/pull/reb/ma_st/n_lim_mid/topped/d23ok/seg_h)。
    """
    engine = get_engine()
    if data_date is None:
        data_date = latest_daily_date()
    if data_date is None:
        return {"data_date": None, "exec_date": None, "mkt_lim_tm1": None, "entries": [],
                "rules_version": contracts.W2S_RULES_VERSION,
                "filter_stats": {"error": "no_daily_bars"}}
    window_start = data_date - timedelta(days=_LOOKBACK_CAL_DAYS)

    bars = pd.read_sql(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
        ).where(schema.stock_daily_bars.c.trade_date >= window_start,
                schema.stock_daily_bars.c.trade_date <= data_date),
        engine,
    )
    stocks = pd.read_sql(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.name),
        engine,
    )
    stats: dict[str, int] = {"bars_rows": int(len(bars))}
    if bars.empty or stocks.empty:
        return {"data_date": data_date.isoformat(), "exec_date": None, "mkt_lim_tm1": None,
                "entries": [], "rules_version": contracts.W2S_RULES_VERSION,
                "filter_stats": {**stats, "error": "empty_source"}}

    eligible = stocks[stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)]
    stats["eligible_universe"] = int(len(eligible))
    name_map = eligible.set_index("vt_symbol")["name"]

    bars = bars[bars["vt_symbol"].isin(set(eligible["vt_symbol"]))].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars = derive_daily(bars)

    # 昨日大盘涨停家数(主板非ST宇宙,信息展示用;V4 无停手规则)
    mkt_lim = int(bars.loc[bars["trade_date"] == pd.Timestamp(data_date), "is_lim"].sum())
    stats["mkt_lim_tm1"] = mkt_lim

    last = bars.groupby("vt_symbol", sort=False).tail(1).copy()
    last = last[last["trade_date"] == pd.Timestamp(data_date)]
    stats["with_bars_on_date"] = int(len(last))

    masks = group_masks(last)
    hit = masks["yin2"] | masks["yang2*"] | masks["yin4"] | masks["yang4"]
    cand = last[hit]
    stats["trigger_pool"] = int(len(cand))

    # 候选股的 U 模型数组(u_features 按行算)
    arr_by: dict[str, dict[str, object]] = {}
    for vt, grp in bars[bars["vt_symbol"].isin(set(cand["vt_symbol"]))].groupby(
            "vt_symbol", sort=False):
        arr_by[str(vt)] = {
            "close": grp["close_price"].to_numpy(dtype=float),
            "high": grp["high_price"].to_numpy(dtype=float),
            "is_lim": grp["is_lim"].to_numpy(dtype=bool),
            "streak": grp["streak"].to_numpy(dtype=float),
        }

    entries: list[dict[str, object]] = []
    n_actionable = 0
    for row in cand.itertuples():
        vt = str(row.vt_symbol)
        arr = arr_by[vt]
        # bigtop 锚修正只对 4+组启用(研究口径: 2板组锚就是2板段, 不做大波重算)
        is4 = bool(masks["yin4"].loc[row.Index] or masks["yang4"].loc[row.Index])
        f = u_shape.u_features(arr["close"], arr["high"], arr["is_lim"],
                               arr["streak"], int(row.pos), bigtop=is4)
        if f is None:
            continue
        # 标注层: 真U结构识别(坑底前最高收盘为顶+topped时序)——只用于展示快照,
        # 出手判定仍用 f(定稿阈值按旧尺子校准, w2s_diag_truetop_final.py 实测换尺子摊薄)
        lab = u_shape.u_struct(arr["close"], arr["high"], arr["is_lim"],
                               arr["streak"], int(row.pos), bigtop=is4) or f
        if masks["yin2"].loc[row.Index]:
            group_key = u_shape.GROUP_YIN2
        elif masks["yin4"].loc[row.Index]:
            group_key = u_shape.GROUP_YIN4
        elif masks["yang4"].loc[row.Index]:
            group_key = u_shape.GROUP_YANG4
        else:  # 2板阳: 按地基分道到五组 key
            group_key = split_yang2_channel(f)
        actionable = u_shape.actionable_of(group_key, f)
        n_actionable += int(actionable)
        prev_close = float(row.close_price)
        limit_price = round(prev_close * 1.10 + 1e-9, 2)
        entries.append({
            "vt_symbol": vt,
            "group_key": group_key,
            "name": str(name_map.get(vt) or ""),
            "actionable": actionable,
            "prev_close": prev_close,
            "trigger_price": limit_price,   # 板上买: 触发价=涨停价
            "limit_price": limit_price,
            "chg_tm1": _f(row.chg),
            "ushadow_tm1": _f(row.ushadow),
            "yang_tm1": bool(row.yang),
            "base": lab["base"],
            "base_label": u_shape.BASE_NAME.get(lab["base"], lab["base"]),
            "pos3": lab["pos3"],
            "low_dd": _f(round(lab["low_dd"] * 100, 2)),
            "pull": _f(round(lab["pull"] * 100, 2)),
            "reb": _f(round(lab["reb"] * 100, 2)),
            "ma_st": f["ma_st"],
            "n_lim_mid": int(f["n_lim_mid"]),
            "topped": bool(lab["topped"]),
            "d23ok": bool(f["d23ok"]),
            "seg_h": int(f["seg_h"]),
            "gap_days": int(f["gap_d0"]),
            "mkt_lim_tm1": mkt_lim,
        })
    stats["actionable"] = n_actionable
    for gk in contracts.GROUP_KEYS:
        stats[f"pool_{gk}"] = sum(1 for e in entries if e["group_key"] == gk)
        stats[f"act_{gk}"] = sum(1 for e in entries
                                 if e["group_key"] == gk and e["actionable"])
    entries.sort(key=lambda e: (str(e["group_key"]), str(e["vt_symbol"])))
    return {
        "data_date": data_date.isoformat(),
        "exec_date": next_weekday(data_date).isoformat(),
        "rules_version": contracts.W2S_RULES_VERSION,
        "mkt_lim_tm1": mkt_lim,
        "entries": entries,
        "filter_stats": stats,
    }


def _f(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
