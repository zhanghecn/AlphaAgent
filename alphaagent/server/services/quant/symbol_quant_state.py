"""Unified latest quant-process state for one symbol."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, desc, select

from alphaagent.market.boards import stock_board_payload
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.quant import screening_payloads, strategy_replay
from alphaagent.server.services.quant.factors import STRATEGY_ID
from alphaagent.server.services.quant.strategy_registry import get_strategy


def latest_symbol_quant_state(vt_symbol: str, strategy_id: str = STRATEGY_ID) -> dict[str, Any]:
    """Return one symbol's status in the latest global quant process.

    The response intentionally ties signal, candidate, and replay information to
    the same latest global process range. Older symbol-specific replay results
    must not be mixed into this view, otherwise the stock detail page can show a
    candidate plan from one process and an execution result from another.
    """

    symbol = _normalize_symbol(vt_symbol)
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"status": "unsupported_strategy", "strategy_id": strategy_id}

    _ensure_schema()
    with session_scope() as session:
        stock = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol == symbol)).mappings().first()
        latest_trade_date = session.execute(select(schema.stock_daily_bars.c.trade_date).where(schema.stock_daily_bars.c.vt_symbol == symbol).order_by(desc(schema.stock_daily_bars.c.trade_date)).limit(1)).scalar_one_or_none()
        replay_run = session.execute(
            select(schema.strategy_replay_runs)
            .where(
                and_(
                    schema.strategy_replay_runs.c.strategy_id == strategy.id,
                    schema.strategy_replay_runs.c.strategy_version == strategy.version,
                )
            )
            .order_by(desc(schema.strategy_replay_runs.c.id))
            .limit(1)
        ).mappings().first()
        screen_run = session.execute(
            select(schema.quant_signal_runs)
            .where(
                and_(
                    schema.quant_signal_runs.c.strategy_id == strategy.id,
                    schema.quant_signal_runs.c.strategy_version == strategy.version,
                )
            )
            .order_by(desc(schema.quant_signal_runs.c.trade_date), desc(schema.quant_signal_runs.c.id))
            .limit(1)
        ).mappings().first()
        use_replay = replay_run and (
            not screen_run
            or replay_run["end_date"] >= screen_run["trade_date"]
        )

        if use_replay:
            process = _process_from_replay(dict(replay_run))
            signal_rows = _signal_rows_for_range(
                session,
                symbol,
                strategy.id,
                str(replay_run["strategy_version"]),
                replay_run["start_date"],
                replay_run["end_date"],
            )
            recommendation = _latest_recommendation_for_range(
                session,
                symbol,
                strategy.id,
                str(replay_run["strategy_version"]),
                replay_run["start_date"],
                replay_run["end_date"],
            )
            attempts = _attempts_for_replay(session, int(replay_run["id"]), symbol)
        else:
            if not screen_run:
                return {
                    "status": "empty",
                    "vt_symbol": symbol,
                    "name": stock.get("name") if stock else None,
                    **stock_board_payload(symbol, stock.get("exchange") if stock else None),
                    "strategy_id": strategy.id,
                    "message": "暂无全局量化过程。请先在量化页刷新候选并回测。",
                }
            process = _process_from_screen(dict(screen_run))
            signal_rows = _signal_rows_for_run(session, int(screen_run["id"]), symbol)
            recommendation = _recommendation_for_run(session, int(screen_run["id"]), symbol)
            attempts = []

    replay = _replay_payload(process.get("replay_run_id"), symbol, stock, attempts)
    signal = _signal_payload(signal_rows)
    candidate = _candidate_payload(recommendation)
    state = _state(signal, candidate, replay)
    return {
        "status": "ready",
        "vt_symbol": symbol,
        "name": stock.get("name") if stock else None,
        **stock_board_payload(symbol, stock.get("exchange") if stock else None),
        "strategy_id": strategy.id,
        "strategy_version": process.get("strategy_version") or strategy.version,
        "process": {
            **process,
            "latest_available_trade_date": _date_text(latest_trade_date),
            "is_stale": bool(latest_trade_date and process.get("end_date") and str(process.get("end_date")) < latest_trade_date.isoformat()),
        },
        "state": state,
        "signal": signal,
        "candidate": candidate,
        "replay": replay,
        "message": _message(state, process),
    }


def _process_from_replay(row: dict[str, Any]) -> dict[str, Any]:
    params = row.get("params") if isinstance(row.get("params"), dict) else {}
    return {
        "source": "replay",
        "replay_run_id": int(row["id"]),
        "screen_run_id": None,
        "strategy_id": row.get("strategy_id"),
        "strategy_version": row.get("strategy_version"),
        "start_date": _date_text(row.get("start_date")),
        "end_date": _date_text(row.get("end_date")),
        "status": row.get("status"),
        "params": params,
        "metrics": row.get("metrics") if isinstance(row.get("metrics"), dict) else {},
        "message": row.get("message"),
        "included_boards": params.get("included_boards") if isinstance(params.get("included_boards"), list) else [],
    }


def _process_from_screen(row: dict[str, Any]) -> dict[str, Any]:
    params = row.get("params") if isinstance(row.get("params"), dict) else {}
    trade_date = _date_text(row.get("trade_date"))
    return {
        "source": "screen",
        "replay_run_id": None,
        "screen_run_id": int(row["id"]),
        "strategy_id": row.get("strategy_id"),
        "strategy_version": row.get("strategy_version"),
        "start_date": trade_date,
        "end_date": trade_date,
        "status": row.get("status"),
        "params": params,
        "metrics": {
            "candidate_count": row.get("candidate_count"),
            "signal_count": row.get("signal_count"),
            "recommendation_count": row.get("recommendation_count"),
        },
        "message": row.get("message"),
        "included_boards": params.get("included_boards") if isinstance(params.get("included_boards"), list) else [],
    }


def _signal_rows_for_range(session, symbol: str, strategy_id: str, strategy_version: str, start, end) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.quant_stock_signals)
        .where(
            and_(
                schema.quant_stock_signals.c.vt_symbol == symbol,
                schema.quant_stock_signals.c.strategy_id == strategy_id,
                schema.quant_stock_signals.c.strategy_version == strategy_version,
                schema.quant_stock_signals.c.trade_date >= start,
                schema.quant_stock_signals.c.trade_date <= end,
            )
        )
        .order_by(desc(schema.quant_stock_signals.c.trade_date), desc(schema.quant_stock_signals.c.total_score))
    ).mappings().all()
    return [screening_payloads.mapping_to_api(dict(row)) for row in rows]


def _signal_rows_for_run(session, run_id: int, symbol: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.quant_stock_signals)
        .where(
            and_(
                schema.quant_stock_signals.c.run_id == run_id,
                schema.quant_stock_signals.c.vt_symbol == symbol,
            )
        )
        .order_by(desc(schema.quant_stock_signals.c.trade_date), desc(schema.quant_stock_signals.c.total_score))
    ).mappings().all()
    return [screening_payloads.mapping_to_api(dict(row)) for row in rows]


def _latest_recommendation_for_range(session, symbol: str, strategy_id: str, strategy_version: str, start, end) -> dict[str, Any] | None:
    row = session.execute(
        select(
            schema.quant_recommendations,
            schema.stocks.c.name.label("stock_name"),
        )
        .select_from(
            schema.quant_recommendations.outerjoin(
                schema.stocks,
                schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            and_(
                schema.quant_recommendations.c.vt_symbol == symbol,
                schema.quant_recommendations.c.strategy_id == strategy_id,
                schema.quant_recommendations.c.strategy_version == strategy_version,
                schema.quant_recommendations.c.trade_date >= start,
                schema.quant_recommendations.c.trade_date <= end,
            )
        )
        .order_by(desc(schema.quant_recommendations.c.trade_date), schema.quant_recommendations.c.rank)
        .limit(1)
    ).mappings().first()
    return screening_payloads.recommendation_row_to_api(dict(row)) if row else None


def _recommendation_for_run(session, run_id: int, symbol: str) -> dict[str, Any] | None:
    row = session.execute(
        select(
            schema.quant_recommendations,
            schema.stocks.c.name.label("stock_name"),
        )
        .select_from(
            schema.quant_recommendations.outerjoin(
                schema.stocks,
                schema.quant_recommendations.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            and_(
                schema.quant_recommendations.c.run_id == run_id,
                schema.quant_recommendations.c.vt_symbol == symbol,
            )
        )
        .order_by(schema.quant_recommendations.c.rank)
        .limit(1)
    ).mappings().first()
    return screening_payloads.recommendation_row_to_api(dict(row)) if row else None


def _attempts_for_replay(session, replay_run_id: int, symbol: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.strategy_replay_attempts)
        .where(
            and_(
                schema.strategy_replay_attempts.c.replay_run_id == replay_run_id,
                schema.strategy_replay_attempts.c.vt_symbol == symbol,
            )
        )
        .order_by(
            schema.strategy_replay_attempts.c.signal_date,
            schema.strategy_replay_attempts.c.side,
            schema.strategy_replay_attempts.c.id,
        )
    ).mappings().all()
    return [strategy_replay._mapping_to_api(dict(row)) for row in rows]


def _signal_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "status": "not_scored",
            "scored_date_count": 0,
            "entry_signal_count": 0,
            "latest": None,
            "latest_entry_signal": None,
            "best_total_score": None,
            "recent": [],
        }
    entry_rows = [row for row in rows if bool(row.get("executable_entry_signal"))]
    best = max(rows, key=lambda row: float(row.get("total_score") or 0))
    latest = rows[0]
    latest_entry = entry_rows[0] if entry_rows else None
    return {
        "status": "buy_signal" if latest_entry else "scored",
        "scored_date_count": len(rows),
        "entry_signal_count": len(entry_rows),
        "latest": latest,
        "latest_entry_signal": latest_entry,
        "best_total_score": best,
        "recent": rows[:20],
    }


def _candidate_payload(recommendation: dict[str, Any] | None) -> dict[str, Any]:
    if not recommendation:
        return {"status": "not_candidate", "item": None, "trade_plan": None}
    risk_control = recommendation.get("risk_control") if isinstance(recommendation.get("risk_control"), dict) else {}
    return {
        "status": "candidate",
        "item": recommendation,
        "trade_plan": risk_control.get("trade_plan") if isinstance(risk_control, dict) else None,
    }


def _replay_payload(replay_run_id: int | None, symbol: str, stock: Any, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    if replay_run_id is None:
        return {
            "status": "not_generated",
            "replay_run_id": None,
            "summary": None,
            "attempts": [],
            "events": [],
            "closed_trades": [],
        }
    trades = strategy_replay._closed_trades(attempts)
    events = strategy_replay._events_from_attempts(attempts)
    summary = strategy_replay._symbol_summary(attempts, trades)
    return {
        "status": "ready" if attempts else "no_attempts",
        "replay_run_id": replay_run_id,
        "vt_symbol": symbol,
        "name": stock.get("name") if stock else None,
        "summary": summary,
        "attempts": attempts,
        "events": events,
        "closed_trades": trades,
    }


def _state(signal: dict[str, Any], candidate: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
    attempts = replay.get("attempts") or []
    buy_attempts = [row for row in attempts if str(row.get("side") or "").upper() == "BUY"]
    filled_buy = [row for row in buy_attempts if row.get("execution_status") == "filled"]
    rejected_buy = [row for row in buy_attempts if row.get("execution_status") == "rejected"]
    if filled_buy:
        latest = filled_buy[-1]
        return {"code": "buy_filled", "label": "买入成交", "severity": "success", "reason": latest.get("reject_reason")}
    if rejected_buy:
        latest = rejected_buy[-1]
        return {"code": "buy_rejected", "label": "买入拒绝", "severity": "warning", "reason": latest.get("reject_reason")}
    if candidate.get("status") == "candidate":
        if replay.get("status") == "not_generated":
            return {"code": "candidate_replay_not_generated", "label": "进入候选，未生成买卖记录", "severity": "warning", "reason": None}
        return {"code": "candidate_no_execution", "label": "进入候选，未产生执行尝试", "severity": "warning", "reason": None}
    if signal.get("entry_signal_count", 0) > 0:
        if replay.get("status") == "not_generated":
            return {"code": "signal_replay_not_generated", "label": "有 BUY 信号，未生成买卖记录", "severity": "warning", "reason": None}
        return {"code": "signal_not_candidate", "label": "有 BUY 信号，未进入候选执行", "severity": "warning", "reason": None}
    if signal.get("scored_date_count", 0) > 0:
        return {"code": "scored_no_buy", "label": "已评分，无 BUY 信号", "severity": "neutral", "reason": None}
    return {"code": "not_scored", "label": "本轮未评分", "severity": "neutral", "reason": None}


def _message(state: dict[str, Any], process: dict[str, Any]) -> str:
    start = process.get("start_date") or "--"
    end = process.get("end_date") or "--"
    label = state.get("label") or "状态未知"
    if state.get("reason"):
        return f"最近量化过程 {start} 至 {end}：{label}（{state['reason']}）。"
    return f"最近量化过程 {start} 至 {end}：{label}。"


def _ensure_schema() -> None:
    schema.ensure_schema_once(get_engine())


def _date_text(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()
