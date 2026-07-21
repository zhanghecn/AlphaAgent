from __future__ import annotations

from datetime import date, datetime

from alphaagent.server.services.data_providers import tdx_transaction_history as tx
from alphaagent.server.services.data_providers.tdx_transaction_history import (
    _fetch_history_pages,
    aggregate_transaction_close_minutes,
    aggregate_transaction_minutes,
    history_pages_complete,
    iter_history_transactions,
    normalize_history_pages,
    validate_transaction_day,
)


def test_normalize_history_pages_reverses_pages_and_filters_non_trades() -> None:
    rows = normalize_history_pages(
        [
            [
                {"time": "10:01", "price": 10.4, "vol": 5, "buyorsell": 0},
                {"time": "15:10", "price": 10.4, "vol": 1, "buyorsell": 5},
            ],
            [
                {"time": "09:15", "price": 9.0, "vol": 0, "buyorsell": 8},
                {"time": "10:00", "price": 10.3, "vol": 8, "buyorsell": 1},
                {"time": "10:00", "price": 10.3, "vol": 0, "buyorsell": 2},
            ],
        ],
        trade_date=date(2026, 7, 16),
    )

    assert [(row["time"], row["sequence"]) for row in rows] == [
        ("10:00", 0),
        ("10:01", 1),
    ]
    assert rows[0]["observed_at"] == datetime(2026, 7, 16, 10, 0)
    assert rows[0]["direction_code"] == 1
    assert rows[0]["turnover"] == 8_240.0


def test_validate_transaction_day_separates_flow_completeness_from_price_audit() -> None:
    rows = normalize_history_pages(
        [
            [
                {"time": "09:25", "price": 10.0, "vol": 100, "buyorsell": 0},
                {"time": "15:00", "price": 10.5, "vol": 200, "buyorsell": 1},
            ]
        ],
        trade_date=date(2026, 7, 16),
    )
    ready = validate_transaction_day(
        rows,
        {
            "volume": 300,
            "high_price": 10.5,
            "low_price": 10.0,
            "close_price": 10.5,
        },
    )
    degraded_prices = validate_transaction_day(
        rows,
        {
            "volume": 300,
            "high_price": 10.5,
            "low_price": 9.97,
            "close_price": 10.5,
        },
    )
    invalid_volume = validate_transaction_day(
        rows,
        {
            "volume": 301,
            "high_price": 10.5,
            "low_price": 10.0,
            "close_price": 10.5,
        },
    )

    assert ready["status"] == "flow_ready"
    assert ready["volume_matches"] is True
    assert ready["price_audit_status"] == "ready"
    assert degraded_prices["status"] == "flow_ready"
    assert degraded_prices["price_audit_status"] == "degraded"
    assert degraded_prices["low_difference"] == 0.03
    assert invalid_volume["status"] == "invalid"
    assert invalid_volume["volume_matches"] is False


def test_validate_transaction_day_rejects_truncated_or_missing_close_tape() -> None:
    rows = normalize_history_pages(
        [
            [
                {"time": "09:25", "price": 10.0, "vol": 100, "buyorsell": 0},
                {"time": "14:59", "price": 10.5, "vol": 200, "buyorsell": 1},
            ]
        ],
        trade_date=date(2026, 7, 16),
    )
    daily = {
        "volume": 300,
        "high_price": 10.5,
        "low_price": 10.0,
        "close_price": 10.5,
    }

    truncated = validate_transaction_day(
        rows,
        daily,
        pagination_complete=False,
    )
    missing_close = validate_transaction_day(
        rows,
        daily,
        pagination_complete=True,
    )

    assert truncated["status"] == "invalid"
    assert "pagination_truncated" in truncated["reasons"]
    assert missing_close["status"] == "invalid"
    assert "closing_print_missing" in missing_close["reasons"]


def test_fetch_history_pages_stops_on_short_tail_and_reports_truncation() -> None:
    class Api:
        def __init__(self, page_lengths: list[int]) -> None:
            self.page_lengths = page_lengths
            self.starts: list[int] = []

        def get_history_transaction_data(
            self,
            market: int,
            symbol: str,
            start: int,
            count: int,
            trade_date: int,
        ) -> list[dict[str, object]]:
            self.starts.append(start)
            index = start // count
            return [
                {"time": "10:00", "price": 10.0, "vol": 1, "buyorsell": 0}
                for _ in range(self.page_lengths[index])
            ]

    complete_api = Api([2_000, 37])
    complete_pages = _fetch_history_pages(
        complete_api,
        market=0,
        symbol="000001",
        trade_date=date(2026, 7, 16),
        max_pages=4,
        page_size=2_000,
    )
    truncated_api = Api([2_000, 2_000])
    truncated_pages = _fetch_history_pages(
        truncated_api,
        market=0,
        symbol="000001",
        trade_date=date(2026, 7, 16),
        max_pages=2,
        page_size=2_000,
    )

    assert complete_api.starts == [0, 2_000]
    assert history_pages_complete(
        complete_pages,
        page_size=2_000,
        max_pages=4,
    ) is True
    assert truncated_api.starts == [0, 2_000]
    assert history_pages_complete(
        truncated_pages,
        page_size=2_000,
        max_pages=2,
    ) is False


