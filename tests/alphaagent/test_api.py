from fastapi.testclient import TestClient

from alphaagent.server.api import stocks
from alphaagent.server.main import create_app


class FakeQuote:
    ok = True

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.name = str(payload.get("name", ""))

    def to_api(self) -> dict[str, object]:
        return self.payload


class FakeStatus:
    ok = True

    def to_api(self) -> dict[str, object]:
        return {"name": "fake_market", "ok": True, "message": "ok", "checked_at": "2026-06-05T15:30:00+08:00"}


class FakeMarketClient:
    def market_overview(self) -> dict[str, object]:
        return {
            "trade_date": "2026-06-05",
            "market_state": "RANGE",
            "indices": [self._index_payload()],
            "active_stocks": [],
            "source": "fake",
            "updated_at": "2026-06-05T15:30:00+08:00",
        }

    def list_stocks(self, page: int = 1, page_size: int = 50, sort: str = "mktcap") -> dict[str, object]:
        return {
            "items": [self._stock_payload()],
            "page": page,
            "page_size": page_size,
            "total": 1,
            "source": sort,
        }

    def search_stocks(self, query: str, page_size: int = 50) -> dict[str, object]:
        return self.list_stocks(page_size=page_size)

    def stock_detail(self, symbol: str, exchange: str | None = None) -> dict[str, object]:
        if symbol == "920206":
            return {
                **self._stock_payload(),
                "symbol": "920206",
                "exchange": "BSE",
                "vt_symbol": "920206.BSE",
                "name": "N彩客",
            }
        payload = self._stock_payload()
        payload["symbol"] = symbol
        payload["exchange"] = exchange or "SSE"
        payload["vt_symbol"] = f"{symbol}.{exchange or 'SSE'}"
        return payload

    def list_sectors(self, sector_type: str = "") -> dict[str, object]:
        concept_items = [
            {"id": "chgn_700458", "name": "半导体", "type": "concept", "path": ["概念"]},
            {"id": "chgn_701159", "name": "CPO概念", "type": "concept", "path": ["概念"]},
            {"id": "chgn_700740", "name": "PCB概念", "type": "concept", "path": ["概念"]},
            {"id": "chgn_700736", "name": "光纤光缆", "type": "concept", "path": ["概念"]},
            {"id": "BK1136", "name": "光通信模块", "type": "concept", "path": ["概念", "东方财富"]},
            {"id": "BK1128", "name": "CPO概念", "type": "concept", "path": ["概念", "东方财富"]},
            {"id": "BK0999", "name": "昨日涨停", "type": "concept", "path": ["概念", "东方财富"]},
            {"id": "BK1643", "name": "小盘股", "type": "concept", "path": ["概念", "东方财富"], "stock_count": 996},
            {"id": "BK1672", "name": "破发股", "type": "concept", "path": ["概念", "东方财富"], "stock_count": 639},
            {"id": "BK1158", "name": "微盘股", "type": "concept", "path": ["概念", "东方财富"], "stock_count": 399},
            {"id": "BK0523", "name": "新材料", "type": "concept", "path": ["概念", "东方财富"], "stock_count": 384},
        ]
        industry_items = [
            {"id": "sw_yx", "name": "银行", "type": "industry", "path": ["行业"]},
            {"id": "sw_bdt", "name": "半导体", "type": "industry", "path": ["行业"]},
            {"id": "BK1205", "name": "机械设备", "type": "industry", "path": ["行业", "东方财富"], "stock_count": 613},
            {"id": "BK1206", "name": "基础化工", "type": "industry", "path": ["行业", "东方财富"], "stock_count": 448},
        ]
        if sector_type == "concept":
            items = concept_items
        elif sector_type == "theme":
            items = []
        elif sector_type == "industry" or not sector_type:
            items = industry_items
        else:
            items = []
        return {
            "items": items,
            "type": sector_type or "industry",
            "source": "fake_sector",
        }

    def search_boards(self, query: str, limit: int = 20) -> dict[str, object]:
        del limit
        if query.upper() == "CPO":
            items = [{"id": "BK1128", "name": "CPO概念", "type": "concept", "path": ["概念", "东方财富"], "source": "fake_board_search"}]
        elif query == "光纤":
            items = [{"id": "BK1660", "name": "光纤概念", "type": "concept", "path": ["概念", "东方财富"], "source": "fake_board_search"}]
        else:
            items = [{"id": "BK1036", "name": "半导体", "type": "industry", "path": ["行业", "东方财富"], "source": "fake_board_search"}]
        return {"query": query, "items": items, "total": len(items), "source": "fake_board_search"}

    def sector_stocks(
        self,
        sector_id: str,
        page: int = 1,
        page_size: int = 50,
        sort: str = "changepercent",
        with_returns: bool = False,
        q: str = "",
    ) -> dict[str, object]:
        del sort, q
        stocks = [self._stock_payload(), self._stock_payload("600001", "SSE", "动态样本")]
        if str(sector_id) in {"BK1128", "chgn_701159"}:
            stocks = [self._stock_payload(), self._stock_payload("600010", "SSE", "搜索样本")]
        elif str(sector_id) in {"BK1036", "chgn_700458", "sw_bdt"}:
            stocks = [self._stock_payload(), self._stock_payload("600020", "SSE", "行业样本")]
        if with_returns:
            stocks = [{**stock, "return_5d": 1.1, "return_10d": 2.2, "return_20d": 3.3} for stock in stocks]
        return {
            "sector_id": sector_id,
            "items": stocks[:page_size],
            "page": page,
            "page_size": page_size,
            "total": len(stocks),
            "source": "fake_sector_stocks",
        }

    def sector_trend(self, sector_id: str, page_size: int = 100, pages: int = 3) -> dict[str, object]:
        del page_size, pages
        return {
            "sector_id": sector_id,
            "trend_state": "UP",
            "sample_size": 3,
            "rise_count": 2,
            "flat_count": 0,
            "fall_count": 1,
            "rise_ratio": 66.67,
            "fall_ratio": 33.33,
            "avg_change_pct": 1.12,
            "turnover_weighted_change_pct": 1.28,
            "market_cap_weighted_change_pct": 0.92,
            "turnover": 1230000000,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "top_gainers": [self._stock_payload()],
            "top_losers": [],
            "source": "fake_sector_stocks",
        }

    def stock_bars(
        self,
        symbol: str,
        exchange: str | None = None,
        limit: int = 90,
        interval: str = "1d",
    ) -> dict[str, object]:
        if symbol == "920206":
            raise IndexError("no BSE bars")
        return {
            "symbol": symbol,
            "exchange": exchange or "SSE",
            "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
            "interval": interval,
            "items": [
                {
                    "trade_date": "2026-06-05",
                    "open": 9.18,
                    "close": 9.34,
                    "high": 9.35,
                    "low": 9.18,
                    "volume": 74572522,
                    "turnover": 692089681,
                    "change_pct": 1.63,
                }
            ],
            "source": "fake_kline",
        }

    def get_indices(self) -> list[FakeQuote]:
        return [FakeQuote(self._index_payload())]

    def index_detail(self, symbol: str, exchange: str | None = None, name: str | None = None) -> dict[str, object]:
        payload = self._index_payload()
        payload["symbol"] = symbol
        payload["exchange"] = exchange or "SSE"
        payload["vt_symbol"] = f"{symbol}.{exchange or 'SSE'}"
        if name:
            payload["name"] = name
        return payload

    def get_quotes(self, symbols) -> list[FakeQuote]:
        return [FakeQuote(self._index_payload())]

    def source_status(self) -> list[FakeStatus]:
        return [FakeStatus()]

    def stock_business(self, symbol: str, exchange: str | None = None) -> dict[str, object]:
        if symbol == "920206":
            raise KeyError("no business")
        return {
            "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
            "summary": "主营业务",
            "business_scope": "经营范围",
            "main_products": ["产品"],
            "source": "fake_business",
        }

    def stock_sectors(self, symbol: str, exchange: str | None = None) -> dict[str, object]:
        return {
            "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
            "items": [{"id": "fake_sector", "name": "通信设备", "type": "industry"}],
            "source": "fake_sector",
        }

    def stock_industry_chain(self, symbol: str, exchange: str | None = None) -> dict[str, object]:
        if symbol == "920206":
            raise KeyError("no chain")
        return {
            "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
            "chain_name": "通信设备 / 产品",
            "upstream": [],
            "midstream": ["通信设备", "产品"],
            "downstream": [],
            "source": "fake_chain",
        }

    def stock_industry_chain_from_data(
        self,
        symbol: str,
        exchange: str | None,
        business: dict[str, object],
        sectors: list[dict[str, object]],
    ) -> dict[str, object]:
        del business, sectors
        return self.stock_industry_chain(symbol, exchange)

    def _stock_payload(self, symbol: str = "600000", exchange: str = "SSE", name: str = "浦发银行") -> dict[str, object]:
        return {
            "symbol": symbol,
            "exchange": exchange,
            "vt_symbol": f"{symbol}.{exchange}",
            "name": name,
            "last_price": 9.34,
            "change_pct": 1.63,
            "turnover": 692089681,
            "source": "fake",
        }

    def _index_payload(self) -> dict[str, object]:
        return {
            "symbol": "000001",
            "exchange": "SSE",
            "vt_symbol": "000001.SSE",
            "name": "上证指数",
            "last_price": 4027.73,
            "change": -30.04,
            "change_pct": -0.74,
            "source": "fake",
        }


