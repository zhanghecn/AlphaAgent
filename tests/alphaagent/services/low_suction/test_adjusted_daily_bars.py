from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction.adjusted_daily_bars import (
    AdjustedDailyBarError,
    build_qfq_daily_scope,
    fetch_qfq_daily_bars,
    next_market_session_close_label,
    normalize_qfq_rows,
)


def _qfq_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "日期": "2026-07-15",
                "开盘": 9.82,
                "收盘": 10.01,
                "最高": 10.12,
                "最低": 9.71,
                "成交量": 123_456,
                "成交额": 1_234_567.0,
            },
            {
                "日期": "2026-07-16",
                "开盘": 10.02,
                "收盘": 10.23,
                "最高": 10.36,
                "最低": 9.98,
                "成交量": 234_567,
                "成交额": 2_345_678.0,
            },
        ]
    )


def test_normalize_qfq_rows_keeps_a_stable_independent_snapshot() -> None:
    first = normalize_qfq_rows(_qfq_frame(), "001258.SZSE")
    second = normalize_qfq_rows(_qfq_frame(), "001258.SZSE")

    assert [row.trade_date for row in first] == [date(2026, 7, 15), date(2026, 7, 16)]
    assert [row.close_price for row in first] == [10.01, 10.23]
    assert all(row.adjustment == "qfq" for row in first)
    assert all(row.source == "akshare.stock_zh_a_hist_tx:qfq" for row in first)
    assert first == second
    assert first[0].source_fingerprint != first[1].source_fingerprint
    assert first[0].raw["日期"] == "2026-07-15"


def test_fetch_qfq_daily_bars_always_requests_front_adjustment() -> None:
    calls: list[dict[str, object]] = []

    def fetcher(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        return _qfq_frame()

    rows = fetch_qfq_daily_bars(
        "001258.SZSE",
        start_date=date(2026, 7, 15),
        end_date=date(2026, 7, 16),
        history_fetcher=fetcher,
    )

    assert len(rows) == 2
    assert calls == [
        {
            "symbol": "sz001258",
            "start_date": "20260715",
            "end_date": "20260716",
            "adjust": "qfq",
            "timeout": 30.0,
        }
    ]


def test_normalize_qfq_rows_accepts_tencent_columns_and_epoch_dates() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": 1_784_131_200_000,
                "open": 9.82,
                "close": 10.01,
                "high": 10.12,
                "low": 9.71,
                "amount": 123_456,
            }
        ]
    )

    rows = normalize_qfq_rows(frame, "001258.SZSE")

    assert rows[0].trade_date == date(2026, 7, 15)
    assert rows[0].volume == 123_456.0
    assert rows[0].turnover is None


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("收盘", 0.0, "positive"),
        ("最高", 9.0, "high"),
        ("最低", 10.5, "low"),
        ("成交量", -1.0, "volume"),
        ("日期", "not-a-date", "date"),
    ],
)
def test_normalize_qfq_rows_rejects_invalid_ohlcv(
    column: str,
    value: object,
    message: str,
) -> None:
    frame = _qfq_frame()
    frame.loc[0, column] = value

    with pytest.raises(AdjustedDailyBarError, match=message):
        normalize_qfq_rows(frame, "001258.SZSE")


def test_normalize_qfq_rows_rejects_missing_columns_and_duplicate_dates() -> None:
    with pytest.raises(AdjustedDailyBarError, match="missing OHLC"):
        normalize_qfq_rows(_qfq_frame().drop(columns=["最高"]), "001258.SZSE")

    duplicate = _qfq_frame()
    duplicate.loc[1, "日期"] = "2026-07-15"
    with pytest.raises(AdjustedDailyBarError, match="duplicate"):
        normalize_qfq_rows(duplicate, "001258.SZSE")


def test_normalize_qfq_rows_allows_missing_optional_volume_fields() -> None:
    frame = _qfq_frame()
    frame.loc[0, "成交量"] = pd.NA
    frame.loc[0, "成交额"] = pd.NA

    rows = normalize_qfq_rows(frame, "001258.SZSE")

    assert rows[0].volume is None
    assert rows[0].turnover is None


def test_next_market_session_label_never_skips_a_suspended_symbol() -> None:
    calendar = [date(2026, 2, 12), date(2026, 2, 13)]
    bars = {date(2026, 2, 12): 2.78, date(2026, 3, 9): 3.06}

    assert next_market_session_close_label(bars, calendar, date(2026, 2, 12)) is None


def test_next_market_session_label_uses_the_immediate_market_session_only() -> None:
    calendar = [date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28)]
    bars = {
        date(2026, 7, 24): 10.0,
        date(2026, 7, 27): 11.005,
        date(2026, 7, 28): 10.5,
    }

    assert next_market_session_close_label(bars, calendar, date(2026, 7, 24)) == 11.005


def test_adjusted_daily_snapshot_and_scope_tables_are_registered() -> None:
    bars = schema.metadata.tables["low_suction_adjusted_daily_bars"]
    scopes = schema.metadata.tables["low_suction_adjusted_daily_bar_scopes"]

    assert tuple(bars.primary_key.columns.keys()) == (
        "vt_symbol",
        "trade_date",
        "adjustment",
    )
    assert {"source", "source_fingerprint", "raw"} <= set(bars.columns.keys())
    assert tuple(scopes.primary_key.columns.keys()) == (
        "trade_date",
        "adjustment",
        "source",
        "request_fingerprint",
    )
    assert {
        "requested_symbol_count",
        "returned_symbol_count",
        "accepted_symbol_count",
        "excluded_symbol_count",
        "complete",
        "request_fingerprint",
        "response_fingerprint",
        "raw",
    } <= set(scopes.columns.keys())


def test_qfq_daily_scope_is_complete_only_for_the_full_requested_symbol_set() -> None:
    rows = normalize_qfq_rows(_qfq_frame(), "001258.SZSE")

    scope = build_qfq_daily_scope(
        date(2026, 7, 15),
        expected_symbols=("001258.SZSE", "003032.SZSE"),
        accepted_rows_by_symbol={"001258.SZSE": rows[0]},
        fetch_failures={"003032.SZSE": "ConnectionError"},
    )

    assert scope.requested_symbol_count == 2
    assert scope.returned_symbol_count == 1
    assert scope.accepted_symbol_count == 1
    assert scope.excluded_symbol_count == 1
    assert scope.complete is False
    assert scope.raw["request"]["symbols_sha256"]
    assert scope.raw["response"]["excluded_examples"] == ["003032.SZSE"]
    assert scope.raw["attempt"]["fetch_failure_count"] == 1


def test_qfq_daily_scope_rejects_a_row_outside_its_declared_range() -> None:
    rows = normalize_qfq_rows(_qfq_frame(), "001258.SZSE")

    with pytest.raises(AdjustedDailyBarError, match="outside declared scope"):
        build_qfq_daily_scope(
            date(2026, 7, 15),
            expected_symbols=("003032.SZSE",),
            accepted_rows_by_symbol={"001258.SZSE": rows[0]},
        )
