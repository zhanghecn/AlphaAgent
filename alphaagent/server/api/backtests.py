"""Backtest endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, Response

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.backtest.engine import (
    BacktestParams,
    backtest_equity,
    backtest_metrics,
    backtest_report,
    backtest_report_csv,
    backtest_trades,
    backtest_validation_grid,
    backtest_validation_grid_csv,
    backtest_minute_gap_csv,
    get_backtest,
    list_backtests,
    run_backtest,
)
from alphaagent.server.services.backtest.strict_pipeline import run_strict_minute_backtest_pipeline

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("")
def create_backtest(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        params = _params_from_payload(payload)
        return ok(run_backtest(params))
    except Exception as exc:
        return _service_error(exc)


@router.post("/strict-minute-pipeline")
def create_strict_minute_backtest(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        params = _params_from_payload(payload)
        return ok(
            run_strict_minute_backtest_pipeline(
                params,
                gap_csv_text=str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                gap_file_path=str(payload.get("gap_file_path") or payload.get("file_path") or ""),
                min_tail_bars=int(payload.get("min_tail_bars") or 1),
                trade_limit=int(payload.get("trade_limit") or 80),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("")
def list_runs(limit: int = Query(default=50, ge=1, le=200)):
    try:
        return ok(list_backtests(limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}")
def get_run(backtest_id: int):
    try:
        return ok(get_backtest(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/metrics")
def get_metrics(backtest_id: int):
    try:
        return ok(backtest_metrics(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/report")
def get_report(backtest_id: int, trade_limit: int = Query(default=50, ge=1, le=500)):
    try:
        return ok(backtest_report(backtest_id, trade_limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/report.csv")
def download_report_csv(backtest_id: int, trade_limit: int = Query(default=500, ge=1, le=500)):
    try:
        result = backtest_report_csv(backtest_id, trade_limit)
        if result.get("status") != "ready":
            return ok(result)
        headers = {
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
        }
        return Response(content=result["content"], media_type="text/csv; charset=utf-8", headers=headers)
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/minute-gaps.csv")
def download_minute_gap_csv(backtest_id: int):
    try:
        result = backtest_minute_gap_csv(backtest_id)
        if result.get("status") != "ready":
            return ok(result)
        headers = {
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
        }
        return Response(content=result["content"], media_type="text/csv; charset=utf-8", headers=headers)
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/validation-grid")
def get_validation_grid(backtest_id: int, max_variants: int = Query(default=54, ge=1, le=54)):
    try:
        return ok(backtest_validation_grid(backtest_id, max_variants))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/validation-grid.csv")
def download_validation_grid_csv(backtest_id: int, max_variants: int = Query(default=54, ge=1, le=54)):
    try:
        result = backtest_validation_grid_csv(backtest_id, max_variants)
        if result.get("status") != "ready":
            return ok(result)
        headers = {
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
        }
        return Response(content=result["content"], media_type="text/csv; charset=utf-8", headers=headers)
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/trades")
def get_trades(backtest_id: int, limit: int = Query(default=500, ge=1, le=2000)):
    try:
        return ok(backtest_trades(backtest_id, limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/equity")
def get_equity(backtest_id: int):
    try:
        return ok(backtest_equity(backtest_id))
    except Exception as exc:
        return _service_error(exc)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value)
    if text == "latest":
        return None
    return date.fromisoformat(text[:10])


def _params_from_payload(payload: dict[str, Any]) -> BacktestParams:
    return BacktestParams(
        strategy=str(payload.get("strategy") or "mainline_leader_pullback"),
        start=_parse_date(payload.get("start")) or date(2020, 1, 1),
        end=_parse_date(payload.get("end")),
        initial_cash=float(payload.get("initial_cash") or 1_000_000),
        max_positions=int(payload.get("max_positions") or 8),
        max_position_pct=float(payload.get("max_position_pct") or 0.125),
        commission_rate=float(payload.get("commission_rate") or 0.0003),
        stamp_tax_rate=float(payload.get("stamp_tax_rate") or 0.0005),
        slippage_bps=float(payload.get("slippage_bps") or 10),
        stop_loss_pct=float(payload.get("stop_loss_pct") or 0.07),
        take_profit_pct=float(payload.get("take_profit_pct") or 0.18),
        trailing_stop_pct=float(payload.get("trailing_stop_pct") or 0.08),
        time_stop_days=int(payload.get("time_stop_days") or 15),
        candidate_limit=int(payload.get("candidate_limit") or 20),
        max_symbols=int(payload.get("max_symbols") or 500),
        min_entry_score=float(payload.get("min_entry_score") or 68),
        strict_entry=_parse_bool(payload.get("strict_entry"), default=True),
        intraday_entry=_parse_bool(payload.get("intraday_entry"), default=True),
        minute_entry_required=_parse_bool(payload.get("minute_entry_required"), default=False),
        tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
        tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
        tail_entry_ma5_tolerance_pct=float(payload.get("tail_entry_ma5_tolerance_pct") or 1.5),
        persist=bool(payload.get("persist") or False),
    )


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail("BACKTEST_SERVICE_UNAVAILABLE", "回测服务暂时不可用。", {"reason": exc.__class__.__name__}),
    )
