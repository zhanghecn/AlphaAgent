"""Build, persist, and report full-history point-in-time limit-up replays."""

from __future__ import annotations

import ctypes
import gc
import logging
import threading
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import copy, deepcopy
from datetime import date, datetime, time, timezone
from math import isnan
from statistics import mean, median
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.market.cache import TTLCache
from alphaagent.server.services.limit_up import (
    cash_backtest,
    core_quality,
    drawdown_diagnostics,
    factor_audit,
    first_board_dual_lane,
    first_board_stock_gene_research,
    history_engine,
    history_repository,
    lane_repository,
    live_evidence,
    live_repository,
    scheduled_execution,
    sector_warmup_research,
    walk_forward_model,
)
from alphaagent.server.services.limit_up.lane_research import BOARD_LANES


logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_BUILD_LOCK = threading.RLock()
_BUILD_THREAD: threading.Thread | None = None
_BACKTEST_WARM_LOCK = threading.RLock()
_BACKTEST_WARM_THREAD: threading.Thread | None = None
_MODEL_REPORT_CACHE = TTLCache(max_items=16)
_LANE_VALIDATION_CACHE = TTLCache(max_items=16)
_BACKTEST_REPORT_CACHE = TTLCache(max_items=32, copier=copy)
_SECTOR_WARMUP_REPORT_CACHE = TTLCache(max_items=16)
_BUILD_STATE: dict[str, object] = {
    "status": "idle",
    "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
}
LANE_RULE_FREEZE_DATE = date(2026, 7, 12)
BACKTEST_SCOPES = ("portfolio", *BOARD_LANES)
PORTFOLIO_EXECUTION_LANES = scheduled_execution.PRODUCT_EXECUTION_LANES
SCHEDULED_VARIANT_LANES = {
    "first_board": ("first_board",),
    "first_board_two_to_three": ("first_board", "two_to_three"),
    "first_board_high_board": ("first_board", "high_board"),
    "first_board_all_relays": ("first_board", "two_to_three", "high_board"),
}
SECTOR_WARMUP_CASH_VARIANTS = (
    ("baseline", "baseline", "当前首板 Top1"),
    ("warmup_gate", "warmup_gate", "原预热准入门"),
    ("continuation_quality", "warmup_quality_gate", "延续质量门"),
)


def _history_cache_revision() -> str:
    """Return a cross-process cache revision for the persisted history ledger."""

    try:
        updated_at = history_repository.history_ledger_updated_at(
            history_engine.HISTORY_STRATEGY_VERSION
        )
    except Exception:  # noqa: BLE001
        return "ledger-unavailable"
    return updated_at.isoformat() if updated_at is not None else "ledger-empty"


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
        try:
            return _rebuild_history_locked()
        finally:
            _release_rebuild_memory()


def _rebuild_history_locked() -> dict[str, object]:
    _set_build_state(status="building", started_at=_utc_now(), error=None)
    frame, coverage = history_repository.load_reliable_history_frame()
    reliable_start = date.fromisoformat(str(coverage["reliable_start"]))
    reliable_end = date.fromisoformat(str(coverage["reliable_end"]))
    event_evidence, financial_index, lane_coverage = (
        lane_repository.load_lane_research_data(
            reliable_start,
            reliable_end,
        )
    )
    coverage = {**coverage, **lane_coverage}
    frame = history_engine.build_daily_feature_frame(frame, copy_frame=False)
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
    _BACKTEST_REPORT_CACHE.clear()
    _SECTOR_WARMUP_REPORT_CACHE.clear()
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


def _release_rebuild_memory() -> None:
    gc.collect()
    try:
        malloc_trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return
    malloc_trim.argtypes = [ctypes.c_size_t]
    malloc_trim.restype = ctypes.c_int
    malloc_trim(0)


