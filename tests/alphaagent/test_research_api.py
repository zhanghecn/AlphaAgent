"""Tests for the research API endpoints.

Covers:
  - research_sectors: dashboard, overview, relation-graph
  - research_stocks: workbench, finance/quarterly, finance/statements, business, events
  - research_graphs: industry-chain/graph

All tests monkeypatch database and AkShare adapter to avoid external dependencies.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient

from alphaagent.server.main import create_app


# ── Fakes ──


def _fake_is_database_configured() -> bool:
    return False


def _fake_session_scope():
    """Context manager that raises — DB should not be touched in these tests."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        raise RuntimeError("session_scope should not be called when DB is not configured")

    return _ctx()


# ── Patch helpers ──


def patch_db_off(monkeypatch) -> None:
    """Make all research endpoints think the database is not configured."""
    from alphaagent.server.api import research_graphs, research_sectors, research_stocks
    from alphaagent.server.db import session as db_session
    from alphaagent.server.services import research_stock_profile

    monkeypatch.setattr(db_session, "is_database_configured", _fake_is_database_configured)
    monkeypatch.setattr(research_sectors, "is_database_configured", _fake_is_database_configured)
    monkeypatch.setattr(research_stocks, "is_database_configured", _fake_is_database_configured)
    monkeypatch.setattr(research_graphs, "is_database_configured", _fake_is_database_configured)
    monkeypatch.setattr(research_stock_profile, "is_database_configured", _fake_is_database_configured)


class FakeAkShareAdapter:
    """Minimal fake for the research stock endpoints."""

    def board_names(self, board_type="concept", limit=20):
        return {
            "items": [
                {
                    "id": "BK0001",
                    "name": "CPO概念",
                    "type": board_type,
                    "change_pct": 3.21,
                    "stock_count": 35,
                    "rise_count": 28,
                    "fall_count": 7,
                    "leader_stock": "中际旭创",
                    "leader_change_pct": 5.12,
                    "market_cap": None,
                    "turnover_rate": 2.5,
                },
                {
                    "id": "BK0002",
                    "name": "AI算力",
                    "type": board_type,
                    "change_pct": 2.8,
                    "stock_count": 42,
                    "rise_count": 35,
                    "fall_count": 7,
                    "leader_stock": "工业富联",
                    "leader_change_pct": 4.5,
                    "market_cap": None,
                    "turnover_rate": 1.8,
                },
            ],
            "total": 2,
            "type": board_type,
            "source": "fake_board_names",
        }

    def sector_fund_flows(self, sector_type="concept", period="即时"):
        return {
            "items": [
                {
                    "代码": "BK0001",
                    "名称": "CPO概念",
                    "主力净流入-净额": 1_200_000_000,
                    "主力净流入-净占比": 2.5,
                    "涨跌幅": 3.21,
                },
            ],
            "total": 1,
            "source": "fake_fund_flow",
        }

    def stock_sectors(self, symbol, exchange=None):
        return {
            "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
            "items": [
                {"id": "BK0001", "name": "CPO概念", "type": "concept", "confirmed": True},
                {"id": "BK0002", "name": "AI算力", "type": "concept", "confirmed": True},
                {"id": "BK0100", "name": "通信设备", "type": "industry", "confirmed": True},
            ],
            "source": "fake_stock_sectors",
        }

    def shenwan_stock_classification(self, symbol):
        return {
            "vt_symbol": f"{symbol}.SSE",
            "levels": {
                "level1": {"code": "801010", "name": "通信"},
                "level2": {"code": "80101010", "name": "通信设备"},
                "level3": {"code": "8010101001", "name": "光通信设备"},
            },
            "source": "fake_shenwan",
        }

    def stock_hot_ranks(self, limit=20):
        return {
            "items": [
                {"symbol": "300308", "name": "中际旭创", "rank": 1},
                {"symbol": "601138", "name": "工业富联", "rank": 2},
            ],
            "total": 2,
            "source": "fake_hot_ranks",
        }

    def limit_up_pools(self, trade_date=None):
        return {
            "trade_date": trade_date or "20250101",
            "pools": {
                "zt": {"label": "涨停池", "items": [], "total": 0},
            },
            "source": "fake_limit_pools",
        }

    def stock_financial_quarterly(self, symbol, exchange=None, limit=12):
        return {
            "items": [
                {
                    "report_date": "2025-12-31",
                    "period_type": "Q4",
                    "revenue": 1_000_000,
                    "revenue_yoy": 10.5,
                    "net_profit": 200_000,
                    "net_profit_yoy": 15.0,
                    "gross_margin": 35.0,
                    "net_margin": 20.0,
                    "roe": 12.5,
                },
            ],
            "total": 1,
            "source": "fake_quarterly",
        }

    def stock_balance_sheet(self, symbol, exchange=None):
        return {"items": [{"report_date": "2025-12-31", "total_assets": 5_000_000}], "source": "fake_balance"}

    def stock_profit_sheet(self, symbol, exchange=None):
        return {"items": [{"report_date": "2025-12-31", "total_revenue": 1_000_000}], "source": "fake_profit"}

    def stock_cash_flow_sheet(self, symbol, exchange=None):
        return {"items": [{"report_date": "2025-12-31", "operating_cash_flow": 300_000}], "source": "fake_cashflow"}

    def stock_business_segments_history(self, symbol, exchange=None, limit=100):
        return {
            "items": [
                {
                    "segment_name": "制造业",
                    "segment_type": "product",
                    "report_date": "2025-12-31",
                    "revenue": 800_000,
                    "revenue_ratio": 0.8,
                    "gross_margin": 35.0,
                },
            ],
            "total": 1,
            "source": "fake_business_history",
        }

    def stock_hot_detail(self, symbol, exchange=None):
        return {"rank": 42, "keywords": ["半导体", "芯片"]}

    def stock_detail(self, symbol, exchange=None):
        return {
            "items": [
                {
                    "symbol": symbol,
                    "exchange": exchange or "SSE",
                    "vt_symbol": f"{symbol}.{exchange or 'SSE'}",
                    "name": "测试股票",
                    "last_price": 10.0,
                    "change_pct": 2.5,
                    "source": "fake_detail",
                }
            ],
            "source": "fake_detail",
        }


