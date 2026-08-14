"""Append-only persistence for low-suction live scan diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from threading import Lock

from sqlalchemy import delete, desc, insert, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


LIVE_SCAN_TRACE_RETAIN_TRADE_DAYS = 10
LIVE_SCAN_TRACE_MAX_RUNS = 100
_READ_COLUMNS = (
    schema.low_suction_live_scan_runs.c.id,
    schema.low_suction_live_scan_runs.c.trade_date,
    schema.low_suction_live_scan_runs.c.started_at,
    schema.low_suction_live_scan_runs.c.finished_at,
    schema.low_suction_live_scan_runs.c.duration_ms,
    schema.low_suction_live_scan_runs.c.status,
    schema.low_suction_live_scan_runs.c.provisional,
    schema.low_suction_live_scan_runs.c.spot_active_symbols,
    schema.low_suction_live_scan_runs.c.trend_count,
    schema.low_suction_live_scan_runs.c.oversold_count,
    schema.low_suction_live_scan_runs.c.score_version,
    schema.low_suction_live_scan_runs.c.merge_note,
    schema.low_suction_live_scan_runs.c.error,
)
_prune_lock = Lock()
_last_pruned_trade_date: date | None = None


def save_live_scan_run(run: Mapping[str, object]) -> None:
    """Persist one actual live scan; callers decide whether a scan occurred."""

    trade_date = _required_date(run["trade_date"])
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(
            insert(schema.low_suction_live_scan_runs).values(
                trade_date=trade_date,
                started_at=_required_datetime(run["started_at"]),
                finished_at=_required_datetime(run["finished_at"]),
                duration_ms=max(int(run["duration_ms"]), 0),
                status=str(run["status"]),
                provisional=_optional_bool(run.get("provisional")),
                spot_active_symbols=_optional_int(run.get("spot_active_symbols")),
                trend_count=_optional_int(run.get("trend_count")),
                oversold_count=_optional_int(run.get("oversold_count")),
                score_version=str(run["score_version"]),
                merge_note=_optional_text(run.get("merge_note")),
                error=_optional_text(run.get("error")),
            )
        )
    _prune_once_for_trade_date(trade_date)


def load_live_scan_runs(
    trade_date: date,
    *,
    limit: int = LIVE_SCAN_TRACE_MAX_RUNS,
) -> list[dict[str, object]]:
    """Return one signal day's scan runs in execution order."""

    schema.ensure_schema_once(get_engine())
    # 先按时间倒序取最新 N 条，再在内存里恢复执行顺序；直接升序 LIMIT
    # 会拿到当天最老的 N 条，长交易日里前端看不到最近一次扫描。
    newest_first = (
        select(*_READ_COLUMNS)
        .where(schema.low_suction_live_scan_runs.c.trade_date == trade_date)
        .order_by(
            desc(schema.low_suction_live_scan_runs.c.started_at),
            desc(schema.low_suction_live_scan_runs.c.id),
        )
        .limit(max(int(limit), 1))
    )
    with session_scope() as session:
        rows = list(session.execute(newest_first).mappings().all())
    rows.reverse()
    return _serialize_runs(rows)


def prune_live_scan_runs(
    retain_trade_days: int = LIVE_SCAN_TRACE_RETAIN_TRADE_DAYS,
) -> int:
    """Keep only the newest signal-date partitions of scan diagnostics."""

    schema.ensure_schema_once(get_engine())
    keep_count = max(int(retain_trade_days), 1)
    with session_scope() as session:
        trade_dates = list(
            session.execute(
                select(schema.low_suction_live_scan_runs.c.trade_date)
                .distinct()
                .order_by(desc(schema.low_suction_live_scan_runs.c.trade_date))
                .limit(keep_count + 1)
            ).scalars()
        )
    if len(trade_dates) <= keep_count:
        return 0
    cutoff = trade_dates[keep_count - 1]
    with session_scope() as session:
        result = session.execute(
            delete(schema.low_suction_live_scan_runs).where(
                schema.low_suction_live_scan_runs.c.trade_date < cutoff
            )
        )
    return max(int(result.rowcount or 0), 0)


def _serialize_runs(rows: list[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    previous_started_at: datetime | None = None
    for row in rows:
        started_at = _required_datetime(row["started_at"])
        result.append(
            {
                "id": int(row["id"]),
                "trade_date": _required_date(row["trade_date"]).isoformat(),
                "started_at": started_at.isoformat(),
                "finished_at": _required_datetime(row["finished_at"]).isoformat(),
                "duration_ms": int(row["duration_ms"]),
                "status": str(row["status"]),
                "provisional": _optional_bool(row.get("provisional")),
                "spot_active_symbols": _optional_int(row.get("spot_active_symbols")),
                "trend_count": _optional_int(row.get("trend_count")),
                "oversold_count": _optional_int(row.get("oversold_count")),
                "score_version": str(row["score_version"]),
                "merge_note": _optional_text(row.get("merge_note")),
                "error": _optional_text(row.get("error")),
                "interval_seconds": (
                    None
                    if previous_started_at is None
                    else max(int((started_at - previous_started_at).total_seconds()), 0)
                ),
            }
        )
        previous_started_at = started_at
    return result


def _prune_once_for_trade_date(trade_date: date) -> None:
    global _last_pruned_trade_date
    if _last_pruned_trade_date == trade_date:
        return
    with _prune_lock:
        if _last_pruned_trade_date == trade_date:
            return
        prune_live_scan_runs()
        _last_pruned_trade_date = trade_date


def _required_date(value: object) -> date:
    if isinstance(value, date):
        return value
    raise TypeError("trade_date must be a date")


def _required_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise TypeError("scan timestamps must be datetimes")


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None