def refresh_history_if_needed(
    latest_reliable_date: date | None,
    *,
    force: bool = False,
) -> dict[str, object]:
    """Rebuild after the calendar advances or historical inputs change."""

    with _BUILD_LOCK:
        coverage = history_repository.history_coverage(
            history_engine.HISTORY_STRATEGY_VERSION
        )
        persisted_end = _optional_date(coverage.get("persisted_end"))
        if latest_reliable_date is None:
            return {
                "status": "skipped",
                "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
                "persisted_days": int(coverage.get("persisted_days") or 0),
                "persisted_end": persisted_end.isoformat() if persisted_end else None,
                "latest_reliable_date": (
                    latest_reliable_date.isoformat() if latest_reliable_date else None
                ),
            }

        rebuild_for_input_change = force
        ledger_is_current = (
            persisted_end is not None and persisted_end >= latest_reliable_date
        )
        if ledger_is_current and not rebuild_for_input_change:
            rebuild_for_input_change = (
                history_repository.history_inputs_newer_than_ledger(
                    history_engine.HISTORY_STRATEGY_VERSION
                )
            )
        if ledger_is_current and not rebuild_for_input_change:
            return {
                "status": "skipped",
                "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
                "persisted_days": int(coverage.get("persisted_days") or 0),
                "persisted_end": persisted_end.isoformat() if persisted_end else None,
                "latest_reliable_date": latest_reliable_date.isoformat(),
            }

        result = rebuild_history_sync()
        rebuilt_end = _optional_date(result.get("end"))
        if rebuilt_end is None or rebuilt_end < latest_reliable_date:
            raise RuntimeError(
                "limit-up history rebuild did not reach the latest reliable trade date"
            )
        return {
            **result,
            "forced": rebuild_for_input_change,
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


def get_sector_warmup_research(
    start: date | None,
    end: date | None,
) -> dict[str, object]:
    cache_key = (
        f"{history_engine.HISTORY_STRATEGY_VERSION}:"
        f"{_history_cache_revision()}:"
        f"{sector_warmup_research.RESEARCH_VERSION}:{start}:{end}"
    )

    def load() -> dict[str, object]:
        rows = history_repository.load_history_range(
            history_engine.HISTORY_STRATEGY_VERSION,
            start,
            end,
        )
        data_coverage = history_repository.load_sector_warmup_data_coverage()
        report = sector_warmup_research.build_sector_warmup_research_report(
            rows,
            start=start,
            end=end,
            data_coverage=data_coverage,
        )
        selected = sector_warmup_research.select_sector_warmup_variant_trades(
            rows,
            start=start,
            end=end,
        )
        return _sector_warmup_static_bundle(report, rows, selected)

    bundle = _SECTOR_WARMUP_REPORT_CACHE.get_or_set(cache_key, 21_600, load)
    return _sector_warmup_report_with_forward_rotation(bundle, start=start, end=end)


def _sector_warmup_static_bundle(
    report: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
    selected: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    config = cash_backtest.CashBacktestConfig()
    orders_by_variant = {
        variant: [
            dict(order)
            for order in selected.get(source_variant, ())
            if _cash_signal_ready(order)
        ]
        for variant, source_variant, _ in SECTOR_WARMUP_CASH_VARIANTS
    }
    all_orders = [
        order
        for orders in orders_by_variant.values()
        for order in orders
    ]
    bars, trade_dates = _account_market_data(rows, all_orders)
    accounts = {
        variant: _simulate_account(
            orders_by_variant[variant],
            bars,
            trade_dates,
            "next_open",
            config,
        )
        for variant, _, _ in SECTOR_WARMUP_CASH_VARIANTS
    }
    comparisons = [
        _sector_cash_comparison(variant, label, accounts[variant])
        for variant, _, label in SECTOR_WARMUP_CASH_VARIANTS
    ]
    return {
        "report": dict(report),
        "orders_by_variant": orders_by_variant,
        "bars": bars,
        "trade_dates": trade_dates,
        "accounts": accounts,
        "comparisons": comparisons,
    }


def _sector_warmup_report_with_forward_rotation(
    bundle: Mapping[str, object],
    *,
    start: date | None,
    end: date | None,
) -> dict[str, object]:
    report = deepcopy(bundle["report"])
    rotation = _load_forward_rotation(start=start, end=end)
    trigger_signals = [
        dict(signal) for signal in rotation.pop("trigger_signals", [])
    ]
    try:
        matured, pending_count, rotation_bars, rotation_dates = (
            _mature_rotation_signals(trigger_signals)
        )
    except Exception as exc:  # noqa: BLE001
        matured, pending_count, rotation_bars, rotation_dates = (
            [],
            len(trigger_signals),
            [],
            [],
        )
        rotation["status"] = "unavailable"
        rotation["unavailable_reason"] = (
            f"rotation_outcome_load_failed:{exc.__class__.__name__}"
        )
    continuation_orders = [
        dict(order)
        for order in bundle["orders_by_variant"]["continuation_quality"]
    ]
    continuation_account = bundle["accounts"]["continuation_quality"]
    if matured:
        dual_orders = _deduplicate_signals([*continuation_orders, *matured])
        dual_bars = _merge_account_bars(bundle["bars"], rotation_bars)
        dual_dates = sorted({*bundle["trade_dates"], *rotation_dates})
        dual_account = _simulate_account(
            dual_orders,
            dual_bars,
            dual_dates,
            "next_open",
            cash_backtest.CashBacktestConfig(),
        )
    else:
        dual_account = deepcopy(continuation_account)

    rotation.update(
        {
            "pending_trade_count": pending_count,
            "closed_trade_count": len(matured),
            "account_effect": "none_until_d1_closed" if not matured else "included",
        }
    )
    static_comparisons = deepcopy(bundle["comparisons"])
    static_comparisons.append(
        _sector_cash_comparison("dual_lane", "延续 + 日内轮动", dual_account)
    )
    report["cash_accounts"] = {
        "execution_version": cash_backtest.ACCOUNT_EXECUTION_VERSION,
        "exit_mode": "next_open",
        "account_config": dict(dual_account["account_config"]),
        "comparisons": static_comparisons,
    }
    report["rotation_forward"] = rotation
    return report


def _load_forward_rotation(
    *,
    start: date | None,
    end: date | None,
) -> dict[str, object]:
    rotation_start = max(
        start or first_board_dual_lane.ROTATION_FORWARD_START,
        first_board_dual_lane.ROTATION_FORWARD_START,
    )
    if end is not None and end < rotation_start:
        return first_board_dual_lane.collect_rotation_forward_evidence(
            [],
            forward_start=rotation_start,
        )
    try:
        snapshots = live_repository.load_snapshots_between(rotation_start, end)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "forward_start_date": rotation_start.isoformat(),
            "historical_substitution": False,
            "snapshot_count": 0,
            "snapshot_day_count": 0,
            "evaluated_candidate_count": 0,
            "watch_count": 0,
            "missed_count": 0,
            "trigger_count": 0,
            "trigger_signals": [],
            "recent_observations": [],
            "unavailable_reason": f"snapshot_load_failed:{exc.__class__.__name__}",
        }
    return first_board_dual_lane.collect_rotation_forward_evidence(
        snapshots,
        forward_start=rotation_start,
    )


def _mature_rotation_signals(
    trigger_signals: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], int, list[dict[str, object]], list[date]]:
    if not trigger_signals:
        return [], 0, [], []
    calendar = [
        parsed
        for value in live_repository.list_daily_trade_dates()
        if (parsed := _optional_date(value)) is not None
    ]
    dated_signals: list[dict[str, object]] = []
    for raw in trigger_signals:
        signal = dict(raw)
        entry_date = _optional_date(signal.get("entry_date"))
        result_date = next(
            (trade_date for trade_date in calendar if entry_date and trade_date > entry_date),
            None,
        )
        if entry_date is not None and result_date is not None:
            signal["result_date"] = result_date.isoformat()
            dated_signals.append(signal)
    if not dated_signals:
        return [], len(trigger_signals), [], calendar

    entry_dates = [_optional_date(signal.get("entry_date")) for signal in dated_signals]
    result_dates = [_optional_date(signal.get("result_date")) for signal in dated_signals]
    load_start = min(value for value in entry_dates if value is not None)
    load_end = max(value for value in result_dates if value is not None)
    symbols = [str(signal.get("vt_symbol") or "") for signal in dated_signals]
    bars = history_repository.load_account_daily_bars(symbols, load_start, load_end)
    bar_index = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")[:10]): bar
        for bar in bars
    }
    matured: list[dict[str, object]] = []
    for signal in dated_signals:
        symbol = str(signal.get("vt_symbol") or "")
        entry_date = str(signal.get("entry_date") or "")[:10]
        result_date = str(signal.get("result_date") or "")[:10]
        entry_bar = bar_index.get((symbol, entry_date))
        result_bar = bar_index.get((symbol, result_date))
        if entry_bar is None or result_bar is None:
            continue
        signal["outcome"] = {
            "entry_day_close_price": entry_bar.get("close_price"),
            "next_open_price": result_bar.get("open_price"),
            "next_close_price": result_bar.get("close_price"),
        }
        matured.append(signal)
    return matured, len(trigger_signals) - len(matured), bars, calendar


def _sector_cash_comparison(
    variant: str,
    label: str,
    account: Mapping[str, object],
) -> dict[str, object]:
    return {
        "variant": variant,
        "label": label,
        "summary": dict(account.get("execution_summary") or {}),
    }


def _deduplicate_signals(
    signals: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    unique: dict[tuple[str, str], dict[str, object]] = {}
    for signal in signals:
        key = (
            str(signal.get("entry_date") or signal.get("signal_date") or "")[:10],
            str(signal.get("vt_symbol") or ""),
        )
        unique.setdefault(key, dict(signal))
    return list(unique.values())


def _cash_signal_ready(signal: Mapping[str, object]) -> bool:
    return bool(
        signal.get("vt_symbol")
        and _optional_date(signal.get("entry_date") or signal.get("signal_date"))
        and _number(signal.get("entry_price"))
    )


def _merge_account_bars(
    left: Sequence[Mapping[str, object]],
    right: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    merged = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")[:10]): dict(bar)
        for bar in [*left, *right]
    }
    return sorted(
        merged.values(),
        key=lambda bar: (
            str(bar.get("trade_date") or ""),
            str(bar.get("vt_symbol") or ""),
        ),
    )


def start_backtest_cache_warmup() -> dict[str, object]:
    """Precompute default dynamic reports after a history rebuild."""

    global _BACKTEST_WARM_THREAD
    try:
        coverage = history_repository.history_coverage(
            history_engine.HISTORY_STRATEGY_VERSION
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "skipped",
            "reason": f"history_unavailable:{exc.__class__.__name__}",
        }
    if int(coverage.get("persisted_days") or 0) <= 0:
        return {"status": "skipped", "reason": "history_unavailable"}
    with _BACKTEST_WARM_LOCK:
        if _BACKTEST_WARM_THREAD is not None and _BACKTEST_WARM_THREAD.is_alive():
            return {"status": "running", "already_running": True}
        _BACKTEST_WARM_THREAD = threading.Thread(
            target=_warm_default_backtests,
            name="limit-up-backtest-warmup",
            daemon=True,
        )
        _BACKTEST_WARM_THREAD.start()
    return {"status": "started", "scopes": list(BACKTEST_SCOPES)}


def _warm_default_backtests() -> None:
    scopes = iter(BACKTEST_SCOPES)
    first_scope = next(scopes, None)
    if first_scope is not None:
        try:
            get_lane_history_backtest(
                None,
                None,
                lane=first_scope,
                exit_mode="dynamic",
            )
        except Exception:  # noqa: BLE001
            pass
    try:
        get_lane_validation_snapshot("dynamic")
    except Exception:  # noqa: BLE001
        pass
    for scope in scopes:
        try:
            get_lane_history_backtest(None, None, lane=scope, exit_mode="dynamic")
        except Exception:  # noqa: BLE001
            continue


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
    exit_mode: str = "dynamic",
) -> dict[str, object]:
    if lane is not None and lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {lane}")
    if exit_mode not in cash_backtest.SUPPORTED_EXIT_MODES:
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
    if lane is None:
        return _scheduled_history_ledger(trade_date, payload)
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


