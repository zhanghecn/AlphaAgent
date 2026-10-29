from datetime import date, datetime, timedelta, timezone
from http.client import HTTPConnection
import json
from threading import Event

from alphaagent.server.services import data_sync_worker


CHINA_TZ = timezone(timedelta(hours=8))
def _schedule(
    schedule_id: str,
    *,
    now: datetime,
    age_seconds: int = 10,
) -> dict[str, object]:
    return {
        "id": schedule_id,
        "action": schedule_id,
        "enabled": True,
        "last_started_at": now - timedelta(seconds=age_seconds),
    }


def _health_report(
    *,
    now: datetime,
    schedules: list[dict[str, object]] | None = None,
    constants: dict[str, int] | None = None,
) -> dict[str, object]:
    return data_sync_worker.audit_worker_health(
        now=now,
        constants=constants
        or {
            "LIVE_SCAN_INTERVAL_SECONDS": 60,
            "SCHEDULER_TICK_SECONDS": 2,
        },
        schedules=schedules
        or [
            _schedule("low_suction_live_scan", now=now),
        ],
    )


def test_worker_owns_schema_recovery_and_scheduler(monkeypatch) -> None:
    calls: list[object] = []
    stop = Event()
    stop.set()

    class HealthServer:
        def shutdown(self) -> None:
            calls.append("health_stop")

        def server_close(self) -> None:
            calls.append("health_close")

    monkeypatch.setattr(
        data_sync_worker,
        "ensure_sync_schema",
        lambda *, recover_interrupted=True: calls.append(
            ("schema", recover_interrupted)
        ),
    )
    monkeypatch.setattr(
        data_sync_worker,
        "start_data_sync_scheduler",
        lambda: calls.append("start"),
    )
    monkeypatch.setattr(
        data_sync_worker,
        "stop_data_sync_scheduler",
        lambda: calls.append("stop"),
    )
    monkeypatch.setattr(
        data_sync_worker,
        "start_worker_health_server",
        lambda: calls.append("health_start") or HealthServer(),
    )

    data_sync_worker.run_forever(stop_event=stop)

    assert calls == [
        ("schema", True),
        "start",
        "health_start",
        "health_stop",
        "health_close",
        "stop",
    ]


def test_worker_health_server_returns_report_status() -> None:
    reports = iter(
        (
            {"ok": True, "status": "healthy", "reason_codes": []},
            {
                "ok": False,
                "status": "unhealthy",
                "reason_codes": ["low_suction_live_scan_heartbeat_stale"],
            },
        )
    )
    server = data_sync_worker.start_worker_health_server(
        port=0,
        health_loader=lambda: next(reports),
    )
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {
            "ok": True,
            "status": "healthy",
            "reason_codes": [],
        }
        connection.close()

        connection = HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        assert response.status == 503
        assert json.loads(response.read())["reason_codes"] == [
            "low_suction_live_scan_heartbeat_stale"
        ]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_worker_runtime_constants_match_scheduler_cadence() -> None:
    assert data_sync_worker.load_worker_runtime_constants() == {
        "SCHEDULER_TICK_SECONDS": 2,
    }


def test_healthcheck_rejects_wrong_capture_cadence_before_market_open() -> None:
    now = datetime(2026, 7, 22, 8, 30, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        constants={
            "SCHEDULER_TICK_SECONDS": 15,
        },
    )

    assert report["ok"] is False
    assert report["reason_codes"] == [
        "scheduler_tick_not_2s",
    ]




def test_healthcheck_accepts_a_fresh_low_suction_scan_heartbeat() -> None:
    now = datetime(2026, 7, 22, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(now=now)

    assert report["ok"] is True
    assert report["reason_codes"] == []
    assert report["scan_heartbeat_required"] is True

def test_healthcheck_skips_intraday_heartbeat_age_on_weekends() -> None:
    now = datetime(2026, 7, 25, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        schedules=[
            _schedule("low_suction_live_scan", now=now, age_seconds=3600),
        ],
    )

    assert report["ok"] is True
    assert report["scan_heartbeat_required"] is False


# ── 回测物化新鲜度自检(错过 23:05/23:20 cron 后的补算判据) ──

NOW = datetime(2026, 10, 29, 20, 40, tzinfo=CHINA_TZ)


def _run_row(status: str, at: datetime) -> dict[str, object]:
    return {"status": status, "requested_at": at, "finished_at": at}


def test_report_rebuild_waits_until_daily_data_ready() -> None:
    assert data_sync_worker.report_rebuild_due(
        latest_data=None, latest_run=None, latest_done=None, now=NOW,
    ) is False


def test_report_rebuild_runs_when_never_built() -> None:
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=None, latest_done=None, now=NOW,
    ) is True


def test_report_rebuild_skips_when_done_covers_latest_daily() -> None:
    done = _run_row("done", datetime(2026, 10, 29, 19, 30, tzinfo=CHINA_TZ))
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=done, latest_done=done, now=NOW,
    ) is False


def test_report_rebuild_catches_up_missed_nightly_cron() -> None:
    # 昨晚 23:05 之后机器关机:最近一次成功只覆盖 10-28,今天日线已就绪→补算
    done = _run_row("done", datetime(2026, 10, 28, 23, 9, tzinfo=CHINA_TZ))
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=done, latest_done=done, now=NOW,
    ) is True


def test_report_rebuild_uses_china_calendar_date_for_done() -> None:
    # UTC 存储 15:30 = 上海 23:30,同日不算落后
    done = _run_row("done", datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc))
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=done, latest_done=done, now=NOW,
    ) is False


def test_report_rebuild_does_not_duplicate_active_run() -> None:
    done = _run_row("done", datetime(2026, 10, 28, 23, 9, tzinfo=CHINA_TZ))
    running = _run_row("running", NOW - timedelta(minutes=1))
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=running, latest_done=done, now=NOW,
    ) is False


def test_report_rebuild_backs_off_after_failure() -> None:
    done = _run_row("done", datetime(2026, 10, 28, 23, 9, tzinfo=CHINA_TZ))
    failed = _run_row("failed", NOW - timedelta(minutes=5))
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=failed, latest_done=done, now=NOW,
    ) is False
    old_failed = _run_row("failed", NOW - timedelta(minutes=45))
    assert data_sync_worker.report_rebuild_due(
        latest_data=date(2026, 10, 29), latest_run=old_failed, latest_done=done, now=NOW,
    ) is True


def test_report_reconcile_loop_repeats_and_survives_errors() -> None:
    stop = Event()
    calls: list[int] = []

    def check() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient db error")
        if len(calls) >= 3:
            stop.set()

    data_sync_worker._report_reconcile_loop(
        check, interval_seconds=0.01, stop_event=stop,
    )

    assert len(calls) >= 3
