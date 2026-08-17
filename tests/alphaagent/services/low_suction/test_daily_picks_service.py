"""Focused tests for low-suction live snapshots, paging, and diagnostics."""

from contextlib import nullcontext
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import daily_picks_service
from alphaagent.server.services.low_suction.daily_picks_service import (
    _exclude_current_st_candidates,
    _paginate_live_payload,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import QuietStreak


def _candidate(vt_symbol: str) -> LowSuctionCandidate:
    return LowSuctionCandidate(
        vt_symbol=vt_symbol,
        trade_date=date(2026, 8, 6),
        setup_type="oversold_rebound",
        rule_key="test_rule",
        matched_rule_keys=("test_rule",),
        score=50.0,
        band="40-59",
        streak=QuietStreak(total=0, yin=0, yang=0),
        components=(),
        close_price=10.0,
        daily_return_pct=0.0,
        turnover_rate_pct=2.0,
        candle_range_pct=1.0,
        d1_trade_date=None,
        d1_close_return_pct=None,
    )


def test_live_scan_interval_is_one_minute() -> None:
    assert daily_picks_service.LIVE_SCAN_INTERVAL_SECONDS == 60


def test_live_pagination_keeps_each_family_within_persisted_top_hundred() -> None:
    payload = {
        "status": "ok",
        "trend": {
            "total": 140,
            "limit": 100,
            "items": [{"rank": value} for value in range(1, 101)],
        },
        "oversold": {
            "total": 7,
            "limit": 100,
            "items": [{"rank": value} for value in range(1, 8)],
        },
    }

    paged = _paginate_live_payload(payload, trend_page=3, oversold_page=9)

    assert payload["trend"]["items"][0]["rank"] == 1
    assert paged["trend"]["page"] == 3
    assert paged["trend"]["pages"] == 5
    assert [item["rank"] for item in paged["trend"]["items"]] == list(range(41, 61))
    assert paged["oversold"]["page"] == 1
    assert paged["oversold"]["pages"] == 1
    assert [item["rank"] for item in paged["oversold"]["items"]] == list(range(1, 8))


def test_live_read_never_runs_a_scan(monkeypatch) -> None:
    trace = [{"id": 1, "status": "ok", "started_at": "2026-08-10T10:00:00+08:00"}]
    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _version, *, trade_date=None: {
            "status": "ok",
            "trade_date": "2026-08-10",
            "provisional": True,
            "score_version": daily_picks_service.SCORE_VERSION,
            "trend": {"total": 2, "limit": 100, "items": []},
            "oversold": {"total": 3, "limit": 100, "items": []},
        },
    )
    monkeypatch.setattr(daily_picks_service, "load_live_scan_runs", lambda _date: trace)
    monkeypatch.setattr(
        daily_picks_service,
        "_compute_live_payload",
        lambda _now: pytest.fail("live GET must not trigger a market scan"),
    )

    first = daily_picks_service.get_live_recommendations(trade_date=date(2026, 8, 10))
    second = daily_picks_service.get_live_recommendations(
        trend_page=2,
        oversold_page=2,
        trade_date=date(2026, 8, 10),
    )

    assert first["scan_trace"] == trace
    assert second["scan_trace"] == trace
    assert first["refresh_interval_seconds"] == 60
    assert second["trend"]["page"] == 1


def test_latest_read_does_not_substitute_yesterday_on_a_weekday(monkeypatch) -> None:
    observed_at = datetime.fromisoformat("2026-08-12T10:00:00+08:00")
    yesterday = {
        "status": "ok",
        "trade_date": "2026-08-11",
        "provisional": False,
        "score_version": daily_picks_service.SCORE_VERSION,
        "trend": {"total": 1, "limit": 100, "items": []},
        "oversold": {"total": 0, "limit": 100, "items": []},
    }
    requested_dates: list[date | None] = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return observed_at.astimezone(tz) if tz is not None else observed_at.replace(tzinfo=None)

    def load_snapshot(_version: str, *, trade_date: date | None = None):
        requested_dates.append(trade_date)
        return yesterday if trade_date is None else None

    monkeypatch.setattr(daily_picks_service, "datetime", FrozenDateTime)
    monkeypatch.setattr(daily_picks_service, "load_live_snapshot", load_snapshot)
    monkeypatch.setattr(daily_picks_service, "load_live_scan_runs", lambda _date: [])

    payload = daily_picks_service.get_live_recommendations()

    assert payload["status"] == "unavailable"
    assert payload["trade_date"] == "2026-08-12"
    assert requested_dates == [date(2026, 8, 12)]


