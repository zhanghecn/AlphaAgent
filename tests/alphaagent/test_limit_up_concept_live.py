from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import concept_live_service as service
from alphaagent.server.services.limit_up import concept_snapshot_repository as repository


SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def clear_concept_runtime_between_tests(monkeypatch):
    service.clear_runtime_snapshot()
    monkeypatch.setattr(
        repository,
        "required_prior_trade_date",
        lambda trade_date: trade_date - timedelta(days=1),
        raising=False,
    )
    yield
    service.clear_runtime_snapshot()


def test_concept_strength_snapshot_table_is_defined() -> None:
    table = schema.limit_up_concept_strength_snapshots

    assert table.name == "limit_up_concept_strength_snapshots"
    assert {
        "trade_date",
        "captured_at",
        "captured_minute",
        "membership_snapshot_date",
        "concept_id",
        "metrics",
    }.issubset({column.name for column in table.columns})


def test_build_snapshot_rows_freezes_minute_and_membership_version() -> None:
    rows = repository.build_strength_snapshot_rows(
        [
            {
                "concept_id": "BK0877",
                "concept_name": "PCB",
                "strength_score": 92.0,
                "strength_rank": 1,
                "strength_percentile": 0.01,
                "concept_state": "launch",
                "coverage_ratio": 0.98,
                "radar_symbols": ["600183.SSE"],
            }
        ],
        captured_at=datetime(2026, 7, 14, 13, 3, 27, tzinfo=SHANGHAI),
        membership_snapshot_date=date(2026, 7, 13),
        source="tencent.full_a_share_pages",
        source_updated_at=datetime(2026, 7, 14, 13, 3, 25, tzinfo=SHANGHAI),
    )

    assert rows[0]["trade_date"] == date(2026, 7, 14)
    assert rows[0]["membership_snapshot_date"] == date(2026, 7, 13)
    assert rows[0]["captured_minute"].second == 0
    assert rows[0]["metrics"]["radar_symbols"] == ["600183.SSE"]


def test_latest_prior_membership_date_never_uses_signal_day() -> None:
    assert repository.latest_prior_membership_date(
        [date(2026, 7, 13), date(2026, 7, 14)],
        date(2026, 7, 14),
    ) == date(2026, 7, 13)


def test_required_prior_membership_date_uses_the_previous_trading_day() -> None:
    assert repository.required_prior_membership_date(
        [date(2026, 7, 16), date(2026, 7, 17)],
        date(2026, 7, 20),
    ) == date(2026, 7, 17)


def test_refresh_rejects_a_membership_snapshot_older_than_d1(monkeypatch) -> None:
    previous = _runtime_snapshot("2026-07-14T13:03:00+08:00")
    service._replace_runtime_snapshot(previous)
    monkeypatch.setattr(
        repository,
        "required_prior_trade_date",
        lambda _date: date(2026, 7, 13),
    )
    monkeypatch.setattr(
        repository,
        "load_frozen_membership_rows",
        lambda _date: (date(2026, 7, 12), _pcb_memberships()),
    )
    persisted: list[object] = []
    monkeypatch.setattr(
        repository,
        "save_strength_snapshots",
        lambda rows: persisted.extend(rows),
    )

    result = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 25, tzinfo=SHANGHAI),
        adapter=FakeAdapter(_full_market_payload("2026-07-14T13:03:20+08:00")),
    )

    assert result["captured_at"] == previous["captured_at"]
    assert result["data_quality"]["trigger_allowed"] is False
    assert "D-1" in result["data_quality"]["source_errors"][0]
    assert persisted == []


def test_select_persisted_concepts_keeps_top30_radar_and_warming() -> None:
    concepts = [
        {
            "concept_id": f"BK{index:04d}",
            "strength_rank": index,
            "concept_state": "observe",
            "radar_symbols": [],
        }
        for index in range(1, 36)
    ]
    concepts[34]["radar_symbols"] = ["600000.SSE"]
    concepts[33]["concept_state"] = "warming"

    selected = repository.select_persisted_concepts(concepts)

    assert len(selected) == 32
    assert "BK0035" in {row["concept_id"] for row in selected}
    assert "BK0034" in {row["concept_id"] for row in selected}


