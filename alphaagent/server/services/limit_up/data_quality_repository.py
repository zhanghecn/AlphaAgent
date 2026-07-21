"""Database coverage counts for the limit-up data-quality gate."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Date, Time, and_, case, cast, func, not_, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

LIMIT_EVENT_TYPES = ("limit_pool_zt", "limit_pool_zbgc")
ACTIVE_SESSION_STAGES = ("auction", "morning", "afternoon", "tail", "close_auction")
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
MIN_RELIABLE_DAILY_SYMBOLS = 3000
MIN_MEMBERSHIP_COVERAGE_PCT = 90.0
RADAR_FULL_SESSION_MINUTE_COUNT = 240


def load_data_quality_counts(
    history_version: str,
    live_version: str,
) -> dict[str, object]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        history = _history_counts(session, history_version)
        events = _event_counts(session)
        memberships = _membership_counts(session)
        stock_minute = _stock_minute_counts(session)
        stock_minute.update(_event_minute_pair_counts(session))
        minute_backfill = _minute_backfill_counts(session)
        sector_minute = _sector_minute_counts(session)
        auction = _auction_counts(session)
        forward = _forward_counts(session, live_version)
    return {
        "history": history,
        "events": events,
        "memberships": memberships,
        "stock_minute": stock_minute,
        "minute_backfill": minute_backfill,
        "sector_minute": sector_minute,
        "auction": auction,
        "tick_l2": {"trade_days": 0, "rows": 0, "mode": "not_collected"},
        "forward": forward,
    }


def load_membership_data_quality_counts() -> dict[str, object]:
    """Load only membership coverage for the dedicated import status endpoint."""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        return _membership_counts(session)


def load_event_minute_quality_counts() -> dict[str, object]:
    """Load only event-minute coverage and its retry ledger."""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        return {
            "stock_minute": _event_minute_pair_counts(session),
            "minute_backfill": _minute_backfill_counts(session),
        }


def list_missing_event_minute_pairs(
    limit: int = 20,
    *,
    provider: str = "tdx",
    as_of: datetime | None = None,
) -> list[dict[str, str]]:
    schema.ensure_schema_once(get_engine())
    event_pairs = _event_pairs()
    minute_exists = _event_minute_exists(event_pairs)
    attempts = schema.limit_up_minute_backfill_attempts
    capped_limit = min(max(int(limit), 1), 200)
    eligible_at = as_of or datetime.now(timezone.utc)
    with session_scope() as session:
        rows = session.execute(
            select(event_pairs.c.trade_date, event_pairs.c.vt_symbol)
            .select_from(
                event_pairs.outerjoin(
                    attempts,
                    and_(
                        event_pairs.c.vt_symbol == attempts.c.vt_symbol,
                        event_pairs.c.trade_date == attempts.c.trade_date,
                        attempts.c.provider == provider,
                    ),
                )
            )
            .where(
                not_(minute_exists),
                or_(
                    attempts.c.vt_symbol.is_(None),
                    attempts.c.next_retry_at.is_(None),
                    attempts.c.next_retry_at <= eligible_at,
                ),
            )
            .order_by(event_pairs.c.trade_date.desc(), event_pairs.c.vt_symbol)
            .limit(capped_limit)
        ).mappings().all()
    return [
        {"trade_date": _iso_date(row["trade_date"]) or "", "vt_symbol": str(row["vt_symbol"])}
        for row in rows
    ]


def list_missing_radar_minute_pairs(
    limit: int,
    *,
    provider: str,
    as_of: datetime,
) -> list[dict[str, object]]:
    """Return fresh observed symbol/date pairs with fewer than 240 1m bars."""

    schema.ensure_schema_once(get_engine())
    frames = schema.limit_up_radar_frames
    observations = schema.limit_up_radar_observations
    minute = schema.stock_minute_bars
    attempts = schema.limit_up_minute_backfill_attempts
    observed_pairs = (
        select(
            observations.c.vt_symbol.label("vt_symbol"),
            frames.c.trade_date.label("trade_date"),
        )
        .select_from(
            observations.join(frames, observations.c.frame_id == frames.c.id)
        )
        .where(
            frames.c.is_stale.is_(False),
            frames.c.quality_status == "ready",
            frames.c.source_trade_date == frames.c.trade_date,
        )
        .distinct()
        .subquery()
    )
    minute_counts = (
        select(
            observed_pairs.c.vt_symbol,
            observed_pairs.c.trade_date,
            func.count(
                func.distinct(func.date_trunc("minute", minute.c.bar_time))
            ).label("bar_count"),
        )
        .select_from(
            observed_pairs.outerjoin(
                minute,
                and_(
                    observed_pairs.c.vt_symbol == minute.c.vt_symbol,
                    observed_pairs.c.trade_date == minute.c.trade_date,
                    minute.c.interval == "1m",
                    _radar_minute_session_predicate(minute),
                ),
            )
        )
        .group_by(observed_pairs.c.vt_symbol, observed_pairs.c.trade_date)
        .subquery()
    )
    capped_limit = min(max(int(limit), 1), 300)
    statement = (
        select(minute_counts.c.trade_date, minute_counts.c.vt_symbol)
        .select_from(
            minute_counts.outerjoin(
                attempts,
                and_(
                    minute_counts.c.vt_symbol == attempts.c.vt_symbol,
                    minute_counts.c.trade_date == attempts.c.trade_date,
                    attempts.c.provider == provider,
                ),
            )
        )
        .where(
            func.coalesce(minute_counts.c.bar_count, 0)
            < RADAR_FULL_SESSION_MINUTE_COUNT,
            or_(
                attempts.c.vt_symbol.is_(None),
                attempts.c.next_retry_at.is_(None),
                attempts.c.next_retry_at <= as_of,
            ),
        )
        .order_by(minute_counts.c.trade_date, minute_counts.c.vt_symbol)
        .limit(capped_limit)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "trade_date": _iso_date(row["trade_date"]) or "",
            "vt_symbol": str(row["vt_symbol"]),
        }
        for row in rows
    ]


def radar_minute_path_complete(bar_count: int) -> bool:
    return max(int(bar_count), 0) >= RADAR_FULL_SESSION_MINUTE_COUNT


def list_retryable_minute_pairs(
    pairs: list[tuple[str, date]],
    *,
    provider: str,
    as_of: datetime,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Return requested pairs whose provider-scoped retry is due."""

    requested = sorted(
        {
            (str(vt_symbol).strip(), _date_value(trade_date))
            for vt_symbol, trade_date in pairs
            if str(vt_symbol).strip()
        },
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )
    if not requested:
        return []
    schema.ensure_schema_once(get_engine())
    attempts = schema.limit_up_minute_backfill_attempts
    with session_scope() as session:
        rows = session.execute(
            select(
                attempts.c.trade_date,
                attempts.c.vt_symbol,
                attempts.c.next_retry_at,
            ).where(
                attempts.c.provider == provider,
                tuple_(attempts.c.vt_symbol, attempts.c.trade_date).in_(requested),
            )
        ).mappings().all()
    retry_at = {
        (str(row["vt_symbol"]), _date_value(row["trade_date"])): row["next_retry_at"]
        for row in rows
    }
    retryable = [
        pair
        for pair in requested
        if pair not in retry_at
        or retry_at[pair] is None
        or retry_at[pair] <= as_of
    ]
    capped_limit = min(max(int(limit), 1), 200)
    return [
        {"trade_date": trade_date.isoformat(), "vt_symbol": vt_symbol}
        for vt_symbol, trade_date in retryable[:capped_limit]
    ]


