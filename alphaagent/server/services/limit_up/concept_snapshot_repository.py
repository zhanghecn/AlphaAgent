"""Persistence for frozen concept memberships and point-in-time strength."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope


SHANGHAI = ZoneInfo("Asia/Shanghai")
PERSISTED_STRENGTH_LIMIT = 30
STRENGTH_RETAIN_TRADE_DAYS = 120
_SNAPSHOT_COLUMNS = {
    "trade_date",
    "captured_at",
    "captured_minute",
    "membership_snapshot_date",
    "concept_id",
    "concept_name",
    "concept_state",
    "strength_score",
    "strength_rank",
    "strength_percentile",
    "coverage_ratio",
    "source",
    "source_updated_at",
    "is_stale",
}


def latest_prior_membership_date(
    values: Sequence[date],
    trade_date: date,
) -> date | None:
    prior = [value for value in values if value < trade_date]
    return max(prior) if prior else None


def load_frozen_membership_rows(
    trade_date: date,
) -> tuple[date | None, list[dict[str, object]]]:
    """Load the latest complete membership version strictly before D day."""

    snapshots = schema.stock_sector_membership_snapshots
    with session_scope() as session:
        snapshot_date = session.execute(
            select(func.max(snapshots.c.snapshot_date)).where(
                snapshots.c.snapshot_date < trade_date,
                snapshots.c.sector_type.in_(("concept", "theme")),
            )
        ).scalar_one_or_none()
        if snapshot_date is None:
            return None, []
        rows = session.execute(
            select(
                snapshots,
                schema.stocks.c.name.label("stock_name"),
            )
            .select_from(
                snapshots.outerjoin(
                    schema.stocks,
                    schema.stocks.c.vt_symbol == snapshots.c.vt_symbol,
                )
            )
            .where(
                snapshots.c.snapshot_date == snapshot_date,
                snapshots.c.sector_type.in_(("concept", "theme")),
            )
            .order_by(snapshots.c.sector_id, snapshots.c.vt_symbol)
        ).mappings().all()
    return snapshot_date, [dict(row) for row in rows]


def build_strength_snapshot_rows(
    concepts: Sequence[Mapping[str, object]],
    *,
    captured_at: datetime,
    membership_snapshot_date: date,
    source: str,
    source_updated_at: datetime | str | None,
) -> list[dict[str, Any]]:
    captured_utc = _as_utc(captured_at)
    source_time = _optional_datetime(source_updated_at)
    rows: list[dict[str, Any]] = []
    for concept in concepts:
        concept_id = str(concept.get("concept_id") or "").strip()
        if not concept_id:
            continue
        indexed = {
            "trade_date": captured_utc.astimezone(SHANGHAI).date(),
            "captured_at": captured_utc,
            "captured_minute": captured_utc.replace(second=0, microsecond=0),
            "membership_snapshot_date": membership_snapshot_date,
            "concept_id": concept_id,
            "concept_name": str(concept.get("concept_name") or concept_id),
            "concept_state": str(concept.get("concept_state") or "observe"),
            "strength_score": _float(concept.get("strength_score")),
            "strength_rank": int(concept.get("strength_rank") or 0),
            "strength_percentile": _float(concept.get("strength_percentile")),
            "coverage_ratio": _float(concept.get("coverage_ratio")),
            "source": str(source or "unknown"),
            "source_updated_at": source_time,
            "is_stale": bool(concept.get("is_stale", False)),
        }
        indexed["metrics"] = {
            key: value
            for key, value in concept.items()
            if key not in _SNAPSHOT_COLUMNS
        }
        rows.append(indexed)
    return rows


def select_persisted_concepts(
    concepts: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    selected: dict[str, dict[str, object]] = {}
    for concept in concepts:
        concept_id = str(concept.get("concept_id") or "")
        if not concept_id:
            continue
        rank = int(concept.get("strength_rank") or 1_000_000)
        state = str(concept.get("concept_state") or "observe")
        radar_symbols = concept.get("radar_symbols")
        has_radar = isinstance(radar_symbols, Sequence) and bool(radar_symbols)
        if rank <= PERSISTED_STRENGTH_LIMIT or has_radar or state in {"warming", "launch", "ebb"}:
            selected[concept_id] = dict(concept)
    return sorted(
        selected.values(),
        key=lambda row: (
            int(row.get("strength_rank") or 1_000_000),
            str(row.get("concept_id") or ""),
        ),
    )


def save_strength_snapshots(rows: Sequence[Mapping[str, object]]) -> int:
    if not rows:
        return 0
    table = schema.limit_up_concept_strength_snapshots
    statement = pg_insert(table).values([dict(row) for row in rows])
    statement = statement.on_conflict_do_update(
        constraint="uq_limit_up_concept_strength_minute",
        set_={
            column: getattr(statement.excluded, column)
            for column in (
                "captured_at",
                "membership_snapshot_date",
                "concept_name",
                "concept_state",
                "strength_score",
                "strength_rank",
                "strength_percentile",
                "coverage_ratio",
                "source",
                "source_updated_at",
                "is_stale",
                "metrics",
            )
        }
        | {"updated_at": datetime.now(timezone.utc)},
    )
    with session_scope() as session:
        session.execute(statement)
    return len(rows)


def load_strength_history(
    trade_date: date,
    *,
    before: datetime | None = None,
    minutes: int = 6,
) -> list[dict[str, object]]:
    table = schema.limit_up_concept_strength_snapshots
    end = _as_utc(before or datetime.now(timezone.utc))
    start = end - timedelta(minutes=max(int(minutes), 1))
    statement = (
        select(table)
        .where(
            table.c.trade_date == trade_date,
            table.c.captured_at >= start,
            table.c.captured_at <= end,
        )
        .order_by(table.c.captured_at, table.c.concept_id)
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [_strength_row(row) for row in rows]


def prune_strength_snapshots(
    retain_trade_days: int = STRENGTH_RETAIN_TRADE_DAYS,
) -> int:
    table = schema.limit_up_concept_strength_snapshots
    keep_count = max(int(retain_trade_days), 1)
    with session_scope() as session:
        dates = list(
            session.execute(
                select(table.c.trade_date)
                .distinct()
                .order_by(desc(table.c.trade_date))
                .limit(keep_count + 1)
            ).scalars().all()
        )
        if len(dates) <= keep_count:
            return 0
        cutoff = dates[keep_count - 1]
        result = session.execute(delete(table).where(table.c.trade_date < cutoff))
    return max(int(result.rowcount or 0), 0)


def _strength_row(row: Mapping[str, object]) -> dict[str, object]:
    metrics = row.get("metrics")
    return {
        **dict(row),
        **(dict(metrics) if isinstance(metrics, Mapping) else {}),
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.astimezone(timezone.utc)


def _optional_datetime(value: datetime | str | None) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _as_utc(parsed)


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
