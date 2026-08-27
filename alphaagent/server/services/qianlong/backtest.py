"""潜龙首板回测引擎(v8.0 纯净版):日线口径全量回放 + 三槽模拟仓 + 物化报告。

v8.0(2026-08-27):买入决策彻底移除收盘信息——「收盘量比<1.5」过滤删除,
入场=盘中触及价×1.005。数字比历史版本难看是特性:先暴露真实期望,
优化(分钟收住确认/时段分层)为后续课题。
- 池 = 底盘形态 A|B,全部由 T-1 收盘数据构成(无未来)
- 触发 = 当日最高价曾达到 昨收×1.08(盘中事实);高开≥8% 用开盘价判(盘时可判)
- 一字板 = 开盘即顶格近似(盘时可判)
- 入场 = 触及价 ×1.005(不使用任何当日收盘后才知的信息)
- 卖出:未封板/未连板 → 次日开盘;连板 → 断板日开盘(逐日演化,无未来)
- 已删:收盘量比准入(未来函数)、|隔夜缺口|>11% 除权剔除(按结局丢样本)、
  全天最低价一字判定(未来信息)
模拟仓:3 槽位,B 类优先,退出日确认盈亏;当月 -5% 熔断停开。
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time as dt_time, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.qianlong import contracts

logger = logging.getLogger(__name__)
TRAIN_END = pd.Timestamp("2025-07-01")
REPLAY_START = "2023-01-01"
MIN_FRESH_SPOT_SYMBOLS = 3000  # 与 live_scan 相同的新鲜度门槛,防节假日假信号
SPOT_VOLUME_PER_LOT = 100.0    # 现货快照 volume=股 → 日线库单位为手
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _append_spot_synthetic_today(
    bars: pd.DataFrame,
    *,
    main_symbols: set[str],
    today: date,
    now: datetime | None = None,
) -> pd.DataFrame:
    """补一根「今日开盘」合成尾行,让昨日信号当日即可定版(不入库)。

    昨日入场信号的退出价 = 今日开盘价;该价格 09:25 集合竞价即定格且
    不再变化(无未来函数),但日线表要 EOD 才写入。这里从现货快照取今开
    拼出最后一根 bar,使 date_p1/open_p1 在日间重算时依然存在——昨日
    的交割单无需等到晚间。快照新鲜度以「拉取发生于当日 A 股交易时段」
    为锚(新浪 ticktime 在午休/盘后可能只含时间不带日期,行级日期不可
    靠);非交易时段、EOD 后已有今日日线、或源异常时静默跳过,回测退回
    原口径。今日合成行自身因缺少 T+1 数据不会成为新事件(dropna(ret)
    剔除),不影响任何历史值。
    """

    now = now or datetime.now(SHANGHAI_TZ)
    latest_date = pd.to_datetime(bars["trade_date"]).max()
    if (
        latest_date is None
        or latest_date.date() >= today
        or now.weekday() >= 5
        or now.date() != today
        or not (dt_time(9, 30) <= now.timetz().replace(tzinfo=None) <= dt_time(15, 1))
    ):
        return bars
    try:
        from alphaagent.data_sources.akshare_adapter import AkShareAdapter

        snapshot = AkShareAdapter().all_stock_ohlcv_spot()
        items = [it for it in (snapshot.get("items") or []) if isinstance(it, dict)]
        fresh = [
            it for it in items
            if str(it.get("vt_symbol") or "") in main_symbols
            and (_number(it.get("volume")) or 0.0) > 0
            and _open_of(it) is not None
        ]
    except Exception as exc:  # noqa: BLE001 — 预览增强失败不得拖垮回测主流程
        logger.warning("spot synthetic tail skipped: %s", exc)
        return bars
    if len(fresh) < MIN_FRESH_SPOT_SYMBOLS:
        logger.info("spot synthetic tail skipped: only %d fresh rows", len(fresh))
        return bars
    tails = [
        {
            "vt_symbol": str(it["vt_symbol"]),
            "trade_date": today,
            "open_price": open_price,
            "high_price": open_price,
            "low_price": open_price,
            "close_price": open_price,
            "volume": (_number(it.get("volume")) or 0.0) / SPOT_VOLUME_PER_LOT,
            "turnover_rate": None,
            "change_pct": None,
        }
        for it in fresh
        for open_price in (_open_of(it),)
    ]
    logger.info("spot synthetic tail appended: %d rows for %s", len(tails), today)
    return pd.concat([bars, pd.DataFrame(tails)], ignore_index=True)


def _open_of(item: dict[str, object]) -> float | None:
    try:
        value = float(item.get("open_price"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None


def build_events() -> pd.DataFrame:
    """全量回放事件表(含全部特征列)。

    run_backtest() 的物化报告与 量化因子研究/潜龙首板/scripts/ 下的分析脚本
    共用同一口径来源——分析脚本不得复制本函数逻辑,避免口径漂移。
    """
    engine = get_engine()
    stocks = pd.read_sql(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.symbol,
               schema.stocks.c.name, schema.stocks.c.market_cap), engine)
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price, schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.high_price, schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.volume,
               schema.stock_daily_bars.c.turnover_rate, schema.stock_daily_bars.c.change_pct)
        .where(schema.stock_daily_bars.c.trade_date >= date(2022, 1, 1)), engine)
    lu = pd.read_sql(
        select(schema.stock_limit_up_daily.c.vt_symbol,
               schema.stock_limit_up_daily.c.trade_date,
               schema.stock_limit_up_daily.c.is_limit_up,
               schema.stock_limit_up_daily.c.limit_up_count)
        .where(schema.stock_limit_up_daily.c.is_limit_up.is_(True)), engine)

    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    main_syms = set(main["vt_symbol"])
    cap_map = (main.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()
    name_map = main.set_index("vt_symbol")["name"].to_dict()

    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars = _append_spot_synthetic_today(
        bars, main_symbols=main_syms, today=date.today())
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    lu = lu[lu.vt_symbol.isin(main_syms)].copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu_key = lu.set_index(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    bars["ma5"] = g["close_price"].transform(lambda s: s.rolling(5).mean())
    bars["ma10"] = g["close_price"].transform(lambda s: s.rolling(10).mean())
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret10"] = g["close_price"].transform(lambda s: s / s.shift(10) - 1)
    bars["vol_ma5_prev"] = g["volume"].transform(lambda s: s.rolling(5).mean().shift(1))
    bars["yang"] = bars["close_price"] > bars["open_price"]
    bars["yang10"] = g["yang"].transform(lambda s: s.rolling(10, min_periods=5).sum())
    # 连续多头排列天数(收>MA5>MA10>MA20)
    bull = ((bars["close_price"] > bars["ma5"]) & (bars["ma5"] > bars["ma10"])
            & (bars["ma10"] > bars["ma20"])).fillna(False)
    run = bull.astype(int)
    bars["trend_days"] = run * run.groupby([bars["vt_symbol"], (~bull).cumsum()]).cumsum()
    # change_pct 列存在约 20 个交易日的历史缺口;用收盘对收盘推导值回填。
    derived_chg = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived_chg)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    bars["date_p1"] = g["trade_date"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
        bars[f"date_p{k}"] = g["trade_date"].shift(-k)
    for col in ["close_price", "low_price", "high_price", "open_price", "turnover_rate",
                "change_pct", "ma20", "trend_days", "yang10", "ret10"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    lu_prev = g["lu_T"].shift(1)
    bars["lu_cnt20"] = lu_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(20, min_periods=1).sum())
    bars["lu_cnt60"] = lu_prev.groupby(bars.vt_symbol).transform(
        lambda s: s.rolling(60, min_periods=1).sum())

    lu_all = lu.sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    first = (lu_all[lu_all.limit_up_count == 1][["vt_symbol", "trade_date", "streak_h"]]
             .set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first, on=["vt_symbol", "trade_date"])

    c = contracts
    bars["trigger_price"] = bars["close_price_tm1"] * (1 + c.TRIGGER_PCT)
    # 触发是盘中事实:当日最高价曾达到 +8%(在哪一刻触及不需要知道)
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    # v8.0 入场=盘中触及价(冲高时刻可成交的价格),买入决策不使用任何
    # 当日收盘后才知的信息;高开分支为防御(GAP_SKIP 已剔高开≥8%)。
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"],
                             bars["open_price"], bars["trigger_price"]) * (1 + c.ENTRY_SLIPPAGE)
    bars["sealed"] = bars["lu_T"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    # 一字板改用开盘即顶格近似(盘时可判):原全天 low>=涨停价 也属未来信息
    bars["oneword_strict"] = bars["open_price"] >= limit_px * 0.999

    # 近5日(T-5..T-1)最大单日涨幅%(v6.2 A 类池条件;窗口不满为 NaN→剔除)
    bars["maxchg5_tm1"] = g["change_pct"].transform(
        lambda s: s.rolling(5).max().shift(1))
    # v6 底盘池: A 全新急建仓(近60日无涨停 且 多头排列≤10天 且 昨日涨幅>-6% 且
    #            近5日单日涨幅均<+7%——v6.2 把 v6.1 单日上界扩成 5 日窗口,蕴含昨日<+7)
    #            B 小阳建仓(近10日≥7阳 且 10日涨幅<15% 且 近20日无涨停)
    cond_a = ((bars["lu_cnt60"] <= c.CHASSIS_A_LU60_MAX)
              & (bars["trend_days_tm1"] <= c.CHASSIS_A_TREND_DAYS_MAX)
              & (bars["change_pct_tm1"] > c.CHASSIS_A_D1_CHG_MIN)
              & (bars["maxchg5_tm1"] < c.CHASSIS_A_MAXCHG5_MAX))
    cond_b = ((bars["yang10_tm1"] >= c.CHASSIS_B_YANG10_MIN)
              & (bars["ret10_tm1"] < c.CHASSIS_B_RET10_MAX)
              & (bars["lu_cnt20"] <= c.CHASSIS_B_LU20_MAX))
    bars["chassis_tag"] = ""
    bars.loc[cond_a & cond_b, "chassis_tag"] = "AB"
    bars.loc[cond_a & ~cond_b, "chassis_tag"] = "A"
    bars.loc[~cond_a & cond_b, "chassis_tag"] = "B"
    bars["vol_ratio"] = bars["volume"] / bars["vol_ma5_prev"]
    # 分析专用特征(只供研究脚本,不参与任何池/触发过滤):
    # T-1 量比、T-1 振幅、T-1 收盘在 60 日区间位置、近 5 日涨幅(T-1 截断)
    ga = bars.groupby("vt_symbol", sort=False)
    bars["vol_ratio_tm1"] = ga["vol_ratio"].shift(1)
    bars["amp_tm1"] = bars["high_price_tm1"] / bars["low_price_tm1"] - 1
    hi60 = ga["close_price"].transform(lambda s: s.rolling(60, min_periods=20).max().shift(1))
    lo60 = ga["close_price"].transform(lambda s: s.rolling(60, min_periods=20).min().shift(1))
    bars["pos60_tm1"] = (bars["close_price_tm1"] - lo60) / (hi60 - lo60)
    bars["ret5_tm1"] = ga["close_price"].transform(lambda s: (s / s.shift(5) - 1).shift(1))
    # 近5日 ≥7% 大阳次数、距最近一次 ≥7% 大阳的交易日数(1=T-1)
    bars["bigcnt7_5tm1"] = (bars["change_pct"] >= 7).groupby(
        bars["vt_symbol"], sort=False).transform(lambda s: s.rolling(5).sum().shift(1))
    # 近10日上涨天数(涨幅>0, 同花顺「上涨天数」口径; 区别于阳线数 yang10)
    bars["up10_tm1"] = (bars["change_pct"] > 0).groupby(
        bars["vt_symbol"], sort=False).transform(
        lambda s: s.rolling(10, min_periods=5).sum().shift(1))
    day_no = ga.cumcount() + 1
    last_big_day = day_no.where(bars["change_pct"] >= 7).groupby(
        bars["vt_symbol"], sort=False).ffill()
    bars["lastbig7_off_tm1"] = (day_no - last_big_day).groupby(
        bars["vt_symbol"], sort=False).shift(1)
    # v8.0:删除收盘量比过滤——收盘信息不得参与入场决策(未来函数)。
    # 盘中量比读数对单笔收益无判别力(分钟实验 rho≈0),优化(分钟收住确认/时段)
    # 属后续课题;当前口径先如实暴露无过滤的原始期望。
    pool = (~bars["lu_tm1"]) & (cond_a | cond_b)
    ev = bars[(bars.trade_date >= REPLAY_START) & bars["triggered"] & pool
              & ~bars["oneword_strict"]
              & (bars["gap_open"] < c.GAP_SKIP)].copy()
    k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
    eo = np.full(len(ev), np.nan)
    for kk in range(2, 7):
        eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
    eo = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, eo)
    ev["exit_px"] = pd.Series(eo, index=ev.index)
    ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
    ev["streak_k"] = k.values
    exit_date = ev["date_p1"].values.copy()
    for kk in range(2, 7):
        exit_date = np.where((k == kk).values, ev[f"date_p{kk}"].values, exit_date)
    exit_date = np.where(~ev["sealed"] | (k < 2), ev["date_p1"].values, exit_date)
    ev["exit_date"] = pd.to_datetime(pd.Series(exit_date, index=ev.index))
    # v7.0 移除「|隔夜缺口|>11% 除权伪触发」事后剔除:它按持有结局丢弃样本,
    # 属于翻看答案式前视。除权污染改为已知风险(日线未复权),见 RISK_NOTES。
    ev["month"] = ev["trade_date"].dt.to_period("M").astype(str)
    ev["is_train"] = ev.trade_date < TRAIN_END
    ev["name"] = ev.vt_symbol.map(name_map)
    ev["priority"] = ev["chassis_tag"].isin(["B", "AB"])  # 小阳建仓(B类)优先
    ev = ev.dropna(subset=["ret"])
    return ev


def run_backtest() -> dict[str, object]:
    """全量回放并返回物化 payload(不写库,由调用方持久化)。"""
    c = contracts
    ev = build_events()

    payload = {
        "rules_version": c.QIANLONG_RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": {
            "from": ev.trade_date.min().date().isoformat(),
            "to": ev.trade_date.max().date().isoformat(),
            "months": int(ev["month"].nunique()),
        },
        "caliber": ("v8.0 纯净口径:池=T-1底盘形态;事件=当日盘中曾触及+8%;"
                    "入场=触及价×1.005,买入决策不使用任何当日收盘后才知的信息"
                    "(收盘量比准入已作为未来函数删除,数字如实偏弱);"
                    "一字板按开盘即顶格判定;高开≥8%不做;"
                    "卖出:未封/未连板次日开盘,连板断板日开盘(逐日决策)。"
                    "日线未复权,除权污染为已知残留风险。"),
        "summary": _stats(ev),
        "chassis_a_subset": _stats(ev[ev["chassis_tag"].isin(["A", "AB"])]),
        "chassis_b_subset": _stats(ev[ev["chassis_tag"].isin(["B", "AB"])]),
        "chassis_ab_subset": _stats(ev[ev["chassis_tag"] == "AB"]),
        "segments": {
            "train_202301_202506": _stats(ev[ev["is_train"]]),
            "valid_202507_now": _stats(ev[~ev["is_train"]]),
            "ex_202409": _stats(ev[ev.month != "2024-09"]),
        },
        "monthly": _monthly_rows(ev),
        "anchors": c.BACKTEST_ANCHORS,
        "anchor_check": _anchor_check(ev),
    }
    sim = _slot_simulation(ev)
    payload["ledger_days"] = _ledger_days(ev)
    payload["simulation"] = sim
    return payload


def _stats(df: pd.DataFrame) -> dict[str, object]:
    # 小样本(n=1~4)同样返回均值:不藏"--"(含亏损月,如 2023-01 n=1)
    r = df["ret"].dropna()
    if len(r) == 0:
        return {"n": 0}
    return {
        "n": int(len(r)),
        "avg_pct": round(float(r.mean()) * 100, 2),
        "median_pct": round(float(r.median()) * 100, 2),
        "win": round(float((r > 0).mean()), 3),
        "seal": round(float(df["sealed"].mean()), 3),
        "streak2": round(float((df["streak_k"] >= 2).mean()), 3),
    }


def _monthly_rows(ev: pd.DataFrame) -> list[dict[str, object]]:
    """月度明细:等权统计 + 月收益(精确式)。

    月收益口径 = 每个有信号的交易日赚一次「当日全部信号等权均值」,按信号日加总
    (全部信号都算买上、每日本金重置、非复利)。不能用「月均每笔×交易日数」近似:
    信号在日间分布不均时偏差平均 17.8pct/最大 74.6pct(2023-01 会算出 -78% 虚构值)。
    signal_days = 当月有信号的天数(无信号日贡献 0,不入计数)。
    """
    daily_mean = ev.groupby([ev["month"], ev["trade_date"].dt.date])["ret"].mean()
    month_ret = (daily_mean.groupby(level=0).sum() * 100).round(2)
    signal_days = daily_mean.groupby(level=0).size()
    return [
        {"month": m, **_stats(g_),
         "ret_pct": float(month_ret[m]), "signal_days": int(signal_days[m])}
        for m, g_ in ev.groupby("month")
    ]


def _anchor_check(ev: pd.DataFrame) -> dict[str, object]:
    """与定稿锚点自校对(容差来自新增交易日与主板口径微调)。"""
    a = contracts.BACKTEST_ANCHORS
    s = _stats(ev)
    va = _stats(ev[~ev["is_train"]])
    return {
        "pool_n_diff": int(s.get("n", 0)) - a["pool_n"],
        "pool_avg_diff": round(float(s.get("avg_pct", 0)) - a["pool_avg_pct"], 2),
        "valid_n_diff": int(va.get("n", 0)) - a["valid_n"],
        "valid_avg_diff": round(float(va.get("avg_pct", 0)) - a["valid_avg_pct"], 2),
        "note": "差异应仅来自锚点之后的新增交易日;若同口径回溯期数值漂移即口径被破坏",
    }


def _slot_simulation(ev: pd.DataFrame) -> dict[str, object]:
    """三槽模拟仓:每日最多 3 笔,B 类(小阳建仓)优先;退出日实现盈亏。

    固定本金口径(非复利):每槽始终投初始本金的 1/3,盈亏直接累加——
    复利口径在数千笔稳定正期望下会得到 +3,532,804% 这种数学正确但
    毫无实盘意义的数字(容量/流动性不考虑),展示层面必须非复利。
    """
    usable = ev.dropna(subset=["exit_date"]).copy()
    picks = usable.sort_values(
        ["trade_date", "priority", "gap_open"],
        ascending=[True, False, True],
    )
    all_days = sorted(set(usable.trade_date.dt.date) | set(usable.exit_date.dt.date))
    day_index = {d: i for i, d in enumerate(all_days)}
    by_day = {d: g_ for d, g_ in picks.groupby(picks.trade_date.dt.date)}
    SLOT_INVEST = 1.0 / 3.0

    def run(with_breaker: bool) -> dict[str, object]:
        equity = 1.0
        slots: list[dict[str, object]] = []
        curve: list[dict[str, object]] = []
        trades: list[dict[str, object]] = []
        month_start_equity = equity
        month_halted: str | None = None
        prev_month = ""
        for i, day in enumerate(all_days):
            for slot in list(slots):
                if int(slot["exit_i"]) <= i:
                    equity += float(slot["invest"]) * float(slot["ret"])
                    trades.append(slot["row"])
                    slots.remove(slot)
            month = day.isoformat()[:7]
            if month != prev_month:
                month_start_equity = equity
                month_halted = None
                prev_month = month
            halted = month_halted == month
            for row in (by_day.get(day).itertuples() if day in by_day else ()):
                if len(slots) >= 3 or halted:
                    continue
                exit_i = day_index.get(row.exit_date.date())
                if exit_i is None:
                    continue
                slots.append({"invest": SLOT_INVEST, "ret": float(row.ret),
                              "exit_i": exit_i, "row": _trade_row(row)})
            if with_breaker and month_halted != month and month_start_equity > 0:
                if (equity - month_start_equity) / month_start_equity * 100 \
                        <= contracts.MONTHLY_CIRCUIT_BREAKER_PCT:
                    month_halted = month
            curve.append({"date": day.isoformat(), "equity": round(equity, 4)})
        rets = [float(t["ret_pct"]) for t in trades if t.get("ret_pct") is not None]
        wins = [r for r in rets if r > 0]
        peak = 1.0
        max_dd = 0.0
        for p in curve:
            peak = max(peak, float(p["equity"]))
            max_dd = min(max_dd, float(p["equity"]) / peak - 1)
        return {
            "trades": len(trades),
            "final_equity": round(equity, 4),
            "total_return_pct": round((equity - 1) * 100, 1),
            "win_rate_pct": round(len(wins) / len(rets) * 100, 1) if rets else None,
            "max_drawdown_pct": round(max_dd * 100, 1),
            "curve": curve,
        }

    plain = run(False)
    breaker = run(True)
    return {
        "note": contracts.SIM_DAILY_STOP_NOTE + ";槽位占用期间信号跳过;退出日确认盈亏",
        "plain": {k2: v for k2, v in plain.items() if k2 != "trades_detail"},
        "with_circuit_breaker": {k2: v for k2, v in breaker.items() if k2 != "trades_detail"},
    }


def _trade_row(row) -> dict[str, object]:
    return {
        "vt_symbol": str(row.vt_symbol),
        "name": str(row.name),
        "chassis_tag": str(getattr(row, "chassis_tag", "") or ""),
        "entry_date": row.trade_date.date().isoformat(),
        "entry_price": _sr(row.entry, 3),
        "gap_open_pct": _sr(float(row.gap_open) * 100 if row.gap_open is not None else None, 2),
        "priority": bool(row.priority),
        "sealed": bool(row.sealed),
        "streak_h": int(row.streak_k),
        "exit_price": _sr(getattr(row, "exit_px", None), 3),
        "exit_date": row.exit_date.date().isoformat(),
        "ret_pct": _sr(float(row.ret) * 100, 2),
        "exit_reason": ("break_open" if row.streak_k >= 2
                        else ("next_open_nostreak" if row.sealed else "next_open_fail")),
    }


def _sr(value: object, ndigits: int) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(number, ndigits) if math.isfinite(number) else None


def _ledger_days(ev: pd.DataFrame) -> list[dict[str, object]]:
    """全历史模拟交割单(全部触发信号,不限仓位不限天数;月份筛选由 API 层切片)。

    此前取三槽模拟仓成交(每日≤3笔),超出槽位的信号不进交割单;
    改为全样本 ev 逐笔——仓位约束只影响模拟仓净值曲线,不影响交割单口径。
    """
    usable = ev.dropna(subset=["exit_date"])
    days: dict[str, list[dict[str, object]]] = {}
    for row in usable.itertuples():
        days.setdefault(row.trade_date.date().isoformat(), []).append(_trade_row(row))
    out = []
    for d in sorted(days, reverse=True):
        items = days[d]
        rets = [float(t["ret_pct"]) for t in items if t.get("ret_pct") is not None]
        out.append({
            "trade_date": d,
            "trades": items,
            "count": len(items),
            "win": sum(1 for r in rets if r > 0),
            "avg_ret_pct": round(sum(rets) / len(rets), 2) if rets else None,
        })
    return out
