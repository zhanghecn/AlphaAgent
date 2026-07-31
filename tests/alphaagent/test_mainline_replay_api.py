"""API contract tests for mainline replay endpoints.

后端 FastAPI 不强制 JWT（鉴权在 Go 网关层），TestClient 可直接调。
若日后后端加全局鉴权依赖，需补 token / monkeypatch。
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

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
    # PK (vt_symbol, trade_date) 唯一：按日过滤完整交易日用 count(*) 即等价
    # count(DISTINCT vt_symbol)，无需 distinct 聚合。
    assert "count(*)" in captured["sql"].lower()
    assert "3000" in captured["params"]


def test_live_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/live")
    body = res.json()
    assert res.status_code == 200
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_sentiment_cycle_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/sentiment-cycle")
    body = res.json()
    assert res.status_code == 200
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_sentiment_cycle_points_track_short_term_metrics():
    d0 = date(2026, 6, 24)
    d1 = date(2026, 6, 25)
    d2 = date(2026, 6, 26)
    rows = [
        ("AAA.SSE", "甲股票", d0, 10.0, 10.0, None),
        ("AAA.SSE", "甲股票", d1, 11.0, 11.0, 10.0),
        ("AAA.SSE", "甲股票", d2, 12.1, 12.1, 10.0),
        ("BBB.SSE", "乙股票", d0, 10.0, 10.0, None),
        ("BBB.SSE", "乙股票", d1, 10.9, 11.1, 9.0),
        ("BBB.SSE", "乙股票", d2, 9.9, 10.1, -9.17),
        ("CCC.SSE", "丙股票", d0, 10.0, 10.0, None),
        ("CCC.SSE", "丙股票", d1, 9.0, 9.5, -10.0),
        ("CCC.SSE", "丙股票", d2, 9.45, 9.45, 5.0),
    ]

    points, state = mainline_replay._build_sentiment_cycle_points(rows, [d1, d2])

    assert len(points) == 2
    assert points[0]["date"] == "2026-06-25"
    assert points[0]["rise_count"] == 2
    assert points[0]["fall_count"] == 1
    assert points[0]["limit_up_count"] == 1
    assert points[0]["failed_limit_up_count"] == 1
    assert points[0]["limit_down_count"] == 1
    assert points[0]["max_limit_up_streak"] == 1
    assert points[0]["promotion_rate"] is None

    assert points[1]["limit_up_count"] == 1
    assert points[1]["previous_limit_up_count"] == 1
    assert points[1]["promoted_limit_up_count"] == 1
    assert points[1]["promotion_rate"] == 1.0
    assert points[1]["max_limit_up_streak"] == 2
    assert points[1]["score_change"] is not None
    assert state["AAA.SSE"]["limit_up_streak"] == 2

    # v2 影子指标：d2 昨日涨停仅 AAA（首板），今日续板且涨 10%
    shadow = points[1]["shadow"]
    assert shadow["prev_limit_up_avg_change"] == 10.0
    assert shadow["prev_limit_up_rise_ratio"] == 1.0
    assert shadow["promotion_1to2_rate"] == 1.0
    assert shadow["promotion_2to3_rate"] is None
    assert shadow["promotion_high_rate"] is None
    assert shadow["tier_samples"] == {"1to2": 1, "2to3": 0, "high": 0}
    assert shadow["consecutive_limit_up_count"] == 1
    # d1 无昨日涨停样本，影子值全为 None / 0
    assert points[0]["shadow"]["prev_limit_up_avg_change"] is None
    assert points[0]["shadow"]["promotion_1to2_rate"] is None


def test_sentiment_cycle_points_match_date_ordered_stream_scan():
    d0 = date(2026, 6, 24)
    d1 = date(2026, 6, 25)
    d2 = date(2026, 6, 26)
    rows = [
        ("AAA.SSE", "甲股票", d0, 10.0, 10.0, None),
        ("AAA.SSE", "甲股票", d1, 11.0, 11.0, 10.0),
        ("AAA.SSE", "甲股票", d2, 12.1, 12.1, 10.0),
        ("BBB.SSE", "乙股票", d0, 10.0, 10.0, None),
        ("BBB.SSE", "乙股票", d1, 10.8, 11.0, 8.0),
        ("BBB.SSE", "乙股票", d2, 11.9, 11.9, 10.0),
    ]

    points_by_symbol, state_by_symbol = mainline_replay._build_sentiment_cycle_points(
        sorted(rows, key=lambda row: (row[0], row[2])),
        [d1, d2],
    )
    points_by_date, state_by_date = mainline_replay._build_sentiment_cycle_points(
        sorted(rows, key=lambda row: (row[2], row[0])),
        [d1, d2],
    )

    assert points_by_date == points_by_symbol
    assert state_by_date == state_by_symbol


def test_live_high_map_returns_latest_minute_from_same_aggregation():
    latest = datetime(2026, 7, 30, 14, 56)

    class FakeResult:
        def all(self):
            return [
                ("AAA.SSE", 11.2, datetime(2026, 7, 30, 14, 55)),
                ("BBB.SSE", 8.6, latest),
                ("CCC.SSE", None, datetime(2026, 7, 30, 14, 54)),
            ]

    class FakeSession:
        def execute(self, stmt):
            compiled = stmt.compile()
            assert "max(stock_minute_bars.high_price)" in str(compiled)
            assert "max(stock_minute_bars.bar_time)" in str(compiled)
            return FakeResult()

    high_map, latest_bar_time = mainline_replay._load_live_high_map(
        FakeSession(),
        date(2026, 7, 30),
    )

    assert high_map == {"AAA.SSE": 11.2, "BBB.SSE": 8.6}
    assert latest_bar_time == latest


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
    monkeypatch.setattr(mainline_replay, "_is_mainline_realtime_window", lambda: False)

    body = mainline_replay.live(limit=10)

    assert body["data"]["mode"] == "live"
    assert body["data"]["trade_date"] == "2026-06-29"
    assert body["data"]["source"] == "sector_fund_flows:concept"
    assert any("sector_fund_flows.trade_date" in sql for sql in captured)


def test_live_defaults_to_today_realtime_hot_cache(monkeypatch):
    class FakeResult:
        def __init__(self, value=None):
            self._value = value

        def scalar(self):
            return self._value

    class FakeSession:
        def execute(self, stmt):
            del stmt
            return FakeResult(None)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    ranking = [{
        "sector_id": "BK1431",
        "name": "存储芯片",
        "data_mode": "live",
        "return_pct": 2.0,
        "main_net_inflow": 1000.0,
    }]

    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(mainline_replay, "session_scope", fake_session_scope)
    monkeypatch.setattr(mainline_replay, "_is_mainline_realtime_window", lambda: True)
    monkeypatch.setattr(
        mainline_replay,
        "_now_china",
        lambda: datetime(2026, 7, 10, 10, 30, tzinfo=timezone(timedelta(hours=8))),
    )
    monkeypatch.setattr(
        mainline_replay,
        "_fetch_live_concept_flow",
        lambda period="即时": {
            "items": [{"id": "BK1431", "name": "存储芯片", "trade_date": "2026-07-10"}],
            "resolved_trade_date": "2026-07-10",
            "fetched_at": "2026-07-10T10:30:00+08:00",
            "cache_state": "fresh",
        },
    )
    monkeypatch.setattr(mainline_replay, "_live_ranking_from_flow_items", lambda *args, **kwargs: ranking)
    monkeypatch.setattr(mainline_replay, "_enrich_concept_index_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(mainline_replay, "_live_flow_top_or_history", lambda *args, **kwargs: {"inflows": [], "outflows": [], "period": "即时", "actual_days": None})
    monkeypatch.setattr(mainline_replay, "_latest_complete_daily_date", lambda session: date(2026, 7, 9))

    body = mainline_replay.live(limit=10)

    assert body["data"]["trade_date"] == "2026-07-10"
    assert body["data"]["data_state"] == "realtime"
    assert body["data"]["realtime_updated_at"] == "2026-07-10T10:30:00+08:00"
    assert "hot_cache" in body["data"]["source"]
    assert body["data"]["ranking"][0]["sector_id"] == "BK1431"


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


def test_live_ranking_from_flow_items_uses_realtime_flow_and_previous_score():
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
                    ("BK1431", "存储芯片", "concept", None, [], 120, "龙头股", 4.2),
                ])
            return FakeResult([
                ("BK1431", 88.0, 70.0, 60.0, "MAINLINE_UP", 12.0, date(2026, 7, 9)),
            ])

    items = mainline_replay._live_ranking_from_flow_items(
        FakeSession(),
        date(2026, 7, 10),
        [{
            "id": "BK1431",
            "name": "存储芯片",
            "rank": 1,
            "change_pct": 2.5,
            "main_net_inflow": 1234.0,
            "main_net_inflow_pct": 1.2,
            "leader_stock": "龙头股",
        }],
        limit=10,
    )

    assert items[0]["sector_id"] == "BK1431"
    assert items[0]["return_pct"] == 2.5
    assert items[0]["historical_return_pct"] == 12.0
    assert items[0]["main_net_inflow"] == 1234.0
    assert items[0]["score_date"] == "2026-07-09"
    assert items[0]["data_mode"] == "live"


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


def test_flow_top_items_keep_flow_order_and_gain_detail_context():
    flow_top = {
        "inflows": [
            {"sector_id": "FLOW", "name": "资金概念", "net_inflow": 9_000_000_000.0},
            {"sector_id": "STORAGE", "name": "存储芯片", "net_inflow": 1_000_000_000.0},
        ],
        "outflows": [],
        "period": "即时",
        "actual_days": None,
    }
    ranking = [
        {
            "sector_id": "STORAGE",
            "name": "存储芯片",
            "continuation_status": "maintained",
            "index_points": [{"date": "2026-07-09", "close": 100.0}],
            "main_net_inflow": 1_000_000_000.0,
        },
        {
            "sector_id": "FLOW",
            "name": "资金概念",
            "continuation_status": "new",
            "index_points": [{"date": "2026-07-09", "close": 88.0}],
            "main_net_inflow": 9_000_000_000.0,
        },
    ]

    enriched = mainline_replay._attach_ranking_context_to_flow_top(flow_top, ranking)

    assert [item["sector_id"] for item in enriched["inflows"]] == ["FLOW", "STORAGE"]
    assert enriched["inflows"][0]["continuation_status"] == "new"
    assert enriched["inflows"][0]["index_points"][0]["close"] == 88.0
    assert enriched["inflows"][0]["net_inflow"] == 9_000_000_000.0


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
                    ("FLOW", 99.0, 100.0, 40.0, "ROTATION", 200, -2.0, None, "高资金概念", "concept", None, [], 50.0, 0.5),
                    ("STORAGE", 60.0, 30.0, 100.0, "MAINLINE_UP", 8, 30.0, None, "存储芯片", "concept", None, [], 100.0, 1.2),
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
            if self.calls == 5:
                return FakeResult([
                    ("FLOW", date(2026, 6, 29), 99.0, 100, "ROTATION"),
                    ("STORAGE", date(2026, 6, 29), 60.0, 8, "MAINLINE_UP"),
                ])
            return FakeResult([])

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
                return FakeResult([("BK1431", 88.0, 70.0, 60.0, "MAINLINE_UP", 1, 4.2, 0.9, "存储芯片", "concept", None, [], 100.0, 1.2)])
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
        industry_filter=False,
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
        industry_filter=False,
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
        industry_filter=False,
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
        industry_filter=False,
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


def test_continuation_status_marks_top_distribution_as_broken():
    """顶部派发：价格涨但主力明确净流出时，不应判 maintained。

    复现 2026-07-03 半导体概念：return_pct=+2.7% 但 main_net_inflow=-358 亿，
    旧 OR 逻辑因价格满足条件就标 maintained 排榜首，掩盖了资金撤退。
    """
    item = {"return_pct": 2.7, "main_net_inflow": -358e8}
    stats = {"current_hot": True}
    assert mainline_replay._continuation_status(item, stats, is_live=True) == "broken"


def test_continuation_status_non_hot_outflow_not_new():
    """非 hot 概念价格上涨但主力净流出时，不应判 new（应 watch）。"""
    item = {"return_pct": 5.0, "main_net_inflow": -20e8}
    stats = {"current_hot": False}
    assert mainline_replay._continuation_status(item, stats, is_live=True) == "watch"


def test_continuation_status_missing_flow_keeps_price_up_status():
    """资金流缺失(None)时不等于流出，价格涨仍按价格判定，避免数据缺失误降级。"""
    hot_item = {"return_pct": 3.0, "main_net_inflow": None}
    assert (
        mainline_replay._continuation_status(hot_item, {"current_hot": True}, is_live=True)
        == "maintained"
    )
    new_item = {"return_pct": 3.0, "main_net_inflow": None}
    assert (
        mainline_replay._continuation_status(new_item, {"current_hot": False}, is_live=True)
        == "new"
    )


def test_ranking_for_date_attaches_history_fund_flow_and_data_mode():
    """history snapshot 补主力净流入 + data_mode='history'，让历史也走派发判定。

    复现需求：07-02 等历史日的半导体主力流出也应被判断档，不能只看评分热度。
    """
    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        def execute(self, stmt):
            del stmt
            # 14 字段：评分(8) + sectors(4) + main_net_inflow + main_net_inflow_ratio
            return FakeResult([(
                "BK1431", 88.0, 70.0, 60.0, "MAINLINE_UP", 8, 30.0, 0.9,
                "半导体概念", "concept", None, [],
                -358e8, -5.5,
            )])

    items = mainline_replay._ranking_for_date(FakeSession(), date(2026, 7, 2), limit=10)
    assert items[0]["sector_id"] == "BK1431"
    assert items[0]["main_net_inflow"] == -358e8
    assert items[0]["data_mode"] == "history"
    assert items[0]["fund_inflow_available"] is True


def test_enrich_marks_history_distribution_as_broken():
    """history item（data_mode='history' + 主力净流出 + current_hot）应判 broken，不是 hot。"""
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
                return FakeResult([])  # 概念指数历史
            return FakeResult([
                ("BK1431", date(2026, 7, 2), 88.0, 8, "MAINLINE_UP"),
            ])  # activity → current_hot=True

    ranking = [{
        "sector_id": "BK1431",
        "data_mode": "history",
        "return_pct": 2.7,        # 滚动收益率仍为正
        "main_net_inflow": -358e8,  # 但历史那天主力巨量流出
    }]

    mainline_replay._enrich_concept_index_context(
        FakeSession(),
        ranking,
        date(2026, 7, 2),
        include_live_projection=False,
    )

    assert ranking[0]["continuation_status"] == "broken"
