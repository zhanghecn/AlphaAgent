from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from alphaagent.server.api import data_sync as data_sync_api
from alphaagent.server.main import create_app
from alphaagent.server.services import market_snapshot_repository
from alphaagent.server.services.limit_up import historical_membership_import as membership


ELIGIBLE_STOCKS = {
    "600001.SSE": "沪市样本",
    "000001.SZSE": "深市样本",
    "002001.SZSE": "深市二号",
}


def test_membership_intervals_normalize_l2_and_filter_non_main_board() -> None:
    result = membership.normalize_membership_intervals(
        [
            {
                "ts_code": "600001.SH",
                "name": "沪市样本",
                "l1_code": "801080.SI",
                "l1_name": "电子",
                "l2_code": "801081.SI",
                "l2_name": "半导体",
                "in_date": "20240101",
                "out_date": "",
            },
            {
                "ts_code": "300001.SZ",
                "name": "创业板样本",
                "l2_code": "801081.SI",
                "l2_name": "半导体",
                "in_date": "20240101",
            },
            {
                "ts_code": "000002.SZ",
                "name": "*ST样本",
                "l2_code": "801081.SI",
                "l2_name": "半导体",
                "in_date": "20240101",
            },
            {
                "ts_code": "000001.SH",
                "name": "错误交易所样本",
                "l2_code": "801081.SI",
                "l2_name": "半导体",
                "in_date": "20240101",
            },
        ],
        eligible_stocks={**ELIGIBLE_STOCKS, "000001.SSE": "错误交易所样本"},
    )

    assert result["accepted_count"] == 1
    assert result["skipped_count"] == 3
    row = result["rows"][0]
    assert row["vt_symbol"] == "600001.SSE"
    assert row["sector_id"] == "801081.SI"
    assert row["sector_name"] == "半导体"
    assert row["in_date"] == date(2024, 1, 1)
    assert row["out_date"] is None