def load_event_minute_pair_bar_counts(
    gaps: list[Mapping[str, object]],
) -> dict[tuple[str, date], int]:
    pairs = {
        (str(gap.get("vt_symbol") or ""), _date_value(gap.get("trade_date")))
        for gap in gaps
        if gap.get("vt_symbol") and gap.get("trade_date")
    }
    if not pairs:
        return {}
    schema.ensure_schema_once(get_engine())
    minute = schema.stock_minute_bars
    with session_scope() as session:
        rows = session.execute(
            select(minute.c.vt_symbol, minute.c.trade_date, func.count())
            .where(
                minute.c.interval == "1m",
                tuple_(minute.c.vt_symbol, minute.c.trade_date).in_(sorted(pairs)),
            )
            .group_by(minute.c.vt_symbol, minute.c.trade_date)
        ).all()
    counts = {(str(row[0]), _date_value(row[1])): int(row[2] or 0) for row in rows}
    return {pair: counts.get(pair, 0) for pair in pairs}


def load_radar_minute_pair_slot_counts(
    gaps: list[Mapping[str, object]],
) -> dict[tuple[str, date], int]:
    """Count distinct official A-share session minute slots per requested pair."""

    pairs = {
        (str(gap.get("vt_symbol") or ""), _date_value(gap.get("trade_date")))
        for gap in gaps
        if gap.get("vt_symbol") and gap.get("trade_date")
    }
    if not pairs:
        return {}
    schema.ensure_schema_once(get_engine())
    minute = schema.stock_minute_bars
    with session_scope() as session:
        rows = session.execute(
            select(
                minute.c.vt_symbol,
                minute.c.trade_date,
                func.count(
                    func.distinct(func.date_trunc("minute", minute.c.bar_time))
                ),
            )
            .where(
                minute.c.interval == "1m",
                tuple_(minute.c.vt_symbol, minute.c.trade_date).in_(sorted(pairs)),
                _radar_minute_session_predicate(minute),
            )
            .group_by(minute.c.vt_symbol, minute.c.trade_date)
        ).all()
    counts = {(str(row[0]), _date_value(row[1])): int(row[2] or 0) for row in rows}
    return {pair: counts.get(pair, 0) for pair in pairs}


