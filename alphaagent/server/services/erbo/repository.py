"""二波反包持久层:池/信号/扫描轨道/回测报告的读写(镜像 fanbao repository)。"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

_SIGNAL_PK = ("trade_date", "vt_symbol")


# ── 池 ──

def save_pool(exec_date: date, entries: list[Mapping[str, object]], rules_version: str) -> int:
    """整日替换执行池(幂等)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(delete(schema.erbo_pool_entries)
                        .where(schema.erbo_pool_entries.c.trade_date == exec_date))
        for e in entries:
            session.execute(
                pg_insert(schema.erbo_pool_entries).values(
                    trade_date=exec_date, vt_symbol=str(e["vt_symbol"]),
                    name=str(e.get("name") or ""), gap=int(e.get("gap") or 0),
                    gain30_pct=e.get("gain30_pct"), dd_pct=e.get("dd_pct"),
                    ma20gap_pct=e.get("ma20gap_pct"), lim30=e.get("lim30"),
                    yin_yang=e.get("yin_yang"), last_open_pct=e.get("last_open_pct"),
                    point=str(e.get("point") or "—"),
                    level=str(e.get("level") or "—"),
                    actionable=bool(e.get("actionable")),
                    avoid_static=e.get("avoid_static"),
                    cold_market=bool(e.get("cold_market")),
                    reb30=e.get("reb30"),
                    s4=bool(e.get("s4")),
                    prev_close=e.get("prev_close"), limit_price=e.get("limit_price"),
                    rules_version=rules_version))
    return len(entries)


def load_pool(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.erbo_pool_entries)
            .where(schema.erbo_pool_entries.c.trade_date == trade_date)
            .order_by(desc(schema.erbo_pool_entries.c.actionable),
                      schema.erbo_pool_entries.c.point,
                      schema.erbo_pool_entries.c.vt_symbol)
        ).mappings().all()
    return [dict(r) for r in rows]


def latest_pool_date() -> date | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        v = session.execute(
            select(func.max(schema.erbo_pool_entries.c.trade_date))).scalar_one_or_none()
    return v


def list_pool_dates(limit: int = 250) -> list[str]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.erbo_pool_entries.c.trade_date)
            .group_by(schema.erbo_pool_entries.c.trade_date)
            .order_by(desc(schema.erbo_pool_entries.c.trade_date))
            .limit(limit)).scalars().all()
    return [d.isoformat() for d in rows]


# ── 信号 ──

def upsert_signal(trade_date: date, vt_symbol: str, **fields: object) -> None:
    """信号幂等 upsert(带行基础字段随行带回,防裸 upsert 撞非空)。"""
    schema.ensure_schema_once(get_engine())
    fields.setdefault("updated_at", datetime.now(timezone.utc))
    with session_scope() as session:
        existing = session.execute(
            select(schema.erbo_signals)
            .where(schema.erbo_signals.c.trade_date == trade_date,
                   schema.erbo_signals.c.vt_symbol == vt_symbol)
        ).mappings().one_or_none()
        if existing is not None:
            merged = {k: v for k, v in dict(existing).items() if v is not None}
            merged.update({k: v for k, v in fields.items() if v is not None})
            session.execute(
                update(schema.erbo_signals)
                .where(schema.erbo_signals.c.trade_date == trade_date,
                       schema.erbo_signals.c.vt_symbol == vt_symbol)
                .values(**merged))
        else:
            session.execute(
                pg_insert(schema.erbo_signals).values(
                    trade_date=trade_date, vt_symbol=vt_symbol, **fields))


def load_signals(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.erbo_signals)
            .where(schema.erbo_signals.c.trade_date == trade_date)
            .order_by(schema.erbo_signals.c.vt_symbol)).mappings().all()
    return [dict(r) for r in rows]


def load_signal_map(trade_date: date) -> dict[str, dict[str, object]]:
    return {str(r["vt_symbol"]): r for r in load_signals(trade_date)}


def load_open_watching(until: date) -> list[dict[str, object]]:
    """≤ until 仍挂 watching/sealed_watch 的信号(扫描漏检兜底)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.erbo_signals)
            .where(schema.erbo_signals.c.trade_date <= until,
                   schema.erbo_signals.c.status.in_(["watching", "sealed_watch"]))
        ).mappings().all()
    return [dict(r) for r in rows]


def load_open_entry_signals() -> list[dict[str, object]]:
    """已入场未了结(entered/holding)信号(退出推进用)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.erbo_signals)
            .where(schema.erbo_signals.c.status.in_(["entered", "holding"]))
        ).mappings().all()
    return [dict(r) for r in rows]


def load_entered_signals(trade_date: date) -> list[dict[str, object]]:
    """前推交割单:指定日入场(entered/closed 起点为该日)的信号。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.erbo_signals)
            .where(schema.erbo_signals.c.trade_date == trade_date,
                   schema.erbo_signals.c.status.in_(["entered", "holding", "closed"]))
        ).mappings().all()
    return [dict(r) for r in rows]


# ── 扫描轨道 ──

def save_scan_run(trade_date: date, finished_at: datetime, *, status: str,
                  stats: dict[str, object] | None = None,
                  message: str | None = None, **extra: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(
            pg_insert(schema.erbo_live_scan_runs).values(
                trade_date=trade_date, finished_at=finished_at, status=status,
                stats=stats or {}, message=message))


def latest_scan_run(trade_date: date) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.erbo_live_scan_runs)
            .where(schema.erbo_live_scan_runs.c.trade_date == trade_date)
            .order_by(desc(schema.erbo_live_scan_runs.c.id)).limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


# ── 回测报告 ──

def save_backtest_report(rules_version: str, payload: Mapping[str, object]) -> None:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    stmt = pg_insert(schema.erbo_backtest_runs).values(
        id=1, rules_version=rules_version, payload=dict(payload),
        built_at=now, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.erbo_backtest_runs.c.id],
        set_={"rules_version": rules_version, "payload": dict(payload),
              "built_at": now, "updated_at": now})
    with session_scope() as session:
        session.execute(stmt)


def load_backtest_report(rules_version: str) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.erbo_backtest_runs.c.rules_version,
                   schema.erbo_backtest_runs.c.built_at,
                   schema.erbo_backtest_runs.c.payload)
            .where(schema.erbo_backtest_runs.c.id == 1)
        ).mappings().one_or_none()
    if row is None or str(row["rules_version"]) != rules_version:
        return None
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        return None
    result = dict(payload)
    result["built_at"] = row["built_at"].isoformat() if row["built_at"] else None
    return result


def create_rebuild_run(source: str, rules_version: str) -> int:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        run_id = session.execute(
            pg_insert(schema.erbo_backtest_rebuild_runs).values(
                source=source, status="queued", stage="排队中",
                rules_version=rules_version, requested_at=now,
            ).returning(schema.erbo_backtest_rebuild_runs.c.id)
        ).scalar_one()
    return int(run_id)


def update_rebuild_run(run_id: int, **fields: object) -> None:
    fields.setdefault("updated_at", datetime.now(timezone.utc))
    with session_scope() as session:
        session.execute(
            update(schema.erbo_backtest_rebuild_runs)
            .where(schema.erbo_backtest_rebuild_runs.c.id == run_id)
            .values(**fields))


def latest_rebuild_run() -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.erbo_backtest_rebuild_runs)
            .order_by(desc(schema.erbo_backtest_rebuild_runs.c.id)).limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None
