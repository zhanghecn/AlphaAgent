"""连板复盘 API 契约测试: /api/lianban/review + /api/lianban/dates。

不碰网络: AkShareAdapter/build_review 一律 monkeypatch; 需要真实库查询的
路径(归档判定/日期列表)用本文件的 api_session fixture(sqlite 内存库)。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alphaagent.server.api import lianban as lianban_api
from alphaagent.server.db import schema
from alphaagent.server.main import create_app
from alphaagent.server.services.lianban.review import ReviewNotFound
from alphaagent.server.services.lianban.review_cache import (
    invalidate_lianban_cache,
    review_payload_cache,
)

TODAY = date(2026, 8, 13)  # 周四(与 test_review 剧本的 D2 同日)
HIST = date(2026, 8, 12)  # 历史交易日
OLDER = date(2026, 8, 11)


@pytest.fixture(autouse=True)
def _clear_review_cache():
    review_payload_cache.clear()
    yield
    review_payload_cache.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def api_session():
    """sqlite 内存库会话(建 API 黏合查询涉及的两张表)。

    与 conftest.fake_session 的区别: TestClient 在独立线程跑 app, 需要
    StaticPool(全线程共享同一连接, 保证内存库是同一份) + check_same_thread
    =False(允许跨线程使用)。JSONB 的 sqlite 渲染钩子见 conftest。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    schema.limit_up_pool_snapshots.create(engine)
    schema.stock_limit_up_daily.create(engine)
    with Session(engine) as session:
        yield session


def _patch_session(monkeypatch, session) -> None:
    """端点 DB 依赖替换: session_scope 出产给定会话, 数据库视为已配置。"""

    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(lianban_api, "session_scope", fake_scope)
    monkeypatch.setattr(lianban_api, "is_database_configured", lambda: True)


def _patch_today(
    monkeypatch, day: date = TODAY, *, hour: int = 10, minute: int = 30,
    second: int = 0,
) -> None:
    """固定"现在"(中国时区); 默认 10:30 已过 live 时间闸(>= 09:25)。"""
    monkeypatch.setattr(
        lianban_api,
        "_now_china",
        lambda: datetime(day.year, day.month, day.day, hour, minute, second,
                         tzinfo=lianban_api.SHANGHAI),
    )


def _review_payload(mode: str = "final", day: date = HIST) -> dict:
    return {
        "trade_date": day.isoformat(),
        "mode": mode,
        "data_quality": {
            "pool_archived": mode == "final",
            "live": mode == "live",
            "rebuild_date": None,
            "missing": [],
        },
    }


class _SpyBuildReview:
    """build_review 替身: 记录调用, 可按需抛 ReviewNotFound。"""

    def __init__(self, payload: dict | None = None, exc: Exception | None = None):
        self.payload = payload
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(self, session, trade_date, **kwargs):
        self.calls.append({"trade_date": trade_date, **kwargs})
        if self.exc is not None:
            raise self.exc
        return self.payload or _review_payload(day=trade_date)


class _FakeLiveAdapter:
    """AkShareAdapter 替身: limit_up_pools 返回固定五池 payload 或抛异常;
    get_indices 返回固定指数行情列表(Quote 形状: vt_symbol/change_pct)或抛异常。"""

    def __init__(
        self,
        payload: dict | None = None,
        exc: Exception | None = None,
        indices: list | None = None,
        indices_exc: Exception | None = None,
    ):
        self.payload = payload
        self.exc = exc
        self.indices = indices
        self.indices_exc = indices_exc
        self.calls: list[tuple] = []

    def limit_up_pools(self, trade_date=None, *, per_pool_limit=200):
        self.calls.append((trade_date, per_pool_limit))
        if self.exc is not None:
            raise self.exc
        return self.payload

    def get_indices(self):
        if self.indices_exc is not None:
            raise self.indices_exc
        return self.indices or []


