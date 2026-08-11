"""FastAPI entrypoint for AlphaAgent."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from alphaagent.server.api.router import api_router
from alphaagent.server.core.config import get_settings
from alphaagent.server.services.data_sync import ensure_sync_schema, start_data_sync_scheduler
from alphaagent.market.warmup import start_market_cache_warmup
from alphaagent.server.services.market_timing.panel import start_intraday_refresher
from alphaagent.server.services.limit_up.history_service import start_backtest_cache_warmup
from alphaagent.server.services.limit_up.next_session_plan import start_next_session_plan_warmup


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        try:
            owns_scheduler = settings.startup_data_sync_scheduler
            ensure_sync_schema(recover_interrupted=owns_scheduler)
            if owns_scheduler:
                start_data_sync_scheduler()
            if settings.startup_next_session_plan_warmup:
                start_next_session_plan_warmup()
        except Exception:
            pass
        if settings.startup_backtest_warmup:
            start_backtest_cache_warmup()
        if settings.startup_market_cache_warmup:
            start_market_cache_warmup(timeout=settings.market_timeout_seconds)
        if settings.startup_intraday_refresher:
            start_intraday_refresher()
        yield

    app = FastAPI(title="AlphaAgent API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        # 走网关同源后 CORS 基本不触发；这里补全方法，兼容直连调试与未来扩展。
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