def _radar_minute_session_predicate(minute):
    minute_time = cast(minute.c.bar_time, Time)
    return or_(
        minute_time.between(time(9, 31), time(11, 30)),
        minute_time.between(time(13, 1), time(15, 0)),
    )


def record_minute_backfill_attempts(
    attempts: list[Mapping[str, object]],
    *,
    provider: str,
    attempted_at: datetime,
) -> None:
    normalized = [_normalized_attempt(item) for item in attempts]
    if not normalized:
        return
    schema.ensure_schema_once(get_engine())
    table = schema.limit_up_minute_backfill_attempts
    keys = [(item["vt_symbol"], item["trade_date"]) for item in normalized]
    with session_scope() as session:
        existing_rows = session.execute(
            select(table.c.vt_symbol, table.c.trade_date, table.c.attempt_count).where(
                table.c.provider == provider,
                tuple_(table.c.vt_symbol, table.c.trade_date).in_(keys),
            )
        ).all()
        existing_counts = {
            (str(row[0]), _date_value(row[1])): int(row[2] or 0)
            for row in existing_rows
        }
        values = []
        for item in normalized:
            key = (item["vt_symbol"], item["trade_date"])
            attempt_count = existing_counts.get(key, 0) + 1
            status = item["status"]
            values.append(
                {
                    **item,
                    "provider": provider,
                    "attempt_count": attempt_count,
                    "last_error": item["last_error"] if status == "error" else None,
                    "last_attempt_at": attempted_at,
                    "next_retry_at": (
                        None
                        if status == "covered"
                        else minute_backfill_retry_at(attempted_at, attempt_count)
                    ),
                    "updated_at": attempted_at,
                }
            )
        statement = pg_insert(table).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.vt_symbol, table.c.trade_date, table.c.provider],
            set_={
                "status": statement.excluded.status,
                "attempt_count": statement.excluded.attempt_count,
                "last_rows_read": statement.excluded.last_rows_read,
                "last_error": statement.excluded.last_error,
                "last_attempt_at": statement.excluded.last_attempt_at,
                "next_retry_at": statement.excluded.next_retry_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        session.execute(statement)


def minute_backfill_retry_at(attempted_at: datetime, attempt_count: int) -> datetime:
    if attempt_count <= 1:
        days = 1
    elif attempt_count == 2:
        days = 3
    else:
        days = 14
    return attempted_at + timedelta(days=days)


def _history_counts(session, version: str) -> dict[str, object]:
    row = session.execute(
        select(
            func.min(schema.limit_up_history_replays.c.trade_date),
            func.max(schema.limit_up_history_replays.c.trade_date),
            func.count(),
        ).where(schema.limit_up_history_replays.c.strategy_version == version)
    ).one()
    return {
        "start": _iso_date(row[0]),
        "end": _iso_date(row[1]),
        "trade_days": int(row[2] or 0),
    }


def _event_counts(session) -> dict[str, object]:
    events = _valid_event_rows()
    raw = events.c.raw
    first_touch = func.coalesce(raw["首次封板时间"].astext, raw["涨停时间"].astext)
    open_path = func.coalesce(raw["炸板次数"].astext, raw["开板次数"].astext)
    last_seal = raw["最后封板时间"].astext
    seal_amount = func.coalesce(raw["封板资金"].astext, raw["涨停封单量"].astext)
    row = session.execute(
        select(
            func.min(events.c.trade_date),
            func.max(events.c.trade_date),
            func.count(func.distinct(events.c.trade_date)),
            func.count(),
            func.count().filter(events.c.event_type == "limit_pool_zt"),
            func.count().filter(events.c.event_type == "limit_pool_zbgc"),
            func.count().filter(first_touch.is_not(None)),
            func.count().filter(
                and_(events.c.event_type == "limit_pool_zt", last_seal.is_not(None))
            ),
            func.count().filter(open_path.is_not(None)),
            func.count().filter(
                and_(events.c.event_type == "limit_pool_zt", seal_amount.is_not(None))
            ),
        )
        .select_from(events)
    ).one()
    return {
        "start": _iso_date(row[0]),
        "end": _iso_date(row[1]),
        "trade_days": int(row[2] or 0),
        "rows": int(row[3] or 0),
        "sealed_rows": int(row[4] or 0),
        "failed_rows": int(row[5] or 0),
        "first_touch_rows": int(row[6] or 0),
        "last_seal_rows": int(row[7] or 0),
        "open_path_rows": int(row[8] or 0),
        "seal_amount_rows": int(row[9] or 0),
    }


def _membership_counts(session) -> dict[str, object]:
    current_row = session.execute(
        select(
            func.count(),
            func.count(func.distinct(schema.stock_sector_memberships.c.vt_symbol)),
        )
    ).one()
    raw_row = session.execute(_membership_scope_counts_query()).one()
    if int(raw_row[3] or 0) == 0:
        industry_row = concept_row = (None, None, 0, 0, 0)
        qualifying_row = (None, None, 0)
    else:
        industry_row = session.execute(_membership_scope_counts_query("industry")).one()
        concept_row = session.execute(_membership_scope_counts_query("concept")).one()
        if int(industry_row[3] or 0) == 0:
            qualifying_row = (None, None, 0)
        else:
            qualifying_dates = _qualifying_membership_dates_query().subquery()
            qualifying_row = session.execute(
                select(
                    func.min(qualifying_dates.c.trade_date),
                    func.max(qualifying_dates.c.trade_date),
                    func.count(),
                )
            ).one()
    point_in_time_trade_days = int(qualifying_row[2] or 0)
    return {
        "mode": (
            "daily_point_in_time_industry_snapshot"
            if point_in_time_trade_days
            else "current_snapshot"
        ),
        "start": _iso_date(qualifying_row[0]),
        "end": _iso_date(qualifying_row[1]),
        "rows": int(industry_row[3] or 0),
        "symbols": int(industry_row[4] or 0),
        "point_in_time_trade_days": point_in_time_trade_days,
        "minimum_daily_symbols": MIN_RELIABLE_DAILY_SYMBOLS,
        "minimum_coverage_pct": MIN_MEMBERSHIP_COVERAGE_PCT,
        "raw_start": _iso_date(raw_row[0]),
        "raw_end": _iso_date(raw_row[1]),
        "raw_snapshot_trade_days": int(raw_row[2] or 0),
        "raw_rows": int(raw_row[3] or 0),
        "raw_symbols": int(raw_row[4] or 0),
        "industry_start": _iso_date(industry_row[0]),
        "industry_end": _iso_date(industry_row[1]),
        "industry_snapshot_trade_days": int(industry_row[2] or 0),
        "industry_rows": int(industry_row[3] or 0),
        "industry_symbols": int(industry_row[4] or 0),
        "concept_start": _iso_date(concept_row[0]),
        "concept_end": _iso_date(concept_row[1]),
        "concept_snapshot_trade_days": int(concept_row[2] or 0),
        "concept_rows": int(concept_row[3] or 0),
        "concept_symbols": int(concept_row[4] or 0),
        "current_rows": int(current_row[0] or 0),
        "current_symbols": int(current_row[1] or 0),
    }


def _membership_scope_counts_query(sector_type: str | None = None):
    snapshots = schema.stock_sector_membership_snapshots
    trading_dates = _trading_dates()
    statement = (
        select(
            func.min(snapshots.c.snapshot_date),
            func.max(snapshots.c.snapshot_date),
            func.count(func.distinct(snapshots.c.snapshot_date)),
            func.count(),
            func.count(func.distinct(snapshots.c.vt_symbol)),
        )
        .select_from(
            snapshots.join(
                trading_dates,
                snapshots.c.snapshot_date == trading_dates.c.trade_date,
            )
        )
    )
    if sector_type:
        statement = statement.where(snapshots.c.sector_type == sector_type)
    return statement


def _qualifying_membership_dates_query():
    """Return reliable dates whose industry snapshots cover at least 90%."""

    snapshots = schema.stock_sector_membership_snapshots
    industry_dates = (
        select(snapshots.c.snapshot_date.label("trade_date"))
        .where(snapshots.c.sector_type == "industry")
        .distinct()
        .cte("industry_membership_dates")
    )
    daily = (
        select(
            schema.stock_daily_bars.c.trade_date.label("trade_date"),
            schema.stock_daily_bars.c.vt_symbol.label("vt_symbol"),
        )
        .select_from(
            schema.stock_daily_bars.join(
                schema.stocks,
                schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
            ).join(
                industry_dates,
                industry_dates.c.trade_date == schema.stock_daily_bars.c.trade_date,
            )
        )
        .where(_eligible_main_board_stock_condition())
        .distinct()
        .cte("eligible_daily_membership_symbols")
    )
    reliable_dates = (
        select(schema.stock_daily_bars.c.trade_date.label("trade_date"))
        .select_from(
            schema.stock_daily_bars.join(
                industry_dates,
                industry_dates.c.trade_date == schema.stock_daily_bars.c.trade_date,
            )
        )
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
            >= MIN_RELIABLE_DAILY_SYMBOLS
        )
        .cte("reliable_membership_dates")
    )
    expected = (
        select(
            daily.c.trade_date,
            func.count(func.distinct(daily.c.vt_symbol)).label("expected_count"),
        )
        .select_from(
            daily.join(
                reliable_dates,
                reliable_dates.c.trade_date == daily.c.trade_date,
            )
        )
        .group_by(daily.c.trade_date)
        .cte("expected_membership_symbols")
    )
    covered = (
        select(
            daily.c.trade_date,
            func.count(func.distinct(snapshots.c.vt_symbol)).label("covered_count"),
        )
        .select_from(
            daily.join(
                snapshots,
                and_(
                    snapshots.c.snapshot_date == daily.c.trade_date,
                    snapshots.c.vt_symbol == daily.c.vt_symbol,
                ),
            )
        )
        .where(snapshots.c.sector_type == "industry")
        .group_by(daily.c.trade_date)
        .cte("covered_membership_symbols")
    )
    covered_count = func.coalesce(covered.c.covered_count, 0)
    return (
        select(
            expected.c.trade_date,
            expected.c.expected_count,
            covered_count.label("covered_count"),
        )
        .select_from(
            expected.outerjoin(
                covered,
                covered.c.trade_date == expected.c.trade_date,
            )
        )
        .where(
            covered_count * 100.0
            >= expected.c.expected_count * MIN_MEMBERSHIP_COVERAGE_PCT
        )
    )


