"""Tests for bounded parallel sync + zombie-batch watchdog.

线上根因：sync_stock_minute_bars 用 ``ThreadPoolExecutor + pool.map`` 无超时，
单只股 AkShare 请求 hang → 整批永久卡死 → 阻塞后续调度。这里覆盖修复行为。
"""

from __future__ import annotations

from datetime import date

import time
from datetime import datetime, timedelta, timezone

import pytest

from alphaagent.server.services import data_sync as svc


def test_bounded_parallel_map_skips_hung_item_without_blocking():
    """单 item hang 时，bounded map 在 per_item_timeout 后跳过它，
    其余 item 正常完成，总耗时远小于 hang 时间。"""

    done: list[str] = []
    timed_out: list[str] = []

    def handler(item: str) -> None:
        if item == "hung":
            time.sleep(1.0)  # 模拟 AkShare 对某只股 hang
        done.append(item)

    start = time.monotonic()
    svc._bounded_parallel_map(
        handler,
        ["a", "b", "hung", "c", "d"],
        concurrency=4,
        per_item_timeout=0.05,
        on_timeout=timed_out.append,
    )
    elapsed = time.monotonic() - start

    # 4 个正常 item 都完成
    assert set(done) == {"a", "b", "c", "d"}
    # hung item 被超时跳过并回调
    assert timed_out == ["hung"]
    # 总耗时明显小于 hang 时长，证明没有阻塞。
    assert elapsed < 0.5


def test_bounded_parallel_map_propagates_fast_items_normally():
    """无 hang 时，bounded map 行为等同普通并发 map——所有 item 完成。"""

    done: list[int] = []

    def handler(item: int) -> None:
        done.append(item * 2)

    svc._bounded_parallel_map(
        handler,
        [1, 2, 3, 4, 5],
        concurrency=3,
        per_item_timeout=5.0,
    )

    assert sorted(done) == [2, 4, 6, 8, 10]


def test_bounded_parallel_map_does_not_timeout_queued_items():
    """总批次可以超过 per_item_timeout，但未开始排队项不能被提前取消。"""

    done: list[int] = []

    def handler(item: int) -> None:
        time.sleep(0.03)
        done.append(item)

    svc._bounded_parallel_map(
        handler,
        list(range(30)),
        concurrency=2,
        per_item_timeout=0.12,
    )

    assert sorted(done) == list(range(30))


def test_financial_quarterly_syncs_complete_report_periods(monkeypatch):
    requested_dates: list[str] = []
    written: list[dict[str, object]] = []
    cache_clears: list[bool] = []

    class FakeAdapter:
        def stock_financial_performance(self, report_date):
            requested_dates.append(report_date)
            return {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "report_date": f"{report_date} 00:00:00",
                        "net_profit_yoy": 18.0,
                    }
                ]
            }

    monkeypatch.setattr(
        svc,
        "_financial_report_dates_for_sync",
        lambda params: ["2025-12-31", "2026-03-31"],
    )
    monkeypatch.setattr(
        svc,
        "_upsert_stock_financial_report_batch",
        lambda items: written.extend(items) or len(items),
    )
    monkeypatch.setattr(
        svc,
        "clear_live_context_cache",
        lambda: cache_clears.append(True),
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_financial_quarterly({})

    assert requested_dates == ["2025-12-31", "2026-03-31"]
    assert [item["net_profit_yoy"] for item in written] == [18.0, 18.0]
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2
    assert result["report_dates"] == ["2025-12-31", "2026-03-31"]
    assert cache_clears == [True]


def test_financial_coverage_rejects_partial_provider_response():
    coverage = svc._financial_period_coverage(
        report_date="2026-03-31",
        reference_date=date(2026, 3, 31),
        expected_vt_symbols={f"{index:06d}.SSE" for index in range(5_500)},
        observed_vt_symbols={f"{index:06d}.SSE" for index in range(1_600)},
        as_of_date=date(2026, 7, 29),
    )

    assert coverage["status"] == "incomplete"
    assert coverage["expected_symbol_count"] == 5_500
    assert coverage["covered_symbol_count"] == 1_600
    assert coverage["coverage_ratio"] < svc.FINANCIAL_BATCH_COMPLETE_COVERAGE_RATIO


def test_financial_coverage_marks_current_disclosure_period_pending():
    coverage = svc._financial_period_coverage(
        report_date="2026-06-30",
        reference_date=date(2026, 6, 30),
        expected_vt_symbols={f"{index:06d}.SSE" for index in range(5_500)},
        observed_vt_symbols={f"{index:06d}.SSE" for index in range(29)},
        as_of_date=date(2026, 7, 29),
    )

    assert coverage["status"] == "pending_disclosure"
    assert coverage["disclosure_deadline"] == "2026-08-31"


@pytest.mark.parametrize(
    ("report_date", "expected_deadline"),
    [
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 6, 30), date(2026, 8, 31)),
        (date(2026, 9, 30), date(2026, 10, 31)),
        (date(2026, 12, 31), date(2027, 4, 30)),
    ],
)
def test_financial_disclosure_deadline(report_date, expected_deadline):
    assert svc._financial_disclosure_deadline(report_date) == expected_deadline


