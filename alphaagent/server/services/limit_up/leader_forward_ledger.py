"""首板龙头前向纸面台账（Phase 3 强制门）：信号落表 + T+1 结算 + 周报。

- **落表**（capture）：盘中定时（10:05 / 15:05）把实时推荐榜写进
  ``leader_forward_signals``，首次捕获保留潜力分/因子分位/价格，
  后续捕获只刷新状态/封单字段（撤单演化可见）。
- **结算**（settle）：晚间 EOD 批次回填 D 收盘与 D+1 开盘/收盘，
  收益口径与回测/研究一致（``d1_open / d_close - 1``，未扣费）。
- **周报**（report）：按 ISO 周聚合胜率/均值/封板率，对照回测预期，
  供前向强制门验收（前向未达标前不进任何实盘权重）。

只读实时快照与日线、只写台账表，绝不触碰交易链路。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.first_board_leader_service import (
    build_first_board_leader_snapshot,
)

SHANGHAI = timezone(timedelta(hours=8))
LEDGER_STRATEGY = "leader-forward-ledger-v1"


def _num(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ── 落表 ───────────────────────────────────────────────────────────────


def capture_forward_signals(captured_at: datetime | None = None) -> dict[str, object]:
    """把当前实时推荐榜写入台账（首捕建行、复捕只刷状态/封单）。"""

    captured_at = captured_at or datetime.now(SHANGHAI)
    snapshot = build_first_board_leader_snapshot()
    leaders = snapshot.get("leaders") or []
    trade_date_text = str(snapshot.get("trade_date") or "")[:10]
    if not leaders or not trade_date_text:
        return {
            "status": "skipped",
            "rows_read": 0,
            "rows_written": 0,
            "message": "当前无首板候选或快照不可用",
        }
    trade_date = date.fromisoformat(trade_date_text)
    written = 0
    with session_scope() as session:
        for leader in leaders:
            symbol = str(leader.get("vt_symbol") or "")
            if not symbol:
                continue
            existing = session.execute(
                select(schema.leader_forward_signals).where(
                    (schema.leader_forward_signals.c.trade_date == trade_date)
                    & (schema.leader_forward_signals.c.vt_symbol == symbol)
                )
            ).mappings().first()
            if existing is None:
                session.execute(
                    schema.leader_forward_signals.insert().values(
                        trade_date=trade_date,
                        vt_symbol=symbol,
                        name=str(leader.get("name") or "") or None,
                        first_captured_at=captured_at,
                        last_captured_at=captured_at,
                        capture_count=1,
                        **_capture_fields(leader),
                    )
                )
            else:
                session.execute(
                    schema.leader_forward_signals.update()
                    .where(schema.leader_forward_signals.c.id == existing["id"])
                    .values(
                        last_captured_at=captured_at,
                        capture_count=int(existing["capture_count"] or 1) + 1,
                        **_capture_fields(leader),
                    )
                )
            written += 1
    return {
        "status": "ok",
        "rows_read": len(leaders),
        "rows_written": written,
        "message": f"前向台账已捕获 {trade_date_text} 推荐 {written} 只",
    }


def _capture_fields(leader: Mapping[str, object]) -> dict[str, object]:
    return {
        "potential_score": _num(leader.get("potential_score")),
        "factor_percentiles": dict(leader.get("factor_percentiles") or {}),
        "change_pct": _num(leader.get("change_pct")),
        "last_price": _num(leader.get("last_price")),
        "limit_price": _num(leader.get("limit_price")),
        "state": str(leader.get("state") or "") or None,
        "first_limit_time": str(leader.get("first_limit_time") or "") or None,
        "open_times": _int_or_none(leader.get("open_times")),
        "seal_to_turnover_ratio": _num(leader.get("seal_to_turnover_ratio")),
        "seal_amount_retention_ratio": _num(leader.get("seal_amount_retention_ratio")),
        "seal_weakening": bool(leader.get("seal_weakening")),
        "late_seal": bool(leader.get("late_seal")),
    }


# ── T+1 结算 ───────────────────────────────────────────────────────────


def settle_forward_signals() -> dict[str, object]:
    """回填未结算信号的 D 收盘 / D+1 开盘收盘（下一交易日日线出现即结算）。"""

    settled = 0
    pending = 0
    with session_scope() as session:
        rows = session.execute(
            select(schema.leader_forward_signals).where(
                schema.leader_forward_signals.c.settled_at.is_(None)
            )
        ).mappings().all()
        for row in rows:
            d_bar = _daily_bar(session, row["vt_symbol"], row["trade_date"])
            if d_bar is None:
                pending += 1
                continue
            d_close = _num(d_bar.get("close_price"))
            d1_bar = _next_daily_bar(session, row["vt_symbol"], row["trade_date"])
            if d_close is None or d1_bar is None:
                pending += 1
                continue
            d1_open = _num(d1_bar.get("open_price"))
            d1_close = _num(d1_bar.get("close_price"))
            sealed = _is_sealed_close(d_bar, row["vt_symbol"])
            session.execute(
                schema.leader_forward_signals.update()
                .where(schema.leader_forward_signals.c.id == row["id"])
                .values(
                    board_status="sealed" if sealed else "no_limit",
                    d_close=d_close,
                    d1_trade_date=d1_bar.get("trade_date"),
                    d1_open=d1_open,
                    d1_close=d1_close,
                    d1_open_return_pct=(
                        round((d1_open / d_close - 1) * 100, 4) if d1_open else None
                    ),
                    d1_close_return_pct=(
                        round((d1_close / d_close - 1) * 100, 4) if d1_close else None
                    ),
                    is_win=(d1_open is not None and d1_open > d_close),
                    settled_at=datetime.now(timezone.utc),
                )
            )
            settled += 1
    return {
        "status": "ok",
        "rows_read": len(rows),
        "rows_written": settled,
        "message": f"前向台账结算 {settled} 条（待结算 {pending} 条）",
    }


def _daily_bar(
    session, vt_symbol: str, trade_date: date
) -> Mapping[str, object] | None:
    return session.execute(
        select(schema.stock_daily_bars).where(
            (schema.stock_daily_bars.c.vt_symbol == vt_symbol)
            & (schema.stock_daily_bars.c.trade_date == trade_date)
        )
    ).mappings().first()


def _next_daily_bar(
    session, vt_symbol: str, trade_date: date
) -> Mapping[str, object] | None:
    return (
        session.execute(
            select(schema.stock_daily_bars)
            .where(
                (schema.stock_daily_bars.c.vt_symbol == vt_symbol)
                & (schema.stock_daily_bars.c.trade_date > trade_date)
            )
            .order_by(schema.stock_daily_bars.c.trade_date)
            .limit(1)
        )
        .mappings()
        .first()
    )


def _is_sealed_close(d_bar: Mapping[str, object], vt_symbol: str) -> bool:
    close = _num(d_bar.get("close_price"))
    change = _num(d_bar.get("change_pct"))
    if close is None or change is None:
        return False
    code = vt_symbol.split(".")[0]
    threshold = 19.5 if code.startswith(("30", "68")) else 9.5
    return change >= threshold


# ── 周报 ───────────────────────────────────────────────────────────────


def build_forward_ledger_report(weeks: int = 8) -> dict[str, object]:
    """按 ISO 周聚合前向台账，对照回测预期（分钟级 v4-B 写库值）。"""

    weeks = min(max(weeks, 1), 26)
    cutoff = date.today() - timedelta(days=weeks * 7)
    with session_scope() as session:
        rows = session.execute(
            select(schema.leader_forward_signals)
            .where(schema.leader_forward_signals.c.trade_date >= cutoff)
            .order_by(schema.leader_forward_signals.c.trade_date.desc())
        ).mappings().all()
    by_week: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        trade_date = row["trade_date"]
        iso = trade_date.isocalendar() if isinstance(trade_date, date) else None
        key = f"{iso.year}-W{iso.week:02d}" if iso else "unknown"
        by_week[key].append(row)
    weekly: list[dict[str, object]] = []
    for week in sorted(by_week, reverse=True):
        members = by_week[week]
        settled_rows = [row for row in members if row.get("settled_at") is not None]
        returns = [
            value
            for value in (_num(row.get("d1_open_return_pct")) for row in settled_rows)
            if value is not None
        ]
        wins = sum(1 for row in settled_rows if row.get("is_win"))
        sealed = sum(1 for row in settled_rows if row.get("board_status") == "sealed")
        weekly.append(
            {
                "week": week,
                "signals": len(members),
                "settled": len(settled_rows),
                "win_rate": round(wins / len(settled_rows) * 100, 2) if settled_rows else None,
                "avg_d1_open_return_pct": round(mean(returns), 4) if returns else None,
                "seal_rate": (
                    round(sealed / len(settled_rows) * 100, 2) if settled_rows else None
                ),
            }
        )
    recent = [
        {
            "trade_date": row["trade_date"].isoformat()
            if isinstance(row["trade_date"], date)
            else str(row["trade_date"]),
            "vt_symbol": row["vt_symbol"],
            "name": row["name"],
            "potential_score": _num(row.get("potential_score")),
            "change_pct": _num(row.get("change_pct")),
            "state": row["state"],
            "board_status": row["board_status"],
            "late_seal": bool(row.get("late_seal")),
            "seal_weakening": bool(row.get("seal_weakening")),
            "seal_to_turnover_ratio": _num(row.get("seal_to_turnover_ratio")),
            "d1_open_return_pct": _num(row.get("d1_open_return_pct")),
            "is_win": row.get("is_win"),
            "settled": row.get("settled_at") is not None,
        }
        for row in rows[:60]
    ]
    return {
        "status": "ok" if rows else "empty",
        "strategy": LEDGER_STRATEGY,
        "weeks": weekly,
        "recent": recent,
        "backtest_reference": _backtest_reference(),
        "notes": [
            "收益口径 = D+1 开盘 / D 收盘 - 1（未扣费），与回测/研究一致。",
            "前向台账为纸面跟踪，非实盘；前向未达标前不进任何实盘权重（Phase 3 强制门）。",
        ],
    }


def _backtest_reference() -> dict[str, object]:
    from alphaagent.server.services.limit_up.leader_minute_repository import (
        load_minute_backtest_run,
    )

    payload = load_minute_backtest_run() or {}
    summary = payload.get("execution_summary") or {}
    return {
        "total_return_pct": summary.get("total_return_pct"),
        "win_rate": summary.get("win_rate"),
        "average_return_pct": summary.get("average_return_pct"),
        "trade_count": summary.get("trade_count"),
    }
