"""首板融合计分卡研究（低位分 + 波浪分 → Top-N 榜 + 最低分底线）。

主人假说（2026-08-03，对前一轮「拆条+硬门槛」测法的批评）：

- 通用因子是**融合规则**：低位型/波浪型各自是一张计分卡，剂量响应（越久/越深越好）、
  阶段递进（MA10 上穿 MA20 → MA20 再上穿 MA30 概率逐级提高）、加分项（量能梯形、
  期间未出现涨停），不是独立门槛的 AND。
- 用法：按融合分排序，每日筛**前 N 个**；同时排查**最低分底线**（lift 跨档的最低分）。

主人已裁决的设计岔路：子分**等权**（0-1 爬坡、封顶值预声明、不调参）；
「期间未出现涨停」是**加分项**（+1 分），不是硬门槛。

计分卡（全部 D-1 收盘可观测，阈值全部预声明 in-sample）：

- **低位分（0-7）**：资格门 bear_run_max_40d>=15；L1 基底深度（/8%）、L2 基底时长（/30）、
  L3 收敛时长（/15）、L4 穿越阶段（stage/2）、L5 企稳（/5）、L6 量能梯形加分、
  L7 近期触碰加分（v2：主人「期间未出现涨停是扣分项」→ 近 20 日有触碰 +1）。
- **波浪分（0-4）**：资格门向上波浪（多头排列）或横盘波浪（缠绕+回前低，v2 补入）；
  W1 多头时长（/20）、W2 回调深度（position_20d 参照 0.8）、W3 企稳
  （days_since_20d_low/3 衰减）、W4 量能加分。
- **统一榜**：fused_score = max(低位分/7, 波浪分/4)（0-1），类型标签 lowpos/wave/both。

验证（预声明，与主人约定）：frame-1 区分度（AUC vs 子分 vs bias_ma20）+ 分数桶结局 +
漏网妖股；frame-2 六桶首板率单调性（spearman>=0.8）+ Top-N 榜（5/10/20/50）+
最低分底线（lift 跨 1.0/1.5/2.0/3.0）+ 月度一致性（>=0.7 且 6/7 月不翻转）+
regime 拆分 + 对照组（必须打败最强子分单用与 bias_ma20>=5%）。

依赖方向规则与结构研究模块一致：本模块 import 老模块的纯函数，老模块不反向 import。
只读研究脚本：不触碰实时表/API/持仓。hit_peak/eventual_peak/is_leader 是未来标签，
仅用于对照分组，绝不作为 D-1 可交易因子。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence, Set as AbstractSet
from datetime import date, timedelta
from pathlib import Path

from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    compare_numeric_factor,
    extract_first_board_samples,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    DAILY_FORWARD_DAYS,
    DAILY_LOOKBACK_DAYS,
    SECTOR_LOOKBACK_DAYS,
    _bool,
    _number,
    _sample_float,
    build_factor_samples,
)
from alphaagent.server.services.limit_up.leader_first_board_factor_stability_research import (
    _spearman_pairs,
    monthly_factor_stability,
)
from alphaagent.server.services.limit_up.leader_first_board_prelude_pattern_research import (
    _june_july_check,
)
from alphaagent.server.services.limit_up.leader_first_board_structure_research import (
    PREMARKET_BAR_SLICE,
    PREMARKET_FORWARD_DAYS,
    PREMARKET_LABEL_MAX_MARKET_SPAN,
    PREMARKET_MIN_HISTORY,
    PREMARKET_TAIL_EXCLUDE_MARKET_DAYS,
    _index_regime_at,
    _index_regime_map,
    _ma_at,
    _outcome_stats,
    _prefix_sums,
    _structure_features,
)
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    INDEX_VT_SYMBOL,
    _is_first_board_candidate,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_sector_daily_bars,
    load_sector_memberships_all,
    load_stock_names,
)

STUDY_VERSION = "leader-first-board-fused-score-v2"

# v2 变更（2026-08-03，主人 首板研究.txt:183 澄清 + :103 横盘波浪补入）：
# 1. 「期间未出现涨停 是扣分项」——v1 按问答实现成加分项（pure+1），方向与数据相反
#    （v1 证据：L7_purity AUC 0.4737 反向、L7_pure 对照 lift 0.7741）。v2 反向为
#    「近 20 日有 zt/zbgc 触碰 +1 / 无触碰 0」（扣分项的等价平移，保 0-7 标度）。
# 2. 波浪门补横盘波浪（首板研究.txt:103「波浪要么是横盘波浪，要么是行情好的向上波浪」）：
#    均线缠绕（ma_state=tangled）+ 20 日位置<=0.35 + 距低点<=3 日（爱丽型）。

# ── 预声明阈值（主人 2026-08-03 裁定等权不调参；敏感性只做预声明档位）─────────
JOURNEY_WINDOW_DAYS = 40  # 旅程回望窗（基底「约1个月+」+ 收敛过程都在窗内度量）
JOURNEY_MIN_HISTORY = JOURNEY_WINDOW_DAYS + 29  # 窗内最老一根也要能算 MA30
BEAR_RUN_GATE_MIN = 15  # 低位资格门：最长空头连续天数（主人「大概1个月及以上」）
SENSITIVITY_BEAR_GATES = (10, 15, 20)
DEPTH_FULL_PCT = 8.0  # L1 满分：空头期最大 (MA20-MA10)+(MA30-MA20) 相对收盘 %
BEAR_RUN_FULL_DAYS = 30  # L2 满分：最长空头连续天数
CONV_FULL_DAYS = 15  # L3 满分：收敛态持续天数
SENSITIVITY_CONV_CAPS = (10, 15, 20)
CONVERGE_HALF_RATIO = 0.5  # |spread| 较峰值收窄 >=50% 才算进入收敛态
ABOVE_MA10_FULL_DAYS = 5  # L5 满分：连续站稳 MA10 天数
PURITY_LOOKBACK_BARS = 20  # L7 纯度窗（个股交易日，停牌票偏严）
SENSITIVITY_PURITY_WINDOWS = (10, 20, 30)
PURITY_EVENTS_EXTRA_DAYS = 45  # 纯度事件前向多加载的自然日（覆盖 20 市场日回溯删失）
VOL_SPEARMAN_FULL = 0.7  # L6/W4 量能梯形满分（|spearman|）
VOL_SPEARMAN_HALF = 0.5
BULL_RUN_FULL_DAYS = 20  # W1 满分：多头排列连续天数
WAVE_POSITION_REF = 0.8  # W2 回调深度参照：position_20d=0.8 起给分，0 满分
WAVE_LOW_FULL_DAYS = 3  # W3 企稳衰减到 0 的距低点天数
# 横盘波浪资格（爱丽型；预声明）：均线缠绕 + 回到 20 日低位 + 低点刚企稳
SIDEWAY_POSITION_MAX = 0.35
SIDEWAY_LOW_DAYS_MAX = 3

LOWPOS_SCORE_MAX = 7.0
WAVE_SCORE_MAX = 4.0

# frame-2 桶与及格线（预声明）
SCORE_BUCKET_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.01)  # 0 桶=未入榜（score==0），后五桶半开
TOP_N_LIST = (5, 10, 20, 50)
FLOOR_LIFT_TARGETS = (1.0, 1.5, 2.0, 3.0)
FLOOR_STEP = 0.05
TOP_BUCKET_MIN_SCORE = 0.6  # 月度一致性/顶桶口径
PASS_MONO_SPEARMAN = 0.8
PASS_TOP_LIFT = 2.0
PASS_TOP_MIN_DAYS = 100
PASS_MONTHLY_AGREEMENT = 0.7
MIN_MONTH_TOP_DAYS = 30
MISSED_PEAK3_LIST_MAX = 50

LOWPOS_SUB_KEYS = (
    "L1_depth",
    "L2_duration",
    "L3_converge",
    "L4_stage",
    "L5_stabilize",
    "L6_volume",
    "L7_recent_touch",
)
WAVE_SUB_KEYS = ("W1_bull_duration", "W2_pullback", "W3_stabilize", "W4_volume")
FRAME1_AUC_KEYS = (
    "fused_score",
    "lowpos_score",
    "wave_score",
    *(f"lowpos_{key}" for key in LOWPOS_SUB_KEYS),
    *(f"wave_{key}" for key in WAVE_SUB_KEYS),
    "bias_ma20_pct",
)

_RESEARCH_NOTES = (
    "计分卡等权、封顶值全部预声明 in-sample（主人 2026-08-03 裁定不调参）；敏感性只做预声明档位。",
    "v2：「期间未出现涨停 是扣分项」（主人 首板研究.txt:183）→ L7 反向为近 20 日有触碰 +1；"
    "v1 曾按问答实现为纯度加分，方向与数据相反（v1 证据：L7_purity AUC 0.4737 反向、对照 lift 0.7741）。",
    "v2：波浪门补横盘波浪（首板研究.txt:103）：均线缠绕(tangled)+20日位置<=0.35+低点<=3日（爱丽型）。",
    "纯度窗用 20 个股交易日近似市场日（停牌票偏严）；纯度事件从 start-45 自然日前向加载，"
    "覆盖 20 市场日回溯，更早期的触碰未知（左删失，窗口头两个月的纯度略偏乐观）。",
    "低位资格门 bear_run_max_40d>=15 是硬条件（没有空头基底就不属于低位型）；"
    "波浪型不加纯度门（主人的波浪案例金钼 5-26 曾首板，本就带前次脉冲）。",
    "盘前全市场框架（frame 2）候选股票日自相关（分数连日成立），只报计数+lift 不做 CI。",
    "regime 只有 2026-07 一次崩盘 episode → 只给描述性结论，不算验证。",
    "敏感性只跑 frame-1（AUC/顶桶≥2板率）；frame-2 变体成本高，中央变体达标后再补。",
    "hit_peak/eventual_peak/is_leader 是未来标签仅作对照，绝不作为 D-1 可交易因子。",
)


# ── 旅程因子（纯函数，全部 D-1 可观测）──────────────────────────────────────


def _journey_features(
    bars_before: Sequence[Mapping[str, object]],
    touch_dates: AbstractSet[str] | None = None,
    *,
    purity_window: int = PURITY_LOOKBACK_BARS,
) -> dict[str, object]:
    """旅程因子：空头基底（深度/时长）+ 收敛时长 + 穿越阶段 + 纯度。

    ``bars_before`` = D-1 及之前日线（升序）；``touch_dates`` = 该票 zt/zbgc 触碰日
    集合（None=未知 → pure_20d 记 None）。历史不足一律 None（不混进 0）。
    """

    out: dict[str, object] = {
        "bear_run_max_40d": None,
        "bear_depth_peak_pct": None,
        "spread_peak_abs_pct": None,
        "conv_days": None,
        "cross_stage": None,
        "pure_20d": None,
    }
    if not bars_before:
        return out
    relevant = list(bars_before[-JOURNEY_MIN_HISTORY:])
    closes = [_number(row.get("close_price")) for row in relevant]
    n = len(closes)
    last = n - 1
    sums, counts = _prefix_sums(closes)

    def _ma(index: int, window: int) -> float | None:
        return _ma_at(sums, counts, index, window)

    ma10, ma20, ma30 = _ma(last, 10), _ma(last, 20), _ma(last, 30)
    if ma10 is not None and ma20 is not None and ma30 is not None:
        if ma10 < ma20:
            out["cross_stage"] = 0
        elif ma20 < ma30:
            out["cross_stage"] = 1
        else:
            out["cross_stage"] = 2

    if n >= JOURNEY_MIN_HISTORY:
        window_start = last - JOURNEY_WINDOW_DAYS + 1
        spreads: list[float | None] = []
        bear_flags: list[bool] = []
        depths: list[float | None] = []
        for index in range(window_start, last + 1):
            a, b, c = _ma(index, 10), _ma(index, 20), _ma(index, 30)
            close = closes[index]
            if a is None or b is None or c is None or not close:
                spreads.append(None)
                bear_flags.append(False)
                depths.append(None)
                continue
            spreads.append((a - b) / close * 100)
            is_bear = a < b < c
            bear_flags.append(is_bear)
            depths.append(((b - a) + (c - b)) / close * 100 if is_bear else None)
        best = 0
        run = 0
        for flag in bear_flags:
            run = run + 1 if flag else 0
            best = max(best, run)
        out["bear_run_max_40d"] = best
        valid_depths = [value for value in depths if value is not None]
        if valid_depths:
            out["bear_depth_peak_pct"] = round(max(valid_depths), 4)
        valid_spreads = [(offset, value) for offset, value in enumerate(spreads) if value is not None]
        if valid_spreads:
            peak_offset, peak_spread = max(valid_spreads, key=lambda pair: abs(pair[1]))
            out["spread_peak_abs_pct"] = round(abs(peak_spread), 4)
            last_spread = spreads[-1]
            if last_spread is not None and abs(last_spread) <= CONVERGE_HALF_RATIO * abs(
                peak_spread
            ):
                out["conv_days"] = last - (window_start + peak_offset)
            else:
                out["conv_days"] = 0

    if touch_dates is not None and len(bars_before) >= purity_window:
        window_dates = [
            str(row.get("trade_date") or "") for row in bars_before[-purity_window:]
        ]
        out["pure_20d"] = not any(day in touch_dates for day in window_dates)
    return out


def _touch_dates_by_symbol(
    events: Sequence[Mapping[str, object]],
) -> dict[str, set[str]]:
    """全量触碰事件（zt 任意 limit_times + zbgc）按票聚合日期集合（纯度判定用）。

    不能用首触索引：连板序列的首次封板可能远在 20 日前，但途中每天都在「出现涨停」。
    """

    out: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.get("event_type") not in ("limit_pool_zt", "limit_pool_zbgc"):
            continue
        symbol = str(event.get("vt_symbol") or "")
        day = str(event.get("trade_date") or "")
        if symbol and day:
            out[symbol].add(day)
    return out


# ── 计分卡（纯函数；等权爬坡，None 子分一律 0）───────────────────────────────


def _ramp(value: float | None, full: float) -> float:
    """等权爬坡：value/full 截断到 [0,1]；None → 0（算不出不送分）。"""

    if value is None or full <= 0:
        return 0.0
    return max(0.0, min(value / full, 1.0))


def _volume_bonus(spearman: float | None) -> float:
    """量能梯形加分（放量/萎缩任一方向）：|rho|>=0.7→1，>=0.5→0.5，否则 0。"""

    if spearman is None:
        return 0.0
    magnitude = abs(spearman)
    if magnitude >= VOL_SPEARMAN_FULL:
        return 1.0
    if magnitude >= VOL_SPEARMAN_HALF:
        return 0.5
    return 0.0


def _lowpos_score(
    features: Mapping[str, object],
    *,
    bear_gate: int = BEAR_RUN_GATE_MIN,
    conv_cap: int = CONV_FULL_DAYS,
) -> dict[str, object]:
    """低位分（0-7）：资格门最长空头>=bear_gate；L1-L7 等权子分。"""

    run = _sample_float(features.get("bear_run_max_40d"))
    qualified = run is not None and run >= bear_gate
    subs = {
        "L1_depth": _ramp(_sample_float(features.get("bear_depth_peak_pct")), DEPTH_FULL_PCT),
        "L2_duration": _ramp(run, BEAR_RUN_FULL_DAYS),
        "L3_converge": _ramp(_sample_float(features.get("conv_days")), conv_cap),
        "L4_stage": _ramp(_sample_float(features.get("cross_stage")), 2.0),
        "L5_stabilize": _ramp(
            _sample_float(features.get("above_ma10_streak")), ABOVE_MA10_FULL_DAYS
        ),
        "L6_volume": _volume_bonus(_sample_float(features.get("vol_spearman_5d"))),
        # v2：主人「期间未出现涨停 是扣分项」→ 近 20 日有触碰 +1（有股性），无 0
        "L7_recent_touch": 1.0 if features.get("pure_20d") is False else 0.0,
    }
    total = round(sum(subs.values()), 4)
    return {"qualified": qualified, "score": total if qualified else 0.0, "raw": total, "subs": subs}


def _wave_qualified(features: Mapping[str, object]) -> bool:
    """波浪资格门：向上波浪（多头排列）或横盘波浪（缠绕+回前低企稳，爱丽型）。"""

    if features.get("ma_bull_align") is True:
        return True
    position = _sample_float(features.get("position_20d"))
    low_days = _sample_float(features.get("days_since_20d_low"))
    return (
        features.get("ma_state") == "tangled"
        and position is not None
        and position <= SIDEWAY_POSITION_MAX
        and low_days is not None
        and low_days <= SIDEWAY_LOW_DAYS_MAX
    )


def _wave_score(features: Mapping[str, object]) -> dict[str, object]:
    """波浪分（0-4）：资格门向上/横盘波浪；W1-W4 等权子分（无纯度门）。"""

    qualified = _wave_qualified(features)
    position = _sample_float(features.get("position_20d"))
    low_days = _sample_float(features.get("days_since_20d_low"))
    subs = {
        "W1_bull_duration": _ramp(_sample_float(features.get("ma_bull_days")), BULL_RUN_FULL_DAYS),
        "W2_pullback": (
            max(0.0, min((WAVE_POSITION_REF - position) / WAVE_POSITION_REF, 1.0))
            if position is not None
            else 0.0
        ),
        "W3_stabilize": (
            max(0.0, 1.0 - low_days / WAVE_LOW_FULL_DAYS) if low_days is not None else 0.0
        ),
        "W4_volume": _volume_bonus(_sample_float(features.get("vol_spearman_5d"))),
    }
    total = round(sum(subs.values()), 4)
    return {"qualified": qualified, "score": total if qualified else 0.0, "raw": total, "subs": subs}


def _fused_score(
    features: Mapping[str, object],
    *,
    bear_gate: int = BEAR_RUN_GATE_MIN,
    conv_cap: int = CONV_FULL_DAYS,
) -> dict[str, object]:
    """融合分：max(低位分/7, 波浪分/4) 归一 0-1 + 类型标签。"""

    low = _lowpos_score(features, bear_gate=bear_gate, conv_cap=conv_cap)
    wave = _wave_score(features)
    low_norm = low["score"] / LOWPOS_SCORE_MAX
    wave_norm = wave["score"] / WAVE_SCORE_MAX
    fused = round(max(low_norm, wave_norm), 4)
    if low["qualified"] and wave["qualified"]:
        fused_type = "both"
    elif low["qualified"]:
        fused_type = "lowpos"
    elif wave["qualified"]:
        fused_type = "wave"
    else:
        fused_type = None
    return {
        "fused_score": fused,
        "fused_type": fused_type,
        "lowpos_score": low["score"],
        "wave_score": wave["score"],
        "lowpos_subs": low["subs"],
        "wave_subs": wave["subs"],
    }


def _score_bucket(score: float | None) -> str:
    """六桶：0（未入榜，score==0）/ [0,0.2) / [0.2,0.4) / [0.4,0.6) / [0.6,0.8) / [0.8,1.0]。"""

    value = score or 0.0
    if value <= 0:
        return "0(未入榜)"
    for index in range(len(SCORE_BUCKET_EDGES) - 1):
        low, high = SCORE_BUCKET_EDGES[index], SCORE_BUCKET_EDGES[index + 1]
        if low <= value < high:
            return f"{low:.1f}-{min(high, 1.0):.1f}"
    return "0.8-1.0"


SCORE_BUCKET_NAMES = ("0(未入榜)", "0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0")


# ── attach：因子样本追加结构/旅程特征 + 融合分（后处理，不重写样本抽取）────────


def attach_fused_scores(
    factor_samples: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    touch_dates_by_symbol: Mapping[str, AbstractSet[str]],
    *,
    purity_window: int = PURITY_LOOKBACK_BARS,
    bear_gate: int = BEAR_RUN_GATE_MIN,
    conv_cap: int = CONV_FULL_DAYS,
    score_suffix: str = "",
) -> list[dict[str, object]]:
    """给 build_factor_samples 的因子样本追加结构特征 + 旅程因子 + 融合分。

    子分扁平化为 ``lowpos_L1_depth`` 等顶层键（AUC/共线性工具直接可用）；
    ``score_suffix`` 供敏感性变体挂并列分键（如 fused_score@v2）。
    """

    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    dates_by_symbol: dict[str, list[str]] = {}
    for symbol, rows in bars_by_symbol.items():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
        dates_by_symbol[symbol] = [str(row.get("trade_date") or "") for row in rows]

    attached: list[dict[str, object]] = []
    for sample in factor_samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        rows = bars_by_symbol.get(symbol, [])
        dates = dates_by_symbol.get(symbol, [])
        d_index = bisect_left(dates, trade_date)
        bars_before = rows[:d_index]
        merged = dict(sample)
        merged.update(_structure_features(bars_before))
        merged.update(
            _journey_features(
                bars_before, touch_dates_by_symbol.get(symbol), purity_window=purity_window
            )
        )
        fused = _fused_score(merged, bear_gate=bear_gate, conv_cap=conv_cap)
        suffix = score_suffix
        merged[f"fused_score{suffix}"] = fused["fused_score"]
        merged[f"fused_type{suffix}"] = fused["fused_type"]
        merged[f"lowpos_score{suffix}"] = fused["lowpos_score"]
        merged[f"wave_score{suffix}"] = fused["wave_score"]
        if not suffix:
            for key, value in fused["lowpos_subs"].items():
                merged[f"lowpos_{key}"] = value
            for key, value in fused["wave_subs"].items():
                merged[f"wave_{key}"] = value
        attached.append(merged)
    return attached


# ── 对照组门槛（预声明；features-only 谓词）─────────────────────────────────


def _comparison_gates() -> tuple[tuple[str, Callable[[Mapping[str, object]], bool]], ...]:
    """子分单用对照门槛 + bias_ma20 动量对照（读表定「最强子分」，非事后搜索）。"""

    return (
        ("L4_stage>=1", lambda f: (_sample_float(f.get("cross_stage")) or 0) >= 1),
        ("L3_conv>=half", lambda f: (_sample_float(f.get("conv_days")) or 0) >= CONV_FULL_DAYS / 2),
        ("L2_bear_run>=15", lambda f: (_sample_float(f.get("bear_run_max_40d")) or 0) >= BEAR_RUN_GATE_MIN),
        ("L1_depth>=4pct", lambda f: (_sample_float(f.get("bear_depth_peak_pct")) or 0) >= DEPTH_FULL_PCT / 2),
        ("L5_above_ma10>=3", lambda f: (_sample_float(f.get("above_ma10_streak")) or 0) >= 3),
        ("L6_vol_trapezoid", lambda f: abs(_sample_float(f.get("vol_spearman_5d")) or 0) >= VOL_SPEARMAN_HALF),
        ("L7_recent_touch", lambda f: f.get("pure_20d") is False),
        ("W1_bull>=10", lambda f: (_sample_float(f.get("ma_bull_days")) or 0) >= BULL_RUN_FULL_DAYS / 2),
        ("W2_pos<=0.4", lambda f: (lambda v: v is not None and v <= 0.4)(_sample_float(f.get("position_20d")))),
        ("W3_low<=1", lambda f: (lambda v: v is not None and v <= 1)(_sample_float(f.get("days_since_20d_low")))),
        ("momentum_ref(bias20>=5)", lambda f: (_sample_float(f.get("bias_ma20_pct")) or 0) >= 5),
    )


# ── frame-1：区分度 / 分数桶结局 / 类型结局 / 漏网妖股 ───────────────────────


def _frame1_buckets(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """六桶 × ≥2板率/≥3板率（对照全样本基线）。"""

    grouped: dict[str, list[Mapping[str, object]]] = {name: [] for name in SCORE_BUCKET_NAMES}
    for sample in samples:
        grouped[_score_bucket(_sample_float(sample.get("fused_score")))].append(sample)
    rows = [{"bucket": "__baseline__", **_outcome_stats(samples)}]
    for name in SCORE_BUCKET_NAMES:
        rows.append({"bucket": name, **_outcome_stats(grouped[name])})
    return rows


def _frame1_types(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """类型结局（lowpos/wave/both/未入榜 四组）。"""

    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample.get("fused_type") or "none")].append(sample)
    rows = [{"type": "__baseline__", **_outcome_stats(samples)}]
    for name in ("lowpos", "wave", "both", "none"):
        rows.append({"type": name, **_outcome_stats(grouped.get(name, []))})
    return rows


def _missed_peak3_rows(
    samples: Sequence[Mapping[str, object]], names: Mapping[str, str]
) -> list[dict[str, object]]:
    """score=0 的 ≥3 板漏网妖股清单（哪种基底都没有，按日期倒序 top N）。"""

    missed = [
        sample
        for sample in samples
        if (_number(sample.get("eventual_peak")) or 0) >= 3
        and (_sample_float(sample.get("fused_score")) or 0) <= 0
    ]
    missed.sort(key=lambda sample: str(sample.get("trade_date") or ""), reverse=True)
    return [
        {
            "vt_symbol": sample.get("vt_symbol"),
            "name": names.get(str(sample.get("vt_symbol") or ""), ""),
            "trade_date": sample.get("trade_date"),
            "eventual_peak": sample.get("eventual_peak"),
            "bear_run_max_40d": sample.get("bear_run_max_40d"),
            "ma_bull_align": sample.get("ma_bull_align"),
            "cross_stage": sample.get("cross_stage"),
            "bias_ma20_pct": sample.get("bias_ma20_pct"),
        }
        for sample in missed[:MISSED_PEAK3_LIST_MAX]
    ]


def _frame1_analysis(
    samples: Sequence[Mapping[str, object]], names: Mapping[str, str]
) -> dict[str, object]:
    """frame-1 全分析：AUC 对照 + 分数桶/类型结局 + 月度一致性 + 漏网妖股。"""

    auc_rows = [compare_numeric_factor(samples, key) for key in FRAME1_AUC_KEYS]
    qualified = [
        sample for sample in samples if (_sample_float(sample.get("fused_score")) or 0) > 0
    ]
    auc_qualified = (
        compare_numeric_factor(qualified, "fused_score") if len(qualified) >= 50 else None
    )
    monthly = monthly_factor_stability(samples, "fused_score")
    return {
        "qualified_count": len(qualified),
        "qualified_share": round(len(qualified) / len(samples), 4) if samples else None,
        "auc_rows": auc_rows,
        "auc_qualified_only": auc_qualified,
        "bucket_outcomes": _frame1_buckets(samples),
        "type_outcomes": _frame1_types(samples),
        "monthly": monthly,
        "june_july": _june_july_check([monthly]),
        "missed_peak3": _missed_peak3_rows(samples, names),
    }


# ── frame-2：全市场股票日（分数桶直方图 + Top-N + 底线 + 月度 + regime + 对照）──

_HISTOGRAM_BINS = 100


def _new_bin() -> dict[str, int]:
    return {"days": 0, "board": 0, "leader": 0, "peak3": 0}


def _new_histogram() -> list[dict[str, int]]:
    return [_new_bin() for _ in range(_HISTOGRAM_BINS)]


def _histogram_add(histogram: list[dict[str, int]], score: float, label: int) -> None:
    bin_index = min(int(score * _HISTOGRAM_BINS), _HISTOGRAM_BINS - 1)
    cell = histogram[bin_index]
    cell["days"] += 1
    if label >= 1:
        cell["board"] += 1
    if label >= 2:
        cell["leader"] += 1
    if label >= 3:
        cell["peak3"] += 1


def _tally_add(tally: dict[str, int], label: int) -> None:
    tally["days"] += 1
    if label >= 1:
        tally["board"] += 1
    if label >= 2:
        tally["leader"] += 1
    if label >= 3:
        tally["peak3"] += 1


def _histogram_range(histogram: list[dict[str, int]], low_bin: int, high_bin: int) -> dict[str, int]:
    out = _new_bin()
    for cell in histogram[low_bin:high_bin]:
        for key in out:
            out[key] += cell[key]
    return out


def _bucket_row(
    name: str, tally: Mapping[str, int], baseline_rate: float | None, total_labels: Mapping[str, int]
) -> dict[str, object]:
    days = tally["days"]
    rate = tally["board"] / days if days else None
    return {
        "bucket": name,
        "days": days,
        "board": tally["board"],
        "board_rate": round(rate, 4) if rate is not None else None,
        "lift": round(rate / baseline_rate, 4) if rate is not None and baseline_rate else None,
        "leader": tally["leader"],
        "leader_recall": (
            round(tally["leader"] / total_labels["leader"], 4) if total_labels["leader"] else None
        ),
        "peak3": tally["peak3"],
        "peak3_recall": (
            round(tally["peak3"] / total_labels["peak3"], 4) if total_labels["peak3"] else None
        ),
    }


def build_fused_frame(
    daily_bars: Sequence[Mapping[str, object]],
    first_board_index: Mapping[tuple[str, str], object],
    names: Mapping[str, str],
    calendar: Sequence[str],
    *,
    touch_dates_by_symbol: Mapping[str, AbstractSet[str]],
    bear_gate: int = BEAR_RUN_GATE_MIN,
    conv_cap: int = CONV_FULL_DAYS,
    forward_days: int = PREMARKET_FORWARD_DAYS,
    min_history: int = PREMARKET_MIN_HISTORY,
) -> dict[str, object]:
    """全市场主板股票日扫描：融合分六桶首板率/单调性/Top-N/最低分底线/月度/regime/对照。

    标签与 frame 1 同一首板事件集（wave 口径）；5 个个股交易日观察窗跨市场日
    不得超 PREMARKET_LABEL_MAX_MARKET_SPAN，且不得越过事件末端（否则 label_invalid）。
    分数用 1% 分辨率直方图累计（桶/底线/月度全部从直方图派生，不存逐行大数组）；
    Top-N 需要逐日行，单独累积 day_rows（仅 score>0 入榜行）。
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

    totals = _new_bin()
    hist_all = _new_histogram()
    hist_by_type = {key: _new_histogram() for key in ("lowpos", "wave", "both")}
    hist_by_regime = {key: _new_histogram() for key in ("above", "below")}
    hist_by_month: dict[str, list[dict[str, int]]] = defaultdict(_new_histogram)
    zero_all = _new_bin()
    zero_by_regime = {"above": _new_bin(), "below": _new_bin()}
    zero_by_month: dict[str, dict[str, int]] = defaultdict(_new_bin)
    comparison_tallies: dict[str, dict[str, int]] = {
        name: _new_bin() for name, _ in _comparison_gates()
    }
    day_rows: dict[str, list[tuple[float, str, int]]] = defaultdict(list)
    scanned_market_days: set[str] = set()
    eligible_symbols = 0
    invalid_labels = 0

    for symbol, rows in sorted(bars_by_symbol.items()):
        if not is_eligible_main_board(symbol, names.get(symbol, "")):
            continue
        eligible_symbols += 1
        dates = [str(row.get("trade_date") or "") for row in rows]
        symbol_touches = touch_dates_by_symbol.get(symbol)
        for index in range(min_history - 1, len(rows)):
            day = dates[index]
            if day > tail_cutoff:
                break
            bars_slice = rows[max(0, index + 1 - PREMARKET_BAR_SLICE) : index + 1]
            if not _is_first_board_candidate(bars_slice):
                continue
            # 标签：未来 forward_days 个个股交易日内是否出现首板（同老框架口径）
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
            label = 0
            if hit_peak is not None:
                label = 1 if hit_peak < 2 else (2 if hit_peak < 3 else 3)
            _tally_add(totals, label)

            features = _structure_features(bars_slice)
            features.update(_journey_features(bars_slice, symbol_touches))
            fused = _fused_score(features, bear_gate=bear_gate, conv_cap=conv_cap)
            score = float(fused["fused_score"])
            fused_type = fused["fused_type"]
            month = day[:7]
            regime = _index_regime_at(index_dates, index_regime, day)
            regime_key = "above" if regime is True else ("below" if regime is False else "")

            if score <= 0:
                _tally_add(zero_all, label)
                _tally_add(zero_by_month[month], label)
                if regime_key:
                    _tally_add(zero_by_regime[regime_key], label)
            else:
                _histogram_add(hist_all, score, label)
                if fused_type in hist_by_type:
                    _histogram_add(hist_by_type[fused_type], score, label)
                if regime_key:
                    _histogram_add(hist_by_regime[regime_key], score, label)
                _histogram_add(hist_by_month[month], score, label)
                day_rows[day].append((score, symbol, label))

            for gate_name, gate_pred in _comparison_gates():
                if gate_pred(features):
                    _tally_add(comparison_tallies[gate_name], label)

    qualified_days = totals["days"] - zero_all["days"]
    baseline_rate = totals["board"] / totals["days"] if totals["days"] else None

    # 六桶（0 桶=精确零分；后五桶从直方图 20 格宽聚合）
    bucket_rows = [
        _bucket_row("0(未入榜)", zero_all, baseline_rate, totals),
    ]
    for index in range(len(SCORE_BUCKET_EDGES) - 1):
        low_bin = index * 20
        tally = _histogram_range(hist_all, low_bin, low_bin + 20)
        name = f"{SCORE_BUCKET_EDGES[index]:.1f}-{min(SCORE_BUCKET_EDGES[index + 1], 1.0):.1f}"
        bucket_rows.append(_bucket_row(name, tally, baseline_rate, totals))

    # 单调性：六桶首板率与桶序的 spearman（空桶率记 None 则整条 None，如实报）
    bucket_rates = [row["board_rate"] for row in bucket_rows]
    monotonicity = (
        round(_spearman_pairs([float(rate) for rate in bucket_rates], [1.0, 2, 3, 4, 5, 6]), 4)
        if all(rate is not None for rate in bucket_rates)
        else None
    )

    # 分类型六桶（0 桶=未入榜行没有类型，只报五个正分桶）
    type_bucket_rows: dict[str, list[dict[str, object]]] = {}
    for type_name, histogram in hist_by_type.items():
        rows_out = []
        for index in range(len(SCORE_BUCKET_EDGES) - 1):
            low_bin = index * 20
            tally = _histogram_range(histogram, low_bin, low_bin + 20)
            name = f"{SCORE_BUCKET_EDGES[index]:.1f}-{min(SCORE_BUCKET_EDGES[index + 1], 1.0):.1f}"
            rows_out.append(_bucket_row(name, tally, baseline_rate, totals))
        type_bucket_rows[type_name] = rows_out

    # Top-N 榜（同分按代码升序，确定性；每日榜单只排序一次）
    for rows_today in day_rows.values():
        rows_today.sort(key=lambda item: (-item[0], item[1]))
    topn_rows: list[dict[str, object]] = []
    for n in TOP_N_LIST:
        candidates = 0
        hits = 0
        leaders = 0
        peak3s = 0
        days_with_list = 0
        for day in scanned_market_days:
            rows_today = day_rows.get(day)
            if not rows_today:
                continue
            top = rows_today[:n]
            days_with_list += 1
            candidates += len(top)
            hits += sum(1 for item in top if item[2] >= 1)
            leaders += sum(1 for item in top if item[2] >= 2)
            peak3s += sum(1 for item in top if item[2] >= 3)
        topn_rows.append(
            {
                "n": n,
                "days_with_candidates": days_with_list,
                "avg_candidates_per_day": (
                    round(candidates / days_with_list, 2) if days_with_list else None
                ),
                "boards_captured": hits,
                "board_recall": round(hits / totals["board"], 4) if totals["board"] else None,
                "hit_rate": round(hits / candidates, 4) if candidates else None,
                "leader_recall": round(leaders / totals["leader"], 4) if totals["leader"] else None,
                "peak3_recall": round(peak3s / totals["peak3"], 4) if totals["peak3"] else None,
            }
        )

    # 最低分底线：细阈值扫描 lift 跨档（0 分行不进底线统计——底线只约束入榜票）
    lift_curve: list[dict[str, object]] = []
    step_count = int(round((1.0 - FLOOR_STEP) / FLOOR_STEP)) + 1
    for step in range(1, step_count):
        threshold = round(step * FLOOR_STEP, 2)
        low_bin = int(round(threshold * _HISTOGRAM_BINS))
        tally = _histogram_range(hist_all, low_bin, _HISTOGRAM_BINS)
        rate = tally["board"] / tally["days"] if tally["days"] else None
        lift_curve.append(
            {
                "min_score": threshold,
                "days": tally["days"],
                "board_rate": round(rate, 4) if rate is not None else None,
                "lift": (
                    round(rate / baseline_rate, 4) if rate is not None and baseline_rate else None
                ),
            }
        )
    floor_rows = []
    for target in FLOOR_LIFT_TARGETS:
        crossing = next(
            (row for row in lift_curve if row["lift"] is not None and row["lift"] >= target),
            None,
        )
        floor_rows.append(
            {
                "lift_target": target,
                "min_score": crossing["min_score"] if crossing else None,
                "days": crossing["days"] if crossing else None,
            }
        )

    # 月度一致性：顶桶（>=0.6）逐月首板率 vs 当月基线方向一致率（MA20 教训）
    full_top = _histogram_range(hist_all, int(TOP_BUCKET_MIN_SCORE * 100), _HISTOGRAM_BINS)
    full_top_rate = full_top["board"] / full_top["days"] if full_top["days"] else None
    full_direction = (
        "higher" if full_top_rate is not None and baseline_rate and full_top_rate > baseline_rate else "lower"
    )
    monthly_rows = []
    agree = 0
    valid = 0
    for month in sorted(set(list(hist_by_month) + list(zero_by_month))):
        month_total = _new_bin()
        month_top = _histogram_range(
            hist_by_month.get(month, _new_histogram()),
            int(TOP_BUCKET_MIN_SCORE * 100),
            _HISTOGRAM_BINS,
        )
        zero_month = zero_by_month.get(month, _new_bin())
        for key in month_total:
            month_total[key] = zero_month[key] + sum(
                cell[key] for cell in hist_by_month.get(month, [])
            )
        month_base = month_total["board"] / month_total["days"] if month_total["days"] else None
        top_rate = month_top["board"] / month_top["days"] if month_top["days"] else None
        if month_top["days"] < MIN_MONTH_TOP_DAYS or top_rate is None or month_base is None:
            monthly_rows.append(
                {
                    "month": month,
                    "top_days": month_top["days"],
                    "top_rate": None,
                    "month_baseline": round(month_base, 4) if month_base is not None else None,
                    "direction": "skip",
                }
            )
            continue
        direction = "higher" if top_rate > month_base else "lower"
        valid += 1
        if direction == full_direction:
            agree += 1
        monthly_rows.append(
            {
                "month": month,
                "top_days": month_top["days"],
                "top_rate": round(top_rate, 4),
                "month_baseline": round(month_base, 4),
                "direction": direction,
            }
        )
    june_july_frame2 = {
        "june_direction": next(
            (row["direction"] for row in monthly_rows if row["month"] == "2026-06"), "skip"
        ),
        "july_direction": next(
            (row["direction"] for row in monthly_rows if row["month"] == "2026-07"), "skip"
        ),
    }
    june_july_frame2["flipped"] = (
        june_july_frame2["june_direction"] not in ("skip",)
        and june_july_frame2["july_direction"] not in ("skip",)
        and june_july_frame2["june_direction"] != june_july_frame2["july_direction"]
    )

    # regime 拆分（描述性，单 episode）
    regime_rows: dict[str, list[dict[str, object]]] = {}
    for regime_name, histogram in hist_by_regime.items():
        regime_total = _new_bin()
        zero_regime = zero_by_regime[regime_name]
        for key in regime_total:
            regime_total[key] = zero_regime[key] + sum(cell[key] for cell in histogram)
        regime_base = regime_total["board"] / regime_total["days"] if regime_total["days"] else None
        rows_out = [_bucket_row("0(未入榜)", zero_regime, regime_base, regime_total)]
        for index in range(len(SCORE_BUCKET_EDGES) - 1):
            low_bin = index * 20
            tally = _histogram_range(histogram, low_bin, low_bin + 20)
            name = f"{SCORE_BUCKET_EDGES[index]:.1f}-{min(SCORE_BUCKET_EDGES[index + 1], 1.0):.1f}"
            rows_out.append(_bucket_row(name, tally, regime_base, regime_total))
        regime_rows[regime_name] = rows_out

    # 对照组（子分单用 + 动量对照）
    comparison_rows = [
        {
            "gate": name,
            **_bucket_row(name, tally, baseline_rate, totals),
        }
        for name, tally in comparison_tallies.items()
    ]

    return {
        "eligible_symbols": eligible_symbols,
        "scanned_days": totals["days"],
        "scanned_market_days": len(scanned_market_days),
        "invalid_labels": invalid_labels,
        "qualified_days": qualified_days,
        "avg_qualified_per_day": (
            round(qualified_days / len(scanned_market_days), 2) if scanned_market_days else None
        ),
        "qualified_share": round(qualified_days / totals["days"], 4) if totals["days"] else None,
        "totals": dict(totals),
        "baseline_board_rate": round(baseline_rate, 4) if baseline_rate is not None else None,
        "buckets": bucket_rows,
        "bucket_monotonicity_spearman": monotonicity,
        "type_buckets": type_bucket_rows,
        "topn": topn_rows,
        "lift_curve": lift_curve,
        "floors": floor_rows,
        "monthly": {
            "full_top_days": full_top["days"],
            "full_top_rate": round(full_top_rate, 4) if full_top_rate is not None else None,
            "full_direction": full_direction,
            "valid_months": valid,
            "monthly_agreement": round(agree / valid, 4) if valid else None,
            "june_july": june_july_frame2,
            "months": monthly_rows,
        },
        "regime": regime_rows,
        "comparisons": comparison_rows,
    }


