"""低吸日线 API：v3/v4 因子的实时推荐、回测报告与历史交割单。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.market.cache import TTLCache
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.low_suction.daily_picks_service import (
    get_daily_backtest_report,
    get_daily_backtest_rebuild_status,
    get_live_recommendation_dates,
    get_live_recommendations,
    start_daily_backtest_rebuild,
)
from alphaagent.server.services.low_suction.guide_cases import (
    load_guide_cases_payload,
)


router = APIRouter(prefix="/low-suction", tags=["low-suction"])

# 说明书案例：策展清单与历史日线一天一变（盘后同步后才可能更新），
# 60s 进程缓存兜底刷新抖动。
_GUIDE_CASES_CACHE_TTL_SECONDS = 60
_guide_cases_cache: TTLCache = TTLCache(max_items=4)


@router.get("/live", response_model=None)
def live_recommendations(
    trend_page: int = Query(default=1, ge=1),
    oversold_page: int = Query(default=1, ge=1),
    trade_date: date | None = Query(default=None, alias="date"),
):
    """实时推荐：两族各自分页，持久化快照中最多保留排名前 100 只。"""

    try:
        return ok(
            get_live_recommendations(
                trend_page=trend_page,
                oversold_page=oversold_page,
                trade_date=trade_date,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_LIVE_UNAVAILABLE",
                "低吸实时推荐暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/live/dates", response_model=None)
def live_recommendation_dates():
    """可回看的低吸推荐交易日（最新在前）。"""

    try:
        return ok({"dates": get_live_recommendation_dates()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_LIVE_DATES_UNAVAILABLE",
                "低吸推荐日期暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/backtest", response_model=None)
def daily_backtest():
    """回测：全量分数段统计 + 两族各前五模拟 + 权益曲线（CLI 物化，API 读库）。"""

    try:
        payload = get_daily_backtest_report()
        rebuild = get_daily_backtest_rebuild_status()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_BACKTEST_UNAVAILABLE",
                "低吸回测报告暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )
    if payload is None:
        return ok(
            {
                "status": "unavailable",
                "message": "低吸日线回测尚未运行",
                "rebuild": rebuild,
            }
        )
    report = {key: value for key, value in payload.items() if key != "ledger_days"}
    return ok({"status": "ok", "is_backtest": True, "report": report, "rebuild": rebuild})


@router.post("/backtest/rebuild", response_model=None)
def daily_backtest_rebuild():
    """手动触发低吸回测物化（后台线程，全量重算写库）。"""

    try:
        result = start_daily_backtest_rebuild()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_BACKTEST_REBUILD_UNAVAILABLE",
                "低吸回测重算暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )
    if result.get("already_running"):
        return JSONResponse(
            status_code=409,
            content=fail("LOW_SUCTION_BACKTEST_RUNNING", "低吸回测正在重算", result),
        )
    return JSONResponse(status_code=202, content=ok(result))


@router.get("/backtest/status", response_model=None)
def daily_backtest_status():
    """读取回测重算状态（前端轮询 building→ready/failed）。"""

    try:
        return ok(get_daily_backtest_rebuild_status())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_BACKTEST_STATUS_UNAVAILABLE",
                "低吸回测状态暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/ledger", response_model=None)
def daily_ledger():
    """历史交割单：两族各前五模拟的最近交易日逐票明细（回测模拟，非实盘）。"""

    try:
        payload = get_daily_backtest_report()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_LEDGER_UNAVAILABLE",
                "低吸历史交割单暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )
    if payload is None:
        return ok({"status": "unavailable", "message": "低吸日线回测尚未运行", "ledger_days": []})
    return ok(
        {
            "status": "ok",
            "is_backtest": True,
            "ledger_days": payload.get("ledger_days", []),
            "coverage": payload.get("coverage"),
            "label_convention": payload.get("label_convention"),
        }
    )


@router.get("/guide/cases", response_model=None)
def guide_cases():
    """说明书案例：策展经典案例按规则归组 + 现算 D+1/D+3/D+5 收益。"""

    try:
        return ok(
            _guide_cases_cache.get_or_set(
                "low-suction:guide:cases:v1",
                _GUIDE_CASES_CACHE_TTL_SECONDS,
                load_guide_cases_payload,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content=fail(
                "LOW_SUCTION_GUIDE_CASES_UNAVAILABLE",
                "低吸说明书案例数据暂时不可用",
                {"reason": exc.__class__.__name__},
            ),
        )
