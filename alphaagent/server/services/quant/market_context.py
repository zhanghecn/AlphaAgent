"""Market and theme context snapshots for quant audits.

The first version is intentionally read-only: it classifies market conditions
from data visible on or before the trade date, and does not alter strategy
orders or scores.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev
from threading import Lock
from typing import Any

from sqlalchemy import desc, func, select

from alphaagent.market.symbols import INDEX_SYMBOLS


INDEX_WEIGHTS: dict[str, float] = {
    "000001.SSE": 0.18,
    "000300.SSE": 0.18,
    "000905.SSE": 0.16,
    "000852.SSE": 0.16,
    "399001.SZSE": 0.12,
    "399006.SZSE": 0.12,
    "000688.SSE": 0.08,
}
GROWTH_INDEXES = {"399006.SZSE", "000688.SSE", "000852.SSE"}
VALUE_INDEXES = {"000001.SSE", "000300.SSE"}
DEFAULT_CONTEXT_SOURCE = "stock_daily_bars"
_BREADTH_CACHE_MAX_ENTRIES = 4
_BREADTH_CACHE_LOCK = Lock()
_BREADTH_CACHE: list[tuple[date, date, dict[date, dict[str, float]]]] = []


@dataclass(frozen=True)
class MarketContext:
    trade_date: date
    regime: str
    label: str
    dominant_theme: str | None
    dominant_theme_id: str | None
    theme_state: str
    market_score: float
    trend_score: float
    momentum_score: float
    breadth_score: float
    risk_score: float
    volatility_score: float
    theme_strength: float
    theme_breadth: float | None
    growth_score: float | None
    value_score: float | None
    small_cap_score: float | None
    index_return_5d: float | None
    index_return_20d: float | None
    drawdown_60d_pct: float | None
    fund_flow_state: str
    fund_flow_label: str
    fund_flow_score: float | None
    fund_flow_streak_days: int
    fund_flow_source: str | None
    main_net_inflow: float | None
    main_net_inflow_ratio: float | None
    fund_flow_worsening_days: int
    fund_flow_new_low: bool
    fund_flow_recovery_from_streak_days: int
    market_warning_level: int
    market_warning_label: str
    recovery_state: str
    recovery_label: str
    source: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "regime": self.regime,
            "label": self.label,
            "dominant_theme": self.dominant_theme,
            "dominant_theme_id": self.dominant_theme_id,
            "theme_state": self.theme_state,
            "market_score": self.market_score,
            "trend_score": self.trend_score,
            "momentum_score": self.momentum_score,
            "breadth_score": self.breadth_score,
            "risk_score": self.risk_score,
            "volatility_score": self.volatility_score,
            "theme_strength": self.theme_strength,
            "theme_breadth": self.theme_breadth,
            "growth_score": self.growth_score,
            "value_score": self.value_score,
            "small_cap_score": self.small_cap_score,
            "index_return_5d": self.index_return_5d,
            "index_return_20d": self.index_return_20d,
            "drawdown_60d_pct": self.drawdown_60d_pct,
            "fund_flow_state": self.fund_flow_state,
            "fund_flow_label": self.fund_flow_label,
            "fund_flow_score": self.fund_flow_score,
            "fund_flow_streak_days": self.fund_flow_streak_days,
            "fund_flow_source": self.fund_flow_source,
            "main_net_inflow": self.main_net_inflow,
            "main_net_inflow_ratio": self.main_net_inflow_ratio,
            "fund_flow_worsening_days": self.fund_flow_worsening_days,
            "fund_flow_new_low": self.fund_flow_new_low,
            "fund_flow_recovery_from_streak_days": self.fund_flow_recovery_from_streak_days,
            "market_warning_level": self.market_warning_level,
            "market_warning_label": self.market_warning_label,
            "recovery_state": self.recovery_state,
            "recovery_label": self.recovery_label,
            "source": self.source,
            "notes": self.notes,
        }


def market_context_for_date(session: Any, schema: Any, trade_date: date) -> dict[str, Any]:
    if not hasattr(session, "execute"):
        return _fallback_context(trade_date).to_dict()
    return compute_market_contexts(session, schema, [trade_date]).get(trade_date, _fallback_context(trade_date)).to_dict()


def classify_dynamic_market_context(
    *,
    index_trend: dict[str, float | str | None],
    breadth: dict[str, float | int | None],
    sector_flow: dict[str, float | str | None],
    stock_theme_alignment: str | None,
) -> dict[str, Any]:
    """Classify market/mainline state for audit displays only."""

    index_return_20d = _safe_float(index_trend.get("return_20d"))
    index_return_5d = _safe_float(index_trend.get("return_5d"))
    drawdown_20d = _safe_float(index_trend.get("drawdown_20d_pct") or index_trend.get("drawdown_pct"))
    ma20_slope = _safe_float(index_trend.get("ma20_slope_pct"))
    breadth_score = _safe_float(breadth.get("breadth_score"))
    up_ratio = _safe_float(breadth.get("up_ratio"))
    limit_down_count = _safe_float(breadth.get("limit_down_count")) or 0.0
    theme_strength = _safe_float(sector_flow.get("theme_strength") or sector_flow.get("dominant_theme_strength")) or 0.0
    fund_flow_state = _fund_flow_state_from_audit_payload(sector_flow)
    dominant_theme = sector_flow.get("dominant_theme")
    alignment = str(stock_theme_alignment or "unknown")
    explain: list[str] = []

    market_warning_level = 0
    if limit_down_count >= 30 or (drawdown_20d is not None and drawdown_20d <= -8) or fund_flow_state == "panic_outflow":
        market_warning_level = 4
        explain.append("市场出现强风险或恐慌流出")
    elif (index_return_20d is not None and index_return_20d <= -5) or (breadth_score is not None and breadth_score < 35) or fund_flow_state == "outflow":
        market_warning_level = 3
        explain.append("大盘或资金状态向下")
    elif (index_return_20d is not None and index_return_20d < 0) or (breadth_score is not None and breadth_score < 45):
        market_warning_level = 2
        explain.append("市场分歧，风险观察")
    elif fund_flow_state == "insufficient_data":
        explain.append("资金流历史不足")

    market_recovery_level = 0
    if fund_flow_state == "recovery" and (index_return_5d is None or index_return_5d >= 0):
        market_recovery_level = 3
        explain.append("资金回流")
    elif index_return_5d is not None and index_return_5d > 1.5 and (breadth_score is None or breadth_score >= 50):
        market_recovery_level = 3
        explain.append("指数和市场广度回暖")
    elif index_return_5d is not None and index_return_5d >= 0 and (up_ratio is None or up_ratio >= 0.48):
        market_recovery_level = 2
        explain.append("止跌观察")

    if theme_strength >= 75 and alignment in {"aligned", "leader_theme", "theme_related"}:
        if market_warning_level >= 2 and index_return_5d is not None and index_return_5d < 0:
            regime = "mainline_pullback"
            explain.append("主线仍强但处于回踩")
        else:
            regime = "narrow_mainline_bull"
            explain.append("主线强势且个股对齐")
    elif market_warning_level >= 4:
        regime = "risk_off"
    elif market_warning_level >= 3:
        regime = "risk_off" if market_recovery_level <= 1 else "weak_rebound"
    elif index_return_20d is not None and index_return_20d >= 5 and (breadth_score is None or breadth_score >= 55):
        regime = "strong_broad"
        explain.append("指数和广度强势")
    elif market_recovery_level >= 2 and market_warning_level >= 2:
        regime = "weak_rebound"
    elif ma20_slope is not None and ma20_slope > 0 and (breadth_score is not None and breadth_score < 48):
        regime = "false_bull"
        explain.append("指数表面偏强但广度不足")
    else:
        regime = "choppy_rotation"
        explain.append("震荡轮动")

    return {
        "dynamic_market_regime": regime,
        "market_warning_level": market_warning_level,
        "market_recovery_level": market_recovery_level,
        "fund_flow_state": fund_flow_state,
        "dominant_theme": dominant_theme,
        "theme_strength": theme_strength,
        "stock_theme_alignment": alignment,
        "explain": _dedupe_notes(explain),
        "not_used_for_signal_score": True,
    }


def compute_market_contexts(session: Any, schema: Any, trade_dates: list[date]) -> dict[date, MarketContext]:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
        return {}
    if not hasattr(session, "execute"):
        return {day: _fallback_context(day) for day in dates}
    start = dates[0] - timedelta(days=420)
    end = dates[-1]
    index_bars = _load_index_bars(session, schema, start, end)
    breadth_by_date = _load_market_breadth_by_date(session, schema, dates[0] - timedelta(days=180), end, dates)
    sector_scores = _load_sector_scores(session, schema, start, end)
    fund_flows = _load_fund_flows_by_date(session, schema, dates[0] - timedelta(days=80), end)
    contexts: dict[date, MarketContext] = {}
    for day in dates:
        contexts[day] = _build_context(day, index_bars, breadth_by_date, sector_scores, fund_flows)
    return contexts


def annotate_rows_with_market_context(
    session: Any,
    schema: Any,
    rows: list[dict[str, Any]],
    *,
    date_key: str = "signal_date",
) -> list[dict[str, Any]]:
    dates = sorted({row.get(date_key) for row in rows if isinstance(row.get(date_key), date)})
    if not _has_index_context(session, schema, dates):
        return _annotate_rows_with_benchmark_proxy(rows)
    contexts = compute_market_contexts(session, schema, dates)
    theme_memberships = _load_stock_theme_memberships(session, schema, rows, contexts)
    result = []
    for row in rows:
        trade_date = row.get(date_key)
        context = contexts.get(trade_date) if isinstance(trade_date, date) else None
        if not context:
            result.append(row)
            continue
        merged = dict(row)
        payload = context.to_dict()
        merged["dynamic_market_regime"] = payload["regime"]
        merged["dynamic_market_label"] = payload["label"]
        merged["dynamic_market_source"] = payload["source"]
        merged["dominant_theme"] = payload["dominant_theme"]
        merged["dominant_theme_id"] = payload["dominant_theme_id"]
        merged["theme_state"] = payload["theme_state"]
        merged["market_score"] = payload["market_score"]
        merged["market_breadth_score"] = payload["breadth_score"]
        merged["market_risk_score"] = payload["risk_score"]
        merged["market_warning_level"] = payload["market_warning_level"]
        merged["market_warning_label"] = payload["market_warning_label"]
        merged["fund_flow_state"] = payload["fund_flow_state"]
        merged["fund_flow_label"] = payload["fund_flow_label"]
        merged["fund_flow_score"] = payload["fund_flow_score"]
        merged["fund_flow_streak_days"] = payload["fund_flow_streak_days"]
        merged["fund_flow_source"] = payload["fund_flow_source"]
        merged["recovery_state"] = payload["recovery_state"]
        merged["recovery_label"] = payload["recovery_label"]
        merged["theme_strength"] = payload["theme_strength"]
        merged["market_context_summary"] = market_context_summary(payload)
        merged["stock_theme_alignment"] = _stock_theme_alignment(
            row,
            payload,
            (str(row.get("vt_symbol") or ""), str(payload.get("dominant_theme_id") or "")) in theme_memberships,
        )
        result.append(merged)
    return result


def _annotate_rows_with_benchmark_proxy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        payload = _benchmark_proxy_context(row)
        merged = dict(row)
        merged["dynamic_market_regime"] = payload["regime"]
        merged["dynamic_market_label"] = payload["label"]
        merged["dynamic_market_source"] = "benchmark_return_20d_proxy"
        merged["dominant_theme"] = None
        merged["dominant_theme_id"] = None
        merged["theme_state"] = "none"
        merged["market_score"] = payload["market_score"]
        merged["market_breadth_score"] = None
        merged["market_risk_score"] = payload["risk_score"]
        merged["market_warning_level"] = payload.get("market_warning_level", 0)
        merged["market_warning_label"] = payload.get("market_warning_label", "未知")
        merged["fund_flow_state"] = "unknown"
        merged["fund_flow_label"] = "资金未知"
        merged["fund_flow_score"] = None
        merged["fund_flow_streak_days"] = 0
        merged["fund_flow_source"] = None
        merged["recovery_state"] = payload.get("recovery_state", "none")
        merged["recovery_label"] = payload.get("recovery_label", "未回暖")
        merged["theme_strength"] = 0.0
        merged["market_context_summary"] = market_context_summary(payload)
        merged["stock_theme_alignment"] = _stock_theme_alignment(row, payload)
        result.append(merged)
    return result


def market_context_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a compact read-only market marker for UI and audits."""

    if not payload:
        return {
            "state": "unknown",
            "label": "市场环境未知",
            "severity": "neutral",
            "notes": [],
            "fund_flow_marker": _fund_flow_marker({}),
        }

    regime = str(payload.get("regime") or payload.get("dynamic_market_regime") or "unknown")
    market_label = str(payload.get("label") or payload.get("dynamic_market_label") or "未知")
    warning_level = _safe_float(payload.get("market_warning_level")) or 0.0
    warning_label = str(payload.get("market_warning_label") or "未知")
    recovery_state = str(payload.get("recovery_state") or "none")
    recovery_label = str(payload.get("recovery_label") or "未回暖")
    fund_flow_state = str(payload.get("fund_flow_state") or "unknown")
    fund_flow_label = str(payload.get("fund_flow_label") or "资金未知")
    fund_flow_streak = int(_safe_float(payload.get("fund_flow_streak_days")) or 0)
    source = str(payload.get("fund_flow_source") or payload.get("source") or "")
    breadth = _safe_float(payload.get("breadth_score"))
    if breadth is None:
        breadth = _safe_float(payload.get("market_breadth_score"))

    notes = [market_label] if market_label and market_label != "未知" else []
    if warning_label and warning_label not in {"正常", "未知"}:
        notes.append(warning_label)
    flow_marker = _fund_flow_marker(payload)
    if fund_flow_label and fund_flow_label != "资金未知":
        notes.append(flow_marker["label"])
    if fund_flow_streak >= 3:
        notes.append(f"资金连续流出 {fund_flow_streak} 天")
    if flow_marker.get("note"):
        notes.append(str(flow_marker["note"]))
    if recovery_state != "none" and recovery_label:
        notes.append(recovery_label)
    if source == "stock_fund_flows_partial":
        notes.append("资金流为局部榜单兜底")

    if regime in {"crash", "weak_defensive"} or warning_level >= 3 or fund_flow_state in {"panic_outflow", "continuous_outflow"}:
        return {
            "state": "risk_off",
            "label": "大盘向下/资金防守",
            "severity": "danger" if warning_level >= 4 or fund_flow_state == "panic_outflow" or flow_marker.get("level") == 4 else "warning",
            "notes": _dedupe_notes(notes),
            "fund_flow_marker": flow_marker,
        }
    if warning_level >= 2 or fund_flow_state == "outflow" or (breadth is not None and breadth < 42):
        return {
            "state": "risk_watch",
            "label": "大盘风险观察",
            "severity": "warning",
            "notes": _dedupe_notes(notes),
            "fund_flow_marker": flow_marker,
        }
    if recovery_state in {"warming_confirmed", "stabilizing"}:
        return {
            "state": "warming",
            "label": recovery_label or "市场回暖",
            "severity": "positive",
            "notes": _dedupe_notes(notes),
            "fund_flow_marker": flow_marker,
        }
    if regime == "narrow_theme_bull":
        return {
            "state": "mainline_active",
            "label": "窄牛主线活跃",
            "severity": "positive",
            "notes": _dedupe_notes(notes),
            "fund_flow_marker": flow_marker,
        }
    if regime in {"false_bull", "choppy_rotation"}:
        return {
            "state": "rotation",
            "label": "震荡轮动",
            "severity": "neutral",
            "notes": _dedupe_notes(notes),
            "fund_flow_marker": flow_marker,
        }
    return {
        "state": "neutral",
        "label": market_label if market_label != "未知" else "环境中性",
        "severity": "neutral",
        "notes": _dedupe_notes(notes),
        "fund_flow_marker": flow_marker,
    }


