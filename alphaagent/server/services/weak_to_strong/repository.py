"""趋势弱转强持久层:池/信号/扫描轨道/回测报告的读写。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

from sqlalchemy import delete, desc, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

_SIGNAL_PK = ("trade_date", "vt_symbol", "group_key")

# v3.0 新增列:create_all 不给已存在的表补列(参照 API Perf 教训),幂等补列
_TABLE_V3_COLUMNS = {
    "w2s_pool_entries": {
        "ushadow_tm1": "DOUBLE PRECISION",
        "yang_tm1": "BOOLEAN",
    },
}
_columns_ensured = False


def _ensure_v3_columns() -> None:
    global _columns_ensured
    if _columns_ensured:
        return
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for table, cols in _TABLE_V3_COLUMNS.items():
                for name, ddl in cols.items():
                    connection.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"))
    _columns_ensured = True


# ── 盘前池 ──

def save_pool(exec_date: date, entries: list[Mapping[str, object]], rules_version: str) -> int:
    """整覆写某执行日的池(先删后插,幂等)。"""
    schema.ensure_schema_once(get_engine())
    _ensure_v3_columns()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(schema.w2s_pool_entries)
            .where(schema.w2s_pool_entries.c.trade_date == exec_date)
        )
        for e in entries:
            session.execute(
                pg_insert(schema.w2s_pool_entries).values(
                    trade_date=exec_date,
                    vt_symbol=str(e["vt_symbol"]),
                    group_key=str(e["group_key"]),
                    name=str(e.get("name") or ""),
                    prev_close=e.get("prev_close"),
                    trigger_price=e.get("trigger_price"),
                    limit_price=e.get("limit_price"),
                    chg_tm1=e.get("chg_tm1"),
                    lshadow_tm1=e.get("lshadow_tm1"),
                    ushadow_tm1=e.get("ushadow_tm1"),
                    yang_tm1=e.get("yang_tm1"),
                    vol_rel5_tm1=e.get("vol_rel5_tm1"),
                    amp_tm1=e.get("amp_tm1"),
                    turnover_tm1=e.get("turnover_tm1"),
                    base20_tm1=e.get("base20_tm1"),
                    last_streak=e.get("last_streak"),
                    gap_days=e.get("gap_days"),
                    mkt_lim_tm1=e.get("mkt_lim_tm1"),
                    halted=bool(e.get("halted")),
                    rules_version=rules_version,
                    updated_at=now,
                )
            )
    return len(entries)


def load_pool(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    _ensure_v3_columns()
    with session_scope() as session:
        rows = session.execute(
            select(schema.w2s_pool_entries)
            .where(schema.w2s_pool_entries.c.trade_date == trade_date)
            .order_by(schema.w2s_pool_entries.c.group_key,
                      schema.w2s_pool_entries.c.vt_symbol)
        ).mappings().all()
    return [dict(r) for r in rows]


def latest_pool_date() -> date | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.w2s_pool_entries.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def list_pool_dates(limit: int = 250) -> list[str]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.w2s_pool_entries.c.trade_date)
            .distinct()
            .order_by(desc(schema.w2s_pool_entries.c.trade_date))
            .limit(limit)
        ).scalars().all()
    return [r.isoformat() for r in rows if isinstance(r, date)]


# ── 信号 ──

def upsert_signal(trade_date: date, vt_symbol: str, group_key: str, **fields: object) -> None:
    """按主键 upsert 一行信号(只写传入字段)。"""
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    base = {"trade_date": trade_date, "vt_symbol": vt_symbol, "group_key": group_key,
            "name": str(fields.pop("name", "") or ""),
            "prev_close": fields.pop("prev_close", None),
            "trigger_price": fields.pop("trigger_price", None),
            "rules_version": str(fields.pop("rules_version", ""))}
    values = {**{k: v for k, v in base.items() if v is not None}, **fields, "updated_at": now}
    stmt = pg_insert(schema.w2s_signals).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.w2s_signals.c.trade_date,
                        schema.w2s_signals.c.vt_symbol,
                        schema.w2s_signals.c.group_key],
        set_={k: getattr(stmt.excluded, k) for k in values if k not in _SIGNAL_PK},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_signals(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.w2s_signals)
            .where(schema.w2s_signals.c.trade_date == trade_date)
        ).mappings().all()
    return [dict(r) for r in rows]


def load_signal_map(trade_date: date) -> dict[tuple[str, str], dict[str, object]]:
    """(vt_symbol, group_key) → 信号行。"""
    return {(str(r["vt_symbol"]), str(r["group_key"])): r for r in load_signals(trade_date)}


def load_open_entry_signals() -> list[dict[str, object]]:
    """已买入但未了结(entered/holding/pending_exit)的信号,EOD 逐日推进退出。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.w2s_signals)
            .where(schema.w2s_signals.c.entry_price.is_not(None))
            .where(schema.w2s_signals.c.exit_date.is_(None))
            .where(schema.w2s_signals.c.status.in_(["entered", "holding", "pending_exit"]))
        ).mappings().all()
    return [dict(r) for r in rows]


def load_entered_signals(trade_date: date) -> list[dict[str, object]]:
    return [r for r in load_signals(trade_date) if r.get("entry_price") is not None]


def load_month_closed_signals(month_prefix: str) -> list[dict[str, object]]:
    """某月(YYYY-MM)已了结信号,供月度汇总条。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.w2s_signals)
            .where(schema.w2s_signals.c.exit_date.is_not(None))
            .where(schema.w2s_signals.c.trade_date >= date.fromisoformat(month_prefix + "-01"))
        ).mappings().all()
    return [dict(r) for r in rows if str(r.get("exit_date") or "").startswith(month_prefix)]


# ── 扫描轨道 ──

def save_scan_run(**fields: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(pg_insert(schema.w2s_live_scan_runs).values(**fields))


def latest_scan_run(trade_date: date) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.w2s_live_scan_runs)
            .where(schema.w2s_live_scan_runs.c.trade_date == trade_date)
            .order_by(desc(schema.w2s_live_scan_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


# ── 回测报告 ──

def save_backtest_report(rules_version: str, payload: Mapping[str, object]) -> None:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    stmt = pg_insert(schema.w2s_backtest_runs).values(
        id=1, rules_version=rules_version, payload=dict(payload),
        built_at=now, updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.w2s_backtest_runs.c.id],
        set_={"rules_version": rules_version, "payload": dict(payload),
              "built_at": now, "updated_at": now},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_backtest_report(rules_version: str) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.w2s_backtest_runs.c.rules_version,
                   schema.w2s_backtest_runs.c.built_at,
                   schema.w2s_backtest_runs.c.payload)
            .where(schema.w2s_backtest_runs.c.id == 1)
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
            pg_insert(schema.w2s_backtest_rebuild_runs).values(
                source=source, status="queued", stage="排队中",
                rules_version=rules_version, requested_at=now,
            ).returning(schema.w2s_backtest_rebuild_runs.c.id)
        ).scalar_one()
    return int(run_id)


def update_rebuild_run(run_id: int, **fields: object) -> None:
    fields.setdefault("updated_at", datetime.now(timezone.utc))
    with session_scope() as session:
        session.execute(
            update(schema.w2s_backtest_rebuild_runs)
            .where(schema.w2s_backtest_rebuild_runs.c.id == run_id)
            .values(**fields)
        )


def latest_rebuild_run() -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.w2s_backtest_rebuild_runs)
            .order_by(desc(schema.w2s_backtest_rebuild_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None
