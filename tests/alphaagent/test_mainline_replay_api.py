"""API contract tests for mainline replay endpoints.

后端 FastAPI 不强制 JWT（鉴权在 Go 网关层），TestClient 可直接调。
若日后后端加全局鉴权依赖，需补 token / monkeypatch。
"""

from contextlib import contextmanager
from datetime import date

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
    assert body["data"]["source"] == "sector_fund_flows"
    assert any("sector_fund_flows.trade_date" in sql for sql in captured)


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
