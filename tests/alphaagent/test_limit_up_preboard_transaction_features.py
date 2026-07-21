from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
    build_transaction_feature_capture,
    build_transaction_feature_rows,
)


def _minute(
    minute: int,
    *,
    trade_count: int = 10,
    turnover: float = 100.0,
    max_print: float = 10.0,
    large_print: float = 0.0,
    direction_0: float = 50.0,
    direction_1: float = 50.0,
    price_up: float = 40.0,
    price_down: float = 20.0,
    signed_path: float = 0.1,
    absolute_path: float = 0.2,
) -> dict[str, object]:
    bar_time = datetime(2026, 7, 16, 9, 55) + timedelta(minutes=minute)
    return {
        "trade_date": bar_time.date(),
        "bar_time": bar_time,
        "turnover": turnover,
        "trade_count": trade_count,
        "max_print_turnover": max_print,
        "large_print_turnover": large_print,
        "direction_0_turnover": direction_0,
        "direction_1_turnover": direction_1,
        "direction_2_turnover": max(turnover - direction_0 - direction_1, 0.0),
        "price_up_turnover": price_up,
        "price_down_turnover": price_down,
        "price_flat_turnover": max(turnover - price_up - price_down, 0.0),
        "signed_price_path": signed_path,
        "absolute_price_path": absolute_path,
        "source": "tdx.history_transaction",
    }


def test_transaction_feature_names_are_frozen() -> None:
    assert TRANSACTION_FEATURE_VERSION == "limit-up-preboard-transaction-flow-v1"
    assert TRANSACTION_FEATURE_NAMES == (
        "tx_trade_count_acceleration_1m_5m",
        "tx_max_print_turnover_share_1m",
        "tx_large_print_turnover_share_1m",
        "tx_large_print_turnover_share_3m",
        "tx_direction_01_imbalance_1m",
        "tx_direction_01_imbalance_3m",
        "tx_price_move_turnover_imbalance_1m",
        "tx_price_move_turnover_imbalance_3m",
        "tx_path_efficiency_1m",
    )


def test_build_transaction_feature_rows_uses_exact_causal_formulas() -> None:
    minutes = [_minute(index) for index in range(5)]
    minutes.append(
        _minute(
            5,
            trade_count=20,
            turnover=200.0,
            max_print=40.0,
            large_print=100.0,
            direction_0=150.0,
            direction_1=50.0,
            price_up=120.0,
            price_down=40.0,
            signed_path=0.2,
            absolute_path=0.4,
        )
    )
    minutes[-3].update(
        {
            "large_print_turnover": 0.0,
            "direction_0_turnover": 50.0,
            "direction_1_turnover": 50.0,
            "price_up_turnover": 40.0,
            "price_down_turnover": 20.0,
        }
    )
    minutes[-2].update(
        {
            "large_print_turnover": 20.0,
            "direction_0_turnover": 20.0,
            "direction_1_turnover": 60.0,
            "price_up_turnover": 10.0,
            "price_down_turnover": 30.0,
        }
    )
    future = _minute(
        6,
        trade_count=10_000,
        turnover=1_000_000.0,
        max_print=1_000_000.0,
        large_print=1_000_000.0,
        direction_0=1_000_000.0,
        direction_1=0.0,
        price_up=1_000_000.0,
        price_down=0.0,
        signed_path=10.0,
        absolute_path=10.0,
    )

    without_future = build_transaction_feature_rows(minutes)
    with_future = build_transaction_feature_rows([*minutes, future])
    current = next(
        row for row in without_future if row["bar_time"] == datetime(2026, 7, 16, 10, 0)
    )
    current_with_future = next(
        row for row in with_future if row["bar_time"] == datetime(2026, 7, 16, 10, 0)
    )

    assert current == current_with_future
    assert current["values"] == {
        "tx_trade_count_acceleration_1m_5m": 2.0,
        "tx_max_print_turnover_share_1m": 0.2,
        "tx_large_print_turnover_share_1m": 0.5,
        "tx_large_print_turnover_share_3m": 0.3,
        "tx_direction_01_imbalance_1m": 0.5,
        "tx_direction_01_imbalance_3m": 0.15789474,
        "tx_price_move_turnover_imbalance_1m": 0.5,
        "tx_price_move_turnover_imbalance_3m": 0.30769231,
        "tx_path_efficiency_1m": 0.5,
    }


