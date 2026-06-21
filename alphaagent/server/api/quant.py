"""Quant screening endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.quant import screening
from alphaagent.server.services.quant import research_jobs
from alphaagent.server.services.quant import strategy_replay
from alphaagent.server.services.quant.symbol_quant_state import latest_symbol_quant_state
from alphaagent.server.services.quant.symbol_diagnostics import symbol_diagnostics_report

router = APIRouter(prefix="/quant", tags=["quant"])


@router.post("/screen-runs")
def create_screen_run(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            screening.screen_stocks(
                _parse_date(payload.get("trade_date")),
                strategy_id=str(payload.get("strategy") or screening.STRATEGY_ID),
                max_symbols=int(payload.get("max_symbols") or 5000),
                recommendation_limit=int(payload.get("recommendation_limit") or screening.DEFAULT_RECOMMENDATION_LIMIT),
                min_recommendation_score=float(payload.get("min_recommendation_score") or 60),
                persist=bool(payload.get("persist", True)),
                auto_portfolio=bool(payload.get("auto_portfolio", True)),
                included_boards=payload.get("included_boards"),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.post("/screen-runs/range")
def create_screen_runs_range(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            screening.screen_stocks_range(
                start=_parse_date(payload.get("start") or payload.get("start_date") or payload.get("trade_date")),
                end=_parse_date(payload.get("end") or payload.get("end_date")),
                strategy_id=str(payload.get("strategy") or screening.STRATEGY_ID),
                max_symbols=int(payload.get("max_symbols") or 5000),
                recommendation_limit=int(payload.get("recommendation_limit") or screening.DEFAULT_RECOMMENDATION_LIMIT),
                min_recommendation_score=float(payload.get("min_recommendation_score") or 60),
                persist=bool(payload.get("persist", True)),
                auto_portfolio=bool(payload.get("auto_portfolio", True)),
                included_boards=payload.get("included_boards"),
                force_refresh=bool(payload.get("force_refresh", False)),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.post("/research-runs")
def create_research_run(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            research_jobs.start_research_run(
                start=_parse_date(payload.get("start") or payload.get("start_date") or payload.get("trade_date")),
                end=_parse_date(payload.get("end") or payload.get("end_date")),
                strategy_id=str(payload.get("strategy") or screening.STRATEGY_ID),
                max_symbols=int(payload.get("max_symbols") or 5000),
                recommendation_limit=int(payload.get("recommendation_limit") or screening.DEFAULT_RECOMMENDATION_LIMIT),
                min_recommendation_score=float(payload.get("min_recommendation_score") or 60),
                min_entry_score=_parse_float(payload.get("min_entry_score")),
                persist=bool(payload.get("persist", True)),
                auto_portfolio=bool(payload.get("auto_portfolio", True)),
                included_boards=payload.get("included_boards"),
                initial_cash=float(payload.get("initial_cash") or 1_000_000),
                max_positions=int(payload.get("max_positions") or 10),
                candidate_limit=int(payload.get("candidate_limit") or 20),
                max_position_pct=float(payload.get("max_position_pct") or 0.1),
                strict_entry=bool(payload.get("strict_entry", True)),
                execution_model=str(payload.get("execution_model") or "legacy_next_open"),
                force_refresh=bool(payload.get("force_refresh", False)),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/research-runs/latest")
def latest_research_run():
    try:
        return ok(research_jobs.get_latest_research_run())
    except Exception as exc:
        return _service_error(exc)


@router.get("/research-runs/{run_id}")
def get_research_run(run_id: str):
    try:
        return ok(research_jobs.get_research_run(run_id))
    except Exception as exc:
        return _service_error(exc)


@router.post("/replay-runs")
def create_replay_run(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        start = _parse_date(payload.get("start") or payload.get("start_date") or payload.get("trade_date"))
        end = _parse_date(payload.get("end") or payload.get("end_date"))
        if start is None or end is None:
            return JSONResponse(status_code=400, content=fail("INVALID_DATE", "start and end are required."))
        return ok(
            strategy_replay.create_replay_run(
                start=start,
                end=end,
                strategy_id=str(payload.get("strategy") or screening.STRATEGY_ID),
                max_symbols=int(payload.get("max_symbols") or 5000),
                min_entry_score=float(payload.get("min_entry_score") or 68),
                strict_entry=bool(payload.get("strict_entry", True)),
                execution_model=str(payload.get("execution_model") or "legacy_next_open"),
                minute_interval=str(payload.get("minute_interval") or "1m"),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                tail_entry_ma5_tolerance_pct=float(payload.get("tail_entry_ma5_tolerance_pct") or 1.5),
                included_boards=payload.get("included_boards"),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/replay-runs")
def list_replay_runs(
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=80, ge=1, le=300),
):
    try:
        return ok(strategy_replay.list_replay_runs(strategy_id=strategy, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/replay-runs/{run_id}")
def get_replay_run(run_id: int):
    try:
        return ok(strategy_replay.get_replay_run(run_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/replay-runs/{run_id}/symbols/{vt_symbol}")
def get_replay_symbol(run_id: int, vt_symbol: str):
    try:
        return ok(strategy_replay.symbol_replay(run_id, vt_symbol))
    except Exception as exc:
        return _service_error(exc)


@router.get("/strategies")
def list_strategies():
    try:
        return ok(screening.list_available_strategies())
    except Exception as exc:
        return _service_error(exc)


@router.get("/screen-runs")
def list_screen_runs(
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=120, ge=1, le=500),
):
    try:
        return ok(screening.list_screen_runs(strategy_id=strategy, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/screen-runs/{run_id}")
def get_screen_run(run_id: int):
    try:
        return ok(screening.get_run(run_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/tail-preview")
def get_tail_preview(
    trade_date: str = Query(default=""),
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=100, ge=1, le=200),
    max_symbols: int = Query(default=5000, ge=1, le=5000),
    refresh: bool = Query(default=False),
):
    try:
        return ok(
            screening.get_tail_preview(
                _parse_date(trade_date),
                strategy_id=strategy,
                max_symbols=max_symbols,
                recommendation_limit=limit,
                refresh=refresh,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/trading-dates")
def list_trading_dates(
    start: str = Query(default=""),
    end: str = Query(default=""),
    limit: int = Query(default=600, ge=1, le=2000),
):
    try:
        return ok(
            screening.list_trading_dates(
                start=_parse_date(start),
                end=_parse_date(end),
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/signals")
def list_signals(
    trade_date: str = Query(default=""),
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        return ok(screening.list_signals(_parse_date(trade_date), strategy_id=strategy, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/recommendations")
def list_recommendations(
    trade_date: str = Query(default=""),
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=screening.DEFAULT_RECOMMENDATION_LIMIT, ge=1, le=200),
):
    try:
        return ok(screening.list_recommendations(_parse_date(trade_date), strategy_id=strategy, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: int):
    try:
        return ok(screening.get_recommendation(recommendation_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/signal-history")
def get_symbol_signal_history(
    vt_symbol: str,
    strategy: str = Query(default=screening.STRATEGY_ID),
    start: str = Query(default=""),
    end: str = Query(default=""),
    min_entry_score: float = Query(default=68.0, ge=0, le=100),
    limit: int = Query(default=200, ge=1, le=1000),
):
    try:
        return ok(
            screening.symbol_signal_history(
                vt_symbol,
                strategy_id=strategy,
                start=_parse_date(start),
                end=_parse_date(end),
                min_entry_score=min_entry_score,
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/market-line")
def get_symbol_market_line(
    vt_symbol: str,
    strategy: str = Query(default=screening.STRATEGY_ID),
    start: str = Query(default=""),
    end: str = Query(default=""),
    limit: int = Query(default=1000, ge=1, le=1500),
):
    try:
        return ok(
            screening.symbol_market_line(
                vt_symbol,
                strategy_id=strategy,
                start=_parse_date(start),
                end=_parse_date(end),
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/trade-plan")
def get_symbol_trade_plan(
    vt_symbol: str,
    strategy: str = Query(default=screening.STRATEGY_ID),
):
    try:
        return ok(screening.latest_trade_plan(vt_symbol, strategy_id=strategy))
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/latest-state")
def get_latest_symbol_quant_state(
    vt_symbol: str,
    strategy: str = Query(default=screening.STRATEGY_ID),
):
    try:
        return ok(latest_symbol_quant_state(vt_symbol, strategy_id=strategy))
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/replay/latest")
def get_latest_symbol_replay(
    vt_symbol: str,
    strategy: str = Query(default=screening.STRATEGY_ID),
):
    try:
        return ok(strategy_replay.latest_symbol_replay(vt_symbol, strategy_id=strategy))
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/strategy-comparison")
def get_symbol_strategy_comparison(
    vt_symbol: str,
    start: str = Query(default=""),
    end: str = Query(default=""),
    limit: int = Query(default=80, ge=1, le=300),
):
    try:
        return ok(
            screening.symbol_strategy_comparison(
                vt_symbol,
                start=_parse_date(start),
                end=_parse_date(end),
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/symbols/{vt_symbol}/diagnostics")
def get_symbol_diagnostics(
    vt_symbol: str,
    start: str = Query(default=""),
    end: str = Query(default=""),
    backtest_id: int | None = Query(default=None, ge=1),
    signal_date: str = Query(default=""),
    limit: int = Query(default=80, ge=1, le=300),
):
    try:
        return ok(
            symbol_diagnostics_report(
                vt_symbol,
                start=_parse_date(start),
                end=_parse_date(end),
                backtest_id=backtest_id,
                signal_date=_parse_date(signal_date),
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail("QUANT_SERVICE_UNAVAILABLE", "量化筛选服务暂时不可用。", {"reason": exc.__class__.__name__}),
    )
