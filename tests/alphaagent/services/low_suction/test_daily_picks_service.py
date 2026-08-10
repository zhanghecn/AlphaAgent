"""Focused tests for low-suction live payload paging and scan diagnostics."""

from datetime import date

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


def test_live_pagination_keeps_each_family_within_cached_top_hundred() -> None:
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


def test_live_scan_trace_records_only_a_real_cache_miss(monkeypatch) -> None:
    calls: list[object] = []
    saved_runs: list[dict[str, object]] = []
    trace = [{"id": 1, "status": "ok", "started_at": "2026-08-10T10:00:00+08:00"}]
    monkeypatch.setattr(
        daily_picks_service,
        "_cache",
        {"expires_at": None, "payload": None},
    )

    def compute(_now):
        calls.append(_now)
        return {
            "status": "ok",
            "trade_date": "2026-08-10",
            "provisional": True,
            "score_version": daily_picks_service.SCORE_VERSION,
            "trend": {"total": 2, "limit": 100, "items": []},
            "oversold": {"total": 3, "limit": 100, "items": []},
            "_scan_spot_active_symbols": 5_001,
        }

    monkeypatch.setattr(daily_picks_service, "_compute_live_payload", compute)
    monkeypatch.setattr(
        daily_picks_service,
        "save_live_scan_run",
        lambda run: saved_runs.append(dict(run)),
    )
    monkeypatch.setattr(daily_picks_service, "load_live_scan_runs", lambda _date: trace)

    first = daily_picks_service.get_live_recommendations()
    second = daily_picks_service.get_live_recommendations(trend_page=2, oversold_page=2)

    assert len(calls) == 1
    assert len(saved_runs) == 1
    assert saved_runs[0]["status"] == "ok"
    assert saved_runs[0]["spot_active_symbols"] == 5_001
    assert saved_runs[0]["trend_count"] == 2
    assert saved_runs[0]["oversold_count"] == 3
    assert first["scan_trace"] == trace
    assert second["scan_trace"] == trace


def test_live_scan_failure_is_persisted_without_hiding_the_original_error(monkeypatch) -> None:
    saved_runs: list[dict[str, object]] = []
    monkeypatch.setattr(
        daily_picks_service,
        "_cache",
        {"expires_at": None, "payload": None},
    )
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
        daily_picks_service.get_live_recommendations()

    assert len(saved_runs) == 1
    assert saved_runs[0]["status"] == "error"
    assert "RuntimeError: stock bars unavailable" in str(saved_runs[0]["error"])


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


def test_daily_backtest_report_normalizes_fully_unsettled_legacy_ledger_day(monkeypatch) -> None:
    payload = {
        "version": daily_picks_service.BACKTEST_VERSION,
        "score_version": daily_picks_service.SCORE_VERSION,
        "ledger_days": [
            {
                "trade_date": "2026-08-10",
                "day_return_pct": 0.0,
                "legs": [
                    {"d1_close_return_pct": None},
                    {"d1_close_return_pct": None},
                ],
            },
            {
                "trade_date": "2026-08-09",
                "day_return_pct": 0.1,
                "legs": [
                    {"d1_close_return_pct": 1.0},
                    {"d1_close_return_pct": None},
                ],
            },
        ],
    }
    monkeypatch.setattr(daily_picks_service, "load_daily_backtest_run", lambda: payload)

    report = daily_picks_service.get_daily_backtest_report()

    assert report is not None
    assert report["ledger_days"][0]["day_return_pct"] is None
    assert report["ledger_days"][1]["day_return_pct"] == 0.1
    assert payload["ledger_days"][0]["day_return_pct"] == 0.0
