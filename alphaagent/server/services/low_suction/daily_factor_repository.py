"""Persistent qfq inputs for the isolated daily low-suction factor study."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import and_, func, or_, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
from alphaagent.server.services.data_providers.adjusted_daily_import import (
    ADJUSTED_DAILY_SYNC_JOB_ID,
)

from .adjusted_daily_bars import (
    QFQ_ADJUSTMENT,
    QFQ_SOURCE,
    QfqDailyScope,
    build_qfq_daily_scope,
)


RESEARCH_VERSION = "low-suction-daily-factor-v1"
MIN_RELIABLE_STOCK_SYMBOLS = 3_000
# The current local stock-daily inventory first reaches the frozen coverage
# threshold on this date.  A caller can still explicitly request an earlier
# range when a future data rebuild provides enough cross-sectional coverage.
EARLIEST_VERIFIED_RELIABLE_TRADE_DATE = date(2023, 3, 28)
RAW_STUDY_LOOKBACK_CALENDAR_DAYS = 120
QFQ_SCOPE_QUERY_BATCH_DAYS = 20
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
SECURITY_EVIDENCE_STRICT = "strict"
SECURITY_EVIDENCE_RECONSTRUCTED = "reconstructed"
PRICE_BASIS_QFQ = "qfq"
PRICE_BASIS_RAW_UNADJUSTED = "raw_unadjusted"
PRICE_BASES = (PRICE_BASIS_QFQ, PRICE_BASIS_RAW_UNADJUSTED)
RAW_FINGERPRINT_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "close_price",
    "high_price",
    "low_price",
    "volume",
    "turnover",
    "source",
    "updated_at",
)


class DailyFactorRepositoryError(RuntimeError):
    """Raised when the durable daily-factor input contract cannot be satisfied."""


@dataclass(frozen=True)
class QfqScopeAudit:
    """Current rows plus their persisted daily-scope proof."""

    scopes: tuple[QfqDailyScope, ...]
    persisted_complete_dates: tuple[date, ...]
    missing_or_stale_dates: tuple[date, ...]

    @property
    def complete(self) -> bool:
        return bool(self.scopes) and not self.missing_or_stale_dates

    def as_dict(self) -> dict[str, object]:
        incomplete = [scope for scope in self.scopes if not scope.complete]
        return {
            "canonical_sync_job_id": ADJUSTED_DAILY_SYNC_JOB_ID,
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


@dataclass(frozen=True)
class DailyFactorInputs:
    """Read-only normalized inputs used by the daily-factor study runner."""

    market_calendar: tuple[date, ...]
    bars: pd.DataFrame
    security_status: pd.DataFrame
    evidence_level: str
    blockers: tuple[str, ...]
    coverage: dict[str, object]
    input_sha256: str


def audit_daily_factor_inputs(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    """Audit qfq and security prerequisites without downloading or writing data."""

    engine = get_engine()
    _ensure_daily_factor_schema(engine)
    with session_scope() as session:
        calendar = _reliable_market_calendar(
            session,
            start_date=start_date,
            end_date=end_date,
        )
        scope_audit = _collect_qfq_scope_audit(session, calendar)
        security = _security_scope_inventory(session, calendar)
    return {
        "research_version": RESEARCH_VERSION,
        "market_calendar": _calendar_summary(calendar),
        "adjusted_prices": scope_audit.as_dict(),
        "security_status": security,
        "evidence_level": _audit_evidence_level(scope_audit, security),
    }


def load_daily_factor_inputs(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    price_basis: str = PRICE_BASIS_QFQ,
    vt_symbols: Sequence[str] | None = None,
) -> DailyFactorInputs:
    """Load either strict qfq inputs or an explicitly exploratory raw snapshot.

    The default qfq path remains fail-closed.  ``raw_unadjusted`` is an
    explicitly labelled exploratory path over the nightly canonical raw table;
    it never qualifies a rule for product use.
    """

    if price_basis not in PRICE_BASES:
        raise DailyFactorRepositoryError(
            f"unsupported daily-factor price basis: {price_basis}"
        )
    normalized_symbols = _normalized_vt_symbols(vt_symbols)
    if normalized_symbols and price_basis != PRICE_BASIS_RAW_UNADJUSTED:
        raise DailyFactorRepositoryError(
            "symbol-filtered daily-factor inputs only support raw_unadjusted"
        )

    engine = get_engine()
    with session_scope() as session:
        calendar = _reliable_market_calendar(
            session,
            start_date=start_date,
            end_date=end_date,
        )

    coverage = {
        "market_calendar": _calendar_summary(calendar),
        "price_basis": price_basis,
    }
    if not calendar:
        return _blocked_inputs(
            calendar,
            blockers=("no_reliable_market_calendar",),
            coverage=coverage,
        )
    if price_basis == PRICE_BASIS_RAW_UNADJUSTED:
        bars = (
            _load_raw_daily_bars(engine, calendar, vt_symbols=normalized_symbols)
            if normalized_symbols
            else _load_raw_daily_bars(engine, calendar)
        )
        coverage["raw_unadjusted_prices"] = {
            **_raw_unadjusted_coverage(bars, calendar),
            "vt_symbols_filter": list(normalized_symbols) or None,
        }
        coverage["security_status"] = {
            "status": "missing",
            "warning": "historical_security_status_not_applied",
        }
        return DailyFactorInputs(
            market_calendar=calendar,
            bars=bars,
            security_status=_empty_security_frame(),
            evidence_level="exploratory_raw_unadjusted",
            blockers=(),
            coverage=coverage,
            input_sha256=_raw_inputs_fingerprint(calendar, bars),
        )

    _ensure_daily_factor_schema(engine)
    with session_scope() as session:
        scope_audit = _collect_qfq_scope_audit(session, calendar)
    coverage["adjusted_prices"] = scope_audit.as_dict()
    if not scope_audit.complete:
        return _blocked_inputs(
            calendar,
            blockers=("adjusted_qfq_scope_incomplete",),
            coverage=coverage,
            evidence_level="blocked_by_adjusted_prices",
        )

    bars = _load_qfq_bars(engine, calendar)
    security_status = _load_security_status(engine, calendar)
    security_coverage = _security_coverage_for_bars(bars, security_status)
    coverage["adjusted_prices"] = {
        **scope_audit.as_dict(),
        "bar_rows": int(len(bars)),
        "bar_symbols": int(bars["vt_symbol"].nunique()) if not bars.empty else 0,
    }
    coverage["security_status"] = security_coverage
    blockers: tuple[str, ...] = ()
    evidence_level = "strict"
    if security_coverage["missing_bar_pair_count"]:
        blockers = ("security_status_scope_incomplete",)
        evidence_level = "blocked_by_security_status"
    elif security_coverage["reconstructed_bar_pair_count"]:
        evidence_level = "exploratory_reconstructed_security"
    input_sha256 = _inputs_fingerprint(
        calendar,
        bars,
        security_status,
        scope_audit.scopes,
    )
    return DailyFactorInputs(
        market_calendar=calendar,
        bars=bars,
        security_status=security_status,
        evidence_level=evidence_level,
        blockers=blockers,
        coverage=coverage,
        input_sha256=input_sha256,
    )


def _blocked_inputs(
    calendar: tuple[date, ...],
    *,
    blockers: tuple[str, ...],
    coverage: dict[str, object],
    evidence_level: str = "blocked_by_adjusted_prices",
) -> DailyFactorInputs:
    return DailyFactorInputs(
        market_calendar=calendar,
        bars=_empty_bars_frame(),
        security_status=_empty_security_frame(),
        evidence_level=evidence_level,
        blockers=blockers,
        coverage=coverage,
        input_sha256=_json_fingerprint(
            {
                "calendar": [value.isoformat() for value in calendar],
                "coverage": coverage,
                "blockers": blockers,
            }
        ),
    )


def _ensure_daily_factor_schema(engine) -> None:
    """Create only the tables owned by this isolated research protocol."""

    for table in (
        schema.low_suction_adjusted_daily_bars,
        schema.low_suction_adjusted_daily_bar_scopes,
        schema.low_suction_security_history,
        schema.low_suction_security_history_scopes,
    ):
        table.create(engine, checkfirst=True)


def _reliable_market_calendar(
    session,
    *,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, ...]:
    stock_daily = schema.stock_daily_bars
    effective_start = start_date or EARLIEST_VERIFIED_RELIABLE_TRADE_DATE
    conditions = [
        stock_daily.c.trade_date >= effective_start,
        stock_daily.c.trade_date <= completed_daily_bar_cutoff(),
    ]
    if end_date is not None:
        conditions.append(stock_daily.c.trade_date <= end_date)
    rows = session.execute(
        select(
            stock_daily.c.trade_date,
            # (vt_symbol, trade_date) is the table primary key, so a plain count
            # is exactly the cross-sectional symbol count and can use the date
            # index without an expensive DISTINCT aggregate.
            func.count(),
        )
        .where(*conditions)
        .group_by(stock_daily.c.trade_date)
        .order_by(stock_daily.c.trade_date)
    ).all()
    return tuple(
        row[0] for row in rows if int(row[1] or 0) >= MIN_RELIABLE_STOCK_SYMBOLS
    )


def _canonical_qfq_sync_join(table):
    """Join a qfq table to the successful data-sync run that produced it."""

    runs = schema.sync_job_runs
    return table.join(
        runs,
        and_(
            runs.c.id == table.c.sync_run_id,
            runs.c.job_id == ADJUSTED_DAILY_SYNC_JOB_ID,
            runs.c.status == "succeeded",
        ),
    )


def _collect_qfq_scope_audit(
    session,
    calendar: Sequence[date],
) -> QfqScopeAudit:
    if not calendar:
        return QfqScopeAudit((), (), ())
    stock_daily = schema.stock_daily_bars
    adjusted = schema.low_suction_adjusted_daily_bars
    canonical_adjusted = _canonical_qfq_sync_join(adjusted)
    join_condition = and_(
        adjusted.c.vt_symbol == stock_daily.c.vt_symbol,
        adjusted.c.trade_date == stock_daily.c.trade_date,
        adjusted.c.adjustment == QFQ_ADJUSTMENT,
        adjusted.c.source == QFQ_SOURCE,
    )
    scopes: list[QfqDailyScope] = []
    for date_batch in _batched(calendar, QFQ_SCOPE_QUERY_BATCH_DAYS):
        statement = (
            select(
                stock_daily.c.trade_date,
                stock_daily.c.vt_symbol,
                adjusted.c.source_fingerprint,
            )
            .select_from(stock_daily.outerjoin(canonical_adjusted, join_condition))
            .where(
                stock_daily.c.trade_date.in_(date_batch),
                _main_board_predicate(stock_daily.c.vt_symbol),
            )
            .order_by(stock_daily.c.trade_date, stock_daily.c.vt_symbol)
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
                )
            )

        for row in session.execute(statement).all():
            trade_date = row[0]
            if current_date is not None and trade_date != current_date:
                append_scope()
                expected_symbols = []
                accepted = {}
            current_date = trade_date
            symbol = str(row[1])
            expected_symbols.append(symbol)
            if row[2]:
                accepted[symbol] = str(row[2])
        append_scope()

    persisted = _persisted_qfq_scopes(session, scopes)
    persisted_complete = tuple(
        scope.trade_date
        for scope in scopes
        if _persisted_scope_matches(scope, persisted.get((scope.trade_date, scope.request_fingerprint)))
    )
    missing_or_stale = tuple(
        scope.trade_date
        for scope in scopes
        if not scope.complete
        or scope.trade_date not in set(persisted_complete)
    )
    return QfqScopeAudit(
        scopes=tuple(scopes),
        persisted_complete_dates=persisted_complete,
        missing_or_stale_dates=missing_or_stale,
    )


def _persisted_qfq_scopes(
    session,
    scopes: Sequence[QfqDailyScope],
) -> dict[tuple[date, str], Mapping[str, object]]:
    if not scopes:
        return {}
    table = schema.low_suction_adjusted_daily_bar_scopes
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
        .select_from(_canonical_qfq_sync_join(table))
        .where(
            table.c.adjustment == QFQ_ADJUSTMENT,
            table.c.source == QFQ_SOURCE,
            table.c.trade_date.in_(tuple(scope.trade_date for scope in scopes)),
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


def _load_qfq_bars(engine, calendar: Sequence[date]) -> pd.DataFrame:
    if not calendar:
        return _empty_bars_frame()
    table = schema.low_suction_adjusted_daily_bars
    statement = (
        select(
            table.c.vt_symbol,
            table.c.trade_date,
            table.c.open_price,
            table.c.close_price,
            table.c.high_price,
            table.c.low_price,
            table.c.volume,
            table.c.turnover,
            table.c.source,
            table.c.source_fingerprint,
            table.c.sync_run_id,
        )
        .select_from(_canonical_qfq_sync_join(table))
        .where(
            table.c.adjustment == QFQ_ADJUSTMENT,
            table.c.source == QFQ_SOURCE,
            table.c.trade_date.in_(tuple(calendar)),
            _main_board_predicate(table.c.vt_symbol),
        )
        .order_by(table.c.vt_symbol, table.c.trade_date)
    )
    frame = pd.read_sql(statement, engine, parse_dates=["trade_date"])
    if frame.empty:
        return _empty_bars_frame()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def _load_raw_daily_bars(
    engine,
    calendar: Sequence[date],
    *,
    vt_symbols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Read canonical nightly raw prices plus a fixed MA lookback window."""

    if not calendar:
        return _empty_bars_frame()
    table = schema.stock_daily_bars
    history_start = calendar[0] - timedelta(days=RAW_STUDY_LOOKBACK_CALENDAR_DAYS)
    conditions = [
        table.c.trade_date >= history_start,
        table.c.trade_date <= calendar[-1],
        _main_board_predicate(table.c.vt_symbol),
    ]
    if vt_symbols:
        conditions.append(table.c.vt_symbol.in_(tuple(vt_symbols)))
    statement = (
        select(
            table.c.vt_symbol,
            table.c.trade_date,
            table.c.open_price,
            table.c.close_price,
            table.c.high_price,
            table.c.low_price,
            table.c.volume,
            table.c.turnover,
            table.c.turnover_rate,
            table.c.source,
            table.c.updated_at,
        )
        .where(*conditions)
        .order_by(table.c.vt_symbol, table.c.trade_date)
    )
    frame = pd.read_sql(statement, engine, parse_dates=["trade_date", "updated_at"])
    if frame.empty:
        return _empty_bars_frame()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def _load_security_status(engine, calendar: Sequence[date]) -> pd.DataFrame:
    if not calendar:
        return _empty_security_frame()
    scopes = schema.low_suction_security_history_scopes
    history = schema.low_suction_security_history
    statement = (
        select(
            scopes.c.trade_date,
            scopes.c.vt_symbol,
            scopes.c.evidence_level,
            scopes.c.source,
            history.c.status,
            history.c.board,
            history.c.listed_on,
            history.c.delisted_on,
            history.c.suspended,
            history.c.risk_warning,
        )
        .select_from(
            scopes.join(
                history,
                and_(
                    history.c.source == scopes.c.source,
                    history.c.evidence_level == scopes.c.evidence_level,
                    history.c.vt_symbol == scopes.c.vt_symbol,
                    history.c.valid_from <= scopes.c.trade_date,
                    history.c.valid_to > scopes.c.trade_date,
                ),
            )
        )
        .where(
            scopes.c.trade_date.in_(tuple(calendar)),
            scopes.c.evidence_level.in_(
                (SECURITY_EVIDENCE_STRICT, SECURITY_EVIDENCE_RECONSTRUCTED)
            ),
            _main_board_predicate(scopes.c.vt_symbol),
        )
        .order_by(
            scopes.c.trade_date,
            scopes.c.vt_symbol,
            scopes.c.evidence_level,
            scopes.c.source,
        )
    )
    frame = pd.read_sql(statement, engine, parse_dates=["trade_date", "listed_on", "delisted_on"])
    if frame.empty:
        return _empty_security_frame()
    for column in ("trade_date", "listed_on", "delisted_on"):
        frame[column] = pd.to_datetime(frame[column]).dt.date
    frame["_evidence_rank"] = frame["evidence_level"].map(
        {
            SECURITY_EVIDENCE_STRICT: 0,
            SECURITY_EVIDENCE_RECONSTRUCTED: 1,
        }
    )
    return (
        frame.sort_values(
            ["trade_date", "vt_symbol", "_evidence_rank", "source"],
            kind="stable",
        )
        .drop_duplicates(["trade_date", "vt_symbol"], keep="first")
        .drop(columns=["_evidence_rank"])
        .reset_index(drop=True)
    )


