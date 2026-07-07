"""Backtest endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, Response

from alphaagent.market.boards import normalize_included_boards
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.backtest.engine import (
    BacktestParams,
    backtest_candidate_trace,
    backtest_candidate_trade_quality_report,
    backtest_day_detail,
    backtest_data_quality,
    backtest_daily_decisions,
    backtest_drilldown_options,
    backtest_equity,
    backtest_execution_model_comparison,
    backtest_execution_breakpoint_matrix,
    backtest_factor_audit,
    backtest_factor_candidates,
    backtest_signal_amount_preview,
    backtest_signal_events,
    backtest_strategy_comparison,
    backtest_metrics,
    backtest_minute_coverage,
    backtest_low_suction_confirmed_path_audit,
    backtest_low_suction_start_factor_audit,
    backtest_market_phase_audit,
    backtest_phase_strategy_family_matrix,
    backtest_path_diagnostics,
    backtest_performance_attribution_report,
    backtest_report,
    backtest_report_csv,
    backtest_setup_market_exit_audit,
    backtest_strategy_timeline,
    backtest_support_stop_matrix,
    backtest_symbol_detail,
    backtest_top_candidate_audit,
    backtest_trade_attribution,
    backtest_trades,
    backtest_audit,
    backtest_validation_grid,
    backtest_validation_grid_csv,
    backtest_minute_gap_csv,
    get_backtest,
    latest_symbol_backtest,
    list_backtests,
    run_backtest,
)
from alphaagent.server.services.backtest.strict_pipeline import run_strict_minute_backtest_pipeline
from alphaagent.server.services.quant.factors import STRATEGY_ID

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("")
def create_backtest(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        params = _params_from_payload(payload)
        return ok(run_backtest(params))
    except Exception as exc:
        return _service_error(exc)


@router.post("/symbol")
def create_symbol_backtest(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        vt_symbol = str(payload.get("vt_symbol") or payload.get("symbol") or "").strip().upper()
        if not vt_symbol:
            return JSONResponse(status_code=400, content=fail("INVALID_SYMBOL", "vt_symbol is required."))
        params = _params_from_payload(
            {
                **payload,
                "symbols": [vt_symbol],
                "max_symbols": 1,
                "max_positions": int(payload.get("max_positions") or 1),
                "candidate_limit": int(payload.get("candidate_limit") or 1),
                "persist": payload.get("persist", True),
            }
        )
        result = run_backtest(params)
        backtest_id = result.get("backtest_id")
        if result.get("status") == "ready" and backtest_id:
            result["audit"] = backtest_audit(int(backtest_id), vt_symbol, int(payload.get("audit_limit") or 300))
        return ok(result)
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/latest")
def get_latest_symbol_backtest(vt_symbol: str, strategy: str = Query(default="")):
    try:
        return ok(latest_symbol_backtest(vt_symbol, strategy_id=strategy or None))
    except Exception as exc:
        return _service_error(exc)


@router.post("/strict-minute-pipeline")
def create_strict_minute_backtest(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        params = _params_from_payload(payload)
        return ok(
            run_strict_minute_backtest_pipeline(
                params,
                backtest_id=int(payload["backtest_id"]) if payload.get("backtest_id") not in (None, "") else None,
                gap_csv_text=str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                gap_file_path=str(payload.get("gap_file_path") or payload.get("file_path") or ""),
                min_tail_bars=int(payload.get("min_tail_bars") or 1),
                trade_limit=int(payload.get("trade_limit") or 80),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.post("/strategy-comparison")
def create_strategy_comparison(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        params = _params_from_payload({**payload, "persist": False})
        strategies = _parse_strategy_list(payload.get("strategies") or payload.get("strategy_ids"))
        return ok(backtest_strategy_comparison(params, strategies=strategies))
    except Exception as exc:
        return _service_error(exc)


@router.get("")
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    run_type: str = Query(default="all", pattern="^(all|portfolio|symbol)$"),
    strategy: str | None = Query(default=None),
    baseline_only: bool = Query(default=False),
):
    try:
        return ok(list_backtests(limit, run_type=run_type, strategy_id=strategy, baseline_only=baseline_only))
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
def get_report(
    backtest_id: int,
    trade_limit: int = Query(default=50, ge=1, le=500),
    include_analysis: bool = Query(default=False),
):
    try:
        return ok(backtest_report(backtest_id, trade_limit, include_analysis=include_analysis))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/execution-model-comparison")
def get_execution_model_comparison(backtest_id: int):
    try:
        return ok(backtest_execution_model_comparison(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/minute-coverage")
def get_minute_coverage(backtest_id: int):
    try:
        return ok(backtest_minute_coverage(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/data-quality")
def get_data_quality(backtest_id: int):
    try:
        return ok(backtest_data_quality(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/audit")
def get_audit(
    backtest_id: int,
    vt_symbol: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=1000),
):
    try:
        return ok(backtest_audit(backtest_id, vt_symbol or None, limit))
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
def get_trades(
    backtest_id: int,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    try:
        return ok(backtest_trades(backtest_id, limit=limit, offset=offset, order=order))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/equity")
def get_equity(backtest_id: int):
    try:
        return ok(backtest_equity(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/drilldown-options")
def get_drilldown_options(backtest_id: int):
    try:
        return ok(backtest_drilldown_options(backtest_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/daily-decisions")
def get_daily_decisions(
    backtest_id: int,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    try:
        return ok(backtest_daily_decisions(backtest_id, limit=limit, offset=offset, order=order))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/trade-attribution")
def get_trade_attribution(
    backtest_id: int,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="pnl_asc", pattern="^(pnl_asc|pnl_desc|entry_desc|entry_asc)$"),
):
    try:
        return ok(backtest_trade_attribution(backtest_id, limit=limit, offset=offset, sort=sort))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/path-diagnostics")
def get_path_diagnostics(
    backtest_id: int,
    vt_symbol: str = Query(default=""),
    lookahead_days: int = Query(default=10, ge=1, le=30),
    limit: int = Query(default=500, ge=1, le=2000),
):
    try:
        return ok(
            backtest_path_diagnostics(
                backtest_id,
                vt_symbol=vt_symbol or None,
                lookahead_days=lookahead_days,
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/low-suction-start-factor-audit")
def get_low_suction_start_factor_audit(
    backtest_id: int,
    lookahead_days: int = Query(default=10, ge=1, le=30),
):
    try:
        return ok(backtest_low_suction_start_factor_audit(backtest_id, lookahead_days=lookahead_days))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/setup-market-exit-audit")
def get_setup_market_exit_audit(
    backtest_id: int,
    lookahead_days: int = Query(default=10, ge=1, le=30),
):
    try:
        return ok(backtest_setup_market_exit_audit(backtest_id, lookahead_days=lookahead_days))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/support-stop-matrix")
def get_support_stop_matrix(
    backtest_id: int,
    lookahead_days: int = Query(default=10, ge=1, le=30),
    sample_limit: int = Query(default=40, ge=1, le=200),
):
    try:
        return ok(
            backtest_support_stop_matrix(
                backtest_id,
                lookahead_days=lookahead_days,
                sample_limit=sample_limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/low-suction-confirmed-path-audit")
def get_low_suction_confirmed_path_audit(
    backtest_id: int,
    lookahead_days: int = Query(default=20, ge=5, le=30),
):
    try:
        return ok(backtest_low_suction_confirmed_path_audit(backtest_id, lookahead_days=lookahead_days))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/market-phase-audit")
def get_market_phase_audit(
    backtest_id: int,
    candidate_top_n: int = Query(default=20, ge=1, le=100),
):
    try:
        return ok(backtest_market_phase_audit(backtest_id, candidate_top_n=candidate_top_n))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/phase-strategy-family-matrix")
def get_phase_strategy_family_matrix(
    backtest_id: int,
    candidate_rank_limits: str = Query(default="10,20,100"),
):
    try:
        return ok(
            backtest_phase_strategy_family_matrix(
                backtest_id,
                candidate_rank_limits=_parse_int_list(candidate_rank_limits, default=[10, 20, 100]),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/execution-breakpoint-matrix")
def get_execution_breakpoint_matrix(
    backtest_id: int,
    candidate_rank_limit: int = Query(default=100, ge=1, le=200),
    sample_limit: int = Query(default=120, ge=1, le=500),
):
    try:
        return ok(
            backtest_execution_breakpoint_matrix(
                backtest_id,
                candidate_rank_limit=candidate_rank_limit,
                sample_limit=sample_limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/top-candidate-audit")
def get_top_candidate_audit(backtest_id: int, top_n: int = Query(default=10, ge=1, le=100)):
    try:
        return ok(backtest_top_candidate_audit(backtest_id, top_n=top_n))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/factor-candidates")
def get_factor_candidates(
    backtest_id: int,
    vt_symbol: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
):
    try:
        return ok(backtest_factor_candidates(backtest_id, vt_symbol=vt_symbol or None, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/factor-audit")
def get_factor_audit(
    backtest_id: int,
    top_limit: int = Query(default=100, ge=1, le=2000),
    exclude_strong_market: bool = Query(default=False),
):
    try:
        return ok(backtest_factor_audit(backtest_id, top_limit=top_limit, exclude_strong_market=exclude_strong_market))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/performance-attribution")
def get_performance_attribution_report(
    backtest_id: int,
    reference_backtest_id: int | None = Query(default=None, ge=1),
    sample_limit: int = Query(default=20, ge=1, le=100),
):
    try:
        return ok(
            backtest_performance_attribution_report(
                backtest_id,
                reference_backtest_id=reference_backtest_id,
                sample_limit=sample_limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/candidate-trade-quality-report")
def get_candidate_trade_quality_report(
    backtest_id: int,
    rank_limit: int = Query(default=20, ge=1, le=20),
    sample_limit: int = Query(default=500, ge=1, le=1000),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
):
    try:
        return ok(
            backtest_candidate_trade_quality_report(
                backtest_id,
                rank_limit=rank_limit,
                sample_limit=sample_limit,
                start_date=_parse_date(start_date),
                end_date=_parse_date(end_date),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/strategy-timeline")
def get_strategy_timeline(backtest_id: int, vt_symbol: str = Query(..., min_length=1)):
    try:
        return ok(backtest_strategy_timeline(backtest_id, vt_symbol))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/signal-events")
def get_signal_events(
    backtest_id: int,
    start: str = Query(default=""),
    end: str = Query(default=""),
    vt_symbol: str = Query(default=""),
    side: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
):
    try:
        return ok(
            backtest_signal_events(
                backtest_id,
                start=_parse_date(start),
                end=_parse_date(end),
                vt_symbol=vt_symbol or None,
                side=side or None,
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/signal-events/amount-preview")
def get_signal_amount_preview(
    backtest_id: int,
    capital: float = Query(default=1_000_000, gt=0),
    max_positions: int = Query(default=8, ge=1, le=200),
    start: str = Query(default=""),
    end: str = Query(default=""),
    vt_symbol: str = Query(default=""),
    side: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=2000),
):
    try:
        return ok(
            backtest_signal_amount_preview(
                backtest_id,
                capital=capital,
                max_positions=max_positions,
                start=_parse_date(start),
                end=_parse_date(end),
                vt_symbol=vt_symbol or None,
                side=side or None,
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/candidate-trace")
def get_candidate_trace(
    backtest_id: int,
    vt_symbol: str = Query(..., min_length=1),
    signal_date: str = Query(..., min_length=1),
):
    try:
        parsed_date = _parse_date(signal_date)
        if parsed_date is None:
            return JSONResponse(status_code=400, content=fail("INVALID_DATE", "signal_date is required."))
        return ok(backtest_candidate_trace(backtest_id, vt_symbol, parsed_date))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/days/{trade_date}")
def get_day_detail(backtest_id: int, trade_date: str):
    try:
        parsed_date = _parse_date(trade_date)
        if parsed_date is None:
            return JSONResponse(status_code=400, content=fail("INVALID_DATE", "trade_date is required."))
        return ok(backtest_day_detail(backtest_id, parsed_date))
    except Exception as exc:
        return _service_error(exc)


@router.get("/{backtest_id}/symbols/{vt_symbol}")
def get_symbol_detail(backtest_id: int, vt_symbol: str):
    try:
        return ok(backtest_symbol_detail(backtest_id, vt_symbol))
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
    execution_model = str(payload.get("execution_model") or "legacy_next_open")
    intraday_entry, minute_entry_required = _execution_flags_from_payload(payload, execution_model)
    return BacktestParams(
        strategy=str(payload.get("strategy") or STRATEGY_ID),
        start=_parse_date(payload.get("start")) or date(2020, 1, 1),
        end=_parse_date(payload.get("end")),
        initial_cash=float(payload.get("initial_cash") or 1_000_000),
        max_positions=int(payload.get("max_positions") or 10),
        max_position_pct=float(payload.get("max_position_pct") or 0.1),
        commission_rate=float(payload.get("commission_rate") or 0.0003),
        stamp_tax_rate=float(payload.get("stamp_tax_rate") or 0.0005),
        slippage_bps=float(payload.get("slippage_bps") or 10),
        stop_loss_pct=float(payload.get("stop_loss_pct") or 0.08),  # 与 schemas 默认同步(2026-06-24 CPCV 验证 0.08 稳健)
        take_profit_pct=float(payload.get("take_profit_pct") or 0.18),
        trailing_stop_pct=float(payload.get("trailing_stop_pct") or 0.08),
        time_stop_days=int(payload.get("time_stop_days") or 15),
        candidate_limit=int(payload.get("candidate_limit") or 20),
        max_symbols=int(payload.get("max_symbols") or 5000),
        min_entry_score=float(payload.get("min_entry_score") or 76),
        strict_entry=_parse_bool(payload.get("strict_entry"), default=True),
        execution_model=execution_model,
        intraday_entry=intraday_entry,
        minute_entry_required=minute_entry_required,
        minute_interval=str(payload.get("minute_interval") or "1m"),
        tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
        tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
        tail_entry_ma5_tolerance_pct=float(payload.get("tail_entry_ma5_tolerance_pct") or 1.5),
        require_low_suction_launch_confirmation=_parse_bool(payload.get("require_low_suction_launch_confirmation"), default=False),
        exclude_repeated_dragon_pullback=_parse_bool(payload.get("exclude_repeated_dragon_pullback"), default=False),
        require_low_suction_launch_for_low_suction_context=_parse_bool(
            payload.get("require_low_suction_launch_for_low_suction_context"),
            default=False,
        ),
        require_balanced_low_suction_launch_quality=_parse_bool(
            payload.get("require_balanced_low_suction_launch_quality"),
            default=False,
        ),
        enable_entry_launch_quality_score=_parse_bool(payload.get("enable_entry_launch_quality_score"), default=False),
        enable_entry_launch_risk_penalty=_parse_bool(payload.get("enable_entry_launch_risk_penalty"), default=False),
        enable_low_suction_market_risk_penalty=_parse_bool(
            payload.get("enable_low_suction_market_risk_penalty"),
            default=False,
        ),
        enable_market_adaptive_setup_weighting=_parse_bool(
            payload.get("enable_market_adaptive_setup_weighting"),
            default=False,
        ),
        enable_low_suction_first_lift_bonus=_parse_bool(
            payload.get("enable_low_suction_first_lift_bonus"),
            default=False,
        ),
        enable_low_suction_lifecycle_ranking=_parse_bool(
            payload.get("enable_low_suction_lifecycle_ranking"),
            default=False,
        ),
        enable_low_suction_buildup_quality_lane=_parse_bool(
            payload.get("enable_low_suction_buildup_quality_lane"),
            default=False,
        ),
        enable_candidate_tail_risk_penalty=_parse_bool(payload.get("enable_candidate_tail_risk_penalty"), default=False),
        enable_mainline_momentum_lane=_parse_bool(payload.get("enable_mainline_momentum_lane"), default=False),
        enable_mainline_momentum_risk_control=_parse_bool(
            payload.get("enable_mainline_momentum_risk_control"),
            default=False,
        ),
        enable_mainline_momentum_hard_filter=_parse_bool(
            payload.get("enable_mainline_momentum_hard_filter"),
            default=False,
        ),
        enable_surge_quality_lane=_parse_bool(payload.get("enable_surge_quality_lane"), default=False),
        enable_top20_day_quality_gate=_parse_bool(payload.get("enable_top20_day_quality_gate"), default=False),
        enable_weekly_top_fractal_relief=_parse_bool(payload.get("enable_weekly_top_fractal_relief"), default=False),
        enable_pure_loss_weak_bucket_penalty=_parse_bool(
            payload.get("enable_pure_loss_weak_bucket_penalty"),
            default=False,
        ),
        enable_selective_setup_quality_lane=_parse_bool(
            payload.get("enable_selective_setup_quality_lane"),
            default=False,
        ),
        enable_support_divergence_entry_lane=_parse_bool(
            payload.get("enable_support_divergence_entry_lane"),
            default=False,
        ),
        enable_strong_trend_ma_pullback_entry_lane=_parse_bool(
            payload.get("enable_strong_trend_ma_pullback_entry_lane"),
            default=False,
        ),
        enable_high_risk_d2_follow_through_entry=_parse_bool(
            payload.get("enable_high_risk_d2_follow_through_entry"),
            default=False,
        ),
        enable_dynamic_failed_launch_exit_stop=_parse_bool(
            payload.get("enable_dynamic_failed_launch_exit_stop"),
            default=False,
        ),
        enable_failed_launch_exit_stop=_parse_bool(payload.get("enable_failed_launch_exit_stop"), default=False),
        enable_contextual_failed_launch_exit_stop=_parse_bool(
            payload.get("enable_contextual_failed_launch_exit_stop"),
            default=False,
        ),
        enable_mid_profit_giveback_stop=_parse_bool(payload.get("enable_mid_profit_giveback_stop"), default=False),
        mid_profit_giveback_min_high_gain_pct=float(payload.get("mid_profit_giveback_min_high_gain_pct") or 0.10),
        mid_profit_giveback_max_current_gain_pct=float(payload.get("mid_profit_giveback_max_current_gain_pct") or 0.04),
        mid_profit_giveback_drawdown_pct=float(payload.get("mid_profit_giveback_drawdown_pct") or 0.07),
        enable_contextual_support_reclaim_delay=_parse_bool(payload.get("enable_contextual_support_reclaim_delay"), default=False),
        support_reclaim_delay_max_warning_level=int(payload.get("support_reclaim_delay_max_warning_level") or 2),
        support_reclaim_delay_min_sell_day_range_pct=float(payload.get("support_reclaim_delay_min_sell_day_range_pct") or 5.0),
        enable_contextual_peak_giveback_stop=_parse_bool(payload.get("enable_contextual_peak_giveback_stop"), default=False),
        peak_giveback_min_high_gain_pct=float(payload.get("peak_giveback_min_high_gain_pct") or 0.12),
        peak_giveback_max_current_gain_pct=float(payload.get("peak_giveback_max_current_gain_pct") or 0.03),
        peak_giveback_drawdown_pct=float(payload.get("peak_giveback_drawdown_pct") or 0.07),
        peak_giveback_min_holding_days=int(payload.get("peak_giveback_min_holding_days") or 5),
        enable_low_suction_false_launch_watch_gate=_parse_bool(payload.get("enable_low_suction_false_launch_watch_gate"), default=False),
        low_suction_false_launch_min_days=int(payload.get("low_suction_false_launch_min_days") or 3),
        low_suction_false_launch_min_warning_level=int(payload.get("low_suction_false_launch_min_warning_level") or 2),
        low_suction_false_launch_max_recovery_level=int(payload.get("low_suction_false_launch_max_recovery_level") or 1),
        enable_low_suction_pullback_entry=_parse_bool(payload.get("enable_low_suction_pullback_entry"), default=False),
        low_suction_pullback_entry_max_wait_days=int(payload.get("low_suction_pullback_entry_max_wait_days") or 3),
        low_suction_pullback_entry_buffer_pct=float(payload.get("low_suction_pullback_entry_buffer_pct") or 0.01),
        low_suction_pullback_entry_reserve_slot=_parse_bool(payload.get("low_suction_pullback_entry_reserve_slot"), default=True),
        enable_low_suction_trigger_day_confirmation=_parse_bool(
            payload.get("enable_low_suction_trigger_day_confirmation"),
            default=False,
        ),
        enable_low_suction_confirmed_branch_exit=_parse_bool(
            payload.get("enable_low_suction_confirmed_branch_exit"),
            default=False,
        ),
        low_suction_failed_follow_d3_low_pct=float(payload.get("low_suction_failed_follow_d3_low_pct") or -8.0),
        low_suction_failed_follow_d3_high_pct=float(payload.get("low_suction_failed_follow_d3_high_pct") or 2.0),
        low_suction_failed_follow_d3_close_pct=float(payload.get("low_suction_failed_follow_d3_close_pct") or -3.0),
        low_suction_opened_space_d5_high_pct=float(payload.get("low_suction_opened_space_d5_high_pct") or 6.0),
        low_suction_opened_space_d5_low_pct=float(payload.get("low_suction_opened_space_d5_low_pct") or -5.0),
        setup_family_filter=str(payload.get("setup_family_filter") or "").strip(),
        enable_phase_aware_setup_selector=_parse_bool(payload.get("enable_phase_aware_setup_selector"), default=False),
        reuse_signal_cache=_parse_bool(payload.get("reuse_signal_cache"), default=False),
        exclude_from_product_baseline=_parse_bool(payload.get("exclude_from_product_baseline"), default=False),
        symbols=_parse_symbols(payload.get("symbols") or payload.get("vt_symbols") or payload.get("vt_symbol")),
        included_boards=normalize_included_boards(payload.get("included_boards")),
        persist=bool(payload.get("persist") or False),
    )


def _execution_flags_from_payload(payload: dict[str, Any], execution_model: str) -> tuple[bool, bool]:
    """Derive legacy flags from the public execution model.

    New API callers should only choose ``execution_model``.  The old boolean
    flags remain accepted for ``legacy_next_open`` so historical scripts and
    reports can still be compared explicitly.
    """

    model = execution_model.strip().lower()
    if model in {"strict_1430", "strict", "strict_minute"}:
        return True, True
    if model in {"tail_close_hybrid", "hybrid", "tail"}:
        return True, False
    return (
        _parse_bool(payload.get("intraday_entry"), default=False),
        _parse_bool(payload.get("minute_entry_required"), default=False),
    )


def _parse_symbols(value: Any) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    else:
        raw_items = [str(item).strip() for item in value]
    items = [item.upper() for item in raw_items if item]
    return items or None


def _parse_strategy_list(value: Any) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    else:
        raw_items = [str(item).strip() for item in value]
    items = [item for item in raw_items if item]
    return items or None


def _parse_int_list(value: Any, *, default: list[int]) -> list[int]:
    if value is None or value == "":
        return list(default)
    raw_items = value.split(",") if isinstance(value, str) else value
    items: list[int] = []
    for item in raw_items:
        text = str(item).strip()
        if not text:
            continue
        try:
            items.append(int(text))
        except ValueError:
            continue
    return items or list(default)


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _payload_value(payload: dict[str, Any], key: str, default: Any) -> Any:
    value = payload.get(key)
    return default if value in (None, "") else value


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail("BACKTEST_SERVICE_UNAVAILABLE", "回测服务暂时不可用。", {"reason": exc.__class__.__name__}),
    )
