"""Append-only point-in-time market evidence used by strict backtests."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope

SHANGHAI = ZoneInfo("Asia/Shanghai")
INTRADAY_FUND_FLOW_PERIODS = frozenset({"即时", "今日", "1日", "当日"})
MEMBERSHIP_SNAPSHOT_CHUNK_SIZE = 500


def save_current_stock_sector_membership_snapshot(
    *,
    snapshot_date: date,
    captured_at: datetime,
) -> int:
    """Freeze the rebuilt current membership index as one daily version."""

    with session_scope() as session:
        items = [
            dict(row)
            for row in session.execute(
                select(schema.stock_sector_memberships)
            ).mappings().all()
        ]
    return save_stock_sector_membership_snapshots(
        items,
        snapshot_date=snapshot_date,
        captured_at=captured_at,
    )


def save_stock_sector_membership_snapshots(
    items: Sequence[Mapping[str, Any]],
    *,
    snapshot_date: date,
    captured_at: datetime,
) -> int:
    rows = build_stock_sector_membership_snapshot_rows(
        items,
        snapshot_date=snapshot_date,
        captured_at=captured_at,
    )
    if not rows:
        return 0

    table = schema.stock_sector_membership_snapshots
    with session_scope() as session:
        session.execute(
            table.delete().where(table.c.snapshot_date == snapshot_date)
        )
        _upsert_membership_snapshot_rows(session, table, rows)
    return len(rows)


def replace_stock_sector_membership_snapshot_scope(
    items: Sequence[Mapping[str, Any]],
    *,
    snapshot_date: date,
    captured_at: datetime,
    sector_type: str,
) -> int:
    """Atomically replace one sector type without deleting other daily scopes."""

    normalized_sector_type = str(sector_type or "").strip()
    if not normalized_sector_type:
        raise ValueError("sector_type is required")
    rows = [
        row
        for row in build_stock_sector_membership_snapshot_rows(
            items,
            snapshot_date=snapshot_date,
            captured_at=captured_at,
        )
        if row["sector_type"] == normalized_sector_type
    ]
    if not rows:
        return 0

    table = schema.stock_sector_membership_snapshots
    with session_scope() as session:
        session.execute(
            table.delete().where(
                table.c.snapshot_date == snapshot_date,
                table.c.sector_type == normalized_sector_type,
            )
        )
        _upsert_membership_snapshot_rows(session, table, rows)
    return len(rows)


def _upsert_membership_snapshot_rows(
    session,
    table,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    updated_at = datetime.now(timezone.utc)
    for chunk in _row_chunks(rows, chunk_size=MEMBERSHIP_SNAPSHOT_CHUNK_SIZE):
        statement = postgresql_insert(table).values(chunk)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.snapshot_date, table.c.vt_symbol, table.c.sector_id],
            set_={
                "captured_at": statement.excluded.captured_at,
                "sector_name": statement.excluded.sector_name,
                "sector_type": statement.excluded.sector_type,
                "rank": statement.excluded.rank,
                "confirmed": statement.excluded.confirmed,
                "is_precise": statement.excluded.is_precise,
                "source": statement.excluded.source,
                "raw": statement.excluded.raw,
                "updated_at": updated_at,
            },
        )
        session.execute(statement)


def _row_chunks(
    rows: Sequence[Mapping[str, Any]],
    *,
    chunk_size: int,
):
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    for offset in range(0, len(rows), chunk_size):
        yield list(rows[offset : offset + chunk_size])


def build_stock_sector_membership_snapshot_rows(
    items: Sequence[Mapping[str, Any]],
    *,
    snapshot_date: date,
    captured_at: datetime,
) -> list[dict[str, Any]]:
    captured_utc = _as_utc(captured_at)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        vt_symbol = str(item.get("vt_symbol") or "").strip().upper()
        sector_id = str(item.get("sector_id") or "").strip()
        if not vt_symbol or not sector_id:
            continue
        rows[(vt_symbol, sector_id)] = {
            "snapshot_date": snapshot_date,
            "vt_symbol": vt_symbol,
            "sector_id": sector_id,
            "captured_at": captured_utc,
            "sector_name": str(item.get("sector_name") or sector_id),
            "sector_type": str(item.get("sector_type") or "concept"),
            "rank": _int_or_none(item.get("rank")),
            "confirmed": item.get("confirmed"),
            "is_precise": item.get("is_precise"),
            "source": str(item.get("source") or "unknown"),
            "raw": _raw_payload(item),
        }
    return list(rows.values())


def save_sector_fund_flow_snapshots(
    items: Sequence[Mapping[str, Any]],
    *,
    period: str,
    sector_type: str,
    captured_at: datetime,
) -> int:
    if str(period).strip() not in INTRADAY_FUND_FLOW_PERIODS:
        return 0
    rows = build_sector_fund_flow_snapshot_rows(
        items,
        period=period,
        sector_type=sector_type,
        captured_at=captured_at,
    )
    if not rows:
        return 0

    table = schema.sector_fund_flow_snapshots
    statement = postgresql_insert(table).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[
            table.c.trade_date,
            table.c.sector_id,
            table.c.period,
            table.c.captured_minute,
        ],
        set_={
            column: getattr(statement.excluded, column)
            for column in (
                "captured_at",
                "session_stage",
                "sector_name",
                "sector_type",
                "change_pct",
                "main_net_inflow",
                "main_net_inflow_ratio",
                "super_large_net_inflow",
                "large_net_inflow",
                "medium_net_inflow",
                "small_net_inflow",
                "rank",
                "rise_count",
                "fall_count",
                "flat_count",
                "rise_ratio",
                "leader_stock",
                "leader_stock_code",
                "source",
                "source_updated_at",
                "is_stale",
                "raw",
            )
        }
        | {"updated_at": datetime.now(timezone.utc)},
    )
    with session_scope() as session:
        session.execute(statement)
    return len(rows)


def build_sector_fund_flow_snapshot_rows(
    items: Sequence[Mapping[str, Any]],
    *,
    period: str,
    sector_type: str,
    captured_at: datetime,
) -> list[dict[str, Any]]:
    captured_utc = _as_utc(captured_at)
    captured_local = captured_utc.astimezone(SHANGHAI)
    captured_minute = captured_utc.replace(second=0, microsecond=0)
    stage = market_session_stage(captured_local)
    rows: dict[tuple[date, str], dict[str, Any]] = {}
    for item in items:
        sector_id = str(
            item.get("id")
            or item.get("sector_id")
            or item.get("code")
            or ""
        ).strip()
        trade_date = _date_value(item.get("trade_date"))
        if not sector_id or trade_date is None:
            continue
        rise_count = _int_or_none(item.get("rise_count"))
        fall_count = _int_or_none(item.get("fall_count"))
        flat_count = _int_or_none(item.get("flat_count"))
        rows[(trade_date, sector_id)] = {
            "trade_date": trade_date,
            "captured_at": captured_utc,
            "captured_minute": captured_minute,
            "session_stage": stage,
            "sector_id": sector_id,
            "sector_name": str(item.get("name") or sector_id),
            "sector_type": str(sector_type or item.get("sector_type") or "concept"),
            "period": str(period),
            "change_pct": _float_or_none(item.get("change_pct")),
            "main_net_inflow": _float_or_none(item.get("main_net_inflow")),
            "main_net_inflow_ratio": _float_or_none(
                item.get("main_net_inflow_pct")
                if item.get("main_net_inflow_pct") is not None
                else item.get("main_net_inflow_ratio")
            ),
            "super_large_net_inflow": _float_or_none(item.get("super_large_net_inflow")),
            "large_net_inflow": _float_or_none(item.get("large_net_inflow")),
            "medium_net_inflow": _float_or_none(item.get("medium_net_inflow")),
            "small_net_inflow": _float_or_none(item.get("small_net_inflow")),
            "rank": _int_or_none(item.get("rank")),
            "rise_count": rise_count,
            "fall_count": fall_count,
            "flat_count": flat_count,
            "rise_ratio": _breadth_ratio(rise_count, fall_count, flat_count),
            "leader_stock": _text_or_none(item.get("leader_stock")),
            "leader_stock_code": _text_or_none(item.get("leader_stock_code")),
            "source": str(item.get("source") or "unknown"),
            "source_updated_at": _source_updated_at(item, trade_date),
            "is_stale": trade_date != captured_local.date(),
            "raw": _raw_payload(item),
        }
    return list(rows.values())


def save_stock_auction_snapshots(
    items: Sequence[Mapping[str, Any]],
    *,
    trade_date: date,
    captured_at: datetime,
) -> int:
    rows = build_stock_auction_snapshot_rows(
        items,
        trade_date=trade_date,
        captured_at=captured_at,
    )
    if not rows:
        return 0

    table = schema.stock_auction_snapshots
    statement = postgresql_insert(table).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.trade_date, table.c.vt_symbol],
        set_={
            column: getattr(statement.excluded, column)
            for column in (
                "captured_at",
                "symbol",
                "exchange",
                "name",
                "auction_price",
                "previous_close",
                "auction_change_pct",
                "matched_volume",
                "matched_amount",
                "unmatched_volume",
                "unmatched_side",
                "auction_status",
                "source_quote_time",
                "source_updated_at",
                "strict_complete",
                "source",
                "raw",
            )
        }
        | {"updated_at": datetime.now(timezone.utc)},
    )
    with session_scope() as session:
        session.execute(table.delete().where(table.c.trade_date == trade_date))
        session.execute(statement)
    return len(rows)


def build_stock_auction_snapshot_rows(
    items: Sequence[Mapping[str, Any]],
    *,
    trade_date: date,
    captured_at: datetime,
) -> list[dict[str, Any]]:
    captured_utc = _as_utc(captured_at)
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        vt_symbol = str(item.get("vt_symbol") or "").strip().upper()
        if not vt_symbol:
            continue
        symbol, _, inferred_exchange = vt_symbol.partition(".")
        auction_price = _float_or_none(
            item.get("auction_price")
            if item.get("auction_price") is not None
            else item.get("open_price")
        )
        previous_close = _float_or_none(item.get("previous_close"))
        matched_volume = _float_or_none(
            item.get("matched_volume")
            if item.get("matched_volume") is not None
            else item.get("volume")
        )
        matched_amount = _float_or_none(
            item.get("matched_amount")
            if item.get("matched_amount") is not None
            else item.get("turnover")
        )
        unmatched_volume = _float_or_none(item.get("unmatched_volume"))
        unmatched_side = _text_or_none(item.get("unmatched_side"))
        source_quote_time = _text_or_none(
            item.get("source_quote_time")
            if item.get("source_quote_time") is not None
            else item.get("trade_time")
        )
        source_updated_at = _source_updated_at(item, trade_date)
        auction_status = str(
            item.get("auction_status")
            or ("matched" if auction_price and matched_volume and matched_volume > 0 else "no_match")
        )
        strict_complete = _strict_auction_complete(
            auction_price=auction_price,
            matched_volume=matched_volume,
            matched_amount=matched_amount,
            unmatched_volume=unmatched_volume,
            unmatched_side=unmatched_side,
            source_updated_at=source_updated_at,
            auction_status=auction_status,
        )
        rows[vt_symbol] = {
            "trade_date": trade_date,
            "vt_symbol": vt_symbol,
            "captured_at": captured_utc,
            "symbol": str(item.get("symbol") or symbol),
            "exchange": str(item.get("exchange") or inferred_exchange),
            "name": str(item.get("name") or symbol),
            "auction_price": auction_price,
            "previous_close": previous_close,
            "auction_change_pct": _return_pct(auction_price, previous_close),
            "matched_volume": matched_volume,
            "matched_amount": matched_amount,
            "unmatched_volume": unmatched_volume,
            "unmatched_side": unmatched_side,
            "auction_status": auction_status,
            "source_quote_time": source_quote_time,
            "source_updated_at": source_updated_at,
            "strict_complete": strict_complete,
            "source": str(item.get("source") or "unknown"),
            "raw": _raw_payload(item),
        }
    return list(rows.values())


def market_session_stage(value: datetime) -> str:
    local = _as_utc(value).astimezone(SHANGHAI)
    current = local.time().replace(tzinfo=None)
    if time(9, 15) <= current < time(9, 30):
        return "auction"
    if time(9, 30) <= current <= time(11, 30):
        return "morning"
    if time(13, 0) <= current < time(14, 30):
        return "afternoon"
    if time(14, 30) <= current <= time(15, 0):
        return "tail"
    return "closed"


def _strict_auction_complete(
    *,
    auction_price: float | None,
    matched_volume: float | None,
    matched_amount: float | None,
    unmatched_volume: float | None,
    unmatched_side: str | None,
    source_updated_at: datetime | None,
    auction_status: str,
) -> bool:
    price_complete = bool(auction_price) or auction_status in {
        "no_match",
        "suspended",
        "halted",
    }
    unmatched_complete = unmatched_volume is not None and (
        unmatched_volume == 0 or bool(unmatched_side)
    )
    return bool(
        price_complete
        and matched_volume is not None
        and matched_amount is not None
        and unmatched_complete
        and source_updated_at is not None
        and auction_status
    )


def _source_updated_at(item: Mapping[str, Any], trade_date: date) -> datetime | None:
    explicit = _datetime_value(item.get("source_updated_at"))
    if explicit is not None:
        return explicit
    trade_time = _text_or_none(
        item.get("source_quote_time")
        if item.get("source_quote_time") is not None
        else item.get("trade_time")
    )
    if trade_time:
        combined = _market_datetime(trade_time, trade_date)
        if combined is not None:
            return combined
    raw = item.get("raw")
    if isinstance(raw, Mapping):
        timestamp = raw.get("updated_timestamp")
        if timestamp is None and isinstance(raw.get("raw"), Mapping):
            timestamp = raw["raw"].get("f124")
        if timestamp is not None:
            try:
                return datetime.fromtimestamp(float(timestamp), timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError):
                return None
    return None


def _market_datetime(value: str, trade_date: date) -> datetime | None:
    parsed = _datetime_value(value)
    if parsed is not None and len(value.strip()) >= 10:
        return parsed
    text_value = value.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(text_value, fmt).time()
            return datetime.combine(trade_date, parsed_time, tzinfo=SHANGHAI).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(timezone.utc)


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = str(value or "").strip()
    if len(text_value) == 8 and text_value.isdigit():
        text_value = f"{text_value[:4]}-{text_value[4:6]}-{text_value[6:]}"
    try:
        return date.fromisoformat(text_value[:10])
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.astimezone(timezone.utc)


def _raw_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = item.get("raw")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return int(number) if number is not None else None


def _text_or_none(value: Any) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None


def _return_pct(price: float | None, previous_close: float | None) -> float | None:
    if price is None or previous_close is None or previous_close <= 0:
        return None
    return round((price / previous_close - 1) * 100, 4)


def _breadth_ratio(
    rise_count: int | None,
    fall_count: int | None,
    flat_count: int | None,
) -> float | None:
    if rise_count is None or fall_count is None:
        return None
    total = rise_count + fall_count + (flat_count or 0)
    return round(rise_count / total * 100, 4) if total > 0 else None
