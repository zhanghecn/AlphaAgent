"""Provider orchestration for database-discovered minute gaps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class MinuteProviderImportError(RuntimeError):
    """Raised for invalid autonomous provider inputs."""


def normalize_minute_gap_provider(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "tdx": "tdx",
        "tdx_public": "tdx",
        "tdx_public_hq": "tdx",
        "通达信": "tdx",
        "tushare": "tushare",
        "tushare_pro": "tushare",
        "akshare": "akshare",
        "eastmoney": "akshare",
        "东方财富": "akshare",
    }
    return aliases.get(text, text or "tdx")


def minute_gap_fetch_interval(provider: str, interval: str) -> str:
    del provider
    if interval in {"1m", "5m"}:
        return interval
    raise MinuteProviderImportError(f"Unsupported minute gap interval: {interval}")


def import_minute_bars_for_gaps(params: dict[str, Any]) -> dict[str, Any]:
    provider = normalize_minute_gap_provider(
        params.get("provider") or params.get("source") or "tdx"
    )
    gaps = params.get("gaps")
    if not isinstance(gaps, Sequence) or isinstance(gaps, (str, bytes)):
        raise MinuteProviderImportError(
            "Autonomous minute backfill requires database-discovered gaps."
        )
    normalized_gaps = [dict(item) for item in gaps if isinstance(item, Mapping)]
    if not normalized_gaps:
        raise MinuteProviderImportError("No database-discovered minute gaps were supplied.")

    interval = "1m"
    fetch_interval = minute_gap_fetch_interval(provider, interval)
    tail_entry_start = str(params.get("tail_entry_start") or "14:30")
    tail_entry_end = str(params.get("tail_entry_end") or "14:30")
    dry_run = _truthy(params.get("dry_run")) if params.get("dry_run") is not None else True
    max_gaps = int(
        params.get("max_gaps")
        or (200 if provider in {"akshare", "tushare"} else 2000)
    )

    if provider == "tdx":
        from alphaagent.server.services.data_providers.tdx_minute_import import (
            import_tdx_minute_bars_for_gaps,
        )

        result = import_tdx_minute_bars_for_gaps(
            gaps=normalized_gaps,
            interval=fetch_interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            dry_run=dry_run,
            max_gaps=max_gaps,
            max_pages_per_symbol=int(params.get("max_pages_per_symbol") or 32),
            timeout_seconds=float(params.get("timeout_seconds") or 3),
        )
    elif provider == "tushare":
        from alphaagent.server.services.data_providers.tushare_minute_import import (
            import_tushare_minute_bars_for_gaps,
        )

        result = import_tushare_minute_bars_for_gaps(
            gaps=normalized_gaps,
            interval=fetch_interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            dry_run=dry_run,
            max_gaps=max_gaps,
        )
    elif provider == "akshare":
        from alphaagent.server.services.data_providers.akshare_minute_import import (
            import_akshare_minute_bars_for_gaps,
        )

        result = import_akshare_minute_bars_for_gaps(
            gaps=normalized_gaps,
            interval=fetch_interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            dry_run=dry_run,
            max_gaps=max_gaps,
        )
    else:
        raise MinuteProviderImportError(f"Unsupported minute gap provider: {provider}")

    rows_read = int(result.get("rows_read") or 0)
    rows_written = int(result.get("rows_written") or 0)
    return {
        **result,
        "mode": "automatic_gaps",
        "provider": provider,
        "interval": interval,
        "fetch_interval": fetch_interval,
        "gap_source": "database_query",
        "rows_read": rows_read,
        "rows_written": rows_written,
        "base_rows_written": rows_written,
        "aggregate_rows_written": 0,
        "aggregate_result": None,
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
