from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from alphaagent.server.api import data_sync as data_sync_api
from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import historical_evidence_import as evidence
from alphaagent.server.services.limit_up import historical_evidence_batch as ths_batch
from alphaagent.server.services.limit_up.repository import normalize_event_row


ELIGIBLE_STOCKS = {
    "600001.SSE": "沪市样本",
    "000001.SZSE": "深市样本",
    "002001.SZSE": "深市二号",
}


def test_tushare_event_rows_map_path_fields_and_filter_non_main_board() -> None:
    result = evidence.normalize_event_rows(
        [
            {
                "trade_date": "20260710",
                "ts_code": "600001.SH",
                "name": "沪市样本",
                "limit": "U",
                "first_time": "093305",
                "last_time": "143152",
                "open_times": 2,
                "fd_amount": 128_000_000,
                "limit_times": 2,
                "industry": "通信设备",
                "turnover_ratio": 12.4,
            },
            {
                "trade_date": "20260710",
                "ts_code": "300001.SZ",
                "name": "创业板样本",
                "limit": "U",
                "first_time": "100000",
            },
            {
                "trade_date": "20260710",
                "ts_code": "000002.SZ",
                "name": "*ST样本",
                "limit": "Z",
                "first_time": "101000",
            },
        ],
        expected_date=date(2026, 7, 10),
        eligible_stocks=ELIGIBLE_STOCKS,
    )

    assert result["accepted_count"] == 1
    assert result["skipped_count"] == 2
    row = result["rows"][0]
    assert row["vt_symbol"] == "600001.SSE"
    assert row["event_type"] == "limit_pool_zt"
    assert row["raw"]["首次封板时间"] == "093305"
    assert row["raw"]["最后封板时间"] == "143152"
    assert row["raw"]["炸板次数"] == 2
    assert row["raw"]["封板资金"] == 128_000_000
    assert row["raw"]["连板数"] == 2


def test_event_normalizer_rejects_cross_date_and_deduplicates_symbol_pool() -> None:
    base = {
        "trade_date": "20260710",
        "ts_code": "000001.SZ",
        "name": "深市样本",
        "limit": "Z",
        "first_time": "101500",
        "open_times": 1,
    }
    result = evidence.normalize_event_rows(
        [base, {**base, "open_times": 3}, {**base, "trade_date": "20260709"}],
        expected_date=date(2026, 7, 10),
        eligible_stocks=ELIGIBLE_STOCKS,
    )

    assert result["accepted_count"] == 1
    assert result["duplicate_count"] == 1
    assert result["error_count"] == 1
    assert result["rows"][0]["raw"]["炸板次数"] == 3


def test_event_normalizer_preserves_zero_open_count() -> None:
    result = evidence.normalize_event_rows(
        [
            {
                "trade_date": "20260710",
                "ts_code": "600001.SH",
                "name": "沪市样本",
                "limit": "U",
                "first_time": "093305",
                "last_time": "093305",
                "open_times": 0,
                "fd_amount": 0,
                "limit_times": 1,
            }
        ],
        expected_date=date(2026, 7, 10),
        eligible_stocks=ELIGIBLE_STOCKS,
    )

    assert result["rows"][0]["raw"]["炸板次数"] == 0
    assert result["rows"][0]["raw"]["封板资金"] == 0


def test_tushare_auction_rows_remain_partial_without_unmatched_queue() -> None:
    result = evidence.normalize_auction_rows(
        [
            {
                "trade_date": "20260710",
                "ts_code": "002001.SZ",
                "price": 10.45,
                "pre_close": 10.0,
                "vol": 320_000,
                "amount": 3_344_000,
                "turnover_rate": 0.8,
                "volume_ratio": 2.1,
            }
        ],
        expected_date=date(2026, 7, 10),
        eligible_stocks=ELIGIBLE_STOCKS,
    )

    assert result["accepted_count"] == 1
    row = result["rows"][0]
    assert row["vt_symbol"] == "002001.SZSE"
    assert row["auction_price"] == 10.45
    assert row["matched_volume"] == 320_000
    assert row["matched_amount"] == 3_344_000
    assert row["unmatched_volume"] is None
    assert row["source_quote_time"] == "09:25:00"
    assert row["source"] == "tushare.stk_auction"


def test_tushare_import_requires_token_before_querying(monkeypatch) -> None:
    monkeypatch.setattr(evidence, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        evidence,
        "get_settings",
        lambda: SimpleNamespace(
            tushare_token="",
            tushare_api_url="https://api.tushare.pro",
            tushare_timeout_seconds=1,
        ),
    )

    result = evidence.import_tushare_evidence(
        dataset="events",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 10),
        dry_run=True,
        max_dates=10,
    )

    assert result["status"] == "unavailable"
    assert result["provider"] == "tushare"
    assert "TUSHARE_TOKEN" in result["message"]


