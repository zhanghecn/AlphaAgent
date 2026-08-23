"""趋势弱转强(二板弱转强打板)API:实时推荐、回测报告、历史交割单、规则契约与同花顺条件。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.weak_to_strong import service

router = APIRouter(prefix="/weak-to-strong", tags=["weak-to-strong"])


@router.get("/live", response_model=None)
def live(trade_date: date | None = Query(default=None, alias="date")):
    """实时推荐:今日池(A1/A2/B 三组)× 触发状态(盘中 30s 轮询;?date= 回看历史)。"""
    try:
        return ok(service.get_live(trade_date))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "W2S_LIVE_UNAVAILABLE", "趋势弱转强实时推荐暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/live/dates", response_model=None)
def live_dates():
    """可回看交易日(有池的日期,最新在前)。"""
    try:
        return ok({"dates": service.get_live_dates()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "W2S_LIVE_DATES_UNAVAILABLE", "趋势弱转强日期列表暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/backtest", response_model=None)
def backtest():
    """回测报告(物化,CLI/调度写库,API 只读)。"""
    try:
        payload = service.get_backtest_report()
        rebuild = service.get_rebuild_status()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "W2S_BACKTEST_UNAVAILABLE", "趋势弱转强回测报告暂时不可用",
            {"reason": exc.__class__.__name__}))
    if payload is None:
        return ok({"status": "unavailable", "message": "趋势弱转强回测尚未运行",
                   "rebuild": rebuild})
    report = {k: v for k, v in payload.items() if k != "ledger_days"}
    return ok({"status": "ok", "is_backtest": True, "report": report,
               "rebuild": rebuild})


@router.post("/backtest/rebuild", response_model=None)
def backtest_rebuild():
    """手动触发回测全量重算(后台线程)。"""
    try:
        result = service.start_backtest_rebuild()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "W2S_BACKTEST_REBUILD_UNAVAILABLE", "趋势弱转强回测重算暂时不可用",
            {"reason": exc.__class__.__name__}))
    if result.get("already_running"):
        return JSONResponse(status_code=409, content=fail(
            "W2S_BACKTEST_RUNNING", "趋势弱转强回测正在重算", result))
    return JSONResponse(status_code=202, content=ok(result))


@router.get("/backtest/status", response_model=None)
def backtest_status():
    """回测重算状态(前端轮询)。"""
    try:
        return ok(service.get_rebuild_status())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "W2S_BACKTEST_STATUS_UNAVAILABLE", "趋势弱转强回测状态暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/ledger", response_model=None)
def ledger(trade_date: date | None = Query(default=None, alias="date"),
           month: str | None = Query(default=None)):
    """历史交割单:默认回测模拟(?month=YYYY-MM 切片,默认最新月);?date= 查前推实时成交。"""
    try:
        if trade_date is not None:
            return ok(service.get_forward_ledger(trade_date))
        return ok(service.get_ledger(month))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "W2S_LEDGER_UNAVAILABLE", "趋势弱转强交割单暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/rules", response_model=None)
def rules():
    """规则契约:分组规则 + 已删除/证伪清单 + 风险声明 + 同花顺条件串 ×3。"""
    return ok(service.get_rules())
