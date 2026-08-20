"""Dedicated owner and lightweight healthcheck for scheduled data jobs."""

from __future__ import annotations

import argparse
import ast
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
from threading import Event, Thread


LOGGER = logging.getLogger(__name__)
CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_HEALTH_PORT = 8010

EXPECTED_RUNTIME_CONSTANTS = {
    "LIVE_SCAN_INTERVAL_SECONDS": 60,
    "SCHEDULER_TICK_SECONDS": 2,
}
SCHEDULE_HEARTBEAT_MAX_AGE_SECONDS = {
    "low_suction_live_scan": 180,
}
SCHEDULE_ACTIONS = {
    "low_suction_live_scan": "low_suction_live_scan",
}


def ensure_sync_schema(*, recover_interrupted: bool = True) -> None:
    """Load the scheduler service only in the long-running worker process."""

    from alphaagent.server.services.data_sync import ensure_sync_schema as ensure

    ensure(recover_interrupted=recover_interrupted)


def start_data_sync_scheduler() -> None:
    from alphaagent.server.services.data_sync import start_data_sync_scheduler as start

    start()


def stop_data_sync_scheduler() -> None:
    from alphaagent.server.services.data_sync import stop_data_sync_scheduler as stop

    stop()


def run_forever(*, stop_event: Event | None = None) -> None:
    """Own scheduler recovery and keep its daemon loop alive."""

    stop = stop_event or Event()
    _configure_market_cache()
    ensure_sync_schema(recover_interrupted=True)
    start_data_sync_scheduler()
    _start_low_suction_view_reconcile()
    health_server: ThreadingHTTPServer | None = None
    try:
        health_server = start_worker_health_server()
        LOGGER.info("data sync scheduler worker started")
        stop.wait()
    finally:
        if health_server is not None:
            health_server.shutdown()
            health_server.server_close()
        stop_data_sync_scheduler()
        LOGGER.info("data sync scheduler worker stopped")


def _configure_market_cache() -> None:
    """Share AkShare read-through cache entries with API workers via Redis."""

    from alphaagent.market.cache import configure_market_cache
    from alphaagent.server.core.config import get_settings

    configure_market_cache(get_settings().redis_url)


def _start_low_suction_view_reconcile() -> None:
    """后台自检低吸物化视图版本漂移（不阻塞调度器与健康端口启动）。"""

    def _run() -> None:
        try:
            from alphaagent.server.services.low_suction.daily_picks_service import (
                backfill_live_snapshots,
                reconcile_materialized_views_on_startup,
            )

            actions = reconcile_materialized_views_on_startup()
            LOGGER.info("low-suction materialized view reconcile: %s", actions)
            # 版本切换后历史快照按版本隔离会整体消失，按当前版本回填最近
            # 交易日，让推荐页日期切换器无缝衔接（幂等：已有日期跳过）。
            backfill = backfill_live_snapshots()
            LOGGER.info("low-suction live snapshot backfill: %s", backfill)
        except Exception:  # noqa: BLE001
            LOGGER.exception("low-suction materialized view reconcile failed")

    Thread(target=_run, name="low-suction-view-reconcile", daemon=True).start()


@lru_cache(maxsize=1)
def load_worker_runtime_constants() -> dict[str, int]:
    """Read low-suction cadence constants without importing the scheduler graph."""

    services = Path(__file__).resolve().parent
    sources = {
        "LIVE_SCAN_INTERVAL_SECONDS": (
            services / "low_suction" / "daily_picks_service.py"
        ),
        "SCHEDULER_TICK_SECONDS": services / "data_sync.py",
    }
    return {
        name: _literal_integer_assignment(path, name)
        for name, path in sources.items()
    }


