from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import cli
from alphaagent.server.services.low_suction.minute_entry import (
    STRICT_MINUTE_EXIT_KEYS,
    generate_strict_minute_outcomes,
)
from alphaagent.server.services.low_suction.minute_manifest import (
    build_candidate_minute_manifest,
    render_minute_manifest_json,
)


def _trading_dates() -> tuple[date, ...]:
    start = date(2026, 7, 13)
    return tuple(start + timedelta(days=index) for index in range(6))


def _signal(*, signal_time: time = time(10, 0)) -> pd.DataFrame:
    trade_date = _trading_dates()[0]
    return pd.DataFrame(
        [
            {
                "event_id": "EVENT_A",
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "signal_at": datetime.combine(trade_date, signal_time),
                "evidence_level": "strict",
            }
        ]
    )


def _bar(
    trade_date: date,
    bar_time: time,
    *,
    open_price: float = 10.0,
    close_price: float = 10.05,
    volume: float = 10_000.0,
) -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": trade_date,
        "bar_time": datetime.combine(trade_date, bar_time),
        "open_price": open_price,
        "close_price": close_price,
        "high_price": max(open_price, close_price) + 0.05,
        "low_price": min(open_price, close_price) - 0.05,
        "volume": volume,
        "limit_up_price": 11.0,
        "limit_down_price": 9.0,
        "suspended": False,
        "source": "fixture",
    }


def _execution_bars(*, entry_time: time = time(10, 1)) -> pd.DataFrame:
    dates = _trading_dates()
    rows = [_bar(dates[0], entry_time)]
    rows.extend(
        [
            _bar(dates[1], time(10, 1), open_price=10.2, close_price=10.25),
            _bar(dates[1], time(14, 31), open_price=10.3, close_price=10.35),
            _bar(dates[1], time(15, 0), open_price=10.4, close_price=10.45),
            _bar(dates[3], time(15, 0), open_price=10.6, close_price=10.65),
            _bar(dates[5], time(15, 0), open_price=10.8, close_price=10.85),
        ]
    )
    return pd.DataFrame(rows)


def _run(
    *,
    signals: pd.DataFrame | None = None,
    bars: pd.DataFrame | None = None,
    cost_multiplier: float = 1.0,
) -> pd.DataFrame:
    return generate_strict_minute_outcomes(
        signals if signals is not None else _signal(),
        bars if bars is not None else _execution_bars(),
        trading_dates=_trading_dates(),
        initial_cash=100_000.0,
        cost_multiplier=cost_multiplier,
    )


def test_signal_fills_at_next_minute_open_not_signal_bar() -> None:
    outcomes = _run()

    assert set(outcomes["entry_time"]) == {pd.Timestamp("2026-07-13 10:01:00")}
    assert set(outcomes["entry_price_raw"]) == {10.0}


def test_lunch_signal_fills_at_first_afternoon_bar() -> None:
    outcomes = _run(
        signals=_signal(signal_time=time(11, 30)),
        bars=_execution_bars(entry_time=time(13, 1)),
    )

    assert set(outcomes["entry_time"]) == {pd.Timestamp("2026-07-13 13:01:00")}


def test_missing_immediate_next_bar_is_not_deferred() -> None:
    bars = _execution_bars(entry_time=time(10, 2))

    outcomes = _run(bars=bars)

    assert set(outcomes["status"]) == {"rejected"}
    assert set(outcomes["reason"]) == {"missing_next_minute_bar"}


def test_signal_at_entry_cutoff_is_rejected() -> None:
    outcomes = _run(signals=_signal(signal_time=time(14, 55)))

    assert set(outcomes["status"]) == {"rejected"}
    assert set(outcomes["reason"]) == {"signal_at_or_after_entry_cutoff"}


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"volume": 0.0}, "entry_zero_volume"),
        ({"suspended": True}, "entry_suspended"),
        (
            {
                "open_price": 11.0,
                "close_price": 11.0,
                "high_price": 11.0,
                "low_price": 11.0,
            },
            "entry_one_price_limit_up",
        ),
    ],
)
def test_non_executable_next_bar_is_rejected(
    mutation: dict[str, object],
    reason: str,
) -> None:
    bars = _execution_bars()
    entry = bars["bar_time"] == pd.Timestamp("2026-07-13 10:01:00")
    for column, value in mutation.items():
        bars.loc[entry, column] = value

    outcomes = _run(bars=bars)

    assert set(outcomes["status"]) == {"rejected"}
    assert set(outcomes["reason"]) == {reason}


