"""明日推演(同景统计)服务 + API 契约测试。

剧本数据(确定性):
- 上证指数 000001.SSE 300 个连续日 bar: 0..249 收盘 3000(day 249 MA250=3000,
  close==MA → 年线上方, >= 口径); 250..253 四根 3050/3060/3055/3070(上方);
  254..299 在 2895..2905 震荡(MA250≈2980+, 全部年线下方)。
- 情绪 points 覆盖 250..299: 250..253 climax; 254..295 偶数 ebb/奇数 repair;
  296..299 连续 ebb → trade_date=day(299) 时 phase_day=4。
- 同景(ebb+年线下方)样本 = 254..298 的 ebb 日 = 21(偶数)+296/297/298 = 24。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from statistics import mean, median

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from alphaagent.server.api import lianban as lianban_api
from alphaagent.server.db import schema
from alphaagent.server.main import create_app
from alphaagent.server.services.lianban.projection import (
    latest_sentiment_point_date,
    same_scene_projection,
)

BASE = date(2025, 1, 1)
TRADE_DATE = BASE + timedelta(days=299)  # 最后一个有点/有 bar 的日子
SH_INDEX = "000001.SSE"

_PHASE_LABELS = {
    "ice": "冰点",
    "repair": "修复",
    "divergence": "分歧",
    "climax": "高潮",
    "ebb": "退潮",
}


def _day(i: int) -> date:
    return BASE + timedelta(days=i)


def _closes() -> list[float]:
    closes = [3000.0] * 250
    closes += [3050.0, 3060.0, 3055.0, 3070.0]
    for i in range(254, 300):
        closes.append(2900.0 + ((i * 7) % 11) - 5)
    return closes


def _phase(i: int) -> str:
    if i <= 253:
        return "climax"
    if i >= 296:
        return "ebb"
    return "ebb" if i % 2 == 0 else "repair"


def _score(i: int) -> float:
    return float(40 + (i % 7))


def _seed_index(session, closes: list[float] | None = None) -> None:
    session.execute(
        insert(schema.stocks),
        [{
            "vt_symbol": SH_INDEX, "symbol": "000001", "exchange": "SSE",
            "name": "上证指数", "source": "test",
        }],
    )
    session.execute(
        insert(schema.stock_daily_bars),
        [
            {
                "vt_symbol": SH_INDEX,
                "trade_date": _day(i),
                "open_price": close,
                "close_price": close,
                "high_price": close,
                "low_price": close,
                "source": "test",
            }
            for i, close in enumerate(closes or _closes())
        ],
    )


def _seed_points(
    session, *, drop: set[int] = frozenset(), temporary: set[int] = frozenset()
) -> None:
    points = [
        {
            "date": _day(i).isoformat(),
            "phase": _phase(i),
            "phase_label": _PHASE_LABELS[_phase(i)],
            "score": _score(i),
            "temporary": i in temporary,
        }
        for i in range(250, 300)
        if i not in drop
    ]
    session.execute(
        insert(schema.mainline_sentiment_history),
        [{
            "id": 1,
            "anchor_date": TRADE_DATE,
            "history_span_days": len(points),
            "points": points,
            "symbol_state": {},
        }],
    )


# ===== 独立重算助手(与服务实现不同代码路径, 交叉验证) =====


def _above_ma250_flags(closes: list[float]) -> list[bool | None]:
    """逐日 close >= 含当日 250 日收盘均值; 不足 250 日 → None。"""
    flags: list[bool | None] = []
    for i, close in enumerate(closes):
        if i < 249:
            flags.append(None)
        else:
            flags.append(close >= mean(closes[i - 249 : i + 1]))
    return flags


def _expected_sample_indices(target_i: int) -> list[int]:
    """同景样本日下标: 同 phase + 同年线位置 + 严格早于目标日 + 有次日 bar。"""
    closes = _closes()
    flags = _above_ma250_flags(closes)
    out = []
    for i in range(250, 300):
        if i >= target_i or _phase(i) != _phase(target_i):
            continue
        if flags[i] is None or flags[i] != flags[target_i]:
            continue
        if i + 1 >= len(closes):
            continue
        out.append(i)
    return out


def _next_change(closes: list[float], i: int) -> float:
    return (closes[i + 1] / closes[i] - 1) * 100


# ===== 服务层契约 =====


def test_ready_full_contract(fake_session):
    _seed_index(fake_session)
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, TRADE_DATE)

    assert result["status"] == "ready"
    assert result["trade_date"] == TRADE_DATE.isoformat()
    assert result["phase"] == "ebb"
    assert result["phase_label"] == "退潮"
    assert result["phase_day"] == 4  # 296..299 连续 ebb
    assert result["above_ma250"] is False

    closes = _closes()
    samples = _expected_sample_indices(299)
    assert len(samples) == 24  # 剧本自检
    assert result["sample_count"] == 24

    changes = [_next_change(closes, i) for i in samples]
    next_day = result["next_day"]
    assert next_day["up_prob"] == round(sum(1 for c in changes if c > 0) / 24, 3)
    assert next_day["avg_change"] == round(mean(changes), 2)
    assert next_day["median_change"] == round(median(changes), 2)

    # 次日阶段: 偶数样本日的次日是 repair(21), 296/297/298 的次日是 ebb(3)
    assert result["phase_next"] == [
        {"phase": "repair", "label": "修复", "count": 21, "ratio": round(21 / 24, 2)},
        {"phase": "ebb", "label": "退潮", "count": 3, "ratio": round(3 / 24, 2)},
    ]

    score_diffs = [_score(i + 1) - _score(i) for i in samples]
    assert result["score_change_avg"] == round(mean(score_diffs), 1)


def test_scene_dates_desc_and_limited(fake_session):
    _seed_index(fake_session)
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, TRADE_DATE, limit_dates=3)

    closes = _closes()
    assert [entry["date"] for entry in result["scene_dates"]] == [
        _day(298).isoformat(),
        _day(297).isoformat(),
        _day(296).isoformat(),
    ]
    for entry, i in zip(result["scene_dates"], (298, 297, 296), strict=True):
        assert entry["next_change"] == round(_next_change(closes, i), 2)
        assert entry["next_phase"] == "退潮"


def test_scene_dates_default_limit_20(fake_session):
    _seed_index(fake_session)
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, TRADE_DATE)

    assert len(result["scene_dates"]) == 20
    assert result["scene_dates"][0]["date"] == _day(298).isoformat()


def test_samples_strictly_before_trade_date(fake_session):
    """站在历史日推演只能用该日之前的样本(防未来函数)。"""
    _seed_index(fake_session)
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, _day(290))

    samples = _expected_sample_indices(290)
    assert result["status"] == "ready"
    assert result["sample_count"] == len(samples) == 18  # 偶数 254..288
    assert result["phase_day"] == 1  # 290 ebb, 289 repair
    assert result["scene_dates"][0]["date"] == _day(288).isoformat()


def test_insufficient_when_samples_below_10(fake_session):
    """样本 <10 → insufficient_data, 但已有统计照常返回。"""
    _seed_index(fake_session)
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, _day(253))  # climax + 年线上方

    assert result["status"] == "insufficient_data"
    assert result["phase"] == "climax"
    assert result["phase_label"] == "高潮"
    assert result["phase_day"] == 4  # 250..253 连续 climax
    assert result["above_ma250"] is True
    assert result["sample_count"] == 3  # 250/251/252
    closes = _closes()
    changes = [_next_change(closes, i) for i in (250, 251, 252)]
    assert result["next_day"]["up_prob"] == round(
        sum(1 for c in changes if c > 0) / 3, 3
    )
    assert result["next_day"]["avg_change"] == round(mean(changes), 2)
    assert result["phase_next"] == [
        {"phase": "climax", "label": "高潮", "count": 3, "ratio": 1.0}
    ]


def test_no_sentiment_point_returns_insufficient_skeleton(fake_session):
    """当日无情绪点 → insufficient_data, 统计全 None, 不炸。"""
    _seed_index(fake_session)
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, _day(249))  # 有 bar 无 point

    assert result == {
        "trade_date": _day(249).isoformat(),
        "phase": None,
        "phase_label": None,
        "phase_day": None,
        "above_ma250": None,
        "sample_count": 0,
        "next_day": {"up_prob": None, "avg_change": None, "median_change": None},
        "phase_next": [],
        "score_change_avg": None,
        "scene_dates": [],
        "status": "insufficient_data",
    }


def test_no_index_bars_returns_insufficient(fake_session):
    """有情绪点但无指数数据 → insufficient; 阶段字段如实回填, 统计 None。"""
    _seed_points(fake_session)

    result = same_scene_projection(fake_session, TRADE_DATE)

    assert result["status"] == "insufficient_data"
    assert result["phase"] == "ebb"
    assert result["phase_label"] == "退潮"
    assert result["phase_day"] == 4
    assert result["above_ma250"] is None
    assert result["sample_count"] == 0
    assert result["next_day"] == {
        "up_prob": None,
        "avg_change": None,
        "median_change": None,
    }
    assert result["phase_next"] == []
    assert result["score_change_avg"] is None
    assert result["scene_dates"] == []


def test_temporary_points_excluded(fake_session):
    """temporary=True 的盘中投影点不进样本也不进连续天数。"""
    _seed_index(fake_session)
    _seed_points(fake_session, temporary={296})

    result = same_scene_projection(fake_session, TRADE_DATE)

    assert result["sample_count"] == 23  # 296 被剔除
    assert result["phase_day"] == 3  # 连续段被 295(repair) 截断
    assert all(
        entry["date"] != _day(296).isoformat() for entry in result["scene_dates"]
    )


def test_next_day_without_point_skips_phase_and_score(fake_session):
    """次日无情绪点: 样本仍进涨幅统计, 但不进 phase_next / score_change_avg。"""
    _seed_index(fake_session)
    _seed_points(fake_session, drop={255})  # 254 的次日无 point

    result = same_scene_projection(fake_session, TRADE_DATE, limit_dates=50)

    assert result["sample_count"] == 24  # 涨幅统计不受 255 缺 point 影响
    assert result["phase_next"] == [
        {"phase": "repair", "label": "修复", "count": 20, "ratio": round(20 / 24, 2)},
        {"phase": "ebb", "label": "退潮", "count": 3, "ratio": round(3 / 24, 2)},
    ]
    score_diffs = [
        _score(i + 1) - _score(i) for i in _expected_sample_indices(299) if i != 254
    ]
    assert result["score_change_avg"] == round(mean(score_diffs), 1)
    entry_254 = next(
        e for e in result["scene_dates"] if e["date"] == _day(254).isoformat()
    )
    assert entry_254["next_phase"] is None


def test_latest_sentiment_point_date(fake_session):
    assert latest_sentiment_point_date(fake_session) is None

    _seed_points(fake_session)
    assert latest_sentiment_point_date(fake_session) == TRADE_DATE


# ===== API 契约 =====


@pytest.fixture(autouse=True)
def _clear_projection_cache():
    lianban_api.projection_cache.clear()
    yield
    lianban_api.projection_cache.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def api_session():
    """sqlite 内存库会话(StaticPool 跨线程共享, 与 test_api.py 同手法)。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    schema.stocks.create(engine)
    schema.stock_daily_bars.create(engine)
    schema.mainline_sentiment_history.create(engine)
    with Session(engine) as session:
        yield session


