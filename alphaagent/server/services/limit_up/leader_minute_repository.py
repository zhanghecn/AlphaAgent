"""Persistence for the leader minute-level backtest run (single latest run).

仿 leader_first_board_repository 模式：CLI 跑完写库，API 读库。单行 id=1 存最新 run。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


def save_minute_backtest_run(strategy_version: str, payload: Mapping[str, object]) -> None:
    """覆盖写入最新分钟级回测 run（id=1）。"""

    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(schema.leader_minute_backtest_runs).where(
                schema.leader_minute_backtest_runs.c.id == 1
            )
        )
        session.execute(
            pg_insert(schema.leader_minute_backtest_runs).values(
                {
                    "id": 1,
                    "strategy_version": strategy_version,
                    "payload": dict(payload),
                    "built_at": now,
                    "updated_at": now,
                }
            )
        )


def load_minute_backtest_run() -> dict[str, object] | None:
    """读取最新分钟级回测 run 的 payload，无则 None。"""

    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.leader_minute_backtest_runs.c.payload).where(
                schema.leader_minute_backtest_runs.c.id == 1
            )
        ).first()
    payload = row[0] if row else None
    return dict(payload) if payload else None