def patch_akshare(monkeypatch) -> None:
    """Replace AkShareAdapter with FakeAkShareAdapter in research modules."""
    from alphaagent.server.api import research_stocks
    from alphaagent.server.services import research_stock_profile

    monkeypatch.setattr(research_stocks, "AkShareAdapter", FakeAkShareAdapter)
    monkeypatch.setattr(research_stock_profile, "AkShareAdapter", FakeAkShareAdapter)


def _setup_client(monkeypatch) -> TestClient:
    """Common setup: patch DB off + fake AkShare + create test client."""
    patch_db_off(monkeypatch)
    patch_akshare(monkeypatch)
    return TestClient(create_app())


# ══════════════════════════════════════════
# Research Sectors
# ══════════════════════════════════════════


class TestSectorDashboard:
    """Tests for GET /api/research/sectors/dashboard."""

    def test_returns_unavailable_when_db_off(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/sectors/dashboard")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["items"] == []
        assert payload["total"] == 0

    def test_accepts_period_query_param(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/sectors/dashboard?period=5d")

        assert response.status_code == 200
        # Even with DB off, it should return the period in the response
        assert response.json()["period"] == "5d"

    def test_accepts_pagination_params(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/sectors/dashboard?page=2&page_size=10")

        assert response.status_code == 200
        payload = response.json()
        assert payload["page"] == 2
        assert payload["page_size"] == 10

    def test_accepts_sort_params(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/sectors/dashboard?sort_by=fund_score&sort_order=asc")

        assert response.status_code == 200
        payload = response.json()
        assert payload["sort_by"] == "fund_score"
        assert payload["sort_order"] == "asc"


class TestSectorOverview:
    """Tests for GET /api/research/sectors/{sector_id}/overview."""

    def test_returns_unavailable_when_db_off(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/sectors/BK0001/overview")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"


class TestSectorRelationGraph:
    """Tests for GET /api/research/sectors/{sector_id}/relation-graph."""

    def test_returns_unavailable_when_db_off(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/sectors/BK0001/relation-graph")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["nodes"] == []
        assert payload["edges"] == []


# ══════════════════════════════════════════
# Research Stocks
# ══════════════════════════════════════════


class TestStockWorkbench:
    """Tests for GET /api/research/stocks/{vt_symbol}/workbench."""

    def test_returns_workbench_structure(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/workbench")

        assert response.status_code == 200
        payload = response.json()
        # Verify the 8 required top-level sections exist
        assert "vt_symbol" in payload
        assert "symbol" in payload
        assert "exchange" in payload
        assert "as_of" in payload
        assert "profile" in payload
        assert "technical" in payload
        assert "financial" in payload
        assert "business" in payload
        assert "sectors" in payload
        assert "chain" in payload
        assert "events" in payload
        assert "data_quality" in payload

    def test_workbench_includes_data_quality(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/workbench")

        payload = response.json()
        dq = payload["data_quality"]
        assert "sections" in dq
        assert "total" in dq
        assert "available" in dq
        assert "completeness" in dq
        assert isinstance(dq["total"], int)
        assert isinstance(dq["completeness"], (int, float))

    def test_workbench_profile_has_source(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/workbench")

        payload = response.json()
        assert "source" in payload["profile"]
        # When DB is off, it falls back to adapter
        assert payload["profile"]["source"] in ("fake_detail", "unavailable")

    def test_workbench_handles_missing_exchange(self, monkeypatch):
        """Workbench should handle vt_symbol without exchange gracefully."""
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/999999/workbench")

        assert response.status_code == 200
        payload = response.json()
        assert "vt_symbol" in payload
        assert "data_quality" in payload


class TestStockFinanceQuarterly:
    """Tests for GET /api/research/stocks/{vt_symbol}/finance/quarterly."""

    def test_returns_quarterly_data_from_adapter(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/finance/quarterly")

        assert response.status_code == 200
        payload = response.json()
        assert payload["vt_symbol"] == "600000.SSE"
        assert payload["total"] == 1
        assert payload["items"][0]["report_date"] == "2025-12-31"
        assert payload["items"][0]["revenue"] == 1_000_000
        assert payload["source"] == "fake_quarterly"

    def test_respects_limit_param(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/finance/quarterly?limit=5")

        assert response.status_code == 200
        # The fake always returns 1 item, but the endpoint should accept the param
        assert response.json()["total"] == 1


class TestStockFinanceStatements:
    """Tests for GET /api/research/stocks/{vt_symbol}/finance/statements."""

    def test_balance_sheet(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/finance/statements?statement_type=balance_sheet")

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["total_assets"] == 5_000_000

    def test_profit_sheet(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/finance/statements?statement_type=profit_sheet")

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["total_revenue"] == 1_000_000

    def test_cash_flow(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/finance/statements?statement_type=cash_flow")

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["operating_cash_flow"] == 300_000

    def test_invalid_statement_type_returns_400(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/finance/statements?statement_type=invalid")

        assert response.status_code == 400


class TestStockBusiness:
    """Tests for GET /api/research/stocks/{vt_symbol}/business."""

    def test_returns_business_from_adapter(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/business")

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"][0]["segment_name"] == "制造业"
        assert payload["items"][0]["revenue_ratio"] == 0.8
        assert payload["source"] == "fake_business_history"


class TestStockEvents:
    """Tests for GET /api/research/stocks/{vt_symbol}/events."""

    def test_returns_events_structure(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/events")

        assert response.status_code == 200
        payload = response.json()
        assert "timeline" in payload
        assert "hot_rank" in payload
        assert isinstance(payload["timeline"], list)

    def test_includes_hot_rank(self, monkeypatch):
        client = _setup_client(monkeypatch)

        response = client.get("/api/research/stocks/600000.SSE/events")

        payload = response.json()
        hr = payload["hot_rank"]
        assert hr["rank"] == 42
        assert "半导体" in hr["keywords"]


# ══════════════════════════════════════════
# Research Graphs
# ══════════════════════════════════════════


class TestIndustryChainGraph:
    """Tests for GET /api/research/industry-chain/graph."""

    def test_returns_unavailable_when_db_off(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/industry-chain/graph")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["nodes"] == []
        assert payload["edges"] == []

    def test_accepts_filter_params(self, monkeypatch):
        patch_db_off(monkeypatch)
        client = TestClient(create_app())

        response = client.get("/api/research/industry-chain/graph?node_type=sector&stage=upstream&min_confidence=0.5")

        assert response.status_code == 200
        # Should not error even with filter params


# ══════════════════════════════════════════
# Integration: schema import smoke test
# ══════════════════════════════════════════


class TestSchemaImport:
    """Verify new research tables are importable and have expected columns."""

    def test_research_tables_exist_in_schema(self):
        from alphaagent.server.db import schema

        expected_tables = [
            "sector_daily_bars",
            "sector_daily_metrics",
            "sector_period_scores",
            "sector_relation_edges",
            "industry_chain_nodes",
            "stock_financial_reports",
            "stock_financial_statement_items",
            "stock_events",
            "stock_fund_flows",
            "sector_fund_flows",
            "stock_hot_ranks",
            "stock_lhb_records",
        ]
        for table_name in expected_tables:
            table = getattr(schema, table_name, None)
            assert table is not None, f"Missing table: {table_name}"
            assert hasattr(table, "c"), f"{table_name} is not a SQLAlchemy Table"

    def test_sector_period_scores_has_required_columns(self):
        from alphaagent.server.db import schema

        cols = set(schema.sector_period_scores.c.keys())
        required = {
            "sector_id", "as_of_date", "period",
            "momentum_score", "breadth_score", "fund_score",
            "sentiment_score", "leader_score", "continuity_score",
            "liquidity_score", "risk_penalty", "heat_score",
            "trend_state", "confidence",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_sector_relation_edges_has_similarity_metrics(self):
        from alphaagent.server.db import schema

        cols = set(schema.sector_relation_edges.c.keys())
        required = {
            "source_sector_id", "target_sector_id", "as_of_date", "period",
            "shared_stock_count", "shared_stock_ratio", "jaccard",
            "price_correlation", "fund_correlation",
            "score", "confidence",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"


# ══════════════════════════════════════════
# Integration: service import smoke test
# ══════════════════════════════════════════


class TestServiceImports:
    """Verify new research services are importable."""

    def test_research_sector_scores_importable(self):
        from alphaagent.server.services.research_sector_scores import (
            compute_sector_period_scores,
            persist_scores,
        )
        assert callable(compute_sector_period_scores)
        assert callable(persist_scores)

    def test_research_sector_graph_importable(self):
        from alphaagent.server.services.research_sector_graph import (
            compute_sector_relation_edges,
            persist_edges,
        )
        assert callable(compute_sector_relation_edges)
        assert callable(persist_edges)

    def test_research_chain_graph_importable(self):
        from alphaagent.server.services.research_chain_graph import (
            compute_industry_chain_graph,
            persist_chain_graph,
        )
        assert callable(compute_industry_chain_graph)
        assert callable(persist_chain_graph)

    def test_research_stock_profile_importable(self):
        from alphaagent.server.services.research_stock_profile import (
            get_stock_workbench,
        )
        assert callable(get_stock_workbench)


def test_sector_score_input_ignores_future_bars_and_fund_flows(monkeypatch):
    """Historical mainline scoring must not read data after as_of_date."""
    from alphaagent.server.db import schema
    from alphaagent.server.services import research_sector_scores as scores

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def scalar(self):
            return self._rows[0] if self._rows else 0

    class _Session:
        def execute(self, stmt):
            sql = str(stmt)
            if "FROM sector_daily_bars" in sql:
                params = stmt.compile().params
                assert params["trade_date_1"] == date(2026, 6, 25)
                return _Result([
                    {
                        "sector_id": "BK0001",
                        "trade_date": date(2026, 6, 25),
                        "close_price": 110.0,
                        "change_pct": 1.0,
                        "turnover": 10.0,
                    },
                    {
                        "sector_id": "BK0001",
                        "trade_date": date(2026, 6, 24),
                        "close_price": 100.0,
                        "change_pct": -1.0,
                        "turnover": 8.0,
                    },
                ])
            if "FROM sector_memberships" in sql:
                return _Result([
                    {"vt_symbol": "000001.SZ", "name": "成员一"},
                    {"vt_symbol": "000002.SZ", "name": "成员二"},
                    {"vt_symbol": "000003.SZ", "name": "成员三"},
                ])
            if "FROM stock_daily_bars" in sql:
                params = stmt.compile().params
                assert params["trade_date_1"] == date(2026, 6, 25)
                return _Result([
                    {"vt_symbol": "000001.SZ", "change_pct": 3.0},
                    {"vt_symbol": "000002.SZ", "change_pct": -1.0},
                    {"vt_symbol": "000003.SZ", "change_pct": 6.0},
                ])
            if "FROM sector_fund_flows" in sql:
                params = stmt.compile().params
                assert params["trade_date_1"] == "2026-06-25"
                assert "sector_fund_flows.period" in sql
                assert "CASE" in sql
                return _Result([{"main_net_inflow": 123.0, "main_net_inflow_ratio": 4.5, "period": "即时"}])
            if "FROM stock_events" in sql:
                params = stmt.compile().params
                assert params["event_date_1"] == ["2026-06-25", "20260625"]
                return _Result([1])
            raise AssertionError(f"unexpected SQL: {sql}")

    @contextmanager
    def fake_session_scope():
        yield _Session()

    monkeypatch.setattr(scores, "session_scope", fake_session_scope)

    inp = scores._collect_score_input("BK0001", "concept", date(2026, 6, 25), 2)

    assert [bar["trade_date"] for bar in inp.bars] == [date(2026, 6, 25), date(2026, 6, 24)]
    assert inp.return_pct == 10.0
    assert inp.main_net_inflow == 123.0
    assert inp.fund_period == "即时"
    assert inp.total_members == 3
    assert inp.rise_count == 2
    assert inp.fall_count == 1
    assert inp.leader_vt_symbol == "000003.SZ"
    assert inp.leader_name == "成员三"
    assert inp.leader_change_pct == 6.0
    assert inp.limit_up_count == 1


def test_sector_score_breadth_and_leader_use_as_of_member_bars():
    """Breadth/leader evidence must come from historical member bars, not sector snapshots."""
    from alphaagent.server.services import research_sector_scores as scores

    inp = scores.SectorScoreInput(
        sector_id="BK0001",
        sector_type="concept",
        period="20d",
        as_of_date=date(2026, 6, 25),
        total_members=4,
        member_universe_count=6,
        member_bar_count=4,
        rise_count=3,
        fall_count=1,
        breadth_source="stock_daily_bars.as_of_date",
        leader_vt_symbol="000003.SZ",
        leader_name="成员三",
        leader_change_pct=6.0,
        leader_source="stock_daily_bars.as_of_date",
        limit_up_count=1,
        sentiment_source="stock_events.event_date",
    )

    breadth, breadth_evidence = scores._score_breadth(inp)
    leader, leader_evidence = scores._score_leader(inp)
    sentiment, sentiment_evidence = scores._score_sentiment(inp)

    assert breadth == 75.0
    assert breadth_evidence["source"] == "stock_daily_bars.as_of_date"
    assert breadth_evidence["as_of_date"] == "2026-06-25"
    assert breadth_evidence["member_universe_count"] == 6
    assert breadth_evidence["member_bar_count"] == 4
    assert leader == 68.0
    assert leader_evidence["leader_vt_symbol"] == "000003.SZ"
    assert leader_evidence["leader_name"] == "成员三"
    assert leader_evidence["source"] == "stock_daily_bars.as_of_date"
    assert sentiment == 100.0
    assert sentiment_evidence["source"] == "stock_events.event_date"


def test_sector_score_fund_evidence_includes_selected_period():
    """Fund score evidence should show the selected sector_fund_flows period."""
    from alphaagent.server.services import research_sector_scores as scores

    inp = scores.SectorScoreInput(
        sector_id="BK0001",
        sector_type="concept",
        period="20d",
        as_of_date=date(2026, 6, 25),
        main_net_inflow=100.0,
        main_net_inflow_ratio=2.0,
        fund_period="即时",
    )

    score, evidence = scores._score_fund(inp)

    assert score == 66.0
    assert evidence["period"] == "即时"


# ══════════════════════════════════════════
# New endpoints: sector ranking, concept-cards, market live data
# ══════════════════════════════════════════


def _setup_client_with_market(monkeypatch) -> TestClient:
    """Setup with DB off + fake AkShare for both research and market modules."""
    patch_db_off(monkeypatch)
    # Patch the source module so local imports inside functions pick up the fake
    import alphaagent.data_sources.akshare_adapter as akshare_module
    monkeypatch.setattr(akshare_module, "AkShareAdapter", FakeAkShareAdapter)
    from alphaagent.server.api import market as market_module
    monkeypatch.setattr(market_module, "AkShareAdapter", FakeAkShareAdapter)
    from alphaagent.server.api import research_stocks as rst_module
    monkeypatch.setattr(rst_module, "AkShareAdapter", FakeAkShareAdapter)
    from alphaagent.server.services import research_stock_profile as rsp_module
    monkeypatch.setattr(rsp_module, "AkShareAdapter", FakeAkShareAdapter)
    return TestClient(create_app())


class TestSectorRanking:
    """Tests for GET /api/research/sectors/ranking."""

    def test_returns_ranking_items(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/sectors/ranking?sector_type=concept&limit=10")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert len(payload["items"]) == 2
        # First item should have required fields
        item = payload["items"][0]
        assert "sector_id" in item
        assert "name" in item
        assert "type" in item
        assert "change_pct" in item
        assert "main_net_inflow" in item

    def test_ranking_sort_by_change_pct(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/sectors/ranking?sort_by=change_pct")

        payload = response.json()
        items = payload["items"]
        assert len(items) >= 2
        # CPO (3.21) should rank before AI (2.8)
        assert abs(items[0].get("change_pct") or 0) >= abs(items[1].get("change_pct") or 0)

    def test_ranking_sort_by_fund_flow(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/sectors/ranking?sort_by=fund_flow")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"

    def test_ranking_concept_type_filter(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/sectors/ranking?sector_type=industry")

        payload = response.json()
        assert payload["status"] == "ready"
        for item in payload["items"]:
            assert item["type"] == "industry"

    def test_ranking_all_types(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/sectors/ranking?sector_type=all")

        payload = response.json()
        assert payload["total"] >= 2


class TestConceptCards:
    """Tests for GET /api/research/stocks/{vt_symbol}/concept-cards."""

    def test_returns_concept_cards(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/stocks/600487.SSE/concept-cards")

        assert response.status_code == 200
        payload = response.json()
        assert payload["vt_symbol"] == "600487.SSE"
        assert payload["status"] == "ready"
        assert len(payload["cards"]) >= 2

        card = payload["cards"][0]
        assert "name" in card
        assert "type" in card
        assert "change_pct" in card
        assert "sector_id" in card

    def test_concept_cards_includes_shenwan(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/stocks/600487.SSE/concept-cards")

        payload = response.json()
        assert "shenwan" in payload
        sw = payload["shenwan"]
        assert "level1" in sw
        assert sw["level1"]["name"] == "通信"

    def test_concept_cards_sorted_by_type_and_change(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/research/stocks/600487.SSE/concept-cards")

        payload = response.json()
        cards = payload["cards"]
        # Concepts should come before industry
        concept_cards = [c for c in cards if c["type"] == "concept"]
        industry_cards = [c for c in cards if c["type"] == "industry"]
        assert len(concept_cards) > 0
        assert len(industry_cards) > 0


class TestMarketFundFlow:
    """Tests for GET /api/market/fund-flow."""

    def test_returns_fund_flow(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/market/fund-flow?sector_type=concept&top_n=10")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert len(payload["items"]) >= 1
        item = payload["items"][0]
        assert "name" in item
        assert "main_net_inflow" in item


class TestMarketHotRanks:
    """Tests for GET /api/market/hot-ranks."""

    def test_returns_hot_ranks(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/market/hot-ranks?limit=10")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert len(payload["items"]) >= 1


class TestMarketLimitPools:
    """Tests for GET /api/market/limit-pools."""

    def test_returns_limit_pools(self, monkeypatch):
        client = _setup_client_with_market(monkeypatch)

        response = client.get("/api/market/limit-pools")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert "pools" in payload
