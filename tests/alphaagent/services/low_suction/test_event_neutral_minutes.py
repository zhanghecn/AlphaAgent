from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from alphaagent.server.services.low_suction import event_neutral_minutes
from alphaagent.server.services.low_suction.cli import build_parser


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 7, 2),
                "entry_date": date(2025, 7, 2),
                "context_date": date(2025, 7, 1),
                "vt_symbol": "600001.SSE",
            },
            {
                "event_id": 2,
                "source_date": date(2025, 7, 2),
                "entry_date": date(2025, 7, 2),
                "context_date": date(2025, 7, 1),
                "vt_symbol": "600002.SSE",
            },
        ]
    )


def _full_day(symbol: str = "600001.SSE") -> pd.DataFrame:
    morning = [
        datetime(2025, 7, 2, 9, 35) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime(2025, 7, 2, 13, 5) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    return pd.DataFrame(
        {
            "vt_symbol": symbol,
            "trade_date": date(2025, 7, 2),
            "bar_time": [*morning, *afternoon],
            "interval": "5m",
            "source": "tdx_public_hq",
        }
    )


def test_manifest_reuses_exact_48_bar_contract() -> None:
    manifest = event_neutral_minutes.build_event_neutral_5m_manifest(
        _candidates(),
        _full_day(),
    )

    assert manifest["status"].tolist() == ["complete", "missing"]
    assert manifest["required_bars"].tolist() == [48, 48]


def test_backfill_only_passes_manifest_gaps(monkeypatch) -> None:
    manifest = event_neutral_minutes.build_event_neutral_5m_manifest(
        _candidates(),
        _full_day(),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        event_neutral_minutes,
        "load_event_neutral_5m_manifest",
        lambda: manifest,
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 48, "rows_written": 0}

    monkeypatch.setattr(
        "alphaagent.server.services.data_providers.tdx_minute_import.import_tdx_minute_bars_for_gaps",
        fake_import,
    )

    result = event_neutral_minutes.backfill_missing_event_neutral_5m(
        dry_run=True,
        max_gaps=10,
    )

    assert captured["gaps"] == [
        {
            "vt_symbol": "600002.SSE",
            "trade_date": date(2025, 7, 2),
            "reference_date": date(2025, 7, 1),
            "window": "event_neutral_observation_5m",
        }
    ]
    assert captured["interval"] == "5m"
    assert captured["tail_entry_start"] == "09:35"
    assert captured["tail_entry_end"] == "15:00"
    assert result["manifest_missing_before"] == 1


def test_backfill_cli_exposes_no_offsets_dates_or_windows() -> None:
    args = build_parser().parse_args(
        ["v2-event-neutral-5m-backfill", "--dry-run", "--max-gaps", "10"]
    )

    assert args.command == "v2-event-neutral-5m-backfill"
    assert args.max_gaps == 10
    for parameter in ("offsets", "start", "end", "tail_entry_start"):
        assert not hasattr(args, parameter)
