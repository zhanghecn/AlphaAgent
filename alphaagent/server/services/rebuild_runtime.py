"""回测物化重建的运行时共享件:新鲜度判据 + 全量回放后的内存归还。

被 data_sync(夜间批门禁)、data_sync_worker(周期自检)、各线 service(重算收尾)
共用,避免三处各写一份。
"""

from __future__ import annotations

import ctypes
import gc
import logging
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone

LOGGER = logging.getLogger(__name__)
CHINA_TZ = timezone(timedelta(hours=8))
REPORT_REBUILD_FAILURE_BACKOFF = timedelta(minutes=30)


def report_rebuild_due(
    *,
    latest_data: date | None,
    latest_run: Mapping[str, object] | None,
    latest_done: Mapping[str, object] | None,
    now: datetime,
) -> bool:
    """回测物化是否需要补算:最近一次成功重算的日期是否落后于最新完整日线。

    判据用「成功重算日」而不是物化 coverage(事件最后买入日):策略长期零命中时
    coverage 天然停在旧日期,不能据此反复重算。失败退避 30 分钟,避免连续重压。
    """
    if latest_data is None:
        return False
    status = str((latest_run or {}).get("status") or "")
    if status in ("queued", "running"):
        return False
    done_at = _aware_datetime((latest_done or {}).get("finished_at"))
    if done_at is not None and done_at.astimezone(CHINA_TZ).date() >= latest_data:
        return False
    if status == "failed":
        requested_at = _aware_datetime((latest_run or {}).get("requested_at"))
        if requested_at is not None and now - requested_at < REPORT_REBUILD_FAILURE_BACKOFF:
            return False
    return True


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def release_rebuild_memory() -> None:
    """全量回放收尾:gc 后 malloc_trim 把 pandas/numpy  arenas 归还 OS。

    实测(2026-10-29,worker 容器):回放峰值 7584MiB,del+gc 后 1789MiB,
    trim 后 176MiB。不 trim 时长驻进程一直挂着几个 G(碎片在分配器里,gc 还不掉)。
    非 glibc 平台没有 malloc_trim,静默跳过(gc 已做)。
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
    except Exception:  # noqa: BLE001
        LOGGER.debug("malloc_trim failed", exc_info=True)