def _security_coverage_for_bars(
    bars: pd.DataFrame,
    security_status: pd.DataFrame,
) -> dict[str, object]:
    if bars.empty:
        return {
            "bar_pair_count": 0,
            "covered_bar_pair_count": 0,
            "missing_bar_pair_count": 0,
            "strict_bar_pair_count": 0,
            "reconstructed_bar_pair_count": 0,
            "status_rows": int(len(security_status)),
        }
    merged = bars[["trade_date", "vt_symbol"]].merge(
        security_status[["trade_date", "vt_symbol", "evidence_level"]],
        on=["trade_date", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    covered = merged["evidence_level"].notna()
    return {
        "bar_pair_count": int(len(merged)),
        "covered_bar_pair_count": int(covered.sum()),
        "missing_bar_pair_count": int((~covered).sum()),
        "strict_bar_pair_count": int(
            (merged["evidence_level"] == SECURITY_EVIDENCE_STRICT).sum()
        ),
        "reconstructed_bar_pair_count": int(
            (merged["evidence_level"] == SECURITY_EVIDENCE_RECONSTRUCTED).sum()
        ),
        "status_rows": int(len(security_status)),
    }


def _security_scope_inventory(session, calendar: Sequence[date]) -> dict[str, object]:
    if not calendar:
        return {"providers": [], "status": "unavailable"}
    scopes = schema.low_suction_security_history_scopes
    rows = session.execute(
        select(
            scopes.c.evidence_level,
            scopes.c.source,
            func.count(),
            func.count(func.distinct(scopes.c.trade_date)),
            func.count(func.distinct(scopes.c.vt_symbol)),
        )
        .where(
            scopes.c.trade_date.in_(tuple(calendar)),
            _main_board_predicate(scopes.c.vt_symbol),
        )
        .group_by(scopes.c.evidence_level, scopes.c.source)
        .order_by(scopes.c.evidence_level, scopes.c.source)
    ).all()
    providers = [
        {
            "evidence_level": str(row[0]),
            "source": str(row[1]),
            "scope_pairs": int(row[2] or 0),
            "trade_days": int(row[3] or 0),
            "symbols": int(row[4] or 0),
        }
        for row in rows
    ]
    return {
        "providers": providers,
        "status": "ready" if providers else "missing",
    }


def _audit_evidence_level(
    scope_audit: QfqScopeAudit,
    security: Mapping[str, object],
) -> str:
    if not scope_audit.complete:
        return "blocked_by_adjusted_prices"
    providers = security.get("providers")
    if not providers:
        return "blocked_by_security_status"
    evidence_levels = {
        str(provider.get("evidence_level"))
        for provider in providers
        if isinstance(provider, Mapping)
    }
    if evidence_levels == {SECURITY_EVIDENCE_STRICT}:
        return "strict"
    return "exploratory_reconstructed_security"


def _main_board_predicate(column):
    return or_(*(column.like(pattern) for pattern in MAIN_BOARD_VT_PATTERNS))


def _normalized_vt_symbols(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    normalized = tuple(sorted({str(value).strip().upper() for value in values if str(value).strip()}))
    if not normalized:
        raise DailyFactorRepositoryError("vt_symbols cannot be empty when declared")
    return normalized


def _calendar_summary(calendar: Sequence[date]) -> dict[str, object]:
    return {
        "trade_days": len(calendar),
        "start": calendar[0].isoformat() if calendar else None,
        "end": calendar[-1].isoformat() if calendar else None,
        "minimum_daily_symbols": MIN_RELIABLE_STOCK_SYMBOLS,
    }


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


def _inputs_fingerprint(
    calendar: Sequence[date],
    bars: pd.DataFrame,
    security_status: pd.DataFrame,
    scopes: Sequence[QfqDailyScope],
) -> str:
    digest = hashlib.sha256()
    for value in calendar:
        digest.update(f"calendar|{value.isoformat()}\n".encode("utf-8"))
    for row in bars.itertuples(index=False):
        digest.update(
            (
                "bar|"
                f"{row.vt_symbol}|{row.trade_date.isoformat()}|"
                f"{row.source_fingerprint}|{row.sync_run_id}\n"
            ).encode("utf-8")
        )
    for row in security_status.itertuples(index=False):
        digest.update(
            (
                "security|"
                f"{row.vt_symbol}|{row.trade_date.isoformat()}|"
                f"{row.evidence_level}|{row.source}\n"
            ).encode("utf-8")
        )
    digest.update(_scope_fingerprint(scopes).encode("ascii"))
    return digest.hexdigest()


def _raw_inputs_fingerprint(
    calendar: Sequence[date],
    bars: pd.DataFrame,
) -> str:
    """Fingerprint every raw input value, not only its table-level metadata."""

    digest = hashlib.sha256()
    digest.update(f"research_version|{RESEARCH_VERSION}\n".encode("utf-8"))
    digest.update(f"price_basis|{PRICE_BASIS_RAW_UNADJUSTED}\n".encode("utf-8"))
    for trade_date in calendar:
        digest.update(f"calendar|{trade_date.isoformat()}\n".encode("utf-8"))
    if not bars.empty:
        for row in bars.loc[:, RAW_FINGERPRINT_COLUMNS].itertuples(
            index=False,
            name=None,
        ):
            digest.update(
                json.dumps(
                    row,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _raw_unadjusted_coverage(
    bars: pd.DataFrame,
    calendar: Sequence[date],
) -> dict[str, object]:
    return {
        "bar_rows": int(len(bars)),
        "bar_symbols": int(bars["vt_symbol"].nunique()) if not bars.empty else 0,
        "history_start": (
            calendar[0] - timedelta(days=RAW_STUDY_LOOKBACK_CALENDAR_DAYS)
        ).isoformat(),
        "study_start": calendar[0].isoformat(),
        "study_end": calendar[-1].isoformat(),
        "warning": "unadjusted_prices_can_be_distorted_by_corporate_actions",
        "d1_label_policy": "exclude_main_board_price_limit_outliers",
    }


def _empty_bars_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=(
            "vt_symbol",
            "trade_date",
            "open_price",
            "close_price",
            "high_price",
            "low_price",
            "volume",
            "turnover",
            "turnover_rate",
            "source",
            "source_fingerprint",
            "sync_run_id",
            "updated_at",
        )
    )


def _empty_security_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=(
            "trade_date",
            "vt_symbol",
            "evidence_level",
            "source",
            "status",
            "board",
            "listed_on",
            "delisted_on",
            "suspended",
            "risk_warning",
        )
    )


def _json_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _batched(values: Sequence[date], size: int) -> Iterable[tuple[date, ...]]:
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])