def test_refresh_builds_atomic_runtime_snapshot(monkeypatch) -> None:
    service.clear_runtime_snapshot()
    monkeypatch.setattr(
        repository,
        "load_frozen_membership_rows",
        lambda _date: (date(2026, 7, 13), _pcb_memberships()),
    )
    monkeypatch.setattr(repository, "save_strength_snapshots", lambda rows: len(rows))
    adapter = FakeAdapter(_full_market_payload("2026-07-14T13:03:20+08:00"))

    snapshot = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 25, tzinfo=SHANGHAI),
        adapter=adapter,
    )

    assert snapshot["data_quality"]["status"] == "ready"
    assert snapshot["membership_snapshot_date"] == "2026-07-13"
    assert snapshot["concepts_by_id"]["BK0877"]["concept_name"] == "PCB"
    assert len(snapshot["quotes"]) == len(_full_market_payload()["items"])


def test_runtime_snapshot_over_45_seconds_is_observation_only() -> None:
    service.clear_runtime_snapshot()
    service._replace_runtime_snapshot(_runtime_snapshot("2026-07-14T13:03:00+08:00"))

    result = service.get_latest_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 46, tzinfo=SHANGHAI)
    )

    assert result is not None
    assert result["data_quality"]["is_stale"] is True
    assert result["data_quality"]["trigger_allowed"] is False


def test_failed_refresh_keeps_previous_snapshot_and_records_error() -> None:
    service.clear_runtime_snapshot()
    previous = _runtime_snapshot("2026-07-14T13:03:00+08:00")
    service._replace_runtime_snapshot(previous)

    result = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 20, tzinfo=SHANGHAI),
        adapter=FakeAdapter(error=TimeoutError("full market timeout")),
    )

    assert result["captured_at"] == previous["captured_at"]
    assert "full market timeout" in result["data_quality"]["source_errors"][0]


def test_invalid_source_date_keeps_previous_snapshot_without_persisting(monkeypatch) -> None:
    previous = _runtime_snapshot("2026-07-14T13:03:00+08:00")
    service._replace_runtime_snapshot(previous)
    monkeypatch.setattr(
        repository,
        "load_frozen_membership_rows",
        lambda _date: (date(2026, 7, 13), _pcb_memberships()),
    )
    persisted: list[object] = []
    monkeypatch.setattr(
        repository,
        "save_strength_snapshots",
        lambda rows: persisted.extend(rows),
    )
    payload = {
        **_full_market_payload("2026-07-15T09:30:00+08:00"),
        "trade_date": "2026-07-15",
    }

    result = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 20, tzinfo=SHANGHAI),
        adapter=FakeAdapter(payload),
    )

    assert result["captured_at"] == previous["captured_at"]
    assert result["data_quality"]["trigger_allowed"] is False
    assert "来源交易日" in result["data_quality"]["source_errors"][0]
    assert persisted == []


def test_low_market_coverage_keeps_previous_snapshot_without_persisting(monkeypatch) -> None:
    previous = _runtime_snapshot("2026-07-14T13:03:00+08:00")
    service._replace_runtime_snapshot(previous)
    monkeypatch.setattr(
        repository,
        "load_frozen_membership_rows",
        lambda _date: (date(2026, 7, 13), _pcb_memberships()),
    )
    persisted: list[object] = []
    monkeypatch.setattr(
        repository,
        "save_strength_snapshots",
        lambda rows: persisted.extend(rows),
    )
    payload = _full_market_payload(items=[_quote("600183.SSE", "生益科技", 8.2)])

    result = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 20, tzinfo=SHANGHAI),
        adapter=FakeAdapter(payload),
    )

    assert result["captured_at"] == previous["captured_at"]
    assert result["data_quality"]["trigger_allowed"] is False
    assert "覆盖率仅 50.0%" in result["data_quality"]["source_errors"][0]
    assert persisted == []


