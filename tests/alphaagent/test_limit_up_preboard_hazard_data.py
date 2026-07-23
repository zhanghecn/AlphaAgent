from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime

import pandas as pd

from alphaagent.server.services import data_sync
from alphaagent.server.services.limit_up import preboard_hazard_data

from alphaagent.server.services.limit_up.preboard_hazard_data import (
    audit_static_hazard_manifest,
    build_one_minute_backfill_gaps,
    build_one_minute_coverage,
    filter_static_hazard_manifest,
    official_one_minute_close_times,
)


def test_one_minute_loader_queries_exact_pairs_in_bounded_batches(
    monkeypatch,
) -> None:
    manifest = pd.DataFrame(
        [
            {"vt_symbol": "600003.SSE", "trade_date": "2026-07-16"},
            {"vt_symbol": "600001.SSE", "trade_date": "2026-07-15"},
            {"vt_symbol": "600002.SSE", "trade_date": "2026-07-16"},
        ]
    )
    queried_batches: list[list[tuple[str, object]]] = []

    def read_sql(statement, engine, *, parse_dates):
        params = statement.compile().params
        pairs = next(
            value
            for value in params.values()
            if isinstance(value, list)
            and (not value or isinstance(value[0], tuple))
        )
        queried_batches.append(pairs)
        return pd.DataFrame()

    monkeypatch.setattr(preboard_hazard_data, "MINUTE_PAIR_QUERY_BATCH_SIZE", 2)
    monkeypatch.setattr(preboard_hazard_data, "get_engine", lambda: "engine")
    monkeypatch.setattr(preboard_hazard_data.pd, "read_sql", read_sql)

    result = preboard_hazard_data.load_one_minute_bars(manifest)

    assert result.empty
    assert [len(batch) for batch in queried_batches] == [2, 1]
    assert [pair for batch in queried_batches for pair in batch] == [
        ("600001.SSE", pd.Timestamp("2026-07-15").date()),
        ("600002.SSE", pd.Timestamp("2026-07-16").date()),
        ("600003.SSE", pd.Timestamp("2026-07-16").date()),
    ]


def test_static_hazard_manifest_uses_only_mature_prior_quality() -> None:
    frame = pd.DataFrame(
        [
            _manifest_row("600001.SSE", samples=5, combined=30, touched=False),
            _manifest_row("600002.SSE", samples=4, combined=90, touched=True),
            _manifest_row("600003.SSE", samples=8, combined=29.99, touched=True),
        ]
    )

    selected = filter_static_hazard_manifest(frame)
    changed = deepcopy(frame)
    changed["touched_limit"] = ~changed["touched_limit"]
    changed["sealed_limit"] = True
    changed["d1_close_price"] = 1.0
    selected_after_outcome_change = filter_static_hazard_manifest(changed)
    audited = audit_static_hazard_manifest(frame).set_index("vt_symbol")

    assert selected["vt_symbol"].tolist() == ["600001.SSE"]
    assert selected_after_outcome_change["vt_symbol"].tolist() == ["600001.SSE"]
    assert audited.loc["600001.SSE", "static_hazard_gate_reason"] == "qualified"
    assert (
        audited.loc["600002.SSE", "static_hazard_gate_reason"]
        == "same_stock_d1_samples_below_5"
    )
    assert (
        audited.loc["600003.SSE", "static_hazard_gate_reason"]
        == "same_stock_joint_rate_below_30"
    )


def test_one_minute_coverage_requires_all_240_official_slots() -> None:
    manifest = pd.DataFrame(
        [{"vt_symbol": "600001.SSE", "trade_date": pd.Timestamp("2026-07-16")}]
    )
    complete_rows = _minute_rows("600001.SSE", "2026-07-16")

    complete = build_one_minute_coverage(manifest, complete_rows)
    partial = build_one_minute_coverage(manifest, complete_rows.iloc[:-1])
    duplicate = build_one_minute_coverage(
        manifest,
        pd.concat([complete_rows, complete_rows.iloc[[0]]], ignore_index=True),
    )
    unexpected_rows = complete_rows.copy()
    unexpected_rows.loc[0, "bar_time"] = datetime(2026, 7, 16, 9, 30)
    unexpected = build_one_minute_coverage(manifest, unexpected_rows)

    assert len(official_one_minute_close_times()) == 240
    assert official_one_minute_close_times()[0] == "09:31"
    assert official_one_minute_close_times()[-1] == "15:00"
    assert complete.iloc[0]["coverage_status"] == "complete"
    assert complete.iloc[0]["valid_slot_count"] == 240
    assert partial.iloc[0]["coverage_status"] == "incomplete"
    assert duplicate.iloc[0]["coverage_status"] == "invalid"
    assert duplicate.iloc[0]["duplicate_count"] == 1
    assert unexpected.iloc[0]["coverage_status"] == "invalid"
    assert unexpected.iloc[0]["unexpected_time_count"] == 1


def test_backfill_gaps_are_bounded_and_exclude_complete_pairs() -> None:
    coverage = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": pd.Timestamp("2026-07-15"),
                "coverage_status": "missing",
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": pd.Timestamp("2026-07-16"),
                "coverage_status": "complete",
            },
            {
                "vt_symbol": "600002.SSE",
                "trade_date": pd.Timestamp("2026-07-16"),
                "coverage_status": "incomplete",
            },
        ]
    )

    first = build_one_minute_backfill_gaps(coverage, max_pairs=1)
    all_gaps = build_one_minute_backfill_gaps(coverage, max_pairs=10)

    assert [(row["vt_symbol"], str(row["trade_date"])) for row in first] == [
        ("600001.SSE", "2026-07-15")
    ]
    assert [row["vt_symbol"] for row in all_gaps] == [
        "600001.SSE",
        "600002.SSE",
    ]


def test_minute_upsert_uses_one_bulk_statement_after_stock_check(monkeypatch) -> None:
    statements: list[object] = []

    class Result:
        def scalar(self) -> str:
            return "600001.SSE"

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_minute_bars(
        "600001",
        "SSE",
        [
            {
                "trade_date": "2026-07-16 09:31:00",
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0,
                "volume": 100,
                "turnover": 100_000,
            },
            {
                "trade_date": "2026-07-16 09:32:00",
                "open": 10.0,
                "high": 10.2,
                "low": 10.0,
                "close": 10.1,
                "volume": 200,
                "turnover": 202_000,
            },
        ],
        "1m",
        "fixture",
    )

    assert written == 2
    assert len(statements) == 2


def _manifest_row(
    vt_symbol: str,
    *,
    samples: int,
    combined: float,
    touched: bool,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": pd.Timestamp("2026-07-16"),
        "stock_d1_sample_count": samples,
        "stock_gene_combined_win_rate": combined,
        "touched_limit": touched,
        "sealed_limit": touched,
        "d1_close_price": 12.0,
    }


def _minute_rows(vt_symbol: str, trade_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": vt_symbol,
                "trade_date": pd.Timestamp(trade_date),
                "bar_time": datetime.fromisoformat(
                    f"{trade_date}T{close_time}:00"
                ),
                "interval": "1m",
                "open_price": 10.0,
                "high_price": 10.1,
                "low_price": 9.9,
                "close_price": 10.0,
                "volume": 1_000.0,
                "turnover": 1_000_000.0,
                "source": "fixture",
            }
            for close_time in official_one_minute_close_times()
        ]
    )
