from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import preboard_point_trigger_worker as worker


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_worker_run_once_delegates_to_the_guarded_model_entry(monkeypatch) -> None:
    frozen_at = datetime(2026, 10, 9, 21, 35, tzinfo=SHANGHAI)
    calls: list[datetime | None] = []
    monkeypatch.setattr(
        worker.preboard_point_trigger_service,
        "fit_point_trigger_model_if_ready",
        lambda *, as_of=None: calls.append(as_of)
        or {"status": "active", "model_fingerprint": "sha256:model"},
    )

    result = worker.run_once(as_of=frozen_at)

    assert calls == [frozen_at]
    assert result == {
        "status": "active",
        "model_fingerprint": "sha256:model",
    }