def _scheduled_history_ledger(
    trade_date: date,
    payload: Mapping[str, object],
) -> dict[str, object]:
    report = get_scheduled_history_backtest(None, None, trade_limit=None)
    date_text = trade_date.isoformat()
    trades = [
        dict(trade)
        for trade in report.get("trades") or []
        if isinstance(trade, Mapping)
        and str(trade.get("buy_date") or trade.get("entry_date") or "")[:10]
        == date_text
    ]
    buy_orders = [
        order
        for order in report.get("orders") or []
        if isinstance(order, Mapping)
        and order.get("side") == "BUY"
        and str(order.get("trade_date") or "")[:10] == date_text
    ]
    return {
        "status": "ready",
        "trade_date": date_text,
        "strategy_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
        "validation_phase": (
            "earlier_history"
            if trade_date < scheduled_execution.RESEARCH_SAMPLE_START
            else "design_sample"
            if trade_date < scheduled_execution.VALIDATION_START
            else "time_validation"
            if trade_date <= scheduled_execution.RULE_FREEZE_DATE
            else "post_freeze_forward"
        ),
        "lane": None,
        "exit_mode": scheduled_execution.EXIT_MODE,
        "action": "normal" if trades else "empty",
        "candidate_count": len(buy_orders),
        "selected_count": len(trades),
        "observation_count": 0,
        "trades": trades,
        "observations": [],
        "validation": report.get("validation"),
        "lane_validations": {},
        "market_context": payload.get("market_context") or {},
        "data_quality": payload.get("data_quality") or {},
        "coverage": report.get("coverage") or {},
        "execution_schedule": report.get("execution_schedule") or {},
    }


def get_lane_validation_status(
    lane: str,
    exit_mode: str = "dynamic",
) -> dict[str, object]:
    """Return the cached out-of-sample gate used by ledger and live decisions."""

    if lane not in BOARD_LANES:
        raise ValueError(f"unsupported board lane: {lane}")
    if exit_mode not in cash_backtest.SUPPORTED_EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    return get_lane_validation_snapshot(exit_mode)[lane]


def get_lane_validation_snapshot(
    exit_mode: str = "dynamic",
) -> dict[str, dict[str, object]]:
    if exit_mode not in cash_backtest.SUPPORTED_EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    cache_key = (
        f"{history_engine.HISTORY_STRATEGY_VERSION}:"
        f"{_history_cache_revision()}:all:{exit_mode}"
    )

    def load() -> dict[str, dict[str, object]]:
        rows = history_repository.load_history_range(
            history_engine.HISTORY_STRATEGY_VERSION,
            None,
            None,
            False,
        )
        portfolio_orders = scheduled_execution.extract_scheduled_orders(
            rows,
            included_lanes=scheduled_execution.RESEARCH_EXECUTION_LANES,
        )
        bars, trade_dates = _account_market_data(rows, portfolio_orders)
        if exit_mode == "next_1430":
            bars, _ = _attach_scheduled_exit_prices(bars, portfolio_orders)
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
    exit_mode: str = "dynamic",
    trade_limit: int = 500,
    account_config: cash_backtest.CashBacktestConfig | None = None,
) -> dict[str, object]:
    if lane not in BACKTEST_SCOPES:
        raise ValueError(f"unsupported board lane: {lane}")
    if exit_mode not in cash_backtest.SUPPORTED_EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")
    if lane == "portfolio":
        return get_scheduled_history_backtest(
            start,
            end,
            trade_limit=trade_limit,
        )
    if exit_mode == "dynamic" and account_config is None:
        cache_key = (
            f"{history_engine.HISTORY_STRATEGY_VERSION}:"
            f"{_history_cache_revision()}:dynamic:{start}:{end}:"
            f"{lane}:{trade_limit}:{cash_backtest.ACCOUNT_EXECUTION_VERSION}"
        )
        return _BACKTEST_REPORT_CACHE.get_or_set(
            cache_key,
            21_600,
            lambda: get_lane_history_backtest(
                start,
                end,
                lane=lane,
                exit_mode=exit_mode,
                trade_limit=trade_limit,
                account_config=cash_backtest.CashBacktestConfig(
                    initial_cash=100_000,
                    max_positions=scheduled_execution.MAX_POSITIONS,
                ),
            ),
        )
    rows = history_repository.load_history_range(
        history_engine.HISTORY_STRATEGY_VERSION,
        start,
        end,
        False,
    )
    orders = scheduled_execution.extract_scheduled_orders(
        rows,
        included_lanes=(lane,),
    )
    bars, trade_dates = _account_market_data(rows, orders)
    exit_coverage: dict[str, int] = {}
    if exit_mode == "next_1430":
        bars, exit_coverage = _attach_scheduled_exit_prices(bars, orders)
        orders, exact_exit_audit = _filter_orders_with_exact_1430(orders, bars)
        exit_coverage.update(exact_exit_audit)
        signal_trades = _next_1430_signal_trades(orders, bars)
    else:
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
    config = account_config or cash_backtest.CashBacktestConfig(
        initial_cash=100_000,
        max_positions=scheduled_execution.MAX_POSITIONS,
    )
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
        "portfolio_policy": {
            "included_lanes": list(PORTFOLIO_EXECUTION_LANES) if lane == "portfolio" else [lane],
            "excluded_lanes": [],
            "selection_basis": "warmup_and_expanding_oos_frozen_before_holdout",
        },
        "exit_summary": (
            _scheduled_exit_summary(account["executed_trades"], exit_mode)
            if exit_mode == "next_1430"
            else _exit_summary(orders, exit_mode)
        ),
        "orders": account["orders"][-trade_limit:],
        "trades": [
            _compact_account_trade(trade)
            for trade in account["executed_trades"][-trade_limit:]
        ],
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
            **exit_coverage,
        },
        "costs": {
            **account["account_config"],
            "slippage_bps_each_side": config.slippage_bps,
        },
        "limitations": [
            "首板分时路径为三分钟代理，没有Tick/L2时不能证明排队成交。",
            "动态退出中的竞价价格使用日线开盘代理；历史逐日板块成员仍可能存在幸存者偏差。",
            "信号日等权收益仅作研究上界，主复利来自10万元共享现金账户。",
            "锁定留出结果不参与规则修改，未同时通过三段验证时保持研究状态。",
        ],
    }


def get_scheduled_history_backtest(
    start: date | None,
    end: date | None,
    *,
    trade_limit: int | None = 500,
) -> dict[str, object]:
    """Return the frozen two-position formal product account."""

    cache_key = (
        f"{history_engine.HISTORY_STRATEGY_VERSION}:"
        f"{_history_cache_revision()}:"
        f"{core_quality.PUBLIC_QUALITY_CONTRACT_VERSION}:"
        f"{scheduled_execution.SCHEDULED_EXECUTION_VERSION}:"
        f"{start}:{end}:{cash_backtest.ACCOUNT_EXECUTION_VERSION}"
    )
    report = _BACKTEST_REPORT_CACHE.get_or_set(
        cache_key,
        21_600,
        lambda: _build_scheduled_history_backtest(start, end),
    )
    return _limit_scheduled_report(report, trade_limit)


def _limit_scheduled_report(
    report: Mapping[str, object],
    trade_limit: int | None,
) -> dict[str, object]:
    if trade_limit is None:
        return dict(report)
    if trade_limit <= 0:
        raise ValueError("trade_limit must be positive")
    return {
        **report,
        "orders": list(report.get("orders") or [])[-trade_limit:],
        "trades": list(report.get("trades") or [])[-trade_limit:],
        "skipped_orders": list(report.get("skipped_orders") or [])[-trade_limit:],
    }


