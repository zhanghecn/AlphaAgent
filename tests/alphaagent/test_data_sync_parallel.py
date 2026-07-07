"""Tests for bounded parallel sync + zombie-batch watchdog.

线上根因：sync_stock_minute_bars 用 ``ThreadPoolExecutor + pool.map`` 无超时，
单只股 AkShare 请求 hang → 整批永久卡死 → 阻塞后续调度。这里覆盖修复行为。
"""

from __future__ import annotations

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
            time.sleep(30)  # 模拟 AkShare 对某只股 hang
        done.append(item)

    start = time.monotonic()
    svc._bounded_parallel_map(
        handler,
        ["a", "b", "hung", "c", "d"],
        concurrency=4,
        per_item_timeout=1.0,
        on_timeout=timed_out.append,
    )
    elapsed = time.monotonic() - start

    # 4 个正常 item 都完成
    assert set(done) == {"a", "b", "c", "d"}
    # hung item 被超时跳过并回调
    assert timed_out == ["hung"]
    # 总耗时 << 30 秒（约 1 秒超时 + 余量），证明没有阻塞
    assert elapsed < 5.0


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
