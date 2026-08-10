"""Tests for persisted low-suction live scan diagnostics."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import live_scan_repository


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_live_scan_table_is_registered() -> None:
    assert "low_suction_live_scan_runs" in schema.metadata.tables


def test_live_scan_serialization_calculates_scan_intervals() -> None:
    first_started = datetime(2026, 8, 10, 9, 30, tzinfo=SHANGHAI)
    second_started = datetime(2026, 8, 10, 10, 0, tzinfo=SHANGHAI)

    runs = live_scan_repository._serialize_runs(
        [
            {
                "id": 11,
                "trade_date": date(2026, 8, 10),
                "started_at": first_started,
                "finished_at": datetime(2026, 8, 10, 9, 30, 4, tzinfo=SHANGHAI),
                "duration_ms": 4_000,
                "status": "ok",
                "provisional": True,
                "spot_active_symbols": 5_011,
                "trend_count": 2,
                "oversold_count": 4,
                "score_version": "low-suction-daily-score-v3",
                "merge_note": "盘中虚拟K线",
                "error": None,
            },
            {
                "id": 12,
                "trade_date": date(2026, 8, 10),
                "started_at": second_started,
                "finished_at": datetime(2026, 8, 10, 10, 0, 2, tzinfo=SHANGHAI),
                "duration_ms": 2_000,
                "status": "error",
                "provisional": None,
                "spot_active_symbols": None,
                "trend_count": None,
                "oversold_count": None,
                "score_version": "low-suction-daily-score-v3",
                "merge_note": None,
                "error": "RuntimeError: provider unavailable",
            },
        ]
    )

    assert runs[0]["interval_seconds"] is None
    assert runs[0]["spot_active_symbols"] == 5_011
    assert runs[1]["interval_seconds"] == 1_800
    assert runs[1]["status"] == "error"
    assert runs[1]["error"] == "RuntimeError: provider unavailable"
