"""Controlled qfq snapshot import for the nightly data-sync worker.

This module owns external adjusted-price requests.  Research readers consume the
persisted snapshot and scope evidence, but never call this importer directly.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
from alphaagent.server.services.low_suction.adjusted_daily_bars import (
    QFQ_ADJUSTMENT,
    QFQ_SOURCE,
    AdjustedDailyBar,
    AdjustedDailyBarError,
    QfqDailyScope,
    build_qfq_daily_scope,
    fetch_qfq_daily_bars,
)

ADJUSTED_DAILY_SYNC_JOB_ID = "sync_low_suction_adjusted_daily_bars"
EARLIEST_RELIABLE_TRADE_DATE = date(2023, 3, 28)
MIN_RELIABLE_STOCK_SYMBOLS = 3_000
DEFAULT_MAX_SYMBOLS = 50
DEFAULT_MAX_WORKERS = 4
MAX_WORKERS = 8
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0
# multi-VALUES 批量 INSERT 每行 13 个绑定参数，Postgres 协议上限 65535
# 个参数（≈5041 行）——批大小必须留在这个上限内，曾用 20_000 连续触发
# "number of parameters must be between 0 and 65535" 使前复权日线停更。
WRITE_BATCH_ROWS = 4_000
SCOPE_QUERY_BATCH_DAYS = 20
MAIN_BOARD_VT_PATTERNS = (
    "600%.SSE",
    "601%.SSE",
    "603%.SSE",
    "605%.SSE",
    "000%.SZSE",
    "001%.SZSE",
    "002%.SZSE",
    "003%.SZSE",
)


class AdjustedDailyImportError(RuntimeError):
    """Raised when a controlled adjusted-price sync request is invalid."""


@dataclass(frozen=True)
class AdjustedDailyTarget:
    """One symbol whose canonical qfq coverage is incomplete."""

    vt_symbol: str
    first_expected_date: date
    last_expected_date: date
    requested_row_count: int
    accepted_row_count: int


@dataclass(frozen=True)
class AdjustedDailyScopeAudit:
    """Current canonical qfq rows and persisted daily scope evidence."""

    scopes: tuple[QfqDailyScope, ...]
    persisted_complete_dates: tuple[date, ...]
    missing_or_stale_dates: tuple[date, ...]

    @property
    def complete(self) -> bool:
        return bool(self.scopes) and not self.missing_or_stale_dates

    def as_dict(self) -> dict[str, object]:
        incomplete = [scope for scope in self.scopes if not scope.complete]
        return {
            "scope_count": len(self.scopes),
            "complete_scope_count": sum(scope.complete for scope in self.scopes),
            "current_incomplete_dates": [
                scope.trade_date.isoformat() for scope in incomplete
            ],
            "persisted_complete_dates": [
                value.isoformat() for value in self.persisted_complete_dates
            ],
            "missing_or_stale_scope_dates": [
                value.isoformat() for value in self.missing_or_stale_dates
            ],
            "ready": self.complete,
            "scope_fingerprint_sha256": _scope_fingerprint(self.scopes),
        }


def sync_adjusted_daily_bars(
    *,
    sync_run_id: int,
    symbols: Sequence[str] = (),
    start_date: date | None = None,
    end_date: date | None = None,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    history_fetcher: Callable[..., pd.DataFrame] | None = None,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Persist a bounded qfq snapshot from the canonical raw-daily universe.

    A normal EOD job uses the finite default symbol cap.  A historical import is
    an explicit data-sync invocation with a date range and ``max_symbols=0``;
    research code has no path to call this function.
    """

    _validate_request(
        sync_run_id=sync_run_id,
        start_date=start_date,
        end_date=end_date,
        max_symbols=max_symbols,
        max_workers=max_workers,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    normalized_symbols = tuple(
        sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    )
    with session_scope() as session:
        calendar = _reliable_market_calendar(
            session,
            start_date=start_date,
            end_date=end_date,
        )
        targets = _missing_adjusted_targets(
            session,
            calendar,
            symbols=normalized_symbols,
            max_symbols=max_symbols,
            current_sync_run_id=sync_run_id,
        )
        scope_before = _collect_scope_audit(
            session,
            calendar,
            current_sync_run_id=sync_run_id,
        )

    if not calendar:
        return {
            "status": "incomplete",
            "rows_read": 0,
            "rows_written": 0,
            "sync_run_id": sync_run_id,
            "source": QFQ_SOURCE,
            "message": "没有满足全市场覆盖门槛的原始日线交易日",
            "market_calendar": _calendar_summary(calendar),
            "adjusted_prices": scope_before.as_dict(),
        }

    _report_progress(progress, current=0, total=len(targets), rows_read=0, rows_written=0)
    failures: dict[str, str] = {}
    rows_read = 0
    rows_written = 0
    completed_targets = 0
    pending_rows: list[AdjustedDailyBar] = []
    for target, rows, failure in _fetch_targets(
        targets,
        max_workers=max_workers,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
        history_fetcher=history_fetcher,
    ):
        completed_targets += 1
        if failure is not None:
            failures[target.vt_symbol] = failure
        else:
            rows_read += len(rows)
            pending_rows.extend(rows)
            if len(pending_rows) >= WRITE_BATCH_ROWS:
                rows_written += _upsert_adjusted_rows(
                    pending_rows,
                    sync_run_id=sync_run_id,
                    requested_start=calendar[0],
                    requested_end=calendar[-1],
                )
                pending_rows.clear()
        _report_progress(
            progress,
            current=completed_targets,
            total=len(targets),
            rows_read=rows_read,
            rows_written=rows_written,
            current_label=target.vt_symbol,
        )
    if pending_rows:
        rows_written += _upsert_adjusted_rows(
            pending_rows,
            sync_run_id=sync_run_id,
            requested_start=calendar[0],
            requested_end=calendar[-1],
        )

    with session_scope() as session:
        scope_after = _collect_scope_audit(
            session,
            calendar,
            current_sync_run_id=sync_run_id,
            fetch_failures=failures,
        )
    _upsert_scopes(
        scope_after.scopes,
        sync_run_id=sync_run_id,
        requested_start=calendar[0],
        requested_end=calendar[-1],
        target_count=len(targets),
    )
    with session_scope() as session:
        persisted_scope = _collect_scope_audit(
            session,
            calendar,
            current_sync_run_id=sync_run_id,
        )

    complete = persisted_scope.complete
    status = "succeeded" if complete else "incomplete"
    message = (
        "前复权日线范围完整"
        if complete
        else "前复权日线范围未完整；已保留本次受控同步结果，后续数据同步将继续补齐"
    )
    return {
        "status": status,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "sync_run_id": sync_run_id,
        "source": QFQ_SOURCE,
        "market_calendar": _calendar_summary(calendar),
        "target_count": len(targets),
        "targets": [_target_payload(target) for target in targets],
        "max_symbols": max_symbols,
        "max_workers": max_workers,
        "fetch_failure_count": len(failures),
        "fetch_failure_examples": [
            {"vt_symbol": symbol, "error": failures[symbol]}
            for symbol in sorted(failures)[:50]
        ],
        "adjusted_prices": persisted_scope.as_dict(),
        "message": message,
    }


def _validate_request(
    *,
    sync_run_id: int,
    start_date: date | None,
    end_date: date | None,
    max_symbols: int,
    max_workers: int,
    retry_attempts: int,
    retry_delay_seconds: float,
) -> None:
    if isinstance(sync_run_id, bool) or int(sync_run_id) < 1:
        raise AdjustedDailyImportError("sync_run_id must be a positive data-sync run id")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise AdjustedDailyImportError("start_date cannot follow end_date")
    if max_symbols < 0:
        raise AdjustedDailyImportError("max_symbols cannot be negative")
    if max_symbols == 0 and (start_date is None or end_date is None):
        raise AdjustedDailyImportError(
            "an unbounded qfq backfill requires explicit start_date and end_date"
        )
    if not 1 <= max_workers <= MAX_WORKERS:
        raise AdjustedDailyImportError(
            f"max_workers must be between 1 and {MAX_WORKERS}"
        )
    if retry_attempts < 1:
        raise AdjustedDailyImportError("retry_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise AdjustedDailyImportError("retry_delay_seconds cannot be negative")


def _reliable_market_calendar(
    session,
    *,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, ...]:
    raw_daily = schema.stock_daily_bars
    conditions = [
        raw_daily.c.trade_date >= (start_date or EARLIEST_RELIABLE_TRADE_DATE),
        raw_daily.c.trade_date <= completed_daily_bar_cutoff(),
    ]
    if end_date is not None:
        conditions.append(raw_daily.c.trade_date <= end_date)
    rows = session.execute(
        select(raw_daily.c.trade_date, func.count())
        .where(*conditions)
        .group_by(raw_daily.c.trade_date)
        .order_by(raw_daily.c.trade_date)
    ).all()
    return tuple(
        trade_date
        for trade_date, symbol_count in rows
        if int(symbol_count or 0) >= MIN_RELIABLE_STOCK_SYMBOLS
    )


def _missing_adjusted_targets(
    session,
    calendar: Sequence[date],
    *,
    symbols: Sequence[str],
    max_symbols: int,
    current_sync_run_id: int,
) -> tuple[AdjustedDailyTarget, ...]:
    if not calendar:
        return ()
    raw_daily = schema.stock_daily_bars
    adjusted = schema.low_suction_adjusted_daily_bars
    adjusted_source, eligible_adjusted_row = _eligible_adjusted_row_source(
        current_sync_run_id=current_sync_run_id,
    )
    join_condition = and_(
        adjusted.c.vt_symbol == raw_daily.c.vt_symbol,
        adjusted.c.trade_date == raw_daily.c.trade_date,
        adjusted.c.adjustment == QFQ_ADJUSTMENT,
        adjusted.c.source == QFQ_SOURCE,
        eligible_adjusted_row,
    )
    requested_count = func.count(raw_daily.c.vt_symbol)
    accepted_count = func.count(adjusted.c.vt_symbol)
    statement = (
        select(
            raw_daily.c.vt_symbol,
            func.min(raw_daily.c.trade_date),
            func.max(raw_daily.c.trade_date),
            requested_count,
            accepted_count,
        )
        .select_from(raw_daily.outerjoin(adjusted_source, join_condition))
        .where(
            raw_daily.c.trade_date.in_(tuple(calendar)),
            _main_board_predicate(raw_daily.c.vt_symbol),
        )
        .group_by(raw_daily.c.vt_symbol)
        .having(accepted_count < requested_count)
        .order_by(raw_daily.c.vt_symbol)
    )
    if symbols:
        statement = statement.where(raw_daily.c.vt_symbol.in_(tuple(symbols)))
    if max_symbols:
        statement = statement.limit(max_symbols)
    return tuple(
        AdjustedDailyTarget(
            vt_symbol=str(row[0]),
            first_expected_date=row[1],
            last_expected_date=row[2],
            requested_row_count=int(row[3] or 0),
            accepted_row_count=int(row[4] or 0),
        )
        for row in session.execute(statement).all()
    )


def _eligible_adjusted_row_source(*, current_sync_run_id: int):
    """Return qfq rows plus the provenance predicate valid for this run.

    Rows from earlier successful controlled imports are reusable.  Rows written
    by the currently running import are also visible for its own scope audit;
    that run becomes canonical only after ``run_job`` marks it succeeded.
    """

    adjusted = schema.low_suction_adjusted_daily_bars
    runs = schema.sync_job_runs
    source = adjusted.outerjoin(
        runs,
        runs.c.id == adjusted.c.sync_run_id,
    )
    eligible = or_(
        adjusted.c.sync_run_id == current_sync_run_id,
        and_(
            runs.c.job_id == ADJUSTED_DAILY_SYNC_JOB_ID,
            runs.c.status == "succeeded",
        ),
    )
    return source, eligible


def _collect_scope_audit(
    session,
    calendar: Sequence[date],
    *,
    current_sync_run_id: int,
    fetch_failures: Mapping[str, str] | None = None,
) -> AdjustedDailyScopeAudit:
    if not calendar:
        return AdjustedDailyScopeAudit((), (), ())
    raw_daily = schema.stock_daily_bars
    adjusted = schema.low_suction_adjusted_daily_bars
    adjusted_source, eligible_adjusted_row = _eligible_adjusted_row_source(
        current_sync_run_id=current_sync_run_id,
    )
    join_condition = and_(
        adjusted.c.vt_symbol == raw_daily.c.vt_symbol,
        adjusted.c.trade_date == raw_daily.c.trade_date,
        adjusted.c.adjustment == QFQ_ADJUSTMENT,
        adjusted.c.source == QFQ_SOURCE,
        eligible_adjusted_row,
    )
    scopes: list[QfqDailyScope] = []
    for date_batch in _batched(calendar, SCOPE_QUERY_BATCH_DAYS):
        statement = (
            select(
                raw_daily.c.trade_date,
                raw_daily.c.vt_symbol,
                adjusted.c.source_fingerprint,
            )
            .select_from(raw_daily.outerjoin(adjusted_source, join_condition))
            .where(
                raw_daily.c.trade_date.in_(date_batch),
                _main_board_predicate(raw_daily.c.vt_symbol),
            )
            .order_by(raw_daily.c.trade_date, raw_daily.c.vt_symbol)
        )
        current_date: date | None = None
        expected_symbols: list[str] = []
        accepted: dict[str, str] = {}

        def append_scope() -> None:
            if current_date is None:
                return
            scopes.append(
                build_qfq_daily_scope(
                    current_date,
                    expected_symbols=expected_symbols,
                    accepted_rows_by_symbol=accepted,
                    fetch_failures=fetch_failures,
                )
            )

        for trade_date, vt_symbol, source_fingerprint in session.execute(statement).all():
            if current_date is not None and trade_date != current_date:
                append_scope()
                expected_symbols = []
                accepted = {}
            current_date = trade_date
            symbol = str(vt_symbol)
            expected_symbols.append(symbol)
            if source_fingerprint:
                accepted[symbol] = str(source_fingerprint)
        append_scope()

    persisted = _persisted_scopes(
        session,
        scopes,
        current_sync_run_id=current_sync_run_id,
    )
    persisted_complete = tuple(
        scope.trade_date
        for scope in scopes
        if _persisted_scope_matches(
            scope,
            persisted.get((scope.trade_date, scope.request_fingerprint)),
        )
    )
    persisted_dates = set(persisted_complete)
    missing_or_stale = tuple(
        scope.trade_date
        for scope in scopes
        if not scope.complete or scope.trade_date not in persisted_dates
    )
    return AdjustedDailyScopeAudit(
        scopes=tuple(scopes),
        persisted_complete_dates=persisted_complete,
        missing_or_stale_dates=missing_or_stale,
    )


def _persisted_scopes(
    session,
    scopes: Sequence[QfqDailyScope],
    *,
    current_sync_run_id: int,
) -> dict[tuple[date, str], Mapping[str, object]]:
    if not scopes:
        return {}
    table = schema.low_suction_adjusted_daily_bar_scopes
    runs = schema.sync_job_runs
    source = table.outerjoin(runs, runs.c.id == table.c.sync_run_id)
    eligible_scope = or_(
        table.c.sync_run_id == current_sync_run_id,
        and_(
            runs.c.job_id == ADJUSTED_DAILY_SYNC_JOB_ID,
            runs.c.status == "succeeded",
        ),
    )
    rows = session.execute(
        select(
            table.c.trade_date,
            table.c.request_fingerprint,
            table.c.requested_symbol_count,
            table.c.returned_symbol_count,
            table.c.accepted_symbol_count,
            table.c.excluded_symbol_count,
            table.c.complete,
            table.c.response_fingerprint,
            table.c.sync_run_id,
        )
        .select_from(source)
        .where(
            table.c.adjustment == QFQ_ADJUSTMENT,
            table.c.source == QFQ_SOURCE,
            table.c.trade_date.in_(tuple(scope.trade_date for scope in scopes)),
            eligible_scope,
        )
    ).all()
    return {
        (row[0], str(row[1])): {
            "requested_symbol_count": int(row[2] or 0),
            "returned_symbol_count": int(row[3] or 0),
            "accepted_symbol_count": int(row[4] or 0),
            "excluded_symbol_count": int(row[5] or 0),
            "complete": bool(row[6]),
            "response_fingerprint": str(row[7] or ""),
            "sync_run_id": row[8],
        }
        for row in rows
    }


def _persisted_scope_matches(
    scope: QfqDailyScope,
    persisted: Mapping[str, object] | None,
) -> bool:
    return bool(
        scope.complete
        and persisted
        and persisted.get("sync_run_id") is not None
        and bool(persisted.get("complete"))
        and int(persisted.get("requested_symbol_count") or 0)
        == scope.requested_symbol_count
        and int(persisted.get("returned_symbol_count") or 0)
        == scope.returned_symbol_count
        and int(persisted.get("accepted_symbol_count") or 0)
        == scope.accepted_symbol_count
        and int(persisted.get("excluded_symbol_count") or 0)
        == scope.excluded_symbol_count
        and str(persisted.get("response_fingerprint") or "")
        == scope.response_fingerprint
    )


def _fetch_targets(
    targets: Sequence[AdjustedDailyTarget],
    *,
    max_workers: int,
    retry_attempts: int,
    retry_delay_seconds: float,
    history_fetcher: Callable[..., pd.DataFrame] | None,
) -> Iterable[tuple[AdjustedDailyTarget, list[AdjustedDailyBar], str | None]]:
    if not targets:
        return ()
    with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as executor:
        futures = {
            executor.submit(
                _fetch_target,
                target,
                retry_attempts=retry_attempts,
                retry_delay_seconds=retry_delay_seconds,
                history_fetcher=history_fetcher,
            ): target
            for target in targets
        }
        results: list[tuple[AdjustedDailyTarget, list[AdjustedDailyBar], str | None]] = []
        for future in as_completed(futures):
            target = futures[future]
            try:
                results.append((target, future.result(), None))
            except Exception as exc:  # provider failures are audit evidence, not a crash
                results.append((target, [], _failure_label(exc)))
        return tuple(sorted(results, key=lambda item: item[0].vt_symbol))


def _fetch_target(
    target: AdjustedDailyTarget,
    *,
    retry_attempts: int,
    retry_delay_seconds: float,
    history_fetcher: Callable[..., pd.DataFrame] | None,
) -> list[AdjustedDailyBar]:
    last_error: AdjustedDailyBarError | None = None
    for attempt in range(retry_attempts):
        try:
            return fetch_qfq_daily_bars(
                target.vt_symbol,
                start_date=target.first_expected_date,
                end_date=target.last_expected_date,
                history_fetcher=history_fetcher,
            )
        except AdjustedDailyBarError as exc:
            last_error = exc
            if attempt + 1 < retry_attempts and retry_delay_seconds:
                time.sleep(retry_delay_seconds * (2**attempt))
    assert last_error is not None
    raise last_error


def _upsert_adjusted_rows(
    rows: Sequence[AdjustedDailyBar],
    *,
    sync_run_id: int,
    requested_start: date,
    requested_end: date,
) -> int:
    if not rows:
        return 0
    table = schema.low_suction_adjusted_daily_bars
    provenance = _provenance(sync_run_id, requested_start, requested_end)
    values = [
        {
            "vt_symbol": row.vt_symbol,
            "trade_date": row.trade_date,
            "adjustment": row.adjustment,
            "open_price": row.open_price,
            "close_price": row.close_price,
            "high_price": row.high_price,
            "low_price": row.low_price,
            "volume": row.volume,
            "turnover": row.turnover,
            "source": row.source,
            "source_fingerprint": row.source_fingerprint,
            "sync_run_id": sync_run_id,
            "raw": {"source_row": row.raw, "sync": provenance},
        }
        for row in rows
    ]
    statement = insert(table).values(values)
    update_columns = (
        "open_price",
        "close_price",
        "high_price",
        "low_price",
        "volume",
        "turnover",
        "source",
        "source_fingerprint",
        "sync_run_id",
        "raw",
    )
    statement = statement.on_conflict_do_update(
        index_elements=(table.c.vt_symbol, table.c.trade_date, table.c.adjustment),
        set_={
            **{column: getattr(statement.excluded, column) for column in update_columns},
            "updated_at": func.now(),
        },
    )
    with session_scope() as session:
        session.execute(statement)
    return len(values)


def _upsert_scopes(
    scopes: Sequence[QfqDailyScope],
    *,
    sync_run_id: int,
    requested_start: date,
    requested_end: date,
    target_count: int,
) -> None:
    if not scopes:
        return
    table = schema.low_suction_adjusted_daily_bar_scopes
    provenance = {
        **_provenance(sync_run_id, requested_start, requested_end),
        "target_count": target_count,
    }
    annotated = [
        replace(scope, raw={**scope.raw, "sync": provenance}) for scope in scopes
    ]
    values = [
        {
            "trade_date": scope.trade_date,
            "adjustment": scope.adjustment,
            "source": scope.source,
            "request_fingerprint": scope.request_fingerprint,
            "requested_symbol_count": scope.requested_symbol_count,
            "returned_symbol_count": scope.returned_symbol_count,
            "accepted_symbol_count": scope.accepted_symbol_count,
            "excluded_symbol_count": scope.excluded_symbol_count,
            "complete": scope.complete,
            "response_fingerprint": scope.response_fingerprint,
            "sync_run_id": sync_run_id,
            "raw": scope.raw,
        }
        for scope in annotated
    ]
    statement = insert(table).values(values)
    update_columns = (
        "requested_symbol_count",
        "returned_symbol_count",
        "accepted_symbol_count",
        "excluded_symbol_count",
        "complete",
        "response_fingerprint",
        "sync_run_id",
        "raw",
    )
    statement = statement.on_conflict_do_update(
        index_elements=(
            table.c.trade_date,
            table.c.adjustment,
            table.c.source,
            table.c.request_fingerprint,
        ),
        set_={
            **{column: getattr(statement.excluded, column) for column in update_columns},
            "updated_at": func.now(),
        },
    )
    with session_scope() as session:
        session.execute(statement)


def _provenance(
    sync_run_id: int,
    requested_start: date,
    requested_end: date,
) -> dict[str, object]:
    return {
        "job_id": ADJUSTED_DAILY_SYNC_JOB_ID,
        "run_id": sync_run_id,
        "requested_range": {
            "start": requested_start.isoformat(),
            "end": requested_end.isoformat(),
        },
    }


def _main_board_predicate(column):
    return or_(*(column.like(pattern) for pattern in MAIN_BOARD_VT_PATTERNS))


def _calendar_summary(calendar: Sequence[date]) -> dict[str, object]:
    return {
        "trade_days": len(calendar),
        "start": calendar[0].isoformat() if calendar else None,
        "end": calendar[-1].isoformat() if calendar else None,
        "minimum_daily_symbols": MIN_RELIABLE_STOCK_SYMBOLS,
    }


def _target_payload(target: AdjustedDailyTarget) -> dict[str, object]:
    return {
        "vt_symbol": target.vt_symbol,
        "first_expected_date": target.first_expected_date.isoformat(),
        "last_expected_date": target.last_expected_date.isoformat(),
        "requested_row_count": target.requested_row_count,
        "accepted_row_count": target.accepted_row_count,
    }


def _failure_label(exc: Exception) -> str:
    message = str(exc).strip().replace("\n", " ")
    return f"{exc.__class__.__name__}: {message}"[:500]


def _scope_fingerprint(scopes: Iterable[QfqDailyScope]) -> str:
    return _json_fingerprint(
        [
            {
                "trade_date": scope.trade_date.isoformat(),
                "request_fingerprint": scope.request_fingerprint,
                "response_fingerprint": scope.response_fingerprint,
                "complete": scope.complete,
            }
            for scope in scopes
        ]
    )


def _json_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _batched(values: Sequence[date], size: int) -> Iterable[tuple[date, ...]]:
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def _report_progress(
    callback: Callable[[dict[str, object]], None] | None,
    *,
    current: int,
    total: int,
    rows_read: int,
    rows_written: int,
    current_label: str | None = None,
) -> None:
    if callback is None:
        return
    payload: dict[str, object] = {
        "current": current,
        "total": total,
        "rows_read": rows_read,
        "rows_written": rows_written,
    }
    if current_label:
        payload["current_label"] = current_label
    callback(payload)
