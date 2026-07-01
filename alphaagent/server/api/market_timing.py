"""大盘择时(金手指/银手指)端点。

GET /api/market-timing/panel  返回全套(概览+K线+信号+准确率), 前端一次拿。
首次请求触发全量计算(约1分钟, 含全市场广度), 之后命中进程缓存(~30分钟)秒回。
?force=true 强制刷新。
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.quant.market_timing.panel import get_market_timing_panel

router = APIRouter(prefix="/market-timing", tags=["market-timing"])


@router.get("/panel", response_model=None)
def get_panel(force: bool = Query(default=False)):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置, 无法计算大盘择时"),
        )
    try:
        with session_scope() as session:
            panel = get_market_timing_panel(session, schema, force_refresh=force)
        return ok(panel)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=fail(
                "MARKET_TIMING_ERROR",
                f"大盘择时计算失败: {exc}",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.post("/refresh", response_model=None)
def refresh_panel():
    """强制重算并落库(供定时任务/手动触发, 写完后续 /panel 读库秒回)。"""
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置"),
        )
    try:
        with session_scope() as session:
            panel = get_market_timing_panel(session, schema, force_refresh=True)
        return ok(
            {
                "computed_at": panel.get("generated_at"),
                "sample_range": panel.get("sample_range"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=fail(
                "MARKET_TIMING_ERROR",
                f"刷新失败: {exc}",
                {"reason": exc.__class__.__name__},
            ),
        )