def _stock_minute_counts(session) -> dict[str, object]:
    estimated_bars = session.execute(
        text(
            """
            SELECT GREATEST(
                table_stats.n_live_tup
                * COALESCE(interval_stats.one_minute_fraction, 1),
                0
            )::bigint
            FROM pg_stat_user_tables AS table_stats
            LEFT JOIN LATERAL (
                SELECT frequency.frequency AS one_minute_fraction
                FROM pg_stats AS column_stats
                CROSS JOIN LATERAL json_array_elements_text(
                    to_json(column_stats.most_common_vals)
                ) WITH ORDINALITY AS value(item, ordinal)
                JOIN LATERAL unnest(
                    column_stats.most_common_freqs
                ) WITH ORDINALITY AS frequency(frequency, ordinal)
                    USING (ordinal)
                WHERE column_stats.schemaname = table_stats.schemaname
                  AND column_stats.tablename = table_stats.relname
                  AND column_stats.attname = 'interval'
                  AND value.item = '1m'
                LIMIT 1
            ) AS interval_stats ON TRUE
            WHERE table_stats.schemaname = current_schema()
              AND table_stats.relname = 'stock_minute_bars'
            """
        )
    ).scalar_one()
    return {
        "bars": int(estimated_bars or 0),
        "bar_count_mode": "postgres_statistics_estimate",
    }


