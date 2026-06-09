"""FastAPI entrypoint for AlphaAgent."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from alphaagent.server.api.router import api_router
from alphaagent.server.core.config import get_settings
from alphaagent.server.services.data_sync import ensure_sync_schema, start_data_sync_scheduler
from alphaagent.market.warmup import start_market_cache_warmup


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        try:
            ensure_sync_schema()
            start_data_sync_scheduler()
        except Exception:
            pass
        start_market_cache_warmup(timeout=settings.market_timeout_seconds)
        yield

    app = FastAPI(title="AlphaAgent API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
