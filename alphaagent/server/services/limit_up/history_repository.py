"""Database access for versioned point-in-time limit-up history replays."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd
from sqlalchemy import and_, delete, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

MIN_RELIABLE_DAILY_SYMBOLS = 3000
HISTORY_LOOKBACK_DATES = 35
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


def reliable_date_window(
    counts: Sequence[tuple[date, int]],
    *,
    min_symbols: int = MIN_RELIABLE_DAILY_SYMBOLS,
) -> list[date]:
    dates = [trade_date for trade_date, count in counts if int(count) >= min_symbols]
    if not dates:
        raise ValueError("reliable daily history is unavailable")
    return sorted(set(dates))


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
    values = [
        {
            "trade_date": _as_date(row.get("trade_date")),
            "strategy_version": version,
            "source_mode": str(row.get("source_mode") or "daily_point_in_time"),
            "payload": _json_mapping(row),
            "coverage": dict(coverage),
            "updated_at": now,
        }
        for row in rows
    ]
    with session_scope() as session:
        session.execute(
            delete(schema.limit_up_history_replays).where(
                schema.limit_up_history_replays.c.strategy_version == version
            )
        )
        for offset in range(0, len(values), 100):
            chunk = values[offset : offset + 100]
            if chunk:
                session.execute(pg_insert(schema.limit_up_history_replays).values(chunk))
    return len(values)


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
    return dict(row) if isinstance(row, Mapping) else None


def load_history_range(
    version: str,
    start: date | None,
    end: date | None,
) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    conditions = [schema.limit_up_history_replays.c.strategy_version == version]
    if start is not None:
        conditions.append(schema.limit_up_history_replays.c.trade_date >= start)
    if end is not None:
        conditions.append(schema.limit_up_history_replays.c.trade_date <= end)
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.limit_up_history_replays.c.trade_date,
                schema.limit_up_history_replays.c.payload,
                schema.limit_up_history_replays.c.coverage,
            )
            .where(and_(*conditions))
            .order_by(schema.limit_up_history_replays.c.trade_date)
        ).mappings().all()
    return [
        {
            **dict(row["payload"] or {}),
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