def _event_minute_pair_counts(session) -> dict[str, object]:
    event_pairs = _event_pairs()
    total = session.execute(select(func.count()).select_from(event_pairs)).scalar_one()
    covered = session.execute(
        select(
            func.min(event_pairs.c.trade_date),
            func.max(event_pairs.c.trade_date),
            func.count(func.distinct(event_pairs.c.trade_date)),
            func.count(func.distinct(event_pairs.c.vt_symbol)),
            func.count(),
        )
        .select_from(event_pairs)
        .where(_event_minute_exists(event_pairs))
    ).one()
    return {
        "start": _iso_date(covered[0]),
        "end": _iso_date(covered[1]),
        "trade_days": int(covered[2] or 0),
        "symbols": int(covered[3] or 0),
        "event_pairs": int(total or 0),
        "covered_event_pairs": int(covered[4] or 0),
        "coverage_scope": "limit_up_event_pairs",
    }


def _event_minute_exists(event_pairs):
    minute = schema.stock_minute_bars
    return (
        select(1)
        .select_from(minute)
        .where(
            minute.c.vt_symbol == event_pairs.c.vt_symbol,
            minute.c.trade_date == event_pairs.c.trade_date,
            minute.c.interval == "1m",
        )
        .correlate(event_pairs)
        .exists()
    )


