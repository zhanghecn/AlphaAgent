from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.capital_mainline_contract import EvidenceLevel
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CANONICAL_CONCEPT_SOURCE,
    CapitalMainlineInputs,
    flow_is_known_for_next_session,
    fund_flow_known_at,
    membership_rows_for_date,
)


def _inputs() -> CapitalMainlineInputs:
    return CapitalMainlineInputs(
        trade_dates=(date(2026, 7, 16), date(2026, 7, 17)),
        concept_bars=(),
        sector_fund_flows=(),
        stock_fund_flows=(),
        memberships=(
            {
                "snapshot_date": date(2026, 7, 16),
                "vt_symbol": "600001.SSE",
                "sector_id": "BK0001",
            },
        ),
        membership_scopes=(
            {"snapshot_date": date(2026, 7, 16), "complete": True},
        ),
        membership_counts=(),
        current_memberships=(
            {"vt_symbol": "600002.SSE", "sector_id": "BK9999"},
        ),
        stock_bars=(),
        limit_up_events=(),
        sentiment_points=(),
        formal_candidate_days=(),
        coverage={},
        fingerprints={},
    )


def test_repository_uses_canonical_concept_source() -> None:
    assert CANONICAL_CONCEPT_SOURCE == "eastmoney.board_kline"


def test_membership_snapshot_must_precede_trade_date() -> None:
    rows, evidence, snapshot_date = membership_rows_for_date(
        _inputs(),
        date(2026, 7, 17),
    )
    assert rows[0]["sector_id"] == "BK0001"
    assert evidence is EvidenceLevel.POINT_IN_TIME
    assert snapshot_date == date(2026, 7, 16)

    rows, evidence, snapshot_date = membership_rows_for_date(
        _inputs(),
        date(2026, 7, 16),
    )
    assert rows[0]["sector_id"] == "BK9999"
    assert evidence is EvidenceLevel.CURRENT_MEMBERSHIP_PROXY
    assert snapshot_date is None


def test_fund_known_at_prefers_source_timestamp_over_row_creation() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    row = {
        "created_at": datetime(2026, 7, 24, 9, 30, tzinfo=shanghai),
        "updated_at": datetime(2026, 7, 24, 21, 30, tzinfo=shanghai),
        "raw": {"source_updated_at": "2026-07-24T07:39:31+00:00"},
    }
    assert fund_flow_known_at(row) == datetime(
        2026,
        7,
        24,
        15,
        39,
        31,
        tzinfo=shanghai,
    )
    assert flow_is_known_for_next_session(row, date(2026, 7, 27))


def test_same_day_close_flow_is_not_known_at_open() -> None:
    row = {"raw": {"source_updated_at": "2026-07-24T07:39:31+00:00"}}
    assert not flow_is_known_for_next_session(row, date(2026, 7, 24))
