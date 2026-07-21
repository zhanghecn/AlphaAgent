from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

import alphaagent.server.services.low_suction.leader_ma5_scheme_minutes as minutes


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "signal-a",
                "signal_date": "2025-01-02",
                "entry_date": "2025-01-03",
                "vt_symbol": "600001.SSE",
            },
            {
                "signal_id": "signal-b",
                "signal_date": "2025-01-06",
                "entry_date": "2025-01-07",
                "vt_symbol": "000001.SZSE",
            },
        ]
    )


def _five_minute_times(trade_date: date) -> tuple[datetime, ...]:
    values = []
    for start in ("09:35", "13:05"):
        current = datetime.combine(
            trade_date,
            datetime.strptime(start, "%H:%M").time(),
        )
        values.extend(current + timedelta(minutes=5 * index) for index in range(24))
    return tuple(values)


def _bars(
    symbol: str,
    trade_date: date,
    *,
    count: int = 48,
    unexpected_last_time: bool = False,
) -> list[dict[str, object]]:
    times = list(_five_minute_times(trade_date)[:count])
    if times and unexpected_last_time:
        times[-1] = datetime.combine(
            trade_date,
            datetime.strptime("15:05", "%H:%M").time(),
        )
    return [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date,
            "bar_time": bar_time,
            "interval": "5m",
            "source": "tdx_public_hq",
        }
        for bar_time in times
    ]


def test_scheme_pairs_are_exact_signal_and_next_session_pairs() -> None:
    pairs = minutes.build_scheme_minute_pairs(_candidates())

    assert len(pairs) == 4
    assert list(pairs["event_id"]) == [
        "signal-a:signal",
        "signal-a:next_session",
        "signal-b:signal",
        "signal-b:next_session",
    ]
    assert list(pairs["pair_role"]) == [
        "signal",
        "next_session",
        "signal",
        "next_session",
    ]
    assert set(zip(pairs["vt_symbol"], pairs["entry_date"], strict=True)) == {
        ("600001.SSE", date(2025, 1, 2)),
        ("600001.SSE", date(2025, 1, 3)),
        ("000001.SZSE", date(2025, 1, 6)),
        ("000001.SZSE", date(2025, 1, 7)),
    }


def test_manifest_distinguishes_complete_partial_invalid_and_missing() -> None:
    pairs = minutes.build_scheme_minute_pairs(_candidates())
    existing = pd.DataFrame(
        [
            *_bars("600001.SSE", date(2025, 1, 2)),
            *_bars("600001.SSE", date(2025, 1, 3), count=47),
            *_bars(
                "000001.SZSE",
                date(2025, 1, 6),
                unexpected_last_time=True,
            ),
        ]
    )

    manifest = minutes.build_scheme_5m_manifest(pairs, existing)

    statuses = dict(zip(manifest["event_id"], manifest["status"], strict=True))
    assert statuses == {
        "signal-a:signal": "complete",
        "signal-a:next_session": "incomplete",
        "signal-b:signal": "invalid",
        "signal-b:next_session": "missing",
    }


def test_existing_loader_uses_only_exact_symbol_date_pairs(monkeypatch) -> None:
    pairs = minutes.build_scheme_minute_pairs(_candidates())
    captured = {}

    def fake_read_sql(statement, engine, **kwargs):
        del engine, kwargs
        compiled = statement.compile()
        captured["sql"] = str(compiled)
        captured["params"] = compiled.params
        return pd.DataFrame(columns=minutes.MINUTE_COLUMNS)

    monkeypatch.setattr(minutes.pd, "read_sql", fake_read_sql)

    loaded = minutes.load_existing_scheme_minutes(pairs, engine=object())

    assert loaded.empty
    assert "(stock_minute_bars.vt_symbol, stock_minute_bars.trade_date) IN" in captured[
        "sql"
    ]
    tuple_values = next(
        value
        for value in captured["params"].values()
        if isinstance(value, list) and value and isinstance(value[0], tuple)
    )
    assert set(tuple_values) == {
        ("600001.SSE", date(2025, 1, 2)),
        ("600001.SSE", date(2025, 1, 3)),
        ("000001.SZSE", date(2025, 1, 6)),
        ("000001.SZSE", date(2025, 1, 7)),
    }


def test_backfill_requests_only_bounded_incomplete_pairs(monkeypatch) -> None:
    manifest = pd.DataFrame(
        [
            {
                "event_id": "signal-a:signal",
                "source_date": date(2025, 1, 2),
                "entry_date": date(2025, 1, 2),
                "vt_symbol": "600001.SSE",
                "status": "complete",
            },
            {
                "event_id": "signal-a:next_session",
                "source_date": date(2025, 1, 2),
                "entry_date": date(2025, 1, 3),
                "vt_symbol": "600001.SSE",
                "status": "missing",
            },
            {
                "event_id": "signal-b:signal",
                "source_date": date(2025, 1, 6),
                "entry_date": date(2025, 1, 6),
                "vt_symbol": "000001.SZSE",
                "status": "incomplete",
            },
        ]
    )
    captured = {}
    monkeypatch.setattr(
        minutes,
        "load_scheme_5m_manifest",
        lambda candidates=None: manifest,
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "dry_run", "rows_read": 0, "rows_written": 0}

    monkeypatch.setattr(minutes, "_import_tdx_gaps", fake_import)

    result = minutes.backfill_missing_scheme_5m(dry_run=True, max_gaps=1)

    assert result["requested_missing_pairs"] == 1
    assert captured["dry_run"] is True
    assert captured["interval"] == "5m"
    assert captured["tail_entry_start"] == "09:35"
    assert captured["tail_entry_end"] == "15:00"
    assert captured["gaps"] == [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": date(2025, 1, 3),
            "reference_date": date(2025, 1, 2),
            "window": "leader_ma5_scheme_signal_and_next_session_5m",
        }
    ]
