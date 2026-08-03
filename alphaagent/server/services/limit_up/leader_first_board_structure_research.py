"""首板结构因子研究（均线收拢/波浪 + 量能梯形 + 控盘小阳 + 案例核查）。

主人假说（2026-08-02，requirements/潜龙首板优化.md，14 个 6-7 月案例人工复盘）：

- **低位收拢型**（情形最多）：MA10<MA20<MA30 空头排列约一个月 → MA10 极速收拢/
  金叉 MA20（或三线粘合近横盘）→ 企稳站上 MA10 → 首板。
- **波浪型**：MA10>MA20>MA30（与低位型相反），回调至摆动低点企稳 → 首板；
  行情好→波浪型多，行情差→低位型多（regime 切换假说，本研究只做描述性对照）。
- **量能规律（主力控盘）**：放量梯形 / 萎缩梯形 / 平稳后突变；控盘小阳（涨幅 ~1% 贴 MA5）。
- **执行层（D 日）**：竞价涨幅可确认首板延续性——D 日可观测，单独标注，
  绝不混进 D-1 因子族；1/2/3/5 分钟涨幅等分钟数据本期不用（主人：数据少易过拟合）。

研究流程（主人指定）：

1. **案例核查**：14 个锚点案例逐条核对主人描述（符合/不符合/数据不足 + 数值证据）。
2. 复用 ``build_factor_samples(min_consecutive_boards=2, board_gap_mode="wave")`` 收集
   >=2 连板首板样本，核对形态命中率（含 >=3 板妖股子集）与预测区分度。
3. 市况分型（index_above_ma20 × 形态族）+ 月度一致性（6/7 月翻转检查）。
4. 预登记组合 vs 基线（21.94%）+ 漏网归因（被拒的 >=2 板票按子条件统计 + 妖股清单）。
5. 盘前全市场框架（frame 2）：全市场主板股票日扫描，输出「出现首板涨停的几率」
   与「每个交易日平均候选数」，lift 分档裁决 过滤 vs 排序（预声明）。

``_structure_features`` 是共享纯函数（D-1 可观测、无未来函数）。
**依赖方向规则**：本模块 import ``leader_minute_backtest`` 的复用函数，
``leader_minute_backtest`` 绝不允许反向 import 本模块——若生产要用结构因子，
先把 ``_structure_features`` 提升到 ``features.py``。

只读研究脚本：不触碰实时表/API/持仓。``is_leader``/``eventual_peak``/``d1_*``/``auction_gap_pct``
是未来或 D 日标签，仅用于对照分组，绝不作为 D-1 可交易因子。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median, quantiles

from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    compare_categorical_factor,
    compare_numeric_factor,
    extract_first_board_samples,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    DAILY_FORWARD_DAYS,
    DAILY_LOOKBACK_DAYS,
    SECTOR_LOOKBACK_DAYS,
    _bool,
    _categorical_outcomes,
    _long_window_features,
    _mid_window_features,
    _number,
    _sample_float,
    build_factor_samples,
)
from alphaagent.server.services.limit_up.leader_first_board_factor_stability_research import (
    _month_of,
    _spearman_pairs,
    collinearity_matrix,
    monthly_factor_stability,
)
from alphaagent.server.services.limit_up.leader_first_board_prelude_pattern_research import (
    _june_july_check,
    _prelude_pattern_features,
)
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    INDEX_VT_SYMBOL,
    _daily_position_volume_features,
    _is_first_board_candidate,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_sector_daily_bars,
    load_sector_memberships_all,
    load_stock_names,
)

STUDY_VERSION = "leader-first-board-structure-v1"

# ── 预声明阈值（主人口径锚定；敏感性只做预声明档位，不网格搜索）──────────────
MA_WINDOWS = (5, 10, 20, 30)  # 主人指定均线族，固定不参数化
MA_ALIGN_DAYS_CAP = 30
MA_MIN_HISTORY = 30  # MA30 至少需要 30 根
MA_STREAK_FULL_HISTORY = 59  # 排列 streak 满口径需要 30+30-1 根
CONVERGE_LAG_DAYS = 5
SENSITIVITY_CONVERGE_LAGS = (3, 5, 8)
SPEARMAN_CUT = 0.7
SENSITIVITY_SPEARMAN_CUTS = (0.6, 0.7, 0.8)
TIGHTNESS_MAX_PCT = 3.0
SENSITIVITY_TIGHTNESS = (2.0, 3.0, 5.0)
SMALL_GAIN_CAP_PCT = 1.5
SENSITIVITY_SMALL_GAIN_CAPS = (1.0, 1.5, 2.0)
LOW_POSITION_126D_MAX = 0.25
WAVE_POSITION_20D_MAX = 0.35
WAVE_DAYS_SINCE_LOW_MAX = 3
MA10_OSCILLATE_MIN_CROSSES = 2
SHADOW_BALANCE_MIN = 0.5
PREMARKET_FORWARD_DAYS = 5
PREMARKET_MIN_HISTORY = 130  # position_126d 需要 126 根 + 余量
PREMARKET_BAR_SLICE = 140  # frame 2 单次特征计算的 bars 上限（>=126 窗口）
PREMARKET_LABEL_MAX_MARKET_SPAN = 10  # 5 个个股交易日不得跨越 10 个市场交易日
PREMARKET_TAIL_EXCLUDE_MARKET_DAYS = 5
MISSED_LEADER3_LIST_MAX = 50

# 数值区分度/月度一致性分析的键（布尔键走 0/1 对照；ma_history_bars 仅诊断不参与）
STRUCTURE_NUMERIC_KEYS = (
    "ma_bear_align",
    "ma_bear_days",
    "ma_bull_align",
    "ma_bull_days",
    "ma_spread_10_20_pct",
    "ma_spread_20_30_pct",
    "ma_converge_10_20_5d",
    "ma10_slope_5d_pct",
    "ma10_cross20_up_5d",
    "ma_tightness_pct",
    "close_above_ma10",
    "above_ma10_streak",
    "ma10_cross_count_20d",
    "vol_spearman_5d",
    "vol_spearman_10d",
    "vol_up_streak",
    "vol_down_streak",
    "small_gain_days_5d",
    "days_since_20d_low",
    "d1_shadow_balance",
    "position_20d",
    "bias_ma5_pct",
    "bias_ma20_pct",
    "turnover_1d_vs_20d",
)

# 共线性对照：新键（不含布尔）vs 预计高相关的既有键
_COLLINEARITY_KEYS = (
    "ma_bear_days",
    "ma_bull_days",
    "ma_spread_10_20_pct",
    "ma_spread_20_30_pct",
    "ma_converge_10_20_5d",
    "ma10_slope_5d_pct",
    "ma_tightness_pct",
    "above_ma10_streak",
    "ma10_cross_count_20d",
    "vol_spearman_5d",
    "vol_spearman_10d",
    "small_gain_days_5d",
    "days_since_20d_low",
    "position_20d",
    "bias_ma5_pct",
    "bias_ma20_pct",
    "turnover_1d_vs_20d",
    "return_20d_pct",
    "position_126d",
    "drawdown_from_126d_high_pct",
    "rebound_from_126d_low_pct",
    "volume_ratio_5_60",
    "turnover_ratio_3d_vs_prev7d",
    "prelude_vol_cv_7d",
)

_RESEARCH_NOTES = (
    "均线窗口 5/10/20/30 为主人指定、固定不动；派生阈值（收拢 5 日、spearman 0.7、紧凑 3%、小阳 1.5%）"
    "全部预声明 in-sample，敏感性只做预声明档位，不做网格搜索。",
    "进生产硬条件前要求月度一致率 >=0.7 且 2026-06/07 方向不翻转；不达标无论全样本 AUC 多高都标证据不足。",
    "样本窗口 2025-06 起为单边牛+一次崩盘（2026-07），index_above_ma20=False 集中在 7 月——"
    "市况分型只有单 episode，只能给描述性结论，不算验证。",
    "盘前全市场框架（frame 2）候选股票日自相关（均线条件连日成立），v1 只报计数+lift 不做 CI。",
    "auction_gap_pct 是 D 日可观测（竞价结果），只能回答「已首板后谁延续」，不能预测「是否首板」；"
    "后者归盘前全市场框架的命中率。",
    "is_leader/eventual_peak/d1_* 是未来标签仅作对照；案例核查的日期与描述全部来自主人笔记，"
    "区间类核查用主人原话日期窗。",
)


# ── 均线/量能底层工具（纯函数）────────────────────────────────────────────


def _prefix_sums(values: Sequence[float | None]) -> tuple[list[float], list[int]]:
    """前缀和 + 有效计数（None 贡献 0 且不计数），配合 _ma_at 做全有效窗口均值。"""

    sums = [0.0]
    counts = [0]
    for value in values:
        sums.append(sums[-1] + (value or 0.0))
        counts.append(counts[-1] + (1 if value is not None else 0))
    return sums, counts


def _ma_at(
    sums: Sequence[float], counts: Sequence[int], index: int, window: int
) -> float | None:
    """values[index-window+1..index] 的均值；窗口内任一值缺失则 None。"""

    if index + 1 < window:
        return None
    if counts[index + 1] - counts[index + 1 - window] != window:
        return None
    return (sums[index + 1] - sums[index + 1 - window]) / window


# ── 共享纯函数：结构因子（回测器/盘前服务复用；全部 D-1 可观测）──────────────


def _structure_features(
    bars_before: Sequence[Mapping[str, object]],
    *,
    converge_lag: int = CONVERGE_LAG_DAYS,
    small_gain_cap: float = SMALL_GAIN_CAP_PCT,
) -> dict[str, object]:
    """首板前奏结构因子（均线结构/量能梯形/控盘小阳/波浪 + 复用 4 键）。

    ``bars_before`` = D-1 及之前的日线（升序）。历史不足的键一律 None
    （布尔键也 None，不把「算不出」混进「不成立」）。
    """

    out: dict[str, object] = {
        "ma_bear_align": None,
        "ma_bear_days": None,
        "ma_bull_align": None,
        "ma_bull_days": None,
        "ma_spread_10_20_pct": None,
        "ma_spread_20_30_pct": None,
        "ma_converge_10_20_5d": None,
        "ma10_slope_5d_pct": None,
        "ma10_cross20_up_5d": None,
        "ma_tightness_pct": None,
        "close_above_ma10": None,
        "above_ma10_streak": None,
        "ma10_cross_count_20d": None,
        "ma_state": None,
        "vol_spearman_5d": None,
        "vol_spearman_10d": None,
        "vol_up_streak": 0,
        "vol_down_streak": 0,
        "small_gain_days_5d": None,
        "days_since_20d_low": None,
        "d1_shadow_balance": None,
        "prior_return_5d_pct": None,
        "amplitude_20d_pct": None,
        "ma_history_bars": len(bars_before),
        # 复用生产口径 4 键（position_20d/bias_ma5_pct/bias_ma20_pct/turnover_1d_vs_20d）
        **_daily_position_volume_features(bars_before),
    }
    if not bars_before:
        return out

    # 均线族：前缀和 O(1) 取 MA，窗口切片上限覆盖 streak 满口径 + converge 滞后
    relevant = list(bars_before[-(MA_STREAK_FULL_HISTORY + converge_lag + 1) :])
    closes = [_number(row.get("close_price")) for row in relevant]
    n = len(closes)
    last = n - 1
    sums, counts = _prefix_sums(closes)
    last_close = closes[-1]

    def _ma(index: int, window: int) -> float | None:
        return _ma_at(sums, counts, index, window)

    ma10 = _ma(last, 10)
    ma20 = _ma(last, 20)
    ma30 = _ma(last, 30)

    if last_close and ma10:
        out["close_above_ma10"] = last_close >= ma10
    if n >= 10 and last_close:
        streak = 0
        index = last
        while index >= 9 and streak < MA_ALIGN_DAYS_CAP:
            close_value = closes[index]
            ma_value = _ma(index, 10)
            if close_value is None or ma_value is None or close_value < ma_value:
                break
            streak += 1
            index -= 1
        out["above_ma10_streak"] = streak

    if n >= 30 and last_close:
        out["ma_bear_align"] = bool(ma10 and ma20 and ma30 and ma10 < ma20 < ma30)
        out["ma_bull_align"] = bool(ma10 and ma20 and ma30 and ma10 > ma20 > ma30)
        bear = 0
        index = last
        while index >= 29 and bear < MA_ALIGN_DAYS_CAP:
            a, b, c = _ma(index, 10), _ma(index, 20), _ma(index, 30)
            if a is None or b is None or c is None or not (a < b < c):
                break
            bear += 1
            index -= 1
        out["ma_bear_days"] = bear
        bull = 0
        index = last
        while index >= 29 and bull < MA_ALIGN_DAYS_CAP:
            a, b, c = _ma(index, 10), _ma(index, 20), _ma(index, 30)
            if a is None or b is None or c is None or not (a > b > c):
                break
            bull += 1
            index -= 1
        out["ma_bull_days"] = bull
        if ma10 and ma20 and ma30:
            out["ma_spread_10_20_pct"] = round((ma10 - ma20) / last_close * 100, 4)
            out["ma_spread_20_30_pct"] = round((ma20 - ma30) / last_close * 100, 4)
            tight = (max(ma10, ma20, ma30) - min(ma10, ma20, ma30)) / last_close * 100
            out["ma_tightness_pct"] = round(tight, 4)

    # 收拢/方向/金叉（MA10↔MA20）
    prev_index = last - converge_lag
    if prev_index >= 19 and last_close:
        prev_close = closes[prev_index]
        prev_ma10, prev_ma20 = _ma(prev_index, 10), _ma(prev_index, 20)
        if prev_close and prev_ma10 and prev_ma20 and ma10 and ma20:
            spread_now = (ma10 - ma20) / last_close * 100
            spread_prev = (prev_ma10 - prev_ma20) / prev_close * 100
            out["ma_converge_10_20_5d"] = round(abs(spread_prev) - abs(spread_now), 4)
        if prev_ma10 and ma10:
            out["ma10_slope_5d_pct"] = round((ma10 / prev_ma10 - 1) * 100, 4)
    if n >= 25:
        cross = False
        for j in range(last - 4, last + 1):
            prev_a, prev_b = _ma(j - 1, 10), _ma(j - 1, 20)
            curr_a, curr_b = _ma(j, 10), _ma(j, 20)
            if None in (prev_a, prev_b, curr_a, curr_b):
                continue
            if prev_a < prev_b and curr_a >= curr_b:
                cross = True
                break
        out["ma10_cross20_up_5d"] = cross

    # MA10 缠绕度：20 日内 close 穿越 MA10 的次数
    if n >= 29:
        signs: list[int] = []
        for index in range(last - 19, last + 1):
            close_value = closes[index]
            ma_value = _ma(index, 10)
            if close_value is None or ma_value is None:
                continue
            diff = close_value - ma_value
            signs.append(1 if diff > 0 else (-1 if diff < 0 else (signs[-1] if signs else 0)))
        crosses = 0
        for position in range(len(signs) - 1):
            earlier, later = signs[position], signs[position + 1]
            if earlier != 0 and later != 0 and earlier != later:
                crosses += 1
        out["ma10_cross_count_20d"] = crosses

    # ma_state 四分类（历史不足 None）
    if out["ma_bull_align"] is True:
        out["ma_state"] = "bull"
    elif out["ma_bear_align"] is True:
        converging = (out["ma_converge_10_20_5d"] or 0.0) > 0 or out[
            "ma10_cross20_up_5d"
        ] is True
        out["ma_state"] = "bear_converging" if converging else "bear_diverging"
    elif out["ma_bear_align"] is not None:
        out["ma_state"] = "tangled"

    # 量能梯形（窗口必须全有效）
    turnovers = [_number(row.get("turnover")) for row in bars_before[-10:]]
    for window, key in ((5, "vol_spearman_5d"), (10, "vol_spearman_10d")):
        values = turnovers[-window:]
        if len(values) == window and all(v is not None and v > 0 for v in values):
            rho = _spearman_pairs(
                [float(v) for v in values if v is not None],
                [float(k) for k in range(1, window + 1)],
            )
            out[key] = round(rho, 4) if rho is not None else None
    up_streak = 0
    for index in range(len(turnovers) - 1, 0, -1):
        current, previous = turnovers[index], turnovers[index - 1]
        if current is None or previous is None or current <= 0 or current <= previous:
            break
        up_streak += 1
        if up_streak >= 5:
            break
    out["vol_up_streak"] = up_streak
    down_streak = 0
    for index in range(len(turnovers) - 1, 0, -1):
        current, previous = turnovers[index], turnovers[index - 1]
        if current is None or previous is None or previous <= 0 or current >= previous:
            break
        down_streak += 1
        if down_streak >= 5:
            break
    out["vol_down_streak"] = down_streak

    # 控盘小阳：近 5 日 0 < 涨幅 <= cap 的天数
    if len(bars_before) >= 5:
        changes = [_number(row.get("change_pct")) for row in bars_before[-5:]]
        out["small_gain_days_5d"] = sum(
            1 for value in changes if value is not None and 0 < value <= small_gain_cap
        )

    # 过滤器工具键（生产低位四条件口径用；不进 STRUCTURE_NUMERIC_KEYS）
    if len(bars_before) >= 6:
        base_close = _number(bars_before[-6].get("close_price"))
        if last_close and base_close and base_close > 0:
            out["prior_return_5d_pct"] = round((last_close / base_close - 1) * 100, 4)
    if len(bars_before) >= 20:
        w20 = bars_before[-20:]
        highs20 = [v for v in (_number(row.get("high_price")) for row in w20) if v]
        lows20 = [v for v in (_number(row.get("low_price")) for row in w20) if v]
        if highs20 and lows20 and min(lows20) > 0:
            out["amplitude_20d_pct"] = round(
                (max(highs20) - min(lows20)) / min(lows20) * 100, 4
            )

    # 波浪：20 日摆动低点距今（镜像 days_since_126d_low 口径）
    if len(bars_before) >= 20:
        lows = [_number(row.get("low_price")) for row in bars_before[-20:]]
        if all(value is not None for value in lows):
            out["days_since_20d_low"] = 19 - min(
                range(20), key=lambda index: lows[index] or 0.0
            )

    # D-1 上下影线匀称度（探索键，单案例假说）
    d1 = bars_before[-1]
    open_price = _number(d1.get("open_price"))
    high_price = _number(d1.get("high_price"))
    low_price = _number(d1.get("low_price"))
    close_price = _number(d1.get("close_price"))
    if None not in (open_price, high_price, low_price, close_price):
        upper = (high_price or 0.0) - max(open_price or 0.0, close_price or 0.0)
        lower = min(open_price or 0.0, close_price or 0.0) - (low_price or 0.0)
        if upper >= 0 and lower >= 0 and max(upper, lower) > 0:
            out["d1_shadow_balance"] = round(min(upper, lower) / max(upper, lower), 4)
    return out


# ── 指数 regime（研究口径：严格 >=20 根，不足 None；不用生产 fail-open 版）─────


def _index_regime_map(
    index_rows: Sequence[Mapping[str, object]],
) -> tuple[list[str], dict[str, bool]]:
    """（排序日期列表, 日期→close>=MA20）；不足 20 根的早期日期缺席（=None）。"""

    rows = sorted(index_rows, key=lambda row: str(row.get("trade_date") or ""))
    dates = [str(row.get("trade_date") or "") for row in rows]
    closes = [_number(row.get("close_price")) for row in rows]
    regime: dict[str, bool] = {}
    for index in range(19, len(rows)):
        window = closes[index - 19 : index + 1]
        if any(value is None for value in window):
            continue
        regime[dates[index]] = bool(closes[index] and closes[index] >= mean(window))  # type: ignore[arg-type]
    return dates, regime


def _index_regime_at(
    index_dates: Sequence[str],
    regime_map: Mapping[str, bool],
    obs_date: str,
) -> bool | None:
    """观测日（含）之前最近一个指数交易日的 regime；无数据 None。"""

    position = bisect_right(index_dates, obs_date) - 1
    if position < 0:
        return None
    return regime_map.get(index_dates[position])


# ── attach：因子样本追加结构特征 + 竞价缺口 + regime ─────────────────────────


def attach_structure_features(
    factor_samples: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    *,
    converge_lag: int = CONVERGE_LAG_DAYS,
    small_gain_cap: float = SMALL_GAIN_CAP_PCT,
) -> list[dict[str, object]]:
    """给 build_factor_samples 的因子样本追加结构特征（后处理，不重写样本抽取）。

    同时附加 ``auction_gap_pct``（D 日开盘/D-1 收盘，D 日可观测标签）与
    ``index_above_ma20``（D-1 可观测 regime 标签）。
    """

    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    dates_by_symbol: dict[str, list[str]] = {}
    for symbol, rows in bars_by_symbol.items():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
        dates_by_symbol[symbol] = [str(row.get("trade_date") or "") for row in rows]
    index_dates, index_regime = _index_regime_map(bars_by_symbol.get(INDEX_VT_SYMBOL, []))

    attached: list[dict[str, object]] = []
    for sample in factor_samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        rows = bars_by_symbol.get(symbol, [])
        dates = dates_by_symbol.get(symbol, [])
        d_index = bisect_left(dates, trade_date)
        merged = dict(sample)
        merged.update(
            _structure_features(
                rows[:d_index], converge_lag=converge_lag, small_gain_cap=small_gain_cap
            )
        )
        # 前奏量能键（prelude_vol_cv_7d/shift_ratio，供主人规则 R7 平稳待突判定）
        merged.update(_prelude_pattern_features(rows[:d_index]))
        # 长窗键（position_126d/drawdown/rebound 等，供生产低位/tight 组合判定；
        # frame-1 样本已有同值键，覆盖写恒等）
        merged.update(_long_window_features(rows[:d_index]))
        d1_close = (
            _number(rows[d_index - 1].get("close_price")) if d_index >= 1 else None
        )
        d_open = (
            _number(rows[d_index].get("open_price"))
            if d_index < len(rows) and dates[d_index] == trade_date
            else None
        )
        merged["auction_gap_pct"] = (
            round((d_open / d1_close - 1) * 100, 4)
            if d_open is not None and d1_close
            else None
        )
        d1_date = dates[d_index - 1] if d_index >= 1 else ""
        merged["index_above_ma20"] = (
            _index_regime_at(index_dates, index_regime, d1_date) if d1_date else None
        )
        attached.append(merged)
    return attached


# ── 分析块 ①：案例核查（主人 14 个锚点案例逐条裁决）─────────────────────────


def _case_context(
    bars_before: Sequence[Mapping[str, object]],
    bars_after: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """案例核查上下文：结构/长窗/中窗因子 + 原始 bars 与前缀和（供区间类核查）。

    ``bars_after`` = 首板日及之后的日线（仅案例核查用于「首板日起放量」类
    D 日描述核对，绝不进任何 D-1 因子）。
    """

    bars = list(bars_before)
    closes = [_number(row.get("close_price")) for row in bars]
    sums, counts = _prefix_sums(closes)
    return {
        "bars": bars,
        "bars_after": list(bars_after),
        "dates": [str(row.get("trade_date") or "") for row in bars],
        "closes": closes,
        "_sums": sums,
        "_counts": counts,
        **_structure_features(bars),
        **_long_window_features(bars),
        **_mid_window_features(bars),
    }


def _ctx_ma(ctx: Mapping[str, object], index: int, window: int) -> float | None:
    return _ma_at(ctx["_sums"], ctx["_counts"], index, window)  # type: ignore[arg-type]


def _range_vol_spearman(
    ctx: Mapping[str, object], start: str, end: str
) -> float | None:
    """主人口径区间内的量能梯形度（turnover 与日序 spearman，>=3 个有效点）。"""

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    left, right = bisect_left(dates, start), bisect_right(dates, end)
    values = [
        value
        for value in (_number(row.get("turnover")) for row in bars[left:right])
        if value is not None and value > 0
    ]
    if len(values) < 3:
        return None
    rho = _spearman_pairs(values, [float(k) for k in range(1, len(values) + 1)])
    return round(rho, 4) if rho is not None else None


def _range_return_pct(ctx: Mapping[str, object], start: str, end: str) -> float | None:
    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    left, right = bisect_left(dates, start), bisect_right(dates, end) - 1
    if left > right or right < 0 or left >= len(bars):
        return None
    first = _number(bars[left].get("close_price"))
    last_close = _number(bars[right].get("close_price"))
    if not first or not last_close:
        return None
    return round((last_close / first - 1) * 100, 4)


def _value_at(ctx: Mapping[str, object], day: str, field: str) -> float | None:
    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    index = bisect_left(dates, day)
    if index >= len(bars) or dates[index] != day:
        return None
    return _number(bars[index].get(field))


def _closes_below_ma_between(
    ctx: Mapping[str, object], window: int, start: str, end: str
) -> bool | None:
    """区间内每日收盘都在 MA(window) 下方；任一天 MA 不可算 → None。"""

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    left, right = bisect_left(dates, start), bisect_right(dates, end)
    if left >= right:
        return None
    for index in range(left, right):
        close_value = _number(bars[index].get("close_price"))
        ma_value = _ctx_ma(ctx, index, window)
        if close_value is None or ma_value is None:
            return None
        if close_value >= ma_value:
            return False
    return True


def _had_close_below_ma_within(
    ctx: Mapping[str, object], window: int, days: int
) -> bool | None:
    """最近 ``days`` 个交易日内是否**曾**收破 MA(window)（任一天 MA 不可算 → None）。"""

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    if len(dates) < days:
        return None
    found = False
    for index in range(len(dates) - days, len(dates)):
        close_value = _number(bars[index].get("close_price"))
        ma_value = _ctx_ma(ctx, index, window)
        if close_value is None or ma_value is None:
            return None
        if close_value < ma_value:
            found = True
    return found


def _first_close_below_ma_since(
    ctx: Mapping[str, object], window: int, start: str
) -> str | None:
    """start 起（含）至 D-1 第一个收破 MA(window) 的日期；全程未破 → ""；不可算 → None。"""

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    for index in range(bisect_left(dates, start), len(dates)):
        close_value = _number(bars[index].get("close_price"))
        ma_value = _ctx_ma(ctx, index, window)
        if close_value is None or ma_value is None:
            return None
        if close_value < ma_value:
            return dates[index]
    return ""


def _ma_hold_since(
    ctx: Mapping[str, object], window: int, start: str, tolerance: float
) -> tuple[bool | None, float | None, str | None]:
    """start 起沿 MA(window) 上方运行判定（主人口径：贴线不算下杀）。

    收盘偏离 < -tolerance（相对 MA 的比例）才算「下杀」。返回
    (是否全程未下杀, 最深偏离%, 最深偏离日)；任一天不可算 → (None, None, None)。
    """

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    worst_dev: float | None = None
    worst_date = ""
    for index in range(bisect_left(dates, start), len(dates)):
        close_value = _number(bars[index].get("close_price"))
        ma_value = _ctx_ma(ctx, index, window)
        if close_value is None or not ma_value:
            return None, None, None
        dev = close_value / ma_value - 1
        if worst_dev is None or dev < worst_dev:
            worst_dev, worst_date = dev, dates[index]
    if worst_dev is None:
        return None, None, None
    return worst_dev >= -tolerance, worst_dev * 100, worst_date


def _board_window_vol_spearman(
    ctx: Mapping[str, object], before_days: int, after_days: int
) -> float | None:
    """跨首板窗口的量能梯形度：D-1 前 ``before_days`` 天 + 首板日起 ``after_days`` 天。

    仅案例核查用（主人口径的梯形观察窗本来就含首板后）；>=3 个有效点。
    """

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    after: list[Mapping[str, object]] = ctx["bars_after"]  # type: ignore[assignment]
    values = [
        _number(row.get("turnover")) for row in bars[-before_days:]
    ] + [_number(row.get("turnover")) for row in after[:after_days]]
    valid = [value for value in values if value is not None and value > 0]
    if len(valid) < 3:
        return None
    rho = _spearman_pairs(valid, [float(k) for k in range(1, len(valid) + 1)])
    return round(rho, 4) if rho is not None else None


def _no_close_below_ma_since(
    ctx: Mapping[str, object], window: int, start: str
) -> bool | None:
    """start 起（含）至 D-1 没有一天收盘跌破 MA(window)。"""

    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    end = dates[-1] if dates else start
    return _closes_below_ma_between(ctx, window, start, end)


def _alignment_since(
    ctx: Mapping[str, object], kind: str, start: str, *, tolerance: float = 0.0
) -> bool | None:
    """start 起（含）至 D-1 每日都满足 bull/bear 排列；任一天不可算 → None。

    ``tolerance`` 为贴平容差（相对价差比例）：案例核查用于放过 ma20≈ma30
    打平这类视觉成立的日子；聚合因子（ma_bull_align 等）保持严格不用容差。
    """

    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    for index in range(bisect_left(dates, start), len(dates)):
        a, b, c = _ctx_ma(ctx, index, 10), _ctx_ma(ctx, index, 20), _ctx_ma(ctx, index, 30)
        if a is None or b is None or c is None:
            return None
        if tolerance > 0:
            close_value = _number(bars[index].get("close_price")) or 0.0
            gap = close_value * tolerance
            holds = a >= b - gap and b >= c - gap if kind == "bull" else a <= b + gap and b <= c + gap
        else:
            holds = a > b > c if kind == "bull" else a < b < c
        if not holds:
            return False
    return True


def _spread_at(ctx: Mapping[str, object], day: str) -> float | None:
    bars: list[Mapping[str, object]] = ctx["bars"]  # type: ignore[assignment]
    dates: list[str] = ctx["dates"]  # type: ignore[assignment]
    index = bisect_left(dates, day)
    if index >= len(bars) or dates[index] != day:
        return None
    close_value = _number(bars[index].get("close_price"))
    a, b = _ctx_ma(ctx, index, 10), _ctx_ma(ctx, index, 20)
    if not close_value or a is None or b is None:
        return None
    return round((a - b) / close_value * 100, 4)


def _v(
    value: object, ok: Callable[[float], bool], fmt: str = "{:.2f}"
) -> tuple[bool | None, str]:
    """核查裁决包装：None → (None, 数据不足)；否则 (判定, 数值证据)。"""

    number = _sample_float(value)
    if number is None:
        return None, "数据不足"
    return bool(ok(number)), fmt.format(number)


def _b(value: object, expect: bool, label: str) -> tuple[bool | None, str]:
    """布尔核查包装：None → 数据不足；判定 = (value 是否为 expect)；证据显示原值。"""

    if value is None:
        return None, "数据不足"
    boolean = bool(value)
    return boolean is expect, f"{label}={boolean}"


CASE_AUDIT: tuple[dict[str, object], ...] = (
    {
        "name": "哈药股份",
        "first_board": "2026-07-10",
        "note": "空头排列背景+均线收拢+绝对低位+量先萎缩、首板日起放量梯形",
        "claims": (
            {"id": "bear15", "desc": "接近1个月空头排列（MA10<MA20<MA30 连续≥15日）",
             "check": lambda c: _v(c.get("ma_bear_days"), lambda v: v >= 15, "{:.0f} 天")},
            {"id": "converge", "desc": "7-6 起均线极速收拢（10/20 价差 5 日收窄）",
             "check": lambda c: _v(c.get("ma_converge_10_20_5d"), lambda v: v > 0, "{:.2f}pt")},
            {"id": "lowpos", "desc": "绝对低位（半年区间位置≤0.25）",
             "check": lambda c: _v(c.get("position_126d"), lambda v: v <= LOW_POSITION_126D_MAX)},
            {"id": "trap_down", "desc": "首板前成交量逐渐萎缩（D-5..D-1 spearman≤-0.5）",
             "check": lambda c: _v(c.get("vol_spearman_5d"), lambda v: v <= -0.5)},
            {"id": "expand_at_board", "desc": "首板日起放量（首板日成交额/前日≥2，D日核对）",
             "check": lambda c: (
                 (lambda before, after: (
                     (None, "数据不足") if not before or not after
                     else (after / before >= 2.0, f"{before / 1e8:.2f}亿→{after / 1e8:.2f}亿")
                 ))(
                     _number((c["bars"] or [{}])[-1].get("turnover")),  # type: ignore[index]
                     _number((c["bars_after"] or [{}])[0].get("turnover")),  # type: ignore[index]
                 ))},
        ),
    },
    {
        "name": "立新能源",
        "first_board": "2026-07-16",
        "note": "量从萎缩到逐步规则放大（7-14..7-21 梯形）+重新站上10日线",
        "claims": (
            {"id": "above_ma10", "desc": "重新站上 10 日线（D-1 收盘≥MA10）",
             "check": lambda c: _b(c.get("close_above_ma10"), True, "close≥MA10")},
            {"id": "trap_expand_range", "desc": "7-14..7-21 逐步梯形放量（含首板后，区间 spearman≥0.7）",
             "check": lambda c: _v(_board_window_vol_spearman(c, 2, 4), lambda v: v >= SPEARMAN_CUT)},
        ),
    },
    {
        "name": "爱丽家居",
        "first_board": "2026-07-21",
        "note": "W形+跌破20日线但放量梯形规则",
        "claims": (
            {"id": "below_ma20", "desc": "前 4 日曾跌破 20 日线",
             "check": lambda c: _b(_had_close_below_ma_within(c, 20, 4), True, "前4日曾收破MA20")},
            {"id": "trap_up", "desc": "逐步放量成梯形（5 日 spearman≥0.7）",
             "check": lambda c: _v(c.get("vol_spearman_5d"), lambda v: v >= SPEARMAN_CUT)},
            {"id": "wave_low", "desc": "回到前低（20 日位置≤0.35 且低点距今≤2 日）",
             "check": lambda c: (
                 (lambda pos, low: (
                     (None, "数据不足") if pos is None or low is None
                     else (pos <= WAVE_POSITION_20D_MAX and low <= 2,
                           f"pos20={pos:.2f},low={low:.0f}天")
                 ))(_sample_float(c.get("position_20d")), _sample_float(c.get("days_since_20d_low"))))},
        ),
    },
    {
        "name": "传智教育",
        "first_board": "2026-07-27",
        "note": "前一日站上10日线+7-15..7-24缩量梯形+10日线已在20日线上方",
        "claims": (
            {"id": "above_ma10", "desc": "前一日站上 10 日线",
             "check": lambda c: _b(c.get("close_above_ma10"), True, "close≥MA10")},
            {"id": "trap_down_range", "desc": "7-15..7-24 缩量梯形（区间 spearman≤-0.7）",
             "check": lambda c: _v(_range_vol_spearman(c, "2026-07-15", "2026-07-24"), lambda v: v <= -SPEARMAN_CUT)},
            {"id": "cross20", "desc": "10 日线已在 20 日线上方（spread>0）",
             "check": lambda c: _v(c.get("ma_spread_10_20_pct"), lambda v: v > 0, "{:.2f}%")},
        ),
    },
    {
        "name": "一鸣食品",
        "first_board": "2026-07-28",
        "note": "7-20起缩量梯形+前一日站稳",
        "claims": (
            {"id": "trap_down_range", "desc": "7-20 起缩量梯形（区间 spearman≤-0.7）",
             "check": lambda c: _v(_range_vol_spearman(c, "2026-07-20", "2026-07-27"), lambda v: v <= -SPEARMAN_CUT)},
            {"id": "stabilize", "desc": "前一日站稳未续跌（7-27 涨幅≥0）",
             "check": lambda c: _v(_value_at(c, "2026-07-27", "change_pct"), lambda v: v >= 0, "{:.2f}%")},
        ),
    },
    {
        "name": "高争民爆",
        "first_board": "2026-07-29",
        "note": "MA10波浪缠绕+7-14后未再下杀+上下影线均匀",
        "claims": (
            {"id": "oscillate", "desc": "MA10 反复缠绕（20 日穿越≥2 次）",
             "check": lambda c: _v(c.get("ma10_cross_count_20d"), lambda v: v >= MA10_OSCILLATE_MIN_CROSSES, "{:.0f} 次")},
            {"id": "no_break", "desc": "7-14 起沿 MA10 上方运行（收盘破线>1.5% 才算下杀）",
             "check": lambda c: (
                 (lambda holds, worst, day: (
                     (None, "数据不足") if holds is None
                     else (holds, f"最深偏离{worst:+.2f}%({day})")  # type: ignore[str-format]
                 ))(*_ma_hold_since(c, 10, "2026-07-14", 0.015)))},
            {"id": "shadow", "desc": "D-1 上下影线匀称（balance≥0.5）",
             "check": lambda c: _v(c.get("d1_shadow_balance"), lambda v: v >= SHADOW_BALANCE_MIN)},
        ),
    },
    {
        "name": "均瑶健康",
        "first_board": "2026-07-29",
        "note": "MA10缠绕+前一日又起稳到10日线上方",
        "claims": (
            {"id": "oscillate", "desc": "MA10 反复缠绕（20 日穿越≥2 次）",
             "check": lambda c: _v(c.get("ma10_cross_count_20d"), lambda v: v >= MA10_OSCILLATE_MIN_CROSSES, "{:.0f} 次")},
            {"id": "above_ma10", "desc": "前一日起稳到 10 日线上方",
             "check": lambda c: _b(c.get("close_above_ma10"), True, "close≥MA10")},
        ),
    },
    {
        "name": "华天酒店",
        "first_board": "2026-07-27",
        "note": "与均瑶健康如出一辙+7-24未站稳10日线+量明显萎缩",
        "claims": (
            {"id": "oscillate", "desc": "MA10 反复缠绕（20 日穿越≥2 次）",
             "check": lambda c: _v(c.get("ma10_cross_count_20d"), lambda v: v >= MA10_OSCILLATE_MIN_CROSSES, "{:.0f} 次")},
            {"id": "below_ma10_d1", "desc": "7-24 未站稳 10 日线（主人预期=不满足）",
             "check": lambda c: _b(c.get("close_above_ma10"), False, "close≥MA10")},
            {"id": "vol_shrink", "desc": "成交量明显萎缩（5 日 spearman≤-0.7 或连缩≥2）",
             "check": lambda c: (
                 (lambda sp, dn: (
                     (None, "数据不足") if sp is None and not dn
                     else ((sp is not None and sp <= -SPEARMAN_CUT) or (dn or 0) >= 2,
                           f"spearman5={sp},down_streak={dn}")
                 ))(_sample_float(c.get("vol_spearman_5d")), c.get("vol_down_streak")))},
        ),
    },
    {
        "name": "顺钠股份",
        "first_board": "2026-07-23",
        "note": "7-15..7-20温和下跌但放量梯形+7-21起止跌",
        "claims": (
            {"id": "trap_up_down", "desc": "7-15..7-20 放量下跌（spearman≥0.7 且区间跌）",
             "check": lambda c: (
                 (lambda sp, ret: (
                     (None, "数据不足") if sp is None or ret is None
                     else (sp >= SPEARMAN_CUT and ret < 0, f"spearman={sp:.2f},ret={ret:.2f}%")
                 ))(_range_vol_spearman(c, "2026-07-15", "2026-07-20"),
                    _range_return_pct(c, "2026-07-15", "2026-07-20")))},
            {"id": "stop_fall", "desc": "7-21 起止跌（7-21/7-22 收盘不低于 7-20）",
             "check": lambda c: (
                 (lambda base, d1, d2: (
                     (None, "数据不足") if None in (base, d1, d2)
                     else (d1 >= base and d2 >= base,  # type: ignore[operator]
                           f"7-20={base:.2f},7-21={d1:.2f},7-22={d2:.2f}")
                 ))(_value_at(c, "2026-07-20", "close_price"),
                    _value_at(c, "2026-07-21", "close_price"),
                    _value_at(c, "2026-07-22", "close_price")))},
        ),
    },
    {
        "name": "新亚制程",
        "first_board": "2026-07-24",
        "note": "7-17..7-21放量下跌+7-22..7-23企稳放量上涨",
        "claims": (
            {"id": "trap_up_down", "desc": "7-17..7-21 放量下跌（spearman≥0.7 且区间跌）",
             "check": lambda c: (
                 (lambda sp, ret: (
                     (None, "数据不足") if sp is None or ret is None
                     else (sp >= SPEARMAN_CUT and ret < 0, f"spearman={sp:.2f},ret={ret:.2f}%")
                 ))(_range_vol_spearman(c, "2026-07-17", "2026-07-21"),
                    _range_return_pct(c, "2026-07-17", "2026-07-21")))},
            {"id": "stabilize_up", "desc": "7-22..7-23 企稳放量上涨（两连涨且量增）",
             "check": lambda c: (
                 (lambda c1, c2, v1, v2: (
                     (None, "数据不足") if None in (c1, c2, v1, v2)
                     else (c1 > 0 and c2 > 0 and v2 > v1,  # type: ignore[operator]
                           f"chg=({c1:.2f}%,{c2:.2f}%),vol=({v1:.0f},{v2:.0f})")
                 ))(_value_at(c, "2026-07-22", "change_pct"),
                    _value_at(c, "2026-07-23", "change_pct"),
                    _value_at(c, "2026-07-22", "turnover"),
                    _value_at(c, "2026-07-23", "turnover")))},
        ),
    },
    {
        "name": "大有能源",
        "first_board": "2026-06-01",
        "note": "5-25..27缩量下跌+5-28..29放量上涨+涨幅控制1%贴5日线",
        "claims": (
            {"id": "trap_down_range", "desc": "5-25..5-27 缩量下跌（spearman≤-0.5 且区间跌）",
             "check": lambda c: (
                 (lambda sp, ret: (
                     (None, "数据不足") if sp is None or ret is None
                     else (sp <= -0.5 and ret < 0, f"spearman={sp:.2f},ret={ret:.2f}%")
                 ))(_range_vol_spearman(c, "2026-05-25", "2026-05-27"),
                    _range_return_pct(c, "2026-05-25", "2026-05-27")))},
            {"id": "control_gain", "desc": "5-28/5-29 涨幅控制在 1.5% 以内（均>0）",
             "check": lambda c: (
                 (lambda c1, c2: (
                     (None, "数据不足") if None in (c1, c2)
                     else (0 < c1 <= 1.5 and 0 < c2 <= 1.5, f"{c1:.2f}%,{c2:.2f}%")  # type: ignore[operator]
                 ))(_value_at(c, "2026-05-28", "change_pct"),
                    _value_at(c, "2026-05-29", "change_pct")))},
            {"id": "hug_ma5", "desc": "贴合 5 日线（|bias_ma5|≤1.5%）",
             "check": lambda c: _v(c.get("bias_ma5_pct"), lambda v: abs(v) <= 1.5, "{:.2f}%")},
            {"id": "ma5_below_ma10", "desc": "5 日线在 10 日线下方（D-1 MA5<MA10）",
             "check": lambda c: (
                 (lambda a, b: (
                     (None, "数据不足") if a is None or b is None
                     else (a < b, f"MA5={a:.3f},MA10={b:.3f}")
                 ))(_ctx_ma(c, len(c["dates"]) - 1, 5), _ctx_ma(c, len(c["dates"]) - 1, 10)))},  # type: ignore[arg-type]
        ),
    },
    {
        "name": "中重科技",
        "first_board": "2026-06-03",
        "note": "5-22..29持续5日线下方+6-1量缩企稳+6-1..6-2放量上涨+站稳5日线附近",
        "claims": (
            {"id": "below_ma5", "desc": "5-22..5-29 持续收在 5 日线下方",
             "check": lambda c: _b(
                 _closes_below_ma_between(c, 5, "2026-05-22", "2026-05-29"),
                 True, "5-22..29收破MA5")},
            {"id": "shrink_expand", "desc": "6-1 量缩企稳、6-1..6-2 放量上涨",
             "check": lambda c: (
                 (lambda v0, v1, v2, ch1, ch2: (
                     (None, "数据不足") if None in (v0, v1, v2, ch1, ch2)
                     else (v1 < v0 and ch1 >= 0 and v2 > v1 and ch2 > 0,  # type: ignore[operator]
                           f"vol=({v0:.0f},{v1:.0f},{v2:.0f}),chg=({ch1:.2f}%,{ch2:.2f}%)")
                 ))(_value_at(c, "2026-05-29", "turnover"),
                    _value_at(c, "2026-06-01", "turnover"),
                    _value_at(c, "2026-06-02", "turnover"),
                    _value_at(c, "2026-06-01", "change_pct"),
                    _value_at(c, "2026-06-02", "change_pct")))},
            {"id": "near_ma5", "desc": "6-2 站稳 5 日线附近（|bias_ma5|≤2%）",
             "check": lambda c: _v(c.get("bias_ma5_pct"), lambda v: abs(v) <= 2.0, "{:.2f}%")},
        ),
    },
    {
        "name": "金钼股份",
        "first_board": "2026-06-11",
        "note": "波浪向上+回落企稳+5-26曾首板",
        "claims": (
            {"id": "bull", "desc": "波浪向上（MA10>MA20>MA30）",
             "check": lambda c: _b(c.get("ma_bull_align"), True, "MA10>MA20>MA30")},
            {"id": "pullback_low", "desc": "回落至 20 日低位企稳（位置≤0.35 且低点≤3 日）",
             "check": lambda c: (
                 (lambda pos, low: (
                     (None, "数据不足") if pos is None or low is None
                     else (pos <= WAVE_POSITION_20D_MAX and low <= WAVE_DAYS_SINCE_LOW_MAX,
                           f"pos20={pos:.2f},low={low:.0f}天")
                 ))(_sample_float(c.get("position_20d")), _sample_float(c.get("days_since_20d_low"))))},
            {"id": "prior_board", "desc": "5-26 曾首板（首板事件集核对）",
             "check": lambda c: _b(
                 (c["vt_symbol"], "2026-05-26") in c["first_board_index"],
                 True, "5-26在首板集")},
        ),
    },
    {
        "name": "诺德股份",
        "first_board": "2026-06-15",
        "note": "6-4起重回多头排列+5-21时10日线在20日线下方",
        "claims": (
            {"id": "bull", "desc": "多头排列（MA10>MA20>MA30）",
             "check": lambda c: _b(c.get("ma_bull_align"), True, "MA10>MA20>MA30")},
            {"id": "bull_since", "desc": "6-4 起持续多头（每日 MA10>MA20>MA30，贴平容差 0.1%）",
             "check": lambda c: _b(
                 _alignment_since(c, "bull", "2026-06-04", tolerance=0.001),
                 True, "6-4起持续多头")},
            {"id": "was_bear", "desc": "5-21 时 10 日线在 20 日线下方（spread<0）",
             "check": lambda c: _v(_spread_at(c, "2026-05-21"), lambda v: v < 0, "{:.2f}%")},
        ),
    },
)


def _audit_cases(
    daily_bars: Sequence[Mapping[str, object]],
    first_board_index: Mapping[tuple[str, str], object],
    names: Mapping[str, str],
) -> dict[str, object]:
    """14 个锚点案例逐条核查：首板日完整性 + 每条主人描述的数据裁决。"""

    name_to_symbol: dict[str, str] = {}
    for symbol, name in names.items():
        name_to_symbol.setdefault(str(name), symbol)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for rows in bars_by_symbol.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))

    cases: list[dict[str, object]] = []
    totals = {"passed": 0, "failed": 0, "insufficient": 0}
    for case in CASE_AUDIT:
        name = str(case["name"])
        board_day = str(case["first_board"])
        symbol = name_to_symbol.get(name)
        row: dict[str, object] = {
            "name": name,
            "first_board": board_day,
            "note": case["note"],
            "vt_symbol": symbol,
            "in_first_board_set": False,
            "eventual_peak": None,
            "board_change_pct": None,
            "claims": [],
        }
        if symbol is None:
            row["status"] = "unresolved"
            cases.append(row)
            continue
        rows = bars_by_symbol.get(symbol, [])
        dates = [str(bar.get("trade_date") or "") for bar in rows]
        d_index = bisect_left(dates, board_day)
        row["in_first_board_set"] = (symbol, board_day) in first_board_index
        row["eventual_peak"] = first_board_index.get((symbol, board_day))
        if d_index < len(rows) and dates[d_index] == board_day:
            row["board_change_pct"] = _number(rows[d_index].get("change_pct"))
        ctx = _case_context(rows[:d_index], rows[d_index : d_index + 4])
        ctx["vt_symbol"] = symbol
        ctx["first_board_index"] = first_board_index
        claim_rows: list[dict[str, object]] = []
        for claim in case["claims"]:  # type: ignore[union-attr]
            verdict, evidence = claim["check"](ctx)
            if verdict is None:
                totals["insufficient"] += 1
            elif verdict:
                totals["passed"] += 1
            else:
                totals["failed"] += 1
            claim_rows.append(
                {
                    "id": claim["id"],
                    "desc": claim["desc"],
                    "verdict": (
                        "数据不足" if verdict is None else ("符合" if verdict else "不符合")
                    ),
                    "evidence": evidence,
                }
            )
        row["claims"] = claim_rows
        row["status"] = "ok"
        cases.append(row)
    return {
        "cases": cases,
        "cases_resolved": sum(1 for case in cases if case.get("status") == "ok"),
        "claims_total": sum(totals.values()),
        **{f"claims_{key}": value for key, value in totals.items()},
    }


# ── 预登记组合（子条件化，供组合统计 + 漏网归因 + frame 2 共用）────────────────


def _ge(value: object, threshold: float) -> bool:
    number = _sample_float(value)
    return number is not None and number >= threshold


def _le(value: object, threshold: float) -> bool:
    number = _sample_float(value)
    return number is not None and number <= threshold


def _gt(value: object, threshold: float) -> bool:
    number = _sample_float(value)
    return number is not None and number > threshold


_COMBO_CLAUSES: tuple[tuple[str, str, tuple[tuple[str, Callable[[Mapping[str, object]], bool]], ...]], ...] = (
    (
        "lowpos_converge",
        "低位 + 空头排列≥15日 + (收拢或金叉) + 收盘≥MA10",
        (
            ("low_position", lambda s: _le(s.get("position_126d"), LOW_POSITION_126D_MAX)),
            ("bear15", lambda s: _ge(s.get("ma_bear_days"), 15)),
            ("converge_or_cross", lambda s: _gt(s.get("ma_converge_10_20_5d"), 0) or s.get("ma10_cross20_up_5d") is True),
            ("above_ma10", lambda s: s.get("close_above_ma10") is True),
        ),
    ),
    (
        "lowpos_converge_strict",
        "低位 + 空头排列≥15日 + (收拢或金叉) + 站稳MA10≥2日 + MA10上行",
        (
            ("low_position", lambda s: _le(s.get("position_126d"), LOW_POSITION_126D_MAX)),
            ("bear15", lambda s: _ge(s.get("ma_bear_days"), 15)),
            ("converge_or_cross", lambda s: _gt(s.get("ma_converge_10_20_5d"), 0) or s.get("ma10_cross20_up_5d") is True),
            ("above_ma10_streak2", lambda s: _ge(s.get("above_ma10_streak"), 2)),
            ("ma10_up", lambda s: _gt(s.get("ma10_slope_5d_pct"), 0)),
        ),
    ),
    (
        "lowpos_tight",
        "低位 + 三线粘合(≤3%) + 空头排列≥10日 + 收盘≥MA10",
        (
            ("low_position", lambda s: _le(s.get("position_126d"), LOW_POSITION_126D_MAX)),
            ("tight3", lambda s: _le(s.get("ma_tightness_pct"), TIGHTNESS_MAX_PCT)),
            ("bear10", lambda s: _ge(s.get("ma_bear_days"), 10)),
            ("above_ma10", lambda s: s.get("close_above_ma10") is True),
        ),
    ),
    (
        "trap_up_lowpos",
        "低位 + 放量梯形（5 日 spearman≥0.7）",
        (
            ("low_position", lambda s: _le(s.get("position_126d"), LOW_POSITION_126D_MAX)),
            ("trap_up", lambda s: _ge(s.get("vol_spearman_5d"), SPEARMAN_CUT)),
        ),
    ),
    (
        "trap_down_lowpos",
        "低位 + 萎缩梯形（5 日 spearman≤-0.7）",
        (
            ("low_position", lambda s: _le(s.get("position_126d"), LOW_POSITION_126D_MAX)),
            ("trap_down", lambda s: _le(s.get("vol_spearman_5d"), -SPEARMAN_CUT)),
        ),
    ),
    (
        "wave_bull_pullback",
        "多头排列 + 20 日低位（≤0.35）+ 低点企稳（≤3 日）",
        (
            ("bull_align", lambda s: s.get("ma_bull_align") is True),
            ("wave_pos", lambda s: _le(s.get("position_20d"), WAVE_POSITION_20D_MAX)),
            ("recent_low", lambda s: _le(s.get("days_since_20d_low"), WAVE_DAYS_SINCE_LOW_MAX)),
        ),
    ),
    (
        "converge_trap_up",
        "低位收拢（同 lowpos_converge）+ 放量梯形",
        (
            ("low_position", lambda s: _le(s.get("position_126d"), LOW_POSITION_126D_MAX)),
            ("bear15", lambda s: _ge(s.get("ma_bear_days"), 15)),
            ("converge_or_cross", lambda s: _gt(s.get("ma_converge_10_20_5d"), 0) or s.get("ma10_cross20_up_5d") is True),
            ("above_ma10", lambda s: s.get("close_above_ma10") is True),
            ("trap_up", lambda s: _ge(s.get("vol_spearman_5d"), SPEARMAN_CUT)),
        ),
    ),
)

COMBO_NAMES = tuple(name for name, _, _ in _COMBO_CLAUSES)


# ── 主人规则原样验证（R1-R7，按原话定义，不加 position_126d）─────────────────
# 主人的「低位」就是均线结构本身（空头排列+收拢），与价格口径的半年低位是两回事。

MA_NEAR_10_20_PCT = 1.0  # 形式一「10日线和20日线非常近」的预声明阈值（相对收盘 %）

OWNER_RULE_CLAUSES: tuple[tuple[str, str, tuple[tuple[str, Callable[[Mapping[str, object]], bool]], ...]], ...] = (
    (
        "R1_lowpos_form1",
        "低位型·形式一：空头排列≥15日 + (5日内金叉 或 MA10/20极近≤1%)",
        (
            ("bear15", lambda s: _ge(s.get("ma_bear_days"), 15)),
            ("near_or_cross", lambda s: s.get("ma10_cross20_up_5d") is True
             or (lambda v: v is not None and abs(v) <= MA_NEAR_10_20_PCT)(_sample_float(s.get("ma_spread_10_20_pct")))),
        ),
    ),
    (
        "R2_lowpos_form2",
        "低位型·形式二：三线粘合≤3% + 空头排列≥10日（近乎横盘）",
        (
            ("tight3", lambda s: _le(s.get("ma_tightness_pct"), TIGHTNESS_MAX_PCT)),
            ("bear10", lambda s: _ge(s.get("ma_bear_days"), 10)),
        ),
    ),
    (
        "R3_lowpos_stable",
        "低位型（形式一或二）+ 收盘≥MA10（汇隆后站稳）",
        (
            ("form1_or_form2", lambda s: all(fn(s) for _, fn in OWNER_RULE_CLAUSES[0][2]) or all(fn(s) for _, fn in OWNER_RULE_CLAUSES[1][2])),
            ("above_ma10", lambda s: s.get("close_above_ma10") is True),
        ),
    ),
    (
        "R4_wave_bull",
        "波浪型·向上：多头排列 + 20日低位(≤0.35) + 低点企稳(≤3日)",
        (
            ("bull_align", lambda s: s.get("ma_bull_align") is True),
            ("wave_pos", lambda s: _le(s.get("position_20d"), WAVE_POSITION_20D_MAX)),
            ("recent_low", lambda s: _le(s.get("days_since_20d_low"), WAVE_DAYS_SINCE_LOW_MAX)),
        ),
    ),
    (
        "R5_wave_price",
        "波浪型·平行（爱丽型价格波）：20日低位(≤0.35) + 低点≤2日（不要求多头排列）",
        (
            ("wave_pos", lambda s: _le(s.get("position_20d"), WAVE_POSITION_20D_MAX)),
            ("recent_low2", lambda s: _le(s.get("days_since_20d_low"), 2)),
        ),
    ),
    (
        "R6_vol_trapezoid",
        "量能梯形任一方向（|5日量序spearman|≥0.7，放量/萎缩都算）",
        (
            ("trapezoid", lambda s: (lambda v: v is not None and abs(v) >= SPEARMAN_CUT)(_sample_float(s.get("vol_spearman_5d")))),
        ),
    ),
)

OWNER_RULE_NAMES = tuple(name for name, _, _ in OWNER_RULE_CLAUSES) + ("R7_vol_calm",)


def _owner_rule_predicates(
    calm_median: float | None,
) -> list[tuple[str, str, Callable[[Mapping[str, object]], bool]]]:
    """主人规则判定器（R7 平稳待突的 cv 阈值 = 全样本中位数，报告期传入）。"""

    rules: list[tuple[str, str, Callable[[Mapping[str, object]], bool]]] = [
        (name, desc, lambda s, cs=clauses: all(fn(s) for _, fn in cs))
        for name, desc, clauses in OWNER_RULE_CLAUSES
    ]
    rules.append(
        (
            "R7_vol_calm",
            f"平稳待突：前7日量稳（cv ≤ 全样本中位数 {calm_median:.3f}）"
            if calm_median is not None
            else "平稳待突：前7日量稳（cv ≤ 全样本中位数）",
            lambda s: calm_median is not None
            and _le(s.get("prelude_vol_cv_7d"), calm_median),
        )
    )
    return rules


def _classify_owner_type(sample: Mapping[str, object]) -> str:
    """主人类型分类器（优先级：形式一 > 形式二 > 波浪向上 > 波浪平行 > 其他）。"""

    if all(fn(sample) for _, fn in OWNER_RULE_CLAUSES[0][2]):
        return "lowpos_form1"
    if all(fn(sample) for _, fn in OWNER_RULE_CLAUSES[1][2]):
        return "lowpos_form2"
    if all(fn(sample) for _, fn in OWNER_RULE_CLAUSES[3][2]):
        return "wave_bull"
    if all(fn(sample) for _, fn in OWNER_RULE_CLAUSES[4][2]):
        return "wave_price"
    return "other"


OWNER_TYPES = ("lowpos_form1", "lowpos_form2", "wave_bull", "wave_price", "other")


def _combo_failed_clauses(sample: Mapping[str, object], combo_name: str) -> list[str]:
    """样本在某组合下未通过的子条件 id 列表（空=通过）。"""

    for name, _, clauses in _COMBO_CLAUSES:
        if name == combo_name:
            return [clause_id for clause_id, fn in clauses if not fn(sample)]
    return []


def _is_peak3(sample: Mapping[str, object]) -> bool:
    peak = _number(sample.get("eventual_peak"))
    return peak is not None and peak >= 3


# ── 分析块 ②：形态命中率（≥2 板 / ≥3 板妖股 / 1 板夭折三组）──────────────────


_HIT_RATE_PATTERNS: tuple[tuple[str, Callable[[Mapping[str, object]], bool]], ...] = (
    ("ma_bear_align", lambda s: s.get("ma_bear_align") is True),
    ("bear15", lambda s: _ge(s.get("ma_bear_days"), 15)),
    ("converge_pos", lambda s: _gt(s.get("ma_converge_10_20_5d"), 0)),
    ("cross20_up_5d", lambda s: s.get("ma10_cross20_up_5d") is True),
    ("tight3", lambda s: _le(s.get("ma_tightness_pct"), TIGHTNESS_MAX_PCT)),
    ("above_ma10", lambda s: s.get("close_above_ma10") is True),
    ("above_ma10_streak2", lambda s: _ge(s.get("above_ma10_streak"), 2)),
    ("oscillate_ma10", lambda s: _ge(s.get("ma10_cross_count_20d"), MA10_OSCILLATE_MIN_CROSSES)),
    ("trap_up", lambda s: _ge(s.get("vol_spearman_5d"), SPEARMAN_CUT)),
    ("trap_down", lambda s: _le(s.get("vol_spearman_5d"), -SPEARMAN_CUT)),
    ("small_gain2", lambda s: _ge(s.get("small_gain_days_5d"), 2)),
    ("bull_align", lambda s: s.get("ma_bull_align") is True),
    ("wave_pullback", lambda s: _le(s.get("position_20d"), WAVE_POSITION_20D_MAX) and _le(s.get("days_since_20d_low"), WAVE_DAYS_SINCE_LOW_MAX)),
)


def _structure_hit_rates(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """P(形态|≥2板) vs P(形态|≥3板妖股) vs P(形态|1板夭折)。"""

    leaders = [sample for sample in samples if _bool(sample.get("is_leader"))]
    leader3 = [sample for sample in samples if _is_peak3(sample)]
    non_leaders = [sample for sample in samples if not _bool(sample.get("is_leader"))]
    rows: list[dict[str, object]] = []
    for pattern, predicate in _HIT_RATE_PATTERNS:
        row: dict[str, object] = {"pattern": pattern}
        for group_name, group in (
            ("leader", leaders),
            ("leader3", leader3),
            ("non_leader", non_leaders),
        ):
            hits = sum(1 for sample in group if predicate(sample))
            row[f"{group_name}_total"] = len(group)
            row[f"{group_name}_hits"] = hits
            row[f"{group_name}_hit_rate"] = round(hits / len(group), 4) if group else None
        leader_rate = row.get("leader_hit_rate")
        non_leader_rate = row.get("non_leader_hit_rate")
        row["rate_ratio"] = (
            round(float(leader_rate) / float(non_leader_rate), 4)  # type: ignore[arg-type]
            if leader_rate is not None and non_leader_rate
            else None
        )
        rows.append(row)
    return rows


# ── 分析块 ⑥：预登记组合 vs 基线 + 漏网归因 ──────────────────────────────────


def _outcome_stats(members: Sequence[Mapping[str, object]]) -> dict[str, object]:
    leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
    leader3 = sum(1 for sample in members if _is_peak3(sample))
    d1_returns = [
        value
        for value in (_number(sample.get("d1_open_return_pct")) for sample in members)
        if value is not None
    ]
    return {
        "total": len(members),
        "leader_count": leaders,
        "leader_rate": round(leaders / len(members), 4) if members else None,
        "leader3_count": leader3,
        "leader3_rate": round(leader3 / len(members), 4) if members else None,
        "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
        "d1_open_win_rate": round(
            sum(1 for value in d1_returns if value > 0) / len(d1_returns), 4
        )
        if d1_returns
        else None,
    }


def _structure_combo_rows(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {"combo": "__baseline__", "description": "全样本基线", **_outcome_stats(samples)}
    ]
    for name, description, clauses in _COMBO_CLAUSES:
        members = [
            sample
            for sample in samples
            if all(predicate(sample) for _, predicate in clauses)
        ]
        rows.append({"combo": name, "description": description, **_outcome_stats(members)})
    return rows


def _miss_analysis(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """每组合：被拒的 ≥2 板票按子条件统计拒因 + 漏网妖股（≥3 板）清单。"""

    leaders = [sample for sample in samples if _bool(sample.get("is_leader"))]
    rows: list[dict[str, object]] = []
    for name, description, clauses in _COMBO_CLAUSES:
        missed = [
            sample
            for sample in leaders
            if not all(predicate(sample) for _, predicate in clauses)
        ]
        clause_miss: dict[str, int] = defaultdict(int)
        missed_leader3: list[dict[str, object]] = []
        for sample in missed:
            failed = _combo_failed_clauses(sample, name)
            for clause_id in failed:
                clause_miss[clause_id] += 1
            if _is_peak3(sample) and len(missed_leader3) < MISSED_LEADER3_LIST_MAX:
                missed_leader3.append(
                    {
                        "vt_symbol": sample.get("vt_symbol"),
                        "name": sample.get("name"),
                        "trade_date": str(sample.get("trade_date") or ""),
                        "eventual_peak": _number(sample.get("eventual_peak")),
                        "failed_clauses": failed,
                    }
                )
        rows.append(
            {
                "combo": name,
                "description": description,
                "leader_total": len(leaders),
                "missed_count": len(missed),
                "recall": round(1 - len(missed) / len(leaders), 4) if leaders else None,
                "missed_by_clause": dict(sorted(clause_miss.items())),
                "missed_leader3": missed_leader3,
                "missed_leader3_count": sum(1 for sample in missed if _is_peak3(sample)),
            }
        )
    return rows


# ── 分析块 ④：市况分型（regime × 形态族；单 episode 描述性）───────────────────


def _regime_split(samples: Sequence[Mapping[str, object]]) -> dict[str, object]:
    groups: dict[str, list[Mapping[str, object]]] = {"above": [], "below": [], "unknown": []}
    month_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"above": 0, "below": 0, "unknown": 0})
    for sample in samples:
        regime = sample.get("index_above_ma20")
        key = "above" if regime is True else ("below" if regime is False else "unknown")
        groups[key].append(sample)
        month_counts[_month_of(sample)][key] += 1

    by_regime: dict[str, object] = {}
    for key in ("above", "below"):
        members = groups[key]
        pattern_rows: dict[str, object] = {}
        for pattern, predicate in _HIT_RATE_PATTERNS:
            hits = sum(1 for sample in members if predicate(sample))
            leader_hits = sum(
                1 for sample in members if predicate(sample) and _bool(sample.get("is_leader"))
            )
            leader_total = sum(1 for sample in members if _bool(sample.get("is_leader")))
            pattern_rows[pattern] = {
                "total": len(members),
                "hit_rate": round(hits / len(members), 4) if members else None,
                "leader_hit_rate": round(leader_hits / leader_total, 4) if leader_total else None,
            }
        combo_rows: list[dict[str, object]] = []
        for name, description, clauses in _COMBO_CLAUSES:
            combo_members = [
                sample
                for sample in members
                if all(predicate(sample) for _, predicate in clauses)
            ]
            combo_rows.append(
                {"combo": name, "description": description, **_outcome_stats(combo_members)}
            )
        by_regime[key] = {
            **_outcome_stats(members),
            "pattern_hit_rates": pattern_rows,
            "combos": combo_rows,
        }
    return {
        "by_regime": by_regime,
        "regime_month_counts": [
            {"month": month, **counts} for month, counts in sorted(month_counts.items())
        ],
        "unknown_count": len(groups["unknown"]),
    }


# ── 主人规则原样验证：frame-1 统计 + 月度一致性 ──────────────────────────────


def _owner_rule_rows(
    samples: Sequence[Mapping[str, object]], *, calm_median: float | None
) -> list[dict[str, object]]:
    """主人规则 R1-R7 的 ≥2板率/妖股率/D+1 收益（对照全样本基线）。"""

    rows: list[dict[str, object]] = [
        {"rule": "__baseline__", "description": "全样本基线", **_outcome_stats(samples)}
    ]
    for name, description, predicate in _owner_rule_predicates(calm_median):
        members = [sample for sample in samples if predicate(sample)]
        rows.append({"rule": name, "description": description, **_outcome_stats(members)})
    return rows


def _monthly_rule_rates(
    samples: Sequence[Mapping[str, object]],
    *,
    calm_median: float | None,
    min_samples: int = 30,
) -> list[dict[str, object]]:
    """主人规则逐月 ≥2板率 vs 当月基线的方向一致率（翻转检查，MA20 教训）。"""

    by_month: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in samples:
        by_month[_month_of(sample)].append(sample)
    baseline_full = sum(1 for s in samples if _bool(s.get("is_leader"))) / len(samples) if samples else 0.0
    rows: list[dict[str, object]] = []
    for name, _, predicate in _owner_rule_predicates(calm_median):
        full_members = [sample for sample in samples if predicate(sample)]
        full_rate = (
            sum(1 for s in full_members if _bool(s.get("is_leader"))) / len(full_members)
            if full_members
            else None
        )
        full_direction = (
            "higher" if full_rate is not None and full_rate > baseline_full else "lower"
        )
        months: list[dict[str, object]] = []
        valid = 0
        agree = 0
        for month in sorted(by_month):
            month_members = by_month[month]
            month_base = (
                sum(1 for s in month_members if _bool(s.get("is_leader"))) / len(month_members)
                if month_members
                else 0.0
            )
            members = [sample for sample in month_members if predicate(sample)]
            if len(members) < min_samples:
                months.append({"month": month, "total": len(members), "leader_rate": None, "direction": "skip"})
                continue
            rate = sum(1 for s in members if _bool(s.get("is_leader"))) / len(members)
            direction = "higher" if rate > month_base else "lower"
            valid += 1
            if direction == full_direction:
                agree += 1
            months.append(
                {
                    "month": month,
                    "total": len(members),
                    "leader_rate": round(rate, 4),
                    "month_baseline": round(month_base, 4),
                    "direction": direction,
                }
            )
        rows.append(
            {
                "rule": name,
                "total": len(full_members),
                "full_leader_rate": round(full_rate, 4) if full_rate is not None else None,
                "baseline_leader_rate": round(baseline_full, 4),
                "full_direction": full_direction,
                "valid_months": valid,
                "monthly_agreement": round(agree / valid, 4) if valid else None,
                "months": months,
            }
        )
    return rows


# ── 早盘价格 × 类型（竞价缺口桶；frame-1 结局对照）────────────────────────────

AUCTION_GAP_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<0", None, 0.0),
    ("0-1", 0.0, 1.0),
    ("1-2", 1.0, 2.0),
    ("2-4", 2.0, 4.0),
    ("4-9.5", 4.0, 9.5),
    (">=9.5", 9.5, None),  # 接近一字/秒板
)


def _gap_bucket(gap_pct: float | None) -> str | None:
    if gap_pct is None:
        return None
    for label, low, high in AUCTION_GAP_BUCKETS:
        if (low is None or gap_pct >= low) and (high is None or gap_pct < high):
            return label
    return None


def _auction_by_type(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """类型 × 竞价缺口桶的 ≥2板率/妖股率（D 日执行证据，非 D-1 因子）。"""

    rows: list[dict[str, object]] = []
    for owner_type in OWNER_TYPES:
        members = [sample for sample in samples if _classify_owner_type(sample) == owner_type]
        gaps = [
            value
            for value in (_sample_float(sample.get("auction_gap_pct")) for sample in members)
            if value is not None
        ]
        bucket_rows: list[dict[str, object]] = []
        for label, _, _ in AUCTION_GAP_BUCKETS:
            bucket_members = [
                sample
                for sample in members
                if _gap_bucket(_sample_float(sample.get("auction_gap_pct"))) == label
            ]
            bucket_rows.append({"bucket": label, **_outcome_stats(bucket_members)})
        rows.append(
            {
                "type": owner_type,
                **_outcome_stats(members),
                "gap_mean": round(mean(gaps), 4) if gaps else None,
                "gap_median": round(median(gaps), 4) if gaps else None,
                "gap_ge2_rate": round(sum(1 for g in gaps if g >= 2.0) / len(gaps), 4)
                if gaps
                else None,
                "buckets": bucket_rows,
            }
        )
    return rows


# ── 过滤器家族（召回×占比前沿；谓词全部 features-only）────────────────────────

MOMENTUM_REF_BIAS_MA20 = 5.0  # 高动量对照阈值（预声明）
FIRST_TOUCH_LOOKBACK_DAYS = 10  # 首触判定：前 10 个市场交易日无封板记录


def _owner_lowpos4_pred(features: Mapping[str, object]) -> bool:
    """生产低位四条件（现观察池）的 dict 版（与 _is_owner_low_position 同口径，测试锁）。"""

    drawdown = _sample_float(features.get("drawdown_from_126d_high_pct"))
    rebound = _sample_float(features.get("rebound_from_126d_low_pct"))
    if drawdown is None or rebound is None:
        return False
    if drawdown > -25.0 or rebound > 12.0:
        return False
    return_5d = _sample_float(features.get("prior_return_5d_pct"))
    if return_5d is not None and return_5d > 6.0:
        return False
    amplitude_20d = _sample_float(features.get("amplitude_20d_pct"))
    return not (amplitude_20d is not None and amplitude_20d > 40.0)


def _filter_sets(
    calm_median: float | None,
) -> list[tuple[str, str, Callable[[Mapping[str, object]], bool]]]:
    """召回×占比前沿的过滤器家族：基线/单体/并集/生产低位/观察组合/动量对照。"""

    rules = {name: predicate for name, _, predicate in _owner_rule_predicates(calm_median)}

    def _union(*names: str) -> Callable[[Mapping[str, object]], bool]:
        return lambda f: any(rules[name](f) for name in names)

    lowpos_wave = _union(
        "R1_lowpos_form1", "R2_lowpos_form2", "R4_wave_bull", "R5_wave_price"
    )
    tight_clauses = dict(
        next(
            (clauses for name, _, clauses in _COMBO_CLAUSES if name == "lowpos_tight"),
            (),
        )
    )
    return [
        ("__none__", "无过滤（全票基线）", lambda f: True),
        ("R1_lowpos_form1", "低位型·形式一", rules["R1_lowpos_form1"]),
        ("R2_lowpos_form2", "低位型·形式二", rules["R2_lowpos_form2"]),
        ("R4_wave_bull", "波浪·向上", rules["R4_wave_bull"]),
        ("R5_wave_price", "波浪·平行", rules["R5_wave_price"]),
        ("R6_vol_trapezoid", "量能梯形双向", rules["R6_vol_trapezoid"]),
        ("U_lowpos", "低位型全集（形式一∪形式二）", _union("R1_lowpos_form1", "R2_lowpos_form2")),
        ("U_lowpos_wave", "低位型∪波浪两型", lowpos_wave),
        (
            "U_plus_trapezoid",
            "低位∪波浪∪量能梯形",
            lambda f: lowpos_wave(f) or rules["R6_vol_trapezoid"](f),
        ),
        (
            "U_plus_calm",
            "低位∪波浪∪梯形∪平稳待突",
            lambda f: lowpos_wave(f)
            or rules["R6_vol_trapezoid"](f)
            or rules["R7_vol_calm"](f),
        ),
        (
            "U_plus_owner4",
            "低位∪波浪∪梯形∪生产低位四条件",
            lambda f: lowpos_wave(f)
            or rules["R6_vol_trapezoid"](f)
            or _owner_lowpos4_pred(f),
        ),
        ("owner_lowpos4", "生产低位四条件（现观察池）", _owner_lowpos4_pred),
        (
            "combo_lowpos_tight",
            "lowpos_tight 组合（观察亮点）",
            lambda f: all(fn(f) for fn in tight_clauses.values()),
        ),
        ("momentum_ref", "高动量对照（bias_ma20≥5%）", lambda f: _ge(f.get("bias_ma20_pct"), MOMENTUM_REF_BIAS_MA20)),
    ]


def _build_touch_index(
    events: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
) -> tuple[dict[tuple[str, str], str], dict[str, int]]:
    """首触事件索引 {(symbol, date): "zt"|"zbgc"}。

    zt 首板 = limit_times==1；zbgc 首触 = 前 FIRST_TOUCH_LOOKBACK_DAYS 个市场
    交易日内无同票 zt 封板记录（provider 对 zbgc 的 limit_times 恒为 0）。
    """

    position = {day: index for index, day in enumerate(calendar)}
    zt_positions: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.get("event_type") == "limit_pool_zt":
            day = str(event.get("trade_date") or "")
            if day in position:
                zt_positions[str(event.get("vt_symbol") or "")].append(position[day])
    index: dict[tuple[str, str], str] = {}
    stats = {"zt_first": 0, "zbgc_first_touch": 0, "zbgc_not_first": 0}
    for event in events:
        symbol = str(event.get("vt_symbol") or "")
        day = str(event.get("trade_date") or "")
        if day not in position:
            continue
        if event.get("event_type") == "limit_pool_zt" and event.get("limit_times") == 1:
            index[(symbol, day)] = "zt"
            stats["zt_first"] += 1
        elif event.get("event_type") == "limit_pool_zbgc":
            pos = position[day]
            recent_seal = any(
                pos - FIRST_TOUCH_LOOKBACK_DAYS <= seal_pos < pos
                for seal_pos in zt_positions.get(symbol, [])
            )
            if recent_seal:
                stats["zbgc_not_first"] += 1
                continue
            index.setdefault((symbol, day), "zbgc")
            stats["zbgc_first_touch"] += 1
    return index, stats


def _frontier_by_height(
    samples: Sequence[Mapping[str, object]], *, calm_median: float | None
) -> list[dict[str, object]]:
    """过滤器家族 × 连板高度召回（frame-1：每个首板只计一次，无重复计数）。"""

    bucket_fns = {
        "peak2": lambda p: p == 2,
        "peak3": lambda p: p == 3,
        "peak4": lambda p: p == 4,
        "peak5p": lambda p: p is not None and p >= 5,
    }
    leaders = [sample for sample in samples if _bool(sample.get("is_leader"))]
    bucket_totals = {
        name: sum(1 for s in leaders if fn(_number(s.get("eventual_peak"))))
        for name, fn in bucket_fns.items()
    }
    rows: list[dict[str, object]] = []
    for name, description, predicate in _filter_sets(calm_median):
        passed = [sample for sample in leaders if predicate(sample)]
        row: dict[str, object] = {
            "filter": name,
            "description": description,
            "pass_total": len(passed),
            "coverage": round(len(passed) / len(leaders), 4) if leaders else None,
        }
        for bucket_name, fn in bucket_fns.items():
            hits = sum(1 for s in passed if fn(_number(s.get("eventual_peak"))))
            row[f"recall_{bucket_name}"] = (
                round(hits / bucket_totals[bucket_name], 4)
                if bucket_totals[bucket_name]
                else None
            )
            row[f"pass_{bucket_name}"] = hits
        row["peak3_share"] = (
            round(row["pass_peak3"] / len(passed), 4) if passed else None  # type: ignore[index]
        )
        rows.append(row)
    rows[0]["baseline_leader_total"] = len(leaders)
    return rows


def _touch_seal_analysis(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    calm_median: float | None,
) -> dict[str, object]:
    """首触样本的封板率：过滤器过/不过 × 封板率（zt 首板 + zbgc 首触）。"""

    touch_index, stats = _build_touch_index(events, calendar)
    touch_samples = [
        {
            "vt_symbol": symbol,
            "trade_date": day,
            "sealed": event_type == "zt",
        }
        for (symbol, day), event_type in touch_index.items()
    ]
    attached = attach_structure_features(touch_samples, daily_bars)
    total_touches = len(attached)
    total_sealed = sum(1 for s in attached if s.get("sealed"))
    rows: list[dict[str, object]] = []
    for name, description, predicate in _filter_sets(calm_median):
        passed = [sample for sample in attached if predicate(sample)]
        sealed = sum(1 for s in passed if s.get("sealed"))
        failed = [sample for sample in attached if not predicate(sample)]
        sealed_fail = sum(1 for s in failed if s.get("sealed"))
        rows.append(
            {
                "filter": name,
                "description": description,
                "touches": len(passed),
                "sealed": sealed,
                "seal_rate": round(sealed / len(passed), 4) if passed else None,
                "rejected_touches": len(failed),
                "rejected_seal_rate": round(sealed_fail / len(failed), 4) if failed else None,
            }
        )
    return {
        "touch_stats": stats,
        "total_touches": total_touches,
        "total_sealed": total_sealed,
        "baseline_seal_rate": round(total_sealed / total_touches, 4) if total_touches else None,
        "per_filter": rows,
    }


# ── 分析块 ⑨：敏感性（预声明档位，不网格搜索）─────────────────────────────────


def _sensitivity_rows(
    factor_samples: Sequence[Mapping[str, object]],
    samples: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """converge_lag 3/5/8 重挂 + 小阳上限 1.0/1.5/2.0 重挂 + spearman/紧凑度阈值后验。"""

    def _combo_summary(attached: Sequence[Mapping[str, object]]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for name, _, clauses in _COMBO_CLAUSES:
            members = [
                sample
                for sample in attached
                if all(predicate(sample) for _, predicate in clauses)
            ]
            leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
            summary[name] = {
                "total": len(members),
                "leader_rate": round(leaders / len(members), 4) if members else None,
            }
        return summary

    converge_rows: list[dict[str, object]] = []
    for lag in SENSITIVITY_CONVERGE_LAGS:
        if lag == CONVERGE_LAG_DAYS:
            attached = list(samples)
        else:
            attached = attach_structure_features(
                factor_samples, daily_bars, converge_lag=lag
            )
        converge_rows.append({"converge_lag": lag, **_combo_summary(attached)})

    small_gain_rows: list[dict[str, object]] = []
    for cap in SENSITIVITY_SMALL_GAIN_CAPS:
        if cap == SMALL_GAIN_CAP_PCT:
            attached = list(samples)
        else:
            attached = attach_structure_features(
                factor_samples, daily_bars, small_gain_cap=cap
            )
        hits = [sample for sample in attached if _ge(sample.get("small_gain_days_5d"), 2)]
        leaders = sum(1 for sample in hits if _bool(sample.get("is_leader")))
        small_gain_rows.append(
            {
                "small_gain_cap": cap,
                "small_gain2_total": len(hits),
                "small_gain2_leader_rate": round(leaders / len(hits), 4) if hits else None,
            }
        )

    spearman_rows: list[dict[str, object]] = []
    for cut in SENSITIVITY_SPEARMAN_CUTS:
        for direction in ("trap_up", "trap_down"):
            members = [
                sample
                for sample in samples
                if _le(sample.get("position_126d"), LOW_POSITION_126D_MAX)
                and (
                    _ge(sample.get("vol_spearman_5d"), cut)
                    if direction == "trap_up"
                    else _le(sample.get("vol_spearman_5d"), -cut)
                )
            ]
            leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
            spearman_rows.append(
                {
                    "cut": cut,
                    "direction": direction,
                    "total": len(members),
                    "leader_rate": round(leaders / len(members), 4) if members else None,
                }
            )

    tightness_rows: list[dict[str, object]] = []
    for tight_max in SENSITIVITY_TIGHTNESS:
        members = [
            sample
            for sample in samples
            if _le(sample.get("position_126d"), LOW_POSITION_126D_MAX)
            and _le(sample.get("ma_tightness_pct"), tight_max)
            and _ge(sample.get("ma_bear_days"), 10)
            and sample.get("close_above_ma10") is True
        ]
        leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
        tightness_rows.append(
            {
                "tightness_max": tight_max,
                "total": len(members),
                "leader_rate": round(leaders / len(members), 4) if members else None,
            }
        )
    return {
        "converge_lag": converge_rows,
        "small_gain_cap": small_gain_rows,
        "spearman_cut": spearman_rows,
        "tightness": tightness_rows,
    }


# ── 分析块 ⑦：盘前全市场框架（frame 2）───────────────────────────────────────


def build_premarket_structure_frame(
    daily_bars: Sequence[Mapping[str, object]],
    first_board_index: Mapping[tuple[str, str], object],
    names: Mapping[str, str],
    calendar: Sequence[str],
    *,
    forward_days: int = PREMARKET_FORWARD_DAYS,
    min_history: int = PREMARKET_MIN_HISTORY,
    calm_median: float | None = None,
    touch_index: Mapping[tuple[str, str], str] | None = None,
) -> dict[str, object]:
    """全市场主板股票日扫描：候选数/日、5 日内首板命中率、lift、妖股命中。

    标签来源与 frame 1 同一首板事件集（provider wave 口径）；5 个个股交易日的
    观察窗跨市场日不得超 PREMARKET_LABEL_MAX_MARKET_SPAN，且不得越过事件末端，
    否则该股票日记为 label_invalid（不计入分母）。

    附带两个子帧：主人规则 R1-R7 的同口径 tallies（``owner_rules_premarket``）与
    竞价帧（``auction_frame``：类型 × 次日竞价缺口 → P(次日首板)，
    「竞价就可以看出要出首板」的精确概率验证）。
    """

    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for rows in bars_by_symbol.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    index_dates, index_regime = _index_regime_map(bars_by_symbol.get(INDEX_VT_SYMBOL, []))
    calendar_position = {day: position for position, day in enumerate(calendar)}
    event_dates = [day for _, day in first_board_index]
    last_events_date = max(event_dates) if event_dates else ""
    market_days = [day for day in calendar if day <= last_events_date]
    tail_cutoff = (
        market_days[-PREMARKET_TAIL_EXCLUDE_MARKET_DAYS - 1]
        if len(market_days) > PREMARKET_TAIL_EXCLUDE_MARKET_DAYS
        else ""
    )

    def _new_tally() -> dict[str, int]:
        return {"days": 0, "board": 0, "leader": 0, "peak3": 0}

    totals = _new_tally()
    combo_tallies: dict[str, dict[str, int]] = {name: _new_tally() for name in COMBO_NAMES}
    owner_rule_tallies: dict[str, dict[str, int]] = {
        name: _new_tally() for name, _, _ in _owner_rule_predicates(calm_median)
    }
    filter_sets = _filter_sets(calm_median)
    filter_tallies: dict[str, dict[str, int]] = {
        name: {"days": 0, "board": 0, "leader": 0, "peak3": 0, "touch1d": 0, "seal1d": 0}
        for name, _, _ in filter_sets
    }
    filter_day_counts: dict[str, dict[str, int]] = {
        name: defaultdict(int) for name, _, _ in filter_sets
    }
    day_valid_counts: dict[str, int] = defaultdict(int)
    touches = touch_index or {}
    auction_cells: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"days": 0, "board": 0, "touch": 0}
    )
    auction_type_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"days": 0, "board": 0}
    )
    auction_month_cells: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"days": 0, "touch": 0}
    )
    auction_day_sides: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {"high": {"days": 0, "touch": 0}, "low": {"days": 0, "touch": 0}}
    )
    auction_days = 0
    auction_boards = 0
    regime_totals: dict[str, dict[str, int]] = {"above": _new_tally(), "below": _new_tally()}
    regime_combo_tallies: dict[str, dict[str, dict[str, int]]] = {
        key: {name: _new_tally() for name in COMBO_NAMES} for key in ("above", "below")
    }
    scanned_market_days: set[str] = set()
    eligible_symbols = 0
    invalid_labels = 0

    for symbol, rows in sorted(bars_by_symbol.items()):
        if not is_eligible_main_board(symbol, names.get(symbol, "")):
            continue
        eligible_symbols += 1
        dates = [str(row.get("trade_date") or "") for row in rows]
        for index in range(min_history - 1, len(rows)):
            day = dates[index]
            if day > tail_cutoff:
                break
            bars_slice = rows[max(0, index + 1 - PREMARKET_BAR_SLICE) : index + 1]
            if not _is_first_board_candidate(bars_slice):
                continue
            # 标签：未来 forward_days 个个股交易日内是否出现首板
            hit_peak: float | None = None
            for step in range(1, forward_days + 1):
                if index + step >= len(rows):
                    break
                forward_day = dates[index + step]
                span = calendar_position.get(forward_day, 0) - calendar_position.get(day, 0)
                if span > PREMARKET_LABEL_MAX_MARKET_SPAN:
                    break
                peak = _number(first_board_index.get((symbol, forward_day)))
                if peak is not None:
                    hit_peak = peak
                    break
            if hit_peak is None:
                last_forward = index + forward_days
                if last_forward >= len(rows):
                    invalid_labels += 1
                    continue
                forward_day = dates[last_forward]
                span = calendar_position.get(forward_day, 0) - calendar_position.get(day, 0)
                if span > PREMARKET_LABEL_MAX_MARKET_SPAN or forward_day > last_events_date:
                    invalid_labels += 1
                    continue
            scanned_market_days.add(day)
            totals["days"] += 1
            day_valid_counts[day] += 1
            regime = _index_regime_at(index_dates, index_regime, day)
            regime_key = "above" if regime is True else ("below" if regime is False else "")
            if regime_key:
                regime_totals[regime_key]["days"] += 1
            if hit_peak is not None:
                totals["board"] += 1
                if hit_peak >= 2:
                    totals["leader"] += 1
                if hit_peak >= 3:
                    totals["peak3"] += 1
                if regime_key:
                    regime_totals[regime_key]["board"] += 1
                    if hit_peak >= 2:
                        regime_totals[regime_key]["leader"] += 1
                    if hit_peak >= 3:
                        regime_totals[regime_key]["peak3"] += 1
            features = {
                **_structure_features(bars_slice),
                **_long_window_features(bars_slice),
                **_prelude_pattern_features(bars_slice),
            }
            for name, _, clauses in _COMBO_CLAUSES:
                if not all(predicate(features) for _, predicate in clauses):
                    continue
                combo_tallies[name]["days"] += 1
                if regime_key:
                    regime_combo_tallies[regime_key][name]["days"] += 1
                if hit_peak is None:
                    continue
                combo_tallies[name]["board"] += 1
                if hit_peak >= 2:
                    combo_tallies[name]["leader"] += 1
                if hit_peak >= 3:
                    combo_tallies[name]["peak3"] += 1
                if regime_key:
                    regime_combo_tallies[regime_key][name]["board"] += 1
                    if hit_peak >= 2:
                        regime_combo_tallies[regime_key][name]["leader"] += 1
                    if hit_peak >= 3:
                        regime_combo_tallies[regime_key][name]["peak3"] += 1
            for name, _, predicate in _owner_rule_predicates(calm_median):
                if not predicate(features):
                    continue
                owner_rule_tallies[name]["days"] += 1
                if hit_peak is None:
                    continue
                owner_rule_tallies[name]["board"] += 1
                if hit_peak >= 2:
                    owner_rule_tallies[name]["leader"] += 1
                if hit_peak >= 3:
                    owner_rule_tallies[name]["peak3"] += 1
            # 过滤器家族前沿 tallies（含 1 日触板/封板标签）
            next_touch = (
                touches.get((symbol, dates[index + 1])) if index + 1 < len(rows) else None
            )
            for name, _, predicate in filter_sets:
                if not predicate(features):
                    continue
                filter_tallies[name]["days"] += 1
                filter_day_counts[name][day] += 1
                if hit_peak is not None:
                    filter_tallies[name]["board"] += 1
                    if hit_peak >= 2:
                        filter_tallies[name]["leader"] += 1
                    if hit_peak >= 3:
                        filter_tallies[name]["peak3"] += 1
                if next_touch is not None:
                    filter_tallies[name]["touch1d"] += 1
                    if next_touch == "zt":
                        filter_tallies[name]["seal1d"] += 1
            # 竞价帧：类型 × 次日竞价缺口 → P(次日首板/触板)
            if index + 1 < len(rows):
                next_open = _number(rows[index + 1].get("open_price"))
                curr_close = _number(rows[index].get("close_price"))
                if next_open and curr_close:
                    gap_pct = (next_open / curr_close - 1) * 100
                    board_next = (symbol, dates[index + 1]) in first_board_index
                    owner_type = _classify_owner_type(features)
                    bucket = _gap_bucket(gap_pct)
                    auction_days += 1
                    auction_type_totals[owner_type]["days"] += 1
                    if board_next:
                        auction_boards += 1
                        auction_type_totals[owner_type]["board"] += 1
                    if bucket is not None:
                        auction_cells[(owner_type, bucket)]["days"] += 1
                        if board_next:
                            auction_cells[(owner_type, bucket)]["board"] += 1
                        month = day[:7]
                        auction_month_cells[(month, bucket)]["days"] += 1
                        side = "high" if gap_pct >= 2.0 else "low"
                        auction_day_sides[day][side]["days"] += 1
                        if next_touch is not None:
                            auction_cells[(owner_type, bucket)]["touch"] += 1
                            auction_month_cells[(month, bucket)]["touch"] += 1
                            auction_day_sides[day][side]["touch"] += 1

    def _frame_row(tally: Mapping[str, int], base_board_rate: float | None) -> dict[str, object]:
        days = tally["days"]
        hit_rate = round(tally["board"] / days, 6) if days else None
        return {
            "candidate_days": days,
            "board_hits": tally["board"],
            "hit_rate": hit_rate,
            "lift": round(hit_rate / base_board_rate, 4)
            if hit_rate is not None and base_board_rate
            else None,
            "leader_hits": tally["leader"],
            "leader_given_board": round(tally["leader"] / tally["board"], 4)
            if tally["board"]
            else None,
            "peak3_hits": tally["peak3"],
        }

    market_day_count = len(scanned_market_days)
    base_board_rate = round(totals["board"] / totals["days"], 6) if totals["days"] else None
    base_leader_rate = round(totals["leader"] / totals["days"], 6) if totals["days"] else None
    per_combo: list[dict[str, object]] = []
    for name in COMBO_NAMES:
        row = _frame_row(combo_tallies[name], base_board_rate)
        row["combo"] = name
        row["avg_candidates_per_day"] = (
            round(combo_tallies[name]["days"] / market_day_count, 4) if market_day_count else None
        )
        per_combo.append(row)

    owner_rule_rows: list[dict[str, object]] = []
    for name, _, _ in _owner_rule_predicates(calm_median):
        row = _frame_row(owner_rule_tallies[name], base_board_rate)
        row["rule"] = name
        row["avg_candidates_per_day"] = (
            round(owner_rule_tallies[name]["days"] / market_day_count, 4)
            if market_day_count
            else None
        )
        owner_rule_rows.append(row)

    def _share_stats(name: str) -> dict[str, object]:
        shares = [
            filter_day_counts[name][day] / day_valid_counts[day]
            for day in sorted(day_valid_counts)
        ]
        if not shares:
            return {"share_mean": None, "share_p50": None, "share_p90": None}
        return {
            "share_mean": round(mean(shares), 4),
            "share_p50": round(median(shares), 4),
            "share_p90": round(quantiles(shares, n=10)[-1], 4) if len(shares) >= 10 else None,
        }

    frontier_rows: list[dict[str, object]] = []
    for name, description, _ in filter_sets:
        tally = filter_tallies[name]
        row = _frame_row(tally, base_board_rate)
        row["filter"] = name
        row["description"] = description
        row.update(_share_stats(name))
        row["touch1d"] = tally["touch1d"]
        row["touch_rate_1d"] = (
            round(tally["touch1d"] / tally["days"], 6) if tally["days"] else None
        )
        row["seal1d"] = tally["seal1d"]
        row["seal_given_touch_1d"] = (
            round(tally["seal1d"] / tally["touch1d"], 4) if tally["touch1d"] else None
        )
        frontier_rows.append(row)

    base_board_1d = round(auction_boards / auction_days, 6) if auction_days else None
    auction_cell_rows: list[dict[str, object]] = []
    for owner_type in OWNER_TYPES:
        for label, _, _ in AUCTION_GAP_BUCKETS:
            cell = auction_cells.get((owner_type, label))
            if not cell or not cell["days"]:
                continue
            hit_rate = round(cell["board"] / cell["days"], 6)
            auction_cell_rows.append(
                {
                    "type": owner_type,
                    "bucket": label,
                    "days": cell["days"],
                    "board_hits": cell["board"],
                    "hit_rate": hit_rate,
                    "lift": round(hit_rate / base_board_1d, 4) if base_board_1d else None,
                    "touch_hits": cell["touch"],
                    "touch_rate": round(cell["touch"] / cell["days"], 6),
                }
            )
    auction_month_rows: list[dict[str, object]] = []
    for (month, bucket), cell in sorted(auction_month_cells.items()):
        if not cell["days"]:
            continue
        auction_month_rows.append(
            {
                "month": month,
                "bucket": bucket,
                "days": cell["days"],
                "touch_hits": cell["touch"],
                "touch_rate": round(cell["touch"] / cell["days"], 6),
            }
        )
    consistency_days = 0
    consistency_wins = 0
    for sides in auction_day_sides.values():
        high, low = sides["high"], sides["low"]
        if high["days"] < 10 or low["days"] < 20:
            continue
        consistency_days += 1
        if high["touch"] / high["days"] > low["touch"] / low["days"]:
            consistency_wins += 1
    auction_frame = {
        "auction_days": auction_days,
        "base_board_1d": base_board_1d,
        "per_type": [
            {
                "type": owner_type,
                "days": auction_type_totals[owner_type]["days"],
                "board_hits": auction_type_totals[owner_type]["board"],
                "board_rate": round(
                    auction_type_totals[owner_type]["board"]
                    / auction_type_totals[owner_type]["days"],
                    6,
                )
                if auction_type_totals[owner_type]["days"]
                else None,
            }
            for owner_type in OWNER_TYPES
        ],
        "cells": auction_cell_rows,
        "monthly_touch": auction_month_rows,
        "daily_consistency": {
            "rule": "触板率(gap≥2%) > 触板率(gap<2%) 的交易日占比（高侧≥10 观察、低侧≥20）",
            "days_valid": consistency_days,
            "days_win": consistency_wins,
            "win_share": round(consistency_wins / consistency_days, 4)
            if consistency_days
            else None,
        },
    }

    by_regime: dict[str, object] = {}
    for key in ("above", "below"):
        regime_base = (
            round(regime_totals[key]["board"] / regime_totals[key]["days"], 6)
            if regime_totals[key]["days"]
            else None
        )
        by_regime[key] = {
            "stock_days": regime_totals[key]["days"],
            "base_board_rate": regime_base,
            "base_leader_rate": round(regime_totals[key]["leader"] / regime_totals[key]["days"], 6)
            if regime_totals[key]["days"]
            else None,
            "per_combo": [
                {"combo": name, **_frame_row(regime_combo_tallies[key][name], regime_base)}
                for name in COMBO_NAMES
            ],
        }
    return {
        "stock_days": totals["days"],
        "scanned_market_days": market_day_count,
        "eligible_symbols": eligible_symbols,
        "invalid_labels": invalid_labels,
        "base_rates": {
            "board_5d": base_board_rate,
            "leader_5d": base_leader_rate,
            "peak3_5d": round(totals["peak3"] / totals["days"], 6) if totals["days"] else None,
        },
        "per_combo": per_combo,
        "owner_rules_premarket": owner_rule_rows,
        "auction_frame": auction_frame,
        "frontier": frontier_rows,
        "by_regime": by_regime,
        "params": {
            "forward_days": forward_days,
            "min_history": min_history,
            "label_max_market_span": PREMARKET_LABEL_MAX_MARKET_SPAN,
            "tail_exclude_market_days": PREMARKET_TAIL_EXCLUDE_MARKET_DAYS,
        },
        "interpretation_bands": "lift>=3 且 candidate_days>=100 → 过滤级；1.5<=lift<3 → 排序级；lift<1.5 → 淘汰（预声明）",
    }


# ── 最终裁决表（预声明逻辑，读已计算的报告块）────────────────────────────────


def _verdict_row(
    condition: str,
    origin: str,
    *,
    lift: float | None = None,
    candidate_days: int | None = None,
    hit_ratio: float | None = None,
    auc: float | None = None,
    agreement: float | None = None,
    flipped: bool | None = None,
    leader_rate: float | None = None,
    baseline: float = 0.2194,
    total: int | None = None,
    evidence: str = "",
) -> dict[str, object]:
    """预声明裁决：过滤级 / 排序级 / 观察 / 淘汰。

    排序级三通道（预声明）：盘前 lift∈[1.5,3)；或命中比≥1.15 且月度一致≥0.7
    且 6/7 不翻转；或 AUC≥0.55 且月度一致≥0.7 且不翻转（纯数值因子通道）。
    """

    if lift is not None and lift >= 3.0 and (candidate_days or 0) >= 100:
        verdict, usage = "过滤级", "可做盘前硬过滤"
    elif (
        (lift is not None and lift >= 1.5)
        or (
            hit_ratio is not None
            and hit_ratio >= 1.15
            and agreement is not None
            and agreement >= 0.7
            and not flipped
        )
        or (
            auc is not None
            and auc >= 0.55
            and agreement is not None
            and agreement >= 0.7
            and not flipped
        )
    ):
        verdict, usage = "排序级", "进排序加权，不做硬过滤"
    elif (
        total is not None
        and total < 100
        and leader_rate is not None
        and leader_rate > baseline * 1.2
    ):
        verdict, usage = "观察", "小样本亮点，做观察标签不进条件"
    else:
        verdict, usage = "淘汰", "不进模型"
    return {
        "condition": condition,
        "origin": origin,
        "verdict": verdict,
        "usage": usage,
        "lift": lift,
        "hit_ratio": hit_ratio,
        "auc": auc,
        "agreement": agreement,
        "flipped": flipped,
        "leader_rate": leader_rate,
        "total": total,
        "evidence": evidence,
    }


def _final_verdicts(report: Mapping[str, object]) -> list[dict[str, object]]:
    """逐条件最终用途裁决（主人规则 + 组合 + 研究因子 + 竞价执行层）。"""

    baseline = (report.get("label_balance") or {}).get("positive_rate") or 0.2194
    frame = report.get("premarket_frame") or {}
    owner_premarket = {
        row.get("rule"): row for row in frame.get("owner_rules_premarket") or []
    }
    owner_monthly = {
        row.get("rule"): row for row in report.get("owner_rules_monthly") or []
    }
    owner_rows = {row.get("rule"): row for row in report.get("owner_rules") or []}
    monthly_by_key = {
        str(item.get("factor_key")): item for item in report.get("monthly_stability") or []
    }
    flip_by_key = {
        str(item.get("factor_key")): bool(item.get("flipped"))
        for item in report.get("june_july_check") or []
    }
    hit_by_pattern = {row.get("pattern"): row for row in report.get("hit_rates") or []}
    auc_by_key = {
        str(item.get("factor_key")): item.get("auc")
        for item in report.get("numeric_factors") or []
    }

    rows: list[dict[str, object]] = []
    for name, description, _ in _owner_rule_predicates(None):
        pre = owner_premarket.get(name) or {}
        monthly = owner_monthly.get(name) or {}
        stats = owner_rows.get(name) or {}
        rows.append(
            _verdict_row(
                name,
                "主人规则",
                lift=pre.get("lift"),  # type: ignore[arg-type]
                candidate_days=pre.get("candidate_days"),  # type: ignore[arg-type]
                agreement=monthly.get("monthly_agreement"),  # type: ignore[arg-type]
                leader_rate=stats.get("leader_rate"),  # type: ignore[arg-type]
                baseline=baseline,
                total=stats.get("total"),  # type: ignore[arg-type]
                evidence=f"≥2板率 {stats.get('leader_rate')} vs 基线 {baseline:.4f}；"
                f"lift {pre.get('lift')}；月度一致 {monthly.get('monthly_agreement')}；{description}",
            )
        )

    combo_rows = {row.get("combo"): row for row in report.get("combos") or []}
    frame_combos = {row.get("combo"): row for row in frame.get("per_combo") or []}
    for name in COMBO_NAMES:
        stats = combo_rows.get(name) or {}
        pre = frame_combos.get(name) or {}
        rows.append(
            _verdict_row(
                name,
                "预登记组合",
                lift=pre.get("lift"),  # type: ignore[arg-type]
                candidate_days=pre.get("candidate_days"),  # type: ignore[arg-type]
                leader_rate=stats.get("leader_rate"),  # type: ignore[arg-type]
                baseline=baseline,
                total=stats.get("total"),  # type: ignore[arg-type]
                evidence=f"≥2板率 {stats.get('leader_rate')} vs 基线 {baseline:.4f}；lift {pre.get('lift')}",
            )
        )

    for key in (
        "bias_ma20_pct",
        "ma10_slope_5d_pct",
        "vol_spearman_10d",
        "above_ma10_streak",
        "close_above_ma10",
        "position_20d",
        "bias_ma5_pct",
        "turnover_1d_vs_20d",
        "vol_spearman_5d",
    ):
        monthly = monthly_by_key.get(key) or {}
        pattern_key = (
            "above_ma10_streak2" if key == "above_ma10_streak" else key
        )
        hit = hit_by_pattern.get(pattern_key) or {}
        rows.append(
            _verdict_row(
                key,
                "研究因子",
                hit_ratio=hit.get("rate_ratio"),  # type: ignore[arg-type]
                auc=auc_by_key.get(key),  # type: ignore[arg-type]
                agreement=monthly.get("monthly_agreement"),  # type: ignore[arg-type]
                flipped=flip_by_key.get(key),
                evidence=f"AUC {auc_by_key.get(key)}；命中比 {hit.get('rate_ratio')}；"
                f"月度一致 {monthly.get('monthly_agreement')}；"
                f"6/7月{'翻转' if flip_by_key.get(key) else '一致'}",
            )
        )

    auction = report.get("auction_gap") or {}
    quintiles = auction.get("quintile_positive_rates") or []
    q5 = quintiles[-1] if quintiles else {}
    q5_rate = q5.get("positive_rate")
    rows.append(
        _verdict_row(
            "auction_gap≥3%（Q5）",
            "D日执行层",
            hit_ratio=round(q5_rate / baseline, 4) if q5_rate and baseline else None,
            agreement=1.0,  # 单日执行层不做月度一致性判定（样本为窗口全期）
            flipped=False,
            evidence=f"Q5 ≥2板率 {q5_rate} vs 基线 {baseline:.4f}（竞价高开>3% 首板）",
        )
    )
    return rows


# ── 报告编排 ──────────────────────────────────────────────────────────────


def build_structure_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
    names: Mapping[str, str],
    *,
    min_consecutive_boards: int = 2,
    board_gap_mode: str = "wave",
) -> dict[str, object]:
    """编排结构因子研究（纯函数，不连数据库）。"""

    _, factor_samples = build_factor_samples(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    samples = attach_structure_features(factor_samples, daily_bars)
    first_boards = extract_first_board_samples(
        events,
        calendar,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    first_board_index = {
        (str(sample.get("vt_symbol") or ""), str(sample.get("trade_date") or "")): sample.get(
            "eventual_peak"
        )
        for sample in first_boards
    }

    numeric_reports = [
        compare_numeric_factor(samples, key) for key in STRUCTURE_NUMERIC_KEYS
    ]
    monthly_reports = [
        monthly_factor_stability(samples, key) for key in STRUCTURE_NUMERIC_KEYS
    ]
    calm_values = sorted(
        value
        for value in (_sample_float(sample.get("prelude_vol_cv_7d")) for sample in samples)
        if value is not None
    )
    calm_median = median(calm_values) if calm_values else None
    touch_index, _ = _build_touch_index(events, calendar)

    positive = sum(1 for sample in samples if _bool(sample.get("is_leader")))
    peak3 = sum(1 for sample in samples if _is_peak3(sample))
    report: dict[str, object] = {
        "status": "ok" if samples else "insufficient_data",
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "board_gap_mode": board_gap_mode,
        "thresholds": {
            "ma_windows": MA_WINDOWS,
            "converge_lag_days": CONVERGE_LAG_DAYS,
            "spearman_cut": SPEARMAN_CUT,
            "tightness_max_pct": TIGHTNESS_MAX_PCT,
            "small_gain_cap_pct": SMALL_GAIN_CAP_PCT,
            "low_position_126d_max": LOW_POSITION_126D_MAX,
            "wave_position_20d_max": WAVE_POSITION_20D_MAX,
            "wave_days_since_low_max": WAVE_DAYS_SINCE_LOW_MAX,
            "ma_near_10_20_pct": MA_NEAR_10_20_PCT,
            "calm_cv_median": round(calm_median, 4) if calm_median is not None else None,
        },
        "first_board_count": len(samples),
        "label_balance": {
            "positive": positive,
            "negative": len(samples) - positive,
            "positive_rate": round(positive / len(samples), 4) if samples else None,
            "peak3": peak3,
            "peak3_rate": round(peak3 / len(samples), 4) if samples else None,
        },
        "case_audit": _audit_cases(daily_bars, first_board_index, names),
        "hit_rates": _structure_hit_rates(samples),
        "numeric_factors": numeric_reports,
        "ma_state_categorical": compare_categorical_factor(samples, "ma_state"),
        "ma_state_outcomes": _categorical_outcomes(samples, "ma_state"),
        "regime_split": _regime_split(samples),
        "monthly_stability": monthly_reports,
        "june_july_check": _june_july_check(monthly_reports),
        "combos": _structure_combo_rows(samples),
        "miss_analysis": _miss_analysis(samples),
        "auction_gap": compare_numeric_factor(samples, "auction_gap_pct"),
        "owner_rules": _owner_rule_rows(samples, calm_median=calm_median),
        "owner_rules_monthly": _monthly_rule_rates(samples, calm_median=calm_median),
        "auction_by_type": _auction_by_type(samples),
        "frontier_by_height": _frontier_by_height(samples, calm_median=calm_median),
        "touch_seal": _touch_seal_analysis(events, daily_bars, calendar, calm_median=calm_median),
        "premarket_frame": build_premarket_structure_frame(
            daily_bars,
            first_board_index,
            names,
            calendar,
            calm_median=calm_median,
            touch_index=touch_index,
        ),
        "sensitivity": _sensitivity_rows(factor_samples, samples, daily_bars),
        "collinearity": collinearity_matrix(samples, _COLLINEARITY_KEYS),
        "notes": list(_RESEARCH_NOTES),
    }
    report["final_verdicts"] = _final_verdicts(report)
    return report


def run_research(*, start: date, end: date) -> dict[str, object]:
    """加载冻结数据集并返回结构因子研究报告。"""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    daily_bars = load_daily_bars_all(
        start - timedelta(days=DAILY_LOOKBACK_DAYS),
        end + timedelta(days=DAILY_FORWARD_DAYS),
    )
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    memberships = load_sector_memberships_all()
    sector_bars = load_sector_daily_bars(start - timedelta(days=SECTOR_LOOKBACK_DAYS), end)
    names = load_stock_names()
    report = build_structure_report(
        events, daily_bars, calendar, memberships, sector_bars, names
    )
    coverage = dict(dataset.get("coverage") or {})
    coverage["trade_days_in_window"] = len(calendar)
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["coverage"] = coverage
    report["input_fingerprint"] = hashlib.sha256(
        f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{report['first_board_count']}".encode()
    ).hexdigest()[:16]
    return report


# ── Markdown 渲染 ─────────────────────────────────────────────────────────


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%" if value is not None else "-"


def _verdict_icon(verdict: object) -> str:
    return {"符合": "✅", "不符合": "❌", "数据不足": "➖"}.get(str(verdict), "?")


def render_markdown(result: Mapping[str, object]) -> str:
    """渲染结构因子研究证据报告。"""

    balance = result.get("label_balance") or {}
    lines = [
        "# 首板结构因子研究（均线收拢/波浪 + 量能梯形 + 案例核查）",
        "",
        "## Boundary",
        "",
        f"- 状态：`{result.get('status') or 'unavailable'}`；研究版本 `{result.get('study_version') or '-'}`。",
        "- 只读 `stock_events`/`stock_daily_bars`/板块数据，不触碰任何实时链路。",
        "- `is_leader`/`eventual_peak`/`d1_*` 是未来标签，`auction_gap_pct` 是 D 日标签，仅用于对照分组。",
        f"- 成功标签：连板 >= {result.get('min_consecutive_boards')} 板（{result.get('board_gap_mode')} 切浪）；妖股 = >=3 板。",
        "- 全部结构因子 D-1 收盘可观测（MA5/10/20/30 + 成交额 + 涨跌幅），无分钟数据。",
        "",
        "## 模型说明（先把模型说一遍）",
        "",
        "- 因子族：①均线结构（空头/多头排列、收拢、金叉、粘合、站稳、缠绕）②量能梯形"
        "（5/10 日量序 spearman、连增/连减）③控盘小阳 ④波浪位置（20 日位置/低点距今）。",
        "- 预登记组合（先验，非事后搜索）：lowpos_converge / lowpos_converge_strict / lowpos_tight /"
        " trap_up_lowpos / trap_down_lowpos / wave_bull_pullback / converge_trap_up。",
        "- 验收口径：盘前全市场框架给出「出现首板涨停的几率」与「每交易日平均候选数」，"
        "lift>=3 → 过滤级、1.5-3 → 排序级、<1.5 → 淘汰（预声明）；"
        "覆盖率看命中率的 ≥2板/≥3板两列；漏网妖股见漏网归因。",
        "",
        "## Sample Balance",
        "",
        f"- 结算范围：`{result.get('start') or '-'}` 至 `{result.get('end') or '-'}`。",
        f"- 首板样本：{result.get('first_board_count')} 个；输入指纹 `{result.get('input_fingerprint') or '-'}`。",
        f"- 正样本（>=2 板）：{balance.get('positive')}（{_pct(balance.get('positive_rate'))}）；"
        f"妖股（>=3 板）：{balance.get('peak3')}（{_pct(balance.get('peak3_rate'))}）。",
        "",
    ]

    # ① 案例核查
    audit = result.get("case_audit") or {}
    cases = audit.get("cases") or []
    lines.extend(
        [
            "## ① 案例核查（主人 14 个案例逐条裁决）",
            "",
            f"- 解析成功 {audit.get('cases_resolved')}/{len(cases)} 例；核查点合计 "
            f"{audit.get('claims_total')} 条：符合 {audit.get('claims_passed')} / "
            f"不符合 {audit.get('claims_failed')} / 数据不足 {audit.get('claims_insufficient')}。",
            "",
        ]
    )
    for case in cases:
        if case.get("status") != "ok":
            lines.append(f"### {case.get('name')}（{case.get('first_board')}）—— 未解析")
            lines.append("")
            continue
        integrity = (
            f"首板日涨幅 {_fmt(case.get('board_change_pct'))}%，"
            f"{'在' if case.get('in_first_board_set') else '不在'}首板事件集，"
            f"eventual_peak={_fmt(case.get('eventual_peak'))}"
        )
        lines.extend(
            [
                f"### {case.get('name')}（{case.get('first_board')}，{case.get('vt_symbol')}）",
                "",
                f"- 完整性：{integrity}。主人笔记：{case.get('note')}。",
                "",
                "| 核查点 | 主人描述 | 数据证据 | 裁决 |",
                "|---|---|---|---|",
            ]
        )
        for claim in case.get("claims") or []:
            lines.append(
                f"| {claim.get('id')} | {claim.get('desc')} | {claim.get('evidence')} | "
                f"{_verdict_icon(claim.get('verdict'))} {claim.get('verdict')} |"
            )
        lines.append("")

    # ② 形态命中率
    lines.extend(
        [
            "## ② 形态命中率（≥2板 / ≥3板妖股 / 1板夭折）",
            "",
            "| 形态 | ≥2板命中率 | ≥3板命中率 | 夭折组命中率 | 命中比 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in result.get("hit_rates") or []:
        lines.append(
            f"| {row.get('pattern')} | {_pct(row.get('leader_hit_rate'))} "
            f"({row.get('leader_hits')}/{row.get('leader_total')}) | "
            f"{_pct(row.get('leader3_hit_rate'))} ({row.get('leader3_hits')}/{row.get('leader3_total')}) | "
            f"{_pct(row.get('non_leader_hit_rate'))} ({row.get('non_leader_hits')}/{row.get('non_leader_total')}) | "
            f"{_fmt(row.get('rate_ratio'))} |"
        )

    # ③ 数值区分度
    lines.extend(
        [
            "",
            "## ③ 预测区分度（≥2 板标签 AUC + 五分位 + bootstrap CI）",
            "",
            "| 因子 | 样本 | 正均值 | 负均值 | AUC | 方向 | 均值差 95%CI |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in result.get("numeric_factors") or []:
        ci = f"[{_fmt(item.get('mean_delta_lower_95'))}, {_fmt(item.get('mean_delta_upper_95'))}]"
        lines.append(
            f"| {item.get('factor_key')} | {item.get('sample_count')} | "
            f"{_fmt(item.get('positive_mean'))} | {_fmt(item.get('negative_mean'))} | "
            f"{_fmt(item.get('auc'))} | {item.get('direction')} | {ci} |"
        )
    outcomes = (result.get("ma_state_outcomes") or {}).get("categories") or []
    if outcomes:
        lines.extend(
            [
                "",
                "### ma_state 分类结局（≥2 板率 + D+1 收益）",
                "",
                "| 状态 | 样本 | ≥2 板率 | D+1 开盘均收益 | D+1 胜率 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for item in outcomes:
            lines.append(
                f"| {item.get('category')} | {item.get('total')} | "
                f"{_pct(item.get('leader_rate'))} | {_fmt(item.get('d1_open_return_mean'))} | "
                f"{_pct(item.get('d1_open_win_rate'))} |"
            )

    # ④ 市况分型
    regime = result.get("regime_split") or {}
    by_regime = regime.get("by_regime") or {}
    lines.extend(
        [
            "",
            "## ④ 市况分型（上证 MA20 上/下 × 形态族；单 episode 描述性，不算验证）",
            "",
            "| regime | 样本 | ≥2板率 | ≥3板率 |",
            "|---|---:|---:|---:|",
        ]
    )
    for key, label in (("above", "MA20 上方（行情好）"), ("below", "MA20 下方（行情差）")):
        stats = by_regime.get(key) or {}
        lines.append(
            f"| {label} | {stats.get('total')} | {_pct(stats.get('leader_rate'))} | "
            f"{_pct(stats.get('leader3_rate'))} |"
        )
    month_counts = regime.get("regime_month_counts") or []
    if month_counts:
        lines.extend(
            [
                "",
                "### regime × 月份样本计数（混淆检查）",
                "",
                "| 月份 | MA20上 | MA20下 | 未知 |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in month_counts:
            lines.append(
                f"| {row.get('month')} | {row.get('above')} | {row.get('below')} | {row.get('unknown')} |"
            )
    for key, label in (("above", "MA20 上方"), ("below", "MA20 下方")):
        stats = by_regime.get(key) or {}
        combos = stats.get("combos") or []
        if not combos:
            continue
        lines.extend(
            [
                "",
                f"### 组合结局（{label}）",
                "",
                "| 组合 | 样本 | ≥2板率 | ≥3板率 |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in combos:
            lines.append(
                f"| {row.get('combo')} | {row.get('total')} | "
                f"{_pct(row.get('leader_rate'))} | {_pct(row.get('leader3_rate'))} |"
            )

    # ⑤ 月度一致性
    lines.extend(
        [
            "",
            "## ⑤ 月度一致性（防过拟合：显式 2026-06 vs 2026-07 方向对照）",
            "",
            "| 因子 | 全样本 AUC | 月度一致率 | 6 月 AUC/方向 | 7 月 AUC/方向 | 翻转 |",
            "|---|---:|---:|---|---|---|",
        ]
    )
    monthly_by_key = {
        str(item.get("factor_key")): item for item in result.get("monthly_stability") or []
    }
    for check in result.get("june_july_check") or []:
        report = monthly_by_key.get(str(check.get("factor_key"))) or {}
        lines.append(
            f"| {check.get('factor_key')} | {_fmt(report.get('full_auc'))} | "
            f"{_fmt(report.get('monthly_agreement'))} | "
            f"{_fmt(check.get('june_auc'))}/{check.get('june_direction')} | "
            f"{_fmt(check.get('july_auc'))}/{check.get('july_direction')} | "
            f"{'⚠️ 翻转' if check.get('flipped') else '一致'} |"
        )

    # ⑥ 组合 + 漏网归因
    combos = result.get("combos") or []
    if combos:
        lines.extend(
            [
                "",
                "## ⑥ 预登记组合 vs 基线（先验设定，非事后搜索）",
                "",
                "| 组合 | 说明 | 样本 | ≥2板率 | ≥3板率 | D+1 开盘均收益 | D+1 胜率 |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in combos:
            lines.append(
                f"| {row.get('combo')} | {row.get('description')} | {row.get('total')} | "
                f"{_pct(row.get('leader_rate'))} | {_pct(row.get('leader3_rate'))} | "
                f"{_fmt(row.get('d1_open_return_mean'))} | {_pct(row.get('d1_open_win_rate'))} |"
            )
    misses = result.get("miss_analysis") or []
    if misses:
        lines.extend(
            [
                "",
                "### 漏网归因（≥2 板票被组合拒掉的子条件统计 + 妖股清单）",
                "",
                "| 组合 | ≥2板召回 | 漏网数 | 主要拒因 | 漏网妖股数 |",
                "|---|---:|---:|---|---:|",
            ]
        )
        for row in misses:
            clauses = row.get("missed_by_clause") or {}
            top = ", ".join(
                f"{key}×{value}"
                for key, value in sorted(clauses.items(), key=lambda item: -item[1])[:3]
            )
            lines.append(
                f"| {row.get('combo')} | {_pct(row.get('recall'))} | {row.get('missed_count')} | "
                f"{top or '-'} | {row.get('missed_leader3_count')} |"
            )
        lines.append("")
        for row in misses:
            missed3 = row.get("missed_leader3") or []
            if not missed3:
                continue
            lines.append(f"#### {row.get('combo')} 漏网妖股（top {len(missed3)}）")
            lines.append("")
            lines.append("| 代码 | 名称 | 首板日 | 最高板 | 拒因 |")
            lines.append("|---|---|---|---:|---|")
            for item in missed3[:20]:
                lines.append(
                    f"| {item.get('vt_symbol')} | {item.get('name')} | {item.get('trade_date')} | "
                    f"{_fmt(item.get('eventual_peak'))} | {', '.join(item.get('failed_clauses') or [])} |"
                )
            lines.append("")

    # ⑦ 盘前全市场框架
    frame = result.get("premarket_frame") or {}
    if frame:
        base = frame.get("base_rates") or {}
        lines.extend(
            [
                "## ⑦ 盘前全市场框架（「出现首板涨停的几率」+ 每交易日候选数）",
                "",
                f"- 有效股票日 {frame.get('stock_days')}（主板合格 {frame.get('eligible_symbols')} 只 × "
                f"{frame.get('scanned_market_days')} 交易日；label_invalid 剔除 {frame.get('invalid_labels')}）。",
                f"- 无条件基线：5 日内首板率 {_pct(base.get('board_5d'))}；"
                f"≥2板率 {_pct(base.get('leader_5d'))}；≥3板率 {_pct(base.get('peak3_5d'))}。",
                f"- 裁决带（预声明）：{frame.get('interpretation_bands')}。",
                "",
                "| 组合 | 候选股票日 | 平均候选/日 | 5日首板命中 | lift | 命中后≥2板率 | ≥3板命中 |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in frame.get("per_combo") or []:
            lines.append(
                f"| {row.get('combo')} | {row.get('candidate_days')} | "
                f"{_fmt(row.get('avg_candidates_per_day'))} | {_pct(row.get('hit_rate'))} | "
                f"{_fmt(row.get('lift'))} | {_pct(row.get('leader_given_board'))} | "
                f"{row.get('peak3_hits')} |"
            )
        regime_frame = frame.get("by_regime") or {}
        for key, label in (("above", "MA20 上方"), ("below", "MA20 下方")):
            stats = regime_frame.get(key) or {}
            if not stats:
                continue
            lines.extend(
                [
                    "",
                    f"### 盘前框架 × regime（{label}，基线 5 日首板率 {_pct(stats.get('base_board_rate'))}）",
                    "",
                    "| 组合 | 候选股票日 | 5日首板命中 | lift | 命中后≥2板率 |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for row in stats.get("per_combo") or []:
                lines.append(
                    f"| {row.get('combo')} | {row.get('candidate_days')} | "
                    f"{_pct(row.get('hit_rate'))} | {_fmt(row.get('lift'))} | "
                    f"{_pct(row.get('leader_given_board'))} |"
                )

    # ⑧ 竞价缺口
    auction = result.get("auction_gap") or {}
    if auction:
        lines.extend(
            [
                "",
                "## ⑧ 竞价缺口（D 日执行证据：只回答「已首板后谁延续」）",
                "",
                f"- 样本 {auction.get('sample_count')}；成功组均值 {_fmt(auction.get('positive_mean'))}% vs "
                f"失败组 {_fmt(auction.get('negative_mean'))}%；AUC {_fmt(auction.get('auc'))}"
                f"（{auction.get('direction')}）；均值差 95%CI "
                f"[{_fmt(auction.get('mean_delta_lower_95'))}, {_fmt(auction.get('mean_delta_upper_95'))}]。",
                "",
                "| 分位 | 样本 | ≥2板率 | 区间 |",
                "|---|---:|---:|---|",
            ]
        )
        for quintile in auction.get("quintile_positive_rates") or []:
            lines.append(
                f"| Q{quintile.get('quintile')} | {quintile.get('total')} | "
                f"{_pct(quintile.get('positive_rate'))} | "
                f"{_fmt(quintile.get('value_min'))}~{_fmt(quintile.get('value_max'))} |"
            )

    # ⑨ 敏感性
    sensitivity = result.get("sensitivity") or {}
    if sensitivity:
        lines.extend(["", "## ⑨ 敏感性（预声明档位，不挑最优）", ""])
        lines.extend(
            [
                "### converge_lag（收拢窗口 3/5/8 日）× 组合 ≥2板率",
                "",
                "| lag | lowpos_converge | lowpos_converge_strict | converge_trap_up |",
                "|---:|---:|---:|---:|",
            ]
        )
        for row in sensitivity.get("converge_lag") or []:
            lines.append(
                f"| {row.get('converge_lag')} | "
                f"{_pct((row.get('lowpos_converge') or {}).get('leader_rate'))} | "
                f"{_pct((row.get('lowpos_converge_strict') or {}).get('leader_rate'))} | "
                f"{_pct((row.get('converge_trap_up') or {}).get('leader_rate'))} |"
            )
        lines.extend(
            [
                "",
                "### spearman cut（梯形阈值）× 低位组合",
                "",
                "| cut | 方向 | 样本 | ≥2板率 |",
                "|---:|---|---:|---:|",
            ]
        )
        for row in sensitivity.get("spearman_cut") or []:
            lines.append(
                f"| {row.get('cut')} | {row.get('direction')} | {row.get('total')} | "
                f"{_pct(row.get('leader_rate'))} |"
            )
        lines.extend(
            [
                "",
                "### 紧凑度阈值（三线粘合 2/3/5%）",
                "",
                "| 上限 | 样本 | ≥2板率 |",
                "|---:|---:|---:|",
            ]
        )
        for row in sensitivity.get("tightness") or []:
            lines.append(
                f"| {row.get('tightness_max')}% | {row.get('total')} | "
                f"{_pct(row.get('leader_rate'))} |"
            )
        lines.extend(
            [
                "",
                "### 小阳上限（1.0/1.5/2.0%）",
                "",
                "| 上限 | small_gain≥2 样本 | ≥2板率 |",
                "|---:|---:|---:|",
            ]
        )
        for row in sensitivity.get("small_gain_cap") or []:
            lines.append(
                f"| {row.get('small_gain_cap')}% | {row.get('small_gain2_total')} | "
                f"{_pct(row.get('small_gain2_leader_rate'))} |"
            )

    # ⑩ 共线性
    collinearity = result.get("collinearity") or []
    high_pairs = [pair for pair in collinearity if abs(pair.get("spearman") or 0.0) >= 0.7]
    if high_pairs:
        lines.extend(
            [
                "",
                "## ⑩ 共线性（|rho|>=0.7 的因子对）",
                "",
                "| 左 | 右 | Spearman | 样本 |",
                "|---|---|---:|---:|",
            ]
        )
        for pair in high_pairs:
            lines.append(
                f"| {pair.get('left')} | {pair.get('right')} | "
                f"{_fmt(pair.get('spearman'))} | {pair.get('sample_count')} |"
            )
    # ⑪ 主人规则原样验证
    owner_rules = result.get("owner_rules") or []
    if owner_rules:
        lines.extend(
            [
                "",
                "## ⑪ 主人规则原样验证（R1-R7，按原话定义，不加价格低位条件）",
                "",
                "| 规则 | 说明 | 样本 | ≥2板率 | ≥3板率 | 月度一致率 | 盘前lift | 平均候选/日 |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        owner_monthly = {
            row.get("rule"): row for row in result.get("owner_rules_monthly") or []
        }
        pre_map = {
            item.get("rule"): item
            for item in (result.get("premarket_frame") or {}).get("owner_rules_premarket") or []
        }
        for row in owner_rules:
            name = row.get("rule")
            monthly = owner_monthly.get(name) or {}
            pre = pre_map.get(name) or {}
            lines.append(
                f"| {name} | {row.get('description')} | {row.get('total')} | "
                f"{_pct(row.get('leader_rate'))} | {_pct(row.get('leader3_rate'))} | "
                f"{_fmt(monthly.get('monthly_agreement'))} | {_fmt(pre.get('lift'))} | "
                f"{_fmt(pre.get('avg_candidates_per_day'))} |"
            )
        lines.append(
            "- 注：R1-R7 按主人原话定义（低位=均线结构本身，未加 position_126d）；"
            "盘前 lift 的基线为 5 日首板率（见⑦）；月度一致率=规则胜率相对当月基线方向的一致月占比。"
        )

    # ⑫ 早盘价格 × 类型
    auction_by_type = result.get("auction_by_type") or []
    if auction_by_type:
        lines.extend(
            [
                "",
                "## ⑫ 早盘价格 × 类型（竞价缺口，D 日执行证据）",
                "",
                "| 类型 | 样本 | ≥2板率 | ≥3板率 | 竞价均值 | 竞价中位 | 高开≥2%占比 |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        type_labels = {
            "lowpos_form1": "低位·形式一（收拢/金叉）",
            "lowpos_form2": "低位·形式二（三线粘合）",
            "wave_bull": "波浪·向上",
            "wave_price": "波浪·平行",
            "other": "其他",
        }
        for row in auction_by_type:
            lines.append(
                f"| {type_labels.get(str(row.get('type')), str(row.get('type')))} | {row.get('total')} | "
                f"{_pct(row.get('leader_rate'))} | {_pct(row.get('leader3_rate'))} | "
                f"{_fmt(row.get('gap_mean'))}% | {_fmt(row.get('gap_median'))}% | "
                f"{_pct(row.get('gap_ge2_rate'))} |"
            )
        frame = result.get("premarket_frame") or {}
        auction_frame = frame.get("auction_frame") or {}
        cells = auction_frame.get("cells") or []
        if cells:
            lines.extend(
                [
                    "",
                    f"### 「竞价看出首板」精确概率（盘前全市场：类型 × 次日竞价 → P(次日首板)，"
                    f"无条件基线 {_pct(auction_frame.get('base_board_1d'))}）",
                    "",
                    "| 类型 | 竞价桶 | 股票日 | 次日首板 | 概率 | lift |",
                    "|---|---|---:|---:|---:|---:|",
                ]
            )
            for cell in cells:
                lines.append(
                    f"| {type_labels.get(str(cell.get('type')), str(cell.get('type')))} | "
                    f"{cell.get('bucket')}% | {cell.get('days')} | {cell.get('board_hits')} | "
                    f"{_pct(cell.get('hit_rate'))} | {_fmt(cell.get('lift'))} |"
                )

    # ⑬ 最终裁决表
    verdicts = result.get("final_verdicts") or []
    if verdicts:
        lines.extend(
            [
                "",
                "## ⑬ 最终裁决表（过滤级/排序级/观察/淘汰，预声明逻辑）",
                "",
                "| 条件 | 来源 | 裁决 | 用途 | 证据 |",
                "|---|---|---|---|---|",
            ]
        )
        for row in verdicts:
            lines.append(
                f"| {row.get('condition')} | {row.get('origin')} | **{row.get('verdict')}** | "
                f"{row.get('usage')} | {row.get('evidence')} |"
            )

    # ⑭ 召回×占比前沿 + 封板率
    frontier = result.get("frontier_by_height") or []
    frame = result.get("premarket_frame") or {}
    frontier_pre = {row.get("filter"): row for row in frame.get("frontier") or []}
    touch_seal = result.get("touch_seal") or {}
    touch_pre = {row.get("filter"): row for row in touch_seal.get("per_filter") or []}
    if frontier:
        lines.extend(
            [
                "",
                "## ⑭ 通用因子召回×占比前沿（D-1 全票验证）",
                "",
                "召回=各高度连板票首板日 D-1 被过滤找到的比例（frame-1 去重）；"
                "占比=过滤中的票占合格主板票比例（frame-2）；封板率=首触后封板占比。",
                "",
                "| 过滤器 | 日候选占比 | p90 | ≥2板召回 | ≥3板召回 | ≥4板召回 | ≥5板召回 | 5日首板lift | 封板率(过) | 封板率(拒) |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in frontier:
            name = row.get("filter")
            pre = frontier_pre.get(name) or {}
            seal = touch_pre.get(name) or {}
            lines.append(
                f"| {name} | {_pct(pre.get('share_mean'))} | {_pct(pre.get('share_p90'))} | "
                f"{_pct(row.get('coverage'))} | {_pct(row.get('recall_peak3'))} | "
                f"{_pct(row.get('recall_peak4'))} | {_pct(row.get('recall_peak5p'))} | "
                f"{_fmt(pre.get('lift'))} | {_pct(seal.get('seal_rate'))} | "
                f"{_pct(seal.get('rejected_seal_rate'))} |"
            )
        stats = touch_seal.get("touch_stats") or {}
        lines.append(
            f"- 首触样本 {touch_seal.get('total_touches')}（zt 首板 {stats.get('zt_first')} + "
            f"zbgc 首触 {stats.get('zbgc_first_touch')}，非首触炸板 {stats.get('zbgc_not_first')} 已剔）；"
            f"无条件封板率 {_pct(touch_seal.get('baseline_seal_rate'))}。"
        )

    # ⑮ 竞价 × 触板逐日验证
    auction_frame = frame.get("auction_frame") or {}
    monthly_touch = auction_frame.get("monthly_touch") or []
    if monthly_touch:
        lines.extend(
            [
                "",
                "## ⑮ 竞价 × 触板概率（逐日/逐月验证）",
                "",
                "逐月触板率（含炸板；桶=次日竞价缺口）：",
                "",
                "| 月份 | <0% | 0-1% | 1-2% | 2-4% | 4-9.5% | ≥9.5% |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        by_month: dict[str, dict[str, dict[str, object]]] = {}
        for row in monthly_touch:
            by_month.setdefault(str(row.get("month")), {})[str(row.get("bucket"))] = row
        for month in sorted(by_month):
            cells = by_month[month]
            lines.append(
                f"| {month} | "
                + " | ".join(
                    _pct((cells.get(label) or {}).get("touch_rate"))
                    for label, _, _ in AUCTION_GAP_BUCKETS
                )
                + " |"
            )
        consistency = auction_frame.get("daily_consistency") or {}
        lines.append(
            f"- 逐日一致性：{consistency.get('days_win')}/{consistency.get('days_valid')} 个交易日 "
            f"触板率（竞价≥2%) > 触板率（竞价<2%)（占比 {_pct(consistency.get('win_share'))}；"
            f"{consistency.get('rule')}）。"
        )

    lines.extend(["", "## Notes", ""])
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="首板结构因子研究（均线收拢/波浪+量能梯形+案例核查）")
    parser.add_argument("--start", required=True, help="样本窗口起点（ISO 日期）")
    parser.add_argument("--end", required=True, help="样本窗口终点（ISO 日期）")
    parser.add_argument("--json-output", required=True, help="JSON 证据输出路径")
    parser.add_argument("--markdown-output", required=True, help="Markdown 报告输出路径")
    arguments = parser.parse_args(argv)

    report = run_research(
        start=date.fromisoformat(arguments.start),
        end=date.fromisoformat(arguments.end),
    )
    json_path = Path(arguments.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    markdown_path = Path(arguments.markdown_output)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    balance = report.get("label_balance") or {}
    audit = report.get("case_audit") or {}
    print(
        f"structure research: status={report['status']} "
        f"samples={report['first_board_count']} "
        f"positive_rate={balance.get('positive_rate')} "
        f"case_claims={audit.get('claims_passed')}/{audit.get('claims_total')} passed"
    )


if __name__ == "__main__":
    main()
