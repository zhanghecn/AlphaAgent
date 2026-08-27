"""潜龙首板持久层:池/信号/扫描轨道/回测报告的读写。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, desc, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

# v6 新增列:create_all 不会给已存在的表补列(参照 API Perf 教训),幂等补列
_TABLE_V6_COLUMNS = {
    "qianlong_pool_entries": {
        "vol_ma5": "DOUBLE PRECISION",
        "chassis_tag": "VARCHAR(4)",
        "trend_days": "DOUBLE PRECISION",
        "yang10": "DOUBLE PRECISION",
        "ret10": "DOUBLE PRECISION",
        "lu_cnt20": "DOUBLE PRECISION",
        "lu_cnt60": "DOUBLE PRECISION",
    },
    "qianlong_signals": {
        "chassis_tag": "VARCHAR(4)",
    },
}
_columns_ensured = False


def _ensure_v6_columns() -> None:
    global _columns_ensured
    if _columns_ensured:
        return
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for table, cols in _TABLE_V6_COLUMNS.items():
                for name, ddl in cols.items():
                    connection.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"))
    _columns_ensured = True


# ── 盘前池 ──

def save_pool(exec_date: date, entries: list[Mapping[str, object]], rules_version: str) -> int:
    """整覆写某执行日的池(先删后插,幂等)。"""
    schema.ensure_schema_once(get_engine())
    _ensure_v6_columns()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(schema.qianlong_pool_entries)
            .where(schema.qianlong_pool_entries.c.trade_date == exec_date)
        )
        for e in entries:
            session.execute(
                pg_insert(schema.qianlong_pool_entries).values(
                    trade_date=exec_date,
                    vt_symbol=str(e["vt_symbol"]),
                    name=str(e.get("name") or ""),
                    prev_close=e.get("prev_close"),
                    trigger_price=e.get("trigger_price"),
                    limit_price=e.get("limit_price"),
                    ma20=e.get("ma20"),
                    dist_ma20=e.get("dist_ma20"),
                    chg_tm1=e.get("chg_tm1"),
                    low_tm1=e.get("low_tm1"),
                    turnover_rate_tm1=e.get("turnover_rate_tm1"),
                    market_cap_yi=e.get("market_cap_yi"),
                    vol_ma5=e.get("vol_ma5"),
                    chassis_tag=e.get("chassis_tag"),
                    trend_days=e.get("trend_days"),
                    yang10=e.get("yang10"),
                    ret10=e.get("ret10"),
                    lu_cnt20=e.get("lu_cnt20"),
                    lu_cnt60=e.get("lu_cnt60"),
                    rules_version=rules_version,
                    updated_at=now,
                )
            )
    return len(entries)


def load_pool(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    _ensure_v6_columns()
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_pool_entries)
            .where(schema.qianlong_pool_entries.c.trade_date == trade_date)
            .order_by(schema.qianlong_pool_entries.c.vt_symbol)
        ).mappings().all()
    return [dict(r) for r in rows]


def load_pool_exec_dates() -> list[date]:
    """全部「曾建过池」的执行日(升序)。

    交割单用它补「建池但零开张」的日子——池存在而当日无信号触及,
    是策略的正常状态,入册以证明覆盖完整。
    """
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_pool_entries.c.trade_date).distinct()
        ).scalars().all()
    return sorted(rows)


def latest_pool_date() -> date | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        value = session.execute(
            select(func_max(schema.qianlong_pool_entries.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def list_pool_dates(limit: int = 250) -> list[str]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_pool_entries.c.trade_date)
            .distinct()
            .order_by(desc(schema.qianlong_pool_entries.c.trade_date))
            .limit(limit)
        ).scalars().all()
    return [r.isoformat() for r in rows if isinstance(r, date)]


def func_max(column):  # 小工具:避免顶部再引 func
    from sqlalchemy import func
    return func.max(column)


# ── 信号 ──

def upsert_signal(trade_date: date, vt_symbol: str, **fields: object) -> None:
    """按主键 upsert 一行信号(只写传入字段)。"""
    schema.ensure_schema_once(get_engine())
    _ensure_v6_columns()
    now = datetime.now(timezone.utc)
    base = {"trade_date": trade_date, "vt_symbol": vt_symbol,
            "name": str(fields.pop("name", "") or ""),
            "prev_close": fields.pop("prev_close", None),
            "trigger_price": fields.pop("trigger_price", None),
            "rules_version": str(fields.pop("rules_version", ""))}
    values = {**{k: v for k, v in base.items() if v is not None}, **fields, "updated_at": now}
    stmt = pg_insert(schema.qianlong_signals).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.qianlong_signals.c.trade_date,
                        schema.qianlong_signals.c.vt_symbol],
        set_={k: getattr(stmt.excluded, k) for k in values if k not in ("trade_date", "vt_symbol")},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_signals(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    _ensure_v6_columns()
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_signals)
            .where(schema.qianlong_signals.c.trade_date == trade_date)
        ).mappings().all()
    return [dict(r) for r in rows]


def load_signal_map(trade_date: date) -> dict[str, dict[str, object]]:
    return {str(r["vt_symbol"]): r for r in load_signals(trade_date)}


def load_open_entry_signals() -> list[dict[str, object]]:
    """已买入但未了结(holding/pending_exit)的信号,EOD 逐日推进退出。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_signals)
            .where(schema.qianlong_signals.c.entry_price.is_not(None))
            .where(schema.qianlong_signals.c.exit_date.is_(None))
            .where(schema.qianlong_signals.c.status.in_(["holding", "pending_exit"]))
        ).mappings().all()
    return [dict(r) for r in rows]


