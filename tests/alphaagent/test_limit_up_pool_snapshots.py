"""Tests for the append-only intraday limit-up pool snapshots."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from alphaagent.server.services import data_sync as svc


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar(self) -> object:
        return self.value


class _FakeSession:
    """Captures bulk inserts; returns a preset max(source_updated_at)."""

    def __init__(self, existing_updated_at: object = None) -> None:
        self.existing_updated_at = existing_updated_at
        self.bulk_rows: list[list[dict[str, object]]] = []

    def execute(self, statement: object, rows: object = None) -> _ScalarResult:
        if rows is not None:
            self.bulk_rows.append(list(rows))
            return _ScalarResult(None)
        return _ScalarResult(self.existing_updated_at)


def _pools() -> dict:
    return {
        "zt": {
            "label": "涨停池",
            "items": [
                {
                    "vt_symbol": "600001.SSE",
                    "name": "示例",
                    "close_price": 11.0,
                    "change_pct": 10.0,
                    "limit_up_price": 11.0,
                    "limit_amount": 5.0e8,
                    "turnover_rate": 6.5,
                    "volume_ratio": 2.1,
                    "first_limit_time": "09:42:00",
                    "last_limit_time": "09:42:00",
                    "limit_up_count": 1,
                    "raw": {"成交额": 8.0e8, "炸板次数": 2},
                }
            ],
        },
        "zbgc": {
            "label": "炸板池",
            "items": [
                {
                    "vt_symbol": "000002.SZSE",
                    "name": "炸板示例",
                    "close_price": 9.5,
                    "change_pct": 6.0,
                    "limit_amount": None,
                    "limit_up_count": 1,
                    "raw": {"成交额": 3.0e8, "炸板次数": 1},
                }
            ],
        },
        "dtgc": {
            "label": "跌停池",
            "items": [{"vt_symbol": "000003.SZSE", "name": "不收集", "raw": {}}],
        },
        "strong": {
            "label": "强势股",
            "items": [{"vt_symbol": "000004.SZSE", "name": "不收集", "raw": {}}],
        },
    }


def _patch_session(monkeypatch, session: _FakeSession) -> None:
    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(svc, "session_scope", fake_scope)


def test_snapshot_appends_zt_and_zbgc_only(monkeypatch) -> None:
    session = _FakeSession(existing_updated_at=None)
    _patch_session(monkeypatch, session)
    written = svc._append_limit_up_pool_snapshots(
        _pools(), "20260731", "2026-07-31T01:30:00+00:00"
    )
    assert written == 2  # zt 1 行 + zbgc 1 行；dtgc/strong 不收集
    pools_written = [row["pool_type"] for batch in session.bulk_rows for row in batch]
    assert sorted(pools_written) == ["zbgc", "zt"]


def test_snapshot_extracts_seal_fields_from_raw(monkeypatch) -> None:
    session = _FakeSession(existing_updated_at=None)
    _patch_session(monkeypatch, session)
    svc._append_limit_up_pool_snapshots(
        _pools(), "20260731", "2026-07-31T01:30:00+00:00"
    )
    zt_row = next(
        row for batch in session.bulk_rows for row in batch if row["pool_type"] == "zt"
    )
    assert zt_row["seal_amount"] == 5.0e8
    assert zt_row["turnover"] == 8.0e8
    assert zt_row["open_times"] == 2
    assert zt_row["limit_times"] == 1
    assert zt_row["first_limit_time"] == "09:42:00"
    assert zt_row["trade_date"].isoformat() == "2026-07-31"
    assert zt_row["source_updated_at"] == datetime(
        2026, 7, 31, 1, 30, tzinfo=timezone.utc
    )


def test_snapshot_dedupes_same_source_payload(monkeypatch) -> None:
    existing = datetime(2026, 7, 31, 1, 30, tzinfo=timezone.utc)
    session = _FakeSession(existing_updated_at=existing)
    _patch_session(monkeypatch, session)
    written = svc._append_limit_up_pool_snapshots(
        _pools(), "20260731", "2026-07-31T01:30:00+00:00"
    )
    assert written == 0
    assert session.bulk_rows == []


# ── 22:00 潜龙首板分钟回测重跑（v4-B 生产配置）─────────────────────────


def test_eod_backtest_2200_schedule_registered() -> None:
    schedules = {item["id"]: item for item in svc.DEFAULT_BATCH_SCHEDULES}
    entry = schedules["eod_backtest_2200"]
    assert entry["cron"] == "0 22 * * 1-5"
    assert entry["job_ids"] == [
        "leader_minute_backtest_rerun",
        "premarket_prelude_snapshot",
        "premarket_fused_score_snapshot",
    ]
    assert svc.LEADER_MINUTE_BACKTEST_RERUN_BATCH_JOB_ID in svc.INTERNAL_BATCH_JOB_IDS
    assert svc.PREMARKET_PRELUDE_SNAPSHOT_BATCH_JOB_ID in svc.INTERNAL_BATCH_JOB_IDS
    assert svc.PREMARKET_FUSED_SCORE_SNAPSHOT_BATCH_JOB_ID in svc.INTERNAL_BATCH_JOB_IDS


def test_leader_minute_backtest_rerun_uses_v4b_config(monkeypatch) -> None:
    from datetime import date as date_type

    runs: list[dict[str, object]] = []
    monkeypatch.setattr(
        svc, "_latest_complete_daily_date_for_research", lambda: date_type(2026, 7, 31)
    )

    def fake_run(**kwargs):
        runs.append(dict(kwargs))
        return {
            "execution_summary": {
                "total_return_pct": 51.4,
                "win_rate": 60.5,
                "trade_count": 86,
            },
            "coverage_stats": {"trigger_count": 790},
        }

    saved: dict[str, object] = {}

    import alphaagent.server.services.limit_up.leader_minute_backtest as backtest
    import alphaagent.server.services.limit_up.leader_minute_repository as repository
    import alphaagent.server.services.limit_up.leader_sweep_repository as sweep_repository

    monkeypatch.setattr(backtest, "run_minute_backtest", fake_run)
    monkeypatch.setattr(repository, "save_minute_backtest_run", lambda v, r: saved.update(version=v, minute=r))
    monkeypatch.setattr(sweep_repository, "save_sweep_backtest_run", lambda v, r: saved.update(sweep=r))

    result = svc._run_leader_minute_backtest_rerun_batch_job()
    minute_run = runs[0]
    assert "factor_set" not in minute_run  # 深度清理后因子池固定为白名单（无 v3/v4 分支）
    assert "position_filter" not in minute_run  # 位置过滤固定为深跌排除
    assert minute_run["min_trigger_volume_ratio"] == 0.94  # v5b 归因裁决的生产触发量能滤
    assert minute_run["index_ma20_gate"] is True  # 大盘 MA20 环境门（7 月崩盘段止损）
    assert minute_run["start"].isoformat() == "2026-03-03"  # end - 150 天
    assert minute_run["end"].isoformat() == "2026-07-31"
    sweep_run = runs[1]
    assert sweep_run["entry_mode"] == "sweep_board"
    assert "factor_set" not in sweep_run
    assert "min_trigger_volume_ratio" not in sweep_run or sweep_run.get("min_trigger_volume_ratio") is None
    assert saved["version"] == backtest.STUDY_VERSION
    assert "sweep" in saved
    assert result["rows_written"] == 2
    assert "51.4" in result["message"]