def _live_item(symbol: str = "600101", name: str = "甲股份") -> dict:
    """适配器规范化后的 item 形状(顶层 + raw 东财原始行)。"""
    return {
        "vt_symbol": f"{symbol}.SSE",
        "name": name,
        "close_price": 11.0,
        "change_pct": 10.0,
        "turnover_rate": 8.5,
        "volume_ratio": 2.1,
        "limit_amount": 3.4e8,
        "first_limit_time": "09:30:00",
        "last_limit_time": "09:30:00",
        "limit_up_count": 3,
        "raw": {"涨停统计": "3/3", "所属行业": "医药", "炸板次数": 0,
                "成交额": 1.2e8},
    }


def _live_pools_payload(**pool_overrides) -> dict:
    pools = {
        "zt": {"label": "涨停池", "items": [_live_item()], "total": 1},
        "zbgc": {"label": "炸板池",
                 "items": [_live_item("600102", "乙股份")], "total": 1},
        "dtgc": {"label": "跌停池", "items": [], "total": 0},
        "zt_previous": {"label": "昨日涨停",
                        "items": [_live_item("600104", "丁股份")], "total": 1},
        "strong": {"label": "强势股", "items": [], "total": 0},
    }
    pools.update(pool_overrides)
    return {"trade_date": "20260813", "pools": pools,
            "source": "akshare.stock_ztb_em"}


def _pool_row(day: date, symbol: str, *, pool: str = "zt") -> dict:
    return {
        "trade_date": day,
        "pool_type": pool,
        "vt_symbol": symbol,
        "name": "测试股",
        "limit_up_count": 1,
        "source": "test",
    }


def _daily_row(day: date, symbol: str) -> dict:
    return {
        "trade_date": day,
        "vt_symbol": symbol,
        "is_limit_up": True,
        "limit_up_count": 1,
        "is_one_word": False,
        "is_st": False,
        "board": "main",
        "close_price": 10.0,
        "change_pct": 10.0,
        "touched_limit": False,
        "source": "daily_rebuild",
    }


# ── review: 正常 / 404 / 422 / 503 ───────────────────────────────────────


