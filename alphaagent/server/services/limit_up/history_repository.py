"""Database access for versioned point-in-time limit-up history replays."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import and_, delete, func, not_, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

MIN_RELIABLE_DAILY_SYMBOLS = 3000
HISTORY_LOOKBACK_DATES = 35
HISTORY_REPLAY_WRITE_BATCH_SIZE = 20
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
HISTORY_INPUT_TABLES = (
    schema.stocks,
    schema.stock_daily_bars,
    schema.stock_minute_bars,
    schema.stock_financial_reports,
    schema.stock_events,
    schema.stock_sector_memberships,
    schema.stock_sector_membership_snapshots,
)


def reliable_date_window(
    counts: Sequence[tuple[date, int]],
    *,
    min_symbols: int = MIN_RELIABLE_DAILY_SYMBOLS,
) -> list[date]:
    dates = [trade_date for trade_date, count in counts if int(count) >= min_symbols]
    if not dates:
        raise ValueError("reliable daily history is unavailable")
    return sorted(set(dates))


def history_inputs_newer_than_ledger(strategy_version: str) -> bool:
    """Return whether persisted replay inputs changed after the last rebuild."""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        ledger_updated_at = session.execute(
            select(func.max(schema.limit_up_history_replays.c.updated_at)).where(
                schema.limit_up_history_replays.c.strategy_version
                == strategy_version
            )
        ).scalar()
        if ledger_updated_at is None:
            return True

        for table in HISTORY_INPUT_TABLES:
            updated_at = session.execute(
                select(func.max(table.c.updated_at))
            ).scalar()
            if updated_at is not None and updated_at > ledger_updated_at:
                return True
        return False


def history_ledger_updated_at(strategy_version: str) -> datetime | None:
    """Return the latest write time for one persisted replay ledger."""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        return session.execute(
            select(func.max(schema.limit_up_history_replays.c.updated_at)).where(
                schema.limit_up_history_replays.c.strategy_version
                == strategy_version
            )
        ).scalar_one_or_none()


def load_reliable_history_frame(
    *,
    min_symbols: int = MIN_RELIABLE_DAILY_SYMBOLS,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load the complete daily window plus enough leading bars for lag features."""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        count_rows = session.execute(
            select(
                schema.stock_daily_bars.c.trade_date,
                func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)),
            )
            .group_by(schema.stock_daily_bars.c.trade_date)
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()
        reliable_dates = reliable_date_window(
            [(row[0], int(row[1])) for row in count_rows],
            min_symbols=min_symbols,
        )
        first_reliable = reliable_dates[0]
        last_reliable = reliable_dates[-1]
        lookback_dates = [row[0] for row in count_rows if row[0] < first_reliable][
            -HISTORY_LOOKBACK_DATES:
        ]
        load_start = lookback_dates[0] if lookback_dates else first_reliable

    symbol = schema.stocks.c.symbol
    name = schema.stocks.c.name
    main_board = or_(
        and_(
            schema.stocks.c.exchange == "SSE",
            or_(*(symbol.startswith(prefix) for prefix in MAIN_BOARD_PREFIXES[:4])),
        ),
        and_(
            schema.stocks.c.exchange == "SZSE",
            or_(*(symbol.startswith(prefix) for prefix in MAIN_BOARD_PREFIXES[4:])),
        ),
    )
    excluded_name = or_(
        name.ilike("%ST%"),
        name.contains("退市"),
        name.startswith("退"),
    )
    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.turnover_rate,
            schema.stock_daily_bars.c.change_pct,
            schema.stocks.c.symbol,
            schema.stocks.c.name,
            schema.stocks.c.industry,
            schema.stocks.c.exchange,
        )
        .select_from(
            schema.stock_daily_bars.join(
                schema.stocks,
                schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_daily_bars.c.trade_date.between(load_start, last_reliable),
            main_board,
            not_(excluded_name),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    frame = pd.read_sql(statement, get_engine(), parse_dates=["trade_date"])
    frame, industry_coverage = _attach_primary_industries(frame)
    coverage = {
        "status": "ready",
        "reliable_start": first_reliable.isoformat(),
        "reliable_end": last_reliable.isoformat(),
        "reliable_trade_days": len(reliable_dates),
        "minimum_daily_symbols": min_symbols,
        "load_start": load_start.isoformat(),
        "loaded_rows": int(len(frame)),
        "universe": "current_main_board_non_st",
        "survivorship_risk": "current_universe_survivorship_risk",
        **industry_coverage,
    }
    return frame, coverage


def _attach_primary_industries(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Attach daily industries first and use current membership only as fallback."""

    if frame.empty:
        return frame.copy(), {
            "industry_membership_mode": "unavailable",
            "industry_membership_symbols": 0,
            "industry_membership_point_in_time_rows": 0,
            "industry_membership_current_proxy_rows": 0,
            "industry_membership_unclassified_rows": 0,
            "industry_membership_survivorship_risk": True,
        }

    engine = get_engine()
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce")
    start_date = result["trade_date"].min().date()
    end_date = result["trade_date"].max().date()
    snapshots = pd.read_sql(
        select(
            schema.stock_sector_membership_snapshots.c.snapshot_date,
            schema.stock_sector_membership_snapshots.c.vt_symbol,
            schema.stock_sector_membership_snapshots.c.sector_id.label("industry_id"),
            schema.stock_sector_membership_snapshots.c.sector_name.label("industry_name"),
            schema.stock_sector_membership_snapshots.c.rank,
        ).where(
            schema.stock_sector_membership_snapshots.c.sector_type == "industry",
            schema.stock_sector_membership_snapshots.c.snapshot_date.between(
                start_date,
                end_date,
            ),
        ),
        engine,
    )
    point_in_time = _primary_snapshot_industries(snapshots)
    if not point_in_time.empty:
        result = result.merge(
            point_in_time,
            left_on=["trade_date", "vt_symbol"],
            right_on=["snapshot_date", "vt_symbol"],
            how="left",
            sort=False,
        ).drop(columns=["snapshot_date"])
    else:
        result["industry_id"] = pd.NA
        result["industry_name"] = pd.NA

    current = _load_current_primary_industries(engine)
    current = current.rename(
        columns={
            "industry_id": "current_industry_id",
            "industry_name": "current_industry_name",
        }
    )
    if current.empty:
        result["current_industry_id"] = pd.NA
        result["current_industry_name"] = pd.NA
    else:
        result = result.merge(current, on="vt_symbol", how="left", sort=False)

    point_in_time_mask = result["industry_id"].notna()
    current_membership_mask = ~point_in_time_mask & result["current_industry_id"].notna()
    stock_industry = result.get("industry", pd.Series(index=result.index, dtype=object))
    stock_proxy_mask = (
        ~point_in_time_mask
        & ~current_membership_mask
        & stock_industry.notna()
        & stock_industry.astype(str).str.strip().ne("")
    )
    result["industry_id"] = (
        result["industry_id"]
        .combine_first(result["current_industry_id"])
        .fillna("UNCLASSIFIED")
    )
    result["industry_name"] = (
        result["industry_name"]
        .combine_first(result["current_industry_name"])
        .fillna(stock_industry)
        .fillna("未分类")
    )
    result["industry_membership_source"] = "unclassified"
    result.loc[stock_proxy_mask, "industry_membership_source"] = "stocks_industry_proxy"
    result.loc[current_membership_mask, "industry_membership_source"] = "current_membership_proxy"
    result.loc[point_in_time_mask, "industry_membership_source"] = "point_in_time_snapshot"
    result = result.drop(columns=["current_industry_id", "current_industry_name"])

    point_in_time_rows = int(point_in_time_mask.sum())
    current_proxy_rows = int((current_membership_mask | stock_proxy_mask).sum())
    unclassified_rows = int(len(result) - point_in_time_rows - current_proxy_rows)
    mode = _industry_membership_mode(
        point_in_time_rows=point_in_time_rows,
        current_proxy_rows=current_proxy_rows,
        unclassified_rows=unclassified_rows,
    )
    return result, {
        "industry_membership_mode": mode,
        "industry_membership_symbols": int(
            result.loc[result["industry_id"] != "UNCLASSIFIED", "vt_symbol"].nunique()
        ),
        "industry_membership_point_in_time_rows": point_in_time_rows,
        "industry_membership_point_in_time_trade_days": int(
            result.loc[point_in_time_mask, "trade_date"].nunique()
        ),
        "industry_membership_point_in_time_symbols": int(
            result.loc[point_in_time_mask, "vt_symbol"].nunique()
        ),
        "industry_membership_point_in_time_coverage_pct": round(
            point_in_time_rows / len(result) * 100,
            4,
        ),
        "industry_membership_current_proxy_rows": current_proxy_rows,
        "industry_membership_unclassified_rows": unclassified_rows,
        "industry_membership_survivorship_risk": bool(
            current_proxy_rows or unclassified_rows
        ),
    }


def _load_current_primary_industries(engine) -> pd.DataFrame:
    statement = (
        select(
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stock_sector_memberships.c.sector_id.label("industry_id"),
            schema.stock_sector_memberships.c.sector_name.label("industry_name"),
            schema.sectors.c.stock_count,
        )
        .select_from(
            schema.stock_sector_memberships.join(
                schema.sectors,
                schema.stock_sector_memberships.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(schema.stock_sector_memberships.c.sector_type == "industry")
    )
    memberships = pd.read_sql(statement, engine)
    if memberships.empty:
        return pd.DataFrame(columns=["vt_symbol", "industry_id", "industry_name"])

    memberships["stock_count"] = pd.to_numeric(memberships["stock_count"], errors="coerce")
    median_size = memberships.groupby("vt_symbol", sort=False)["stock_count"].transform("median")
    memberships["middle_distance"] = (memberships["stock_count"] - median_size).abs().fillna(1e9)
    memberships["level_priority"] = (~memberships["industry_name"].astype(str).str.endswith("Ⅱ")).astype(int)
    primary = (
        memberships.sort_values(
            ["vt_symbol", "level_priority", "middle_distance", "industry_id"],
            kind="stable",
        )
        .drop_duplicates("vt_symbol", keep="first")
        [["vt_symbol", "industry_id", "industry_name"]]
    )
    return primary


def _primary_snapshot_industries(snapshots: pd.DataFrame) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame(
            columns=["snapshot_date", "vt_symbol", "industry_id", "industry_name"]
        )
    result = snapshots.copy()
    result["snapshot_date"] = pd.to_datetime(result["snapshot_date"], errors="coerce")
    result["rank"] = pd.to_numeric(result["rank"], errors="coerce").fillna(1_000_000)
    return (
        result.dropna(subset=["snapshot_date", "vt_symbol", "industry_id"])
        .sort_values(
            ["snapshot_date", "vt_symbol", "rank", "industry_id"],
            kind="stable",
        )
        .drop_duplicates(["snapshot_date", "vt_symbol"], keep="first")
        [["snapshot_date", "vt_symbol", "industry_id", "industry_name"]]
    )


def _industry_membership_mode(
    *,
    point_in_time_rows: int,
    current_proxy_rows: int,
    unclassified_rows: int,
) -> str:
    if point_in_time_rows and not current_proxy_rows and not unclassified_rows:
        return "point_in_time_daily_snapshot"
    if point_in_time_rows:
        return "mixed_point_in_time_and_current_proxy"
    if current_proxy_rows:
        return "current_mid_level_industry_proxy"
    return "unavailable"


def replace_history_replays(
    version: str,
    rows: Sequence[Mapping[str, object]],
    coverage: Mapping[str, object],
) -> int:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(schema.limit_up_history_replays).where(
                schema.limit_up_history_replays.c.strategy_version == version
            )
        )
        for batch in _history_replay_value_batches(rows):
            values = [
                {
                    **value,
                    "strategy_version": version,
                    "coverage": dict(coverage),
                    "updated_at": now,
                }
                for value in batch
            ]
            session.execute(pg_insert(schema.limit_up_history_replays).values(values))
    return len(rows)


def _history_replay_value_batches(
    rows: Sequence[Mapping[str, object]],
) -> Iterator[list[dict[str, object]]]:
    for offset in range(0, len(rows), HISTORY_REPLAY_WRITE_BATCH_SIZE):
        yield [
            _history_replay_value(row)
            for row in rows[offset : offset + HISTORY_REPLAY_WRITE_BATCH_SIZE]
        ]


def _history_replay_value(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "trade_date": _as_date(row.get("trade_date")),
        "source_mode": str(row.get("source_mode") or "daily_point_in_time"),
        "payload": _history_payload_for_storage(row),
    }


def _history_payload_for_storage(replay: Mapping[str, object]) -> dict[str, Any]:
    canonical = {
        key: value
        for key, value in replay.items()
        if key not in {"board_lanes", "board_candidate_pool"}
    }
    return _json_mapping(canonical)


def _expand_history_payload(stored: Mapping[str, object]) -> dict[str, object]:
    payload = dict(stored)
    portfolio = payload.get("lane_portfolio")
    if not isinstance(portfolio, Mapping):
        return payload
    if "board_lanes" not in payload:
        lanes = portfolio.get("lanes")
        payload["board_lanes"] = dict(lanes) if isinstance(lanes, Mapping) else {}
    if "board_candidate_pool" not in payload:
        pool = portfolio.get("candidate_pool")
        payload["board_candidate_pool"] = (
            dict(pool) if isinstance(pool, Mapping) else {}
        )
    return payload


def load_history_dates(version: str) -> list[date]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        return list(
            session.execute(
                select(schema.limit_up_history_replays.c.trade_date)
                .where(schema.limit_up_history_replays.c.strategy_version == version)
                .order_by(schema.limit_up_history_replays.c.trade_date)
            ).scalars()
        )


def load_history_day(version: str, trade_date: date) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.limit_up_history_replays.c.payload).where(
                schema.limit_up_history_replays.c.strategy_version == version,
                schema.limit_up_history_replays.c.trade_date == trade_date,
            )
        ).scalar_one_or_none()
    return _expand_history_payload(row) if isinstance(row, Mapping) else None


def load_history_candidate_pools(version: str) -> list[dict[str, object]]:
    """Load only persisted candidate pools needed for scheduled execution."""

    schema.ensure_schema_once(get_engine())
    payload = schema.limit_up_history_replays.c.payload
    statement = (
        select(
            schema.limit_up_history_replays.c.trade_date,
            payload["validation_phase"].as_string().label("validation_phase"),
            payload["lane_portfolio"]["candidate_pool"].label("candidate_pool"),
        )
        .where(schema.limit_up_history_replays.c.strategy_version == version)
        .order_by(schema.limit_up_history_replays.c.trade_date)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "trade_date": row["trade_date"].isoformat(),
            "validation_phase": str(row["validation_phase"] or "unknown"),
            "lane_portfolio": {
                "candidate_pool": dict(row["candidate_pool"] or {}),
            },
        }
        for row in rows
    ]


def load_history_evidence_rows(
    version: str,
    end: date,
) -> list[dict[str, object]]:
    """Load only the replay fields needed by live historical evidence."""

    schema.ensure_schema_once(get_engine())
    payload = schema.limit_up_history_replays.c.payload
    statement = (
        select(
            schema.limit_up_history_replays.c.trade_date,
            payload["lanes"].label("lanes"),
            payload["lane_portfolio"]["candidate_pool"].label(
                "candidate_pool"
            ),
        )
        .where(
            schema.limit_up_history_replays.c.strategy_version == version,
            schema.limit_up_history_replays.c.trade_date <= end,
        )
        .order_by(schema.limit_up_history_replays.c.trade_date)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "trade_date": row["trade_date"].isoformat(),
            "lanes": dict(row["lanes"] or {}),
            "lane_portfolio": {
                "candidate_pool": dict(row["candidate_pool"] or {}),
            },
        }
        for row in rows
    ]


def load_history_range(
    version: str,
    start: date | None,
    end: date | None,
    compact: bool = False,
) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    conditions = [schema.limit_up_history_replays.c.strategy_version == version]
    if start is not None:
        conditions.append(schema.limit_up_history_replays.c.trade_date >= start)
    if end is not None:
        conditions.append(schema.limit_up_history_replays.c.trade_date <= end)
    if compact:
        payload = schema.limit_up_history_replays.c.payload
        statement = select(
            schema.limit_up_history_replays.c.trade_date,
            payload["validation_phase"].as_string().label("validation_phase"),
            payload["lane_portfolio"]["selected"].label("selected"),
            schema.limit_up_history_replays.c.coverage,
        )
    else:
        statement = select(
            schema.limit_up_history_replays.c.trade_date,
            schema.limit_up_history_replays.c.payload,
            schema.limit_up_history_replays.c.coverage,
        )
    with session_scope() as session:
        rows = session.execute(
            statement.where(and_(*conditions)).order_by(
                schema.limit_up_history_replays.c.trade_date
            )
        ).mappings().all()
    if compact:
        return [
            {
                "trade_date": row["trade_date"].isoformat(),
                "validation_phase": str(row["validation_phase"] or "unknown"),
                "lane_portfolio": {
                    "selected": [
                        dict(candidate)
                        for candidate in (row["selected"] or [])
                        if isinstance(candidate, Mapping)
                    ]
                },
                "coverage": dict(row["coverage"] or {}),
            }
            for row in rows
        ]
    return [
        {
            **_expand_history_payload(row["payload"] or {}),
            "trade_date": row["trade_date"].isoformat(),
            "coverage": dict(row["coverage"] or {}),
        }
        for row in rows
    ]


def load_account_daily_bars(
    vt_symbols: Sequence[str],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    """Load only the prices needed to execute and mark selected candidates."""

    symbols = sorted({str(symbol).strip() for symbol in vt_symbols if str(symbol).strip()})
    if not symbols or start > end:
        return []
    schema.ensure_schema_once(get_engine())
    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(start, end),
        )
        .order_by(
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.vt_symbol,
        )
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "vt_symbol": str(row["vt_symbol"]),
            "trade_date": row["trade_date"].isoformat(),
            "open_price": float(row["open_price"]),
            "high_price": float(row["high_price"]),
            "low_price": float(row["low_price"]),
            "close_price": float(row["close_price"]),
        }
        for row in rows
    ]


def load_account_1430_prices(
    requests: Sequence[tuple[str, date]],
) -> list[dict[str, object]]:
    """Load exact D+1 14:30 one-minute closes in one database query."""

    pairs = sorted(
        {
            (str(vt_symbol).strip(), trade_date)
            for vt_symbol, trade_date in requests
            if str(vt_symbol).strip()
        }
    )
    if not pairs:
        return []
    schema.ensure_schema_once(get_engine())
    minute = schema.stock_minute_bars
    statement = (
        select(
            minute.c.vt_symbol,
            minute.c.trade_date,
            minute.c.bar_time,
            minute.c.close_price,
        )
        .where(
            tuple_(minute.c.vt_symbol, minute.c.trade_date).in_(pairs),
            minute.c.interval == "1m",
            func.to_char(minute.c.bar_time, "HH24:MI") == "14:30",
        )
        .order_by(minute.c.trade_date, minute.c.vt_symbol, minute.c.bar_time)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "vt_symbol": str(row["vt_symbol"]),
            "trade_date": row["trade_date"].isoformat(),
            "bar_time": row["bar_time"].isoformat(),
            "price_1430": float(row["close_price"]),
            "price_1430_source": "minute_1430",
        }
        for row in rows
    ]


def load_account_post_auction_prices(
    requests: Sequence[tuple[str, date]],
) -> list[dict[str, object]]:
    """Load the first continuous-session one-minute open after a 09:25 decision."""

    pairs = sorted(
        {
            (str(vt_symbol).strip(), trade_date)
            for vt_symbol, trade_date in requests
            if str(vt_symbol).strip()
        }
    )
    if not pairs:
        return []
    schema.ensure_schema_once(get_engine())
    minute = schema.stock_minute_bars
    statement = (
        select(
            minute.c.vt_symbol,
            minute.c.trade_date,
            minute.c.bar_time,
            minute.c.open_price,
            minute.c.source,
        )
        .where(
            tuple_(minute.c.vt_symbol, minute.c.trade_date).in_(pairs),
            minute.c.interval == "1m",
            func.to_char(minute.c.bar_time, "HH24:MI") == "09:31",
        )
        .order_by(minute.c.trade_date, minute.c.vt_symbol, minute.c.bar_time)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "vt_symbol": str(row["vt_symbol"]),
            "trade_date": row["trade_date"].isoformat(),
            "bar_time": row["bar_time"].isoformat(),
            "price_0931": float(row["open_price"]),
            "price_source": f"minute_0931_open:{row['source']}",
        }
        for row in rows
    ]


def load_account_auction_evidence(
    requests: Sequence[tuple[str, date]],
) -> list[dict[str, object]]:
    """Load point-in-time opening-auction fields for candidate exit pairs."""

    pairs = sorted(
        {
            (str(vt_symbol).strip(), trade_date)
            for vt_symbol, trade_date in requests
            if str(vt_symbol).strip()
        }
    )
    if not pairs:
        return []
    schema.ensure_schema_once(get_engine())
    auction = schema.stock_auction_snapshots
    statement = (
        select(
            auction.c.vt_symbol,
            auction.c.trade_date,
            auction.c.captured_at,
            auction.c.auction_price,
            auction.c.matched_volume,
            auction.c.unmatched_volume,
            auction.c.unmatched_side,
            auction.c.strict_complete,
            auction.c.source,
        )
        .where(tuple_(auction.c.vt_symbol, auction.c.trade_date).in_(pairs))
        .order_by(auction.c.trade_date, auction.c.vt_symbol)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [
        {
            "vt_symbol": str(row["vt_symbol"]),
            "trade_date": row["trade_date"].isoformat(),
            "captured_at": row["captured_at"].isoformat(),
            "auction_price": _optional_float(row["auction_price"]),
            "matched_volume": _optional_float(row["matched_volume"]),
            "unmatched_volume": _optional_float(row["unmatched_volume"]),
            "unmatched_side": row["unmatched_side"],
            "strict_complete": bool(row["strict_complete"]),
            "source": str(row["source"]),
        }
        for row in rows
    ]


def _optional_float(value: object) -> float | None:
    return float(value) if value is not None else None


def history_coverage(version: str) -> dict[str, object]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(
                func.min(schema.limit_up_history_replays.c.trade_date),
                func.max(schema.limit_up_history_replays.c.trade_date),
                func.count(),
            ).where(schema.limit_up_history_replays.c.strategy_version == version)
        ).one()
        coverage = session.execute(
            select(schema.limit_up_history_replays.c.coverage)
            .where(schema.limit_up_history_replays.c.strategy_version == version)
            .order_by(schema.limit_up_history_replays.c.trade_date.desc())
            .limit(1)
        ).scalar_one_or_none()
    return {
        **dict(coverage or {}),
        "persisted_start": row[0].isoformat() if row[0] else None,
        "persisted_end": row[1].isoformat() if row[1] else None,
        "persisted_days": int(row[2] or 0),
    }


def load_sector_warmup_data_coverage() -> dict[str, object]:
    """Return point-in-time concept evidence coverage for warmup research."""

    schema.ensure_schema_once(get_engine())
    concept_bars = schema.sector_daily_bars.join(
        schema.sectors,
        schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
    )
    with session_scope() as session:
        concept_daily = session.execute(
            select(
                func.min(schema.sector_daily_bars.c.trade_date),
                func.max(schema.sector_daily_bars.c.trade_date),
                func.count(func.distinct(schema.sector_daily_bars.c.trade_date)),
                func.count(),
            )
            .select_from(concept_bars)
            .where(schema.sectors.c.type.in_(("concept", "theme")))
        ).one()
        period_scores = _date_coverage_row(
            session,
            schema.sector_period_scores,
            schema.sector_period_scores.c.as_of_date,
        )
        fund_flows = _date_coverage_row(
            session,
            schema.sector_fund_flows,
            schema.sector_fund_flows.c.trade_date,
        )
        fund_snapshots = _date_coverage_row(
            session,
            schema.sector_fund_flow_snapshots,
            schema.sector_fund_flow_snapshots.c.trade_date,
            schema.sector_fund_flow_snapshots.c.sector_type.in_(("concept", "theme")),
        )
        membership_snapshots = _date_coverage_row(
            session,
            schema.stock_sector_membership_snapshots,
            schema.stock_sector_membership_snapshots.c.snapshot_date,
            schema.stock_sector_membership_snapshots.c.sector_type.in_(("concept", "theme")),
        )
        relation_edges = _date_coverage_row(
            session,
            schema.sector_relation_edges,
            schema.sector_relation_edges.c.as_of_date,
        )
    return {
        "concept_daily_bar_start": _iso_or_none(concept_daily[0]),
        "concept_daily_bar_end": _iso_or_none(concept_daily[1]),
        "concept_daily_bar_days": int(concept_daily[2] or 0),
        "concept_daily_bar_rows": int(concept_daily[3] or 0),
        **_coverage_fields("period_score", period_scores),
        **_coverage_fields("fund_flow", fund_flows),
        **_coverage_fields("intraday_fund_snapshot", fund_snapshots),
        **_coverage_fields("membership_snapshot", membership_snapshots),
        **_coverage_fields("relation_edge", relation_edges),
    }


def _date_coverage_row(
    session,
    table,
    date_column,
    *conditions,
) -> tuple[object, object, int, int]:
    statement = select(
        func.min(date_column),
        func.max(date_column),
        func.count(func.distinct(date_column)),
        func.count(),
    ).select_from(table)
    if conditions:
        statement = statement.where(*conditions)
    row = session.execute(statement).one()
    return row[0], row[1], int(row[2] or 0), int(row[3] or 0)


def _coverage_fields(
    prefix: str,
    row: tuple[object, object, int, int],
) -> dict[str, object]:
    return {
        f"{prefix}_start": _iso_or_none(row[0]),
        f"{prefix}_end": _iso_or_none(row[1]),
        f"{prefix}_days": row[2],
        f"{prefix}_rows": row[3],
    }


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _json_mapping(value: Mapping[str, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if hasattr(item, "isoformat"):
            result[str(key)] = item.isoformat()
        elif isinstance(item, Mapping):
            result[str(key)] = _json_mapping(item)
        elif isinstance(item, list):
            result[str(key)] = [
                _json_mapping(entry) if isinstance(entry, Mapping) else entry
                for entry in item
            ]
        else:
            result[str(key)] = item
    return result
