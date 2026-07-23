"""Bounded data orchestration for pre-board transaction-flow research."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
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
from alphaagent.server.services.limit_up import (
    history_engine,
    history_repository,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.first_board_quality import (
    evaluate_first_board_quality_at_time,
)
from alphaagent.server.services.limit_up.lane_repository import (
    FinancialIndex,
    build_financial_index,
    financial_risk_as_of,
    financial_snapshot_as_of,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    build_one_minute_backfill_gaps,
    load_one_minute_bars,
    load_one_minute_coverage,
    load_static_hazard_capture_manifest_with_audit,
    load_static_hazard_manifest,
)
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
)
from alphaagent.server.services.limit_up.preboard_decision_features import (
    build_lane_prefix,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_VERSION,
    build_transaction_feature_capture,
)
from alphaagent.server.services.limit_up import preboard_transaction_repository as repository


MAX_TRANSACTION_BATCH_PAIRS = 500
DECISION_PAIR_MANIFEST_VERSION = "limit-up-preboard-decision-pairs-v2"
DECISION_SCOPE_LOOKBACK_SESSIONS = 140

_DECISION_SCOPE_STATIC_FIELDS = (
    "industry_id",
    "industry_name",
    "auction_gap_pct",
    "prior_streak",
    "prior_break_streak",
    "prior_limit_count_126",
    "prior_touch_count_126",
    "prior_limit_count_5",
    "prior_limit_count_10",
    "prior_seal_success_rate_126",
    "trade_days_since_prior_limit",
    "pullback_from_prior_limit_pct",
    "prior_position_120",
    "prior_change_pct",
    "prior_open_gap_pct",
    "prior_low_change_pct",
    "prior_amplitude_pct",
    "prior_return_5d_pct",
    "prior_return_20d_pct",
    "prior_turnover_rate",
    "prior_amount_ratio_5d",
    "prior_industry_change_pct",
    "prior_industry_return_5d_pct",
    "prior_industry_advancing_rate",
    "prior_industry_turnover_ratio_5d",
    "prior_industry_sealed_count",
    "prior_industry_sealed_rate",
    "prior_industry_heat_score",
    "prior_industry_heat_rank",
    "prior_industry_count",
    "prior_industry_leadership_score",
    "prior_industry_leader_rank",
    "prior_industry_stock_count",
    "prior_market_phase",
    "prior_market_advancing_rate",
    "prior_market_sealed_count",
    "prior_market_failed_rate",
    "prior_market_max_board",
    "prior_market_first_board_count",
    "prior_market_one_to_two_rate",
    "prior_market_two_to_three_rate",
)


@dataclass(frozen=True)
class PreboardDecisionStaticScope:
    manifest: pd.DataFrame
    minute_manifest: pd.DataFrame
    feature_by_pair: Mapping[tuple[str, date], Mapping[str, object]]
    financial_index: object
    feature_coverage: dict[str, object]
    prefilter_audit: dict[str, object]
    static_pair_audit: Mapping[tuple[str, date], Mapping[str, object]] = field(
        default_factory=dict
    )


def backfill_preboard_decision_transaction_features(
    *,
    session_count: int = 89,
    end_date: date | None = None,
    max_pairs: int = MAX_TRANSACTION_BATCH_PAIRS,
    dry_run: bool = False,
) -> dict[str, object]:
    """Fill transaction features for the complete static decision-model scope."""

    resolve_kwargs: dict[str, object] = {
        "session_count": session_count,
        "freeze_manifest": not dry_run,
    }
    if end_date is not None:
        resolve_kwargs["end_date"] = end_date
    pairs, pair_audit = resolve_preboard_decision_pairs(**resolve_kwargs)
    result = sync_transaction_feature_pairs(
        pairs,
        max_pairs=max_pairs,
        dry_run=dry_run,
    )
    return {
        **result,
        "scope": "limit_up_preboard_decision_transaction_flow",
        "session_count": int(session_count),
        "end_date": end_date.isoformat() if end_date is not None else None,
        "pair_audit": pair_audit,
    }


def backfill_preboard_decision_minutes(
    *,
    session_count: int = 81,
    end_date: date | None = None,
    max_gaps: int = 2_000,
    max_pages_per_symbol: int = 64,
    dry_run: bool = False,
) -> dict[str, object]:
    """Fill the exact static decision scope before path-dependent filtering."""

    if not 1 <= int(max_gaps) <= 20_000:
        raise ValueError("max_gaps must be between 1 and 20000")
    if not 1 <= int(max_pages_per_symbol) <= 82:
        raise ValueError("max_pages_per_symbol must be between 1 and 82")
    scope, scope_audit = load_preboard_decision_static_scope(
        session_count=session_count,
        end_date=end_date,
    )
    if scope is None:
        return {
            **scope_audit,
            "scope": "limit_up_preboard_decision_1m",
            "dry_run": dry_run,
        }
    coverage_before = load_one_minute_coverage(scope.minute_manifest)
    gaps = build_one_minute_backfill_gaps(
        coverage_before,
        max_pairs=max_gaps,
    )
    provider_result: dict[str, object] = {
        "status": "ready",
        "rows_read": 0,
        "rows_written": 0,
    }
    if gaps:
        from alphaagent.server.services.data_providers.tdx_minute_import import (
            import_tdx_minute_bars_for_gaps,
        )

        provider_result = import_tdx_minute_bars_for_gaps(
            gaps=gaps,
            interval="1m",
            tail_entry_start="09:31",
            tail_entry_end="15:00",
            dry_run=dry_run,
            max_gaps=len(gaps),
            max_pages_per_symbol=max_pages_per_symbol,
            timeout_seconds=3.0,
        )
    coverage_after = (
        coverage_before
        if dry_run
        else load_one_minute_coverage(scope.minute_manifest)
    )
    return _decision_minute_backfill_report(
        scope_audit,
        coverage_after,
        gaps=gaps,
        provider_result=provider_result,
        dry_run=dry_run,
    )


def freeze_preboard_decision_pair_manifest(
    *,
    session_count: int = 89,
    end_date: date | None = None,
) -> dict[str, object]:
    """Freeze the independent static-quality decision-model scope."""

    resolve_kwargs: dict[str, object] = {
        "session_count": session_count,
        "freeze_manifest": True,
    }
    if end_date is not None:
        resolve_kwargs["end_date"] = end_date
    pairs, audit = resolve_preboard_decision_pairs(**resolve_kwargs)
    return {
        "status": str(audit.get("status") or "unknown"),
        "pair_count": len(pairs),
        "pair_audit": audit,
    }


def resolve_preboard_decision_pairs(
    *,
    session_count: int,
    end_date: date | None = None,
    manifest_version: str = DECISION_PAIR_MANIFEST_VERSION,
    freeze_manifest: bool,
) -> tuple[list[tuple[str, date]], dict[str, object]]:
    """Reuse or discover the static-quality decision-model stock-day scope."""

    cache_kwargs: dict[str, object] = {
        "manifest_version": manifest_version,
        "session_count": session_count,
    }
    if end_date is not None:
        cache_kwargs["end_date"] = end_date
    cached = repository.load_latest_transaction_pair_manifest(**cache_kwargs)
    if cached is not None:
        _validate_cached_pair_manifest(
            cached,
            strategy_filter_version=PREBOARD_DECISION_VERSION,
        )
        pairs = _pairs_from_manifest(cached)
        audit = _pair_audit_from_manifest(cached, cache_status="already_frozen")
        return pairs, {**audit, "decision_pair_count": len(pairs)}
    if manifest_version != DECISION_PAIR_MANIFEST_VERSION:
        return [], {
            "status": "blocked_by_missing_frozen_pair_manifest",
            "manifest_version": manifest_version,
            "decision_pair_count": 0,
        }

    load_kwargs: dict[str, object] = {"session_count": session_count}
    if end_date is not None:
        load_kwargs["end_date"] = end_date
    pairs, pair_audit = load_preboard_decision_pairs(**load_kwargs)
    if str(pair_audit.get("status") or "") != "ready":
        return pairs, pair_audit
    manifest = build_preboard_decision_pair_manifest(
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
            raise ValueError("preboard decision pair manifest fingerprint conflict")
    return pairs, {
        **pair_audit,
        "pair_manifest": {
            "manifest_version": manifest["manifest_version"],
            "input_fingerprint": manifest["input_fingerprint"],
            "status": save_result.get("status"),
        },
    }


def load_preboard_decision_pairs(
    *,
    session_count: int,
    end_date: date | None = None,
) -> tuple[list[tuple[str, date]], dict[str, object]]:
    """Build the complete causal >=3% pre-touch static-quality scope."""

    scope, static_audit = load_preboard_decision_static_scope(
        session_count=session_count,
        end_date=end_date,
    )
    if scope is None:
        return [], static_audit
    coverage = load_one_minute_coverage(scope.minute_manifest)
    complete_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    missing_minute_pair_count = len(scope.minute_manifest) - len(complete_pairs)
    coverage_status_counts = {
        str(key): int(value)
        for key, value in coverage["coverage_status"].value_counts().items()
    }
    common_audit = {
        **static_audit,
        "complete_minute_pair_count": len(complete_pairs),
        "missing_minute_pair_count": missing_minute_pair_count,
        "minute_coverage_status_counts": coverage_status_counts,
    }
    if missing_minute_pair_count:
        return [], {
            **common_audit,
            "status": "blocked_by_one_minute_coverage",
            "decision_pair_count": 0,
        }
    minute_rows = load_one_minute_bars(scope.minute_manifest)
    prefix_rows, filter_audit = _build_decision_scope_prefix_rows(
        scope.minute_manifest,
        minute_rows,
        complete_pairs,
        scope.feature_by_pair,
        scope.financial_index,
    )
    filter_audit = {
        **filter_audit,
        "manifest_pair_count": int(len(scope.manifest)),
        "static_prefilter": scope.prefilter_audit,
    }
    pairs = decision_pairs_from_prefix_rows(prefix_rows)
    return pairs, {
        "status": "ready" if pairs else "empty_preboard_decision_scope",
        **common_audit,
        "decision_pair_count": len(pairs),
        "filter_audit": filter_audit,
        "feature_coverage": scope.feature_coverage,
    }


def load_preboard_decision_static_scope(
    *,
    session_count: int,
    end_date: date | None = None,
) -> tuple[PreboardDecisionStaticScope | None, dict[str, object]]:
    """Freeze the minute backfill universe without reading intraday outcomes."""

    manifest = load_static_hazard_manifest(
        session_count=session_count,
        end_date=end_date,
    )
    return _build_preboard_decision_static_scope(
        manifest,
        empty_status="blocked_by_manifest",
        membership_rule="bounded_historical_manifest_requires_mature_d1_result",
        d1_membership_required=True,
    )


def load_preboard_decision_static_scope_for_dates(
    *,
    start_date: date,
    end_date: date,
) -> tuple[PreboardDecisionStaticScope | None, dict[str, object]]:
    """Build recent static scope without requiring any D+1 outcome."""

    manifest, audited_manifest = load_static_hazard_capture_manifest_with_audit(
        start_date=start_date,
        end_date=end_date,
    )
    return _build_preboard_decision_static_scope(
        manifest,
        empty_status="blocked_by_capture_manifest",
        membership_rule="daily_high_crossed_3pct_with_prior_only_static_quality_no_d1",
        d1_membership_required=False,
        static_pair_audit=_static_hazard_pair_audit(audited_manifest),
    )


def _build_preboard_decision_static_scope(
    manifest: pd.DataFrame,
    *,
    empty_status: str,
    membership_rule: str,
    d1_membership_required: bool,
    static_pair_audit: Mapping[
        tuple[str, date], Mapping[str, object]
    ] | None = None,
) -> tuple[PreboardDecisionStaticScope | None, dict[str, object]]:
    pair_audit = dict(static_pair_audit or {})
    static_rejection_counts = dict(
        sorted(
            Counter(
                str(row.get("static_hazard_gate_reason") or "unknown")
                for row in pair_audit.values()
                if row.get("static_hazard_gate_passed") is not True
            ).items()
        )
    )
    if manifest.empty:
        return None, {
            "status": empty_status,
            "manifest_pair_count": 0,
            "raw_capture_pair_count": len(pair_audit),
            "static_hazard_rejected_pair_count": sum(
                static_rejection_counts.values()
            ),
            "static_hazard_rejection_counts": static_rejection_counts,
            "membership_rule": membership_rule,
            "d1_membership_required": d1_membership_required,
        }
    dates = set(pd.to_datetime(manifest["trade_date"], errors="raise").dt.date)
    feature_frame, feature_coverage = _load_decision_scope_feature_frame(
        manifest,
        lookback_sessions=DECISION_SCOPE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = _decision_scope_feature_index(feature_frame, dates)
    financial_index = _load_decision_scope_financial_index()
    static_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in manifest.itertuples()
    }
    minute_manifest, prefilter_audit = _prefilter_decision_scope_manifest(
        manifest,
        static_pairs,
        feature_by_pair,
        financial_index,
    )
    status = "ready" if not minute_manifest.empty else "empty_preboard_decision_static_scope"
    audit = {
        "status": status,
        "start_date": pd.Timestamp(manifest["trade_date"].min()).date().isoformat(),
        "end_date": pd.Timestamp(manifest["trade_date"].max()).date().isoformat(),
        "manifest_pair_count": int(len(manifest)),
        "raw_capture_pair_count": len(pair_audit) or int(len(manifest)),
        "static_hazard_rejected_pair_count": sum(static_rejection_counts.values()),
        "static_hazard_rejection_counts": static_rejection_counts,
        "static_scope_pair_count": int(len(minute_manifest)),
        "membership_rule": membership_rule,
        "d1_membership_required": d1_membership_required,
        "filter_audit": {"static_prefilter": prefilter_audit},
        "feature_coverage": feature_coverage,
    }
    if minute_manifest.empty:
        return None, audit
    return (
        PreboardDecisionStaticScope(
            manifest=manifest,
            minute_manifest=minute_manifest,
            feature_by_pair=feature_by_pair,
            financial_index=financial_index,
            feature_coverage=dict(feature_coverage),
            prefilter_audit=dict(prefilter_audit),
            static_pair_audit=pair_audit,
        ),
        audit,
    )


def _static_hazard_pair_audit(
    frame: pd.DataFrame,
) -> dict[tuple[str, date], dict[str, object]]:
    """Index prior-only static gate evidence without outcome fields."""

    result: dict[tuple[str, date], dict[str, object]] = {}
    for raw in frame.to_dict(orient="records"):
        symbol = str(raw.get("vt_symbol") or "").strip()
        trade_date = _optional_date(raw.get("trade_date"))
        if not symbol or trade_date is None:
            continue
        passed = raw.get("static_hazard_gate_passed") is True
        reason = str(raw.get("static_hazard_gate_reason") or "unknown")
        result[(symbol, trade_date)] = {
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "name": str(raw.get("name") or ""),
            "static_hazard_gate_passed": passed,
            "static_hazard_gate_reason": reason,
            "pool_stage": "static_hazard_passed" if passed else "capture_rejected",
            "rejection_codes": () if passed else (reason,),
            "stock_d1_sample_count": _plain_value(
                raw.get("stock_d1_sample_count")
            ),
            "stock_d1_win_rate": _plain_value(raw.get("stock_d1_win_rate")),
            "stock_d1_average_return_pct": _plain_value(
                raw.get("stock_d1_average_return_pct")
            ),
            "stock_gene_combined_win_rate": _plain_value(
                raw.get("stock_gene_combined_win_rate")
            ),
        }
    return result


def _build_transaction_pair_manifest(
    pairs: Sequence[tuple[str, date]],
    pair_audit: Mapping[str, object],
    *,
    session_count: int,
    manifest_version: str,
    strategy_filter_version: str,
    prefix_count_field: str,
) -> dict[str, object]:
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
        "manifest_version": manifest_version,
        "session_count": int(session_count),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "strategy_filter_version": strategy_filter_version,
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
        "shared_prefix_count": int(filter_audit.get(prefix_count_field) or 0),
    }


def build_preboard_decision_pair_manifest(
    pairs: Sequence[tuple[str, date]],
    pair_audit: Mapping[str, object],
    *,
    session_count: int,
) -> dict[str, object]:
    """Build an immutable decision scope without altering the legacy manifest."""

    return _build_transaction_pair_manifest(
        pairs,
        pair_audit,
        session_count=session_count,
        manifest_version=DECISION_PAIR_MANIFEST_VERSION,
        strategy_filter_version=PREBOARD_DECISION_VERSION,
        prefix_count_field="static_model_prefix_count",
    )


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


def _validate_cached_pair_manifest(
    manifest: Mapping[str, object],
    *,
    strategy_filter_version: str,
) -> None:
    if str(manifest.get("status") or "") != "ready":
        raise ValueError("cached transaction pair manifest is not ready")
    if str(manifest.get("strategy_filter_version") or "") != strategy_filter_version:
        raise ValueError("cached transaction pair manifest strategy version differs")
    if str(manifest.get("feature_version") or "") != TRANSACTION_FEATURE_VERSION:
        raise ValueError("cached transaction pair manifest feature version differs")


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


def _load_decision_scope_feature_frame(
    manifest: pd.DataFrame,
    *,
    lookback_sessions: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    evaluation_start = pd.to_datetime(manifest["trade_date"]).min().normalize()
    evaluation_end = pd.to_datetime(manifest["trade_date"]).max().normalize()
    raw_frame, raw_coverage = history_repository.load_reliable_history_frame(
        evaluation_start=evaluation_start.date(),
        evaluation_end=evaluation_end.date(),
        lookback_sessions=max(int(lookback_sessions), 1),
    )
    all_dates = sorted(pd.to_datetime(raw_frame["trade_date"]).dropna().unique())
    if not all_dates:
        return pd.DataFrame(), {
            "feature_context_start": None,
            "feature_loaded_rows": 0,
            "feature_computed_rows": 0,
            "feature_source_loaded_rows": int(raw_coverage.get("loaded_rows") or 0),
            "industry_membership_mode": raw_coverage.get("industry_membership_mode"),
            "industry_membership_survivorship_risk": raw_coverage.get(
                "industry_membership_survivorship_risk"
            ),
        }
    start_index = next(
        (index for index, value in enumerate(all_dates) if value >= evaluation_start),
        len(all_dates) - 1,
    )
    context_start = all_dates[max(start_index - max(int(lookback_sessions), 1), 0)]
    bounded = raw_frame.loc[raw_frame["trade_date"].ge(context_start)].copy()
    feature_frame = history_engine.build_daily_feature_frame(bounded)
    return feature_frame, {
        "feature_context_start": pd.Timestamp(context_start).date().isoformat(),
        "feature_loaded_rows": int(len(bounded)),
        "feature_computed_rows": int(len(feature_frame)),
        "feature_source_loaded_rows": int(raw_coverage.get("loaded_rows") or 0),
        "industry_membership_mode": raw_coverage.get("industry_membership_mode"),
        "industry_membership_survivorship_risk": raw_coverage.get(
            "industry_membership_survivorship_risk"
        ),
    }


def _load_decision_scope_financial_index() -> FinancialIndex:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = [
            dict(row)
            for row in session.execute(
                select(schema.stock_financial_reports)
            ).mappings()
        ]
    return build_financial_index(rows)


def _decision_scope_feature_index(
    frame: pd.DataFrame,
    evaluation_dates: set[date],
) -> dict[tuple[str, date], dict[str, object]]:
    if frame.empty:
        return {}
    selected = frame.loc[
        pd.to_datetime(frame["trade_date"]).dt.date.isin(evaluation_dates)
    ]
    return {
        (str(row["vt_symbol"]), _as_date(row["trade_date"])): dict(row)
        for row in selected.to_dict(orient="records")
    }


def _prefilter_decision_scope_manifest(
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
        upper_bound = _evaluate_decision_scope_upper_bound(
            manifest_row,
            feature_row,
            financial_index=financial_index,
        )
        if upper_bound.get("static_upper_bound_passed") is True:
            selected_indexes.append(index)
            continue
        blockers = list(upper_bound.get("lane_blockers") or [])
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


def _evaluate_decision_scope_upper_bound(
    manifest_row: Mapping[str, object],
    feature_row: Mapping[str, object],
    *,
    financial_index: object,
) -> dict[str, object]:
    """Apply the shared quality gate to a best-case causal path for lossless prefiltering."""

    static_candidate = _decision_scope_static_candidate(
        manifest_row,
        feature_row,
        financial_index=financial_index,
    )
    trade_date = _optional_date(manifest_row.get("trade_date"))
    previous_close = _number(manifest_row.get("previous_close"))
    limit_price = _number(manifest_row.get("limit_price"))
    if trade_date is None or previous_close is None or previous_close <= 0 or limit_price is None:
        return {
            "static_upper_bound_passed": False,
            "profitability_gate_reason": "invalid_static_identity",
            "lane_blockers": ("invalid_static_identity",),
        }
    decision_at = datetime.combine(trade_date, datetime.strptime("10:30", "%H:%M").time())
    last_price = min(previous_close * 1.09, limit_price - 0.01)
    candidate = {
        **static_candidate,
        "decision_at": decision_at.isoformat(),
        "signal_time": "10:30:00",
        "entry_window_passed": True,
        "state": "near_limit",
        "action": "observe",
        "last_price": last_price,
        "change_pct": _return_pct(previous_close, last_price),
        "path_prefix": {
            "signal_time": "10:30:00",
            "last_point_time": "10:30:00",
            "point_count": 60,
            "last_pct": 9.0,
            "maximum_pct": 9.0,
            "minimum_pct": 0.0,
            "recent_15m_min_pct": 3.0,
            "recent_15m_change_pct": 6.0,
            "recent_15m_range_pct": 6.0,
            "recent_15m_drawdown_pct": 0.0,
            "recent_30m_min_pct": 0.0,
            "recent_30m_change_pct": 9.0,
            "touch_count": 0,
            "break_count": 0,
            "reseal_count": 0,
            "is_at_limit": False,
            "approach_3point_pct": 6.0,
        },
        "snapshot_fresh": True,
        "quote_fresh": True,
    }
    evaluated = evaluate_first_board_quality_at_time(
        candidate,
        decision_at=decision_at,
        market_gate={"passed": True},
        execution_checks=(),
    )
    return {
        "static_upper_bound_passed": evaluated.get("quality_gate_passed") is True,
        "profitability_gate_reason": evaluated.get("profitability_gate_reason"),
        "lane_blockers": tuple(evaluated.get("lane_blockers") or ()),
    }


def _build_decision_scope_prefix_rows(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
    complete_pairs: set[tuple[str, date]],
    feature_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    financial_index: object,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    manifests = {
        (str(row["vt_symbol"]), _as_date(row["trade_date"])): dict(row)
        for row in manifest.to_dict(orient="records")
    }
    minute = minute_rows.copy()
    minute["trade_date"] = pd.to_datetime(minute["trade_date"]).dt.date
    rows: list[dict[str, object]] = []
    lane_blockers: Counter[str] = Counter()
    evaluated_pair_count = 0
    missing_feature_pair_count = 0
    quality_pairs: set[tuple[str, date]] = set()

    for pair, group in minute.groupby(["vt_symbol", "trade_date"], sort=False):
        normalized_pair = (str(pair[0]), _as_date(pair[1]))
        if normalized_pair not in complete_pairs:
            continue
        manifest_row = manifests.get(normalized_pair)
        feature_row = feature_by_pair.get(normalized_pair)
        if manifest_row is None:
            continue
        if feature_row is None:
            missing_feature_pair_count += 1
            continue
        evaluated_pair_count += 1
        static_candidate = _decision_scope_static_candidate(
            manifest_row,
            feature_row,
            financial_index=financial_index,
        )
        ordered = sorted(
            group.to_dict(orient="records"),
            key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
        )
        previous_close = _number(manifest_row.get("previous_close"))
        limit_price = _number(manifest_row.get("limit_price"))
        if previous_close is None or previous_close <= 0 or limit_price is None:
            continue
        for index, bar in enumerate(ordered):
            decision_at = _as_datetime(bar.get("bar_time"))
            if decision_at is None:
                continue
            if (_number(bar.get("high_price")) or float("-inf")) >= limit_price - 0.001:
                break
            last_price = _number(bar.get("close_price"))
            change_pct = _return_pct(previous_close, last_price)
            if (
                change_pct is None
                or change_pct < 3.0
                or not scheduled_execution.is_entry_time(decision_at.time())
            ):
                continue
            candidate = {
                **static_candidate,
                "decision_at": decision_at.isoformat(),
                "signal_time": decision_at.time().replace(microsecond=0).isoformat(),
                "entry_window_passed": True,
                "state": "near_limit",
                "action": "observe",
                "last_price": last_price,
                "change_pct": change_pct,
                "path_prefix": build_lane_prefix(
                    ordered,
                    index,
                    previous_close=previous_close,
                    bar_minutes=1,
                ),
                "snapshot_fresh": False,
                "quote_fresh": False,
            }
            evaluated = evaluate_first_board_quality_at_time(
                candidate,
                decision_at=decision_at,
                market_gate={"passed": False},
                execution_checks=(),
            )
            eligible = evaluated.get("quality_gate_passed") is True
            lane_blockers.update(str(value) for value in evaluated.get("lane_blockers") or ())
            row = {
                "vt_symbol": normalized_pair[0],
                "signal_date": normalized_pair[1].isoformat(),
                "decision_at": decision_at.isoformat(),
                "change_pct": change_pct,
                "quality_gate_passed": eligible,
                "lane_decision": evaluated.get("lane_decision"),
                "lane_blockers": tuple(evaluated.get("lane_blockers") or ()),
                "profitability_gate_passed": evaluated.get("profitability_gate_passed"),
                "profitability_gate_reason": evaluated.get("profitability_gate_reason"),
            }
            rows.append(row)
            if eligible:
                quality_pairs.add(normalized_pair)

    return rows, {
        "evaluated_pair_count": evaluated_pair_count,
        "evaluated_prefix_count": len(rows),
        "static_model_pair_count": len(quality_pairs),
        "static_model_prefix_count": sum(
            row.get("quality_gate_passed") is True for row in rows
        ),
        "missing_feature_pair_count": missing_feature_pair_count,
        "lane_blocker_counts": dict(sorted(lane_blockers.items())),
    }


def _decision_scope_static_candidate(
    manifest_row: Mapping[str, object],
    feature_row: Mapping[str, object],
    *,
    financial_index: object,
) -> dict[str, object]:
    trade_date = _as_date(manifest_row.get("trade_date"))
    symbol = str(manifest_row.get("vt_symbol") or "")
    financial_snapshot = feature_row.get("financial_snapshot")
    if not isinstance(financial_snapshot, Mapping):
        financial_snapshot = financial_snapshot_as_of(
            financial_index,
            symbol,
            trade_date,
        )
    financial_risk = feature_row.get("financial_risk")
    if not isinstance(financial_risk, Mapping):
        financial_risk = financial_risk_as_of(
            financial_index,
            symbol,
            trade_date,
        )
    candidate = {
        key: _plain_value(feature_row.get(key))
        for key in _DECISION_SCOPE_STATIC_FIELDS
    }
    candidate.update(
        {
            key: _plain_value(manifest_row.get(key))
            for key in (
                "stock_d1_sample_count",
                "stock_d1_win_count",
                "stock_d1_win_rate",
                "stock_d1_average_return_pct",
                "stock_gene_combined_win_rate",
            )
        }
    )
    candidate.update(
        {
            "vt_symbol": symbol,
            "name": str(manifest_row.get("name") or ""),
            "trade_date": trade_date.isoformat(),
            "signal_date": trade_date.isoformat(),
            "board_lane": "first_board",
            "board_level": 1,
            "target_board": 1,
            "prior_streak": 0,
            "previous_limit_up": bool(manifest_row.get("prior_day_limit_up")),
            "previous_close": _number(manifest_row.get("previous_close")),
            "limit_price": _number(manifest_row.get("limit_price")),
            "financial_snapshot": (
                dict(financial_snapshot)
                if isinstance(financial_snapshot, Mapping)
                else None
            ),
            "financial_risk": dict(financial_risk),
            "risk_gate_passed": financial_risk.get("blocked") is False,
            "universe_gate_passed": manifest_row.get("eligible_main_board") is not False,
            "signal_kind": "momentum",
            "source_mode": "causal_decision_scope_complete_one_minute_path",
            "has_l2": False,
            "historical_evidence": {},
        }
    )
    return candidate


def decision_pairs_from_prefix_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[tuple[str, date]]:
    """Return stock-days with at least one point-in-time shared quality pass."""

    pairs: set[tuple[str, date]] = set()
    for row in rows:
        symbol = str(row.get("vt_symbol") or "").strip()
        signal_date = _optional_date(row.get("signal_date"))
        if symbol and signal_date is not None and row.get("quality_gate_passed") is True:
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


def _decision_minute_backfill_report(
    scope_audit: Mapping[str, object],
    coverage: pd.DataFrame,
    *,
    gaps: Sequence[Mapping[str, object]],
    provider_result: Mapping[str, object],
    dry_run: bool,
) -> dict[str, object]:
    requested = {
        (str(row.get("vt_symbol") or ""), _as_date(row.get("trade_date")))
        for row in gaps
    }
    complete = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    covered = requested & complete
    provider_status = str(provider_result.get("status") or "unknown")
    remaining = int((~coverage["coverage_status"].eq("complete")).sum())
    if provider_status in {"error", "unavailable", "unsupported_interval"}:
        status = provider_status
    elif dry_run:
        status = "dry_run"
    elif remaining:
        status = "partial"
    else:
        status = "ready"
    return {
        **dict(provider_result),
        **dict(scope_audit),
        "status": status,
        "scope": "limit_up_preboard_decision_1m",
        "requested_gap_count": len(requested),
        "covered_gap_count": len(covered),
        "complete_minute_pair_count": len(complete),
        "remaining_missing_pair_count": remaining,
        "coverage_status_counts": {
            str(key): int(value)
            for key, value in coverage["coverage_status"].value_counts().items()
        },
        "dry_run": dry_run,
    }


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def _return_pct(base: float | None, value: float | None) -> float | None:
    if base is None or base <= 0 or value is None:
        return None
    return (value / base - 1.0) * 100.0


def _plain_value(value: object) -> object:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            return value
    return value


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


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage causal pre-board transaction-flow research data"
    )
    parser.add_argument(
        "command",
        choices=(
            "backfill-decision-minutes",
            "backfill-decision",
            "freeze-decision",
        ),
    )
    parser.add_argument("--sessions", type=int, default=89)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--max-pairs", type=int, default=MAX_TRANSACTION_BATCH_PAIRS)
    parser.add_argument("--max-gaps", type=int, default=2_000)
    parser.add_argument("--max-pages-per-symbol", type=int, default=64)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "freeze-decision":
        result = freeze_preboard_decision_pair_manifest(
            session_count=args.sessions,
            end_date=args.end_date,
        )
    elif args.command == "backfill-decision-minutes":
        result = backfill_preboard_decision_minutes(
            session_count=args.sessions,
            end_date=args.end_date,
            max_gaps=args.max_gaps,
            max_pages_per_symbol=args.max_pages_per_symbol,
            dry_run=args.dry_run,
        )
    else:
        result = backfill_preboard_decision_transaction_features(
            session_count=args.sessions,
            end_date=args.end_date,
            max_pairs=args.max_pairs,
            dry_run=args.dry_run,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