def test_review_historical_returns_ok(client, monkeypatch, api_session):
    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get(f"/api/lianban/review?date={HIST.isoformat()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["mode"] == "final"
    assert payload["data"]["trade_date"] == HIST.isoformat()
    assert [c["trade_date"] for c in spy.calls] == [HIST]
    # 历史日期不带 override 关键字
    assert spy.calls[0].get("pool_rows_override") is None


def test_review_not_found_returns_404(client, monkeypatch, api_session):
    spy = _SpyBuildReview(exc=ReviewNotFound("复盘数据不存在: 2026-08-12"))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get(f"/api/lianban/review?date={HIST.isoformat()}")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "REVIEW_NOT_FOUND"


def test_review_invalid_date_returns_422(client, monkeypatch):
    _patch_session(monkeypatch, object())
    _patch_today(monkeypatch)

    response = client.get("/api/lianban/review?date=not-a-date")

    assert response.status_code == 422


def test_review_db_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(lianban_api, "is_database_configured", lambda: False)

    response = client.get(f"/api/lianban/review?date={HIST.isoformat()}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LIANBAN_DB_UNAVAILABLE"


# ── review: live 分流 ────────────────────────────────────────────────────


def test_review_live_mode_maps_realtime_pools(client, monkeypatch, api_session):
    """今日无归档 → live: 实时五池映射成归档行 override 走聚合。"""
    adapter = _FakeLiveAdapter(payload=_live_pools_payload())
    spy = _SpyBuildReview(payload=_review_payload(mode="live", day=TODAY))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["mode"] == "live"
    assert payload["data"]["data_quality"]["live"] is True
    # 适配器调用: 当日日期串 + 全量(防截断, TTL 缓存照样保护)
    assert adapter.calls == [("20260813", None)]
    # override 行经 archive.pool_row 映射: raw 字段解析正确
    assert len(spy.calls) == 1
    override = spy.calls[0]["pool_rows_override"]
    zt_row = override["zt"][0]
    assert zt_row["trade_date"] == TODAY
    assert zt_row["pool_type"] == "zt"
    assert zt_row["vt_symbol"] == "600101.SSE"
    assert zt_row["limit_stat_days"] == 3
    assert zt_row["limit_stat_boards"] == 3
    assert zt_row["first_limit_time"] == "09:30:00"
    assert zt_row["industry"] == "医药"
    assert zt_row["break_count"] == 0
    assert set(override) == {"zt", "zbgc", "dtgc", "zt_previous", "strong"}


def test_review_live_fetch_exception_returns_503(client, monkeypatch,
                                               api_session):
    adapter = _FakeLiveAdapter(exc=RuntimeError("eastmoney down"))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "LIANBAN_LIVE_UNAVAILABLE"
    assert payload["error"]["detail"]["reason"] == "RuntimeError"


def test_review_live_core_pool_unavailable_returns_503(client, monkeypatch,
                                                       api_session):
    """核心池(zt/zbgc/dtgc)任一不可用 → 503(家数/封板率必然失真)。"""
    payload = _live_pools_payload(
        zt={"label": "涨停池", "items": [], "total": 0, "status": "unavailable"}
    )
    adapter = _FakeLiveAdapter(payload=payload)
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LIANBAN_LIVE_UNAVAILABLE"
    assert response.json()["error"]["detail"]["pools"] == ["zt"]


def test_review_live_degraded_pool_annotates_missing(client, monkeypatch,
                                                     api_session):
    """非核心池(zt_previous/strong)不可用 → 降级空池 + missing 标注。"""
    payload = _live_pools_payload(
        zt_previous={"label": "昨日涨停", "items": [], "total": 0,
                     "status": "unavailable"}
    )
    adapter = _FakeLiveAdapter(payload=payload)
    live_payload = _review_payload(mode="live", day=TODAY)
    spy = _SpyBuildReview(payload=live_payload)
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 200
    missing = response.json()["data"]["data_quality"]["missing"]
    assert "pool:zt_previous" in missing
    # 降级池不进 override
    assert "zt_previous" not in spy.calls[0]["pool_rows_override"]


def test_review_today_archived_skips_live_and_cache(client, monkeypatch,
                                                    api_session):
    """今日已归档 → 不走 live 也不缓存(盘后可补偿重归档)。"""
    api_session.execute(
        insert(schema.limit_up_pool_snapshots),
        [_pool_row(TODAY, "600101.SSE")],
    )

    def _no_adapter():
        raise AssertionError("已归档当日不应触碰实时适配器")

    spy = _SpyBuildReview(payload=_review_payload(mode="final", day=TODAY))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", _no_adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    for _ in range(2):
        response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")
        assert response.status_code == 200
        assert response.json()["data"]["mode"] == "final"
    # 今日 final 不缓存: 两次都真实调用
    assert len(spy.calls) == 2


# ── review: 缺省日期(「打开复盘页=今日」) / 进程缓存 ─────────────────────


def test_review_default_weekday_intraday_returns_live(client, monkeypatch,
                                                      api_session):
    """缺省+工作日盘中: 今日未归档, 实时池 zt 非空 → live 返回。"""
    adapter = _FakeLiveAdapter(payload=_live_pools_payload())
    spy = _SpyBuildReview(payload=_review_payload(mode="live", day=TODAY))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["mode"] == "live"
    assert "fallback_from" not in payload["data_quality"]
    assert adapter.calls == [("20260813", None)]
    assert spy.calls[0]["trade_date"] == TODAY
    assert spy.calls[0]["pool_rows_override"]["zt"]


def test_review_default_weekday_premarket_falls_back(client, monkeypatch,
                                                     api_session):
    """缺省+工作日盘前: 实时池 zt 空 → 回落最近有数据日 + fallback_from 标注。"""
    api_session.execute(
        insert(schema.stock_limit_up_daily), [_daily_row(HIST, "600102.SSE")]
    )
    payload = _live_pools_payload(
        zt={"label": "涨停池", "items": [], "total": 0}
    )
    adapter = _FakeLiveAdapter(payload=payload)
    calls = []

    def fake_build(session, target, **kwargs):
        calls.append((target, kwargs))
        if kwargs.get("pool_rows_override") is not None:
            raise ReviewNotFound("复盘数据不存在: 实时涨停池为空")
        return _review_payload(mode="final", day=target)

    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", fake_build)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trade_date"] == HIST.isoformat()
    assert data["mode"] == "final"
    assert data["data_quality"]["fallback_from"] == TODAY.isoformat()
    # live 尝试(override) + 回落(无 override) 各一次
    assert [c[0] for c in calls] == [TODAY, HIST]
    assert calls[0][1].get("pool_rows_override") is not None
    assert calls[1][1].get("pool_rows_override") is None


def test_review_default_weekday_live_unavailable_falls_back(client, monkeypatch,
                                                            api_session):
    """缺省+工作日: 实时源异常 → 同样回落最近有数据日(不报 503)。"""
    api_session.execute(
        insert(schema.limit_up_pool_snapshots),
        [_pool_row(OLDER, "600101.SSE")],
    )
    api_session.execute(
        insert(schema.stock_limit_up_daily), [_daily_row(HIST, "600102.SSE")]
    )
    adapter = _FakeLiveAdapter(exc=RuntimeError("eastmoney down"))
    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trade_date"] == HIST.isoformat()  # max(归档 OLDER, 重建 HIST)
    assert data["data_quality"]["fallback_from"] == TODAY.isoformat()


def test_review_default_weekend_uses_latest(client, monkeypatch, api_session):
    """缺省+周末: 直接最近有数据日, 不试 live 也不标 fallback_from。"""
    api_session.execute(
        insert(schema.stock_limit_up_daily), [_daily_row(HIST, "600102.SSE")]
    )

    def _no_adapter():
        raise AssertionError("周末不应触碰实时适配器")

    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch, date(2026, 8, 15))  # 周六
    monkeypatch.setattr(lianban_api, "AkShareAdapter", _no_adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trade_date"] == HIST.isoformat()
    assert "fallback_from" not in data["data_quality"]
    assert spy.calls[0]["trade_date"] == HIST


def test_review_default_no_data_returns_404(client, monkeypatch, api_session):
    """缺省+工作日: 实时不可用且全库无数据 → 404。"""
    adapter = _FakeLiveAdapter(exc=RuntimeError("eastmoney down"))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)

    response = client.get("/api/lianban/review")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REVIEW_NOT_FOUND"