def _minute_backfill_counts(session, provider: str = "tdx") -> dict[str, object]:
    attempts = schema.limit_up_minute_backfill_attempts
    event_pairs = _event_pairs()
    now = datetime.now(timezone.utc)
    pending = attempts.c.status != "covered"
    row = session.execute(
        select(
            func.count(),
            func.count().filter(attempts.c.status == "covered"),
            func.count().filter(attempts.c.status == "empty"),
            func.count().filter(attempts.c.status == "error"),
            func.count().filter(and_(pending, attempts.c.next_retry_at > now)),
            func.count().filter(
                and_(
                    pending,
                    or_(attempts.c.next_retry_at.is_(None), attempts.c.next_retry_at <= now),
                )
            ),
            func.max(attempts.c.last_attempt_at),
            func.min(attempts.c.next_retry_at).filter(attempts.c.next_retry_at > now),
        )
        .select_from(
            attempts.join(
                event_pairs,
                and_(
                    attempts.c.vt_symbol == event_pairs.c.vt_symbol,
                    attempts.c.trade_date == event_pairs.c.trade_date,
                ),
            )
        )
        .where(attempts.c.provider == provider)
    ).one()
    return {
        "provider": provider,
        "attempted_pair_count": int(row[0] or 0),
        "covered_pair_count": int(row[1] or 0),
        "empty_pair_count": int(row[2] or 0),
        "error_pair_count": int(row[3] or 0),
        "cooling_down_pair_count": int(row[4] or 0),
        "retryable_pair_count": int(row[5] or 0),
        "last_attempt_at": _iso_datetime(row[6]),
        "next_retry_at": _iso_datetime(row[7]),
    }


def _event_pairs():
    events = _valid_event_rows()
    return (
        select(
            events.c.vt_symbol,
            events.c.trade_date,
        )
        .distinct()
        .subquery()
    )


