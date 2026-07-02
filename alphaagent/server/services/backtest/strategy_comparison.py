"""Portfolio-level strategy comparison for the same backtest parameters."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any, Callable

from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant import market_context
from alphaagent.server.services.quant.strategy_registry import list_internal_strategies


RunBacktest = Callable[[BacktestParams], dict[str, Any]]
LoadMarketContexts = Callable[[list[date]], dict[date, dict[str, Any]]]


def compare_strategies(
    base_params: BacktestParams,
    *,
    strategies: list[str] | None = None,
    run_backtest: RunBacktest,
    load_market_contexts: LoadMarketContexts | None = None,
) -> dict[str, Any]:
    """Run multiple strategies with identical non-persistent parameters."""

    strategy_meta = {str(item.get("id")): item for item in list_internal_strategies()}
    selected = _selected_strategies(strategies, strategy_meta)
    if not selected:
        return {"status": "empty", "rows": [], "message": "No strategies selected."}

    rows = []
    context_cache: dict[date, dict[str, Any]] = {}
    for strategy_id in selected:
        params = replace(
            base_params,
            strategy=strategy_id,
            execution_model=base_params.execution_model,
            minute_interval="1m",
            tail_entry_start="14:30",
            tail_entry_end="14:30",
            persist=False,
        )
        result = run_backtest(params)
        trades = list(result.get("trades") or [])
        signal_events = list(result.get("signal_events") or [])
        if load_market_contexts is not None:
            context_dates = _unique_dates([*_closed_trade_entry_dates(trades), *_candidate_signal_dates(signal_events)])
            missing_dates = [day for day in context_dates if day not in context_cache]
            if missing_dates:
                context_cache.update(load_market_contexts(missing_dates))
        rows.append(
            _strategy_row(
                strategy_id,
                strategy_meta.get(strategy_id) or {},
                result,
                context_cache,
                candidate_limit=base_params.candidate_limit,
            )
        )

    return {
        "status": "ready" if rows else "empty",
        "params": _params_payload(base_params),
        "rows": rows,
        "summary": _summary(rows),
        "note": "策略对比使用同一股票池、同一区间、同一执行模型非持久化重跑；不创建新的回测记录。",
    }


def _selected_strategies(strategies: list[str] | None, meta: dict[str, dict[str, Any]]) -> list[str]:
    if strategies:
        result = []
        for item in strategies:
            strategy_id = str(item or "").strip()
            if strategy_id and strategy_id in meta and strategy_id not in result:
                result.append(strategy_id)
        return result
    return list(meta)


def _strategy_row(
    strategy_id: str,
    meta: dict[str, Any],
    result: dict[str, Any],
    market_context_by_date: dict[date, dict[str, Any]] | None = None,
    *,
    candidate_limit: int = 20,
) -> dict[str, Any]:
    if result.get("status") != "ready":
        return {
            "strategy_id": strategy_id,
            "strategy_version": meta.get("version"),
            "strategy_name": meta.get("name") or strategy_id,
            "status": result.get("status") or "error",
            "message": result.get("message"),
        }

    metrics = dict(result.get("metrics") or {})
    trades = list(result.get("trades") or [])
    orders = list(result.get("orders") or [])
    signal_events = list(result.get("signal_events") or [])
    buy_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "BUY"]
    sell_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "SELL"]
    rejected_orders = [order for order in orders if str(order.get("status") or "") == "rejected"]
    buy_signals = [row for row in signal_events if str(row.get("side") or "").upper() == "BUY"]
    watch_count = max(len(signal_events) - len(buy_signals), 0)
    minute_1430_count = int(metrics.get("minute_1430_count") or 0)
    daily_close_proxy_count = int(metrics.get("daily_close_proxy_count") or 0)
    strict_rejected = [
        order
        for order in rejected_orders
        if _order_execution_model(order) == "strict_1430"
    ]
    minute_gap_rejected = [
        order
        for order in strict_rejected
        if str(order.get("reason") or "") == "missing_1430_snapshot"
        or str(_order_execution(order).get("reason") or "") == "missing_1430_snapshot"
    ]
    tail_entry_rejected = [
        order
        for order in rejected_orders
        if str(order.get("reason") or "") == "tail_entry_not_triggered"
    ]
    quality = _quality_payload(
        buy_count=len(buy_trades),
        daily_close_proxy_count=daily_close_proxy_count,
        minute_gap_rejected_count=len(minute_gap_rejected),
        strict_1430_rejected_count=len(strict_rejected),
        tail_entry_rejected_count=len(tail_entry_rejected),
    )
    phase_summary = _strategy_phase_summary(trades, market_context_by_date)
    candidate_phase_summary = _strategy_candidate_phase_summary(
        signal_events,
        market_context_by_date,
        top_limit=candidate_limit,
    )
    return {
        "strategy_id": strategy_id,
        "strategy_version": result.get("strategy_version") or meta.get("version"),
        "strategy_name": meta.get("name") or strategy_id,
        "status": "ready",
        **quality,
        "final_equity": metrics.get("final_equity"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "trade_count": len(trades),
        "total_trade_rows": len(trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "buy_signal_count": len(buy_signals),
        "watch_count": watch_count,
        "rejected_order_count": len(rejected_orders),
        "strict_1430_rejected_count": len(strict_rejected),
        "tail_entry_rejected_count": len(tail_entry_rejected),
        "minute_gap_rejected_count": len(minute_gap_rejected),
        "minute_1430_count": minute_1430_count,
        "daily_close_proxy_count": daily_close_proxy_count,
        "minute_1430_ratio": _ratio_pct(minute_1430_count, len(buy_trades)),
        "daily_close_proxy_ratio": _ratio_pct(daily_close_proxy_count, len(buy_trades)),
        "phase_summary": phase_summary,
        "phase_rank_hint": _phase_rank_hint(phase_summary),
        "candidate_phase_summary": candidate_phase_summary,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [row for row in rows if row.get("status") == "ready"]
    best = max(ready, key=lambda row: _numeric_or_floor(row.get("total_return_pct")), default=None)
    complete_strict = [
        row
        for row in ready
        if int(row.get("daily_close_proxy_count") or 0) == 0
        and int(row.get("minute_gap_rejected_count") or 0) == 0
    ]
    verifiable = [row for row in ready if row.get("quality_status") in {"complete_strict", "strict_condition_rejections"}]
    best_verifiable = max(verifiable, key=lambda row: _numeric_or_floor(row.get("total_return_pct")), default=None)
    return {
        "status": "ready" if ready else "empty",
        "strategy_count": len(rows),
        "ready_count": len(ready),
        "best_strategy_id": best.get("strategy_id") if best else None,
        "best_total_return_pct": best.get("total_return_pct") if best else None,
        "best_verifiable_strategy_id": best_verifiable.get("strategy_id") if best_verifiable else None,
        "best_verifiable_total_return_pct": best_verifiable.get("total_return_pct") if best_verifiable else None,
        "complete_strict_count": len(complete_strict),
        "message": "策略收益只代表当前样本和执行口径；仍需 walk-forward、参数敏感性和基准超额验证。",
    }


def _params_payload(params: BacktestParams) -> dict[str, Any]:
    payload = dict(params.__dict__)
    for key, value in list(payload.items()):
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
        elif isinstance(value, tuple):
            payload[key] = list(value)
    payload["persist"] = False
    return payload


def _strategy_phase_summary(
    trades: list[dict[str, Any]],
    market_context_by_date: dict[date, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    closed = _closed_trade_rows(trades)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in closed:
        phase = market_context.classify_trading_market_phase(_entry_market_payload(row, market_context_by_date))
        phase_id = str(phase.get("phase") or "unknown")
        item = dict(row)
        item["market_phase"] = phase_id
        item["market_phase_label"] = phase.get("label")
        buckets.setdefault(phase_id, []).append(item)

    by_phase = [_phase_bucket_summary(phase_id, rows) for phase_id, rows in buckets.items()]
    by_phase.sort(key=lambda item: (_phase_sort_rank(str(item.get("phase") or "")), -int(item.get("trade_count") or 0)))
    best_phase = max(
        [row for row in by_phase if int(row.get("trade_count") or 0) > 0],
        key=lambda row: (_numeric_or_floor(row.get("avg_return_pct")), _numeric_or_floor(row.get("win_rate_pct"))),
        default=None,
    )
    return {
        "status": "ready" if closed else "empty",
        "trade_count": len(closed),
        "by_phase": by_phase,
        "best_phase": best_phase.get("phase") if best_phase else None,
        "best_phase_label": best_phase.get("label") if best_phase else None,
        "not_used_for_signal_score": True,
        "method": "按真实闭合成交的买入日可见行情上下文聚合；不改变买卖或排序。",
    }


def _closed_trade_entry_dates(trades: list[dict[str, Any]]) -> list[date]:
    result = []
    for row in _closed_trade_rows(trades):
        entry_date = _as_date(row.get("entry_date"))
        if entry_date and entry_date not in result:
            result.append(entry_date)
    return result


def _candidate_signal_dates(signal_events: list[dict[str, Any]]) -> list[date]:
    result = []
    for event in signal_events:
        if str(event.get("side") or "").upper() != "BUY":
            continue
        signal_date = _as_date(event.get("signal_date") or event.get("trade_date"))
        if signal_date and signal_date not in result:
            result.append(signal_date)
    return result


def _unique_dates(values: list[date]) -> list[date]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _closed_trade_rows(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    ordered = sorted(enumerate(trades), key=lambda item: (_date_sort_key(item[1].get("trade_date")), item[0]))
    for _, trade in ordered:
        side = str(trade.get("side") or "").upper()
        vt_symbol = str(trade.get("vt_symbol") or "")
        if side == "BUY":
            open_by_symbol.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_by_symbol.get(vt_symbol, []).pop(0) if open_by_symbol.get(vt_symbol) else None
        if not entry:
            continue
        entry_price = _safe_float(entry.get("price"))
        exit_price = _safe_float(trade.get("price"))
        amount = _safe_float(entry.get("amount"))
        pnl = _safe_float(trade.get("pnl"))
        return_pct = None
        if pnl is not None and amount:
            return_pct = pnl / amount * 100
        elif entry_price and exit_price:
            return_pct = (exit_price / entry_price - 1) * 100
        rows.append(
            {
                "vt_symbol": vt_symbol,
                "entry_date": _date_text(entry.get("trade_date")),
                "exit_date": _date_text(trade.get("trade_date")),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "amount": amount,
                "pnl": pnl,
                "return_pct": return_pct,
                "exit_reason": trade.get("reason"),
                "raw": entry.get("raw") if isinstance(entry.get("raw"), dict) else {},
            }
        )
    return rows


def _strategy_candidate_phase_summary(
    signal_events: list[dict[str, Any]],
    market_context_by_date: dict[date, dict[str, Any]] | None = None,
    *,
    top_limit: int = 20,
) -> dict[str, Any]:
    rows = _candidate_signal_outcome_rows(signal_events, market_context_by_date, top_limit=top_limit)
    buy_rows = rows["buy_rows"]
    closed_rows = rows["closed_rows"]
    by_phase = []
    phase_ids = {str(row.get("market_phase") or "unknown") for row in buy_rows}
    phase_ids.update(str(row.get("market_phase") or "unknown") for row in closed_rows)
    for phase_id in phase_ids:
        phase_buy_rows = [row for row in buy_rows if str(row.get("market_phase") or "unknown") == phase_id]
        phase_closed_rows = [row for row in closed_rows if str(row.get("market_phase") or "unknown") == phase_id]
        by_phase.append(_candidate_phase_bucket_summary(phase_id, phase_buy_rows, phase_closed_rows))
    by_phase.sort(key=lambda item: (_phase_sort_rank(str(item.get("phase") or "")), -int(item.get("signal_count") or 0)))
    best_phase = max(
        [row for row in by_phase if int(row.get("evaluated_count") or 0) > 0],
        key=lambda row: (_numeric_or_floor(row.get("avg_return_pct")), _numeric_or_floor(row.get("win_rate_pct"))),
        default=None,
    )
    return {
        "status": "ready" if buy_rows else "empty",
        "top_limit": int(top_limit or 0),
        "signal_count": len(buy_rows),
        "evaluated_count": len([row for row in closed_rows if _safe_float(row.get("return_pct")) is not None]),
        "open_count": rows["open_count"],
        "not_triggered_count": rows["not_triggered_count"],
        "by_phase": by_phase,
        "best_phase": best_phase.get("phase") if best_phase else None,
        "best_phase_label": best_phase.get("label") if best_phase else None,
        "not_used_for_signal_score": True,
        "method": "按理论买入候选 Top-N 的信号日行情聚合，收益为后验审计；不改变默认买卖或排序。",
    }


def _candidate_signal_outcome_rows(
    signal_events: list[dict[str, Any]],
    market_context_by_date: dict[date, dict[str, Any]] | None,
    *,
    top_limit: int,
) -> dict[str, Any]:
    open_by_symbol: dict[str, list[dict[str, Any]]] = {}
    buy_rows: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []
    not_triggered_count = 0
    ordered = sorted(enumerate(signal_events), key=lambda item: (_date_sort_key(item[1].get("trade_date")), item[0]))
    for _, event in ordered:
        side = str(event.get("side") or "").upper()
        vt_symbol = str(event.get("vt_symbol") or "")
        if side == "BUY":
            if not _is_top_candidate_event(event, top_limit):
                continue
            row = _candidate_buy_row(event, market_context_by_date)
            buy_rows.append(row)
            if row.get("entry_price") is None or not row.get("filled"):
                not_triggered_count += 1
                continue
            open_by_symbol.setdefault(vt_symbol, []).append(row)
            continue
        if side != "SELL":
            continue
        entry = open_by_symbol.get(vt_symbol, []).pop(0) if open_by_symbol.get(vt_symbol) else None
        if not entry:
            continue
        exit_price = _safe_float(event.get("price"))
        return_pct = None
        entry_price = _safe_float(entry.get("entry_price"))
        if entry_price and exit_price:
            return_pct = (exit_price / entry_price - 1) * 100
        closed_rows.append(
            {
                **entry,
                "exit_date": _date_text(event.get("trade_date") or event.get("execute_date")),
                "exit_price": exit_price,
                "return_pct": return_pct,
                "exit_reason": event.get("reason") or _event_raw(event).get("reason"),
            }
        )
    return {
        "buy_rows": buy_rows,
        "closed_rows": closed_rows,
        "open_count": sum(len(items) for items in open_by_symbol.values()),
        "not_triggered_count": not_triggered_count,
    }


def _candidate_buy_row(
    event: dict[str, Any],
    market_context_by_date: dict[date, dict[str, Any]] | None,
) -> dict[str, Any]:
    raw = _event_raw(event)
    evidence = _event_evidence(event)
    signal_date = _as_date(event.get("signal_date") or event.get("trade_date"))
    phase = market_context.classify_trading_market_phase(_candidate_market_payload(event, market_context_by_date))
    execution = raw.get("candidate_execution") if isinstance(raw.get("candidate_execution"), dict) else {}
    return {
        "vt_symbol": str(event.get("vt_symbol") or ""),
        "signal_date": signal_date.isoformat() if signal_date else None,
        "entry_date": _date_text(event.get("execute_date") or event.get("trade_date")),
        "entry_price": _safe_float(event.get("price")),
        "score": _safe_float(event.get("score")),
        "rank": _safe_int(execution.get("execution_candidate_rank") or execution.get("raw_signal_rank")),
        "raw_signal_rank": _safe_int(execution.get("raw_signal_rank")),
        "execution_candidate_rank": _safe_int(execution.get("execution_candidate_rank")),
        "entry_setup": evidence.get("entry_setup") or evidence.get("setup_type") or evidence.get("entry_family"),
        "entry_family": evidence.get("entry_family") or evidence.get("entry_setup") or evidence.get("setup_type"),
        "market_phase": str(phase.get("phase") or "unknown"),
        "market_phase_label": phase.get("label"),
        "filled": _event_filled(event),
    }


def _candidate_market_payload(
    event: dict[str, Any],
    market_context_by_date: dict[date, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = _event_raw(event)
    evidence = _event_evidence(event)
    signal_date = _as_date(event.get("signal_date") or event.get("trade_date"))
    payload = dict((market_context_by_date or {}).get(signal_date, {}) if signal_date else {})
    for source in (raw, evidence):
        context = source.get("market_context") if isinstance(source.get("market_context"), dict) else {}
        payload.update(context)
        for key in (
            "regime",
            "dynamic_market_regime",
            "market_warning_level",
            "recovery_state",
            "fund_flow_state",
            "market_score",
            "breadth_score",
            "market_breadth_score",
            "theme_strength",
            "index_return_5d",
            "index_return_20d",
            "growth_score",
            "value_score",
            "small_cap_score",
        ):
            if key in source and key not in payload:
                payload[key] = source[key]
    return payload


def _candidate_phase_bucket_summary(
    phase_id: str,
    buy_rows: list[dict[str, Any]],
    closed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    returns = [value for row in closed_rows if (value := _safe_float(row.get("return_pct"))) is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    return {
        "phase": phase_id,
        "label": _phase_label(phase_id),
        "signal_count": len(buy_rows),
        "evaluated_count": len(returns),
        "open_count": sum(1 for row in buy_rows if row.get("filled"))
        - len([row for row in closed_rows if row.get("filled")]),
        "not_triggered_count": sum(1 for row in buy_rows if not row.get("filled") or row.get("entry_price") is None),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(returns) * 100 if returns else None,
        "avg_return_pct": sum(returns) / len(returns) if returns else None,
        "total_return_pct": sum(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "best_return_pct": max(returns) if returns else None,
        "support_stop_count": sum(1 for row in closed_rows if str(row.get("exit_reason") or "") == "support_stop"),
    }


def _entry_market_payload(
    row: dict[str, Any],
    market_context_by_date: dict[date, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    entry_date = _as_date(row.get("entry_date"))
    payload = dict((market_context_by_date or {}).get(entry_date, {}) if entry_date else {})
    context = raw.get("market_context") if isinstance(raw.get("market_context"), dict) else {}
    payload.update(context)
    for key in (
        "regime",
        "dynamic_market_regime",
        "market_warning_level",
        "recovery_state",
        "fund_flow_state",
        "market_score",
        "breadth_score",
        "market_breadth_score",
        "theme_strength",
        "index_return_5d",
        "index_return_20d",
        "growth_score",
        "value_score",
        "small_cap_score",
    ):
        if key in raw and key not in payload:
            payload[key] = raw[key]
    return payload


def _is_top_candidate_event(event: dict[str, Any], top_limit: int) -> bool:
    limit = max(int(top_limit or 0), 0)
    if limit <= 0:
        return False
    execution = _event_raw(event).get("candidate_execution")
    if not isinstance(execution, dict):
        return True
    execution_rank = _safe_int(execution.get("execution_candidate_rank"))
    if execution_rank is not None:
        return 1 <= execution_rank <= limit
    if execution.get("execution_candidate_selected") is False:
        return False
    raw_rank = _safe_int(execution.get("raw_signal_rank"))
    if raw_rank is not None:
        return 1 <= raw_rank <= limit
    return True


def _event_filled(event: dict[str, Any]) -> bool:
    raw = _event_raw(event)
    status = str(raw.get("status") or "").strip().lower()
    if status:
        return status == "filled"
    return _safe_float(event.get("price")) is not None


def _event_raw(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
    return raw


def _event_evidence(event: dict[str, Any]) -> dict[str, Any]:
    raw = _event_raw(event)
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    return evidence if evidence else raw


def _phase_bucket_summary(phase_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _safe_float(row.get("return_pct"))) is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    return {
        "phase": phase_id,
        "label": _phase_label(phase_id),
        "trade_count": len(rows),
        "evaluated_count": len(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(returns) * 100 if returns else None,
        "avg_return_pct": sum(returns) / len(returns) if returns else None,
        "total_return_pct": sum(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "best_return_pct": max(returns) if returns else None,
        "support_stop_count": sum(1 for row in rows if str(row.get("exit_reason") or "") == "support_stop"),
    }


def _phase_rank_hint(summary: dict[str, Any]) -> dict[str, Any] | None:
    by_phase = [row for row in summary.get("by_phase") or [] if int(row.get("trade_count") or 0) > 0]
    if not by_phase:
        return None
    best = max(by_phase, key=lambda row: (_numeric_or_floor(row.get("avg_return_pct")), _numeric_or_floor(row.get("win_rate_pct"))))
    weak = [
        row
        for row in by_phase
        if int(row.get("evaluated_count") or 0) >= 3
        and _safe_float(row.get("avg_return_pct")) is not None
        and float(row.get("avg_return_pct") or 0) <= 0
    ]
    return {
        "best_phase": best.get("phase"),
        "best_phase_label": best.get("label"),
        "best_avg_return_pct": best.get("avg_return_pct"),
        "weak_phase_count": len(weak),
        "note": "只读提示：用于比较策略适配行情，不参与默认交易。",
    }


def _phase_label(phase_id: str) -> str:
    return {
        "uptrend": "主升",
        "rotation": "震荡",
        "retreat": "退潮",
        "warming": "回暖",
        "unknown": "未知",
    }.get(phase_id, phase_id or "未知")


def _phase_sort_rank(phase_id: str) -> int:
    order = {"uptrend": 0, "rotation": 1, "retreat": 2, "warming": 3, "unknown": 4}
    return order.get(phase_id, 9)


def _date_sort_key(value: Any) -> date:
    parsed = _as_date(value)
    return parsed or date.min


def _date_text(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _order_execution(order: dict[str, Any]) -> dict[str, Any]:
    raw = order.get("raw") if isinstance(order.get("raw"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else raw
    return execution if isinstance(execution, dict) else {}


def _order_execution_model(order: dict[str, Any]) -> str:
    return str(_order_execution(order).get("execution_model") or "")


def _ratio_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 4)


def _quality_payload(
    *,
    buy_count: int,
    daily_close_proxy_count: int,
    minute_gap_rejected_count: int,
    strict_1430_rejected_count: int,
    tail_entry_rejected_count: int,
) -> dict[str, str | None]:
    if buy_count <= 0:
        if minute_gap_rejected_count > 0:
            return {
                "quality_status": "missing_snapshots",
                "quality_label": "缺14:30快照",
                "quality_warning": f"有 {minute_gap_rejected_count} 笔买入因缺 14:30 快照拒单，当前 0% 收益不能验证策略表现。",
            }
        return {
            "quality_status": "no_fills",
            "quality_label": "未成交",
            "quality_warning": "当前策略没有真实买入成交，0% 或空收益不能验证收益表现。",
        }
    if daily_close_proxy_count > 0:
        return {
            "quality_status": "uses_daily_close_proxy",
            "quality_label": "含收盘代理",
            "quality_warning": f"有 {daily_close_proxy_count} 笔成交使用收盘代理，不能按纯真实 14:30 回测解读。",
        }
    if minute_gap_rejected_count > 0:
        return {
            "quality_status": "missing_snapshots",
            "quality_label": "缺14:30快照",
            "quality_warning": f"有 {minute_gap_rejected_count} 笔买入因缺 14:30 快照拒单，需要补齐后重跑。",
        }
    if strict_1430_rejected_count > 0:
        return {
            "quality_status": "strict_condition_rejections",
            "quality_label": "严格条件拒单",
            "quality_warning": f"有 {strict_1430_rejected_count} 笔严格 14:30 拒单，其中 {tail_entry_rejected_count} 笔是尾盘条件未触发。",
        }
    return {
        "quality_status": "complete_strict",
        "quality_label": "完整严格",
        "quality_warning": None,
    }


def _numeric_or_floor(value: Any) -> float:
    if value in (None, ""):
        return -10**9
    try:
        return float(value)
    except (TypeError, ValueError):
        return -10**9


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