def test_review_explicit_today_empty_pool_returns_404_no_fallback(
    client, monkeypatch, api_session
):
    """显式 ?date=今日: 实时池空 → 404 不回落(即使存在可回落的历史日)。"""
    api_session.execute(
        insert(schema.stock_limit_up_daily), [_daily_row(HIST, "600102.SSE")]
    )
    payload = _live_pools_payload(
        zt={"label": "涨停池", "items": [], "total": 0}
    )
    adapter = _FakeLiveAdapter(payload=payload)

    def fake_build(session, target, **kwargs):
        if kwargs.get("pool_rows_override") is not None:
            raise ReviewNotFound("复盘数据不存在: 实时涨停池为空")
        return _review_payload(mode="final", day=target)

    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", fake_build)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REVIEW_NOT_FOUND"


# ── review: live 诚实性两道闸(时间闸 + 指纹闸) ───────────────────────────


def _seed_archive_zt(session, day: date, symbols: list[str]) -> None:
    session.execute(
        insert(schema.limit_up_pool_snapshots),
        [_pool_row(day, symbol) for symbol in symbols],
    )


def test_review_default_premarket_falls_back_without_adapter(
    client, monkeypatch, api_session
):
    """时间闸: 工作日 09:00(09:25 前)缺省 → 直接回落昨日, 不触碰适配器。"""
    api_session.execute(
        insert(schema.stock_limit_up_daily), [_daily_row(HIST, "600102.SSE")]
    )

    def _no_adapter():
        raise AssertionError("live 时间闸外不应触碰实时适配器")

    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch, TODAY, hour=9, minute=0)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", _no_adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trade_date"] == HIST.isoformat()
    assert data["data_quality"]["fallback_from"] == TODAY.isoformat()


