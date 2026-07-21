from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from alphaagent.server.services.limit_up import preboard_momentum_data
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    attach_preboard_prior_evidence,
    build_backfill_gaps,
    build_five_minute_coverage,
    build_preboard_manifest,
    official_five_minute_close_times,
)


def test_manifest_query_filters_evaluation_rows_before_history_windows(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def read_sql(statement, engine, *, params, parse_dates):
        captured.update(
            statement=str(statement),
            engine=engine,
            params=params,
            parse_dates=parse_dates,
        )
        return pd.DataFrame()

    monkeypatch.setattr(preboard_momentum_data, "get_engine", lambda: "engine")
    monkeypatch.setattr(preboard_momentum_data.pd, "read_sql", read_sql)

    result = preboard_momentum_data._load_manifest_candidates(
        [date(2026, 7, 16)]
    )

    sql = " ".join(str(captured["statement"]).split())
    assert result.empty
    assert "WITH evaluation_rows AS MATERIALIZED" in sql
    assert sql.index("b.trade_date IN") < sql.index("JOIN LATERAL")
    assert "LIMIT :history_context_bars" in sql
    assert "ROWS BETWEEN 126 PRECEDING" not in sql
    assert "ROW_NUMBER() OVER symbol_history" not in sql
    assert "candidate_rows.high_price >=" in sql
    assert "candidate_rows.close_price >=" in sql
    assert "ROUND(candidate_rows.previous_close::numeric" in sql
    assert captured["params"] == {
        "evaluation_dates": [date(2026, 7, 16)],
        "minimum_prior_bars": 120,
        "history_window_bars": 126,
        "history_context_bars": 127,
        "capture_ratio": 1.03,
    }


def test_manifest_loader_checks_research_runtime_before_database(
    monkeypatch,
) -> None:
    def reject_runtime() -> None:
        raise RuntimeError("research runtime required")

    monkeypatch.setattr(
        preboard_momentum_data,
        "require_research_runtime",
        reject_runtime,
    )
    monkeypatch.setattr(
        preboard_momentum_data,
        "_load_reliable_dates",
        lambda _count: pytest.fail("database access must not start"),
    )

    with pytest.raises(RuntimeError, match="research runtime required"):
        preboard_momentum_data.load_preboard_manifest(session_count=95)


def test_manifest_keeps_only_mature_first_board_three_percent_crossers() -> None:
    rows = pd.concat(
        [
            _daily_rows("600001.SSE", "Alpha", high_on_signal=10.40),
            _daily_rows("600002.SSE", "Below", high_on_signal=10.299),
            _daily_rows(
                "600003.SSE",
                "Prior limit",
                high_on_signal=11.50,
                prior_close=11.0,
            ),
            _daily_rows("600004.SSE", "*ST Risk", high_on_signal=10.40),
            _daily_rows(
                "600005.SSE",
                "Short history",
                high_on_signal=10.40,
                row_count=30,
            ),
            _daily_rows(
                "600006.SSE",
                "No D1",
                high_on_signal=10.40,
                signal_on_last_row=True,
            ),
        ],
        ignore_index=True,
    )

    manifest = build_preboard_manifest(rows)

    assert manifest["vt_symbol"].tolist() == ["600003.SSE", "600001.SSE"]
    prior_limit_rows = manifest.loc[manifest["vt_symbol"].eq("600003.SSE")]
    assert len(prior_limit_rows) == 1
    assert prior_limit_rows.iloc[0]["close_price"] == 11.0
    row = manifest.loc[manifest["vt_symbol"].eq("600001.SSE")].iloc[0]
    assert row["manifest_reason"] == "daily_high_crossed_3pct"
    assert bool(row["prior_day_limit_up"]) is False
    assert row["prior_history_count"] >= 120
    assert row["previous_close"] == 10.0
    assert row["d1_close_price"] == 10.2


def test_five_minute_coverage_requires_exact_official_slots() -> None:
    manifest = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "name": "Alpha",
                "trade_date": pd.Timestamp("2026-07-01"),
            }
        ]
    )
    complete_rows = _minute_rows("600001.SSE", "2026-07-01")

    complete = build_five_minute_coverage(manifest, complete_rows)
    duplicated = build_five_minute_coverage(
        manifest,
        pd.concat([complete_rows, complete_rows.iloc[[0]]], ignore_index=True),
    )
    shifted = complete_rows.copy()
    shifted.loc[0, "bar_time"] = pd.Timestamp("2026-07-01 09:34:00")
    invalid = build_five_minute_coverage(manifest, shifted)

    assert len(official_five_minute_close_times()) == 48
    assert complete.iloc[0]["coverage_status"] == "complete"
    assert complete.iloc[0]["valid_slot_count"] == 48
    assert duplicated.iloc[0]["coverage_status"] == "invalid"
    assert duplicated.iloc[0]["duplicate_count"] == 1
    assert invalid.iloc[0]["coverage_status"] == "invalid"
    assert invalid.iloc[0]["unexpected_time_count"] == 1