def test_event_replacement_uses_one_transaction(monkeypatch) -> None:
    calls: list[object] = []

    class FakeSession:
        def execute(self, statement):
            calls.append(statement)

    @contextmanager
    def fake_session_scope():
        calls.append("enter")
        yield FakeSession()
        calls.append("exit")

    monkeypatch.setattr(evidence, "session_scope", fake_session_scope)
    written = evidence.replace_event_evidence(
        date(2026, 7, 10),
        [
            {
                "vt_symbol": "600001.SSE",
                "name": "沪市样本",
                "event_type": "limit_pool_zt",
                "raw": {"首次封板时间": "093305"},
            }
        ],
    )

    assert written == 1
    assert calls[0] == "enter"
    assert calls[-1] == "exit"
    assert len(calls) == 4


def test_tushare_query_uses_dataset_specific_api_and_never_returns_token(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "fields": ["trade_date", "ts_code", "limit"],
                    "items": [["20260710", "600001.SH", "U"]],
                },
            }

    def fake_post(url, *, json, timeout):
        captured.update({"url": url, "payload": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(evidence.requests, "post", fake_post)
    rows = evidence.query_tushare_evidence(
        "events",
        trade_date=date(2026, 7, 10),
        token="secret-token",
        api_url="https://api.tushare.pro",
        timeout=2,
    )

    assert rows == [{"trade_date": "20260710", "ts_code": "600001.SH", "limit": "U"}]
    assert captured["payload"]["api_name"] == "limit_list_d"
    assert "secret-token" not in str(rows)


def test_ths_pool_rows_map_epoch_times_board_height_and_failed_open_count() -> None:
    rows = evidence.ths_pool_rows_to_source_rows(
        trade_date=date(2026, 7, 10),
        limit_up_rows=[
            {
                "code": "601608",
                "name": "沪市样本",
                "first_limit_up_time": "1783666600",
                "last_limit_up_time": "1783666600",
                "open_num": None,
                "order_amount": 37_812_585,
                "order_volume": 7_502_497,
                "high_days": "3天2板",
                "latest": 5.04,
                "change_rate": 10.0437,
                "turnover_rate": 1.7031,
                "turnover": 376_969_930,
                "reason_type": "商业航天",
                "limit_up_type": "换手板",
                "limit_up_suc_rate": 1.0,
                "currency_value": 23_080_949_000,
                "time_preview": [1.0, 10.0437],
            }
        ],
        open_limit_rows=[
            {
                "code": "002001",
                "name": "深市二号",
                "first_limit_up_time": "1783652781",
                "last_limit_up_time": "1783666800",
                "open_num": None,
                "order_amount": 0,
                "high_days": "首板",
            }
        ],
    )

    sealed, failed = rows
    assert sealed["first_time"] == "14:56:40"
    assert sealed["open_times"] == 0
    assert sealed["limit_times"] == 2
    assert sealed["source"] == "ths.limit_up_pool"
    assert sealed["涨停原因"] == "商业航天"
    assert sealed["分时路径"] == [1.0, 10.0437]
    assert failed["limit_type"] == "Z"
    assert failed["open_times"] == 1
    assert failed["limit_times"] == 1
    assert failed["source"] == "ths.open_limit_pool"


def test_repository_exposes_original_historical_provider() -> None:
    normalized = normalize_event_row(
        {
            "vt_symbol": "600001.SSE",
            "event_date": "20260710",
            "event_type": "limit_pool_zt",
            "source": evidence.CANONICAL_EVENT_SOURCE,
            "raw": {
                "名称": "沪市样本",
                "首次封板时间": "09:33:05",
                "历史证据来源": "ths.limit_up_pool",
            },
        }
    )

    assert normalized["source"] == "ths.limit_up_pool"


def test_ths_pool_query_reads_all_pages_and_rejects_wrong_date() -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    class FakeSession:
        def __init__(self, response_date: str = "20260710"):
            self.response_date = response_date

        def get(self, _url, *, headers, params, timeout):
            calls.append({"headers": headers, "params": dict(params), "timeout": timeout})
            page = int(params["page"])
            return FakeResponse(
                {
                    "status_code": 0,
                    "status_msg": "success",
                    "data": {
                        "date": self.response_date,
                        "page": {"page": page, "limit": 1, "total": 2, "count": 2},
                        "info": [{"code": f"60000{page}"}],
                    },
                }
            )

    rows = evidence.query_ths_event_pool(
        "limit_up",
        trade_date=date(2026, 7, 10),
        session=FakeSession(),
        timeout=2,
        page_size=1,
    )

    assert [row["code"] for row in rows] == ["600001", "600002"]
    assert [call["params"]["page"] for call in calls] == [1, 2]
    assert calls[0]["headers"]["Referer"] == evidence.THS_REFERER

    with pytest.raises(evidence.ThsQueryError, match="date mismatch"):
        evidence.query_ths_event_pool(
            "limit_up",
            trade_date=date(2026, 7, 10),
            session=FakeSession("20260709"),
            page_size=1,
        )


def test_ths_import_writes_only_dates_that_pass_coverage(monkeypatch) -> None:
    first_date = date(2026, 7, 9)
    failed_date = date(2026, 7, 10)
    writes: list[tuple[date, int]] = []
    progress: list[dict[str, object]] = []
    monkeypatch.setattr(evidence, "is_database_configured", lambda: True)
    monkeypatch.setattr(evidence, "_require_database", lambda: None)
    monkeypatch.setattr(evidence, "load_eligible_stocks", lambda: ELIGIBLE_STOCKS)
    monkeypatch.setattr(
        evidence,
        "select_ths_import_dates",
        lambda **_kwargs: [first_date, failed_date],
    )
    monkeypatch.setattr(
        evidence,
        "load_expected_event_symbols",
        lambda _dates, **_kwargs: {
            first_date: {"600001.SSE"},
            failed_date: {"000001.SZSE"},
        },
    )

    def fake_query(*, trade_date, **_kwargs):
        if trade_date == failed_date:
            raise evidence.ThsQueryError("date参数不合法")
        return {
            "limit_up": [
                {
                    "code": "600001",
                    "name": "沪市样本",
                    "first_limit_up_time": "1783579800",
                    "last_limit_up_time": "1783579800",
                    "high_days": "首板",
                }
            ],
            "open_limit": [],
        }

    monkeypatch.setattr(evidence, "query_ths_event_pools", fake_query)
    monkeypatch.setattr(
        evidence,
        "replace_event_evidence",
        lambda trade_date, rows: writes.append((trade_date, len(rows))) or len(rows),
    )

    result = evidence.import_ths_evidence(
        max_dates=2,
        only_missing=True,
        request_delay_seconds=0,
        http_session=object(),
        progress=progress.append,
    )

    assert result["status"] == "partial"
    assert result["accepted_date_count"] == 1
    assert result["provider_error_count"] == 1
    assert result["rows_written"] == 1
    assert writes == [(first_date, 1)]
    assert result["date_results"][1]["status"] == "provider_error"
    assert progress[-1]["progress_current"] == 2


def test_ths_batch_service_starts_only_the_internal_import_job(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_start_sync_batch(**kwargs):
        captured.update(kwargs)
        return {
            "id": "ths-batch-1",
            "status": "running",
            "jobs": [{"job_id": ths_batch.JOB_ID, "status": "running"}],
        }

    monkeypatch.setattr(ths_batch.data_sync, "start_sync_batch", fake_start_sync_batch)
    batch = ths_batch.start_ths_evidence_batch(max_dates=252, only_missing=True)

    assert batch["id"] == "ths-batch-1"
    assert captured == {
        "job_ids": [ths_batch.JOB_ID],
        "params": {
            "jobs": {
                ths_batch.JOB_ID: {"max_dates": 252, "only_missing": True}
            }
        },
        "concurrency": 1,
        "source": "manual",
    }


def test_historical_evidence_api_contracts(monkeypatch) -> None:
    monkeypatch.setattr(
        data_sync_api.historical_evidence_import,
        "historical_evidence_status",
        lambda: {"provider": {"configured": False}, "datasets": {}},
    )
    monkeypatch.setattr(
        data_sync_api.historical_evidence_import,
        "import_tushare_evidence",
        lambda **kwargs: {"status": "unavailable", "dataset": kwargs["dataset"]},
    )
    client = TestClient(create_app())

    status = client.get("/api/data-sync/imports/limit-up-evidence/status")
    template = client.get("/api/data-sync/imports/limit-up-evidence/template.csv?dataset=auction")
    tushare = client.post(
        "/api/data-sync/imports/limit-up-evidence/tushare",
        json={
            "dataset": "events",
            "start_date": "2026-07-01",
            "end_date": "2026-07-10",
            "dry_run": True,
            "max_dates": 10,
        },
    )
    csv_import = client.post(
        "/api/data-sync/imports/limit-up-evidence/csv",
        json={"dataset": "auction", "csv_text": "x", "dry_run": True},
    )

    assert status.status_code == 200
    assert status.json()["data"]["provider"]["configured"] is False
    assert template.status_code == 404
    assert tushare.status_code == 200
    assert tushare.json()["data"]["status"] == "unavailable"
    assert csv_import.status_code == 404


def test_manual_csv_and_file_data_sync_routes_are_not_exposed() -> None:
    client = TestClient(create_app())
    routes = [
        ("GET", "/api/data-sync/imports/minute-bars/template.csv"),
        ("POST", "/api/data-sync/imports/minute-bars"),
        ("POST", "/api/data-sync/imports/minute-bars/audit-gaps"),
        ("POST", "/api/data-sync/imports/minute-bars/gap-template.csv"),
        ("POST", "/api/data-sync/imports/minute-bars/vendor-manifest"),
        ("POST", "/api/data-sync/imports/minute-bars/vendor-manifest.csv"),
        ("POST", "/api/data-sync/imports/minute-bars/tushare-gaps"),
        ("POST", "/api/data-sync/imports/minute-bars/tdx-gaps"),
        ("POST", "/api/data-sync/imports/minute-bars/akshare-gaps"),
        ("POST", "/api/vnpy/import-minute-bars/gaps"),
    ]

    responses = [client.request(method, path, json={}) for method, path in routes]

    assert [response.status_code for response in responses] == [404] * len(routes)


def test_historical_evidence_csv_service_is_removed() -> None:
    assert not hasattr(evidence, "import_csv_evidence")
    assert not hasattr(evidence, "evidence_csv_template")


def test_historical_evidence_api_rejects_invalid_dataset(monkeypatch) -> None:
    response = TestClient(create_app()).get(
        "/api/data-sync/imports/limit-up-evidence/template.csv?dataset=unknown"
    )

    assert response.status_code == 404


def test_historical_evidence_api_rejects_invalid_date_range(monkeypatch) -> None:
    def reject(**_kwargs):
        raise evidence.HistoricalEvidenceImportError(
            "start_date must not be after end_date"
        )

    monkeypatch.setattr(
        data_sync_api.historical_evidence_import,
        "import_tushare_evidence",
        reject,
    )
    response = TestClient(create_app()).post(
        "/api/data-sync/imports/limit-up-evidence/tushare",
        json={
            "dataset": "events",
            "start_date": "2026-07-10",
            "end_date": "2026-07-01",
        },
    )

    assert response.status_code == 422
    assert "start_date" in response.json()["error"]["message"]


def test_ths_evidence_batch_api_returns_202_and_status(monkeypatch) -> None:
    batch = {
        "id": "ths-batch-1",
        "status": "running",
        "jobs": [{"job_id": ths_batch.JOB_ID, "status": "running"}],
    }
    monkeypatch.setattr(
        data_sync_api,
        "start_ths_evidence_batch",
        lambda *, max_dates, only_missing: batch,
    )
    monkeypatch.setattr(data_sync_api, "get_ths_evidence_batch", lambda _batch_id: batch)
    client = TestClient(create_app())

    started = client.post(
        "/api/data-sync/imports/limit-up-evidence/ths/start",
        json={"max_dates": 252, "only_missing": True},
    )
    status = client.get(
        "/api/data-sync/imports/limit-up-evidence/ths/batches/ths-batch-1"
    )

    assert started.status_code == 202
    assert started.json()["data"]["id"] == "ths-batch-1"
    assert status.status_code == 200
    assert status.json()["data"]["jobs"][0]["job_id"] == ths_batch.JOB_ID


def test_ths_evidence_batch_api_reports_busy_and_foreign_batch(monkeypatch) -> None:
    unrelated = {
        "id": "other-batch",
        "status": "running",
        "jobs": [{"job_id": "sync_stock_daily_bars", "status": "running"}],
    }

    def raise_busy(**_kwargs):
        raise ths_batch.ThsEvidenceBatchBusyError(unrelated)

    def raise_not_found(_batch_id: str):
        raise ths_batch.ThsEvidenceBatchNotFoundError("other-batch")

    monkeypatch.setattr(data_sync_api, "start_ths_evidence_batch", raise_busy)
    monkeypatch.setattr(data_sync_api, "get_ths_evidence_batch", raise_not_found)
    client = TestClient(create_app())

    busy = client.post(
        "/api/data-sync/imports/limit-up-evidence/ths/start",
        json={"max_dates": 252},
    )
    missing = client.get(
        "/api/data-sync/imports/limit-up-evidence/ths/batches/other-batch"
    )

    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "DATA_SYNC_BATCH_BUSY"
    assert busy.json()["error"]["detail"]["batch_id"] == "other-batch"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "THS_EVIDENCE_BATCH_NOT_FOUND"


def test_ths_evidence_batch_api_validates_date_count(monkeypatch) -> None:
    response = TestClient(create_app()).post(
        "/api/data-sync/imports/limit-up-evidence/ths/start",
        json={"max_dates": 253},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_THS_EVIDENCE_DATE_COUNT"