def test_live_read_without_snapshot_returns_immediately(monkeypatch) -> None:
    # 固定到工作日：非交易日 requested_date 为 None 时走「后台首次扫描中」
    # 分支，本测试验证的是「指定交易日无快照」的立即返回语义。
    observed_at = datetime.fromisoformat("2026-08-12T10:00:00+08:00")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return observed_at.astimezone(tz) if tz is not None else observed_at.replace(tzinfo=None)

    monkeypatch.setattr(daily_picks_service, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _version, *, trade_date=None: None,
    )
    monkeypatch.setattr(daily_picks_service, "load_live_scan_runs", lambda _date: [])
    monkeypatch.setattr(
        daily_picks_service,
        "_compute_live_payload",
        lambda _now: pytest.fail("live GET must not trigger a market scan"),
    )

    payload = daily_picks_service.get_live_recommendations()

    assert payload["status"] == "unavailable"
    assert "暂无低吸推荐快照" in str(payload["message"])
    assert payload["scan_trace"] == []


def test_worker_refresh_persists_snapshot_and_scan_trace(monkeypatch) -> None:
    saved_snapshots: list[dict[str, object]] = []
    saved_runs: list[dict[str, object]] = []
    trace = [{"id": 1, "status": "ok", "started_at": "2026-08-10T10:00:00+08:00"}]

    def compute(_now):
        return {
            "status": "ok",
            "trade_date": "2026-08-10",
            "asof": "2026-08-10T10:00:00+08:00",
            "provisional": True,
            "score_version": daily_picks_service.SCORE_VERSION,
            "trend": {"total": 2, "limit": 100, "items": []},
            "oversold": {"total": 3, "limit": 100, "items": []},
            "_scan_spot_active_symbols": 5_001,
        }

    monkeypatch.setattr(daily_picks_service, "_live_scan_execution_lock", nullcontext)
    monkeypatch.setattr(daily_picks_service, "_compute_live_payload", compute)
    monkeypatch.setattr(
        daily_picks_service,
        "save_live_snapshot",
        lambda payload: saved_snapshots.append(dict(payload)),
    )
    monkeypatch.setattr(
        daily_picks_service,
        "save_live_scan_run",
        lambda run: saved_runs.append(dict(run)),
    )
    monkeypatch.setattr(daily_picks_service, "load_live_scan_runs", lambda _date: trace)

    payload = daily_picks_service.refresh_live_recommendations()

    assert len(saved_snapshots) == 1
    assert saved_snapshots[0]["refresh_interval_seconds"] == 60
    assert saved_runs[0]["status"] == "ok"
    assert saved_runs[0]["spot_active_symbols"] == 5_001
    assert saved_runs[0]["trend_count"] == 2
    assert saved_runs[0]["oversold_count"] == 3
    assert payload["scan_trace"] == trace


def test_tail_final_snapshot_is_not_replaced_by_incomplete_later_scan(monkeypatch) -> None:
    today = date(2026, 8, 12)
    tail_final = {
        "status": "ok",
        "trade_date": today.isoformat(),
        "asof": "2026-08-12T15:01:00+08:00",
        "snapshot_phase": "tail_final",
        "provisional": True,
        "score_version": daily_picks_service.SCORE_VERSION,
        "trend": {"total": 2, "limit": 100, "items": []},
        "oversold": {"total": 1, "limit": 100, "items": []},
    }
    fallback = {
        "status": "ok",
        "trade_date": "2026-08-11",
        "asof": "2026-08-12T15:02:00+08:00",
        "snapshot_phase": "confirmed",
        "score_version": daily_picks_service.SCORE_VERSION,
        "merge_note": "现货快照获取失败，沿用最近完整日线",
    }

    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _version, *, trade_date: tail_final if trade_date == today else None,
    )

    preserved = daily_picks_service._snapshot_payload_to_persist(fallback, today)

    assert preserved == tail_final


