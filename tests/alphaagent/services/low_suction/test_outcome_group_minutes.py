from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from alphaagent.server.services.low_suction import outcome_group_minutes
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


def _full_day() -> pd.DataFrame:
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
            "vt_symbol": "600001.SSE",
            "trade_date": date(2025, 7, 2),
            "bar_time": [*morning, *afternoon],
            "interval": "5m",
            "source": "tdx_public_hq",
        }
    )


def test_manifest_reuses_exact_candidate_only_48_bar_contract() -> None:
    manifest = outcome_group_minutes.build_outcome_group_5m_manifest(
        _candidates(),
        _full_day(),
    )

    assert manifest["status"].tolist() == ["complete", "missing"]
    assert manifest["required_bars"].tolist() == [48, 48]
    assert manifest["context_date"].tolist() == [date(2025, 7, 1)] * 2


def test_backfill_only_passes_comparison_manifest_gaps(monkeypatch) -> None:
    manifest = outcome_group_minutes.build_outcome_group_5m_manifest(
        _candidates(),
        _full_day(),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        outcome_group_minutes,
        "load_outcome_group_5m_manifest",
        lambda: manifest,
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 48, "rows_written": 0}

    monkeypatch.setattr(
        "alphaagent.server.services.data_providers.tdx_minute_import.import_tdx_minute_bars_for_gaps",
        fake_import,
    )

    result = outcome_group_minutes.backfill_missing_outcome_group_5m(
        dry_run=True,
        max_gaps=10,
    )

    assert captured["gaps"] == [
        {
            "vt_symbol": "600002.SSE",
            "trade_date": date(2025, 7, 2),
            "reference_date": date(2025, 7, 1),
            "window": "outcome_group_observation_5m",
        }
    ]
    assert result["dataset"] == "low_suction_outcome_group_observation_5m"
    assert result["manifest_missing_before"] == 1


def test_manifest_and_backfill_cli_expose_no_research_knobs() -> None:
    manifest = build_parser().parse_args(
        ["v2-outcome-group-5m-manifest", "--format", "json"]
    )
    backfill = build_parser().parse_args(
        ["v2-outcome-group-5m-backfill", "--dry-run", "--max-gaps", "10"]
    )

    assert manifest.command == "v2-outcome-group-5m-manifest"
    assert backfill.command == "v2-outcome-group-5m-backfill"
    for args in (manifest, backfill):
        for parameter in ("offsets", "start", "end", "entry_depth"):
            assert not hasattr(args, parameter)
