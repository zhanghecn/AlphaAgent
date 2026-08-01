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


def test_snapshot_round_trip_keeps_formal_candidates(monkeypatch) -> None:
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
            "action": "buy_now",
        }
    ]
    snapshot = {
        "trade_date": "2026-07-23",
        "captured_at": "2026-07-23T10:05:20+08:00",
        "session_stage": "morning",
        "strategy_version": "obsolete-version",
        "mode": "live_snapshot",
        "source": "test",
        "source_updated_at": "2026-07-23T10:05:20+08:00",
        "market_context": {},
        "candidates": candidates,
        "recommendations": {},
        "data_quality": {"status": "ready", "is_stale": False},
    }

    saved = live_repository.save_snapshot(snapshot)
    loaded = live_repository.load_latest_snapshot(
        date(2026, 7, 23),
        strategy_version="obsolete-version",
    )

    assert saved["candidates"] == candidates
    assert loaded is not None
    assert loaded["candidates"] == candidates


def test_publication_audit_reads_only_public_live_minutes(monkeypatch) -> None:
    captured = datetime(2026, 7, 23, 10, 5, tzinfo=SHANGHAI)
    persisted = [
        {
            "captured_minute": captured,
            "captured_at": captured.replace(second=15),
            "created_at": captured.replace(second=20),
        }
    ]
    statements = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return persisted

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(live_repository, "session_scope", fake_session_scope)

    rows = live_repository.load_publication_audit_rows(date(2026, 7, 23))

    assert rows == persisted
    params = statements[0].compile().params
    assert date(2026, 7, 23) in params.values()
    assert "limit-up-core-abc-v2" in params.values()
    assert "live_snapshot" in params.values()


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
        strategy_version="obsolete-version",
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


def test_industry_turnover_ratio_uses_d1_against_five_prior_trade_days() -> None:
    rows = [
        {
            "sector_id": "industry-a",
            "trade_date": trade_date,
            "industry_turnover": turnover,
        }
        for trade_date, turnover in (
            (date(2026, 7, 1), 100.0),
            (date(2026, 7, 2), 110.0),
            (date(2026, 7, 3), 90.0),
            (date(2026, 7, 6), 100.0),
            (date(2026, 7, 7), 100.0),
            (date(2026, 7, 8), 120.0),
        )
    ]
    rows.extend(
        [
            {
                "sector_id": "industry-incomplete",
                "trade_date": date(2026, 7, 7),
                "industry_turnover": 100.0,
            },
            {
                "sector_id": "industry-incomplete",
                "trade_date": date(2026, 7, 8),
                "industry_turnover": 120.0,
            },
        ]
    )

    assert live_repository._industry_turnover_ratios(
        rows,
        date(2026, 7, 8),
    ) == {"industry-a": 1.2}


# ── Phase 2：v4 白名单长窗因子 + 板块 20 日动量 ────────────────────────


def test_prior_price_context_includes_long_window_features() -> None:
    from alphaagent.server.services.limit_up import live_repository

    rows = []
    closes = [10.0] * 125 + [13.0, 11.0]  # 窗口内高点 13 → 现值 11
    for index, close in enumerate(closes):
        rows.append(
            {
                "trade_date": f"2026-01-{(index % 28) + 1:02d}",
                "close_price": close,
                "high_price": close,
                "low_price": close,
                "open_price": close,
                "change_pct": 0.0,
                "turnover": 1.0e8,
                "turnover_rate": 5.0,
            }
        )
    context = live_repository._prior_price_context(rows)
    assert context["drawdown_from_126d_high_pct"] is not None
    assert context["position_126d"] is not None
    assert context["volume_ratio_5_60"] is not None
    # 空数据默认 None
    empty = live_repository._prior_price_context([])
    assert empty["drawdown_from_126d_high_pct"] is None
    assert empty["position_126d"] is None
    assert empty["volume_ratio_5_60"] is None


def test_concept_max_r20_picks_max_concept_only() -> None:
    from alphaagent.server.services.limit_up import live_repository

    memberships = [
        {"sector_id": "BK1", "sector_type": "concept"},
        {"sector_id": "BK2", "sector_type": "concept"},
        {"sector_id": "BK3", "sector_type": "industry"},  # 行业不算
    ]
    scores = {
        "BK1": {"return_pct": 5.0},
        "BK2": {"return_pct": 12.5},
        "BK3": {"return_pct": 99.0},
    }
    assert live_repository._concept_max_r20(memberships, scores) == 12.5
    assert live_repository._concept_max_r20([], scores) is None
    assert live_repository._concept_max_r20(memberships, {}) is None
