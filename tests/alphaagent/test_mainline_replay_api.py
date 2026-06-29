"""API contract tests for mainline replay endpoints.

后端 FastAPI 不强制 JWT（鉴权在 Go 网关层），TestClient 可直接调。
若日后后端加全局鉴权依赖，需补 token / monkeypatch。
"""

from contextlib import contextmanager
from datetime import date, timedelta

from fastapi.testclient import TestClient

from alphaagent.server.api import mainline_replay
from alphaagent.server.db import session as db_session
from alphaagent.server.main import create_app


def _disable_db(monkeypatch) -> None:
    monkeypatch.setattr(db_session, "is_database_configured", lambda: False)
    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: False)


def test_timeline_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/timeline")
    body = res.json()
    assert res.status_code == 200
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_snapshot_requires_date_or_range(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/snapshot")
    assert res.status_code == 400


def test_snapshot_single_date_unavailable_when_db_off(monkeypatch):
    # db off：有 date 参数 → 不 400，返回 unavailable（mode/ranking 形状留给真实 db 端到端验证）
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/snapshot?date=2026-06-20")
    body = res.json()
    assert res.status_code == 200
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_mainline_rejects_sector_type_query_param():
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/snapshot?date=2026-06-20&sector_type=industry")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "BAD_PARAMS"


def test_relation_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/relation?sector_id=BK0001&date=2026-06-20")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_timeline_route_registered():
    """路由确实挂到了 /api 下（防止 router 漏注册）。"""
    client = TestClient(create_app())
    # db off 时返回 200 + unavailable，证明路由可达
    res = client.get("/api/mainline-replay/timeline")
    assert res.status_code != 404


def test_timeline_filters_to_complete_trade_dates(monkeypatch):
    captured: dict[str, str] = {}

    class FakeResult:
        def all(self):
            return [(date(2026, 6, 26),), (date(2026, 6, 25),)]

    class FakeSession:
        def execute(self, stmt):
            compiled = stmt.compile()
            captured["sql"] = str(compiled)
            captured["params"] = str(compiled.params)
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.timeline(limit=10)

    assert body["data"]["dates"] == ["2026-06-26", "2026-06-25"]
    assert "stock_daily_bars" in captured["sql"]
    assert "count(distinct" in captured["sql"].lower()
    assert "3000" in captured["params"]


def test_live_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/live")
    body = res.json()
    assert res.status_code == 200
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_live_uses_latest_sector_fund_flow_date(monkeypatch):
    captured: list[str] = []

    class FakeResult:
        def __init__(self, value=None):
            self._value = value

        def scalar(self):
            return self._value

        def first(self):
            return None

        def all(self):
            return []

    class FakeSession:
        def execute(self, stmt):
            compiled = stmt.compile()
            sql = str(compiled)
            captured.append(sql)
            if "max(sector_fund_flows.trade_date)" in sql:
                return FakeResult("2026-06-29")
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.live(limit=10)

    assert body["data"]["mode"] == "live"
    assert body["data"]["trade_date"] == "2026-06-29"
    assert body["data"]["source"] == "sector_fund_flows:concept"
    assert any("sector_fund_flows.trade_date" in sql for sql in captured)


def test_live_ranking_is_concept_only_query(monkeypatch):
    captured: dict[str, str] = {}

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        def execute(self, stmt):
            compiled = stmt.compile()
            captured["sql"] = str(compiled)
            captured["params"] = str(compiled.params)
            return FakeResult()

    mainline_replay._live_ranking_for_date(FakeSession(), date(2026, 6, 29), limit=10)

    assert "sectors.type" in captured["sql"]
    assert "concept" in captured["params"]


def test_live_ranking_payload_does_not_expose_sector_type():
    class FakeResult:
        def all(self):
            return [
                (
                    "BK1431",
                    1000.0,
                    1.2,
                    1,
                    None,
                    "存储芯片",
                    "concept",
                    None,
                    [],
                    2.3,
                    80,
                    "龙头股",
                    5.5,
                    88.0,
                    70.0,
                    60.0,
                    "MAINLINE_UP",
                    4.2,
                    date(2026, 6, 26),
                )
            ]

    class FakeSession:
        def execute(self, stmt):
            del stmt
            return FakeResult()

    items = mainline_replay._live_ranking_for_date(FakeSession(), date(2026, 6, 29), limit=10)

    assert items[0]["name"] == "存储芯片"
    assert "sector_type" not in items[0]


def test_concept_index_context_enriches_live_projection_and_status():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([
                    ("BK1431", date(2026, 6, 24), 100.0, 1.0, 1000.0),
                    ("BK1431", date(2026, 6, 25), 104.0, 4.0, 1200.0),
                    ("BK1431", date(2026, 6, 26), 105.0, 0.96, 1300.0),
                ])
            return FakeResult([
                ("BK1431", date(2026, 6, 26), 72.0, 8, "MAINLINE_UP"),
                ("BK1431", date(2026, 6, 25), 68.0, 12, "FAST_UP"),
                ("BK1431", date(2026, 6, 24), 41.0, 200, "WEAK"),
            ])

    ranking = [{
        "sector_id": "BK1431",
        "data_mode": "live",
        "return_pct": 2.0,
        "main_net_inflow": 1000.0,
    }]

    mainline_replay._enrich_concept_index_context(
        FakeSession(),
        ranking,
        date(2026, 6, 29),
        include_live_projection=True,
    )

    item = ranking[0]
    assert item["continuation_status"] == "maintained"
    assert item["continuation_days"] == 2
    assert item["activity_days_20"] == 2
    assert item["index_points"][-1]["date"] == "2026-06-29"
    assert item["index_points"][-1]["temporary"] is True
    assert round(item["index_points"][-1]["close"], 2) == 107.10
    assert item["index_change_pct"] is not None


def test_concept_index_context_marks_live_new_when_previous_not_hot():
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([])
            return FakeResult([
                ("BK2000", date(2026, 6, 26), 30.0, 300, "WEAK"),
                ("BK2000", date(2026, 6, 25), 29.0, 310, "WEAK"),
            ])

    ranking = [{
        "sector_id": "BK2000",
        "data_mode": "live",
        "return_pct": 3.0,
        "main_net_inflow": None,
    }]

    mainline_replay._enrich_concept_index_context(
        FakeSession(),
        ranking,
        date(2026, 6, 29),
        include_live_projection=True,
    )

    assert ranking[0]["continuation_status"] == "new"
    assert ranking[0]["continuation_days"] == 0


def test_live_concept_sort_prefers_rolling_index_over_intraday_inflow():
    ranking = [
        {
            "sector_id": "FLOW",
            "continuation_status": "maintained",
            "rolling_board_count": 0,
            "continuation_days": 1,
            "index_change_pct": 3.0,
            "main_net_inflow": 9_000_000_000.0,
        },
        {
            "sector_id": "STORAGE",
            "continuation_status": "maintained",
            "rolling_board_count": 2,
            "continuation_days": 20,
            "index_change_pct": 30.0,
            "main_net_inflow": -900_000_000.0,
        },
    ]

    sorted_items = mainline_replay._sort_live_concept_ranking(ranking)

    assert sorted_items[0]["sector_id"] == "STORAGE"


def test_concept_sort_prefers_continuation_and_index_return_over_spike_count():
    ranking = [
        {
            "sector_id": "SPIKE",
            "continuation_status": "hot",
            "rolling_board_count": 3,
            "rolling_board_avg_change_pct": 5.84,
            "continuation_days": 1,
            "index_change_pct": -0.09,
            "heat_score": 78.69,
        },
        {
            "sector_id": "STORAGE",
            "continuation_status": "hot",
            "rolling_board_count": 2,
            "rolling_board_avg_change_pct": 4.13,
            "continuation_days": 20,
            "index_change_pct": 30.13,
            "heat_score": 69.72,
        },
    ]

    sorted_items = mainline_replay._sort_live_concept_ranking(ranking)

    assert sorted_items[0]["sector_id"] == "STORAGE"


def test_snapshot_single_date_uses_concept_index_sort_after_enrichment(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def scalar(self):
            return None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([
                    ("FLOW", 99.0, 100.0, 40.0, "ROTATION", 200, -2.0, None, "高资金概念", "concept", None, []),
                    ("STORAGE", 60.0, 30.0, 100.0, "MAINLINE_UP", 8, 30.0, None, "存储芯片", "concept", None, []),
                ])
            if self.calls == 2:
                return FakeResult([])
            if self.calls == 3:
                return FakeResult([
                    ("FLOW", "高资金概念", "concept", None, []),
                    ("STORAGE", "存储芯片", "concept", None, []),
                ])
            if self.calls == 4:
                return FakeResult([
                    ("FLOW", date(2026, 6, 26), 100.0, -2.0, 1000.0),
                    ("STORAGE", date(2026, 6, 26), 100.0, 8.0, 1000.0),
                    ("STORAGE", date(2026, 6, 29), 130.0, 30.0, 1000.0),
                ])
            return FakeResult([
                ("FLOW", date(2026, 6, 29), 99.0, 100, "ROTATION"),
                ("STORAGE", date(2026, 6, 29), 60.0, 8, "MAINLINE_UP"),
            ])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.snapshot(date=date(2026, 6, 29), limit=1)

    assert body["data"]["ranking"][0]["sector_id"] == "STORAGE"


def test_snapshot_ranking_is_concept_only_query(monkeypatch):
    captured: dict[str, str] = {}

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        def execute(self, stmt):
            compiled = stmt.compile()
            captured["sql"] = str(compiled)
            captured["params"] = str(compiled.params)
            return FakeResult()

    mainline_replay._ranking_for_date(FakeSession(), date(2026, 6, 26), limit=10)

    assert "sector_period_scores.sector_type" in captured["sql"]
    assert "sectors.type" in captured["sql"]
    assert "concept" in captured["params"]


def test_snapshot_payload_does_not_expose_sector_type(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([("BK1431", 88.0, 70.0, 60.0, "MAINLINE_UP", 1, 4.2, 0.9, "存储芯片", "concept", None, [])])
            if self.calls == 2:
                return FakeResult([])
            if self.calls == 3:
                return FakeResult([("BK1431", "存储芯片", "concept", None, [])])
            return FakeResult([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.snapshot(date=date(2026, 6, 26), limit=10)

    item = body["data"]["ranking"][0]
    assert item["name"] == "存储芯片"
    assert "sector_type" not in item


def test_relation_rejects_industry_target(monkeypatch):
    class FakeResult:
        def all(self):
            return [("BK1000", "元件", "industry", None, [])]

    class FakeSession:
        def execute(self, stmt):
            del stmt
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.relation(sector_id="BK1000", date=date(2026, 6, 26), limit=10)

    assert body["data"]["status"] == "unsupported_target"
    assert body["data"]["items"] == []


def test_mainline_concept_meta_filters_style_status_and_index_baskets():
    assert mainline_replay._is_mainline_concept_meta({"name": "存储芯片", "type": "concept"}) is True
    assert mainline_replay._is_mainline_concept_meta({"name": "高带宽内存", "type": "concept"}) is True
    assert mainline_replay._is_mainline_concept_meta({"name": "上证50_", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "AH股", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "昨日涨停", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "趋势股", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "历史新高", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "东方财富热股", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "题材股", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "创业成份", "type": "concept"}) is False
    assert mainline_replay._is_mainline_concept_meta({"name": "元件", "type": "industry"}) is False


def test_sector_stocks_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/sector-stocks?sector_id=BK1431&date=2026-06-26")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_sector_stocks_does_not_use_previous_bar_as_selected_date(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([("AAA.SSE", "甲股票"), ("BBB.SSE", "乙股票")])
            if self.calls == 2:
                return FakeResult([("AAA.SSE", 11.0)])
            if self.calls == 3:
                return FakeResult([("AAA.SSE", 10.0), ("BBB.SSE", 20.0)])
            if self.calls == 4:
                return FakeResult([
                    ("AAA.SSE", date(2026, 6, 25), 10.0, None),
                    ("AAA.SSE", date(2026, 6, 26), 11.0, None),
                ])
            return FakeResult([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.sector_stocks(
        sector_id="BK0001",
        date=date(2026, 6, 26),
        sort_by="name",
        limit=50,
    )

    items = {item["vt_symbol"]: item for item in body["data"]["items"]}
    assert items["AAA.SSE"]["close"] == 11.0
    assert items["AAA.SSE"]["change_pct"] == 10.0
    assert items["AAA.SSE"]["price_date"] == "2026-06-26"
    assert items["BBB.SSE"]["close"] is None
    assert items["BBB.SSE"]["change_pct"] is None
    assert items["BBB.SSE"]["price_date"] is None
    assert items["AAA.SSE"]["return_5d"] is None
    assert items["AAA.SSE"]["limit_up_count_5d"] == 1


def test_sector_stocks_default_sorts_by_change_pct(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([("AAA.SSE", "甲股票"), ("BBB.SSE", "乙股票")])
            if self.calls == 2:
                return FakeResult([("AAA.SSE", 11.0), ("BBB.SSE", 21.0)])
            if self.calls == 3:
                return FakeResult([("AAA.SSE", 10.0), ("BBB.SSE", 20.0)])
            if self.calls == 4:
                return FakeResult([])
            return FakeResult([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.sector_stocks(
        sector_id="BK0001",
        date=date(2026, 6, 26),
        limit=50,
    )

    assert [item["vt_symbol"] for item in body["data"]["items"]] == ["AAA.SSE", "BBB.SSE"]
    assert [item["change_pct"] for item in body["data"]["items"]] == [10.0, 5.0]


def test_sector_stocks_uses_intraday_snapshot_when_daily_bar_missing(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([("AAA.SSE", "甲股票")])
            if self.calls == 2:
                return FakeResult([])
            if self.calls == 3:
                return FakeResult([])
            if self.calls == 4:
                return FakeResult([("AAA.SSE",)])
            if self.calls == 5:
                return FakeResult([("AAA.SSE", 12.0, 3.21, "14:30:00")])
            if self.calls == 6:
                return FakeResult([("AAA.SSE", 10.0)])
            if self.calls == 7:
                return FakeResult([
                    ("AAA.SSE", date(2026, 6, 26), 10.0, None),
                ])
            if self.calls == 8:
                return FakeResult([])
            return FakeResult([("AAA.SSE", 1000.0, 2.5)])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.sector_stocks(
        sector_id="BK0001",
        date=date(2026, 6, 29),
        sort_by="net_inflow",
        limit=50,
    )

    item = body["data"]["items"][0]
    assert item["close"] == 12.0
    assert item["change_pct"] == 20.0
    assert item["price_date"] == "2026-06-29"
    assert item["price_source"] == "intraday_snapshot"
    assert item["trade_time"] == "14:30:00"
    assert item["limit_up_count_5d"] == 1
    assert body["data"]["price_source"] == "intraday_snapshot"


def test_sector_stocks_does_not_use_snapshot_for_old_missing_daily_bar(monkeypatch):
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            del stmt
            self.calls += 1
            if self.calls == 1:
                return FakeResult([("AAA.SSE", "甲股票")])
            if self.calls == 2:
                return FakeResult([])
            if self.calls == 3:
                return FakeResult([(date(2026, 6, 26),)])
            if self.calls == 4:
                return FakeResult([])
            if self.calls == 5:
                return FakeResult([])
            if self.calls == 6:
                return FakeResult([])
            return FakeResult([("AAA.SSE", 1000.0, 2.5)])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)

    body = mainline_replay.sector_stocks(
        sector_id="BK0001",
        date=date(2026, 6, 20),
        sort_by="net_inflow",
        limit=50,
    )

    item = body["data"]["items"][0]
    assert item["close"] is None
    assert item["change_pct"] is None
    assert item["price_date"] is None
    assert item["price_source"] is None
    assert body["data"]["price_source"] is None


def test_recent_stock_momentum_adds_return_and_limit_up_count():
    d = date(2026, 6, 26)
    daily_bars = [
        {"trade_date": d - timedelta(days=7), "close": 10.0, "change_pct": None},
        {"trade_date": d - timedelta(days=6), "close": 10.5, "change_pct": None},
        {"trade_date": d - timedelta(days=5), "close": 11.55, "change_pct": 10.0},
        {"trade_date": d - timedelta(days=4), "close": 11.0, "change_pct": None},
        {"trade_date": d - timedelta(days=3), "close": 11.5, "change_pct": None},
        {"trade_date": d, "close": 12.0, "change_pct": None},
    ]

    momentum = mainline_replay._recent_stock_momentum(
        vt_symbol="AAA.SSE",
        stock_name="甲股票",
        selected_date=d,
        selected_close=12.0,
        selected_change_pct=None,
        daily_bars=daily_bars,
        limit_up_event_dates=set(),
    )

    assert momentum["return_5d"] == 20.0
    assert momentum["limit_up_count_5d"] == 1


def test_recent_stock_momentum_uses_limit_up_pool_events():
    d = date(2026, 6, 26)
    daily_bars = [
        {"trade_date": d - timedelta(days=7), "close": 10.0, "change_pct": None},
        {"trade_date": d - timedelta(days=6), "close": 10.2, "change_pct": None},
        {"trade_date": d - timedelta(days=5), "close": 10.3, "change_pct": None},
        {"trade_date": d - timedelta(days=4), "close": 10.4, "change_pct": None},
        {"trade_date": d - timedelta(days=3), "close": 10.5, "change_pct": None},
    ]

    momentum = mainline_replay._recent_stock_momentum(
        vt_symbol="AAA.SSE",
        stock_name="甲股票",
        selected_date=d,
        selected_close=10.6,
        selected_change_pct=1.0,
        daily_bars=daily_bars,
        limit_up_event_dates={d - timedelta(days=5)},
    )

    assert momentum["limit_up_count_5d"] == 1
