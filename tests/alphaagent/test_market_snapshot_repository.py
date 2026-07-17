from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.db import schema
from alphaagent.server.services import market_snapshot_repository


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _membership(
    sector_id: str,
    sector_type: str,
    *,
    vt_symbol: str = "600000.SSE",
    source: str = "eastmoney.push2.board",
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "sector_id": sector_id,
        "sector_name": sector_id,
        "sector_type": sector_type,
        "source": source,
    }


def _sector(sector_id: str, sector_type: str) -> dict[str, str]:
    return {"id": sector_id, "type": sector_type}


def test_sector_fund_flow_rows_freeze_capture_minute_and_staleness() -> None:
    captured_at = datetime(2026, 7, 13, 10, 30, 42, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_sector_fund_flow_snapshot_rows(
        [
            {
                "id": "BK0963",
                "name": "商业航天",
                "trade_date": "2026-07-13",
                "main_net_inflow": 11_085_815_808,
                "main_net_inflow_pct": 3.26,
                "rank": 1,
                "rise_count": 60,
                "fall_count": 35,
                "flat_count": 5,
                "source_updated_at": "2026-07-13T10:30:30+08:00",
                "source": "eastmoney.sector_fund_flow_rank",
                "raw": {"updated_timestamp": 1783919430},
            }
        ],
        period="即时",
        sector_type="concept",
        captured_at=captured_at,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["trade_date"] == date(2026, 7, 13)
    assert row["captured_at"] == captured_at.astimezone(timezone.utc)
    assert row["captured_minute"] == datetime(2026, 7, 13, 2, 30, tzinfo=timezone.utc)
    assert row["session_stage"] == "morning"
    assert row["is_stale"] is False
    assert row["rise_ratio"] == 60.0
    assert row["source_updated_at"] == datetime(2026, 7, 13, 2, 30, 30, tzinfo=timezone.utc)


def test_sector_fund_flow_rows_mark_previous_trade_date_as_stale() -> None:
    rows = market_snapshot_repository.build_sector_fund_flow_snapshot_rows(
        [{"id": "BK0001", "trade_date": "2026-07-10"}],
        period="即时",
        sector_type="industry",
        captured_at=datetime(2026, 7, 13, 10, 30, tzinfo=SHANGHAI),
    )

    assert rows[0]["is_stale"] is True


def test_auction_rows_preserve_partial_public_quote_without_claiming_strict_l2() -> None:
    captured_at = datetime(2026, 7, 13, 9, 26, 15, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_stock_auction_snapshot_rows(
        [
            {
                "vt_symbol": "600000.SSE",
                "symbol": "600000",
                "exchange": "SSE",
                "name": "浦发银行",
                "open_price": 10.2,
                "previous_close": 10.0,
                "volume": 120_000,
                "turnover": 1_224_000,
                "trade_time": "09:25:03",
                "source": "sina.market_center.hs_a",
                "raw": {"ticktime": "09:25:03"},
            }
        ],
        trade_date=date(2026, 7, 13),
        captured_at=captured_at,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["auction_price"] == 10.2
    assert row["auction_change_pct"] == 2.0
    assert row["matched_volume"] == 120_000
    assert row["matched_amount"] == 1_224_000
    assert row["unmatched_volume"] is None
    assert row["strict_complete"] is False
    assert row["source_updated_at"] == datetime(2026, 7, 13, 1, 25, 3, tzinfo=timezone.utc)


def test_no_match_auction_can_be_strict_when_the_provider_proves_zero_match_and_queue() -> None:
    rows = market_snapshot_repository.build_stock_auction_snapshot_rows(
        [
            {
                "vt_symbol": "600001.SSE",
                "name": "示例股票",
                "auction_status": "no_match",
                "matched_volume": 0,
                "matched_amount": 0,
                "unmatched_volume": 0,
                "unmatched_side": "balanced",
                "source_updated_at": "2026-07-13T09:25:05+08:00",
            }
        ],
        trade_date=date(2026, 7, 13),
        captured_at=datetime(2026, 7, 13, 9, 26, tzinfo=SHANGHAI),
    )

    assert rows[0]["auction_price"] is None
    assert rows[0]["strict_complete"] is True


def test_membership_rows_keep_the_capture_date_as_a_separate_version() -> None:
    captured_at = datetime(2026, 7, 13, 19, 8, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_stock_sector_membership_snapshot_rows(
        [
            {
                "vt_symbol": "600000.SSE",
                "sector_id": "BK0475",
                "sector_name": "银行",
                "sector_type": "industry",
                "source": "akshare",
            }
        ],
        snapshot_date=date(2026, 7, 13),
        captured_at=captured_at,
    )

    assert rows[0]["snapshot_date"] == date(2026, 7, 13)
    assert rows[0]["captured_at"] == captured_at.astimezone(timezone.utc)


def test_large_membership_snapshots_are_split_below_postgres_parameter_limit() -> None:
    chunks = list(
        market_snapshot_repository._row_chunks(
            [{"row": index} for index in range(1_201)],
            chunk_size=500,
        )
    )

    assert [len(chunk) for chunk in chunks] == [500, 500, 201]


def test_complete_membership_scope_combines_concept_and_theme() -> None:
    captured_at = datetime(2026, 7, 16, 19, 8, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_stock_sector_membership_snapshot_rows(
        [
            _membership("BK0001", "concept"),
            _membership("BK0002", "theme", vt_symbol="000001.SZSE"),
            _membership("BK1001", "industry"),
        ],
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    scopes = market_snapshot_repository.build_membership_snapshot_scopes(
        rows,
        expected_sectors=[
            _sector("BK0001", "concept"),
            _sector("BK0002", "theme"),
            _sector("BK1001", "industry"),
        ],
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    assert [scope["scope_type"] for scope in scopes] == ["concept", "industry"]
    concept = scopes[0]
    assert concept["expected_sector_count"] == 2
    assert concept["captured_sector_count"] == 2
    assert concept["row_count"] == 2
    assert concept["symbol_count"] == 2
    assert concept["complete"] is True
    assert concept["evidence_level"] == "strict"
    assert concept["source"] == "eastmoney.push2.board"


def test_membership_scope_explicitly_excludes_unavailable_sectors() -> None:
    captured_at = datetime(2026, 7, 16, 19, 8, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_stock_sector_membership_snapshot_rows(
        [
            _membership("BK0001", "concept"),
            _membership("BK1001", "industry"),
        ],
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    scopes = market_snapshot_repository.build_membership_snapshot_scopes(
        rows,
        expected_sectors=[
            _sector("BK0001", "concept"),
            _sector("BK0002", "theme"),
            _sector("BK1001", "industry"),
        ],
        excluded_sector_ids=("BK0002",),
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    concept = scopes[0]
    assert concept["expected_sector_count"] == 1
    assert concept["captured_sector_count"] == 1
    assert concept["complete"] is True
    assert concept["evidence_level"] == "strict_exclusions"
    assert concept["raw"]["catalog_expected_sector_count"] == 2
    assert concept["raw"]["excluded_sector_ids"] == ["BK0002"]


def test_membership_snapshot_rejects_a_missing_expected_sector() -> None:
    captured_at = datetime(2026, 7, 16, 19, 8, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_stock_sector_membership_snapshot_rows(
        [_membership("BK0001", "concept")],
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    with pytest.raises(
        market_snapshot_repository.IncompleteMembershipSnapshotError,
        match="BK0002",
    ):
        market_snapshot_repository.build_membership_snapshot_scopes(
            rows,
            expected_sectors=[
                _sector("BK0001", "concept"),
                _sector("BK0002", "concept"),
            ],
            snapshot_date=date(2026, 7, 16),
            captured_at=captured_at,
        )


def test_membership_snapshot_rejects_mixed_sources() -> None:
    captured_at = datetime(2026, 7, 16, 19, 8, tzinfo=SHANGHAI)
    rows = market_snapshot_repository.build_stock_sector_membership_snapshot_rows(
        [
            _membership("BK0001", "concept"),
            _membership("BK1001", "industry", source="another.provider"),
        ],
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    with pytest.raises(
        market_snapshot_repository.IncompleteMembershipSnapshotError,
        match="one source",
    ):
        market_snapshot_repository.build_membership_snapshot_scopes(
            rows,
            expected_sectors=[
                _sector("BK0001", "concept"),
                _sector("BK1001", "industry"),
            ],
            snapshot_date=date(2026, 7, 16),
            captured_at=captured_at,
        )


def test_membership_snapshot_scope_table_has_one_row_per_date_and_scope() -> None:
    table = schema.stock_sector_membership_snapshot_scopes

    assert table.name == "stock_sector_membership_snapshot_scopes"
    assert [column.name for column in table.primary_key.columns] == [
        "snapshot_date",
        "scope_type",
    ]


def test_membership_rows_and_scopes_are_replaced_in_one_transaction(
    monkeypatch,
) -> None:
    sessions: list[object] = []

    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def execute(self, statement):
            self.calls.append(statement)
            return None

    @contextmanager
    def fake_scope():
        session = FakeSession()
        sessions.append(session)
        yield session

    monkeypatch.setattr(market_snapshot_repository, "session_scope", fake_scope)
    captured_at = datetime(2026, 7, 16, 19, 8, tzinfo=SHANGHAI)

    written = market_snapshot_repository.save_stock_sector_membership_snapshots(
        [
            _membership("BK0001", "concept"),
            _membership("BK1001", "industry"),
        ],
        expected_sectors=[
            _sector("BK0001", "concept"),
            _sector("BK1001", "industry"),
        ],
        snapshot_date=date(2026, 7, 16),
        captured_at=captured_at,
    )

    assert written == 2
    assert len(sessions) == 1
    sql = [str(statement) for statement in sessions[0].calls]
    assert sql[0].startswith("DELETE FROM stock_sector_membership_snapshots")
    assert sql[1].startswith("DELETE FROM stock_sector_membership_snapshot_scopes")
    assert "INSERT INTO stock_sector_membership_snapshots" in sql[2]
    assert "INSERT INTO stock_sector_membership_snapshot_scopes" in sql[3]
