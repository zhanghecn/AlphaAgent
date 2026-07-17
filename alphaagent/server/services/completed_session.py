"""Shared cutoff for completed A-share daily bars."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAILY_BAR_COMPLETION_TIME = time(15, 5)


def completed_daily_bar_cutoff(at: datetime | None = None) -> date:
    """Return the latest calendar date allowed in completed daily research."""

    observed_at = at or datetime.now(SHANGHAI)
    if observed_at.tzinfo is None:
        raise ValueError("completed daily-bar cutoff requires timezone-aware time")
    local_at = observed_at.astimezone(SHANGHAI)
    if local_at.time() < DAILY_BAR_COMPLETION_TIME:
        return local_at.date() - timedelta(days=1)
    return local_at.date()
