"""Signal-plan helpers for portfolio backtest audit flows."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Callable


def link_signal_events_to_orders(
    events: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    *,
    as_date: Callable[[Any], date | None],
) -> list[dict[str, Any]]:
    orders_by_key: dict[tuple[str, date | None, str], list[dict[str, Any]]] = defaultdict(list)
    for order in orders:
        key = (
            str(order.get("vt_symbol") or ""),
            as_date(order.get("trade_date")),
            str(order.get("side") or "").upper(),
        )
        orders_by_key[key].append(order)

    linked: list[dict[str, Any]] = []
    for event in events:
        item = dict(event)
        key = (
            str(item.get("vt_symbol") or ""),
            as_date(item.get("execute_date") or item.get("trade_date")),
            str(item.get("side") or "").upper(),
        )
        candidates = orders_by_key.get(key) or []
        order = candidates[0] if candidates else None
        raw = dict(item.get("raw") or {})
        if order:
            item["linked_order_id"] = order.get("id")
            item["linked_order_status"] = order.get("status")
            item["linked_order_reason"] = order.get("reason")
            item["plan_status"] = signal_plan_status(raw, order)
            item["plan_status_label"] = signal_plan_status_label(item["plan_status"])
            raw["linked_order"] = {
                "id": order.get("id"),
                "status": order.get("status"),
                "reason": order.get("reason"),
                "price": order.get("price"),
                "volume": order.get("volume"),
            }
        else:
            item["linked_order_id"] = None
            item["linked_order_status"] = None
            item["linked_order_reason"] = None
            item["plan_status"] = signal_plan_status(raw, None)
            item["plan_status_label"] = signal_plan_status_label(item["plan_status"])
            raw.setdefault("linked_order", None)
        raw.setdefault("event_role", "theoretical_signal")
        raw.setdefault("plan_status", item["plan_status"])
        item["raw"] = raw
        linked.append(item)
    return linked


def candidate_trace_plan_summary(reason: str) -> str:
    if reason == "missing_1430_snapshot":
        return "理论买入信号存在，但执行日缺少 14:30 的 1 分钟快照，因此没有下组合订单。"
    if reason == "tail_entry_not_triggered":
        return "理论买入信号存在，但执行日 14:30 价格没有满足尾盘入场条件，因此没有下组合订单。"
    if reason == "tail_exit_not_triggered":
        return "理论卖出信号存在，但执行日 14:30 缺快照或没有满足尾盘卖出条件，因此没有下组合订单。"
    if reason:
        return f"理论信号存在，但执行计划未触发：{reason}。"
    return "理论信号存在，但执行计划未触发，因此没有下组合订单。"


def candidate_trace_diagnostics(
    recommendation: dict[str, Any] | None,
    signal_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    action = str((recommendation or {}).get("action") or "").upper()
    failed_rules = []
    reason = (recommendation or {}).get("reason")
    if isinstance(reason, dict) and isinstance(reason.get("failed_rules"), list):
        failed_rules = [str(item) for item in reason["failed_rules"] if item]
    diagnostics.append(
        {
            "id": "candidate_action",
            "status": "pass" if action == "BUY" else "info" if action == "WATCH" else "missing",
            "message": f"候选动作为 {action or '未入选'}。",
            "failed_rules": failed_rules,
        }
    )
    recommendation_strategy = str((recommendation or {}).get("strategy_id") or "")
    recommendation_version = str((recommendation or {}).get("strategy_version") or "")
    if recommendation_strategy:
        diagnostics.append(
            {
                "id": "candidate_strategy",
                "status": "info",
                "message": f"候选策略为 {recommendation_strategy} / {recommendation_version or '--'}。",
            }
        )
    diagnostics.append(
        {
            "id": "signal_plan",
            "status": "pass" if signal_rows else "missing",
            "message": "已写入理论信号计划。" if signal_rows else "没有找到理论信号计划。",
        }
    )
    filled_orders = [row for row in order_rows if row.get("status") == "filled"]
    rejected_orders = [row for row in order_rows if row.get("status") == "rejected"]
    untriggered_signals = [
        row
        for row in signal_rows
        if str(row.get("plan_status") or "") in {"not_triggered", "rejected"} and not row.get("linked_order_id")
    ]
    first_untriggered = untriggered_signals[0] if untriggered_signals else None
    first_untriggered_raw = (
        first_untriggered.get("raw")
        if isinstance(first_untriggered, dict) and isinstance(first_untriggered.get("raw"), dict)
        else {}
    )
    first_untriggered_reason = (
        str(first_untriggered.get("linked_order_reason") or first_untriggered_raw.get("reason") or "")
        if first_untriggered
        else ""
    )
    diagnostics.append(
        {
            "id": "real_order",
            "status": "pass" if filled_orders else "warning" if rejected_orders else "info" if first_untriggered else "missing",
            "message": (
                "组合订单已成交。"
                if filled_orders
                else f"组合订单被拒绝：{rejected_orders[0].get('reason') or 'unknown'}。"
                if rejected_orders
                else candidate_trace_plan_summary(first_untriggered_reason)
                if first_untriggered
                else "没有找到组合订单。"
            ),
        }
    )
    diagnostics.append(
        {
            "id": "real_trade",
            "status": "pass" if trade_rows else "missing",
            "message": "已形成组合成交。" if trade_rows else "没有组合成交。",
        }
    )
    return diagnostics


def signal_plan_status(raw: dict[str, Any], order: dict[str, Any] | None) -> str:
    if order:
        status = str(order.get("status") or "").strip().lower()
        if status == "filled":
            return "filled"
        if status == "rejected":
            return "rejected"
        if status == "pending":
            return "pending"
    raw_status = str(raw.get("status") or "").strip().lower()
    if raw_status == "filled":
        return "planned"
    if raw_status == "rejected":
        return "not_triggered"
    return "signal_only"


def signal_plan_status_label(status: str) -> str:
    labels = {
        "filled": "已成交",
        "rejected": "已拒单",
        "pending": "待执行",
        "planned": "理论计划",
        "not_triggered": "理论未触发",
        "signal_only": "仅信号",
    }
    return labels.get(status, status or "--")