def test_manifest_gene_counts_are_shifted_before_the_signal_day() -> None:
    daily = _daily_rows("600001.SSE", "Alpha", high_on_signal=10.40)
    prior_event_index = 20
    daily.loc[prior_event_index, ["high_price", "close_price"]] = [11.0, 11.0]

    baseline = build_preboard_manifest(daily)
    sealed_signal = daily.copy()
    signal_index = len(sealed_signal) - 2
    sealed_signal.loc[signal_index, ["high_price", "close_price"]] = [11.0, 11.0]
    mutated = build_preboard_manifest(sealed_signal)

    baseline_row = baseline.iloc[-1]
    mutated_row = mutated.iloc[-1]
    assert baseline_row["prior_touch_count_126"] == 1
    assert baseline_row["prior_limit_count_126"] == 1
    assert baseline_row["prior_seal_success_rate_126"] == 1.0
    assert mutated_row["prior_touch_count_126"] == baseline_row["prior_touch_count_126"]
    assert mutated_row["prior_limit_count_126"] == baseline_row["prior_limit_count_126"]


def test_prior_d1_evidence_excludes_unmatured_and_future_results() -> None:
    manifest = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "name": "Alpha",
                "trade_date": pd.Timestamp("2026-07-01"),
                "prior_touch_count_126": 4,
                "prior_limit_count_126": 3,
                "prior_seal_success_rate_126": 0.75,
            }
        ]
    )
    history_days = [
        _history_day("2026-06-02", result_date="2026-06-03", return_pct=2.0),
        _history_day("2026-06-20", result_date="2026-06-23", return_pct=-1.0),
        _history_day("2026-06-30", result_date="2026-07-02", return_pct=8.0),
    ]

    enriched = attach_preboard_prior_evidence(manifest, history_days)

    row = enriched.iloc[0]
    assert row["stock_d1_sample_count"] == 2
    assert row["stock_d1_win_count"] == 1
    assert row["stock_d1_win_rate"] == 50.0
    assert row["stock_gene_combined_win_rate"] == 37.5


def test_backfill_gaps_group_all_dates_for_selected_symbols() -> None:
    coverage = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": "2026-07-01",
                "coverage_status": "missing",
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": "2026-07-02",
                "coverage_status": "incomplete",
            },
            {
                "vt_symbol": "600002.SSE",
                "trade_date": "2026-07-01",
                "coverage_status": "missing",
            },
            {
                "vt_symbol": "600003.SSE",
                "trade_date": "2026-07-01",
                "coverage_status": "complete",
            },
        ]
    )

    first = build_backfill_gaps(coverage, max_symbols=1, symbol_offset=0)
    second = build_backfill_gaps(coverage, max_symbols=1, symbol_offset=1)

    assert [(row["vt_symbol"], str(row["trade_date"])) for row in first] == [
        ("600001.SSE", "2026-07-01"),
        ("600001.SSE", "2026-07-02"),
    ]
    assert [row["vt_symbol"] for row in second] == ["600002.SSE"]


def _daily_rows(
    vt_symbol: str,
    name: str,
    *,
    high_on_signal: float,
    prior_close: float = 10.0,
    row_count: int = 123,
    signal_on_last_row: bool = False,
) -> pd.DataFrame:
    dates = pd.bdate_range("2025-12-01", periods=row_count)
    signal_index = row_count - 1 if signal_on_last_row else row_count - 2
    rows = []
    for index, trade_date in enumerate(dates):
        close = 10.0
        high = 10.1
        if index == signal_index - 1:
            close = prior_close
            high = max(high, prior_close)
        if index == signal_index:
            high = high_on_signal
            close = min(high_on_signal, prior_close * 1.02)
        if index == signal_index + 1:
            close = 10.2
            high = 10.3
        rows.append(
            {
                "vt_symbol": vt_symbol,
                "name": name,
                "trade_date": trade_date,
                "open_price": close,
                "close_price": close,
                "high_price": high,
                "low_price": min(close, 9.9),
                "volume": 1_000_000.0,
                "turnover": 10_000_000.0,
            }
        )
    return pd.DataFrame(rows)


def _minute_rows(vt_symbol: str, trade_date: str) -> pd.DataFrame:
    rows = []
    for close_time in official_five_minute_close_times():
        rows.append(
            {
                "vt_symbol": vt_symbol,
                "trade_date": pd.Timestamp(trade_date),
                "bar_time": datetime.fromisoformat(f"{trade_date}T{close_time}:00"),
                "interval": "5m",
                "open_price": 10.0,
                "high_price": 10.1,
                "low_price": 9.9,
                "close_price": 10.0,
                "volume": 1_000.0,
                "turnover": 10_000.0,
                "source": "fixture",
            }
        )
    return pd.DataFrame(rows)


def _history_day(
    trade_date: str,
    *,
    result_date: str,
    return_pct: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "lane_portfolio": {
            "candidate_pool": {
                "first_board": [
                    {
                        "vt_symbol": "600001.SSE",
                        "lane": "first_board",
                        "result_date": result_date,
                        "outcome": {
                            "touched": True,
                            "sealed": True,
                            "next_close_return_pct": return_pct,
                        },
                    }
                ]
            }
        },
    }
