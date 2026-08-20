from fastapi.testclient import TestClient

from alphaagent.server.api import market
from alphaagent.server.api import research_sectors
from alphaagent.server.main import create_app


class ExplodingAkShareAdapter:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("dashboard request must not call AkShare when a stored snapshot exists")


def test_market_dashboard_endpoints_prefer_stored_snapshots(monkeypatch) -> None:
    fund_flow = {
        "items": [{"code": "BK001", "name": "存储概念", "main_net_inflow": 123.0}],
        "total": 1,
        "sector_type": "concept",
        "status": "ready",
        "updated_at": "2026-08-20T10:00:00+08:00",
        "data_origin": "local_db",
        "storage_table": "sector_fund_flows",
    }
    hot_ranks = {
        "items": [{"stock_code": "600000", "stock_name": "存储股票", "rank": 1}],
        "total": 1,
        "status": "ready",
        "updated_at": "2026-08-20T10:00:00+08:00",
        "data_origin": "local_db",
        "storage_table": "stock_hot_ranks",
    }
    limit_pools = {
        "trade_date": "20260820",
        "pools": {"zt": {"label": "涨停池", "items": [], "total": 0}},
        "status": "ready",
        "updated_at": "2026-08-20T10:00:00+08:00",
        "data_origin": "local_db",
        "storage_table": "limit_up_pool_snapshots",
    }
    monkeypatch.setattr(
        market.market_dashboard,
        "load_fund_flow_snapshot",
        lambda **_kwargs: fund_flow,
    )
    monkeypatch.setattr(
        market.market_dashboard,
        "load_hot_rank_snapshot",
        lambda **_kwargs: hot_ranks,
    )
    monkeypatch.setattr(
        market.market_dashboard,
        "load_limit_pool_snapshot",
        lambda **_kwargs: limit_pools,
    )
    monkeypatch.setattr(market, "AkShareAdapter", ExplodingAkShareAdapter)

    client = TestClient(create_app())

    assert client.get("/api/market/fund-flow?sector_type=concept&top_n=5").json() == fund_flow
    assert client.get("/api/market/hot-ranks?limit=5").json() == hot_ranks
    assert client.get("/api/market/limit-pools").json() == limit_pools


def test_sector_ranking_prefers_stored_snapshot(monkeypatch) -> None:
    stored = {
        "items": [{"sector_id": "BK001", "name": "存储概念", "type": "concept"}],
        "total": 1,
        "sort_by": "change_pct",
        "status": "ready",
        "updated_at": "2026-08-20T10:00:00+08:00",
        "data_origin": "local_db",
        "storage_table": "sector_fund_flow_snapshots",
        "fallback_used": False,
    }
    monkeypatch.setattr(
        research_sectors.market_dashboard,
        "load_sector_ranking_snapshot",
        lambda **_kwargs: stored,
    )

    import alphaagent.data_sources.akshare_adapter as akshare_module

    monkeypatch.setattr(akshare_module, "AkShareAdapter", ExplodingAkShareAdapter)
    client = TestClient(create_app())

    assert client.get("/api/research/sectors/ranking?sector_type=concept").json() == stored
