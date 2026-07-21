from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
import json
from threading import Event

from alphaagent.server.services import data_sync_worker


CHINA_TZ = timezone(timedelta(hours=8))
VALID_FINGERPRINT = "sha256:" + "a" * 64


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
    latest_frame: dict[str, object] | None = None,
    current_day_frame_count: int = 0,
    current_day_fingerprints: list[object] | None = None,
    current_day_missing_fingerprint_count: int = 0,
) -> dict[str, object]:
    return data_sync_worker.audit_worker_health(
        now=now,
        constants=constants
        or {
            "LIVE_SCAN_INTERVAL_SECONDS": 10,
            "SCHEDULER_TICK_SECONDS": 2,
            "CONCEPT_REFRESH_SECONDS": 30,
        },
        schedules=schedules
        or [
            _schedule("limit_up_live_scan", now=now),
            _schedule("limit_up_concept_scan", now=now),
        ],
        latest_frame=latest_frame,
        current_day_frame_count=current_day_frame_count,
        current_day_fingerprints=current_day_fingerprints or [],
        current_day_missing_fingerprint_count=(
            current_day_missing_fingerprint_count
        ),
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
                "reason_codes": ["limit_up_live_scan_heartbeat_stale"],
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
            "limit_up_live_scan_heartbeat_stale"
        ]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_worker_runtime_constants_match_the_frozen_capture_cadence() -> None:
    assert data_sync_worker.load_worker_runtime_constants() == {
        "LIVE_SCAN_INTERVAL_SECONDS": 10,
        "SCHEDULER_TICK_SECONDS": 2,
        "CONCEPT_REFRESH_SECONDS": 30,
    }


def test_healthcheck_rejects_wrong_capture_cadence_before_market_open() -> None:
    now = datetime(2026, 7, 22, 8, 30, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        constants={
            "LIVE_SCAN_INTERVAL_SECONDS": 60,
            "SCHEDULER_TICK_SECONDS": 15,
            "CONCEPT_REFRESH_SECONDS": 30,
        },
    )

    assert report["ok"] is False
    assert report["reason_codes"] == [
        "live_scan_interval_not_10s",
        "scheduler_tick_not_2s",
    ]


def test_healthcheck_rejects_stale_intraday_schedule_heartbeats() -> None:
    now = datetime(2026, 7, 22, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        schedules=[
            _schedule("limit_up_live_scan", now=now, age_seconds=61),
            _schedule("limit_up_concept_scan", now=now, age_seconds=121),
        ],
    )

    assert report["ok"] is False
    assert report["reason_codes"] == [
        "limit_up_live_scan_heartbeat_stale",
        "limit_up_concept_scan_heartbeat_stale",
    ]


def test_healthcheck_accepts_fresh_intraday_heartbeats_and_one_fingerprint() -> None:
    now = datetime(2026, 7, 22, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        latest_frame={
            "trade_date": now.date(),
            "captured_at": now - timedelta(seconds=5),
            "capture_runtime_fingerprint": VALID_FINGERPRINT,
        },
        current_day_frame_count=12,
        current_day_fingerprints=[VALID_FINGERPRINT],
    )

    assert report["ok"] is True
    assert report["reason_codes"] == []
    assert report["scan_heartbeat_required"] is True


def test_healthcheck_rejects_missing_or_changed_current_day_fingerprint() -> None:
    now = datetime(2026, 7, 22, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        latest_frame={
            "trade_date": now.date(),
            "captured_at": now - timedelta(seconds=5),
            "capture_runtime_fingerprint": VALID_FINGERPRINT,
        },
        current_day_frame_count=12,
        current_day_fingerprints=[VALID_FINGERPRINT, "sha256:" + "b" * 64],
        current_day_missing_fingerprint_count=1,
    )

    assert report["ok"] is False
    assert report["reason_codes"] == [
        "current_day_radar_fingerprint_missing",
        "current_day_radar_fingerprint_changed",
    ]


def test_healthcheck_does_not_recycle_after_close_for_a_frozen_bad_day() -> None:
    now = datetime(2026, 7, 22, 16, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        latest_frame={
            "trade_date": now.date(),
            "captured_at": now - timedelta(hours=1),
            "capture_runtime_fingerprint": VALID_FINGERPRINT,
        },
        current_day_frame_count=12,
        current_day_fingerprints=[VALID_FINGERPRINT, "sha256:" + "b" * 64],
        current_day_missing_fingerprint_count=1,
    )

    assert report["ok"] is True
    assert report["scan_heartbeat_required"] is False


def test_healthcheck_does_not_require_a_current_frame_on_weekday_holiday() -> None:
    # National Day is a weekday in 2026. The scheduler heartbeat still proves
    # that the worker is alive; an absent current quote frame is not a fault.
    now = datetime(2026, 10, 1, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        latest_frame={
            "trade_date": datetime(2026, 9, 30).date(),
            "captured_at": datetime(2026, 9, 30, 14, 57, tzinfo=CHINA_TZ),
            "capture_runtime_fingerprint": VALID_FINGERPRINT,
        },
    )

    assert report["ok"] is True
    assert report["scan_heartbeat_required"] is True


def test_healthcheck_skips_intraday_heartbeat_age_on_weekends() -> None:
    now = datetime(2026, 7, 25, 10, 0, tzinfo=CHINA_TZ)
    report = _health_report(
        now=now,
        schedules=[
            _schedule("limit_up_live_scan", now=now, age_seconds=3600),
            _schedule("limit_up_concept_scan", now=now, age_seconds=3600),
        ],
    )

    assert report["ok"] is True
    assert report["scan_heartbeat_required"] is False
