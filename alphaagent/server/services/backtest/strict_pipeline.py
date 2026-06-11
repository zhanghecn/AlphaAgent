"""Strict minute-tail backtest pipeline."""

from __future__ import annotations

from datetime import date
from typing import Any

from alphaagent.server.services.backtest.engine import (
    BacktestParams,
    backtest_report,
    backtest_report_csv,
    run_backtest,
)
from alphaagent.server.services.data_sync import audit_minute_gap_csv, audit_minute_gap_file


def run_strict_minute_backtest_pipeline(
    params: BacktestParams,
    *,
    gap_csv_text: str = "",
    gap_file_path: str = "",
    min_tail_bars: int = 1,
    trade_limit: int = 80,
) -> dict[str, Any]:
    """Audit strict minute gaps and run the backtest only when coverage is ready."""

    audit = _audit_gap_coverage(
        gap_csv_text=gap_csv_text,
        gap_file_path=gap_file_path,
        interval="1m",
        tail_entry_start=params.tail_entry_start,
        tail_entry_end=params.tail_entry_end,
        min_tail_bars=min_tail_bars,
    )
    strict_params = _strict_params(params)
    if audit.get("status") != "ready":
        return {
            "status": "blocked_by_minute_gaps",
            "message": "严格分钟尾盘回测未运行：分钟线缺口尚未覆盖完成。",
            "audit": audit,
            "params": _params_payload(strict_params),
            "next_action": "先用外部 CSV、vn.py 数据库或 Tushare Pro 补齐缺口；审计 ready 后再运行严格分钟回测。",
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
        max_symbols=max(params.max_symbols, 1500),
        min_entry_score=params.min_entry_score,
        strict_entry=True,
        intraday_entry=True,
        minute_entry_required=True,
        tail_entry_start=params.tail_entry_start,
        tail_entry_end=params.tail_entry_end,
        tail_entry_ma5_tolerance_pct=params.tail_entry_ma5_tolerance_pct,
        persist=True,
    )


def _params_payload(params: BacktestParams) -> dict[str, Any]:
    result = dict(params.__dict__)
    for key, value in list(result.items()):
        if isinstance(value, date):
            result[key] = value.isoformat()
    return result
