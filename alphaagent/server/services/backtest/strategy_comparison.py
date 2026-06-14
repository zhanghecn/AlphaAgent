"""Portfolio-level strategy comparison for the same backtest parameters."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.strategy_registry import list_strategies


RunBacktest = Callable[[BacktestParams], dict[str, Any]]


def compare_strategies(
    base_params: BacktestParams,
    *,
    strategies: list[str] | None = None,
    run_backtest: RunBacktest,
) -> dict[str, Any]:
    """Run multiple strategies with identical non-persistent parameters."""

    strategy_meta = {str(item.get("id")): item for item in list_strategies()}
    selected = _selected_strategies(strategies, strategy_meta)
    if not selected:
        return {"status": "empty", "rows": [], "message": "No strategies selected."}

    rows = []
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
        rows.append(_strategy_row(strategy_id, strategy_meta.get(strategy_id) or {}, result))

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


def _strategy_row(strategy_id: str, meta: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
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
