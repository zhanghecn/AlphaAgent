"""高位接力盘后补数:盘中整天漏跑也不能留下空白历史。"""

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.high_relay import eod_finalize


DATA_DATE = date(2026, 10, 30)


def _entry(vt_symbol: str = "603006.SSE", **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "vt_symbol": vt_symbol,
        "name": "联明股份",
        "group4": "二接三阴",
        "point": "B1",
        "level": "A",
        "actionable": True,
        "auction_gate": "today_6_9",
        "prev_close": 10.0,
        "limit_price": 11.0,
        "weak_point": "—",
    }
    row.update(overrides)
    return row


def _bars(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "vt_symbol": "603006.SSE",
            "trade_date": pd.Timestamp("2026-10-29"),
            "open_price": 10.0,
            "high_price": 10.0,
            "low_price": 10.0,
            "close_price": 10.0,
        },
        *rows,
    ])


def _fake_bars(monkeypatch: pytest.MonkeyPatch, bars: pd.DataFrame) -> None:
    monkeypatch.setattr(eod_finalize, "_load_bars", lambda *_args: bars)
    monkeypatch.setattr(eod_finalize, "_dyn_group_for_date", lambda _date: "strong")


def test_backfill_missing_pool_signal_uses_real_daily_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = [_entry()]
    signals: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(eod_finalize.repository, "load_pool", lambda _date: pool)
    monkeypatch.setattr(eod_finalize.repository, "load_signal_map", lambda _date: signals)
    monkeypatch.setattr(
        eod_finalize.repository,
        "upsert_signal",
        lambda _date, vt, **fields: signals.setdefault(vt, {}).update(fields),
    )
    _fake_bars(monkeypatch, _bars([{
        "vt_symbol": "603006.SSE",
        "trade_date": pd.Timestamp(DATA_DATE),
        "open_price": 10.7,
        "high_price": 10.8,
        "low_price": 10.1,
        "close_price": 10.2,
    }]))

    created = eod_finalize._backfill_missing_pool_signals(DATA_DATE)

    assert created == 1
    assert signals["603006.SSE"]["status"] == "no_trigger"
    assert signals["603006.SSE"]["auction_pct"] == 7.0
    assert signals["603006.SSE"]["last_price"] == 10.2
    assert signals["603006.SSE"]["change_pct"] == 2.0


def test_backfill_missing_pool_signal_keeps_auction_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(eod_finalize.repository, "load_pool", lambda _date: [_entry()])
    monkeypatch.setattr(eod_finalize.repository, "load_signal_map", lambda _date: signals)
    monkeypatch.setattr(
        eod_finalize.repository,
        "upsert_signal",
        lambda _date, vt, **fields: signals.setdefault(vt, {}).update(fields),
    )
    _fake_bars(monkeypatch, _bars([{
        "vt_symbol": "603006.SSE",
        "trade_date": pd.Timestamp(DATA_DATE),
        "open_price": 10.0,
        "high_price": 11.0,
        "low_price": 9.9,
        "close_price": 11.0,
    }]))

    eod_finalize._backfill_missing_pool_signals(DATA_DATE)

    assert signals["603006.SSE"]["status"] == "skipped_auction"
    assert "entry_price" not in signals["603006.SSE"]


def test_backfill_missing_pool_signal_ignores_radar_and_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = {"603006.SSE": {"status": "closed"}}
    writes: list[str] = []
    monkeypatch.setattr(
        eod_finalize.repository,
        "load_pool",
        lambda _date: [_entry(), _entry("600715.SSE", actionable=False)],
    )
    monkeypatch.setattr(eod_finalize.repository, "load_signal_map", lambda _date: existing)
    monkeypatch.setattr(
        eod_finalize.repository,
        "upsert_signal",
        lambda _date, vt, **_fields: writes.append(vt),
    )
    _fake_bars(monkeypatch, _bars([]))

    created = eod_finalize._backfill_missing_pool_signals(DATA_DATE)

    assert created == 0
    assert writes == []


def test_dyn_group_for_new_month_follows_live_latest_materialized_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphaagent.server.services.high_relay import service

    monkeypatch.setattr(
        service,
        "_load_dyn_states",
        lambda: ({"2026-09": "weak"}, "2026-09"),
    )

    assert eod_finalize._dyn_group_for_date(DATA_DATE) == "weak"


def test_backfill_missing_pool_signal_uses_live_auction_point_reassignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(eod_finalize.repository, "load_pool", lambda _date: [_entry()])
    monkeypatch.setattr(eod_finalize.repository, "load_signal_map", lambda _date: signals)
    monkeypatch.setattr(
        eod_finalize.repository,
        "upsert_signal",
        lambda _date, vt, **fields: signals.setdefault(vt, {}).update(fields),
    )
    monkeypatch.setattr(
        eod_finalize.live_scan,
        "_point_after_auction",
        lambda *_args, **_kwargs: ("C2", "A"),
        raising=False,
    )
    _fake_bars(monkeypatch, _bars([{
        "vt_symbol": "603006.SSE",
        "trade_date": pd.Timestamp(DATA_DATE),
        "open_price": 10.7,
        "high_price": 10.8,
        "low_price": 10.1,
        "close_price": 10.2,
    }]))

    eod_finalize._backfill_missing_pool_signals(DATA_DATE)

    assert signals["603006.SSE"]["point"] == "C2"
    assert signals["603006.SSE"]["level"] == "A"


def test_eod_finalize_runs_missing_pool_recovery_before_residual_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(eod_finalize.pool_mod, "latest_daily_date", lambda: DATA_DATE)
    monkeypatch.setattr(eod_finalize, "_backfill_touch_times", lambda _date: 0)
    monkeypatch.setattr(
        eod_finalize,
        "_backfill_missing_pool_signals",
        lambda _date: calls.append("recover") or 2,
    )
    monkeypatch.setattr(
        eod_finalize,
        "_settle_residual_signals",
        lambda _date: calls.append("settle") or 0,
    )
    monkeypatch.setattr(
        eod_finalize,
        "_finalize_exits",
        lambda _date: {"closed": 0, "holding": 0, "processed": 0},
    )
    monkeypatch.setattr(eod_finalize.pool_mod, "compute_pool", lambda _date: {
        "entries": [],
        "exec_date": "2026-11-02",
        "mkt_lim_tm1": 38,
        "filter_stats": {"actionable": 0},
    })
    monkeypatch.setattr(eod_finalize.repository, "save_pool", lambda *_args: 0)

    result = eod_finalize.run_eod_finalize()

    assert calls == ["recover", "settle"]
    assert "漏扫补建 2" in str(result["message"])
