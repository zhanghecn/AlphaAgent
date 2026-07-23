"""Causal one-minute data scope for short-horizon first-board research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import bindparam, select, text, tuple_

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    attach_preboard_prior_evidence,
    load_preboard_capture_manifest,
    load_preboard_manifest,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


ONE_MINUTE_INTERVAL = "1m"
MINIMUM_D1_SAMPLES = scheduled_execution.FIRST_BOARD_MIN_D1_SAMPLES
MINIMUM_COMBINED_RATE = scheduled_execution.FIRST_BOARD_MIN_COMBINED_RATE
EXPECTED_ONE_MINUTE_BARS = 240
MAX_BACKFILL_GAPS = 20_000
MINUTE_PAIR_QUERY_BATCH_SIZE = 128


def official_one_minute_close_times() -> tuple[str, ...]:
    """Return all official one-minute close labels for one A-share session."""

    return tuple(
        [*_minute_sequence("09:31", 120), *_minute_sequence("13:01", 120)]
    )


def filter_static_hazard_manifest(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply only the frozen same-stock evidence gate to manifest pairs."""

    if frame.empty:
        return frame.copy()
    audited = audit_static_hazard_manifest(frame)
    selected = audited.loc[
        audited["static_hazard_gate_passed"].eq(True),  # noqa: E712
        list(frame.columns),
    ].copy()
    return selected.sort_values(
        ["trade_date", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def audit_static_hazard_manifest(frame: pd.DataFrame) -> pd.DataFrame:
    """Annotate every label-free pair with the shared prior-only gate result."""

    audited = frame.copy()
    if audited.empty:
        audited["static_hazard_gate_passed"] = pd.Series(dtype=bool)
        audited["static_hazard_gate_reason"] = pd.Series(dtype=str)
        return audited
    decisions = []
    for raw in audited.to_dict(orient="records"):
        decisions.append(
            scheduled_execution.first_board_profitability_gate(
                {**raw, "board_lane": "first_board", "board_level": 1}
            )
        )
    audited["static_hazard_gate_passed"] = [
        decision["profitability_gate_passed"] for decision in decisions
    ]
    audited["static_hazard_gate_reason"] = [
        decision["profitability_gate_reason"] for decision in decisions
    ]
    return audited


def load_static_hazard_manifest(
    *,
    session_count: int = 60,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Load the bounded all-3% manifest and attach strictly mature evidence."""

    manifest = (
        load_preboard_manifest(session_count=session_count)
        if end_date is None
        else load_preboard_manifest(session_count=session_count, end_date=end_date)
    )
    if manifest.empty:
        return manifest
    end = pd.to_datetime(manifest["trade_date"], errors="raise").max().date()
    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        False,
    )
    return filter_static_hazard_manifest(
        attach_preboard_prior_evidence(manifest, history_days)
    )


def load_static_hazard_capture_manifest_with_audit(
    *,
    start_date: date,
    end_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the selected recent manifest and every pair's static gate audit."""

    manifest = load_preboard_capture_manifest(
        start_date=start_date,
        end_date=end_date,
    )
    if manifest.empty:
        return manifest, audit_static_hazard_manifest(manifest)
    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end_date,
        False,
    )
    audited = audit_static_hazard_manifest(
        attach_preboard_prior_evidence(manifest, history_days)
    )
    selected = audited.loc[
        audited["static_hazard_gate_passed"].eq(True),  # noqa: E712
        [column for column in audited.columns if not column.startswith("static_hazard_")],
    ].copy()
    selected = selected.sort_values(
        ["trade_date", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)
    return selected, audited


def build_one_minute_coverage(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
) -> pd.DataFrame:
    """Audit exact one-minute slots for every requested stock-day."""

    pairs = _manifest_pairs(manifest)
    if pairs.empty:
        return _empty_coverage()
    rows = minute_rows.copy()
    if "interval" in rows:
        rows = rows.loc[rows["interval"].eq(ONE_MINUTE_INTERVAL)].copy()
    if rows.empty:
        counts = _empty_coverage_counts()
    else:
        rows["trade_date"] = pd.to_datetime(rows["trade_date"], errors="coerce").dt.date
        rows["bar_time"] = pd.to_datetime(rows["bar_time"], errors="coerce")
        rows = rows.dropna(subset=["trade_date", "bar_time"])
        expected = set(official_one_minute_close_times())
        rows["slot"] = rows["bar_time"].dt.strftime("%H:%M")
        rows["valid_slot"] = rows["slot"].isin(expected)
        counts = (
            rows.groupby(["vt_symbol", "trade_date"], sort=True)
            .agg(
                raw_row_count=("bar_time", "size"),
                unique_row_count=("bar_time", "nunique"),
                valid_slot_count=("slot", lambda values: values[values.isin(expected)].nunique()),
                unexpected_time_count=("valid_slot", lambda values: int((~values).sum())),
                first_slot=("slot", "min"),
                last_slot=("slot", "max"),
            )
            .reset_index()
        )
        counts["duplicate_count"] = (
            counts["raw_row_count"] - counts["unique_row_count"]
        )
    return _classify_coverage(pairs, counts)


def load_one_minute_coverage(manifest: pd.DataFrame) -> pd.DataFrame:
    """Audit one-minute coverage in PostgreSQL without loading all bars."""

    pairs = _manifest_pairs(manifest)
    if pairs.empty:
        return _empty_coverage()
    symbols = sorted(pairs["vt_symbol"].astype(str).unique())
    statement = text(
        """
        SELECT vt_symbol, trade_date,
               COUNT(*) AS raw_row_count,
               COUNT(DISTINCT bar_time) AS unique_row_count,
               COUNT(DISTINCT bar_time) FILTER (
                   WHERE (bar_time::time BETWEEN time '09:31' AND time '11:30')
                      OR (bar_time::time BETWEEN time '13:01' AND time '15:00')
               ) AS valid_slot_count,
               COUNT(*) FILTER (
                   WHERE NOT (
                       (bar_time::time BETWEEN time '09:31' AND time '11:30')
                       OR (bar_time::time BETWEEN time '13:01' AND time '15:00')
                   )
               ) AS unexpected_time_count,
               TO_CHAR(MIN(bar_time), 'HH24:MI') AS first_slot,
               TO_CHAR(MAX(bar_time), 'HH24:MI') AS last_slot,
               COUNT(*) - COUNT(DISTINCT bar_time) AS duplicate_count
        FROM stock_minute_bars
        WHERE interval = :interval
          AND trade_date BETWEEN :start AND :end
          AND vt_symbol IN :symbols
        GROUP BY vt_symbol, trade_date
        ORDER BY trade_date, vt_symbol
        """
    ).bindparams(bindparam("symbols", expanding=True))
    counts = pd.read_sql(
        statement,
        get_engine(),
        params={
            "interval": ONE_MINUTE_INTERVAL,
            "start": min(pairs["trade_date"]),
            "end": max(pairs["trade_date"]),
            "symbols": symbols,
        },
    )
    if counts.empty:
        counts = _empty_coverage_counts()
    else:
        counts["trade_date"] = pd.to_datetime(
            counts["trade_date"], errors="raise"
        ).dt.date
    return _classify_coverage(pairs, counts)


def load_one_minute_bars(manifest: pd.DataFrame) -> pd.DataFrame:
    """Load only one-minute rows belonging to requested manifest pairs."""

    pairs = _manifest_pairs(manifest)
    if pairs.empty:
        return pd.DataFrame()
    exact_pairs = list(
        pairs[["vt_symbol", "trade_date"]].itertuples(index=False, name=None)
    )
    table = schema.stock_minute_bars
    frames: list[pd.DataFrame] = []
    engine = get_engine()
    for start in range(0, len(exact_pairs), MINUTE_PAIR_QUERY_BATCH_SIZE):
        batch = exact_pairs[start : start + MINUTE_PAIR_QUERY_BATCH_SIZE]
        statement = (
            select(
                table.c.vt_symbol,
                table.c.trade_date,
                table.c.bar_time,
                table.c.interval,
                table.c.open_price,
                table.c.high_price,
                table.c.low_price,
                table.c.close_price,
                table.c.volume,
                table.c.turnover,
                table.c.source,
            )
            .where(
                table.c.interval == ONE_MINUTE_INTERVAL,
                tuple_(table.c.vt_symbol, table.c.trade_date).in_(batch),
            )
            .order_by(table.c.trade_date, table.c.vt_symbol, table.c.bar_time)
        )
        rows = pd.read_sql(
            statement,
            engine,
            parse_dates=["trade_date", "bar_time"],
        )
        if not rows.empty:
            frames.append(rows)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_one_minute_backfill_gaps(
    coverage: pd.DataFrame,
    *,
    max_pairs: int,
) -> list[dict[str, object]]:
    """Return a stable bounded list of non-complete stock-day requirements."""

    limit = min(max(int(max_pairs), 1), MAX_BACKFILL_GAPS)
    missing = coverage.loc[~coverage["coverage_status"].eq("complete")].copy()
    missing = missing.sort_values(["vt_symbol", "trade_date"], kind="stable")
    return [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": _as_date(row.trade_date),
        }
        for row in missing.head(limit).itertuples()
    ]


def backfill_preboard_hazard_minutes(
    *,
    session_count: int = 60,
    max_gaps: int = 2_000,
    dry_run: bool = False,
) -> dict[str, object]:
    """Backfill a bounded causal universe and verify exact 240-bar coverage."""

    if max_gaps < 1 or max_gaps > MAX_BACKFILL_GAPS:
        raise ValueError(f"max_gaps must be between 1 and {MAX_BACKFILL_GAPS}")
    manifest = load_static_hazard_manifest(session_count=session_count)
    coverage_before = load_one_minute_coverage(manifest)
    gaps = build_one_minute_backfill_gaps(coverage_before, max_pairs=max_gaps)
    if not gaps:
        return _backfill_summary(
            manifest,
            coverage_before,
            requested_pairs=(),
            provider_result={"status": "ready", "rows_read": 0, "rows_written": 0},
            dry_run=dry_run,
        )

    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    provider_result = import_tdx_minute_bars_for_gaps(
        gaps=gaps,
        interval=ONE_MINUTE_INTERVAL,
        tail_entry_start="09:31",
        tail_entry_end="15:00",
        dry_run=dry_run,
        max_gaps=len(gaps),
        max_pages_per_symbol=32,
        timeout_seconds=3.0,
    )
    coverage_after = (
        coverage_before if dry_run else load_one_minute_coverage(manifest)
    )
    requested_pairs = {
        (str(row["vt_symbol"]), _as_date(row["trade_date"])) for row in gaps
    }
    return _backfill_summary(
        manifest,
        coverage_after,
        requested_pairs=requested_pairs,
        provider_result=provider_result,
        dry_run=dry_run,
    )


def _backfill_summary(
    manifest: pd.DataFrame,
    coverage: pd.DataFrame,
    *,
    requested_pairs: Sequence[tuple[str, date]] | set[tuple[str, date]],
    provider_result: Mapping[str, object],
    dry_run: bool,
) -> dict[str, object]:
    requested = set(requested_pairs)
    complete = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    covered_requested = requested & complete
    status_counts = {
        str(key): int(value)
        for key, value in coverage["coverage_status"].value_counts().items()
    }
    provider_status = str(provider_result.get("status") or "unknown")
    if provider_status in {"error", "unavailable", "unsupported_interval"}:
        status = provider_status
    elif dry_run:
        status = "dry_run"
    elif requested and len(covered_requested) < len(requested):
        status = "partial"
    else:
        status = "ready"
    return {
        **dict(provider_result),
        "status": status,
        "scope": "limit_up_preboard_hazard_1m",
        "session_count": int(manifest["trade_date"].nunique())
        if not manifest.empty
        else 0,
        "manifest_pair_count": int(len(manifest)),
        "manifest_symbol_count": int(manifest["vt_symbol"].nunique())
        if not manifest.empty
        else 0,
        "requested_gap_count": len(requested),
        "covered_gap_count": len(covered_requested),
        "remaining_missing_pair_count": int(
            (~coverage["coverage_status"].eq("complete")).sum()
        ),
        "complete_pair_count": len(complete),
        "coverage_status_counts": status_counts,
        "dry_run": dry_run,
        "message": (
            f"短时触板一分钟补数：本批完整 {len(covered_requested)}/{len(requested)}，"
            f"总覆盖 {len(complete)}/{len(manifest)}"
        ),
    }


def _classify_coverage(
    pairs: pd.DataFrame,
    counts: pd.DataFrame,
) -> pd.DataFrame:
    coverage = pairs.merge(
        counts,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    integer_columns = (
        "raw_row_count",
        "unique_row_count",
        "valid_slot_count",
        "unexpected_time_count",
        "duplicate_count",
    )
    for column in integer_columns:
        coverage[column] = coverage[column].fillna(0).astype(int)
    coverage["coverage_status"] = "incomplete"
    coverage.loc[coverage["raw_row_count"].eq(0), "coverage_status"] = "missing"
    invalid = coverage["duplicate_count"].gt(0) | coverage[
        "unexpected_time_count"
    ].gt(0)
    coverage.loc[invalid, "coverage_status"] = "invalid"
    complete = (
        coverage["raw_row_count"].eq(EXPECTED_ONE_MINUTE_BARS)
        & coverage["unique_row_count"].eq(EXPECTED_ONE_MINUTE_BARS)
        & coverage["valid_slot_count"].eq(EXPECTED_ONE_MINUTE_BARS)
        & coverage["duplicate_count"].eq(0)
        & coverage["unexpected_time_count"].eq(0)
        & coverage["first_slot"].eq("09:31")
        & coverage["last_slot"].eq("15:00")
    )
    coverage.loc[complete, "coverage_status"] = "complete"
    return coverage.sort_values(
        ["trade_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def _manifest_pairs(manifest: pd.DataFrame) -> pd.DataFrame:
    if manifest.empty:
        return pd.DataFrame(columns=["vt_symbol", "trade_date"])
    pairs = manifest.loc[:, ["vt_symbol", "trade_date"]].drop_duplicates().copy()
    pairs["trade_date"] = pd.to_datetime(
        pairs["trade_date"], errors="raise"
    ).dt.date
    return pairs.sort_values(["trade_date", "vt_symbol"], kind="stable")


def _minute_sequence(start: str, count: int) -> list[str]:
    current = datetime.strptime(start, "%H:%M")
    return [
        (current + timedelta(minutes=index)).strftime("%H:%M")
        for index in range(count)
    ]


def _empty_coverage() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "trade_date",
            "raw_row_count",
            "unique_row_count",
            "valid_slot_count",
            "unexpected_time_count",
            "first_slot",
            "last_slot",
            "duplicate_count",
            "coverage_status",
        ]
    )


def _empty_coverage_counts() -> pd.DataFrame:
    return _empty_coverage().drop(columns=["coverage_status"])


def _as_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()
