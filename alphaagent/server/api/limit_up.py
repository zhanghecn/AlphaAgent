"""Limit-up Top5 research dashboard and proxy backtest endpoints."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db.session import is_database_configured
from alphaagent.server.services.limit_up.service import (
    get_limit_up_dashboard,
    get_limit_up_proxy_backtest,
)
from alphaagent.server.services.limit_up.live_service import (
    get_latest_live_snapshot,
    refresh_live_snapshot,
)
from alphaagent.server.services.limit_up.history_service import (
    get_history_backtest as get_limit_up_history_backtest,
    get_history_dates as get_limit_up_history_dates,
    get_history_day as get_limit_up_history_day,
    get_history_factor_audit as get_limit_up_history_factor_audit,
    get_history_ledger as get_limit_up_history_ledger,
    get_lane_history_backtest as get_limit_up_lane_history_backtest,
    get_history_model_report as get_limit_up_history_model_report,
    get_history_status as get_limit_up_history_status,
    get_sector_warmup_research as get_limit_up_sector_warmup_research,
    start_history_rebuild as start_limit_up_history_rebuild,
)
from alphaagent.server.services.limit_up.signal_service import (
    get_limit_up_signal_dates,
    get_limit_up_signals,
)
from alphaagent.server.services.limit_up.forward_validation import (
    get_forward_validation as get_limit_up_forward_validation,
)
from alphaagent.server.services.limit_up.data_quality import (
    backfill_limit_up_event_minutes,
    get_limit_up_data_quality,
)
from alphaagent.server.services.limit_up.minute_backfill_batch import (
    MAX_GAP_BATCH_SIZE,
    MinuteBackfillBatchBusyError,
    MinuteBackfillBatchNotFoundError,
    get_minute_backfill_batch as get_limit_up_minute_backfill_batch,
    start_minute_backfill_batch as start_limit_up_minute_backfill_batch,
)

router = APIRouter(prefix="/limit-up", tags=["limit-up"])


@router.get("/dates", response_model=None)
def trade_dates():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取打板交易日"),
        )
    try:
        return ok(get_limit_up_signal_dates())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/dashboard", response_model=None)
def dashboard(
    trade_date: date | None = Query(default=None, alias="date"),
):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法生成打板研究工作台"),
        )
    try:
        return ok(get_limit_up_dashboard(trade_date))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/live", response_model=None)
def live_snapshot():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取实时打板信号"),
        )
    try:
        return ok(get_latest_live_snapshot())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.post("/live/refresh", response_model=None)
def refresh_snapshot():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法保存实时打板信号"),
        )
    try:
        return ok(refresh_live_snapshot())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/signals", response_model=None)
def signals(
    trade_date: date = Query(alias="date"),
    as_of: datetime | None = Query(default=None),
):
    if as_of is not None and as_of.date() != trade_date:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_AS_OF", "查询时点必须属于所选交易日"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取历史打板信号"),
        )
    try:
        return ok(get_limit_up_signals(trade_date, as_of))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/status", response_model=None)
def history_status():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取全历史打板状态"),
        )
    try:
        return ok(get_limit_up_history_status())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.post("/history/rebuild", response_model=None)
def history_rebuild():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法构建全历史打板账本"),
        )
    try:
        result = start_limit_up_history_rebuild()
        if result.get("already_running"):
            return JSONResponse(
                status_code=409,
                content=fail("HISTORY_REBUILD_RUNNING", "全历史打板账本正在构建", result),
            )
        return JSONResponse(status_code=202, content=ok(result))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/dates", response_model=None)
def history_dates():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取全历史交易日"),
        )
    try:
        return ok(get_limit_up_history_dates())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/day", response_model=None)
def history_day(trade_date: date = Query(alias="date")):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取历史打板结果"),
        )
    try:
        result = get_limit_up_history_day(trade_date)
        if result.get("status") == "not_found":
            return JSONResponse(
                status_code=404,
                content=fail(
                    "HISTORY_DATE_NOT_FOUND",
                    "所选日期不在可靠全历史窗口内",
                    {"date": trade_date.isoformat()},
                ),
            )
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/ledger", response_model=None)
def history_ledger(
    trade_date: date = Query(alias="date"),
    lane: Literal["first_board", "one_to_two", "two_to_three", "high_board"] | None = Query(
        default=None
    ),
    exit_mode: Literal["dynamic", "next_open", "next_close"] = Query(default="dynamic"),
):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取历史打板交割单"),
        )
    try:
        result = get_limit_up_history_ledger(
            trade_date,
            lane=lane,
            exit_mode=exit_mode,
        )
        if result.get("status") == "not_found":
            return JSONResponse(
                status_code=404,
                content=fail(
                    "HISTORY_DATE_NOT_FOUND",
                    "所选日期不在可靠全历史窗口内",
                    {"date": trade_date.isoformat()},
                ),
            )
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/backtest", response_model=None)
def history_backtest(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    exit_mode: Literal["dynamic", "next_open", "next_close"] = Query(default="dynamic"),
    entry_mode: Literal["auction", "sweep", "tail", "next_auction"] = Query(default="auction"),
    lane: Literal[
        "portfolio",
        "first_board",
        "one_to_two",
        "two_to_three",
        "high_board",
    ]
    | None = Query(default=None),
):
    if start and end and start > end:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_DATE_RANGE", "开始日期不能晚于结束日期"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法执行全历史打板回测"),
        )
    try:
        if lane is not None:
            return ok(
                get_limit_up_lane_history_backtest(
                    start,
                    end,
                    lane=lane,
                    exit_mode=exit_mode,
                )
            )
        return ok(get_limit_up_history_backtest(start, end, entry_mode, exit_mode))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/sector-warmup", response_model=None)
def history_sector_warmup(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    if start and end and start > end:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_DATE_RANGE", "开始日期不能晚于结束日期"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法研究板块预热"),
        )
    try:
        return ok(get_limit_up_sector_warmup_research(start, end))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/factors", response_model=None)
def history_factors(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    exit_mode: Literal["next_open", "next_close"] = Query(default="next_open"),
    entry_mode: Literal["auction", "sweep", "tail", "next_auction"] = Query(default="auction"),
):
    if start and end and start > end:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_DATE_RANGE", "开始日期不能晚于结束日期"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法审计打板因子"),
        )
    try:
        return ok(get_limit_up_history_factor_audit(start, end, entry_mode, exit_mode))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/history/model-report", response_model=None)
def history_model_report(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    exit_mode: Literal["next_open", "next_close"] = Query(default="next_open"),
    entry_mode: Literal["auction", "sweep", "tail", "next_auction"] = Query(default="auction"),
    lane: Literal["first_board", "one_to_two", "two_to_three", "high_board"] | None = Query(
        default=None
    ),
):
    if start and end and start > end:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_DATE_RANGE", "开始日期不能晚于结束日期"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法运行打板净期望模型"),
        )
    try:
        if lane is None:
            return ok(
                get_limit_up_history_model_report(start, end, entry_mode, exit_mode)
            )
        return ok(
            get_limit_up_history_model_report(
                start,
                end,
                entry_mode,
                exit_mode,
                board_lane=lane,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/forward-validation", response_model=None)
def forward_validation(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    exit_mode: Literal["next_open", "next_close"] = Query(default="next_open"),
    entry_mode: Literal["auction", "sweep", "tail", "next_auction"] = Query(
        default="auction"
    ),
):
    if start and end and start > end:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_DATE_RANGE", "开始日期不能晚于结束日期"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取打板前向观察账本"),
        )
    try:
        return ok(get_limit_up_forward_validation(start, end, entry_mode, exit_mode))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/data-quality", response_model=None)
def data_quality():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法审计打板数据质量"),
        )
    try:
        return ok(get_limit_up_data_quality())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.post("/data-quality/minute-backfill", response_model=None)
def data_quality_minute_backfill(payload: dict[str, object] = Body(default_factory=dict)):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法补齐涨停事件分钟线"),
        )
    try:
        max_gaps = int(payload.get("max_gaps") or 20)
    except (TypeError, ValueError):
        max_gaps = 0
    if max_gaps < 1 or max_gaps > 200:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_GAP_BATCH_SIZE", "单次补数范围必须为1到200个缺口"),
        )
    raw_dry_run = payload.get("dry_run", True)
    dry_run = raw_dry_run if isinstance(raw_dry_run, bool) else str(raw_dry_run).lower() == "true"
    try:
        return ok(backfill_limit_up_event_minutes(max_gaps=max_gaps, dry_run=dry_run))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.post("/data-quality/minute-backfill/start", response_model=None)
def start_data_quality_minute_backfill(
    payload: dict[str, object] = Body(default_factory=dict),
):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法后台补齐涨停事件分钟线"),
        )
    max_gaps = _gap_batch_size(payload, default=MAX_GAP_BATCH_SIZE)
    if max_gaps is None:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_GAP_BATCH_SIZE", "单次补数范围必须为1到200个缺口"),
        )
    try:
        batch = start_limit_up_minute_backfill_batch(max_gaps=max_gaps)
        return JSONResponse(status_code=202, content=ok(batch))
    except MinuteBackfillBatchBusyError as exc:
        return JSONResponse(
            status_code=409,
            content=fail(
                "DATA_SYNC_BATCH_BUSY",
                "另一数据同步批次正在运行，请等待其完成后再补分钟数据",
                {
                    "batch_id": exc.batch.get("id"),
                    "jobs": [
                        job.get("job_id")
                        for job in exc.batch.get("jobs", [])
                        if isinstance(job, dict)
                    ],
                },
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/data-quality/minute-backfill/batches/{batch_id}", response_model=None)
def data_quality_minute_backfill_batch(batch_id: str):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取分钟补数批次"),
        )
    try:
        return ok(get_limit_up_minute_backfill_batch(batch_id))
    except MinuteBackfillBatchNotFoundError:
        return JSONResponse(
            status_code=404,
            content=fail(
                "MINUTE_BACKFILL_BATCH_NOT_FOUND",
                "分钟补数批次不存在或不属于打板数据补数",
                {"batch_id": batch_id},
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/backtest", response_model=None)
def proxy_backtest(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    exit_mode: Literal["next_open", "next_close"] = Query(default="next_open"),
    entry_mode: Literal["auction", "sweep", "tail", "next_auction"] | None = Query(
        default=None
    ),
):
    if start and end and start > end:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_DATE_RANGE", "开始日期不能晚于结束日期"),
        )
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法执行打板代理回测"),
        )
    try:
        if entry_mode is not None:
            return ok(get_limit_up_history_backtest(start, end, entry_mode, exit_mode))
        return ok(get_limit_up_proxy_backtest(start, end, exit_mode))
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=fail(
            "LIMIT_UP_RESEARCH_ERROR",
            f"打板研究计算失败: {exc}",
            {"reason": exc.__class__.__name__},
        ),
    )


def _gap_batch_size(payload: dict[str, object], *, default: int) -> int | None:
    raw_value = payload.get("max_gaps", default)
    if isinstance(raw_value, bool):
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= MAX_GAP_BATCH_SIZE else None
