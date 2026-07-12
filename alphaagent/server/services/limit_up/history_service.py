"""Build, persist, and report full-history point-in-time limit-up replays."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean, median
import threading
from typing import Mapping, Sequence

from alphaagent.market.cache import TTLCache
from alphaagent.server.services.limit_up import (
    cash_backtest,
    factor_audit,
    history_engine,
    history_repository,
    lane_repository,
    live_evidence,
    walk_forward_model,
)
from alphaagent.server.services.limit_up.lane_research import BOARD_LANES

_BUILD_LOCK = threading.RLock()
_BUILD_THREAD: threading.Thread | None = None
_MODEL_REPORT_CACHE = TTLCache(max_items=16)
_LANE_VALIDATION_CACHE = TTLCache(max_items=16)
_BUILD_STATE: dict[str, object] = {
    "status": "idle",
    "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
}
LANE_RULE_FREEZE_DATE = date(2026, 7, 12)
BACKTEST_SCOPES = ("portfolio", *BOARD_LANES)


def start_history_rebuild() -> dict[str, object]:
    global _BUILD_THREAD
    with _BUILD_LOCK:
        if _BUILD_THREAD is not None and _BUILD_THREAD.is_alive():
            return {**_BUILD_STATE, "already_running": True}
        _set_build_state(status="building", started_at=_utc_now())
        _BUILD_THREAD = threading.Thread(
            target=_background_rebuild,
            name="limit-up-history-rebuild",
            daemon=True,
        )
        _BUILD_THREAD.start()
        return dict(_BUILD_STATE)


def rebuild_history_sync() -> dict[str, object]:
    with _BUILD_LOCK:
        _set_build_state(status="building", started_at=_utc_now(), error=None)
        frame, coverage = history_repository.load_reliable_history_frame()
        reliable_start = date.fromisoformat(str(coverage["reliable_start"]))
        reliable_end = date.fromisoformat(str(coverage["reliable_end"]))
        event_evidence, financial_index, lane_coverage = lane_repository.load_lane_research_data(
            reliable_start,
            reliable_end,
        )
        coverage = {**coverage, **lane_coverage}
        replays = history_engine.build_history_replays(
            frame,
            reliable_start=reliable_start,
            reliable_end=reliable_end,
            event_evidence=event_evidence,
            financial_index=financial_index,
        )
        persisted = history_repository.replace_history_replays(
            history_engine.HISTORY_STRATEGY_VERSION,
            replays,
            coverage,
        )
        _MODEL_REPORT_CACHE.clear()
        _LANE_VALIDATION_CACHE.clear()
        live_evidence.clear_live_evidence_cache()
        result = {
            "status": "ready",
            "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
            "persisted_days": persisted,
            "start": replays[0]["trade_date"] if replays else None,
            "end": replays[-1]["trade_date"] if replays else None,
            "coverage": coverage,
            "finished_at": _utc_now(),
        }
        _set_build_state(**result)
        return result


def refresh_history_if_needed(latest_reliable_date: date | None) -> dict[str, object]:
    """Rebuild the versioned ledger only after the reliable daily calendar advances."""

    with _BUILD_LOCK:
        coverage = history_repository.history_coverage(
            history_engine.HISTORY_STRATEGY_VERSION
        )
        persisted_end = _optional_date(coverage.get("persisted_end"))
        if latest_reliable_date is None or (
            persisted_end is not None and persisted_end >= latest_reliable_date
        ):
            return {
                "status": "skipped",
                "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
                "persisted_days": int(coverage.get("persisted_days") or 0),
                "persisted_end": persisted_end.isoformat() if persisted_end else None,
                "latest_reliable_date": (
                    latest_reliable_date.isoformat() if latest_reliable_date else None
                ),
            }

        result = rebuild_history_sync()
        rebuilt_end = _optional_date(result.get("end"))
        if rebuilt_end is None or rebuilt_end < latest_reliable_date:
            raise RuntimeError(
                "limit-up history rebuild did not reach the latest reliable trade date"
            )
        return {
            **result,
            "previous_persisted_end": persisted_end.isoformat() if persisted_end else None,
            "latest_reliable_date": latest_reliable_date.isoformat(),
        }


def get_history_status() -> dict[str, object]:
    coverage = history_repository.history_coverage(history_engine.HISTORY_STRATEGY_VERSION)
    state = dict(_BUILD_STATE)
    if int(coverage.get("persisted_days") or 0) > 0 and state.get("status") == "idle":
        state["status"] = "ready"
    return {
        **state,
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "coverage": coverage,
    }


def get_history_dates() -> dict[str, object]:
    dates = history_repository.load_history_dates(history_engine.HISTORY_STRATEGY_VERSION)
    coverage = history_repository.history_coverage(history_engine.HISTORY_STRATEGY_VERSION)
    return {
        "status": "ready" if dates else "empty",
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "dates": [item.isoformat() for item in dates],
        "start": dates[0].isoformat() if dates else None,
        "end": dates[-1].isoformat() if dates else None,
        "latest": dates[-1].isoformat() if dates else None,
        "count": len(dates),
        "coverage": coverage,
    }


def get_history_day(trade_date: date) -> dict[str, object]:
    payload = history_repository.load_history_day(
        history_engine.HISTORY_STRATEGY_VERSION,
        trade_date,
    )
    if payload is None:
        return {
            "status": "not_found",
            "trade_date": trade_date.isoformat(),
            "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        }
    return {**payload, "status": "ready"}


def get_history_ledger(
    trade_date: date,
    *,
    lane: str | None = None,
    exit_mode: str = "next_open",
) -> dict[str, object]:
    if lane is not None and lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {lane}")
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    payload = history_repository.load_history_day(
        history_engine.HISTORY_STRATEGY_VERSION,
        trade_date,
    )
    if payload is None:
        return {
            "status": "not_found",
            "trade_date": trade_date.isoformat(),
            "lane": lane,
            "trades": [],
        }
    selected = _selected_lane_candidates(payload, lane)
    validations = {
        lane_name: _safe_lane_validation_status(lane_name, exit_mode)
        for lane_name in sorted(
            {
                str(candidate.get("lane") or "")
                for candidate in selected
                if str(candidate.get("lane") or "") in BOARD_LANES
            }
        )
    }
    executable = [
        candidate
        for candidate in selected
        if bool((validations.get(str(candidate.get("lane") or "")) or {}).get("passed"))
    ]
    observations = [
        candidate
        for candidate in selected
        if candidate not in executable
    ]
    trades = [_ledger_trade(candidate, exit_mode) for candidate in executable]
    observation_trades = [_ledger_trade(candidate, exit_mode) for candidate in observations]
    board_lanes = payload.get("board_lanes")
    board_lanes = board_lanes if isinstance(board_lanes, Mapping) else {}
    portfolio = payload.get("lane_portfolio")
    portfolio = portfolio if isinstance(portfolio, Mapping) else {}
    return {
        "status": "ready",
        "trade_date": trade_date.isoformat(),
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "validation_phase": payload.get("validation_phase"),
        "lane": lane,
        "exit_mode": exit_mode,
        "action": "normal" if trades else "observe" if observation_trades else "empty",
        "candidate_count": len(selected),
        "selected_count": len(trades),
        "observation_count": len(observation_trades),
        "lane_counts": {
            lane_name: len(rows) if isinstance(rows, list) else 0
            for lane_name, rows in board_lanes.items()
            if lane_name in BOARD_LANES
        },
        "trades": trades,
        "observations": observation_trades,
        "validation": validations.get(lane) if lane else None,
        "lane_validations": validations,
        "market_context": payload.get("market_context") or {},
        "data_quality": payload.get("data_quality") or {},
        "coverage": payload.get("coverage") or {},
    }


def get_lane_validation_status(
    lane: str,
    exit_mode: str = "next_open",
) -> dict[str, object]:
    """Return the cached out-of-sample gate used by ledger and live decisions."""

    if lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {lane}")
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    return get_lane_validation_snapshot(exit_mode)[lane]


def get_lane_validation_snapshot(
    exit_mode: str = "next_open",
) -> dict[str, dict[str, object]]:
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    cache_key = f"{history_engine.HISTORY_STRATEGY_VERSION}:all:{exit_mode}"

    def load() -> dict[str, dict[str, object]]:
        rows = history_repository.load_history_range(
            history_engine.HISTORY_STRATEGY_VERSION,
            None,
            None,
        )
        portfolio_orders = _selected_history_orders(rows, None)
        bars, trade_dates = _account_market_data(rows, portfolio_orders)
        return {
            lane: _lane_validation_from_rows(
                rows,
                lane,
                exit_mode,
                bars=bars,
                trade_dates=trade_dates,
            )
            for lane in BOARD_LANES
        }

    return _LANE_VALIDATION_CACHE.get_or_set(cache_key, 900, load)


def get_lane_history_backtest(
    start: date | None,
    end: date | None,
    *,
    lane: str,
    exit_mode: str = "next_open",
    trade_limit: int = 500,
    account_config: cash_backtest.CashBacktestConfig | None = None,
) -> dict[str, object]:
    if lane not in BACKTEST_SCOPES:
        raise ValueError(f"unsupported board lane: {lane}")
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    rows = history_repository.load_history_range(
        history_engine.HISTORY_STRATEGY_VERSION,
        start,
        end,
    )
    lane_filter = None if lane == "portfolio" else lane
    orders = _selected_history_orders(rows, lane_filter)
    signal_trades = [
        trade
        for order in orders
        if (trade := _lane_closed_trade(order, exit_mode)) is not None
    ]
    signal_daily_results, signal_return, signal_drawdown = _signal_daily_equity(signal_trades)
    signal_summary = _summary(
        orders,
        signal_trades,
        total_return_pct=signal_return,
        max_drawdown_pct=signal_drawdown,
    )
    bars, trade_dates = _account_market_data(rows, orders)
    config = account_config or cash_backtest.CashBacktestConfig()
    account = _simulate_account(orders, bars, trade_dates, exit_mode, config)
    summary = account["execution_summary"]
    phase_summaries = {
        phase: _simulate_account(
            [order for order in orders if order.get("validation_phase") == phase],
            bars,
            trade_dates,
            exit_mode,
            config,
        )["execution_summary"]
        for phase in ("warmup", "expanding_oos", "locked_holdout")
    }
    coverage = (
        dict(rows[-1].get("coverage") or {})
        if rows
        else history_repository.history_coverage(history_engine.HISTORY_STRATEGY_VERSION)
    )
    segment_summaries = {
        segment: _segment_summary(orders, signal_trades, segment)
        for segment in ("intraday_path_prefix", "event_time_proxy_without_path", "daily_auction_point_in_time")
    }
    forward_orders = [
        order
        for order in orders
        if _trade_is_after_freeze(order, LANE_RULE_FREEZE_DATE)
    ]
    forward_summary = _simulate_account(
        forward_orders,
        bars,
        trade_dates,
        exit_mode,
        config,
    )["execution_summary"]
    validation = _lane_validation(lane, phase_summaries, forward_summary)
    return {
        "status": "ready" if rows else "insufficient_data",
        "mode": "real_cash_point_in_time_replay",
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "lane": lane,
        "exit_mode": exit_mode,
        "summary": summary,
        "execution_summary": summary,
        "signal_summary": signal_summary,
        "phase_summaries": phase_summaries,
        "segment_summaries": segment_summaries,
        "segment_summary_mode": "signal_research_upper_bound",
        "daily_results": account["equity_curve"],
        "signal_daily_results": signal_daily_results,
        "account_config": account["account_config"],
        "execution_version": account["execution_version"],
        "execution_assumptions": account["execution_assumptions"],
        "orders": account["orders"][-trade_limit:],
        "signals": orders[-trade_limit:],
        "trades": account["executed_trades"][-trade_limit:],
        "skipped_orders": account["skipped_orders"][-trade_limit:],
        "open_positions": account["open_positions"],
        "validation": validation,
        "simulation_eligible": bool(validation["passed"]),
        "coverage": {
            **coverage,
            "selected_start": rows[0].get("trade_date") if rows else None,
            "selected_end": rows[-1].get("trade_date") if rows else None,
            "selected_trade_days": len(rows),
            "account_price_rows": len(bars),
        },
        "costs": {
            **account["account_config"],
            "slippage_bps_each_side": config.slippage_bps,
        },
        "limitations": [
            "首板分时路径为三分钟代理，没有Tick/L2时不能证明排队成交。",
            "接力竞价使用日线开盘成交代理；历史逐日板块成员仍可能存在幸存者偏差。",
            "信号日等权收益仅作研究上界，主复利来自10万元共享现金账户。",
            "锁定留出结果不参与规则修改，未同时通过三段验证时保持研究状态。",
        ],
    }


def get_history_backtest(
    start: date | None,
    end: date | None,
    entry_mode: str,
    exit_mode: str = "next_open",
    *,
    trade_limit: int = 300,
) -> dict[str, object]:
    if entry_mode not in history_engine.ENTRY_MODES:
        raise ValueError(f"unsupported entry mode: {entry_mode}")
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    rows = history_repository.load_history_range(
        history_engine.HISTORY_STRATEGY_VERSION,
        start,
        end,
    )
    orders: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    observational_trades: list[dict[str, object]] = []
    for day in rows:
        phase = str(day.get("validation_phase") or "unknown")
        lanes = day.get("lanes")
        lanes = lanes if isinstance(lanes, Mapping) else {}
        candidates = lanes.get(entry_mode)
        candidates = candidates if isinstance(candidates, list) else []
        for raw_candidate in candidates:
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate = {**dict(raw_candidate), "validation_phase": phase}
            orders.append(candidate)
            trade = _closed_trade(candidate, entry_mode, exit_mode)
            if trade is not None:
                trades.append(trade)
            if entry_mode == "tail":
                observational_trade = _closed_trade(
                    candidate,
                    entry_mode,
                    exit_mode,
                    allow_unverifiable_tail=True,
                )
                if observational_trade is not None:
                    observational_trades.append(observational_trade)

    daily_results, total_return, max_drawdown = _signal_daily_equity(trades)
    summary = _summary(
        orders,
        trades,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
    )
    phase_summaries = {
        phase: _subset_summary(orders, trades, phase=phase)
        for phase in ("warmup", "expanding_oos", "locked_holdout")
    }
    coverage = dict(rows[-1].get("coverage") or {}) if rows else history_repository.history_coverage(
        history_engine.HISTORY_STRATEGY_VERSION
    )
    report = {
        "status": "ready" if rows else "insufficient_data",
        "mode": "point_in_time_history_replay",
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "entry_mode": entry_mode,
        "entry_mode_label": _entry_mode_label(entry_mode),
        "exit_mode": exit_mode,
        "summary": summary,
        "phase_summaries": phase_summaries,
        "monthly_summaries": _monthly_summaries(orders, trades),
        "board_summaries": _board_summaries(orders, trades),
        "daily_results": daily_results,
        "orders": orders[-trade_limit:],
        "trades": trades[-trade_limit:],
        "coverage": {
            **coverage,
            "selected_start": rows[0]["trade_date"] if rows else None,
            "selected_end": rows[-1]["trade_date"] if rows else None,
            "selected_trade_days": len(rows),
            "strict_snapshot_orders": 0,
            "historical_proxy_orders": len(orders),
        },
        "costs": {
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.0005,
            "slippage_bps_each_side": 10.0,
            "total_round_trip_cost_pct": 0.31,
        },
        "limitations": [
            "全历史使用当前仍在股票池中的主板股票，存在退市与历史ST状态缺失造成的幸存者偏差。",
            "扫板和尾盘只有日线触板/收盘封板代理，不代表盘口队列真实成交。",
            "相似样本只使用结果成熟日早于信号日的数据；最终120日为锁定留出集。",
        ],
    }
    if entry_mode == "tail":
        _, observational_return, observational_drawdown = _signal_daily_equity(observational_trades)
        report["observational_proxy"] = {
            "label": "假设尾盘涨停价可成交",
            "execution_confidence": "daily_close_proxy_unverifiable",
            "summary": _summary(
                orders,
                observational_trades,
                total_return_pct=observational_return,
                max_drawdown_pct=observational_drawdown,
            ),
            "phase_summaries": {
                phase: _subset_summary(orders, observational_trades, phase=phase)
                for phase in ("warmup", "expanding_oos", "locked_holdout")
            },
        }
    return report


def get_history_factor_audit(
    start: date | None,
    end: date | None,
    entry_mode: str,
    exit_mode: str = "next_open",
) -> dict[str, object]:
    rows = history_repository.load_history_range(
        history_engine.HISTORY_STRATEGY_VERSION,
        start,
        end,
    )
    report = factor_audit.build_history_factor_audit(
        rows,
        entry_mode=entry_mode,
        exit_mode=exit_mode,
    )
    return {
        **report,
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
    }


def get_history_model_report(
    start: date | None,
    end: date | None,
    entry_mode: str,
    exit_mode: str = "next_open",
    *,
    board_lane: str | None = None,
) -> dict[str, object]:
    if entry_mode not in history_engine.ENTRY_MODES:
        raise ValueError(f"unsupported entry mode: {entry_mode}")
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    if board_lane is not None and board_lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {board_lane}")
    cache_key = (
        f"{history_engine.HISTORY_STRATEGY_VERSION}:{start}:{end}:"
        f"{entry_mode}:{exit_mode}:{board_lane}:{walk_forward_model.MODEL_VERSION}"
    )

    def load() -> dict[str, object]:
        rows = history_repository.load_history_range(
            history_engine.HISTORY_STRATEGY_VERSION,
            None,
            end,
        )
        return walk_forward_model.build_walk_forward_model_report(
            rows,
            entry_mode=entry_mode,
            exit_mode=exit_mode,
            evaluation_start=start,
            evaluation_end=end,
            board_lane=board_lane,
        )

    return _MODEL_REPORT_CACHE.get_or_set(cache_key, 3600, load)


def _background_rebuild() -> None:
    try:
        rebuild_history_sync()
    except Exception as exc:  # noqa: BLE001
        _set_build_state(
            status="failed",
            error={"type": exc.__class__.__name__, "message": str(exc)},
            finished_at=_utc_now(),
        )


def _selected_lane_candidates(
    day: Mapping[str, object],
    lane: str | None,
) -> list[dict[str, object]]:
    portfolio = day.get("lane_portfolio")
    portfolio = portfolio if isinstance(portfolio, Mapping) else {}
    selected = portfolio.get("selected")
    if not isinstance(selected, list):
        return []
    return [
        dict(candidate)
        for candidate in selected
        if isinstance(candidate, Mapping)
        and (lane is None or candidate.get("lane") == lane)
    ]


def _selected_history_orders(
    rows: Sequence[Mapping[str, object]],
    lane: str | None,
) -> list[dict[str, object]]:
    orders: list[dict[str, object]] = []
    for day in rows:
        phase = str(day.get("validation_phase") or "unknown")
        orders.extend(
            {**candidate, "validation_phase": phase}
            for candidate in _selected_lane_candidates(day, lane)
        )
    return orders


def _simulate_account(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    exit_mode: str,
    config: cash_backtest.CashBacktestConfig,
) -> dict[str, object]:
    return cash_backtest.simulate_limit_up_account(
        orders,
        bars,
        trade_dates,
        exit_mode,
        config,
    )


def _account_market_data(
    rows: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[date]]:
    trade_dates = {
        parsed
        for row in rows
        if (parsed := _optional_date(row.get("trade_date"))) is not None
    }
    if not orders:
        return [], sorted(trade_dates)

    entry_dates = [
        parsed
        for order in orders
        if (parsed := _optional_date(order.get("entry_date") or order.get("signal_date")))
        is not None
    ]
    result_dates = [
        parsed
        for order in orders
        if (parsed := _optional_date(order.get("result_date") or order.get("exit_date")))
        is not None
    ]
    coverage_dates = [
        parsed
        for row in rows[-1:]
        for key in ("reliable_end", "persisted_end")
        if (parsed := _optional_date((row.get("coverage") or {}).get(key))) is not None
    ]
    if not entry_dates:
        return _candidate_account_bars(orders), sorted(trade_dates)
    load_start = min(entry_dates)
    load_end = max([*entry_dates, *result_dates, *coverage_dates])
    symbols = [str(order.get("vt_symbol") or "") for order in orders]
    loaded = history_repository.load_account_daily_bars(symbols, load_start, load_end)
    indexed = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")[:10]): dict(bar)
        for bar in _candidate_account_bars(orders)
    }
    for bar in loaded:
        indexed[
            (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")[:10])
        ] = dict(bar)
    bars = sorted(
        indexed.values(),
        key=lambda bar: (str(bar.get("trade_date") or ""), str(bar.get("vt_symbol") or "")),
    )
    trade_dates.update(entry_dates)
    trade_dates.update(result_dates)
    trade_dates.update(
        parsed
        for bar in bars
        if (parsed := _optional_date(bar.get("trade_date"))) is not None
    )
    return bars, sorted(trade_dates)


def _candidate_account_bars(
    orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    indexed: dict[tuple[str, str], dict[str, object]] = {}
    for order in orders:
        symbol = str(order.get("vt_symbol") or "")
        entry_date = str(order.get("entry_date") or order.get("signal_date") or "")[:10]
        result_date = str(order.get("result_date") or order.get("exit_date") or "")[:10]
        entry_price = _number(order.get("entry_price"))
        outcome = order.get("outcome")
        outcome = outcome if isinstance(outcome, Mapping) else {}
        entry_close = _number(outcome.get("entry_day_close_price")) or entry_price
        if symbol and entry_date and entry_price is not None and entry_close is not None:
            indexed[(symbol, entry_date)] = _price_bar(
                symbol,
                entry_date,
                entry_price,
                entry_close,
            )
        next_open = _number(outcome.get("next_open_price"))
        next_close = _number(outcome.get("next_close_price"))
        result_open = next_open or next_close
        result_close = next_close or next_open
        if symbol and result_date and result_open is not None and result_close is not None:
            indexed[(symbol, result_date)] = _price_bar(
                symbol,
                result_date,
                result_open,
                result_close,
            )
    return list(indexed.values())


def _price_bar(
    vt_symbol: str,
    trade_date: str,
    open_price: float,
    close_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": open_price,
        "high_price": max(open_price, close_price),
        "low_price": min(open_price, close_price),
        "close_price": close_price,
    }


def _safe_lane_validation_status(
    lane: str,
    exit_mode: str,
) -> dict[str, object]:
    try:
        return get_lane_validation_status(lane, exit_mode)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "status": "unavailable",
            "checks": [],
            "reason": f"战法验证暂不可用：{exc.__class__.__name__}",
        }


def _lane_validation_from_rows(
    rows: Sequence[Mapping[str, object]],
    lane: str,
    exit_mode: str,
    *,
    bars: Sequence[Mapping[str, object]] | None = None,
    trade_dates: Sequence[date] | None = None,
) -> dict[str, object]:
    orders = _selected_history_orders(rows, lane)
    if bars is None or trade_dates is None:
        bars, trade_dates = _account_market_data(rows, orders)
    config = cash_backtest.CashBacktestConfig()
    account = _simulate_account(orders, bars, trade_dates, exit_mode, config)
    phase_summaries = {
        phase: _simulate_account(
            [order for order in orders if order.get("validation_phase") == phase],
            bars,
            trade_dates,
            exit_mode,
            config,
        )["execution_summary"]
        for phase in ("warmup", "expanding_oos", "locked_holdout")
    }
    forward_summary = _simulate_account(
        [
            order
            for order in orders
            if _trade_is_after_freeze(order, LANE_RULE_FREEZE_DATE)
        ],
        bars,
        trade_dates,
        exit_mode,
        config,
    )["execution_summary"]
    validation = _lane_validation(lane, phase_summaries, forward_summary)
    validation.update(
        {
            "reason": _lane_validation_reason(validation),
            "summary": account["execution_summary"],
            "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        }
    )
    return validation


def _lane_validation_reason(validation: Mapping[str, object]) -> str:
    if validation.get("passed") is True:
        return "滚动样本外与锁定留出均已通过"
    checks = validation.get("checks")
    checks = checks if isinstance(checks, Sequence) else []
    details: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping) or check.get("passed") is True:
            continue
        phase = str(check.get("phase") or "")
        label = {
            "expanding_oos": "滚动样本外",
            "locked_holdout": "锁定留出",
            "post_freeze_forward": "规则冻结后前向",
        }.get(phase, phase or "验证段")
        trade_count = int(check.get("trade_count") or 0)
        win_rate = _number(check.get("win_rate"))
        total_return = _number(check.get("total_return_pct"))
        if trade_count < 30:
            details.append(f"{label}仅{trade_count}笔")
        elif win_rate is None or win_rate < 50:
            details.append(f"{label}胜率未达50%")
        elif total_return is None or total_return <= 0:
            details.append(f"{label}收益未转正")
        else:
            details.append(f"{label}回撤未达标")
    return "、".join(details) or "尚未通过样本外验证"


def _ledger_trade(
    candidate: Mapping[str, object],
    exit_mode: str,
) -> dict[str, object]:
    outcome = candidate.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    return_field = "next_open_return_pct" if exit_mode == "next_open" else "next_close_return_pct"
    price_field = "next_open_price" if exit_mode == "next_open" else "next_close_price"
    return_pct = _number(outcome.get(return_field))
    result_status = "closed" if return_pct is not None else "awaiting_d1_bar"
    return {
        "lane": candidate.get("lane"),
        "lane_label": candidate.get("lane_label"),
        "vt_symbol": candidate.get("vt_symbol"),
        "name": candidate.get("name"),
        "industry_id": candidate.get("industry_id"),
        "industry_name": candidate.get("industry_name"),
        "action": candidate.get("action"),
        "signal_kind": candidate.get("signal_kind"),
        "decision": candidate.get("decision"),
        "buy_date": candidate.get("entry_date") or candidate.get("signal_date"),
        "buy_time": candidate.get("buy_time") or candidate.get("signal_time"),
        "buy_price": _number(candidate.get("entry_price")),
        "sell_date": candidate.get("result_date"),
        "sell_time": candidate.get(
            "sell_time_next_open" if exit_mode == "next_open" else "sell_time_next_close"
        ),
        "sell_price": _number(outcome.get(price_field)),
        "return_pct": round(return_pct, 4) if return_pct is not None else None,
        "result_status": result_status,
        "is_win": return_pct > 0 if return_pct is not None else None,
        "is_hard_loss": return_pct <= -5 if return_pct is not None else None,
        "d1_outcome": _lane_d1_outcome(return_pct, bool(outcome.get("sealed"))),
        "d_board_status": (
            "sealed"
            if outcome.get("sealed")
            else "failed"
            if outcome.get("touched")
            else "no_limit"
        ),
        "execution_confidence": candidate.get("execution_confidence"),
        "source_mode": candidate.get("source_mode"),
        "rank_score": candidate.get("rank_score"),
        "two_to_three_quality_tier": candidate.get("two_to_three_quality_tier"),
        "two_to_three_risk_count": candidate.get("two_to_three_risk_count"),
        "two_to_three_risk_flags": candidate.get("two_to_three_risk_flags") or [],
        "favorable_factors": candidate.get("favorable_factors") or [],
        "blockers": candidate.get("blockers") or [],
        "financial_risk": candidate.get("financial_risk") or {},
        "prior_board": candidate.get("prior_board"),
        "path_prefix": candidate.get("path_prefix"),
        "outcome": dict(outcome),
    }


def _lane_closed_trade(
    candidate: Mapping[str, object],
    exit_mode: str,
) -> dict[str, object] | None:
    ledger = _ledger_trade(candidate, exit_mode)
    return_pct = _number(ledger.get("return_pct"))
    if return_pct is None:
        return None
    return {
        **dict(candidate),
        **ledger,
        "signal_date": candidate.get("entry_date") or candidate.get("signal_date"),
        "entry_date": candidate.get("entry_date") or candidate.get("signal_date"),
        "exit_date": candidate.get("result_date"),
        "entry_price": _number(candidate.get("entry_price")),
        "exit_price": ledger.get("sell_price"),
        "return_pct": return_pct,
    }


def _lane_d1_outcome(return_pct: float | None, sealed: bool) -> str:
    if return_pct is None:
        return "awaiting_d1_bar"
    if return_pct >= 9:
        return "continuation_limit_up" if sealed else "next_limit_up_after_failed_board"
    if return_pct > 0:
        return "d1_premium"
    if return_pct <= -5:
        return "direct_breakdown"
    return "no_premium"


def _segment_summary(
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
    segment: str,
) -> dict[str, object]:
    segment_orders = [row for row in orders if row.get("source_mode") == segment]
    segment_trades = [row for row in trades if row.get("source_mode") == segment]
    _, total_return, max_drawdown = _signal_daily_equity(segment_trades)
    return _summary(
        segment_orders,
        segment_trades,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
    )


def _lane_validation(
    lane: str,
    phase_summaries: Mapping[str, Mapping[str, object]],
    forward_summary: Mapping[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for phase in ("expanding_oos", "locked_holdout"):
        summary = phase_summaries.get(phase) or {}
        checks.append(_validation_check(phase, summary))
    checks.append(_validation_check("post_freeze_forward", forward_summary))
    passed = bool(checks and all(check["passed"] for check in checks))
    return {
        "passed": passed,
        "status": "validated" if passed else "research_only",
        "lane": lane,
        "checks": checks,
        "requirements": {
            "minimum_trades_each_phase": 30,
            "minimum_win_rate": 50,
            "minimum_total_return_pct": 0,
            "maximum_drawdown_pct": -20,
            "rule_freeze_date": LANE_RULE_FREEZE_DATE.isoformat(),
            "minimum_post_freeze_trades": 30,
        },
    }


def _validation_check(
    phase: str,
    summary: Mapping[str, object],
) -> dict[str, object]:
    trade_count = int(summary.get("trade_count") or 0)
    win_rate = _number(summary.get("win_rate"))
    total_return = _number(summary.get("total_return_pct"))
    max_drawdown = _number(summary.get("max_drawdown_pct"))
    passed = bool(
        trade_count >= 30
        and win_rate is not None
        and win_rate >= 50
        and total_return is not None
        and total_return > 0
        and max_drawdown is not None
        and max_drawdown >= -20
    )
    return {
        "phase": phase,
        "passed": passed,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "total_return_pct": total_return,
        "max_drawdown_pct": max_drawdown,
    }


def _trade_is_after_freeze(
    trade: Mapping[str, object],
    freeze_date: date,
) -> bool:
    value = str(trade.get("signal_date") or trade.get("entry_date") or "")[:10]
    try:
        return date.fromisoformat(value) > freeze_date
    except ValueError:
        return False


def _closed_trade(
    candidate: Mapping[str, object],
    entry_mode: str,
    exit_mode: str,
    *,
    allow_unverifiable_tail: bool = False,
) -> dict[str, object] | None:
    outcome = candidate.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    action = str(candidate.get("action") or "")
    executable = False
    if entry_mode == "auction":
        executable = action == "auction_buy"
    elif entry_mode == "sweep":
        executable = action == "wait_sweep" and bool(outcome.get("touched"))
    elif entry_mode == "tail":
        executable = (
            allow_unverifiable_tail
            and action == "wait_tail"
            and bool(outcome.get("sealed"))
        )
    elif entry_mode == "next_auction":
        executable = action == "next_auction"
    return_field = "next_open_return_pct" if exit_mode == "next_open" else "next_close_return_pct"
    return_pct = _number(outcome.get(return_field))
    if not executable or return_pct is None:
        return None
    exit_field = "next_open_price" if exit_mode == "next_open" else "next_close_price"
    return {
        **dict(candidate),
        "return_pct": round(return_pct, 4),
        "exit_price": _number(outcome.get(exit_field)),
        "exit_date": candidate.get("result_date"),
        "is_win": return_pct > 0,
        "is_hard_loss": return_pct <= -5,
    }


def _summary(
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
    *,
    total_return_pct: float,
    max_drawdown_pct: float,
) -> dict[str, object]:
    returns = [float(trade["return_pct"]) for trade in trades]
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    return {
        "signal_count": len(orders),
        "filled_count": len(trades),
        "fill_rate": round(len(trades) / len(orders) * 100, 4) if orders else None,
        "trade_count": len(trades),
        "win_count": sum(value > 0 for value in returns),
        "win_rate": round(sum(value > 0 for value in returns) / len(returns) * 100, 4) if returns else None,
        "average_return_pct": round(mean(returns), 4) if returns else None,
        "median_return_pct": round(median(returns), 4) if returns else None,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "hard_loss_count": sum(value <= -5 for value in returns),
        "hard_loss_rate": round(sum(value <= -5 for value in returns) / len(returns) * 100, 4) if returns else None,
        "seal_rate": _seal_rate(orders),
        "profit_factor": round(gains / losses, 4) if losses else None,
        **_portfolio_scale_summary(trades),
    }


def _portfolio_scale_summary(
    trades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not trades:
        return {
            "trade_day_count": 0,
            "average_trades_per_day": 0.0,
            "max_trades_per_day": 0,
            "max_industry_concentration_pct": None,
        }

    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for trade in trades:
        entry_date = str(
            trade.get("entry_date")
            or trade.get("signal_date")
            or trade.get("buy_date")
            or "unknown"
        )
        grouped[entry_date].append(trade)

    concentrations: list[float] = []
    for day_trades in grouped.values():
        industry_counts: dict[str, int] = defaultdict(int)
        for trade in day_trades:
            industry = str(
                trade.get("industry_id") or trade.get("industry_name") or ""
            ).strip()
            if industry:
                industry_counts[industry] += 1
        if industry_counts:
            concentrations.append(
                max(industry_counts.values()) / len(day_trades) * 100
            )

    trade_day_count = len(grouped)
    return {
        "trade_day_count": trade_day_count,
        "average_trades_per_day": round(len(trades) / trade_day_count, 4),
        "max_trades_per_day": max(len(rows) for rows in grouped.values()),
        "max_industry_concentration_pct": (
            round(max(concentrations), 4) if concentrations else None
        ),
    }


def _subset_summary(
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
    *,
    phase: str,
) -> dict[str, object]:
    subset_orders = [row for row in orders if row.get("validation_phase") == phase]
    subset_trades = [row for row in trades if row.get("validation_phase") == phase]
    _, total_return, max_drawdown = _signal_daily_equity(subset_trades)
    return _summary(
        subset_orders,
        subset_trades,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
    )


def _monthly_summaries(
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    months = sorted({str(row.get("signal_date") or "")[:7] for row in orders if row.get("signal_date")})
    result = []
    for month in months:
        month_orders = [row for row in orders if str(row.get("signal_date") or "").startswith(month)]
        month_trades = [row for row in trades if str(row.get("signal_date") or "").startswith(month)]
        _, total_return, max_drawdown = _signal_daily_equity(month_trades)
        result.append(
            {
                "month": month,
                **_summary(
                    month_orders,
                    month_trades,
                    total_return_pct=total_return,
                    max_drawdown_pct=max_drawdown,
                ),
            }
        )
    return result


def _board_summaries(
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    boards = sorted({int(row.get("target_board") or 1) for row in orders})
    result = []
    for board in boards:
        board_orders = [row for row in orders if int(row.get("target_board") or 1) == board]
        board_trades = [row for row in trades if int(row.get("target_board") or 1) == board]
        _, total_return, max_drawdown = _signal_daily_equity(board_trades)
        result.append(
            {
                "target_board": board,
                **_summary(
                    board_orders,
                    board_trades,
                    total_return_pct=total_return,
                    max_drawdown_pct=max_drawdown,
                ),
            }
        )
    return result


def _signal_daily_equity(
    trades: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], float, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get("result_date") or trade.get("exit_date") or "")].append(
            float(trade["return_pct"])
        )
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    rows = []
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


def _seal_rate(orders: Sequence[Mapping[str, object]]) -> float | None:
    known = []
    for order in orders:
        outcome = order.get("outcome")
        if isinstance(outcome, Mapping) and outcome.get("sealed") is not None:
            known.append(bool(outcome.get("sealed")))
    return round(sum(known) / len(known) * 100, 4) if known else None


def _entry_mode_label(entry_mode: str) -> str:
    return {
        "auction": "当日竞价·首板",
        "sweep": "盘中扫首板/回封",
        "tail": "尾盘确认",
        "next_auction": "明早竞价·二三板",
    }[entry_mode]


def _set_build_state(**values: object) -> None:
    with _BUILD_LOCK:
        _BUILD_STATE.update(values)
        _BUILD_STATE["strategy_version"] = history_engine.HISTORY_STRATEGY_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
