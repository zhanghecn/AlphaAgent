"""Read models for the public market dashboard.

The dashboard serves materialized PostgreSQL snapshots first.  Live AkShare
calls stay in the API layer only as a bootstrap fallback before the worker has
written the first snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import logging
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope

LOGGER = logging.getLogger(__name__)
INTRADAY_PERIOD = "即时"
POOL_LABELS = {
    "zt": "涨停池",
    "zt_previous": "昨日涨停",
    "strong": "强势股",
    "zbgc": "炸板池",
    "dtgc": "跌停池",
}


def load_fund_flow_snapshot(
    *,
    sector_type: str,
    top_n: int,
) -> dict[str, Any] | None:
    """Load the latest stored sector-fund-flow snapshot for one board type."""

    if not is_database_configured():
        return None
    try:
        with session_scope() as session:
            snapshot = _load_sector_snapshot(session, sector_type, top_n)
            return snapshot or _load_current_sector_flow(session, sector_type, top_n)
    except Exception as exc:  # noqa: BLE001 - caller will use its live bootstrap fallback
        LOGGER.debug("stored fund-flow snapshot unavailable: %s", exc.__class__.__name__)
        return None


def load_sector_ranking_snapshot(
    *,
    sector_type: str,
    sort_by: str,
    limit: int,
) -> dict[str, Any] | None:
    """Load the homepage sector ranking from materialized sector snapshots."""

    requested_types = _ranking_sector_types(sector_type)
    if not requested_types or not is_database_configured():
        return None
    try:
        with session_scope() as session:
            snapshot = _load_sector_ranking_snapshot(
                session,
                requested_types,
                sort_by,
                limit,
            )
            return snapshot or _load_sector_ranking_current_flow(
                session,
                requested_types,
                sort_by,
                limit,
            )
    except Exception as exc:  # noqa: BLE001 - API keeps its first-run bootstrap fallback
        LOGGER.debug("stored sector ranking unavailable: %s", exc.__class__.__name__)
        return None


def load_hot_rank_snapshot(*, limit: int) -> dict[str, Any] | None:
    """Load the newest stored EastMoney popularity ranking."""

    if not is_database_configured():
        return None
    try:
        with session_scope() as session:
            table = schema.stock_hot_ranks
            rank_time = session.execute(select(func.max(table.c.rank_time))).scalar_one_or_none()
            if rank_time is None:
                return None
            filters = (table.c.rank_time == rank_time,)
            total = int(
                session.execute(select(func.count()).select_from(table).where(*filters)).scalar_one()
                or 0
            )
            rows = session.execute(
                select(
                    table,
                    schema.stocks.c.symbol.label("stock_symbol"),
                    schema.stocks.c.name.label("stock_name"),
                    schema.stocks.c.change_pct.label("stock_change_pct"),
                    schema.stocks.c.last_price.label("stock_last_price"),
                )
                .select_from(table.outerjoin(schema.stocks, table.c.vt_symbol == schema.stocks.c.vt_symbol))
                .where(*filters)
                .order_by(table.c.rank.asc().nulls_last(), table.c.vt_symbol.asc())
                .limit(limit)
            ).mappings().all()
            if not rows:
                return None
            updated_at = session.execute(
                select(func.max(table.c.updated_at)).where(*filters)
            ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - caller will use its live bootstrap fallback
        LOGGER.debug("stored hot-rank snapshot unavailable: %s", exc.__class__.__name__)
        return None

    items = [_hot_rank_item(dict(row)) for row in rows]
    return {
        "items": items,
        "total": total,
        "status": "ready",
        "updated_at": _iso_datetime(updated_at),
        "data_origin": "local_db",
        "storage_table": "stock_hot_ranks",
        "fallback_used": False,
    }


def load_limit_pool_snapshot(*, trade_date: str | None) -> dict[str, Any] | None:
    """Load a stored five-pool snapshot, defaulting to the latest available day."""

    requested_date = _parse_trade_date(trade_date)
    if trade_date and requested_date is None:
        return None
    if not is_database_configured():
        return None
    try:
        with session_scope() as session:
            table = schema.limit_up_pool_snapshots
            target_date = requested_date or session.execute(
                select(func.max(table.c.trade_date))
            ).scalar_one_or_none()
            if target_date is None:
                return None
            rows = session.execute(
                select(table)
                .where(table.c.trade_date == target_date)
                .order_by(
                    table.c.pool_type.asc(),
                    table.c.limit_up_count.desc().nulls_last(),
                    table.c.change_pct.desc().nulls_last(),
                    table.c.vt_symbol.asc(),
                )
            ).mappings().all()
            if not rows:
                return None
            updated_at = session.execute(
                select(func.max(table.c.updated_at)).where(table.c.trade_date == target_date)
            ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - caller will use its live bootstrap fallback
        LOGGER.debug("stored limit-pool snapshot unavailable: %s", exc.__class__.__name__)
        return None

    pools = {
        pool_type: {"label": label, "items": [], "total": 0}
        for pool_type, label in POOL_LABELS.items()
    }
    for raw_row in rows:
        row = dict(raw_row)
        pool_type = str(row.get("pool_type") or "")
        pool = pools.get(pool_type)
        if pool is None:
            continue
        pool["items"].append(_limit_pool_item(row))
        pool["total"] = int(pool["total"]) + 1

    return {
        "trade_date": target_date.strftime("%Y%m%d"),
        "pools": pools,
        "status": "ready",
        "updated_at": _iso_datetime(updated_at),
        "data_origin": "local_db",
        "storage_table": "limit_up_pool_snapshots",
        "fallback_used": False,
    }


def _load_sector_snapshot(session: Any, sector_type: str, top_n: int) -> dict[str, Any] | None:
    table = schema.sector_fund_flow_snapshots
    latest_captured_at = session.execute(
        select(func.max(table.c.captured_at)).where(
            table.c.sector_type == sector_type,
            table.c.period == INTRADAY_PERIOD,
        )
    ).scalar_one_or_none()
    if latest_captured_at is None:
        return None
    filters = (
        table.c.sector_type == sector_type,
        table.c.period == INTRADAY_PERIOD,
        table.c.captured_at == latest_captured_at,
    )
    total = int(
        session.execute(select(func.count()).select_from(table).where(*filters)).scalar_one()
        or 0
    )
    rows = session.execute(
        select(table)
        .where(*filters)
        .order_by(func.abs(table.c.main_net_inflow).desc().nulls_last(), table.c.sector_id.asc())
        .limit(top_n)
    ).mappings().all()
    if not rows:
        return None
    return {
        "items": [_sector_snapshot_item(dict(row)) for row in rows],
        "total": total,
        "sector_type": sector_type,
        "status": "ready",
        "updated_at": _iso_datetime(latest_captured_at),
        "data_origin": "local_db",
        "storage_table": "sector_fund_flow_snapshots",
        "fallback_used": False,
    }


def _load_sector_ranking_snapshot(
    session: Any,
    sector_types: tuple[str, ...],
    sort_by: str,
    limit: int,
) -> dict[str, Any] | None:
    table = schema.sector_fund_flow_snapshots
    latest_by_type = (
        select(
            table.c.sector_type,
            func.max(table.c.captured_at).label("captured_at"),
        )
        .where(
            table.c.sector_type.in_(sector_types),
            table.c.period == INTRADAY_PERIOD,
        )
        .group_by(table.c.sector_type)
        .subquery()
    )
    rows = session.execute(
        select(
            table.c.sector_id,
            table.c.sector_name,
            table.c.sector_type,
            table.c.change_pct,
            table.c.rise_count,
            table.c.fall_count,
            table.c.leader_stock,
            table.c.main_net_inflow,
            schema.sectors.c.stock_count,
            schema.sectors.c.leader_change_pct,
            schema.sectors.c.market_cap,
            schema.sectors.c.turnover_rate,
            table.c.captured_at,
        )
        .select_from(
            table.join(
                latest_by_type,
                (latest_by_type.c.sector_type == table.c.sector_type)
                & (latest_by_type.c.captured_at == table.c.captured_at),
            ).outerjoin(schema.sectors, schema.sectors.c.id == table.c.sector_id)
        )
        .where(
            table.c.sector_type.in_(sector_types),
            table.c.period == INTRADAY_PERIOD,
        )
    ).mappings().all()
    if not rows:
        return None
    items = [_sector_ranking_item(dict(row)) for row in rows]
    return _sector_ranking_payload(
        items,
        sort_by=sort_by,
        limit=limit,
        updated_at=max((row["captured_at"] for row in rows), default=None),
        storage_table="sector_fund_flow_snapshots",
    )


def _load_sector_ranking_current_flow(
    session: Any,
    sector_types: tuple[str, ...],
    sort_by: str,
    limit: int,
) -> dict[str, Any] | None:
    flow = schema.sector_fund_flows
    latest_by_type = (
        select(
            schema.sectors.c.type.label("sector_type"),
            func.max(flow.c.trade_date).label("trade_date"),
        )
        .select_from(flow.join(schema.sectors, schema.sectors.c.id == flow.c.sector_id))
        .where(
            schema.sectors.c.type.in_(sector_types),
            flow.c.period == INTRADAY_PERIOD,
        )
        .group_by(schema.sectors.c.type)
        .subquery()
    )
    rows = session.execute(
        select(
            flow.c.sector_id,
            schema.sectors.c.name.label("sector_name"),
            schema.sectors.c.type.label("sector_type"),
            schema.sectors.c.change_pct,
            schema.sectors.c.rise_count,
            schema.sectors.c.fall_count,
            schema.sectors.c.leader_stock,
            flow.c.main_net_inflow,
            schema.sectors.c.stock_count,
            schema.sectors.c.leader_change_pct,
            schema.sectors.c.market_cap,
            schema.sectors.c.turnover_rate,
            flow.c.updated_at,
        )
        .select_from(flow.join(schema.sectors, schema.sectors.c.id == flow.c.sector_id).join(
            latest_by_type,
            (latest_by_type.c.sector_type == schema.sectors.c.type)
            & (latest_by_type.c.trade_date == flow.c.trade_date),
        ))
        .where(
            schema.sectors.c.type.in_(sector_types),
            flow.c.period == INTRADAY_PERIOD,
        )
    ).mappings().all()
    if not rows:
        return None
    items = [_sector_ranking_item(dict(row)) for row in rows]
    return _sector_ranking_payload(
        items,
        sort_by=sort_by,
        limit=limit,
        updated_at=max((row["updated_at"] for row in rows), default=None),
        storage_table="sector_fund_flows",
    )


def _ranking_sector_types(sector_type: str) -> tuple[str, ...]:
    normalized = sector_type.strip().lower()
    if normalized in {"", "all"}:
        return ("concept", "industry")
    if normalized in {"concept", "industry"}:
        return (normalized,)
    return ()


def _sector_ranking_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sector_id": str(row.get("sector_id") or ""),
        "name": str(row.get("sector_name") or row.get("sector_id") or ""),
        "type": str(row.get("sector_type") or "concept"),
        "change_pct": row.get("change_pct"),
        "stock_count": row.get("stock_count"),
        "rise_count": row.get("rise_count"),
        "fall_count": row.get("fall_count"),
        "leader_stock": row.get("leader_stock"),
        "leader_change_pct": row.get("leader_change_pct"),
        "market_cap": row.get("market_cap"),
        "turnover_rate": row.get("turnover_rate"),
        "main_net_inflow": row.get("main_net_inflow"),
    }


def _sector_ranking_payload(
    items: list[dict[str, Any]],
    *,
    sort_by: str,
    limit: int,
    updated_at: object,
    storage_table: str,
) -> dict[str, Any]:
    value_key = {
        "fund_flow": "main_net_inflow",
        "stock_count": "stock_count",
    }.get(sort_by, "change_pct")
    items.sort(
        key=lambda item: (
            _ranking_value(item.get(value_key)) is None,
            -(_ranking_value(item.get(value_key)) or 0.0),
            str(item.get("sector_id") or ""),
        )
    )
    return {
        "items": items[:limit],
        "total": len(items),
        "sort_by": sort_by,
        "status": "ready",
        "updated_at": _iso_datetime(updated_at),
        "data_origin": "local_db",
        "storage_table": storage_table,
        "fallback_used": False,
    }


def _ranking_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_current_sector_flow(session: Any, sector_type: str, top_n: int) -> dict[str, Any] | None:
    table = schema.sector_fund_flows
    latest_trade_date = session.execute(
        select(func.max(table.c.trade_date)).where(table.c.period == INTRADAY_PERIOD)
    ).scalar_one_or_none()
    if latest_trade_date is None:
        return None
    filters = (
        table.c.trade_date == latest_trade_date,
        table.c.period == INTRADAY_PERIOD,
        schema.sectors.c.type == sector_type,
    )
    statement = table.join(schema.sectors, table.c.sector_id == schema.sectors.c.id)
    total = int(
        session.execute(
            select(func.count()).select_from(statement).where(*filters)
        ).scalar_one()
        or 0
    )
    rows = session.execute(
        select(
            table,
            schema.sectors.c.name.label("sector_name"),
            schema.sectors.c.change_pct.label("sector_change_pct"),
        )
        .select_from(statement)
        .where(*filters)
        .order_by(func.abs(table.c.main_net_inflow).desc().nulls_last(), table.c.sector_id.asc())
        .limit(top_n)
    ).mappings().all()
    if not rows:
        return None
    updated_at = session.execute(
        select(func.max(table.c.updated_at)).select_from(statement).where(*filters)
    ).scalar_one_or_none()
    return {
        "items": [_current_sector_flow_item(dict(row)) for row in rows],
        "total": total,
        "sector_type": sector_type,
        "status": "ready",
        "updated_at": _iso_datetime(updated_at),
        "data_origin": "local_db",
        "storage_table": "sector_fund_flows",
        "fallback_used": False,
    }


def _sector_snapshot_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": str(row.get("sector_id") or ""),
        "name": str(row.get("sector_name") or row.get("sector_id") or ""),
        "change_pct": row.get("change_pct"),
        "main_net_inflow": row.get("main_net_inflow"),
        "main_net_inflow_ratio": row.get("main_net_inflow_ratio"),
        "super_large_net_inflow": row.get("super_large_net_inflow"),
        "large_net_inflow": row.get("large_net_inflow"),
        "medium_net_inflow": row.get("medium_net_inflow"),
        "small_net_inflow": row.get("small_net_inflow"),
    }


def _current_sector_flow_item(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": str(row.get("sector_id") or ""),
        "name": str(row.get("sector_name") or row.get("sector_id") or ""),
        "change_pct": row.get("sector_change_pct"),
        "main_net_inflow": row.get("main_net_inflow"),
        "main_net_inflow_ratio": row.get("main_net_inflow_ratio"),
        "super_large_net_inflow": None,
        "large_net_inflow": None,
        "medium_net_inflow": None,
        "small_net_inflow": None,
    }


def _hot_rank_item(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(row.get("raw"))
    vt_symbol = str(row.get("vt_symbol") or "")
    return {
        "stock_code": str(raw.get("stock_code") or raw.get("代码") or row.get("stock_symbol") or vt_symbol.split(".", 1)[0]),
        "stock_name": str(raw.get("stock_name") or raw.get("名称") or row.get("stock_name") or vt_symbol),
        "rank": row.get("rank"),
        "rank_change": row.get("rank_change"),
        "keywords": row.get("keywords") or [],
        "change_pct": row.get("stock_change_pct"),
        "latest_price": row.get("stock_last_price"),
    }


def _limit_pool_item(row: Mapping[str, Any]) -> dict[str, Any]:
    vt_symbol = str(row.get("vt_symbol") or "")
    symbol, _, exchange = vt_symbol.partition(".")
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": vt_symbol,
        "name": str(row.get("name") or vt_symbol),
        "close_price": row.get("close_price"),
        "change_pct": row.get("change_pct"),
        "turnover_rate": row.get("turnover_rate"),
        "volume_ratio": row.get("volume_ratio"),
        "turnover": row.get("amount"),
        "limit_amount": row.get("limit_amount"),
        "limit_up_count": row.get("limit_up_count"),
        "first_limit_time": row.get("first_limit_time"),
        "last_limit_time": row.get("last_limit_time"),
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_trade_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _iso_datetime(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value or "")
