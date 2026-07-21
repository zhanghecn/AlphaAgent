"""Low-resource worker for the one-time point-trigger model freeze."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
import logging
import os
import signal
from threading import Event

from alphaagent.server.services.limit_up import preboard_point_trigger_service


LOGGER = logging.getLogger(__name__)
DEFAULT_POLL_SECONDS = 300


def run_once(*, as_of: datetime | None = None) -> dict[str, object]:
    return preboard_point_trigger_service.fit_point_trigger_model_if_ready(
        as_of=as_of
    )


def run_forever(
    *,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    stop_event: Event | None = None,
) -> None:
    stop = stop_event or Event()
    interval = max(int(poll_seconds), 30)
    previous_status: tuple[object, object] | None = None
    while not stop.is_set():
        try:
            result = run_once()
        except Exception:  # noqa: BLE001
            LOGGER.exception("point-trigger research worker iteration failed")
        else:
            status = (result.get("status"), result.get("model_fingerprint"))
            if status != previous_status:
                LOGGER.info(
                    "point-trigger research worker status=%s model=%s",
                    *status,
                )
                previous_status = status
        stop.wait(interval)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=_poll_seconds_from_environment(),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.once:
        result = run_once()
        LOGGER.info("point-trigger research worker result=%s", result)
        return 0

    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    signal.signal(signal.SIGINT, lambda *_args: stop.set())
    run_forever(poll_seconds=args.interval_seconds, stop_event=stop)
    return 0


def _poll_seconds_from_environment() -> int:
    raw = os.environ.get(
        "ALPHAAGENT_POINT_TRIGGER_WORKER_INTERVAL_SECONDS",
        str(DEFAULT_POLL_SECONDS),
    )
    try:
        return max(int(raw), 30)
    except ValueError:
        return DEFAULT_POLL_SECONDS


if __name__ == "__main__":
    raise SystemExit(main())
