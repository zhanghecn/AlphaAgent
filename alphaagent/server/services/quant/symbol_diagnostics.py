"""Combined diagnostics for one stock across quant signals and backtests."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from alphaagent.server.services.backtest import engine as backtest_engine
from alphaagent.server.services.backtest.queries import reason_label
from alphaagent.server.services.quant import screening


def symbol_diagnostics_report(
    vt_symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
    backtest_id: int | None = None,
    signal_date: date | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    """Return a single-stock diagnostics payload for stock detail pages.

    The report intentionally composes existing read-side services. It does not
    rescore, rerun, or mutate a backtest.
    """

    symbol = str(vt_symbol or "").strip().upper()
    if not symbol:
        return {"status": "invalid_symbol", "message": "vt_symbol is required"}

    comparison = screening.symbol_strategy_comparison(symbol, start=start, end=end, limit=limit)
    symbol_detail = None
    candidate_trace = None
    if backtest_id is not None:
        symbol_detail = backtest_engine.backtest_symbol_detail(backtest_id, symbol)
        if signal_date is not None:
            candidate_trace = backtest_engine.backtest_candidate_trace(backtest_id, symbol, signal_date)

    summary = _diagnostic_summary(
        comparison=comparison,
        symbol_detail=symbol_detail,
        candidate_trace=candidate_trace,
        backtest_id=backtest_id,
        signal_date=signal_date,
    )
    return {
        "status": _diagnostic_status(comparison, symbol_detail, candidate_trace),
        "vt_symbol": symbol,
        "name": comparison.get("name") or (symbol_detail or {}).get("name"),
        "board": comparison.get("board") or (symbol_detail or {}).get("board"),
        "board_label": comparison.get("board_label") or (symbol_detail or {}).get("board_label"),
        "start_date": comparison.get("start_date"),
        "end_date": comparison.get("end_date"),
        "strategy_comparison": comparison,
        "backtest": {
            "backtest_id": backtest_id,
            "signal_date": signal_date.isoformat() if signal_date else None,
            "symbol_detail": symbol_detail,
            "candidate_trace": candidate_trace,
        }
        if backtest_id is not None
        else None,
        "summary": summary,
    }


def display_candidate_markers(rows: list[dict[str, Any]], *, cluster_days: int = 3) -> list[dict[str, Any]]:
    """Select user-facing candidate markers from dense daily signal rows.

    Quant rows are evidence, not all chart markers. BUY rows are collapsed into
    short clusters so a low-suction buildup followed by launch becomes one key
    point. Raw buy rows that failed rules are kept as rejected-buy markers.
    """

    selected: list[dict[str, Any]] = []
    buy_cluster: list[dict[str, Any]] = []
    buy_cluster_start: date | None = None
    max_cluster_days = max(int(cluster_days), 0)

    def flush_buy_cluster() -> None:
        nonlocal buy_cluster, buy_cluster_start
        if not buy_cluster:
            return
        selected.append(_candidate_cluster_marker(buy_cluster))
        buy_cluster = []
        buy_cluster_start = None

    for row in sorted((dict(item) for item in rows), key=_candidate_marker_sort_key):
        row_date = _candidate_row_date(row)
        if _is_actual_trade_or_sell_marker(row):
            flush_buy_cluster()
            selected.append(_with_display_kind(row, _existing_display_kind(row) or "trade"))
            continue
        if _is_display_buy_row(row):
            if buy_cluster_start is None:
                buy_cluster_start = row_date
            if row_date is not None and buy_cluster_start is not None and (row_date - buy_cluster_start).days > max_cluster_days:
                flush_buy_cluster()
                buy_cluster_start = row_date
            buy_cluster.append(row)
            continue
        if _is_display_rejected_buy_row(row):
            flush_buy_cluster()
            selected.append(_with_display_kind(row, "rejected_buy"))
            continue
    flush_buy_cluster()
    return sorted(selected, key=_candidate_marker_sort_key)


def _candidate_cluster_marker(rows: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(rows, key=lambda row: (_candidate_score(row), _candidate_date_text(row), str(row.get("vt_symbol") or "")))
    dates = [_candidate_date_text(row) for row in rows if _candidate_date_text(row)]
    marker = _with_display_kind(best, "buy")
    marker["cluster_size"] = len(rows)
    marker["cluster_start_date"] = dates[0] if dates else None
    marker["cluster_end_date"] = dates[-1] if dates else None
    marker["cluster_dates"] = dates
    return marker


def _is_display_buy_row(row: dict[str, Any]) -> bool:
    return str(row.get("action") or "").upper() == "BUY" or bool(row.get("executable_entry_signal"))


def _is_display_rejected_buy_row(row: dict[str, Any]) -> bool:
    if str(row.get("action") or "").upper() != "WATCH":
        return False
    if not _candidate_failed_rules(row):
        return False
    raw_entry_signal = row.get("raw_entry_signal")
    return bool(row.get("entry_signal")) or bool(raw_entry_signal) or raw_entry_signal is None


def _is_actual_trade_or_sell_marker(row: dict[str, Any]) -> bool:
    marker_kind = str(row.get("markerKind") or row.get("marker_kind") or "").lower()
    side = str(row.get("side") or "").upper()
    if marker_kind == "trade":
        return True
    if marker_kind == "rejected" and side == "BUY":
        return True
    return side == "SELL" and marker_kind in {"trade", "execution", "sell"}


def _existing_display_kind(row: dict[str, Any]) -> str | None:
    value = row.get("display_kind")
    return str(value) if value not in (None, "") else None


def _with_display_kind(row: dict[str, Any], display_kind: str) -> dict[str, Any]:
    marker = dict(row)
    marker["display_kind"] = display_kind
    return marker


def _candidate_failed_rules(row: dict[str, Any]) -> list[str]:
    failed_rules = row.get("failed_rules")
    if isinstance(failed_rules, list):
        return [str(rule) for rule in failed_rules if str(rule)]
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    evidence_rules = evidence.get("failed_rules") if isinstance(evidence, dict) else None
    if isinstance(evidence_rules, list):
        return [str(rule) for rule in evidence_rules if str(rule)]
    return []


def _candidate_marker_sort_key(row: dict[str, Any]) -> tuple[date, str, float]:
    row_date = _candidate_row_date(row) or date.min
    return (row_date, str(row.get("vt_symbol") or ""), -_candidate_score(row))


def _candidate_row_date(row: dict[str, Any]) -> date | None:
    for key in ("trade_date", "signal_date", "time", "execute_date"):
        value = row.get(key)
        parsed = _parse_candidate_date(value)
        if parsed:
            return parsed
    return None


def _candidate_date_text(row: dict[str, Any]) -> str:
    value = row.get("trade_date") or row.get("signal_date") or row.get("time") or row.get("execute_date")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _parse_candidate_date(value: Any) -> date | None:
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


def _candidate_score(row: dict[str, Any]) -> float:
    value = row.get("total_score", row.get("score"))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _diagnostic_status(
    comparison: dict[str, Any] | None,
    symbol_detail: dict[str, Any] | None,
    candidate_trace: dict[str, Any] | None,
) -> str:
    statuses = {
        str(payload.get("status") or "")
        for payload in (comparison, symbol_detail, candidate_trace)
        if payload
    }
    if "unavailable" in statuses:
        return "unavailable"
    if "not_found" in statuses:
        return "not_found"
    if "invalid_symbol" in statuses:
        return "invalid_symbol"
    if any(status in {"ready", "filled", "rejected", "signal_only", "watch_not_bought"} for status in statuses):
        return "ready"
    return str((comparison or {}).get("status") or "empty")


def _diagnostic_summary(
    *,
    comparison: dict[str, Any] | None,
    symbol_detail: dict[str, Any] | None,
    candidate_trace: dict[str, Any] | None,
    backtest_id: int | None,
    signal_date: date | None,
) -> dict[str, Any]:
    strategies = list((comparison or {}).get("items") or [])
    entry_signal_count = sum(int(item.get("entry_signal_count") or 0) for item in strategies)
    strategy_signal_counts = _strategy_signal_counts(strategies)
    strategies_with_entry_signal = [
        str(item.get("strategy_id") or item.get("strategy", {}).get("id") or "")
        for item in strategies
        if int(item.get("entry_signal_count") or 0) > 0
    ]
    best_signal_date = _best_signal_date(strategies)

    detail = symbol_detail or {}
    trades = list(detail.get("trades") or [])
    orders = list(detail.get("orders") or [])
    positions = list(detail.get("positions") or [])
    buy_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "BUY"]
    sell_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "SELL"]
    rejected_orders = [order for order in orders if str(order.get("status") or "") == "rejected"]

    trace = candidate_trace or {}
    trace_equity = trace.get("equity") if isinstance(trace.get("equity"), dict) else {}
    trace_recommendation = trace.get("recommendation") if isinstance(trace.get("recommendation"), dict) else {}
    trace_trades = list(trace.get("trades") or [])
    trace_orders = list(trace.get("orders") or [])
    trace_rejected = [order for order in trace_orders if str(order.get("status") or "") == "rejected"]

    has_trade = bool(trades or trace_trades)
    has_order = bool(orders or trace_orders)
    has_rejected_order = bool(rejected_orders or trace_rejected)
    has_entry_signal = entry_signal_count > 0
    status = _summary_status(
        has_entry_signal=has_entry_signal,
        has_trade=has_trade,
        has_order=has_order,
        has_rejected_order=has_rejected_order,
        backtest_id=backtest_id,
        signal_date=signal_date,
        trace=trace,
    )
    reason = _summary_reason(
        status=status,
        trace=trace,
        trace_rejected=trace_rejected,
        rejected_orders=rejected_orders,
        has_entry_signal=has_entry_signal,
        signal_date=signal_date,
        best_signal_date=best_signal_date,
    )
    return {
        "status": status,
        "status_label": _summary_status_label(status),
        "has_entry_signal": has_entry_signal,
        "entry_signal_count": entry_signal_count,
        "strategy_signal_counts": strategy_signal_counts,
        "strategies_with_entry_signal": [item for item in strategies_with_entry_signal if item],
        "best_signal_date": best_signal_date,
        "selected_signal_date": signal_date.isoformat() if signal_date else None,
        "has_backtest": backtest_id is not None,
        "backtest_id": backtest_id,
        "has_trade": has_trade,
        "trade_count": len(trades),
        "buy_trade_count": len(buy_trades),
        "sell_trade_count": len(sell_trades),
        "has_order": has_order,
        "order_count": len(orders),
        "rejected_order_count": len(rejected_orders),
        "has_position": bool(positions),
        "position_day_count": len(positions),
        "main_reason": reason["code"],
        "main_reason_label": reason["label"],
        "main_reason_source": reason["source"],
        "main_reason_detail": reason["detail"],
        "candidate_action": trace.get("action"),
        "candidate_rank": _first_present(trace.get("rank"), trace_recommendation.get("rank")),
        "candidate_score": _first_present(trace.get("total_score"), trace_recommendation.get("total_score")),
        "planned_execute_date": trace.get("planned_execute_date"),
        "signal_day_cash": trace_equity.get("cash"),
        "signal_day_market_value": trace_equity.get("market_value"),
        "signal_day_total_equity": trace_equity.get("total_equity"),
        "signal_day_position_count": trace_equity.get("position_count"),
        "not_traded_context": _not_traded_context(
            status=status,
            reason=reason["code"],
            best_signal_date=best_signal_date,
            signal_date=signal_date,
            trace=trace,
            trace_equity=trace_equity,
        ),
        "diagnostic_checks": _diagnostic_checks(
            has_entry_signal=has_entry_signal,
            signal_date=signal_date,
            trace=trace,
            has_order=has_order,
            has_trade=has_trade,
            has_rejected_order=has_rejected_order,
            reason=reason["code"],
        ),
        "next_action": _summary_next_action(status, best_signal_date, signal_date, reason["code"]),
    }


def _summary_status(
    *,
    has_entry_signal: bool,
    has_trade: bool,
    has_order: bool,
    has_rejected_order: bool,
    backtest_id: int | None,
    signal_date: date | None,
    trace: dict[str, Any],
) -> str:
    if has_trade:
        return "traded"
    if has_rejected_order:
        return "rejected"
    if trace and trace.get("action") == "WATCH":
        return "watch_not_bought"
    if trace and trace.get("signals"):
        return "signal_only"
    if backtest_id is None:
        return "needs_backtest"
    if has_order:
        return "ordered_not_filled"
    if has_entry_signal and signal_date is None:
        return "needs_signal_date"
    if has_entry_signal:
        return "entry_signal_not_traded"
    return "no_entry_signal"


def _summary_status_label(status: str) -> str:
    labels = {
        "traded": "组合已成交",
        "rejected": "组合有拒单",
        "watch_not_bought": "只是观察",
        "signal_only": "有理论信号未成交",
        "needs_backtest": "待选择组合回测",
        "needs_signal_date": "待选择信号日",
        "ordered_not_filled": "有订单未成交",
        "entry_signal_not_traded": "有BUY但组合未买",
        "no_entry_signal": "无BUY信号",
    }
    return labels.get(status, status)


def _summary_reason(
    *,
    status: str,
    trace: dict[str, Any],
    trace_rejected: list[dict[str, Any]],
    rejected_orders: list[dict[str, Any]],
    has_entry_signal: bool,
    signal_date: date | None,
    best_signal_date: str | None,
) -> dict[str, Any]:
    """Choose the clearest human-facing reason for one-stock diagnostics."""

    linked_reason = trace.get("linked_order_reason")
    if linked_reason:
        return _reason_payload(linked_reason, trace.get("linked_order_reason_label"), "linked_order", trace.get("summary"))

    trace_reason = _first_value(trace_rejected, "reason")
    if trace_reason:
        return _reason_payload(trace_reason, _first_value(trace_rejected, "reason_label"), "candidate_trace_order", None)

    rejected_reason = _first_value(rejected_orders, "reason")
    if rejected_reason:
        return _reason_payload(rejected_reason, _first_value(rejected_orders, "reason_label"), "symbol_orders", None)

    trace_status = str(trace.get("status") or "")
    trace_action = str(trace.get("action") or "").upper()
    trace_plan_status = str(trace.get("plan_status") or "")
    if trace_action == "WATCH" or status == "watch_not_bought":
        return _reason_payload("watch_not_bought", "只是观察，默认不买", "candidate_action", trace.get("summary"))
    if trace_status == "candidate_not_planned":
        return _reason_payload("candidate_not_planned", "候选未进入组合计划", "candidate_trace", trace.get("summary"))
    if trace_plan_status:
        return _reason_payload(trace_plan_status, trace.get("plan_status_label"), "signal_plan", trace.get("summary"))
    if trace_status:
        return _reason_payload(trace_status, None, "candidate_trace", trace.get("summary"))
    if has_entry_signal and signal_date is None:
        return _reason_payload("needs_signal_date", "需要选择 BUY 信号日", "strategy_history", best_signal_date)
    if has_entry_signal:
        return _reason_payload("entry_signal_not_traded", "有 BUY 但组合未买", "strategy_history", None)
    return _reason_payload("no_entry_signal", "无 BUY 信号", "strategy_history", None)


def _reason_payload(code: Any, label: Any = None, source: str = "", detail: Any = None) -> dict[str, Any]:
    reason_code = str(code or "").strip()
    return {
        "code": reason_code or None,
        "label": str(label or reason_label(reason_code) or reason_code or "").strip() or None,
        "source": source,
        "detail": detail,
    }


def _summary_next_action(status: str, best_signal_date: str | None, signal_date: date | None, reason: str | None = None) -> str:
    reason_code = str(reason or "")
    if reason_code in {"position_slot_unavailable", "insufficient_cash"}:
        return "查看执行日组合资金、持仓数量和同日其它买入，判断是否被仓位或现金挤掉。"
    if reason_code in {"limit_up_tail_unfilled", "limit_up_or_no_bar"}:
        return "查看执行日日线和 14:30 快照，确认是否涨停或缺执行日行情导致无法买入。"
    if reason_code == "tail_entry_not_triggered":
        return "查看执行日 14:30 价格、MA5 和尾盘偏离，确认是策略条件未触发而非缺数据。"
    if reason_code in {"missing_1430_snapshot", "strict_1430_required"}:
        return "先用数据同步按回测 ID 补齐执行日 14:30 的 1m 快照，再重跑严格 14:30 回测。"
    if reason_code == "candidate_not_planned":
        return "查看该日候选排名、最大持仓、candidate_limit 和组合已有持仓，确认为什么没有进入买入计划。"
    if reason_code == "watch_not_bought":
        return "默认组合回测只买 BUY；WATCH 只有开启宽松研究买入才会参与。"
    if status == "needs_backtest":
        return "输入组合回测 ID 后，可核查该股在组合中是否下单、成交或拒单。"
    if status == "needs_signal_date":
        return f"选择 BUY 信号日继续追踪；当前最佳候选日为 {best_signal_date or '未知'}。"
    if status in {"entry_signal_not_traded", "signal_only"} and signal_date is None:
        return "选择一个 BUY 信号日，查看候选排名、计划执行日、订单和资金状态。"
    if status in {"rejected", "ordered_not_filled"}:
        return "查看订单原因和执行日资金/持仓状态，区分现金、仓位、涨跌停和尾盘未触发。"
    if status == "no_entry_signal":
        return "查看策略失败规则，确认是分数、位置、风险、流动性还是数据可见性导致。"
    return "查看成交、持仓路径和卖出原因。"


def _best_signal_date(strategies: list[dict[str, Any]]) -> str | None:
    for item in strategies:
        for row in item.get("entry_signals") or []:
            trade_date = row.get("trade_date")
            if trade_date:
                return str(trade_date)
    for item in strategies:
        row = item.get("best_entry_fit") or {}
        trade_date = row.get("trade_date")
        if trade_date:
            return str(trade_date)
    return None


def _strategy_signal_counts(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in strategies:
        strategy_id = str(item.get("strategy_id") or item.get("strategy", {}).get("id") or "").strip()
        if not strategy_id:
            continue
        best_entry_fit = item.get("best_entry_fit") if isinstance(item.get("best_entry_fit"), dict) else {}
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": item.get("strategy_name") or item.get("name") or item.get("strategy", {}).get("name"),
                "entry_signal_count": int(item.get("entry_signal_count") or 0),
                "watch_count": int(item.get("watch_count") or 0),
                "best_signal_date": _best_signal_date([item]),
                "best_entry_score": best_entry_fit.get("total_score"),
            }
        )
    return rows


def _not_traded_context(
    *,
    status: str,
    reason: Any,
    best_signal_date: str | None,
    signal_date: date | None,
    trace: dict[str, Any],
    trace_equity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "needs_signal_date": status == "needs_signal_date",
        "best_signal_date": best_signal_date,
        "selected_signal_date": signal_date.isoformat() if signal_date else None,
        "candidate_action": trace.get("action"),
        "candidate_rank": trace.get("rank"),
        "candidate_score": trace.get("total_score"),
        "plan_status": trace.get("plan_status"),
        "planned_execute_date": trace.get("planned_execute_date"),
        "cash": trace_equity.get("cash"),
        "market_value": trace_equity.get("market_value"),
        "total_equity": trace_equity.get("total_equity"),
        "position_count": trace_equity.get("position_count"),
    }


def _diagnostic_checks(
    *,
    has_entry_signal: bool,
    signal_date: date | None,
    trace: dict[str, Any],
    has_order: bool,
    has_trade: bool,
    has_rejected_order: bool,
    reason: Any,
) -> list[dict[str, str]]:
    trace_action = str(trace.get("action") or "").upper()
    return [
        {"label": "单股BUY信号", "status": "pass" if has_entry_signal else "fail"},
        {"label": "已选择信号日", "status": "pass" if signal_date else "warning"},
        {"label": "进入当日候选", "status": "pass" if trace_action in {"BUY", "WATCH"} else "warning"},
        {"label": "进入组合订单", "status": "pass" if has_order else "warning"},
        {"label": "真实买入成交", "status": "pass" if has_trade else "fail"},
        {"label": "拒单原因", "status": "warning" if has_rejected_order or reason else "pass"},
    ]


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None
