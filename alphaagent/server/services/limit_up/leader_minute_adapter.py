"""Adapt leader minute-backtest output into LimitUpLaneBacktest/Ledger shape.

复用 leader_first_board_adapter 的 helpers（summary/daily/aggregate/stub），仅
adapt_minute_backtest / group_minute_trades_by_day / _adapt_trade_minute 自定义：
buy_time 用分钟级 bar_time（真实买入时刻，非 first_limit_time）。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from alphaagent.server.services.limit_up.leader_first_board_adapter import (
    _adapt_account_config,
    _adapt_daily_results,
    _adapt_exit_summary,
    _adapt_summary,
    _aggregate_exit_reason,
    _aggregate_position,
    _num,
    _sell_time,
    _stub_coverage,
    _stub_validation,
)

STRATEGY_VERSION = "leader-minute-backtest-v2"


def adapt_minute_backtest(v3_result: Mapping[str, object]) -> dict[str, object]:
    """分钟级回测结果 → LimitUpLaneBacktest 结构（前端复用 BacktestView）。"""

    raw_summary = v3_result.get("execution_summary") or {}
    summary = _adapt_summary(raw_summary)
    trades = [_adapt_trade_minute(trade) for trade in (v3_result.get("closed_trades") or [])]
    daily_results = _adapt_daily_results(v3_result.get("equity_curve") or [], summary)
    return {
        "status": "ok",
        "mode": "leader_minute_backtest",
        "strategy_version": STRATEGY_VERSION,
        "lane": "first_board",
        "exit_mode": "dynamic",
        "summary": summary,
        "execution_summary": summary,
        "signal_summary": summary,
        "account_config": _adapt_account_config(v3_result.get("account_config") or {}),
        "portfolio_policy": {
            "included_lanes": ["first_board"],
            "excluded_lanes": ["two_to_three", "high_board"],
            "selection_basis": "allmarket_minute_trigger_d1_factor_expanding",
        },
        "exit_summary": _adapt_exit_summary(trades),
        "daily_results": daily_results,
        "trades": trades,
        "skipped_orders": [],
        "open_positions": [],
        "validation": _stub_validation(summary),
        "simulation_eligible": False,
        "coverage": _stub_coverage(v3_result, daily_results),
    }


def group_minute_trades_by_day(
    v3_result: Mapping[str, object],
) -> list[dict[str, object]]:
    """分钟级 closed_trades → 按 buy_date 分组（同笔买入分批卖出聚合）。"""

    trades = [_adapt_trade_minute(trade) for trade in (v3_result.get("closed_trades") or [])]
    by_position: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for trade in trades:
        key = (str(trade.get("vt_symbol") or ""), str(trade.get("buy_date") or ""))
        by_position[key].append(trade)
    aggregated = [_aggregate_position(parts) for parts in by_position.values()]
    by_day: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trade in aggregated:
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


def _adapt_trade_minute(trade: Mapping[str, object]) -> dict[str, object]:
    reason = str(trade.get("exit_reason") or "")
    buy_price = _num(trade.get("buy_price"))
    exit_price = _num(trade.get("exit_price"))
    volume = _num(trade.get("volume")) or 0
    fee = _num(trade.get("fee")) or 0.0
    # 分钟级：buy_time 用真实触发 bar_time（如 09:33:00）；board_status 为当日结局（展示用）
    buy_time = str(trade.get("buy_time") or "09:30:00")
    return {
        "lane": "first_board",
        "vt_symbol": str(trade.get("vt_symbol") or ""),
        "name": str(trade.get("name") or trade.get("vt_symbol") or ""),
        "buy_date": str(trade.get("entry_date") or ""),
        "buy_time": buy_time,
        "first_limit_time": str(trade.get("first_limit_time") or ""),
        "buy_price": buy_price,
        "sell_date": str(trade.get("exit_date") or "") or None,
        "sell_time": _sell_time(reason),
        "sell_price": exit_price,
        "return_pct": _num(trade.get("return_pct")),
        "d1_outcome": "leader_minute_proxy",
        "d_board_status": str(trade.get("board_status") or "no_limit"),
        "execution_confidence": "research_only",
        "signal_date": str(trade.get("entry_date") or ""),
        "entry_date": str(trade.get("entry_date") or ""),
        "exit_date": str(trade.get("exit_date") or ""),
        "entry_price": buy_price,
        "exit_price": exit_price,
        "volume": volume,
        "buy_amount": round(buy_price * volume, 4) if buy_price else 0.0,
        "buy_fee": 0.0,
        "sell_amount": _num(trade.get("sell_amount")) or 0.0,
        "sell_fee": fee,
        "total_fee": fee,
        "net_pnl": _num(trade.get("net_pnl")) or 0.0,
        "exit_reason": reason,
    }