def _valid_event_rows():
    event_date = schema.stock_events.c.event_date
    parsed_event_date = case(
        (func.length(event_date) == 8, func.to_date(event_date, "YYYYMMDD")),
        else_=cast(event_date, Date),
    )
    ranked = (
        select(
            schema.stock_events.c.vt_symbol.label("vt_symbol"),
            parsed_event_date.label("trade_date"),
            schema.stock_events.c.event_type.label("event_type"),
            schema.stock_events.c.raw.label("raw"),
            func.row_number()
            .over(
                partition_by=(schema.stock_events.c.vt_symbol, parsed_event_date),
                order_by=(
                    schema.stock_events.c.updated_at.desc(),
                    schema.stock_events.c.created_at.desc(),
                    schema.stock_events.c.id.desc(),
                ),
            )
            .label("event_snapshot_rank"),
        )
        .select_from(
            schema.stock_events.join(
                schema.stocks,
                schema.stock_events.c.vt_symbol == schema.stocks.c.vt_symbol,
            ).join(
                schema.stock_daily_bars,
                and_(
                    schema.stock_daily_bars.c.vt_symbol == schema.stock_events.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date == parsed_event_date,
                ),
            )
        )
        .where(
            schema.stock_events.c.event_type.in_(LIMIT_EVENT_TYPES),
            _eligible_main_board_stock_condition(),
        )
        .subquery()
    )
    return (
        select(
            ranked.c.vt_symbol,
            ranked.c.trade_date,
            ranked.c.event_type,
            ranked.c.raw,
        )
        .where(ranked.c.event_snapshot_rank == 1)
        .subquery()
    )


def _eligible_main_board_stock_condition():
    symbol = schema.stocks.c.symbol
    exchange = schema.stocks.c.exchange
    normalized_name = func.upper(func.replace(func.coalesce(schema.stocks.c.name, ""), "*", ""))
    excluded_name = or_(
        normalized_name.contains("ST"),
        normalized_name.contains("退"),
        normalized_name.startswith("S"),
        normalized_name.startswith("N"),
        normalized_name.startswith("C"),
    )
    return and_(
        or_(
            and_(
                exchange == "SSE",
                or_(*(symbol.startswith(prefix) for prefix in MAIN_BOARD_PREFIXES[:4])),
            ),
            and_(
                exchange == "SZSE",
                or_(*(symbol.startswith(prefix) for prefix in MAIN_BOARD_PREFIXES[4:])),
            ),
        ),
        not_(excluded_name),
    )


def _sector_minute_counts(session) -> dict[str, object]:
    daily_snapshot_days = session.execute(
        select(func.count(func.distinct(schema.sector_fund_flows.c.trade_date)))
    ).scalar_one()
    snapshots = schema.sector_fund_flow_snapshots
    trading_dates = _trading_dates()
    eligible = and_(
        snapshots.c.period.in_(("即时", "今日", "1日", "当日")),
        snapshots.c.session_stage.in_(("auction", "morning", "afternoon", "tail")),
        snapshots.c.is_stale == False,  # noqa: E712
        snapshots.c.main_net_inflow.is_not(None),
    )
    row = session.execute(
        select(
            func.min(snapshots.c.trade_date),
            func.max(snapshots.c.trade_date),
            func.count(func.distinct(snapshots.c.trade_date)),
            func.count(),
            func.count(func.distinct(snapshots.c.captured_minute)),
            func.count().filter(snapshots.c.rise_count.is_not(None)),
        )
        .select_from(
            snapshots.join(
                trading_dates,
                snapshots.c.trade_date == trading_dates.c.trade_date,
            )
        )
        .where(eligible)
    ).one()
    trade_days = int(row[2] or 0)
    return {
        "start": _iso_date(row[0]),
        "end": _iso_date(row[1]),
        "trade_days": trade_days,
        "rows": int(row[3] or 0),
        "snapshot_count": int(row[4] or 0),
        "breadth_rows": int(row[5] or 0),
        "mode": (
            "intraday_append_only_snapshot"
            if trade_days
            else "daily_latest_snapshot_only"
        ),
        "daily_snapshot_trade_days": int(daily_snapshot_days or 0),
    }


