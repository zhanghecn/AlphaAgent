"""盘前低位首板候选筛选测试：单票筛选拒因、缓存、txt 格式、快照读写、API 端点。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

import alphaagent.server.api.limit_up as api
import alphaagent.server.services.limit_up.premarket_prelude_service as service
from alphaagent.server.services.limit_up.premarket_prelude_service import (
    _screen_symbol,
    render_candidates_txt,
)

LATEST = "2026-07-31"


def _low_position_closes(n: int = 130) -> list[float]:
    """主人版低位价格轨迹：前高 15.0（126 日高点），后段贴底 10.0。

    position_126d=0、drawdown=-33%、rebound=0——三条件全满足的贴底票。
    """

    return [15.0] * (n - 30) + [10.0] * 30


def _bars(
    n: int = 130,
    *,
    changes: list[float] | None = None,
    closes: list[float] | None = None,
    turnovers: list[float] | None = None,
    latest: str = LATEST,
) -> list[dict[str, Any]]:
    """合成 n 根日线（最后一根日期=latest）。默认低位、无形态、量稳。"""

    changes = changes if changes is not None else [(0.5 if i % 2 == 0 else -0.4) for i in range(n)]
    closes = closes or _low_position_closes(n)
    turnovers = turnovers or [100.0] * n
    last_day = date.fromisoformat(latest)
    return [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": (last_day - timedelta(days=n - 1 - index)).isoformat(),
            "close_price": closes[index],
            "high_price": closes[index],  # 126 日窗口特征需要 high/low
            "low_price": closes[index],
            "change_pct": changes[index],
            "turnover": turnovers[index],
        }
        for index in range(n)
    ]


def _yang_bars() -> list[dict[str, Any]]:
    changes = [(0.5 if i % 2 == 0 else -0.4) for i in range(127)] + [2.0, 2.0, 2.0]
    return _bars(changes=changes)


def _screen(bars: list[dict[str, Any]], **overrides: Any) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "latest": LATEST,
        "pattern": "all",
        "max_change_pct": 3.0,
        "max_vol_cv": None,
        "min_vol_shift": None,
        "max_vol_shift": None,
    }
    params.update(overrides)
    return _screen_symbol(bars, **params)


# ── _screen_symbol 拒因 ──────────────────────────────────────────────────


def test_low_position_passes_with_all_pattern() -> None:
    hit = _screen(_bars())
    assert hit is not None
    assert hit["prelude_pattern"] == "none"  # 默认交替涨跌无形态，all 不卡形态
    assert hit["return_20d_pct"] == 0.0


def test_small_yang_pattern_optional_filter() -> None:
    # 有形态：has_pattern / small_yang 通过
    assert _screen(_yang_bars(), pattern="has_pattern") is not None
    assert _screen(_yang_bars(), pattern="small_yang") is not None
    assert _screen(_yang_bars(), pattern="small_yin") is None
    # 无形态：has_pattern 拒、all 不拒
    assert _screen(_bars(), pattern="has_pattern") is None
    assert _screen(_bars(), pattern="all") is not None


def test_not_low_position_rejected() -> None:
    # 高位轨迹：前段 8.0 后段 13.0 → position=1.0、drawdown=0、rebound=62.5% → 非低位
    closes = [8.0] * 100 + [13.0] * 30
    assert _screen(_bars(closes=closes)) is None
    # 中位轨迹（至纯科技型：半年位置 0.69、反弹 +43.6%）→ 非低位
    closes_mid = [10.0] * 100 + [11.5, 12.0, 12.5, 13.0, 13.5, 14.0] + [14.36] * 24
    assert _screen(_bars(closes=closes_mid)) is None


def test_d1_limit_up_rejected() -> None:
    closes = _low_position_closes()
    closes[-2] = 9.2
    closes[-1] = 10.2  # 10.2 >= 9.2×1.098 → D-1 涨停
    assert _screen(_bars(closes=closes)) is None


def test_insufficient_history_rejected() -> None:
    assert _screen(_bars(n=10, changes=[0.5] * 10)) is None


def test_stale_latest_date_rejected() -> None:
    assert _screen(_bars(), latest="2026-08-03") is None


def test_volume_thresholds() -> None:
    turnovers = [100.0] * 127 + [300.0, 300.0, 300.0]
    bars = _bars(turnovers=turnovers)
    assert _screen(bars, max_vol_cv=0.5) is not None  # cv=0 通过
    assert _screen(bars, min_vol_shift=2.0) is not None  # shift=3 ≥ 2 通过
    assert _screen(bars, min_vol_shift=4.0) is None
    assert _screen(bars, max_vol_shift=2.0) is None


# ── render_candidates_txt ────────────────────────────────────────────────


def test_render_candidates_txt_one_code_per_line() -> None:
    result = {
        "candidates": [
            {"code": "600001"},
            {"code": "000002"},
            {"code": ""},  # 空代码过滤
        ]
    }
    assert render_candidates_txt(result) == "600001\n000002\n"


def test_render_candidates_txt_empty() -> None:
    assert render_candidates_txt({"candidates": []}) == ""


# ── build_premarket_prelude_candidates（loader 全 monkeypatch）────────────


@pytest.fixture(autouse=True)
def _reset_cache():
    service._candidates_cache.update({"at": None, "key": None, "value": None})
    yield
    service._candidates_cache.update({"at": None, "key": None, "value": None})


def _patch_loaders(monkeypatch: pytest.MonkeyPatch, calls: dict[str, int]) -> None:
    monkeypatch.setattr(service, "load_latest_daily_trade_date", lambda: date(2026, 7, 31))

    def _fake_daily_bars(start: date, end: date) -> list[dict[str, Any]]:
        calls["daily_bars"] += 1
        return _yang_bars()

    monkeypatch.setattr(service, "load_daily_bars_all", _fake_daily_bars)
    monkeypatch.setattr(service, "load_stock_names", lambda: {"600001.SSE": "示例股份"})
    monkeypatch.setattr(service, "load_sector_memberships_all", lambda: [])
    monkeypatch.setattr(service, "load_sector_daily_bars", lambda start, end: [])
    monkeypatch.setattr(service, "_load_sector_names", lambda: {})


def test_build_candidates_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"daily_bars": 0}
    _patch_loaders(monkeypatch, calls)
    result = service.build_premarket_prelude_candidates()
    assert result["status"] == "ok"
    assert result["trade_date"] == "2026-07-31"
    assert result["count"] == 1
    candidate = result["candidates"][0]
    assert candidate["code"] == "600001"
    assert candidate["name"] == "示例股份"
    assert candidate["prelude_pattern"] == "small_yang"


def test_build_candidates_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"daily_bars": 0}
    _patch_loaders(monkeypatch, calls)
    service.build_premarket_prelude_candidates()
    service.build_premarket_prelude_candidates()
    assert calls["daily_bars"] == 1  # 第二次走 60s 缓存


def test_build_candidates_unavailable_when_no_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_latest_daily_trade_date", lambda: None)
    result = service.build_premarket_prelude_candidates()
    assert result["status"] == "unavailable"
    assert result["candidates"] == []


# ── API 端点 ─────────────────────────────────────────────────────────────


def test_api_candidates_503_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "is_database_configured", lambda: False)
    response = api.premarket_prelude_candidates()
    assert response.status_code == 503


def test_api_candidates_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        service,
        "get_premarket_prelude_candidates",
        lambda **kwargs: {"status": "ok", "trade_date": LATEST, "candidates": []},
    )
    result = api.premarket_prelude_candidates()
    assert result["success"] is True
    assert result["data"]["trade_date"] == LATEST


def test_api_candidates_txt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        service,
        "get_premarket_prelude_candidates",
        lambda **kwargs: {
            "status": "ok",
            "trade_date": LATEST,
            "candidates": [{"code": "600001"}, {"code": "000002"}],
        },
    )
    response = api.premarket_prelude_candidates_txt()
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="prelude_candidates_2026-07-31.txt"' in (
        response.headers["content-disposition"]
    )
    assert response.body.decode() == "600001\n000002\n"


# ── 快照读写 + get 入口（EOD 预算 → API 读库）─────────────────────────────


class _FakeSession:
    """捕获 upsert 写入；scalar_one_or_none 返回预设快照 payload。"""

    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        self.snapshot = snapshot
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> _FakeSession:
        self.statements.append(statement)
        return self

    def scalar_one_or_none(self) -> dict[str, Any] | None:
        return self.snapshot


def _patch_session_scope(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(service, "session_scope", fake_scope)


def test_save_and_load_snapshot_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": "ok", "trade_date": LATEST, "count": 1, "candidates": [{"code": "600001"}]}
    session = _FakeSession()
    _patch_session_scope(monkeypatch, session)
    assert service.save_premarket_prelude_snapshot(payload) == 1
    assert session.statements  # upsert 已执行
    # load 返回最新 payload
    _patch_session_scope(monkeypatch, _FakeSession(snapshot=payload))
    loaded = service.load_premarket_prelude_snapshot()
    assert loaded is not None and loaded["trade_date"] == LATEST


def test_save_snapshot_skips_without_trade_date(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    _patch_session_scope(monkeypatch, session)
    assert service.save_premarket_prelude_snapshot({"status": "unavailable"}) == 0
    assert session.statements == []


def test_get_prefers_snapshot_over_live_build(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = {
        "status": "ok",
        "trade_date": LATEST,
        "count": 3,
        "candidates": [
            {"code": "600001", "prelude_pattern": "small_yang"},
            {"code": "600002", "prelude_pattern": "small_yin"},
            {"code": "600003", "prelude_pattern": "none"},
        ],
        "params": {"pattern": "all"},
    }
    monkeypatch.setattr(service, "load_premarket_prelude_snapshot", lambda: snapshot)

    def _no_build(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("快照命中时不应实时全市场扫描")

    monkeypatch.setattr(service, "build_premarket_prelude_candidates", _no_build)
    # has_pattern 过滤：剩 2 只
    result = service.get_premarket_prelude_candidates(pattern="has_pattern")
    assert result["count"] == 2
    assert result["params"]["pattern"] == "has_pattern"
    # small_yin 过滤：剩 1 只
    result = service.get_premarket_prelude_candidates(pattern="small_yin")
    assert result["count"] == 1
    assert result["candidates"][0]["code"] == "600002"
    # limit 截断
    result = service.get_premarket_prelude_candidates(pattern="all", limit=1)
    assert result["count"] == 1
    assert result["total"] == 3


def test_get_falls_back_to_live_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "load_premarket_prelude_snapshot", lambda: None)
    monkeypatch.setattr(
        service,
        "build_premarket_prelude_candidates",
        lambda **kwargs: {"status": "ok", "trade_date": LATEST, "count": 0, "candidates": []},
    )
    result = service.get_premarket_prelude_candidates()
    assert result["status"] == "ok" and result["trade_date"] == LATEST
