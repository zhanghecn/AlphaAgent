from datetime import date

import pytest

from alphaagent.server.services.limit_up import live_repository


@pytest.fixture(autouse=True)
def clear_context_cache() -> None:
    live_repository.clear_live_context_cache()
    yield
    live_repository.clear_live_context_cache()


def test_live_context_caches_prior_fields_but_refreshes_intraday_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_calls: list[tuple[list[str], date]] = []
    intraday_calls: list[tuple[list[str], date]] = []

    def fake_prior(symbols: list[str], trade_date: date) -> dict[str, object]:
        prior_calls.append((list(symbols), trade_date))
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
        (["600001.SSE", "600002.SSE"], date(2026, 7, 20)),
        (["600003.SSE"], date(2026, 7, 20)),
        (["600001.SSE"], date(2026, 7, 21)),
    ]
    assert intraday_calls == [
        (["600001.SSE", "600002.SSE"], date(2026, 7, 20)),
        (["600002.SSE", "600003.SSE"], date(2026, 7, 20)),
        (["600001.SSE"], date(2026, 7, 21)),
    ]
    assert first["by_symbol"]["600001.SSE"]["intraday_marker"] == 1
    assert second["by_symbol"]["600002.SSE"]["intraday_marker"] == 2
    assert third["by_symbol"]["600001.SSE"]["intraday_marker"] == 3