def test_review_default_live_pool_matching_archive_falls_back(
    client, monkeypatch, api_session
):
    """指纹闸: 工作日 10:00 缺省, 实时 zt 名单 == 昨日归档名单 → 判定为
    最近交易日快照 → 回落昨日 + fallback_from。"""
    _seed_archive_zt(api_session, HIST, ["600101.SSE"])
    # 实时 zt 池与昨日归档完全一致(_live_pools_payload 默认单只 600101.SSE)
    adapter = _FakeLiveAdapter(payload=_live_pools_payload())
    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch, TODAY, hour=10, minute=0)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["trade_date"] == HIST.isoformat()
    assert data["mode"] == "final"
    assert data["data_quality"]["fallback_from"] == TODAY.isoformat()
    # 指纹闸拦截: build_review 未拿到 override(仅回落调用一次)
    assert [c["trade_date"] for c in spy.calls] == [HIST]
    assert spy.calls[0].get("pool_rows_override") is None


def test_review_default_live_pool_with_new_stock_passes(
    client, monkeypatch, api_session
):
    """指纹闸放行: 实时池比昨日归档多一只新涨停 → 真实盘中滚动 → live。"""
    _seed_archive_zt(api_session, HIST, ["600101.SSE"])
    payload = _live_pools_payload(
        zt={
            "label": "涨停池",
            "items": [_live_item(), _live_item("600102", "乙股份")],
            "total": 2,
        }
    )
    adapter = _FakeLiveAdapter(payload=payload)
    spy = _SpyBuildReview(payload=_review_payload(mode="live", day=TODAY))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch, TODAY, hour=10, minute=0)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    assert response.json()["data"]["mode"] == "live"
    assert spy.calls[0]["trade_date"] == TODAY
    assert spy.calls[0]["pool_rows_override"]["zt"]


def test_review_explicit_today_live_pool_matching_archive_returns_404(
    client, monkeypatch, api_session
):
    """指纹闸: 显式 ?date=今日, 实时名单 == 昨日归档 → 404(不回落)。"""
    _seed_archive_zt(api_session, HIST, ["600101.SSE"])
    adapter = _FakeLiveAdapter(payload=_live_pools_payload())

    def _no_build(session, target, **kwargs):
        raise AssertionError("指纹闸拦截后不应进入聚合")

    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch, TODAY, hour=10, minute=0)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", _no_build)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REVIEW_NOT_FOUND"


def test_review_default_settlement_window_returns_live(
    client, monkeypatch, api_session
):
    """15:15 整理窗口: 实时池为今日数据(名单与昨日归档不同)→ live 正常。"""
    _seed_archive_zt(api_session, HIST, ["600101.SSE"])
    payload = _live_pools_payload(
        zt={
            "label": "涨停池",
            "items": [_live_item("600105", "戊股份"),
                      _live_item("600106", "己股份")],
            "total": 2,
        }
    )
    adapter = _FakeLiveAdapter(payload=payload)
    spy = _SpyBuildReview(payload=_review_payload(mode="live", day=TODAY))
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch, TODAY, hour=15, minute=15)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get("/api/lianban/review")

    assert response.status_code == 200
    assert response.json()["data"]["mode"] == "live"
    assert spy.calls[0]["trade_date"] == TODAY


