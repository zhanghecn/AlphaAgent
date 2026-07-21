"""Bounded data orchestration for pre-board transaction-flow research."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from hashlib import sha256
import json

import pandas as pd
from sqlalchemy import select, tuple_

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.data_providers.tdx_transaction_history import (
    iter_history_transactions,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    load_one_minute_bars,
    load_one_minute_coverage,
    load_static_hazard_manifest,
)
from alphaagent.server.services.limit_up.preboard_strategy_study import (
    FEATURE_LOOKBACK_SESSIONS,
    _build_all_strategy_prefix_rows,
    _feature_index,
    _load_bounded_feature_frame,
    _load_financial_index,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_VERSION,
    build_transaction_feature_capture,
)
from alphaagent.server.services.limit_up.preboard_strategy_replay import (
    STUDY_VERSION as STRATEGY_FILTER_VERSION,
    evaluate_static_shared_strategy_upper_bound,
)
from alphaagent.server.services.limit_up import preboard_transaction_repository as repository


MAX_TRANSACTION_BATCH_PAIRS = 500


def backfill_preboard_transaction_features(
    *,
    session_count: int = 89,
    max_pairs: int = MAX_TRANSACTION_BATCH_PAIRS,
    dry_run: bool = False,
) -> dict[str, object]:
    """Discover the exact v3 mother-pool pairs and fill one bounded batch."""

    pairs, pair_audit = resolve_shared_transaction_pairs(
        session_count=session_count,
        freeze_manifest=not dry_run,
    )
    result = sync_transaction_feature_pairs(
        pairs,
        max_pairs=max_pairs,
        dry_run=dry_run,
    )
    return {
        **result,
        "scope": "limit_up_preboard_transaction_flow",
        "session_count": int(session_count),
        "pair_audit": pair_audit,
    }


def freeze_shared_transaction_pair_manifest(
    *,
    session_count: int = 89,
) -> dict[str, object]:
    """Build and freeze the exact shared scope without fetching transactions."""

    pairs, audit = resolve_shared_transaction_pairs(
        session_count=session_count,
        freeze_manifest=True,
    )
    return {
        "status": str(audit.get("status") or "unknown"),
        "pair_count": len(pairs),
        "pair_audit": audit,
    }


def resolve_shared_transaction_pairs(
    *,
    session_count: int,
    freeze_manifest: bool,
) -> tuple[list[tuple[str, date]], dict[str, object]]:
    """Reuse an immutable scope or discover it once and optionally freeze it."""

    cached = repository.load_latest_transaction_pair_manifest(
        manifest_version=repository.PAIR_MANIFEST_VERSION,
        session_count=session_count,
    )
    if cached is not None:
        if str(cached.get("status") or "") != "ready":
            raise ValueError("cached transaction pair manifest is not ready")
        if str(cached.get("strategy_filter_version") or "") != STRATEGY_FILTER_VERSION:
            raise ValueError("cached transaction pair manifest strategy version differs")
        if str(cached.get("feature_version") or "") != TRANSACTION_FEATURE_VERSION:
            raise ValueError("cached transaction pair manifest feature version differs")
        pairs = _pairs_from_manifest(cached)
        return pairs, _pair_audit_from_manifest(cached, cache_status="already_frozen")

    pairs, pair_audit = load_shared_transaction_pairs(session_count=session_count)
    if str(pair_audit.get("status") or "") != "ready":
        return pairs, pair_audit
    manifest = build_shared_transaction_pair_manifest(
        pairs,
        pair_audit,
        session_count=session_count,
    )
    save_result: dict[str, object] = {
        "status": "not_frozen_dry_run",
        "manifest_written": 0,
    }
    if freeze_manifest:
        save_result = repository.save_transaction_pair_manifest(manifest)
        if save_result.get("status") == "fingerprint_conflict":
            raise ValueError("transaction pair manifest fingerprint conflict")
    return pairs, {
        **pair_audit,
        "pair_manifest": {
            "manifest_version": manifest["manifest_version"],
            "input_fingerprint": manifest["input_fingerprint"],
            "status": save_result.get("status"),
        },
    }


def load_shared_transaction_pairs(
    *,
    session_count: int,
) -> tuple[list[tuple[str, date]], dict[str, object]]:
    """Rebuild only stock-days that pass the causal v3 shared strategy."""

    manifest = load_static_hazard_manifest(session_count=session_count)
    if manifest.empty:
        return [], {"status": "blocked_by_manifest", "manifest_pair_count": 0}
    coverage = load_one_minute_coverage(manifest)
    complete_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    dates = set(pd.to_datetime(manifest["trade_date"], errors="raise").dt.date)
    feature_frame, feature_coverage = _load_bounded_feature_frame(
        manifest,
        lookback_sessions=FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = _feature_index(feature_frame, dates)
    financial_index = _load_financial_index()
    prefiltered_manifest, prefilter_audit = prefilter_shared_transaction_manifest(
        manifest,
        complete_pairs,
        feature_by_pair,
        financial_index,
    )
    minute_rows = load_one_minute_bars(prefiltered_manifest)
    prefix_rows, filter_audit = _build_all_strategy_prefix_rows(
        prefiltered_manifest,
        minute_rows,
        complete_pairs,
        feature_by_pair,
        financial_index,
        bar_minutes=1,
        passed_only=True,
        row_projection=lambda row: {
            "vt_symbol": row.get("vt_symbol"),
            "signal_date": row.get("signal_date"),
            "shared_strategy_passed": row.get("shared_strategy_passed"),
        },
    )
    filter_audit = {
        **filter_audit,
        "manifest_pair_count": int(len(manifest)),
        "static_prefilter": prefilter_audit,
    }
    pairs = shared_pairs_from_prefix_rows(prefix_rows)
    return pairs, {
        "status": "ready" if pairs else "empty_shared_strategy_scope",
        "start_date": pd.Timestamp(manifest["trade_date"].min()).date().isoformat(),
        "end_date": pd.Timestamp(manifest["trade_date"].max()).date().isoformat(),
        "manifest_pair_count": int(len(manifest)),
        "complete_minute_pair_count": len(complete_pairs),
        "shared_pair_count": len(pairs),
        "filter_audit": filter_audit,
        "feature_coverage": feature_coverage,
    }


def build_shared_transaction_pair_manifest(
    pairs: Sequence[tuple[str, date]],
    pair_audit: Mapping[str, object],
    *,
    session_count: int,
) -> dict[str, object]:
    """Build the deterministic immutable record for one discovered scope."""

    normalized = sorted(set(pairs), key=lambda pair: (pair[1], pair[0]))
    pair_rows = [
        {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
        for symbol, trade_date in normalized
    ]
    start_date = _as_date(pair_audit.get("start_date"))
    end_date = _as_date(pair_audit.get("end_date"))
    filter_audit = dict(pair_audit.get("filter_audit") or {})
    feature_coverage = dict(pair_audit.get("feature_coverage") or {})
    payload = {
        "manifest_version": repository.PAIR_MANIFEST_VERSION,
        "session_count": int(session_count),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "strategy_filter_version": STRATEGY_FILTER_VERSION,
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "manifest_pair_count": int(pair_audit.get("manifest_pair_count") or 0),
        "complete_minute_pair_count": int(
            pair_audit.get("complete_minute_pair_count") or 0
        ),
        "filter_audit": filter_audit,
        "feature_coverage": feature_coverage,
        "pairs": pair_rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("ascii")
    static_audit = dict(filter_audit.get("static_prefilter") or {})
    return {
        **payload,
        "start_date": start_date,
        "end_date": end_date,
        "status": "ready",
        "input_fingerprint": f"sha256:{sha256(encoded).hexdigest()}",
        "static_upper_bound_pair_count": int(
            static_audit.get("static_upper_bound_pair_count") or 0
        ),
        "shared_pair_count": len(pair_rows),
        "shared_prefix_count": int(filter_audit.get("shared_prefix_count") or 0),
    }


def _pairs_from_manifest(
    manifest: Mapping[str, object],
) -> list[tuple[str, date]]:
    raw_pairs = manifest.get("pairs")
    if not isinstance(raw_pairs, Sequence) or isinstance(raw_pairs, (str, bytes)):
        raise ValueError("cached transaction pair manifest has invalid pairs")
    pairs = [
        (
            str(row.get("vt_symbol") or ""),
            _as_date(row.get("trade_date")),
        )
        for row in raw_pairs
        if isinstance(row, Mapping)
    ]
    normalized = sorted(set(pairs), key=lambda pair: (pair[1], pair[0]))
    if len(normalized) != int(manifest.get("shared_pair_count") or 0):
        raise ValueError("cached transaction pair manifest pair count differs")
    return normalized


def _pair_audit_from_manifest(
    manifest: Mapping[str, object],
    *,
    cache_status: str,
) -> dict[str, object]:
    return {
        "status": "ready",
        "start_date": _as_date(manifest.get("start_date")).isoformat(),
        "end_date": _as_date(manifest.get("end_date")).isoformat(),
        "manifest_pair_count": int(manifest.get("manifest_pair_count") or 0),
        "complete_minute_pair_count": int(
            manifest.get("complete_minute_pair_count") or 0
        ),
        "shared_pair_count": int(manifest.get("shared_pair_count") or 0),
        "filter_audit": dict(manifest.get("filter_audit") or {}),
        "feature_coverage": dict(manifest.get("feature_coverage") or {}),
        "pair_manifest": {
            "manifest_version": str(manifest.get("manifest_version") or ""),
            "input_fingerprint": str(manifest.get("input_fingerprint") or ""),
            "status": cache_status,
        },
    }


def prefilter_shared_transaction_manifest(
    manifest: pd.DataFrame,
    complete_pairs: set[tuple[str, date]],
    feature_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    financial_index: object,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Keep a lossless upper bound before loading exact one-minute paths."""

    selected_indexes: list[object] = []
    rejection_counts: Counter[str] = Counter()
    missing_features = 0
    incomplete = 0
    for index, row in manifest.iterrows():
        manifest_row = row.to_dict()
        pair = (
            str(manifest_row.get("vt_symbol") or ""),
            _as_date(manifest_row.get("trade_date")),
        )
        if pair not in complete_pairs:
            incomplete += 1
            continue
        feature_row = feature_by_pair.get(pair)
        if feature_row is None:
            missing_features += 1
            continue
        upper_bound = evaluate_static_shared_strategy_upper_bound(
            manifest_row,
            feature_row,
            financial_index=financial_index,
        )
        if upper_bound.get("static_upper_bound_passed") is True:
            selected_indexes.append(index)
            continue
        blockers = list(upper_bound.get("shared_lane_blockers") or [])
        if blockers:
            rejection_counts.update(str(value) for value in blockers)
        else:
            rejection_counts.update(
                [str(upper_bound.get("profitability_gate_reason") or "unknown")]
            )
    selected = manifest.loc[selected_indexes].copy()
    selected = selected.sort_values(
        ["trade_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)
    return selected, {
        "input_pair_count": int(len(manifest)),
        "complete_pair_count": int(len(complete_pairs)),
        "missing_feature_pair_count": int(missing_features),
        "static_upper_bound_pair_count": int(len(selected)),
        "static_rejection_counts": dict(sorted(rejection_counts.items())),
        "incomplete_pair_count": int(incomplete),
    }


def shared_pairs_from_prefix_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[tuple[str, date]]:
    """Return deduplicated pairs that really passed the shared v3 strategy."""

    pairs: set[tuple[str, date]] = set()
    for row in rows:
        symbol = str(row.get("vt_symbol") or "").strip()
        signal_date = _optional_date(row.get("signal_date"))
        if symbol and signal_date is not None and row.get("shared_strategy_passed") is True:
            pairs.add((symbol, signal_date))
    return sorted(pairs, key=lambda pair: (pair[1], pair[0]))


def sync_transaction_feature_pairs(
    pairs: Sequence[tuple[str, date]],
    *,
    max_pairs: int = MAX_TRANSACTION_BATCH_PAIRS,
    dry_run: bool = False,
) -> dict[str, object]:
    """Fetch and freeze one exact bounded batch, never a broader universe."""

    limit = int(max_pairs)
    if limit < 1 or limit > MAX_TRANSACTION_BATCH_PAIRS:
        raise ValueError(
            f"max_pairs must be between 1 and {MAX_TRANSACTION_BATCH_PAIRS}"
        )
    normalized = sorted(set(pairs), key=lambda pair: (pair[1], pair[0]))
    coverage_before = repository.load_transaction_feature_coverage(
        normalized,
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    pending = [
        (str(row["vt_symbol"]), date.fromisoformat(str(row["trade_date"])))
        for row in coverage_before.get("pending_pairs") or []
    ]
    requested = pending[:limit]
    if dry_run or not requested:
        return _sync_summary(
            status="dry_run" if dry_run else "ready",
            pairs=normalized,
            requested=requested,
            coverage_before=coverage_before,
            coverage_after=coverage_before,
            rows_read=0,
            rows_written=0,
            scopes_written=0,
            save_status_counts={},
            errors=[],
            dry_run=dry_run,
        )

    daily_by_pair = load_transaction_daily_bars(requested)
    fetch_requests = [pair for pair in requested if pair in daily_by_pair]
    errors = [
        f"{symbol} {trade_date.isoformat()}: daily_bar_missing"
        for symbol, trade_date in requested
        if (symbol, trade_date) not in daily_by_pair
    ]
    rows_read = 0
    rows_written = 0
    scopes_written = 0
    save_status_counts: Counter[str] = Counter()
    try:
        for fetched in iter_history_transactions(fetch_requests):
            symbol = str(fetched.get("vt_symbol") or "")
            trade_date = _as_date(fetched.get("trade_date"))
            daily_bar = daily_by_pair.get((symbol, trade_date))
            if daily_bar is None:
                errors.append(f"{symbol} {trade_date.isoformat()}: daily_bar_missing")
                continue
            scope, feature_rows = build_transaction_feature_capture(
                symbol,
                trade_date,
                fetched,
                daily_bar,
            )
            saved = repository.save_transaction_feature_capture(scope, feature_rows)
            save_status_counts[str(saved.get("status") or "unknown")] += 1
            rows_read += int(fetched.get("raw_row_count") or 0)
            rows_written += int(saved.get("rows_written") or 0)
            scopes_written += int(saved.get("scope_written") or 0)
    except Exception as exc:
        errors.append(f"transaction_provider: {exc.__class__.__name__}: {exc}")

    coverage_after = repository.load_transaction_feature_coverage(
        normalized,
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    remaining = int(len(coverage_after.get("pending_pairs") or []))
    status = "ready" if remaining == 0 and not errors else "partial"
    if errors and rows_written == 0:
        status = "error"
    return _sync_summary(
        status=status,
        pairs=normalized,
        requested=requested,
        coverage_before=coverage_before,
        coverage_after=coverage_after,
        rows_read=rows_read,
        rows_written=rows_written,
        scopes_written=scopes_written,
        save_status_counts=dict(sorted(save_status_counts.items())),
        errors=errors,
        dry_run=False,
    )


def load_transaction_daily_bars(
    pairs: Sequence[tuple[str, date]],
) -> dict[tuple[str, date], dict[str, object]]:
    """Load authoritative daily bars for exact requested pairs."""

    normalized = sorted(set(pairs), key=lambda pair: (pair[1], pair[0]))
    if not normalized:
        return {}
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.stock_daily_bars
    with session_scope() as session:
        rows = session.execute(
            select(
                table.c.vt_symbol,
                table.c.trade_date,
                table.c.high_price,
                table.c.low_price,
                table.c.close_price,
                table.c.volume,
                table.c.source,
            ).where(tuple_(table.c.vt_symbol, table.c.trade_date).in_(normalized))
        ).mappings().all()
    return {
        (str(row["vt_symbol"]), _as_date(row["trade_date"])): dict(row)
        for row in rows
    }


def _sync_summary(
    *,
    status: str,
    pairs: Sequence[tuple[str, date]],
    requested: Sequence[tuple[str, date]],
    coverage_before: Mapping[str, object],
    coverage_after: Mapping[str, object],
    rows_read: int,
    rows_written: int,
    scopes_written: int,
    save_status_counts: Mapping[str, int],
    errors: Sequence[str],
    dry_run: bool,
) -> dict[str, object]:
    ready_before = int(coverage_before.get("ready_pair_count") or 0)
    ready_after = int(coverage_after.get("ready_pair_count") or 0)
    remaining = len(coverage_after.get("pending_pairs") or [])
    return {
        "status": status,
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "pair_count": len(pairs),
        "requested_gap_count": len(requested),
        "covered_gap_count": max(ready_after - ready_before, 0),
        "remaining_pending_pair_count": remaining,
        "rows_read": int(rows_read),
        "rows_written": int(rows_written),
        "scopes_written": int(scopes_written),
        "save_status_counts": dict(save_status_counts),
        "coverage_before": dict(coverage_before),
        "coverage_after": dict(coverage_after),
        "errors": list(errors)[:50],
        "dry_run": bool(dry_run),
        "message": (
            f"逐笔资金流特征：本批完整 {max(ready_after - ready_before, 0)}/"
            f"{len(requested)}，总覆盖 {ready_after}/{len(pairs)}"
        ),
    }


def _optional_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_date(value: object) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError(f"invalid trade date: {value}")
    return parsed