def audit_worker_health(
    *,
    now: datetime,
    constants: Mapping[str, int],
    schedules: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate scheduler liveness for the low-suction intraday scan."""

    current = _aware_china_datetime(now)
    reasons: list[str] = []
    for name, expected in EXPECTED_RUNTIME_CONSTANTS.items():
        if constants.get(name) == expected:
            continue
        reasons.append(_runtime_constant_reason(name, expected))

    heartbeat_required = _scan_heartbeat_required(current)
    schedules_by_id = {
        str(row.get("id") or ""): row
        for row in schedules
        if str(row.get("id") or "")
    }
    heartbeat_ages: dict[str, float | None] = {}
    for schedule_id, action in SCHEDULE_ACTIONS.items():
        row = schedules_by_id.get(schedule_id)
        if row is None:
            reasons.append(f"{schedule_id}_schedule_missing")
            heartbeat_ages[schedule_id] = None
            continue
        if row.get("enabled") is not True:
            reasons.append(f"{schedule_id}_schedule_disabled")
        if str(row.get("action") or "") != action:
            reasons.append(f"{schedule_id}_schedule_action_mismatch")
        age = _heartbeat_age_seconds(current, row.get("last_started_at"))
        heartbeat_ages[schedule_id] = age
        if heartbeat_required and (
            age is None
            or age < -5
            or age > SCHEDULE_HEARTBEAT_MAX_AGE_SECONDS[schedule_id]
        ):
            reasons.append(f"{schedule_id}_heartbeat_stale")

    return {
        "ok": not reasons,
        "status": "healthy" if not reasons else "unhealthy",
        "checked_at": current.isoformat(),
        "reason_codes": reasons,
        "runtime_constants": dict(constants),
        "scan_heartbeat_required": heartbeat_required,
        "schedule_heartbeat_age_seconds": heartbeat_ages,
    }


def check_worker_health(*, now: datetime | None = None) -> dict[str, object]:
    """Load a small database projection and evaluate the worker health contract."""

    current = _aware_china_datetime(now or datetime.now(CHINA_TZ))
    state = _load_worker_health_state(current)
    return audit_worker_health(
        now=current,
        constants=load_worker_runtime_constants(),
        schedules=state["schedules"],
    )


def start_worker_health_server(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    health_loader: Callable[[], Mapping[str, object]] | None = None,
) -> ThreadingHTTPServer:
    """Serve the health audit inside the warm scheduler process."""

    loader = health_loader or check_worker_health

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/healthz":
                self.send_error(404)
                return
            try:
                report = dict(loader())
            except Exception as exc:  # noqa: BLE001
                report = {
                    "ok": False,
                    "status": "unhealthy",
                    "reason_codes": ["healthcheck_exception"],
                    "error_type": exc.__class__.__name__,
                }
            body = json.dumps(
                report,
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            ).encode()
            self.send_response(200 if report.get("ok") is True else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    selected_port = _health_port_from_environment() if port is None else int(port)
    server = ThreadingHTTPServer((host, selected_port), HealthHandler)
    thread = Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.1},
        name="data-sync-worker-health",
        daemon=True,
    )
    thread.start()
    return server


def _load_worker_health_state(now: datetime) -> dict[str, object]:
    import psycopg
    from psycopg.rows import dict_row

    database_url = _psycopg_database_url()
    with psycopg.connect(
        database_url,
        autocommit=True,
        connect_timeout=5,
        options="-c statement_timeout=5000",
        row_factory=dict_row,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, action, enabled, last_status, last_started_at
                FROM sync_batch_schedules
                WHERE id = ANY(%s)
                """,
                (list(SCHEDULE_ACTIONS),),
            )
            schedules = [dict(row) for row in cursor.fetchall()]
    return {
        "schedules": schedules,
    }


def _psycopg_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _health_port_from_environment() -> int:
    raw = os.environ.get("ALPHAAGENT_DATA_SYNC_HEALTH_PORT", "").strip()
    try:
        return int(raw) if raw else DEFAULT_HEALTH_PORT
    except ValueError:
        return DEFAULT_HEALTH_PORT


def _literal_integer_assignment(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value_node = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            value_node = node.value
        if value_node is None:
            continue
        value = ast.literal_eval(value_node)
        if isinstance(value, bool) or not isinstance(value, int):
            break
        return value
    raise RuntimeError(f"{name} is not a literal integer in {path.name}")


def _runtime_constant_reason(name: str, expected: int) -> str:
    labels = {
        "LIVE_SCAN_INTERVAL_SECONDS": "low_suction_live_scan_interval",
        "SCHEDULER_TICK_SECONDS": "scheduler_tick",
    }
    return f"{labels[name]}_not_{expected}s"


def _scan_heartbeat_required(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current_time = now.timetz().replace(tzinfo=None)
    return (
        time(9, 25) <= current_time <= time(11, 30)
        or time(13, 0) <= current_time <= time(15, 1)
    )


def _heartbeat_age_seconds(now: datetime, value: object) -> float | None:
    if not isinstance(value, datetime):
        return None
    started_at = value
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return round((now - started_at.astimezone(CHINA_TZ)).total_seconds(), 3)


def _aware_china_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("healthcheck datetime must be timezone-aware")
    return value.astimezone(CHINA_TZ)


def _run_healthcheck() -> int:
    try:
        report = check_worker_health()
    except Exception as exc:  # noqa: BLE001
        report = {
            "ok": False,
            "status": "unhealthy",
            "reason_codes": ["healthcheck_exception"],
            "error_type": exc.__class__.__name__,
        }
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, default=str))
    return 0 if report["ok"] is True else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return _run_healthcheck()

    logging.basicConfig(level=logging.INFO)
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    signal.signal(signal.SIGINT, lambda *_args: stop.set())
    run_forever(stop_event=stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
