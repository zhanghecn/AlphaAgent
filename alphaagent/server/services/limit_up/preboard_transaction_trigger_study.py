"""Historical v4 transaction-flow counterexample for pre-board actions."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from statistics import mean
from time import monotonic

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy
from alphaagent.server.services.limit_up import preboard_joint_trigger_study as v3
from alphaagent.server.services.limit_up import preboard_transaction_data
from alphaagent.server.services.limit_up import preboard_transaction_disposition
from alphaagent.server.services.limit_up import preboard_transaction_repository
from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    attach_competing_risk_targets,
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    load_one_minute_bars,
    load_one_minute_coverage,
    load_static_hazard_manifest,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD as V3_ACTION_SCORE_FIELD,
    ACTION_TARGET_FIELD,
    PREPARE_TARGET_FIELD,
    attach_joint_trigger_targets,
    probability_calibration_report,
    score_joint_trigger_rows,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)
from alphaagent.server.services.limit_up.preboard_transaction_trigger_model import (
    TRANSACTION_ACTION_SCORE_FIELD,
    TRANSACTION_PREPARE_SCORE_FIELD,
    TRANSACTION_TRIGGER_FEATURE_NAMES,
    TransactionTriggerModelFit,
    calibrate_transaction_threshold,
    fit_transaction_trigger_model,
    score_transaction_trigger_rows,
    transaction_trigger_feature_vector,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


STUDY_VERSION = "limit-up-preboard-transaction-trigger-v4"
DEFAULT_SESSION_COUNT = 89
MINIMUM_TRANSACTION_COVERAGE_PCT = 100.0
MINIMUM_NORMAL_ACCOUNT_PROFIT_FACTOR = 1.2
V3_REFERENCE_PREPARE_FINGERPRINT = "dad05e19169d9b24"
V3_REFERENCE_ACTION_FINGERPRINT = "0fa5bf1592cbe59c"
V3_REFERENCE_ACTION_THRESHOLD = 0.15
STRICT_V4_COVERAGE = "strict_v4"
EXPLICIT_NO_ACTION_V5_COVERAGE = "explicit_no_action_v5"


def join_transaction_features(
    prefix_rows: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Join only the same stock-day completed minute; later flow stays unused."""

    feature_index: dict[tuple[str, date, str], dict[str, object]] = {}
    for raw in feature_rows:
        row = dict(raw)
        key = _transaction_key(row)
        if key in feature_index:
            raise ValueError(f"duplicate transaction feature minute: {key}")
        values = row.get("values")
        values = dict(values) if isinstance(values, Mapping) else {}
        feature_index[key] = {
            "values": values,
            "feature_version": row.get("feature_version"),
            "input_fingerprint": row.get("input_fingerprint"),
        }

    used: set[tuple[str, date, str]] = set()
    joined: list[dict[str, object]] = []
    scoreable = 0
    missing_prefixes: list[dict[str, object]] = []
    missing_feature_minute_count = 0
    invalid_feature_value_count = 0
    for raw in prefix_rows:
        row = dict(raw)
        key = _prefix_key(row)
        matched = feature_index.get(key)
        values = dict(matched.get("values") or {}) if matched else None
        if values is not None and _valid_transaction_values(values):
            scoreable += 1
            used.add(key)
        else:
            if matched is None:
                reason = "feature_minute_missing"
                missing_feature_minute_count += 1
                invalid_features: list[str] = []
            else:
                reason = "invalid_feature_values"
                invalid_feature_value_count += 1
                invalid_features = [
                    name
                    for name in TRANSACTION_FEATURE_NAMES
                    if _number(values.get(name) if values is not None else None) is None
                ]
            missing_prefixes.append(
                {
                    "vt_symbol": key[0],
                    "signal_date": key[1].isoformat(),
                    "signal_time": key[2],
                    "reason": reason,
                    "invalid_features": invalid_features,
                }
            )
            values = None
        joined.append(
            {
                **row,
                "transaction_features": values,
                "transaction_feature_version": (
                    matched.get("feature_version") if matched else None
                ),
                "transaction_input_fingerprint": (
                    matched.get("input_fingerprint") if matched else None
                ),
            }
        )
    prefix_count = len(prefix_rows)
    return joined, {
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "prefix_count": prefix_count,
        "scoreable_prefix_count": scoreable,
        "missing_prefix_count": prefix_count - scoreable,
        "scoreable_prefix_pct": _percentage(scoreable, prefix_count),
        "missing_feature_minute_count": missing_feature_minute_count,
        "invalid_feature_value_count": invalid_feature_value_count,
        "missing_prefixes": missing_prefixes,
        "transaction_feature_count": len(feature_index),
        "used_transaction_feature_count": len(used),
        "unused_transaction_feature_count": len(feature_index) - len(used),
    }


