"""低吸日线回测 run 持久化（单行 id=1 存最新 run，仿 leader_minute 模式）。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy import delete, desc, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


_REBUILD_RUN_COLUMNS = (
    schema.low_suction_daily_backtest_rebuild_runs.c.id,
    schema.low_suction_daily_backtest_rebuild_runs.c.source,
    schema.low_suction_daily_backtest_rebuild_runs.c.status,
    schema.low_suction_daily_backtest_rebuild_runs.c.stage,
    schema.low_suction_daily_backtest_rebuild_runs.c.strategy_version,
    schema.low_suction_daily_backtest_rebuild_runs.c.score_version,
    schema.low_suction_daily_backtest_rebuild_runs.c.requested_at,
    schema.low_suction_daily_backtest_rebuild_runs.c.started_at,
    schema.low_suction_daily_backtest_rebuild_runs.c.stage_started_at,
    schema.low_suction_daily_backtest_rebuild_runs.c.finished_at,
    schema.low_suction_daily_backtest_rebuild_runs.c.message,
    schema.low_suction_daily_backtest_rebuild_runs.c.error,
    schema.low_suction_daily_backtest_rebuild_runs.c.metrics,
)


def save_daily_backtest_run(strategy_version: str, payload: Mapping[str, object]) -> None:
    """覆盖写入最新低吸日线回测 run（id=1）。"""

    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(schema.low_suction_daily_backtest_runs).where(
                schema.low_suction_daily_backtest_runs.c.id == 1
            )
        )
        session.execute(
            pg_insert(schema.low_suction_daily_backtest_runs).values(
                {
                    "id": 1,
                    "strategy_version": strategy_version,
                    "payload": dict(payload),
                    "built_at": now,
                    "updated_at": now,
                }
            )
        )


def load_daily_backtest_run() -> dict[str, object] | None:
    """读取最新低吸日线回测 run 的 payload，无则 None。"""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.low_suction_daily_backtest_runs.c.payload).where(
                schema.low_suction_daily_backtest_runs.c.id == 1
            )
        ).first()
    payload = row[0] if row else None
    return dict(payload) if payload else None


def create_daily_backtest_rebuild_run(
    *,
    source: str,
    status: str,
    stage: str,
    strategy_version: str,
    score_version: str,
    message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> int:
    """Append one manual or scheduled backtest request to the audit trail."""

    schema.ensure_schema_once(get_engine())
    requested_at = datetime.now(timezone.utc)
    with session_scope() as session:
        run_id = session.execute(
            insert(schema.low_suction_daily_backtest_rebuild_runs)
            .values(
                source=source,
                status=status,
                stage=stage,
                strategy_version=strategy_version,
                score_version=score_version,
                requested_at=requested_at,
                started_at=started_at,
                stage_started_at=started_at,
                finished_at=finished_at,
                message=message,
                metrics={},
                updated_at=requested_at,
            )
            .returning(schema.low_suction_daily_backtest_rebuild_runs.c.id)
        ).scalar_one()
    return int(run_id)


def update_daily_backtest_rebuild_run(
    run_id: int,
    *,
    status: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    error: str | None = None,
    metrics: Mapping[str, object] | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Update one tracked run at a stage boundary or terminal outcome."""

    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    values: dict[str, object] = {"updated_at": now}
    if status is not None:
        values["status"] = status
    if stage is not None:
        values["stage"] = stage
        values["stage_started_at"] = now
    if message is not None:
        values["message"] = message
    if error is not None:
        values["error"] = error
    if metrics is not None:
        values["metrics"] = dict(metrics)
    if finished_at is not None:
        values["finished_at"] = finished_at
    with session_scope() as session:
        session.execute(
            update(schema.low_suction_daily_backtest_rebuild_runs)
            .where(schema.low_suction_daily_backtest_rebuild_runs.c.id == run_id)
            .values(**values)
        )


def load_daily_backtest_rebuild_runs(limit: int = 8) -> list[dict[str, object]]:
    """Read the newest backtest requests, including duplicate-click evidence."""

    schema.ensure_schema_once(get_engine())
    statement = (
        select(*_REBUILD_RUN_COLUMNS)
        .order_by(
            desc(schema.low_suction_daily_backtest_rebuild_runs.c.requested_at),
            desc(schema.low_suction_daily_backtest_rebuild_runs.c.id),
        )
        .limit(max(int(limit), 1))
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return [_serialize_rebuild_run(row) for row in rows]


def _serialize_rebuild_run(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "source": str(row["source"]),
        "status": str(row["status"]),
        "stage": str(row["stage"]),
        "strategy_version": str(row["strategy_version"]),
        "score_version": str(row["score_version"]),
        "requested_at": _as_iso(row["requested_at"]),
        "started_at": _as_iso(row.get("started_at")),
        "stage_started_at": _as_iso(row.get("stage_started_at")),
        "finished_at": _as_iso(row.get("finished_at")),
        "message": _optional_text(row.get("message")),
        "error": _optional_text(row.get("error")),
        "metrics": dict(row.get("metrics") or {}),
    }


def _as_iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None