def patch_clients(monkeypatch) -> None:
    from alphaagent.server.api import data_status, indices, industry_chains, market, sectors, stocks

    fake = lambda timeout=8.0: FakeMarketClient()
    monkeypatch.setattr(data_status, "RealMarketDataClient", fake)
    monkeypatch.setattr(indices, "RealMarketDataClient", fake)
    monkeypatch.setattr(industry_chains, "RealMarketDataClient", fake)
    monkeypatch.setattr(market, "RealMarketDataClient", fake)
    monkeypatch.setattr(sectors, "RealMarketDataClient", fake)
    monkeypatch.setattr(stocks, "RealMarketDataClient", fake)


class FakeAkShareInfo:
    def to_api(self) -> dict[str, object]:
        return {
            "name": "akshare",
            "version": "1.18.64",
            "source_root": "/app/third_party/akshare",
            "package_dir": "/app/third_party/akshare/akshare",
        }


class FakeAkShareAdapter:
    def info(self) -> FakeAkShareInfo:
        return FakeAkShareInfo()

    def probe(self) -> dict[str, object]:
        return {
            "name": "akshare",
            "version": "1.18.64",
            "ok": True,
            "checks": [
                {"name": "source_tree", "ok": True, "count": 1, "sample": self.info().to_api()},
                {"name": "a_share_spot", "ok": True, "count": 200, "sample": [self._stock()]},
            ],
            "started_at": "2026-06-08T00:00:00+00:00",
            "finished_at": "2026-06-08T00:00:01+00:00",
        }

    def a_share_spot(self, limit: int = 20) -> dict[str, object]:
        del limit
        return {"items": [self._stock()], "total": 200, "source": "akshare.stock_zh_a_spot_tx"}

    def board_names(self, board_type: str = "concept", limit: int = 20) -> dict[str, object]:
        del limit
        return {"items": [{"id": "BK0736", "name": "光纤光缆", "type": board_type}], "total": 1, "type": board_type}

    def board_members(self, board_type: str, symbol: str, limit: int = 100) -> dict[str, object]:
        del limit
        return {"items": [self._stock()], "total": 1, "type": board_type, "symbol": symbol}

    def stock_news(self, symbol: str, limit: int = 10) -> dict[str, object]:
        del limit
        return {"items": [{"关键词": symbol, "新闻标题": "亨通光电新闻"}], "total": 1, "symbol": symbol}

    def stock_business_segments(self, symbol: str, exchange: str | None = None, limit: int = 30) -> dict[str, object]:
        del limit
        return {
            "items": [{"股票代码": symbol, "主营构成": "制造业", "收入比例": 0.97}],
            "total": 1,
            "symbol": symbol,
            "exchange": exchange or "SSE",
            "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
            "source": "akshare.stock_zygc_em",
        }

    def _stock(self) -> dict[str, object]:
        return {
            "symbol": "600487",
            "exchange": "SSE",
            "vt_symbol": "600487.SSE",
            "name": "亨通光电",
            "last_price": 15.26,
            "return_5d": 5.1,
            "return_10d": 7.2,
            "return_20d": 12.3,
        }


