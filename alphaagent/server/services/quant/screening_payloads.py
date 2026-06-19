"""Payload helpers for quant screening APIs and persistence."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from alphaagent.market.boards import stock_board_payload
from alphaagent.server.services.quant.factors import (
    BREAKOUT_STRATEGY_ID,
    DRAGON_PULLBACK_STRATEGY_ID,
    LIMIT_UP_PULLBACK_STRATEGY_ID,
    STRATEGY_ID,
    STRATEGY_VERSION,
    TREND_ACCELERATION_STRATEGY_ID,
    SignalScore,
)
from alphaagent.server.services.quant.strategy_registry import require_strategy


STEALTH_LOW_SUCTION_ENTRY_SCORE = 74.5
STEALTH_LOW_SUCTION_HARD_FAILURES = {
    "distribution_risk",
    "weak_rebound_ma5_below_ma10",
    "ma20_broken",
    "pullback_too_deep",
    "liquidity_score",
    "risk_score",
    "overheat",
}
LOW_SUCTION_LAUNCH_UNCONFIRMED_RULE = "low_suction_launch_unconfirmed"
SIGNAL_EVIDENCE_SCHEMA_VERSION = "2026-06-19.1"


def score_to_db(item: SignalScore, run_id: int | None, strategy_id: str, strategy_version: str = STRATEGY_VERSION) -> dict[str, Any]:
    evidence = dict(item.evidence or {})
    evidence["signal_evidence_schema_version"] = SIGNAL_EVIDENCE_SCHEMA_VERSION
    return {
        "run_id": run_id,
        "trade_date": item.trade_date,
        "vt_symbol": item.vt_symbol,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "signal_type": item.signal_type,
        "total_score": item.total_score,
        "relative_strength_score": item.relative_strength_score,
        "washout_score": item.washout_score,
        "trend_quality_score": item.trend_quality_score,
        "sector_mainline_score": item.sector_mainline_score,
        "financial_improvement_score": item.financial_improvement_score,
        "liquidity_score": item.liquidity_score,
        "risk_score": item.risk_score,
        "entry_signal": item.entry_signal,
        "risk_level": item.risk_level,
        "evidence": evidence,
    }


def recommendation_to_db(
    rank: int,
    item: SignalScore,
    run_id: int | None,
    strategy_id: str,
    strategy_version: str = STRATEGY_VERSION,
    *,
    min_entry_score: float | None = None,
) -> dict[str, Any]:
    strategy = require_strategy(strategy_id)
    threshold = strategy.default_min_entry_score if min_entry_score is None else min_entry_score
    reason = normalize_quant_evidence(dict(item.evidence or {}))
    reason["risk_score"] = item.risk_score
    reason["liquidity_score"] = item.liquidity_score
    action_payload = entry_action_payload(item, threshold)
    reason["failed_rules"] = action_payload["failed_rules"]
    reason["raw_entry_signal"] = action_payload["raw_entry_signal"]
    reason["executable_entry_signal"] = action_payload["executable_entry_signal"]
    reason["action"] = action_payload["action"]
    reason["signal_label"] = action_payload["signal_label"]
    reason["signal_role"] = action_payload["signal_role"]
    reason["key_entry_signal"] = action_payload["key_entry_signal"]
    entry_price = (item.evidence or {}).get("close_price")
    return {
        "run_id": run_id,
        "trade_date": item.trade_date,
        "vt_symbol": item.vt_symbol,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "rank": rank,
        "action": action_payload["action"],
        "horizon": "SWING",
        "confidence": item.total_score / 100,
        "total_score": item.total_score,
        "reason": reason,
        "risk_control": default_risk_control(entry_price=entry_price, trade_date=item.trade_date),
        "status": "active",
        "expires_at": item.trade_date + timedelta(days=7),
    }


def symbol_signal_row(item: SignalScore, min_entry_score: float) -> dict[str, Any]:
    evidence = item.evidence or {}
    ma5_distance = evidence.get("ma5_distance_pct")
    action_payload = entry_action_payload(item, min_entry_score)
    return {
        "trade_date": item.trade_date.isoformat(),
        "vt_symbol": item.vt_symbol,
        "total_score": item.total_score,
        "relative_strength_score": item.relative_strength_score,
        "washout_score": item.washout_score,
        "trend_quality_score": item.trend_quality_score,
        "sector_mainline_score": item.sector_mainline_score,
        "financial_improvement_score": item.financial_improvement_score,
        "liquidity_score": item.liquidity_score,
        "risk_score": item.risk_score,
        "entry_signal": item.entry_signal,
        **action_payload,
        "ma5": evidence.get("ma5"),
        "ma5_distance_pct": ma5_distance,
        "turnover20": evidence.get("turnover20"),
        "turnover_estimated_from_volume": evidence.get("turnover_estimated_from_volume"),
        "evidence": evidence,
    }


def entry_action_payload(item: SignalScore, min_entry_score: float) -> dict[str, Any]:
    effective_min_entry_score = effective_entry_score_threshold(item, min_entry_score)
    failed_rules = failed_entry_rules(item, min_entry_score)
    executable = bool(item.entry_signal and not failed_rules)
    signal_label, signal_role, key_entry_signal = signal_semantics(item, executable)
    return {
        "raw_entry_signal": bool(item.entry_signal),
        "executable_entry_signal": executable,
        "action": "BUY" if executable else "WATCH",
        "failed_rules": failed_rules,
        "failed_rule_count": len(failed_rules),
        "effective_min_entry_score": effective_min_entry_score,
        "entry_threshold_reason": "stealth_low_suction" if effective_min_entry_score < float(min_entry_score) else "default",
        "signal_label": signal_label,
        "signal_role": signal_role,
        "key_entry_signal": key_entry_signal,
    }


def signal_semantics(item: SignalScore, executable: bool) -> tuple[str, str, bool]:
    evidence = item.evidence or {}
    setup = str(evidence.get("setup_type") or evidence.get("entry_setup") or "")
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    fresh_tail_buy = bool(evidence.get("fresh_tail_buy", True))
    repeat_days = int(float(evidence.get("tail_buy_repeat_days") or 0))
    if setup == "stealth_low_suction":
        if executable and launch_confirmed:
            return "低吸启动买点", "key_buy", True
        return "低吸蓄势观察", "watch", False
    if setup == "dragon_pullback" and (not fresh_tail_buy or repeat_days > 0):
        return "重复龙回头观察" if not executable else "龙回头买点", "key_buy" if executable else "watch", executable
    if executable:
        return "龙回头买点", "key_buy", True
    return "观察", "watch", False


def symbol_signal_fit_key(row: dict[str, Any], strategy_id: str) -> tuple[int, float, float]:
    if strategy_id == DRAGON_PULLBACK_STRATEGY_ID:
        evidence = row.get("evidence") or {}
        state_rank = 0 if evidence.get("dragon_state") == "TAIL_BUY_READY" else 1
        support_rank = 0 if evidence.get("support_type") in {"ma5_reclaim", "ma10_support"} else 1
        ma5_distance = evidence.get("ma5_distance_pct")
        ma10_distance = evidence.get("ma10_distance_pct")
        distance = min(
            abs(float(ma5_distance)) if ma5_distance is not None else 999.0,
            abs(float(ma10_distance)) if ma10_distance is not None else 999.0,
        )
        return (state_rank + support_rank + int(row["failed_rule_count"]), -float(row["total_score"]), distance)
    if strategy_id == BREAKOUT_STRATEGY_ID:
        evidence = row.get("evidence") or {}
        close_to_high = evidence.get("close_to_prior_high_pct")
        distance = abs(float(close_to_high)) if close_to_high is not None else 999.0
        return (int(row["failed_rule_count"]), -float(row["total_score"]), distance)
    if strategy_id == LIMIT_UP_PULLBACK_STRATEGY_ID:
        evidence = row.get("evidence") or {}
        ma5_distance = evidence.get("ma5_distance_pct")
        days_since_limit_up = evidence.get("days_since_limit_up")
        distance = abs(float(ma5_distance)) if ma5_distance is not None else 999.0
        recency_gap = abs(float(days_since_limit_up) - 5.0) if days_since_limit_up is not None else 999.0
        return (int(row["failed_rule_count"]), -float(row["total_score"]), distance + recency_gap / 10.0)
    if strategy_id == TREND_ACCELERATION_STRATEGY_ID:
        evidence = row.get("evidence") or {}
        ma5_distance = evidence.get("ma5_distance_pct")
        volume_ratio = evidence.get("volume_ratio_5d_20d")
        distance = abs(float(ma5_distance) - 3.0) if ma5_distance is not None else 999.0
        volume_gap = abs(float(volume_ratio) - 1.5) if volume_ratio is not None else 999.0
        return (int(row["failed_rule_count"]), -float(row["total_score"]), distance + volume_gap)
    ma5_distance = row.get("ma5_distance_pct")
    distance = abs(float(ma5_distance)) if ma5_distance is not None else 999.0
    return (int(row["failed_rule_count"]), -float(row["total_score"]), distance)


def strategy_rule_payload(strategy_id: str, min_entry_score: float) -> dict[str, Any]:
    if strategy_id == DRAGON_PULLBACK_STRATEGY_ID:
        return {
            "min_entry_score": min_entry_score,
            "stealth_low_suction_min_entry_score": STEALTH_LOW_SUCTION_ENTRY_SCORE,
            "pullback_days": "[3, 12]",
            "support_type": "MA5/MA10/MA20 support + reclaim",
            "ma5_distance_pct": "[-1.8, 3.0]",
            "ma10_distance_pct": "[-2.5, 3.0]",
            "ma_convergence_pct": "<= 8.8 adds low-suction score; improving <=13.0 can count during shrinking-volume absorption",
            "low_suction_days": "continuous MA5/MA10/MA20 acceptance with shrinking volume adds score",
            "stealth_low_suction_execution": "setup-specific threshold requires repeated low-suction days, MA20 not broken, controlled volume, no hard risk failure, and the first controlled lift can confirm the setup",
            "ma_convergence_too_wide_without_low_suction": "reject wide MA spread without repeated low-suction",
            "distribution_risk": "reject",
            "weak_rebound_ma5_below_ma10": "reject",
            "min_risk_score": 35,
            "min_liquidity_score": 25,
        }
    if strategy_id == BREAKOUT_STRATEGY_ID:
        return {
            "min_entry_score": min_entry_score,
            "close_to_prior_high_pct": ">= -1.0",
            "volume_ratio_5d_20d": ">= 1.10",
            "min_trend_quality_score": 60,
            "min_risk_score": 35,
            "min_liquidity_score": 25,
        }
    if strategy_id == LIMIT_UP_PULLBACK_STRATEGY_ID:
        return {
            "min_entry_score": min_entry_score,
            "limit_up_count_20d": ">= 1",
            "days_since_limit_up": "[2, 12]",
            "ma5_distance_pct": "[-3.0, 4.0]",
            "ma20_distance_pct": ">= -2.0",
            "min_trend_quality_score": 60,
            "min_risk_score": 35,
            "min_liquidity_score": 25,
        }
    if strategy_id == TREND_ACCELERATION_STRATEGY_ID:
        return {
            "min_entry_score": min_entry_score,
            "return_20d": ">= 12.0",
            "return_60d": ">= 20.0",
            "return_5d": "[1.0, 18.0]",
            "ma_alignment": "MA5 > MA20 > MA60",
            "ma5_distance_pct": "[-1.0, 8.0]",
            "ma20_distance_pct": "[2.0, 28.0]",
            "volume_ratio_5d_20d": "[1.05, 2.80]",
            "latest_change_pct": "<= 8.5",
            "min_trend_quality_score": 65,
            "min_risk_score": 45,
            "min_liquidity_score": 30,
        }
    return {
        "min_entry_score": min_entry_score,
        "ma5_distance_pct": "[-1.5, 2.0]",
        "min_risk_score": 35,
        "min_liquidity_score": 25,
    }


def failed_entry_rules(
    item: SignalScore,
    min_entry_score: float,
    *,
    include_low_suction_launch_gate: bool = True,
) -> list[str]:
    evidence = item.evidence or {}
    failed_rules = []
    if item.total_score < effective_entry_score_threshold(item, min_entry_score):
        failed_rules.append("total_score")
    if item.signal_type == DRAGON_PULLBACK_STRATEGY_ID:
        for rule in evidence.get("failed_rules") or []:
            if _is_executable_low_suction_exception(evidence, str(rule)):
                continue
            if rule not in failed_rules:
                failed_rules.append(str(rule))
        if (
            include_low_suction_launch_gate
            and _is_unconfirmed_stealth_low_suction(item)
            and LOW_SUCTION_LAUNCH_UNCONFIRMED_RULE not in failed_rules
        ):
            failed_rules.append(LOW_SUCTION_LAUNCH_UNCONFIRMED_RULE)
        if item.risk_score < 35:
            failed_rules.append("risk_score")
        if item.liquidity_score < 25:
            failed_rules.append("liquidity_score")
        return failed_rules
    if item.signal_type == BREAKOUT_STRATEGY_ID:
        close_to_high = evidence.get("close_to_prior_high_pct")
        volume_ratio = evidence.get("volume_ratio_5d_20d")
        if close_to_high is None or float(close_to_high) < -1.0:
            failed_rules.append("breakout_distance")
        if volume_ratio is None or float(volume_ratio) < 1.10:
            failed_rules.append("volume_confirmation")
        if item.trend_quality_score < 60:
            failed_rules.append("trend_quality")
        if item.risk_score < 35:
            failed_rules.append("risk_score")
        if item.liquidity_score < 25:
            failed_rules.append("liquidity_score")
        return failed_rules
    if item.signal_type == LIMIT_UP_PULLBACK_STRATEGY_ID:
        limit_up_count = evidence.get("limit_up_count_20d")
        days_since_limit_up = evidence.get("days_since_limit_up")
        ma5_distance = evidence.get("ma5_distance_pct")
        ma20_distance = evidence.get("ma20_distance_pct")
        if limit_up_count is None or float(limit_up_count) < 1:
            failed_rules.append("limit_up_presence")
        if days_since_limit_up is None or not (2 <= float(days_since_limit_up) <= 12):
            failed_rules.append("limit_up_recency")
        if ma5_distance is None or not (-3.0 <= float(ma5_distance) <= 4.0):
            failed_rules.append("pullback_position")
        if ma20_distance is None or float(ma20_distance) < -2.0:
            failed_rules.append("ma20_support")
        if item.trend_quality_score < 60:
            failed_rules.append("trend_quality")
        if item.risk_score < 35:
            failed_rules.append("risk_score")
        if item.liquidity_score < 25:
            failed_rules.append("liquidity_score")
        return failed_rules
    if item.signal_type == TREND_ACCELERATION_STRATEGY_ID:
        return_5d = evidence.get("return_5d")
        return_20d = evidence.get("return_20d")
        return_60d = evidence.get("return_60d")
        ma5 = evidence.get("ma5")
        ma20 = evidence.get("ma20")
        ma60 = evidence.get("ma60")
        ma5_distance = evidence.get("ma5_distance_pct")
        ma20_distance = evidence.get("ma20_distance_pct")
        volume_ratio = evidence.get("volume_ratio_5d_20d")
        latest_change = evidence.get("latest_change_pct")
        if return_20d is None or float(return_20d) < 12.0 or return_60d is None or float(return_60d) < 20.0:
            failed_rules.append("trend_return")
        if return_5d is None or not (1.0 <= float(return_5d) <= 18.0):
            failed_rules.append("recent_acceleration")
        if ma5 is None or ma20 is None or ma60 is None or not (float(ma5) > float(ma20) > float(ma60)):
            failed_rules.append("ma_alignment")
        if ma5_distance is None or not (-1.0 <= float(ma5_distance) <= 8.0):
            failed_rules.append("ma5_position")
        if ma20_distance is None or not (2.0 <= float(ma20_distance) <= 28.0):
            failed_rules.append("ma20_position")
        if volume_ratio is None or not (1.05 <= float(volume_ratio) <= 2.80):
            failed_rules.append("volume_acceleration")
        if latest_change is not None and float(latest_change) > 8.5:
            failed_rules.append("overheat")
        if item.trend_quality_score < 65:
            failed_rules.append("trend_quality")
        if item.risk_score < 45:
            failed_rules.append("risk_score")
        if item.liquidity_score < 30:
            failed_rules.append("liquidity_score")
        return failed_rules
    ma5_distance = evidence.get("ma5_distance_pct")
    if ma5_distance is None or not (-1.5 <= float(ma5_distance) <= 2.0):
        failed_rules.append("ma5_distance")
    if item.risk_score < 35:
        failed_rules.append("risk_score")
    if item.liquidity_score < 25:
        failed_rules.append("liquidity_score")
    return failed_rules


def effective_entry_score_threshold(item: SignalScore, min_entry_score: float) -> float:
    if _qualifies_for_stealth_low_suction_threshold(item):
        return min(float(min_entry_score), STEALTH_LOW_SUCTION_ENTRY_SCORE)
    return float(min_entry_score)


def signal_score_prefilter_threshold(strategy_id: str, min_entry_score: float) -> float:
    if strategy_id == DRAGON_PULLBACK_STRATEGY_ID:
        return min(float(min_entry_score), STEALTH_LOW_SUCTION_ENTRY_SCORE)
    return float(min_entry_score)


def _qualifies_for_stealth_low_suction_threshold(item: SignalScore) -> bool:
    if item.signal_type != DRAGON_PULLBACK_STRATEGY_ID:
        return False
    if not item.entry_signal:
        return False
    if float(item.total_score or 0.0) < STEALTH_LOW_SUCTION_ENTRY_SCORE:
        return False
    evidence = item.evidence or {}
    if evidence.get("setup_type") != "stealth_low_suction" and evidence.get("entry_setup") != "stealth_low_suction":
        return False
    try:
        low_suction_days = float(evidence.get("low_suction_days") or 0)
        low_suction_score = float(evidence.get("low_suction_buildup_score") or 0)
        stealth_score = float(evidence.get("stealth_low_suction_score") or 0)
        convergence = float(evidence.get("ma_convergence_pct") or 999)
        volume_ratio = float(evidence.get("volume_ratio_5d_20d") or 0)
        ma20_distance = float(evidence.get("ma20_distance_pct") or -999)
    except (TypeError, ValueError):
        return False
    if low_suction_days < 4 or low_suction_score < 95 or stealth_score < 90:
        return False
    if convergence > 3.5:
        return False
    if not 0.55 <= volume_ratio <= 1.45:
        return False
    if ma20_distance < -2.5:
        return False
    failed_rules = {str(rule) for rule in evidence.get("failed_rules") or []}
    return not bool(failed_rules & STEALTH_LOW_SUCTION_HARD_FAILURES)


def _is_unconfirmed_stealth_low_suction(item: SignalScore) -> bool:
    if item.signal_type != DRAGON_PULLBACK_STRATEGY_ID:
        return False
    if not item.entry_signal:
        return False
    evidence = item.evidence or {}
    setup = str(evidence.get("setup_type") or evidence.get("entry_setup") or "")
    return setup == "stealth_low_suction" and not bool(evidence.get("low_suction_launch_confirmed"))


def _is_executable_low_suction_exception(evidence: dict[str, Any], rule: str) -> bool:
    if evidence.get("setup_type") == "stealth_low_suction":
        return rule in {
            "strong_leg",
            "pullback_structure",
            "support_acceptance",
            "reclaim_confirmation",
            "pullback_too_short",
            "pullback_too_late",
        }
    if rule != "reclaim_confirmation":
        return False
    if evidence.get("dragon_state") != "LOW_SUCTION_BUILDUP":
        return False
    try:
        low_suction_score = float(evidence.get("low_suction_buildup_score") or 0)
        low_suction_days = float(evidence.get("low_suction_days") or 0)
        convergence = float(evidence.get("ma_convergence_pct") or 999)
        ma20_distance = float(evidence.get("ma20_distance_pct") or -999)
    except (TypeError, ValueError):
        return False
    return (
        low_suction_score >= 90
        and low_suction_days >= 3
        and convergence <= 5.0
        and ma20_distance >= -3.0
    )


def score_to_api(item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = score_to_db(item, None, item.signal_type or STRATEGY_ID)
    payload.pop("run_id", None)
    payload["trade_date"] = item.trade_date.isoformat()
    payload["name"] = stock.get("name") if stock else None
    payload.update(stock_board_payload(item.vt_symbol, (stock or {}).get("exchange")))
    return payload


def recommendation_to_api(rank: int, item: SignalScore, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = recommendation_to_db(rank, item, None, item.signal_type or STRATEGY_ID)
    payload.pop("run_id", None)
    payload["trade_date"] = item.trade_date.isoformat()
    payload["expires_at"] = payload["expires_at"].isoformat()
    payload["name"] = stock.get("name") if stock else None
    payload.update(stock_board_payload(item.vt_symbol, (stock or {}).get("exchange")))
    return payload


def default_risk_control(entry_price: float | None = None, trade_date: date | None = None) -> dict[str, Any]:
    stop_loss_pct = 0.07
    take_profit_pct = 0.18
    risk_control = {
        "max_position_pct": 0.125,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "trailing_stop_pct": 0.08,
        "time_stop_days": 15,
        "execution": "daily close observable signal; execution model selected by backtest",
    }
    # 候选筛选时预算买卖计划：买入价=信号日收盘，止损/止盈按风险参数推算。
    # 存入 risk_control.trade_plan，供单股详情与回测直接读取，避免反复重算。
    if entry_price is not None:
        risk_control["trade_plan"] = {
            "entry_price": round(float(entry_price), 4),
            "stop_loss_price": round(float(entry_price) * (1 - stop_loss_pct), 4),
            "take_profit_price": round(float(entry_price) * (1 + take_profit_pct), 4),
            "entry_date": trade_date.isoformat() if trade_date else None,
        }
    return risk_control


def mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if result.get("vt_symbol"):
        result.update(stock_board_payload(result.get("vt_symbol")))
    if isinstance(result.get("reason"), dict):
        result["reason"] = normalize_quant_evidence(result["reason"])
        _apply_read_action_from_reason(result)
    if isinstance(result.get("evidence"), dict):
        result["evidence"] = normalize_quant_evidence(result["evidence"])
    if "entry_signal" in result and "total_score" in result:
        result.update(signal_mapping_action_payload(result))
    if isinstance(result.get("risk_control"), dict):
        result["risk_control"] = normalize_risk_control(result["risk_control"])
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


def recommendation_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    result = mapping_to_api(row)
    result["name"] = result.pop("stock_name", None)
    return result


def _apply_read_action_from_reason(result: dict[str, Any]) -> None:
    reason = result.get("reason")
    if not isinstance(reason, dict):
        return
    if not reason.get("action"):
        _derive_reason_action(result, reason)
    current_action = str(reason.get("action") or "").upper()
    if current_action not in {"BUY", "WATCH"}:
        return
    persisted_action = str(result.get("action") or "").upper()
    if persisted_action and persisted_action != current_action:
        result["persisted_action"] = persisted_action
        result["action_mismatch_resolved"] = True
    result["action"] = current_action
    for key in (
        "failed_rules",
        "raw_entry_signal",
        "executable_entry_signal",
        "signal_label",
        "signal_role",
        "key_entry_signal",
    ):
        if key in reason:
            result[key] = reason[key]


def _derive_reason_action(result: dict[str, Any], reason: dict[str, Any]) -> None:
    strategy_id = str(result.get("strategy_id") or result.get("signal_type") or STRATEGY_ID)
    try:
        min_entry_score = float(require_strategy(strategy_id).default_min_entry_score)
    except ValueError:
        min_entry_score = float(require_strategy(STRATEGY_ID).default_min_entry_score)
    item = SignalScore(
        vt_symbol=str(result.get("vt_symbol") or ""),
        trade_date=result.get("trade_date") if isinstance(result.get("trade_date"), date) else date.min,
        signal_type=strategy_id,
        total_score=_float_or_default(result.get("total_score"), 0.0),
        relative_strength_score=_float_or_default(result.get("relative_strength_score"), 0.0),
        washout_score=_float_or_default(result.get("washout_score"), 0.0),
        trend_quality_score=_float_or_default(result.get("trend_quality_score"), 0.0),
        sector_mainline_score=_float_or_default(result.get("sector_mainline_score"), 50.0),
        financial_improvement_score=_float_or_default(result.get("financial_improvement_score"), 50.0),
        liquidity_score=_float_or_default(result.get("liquidity_score"), reason.get("liquidity_score") or 100.0),
        risk_score=_float_or_default(result.get("risk_score"), reason.get("risk_score") or 50.0),
        entry_signal=bool(reason.get("raw_entry_signal", result.get("entry_signal", True))),
        risk_level=str(result.get("risk_level") or "MEDIUM"),
        evidence=reason,
    )
    reason.update(entry_action_payload(item, min_entry_score))


def normalize_quant_evidence(value: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(value)
    if evidence.get("entry_rule") == "daily_close_signal_next_open_execution":
        evidence.pop("entry_rule", None)
        evidence.setdefault("selection_rule", "daily_close_visible_signal")
        evidence.setdefault("entry_setup", "ma5_pullback")
    _normalize_market_context_summary(evidence)
    _normalize_low_suction_stage(evidence)
    _normalize_low_suction_launch_quality(evidence)
    _normalize_low_suction_dragon_context(evidence)
    return evidence


def _normalize_market_context_summary(evidence: dict[str, Any]) -> None:
    if isinstance(evidence.get("market_context_summary"), dict):
        summary = dict(evidence["market_context_summary"])
        if not isinstance(summary.get("fund_flow_marker"), dict):
            payload = _market_context_payload_from_evidence(evidence)
            if any(value not in (None, "") for value in payload.values()):
                from alphaagent.server.services.quant.market_context import market_context_summary

                generated = market_context_summary(payload)
                if isinstance(generated.get("fund_flow_marker"), dict):
                    summary["fund_flow_marker"] = generated["fund_flow_marker"]
                    notes = list(summary.get("notes") or [])
                    for note in generated.get("notes") or []:
                        text = str(note or "").strip()
                        if text and text not in notes:
                            notes.append(text)
                    summary["notes"] = notes
                    evidence["market_context_summary"] = summary
        return
    payload = evidence.get("market_context") if isinstance(evidence.get("market_context"), dict) else {}
    payload = _market_context_payload_from_evidence(evidence, payload)
    if not any(value not in (None, "") for value in payload.values()):
        return
    from alphaagent.server.services.quant.market_context import market_context_summary

    evidence["market_context_summary"] = market_context_summary(payload)


def _market_context_payload_from_evidence(
    evidence: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(payload or {})
    # Top-level fund_flow_score is a per-stock smart-money input in old evidence.
    # Prefer the nested market_context values for market/fund-flow summaries.
    return {
        **base,
        "regime": base.get("regime", evidence.get("dynamic_market_regime")),
        "label": base.get("label", evidence.get("dynamic_market_label")),
        "market_warning_level": base.get("market_warning_level", evidence.get("market_warning_level")),
        "market_warning_label": base.get("market_warning_label", evidence.get("market_warning_label")),
        "fund_flow_state": base.get("fund_flow_state", evidence.get("fund_flow_state")),
        "fund_flow_label": base.get("fund_flow_label", evidence.get("fund_flow_label")),
        "fund_flow_score": base.get("fund_flow_score", evidence.get("fund_flow_score")),
        "fund_flow_streak_days": base.get("fund_flow_streak_days", evidence.get("fund_flow_streak_days")),
        "fund_flow_source": base.get("fund_flow_source", evidence.get("fund_flow_source")),
        "main_net_inflow": base.get("main_net_inflow", evidence.get("main_net_inflow")),
        "main_net_inflow_ratio": base.get("main_net_inflow_ratio", evidence.get("main_net_inflow_ratio")),
        "recovery_state": base.get("recovery_state", evidence.get("recovery_state")),
        "recovery_label": base.get("recovery_label", evidence.get("recovery_label")),
    }


def _normalize_low_suction_stage(evidence: dict[str, Any]) -> None:
    if evidence.get("low_suction_stage_label"):
        return
    setup = str(evidence.get("setup_type") or evidence.get("entry_setup") or "")
    try:
        days = float(evidence.get("low_suction_days") or 0)
        pullback_days = float(evidence.get("pullback_days") or 0)
        close_location = float(evidence.get("close_location_in_range")) if evidence.get("close_location_in_range") is not None else None
        volume_ratio = float(evidence.get("volume_ratio_5d_20d")) if evidence.get("volume_ratio_5d_20d") is not None else None
    except (TypeError, ValueError):
        return
    if setup != "stealth_low_suction" and days < 3:
        stage = "not_low_suction"
    elif bool(evidence.get("low_suction_launch_confirmed")):
        if pullback_days >= 12:
            stage = "late_confirmed_lift"
        elif volume_ratio is not None and volume_ratio < 0.75:
            stage = "thin_confirmed_lift"
        elif close_location is not None and 0.55 <= close_location <= 0.72 and volume_ratio is not None and 0.80 <= volume_ratio <= 1.40:
            stage = "balanced_first_lift"
        else:
            stage = "confirmed_lift"
    elif days >= 6:
        stage = "mature_buildup_waiting_lift"
    elif days >= 3:
        stage = "buildup_waiting_lift"
    else:
        stage = "not_low_suction"
    labels = {
        "not_low_suction": "非低吸蓄势",
        "buildup_waiting_lift": "低吸蓄势等待上拉",
        "mature_buildup_waiting_lift": "低吸蓄势已久等待上拉",
        "balanced_first_lift": "低吸首个均衡上拉",
        "thin_confirmed_lift": "低吸上拉量能偏弱",
        "late_confirmed_lift": "低吸启动偏晚",
        "confirmed_lift": "低吸上拉确认",
    }
    evidence["low_suction_stage"] = stage
    evidence["low_suction_stage_label"] = labels[stage]


def _normalize_low_suction_launch_quality(evidence: dict[str, Any]) -> None:
    from alphaagent.server.services.quant.low_suction_quality import ensure_low_suction_launch_quality

    ensure_low_suction_launch_quality(evidence)


def _normalize_low_suction_dragon_context(evidence: dict[str, Any]) -> None:
    from alphaagent.server.services.quant.low_suction_quality import ensure_low_suction_dragon_context

    ensure_low_suction_dragon_context(evidence)


def signal_mapping_action_payload(row: dict[str, Any], min_entry_score: float | None = None) -> dict[str, Any]:
    strategy_id = str(row.get("signal_type") or row.get("strategy_id") or STRATEGY_ID)
    if min_entry_score is None:
        try:
            min_entry_score = float(require_strategy(strategy_id).default_min_entry_score)
        except ValueError:
            min_entry_score = float(require_strategy(STRATEGY_ID).default_min_entry_score)
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    item = SignalScore(
        vt_symbol=str(row.get("vt_symbol") or ""),
        trade_date=row.get("trade_date") if isinstance(row.get("trade_date"), date) else date.min,
        signal_type=strategy_id,
        total_score=_float_or_default(row.get("total_score"), 0.0),
        relative_strength_score=_float_or_default(row.get("relative_strength_score"), 0.0),
        washout_score=_float_or_default(row.get("washout_score"), 0.0),
        trend_quality_score=_float_or_default(row.get("trend_quality_score"), 0.0),
        sector_mainline_score=_float_or_default(row.get("sector_mainline_score"), 50.0),
        financial_improvement_score=_float_or_default(row.get("financial_improvement_score"), 50.0),
        liquidity_score=_float_or_default(row.get("liquidity_score"), 0.0),
        risk_score=_float_or_default(row.get("risk_score"), 50.0),
        entry_signal=bool(row.get("entry_signal")),
        risk_level=str(row.get("risk_level") or "MEDIUM"),
        evidence=evidence,
    )
    return entry_action_payload(item, float(min_entry_score))


def normalize_risk_control(value: dict[str, Any]) -> dict[str, Any]:
    risk_control = dict(value)
    if risk_control.get("execution") == "D close signal; D+1 tail-window minute fill when available, otherwise next-open simulation fallback":
        risk_control["execution"] = default_risk_control()["execution"]
    return risk_control


def _float_or_default(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
