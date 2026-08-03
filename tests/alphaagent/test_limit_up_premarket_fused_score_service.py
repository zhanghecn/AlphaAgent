"""盘前融合计分候选服务测试：单票打分拒因、L7 方向、缓存、快照过滤、txt、API。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

import alphaagent.server.api.limit_up as api
import alphaagent.server.services.limit_up.premarket_fused_score_service as service
from alphaagent.server.services.limit_up.premarket_fused_score_service import (
    _filter_snapshot,
    _screen_symbol,
    render_candidates_txt,
)

LATEST = "2026-07-31"


def _bars(
    closes: list[float],
    *,
    symbol: str = "600001.SSE",
    latest: str = LATEST,
) -> list[dict[str, Any]]:
    """合成日线（最后一根日期=latest），含 open/change/turnover。"""

    n = len(closes)
    last_day = date.fromisoformat(latest)
    return [
        {
            "vt_symbol": symbol,
            "trade_date": (last_day - timedelta(days=n - 1 - index)).isoformat(),
            "open_price": closes[index],
            "close_price": closes[index],
            "high_price": closes[index],
            "low_price": closes[index],
            "change_pct": 1.0,
            "turnover": 100.0,
        }
        for index in range(n)
    ]


def _bull_bars() -> list[dict[str, Any]]:
    return _bars([10.0 + index * 0.1 for index in range(75)])


def _bear_base_bars() -> list[dict[str, Any]]:
    """长空头基底（75 根线性阴跌）：bear_run=40 满窗，低位型入榜。"""

    return _bars([30.0 - index * 0.1 for index in range(75)])


# ── _screen_symbol 打分与拒因 ──────────────────────────────────────────────


def test_screen_bull_bars_wave_qualified() -> None:
    hit = _screen_symbol(_bull_bars(), set(), latest=LATEST)
    assert hit is not None
    assert hit["fused_type"] == "wave"
    assert hit["fused_score"] > 0
    assert hit["lowpos_score"] == 0  # 无空头基底
    assert hit["wave_score"] > 0
    assert set(hit["wave_subs"]) == {
        "W1_bull_duration",
        "W2_pullback",
        "W3_stabilize",
        "W4_volume",
    }


def test_screen_bear_base_lowpos_qualified() -> None:
    hit = _screen_symbol(_bear_base_bars(), set(), latest=LATEST)
    assert hit is not None
    assert hit["fused_type"] == "lowpos"
    assert hit["lowpos_score"] > 0
    assert hit["bear_run_max_40d"] == 40
    assert set(hit["lowpos_subs"]) == {
        "L1_depth",
        "L2_duration",
        "L3_converge",
        "L4_stage",
        "L5_stabilize",
        "L6_volume",
        "L7_recent_touch",
    }


def test_screen_l7_recent_touch_direction() -> None:
    """v2 方向：近 20 日有触碰 L7=1；无触碰 L7=0。"""

    bars = _bear_base_bars()
    touch_day = str(bars[-1]["trade_date"])
    with_touch = _screen_symbol(bars, {touch_day}, latest=LATEST)
    without_touch = _screen_symbol(bars, set(), latest=LATEST)
    assert with_touch is not None and without_touch is not None
    assert with_touch["lowpos_subs"]["L7_recent_touch"] == 1.0
    assert without_touch["lowpos_subs"]["L7_recent_touch"] == 0.0
    assert with_touch["lowpos_score"] > without_touch["lowpos_score"]


def test_screen_rejects() -> None:
    # 横盘缠绕无基底：低位/波浪门都不过 → None
    assert _screen_symbol(_bars([10.0] * 75), set(), latest=LATEST) is None
    # 历史不足 69 根
    assert _screen_symbol(_bull_bars()[:60], set(), latest=LATEST) is None
    # 最新日期不符（停牌）
    stale = _bull_bars()
    stale[-1]["trade_date"] = "2026-07-30"
    assert _screen_symbol(stale, set(), latest=LATEST) is None
    # D-1 涨停
    limit_bars = _bull_bars()
    limit_bars[-1]["close_price"] = float(limit_bars[-2]["close_price"]) * 1.1
    assert _screen_symbol(limit_bars, set(), latest=LATEST) is None


# ── 快照过滤 / txt ─────────────────────────────────────────────────────────


def _snapshot_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "trade_date": LATEST,
        "params": {"score_type": "all", "min_score": 0.0},
        "count": 3,
        "total": 3,
        "qualified_total": 3,
        "candidates": [
            {"code": "600001", "vt_symbol": "600001.SSE", "fused_score": 0.8, "fused_type": "lowpos"},
            {"code": "600002", "vt_symbol": "600002.SSE", "fused_score": 0.5, "fused_type": "wave"},
            {"code": "600003", "vt_symbol": "600003.SSE", "fused_score": 0.3, "fused_type": "both"},
        ],
    }


def test_filter_snapshot_by_type_and_min_score() -> None:
    wave_only = _filter_snapshot(_snapshot_payload(), "wave", 0.0, 100)
    assert wave_only["count"] == 1
    assert wave_only["candidates"][0]["code"] == "600002"
    high = _filter_snapshot(_snapshot_payload(), "all", 0.4, 100)
    assert high["count"] == 2
    limited = _filter_snapshot(_snapshot_payload(), "all", 0.0, 2)
    assert limited["count"] == 2
    assert limited["total"] == 3  # total 不受截断影响


def test_render_candidates_txt() -> None:
    txt = render_candidates_txt(_snapshot_payload())
    assert txt.splitlines() == ["600001", "600002", "600003"]
    assert render_candidates_txt({"candidates": []}) == ""


# ── build_premarket_fused_score_candidates（loader 全 monkeypatch）─────────


@pytest.fixture(autouse=True)
def _reset_cache():
    service._candidates_cache.update({"at": None, "key": None, "value": None})
    yield
    service._candidates_cache.update({"at": None, "key": None, "value": None})


def _patch_loaders(monkeypatch: pytest.MonkeyPatch, calls: dict[str, int]) -> None:
    monkeypatch.setattr(service, "load_latest_daily_trade_date", lambda: date(2026, 7, 31))

    def _fake_daily_bars(start: date, end: date) -> list[dict[str, Any]]:
        calls["daily_bars"] += 1
        return _bull_bars()

    monkeypatch.setattr(service, "load_daily_bars_all", _fake_daily_bars)
    monkeypatch.setattr(
        service, "load_limit_up_dataset", lambda start, end: {"events": []}
    )
    monkeypatch.setattr(service, "load_stock_names", lambda: {"600001.SSE": "示例股份"})
    monkeypatch.setattr(service, "load_sector_memberships_all", lambda: [])
    monkeypatch.setattr(service, "_load_sector_names", lambda: {})


def test_build_candidates_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"daily_bars": 0}
    _patch_loaders(monkeypatch, calls)
    result = service.build_premarket_fused_score_candidates()
    assert result["status"] == "ok"
    assert result["trade_date"] == LATEST
    assert result["count"] == 1
    candidate = result["candidates"][0]
    assert candidate["code"] == "600001"
    assert candidate["fused_type"] == "wave"
    assert candidate["fused_score"] > 0


def test_build_candidates_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"daily_bars": 0}
    _patch_loaders(monkeypatch, calls)
    service.build_premarket_fused_score_candidates()
    service.build_premarket_fused_score_candidates()
    assert calls["daily_bars"] == 1  # 第二次走 60s 缓存


def test_build_candidates_unavailable_when_no_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_latest_daily_trade_date", lambda: None)
    result = service.build_premarket_fused_score_candidates()
    assert result["status"] == "unavailable"


# ── API 端点 ───────────────────────────────────────────────────────────────


def test_api_fused_503_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "is_database_configured", lambda: False)
    response = api.premarket_fused_candidates()
    assert response.status_code == 503


def test_api_fused_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        service,
        "get_premarket_fused_score_candidates",
        lambda **kwargs: {"status": "ok", "trade_date": LATEST, "candidates": []},
    )
    result = api.premarket_fused_candidates()
    assert result["success"] is True
    assert result["data"]["trade_date"] == LATEST


def test_api_fused_txt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        service,
        "get_premarket_fused_score_candidates",
        lambda **kwargs: {
            "status": "ok",
            "trade_date": LATEST,
            "candidates": [{"code": "600001"}, {"code": "000002"}],
        },
    )
    response = api.premarket_fused_candidates_txt()
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.body.decode() == "600001\n000002\n"
