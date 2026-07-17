"""Append-only persistence for short-lived intraday limit-up diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from threading import Lock

from sqlalchemy import delete, desc, insert, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope


TRACE_RETAIN_TRADE_DAYS = 2
TRACE_CANDIDATE_FIELDS = (
    "vt_symbol",
    "name",
    "sector_id",
    "sector_name",
    "concept_id",
    "concept_name",
    "concept_state",
    "concept_strength_score",
    "concept_strength_rank",
    "concept_strength_percentile",
    "concept_leader_rank",
    "concept_coverage_ratio",
    "concept_strong_5_count",
    "concept_near_limit_count",
    "concept_sealed_count",
    "concept_failed_count",
    "concept_change_acceleration_3m",
    "concept_turnover_acceleration_3m",
    "concept_snapshot_age_seconds",
    "market_dragon_rank",
    "sector_dragon_rank",
    "board_level",
    "board_lane",
    "state",
    "change_pct",
    "last_price",
    "limit_price",
    "distance_to_limit_pct",
    "first_limit_time",
    "evaluation_time",
    "last_limit_time",
    "open_times",
    "seal_amount",
    "turnover_rate",
    "volume_ratio",
    "sector_heat",
    "sector_touch_count",
    "sector_main_net_inflow",
    "stock_main_net_inflow",
    "seal_to_turnover_ratio",
    "seal_amount_retention_ratio",
    "seal_amount_change_pct",
    "lane_decision",
    "lane_blockers",
    "lane_favorable_factors",
    "lane_support_score",
    "lane_entry_quality_score",
    "lane_quality_tier",
    "lane_risk_count",
    "lane_risk_flags",
    "lane_rank_score",
    "setup_tags",
    "portfolio_selected",
    "seen_before_seal",
    "missed_preseal_entry",
)
TRACE_SIGNAL_FIELDS = (
    "vt_symbol",
    "name",
    "market_dragon_rank",
    "board_lane",
    "board_level",
    "state",
    "concept_id",
    "concept_name",
    "concept_state",
    "concept_strength_score",
    "concept_strength_rank",
    "concept_strength_percentile",
    "concept_leader_rank",
    "concept_coverage_ratio",
    "concept_strong_5_count",
    "concept_near_limit_count",
    "concept_sealed_count",
    "concept_failed_count",
    "concept_change_acceleration_3m",
    "concept_turnover_acceleration_3m",
    "concept_snapshot_age_seconds",
    "signal_state",
    "action",
    "research_action",
    "entry_kind",
    "reason",
    "trigger_price",
    "distance_to_limit_pct",
    "lane_blocker_reasons",
    "lane_support_score",
    "lane_entry_quality_score",
    "blocking_scope",
    "pending_reasons",
    "selection_reasons",
    "trigger_checks",
)
_prune_lock = Lock()
_last_pruned_trade_date: date | None = None


def retention_cutoff(
    trade_dates: Sequence[date],
    *,
    retain_trade_days: int = TRACE_RETAIN_TRADE_DAYS,
) -> date | None:
    keep_count = max(int(retain_trade_days), 1)
    ordered = sorted(set(trade_dates), reverse=True)
    return ordered[keep_count - 1] if len(ordered) >= keep_count else None


def save_live_trace_snapshot(snapshot: Mapping[str, object]) -> dict[str, object]:
    captured_at = _as_datetime(snapshot["captured_at"])
    trade_date = captured_at.date()
    values = {
        "trade_date": trade_date,
        "source_trade_date": _optional_date(snapshot.get("trade_date")),
        "captured_at": captured_at,
        "session_stage": str(snapshot.get("session_stage") or "closed"),
        "strategy_version": str(snapshot.get("strategy_version") or "unknown"),
        "mode": "live_trace",
        "source": str(snapshot.get("source") or "unknown"),
        "source_updated_at": _optional_datetime(snapshot.get("source_updated_at")),
        "market_context": _mapping(snapshot.get("market_context")),
        "radar_candidates": _project_rows(
            snapshot.get("trace_radar_candidates"),
            TRACE_CANDIDATE_FIELDS,
        ),
        "ranked_candidates": _project_rows(
            snapshot.get("candidates"),
            TRACE_CANDIDATE_FIELDS,
        ),
        "recommendations": _trace_recommendations(snapshot.get("recommendations")),
        "data_quality": _mapping(snapshot.get("data_quality")),
    }
    with session_scope() as session:
        row = session.execute(
            insert(schema.limit_up_live_trace_snapshots)
            .values(**values)
            .returning(schema.limit_up_live_trace_snapshots)
        ).mappings().one()
    _prune_once_for_trade_date(trade_date)
    return dict(row)


def save_live_trace_error(
    captured_at: datetime,
    error: Exception,
    *,
    strategy_version: str,
) -> dict[str, object]:
    values = {
        "trade_date": captured_at.date(),
        "source_trade_date": None,
        "captured_at": captured_at,
        "session_stage": "scan_error",
        "strategy_version": strategy_version,
        "mode": "scan_error",
        "source": "unavailable",
        "market_context": {},
        "radar_candidates": [],
        "ranked_candidates": [],
        "recommendations": {},
        "data_quality": {"status": "error", "error": str(error)[:500]},
    }
    with session_scope() as session:
        row = session.execute(
            insert(schema.limit_up_live_trace_snapshots)
            .values(**values)
            .returning(schema.limit_up_live_trace_snapshots)
        ).mappings().one()
    return dict(row)


def load_live_trace_dates(limit: int = TRACE_RETAIN_TRADE_DAYS) -> list[date]:
    statement = (
        select(schema.limit_up_live_trace_snapshots.c.trade_date)
        .distinct()
        .order_by(desc(schema.limit_up_live_trace_snapshots.c.trade_date))
        .limit(max(int(limit), 1))
    )
    with session_scope() as session:
        return list(session.execute(statement).scalars().all())


def load_live_trace_rows(
    trade_date: date,
    *,
    after_id: int | None = None,
) -> list[dict[str, object]]:
    statement = (
        select(schema.limit_up_live_trace_snapshots)
        .where(schema.limit_up_live_trace_snapshots.c.trade_date == trade_date)
        .order_by(
            schema.limit_up_live_trace_snapshots.c.captured_at,
            schema.limit_up_live_trace_snapshots.c.id,
        )
    )
    if after_id is not None:
        statement = statement.where(
            schema.limit_up_live_trace_snapshots.c.id > max(int(after_id), 0)
        )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def prune_live_trace_snapshots(
    retain_trade_days: int = TRACE_RETAIN_TRADE_DAYS,
) -> int:
    keep_count = max(int(retain_trade_days), 1)
    trade_dates = load_live_trace_dates(limit=keep_count + 1)
    cutoff = retention_cutoff(trade_dates, retain_trade_days=keep_count)
    if cutoff is None:
        return 0
    with session_scope() as session:
        result = session.execute(
            delete(schema.limit_up_live_trace_snapshots).where(
                schema.limit_up_live_trace_snapshots.c.trade_date < cutoff
            )
        )
    return max(int(result.rowcount or 0), 0)


def _prune_once_for_trade_date(trade_date: date) -> None:
    global _last_pruned_trade_date
    if _last_pruned_trade_date == trade_date:
        return
    with _prune_lock:
        if _last_pruned_trade_date == trade_date:
            return
        prune_live_trace_snapshots()
        _last_pruned_trade_date = trade_date


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    return None if value in (None, "") else _as_datetime(value)


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _trace_recommendations(value: object) -> dict[str, object]:
    recommendations = _mapping(value)
    lanes = _mapping(recommendations.get("lanes"))
    result: dict[str, object] = {
        "market_gate": _mapping(recommendations.get("market_gate")),
        "lanes": {
            channel: _project_rows(lanes.get(channel), TRACE_SIGNAL_FIELDS)
            for channel in ("now", "tail", "next_auction")
        },
    }
    for key in ("portfolio", "watchlist"):
        if key in recommendations:
            result[key] = _project_rows(recommendations.get(key), TRACE_SIGNAL_FIELDS)
    for key in ("board_lane_validations", "plan"):
        if key in recommendations:
            result[key] = recommendations[key]
    return result


def _project_rows(value: object, fields: Sequence[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        {key: row[key] for key in fields if key in row}
        for row in value
        if isinstance(row, Mapping)
    ]


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}
