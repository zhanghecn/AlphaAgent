"""Provider orchestration for strict 14:30 minute-gap imports."""

from __future__ import annotations

from typing import Any, Callable


class MinuteProviderImportError(RuntimeError):
    """Raised for invalid provider import inputs."""


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
    if interval == "1m":
        return "1m"
    raise MinuteProviderImportError(f"Unsupported minute gap interval: {interval}")


def minute_gap_csv_from_sync_params(
    params: dict[str, Any],
    *,
    backtest_gap_csv: Callable[[int], dict[str, Any]] | None = None,
) -> tuple[str, str]:
    file_path = str(params.get("gap_file_path") or params.get("file_path") or "").strip()
    if file_path:
        return "", f"gap_file_path={file_path}"

    csv_text = str(params.get("gap_csv_text") or params.get("csv_text") or "").strip()
    if csv_text:
        return csv_text, "inline_gap_csv"

    backtest_id = params.get("backtest_id")
    if backtest_id not in (None, ""):
        try:
            numeric_id = int(backtest_id)
        except (TypeError, ValueError) as exc:
            raise MinuteProviderImportError(f"Invalid backtest_id: {backtest_id}") from exc
        if backtest_gap_csv is None:
            from alphaagent.server.services.backtest.engine import backtest_minute_gap_csv

            backtest_gap_csv = backtest_minute_gap_csv
        result = backtest_gap_csv(numeric_id)
        if result.get("status") not in {"ready", "empty"}:
            message = result.get("message") or result.get("status") or "unknown"
            raise MinuteProviderImportError(f"Cannot load minute gaps for backtest {numeric_id}: {message}")
        return str(result.get("content") or ""), f"backtest_id={numeric_id}"

    raise MinuteProviderImportError("Minute gap sync requires backtest_id, gap_csv_text, or gap_file_path.")


def minute_gap_source_label(params: dict[str, Any]) -> str:
    file_path = str(params.get("gap_file_path") or params.get("file_path") or "").strip()
    if file_path:
        return f"gap_file_path={file_path}"
    csv_text = str(params.get("gap_csv_text") or params.get("csv_text") or "").strip()
    if csv_text:
        return "inline_gap_csv"
    backtest_id = params.get("backtest_id")
    if backtest_id not in (None, ""):
        return f"backtest_id={backtest_id}"
    return "missing_gap_source"


def import_minute_bars_for_gaps(
    params: dict[str, Any],
    *,
    backtest_gap_csv: Callable[[int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    provider = normalize_minute_gap_provider(params.get("provider") or params.get("source") or "tdx")
    interval = "1m"
    fetch_interval = minute_gap_fetch_interval(provider, interval)
    gap_csv_text, gap_source = minute_gap_csv_from_sync_params(params, backtest_gap_csv=backtest_gap_csv)
    gap_file_path = str(params.get("gap_file_path") or params.get("file_path") or "").strip()
    tail_entry_start = str(params.get("tail_entry_start") or "14:30")
    tail_entry_end = str(params.get("tail_entry_end") or "14:30")
    dry_run = _truthy(params.get("dry_run")) if params.get("dry_run") is not None else True
    max_gaps = int(params.get("max_gaps") or (200 if provider in {"akshare", "tushare"} else 2000))

    if provider == "tdx":
        from alphaagent.server.services.data_providers.tdx_minute_import import import_tdx_minute_bars_for_gaps

        result = import_tdx_minute_bars_for_gaps(
            gap_csv_text=gap_csv_text if not gap_file_path else "",
            gap_file_path=gap_file_path,
            interval=fetch_interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            dry_run=dry_run,
            max_gaps=max_gaps,
            max_pages_per_symbol=int(params.get("max_pages_per_symbol") or 32),
            timeout_seconds=float(params.get("timeout_seconds") or 3),
        )
    elif provider == "tushare":
        from alphaagent.server.services.data_providers.tushare_minute_import import import_tushare_minute_bars_for_gaps

        result = import_tushare_minute_bars_for_gaps(
            gap_csv_text=gap_csv_text if not gap_file_path else "",
            gap_file_path=gap_file_path,
            interval=fetch_interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            dry_run=dry_run,
            max_gaps=max_gaps,
        )
    elif provider == "akshare":
        from alphaagent.server.services.data_providers.akshare_minute_import import import_akshare_minute_bars_for_gaps

        result = import_akshare_minute_bars_for_gaps(
            gap_csv_text=gap_csv_text if not gap_file_path else "",
            gap_file_path=gap_file_path,
            interval=fetch_interval,
            tail_entry_start=tail_entry_start,
            tail_entry_end=tail_entry_end,
            dry_run=dry_run,
            max_gaps=max_gaps,
        )
    else:
        raise MinuteProviderImportError(f"Unsupported minute gap provider: {provider}")

    rows_read = int(result.get("rows_read") or 0)
    base_rows_written = int(result.get("rows_written") or 0)
    return {
        **result,
        "mode": "backtest_gaps",
        "provider": provider,
        "interval": interval,
        "fetch_interval": fetch_interval,
        "gap_source": gap_source,
        "rows_read": rows_read,
        "rows_written": base_rows_written,
        "base_rows_written": base_rows_written,
        "aggregate_rows_written": 0,
        "aggregate_result": None,
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
