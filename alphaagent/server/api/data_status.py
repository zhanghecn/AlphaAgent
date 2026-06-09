"""Data status endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.providers import RealMarketDataClient
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import ok
from alphaagent.server.db.session import check_database
from alphaagent.server.api.health import check_redis
from alphaagent.server.services.data_sync import coverage

router = APIRouter(tags=["data"])


@router.get("/data/status")
def data_status():
    settings = get_settings()
    client = RealMarketDataClient(timeout=settings.market_timeout_seconds)
    data_sources = [status.to_api() for status in client.source_status()]
    try:
        akshare_info = AkShareAdapter().info().to_api()
        data_sources.append(
            {
                "name": "akshare_source_package",
                "ok": True,
                "message": f"source integrated: {akshare_info['version']} ({akshare_info['package_dir']})",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as exc:
        data_sources.append(
            {
                "name": "akshare_source_tree",
                "ok": False,
                "message": exc.__class__.__name__,
                "checked_at": "",
            }
        )
    postgres = check_database()
    redis = check_redis()
    try:
        local_coverage = coverage()
        tables = local_coverage.get("tables", {})
    except Exception as exc:
        local_coverage = {"status": "unavailable", "reason": exc.__class__.__name__}
        tables = {}
    return ok(
        {
            "persistence": "postgresql" if postgres["ok"] else "postgresql_unavailable",
            "cache": "redis" if redis["ok"] else "in_process_ttl",
            "storage": [postgres, redis],
            "data_sources": data_sources,
            "coverage": local_coverage,
            "tables": tables,
            "notes": [
                "历史 K 线、股票清单、板块清单和板块关系输入优先同步到 PostgreSQL，本地表用于提速和后续量化复用。",
                "页面仍可在本地库缺数据时回退 AkShare 实时接口；同步管理模块用于补齐覆盖率并记录每次同步结果。",
            ],
        }
    )