def test_iter_history_transactions_reuses_one_connection(monkeypatch) -> None:
    calls = {"connect": 0, "disconnect": 0}

    class Api:
        def get_history_transaction_data(
            self,
            market: int,
            symbol: str,
            start: int,
            count: int,
            trade_date: int,
        ) -> list[dict[str, object]]:
            return [
                {"time": "09:25", "price": 10.0, "vol": 1, "buyorsell": 0},
                {"time": "15:00", "price": 10.1, "vol": 2, "buyorsell": 1},
            ]

    api = Api()

    def connect(**_kwargs):
        calls["connect"] += 1
        return api, {"name": "test"}

    def disconnect(received) -> None:
        assert received is api
        calls["disconnect"] += 1

    monkeypatch.setattr(tx, "_connect_tdx", connect)
    monkeypatch.setattr(tx, "_disconnect_tdx", disconnect)

    results = list(
        iter_history_transactions(
            [
                ("000001.SZSE", date(2026, 7, 16)),
                ("600000.SSE", date(2026, 7, 16)),
            ]
        )
    )

    assert calls == {"connect": 1, "disconnect": 1}
    assert [row["vt_symbol"] for row in results] == ["000001.SZSE", "600000.SSE"]
    assert all(row["pagination_complete"] is True for row in results)


def test_aggregate_transaction_minutes_keeps_only_causal_minute_values() -> None:
    rows = normalize_history_pages(
        [
            [
                {"time": "10:00", "price": 10.0, "vol": 1_000, "buyorsell": 0},
                {"time": "10:00", "price": 10.2, "vol": 600, "buyorsell": 1},
                {"time": "10:01", "price": 10.1, "vol": 50, "buyorsell": 2},
            ]
        ],
        trade_date=date(2026, 7, 16),
    )

    minutes = aggregate_transaction_minutes(rows)

    assert len(minutes) == 2
    first = minutes[0]
    assert first["bar_time"] == datetime(2026, 7, 16, 10, 0)
    assert first["open_price"] == 10.0
    assert first["close_price"] == 10.2
    assert first["high_price"] == 10.2
    assert first["low_price"] == 10.0
    assert first["volume"] == 1_600.0
    assert first["trade_count"] == 2
    assert first["max_print_turnover"] == 1_000_000.0
    assert first["large_print_count"] == 1
    assert first["large_print_turnover"] == 1_000_000.0
    assert first["direction_0_volume"] == 1_000.0
    assert first["direction_1_volume"] == 600.0
    assert first["direction_2_volume"] == 0.0


def test_aggregate_transaction_close_minutes_uses_only_completed_intervals() -> None:
    rows = normalize_history_pages(
        [
            [
                {"time": "09:25", "price": 10.0, "vol": 10, "buyorsell": 0},
                {"time": "09:30", "price": 10.1, "vol": 20, "buyorsell": 1},
                {"time": "09:31", "price": 10.2, "vol": 30, "buyorsell": 0},
                {"time": "11:29", "price": 10.3, "vol": 40, "buyorsell": 1},
                {"time": "11:30", "price": 10.4, "vol": 50, "buyorsell": 0},
                {"time": "13:00", "price": 10.5, "vol": 60, "buyorsell": 1},
                {"time": "14:29", "price": 10.6, "vol": 70, "buyorsell": 0},
                {"time": "14:30", "price": 10.7, "vol": 80, "buyorsell": 1},
            ]
        ],
        trade_date=date(2026, 7, 16),
    )

    minutes = aggregate_transaction_close_minutes(rows)
    by_time = {row["bar_time"].strftime("%H:%M"): row for row in minutes}

    assert sorted(by_time) == ["09:31", "09:32", "11:30", "13:01", "14:30"]
    assert by_time["09:31"]["volume"] == 30.0
    assert by_time["09:32"]["volume"] == 30.0
    assert by_time["11:30"]["volume"] == 90.0
    assert by_time["13:01"]["volume"] == 60.0
    assert by_time["14:30"]["volume"] == 70.0
    assert by_time["09:31"]["direction_0_turnover"] == 10_000.0
    assert by_time["09:31"]["direction_1_turnover"] == 20_200.0
    assert by_time["09:31"]["price_up_turnover"] == 20_200.0
    assert all(row["source_cutoff_time"] <= "14:29" for row in minutes)


def test_normalize_history_pages_does_not_deduplicate_identical_trades() -> None:
    rows = normalize_history_pages(
        [
            [
                {"time": "10:00", "price": 10.0, "vol": 10, "buyorsell": 0},
                {"time": "10:00", "price": 10.0, "vol": 10, "buyorsell": 0},
            ]
        ],
        trade_date=date(2026, 7, 16),
    )

    assert len(rows) == 2
    assert [row["sequence"] for row in rows] == [0, 1]
