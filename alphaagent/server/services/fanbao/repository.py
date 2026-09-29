"""断板反包打板持久层:池/信号/扫描轨道/回测报告的读写。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone

from sqlalchemy import delete, desc, func, select, tuple_, update
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
            delete(schema.fbb_pool_entries)
            .where(schema.fbb_pool_entries.c.trade_date == exec_date)
        )
        for e in entries:
            session.execute(
                pg_insert(schema.fbb_pool_entries).values(
                    trade_date=exec_date,
                    vt_symbol=str(e["vt_symbol"]),
                    name=str(e.get("name") or ""),
                    group6=str(e["group6"]),
                    n_board=int(e["n_board"]),
                    seg=str(e["seg"]),
                    gap=int(e["gap"]),
                    yin_yang=str(e["yin_yang"]),
                    point=str(e.get("point") or "—"),
                    level=str(e.get("level") or "—"),
                    actionable=bool(e.get("actionable")),
                    avoid_static=e.get("avoid_static"),
                    prev_close=e.get("prev_close"),
                    limit_price=e.get("limit_price"),
                    break_end=e.get("break_end"),
                    wave_start=e.get("wave_start"),
                    break_days=e.get("break_days"),
                    break_yin_count=e.get("break_yin_count"),
                    break_zha_days=e.get("break_zha_days"),
                    break_drop_pct=e.get("break_drop_pct"),
                    pit_depth_pct=e.get("pit_depth_pct"),
                    last_entity=e.get("last_entity"),
                    last_open_pct=e.get("last_open_pct"),
                    dist_ma5=e.get("dist_ma5"),
                    dist_h60=e.get("dist_h60"),
                    ma_state=e.get("ma_state"),
                    dist_ma10=e.get("dist_ma10"),
                    chain=e.get("chain"),
                    foundation_yang=e.get("foundation_yang"),
                    foundation_chg=e.get("foundation_chg"),
                    prior_gap=e.get("prior_gap"),
                    prev_wave60=e.get("prev_wave60"),
                    prev_wave120=e.get("prev_wave120"),
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
            select(schema.fbb_pool_entries)
            .where(schema.fbb_pool_entries.c.trade_date == trade_date)
            .order_by(schema.fbb_pool_entries.c.group6,
                      schema.fbb_pool_entries.c.point,
                      schema.fbb_pool_entries.c.vt_symbol)
        ).mappings().all()
    return [dict(r) for r in rows]


def latest_pool_date() -> date | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.fbb_pool_entries.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def list_pool_dates(limit: int = 250) -> list[str]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.fbb_pool_entries.c.trade_date)
            .distinct()
            .order_by(desc(schema.fbb_pool_entries.c.trade_date))
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
            "group6": str(fields.pop("group6", "") or ""),
            "point": str(fields.pop("point", "—") or "—"),
            "level": str(fields.pop("level", "—") or "—"),
            "prev_close": fields.pop("prev_close", None),
            "limit_price": fields.pop("limit_price", None),
            "rules_version": str(fields.pop("rules_version", ""))}
    values = {**{k: v for k, v in base.items() if v is not None}, **fields, "updated_at": now}
    stmt = pg_insert(schema.fbb_signals).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.fbb_signals.c.trade_date,
                        schema.fbb_signals.c.vt_symbol],
        set_={k: getattr(stmt.excluded, k) for k in values if k not in _SIGNAL_PK},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_signals(trade_date: date) -> list[dict[str, object]]:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = session.execute(
            select(schema.fbb_signals)
            .where(schema.fbb_signals.c.trade_date == trade_date)
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
            select(schema.fbb_signals)
            .where(schema.fbb_signals.c.entry_price.is_not(None))
            .where(schema.fbb_signals.c.exit_date.is_(None))
            .where(schema.fbb_signals.c.status.in_(["entered", "holding", "pending_exit"]))
        ).mappings().all()
    return [dict(r) for r in rows]


def load_entered_signals(trade_date: date) -> list[dict[str, object]]:
    return [r for r in load_signals(trade_date) if r.get("entry_price") is not None]


# ── 扫描轨道 ──

def save_scan_run(**fields: object) -> None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(pg_insert(schema.fbb_live_scan_runs).values(**fields))


def latest_scan_run(trade_date: date) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.fbb_live_scan_runs)
            .where(schema.fbb_live_scan_runs.c.trade_date == trade_date)
            .order_by(desc(schema.fbb_live_scan_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


# ── 回测报告 ──

def save_backtest_report(rules_version: str, payload: Mapping[str, object]) -> None:
    schema.ensure_schema_once(get_engine())
    now = datetime.now(timezone.utc)
    stmt = pg_insert(schema.fbb_backtest_runs).values(
        id=1, rules_version=rules_version, payload=dict(payload),
        built_at=now, updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[schema.fbb_backtest_runs.c.id],
        set_={"rules_version": rules_version, "payload": dict(payload),
              "built_at": now, "updated_at": now},
    )
    with session_scope() as session:
        session.execute(stmt)


def load_backtest_report(rules_version: str) -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.fbb_backtest_runs.c.rules_version,
                   schema.fbb_backtest_runs.c.built_at,
                   schema.fbb_backtest_runs.c.payload)
            .where(schema.fbb_backtest_runs.c.id == 1)
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
            pg_insert(schema.fbb_backtest_rebuild_runs).values(
                source=source, status="queued", stage="排队中",
                rules_version=rules_version, requested_at=now,
            ).returning(schema.fbb_backtest_rebuild_runs.c.id)
        ).scalar_one()
    return int(run_id)


def update_rebuild_run(run_id: int, **fields: object) -> None:
    fields.setdefault("updated_at", datetime.now(timezone.utc))
    with session_scope() as session:
        session.execute(
            update(schema.fbb_backtest_rebuild_runs)
            .where(schema.fbb_backtest_rebuild_runs.c.id == run_id)
            .values(**fields)
        )


def latest_rebuild_run() -> dict[str, object] | None:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        row = session.execute(
            select(schema.fbb_backtest_rebuild_runs)
            .order_by(desc(schema.fbb_backtest_rebuild_runs.c.id))
            .limit(1)
        ).mappings().one_or_none()
    return dict(row) if row else None


# ── 答题训练题库(随回测重建整表替换;API 只读) ──

def save_quiz_questions(rules_version: str, rows: list[Mapping[str, object]]) -> int:
    """整表替换题库(单事务 delete-all + 逐行写入;幂等)。"""
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        session.execute(delete(schema.fbb_quiz_questions))
        for row in rows:
            session.execute(
                pg_insert(schema.fbb_quiz_questions).values(
                    decision_date=row["decision_date"],
                    vt_symbol=row["vt_symbol"],
                    year=row["year"],
                    month=row["month"],
                    seq=row["seq"],
                    name=row["name"],
                    group6=row["group6"],
                    point=row["point"],
                    ret_pct=row.get("ret_pct"),
                    payload=row["payload"],
                    rules_version=rules_version,
                )
            )
    return len(rows)


def load_quiz_overview() -> dict[str, object]:
    """题库标量聚合:year→month→{total,buy_count,reject_count}+全库合计+版本。"""
    schema.ensure_schema_once(get_engine())
    t = schema.fbb_quiz_questions
    with session_scope() as session:
        rows = session.execute(
            select(
                t.c.year, t.c.month,
                func.count().label("total"),
                func.count().filter(t.c.point != "—").label("buy_count"),
                func.count().filter(t.c.point == "—").label("reject_count"),
            ).group_by(t.c.year, t.c.month).order_by(t.c.year, t.c.month)
        ).mappings().all()
        versions = session.execute(
            select(t.c.rules_version).distinct()
        ).scalars().all()
    return {"months": [dict(r) for r in rows],
            "rules_versions": [str(v) for v in versions]}


def load_quiz_questions(month: str) -> list[dict[str, object]]:
    """该月全部题目 payload,按 seq 升序。"""
    schema.ensure_schema_once(get_engine())
    t = schema.fbb_quiz_questions
    with session_scope() as session:
        rows = session.execute(
            select(t.c.payload).where(t.c.month == month).order_by(t.c.seq)
        ).scalars().all()
    return [dict(r) for r in rows if isinstance(r, Mapping)]


def quiz_bank_status() -> dict[str, object]:
    """{rules_version, count}(reconcile 自检:版本漂移/空表→触发重建)。"""
    schema.ensure_schema_once(get_engine())
    t = schema.fbb_quiz_questions
    with session_scope() as session:
        versions = session.execute(select(t.c.rules_version).distinct()).scalars().all()
        count = session.execute(select(func.count()).select_from(t)).scalar_one()
    return {"rules_versions": [str(v) for v in versions], "count": int(count)}


def load_quiz_mix_projection(year: str | None = None) -> list[dict[str, object]]:
    """综合挑战卷抽题投影:[{decision_date, vt_symbol, point, trap_kind}](轻量,
    trap_kind 从 payload.explain JSON 抽取,命中题为 NULL→None;不读K线大字段)。
    year 非空时只抽该年(按年份练市场环境)。"""
    schema.ensure_schema_once(get_engine())
    t = schema.fbb_quiz_questions
    stmt = select(t.c.decision_date, t.c.vt_symbol, t.c.point,
                  t.c.payload["explain"]["trap_kind"].astext.label("trap_kind"))
    if year:
        stmt = stmt.where(t.c.year == year)
    with session_scope() as session:
        rows = session.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def load_quiz_questions_by_keys(keys: list[tuple]) -> list[dict[str, object]]:
    """按 (decision_date, vt_symbol) 主键批量拉完整 payload(综合挑战卷用)。"""
    if not keys:
        return []
    schema.ensure_schema_once(get_engine())
    t = schema.fbb_quiz_questions
    with session_scope() as session:
        rows = session.execute(
            select(t.c.payload).where(
                tuple_(t.c.decision_date, t.c.vt_symbol).in_(keys))
        ).scalars().all()
    return [dict(r) for r in rows if isinstance(r, Mapping)]