def test_zero_denominator_marks_only_that_minute_unscoreable() -> None:
    minutes = [_minute(index) for index in range(5)]
    minutes.append(
        _minute(
            5,
            direction_0=0.0,
            direction_1=0.0,
            price_up=0.0,
            price_down=0.0,
            signed_path=0.0,
            absolute_path=0.0,
        )
    )

    rows = build_transaction_feature_rows(minutes)

    assert all(row["bar_time"] != datetime(2026, 7, 16, 10, 0) for row in rows)


def test_capture_fingerprint_changes_when_past_trade_changes_not_future_metadata() -> None:
    raw_rows = [
        {
            "sequence": 0,
            "time": "09:25",
            "price": 10.0,
            "volume": 100.0,
            "turnover": 100_000.0,
            "direction_code": 0,
            "observed_at": datetime(2026, 7, 16, 9, 25),
        },
        {
            "sequence": 1,
            "time": "15:00",
            "price": 10.5,
            "volume": 200.0,
            "turnover": 210_000.0,
            "direction_code": 1,
            "observed_at": datetime(2026, 7, 16, 15, 0),
        },
    ]
    fetched = {
        "source": "tdx.history_transaction",
        "host": {"name": "a"},
        "page_count": 1,
        "raw_row_count": 2,
        "trade_row_count": 2,
        "pagination_complete": True,
        "rows": raw_rows,
    }
    daily = {
        "volume": 300.0,
        "high_price": 10.5,
        "low_price": 10.0,
        "close_price": 10.5,
    }

    first_scope, _ = build_transaction_feature_capture(
        "000001.SZSE",
        date(2026, 7, 16),
        fetched,
        daily,
    )
    different_host = deepcopy(fetched)
    different_host["host"] = {"name": "b"}
    host_scope, _ = build_transaction_feature_capture(
        "000001.SZSE",
        date(2026, 7, 16),
        different_host,
        daily,
    )
    changed_trade = deepcopy(fetched)
    changed_trade["rows"][0]["direction_code"] = 2
    changed_scope, _ = build_transaction_feature_capture(
        "000001.SZSE",
        date(2026, 7, 16),
        changed_trade,
        daily,
    )

    assert first_scope["input_fingerprint"] == host_scope["input_fingerprint"]
    assert first_scope["input_fingerprint"] != changed_scope["input_fingerprint"]
    assert first_scope["status"] == "invalid"
    assert first_scope["raw"]["quality_reasons"] == [
        "no_scoreable_feature_rows"
    ]


def test_flow_ready_day_without_scoreable_rows_is_frozen_as_invalid() -> None:
    rows = [
        {
            "sequence": 0,
            "time": "09:25",
            "price": 10.0,
            "volume": 100.0,
            "turnover": 100_000.0,
            "direction_code": 0,
        },
        {
            "sequence": 1,
            "time": "15:00",
            "price": 10.5,
            "volume": 200.0,
            "turnover": 210_000.0,
            "direction_code": 1,
        },
    ]
    scope, feature_rows = build_transaction_feature_capture(
        "000001.SZSE",
        date(2026, 7, 16),
        {
            "source": "tdx.history_transaction",
            "pagination_complete": True,
            "rows": rows,
        },
        {
            "volume": 300.0,
            "high_price": 10.5,
            "low_price": 10.0,
            "close_price": 10.5,
        },
    )

    assert feature_rows == []
    assert scope["status"] == "invalid"
    assert scope["raw"]["quality_reasons"] == ["no_scoreable_feature_rows"]
