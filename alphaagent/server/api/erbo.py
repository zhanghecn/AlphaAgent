"""二波反包打板(erbo)API:实时推荐、回测报告、历史交割单、规则契约。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.erbo import service

router = APIRouter(prefix="/erbo", tags=["erbo"])


@router.get("/live", response_model=None)
def live(trade_date: date | None = Query(default=None, alias="date")):
    """实时推荐:今日池(妖股二波潜伏名单×A/B档)× 触发状态(?date= 回看)。"""
    try:
        return ok(service.get_live(trade_date))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "ERBO_LIVE_UNAVAILABLE", "二波反包实时推荐暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/live/dates", response_model=None)
def live_dates():
    try:
        return ok({"dates": service.get_live_dates()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "ERBO_LIVE_DATES_UNAVAILABLE", "二波反包日期列表暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/backtest", response_model=None)
def backtest():
    """回测报告(物化,API 只读)。"""
    payload = service.get_backtest_report()
    if payload is None:
        return ok({"status": "unavailable",
                   "message": "回测报告尚未生成",
                   "rebuild": service.get_rebuild_status()})
    return ok({"status": "ok", "report": payload,
               "rebuild": service.get_rebuild_status()})


@router.post("/backtest/rebuild", response_model=None)
def rebuild():
    try:
        return ok(service.run_backtest_sync(source="manual"))
    except service.BacktestAlreadyRunningError:
        return ok({"status": "already_running",
                   "rebuild": service.get_rebuild_status()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "ERBO_REBUILD_UNAVAILABLE", "二波反包回测重算暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/backtest/status", response_model=None)
def backtest_status():
    return ok(service.get_rebuild_status() or {"status": "idle"})


@router.get("/ledger", response_model=None)
def ledger(trade_date: date | None = Query(default=None, alias="date"),
           month: str | None = Query(default=None)):
    """历史交割单:默认回测模拟(?month=YYYY-MM);?date= 前推实时成交。"""
    try:
        if trade_date is not None:
            return ok(service.get_forward_ledger(trade_date))
        return ok(service.get_ledger(month))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "ERBO_LEDGER_UNAVAILABLE", "二波反包交割单暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/rules", response_model=None)
def rules():
    """规则契约:A/B 档 + 死格 + 留档 + 风险声明 + 盘中手册。"""
    return ok(service.get_rules())
