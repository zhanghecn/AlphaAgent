from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.low_suction.dc_membership_normalization import (
    compress_daily_memberships,
    normalize_dc_snapshot,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_source_session_only_becomes_effective_on_next_session() -> None:
    rows = normalize_dc_snapshot(
        source_trade_date=date(2026, 7, 14),
        effective_trade_date=date(2026, 7, 15),
        sector_id="BK1184",
        sector_name="人形机器人",
        members=[{"con_code": "600001.SH", "name": "A"}],
        fetched_at=datetime(2026, 7, 16, 12, 0, tzinfo=SHANGHAI),
    )

    assert rows[0].source_trade_date == date(2026, 7, 14)
    assert rows[0].effective_trade_date == date(2026, 7, 15)
    assert rows[0].known_at == datetime(2026, 7, 14, 23, 59, tzinfo=SHANGHAI)
    assert rows[0].vt_symbol == "600001.SSE"


def test_normalization_rejects_duplicate_or_unsupported_constituents() -> None:
    duplicate = [
        {"con_code": "600001.SH", "name": "A"},
        {"con_code": "600001.SH", "name": "A again"},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        normalize_dc_snapshot(
            source_trade_date=date(2026, 7, 14),
            effective_trade_date=date(2026, 7, 15),
            sector_id="BK1184",
            sector_name="人形机器人",
            members=duplicate,
        )
    with pytest.raises(ValueError, match="unsupported"):
        normalize_dc_snapshot(
            source_trade_date=date(2026, 7, 14),
            effective_trade_date=date(2026, 7, 15),
            sector_id="BK1184",
            sector_name="人形机器人",
            members=[{"con_code": "US.AAPL", "name": "Apple"}],
        )


def test_disappearing_and_reappearing_member_creates_two_intervals() -> None:
    dates = (
        date(2026, 7, 15),
        date(2026, 7, 16),
        date(2026, 7, 17),
        date(2026, 7, 20),
    )
    rows = []
    for source_date, effective_date in (
        (date(2026, 7, 14), dates[0]),
        (date(2026, 7, 16), dates[2]),
        (date(2026, 7, 17), dates[3]),
    ):
        rows.extend(
            normalize_dc_snapshot(
                source_trade_date=source_date,
                effective_trade_date=effective_date,
                sector_id="BK1184",
                sector_name="人形机器人",
                members=[{"con_code": "600001.SH", "name": "A"}],
            )
        )

    intervals = compress_daily_memberships(
        rows,
        effective_dates=dates,
        terminal_out_date=date(2026, 7, 21),
    )

    assert [(row.in_date, row.out_date) for row in intervals] == [
        (date(2026, 7, 15), date(2026, 7, 16)),
        (date(2026, 7, 17), date(2026, 7, 21)),
    ]
    assert all(row.evidence_level == "strict" for row in intervals)


def test_compression_rejects_rows_outside_declared_calendar() -> None:
    rows = normalize_dc_snapshot(
        source_trade_date=date(2026, 7, 14),
        effective_trade_date=date(2026, 7, 15),
        sector_id="BK1184",
        sector_name="人形机器人",
        members=[{"con_code": "600001.SH", "name": "A"}],
    )

    with pytest.raises(ValueError, match="outside"):
        compress_daily_memberships(
            rows,
            effective_dates=(date(2026, 7, 16),),
            terminal_out_date=date(2026, 7, 17),
        )
