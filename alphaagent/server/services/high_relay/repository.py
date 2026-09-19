"""高位接力打板持久层:池/信号/扫描轨道/回测报告的读写。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope

_SIGNAL_PK = ("trade_date", "vt_symbol")


# ── 首触板时间(复用 w2s_touch_times 全市场通用心跳表;只读+同口径增量写) ──

def load_touch_map() -> dict[tuple[str, date], str]:
    """全表 → {(vt_symbol, D0日): 'HH:MM'}(15mK周期末刻); 行数~数千,直接全读。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(select(
            schema.w2s_touch_times.c.vt_symbol,
            schema.w2s_touch_times.c.trade_date,
            schema.w2s_touch_times.c.touch,
        )).all()
    return {(str(v), d): str(t) for v, d, t in rows}


def upsert_touch_times(rows: list[Mapping[str, object]]) -> int:
    """幂等批量写入 {(vt_symbol, trade_date, touch, source)}; 同键 zt_pool 覆盖 pytdx(更新鲜)。"""
    if not rows:
        return 0
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        for r in rows:
            stmt = pg_insert(schema.w2s_touch_times).values(
                vt_symbol=str(r["vt_symbol"]), trade_date=r["trade_date"],
                touch=str(r["touch"]), source=str(r.get("source", "zt_pool")))
            stmt = stmt.on_conflict_do_update(
                index_elements=["vt_symbol", "trade_date"],
                set_={"touch": stmt.excluded.touch, "source": stmt.excluded.source})
            session.execute(stmt)
    return len(rows)


# ── 盘前池 ──

def save_pool(exec_date: date, entries: list[Mapping[str, object]], rules_version: str) -> int:
    """整覆写某执行日的池(先删后插,幂等)。"""
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(
            delete(schema.hpr_pool_entries)
            .where(schema.hpr_pool_entries.c.trade_date == exec_date)
        )
        for e in entries:
            session.execute(
                pg_insert(schema.hpr_pool_entries).values(
                    trade_date=exec_date,
                    vt_symbol=str(e["vt_symbol"]),
                    name=str(e.get("name") or ""),
                    group4=str(e["group4"]),
                    n_board=int(e["n_board"]),
                    point=str(e.get("point") or "—"),
                    level=str(e.get("level") or "—"),
                    actionable=bool(e.get("actionable")),
                    avoid_static=e.get("avoid_static"),
                    auction_gate=e.get("auction_gate"),
                    prev_close=e.get("prev_close"),
                    limit_price=e.get("limit_price"),
                    foundation_yang=e.get("foundation_yang"),
                    foundation_chg=e.get("foundation_chg"),
                    dist_h60=e.get("dist_h60"),
                    ma_state=e.get("ma_state"),
                    dist_ma10=e.get("dist_ma10"),
                    prior_height=e.get("prior_height"),
                    prior_gap=e.get("prior_gap"),
                    prev_wave60=e.get("prev_wave60"),
                    prev_wave120=e.get("prev_wave120"),
                    chain=e.get("chain"),
                    b1_type=e.get("b1_type"),
                    b2_type=e.get("b2_type"),
                    b3_type=e.get("b3_type"),
                    b1_open=e.get("b1_open"),
                    b2_open=e.get("b2_open"),
                    b1_turn=e.get("b1_turn"),
                    b2_turn=e.get("b2_turn"),
                    turn_grad=e.get("turn_grad"),
                    mkt_lim_tm1=e.get("mkt_lim_tm1"),
                    rules_version=rules_version,
                    updated_at=now,
                )
            )
    return len(entries)


def load_pool(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.hpr_pool_entries)
            .where(schema.hpr_pool_entries.c.trade_date == trade_date)
            .order_by(schema.hpr_pool_entries.c.group4,
                      schema.hpr_pool_entries.c.point,
                      schema.hpr_pool_entries.c.vt_symbol)
        ).mappings().all()
    return [dict(r) for r in rows]


