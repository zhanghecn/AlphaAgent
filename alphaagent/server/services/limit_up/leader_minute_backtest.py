"""Leader minute-level backtest v2（全市场 + 无未来函数）。

修复 v1 的样本选择偏差：v1 从涨停池 is_sealed 事件出发——先取事后确认涨停的首板，
再在其中找触板前的分钟买点，胜率被样本「必然涨停」虚高，不能称为全市场真实可执行回测。

v2 的 universe = 当日有分钟数据的全市场主板非 ST 股票，决策只用 D-1 及更早数据 +
盘中可观测数据：

- 触发：9:31-9:40 窗口内 1 分钟 surge ≥ 阈值或距开盘 cum ≥ 阈值，按触发 bar close 买入。
- 封板跳过：触发 bar close ≥ 涨停价（昨收 ×1.10）→ 当时已封板买不到（价格可观测，
  不使用 events 的 first_limit_time）。
- 一字板跳过：开盘价 ≥ 涨停价。
- 覆盖过滤：仅在当日分钟数据覆盖 ≥ MIN_DAY_COVERAGE 只的日子交易（覆盖数盘中可
  观测；稀疏日多为涨停事件票回填，存在覆盖偏差，整日跳过）。
- 因子：4 个 D-1 因子（流通市值/前5日涨幅/前3日上涨天数/前5日量比），触发群体月度
  expanding 校准，标签 = D+1 净赢（训练只用之前完整月份）。
- 卖出：D+1 日线规则（低开走/涨停减半/收盘走），双边费用 + 比例分摊。

研究只读 PostgreSQL，只写 ``leader_minute_backtest_runs`` 表。
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig
from alphaagent.server.services.limit_up.domain import main_board_limit_price
from alphaagent.server.services.limit_up.features import prior_stock_features
from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    _prior_3d_shape,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    _long_window_features,
    _mid_window_features,
    build_sector_context,
)
from alphaagent.server.services.limit_up.leader_first_board_prelude_pattern_research import (
    _prelude_pattern_features,
)
from alphaagent.server.services.limit_up.morning_window_leader_probability_research import (
    build_calibration,
    score_leader_probability,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_sector_daily_bars,
    load_sector_memberships_all,
    load_stock_names,
    load_window_minute_bars,
)
from alphaagent.server.services.limit_up.leader_minute_repository import (
    save_minute_backtest_run,
)

STUDY_VERSION = "leader-minute-backtest-v3"
WINDOW_START = "09:31:00"
WINDOW_END = "09:40:00"
DEFAULT_SURGE_PCT = 2.0  # 1 分钟涨幅阈值（%）
DEFAULT_CUM_PCT = 7.0  # 距开盘价累计涨幅阈值（%）
DEFAULT_MAX_POSITIONS = 3
DEFAULT_MIN_EFFECT = 4.0
MIN_DAY_COVERAGE = 600  # 宽覆盖日下限：当日有分钟数据的票数（盘中可观测）
MIN_TRAIN_SAMPLES = 20  # 月度 expanding 校准的最少已标答触发样本数
MAIN_BOARD_PREFIXES = ("60", "00")
PAPER_NOTIONAL = 100_000.0  # 训练标签用的单位名义本金（不进真实账户）

# 选股因子（连板龙头首板因子研究调研过的 D-1 可观测因子，剔除触板后的封板时间/封单比）
CANDIDATE_FACTORS = (
    "float_market_cap",
    "prior_return_5d_pct",
    "prior_turnover_ratio_5d",
    "prior_change_pct",
    "prior_3d_cum_return_pct",
    "prior_3d_max_change_pct",
    "prior_3d_up_days",
    "prior_day_change_pct",
    "prior_day_body_pct",
    "prior_day_range_pct",
    "prior_day_close_position",
    "prior_limit_count_126",
    "prior_limit_count_20",
    "days_since_prior_limit",
    "turnover_rate",
)
DEFAULT_MAX_PRIOR_RETURN_20D_PCT = 10.0  # 低位约束：前20日累计涨幅上限（%）

# v4 因子池 = Phase 0 稳定性门白名单（进回测/实时的唯一因子来源）：
# holdout 方向一致 + test |AUC-0.5|≥0.05 + 逐月一致性≥0.7 + 双目标一致。
# 证据：memory/06_backtests/limit_up_leader_first_board_factor_stability_20260801.md
# 滞后温度未过门（逐月一致性 0.61-0.69<0.7）→ 不进打分池、不做硬门，仅展示。
CANDIDATE_FACTORS_V4 = (
    "concept_max_return_20d",  # test AUC 0.6151（holdout 最强）
    "drawdown_from_126d_high_pct",  # 0.5816，strength 族代表
    "return_20d_pct",  # 0.5696
    "volume_ratio_5_60",  # 0.5659
    "prior_return_5d_pct",  # 0.5628
    "position_126d",  # 0.5614（与 drawdown rho 0.89，族合计权重上限 0.4）
)

# 位置过滤模式：low_position = v3 低位滤（return_20d ≤ 阈值）；
# deep_drop_exclusion = 深跌排除（return_20d ≤ -8.5% 或 drawdown_126d ≤ -21% 排除，
# concept_max_return_20d ≥ 16.5% 豁免）；owner_low_position = 主人版低位（只要贴底首板）；
# none = 不过滤。
POSITION_FILTERS = ("low_position", "deep_drop_exclusion", "owner_low_position", "none")
DEEP_DROP_RETURN_20D_PCT = -8.5
DEEP_DROP_DRAWDOWN_126D_PCT = -21.0
DEEP_DROP_EXEMPTION_CONCEPT_R20 = 16.5

# 触发时分时因子（归因研究验证：trigger_volume_ratio 封板 AUC 0.63 且 6/7 月方向一致，
# 是封板最强可交易确认信号；可选加入校准池或做硬滤下限）
TRIGGER_CALIBRATION_FEATURES = ("trigger_volume_ratio",)
# 生产触发量能硬滤（v5b 归因裁决：≥0.94 两档口径全面优于不滤——≥600 +8.8 vs +5.8、
# ≥300 +61.6 vs +51.4，触发池封板率 36.5%→41.9%/48.1%；证据
# memory/06_backtests/limit_up_leader_trigger_postmortem_cov300_20260801.md）
PRODUCTION_MIN_TRIGGER_VOLUME_RATIO = 0.94
# v6 预过滤（宽口径归因裁决，6/7 月一致）：
# ① 远距急拉排除——触发时距涨停 < -5.9% 的票封板率仅 13-15%（近距 44-48%）
# ② 冷板块排除——concept_max_return_20d ≤ 0.35% 胜率比温板块低 ~10pt
PRODUCTION_MIN_TRIGGER_DISTANCE_TO_LIMIT_PCT = -5.9
PRODUCTION_MIN_CONCEPT_R20_PCT = 0.35

# 前奏形态因子（主人 2026-08-02 假说，研究裁决：形态整体区分度弱、B 阴跌型不成立，
# vol_shift 月度一致 0.857 但 AUC 仅 0.545——默认不进校准、不做硬滤，仅 dump 观察；
# 证据 memory/06_backtests/limit_up_leader_first_board_prelude_pattern_20260802.md）
PRELUDE_CALIBRATION_FEATURES = (
    "prelude_small_yang_streak",
    "prelude_small_yin_streak",
    "prelude_vol_cv_7d",
    "prelude_vol_shift_ratio",
)
# 前奏形态硬滤模式：none = 不滤（默认）；any = 任一形态；small_yang/small_yin = 指定型
PRELUDE_PATTERN_MODES = ("none", "any", "small_yang", "small_yin")

# 入场模式：momentum_window = 9:31-9:40 surge/cum 触发（分钟级回测）；
# sweep_board = 扫板（触板后开板才按涨停价排板成交，全天未开板=买不到）。
ENTRY_MODES = ("momentum_window", "sweep_board")


def _sweep_entry_status(
    day_bars: Sequence[Mapping[str, object]],
    *,
    prev_close: float,
    max_entry_time: str | None = None,
    min_touch_bar_close_position: float | None = None,
) -> tuple[str, dict[str, object] | None]:
    """扫板入场（带状态）：触板后开板瞬间按涨停价排板成交；全天未开板 = 买不到。

    真实打板机制：买单挂在涨停价排队，只有炸板（开板）时卖单砸下来才成交，
    成交价 = 涨停价。未触板或触板后全天封死不打开，都视为买不进。
    触板判定：bar high ≥ 涨停价（容差）；开板判定：触板之后 bar low < 涨停价（容差）。
    触板 bar 自身不算开板（bar 内先砸后拉还是先拉后砸不可知，保守等下一根）。
    返回 ("filled"|"no_touch"|"no_open"|"too_late", entry|None)。
    """

    if prev_close <= 0:
        return "no_touch", None
    limit_price = main_board_limit_price(prev_close)
    tolerance = max(0.02, limit_price * 0.001)
    touched = False
    touch_time = ""
    for bar in day_bars:
        bar_time = str(bar.get("bar_time") or "")
        high = _float(bar.get("high_price")) or 0.0
        low = _float(bar.get("low_price")) or 0.0
        if not touched:
            if high >= limit_price - tolerance:
                # 触板 bar 收弱势（收在 bar 下半部=锁单差）→ 整票放弃（封板率仅 60%）
                if min_touch_bar_close_position is not None:
                    bar_close = _float(bar.get("close_price")) or 0.0
                    if high > low and bar_close > 0:
                        close_position = (bar_close - low) / (high - low)
                        if close_position < min_touch_bar_close_position:
                            return "weak_touch", None
                touched = True
                touch_time = bar_time
            continue
        if low < limit_price - tolerance:
            if max_entry_time and bar_time > max_entry_time:
                return "too_late", None  # 开板太晚（尾盘板没溢价，可配置回避）
            return "filled", {
                "buy_price": limit_price,
                "buy_time": bar_time,
                "touch_time": touch_time,
                "entry_kind": "sweep_open",
            }
    return ("no_open", None) if touched else ("no_touch", None)


def _sweep_entry(
    day_bars: Sequence[Mapping[str, object]],
    *,
    prev_close: float,
    max_entry_time: str | None = None,
) -> dict[str, object] | None:
    """扫板入场：开板成交则返回买入信息，否则 None（买不到/未触板/太晚）。"""

    _status, entry = _sweep_entry_status(
        day_bars, prev_close=prev_close, max_entry_time=max_entry_time
    )
    return entry

# 滞后温度门默认值：D-1 全市场首板数 ≥ 阈值则当日停手（None = 关闭）。
# 阈值来自 Phase 0 滞后口径分位（高潮日成龙率 4.77% vs 冷日 11.54%）。
DEFAULT_MAX_LAG1_FIRST_BOARD_COUNT: float | None = None


def _float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _is_main_board(vt_symbol: str) -> bool:
    return vt_symbol.split(".")[0].startswith(MAIN_BOARD_PREFIXES)


def _is_first_board_candidate(bars_before: Sequence[Mapping[str, object]]) -> bool:
    """首板候选：D-1 未涨停（今天若涨停必为首板）。D-1 可观测，不依赖 events。"""

    if len(bars_before) < 2:
        return False
    d1_close = _float(bars_before[-1].get("close_price"))
    d2_close = _float(bars_before[-2].get("close_price"))
    if not d1_close or not d2_close or d2_close <= 0:
        return False
    return d1_close < d2_close * 1.098


def _is_low_position(
    bars_before: Sequence[Mapping[str, object]], max_return_20d_pct: float
) -> bool:
    """低位：D-1 前20日累计涨幅 ≤ 阈值（近期没连续涨高）。历史不足 21 根则放行。"""

    if len(bars_before) < 21:
        return True
    d1_close = _float(bars_before[-1].get("close_price"))
    base_close = _float(bars_before[-21].get("close_price"))
    if not d1_close or not base_close or base_close <= 0:
        return True
    return (d1_close / base_close - 1) * 100 <= max_return_20d_pct


def _limit_flags(bars_before: Sequence[Mapping[str, object]]) -> list[bool]:
    """每日是否涨停（close ≥ 前收×1.098），日线自算，不依赖 events。"""

    flags: list[bool] = []
    for index in range(1, len(bars_before)):
        current = _float(bars_before[index].get("close_price"))
        previous = _float(bars_before[index - 1].get("close_price"))
        flags.append(bool(current and previous and previous > 0 and current >= previous * 1.098))
    return flags


def _d1_factors(
    bars_up_to_d: Sequence[Mapping[str, object]], today: str
) -> dict[str, object] | None:
    """完整调研 D-1 因子集（全部 D-1 可观测，日线自算，不依赖 events）。

    复用连板龙头首板因子研究口径：前序走势 + 前3天形状 + 涨停基因 + 市值流动性。
    bars_up_to_d 含 D 日（升序）；因子一律取 D-1 及更早。
    """

    bars_before = list(bars_up_to_d[:-1])  # D-1 及更早
    if len(bars_before) < 6:
        return None
    d1 = bars_before[-1]
    # ① 前序走势 + ② 前3天形状（复用调研口径）
    prior = prior_stock_features(bars_up_to_d, today, assume_sorted=True)
    shape = _prior_3d_shape(bars_up_to_d, today)
    # ③ 市值/流动性（D-1）
    d1_amount = _float(d1.get("turnover"))
    turnover_rate = _float(d1.get("turnover_rate"))
    float_market_cap = (
        d1_amount / (turnover_rate / 100)
        if d1_amount and turnover_rate and turnover_rate > 0
        else None
    )
    # ④ 涨停基因（日线自算）
    flags = _limit_flags(bars_before)
    last_limit = next((i for i in range(len(flags) - 1, -1, -1) if flags[i]), None)
    return {
        "prior_return_5d_pct": prior.get("prior_return_5d_pct"),
        "prior_turnover_ratio_5d": prior.get("prior_turnover_ratio_5d"),
        "prior_change_pct": prior.get("prior_change_pct"),
        "prior_3d_cum_return_pct": shape.get("prior_3d_cum_return_pct"),
        "prior_3d_max_change_pct": shape.get("prior_3d_max_change_pct"),
        "prior_3d_up_days": shape.get("prior_3d_up_days"),
        "prior_day_change_pct": shape.get("prior_day_change_pct"),
        "prior_day_body_pct": shape.get("prior_day_body_pct"),
        "prior_day_range_pct": shape.get("prior_day_range_pct"),
        "prior_day_close_position": shape.get("prior_day_close_position"),
        "float_market_cap": round(float_market_cap, 2) if float_market_cap else None,
        "turnover_rate": turnover_rate,
        "prior_limit_count_126": sum(flags[-126:]),
        "prior_limit_count_20": sum(flags[-20:]),
        "days_since_prior_limit": (len(flags) - 1 - last_limit)
        if last_limit is not None
        else None,
        # ⑤ v4 白名单因子：近半年大周期 + 前 4-10 天 + 量能（复用深度研究口径）
        **_long_window_features(bars_before),
        **_mid_window_features(bars_before),
        # ⑥ 归因补充：20 日位置/均线乖离/单日量能（D-1 可观测）
        **_daily_position_volume_features(bars_before),
        # ⑦ 前奏形态：小阳爬升/阴跌蓄势 + 量能共振（D-1 可观测，默认只 dump 观察）
        **_prelude_pattern_features(bars_before),
    }


def _is_owner_low_position(bars_before: Sequence[Mapping[str, object]]) -> bool:
    """主人版低位（2026-08-02 锚点校准 v2''）：贴底企稳首板，四条件同时成立。

    ① 距 126 日高点回撤 ≤ -25%（跌得深）；
    ② 距 126 日低点反弹 ≤ 12%（离底近，刚见底）；
    ③ 近 5 日涨幅 ≤ 6%（近期没有急反弹）；
    ④ 近 20 日振幅 ≤ 40%（底部平稳，非剧烈震荡）。
    锚点验证：立新能源/爱丽家居/传智教育全通过（振幅 21-34%）；
    至纯科技（07-31：深 V 急反弹后底部剧烈震荡，20 日振幅 90%、
    日均|涨跌| 7.0% vs 锚点 ≤3.2%——主人裁决「这种不算低位，
    看前 30 日与均线」）被 ③④ 卡排除。
    """

    long_feats = _long_window_features(bars_before)
    drawdown = _float(long_feats.get("drawdown_from_126d_high_pct"))
    rebound = _float(long_feats.get("rebound_from_126d_low_pct"))
    if drawdown is None or rebound is None:
        return False
    if drawdown > -25.0 or rebound > 12.0:
        return False
    if len(bars_before) >= 6:
        last_close = _float(bars_before[-1].get("close_price"))
        base_close = _float(bars_before[-6].get("close_price"))
        if last_close and base_close and base_close > 0:
            if (last_close / base_close - 1) * 100 > 6.0:
                return False  # 近 5 日急涨（V 形右半坡，非贴底）
    if len(bars_before) >= 20:
        w20 = bars_before[-20:]
        highs = [v for v in (_float(row.get("high_price")) for row in w20) if v]
        lows = [v for v in (_float(row.get("low_price")) for row in w20) if v]
        if highs and lows and min(lows) > 0:
            if (max(highs) - min(lows)) / min(lows) * 100 > 40.0:
                return False  # 底部剧烈震荡（非企稳）
    return True


def _position_filter_pass(
    bars_before: Sequence[Mapping[str, object]],
    mode: str,
    max_return_20d_pct: float,
    concept_r20: float | None,
) -> bool:
    """位置过滤：low_position=v3 低位滤；deep_drop_exclusion=深跌排除+板块爆发豁免；
    owner_low_position=主人版低位（只要贴底首板）。"""

    if mode == "none":
        return True
    if mode == "low_position":
        return _is_low_position(bars_before, max_return_20d_pct)
    if mode == "owner_low_position":
        return _is_owner_low_position(bars_before)
    if mode == "deep_drop_exclusion":
        long_feats = _long_window_features(bars_before)
        return_20d = _float(long_feats.get("return_20d_pct"))
        drawdown = _float(long_feats.get("drawdown_from_126d_high_pct"))
        deep_drop = (return_20d is not None and return_20d <= DEEP_DROP_RETURN_20D_PCT) or (
            drawdown is not None and drawdown <= DEEP_DROP_DRAWDOWN_126D_PCT
        )
        if not deep_drop:
            return True
        # 豁免：板块 20 日动量爆发（立新能源/爱丽家居「深跌+板块爆发」次路径）
        return concept_r20 is not None and concept_r20 >= DEEP_DROP_EXEMPTION_CONCEPT_R20
    raise ValueError(f"unknown position filter: {mode}")


def _limit_up_ratio(vt_symbol: str) -> float:
    """个股涨停幅度系数（主板 10%、创业板/科创板 20%），日线自算温度用。"""

    code = vt_symbol.split(".")[0]
    if code.startswith(("30", "68")):
        return 1.198
    return 1.098


def build_first_board_counts(
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, int]:
    """逐日全市场首板数（日线自算：当日涨停且前一日未涨停）。

    D 日盘前看 D-1 的计数 = 滞后温度，无未来函数；与 provider events 口径
    存在近似差异（涨停判定用收盘 ≥ 前收×幅度系数），研究/回测内部自洽。
    """

    counts: dict[str, int] = defaultdict(int)
    for symbol, rows in bars_by_symbol.items():
        ratio = _limit_up_ratio(symbol)
        prev_close: float | None = None
        prev_limit = False
        for bar in rows:
            close = _float(bar.get("close_price"))
            is_limit = bool(close and prev_close and prev_close > 0 and close >= prev_close * ratio)
            if is_limit and not prev_limit:
                counts[str(bar.get("trade_date") or "")] += 1
            prev_close = close
            prev_limit = is_limit
    return dict(counts)


def build_sector_r20_lookup(
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
) -> Callable[[str, str], float | None]:
    """concept_max_return_20d 查找：(symbol, D) → 所属概念板块 20 日动量最大值。

    板块动量用严格 D 日之前的指数收盘（build_sector_context 口径），
    D 日盘前可观测，无未来函数；板块归属为当前快照（历史归属可能漂移）。
    """

    ctx = build_sector_context([], memberships, sector_bars)

    def lookup(symbol: str, trade_date: str) -> float | None:
        values = [
            ctx.sector_return_prev[(sector_id, trade_date)]["r20"]
            for sector_id in ctx.member_map.get(symbol, {}).get("concept", [])
            if "r20" in ctx.sector_return_prev.get((sector_id, trade_date), {})
        ]
        return round(max(values), 4) if values else None

    return lookup


INDEX_VT_SYMBOL = "000001.SSE"  # 上证指数（stock_daily_bars 内含指数行）


def _index_above_ma20(
    index_daily_index: Mapping[str, Sequence[Mapping[str, object]]],
    prev_day: str,
) -> bool:
    """D-1 指数收盘是否 ≥ MA20（盘前可观测，无未来函数）。数据不足默认放行。"""

    rows = list(index_daily_index.get(INDEX_VT_SYMBOL) or [])
    closes = [
        _float(row.get("close_price"))
        for row in rows
        if str(row.get("trade_date") or "") <= prev_day
    ]
    closes = [value for value in closes if value]
    if len(closes) < 20:
        return True
    ma20 = mean(closes[-20:])
    return closes[-1] >= ma20


def _daily_position_volume_features(
    bars_before: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """前序交易日位置/量能补充因子（D-1 可观测）：20 日区间位置、均线乖离、单日量能比。"""

    out: dict[str, object] = {
        "position_20d": None,
        "bias_ma5_pct": None,
        "bias_ma20_pct": None,
        "turnover_1d_vs_20d": None,
    }
    if len(bars_before) < 20:
        return out
    w20 = list(bars_before[-20:])
    closes = [_float(row.get("close_price")) for row in w20]
    last_close = closes[-1]
    if not last_close:
        return out
    highs = [v for v in (_float(row.get("high_price")) for row in w20) if v]
    lows = [v for v in (_float(row.get("low_price")) for row in w20) if v]
    if highs and lows and max(highs) > min(lows) and min(lows) > 0:
        out["position_20d"] = round((last_close - min(lows)) / (max(highs) - min(lows)), 4)
    if len(closes) >= 5 and closes[-5] and mean(closes[-5:]) > 0:
        out["bias_ma5_pct"] = round((last_close / mean(closes[-5:]) - 1) * 100, 4)
    ma20 = mean(closes)
    if ma20 > 0:
        out["bias_ma20_pct"] = round((last_close / ma20 - 1) * 100, 4)
    turnovers = [v for v in (_float(row.get("turnover")) for row in w20) if v]
    d1_turnover = _float(bars_before[-1].get("turnover"))
    if d1_turnover and len(turnovers) >= 20 and mean(turnovers) > 0:
        out["turnover_1d_vs_20d"] = round(d1_turnover / mean(turnovers), 4)
    return out


def _d1_exit(bar: Mapping[str, object], prev_close: float) -> tuple[str, float]:
    """D+1 卖出决策（同打板口径）：返回 (exit_kind, price)。"""

    open_price = _float(bar.get("open_price")) or 0.0
    close_price = _float(bar.get("close_price")) or 0.0
    limit_price = main_board_limit_price(prev_close)
    if open_price <= prev_close:
        return "open_below_prev_close", open_price
    if close_price >= limit_price - max(0.02, limit_price * 0.001):
        return "limit_close", close_price
    return "close_not_limit", close_price


def _board_status(day_bar: Mapping[str, object], prev_close: float) -> str:
    """当日封板结局（结果信息，仅供交割单展示，不参与任何决策）。"""

    close_price = _float(day_bar.get("close_price")) or 0.0
    high_price = _float(day_bar.get("high_price")) or 0.0
    limit_price = main_board_limit_price(prev_close)
    tolerance = max(0.02, limit_price * 0.001)
    if close_price >= limit_price - tolerance:
        return "sealed"
    if high_price >= limit_price - tolerance:
        return "failed"
    return "no_limit"


def _trigger_buy(
    window_bars: Sequence[Mapping[str, object]],
    *,
    open_price: float,
    prev_close: float,
    surge_pct: float,
    cum_pct: float,
    window_start: str,
    window_end: str,
) -> dict[str, object] | None:
    """窗口内 surge/cum 触发 → 触发 bar close 买入；只用触发时点及之前的数据。"""

    if open_price <= 0 or prev_close <= 0:
        return None
    limit_price = main_board_limit_price(prev_close)
    if open_price >= limit_price:
        return None  # 一字板开盘即封，买不到
    prev_window_close: float | None = None
    trigger_index = 0
    for bar in window_bars:
        bar_time = str(bar.get("bar_time") or "")
        if bar_time < window_start or bar_time > window_end:
            continue
        close = _float(bar.get("close_price")) or 0.0
        if close <= 0:
            continue
        surge = (close / prev_window_close - 1) * 100 if prev_window_close else 0.0
        cum = (close / open_price - 1) * 100
        if (prev_window_close and surge >= surge_pct) or cum >= cum_pct:
            if close >= limit_price:
                return None  # 触发瞬间已封板（价格可观测），买不到
            return {
                "buy_price": close,
                "buy_time": bar_time,
                "cum_pct": round(cum, 4),
                "trigger_kind": "surge" if (prev_window_close and surge >= surge_pct) else "cum",
                "trigger_index": trigger_index,
                "surge_pct_at_trigger": round(surge, 4),
            }
        prev_window_close = close
        trigger_index += 1
    return None


def _trigger_minute_features(
    window_bars: Sequence[Mapping[str, object]],
    trigger: Mapping[str, object],
    *,
    open_price: float,
    prev_close: float,
) -> dict[str, object]:
    """打板买入过程的分时特征（全部触发时点及之前可观测，无未来函数）。"""

    out: dict[str, object] = {
        "open_gap_pct": None,
        "distance_to_limit_at_trigger_pct": None,
        "pre_trigger_consolidation_pct": None,
        "trigger_volume_ratio": None,
    }
    if open_price > 0 and prev_close > 0:
        out["open_gap_pct"] = round((open_price / prev_close - 1) * 100, 4)
        limit_price = main_board_limit_price(prev_close)
        buy_price = _float(trigger.get("buy_price"))
        if buy_price:
            out["distance_to_limit_at_trigger_pct"] = round(
                (buy_price / limit_price - 1) * 100, 4
            )
    trigger_time = str(trigger.get("buy_time") or "")
    pre_closes: list[float] = []
    pre_volumes: list[float] = []
    trigger_volume: float | None = None
    for bar in window_bars:
        bar_time = str(bar.get("bar_time") or "")
        close = _float(bar.get("close_price"))
        volume = _float(bar.get("volume"))
        if bar_time < trigger_time:
            if close and close > 0:
                pre_closes.append(close)
            if volume is not None and volume > 0:
                pre_volumes.append(volume)
        elif bar_time == trigger_time and volume is not None and volume > 0:
            trigger_volume = volume
    if len(pre_closes) >= 2 and open_price > 0:
        out["pre_trigger_consolidation_pct"] = round(
            (max(pre_closes) - min(pre_closes)) / open_price * 100, 4
        )
    if trigger_volume is not None and pre_volumes and mean(pre_volumes) > 0:
        out["trigger_volume_ratio"] = round(trigger_volume / mean(pre_volumes), 4)
    return out


def _build_month_calibration(
    train_samples: Sequence[Mapping[str, object]],
    month: str,
    *,
    min_train_samples: int,
    min_effect: float,
    candidate_factors: Sequence[str] = CANDIDATE_FACTORS,
) -> dict[str, object] | None:
    """expanding 校准：只用严格早于 month 且标签已知的触发样本。"""

    train = [
        sample
        for sample in train_samples
        if str(sample.get("month") or "") < month and sample.get("is_leader") is not None
    ]
    if len(train) < min_train_samples:
        return None
    calibration = build_calibration(train, tuple(candidate_factors), min_effect=min_effect)
    return calibration if calibration.get("factors") else None


@dataclass
class _Position:
    vt_symbol: str
    volume: int
    entry_date: str
    buy_price: float
    name: str = ""
    buy_time: str = ""
    cash_cost: float = 0.0
    initial_volume: int = 0
    board_status: str = "no_limit"


@dataclass
class _PaperPosition:
    """训练标签用的单位持仓（不进真实账户，不占用仓位）。"""

    sample: dict[str, object]
    volume: int
    buy_price: float
    cash_cost: float
    initial_volume: int
    net_pnl: float = 0.0


def simulate_allmarket_minute(
    *,
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, object]]],
    daily_index: Mapping[tuple[str, str], Mapping[str, object]],
    calendar: Sequence[str],
    names: Mapping[str, str],
    minute_loader: Callable[[date], Mapping[str, Sequence[Mapping[str, object]]]],
    config: CashBacktestConfig | None = None,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
    window_start: str = WINDOW_START,
    window_end: str = WINDOW_END,
    min_day_coverage: int = MIN_DAY_COVERAGE,
    min_train_samples: int = MIN_TRAIN_SAMPLES,
    min_effect: float = DEFAULT_MIN_EFFECT,
    max_prior_return_20d_pct: float = DEFAULT_MAX_PRIOR_RETURN_20D_PCT,
    candidate_factors: Sequence[str] = CANDIDATE_FACTORS,
    position_filter: str = "low_position",
    max_lag1_first_board_count: float | None = DEFAULT_MAX_LAG1_FIRST_BOARD_COUNT,
    lag1_first_board_counts: Mapping[str, int] | None = None,
    sector_r20_lookup: Callable[[str, str], float | None] | None = None,
    include_trigger_samples: bool = False,
    include_trigger_features_in_calibration: bool = False,
    min_trigger_volume_ratio: float | None = None,
    entry_mode: str = "momentum_window",
    max_entry_time: str | None = None,
    min_touch_bar_close_position: float | None = None,
    min_trigger_distance_to_limit_pct: float | None = None,
    min_concept_r20_pct: float | None = None,
    index_ma20_gate: bool = False,
    index_daily_index: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    require_prelude_pattern: str = "none",
    include_prelude_factors_in_calibration: bool = False,
) -> dict[str, object]:
    """全市场分钟级回测：低位首板触发 → D-1 因子校准排序 → TOP N 买入 → D+1 卖出。"""

    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"unknown entry mode: {entry_mode}")
    if require_prelude_pattern not in PRELUDE_PATTERN_MODES:
        raise ValueError(f"unknown prelude pattern mode: {require_prelude_pattern}")
    calibration_factors = (
        tuple(candidate_factors)
        + (TRIGGER_CALIBRATION_FEATURES if include_trigger_features_in_calibration else ())
        + (PRELUDE_CALIBRATION_FEATURES if include_prelude_factors_in_calibration else ())
    )

    if config is None:
        config = CashBacktestConfig(max_positions=DEFAULT_MAX_POSITIONS)
    cash = config.initial_cash
    positions: dict[str, _Position] = {}
    paper_positions: dict[str, _PaperPosition] = {}
    train_samples: list[dict[str, object]] = []
    closed_trades: list[dict[str, object]] = []
    equity_curve: list[dict[str, object]] = []
    calibrations: dict[str, object | None] = {}
    peak_equity = config.initial_cash
    prev_map = {
        calendar[i]: (calendar[i - 1] if i > 0 else None) for i in range(len(calendar))
    }
    symbol_dates: dict[str, list[str]] = {
        symbol: [str(bar.get("trade_date") or "") for bar in rows]
        for symbol, rows in bars_by_symbol.items()
    }
    stats = {
        "days_total": 0,
        "days_tradeable": 0,
        "days_skipped_low_coverage": 0,
        "days_skipped_hot_market": 0,
        "coverage_total": 0,
        "trigger_count": 0,
        "calibration_months": 0,
        "sweep_filled": 0,
        "sweep_no_touch": 0,
        "sweep_no_open": 0,
        "sweep_too_late": 0,
        "sweep_weak_touch": 0,
        "days_skipped_index_gate": 0,
        "candidates_skipped_prelude": 0,
    }

    def daily_close(symbol: str, today: str) -> float:
        bar = daily_index.get((symbol, today))
        return _float(bar.get("close_price")) or 0.0 if bar else 0.0

    def sell_execution(price: float, volume: int, cost_price: float):
        return cash_ledger.calculate_sell_execution(
            raw_price=price,
            volume=volume,
            cost_price=cost_price,
            commission_rate=config.commission_rate,
            stamp_tax_rate=config.stamp_tax_rate,
            slippage_bps=config.slippage_bps,
            minimum_commission=config.minimum_commission,
            transfer_fee_rate=config.transfer_fee_rate,
        )

    def sell_real(
        symbol: str,
        pos: _Position,
        exit_date: str,
        exit_price: float,
        volume: int,
        reason: str,
    ) -> None:
        nonlocal cash
        execution = sell_execution(exit_price, volume, pos.buy_price)
        cash += execution.cash_delta
        total_vol = pos.initial_volume or pos.volume
        sell_cost = pos.cash_cost * (volume / total_vol) if total_vol else pos.cash_cost
        net_pnl = execution.cash_delta - sell_cost
        closed_trades.append(
            {
                "vt_symbol": symbol,
                "name": pos.name or symbol,
                "entry_date": pos.entry_date,
                "exit_date": exit_date,
                "buy_price": pos.buy_price,
                "buy_time": pos.buy_time,
                "exit_price": execution.price,
                "volume": volume,
                "sell_amount": execution.amount,
                "fee": execution.fee,
                "net_pnl": net_pnl,
                "return_pct": round(net_pnl / sell_cost * 100, 4) if sell_cost else None,
                "is_win": net_pnl > 0,
                "exit_reason": reason,
                "board_status": pos.board_status,
            }
        )

    def sell_paper(paper: _PaperPosition, exit_price: float, volume: int) -> None:
        execution = sell_execution(exit_price, volume, paper.buy_price)
        total_vol = paper.initial_volume or paper.volume
        sell_cost = (
            paper.cash_cost * (volume / total_vol) if total_vol else paper.cash_cost
        )
        paper.net_pnl += execution.cash_delta - sell_cost

    def finish_paper(paper: _PaperPosition) -> None:
        paper.sample["is_leader"] = paper.net_pnl > 0

    for today in calendar:
        prev_day = prev_map[today]
        today_date = date.fromisoformat(today)
        # ── 1) D+1 卖出：真实持仓 + paper 持仓（同一套日线规则）
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            bar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
            if not bar or not prev_bar:
                continue
            prev_close = _float(prev_bar.get("close_price")) or 0.0
            if prev_close <= 0:
                continue
            kind, price = _d1_exit(bar, prev_close)
            if kind == "limit_close":
                sell_vol = (pos.volume // 2 // config.lot_size) * config.lot_size
                if sell_vol > 0:
                    sell_real(symbol, pos, today, price, sell_vol, "limit_half")
                    pos.volume -= sell_vol
                if pos.volume <= 0:
                    del positions[symbol]
            else:
                sell_real(symbol, pos, today, price, pos.volume, kind)
                del positions[symbol]
        for symbol in list(paper_positions.keys()):
            paper = paper_positions[symbol]
            bar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
            if not bar or not prev_bar:
                continue
            prev_close = _float(prev_bar.get("close_price")) or 0.0
            if prev_close <= 0:
                continue
            kind, price = _d1_exit(bar, prev_close)
            if kind == "limit_close":
                sell_vol = (paper.volume // 2 // config.lot_size) * config.lot_size
                if sell_vol > 0:
                    sell_paper(paper, price, sell_vol)
                    paper.volume -= sell_vol
                if paper.volume <= 0:
                    finish_paper(paper)
                    del paper_positions[symbol]
            else:
                sell_paper(paper, price, paper.volume)
                finish_paper(paper)
                del paper_positions[symbol]
        # ── 2) D 日全市场触发扫描（仅宽覆盖日）
        stats["days_total"] += 1
        window_bars = minute_loader(today_date)
        coverage = len(window_bars)
        stats["coverage_total"] += coverage
        if coverage < min_day_coverage:
            stats["days_skipped_low_coverage"] += 1
        # 滞后温度门：D-1 全市场首板数 ≥ 阈值（涨停潮次日稀释）→ 当日停手
        elif (
            max_lag1_first_board_count is not None
            and prev_day
            and (lag1_first_board_counts or {}).get(prev_day, 0)
            >= max_lag1_first_board_count
        ):
            stats["days_skipped_hot_market"] += 1
        # 大盘环境门：D-1 指数收盘 < MA20 → 当日停手（下跌段不做动量首板）
        elif (
            index_ma20_gate
            and prev_day
            and not _index_above_ma20(index_daily_index or {}, prev_day)
        ):
            stats["days_skipped_index_gate"] += 1
        else:
            stats["days_tradeable"] += 1
            month = today[:7]
            if month not in calibrations:
                calibrations[month] = _build_month_calibration(
                    train_samples,
                    month,
                    min_train_samples=min_train_samples,
                    min_effect=min_effect,
                    candidate_factors=calibration_factors,
                )
                if calibrations[month]:
                    stats["calibration_months"] += 1
            calibration = calibrations[month]
            candidates: list[dict[str, object]] = []
            for symbol, bars in window_bars.items():
                if not _is_main_board(symbol):
                    continue
                name = names.get(symbol) or symbol
                if "ST" in name.upper():
                    continue
                dates = symbol_dates.get(symbol) or []
                index = bisect_left(dates, today)
                if index >= len(dates) or dates[index] != today:
                    continue
                bars_all = list(bars_by_symbol[symbol])
                bars_before = bars_all[:index]
                # 首板：D-1 未涨停（今天若涨停必为首板，排除连板延续）
                if not _is_first_board_candidate(bars_before):
                    continue
                # 位置过滤（A/B 对照：v3 低位滤 vs 深跌排除+板块爆发豁免）
                concept_r20 = (
                    sector_r20_lookup(symbol, today) if sector_r20_lookup else None
                )
                if not _position_filter_pass(
                    bars_before, position_filter, max_prior_return_20d_pct, concept_r20
                ):
                    continue
                # 前奏形态硬滤（默认关闭；研究裁决形态区分度弱，对照跑用）
                if require_prelude_pattern != "none":
                    matched = str(
                        _prelude_pattern_features(bars_before).get("prelude_pattern")
                    )
                    passed = (
                        matched in ("small_yang", "small_yin")
                        if require_prelude_pattern == "any"
                        else matched == require_prelude_pattern
                    )
                    if not passed:
                        stats["candidates_skipped_prelude"] += 1
                        continue
                dbar = daily_index.get((symbol, today))
                prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
                if not dbar or not prev_bar:
                    continue
                open_price = _float(dbar.get("open_price")) or 0.0
                prev_close = _float(prev_bar.get("close_price")) or 0.0
                if entry_mode == "sweep_board":
                    # 扫板：触板后开板按涨停价排板成交；全天未开板 = 买不到
                    sweep_status, entry = _sweep_entry_status(
                        bars,
                        prev_close=prev_close,
                        max_entry_time=max_entry_time,
                        min_touch_bar_close_position=min_touch_bar_close_position,
                    )
                    stats[f"sweep_{sweep_status}"] += 1
                    if entry is None:
                        continue
                    factors = _d1_factors(bars_all[: index + 1], today)
                    if factors is None:
                        continue
                    factors["concept_max_return_20d"] = concept_r20
                    stats["trigger_count"] += 1
                    sample: dict[str, object] = {
                        **factors,
                        "trigger_kind": "sweep_open",
                        "vt_symbol": symbol,
                        "name": name,
                        "trade_date": today,
                        "month": month,
                        "buy_price": entry["buy_price"],
                        "buy_time": entry["buy_time"],
                        "touch_time": entry["touch_time"],
                        "cum_pct": round(
                            (float(entry["buy_price"]) / open_price - 1) * 100, 4
                        )
                        if open_price > 0
                        else 0.0,
                        "board_status": _board_status(dbar, prev_close),
                        "is_leader": None,
                        "bought": False,
                        "score": None,
                    }
                    candidates.append(sample)
                    # paper 单位持仓（训练标签，独立同规则模拟，不进真实账户）
                    if symbol not in paper_positions:
                        paper_buy = cash_ledger.calculate_buy_execution(
                            raw_price=float(entry["buy_price"]),
                            cash=PAPER_NOTIONAL,
                            target_cash=PAPER_NOTIONAL,
                            commission_rate=config.commission_rate,
                            slippage_bps=config.slippage_bps,
                            lot_size=config.lot_size,
                            minimum_commission=config.minimum_commission,
                            transfer_fee_rate=config.transfer_fee_rate,
                        )
                        if paper_buy.volume > 0:
                            paper_positions[symbol] = _PaperPosition(
                                sample=sample,
                                volume=paper_buy.volume,
                                buy_price=paper_buy.price,
                                cash_cost=paper_buy.amount + paper_buy.fee,
                                initial_volume=paper_buy.volume,
                            )
                    continue
                trigger = _trigger_buy(
                    bars,
                    open_price=open_price,
                    prev_close=prev_close,
                    surge_pct=surge_pct,
                    cum_pct=cum_pct,
                    window_start=window_start,
                    window_end=window_end,
                )
                if not trigger:
                    continue
                factors = _d1_factors(bars_all[: index + 1], today)
                if factors is None:
                    continue
                factors["concept_max_return_20d"] = concept_r20
                # 打板过程分时特征（触发时点可观测，归因研究用）
                minute_features = _trigger_minute_features(
                    bars, trigger, open_price=open_price, prev_close=prev_close
                )
                # 触发量能硬滤（归因验证：量比 ≥0.94 封板率 41.7% vs <0.94 的 26-31%）
                if (
                    min_trigger_volume_ratio is not None
                    and (
                        _float(minute_features.get("trigger_volume_ratio")) or 0.0
                    )
                    < min_trigger_volume_ratio
                ):
                    continue
                # v6 预过滤①：远距急拉排除（触发时距涨停太远=封板率 13-15% 的弱票）
                trigger_distance = _float(
                    minute_features.get("distance_to_limit_at_trigger_pct")
                )
                if (
                    min_trigger_distance_to_limit_pct is not None
                    and trigger_distance is not None
                    and trigger_distance < min_trigger_distance_to_limit_pct
                ):
                    continue
                # v6 预过滤②：冷板块排除（concept r20 ≤ 阈值；无归属数据不罚）
                if (
                    min_concept_r20_pct is not None
                    and concept_r20 is not None
                    and concept_r20 <= min_concept_r20_pct
                ):
                    continue
                stats["trigger_count"] += 1
                sample: dict[str, object] = {
                    **factors,
                    "trigger_kind": trigger["trigger_kind"],
                    "trigger_index": trigger["trigger_index"],
                    "surge_pct_at_trigger": trigger["surge_pct_at_trigger"],
                    **minute_features,
                    "vt_symbol": symbol,
                    "name": name,
                    "trade_date": today,
                    "month": month,
                    "buy_price": trigger["buy_price"],
                    "buy_time": trigger["buy_time"],
                    "cum_pct": trigger["cum_pct"],
                    "board_status": _board_status(dbar, prev_close),
                    "is_leader": None,
                    "bought": False,
                    "score": None,
                }
                candidates.append(sample)
                # paper 单位持仓（训练标签，独立同规则模拟，不进真实账户）
                if symbol not in paper_positions:
                    paper_buy = cash_ledger.calculate_buy_execution(
                        raw_price=float(trigger["buy_price"]),
                        cash=PAPER_NOTIONAL,
                        target_cash=PAPER_NOTIONAL,
                        commission_rate=config.commission_rate,
                        slippage_bps=config.slippage_bps,
                        lot_size=config.lot_size,
                        minimum_commission=config.minimum_commission,
                        transfer_fee_rate=config.transfer_fee_rate,
                    )
                    if paper_buy.volume > 0:
                        paper_positions[symbol] = _PaperPosition(
                            sample=sample,
                            volume=paper_buy.volume,
                            buy_price=paper_buy.price,
                            cash_cost=paper_buy.amount + paper_buy.fee,
                            initial_volume=paper_buy.volume,
                        )
            # ── 3) 校准排序 + TOP N 买入
            if calibration:
                for sample in candidates:
                    sample["score"] = score_leader_probability(sample, calibration)
                candidates.sort(
                    key=lambda s: (
                        -(s["score"] if s["score"] is not None else float("-inf")),
                        -float(s["cum_pct"]),
                    )
                )
            else:
                candidates.sort(key=lambda s: -float(s["cum_pct"]))
            train_samples.extend(candidates)
            for sample in candidates:
                if len(positions) >= config.max_positions:
                    break
                symbol = str(sample["vt_symbol"])
                if symbol in positions:
                    continue
                total_equity_now = cash + sum(
                    p.volume * daily_close(s, today) for s, p in positions.items()
                )
                buy = cash_ledger.calculate_buy_execution(
                    raw_price=float(sample["buy_price"]),
                    cash=cash,
                    target_cash=total_equity_now / config.max_positions,
                    commission_rate=config.commission_rate,
                    slippage_bps=config.slippage_bps,
                    lot_size=config.lot_size,
                    minimum_commission=config.minimum_commission,
                    transfer_fee_rate=config.transfer_fee_rate,
                )
                if buy.volume <= 0:
                    continue
                cash = buy.cash_after
                sample["bought"] = True
                positions[symbol] = _Position(
                    symbol,
                    buy.volume,
                    today,
                    buy.price,
                    name=str(sample["name"]),
                    buy_time=str(sample["buy_time"]),
                    cash_cost=buy.amount + buy.fee,
                    initial_volume=buy.volume,
                    board_status=str(sample["board_status"]),
                )
        # ── 4) equity mark（用当日收盘，盘后行为非决策）
        market_value = sum(
            p.volume * daily_close(s, today) for s, p in positions.items()
        )
        total_equity = cash + market_value
        peak_equity = max(peak_equity, total_equity)
        drawdown = (total_equity / peak_equity - 1) if peak_equity > 0 else 0.0
        equity_curve.append(
            {
                "trade_date": today,
                "cash": round(cash, 4),
                "market_value": round(market_value, 4),
                "total_equity": round(total_equity, 4),
                "drawdown_pct": round(drawdown * 100, 4),
            }
        )

    # ── 5) 末日清仓（真实 + paper）
    last_day = calendar[-1] if calendar else ""
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        bar = daily_index.get((symbol, last_day))
        exit_price = (_float(bar.get("close_price")) or pos.buy_price) if bar else pos.buy_price
        sell_real(symbol, pos, last_day, exit_price, pos.volume, "final_close")
        del positions[symbol]
    for symbol in list(paper_positions.keys()):
        paper = paper_positions[symbol]
        bar = daily_index.get((symbol, last_day))
        exit_price = (_float(bar.get("close_price")) or paper.buy_price) if bar else paper.buy_price
        sell_paper(paper, exit_price, paper.volume)
        finish_paper(paper)
        del paper_positions[symbol]

    labeled = [s for s in train_samples if s.get("is_leader") is not None]
    result: dict[str, object] = {
        "execution_valid": False,
        "account_config": {
            "initial_cash": config.initial_cash,
            "max_positions": config.max_positions,
            "commission_rate": config.commission_rate,
            "stamp_tax_rate": config.stamp_tax_rate,
            "slippage_bps": config.slippage_bps,
        },
        "execution_summary": _build_summary(config, cash, closed_trades, equity_curve),
        "equity_curve": equity_curve,
        "closed_trades": closed_trades,
        "coverage_stats": {
            "days_total": stats["days_total"],
            "days_tradeable": stats["days_tradeable"],
            "days_skipped_low_coverage": stats["days_skipped_low_coverage"],
            "days_skipped_hot_market": stats["days_skipped_hot_market"],
            "avg_covered_symbols": round(
                stats["coverage_total"] / stats["days_total"], 1
            )
            if stats["days_total"]
            else 0,
            "trigger_count": stats["trigger_count"],
            "calibration_months": stats["calibration_months"],
            "train_samples_labeled": len(labeled),
            "label_win_count": sum(1 for s in labeled if s.get("is_leader")),
            "sweep_filled": stats["sweep_filled"],
            "sweep_no_touch": stats["sweep_no_touch"],
            "sweep_no_open": stats["sweep_no_open"],
            "sweep_too_late": stats["sweep_too_late"],
            "sweep_weak_touch": stats["sweep_weak_touch"],
            "days_skipped_index_gate": stats["days_skipped_index_gate"],
            "candidates_skipped_prelude": stats["candidates_skipped_prelude"],
        },
        "backtest_config": {
            "factor_set": list(candidate_factors),
            "position_filter": position_filter,
            "max_lag1_first_board_count": max_lag1_first_board_count,
            "entry_mode": entry_mode,
            "max_entry_time": max_entry_time,
        },
    }
    if include_trigger_samples:
        # 归因研究用：全部触发样本（D-1 因子 + 分时特征 + 封板结局 + D+1 标签）
        result["trigger_samples"] = train_samples
    return result


def _build_summary(config, final_cash, closed_trades, equity_curve):
    wins = [t for t in closed_trades if t.get("is_win")]
    losses = [t for t in closed_trades if not t.get("is_win")]
    gross_profit = sum(t.get("net_pnl", 0.0) for t in wins)
    gross_loss = sum(abs(t.get("net_pnl", 0.0)) for t in losses)
    returns = [
        t.get("return_pct") for t in closed_trades if t.get("return_pct") is not None
    ]
    max_drawdown = min(
        (row.get("drawdown_pct", 0.0) for row in equity_curve), default=0.0
    )
    return {
        "initial_cash": config.initial_cash,
        "final_equity": round(final_cash, 4),
        "trade_count": len(closed_trades),
        "win_count": len(wins),
        "win_rate": round(len(wins) / len(closed_trades) * 100, 4)
        if closed_trades
        else None,
        "total_return_pct": round((final_cash / config.initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "total_fees": round(sum(t.get("fee", 0.0) for t in closed_trades), 4),
    }


def run_minute_backtest(
    *,
    start: date,
    end: date,
    surge_pct: float = DEFAULT_SURGE_PCT,
    cum_pct: float = DEFAULT_CUM_PCT,
    min_day_coverage: int = MIN_DAY_COVERAGE,
    max_prior_return_20d_pct: float = DEFAULT_MAX_PRIOR_RETURN_20D_PCT,
    factor_set: str = "v3",
    position_filter: str = "low_position",
    max_lag1_first_board_count: float | None = DEFAULT_MAX_LAG1_FIRST_BOARD_COUNT,
    minute_interval: str = "1m",
    include_trigger_samples: bool = False,
    include_trigger_features_in_calibration: bool = False,
    min_trigger_volume_ratio: float | None = None,
    entry_mode: str = "momentum_window",
    max_entry_time: str | None = None,
    min_touch_bar_close_position: float | None = None,
    min_trigger_distance_to_limit_pct: float | None = None,
    min_concept_r20_pct: float | None = None,
    index_ma20_gate: bool = False,
    require_prelude_pattern: str = "none",
    include_prelude_factors_in_calibration: bool = False,
) -> dict[str, object]:
    """加载全市场日线 + 分钟 bar，跑无未来函数的低位首板分钟级回测。"""

    daily_bars = load_daily_bars_all(start - timedelta(days=320), end + timedelta(days=7))
    names = load_stock_names()
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for rows in bars_by_symbol.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    daily_index = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")): bar
        for bar in daily_bars
    }
    calendar = sorted(
        {
            str(bar.get("trade_date") or "")
            for bar in daily_bars
            if bar.get("trade_date")
            and start.isoformat() <= str(bar["trade_date"]) <= end.isoformat()
        }
    )
    candidate_factors = CANDIDATE_FACTORS_V4 if factor_set == "v4" else CANDIDATE_FACTORS
    lag1_counts = (
        build_first_board_counts(bars_by_symbol)
        if max_lag1_first_board_count is not None
        else None
    )
    sector_r20_lookup = None
    if factor_set == "v4" or position_filter == "deep_drop_exclusion":
        sector_r20_lookup = build_sector_r20_lookup(
            load_sector_memberships_all(),
            load_sector_daily_bars(start - timedelta(days=190), end),
        )
    result = simulate_allmarket_minute(
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        calendar=calendar,
        names=names,
        minute_loader=(
            (lambda day: load_window_minute_bars(day, interval=minute_interval))
            if minute_interval != "1m"
            else load_window_minute_bars
        )
        if entry_mode != "sweep_board"
        else (
            # 扫板需要全天分钟 bar（触板/开板可能发生在任意时段）
            lambda day: load_window_minute_bars(
                day, start_time="09:25:00", end_time="15:01:00", interval=minute_interval
            )
        ),
        surge_pct=surge_pct,
        cum_pct=cum_pct,
        min_day_coverage=min_day_coverage,
        max_prior_return_20d_pct=max_prior_return_20d_pct,
        candidate_factors=candidate_factors,
        position_filter=position_filter,
        max_lag1_first_board_count=max_lag1_first_board_count,
        lag1_first_board_counts=lag1_counts,
        sector_r20_lookup=sector_r20_lookup,
        include_trigger_samples=include_trigger_samples,
        include_trigger_features_in_calibration=include_trigger_features_in_calibration,
        min_trigger_volume_ratio=min_trigger_volume_ratio,
        entry_mode=entry_mode,
        max_entry_time=max_entry_time,
        min_touch_bar_close_position=min_touch_bar_close_position,
        min_trigger_distance_to_limit_pct=min_trigger_distance_to_limit_pct,
        min_concept_r20_pct=min_concept_r20_pct,
        index_ma20_gate=index_ma20_gate,
        index_daily_index=bars_by_symbol,
        require_prelude_pattern=require_prelude_pattern,
        include_prelude_factors_in_calibration=include_prelude_factors_in_calibration,
    )
    stats = result["coverage_stats"]
    result["study_version"] = STUDY_VERSION
    result["start"] = start.isoformat()
    result["end"] = end.isoformat()
    result["surge_pct"] = surge_pct
    result["cum_pct"] = cum_pct
    result["window"] = f"{WINDOW_START}-{WINDOW_END}"
    result["factor_set"] = factor_set
    result["position_filter"] = position_filter
    result["minute_interval"] = minute_interval
    result["entry_mode"] = entry_mode
    result["require_prelude_pattern"] = require_prelude_pattern
    result["include_prelude_factors_in_calibration"] = include_prelude_factors_in_calibration
    result["notes"] = [
        "v3 在 v2 无未来函数口径上加「低位首板」约束：D-1未涨停（保证首板，排除连板延续）+ 前20日累计涨幅≤阈值（低位，排除高位追涨），全部 D-1 可观测。",
        "v4 变更：因子池换 Phase 0 稳定性门白名单（concept_max_return_20d/drawdown_126d/return_20d/volume_ratio_5_60/prior_return_5d/position_126d）；位置过滤可切 deep_drop_exclusion（深跌排除+板块爆发豁免）；滞后温度门可选（D-1 全市场首板数≥阈值停手，Phase 0 未过稳定性门，默认关闭）。",
        "触发/封板/一字全部盘中可观测：9:31-9:40 surge≥2% 或 cum≥7% 按触发 bar close 买入；触发 bar close≥涨停价 或 开盘≥涨停价跳过（不用 events 的 first_limit_time）。",
        f"仅在分钟覆盖≥{min_day_coverage}票的宽覆盖日交易：{stats['days_tradeable']}/{stats['days_total']} 天（稀疏日多为事件票回填，整日跳过；温度门跳过 {stats['days_skipped_hot_market']} 天）。校准生效月：{stats['calibration_months']}。",
        "板块动量用板块指数日线严格 D 日前收盘自算；板块归属为当前快照（历史归属可能漂移）。",
        "剩余限制：1m 覆盖窗口短（2026-06起才有宽覆盖），可交易日少、样本小；覆盖偏活跃股。胜率/复利为小样本结果，不可外推。",
    ]
    return result


def main(argv: Sequence[str] | None = None) -> None:
    """Run the all-market minute backtest and write to DB."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--surge-pct", type=float, default=DEFAULT_SURGE_PCT)
    parser.add_argument("--cum-pct", type=float, default=DEFAULT_CUM_PCT)
    parser.add_argument("--min-day-coverage", type=int, default=MIN_DAY_COVERAGE)
    parser.add_argument("--factor-set", choices=("v3", "v4"), default="v3")
    parser.add_argument("--position-filter", choices=POSITION_FILTERS, default="low_position")
    parser.add_argument(
        "--max-lag1-first-board-count",
        type=float,
        default=DEFAULT_MAX_LAG1_FIRST_BOARD_COUNT,
        help="滞后温度门：D-1 全市场首板数≥阈值则当日停手（默认关闭）",
    )
    parser.add_argument("--skip-save", action="store_true", help="不写 DB（A/B 对照跑法）")
    parser.add_argument("--minute-interval", choices=("1m", "5m"), default="1m")
    parser.add_argument(
        "--dump-trigger-samples",
        action="store_true",
        help="结果附带全部触发样本（归因研究用，样本量大时 JSON 较大）",
    )
    parser.add_argument(
        "--trigger-features-in-calibration",
        action="store_true",
        help="把触发时分时因子（trigger_volume_ratio）加入月度校准池",
    )
    parser.add_argument(
        "--min-trigger-volume-ratio",
        type=float,
        default=None,
        help="触发量能硬滤：trigger_volume_ratio 低于阈值则跳过（默认关闭）",
    )
    parser.add_argument("--entry-mode", choices=ENTRY_MODES, default="momentum_window")
    parser.add_argument(
        "--max-entry-time",
        default=None,
        help="扫板模式：开板晚于该时刻不入场（如 14:00:00，默认不限）",
    )
    parser.add_argument(
        "--min-touch-bar-close-position",
        type=float,
        default=None,
        help="扫板模式：触板 bar 收盘位置低于阈值（0-1）则放弃该票（如 0.57）",
    )
    parser.add_argument(
        "--min-trigger-distance-to-limit-pct",
        type=float,
        default=None,
        help="分钟级：触发时距涨停低于阈值（如 -5.9）则跳过（远距急拉封板率低）",
    )
    parser.add_argument(
        "--min-concept-r20-pct",
        type=float,
        default=None,
        help="分钟级：板块 20 日动量 ≤ 阈值（如 0.35）则跳过（冷板块胜率低）",
    )
    parser.add_argument(
        "--index-ma20-gate",
        action="store_true",
        help="大盘环境门：D-1 上证指数收盘 < MA20 则当日停手",
    )
    parser.add_argument(
        "--require-prelude-pattern",
        choices=PRELUDE_PATTERN_MODES,
        default="none",
        help="前奏形态硬滤：any=任一小阳/小阴形态才允许候选（默认关闭，对照跑用）",
    )
    parser.add_argument(
        "--prelude-factors-in-calibration",
        action="store_true",
        help="把前奏形态因子（streak/量稳/量比）加入月度校准池",
    )
    parser.add_argument("--json-output", type=Path, required=False)
    arguments = parser.parse_args(argv)

    result = run_minute_backtest(
        start=arguments.start,
        end=arguments.end,
        surge_pct=arguments.surge_pct,
        cum_pct=arguments.cum_pct,
        min_day_coverage=arguments.min_day_coverage,
        factor_set=arguments.factor_set,
        position_filter=arguments.position_filter,
        max_lag1_first_board_count=arguments.max_lag1_first_board_count,
        minute_interval=arguments.minute_interval,
        include_trigger_samples=arguments.dump_trigger_samples,
        include_trigger_features_in_calibration=arguments.trigger_features_in_calibration,
        min_trigger_volume_ratio=arguments.min_trigger_volume_ratio,
        entry_mode=arguments.entry_mode,
        max_entry_time=arguments.max_entry_time,
        min_touch_bar_close_position=arguments.min_touch_bar_close_position,
        min_trigger_distance_to_limit_pct=arguments.min_trigger_distance_to_limit_pct,
        min_concept_r20_pct=arguments.min_concept_r20_pct,
        index_ma20_gate=arguments.index_ma20_gate,
        require_prelude_pattern=arguments.require_prelude_pattern,
        include_prelude_factors_in_calibration=arguments.prelude_factors_in_calibration,
    )
    if not arguments.skip_save:
        if arguments.entry_mode == "sweep_board":
            from alphaagent.server.services.limit_up.leader_sweep_repository import (
                save_sweep_backtest_run,
            )

            save_sweep_backtest_run(STUDY_VERSION, result)
        else:
            save_minute_backtest_run(STUDY_VERSION, result)
    if arguments.json_output:
        arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
