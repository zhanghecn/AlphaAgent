"""Strategy registry for AlphaAgent quant screening.

Keeping the dispatch explicit lets pullback, breakout, acceleration and future
strategies share the same screening and backtest orchestration code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from alphaagent.server.services.quant.factors import (
    BREAKOUT_STRATEGY_ID,
    BREAKOUT_STRATEGY_VERSION,
    DRAGON_PULLBACK_STRATEGY_ID,
    DRAGON_PULLBACK_STRATEGY_VERSION,
    LEADER_PULLBACK_STRATEGY_ID,
    LEADER_PULLBACK_STRATEGY_VERSION,
    LIMIT_UP_PULLBACK_STRATEGY_ID,
    LIMIT_UP_PULLBACK_STRATEGY_VERSION,
    STRATEGY_ID,
    STRATEGY_VERSION,
    TREND_ACCELERATION_STRATEGY_ID,
    TREND_ACCELERATION_STRATEGY_VERSION,
    Bar,
    SignalScore,
)
from alphaagent.server.services.quant.strategies.breakout import score_breakout_confirmation
from alphaagent.server.services.quant.strategies.dragon_pullback import score_dragon_pullback
from alphaagent.server.services.quant.strategies.limit_up_pullback import score_limit_up_after_pullback
from alphaagent.server.services.quant.strategies.pullback import score_stock
from alphaagent.server.services.quant.strategies.trend_acceleration import score_trend_acceleration


ScoreFunction = Callable[..., SignalScore]


@dataclass(frozen=True)
class QuantStrategy:
    id: str
    version: str
    name: str
    description: str
    default_min_entry_score: float
    entry_action_label: str
    watch_action_label: str
    failed_rule_labels: dict[str, str]
    evidence_labels: dict[str, str]
    primary_metric_keys: tuple[str, ...]
    score: ScoreFunction


MAINLINE_LEADER_PULLBACK = QuantStrategy(
    id=LEADER_PULLBACK_STRATEGY_ID,
    version=LEADER_PULLBACK_STRATEGY_VERSION,
    name="主线强势回踩低吸",
    description="使用日线可见数据寻找主线强势股在 MA5 附近回踩的低吸机会。",
    default_min_entry_score=68.0,
    entry_action_label="买入",
    watch_action_label="观察",
    failed_rule_labels={
        "total_score": "分数不足",
        "ma5_distance": "不在MA5低吸区",
        "risk_score": "风险分不足",
        "liquidity_score": "流动性不足",
    },
    evidence_labels={
        "ma5_distance_pct": "MA5距离",
        "risk_score": "风险分",
        "liquidity_score": "流动性",
    },
    primary_metric_keys=("ma5_distance_pct",),
    score=score_stock,
)

BREAKOUT_CONFIRMATION = QuantStrategy(
    id=BREAKOUT_STRATEGY_ID,
    version=BREAKOUT_STRATEGY_VERSION,
    name="平台放量突破确认",
    description="使用日线可见数据寻找接近 60 日新高、量能确认、趋势未破坏的突破机会。",
    default_min_entry_score=70.0,
    entry_action_label="买入",
    watch_action_label="观察",
    failed_rule_labels={
        "total_score": "分数不足",
        "breakout_distance": "未接近60日高点",
        "volume_confirmation": "量能确认不足",
        "trend_quality": "趋势质量不足",
        "risk_score": "风险分不足",
        "liquidity_score": "流动性不足",
    },
    evidence_labels={
        "close_to_prior_high_pct": "距60日高点",
        "volume_ratio_5d_20d": "量能比",
        "trend_quality_score": "趋势质量",
        "risk_score": "风险分",
        "liquidity_score": "流动性",
    },
    primary_metric_keys=("close_to_prior_high_pct", "volume_ratio_5d_20d"),
    score=score_breakout_confirmation,
)

MAINLINE_DRAGON_PULLBACK = QuantStrategy(
    id=DRAGON_PULLBACK_STRATEGY_ID,
    version=DRAGON_PULLBACK_STRATEGY_VERSION,
    name="主线龙回头回踩低吸",
    description="使用日线可见数据识别主线强势股第一波启动后的缩量回踩、均线承接和弱转强机会。",
    default_min_entry_score=76.0,
    entry_action_label="买入",
    watch_action_label="观察",
    failed_rule_labels={
        "total_score": "分数不足",
        "strong_leg": "第一波强度不足",
        "pullback_structure": "回踩结构不足",
        "pullback_too_short": "回踩时间不足",
        "pullback_too_late": "回踩时间过长",
        "support_acceptance": "均线承接不足",
        "reclaim_confirmation": "弱转强确认不足",
        "repeat_tail_buy_setup": "同一回踩结构重复信号",
        "weak_rebound_ma5_below_ma10": "MA5下穿MA10弱反抽",
        "distribution_risk": "高位派发风险",
        "pullback_too_deep": "回撤过深",
        "ma20_broken": "跌破MA20支撑",
        "overheat": "短期过热",
        "risk_score": "风险分不足",
        "liquidity_score": "流动性不足",
    },
    evidence_labels={
        "dragon_state": "龙回头状态",
        "support_type": "承接类型",
        "ma5_distance_pct": "MA5距离",
        "ma10_distance_pct": "MA10距离",
        "drawdown_from_pivot_pct": "距高点回撤",
        "pullback_days": "回踩天数",
        "volume_ratio_5d_20d": "量能比",
        "risk_score": "风险分",
        "liquidity_score": "流动性",
    },
    primary_metric_keys=("dragon_state", "support_type", "ma5_distance_pct"),
    score=score_dragon_pullback,
)

LIMIT_UP_AFTER_PULLBACK = QuantStrategy(
    id=LIMIT_UP_PULLBACK_STRATEGY_ID,
    version=LIMIT_UP_PULLBACK_STRATEGY_VERSION,
    name="涨停后回踩确认",
    description="使用日线可见数据寻找近 20 日有涨停、回踩 MA5/MA20 未破坏的强势股确认机会。",
    default_min_entry_score=72.0,
    entry_action_label="买入",
    watch_action_label="观察",
    failed_rule_labels={
        "total_score": "分数不足",
        "limit_up_presence": "近20日无涨停",
        "limit_up_recency": "涨停后时间不合适",
        "pullback_position": "回踩位置不合适",
        "ma20_support": "跌破MA20支撑",
        "trend_quality": "趋势质量不足",
        "risk_score": "风险分不足",
        "liquidity_score": "流动性不足",
    },
    evidence_labels={
        "days_since_limit_up": "距涨停天数",
        "limit_up_count_20d": "20日涨停数",
        "ma5_distance_pct": "MA5距离",
        "ma20_distance_pct": "MA20距离",
        "risk_score": "风险分",
        "liquidity_score": "流动性",
    },
    primary_metric_keys=("days_since_limit_up", "ma5_distance_pct"),
    score=score_limit_up_after_pullback,
)

TREND_ACCELERATION = QuantStrategy(
    id=TREND_ACCELERATION_STRATEGY_ID,
    version=TREND_ACCELERATION_STRATEGY_VERSION,
    name="趋势加速确认",
    description="使用日线可见数据寻找趋势已形成且正在温和加速、但尚未明显过热的强势股机会。",
    default_min_entry_score=73.0,
    entry_action_label="买入",
    watch_action_label="观察",
    failed_rule_labels={
        "total_score": "分数不足",
        "trend_return": "阶段强度不足",
        "recent_acceleration": "短期加速不合适",
        "ma_alignment": "均线多头不足",
        "ma5_position": "偏离MA5不合适",
        "ma20_position": "趋势位置不合适",
        "volume_acceleration": "量能加速不合适",
        "overheat": "短期过热",
        "trend_quality": "趋势质量不足",
        "risk_score": "风险分不足",
        "liquidity_score": "流动性不足",
    },
    evidence_labels={
        "return_5d": "5日涨跌",
        "return_20d": "20日涨跌",
        "return_60d": "60日涨跌",
        "ma5_distance_pct": "MA5距离",
        "ma20_distance_pct": "MA20距离",
        "volume_ratio_5d_20d": "量能比",
        "risk_score": "风险分",
        "liquidity_score": "流动性",
    },
    primary_metric_keys=("return_20d", "volume_ratio_5d_20d"),
    score=score_trend_acceleration,
)

_STRATEGIES: dict[str, QuantStrategy] = {
    MAINLINE_LEADER_PULLBACK.id: MAINLINE_LEADER_PULLBACK,
    MAINLINE_DRAGON_PULLBACK.id: MAINLINE_DRAGON_PULLBACK,
    BREAKOUT_CONFIRMATION.id: BREAKOUT_CONFIRMATION,
    LIMIT_UP_AFTER_PULLBACK.id: LIMIT_UP_AFTER_PULLBACK,
    TREND_ACCELERATION.id: TREND_ACCELERATION,
}

PUBLIC_STRATEGY_IDS = (DRAGON_PULLBACK_STRATEGY_ID,)


def get_strategy(strategy_id: str | None) -> QuantStrategy | None:
    """Return a registered strategy, or ``None`` when unsupported."""

    return _STRATEGIES.get(str(strategy_id or STRATEGY_ID).strip() or STRATEGY_ID)


def require_strategy(strategy_id: str | None) -> QuantStrategy:
    """Return a registered strategy or raise ``ValueError``."""

    strategy = get_strategy(strategy_id)
    if strategy is None:
        supported = ", ".join(sorted(_STRATEGIES))
        raise ValueError(f"Unsupported quant strategy: {strategy_id}; supported: {supported}")
    return strategy


def list_strategies(*, include_internal: bool = False) -> list[dict[str, object]]:
    """Return strategy metadata suitable for API/UI option lists."""

    strategy_ids = _STRATEGIES if include_internal else PUBLIC_STRATEGY_IDS
    return [
        _strategy_metadata(_STRATEGIES[strategy_id])
        for strategy_id in strategy_ids
        if strategy_id in _STRATEGIES
    ]


def list_internal_strategies() -> list[dict[str, object]]:
    """Return all registered strategies for compatibility tooling."""

    return list_strategies(include_internal=True)


def _strategy_metadata(strategy: QuantStrategy) -> dict[str, object]:
    return {
        "id": strategy.id,
        "version": strategy.version,
        "name": strategy.name,
        "description": strategy.description,
        "default_min_entry_score": strategy.default_min_entry_score,
        "entry_action_label": strategy.entry_action_label,
        "watch_action_label": strategy.watch_action_label,
        "failed_rule_labels": strategy.failed_rule_labels,
        "evidence_labels": strategy.evidence_labels,
        "primary_metric_keys": list(strategy.primary_metric_keys),
    }


def score_strategy(
    strategy_id: str | None,
    vt_symbol: str,
    bars: list[Bar],
    trade_date: date,
    **kwargs,
) -> SignalScore:
    """Score one stock with a registered strategy."""

    strategy = require_strategy(strategy_id)
    return strategy.score(vt_symbol, bars, trade_date, **kwargs)