def test_membership_expansion_treats_out_date_as_exclusive() -> None:
    intervals = membership.normalize_membership_intervals(
        [
            {
                "ts_code": "600001.SH",
                "name": "沪市样本",
                "l2_code": "OLD.SI",
                "l2_name": "旧行业",
                "in_date": "20240101",
                "out_date": "20240103",
            },
            {
                "ts_code": "600001.SH",
                "name": "沪市样本",
                "l2_code": "NEW.SI",
                "l2_name": "新行业",
                "in_date": "20240103",
                "out_date": "",
            },
        ],
        eligible_stocks=ELIGIBLE_STOCKS,
    )["rows"]

    expanded = membership.expand_membership_intervals(
        intervals,
        [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
    )

    assert expanded["rows_by_date"][date(2024, 1, 2)][0]["sector_id"] == "OLD.SI"
    assert expanded["rows_by_date"][date(2024, 1, 3)][0]["sector_id"] == "NEW.SI"
    assert expanded["rows_by_date"][date(2024, 1, 4)][0]["sector_id"] == "NEW.SI"
    assert expanded["conflict_count"] == 0


def test_membership_expansion_resolves_overlap_by_latest_in_date() -> None:
    intervals = membership.normalize_membership_intervals(
        [
            {
                "ts_code": "000001.SZ",
                "name": "深市样本",
                "l2_code": "OLD.SI",
                "l2_name": "旧行业",
                "in_date": "20240101",
            },
            {
                "ts_code": "000001.SZ",
                "name": "深市样本",
                "l2_code": "NEW.SI",
                "l2_name": "新行业",
                "in_date": "20240102",
            },
        ],
        eligible_stocks=ELIGIBLE_STOCKS,
    )["rows"]

    expanded = membership.expand_membership_intervals(
        intervals,
        [date(2024, 1, 3)],
    )

    assert expanded["rows_by_date"][date(2024, 1, 3)][0]["sector_id"] == "NEW.SI"
    assert expanded["conflict_count"] == 1


def test_membership_tushare_import_requires_token(monkeypatch) -> None:
    monkeypatch.setattr(membership, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        membership,
        "get_settings",
        lambda: SimpleNamespace(
            tushare_token="",
            tushare_api_url="https://api.tushare.pro",
            tushare_timeout_seconds=1,
        ),
    )

    result = membership.import_tushare_memberships(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        max_dates=20,
        dry_run=True,
    )

    assert result["status"] == "unavailable"
    assert "TUSHARE_TOKEN" in result["message"]


def test_membership_tushare_query_rejects_any_empty_l1_response(monkeypatch) -> None:
    def fake_query(api_name, **kwargs):
        if api_name == "index_classify":
            return [{"index_code": "801010.SI"}, {"index_code": "801020.SI"}]
        if kwargs["params"]["l1_code"] == "801010.SI":
            return [{"ts_code": "600001.SH"}]
        return []

    monkeypatch.setattr(membership, "_query_tushare_api", fake_query)

    with pytest.raises(
        membership.TushareMembershipQueryError,
        match="801020.SI",
    ):
        membership.query_tushare_membership_intervals(
            token="token",
            api_url="https://api.tushare.pro",
            timeout=1,
        )


def test_membership_status_reads_membership_coverage_without_full_gate(monkeypatch) -> None:
    monkeypatch.setattr(membership, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        membership,
        "get_settings",
        lambda: SimpleNamespace(
            tushare_token="",
            tushare_api_url="https://api.tushare.pro",
        ),
    )
    monkeypatch.setattr(
        membership.data_quality_repository,
        "load_membership_data_quality_counts",
        lambda: {"point_in_time_trade_days": 12, "industry_rows": 40_000},
    )

    result = membership.historical_membership_status()

    assert result["provider"]["configured"] is False
    assert result["dataset"]["coverage"] == {
        "point_in_time_trade_days": 12,
        "industry_rows": 40_000,
    }


def test_industry_scoped_snapshot_replacement_preserves_other_sector_types(monkeypatch) -> None:
    statements: list[object] = []

    class FakeSession:
        def execute(self, statement):
            statements.append(statement)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(market_snapshot_repository, "session_scope", fake_session_scope)
    written = market_snapshot_repository.replace_stock_sector_membership_snapshot_scope(
        [
            {
                "vt_symbol": "600001.SSE",
                "sector_id": "801081.SI",
                "sector_name": "半导体",
                "sector_type": "industry",
                "rank": 2,
                "source": "tushare.index_member_all",
            }
        ],
        snapshot_date=date(2024, 1, 2),
        captured_at=datetime(2026, 7, 11, tzinfo=timezone.utc),
        sector_type="industry",
    )

    delete_sql = str(
        statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert written == 1
    assert "snapshot_date = '2024-01-02'" in delete_sql
    assert "sector_type = 'industry'" in delete_sql


def test_historical_membership_api_contracts(monkeypatch) -> None:
    monkeypatch.setattr(
        data_sync_api.historical_membership_import,
        "historical_membership_status",
        lambda: {"provider": {"configured": False}, "dataset": {}},
    )
    monkeypatch.setattr(
        data_sync_api.historical_membership_import,
        "import_tushare_memberships",
        lambda **kwargs: {"status": "unavailable", "dry_run": kwargs["dry_run"]},
    )
    client = TestClient(create_app())

    status = client.get("/api/data-sync/imports/limit-up-memberships/status")
    template = client.get("/api/data-sync/imports/limit-up-memberships/template.csv")
    tushare = client.post(
        "/api/data-sync/imports/limit-up-memberships/tushare",
        json={
            "start_date": "2024-01-15",
            "end_date": "2024-01-31",
            "dry_run": True,
            "max_dates": 20,
            "only_missing": True,
        },
    )
    csv_import = client.post(
        "/api/data-sync/imports/limit-up-memberships/csv",
        json={
            "start_date": "2024-01-15",
            "end_date": "2024-01-31",
            "csv_text": "x",
            "dry_run": True,
            "max_dates": 20,
            "only_missing": False,
        },
    )

    assert status.status_code == 200
    assert status.json()["data"]["provider"]["configured"] is False
    assert template.status_code == 404
    assert tushare.status_code == 200
    assert tushare.json()["data"]["status"] == "unavailable"
    assert csv_import.status_code == 404


def test_historical_membership_csv_service_is_removed() -> None:
    assert not hasattr(membership, "import_membership_csv")
    assert not hasattr(membership, "membership_csv_template")


def test_historical_membership_api_rejects_invalid_date() -> None:
    response = TestClient(create_app()).post(
        "/api/data-sync/imports/limit-up-memberships/tushare",
        json={"start_date": "not-a-date", "end_date": "2024-01-31"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_LIMIT_UP_MEMBERSHIP_IMPORT"
