from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.forward_ma5_minutes import (
    build_forward_ma5_signal_pairs,
    build_forward_ma5_signal_manifest,
    backfill_forward_ma5_signal_5m,
)


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_version": "low-suction-forward-ma5-shadow-v1",
                "signal_trade_date": date(2026, 7, 17),
                "identity_mode": "rank_by_return",
                "vt_symbol": "600001.SSE",
                "source_trade_date": date(2026, 7, 16),
                "signal_eligible": True,
            },
            {
                "contract_version": "low-suction-forward-ma5-shadow-v1",
                "signal_trade_date": date(2026, 7, 17),
                "identity_mode": "rank_by_turnover",
                "vt_symbol": "600001.SSE",
                "source_trade_date": date(2026, 7, 16),
                "signal_eligible": True,
            },
            {
                "contract_version": "low-suction-forward-ma5-shadow-v1",
                "signal_trade_date": date(2026, 7, 17),
                "identity_mode": "rank_by_return",
                "vt_symbol": "000001.SZSE",
                "source_trade_date": date(2026, 7, 16),
                "signal_eligible": False,
            },
        ]
    )


def _five_minute_bars() -> pd.DataFrame:
    trade_date = date(2026, 7, 17)
    times = []
    for start in ("09:35", "13:05"):
        current = datetime.combine(
            trade_date,
            datetime.strptime(start, "%H:%M").time(),
        )
        times.extend(current + timedelta(minutes=5 * index) for index in range(24))
    return pd.DataFrame(
        {
            "vt_symbol": "600001.SSE",
            "trade_date": trade_date,
            "bar_time": times,
            "interval": "5m",
            "source": "tdx_public_hq",
        }
    )


def test_forward_signal_pairs_only_keep_unique_eligible_symbol_dates() -> None:
    pairs = build_forward_ma5_signal_pairs(_candidates())

    assert len(pairs) == 1
    assert pairs.loc[0, "vt_symbol"] == "600001.SSE"
    assert pairs.loc[0, "entry_date"] == date(2026, 7, 17)
    assert pairs.loc[0, "source_date"] == date(2026, 7, 16)


def test_forward_signal_manifest_requires_complete_48_bar_path() -> None:
    pairs = build_forward_ma5_signal_pairs(_candidates())

    complete = build_forward_ma5_signal_manifest(pairs, _five_minute_bars())
    incomplete = build_forward_ma5_signal_manifest(
        pairs,
        _five_minute_bars().iloc[:-1],
    )

    assert complete.loc[0, "status"] == "complete"
    assert complete.loc[0, "existing_bars"] == 48
    assert incomplete.loc[0, "status"] == "incomplete"


def test_forward_signal_backfill_requests_only_missing_exact_pairs(monkeypatch) -> None:
    manifest = pd.DataFrame(
        [
            {
                "event_id": "complete",
                "source_date": date(2026, 7, 16),
                "entry_date": date(2026, 7, 17),
                "vt_symbol": "600001.SSE",
                "status": "complete",
            },
            {
                "event_id": "missing",
                "source_date": date(2026, 7, 17),
                "entry_date": date(2026, 7, 18),
                "vt_symbol": "000001.SZSE",
                "status": "missing",
            },
        ]
    )
    captured = {}
    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.forward_ma5_minutes.load_forward_ma5_signal_manifest",
        lambda: manifest,
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 48, "rows_written": 48}

    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.forward_ma5_minutes._import_tdx_gaps",
        fake_import,
    )

    result = backfill_forward_ma5_signal_5m(dry_run=False, max_gaps=10)

    assert result["requested_missing_pairs"] == 1
    assert captured["gaps"] == [
        {
            "vt_symbol": "000001.SZSE",
            "trade_date": date(2026, 7, 18),
            "reference_date": date(2026, 7, 17),
            "window": "forward_ma5_signal_day_5m",
        }
    ]
    assert captured["interval"] == "5m"
    assert captured["tail_entry_start"] == "09:35"
    assert captured["tail_entry_end"] == "15:00"
    assert captured["dry_run"] is False
