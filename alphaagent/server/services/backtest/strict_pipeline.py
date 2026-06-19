"""Strict minute-tail backtest pipeline."""

from __future__ import annotations

from datetime import date
from typing import Any

from alphaagent.server.services.backtest.engine import (
    BacktestParams,
    _params_from_run,
    backtest_minute_gap_csv,
    get_backtest,
    backtest_report,
    backtest_report_csv,
    run_backtest,
)
from alphaagent.server.services.data_sync import audit_minute_gap_csv, audit_minute_gap_file


def run_strict_minute_backtest_pipeline(
    params: BacktestParams,
    *,
    backtest_id: int | None = None,
    gap_csv_text: str = "",
    gap_file_path: str = "",
    min_tail_bars: int = 1,
    trade_limit: int = 80,
) -> dict[str, Any]:
    """Audit strict minute gaps and run the backtest only when coverage is ready."""

    gap_csv_text = _gap_csv_from_backtest(backtest_id) if backtest_id is not None else gap_csv_text
    strict_params = _strict_params(_base_params(params, backtest_id))
    audit = _audit_gap_coverage(
        gap_csv_text=gap_csv_text,
        gap_file_path=gap_file_path,
        interval=strict_params.minute_interval,
        tail_entry_start=strict_params.tail_entry_start,
        tail_entry_end=strict_params.tail_entry_end,
        min_tail_bars=min_tail_bars,
    )
    if audit.get("status") != "ready":
        return {
            "status": "blocked_by_minute_gaps",
            "message": "严格分钟尾盘回测未运行：分钟线缺口尚未覆盖完成。",
            "audit": audit,
            "params": _params_payload(strict_params),
            "next_action": "先用数据同步补齐该回测的执行日 14:30 快照；审计 ready 后再运行严格分钟回测。",
        }

    result = run_backtest(strict_params)
    if result.get("status") != "ready" or not result.get("backtest_id"):
        return {
            "status": result.get("status") or "backtest_failed",
            "message": "严格分钟回测运行失败或未持久化。",
            "audit": audit,
            "backtest": result,
            "params": _params_payload(strict_params),
        }

    backtest_id = int(result["backtest_id"])
    report = backtest_report(backtest_id, trade_limit=trade_limit)
    csv_result = backtest_report_csv(backtest_id, trade_limit=500)
    return {
        "status": "ready",
        "message": "严格分钟尾盘回测已完成。",
        "audit": audit,
        "backtest": {
            "backtest_id": backtest_id,
            "metrics": result.get("metrics") or {},
            "start": result.get("start"),
            "end": result.get("end"),
        },
        "report": report,
        "csv": {
            "status": csv_result.get("status"),
            "filename": csv_result.get("filename"),
        },
        "params": _params_payload(strict_params),
    }


def _audit_gap_coverage(
    *,
    gap_csv_text: str,
    gap_file_path: str,
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
    min_tail_bars: int,
) -> dict[str, Any]:
    if str(gap_file_path or "").strip():
        return audit_minute_gap_file(
            gap_file_path,
            interval=interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            min_tail_bars=min_tail_bars,
        )
    return audit_minute_gap_csv(
        str(gap_csv_text or ""),
        interval=interval,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        min_tail_bars=min_tail_bars,
    )


def _gap_csv_from_backtest(backtest_id: int | None) -> str:
    if backtest_id is None:
        return ""
    result = backtest_minute_gap_csv(int(backtest_id))
    if result.get("status") not in {"ready", "empty"}:
        raise ValueError(f"Cannot load minute gaps for backtest {backtest_id}: {result.get('status')}")
    return str(result.get("content") or "")


def _base_params(params: BacktestParams, backtest_id: int | None) -> BacktestParams:
    if backtest_id is None:
        return params
    result = get_backtest(int(backtest_id))
    if result.get("status") != "ready" or not result.get("item"):
        raise ValueError(f"Cannot load params for backtest {backtest_id}: {result.get('status')}")
    return _params_from_run(dict(result["item"]))


