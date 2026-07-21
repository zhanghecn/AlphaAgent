"""Forward-only evidence for the first-board style-isolation shadow."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from math import isfinite

from sqlalchemy import func, select

from alphaagent.market.cache import TTLCache
from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.domain import is_eligible_main_board

POLICY_VERSION = "first-board-style-isolation-shadow-v1"
STYLE_INDEX_SYMBOLS = ("000300.SSE", "000852.SSE")
STYLE_LOOKBACK_DAYS = 20
MIN_STYLE_OBSERVATIONS = 15
STYLE_PERCENTILE_THRESHOLD = 0.75
STRICT_MEMBERSHIP_LEVELS = frozenset({"strict", "strict_exclusions"})
CONTEXT_CACHE_SECONDS = 300

_CONTEXT_CACHE = TTLCache(max_items=4)


def attach_regime_failure_shadow(
    snapshot: Mapping[str, object],
    *,
    context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Attach research metadata without changing any executable action."""

    result = dict(snapshot)
    resolved = dict(context) if context is not None else _safe_context(snapshot)
    recommendations = _mapping(result.get("recommendations"))
    signals = _mapping_rows(recommendations.get("actionable_recommendations"))
    enriched = [_attach_signal_shadow(signal, resolved) for signal in signals]
    recommendations["actionable_recommendations"] = enriched
    result["recommendations"] = recommendations

    quality = _mapping(result.get("data_quality"))
    quality["regime_failure_shadow"] = _shadow_quality(resolved, enriched)
    result["data_quality"] = quality
    return result


def load_regime_failure_context(trade_date: date) -> dict[str, object]:
    """Load one immutable D-1 context shared by all snapshots of a session."""

    return _CONTEXT_CACHE.get_or_set(
        trade_date.isoformat(),
        CONTEXT_CACHE_SECONDS,
        lambda: _load_regime_failure_context(trade_date),
    )


def clear_regime_failure_context_cache() -> None:
    _CONTEXT_CACHE.clear()


def build_style_context(
    rows: Sequence[Mapping[str, object]],
    trade_date: date,
) -> dict[str, object]:
    """Calculate the D-1 large-cap minus small-cap rolling percentile."""

    values = _index_changes_by_date(rows, trade_date)
    common_dates = sorted(
        set(values[STYLE_INDEX_SYMBOLS[0]])
        & set(values[STYLE_INDEX_SYMBOLS[1]])
    )
    if not common_dates:
        return _blocked_style("blocked_by_style_current")

    prior_trade_date = common_dates[-1]
    current = _style_spread(values, prior_trade_date)
    prior_dates = common_dates[:-1][-STYLE_LOOKBACK_DAYS:]
    history = [_style_spread(values, item) for item in prior_dates]
    if current is None:
        return _blocked_style("blocked_by_style_current", prior_trade_date)
    valid_history = [item for item in history if item is not None]
    if len(valid_history) < MIN_STYLE_OBSERVATIONS:
        return _blocked_style("blocked_by_style_history", prior_trade_date, len(valid_history))

    percentile = sum(item <= current for item in valid_history) / len(valid_history)
    return {
        "status": "ready",
        "prior_trade_date": prior_trade_date.isoformat(),
        "style_spread_pct_points": round(current, 6),
        "style_percentile_20": round(percentile, 6),
        "style_history_count": len(valid_history),
    }


def build_industry_context(
    membership_rows: Sequence[Mapping[str, object]],
    scope: Mapping[str, object] | None,
    sealed_events: Sequence[Mapping[str, object]],
    prior_trade_date: date,
) -> dict[str, object]:
    """Build strict D-1 primary industries and sealed-board counts."""

    scope_status = _membership_scope_status(scope, prior_trade_date)
    if scope_status != "ready":
        return _blocked_industry(scope_status, scope, prior_trade_date)

    primary = _primary_industries(membership_rows)
    if not primary:
        return _blocked_industry("blocked_by_strict_industry_membership", scope, prior_trade_date)
    sealed_counts = _sealed_counts_by_industry(sealed_events, primary)
    sealed_event_count = sum(
        is_eligible_main_board(str(row.get("vt_symbol") or ""), str(row.get("name") or ""))
        for row in sealed_events
    )
    if sealed_event_count == 0:
        return _blocked_industry("blocked_by_limit_event_coverage", scope, prior_trade_date)
    return {
        "status": "ready",
        "membership_scope": _compact_scope(scope, prior_trade_date),
        "primary_industries": primary,
        "sealed_count_by_industry": dict(sealed_counts),
        "sealed_event_count": sealed_event_count,
    }