def _patch_session(monkeypatch, session) -> None:
    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(lianban_api, "session_scope", fake_scope)
    monkeypatch.setattr(lianban_api, "is_database_configured", lambda: True)


def test_api_explicit_date_ok(client, monkeypatch, api_session):
    _seed_index(api_session)
    _seed_points(api_session)
    _patch_session(monkeypatch, api_session)

    response = client.get(f"/api/lianban/projection?date={TRADE_DATE.isoformat()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "ready"
    assert data["trade_date"] == TRADE_DATE.isoformat()
    assert data["phase"] == "ebb"
    assert data["phase_label"] == "退潮"
    assert data["phase_day"] == 4
    assert data["above_ma250"] is False
    assert data["sample_count"] == 24
    assert data["phase_next"][0]["label"] == "修复"
    assert len(data["scene_dates"]) == 20


def test_api_default_date_uses_latest_point(client, monkeypatch, api_session):
    _seed_index(api_session)
    _seed_points(api_session)
    _patch_session(monkeypatch, api_session)

    response = client.get("/api/lianban/projection")

    assert response.status_code == 200
    assert response.json()["data"]["trade_date"] == TRADE_DATE.isoformat()


def test_api_no_points_returns_ok_insufficient(client, monkeypatch, api_session):
    _patch_session(monkeypatch, api_session)

    response = client.get("/api/lianban/projection")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "insufficient_data"
    assert data["trade_date"] is None
    assert data["sample_count"] == 0


def test_api_invalid_date_returns_422(client, monkeypatch, api_session):
    _patch_session(monkeypatch, api_session)

    response = client.get("/api/lianban/projection?date=not-a-date")

    assert response.status_code == 422


def test_api_db_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(lianban_api, "is_database_configured", lambda: False)

    response = client.get(f"/api/lianban/projection?date={TRADE_DATE.isoformat()}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LIANBAN_DB_UNAVAILABLE"


def test_api_caches_within_ttl(client, monkeypatch, api_session):
    """60s TTL 进程缓存: 同日期第二次请求不再调服务。"""
    _patch_session(monkeypatch, api_session)
    calls = []
    payload = {
        "trade_date": TRADE_DATE.isoformat(),
        "status": "ready",
        "sample_count": 24,
    }

    def spy(session, trade_date, **kwargs):
        calls.append(trade_date)
        return dict(payload)

    monkeypatch.setattr(lianban_api, "same_scene_projection", spy)

    first = client.get(f"/api/lianban/projection?date={TRADE_DATE.isoformat()}")
    second = client.get(f"/api/lianban/projection?date={TRADE_DATE.isoformat()}")

    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert calls == [TRADE_DATE]