# ── 敏感性（frame-1，预声明档位）────────────────────────────────────────────


def _sensitivity_rows(
    factor_samples: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    touch_dates_by_symbol: Mapping[str, AbstractSet[str]],
) -> list[dict[str, object]]:
    """预声明档位的 frame-1 敏感性：空头门/纯度窗/收敛封顶（不网格搜索）。

    空头门/收敛封顶是计分参数（重打分即可，O(n)）；纯度窗是旅程参数
    （需重算 _journey_features，11k 样本成本可接受）。frame-2 变体成本高，
    中央变体达标后再补（notes 已声明）。
    """

    rows: list[dict[str, object]] = []

    def _variant_stats(label: str, attached: list[dict[str, object]], key: str) -> None:
        top = [
            sample
            for sample in attached
            if (_sample_float(sample.get(key)) or 0) >= TOP_BUCKET_MIN_SCORE
        ]
        report = compare_numeric_factor(attached, key)
        rows.append(
            {
                "variant": label,
                "top_share": round(len(top) / len(attached), 4) if attached else None,
                "top_leader_rate": (
                    round(
                        sum(1 for sample in top if _bool(sample.get("is_leader"))) / len(top), 4
                    )
                    if top
                    else None
                ),
                "auc": report.get("auc"),
            }
        )

    base = attach_fused_scores(factor_samples, daily_bars, touch_dates_by_symbol)
    _variant_stats(f"bear_gate={BEAR_RUN_GATE_MIN}(中央)", base, "fused_score")
    for gate in SENSITIVITY_BEAR_GATES:
        if gate == BEAR_RUN_GATE_MIN:
            continue
        variant = attach_fused_scores(
            factor_samples, daily_bars, touch_dates_by_symbol, bear_gate=gate, score_suffix="@v"
        )
        _variant_stats(f"bear_gate={gate}", variant, "fused_score@v")
    for window in SENSITIVITY_PURITY_WINDOWS:
        if window == PURITY_LOOKBACK_BARS:
            continue
        variant = attach_fused_scores(
            factor_samples,
            daily_bars,
            touch_dates_by_symbol,
            purity_window=window,
            score_suffix="@v",
        )
        _variant_stats(f"purity_window={window}", variant, "fused_score@v")
    for cap in SENSITIVITY_CONV_CAPS:
        if cap == CONV_FULL_DAYS:
            continue
        variant = attach_fused_scores(
            factor_samples, daily_bars, touch_dates_by_symbol, conv_cap=cap, score_suffix="@v"
        )
        _variant_stats(f"conv_cap={cap}", variant, "fused_score@v")
    return rows


