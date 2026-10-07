"""低位一接二(首板次日打二板)API:实时推荐、回测报告、规则契约。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.first_relay import service

router = APIRouter(prefix="/first-relay", tags=["first-relay"])


@router.get("/live", response_model=None)
def live(trade_date: date | None = Query(default=None, alias="date")):
    """实时推荐:今日首板池 × G1/S1 触发状态(?date= 回看历史)。"""
    try:
        return ok(service.get_live(trade_date))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "J12_LIVE_UNAVAILABLE", "一接二实时推荐暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/live/dates", response_model=None)
def live_dates():
    """可回看交易日(有池的日期,最新在前)。"""
    try:
        return ok({"dates": service.get_live_dates()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "J12_LIVE_DATES_UNAVAILABLE", "一接二日期列表暂时不可用",
            {"reason": exc.__class__.__name__}))


@router.get("/backtest", response_model=None)
def backtest():
    """回测报告(物化,CLI/调度写库,API 只读)。"""
    try:
        payload = service.get_backtest_report()
        rebuild = service.get_rebuild_status()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "J12_BACKTEST_UNAVAILABLE", "一接二回测报告暂时不可用",
            {"reason": exc.__class__.__name__}))
    if payload is None:
        return ok({"status": "unavailable", "message": "一接二回测尚未运行",
                   "rebuild": rebuild})
    # ledger_days 保留(月度明细表用;体量=69个月,可忽略)
    return ok({"status": "ok", "is_backtest": True, "report": payload,
               "rebuild": rebuild})


@router.post("/backtest/rebuild", response_model=None)
def backtest_rebuild():
    """手动触发回测全量重算(同步执行,约1~2分钟)。"""
    try:
        result = service.start_backtest_rebuild()
    except service.BacktestAlreadyRunningError:
        return JSONResponse(status_code=409, content=fail(
            "J12_BACKTEST_RUNNING", "一接二回测重算已在执行", {}))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "J12_BACKTEST_REBUILD_FAILED", "一接二回测重算失败",
            {"error": str(exc)[:500]}))
    return ok(result)


@router.get("/rules", response_model=None)
def rules():
    """规则契约:口诀/分支定义/毒格/信息层文案。"""
    return ok(service.get_rules())


@router.post("/eod-finalize", response_model=None)
def eod_finalize():
    """收盘后主链:按最新日线生成下一交易日池。"""
    try:
        return ok(service.run_eod_finalize())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content=fail(
            "J12_EOD_FAILED", "一接二EOD池生成失败",
            {"error": str(exc)[:500]}))
