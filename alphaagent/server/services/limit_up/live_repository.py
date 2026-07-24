"""Persistence for append-only intraday limit-up signal snapshots."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median
from threading import Lock
from zoneinfo import ZoneInfo

from sqlalchemy import case, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.market.cache import TTLCache
from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.features import market_snapshot_for_trade
from alphaagent.server.services.limit_up.lane_repository import (
    build_financial_index,
    financial_risk_as_of,
    financial_snapshot_as_of,
    merge_rich_event_rows,
)
from alphaagent.server.services.limit_up.repository import LIMIT_EVENT_TYPES
from alphaagent.server.services.limit_up.sentiment import load_sentiment_points
from alphaagent.server.services.limit_up.sector_warmup import group_concepts
from alphaagent.server.services.limit_up.versions import LIVE_STRATEGY_VERSION

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEXT_SESSION_PLAN_MODES = ("next_session_preliminary", "next_session_final")
LANE_VALIDATION_SNAPSHOT_MODES = ("live_snapshot", "next_session_final")
RESEARCH_SECTOR_TYPES = ("theme", "industry")
LIVE_CONTEXT_SECTOR_TYPES = (*RESEARCH_SECTOR_TYPES, "concept")
CONCEPT_GROUP_CACHE_SECONDS = 900
_CONCEPT_GROUP_CACHE = TTLCache(max_items=2)
_prior_context_lock = Lock()
_prior_context_trade_date: date | None = None
_prior_context_by_symbol: dict[str, dict[str, object]] = {}
_prior_context_meta: dict[str, object] = {}
STYLE_SECTOR_KEYWORDS = (
    "MSCI",
    "中证",
    "沪深300",
    "上证50",
    "深证100",
    "大盘股",
    "中盘股",
    "小盘股",
    "成长",
    "价值",
    "风格",
    "热股",
    "昨日",
    "近期",
    "涨停",
    "连板",
    "高换手",
    "融资融券",
    "沪股通",
    "深股通",
    "机构重仓",
    "基金重仓",
    "成份股",
    "成分股",
    "年报",
    "季报",
    "预增",
    "扭亏",
    "高振幅",
    "HS300",
)


def save_snapshot(snapshot: Mapping[str, object]) -> dict[str, object]:
    captured_at = _datetime(snapshot.get("captured_at"))
    trade_date = _date(snapshot.get("trade_date") or captured_at.date())
    captured_minute = captured_at.replace(second=0, microsecond=0)
    values = {
        "trade_date": trade_date,
        "captured_at": captured_at,
        "captured_minute": captured_minute,
        "session_stage": str(snapshot.get("session_stage") or "closed"),
        "strategy_version": str(snapshot.get("strategy_version") or LIVE_STRATEGY_VERSION),
        "mode": str(snapshot.get("mode") or "live_snapshot"),
        "source": str(snapshot.get("source") or "unknown"),
        "source_updated_at": _optional_datetime(snapshot.get("source_updated_at")),
        "market_context": dict(snapshot.get("market_context") or {}),
        "candidates": list(snapshot.get("candidates") or []),
        "preboard_candidates": list(snapshot.get("preboard_candidates") or []),
        "recommendations": dict(snapshot.get("recommendations") or {}),
        "data_quality": dict(snapshot.get("data_quality") or {}),
    }
    statement = pg_insert(schema.limit_up_signal_snapshots).values(**values)
    statement = statement.on_conflict_do_update(
        constraint="uq_limit_up_signal_snapshot_minute_version",
        set_={
            "captured_at": statement.excluded.captured_at,
            "session_stage": statement.excluded.session_stage,
            "mode": statement.excluded.mode,
            "source": statement.excluded.source,
            "source_updated_at": statement.excluded.source_updated_at,
            "market_context": statement.excluded.market_context,
            "candidates": statement.excluded.candidates,
            "preboard_candidates": statement.excluded.preboard_candidates,
            "recommendations": statement.excluded.recommendations,
            "data_quality": statement.excluded.data_quality,
            "updated_at": datetime.now(timezone.utc),
        },
    ).returning(schema.limit_up_signal_snapshots)
    with session_scope() as session:
        row = session.execute(statement).mappings().one()
    return _snapshot_row(row)


def load_latest_snapshot(
    trade_date: date | str | None = None,
    *,
    strategy_version: str | None = None,
) -> dict[str, object] | None:
    statement = select(schema.limit_up_signal_snapshots)
    if trade_date is not None:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.trade_date == _date(trade_date)
        )
    if strategy_version:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.strategy_version == strategy_version
        )
    statement = statement.order_by(
        desc(schema.limit_up_signal_snapshots.c.captured_at)
    ).limit(1)
    with session_scope() as session:
        row = session.execute(statement).mappings().one_or_none()
    return _snapshot_row(row) if row else None


def load_publication_audit_rows(
    trade_date: date | str,
    *,
    strategy_version: str = LIVE_STRATEGY_VERSION,
) -> list[dict[str, object]]:
    """Load one row per publicly readable live minute with its first write time."""

    table = schema.limit_up_signal_snapshots
    statement = (
        select(
            table.c.captured_minute,
            table.c.captured_at,
            table.c.created_at,
        )
        .where(
            table.c.trade_date == _date(trade_date),
            table.c.strategy_version == strategy_version,
            table.c.mode == "live_snapshot",
        )
        .order_by(table.c.captured_minute)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def load_latest_lane_validations(
    *,
    strategy_version: str,
    captured_after: datetime,
) -> dict[str, dict[str, object]] | None:
    """Load the compact live validation gate produced after a ledger rebuild."""

    recommendations = schema.limit_up_signal_snapshots.c.recommendations
    statement = (
        select(
            recommendations["board_lane_validations"].label("validations")
        )
        .where(
            schema.limit_up_signal_snapshots.c.strategy_version
            == strategy_version,
            schema.limit_up_signal_snapshots.c.mode.in_(
                LANE_VALIDATION_SNAPSHOT_MODES
            ),
            schema.limit_up_signal_snapshots.c.captured_at >= captured_after,
            recommendations["board_lane_validations"].is_not(None),
        )
        .order_by(desc(schema.limit_up_signal_snapshots.c.captured_at))
        .limit(1)
    )
    with session_scope() as session:
        payload = session.execute(statement).scalar_one_or_none()
    if not isinstance(payload, Mapping):
        return None
    return {
        str(lane): dict(validation)
        for lane, validation in payload.items()
        if isinstance(validation, Mapping)
    }


def load_latest_next_session_plan(
    source_trade_date: date | str | None = None,
    *,
    phase: str | None = None,
    strategy_version: str | None = None,
) -> dict[str, object] | None:
    modes = (
        (f"next_session_{phase}",)
        if phase in {"preliminary", "final"}
        else NEXT_SESSION_PLAN_MODES
    )
    statement = select(schema.limit_up_signal_snapshots).where(
        schema.limit_up_signal_snapshots.c.mode.in_(modes)
    )
    if source_trade_date is not None:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.trade_date == _date(source_trade_date)
        )
    if strategy_version:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.strategy_version == strategy_version
        )
    mode_priority = case(
        (schema.limit_up_signal_snapshots.c.mode == "next_session_final", 0),
        else_=1,
    )
    statement = statement.order_by(
        desc(schema.limit_up_signal_snapshots.c.trade_date),
        mode_priority,
        desc(schema.limit_up_signal_snapshots.c.captured_at),
    ).limit(1)
    with session_scope() as session:
        row = session.execute(statement).mappings().one_or_none()
    return _snapshot_row(row) if row else None


def load_snapshot_as_of(
    trade_date: date | str,
    as_of: datetime | str | None,
    *,
    strategy_version: str | None = None,
) -> dict[str, object] | None:
    statement = select(schema.limit_up_signal_snapshots).where(
        schema.limit_up_signal_snapshots.c.trade_date == _date(trade_date)
    )
    if as_of is not None:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.captured_at <= _datetime(as_of)
        )
    if strategy_version:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.strategy_version == strategy_version
        )
    statement = statement.order_by(
        desc(schema.limit_up_signal_snapshots.c.captured_at)
    ).limit(1)
    with session_scope() as session:
        row = session.execute(statement).mappings().one_or_none()
    return _snapshot_row(row) if row else None


def load_previous_snapshot(
    trade_date: date | str,
    before: datetime | str,
) -> dict[str, object] | None:
    return load_snapshot_as_of(trade_date, _datetime(before))


def list_snapshot_dates() -> list[str]:
    statement = select(schema.limit_up_signal_snapshots.c.trade_date).distinct().order_by(
        schema.limit_up_signal_snapshots.c.trade_date
    )
    with session_scope() as session:
        rows = session.execute(statement).scalars().all()
    return [row.isoformat() if isinstance(row, date) else str(row) for row in rows]


def list_daily_trade_dates() -> list[str]:
    statement = select(schema.stock_daily_bars.c.trade_date).distinct().order_by(
        schema.stock_daily_bars.c.trade_date
    )
    with session_scope() as session:
        rows = session.execute(statement).scalars().all()
    return [row.isoformat() if isinstance(row, date) else str(row) for row in rows]


def load_actionable_recommendation_snapshots(
    strategy_version: str,
) -> list[dict[str, object]]:
    """Load only formal live recommendations needed for D+1 exit backfill."""

    table = schema.limit_up_signal_snapshots
    actionable = table.c.recommendations["actionable_recommendations"].label(
        "actionable_recommendations"
    )
    statement = (
        select(
            table.c.trade_date,
            actionable,
        )
        .where(
            table.c.strategy_version == strategy_version,
            table.c.mode == "live_snapshot",
        )
        .order_by(table.c.trade_date, table.c.captured_at)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "trade_date": row["trade_date"].isoformat(),
            "actionable_recommendations": [
                dict(item)
                for item in (row["actionable_recommendations"] or [])
                if isinstance(item, Mapping)
            ],
        }
        for row in rows
    ]


def load_snapshots_between(
    start: date | None,
    end: date | None,
    *,
    strategy_version: str | None = None,
) -> list[dict[str, object]]:
    statement = select(schema.limit_up_signal_snapshots)
    if start is not None:
        statement = statement.where(schema.limit_up_signal_snapshots.c.trade_date >= start)
    if end is not None:
        statement = statement.where(schema.limit_up_signal_snapshots.c.trade_date <= end)
    if strategy_version:
        statement = statement.where(
            schema.limit_up_signal_snapshots.c.strategy_version == strategy_version
        )
    statement = statement.order_by(
        schema.limit_up_signal_snapshots.c.trade_date,
        schema.limit_up_signal_snapshots.c.captured_at,
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [_snapshot_row(row) for row in rows]


def load_daily_bars_for_symbols(
    symbols: list[str],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    normalized_symbols = sorted({str(symbol) for symbol in symbols if symbol})
    if not normalized_symbols:
        return []
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars)
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(normalized_symbols),
                schema.stock_daily_bars.c.trade_date.between(start, end),
            )
            .order_by(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
            )
        ).mappings().all()
    return [_plain_row(row) for row in rows]


def load_latest_daily_trade_date(on_or_before: date | None = None) -> date | None:
    statement = select(func.max(schema.stock_daily_bars.c.trade_date))
    if on_or_before is not None:
        statement = statement.where(schema.stock_daily_bars.c.trade_date <= on_or_before)
    with session_scope() as session:
        return session.execute(statement).scalar_one_or_none()


def load_live_context(
    symbols: list[str],
    trade_date: date,
) -> dict[str, object]:
    """Load cached prior context and freshly queried intraday context."""

    normalized_symbols = sorted({str(symbol) for symbol in symbols if symbol})
    if not normalized_symbols:
        return {"by_symbol": {}, "sentiment": {}, "timing": {}}

    prior = _cached_prior_symbol_context(normalized_symbols, trade_date)
    intraday = _load_intraday_context(normalized_symbols, trade_date, prior)
    prior_by_symbol = prior.get("by_symbol")
    prior_by_symbol = (
        prior_by_symbol if isinstance(prior_by_symbol, Mapping) else {}
    )
    intraday_by_symbol = intraday.get("by_symbol")
    intraday_by_symbol = (
        intraday_by_symbol if isinstance(intraday_by_symbol, Mapping) else {}
    )
    return {
        "by_symbol": {
            symbol: {
                **{
                    key: value
                    for key, value in dict(prior_by_symbol.get(symbol) or {}).items()
                    if not key.startswith("_")
                },
                **dict(intraday_by_symbol.get(symbol) or {}),
            }
            for symbol in normalized_symbols
        },
        "previous_trade_date": prior.get("previous_trade_date"),
        "sentiment": dict(intraday.get("sentiment") or {}),
        "timing": dict(intraday.get("timing") or {}),
    }


def clear_live_context_cache() -> None:
    """Clear the per-trading-day D-1 context cache."""

    global _prior_context_trade_date
    with _prior_context_lock:
        _prior_context_trade_date = None
        _prior_context_by_symbol.clear()
        _prior_context_meta.clear()


def _cached_prior_symbol_context(
    symbols: list[str],
    trade_date: date,
) -> dict[str, object]:
    global _prior_context_trade_date
    with _prior_context_lock:
        if _prior_context_trade_date != trade_date:
            _prior_context_trade_date = trade_date
            _prior_context_by_symbol.clear()
            _prior_context_meta.clear()
        missing = [
            symbol for symbol in symbols if symbol not in _prior_context_by_symbol
        ]
        if missing:
            loaded = _load_prior_symbol_context(
                missing,
                trade_date,
                include_global_context=not _prior_context_meta,
            )
            loaded_by_symbol = loaded.get("by_symbol")
            loaded_by_symbol = (
                loaded_by_symbol if isinstance(loaded_by_symbol, Mapping) else {}
            )
            for symbol in missing:
                _prior_context_by_symbol[symbol] = dict(
                    loaded_by_symbol.get(symbol) or {}
                )
            loaded_scores = loaded.get("score_by_sector")
            if isinstance(loaded_scores, Mapping):
                scores = _prior_context_meta.setdefault("score_by_sector", {})
                if isinstance(scores, dict):
                    scores.update(
                        {
                            str(key): dict(value)
                            for key, value in loaded_scores.items()
                            if isinstance(value, Mapping)
                        }
                    )
            for key in (
                "previous_trade_date",
                "sentiment_points",
                "calendar_dates",
                "concept_groups",
            ):
                if key in loaded:
                    _prior_context_meta[key] = loaded[key]
        return {
            "by_symbol": {
                symbol: dict(_prior_context_by_symbol.get(symbol) or {})
                for symbol in symbols
            },
            **_prior_context_meta,
        }


def _load_prior_symbol_context(
    symbols: list[str],
    trade_date: date,
    *,
    include_global_context: bool = True,
) -> dict[str, object]:
    """Load fields that cannot change during the current trading day."""

    normalized_symbols = sorted({str(symbol) for symbol in symbols if symbol})
    with session_scope() as session:
        previous_date = session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date)).where(
                schema.stock_daily_bars.c.trade_date < trade_date
            )
        ).scalar_one_or_none()
        memberships = session.execute(
            select(schema.stock_sector_memberships).where(
                schema.stock_sector_memberships.c.vt_symbol.in_(normalized_symbols),
                schema.stock_sector_memberships.c.sector_type.in_(LIVE_CONTEXT_SECTOR_TYPES),
            )
        ).mappings().all()
        sector_ids = sorted({str(row["sector_id"]) for row in memberships if row.get("sector_id")})
        score_rows = []
        if sector_ids and previous_date is not None:
            score_rows = session.execute(
                select(schema.sector_period_scores).where(
                    schema.sector_period_scores.c.sector_id.in_(sector_ids),
                    schema.sector_period_scores.c.period == "20d",
                    schema.sector_period_scores.c.as_of_date <= previous_date,
                )
                .distinct(schema.sector_period_scores.c.sector_id)
                .order_by(
                    schema.sector_period_scores.c.sector_id,
                    desc(schema.sector_period_scores.c.as_of_date),
                )
            ).mappings().all()
        bar_rows = []
        prior_event_rows = []
        financial_rows = []
        sentiment_points: list[dict[str, object]] = []
        calendar_dates: list[str] = []
        if previous_date is not None:
            data_start = previous_date - timedelta(days=220)
            bar_rows = session.execute(
                select(schema.stock_daily_bars).where(
                    schema.stock_daily_bars.c.vt_symbol.in_(normalized_symbols),
                    schema.stock_daily_bars.c.trade_date.between(data_start, previous_date),
                ).order_by(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date,
                )
            ).mappings().all()
            normalized_event_date = func.replace(
                func.substr(schema.stock_events.c.event_date, 1, 10),
                "-",
                "",
            )
            prior_event_rows = session.execute(
                select(schema.stock_events).where(
                    schema.stock_events.c.vt_symbol.in_(normalized_symbols),
                    schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES),
                    normalized_event_date == previous_date.strftime("%Y%m%d"),
                )
            ).mappings().all()
            financial_rows = session.execute(
                select(schema.stock_financial_reports).where(
                    schema.stock_financial_reports.c.vt_symbol.in_(normalized_symbols),
                    schema.stock_financial_reports.c.publish_date.is_not(None),
                    schema.stock_financial_reports.c.publish_date
                    <= trade_date.isoformat(),
                )
            ).mappings().all()
            if include_global_context:
                sentiment_points = load_sentiment_points(
                    session,
                    previous_date,
                    previous_date,
                )
                calendar_dates = [
                    item.isoformat()
                    for item in session.execute(
                        select(schema.stock_daily_bars.c.trade_date)
                        .where(
                            schema.stock_daily_bars.c.trade_date.between(
                                data_start,
                                previous_date,
                            )
                        )
                        .distinct()
                        .order_by(schema.stock_daily_bars.c.trade_date)
                    ).scalars().all()
                ]

    score_by_sector = _latest_by_key(score_rows, "sector_id")
    memberships_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in memberships:
        memberships_by_symbol[str(row.get("vt_symbol") or "")].append(row)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in bar_rows:
        bars_by_symbol[str(row.get("vt_symbol") or "")].append(row)
    prior_events = merge_rich_event_rows(prior_event_rows)
    financial_index = build_financial_index(financial_rows)
    concept_groups = _load_current_concept_groups() if include_global_context else []

    by_symbol: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        bars = bars_by_symbol.get(symbol, [])
        price_context = _prior_price_context(bars)
        prior_board = prior_events.get((symbol, previous_date)) if previous_date else None
        by_symbol[symbol] = {
            **price_context,
            "prior_board": _prior_board_context(prior_board, price_context),
            "financial_risk": financial_risk_as_of(
                financial_index,
                symbol,
                trade_date,
            ),
            "financial_snapshot": financial_snapshot_as_of(
                financial_index,
                symbol,
                trade_date,
            ),
            "lane_feature_ready": len(bars) >= 20,
            "_memberships": [
                dict(item) for item in memberships_by_symbol.get(symbol, [])
            ],
        }
    result: dict[str, object] = {
        "by_symbol": by_symbol,
        "previous_trade_date": previous_date.isoformat() if previous_date else None,
        "score_by_sector": score_by_sector,
    }
    if include_global_context:
        result.update(
            {
                "sentiment_points": sentiment_points,
                "calendar_dates": calendar_dates,
                "concept_groups": concept_groups,
            }
        )
    return result


def _load_intraday_context(
    symbols: list[str],
    trade_date: date,
    prior: Mapping[str, object],
) -> dict[str, object]:
    """Load fund-flow and timing fields that can change during the session."""

    prior_by_symbol = prior.get("by_symbol")
    prior_by_symbol = (
        prior_by_symbol if isinstance(prior_by_symbol, Mapping) else {}
    )
    memberships_by_symbol: dict[str, list[Mapping[str, object]]] = {}
    for symbol in symbols:
        row = prior_by_symbol.get(symbol)
        row = row if isinstance(row, Mapping) else {}
        memberships_by_symbol[symbol] = [
            item
            for item in row.get("_memberships") or []
            if isinstance(item, Mapping)
        ]
    sector_ids = sorted(
        {
            str(item.get("sector_id") or "")
            for rows in memberships_by_symbol.values()
            for item in rows
            if item.get("sector_id")
        }
    )
    with session_scope() as session:
        sector_flow_rows = []
        if sector_ids:
            sector_flow_rows = session.execute(
                select(schema.sector_fund_flows).where(
                    schema.sector_fund_flows.c.sector_id.in_(sector_ids),
                    schema.sector_fund_flows.c.period == "即时",
                    schema.sector_fund_flows.c.trade_date <= trade_date.isoformat(),
                )
                .distinct(schema.sector_fund_flows.c.sector_id)
                .order_by(
                    schema.sector_fund_flows.c.sector_id,
                    desc(schema.sector_fund_flows.c.trade_date),
                )
            ).mappings().all()
        stock_flow_rows = session.execute(
            select(schema.stock_fund_flows).where(
                schema.stock_fund_flows.c.vt_symbol.in_(symbols),
                schema.stock_fund_flows.c.period == "即时",
                schema.stock_fund_flows.c.trade_date <= trade_date.isoformat(),
            )
            .distinct(schema.stock_fund_flows.c.vt_symbol)
            .order_by(
                schema.stock_fund_flows.c.vt_symbol,
                desc(schema.stock_fund_flows.c.trade_date),
            )
        ).mappings().all()
        timing_panel = session.execute(
            select(schema.market_timing_panel.c.panel).where(
                schema.market_timing_panel.c.id == 1
            )
        ).scalar_one_or_none()

    scores = prior.get("score_by_sector")
    score_by_sector = scores if isinstance(scores, Mapping) else {}
    sector_flow_by_sector = _latest_by_key(sector_flow_rows, "sector_id")
    stock_flow_by_symbol = _latest_by_key(stock_flow_rows, "vt_symbol")
    concept_groups = prior.get("concept_groups")
    concept_groups = concept_groups if isinstance(concept_groups, list) else []
    by_symbol: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        membership = _best_membership(
            memberships_by_symbol.get(symbol, []),
            score_by_sector,
            sector_flow_by_sector,
        )
        sector_id = str(membership.get("sector_id") or "")
        sector_score = score_by_sector.get(sector_id, {})
        sector_score = sector_score if isinstance(sector_score, Mapping) else {}
        sector_flow = sector_flow_by_sector.get(sector_id, {})
        stock_flow = stock_flow_by_symbol.get(symbol, {})
        by_symbol[symbol] = {
            "sector_id": sector_id,
            "sector_name": membership.get("sector_name"),
            "sector_type": membership.get("sector_type"),
            "sector_heat": _number(sector_score.get("heat_score")),
            "sector_trend_state": sector_score.get("trend_state"),
            "sector_main_net_inflow": _number(sector_flow.get("main_net_inflow")),
            "sector_main_net_inflow_ratio": _number(
                sector_flow.get("main_net_inflow_ratio")
            ),
            "sector_flow_trade_date": sector_flow.get("trade_date"),
            "stock_main_net_inflow": _number(stock_flow.get("main_net_inflow")),
            "stock_main_net_inflow_ratio": _number(
                stock_flow.get("main_net_inflow_ratio")
            ),
            "stock_flow_trade_date": stock_flow.get("trade_date"),
            "concept_contexts": _concept_group_contexts(
                memberships_by_symbol.get(symbol, []),
                [],
                score_by_sector,
                sector_flow_by_sector,
                groups=concept_groups,
            ),
        }

    previous_text = str(prior.get("previous_trade_date") or "")
    previous_date = date.fromisoformat(previous_text) if previous_text else None
    timing_signals = (
        list((timing_panel.get("chart") or {}).get("signals") or [])
        if isinstance(timing_panel, Mapping)
        else []
    )
    sentiment_points = [
        dict(item)
        for item in prior.get("sentiment_points") or []
        if isinstance(item, Mapping)
    ]
    calendar_dates = [str(item) for item in prior.get("calendar_dates") or []]
    market = market_snapshot_for_trade(
        trade_date,
        previous_date,
        sentiment_points,
        timing_signals,
        calendar_dates,
    )
    return {
        "by_symbol": by_symbol,
        "sentiment": dict(market.get("sentiment") or {}),
        "timing": dict(market.get("timing") or {}),
    }


def _load_current_concept_groups() -> list[dict[str, object]]:
    def load() -> list[dict[str, object]]:
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_sector_memberships).where(
                    schema.stock_sector_memberships.c.sector_type.in_(("theme", "concept"))
                )
            ).mappings().all()
        return group_concepts(rows)

    return _CONCEPT_GROUP_CACHE.get_or_set(
        "current_memberships",
        CONCEPT_GROUP_CACHE_SECONDS,
        load,
    )


def _concept_group_contexts(
    candidate_memberships: list[Mapping[str, object]],
    all_memberships: list[Mapping[str, object]],
    scores: Mapping[str, Mapping[str, object]],
    flows: Mapping[str, Mapping[str, object]],
    *,
    groups: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    concept_groups = groups if groups is not None else group_concepts(all_memberships)
    group_by_sector = {
        str(sector_id): group
        for group in concept_groups
        for sector_id in group.get("sector_ids") or []
    }
    candidate_group_ids = {
        str(group["group_id"])
        for membership in candidate_memberships
        if str(membership.get("sector_type") or "") in {"theme", "concept"}
        and (group := group_by_sector.get(str(membership.get("sector_id") or "")))
    }
    contexts: list[dict[str, object]] = []
    groups_by_id = {
        str(group.get("group_id") or ""): group
        for group in concept_groups
    }
    for group_id in sorted(candidate_group_ids):
        group = groups_by_id[group_id]
        sector_ids = [str(value) for value in group.get("sector_ids") or []]
        heat_values = _numbers_for_keys(scores, sector_ids, "heat_score")
        inflow_values = _numbers_for_keys(flows, sector_ids, "main_net_inflow")
        ratio_values = _numbers_for_keys(flows, sector_ids, "main_net_inflow_ratio")
        flow_dates = sorted(
            {
                str(flows.get(sector_id, {}).get("trade_date") or "")[:10]
                for sector_id in sector_ids
                if flows.get(sector_id, {}).get("trade_date") not in (None, "")
            }
        )
        contexts.append(
            {
                "group_id": group_id,
                "group_name": group.get("group_name"),
                "sector_ids": sector_ids,
                "sector_names": list(group.get("sector_names") or []),
                "member_count": int(group.get("member_count") or 0),
                "sector_id": sector_ids[0] if sector_ids else None,
                "sector_name": (group.get("sector_names") or [None])[0],
                "heat_score": round(median(heat_values), 4) if heat_values else None,
                "trend_state": _group_trend_state(scores, sector_ids),
                "main_net_inflow": (
                    round(median(inflow_values), 4) if inflow_values else None
                ),
                "main_net_inflow_ratio": (
                    round(median(ratio_values), 4) if ratio_values else None
                ),
                "flow_trade_date": flow_dates[0] if len(flow_dates) == 1 else None,
                "source": group.get("source"),
            }
        )
    return sorted(
        contexts,
        key=lambda context: (
            -(_number(context.get("heat_score")) or -1.0),
            str(context.get("group_id") or ""),
        ),
    )


def _numbers_for_keys(
    values: Mapping[str, Mapping[str, object]],
    keys: list[str],
    field: str,
) -> list[float]:
    return [
        number
        for key in keys
        if (number := _number(values.get(key, {}).get(field))) is not None
    ]


def _group_trend_state(
    scores: Mapping[str, Mapping[str, object]],
    sector_ids: list[str],
) -> str | None:
    states = [
        str(scores.get(sector_id, {}).get("trend_state") or "").lower()
        for sector_id in sector_ids
    ]
    for risk_state in ("broken", "ebb", "retreat", "decline"):
        if risk_state in states:
            return risk_state
    ranked = sorted(
        sector_ids,
        key=lambda sector_id: -(
            _number(scores.get(sector_id, {}).get("heat_score")) or -1.0
        ),
    )
    if not ranked:
        return None
    value = scores.get(ranked[0], {}).get("trend_state")
    return str(value) if value not in (None, "") else None


def _snapshot_row(row: Mapping[str, object]) -> dict[str, object]:
    result = dict(row)
    for key in ("trade_date", "captured_at", "captured_minute", "source_updated_at", "created_at", "updated_at"):
        value = result.get(key)
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    quality = result.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    plan = quality.get("plan")
    if isinstance(plan, Mapping):
        for key in ("source_trade_date", "target_session", "plan_phase"):
            if plan.get(key) not in (None, ""):
                result[key] = plan[key]
    return result


def _plain_row(row: Mapping[str, object]) -> dict[str, object]:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    return result


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)


def _optional_datetime(value: object) -> datetime | None:
    return _datetime(value) if value not in (None, "") else None


def _latest_by_key(
    rows: list[Mapping[str, object]] | list[object],
    key: str,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        value = str(raw.get(key) or "")
        if value and value not in result:
            result[value] = raw
    return result


def _best_membership(
    rows: list[Mapping[str, object]],
    scores: Mapping[str, Mapping[str, object]],
    flows: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object]:
    usable = [
        row
        for row in rows
        if str(row.get("sector_type") or "") == "industry"
        and _is_trade_sector(str(row.get("sector_name") or ""))
    ]
    if not usable:
        return {}
    return max(
        usable,
        key=lambda row: (
            _number(scores.get(str(row.get("sector_id") or ""), {}).get("heat_score")) or -1.0,
            _number(flows.get(str(row.get("sector_id") or ""), {}).get("main_net_inflow")) or -1e30,
            1 if row.get("is_precise") else 0,
            -int(row.get("rank") or 9999),
        ),
    )


def _prior_price_context(rows: list[Mapping[str, object]]) -> dict[str, object]:
    if not rows:
        return {
            "previous_close": None,
            "previous_limit_up": False,
            "prior_streak": 0,
            "prior_break_streak": 0,
            "prior_change_pct": None,
            "prior_return_5d_pct": None,
            "prior_return_20d_pct": None,
            "prior_amplitude_pct": None,
            "prior_turnover_rate": None,
            "prior_turnover_ratio_5d": None,
            "prior_amount_ratio_5d": None,
            "prior_low_change_pct": None,
            "prior_limit_count_126": 0,
            "prior_touch_count_126": 0,
            "prior_seal_success_rate_126": None,
            "prior_limit_count_5": 0,
            "prior_limit_count_10": 0,
            "trade_days_since_prior_limit": None,
            "pullback_from_prior_limit_pct": None,
            "prior_position_120": None,
        }
    ordered = sorted(rows, key=lambda row: str(row.get("trade_date") or ""))
    latest = ordered[-1]
    streak = 0
    for row in reversed(ordered):
        change_pct = _number(row.get("change_pct"))
        if change_pct is None or change_pct < 9.5:
            break
        streak += 1
    previous_turnovers = [
        value
        for row in ordered[-6:-1]
        if (value := _number(row.get("turnover"))) is not None and value > 0
    ]
    latest_turnover = _number(latest.get("turnover"))
    average_turnover = mean(previous_turnovers) if previous_turnovers else None
    latest_close = _number(latest.get("close_price"))
    previous_close = _number(ordered[-2].get("close_price")) if len(ordered) >= 2 else None
    prior_change_pct = _number(latest.get("change_pct"))
    if prior_change_pct is None and latest_close is not None and previous_close:
        prior_change_pct = (latest_close / previous_close - 1) * 100
    amount_ratio = (
        round(latest_turnover / average_turnover, 4)
        if latest_turnover is not None and average_turnover
        else None
    )
    sealed_flags = [_daily_sealed(row) for row in ordered]
    prior_break_streak = 0
    if sealed_flags and not sealed_flags[-1]:
        for is_sealed in reversed(sealed_flags[:-1]):
            if not is_sealed:
                break
            prior_break_streak += 1
    touched_flags = [
        _daily_touched(row, ordered[index - 1] if index > 0 else None)
        for index, row in enumerate(ordered)
    ]
    recent_126 = sealed_flags[-126:]
    touched_126 = touched_flags[-126:]
    limit_count_126 = sum(recent_126)
    touch_count_126 = sum(touched_126)
    last_limit_index = next(
        (index for index in range(len(ordered) - 1, -1, -1) if sealed_flags[index]),
        None,
    )
    last_limit_close = (
        _number(ordered[last_limit_index].get("close_price"))
        if last_limit_index is not None
        else None
    )
    position_rows = ordered[-120:]
    position_lows = [
        value
        for row in position_rows
        if (value := _number(row.get("low_price"))) is not None
    ]
    position_highs = [
        value
        for row in position_rows
        if (value := _number(row.get("high_price"))) is not None
    ]
    position = None
    if latest_close is not None and len(position_rows) >= 20 and position_lows and position_highs:
        low_120 = min(position_lows)
        high_120 = max(position_highs)
        if high_120 > low_120:
            position = min(max((latest_close - low_120) / (high_120 - low_120), 0.0), 1.0)
    latest_low = _number(latest.get("low_price"))
    prior_low_change = (
        (latest_low / previous_close - 1) * 100
        if latest_low is not None and previous_close
        else None
    )
    return {
        "previous_close": latest_close,
        "previous_limit_up": streak > 0,
        "prior_streak": streak,
        "prior_break_streak": prior_break_streak,
        "prior_change_pct": _rounded(prior_change_pct),
        "prior_return_5d_pct": _close_return(ordered, latest_close, 6),
        "prior_return_20d_pct": _close_return(ordered, latest_close, 21),
        "prior_amplitude_pct": _amplitude(latest),
        "prior_turnover_rate": _number(latest.get("turnover_rate")),
        "prior_turnover_ratio_5d": amount_ratio,
        "prior_amount_ratio_5d": amount_ratio,
        "prior_low_change_pct": _rounded(prior_low_change),
        "prior_limit_count_126": limit_count_126,
        "prior_touch_count_126": touch_count_126,
        "prior_seal_success_rate_126": _rounded(
            limit_count_126 / touch_count_126 if touch_count_126 else None
        ),
        "prior_limit_count_5": sum(sealed_flags[-5:]),
        "prior_limit_count_10": sum(sealed_flags[-10:]),
        "trade_days_since_prior_limit": (
            len(ordered) - last_limit_index if last_limit_index is not None else None
        ),
        "pullback_from_prior_limit_pct": _rounded(
            (latest_close / last_limit_close - 1) * 100
            if latest_close is not None and last_limit_close
            else None
        ),
        "prior_position_120": _rounded(position),
    }


def _prior_board_context(
    event: Mapping[str, object] | None,
    price_context: Mapping[str, object],
) -> dict[str, object] | None:
    if event is not None:
        return _plain_row(event)
    if not price_context.get("previous_limit_up"):
        return None
    return {
        "is_sealed": True,
        "open_times": None,
        "source": "daily_only",
    }


def _daily_sealed(row: Mapping[str, object]) -> bool:
    change_pct = _number(row.get("change_pct"))
    return change_pct is not None and change_pct >= 9.5


def _daily_touched(
    row: Mapping[str, object],
    previous: Mapping[str, object] | None,
) -> bool:
    if _daily_sealed(row):
        return True
    high = _number(row.get("high_price"))
    previous_close = _number(previous.get("close_price")) if previous else None
    return bool(high is not None and previous_close and (high / previous_close - 1) * 100 >= 9.7)


def _close_return(
    rows: list[Mapping[str, object]],
    latest_close: float | None,
    lookback_rows: int,
) -> float | None:
    if latest_close is None or len(rows) < lookback_rows:
        return None
    base = _number(rows[-lookback_rows].get("close_price"))
    return _rounded((latest_close / base - 1) * 100) if base else None


def _amplitude(row: Mapping[str, object]) -> float | None:
    high = _number(row.get("high_price"))
    low = _number(row.get("low_price"))
    return _rounded((high / low - 1) * 100) if high is not None and low else None


def _rounded(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _is_trade_sector(name: str) -> bool:
    return bool(name.strip()) and not any(keyword in name for keyword in STYLE_SECTOR_KEYWORDS)


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
