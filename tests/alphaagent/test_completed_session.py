from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
from alphaagent.server.services import data_sync

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _FakeResult:
    def first(self):
        return (date(2026, 7, 15),)

    def one(self):
        return (800, date(2023, 3, 28), date(2026, 7, 15))


class _FakeSession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult()


def test_completed_daily_bar_cutoff_excludes_current_session_before_1505() -> None:
    cutoff = completed_daily_bar_cutoff(
        datetime(2026, 7, 16, 12, 46, tzinfo=SHANGHAI)
    )

    assert cutoff == date(2026, 7, 15)


def test_completed_daily_bar_cutoff_accepts_current_session_from_1505() -> None:
    cutoff = completed_daily_bar_cutoff(
        datetime(2026, 7, 16, 15, 5, tzinfo=SHANGHAI)
    )

    assert cutoff == date(2026, 7, 16)


def test_completed_daily_bar_cutoff_normalizes_to_shanghai_time() -> None:
    cutoff = completed_daily_bar_cutoff(
        datetime(2026, 7, 16, 7, 4, 59, tzinfo=timezone.utc)
    )

    assert cutoff == date(2026, 7, 15)


def test_completed_daily_bar_cutoff_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        completed_daily_bar_cutoff(datetime(2026, 7, 16, 15, 5))


def test_latest_complete_daily_query_uses_completed_session_cutoff(
    monkeypatch,
) -> None:
    session = _FakeSession()
    cutoff = date(2026, 7, 15)
    monkeypatch.setattr(
        data_sync,
        "completed_daily_bar_cutoff",
        lambda _at: cutoff,
        raising=False,
    )

    assert data_sync._latest_complete_daily_date(session) == cutoff
    assert cutoff in session.statements[0].compile().params.values()


def test_reliable_daily_history_query_uses_completed_session_cutoff(
    monkeypatch,
) -> None:
    session = _FakeSession()
    cutoff = date(2026, 7, 15)
    monkeypatch.setattr(
        data_sync,
        "completed_daily_bar_cutoff",
        lambda _at: cutoff,
        raising=False,
    )

    coverage = data_sync._reliable_stock_daily_history_coverage(session)

    assert coverage["trade_days"] == 800
    assert cutoff in session.statements[0].compile().params.values()