def test_review_live_window_boundaries(client, monkeypatch, api_session):
    """时间闸边界: 09:25:00 起(含深夜 23:30)试 live, 09:24:59 不含(回落)。"""
    adapter = _FakeLiveAdapter(payload=_live_pools_payload())
    spy = _SpyBuildReview(payload=_review_payload(mode="live", day=TODAY))
    _patch_session(monkeypatch, api_session)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    # 下界含: 09:25:00 → 试 live(无归档, 指纹闸放行)
    _patch_today(monkeypatch, TODAY, hour=9, minute=25, second=0)
    response = client.get("/api/lianban/review")
    assert response.status_code == 200
    assert response.json()["data"]["mode"] == "live"
    assert len(adapter.calls) == 1

    # 收盘后整理窗口: 17:15 → 仍试 live(当日完整名单)
    _patch_today(monkeypatch, TODAY, hour=17, minute=15, second=0)
    response = client.get("/api/lianban/review")
    assert response.json()["data"]["mode"] == "live"
    assert len(adapter.calls) == 2

    # 深夜: 23:30 → 仍试 live(eod 失败时兜底展示今日, 无右端限制)
    _patch_today(monkeypatch, TODAY, hour=23, minute=30, second=0)
    response = client.get("/api/lianban/review")
    assert response.json()["data"]["mode"] == "live"
    assert len(adapter.calls) == 3

    # 界外: 09:24:59 → 不试 live, 全库无数据 → 404
    def _no_adapter():
        raise AssertionError("live 时间闸外不应触碰实时适配器")

    monkeypatch.setattr(lianban_api, "AkShareAdapter", _no_adapter)
    _patch_today(monkeypatch, TODAY, hour=9, minute=24, second=59)
    response = client.get("/api/lianban/review")
    assert response.status_code == 404


# ── review: live 指数条实时填补 ──────────────────────────────────────────


def _live_payload_with_indices() -> dict:
    """live payload: 盘中库无当日日线 → 六指数格 change_pct 全 None + missing。"""
    specs = [
        ("sh", "上证", "000001.SSE"), ("sz", "深证", "399001.SZSE"),
        ("cyb", "创业板", "399006.SZSE"), ("kc50", "科创50", "000688.SSE"),
        ("sz50", "上证50", "000016.SSE"), ("bz50", "北证50", "899050.BSE"),
    ]
    return {
        "trade_date": TODAY.isoformat(),
        "mode": "live",
        "indices": [
            {"key": key, "name": name, "vt_symbol": vt, "change_pct": None}
            for key, name, vt in specs
        ],
        "data_quality": {
            "pool_archived": False,
            "live": True,
            "rebuild_date": None,
            "missing": [f"indices:{key}" for key, _, _ in specs],
        },
    }


def test_review_live_fills_indices_from_realtime_quotes(
    client, monkeypatch, api_session
):
    """live 路径: 实时指数行情填补盘中 null 指数条, 并摘掉对应 missing。"""
    adapter = _FakeLiveAdapter(
        payload=_live_pools_payload(),
        indices=[
            SimpleNamespace(vt_symbol="000001.SSE", name="上证指数",
                            change_pct=0.75),
            SimpleNamespace(vt_symbol="399001.SZSE", name="深证成指",
                            change_pct=-0.32),
            # 其余四指数实时行情缺失 → 对应格保持 null + missing
        ],
    )
    spy = _SpyBuildReview(payload=_live_payload_with_indices())
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 200
    data = response.json()["data"]
    indices = {entry["key"]: entry["change_pct"] for entry in data["indices"]}
    assert indices == {
        "sh": 0.75, "sz": -0.32, "cyb": None,
        "kc50": None, "sz50": None, "bz50": None,
    }
    missing = data["data_quality"]["missing"]
    assert "indices:sh" not in missing
    assert "indices:sz" not in missing
    assert "indices:cyb" in missing  # 无实时行情的格保持缺失标注


def test_review_live_indices_fetch_failure_keeps_null(
    client, monkeypatch, api_session
):
    """实时指数接口异常 → 保留 null 降级, 不阻塞 live。"""
    adapter = _FakeLiveAdapter(
        payload=_live_pools_payload(),
        indices_exc=RuntimeError("index source down"),
    )
    spy = _SpyBuildReview(payload=_live_payload_with_indices())
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "AkShareAdapter", lambda: adapter)
    monkeypatch.setattr(lianban_api, "build_review", spy)

    response = client.get(f"/api/lianban/review?date={TODAY.isoformat()}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert all(entry["change_pct"] is None for entry in data["indices"])
    assert "indices:sh" in data["data_quality"]["missing"]


def test_review_historical_cached_until_invalidate(client, monkeypatch,
                                                   api_session):
    """历史日期第二次命中缓存; invalidate_lianban_cache 后重新计算。"""
    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "build_review", spy)
    url = f"/api/lianban/review?date={HIST.isoformat()}"

    first = client.get(url)
    second = client.get(url)
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(spy.calls) == 1  # 第二次走进程缓存
    assert second.json()["data"] == first.json()["data"]

    invalidate_lianban_cache()
    third = client.get(url)
    assert third.status_code == 200
    assert len(spy.calls) == 2  # 失效后重新回源