def _load_regime_failure_context(trade_date: date) -> dict[str, object]:
    inputs = _load_context_inputs(trade_date)
    prior_trade_date = inputs.get("prior_trade_date")
    if not isinstance(prior_trade_date, date):
        return {"status": "blocked_by_prior_trade_date"}
    style = build_style_context(_mapping_rows(inputs.get("index_rows")), trade_date)
    if (
        style.get("status") == "ready"
        and _optional_date(style.get("prior_trade_date")) != prior_trade_date
    ):
        style = {
            **style,
            "status": "blocked_by_style_trade_date",
        }
    industry = build_industry_context(
        _mapping_rows(inputs.get("membership_rows")),
        _optional_mapping(inputs.get("membership_scope")),
        _mapping_rows(inputs.get("sealed_events")),
        prior_trade_date,
    )
    blockers = [
        str(item.get("status"))
        for item in (style, industry)
        if item.get("status") != "ready"
    ]
    return {
        **style,
        **industry,
        "status": "ready" if not blockers else blockers[0],
        "blockers": blockers,
    }


def _load_context_inputs(trade_date: date) -> dict[str, object]:
    with session_scope() as session:
        prior_trade_date = session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date)).where(
                schema.stock_daily_bars.c.trade_date < trade_date
            )
        ).scalar_one_or_none()
        if prior_trade_date is None:
            return {"prior_trade_date": None}

        index_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.change_pct,
            ).where(
                schema.stock_daily_bars.c.vt_symbol.in_(STYLE_INDEX_SYMBOLS),
                schema.stock_daily_bars.c.trade_date.between(
                    prior_trade_date - timedelta(days=60),
                    prior_trade_date,
                ),
            )
        ).mappings().all()
        scope = session.execute(
            select(schema.stock_sector_membership_snapshot_scopes).where(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date
                == prior_trade_date,
                schema.stock_sector_membership_snapshot_scopes.c.scope_type
                == "industry",
            )
        ).mappings().one_or_none()
        memberships = session.execute(
            select(schema.stock_sector_membership_snapshots).where(
                schema.stock_sector_membership_snapshots.c.snapshot_date
                == prior_trade_date,
                schema.stock_sector_membership_snapshots.c.sector_type
                == "industry",
            )
        ).mappings().all()
        event_date = func.replace(
            func.substr(schema.stock_events.c.event_date, 1, 10),
            "-",
            "",
        )
        sealed_events = session.execute(
            select(
                schema.stock_events.c.vt_symbol,
                schema.stocks.c.name,
            )
            .select_from(
                schema.stock_events.join(
                    schema.stocks,
                    schema.stock_events.c.vt_symbol == schema.stocks.c.vt_symbol,
                )
            )
            .where(
                schema.stock_events.c.event_type == "limit_pool_zt",
                event_date == prior_trade_date.strftime("%Y%m%d"),
            )
            .distinct()
        ).mappings().all()
    return {
        "prior_trade_date": prior_trade_date,
        "index_rows": [dict(row) for row in index_rows],
        "membership_scope": dict(scope) if scope else None,
        "membership_rows": [dict(row) for row in memberships],
        "sealed_events": [dict(row) for row in sealed_events],
    }


def _safe_context(snapshot: Mapping[str, object]) -> dict[str, object]:
    try:
        trade_date = _date(snapshot.get("trade_date"))
        return load_regime_failure_context(trade_date)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "blockers": [exc.__class__.__name__],
        }


