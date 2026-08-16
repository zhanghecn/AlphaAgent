"""低吸说明书案例：策展经典案例按规则归组 + 现算 D+N 远期收益。

数据源是研究层冻结的 ``PERSONAL_CASES``（22 条真实历史股票断言，含底盘叙事
起点与预期启动日），本模块把它们翻译成说明书前端可直接渲染的 payload：

- 归组：案例按 ``required_process_rule_keys`` 挂到 ``DISCOVERY_RULES`` 的规则
  节点下；没有 rule_key 的待验证案例（research_pending）进 ``orphan_cases``。
- 收益：按 ``stock_daily_bars`` 现算 D+1/D+3/D+5 收盘收益（session-indexed，
  停牌缺口自然跳过），与回测标签同源使用主板涨跌停链式检查——除权日跳变
  会被判为 ``raw_price_limit_outlier`` 并置空，不静默展示误导性收益。
- 诚实性：单票无数据只把该案例标记为 ``bars_unavailable`` 并整体降
  ``partial``，不拖垮整个端点。

本模块只有 ``load_guide_cases_payload`` 触及数据库，其余均为纯函数，便于测试。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope

from .daily_factor_comprehensive_study import PERSONAL_CASES, PersonalResearchCase
from .daily_factor_extended_discovery import (
    DISCOVERY_RULES,
    FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
    LIMIT_UP_PULLBACK_REBOUND_RULE_KEY,
    LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY,
    POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
    PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
    PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
    RESEARCH_THREE_MA_WRAP_RULE_KEY,
    STAGED_MA10_SUPPORT_RULE_KEY,
)
from .daily_factor_research import is_main_board_close_within_price_limit
from .daily_picks_scanner import PRODUCT_DISCOVERY_RULES, SETUP_TYPE_LABELS
from .daily_picks_scoring import SCORE_VERSION

GUIDE_RETURN_HORIZONS = (1, 3, 5)
# 收益查询窗口边界（日历日）：信号日前 10 天用于定位信号日，后 30 天覆盖
# D+5 个交易日 + 春节级长假。
_GUIDE_BARS_LOOKBACK_DAYS = 10
_GUIDE_BARS_FORWARD_DAYS = 30

# 收益状态：available / missing_exit_session / raw_price_limit_outlier /
# signal_date_not_found / bars_unavailable
_PRODUCT_RULE_KEYS = frozenset(
    rule.key for rules in PRODUCT_DISCOVERY_RULES.values() for rule in rules
)
_PRODUCT_TIER_BY_RULE = {
    FIRST_LEG_TWO_MA_WRAP_RULE_KEY: "P1.5",
    PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY: "P1.5",
    PRICE_FIRST_STRONG_ATTACK_RULE_KEY: "P1.5",
    RESEARCH_THREE_MA_WRAP_RULE_KEY: "P1.5",
    POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY: "P1.5",
    STAGED_MA10_SUPPORT_RULE_KEY: "P1",
    LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY: "P1.5",
    LIMIT_UP_PULLBACK_REBOUND_RULE_KEY: "P1",
}
_FAMILY_ORDER = ("trend_pullback", "oversold_rebound")


def compute_forward_close_returns(
    bars: Sequence[Mapping[str, object]],
    signal_date: date,
    horizons: Sequence[int] = GUIDE_RETURN_HORIZONS,
) -> dict[str, Any]:
    """现算信号日后第 N 个实际交易日的收盘收益（D 日收盘买入口径）。

    bars 按 trade_date 升序，元素至少含 ``trade_date`` / ``close_price``。
    链式主板涨跌停检查：从信号日收盘起逐日校验，任一步越界（除权污染）
    则该档及更远档全部置 None。
    """

    result: dict[str, Any] = {
        f"d{horizon}_close_return_pct": None for horizon in horizons
    }
    dates = [bar["trade_date"] for bar in bars]
    try:
        signal_index = dates.index(signal_date)
    except ValueError:
        return {**result, "status": "signal_date_not_found"}

    signal_close = _close(bars[signal_index])
    if signal_close is None or signal_close <= 0:
        return {**result, "status": "bars_unavailable"}

    reached: dict[int, float] = {}
    blocked: str | None = None
    prior_close = signal_close
    for step in range(1, max(horizons) + 1):
        position = signal_index + step
        if position >= len(bars):
            blocked = "missing_exit_session"
            break
        close = _close(bars[position])
        if close is None or not is_main_board_close_within_price_limit(
            prior_close, close
        ):
            blocked = "raw_price_limit_outlier"
            break
        reached[step] = close
        prior_close = close

    for horizon in horizons:
        if horizon in reached:
            result[f"d{horizon}_close_return_pct"] = round(
                (reached[horizon] - signal_close) / signal_close * 100, 2
            )
    return {**result, "status": blocked or "available"}


def assemble_guide_payload(returns_by_case: Mapping[str, Mapping[str, Any]]) -> dict:
    """把策展案例 + 每案收益装配成说明书 payload（纯函数）。"""

    families = []
    for setup_type in _FAMILY_ORDER:
        rules = []
        for rule in DISCOVERY_RULES[setup_type]:
            cases = [
                _case_payload(case, returns_by_case.get(case.name))
                for case in PERSONAL_CASES
                if rule.key in case.required_process_rule_keys
            ]
            rules.append(
                {
                    "rule_key": rule.key,
                    "description": rule.description,
                    "tier": (
                        "product" if rule.key in _PRODUCT_RULE_KEYS else "research"
                    ),
                    "product_tier": _PRODUCT_TIER_BY_RULE.get(rule.key),
                    "cases": cases,
                }
            )
        families.append(
            {
                "key": setup_type,
                "label": SETUP_TYPE_LABELS[setup_type],
                "rules": rules,
            }
        )
    orphans = [
        _case_payload(case, returns_by_case.get(case.name))
        for case in PERSONAL_CASES
        if not case.required_process_rule_keys
    ]
    partial = any(
        (returns_by_case.get(case.name) or {}).get("status") == "bars_unavailable"
        for case in PERSONAL_CASES
    )
    return {
        "status": "partial" if partial else "ok",
        "score_version": SCORE_VERSION,
        "families": families,
        "orphan_cases": orphans,
    }


def load_guide_cases_payload() -> dict[str, Any]:
    """读库现算每案 D+N 收益并装配 payload（本模块唯一触库函数）。"""

    cases_by_symbol: dict[str, list[PersonalResearchCase]] = defaultdict(list)
    for case in PERSONAL_CASES:
        cases_by_symbol[case.vt_symbol].append(case)

    returns_by_case: dict[str, dict[str, Any]] = {}
    with session_scope() as session:
        for vt_symbol, group in cases_by_symbol.items():
            start = min(case.trade_date for case in group) - timedelta(
                days=_GUIDE_BARS_LOOKBACK_DAYS
            )
            end = max(case.trade_date for case in group) + timedelta(
                days=_GUIDE_BARS_FORWARD_DAYS
            )
            try:
                bars = _load_symbol_closes(session, vt_symbol, start, end)
            except Exception:  # noqa: BLE001 - 单票失败不拖垮整个端点
                bars = []
            if not bars:
                for case in group:
                    returns_by_case[case.name] = _empty_returns("bars_unavailable")
                continue
            for case in group:
                returns_by_case[case.name] = compute_forward_close_returns(
                    bars, case.trade_date
                )
    return assemble_guide_payload(returns_by_case)


def _load_symbol_closes(
    session, vt_symbol: str, start: date, end: date
) -> list[dict[str, Any]]:
    table = schema.stock_daily_bars
    stmt = (
        select(table.c.trade_date, table.c.close_price)
        .where(
            table.c.vt_symbol == vt_symbol,
            table.c.trade_date >= start,
            table.c.trade_date <= end,
        )
        .order_by(table.c.trade_date)
    )
    rows = session.execute(stmt).mappings().all()
    return [
        {"trade_date": row["trade_date"], "close_price": float(row["close_price"])}
        for row in rows
        if row["close_price"]
    ]


def _case_payload(
    case: PersonalResearchCase, returns: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {
        "case_id": case.name,
        "name": case.name,
        "vt_symbol": case.vt_symbol,
        "signal_date": case.trade_date.isoformat(),
        "setup_type": case.expected_setup_type,
        "narrative_start_date": (
            case.narrative_start_date.isoformat()
            if case.narrative_start_date
            else None
        ),
        "expected_launch_date": (
            case.expected_launch_date.isoformat()
            if case.expected_launch_date
            else None
        ),
        "source_anchor": case.source_anchor,
        "narrative_status": case.narrative_status,
        "returns": dict(returns) if returns else _empty_returns("bars_unavailable"),
    }


def _empty_returns(status: str) -> dict[str, Any]:
    return {
        **{
            f"d{horizon}_close_return_pct": None
            for horizon in GUIDE_RETURN_HORIZONS
        },
        "status": status,
    }


def _close(bar: Mapping[str, object]) -> float | None:
    value = bar.get("close_price")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