def patch_akshare(monkeypatch) -> None:
    from alphaagent.server.api import data_sources

    monkeypatch.setattr(data_sources, "AkShareAdapter", FakeAkShareAdapter)


def test_health() -> None:
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["service"] == "alphaagent-api"


def test_ready(monkeypatch) -> None:
    from alphaagent.server.api import health

    monkeypatch.setattr(health, "AkShareAdapter", FakeAkShareAdapter)
    monkeypatch.setattr(health, "check_database", lambda: {"name": "postgresql", "ok": True, "message": "ok", "checked_at": ""})
    monkeypatch.setattr(health, "check_redis", lambda: {"name": "redis", "ok": True, "message": "ok", "checked_at": ""})
    monkeypatch.setattr(health, "_safe_coverage", lambda: {"tables": {}})
    client = TestClient(create_app())

    response = client.get("/api/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["persistence"] == "postgresql"
    assert payload["data"]["cache"] == "redis"
    assert payload["data"]["postgres"] == "ok"
    assert payload["data"]["redis"] == "ok"
    assert payload["data"]["market_data"][0]["ok"] is True


def test_akshare_source_info(monkeypatch) -> None:
    patch_akshare(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/data-sources/akshare")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["version"] == "1.18.64"
    assert payload["data"]["package_dir"].endswith("/akshare")


def test_akshare_smoke(monkeypatch) -> None:
    patch_akshare(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/data-sources/akshare/smoke")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["ok"] is True
    assert payload["data"]["checks"][1]["name"] == "a_share_spot"
    assert payload["data"]["checks"][1]["sample"][0]["vt_symbol"]


def test_akshare_business_segments(monkeypatch) -> None:
    patch_akshare(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/data-sources/akshare/stocks/600487.SSE/business-segments")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["vt_symbol"] == "600487.SSE"
    assert payload["data"]["items"][0]["主营构成"] == "制造业"


def test_market_overview(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/market/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["indices"][0]["name"] == "上证指数"


def test_data_status_reports_local_database_and_cache(monkeypatch) -> None:
    patch_clients(monkeypatch)
    patch_akshare(monkeypatch)
    from alphaagent.server.api import data_status

    monkeypatch.setattr(data_status, "check_database", lambda: {"name": "postgresql", "ok": True, "message": "ok", "checked_at": ""})
    monkeypatch.setattr(data_status, "check_redis", lambda: {"name": "redis", "ok": True, "message": "ok", "checked_at": ""})
    monkeypatch.setattr(
        data_status,
        "coverage",
        lambda: {
            "tables": {"stocks": {"rows": 1}, "stock_daily_bars": {"rows": 1, "latest_trade_date": "2026-06-05"}},
            "source": "postgresql",
        },
    )
    client = TestClient(create_app())

    response = client.get("/api/data/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["persistence"] == "postgresql"
    assert payload["data"]["cache"] == "redis"
    assert payload["data"]["tables"]["stocks"]["rows"] == 1
    assert "PostgreSQL" in payload["data"]["notes"][0]


def test_data_sync_routes(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    monkeypatch.setattr(data_sync.service, "list_sources", lambda: {"items": [{"id": "akshare", "name": "AkShare"}], "total": 1})
    monkeypatch.setattr(data_sync.service, "list_jobs", lambda: {"items": [{"id": "sync_stock_list", "name": "同步全 A 股票清单"}], "total": 1})
    monkeypatch.setattr(data_sync.service, "list_runs", lambda limit=20: {"items": [{"id": 1, "job_id": "sync_stock_list", "status": "succeeded"}], "total": 1})
    monkeypatch.setattr(data_sync.service, "coverage", lambda: {"tables": {"stocks": {"rows": 1}}, "source": "postgresql"})
    monkeypatch.setattr(
        data_sync.service,
        "usage",
        lambda: {
            "status": "partial",
            "capabilities": [
                {
                    "id": "market_universe",
                    "name": "全 A 股票池",
                    "used_by": ["全 A 股票"],
                    "data_origin": "local_db",
                    "fallback_used": False,
                }
            ],
            "source": "postgresql,akshare_live_fallback",
        },
    )
    monkeypatch.setattr(
        data_sync.service,
        "run_job",
        lambda job_id, params=None: {"id": 2, "job_id": job_id, "status": "succeeded", "params": params or {}},
    )
    monkeypatch.setattr(
        data_sync.service,
        "start_sync_batch",
        lambda profile="core", params=None, **_kwargs: {
            "id": "batch1",
            "profile": profile,
            "status": "running",
            "progress_pct": 0,
            "jobs": [],
            "params": params or {},
        },
    )
    monkeypatch.setattr(data_sync.service, "get_latest_sync_batch", lambda: {"id": "batch1", "status": "running"})
    monkeypatch.setattr(data_sync.service, "get_sync_batch", lambda batch_id: {"id": batch_id, "status": "succeeded"})
    client = TestClient(create_app())

    assert client.get("/api/data-sync/sources").json()["data"]["items"][0]["id"] == "akshare"
    assert client.get("/api/data-sync/jobs").json()["data"]["items"][0]["id"] == "sync_stock_list"
    assert client.get("/api/data-sync/runs").json()["data"]["items"][0]["status"] == "succeeded"
    assert client.get("/api/data-sync/coverage").json()["data"]["tables"]["stocks"]["rows"] == 1
    assert client.get("/api/data-sync/usage").json()["data"]["capabilities"][0]["used_by"] == ["全 A 股票"]
    run_response = client.post("/api/data-sync/jobs/sync_stock_list/run", json={"max_pages": 1})
    assert run_response.status_code == 200
    assert run_response.json()["data"]["job_id"] == "sync_stock_list"
    batch_response = client.post("/api/data-sync/batches/run-all", json={"profile": "core"})
    assert batch_response.status_code == 200
    assert batch_response.json()["data"]["id"] == "batch1"
    assert client.get("/api/data-sync/batches/latest").json()["data"]["status"] == "running"
    assert client.get("/api/data-sync/batches/batch1").json()["data"]["status"] == "succeeded"


def test_stocks(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/stocks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["items"][0]["vt_symbol"] == "600000.SSE"


def test_stock_detail_date_uses_historical_daily_bar(monkeypatch) -> None:
    from contextlib import contextmanager
    from datetime import date

    class FakeResult:
        def __init__(self, row=None):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult({
                    "symbol": "600000",
                    "exchange": "SSE",
                    "vt_symbol": "600000.SSE",
                    "name": "浦发银行",
                    "industry": "银行",
                    "area": "上海",
                    "market_cap": 100_000_000_000.0,
                    "pe": 5.5,
                    "pb": 0.6,
                    "turnover_rate": 1.2,
                    "volume_ratio": 0.9,
                    "return_5d": 1.0,
                    "return_10d": 2.0,
                    "return_20d": 3.0,
                })
            if self.calls == 2:
                return FakeResult({
                    "trade_date": date(2026, 6, 26),
                    "open_price": 10.2,
                    "close_price": 11.0,
                    "high_price": 11.2,
                    "low_price": 10.1,
                    "volume": 1_000_000.0,
                    "turnover": 11_000_000.0,
                    "source": "postgresql",
                })
            return FakeResult((10.0,))

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(stocks, "is_database_configured", lambda: True)
    monkeypatch.setattr(stocks, "session_scope", fake_session_scope)

    response = stocks.stock_detail("600000.SSE", date(2026, 6, 26))

    assert response["data"]["vt_symbol"] == "600000.SSE"
    assert response["data"]["name"] == "浦发银行"
    assert response["data"]["last_price"] == 11.0
    assert response["data"]["previous_close"] == 10.0
    assert response["data"]["change"] == 1.0
    assert round(response["data"]["change_pct"], 2) == 10.0
    assert response["data"]["trade_time"] == "2026-06-26"
    assert response["data"]["source"] == "postgresql.stock_daily_bars.as_of_date"


def test_stock_detail_date_uses_intraday_snapshot_for_live_day(monkeypatch) -> None:
    from contextlib import contextmanager
    from datetime import date

    class FakeResult:
        def __init__(self, row=None):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

        def scalar_one_or_none(self):
            return self._row

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult({
                    "symbol": "600000",
                    "exchange": "SSE",
                    "vt_symbol": "600000.SSE",
                    "name": "浦发银行",
                    "industry": "银行",
                    "area": "上海",
                    "last_price": 12.3,
                    "change_pct": 2.5,
                    "open_price": 12.0,
                    "high_price": 12.5,
                    "low_price": 11.9,
                    "previous_close": 12.0,
                    "volume": 2_000_000.0,
                    "turnover": 24_000_000.0,
                    "market_cap": 100_000_000_000.0,
                    "pe": 5.5,
                    "pb": 0.6,
                    "turnover_rate": 1.8,
                    "volume_ratio": 1.2,
                    "trade_time": "14:55:00",
                })
            if self.calls == 2:
                return FakeResult(None)
            if self.calls == 3:
                return FakeResult(date(2026, 6, 26))
            if self.calls == 4:
                return FakeResult(("600000.SSE",))
            return FakeResult(None)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(stocks, "is_database_configured", lambda: True)
    monkeypatch.setattr(stocks, "session_scope", fake_session_scope)

    response = stocks.stock_detail("600000.SSE", date(2026, 6, 29))

    assert response["data"]["vt_symbol"] == "600000.SSE"
    assert response["data"]["name"] == "浦发银行"
    assert response["data"]["last_price"] == 12.3
    assert response["data"]["change_pct"] == 2.5
    assert response["data"]["trade_time"] == "2026-06-29 14:55:00"
    assert response["data"]["source"] == "postgresql.stocks.intraday_snapshot"
    assert response["data"]["price_source"] == "intraday_snapshot"


def test_stock_detail_date_keeps_old_missing_history_strict(monkeypatch) -> None:
    from contextlib import contextmanager
    from datetime import date

    class FakeResult:
        def __init__(self, row=None):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

        def scalar_one_or_none(self):
            return self._row

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult({
                    "symbol": "600000",
                    "exchange": "SSE",
                    "vt_symbol": "600000.SSE",
                    "name": "浦发银行",
                })
            if self.calls == 2:
                return FakeResult(None)
            if self.calls == 3:
                return FakeResult(date(2026, 6, 26))
            return FakeResult(None)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(stocks, "is_database_configured", lambda: True)
    monkeypatch.setattr(stocks, "session_scope", fake_session_scope)

    response = stocks.stock_detail("600000.SSE", date(2026, 6, 20))

    assert response.status_code == 404


def test_stock_search_route_does_not_resolve_as_symbol(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/stocks/search?q=亨通光电&page_size=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["items"][0]["vt_symbol"] == "600000.SSE"
    assert payload["data"]["items"][0]["symbol"] != "search"


def test_stock_snapshot(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/stocks/600000.SSE/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["quote"]["symbol"] == "600000"
    assert payload["data"]["bars"][0]["trade_date"] == "2026-06-05"
    assert "business" in payload["data"]
    assert "industry_chain" in payload["data"]


def test_stock_snapshot_date_appends_intraday_bar_for_indicators(monkeypatch) -> None:
    from contextlib import contextmanager

    @contextmanager
    def fake_session_scope():
        yield object()

    patch_clients(monkeypatch)
    monkeypatch.setattr(stocks, "is_database_configured", lambda: True)
    monkeypatch.setattr(stocks, "session_scope", fake_session_scope)
    monkeypatch.setattr(stocks, "_can_use_intraday_snapshot", lambda session, trade_date: True)
    client = TestClient(create_app())

    response = client.get("/api/stocks/600000.SSE/snapshot?date=2026-06-29")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["quote"]["last_price"] == 9.34
    assert payload["data"]["quote"]["price_source"] == "intraday_snapshot"
    assert payload["data"]["bars"][-1]["trade_date"] == "2026-06-29"
    assert payload["data"]["bars"][-1]["close"] == 9.34
    assert payload["data"]["technical_indicators"]["latest_close"] == 9.34
    assert payload["data"]["technical_indicators"]["temporary_bar"] is True


def test_stock_optional_modules_degrade_to_empty_payloads(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    bars_response = client.get("/api/stocks/920206.SSE/bars")
    indicators_response = client.get("/api/stocks/920206.SSE/indicators")
    business_response = client.get("/api/stocks/920206.SSE/business")
    chain_response = client.get("/api/stocks/920206.SSE/industry-chain")
    snapshot_response = client.get("/api/stocks/920206.SSE/snapshot")

    assert bars_response.status_code == 200
    assert bars_response.json()["data"]["items"] == []
    assert indicators_response.status_code == 200
    assert indicators_response.json()["data"]["status"] == "pending"
    assert business_response.status_code == 200
    assert business_response.json()["data"]["source"] == "unavailable"
    assert chain_response.status_code == 200
    assert chain_response.json()["data"]["status"] == "unavailable"
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["data"]["quote"]["vt_symbol"] == "920206.BSE"
    assert "bars" in snapshot_response.json()["data"]["data_quality"]["missing"]


def test_index_detail(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/indices/000001.SSE")

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "上证指数"


def test_sectors(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors?type=industry")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["name"] == "银行"


def test_sector_trend(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/sw_yx/trend")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["trend_state"] == "UP"
    assert payload["data"]["rise_ratio"] == 66.67


def test_sector_stocks_can_include_period_returns(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/sw_yx/stocks?with_returns=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["items"][0]["return_5d"] == 1.1
    assert payload["data"]["items"][0]["return_10d"] == 2.2
    assert payload["data"]["items"][0]["return_20d"] == 3.3


def test_sector_search_returns_real_boards_only(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/search?q=CPO")

    assert response.status_code == 200
    payload = response.json()
    names = [item["name"] for item in payload["data"]["items"]]
    assert "CPO概念" in names
    assert {item["kind"] for item in payload["data"]["items"]} == {"sector"}


def test_sector_search_finds_semiconductor(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/search?q=半导体")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["kind"] == "sector" and item["name"] == "半导体" for item in payload["data"]["items"])


def test_sector_search_matches_board_names(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/search?q=光纤光缆")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["kind"] == "sector" and item["name"] == "光纤光缆" for item in payload["data"]["items"])


def test_sector_search_matches_user_optical_module_wording(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/search?q=光模块")

    assert response.status_code == 200
    payload = response.json()
    names = [item["name"] for item in payload["data"]["items"]]
    assert "光通信模块" in names


def test_sector_search_returns_user_facing_discovery_groups(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/sectors/search?q=&limit=24")

    assert response.status_code == 200
    payload = response.json()["data"]
    groups = {group["id"]: group for group in payload["discovery_groups"]}
    assert "style_status" in groups
    assert "industry" in groups
    assert any(item["name"] == "小盘股" and item["user_category"] == "style_status" for item in groups["style_status"]["items"])
    assert any(item["name"] == "机械设备" and item["user_category"] == "industry" for item in groups["industry"]["items"])
    assert all(item["user_category"] != "style_status" for item in groups["mainline_watch"]["items"])


def test_industry_chain_stocks(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/industry-chains/半导体/stocks?page_size=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["items"][0]["vt_symbol"] == "600000.SSE"
    assert payload["data"]["related_sectors"]


def test_industry_chain_map(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/industry-chains/半导体/map?page_size=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["related_sectors"]
    assert {segment["stage"] for segment in payload["data"]["segments"]} <= {"source", "bridge", "sink"}
    assert payload["data"]["edges"]
    assert "动态计算" in payload["data"]["exposure_basis"]


def test_sector_relation_graph(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/industry-chains/graph?q=半导体&limit=6&page_size=20")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["algorithm"]["name"] == "sector_constituent_overlap_graph"
    assert payload["data"]["nodes"]
    assert payload["data"]["source"]


def test_sector_relation_graph_deep_mode(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/industry-chains/graph?q=半导体&limit=6&page_size=20&deep=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["algorithm"]["name"] == "sector_constituent_overlap_graph"
    assert payload["data"]["nodes"]
    assert payload["data"]["edges"]
    assert payload["data"]["edges"][0]["shared_stock_count"] >= 1
    assert "chain_affinity" not in payload["data"]["edges"][0]


def test_optical_module_graph_filters_trading_status_noise(monkeypatch) -> None:
    patch_clients(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/industry-chains/graph?q=光模块&limit=8&page_size=20")

    assert response.status_code == 200
    payload = response.json()
    names = [node["name"] for node in payload["data"]["nodes"]]
    assert "光通信模块" in names
    assert "昨日涨停" not in names