def _strict_params(params: BacktestParams) -> BacktestParams:
    return BacktestParams(
        strategy=params.strategy,
        start=params.start,
        end=params.end,
        initial_cash=params.initial_cash,
        max_positions=params.max_positions,
        max_position_pct=params.max_position_pct,
        commission_rate=params.commission_rate,
        stamp_tax_rate=params.stamp_tax_rate,
        slippage_bps=params.slippage_bps,
        stop_loss_pct=params.stop_loss_pct,
        take_profit_pct=params.take_profit_pct,
        trailing_stop_pct=params.trailing_stop_pct,
        time_stop_days=params.time_stop_days,
        candidate_limit=params.candidate_limit,
        max_symbols=params.max_symbols,
        min_entry_score=params.min_entry_score,
        strict_entry=True,
        require_low_suction_launch_confirmation=params.require_low_suction_launch_confirmation,
        exclude_repeated_dragon_pullback=params.exclude_repeated_dragon_pullback,
        require_low_suction_launch_for_low_suction_context=params.require_low_suction_launch_for_low_suction_context,
        require_balanced_low_suction_launch_quality=params.require_balanced_low_suction_launch_quality,
        enable_entry_launch_quality_score=params.enable_entry_launch_quality_score,
        enable_entry_launch_risk_penalty=params.enable_entry_launch_risk_penalty,
        enable_low_suction_market_risk_penalty=params.enable_low_suction_market_risk_penalty,
        enable_market_adaptive_setup_weighting=params.enable_market_adaptive_setup_weighting,
        enable_low_suction_first_lift_bonus=params.enable_low_suction_first_lift_bonus,
        enable_failed_launch_exit_stop=params.enable_failed_launch_exit_stop,
        enable_contextual_failed_launch_exit_stop=params.enable_contextual_failed_launch_exit_stop,
        enable_mid_profit_giveback_stop=params.enable_mid_profit_giveback_stop,
        mid_profit_giveback_min_high_gain_pct=params.mid_profit_giveback_min_high_gain_pct,
        mid_profit_giveback_max_current_gain_pct=params.mid_profit_giveback_max_current_gain_pct,
        mid_profit_giveback_drawdown_pct=params.mid_profit_giveback_drawdown_pct,
        enable_contextual_support_reclaim_delay=params.enable_contextual_support_reclaim_delay,
        support_reclaim_delay_max_warning_level=params.support_reclaim_delay_max_warning_level,
        support_reclaim_delay_max_replacement_score_gap=params.support_reclaim_delay_max_replacement_score_gap,
        support_reclaim_delay_min_sell_day_range_pct=params.support_reclaim_delay_min_sell_day_range_pct,
        enable_contextual_peak_giveback_stop=params.enable_contextual_peak_giveback_stop,
        peak_giveback_min_high_gain_pct=params.peak_giveback_min_high_gain_pct,
        peak_giveback_max_current_gain_pct=params.peak_giveback_max_current_gain_pct,
        peak_giveback_drawdown_pct=params.peak_giveback_drawdown_pct,
        peak_giveback_min_holding_days=params.peak_giveback_min_holding_days,
        enable_low_suction_false_launch_watch_gate=params.enable_low_suction_false_launch_watch_gate,
        low_suction_false_launch_min_days=params.low_suction_false_launch_min_days,
        low_suction_false_launch_min_warning_level=params.low_suction_false_launch_min_warning_level,
        low_suction_false_launch_max_recovery_level=params.low_suction_false_launch_max_recovery_level,
        enable_missed_candidate_quality_rotation=params.enable_missed_candidate_quality_rotation,
        missed_rotation_min_score=params.missed_rotation_min_score,
        missed_rotation_min_score_gap=params.missed_rotation_min_score_gap,
        missed_rotation_max_held_return_pct=params.missed_rotation_max_held_return_pct,
        missed_rotation_min_held_days=params.missed_rotation_min_held_days,
        exclude_from_product_baseline=params.exclude_from_product_baseline,
        execution_model="strict_1430",
        intraday_entry=True,
        minute_entry_required=True,
        minute_interval="1m",
        tail_entry_start=params.tail_entry_start,
        tail_entry_end=params.tail_entry_end,
        tail_entry_ma5_tolerance_pct=params.tail_entry_ma5_tolerance_pct,
        symbols=params.symbols,
        included_boards=params.included_boards,
        persist=True,
    )


def _params_payload(params: BacktestParams) -> dict[str, Any]:
    result = dict(params.__dict__)
    for key, value in list(result.items()):
        if isinstance(value, date):
            result[key] = value.isoformat()
        elif isinstance(value, tuple):
            result[key] = list(value)
    return result