def latest_pool_date() -> date | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.hpr_pool_entries.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def list_pool_dates(limit: int = 250) -> list[str]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.hpr_pool_entries.c.trade_date)
            .distinct()
            .order_by(desc(schema.hpr_pool_entries.c.trade_date))
            .limit(limit)
        ).scalars().all()
    return [r.isoformat() for r in rows if isinstance(r, date)]


# ── 信号 ──

def upsert_signal(trade_date: date, vt_symbol: str, **fields: object) -> None:
    """按主键 upsert 一行信号(只写传入字段)。"""
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    base = {"trade_date": trade_date, "vt_symbol": vt_symbol,
            "name": str(fields.pop("name", "") or ""),
            "group4": str(fields.pop("group4", "") or ""),
            "point": str(fields.pop("point", "—") or "—"),
            "prev_close": fields.pop("prev_close", None),
            "limit_price": fields.pop("limit_price", None),
            "rules_version": str(fields.pop("rules_version", ""))}
    values = {**{k: v for k, v in base.items() if v is not None}, **fields, "updated_at": now}
    stmt = pg_insert(schema.hpr_signals).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.hpr_signals.c.trade_date,
                        schema.hpr_signals.c.vt_symbol],
        set_={k: getattr(stmt.excluded, k) for k in values if k not in _SIGNAL_PK},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_signals(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.hpr_signals)
            .where(schema.hpr_signals.c.trade_date == trade_date)
        ).mappings().all()
    return [dict(r) for r in rows]


def load_signal_map(trade_date: date) -> dict[str, dict[str, object]]:
    """vt_symbol → 信号行。"""
    return {str(r["vt_symbol"]): r for r in load_signals(trade_date)}


def load_open_entry_signals() -> list[dict[str, object]]:
    """已买入但未了结(entered/holding/pending_exit)的信号,EOD 逐日推进退出。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.hpr_signals)
            .where(schema.hpr_signals.c.entry_price.is_not(None))
            .where(schema.hpr_signals.c.exit_date.is_(None))
            .where(schema.hpr_signals.c.status.in_(["entered", "holding", "pending_exit"]))
        ).mappings().all()
    return [dict(r) for r in rows]


def load_entered_signals(trade_date: date) -> list[dict[str, object]]:
    return [r for r in load_signals(trade_date) if r.get("entry_price") is not None]


# ── 扫描轨道 ──

def save_scan_run(**fields: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(pg_insert(schema.hpr_live_scan_runs).values(**fields))


def latest_scan_run(trade_date: date) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.hpr_live_scan_runs)
            .where(schema.hpr_live_scan_runs.c.trade_date == trade_date)
            .order_by(desc(schema.hpr_live_scan_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


# ── 回测报告 ──

def save_backtest_report(rules_version: str, payload: Mapping[str, object]) -> None:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    stmt = pg_insert(schema.hpr_backtest_runs).values(
        id=1, rules_version=rules_version, payload=dict(payload),
        built_at=now, updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.hpr_backtest_runs.c.id],
        set_={"rules_version": rules_version, "payload": dict(payload),
              "built_at": now, "updated_at": now},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_backtest_report(rules_version: str) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.hpr_backtest_runs.c.rules_version,
                   schema.hpr_backtest_runs.c.built_at,
                   schema.hpr_backtest_runs.c.payload)
            .where(schema.hpr_backtest_runs.c.id == 1)
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
            pg_insert(schema.hpr_backtest_rebuild_runs).values(
                source=source, status="queued", stage="排队中",
                rules_version=rules_version, requested_at=now,
            ).returning(schema.hpr_backtest_rebuild_runs.c.id)
        ).scalar_one()
    return int(run_id)


def update_rebuild_run(run_id: int, **fields: object) -> None:
    fields.setdefault("updated_at", datetime.now(timezone.utc))
    with session_scope() as session:
        session.execute(
            update(schema.hpr_backtest_rebuild_runs)
            .where(schema.hpr_backtest_rebuild_runs.c.id == run_id)
            .values(**fields)
        )


def latest_rebuild_run() -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.hpr_backtest_rebuild_runs)
            .order_by(desc(schema.hpr_backtest_rebuild_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None
