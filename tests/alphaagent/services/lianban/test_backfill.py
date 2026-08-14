"""近三周回补 backfill_pool_snapshots: 交易日序列 / 已归档跳过 / 限流 sleep。

archive_daily_pools 一律 mock(不碰网络); 交易日序列来自 sqlite 内存库的
stock_daily_bars, 已归档判定查 limit_up_pool_snapshots 真实行。
"""
from __future__ import annotations

import time
from datetime import date

import pytest
from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban import backfill as backfill_mod
from alphaagent.server.services.lianban.backfill import backfill_pool_snapshots

DATES = [date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11)]
DATES_DESC = sorted(DATES, reverse=True)
DATES_DESC_ISO = [d.isoformat() for d in DATES_DESC]


def _seed_bars(session, dates=DATES) -> None:
    session.execute(
        insert(schema.stocks).values(
            vt_symbol="600001.SSE",
            symbol="600001",
            exchange="SSE",
            name="测试股",
            source="test",
        )
    )
    session.execute(
        insert(schema.stock_daily_bars),
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": td,
                "open_price": 10.0,
                "close_price": 10.5,
                "high_price": 10.6,
                "low_price": 9.9,
                "source": "test",
            }
            for td in dates
        ],
    )


def _insert_pool_row(session, trade_date: date, pool_type: str) -> None:
    session.execute(
        insert(schema.limit_up_pool_snapshots).values(
            trade_date=trade_date,
            pool_type=pool_type,
            vt_symbol="600001.SSE",
            name="测试股",
            source="akshare.stock_ztb_em",
        )
    )


@pytest.fixture()
def archive_calls(monkeypatch) -> list[date]:
    """mock archive_daily_pools, 记录调用日期, 返回非零 rows_written。"""
    calls: list[date] = []

    def fake_archive(session, trade_date, *, adapter=None):
        calls.append(trade_date)
        return {
            "trade_date": trade_date.isoformat(),
            "pools": {"zt": 3},
            "rows_written": 3,
        }

    monkeypatch.setattr(backfill_mod, "archive_daily_pools", fake_archive)
    return calls


@pytest.fixture()
def sleep_calls(monkeypatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: calls.append(seconds))
    return calls


def test_backfill_fetches_recent_days_desc_and_sleeps(
    fake_session, archive_calls, sleep_calls
):
    _seed_bars(fake_session)

    result = backfill_pool_snapshots(
        fake_session, days=25, adapter=object(), sleep_seconds=0.5
    )

    # 交易日序列: stock_daily_bars 最近 distinct 交易日, 降序
    assert archive_calls == DATES_DESC
    assert result["archived"] == DATES_DESC_ISO
    assert result["skipped_existing"] == []
    assert result["empty"] == []
    # 4 次抓取 3 个日间间隔
    assert sleep_calls == [0.5, 0.5, 0.5]


def test_backfill_skips_already_archived_days(fake_session, archive_calls, sleep_calls):
    _seed_bars(fake_session)
    # 最近一日 zt 池已归档 → 跳过; 前一交易日只有 zbgc 行 → 不算已归档
    _insert_pool_row(fake_session, date(2026, 8, 11), "zt")
    _insert_pool_row(fake_session, date(2026, 8, 10), "zbgc")

    result = backfill_pool_snapshots(fake_session, days=25, sleep_seconds=0.1)

    assert archive_calls == [date(2026, 8, 10), date(2026, 8, 7), date(2026, 8, 6)]
    assert result["skipped_existing"] == ["2026-08-11"]
    assert result["archived"] == ["2026-08-10", "2026-08-07", "2026-08-06"]
    assert sleep_calls == [0.1, 0.1]


def test_backfill_marks_zero_row_days_as_empty(fake_session, monkeypatch, sleep_calls):
    _seed_bars(fake_session)

    def fake_archive(session, trade_date, *, adapter=None):
        return {"trade_date": trade_date.isoformat(), "pools": {}, "rows_written": 0}

    monkeypatch.setattr(backfill_mod, "archive_daily_pools", fake_archive)

    result = backfill_pool_snapshots(fake_session, days=25, sleep_seconds=0.0)

    # 东财窗口外的日子接口返回 0 行属正常, 记录即可
    assert result["empty"] == DATES_DESC_ISO
    assert result["archived"] == []
    assert result["skipped_existing"] == []


def test_backfill_respects_days_limit(fake_session, archive_calls, sleep_calls):
    _seed_bars(fake_session)

    result = backfill_pool_snapshots(fake_session, days=2, sleep_seconds=0.0)

    assert archive_calls == [date(2026, 8, 11), date(2026, 8, 10)]
    assert result["archived"] == ["2026-08-11", "2026-08-10"]


def test_backfill_without_bars_is_noop(fake_session, archive_calls, sleep_calls):
    result = backfill_pool_snapshots(fake_session, days=25, sleep_seconds=0.0)

    assert archive_calls == []
    assert sleep_calls == []
    assert result == {"archived": [], "skipped_existing": [], "empty": []}


# ── data_sync runner 接线 ────────────────────────────────────────────────


def test_data_sync_runner_wires_backfill(monkeypatch):
    """手动回补 job: 解析 days/sleep_seconds→开 session→调 backfill→补 message。"""
    from contextlib import contextmanager

    from alphaagent.server.services import data_sync as svc

    captured: dict[str, object] = {}

    def fake_backfill(session, *, days=25, adapter=None, sleep_seconds=1.0):
        captured["session"] = session
        captured["days"] = days
        captured["adapter"] = adapter
        captured["sleep_seconds"] = sleep_seconds
        return {
            "archived": ["2026-08-11"],
            "skipped_existing": ["2026-08-10"],
            "empty": [],
        }

    sentinel_session = object()
    sentinel_adapter = object()

    @contextmanager
    def fake_session_scope():
        yield sentinel_session

    monkeypatch.setattr(backfill_mod, "backfill_pool_snapshots", fake_backfill)
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    method_name = svc.JOB_RUNNERS["backfill_limit_up_pool_snapshots"]
    runner = svc.DataSyncRunner(adapter=sentinel_adapter)
    result = getattr(runner, method_name)({"days": "10", "sleep_seconds": "0"})

    assert captured["session"] is sentinel_session
    assert captured["days"] == 10
    assert captured["sleep_seconds"] == 0.0
    assert captured["adapter"] is sentinel_adapter
    assert "message" in result