def _auction_counts(session) -> dict[str, object]:
    snapshots = schema.stock_auction_snapshots
    trading_dates = _trading_dates()
    daily = (
        select(
            snapshots.c.trade_date.label("trade_date"),
            func.count().label("rows"),
            func.count().filter(snapshots.c.strict_complete == True).label("strict_rows"),  # noqa: E712
        )
        .select_from(
            snapshots.join(
                trading_dates,
                snapshots.c.trade_date == trading_dates.c.trade_date,
            )
        )
        .group_by(snapshots.c.trade_date)
        .subquery()
    )
    daily_row = session.execute(
        select(
            func.min(daily.c.trade_date),
            func.max(daily.c.trade_date),
            func.count(),
            func.count().filter(
                and_(
                    daily.c.rows > 0,
                    daily.c.strict_rows >= daily.c.rows * 0.95,
                )
            ),
            func.coalesce(func.sum(daily.c.rows), 0),
            func.coalesce(func.sum(daily.c.strict_rows), 0),
        )
    ).one()
    field_row = session.execute(
        select(
            func.count().filter(snapshots.c.auction_price.is_not(None)),
            func.count().filter(snapshots.c.matched_volume.is_not(None)),
            func.count().filter(snapshots.c.matched_amount.is_not(None)),
            func.count().filter(snapshots.c.unmatched_volume.is_not(None)),
            func.count().filter(snapshots.c.source_updated_at.is_not(None)),
        )
        .select_from(
            snapshots.join(
                trading_dates,
                snapshots.c.trade_date == trading_dates.c.trade_date,
            )
        )
    ).one()
    trade_days = int(daily_row[2] or 0)
    strict_trade_days = int(daily_row[3] or 0)
    return {
        "start": _iso_date(daily_row[0]),
        "end": _iso_date(daily_row[1]),
        "trade_days": trade_days,
        "strict_trade_days": strict_trade_days,
        "rows": int(daily_row[4] or 0),
        "strict_rows": int(daily_row[5] or 0),
        "price_rows": int(field_row[0] or 0),
        "matched_volume_rows": int(field_row[1] or 0),
        "matched_amount_rows": int(field_row[2] or 0),
        "unmatched_volume_rows": int(field_row[3] or 0),
        "source_time_rows": int(field_row[4] or 0),
        "mode": (
            "strict_auction_snapshot"
            if trade_days and strict_trade_days == trade_days
            else "partial_auction_snapshot"
            if trade_days
            else "not_collected"
        ),
    }


def _trading_dates():
    return (
        select(schema.stock_daily_bars.c.trade_date.label("trade_date"))
        .distinct()
        .subquery()
    )


def _forward_counts(session, live_version: str) -> dict[str, object]:
    snapshots = schema.limit_up_signal_snapshots
    trading_dates = select(schema.stock_daily_bars.c.trade_date).distinct().subquery()
    local_capture_date = cast(func.timezone("Asia/Shanghai", snapshots.c.captured_at), Date)
    base = snapshots.c.strategy_version == live_version
    eligible = and_(
        base,
        snapshots.c.mode == "live_snapshot",
        snapshots.c.session_stage.in_(ACTIVE_SESSION_STAGES),
        snapshots.c.data_quality["is_stale"].astext == "false",
        local_capture_date == snapshots.c.trade_date,
    )
    raw_row = session.execute(
        select(
            func.count(),
            func.min(snapshots.c.trade_date),
            func.max(snapshots.c.trade_date),
        ).where(base)
    ).one()
    eligible_row = session.execute(
        select(
            func.count(),
            func.count(func.distinct(snapshots.c.trade_date)),
        )
        .select_from(
            snapshots.join(
                trading_dates,
                snapshots.c.trade_date == trading_dates.c.trade_date,
            )
        )
        .where(eligible)
    ).one()
    return {
        "start": _iso_date(raw_row[1]),
        "end": _iso_date(raw_row[2]),
        "raw_snapshot_count": int(raw_row[0] or 0),
        "eligible_snapshot_count": int(eligible_row[0] or 0),
        "eligible_trade_days": int(eligible_row[1] or 0),
    }


def _iso_date(value: object) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or None


def _iso_datetime(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "").strip()
    return text or None


def _date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _normalized_attempt(item: Mapping[str, object]) -> dict[str, object]:
    status = str(item.get("status") or "error")
    if status not in {"covered", "empty", "error"}:
        raise ValueError(f"Unsupported minute backfill attempt status: {status}")
    return {
        "vt_symbol": str(item.get("vt_symbol") or ""),
        "trade_date": _date_value(item.get("trade_date")),
        "status": status,
        "last_rows_read": max(int(item.get("last_rows_read") or 0), 0),
        "last_error": str(item.get("last_error") or "")[:1000] or None,
    }
