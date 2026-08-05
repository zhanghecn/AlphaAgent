from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import cli
from alphaagent.server.services.low_suction import daily_factor_comprehensive_study
from alphaagent.server.services.low_suction import adjusted_daily_bars
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction import daily_factor_repository as repository


@contextmanager
def _fake_session_scope():
    yield object()


def test_raw_inputs_do_not_depend_on_qfq_scope_or_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = (date(2026, 1, 5), date(2026, 1, 6))
    raw_bars = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": date(2025, 12, 31),
                "open_price": 10.0,
                "close_price": 10.1,
                "high_price": 10.2,
                "low_price": 9.9,
                "volume": 1_000.0,
                "turnover": 10_000.0,
                "source": "nightly-akshare-raw",
                "updated_at": datetime(2026, 1, 6, 18, 0),
            }
        ]
    )
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        repository,
        "_reliable_market_calendar",
        lambda session, *, start_date, end_date: calendar,
    )
    monkeypatch.setattr(
        repository,
        "_ensure_daily_factor_schema",
        lambda engine: pytest.fail("raw research must not create qfq tables"),
    )
    monkeypatch.setattr(
        repository,
        "_collect_qfq_scope_audit",
        lambda session, calendar: pytest.fail("raw research must not audit qfq scope"),
    )
    monkeypatch.setattr(repository, "_load_raw_daily_bars", lambda engine, calendar: raw_bars)

    inputs = repository.load_daily_factor_inputs(
        price_basis=repository.PRICE_BASIS_RAW_UNADJUSTED,
    )

    assert inputs.evidence_level == "exploratory_raw_unadjusted"
    assert inputs.blockers == ()
    assert inputs.coverage["price_basis"] == "raw_unadjusted"
    assert "adjusted_prices" not in inputs.coverage


def test_raw_inputs_can_read_only_declared_case_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = (date(2026, 1, 5), date(2026, 1, 6))
    raw_bars = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": date(2025, 12, 31),
                "open_price": 10.0,
                "close_price": 10.1,
                "high_price": 10.2,
                "low_price": 9.9,
                "volume": 1_000.0,
                "turnover": 10_000.0,
                "source": "nightly-akshare-raw",
                "updated_at": datetime(2026, 1, 6, 18, 0),
            }
        ]
    )
    calls: list[tuple[str, ...] | None] = []
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", _fake_session_scope)
    monkeypatch.setattr(
        repository,
        "_reliable_market_calendar",
        lambda session, *, start_date, end_date: calendar,
    )

    def load_raw(engine, values, *, vt_symbols=None):
        calls.append(vt_symbols)
        return raw_bars

    monkeypatch.setattr(repository, "_load_raw_daily_bars", load_raw)

    inputs = repository.load_daily_factor_inputs(
        price_basis=repository.PRICE_BASIS_RAW_UNADJUSTED,
        vt_symbols=("600000.SSE", "000001.SZSE", "600000.SSE"),
    )

    assert calls == [("000001.SZSE", "600000.SSE")]
    assert inputs.coverage["raw_unadjusted_prices"]["vt_symbols_filter"] == [
        "000001.SZSE",
        "600000.SSE",
    ]


def test_raw_input_fingerprint_changes_when_a_price_changes() -> None:
    calendar = (date(2026, 1, 5),)
    bars = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": date(2026, 1, 5),
                "open_price": 10.0,
                "close_price": 10.1,
                "high_price": 10.2,
                "low_price": 9.9,
                "volume": 1_000.0,
                "turnover": 10_000.0,
                "source": "nightly-akshare-raw",
                "updated_at": datetime(2026, 1, 5, 18, 0),
            }
        ]
    )

    original = repository._raw_inputs_fingerprint(calendar, bars)
    changed = bars.copy()
    changed.loc[0, "close_price"] = 10.11

    assert repository._raw_inputs_fingerprint(calendar, changed) != original


def test_qfq_reader_requires_a_successful_canonical_sync_run() -> None:
    statement = select(schema.low_suction_adjusted_daily_bars.c.vt_symbol).select_from(
        repository._canonical_qfq_sync_join(schema.low_suction_adjusted_daily_bars)
    )
    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "sync_job_runs" in compiled
    assert "sync_run_id" in compiled
    assert "sync_low_suction_adjusted_daily_bars" in compiled
    assert "succeeded" in compiled


def test_research_cli_exposes_only_current_daily_factor_commands() -> None:
    parser = build_parser()
    command_action = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )

    assert set(command_action.choices) == {
        "daily-factor-audit",
        "daily-factor-study",
        "daily-factor-comprehensive-study",
        "daily-factor-case-audit",
        "daily-factor-extended-discovery",
        "low-suction-daily-backtest",
    }


def test_research_cli_defaults_current_studies_to_nightly_raw_prices() -> None:
    parser = build_parser()

    for command in (
        "daily-factor-study",
        "daily-factor-comprehensive-study",
        "daily-factor-extended-discovery",
    ):
        assert parser.parse_args([command]).price_basis == "raw_unadjusted"


def test_comprehensive_cli_reads_declared_raw_snapshot_without_qfq_fetch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    inputs = repository.DailyFactorInputs(
        market_calendar=(date(2026, 1, 5),),
        bars=pd.DataFrame(),
        security_status=pd.DataFrame(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="snapshot-sha",
    )

    def load_inputs(**kwargs: object) -> repository.DailyFactorInputs:
        calls.append(dict(kwargs))
        return inputs

    monkeypatch.setattr(repository, "load_daily_factor_inputs", load_inputs)
    monkeypatch.setattr(
        adjusted_daily_bars,
        "fetch_qfq_daily_bars",
        lambda *args, **kwargs: pytest.fail("research CLI must not fetch qfq bars"),
    )
    monkeypatch.setattr(
        daily_factor_comprehensive_study,
        "run_comprehensive_daily_factor_study",
        lambda **kwargs: {"status": "exploratory_complete"},
    )
    monkeypatch.setattr(
        daily_factor_comprehensive_study,
        "render_comprehensive_daily_factor_markdown",
        lambda report: "comprehensive-report\n",
    )

    assert cli.main(
        [
            "daily-factor-comprehensive-study",
            "--start",
            "2026-01-05",
            "--end",
            "2026-01-05",
            "--price-basis",
            "raw_unadjusted",
            "--format",
            "markdown",
        ]
    ) == 0

    assert calls == [
        {
            "start_date": date(2026, 1, 5),
            "end_date": date(2026, 1, 5),
            "price_basis": "raw_unadjusted",
        }
    ]
    assert capsys.readouterr().out == "comprehensive-report\n"