def test_runtime_snapshot_builds_authoritative_main_board_three_percent_radar(monkeypatch) -> None:
    service.clear_runtime_snapshot()
    memberships = [
        {
            "vt_symbol": symbol,
            "stock_name": name,
            "sector_id": "BK0877",
            "sector_name": "PCB",
            "sector_type": "theme",
        }
        for symbol, name in (
            ("600001.SSE", "上证主板"),
            ("000001.SZSE", "深证主板"),
            ("300001.SZSE", "创业板"),
            ("600002.SSE", "三成雷达"),
            ("600003.SSE", "低于雷达"),
        )
    ]
    monkeypatch.setattr(
        repository,
        "load_frozen_membership_rows",
        lambda _date: (date(2026, 7, 13), memberships),
    )
    quotes = [
        _quote("600001.SSE", "上证主板", 5.0),
        _quote("000001.SZSE", "深证主板", 7.0),
        _quote("300001.SZSE", "创业板", 19.0),
        _quote("600002.SSE", "三成雷达", 3.0),
        _quote("600003.SSE", "低于雷达", 2.99),
    ]

    snapshot = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 25, tzinfo=SHANGHAI),
        adapter=FakeAdapter(_full_market_payload(items=quotes)),
        persist=False,
    )

    assert {row["vt_symbol"] for row in snapshot["radar_quotes"]} == {
        "600001.SSE",
        "000001.SZSE",
        "600002.SSE",
    }


def test_refresh_outside_market_hours_does_not_fetch_or_persist() -> None:
    result = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 18, 30, tzinfo=SHANGHAI),
        adapter=FakeAdapter(error=AssertionError("adapter must not be called")),
    )

    assert result["data_quality"]["status"] == "unavailable"
    assert result["data_quality"]["trigger_allowed"] is False
    assert "盘中概念扫描时段" in result["data_quality"]["source_errors"][0]


class FakeAdapter:
    def __init__(self, payload=None, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def all_stock_quotes(self):
        if self.error is not None:
            raise self.error
        return self.payload


def _pcb_memberships() -> list[dict[str, object]]:
    return [
        {
            "vt_symbol": "600183.SSE",
            "stock_name": "生益科技",
            "sector_id": "BK0877",
            "sector_name": "PCB",
            "sector_type": "theme",
        },
        {
            "vt_symbol": "002463.SZSE",
            "stock_name": "沪电股份",
            "sector_id": "BK0877",
            "sector_name": "PCB",
            "sector_type": "theme",
        },
    ]


def _full_market_payload(updated_at="2026-07-14T13:03:20+08:00", *, items=None):
    rows = items or [
        _quote("600183.SSE", "生益科技", 8.2),
        _quote("002463.SZSE", "沪电股份", 9.5),
    ]
    return {
        "trade_date": "2026-07-14",
        "updated_at": updated_at,
        "source": "tencent.full_a_share_pages",
        "items": rows,
        "total": len(rows),
    }


def _quote(symbol: str, name: str, change_pct: float) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": name,
        "change_pct": change_pct,
        "turnover": 1_000_000_000,
        "previous_close": 10.0,
        "last_price": 10.0 * (1 + change_pct / 100),
    }


def _runtime_snapshot(captured_at: str) -> dict[str, object]:
    return {
        "captured_at": captured_at,
        "trade_date": "2026-07-14",
        "membership_snapshot_date": "2026-07-13",
        "source": "test",
        "quotes": [],
        "radar_quotes": [],
        "membership": {},
        "concepts": [],
        "concepts_by_id": {},
        "concept_count": 0,
        "data_quality": {
            "status": "ready",
            "is_stale": False,
            "trigger_allowed": True,
            "age_seconds": 0,
            "quote_coverage_ratio": 1.0,
            "source_trade_date_valid": True,
            "source_errors": [],
        },
    }