def classify_trading_market_phase(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Map detailed market context into four trading phases for read-only audits."""

    if not payload:
        return {
            "phase": "unknown",
            "label": "行情未知",
            "confidence": 0,
            "position_hint": "等待数据",
            "preferred_setups": [],
            "notes": ["市场画像数据不足"],
            "not_used_for_signal_score": True,
        }

    regime = str(payload.get("regime") or payload.get("dynamic_market_regime") or "unknown")
    warning_level = int(_safe_float(payload.get("market_warning_level")) or 0)
    recovery_state = str(payload.get("recovery_state") or "none")
    fund_flow_state = str(payload.get("fund_flow_state") or "unknown")
    market_score = _safe_float(payload.get("market_score"))
    breadth_score = _safe_float(payload.get("breadth_score"))
    if breadth_score is None:
        breadth_score = _safe_float(payload.get("market_breadth_score"))
    theme_strength = _safe_float(payload.get("theme_strength")) or 0.0
    tide = _market_tide_state(payload)
    notes = []

    if tide["state"] == "retreat" and recovery_state not in {"warming_confirmed", "stabilizing"}:
        phase = "retreat"
        label = "退潮"
        confidence = max(76, int(tide["confidence"]))
        position_hint = "防守/空仓"
        preferred_setups = ["极强低吸首启"]
        notes.append("多指数同步走弱，涨潮线转入退潮")
    elif tide["state"] == "warming":
        phase = "warming"
        label = "回暖"
        confidence = max(72, int(tide["confidence"]))
        position_hint = "小仓试错"
        preferred_setups = ["低吸首启", "低吸+龙回头叠加"]
        notes.append("多指数同步修复，退潮后回暖")
    elif regime in {"crash", "weak_defensive", "risk_off"} or (
        warning_level >= 3 and recovery_state not in {"warming_confirmed", "stabilizing"}
    ):
        phase = "retreat"
        label = "退潮"
        confidence = 86 if warning_level >= 3 or fund_flow_state in {"panic_outflow", "continuous_outflow"} else 76
        position_hint = "防守/空仓"
        preferred_setups = ["极强低吸首启"]
        notes.append("市场风险优先，先控制仓位")
    elif regime in {"weak_rebound"} or (
        recovery_state in {"warming_confirmed", "stabilizing"} and warning_level >= 2
    ):
        phase = "warming"
        label = "回暖"
        confidence = 78 if recovery_state == "warming_confirmed" else 66
        position_hint = "小仓试错"
        preferred_setups = ["低吸首启", "低吸+龙回头叠加"]
        notes.append("退潮后修复，优先看资金承接是否持续")
    elif regime in {"strong_broad", "narrow_theme_bull", "narrow_mainline_bull", "mainline_pullback"}:
        phase = "uptrend"
        label = "主升"
        confidence = 82 if warning_level <= 1 else 68
        position_hint = "积极但不满仓预设"
        preferred_setups = ["主线龙回头", "低吸首启", "低吸+龙回头叠加"]
        notes.append("主升期仍需比较低吸和龙回头的实际胜率")
    elif regime in {"choppy_rotation", "false_bull"}:
        phase = "rotation"
        label = "震荡"
        confidence = 72 if warning_level <= 2 else 60
        position_hint = "中低仓轮动"
        preferred_setups = ["低吸首启", "低吸+龙回头叠加", "新鲜龙回头"]
        notes.append("震荡期不强行持满，重视前排质量")
    else:
        phase = "unknown"
        label = "行情未知"
        confidence = 30
        position_hint = "等待数据"
        preferred_setups = []
        notes.append("行情状态无法稳定识别")

    if fund_flow_state in {"panic_outflow", "continuous_outflow", "outflow"}:
        notes.append("资金流出压力")
    if theme_strength >= 72:
        notes.append("主线热度高")
    if breadth_score is not None and breadth_score < 42:
        notes.append("市场广度偏弱")
    if tide.get("note"):
        notes.append(str(tide["note"]))
    if market_score is not None:
        notes.append(f"市场分 {round(market_score, 1)}")

    return {
        "phase": phase,
        "label": label,
        "confidence": int(max(0, min(100, confidence))),
        "position_hint": position_hint,
        "preferred_setups": preferred_setups,
        "notes": _dedupe_notes(notes),
        "source_regime": regime,
        "market_warning_level": warning_level,
        "recovery_state": recovery_state,
        "fund_flow_state": fund_flow_state,
        "tide_state": tide["state"],
        "tide_score": tide["score"],
        "not_used_for_signal_score": True,
    }


def _market_tide_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Classify visible multi-index tide pressure/recovery.

    This is a read-only overlay for UI/audits. It only uses fields that are
    already computed from bars visible on or before the trade date.
    """

    market_score = _safe_float(payload.get("market_score")) or 50.0
    breadth_score = _safe_float(payload.get("breadth_score"))
    if breadth_score is None:
        breadth_score = _safe_float(payload.get("market_breadth_score"))
    index_return_5d = _safe_float(payload.get("index_return_5d"))
    index_return_20d = _safe_float(payload.get("index_return_20d"))
    growth_score = _safe_float(payload.get("growth_score"))
    value_score = _safe_float(payload.get("value_score"))
    small_cap_score = _safe_float(payload.get("small_cap_score"))
    drawdown = _safe_float(payload.get("drawdown_60d_pct"))
    warning_level = int(_safe_float(payload.get("market_warning_level")) or 0)
    recovery_state = str(payload.get("recovery_state") or "none")
    style_scores = [value for value in [growth_score, value_score, small_cap_score] if value is not None]
    weak_style_count = sum(1 for value in style_scores if value < 46)
    strong_style_count = sum(1 for value in style_scores if value >= 54)

    raw_score = market_score
    if index_return_5d is not None:
        raw_score += index_return_5d * 3.2
    if index_return_20d is not None:
        raw_score += index_return_20d * 1.1
    if breadth_score is not None:
        raw_score += (breadth_score - 50.0) * 0.35
    if style_scores:
        raw_score += (sum(style_scores) / len(style_scores) - 50.0) * 0.28
    if drawdown is not None and drawdown < 0:
        raw_score += max(drawdown, -12.0) * 1.25
    score = round(max(0.0, min(100.0, raw_score)), 2)

    retreat_hits = 0
    if index_return_5d is not None and index_return_5d <= -1.6:
        retreat_hits += 1
    if index_return_20d is not None and index_return_20d <= -2.4:
        retreat_hits += 1
    if breadth_score is not None and breadth_score < 45:
        retreat_hits += 1
    if weak_style_count >= 2:
        retreat_hits += 1
    if market_score < 48:
        retreat_hits += 1
    if warning_level >= 2:
        retreat_hits += 1
    strong_recovery_impulse = (
        index_return_5d is not None
        and index_return_5d >= 5.0
        and strong_style_count >= 2
        and market_score >= 55
    )
    false_bull_distribution = (
        str(payload.get("regime") or payload.get("dynamic_market_regime") or "") == "false_bull"
        and warning_level >= 2
        and breadth_score is not None
        and breadth_score < 40
        and index_return_20d is not None
        and index_return_20d >= 3.0
        and not (
            index_return_5d is not None
            and index_return_5d >= 3.0
            and str(payload.get("fund_flow_state") or "unknown") == "inflow"
        )
        and not strong_recovery_impulse
    )

    warming_hits = 0
    if index_return_5d is not None and index_return_5d >= 1.4:
        warming_hits += 1
    if index_return_5d is not None and index_return_5d >= 3.0:
        warming_hits += 1
    if index_return_20d is not None and index_return_20d > -3.5:
        warming_hits += 1
    if breadth_score is not None and breadth_score >= 48:
        warming_hits += 1
    if strong_style_count >= 2:
        warming_hits += 1
    if market_score >= 53:
        warming_hits += 1
    if recovery_state in {"warming_confirmed", "stabilizing"}:
        warming_hits += 1

    if false_bull_distribution:
        return {
            "state": "retreat",
            "score": min(score, 38.0),
            "confidence": 78,
            "note": "指数高位但广度退潮",
        }
    if retreat_hits >= 3 and warming_hits < 4:
        return {
            "state": "retreat",
            "score": score,
            "confidence": min(92, 58 + retreat_hits * 7),
            "note": f"退潮确认项 {retreat_hits} 个",
        }
    if warming_hits >= 4 and (index_return_5d is None or index_return_5d >= 0):
        return {
            "state": "warming",
            "score": score,
            "confidence": min(90, 54 + warming_hits * 7),
            "note": f"回暖确认项 {warming_hits} 个",
        }
    if score >= 66:
        return {"state": "uptrend", "score": score, "confidence": 70, "note": "市场潮汐偏上"}
    if score <= 38:
        return {"state": "retreat", "score": score, "confidence": 72, "note": "市场潮汐偏下"}
    return {"state": "rotation", "score": score, "confidence": 56, "note": "市场潮汐震荡"}


def _fund_flow_marker(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact read-only fund-flow pressure/recovery marker."""

    state = str(payload.get("fund_flow_state") or "unknown")
    label = str(payload.get("fund_flow_label") or "资金未知")
    score = _safe_float(payload.get("fund_flow_score"))
    streak = int(_safe_float(payload.get("fund_flow_streak_days")) or 0)
    source = str(payload.get("fund_flow_source") or payload.get("source") or "")
    net = _safe_float(payload.get("main_net_inflow"))
    ratio = _safe_float(payload.get("main_net_inflow_ratio"))
    worsening_days = int(
        _safe_float(payload.get("fund_flow_worsening_days"))
        or _safe_float(payload.get("outflow_worsening_days"))
        or 0
    )
    new_low = bool(payload.get("fund_flow_new_low") or payload.get("outflow_new_low"))
    recovery_from_streak = int(
        _safe_float(payload.get("fund_flow_recovery_from_streak_days"))
        or _safe_float(payload.get("recovery_from_outflow_streak_days"))
        or 0
    )

    severity = "neutral"
    level = 0
    note = ""
    trend = "neutral"
    trend_label = ""
    if state == "panic_outflow":
        severity = "danger"
        level = 4
        note = "资金明显外逃"
        trend = "worsening"
        trend_label = "资金外逃"
    elif state == "continuous_outflow":
        severity = "warning"
        level = 3
        note = f"连续流出 {streak} 天" if streak else "资金连续流出"
        trend = "outflow"
        trend_label = "连续流出"
    elif state == "outflow":
        severity = "warning"
        level = 2
        note = "资金净流出"
        trend = "outflow"
        trend_label = "资金流出"
    elif state == "inflow":
        severity = "positive"
        level = 0
        note = "资金回流"
        trend = "recovery"
        trend_label = "资金回流"
    elif state == "balanced":
        severity = "neutral"
        level = 1
        note = "资金平衡"
        trend = "balanced"
        trend_label = "资金平衡"

    if state in {"outflow", "continuous_outflow", "panic_outflow"} and (new_low or worsening_days >= 2):
        severity = "danger" if streak >= 3 or state == "panic_outflow" else "warning"
        level = max(level, 4 if severity == "danger" else 3)
        trend = "worsening"
        trend_label = "流出扩大"
        note = f"连续流出 {streak} 天且流出扩大" if streak else "资金流出扩大"
    elif state == "inflow" and recovery_from_streak >= 3:
        note = f"连续流出 {recovery_from_streak} 天后资金回流"

    if source == "stock_fund_flows_partial" and label != "资金未知":
        label = label if label.startswith("局部") else f"局部{label}"
    return {
        "state": state,
        "label": label,
        "severity": severity,
        "level": level,
        "score": round(score, 4) if score is not None else None,
        "streak_days": streak,
        "worsening_days": worsening_days,
        "new_low": new_low,
        "recovery_from_streak_days": recovery_from_streak,
        "trend": trend,
        "trend_label": trend_label,
        "source": source or None,
        "main_net_inflow": net,
        "main_net_inflow_ratio": ratio,
        "note": note,
    }


def _fund_flow_state_from_audit_payload(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("fund_flow_state") or "").strip()
    if explicit:
        if explicit == "inflow":
            return "recovery"
        if explicit == "unknown":
            return "insufficient_data"
        return explicit
    if payload.get("fund_flow_source") in {None, "", "unknown"}:
        return "insufficient_data"
    net_ratio = _safe_float(payload.get("main_net_inflow_ratio"))
    outflow_streak = int(_safe_float(payload.get("fund_flow_streak_days") or payload.get("outflow_streak_days")) or 0)
    if net_ratio is None:
        return "insufficient_data"
    if net_ratio <= -8:
        return "panic_outflow"
    if net_ratio < 0:
        return "outflow" if outflow_streak < 3 else "panic_outflow"
    if net_ratio >= 3:
        return "recovery"
    return "balanced"


def _dedupe_notes(notes: list[str]) -> list[str]:
    result = []
    seen = set()
    for note in notes:
        text = str(note or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _benchmark_proxy_context(row: dict[str, Any]) -> dict[str, Any]:
    benchmark_return = _safe_float(row.get("benchmark_return_pct"))
    if benchmark_return is None:
        return {
            "regime": "unknown",
            "label": "未知",
            "market_score": 50.0,
            "risk_score": 50.0,
            "market_warning_level": 0,
            "market_warning_label": "未知",
            "recovery_state": "none",
            "recovery_label": "未回暖",
        }
    if benchmark_return <= -8.0:
        return {
            "regime": "crash",
            "label": _dynamic_regime_labels()["crash"],
            "market_score": max(10.0, 35.0 + benchmark_return),
            "risk_score": min(95.0, 70.0 + abs(benchmark_return) * 2),
            "market_warning_level": 4,
            "market_warning_label": "极端风险",
            "recovery_state": "none",
            "recovery_label": "未回暖",
        }
    if benchmark_return <= -3.0:
        return {
            "regime": "weak_defensive",
            "label": _dynamic_regime_labels()["weak_defensive"],
            "market_score": max(20.0, 45.0 + benchmark_return),
            "risk_score": min(88.0, 58.0 + abs(benchmark_return) * 2),
            "market_warning_level": 3,
            "market_warning_label": "强风险",
            "recovery_state": "none",
            "recovery_label": "未回暖",
        }
    if benchmark_return >= 5.0:
        return {
            "regime": "strong_broad",
            "label": _dynamic_regime_labels()["strong_broad"],
            "market_score": min(90.0, 64.0 + benchmark_return * 2),
            "risk_score": max(20.0, 42.0 - benchmark_return),
            "market_warning_level": 0,
            "market_warning_label": "正常",
            "recovery_state": "warming_confirmed",
            "recovery_label": "回暖确认",
        }
    return {
        "regime": "choppy_rotation",
        "label": _dynamic_regime_labels()["choppy_rotation"],
        "market_score": 50.0 + benchmark_return,
        "risk_score": 50.0 - benchmark_return,
        "market_warning_level": 1 if benchmark_return < 0 else 0,
        "market_warning_label": "窄幅分歧" if benchmark_return < 0 else "正常",
        "recovery_state": "stabilizing" if benchmark_return >= 0 else "none",
        "recovery_label": "止跌观察" if benchmark_return >= 0 else "未回暖",
    }


def _has_index_context(session: Any, schema: Any, trade_dates: list[date]) -> bool:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
        return False
    if not hasattr(session, "execute"):
        return False
    vt_symbols = [f"{item['symbol']}.{item['exchange']}" for item in INDEX_SYMBOLS]
    count = session.execute(
        select(func.count())
        .select_from(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols))
        .where(schema.stock_daily_bars.c.trade_date >= dates[0] - timedelta(days=80))
        .where(schema.stock_daily_bars.c.trade_date <= dates[-1])
    ).scalar_one()
    return int(count or 0) >= 60


def summarize_contexts(
    rows: list[dict[str, Any]],
    *,
    return_key: str,
    excess_key: str,
    evaluated_predicate,
) -> list[dict[str, Any]]:
    result = []
    labels = _dynamic_regime_labels()
    for regime in labels:
        bucket = [row for row in rows if str(row.get("dynamic_market_regime") or "unknown") == regime]
        if not bucket:
            continue
        evaluated = [row for row in bucket if evaluated_predicate(row)]
        result.append(
            {
                "regime": regime,
                "label": labels[regime],
                "candidate_count": len(bucket),
                "evaluated_count": len(evaluated),
                "win_rate": _ratio(
                    len([row for row in evaluated if (_safe_float(row.get(return_key)) or 0) > 0]),
                    len(evaluated),
                ),
                "avg_return_pct": _avg_optional(row.get(return_key) for row in evaluated),
                "avg_excess_return_pct": _avg_optional(row.get(excess_key) for row in evaluated),
                "avg_market_score": _avg_optional(row.get("market_score") for row in bucket),
                "avg_breadth_score": _avg_optional(row.get("market_breadth_score") for row in bucket),
                "avg_risk_score": _avg_optional(row.get("market_risk_score") for row in bucket),
            }
        )
    return result


def _build_context(
    trade_date: date,
    index_bars: dict[str, list[dict[str, Any]]],
    breadth_by_date: dict[date, dict[str, float]],
    sector_scores: list[dict[str, Any]],
    fund_flows: dict[date, dict[str, Any]],
) -> MarketContext:
    index_features = [_index_feature(symbol, bars, trade_date) for symbol, bars in index_bars.items()]
    index_features = [feature for feature in index_features if feature]
    breadth = breadth_by_date.get(trade_date) or _neutral_breadth()
    theme = _dominant_theme(sector_scores, trade_date)
    trend_score = _weighted_index_score(index_features, "trend_score")
    momentum_score = _weighted_index_score(index_features, "momentum_score")
    volatility_score = _weighted_index_score(index_features, "volatility_score")
    drawdown_score = _weighted_index_score(index_features, "drawdown_score")
    breadth_score = breadth.get("breadth_score")
    risk_score = max(0.0, min(100.0, (drawdown_score * 0.45 + volatility_score * 0.35 + (100 - breadth_score) * 0.20)))
    theme_strength = _safe_float(theme.get("heat_score")) or 0.0
    market_score = max(0.0, min(100.0, trend_score * 0.32 + momentum_score * 0.28 + breadth_score * 0.24 + theme_strength * 0.16))
    growth_score = _style_score(index_features, GROWTH_INDEXES)
    value_score = _style_score(index_features, VALUE_INDEXES)
    small_cap_score = _style_score(index_features, {"000852.SSE", "000905.SSE"})
    fund_flow = _fund_flow_snapshot(fund_flows, trade_date)
    fund_flow_source = str(fund_flow.get("fund_flow_source") or "") or None
    partial_fund_flow = fund_flow_source == "stock_fund_flows_partial"
    fund_flow_state, fund_flow_label = _fund_flow_state(
        fund_flow_score=_safe_float(fund_flow.get("fund_flow_score")),
        main_net_inflow=_safe_float(fund_flow.get("main_net_inflow")),
        main_net_inflow_ratio=_safe_float(fund_flow.get("main_net_inflow_ratio")),
        outflow_streak=int(fund_flow.get("outflow_streak_days") or 0),
    )
    if partial_fund_flow and fund_flow_label != "资金未知":
        fund_flow_label = f"局部{fund_flow_label}"
    index_return_5d = _weighted_index_return(index_features, "return_5d")
    index_return_20d = _weighted_index_return(index_features, "return_20d")
    drawdown_60d_pct = _weighted_index_return(index_features, "drawdown_60d_pct")
    regime, notes = _classify_dynamic_regime(
        market_score=market_score,
        trend_score=trend_score,
        momentum_score=momentum_score,
        breadth_score=breadth_score,
        risk_score=risk_score,
        theme_strength=theme_strength,
        growth_score=growth_score,
        value_score=value_score,
    )
    theme_state = _theme_state(theme_strength, breadth_score, risk_score, regime)
    warning_level, warning_label = _market_warning(
        regime=regime,
        risk_score=risk_score,
        trend_score=trend_score,
        breadth_score=breadth_score,
        fund_flow_state="balanced" if partial_fund_flow else fund_flow_state,
        outflow_streak=0 if partial_fund_flow else int(fund_flow.get("outflow_streak_days") or 0),
        drawdown_60d_pct=drawdown_60d_pct,
        index_return_20d=index_return_20d,
    )
    recovery_state, recovery_label = _recovery_state(
        trend_score=trend_score,
        momentum_score=momentum_score,
        breadth_score=breadth_score,
        risk_score=risk_score,
        fund_flow_state="balanced" if partial_fund_flow else fund_flow_state,
        fund_flow_score=None if partial_fund_flow else _safe_float(fund_flow.get("fund_flow_score")),
        index_return_5d=index_return_5d,
    )
    context_notes = list(notes)
    if fund_flow_state in {"continuous_outflow", "panic_outflow"}:
        context_notes.append(fund_flow_label)
    if partial_fund_flow:
        context_notes.append("个股资金流为局部榜单兜底，不能代表全市场资金流")
    if recovery_state != "none":
        context_notes.append(recovery_label)
    return MarketContext(
        trade_date=trade_date,
        regime=regime,
        label=_dynamic_regime_labels().get(regime, "未知"),
        dominant_theme=theme.get("sector_name"),
        dominant_theme_id=theme.get("sector_id"),
        theme_state=theme_state,
        market_score=round(market_score, 4),
        trend_score=round(trend_score, 4),
        momentum_score=round(momentum_score, 4),
        breadth_score=round(breadth_score, 4),
        risk_score=round(risk_score, 4),
        volatility_score=round(volatility_score, 4),
        theme_strength=round(theme_strength, 4),
        theme_breadth=_safe_float(theme.get("breadth_score")),
        growth_score=round(growth_score, 4) if growth_score is not None else None,
        value_score=round(value_score, 4) if value_score is not None else None,
        small_cap_score=round(small_cap_score, 4) if small_cap_score is not None else None,
        index_return_5d=round(index_return_5d, 4) if index_return_5d is not None else None,
        index_return_20d=round(index_return_20d, 4) if index_return_20d is not None else None,
        drawdown_60d_pct=round(drawdown_60d_pct, 4) if drawdown_60d_pct is not None else None,
        fund_flow_state=fund_flow_state,
        fund_flow_label=fund_flow_label,
        fund_flow_score=round(float(fund_flow["fund_flow_score"]), 4) if fund_flow.get("fund_flow_score") is not None else None,
        fund_flow_streak_days=int(fund_flow.get("outflow_streak_days") or 0),
        fund_flow_source=fund_flow_source,
        main_net_inflow=_safe_float(fund_flow.get("main_net_inflow")),
        main_net_inflow_ratio=_safe_float(fund_flow.get("main_net_inflow_ratio")),
        fund_flow_worsening_days=int(fund_flow.get("outflow_worsening_days") or 0),
        fund_flow_new_low=bool(fund_flow.get("outflow_new_low")),
        fund_flow_recovery_from_streak_days=int(fund_flow.get("recovery_from_outflow_streak_days") or 0),
        market_warning_level=warning_level,
        market_warning_label=warning_label,
        recovery_state=recovery_state,
        recovery_label=recovery_label,
        source=DEFAULT_CONTEXT_SOURCE,
        notes=context_notes,
    )


def _load_index_bars(session: Any, schema: Any, start: date, end: date) -> dict[str, list[dict[str, Any]]]:
    vt_symbols = [f"{item['symbol']}.{item['exchange']}" for item in INDEX_SYMBOLS]
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols))
        .where(schema.stock_daily_bars.c.trade_date >= start)
        .where(schema.stock_daily_bars.c.trade_date <= end)
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row["vt_symbol"])].append(dict(row))
    return result


def _load_market_breadth_by_date(
    session: Any,
    schema: Any,
    start: date,
    end: date,
    trade_dates: list[date],
) -> dict[date, dict[str, float]]:
    target_dates = sorted({day for day in trade_dates if day})
    if not target_dates:
        return {}
    cached = _cached_market_breadth(start, end)
    if cached is not None:
        return {day: cached.get(day, _neutral_breadth()) for day in target_dates}

    table = schema.stock_daily_bars
    excluded_symbols = [f"{item['symbol']}.{item['exchange']}" for item in INDEX_SYMBOLS]
    rows = session.execute(
        select(
            table.c.vt_symbol,
            table.c.trade_date,
            table.c.close_price,
        )
        .where(table.c.trade_date >= start)
        .where(table.c.trade_date <= end)
        .where(~table.c.vt_symbol.in_(excluded_symbols))
        .order_by(table.c.vt_symbol, table.c.trade_date)
    ).all()
    breadth = _market_breadth_from_close_rows(rows)
    _store_market_breadth(start, end, breadth)
    return {day: breadth.get(day, _neutral_breadth()) for day in target_dates}


def _cached_market_breadth(start: date, end: date) -> dict[date, dict[str, float]] | None:
    with _BREADTH_CACHE_LOCK:
        for index, (cached_start, cached_end, values) in enumerate(_BREADTH_CACHE):
            if cached_start <= start and cached_end >= end:
                _BREADTH_CACHE.insert(0, _BREADTH_CACHE.pop(index))
                return values
    return None


def _store_market_breadth(start: date, end: date, values: dict[date, dict[str, float]]) -> None:
    with _BREADTH_CACHE_LOCK:
        _BREADTH_CACHE.insert(0, (start, end, values))
        del _BREADTH_CACHE[_BREADTH_CACHE_MAX_ENTRIES:]


def _market_breadth_from_close_rows(rows: list[Any]) -> dict[date, dict[str, float]]:
    counts: dict[date, dict[str, int]] = defaultdict(lambda: {"total": 0, "above20": 0, "above60": 0, "rising": 0})
    current_symbol: str | None = None
    window20: deque[float] = deque()
    window60: deque[float] = deque()
    sum20 = 0.0
    sum60 = 0.0
    previous_close: float | None = None

    for row in rows:
        vt_symbol = str(row[0])
        trade_date = row[1]
        close_price = _safe_float(row[2])
        if close_price is None:
            continue
        if vt_symbol != current_symbol:
            current_symbol = vt_symbol
            window20 = deque()
            window60 = deque()
            sum20 = 0.0
            sum60 = 0.0
            previous_close = None

        window20.append(close_price)
        sum20 += close_price
        if len(window20) > 20:
            sum20 -= window20.popleft()
        window60.append(close_price)
        sum60 += close_price
        if len(window60) > 60:
            sum60 -= window60.popleft()

        if len(window20) >= 20:
            day_counts = counts[trade_date]
            day_counts["total"] += 1
            if close_price >= sum20 / len(window20):
                day_counts["above20"] += 1
            if len(window60) >= 60 and close_price >= sum60 / len(window60):
                day_counts["above60"] += 1
            if previous_close is not None and close_price > previous_close:
                day_counts["rising"] += 1
        previous_close = close_price

    return {trade_date: _breadth_from_counts(day_counts) for trade_date, day_counts in counts.items()}


def _load_sector_scores(session: Any, schema: Any, start: date, end: date) -> list[dict[str, Any]]:
    if not hasattr(schema, "sector_period_scores"):
        return []
    rows = session.execute(
        select(schema.sector_period_scores, schema.sectors.c.name.label("sector_name"))
        .join(schema.sectors, schema.sectors.c.id == schema.sector_period_scores.c.sector_id)
        .where(schema.sector_period_scores.c.as_of_date >= start)
        .where(schema.sector_period_scores.c.as_of_date <= end)
        .where(schema.sector_period_scores.c.period == "20d")
        .order_by(schema.sector_period_scores.c.as_of_date, desc(schema.sector_period_scores.c.heat_score))
    ).mappings().all()
    return [dict(row) for row in rows]


def _load_fund_flows_by_date(session: Any, schema: Any, start: date, end: date) -> dict[date, dict[str, Any]]:
    sector_flows = _load_sector_fund_flows_by_date(session, schema, start, end)
    if sector_flows:
        return sector_flows
    return _load_stock_fund_flows_by_date(session, schema, start, end)


def _load_sector_fund_flows_by_date(session: Any, schema: Any, start: date, end: date) -> dict[date, dict[str, Any]]:
    if not hasattr(schema, "sector_fund_flows"):
        return {}
    rows = session.execute(
        select(
            schema.sector_fund_flows.c.trade_date,
            func.sum(schema.sector_fund_flows.c.main_net_inflow).label("main_net_inflow"),
            func.avg(schema.sector_fund_flows.c.main_net_inflow_ratio).label("main_net_inflow_ratio"),
            func.count().label("sector_count"),
        )
        .where(schema.sector_fund_flows.c.trade_date >= start.isoformat())
        .where(schema.sector_fund_flows.c.trade_date <= end.isoformat())
        .where(schema.sector_fund_flows.c.period.in_(["即时", "今日", "1日"]))
        .group_by(schema.sector_fund_flows.c.trade_date)
        .order_by(schema.sector_fund_flows.c.trade_date)
    ).mappings().all()
    return _fund_flow_payloads_from_rows(rows, source="sector_fund_flows")


def _load_stock_fund_flows_by_date(session: Any, schema: Any, start: date, end: date) -> dict[date, dict[str, Any]]:
    if not hasattr(schema, "stock_fund_flows"):
        return {}
    rows = session.execute(
        select(
            schema.stock_fund_flows.c.trade_date,
            func.sum(schema.stock_fund_flows.c.main_net_inflow).label("main_net_inflow"),
            func.avg(schema.stock_fund_flows.c.main_net_inflow_ratio).label("main_net_inflow_ratio"),
            func.count().label("stock_count"),
        )
        .where(schema.stock_fund_flows.c.trade_date >= start.isoformat())
        .where(schema.stock_fund_flows.c.trade_date <= end.isoformat())
        .where(schema.stock_fund_flows.c.period.in_(["即时", "今日", "1日"]))
        .group_by(schema.stock_fund_flows.c.trade_date)
        .order_by(schema.stock_fund_flows.c.trade_date)
    ).mappings().all()
    return _fund_flow_payloads_from_rows(rows, source="stock_fund_flows_partial")


def _fund_flow_payloads_from_rows(rows: list[dict[str, Any]], *, source: str) -> dict[date, dict[str, Any]]:
    dated: list[tuple[date, dict[str, Any]]] = []
    for row in rows:
        trade_date = _parse_date(row.get("trade_date"))
        if trade_date is None:
            continue
        net = _safe_float(row.get("main_net_inflow"))
        ratio = _safe_float(row.get("main_net_inflow_ratio"))
        score = _flow_score(net, ratio)
        dated.append(
            (
                trade_date,
                {
                    "main_net_inflow": net,
                    "main_net_inflow_ratio": ratio,
                    "fund_flow_score": score,
                    "fund_flow_source": source,
                    "sector_count": int(row.get("sector_count") or 0),
                    "stock_count": int(row.get("stock_count") or 0),
                },
            )
        )
    result: dict[date, dict[str, Any]] = {}
    streak = 0
    worsening_days = 0
    streak_min_score: float | None = None
    previous_score: float | None = None
    for trade_date, payload in dated:
        score = _safe_float(payload.get("fund_flow_score"))
        if score is not None and score < 45:
            previous_min = streak_min_score
            previous = previous_score
            streak += 1
            is_new_low = previous_min is not None and score < previous_min - 0.5
            is_worsening = previous is not None and score < previous - 2.0
            if is_new_low or is_worsening:
                worsening_days += 1
            else:
                worsening_days = 0
            streak_min_score = score if previous_min is None else min(previous_min, score)
            payload["outflow_new_low"] = bool(streak > 1 and is_new_low)
            payload["outflow_worsening_days"] = worsening_days
            payload["recovery_from_outflow_streak_days"] = 0
        elif score is not None and score >= 52:
            payload["recovery_from_outflow_streak_days"] = streak
            streak = 0
            worsening_days = 0
            streak_min_score = None
            payload["outflow_new_low"] = False
            payload["outflow_worsening_days"] = 0
        else:
            payload["outflow_new_low"] = False
            payload["outflow_worsening_days"] = worsening_days
            payload["recovery_from_outflow_streak_days"] = 0
        payload["outflow_streak_days"] = streak
        result[trade_date] = payload
        if score is not None:
            previous_score = score
    return result


def _fund_flow_snapshot(fund_flows: dict[date, dict[str, Any]], trade_date: date) -> dict[str, Any]:
    if not fund_flows:
        return {}
    candidates = [day for day in fund_flows if day <= trade_date]
    if not candidates:
        return {}
    return dict(fund_flows[max(candidates)])


def _flow_score(main_net_inflow: float | None, main_net_inflow_ratio: float | None) -> float | None:
    if main_net_inflow is None and main_net_inflow_ratio is None:
        return None
    ratio_score = None
    if main_net_inflow_ratio is not None:
        ratio_score = _clamp(50.0 + main_net_inflow_ratio * 2.4)
    amount_score = None
    if main_net_inflow is not None:
        amount_score = _clamp(50.0 + main_net_inflow / 20_000_000_000 * 25.0)
    if ratio_score is not None and amount_score is not None:
        return ratio_score * 0.65 + amount_score * 0.35
    return ratio_score if ratio_score is not None else amount_score


def _fund_flow_state(
    *,
    fund_flow_score: float | None,
    main_net_inflow: float | None,
    main_net_inflow_ratio: float | None,
    outflow_streak: int,
) -> tuple[str, str]:
    if fund_flow_score is None:
        return "unknown", "资金未知"
    if fund_flow_score <= 25 or (main_net_inflow is not None and main_net_inflow < -35_000_000_000) or outflow_streak >= 5:
        return "panic_outflow", "恐慌流出"
    if outflow_streak >= 3 or fund_flow_score <= 38:
        return "continuous_outflow", "连续流出"
    if fund_flow_score < 48 or (main_net_inflow_ratio is not None and main_net_inflow_ratio < -1.0):
        return "outflow", "资金流出"
    if fund_flow_score >= 62:
        return "inflow", "资金流入"
    return "balanced", "资金平衡"


def _market_warning(
    *,
    regime: str,
    risk_score: float,
    trend_score: float,
    breadth_score: float,
    fund_flow_state: str,
    outflow_streak: int,
    drawdown_60d_pct: float | None,
    index_return_20d: float | None,
) -> tuple[int, str]:
    level = 0
    if regime in {"weak_defensive", "crash"}:
        level = max(level, 2)
    if regime == "crash" or risk_score >= 78:
        level = max(level, 4)
    elif risk_score >= 68 or trend_score < 42 or breadth_score < 30:
        level = max(level, 3)
    elif risk_score >= 58 or breadth_score < 42:
        level = max(level, 2)
    if fund_flow_state == "panic_outflow":
        level = max(level, 4)
    elif fund_flow_state == "continuous_outflow":
        level = max(level, 3)
    elif fund_flow_state == "outflow":
        level = max(level, 2)
    if outflow_streak >= 5:
        level = max(level, 4)
    elif outflow_streak >= 3:
        level = max(level, 3)
    if drawdown_60d_pct is not None and drawdown_60d_pct <= -8:
        level = max(level, 3)
    if index_return_20d is not None and index_return_20d <= -6:
        level = max(level, 3)
    labels = {
        0: "正常",
        1: "窄幅分歧",
        2: "风险",
        3: "强风险",
        4: "极端风险",
    }
    return level, labels[level]


def _recovery_state(
    *,
    trend_score: float,
    momentum_score: float,
    breadth_score: float,
    risk_score: float,
    fund_flow_state: str,
    fund_flow_score: float | None,
    index_return_5d: float | None,
) -> tuple[str, str]:
    if fund_flow_state in {"panic_outflow", "continuous_outflow"}:
        return "none", "未回暖"
    if risk_score <= 48 and breadth_score >= 55 and momentum_score >= 54:
        return "warming_confirmed", "回暖确认"
    if fund_flow_state == "inflow" and index_return_5d is not None and index_return_5d >= 0:
        return "warming_confirmed", "资金回流"
    if fund_flow_score is not None and fund_flow_score >= 52 and index_return_5d is not None and index_return_5d >= -1.0:
        return "stabilizing", "止跌观察"
    if trend_score >= 52 and breadth_score >= 45 and risk_score < 62:
        return "stabilizing", "止跌观察"
    return "none", "未回暖"


def _index_feature(symbol: str, bars: list[dict[str, Any]], trade_date: date) -> dict[str, Any] | None:
    visible = [row for row in bars if row["trade_date"] <= trade_date]
    if len(visible) < 60:
        return None
    closes = [float(row["close_price"]) for row in visible]
    latest = closes[-1]
    ma20 = _avg(closes[-20:])
    ma60 = _avg(closes[-60:])
    ret5 = _period_return(closes, 5)
    ret20 = _period_return(closes, 20)
    ret60 = _period_return(closes, 60)
    high60 = max(closes[-60:])
    dd60 = (latest / high60 - 1) * 100 if high60 else 0.0
    returns20 = [closes[index] / closes[index - 1] - 1 for index in range(len(closes) - 19, len(closes)) if closes[index - 1]]
    vol20 = pstdev(returns20) * 100 if len(returns20) > 1 else 0.0
    trend_score = 50.0
    if ma20 and latest >= ma20:
        trend_score += 18
    if ma60 and latest >= ma60:
        trend_score += 18
    if len(closes) >= 25 and ma20 and _avg(closes[-25:-5]) and ma20 >= _avg(closes[-25:-5]):
        trend_score += 8
    momentum_score = 50.0 + (ret20 or 0) * 3.0 + (ret60 or 0) * 1.2 + (ret5 or 0) * 2.0
    drawdown_score = min(max(abs(dd60) * 5.0, 0.0), 100.0)
    volatility_score = min(max(vol20 * 14.0, 0.0), 100.0)
    return {
        "symbol": symbol,
        "trend_score": _clamp(trend_score),
        "momentum_score": _clamp(momentum_score),
        "drawdown_score": drawdown_score,
        "volatility_score": volatility_score,
        "return_5d": ret5,
        "return_20d": ret20,
        "return_60d": ret60,
        "drawdown_60d_pct": dd60,
    }


def _breadth_from_counts(counts: dict[str, int]) -> dict[str, float]:
    total = counts.get("total") or 0
    if not total:
        return _neutral_breadth()
    above20_pct = counts.get("above20", 0) / total * 100
    above60_pct = counts.get("above60", 0) / total * 100
    rising_pct = counts.get("rising", 0) / total * 100
    breadth_score = above20_pct * 0.45 + above60_pct * 0.35 + rising_pct * 0.20
    return {
        "breadth_score": _clamp(breadth_score),
        "above20_pct": above20_pct,
        "above60_pct": above60_pct,
        "rising_pct": rising_pct,
    }


def _neutral_breadth() -> dict[str, float]:
    return {"breadth_score": 50.0, "above20_pct": 0.0, "above60_pct": 0.0, "rising_pct": 0.0}


def _dominant_theme(rows: list[dict[str, Any]], trade_date: date) -> dict[str, Any]:
    candidates = [row for row in rows if row.get("as_of_date") == trade_date]
    if not candidates:
        candidates = [row for row in rows if row.get("as_of_date") and row.get("as_of_date") <= trade_date]
    if not candidates:
        return {}
    by_sector: dict[str, dict[str, Any]] = {}
    for row in sorted(candidates, key=lambda item: (item.get("as_of_date"), item.get("heat_score") or 0), reverse=True):
        sector_id = str(row.get("sector_id") or "")
        if sector_id and sector_id not in by_sector:
            by_sector[sector_id] = row
    ranked = sorted(by_sector.values(), key=lambda item: float(item.get("heat_score") or 0), reverse=True)
    if not ranked:
        return {}
    top = dict(ranked[0])
    return {
        "sector_id": top.get("sector_id"),
        "sector_name": top.get("sector_name") or top.get("sector_id"),
        "heat_score": _safe_float(top.get("heat_score")) or 0.0,
        "breadth_score": _safe_float(top.get("breadth_score")),
        "return_pct": _safe_float(top.get("return_pct")),
    }


def _classify_dynamic_regime(
    *,
    market_score: float,
    trend_score: float,
    momentum_score: float,
    breadth_score: float,
    risk_score: float,
    theme_strength: float,
    growth_score: float | None,
    value_score: float | None,
) -> tuple[str, list[str]]:
    notes = []
    if risk_score >= 78 and trend_score < 42:
        return "crash", ["指数破位且波动/回撤风险高"]
    if market_score < 42 and trend_score < 45:
        return "weak_defensive", ["宽基趋势弱，风险预算应收缩"]
    if market_score >= 66 and breadth_score >= 58:
        return "strong_broad", ["宽基和市场广度同步走强"]
    if theme_strength >= 72 and breadth_score < 52:
        if growth_score is not None and value_score is not None and growth_score - value_score >= 10:
            return "narrow_theme_bull", ["成长/小盘主线强于宽基，市场广度偏窄"]
        return "narrow_theme_bull", ["主线热度高但扩散不足"]
    if trend_score >= 58 and breadth_score < 42:
        return "false_bull", ["指数趋势尚可但市场广度差"]
    if 42 <= market_score <= 66:
        return "choppy_rotation", ["市场处于震荡轮动，需看新主线确认"]
    return "choppy_rotation", notes or ["市场无单边趋势，按轮动处理"]


def _theme_state(theme_strength: float, breadth_score: float, risk_score: float, regime: str) -> str:
    if regime == "crash":
        return "risk_off"
    if theme_strength >= 72 and risk_score < 70:
        return "active"
    if theme_strength >= 62 and breadth_score < 50:
        return "active_pullback"
    if theme_strength >= 55:
        return "emerging"
    return "none"


def _load_stock_theme_memberships(
    session: Any,
    schema: Any,
    rows: list[dict[str, Any]],
    contexts: dict[date, MarketContext],
) -> set[tuple[str, str]]:
    if not hasattr(schema, "stock_sector_memberships"):
        return set()
    symbols = sorted({str(row.get("vt_symbol") or "") for row in rows if row.get("vt_symbol")})
    theme_ids = sorted({str(context.dominant_theme_id or "") for context in contexts.values() if context.dominant_theme_id})
    if not symbols or not theme_ids:
        return set()
    matches = session.execute(
        select(
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stock_sector_memberships.c.sector_id,
        )
        .where(schema.stock_sector_memberships.c.vt_symbol.in_(symbols))
        .where(schema.stock_sector_memberships.c.sector_id.in_(theme_ids))
    ).mappings().all()
    return {(str(row["vt_symbol"]), str(row["sector_id"])) for row in matches}


def _stock_theme_alignment(row: dict[str, Any], context: dict[str, Any], exact_theme_member: bool = False) -> str:
    if exact_theme_member:
        return "leader_theme"
    reason = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    evidence = reason.get("evidence") if isinstance(reason.get("evidence"), dict) else reason
    sector_score = None
    if isinstance(evidence, dict):
        for key in ("sector_score", "sector_mainline_score", "smart_money_proxy_score"):
            sector_score = _safe_float(evidence.get(key))
            if sector_score is not None:
                break
    if sector_score is None:
        sector_score = _safe_float(row.get("sector_mainline_score"))
    if sector_score is not None and sector_score >= 72:
        return "leader_theme"
    if sector_score is not None and sector_score >= 58:
        return "theme_related"
    if context.get("regime") in {"weak_defensive", "crash"}:
        return "isolated_candidate"
    return "unknown"


def _weighted_index_score(features: list[dict[str, Any]], key: str) -> float:
    if not features:
        return 50.0
    weighted = []
    weights = []
    for feature in features:
        symbol = str(feature["symbol"])
        weight = INDEX_WEIGHTS.get(symbol, 0.08)
        weighted.append(float(feature.get(key) or 50.0) * weight)
        weights.append(weight)
    return sum(weighted) / sum(weights) if weights else 50.0


def _weighted_index_return(features: list[dict[str, Any]], key: str) -> float | None:
    if not features:
        return None
    weighted = []
    weights = []
    for feature in features:
        value = _safe_float(feature.get(key))
        if value is None:
            continue
        symbol = str(feature["symbol"])
        weight = INDEX_WEIGHTS.get(symbol, 0.08)
        weighted.append(value * weight)
        weights.append(weight)
    return sum(weighted) / sum(weights) if weights else None


def _style_score(features: list[dict[str, Any]], symbols: set[str]) -> float | None:
    selected = [feature for feature in features if str(feature.get("symbol")) in symbols]
    if not selected:
        return None
    return mean(float(feature.get("momentum_score") or 50.0) for feature in selected)


def _period_return(values: list[float], days: int) -> float | None:
    if len(values) <= days or not values[-days - 1]:
        return None
    return (values[-1] / values[-days - 1] - 1) * 100


def _dynamic_regime_labels() -> dict[str, str]:
    return {
        "strong_broad": "普涨强势",
        "narrow_theme_bull": "窄幅主线牛",
        "choppy_rotation": "震荡轮动",
        "weak_defensive": "弱势防守",
        "crash": "快速杀跌",
        "false_bull": "假强势",
        "unknown": "未知",
    }


def _fallback_context(trade_date: date) -> MarketContext:
    return MarketContext(
        trade_date=trade_date,
        regime="unknown",
        label="未知",
        dominant_theme=None,
        dominant_theme_id=None,
        theme_state="none",
        market_score=50.0,
        trend_score=50.0,
        momentum_score=50.0,
        breadth_score=50.0,
        risk_score=50.0,
        volatility_score=50.0,
        theme_strength=0.0,
        theme_breadth=None,
        growth_score=None,
        value_score=None,
        small_cap_score=None,
        index_return_5d=None,
        index_return_20d=None,
        drawdown_60d_pct=None,
        fund_flow_state="unknown",
        fund_flow_label="资金未知",
        fund_flow_score=None,
        fund_flow_streak_days=0,
        fund_flow_source=None,
        main_net_inflow=None,
        main_net_inflow_ratio=None,
        fund_flow_worsening_days=0,
        fund_flow_new_low=False,
        fund_flow_recovery_from_streak_days=0,
        market_warning_level=0,
        market_warning_label="未知",
        recovery_state="none",
        recovery_label="未回暖",
        source="fallback",
        notes=["市场画像数据不足"],
    )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            from datetime import datetime

            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _avg(values) -> float:
    parsed = [_safe_float(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return sum(parsed) / len(parsed) if parsed else 0.0


def _avg_optional(values) -> float | None:
    parsed = [_safe_float(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return sum(parsed) / len(parsed) if parsed else None


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