def test_fixed_exits_start_on_d_plus_one_and_include_all_horizons() -> None:
    outcomes = _run().set_index("exit_key")

    assert set(outcomes.index) == set(STRICT_MINUTE_EXIT_KEYS)
    assert outcomes.loc["d1_1000", "exit_time"] == pd.Timestamp(
        "2026-07-14 10:01:00"
    )
    assert outcomes.loc["d1_1430", "exit_time"] == pd.Timestamp(
        "2026-07-14 14:31:00"
    )
    assert outcomes.loc["d1_close", "exit_time"] == pd.Timestamp(
        "2026-07-14 15:00:00"
    )
    assert outcomes.loc["d3_close", "exit_date"] == pd.Timestamp("2026-07-16")
    assert outcomes.loc["d5_close", "exit_date"] == pd.Timestamp("2026-07-18")
    assert (outcomes["exit_date"] > pd.Timestamp("2026-07-13")).all()


def test_costs_lots_and_double_cost_are_applied() -> None:
    normal = _run().set_index("exit_key")
    stressed = _run(cost_multiplier=2.0).set_index("exit_key")

    assert (normal["volume"] % 100 == 0).all()
    assert (normal["total_fees"] > 0).all()
    assert normal.loc["d1_close", "net_return_pct"] < normal.loc[
        "d1_close", "gross_return_pct"
    ]
    assert stressed.loc["d1_close", "net_return_pct"] < normal.loc[
        "d1_close", "net_return_pct"
    ]


def test_one_price_limit_down_exit_remains_unclosed() -> None:
    bars = _execution_bars()
    target = bars["bar_time"] == pd.Timestamp("2026-07-14 10:01:00")
    for column in ("open_price", "close_price", "high_price", "low_price"):
        bars.loc[target, column] = 9.0

    outcomes = _run(bars=bars).set_index("exit_key")

    assert outcomes.loc["d1_1000", "status"] == "unclosed"
    assert outcomes.loc["d1_1000", "reason"] == "exit_one_price_limit_down"


def _window_times(start: str, end: str) -> list[time]:
    values = pd.date_range(f"2026-07-13 {start}", f"2026-07-13 {end}", freq="1min")
    return [value.time() for value in values]


def _full_entry_day(symbol: str, *, source: str = "fixture") -> list[dict[str, object]]:
    windows = (
        ("09:31", "10:00"),
        ("10:01", "11:30"),
        ("13:01", "14:30"),
        ("14:31", "14:55"),
    )
    rows = []
    for start, end in windows:
        for bar_time in _window_times(start, end):
            row = _bar(date(2026, 7, 13), bar_time)
            row["vt_symbol"] = symbol
            row["source"] = source
            rows.append(row)
    return rows


def test_manifest_is_candidate_directed_and_reports_each_window() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "A",
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 13),
                "evidence_level": "strict",
            },
            {
                "event_id": "B",
                "vt_symbol": "600002.SSE",
                "trade_date": date(2026, 7, 13),
                "evidence_level": "strict",
            },
        ]
    )
    bars = _full_entry_day("600001.SSE")
    bars.extend(_full_entry_day("999999.SSE", source="unrelated"))
    bars.append({**_full_entry_day("600002.SSE")[0], "source": "partial"})

    manifest = build_candidate_minute_manifest(events, pd.DataFrame(bars))

    assert len(manifest) == 8
    assert set(manifest["event_id"]) == {"A", "B"}
    complete = manifest.loc[manifest["event_id"] == "A"]
    partial = manifest.loc[manifest["event_id"] == "B"]
    assert set(complete["rejection_reason"].dropna()) == set()
    assert complete["existing_bars"].sum() == 235
    assert set(partial["rejection_reason"]) == {
        "incomplete_minute_window",
        "missing_minute_window",
    }
    assert set(partial["source"].dropna()) == {"partial"}


def test_manifest_json_never_exposes_formal_metrics() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "A",
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 13),
                "evidence_level": "membership_proxy",
            }
        ]
    )
    manifest = build_candidate_minute_manifest(
        events,
        pd.DataFrame(_full_entry_day("600001.SSE")),
    )

    payload = json.loads(render_minute_manifest_json(manifest))

    assert payload["formal_metrics"] is None
    assert payload["evidence_level"] == "membership_proxy"
    assert payload["complete_rows"] == 4


def test_empty_minute_inventory_becomes_explicit_gaps() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "A",
                "vt_symbol": "600001.SSE",
                "trade_date": date(2026, 7, 13),
                "evidence_level": "strict",
            }
        ]
    )
    empty_bars = pd.DataFrame(columns=_execution_bars().columns)

    manifest = build_candidate_minute_manifest(events, empty_bars)

    assert len(manifest) == 4
    assert set(manifest["existing_bars"]) == {0}
    assert set(manifest["rejection_reason"]) == {"missing_minute_window"}


def test_cli_registers_candidate_minute_manifest_command() -> None:
    args = cli.build_parser().parse_args(
        ["minute-manifest", "--format", "json", "--start", "2026-07-01"]
    )

    assert args.command == "minute-manifest"
    assert args.format == "json"
    assert args.start == date(2026, 7, 1)