def test_financial_quarterly_keeps_current_disclosure_pending(monkeypatch):
    class FakeAdapter:
        def stock_financial_performance(self, report_date):
            return {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "report_date": report_date,
                    }
                ]
            }

    monkeypatch.setattr(
        svc,
        "_upsert_stock_financial_report_batch",
        lambda items: len(items),
    )
    monkeypatch.setattr(
        svc,
        "_financial_batch_coverage",
        lambda report_dates: {
            "2026-06-30": {
                "status": "pending_disclosure",
                "report_date": "2026-06-30",
            }
        },
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_financial_quarterly(
        {"report_dates": ["2026-06-30"]}
    )

    assert result.get("status") is None
    assert result["incomplete_report_dates"] == []
    assert result["pending_disclosure_report_dates"] == ["2026-06-30"]
    assert "披露期内待补齐" in result["message"]


def test_financial_coverage_accepts_expected_universe():
    symbols = {f"{index:06d}.SSE" for index in range(5_500)}

    coverage = svc._financial_period_coverage(
        report_date="2026-03-31",
        reference_date=date(2026, 3, 31),
        expected_vt_symbols=symbols,
        observed_vt_symbols=symbols,
    )

    assert coverage["status"] == "complete"
    assert coverage["coverage_ratio"] == 1.0


def test_financial_report_change_detection_skips_identical_values():
    values = {
        "vt_symbol": "600001.SSE",
        "report_date": "2026-06-30 00:00:00",
        "period_type": "quarterly",
        "net_profit_yoy": 18.0,
        "source": svc.FINANCIAL_BATCH_SOURCE,
        "raw": {"SJLTZ": 18.0},
    }

    assert not svc._financial_report_values_changed(values, dict(values))

    changed = {**values, "net_profit_yoy": 19.0}
    assert svc._financial_report_values_changed(values, changed)


def test_financial_quarterly_keeps_cache_for_unchanged_reports(monkeypatch):
    cache_clears: list[bool] = []

    class FakeAdapter:
        def stock_financial_performance(self, report_date):
            return {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "report_date": report_date,
                    }
                ]
            }

    monkeypatch.setattr(svc, "_upsert_stock_financial_report_batch", lambda items: 0)
    monkeypatch.setattr(
        svc,
        "_invalidate_legacy_financial_growth_fields",
        lambda report_date, *, symbols=None: 0,
    )
    monkeypatch.setattr(
        svc,
        "clear_live_context_cache",
        lambda: cache_clears.append(True),
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_financial_quarterly(
        {"report_dates": ["2026-06-30"]}
    )

    assert result["rows_written"] == 0
    assert cache_clears == []


def test_financial_quarterly_filters_explicit_symbols(monkeypatch):
    written: list[dict[str, object]] = []

    class FakeAdapter:
        def stock_financial_performance(self, report_date):
            return {
                "items": [
                    {"vt_symbol": "603989.SSE", "report_date": report_date},
                    {"vt_symbol": "000506.SZSE", "report_date": report_date},
                ]
            }

    monkeypatch.setattr(
        svc,
        "_upsert_stock_financial_report_batch",
        lambda items: written.extend(items) or len(items),
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_financial_quarterly(
        {
            "report_dates": ["2026-03-31"],
            "symbols": ["603989.SSE"],
        }
    )

    assert [item["vt_symbol"] for item in written] == ["603989.SSE"]
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1


def test_financial_quarterly_clears_live_cache_after_partial_write(monkeypatch):
    cache_clears: list[bool] = []

    class FakeAdapter:
        def stock_financial_performance(self, report_date):
            if report_date == "2026-03-31":
                return {
                    "items": [
                        {
                            "vt_symbol": "000670.SZSE",
                            "report_date": report_date,
                        }
                    ]
                }
            raise TimeoutError("quarter unavailable")

    monkeypatch.setattr(
        svc,
        "_financial_report_dates_for_sync",
        lambda params: ["2026-03-31", "2026-06-30"],
    )
    monkeypatch.setattr(
        svc,
        "_upsert_stock_financial_report_batch",
        lambda items: len(items),
    )
    monkeypatch.setattr(
        svc,
        "clear_live_context_cache",
        lambda: cache_clears.append(True),
    )

    with pytest.raises(svc.DataSyncError, match="2026-06-30:TimeoutError"):
        svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_financial_quarterly({})

    assert cache_clears == [True]


def test_select_zombie_batch_ids_picks_only_stale_running():
    """看门狗只挑 started_at 早于阈值的 running 批次，跳过新鲜的和无开始时间的。

    线上根因：sync_batches.status='running' 的批次永不结束 → 阻塞后续调度。
    mark_interrupted_runs 只在进程重启时清理，且漏了 sync_batches 表。
    看门狗补这个缺口：按时间阈值挑出僵尸批次 ID。
    """
    now = datetime(2026, 7, 6, 21, 54, tzinfo=timezone.utc)
    batches = [
        {"id": "old", "status": "running", "started_at": now - timedelta(hours=7)},        # 僵尸
        {"id": "fresh", "status": "running", "started_at": now - timedelta(minutes=5)},    # 正常 running
        {"id": "done_old", "status": "succeeded", "started_at": now - timedelta(hours=7)}, # 已结束不动
        {"id": "null_started", "status": "running", "started_at": None},                   # 无开始时间跳过
    ]
    zombies = svc._select_zombie_batch_ids(batches, now, threshold_seconds=2 * 3600)
    assert zombies == ["old"]
