"""Tests for bounded parallel sync + zombie-batch watchdog.

线上根因：sync_stock_minute_bars 用 ``ThreadPoolExecutor + pool.map`` 无超时，
单只股 AkShare 请求 hang → 整批永久卡死 → 阻塞后续调度。这里覆盖修复行为。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

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


def test_financial_quarterly_skips_hung_stock_without_late_write(monkeypatch):
    """A hung quarterly request must not block the batch or write after timeout."""

    written_symbols: list[str] = []
    attempts: list[tuple[str, str]] = []
    progress: list[dict[str, object]] = []
    release_hung_request = threading.Event()

    class FakeAdapter:
        def stock_financial_quarterly(self, symbol, exchange=None):
            if symbol == "600001":
                release_hung_request.wait()
            return {
                "items": [
                    {
                        "report_date": "2026-03-31",
                        "revenue": 1.0,
                        "net_profit": 1.0,
                    }
                ]
            }

        def stock_balance_sheet(self, symbol, exchange=None):
            return {"items": []}

        def stock_cash_flow_sheet(self, symbol, exchange=None):
            return {"items": []}

    monkeypatch.setattr(
        svc,
        "_financial_sync_stock_rows",
        lambda stock_limit, only_missing: [
            {"symbol": "600001", "exchange": "SSE", "name": "慢响应"},
            {"symbol": "600002", "exchange": "SSE", "name": "正常"},
        ],
    )
    monkeypatch.setattr(
        svc,
        "_upsert_stock_financial_reports",
        lambda symbol, exchange, items, period_type: written_symbols.append(symbol) or len(items),
    )
    monkeypatch.setattr(
        svc,
        "_record_financial_sync_attempt",
        lambda vt_symbol_value, status, **kwargs: attempts.append(
            (vt_symbol_value, status)
        ),
    )
    monkeypatch.setattr(svc, "FINANCIAL_SYNC_PER_ITEM_TIMEOUT_SECONDS", 0.03)

    start = time.monotonic()
    try:
        result = svc.DataSyncRunner(
            adapter=FakeAdapter(),
            progress=progress.append,
            concurrency=2,
        )._run_sync_stock_financial_quarterly({})
        elapsed = time.monotonic() - start
    finally:
        release_hung_request.set()

    assert elapsed < 0.5
    assert result == {"rows_read": 1, "rows_written": 1, "timed_out": 1}
    assert written_symbols == ["600002"]
    assert any("超时跳过" in str(item.get("current_label")) for item in progress)

    time.sleep(0.05)
    assert written_symbols == ["600002"]
    assert sorted(attempts) == [
        ("600001.SSE", "timed_out"),
        ("600002.SSE", "succeeded"),
    ]


def test_financial_quarterly_uses_dedicated_timeout_and_capped_concurrency(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        svc,
        "_financial_sync_stock_rows",
        lambda stock_limit, only_missing: [
            {"symbol": "600001", "exchange": "SSE", "name": "样本"},
        ],
    )

    def capture_map(fn, items, *, concurrency, per_item_timeout, on_timeout):
        del fn, items, on_timeout
        captured.update(
            concurrency=concurrency,
            per_item_timeout=per_item_timeout,
        )

    monkeypatch.setattr(svc, "_bounded_parallel_map", capture_map)
    monkeypatch.setattr(svc, "FINANCIAL_SYNC_PER_ITEM_TIMEOUT_SECONDS", 180.0)
    monkeypatch.setattr(svc, "FINANCIAL_SYNC_MAX_STOCK_CONCURRENCY", 3)

    svc.DataSyncRunner(concurrency=8)._run_sync_stock_financial_quarterly({})

    assert captured == {
        "concurrency": 3,
        "per_item_timeout": 180.0,
    }


def test_financial_quarterly_fetches_statement_bundle_concurrently(monkeypatch):
    barrier = threading.Barrier(3, timeout=0.5)
    written: list[dict[str, object]] = []
    attempts: list[tuple[str, str]] = []

    class FakeAdapter:
        def stock_financial_quarterly(self, symbol, exchange=None):
            del symbol, exchange
            barrier.wait()
            return {
                "items": [
                    {
                        "report_date": "2026-03-31",
                        "publish_date": "2026-04-30",
                        "revenue": 100.0,
                        "net_profit": 10.0,
                        "raw": {"PARENT_NETPROFIT": 10.0},
                    }
                ]
            }

        def stock_balance_sheet(self, symbol, exchange=None):
            del symbol, exchange
            barrier.wait()
            return {
                "items": [
                    {
                        "REPORT_DATE": "2026-03-31",
                        "TOTAL_PARENT_EQUITY": 100.0,
                    }
                ]
            }

        def stock_cash_flow_sheet(self, symbol, exchange=None):
            del symbol, exchange
            barrier.wait()
            return {
                "items": [
                    {
                        "REPORT_DATE": "2026-03-31",
                        "NOTICE_DATE": "2026-04-30",
                        "NETCASH_OPERATE": 15.0,
                        "NETPROFIT": 10.0,
                    }
                ]
            }

    monkeypatch.setattr(
        svc,
        "_financial_sync_stock_rows",
        lambda stock_limit, only_missing: [
            {"symbol": "600001", "exchange": "SSE", "name": "并发样本"},
        ],
    )
    monkeypatch.setattr(
        svc,
        "_upsert_stock_financial_reports",
        lambda symbol, exchange, items, period_type: written.extend(items) or len(items),
    )
    monkeypatch.setattr(
        svc,
        "_record_financial_sync_attempt",
        lambda vt_symbol_value, status, **kwargs: attempts.append(
            (vt_symbol_value, status)
        ),
    )

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_stock_financial_quarterly({})

    assert result == {"rows_read": 1, "rows_written": 1, "timed_out": 0}
    assert written[0]["roe"] == 10.0
    assert written[0]["operating_cash_flow"] == 15.0
    assert written[0]["cash_flow_quality"] == 1.5
    assert attempts == [("600001.SSE", "succeeded")]


def test_financial_quarterly_forwards_requested_symbols(monkeypatch):
    selected: dict[str, object] = {}

    def select_stocks(stock_limit, only_missing, *, symbols=None):
        selected.update(
            stock_limit=stock_limit,
            only_missing=only_missing,
            symbols=symbols,
        )
        return []

    monkeypatch.setattr(svc, "_financial_sync_stock_rows", select_stocks)

    result = svc.DataSyncRunner()._run_sync_stock_financial_quarterly(
        {
            "stock_limit": 24,
            "only_missing": True,
            "symbols": ["603989.SSE", "000506.SZSE"],
        }
    )

    assert selected == {
        "stock_limit": 24,
        "only_missing": True,
        "symbols": ["603989.SSE", "000506.SZSE"],
    }
    assert result == {
        "rows_read": 0,
        "rows_written": 0,
        "message": "No stocks in DB.",
    }


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
