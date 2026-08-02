"""Adapt leader-first-board research output into LimitUpLaneBacktest/Ledger shape.

让前端「潜龙首板」tab 直接复用打板研究的 ``BacktestView`` / ``LedgerTimeline`` 组件。
原始结果只有 summary/equity/trades 三块基石，这里补齐 BacktestView 的硬必需字段
（validation/trades/skipped_orders/coverage/account_config 等），其余丰富度区块
（drawdown_diagnostics/core_quality_filter 等）按真实缺失优雅降级。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

STRATEGY_VERSION = "leader-first-board-backtest-v2"


def adapt_leader_backtest(result: Mapping[str, object]) -> dict[str, object]:
    """研究回测结果 → LimitUpLaneBacktest 结构（前端复用 BacktestView）。"""

    strategy_version = str(result.get("study_version") or STRATEGY_VERSION)
    raw_summary = result.get("execution_summary") or {}
    summary = _adapt_summary(raw_summary)
    exit_trades = [
        _adapt_trade(trade) for trade in (result.get("closed_trades") or [])
    ]
    trades = _aggregate_positions(exit_trades)
    trade_count = int(_num(summary.get("trade_count")) or len(trades))
    signal_count = int(_num(result.get("signal_count")) or trade_count)
    trades_by_day = Counter(
        str(trade.get("buy_date") or "") for trade in trades if trade.get("buy_date")
    )
    summary.update(
        {
            "signal_count": signal_count,
            "filled_count": trade_count,
            "fill_rate": (
                round(trade_count / signal_count * 100, 4) if signal_count else None
            ),
            "trade_count": trade_count,
            "trade_day_count": len(trades_by_day),
            "average_trades_per_day": (
                round(trade_count / len(trades_by_day), 4) if trades_by_day else 0.0
            ),
            "max_trades_per_day": max(trades_by_day.values(), default=0),
        }
    )
    daily_results = _adapt_daily_results(result.get("equity_curve") or [], summary)
    return {
        "status": "ok",
        "mode": "leader_factor_research_proxy",
        "strategy_version": strategy_version,
        "lane": "first_board",
        "exit_mode": "dynamic",
        "summary": summary,
        "execution_summary": summary,
        "signal_summary": summary,
        "account_config": _adapt_account_config(result.get("account_config") or {}),
        "portfolio_policy": {
            "included_lanes": ["first_board"],
            "excluded_lanes": ["two_to_three", "high_board"],
            "selection_basis": (
                "leader_3_prior_plus_touch_cap_expanding_top3"
                if strategy_version == STRATEGY_VERSION
                else "legacy_leader_factor_expanding_top3"
            ),
        },
        "exit_summary": _adapt_exit_summary(exit_trades),
        "daily_results": daily_results,
        "trades": trades,
        "skipped_orders": [],
        "open_positions": [],
        "validation": _stub_validation(summary),
        "simulation_eligible": False,
        "coverage": _stub_coverage(result, daily_results),
    }


def group_leader_trades_by_day(
    result: Mapping[str, object],
) -> list[dict[str, object]]:
    """closed_trades → 按 buy_date 分组的 LimitUpLaneLedger[]（喂 LedgerTimeline）。

    同一笔买入（vt_symbol + buy_date）的多笔分批卖出（涨停减半 limit_half + 后续清仓）
    聚合成一条 trade，避免交割单里同一笔买入显示成多行；分批明细存 exit_splits。
    """

    trades = _aggregate_positions(
        [_adapt_trade(trade) for trade in (result.get("closed_trades") or [])]
    )
    by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        by_day[str(trade.get("buy_date") or "")].append(trade)
    ledgers: list[dict[str, object]] = []
    for trade_date, day_trades in sorted(by_day.items()):
        ledgers.append(
            {
                "status": "ok",
                "trade_date": trade_date,
                "lane": "first_board",
                "exit_mode": "dynamic",
                "selected_count": len(day_trades),
                "trades": day_trades,
                "observations": [],
            }
        )
    return ledgers


def _aggregate_positions(
    trades: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    by_position: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        key = (str(trade.get("vt_symbol") or ""), str(trade.get("buy_date") or ""))
        by_position[key].append(trade)
    return [_aggregate_position(parts) for parts in by_position.values()]


def _aggregate_position(parts: list[dict[str, object]]) -> dict[str, object]:
    """同一笔买入的分批卖出聚合成一条 trade；单笔原样补 split_count=1。"""

    if len(parts) == 1:
        return {**parts[0], "split_count": 1, "exit_splits": []}
    first = parts[0]
    last = parts[-1]
    total_vol = sum(_num(p.get("volume")) or 0 for p in parts)
    total_pnl = sum(_num(p.get("net_pnl")) or 0 for p in parts)
    total_buy = sum(_num(p.get("buy_amount")) or 0 for p in parts) or (
        _num(first.get("buy_price")) or 0
    ) * total_vol
    total_buy_fee = sum(_num(p.get("buy_fee")) or 0 for p in parts)
    total_cash_cost = sum(_num(p.get("cash_cost")) or 0 for p in parts) or (
        total_buy + total_buy_fee
    )
    total_sell = sum(_num(p.get("sell_amount")) or 0 for p in parts)
    total_sell_fee = sum(_num(p.get("sell_fee")) or 0 for p in parts)
    total_fee = sum(_num(p.get("total_fee")) or 0 for p in parts)
    return_pct = round(total_pnl / total_cash_cost * 100, 4) if total_cash_cost else None
    exit_splits = [
        {
            "exit_reason": str(p.get("exit_reason") or ""),
            "sell_date": p.get("sell_date"),
            "sell_time": p.get("sell_time"),
            "volume": _num(p.get("volume")) or 0,
            "return_pct": p.get("return_pct"),
        }
        for p in parts
    ]
    return {
        **first,
        "volume": total_vol,
        "buy_amount": round(total_buy, 4),
        "buy_fee": round(total_buy_fee, 4),
        "cash_cost": round(total_cash_cost, 4),
        "sell_amount": round(total_sell, 4),
        "fee": round(total_sell_fee, 4),
        "sell_fee": round(total_sell_fee, 4),
        "total_fee": round(total_fee, 4),
        "net_pnl": round(total_pnl, 4),
        "return_pct": return_pct,
        "is_win": total_pnl > 0,
        # 卖出侧用最后一笔（最终清仓）的时点/价格
        "sell_date": last.get("sell_date"),
        "sell_time": last.get("sell_time"),
        "sell_price": last.get("sell_price"),
        "exit_date": last.get("exit_date"),
        "exit_price": last.get("exit_price"),
        "exit_reason": _aggregate_exit_reason(parts),
        "split_count": len(parts),
        "exit_splits": exit_splits,
    }


def _aggregate_exit_reason(parts: list[dict[str, object]]) -> str:
    """分批卖出原因聚合，如 'limit_half×2 + open_below_prev_close'。"""

    counts: Counter[str] = Counter(str(p.get("exit_reason") or "") for p in parts)
    return " + ".join(
        f"{reason}×{count}" if count > 1 else reason for reason, count in counts.items()
    )


def _adapt_summary(raw: Mapping[str, object]) -> dict[str, object]:
    trade_count = _num(raw.get("trade_count")) or 0
    win_rate = _num(raw.get("win_rate"))
    total_return = _num(raw.get("total_return_pct")) or 0.0
    max_drawdown = _num(raw.get("max_drawdown_pct")) or 0.0
    return {
        "initial_cash": _num(raw.get("initial_cash")) or 100_000.0,
        "final_equity": _num(raw.get("final_equity")),
        "signal_count": trade_count,
        "filled_count": trade_count,
        "fill_rate": 100.0 if trade_count else None,
        "trade_count": trade_count,
        "trade_day_count": _num(raw.get("trade_day_count")) or 0,
        "average_trades_per_day": _num(raw.get("average_trades_per_day")) or 0.0,
        "max_trades_per_day": _num(raw.get("max_trades_per_day")) or 0,
        "max_industry_concentration_pct": None,
        "win_count": _num(raw.get("win_count")) or 0,
        "win_rate": win_rate,
        "average_return_pct": _num(raw.get("average_return_pct")),
        "median_return_pct": None,
        "total_return_pct": total_return,
        "max_drawdown_pct": max_drawdown,
        "hard_loss_count": _num(raw.get("hard_loss_count")) or 0,
        "hard_loss_rate": None,
        "seal_rate": None,
        "profit_factor": _num(raw.get("profit_factor")),
        "total_fees": _num(raw.get("total_fees")),
    }


def _adapt_account_config(raw: Mapping[str, object]) -> dict[str, object]:
    return {
        "initial_cash": _num(raw.get("initial_cash")) or 100_000.0,
        "max_positions": _num(raw.get("max_positions")) or 3,
        "commission_rate": _num(raw.get("commission_rate")) or 0.0003,
        "minimum_commission": _num(raw.get("minimum_commission")) or 5.0,
        "stamp_tax_rate": _num(raw.get("stamp_tax_rate")) or 0.0005,
        "transfer_fee_rate": _num(raw.get("transfer_fee_rate")) or 0.00001,
        "slippage_bps": _num(raw.get("slippage_bps")) or 10.0,
        "lot_size": _num(raw.get("lot_size")) or 100,
    }


def _adapt_daily_results(
    equity_curve: Sequence[Mapping[str, object]], summary: Mapping[str, object]
) -> list[dict[str, object]]:
    initial_cash = _num(summary.get("initial_cash")) or 100_000.0
    results: list[dict[str, object]] = []
    previous_equity = initial_cash
    for row in equity_curve:
        equity = _num(row.get("total_equity")) or previous_equity
        daily_return = (
            (equity / previous_equity - 1) * 100 if previous_equity else 0.0
        )
        total_return = (equity / initial_cash - 1) * 100 if initial_cash else 0.0
        results.append(
            {
                "result_date": str(row.get("trade_date") or ""),
                "trade_count": 0,
                "cash": _num(row.get("cash")) or 0.0,
                "market_value": _num(row.get("market_value")) or 0.0,
                "total_equity": equity,
                "position_count": 0,
                "utilization_pct": 0.0,
                "daily_return_pct": round(daily_return, 4),
                "equity": equity,
                "total_return_pct": round(total_return, 4),
                "drawdown_pct": _num(row.get("drawdown_pct")) or 0.0,
            }
        )
        previous_equity = equity
    return results


def _adapt_trade(trade: Mapping[str, object]) -> dict[str, object]:
    reason = str(trade.get("exit_reason") or "")
    buy_price = _num(trade.get("buy_price"))
    exit_price = _num(trade.get("exit_price"))
    volume = _num(trade.get("volume")) or 0
    buy_fee = _num(trade.get("buy_fee")) or 0.0
    sell_fee = _num(trade.get("sell_fee")) or _num(trade.get("fee")) or 0.0
    first_limit_time = str(trade.get("first_limit_time") or "")
    return {
        "lane": "first_board",
        "vt_symbol": str(trade.get("vt_symbol") or ""),
        "name": str(trade.get("name") or trade.get("vt_symbol") or ""),
        "buy_date": str(trade.get("entry_date") or ""),
        "buy_time": first_limit_time or "09:30:00",
        "first_limit_time": first_limit_time,
        "buy_price": buy_price,
        "sell_date": str(trade.get("exit_date") or "") or None,
        "sell_time": _sell_time(reason),
        "sell_price": exit_price,
        "return_pct": _num(trade.get("return_pct")),
        "d1_outcome": "leader_proxy",
        "d_board_status": "sealed",
        "execution_confidence": "research_only",
        "signal_date": str(trade.get("entry_date") or ""),
        "entry_date": str(trade.get("entry_date") or ""),
        "exit_date": str(trade.get("exit_date") or ""),
        "entry_price": buy_price,
        "exit_price": exit_price,
        "volume": volume,
        "buy_amount": _num(trade.get("buy_amount"))
        or (round(buy_price * volume, 4) if buy_price else 0.0),
        "buy_fee": buy_fee,
        "cash_cost": _num(trade.get("cash_cost")) or 0.0,
        "sell_amount": _num(trade.get("sell_amount")) or 0.0,
        "sell_fee": sell_fee,
        "total_fee": _num(trade.get("total_fee")) or buy_fee + sell_fee,
        "net_pnl": _num(trade.get("net_pnl")) or 0.0,
        "exit_reason": reason,
    }


def _adapt_exit_summary(trades: Sequence[Mapping[str, object]]) -> dict[str, object]:
    reasons = Counter(str(trade.get("exit_reason") or "") for trade in trades)
    return {
        "mode": "dynamic",
        "auction_exit_count": reasons.get("open_below_prev_close", 0),
        "close_exit_count": reasons.get("close_not_limit", 0)
        + reasons.get("final_close", 0),
        "minute_1430_count": 0,
        "daily_close_proxy_count": reasons.get("limit_half", 0),
    }


def _stub_validation(summary: Mapping[str, object]) -> dict[str, object]:
    return {
        "passed": False,
        "status": "research_only",
        "checks": [
            {
                "phase": "full_range",
                "passed": False,
                "trade_count": _num(summary.get("trade_count")) or 0,
                "win_rate": _num(summary.get("win_rate")),
                "total_return_pct": _num(summary.get("total_return_pct")),
                "max_drawdown_pct": _num(summary.get("max_drawdown_pct")),
            }
        ],
        "reason": "leader_factor_research_proxy_no_walk_forward",
    }


def _stub_coverage(
    result: Mapping[str, object], daily_results: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    return {
        "status": "ok",
        "reliable_start": result.get("start"),
        "reliable_end": result.get("end"),
        "daily_close_count": len(daily_results),
        "daily_close_missing_count": 0,
        "minute_1430_count": 0,
        "daily_close_proxy_count": 0,
        "exit_price_missing_count": 0,
    }


def _sell_time(reason: str) -> str:
    if reason == "open_below_prev_close":
        return "09:30:00"
    return "15:00:00"


def _num(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
