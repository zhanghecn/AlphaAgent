"""Read-only inputs and coverage contracts for leader-cycle research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, tuple_

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up import (
    history_repository,
    lane_repository,
    radar_observation_repository,
    sentiment,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


EVIDENCE_LEVELS = frozenset(
    {
        "point_in_time_complete",
        "point_in_time_partial",
        "daily_only",
        "unavailable",
    }
)
PROPAGATION_HORIZONS_MINUTES = (1, 3, 5, 10)
MINIMUM_MEMBER_COVERAGE_RATIO = 0.90


def load_market_trade_dates(start: date, end: date) -> list[date]:
    _validate_range(start, end)
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .where(schema.stock_daily_bars.c.trade_date.between(start, end))
            .distinct()
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).scalars()
    return [value for value in rows if isinstance(value, date)]


@dataclass(frozen=True, slots=True)
class CoverageRow:
    dataset: str
    first_date: date | None
    last_date: date | None
    trade_day_count: int
    symbol_count: int
    symbol_day_count: int
    frame_count: int
    row_count: int
    evidence_level: str

    def __post_init__(self) -> None:
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise ValueError(f"unsupported evidence level: {self.evidence_level}")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def load_leader_cycle_inputs(
    start: date,
    end: date,
    *,
    compact: bool = False,
) -> dict[str, object]:
    """Load the bounded daily research inputs without copying formal gate SQL."""

    _validate_range(start, end)
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        if compact:
            daily_bars = _mapping_rows(
                session,
                select(schema.stock_daily_bars.c.trade_date)
                .where(schema.stock_daily_bars.c.trade_date.between(start, end))
                .distinct()
                .order_by(schema.stock_daily_bars.c.trade_date),
            )
            daily_coverage = _aggregate_coverage_row(
                session,
                "daily_bars",
                schema.stock_daily_bars,
                date_column=schema.stock_daily_bars.c.trade_date,
                symbol_column=schema.stock_daily_bars.c.vt_symbol,
                start=start,
                end=end,
                evidence_level="daily_only",
            )
        else:
            daily_bars = _mapping_rows(
                session,
                select(
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stocks.c.name,
                )
                .select_from(
                    schema.stock_daily_bars.join(
                        schema.stocks,
                        schema.stocks.c.vt_symbol == schema.stock_daily_bars.c.vt_symbol,
                    )
                )
                .where(schema.stock_daily_bars.c.trade_date.between(start, end))
                .order_by(
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.vt_symbol,
                ),
            )
            daily_coverage = None
        memberships = _mapping_rows(
            session,
            select(
                schema.stock_sector_membership_snapshots.c.snapshot_date,
                schema.stock_sector_membership_snapshots.c.vt_symbol,
                schema.stock_sector_membership_snapshots.c.sector_id,
                schema.stock_sector_membership_snapshots.c.sector_name,
                schema.stock_sector_membership_snapshots.c.sector_type,
            ).where(
                schema.stock_sector_membership_snapshots.c.snapshot_date.between(
                    start - timedelta(days=10),
                    end,
                ),
                schema.stock_sector_membership_snapshots.c.sector_type.in_(
                    ("concept", "theme", "industry")
                ),
            ),
        )
        membership_scopes = _mapping_rows(
            session,
            select(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date,
                schema.stock_sector_membership_snapshot_scopes.c.scope_type,
                schema.stock_sector_membership_snapshot_scopes.c.complete,
                schema.stock_sector_membership_snapshot_scopes.c.evidence_level,
            ).where(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date.between(
                    start - timedelta(days=10),
                    end,
                )
            ),
        )
        current_memberships = _mapping_rows(
            session,
            select(
                schema.stock_sector_memberships.c.vt_symbol,
                schema.stock_sector_memberships.c.sector_id,
                schema.stock_sector_memberships.c.sector_name,
                schema.stock_sector_memberships.c.sector_type,
            ).where(
                schema.stock_sector_memberships.c.sector_type.in_(("concept", "theme"))
            ),
        )
        fund_flows = _mapping_rows(
            session,
            select(
                schema.sector_fund_flow_snapshots.c.trade_date,
                schema.sector_fund_flow_snapshots.c.captured_at,
                schema.sector_fund_flow_snapshots.c.captured_minute,
                schema.sector_fund_flow_snapshots.c.sector_id,
                schema.sector_fund_flow_snapshots.c.sector_name,
                schema.sector_fund_flow_snapshots.c.sector_type,
                schema.sector_fund_flow_snapshots.c.main_net_inflow,
                schema.sector_fund_flow_snapshots.c.main_net_inflow_ratio,
                schema.sector_fund_flow_snapshots.c.rise_count,
                schema.sector_fund_flow_snapshots.c.fall_count,
                schema.sector_fund_flow_snapshots.c.rise_ratio,
            )
            .where(schema.sector_fund_flow_snapshots.c.trade_date.between(start, end))
            .order_by(schema.sector_fund_flow_snapshots.c.captured_at),
        )
        if compact:
            concept_strength = []
            concept_strength_coverage = _aggregate_coverage_row(
                session,
                "concept_strength",
                schema.limit_up_concept_strength_snapshots,
                date_column=schema.limit_up_concept_strength_snapshots.c.trade_date,
                symbol_column=schema.limit_up_concept_strength_snapshots.c.concept_id,
                frame_column=schema.limit_up_concept_strength_snapshots.c.captured_minute,
                start=start,
                end=end,
                evidence_level="point_in_time_partial",
            )
        else:
            concept_strength = _mapping_rows(
                session,
                select(
                    schema.limit_up_concept_strength_snapshots.c.trade_date,
                    schema.limit_up_concept_strength_snapshots.c.captured_at,
                    schema.limit_up_concept_strength_snapshots.c.captured_minute,
                    schema.limit_up_concept_strength_snapshots.c.membership_snapshot_date,
                    schema.limit_up_concept_strength_snapshots.c.concept_id,
                    schema.limit_up_concept_strength_snapshots.c.concept_name,
                    schema.limit_up_concept_strength_snapshots.c.concept_state,
                    schema.limit_up_concept_strength_snapshots.c.strength_score,
                    schema.limit_up_concept_strength_snapshots.c.strength_rank,
                    schema.limit_up_concept_strength_snapshots.c.strength_percentile,
                    schema.limit_up_concept_strength_snapshots.c.coverage_ratio,
                    schema.limit_up_concept_strength_snapshots.c.is_stale,
                )
                .where(
                    schema.limit_up_concept_strength_snapshots.c.trade_date.between(start, end)
                )
                .order_by(schema.limit_up_concept_strength_snapshots.c.captured_at),
            )
            concept_strength_coverage = None
        sentiment_points = sentiment.load_sentiment_points(session, start, end)
        minute_coverage = _load_minute_coverage(session, start, end)

    events, _, event_coverage = lane_repository.load_lane_research_data(
        start,
        end,
        include_financials=False,
    )
    radar_frames = radar_observation_repository.load_frames(start, end)
    radar_observations = (
        []
        if compact
        else radar_observation_repository.load_observations(start, end)
    )
    formal_replays = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        start,
        end,
        compact=True,
    )
    event_rows = list(events.values())
    coverage = _build_coverage_rows(
        daily_bars=daily_bars,
        minute_coverage=minute_coverage,
        events=event_rows,
        memberships=memberships,
        membership_scopes=membership_scopes,
        fund_flows=fund_flows,
        concept_strength=concept_strength,
        radar_frames=radar_frames,
        radar_observations=radar_observations,
        formal_replays=formal_replays,
        daily_coverage=daily_coverage,
        concept_strength_coverage=concept_strength_coverage,
    )
    return {
        "daily_bars": daily_bars,
        "minute_bars": [],
        "events": event_rows,
        "memberships": memberships,
        "membership_scopes": membership_scopes,
        "current_memberships": current_memberships,
        "fund_flows": fund_flows,
        "concept_strength": concept_strength,
        "radar": {
            "frames": radar_frames,
            "observations": radar_observations,
        },
        "formal_replays": formal_replays,
        "sentiment": sentiment_points,
        "coverage": coverage,
        "event_coverage": event_coverage,
        "supply_capabilities": inspect_data_supply_capabilities(),
    }


def load_intraday_propagation_inputs(
    trade_dates: Sequence[date],
) -> dict[str, object]:
    dates = sorted(set(trade_dates))
    if not dates:
        return {
            "minute_bars": [],
            "events": [],
            "memberships": [],
            "membership_scopes": [],
            "fund_flows": [],
            "concept_strength": [],
            "radar": {"frames": [], "observations": []},
        }
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        minute = schema.stock_minute_bars
        daily = schema.stock_daily_bars
        previous_close = (
            daily.c.close_price / func.nullif(1 + daily.c.change_pct / 100, 0)
        ).label("previous_close")
        minute_bars = _mapping_rows(
            session,
            select(
                minute.c.vt_symbol,
                minute.c.bar_time,
                minute.c.interval,
                minute.c.trade_date,
                minute.c.close_price,
                minute.c.high_price,
                minute.c.turnover,
                previous_close,
            )
            .select_from(
                minute.outerjoin(
                    daily,
                    (daily.c.vt_symbol == minute.c.vt_symbol)
                    & (daily.c.trade_date == minute.c.trade_date),
                )
            )
            .where(
                minute.c.trade_date.in_(dates),
                minute.c.interval == "1m",
            )
            .order_by(
                minute.c.trade_date,
                minute.c.vt_symbol,
                minute.c.bar_time,
            ),
        )
        memberships = _mapping_rows(
            session,
            select(
                schema.stock_sector_membership_snapshots.c.snapshot_date,
                schema.stock_sector_membership_snapshots.c.vt_symbol,
                schema.stock_sector_membership_snapshots.c.sector_id,
                schema.stock_sector_membership_snapshots.c.sector_name,
                schema.stock_sector_membership_snapshots.c.sector_type,
            ).where(
                schema.stock_sector_membership_snapshots.c.snapshot_date.between(
                    dates[0] - timedelta(days=10),
                    dates[-1],
                )
            ),
        )
        membership_scopes = _mapping_rows(
            session,
            select(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date,
                schema.stock_sector_membership_snapshot_scopes.c.scope_type,
                schema.stock_sector_membership_snapshot_scopes.c.complete,
                schema.stock_sector_membership_snapshot_scopes.c.evidence_level,
            ).where(
                schema.stock_sector_membership_snapshot_scopes.c.snapshot_date.between(
                    dates[0] - timedelta(days=10),
                    dates[-1],
                )
            ),
        )
        fund_flows = _mapping_rows(
            session,
            select(
                schema.sector_fund_flow_snapshots.c.trade_date,
                schema.sector_fund_flow_snapshots.c.captured_at,
                schema.sector_fund_flow_snapshots.c.captured_minute,
                schema.sector_fund_flow_snapshots.c.sector_id,
                schema.sector_fund_flow_snapshots.c.sector_name,
                schema.sector_fund_flow_snapshots.c.sector_type,
                schema.sector_fund_flow_snapshots.c.main_net_inflow,
                schema.sector_fund_flow_snapshots.c.main_net_inflow_ratio,
            ).where(
                schema.sector_fund_flow_snapshots.c.trade_date.in_(dates)
            ),
        )
        concept_strength = _mapping_rows(
            session,
            select(
                schema.limit_up_concept_strength_snapshots.c.trade_date,
                schema.limit_up_concept_strength_snapshots.c.captured_at,
                schema.limit_up_concept_strength_snapshots.c.captured_minute,
                schema.limit_up_concept_strength_snapshots.c.membership_snapshot_date,
                schema.limit_up_concept_strength_snapshots.c.concept_id,
                schema.limit_up_concept_strength_snapshots.c.concept_name,
                schema.limit_up_concept_strength_snapshots.c.strength_score,
                schema.limit_up_concept_strength_snapshots.c.coverage_ratio,
            ).where(
                schema.limit_up_concept_strength_snapshots.c.trade_date.in_(dates)
            ),
        )
    events, _, _ = lane_repository.load_lane_research_data(
        dates[0],
        dates[-1],
        include_financials=False,
    )
    selected_events = [
        event for event in events.values() if event.get("trade_date") in set(dates)
    ]
    return {
        "minute_bars": minute_bars,
        "events": selected_events,
        "memberships": memberships,
        "membership_scopes": membership_scopes,
        "fund_flows": fund_flows,
        "concept_strength": concept_strength,
        "radar": {
            "frames": radar_observation_repository.load_frames(dates[0], dates[-1]),
            "observations": [],
        },
    }


def evaluate_propagation_coverage(payload: Mapping[str, object]) -> dict[str, object]:
    events = _dict_rows(payload.get("events"))
    minutes = _dict_rows(payload.get("minute_bars"))
    memberships = _dict_rows(payload.get("memberships"))
    membership_scopes = _dict_rows(payload.get("membership_scopes"))
    controls = _dict_rows(payload.get("market_controls"))
    accepted: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    minute_index = _minute_index(minutes)
    complete_snapshot_dates = sorted(
        {
            parsed
            for row in membership_scopes
            if row.get("scope_type") == "concept"
            and row.get("complete") is True
            and (parsed := _date_value(row.get("snapshot_date"))) is not None
        }
    )
    members_by_snapshot_sector: dict[tuple[date, str], set[str]] = {}
    for row in memberships:
        snapshot_date = _date_value(row.get("snapshot_date"))
        sector_id = str(row.get("sector_id") or "")
        symbol = str(row.get("vt_symbol") or "")
        sector_type = str(row.get("sector_type") or "concept").lower()
        if (
            snapshot_date in complete_snapshot_dates
            and sector_type in {"concept", "theme"}
            and sector_id
            and symbol
        ):
            members_by_snapshot_sector.setdefault((snapshot_date, sector_id), set()).add(
                symbol
            )

    for event in events:
        reasons: list[str] = []
        trade_date = _date_value(event.get("trade_date"))
        ignition_at = _datetime_value(event.get("ignition_at"))
        symbol = str(event.get("vt_symbol") or "")
        sector_ids = {
            str(value) for value in event.get("sector_ids", ()) if str(value)
        }
        ignition_symbols = ({symbol} if symbol else set()) | {
            str(value)
            for value in event.get("ignition_symbols", ())
            if str(value)
        }
        latest_snapshot = max(
            (
                snapshot_date
                for snapshot_date in complete_snapshot_dates
                if trade_date is not None and snapshot_date < trade_date
            ),
            default=None,
        )
        all_member_symbols = set().union(
            *(
                members_by_snapshot_sector.get((latest_snapshot, sector_id), set())
                for sector_id in sector_ids
            )
        ) if latest_snapshot is not None and sector_ids else set()
        member_symbols = all_member_symbols - ignition_symbols
        if latest_snapshot is None or not all_member_symbols:
            reasons.append("prior_membership_unavailable")
        elif not member_symbols:
            reasons.append("no_members_after_excluding_ignition")
        if trade_date is None or ignition_at is None or not symbol:
            reasons.append("invalid_ignition_event")
        required_times = _required_minute_times(ignition_at) if ignition_at else ()
        covered_members = {
            member
            for member in member_symbols
            if all((member, moment) in minute_index for moment in required_times)
        }
        coverage_ratio = (
            len(covered_members) / len(member_symbols) if member_symbols else 0.0
        )
        if coverage_ratio < MINIMUM_MEMBER_COVERAGE_RATIO:
            reasons.append("member_minute_coverage_below_90pct")
        if required_times and not all(
            (ignition_symbol, moment) in minute_index
            for ignition_symbol in ignition_symbols
            for moment in required_times
        ):
            reasons.append("ignition_symbol_path_incomplete")
        control_available = bool(event.get("control_available")) or any(
            control.get("ignition_cluster_id") == event.get("ignition_cluster_id")
            for control in controls
        )
        if not control_available:
            reasons.append("matched_market_control_unavailable")
        evaluated = {
            **event,
            "membership_snapshot_date": latest_snapshot,
            "member_count": len(member_symbols),
            "covered_member_count": len(covered_members),
            "member_coverage_ratio": round(coverage_ratio, 4),
            "exclusion_reasons": sorted(set(reasons)),
        }
        (excluded if reasons else accepted).append(evaluated)
    return {
        "accepted_events": accepted,
        "excluded_events": excluded,
        "accepted_count": len(accepted),
        "excluded_count": len(excluded),
    }


def coverage_row_from_rows(
    dataset: str,
    rows: Sequence[Mapping[str, object]],
    *,
    date_field: str,
    symbol_field: str | None = None,
    frame_field: str | None = None,
    evidence_level: str,
) -> CoverageRow:
    dates = [_date_value(row.get(date_field)) for row in rows]
    valid_dates = [value for value in dates if value is not None]
    symbols = {
        str(row.get(symbol_field) or "")
        for row in rows
        if symbol_field and str(row.get(symbol_field) or "")
    }
    symbol_days = {
        (_date_value(row.get(date_field)), str(row.get(symbol_field) or ""))
        for row in rows
        if symbol_field
        and _date_value(row.get(date_field)) is not None
        and str(row.get(symbol_field) or "")
    }
    frames = {
        row.get(frame_field)
        for row in rows
        if frame_field and row.get(frame_field) is not None
    }
    return CoverageRow(
        dataset=dataset,
        first_date=min(valid_dates) if valid_dates else None,
        last_date=max(valid_dates) if valid_dates else None,
        trade_day_count=len(set(valid_dates)),
        symbol_count=len(symbols),
        symbol_day_count=len(symbol_days),
        frame_count=len(frames) if frame_field else len(rows),
        row_count=len(rows),
        evidence_level=evidence_level if rows else "unavailable",
    )


def inspect_data_supply_capabilities() -> dict[str, dict[str, str]]:
    return {
        "historical_point_in_time_memberships": {
            "status": "forward_only",
            "reason": "provider snapshots are captured prospectively with known_at metadata",
        },
        "historical_sector_minute_fund_flows": {
            "status": "forward_only",
            "reason": "the configured source exposes current intraday board snapshots",
        },
        "full_market_minute_bars": {
            "status": "forward_only",
            "reason": "existing bounded gap/tail imports do not establish historical full-market coverage",
        },
    }


def _build_coverage_rows(**datasets: object) -> tuple[CoverageRow, ...]:
    minute_coverage = datasets["minute_coverage"]
    minute_rows = minute_coverage if isinstance(minute_coverage, Mapping) else {}
    scopes = _dict_rows(datasets["membership_scopes"])
    concept_scopes = [row for row in scopes if row.get("scope_type") == "concept"]
    membership_complete = bool(concept_scopes) and all(
        row.get("complete") is True for row in concept_scopes
    )
    daily_coverage = datasets.get("daily_coverage")
    concept_strength_coverage = datasets.get("concept_strength_coverage")
    rows = [
        daily_coverage
        if isinstance(daily_coverage, CoverageRow)
        else coverage_row_from_rows(
            "daily_bars",
            _dict_rows(datasets["daily_bars"]),
            date_field="trade_date",
            symbol_field="vt_symbol",
            evidence_level="daily_only",
        ),
        _coverage_from_aggregate("minute_bars_1m", minute_rows.get("1m")),
        _coverage_from_aggregate("minute_bars_5m", minute_rows.get("5m")),
        coverage_row_from_rows(
            "events",
            _dict_rows(datasets["events"]),
            date_field="trade_date",
            symbol_field="vt_symbol",
            evidence_level="daily_only",
        ),
        coverage_row_from_rows(
            "memberships",
            _dict_rows(datasets["memberships"]),
            date_field="snapshot_date",
            symbol_field="vt_symbol",
            evidence_level=(
                "point_in_time_complete" if membership_complete else "point_in_time_partial"
            ),
        ),
        coverage_row_from_rows(
            "fund_flows",
            _dict_rows(datasets["fund_flows"]),
            date_field="trade_date",
            symbol_field="sector_id",
            frame_field="captured_minute",
            evidence_level="point_in_time_partial",
        ),
        concept_strength_coverage
        if isinstance(concept_strength_coverage, CoverageRow)
        else coverage_row_from_rows(
            "concept_strength",
            _dict_rows(datasets["concept_strength"]),
            date_field="trade_date",
            symbol_field="concept_id",
            frame_field="captured_minute",
            evidence_level="point_in_time_partial",
        ),
        coverage_row_from_rows(
            "radar",
            _dict_rows(datasets["radar_frames"]),
            date_field="trade_date",
            frame_field="id",
            evidence_level="point_in_time_partial",
        ),
        coverage_row_from_rows(
            "formal_replays",
            _dict_rows(datasets["formal_replays"]),
            date_field="trade_date",
            evidence_level="daily_only",
        ),
    ]
    return tuple(rows)


def _load_minute_coverage(session: Any, start: date, end: date) -> dict[str, object]:
    rows = session.execute(
        select(
            schema.stock_minute_bars.c.interval,
            func.min(schema.stock_minute_bars.c.trade_date),
            func.max(schema.stock_minute_bars.c.trade_date),
            func.count(func.distinct(schema.stock_minute_bars.c.trade_date)),
            func.count(func.distinct(schema.stock_minute_bars.c.vt_symbol)),
            func.count(
                func.distinct(
                    tuple_(
                        schema.stock_minute_bars.c.vt_symbol,
                        schema.stock_minute_bars.c.trade_date,
                    )
                )
            ),
            func.count(),
        )
        .where(schema.stock_minute_bars.c.trade_date.between(start, end))
        .group_by(schema.stock_minute_bars.c.interval)
    ).all()
    return {
        str(row[0]): {
            "first_date": row[1],
            "last_date": row[2],
            "trade_day_count": int(row[3] or 0),
            "symbol_count": int(row[4] or 0),
            "symbol_day_count": int(row[5] or 0),
            "row_count": int(row[6] or 0),
        }
        for row in rows
    }


def _aggregate_coverage_row(
    session: Any,
    dataset: str,
    table: Any,
    *,
    date_column: Any,
    symbol_column: Any,
    start: date,
    end: date,
    evidence_level: str,
    frame_column: Any | None = None,
) -> CoverageRow:
    row = session.execute(
        select(
            func.min(date_column),
            func.max(date_column),
            func.count(func.distinct(date_column)),
            func.count(func.distinct(symbol_column)),
            func.count(func.distinct(tuple_(symbol_column, date_column))),
            func.count(func.distinct(frame_column)) if frame_column is not None else func.count(),
            func.count(),
        )
        .select_from(table)
        .where(date_column.between(start, end))
    ).one()
    row_count = int(row[6] or 0)
    return CoverageRow(
        dataset=dataset,
        first_date=_date_value(row[0]),
        last_date=_date_value(row[1]),
        trade_day_count=int(row[2] or 0),
        symbol_count=int(row[3] or 0),
        symbol_day_count=int(row[4] or 0),
        frame_count=int(row[5] or 0),
        row_count=row_count,
        evidence_level=evidence_level if row_count else "unavailable",
    )


def _coverage_from_aggregate(dataset: str, value: object) -> CoverageRow:
    row = value if isinstance(value, Mapping) else {}
    row_count = int(row.get("row_count") or 0)
    return CoverageRow(
        dataset=dataset,
        first_date=_date_value(row.get("first_date")),
        last_date=_date_value(row.get("last_date")),
        trade_day_count=int(row.get("trade_day_count") or 0),
        symbol_count=int(row.get("symbol_count") or 0),
        symbol_day_count=int(row.get("symbol_day_count") or 0),
        frame_count=row_count,
        row_count=row_count,
        evidence_level="point_in_time_partial" if row_count else "unavailable",
    )


def _mapping_rows(session: Any, statement: object) -> list[dict[str, object]]:
    return [dict(row) for row in session.execute(statement).mappings().all()]


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _minute_index(rows: Sequence[Mapping[str, object]]) -> set[tuple[str, datetime]]:
    return {
        (str(row.get("vt_symbol") or ""), moment.replace(second=0, microsecond=0))
        for row in rows
        if (moment := _datetime_value(row.get("bar_time"))) is not None
    }


def _required_minute_times(ignition_at: datetime) -> tuple[datetime, ...]:
    anchor = ignition_at.replace(second=0, microsecond=0)
    return (anchor - timedelta(minutes=1),) + tuple(
        anchor + timedelta(minutes=minutes)
        for minutes in PROPAGATION_HORIZONS_MINUTES
    )


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("leader-cycle input range is reversed")
