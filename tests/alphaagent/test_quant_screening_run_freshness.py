from __future__ import annotations

from datetime import date

from alphaagent.server.services.quant import screening, screening_persistence
from alphaagent.server.services.quant.factors import SignalScore


def test_screen_run_daily_count_requires_current_latest_count():
    assert screening._screen_run_daily_count_matches({"params": {"daily_symbol_count": 5524}}, 5524)
    assert not screening._screen_run_daily_count_matches({"params": {"daily_symbol_count": 1446}}, 5524)
    assert not screening._screen_run_daily_count_matches({"params": {}}, 5524)


def test_persist_screen_run_records_daily_symbol_count():
    inserted_run: dict[str, object] = {}

    class FakeReturning:
        def scalar_one(self):
            return 7

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        def execute(self, statement, params=None):
            text = str(statement)
            if text.startswith("INSERT INTO quant_signal_runs"):
                inserted_run.update(dict(statement.compile().params))
                return FakeReturning()
            return FakeScalar()

    score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 7, 7),
        total_score=72,
        entry_signal=True,
        evidence={"status": "ready"},
    )

    run_id = screening_persistence.persist_screen_run(
        FakeSession(),
        date(2026, 7, 7),
        [score],
        [score],
        "mainline_leader_pullback",
        included_boards=("main",),
        daily_symbol_count=5524,
    )

    assert run_id == 7
    assert inserted_run["params"]["daily_symbol_count"] == 5524