def load_entered_signals(trade_date: date) -> list[dict[str, object]]:
    return [r for r in load_signals(trade_date) if r.get("entry_price") is not None]


def load_month_closed_signals(month_prefix: str) -> list[dict[str, object]]:
    """某月(YYYY-MM)已了结信号,供熔断状态计算。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.qianlong_signals)
            .where(schema.qianlong_signals.c.exit_date.is_not(None))
            .where(schema.qianlong_signals.c.trade_date >= date.fromisoformat(month_prefix + "-01"))
        ).mappings().all()
    return [dict(r) for r in rows if str(r.get("exit_date") or "").startswith(month_prefix)]


# ── 扫描轨道 ──

def save_scan_run(**fields: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(pg_insert(schema.qianlong_live_scan_runs).values(**fields))


def latest_scan_run(trade_date: date) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.qianlong_live_scan_runs)
            .where(schema.qianlong_live_scan_runs.c.trade_date == trade_date)
            .order_by(desc(schema.qianlong_live_scan_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


# ── 回测报告 ──

def save_backtest_report(rules_version: str, payload: Mapping[str, object]) -> None:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    stmt = pg_insert(schema.qianlong_backtest_runs).values(
        id=1, rules_version=rules_version, payload=dict(payload),
        built_at=now, updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.qianlong_backtest_runs.c.id],
        set_={"rules_version": rules_version, "payload": dict(payload),
              "built_at": now, "updated_at": now},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_backtest_report(rules_version: str) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.qianlong_backtest_runs.c.rules_version,
                   schema.qianlong_backtest_runs.c.built_at,
                   schema.qianlong_backtest_runs.c.payload)
            .where(schema.qianlong_backtest_runs.c.id == 1)
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
            pg_insert(schema.qianlong_backtest_rebuild_runs).values(
                source=source, status="queued", stage="排队中",
                rules_version=rules_version, requested_at=now,
            ).returning(schema.qianlong_backtest_rebuild_runs.c.id)
        ).scalar_one()
    return int(run_id)


def update_rebuild_run(run_id: int, **fields: object) -> None:
    fields.setdefault("updated_at", datetime.now(timezone.utc))
    with session_scope() as session:
        session.execute(
            update(schema.qianlong_backtest_rebuild_runs)
            .where(schema.qianlong_backtest_rebuild_runs.c.id == run_id)
            .values(**fields)
        )


def latest_rebuild_run() -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.qianlong_backtest_rebuild_runs)
            .order_by(desc(schema.qianlong_backtest_rebuild_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


def fail_stale_rebuild_runs(stale_minutes: int = 30) -> int:
    """把超时仍停在 queued/running 的重建任务标 failed,返回清理条数。

    uvicorn 多 worker 下手动 rebuild 的执行线程随 worker 进程崩溃而消失
    (uvicorn 秒级补位新 worker,但线程不复活),状态会永远停在 running;
    容器重启也会遗留僵尸。正常全量回放仅 1~5 分钟,30 分钟阈值安全。
    """
    schema.ensure_schema_once(get_engine())
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    with session_scope() as session:
        result = session.execute(
            update(schema.qianlong_backtest_rebuild_runs)
            .where(schema.qianlong_backtest_rebuild_runs.c.status.in_(("queued", "running")),
                   schema.qianlong_backtest_rebuild_runs.c.requested_at < cutoff)
            .values(status="failed", stage="失败",
                    error="执行进程中断(worker 崩溃或重启),请重新计算",
                    finished_at=datetime.now(timezone.utc))
        )
    return int(result.rowcount or 0)


def has_active_rebuild_run() -> bool:
    """是否存在排队/执行中的重建任务(跨进程去重,以 DB 状态为准)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        run_id = session.execute(
            select(schema.qianlong_backtest_rebuild_runs.c.id)
            .where(schema.qianlong_backtest_rebuild_runs.c.status.in_(("queued", "running")))
            .order_by(desc(schema.qianlong_backtest_rebuild_runs.c.id))
            .limit(1)
        ).scalar_one_or_none()
    return run_id is not None