def test_review_cache_targeted_invalidate(client, monkeypatch, api_session):
    """invalidate_lianban_cache(trade_date) 只失效指定日, 其余日期仍命中。"""
    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "build_review", spy)
    hist_url = f"/api/lianban/review?date={HIST.isoformat()}"
    older_url = f"/api/lianban/review?date={OLDER.isoformat()}"

    client.get(hist_url)
    client.get(older_url)
    assert len(spy.calls) == 2

    invalidate_lianban_cache(HIST)
    client.get(hist_url)  # 指定日已失效 → 重新回源
    client.get(older_url)  # 未失效 → 仍命中缓存
    assert len(spy.calls) == 3


def test_review_cache_version_stamp_reloads_on_data_change(
    client, monkeypatch, api_session
):
    """版本戳跨进程失效: 缓存命中后该日归档 updated_at 前进(模拟 worker
    进程重跑 backfill/归档)→ 下次请求自然回源; 他日缓存不受影响。"""
    t1 = datetime(2026, 8, 12, 20, 0, 0)
    api_session.execute(
        insert(schema.limit_up_pool_snapshots),
        [
            {**_pool_row(HIST, "600101.SSE"), "updated_at": t1},
            {**_pool_row(OLDER, "600103.SSE"), "updated_at": t1},
        ],
    )
    spy = _SpyBuildReview()
    _patch_session(monkeypatch, api_session)
    _patch_today(monkeypatch)
    monkeypatch.setattr(lianban_api, "build_review", spy)
    hist_url = f"/api/lianban/review?date={HIST.isoformat()}"
    older_url = f"/api/lianban/review?date={OLDER.isoformat()}"

    client.get(hist_url)
    client.get(older_url)
    client.get(hist_url)  # 命中缓存
    assert len(spy.calls) == 2

    # worker 进程重写了 HIST 当日归档行: updated_at 前进 → 版本戳变
    t2 = datetime(2026, 8, 12, 21, 0, 0)
    api_session.execute(
        update(schema.limit_up_pool_snapshots)
        .where(schema.limit_up_pool_snapshots.c.trade_date == HIST)
        .values(updated_at=t2)
    )

    reloaded = client.get(hist_url)  # key 变 → miss → 回源
    assert reloaded.status_code == 200
    assert len(spy.calls) == 3
    client.get(older_url)  # 他日版本未变 → 仍命中
    assert len(spy.calls) == 3


# ── dates 端点 ───────────────────────────────────────────────────────────


def test_dates_returns_descending_union(client, monkeypatch, api_session):
    api_session.execute(
        insert(schema.limit_up_pool_snapshots),
        [_pool_row(OLDER, "600101.SSE"), _pool_row(HIST, "600102.SSE")],
    )
    api_session.execute(
        insert(schema.stock_limit_up_daily),
        [_daily_row(HIST, "600102.SSE"), _daily_row(TODAY, "600103.SSE")],
    )
    _patch_session(monkeypatch, api_session)

    response = client.get("/api/lianban/dates")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    # 归档 {OLDER, HIST} ∪ 重建 {HIST, TODAY}, 去重降序
    assert payload["data"]["dates"] == [
        TODAY.isoformat(), HIST.isoformat(), OLDER.isoformat()
    ]
    assert payload["data"]["latest"] == TODAY.isoformat()


def test_dates_empty_tables(client, monkeypatch, api_session):
    _patch_session(monkeypatch, api_session)

    response = client.get("/api/lianban/dates")

    assert response.status_code == 200
    assert response.json()["data"] == {"dates": [], "latest": None}
