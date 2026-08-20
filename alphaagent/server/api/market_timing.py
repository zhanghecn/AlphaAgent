"""大盘择时(金手指/银手指)端点。

GET /api/market-timing/panel 只读后端已物化的概览、K线、信号和准确率。
全市场计算由同步 worker 或管理员 POST /refresh 执行，避免页面打开时占满 CPU。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.market_timing.panel import (
    load_stored_market_timing_panel,
    refresh_market_timing_panel,
)

router = APIRouter(prefix="/market-timing", tags=["market-timing"])


@router.get("/panel", response_model=None)
def get_panel():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置, 无法计算大盘择时"),
        )
    try:
        with session_scope() as session:
            panel = load_stored_market_timing_panel(session, schema)
        if panel is None:
            return JSONResponse(
                status_code=503,
                content=fail(
                    "MARKET_TIMING_INITIALIZING",
                    "大盘择时面板正在由后台初始化，请稍后刷新。",
                ),
            )
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
            panel = refresh_market_timing_panel(session, schema)
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
