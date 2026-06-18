"""Market and theme context snapshots for quant audits.

The first version is intentionally read-only: it classifies market conditions
from data visible on or before the trade date, and does not alter strategy
orders or scores.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import and_, case, desc, func, select

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
            "source": self.source,
            "notes": self.notes,
        }


def market_context_for_date(session: Any, schema: Any, trade_date: date) -> dict[str, Any]:
    return compute_market_contexts(session, schema, [trade_date]).get(trade_date, _fallback_context(trade_date)).to_dict()


def compute_market_contexts(session: Any, schema: Any, trade_dates: list[date]) -> dict[date, MarketContext]:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
        return {}
    start = dates[0] - timedelta(days=420)
    end = dates[-1]
    index_bars = _load_index_bars(session, schema, start, end)
    breadth_by_date = _load_market_breadth_by_date(session, schema, dates[0] - timedelta(days=180), end, dates)
    sector_scores = _load_sector_scores(session, schema, start, end)
    contexts: dict[date, MarketContext] = {}
    for day in dates:
        contexts[day] = _build_context(day, index_bars, breadth_by_date, sector_scores)
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
        merged["theme_strength"] = payload["theme_strength"]
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
        merged["theme_strength"] = 0.0
        merged["stock_theme_alignment"] = _stock_theme_alignment(row, payload)
        result.append(merged)
    return result


def _benchmark_proxy_context(row: dict[str, Any]) -> dict[str, Any]:
    benchmark_return = _safe_float(row.get("benchmark_return_pct"))
    if benchmark_return is None:
        return {"regime": "unknown", "label": "未知", "market_score": 50.0, "risk_score": 50.0}
    if benchmark_return <= -8.0:
        return {
            "regime": "crash",
            "label": _dynamic_regime_labels()["crash"],
            "market_score": max(10.0, 35.0 + benchmark_return),
            "risk_score": min(95.0, 70.0 + abs(benchmark_return) * 2),
        }
    if benchmark_return <= -3.0:
        return {
            "regime": "weak_defensive",
            "label": _dynamic_regime_labels()["weak_defensive"],
            "market_score": max(20.0, 45.0 + benchmark_return),
            "risk_score": min(88.0, 58.0 + abs(benchmark_return) * 2),
        }
    if benchmark_return >= 5.0:
        return {
            "regime": "strong_broad",
            "label": _dynamic_regime_labels()["strong_broad"],
            "market_score": min(90.0, 64.0 + benchmark_return * 2),
            "risk_score": max(20.0, 42.0 - benchmark_return),
        }
    return {
        "regime": "choppy_rotation",
        "label": _dynamic_regime_labels()["choppy_rotation"],
        "market_score": 50.0 + benchmark_return,
        "risk_score": 50.0 - benchmark_return,
    }


def _has_index_context(session: Any, schema: Any, trade_dates: list[date]) -> bool:
    dates = sorted({day for day in trade_dates if day})
    if not dates:
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
        source=DEFAULT_CONTEXT_SOURCE,
        notes=notes,
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
    table = schema.stock_daily_bars
    excluded_symbols = [f"{item['symbol']}.{item['exchange']}" for item in INDEX_SYMBOLS]
    window = {
        "partition_by": table.c.vt_symbol,
        "order_by": table.c.trade_date,
    }
    rows = (
        select(
            table.c.vt_symbol.label("vt_symbol"),
            table.c.trade_date.label("trade_date"),
            table.c.close_price.label("close_price"),
            func.avg(table.c.close_price).over(**window, rows=(-19, 0)).label("ma20"),
            func.avg(table.c.close_price).over(**window, rows=(-59, 0)).label("ma60"),
            func.count(table.c.close_price).over(**window, rows=(-19, 0)).label("count20"),
            func.count(table.c.close_price).over(**window, rows=(-59, 0)).label("count60"),
            func.lag(table.c.close_price).over(**window).label("prev_close"),
        )
        .where(table.c.trade_date >= start)
        .where(table.c.trade_date <= end)
        .where(~table.c.vt_symbol.in_(excluded_symbols))
        .subquery()
    )
    total_case = case((rows.c.count20 >= 20, 1), else_=0)
    query = (
        select(
            rows.c.trade_date,
            func.sum(total_case).label("total"),
            func.sum(case((and_(rows.c.count20 >= 20, rows.c.close_price >= rows.c.ma20), 1), else_=0)).label("above20"),
            func.sum(case((and_(rows.c.count60 >= 60, rows.c.close_price >= rows.c.ma60), 1), else_=0)).label("above60"),
            func.sum(case((and_(rows.c.count20 >= 20, rows.c.close_price > rows.c.prev_close), 1), else_=0)).label("rising"),
        )
        .where(rows.c.trade_date.in_(target_dates))
        .group_by(rows.c.trade_date)
    )
    result = {day: _neutral_breadth() for day in target_dates}
    for row in session.execute(query).mappings().all():
        result[row["trade_date"]] = _breadth_from_counts(
            {
                "total": int(row.get("total") or 0),
                "above20": int(row.get("above20") or 0),
                "above60": int(row.get("above60") or 0),
                "rising": int(row.get("rising") or 0),
            }
        )
    return result


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
        "return_20d": ret20,
        "return_60d": ret60,
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