def test_unavailable_scan_does_not_replace_a_current_intraday_snapshot(monkeypatch) -> None:
    today = date(2026, 8, 12)
    intraday = {
        "status": "ok",
        "trade_date": today.isoformat(),
        "asof": "2026-08-12T14:59:00+08:00",
        "snapshot_phase": "intraday",
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    unavailable = {
        "status": "unavailable",
        "trade_date": today.isoformat(),
        "asof": "2026-08-12T15:01:00+08:00",
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _version, *, trade_date: intraday if trade_date == today else None,
    )

    assert daily_picks_service._snapshot_payload_to_persist(unavailable, today) == intraday


def test_confirmed_daily_snapshot_replaces_tail_final_snapshot(monkeypatch) -> None:
    today = date(2026, 8, 12)
    tail_final = {
        "trade_date": today.isoformat(),
        "snapshot_phase": "tail_final",
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    confirmed = {
        "trade_date": today.isoformat(),
        "snapshot_phase": "confirmed",
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _version, *, trade_date: tail_final if trade_date == today else None,
    )

    assert daily_picks_service._snapshot_payload_to_persist(confirmed, today) == confirmed


def test_live_scan_failure_is_persisted_without_hiding_the_original_error(monkeypatch) -> None:
    saved_runs: list[dict[str, object]] = []
    monkeypatch.setattr(daily_picks_service, "_live_scan_execution_lock", nullcontext)
    monkeypatch.setattr(
        daily_picks_service,
        "_compute_live_payload",
        lambda _now: (_ for _ in ()).throw(RuntimeError("stock bars unavailable")),
    )
    monkeypatch.setattr(
        daily_picks_service,
        "save_live_scan_run",
        lambda run: saved_runs.append(dict(run)),
    )

    with pytest.raises(RuntimeError, match="stock bars unavailable"):
        daily_picks_service.refresh_live_recommendations()

    assert len(saved_runs) == 1
    assert saved_runs[0]["status"] == "error"
    assert "RuntimeError: stock bars unavailable" in str(saved_runs[0]["error"])


def test_merge_spot_bars_uses_complete_ohlcv_snapshot(monkeypatch) -> None:
    from alphaagent.data_sources.akshare_adapter import AkShareAdapter

    monkeypatch.setattr(
        AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda _self: {
            "items": [
                {
                    "vt_symbol": "600000.SSE",
                    "last_price": 10.5,
                    "open_price": 10.2,
                    "high_price": 10.7,
                    "low_price": 10.1,
                    "volume": 123456,
                    "turnover": 1296288,
                    "turnover_rate": 1.2,
                },
                {
                    "vt_symbol": "000001.SZSE",
                    "last_price": 11.2,
                    "open_price": None,
                    "high_price": None,
                    "low_price": None,
                    "volume": 654321,
                },
                {
                    "vt_symbol": "300001.SZSE",
                    "last_price": 20.0,
                    "open_price": 20.0,
                    "high_price": 20.0,
                    "low_price": 20.0,
                    "volume": 1,
                },
            ]
        },
    )

    result = daily_picks_service._merge_spot_bars(pd.DataFrame(), date(2026, 8, 12))

    assert result.error is None
    assert result.total_symbols == 2
    assert result.active_symbols == 1
    synthetic = result.bars.iloc[0].to_dict()
    assert synthetic["vt_symbol"] == "600000.SSE"
    assert synthetic["close_price"] == 10.5
    assert synthetic["high_price"] == 10.7
    assert synthetic["low_price"] == 10.1
    # 新浪快照 volume 单位是股，日线库存单位是手，合成 bar 必须换算。
    assert synthetic["volume"] == 1234.56


def test_merge_spot_bars_preserves_scanner_symbol_date_order(monkeypatch) -> None:
    from alphaagent.data_sources.akshare_adapter import AkShareAdapter

    previous = date(2026, 8, 11)
    today = date(2026, 8, 12)
    bars = pd.DataFrame(
        [
            {"vt_symbol": "000001.SZSE", "trade_date": previous},
            {"vt_symbol": "600000.SSE", "trade_date": previous},
        ]
    )
    monkeypatch.setattr(
        AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda _self: {
            "items": [
                {
                    "vt_symbol": "600000.SSE",
                    "last_price": 10.5,
                    "open_price": 10.2,
                    "high_price": 10.7,
                    "low_price": 10.1,
                    "volume": 123456,
                },
                {
                    "vt_symbol": "000001.SZSE",
                    "last_price": 11.2,
                    "open_price": 11.0,
                    "high_price": 11.3,
                    "low_price": 10.9,
                    "volume": 654321,
                },
            ]
        },
    )

    result = daily_picks_service._merge_spot_bars(bars, today)

    assert result.bars[["vt_symbol", "trade_date"]].to_dict(orient="records") == [
        {"vt_symbol": "000001.SZSE", "trade_date": previous},
        {"vt_symbol": "000001.SZSE", "trade_date": today},
        {"vt_symbol": "600000.SSE", "trade_date": previous},
        {"vt_symbol": "600000.SSE", "trade_date": today},
    ]


def test_tail_final_merge_forces_a_fresh_ohlcv_snapshot(monkeypatch) -> None:
    from alphaagent.data_sources.akshare_adapter import AkShareAdapter

    calls: list[bool] = []
    monkeypatch.setattr(
        AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda _self, *, force_refresh=False: calls.append(force_refresh) or {"items": []},
    )

    daily_picks_service._merge_spot_bars(
        pd.DataFrame(),
        date(2026, 8, 12),
        force_refresh=True,
    )

    assert calls == [True]


@pytest.mark.parametrize(
    ("items", "error"),
    [
        ([], "现货快照未返回任何股票"),
        (
            [
                {
                    "vt_symbol": "300001.SZSE",
                    "last_price": 20.0,
                    "open_price": 20.0,
                    "high_price": 20.0,
                    "low_price": 20.0,
                    "volume": 1,
                }
            ],
            "现货快照未包含可用主板股票",
        ),
    ],
)
def test_merge_spot_bars_marks_empty_or_non_main_board_snapshot_as_source_failure(
    monkeypatch,
    items,
    error,
) -> None:
    from alphaagent.data_sources.akshare_adapter import AkShareAdapter

    monkeypatch.setattr(
        AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda _self: {"items": items},
    )

    result = daily_picks_service._merge_spot_bars(pd.DataFrame(), date(2026, 8, 12))

    assert result.active_symbols == 0
    assert result.total_symbols == 0
    assert result.error == error


def test_live_payload_distinguishes_spot_source_failure_from_low_coverage(
    monkeypatch,
) -> None:
    latest = date(2026, 8, 11)
    now = datetime.fromisoformat("2026-08-12T10:00:00+08:00")
    today = now.date()
    inputs = SimpleNamespace(
        market_calendar=(latest,),
        bars=pd.DataFrame(),
        security_status=pd.DataFrame(),
    )
    monkeypatch.setattr(daily_picks_service, "_live_inputs", lambda _now: inputs)
    monkeypatch.setattr(
        daily_picks_service,
        "scan_low_suction_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        daily_picks_service,
        "_merge_spot_bars",
        lambda bars, _today: daily_picks_service.SpotBarMerge(
            bars=bars,
            active_symbols=0,
            total_symbols=0,
            error="TimeoutError: sina unavailable",
        ),
    )

    failed = daily_picks_service._compute_live_payload(now)

    assert failed["status"] == "unavailable"
    assert failed["trade_date"] == today.isoformat()
    assert failed["merge_note"] == "现货快照获取失败（TimeoutError: sina unavailable）"
    assert "今日低吸推荐" in str(failed["message"])

    monkeypatch.setattr(
        daily_picks_service,
        "_merge_spot_bars",
        lambda bars, _today: daily_picks_service.SpotBarMerge(
            bars=bars,
            active_symbols=12,
            total_symbols=3_193,
        ),
    )

    low_coverage = daily_picks_service._compute_live_payload(now)

    assert low_coverage["status"] == "unavailable"
    assert low_coverage["trade_date"] == today.isoformat()
    assert low_coverage["merge_note"] == "现货快照 OHLCV 覆盖不足（12/3193 只可用，至少 3000 只）"


def test_live_payload_keeps_partial_today_as_a_tail_final_virtual_bar(monkeypatch) -> None:
    previous = date(2026, 8, 11)
    today = date(2026, 8, 12)
    now = datetime.fromisoformat("2026-08-12T15:01:00+08:00")
    bars = pd.DataFrame(
        [
            {"vt_symbol": "600000.SSE", "trade_date": previous},
            {"vt_symbol": "600000.SSE", "trade_date": today},
        ]
    )
    inputs = SimpleNamespace(
        market_calendar=(previous, today),
        bars=bars,
        security_status=pd.DataFrame(),
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(daily_picks_service, "_live_inputs", lambda _now: inputs)
    monkeypatch.setattr(
        daily_picks_service,
        "_merge_spot_bars",
        lambda base, _today: daily_picks_service.SpotBarMerge(
            bars=pd.concat(
                [
                    base,
                    pd.DataFrame(
                        [{"vt_symbol": "000001.SZSE", "trade_date": today}]
                    ),
                ],
                ignore_index=True,
            ),
            active_symbols=3_100,
            total_symbols=3_200,
        ),
    )

    def scan(
        _bars,
        calendar,
        _security,
        *,
        target_dates,
        market_regimes=None,
    ):
        observed["calendar"] = calendar
        observed["target_dates"] = target_dates
        observed["market_regimes"] = market_regimes
        return []

    monkeypatch.setattr(daily_picks_service, "scan_low_suction_candidates", scan)
    monkeypatch.setattr(
        daily_picks_service,
        "_load_market_regimes",
        lambda _calendar: {today: "below_ma20"},
    )

    payload = daily_picks_service._compute_live_payload(now)

    assert payload["trade_date"] == "2026-08-12"
    assert payload["snapshot_phase"] == "tail_final"
    assert payload["provisional"] is True
    assert observed["calendar"] == [previous, today]
    assert observed["target_dates"] == {today}
    assert observed["market_regimes"] == {today: "below_ma20"}


def test_spot_merge_stops_after_the_single_tail_final_scan() -> None:
    latest = date(2026, 8, 11)

    assert daily_picks_service._should_merge_spot(
        datetime.fromisoformat("2026-08-12T15:01:00+08:00"), latest
    )
    assert not daily_picks_service._should_merge_spot(
        datetime.fromisoformat("2026-08-12T15:02:00+08:00"), latest
    )


def test_backtest_background_records_stage_and_completion(monkeypatch) -> None:
    updates: list[dict[str, object]] = []
    state = {"status": "building", "run_id": 41}
    monkeypatch.setattr(daily_picks_service, "_REBUILD_STATE", state)

    def run_backtest(*, progress, **_kwargs):
        progress("scan_candidates", "扫描全市场候选", {"bar_rows": 1_029_842})
        return {"coverage": {"trade_days": 324, "candidates": 50_704, "labeled": 48_921}}

    monkeypatch.setattr(daily_picks_service, "run_daily_backtest_sync", run_backtest)
    monkeypatch.setattr(
        daily_picks_service,
        "update_daily_backtest_rebuild_run",
        lambda run_id, **values: updates.append({"run_id": run_id, **values}),
    )

    daily_picks_service._background_daily_backtest_rebuild(41)

    assert state["status"] == "ready"
    assert state["stage"] == "completed"
    assert updates[0]["stage"] == "scan_candidates"
    assert updates[-1]["status"] == "ready"
    assert updates[-1]["metrics"] == {
        "trade_days": 324,
        "candidate_count": 50_704,
        "labeled": 48_921,
    }


def test_backtest_sync_rejects_a_cross_process_rebuild(monkeypatch) -> None:
    class BusyExecutionLock:
        def __enter__(self) -> None:
            raise daily_picks_service.DailyBacktestAlreadyRunningError("busy")

        def __exit__(self, *_args: object) -> bool:
            return False

    monkeypatch.setattr(
        daily_picks_service,
        "_daily_backtest_execution_lock",
        lambda: BusyExecutionLock(),
    )

    with pytest.raises(daily_picks_service.DailyBacktestAlreadyRunningError, match="busy"):
        daily_picks_service.run_daily_backtest_sync()


def test_duplicate_backtest_click_is_recorded_and_keeps_active_run(monkeypatch) -> None:
    duplicate_messages: list[str] = []
    monkeypatch.setattr(daily_picks_service, "_REBUILD_STATE", {
        "status": "building",
        "run_id": 41,
        "stage": "scan_candidates",
    })

    class RunningThread:
        @staticmethod
        def is_alive() -> bool:
            return True

    monkeypatch.setattr(daily_picks_service, "_REBUILD_THREAD", RunningThread())
    monkeypatch.setattr(
        daily_picks_service,
        "_record_duplicate_rebuild_request",
        lambda message: duplicate_messages.append(message),
    )

    result = daily_picks_service.start_daily_backtest_rebuild()

    assert result["already_running"] is True
    assert result["run_id"] == 41
    assert duplicate_messages == ["回测 #41 正在 scan_candidates，本次请求未新建任务"]


def test_backtest_status_includes_recent_persisted_runs(monkeypatch) -> None:
    monkeypatch.setattr(daily_picks_service, "_REBUILD_STATE", {"status": "idle"})
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_rebuild_runs",
        lambda: [{"id": 41, "status": "ready", "stage": "completed"}],
    )

    status = daily_picks_service.get_daily_backtest_rebuild_status()

    assert status["status"] == "idle"
    assert status["recent_runs"] == [{"id": 41, "status": "ready", "stage": "completed"}]


def test_backtest_candidate_filter_matches_live_current_name_st_screen() -> None:
    candidates = [_candidate("000001.SZSE"), _candidate("000002.SZSE")]

    filtered = _exclude_current_st_candidates(
        candidates,
        {"000001.SZSE": "平安银行", "000002.SZSE": "*ST样例"},
    )

    assert [candidate.vt_symbol for candidate in filtered] == ["000001.SZSE"]


def test_daily_backtest_report_rejects_stale_scoring_payload(monkeypatch) -> None:
    payload = {
        "version": daily_picks_service.BACKTEST_VERSION,
        "score_version": "low-suction-daily-score-v2.4",
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_run",
        lambda: payload,
    )

    assert daily_picks_service.get_daily_backtest_report() is None


def test_daily_backtest_report_rejects_stale_backtest_payload(monkeypatch) -> None:
    payload = {
        "version": "low-suction-daily-backtest-v2",
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_run",
        lambda: payload,
    )

    assert daily_picks_service.get_daily_backtest_report() is None


def test_daily_backtest_report_accepts_matching_versions(monkeypatch) -> None:
    payload = {
        "version": daily_picks_service.BACKTEST_VERSION,
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_run",
        lambda: payload,
    )

    assert daily_picks_service.get_daily_backtest_report() == payload


def test_startup_reconcile_rebuilds_missing_snapshot_and_report(monkeypatch) -> None:
    """版本升级日缺口：当前版本快照/回测报告都缺失时，自检立即补建。"""

    calls: list[str] = []
    monkeypatch.setattr(daily_picks_service, "load_live_snapshot", lambda _v: None)
    monkeypatch.setattr(
        daily_picks_service,
        "refresh_live_recommendations",
        lambda: calls.append("refresh") or {"status": "ok"},
    )
    monkeypatch.setattr(
        daily_picks_service, "get_daily_backtest_report", lambda: None
    )
    monkeypatch.setattr(
        daily_picks_service,
        "start_daily_backtest_rebuild",
        lambda: calls.append("rebuild") or {"status": "building"},
    )

    actions = daily_picks_service.reconcile_materialized_views_on_startup()

    assert calls == ["refresh", "rebuild"]
    assert actions == {"live_snapshot": "rebuilt", "backtest_report": "rebuilding"}


def test_startup_reconcile_skips_fresh_materialized_views(monkeypatch) -> None:
    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _v: {"status": "ok"},
    )
    monkeypatch.setattr(
        daily_picks_service,
        "get_daily_backtest_report",
        lambda: {"status": "ok"},
    )
    monkeypatch.setattr(
        daily_picks_service,
        "refresh_live_recommendations",
        lambda: (_ for _ in ()).throw(AssertionError("must not scan")),
    )
    monkeypatch.setattr(
        daily_picks_service,
        "start_daily_backtest_rebuild",
        lambda: (_ for _ in ()).throw(AssertionError("must not rebuild")),
    )

    actions = daily_picks_service.reconcile_materialized_views_on_startup()

    assert actions == {"live_snapshot": "fresh", "backtest_report": "fresh"}


def test_startup_reconcile_tolerates_a_running_live_scan(monkeypatch) -> None:
    monkeypatch.setattr(daily_picks_service, "load_live_snapshot", lambda _v: None)

    def _busy() -> dict:
        raise daily_picks_service.LiveScanAlreadyRunningError("busy")

    monkeypatch.setattr(daily_picks_service, "refresh_live_recommendations", _busy)
    monkeypatch.setattr(
        daily_picks_service,
        "get_daily_backtest_report",
        lambda: {"status": "ok"},
    )

    actions = daily_picks_service.reconcile_materialized_views_on_startup()

    assert actions == {"live_snapshot": "already_running", "backtest_report": "fresh"}


def test_startup_reconcile_reports_an_already_running_backtest(monkeypatch) -> None:
    monkeypatch.setattr(
        daily_picks_service,
        "load_live_snapshot",
        lambda _v: {"status": "ok"},
    )
    monkeypatch.setattr(
        daily_picks_service, "get_daily_backtest_report", lambda: None
    )
    monkeypatch.setattr(
        daily_picks_service,
        "start_daily_backtest_rebuild",
        lambda: {"already_running": True},
    )

    actions = daily_picks_service.reconcile_materialized_views_on_startup()

    assert actions == {"live_snapshot": "fresh", "backtest_report": "already_running"}


def test_rebuild_status_surfaces_a_worker_owned_running_run(monkeypatch) -> None:
    """worker 进程触发的回测：本进程内存 idle，顶层状态必须从 DB running 记录合成。"""

    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_rebuild_runs",
        lambda: [
            {
                "id": 4,
                "status": "running",
                "stage": "scan_candidates",
                "source": "manual",
                "started_at": "2026-08-15T14:00:00+00:00",
                "requested_at": "2026-08-15T14:00:00+00:00",
                "message": "扫描全市场候选",
            },
            {"id": 3, "status": "failed", "stage": "scan_candidates"},
        ],
    )

    status = daily_picks_service.get_daily_backtest_rebuild_status()

    assert status["status"] == "building"
    assert status["run_id"] == 4
    assert status["stage"] == "scan_candidates"
    assert status["started_at"] == "2026-08-15T14:00:00+00:00"