# ── 最终裁决（预声明及格线，读已计算的报告块）────────────────────────────────


def _final_verdicts(report: Mapping[str, object]) -> dict[str, object]:
    """融合成立的四条预声明及格线 + 总裁决。"""

    frame2 = report.get("frame2") or {}
    mono = frame2.get("bucket_monotonicity_spearman")
    buckets = frame2.get("buckets") or []
    top_bucket = buckets[-1] if buckets else {}
    comparisons = frame2.get("comparisons") or []
    subscore_gates = [row for row in comparisons if not str(row.get("gate", "")).startswith("momentum_ref")]
    best_sub = max(
        subscore_gates, key=lambda row: row.get("leader_recall") or 0.0, default=None
    )
    monthly = frame2.get("monthly") or {}
    june_july = monthly.get("june_july") or {}

    criteria = [
        {
            "criterion": f"六桶首板率单调性 spearman>={PASS_MONO_SPEARMAN}",
            "value": mono,
            "passed": mono is not None and mono >= PASS_MONO_SPEARMAN,
        },
        {
            "criterion": f"顶桶(0.8-1.0) lift>={PASS_TOP_LIFT} 且候选日>={PASS_TOP_MIN_DAYS}",
            "value": {
                "lift": top_bucket.get("lift"),
                "days": top_bucket.get("days"),
            },
            "passed": (
                top_bucket.get("lift") is not None
                and top_bucket["lift"] >= PASS_TOP_LIFT
                and (top_bucket.get("days") or 0) >= PASS_TOP_MIN_DAYS
            ),
        },
        {
            "criterion": "顶桶 ≥2板召回 > 最强子分单用召回",
            "value": {
                "top_recall": top_bucket.get("leader_recall"),
                "best_sub_gate": (best_sub or {}).get("gate"),
                "best_sub_recall": (best_sub or {}).get("leader_recall"),
            },
            "passed": (
                top_bucket.get("leader_recall") is not None
                and best_sub is not None
                and (best_sub.get("leader_recall") or 0) < (top_bucket.get("leader_recall") or 0)
            ),
        },
        {
            "criterion": f"顶桶月度一致率>={PASS_MONTHLY_AGREEMENT} 且 2026-06/07 不翻转",
            "value": {
                "agreement": monthly.get("monthly_agreement"),
                "june_july": june_july,
            },
            "passed": (
                monthly.get("monthly_agreement") is not None
                and monthly["monthly_agreement"] >= PASS_MONTHLY_AGREEMENT
                and not june_july.get("flipped")
            ),
        },
    ]
    passed_count = sum(1 for row in criteria if row["passed"])
    return {
        "criteria": criteria,
        "passed_count": passed_count,
        "overall": "融合成立（进排序级+观察池候选）" if passed_count == len(criteria) else "融合未达标",
        "overall_passed": passed_count == len(criteria),
    }


