"""Health and readiness endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db.session import check_database
from alphaagent.server.services.data_sync import coverage

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return ok({"status": "ok", "service": "alphaagent-api"})


@router.get("/ready", response_model=None)
def ready():
    postgres = check_database()
    redis = check_redis()
    try:
        akshare_info = AkShareAdapter().info().to_api()
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("SERVICE_NOT_READY", "AkShare 源码包不可用。", {"reason": exc.__class__.__name__}),
        )

    return ok(
        {
            "status": "ready" if postgres["ok"] else "degraded",
            "persistence": "postgresql" if postgres["ok"] else "postgresql_unavailable",
            "cache": "redis" if redis["ok"] else "in_process_ttl",
            "postgres": "ok" if postgres["ok"] else "error",
            "redis": "ok" if redis["ok"] else "error",
            "storage": [postgres, redis],
            "market_data": [
                {
                    "name": "akshare_source_package",
                    "ok": True,
                    "message": f"source integrated: {akshare_info['version']}",
                    "checked_at": "",
                }
            ],
            "coverage": _safe_coverage(),
        }
    )


def check_redis() -> dict[str, object]:
    settings = get_settings()
    if not settings.redis_url.strip():
        return {"name": "redis", "ok": False, "message": "REDIS_URL 未配置", "checked_at": ""}
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        client.close()
        return {"name": "redis", "ok": True, "message": "PING ok", "checked_at": ""}
    except Exception as exc:
        return {"name": "redis", "ok": False, "message": exc.__class__.__name__, "checked_at": ""}


def _safe_coverage() -> dict[str, object]:
    try:
        return coverage()
    except Exception as exc:
        return {"status": "unavailable", "reason": exc.__class__.__name__}
