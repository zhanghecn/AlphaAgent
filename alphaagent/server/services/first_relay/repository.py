"""一接二物化表读写(照 hpr repository 模式精简)。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Mapping

from sqlalchemy import delete, desc, func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

try:  # PostgreSQL INSERT .. ON CONFLICT
    from sqlalchemy.dialects.postgresql import insert as pg_insert
except ImportError:  # pragma: no cover
    pg_insert = None


def save_pool(exec_date: date, entries: list[Mapping[str, object]],
              rules_version: str) -> int:
    """整覆写某执行日的池(先删后插,幂等)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(delete(schema.j12_pool_entries)
                        .where(schema.j12_pool_entries.c.trade_date == exec_date))
        for e in entries:
            session.execute(pg_insert(schema.j12_pool_entries).values(
                trade_date=exec_date,
                vt_symbol=str(e["vt_symbol"]),
                name=str(e.get("name") or ""),
                point=str(e.get("point") or "—"),
                level=str(e.get("level") or "—"),
                actionable=bool(e.get("actionable")),
                avoid_static=e.get("avoid_static"),
                auction_gate=e.get("auction_gate"),
                action_hint=e.get("action_hint"),
                bonus=e.get("bonus"),
                prev_close=e.get("prev_close"),
                limit_price=e.get("limit_price"),
                foundation_yang=e.get("foundation_yang"),
                foundation_chg=e.get("foundation_chg"),
                dist_ma20=e.get("dist_ma20"),
                dist_h60=e.get("dist_h60"),
                pre10_pct=e.get("pre10_pct"),
                pre20_pct=e.get("pre20_pct"),
                b1_type=e.get("b1_type"),
                b1_open=e.get("b1_open"),
                b1_turn=e.get("b1_turn"),
                b1_gap=e.get("b1_gap"),
                chassis=e.get("chassis"),
                max_streak60=e.get("max_streak60"),
                mkt_lim_tm1=e.get("mkt_lim_tm1"),
                rules_version=rules_version,
            ))
    return len(entries)


def load_pool(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.j12_pool_entries)
            .where(schema.j12_pool_entries.c.trade_date == trade_date)
            .order_by(schema.j12_pool_entries.c.vt_symbol)
        ).mappings().all()
    return [dict(r) for r in rows]


def latest_pool_date() -> date | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.j12_pool_entries.c.trade_date))).scalar_one_or_none()
    return value if isinstance(value, date) else None


def list_pool_dates(limit: int = 250) -> list[str]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.j12_pool_entries.c.trade_date)
            .group_by(schema.j12_pool_entries.c.trade_date)
            .order_by(desc(schema.j12_pool_entries.c.trade_date))
            .limit(limit)).all()
    return [r[0].isoformat() for r in rows]


def upsert_signal(trade_date: date, vt_symbol: str, **fields: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        stmt = pg_insert(schema.j12_signals).values(
            trade_date=trade_date, vt_symbol=vt_symbol, **fields)
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_date", "vt_symbol"],
            set_={k: v for k, v in fields.items()}
            | {"updated_at": datetime.now(timezone.utc)})
        session.execute(stmt)


def load_signal_map(trade_date: date) -> dict[str, dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.j12_signals)
            .where(schema.j12_signals.c.trade_date == trade_date)).mappings().all()
    return {str(r["vt_symbol"]): dict(r) for r in rows}


def load_entered_open_signals() -> list[dict[str, object]]:
    """持仓中的信号(entered/holding/pending_exit)——EOD 推进退出用。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.j12_signals)
            .where(schema.j12_signals.c.status.in_(["entered", "holding", "pending_exit"]))
            .order_by(schema.j12_signals.c.entry_time)).mappings().all()
    return [dict(r) for r in rows]


def save_backtest_report(rules_version: str, payload: Mapping[str, object]) -> None:
    schema.ensure_schema_once(get_engine())
    from sqlalchemy.dialects.postgresql import insert
    with session_scope() as session:
        stmt = insert(schema.j12_backtest_runs).values(
            id=1, rules_version=rules_version, payload=dict(payload))
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"rules_version": rules_version, "payload": dict(payload),
                  "built_at": datetime.now(timezone.utc),
                  "updated_at": datetime.now(timezone.utc)})
        session.execute(stmt)


def load_backtest_report(rules_version: str) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.j12_backtest_runs)
            .where(schema.j12_backtest_runs.c.id == 1)).mappings().first()
    if row is None or str(row["rules_version"]) != rules_version:
        return None
    return dict(row["payload"])


def create_rebuild_run(source: str, rules_version: str) -> int:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        result = session.execute(
            pg_insert(schema.j12_backtest_rebuild_runs)
            .values(source=source)
            .returning(schema.j12_backtest_rebuild_runs.c.id))
        return int(result.scalar_one())


def update_rebuild_run(run_id: int, **fields: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(
            schema.j12_backtest_rebuild_runs.update()
            .where(schema.j12_backtest_rebuild_runs.c.id == run_id)
            .values(**fields))


def latest_rebuild_run() -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.j12_backtest_rebuild_runs)
            .order_by(desc(schema.j12_backtest_rebuild_runs.c.id)).limit(1)
        ).mappings().first()
    return dict(row) if row else None