def build_transaction_trigger_analysis(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
    baseline_parity: Mapping[str, object],
    v3_reference_parity: Mapping[str, object],
    transaction_coverage: Mapping[str, object],
    coverage_contract: str = STRICT_V4_COVERAGE,
) -> tuple[
    dict[str, object],
    dict[str, TransactionTriggerModelFit],
    dict[str, object],
]:
    """Fit v4 and replay it through the unchanged v3 execution contract."""

    identity_labeled = attach_competing_risk_targets(prefix_rows, formal_orders)
    joint_labeled = attach_joint_trigger_targets(identity_labeled, formal_orders)
    enriched_rows = enrich_same_minute_competition(joint_labeled)
    prepare_model = fit_transaction_trigger_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=PREPARE_TARGET_FIELD,
    )
    action_model = fit_transaction_trigger_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=ACTION_TARGET_FIELD,
    )
    prepare_rows = score_transaction_trigger_rows(
        enriched_rows,
        prepare_model,
        score_field=TRANSACTION_PREPARE_SCORE_FIELD,
    )
    action_rows = score_transaction_trigger_rows(enriched_rows, action_model)
    threshold = calibrate_transaction_threshold(
        action_rows,
        calibration_dates=calibration_dates,
        minimum_selection_count=v3.MINIMUM_CALIBRATION_SELECTIONS,
        confirmation_minutes=v3.CONFIRMATION_MINUTES,
        max_daily_actions=v3.MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    aliased_rows = [_alias_v4_action_score(row) for row in action_rows]
    action_threshold = threshold.threshold if threshold.threshold is not None else 1.1
    normal_bundle = v3.build_joint_replay_orders(
        action_rows=aliased_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
    )
    conservative_bundle = v3.build_joint_replay_orders(
        action_rows=aliased_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
        conservative_entry=True,
    )
    diagnostic_observations = v3._legacy_score_alias(enriched_rows)
    diagnostic_scores = v3._legacy_score_alias(aliased_rows)
    diagnostic_signals = v3._legacy_score_alias(normal_bundle["action_signals"])
    phases: dict[str, dict[str, object]] = {}
    for phase, allowed_dates in {
        "full": fit_dates | calibration_dates | validation_dates,
        "validation": validation_dates,
    }.items():
        phases[phase] = v3._phase_report(
            enriched_rows=enriched_rows,
            formal_orders=formal_orders,
            action_signals=normal_bundle["action_signals"],
            action_orders=normal_bundle["combined_orders"],
            conservative_orders=conservative_bundle["combined_orders"],
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
            diagnostic_observations=diagnostic_observations,
            diagnostic_scores=diagnostic_scores,
            diagnostic_signals=diagnostic_signals,
            action_threshold=action_threshold,
        )
    validation_blocks: list[dict[str, object]] = []
    for index, block_dates in enumerate(
        legacy._fixed_validation_blocks(validation_dates),
        start=1,
    ):
        block_set = set(block_dates)
        validation_blocks.append(
            {
                "block": index,
                "date_range": legacy._date_range(block_dates),
                **v3._phase_report(
                    enriched_rows=enriched_rows,
                    formal_orders=formal_orders,
                    action_signals=normal_bundle["action_signals"],
                    action_orders=normal_bundle["combined_orders"],
                    conservative_orders=conservative_bundle["combined_orders"],
                    bars=bars,
                    trade_dates=trade_dates,
                    allowed_dates=block_set,
                    diagnostic_observations=(),
                    diagnostic_scores=(),
                    diagnostic_signals=(),
                    action_threshold=action_threshold,
                    include_attribution=False,
                ),
            }
        )
    validation = _mapping(phases.get("validation"))
    acceptance = build_transaction_acceptance_report(
        validation,
        validation_blocks=validation_blocks,
        models=(prepare_model, action_model),
        threshold=threshold,
        baseline_parity=baseline_parity,
        v3_reference_parity=v3_reference_parity,
        transaction_coverage=transaction_coverage,
        coverage_contract=coverage_contract,
    )
    models = {"prepare_5m": prepare_model, "joint_action_3m": action_model}
    analysis = {
        "dataset": legacy._dataset_report(enriched_rows),
        "models": {key: _model_report(model) for key, model in models.items()},
        "threshold_selection": v3._threshold_report(threshold),
        "probability_calibration": {
            "calibration": probability_calibration_report(
                aliased_rows,
                allowed_dates=calibration_dates,
            ),
            "validation": probability_calibration_report(
                aliased_rows,
                allowed_dates=validation_dates,
            ),
        },
        "prepare_score_count": len(prepare_rows),
        "phases": phases,
        "validation_blocks": validation_blocks,
        "signal_counts": {
            "action": len(normal_bundle["action_signals"]),
            "fillable_action": len(normal_bundle["early_orders"]),
        },
        "acceptance": acceptance,
        "decision": (
            "historical_pass_forward_shadow_only"
            if acceptance["passed"] is True
            else "historical_rejected_no_live_promotion"
        ),
    }
    artifacts = {
        "enriched_rows": enriched_rows,
        "action_rows": aliased_rows,
        "action_signals": normal_bundle["action_signals"],
        "combined_orders": normal_bundle["combined_orders"],
    }
    return analysis, models, artifacts


def build_transaction_acceptance_report(
    validation: Mapping[str, object],
    *,
    validation_blocks: Sequence[Mapping[str, object]],
    models: Sequence[object],
    threshold: object,
    baseline_parity: Mapping[str, object],
    v3_reference_parity: Mapping[str, object],
    transaction_coverage: Mapping[str, object],
    coverage_contract: str = STRICT_V4_COVERAGE,
) -> dict[str, object]:
    """Apply every v3 account gate plus v4 coverage and profit-factor gates."""

    base = v3._acceptance_report(
        validation,
        validation_blocks=validation_blocks,
        models=models,
        threshold=threshold,
        baseline_parity=baseline_parity,
    )
    action = _mapping(
        _mapping(validation.get("accounts")).get("joint_action")
    )
    coverage_checks: dict[str, bool]
    if coverage_contract == STRICT_V4_COVERAGE:
        coverage_checks = {
            "transaction_prefix_coverage_100pct": (
                _number(transaction_coverage.get("scoreable_prefix_pct")) == 100.0
            ),
        }
    elif coverage_contract == EXPLICIT_NO_ACTION_V5_COVERAGE:
        disposition = preboard_transaction_disposition.build_disposition_coverage_checks(
            transaction_coverage
        )
        coverage_checks = {
            str(name): bool(value)
            for name, value in _mapping(disposition.get("checks")).items()
        }
    else:
        raise ValueError(f"unsupported transaction coverage contract: {coverage_contract}")
    checks = {
        **_mapping(base.get("checks")),
        "v3_reference_parity": v3_reference_parity.get("passed") is True,
        "transaction_scope_coverage_100pct": (
            _number(transaction_coverage.get("scope_ready_pair_pct")) == 100.0
        ),
        **coverage_checks,
        "minimum_1_2_normal_account_profit_factor": (
            (_number(action.get("profit_factor")) or -1e9)
            >= MINIMUM_NORMAL_ACCOUNT_PROFIT_FACTOR
        ),
    }
    return {
        **base,
        "passed": all(checks.values()),
        "checks": checks,
        "transaction_feature_coverage_required_pct": (
            MINIMUM_TRANSACTION_COVERAGE_PCT
        ),
        "minimum_normal_account_profit_factor": (
            MINIMUM_NORMAL_ACCOUNT_PROFIT_FACTOR
        ),
        "coverage_contract": coverage_contract,
    }


def evaluate_preboard_transaction_trigger(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    """Run the frozen 89-session v3/v4 same-account historical comparison."""

    return _evaluate_preboard_transaction_trigger(
        session_count=session_count,
        study_version=STUDY_VERSION,
        coverage_contract=STRICT_V4_COVERAGE,
        candidate_key="v4",
    )


def _evaluate_preboard_transaction_trigger(
    *,
    session_count: int,
    study_version: str,
    coverage_contract: str,
    candidate_key: str,
    candidate_analysis_builder: Callable[..., tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]] | None = None,
    candidate_confirmation_minutes: int = v3.CONFIRMATION_MINUTES,
    candidate_action_model_key: str = "joint_action_3m",
    candidate_label: str | None = None,
    historical_validation_kind: str = "viewed_expanded_historical_time_validation",
) -> dict[str, object]:
    """Run one frozen coverage policy through the shared historical replay."""

    if coverage_contract not in {
        STRICT_V4_COVERAGE,
        EXPLICIT_NO_ACTION_V5_COVERAGE,
    }:
        raise ValueError(f"unsupported transaction coverage contract: {coverage_contract}")
    if candidate_key not in {"v4", "v5", "v6", "v7"}:
        raise ValueError(f"unsupported transaction candidate key: {candidate_key}")
    if int(candidate_confirmation_minutes) < 1:
        raise ValueError("candidate_confirmation_minutes must be positive")

    started = monotonic()
    timings: dict[str, float] = {}
    checkpoint = started
    pairs, pair_audit = preboard_transaction_data.resolve_shared_transaction_pairs(
        session_count=session_count,
        freeze_manifest=False,
    )
    checkpoint = _record_timing(timings, "pair_manifest_seconds", checkpoint)
    if not pairs or str(pair_audit.get("status") or "") != "ready":
        return _blocked_report(
            "blocked_by_pair_manifest",
            session_count,
            timings,
            study_version=study_version,
        )

    manifest = load_static_hazard_manifest(session_count=session_count)
    checkpoint = _record_timing(timings, "manifest_seconds", checkpoint)
    if manifest.empty:
        return _blocked_report(
            "blocked_by_manifest",
            session_count,
            timings,
            study_version=study_version,
        )
    start = legacy._as_date(manifest["trade_date"].min())
    end = legacy._as_date(manifest["trade_date"].max())
    manifest_parity = {
        "expected_pair_count": int(pair_audit.get("manifest_pair_count") or 0),
        "actual_pair_count": int(len(manifest)),
        "expected_start": pair_audit.get("start_date"),
        "actual_start": start.isoformat(),
        "expected_end": pair_audit.get("end_date"),
        "actual_end": end.isoformat(),
    }
    manifest_parity["passed"] = bool(
        manifest_parity["expected_pair_count"] == manifest_parity["actual_pair_count"]
        and manifest_parity["expected_start"] == manifest_parity["actual_start"]
        and manifest_parity["expected_end"] == manifest_parity["actual_end"]
    )
    if manifest_parity["passed"] is not True:
        return {
            **_blocked_report(
                "blocked_by_manifest_parity",
                session_count,
                timings,
                study_version=study_version,
            ),
            "manifest_parity": manifest_parity,
        }

    coverage = load_one_minute_coverage(manifest)
    coverage_report = legacy._coverage_report(manifest, coverage)
    checkpoint = _record_timing(timings, "coverage_seconds", checkpoint)
    if float(coverage_report["complete_pair_pct"]) < 100.0:
        return {
            **_blocked_report(
                "blocked_by_one_minute_coverage",
                session_count,
                timings,
                study_version=study_version,
            ),
            "coverage": coverage_report,
        }
    dates = sorted(pd.to_datetime(manifest["trade_date"]).dt.date.unique())
    fit_dates, calibration_dates, validation_dates = legacy.split_competing_dates(dates)
    if (
        len(fit_dates) != legacy.FIT_SESSION_COUNT
        or len(calibration_dates) != legacy.CALIBRATION_SESSION_COUNT
        or len(validation_dates) != legacy.VALIDATION_SESSION_COUNT
    ):
        return _blocked_report(
            "blocked_by_frozen_date_split",
            session_count,
            timings,
            study_version=study_version,
        )

    pair_set = set(pairs)
    scoped_manifest = manifest.loc[
        [
            (str(row.vt_symbol), legacy._as_date(row.trade_date)) in pair_set
            for row in manifest.itertuples()
        ]
    ].copy()
    if len(scoped_manifest) != len(pair_set):
        return _blocked_report(
            "blocked_by_scoped_manifest",
            session_count,
            timings,
            study_version=study_version,
        )
    minute_rows = load_one_minute_bars(scoped_manifest)
    daily_consistency = legacy.audit_minute_daily_consistency(
        scoped_manifest,
        minute_rows,
    )
    checkpoint = _record_timing(timings, "minute_load_audit_seconds", checkpoint)
    if float(daily_consistency["ready_pair_pct"]) < 100.0:
        return {
            **_blocked_report(
                "blocked_by_minute_daily_inconsistency",
                session_count,
                timings,
                study_version=study_version,
            ),
            "minute_daily_consistency": daily_consistency,
        }

    feature_frame, feature_coverage = legacy._load_bounded_feature_frame(
        manifest,
        lookback_sessions=legacy.FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = legacy._feature_index(feature_frame, set(dates))
    financial_index = legacy._load_financial_index()
    checkpoint = _record_timing(timings, "feature_seconds", checkpoint)
    prefix_rows, filter_audit = legacy._build_all_strategy_prefix_rows(
        scoped_manifest,
        minute_rows,
        pair_set,
        feature_by_pair,
        financial_index,
        bar_minutes=1,
        passed_only=True,
        row_projection=legacy._project_competing_row,
    )
    expected_prefix_count = int(
        _mapping(pair_audit.get("filter_audit")).get("shared_prefix_count") or 0
    )
    prefix_parity = {
        "expected_pair_count": len(pair_set),
        "actual_pair_count": len(
            {(str(row.get("vt_symbol") or ""), legacy._order_date(row)) for row in prefix_rows}
        ),
        "expected_prefix_count": expected_prefix_count,
        "actual_prefix_count": len(prefix_rows),
    }
    prefix_parity["passed"] = bool(
        prefix_parity["expected_pair_count"] == prefix_parity["actual_pair_count"]
        and prefix_parity["expected_prefix_count"] == prefix_parity["actual_prefix_count"]
    )
    checkpoint = _record_timing(timings, "prefix_build_seconds", checkpoint)
    if prefix_parity["passed"] is not True:
        return {
            **_blocked_report(
                "blocked_by_prefix_parity",
                session_count,
                timings,
                study_version=study_version,
            ),
            "prefix_parity": prefix_parity,
        }

    transaction_scope = preboard_transaction_repository.load_transaction_feature_coverage(
        pairs,
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    transaction_rows = preboard_transaction_repository.load_transaction_features(
        pairs,
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    if coverage_contract == STRICT_V4_COVERAGE:
        joined_rows, join_audit = join_transaction_features(
            prefix_rows,
            transaction_rows,
        )
    else:
        pending_pairs = {
            (
                str(row.get("vt_symbol") or ""),
                legacy._as_date(row.get("trade_date")),
            )
            for row in transaction_scope.get("pending_pairs") or []
            if isinstance(row, Mapping)
        }
        ready_pairs = pair_set - pending_pairs
        joined_rows, join_audit = (
            preboard_transaction_disposition.classify_transaction_prefixes(
                prefix_rows,
                transaction_rows,
                ready_pairs=ready_pairs,
            )
        )
    transaction_coverage = {
        "requested_pair_count": int(transaction_scope.get("requested_pair_count") or 0),
        "ready_pair_count": int(transaction_scope.get("ready_pair_count") or 0),
        "scope_ready_pair_pct": transaction_scope.get("ready_pair_pct"),
        **join_audit,
    }
    checkpoint = _record_timing(timings, "transaction_join_seconds", checkpoint)
    strict_coverage_failed = bool(
        coverage_contract == STRICT_V4_COVERAGE
        and (
            _number(transaction_coverage.get("scope_ready_pair_pct")) != 100.0
            or _number(transaction_coverage.get("scoreable_prefix_pct")) != 100.0
        )
    )
    disposition_gate = (
        preboard_transaction_disposition.build_disposition_coverage_checks(
            transaction_coverage
        )
        if coverage_contract == EXPLICIT_NO_ACTION_V5_COVERAGE
        else {"passed": True, "checks": {}}
    )
    disposition_coverage_failed = bool(
        coverage_contract == EXPLICIT_NO_ACTION_V5_COVERAGE
        and (
            _number(transaction_coverage.get("scope_ready_pair_pct")) != 100.0
            or disposition_gate.get("passed") is not True
        )
    )
    if strict_coverage_failed or disposition_coverage_failed:
        return _coverage_rejection_report(
            session_count=session_count,
            timings=timings,
            transaction_coverage=transaction_coverage,
            study_version=study_version,
            coverage_checks=_mapping(disposition_gate.get("checks")),
        )

    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        False,
    )
    scoped_history_days = [
        day
        for day in history_days
        if start <= (legacy._optional_date(day.get("trade_date")) or date.min) <= end
    ]
    formal_orders, profitability_audit = legacy._formal_orders(
        history_days,
        scoped_history_days,
        start,
        end,
    )
    symbols = sorted(
        {
            *(symbol for symbol, _ in pair_set),
            *(
                str(order.get("vt_symbol") or "")
                for order in formal_orders
                if order.get("vt_symbol")
            ),
        }
    )
    result_dates = [
        parsed
        for value in scoped_manifest.get("result_date", [])
        if (parsed := legacy._optional_date(value)) is not None
    ]
    result_dates.extend(
        parsed
        for order in formal_orders
        if (parsed := legacy._optional_date(order.get("result_date"))) is not None
    )
    account_end = max(result_dates, default=end)
    bars = history_repository.load_account_daily_bars(symbols, start, account_end)
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        load_reliable_trade_dates,
    )

    trade_dates = load_reliable_trade_dates(start, account_end)
    checkpoint = _record_timing(timings, "account_data_seconds", checkpoint)
    from alphaagent.server.services.limit_up.history_service import (
        get_scheduled_history_backtest,
    )

    service_baseline = get_scheduled_history_backtest(start, end, trade_limit=None)
    baseline_summary = legacy._account_summary(
        formal_orders,
        bars,
        trade_dates,
        cost_multiplier=1.0,
    )
    baseline_parity = legacy.compare_baseline_summaries(
        _mapping(service_baseline.get("summary")),
        baseline_summary,
    )
    checkpoint = _record_timing(timings, "baseline_seconds", checkpoint)
    if baseline_parity.get("passed") is not True:
        return {
            **_blocked_report(
                "blocked_by_baseline_mismatch",
                session_count,
                timings,
                study_version=study_version,
            ),
            "baseline_parity": baseline_parity,
        }

    v3_analysis, v3_models = v3.build_joint_trigger_analysis(
        joined_rows,
        formal_orders,
        bars,
        trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
        baseline_parity=baseline_parity,
    )
    v3_reference_parity = _v3_reference_parity(v3_analysis)
    analysis_builder = candidate_analysis_builder or build_transaction_trigger_analysis
    v4_analysis, v4_models, v4_artifacts = analysis_builder(
        joined_rows,
        formal_orders,
        bars,
        trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
        baseline_parity=baseline_parity,
        v3_reference_parity=v3_reference_parity,
        transaction_coverage=transaction_coverage,
        coverage_contract=coverage_contract,
    )
    v3_artifacts = _build_v3_artifacts(
        joined_rows,
        formal_orders,
        v3_models,
        _number(_mapping(v3_analysis.get("threshold_selection")).get("threshold"))
        or 1.1,
    )
    incremental = _incremental_attribution(
        formal_orders=formal_orders,
        v3_artifacts=v3_artifacts,
        v4_artifacts=v4_artifacts,
        bars=bars,
        trade_dates=trade_dates,
        validation_dates=set(validation_dates),
    )
    disposition_attribution: dict[str, object] = {}
    if coverage_contract == EXPLICIT_NO_ACTION_V5_COVERAGE:
        validation_set = set(validation_dates)
        formal_scope = legacy._orders_on_dates(formal_orders, validation_set)
        formal_identity_pairs = {
            legacy._order_pair(order)
            for order in formal_scope
            if str(order.get("lane") or "") == "first_board"
        }
        formal_account = legacy.replay_competing_account(
            formal_scope,
            bars,
            trade_dates,
        )
        disposition_attribution = (
            preboard_transaction_disposition.build_causal_no_action_attribution(
                joined_rows,
                validation_dates=validation_set,
                formal_identity_pairs=formal_identity_pairs,
                original_account_pairs=legacy._filled_first_board_pairs(formal_account),
            )
        )
    distributions = _transaction_feature_distributions(
        joined_rows,
        {
            "fit": set(fit_dates),
            "calibration": set(calibration_dates),
            "validation": set(validation_dates),
        },
    )
    checkpoint = _record_timing(timings, "model_and_replay_seconds", checkpoint)
    timings["total_seconds"] = round(monotonic() - started, 3)
    date_split = {
        phase: {
            **legacy._date_range(values),
            "dates": [value.isoformat() for value in values],
        }
        for phase, values in (
            ("fit", fit_dates),
            ("calibration", calibration_dates),
            ("validation", validation_dates),
        )
    }
    fingerprints = {
        "pair_manifest": str(
            _mapping(pair_audit.get("pair_manifest")).get("input_fingerprint") or ""
        ),
        "transaction_inputs": _transaction_input_fingerprint(transaction_rows),
        "transaction_dispositions": _stable_fingerprint(
            [
                [
                    str(row.get("vt_symbol") or ""),
                    str(row.get("signal_date") or "")[:10],
                    str(row.get("signal_time") or "")[:5],
                    str(row.get("transaction_disposition") or ""),
                ]
                for row in joined_rows
            ]
        ),
        "v3": v3.build_research_fingerprints(
            date_split=date_split,
            models=_mapping(v3_analysis.get("models")),
            threshold_selection=_mapping(v3_analysis.get("threshold_selection")),
        ),
        candidate_key: v3.build_research_fingerprints(
            date_split=date_split,
            models=_mapping(v4_analysis.get("models")),
            threshold_selection=_mapping(v4_analysis.get("threshold_selection")),
            action_model_key=candidate_action_model_key,
            confirmation_minutes=candidate_confirmation_minutes,
        ),
        "validation_accounts": {
            "v3": _stable_fingerprint(
                _mapping(_mapping(v3_analysis.get("phases")).get("validation")).get(
                    "accounts"
                )
            ),
            candidate_key: _stable_fingerprint(
                _mapping(_mapping(v4_analysis.get("phases")).get("validation")).get(
                    "accounts"
                )
            ),
        },
    }
    acceptance = _mapping(v4_analysis.get("acceptance"))
    return {
        "study_version": study_version,
        "status": (
            "ready_historical_pass"
            if acceptance.get("passed") is True
            else "ready_historical_rejected"
        ),
        "decision": v4_analysis.get("decision"),
        "formal_strategy_changed": False,
        "historical_validation_kind": historical_validation_kind,
        "candidate_key": candidate_key,
        "candidate_label": candidate_label or f"{candidate_key}逐笔模型",
        "report_title": (
            "首板逐笔三态触发 v5 研究"
            if candidate_key == "v5"
            else "首板逐笔触板时序 v6 研究"
            if candidate_key == "v6"
            else "首板事件竞争风险 v7 研究"
            if candidate_key == "v7"
            else "首板逐笔资金流提前触发 v4 研究"
        ),
        "contract": {
            "observation_gain_operator": ">=",
            "observation_gain_pct": 3.0,
            "core_features": list(legacy.COMPETING_FEATURE_NAMES),
            "transaction_features": list(TRANSACTION_FEATURE_NAMES),
            "transaction_feature_version": TRANSACTION_FEATURE_VERSION,
            "confirmation_minutes": int(candidate_confirmation_minutes),
            "maximum_daily_first_board_actions": v3.MAX_DAILY_FIRST_BOARD_ACTIONS,
            "entry": "next_one_minute_open_strictly_below_limit",
            "exit": "d1_official_close",
            "execution_effect": "none_research_only",
            "coverage_contract": coverage_contract,
        },
        "date_split": date_split,
        "research_fingerprints": fingerprints,
        "performance": timings,
        "manifest_parity": manifest_parity,
        "prefix_parity": prefix_parity,
        "coverage": {**coverage_report, **feature_coverage},
        "minute_daily_consistency": daily_consistency,
        "transaction_coverage": transaction_coverage,
        "filter_audit": filter_audit,
        "formal_profitability_filter": profitability_audit,
        "baseline_parity": baseline_parity,
        "v3_reference_parity": v3_reference_parity,
        "v3": v3_analysis,
        candidate_key: v4_analysis,
        "incremental_attribution": incremental,
        "causal_no_action_attribution": disposition_attribution,
        "transaction_feature_distributions": distributions,
        "acceptance": acceptance,
        "forward_validation": {
            "status": (
                "collecting_forward_transaction_overlay"
                if acceptance.get("passed") is True
                else "not_promoted_historical_rejected"
            ),
            "trade_day_count": 0,
            "closed_action_event_count": 0,
            "execution_effect": "none_research_only",
        },
        "limitations": [
            "后30日已经被此前研究查看，只能称扩展历史时间反证，不是新的锁定留出。",
            "TDX逐笔是成交记录，不包含委托队列、撤单和封单排队。",
            "buyorsell枚举缺少可信公开语义，方向特征只使用direction_0/1中性名称。",
            "历史通过也只允许冻结前向影子；正式v9/v15保持不变。",
        ],
    }


def _build_v3_artifacts(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    models: Mapping[str, object],
    threshold: float,
) -> dict[str, object]:
    identity = attach_competing_risk_targets(rows, formal_orders)
    labeled = attach_joint_trigger_targets(identity, formal_orders)
    enriched = enrich_same_minute_competition(labeled)
    action_model = models.get("joint_action_3m")
    scored = score_joint_trigger_rows(enriched, action_model)
    bundle = v3.build_joint_replay_orders(
        action_rows=scored,
        formal_orders=formal_orders,
        action_threshold=threshold,
    )
    return {
        "action_rows": scored,
        "action_signals": bundle["action_signals"],
        "combined_orders": bundle["combined_orders"],
    }


def _incremental_attribution(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    v3_artifacts: Mapping[str, object],
    v4_artifacts: Mapping[str, object],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    validation_dates: set[date],
) -> dict[str, object]:
    formal_scope = legacy._orders_on_dates(formal_orders, validation_dates)
    formal_account = legacy.replay_competing_account(formal_scope, bars, trade_dates)
    original_pairs = legacy._filled_first_board_pairs(formal_account)
    v3_pairs = {
        legacy._order_pair(row)
        for row in v3_artifacts.get("action_signals") or []
        if legacy._order_date(row) in validation_dates
    }
    v4_pairs = {
        legacy._order_pair(row)
        for row in v4_artifacts.get("action_signals") or []
        if legacy._order_date(row) in validation_dates
    }
    categories = {
        "v3_false_momentum_removed_by_v4": (v3_pairs - original_pairs) - v4_pairs,
        "v3_original_account_identity_retained": v3_pairs & v4_pairs & original_pairs,
        "v3_original_account_identity_killed_by_v4": (v3_pairs & original_pairs) - v4_pairs,
        "v4_new_original_account_identity": (v4_pairs - v3_pairs) & original_pairs,
        "v4_new_false_positive": (v4_pairs - v3_pairs) - original_pairs,
    }
    return {
        "validation_original_account_pair_count": len(original_pairs),
        "v3_signal_pair_count": len(v3_pairs),
        "v4_signal_pair_count": len(v4_pairs),
        "categories": {
            name: {
                "pair_count": len(pairs),
                "pairs": [
                    {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
                    for symbol, trade_date in sorted(pairs)
                ],
            }
            for name, pairs in categories.items()
        },
    }


def _transaction_feature_distributions(
    rows: Sequence[Mapping[str, object]],
    phase_dates: Mapping[str, set[date]],
) -> dict[str, object]:
    report: dict[str, object] = {}
    for phase, allowed_dates in phase_dates.items():
        phase_rows = [
            row for row in rows if legacy._order_date(row) in allowed_dates
        ]
        report[phase] = {
            name: _distribution(
                [
                    value
                    for row in phase_rows
                    if isinstance(row.get("transaction_features"), Mapping)
                    and (
                        value := _number(
                            _mapping(row.get("transaction_features")).get(name)
                        )
                    )
                    is not None
                ]
            )
            for name in TRANSACTION_FEATURE_NAMES
        }
    return report


def _distribution(values: Sequence[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "mean": None, "p25": None, "median": None, "p75": None}
    array = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "mean": round(float(np.mean(array)), 8),
        "p25": round(float(np.percentile(array, 25)), 8),
        "median": round(float(np.percentile(array, 50)), 8),
        "p75": round(float(np.percentile(array, 75)), 8),
    }


def _v3_reference_parity(analysis: Mapping[str, object]) -> dict[str, object]:
    models = _mapping(analysis.get("models"))
    prepare = _mapping(models.get("prepare_5m"))
    action = _mapping(models.get("joint_action_3m"))
    threshold = _mapping(analysis.get("threshold_selection")).get("threshold")
    checks = {
        "prepare_model_fingerprint": (
            prepare.get("fingerprint") == V3_REFERENCE_PREPARE_FINGERPRINT
        ),
        "action_model_fingerprint": (
            action.get("fingerprint") == V3_REFERENCE_ACTION_FINGERPRINT
        ),
        "action_threshold": _number(threshold) == V3_REFERENCE_ACTION_THRESHOLD,
        "candidate_pair_count": (
            _number(_mapping(analysis.get("dataset")).get("candidate_pair_count"))
            == 962
        ),
        "observable_prefix_count": (
            _number(_mapping(analysis.get("dataset")).get("observable_prefix_count"))
            == 22_821
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "expected": {
            "prepare_model_fingerprint": V3_REFERENCE_PREPARE_FINGERPRINT,
            "action_model_fingerprint": V3_REFERENCE_ACTION_FINGERPRINT,
            "action_threshold": V3_REFERENCE_ACTION_THRESHOLD,
        },
    }


def _model_report(model: TransactionTriggerModelFit) -> dict[str, object]:
    return {
        "status": model.status,
        "target_field": model.target_field,
        "feature_version": model.feature_version,
        "features": list(TRANSACTION_TRIGGER_FEATURE_NAMES),
        "transaction_features": list(model.transaction_feature_names),
        "training_row_count": model.training_row_count,
        "training_pair_count": model.training_pair_count,
        "class_counts": dict(model.class_counts),
        "fit_dates": list(model.fit_dates),
        "scaler_mean_by_feature": dict(model.scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(model.scaler_scale_by_feature),
        "coefficient_by_feature": dict(model.coefficient_by_feature),
        "intercept": model.intercept,
        "fingerprint": model.fingerprint,
    }


def _alias_v4_action_score(row: Mapping[str, object]) -> dict[str, object]:
    return {
        **dict(row),
        V3_ACTION_SCORE_FIELD: row.get(TRANSACTION_ACTION_SCORE_FIELD),
    }


def _transaction_key(row: Mapping[str, object]) -> tuple[str, date, str]:
    value = row.get("bar_time")
    bar_time = _as_datetime(value)
    if bar_time is None:
        raise ValueError("transaction feature bar_time is invalid")
    return (
        str(row.get("vt_symbol") or ""),
        legacy._as_date(row.get("trade_date")),
        bar_time.strftime("%H:%M"),
    )


def _prefix_key(row: Mapping[str, object]) -> tuple[str, date, str]:
    return (
        str(row.get("vt_symbol") or ""),
        legacy._order_date(row),
        str(row.get("signal_time") or "")[:5],
    )


def _valid_transaction_values(values: Mapping[str, object]) -> bool:
    return all(_number(values.get(name)) is not None for name in TRANSACTION_FEATURE_NAMES)


def _transaction_input_fingerprint(
    rows: Sequence[Mapping[str, object]],
) -> str:
    payload = [
        [
            str(row.get("vt_symbol") or ""),
            str(row.get("trade_date") or "")[:10],
            str(row.get("bar_time") or ""),
            str(row.get("input_fingerprint") or ""),
        ]
        for row in rows
    ]
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=False).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _stable_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _record_timing(timings: dict[str, float], field: str, started: float) -> float:
    now = monotonic()
    timings[field] = round(now - started, 3)
    return now


def _blocked_report(
    status: str,
    session_count: int,
    timings: Mapping[str, float],
    *,
    study_version: str = STUDY_VERSION,
) -> dict[str, object]:
    return {
        "study_version": study_version,
        "status": status,
        "decision": "blocked_no_conclusion",
        "formal_strategy_changed": False,
        "requested_session_count": int(session_count),
        "performance": dict(timings),
    }


def _coverage_rejection_report(
    *,
    session_count: int,
    timings: Mapping[str, float],
    transaction_coverage: Mapping[str, object],
    study_version: str = STUDY_VERSION,
    coverage_checks: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Archive a pre-registered coverage failure without fitting any model."""

    scope_ready = (
        _number(transaction_coverage.get("scope_ready_pair_pct")) == 100.0
    )
    prefixes_ready = (
        _number(transaction_coverage.get("scoreable_prefix_pct")) == 100.0
    )
    contract_checks = (
        {str(name): bool(value) for name, value in coverage_checks.items()}
        if coverage_checks
        else {"transaction_prefix_coverage_100pct": prefixes_ready}
    )
    return {
        "study_version": study_version,
        "status": "ready_historical_rejected",
        "decision": "historical_rejected_no_live_promotion",
        "formal_strategy_changed": False,
        "requested_session_count": int(session_count),
        "performance": dict(timings),
        "transaction_coverage": dict(transaction_coverage),
        "model_evaluation_status": "not_run_fail_closed_coverage",
        "acceptance": {
            "passed": False,
            "checks": {
                "transaction_scope_coverage_100pct": scope_ready,
                **contract_checks,
                "historical_model_evaluation_completed": False,
            },
            "rejection_reason": "pre_registered_transaction_coverage_gate_failed",
        },
        "forward_validation": {
            "status": "not_started_historical_rejected",
            "trade_day_count": 0,
            "closed_action_event_count": 0,
        },
        "limitations": [
            "v4要求逐笔分钟前缀100%可评分；覆盖门失败后未拟合、校准或查看验证收益。",
            "正式limit-up-scheduled-v9、limit-up-live-v15、公开排序和自动动作未改变。",
        ],
    }


def render_transaction_trigger_markdown(report: Mapping[str, object]) -> str:
    """Render the decisive v3/v4 same-account comparison."""

    candidate_key = str(report.get("candidate_key") or "v4")
    candidate_label = str(report.get("candidate_label") or "v4逐笔模型")
    lines = [
        f"# {report.get('report_title') or '首板逐笔资金流提前触发 v4 研究'}",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision')}`。",
        f"- 研究版本：`{report.get('study_version')}`；正式策略修改：`False`。",
    ]
    coverage = _mapping(report.get("transaction_coverage"))
    lines.append(
        "- 逐笔覆盖：股票日 "
        f"{coverage.get('ready_pair_count', 0)}/{coverage.get('requested_pair_count', 0)}；"
        f"分钟前缀 {coverage.get('scoreable_prefix_count', 0)}/{coverage.get('prefix_count', 0)}。"
    )
    lines.extend(["", "## Same-account validation", ""])
    if report.get("model_evaluation_status") != "not_run_fail_closed_coverage":
        lines.append("| 方案 | 信号 | 原账户身份精度 | 原账户召回 | 成交 | 胜率 | 复利 | 回撤 | PF |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for key, label in (("v3", "v3分钟模型"), (candidate_key, candidate_label)):
            analysis = _mapping(report.get(key))
            validation = _mapping(_mapping(analysis.get("phases")).get("validation"))
            identity = _mapping(validation.get("identity"))
            account_identity = _mapping(validation.get("account_identity"))
            account = _mapping(_mapping(validation.get("accounts")).get("joint_action"))
            lines.append(
                f"| {label} | {identity.get('selection_count', 0)} | "
                f"{_pct(account_identity.get('precision_pct'))} | "
                f"{_pct(account_identity.get('recall_pct'))} | "
                f"{account.get('trade_count', 0)} | {_pct(account.get('win_rate'))} | "
                f"{_signed_pct(account.get('total_return_pct'))} | "
                f"{_signed_pct(account.get('max_drawdown_pct'))} | "
                f"{_display(account.get('profit_factor'))} |"
            )
    else:
        lines.append("- 覆盖门失败后按 fail-closed 合同停止；v3/v4 模型和账户均未运行。")
    candidate_analysis = _mapping(report.get(candidate_key))
    lines.extend(["", "## Validation blocks", ""])
    lines.append("| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for raw in candidate_analysis.get("validation_blocks") or []:
        block = _mapping(raw)
        date_range = _mapping(block.get("date_range"))
        identity = _mapping(block.get("identity"))
        account = _mapping(_mapping(block.get("accounts")).get("joint_action"))
        lines.append(
            f"| {block.get('block')} | {date_range.get('start')}..{date_range.get('end')} | "
            f"{identity.get('selection_count', 0)} | {account.get('trade_count', 0)} | "
            f"{_pct(account.get('win_rate'))} | "
            f"{_signed_pct(account.get('total_return_pct'))} | "
            f"{_signed_pct(account.get('max_drawdown_pct'))} |"
        )
    lines.extend(["", "## Incremental attribution", ""])
    categories = _mapping(_mapping(report.get("incremental_attribution")).get("categories"))
    for name, value in categories.items():
        lines.append(f"- `{name}`：{_mapping(value).get('pair_count', 0)} 个股票日。")
    no_action = _mapping(report.get("causal_no_action_attribution"))
    if no_action:
        lines.extend(["", "## Causal no-action attribution", ""])
        lines.append(
            f"- 全样本 {no_action.get('minute_count', 0)} 个分钟、"
            f"{no_action.get('pair_count', 0)} 个股票日；验证段 "
            f"{no_action.get('validation_minute_count', 0)} 个分钟、"
            f"{no_action.get('validation_pair_count', 0)} 个股票日。"
        )
        lines.append(
            "- 验证段与正式候选身份交集 "
            f"{no_action.get('validation_formal_identity_intersection_count', 0)}；"
            "与原两仓实际成交身份交集 "
            f"{no_action.get('validation_original_account_intersection_count', 0)}。"
        )
    lines.extend(["", "## Decision", ""])
    acceptance = _mapping(report.get("acceptance"))
    lines.append(f"- 历史门禁：`{'PASS' if acceptance.get('passed') else 'FAIL'}`。")
    for name, passed in _mapping(acceptance.get("checks")).items():
        lines.append(f"- `{name}`：{'通过' if passed else '未通过'}。")
    lines.extend(["", "## Forward validation", ""])
    forward = _mapping(report.get("forward_validation"))
    lines.append(
        f"- 状态：`{forward.get('status')}`；交易日 {forward.get('trade_day_count', 0)}，"
        f"闭合行动 {forward.get('closed_action_event_count', 0)}。"
    )
    limitations = [str(value) for value in report.get("limitations") or []]
    if limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {value}" for value in limitations)
    return "\n".join(lines) + "\n"


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "-"


def _pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.2f}%" if parsed is not None else "-"


def _signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}%" if parsed is not None else "-"


def _write_output(path_text: str, content: str) -> None:
    path = Path(path_text).resolve()
    evidence_root = (Path.cwd() / "memory" / "06_backtests").resolve()
    if evidence_root not in path.parents:
        raise ValueError("transaction-trigger report must stay under memory/06_backtests")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate transaction-flow v4 trigger")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="markdown",
    )
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_preboard_transaction_trigger(session_count=args.sessions)
    markdown = render_transaction_trigger_markdown(report)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.format == "both":
        if not args.output:
            raise ValueError("--output is required when --format=both")
        _write_output(f"{args.output}.md", markdown)
        _write_output(f"{args.output}.json", json_text)
        return
    content = json_text if args.format == "json" else markdown
    if args.output:
        _write_output(args.output, content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