def test_rebuild_status_keeps_the_local_building_state_authoritative(monkeypatch) -> None:
    daily_picks_service._set_rebuild_state(
        status="building", run_id=9, stage="load_inputs"
    )
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_rebuild_runs",
        lambda: [{"id": 8, "status": "running", "stage": "scan_candidates"}],
    )
    try:
        status = daily_picks_service.get_daily_backtest_rebuild_status()
    finally:
        daily_picks_service._set_rebuild_state(status="idle", run_id=None, stage=None)

    assert status["status"] == "building"
    assert status["run_id"] == 9
    assert status["stage"] == "load_inputs"


def test_rebuild_status_stays_idle_without_any_running_run(monkeypatch) -> None:
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_rebuild_runs",
        lambda: [{"id": 3, "status": "failed"}, {"id": 1, "status": "ready"}],
    )

    status = daily_picks_service.get_daily_backtest_rebuild_status()

    assert status["status"] == "idle"


def test_backtest_sync_defaults_to_a_two_year_window(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(daily_picks_service, "load_daily_factor_inputs", _capture)
    monkeypatch.setattr(
        daily_picks_service, "_daily_backtest_execution_lock", nullcontext
    )

    with pytest.raises(RuntimeError, match="stop after capture"):
        daily_picks_service.run_daily_backtest_sync()

    start = captured["start_date"]
    end = captured["end_date"]
    assert (end - start).days == daily_picks_service.DEFAULT_BACKTEST_WINDOW_DAYS


def test_backtest_sync_respects_an_explicit_window(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(daily_picks_service, "load_daily_factor_inputs", _capture)
    monkeypatch.setattr(
        daily_picks_service, "_daily_backtest_execution_lock", nullcontext
    )

    with pytest.raises(RuntimeError, match="stop after capture"):
        daily_picks_service.run_daily_backtest_sync(
            start_date=date(2026, 2, 9), end_date=date(2026, 8, 14)
        )

    assert captured["start_date"] == date(2026, 2, 9)
    assert captured["end_date"] == date(2026, 8, 14)


def test_backfill_live_snapshots_fills_only_missing_history_days(monkeypatch) -> None:
    """发版回填：只补当前版本缺失的历史交易日，当天与已有日期不碰。"""

    observed_at = datetime(2026, 8, 17, 16, 0, tzinfo=daily_picks_service.SHANGHAI)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (
                observed_at.astimezone(tz)
                if tz is not None
                else observed_at.replace(tzinfo=None)
            )

    calendar = (
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 17),
    )
    bars = pd.DataFrame({"trade_date": [date(2026, 8, 14)]})
    inputs = SimpleNamespace(
        market_calendar=calendar,
        bars=bars,
        security_status=pd.DataFrame(),
    )
    scan_calls: list[tuple[date, date]] = []
    saved: list[dict[str, object]] = []

    def fake_scan(bars_arg, calendar_arg, *_args, **_kwargs):
        scan_calls.append((max(calendar_arg), bars_arg["trade_date"].max()))
        return [_candidate("600000.SSE")]

    monkeypatch.setattr(daily_picks_service, "datetime", FrozenDateTime)
    monkeypatch.setattr(daily_picks_service, "_live_inputs", lambda _now: inputs)
    monkeypatch.setattr(
        daily_picks_service,
        "list_live_snapshot_dates",
        lambda _version: ["2026-08-14"],  # 已有一天 → 跳过
    )
    monkeypatch.setattr(daily_picks_service, "scan_low_suction_candidates", fake_scan)
    monkeypatch.setattr(daily_picks_service, "_load_market_regimes", lambda _cal: {})
    monkeypatch.setattr(daily_picks_service, "_load_stock_names", lambda _symbols: {})
    monkeypatch.setattr(daily_picks_service, "save_live_snapshot", saved.append)

    result = daily_picks_service.backfill_live_snapshots()

    # 当天(8-17)由盘中/eod 链路负责；已有 8-14 跳过；正序回填 8-11/12/13。
    assert result["backfilled"] == ["2026-08-11", "2026-08-12", "2026-08-13"]
    assert [payload["trade_date"] for payload in saved] == [
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
    ]
    for payload in saved:
        assert payload["snapshot_phase"] == "confirmed"
        assert payload["status"] == "ok"
        assert payload["score_version"] == daily_picks_service.SCORE_VERSION
    # 因果：scan 收到的日历截断到 ≤目标日（bars 由 fake 直接返回）。
    assert [call[0] for call in scan_calls] == [
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
    ]


def test_backfill_live_snapshots_continues_after_single_day_failure(
    monkeypatch,
) -> None:
    """单日重算失败只跳过该日，不中断整体回填。"""

    observed_at = datetime(2026, 8, 17, 16, 0, tzinfo=daily_picks_service.SHANGHAI)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return (
                observed_at.astimezone(tz)
                if tz is not None
                else observed_at.replace(tzinfo=None)
            )

    calendar = (date(2026, 8, 13), date(2026, 8, 14))
    bars = pd.DataFrame({"trade_date": [date(2026, 8, 14)]})
    inputs = SimpleNamespace(
        market_calendar=calendar,
        bars=bars,
        security_status=pd.DataFrame(),
    )
    saved: list[dict[str, object]] = []

    def flaky_scan(_bars, calendar_arg, *_args, **_kwargs):
        if max(calendar_arg) == date(2026, 8, 13):
            raise RuntimeError("boom")
        return []

    monkeypatch.setattr(daily_picks_service, "datetime", FrozenDateTime)
    monkeypatch.setattr(daily_picks_service, "_live_inputs", lambda _now: inputs)
    monkeypatch.setattr(
        daily_picks_service, "list_live_snapshot_dates", lambda _version: []
    )
    monkeypatch.setattr(
        daily_picks_service, "scan_low_suction_candidates", flaky_scan
    )
    monkeypatch.setattr(daily_picks_service, "_load_market_regimes", lambda _cal: {})
    monkeypatch.setattr(daily_picks_service, "_load_stock_names", lambda _symbols: {})
    monkeypatch.setattr(daily_picks_service, "save_live_snapshot", saved.append)

    result = daily_picks_service.backfill_live_snapshots()

    assert result["backfilled"] == ["2026-08-14"]
    assert [payload["trade_date"] for payload in saved] == ["2026-08-14"]