# ── 报告编排 ──────────────────────────────────────────────────────────────


def build_fused_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
    names: Mapping[str, str],
    *,
    purity_events: Sequence[Mapping[str, object]],
    min_consecutive_boards: int = 2,
    board_gap_mode: str = "wave",
    forward_days: int = PREMARKET_FORWARD_DAYS,
    min_history: int = PREMARKET_MIN_HISTORY,
) -> dict[str, object]:
    """编排融合计分卡研究（纯函数，不连数据库）。"""

    _, factor_samples = build_factor_samples(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    touch_by_symbol = _touch_dates_by_symbol(purity_events)
    samples = attach_fused_scores(factor_samples, daily_bars, touch_by_symbol)
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

    positive = sum(1 for sample in samples if _bool(sample.get("is_leader")))
    peak3 = sum(1 for sample in samples if (_number(sample.get("eventual_peak")) or 0) >= 3)
    report: dict[str, object] = {
        "status": "ok" if samples else "insufficient_data",
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "board_gap_mode": board_gap_mode,
        "thresholds": {
            "journey_window_days": JOURNEY_WINDOW_DAYS,
            "bear_gate": BEAR_RUN_GATE_MIN,
            "depth_full_pct": DEPTH_FULL_PCT,
            "bear_run_full_days": BEAR_RUN_FULL_DAYS,
            "conv_full_days": CONV_FULL_DAYS,
            "converge_half_ratio": CONVERGE_HALF_RATIO,
            "above_ma10_full_days": ABOVE_MA10_FULL_DAYS,
            "purity_lookback_bars": PURITY_LOOKBACK_BARS,
            "vol_spearman_full": VOL_SPEARMAN_FULL,
            "vol_spearman_half": VOL_SPEARMAN_HALF,
            "bull_run_full_days": BULL_RUN_FULL_DAYS,
            "wave_position_ref": WAVE_POSITION_REF,
            "wave_low_full_days": WAVE_LOW_FULL_DAYS,
            "top_bucket_min_score": TOP_BUCKET_MIN_SCORE,
        },
        "pass_bar": {
            "mono_spearman": PASS_MONO_SPEARMAN,
            "top_lift": PASS_TOP_LIFT,
            "top_min_days": PASS_TOP_MIN_DAYS,
            "monthly_agreement": PASS_MONTHLY_AGREEMENT,
        },
        "first_board_count": len(samples),
        "label_balance": {
            "positive": positive,
            "negative": len(samples) - positive,
            "positive_rate": round(positive / len(samples), 4) if samples else None,
            "peak3": peak3,
            "peak3_rate": round(peak3 / len(samples), 4) if samples else None,
        },
        "frame1": _frame1_analysis(samples, names),
        "frame2": build_fused_frame(
            daily_bars,
            first_board_index,
            names,
            calendar,
            touch_dates_by_symbol=touch_by_symbol,
            forward_days=forward_days,
            min_history=min_history,
        ),
        "sensitivity": _sensitivity_rows(factor_samples, daily_bars, touch_by_symbol),
        "notes": list(_RESEARCH_NOTES),
    }
    report["final_verdicts"] = _final_verdicts(report)
    return report


def run_research(*, start: date, end: date) -> dict[str, object]:
    """加载冻结数据集并返回融合计分卡研究报告（纯度事件前向多加载 45 自然日）。"""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    purity_dataset = load_limit_up_dataset(start - timedelta(days=PURITY_EVENTS_EXTRA_DAYS), end)
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
    report = build_fused_report(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        names,
        purity_events=purity_dataset["events"],
    )
    coverage = dict(dataset.get("coverage") or {})
    coverage["trade_days_in_window"] = len(calendar)
    coverage["purity_events_extra_days"] = PURITY_EVENTS_EXTRA_DAYS
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
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _icon(passed: object) -> str:
    return "✅" if passed else "❌"


def render_markdown(result: Mapping[str, object]) -> str:
    """渲染融合计分卡研究报告。"""

    lines: list[str] = []
    lines.append("# 首板融合计分卡研究（低位分+波浪分 → Top-N 榜 + 最低分底线）")
    lines.append("")
    lines.append("## Boundary")
    lines.append("")
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## 模型说明（计分卡公式，等权预声明）")
    lines.append("")
    lines.append("- 低位分（0-7）：资格门 bear_run_max_40d≥15；L1 基底深度/8%、L2 基底时长/30、"
                 "L3 收敛时长/15、L4 穿越阶段/2、L5 企稳/5、L6 量能梯形加分、L7 近期触碰加分（v2 反向）。")
    lines.append("- 波浪分（0-4）：资格门向上波浪（多头排列）或横盘波浪（缠绕+回前低，v2）；"
                 "W1 多头时长/20、W2 回调深度（参照0.8）、W3 企稳（/3 衰减）、W4 量能加分。")
    lines.append("- 融合分 = max(低位分/7, 波浪分/4)（0-1），类型 lowpos/wave/both；Top-N 同分按代码升序。")
    lines.append("")

    lines.append("## Sample Balance")
    lines.append("")
    balance = result.get("label_balance") or {}
    lines.append("| 首板样本 | ≥2板 | 基线 | ≥3板妖股 | 妖股率 |")
    lines.append("|---:|---:|---:|---:|---:|")
    lines.append(
        f"| {result.get('first_board_count')} | {balance.get('positive')} | "
        f"{_pct(balance.get('positive_rate'))} | {balance.get('peak3')} | {_pct(balance.get('peak3_rate'))} |"
    )
    lines.append("")

    frame1 = result.get("frame1") or {}
    lines.append("## ① Frame-1 区分度（≥2 板标签 AUC；融合分 vs 子分 vs bias_ma20）")
    lines.append("")
    lines.append(f"- 入榜样本：{frame1.get('qualified_count')}/{result.get('first_board_count')}"
                 f"（{_pct(frame1.get('qualified_share'))}）")
    qualified_auc = frame1.get("auc_qualified_only") or {}
    lines.append(f"- 仅入榜样本的融合分 AUC：{_fmt(qualified_auc.get('auc'))}")
    lines.append("")
    lines.append("| 因子 | 样本 | 正均值 | 负均值 | AUC | 方向 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for row in frame1.get("auc_rows") or []:
        lines.append(
            f"| {row.get('factor_key')} | {row.get('sample_count')} | "
            f"{_fmt(row.get('positive_mean'))} | {_fmt(row.get('negative_mean'))} | "
            f"{_fmt(row.get('auc'))} | {row.get('direction') or '-'} |"
        )
    lines.append("")

    lines.append("## ② Frame-1 分数桶结局 + 类型结局")
    lines.append("")
    lines.append("| 桶 | 样本 | ≥2板率 | ≥3板率 |")
    lines.append("|---|---:|---:|---:|")
    for row in frame1.get("bucket_outcomes") or []:
        lines.append(
            f"| {row.get('bucket')} | {row.get('total')} | "
            f"{_pct(row.get('leader_rate'))} | {_pct(row.get('leader3_rate'))} |"
        )
    lines.append("")
    lines.append("| 类型 | 样本 | ≥2板率 | ≥3板率 |")
    lines.append("|---|---:|---:|---:|")
    for row in frame1.get("type_outcomes") or []:
        lines.append(
            f"| {row.get('type')} | {row.get('total')} | "
            f"{_pct(row.get('leader_rate'))} | {_pct(row.get('leader3_rate'))} |"
        )
    lines.append("")

    lines.append("## ③ 漏网妖股（score=0 的 ≥3 板票，按日期倒序 top 50）")
    lines.append("")
    lines.append("| 代码 | 名称 | 首板日 | 峰值 | 最长空头 | 多头 | 阶段 | bias_ma20 |")
    lines.append("|---|---|---|---:|---:|---|---:|---:|")
    for row in frame1.get("missed_peak3") or []:
        lines.append(
            f"| {row.get('vt_symbol')} | {row.get('name')} | {row.get('trade_date')} | "
            f"{row.get('eventual_peak')} | {_fmt(row.get('bear_run_max_40d'))} | "
            f"{row.get('ma_bull_align')} | {_fmt(row.get('cross_stage'))} | {_fmt(row.get('bias_ma20_pct'))} |"
        )
    lines.append("")

    frame2 = result.get("frame2") or {}
    lines.append("## ④ Frame-2 分数桶 × 5日首板率（全市场盘前框架）")
    lines.append("")
    lines.append(
        f"- 扫描股票日 {frame2.get('scanned_days')}（{frame2.get('scanned_market_days')} 个交易日"
        f" × {frame2.get('eligible_symbols')} 票），基线 5 日首板率 {_pct(frame2.get('baseline_board_rate'))}；"
        f"入榜股票日 {frame2.get('qualified_days')}（占比 {_pct(frame2.get('qualified_share'))}，"
        f"日均 {frame2.get('avg_qualified_per_day')} 只）；label_invalid {frame2.get('invalid_labels')}"
    )
    lines.append(f"- **六桶单调性 spearman：{_fmt(frame2.get('bucket_monotonicity_spearman'))}**"
                 f"（及格线 ≥{PASS_MONO_SPEARMAN}）")
    lines.append("")
    lines.append("| 桶 | 股票日 | 首板 | 首板率 | lift | ≥2板召回 | ≥3板召回 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for row in frame2.get("buckets") or []:
        lines.append(
            f"| {row.get('bucket')} | {row.get('days')} | {row.get('board')} | "
            f"{_pct(row.get('board_rate'))} | {_fmt(row.get('lift'))} | "
            f"{_pct(row.get('leader_recall'))} | {_pct(row.get('peak3_recall'))} |"
        )
    lines.append("")
    for type_name, rows in (frame2.get("type_buckets") or {}).items():
        lines.append(f"### 分类型：{type_name}")
        lines.append("")
        lines.append("| 桶 | 股票日 | 首板率 | lift | ≥2板召回 |")
        lines.append("|---|---:|---:|---:|---:|")
        for row in rows:
            lines.append(
                f"| {row.get('bucket')} | {row.get('days')} | {_pct(row.get('board_rate'))} | "
                f"{_fmt(row.get('lift'))} | {_pct(row.get('leader_recall'))} |"
            )
        lines.append("")

    lines.append("## ⑤ Top-N 榜（每日按融合分取前 N）")
    lines.append("")
    lines.append("| N | 有候选日 | 平均候选/日 | 命中首板 | 命中率 | 首板召回 | ≥2板召回 | ≥3板召回 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in frame2.get("topn") or []:
        lines.append(
            f"| {row.get('n')} | {row.get('days_with_candidates')} | {row.get('avg_candidates_per_day')} | "
            f"{row.get('boards_captured')} | {_pct(row.get('hit_rate'))} | "
            f"{_pct(row.get('board_recall'))} | {_pct(row.get('leader_recall'))} | {_pct(row.get('peak3_recall'))} |"
        )
    lines.append("")

    lines.append("## ⑥ 最低分底线（lift 跨档的最低分）")
    lines.append("")
    lines.append("| lift 门槛 | 最低分 | 股票日 |")
    lines.append("|---:|---:|---:|")
    for row in frame2.get("floors") or []:
        lines.append(f"| {row.get('lift_target')} | {_fmt(row.get('min_score'))} | {_fmt(row.get('days'))} |")
    lines.append("")
    lines.append("<details><summary>完整 lift 曲线（0.05 步长）</summary>")
    lines.append("")
    lines.append("| 最低分 | 股票日 | 首板率 | lift |")
    lines.append("|---:|---:|---:|---:|")
    for row in frame2.get("lift_curve") or []:
        lines.append(
            f"| {row.get('min_score')} | {row.get('days')} | "
            f"{_pct(row.get('board_rate'))} | {_fmt(row.get('lift'))} |"
        )
    lines.append("")
    lines.append("</details>")
    lines.append("")

    monthly = frame2.get("monthly") or {}
    june_july = monthly.get("june_july") or {}
    lines.append("## ⑦ 月度一致性（顶桶≥0.6 逐月首板率 vs 当月基线）")
    lines.append("")
    lines.append(
        f"- 顶桶全期首板率 {_pct(monthly.get('full_top_rate'))}（{monthly.get('full_top_days')} 股票日）；"
        f"月度一致率 **{_fmt(monthly.get('monthly_agreement'))}**（{monthly.get('valid_months')} 个有效月，"
        f"及格线 ≥{PASS_MONTHLY_AGREEMENT}）；2026-06 {june_july.get('june_direction')} / "
        f"2026-07 {june_july.get('july_direction')} → 翻转={june_july.get('flipped')}"
    )
    lines.append("")
    lines.append("| 月份 | 顶桶股票日 | 顶桶首板率 | 当月基线 | 方向 |")
    lines.append("|---|---:|---:|---:|---|")
    for row in monthly.get("months") or []:
        lines.append(
            f"| {row.get('month')} | {row.get('top_days')} | {_pct(row.get('top_rate'))} | "
            f"{_pct(row.get('month_baseline'))} | {row.get('direction')} |"
        )
    lines.append("")

    lines.append("## ⑧ Regime 拆分（上证 MA20 上/下；单 episode 描述性，不算验证）")
    lines.append("")
    for regime_name, rows in (frame2.get("regime") or {}).items():
        lines.append(f"### MA20 {regime_name}")
        lines.append("")
        lines.append("| 桶 | 股票日 | 首板率 | lift |")
        lines.append("|---|---:|---:|---:|")
        for row in rows:
            lines.append(
                f"| {row.get('bucket')} | {row.get('days')} | "
                f"{_pct(row.get('board_rate'))} | {_fmt(row.get('lift'))} |"
            )
        lines.append("")

    lines.append("## ⑨ 敏感性（frame-1，预声明档位）")
    lines.append("")
    lines.append("| 变体 | 顶桶(≥0.6)占比 | 顶桶≥2板率 | AUC |")
    lines.append("|---|---:|---:|---:|")
    for row in result.get("sensitivity") or []:
        lines.append(
            f"| {row.get('variant')} | {_pct(row.get('top_share'))} | "
            f"{_pct(row.get('top_leader_rate'))} | {_fmt(row.get('auc'))} |"
        )
    lines.append("")

    lines.append("## ⑩ 对照组（子分单用 + 动量对照；融合必须双赢才算融合成功）")
    lines.append("")
    lines.append("| 门槛 | 股票日 | 首板率 | lift | ≥2板召回 | ≥3板召回 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in frame2.get("comparisons") or []:
        lines.append(
            f"| {row.get('gate')} | {row.get('days')} | {_pct(row.get('board_rate'))} | "
            f"{_fmt(row.get('lift'))} | {_pct(row.get('leader_recall'))} | {_pct(row.get('peak3_recall'))} |"
        )
    lines.append("")

    verdicts = result.get("final_verdicts") or {}
    lines.append("## ⑪ 最终裁决（预声明及格线）")
    lines.append("")
    lines.append("| 及格线 | 实测 | 通过 |")
    lines.append("|---|---|---|")
    for row in verdicts.get("criteria") or []:
        lines.append(f"| {row.get('criterion')} | {row.get('value')} | {_icon(row.get('passed'))} |")
    lines.append("")
    lines.append(f"**总裁决：{verdicts.get('overall')}**（{verdicts.get('passed_count')}/4 条通过）")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(f"- study_version: {result.get('study_version')}")
    lines.append(f"- input_fingerprint: {result.get('input_fingerprint')}")
    coverage = result.get("coverage") or {}
    lines.append(f"- 窗口: {result.get('start')}..{result.get('end')}；coverage: {coverage}")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="首板融合计分卡研究（低位分+波浪分→Top-N+底线）")
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
    frame2 = report.get("frame2") or {}
    verdicts = report.get("final_verdicts") or {}
    print(
        f"fused score research: status={report['status']} "
        f"samples={report['first_board_count']} "
        f"positive_rate={balance.get('positive_rate')} "
        f"mono_spearman={frame2.get('bucket_monotonicity_spearman')} "
        f"verdict={verdicts.get('overall')} ({verdicts.get('passed_count')}/4)"
    )


if __name__ == "__main__":
    main()
