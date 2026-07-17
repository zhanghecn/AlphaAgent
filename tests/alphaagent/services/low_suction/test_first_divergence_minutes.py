from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from alphaagent.server.services.low_suction import first_divergence_minutes
from alphaagent.server.services.low_suction.cli import build_parser


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 7, 3),
                "entry_date": date(2025, 7, 4),
                "vt_symbol": "600001.SSE",
            },
            {
                "event_id": 2,
                "source_date": date(2025, 7, 3),
                "entry_date": date(2025, 7, 4),
                "vt_symbol": "600002.SSE",
            },
        ]
    )


def _full_day(symbol: str = "600001.SSE") -> pd.DataFrame:
    morning = [
        datetime(2025, 7, 4, 9, 35) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime(2025, 7, 4, 13, 5) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    return pd.DataFrame(
        {
            "vt_symbol": symbol,
            "trade_date": date(2025, 7, 4),
            "bar_time": [*morning, *afternoon],
            "interval": "5m",
            "source": "tdx_public_hq",
        }
    )


def test_manifest_reuses_exact_48_bar_contract() -> None:
    manifest = first_divergence_minutes.build_first_divergence_5m_manifest(
        _candidates(),
        _full_day(),
    )

    assert manifest["status"].tolist() == ["complete", "missing"]
    assert manifest["required_bars"].tolist() == [48, 48]


def test_backfill_only_uses_manifest_discovered_pairs(monkeypatch) -> None:
    manifest = first_divergence_minutes.build_first_divergence_5m_manifest(
        _candidates(),
        _full_day(),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        first_divergence_minutes,
        "load_first_divergence_5m_manifest",
        lambda: manifest,
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 48, "rows_written": 0}

    monkeypatch.setattr(
        "alphaagent.server.services.data_providers.tdx_minute_import.import_tdx_minute_bars_for_gaps",
        fake_import,
    )

    result = first_divergence_minutes.backfill_missing_first_divergence_5m(
        dry_run=True,
        max_gaps=10,
    )

    assert captured["gaps"] == [
        {
            "vt_symbol": "600002.SSE",
            "trade_date": date(2025, 7, 4),
            "reference_date": date(2025, 7, 3),
            "window": "first_divergence_observation_5m",
        }
    ]
    assert captured["interval"] == "5m"
    assert captured["tail_entry_start"] == "09:35"
    assert captured["tail_entry_end"] == "15:00"
    assert result["manifest_missing_before"] == 1


def test_manifest_cli_exposes_no_custom_dates_or_windows() -> None:
    args = build_parser().parse_args(
        ["v2-first-divergence-5m-backfill", "--dry-run", "--max-gaps", "10"]
    )

    assert args.command == "v2-first-divergence-5m-backfill"
    assert args.max_gaps == 10
    assert not hasattr(args, "start")
    assert not hasattr(args, "tail_entry_start")