def _attach_signal_shadow(
    signal: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    result = dict(signal)
    result["regime_failure_shadow"] = _signal_shadow(result, context)
    return result


def _signal_shadow(
    signal: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    base = _shadow_base(context)
    lane = str(signal.get("board_lane") or signal.get("lane") or "")
    if lane != "first_board":
        return {**base, "status": "not_applicable", "risk_flag": None}
    if context.get("status") != "ready":
        return {**base, "status": str(context.get("status") or "unavailable"), "risk_flag": None}

    symbol = str(signal.get("vt_symbol") or "")
    primary = _mapping(context.get("primary_industries")).get(symbol)
    if not isinstance(primary, Mapping):
        return {**base, "status": "blocked_by_strict_industry_membership", "risk_flag": None}
    industry_id = str(primary.get("industry_id") or "")
    sealed_count = int(_mapping(context.get("sealed_count_by_industry")).get(industry_id) or 0)
    percentile = _number(context.get("style_percentile_20"))
    risk_flag = bool(
        percentile is not None
        and percentile > STYLE_PERCENTILE_THRESHOLD
        and sealed_count == 0
    )
    return {
        **base,
        "status": "ready",
        "industry_id": industry_id,
        "industry_name": str(primary.get("industry_name") or ""),
        "prior_industry_sealed_count": sealed_count,
        "risk_flag": risk_flag,
    }


def _shadow_base(context: Mapping[str, object]) -> dict[str, object]:
    scope = _mapping(context.get("membership_scope"))
    return {
        "policy_version": POLICY_VERSION,
        "decision_cutoff": "D-1_CLOSE",
        "execution_effect": "none_research_only",
        "prior_trade_date": context.get("prior_trade_date"),
        "style_spread_pct_points": context.get("style_spread_pct_points"),
        "style_percentile_20": context.get("style_percentile_20"),
        "style_history_count": context.get("style_history_count"),
        "style_percentile_threshold": STYLE_PERCENTILE_THRESHOLD,
        "membership_scope_date": scope.get("snapshot_date"),
        "membership_evidence_level": scope.get("evidence_level"),
        "membership_source": scope.get("source"),
    }


def _shadow_quality(
    context: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    shadows = [
        _mapping(signal.get("regime_failure_shadow"))
        for signal in signals
        if str(signal.get("board_lane") or signal.get("lane") or "") == "first_board"
    ]
    return {
        "policy_version": POLICY_VERSION,
        "status": str(context.get("status") or "unavailable"),
        "execution_effect": "none_research_only",
        "first_board_count": len(shadows),
        "eligible_count": sum(item.get("status") == "ready" for item in shadows),
        "risk_count": sum(item.get("risk_flag") is True for item in shadows),
        "prior_trade_date": context.get("prior_trade_date"),
        "blockers": list(context.get("blockers") or []),
    }


def _index_changes_by_date(
    rows: Sequence[Mapping[str, object]],
    trade_date: date,
) -> dict[str, dict[date, float | None]]:
    values: dict[str, dict[date, float | None]] = {
        symbol: {} for symbol in STYLE_INDEX_SYMBOLS
    }
    for row in rows:
        symbol = str(row.get("vt_symbol") or "")
        row_date = _optional_date(row.get("trade_date"))
        if symbol in values and row_date is not None and row_date < trade_date:
            values[symbol][row_date] = _number(row.get("change_pct"))
    return values


def _style_spread(
    values: Mapping[str, Mapping[date, float | None]],
    trade_date: date,
) -> float | None:
    large = values[STYLE_INDEX_SYMBOLS[0]].get(trade_date)
    small = values[STYLE_INDEX_SYMBOLS[1]].get(trade_date)
    return large - small if large is not None and small is not None else None


def _primary_industries(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row.get("vt_symbol") or ""),
            int(row.get("rank")) if row.get("rank") is not None else 1_000_000,
            str(row.get("sector_id") or ""),
        ),
    )
    result: dict[str, dict[str, object]] = {}
    for row in ordered:
        symbol = str(row.get("vt_symbol") or "")
        sector_id = str(row.get("sector_id") or "")
        if symbol and sector_id and symbol not in result:
            result[symbol] = {
                "industry_id": sector_id,
                "industry_name": str(row.get("sector_name") or ""),
            }
    return result


def _sealed_counts_by_industry(
    events: Sequence[Mapping[str, object]],
    primary: Mapping[str, Mapping[str, object]],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in events:
        symbol = str(row.get("vt_symbol") or "")
        name = str(row.get("name") or "")
        industry = primary.get(symbol)
        if is_eligible_main_board(symbol, name) and isinstance(industry, Mapping):
            counts[str(industry.get("industry_id") or "")] += 1
    counts.pop("", None)
    return counts


def _membership_scope_status(
    scope: Mapping[str, object] | None,
    prior_trade_date: date,
) -> str:
    if not isinstance(scope, Mapping):
        return "blocked_by_membership_scope"
    if _optional_date(scope.get("snapshot_date")) != prior_trade_date:
        return "blocked_by_membership_scope_date"
    if scope.get("complete") is not True:
        return "blocked_by_membership_scope"
    if str(scope.get("evidence_level") or "") not in STRICT_MEMBERSHIP_LEVELS:
        return "blocked_by_membership_evidence"
    return "ready"


def _compact_scope(
    scope: Mapping[str, object] | None,
    prior_trade_date: date,
) -> dict[str, object]:
    source = scope if isinstance(scope, Mapping) else {}
    return {
        "snapshot_date": prior_trade_date.isoformat(),
        "complete": source.get("complete") is True,
        "evidence_level": str(source.get("evidence_level") or ""),
        "source": str(source.get("source") or ""),
        "captured_at": _text(source.get("captured_at")),
    }


def _blocked_style(
    status: str,
    prior_trade_date: date | None = None,
    history_count: int = 0,
) -> dict[str, object]:
    return {
        "status": status,
        "prior_trade_date": prior_trade_date.isoformat() if prior_trade_date else None,
        "style_spread_pct_points": None,
        "style_percentile_20": None,
        "style_history_count": history_count,
    }


def _blocked_industry(
    status: str,
    scope: Mapping[str, object] | None,
    prior_trade_date: date,
) -> dict[str, object]:
    return {
        "status": status,
        "membership_scope": _compact_scope(scope, prior_trade_date),
        "primary_industries": {},
        "sealed_count_by_industry": {},
        "sealed_event_count": 0,
    }


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _date(value: object) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError("trade_date is required")
    return parsed


def _optional_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _text(value: object) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value else None