def _filtered_scheduled_orders(
    rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    extracted = scheduled_execution.extract_scheduled_orders(rows)
    enriched = (
        first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
            rows,
            extracted,
        )
    )
    enriched = _attach_historical_c_quality_evidence(enriched)
    return core_quality.filter_core_quality_qualified_orders(enriched)


def _attach_historical_c_quality_evidence(
    orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach signal-time concept diffusion, retaining its proxy evidence label."""

    copied = [
        {
            **dict(order),
            "trade_date": _order_date(order),
        }
        for order in orders
    ]
    dated_orders = [
        order for order in copied if _order_date(order) != date.min
    ]
    if not dated_orders:
        return copied
    start = min(_order_date(order) for order in dated_orders)
    end = max(_order_date(order) for order in dated_orders)
    try:
        from alphaagent.server.services.limit_up.capital_mainline_repository import (
            load_capital_mainline_inputs,
        )
        from alphaagent.server.services.limit_up.capital_mainline_research import (
            build_event_ledger,
            build_membership_contexts,
        )
        from alphaagent.server.services.limit_up.quality_no_trade_reverse import (
            attach_intraday_concept_diffusion_proxy,
        )

        inputs = load_capital_mainline_inputs(
            start,
            end,
            include_formal_candidates=False,
            include_stock_bars=False,
        )
        event_ledger = build_event_ledger(inputs)
        frame = attach_intraday_concept_diffusion_proxy(
            pd.DataFrame.from_records(copied),
            event_ledger.to_dict("records"),
            build_membership_contexts(inputs),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("historical C concept evidence unavailable: %s", exc)
        return [
            {
                **order,
                "c_concept_evidence_status": "unavailable",
            }
            for order in copied
        ]
    return [
        {
            **{
                key: None
                if isinstance(value, float) and isnan(value)
                else value
                for key, value in row.items()
            },
            "c_concept_evidence_status": core_quality.C_EVIDENCE_STATUS,
        }
        for row in frame.to_dict("records")
    ]


def _scheduled_order_identity(order: Mapping[str, object]) -> tuple[date, str, str]:
    return (
        _order_date(order),
        str(order.get("vt_symbol") or ""),
        str(order.get("lane") or ""),
    )


def _frozen_position_sizing_audit(
    *,
    rows: Sequence[Mapping[str, object]] | None = None,
    orders: Sequence[Mapping[str, object]] | None = None,
    bars: Sequence[Mapping[str, object]] | None = None,
    trade_dates: Sequence[date] | None = None,
) -> dict[str, object]:
    cache_key = (
        f"{history_engine.HISTORY_STRATEGY_VERSION}:"
        f"{_history_cache_revision()}:"
        f"{scheduled_execution.SCHEDULED_EXECUTION_VERSION}:"
        f"{cash_backtest.ACCOUNT_EXECUTION_VERSION}:frozen-position-sizing"
    )

    def load() -> dict[str, object]:
        if rows is not None:
            full_rows = list(rows)
        else:
            full_rows = history_repository.load_history_range(
                history_engine.HISTORY_STRATEGY_VERSION,
                None,
                None,
                False,
            )
        full_orders = (
            list(orders)
            if orders is not None
            else _filtered_scheduled_orders(full_rows)[0]
        )
        if bars is not None and trade_dates is not None:
            full_bars = list(bars)
            full_trade_dates = list(trade_dates)
        else:
            full_bars, full_trade_dates = _account_market_data(full_rows, full_orders)
        return _scheduled_position_sizing_audit(
            full_orders,
            full_bars,
            full_trade_dates,
        )

    return _BACKTEST_REPORT_CACHE.get_or_set(cache_key, 21_600, load)


def _build_scheduled_history_backtest(
    start: date | None,
    end: date | None,
) -> dict[str, object]:
    rows = history_repository.load_history_range(
        history_engine.HISTORY_STRATEGY_VERSION,
        start,
        end,
        False,
    )
    evidence_rows = (
        rows
        if start is None
        else history_repository.load_history_range(
            history_engine.HISTORY_STRATEGY_VERSION,
            None,
            end,
            False,
        )
    )
    extracted_variant_orders = {
        name: scheduled_execution.extract_scheduled_orders(
            rows,
            included_lanes=lanes,
        )
        for name, lanes in SCHEDULED_VARIANT_LANES.items()
    }
    variant_orders = {
        name: first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
            evidence_rows,
            orders,
        )
        for name, orders in extracted_variant_orders.items()
    }
    all_orders = {
        _scheduled_order_identity(order): dict(order)
        for orders in variant_orders.values()
        for order in orders
    }
    c_enriched_index = {
        _scheduled_order_identity(order): order
        for order in _attach_historical_c_quality_evidence(
            list(all_orders.values())
        )
    }
    variant_orders = {
        name: [
            {
                **order,
                **c_enriched_index.get(_scheduled_order_identity(order), {}),
            }
            for order in orders
        ]
        for name, orders in variant_orders.items()
    }
    variant_filter_results = {
        name: core_quality.filter_core_quality_qualified_orders(orders)
        for name, orders in variant_orders.items()
    }
    qualified_variant_orders = {
        name: filtered[0]
        for name, filtered in variant_filter_results.items()
    }
    union_orders = scheduled_execution.extract_scheduled_orders(
        rows,
        included_lanes=scheduled_execution.RESEARCH_EXECUTION_LANES,
    )
    bars, trade_dates = _account_market_data(rows, union_orders)
    config = cash_backtest.CashBacktestConfig(
        initial_cash=100_000,
        max_positions=scheduled_execution.MAX_POSITIONS,
    )
    double_cost_config = cash_backtest.CashBacktestConfig(
        initial_cash=100_000,
        max_positions=scheduled_execution.MAX_POSITIONS,
        commission_rate=config.commission_rate * 2,
        minimum_commission=config.minimum_commission * 2,
        stamp_tax_rate=config.stamp_tax_rate * 2,
        transfer_fee_rate=config.transfer_fee_rate * 2,
        slippage_bps=config.slippage_bps * 2,
    )
    variant_bundles = {
        name: _scheduled_variant_bundle(
            qualified_variant_orders[name],
            bars,
            trade_dates,
            config,
            double_cost_config,
        )
        for name in variant_orders
    }
    baseline = variant_bundles["first_board"]
    for name, bundle in variant_bundles.items():
        if name == "first_board":
            bundle["gate"] = {"passed": True, "checks": {"baseline": True}}
            continue
        bundle["gate"] = _relay_variant_gate(
            bundle["summary"],
            bundle["phase_summaries"]["time_validation"],
            bundle["double_cost_summary"],
            baseline["summary"],
            baseline["phase_summaries"]["time_validation"],
        )
    passing = [
        (name, bundle)
        for name, bundle in variant_bundles.items()
        if name != "first_board" and bool(bundle["gate"]["passed"])
    ]
    gate_selected_variant = (
        max(
            passing,
            key=lambda item: float(item[1]["summary"]["total_return_pct"]),
        )[0]
        if passing
        else "first_board"
    )
    configured_variant = _scheduled_variant_for_lanes(
        scheduled_execution.PRODUCT_EXECUTION_LANES
    )
    if configured_variant is None:
        raise ValueError("scheduled product lanes do not map to a replay variant")
    configuration_matches_gate = bool(
        variant_bundles[configured_variant]["gate"]["passed"]
    )
    selected_variant = configured_variant
    unfiltered_orders = variant_orders[selected_variant]
    unfiltered_bundle = _scheduled_variant_bundle(
        unfiltered_orders,
        bars,
        trade_dates,
        config,
        double_cost_config,
    )
    orders = qualified_variant_orders[selected_variant]
    core_quality_audit = dict(
        variant_filter_results[selected_variant][1]
    )
    selected_bundle = variant_bundles[selected_variant]
    account = selected_bundle["account"]
    summary = selected_bundle["summary"]
    phase_summaries = selected_bundle["phase_summaries"]
    double_cost_summary = selected_bundle["double_cost_summary"]
    recommendation_quality = _recommendation_quality_report(
        orders,
        bars,
        trade_dates,
        config,
    )
    unfiltered_recommendation_quality = _recommendation_quality_report(
        unfiltered_orders,
        bars,
        trade_dates,
        config,
    )
    exit_coverage = _scheduled_close_coverage(bars, orders)
    executed_trades = account["executed_trades"]
    signal_daily_results = recommendation_quality["daily_results"]
    signal_summary = recommendation_quality["summary"]
    position_sizing_audit = _frozen_position_sizing_audit(
        rows=rows if start is None and end is None else None,
        orders=orders if start is None and end is None else None,
        bars=bars if start is None and end is None else None,
        trade_dates=trade_dates if start is None and end is None else None,
    )
    latest_coverage = (
        dict(rows[-1].get("coverage") or {})
        if rows
        else history_repository.history_coverage(history_engine.HISTORY_STRATEGY_VERSION)
    )
    validation = _scheduled_validation(phase_summaries)
    selected_lanes = list(SCHEDULED_VARIANT_LANES[selected_variant])
    configured_lanes = list(scheduled_execution.PRODUCT_EXECUTION_LANES)
    diagnostic_orders, _ = _filter_orders_with_daily_close(orders, bars)
    first_board_exit_requests = [
        (str(trade.get("vt_symbol") or ""), result_date)
        for trade in executed_trades
        if str(trade.get("lane") or "") == "first_board"
        and (result_date := _optional_date(trade.get("exit_date"))) is not None
        and trade.get("vt_symbol")
    ]
    post_auction_prices = history_repository.load_account_post_auction_prices(
        first_board_exit_requests
    )
    auction_evidence = history_repository.load_account_auction_evidence(
        first_board_exit_requests
    )
    drawdown_report = drawdown_diagnostics.build_drawdown_diagnostics(
        orders=diagnostic_orders,
        bars=bars,
        trade_dates=trade_dates,
        baseline_account=account,
        auction_evidence=auction_evidence,
        post_auction_prices=post_auction_prices,
        config=config,
        design_start=scheduled_execution.RESEARCH_SAMPLE_START,
        validation_start=scheduled_execution.VALIDATION_START,
        freeze_date=scheduled_execution.RULE_FREEZE_DATE,
    )
    return {
        "status": "ready" if rows else "insufficient_data",
        "mode": "scheduled_unified_intraday_cash_replay",
        "strategy_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
        "history_strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "lane": "portfolio",
        "exit_mode": scheduled_execution.EXIT_MODE,
        "summary": summary,
        "execution_summary": summary,
        "signal_summary": signal_summary,
        "recommendation_quality": recommendation_quality,
        "phase_summaries": phase_summaries,
        "daily_results": account["equity_curve"],
        "signal_daily_results": signal_daily_results,
        "account_config": account["account_config"],
        "execution_version": account["execution_version"],
        "execution_assumptions": account["execution_assumptions"],
        "execution_schedule": {
            "entry_windows": [
                f"{window_start[:5]}-{window_end[:5]}"
                for window_start, window_end in scheduled_execution.ENTRY_WINDOWS
            ],
            "exit_time": scheduled_execution.EXIT_TIME[:5],
            "exit_rule": "D+1 official close",
            "target_position_pct": scheduled_execution.TARGET_POSITION_PCT,
            "max_snapshot_age_seconds": scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS,
        },
        "execution_comparability": {
            "status": "candidate_proxy_only",
            "live_equivalent": False,
            "candidate_proxy_signal_count": len(orders),
            "missing_evidence": [
                "intraday_market_repair_frames",
                "intraday_sector_fund_flow",
                "intraday_stock_fund_flow",
                "intraday_sector_expansion_frames",
                "tick_l2_queue",
            ],
            "reason": (
                "历史账户只验证信号时点结构硬门和时间覆盖；盘中市场、板块、资金"
                "与排队证据缺失，不能视为实盘等价回放。"
            ),
        },
        "portfolio_policy": {
            "included_lanes": selected_lanes,
            "excluded_lanes": [
                lane
                for lane in scheduled_execution.RESEARCH_EXECUTION_LANES
                if lane not in selected_lanes
            ],
            "selection_basis": (
                "complete_active_candidate_pools_in_event_order_then_"
                "core_abc_quality_gate"
            ),
            "candidate_source": "complete_active_lane_candidate_pools",
            "configured_lanes": configured_lanes,
            "configuration_matches_gate": configuration_matches_gate,
        },
        "core_quality_filter": {
            **core_quality.core_quality_filter_metadata(),
            "audit": core_quality_audit,
            "selected_summary": dict(summary),
            "unfiltered_summary": dict(unfiltered_bundle["summary"]),
            "selected_recommendation_quality": recommendation_quality,
            "unfiltered_recommendation_quality": (
                unfiltered_recommendation_quality
            ),
            "selected_phase_summaries": {
                phase: dict(phase_summary)
                for phase, phase_summary in phase_summaries.items()
            },
            "unfiltered_phase_summaries": {
                phase: dict(phase_summary)
                for phase, phase_summary in unfiltered_bundle[
                    "phase_summaries"
                ].items()
            },
            "selected_double_cost": dict(double_cost_summary),
            "unfiltered_double_cost": dict(
                unfiltered_bundle["double_cost_summary"]
            ),
            "delta": {
                "trade_count": int(summary.get("trade_count") or 0)
                - int(unfiltered_bundle["summary"].get("trade_count") or 0),
                "win_rate_pct_points": round(
                    (_number(summary.get("win_rate")) or 0.0)
                    - (
                        _number(
                            unfiltered_bundle["summary"].get("win_rate")
                        )
                        or 0.0
                    ),
                    4,
                ),
                "total_return_pct_points": round(
                    (_number(summary.get("total_return_pct")) or 0.0)
                    - (
                        _number(
                            unfiltered_bundle["summary"].get(
                                "total_return_pct"
                            )
                        )
                        or 0.0
                    ),
                    4,
                ),
                "recommendation_win_rate_pct_points": (
                    _summary_metric_delta(
                        recommendation_quality["summary"],
                        unfiltered_recommendation_quality["summary"],
                        "win_rate",
                    )
                ),
                "recommendation_average_return_pct_points": (
                    _summary_metric_delta(
                        recommendation_quality["summary"],
                        unfiltered_recommendation_quality["summary"],
                        "average_return_pct",
                    )
                ),
                "recommendation_total_return_pct_points": (
                    _summary_metric_delta(
                        recommendation_quality["summary"],
                        unfiltered_recommendation_quality["summary"],
                        "total_return_pct",
                    )
                ),
            },
        },
        "exit_summary": _scheduled_exit_summary(
            executed_trades,
            scheduled_execution.EXIT_MODE,
        ),
        "stress_tests": {
            "double_cost": double_cost_summary,
        },
        "drawdown_diagnostics": drawdown_report,
        "relay_comparison": {
            "selected_variant": selected_variant,
            "configured_variant": configured_variant,
            "gate_selected_variant": gate_selected_variant,
            "configuration_matches_gate": configuration_matches_gate,
            "variants": {
                name: {
                    "lanes": list(SCHEDULED_VARIANT_LANES[name]),
                    "passed": bool(bundle["gate"]["passed"]),
                    "gate_checks": dict(bundle["gate"]["checks"]),
                    "summary": dict(bundle["summary"]),
                    "phase_summaries": {
                        phase: dict(phase_summary)
                        for phase, phase_summary in bundle[
                            "phase_summaries"
                        ].items()
                    },
                    "double_cost": dict(bundle["double_cost_summary"]),
                }
                for name, bundle in variant_bundles.items()
            },
            "trigger_coverage": scheduled_execution.relay_trigger_coverage(rows),
        },
        "position_sizing_audit": position_sizing_audit,
        "orders": account["orders"],
        "trades": [
            _compact_account_trade(trade)
            for trade in executed_trades
        ],
        "skipped_orders": account["skipped_orders"],
        "open_positions": account["open_positions"],
        "validation": validation,
        "simulation_eligible": False,
        "coverage": {
            **latest_coverage,
            "selected_start": rows[0].get("trade_date") if rows else None,
            "selected_end": rows[-1].get("trade_date") if rows else None,
            "selected_trade_days": len(rows),
            "account_price_rows": len(bars),
            **exit_coverage,
        },
        "costs": {
            **account["account_config"],
            "slippage_bps_each_side": config.slippage_bps,
        },
        "limitations": [
            "首次触板是三分钟路径成交代理，没有Tick/L2时不能证明排队成交。",
            "D+1退出统一使用官方日线收盘价，并计入滑点；它是收盘集合竞价成交假设。",
            "缺失D+1官方收盘价的历史订单直接剔除，不使用其他价格替代。",
            "一进二已从候选、研究接口和组合复利中移除。",
            "高板统一盘中触发未通过收益回撤门槛，仅保留独立研究。",
            "历史收益是候选代理；缺少逐时点市场、板块资金和Tick/L2，非实盘等价结果。",
            "冻结后尚未达到60个交易日和30笔闭合交易，保持research_only。",
        ],
    }


def _scheduled_variant_bundle(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    config: cash_backtest.CashBacktestConfig,
    double_cost_config: cash_backtest.CashBacktestConfig,
) -> dict[str, object]:
    exit_mode = scheduled_execution.EXIT_MODE
    account = _simulate_account(orders, bars, trade_dates, exit_mode, config)
    phase_orders = {
        "earlier_history": [
            order
            for order in orders
            if _order_date(order) < scheduled_execution.RESEARCH_SAMPLE_START
        ],
        "design_sample": [
            order
            for order in orders
            if scheduled_execution.RESEARCH_SAMPLE_START
            <= _order_date(order)
            < scheduled_execution.VALIDATION_START
        ],
        "time_validation": [
            order
            for order in orders
            if scheduled_execution.VALIDATION_START
            <= _order_date(order)
            <= scheduled_execution.RULE_FREEZE_DATE
        ],
        "post_freeze_forward": [
            order
            for order in orders
            if _order_date(order) > scheduled_execution.RULE_FREEZE_DATE
        ],
    }
    phase_summaries = {
        phase: _simulate_account(
            phase_rows,
            bars,
            trade_dates,
            exit_mode,
            config,
        )["execution_summary"]
        for phase, phase_rows in phase_orders.items()
    }
    double_cost_summary = _simulate_account(
        orders,
        bars,
        trade_dates,
        exit_mode,
        double_cost_config,
    )["execution_summary"]
    return {
        "account": account,
        "summary": account["execution_summary"],
        "phase_summaries": phase_summaries,
        "double_cost_summary": double_cost_summary,
    }


def _recommendation_quality_report(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    config: cash_backtest.CashBacktestConfig,
) -> dict[str, object]:
    orders, _ = _filter_orders_with_daily_close(orders, bars)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)

    trades: list[dict[str, object]] = []
    skipped_reasons: Counter[str] = Counter()
    open_position_count = 0
    for order in orders:
        symbol = str(order.get("vt_symbol") or "")
        account = _simulate_account(
            [order],
            bars_by_symbol.get(symbol, []),
            trade_dates,
            scheduled_execution.EXIT_MODE,
            config,
        )
        trades.extend(account["executed_trades"])
        open_position_count += len(account["open_positions"])
        skipped_reasons.update(
            str(skipped.get("reason") or "unknown")
            for skipped in account["skipped_orders"]
        )

    daily_results, total_return, max_drawdown = _signal_daily_equity(trades)
    summary = _summary(
        orders,
        trades,
        total_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
    )
    summary.update(
        {
            "open_position_count": open_position_count,
            "skipped_count": sum(skipped_reasons.values()),
            "skipped_reasons": dict(sorted(skipped_reasons.items())),
        }
    )
    return {
        "mode": "independent_standard_slot_daily_equal_weight",
        "position_constraints_applied": False,
        "standard_slot_cash": round(
            config.initial_cash / config.max_positions,
            4,
        ),
        "costs_included": True,
        "daily_aggregation": "mean_net_return_by_exit_date",
        "summary": summary,
        "daily_results": daily_results,
        "trades": [_compact_account_trade(trade) for trade in trades],
        "skipped_reasons": dict(sorted(skipped_reasons.items())),
    }


def _relay_variant_gate(
    summary: Mapping[str, object],
    validation: Mapping[str, object],
    stress: Mapping[str, object],
    baseline_summary: Mapping[str, object],
    baseline_validation: Mapping[str, object],
) -> dict[str, object]:
    checks = {
        "full_return_improved": _greater_than(
            summary.get("total_return_pct"),
            baseline_summary.get("total_return_pct"),
        ),
        "full_drawdown": _at_least(summary.get("max_drawdown_pct"), -10.0),
        "validation_return_not_lower": _at_least(
            validation.get("total_return_pct"),
            _number(baseline_validation.get("total_return_pct")),
        ),
        "validation_drawdown": _at_least(
            validation.get("max_drawdown_pct"),
            -10.0,
        ),
        "double_cost_positive": _greater_than(
            stress.get("total_return_pct"),
            0.0,
        ),
        "double_cost_drawdown": _at_least(
            stress.get("max_drawdown_pct"),
            -10.0,
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _greater_than(left: object, right: object) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return bool(
        left_number is not None
        and right_number is not None
        and left_number > right_number
    )


def _at_least(left: object, right: float | None) -> bool:
    left_number = _number(left)
    return bool(
        left_number is not None
        and right is not None
        and left_number >= right
    )


def _summary_metric_delta(
    selected: Mapping[str, object],
    baseline: Mapping[str, object],
    field: str,
) -> float:
    return round(
        (_number(selected.get(field)) or 0.0)
        - (_number(baseline.get(field)) or 0.0),
        4,
    )


def _scheduled_variant_for_lanes(lanes: Sequence[str]) -> str | None:
    normalized = tuple(lanes)
    return next(
        (
            name
            for name, variant_lanes in SCHEDULED_VARIANT_LANES.items()
            if tuple(variant_lanes) == normalized
        ),
        None,
    )


def _scheduled_exit_coverage(
    bars: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    index = {
        (
            str(bar.get("vt_symbol") or ""),
            str(bar.get("trade_date") or "")[:10],
        ): bar
        for bar in bars
    }
    minute_count = 0
    missing_count = 0
    request_count = 0
    for order in orders:
        result_date = _optional_date(order.get("result_date"))
        symbol = str(order.get("vt_symbol") or "")
        if result_date is None or not symbol:
            continue
        request_count += 1
        source = str(
            (index.get((symbol, result_date.isoformat())) or {}).get(
                "price_1430_source"
            )
            or ""
        )
        if source == "minute_1430":
            minute_count += 1
        else:
            missing_count += 1
    return {
        "exit_price_request_count": request_count,
        "minute_1430_count": minute_count,
        "daily_close_proxy_count": 0,
        "exit_price_missing_count": missing_count,
        "excluded_no_exact_1430_count": missing_count,
    }


def _scheduled_close_coverage(
    bars: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    available = _daily_close_keys(bars)
    requested = [
        (str(order.get("vt_symbol") or ""), result_date.isoformat())
        for order in orders
        if (result_date := _optional_date(order.get("result_date"))) is not None
        and order.get("vt_symbol")
    ]
    close_count = sum(key in available for key in requested)
    missing_count = len(requested) - close_count
    return {
        "exit_price_request_count": len(requested),
        "daily_close_count": close_count,
        "daily_close_missing_count": missing_count,
        "exit_price_missing_count": missing_count,
    }


def _attach_scheduled_exit_prices(
    bars: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    requests = [
        (str(order.get("vt_symbol") or ""), result_date)
        for order in orders
        if (result_date := _optional_date(order.get("result_date"))) is not None
        and order.get("vt_symbol")
    ]
    exact_rows = history_repository.load_account_1430_prices(requests)
    exact_index = {
        (
            str(row.get("vt_symbol") or ""),
            str(row.get("trade_date") or "")[:10],
        ): row
        for row in exact_rows
    }
    indexed = {
        (
            str(bar.get("vt_symbol") or ""),
            str(bar.get("trade_date") or "")[:10],
        ): dict(bar)
        for bar in bars
    }
    minute_count = 0
    missing_count = 0
    for vt_symbol, result_date in requests:
        key = (vt_symbol, result_date.isoformat())
        bar = indexed.get(key)
        exact = exact_index.get(key)
        exact_price = _number((exact or {}).get("price_1430"))
        if exact_price is not None and exact_price > 0:
            if bar is None:
                bar = _price_bar(vt_symbol, result_date.isoformat(), exact_price, exact_price)
                indexed[key] = bar
            bar["price_1430"] = exact_price
            bar["price_1430_source"] = "minute_1430"
            minute_count += 1
            continue
        if bar is not None:
            bar.pop("price_1430", None)
            bar.pop("price_1430_source", None)
        missing_count += 1
    merged = sorted(
        indexed.values(),
        key=lambda bar: (
            str(bar.get("trade_date") or ""),
            str(bar.get("vt_symbol") or ""),
        ),
    )
    return merged, {
        "exit_price_request_count": len(requests),
        "minute_1430_count": minute_count,
        "daily_close_proxy_count": 0,
        "exit_price_missing_count": missing_count,
        "excluded_no_exact_1430_count": missing_count,
    }


def _scheduled_position_sizing_audit(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
) -> dict[str, object]:
    development_orders = [
        order
        for order in orders
        if _order_date(order) < scheduled_execution.VALIDATION_START
    ]
    validation_orders = [
        order
        for order in orders
        if scheduled_execution.VALIDATION_START
        <= _order_date(order)
        <= scheduled_execution.RULE_FREEZE_DATE
    ]
    variants = _position_sizing_variants(orders, bars, trade_dates)
    development_variants = _position_sizing_variants(
        development_orders,
        bars,
        trade_dates,
    )
    validation_variants = _position_sizing_variants(
        validation_orders,
        bars,
        trade_dates,
    )
    selected_by_development = _select_scheduled_position_count(development_variants)
    selected_positions = scheduled_execution.MAX_POSITIONS
    return {
        "selected_max_positions": selected_positions,
        "selected_by_development": selected_by_development,
        "selection_matches_frozen_policy": selected_by_development == selected_positions,
        "selection_rule": (
            "pre_validation_maximum_return_with_drawdown_not_below_minus_10_pct"
        ),
        "selection_cutoff_exclusive": scheduled_execution.VALIDATION_START.isoformat(),
        "drawdown_floor_pct": -10.0,
        "target_position_pct": round(100 / selected_positions, 4),
        "development_sample": _position_sizing_sample(development_orders),
        "validation_sample": _position_sizing_sample(validation_orders),
        "development_variants": development_variants,
        "validation_variants": validation_variants,
        "variants": variants,
    }


def _position_sizing_variants(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
) -> dict[str, Mapping[str, object]]:
    variants: dict[str, Mapping[str, object]] = {}
    for max_positions in (1, 2, 3, 4):
        variant_config = cash_backtest.CashBacktestConfig(
            initial_cash=100_000,
            max_positions=max_positions,
        )
        variants[str(max_positions)] = _simulate_account(
            orders,
            bars,
            trade_dates,
            scheduled_execution.EXIT_MODE,
            variant_config,
        )["execution_summary"]
    return variants


def _select_scheduled_position_count(
    variants: Mapping[str, Mapping[str, object]],
) -> int:
    eligible = [
        (int(position_count), summary)
        for position_count, summary in variants.items()
        if (_number(summary.get("max_drawdown_pct")) or 0.0) >= -10.0
    ]
    if not eligible:
        return max(int(position_count) for position_count in variants)
    return max(
        eligible,
        key=lambda item: (
            _number(item[1].get("total_return_pct")) or 0.0,
            -item[0],
        ),
    )[0]


def _position_sizing_sample(
    orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    signal_dates = sorted({_order_date(order) for order in orders})
    return {
        "signal_count": len(orders),
        "signal_day_count": len(signal_dates),
        "start": signal_dates[0].isoformat() if signal_dates else None,
        "end": signal_dates[-1].isoformat() if signal_dates else None,
    }


def _scheduled_validation(
    phase_summaries: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for phase in ("design_sample", "time_validation"):
        summary = phase_summaries.get(phase) or {}
        win_rate = _number(summary.get("win_rate"))
        total_return = _number(summary.get("total_return_pct"))
        max_drawdown = _number(summary.get("max_drawdown_pct"))
        checks.append(
            {
                "phase": phase,
                "passed": bool(
                    int(summary.get("trade_count") or 0) > 0
                    and win_rate is not None
                    and win_rate >= 55
                    and total_return is not None
                    and total_return > 0
                    and max_drawdown is not None
                    and max_drawdown >= -10
                ),
                "trade_count": int(summary.get("trade_count") or 0),
                "win_rate": win_rate,
                "total_return_pct": total_return,
                "max_drawdown_pct": max_drawdown,
            }
        )
    forward = phase_summaries.get("post_freeze_forward") or {}
    forward_trades = int(forward.get("trade_count") or 0)
    checks.append(
        {
            "phase": "post_freeze_forward",
            "passed": bool(
                forward_trades >= 30
                and (_number(forward.get("win_rate")) or 0) >= 55
                and (_number(forward.get("total_return_pct")) or 0) > 0
                and (_number(forward.get("max_drawdown_pct")) or -100) >= -10
            ),
            "trade_count": forward_trades,
            "win_rate": _number(forward.get("win_rate")),
            "total_return_pct": _number(forward.get("total_return_pct")),
            "max_drawdown_pct": _number(forward.get("max_drawdown_pct")),
        }
    )
    return {
        "passed": False,
        "status": "research_only",
        "lane": "portfolio",
        "checks": checks,
        "reason": "冻结后尚未达到60个交易日和30笔真实闭合交易",
        "requirements": {
            "minimum_forward_trade_days": 60,
            "minimum_forward_trades": 30,
            "minimum_win_rate": 55,
            "minimum_total_return_pct": 0,
            "maximum_drawdown_pct": -10,
            "rule_freeze_date": scheduled_execution.RULE_FREEZE_DATE.isoformat(),
        },
    }


def _scheduled_exit_summary(
    trades: Sequence[Mapping[str, object]],
    exit_mode: str,
) -> dict[str, object]:
    if exit_mode == "next_close":
        return {
            "mode": exit_mode,
            "policy_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
            "close_exit_count": sum(
                trade.get("exit_price_source") == "daily_close"
                for trade in trades
            ),
            "daily_close_proxy_count": 0,
        }
    minute_count = sum(trade.get("exit_price_source") == "minute_1430" for trade in trades)
    proxy_count = sum(
        trade.get("exit_price_source") == "daily_close_proxy" for trade in trades
    )
    return {
        "mode": "next_1430",
        "policy_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
        "auction_exit_count": 0,
        "tail_exit_count": len(trades),
        "minute_1430_count": minute_count,
        "daily_close_proxy_count": proxy_count,
    }


def _order_date(order: Mapping[str, object]) -> date:
    return _optional_date(order.get("entry_date") or order.get("signal_date")) or date.min


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
        f"{history_engine.HISTORY_STRATEGY_VERSION}:"
        f"{_history_cache_revision()}:{start}:{end}:"
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
        return
    if not _post_rebuild_plan_refresh_allowed(_now_shanghai()):
        return
    try:
        from alphaagent.server.services.limit_up import next_session_plan

        next_session_plan.refresh_next_session_plan("final")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "post-rebuild next-session validation cache refresh failed: %s",
            exc,
        )


def _post_rebuild_plan_refresh_allowed(local_at: datetime) -> bool:
    return not (
        local_at.weekday() < 5
        and time(9, 15) <= local_at.time() <= time(15, 0)
    )


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


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
        and str(candidate.get("lane") or "") in BOARD_LANES
        and (lane is None or candidate.get("lane") == lane)
    ]


def _simulate_account(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    exit_mode: str,
    config: cash_backtest.CashBacktestConfig,
) -> dict[str, object]:
    if exit_mode == "next_1430":
        orders, _ = _filter_orders_with_exact_1430(orders, bars)
    elif exit_mode == "next_close":
        orders, _ = _filter_orders_with_daily_close(orders, bars)
    return cash_backtest.simulate_limit_up_account(
        orders,
        bars,
        trade_dates,
        exit_mode,
        config,
    )


def _filter_orders_with_exact_1430(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], dict[str, int]]:
    exact_keys = {
        (
            str(bar.get("vt_symbol") or ""),
            str(bar.get("trade_date") or "")[:10],
        )
        for bar in bars
        if bar.get("price_1430_source") == "minute_1430"
        and (_number(bar.get("price_1430")) or 0) > 0
    }
    selected = [
        order
        for order in orders
        if (
            str(order.get("vt_symbol") or ""),
            str(order.get("result_date") or "")[:10],
        )
        in exact_keys
    ]
    return selected, {
        "input_count": len(orders),
        "selected_count": len(selected),
        "excluded_no_exact_1430_count": len(orders) - len(selected),
    }


def _filter_orders_with_daily_close(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], dict[str, int]]:
    close_keys = _daily_close_keys(bars)
    selected = [
        order
        for order in orders
        if (
            str(order.get("vt_symbol") or ""),
            str(order.get("result_date") or "")[:10],
        )
        in close_keys
    ]
    return selected, {
        "input_count": len(orders),
        "selected_count": len(selected),
        "excluded_no_daily_close_count": len(orders) - len(selected),
    }


def _daily_close_keys(
    bars: Sequence[Mapping[str, object]],
) -> set[tuple[str, str]]:
    return {
        (
            str(bar.get("vt_symbol") or ""),
            str(bar.get("trade_date") or "")[:10],
        )
        for bar in bars
        if (_number(bar.get("close_price")) or 0) > 0
    }


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
    orders = scheduled_execution.extract_scheduled_orders(
        rows,
        included_lanes=(lane,),
    )
    loaded_market_data = bars is None or trade_dates is None
    if loaded_market_data:
        bars, trade_dates = _account_market_data(rows, orders)
    if loaded_market_data and exit_mode == "next_1430":
        bars, _ = _attach_scheduled_exit_prices(bars, orders)
    config = cash_backtest.CashBacktestConfig(
        initial_cash=100_000,
        max_positions=scheduled_execution.MAX_POSITIONS,
    )
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
    resolved_exit_mode = _candidate_exit_mode(candidate, exit_mode)
    return_field = (
        "next_open_return_pct"
        if resolved_exit_mode == "next_open"
        else "next_close_return_pct"
    )
    price_field = (
        "next_open_price" if resolved_exit_mode == "next_open" else "next_close_price"
    )
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
            "sell_time_next_open"
            if resolved_exit_mode == "next_open"
            else "sell_time_next_close"
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
        "setup_tags": candidate.get("setup_tags") or [],
        "setup_confidence": candidate.get("setup_confidence"),
        "dynamic_exit": candidate.get("dynamic_exit") or {},
        "blockers": candidate.get("blockers") or [],
        "financial_risk": candidate.get("financial_risk") or {},
        "prior_board": candidate.get("prior_board"),
        "path_prefix": candidate.get("path_prefix"),
        "outcome": dict(outcome),
    }


def _candidate_exit_mode(candidate: Mapping[str, object], exit_mode: str) -> str:
    if exit_mode != "dynamic":
        return exit_mode
    decision = candidate.get("dynamic_exit")
    decision = decision if isinstance(decision, Mapping) else {}
    return "next_open" if decision.get("mode") == "auction_exit" else "next_close"


def _exit_summary(
    orders: Sequence[Mapping[str, object]],
    exit_mode: str,
) -> dict[str, object]:
    if exit_mode != "dynamic":
        return {
            "mode": exit_mode,
            "auction_exit_count": len(orders) if exit_mode == "next_open" else 0,
            "tail_exit_count": len(orders) if exit_mode == "next_close" else 0,
        }
    auction_count = 0
    tail_count = 0
    for order in orders:
        if _candidate_exit_mode(order, exit_mode) == "next_open":
            auction_count += 1
        else:
            tail_count += 1
    return {
        "mode": "dynamic",
        "policy_version": "limit-up-dynamic-exit-v1",
        "auction_exit_count": auction_count,
        "tail_exit_count": tail_count,
    }


def _compact_account_trade(trade: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "lane",
        "lane_label",
        "vt_symbol",
        "name",
        "industry_id",
        "industry_name",
        "signal_kind",
        "signal_date",
        "entry_date",
        "exit_date",
        "entry_price",
        "exit_price",
        "buy_date",
        "buy_time",
        "buy_price",
        "volume",
        "buy_amount",
        "buy_fee",
        "sell_date",
        "sell_time",
        "sell_price",
        "sell_amount",
        "sell_fee",
        "total_fee",
        "net_pnl",
        "return_pct",
        "is_win",
        "is_hard_loss",
        "d1_outcome",
        "d_board_status",
        "exit_reason",
        "exit_price_source",
        "exit_price_proxy",
        "result_status",
        "execution_confidence",
        "two_to_three_quality_tier",
        "two_to_three_risk_count",
        "two_to_three_risk_flags",
        "favorable_factors",
        "setup_tags",
        "setup_confidence",
        "prior_limit_count_126",
        "prior_industry_turnover_ratio_5d",
        "quality_priority_tier",
        "public_quality_contract_version",
        "public_quality_status",
        "public_quality_gate_passed",
        "public_quality_actionable",
        "public_quality_reason",
        "quality_tier_prior_win_probability",
        "quality_tier_prior_expected_d1_net_return_pct",
        "quality_tier_prior_sample_count",
        "quality_estimate_prior_strength",
        "quality_estimate_stock_sample_count",
        "quality_win_probability",
        "quality_expected_d1_net_return_pct",
        "stock_d1_sample_count",
        "stock_d1_win_rate",
        "stock_d1_average_return_pct",
        "profitability_gate_passed",
        "profitability_gate_reason",
        "recognition_gate_passed",
        "recognition_gate_reason",
        "core_quality_gate_passed",
        "core_quality_gate_reason",
        "dynamic_exit",
    )
    return {field: trade.get(field) for field in fields if field in trade}


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


def _next_1430_signal_trades(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    bar_index = {
        (
            str(bar.get("vt_symbol") or ""),
            str(bar.get("trade_date") or "")[:10],
        ): bar
        for bar in bars
    }
    trades: list[dict[str, object]] = []
    for order in orders:
        symbol = str(order.get("vt_symbol") or "")
        result_date = str(order.get("result_date") or "")[:10]
        entry_price = _number(order.get("entry_price"))
        exit_bar = bar_index.get((symbol, result_date))
        exit_price = _number((exit_bar or {}).get("price_1430"))
        if entry_price is None or entry_price <= 0 or exit_price is None:
            continue
        return_pct = round((exit_price / entry_price - 1) * 100, 4)
        trades.append(
            {
                **dict(order),
                "signal_date": order.get("entry_date") or order.get("signal_date"),
                "entry_date": order.get("entry_date") or order.get("signal_date"),
                "exit_date": result_date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": return_pct,
                "is_win": return_pct > 0,
                "is_hard_loss": return_pct <= -5,
                "exit_price_source": (exit_bar or {}).get("price_1430_source"),
            }
        )
    return trades


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
