"""Entry-specific proxy backtests for the live limit-up recommendation desk."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median
from typing import Mapping, Sequence

from alphaagent.market.cache import TTLCache
from alphaagent.server.services.limit_up.domain import (
    event_fill_status,
    main_board_limit_price,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_daily_bars_for_symbols,
    load_snapshots_between,
)
from alphaagent.server.services.limit_up.repository import load_limit_up_dataset
from alphaagent.server.services.limit_up.service import build_limit_up_dashboard
from alphaagent.server.services.limit_up.history_service import get_history_backtest

ENTRY_MODES = {"auction", "sweep", "tail", "next_auction"}
EXIT_MODES = {"next_open", "next_close"}
ENTRY_MODE_LABELS = {
    "auction": "当日竞价",
    "sweep": "盘中扫板/回封",
    "tail": "尾盘确认",
    "next_auction": "明早竞价",
}
_DATASET_CACHE = TTLCache(max_items=16)
_RESULT_CACHE = TTLCache(max_items=64)


def get_limit_up_entry_backtest(
    start: date | None,
    end: date | None,
    entry_mode: str,
    exit_mode: str,
) -> dict[str, object]:
    """Compatibility entrypoint backed by the point-in-time full-history ledger."""

    return get_history_backtest(start, end, entry_mode, exit_mode)


def _build_cached_entry_backtest(
    start: date | None,
    end: date | None,
    entry_mode: str,
    exit_mode: str,
    ttl_seconds: int,
) -> dict[str, object]:
    bundle = _DATASET_CACHE.get_or_set(
        f"limit_up_entry_dataset:{start}:{end}",
        ttl_seconds,
        lambda: _load_entry_dataset(start, end),
    )
    return build_limit_up_entry_backtest(
        bundle["dataset"],
        bundle["snapshots"],
        entry_mode=entry_mode,
        exit_mode=exit_mode,
        historical_proxy_candidates=bundle["historical_proxy_candidates"],
    )


def _load_entry_dataset(start: date | None, end: date | None) -> dict[str, object]:
    dataset = load_limit_up_dataset(start=start, end=end)
    snapshots = load_snapshots_between(start, end)
    strict_symbols = _snapshot_symbols(snapshots)
    snapshot_dates = [
        parsed
        for row in snapshots
        if (parsed := _date_value(row.get("trade_date"))) is not None
    ]
    if strict_symbols and snapshot_dates:
        extra_bars = load_daily_bars_for_symbols(
            strict_symbols,
            min(snapshot_dates) - timedelta(days=7),
            max(snapshot_dates) + timedelta(days=14),
        )
        dataset = {
            **dataset,
            "daily_bars": _merge_bars(
                _rows(dataset.get("daily_bars")),
                extra_bars,
            ),
        }
    strict_dates = {
        str(row.get("trade_date") or "")[:10]
        for row in snapshots
        if row.get("trade_date")
    }
    return {
        "dataset": dataset,
        "snapshots": snapshots,
        "historical_proxy_candidates": _historical_proxy_candidates(
            dataset,
            strict_dates,
        ),
    }


def _cache_ttl(end: date | None) -> int:
    return 20 if end is None or end >= date.today() else 300


def build_limit_up_entry_backtest(
    dataset: Mapping[str, object],
    snapshots: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
    exit_mode: str = "next_open",
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10.0,
    historical_proxy_candidates: Sequence[Mapping[str, object]] | None = None,
    strict_signal_action_field: str = "action",
    strict_fill_evidence: str = "saved_buy_action",
) -> dict[str, object]:
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"Unsupported entry mode: {entry_mode}")
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"Unsupported exit mode: {exit_mode}")

    bars = _rows(dataset.get("daily_bars"))
    bar_index = {
        (str(row.get("vt_symbol") or ""), str(row.get("trade_date") or "")[:10]): row
        for row in bars
        if row.get("vt_symbol") and row.get("trade_date")
    }
    calendar = sorted(
        {key[1] for key in bar_index}
        | _calendar_values(dataset.get("trade_calendar"))
    )
    strict_dates = {
        str(row.get("trade_date") or "")[:10]
        for row in snapshots
        if row.get("trade_date")
    }
    strict_orders = _strict_snapshot_orders(
        snapshots,
        entry_mode,
        action_field=strict_signal_action_field,
        fill_evidence=strict_fill_evidence,
    )
    proxy_orders = (
        _historical_proxy_orders(dataset, entry_mode, strict_dates)
        if historical_proxy_candidates is None
        else _historical_proxy_orders_from_candidates(
            historical_proxy_candidates,
            entry_mode,
        )
    )
    raw_orders = [*strict_orders, *proxy_orders]
    total_cost_rate = commission_rate * 2 + stamp_tax_rate + slippage_bps * 2 / 10_000

    resolved_orders: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    for raw_order in raw_orders:
        order, trade = _resolve_order(
            raw_order,
            bar_index,
            calendar,
            entry_mode=entry_mode,
            exit_mode=exit_mode,
            total_cost_rate=total_cost_rate,
        )
        resolved_orders.append(order)
        if trade is not None:
            trades.append(trade)

    daily_results, total_return, max_drawdown = _daily_equity(trades)
    summary = _summary(
        resolved_orders,
        trades,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
    )
    modes = sorted({str(order.get("source_mode") or "") for order in resolved_orders})
    return {
        "status": "ready" if resolved_orders else "insufficient_data",
        "mode": "strict_signal_ledger" if modes == ["strict_snapshot"] else "entry_proxy_backtest",
        "entry_mode": entry_mode,
        "entry_mode_label": ENTRY_MODE_LABELS[entry_mode],
        "exit_mode": exit_mode,
        "costs": {
            "commission_rate": commission_rate,
            "stamp_tax_rate": stamp_tax_rate,
            "slippage_bps_each_side": slippage_bps,
            "total_round_trip_cost_pct": round(total_cost_rate * 100, 4),
        },
        "summary": summary,
        "daily_results": daily_results,
        "orders": resolved_orders,
        "trades": trades,
        "coverage": {
            **dict(dataset.get("coverage") or {}),
            "strict_snapshot_dates": len(strict_dates),
            "strict_snapshot_orders": sum(
                1 for order in resolved_orders if order.get("source_mode") == "strict_snapshot"
            ),
            "historical_proxy_orders": sum(
                1 for order in resolved_orders if order.get("source_mode") == "historical_proxy"
            ),
        },
        "limitations": [
            "严格快照回测的是系统当时动作，不代表券商真实成交；没有L2时成交可信度仍为盘口代理。",
            "旧日期使用日终事件重建并标记historical_proxy，不与严格快照混成真实成交结论。",
            "尾盘代理缺少完整14:30分钟覆盖时使用涨停价，结果只能用于方向比较。",
        ],
    }


def _strict_snapshot_orders(
    snapshots: Sequence[Mapping[str, object]],
    entry_mode: str,
    *,
    action_field: str = "action",
    fill_evidence: str = "saved_buy_action",
) -> list[dict[str, object]]:
    ordered_snapshots = sorted(snapshots, key=_snapshot_sort_key)
    if entry_mode == "next_auction":
        ordered_snapshots = _latest_snapshots_by_date(ordered_snapshots)

    selected: dict[tuple[str, str], dict[str, object]] = {}
    lane_name, entry_kinds, action = _strict_signal_filter(entry_mode)
    for snapshot in ordered_snapshots:
        trade_date = str(snapshot.get("trade_date") or "")[:10]
        recommendations = snapshot.get("recommendations")
        recommendations = recommendations if isinstance(recommendations, Mapping) else {}
        lanes = recommendations.get("lanes")
        lanes = lanes if isinstance(lanes, Mapping) else {}
        rows = lanes.get(lane_name)
        if not isinstance(rows, list):
            continue
        for signal in rows:
            if not isinstance(signal, Mapping):
                continue
            signal_action = (
                signal.get(action_field)
                if action_field in signal
                else signal.get("action")
            )
            if signal_action != action or str(signal.get("entry_kind") or "") not in entry_kinds:
                continue
            symbol = str(signal.get("vt_symbol") or "")
            if not symbol or not trade_date:
                continue
            order = {
                **dict(signal),
                "plan_date": trade_date,
                "source_mode": "strict_snapshot",
                "snapshot_at": snapshot.get("captured_at"),
                "entry_offset": 1 if entry_mode == "next_auction" else 0,
                "fill_evidence": fill_evidence,
                "final_sealed": signal.get("state") in {"sealed", "resealed"},
                "execution_confidence": signal.get("execution_confidence") or "proxy_without_l2",
            }
            key = (trade_date, symbol)
            if key not in selected:
                selected[key] = order
    return list(selected.values())


def _latest_snapshots_by_date(
    snapshots: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    latest: dict[str, Mapping[str, object]] = {}
    for snapshot in snapshots:
        trade_date = str(snapshot.get("trade_date") or "")[:10]
        if trade_date:
            latest[trade_date] = snapshot
    return [latest[trade_date] for trade_date in sorted(latest)]


def _snapshot_sort_key(snapshot: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(snapshot.get("trade_date") or "")[:10],
        str(snapshot.get("captured_at") or ""),
    )


def _strict_signal_filter(entry_mode: str) -> tuple[str, set[str], str]:
    if entry_mode == "auction":
        return "now", {"auction"}, "buy_now"
    if entry_mode == "sweep":
        return "now", {"sweep", "reseal"}, "buy_now"
    if entry_mode == "tail":
        return "tail", {"tail_seal"}, "buy_now"
    return "next_auction", {"next_auction"}, "next_auction"


def _historical_proxy_orders(
    dataset: Mapping[str, object],
    entry_mode: str,
    strict_dates: set[str],
) -> list[dict[str, object]]:
    return _historical_proxy_orders_from_candidates(
        _historical_proxy_candidates(dataset, strict_dates),
        entry_mode,
    )


def _historical_proxy_candidates(
    dataset: Mapping[str, object],
    strict_dates: set[str],
) -> list[dict[str, object]]:
    event_dates = sorted(
        {
            str(row.get("trade_date") or "")[:10]
            for row in _rows(dataset.get("events"))
            if row.get("trade_date")
        }
        - strict_dates
    )
    candidates: list[dict[str, object]] = []
    for event_date in event_dates:
        dashboard = build_limit_up_dashboard(dataset, target_date=date.fromisoformat(event_date))
        plan = dashboard.get("research_plan")
        plan = plan if isinstance(plan, Mapping) else {}
        for candidate in plan.get("plans") or []:
            if not isinstance(candidate, Mapping):
                continue
            candidates.append(
                {
                    "plan_date": event_date,
                    "candidate": dict(candidate),
                }
            )
    return candidates


def _historical_proxy_orders_from_candidates(
    proxy_candidates: Sequence[Mapping[str, object]],
    entry_mode: str,
) -> list[dict[str, object]]:
    orders: list[dict[str, object]] = []
    for item in proxy_candidates:
        event_date = str(item.get("plan_date") or "")[:10]
        candidate = item.get("candidate")
        if not event_date or not isinstance(candidate, Mapping):
            continue
        outcome = candidate.get("outcome")
        outcome = outcome if isinstance(outcome, Mapping) else {}
        final_sealed = str(outcome.get("final_status") or "") == "sealed"
        if entry_mode in {"auction", "next_auction", "tail"} and not final_sealed:
            continue
        fill_evidence = (
            event_fill_status(candidate, "conservative")
            if entry_mode == "sweep"
            else "historical_proxy_assumption"
        )
        orders.append(
            {
                "plan_date": event_date,
                "vt_symbol": candidate.get("vt_symbol"),
                "name": candidate.get("name"),
                "sector_id": candidate.get("sector_id"),
                "sector_name": candidate.get("sector_name"),
                "market_dragon_rank": candidate.get("market_dragon_rank"),
                "sector_dragon_rank": candidate.get("sector_dragon_rank"),
                "board_level": candidate.get("signal_board_level"),
                "state": "sealed" if final_sealed else "failed",
                "open_times": candidate.get("open_times"),
                "trigger_price": None,
                "source_mode": "historical_proxy",
                "entry_offset": 1 if entry_mode in {"auction", "next_auction"} else 0,
                "fill_evidence": fill_evidence,
                "final_sealed": final_sealed,
                "execution_confidence": "historical_proxy_unverifiable",
                "market_context": candidate.get("market_context"),
                "result": outcome,
            }
        )
    return orders


def _resolve_order(
    raw_order: Mapping[str, object],
    bar_index: Mapping[tuple[str, str], Mapping[str, object]],
    calendar: list[str],
    *,
    entry_mode: str,
    exit_mode: str,
    total_cost_rate: float,
) -> tuple[dict[str, object], dict[str, object] | None]:
    order = dict(raw_order)
    symbol = str(order.get("vt_symbol") or "")
    plan_date = str(order.get("plan_date") or "")[:10]
    entry_date = _calendar_date(calendar, plan_date, int(order.get("entry_offset") or 0))
    order["entry_date"] = entry_date
    if entry_date is None:
        order["status"] = "awaiting_entry_bar"
        return order, None
    entry_bar = bar_index.get((symbol, entry_date))
    if entry_bar is None:
        order["status"] = "entry_bar_missing"
        return order, None

    previous_date = _calendar_date(calendar, entry_date, -1)
    previous_bar = bar_index.get((symbol, previous_date or ""))
    entry_price = _entry_price(order, entry_bar, previous_bar, entry_mode)
    if entry_mode in {"auction", "next_auction"}:
        gap = _return_pct(
            _number(previous_bar.get("close_price")) if previous_bar else None,
            _number(entry_bar.get("open_price")),
        )
        order["auction_gap_pct"] = gap
        if gap is None or gap < 1 or gap > 7:
            order["status"] = "rejected_auction_gap"
            return order, None
    if entry_mode == "sweep" and order.get("source_mode") == "historical_proxy":
        if not str(order.get("fill_evidence") or "").startswith("filled_"):
            order["status"] = str(order.get("fill_evidence") or "unfilled_queue_unknown")
            return order, None
    if entry_mode == "tail" and not bool(order.get("final_sealed")):
        order["status"] = "unfilled_tail_not_sealed"
        return order, None
    if entry_price is None or entry_price <= 0:
        order["status"] = "entry_price_missing"
        return order, None

    exit_date, exit_field = _exit_target(calendar, entry_date, entry_mode, exit_mode)
    order.update(entry_price=entry_price, exit_date=exit_date, exit_field=exit_field)
    if exit_date is None:
        order["status"] = "awaiting_exit_bar"
        return order, None
    exit_bar = bar_index.get((symbol, exit_date))
    exit_price = _number(exit_bar.get(exit_field)) if exit_bar else None
    if exit_price is None or exit_price <= 0:
        order["status"] = "awaiting_exit_bar"
        return order, None

    return_pct = round(((exit_price / entry_price - 1) - total_cost_rate) * 100, 4)
    order["status"] = "filled_closed"
    order["exit_price"] = exit_price
    trade = {
        **order,
        "signal_date": plan_date,
        "entry_mode": entry_mode,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return_pct": return_pct,
        "entry_day_close_return_pct": _net_return_pct(
            entry_price,
            _number(entry_bar.get("close_price")),
            total_cost_rate,
        ),
        "next_open_return_pct": _path_return(
            symbol,
            entry_date,
            "open_price",
            bar_index,
            calendar,
            entry_price,
            total_cost_rate,
        ),
        "next_close_return_pct": _path_return(
            symbol,
            entry_date,
            "close_price",
            bar_index,
            calendar,
            entry_price,
            total_cost_rate,
        ),
        "is_win": return_pct > 0,
        "is_hard_loss": return_pct <= -5,
    }
    return order, trade


def _entry_price(
    order: Mapping[str, object],
    entry_bar: Mapping[str, object],
    previous_bar: Mapping[str, object] | None,
    entry_mode: str,
) -> float | None:
    if entry_mode in {"auction", "next_auction"}:
        return _number(entry_bar.get("open_price"))
    trigger = _number(order.get("trigger_price"))
    if trigger is not None:
        return trigger
    previous_close = _number(previous_bar.get("close_price")) if previous_bar else None
    return main_board_limit_price(previous_close) if previous_close else None


def _exit_target(
    calendar: list[str],
    entry_date: str,
    entry_mode: str,
    exit_mode: str,
) -> tuple[str | None, str]:
    del entry_mode
    exit_date = _calendar_date(calendar, entry_date, 1)
    return exit_date, "open_price" if exit_mode == "next_open" else "close_price"


def _path_return(
    symbol: str,
    entry_date: str,
    field: str,
    bar_index: Mapping[tuple[str, str], Mapping[str, object]],
    calendar: list[str],
    entry_price: float,
    total_cost_rate: float,
) -> float | None:
    next_date = _calendar_date(calendar, entry_date, 1)
    next_bar = bar_index.get((symbol, next_date or ""))
    return _net_return_pct(
        entry_price,
        _number(next_bar.get(field)) if next_bar else None,
        total_cost_rate,
    )


def _summary(
    orders: list[dict[str, object]],
    trades: list[dict[str, object]],
    *,
    total_return_pct: float,
    max_drawdown_pct: float,
) -> dict[str, object]:
    returns = [float(trade["return_pct"]) for trade in trades]
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    sealed_known = [order for order in orders if order.get("final_sealed") is not None]
    confidence_counts = defaultdict(int)
    for order in orders:
        confidence_counts[str(order.get("execution_confidence") or "unknown")] += 1
    return {
        "signal_count": len(orders),
        "filled_count": len(trades),
        "fill_rate": round(len(trades) / len(orders) * 100, 4) if orders else None,
        "trade_count": len(trades),
        "win_count": sum(1 for value in returns if value > 0),
        "win_rate": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 4)
        if returns
        else None,
        "average_return_pct": round(mean(returns), 4) if returns else None,
        "median_return_pct": round(median(returns), 4) if returns else None,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "hard_loss_count": sum(1 for value in returns if value <= -5),
        "hard_loss_rate": round(sum(1 for value in returns if value <= -5) / len(returns) * 100, 4)
        if returns
        else None,
        "seal_rate": round(
            sum(1 for order in sealed_known if order.get("final_sealed")) / len(sealed_known) * 100,
            4,
        )
        if sealed_known
        else None,
        "profit_factor": round(gains / losses, 4) if losses else None,
        "execution_confidence": dict(confidence_counts),
    }


def _daily_equity(
    trades: list[dict[str, object]],
) -> tuple[list[dict[str, object]], float, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get("exit_date") or "")].append(float(trade["return_pct"]))
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    rows: list[dict[str, object]] = []
    for result_date in sorted(grouped):
        daily_return = mean(grouped[result_date])
        equity *= 1 + daily_return / 100
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)
        rows.append(
            {
                "result_date": result_date,
                "trade_count": len(grouped[result_date]),
                "daily_return_pct": round(daily_return, 4),
                "equity": round(equity, 6),
                "total_return_pct": round((equity - 1) * 100, 4),
                "drawdown_pct": round(drawdown, 4),
            }
        )
    return rows, round((equity - 1) * 100, 4), round(max_drawdown, 4)


def _calendar_date(calendar: list[str], base: str, offset: int) -> str | None:
    if base not in calendar:
        return None
    index = calendar.index(base) + offset
    return calendar[index] if 0 <= index < len(calendar) else None


def _snapshot_symbols(snapshots: Sequence[Mapping[str, object]]) -> list[str]:
    symbols: set[str] = set()
    for snapshot in snapshots:
        for candidate in snapshot.get("candidates") or []:
            if isinstance(candidate, Mapping) and candidate.get("vt_symbol"):
                symbols.add(str(candidate["vt_symbol"]))
    return sorted(symbols)


def _merge_bars(
    first: list[dict[str, object]],
    second: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged = {
        (str(row.get("vt_symbol") or ""), str(row.get("trade_date") or "")[:10]): row
        for row in [*first, *second]
        if row.get("vt_symbol") and row.get("trade_date")
    }
    return list(merged.values())


def _rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _calendar_values(value: object) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {str(item)[:10] for item in value if item}


def _date_value(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _return_pct(base: float | None, value: float | None) -> float | None:
    return round((value / base - 1) * 100, 4) if base and value is not None else None


def _net_return_pct(
    entry_price: float,
    exit_price: float | None,
    total_cost_rate: float,
) -> float | None:
    if exit_price is None:
        return None
    return round(((exit_price / entry_price - 1) - total_cost_rate) * 100, 4)


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
