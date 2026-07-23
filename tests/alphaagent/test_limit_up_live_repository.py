from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.services.limit_up import live_repository


SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
def clear_context_cache() -> None:
    live_repository.clear_live_context_cache()
    yield
    live_repository.clear_live_context_cache()


def test_snapshot_round_trip_keeps_preboard_candidates(monkeypatch) -> None:
    stored: dict[str, object] = {}

    class Result:
        def __init__(self, row: dict[str, object] | None) -> None:
            self._row = row

        def mappings(self):
            return self

        def one(self) -> dict[str, object]:
            assert self._row is not None
            return self._row

        def one_or_none(self) -> dict[str, object] | None:
            return self._row

    class Session:
        def execute(self, statement):
            if getattr(statement, "is_insert", False):
                stored.update(
                    statement.compile(dialect=postgresql.dialect()).params
                )
                return Result(stored)
            return Result(stored or None)

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(live_repository, "session_scope", fake_session_scope)
    candidates = [
        {
            "vt_symbol": "600001.SSE",
            "decision_state": "observe",
            "touch_probability_3m": 0.72,
        }
    ]
    snapshot = {
        "trade_date": "2026-07-23",
        "captured_at": "2026-07-23T10:05:20+08:00",
        "session_stage": "morning",
        "strategy_version": "limit-up-live-v15",
        "mode": "live_snapshot",
        "source": "test",
        "source_updated_at": "2026-07-23T10:05:20+08:00",
        "market_context": {},
        "candidates": [],
        "preboard_candidates": candidates,
        "recommendations": {},
        "data_quality": {"status": "ready", "is_stale": False},
    }

    saved = live_repository.save_snapshot(snapshot)
    loaded = live_repository.load_latest_snapshot(
        date(2026, 7, 23),
        strategy_version="limit-up-live-v15",
    )

    assert "preboard_candidates" in live_repository.schema.limit_up_signal_snapshots.c
    assert saved["preboard_candidates"] == candidates
    assert loaded is not None
    assert loaded["preboard_candidates"] == candidates


def test_lane_validation_cache_reads_live_and_final_plan_modes(monkeypatch) -> None:
    captured_after = datetime(2026, 7, 20, 21, 30, tzinfo=SHANGHAI)
    persisted = {
        "first_board": {
            "passed": True,
            "summary": {"trade_count": 99},
        }
    }
    statements = []

    class Result:
        def scalar_one_or_none(self):
            return persisted

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(live_repository, "session_scope", fake_session_scope)

    result = live_repository.load_latest_lane_validations(
        strategy_version="limit-up-live-v15",
        captured_after=captured_after,
    )

    assert result == persisted
    assert len(statements) == 1
    params = statements[0].compile().params
    bound_strings = {
        item
        for value in params.values()
        for item in (value if isinstance(value, (list, tuple, set)) else (value,))
        if isinstance(item, str)
    }
    snapshot_modes = {
        "live_snapshot",
        "next_session_preliminary",
        "next_session_final",
    }
    assert bound_strings & snapshot_modes == {
        "live_snapshot",
        "next_session_final",
    }
    assert captured_after in params.values()


def test_live_context_caches_prior_fields_but_refreshes_intraday_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_calls: list[tuple[list[str], date, bool]] = []
    intraday_calls: list[tuple[list[str], date]] = []

    def fake_prior(
        symbols: list[str],
        trade_date: date,
        *,
        include_global_context: bool,
    ) -> dict[str, object]:
        prior_calls.append((list(symbols), trade_date, include_global_context))
        return {
            "by_symbol": {
                symbol: {"prior_marker": f"prior:{symbol}"}
                for symbol in symbols
            },
            "previous_trade_date": "2026-07-17",
            "score_by_sector": {},
            "sentiment_points": [],
            "calendar_dates": [],
            "concept_groups": [],
        }

    def fake_intraday(
        symbols: list[str],
        trade_date: date,
        prior: dict[str, object],
    ) -> dict[str, object]:
        intraday_calls.append((list(symbols), trade_date))
        return {
            "by_symbol": {
                symbol: {"intraday_marker": len(intraday_calls)}
                for symbol in symbols
            },
            "sentiment": {"phase": "repair"},
            "timing": {"signal_state": "NONE"},
        }

    monkeypatch.setattr(
        live_repository,
        "_load_prior_symbol_context",
        fake_prior,
    )
    monkeypatch.setattr(
        live_repository,
        "_load_intraday_context",
        fake_intraday,
    )

    first = live_repository.load_live_context(
        ["600001.SSE", "600002.SSE"],
        date(2026, 7, 20),
    )
    second = live_repository.load_live_context(
        ["600002.SSE", "600003.SSE"],
        date(2026, 7, 20),
    )
    third = live_repository.load_live_context(
        ["600001.SSE"],
        date(2026, 7, 21),
    )

    assert prior_calls == [
        (["600001.SSE", "600002.SSE"], date(2026, 7, 20), True),
        (["600003.SSE"], date(2026, 7, 20), False),
        (["600001.SSE"], date(2026, 7, 21), True),
    ]
    assert intraday_calls == [
        (["600001.SSE", "600002.SSE"], date(2026, 7, 20)),
        (["600002.SSE", "600003.SSE"], date(2026, 7, 20)),
        (["600001.SSE"], date(2026, 7, 21)),
    ]
    assert first["by_symbol"]["600001.SSE"]["intraday_marker"] == 1
    assert second["by_symbol"]["600002.SSE"]["intraday_marker"] == 2
    assert third["by_symbol"]["600001.SSE"]["intraday_marker"] == 3
